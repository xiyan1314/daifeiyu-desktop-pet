# -*- coding: utf-8 -*-
"""变异 spec 的 **nodeid 体检**（v2.9.0 第 7 轮 · 代理 C）——与 `mutate_batch_v270.py --scan-only` 并列的定版前必跑项。

**为什么要有它（本轮实测的新失败模式）**：改用例名是常规操作（本轮 A10 就是把
`test_static_input_dialogs_are_gone_except_the_frame_action_one` 改名为
`test_static_input_dialogs_are_gone`，而且是**加强式**改写），但 spec 里的 nodeid 不会跟着动 ——
于是 `MA11` 与 `M-C-A22` 指向了**不存在的用例**：pytest 报 node-not-found，
**那两条变异永远判不成 CAUGHT**，而这件事**只有在定版整批跑时才暴露成 WRONG TEST**（白烧一整批）。
锚点一直有 `--scan-only` 体检（命中次数必须恰好 1），**nodeid 在此之前一条体检都没有**——这是清单完整性的另一面。

判据：
  * `tests/x.py::test_y`：文件存在 **且** 文件里真的定义了 `test_y`（含类方法 `TestX::test_y`、参数化 `test_y[参数]`）；
  * 只给文件（`tests/x.py`，旧形态驱动）：文件存在即可（pytest 收整个文件）；
  * 不给文件（老 spec 里的裸用例名）：在**这份 spec 引用过的测试文件**里找得到就算过；
  * `expect_fail` 与 `tests` 两份都查（前者判定要用，缺了会永远判 WRONG TEST）。

**校验范围（v2.9.0 三审 F-6 更正措辞）**：**只查 `mutations[].tests` / `mutations[].expect_fail`** ——
这两份才是**判定真正会用到**的 nodeid。**不查** spec 顶层 `evidence.tests`、`results.tests` /
`results.items[].failed` 这些**历史记录**：它们记的是「当时跑出什么」，保留当时的用例名（哪怕后来改名了）
**本来就是对的**，改它们反而是篡改历史。所以本工具的输出**不许**说「全库 nodeid 都对得上」，
只能说「**校验范围内**对得上」；范围外还有多少条，工具会**一并报出来**（免得读的人以为漏了）。

只读、秒级、不跑 pytest、不摸产品代码。
用法：
    python -B _dev/check_mutation_nodeids.py              # 自动收全 _dev/mutations_*.json
    python -B _dev/check_mutation_nodeids.py <spec.json>  # 只查指定 spec
退出码：0 = 全对得上；1 = 有 nodeid 对不上（定版前必须修）；2 = 脚本自身出错。
"""
import ast
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def spec_paths(argv):
    if argv:
        return [a if os.path.isabs(a) else os.path.join(ROOT, a) for a in argv]
    out = []
    for name in sorted(os.listdir(HERE)):
        if name.startswith("mutations_") and name.endswith(".json"):
            out.append(os.path.join(HERE, name))
    return out


_DEF_CACHE = {}


def defined_names(rel):
    """tests/x.py 里定义的所有用例名（顶层函数 + 类方法，形如 `方法名`）。"""
    if rel in _DEF_CACHE:
        return _DEF_CACHE[rel]
    path = os.path.join(ROOT, rel.replace("/", os.sep))
    names = set()
    try:
        with io.open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
    except Exception:
        _DEF_CACHE[rel] = None
        return None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
    _DEF_CACHE[rel] = names
    return names


def _strip_params(name):
    return name.split("[", 1)[0]


def check_node(node, spec_files):
    """(ok, 原因)。spec_files = 这份 spec 引用过的测试文件集合（给裸用例名兜底）。"""
    raw = str(node or "").strip()
    if not raw:
        return False, "空 nodeid"
    if "::" not in raw:
        if raw.endswith(".py"):
            p = os.path.join(ROOT, raw.replace("/", os.sep))
            return (True, "") if os.path.isfile(p) else (False, "测试文件不存在：%s" % raw)
        # 裸用例名：在这份 spec 引用过的文件里找
        want = _strip_params(raw.split(".")[-1])
        for rel in sorted(spec_files):
            names = defined_names(rel)
            if names and want in names:
                return True, ""
        return False, "裸用例名在这份 spec 引用的测试文件里找不到：%s" % raw
    rel, func = raw.split("::", 1)
    names = defined_names(rel)
    if names is None:
        return False, "测试文件不存在/读不动：%s" % rel
    want = _strip_params(func.split("::")[-1])
    if want in names:
        return True, ""
    return False, "用例不存在：%s（文件在，但没有这个 def —— 多半是改用例名了）" % raw


def _count_history(data):
    """范围外（历史记录）里长得像 nodeid 的字符串条数：**只统计、不判定**。

    顶层 `evidence.tests` / `results.tests` / `results.items[].failed` 是「当时跑出什么」的账，
    保留当时的用例名是对的（三审 F-6）；这里把它们数出来写进结论，免得读的人以为漏检。
    """
    n = 0
    srcs = []
    ev = data.get("evidence")
    if isinstance(ev, dict):
        srcs.append(ev.get("tests"))
    top = data.get("tests")
    if top is not None:
        srcs.append(top)
    res = data.get("results")
    if isinstance(res, dict):
        srcs.append(res.get("tests"))
        for it in (res.get("items") or []):
            if isinstance(it, dict):
                srcs.append(it.get("failed"))
    for s in srcs:
        if isinstance(s, list):
            n += len([x for x in s if isinstance(x, str) and "::" in x])
        elif isinstance(s, str) and "::" in s:
            n += 1
    return n


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    paths = spec_paths(sys.argv[1:])
    if not paths:
        print("没找到 _dev/mutations_*.json")
        return 2
    total = bad = 0
    hist = 0            # 范围外（历史记录）里像 nodeid 的条数：只统计、不判定
    for path in paths:
        try:
            with io.open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as e:
            print("%-40s 读不出来：%r" % (os.path.basename(path), e))
            bad += 1
            continue
        muts = data.get("mutations") or []
        hist += _count_history(data)
        spec_files = set()
        for m in muts:
            for t in (m.get("tests") or []):
                t = str(t)
                # 带 "::" 的记文件；只给文件的旧形态（MF4 那种）也要记进来 ——
                # 裸用例名要在这份 spec 引用过的文件里找，漏了它就会误报
                spec_files.add(t.split("::")[0] if "::" in t else t)
        rows = []
        for m in muts:
            for key in ("tests", "expect_fail"):
                for node in (m.get(key) or []):
                    total += 1
                    ok, why = check_node(node, spec_files)
                    if not ok:
                        bad += 1
                        rows.append((m.get("id") or "?", key, why))
        print("%-40s nodeid %3d 个，坏 %d%s" % (
            os.path.basename(path), sum(len(m.get("tests") or []) + len(m.get("expect_fail") or [])
                                        for m in muts), len(rows),
            "" if not rows else "  → " + "；".join("%s[%s] %s" % (i, k, w) for i, k, w in rows)))
    print("")
    print("校验范围：mutations[].tests / mutations[].expect_fail —— 合计 %d 条，坏 %d 条" % (total, bad))
    print("（坏 = spec 点名的用例在当前树里不存在：改用例名/搬家 → 这条变异**静默失效**，"
          "定版整批跑时才会暴露成 WRONG TEST）")
    print("范围外（**只统计、不判定**）：顶层 evidence.tests / results.tests / results.items[].failed "
          "等历史记录里还有 %d 条 nodeid —— 它们记的是「当时跑出什么」，保留当时的用例名是对的"
          "（v2.9.0 三审 F-6），本工具刻意不查、也**不该改**。" % hist)
    if not bad:
        print("**校验范围内** nodeid 全部对得上 —— 可以进整批复跑（范围外那些历史记录不参与判定）。")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
