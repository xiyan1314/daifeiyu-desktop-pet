# -*- coding: utf-8 -*-
"""v2.6.0 对照实验：动作自定义段落的"环境插播收尾"（settle）到底是不是承重的。

场景：上一拍闲逛节拍在**别的 check 的事件循环里**插播了一次 jump，之后脚本长时间不泵事件
→ 该动画冻结在途、busy 一直为真；而本段所有动作都走 play_action（有 busy 门控）。
本脚本在 %TEMP% 影子副本里跑两遍同一个探针（_dev/probe_proc_reset_v26.py --force prejump）：
  A 对照：把 _verify_v13.py 里的 settle 段摘掉 → 预期被门控吞掉、连红
  B 现状：原样                     → 预期 273/0
用法：python -B _dev/verify_ambient_settle_v26.py
"""
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from _mutate_lib import shadow, write_results  # noqa: E402

SETTLE_HEAD = '    _amb = getattr(pet, "_tween_anim", None)\n'
SETTLE_TAIL = '    # 播放：命名帧动作 → 播完自动回待机\n'
TOTAL_RE = re.compile(r"TOTAL CHECKS: (\d+), FAILS: (\d+)")


def run_probe(tree):
    cmd = [sys.executable, "-B", os.path.join("_dev", "probe_proc_reset_v26.py"),
           "--force", "prejump"]
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run(cmd, cwd=tree, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=900, env=env)
    out = p.stdout.decode("utf-8", "replace")
    m = TOTAL_RE.search(out)
    reds = [ln.split(" ", 1)[1].strip() for ln in out.splitlines() if ln.startswith("FAIL ")]
    nonvacuous = "PREJUMP:" in open(os.path.join(tree, "_dev", "probe_proc_reset_v26.log"),
                                    encoding="utf-8", errors="replace").read()
    return p.returncode, (int(m.group(1)) if m else -1), (int(m.group(2)) if m else -1), reds, nonvacuous


def main():
    results = []
    with shadow(what="ambient_settle_v26") as tree:
        vp = os.path.join(tree, "_verify_v13.py")
        with open(vp, encoding="utf-8") as f:
            original = f.read()
        i = original.index(SETTLE_HEAD)
        j = original.index(SETTLE_TAIL, i)
        with open(vp, "w", encoding="utf-8") as f:
            f.write(original[:i] + original[j:])
        rc, total, fails, reds, nv = run_probe(tree)
        print("[A 无 settle] rc=%s total=%s fails=%s 注入生效=%s\n    %s"
              % (rc, total, fails, nv, reds), flush=True)
        # 注意：探针内部走 runpy 并吞掉 SystemExit，所以判红看 FAILS 数而不是 rc。
        results.append(("A-无 settle（对照）",
                        "RED-AS-EXPECTED" if fails > 0 and nv else "GREEN?!", rc,
                        "fails=%s 红=%s" % (fails, [r.split(" ")[0] for r in reds]), reds))
        with open(vp, "w", encoding="utf-8") as f:
            f.write(original)
        rc2, total2, fails2, reds2, nv2 = run_probe(tree)
        print("[B 有 settle] rc=%s total=%s fails=%s 注入生效=%s\n    %s"
              % (rc2, total2, fails2, nv2, reds2), flush=True)
        results.append(("B-有 settle（现状）",
                        "GREEN-AS-EXPECTED" if total2 == 273 and fails2 == 0 and nv2
                        else "RED?!", rc2, "total=%s fails=%s" % (total2, fails2), reds2))
    path = write_results(os.path.join(HERE, "results_ambient_settle_v26.json"),
                         "v2.6.0 环境插播收尾（settle）承重对照", results,
                         {"stamp": time.strftime("%Y-%m-%d %H:%M:%S")})
    ok = results[0][1] == "RED-AS-EXPECTED" and results[1][1] == "GREEN-AS-EXPECTED"
    print("=" * 60)
    print("对照结论：%s" % ("settle 承重成立（无它必红/有它绿）" if ok else "结论不成立，需复查"))
    print("结果: %s" % path)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
