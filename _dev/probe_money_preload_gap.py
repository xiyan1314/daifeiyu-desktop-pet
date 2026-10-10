# -*- coding: utf-8 -*-
"""撒钱帧集预载的**事件循环缺口**探针（v2.4.3 · 兼容审查 L3② / 质量审查 M2）。

要回答的问题只有一个：启动 3 秒后那批撒钱帧（86 帧 ≈2MB PNG）解码时，窗口的事件循环
被连续占住多久（= 用户感知的假死时长）。

两种形态各测一遍，**每轮一个新进程**（冷缓存，与质量审查自写探针同法）：
  · eager  —— v2.4.2 原样：到点后一次 load_frame_set(dir, "money", 86)（同步解完整批）；
  · sliced —— v2.4.3：_preload_money_fx() 只登记在途状态，解码按 _FRAME_SLICE_MS 分片，
              片与片之间事件循环照常转。

测量口径：
  · loop_gap_ms —— 1ms PreciseTimer 心跳的最大间隔（事件循环真的被占住多久）；
  · entry_ms    —— _preload_money_fx() 这一下同步返回花多久（分片版的入口应该接近 0）；
  · slice_max_ms—— 分片版**单片**同步耗时（= 单片预算的实测值）；
  · slices      —— 分片版跑了几片；
  · 素材一致性   —— 分片解出来的 86 帧与一次性 load_frame_set 逐张 toImage() 比对。

用法：
    python _dev/probe_money_preload_gap.py --rounds 4 --json _dev/money_preload_summary.json
    python _dev/probe_money_preload_gap.py --mode sliced --rounds 1      # 只跑一种形态
    python _dev/probe_money_preload_gap.py --repo "<另一棵树>"            # 量别的检出（如 v2.4.2）

退出码：0 = 两种形态都测到且分片版明显更平顺；1 = 测量不成立（超时/素材不一致/没有改善）。
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="probe_money_")


# ---------------- 子进程：跑一轮 ----------------

def one_round(mode, repo, out_path):
    """在**本进程**里测一轮（由父进程用新进程调用），结果写 out_path。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, "tests"))

    import pet_log
    pet_log.set_data_dir(TMP)

    import 桌宠 as main
    import pet_anim
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication

    main.DATA_DIR = TMP
    main.CONFIG_PATH = os.path.join(TMP, "config.json")
    main.USAGE_PATH = os.path.join(TMP, "usage.json")
    main.MEMORY_PATH = os.path.join(TMP, "memory.json")

    app = QApplication.instance() or QApplication([])
    win = main.PetWindow()
    win.show_bubble = lambda *a, **k: None
    win.hide()
    # 3s 后的那次自动预载与我们无关（本轮手动驱动），先撤掉在途状态
    win._money_preload = None
    win._fx_money = []

    heart = QTimer()
    heart.setTimerType(Qt.TimerType.PreciseTimer)
    heart.setInterval(1)
    tick = {"last": time.perf_counter(), "max_gap": 0.0}

    def on_tick():
        now = time.perf_counter()
        gap = (now - tick["last"]) * 1000.0
        if gap > tick["max_gap"]:
            tick["max_gap"] = gap
        tick["last"] = now

    heart.timeout.connect(on_tick)

    res = {"mode": mode, "repo": repo, "ok": False, "error": "",
           "loop_gap_ms": None, "entry_ms": None, "slice_max_ms": None,
           "slices": 0, "frames": 0, "materials_equal": None}

    def finish():
        heart.stop()
        res["loop_gap_ms"] = round(tick["max_gap"], 1)
        res["frames"] = len(win._fx_money)
        if mode == "sliced" and win._fx_money:
            want = pet_anim.load_frame_set(win._fx_money_dir, main._MONEY_FRAME_PREFIX,
                                           main._MONEY_FRAME_COUNT)
            res["materials_equal"] = (len(want) == len(win._fx_money)
                                      and all(a.toImage() == b.toImage()
                                              for a, b in zip(win._fx_money, want)))
        res["ok"] = True
        try:
            win._closing = True
            win.voice.stop()
            win.hide()
        except Exception:
            pass  # 有意忽略：退出清理失败不影响已采集的数据
        app.quit()

    def start():
        heart.start()
        tick["last"] = time.perf_counter()
        tick["max_gap"] = 0.0
        if mode == "eager":
            # v2.4.2 原样（该版本的 _preload_money_fx 函数体）：一次同步解完整批
            t0 = time.perf_counter()
            win._fx_money = pet_anim.load_frame_set(win._fx_money_dir, "money", 86)
            res["entry_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
            # 让心跳把这次长阻塞记成缺口再收工
            QTimer.singleShot(80, finish)
            return
        # sliced：入口 + 真 QTimer(0) 接力（片长与片数由产品代码自己决定）
        steps = []
        real_step = win._money_preload_step

        def timed_step():
            t0 = time.perf_counter()
            try:
                return real_step()
            finally:
                steps.append((time.perf_counter() - t0) * 1000.0)

        win._money_preload_step = timed_step        # 入口与后续片都排到它（_gslot 排期时取值）
        t0 = time.perf_counter()
        win._preload_money_fx()
        res["entry_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
        res["slices"] = 0
        deadline = time.perf_counter() + 10.0

        def watch():
            if win._money_preload is None and win._fx_money:
                res["slices"] = len(steps)
                res["slice_max_ms"] = round(max(steps), 1) if steps else None
                finish()
                return
            if time.perf_counter() > deadline:
                res["error"] = "分片预载 10s 没跑完（链没收敛）"
                finish()
                return
            QTimer.singleShot(2, watch)

        QTimer.singleShot(0, watch)

    QTimer.singleShot(0, start)
    app.exec()
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False)
    return res


# ---------------- 父进程：交替采样 + 汇总 ----------------

def _one_round_subprocess(mode, repo):
    out = os.path.join(TMP, "round_%s_%d.json" % (mode, os.getpid()))
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("PYTHONPATH", None)
    cmd = [sys.executable, os.path.abspath(__file__), "--one-round", mode,
           "--repo", repo, "--out", out]
    p = subprocess.run(cmd, capture_output=True, env=env, timeout=180,
                       cwd=os.path.dirname(os.path.abspath(__file__)))
    if not os.path.isfile(out):
        tail = (p.stdout or b"")[-400:].decode("utf-8", "replace")
        raise RuntimeError("子进程没写出结果（rc=%s）：%s" % (p.returncode, tail))
    with open(out, "r", encoding="utf-8") as f:
        return json.load(f)


def _stats(rows, key):
    vals = [r[key] for r in rows if r.get(key) is not None]
    if not vals:
        return None
    return {"n": len(vals), "min": round(min(vals), 1),
            "median": round(statistics.median(vals), 1), "max": round(max(vals), 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--mode", default="both", choices=("both", "eager", "sliced"))
    ap.add_argument("--repo", default=HERE, help="量哪棵树（默认本仓库；可指向 v2.4.2 检出）")
    ap.add_argument("--json", default="", help="把摘要写到这个路径")
    ap.add_argument("--one-round", default="", help=argparse.SUPPRESS)
    ap.add_argument("--out", default="", help=argparse.SUPPRESS)
    args = ap.parse_args()
    repo = os.path.abspath(args.repo)
    if args.one_round:
        one_round(args.one_round, repo, args.out)
        return 0

    modes = ["eager", "sliced"] if args.mode == "both" else [args.mode]
    rows = []
    for i in range(args.rounds):
        order = modes if i % 2 == 0 else list(reversed(modes))   # 交替顺序，抵消负载漂移
        for mode in order:
            r = _one_round_subprocess(mode, repo)
            rows.append(r)
            print("  第 %d 轮 [%-6s] 循环缺口 %8s ms | 入口 %7s ms | 单片最大 %7s ms | %2s 片 | %2s 帧%s"
                  % (i + 1, mode, r.get("loop_gap_ms"), r.get("entry_ms"),
                     r.get("slice_max_ms"), r.get("slices"), r.get("frames"),
                     ("  ERR=" + r["error"]) if r.get("error") else ""))

    by = {m: [r for r in rows if r["mode"] == m] for m in modes}
    summary = {
        "what": "撒钱帧集预载的事件循环缺口（每轮一个新进程，1ms PreciseTimer 心跳，交替采样）",
        "repo": repo,
        "rounds": args.rounds,
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "eager_v242": {"loop_gap_ms": _stats(by.get("eager", []), "loop_gap_ms"),
                       "entry_ms": _stats(by.get("eager", []), "entry_ms")},
        "sliced_v243": {"loop_gap_ms": _stats(by.get("sliced", []), "loop_gap_ms"),
                        "entry_ms": _stats(by.get("sliced", []), "entry_ms"),
                        "slice_max_ms": _stats(by.get("sliced", []), "slice_max_ms"),
                        "slices": _stats(by.get("sliced", []), "slices"),
                        "materials_equal": all(r.get("materials_equal") for r in by.get("sliced", []))},
        "rows": rows,
        "rerun": "python _dev/probe_money_preload_gap.py --rounds 4 --json _dev/money_preload_summary.json",
    }
    if args.json:
        path = args.json if os.path.isabs(args.json) else os.path.join(HERE, args.json)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
            f.write(chr(10))
        print("摘要已写入 %s" % path)

    print(chr(10) + "== 汇总（%d 轮，每轮新进程） ==" % args.rounds)
    for m in modes:
        st = summary["eager_v242" if m == "eager" else "sliced_v243"]["loop_gap_ms"]
        print("  %-6s 循环缺口 min/中位/max = %s" % (m, st))
    bad = [r for r in rows if not r.get("ok") or r.get("error")]
    if bad:
        print(chr(10) + "测量不成立：%r" % (bad,))
        return 1
    if args.mode == "both":
        e, s = summary["eager_v242"]["loop_gap_ms"], summary["sliced_v243"]["loop_gap_ms"]
        if not (e and s):
            print(chr(10) + "有一侧没测到数")
            return 1
        assert_gap = s["median"] < e["median"]
        print("  判定：分片版中位缺口 %.1fms < 一次性 %.1fms → %s"
              % (s["median"], e["median"], "通过" if assert_gap else "不成立"))
        print("  素材逐张一致：%s" % summary["sliced_v243"]["materials_equal"])
        if not assert_gap or not summary["sliced_v243"]["materials_equal"]:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
