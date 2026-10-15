# -*- coding: utf-8 -*-
"""铁律 5：对着**当前树**整批复跑全部变异证据（v2.7.0 · 代理 C）。

跑什么（四类，一份都不落下）：
  ① `_dev/mutations_*.json` 里带 mutations 段的 spec → `_dev/mutate_check.py`（同一实现，不改判据）；
  ② 三份**旧形态单脚本驱动**：mutate_export_slice.py / mutate_startup_defer.py /
     mutate_proc_reset_v26.py（它们的变异写在脚本里，结果落成 mutations_*.json）；
  ③ 两份独立结果：verify_fastci_slices_v251.py（results_fastci_slices_v251.json）与
     verify_guardrails_can_fail.py（results_guardrails_can_fail.json）。

用法：
    python -B _dev/mutate_batch_v270.py --scan-only   # 只查锚点命中数（秒级，不跑 pytest）
    python -B _dev/mutate_batch_v270.py               # 整批跑（串行；变体都在 %%TEMP%% 影子里做）

结果：_dev/results_batch_v270.json —— 每项 rc / 末行 / 用时 / 产出文件，外加**跑前跑后**的
源码指纹（两者不一致 = 批次窗口里有人改了树，这一批证据不可信，必须重跑）。
退出码：0 = 全绿；1 = 有项非 0 / 指纹在窗口里变了。
"""
import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from _mutate_lib import repo_fingerprint  # noqa: E402


def _py():
    return sys.executable


def _child_env():
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def spec_files():
    """带 mutations 段的 spec（旧形态那三份只有 results 段，不在这里）。"""
    out = []
    for name in sorted(os.listdir(HERE)):
        if not (name.startswith("mutations_") and name.endswith(".json")):
            continue
        try:
            with io.open(os.path.join(HERE, name), encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            continue
        if isinstance(data, dict) and data.get("mutations"):
            out.append(name)
    return out


def targets():
    out = []
    for name in spec_files():
        out.append((name, [_py(), "-B", os.path.join("_dev", "mutate_check.py"),
                           os.path.join("_dev", name)]))
    for name, driver in (("mutations_export_slice_v242.json", "mutate_export_slice.py"),
                         ("mutations_startup_defer_v242.json", "mutate_startup_defer.py"),
                         ("mutations_proc_reset_v26.json", "mutate_proc_reset_v26.py"),
                         ("results_fastci_slices_v251.json", "verify_fastci_slices_v251.py"),
                         ("results_guardrails_can_fail.json", "verify_guardrails_can_fail.py")):
        out.append((name, [_py(), "-B", os.path.join("_dev", driver)]))
    return out


# ---------------- 锚点体检（不跑 pytest） ----------------
def _anchor_rows(name):
    """(文件名, [(变异 id, 锚点命中数, 说明)]) —— spec 与旧形态脚本都认。"""
    if name.endswith(".json"):
        with io.open(os.path.join(HERE, name), encoding="utf-8") as fh:
            data = json.load(fh)
        rows = [(m.get("id") or "?", m.get("file") or "", m.get("old") or "")
                for m in data.get("mutations") or []]
    else:
        import importlib.util
        path = os.path.join(HERE, name)
        spec = importlib.util.spec_from_file_location("anchor_" + name[:-3], path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        rows = []
        for item in getattr(mod, "MUTATIONS", []):
            if len(item) >= 6:          # proc_reset：(id, file, old, new, expect, note)
                rows.append((item[0], item[1], item[2]))
            else:                        # export_slice / startup_defer：(name, file, old, new)
                rows.append((item[0], item[1], item[2]))
    return rows


def scan_only():
    """只查每份 spec / 驱动里每条锚点在当前树里命中几次（要求恰好 1 次）。"""
    src_cache = {}
    total = bad = 0
    for name in spec_files() + ["mutate_export_slice.py", "mutate_startup_defer.py",
                                "mutate_proc_reset_v26.py"]:
        try:
            rows = _anchor_rows(name)
        except Exception as e:
            print("%-40s 读不出来：%r" % (name, e))
            continue
        broken = []
        for mid, rel, old in rows:
            total += 1
            if rel not in src_cache:
                p = os.path.join(ROOT, rel.replace("/", os.sep))
                try:
                    with io.open(p, encoding="utf-8") as fh:
                        src_cache[rel] = fh.read()
                except Exception:
                    src_cache[rel] = ""
            n = src_cache[rel].count(old)
            if n != 1:
                broken.append((mid, rel, n))
                bad += 1
        print("%-40s 锚点 %2d，坏 %d%s" % (name, len(rows), len(broken),
                                          "" if not broken else "  → " + "；".join(
                                              "%s@%s(%d 次)" % (m, f, c) for m, f, c in broken)))
    print("\n锚点合计 %d 条，坏 %d 条（坏 = 命中次数不是 1：源码改过，需要重锚）" % (total, bad))
    return 1 if bad else 0


def run_all():
    before = repo_fingerprint(ROOT)
    rows = []
    failed = []
    print("跑前源码指纹：%s" % json.dumps(before, ensure_ascii=False, sort_keys=True))
    for name, argv in targets():
        t0 = time.time()
        print("\n=== %s ===" % name, flush=True)
        p = subprocess.run(argv, cwd=ROOT, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, env=_child_env())
        out = (p.stdout or b"").decode("utf-8", "replace")
        tail = [ln for ln in out.strip().splitlines() if ln.strip()]
        tail = tail[-1][:160] if tail else ""
        print(out[-2500:], flush=True)
        rows.append({"target": name, "rc": p.returncode, "tail": tail,
                     "seconds": round(time.time() - t0, 1), "argv": argv[2:]})
        if p.returncode != 0:
            failed.append(name)
    after = repo_fingerprint(ROOT)
    moved = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    payload = {"title": "铁律 5：整批变异证据复跑（v2.7.0 · 代理 C）",
               "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
               "total": len(rows), "failed": failed,
               "items": rows,
               "fingerprint_before": before, "fingerprint_after": after,
               "fingerprint_moved": moved,
               "note": "全部在 %%TEMP%% 影子副本里跑；真仓只写 _dev/.mutation.lock 与结果 JSON"}
    path = os.path.join(HERE, "results_batch_v270.json")
    with io.open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write(chr(10))
    print("\n%-42s %-4s %8s  %s" % ("证据", "rc", "秒", "末行"))
    for r in rows:
        print("%-42s %-4s %8s  %s" % (r["target"], r["rc"], r["seconds"], r["tail"]))
    if moved:
        print("\n⚠ 跑前跑后指纹不一致（%s）：这一批证据不是对着同一棵树测的，必须重跑！"
              % "、".join(moved))
    print("\n%d 项，%d 项非 0%s" % (len(rows), len(failed),
                                     ("：" + "、".join(failed)) if failed else ""))
    print("结果已写：%s" % os.path.relpath(path, ROOT))
    return 1 if (failed or moved) else 0


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass  # 有意忽略：老解释器没有 reconfigure
    ap = argparse.ArgumentParser(description="整批变异证据复跑（铁律 5）")
    ap.add_argument("--scan-only", action="store_true", help="只查锚点命中数，不跑 pytest")
    args = ap.parse_args()
    return scan_only() if args.scan_only else run_all()


if __name__ == "__main__":
    sys.exit(main())
