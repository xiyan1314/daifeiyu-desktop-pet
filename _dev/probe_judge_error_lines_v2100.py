# -*- coding: utf-8 -*-
"""judge 口径变更的对照探针（v2.10.0 第 8 轮 · 代理 C · 任务 R5）。

**这份脚本是"改判定口径"这件事的安全带**：口径一动，全部 spec 的判定都可能变，而
results JSON 里**没有存 ERROR 行**（旧口径根本不看它），所以光读盘上的证据**算不出**哪几条会翻。
两条路一起给：

  ① **--dry-run（默认，不跑 pytest）**：把全库 results 里**非 CAUGHT** 的条目逐条列出来，
     按"能不能翻"分类：
       · rc == 0            → 不会翻（新口径也要求 rc != 0）；
       · rc != 0 且 failed 为空 → **只能靠 ERROR 行翻**（旧口径判 WRONG TEST 的典型形态）；
       · rc != 0 且有 failed 但没覆盖全部 expect_fail → 要看 ERROR 行有没有点名剩下那几条。
  ② **--run**：把候选**真的在影子副本里重跑一遍**，同一份输出分别喂给
     judge(m, rc, failed)（旧口径）与 judge(m, rc, failed, errored_nodeids(out))（新口径），
     逐条打印 旧判定 → 新判定、ERROR 行原文与相位（setup/call/teardown）。

用法：
    python -B _dev/probe_judge_error_lines_v2100.py                     # 只对账，不跑
    python -B _dev/probe_judge_error_lines_v2100.py --run               # 真重跑候选
    python -B _dev/probe_judge_error_lines_v2100.py --run --spec _dev/mutations_agent_a_v290.json

判定口径的"为什么更正确"写在 mutate_check.judge 的 docstring 与 _dev/README.md 里，
本脚本只负责**把影响面摆出来**，不做判定。
"""
import glob
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import mutate_check  # noqa: E402
from _mutate_lib import (errored_nodeids, last_line, run_pytest, shadow,  # noqa: E402
                         test_error_phases)

BAD = ("NOT CAUGHT", "WRONG TEST", "SPEC-BAD", "ANCHOR-LOST", "INVALID", "BASELINE-RED")


def _read_json(path):
    with io.open(path, encoding="utf-8") as f:
        return json.loads(f.read())


def spec_paths(only=None):
    if only:
        return [only if os.path.isabs(only) else os.path.join(ROOT, only)]
    return sorted(p for p in glob.glob(os.path.join(ROOT, "_dev", "mutations_*.json")))


def collect_candidates(only=None):
    """→ [(spec_path, spec, item, mutation or None)]，只收非 CAUGHT 的条目。"""
    out = []
    for sp in spec_paths(only):
        try:
            data = _read_json(sp)
        except Exception as e:
            print("  [跳过] %s：%r" % (os.path.basename(sp), e))
            continue
        res = data.get("results")
        items = res.get("items") if isinstance(res, dict) else None
        if not isinstance(items, list):
            continue
        by_id = {m.get("id"): m for m in data.get("mutations", [])}
        for it in items:
            if str(it.get("verdict") or "").upper() in BAD:
                out.append((sp, data, it, by_id.get(it.get("id"))))
    return out


def classify(item):
    """候选能不能翻（纯读盘预测，不需要 ERROR 行）。"""
    rc = item.get("rc")
    failed = item.get("failed") or []
    if rc == 0:
        return "不会翻（rc=0，新口径也要求 rc != 0）"
    if not failed:
        return "**只能靠 ERROR 行翻**（旧口径：rc!=0 但 FAILED 列表为空）"
    return "部分覆盖（failed 非空；要看 ERROR 行有没有点名剩下那几条）"


def dry_run(only=None):
    cands = collect_candidates(only)
    print("=== 全库 results 里非 CAUGHT 的条目 ===")
    if not cands:
        print("（无）")
        return 0
    for sp, _data, it, m in cands:
        print("")
        print("%s :: %s" % (os.path.basename(sp), it.get("id")))
        print("  旧判定 %s / rc=%s / failed=%r / 末行 %s"
              % (it.get("verdict"), it.get("rc"), it.get("failed") or [], it.get("tail")))
        print("  预测：%s" % classify(it))
        if m:
            print("  expect_fail=%r" % (m.get("expect_fail") or m.get("tests") or [],))
        else:
            print("  （这份 spec 里已经没有这条变异 id —— 无法重跑）")
    print("")
    print("合计 %d 条非 CAUGHT。--run 会把这些（在影子里）逐条重跑，用新旧两种口径各判一次。" %
          len(cands))
    return 0


def rerun(only=None):
    cands = collect_candidates(only)
    if not cands:
        print("没有非 CAUGHT 的条目 —— 没有可对账的对象。")
        return 0
    by_spec = {}
    for sp, data, it, m in cands:
        by_spec.setdefault(sp, []).append((it, m))
    flipped = 0
    same = 0
    skipped = 0
    for sp, pairs in sorted(by_spec.items()):
        data = _read_json(sp)
        baseline = sorted({t for _it, m in pairs if m for t in (m.get("tests") or [])})
        if not baseline:
            print("[%s] 没有可跑的用例（变异已不在 spec 里）→ 跳过" % os.path.basename(sp))
            skipped += len(pairs)
            continue
        with shadow(what="judge_compare:" + os.path.basename(sp)) as tree:
            rc, failed, out = run_pytest(tree, baseline)
            if rc != 0:
                print("[%s] 基线就不过（影子）：%r —— 这批不作数，跳过" %
                      (os.path.basename(sp), failed[:5]))
                skipped += len(pairs)
                continue
            print("[%s] 基线 %d 条用例全过（影子）" % (os.path.basename(sp), len(baseline)))
            for it, m in pairs:
                mid = it.get("id")
                if not m:
                    print("  %-44s 跳过（spec 里找不到这条）" % mid)
                    skipped += 1
                    continue
                path = os.path.join(tree, m["file"])
                with io.open(path, encoding="utf-8") as f:
                    orig = f.read()
                n = orig.count(m["old"])
                if n != 1:
                    print("  %-44s 跳过（锚点命中 %d 次）" % (mid, n))
                    skipped += 1
                    continue
                try:
                    with io.open(path, "w", encoding="utf-8") as f:
                        f.write(orig.replace(m["old"], m["new"]))
                    rc, failed, out = run_pytest(tree, m["tests"])
                finally:
                    with io.open(path, "w", encoding="utf-8") as f:
                        f.write(orig)
                errors = errored_nodeids(out)
                old_v, _ = mutate_check.judge(m, rc, failed)
                new_v, _ = mutate_check.judge(m, rc, failed, errors)
                phases = test_error_phases(out)
                print("  %-44s rc=%s  旧 %-11s → 新 %-11s  %s"
                      % (mid, rc, old_v, new_v, "★ 翻转" if old_v != new_v else ""))
                print("      FAILED %r" % (failed,))
                for e in errors:
                    print("      ERROR  %s   [%s]" % (e, phases.get(e.split("[")[0], "?")))
                if not errors and failed:
                    print("      （没有 ERROR 行）")
                if old_v != new_v:
                    flipped += 1
                else:
                    same += 1
                print("      末行 %s" % last_line(out))
    print("")
    print("对账结果：翻 %d 条 · 不翻 %d 条 · 跳过 %d 条" % (flipped, same, skipped))
    return 0


def main(argv):
    only = None
    if "--spec" in argv:
        only = argv[argv.index("--spec") + 1]
    print("判定口径对照（v2.10.0 第 8 轮 · R5）：旧 = 只看 FAILED 行；新 = FAILED + 点名到用例的 ERROR 行")
    print("")
    if "--run" in argv:
        return rerun(only)
    return dry_run(only)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
