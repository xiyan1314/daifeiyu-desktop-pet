# -*- coding: utf-8 -*-
"""v2.11.0 第 9 轮（代理 A）：动效地基（A1/A2/A3）+ 视觉三件套（A4/A5）+ 传下来的五条速胜（B1/B2/B3/B4/B7）。

**判定一律是结构性断言**（不看眼看、不看墙钟）：

· A4 三件套：悬停/按下时**几何量逐项不变**（窗口尺寸、scale、squash、item 变换、item 位置
  五元组逐个比），按下**描边出现**，涟漪收尾后**场景对象数回到基线**（不是"看起来没了"）；
· A2 减少动效：**逐条列举每个动效点**，开关打开后断言"该动的都不动了"（各自动画对象为 None /
  时长为 0 / 一次性动效不产生），再反向断言"开关关掉后它们又动了"；
· A3 高对比度：对比度用 pet_motion.contrast_ratio **算出来**钉 ≥ 4.5:1；
· A5 贴边：目标位置由用例**独立重算一遍**（与旧公式逐字相同）再与动画终点比；
· B1/B7：阈值与"双击走事件、不加延迟"按**调用计数**与状态断言（不是"看起来没延迟"）；
· B2/B3：淡入淡出按动画对象 + **平台无关读数** _opacity（offscreen 不支持窗口不透明度），
  跟随按位移**逐像素相等**且自动隐藏计时**不被重启**。

驱动方式：QVariantAnimation 用 setCurrentTime(duration) 推到终态——
_dev/probe_qt_setcurrenttime_v26.py 验过它是**确定性**驱动（不看钟），
与 tests/test_idle_settle_v26.py 的驱动口径一致。

v2.11.0 定版补漏（A-04 的三个新接动效点 + 两条"没牙齿"的守卫）：
· A-08 / A-12：跳跃（pet_actions 的 JUMP）/ 落地 Q 弹（桌宠 _play_landing_bounce）/
  余额徽章滚动（pet_balance 的 BALANCE_ROLL）三处**并在验收主用例里逐条列举**——
  开着开关不产生在途动画、瞬时到终态，且**结果值与开动效时逐项相同**；
· A-11①：`duration_ms` / `effective_duration` 的**第二个实参形状**由 AST 判
  （不再是"字符串在不在"——那种判据对桌上现成的 `duration_ms("RIPPLE", False)` 无感）；
· A-11② / C-10：令牌名守卫的扫描面扩到产品侧四个文件，正则放宽到含小写；
· C-09：反向钉子——表里每个键都要有消费点（备用档位显式祖父化）；
· C-20：高对比度的**挂件/托盘**那一半（pet_widgets._pal()）也要真换、关掉逐键复原；
· C-21：520 / 700 进"原处不许再有字面量"名单；
· D1：素材帧的折中倍率 frame_rate_factor() 的契约（坏值回退不抛、且**绝不返回 0**）。
"""
import ast
import io
import json
import os
import re
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import 桌宠 as main  # noqa: E402
import pet_motion  # noqa: E402
import pet_physics  # noqa: E402
import pet_widgets  # noqa: E402
from PySide6.QtCore import (QAbstractAnimation, QCoreApplication, QEasingCurve,  # noqa: E402
                            QEvent, QPoint, QPointF, Qt, QVariantAnimation)
from PySide6.QtGui import QEnterEvent, QKeyEvent, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


# ---------------- 夹具 ----------------

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
    """一个真 PetWindow（数据目录指到 tmp_path，绝不碰真配置）。"""
    snap = _snapshot()
    # v2.11.0 收尾：BUBBLE_STYLE 是**模块全局**，本文件里"回到用户那份样式"那类断言
    # （高对比度开关）的前提是**每个窗口都从同一份 canon 样式出发**。别的文件会故意改它
    # （tests/test_feedback_host_v270.py 注入 #445566 验成功路径，没还原）→ 全量套件里
    # 前序污染会让这条红、单跑却绿。夹具因此在建窗**前**pinned 到 canon 值，
    # 建窗**后**逐项断言窗口真的拿着 canon 那一份（不然"回到用户样式"就是空话），
    # 结束时把进入本夹具时的全局值原样复原（不污染别人）。
    _style_before = dict(main.BUBBLE_STYLE)
    main.BUBBLE_STYLE.clear()
    main.BUBBLE_STYLE.update(dict(pet_widgets.BUBBLE_STYLE_CANON))
    _point_data_dir(tmp_path)
    w = main.PetWindow()
    # 窗口必须**拿着 canon 那一份**（全新数据目录 → 配置里的 bubble_style 就是默认值）。
    # 这条不成立的话，下面"关掉开关要回到用户那份样式"的断言就是在比两份都不是用户的那份。
    assert dict(main.BUBBLE_STYLE) == dict(pet_widgets.BUBBLE_STYLE_CANON), dict(main.BUBBLE_STYLE)
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


class _Ev:
    """最小鼠标事件替身：只提供产品代码真正读的那几个方法。"""

    def __init__(self, pos=(40, 40), gp=(200, 200), btn=Qt.MouseButton.LeftButton,
                 buttons=Qt.MouseButton.NoButton):
        self._pos = QPointF(*pos) if not isinstance(pos, QPointF) else pos
        self._gp = QPointF(*gp) if not isinstance(gp, QPointF) else gp
        self._btn = btn
        self._btns = buttons

    def button(self):
        return self._btn

    def buttons(self):
        return self._btns

    def position(self):
        return self._pos

    def globalPosition(self):
        return self._gp

    def accept(self):
        pass


def _app():
    return QApplication.instance() or QApplication([])


def _drive(anim, app=None):
    """把在途动画**确定性**推到终态（不看钟）。"""
    assert anim is not None, "没有在途动画：这一条动效根本没发生"
    anim.setCurrentTime(anim.duration())
    (app or _app()).processEvents()


def _geometry(win):
    """角色的**几何五元组**：窗口尺寸 / scale / squash_x / squash_y / item 变换与位置。

    A4 的验收就钉它：悬停与按下期间这五项一个都不许变。
    """
    t = win.item.transform()
    return (win.size().width(), win.size().height(), round(float(win.scale), 9),
            round(float(win.squash_x), 9), round(float(win.squash_y), 9),
            round(t.m11(), 9), round(t.m22(), 9), round(t.dx(), 9), round(t.dy(), 9),
            win.item.pos().x(), win.item.pos().y())


def _enter(win):
    win.enterEvent(QEnterEvent(QPointF(10, 10), QPointF(10, 10), QPointF(10, 10)))


def _leave(win):
    win.leaveEvent(QEvent(QEvent.Type.Leave))


def _src(name):
    return io.open(os.path.join(HERE, name), encoding="utf-8").read()


# ===================== A1：令牌表 =====================

def test_token_table_shape_and_hci_values():
    """令牌表就是单一来源：档位值符合 HCI（反馈 ≤100ms / 转换 150–250ms / 大位移 ≈300ms）。"""
    assert pet_motion.DUR["FEEDBACK"] <= 100
    assert 150 <= pet_motion.DUR["TRANSITION"] <= 250
    assert 150 <= pet_motion.DUR["BUBBLE_FADE"] <= 250
    assert pet_motion.DUR["LARGE"] == 300
    assert all(isinstance(v, int) and v > 0 for v in pet_motion.DUR.values())
    # A4 的硬口径：悬停/按下都**不缩放**（几何因子恒 1.0）
    assert pet_motion.visual_scale("HOVER") == 1.0
    assert pet_motion.visual_scale("PRESS") == 1.0
    # 缓动名字必须真的能映射到 Qt 枚举（写错名字 = 静默退化）
    for _name in pet_motion.EASE:
        assert hasattr(QEasingCurve.Type, pet_motion.easing_name(_name)), _name
    for _name in ("GLOW", "OUTLINE", "RIPPLE", "HEART", "THINKING", "DRAG"):
        assert isinstance(getattr(pet_motion, _name), dict), _name


def test_moved_durations_are_gone_from_their_old_homes():
    """「沿用的既有时长常量必须显式搬家」：原处**不许再有字面量**，且原处留了指路注释。

    C-21（v2.11.0 定版）：A-04 新搬的 **520（JUMP）/ 700（BALANCE_ROLL）** 必须在**同一张名单**上
    ——旧版只钉了 1500 / 900 / 1500 / 5000 四个，新两个可以悄悄回到原处而无人红。
    """
    src_main = _src("桌宠.py")
    src_wid = _src("pet_widgets.py")
    src_act = _src("pet_actions.py")
    src_bal = _src("pet_balance.py")
    # 原处的硬编码必须一个不剩
    assert "anim.setDuration(1500)" not in src_main
    assert "_run_anim(900," not in src_main
    assert "_hold_timer.start(1500)" not in src_main
    assert "_timer.start(5000)" not in src_wid
    # A-04（v2.11.0 定版补漏）新搬的两处：原处同样不许再有字面量
    assert "_run_anim(520," not in src_act
    assert "setDuration(700)" not in src_bal
    # 原处必须留"搬家去哪"的指路注释（两处并存 = 改一处漏一处）
    for _token in ("EMOTE_FLOAT", "EAT_SQUASH", "PET_HOLD"):
        assert ('pet_motion.DUR["%s"]' % _token) in src_main, _token
    assert 'pet_motion.DUR["BUBBLE_HOLD"]' in src_wid
    # 新两处走的是 duration_ms（不是 DUR[...]）：名字必须落在调用点上，
    # 且**搬走的那个数一个毫秒都不许漂**（520 / 700 就是搬家前原处的字面量）
    assert 'duration_ms("JUMP"' in src_act, "跳跃的时长没走令牌表"
    assert 'duration_ms("BALANCE_ROLL"' in src_bal, "余额滚动的时长没走令牌表"
    assert pet_motion.DUR["JUMP"] == 520
    assert pet_motion.DUR["BALANCE_ROLL"] == 700


def test_pure_function_fallbacks_are_asserted_contracts():
    """pet_motion 里每个"坏值回默认"的 except 都**有契约**：回退值本身被这里断言。

    为什么它们可以登记为**静默**（而不是改成留痕）：都是纯函数，回退值是文档化的答案，
    而且回退方向都在**安全侧**（瞬时 / 不缩放 / 不猜系统设置 → 保持动效开启）。
    ⚠ 唯一有真实风险的一条是「令牌名打错 → duration_ms 返回 0 → 动效静默失效」，
    那一条**不在运行时留痕**，而是由下面 test_every_token_name_used_at_a_call_site_exists
    在**源码层**钉死（调用点写的名字必须真在表里）。
    """
    assert pet_motion.duration_ms("这个令牌不存在") == 0
    assert pet_motion.duration_ms(None) == 0
    assert pet_motion.effective_duration("坏值") == 0
    assert pet_motion.visual_scale("没有这个档位") == 1.0     # = A4 的"不缩放"策略（安全侧）
    assert pet_motion.easing_name("没有这个缓动") == pet_motion.EASE["STANDARD"]
    assert pet_motion.parse_hex("这不是颜色") == (0, 0, 0)
    assert pet_motion.parse_hex("#12345") == (0, 0, 0)
    assert pet_motion.parse_hex("#abc") == (170, 187, 204)
    assert pet_motion.to_hex((-5, 300, 12)) == "#00ff0c"
    # 系统探针的"读不到"契约：None → 调用方**不降级**（保持动效开启 / 不猜主题）
    assert pet_motion.reduce_motion_enabled("auto", None) is False
    assert pet_motion.high_contrast_enabled("auto", None) is False
    # 对比度这套纯函数遇到坏输入不许抛（回退到 default 之后仍给出一个数）
    assert isinstance(pet_motion.contrast_ratio("坏", "#ffffff"), float)
    _fixed = pet_motion.ensure_min_contrast("坏", "坏")   # 两个坏值都回 default((0,0,0))
    assert isinstance(_fixed, str) and _fixed.startswith("#"), _fixed
    assert pet_motion.ensure_min_contrast("#ffee00", "#ffffff") == "#7f7700"  # 确定性


def test_frame_rate_factor_is_a_compromise_and_never_freezes(monkeypatch):
    """D1：素材帧在「减少动效」下**放慢不停帧**（用户裁决「纳入，折中」）—— 契约在这里钉住。

    · 关着 → 1.0（原速）；开着 → RATE["FRAME_REDUCED"]，且必须落在 **(0, 1) 开区间**
      （0 = 把角色冻成一张图，正是被否掉的那一支；≥1 = 根本没放慢，等于没纳入）；
    · 表里没有这个键 / 表值坏（非数值）/ 表值不是正数 → **1.0（原速）**，不抛：
      宁可"没放慢"，也绝不返回 0 把角色冻住。
    """
    assert pet_motion.frame_rate_factor(False) == 1.0
    factor = pet_motion.frame_rate_factor(True)
    assert factor == pet_motion.RATE["FRAME_REDUCED"]
    assert 0.0 < factor < 1.0, "折中倍率必须落在 (0,1)：0 = 冻帧（被否掉），≥1 = 没纳入"
    for _bad in ("坏值", None, [], 0, -0.5):
        monkeypatch.setitem(pet_motion.RATE, "FRAME_REDUCED", _bad)
        assert pet_motion.frame_rate_factor(True) == 1.0, \
            "坏表值必须回 1.0（原速）：不许抛，更不许返回 0 把角色冻住：%r" % (_bad,)
    monkeypatch.delitem(pet_motion.RATE, "FRAME_REDUCED", raising=False)
    assert pet_motion.frame_rate_factor(True) == 1.0, "表里没有这个键时必须回 1.0（原速）"
    assert pet_motion.frame_rate_factor(False) == 1.0
    assert pet_motion.frame_rate_factor(None) == 1.0  # 关着时给什么值都一样：原速


# 调用点令牌名的形状：名字出现在 duration_ms 的**第一个实参**上。
# ⚠ 必须含小写：C-10 实测旧正则 `[A-Z_]+` 对"小写打错令牌名"无感（NOT CAUGHT）。
_TOKEN_CALL_RE = r'duration_ms\(\s*"([A-Za-z_][A-Za-z0-9_]*)"'


def test_every_token_name_used_at_a_call_site_exists():
    """调用点写下的令牌名**必须真的在表里**——否则 duration_ms 静默回退 0（动效静默失效）。

    这条把 pet_motion.duration_ms 那个"坏键 → 0"的静默回退关在门外：改名不改调用点、
    或调用点打错一个字母，这里当场红（不靠人眼、也不靠运行时日志）。

    A-11② / C-10（v2.11.0 定版）：扫描面从 桌宠.py + pet_widgets.py 扩到**产品侧四个文件**——
    A-04 新接的两处就在 pet_actions.py / pet_balance.py，漏掉它们的话"JUMP"打成"JMP"
    会静默回退 0ms 而**零红**；正则同时放宽到含**小写**（大小写写错都算打错）。
    四个文件必须**各自**贡献调用点：否则"扩了扫描面"这件事本身会悄悄回退。
    """
    files = ("桌宠.py", "pet_widgets.py", "pet_actions.py", "pet_balance.py")
    sites = []
    for name in files:
        for m in re.finditer(_TOKEN_CALL_RE, _src(name)):
            sites.append((name, m.group(1)))
    assert len(sites) >= 8, "扫描面太小（这条会退化成空检查）：%r" % (sites,)
    # 反向对照：这个正则必须**大小写都认**（C-10：旧版只认 [A-Z_]+，小写打错时 NOT CAUGHT）
    assert re.findall(_TOKEN_CALL_RE, 'x = duration_ms("jmp", True)') == ["jmp"]
    assert re.findall(_TOKEN_CALL_RE, 'x = duration_ms("JUMP", True)') == ["JUMP"]
    for name in files:
        assert any(f == name for f, _ in sites), \
            "扫描面漏了 %s（它的调用点从此无人看管）" % name
    missing = [(f, t) for f, t in sites if t not in pet_motion.DUR]
    assert missing == [], "调用点用了表里没有的令牌名（会静默退化成 0ms）：%r" % (missing,)
    for token in ("FEEDBACK", "TRANSITION", "BUBBLE_FADE", "LARGE", "EDGE", "RIPPLE",
                  "HEART", "THINKING_PULSE", "EMOTE_FLOAT", "EAT_SQUASH", "PET_HOLD",
                  "BUBBLE_HOLD", "JUMP", "BALANCE_ROLL"):
        assert token in pet_motion.DUR, token


def test_every_token_value_is_numeric():
    """v2.11.0 收尾（审计裁决）：令牌**表值**必须都是数值——不然那是一条静默失效的动效。

    为什么这条必须存在：duration_ms 在 `str(name)` 之后只可能因为「表里写了非数值」
    （例如 "1500ms" / None）抛 ValueError，而它以前是 `except (TypeError, ValueError): return 0`
    ——**表写错 = 那条动效永远 0ms 且零痕迹**。收紧 except 之后 ValueError 会冒出来，
    但那条路要等运行时才炸；这里把判据前置到测试期（表值类型 + float 可转换），
    并顺带钉住调用方传非数值对象时仍然安全（TypeError 仍被兜住、不抛给 UI）。

    能真失败：把 DUR 里任一值改成 "1500ms" / None / []，本用例当场红（不靠人眼）。
    """
    bad = [(grp, k, v) for grp, table in (("DUR", pet_motion.DUR), ("SCALE", pet_motion.SCALE))
           for k, v in table.items()
           if isinstance(v, bool) or not isinstance(v, (int, float))]
    assert bad == [], "令牌表里有非数值（会让那条动效静默失效）：%r" % (bad,)
    # 反向对照：上面那个判据必须真能失败——把表值换成一个非数值，同一个表达式要报出来
    assert [1 for v in ("1500ms", None, []) if isinstance(v, bool) or not isinstance(v, (int, float))]
    # 调用方给了奇怪对象时不许抛（这是 duration_ms 唯一合法保留的 TypeError 出口）
    assert pet_motion.duration_ms(object()) == 0
    assert pet_motion.duration_ms(None) == 0, "表里没有的键 -> 0（既有口径）"


# ---------------- A-11①：时长取用处的**实参形状**判据 ----------------

# 产品侧"时长从哪来"的两个入口：令牌表（HCI 档位）与数据驱动时长。两者都是
# `(…, reduce_motion=False)` 的签名 —— 所以第二个实参就是"开关有没有被带进去"。
_DURATION_ENTRY_POINTS = ("duration_ms", "effective_duration")

# 扫描面 = 产品侧全部会取时长的文件（少一个，那个文件的调用点就无人看管）
_DURATION_SOURCE_FILES = ("桌宠.py", "pet_widgets.py", "pet_actions.py", "pet_balance.py")

# 祖父条款：这些令牌的调用点**拿不到**开关表达式，但语义等价（"为什么"就写在值里）。
# ⚠ 新令牌不许往这里加 —— 要加，先在评审里解释"它为什么不是动效"。
_GRANDFATHERED_SWITCH_FREE = {
    "RIPPLE": "上面已有 `if not pet_motion.animation_enabled(self._reduce_motion()): return None` 早退",
    "HEART": "上面已有 `if not pet_motion.animation_enabled(self._reduce_motion()): return 0` 早退",
    "EMOTE_FLOAT": "展示时长：一处**就在** `if self._reduce_motion():` 的分支里，另一处在它的 return 之后（等价 False）",
    "BUBBLE_HOLD": "气泡**展示时长**（这条信息该看多久）刻意不随开关归零 —— 归零 = 闪一下就没",
    "PET_HOLD": "长按阈值是**交互阈值不是动效**：归零 = 按下即摸头（行为改变，不是降级）",
    "THINKING_PULSE": "唯一调用点只在动效开着时被调用（减少动效只停脉动、留着指示）",
}


def _duration_call_sites(src):
    """所有 `…duration_ms(…)` / `…effective_duration(…)` 调用。

    返回 [(行号, 函数名, 令牌名或 None, 第二个实参 AST 或 None)]。
    """
    out = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else \
            (fn.id if isinstance(fn, ast.Name) else None)
        if name not in _DURATION_ENTRY_POINTS:
            continue
        token = None
        if node.args and isinstance(node.args[0], ast.Constant) \
                and isinstance(node.args[0].value, str):
            token = node.args[0].value
        out.append((node.lineno, name, token, node.args[1] if len(node.args) > 1 else None))
    return out


def _is_switch_expr(node):
    """第二个实参是不是"开关表达式"：`…_reduce_motion()` 调用，或 `…_motion_reduced` 属性。

    后者是气泡自己那份开关副本，由 set_motion_reduced 从「减少动效」的生效值写入。
    """
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) \
                and sub.func.attr == "_reduce_motion":
            return True
        if isinstance(sub, ast.Attribute) and sub.attr == "_motion_reduced":
            return True
    return False


def test_all_animation_durations_go_through_the_table():
    """时长都从表里取 —— 而且**取的时候必须把开关带进去**（A-11①：AST 判实参形状，不判字符串）。

    旧版只断言 `duration_ms("X"` 这个**字符串**在源码里出现过：桌上现成的反例照样绿
    （桌宠.py 写死 `duration_ms("RIPPLE", False)` / `duration_ms("HEART", False)`），
    把任意一处的 `self._reduce_motion()` 改成 `False` 也照样绿 —— 那是"没牙齿"的守卫。
    现在按 AST 查**第二个实参的形状**：开关表达式 → 过；其余形状 → 该令牌必须在
    _GRANDFATHERED_SWITCH_FREE 里（逐个祖父化，每条的"为什么等价"写在那张表上）。

    effective_duration **一并查**：它是同一条政策的另一半（数据驱动的时长同样要能被开关
    关掉），A-04 的第三处（落地 Q 弹）正落在它上面。
    """
    sites = []
    for name in _DURATION_SOURCE_FILES:
        for lineno, fn, token, arg in _duration_call_sites(_src(name)):
            sites.append((name, lineno, fn, token, arg))
    # 判据不许退化成空检查：产品侧真的有一批调用点，且四个文件都在扫描面内
    assert len(sites) >= 12, "扫描面太小（这条会退化成空检查）：%r" % (
        [(s[0], s[1], s[3]) for s in sites],)
    for name in _DURATION_SOURCE_FILES:
        assert any(s[0] == name for s in sites), "扫描面漏了 %s" % name
    # 反向对照：形状判据必须真能区分 —— 这两行正是 A-11① 要堵的那个洞
    assert _is_switch_expr(ast.parse("f(1, self._reduce_motion())").body[0].value.args[1])
    assert _is_switch_expr(ast.parse("f(1, pet._reduce_motion())").body[0].value.args[1])
    assert _is_switch_expr(ast.parse("f(1, self._motion_reduced)").body[0].value.args[1])
    assert not _is_switch_expr(ast.parse("f(1, False)").body[0].value.args[1])
    assert not _is_switch_expr(ast.parse("f(1)").body[0].value)
    bad = [(f, ln, fn, tok) for f, ln, fn, tok, arg in sites
           if not (arg is not None and _is_switch_expr(arg))
           and tok not in _GRANDFATHERED_SWITCH_FREE]
    assert bad == [], ("这些调用点的第二个实参不是开关表达式、又不在祖父条款里"
                       "（「减少动效」对它们静默失效）：%r" % (bad,))
    # 换成 AST 之后不许把"谁在消费这些令牌"这件事丢掉
    used = {tok for _, _, _, tok, _ in sites if tok}
    for _token in ("EMOTE_FLOAT", "EAT_SQUASH", "EDGE", "RIPPLE", "PET_HOLD",
                   "THINKING_PULSE", "BUBBLE_HOLD", "BUBBLE_FADE", "FEEDBACK",
                   "JUMP", "BALANCE_ROLL"):
        assert _token in used, "%s 在产品侧已经没有调用点了" % _token
    # A-04 的三处必须在扫描面内，且**走的是开关**（不是靠祖父条款混过去的）
    strict = {(f, tok) for f, _, fn, tok, arg in sites
              if arg is not None and _is_switch_expr(arg)}
    assert ("pet_actions.py", "JUMP") in strict, "跳跃的时长没把开关带进去（A-04 会被静默推翻）"
    assert ("pet_balance.py", "BALANCE_ROLL") in strict, "余额滚动的时长没把开关带进去"
    assert any(f == "桌宠.py" and fn == "effective_duration" and tok is None
               and arg is not None and _is_switch_expr(arg)
               for f, _, fn, tok, arg in sites), "落地 Q 弹的时长没把开关带进去"


# ---------------- C-09：反向钉子——表里每个键都要有人用 ----------------

# 备用档位（**显式祖父化**，每个带理由）；新加的死键不在这张名单里 → 上面那条用例会红。
_DUR_RESERVED = {
    "TRANSITION": "HCI「状态转换」档的定义值（150–250ms）；消费点都用更具体的 BUBBLE_FADE",
    "LARGE": "HCI「大位移」档的定义值（≈300ms）；消费点都用更具体的 EDGE / RIPPLE",
}


def test_every_token_in_the_table_is_actually_used():
    """C-09：反向钉子 —— 表里**每个键**都要有消费点（死配置会让下一个人以为有档位在用）。

    只钉"调用点用的名字在表里"是单向的：表里多出来的键（没人用的档位）永远不会红。
    DUR["TRANSITION"] / DUR["LARGE"] 今天产品侧 **0 个消费点** → 显式登记在 _DUR_RESERVED
    并写明理由；**新出现的死键不在名单里 → 这里当场红**。
    """
    used = {tok for name in _DURATION_SOURCE_FILES
            for _, _, tok, _ in _duration_call_sites(_src(name)) if tok}
    dead = sorted(set(pet_motion.DUR) - used - set(_DUR_RESERVED))
    assert dead == [], "这些令牌在表里、产品侧却没有消费点（死配置）：%r" % (dead,)
    # 反向对照：上面那个表达式必须真能报出死键（否则它是一条恒过的空检查）
    assert sorted({"TRANSITION", "LARGE", "没人用的键"} - used - set(_DUR_RESERVED)) == ["没人用的键"]
    # 祖父条款自己也要被钉住：它们真的还没人用（哪天被用上了，就该从名单里删掉）
    for _k in _DUR_RESERVED:
        assert _k not in used, "%s 已经有消费点了 —— 把它从 _DUR_RESERVED 里删掉" % _k
    assert set(_DUR_RESERVED) <= set(pet_motion.DUR), "祖父名单里混进了表里没有的键"


# ===================== A2：减少动效 =====================

def test_default_follows_system_and_never_downgrades():
    """默认值：读得到系统设置就跟随；**读不到就开启动效**（不擅自替用户降级）。"""
    assert pet_motion.reduce_motion_enabled("auto", None) is False
    assert pet_motion.reduce_motion_enabled("auto", False) is False
    assert pet_motion.reduce_motion_enabled("auto", True) is True
    assert pet_motion.reduce_motion_enabled("on", False) is True     # 显式选择覆盖系统
    assert pet_motion.reduce_motion_enabled("off", True) is False
    assert pet_motion.reduce_motion_enabled("莫名其妙", True) is True  # 坏值按 auto 处理
    # 时长归零语义：关掉动效 = 瞬时（0），不是"短一点"
    assert pet_motion.duration_ms("EDGE", True) == 0
    assert pet_motion.duration_ms("EDGE", False) == pet_motion.DUR["EDGE"]
    assert pet_motion.animation_enabled(True) is False
    assert pet_motion.animation_enabled(False) is True


def test_every_animation_point_is_covered_by_the_switch(win, monkeypatch):
    """**逐条列举**本用例覆盖的动效点（v2.11.0 定版：①–⑧ + 本轮新增 ⑩⑪⑫ = 11 条；
    第 ⑨ 条"合成动作"在同文件的 test_proc_actions_are_covered_by_the_switch）：
    开关打开后"该动的都不动了"，关掉后又动了；**新补的三条还要结果值与开动效时逐项相同**。

    ⚠ 名字里的 "every" 指的是**本用例逐条列举的这些点**，不是"全仓穷举"：
    A-07 那 4 处代码驱动的**位移**（走路 / 甩抛飞行 / 食物托盘飞行 / 拖拽弹簧）按裁决
    **不纳入**「减少动效」（收窄声明 —— 边界写在 pet_motion.effective_duration 的「已知边界」里）。
    ⚠ 名字**故意没改**：这个 nodeid 被 _dev/mutations_agent_a_v2110.json 多处引用
    （含一条 pinned 用例体摘要），改名 = 让那些变异锚点变成"node not found"，
    而那份 spec 不在本轮的独占文件里 → 用 docstring 把覆盖面写准，不动名字。
    """
    # 跳跃会随机喊一句台词（走 show_bubble）→ 与本用例的判据无关，去掉噪音
    monkeypatch.setattr(win, "_say_line", lambda *a, **k: None)
    win._set_reduce_motion(True)
    assert win._reduce_motion() is True
    # ① 悬停光晕：不建动画对象，瞬时到位
    _enter(win)
    assert win._glow_anim is None, "减少动效下悬停光晕仍在做过渡动画"
    assert win._glow_item.opacity() == 1.0, "减少动效下光晕应当是瞬时亮起"
    _leave(win)
    assert win._glow_item.opacity() == 0.0
    # ② 按下描边：**照旧出现**（状态不是动效），但没有过渡动画
    win.mousePressEvent(_Ev())
    assert win._outline_item is not None and win._outline_item.isVisible()
    win.mouseReleaseEvent(_Ev())
    # ③ 点击涟漪：根本不产生
    scene_n = len(win.scene.items())
    assert win._spawn_ripple(QPointF(20, 20)) is None
    assert len(win.scene.items()) == scene_n, "减少动效下涟漪仍被创建"
    # ④ 摸头心形：不产生
    assert win._spawn_hearts() == 0
    assert len(win.scene.items()) == scene_n
    # ⑤ 头顶表情上浮：不建动画（**但表情照旧显示**——它是信息）
    win._show_emote("note")
    assert win._emote_anim is None, "减少动效下表情仍在做上浮动画"
    assert win.emote_item.isVisible(), "减少动效把表情本身也关掉了（那是信息不是装饰）"
    # ⑥ 气泡淡入淡出：瞬时（先从"看不见"起步——已经在显示时本来就不淡入，测不出开关）
    win.bubble.set_motion_reduced(True)
    win.bubble.hide()
    win.bubble._apply_opacity(1.0)
    win.bubble.show_text("测试", QPoint(200, 200))
    assert win.bubble._fade_anim is None
    assert win.bubble._opacity == 1.0
    # ⑦ 贴边：瞬时到位
    scr = win._screen_geo(win.frameGeometry().center())
    if scr is not None:
        win.move(scr.left() + 10, scr.top() + 10)
        win._snap_to_edge()
        assert win._slide_anim is None, "减少动效下贴边仍在缓动"
        assert (win.x(), win.y()) == (scr.left(), scr.top()), "减少动效下贴边没到位"
    # ⑧ AI 在途指示：**照旧可见**（信息），只是不脉动
    win.bubble.hide()   # 收掉气泡：下面反向那一半要验"从看不见到看得见"的淡入
    win.bubble._apply_opacity(1.0)
    win._ai_inflight = True
    assert win._thinking_item.isVisible(), "减少动效把在途指示也关掉了（那是信息不是装饰）"
    assert win._thinking_anim is None
    win._ai_inflight = False
    # ⑩ 跳跃（pet_actions.py 的 do_jump，令牌 JUMP）：不产生在途动画，瞬时到终态
    win.busy = False
    win.move(420, 420)
    jump_home = (win.x(), win.y())
    win.actions.do_jump()
    assert win._tween_anim is None, "减少动效下跳跃仍挂着在途动画"
    assert (win.x(), win.y()) == jump_home, "减少动效下跳跃没落到终态（起点=终点）"
    # ⑪ 落地 Q 弹（桌宠.py 的 _play_landing_bounce）：时长来自**物理数据** → effective_duration
    win._land_squash = 0.6            # 落地压缩量（默认 1.0 = 根本没有 Q 弹）
    win.squash_x = win.squash_y = 1.0
    win._play_landing_bounce()
    # "不产生动画对象"的口径与 test_proc_actions_are_covered_by_the_switch 一致：0ms 的动画在
    # start() 里**同步收尾**（实测 state=Stopped / duration=0），但它的收尾回调是 _bounce_done，
    # 不负责清 _tween_anim 槽 → 在途判据 = "槽为空 **或** 已不在跑"，再加"形变已到终态"。
    assert win._tween_anim is None or \
        win._tween_anim.state() != QAbstractAnimation.State.Running, \
        "减少动效下落地 Q 弹仍在跑（应当是 0ms 瞬时收尾）"
    assert (win.squash_x, win.squash_y) == (1.0, 1.0), "减少动效下落地 Q 弹留下了半截形变"
    # ⑫ 余额徽章滚动（pet_balance.py 的 on_updated，令牌 BALANCE_ROLL）：不滚数字，直接落终值
    win.cfg["api_key"] = "sk-test"    # on_updated 在 Key 为空时会早退（这里要走到滚动那一段）
    win._shown_balance = 1.0
    win._balance_active_gen = 11
    win._manual_pending = False
    win.balance.on_updated(11, 9.0, "CNY", 0.0)
    assert win._balance_anim is None, "减少动效下余额徽章仍挂着滚动动画"
    assert win._shown_balance == 9.0, "减少动效下余额没有落到终值"
    # 三处的"结果值"留档：下面反向那一半要**逐项**比对（减少动效 = 没有过程，结果一样）
    reduced_results = (jump_home, (win.squash_x, win.squash_y), win._shown_balance)

    # ---- 反向：开关关掉之后，同样的动作**又动了** ----
    win._set_reduce_motion(False)
    _enter(win)
    assert win._glow_anim is not None
    _leave(win)
    _drive(win._glow_anim)
    assert win._spawn_ripple(QPointF(20, 20)) is not None
    assert win._spawn_hearts() > 0
    # _set_reduce_motion 自己弹了一条回执气泡 → 重新摆好"从看不见起步"的前提
    win.bubble.hide()
    win.bubble._apply_opacity(1.0)
    win.bubble.show_text("测试2", QPoint(200, 200))
    assert win.bubble._fade_anim is not None
    win._ai_inflight = True
    assert win._thinking_anim is not None
    win._ai_inflight = False
    # ⑩⑪⑫ 反向：同三处，开着动效**真的起播**；推到终态后**结果值与上面逐项相同**
    win.busy = False
    win.move(420, 420)
    win.actions.do_jump()
    assert win._tween_anim is not None, "前提不成立：开着动效时跳跃也没起播"
    _drive(win._tween_anim)
    assert (win.x(), win.y()) == reduced_results[0], "跳跃终态与减少动效下的结果不一致"
    win._land_squash = 0.6
    win.squash_x = win.squash_y = 1.0
    win._play_landing_bounce()
    assert win._tween_anim is not None, "前提不成立：开着动效时落地 Q 弹也没起播"
    assert win._tween_anim.state() == QAbstractAnimation.State.Running, \
        "开着动效时落地 Q 弹没有真的在跑（上面那条'不在跑'就失去对照）"
    assert win._tween_anim.duration() == \
        pet_motion.effective_duration(int(pet_physics.BOUNCE_DURATION * 1000), False), \
        "落地 Q 弹的基准时长没走 pet_physics 的物理数据"
    win._tween_anim.setCurrentTime(win._tween_anim.duration() // 4)
    assert win.squash_y != 1.0, "落地 Q 弹起了个空动画（形变没动）"
    _drive(win._tween_anim)
    assert (win.squash_x, win.squash_y) == reduced_results[1], \
        "落地 Q 弹终态与减少动效下的结果不一致"
    win._shown_balance = 1.0
    win._balance_active_gen = 12
    win._manual_pending = False
    win.balance.on_updated(12, 9.0, "CNY", 0.0)
    assert win._balance_anim is not None, "前提不成立：开着动效时余额也没滚动"
    assert win._balance_anim.duration() == pet_motion.DUR["BALANCE_ROLL"], "余额滚动没走令牌表"
    _drive(win._balance_anim)
    assert win._shown_balance == reduced_results[2], "余额终值与减少动效下的结果不一致"


def test_proc_actions_are_covered_by_the_switch(win):
    """合成动作（呼吸/摇摆/点头）也是**代码驱动**的动效：关掉后一次都不播（瞬时收尾）。

    这是 A2 覆盖面上的第 ⑨ 条——它的时长基准来自**角色数据**（period_ms），
    所以走 effective_duration 而不是令牌表。
    """
    assert pet_motion.effective_duration(1200, True) == 0
    assert pet_motion.effective_duration(1200, False) == 1200
    assert pet_motion.effective_duration("坏值", False) == 0
    spec = {"kind": "sway", "amp": 0.2, "period_ms": 600}
    win.busy = False
    win._set_reduce_motion(True)
    win.squash_x = win.squash_y = 1.0
    win._play_proc("sway", spec)
    # 判据是**确定性**的：0ms 动画在 start() 里同步发 finished → 状态已 Stopped；
    # 若还在 Running，说明它还挂着 1200ms 的振荡（"减少动效"没覆盖到它）。
    assert win._tween_anim is None or \
        win._tween_anim.state() != QAbstractAnimation.State.Running, \
        "减少动效下合成动作还在播（应当是 0ms 瞬时收尾）"
    assert (win.squash_x, win.squash_y) == (1.0, 1.0), "减少动效下合成动作已经改过形变了"
    win._set_reduce_motion(False)
    win.busy = False
    win.squash_x = win.squash_y = 1.0
    win._play_proc("sway", spec)
    assert win._tween_anim is not None, "打开动效后合成动作没有起播"
    assert win._tween_anim.duration() == 1200, "合成动作时长没按角色周期（2 个周期 × 600ms）"
    win._tween_anim.setCurrentTime(150)  # v=0.125 → sin(π/2)=1 → 形变最大
    assert abs(win.squash_x - 1.0) > 1e-6, "合成动作起了个空动画（形变没动）"
    _drive(win._tween_anim)
    assert abs(win.squash_x - 1.0) < 1e-6 and abs(win.squash_y - 1.0) < 1e-6


def test_reduce_motion_toggle_persists_and_clears_inflight(win):
    """开关落盘 + 打开时把在途的一次性动效立刻收干净（不留半截残影）。"""
    win._spawn_ripple(QPointF(20, 20))
    win._spawn_hearts()
    assert win._ripples or win._hearts
    win._set_reduce_motion(True)
    assert win._ripples == [] and win._hearts == []
    saved = json.loads(io.open(main.CONFIG_PATH, encoding="utf-8").read())
    assert saved.get("reduce_motion") == "on", "开关没落盘：%r" % (saved.get("reduce_motion"),)
    win._set_reduce_motion(False)
    saved = json.loads(io.open(main.CONFIG_PATH, encoding="utf-8").read())
    assert saved.get("reduce_motion") == "off"


# ===================== A4：视觉三件套 =====================

def test_hover_glow_does_not_change_geometry(win):
    """① 悬停时**角色的几何尺寸不变**（断言，不是眼看）+ 光晕真的亮起来。"""
    before = _geometry(win)
    _enter(win)
    assert win._glow_item is not None, "悬停没有光晕"
    assert _geometry(win) == before, "悬停改了角色的几何量（A4 明令：悬停只做光晕）"
    _drive(win._glow_anim)
    assert win._glow_item.opacity() == 1.0
    _leave(win)
    assert _geometry(win) == before, "离开时改了角色的几何量"
    _drive(win._glow_anim)
    assert win._glow_item.opacity() == 0.0


def test_press_outline_appears_and_geometry_is_untouched(win):
    """② 按下时尺寸不变 + 描边出现；松手描边收掉、几何仍不变。"""
    before = _geometry(win)
    win.mousePressEvent(_Ev())
    assert win._pressed is True
    assert win._outline_item is not None and win._outline_item.isVisible(), "按下没有描边"
    assert _geometry(win) == before, "按压缩放了角色（A4 明令：按下只补描边、不改几何）"
    win.mouseReleaseEvent(_Ev())
    assert win._pressed is False
    assert not win._outline_item.isVisible(), "松手后描边还挂着"
    assert _geometry(win) == before


def test_press_does_not_fight_an_inflight_breathing_animation(win):
    """按压缩放会与呼吸相位叠加（上一轮复盘）——所以按下**不许写 squash**。"""
    win.busy = False
    win.squash_x, win.squash_y = 1.08, 0.94   # 假装角色正在呼吸/摇摆
    win._apply_transform()
    snap = (win.squash_x, win.squash_y)
    win.mousePressEvent(_Ev())
    assert (win.squash_x, win.squash_y) == snap, "按下把在播的呼吸相位打回了 1.0（会闪一下）"
    win.mouseReleaseEvent(_Ev())


def test_ripple_returns_scene_to_baseline(win):
    """③ 涟漪结束后**无残留控件、无泄漏**：场景对象数回到基线 + 在途表清空。"""
    base = len(win.scene.items())
    item = win._spawn_ripple(QPointF(30, 30))
    assert item is not None and len(win.scene.items()) == base + 1
    assert len(win._ripples) == 1
    _drive(win._ripples[0][1])
    assert win._ripples == [], "涟漪收尾后还在途"
    assert len(win.scene.items()) == base, "涟漪留下了残留绘制项（对象数没回基线）"


def test_ripple_starts_at_the_click_point(win):
    """涟漪从**点击点**扩散（不是从窗口中心）。"""
    item = win._spawn_ripple(QPointF(11, 23))
    r = item.rect()
    assert abs(r.center().x() - 11) < 1e-6 and abs(r.center().y() - 23) < 1e-6
    _drive(win._ripples[0][1])


def test_click_spawns_ripple_but_drag_does_not(win):
    """点击 = 涟漪；拖动 = 没有涟漪（涟漪是"点"的反馈，不是"拖"的）。"""
    win.mousePressEvent(_Ev(gp=(200, 200)))
    win.mouseReleaseEvent(_Ev(gp=(200, 200)))
    assert len(win._ripples) == 1, "点击没有涟漪"
    for _it, _an in list(win._ripples):
        _drive(_an)
    win.mousePressEvent(_Ev(gp=(200, 200)))
    win.mouseMoveEvent(_Ev(gp=(200 + pet_motion.DRAG["THRESHOLD_PX"] + 30, 200),
                           buttons=Qt.MouseButton.LeftButton))
    assert win._moved is True, "前提不成立：这次移动没进入拖拽态"
    win.mouseReleaseEvent(_Ev(gp=(200 + pet_motion.DRAG["THRESHOLD_PX"] + 30, 200)))
    assert len(win._ripples) == 0, "拖动也放了涟漪"


# ===================== A5：贴边缓动 =====================

def _edge_target(win, scr):
    """**独立重算**贴边目标（与 _snap_to_edge 的旧公式逐字相同）。

    这条用例的用途就是钉住"目标位置计算不变"：动画的终点必须等于这个独立算出来的值。
    """
    cx = win.pos().x() + win.width() // 2
    cy = win.pos().y() + win.height() // 2
    x, y = win.pos().x(), win.pos().y()
    if cx < scr.left() + scr.width() / 4:
        x = scr.left()
    elif cx > scr.left() + 3 * scr.width() / 4:
        x = scr.right() - win.width()
    if cy < scr.top() + scr.height() / 4:
        y = scr.top()
    elif cy > scr.top() + 3 * scr.height() / 4:
        y = scr.bottom() - win.height()
    return x, y


def test_edge_slide_eases_to_the_old_target(win):
    """贴边：目标算法不变（独立重算比对）+ 位移走令牌时长 + 不是瞬移。"""
    scr = win._screen_geo(win.frameGeometry().center())
    if scr is None:
        pytest.skip("offscreen 下没有可用屏幕")
    win.move(scr.left() + 10, scr.top() + 10)
    want = _edge_target(win, scr)
    start = (win.x(), win.y())
    win._snap_to_edge()
    assert win._slide_anim is not None, "贴边还是瞬移（没有缓动动画）"
    assert win._slide_anim.duration() == pet_motion.DUR["EDGE"], "贴边时长没走令牌表"
    assert (win.x(), win.y()) == start, "动画还没跑就已经到位了（那不是缓动）"
    _drive(win._slide_anim)
    assert (win.x(), win.y()) == want, "缓动终点与旧目标算法算出来的位置不一致"


def test_edge_slide_instant_when_motion_reduced(win):
    """减少动效：贴边瞬时到位（0ms），不产生动画对象。"""
    scr = win._screen_geo(win.frameGeometry().center())
    if scr is None:
        pytest.skip("offscreen 下没有可用屏幕")
    win._set_reduce_motion(True)
    win.move(scr.left() + 10, scr.top() + 10)
    want = _edge_target(win, scr)
    win._snap_to_edge()
    assert win._slide_anim is None
    assert (win.x(), win.y()) == want


# ===================== B1：拖拽光标 + 阈值 =====================

def test_drag_threshold_blocks_micro_moves(win):
    """小于阈值**不进入拖拽态**：不移动窗口、不算"挪过"（松手仍按戳一下处理）。"""
    win.move(300, 300)
    win.mousePressEvent(_Ev(gp=(400, 400)))
    pos0 = (win.x(), win.y())
    step = pet_motion.DRAG["THRESHOLD_PX"] - 1
    win.mouseMoveEvent(_Ev(gp=(400 + step, 400), buttons=Qt.MouseButton.LeftButton))
    assert (win.x(), win.y()) == pos0, "阈值内的手抖把宠物拖走了"
    assert win._dragging is False and win._moved is False
    win.mouseMoveEvent(_Ev(gp=(400 + pet_motion.DRAG["THRESHOLD_PX"] + 20, 400),
                           buttons=Qt.MouseButton.LeftButton))
    assert win._dragging is True and win._moved is True, "越过阈值还没进入拖拽态"
    assert (win.x(), win.y()) != pos0, "进入拖拽态之后窗口没跟手"
    win.mouseReleaseEvent(_Ev(gp=(400 + pet_motion.DRAG["THRESHOLD_PX"] + 20, 400)))


def test_drag_cursor_states(win):
    """悬停 = 可拖（开手）· 拖拽中 = 抓着（握手）· 松手回到可拖。"""
    _enter(win)
    assert win.cursor().shape() == Qt.CursorShape.OpenHandCursor, "悬停没有'可拖'光标"
    win.mousePressEvent(_Ev(gp=(400, 400)))
    win.mouseMoveEvent(_Ev(gp=(400 + pet_motion.DRAG["THRESHOLD_PX"] + 30, 400),
                           buttons=Qt.MouseButton.LeftButton))
    assert win.cursor().shape() == Qt.CursorShape.ClosedHandCursor, "拖拽中没有'抓着'光标"
    win.mouseReleaseEvent(_Ev(gp=(400 + pet_motion.DRAG["THRESHOLD_PX"] + 30, 400)))
    assert win.cursor().shape() == Qt.CursorShape.OpenHandCursor, "松手后没回到可拖光标"


def test_poke_still_fires_below_the_threshold(win, monkeypatch):
    """阈值不许把"戳一下"弄丢：阈值内的按下-松手仍然是一次戳。"""
    pokes = []
    monkeypatch.setattr(win.mood, "poke", lambda *a, **k: pokes.append(1))
    win.mousePressEvent(_Ev(gp=(400, 400)))
    win.mouseMoveEvent(_Ev(gp=(403, 400), buttons=Qt.MouseButton.LeftButton))
    win.mouseReleaseEvent(_Ev(gp=(403, 400)))
    assert pokes == [1], "阈值内的点击没有戳到（%r）" % (pokes,)


# ===================== B7：双击走事件、不加延迟 =====================

def test_double_click_uses_the_event_and_swallows_the_second_release(win, monkeypatch):
    """双击走 mouseDoubleClickEvent：一次戳 + 一次双击专属反应，**没有第二次戳**。"""
    pokes, blushes = [], []
    monkeypatch.setattr(win.mood, "poke", lambda *a, **k: pokes.append(1))
    monkeypatch.setattr(win.mood, "blush", lambda *a, **k: blushes.append(1))
    monkeypatch.setattr(win, "_say_line", lambda *a, **k: None)
    win.mousePressEvent(_Ev(gp=(400, 400)))
    win.mouseReleaseEvent(_Ev(gp=(400, 400)))
    win.mouseDoubleClickEvent(_Ev(gp=(400, 400)))
    assert blushes == [1], "双击没有触发双击专属动作"
    assert pokes == [1], "双击序列戳了 %d 次（应当只有第一次 release 那一下）" % len(pokes)
    # Qt 的双击序列最后还有一次 release：必须被吞掉
    win.mouseReleaseEvent(_Ev(gp=(400, 400)))
    assert pokes == [1], "双击之后紧跟的 release 又被记成一次戳"


def test_double_click_has_no_delay_timer():
    """用户明确否决过"单击等一等"：鼠标路径里不许出现任何 150ms 计时。"""
    src = _src("桌宠.py")
    tree = ast.parse(src)
    handlers = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in (
                "mousePressEvent", "mouseReleaseEvent", "mouseDoubleClickEvent", "mouseMoveEvent"):
            handlers[node.name] = ast.get_source_segment(src, node)
    assert "mouseDoubleClickEvent" in handlers, "双击没有走 mouseDoubleClickEvent"
    for name, body in handlers.items():
        assert "singleShot" not in body, "%s 里出现了 singleShot（延迟实现的痕迹）" % name
        assert "QTimer(" not in body, "%s 里出现了 QTimer" % name


# ===================== B2：气泡淡入淡出 =====================

def test_bubble_fades_in_and_out_with_tokens(win):
    """淡入：0 → 1（时长走令牌表）；淡出：1 → 0 之后才 hide。"""
    win.bubble.hide()                 # 前提：从"看不见"起步（已经在显示时**不**重新淡入，见下一条）
    win.bubble._apply_opacity(1.0)
    win.bubble.show_text("你好", QPoint(300, 300))
    assert win.bubble._fade_anim is not None, "气泡没有淡入"
    assert win.bubble._fade_anim.duration() == pet_motion.DUR["BUBBLE_FADE"]
    assert win.bubble._opacity == 0.0, "淡入应当从透明起步"
    _drive(win.bubble._fade_anim)
    assert win.bubble._opacity == 1.0
    win.bubble._timer.stop()      # 不等 5s：直接驱动"到点"
    win.bubble._fade_out()
    assert win.bubble._fade_anim is not None, "淡出没有动画"
    _drive(win.bubble._fade_anim)
    assert not win.bubble.isVisible(), "淡出结束后没有隐藏"
    assert win.bubble._opacity == 1.0, "淡出结束后没把不透明度复位（下次淡入会从半透明起步）"


def test_new_bubble_text_never_fades_in_over_old_one(win):
    """B2.3：淡出/显示途中来新文本 → **以新文本为准并立刻满不透明**（不许把新字淡没）。"""
    win.bubble.hide()
    win.bubble._apply_opacity(1.0)
    win.bubble.show_text("第一条", QPoint(300, 300))
    assert win.bubble._fade_anim is not None, "前提：第一条是淡入的"
    win.bubble._fade_anim.setCurrentTime(0)          # 停在"刚起淡入"的中间态
    assert win.bubble._opacity < 1.0, "前提：此刻确实还没到满不透明"
    win.bubble.show_text("第二条", QPoint(300, 300))
    assert win.bubble._text == "第二条", "新文本没有覆盖旧文本"
    assert win.bubble._opacity == 1.0, "新文本还在半透明里（用户这一两百毫秒读不清字）"
    assert win.bubble._fade_anim is None, "已经在终态还起了个空动画"


def test_bubble_fade_is_instant_when_motion_reduced(win):
    """减少动效：瞬时（不建动画对象），且**展示时长照旧**（信息不许被缩短成 0）。"""
    win.bubble.set_motion_reduced(True)
    win.bubble.hide()                 # 前提：从"看不见"起步（那样才走淡入那一支）
    win.bubble._apply_opacity(1.0)
    win.bubble.show_text("你好", QPoint(300, 300))
    assert win.bubble._fade_anim is None, "减少动效下气泡还在淡入"
    assert win.bubble._opacity == 1.0
    assert win.bubble._timer.isActive(), "减少动效把展示时长也归零了（气泡闪一下就没）"
    assert win.bubble._timer.remainingTime() > 0
    # 淡出同样必须瞬时（两个方向都要覆盖：只关一头等于没关）
    win.bubble._timer.stop()
    win.bubble._fade_out()
    assert win.bubble._fade_anim is None, "减少动效下气泡还在淡出"
    assert not win.bubble.isVisible(), "瞬时的淡出没有把气泡收起来"


# ===================== B3：气泡跟随 =====================

def test_bubble_follows_the_character_without_restarting_the_timer(win):
    """跟随：位移**逐像素相等**（同样的锚点算法），且自动隐藏计时不被重置。"""
    win.move(300, 300)
    win.show_bubble("跟着我")
    assert win.bubble.isVisible()
    p0 = (win.bubble.x(), win.bubble.y())
    rem0 = win.bubble._timer.remainingTime()
    win.move(300 + 40, 300 + 25)
    _app().processEvents()
    assert (win.bubble.x() - p0[0], win.bubble.y() - p0[1]) == (40, 25), "气泡没有跟着走"
    rem1 = win.bubble._timer.remainingTime()
    assert rem1 <= rem0, "跟随把自动隐藏计时重置了（用户永远读不完）"


# ===================== B4：摸头心形 =====================

def test_petting_spawns_one_string_of_hearts_that_retire(win, monkeypatch):
    """摸头**一次一串**心形、会自己消失（收尾后对象数回基线）。"""
    if not win._fx_petpet:
        win._ensure_default_frames(win._startup_frame_sets())
    if not win._fx_petpet:
        pytest.skip("素材缺失：摸头帧集为空，这条路径走不到")
    calls = []
    monkeypatch.setattr(win, "_spawn_hearts", lambda: calls.append(1))
    win._press_dist = 0
    win.busy = False
    win._petting = False
    win._start_petting()
    assert calls == [1], "摸头没有触发心形（B4 的接线断了）"
    monkeypatch.undo()
    base = len(win.scene.items())
    assert win._spawn_hearts() == pet_motion.HEART["COUNT"]
    assert len(win.scene.items()) == base + pet_motion.HEART["COUNT"]
    for _it, _an in list(win._hearts):
        _drive(_an)
    assert win._hearts == [], "心形收尾后还在途"
    assert len(win.scene.items()) == base, "心形留下了残留绘制项"


# ===================== B8：AI 在途可见 =====================

def test_ai_inflight_is_visible_and_survives_reduce_motion(win):
    """发起到回复之间必须有可见的在途状态；减少动效只停脉动，**不关掉信息**。"""
    assert win._thinking_item is None or not win._thinking_item.isVisible()
    win._ai_inflight = True
    assert win._thinking_item is not None and win._thinking_item.isVisible(), "AI 在途没有任何可见状态"
    assert win._thinking_anim is not None, "在途指示没有脉动"
    win._set_reduce_motion(True)
    assert win._thinking_item.isVisible(), "减少动效把在途指示关掉了（它是信息不是装饰）"
    assert win._thinking_anim is None, "减少动效下在途指示还在脉动"
    win._ai_inflight = False
    assert not win._thinking_item.isVisible()


def test_ai_inflight_property_drives_the_indicator(win):
    """接线方式：pet_chat 写的就是那个属性（_ai_inflight），不是另一条私有开关。"""
    assert win._ai_inflight is False
    win._ai_inflight = True
    assert win._ai_inflight is True and win._thinking_item.isVisible()
    win._ai_inflight = False
    assert win._ai_inflight is False


# ===================== A3：高对比度 + 键盘 =====================

def test_contrast_is_computed_not_eyeballed():
    """≥ 4.5:1 用算法验：两套调色板的每一对、以及"坏配色被调到达标"。"""
    for dark in (False, True):
        pal = pet_motion.palette(dark)
        for fg_key in ("fg", "border", "muted"):
            ratio = pet_motion.contrast_ratio(pal[fg_key], pal["bg"])
            assert ratio >= 4.5, "%s 的 %s/bg 只有 %.2f:1" % (
                "深色" if dark else "浅色", fg_key, ratio)
    # 用户自己配的"黄字白底"（约 1.07:1）必须被调到达标，且是确定性的
    fixed = pet_motion.ensure_min_contrast("#ffee00", "#ffffff")
    assert pet_motion.contrast_ratio(fixed, "#ffffff") >= 4.5
    assert fixed == pet_motion.ensure_min_contrast("#ffee00", "#ffffff")
    # 已经达标的配色**一个字节都不改**
    assert pet_motion.ensure_min_contrast("#203170", "#ffffff") == "#203170"


def test_high_contrast_switch_applies_and_restores(win):
    """开关：打开换成调色板（算出来的对比度达标）；关掉回到用户那份样式。"""
    before = dict(main.BUBBLE_STYLE)
    win._apply_contrast()
    assert dict(main.BUBBLE_STYLE) == before, "高对比度没开却改了气泡样式"
    win._set_high_contrast(True)
    pal = pet_motion.palette(bool(win._sys_dark))
    assert main.BUBBLE_STYLE["fg"] == pal["fg"] and main.BUBBLE_STYLE["bg"] == pal["bg"]
    assert pet_motion.contrast_ratio(main.BUBBLE_STYLE["fg"], main.BUBBLE_STYLE["bg"]) >= 4.5
    saved = json.loads(io.open(main.CONFIG_PATH, encoding="utf-8").read())
    assert saved.get("high_contrast") == "on"
    win._set_high_contrast(False)
    assert main.BUBBLE_STYLE["fg"] == before["fg"], "关掉高对比度没有回到用户那份样式"


def test_high_contrast_reaches_widgets_and_restores_them_key_by_key(win):
    """C-20：高对比度**不止气泡那一半** —— 挂件/托盘配色（pet_widgets._pal()）也要真的换，
    关掉后**逐键不变**（发布说明原文：「气泡**与挂件**换成两套高对比调色板……
    关闭时挂件/托盘配色一个字节都不变」）。

    旧判据只断言了 main.BUBBLE_STYLE 那一半；最小变异是让 _pal() 恒返回历史配色
    （删掉 if _HC["on"] 那一支）→ 旧判据全绿、这条红。
    _pal() 的消费点是挂件/托盘的 paintEvent（食物托盘 / 余额徽章）与 thinking_pixmap，
    这条用例钉的就是它。
    """
    win._set_high_contrast(False)
    before_pal = dict(pet_widgets._pal())
    before_style = dict(main.BUBBLE_STYLE)
    win._set_high_contrast(True)
    want = pet_motion.palette(bool(win._sys_dark))
    after_pal = dict(pet_widgets._pal())
    assert after_pal == want, "挂件/托盘配色没换成高对比度调色板：%r" % (after_pal,)
    assert after_pal != before_pal, "挂着高对比度，挂件/托盘配色却和原来一模一样"
    for _key in ("fg", "border", "muted"):
        assert pet_motion.contrast_ratio(after_pal[_key], after_pal["bg"]) >= 4.5, _key
    win._set_high_contrast(False)
    assert dict(pet_widgets._pal()) == before_pal, "关掉高对比度后挂件/托盘配色没有逐键复原"
    assert dict(main.BUBBLE_STYLE) == before_style, "关掉高对比度后气泡样式没有逐键复原"


def test_keyboard_escape_and_enter_route_to_window_actions(win):
    """Esc = 收进托盘（与 closeEvent 同一语义）；Enter/Space = 主交互。"""
    win.show()
    win.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                Qt.KeyboardModifier.NoModifier))
    assert not win.isVisible(), "Esc 没有把窗口收起来"
    called = []
    win._primary_action = lambda: called.append(1)
    win.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Return,
                                Qt.KeyboardModifier.NoModifier))
    win.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Space,
                                Qt.KeyboardModifier.NoModifier))
    assert called == [1, 1], "Enter/Space 没有触发主交互"


def _shortcut_hits(src):
    """源码里**真的用到**的快捷键 API（按 AST 名字判，注释/文档里的提及不算）。"""
    banned = {"QShortcut", "ApplicationShortcut", "WindowShortcut"}
    hits = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Name) and node.id in banned:
            hits.append(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in banned:
            hits.append(node.attr)
        elif isinstance(node, ast.alias) and (node.name.split(".")[-1] in banned
                                              or (node.asname or "") in banned):
            hits.append(node.name)
    return hits


def test_no_global_shortcut_and_no_focus_stealing(win):
    """**不许抢全局 Esc**：全仓没有 QShortcut/应用级快捷键，窗口也不抢焦点。"""
    for name in ("桌宠.py", "pet_widgets.py", "pet_motion.py"):
        assert _shortcut_hits(_src(name)) == [], "%s 里出现了快捷键 API" % name
    # 反例对照：这段合成源码必须被认出来（否则上面那条是"恒过"的空检查）
    assert _shortcut_hits("from PySide6.QtGui import QShortcut\n") == ["QShortcut"]
    assert _shortcut_hits("x = Qt.ShortcutContext.ApplicationShortcut\n") == ["ApplicationShortcut"]
    assert bool(win.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus),         "窗口开始抢键盘焦点了（Esc 会抢到用户当前应用的按键）"
    assert win.focusPolicy() != Qt.FocusPolicy.NoFocus


def test_tray_menu_carries_primary_action_and_toggles(win):
    """键盘可达的兜底入口：托盘菜单里有主交互与两个无障碍开关，且状态与配置一致。"""
    texts = [a.text() for a in win.tray.contextMenu().actions()]
    assert any("戳一下" in t for t in texts), texts
    assert any("减少动效" in t for t in texts), texts
    assert any("高对比度" in t for t in texts), texts
    act = [a for a in win.tray.contextMenu().actions() if "减少动效" in a.text()][0]
    assert act.isCheckable() and act.isChecked() == win._reduce_motion()
    act.setChecked(True)
    assert win._reduce_motion() is True and win.cfg["reduce_motion"] == "on"
    act.setChecked(False)
    assert win._reduce_motion() is False and win.cfg["reduce_motion"] == "off"

# ===================== B 的判据清单：补齐的边角（异常路径 / 反例对照） =====================

def test_drag_cursor_restored_on_every_exit_path(win):
    """B1.1：光标三态闭环，**异常路径也要回弹**（Esc 打断是"拖到一半"的常见形态）。"""
    _enter(win)
    win.mousePressEvent(_Ev(gp=(400, 400)))
    win.mouseMoveEvent(_Ev(gp=(400 + pet_motion.DRAG["THRESHOLD_PX"] + 30, 400),
                           buttons=Qt.MouseButton.LeftButton))
    assert win.cursor().shape() == Qt.CursorShape.ClosedHandCursor
    win.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                Qt.KeyboardModifier.NoModifier))
    assert win.cursor().shape() == Qt.CursorShape.ArrowCursor, "Esc 打断后光标卡在『抓着』"
    assert win._dragging is False and win._pressed is False, "Esc 打断后按压/拖拽态没复位"
    assert not win.isVisible(), "Esc 没有把窗口收起来"


def test_release_outside_the_window_does_not_leave_the_open_hand(win):
    """B1.1 第二条路径：拖到窗外松手 → 光标不该留在"可拖"。"""
    _enter(win)
    win.mousePressEvent(_Ev(gp=(400, 400)))
    win.mouseMoveEvent(_Ev(gp=(400 + pet_motion.DRAG["THRESHOLD_PX"] + 30, 400),
                           buttons=Qt.MouseButton.LeftButton))
    _leave(win)                      # 拖出窗口：Qt 会先发 leave
    win.mouseReleaseEvent(_Ev(gp=(900, 900)))
    assert win.cursor().shape() == Qt.CursorShape.ArrowCursor, "窗外松手后还留着开手光标"


def test_petting_survives_the_drag_threshold(win):
    """B1.3（最容易被改坏的一条）：加了阈值之后，**按住不动仍要能摸头**。"""
    if not win._fx_petpet:
        win._ensure_default_frames(win._startup_frame_sets())
    if not win._fx_petpet:
        pytest.skip("素材缺失：摸头帧集为空，这条路径走不到")
    _enter(win)
    win.mousePressEvent(_Ev(gp=(400, 400)))
    assert win._hold_timer.isActive(), "按下没有起长按计时（摸头永远不会触发）"
    hold_before = win._hold_timer.remainingTime()
    win.mouseMoveEvent(_Ev(gp=(403, 400), buttons=Qt.MouseButton.LeftButton))  # 阈值内的手抖
    assert win._hold_timer.isActive(), "阈值内的手抖把长按计时停了（摸头被阈值吃掉）"
    assert win._hold_timer.remainingTime() <= hold_before
    win._hold_timer.timeout.emit()   # 时间到（等价于真按住 1.5s）
    assert win._petting is True, "按住不动没能触发摸头"
    win._end_petting()


def test_press_feedback_is_synchronous(win):
    """B1.4：press 里立刻有的反馈**一秒都不许延后**（探针：状态在同一个调用里就变了）。"""
    win._hold_timer.stop()
    win.mousePressEvent(_Ev(gp=(400, 400)))
    assert win._pressed is True and win._outline_item.isVisible(), "按下反馈不是同步出现的"
    assert win._hold_timer.isActive() and win._hold_timer.remainingTime() > 0
    assert win._dragging is False and win._moved is False
    win.mouseReleaseEvent(_Ev(gp=(400, 400)))


def test_no_override_cursor_anywhere():  # noqa: D103
    """B1.5：不许用 QApplication.setOverrideCursor（全局光标栈，异常路径不回弹）。"""
    for name in ("桌宠.py", "pet_widgets.py"):
        assert "setOverrideCursor" not in _src(name), "%s 里用了全局光标栈" % name


def test_bubble_click_semantics_unchanged_after_fade(win):
    """B2.4：淡入淡出不改命中语义——点气泡仍然发 clicked。"""
    hits = []
    win.bubble.clicked.connect(lambda: hits.append(1))
    win.bubble.hide()
    win.bubble._apply_opacity(1.0)
    win.bubble.show_text("点我", QPoint(300, 300))
    _drive(win.bubble._fade_anim)
    win.bubble.mousePressEvent(_Ev(pos=(5, 5), gp=(300, 300)))
    assert hits == [1], "淡入之后点气泡不再发 clicked"


def test_bubble_leaves_no_animation_children(win):
    """B2.5：淡入淡出跑完后不留动画子对象（退出路径也不留）。"""
    win.bubble.hide()
    win.bubble._apply_opacity(1.0)
    win.bubble.show_text("残留检查", QPoint(300, 300))
    _drive(win.bubble._fade_anim)
    win.bubble._fade_out()
    if win.bubble._fade_anim is not None:
        _drive(win.bubble._fade_anim)
    _app().processEvents()
    # deleteLater 的回收走 DeferredDelete，processEvents 默认不处理它（要显式派发）
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    left = win.bubble.findChildren(QVariantAnimation)
    assert win.bubble._fade_anim is None, "动画槽没清"
    assert not left, "气泡留下了未回收的动画子对象：%r" % (left,)


def test_bubble_follow_keeps_the_screen_clamp(win):
    """B3.2：跟随复用同一份屏幕夹紧——贴到屏幕右边缘时不许把气泡推出屏外。"""
    from pet_screen import screen_geometry_at
    scr = screen_geometry_at(QPoint(win.x(), win.y()))[1]
    if scr is None:
        pytest.skip("offscreen 下没有可用屏幕")
    win.move(scr.right() - win.width() - 2, scr.top() + 200)
    win.show_bubble("贴边时的气泡")
    assert win.bubble.isVisible()
    assert win.bubble.x() + win.bubble.width() <= scr.right() + 1, "气泡被推出屏幕右边界"
    win.move(win.x() - 30, win.y())
    _app().processEvents()
    assert win.bubble.x() + win.bubble.width() <= scr.right() + 1, "跟随时越过了屏幕右边界"


def test_bubble_follow_does_not_leak_widgets(win):
    """B3.5：连续跟随不新建窗口/不泄漏（对象数守恒）。"""
    win.show_bubble("跟随泄漏检查")
    before = len(_app().topLevelWidgets())
    for i in range(100):
        win.move(200 + i, 200 + (i % 7))
    _app().processEvents()
    after = len(_app().topLevelWidgets())
    assert after == before, "跟随过程中 topLevel 窗口数变了：%d → %d" % (before, after)
    assert win.bubble.isVisible()


def test_two_petting_strings_still_return_to_baseline(win):
    """B4.3：连续摸两次（两串心形）→ 全部收尾后仍回基线。"""
    base = len(win.scene.items())
    win._spawn_hearts()
    win._spawn_hearts()
    assert len(win.scene.items()) == base + 2 * pet_motion.HEART["COUNT"]
    for _it, _an in list(win._hearts):
        _drive(_an)
    assert win._hearts == [] and len(win.scene.items()) == base, "两串心形留下了残留"


def test_mood_heart_gate_for_petting_is_untouched(win, monkeypatch):
    """B4.4：**不许推翻 S3 的修复**——摸摸头期间抑制的是 emote 的 heart；新心形走另一条路。"""
    calls = []
    monkeypatch.setattr(win, "_show_emote", lambda kind: calls.append(kind))
    win._petting = True
    win.busy = False
    win._mood_emote("heart")
    assert calls == [], "摸摸头期间的情绪 heart 没有被抑制（S3 的修复被推翻了）"
    win._petting = False
    win._mood_emote("heart")
    assert calls == ["heart"], "对照：不在摸头时情绪 heart 应当照常展示"


def test_hearts_do_not_open_a_new_top_level_window(win):
    """B4.6：心形只画在角色场景里，**不许新开置顶窗口**（否则会压住气泡文字）。"""
    before = len(_app().topLevelWidgets())
    win._spawn_hearts()
    after = len(_app().topLevelWidgets())
    assert after == before, "心形开了新窗口：%d → %d" % (before, after)
    for _it, _an in list(win._hearts):
        assert _it.scene() is win.scene, "心形没有画在角色场景里"
        _drive(_an)


def test_single_and_double_click_are_different_actions(win, monkeypatch):
    """B7.2/B7.3/B7.4：双击的动作与单击不同、状态收敛、且只认左键。"""
    poke, blush = [], []
    monkeypatch.setattr(win.mood, "poke", lambda *a, **k: poke.append(1))
    monkeypatch.setattr(win.mood, "blush", lambda *a, **k: blush.append(1))
    monkeypatch.setattr(win, "_say_line", lambda *a, **k: None)
    win.mousePressEvent(_Ev(gp=(400, 400)))
    win.mouseReleaseEvent(_Ev(gp=(400, 400)))
    assert poke == [1] and blush == [], "单击的动作集变了"
    win.mouseDoubleClickEvent(_Ev(gp=(400, 400)))
    assert blush == [1], "双击没有自己的动作（与单击无法区分）"
    win.mouseReleaseEvent(_Ev(gp=(400, 400)))   # 双击序列里最后那次 release
    assert win.busy is False and win._petting is False and win._suppress_release is False, \
        "双击之后状态没有收敛"
    # 只认左键：右键双击不许触发（用**真** QMouseEvent：非左键会走 super()，替身过不了签名）。
    # ⚠ super() 的 Qt 默认实现会转调 mousePressEvent → 右键会去开**真菜单**（exec 永久阻塞，
    # 正是"测试健壮性第一条"那个坑）→ 必须先把开菜单 stub 掉。
    monkeypatch.setattr(win, "_open_menu", lambda gp: None)
    win.mouseDoubleClickEvent(QMouseEvent(
        QEvent.Type.MouseButtonDblClick, QPointF(10, 10), QPointF(400, 400),
        Qt.MouseButton.RightButton, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier))
    assert blush == [1], "右键双击也触发了双击动作"