# -*- coding: utf-8 -*-
"""恒真 / 弱断言扫描（v2.10.0 第 8 轮 · 代理 C · 任务 R4，只读）。

**为什么要有这件工具**：R4 的原文是「全仓扫一遍『永远为真的断言』」。上一轮只靠人眼在
diff 里认出了 4 条（test_dialogs_feedback_v280.py:1150 已清；test_import_thread.py:108、
test_io_v231.py:1287、test_plugin_host_v251.py:1643 登记在案），**人眼扫描不是系统性做法**：
真正恒真的那一类（X or True、assert True、a == a）在 diff 里长得和正常断言一模一样。
所以先落工具、再逐条定性 —— 工具负责「一条不漏」，人负责「这条该加强还是该删」。

**判据（结构层，不猜语义）**：
  · 恒真-T：断言式结构上恒为真（实现怎么改都会过）——
      assert True / 任何真值常量 / X or True（Or 任一侧是恒真常量）/
      a == a、a is a、a <= a、a >= a（自比较）/ assert not x 而 x 是恒假常量。
  · 恒假-F：断言式结构上恒为假（永远不会过 = 死断言，与恒真同为「假覆盖」）——
      X and False / a != a、a is not a / 恒假常量。
  · 已保证-R：断言的是同一函数里刚刚赋过的那个**不可变**字面量（任务书点名的第三种形态
      「断言前已被保证的条件」）——x = "..." 之后 assert x / assert x is not None /
      assert x == "..."。**只认不可变标量**（str/bytes/int/float/bool/None）：
      logs = [] 之后 assert logs == [] 是**捕获列表**的常规写法，被测代码完全可以通过
      别名往里追加 —— 把它算成恒真是**误报**（本工具第一版真报了 63 条这种，
      逐条看下来 63/63 都是误报，所以收紧了）。
  · 重复调用-W：自比较但两侧含函数调用 —— assert f(x) == f(x)。**不是恒真**（f 非确定性
      就会红），但它是「弱断言」：只钉住了"这个函数在同进程内可重复"，钉不住它算得对不对。
      只列不挡（--strict 不看它），留给人写清单。
  · 死块-D：落在 if False / while False 里的断言（永不执行）。
  · 构造后-R：断言前一行的构造已经保证的事 —— x = Cls(...) 之后 assert isinstance(x, Cls)；
     或 x = Cls(...)（大写开头的类名）之后 assert x is not None。

**⚠ 边界（质量审实测，写在明处，免得下一个人以为它全能）**：
本工具**只走函数体**——不下钻 `match` 的 case 体、不看模块级与类体级的断言、
不认 `len(x) >= 0` / `x in [x]` / `isinstance(x, object)` / `bool in (True, False)` /
三元表达式恒真 / `not (p and not p)` / `all([])` 这类**语义恒真但结构不显式**的写法。
质量审造了 **21 种**形态，本工具**抓 11 漏 10**；但拿同一套判据扫那 10 种写法在全仓的落点
（`len(...) >= 0` / `count(...) <= 0` 之类）→ **0 条真恒真**。
**结论：窄，但无实际漏检**——"窄而准"是有意的取舍（宽的版本第一版报 63 条、63/63 全是误报）。
将来真出现这里漏掉的形态，**先补判据、再补一条 `# EXP:` 自检样本**，别直接放宽。

**⚠ 冻结副本是预期命中**：`_dev/_compat270/base/tests/**` 是 v2.7.0 兼容审查留下的**冻结基线副本**
（"当时那份树"），里面有 3 条**故意不改**的命中。因此：
    python -B _dev/audit_tautology_asserts_v2100.py tests --strict   # 活树：期望「合计 0 条」、exit 0
    python -B _dev/audit_tautology_asserts_v2100.py . --strict       # 全仓：**列出** 3 条（全在冻结副本）
                                                                     # 但 **exit 0** —— --strict 只看活树
工具会把冻结副本的命中**单独列一段**，并且 `--strict` **只看活树**（冻结副本不计入退出码）。
⚠ **本节初稿写错过一处（v2.11.0 第 9 轮 · 代理 C 更正）**：上面第二行原写「全仓 → exit 1」，
与紧接着的「`--strict` 只看活树」**自相矛盾**；2026-10-16 实测 `python -B _dev/audit_tautology_asserts_v2100.py . --strict`
→ rc=**0**（自己打印 `--strict 只看活树的 恒真/恒假/死块：0 条`）。照初稿复跑会把**预期**读成「回归」。

用法：
    python -B _dev/audit_tautology_asserts_v2100.py                  # 扫 tests/**（默认）
    python -B _dev/audit_tautology_asserts_v2100.py tests _dev       # 指定若干根
    python -B _dev/audit_tautology_asserts_v2100.py --json out.json  # 另存机器可读结果
    python -B _dev/audit_tautology_asserts_v2100.py tests --strict    # 活树有 恒真/恒假/死块 就退出码 1

退出码：0 = 活树没有「恒真/恒假/死块」（冻结副本不计）；1 = --strict 且活树有条目；2 = 用法错误。

**原始读数不入库**：`--json` 的输出落在 `_dev/` 下，被 `.gitignore` 的 `_dev/*` 覆盖
（本仓口径：探针的原始逐轮数据复跑即得）——**复跑一条命令就能重建**，本文档里的数字都是这样来的。
"""
import ast
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 冻结的对照基线副本（v2.7.0 兼容审查的"当时那份树"）：里面的命中**故意不改**，
# 单独列出、**不计入 --strict 的退出码**——换句话说：**若不把冻结副本排除在退出码之外**，
# 全仓跑 --strict 才会 exit=1（实测是 rc=0，见上面 docstring 里那段更正）；
# 照"全仓会 exit=1"那句初稿复跑，会把**预期**读成"回归了"。
FROZEN_PREFIXES = ("_dev/_compat270/base/",)

TAUTOLOGY = "恒真-T"
ALWAYS_FALSE = "恒假-F"
REDUNDANT = "已保证-R"
WEAK = "重复调用-W"
CTOR = "构造后-R"
DEAD = "死块-D"

TRUE_OPS = (ast.Eq, ast.Is, ast.LtE, ast.GtE, ast.In)
FALSE_OPS = (ast.NotEq, ast.IsNot, ast.Lt, ast.Gt, ast.NotIn)


def _const(node):
    """字面量常量节点 → 值；其它（含 None 本身）一律「未知」。"""
    if isinstance(node, ast.Constant) and node.value is not None:
        return node.value
    if isinstance(node, ast.Constant):
        return node.value
    return None


def _is_truthy_const(node):
    """结构上是「恒真常量表达式」：True / 非零数 / 非空字符串 / 非空字面量容器。"""
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, bool):
            return v is True
        if isinstance(v, (int, float)):
            return v != 0
        if isinstance(v, (str, bytes)):
            return len(v) > 0
        return False
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return len(node.elts) > 0
    if isinstance(node, ast.Dict):
        return len(node.keys) > 0
    return False


def _is_falsy_const(node):
    """结构上是「恒假常量表达式」：False / 0 / 空串 / 空字面量容器 / None。"""
    if isinstance(node, ast.Constant):
        v = node.value
        if v is None:
            return True
        if isinstance(v, bool):
            return v is False
        if isinstance(v, (int, float)):
            return v == 0
        if isinstance(v, (str, bytes)):
            return len(v) == 0
        return False
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return len(node.elts) == 0
    if isinstance(node, ast.Dict):
        return len(node.keys) == 0
    return False


def _dump(node):
    return ast.dump(node, annotate_fields=False)


def classify_test(node):
    """断言式本身 → 判定码；"ok" = 看不出结构性恒真/恒假。"""
    if _is_truthy_const(node):
        return TAUTOLOGY
    if _is_falsy_const(node):
        return ALWAYS_FALSE
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.Or) and any(_is_truthy_const(v) for v in node.values):
            return TAUTOLOGY
        if isinstance(node.op, ast.And) and any(_is_falsy_const(v) for v in node.values):
            return ALWAYS_FALSE
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        if _is_falsy_const(node.operand):
            return TAUTOLOGY
        if _is_truthy_const(node.operand):
            return ALWAYS_FALSE
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        if _dump(node.left) == _dump(node.comparators[0]):
            weak = _has_call(node.left) or _has_call(node.comparators[0])
            if isinstance(node.ops[0], TRUE_OPS):
                return WEAK if weak else TAUTOLOGY
            if isinstance(node.ops[0], FALSE_OPS):
                return WEAK if weak else ALWAYS_FALSE
    return "ok"


def _is_none(node):
    return isinstance(node, ast.Constant) and node.value is None


def _has_call(node):
    """自比较两侧含不含函数调用 —— 含调用就"可能非确定"，不能算结构性恒真。"""
    return any(isinstance(n, ast.Call) for n in ast.walk(node))


def _is_ctor_call(node):
    """x = Cls(...) —— 大写开头的名字当类，构造出来的东西不可能是 None。"""
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id[:1].isupper())


def _is_immutable_const(node):
    """能记成「已知不可变常量」的右值 —— **只认标量**。

    可变容器（x = [] / {} / set() / list()）**故意不算**：捕获列表是常规写法，被测代码可以
    通过别名往里追加，"x 此刻还是空的"不是结构事实。第一版把它们算进来 → 63 条全是误报。
    """
    if isinstance(node, ast.Constant):
        return not isinstance(node.value, (list, dict, set, bytearray))
    return False


def _const_of(node, consts):
    if isinstance(node, ast.Name) and node.id in consts:
        return consts[node.id]
    return node


def _redundant(test, consts, ctors):
    """「断言前已被保证」——字面量常量名，或刚构造出来的对象。"""
    if isinstance(test, ast.Compare) and len(test.ops) == 1 and \
            isinstance(test.left, ast.Name) and test.left.id in ctors:
        if isinstance(test.ops[0], ast.IsNot) and _is_none(test.comparators[0]):
            return CTOR          # x = Cls(...) 之后 x is not None 必真（构造不可能返回 None）
    if isinstance(test, ast.Call) and isinstance(test.func, ast.Name) and \
            test.func.id == "isinstance" and len(test.args) == 2 and \
            isinstance(test.args[0], ast.Name) and test.args[0].id in ctors and \
            isinstance(test.args[1], ast.Name) and test.args[1].id == ctors[test.args[0].id]:
        return CTOR
    if isinstance(test, ast.Name) and test.id in consts and _is_truthy_const(consts[test.id]):
        return REDUNDANT
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        inner = _const_of(test.operand, consts)
        if not isinstance(inner, ast.Name) and _is_falsy_const(inner):
            return REDUNDANT
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        left = _const_of(test.left, consts)
        right = _const_of(test.comparators[0], consts)
        if not isinstance(left, ast.Name) and _dump(left) == _dump(right):
            if isinstance(test.ops[0], TRUE_OPS):
                return REDUNDANT
            if isinstance(test.ops[0], FALSE_OPS):
                return ALWAYS_FALSE
        if isinstance(test.left, ast.Name) and test.left.id in consts and \
                _dump(consts[test.left.id]) == _dump(test.comparators[0]):
            if isinstance(test.ops[0], (ast.Eq, ast.Is)):
                return REDUNDANT
            if isinstance(test.ops[0], ast.IsNot):
                return ALWAYS_FALSE
        if isinstance(test.left, ast.Name) and test.left.id in consts and \
                _is_none(test.comparators[0]):
            if isinstance(test.ops[0], ast.IsNot):
                return REDUNDANT     # s = "abc" 之后 assert s is not None
            if isinstance(test.ops[0], ast.Is):
                return ALWAYS_FALSE
    return "ok"


def _walk_body(body, dead, out, func_name, consts, ctors):
    """前向走一遍语句表；consts = Name → 字面量节点，ctors = Name → 构造用的类名。"""
    for stmt in body:
        if isinstance(stmt, ast.Assert):
            code = classify_test(stmt.test)
            if code == "ok" and (consts or ctors):
                code = _redundant(stmt.test, consts, ctors)
            if dead:
                code = DEAD        # 死块里的断言先按"永不执行"算，再看它本身恒不恒真
            if code != "ok":
                out.append((stmt.lineno, code, func_name, _text(stmt)))
            continue
        if isinstance(stmt, (ast.If, ast.While)):
            inner_dead = dead or _is_falsy_const(stmt.test)
            _walk_body(stmt.body, inner_dead, out, func_name, dict(consts), dict(ctors))
            _walk_body(stmt.orelse, dead, out, func_name, dict(consts), dict(ctors))
            continue
        if isinstance(stmt, ast.Try):
            _walk_body(stmt.body, dead, out, func_name, dict(consts), dict(ctors))
            for h in stmt.handlers:
                _walk_body(h.body, dead, out, func_name, dict(consts), dict(ctors))
            _walk_body(stmt.orelse, dead, out, func_name, dict(consts), dict(ctors))
            _walk_body(stmt.finalbody, dead, out, func_name, dict(consts), dict(ctors))
            continue
        if isinstance(stmt, (ast.For, ast.AsyncFor)):
            _walk_body(stmt.body, dead, out, func_name, dict(consts), dict(ctors))
            _walk_body(stmt.orelse, dead, out, func_name, dict(consts), dict(ctors))
            continue
        if isinstance(stmt, (ast.With, ast.AsyncWith)):
            _walk_body(stmt.body, dead, out, func_name, dict(consts), dict(ctors))
            continue
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue        # 嵌套定义由 scan_source 的 ast.walk 单独覆盖
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and \
                isinstance(stmt.targets[0], ast.Name):
            name = stmt.targets[0].id
            consts.pop(name, None)
            ctors.pop(name, None)
            if _is_immutable_const(stmt.value):
                consts[name] = stmt.value
            elif _is_ctor_call(stmt.value):
                ctors[name] = stmt.value.func.id
            continue
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            consts.pop(stmt.target.id, None)
            ctors.pop(stmt.target.id, None)
            if _is_immutable_const(stmt.value) if stmt.value is not None else False:
                consts[stmt.target.id] = stmt.value
            elif stmt.value is not None and _is_ctor_call(stmt.value):
                ctors[stmt.target.id] = stmt.value.func.id
            continue
        if isinstance(stmt, ast.AugAssign) and isinstance(stmt.target, ast.Name):
            consts.pop(stmt.target.id, None)
            ctors.pop(stmt.target.id, None)
            continue
        for tgt in getattr(stmt, "targets", []) or []:
            if isinstance(tgt, ast.Name):
                consts.pop(tgt.id, None)
                ctors.pop(tgt.id, None)
    return consts


def _text(stmt):
    try:
        return ast.unparse(stmt)
    except Exception:
        return "assert <unparse 失败>"


def scan_source(src, filename):
    """一个文件的全部命中 → [(lineno, code, func, text)]。"""
    tree = ast.parse(src, filename=filename)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _walk_body(node.body, False, out, node.name, {}, {})
    out.sort(key=lambda r: r[0])
    return out


def iter_files(roots):
    for root in roots:
        p = root if os.path.isabs(root) else os.path.join(ROOT, root)
        if os.path.isfile(p):
            yield p
            continue
        for dirpath, dirnames, filenames in os.walk(p):
            dirnames[:] = [d for d in dirnames
                           if d not in ("__pycache__", ".git", ".pytest_cache", "build", "dist",
                                        "大肥鱼桌宠_绿色版")]
            for fn in sorted(filenames):
                if fn.endswith(".py"):
                    yield os.path.join(dirpath, fn)


def main(argv):
    as_json = None
    if "--json" in argv:
        i = argv.index("--json")
        as_json = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    roots = [a for a in argv if not a.startswith("-")]
    strict = "--strict" in argv
    if not roots:
        roots = ["tests"]
    hits = []
    scanned = 0
    for path in iter_files(roots):
        try:
            src = io.open(path, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            continue
        scanned += 1
        for lineno, code, func, text in scan_source(src, path):
            rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
            hits.append({"file": rel, "line": lineno, "code": code, "func": func, "text": text,
                         "frozen": rel.startswith(FROZEN_PREFIXES)})
    order = {TAUTOLOGY: 0, ALWAYS_FALSE: 1, DEAD: 2, REDUNDANT: 3, WEAK: 4, CTOR: 5}
    hits.sort(key=lambda h: (h["frozen"], order.get(h["code"], 9), h["file"], h["line"]))
    live = [h for h in hits if not h["frozen"]]
    frozen = [h for h in hits if h["frozen"]]
    print("扫描 %d 个 .py（根：%s）" % (scanned, ", ".join(roots)))
    for h in live:
        print("%-8s %s:%d  [%s]  %s" % (h["code"], h["file"], h["line"], h["func"], h["text"]))
    if frozen:
        print("")
        print("—— 冻结基线副本（%s）：**预期命中，故意不改**，不计入 --strict ——" % (FROZEN_PREFIXES[0],))
        for h in frozen:
            print("%-8s %s:%d  [%s]  %s" % (h["code"], h["file"], h["line"], h["func"], h["text"]))

    def _counts(rows):
        c = {}
        for h in rows:
            c[h["code"]] = c.get(h["code"], 0) + 1
        return c

    counts = _counts(live)
    summary = " · ".join("%s %d" % (k, counts[k])
                         for k in (TAUTOLOGY, ALWAYS_FALSE, DEAD, REDUNDANT, WEAK, CTOR)
                         if k in counts) or "无"
    print("")
    print("活树合计 %d 条：%s" % (len(live), summary))
    if frozen:
        fsum = " · ".join("%s %d" % (k, v) for k, v in sorted(_counts(frozen).items()))
        print("冻结副本另计 %d 条（%s）——不是回归，复跑期望就是这些" % (len(frozen), fsum))
    blocking = [h for h in live if h["code"] in (TAUTOLOGY, ALWAYS_FALSE, DEAD)]
    print("--strict 只看活树的 恒真/恒假/死块：%d 条" % len(blocking))
    if as_json:
        with io.open(as_json, "w", encoding="utf-8", newline="") as f:
            json.dump({"roots": roots, "scanned": scanned, "counts": counts,
                       "frozen_counts": _counts(frozen), "hits": hits},
                      f, ensure_ascii=False, indent=2)
            f.write(chr(10))
        print("JSON → %s" % as_json)
    if strict and blocking:
        return 1
    return 0


_SELFTEST = '''# -*- coding: utf-8 -*-
def f_t(x):
    assert x or True                    # EXP:恒真-T
    assert True                         # EXP:恒真-T
    assert x == x                       # EXP:恒真-T


def f_f(x):
    assert x and False                  # EXP:恒假-F
    assert x != x                       # EXP:恒假-F


def f_r(x):
    s = "abc"
    assert s                            # EXP:已保证-R
    assert s is not None                # EXP:已保证-R
    assert s == "abc"                   # EXP:已保证-R


def f_c():
    d = Foo(1)
    assert d is not None                # EXP:构造后-R
    assert isinstance(d, Foo)           # EXP:构造后-R


def f_w():
    assert f_w() == f_w()               # EXP:重复调用-W


def f_d(x):
    if False:
        assert x                        # EXP:死块-D


def f_ok(x):
    logs = []
    assert logs == []                   # NOT：捕获列表可以被测代码通过别名追加
    d = Foo()
    assert d.value == 1                 # NOT：构造函数的返回值没被断言
    assert x > 0                        # NOT
    assert isinstance(x, int)           # NOT：x 不是这一函数里构造出来的
    s = "abc"
    assert "b" in s                     # NOT：常量名只用于整值断言，不做子串推断
'''


def _selftest():
    """工具自己的「能真失败」自检：样本里每行用 # EXP:<判定码> 标出期望，# NOT 标反例。

    期望**从样本自己解析出来**（不手抄行号）——手抄行号这件事本轮刚被 check_mutation_nodeids.py
    教训过（「照抄一遍」本身就是风险点）。
    没有这一步，「扫描 0 条」与「扫描器坏了」长得一模一样。
    """
    want = {}
    for i, line in enumerate(_SELFTEST.splitlines(), start=1):
        if "# EXP:" in line:
            want[i] = line.split("# EXP:", 1)[1].strip()
        elif "# NOT" in line:
            want[i] = None
    got = {lineno: code for lineno, code, _f, _t in scan_source(_SELFTEST, "<selftest>")}
    bad = 0
    for lineno, code in sorted(want.items()):
        if got.get(lineno) != code:
            print("第 %d 行：期望 %r，实得 %r" % (lineno, code, got.get(lineno)))
            bad = 1
    for lineno in sorted(got):
        if lineno not in want:
            print("第 %d 行：多报 %s（样本里没标 EXP）" % (lineno, got[lineno]))
            bad = 1
    if bad:
        print("自检失败：判定码与样本标记不一致")
    else:
        n_exp = len([v for v in want.values() if v])
        print("自检通过：%d 条命中逐条对上标记，%d 条反例未报" %
              (n_exp, len([v for v in want.values() if not v])))
    return bad




if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
