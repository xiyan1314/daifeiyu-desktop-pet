# -*- coding: utf-8 -*-
"""代理C（v2.9.0 第 7 轮 · 任务 C-2）实测：spec 的**锚点文件**是不是都在指纹清单里。

要回答的问题（任务书 C-2 原话）："现状缺这两个 → C 落在它们上的 16 条无法用指纹判过期"。
"判不了过期"有两种，本探针把两种都打出来：

  ① **锚点文件不在指纹清单里**：改了它，发布门**一条"证据过期"提示都不会有**（真盲区）。
     判据 = 逐份 spec 收 `file` 字段，与 `_check_release.MUTATION_FINGERPRINT_FILES` 比。
  ② **证据 JSON 缺键**：老证据落盘时清单里还没有这些文件，它记的指纹里根本没有这个键
     （v2.6.0 的 `probe_fingerprint_gap_v260.py` 覆盖这一面）。

外加一条一致性自检：两处清单（`_check_release` 与 `_dev/_mutate_lib.repo_fingerprint`）
必须逐项一致（`tests/test_release_check.py` 已钉，这里再当场对一遍，便于复现）。

只读：不写任何文件、不跑 pytest、不摸产品代码。
用法：`python -B _dev/probe_fingerprint_gap_v290.py`
"""
import ast
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import _check_release as chk  # noqa: E402


def lib_fingerprint_files():
    """从 _dev/_mutate_lib.py 的 repo_fingerprint 里取出文件清单（与发布门同口径的 AST 取法）。"""
    src = io.open(os.path.join(HERE, "_mutate_lib.py"), encoding="utf-8").read()
    files = None
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == "repo_fingerprint":
            for sub in ast.walk(node):
                if isinstance(sub, ast.For) and isinstance(sub.iter, (ast.Tuple, ast.List)):
                    files = [e.value for e in sub.iter.elts if isinstance(e, ast.Constant)]
    return files or []


def spec_rows():
    """[(spec 文件名, [(变异 id, 锚点文件)])] —— 带 mutations 段的 spec。"""
    out = []
    for name in sorted(os.listdir(HERE)):
        if not (name.startswith("mutations_") and name.endswith(".json")):
            continue
        try:
            with io.open(os.path.join(HERE, name), encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            continue
        muts = data.get("mutations") if isinstance(data, dict) else None
        if muts:
            out.append((name, [(m.get("id") or "?", m.get("file") or "") for m in muts]))
    return out


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    gate = list(chk.MUTATION_FINGERPRINT_FILES)
    lib = lib_fingerprint_files()
    print("指纹清单：发布门 %d 个 / 变异库 %d 个 —— %s"
          % (len(gate), len(lib), "逐项一致" if gate == lib else "⚠ 漂移：%r vs %r" % (gate, lib)))
    print("清单内容：%s" % " / ".join(gate))
    print()

    rows = spec_rows()
    by_file = {}
    for name, muts in rows:
        for mid, rel in muts:
            by_file.setdefault(rel, []).append((name, mid))
    covered = sorted(f for f in by_file if f in gate)
    uncovered = sorted(f for f in by_file if f not in gate)
    total = sum(len(v) for v in by_file.values())
    print("spec %d 份 / 变异 %d 条，锚点落在 %d 个文件上" % (len(rows), total, len(by_file)))
    print("  ① 已被指纹覆盖（改它 → 证据会报「过期」）：%d 个文件 / %d 条变异"
          % (len(covered), sum(len(by_file[f]) for f in covered)))
    print("  ① 未被指纹覆盖（改它 → **零提示**，真盲区）：%d 个文件 / %d 条变异"
          % (len(uncovered), sum(len(by_file[f]) for f in uncovered)))
    for f in uncovered:
        ids = "、".join("%s(%s)" % (mid, name.replace("mutations_", "").replace(".json", ""))
                        for name, mid in by_file[f])
        print("      · %-24s %2d 条：%s" % (f, len(by_file[f]), ids))
    print("  ② 清单里但没有任何 spec 锚在它上面（只是「改了要提示」）：%s"
          % ("、".join(sorted(set(gate) - set(by_file))) or "-"))
    print()

    cur = chk.tree_fingerprint(ROOT)
    print("当前树可算指纹的文件 %d 个（清单里点名的文件都在树上：%s）"
          % (len(cur), "是" if set(cur) == set(gate) else "否，缺 %r" % (set(gate) - set(cur))))
    ev = []
    for name, data in chk._iter_dev_results(ROOT):
        rec = data.get("repo_fingerprint") if isinstance(data, dict) else None
        if not isinstance(rec, dict) and isinstance(data, dict):
            res = data.get("results")
            rec = res.get("repo_fingerprint") if isinstance(res, dict) else None
        if isinstance(rec, dict):
            ev.append((name, len(rec), chk.missing_fingerprint_keys(rec, cur),
                       chk.stale_fingerprints(rec, cur)))
    print("有指纹段的证据 %d 份：缺键 %d 份 / 过期 %d 份"
          % (len(ev), sum(1 for r in ev if r[2]), sum(1 for r in ev if r[3])))
    for name, n, missing, stale in ev:
        print("      %-40s 记了 %2d 键  缺=%s  过期=%s"
              % (name, n, ",".join(missing) or "-", ",".join(stale) or "-"))
    print()
    notes = chk.mutation_evidence_notes(ROOT)
    print("发布门 mutation_evidence_notes() 现在返回 %d 条提示（只提示、不挡发布）：" % len(notes))
    for n in notes:
        print("  [提示] %s" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
