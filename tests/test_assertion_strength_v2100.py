# -*- coding: utf-8 -*-
"""断言强度守卫（v2.10.0 第 8 轮 · 代理 C · 任务 R4）：tests/** 里不许再有"恒真/恒假/死块"断言。

**为什么要有这条守卫**：R4 的定性是"**恒真断言也是假覆盖的一种**"——assert x or True、
assert True、assert a == a 在 diff 里和正常断言长得一模一样，永远不会红，
**而"永远不会红"和"跑过了"在读结果时没有区别**。上一轮靠人眼在 diff 里认出 4 条
（test_dialogs_feedback_v280.py:1150 清掉了，另三条登记在案），本轮一次性清掉：
test_import_thread.py:108（真·恒真）· test_io_v231.py:1287 与
test_plugin_host_v251.py:1643（自比较里含真函数调用的"重复调用"弱断言）·
test_dialogs_more_v24.py:880（and/or 优先级写错，等价于"0 或 1 在里面"，两条路都放行）。

守卫 = 把 _dev/audit_tautology_asserts_v2100.py 扫一遍 tests/，出现 恒真-T / 恒假-F / 死块-D
就红。它**不拦"重复调用-W"**（assert f(x) == f(x) 不是恒真，只是弱；误报率太高，只列不挡）。

能真失败：把任意一条断言改回 ... or True（或往 tests/ 里加一行 assert True）→ 第二条红；
把扫描器的自检样本改坏 → 第一条红。
"""
import ast
import importlib.util
import io
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEV = os.path.join(HERE, "_dev")
TESTS = os.path.join(HERE, "tests")


def _load(name, path):
    """按路径加载 _dev 下的脚本（与 test_mutate_harness_v244 / test_silent_except_audit_v241 同法）。"""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


audit = _load("audit_tautology_v2100", os.path.join(DEV, "audit_tautology_asserts_v2100.py"))

BAD = (audit.TAUTOLOGY, audit.ALWAYS_FALSE, audit.DEAD)


def test_scanner_selftest_passes():
    """扫描器自己的"能真失败"自检：样本里每类各一条 + 5 条反例，逐条对上才算数。

    没有这一步，"扫描 0 条"与"扫描器坏了"长得一模一样——所以它是本文件的第一条。
    """
    assert audit._selftest() == 0


def test_no_tautological_asserts_in_the_test_suite():
    """tests/** 全扫：恒真（X or True / assert True / a == a）、恒假（and False）、死块（if False 里）。"""
    hits = []
    scanned = 0
    for path in audit.iter_files([TESTS]):
        try:
            src = io.open(path, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            continue
        scanned += 1
        for lineno, code, func, text in audit.scan_source(src, path):
            if code in BAD:
                hits.append("%s:%d [%s] %s  —— %s"
                            % (os.path.relpath(path, HERE).replace(os.sep, "/"),
                               lineno, code, func, text.strip()))
    assert scanned > 50, "只扫到 %d 个文件（路径不对？守卫会变成空转）" % scanned
    assert hits == [], (
        "发现恒真/恒假/死块断言（永远不会红 = 这条检查等于没做）：\n  " + "\n  ".join(hits) +
        "\n（工具：python -B _dev/audit_tautology_asserts_v2100.py；口径见该文件 docstring）")


def _norm_expr(text):
    """断言表达式归一：去掉空白与引号（ast.unparse 一律用单引号，人写的是双引号）。"""
    return "".join(ch for ch in text if not ch.isspace() and ch not in "'\"")


def _assert_exprs(path):
    """文件里**所有 assert 的表达式**（AST 层；注释与 docstring 一律不算）。

    为什么不用文本匹配：本轮在旧断言上方留了"原来是 X"的说明（注释与 docstring 里都写过），
    文本匹配会把**给人读的说明**当成"又改回去了"——这条守卫第一次跑就是被自己的说明误报拦下的。
    守卫要盯的是**可执行的断言表达式**，那就去 AST 拿。
    """
    tree = ast.parse(io.open(path, encoding="utf-8").read())
    return {_norm_expr(ast.unparse(n.test)) for n in ast.walk(tree) if isinstance(n, ast.Assert)}


def test_the_four_assertions_cleaned_this_round_are_really_gone():
    """点名复核本轮清掉的四条——扫描器是通用判据，这里是"这四处确实不再是那个写法"的钉子。

    能真失败：把任一处改回旧写法（例如 test_import_thread 里那句 or True）→ 红。
    """
    checks = [
        ("test_import_thread.py", "not dlg._ok.isEnabled() or True", "dlg._ok.isEnabled()"),
        ("test_io_v231.py", "pet_io.path_lock(p) is pet_io.path_lock(p)",
         'pet_io.path_lock(os.path.join(str(tmp_path), ".", "X.json")) is lock'),
        ("test_plugin_host_v251.py",
         'pet_plugin_host._fp_named("\u7532.txt", same) == pet_plugin_host._fp_named("\u7532.txt", same)',
         'pet_plugin_host._fp_named("\u7532.txt", same) == hashlib.sha256('
         '"\u7532.txt".encode("utf-8") + b"\\x00" + same).hexdigest()'),
        ("test_dialogs_more_v24.py",
         "0 in dlg._touched_flags and 1 not in dlg._touched_flags or 1 in dlg._touched_flags",
         "dlg._touched_flags == {1}"),
    ]
    for fname, old, new in checks:
        exprs = _assert_exprs(os.path.join(TESTS, fname))
        assert _norm_expr(old) not in exprs, "%s 里那句旧断言又回来了：%r" % (fname, old)
        assert _norm_expr(new) in exprs, \
            "%s 里加强后的断言不见了（被改回去了？）：%r\n实得断言：%r" % (fname, new, sorted(exprs))
