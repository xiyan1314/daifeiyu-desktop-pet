# -*- coding: utf-8 -*-
"""v2.10.0 发版轮（P4 · 配置与菜单）：C-13 三态 · D3 菜单去重 · D4 命名统一。

**领地**：只覆盖 `pet_config.py` 与 `pet_menu.py` 两个模块（其余模块一个字都不碰；
驱动用的是**真** `PetWindow` + 真 `MenuBuilder.open`，数据目录指到 tmp）。

三条各自的"为什么"：

  · **C-13（三态）**：原来每个无障碍开关只有**一个勾选框**——点过一次就写死 on/off，
    用户**再也回不到 auto**（只能手改 config.json），而"跟随系统"又只在建窗时读过一次。
    现在每个开关两条：开关本身（勾选＝**生效值**，点它＝显式 on/off）+
    「：跟随系统」（勾选＝配置值就是 auto，点它＝写回 auto）。
    三态的词表**只有** `pet_config.MOTION_MODES` 那一份（auto/on/off）。
  · **D3（去重）**：「🐟 角色 → 导入角色…」与顶层「📦 资源管理…」是**同一个调用**
    （`open_resource_manager(pet, 0)`，同一个页签），而前者文案承诺"导入"却只打开面板
    → 删掉子菜单里那条，保留顶层那条。**顶层 ≤18 项的硬断言不许破**（`_verify_green.py:86`
    / `_verify_v13.py:1632`），所以少一条不加一条。
  · **D4（命名）**：音效库的片段全仓叫**音效片段**（与「🎵 音效设置」子菜单、资源管理
    「音效」页签同一套词），"音频片段"退役——它和另一条「管理声音素材…」（去的是**另一个
    库**的页签）长得像同义词。本文件只钉菜单侧；另一侧（pet_dialogs.py）不归本包。

写法沿用仓内套路：offscreen；真 exec 换成"记录完就返回"；断言**结构性事实**
（哪个动作在哪个子菜单 / 勾选态 / 被调用的实参是哪个字符串），不看耗时。
"""
import io
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pet_config          # noqa: E402
import pet_log             # noqa: E402
import pet_resources       # noqa: E402

from PySide6.QtCore import QPoint                                    # noqa: E402
from PySide6.QtGui import QAction                                    # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu                    # noqa: E402

# 顶层菜单项数上限：与 _verify_green.py:86 / _verify_v13.py:1632 同一口径（**只许少，不许抬**）
TOP_LIMIT = 18


def _src(name):
    return io.open(os.path.join(ROOT, name), encoding="utf-8").read()


def _code_only(name):
    """剥掉 `#` 注释后的源码。

    注释里**可以**提旧词做说明（说明"这个词为什么退役"），代码里不许再有 ——
    计数与用词检查一律只看剥完的这一份，否则注释里的举例会把判据变成假红。
    """
    return "\n".join(line.split("#", 1)[0] for line in _src(name).split("\n"))


def _count_calls(needle, name="pet_menu.py"):
    return _code_only(name).count(needle)


# ============================================================
# 夹具：一个真 PetWindow（数据目录指到 tmp，退出时还原进程级全局）
# ============================================================

@pytest.fixture(scope="module")
def pet(tmp_path_factory):
    from PySide6.QtWidgets import QApplication as _QA
    if _QA.instance() is None:
        _QA([])
    import 桌宠 as main
    tmp = tmp_path_factory.mktemp("cfgmenu2100")
    _snap = (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
             getattr(pet_log, "_data_dir", None), getattr(main, "_redact_key", None),
             getattr(pet_resources, "FRAME_MAX", None))
    main.DATA_DIR = str(tmp)
    main.CONFIG_PATH = str(tmp / "config.json")
    main.USAGE_PATH = str(tmp / "usage.json")
    main.MEMORY_PATH = str(tmp / "memory.json")
    pet_log.set_data_dir(str(tmp))
    win = main.PetWindow()
    yield win
    try:
        from helpers_roles import shutdown_pet
        shutdown_pet(win)
    except Exception:
        pass  # 有意忽略：收尾尽力而为，不掩盖上面的断言结果
    QApplication.processEvents()
    (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH,
     main.MEMORY_PATH) = _snap[0], _snap[1], _snap[2], _snap[3]
    pet_log.set_data_dir(_snap[4])
    main.set_redact_key(_snap[5] or "")
    if _snap[6] is not None:
        pet_resources.FRAME_MAX = _snap[6]


def _capture(pet, monkeypatch):
    """走真 `MenuBuilder.open`（真 exec 换成"记录完就返回"）→ 菜单结构快照。

    快照里既有文本（层级关系），也留着 QAction 本体（点击类用例直接 trigger，
    断言的是**接线**而不是"文本看着对"）。
    """
    snap = {}

    class _CapMenu(QMenu):
        def exec(self, *_a, **_k):        # noqa: A003 —— Qt 的名字
            snap["top"] = [a.text() for a in self.actions() if a.text()]
            snap["all"] = [a.text() for a in self.findChildren(QAction) if a.text()]
            set_act = next((a for a in self.actions() if a.text().startswith("⚙️ 设置")), None)
            sub = set_act.menu() if set_act is not None else None
            snap["set"] = [a.text() for a in sub.actions() if a.text()] if sub is not None else []
            snap["acts"] = {a.text(): a for a in self.findChildren(QAction) if a.text()}
            return None

    monkeypatch.setattr(pet, "_new_menu", lambda: _CapMenu(pet))
    pet.menu_builder.open(QPoint(10, 10))
    return snap


# ============================================================
# C-13 配置侧：三态词表只有一份，坏值一律回 auto
# ============================================================

def test_三态词表只有一份_auto_on_off():
    """词表的单一来源在 pet_config；别处（菜单/桌宠）只许用它，不许再造一套字符串。"""
    assert pet_config.MOTION_MODES == ("auto", "on", "off"), pet_config.MOTION_MODES
    assert pet_config.MOTION_MODE_KEYS == ("reduce_motion", "high_contrast"), \
        pet_config.MOTION_MODE_KEYS
    for good in ("auto", "on", "off", "ON", " off ", "Auto"):
        want = good.strip().lower()
        assert pet_config.normalize_motion_mode(good) == want, good
    # 坏值一律回 auto（**不是** off：不擅自替用户做无障碍决定）
    for bad in (None, "", "   ", [], {}, 123, True, False, "true", "1", "yes", "always",
                "system", "跟随系统"):
        assert pet_config.normalize_motion_mode(bad) == "auto", bad
        assert pet_config.is_auto_motion_mode(bad) is True, bad
    for explicit in ("on", "off"):
        assert pet_config.is_auto_motion_mode(explicit) is False, explicit


def test_normalize_cfg_把两个无障碍键归一成三态():
    """C-13 配置侧：手改 config.json 塞任何东西，两个键回来都必须是词表里的三个值之一。

    这条与 tests/test_config_robustness.py 的分工：那边走**真 load_config**（整条链路 + 类型），
    这里直接钉**归一函数的取值域**（三态而不是"随便一个字符串"）。
    """
    for poison in (None, [], {}, 123, True, "true", "always", "乱七八糟", "ON", " off "):
        cfg = {"reduce_motion": poison, "high_contrast": poison}
        pet_config.normalize_cfg(cfg, {}, frozenset())
        for key in pet_config.MOTION_MODE_KEYS:
            assert cfg[key] in pet_config.MOTION_MODES, (poison, key, cfg[key])
        if poison in ("ON", " off "):
            assert cfg["reduce_motion"] == poison.strip().lower(), poison


# ============================================================
# C-13 菜单侧：三态入口 + 勾选态 + 写回的值
# ============================================================

def test_设置子菜单里两个开关各有跟随系统一条(pet, monkeypatch):
    """三态的第二条必须落在「⚙️ 设置…」里（不是顶层：顶层顶着 <=18 的硬断言）。"""
    monkeypatch.setattr(pet, "_reduce_motion", lambda: True)
    monkeypatch.setattr(pet, "_high_contrast", lambda: False)
    snap = _capture(pet, monkeypatch)
    for text in ("🌊 减少动效", "🔁 跟随系统（减少动效）", "🔲 高对比度", "🔁 跟随系统（高对比度）"):
        assert text in snap["set"], "设置子菜单里缺 %r：%r" % (text, snap["set"])
        assert text not in snap["top"], "%r 跑到顶层去了：%r" % (text, snap["top"])
        assert snap["acts"][text].isCheckable(), text


def test_跟随系统的勾选态读配置值_开关读生效值(pet, monkeypatch):
    """"跟随系统"的勾＝配置值就是 auto；开关本身的勾＝**生效值**（auto 时跟随系统）。

    两者不是同一个东西：生效值被钉成 True 时，配置写 on/off/auto 都不影响它 ——
    界面既不说谎（不把开着的显示成未勾选），也能看出当前处在哪一态。
    """
    monkeypatch.setattr(pet, "_reduce_motion", lambda: True)
    monkeypatch.setattr(pet, "_high_contrast", lambda: False)
    for raw, want_auto in (("on", False), ("off", False), ("auto", True),
                           ("莫名其妙", True), (None, True)):
        pet.cfg["reduce_motion"] = raw
        pet.cfg["high_contrast"] = raw
        snap = _capture(pet, monkeypatch)
        assert snap["acts"]["🔁 跟随系统（减少动效）"].isChecked() is want_auto, raw
        assert snap["acts"]["🔁 跟随系统（高对比度）"].isChecked() is want_auto, raw
        assert snap["acts"]["🌊 减少动效"].isChecked() is True, raw
        assert snap["acts"]["🔲 高对比度"].isChecked() is False, raw


def test_点跟随系统把_auto_写下去(pet, monkeypatch):
    """点「跟随系统」→ 落到 _set_* 的**实参就是 "auto"**（三态字符串，不是 True/False）。

    ⚠ 这条钉的是**菜单侧的接口契约**：桌宠._set_reduce_motion / _set_high_contrast 必须收
    三态字符串（"auto"/"on"/"off"），同时保持 True/False → on/off 的旧口径
    （tests/test_motion_v2110.py 仍按布尔调它们）。
    """
    seen = []
    monkeypatch.setattr(pet, "_set_reduce_motion", lambda v: seen.append(("rm", v)))
    monkeypatch.setattr(pet, "_set_high_contrast", lambda v: seen.append(("hc", v)))
    monkeypatch.setattr(pet, "_reduce_motion", lambda: True)
    monkeypatch.setattr(pet, "_high_contrast", lambda: False)
    snap = _capture(pet, monkeypatch)
    snap["acts"]["🔁 跟随系统（减少动效）"].trigger()
    snap["acts"]["🔁 跟随系统（高对比度）"].trigger()
    assert seen == [("rm", "auto"), ("hc", "auto")], seen

    # 反向对照：开关本身仍然按布尔走（显式 on/off），没被三态改掉
    seen.clear()
    snap["acts"]["🌊 减少动效"].trigger()
    assert seen == [("rm", False)], "开关本身的接线变了：%r" % (seen,)


# ============================================================
# D3：菜单去重（顶层 ≤18 项不许破）
# ============================================================

def test_顶层菜单项数不超过硬上限(pet, monkeypatch):
    """D3 的硬约束：**只能少，不能加**（_verify_green.py:86 / _verify_v13.py:1632）。"""
    snap = _capture(pet, monkeypatch)
    assert len(snap["top"]) <= TOP_LIMIT, \
        "顶层菜单超了 %d 项：%d 项 %r" % (TOP_LIMIT, len(snap["top"]), snap["top"])


def test_资源管理只剩一个入口(pet, monkeypatch):
    """「角色 → 导入角色…」与顶层「📦 资源管理…」是同一个调用 → 只留顶层那条。"""
    snap = _capture(pet, monkeypatch)
    assert "📦 资源管理…" in snap["top"], snap["top"]
    assert "导入角色…" not in snap["all"], "重复入口还在：%r" % (snap["all"],)
    # 删的**不能**是"角色包"那两条：它们是另一件事（导出/导入 .dfypet.zip）
    assert "📦 导出角色包…" in snap["all"] and "📦 导入角色包…" in snap["all"], snap["all"]
    # 结构性证据：通往「角色」页签（tab 0）的调用在菜单源码里只剩一处（剥注释后数）
    assert _count_calls("open_resource_manager(pet, 0)") == 1, _count_calls("open_resource_manager(pet, 0)")


def test_源码计数器与剥注释都有反例():
    """反例对照：计数器必须能给出 0 与非 0；"剥注释"必须真的剥（否则下面两条是空转）。"""
    assert _count_calls("open_resource_manager(pet, 1)") == 1, "计数器认不出真调用"
    assert _count_calls("open_resource_manager(pet, 2)") == 0, "计数把不存在的调用也数上了"
    # 剥注释这一步的反例就在 D4 那条注释里：注释**必须**能提旧词（说明它为什么退役），
    # 而代码里不许再有 —— 不剥的话下面那条"代码里没有旧词"必然假红。
    assert "音频片段" in _src("pet_menu.py"), "注释里的旧词说明没了（这条反例失去前提）"
    assert "音频片段" not in _code_only("pet_menu.py"), "剥注释没生效"


# ============================================================
# D4：命名统一（音效片段 / 声音素材 两套词，各指各的库）
# ============================================================

def test_菜单侧音效库的片段叫音效片段(pet, monkeypatch):
    """「管理音频片段…」退役 →「管理音效片段…」；目的地**不变**（资源管理 tab 1 = 音效）。"""
    snap = _capture(pet, monkeypatch)
    assert "管理音效片段…" in snap["all"], snap["all"]
    assert not [t for t in snap["all"] if "音频片段" in t], snap["all"]
    assert "音频片段" not in _code_only("pet_menu.py"), "菜单代码里还有旧词"
    assert _count_calls("open_resource_manager(pet, 1)") == 1, "目的地被改掉了"
