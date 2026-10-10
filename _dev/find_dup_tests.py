# -*- coding: utf-8 -*-
"""定位语义重复的测试用例：AST 取每个 test_* 的函数体，归一化后算相似度。

用法: python _dev/find_dup_tests.py [最低相似度, 默认 0.70]
只读，不写任何文件。
"""
import ast
import difflib
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")


def norm_body(src_segment):
    lines = []
    for ln in src_segment.splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        lines.append(s)
    return lines


def collect():
    out = []
    for fn in sorted(os.listdir(TESTS)):
        if not (fn.startswith("test_") and fn.endswith(".py")):
            continue
        path = os.path.join(TESTS, fn)
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        tree = ast.parse(text)
        src = text.splitlines()
        funcs = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                funcs.append((node.name, node))
            elif isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name.startswith("test_"):
                        funcs.append((node.name + "." + sub.name, sub))
        for name, node in funcs:
            seg = "\n".join(src[node.lineno - 1:node.end_lineno])
            # 去掉 def 行与装饰器行（名字不同不构成语义差异的判据）
            body = [l for l in norm_body(seg) if not re.match(r"^(def |@)", l)]
            asserts = [l for l in body if l.startswith("assert ")]
            out.append({"file": fn, "name": name, "body": body, "asserts": asserts,
                        "text": "\n".join(body)})
    return out


def main():
    thr = float(sys.argv[1]) if len(sys.argv) > 1 else 0.70
    items = collect()
    print("收集到 %d 个用例" % len(items))
    pairs = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            if not a["body"] or not b["body"]:
                continue
            r = difflib.SequenceMatcher(None, a["body"], b["body"]).ratio()
            if r >= thr:
                pairs.append((r, a, b))
    pairs.sort(key=lambda x: -x[0])
    print("相似度 >= %.2f 的用例对: %d\n" % (thr, len(pairs)))
    for r, a, b in pairs[:60]:
        print("%.3f  %s::%s  <->  %s::%s" % (r, a["file"], a["name"], b["file"], b["name"]))
        print("        A asserts=%d B asserts=%d" % (len(a["asserts"]), len(b["asserts"])))


if __name__ == "__main__":
    main()
