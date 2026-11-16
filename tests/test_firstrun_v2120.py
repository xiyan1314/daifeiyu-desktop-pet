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

    只看**代码**（AST 里的名字与字符串常量），不看源码字符串：注释里解释"以前是什么"是
    允许的，而 v2.12.0 旧版第一条读的是源码字符串 → 把调用注释掉仍然绿（遗留-13）。
    globals() 的两种写法都会落进字符串常量里，所以两条都查。
    """
    src = open(os.path.join(HERE, "桌宠.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    # ① 关窗路径必须真的做 `self.cfg.get("tray_tip_done") is not True` 比较；注释不算。
    #    还要**在真正会执行的函数里**（closeEvent）：三审实测过"把 if 改成 if True、再在
    #    一个永不调用的方法里放同一个比较"能骗过只查形状的版本。
    parent = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node

    def _enclosing_fn(node):
        cur = parent.get(node)
        while cur is not None and not isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            cur = parent.get(cur)
        return cur

    persisted = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or len(node.ops) != 1:
            continue
        if not isinstance(node.ops[0], ast.IsNot):
            continue
        left = node.left
        right = node.comparators[0]
        if not (isinstance(left, ast.Call) and isinstance(left.func, ast.Attribute)
                and left.func.attr == "get"):
            continue
        if not (left.args and isinstance(left.args[0], ast.Constant)
                and left.args[0].value == "tray_tip_done"):
            continue
        if isinstance(right, ast.Constant) and right.value is True:
            fn = _enclosing_fn(node)
            if fn is not None and fn.name == "closeEvent":
                persisted.append(node.lineno)
    assert persisted, "关窗提示没接落盘标记（self.cfg.get(\"tray_tip_done\") is not True）"
    # ② 老的进程级全局不许回来（名字 / 字符串常量两种写法都查）。
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    consts = {n.value for n in ast.walk(tree)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "_HIDE_TIP_SHOWN" not in names, "进程级全局 _HIDE_TIP_SHOWN 又回来了（重启就忘）"
    assert "_HIDE_TIP_SHOWN" not in consts, "globals()[\"_HIDE_TIP_SHOWN\"] 又回来了（重启就忘）"

def test_window_schedules_the_first_run_guide():
    """**接线判据**：窗口必须真的把 _first_run_guide 挂到定时器上。

    三审 P0-1 的实测：把 `桌宠.py` 那行 `QTimer.singleShot(2600, self, self._gslot("first_run",
    self._first_run_guide))` 整行删掉，17 条 D1 判据**全绿**——功能可以人间蒸发而门不动。
    本条读 AST 里所有 `*.singleShot(...)` 调用，要求其中**至少一个**的参数里出现
    `_first_run_guide`；删掉那行 → 当场红。
    """
    src = open(os.path.join(HERE, "桌宠.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Attribute) and fn.attr == "singleShot":
            if "_first_run_guide" in ast.unparse(node):
                hits.append(node.lineno)
    assert hits, "窗口里没有任何地方调度 _first_run_guide —— D1 首次引导等于没做"


def test_existing_config_marks_an_old_user_as_done(tmp_path, monkeypatch):
    """老用户升级不许被"第一次见～"再问一次（三审 P1-9）。

    判据：磁盘上**已经有** config.json（而且没有这两个键）→ load_config 必须补成 True。
    把 `load_config` 里那两行迁移删掉 → 本条红。
    """
    import json
    import 桌宠 as main
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"schema_version": main.CONFIG_SCHEMA_VERSION, "sound": False}),
                 encoding="utf-8")
    monkeypatch.setattr(main, "CONFIG_PATH", str(p))
    cfg = main.load_config()
    assert cfg["first_run_done"] is True, "老用户升级后仍会被弹一次首次引导"
    assert cfg["tray_tip_done"] is True, "老用户关窗还会再看一遍托盘提示"


def test_first_install_has_not_run_yet(tmp_path, monkeypatch):
    """真·首启（config.json 还不存在）：两个标记都必须是 False（否则引导永远不弹）。"""
    import 桌宠 as main
    monkeypatch.setattr(main, "CONFIG_PATH", str(tmp_path / "config.json"))
    cfg = main.load_config()
    assert cfg["first_run_done"] is False
    assert cfg["tray_tip_done"] is False

