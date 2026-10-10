# -*- coding: utf-8 -*-
r"""时间轴 + 画面级验收（v2.2.5）：**相位无关**——任选喂食时刻，相对时间轴都必须成立。

相对期望（以喂食时刻 T 为基准，v2.2.5 起 zzz 挂喂食事件时钟）：
  T       喂食 → 画面切吃饱静态图（吃帧窗口 ~1.6s 后恒为 character_full.png）
  T+10s   消化窗口内头顶 zzz（叠在吃饱形态上，不换形态）
  T+12s   消化结束 → 常态 + sparkle；此后安静
  T+25s   第二次 zzz（消化结束 +13s 的"饭后小盹"）
  T+12~T+25 之间：无任何随机动作/zzz（安静期）
画面：T~T+12s 消化窗口内不出现常态 idle 帧；消化后回到常态 idle 帧动画。
跑法：cd 大肥鱼桌宠_绿色版 && .\python.exe _dev\repro_quiet.py

v2.4（审查 附-1 修复）：此前本脚本在"三次相位都跑完了"之后**不退出**（Windows 上
挂死、CPU 冻结、无输出——管道缓冲把已有输出也扣住了）。现在：
  · 所有进度/结论都走 log() 立刻 flush，重定向到文件/管道也能实时看到卡在哪一相位；
  · 每相位 + 全程各有**线程级** watchdog（不是 QTimer——事件循环卡住时 QTimer 不会
    再触发）：超时即打印诊断（相位、已采样的画面上限、全部线程栈）并以退出码 2 结束；
  · 相位之间显式收尾：停采样定时器、关窗口、处理一轮事件队列，避免上一相位的窗口/
    定时器把下一相位或解释器退出拖住。
"""
import faulthandler
import os
import sys
import tempfile
import threading
import time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# v2.2.7（审查 中-2）：默认 GBK 控制台下打印 ✓ 会 UnicodeEncodeError → 全过也 exit 1。
# 与 _verify_v13.py / _verify_green.py 同款处理：强制 stdout 为 utf-8 且不抛。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass  # 有意忽略：老解释器/非标准流上无 reconfigure，退化为原编码
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import 桌宠 as main
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

app = QApplication([])
RESULTS = []
# 诊断用全局：watchdog 超时时能说清"卡在哪一相位、进度到哪一步"
PROGRESS = {"phase": None, "step": "启动", "shots": [], "events": []}
STOP_FLAG = {"why": ""}


def log(msg):
    """带 flush 的输出：管道/重定向下也能实时看到进度（此前块缓冲=看起来完全没输出）。"""
    try:
        print(msg, flush=True)
    except Exception:
        pass  # 有意忽略：输出流不可用时无从记录


def _diag_lines():
    phase = PROGRESS.get("phase")
    lines = ["", "[WATCHDOG] %s" % STOP_FLAG["why"],
             "[WATCHDOG] 当前相位=%r 步骤=%r" % (phase, PROGRESS.get("step")),
             "[WATCHDOG] 已完成相位=%r" % ([t for t, _ok, _ck in RESULTS],)]
    shots = PROGRESS.get("shots") or []
    if shots:
        tail = shots[-6:]
        lines.append("[WATCHDOG] 最近采样=%r" % ([(round(t, 1), tag) for t, tag in tail],))
    evs = PROGRESS.get("events") or []
    if evs:
        lines.append("[WATCHDOG] 最近事件=%r" % ([(round(t, 1), k, d) for t, k, d in evs[-6:]],))
    return lines


def bail(why):
    """超时兜底：打印诊断 + 全部线程栈，然后以非 0 退出（绝不再无声挂死）。"""
    if STOP_FLAG["why"]:
        return  # 只报一次
    STOP_FLAG["why"] = why
    for line in _diag_lines():
        log(line)
    try:
        faulthandler.dump_traceback(all_threads=True)   # 卡在哪个线程/哪一行，一目了然
    except Exception:
        pass  # 有意忽略：栈打不出来也要保证退出
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass  # 有意忽略：同上
    os._exit(2)


def arm_watchdog(seconds, why):
    """线程级 watchdog：事件循环卡住时 QTimer 不会触发，只有独立线程靠得住。"""
    t = threading.Timer(seconds, bail, args=(why,))
    t.daemon = True
    t.start()
    return t


def run_case(T_FEED, watch=27.0):
    global PROGRESS
    PROGRESS = {"phase": T_FEED, "step": "建窗口", "shots": [], "events": []}
    tmp = tempfile.mkdtemp()
    main.DATA_DIR = tmp; main.CONFIG_PATH = os.path.join(tmp, "config.json")
    main.USAGE_PATH = os.path.join(tmp, "usage.json"); main.MEMORY_PATH = os.path.join(tmp, "memory.json")
    main.pet_log.set_data_dir(tmp)
    win = main.PetWindow()
    win.cfg["idle_trigger_delay"] = 8
    win.cfg["idle_delay_after_full"] = 2
    win.apply_idle_settings(win.cfg)
    T0 = time.monotonic()
    EV, SHOT = [], []
    # 本相位 watchdog：理论时长 + 余量。QTimer 之外还留一份线程级兜底（见 arm_watchdog）。
    # 相位结束必须 cancel——否则它会带着"上一相位的账"在下一相位中途开火（实测踩过：
    # 相位 1 的 57.5s 计时器在相位 2 跑到 24s 时把进程杀掉，报的还是"相位 T=0.5s 超时"）。
    _phase_wd = arm_watchdog(T_FEED + watch + 30.0,
                             "相位 T=%ss 超过 %.0fs 未完成（事件循环可能卡住）"
                             % (T_FEED, T_FEED + watch + 30.0))

    def lg(kind, detail=""):
        EV.append((time.monotonic() - T0 - T_FEED, kind, detail))  # 时间以喂食为原点
        PROGRESS["events"] = EV

    def _keys(ps):
        return {p.cacheKey() for p in (ps or []) if p is not None and not p.isNull()}
    def sample():
        t = time.monotonic() - T0 - T_FEED
        p = win.item.pixmap()
        cur = p.cacheKey() if (p is not None and not p.isNull()) else 0
        full = win.sprites.get("full") or {}
        fk = full.get("side").cacheKey() if full.get("side") is not None else -1
        # v2.4.0：吃饱形态**不再是静态图**——它有自己的帧集 assets/idle_full_f*（按形态注册进
        # "idle" 槽）。所以"是不是吃饱形态"必须看"静态图 ∪ 该形态的专属帧集"，
        # 否则新帧会被归成 idle → 消化窗口的断言全部假 FAIL。
        full_k = {fk} | _keys(getattr(win, "_idle_full_frames", None))
        idle_k = _keys(win.anim._sets.get("idle"))
        eat_k = _keys(win.anim._sets.get("eat"))
        tag = "full" if cur in full_k else ("idle" if cur in idle_k else ("eat" if cur in eat_k else "other"))
        SHOT.append((t, tag))
        PROGRESS["shots"] = SHOT
    _set = win._set_form
    def setf(form, refresh=True, cancel_transform=True, display_only=False):
        if form != win.form:
            lg("SET_FORM", "%s -> %s" % (win.form, form))
        return _set(form, refresh, cancel_transform, display_only)
    win._set_form = setf
    _dg = win._digest
    win._digest = lambda: (lg("DIGEST", "form=%s" % win.form), _dg())[1]
    _se = win._show_emote
    win._show_emote = lambda e: (lg("emote", "%s (form=%s)" % (e, win.form)), _se(e))[1]
    _pa = win.actions.play_action
    win.actions.play_action = lambda name, arg=None, force=False: (
        lg("play_action", "%s/%s" % (name, arg)), _pa(name, arg, force))[1]
    _sm = QTimer(); _sm.timeout.connect(sample); _sm.start(150)
    QTimer.singleShot(int(T_FEED * 1000), lambda: (lg(">>> FEED"), win.feed("小鱼干")))
    # v2.4（审查 附-1 卡死根因）：这里**不能**用 app.quit()。Qt 的 quit() 与 exit() 语义不同：
    # quit() 在"退出锁"（QEventLoopLocker → QCoreApplicationPrivate::quitLockRef）非 0 时
    # 只做一次 deref、**不退出事件循环**；PetWindow 建起来之后进程里就有这样一把锁
    # （实测：同一进程里 app.quit() 调 3 次才退出一次；QCoreApplication.quit()/invokeMethod("quit")
    #  单次都不退；app.exit(0) 每次都立即退）。本脚本此前用 app.quit → 第一相位永远不结束、
    # 进程挂死（CPU 冻结、无输出）。exit(0) 不受退出锁影响，且连续 3 轮 exec 实测都正常返回。
    QTimer.singleShot(int((T_FEED + watch) * 1000), lambda: app.exit(0))
    PROGRESS["step"] = "事件循环"
    log("  [phase T=%s] 事件循环开始（watch=%.1fs）" % (T_FEED, watch))
    app.exec()
    log("  [phase T=%s] 事件循环已退出" % T_FEED)
    _sm.stop()

    def at(kind, lo, hi):
        return [(t, d) for (t, k, d) in EV if k == kind and lo <= t <= hi]
    def shots(lo, hi):
        return [x for x in SHOT if lo <= x[0] <= hi]
    ck = []
    def chk(name, ok, detail=""):
        ck.append((name, ok, detail))
    zzz1 = at("emote", 9.4, 11.0)
    chk("喂食+10s 消化期 zzz（叠在吃饱形态上）",
        any(d.startswith("zzz") and "form=full" in d for _, d in zzz1), "%r" % (zzz1,))
    chk("喂食+12s 消化结束 → 常态 + sparkle",
        any(11.5 <= t <= 13.0 for t, _ in at("DIGEST", -1, 99))
        and any(11.5 <= t <= 14.0 and d.startswith("sparkle") for t, d in at("emote", -1, 99))
        and any(11.5 <= t <= 13.0 and d.endswith("-> normal") for t, d in at("SET_FORM", -1, 99)))
    quiet = [x for x in EV if 13.2 <= x[0] <= 24.4 and x[1] in ("emote", "play_action")]
    chk("安静期（消化后~第二次 zzz 前）无任何动作", not quiet, "%r" % (quiet[:3],))
    zzz2 = at("emote", 24.4, 26.5)
    chk("喂食+25s 第二次 zzz（饭后小盹，确定性）",
        any(d.startswith("zzz") for _, d in zzz2), "%r" % (zzz2,))
    w_dig = shots(0.4, 11.9)
    chk("消化窗口内画面无常态 idle 帧（未被常态动画盖住）",
        not [x for x in w_dig if x[1] == "idle"],
        "越界=%d/%d" % (len([x for x in w_dig if x[1] == "idle"]), len(w_dig)))
    w_hold = shots(2.2, 11.9)
    chk("吃帧窗口后画面恒为 character_full.png",
        bool(w_hold) and all(x[1] == "full" for x in w_hold),
        "非full=%r" % ([(round(t, 1), tg) for t, tg in w_hold if tg != "full"][:3],))
    w_back = shots(14.0, 23.5)
    chk("消化后画面回到常态 idle 帧动画",
        bool(w_back) and all(x[1] == "idle" for x in w_back),
        "非idle=%r" % ([(round(t, 1), tg) for t, tg in w_back if tg != "idle"][:3],))
    log("  ── 喂食时刻 T=%ss ──" % T_FEED)
    for name, ok, detail in ck:
        log("  %s %s  %s" % ("PASS" if ok else "FAIL", name, detail))
    RESULTS.append((T_FEED, all(ok for _, ok, _ in ck), ck))
    # 相位收尾：窗口/定时器不能拖到下一相位，更不能拖着解释器不退出
    PROGRESS["step"] = "相位收尾"
    _phase_wd.cancel()
    win._closing = True
    try:
        win.voice.stop()
    except Exception:
        pass  # 有意忽略：收尾尽力而为
    try:
        win._state_timer.stop()
        win.idle_timer.stop()
        win._idle_check_timer.stop()
        win.anim.stop()
    except Exception:
        pass  # 有意忽略：同上
    _sm.stop()
    win.hide()
    win.deleteLater()
    app.processEvents()   # 让 deleteLater 真正生效，别把 QObject 留到下一相位


log("VERSION = %s" % main.VERSION)
# 全程 watchdog：三相位理论总时长 + 余量（独立线程；事件循环卡死也照样兜底退出）
_TOTAL = sum(t + 27.0 for t in (0.5, 5.0, 16.0)) + 60.0
arm_watchdog(_TOTAL, "全程超过 %.0fs 仍未跑完" % _TOTAL)
for _t in (0.5, 5.0, 16.0):
    run_case(_t)
log("")
for t, ok, ck in RESULTS:
    log("T=%-5s  %s" % (t, "全部通过" if ok else "有失败：%s" % [n for n, o, _ in ck if not o]))
all_ok = all(ok for _, ok, _ in RESULTS)
log("\n总结果：%s" % ("全部相位通过 ✓" if all_ok else "存在失败相位 ✗"))
sys.exit(0 if all_ok else 1)
