# -*- coding: utf-8 -*-
"""定位"语义重复"用例（v3）：比较**断言内容的形态**，根对象名忽略、常量保留。

两个用例如果对同一个东西做了同一条断言（只是变量名/文件不同），它们的"断言形态"会相同。
形态里忽略的是属性链的根对象名（svc/pet_voice/mod…），保留属性名与常量——所以
  assert pet_voice.VOICE_EVENTS == pet_behaviors.BEHAVIOR_VOICE_EVENTS
  assert voice.VOICE_EVENTS == behaviors.BEHAVIOR_VOICE_EVENTS
会被判成同一条断言。

用法: python _dev/find_dup_claims.py [最短形态长度, 默认 30] [最少共有条数, 默认 1]
只读。
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")


def shape(node):
    if isinstance(node, ast.Attribute):
        return ("attr", shape(node.value), node.attr)
    if isinstance(node, ast.Name):
        return ("root",)
    if isinstance(node, ast.Constant):
        return ("const", repr(node.value))
    if isinstance(node, ast.Call):
        return ("call", shape(node.func), tuple(shape(a) for a in node.args),
                tuple((k.arg, shape(k.value)) for k in node.keywords))
    if isinstance(node, ast.Subscript):
        return ("sub", shape(node.value), shape(node.slice))
    if isinstance(node, ast.Compare):
        return ("cmp", shape(node.left), tuple(type(o).__name__ for o in node.ops),
                tuple(shape(c) for c in node.comparators))
    if isinstance(node, ast.BoolOp):
        return ("bool", type(node.op).__name__, tuple(shape(v) for v in node.values))
    if isinstance(node, ast.UnaryOp):
        return ("unary", type(node.op).__name__, shape(node.operand))
    if isinstance(node, (ast.Tuple, ast.List)):
        return ("seq", tuple(shape(e) for e in node.elts))
    if isinstance(node, ast.Dict):
        return ("dict", tuple(shape(k) for k in node.keys),
                tuple(shape(v) for v in node.values))
    if isinstance(node, ast.IfExp):
        return ("ifexp", shape(node.test), shape(node.body), shape(node.orelse))
    return (type(node).__name__,)


def collect():
    out = []
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
            claims = []
            for n in ast.walk(node):
                if isinstance(n, ast.Assert):
                    claims.append(repr(shape(n.test)))
            out.append({"file": fn, "name": name, "claims": claims,
                        "set": set(claims)})
    return out


def main():
    min_len = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    min_common = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    items = collect()
    pairs = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            if a["file"] == b["file"] and a["name"] == b["name"]:
                continue
            common = {c for c in (a["set"] & b["set"]) if len(c) >= min_len}
            if len(common) >= min_common:
                pairs.append((len(common), a, b, sorted(common)[:4]))
    pairs.sort(key=lambda x: -x[0])
    print("共有断言的用例对: %d\n" % len(pairs))
    for n, a, b, ex in pairs[:50]:
        print("共有 %d 条  |  %s::%s  <->  %s::%s" % (n, a["file"], a["name"], b["file"], b["name"]))
        for e in ex:
            print("      %s" % e[:150])
        print()


if __name__ == "__main__":
    main()
