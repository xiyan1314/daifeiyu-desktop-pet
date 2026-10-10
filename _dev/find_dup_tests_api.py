# -*- coding: utf-8 -*-
"""定位"语义重复"的测试用例（v2）：按"用例触碰的 API 面"聚类，而不是按文本相似度。

对每个 test_* 收集指纹：
  · 被调用的名字（ast.Call 的 func 末段）
  · 属性名（ast.Attribute 的 attr）
  · 出现的字符串常量（去掉过短/纯路径的）
  · 断言里出现的名字集合
再算两两 Jaccard 相似度，并按"名字词元相似度"加权排序输出，人工复核。

用法: python _dev/find_dup_tests.py --api [阈值]
只读。
"""
import ast
import difflib
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
SKIP_STR = re.compile(r"^[\w./\\-]*$")


def collect():
    out = []
    for fn in sorted(os.listdir(TESTS)):
        if not (fn.startswith("test_") and fn.endswith(".py")):
            continue
        with open(os.path.join(TESTS, fn), "r", encoding="utf-8") as f:
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
            calls, attrs, strs, asserted = set(), set(), set(), set()
            for n in ast.walk(node):
                if isinstance(n, ast.Call):
                    f = n.func
                    if isinstance(f, ast.Name):
                        calls.add(f.id)
                    elif isinstance(f, ast.Attribute):
                        attrs.add(f.attr)
                elif isinstance(n, ast.Attribute):
                    attrs.add(n.attr)
                elif isinstance(n, ast.Constant) and isinstance(n.value, str):
                    v = n.value
                    if 3 <= len(v) <= 60 and not SKIP_STR.match(v) and "/" not in v and "\\" not in v:
                        strs.add(v)
                elif isinstance(n, ast.Assert):
                    for m in ast.walk(n.test):
                        if isinstance(m, ast.Attribute):
                            asserted.add(m.attr)
                        elif isinstance(m, ast.Name):
                            asserted.add(m.id)
            body = []
            for ln in src[node.lineno - 1:node.end_lineno]:
                s = ln.strip()
                if s and not s.startswith("#"):
                    body.append(s)
            out.append({"file": fn, "name": name,
                        "fp": calls | {a for a in attrs},
                        "asserted": asserted, "strs": strs,
                        "text": "\n".join(body)})
    return out


def jac(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / float(len(a | b))


def name_sim(a, b):
    ta = set(re.split(r"[_.]", a.lower())) - {"test", "v24", "v241", "v231", "v23", "v21", "v230", "the", "and"}
    tb = set(re.split(r"[_.]", b.lower())) - {"test", "v24", "v241", "v231", "v23", "v21", "v230", "the", "and"}
    return jac(ta, tb)


def main():
    thr = float(sys.argv[2]) if len(sys.argv) > 2 else 0.7
    items = collect()
    pairs = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            api = jac(a["fp"], b["fp"])
            ns = name_sim(a["name"], b["name"])
            if api >= thr and (ns > 0 or len(a["fp"] | b["fp"]) <= 25):
                pairs.append((api, ns, a, b))
    pairs.sort(key=lambda x: (-x[0], -x[1]))
    print("候选对: %d（api>=%.2f）\n" % (len(pairs), thr))
    for api, ns, a, b in pairs[:80]:
        overlap = a["fp"] & b["fp"]
        only_a = a["fp"] - b["fp"]
        only_b = b["fp"] - a["fp"]
        print("api=%.2f name=%.2f" % (api, ns))
        print("  A %s::%s" % (a["file"], a["name"]))
        print("  B %s::%s" % (b["file"], b["name"]))
        print("  共有: %s" % ", ".join(sorted(overlap))[:200])
        print("  仅A : %s" % ", ".join(sorted(only_a))[:160])
        print("  仅B : %s" % ", ".join(sorted(only_b))[:160])
        print()


if __name__ == "__main__":
    main()
