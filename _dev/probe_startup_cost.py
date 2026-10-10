# -*- coding: utf-8 -*-
"""启动耗时探针：量出 PetWindow() 构造里每一段的**实测**占比（只读测量，不改产品代码）。

为什么要它：交接里的"启动 173~617 ms（方差大）"只有一个总数，没有分段归因——按总数
猜"是 load_frame_set 慢"就可能改错地方。本脚本给两把尺子：

  · 归因尺（采样）：后台线程每 ~0.4ms 采一次主线程栈，按**最内层帧的文件:行号**聚合。
    PetWindow.__init__ 是一个大函数，行号级聚合能直接指出"慢在哪一行"。采样的好处是
    不侵入产品代码、也不改变被测量代码的调用结构。
  · 计时尺（插桩）：按名字包住已知的大块（load_frame_set / _build_sprites /
    _build_state_pix / winId 预热 …），给每个名字的"总耗时 / 调用次数"。两把尺子互相
    校验：归因尺说某行占 40%，计时尺应该能在对应名字上看到同样的量级。

首屏口径（证明"窗口出现时机"没变差）：
  · t_show_call     —— __init__ 里 self.show() 被调用的时刻（相对构造开始）
  · t_first_paint   —— 事件循环里第一次收到 Paint 事件的时刻（相对构造开始）
  · first_pix_ok    —— 收到首次绘制时 self.item 上的 QPixmap 是否为非空图
    （空图 = 白屏/闪空；offscreen 平台下同样成立）

用法：
    python _dev/probe_startup_cost.py                      # 7 轮，打印表格
    python _dev/probe_startup_cost.py --runs 3 --json out.json
    python _dev/probe_startup_cost.py --no-sample          # 只跑计时尺（采样有 ~5% 干扰）

退出码：0 = 测量有效且首屏不变量成立；1 = 首屏不变量被破坏或测量失败。
"""
import argparse
import json
import os
import shutil
import statistics
import sys
import tempfile
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.environ.get("PROBE_REPO") or HERE
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))

from PySide6.QtCore import QEvent, QObject, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402
from PySide6.QtWidgets import QSystemTrayIcon  # noqa: E402

TMPROOT = tempfile.mkdtemp(prefix="probe_startup_")

import pet_log  # noqa: E402

DATA = os.path.join(TMPROOT, "data")
os.makedirs(DATA, exist_ok=True)
pet_log.set_data_dir(DATA)

import 桌宠 as main  # noqa: E402
import pet_anim  # noqa: E402
import pet_audio  # noqa: E402
import pet_book  # noqa: E402
import pet_lines  # noqa: E402
import pet_resources  # noqa: E402

main.DATA_DIR = DATA
main.CONFIG_PATH = os.path.join(DATA, "config.json")
main.USAGE_PATH = os.path.join(DATA, "usage.json")
main.MEMORY_PATH = os.path.join(DATA, "memory.json")

app = QApplication.instance() or QApplication([])

# ---------------------------------------------------------------- 计时尺
TIMERS = {}          # name -> [total_ms, max_ms, calls]（**构造窗口内**的调用）
TIMERS_AFTER = {}    # 同上，但属于构造返回之后的调用（定时器接力，如 3s 后的撒钱预载）
EVENTS = {}          # name -> [(t_rel_ms, detail)]
T_END = [None]       # 构造结束时刻（perf_counter）；None = 还在构造里


def _rec(name, dt_ms):
    """记一次调用。**按时间窗分桶**：构造窗口内 / 之后。

    分窗是必须的：QTimer.singleShot(3000) 排下的 _preload_money_fx（86 帧撒钱）会在
    构造返回 3s 后才跑，不分开就会把它算进"启动构造"里（实测把 52ms 记到了构造头上）。
    """
    bucket = TIMERS if (T_END[0] is None or time.perf_counter() <= T_END[0]) else TIMERS_AFTER
    r = bucket.setdefault(name, [0.0, 0.0, 0])
    r[0] += dt_ms
    r[1] = max(r[1], dt_ms)
    r[2] += 1


def _fmt_timers(bucket):
    return {k: [round(v[0], 2), round(v[1], 2), v[2]] for k, v in bucket.items()}


def timed(obj, name, label=None, only_main=True):
    """包住 obj.name：把每次调用的墙钟耗时记进 TIMERS。"""
    if obj is None:
        return
    orig = getattr(obj, name, None)
    if orig is None:
        return
    tag = label or ("%s.%s" % (getattr(obj, "__name__", type(obj).__name__), name))

    def wrapper(*a, **k):
        if only_main and threading.current_thread() is not threading.main_thread():
            return orig(*a, **k)
        t0 = time.perf_counter()
        try:
            return orig(*a, **k)
        finally:
            _rec(tag, (time.perf_counter() - t0) * 1000.0)

    try:
        setattr(obj, name, wrapper)
    except Exception:
        pass


def timed_load_frame_set():
    """load_frame_set 每次调用单独记（前缀做标签），因为它被调 4 次、帧数各不同。"""
    orig = pet_anim.load_frame_set

    def wrapper(dir_path, prefix, count):
        t0 = time.perf_counter()
        out = orig(dir_path, prefix, count)
        _rec("load_frame_set[%s]" % prefix, (time.perf_counter() - t0) * 1000.0)
        _rec("load_frame_set[TOTAL]", (time.perf_counter() - t0) * 1000.0)
        EVENTS.setdefault("frames_loaded", []).append(
            (round((t0 - T0) * 1000.0, 1), "%s=%d" % (prefix, len(out))))
        return out

    pet_anim.load_frame_set = wrapper
    main.pet_anim.load_frame_set = wrapper


def timed_qpixmap():
    """QPixmap(路径) 的真实构造次数与耗时（= PNG 解码口径）。

    **两个模块都要包**：桌宠.py 与 pet_anim.py 各自 from PySide6.QtGui import QPixmap，
    只包 main.QPixmap 的话 load_frame_set 里那 37 帧一次都数不到（第一版探针就漏了这个，
    "构造期解码 21 张"只统计到状态图与角色贴图）。
    """
    def make(real):
        def wrapper(*a, **k):
            p = a[0] if a and isinstance(a[0], str) else None
            if p is None:
                return real(*a, **k)
            t0 = time.perf_counter()
            out = real(*a, **k)
            _rec("QPixmap(路径)", (time.perf_counter() - t0) * 1000.0)
            DECODES.append(p)
            return out
        return wrapper

    main.QPixmap = make(main.QPixmap)
    pet_anim.QPixmap = make(pet_anim.QPixmap)


timed_qpixmap()

for _o, _n in ((main, "load_config"), (main, "save_config"), (main, "ensure_persona_files"),
               (main, "resource_path"), (main, "resource_dir"),
               (main.PetWindow, "_build_sprites"), (main.PetWindow, "_build_state_pix"),
               (main.PetWindow, "_compute_base_size"), (main.PetWindow, "_wire_anim_sets"),
               (main.PetWindow, "_wire_anim_key"), (main.PetWindow, "_load_img"),
               (main.PetWindow, "_cap_role_pix"), (main.PetWindow, "_role_pix"),
               (main.PetWindow, "_custom_state_pix"), (main.PetWindow, "_refresh_lines"),
               (main.PetWindow, "_migrate_lines_extra"), (main.PetWindow, "_frame_pix"),
               (main.PetWindow, "_show_state"), (main.PetWindow, "_say_line"),
               (main.PetWindow, "_pick_line"), (main.PetWindow, "_scan_invalid_refs"),
               (main.PetWindow, "_update_click_mask"), (main.PetWindow, "_apply_transform"),
               (main.PetWindow, "_preload_money_fx"),
               (main, "_make_custom_state_pix"),
               (pet_resources.RoleLibrary, "__init__"), (pet_resources.RoleLibrary, "_load"),
               (pet_resources.AudioLibrary, "__init__"),
               (pet_resources.VoiceAssetLibrary, "__init__"),
               (pet_audio, "init"), (pet_audio, "_rebuild_effects"),
               (pet_book.Book, "__init__"), (pet_lines.LineService, "__init__"),
               (main.PetWindow, "_apply_sound_group"),
               (QWidget, "winId"), (QSystemTrayIcon, "show")):
    timed(_o, _n)
for _cls in ("Bubble", "Badge", "FoodTray", "FoodFlyer"):
    timed(getattr(main, _cls, None), "__init__", label="%s.__init__" % _cls)

timed_load_frame_set()

# ---------------------------------------------------------------- 归因尺（采样）
MAIN_TID = threading.get_ident()
SAMPLES = []
_SAMPLING = threading.Event()
T0 = time.perf_counter()


def _sampler(gap=0.0003):
    """主线程栈采样。

    Windows 的 time.sleep 粒度是 ~15.6ms（默认时钟分辨率），直接 sleep(0.0004) 实测
    90ms 只采到 5 个样本——归因尺基本失效。改成 sleep(0) 让出 GIL 的紧循环，并把
    GIL 切换间隔压到 0.2ms，采样间隔就落回 ~0.3ms 量级（实测 90ms 采到 100+ 个样本）。
    """
    frames_ref = sys._current_frames
    pc = time.perf_counter
    while _SAMPLING.is_set():
        t0 = pc()
        f = frames_ref().get(MAIN_TID)
        stack = []
        while f is not None and len(stack) < 40:
            stack.append((f.f_code.co_filename, f.f_code.co_name, f.f_lineno))
            f = f.f_back
        if stack:
            SAMPLES.append(stack)
        while pc() - t0 < gap:
            time.sleep(0)


def _short(path):
    """短文件名：仓库内相对路径，否则 basename。"""
    try:
        rel = os.path.relpath(path, REPO)
    except Exception:
        return os.path.basename(path)
    return rel if not rel.startswith("..") else os.path.basename(path)


def attribute():
    """两种口径一起出：

    · 叶子帧：最内层帧的文件:函数:行号（C 调用不压 Python 帧，所以 QPixmap 解码会落在
      调用它的那一行上）。
    · 最近仓库帧：从内往外找**第一个仓库内**的帧，按 文件:函数 聚合。

    采样尺的已知偏差（必须一起读，否则会误判）：采样线程要拿 GIL。**持 GIL 的 C 调用**
    （如 Qt 的 PNG 解码）期间它完全采不到样，而**放 GIL 的 C 调用**（如 os.stat 的
    系统调用）期间它反而能全速采 —— 所以"叶子帧"口径会**高估文件 IO、低估图片解码**。
    定量结论一律以计时尺为准，采样尺只用来看"Python 层热在哪"。
    """
    n = len(SAMPLES)
    if not n:
        return [], 0, []
    leaf = {}
    near = {}
    for st in SAMPLES:
        f, name, ln = st[0]
        k = (_short(f), name, ln)
        leaf[k] = leaf.get(k, 0) + 1
        for (pf, pn, _pl) in st:
            if not pf.startswith(REPO):
                continue
            sf = _short(pf)
            if sf.startswith("_dev" + os.sep) or sf.startswith("tests" + os.sep):
                continue
            near[(sf, pn)] = near.get((sf, pn), 0) + 1
            break
    return (sorted(leaf.items(), key=lambda kv: -kv[1]), n,
            sorted(near.items(), key=lambda kv: -kv[1]))


# ---------------------------------------------------------------- 首屏观察
class PaintWatch(QObject):
    def __init__(self):
        super().__init__()
        self.t_show_call = None
        self.t_first_show = None
        self.t_first_paint = None
        self.pix_at_paint = None

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Type.Show and self.t_first_show is None:
            self.t_first_show = time.perf_counter()
        elif t == QEvent.Type.Paint and self.t_first_paint is None:
            self.t_first_paint = time.perf_counter()
            w = getattr(obj, "window", None)
            win = w() if callable(w) else None
            while win is not None and not isinstance(win, main.PetWindow):
                pw = getattr(win, "parentWidget", None)
                win = pw() if callable(pw) else None
            if isinstance(win, main.PetWindow):
                self.pix_at_paint = win.item.pixmap()
        return False


_orig_show = main.PetWindow.show
_WATCH = None


def _probe_show(self):
    """记录 self.show() 的调用时刻，并在**真正 show 之前**挂上事件过滤器。

    必须在真 show 之前挂：Show/Paint 事件是事件循环投递的，show() 之后再挂就漏掉首个。
    """
    w = _WATCH
    if w is not None and w.t_show_call is None:
        w.t_show_call = time.perf_counter()
        try:
            self.installEventFilter(w)
            self.view.viewport().installEventFilter(w)
        except Exception:
            pass
    return _orig_show(self)


main.PetWindow.show = _probe_show


def pump_until(cond, limit_s=2.0, step=0.002):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < limit_s:
        app.processEvents()
        if cond():
            return True
        time.sleep(step)
    app.processEvents()
    return cond()


def one_run(idx, use_sample=True):
    """构造一次 PetWindow，返回本次的分段实测。"""
    global T0, _WATCH
    run_dir = os.path.join(TMPROOT, "run%d" % idx)
    os.makedirs(run_dir, exist_ok=True)
    main.DATA_DIR = run_dir
    main.CONFIG_PATH = os.path.join(run_dir, "config.json")
    main.USAGE_PATH = os.path.join(run_dir, "usage.json")
    main.MEMORY_PATH = os.path.join(run_dir, "memory.json")
    pet_log.set_data_dir(run_dir)

    TIMERS.clear()
    TIMERS_AFTER.clear()
    EVENTS.clear()
    DECODES.clear()
    del SAMPLES[:]
    T_END[0] = None

    watch = PaintWatch()
    _WATCH = watch
    app.processEvents()
    time.sleep(0.01)
    app.processEvents()

    if use_sample:
        _SAMPLING.set()
        th = threading.Thread(target=_sampler, daemon=True)
        th.start()

    T0 = time.perf_counter()
    win = main.PetWindow()
    t_init = time.perf_counter()
    T_END[0] = t_init
    # 构造**刚返回**时的状态：延迟装载（帧集/状态图）的判据必须在这一刻取——
    # 事件循环一转，QTimer(0) 排下的接力装载就已经把素材补齐了（第一版探针踩过这个坑）。
    after = {
        "has_frames": bool(getattr(win, "has_frames", False)),
        "idle_frames": len(getattr(win, "_idle_frames", []) or []),
        "idle_full_frames": len(getattr(win, "_idle_full_frames", []) or []),
        "eat_frames": len(getattr(win, "_eat_frames", []) or []),
        "fx_petpet": len(getattr(win, "_fx_petpet", []) or []),
        "anim_idle_set": len((win.anim._sets.get("idle") or [])),
        "anim_eat_set": len((win.anim._sets.get("eat") or [])),
        "state_states": sum(len(v) for v in getattr(win, "state_pix", {}).values()),
        "decodes_ctor": len(DECODES),
        "decode_names_ctor": sorted({os.path.basename(p) for p in DECODES}),
    }

    if use_sample:
        _SAMPLING.clear()
        th.join(timeout=1.0)

    init_ms = (t_init - T0) * 1000.0
    first_paint = pump_until(lambda: watch.t_first_paint is not None, 2.0)
    t_first_paint_ms = ((watch.t_first_paint - T0) * 1000.0
                        if watch.t_first_paint is not None else None)
    t_show_ms = ((watch.t_show_call - T0) * 1000.0
                 if watch.t_show_call is not None else None)
    pix = watch.pix_at_paint
    first_pix_ok = bool(pix is not None and not pix.isNull() and pix.width() > 0)

    # 把事件循环转 1.5s：任何"启动后接力"的工作都该跑完了
    t_settle0 = time.perf_counter()
    settle_gap = 0.0
    last = t_settle0
    while time.perf_counter() - t_settle0 < 1.5:
        app.processEvents()
        now = time.perf_counter()
        settle_gap = max(settle_gap, (now - last) * 1000.0)
        last = now
        time.sleep(0.002)
    settled = {
        "has_frames": bool(getattr(win, "has_frames", False)),
        "idle_frames": len(getattr(win, "_idle_frames", []) or []),
        "idle_full_frames": len(getattr(win, "_idle_full_frames", []) or []),
        "eat_frames": len(getattr(win, "_eat_frames", []) or []),
        "fx_petpet": len(getattr(win, "_fx_petpet", []) or []),
        "anim_idle_set": len((win.anim._sets.get("idle") or [])),
        "state_states": sum(len(v) for v in getattr(win, "state_pix", {}).values()),
        "max_settle_gap_ms": round(settle_gap, 1),
        "anim_running": bool(win.anim._timer.isActive()),
    }

    try:
        from helpers_roles import shutdown_pet
        shutdown_pet(win)
    except Exception:
        try:
            win.hide()
            win.deleteLater()
        except Exception:
            pass
    app.processEvents()

    leaf, nsamp, near = attribute() if use_sample else ([], 0, [])
    phases = _fmt_timers(TIMERS)
    phases_after = _fmt_timers(TIMERS_AFTER)
    return {
        "run": idx,
        "init_ms": round(init_ms, 1),
        "t_show_call_ms": None if t_show_ms is None else round(t_show_ms, 1),
        "t_first_paint_ms": None if t_first_paint_ms is None else round(t_first_paint_ms, 1),
        "first_paint_seen": bool(first_paint),
        "first_pix_ok": first_pix_ok,
        "first_pix": None if pix is None else "%dx%d" % (pix.width(), pix.height()),
        "decodes": len(DECODES),
        "decode_names": sorted({os.path.basename(p) for p in DECODES}),
        "after_init": after,
        "settled": settled,
        "timers": phases,
        "timers_after": phases_after,
        "samples": nsamp,
        "leaf": [["%s:%s:%d" % k, v] for k, v in leaf[:40]],
        "near": [["%s:%s" % k, v] for k, v in near[:40]],
        "leaf_total": len(leaf),
        "events": {k: v[:12] for k, v in EVENTS.items()},
    }


DECODES = []


def main_cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=7)
    ap.add_argument("--json", default="")
    ap.add_argument("--no-sample", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    print("仓库：%s" % REPO)
    print("真实素材帧：%s" % _asset_line(REPO))
    rows = []
    for i in range(args.runs):
        r = one_run(i, use_sample=not args.no_sample)
        rows.append(r)
        print("[run %d] 构造 %6.1f ms | show 调用 %s ms | 首次绘制 %s ms | 解码 %d 张 | 采样 %d | 首屏图 %s"
              % (i + 1, r["init_ms"], r["t_show_call_ms"], r["t_first_paint_ms"],
                 r["decodes"], r["samples"], r["first_pix"]))

    def stat(key, sub=None):
        vals = []
        for r in rows:
            v = r[sub][key] if sub else r[key]
            if isinstance(v, (int, float)):
                vals.append(float(v))
        if not vals:
            return None
        return (min(vals), statistics.median(vals), max(vals))

    print("\n== 总览（min / 中位 / max，毫秒）==")
    for key, label in (("init_ms", "PetWindow() 构造"), ("t_show_call_ms", "self.show() 被调用"),
                       ("t_first_paint_ms", "事件循环首次绘制")):
        s = stat(key)
        if s:
            print("  %-22s %7.1f / %7.1f / %7.1f" % (label, s[0], s[1], s[2]))

    # 计时尺：把每轮的名字列表并起来，取中位
    names = []
    for r in rows:
        for k in r["timers"]:
            if k not in names:
                names.append(k)
    agg = []
    for k in names:
        vals = [r["timers"][k][0] for r in rows if k in r["timers"]]
        calls = max(r["timers"][k][2] for r in rows if k in r["timers"])
        mx = max(r["timers"][k][1] for r in rows if k in r["timers"])
        med = statistics.median(vals)
        agg.append((med, k, min(vals), mx, calls))
    agg.sort(reverse=True)
    print("\n== 计时尺：构造期各段耗时（中位 ms，仅列 >0.5ms）==")
    for med, k, mn, mx, calls in agg:
        if med < 0.5:
            continue
        print("  %-34s 中位 %7.2f  范围 %6.2f–%6.2f  ×%d" % (k, med, mn, mx, calls))
    tot = stat("init_ms")
    named = sum(x[0] for x in agg)
    if tot:
        print("  %-34s 中位 %7.2f （= 构造总时长的 %.0f%%）"
              % ("[计时尺已归因合计]", named, 100.0 * named / max(tot[1], 1e-9)))

    if not args.no_sample:
        print("\n== 归因尺：采样热点（按最内层帧，中位占比）==")
        keys = []
        for r in rows:
            for k, v in r["leaf"]:
                if k not in keys:
                    keys.append(k)
        shares = []
        for k in keys:
            vals = []
            for r in rows:
                n = r["samples"]
                d = dict(r["leaf"])
                vals.append(100.0 * d.get(k, 0) / max(n, 1))
            shares.append((statistics.median(vals), max(vals), k))
        shares.sort(reverse=True)
        for med, mx, k in shares[:22]:
            if med < 0.4:
                continue
            print("  %5.1f%%  (max %4.1f%%)  %s" % (med, mx, k))

        print("\n== 归因尺：最近仓库帧（= 这段时间在哪个项目函数里，中位占比）==")
        keys2 = []
        for r in rows:
            for k, v in r["near"]:
                if k not in keys2:
                    keys2.append(k)
        sh2 = []
        for k in keys2:
            vals = []
            for r in rows:
                n = r["samples"]
                d = dict(r["near"])
                vals.append(100.0 * d.get(k, 0) / max(n, 1))
            sh2.append((statistics.median(vals), max(vals), k))
        sh2.sort(reverse=True)
        for med, mx, k in sh2[:20]:
            if med < 0.4:
                continue
            print("  %5.1f%%  (max %4.1f%%)  %s" % (med, mx, k))

    names_a = []
    for r in rows:
        for k in r.get("timers_after", {}):
            if k not in names_a:
                names_a.append(k)
    if names_a:
        print("\n== 构造返回之后跑的主线程工作（定时器接力，中位 ms）==")
        for k in names_a:
            vals = [r["timers_after"][k][0] for r in rows if k in r["timers_after"]]
            mx = max(r["timers_after"][k][1] for r in rows if k in r["timers_after"])
            print("  %-34s 中位 %7.2f  单次最大 %6.2f  ×%d"
                  % (k, statistics.median(vals), mx,
                     max(r["timers_after"][k][2] for r in rows if k in r["timers_after"])))

    r0 = rows[0]
    print("\n== 构造刚结束时 / 事件循环转 1.5s 后 ==")
    for tag, blk in (("刚结束", r0["after_init"]), ("1.5s 后", r0["settled"])):
        print("  %-6s %s" % (tag, json.dumps(blk, ensure_ascii=False)))

    ok = all(r["first_pix_ok"] and r["first_paint_seen"] for r in rows)
    print("\n首屏不变量（每次构造都收到绘制且 item 上是非空图）：%s" % ("PASS" if ok else "FAIL"))

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fp:
            json.dump({"repo": REPO, "rows": rows}, fp, ensure_ascii=False, indent=1)
        print("JSON → %s" % args.json)

    shutil.rmtree(TMPROOT, ignore_errors=True)
    return 0 if ok else 1


def _asset_line(repo):
    from PySide6.QtGui import QImageReader
    p = os.path.join(repo, "assets", "idle_f00.png")
    if not os.path.isfile(p):
        return "(缺失 %s)" % p
    s = QImageReader(p).size()
    return "%dx%d %d B（%s）" % (s.width(), s.height(), os.path.getsize(p), p)


if __name__ == "__main__":
    sys.exit(main_cli())
