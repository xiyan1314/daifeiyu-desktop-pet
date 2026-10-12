# -*- coding: utf-8 -*-
"""D7-B 工作台：把审计工具的 B 档列表按文件/函数/理由分桶打印（只读，不改代码）。

用法：
    python -B _dev/silent_except_b_list.py            # 汇总
    python -B _dev/silent_except_b_list.py --by-func  # 按文件+函数列出
    python -B _dev/silent_except_b_list.py --json out.json
"""
import argparse
import collections
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIT = os.path.join(HERE, "_dev", "audit_silent_except.py")

# 代理 B 领地之外（本轮由代理 A / C 改造）
FOREIGN = {"pet_plugin.py", "pet_plugin_host.py", "pet_plugin_index.py", "pet_dialogs.py"}


def load_audit():
    spec = importlib.util.spec_from_file_location("audit_silent_except_b", AUDIT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--by-func", action="store_true")
    ap.add_argument("--foreign", action="store_true", help="列领地外明细")
    ap.add_argument("--json")
    ap.add_argument("--tier", default="B")
    args = ap.parse_args(argv)
    audit = load_audit()
    findings = audit.scan(HERE)
    prod = [f for f in findings if not f["nonprod"]]
    counts = collections.Counter(f["tier"] for f in prod)
    print("生产路径三档：A=%d B=%d C=%d OK=%d" % (counts["A"], counts["B"], counts["C"], counts["OK"]))
    sel = [f for f in prod if f["tier"] == args.tier]
    mine = [f for f in sel if os.path.basename(f["file"]) not in FOREIGN]
    foreign = [f for f in sel if os.path.basename(f["file"]) in FOREIGN]
    print("%s 档：合计 %d（领地内 %d · 领地外 %d）" % (args.tier, len(sel), len(mine), len(foreign)))
    print()
    print("== 领地内按文件 ==")
    c = collections.Counter(f["file"] for f in mine)
    for k, v in c.most_common():
        print("%4d  %s" % (v, k))
    print()
    print("== 领地外按文件（只判定） ==")
    c2 = collections.Counter(f["file"] for f in foreign)
    for k, v in c2.most_common():
        print("%4d  %s" % (v, k))
    print()
    print("== 理由分桶（领地内） ==")
    def bucket(r):
        for pre in ("失败以返回值/哨兵上报调用方", "重试/轮询循环", "回滚里的回滚"):
            if r.startswith(pre):
                return pre
        return r
    c3 = collections.Counter(bucket(f["reason"]) for f in mine)
    for k, v in c3.most_common():
        print("%4d  %s" % (v, k))
    if args.foreign:
        print()
        print("== 领地外明细 ==")
        for f in sorted(foreign, key=lambda x: (x["file"], x["line"])):
            print("%s:%d | %s | ann=%s | %s | %s" % (f["file"], f["line"], f["func"],
                                                     "1" if f["annotated"] else "0",
                                                     f["reason"], f["snippet"][:110]))
    if args.by_func:
        print()
        print("== 领地内明细 ==")
        for f in sorted(mine, key=lambda x: (x["file"], x["line"])):
            print("%s:%d | %s | ann=%s | %s" % (f["file"], f["line"], f["func"],
                                                "1" if f["annotated"] else "0", f["reason"]))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(sel, fh, ensure_ascii=False, indent=1)
        print("wrote %s (%d rows)" % (args.json, len(sel)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
