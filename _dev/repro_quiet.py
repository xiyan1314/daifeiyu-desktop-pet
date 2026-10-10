# -*- coding: utf-8 -*-
"""时间轴 + 画面级验收（v2.2.5）：**相位无关**——任选喂食时刻，相对时间轴都必须成立。

相对期望（以喂食时刻 T 为基准，v2.2.5 起 zzz 挂喂食事件时钟）：
  T       喂食 → 画面切吃饱静态图（吃帧窗口 ~1.6s 后恒为 character_full.png）
  T+10s   消化窗口内头顶 zzz（叠在吃饱形态上，不换形态）
  T+12s   消化结束 → 常态 + sparkle；此后安静
  T+25s   第二次 zzz（消化结束 +13s 的"饭后小盹"）
  T+12~T+25 之间：无任何随机动作/zzz（安静期）
画面：T~T+12s 消化窗口内不出现常态 idle 帧；消化后回到常态 idle 帧动画。
跑法：cd 大肥鱼桌宠_绿色版 && .\python.exe _dev\repro_quiet.py
"""
import os, sys, time, tempfile
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

def run_case(T_FEED, watch=27.0):
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
    def lg(kind, detail=""):
        EV.append((time.monotonic() - T0 - T_FEED, kind, detail))  # 时间以喂食为原点
        
    def _keys(ps):
        return {p.cacheKey() for p in (ps or []) if p is not None and not p.isNull()}
    def sample():
        t = time.monotonic() - T0 - T_FEED
        p = win.item.pixmap()
        cur = p.cacheKey() if (p is not None and not p.isNull()) else 0
        full = win.sprites.get("full") or {}
        fk = full.get("side").cacheKey() if full.get("side") is not None else -1
        idle_k = _keys(win.anim._sets.get("idle"))
        eat_k = _keys(win.anim._sets.get("eat"))
        tag = "full" if cur == fk else ("idle" if cur in idle_k else ("eat" if cur in eat_k else "other"))
        SHOT.append((t, tag))
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
    QTimer.singleShot(int((T_FEED + watch) * 1000), app.quit)
    app.exec()
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
    print("  ── 喂食时刻 T=%ss ──" % T_FEED)
    for name, ok, detail in ck:
        print("  %s %s  %s" % ("PASS" if ok else "FAIL", name, detail))
    RESULTS.append((T_FEED, all(ok for _, ok, _ in ck), ck))
    win._closing = True
    try:
        win.voice.stop()
    except Exception:
        pass
    win.hide(); win.deleteLater()

print("VERSION =", main.VERSION)
for _t in (0.5, 5.0, 16.0):
    run_case(_t)
print("")
for t, ok, ck in RESULTS:
    print("T=%-5s  %s" % (t, "全部通过" if ok else "有失败：%s" % [n for n, o, _ in ck if not o]))
all_ok = all(ok for _, ok, _ in RESULTS)
print("\n总结果：%s" % ("全部相位通过 ✓" if all_ok else "存在失败相位 ✗"))
sys.exit(0 if all_ok else 1)