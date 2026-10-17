# -*- coding: utf-8 -*-
"""v2.11.0 · W3-d「持续气泡 + 系统通知」的判据（气泡常驻/定时 + 托盘通知 + 限流）。

来路（别写成"用户要求"）：本项来自**用户 #194 提交的两份附件方案**（"① 持续气泡 +
系统通知"，正文 AI 起草）+ **2026-10-16 用户裁决并入 v2.11.0**；登记在
`_dev/REMAINING.md` §十三 第 ① 行。**这 9 项没有一项是用户原话。**

两组用例，**每条都写明"把哪一行拿掉/改坏它会红"**（本仓硬规矩：判据必须能真失败）：

A 持续气泡（pet_widgets.Bubble.show_text 的 `hold_ms`）
  A-1 默认调用 → 计时器 active，且 interval **逐值等于** pet_motion.DUR["BUBBLE_HOLD"]
  A-2 「减少动效」开着时默认时长**照旧**（信息不许被缩短成 0ms）
  A-3 hold_ms=0 / 负数 → **常驻**：计时器不 active、气泡仍可见
      （前置先起一条 5s 的：常驻这一支必须把它停掉，否则"设成常驻反而更短命"）
  A-4 hold_ms=1500 → interval **逐值等于** 1500
  A-5 常驻之后来一条默认气泡 → 恢复 5s 计时（自愈，不留粘滞状态）
  A-6 常驻之后 hide() 有效；隐藏同时把计时停掉（不留在看不见的窗口上收尾的僵尸计时）
  A-7 反复 show_text 不攒计时器（子 QTimer 数恒为 1，回基线）
  A-8 hold_ms 坏值（非数值）→ 回到默认 5s，不抛

B 系统通知（pet_notify.notify）
  B-1 真探针这一支：offscreen 时系统托盘不可用 → 直接 False，**一次 showMessage 都不调**
  B-2 tray=None / 没有 showMessage → False，且**不探测托盘、不占限流名额**
  B-3 假 tray + 托盘可用 → **只调一次**，实参逐字是 (title, text)
  B-4 同正文在限流窗口内第二次 → 不再调（False）
  B-5 超过窗口 → 又调；窗口边界由 throttle_sec 参数算（不是写死 30，且 =窗口 那次要放行）
  B-6 mute=True → 不发，且**不占限流名额**（关掉过的那句话，打开开关后第一条照发）
  B-7 showMessage 抛异常 → False，不冒到调用方
  B-8 throttle_sec 坏值 → 回默认窗口，不抛

驱动口径：**不看墙钟**——计时器只读 `isActive()/interval()`；限流注入 `now`
（monotonic 秒序列），不 sleep。
"""
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import pet_motion  # noqa: E402
import pet_notify  # noqa: E402
import pet_widgets  # noqa: E402
from PySide6.QtCore import QEvent, QPoint, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

# 锚点随便给一个屏内点：offscreen 也有主屏，Bubble 自己会算出窗口左上角
ANCHOR = QPoint(300, 300)


def _pump():
    """把 deleteLater 的 DeferredDelete 事件真的处理掉（对象数才回得到基线）。"""
    QApplication.processEvents()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()


@pytest.fixture
def bubble():
    """一个干净的气泡窗口；收尾把计时 / 在途动画 / 窗口全收干净。"""
    b = pet_widgets.Bubble()
    try:
        yield b
    finally:
        b._timer.stop()
        b._stop_fade()
        b.hide()
        b.deleteLater()
        _pump()


@pytest.fixture(autouse=True)
def _clear_throttle():
    """限流是 pet_notify 的**模块级状态**：用例之间必须清干净，否则跑的顺序会改变结论。"""
    pet_notify._SEEN.clear()
    try:
        yield
    finally:
        pet_notify._SEEN.clear()


@pytest.fixture
def tray_available(monkeypatch):
    """把"系统托盘可用"那支的探针钉成 True（**只替换探针，不骗 Qt**）。

    为什么必须可注入：offscreen 上 QSystemTrayIcon.isSystemTrayAvailable() 天生为假，
    否则 B-3~B-8 六条会全部落在"托盘不可用"那一支上，showMessage 一次都走不到。
    """
    monkeypatch.setattr(pet_notify, "_probe_tray_available", lambda: True)


class _FakeTray(object):
    """只带 showMessage 的托盘替身：记录每次调用的实参（鸭子类型，不伪造 Qt 内部状态）。"""

    def __init__(self, raises=False):
        self.calls = []
        self._raises = raises

    def showMessage(self, title, text):
        self.calls.append((title, text))
        if self._raises:
            raise RuntimeError("托盘对象在途被销毁")


# ===================== A 持续气泡 =====================

def test_default_hold_is_the_five_second_token(bubble):
    """A-1：默认调用 = 既有行为，**逐值**断言 interval，不是"有个计时器"。

    能真失败：把 _set_hold 的默认支改成 `self._timer.start(1000)`（或任何不等于
    pet_motion.DUR["BUBBLE_HOLD"] 的字面量）→ interval 逐值断言红。
    """
    bubble.show_text("默认时长", ANCHOR)
    assert bubble.isVisible(), "默认调用没有把气泡显示出来"
    assert bubble._timer.isActive(), "默认调用没有起自动隐藏计时（气泡会常驻不消失）"
    assert bubble._timer.interval() == pet_motion.DUR["BUBBLE_HOLD"], \
        "展示时长没有走令牌表：interval=%r，令牌=%r" % (
            bubble._timer.interval(), pet_motion.DUR["BUBBLE_HOLD"])
    assert bubble._hold_ms is None


def test_default_hold_is_not_zeroed_by_reduce_motion(bubble):
    """A-2：「减少动效」只关时长动画，**不关展示时长**（归零 = 气泡闪一下就没）。

    能真失败：把默认支写成 `start(pet_motion.duration_ms("BUBBLE_HOLD", self._motion_reduced))`
    （这看起来"很一致"，是全仓最容易被顺手写成的那一行）→ interval=0 且不 active → 红。
    """
    bubble.set_motion_reduced(True)
    bubble.show_text("减少动效下的默认", ANCHOR)
    assert bubble._timer.isActive(), "减少动效把展示时长也归零了（用户读不到这条信息）"
    assert bubble._timer.interval() == pet_motion.DUR["BUBBLE_HOLD"]


@pytest.mark.parametrize("hold", [0, -1, -2500])
def test_zero_or_negative_hold_is_persistent(bubble, hold):
    """A-3：hold_ms ≤ 0 = **常驻**，而且必须把上一条的 5s 计时停掉。

    "先来一条普通的"是这条用例的关键前置：只测"新气泡不 active"的话，
    实现里漏掉 `self._timer.stop()` 也照样绿（5s 后它才把常驻气泡关掉）。
    能真失败：删掉 _set_hold 里常驻支的 `self._timer.stop()` → isActive() 断言红。
    """
    bubble.show_text("先来一条普通的", ANCHOR)
    assert bubble._timer.isActive(), "前置：普通气泡确实在倒计时"
    bubble.show_text("常驻", ANCHOR, hold_ms=hold)
    assert bubble._text == "常驻", "常驻气泡没有换成新文本"
    assert bubble.isVisible(), "常驻气泡必须看得见"
    assert not bubble._timer.isActive(), \
        "常驻气泡还挂着自动隐藏计时（到点就会被上一条的计时关掉）"
    assert bubble._hold_ms == hold


def test_positive_hold_is_the_interval_verbatim(bubble):
    """A-4：hold_ms=1500 → interval 逐值等于 1500（不是"大于 0 就行"）。

    能真失败：把正数支写成 `start(pet_motion.DUR["BUBBLE_HOLD"])`（忘了传值）→ 红。
    """
    bubble.show_text("只看 1.5 秒", ANCHOR, hold_ms=1500)
    assert bubble._timer.isActive()
    assert bubble._timer.interval() == 1500
    assert bubble._hold_ms == 1500


def test_a_normal_bubble_replaces_a_persistent_one(bubble):
    """A-5：常驻之后再来一条**默认**气泡 → 恢复 5s 计时（"常驻之后再也关不掉"的反面）。

    能真失败：把常驻实现成粘滞状态（例如 `if self._hold_ms == 0: return` 加在 _set_hold
    的开头）→ 新气泡不再计时，isActive() 红。
    """
    bubble.show_text("常驻", ANCHOR, hold_ms=0)
    assert not bubble._timer.isActive(), "前置：常驻气泡没有计时"
    bubble.show_text("新的一条", ANCHOR)
    assert bubble._text == "新的一条"
    assert bubble._timer.isActive(), "常驻之后来的普通气泡没有重新计时（常驻变成了粘滞状态）"
    assert bubble._timer.interval() == pet_motion.DUR["BUBBLE_HOLD"]


def test_hide_ends_a_persistent_bubble_and_kills_any_timer(bubble):
    """A-6：常驻气泡能被 hide() 正常取代；隐藏还要把**任何**在途计时停掉。

    两条判据分开写（都能单独红）：
      · "常驻关不掉" → 常驻之后 isVisible() 必须变假；
      · "僵尸计时"   → 普通气泡被隐藏后计时器必须不 active（否则 5s 后它会在一个
        看不见的窗口上再起一次淡出动画 = 收尾后还有东西在动）。
    能真失败：删掉 `Bubble.hide` 里的 `self._timer.stop()` → 最后那条断言红。
    """
    bubble.show_text("常驻", ANCHOR, hold_ms=0)
    bubble.hide()
    assert not bubble.isVisible(), "常驻气泡关不掉"
    assert not bubble._timer.isActive()

    bubble.show_text("再来一条", ANCHOR)
    assert bubble.isVisible() and bubble._timer.isActive(), "隐藏之后气泡起不来了"
    bubble.hide()
    assert not bubble.isVisible()
    assert not bubble._timer.isActive(), "隐藏后计时还在跑（到点会去动一个看不见的窗口）"


def test_repeated_show_text_never_stacks_timers(bubble):
    """A-7：反复弹气泡不攒计时器——**同一个** QTimer 复用，子 QTimer 数回到基线。

    能真失败：把 _set_hold 改成"每次新建一个 QTimer(self)"（最常见的那种改法）→
    计数从 1 变 6 → 红。
    """
    n0 = len(bubble.findChildren(QTimer))
    assert n0 == 1, "前置：一个气泡只该有一个自动隐藏计时器，实际 %d" % n0
    for i, hold in enumerate((None, 0, 1500, None, -1)):
        bubble.show_text("第%d条" % i, ANCHOR, hold_ms=hold)
    assert len(bubble.findChildren(QTimer)) == n0, "弹了几条气泡就多出几个计时器（计时器泄漏）"
    assert bubble._timer in bubble.findChildren(QTimer)


def test_garbage_hold_falls_back_to_the_default(bubble):
    """A-8：坏值（非数值）→ 回到默认 5s，既不常驻也不闪一下就没。

    能真失败：把 _set_hold 里的 `except (TypeError, ValueError)` 改成 `except ()`
    （= 不吞了）→ float/int("一会儿") 抛出来，用例红。
    """
    bubble.show_text("坏值", ANCHOR, hold_ms="一会儿")
    assert bubble._timer.isActive(), "坏值让气泡变成了常驻"
    assert bubble._timer.interval() == pet_motion.DUR["BUBBLE_HOLD"]


# ===================== B 系统通知 =====================

def test_real_probe_reports_no_tray_and_sends_nothing():
    """B-1：**真探针**这一支——offscreen（本机用例环境 / CI）没有系统托盘。

    跑的是真的 `QSystemTrayIcon.isSystemTrayAvailable()`，不是替身：它会走
    `if not _probe_tray_available(): return False` 那一行，**一次 showMessage 都不该调**。
    有托盘的机器上跳过（那是另一条分支，由下面 monkeypatch 探针的用例覆盖）。
    能真失败：删掉 notify 里的可用性判断 → 这条在 offscreen 上会"发出去"→ 红。
    """
    if pet_notify._probe_tray_available():
        pytest.skip("本机有系统托盘：这条钉的是 offscreen / 无托盘分支")
    tray = _FakeTray()
    assert pet_notify.notify(tray, "桌宠", "没有托盘时不该发") is False
    assert tray.calls == [], "系统托盘不可用时仍然调了 showMessage（消息会静默丢失）"


def test_no_tray_object_is_a_safe_no_op(monkeypatch):
    """B-2：tray 为 None / 没有 showMessage → False，而且**不探测、不占限流名额**。

    ⚠ 只断言"返回 False"这一条是**没有牙**的：把守门删掉之后 showMessage 抛的
    AttributeError 会被下面那个 try/except 接住，返回值照样是 False（实测 M-B2 变异
    在旧版判据上是"1 passed"）。所以这里钉两件被守门**独占**保证的事：
      ① 没有托盘对象时**连系统托盘可用性都不问**（结果对结论毫无影响，还白问一次平台）；
      ② **不占限流名额**——否则托盘晚一点起来时，同一句话的第一条会被这条空调用吞掉。
    能真失败：删掉 `if tray is None or not hasattr(tray, "showMessage"): return False`
    → 探针被调用（calls 非空）**且** _SEEN 里留下记录 → 两条断言双红。
    """
    calls = []

    def _probe():
        calls.append(1)
        return True

    monkeypatch.setattr(pet_notify, "_probe_tray_available", _probe)
    assert pet_notify.notify(None, "桌宠", "没有托盘对象") is False
    assert pet_notify.notify(object(), "桌宠", "这个对象没有 showMessage") is False
    assert calls == [], "没有托盘对象还去问系统托盘（最便宜的一支必须最先返回）"
    assert pet_notify._SEEN == {}, "没有托盘对象的调用占了限流名额"


def test_fake_tray_gets_exactly_one_showmessage_with_the_right_args(tray_available):
    """B-3：假 tray → **只调一次**，实参逐字是 (title, text)。

    能真失败：把实参顺序写成 (text, title) → 元组逐字断言红；多传一个 icon/msecs
    → 替身的 showMessage 只收两个参数 → TypeError → 红（顺带钉住"只传两参"）。
    """
    tray = _FakeTray()
    assert pet_notify.notify(tray, "大肥鱼桌宠", "到点啦", now=1000.0) is True
    assert tray.calls == [("大肥鱼桌宠", "到点啦")], "showMessage 的实参不对：%r" % (tray.calls,)


def test_same_text_is_throttled_inside_the_window(tray_available):
    """B-4：同一条正文在限流窗口内第二次 → 不再调（返回 False）。

    能真失败：删掉 `if last is not None and (t - last) < window: return False`
    → 第二次照发 → 调用数断言红。
    """
    tray = _FakeTray()
    window = pet_notify.DEFAULT_THROTTLE_SEC
    assert pet_notify.notify(tray, "桌宠", "记得喝水", now=1000.0) is True
    assert pet_notify.notify(tray, "桌宠", "记得喝水", now=1000.0 + window - 0.001) is False
    assert len(tray.calls) == 1, "同一句话在窗口内又发了一次（连发会在托盘里互相顶掉）"


def test_after_the_window_it_sends_again_and_the_window_is_configurable(tray_available):
    """B-5：超过窗口 → 又调；窗口边界按 `throttle_sec` 算（不是写死 30s）。

    能真失败：① 把比较写成 `(t - last) <= window` → 恰好等于窗口那次被挡 → 红；
    ② 忽略 throttle_sec 而用 DEFAULT_THROTTLE_SEC → now=1005 那次仍在 30s 窗口内 → 红。
    """
    tray = _FakeTray()
    assert pet_notify.notify(tray, "桌宠", "记得喝水", throttle_sec=5, now=1000.0) is True
    assert pet_notify.notify(tray, "桌宠", "记得喝水", throttle_sec=5, now=1004.0) is False
    assert pet_notify.notify(tray, "桌宠", "记得喝水", throttle_sec=5, now=1005.0) is True, \
        "越过窗口（>=）之后应当再发一次"
    # 不同正文各发各的：限流是"同一条文本"，不是"整个模块一条"
    assert pet_notify.notify(tray, "桌宠", "另一句话", throttle_sec=5, now=1005.0) is True
    assert [c[1] for c in tray.calls] == ["记得喝水", "记得喝水", "另一句话"]


def test_mute_sends_nothing_and_does_not_eat_the_throttle_slot(tray_available):
    """B-6：mute=True → 不发；而且**不占限流名额**（关掉过的那句话，打开开关后第一条照发）。

    能真失败：① 删掉 `if mute: return False` → 调用数红；
    ② 把 mute 判断挪到限流记账**之后** → 第二条（mute 关掉后）被窗口挡 → 红。
    """
    tray = _FakeTray()
    assert pet_notify.notify(tray, "桌宠", "喝水", mute=True, now=1000.0) is False
    assert tray.calls == [], "静音状态下仍然调了 showMessage"
    assert pet_notify.notify(tray, "桌宠", "喝水", now=1001.0) is True
    assert len(tray.calls) == 1


def test_showmessage_failure_is_reported_not_raised(tray_available):
    """B-7：showMessage 抛异常 → 返回 False，不冒到调用方（托盘对象被销毁的现场）。

    能真失败：删掉 notify 里包住 showMessage 的 try/except → RuntimeError 冒出来 → 用例红。
    """
    tray = _FakeTray(raises=True)
    assert pet_notify.notify(tray, "桌宠", "托盘炸了", now=1000.0) is False
    assert len(tray.calls) == 1, "异常路径下没记录到这次尝试（计数只该是 1 次）"


def test_bad_throttle_value_falls_back_to_the_default(tray_available):
    """B-8：throttle_sec 坏值 → 回默认窗口，不抛（调用方可能从配置里读它）。

    能真失败：删掉 `try/except (TypeError, ValueError): window = DEFAULT_THROTTLE_SEC`
    → float("一会儿") 抛 ValueError → 用例 error；回退成 0 → 窗口内第二次会发 → 红。
    """
    tray = _FakeTray()
    assert pet_notify.notify(tray, "桌宠", "坏窗口", throttle_sec="一会儿", now=1000.0) is True
    assert pet_notify.notify(
        tray, "桌宠", "坏窗口", throttle_sec="一会儿",
        now=1000.0 + pet_notify.DEFAULT_THROTTLE_SEC - 1.0) is False
    assert len(tray.calls) == 1
