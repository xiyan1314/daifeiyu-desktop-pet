# -*- coding: utf-8 -*-
"""D1 首次引导 + 关窗提示的钉子（v2.12.0 第 12 轮）。

## 为什么需要这两颗钉子

v2.11.0 的"关窗收进托盘"提示靠模块级全局 `_HIDE_TIP_SHOWN` —— **重启就忘**，
于是每次首启都会弹；D1 首次引导则完全没做。本轮把两件事都换成**落盘**的一次性标记
（`first_run_done` / `tray_tip_done`），并在 pet_first_run 里把判定拆成可注入的三段。

## 每条能真失败在哪

- 把 guide() 改成"每次都弹"（去掉 should_guide 早退）→ test_guide_fires_only_once 红；
- 把 mark_done 挪到 show 之后（落盘/展示失败就回滚）→ 落盘失败那条与"只弹一次"那条都会红；
- 把 `is not True` 放宽成真值判断（"true"/1 也算已引导）→ test_bad_value_is_not_done 红；
- 把 tray_tip_done 改回 `_HIDE_TIP_SHOWN` 全局 → test_tray_tip_is_persisted 红；
- 从 DEFAULT_CONFIG 删掉这两个键（加载白名单）→ test_defaults_are_declared 红，
  而且 normalize 那条也会红（键不在 defaults 里会被丢弃）。
"""
import ast
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import pet_config  # noqa: E402
import pet_first_run  # noqa: E402


def test_guide_fires_only_once_per_cfg():
    cfg = {}
    shown = []

    def save(_c):
        return None

    def show(text):
        shown.append(text)
        return True

    assert pet_first_run.guide(cfg, save, show) == (True, None)
    assert pet_first_run.guide(cfg, save, show) == (False, None)
    assert cfg["first_run_done"] is True
    assert len(shown) == 1, "同一次运行里弹了 %d 次引导" % len(shown)


def test_marker_is_saved_before_the_bubble():
    """落盘拿到的必须是"已置真"的那份 cfg（顺序反了：崩在中间就永远引导）。"""
    cfg = {}
    seen = []

    def save(c):
        seen.append(dict(c))
        return None

    pet_first_run.guide(cfg, save, lambda _t: True)
    assert seen and seen[0]["first_run_done"] is True


def test_save_failure_still_only_one_bubble():
    """落盘失败：返回原因、不回滚、同一次运行里**不再弹第二次**。"""
    cfg = {}
    shown = []

    def boom(_c):
        raise OSError("disk full")

    shown_flag, err = pet_first_run.guide(cfg, boom, lambda t: shown.append(t) or True)
    assert shown_flag is True
    assert err and "落盘失败" in err
    assert cfg["first_run_done"] is True, "落盘失败不该回滚标记（否则同一次运行里反复弹）"
    assert pet_first_run.guide(cfg, boom, lambda t: shown.append(t) or True) == (False, None)
    assert len(shown) == 1


def test_show_failure_is_reported_but_marks_done():
    """气泡抛异常：不许带崩启动，标记照样置真（用户下次启动不会错过第二次）。"""
    cfg = {}

    def boom_show(_t):
        raise RuntimeError("no screen")

    ok, err = pet_first_run.guide(cfg, lambda _c: None, boom_show)
    assert ok is False
    assert err and "气泡失败" in err
    assert cfg["first_run_done"] is True


@pytest.mark.parametrize("bad", ["true", 1, None, [], {"x": 1}])
def test_bad_value_is_not_done(bad):
    """只认归一化之后的 True：原始坏值一律当"还没引导过"（宁可多弹一次）。"""
    assert pet_first_run.should_guide({"first_run_done": bad}) is True


def test_defaults_are_declared():
    import 桌宠 as main
    assert main.DEFAULT_CONFIG["first_run_done"] is False
    assert main.DEFAULT_CONFIG["tray_tip_done"] is False


@pytest.mark.parametrize("bad", ["true", 1, None, [], {"x": 1}, 2])
def test_normalized_config_turns_the_markers_into_bools(bad):
    """手改 config.json 塞毒值：归一化后类型必须仍然 bool（与其它开关同一条口径）。"""
    import 桌宠 as main
    cfg = dict(main.DEFAULT_CONFIG)
    cfg["first_run_done"] = bad
    cfg["tray_tip_done"] = bad
    pet_config.normalize_cfg(cfg, main.DEFAULT_CONFIG, set())
    assert isinstance(cfg["first_run_done"], bool)
    assert isinstance(cfg["tray_tip_done"], bool)


def test_tray_tip_is_persisted_not_a_process_global():
    """关窗提示只许用配置里的一次性标记 —— 老的进程级全局不许再回来。

    只看**代码**（AST 里的名字与字符串常量），不看注释：注释里解释"以前是什么"是允许的。
    globals() 的两种写法都会落进字符串常量里，所以两条都查。
    """
    src = open(os.path.join(HERE, "桌宠.py"), encoding="utf-8").read()
    assert 'self.cfg.get("tray_tip_done") is not True' in src, "关窗提示没接落盘标记"
    tree = ast.parse(src)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    consts = {n.value for n in ast.walk(tree)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "_HIDE_TIP_SHOWN" not in names, "进程级全局 _HIDE_TIP_SHOWN 又回来了（重启就忘）"
    assert "_HIDE_TIP_SHOWN" not in consts, "globals()[\"_HIDE_TIP_SHOWN\"] 又回来了（重启就忘）"
