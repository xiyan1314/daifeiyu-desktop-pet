# -*- coding: utf-8 -*-
"""D7-B 逐条判定用上下文导出（只读）：把每个 B 档 handler 的 try 体 / 异常类型 / handler 体打平。

用法：python -B _dev/silent_except_ctx.py [--skip-foreign] [--file X.py] [--from N]
"""
import argparse
import ast
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FOREIGN = {"pet_plugin.py", "pet_plugin_host.py", "pet_plugin_index.py", "pet_dialogs.py"}


def flat(node, src, limit=160):
    try:
        seg = ast.get_source_segment(src, node) or ""
    except Exception:
        seg = ""
    seg = re.sub(r"\s+", " ", seg).strip()
    return seg[:limit]


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-foreign", action="store_true")
    ap.add_argument("--file")
    ap.add_argument("--tier", default="B")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    if args.out:
        sys.stdout = io.open(args.out, "w", encoding="utf-8")

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "audit_ctx", os.path.join(HERE, "_dev", "audit_silent_except.py"))
    audit = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = audit
    spec.loader.exec_module(audit)

    findings = [f for f in audit.scan(HERE)
                if not f["nonprod"] and f["tier"] == args.tier
                and not (args.skip_foreign and os.path.basename(f["file"]) in FOREIGN)
                and (not args.file or f["file"] == args.file)]
    by_file = {}
    for f in findings:
        by_file.setdefault(f["file"], []).append(f)
    for rel in sorted(by_file):
        path = os.path.join(HERE, rel)
        with io.open(path, "r", encoding="utf-8-sig") as fh:
            src = fh.read()
        tree = ast.parse(src)
        tries = [n for n in ast.walk(tree) if isinstance(n, ast.Try)]
        print("### %s" % rel)
        for f in sorted(by_file[rel], key=lambda x: x["line"]):
            hit = None
            for t in tries:
                for h in t.handlers:
                    if getattr(h, "lineno", 0) == f["line"]:
                        hit = (t, h)
            if hit is None:
                print("%d [%s] ???" % (f["line"], f["func"]))
                continue
            t, h = hit
            etype = ""
            if h.type is not None:
                etype = flat(h.type, src, 40)
            print("%d [%s]%s TRY{%s} EXC(%s) H{%s}" % (
                f["line"], f["func"], " ANN" if f["annotated"] else "",
                flat(t, src, 150), etype, flat(h, src, 150).replace("except %s:" % etype, "")))
        sys.stdout.flush()
    if args.out:
        sys.stdout.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
