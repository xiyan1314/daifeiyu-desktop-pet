# -*- coding: utf-8 -*-
"""v2.6.0 交叉验证：产品修复（_reset_squash 收尾兜底）会不会把护栏变异的牙齿磨钝。

做法：**复用**护栏代理的 _dev/mutate_proc_reset_v26.py 里的 MUTATIONS 表（同一份锚点，
不复制不漂移），在自己的影子副本里逐条变异 + 跑 _verify_v13.py，结果写
_dev/results_proc_reset_cross_v26.json（**不覆盖**他们的 mutations_proc_reset_v26.json）。

期望：BASELINE 273/0，且 12 条全部仍被捕获（被捕获 = 护栏在"修好之后"依然看得见坏改动）。
用法：python -B _dev/verify_proc_reset_cross_v26.py
"""
import importlib.util
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from _mutate_lib import shadow  # noqa: E402

LOCK = os.path.join(HERE, ".mutation.lock")
TOTAL_RE = re.compile(r"TOTAL CHECKS: (\d+), FAILS: (\d+)")


def _load_mutations():
    spec = importlib.util.spec_from_file_location(
        "mut_proc_reset_v26", os.path.join(HERE, "mutate_proc_reset_v26.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)      # 模块级只有常量与函数（main 在 __main__ 下才跑）
    return mod.MUTATIONS


def run_verify(tree, timeout=900):
    import subprocess
    cmd = [sys.executable, "-B", "_verify_v13.py"]
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run(cmd, cwd=tree, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=timeout, env=env)
    out = p.stdout.decode("utf-8", "replace")
    m = TOTAL_RE.search(out)
    return (p.returncode, int(m.group(1)) if m else -1,
            int(m.group(2)) if m else -1, out)


def main():
    if os.path.exists(LOCK):
        print("ABORT：_dev/.mutation.lock/ 已存在（有别的变异在跑）")
        return 2
    mutations = _load_mutations()
    results = []
    with shadow(what="proc_reset_cross_v26") as tree:
        real = {}
        for _mid, _rel, _a, _b, _exp, _note in mutations:
            if _rel not in real:
                with open(os.path.join(tree, _rel), encoding="utf-8") as f:
                    real[_rel] = f.read()
        print("[baseline] 影子副本（含本次产品修复）跑 _verify_v13.py ...", flush=True)
        rc, total, fails, _out = run_verify(tree)
        base_ok = rc == 0 and total == 273 and fails == 0
        print("[baseline] rc=%s total=%s fails=%s → %s"
              % (rc, total, fails, "OK" if base_ok else "BASELINE-RED"), flush=True)
        results.append(("BASELINE", "PASS" if base_ok else "BASELINE-RED", rc,
                        "total=%s fails=%s" % (total, fails), []))
        for mid, rel, anchor, repl, expect, note in mutations:
            src = real[rel]
            n = src.count(anchor)
            if n != 1:
                results.append((mid, "ANCHOR-LOST", None, "锚点命中 %d 次" % n, []))
                print("[%s] ANCHOR-LOST（%d 次）%s" % (mid, n, note), flush=True)
                continue
            with open(os.path.join(tree, rel), "w", encoding="utf-8") as f:
                f.write(src.replace(anchor, repl))
            t0 = time.time()
            rc2, total2, fails2, out2 = run_verify(tree)
            hit = [e for e in expect if ("FAIL " + e) in out2]
            caught = rc2 != 0 and fails2 >= 1 and len(hit) == len(expect)
            verdict = "CAUGHT" if caught else "NOT CAUGHT"
            tail = "rc=%s total=%s fails=%s 命中=%s 用时=%.1fs" % (
                rc2, total2, fails2, hit, time.time() - t0)
            results.append((mid, verdict, rc2, tail, hit))
            print("[%s] %-10s %s | %s" % (mid, verdict, note, tail), flush=True)
            if verdict == "NOT CAUGHT":
                print(out2[-2500:])
            with open(os.path.join(tree, rel), "w", encoding="utf-8") as f:
                f.write(src)
    payload = {
        "title": "v2.6.0 产品修复 × 护栏变异交叉验证（影子副本）",
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "note": "复用 _dev/mutate_proc_reset_v26.py 的 MUTATIONS 表；不覆盖其证据文件",
        "total": len(results) - 1,
        "caught": len([r for r in results[1:] if r[1] == "CAUGHT"]),
        "not_caught": len([r for r in results[1:] if r[1] != "CAUGHT"]),
        "items": [{"id": r[0], "verdict": r[1], "rc": r[2], "tail": r[3], "hit": r[4]}
                  for r in results],
    }
    path = os.path.join(HERE, "results_proc_reset_cross_v26.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write(chr(10))
    ok = results[0][1] == "PASS" and all(r[1] == "CAUGHT" for r in results[1:])
    print("=" * 60)
    print("变异 %d 条，CAUGHT %d；锁存在=%s"
          % (len(results) - 1, payload["caught"], os.path.exists(LOCK)))
    print("结果: %s" % path)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
