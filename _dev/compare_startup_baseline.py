# -*- coding: utf-8 -*-
"""启动耗时 A/B 对照：把同一份探针在**基线树**与**当前树**上交替跑，抵消机器负载漂移。

为什么要交替：探针本身很准（进程内 perf_counter），但同一次测量会被机器负载左右——
本轮实测同一个树、同一个脚本，单轮构造从 60.8ms 到 173.3ms 都出现过（旁边还有别的
会话在跑 pytest）。不交替的话，"改前 100ms / 改后 133ms"完全可能是"改前机器闲、
改后机器忙"。所以：每一轮先后各跑一次基线、各跑一次当前，成对统计。

基线树怎么来（一次性）：
    git worktree add ../wt-p-baseline HEAD
    # 把**不属于本次改动**的其它工作区改动抄进去，保证两边只差被测量的那几个文件：
    copy pet_alarm.py pet_behaviors.py pet_lines.py _check_static.py tests\ 过去
    copy _dev\probe_startup_cost.py 过去

用法：
    python _dev/compare_startup_baseline.py --baseline "E:\\deep seek\\wt-p-baseline" --rounds 5
    python _dev/compare_startup_baseline.py --baseline ... --json _dev/startup_ab.json

退出码：0 = 两侧都测到了有效样本；1 = 有一侧没测出来（脚本/环境坏了）。
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE = os.path.join("_dev", "probe_startup_cost.py")


def _invoke(repo, runs, sample):
    """在一个仓库里跑一次探针，返回它的 rows。"""
    out = os.path.join(tempfile.gettempdir(), "probe_ab_%d.json" % os.getpid())
    cmd = [sys.executable, PROBE, "--runs", str(runs), "--json", out]
    if not sample:
        cmd.append("--no-sample")
    p = subprocess.run(cmd, cwd=repo, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not os.path.isfile(out):
        print("探针没产出 JSON（exit=%s）：%s" % (p.returncode, repo))
        return []
    with open(out, encoding="utf-8") as fp:
        rows = json.load(fp)["rows"]
    try:
        os.unlink(out)
    except OSError:
        pass
    return rows


def _stat(vals):
    vals = sorted(v for v in vals if isinstance(v, (int, float)))
    if not vals:
        return None
    return (vals[0], statistics.median(vals), vals[-1])


def _line(label, a, b):
    sa, sb = _stat(a), _stat(b)
    if sa is None or sb is None:
        return "  %-26s 基线 %s / 改后 %s" % (label, sa, sb)
    delta = sb[1] - sa[1]
    pct = (100.0 * delta / sa[1]) if sa[1] else 0.0
    return ("  %-26s 基线 %7.1f / %7.1f / %7.1f    改后 %7.1f / %7.1f / %7.1f"
            "    中位 %+7.1f ms (%+.0f%%)"
            % (label, sa[0], sa[1], sa[2], sb[0], sb[1], sb[2], delta, pct))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True, help="基线仓库路径（git worktree）")
    ap.add_argument("--current", default=HERE)
    ap.add_argument("--rounds", type=int, default=5, help="交替轮数（每轮两侧各一次）")
    ap.add_argument("--runs", type=int, default=3, help="每次调用里的测量次数（首轮冷启动会被丢掉）")
    ap.add_argument("--sample", action="store_true", help="带采样尺（约 +5% 干扰）")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    base, cur = [], []
    for i in range(args.rounds):
        for repo, acc in ((args.baseline, base), (args.current, cur)):
            rows = _invoke(repo, args.runs, args.sample)
            # 每轮调用里的第一条是"进程内冷启动"（首触页/首次解码），两侧都丢，保证只比稳态
            acc.extend(rows[1:] or rows)
        sys.stdout.write("\r已完成 %d/%d 轮交替测量" % (i + 1, args.rounds))
        sys.stdout.flush()
    print()

    if not base or not cur:
        print("测量失败：基线 %d 条、当前 %d 条" % (len(base), len(cur)))
        return 1

    print("\n样本数：基线 %d 条、当前 %d 条（交替 %d 轮 × 每轮 %d 次，各丢 1 次冷启动）"
          % (len(base), len(cur), args.rounds, args.runs))
    print("\n== 启动耗时 A/B（min / 中位 / max，毫秒）==")
    print(_line("PetWindow() 构造", [r["init_ms"] for r in base], [r["init_ms"] for r in cur]))
    print(_line("self.show() 被调用",
                [r["t_show_call_ms"] for r in base if r["t_show_call_ms"]],
                [r["t_show_call_ms"] for r in cur if r["t_show_call_ms"]]))
    print(_line("事件循环首次绘制",
                [r["t_first_paint_ms"] for r in base if r["t_first_paint_ms"]],
                [r["t_first_paint_ms"] for r in cur if r["t_first_paint_ms"]]))
    print(_line("构造期解码 PNG 张数",
                [r["after_init"]["decodes_ctor"] for r in base if "decodes_ctor" in r["after_init"]]
                or [r["decodes"] for r in base],
                [r["after_init"]["decodes_ctor"] for r in cur if "decodes_ctor" in r["after_init"]]
                or [r["decodes"] for r in cur]))

    print("\n== 构造刚返回时的状态（每侧取一轮代表）==")
    for tag, rows in (("基线", base), ("改后", cur)):
        blk = rows[0].get("after_init", {})
        print("  %-4s %s" % (tag, json.dumps(blk, ensure_ascii=False)))

    ok = all(r.get("first_pix_ok") and r.get("first_paint_seen") for r in base + cur)
    print("\n首屏不变量（两侧每次构造都收到绘制 + item 上是非空图）：%s"
          % ("PASS" if ok else "FAIL"))

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fp:
            json.dump({"baseline": args.baseline, "current": args.current,
                       "baseline_rows": base, "current_rows": cur}, fp,
                      ensure_ascii=False, indent=1)
        print("JSON → %s" % args.json)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
