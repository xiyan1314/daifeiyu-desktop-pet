# -*- coding: utf-8 -*-
"""定位语义重复（v4）：按"被测符号"分组，列出**同一符号被多个文件/多个用例覆盖**的地方。

被测符号 = ast.Attribute 链的完整点号路径（pet_alarm.normalize_time / svc.add 只取末段方法名），
以及被测类名。用法: python _dev/find_dup_symbols.py [只看跨文件的] 
只读。
"""
import ast
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
MODULE_PREFIX = ("pet_", "main", "桌宠")


def dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def collect():
    tests = []
    for fn in sorted(os.listdir(TESTS)):
        if not (fn.startswith("test_") and fn.endswith(".py")):
            continue
        with open(os.path.join(TESTS, fn), "r", encoding="utf-8") as f:
            text = f.read()
        tree = ast.parse(text)
        funcs = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                funcs.append((node.name, node))
            elif isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name.startswith("test_"):
                        funcs.append((node.name + "." + sub.name, sub))
        for name, node in funcs:
            syms = set()
            for n in ast.walk(node):
                if isinstance(n, ast.Attribute):
                    d = dotted(n)
                    if d:
                        root = d.split(".")[0]
                        if root.startswith(MODULE_PREFIX) or root in ("voice", "lines", "alarm", "lib", "svc"):
                            syms.add(d if len(d.split(".")) > 1 else d)
                    # 方法名单独记（svc.add → add）
                    syms.add("." + n.attr)
            tests.append({"file": fn, "name": name, "syms": syms,
                          "line": node.lineno})
    return tests


def main():
    cross_only = "--cross" in sys.argv
    items = collect()
    bysym = defaultdict(list)
    for t in items:
        for s in t["syms"]:
            bysym[s].append(t)
    rows = []
    for s, ts in bysym.items():
        if len(ts) < 2:
            continue
        files = {t["file"] for t in ts}
        if cross_only and len(files) < 2:
            continue
        rows.append((len(files), len(ts), s, ts))
    rows.sort(key=lambda x: (-x[0], -x[1], x[2]))
    for nf, nt, s, ts in rows:
        if len(s) <= 3:
            continue
        print("%-38s 文件%d 用例%d" % (s, nf, nt))
        for t in ts:
            print("      %s::%s:%d" % (t["file"], t["name"], t["line"]))
        print()


if __name__ == "__main__":
    main()
