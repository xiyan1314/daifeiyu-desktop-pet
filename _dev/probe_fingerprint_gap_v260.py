# -*- coding: utf-8 -*-
"""代理C（v2.6.0）实测：发布门"证据缺键"提示的影响面。

只读：调 _check_release.mutation_evidence_notes()，打印它现在会说什么，
以及每份 _dev/*.json 缺哪些键。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import _check_release as chk

cur = chk.tree_fingerprint(ROOT)
print("当前树关键文件 %d 个：%s" % (len(cur), " / ".join(sorted(cur))))
print()
rows = []
for name, data in chk._iter_dev_results(ROOT):
    rec = data.get("repo_fingerprint") if isinstance(data, dict) else None
    if not isinstance(rec, dict) and isinstance(data, dict):
        res = data.get("results")
        rec = res.get("repo_fingerprint") if isinstance(res, dict) else None
    if not isinstance(rec, dict):
        continue
    missing = chk.missing_fingerprint_keys(rec, cur)
    stale = chk.stale_fingerprints(rec, cur)
    rows.append((name, len(rec), missing, stale))

print("有指纹段的证据 %d 份：缺键 %d 份 / 过期 %d 份"
      % (len(rows), sum(1 for r in rows if r[2]), sum(1 for r in rows if r[3])))
for name, n, missing, stale in rows:
    print("  %-38s 记了 %2d 键  缺=%s  过期=%s"
          % (name, n, ",".join(missing) or "-", ",".join(stale) or "-"))
print()
notes = chk.mutation_evidence_notes(ROOT)
print("mutation_evidence_notes() 现在返回 %d 条：" % len(notes))
for n in notes:
    print("  [提示] %s" % n)
