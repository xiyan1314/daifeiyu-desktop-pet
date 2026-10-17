# -*- coding: utf-8 -*-
"""v2.11.0 发版轮 · P7 工作包（桌宠.py + pet_anim.py）的判据。

覆盖四条条目（条目定义见 _dev/REMAINING.md）：

· **C-13「跟随系统」接线**：reduce_motion / high_contrast 是**三态** auto / on / off，
  字符串与配置归一化认的那三个**逐字相同**（不另造字符串）；传 "auto" 时**重新读一次**
  系统设置（不是沿用建窗时那份缓存），且"回到 auto"这条路在菜单里真的点得到
  （托盘菜单的「跟随系统（…）」项）；
· **D1 角色素材帧纳入「减少动效」（折中：放慢帧率、不停帧）**：帧率倍率的真源是
  pet_motion.frame_rate_factor（关 1.0 / 开 0.5），**五条**角色素材帧播放路径都带这个
  令牌（桌宠.py 四条字面帧集 + pet_actions.py 的命名帧动作），且**实参形状**必须是开关
  表达式（不是常量字面量 —— A-11 同一族判据，见 `_is_rate_factor_switch`）；
  **pet_fx 的特效帧不纳入**
  （装饰帧，pet_fx.AnimatedEmote.play 没有倍率入口），扫描面与排除理由见对应用例；
  开着时**相邻帧的时间间隔变长**、关掉**恢复原速**，且帧**仍在推进**（不是冻成一张图）；
· **D3 顶层菜单项数**：_verify_green.py 与 tests/test_feedback_v2110_b.py 都有
  「顶层 <=18 项」的硬断言，这里**独立数一遍并留下读数**（菜单定义在 pet_menu.py，
  不归本工作包；本文件只测量，不改菜单）；
· **D2 播放点（喂食）**：语音库与内置音效两个独立播放器合成一条**显式优先级链** ——
  语音库有该事件片段就只走语音、没有才落回内置音效；回落判据只有
  pet_voice.EventClipResult.fallback_allowed（missing / voice_off 为真，failed 为假）。

判定口径：结构性读数（定时器间隔 / 落盘配置 / 动作勾选态 / 顶层项数 / 函数调用记账），不看眼。
唯一用到墙钟的一处是"帧确实还在推进"（给 4 倍余量，只断言 **>=1 帧**），见
test_idle_material_frames_slow_down_and_never_freeze 末尾的说明。
"""
import ast
import io
import json
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import 桌宠 as main  # noqa: E402
import pet_anim  # noqa: E402
import pet_config  # noqa: E402
import pet_motion  # noqa: E402
import pet_widgets  # noqa: E402
from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QMenu  # noqa: E402


# ---------------- 夹具（与 tests/test_motion_v2110.py 同一口径：数据目录指到 tmp_path） ----------------

def _snapshot():
    import pet_log
    return (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
            getattr(pet_log, "_data_dir", None))


def _point_data_dir(tmp_path):
    import pet_log
    main.DATA_DIR = str(tmp_path)
    main.CONFIG_PATH = str(tmp_path / "config.json")
    main.USAGE_PATH = str(tmp_path / "usage.json")
    main.MEMORY_PATH = str(tmp_path / "memory.json")
    pet_log.set_data_dir(str(tmp_path))


def _restore(snap):
    import pet_log
    (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
     pet_log._data_dir) = snap


@pytest.fixture
def win(tmp_path):
    """一个真 PetWindow（数据目录指到 tmp_path，绝不碰真配置）。

    BUBBLE_STYLE 是**模块全局**：高对比度那条要断言"调色板真的换上了"，
    前提是出发点就是 canon 样式，且结束时把进入夹具时的那份原样放回（不污染别人）。
    """
    snap = _snapshot()
    _style_before = dict(main.BUBBLE_STYLE)
    main.BUBBLE_STYLE.clear()
    main.BUBBLE_STYLE.update(dict(pet_widgets.BUBBLE_STYLE_CANON))
    _point_data_dir(tmp_path)
    w = main.PetWindow()
    try:
        yield w
    finally:
        try:
            if not w._closing:
                w._quit()
        except Exception:
            pass
        _restore(snap)
        main.BUBBLE_STYLE.clear()
        main.BUBBLE_STYLE.update(_style_before)


def _cfg_on_disk():
    return json.loads(io.open(main.CONFIG_PATH, encoding="utf-8").read())


def _tray_action(win, needle, not_needle=()):
    """托盘菜单里**唯一**一条文本含 needle（且不含 not_needle 里任一个）的动作。"""
    hits = [a for a in win.tray.contextMenu().actions()
            if needle in a.text() and not any(s in a.text() for s in not_needle)]
    assert len(hits) == 1, [(a.text(), a.isCheckable()) for a in win.tray.contextMenu().actions()]
    return hits[0]


# ===================== C-13：三态口径 =====================

def test_motion_state_is_exactly_the_three_config_values():
    """三态就是 pet_config.MOTION_MODES 那三个；勾选框的 bool 映射成 on/off；其余一律回 auto。

    这条同时钉**词表只有一份**：桌宠._motion_state 与 pet_config.normalize_motion_mode
    对同一批输入的结论必须逐条相同（两边各留一套字符串的话，这里当场红）。
    """
    import pet_config
    assert pet_config.MOTION_MODES == ("auto", "on", "off"), pet_config.MOTION_MODES
    for v in pet_config.MOTION_MODES:
        assert main._motion_state(v) == v
        assert main._motion_state(v) == pet_config.normalize_motion_mode(v)
    assert main._motion_state(" ON ") == "on"          # 大小写与空白归一
    assert main._motion_state(True) == "on" and main._motion_state(False) == "off"
    for bad in (None, "", "   ", 1, 0, 1.0, [], {}, "true", "yes", "always", "跟随系统"):
        assert main._motion_state(bad) == "auto", bad
        assert main._motion_state(bad) == pet_config.normalize_motion_mode(bad), bad


def test_the_three_states_survive_the_real_config_round_trip(win):
    """三态写进配置后**读回来仍是那三个值本身** —— 即它们就是合法集合。

    这条钉的是"不要另造字符串"：写个"跟随系统"之类会被归一化悄悄改成 auto，
    菜单勾选态就会说谎。
    ⚠ diff 存储：等于默认值的键**不落盘**（pet_config.write_config 的口径：只写与
    DEFAULT_CONFIG 不同的键），所以 auto 在文件里是"没有这个键"，读回来仍是 auto。
    判据因此按"load_config 读回来的值"判，文件那一侧只对非默认值判。
    """
    for key, setter in (("reduce_motion", win._set_reduce_motion),
                        ("high_contrast", win._set_high_contrast)):
        assert main.DEFAULT_CONFIG[key] == "auto", (key, main.DEFAULT_CONFIG[key])
        for st in ("on", "off", "auto"):
            setter(st)
            reloaded = main.load_config()          # ← 走产品自己的归一化
            assert reloaded[key] == st, (key, st, reloaded[key])
            if st == "auto":
                assert key not in _cfg_on_disk(), (key, st, _cfg_on_disk())
            else:
                assert _cfg_on_disk()[key] == st, (key, st, _cfg_on_disk().get(key))


def test_reduce_motion_auto_rereads_the_system_setting(win, monkeypatch):
    """C-13 的核心：auto 不是"建窗那一刻"的快照，每次切回 auto 都**重读**。"""
    state = {"v": True}
    monkeypatch.setattr(pet_motion, "system_reduce_motion", lambda: state["v"])
    # 先把建窗缓存清成"读不到"（None）——不重读的话它就一直是 None，下面必红
    win._sys_reduce_motion = None
    win._set_reduce_motion("on")
    win._set_reduce_motion("auto")
    assert win.cfg["reduce_motion"] == "auto"
    assert win._sys_reduce_motion is True, "切回 auto 没有重读系统设置（还在用旧缓存）"
    assert win._reduce_motion() is True
    # 系统又变了：再切一次 auto 必须再读一次（不是只读一次就固化）
    state["v"] = False
    win._set_reduce_motion("auto")
    assert win._reduce_motion() is False, "第二次 auto 没有重读系统设置"
    # auto 是默认值 → diff 存储不落这个键；"读回来是 auto"才是要钉的东西
    assert _cfg_on_disk().get("reduce_motion", "auto") == "auto", _cfg_on_disk()


def test_high_contrast_auto_rereads_the_system_theme(win, monkeypatch):
    """高对比度同口径：切回 auto 重读系统深色主题，并**真的**换上那套调色板。"""
    monkeypatch.setattr(pet_motion, "system_dark_theme", lambda: True)
    win._sys_dark = None
    win._set_high_contrast("auto")
    assert win.cfg["high_contrast"] == "auto"
    assert win._sys_dark is True, "切回 auto 没有重读系统主题（还在用旧缓存）"
    assert win._high_contrast() is True
    pal = pet_motion.palette(True)                       # 深色那套
    assert main.BUBBLE_STYLE["fg"] == pal["fg"]
    assert main.BUBBLE_STYLE["bg"] == pal["bg"]
    assert pet_motion.contrast_ratio(main.BUBBLE_STYLE["fg"], main.BUBBLE_STYLE["bg"]) >= 4.5
    # 关掉：回到用户那份样式，且配置真的是 off（不是 auto 被悄悄写成 off）
    before = dict(pet_widgets.BUBBLE_STYLE_CANON)
    win._set_high_contrast("off")
    assert _cfg_on_disk()["high_contrast"] == "off"
    assert main.BUBBLE_STYLE["fg"] == before["fg"]


def test_tray_menu_represents_three_states_and_auto_is_reachable(win, monkeypatch):
    """菜单勾选态反映三态，且"回到跟随系统"**任何时候都点得到**。

    表示法：主项勾 = 生效值为真（auto 时也照实显示系统那份）；「跟随系统」项勾 = 配置是 auto。

    ⚠ **两个方向都由本用例自己钉住**（不靠 conftest 的固定值）：系统说"减少动效"（True）与
    系统说"动画全开"（False）下，auto 的勾选态都必须说真话 —— 只钉一个方向的用例在换台
    机器（或 CI 的 windows-latest）上会静默变成"测的是另一件事"。
    """
    sys_reduce = {"v": True}      # 先钉成"系统动画 = 关"（= 应当减少动效）
    monkeypatch.setattr(pet_motion, "system_reduce_motion", lambda: sys_reduce["v"])
    rm = _tray_action(win, "减少动效", not_needle=("跟随系统",))
    rm_auto = _tray_action(win, "跟随系统（减少动效）")
    hc_auto = _tray_action(win, "跟随系统（高对比度）")
    assert rm.isCheckable() and rm_auto.isCheckable() and hc_auto.isCheckable()

    # ⓪ **建窗时的初值**：配置默认就是 auto → 两个「跟随系统」项一建出来就该勾着。
    # 勾选态初值由 _sync_motion_acts() 落（不是 __init__ 里直接 setChecked）——
    # 少了这次同步，初值就是"未勾"，而配置说的是 auto：界面在说谎。
    assert pet_config.is_auto_motion_mode(win.cfg.get("reduce_motion")) is True
    assert pet_config.is_auto_motion_mode(win.cfg.get("high_contrast")) is True
    assert rm_auto.isChecked() is True, "建窗时「跟随系统（减少动效）」没勾上（初值丢了）"
    assert hc_auto.isChecked() is True, "建窗时「跟随系统（高对比度）」没勾上（初值丢了）"

    # ① 显式开：只有主项勾着
    rm.setChecked(True)
    assert win.cfg["reduce_motion"] == "on" and win._reduce_motion() is True
    assert rm.isChecked() is True and rm_auto.isChecked() is False

    # ② 显式关：两项都不勾
    rm.setChecked(False)
    assert win.cfg["reduce_motion"] == "off" and win._reduce_motion() is False
    assert rm.isChecked() is False and rm_auto.isChecked() is False

    # ③ 回到跟随系统（旧实现在这里就回不去了）：点得到、配置回 auto、勾选态说真话
    rm_auto.trigger()
    assert win.cfg["reduce_motion"] == "auto"
    assert rm_auto.isChecked() is True
    assert rm.isChecked() is True, "auto 且系统开着减少动效时，主项应照实显示已勾选"
    assert win._reduce_motion() is True
    assert _cfg_on_disk().get("reduce_motion", "auto") == "auto", _cfg_on_disk()

    # 高对比度那一对同样存在（同一条接线，两处都要有）
    hc = _tray_action(win, "高对比度", not_needle=("跟随系统",))
    hc_auto.trigger()
    assert win.cfg["high_contrast"] == "auto" and hc_auto.isChecked() is True
    assert hc.isChecked() == win._high_contrast()

    # ④ **反方向**（系统动画 = 开）：auto 必须重读出来，勾选态两边都说真话。
    # 旧实现在这里同样是"点过就回不去"的重灾区；只覆盖 ③ 的话，本用例在
    # "系统动画 = 开"的机器上测的其实是另一件事（初始勾选态相反）。
    sys_reduce["v"] = False
    rm_auto.trigger()
    assert win.cfg["reduce_motion"] == "auto"
    assert win._sys_reduce_motion is False, "切回 auto 没重读系统设置（还留着上一个方向的值）"
    assert win._reduce_motion() is False, "系统动画全开时 auto 的生效值应当是「不减少动效」"
    assert rm_auto.isChecked() is True, "auto 时「跟随系统（减少动效）」应当勾着"
    assert rm.isChecked() is False, "系统动画全开时，主项不该显示已勾选"
    assert _cfg_on_disk().get("reduce_motion", "auto") == "auto", _cfg_on_disk()


# ===================== D1：素材帧帧率倍率 =====================

def test_frame_rate_token_contract():
    """令牌契约（真源在 pet_motion，另一个工作包负责加）：关 1.0、开 0.5，且**永不为 0**。"""
    assert hasattr(pet_motion, "frame_rate_factor"), "D1 的帧率倍率令牌还没进 pet_motion"
    assert pet_motion.frame_rate_factor(False) == 1.0
    assert pet_motion.frame_rate_factor(True) == 0.5
    assert pet_motion.frame_rate_factor(True) > 0.0, "0 倍速 = 冻帧，正是被否掉的那一支"


def test_rate_gate_folds_bad_factors_back_to_full_speed(win):
    """`pet_anim._safe_rate_factor` 那道闸：坏值一律回 1.0（原速），**绝不返回 0 / 负 / 非有限**。

    为什么必须钉它：`effective_interval_ms() = max(1, int(round(interval / rate)))` —— rate 漏进
    0 就是 ZeroDivisionError、漏进负数得到负间隔、漏进 NaN 是 `int(nan)` 抛错，三种都会把 D1 的
    "放慢"变成"崩"或"冻帧"（正是用户否掉的那一支）。真源侧 pet_motion.frame_rate_factor 的坏值
    回退另有判据（tests/test_motion_v2110.py:248-267）；这里是**消费端**那道闸，同一份契约的
    另一半也得有牙。喂的是**真函数**：把闸拆成放行（单行 `return r`）→ 本用例立刻红。
    行为钉子用真的 FrameAnim（两个消费点各一次），判的是"间隔仍是有限正数、不抛"。
    """
    bad = (0, 0.0, -0.5, -1, float("nan"), float("inf"), float("-inf"), None, "坏值", [], {})
    for v in bad:
        got = pet_anim._safe_rate_factor(v)
        assert got == 1.0, "坏倍率 %r 没被折回原速（得到 %r）：这一格会变成冻帧 / 崩" % (v, got)
    # 正常值必须原样通过 —— 否则"闸"就退化成常量，D1 的放慢会被它自己吃掉
    assert pet_anim._safe_rate_factor(0.5) == 0.5
    assert pet_anim._safe_rate_factor(2) == 2.0
    # 消费点①：play(rate_factor=坏值)：倍率被折回 1.0，实际间隔仍是有限正数（不抛）
    win.anim.add_set("__rate_gate_probe__", [])
    assert win.anim.play("__rate_gate_probe__", 140, rate_factor=0) is False  # 空帧集：立即"播完"
    assert win.anim.rate_factor() == 1.0, "坏倍率没被闸拦下：%r" % (win.anim.rate_factor(),)
    assert win.anim.effective_interval_ms() == 140, win.anim.effective_interval_ms()
    # 消费点②：运行中改倍率（set_rate_factor）同一道闸
    assert win.anim.set_rate_factor(0) >= 1, "运行中改倍率那一侧漏了闸（0 会除爆）"
    assert win.anim.rate_factor() == 1.0


def test_idle_material_frames_slow_down_and_never_freeze(win):
    """D1 验收（硬性）：间隔变长 → 关掉恢复原速 → 帧仍在推进（不冻成一张图）。"""
    win._set_reduce_motion("off")
    win._play_idle()
    frames = win.anim._sets.get("idle") or []
    assert len(frames) >= 2, "默认角色应当有 idle 素材帧（否则这条测的是静态图，没有帧可放慢）"
    base = win.anim.effective_interval_ms()
    assert base == main.IDLE_FRAME_MS, (base, main.IDLE_FRAME_MS)
    assert win.anim._timer.isActive() and win.anim._timer.interval() == base

    # 开着减少动效：**当场**换速（在播的这一次就变，不需要重启播放）
    win._set_reduce_motion(True)
    slow = win.anim.effective_interval_ms()
    assert slow == 2 * base, "相邻帧的时间间隔没有变长：%d -> %d" % (base, slow)
    assert win.anim._timer.interval() == slow, "定时器没跟着换速（倍率只记在别处，没落到播放路径）"
    assert win.anim._timer.isActive(), "减少动效把帧停住了（D1 明令：不许冻成一张图）"
    assert 0 < win.anim._timer.remainingTime() <= slow, "定时器没有在倒计时（帧不会再来）"

    # 帧仍在推进：定时器每次 timeout 都要往前走一帧
    seen = []
    win.anim.frame_changed.connect(seen.append)
    start = win.anim._index
    for _ in range(3):
        win.anim._timer.timeout.emit()
    assert len(seen) == 3 and win.anim._index == start + 3, (seen, win.anim._index, start)
    assert win.anim.current() is not None

    # 墙钟旁证（本文件唯一一处）：慢速间隔 280ms，给 1120ms 窗口（4 倍余量）只要求 >=1 帧。
    # 这条判的是"没被冻住"，不是"速率"——速率由上面的定时器间隔钉死。
    before = len(seen)
    QTest.qWait(1120)
    assert len(seen) > before, "1120ms 里一帧都没推进（4 倍余量内仍不动 = 冻帧）"

    # 关掉：恢复原速
    win._set_reduce_motion("off")
    assert win.anim.effective_interval_ms() == base, "关掉开关没有恢复原速"
    assert win.anim._timer.interval() == base


def test_eat_watchdog_covers_the_slowed_frames(win):
    """吃帧看门狗按**实际生效**的间隔算：素材帧放慢一倍，看门狗也得放宽一倍。

    否则减少动效下看门狗会在吃帧播到一半时抢着收尾（busy 提前释放 -> 之后喂食被判
    "嘴里还有呢"）。判据用的是"看门狗必须覆盖整段播放"这条不变量，不是抄一遍公式。
    """
    win._ensure_default_frames(("eat",))
    win._wire_anim_sets()   # 把刚补上的帧集注册进播放器（生产路径由 _play_idle 顺手做）
    n = len(win.anim._sets.get("eat") or []) or 7
    assert n >= 2, "默认角色的吃帧没就位（这条就测不成：空帧集会让 play 立刻回调收尾）"

    win._set_reduce_motion("off")
    win._play_eat()
    fast_eff, fast_wd = win.anim.effective_interval_ms(), win._eat_watchdog.interval()
    assert fast_wd >= n * 2 * fast_eff, (fast_wd, n, fast_eff)

    win._set_reduce_motion("on")
    win._play_eat()
    slow_eff, slow_wd = win.anim.effective_interval_ms(), win._eat_watchdog.interval()
    assert slow_eff == 2 * fast_eff, (slow_eff, fast_eff)
    assert slow_wd >= n * 2 * slow_eff, "看门狗没跟着放慢：%r（需要覆盖 %r）" % (slow_wd, n * 2 * slow_eff)
    assert slow_wd > fast_wd


# 扫描面：角色素材帧能被播放的**全部**落点（pet_fx.py 只作为"必须为空"的那一侧参与，
# 理由见下面那条用例的 docstring —— 它是判据里的一个断言，不是这里的注释）。
_MATERIAL_FRAME_FILES = ("桌宠.py", "pet_actions.py", "pet_fx.py")


def _anim_play_sites(rel):
    """扫 rel 里所有 `<x>.anim.play(...)` 调用点 → [node]（只看 AST：注释/字符串不算）。"""
    src = io.open(os.path.join(HERE, rel), encoding="utf-8").read()
    out = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if (isinstance(fn, ast.Attribute) and fn.attr == "play"
                and isinstance(fn.value, ast.Attribute) and fn.value.attr == "anim"):
            out.append(node)
    return out


def _is_rate_factor_switch(node):
    """`rate_factor=` 的实参是不是**开关表达式**：`…_frame_rate_factor()` 这一个调用。

    A-11① 的同一路形状判据（tests/test_motion_v2110.py:371 `_is_switch_expr`）：判**取值形状**，
    不判"关键字在不在" —— 只查关键字的话，把 `rate_factor=pet._frame_rate_factor()` 换成
    `rate_factor=1.0`（关键字还在、值被钉成常量）照样绿，与 A-11 当年要修的
    `duration_ms("RIPPLE", False)` 是同一族漏洞：开关在这条路径上被静默架空。

    收得很紧：只认 `_frame_rate_factor` 这一个属性调用（开关注入点本身，转发
    pet_motion.frame_rate_factor(开关)，见 桌宠.py:4496-4507）。今天 5 条落点全是这个形状，
    **没有合法的常量实参**，所以这条判据不设祖父条款。故意**不**收
    `pet_motion.frame_rate_factor(...)`：它的实参本身可能就是 `False`（= 常量 1.0 的等价写法），
    收下等于把同一个洞换个写法放回来。先算进局部变量再传（`f = self._frame_rate_factor()`）
    会被判红 —— 届时按 A-11 的 _GRANDFATHERED_SWITCH_FREE 同一流程显式裁决，不静默放宽。
    """
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_frame_rate_factor")


def test_every_material_frame_play_site_carries_the_rate_token():
    """**角色**素材帧的每一条播放路径都带帧率令牌（少一条 = 那条在减少动效下仍是原速）。

    扫描面 = 桌宠.py（idle/eat/poke/sleep **/ walk** 五条字面帧集；walk 是 v2.11.0 第 11 轮
    W2 的走路播帧，同样带 rate_factor —— 用户裁决 D1「纳入、折中」：放慢不停帧）+ pet_actions.py（命名帧动作：
    帧集名来自变量，是**用户给角色配的**素材帧序列，同样必须带令牌 —— 不带的话
    pet_anim.play() 会把倍率重置回默认 1.0，那一段就以原速整段播完）。

    "带令牌"判的是**实参的形状**：`rate_factor=` 的值必须是开关表达式（`…_frame_rate_factor()`
    调用），不是"关键字在" —— 只查关键字的话 `rate_factor=1.0`（关键字还在、值被钉死）照样
    绿，与 A-11 当年要修的 `duration_ms("RIPPLE", False)` 是同一族漏洞；判据见
    `_is_rate_factor_switch` 与它下面那四条反向对照。

    **pet_fx.py 明确不在"必须带令牌"的那一侧**：v2.11.0 裁决 D1 只管**角色**素材帧；
    petpet / money 是叠在角色上的**装饰特效帧**，走 pet_fx.AnimatedEmote 自己的 QTimer，
    play() 只有 interval_ms 一个时间参数、**没有倍率入口**（pet_motion.py:66/:171 的注释
    与发布说明同一口径）。为了让"排除"是**判据**而不是一句注释，下面单独断言 pet_fx.py 里
    `<x>.anim.play(` 命中数为 0 —— 它抓的是**这一种形状**：pet_fx.py 里出现 `anim.play`
    调用（例如将来给它接一个 pet_anim.FrameAnim，或把主窗口的 anim 传进去）→ 那条路当场红，
    逼着他先裁决"纳不纳入"。
    ⚠ **它抓不到另一种**：绕开 anim、用 pet_fx 自己的 AnimatedEmote（`fx.play(...)`）播角色帧
    —— 那种写法不在扫描面里（pet_fx.py 今天 6 处 `fx.play` 全在 `__main__` 冒烟块、产品侧 0 处）；
    同理，"AnimatedEmote.play 没有倍率入口"这条排除依据今天也只写在注释里，没有机检。
    """
    # 判据自检（A-11 的同一道工序）：形状判据必须真能区分"开关"与"常量"，否则它就退化回
    # "关键字在不在" —— 那正是本轮要堵的那个洞。
    def _kw(src):
        """`f(rate_factor=…)` 源码 → 那个实参节点（只给下面这几条反向对照用）。"""
        return ast.parse(src).body[0].value.keywords[0].value

    assert _is_rate_factor_switch(_kw("f(rate_factor=pet._frame_rate_factor())"))
    assert _is_rate_factor_switch(_kw("f(rate_factor=self._frame_rate_factor())"))
    for _bad in ("f(rate_factor=1.0)", "f(rate_factor=0.5)",
                 "f(rate_factor=None)", "f(rate_factor=True)"):
        assert not _is_rate_factor_switch(_kw(_bad)), _bad

    named, dynamic, fx_sites = set(), set(), []   # 字面帧集名 / 按变量播的落点 / 特效帧落点
    for rel in _MATERIAL_FRAME_FILES:
        for node in _anim_play_sites(rel):
            if rel == "pet_fx.py":
                fx_sites.append(node)
                continue
            kws = {k.arg for k in node.keywords}
            assert "rate_factor" in kws, (
                "这处素材帧播放没带帧率倍率令牌（%s line %d）：%s"
                % (rel, node.lineno, ast.unparse(node)))
            assert _is_rate_factor_switch(
                next(k.value for k in node.keywords if k.arg == "rate_factor")), (
                "这处 rate_factor= 的实参不是开关表达式（%s line %d）：%s —— 关键字在、取值却被"
                "钉成常量（1.0 / 0.5 / None…）的话，「减少动效」在这条路径上静默失效，与 A-11 的"
                "duration_ms(…, False) 是同一族漏洞" % (rel, node.lineno, ast.unparse(node)))
            assert node.args, "%s line %d 没有帧集名实参：%s" % (rel, node.lineno, ast.unparse(node))
            if isinstance(node.args[0], ast.Constant):
                named.add(node.args[0].value)
            else:
                dynamic.add((rel, ast.unparse(node.args[0])))
    # v2.11.0（第 11 轮 W2）：「走路播帧」把 "walk" 加进这张清单 —— 它确实带了
    # rate_factor=self._frame_rate_factor()（D1 的折中放慢，见 桌宠.py 的 _walk_anim）。
    assert named == {"idle", "eat", "poke", "sleep", "walk"}, (
        "字面帧集的播放路径清单变了（新加一条时请一并想清楚它要不要走帧率倍率）：%r"
        % (sorted(named),))
    assert dynamic == {("pet_actions.py", "name")}, (
        "按变量名播放的路径清单变了（同上：新加一条时请一并想清楚它要不要走帧率倍率）：%r"
        % (sorted(dynamic),))
    assert not fx_sites, (
        "pet_fx.py 里出现了 `<x>.anim.play(` 播放点（line %s）：**特效帧**（petpet/money）按 "
        "v2.11.0 裁决不纳入 D1；要在这里加角色素材帧的播放路径，先裁决纳不纳入，再把本用例"
        "的扫描面/口径一起改" % ([n.lineno for n in fx_sites],))


# ===================== D2：语音库 / 内置音效的显式优先级链 =====================

def _arm_feed_voice(win, present, voice_enabled):
    """把喂食这条链的**输入**摆成指定场景：语音库里 feed 有没有片段 + 语音总开关。

    摆的是**真东西**：往 voice/ 写一个真片段文件，让 VoiceService.clip() 真的 isfile 命中；
    不伪造 EventClipResult（契约的真源在 pet_voice，判据要连着它一起验）。
    返回片段路径（present=False 时也返回那个路径，便于断言它确实不存在）。
    """
    vdir = win.voice._dir
    os.makedirs(vdir, exist_ok=True)
    path = os.path.join(vdir, "feed_probe.wav")
    if present:
        with io.open(path, "wb") as fh:
            fh.write(b"RIFF0000WAVEfmt ")   # 内容无所谓：clip() 只做 isfile，不解码
        win.voice._clips["feed"] = "feed_probe.wav"
    else:
        win.voice._clips.pop("feed", None)
        if os.path.isfile(path):
            os.remove(path)
    win.cfg.setdefault("voice", {})["enabled"] = bool(voice_enabled)
    return path


def test_feed_voice_clip_wins_and_falls_back_only_when_allowed(win, monkeypatch):
    """D2 验收主用例：喂食这条链的**四种结局**，每种"内置音效响不响"都钉死。

    判据按**调用记账**判（把 桌宠.play_sound 换成记录器），不看眼、不看墙钟；
    语音那一侧不伪造 —— 走的是真 VoiceService.play_event + 真 EventClipResult。
    """
    sounds = []
    monkeypatch.setattr(main, "play_sound", lambda kind: sounds.append(kind))

    def feed_once():
        win.busy = False          # 上一次喂食把 busy 置上了；复位成"可以再喂"
        del sounds[:]
        win.feed("小鱼干")
        return list(sounds)

    # ① missing（没有片段）→ 内置音效接手：没配音的用户不许丢音效
    _arm_feed_voice(win, present=False, voice_enabled=True)
    assert win.voice.clip("feed") is None, "场景没摆对：本来该是'没有片段'"
    assert feed_once() == ["feed"], "没有片段时内置音效没响（没配音的用户丢了内置音效）"

    # ② played（有片段且已交给播放器）→ 内置音效**不响**（同一事件只响一次）
    _arm_feed_voice(win, present=True, voice_enabled=True)
    assert win.voice.clip("feed") is not None, "场景没摆对：本来该是'有片段'"
    monkeypatch.setattr(win.voice, "_play_clip", lambda p: None)
    assert feed_once() == [], "语音已经播了，内置音效又响了一次（同一事件响了两遍）"

    # ③ failed（有片段但这次播不出来）→ **也不许落回**：内置音效会把语音的事故盖住
    _arm_feed_voice(win, present=True, voice_enabled=True)

    def _boom(path):
        raise RuntimeError("播放器炸了（判据自造，只影响这一条）")

    monkeypatch.setattr(win.voice, "_play_clip", _boom)
    assert feed_once() == [], "播不出来时落回了内置音效（D2 明令：不许拿它盖住事故）"

    # ④ voice_off（语音总开关关着，而片段**是配了的**）→ 落回内置音效
    _arm_feed_voice(win, present=True, voice_enabled=False)
    assert feed_once() == ["feed"], "关掉语音的用户连内置音效一起丢了（D2 要避免的正是这个）"

    # ⑤ 既有的音效总开关照旧管用：关掉它 → 内置音效一声不响（语音那条链不受它管）
    _arm_feed_voice(win, present=False, voice_enabled=True)
    win.cfg["sound"] = False
    try:
        assert feed_once() == [], "cfg.sound 关着时内置音效还是响了"
    finally:
        win.cfg["sound"] = True


def test_feed_fallback_never_uses_truthiness_or_has_clip(win, monkeypatch):
    """回落判据**只许**是 fallback_allowed —— 两个反例各钉一条。

    · 反例 A「拿真假值判断」：EventClipResult 没定义 __bool__，bool(res) 恒为真 ——
      若调用点写成 if res: / if not res:，voice_off（片段配了、语音关着）就会不落回；
    · 反例 B「拿 not res.has_clip 当判据」：voice_off 时 has_clip 可能是 True（片段配了）
      → 同样会不落回。两条都拿真对象验，验的是**契约本身**而不是我抄的一句话。
    """
    import pet_voice
    _arm_feed_voice(win, present=True, voice_enabled=False)   # 片段配了 + 语音关着
    res = win.voice.play_event("feed")
    assert res.reason == pet_voice.EVENT_CLIP_VOICE_OFF, res
    assert res.has_clip is True, "本反例的前提是'片段配了'，场景没摆对"
    assert bool(res) is True, "EventClipResult 没有 __bool__：真假值判断会恒真"
    assert res.fallback_allowed is True, "voice_off 必须允许落回（D2 的口径）"
    # failed 的反面：有片段、播不出来 → has_clip 仍 True，但**不许**落回
    _arm_feed_voice(win, present=True, voice_enabled=True)   # 语音得是开着的，否则又是 voice_off

    def _boom(path):
        raise RuntimeError("播放器炸了（判据自造，只影响这一条）")

    monkeypatch.setattr(win.voice, "_play_clip", _boom)
    res2 = win.voice.play_event("feed")
    assert res2.reason == pet_voice.EVENT_CLIP_FAILED and res2.failed is True, res2
    assert res2.has_clip is True and res2.fallback_allowed is False, res2

# ===================== D3：顶层菜单项数（只测量，不裁决） =====================

def _ascii(s):
    """菜单文本 -> 纯 ASCII（控制台编码是 GBK，直接 print emoji 会 UnicodeEncodeError）。"""
    return s.encode("ascii", "backslashreplace").decode("ascii")


def _walk_menu(menu, depth=0, out=None):
    out = [] if out is None else out
    for a in menu.actions():
        if a.text():
            out.append((depth, a.text()))
        if a.menu() is not None:
            _walk_menu(a.menu(), depth + 1, out)
    return out


def test_top_level_menu_items_are_within_the_hard_cap(win, monkeypatch):
    """顶层菜单 <=18 项（_verify_green.py:86 / tests/test_feedback_v2110_b.py:568 的硬断言）。

    菜单定义在 pet_menu.py（不归本工作包）——这里只**数**并打印读数，供 D3（菜单去重）
    与任何"往顶层加东西"的改动当场看到数。
    """
    captured = {}

    class _CapMenu(QMenu):
        def exec(self, *_a, **_k):  # noqa: A003
            captured["top"] = [a.text() for a in self.actions() if a.text()]
            captured["all"] = _walk_menu(self)
            return None

    monkeypatch.setattr(win, "_new_menu", lambda: _CapMenu(win))
    win._open_menu(QPoint(10, 10))
    top = captured["top"]
    print("\n[P7/D3] 顶层菜单项数 = %d（硬上限 18）: %s"
          % (len(top), " | ".join(_ascii(t) for t in top)))
    print("[P7/D3] 角色子菜单里含「导入角色」的条目: %s"
          % ([_ascii(t) for d, t in captured["all"] if d == 1 and "导入角色" in t],))
    print("[P7/D3] 全菜单含「资源管理」的条目: %s"
          % ([_ascii(t) for d, t in captured["all"] if "资源管理" in t],))
    # 读数（不是判据）：_verify_v13.py 另有"菜单总条目 >= 35"与"含「资源管理」"两条断言，
    # 顶层去重会动这两个数，所以把总条目数一并打出来，让去重的代价当场看得见。
    print("[P7/D3] 全菜单（含子菜单）非空文本条目数 = %d（_verify_v13.py:1633 要求 >= 35）"
          % (len(captured["all"]),))
    assert len(top) <= 18, "顶层菜单超了 18 项：%d —— %r" % (len(top), top)
    # ⚠ 顶层「📦 资源管理…」必须留着：_verify_v13.py:1635（any("资源管理" in t)）与
    # :1673（"资源管理" or "音频片段"）两条断言都靠它命中——D4 把「管理音频片段…」改名成
    # 「管理音效片段…」之后，"音频片段"这半已经不再命中，只剩"资源管理"这半兜着。
    # （D3 的去重已由 pet_menu.py 删掉角色子菜单里的「导入角色…」完成，与这条约束相容。）
    assert any("资源管理" in t for _d, t in captured["all"]), captured["all"]
