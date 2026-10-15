# -*- coding: utf-8 -*-
"""v2.8.0 第 7 轮：_check_static 的 N 检查（未定义全局名）回归。

为什么单开一个文件：这条检查守的是"**用了没 import / 没定义的名字**"。v2.8.0 找茬审查的
F1（pet_dialogs 的 import 行里少一个 QTimer，两处"在途期间排队补发"一跑就 NameError、
PySide6 只往 stderr 打一行 traceback、绿色版 pythonw 没有控制台 → 用户点了没反应）就是
这样穿过原 10 类检查的：A 检查只认 `pet_dialogs.X` / `pet.X` 的**属性形状**，名字本身
没导入它一个字都看不到。

口径与 _check_static.py 里 N 段的注释逐条对应：
  · 真漏必报：合成源码里的未定义名 + **真仓 pet_dialogs 去掉 QTimer 的那份快照**；
  · 正例不报：内置 / 形参 / 局部 / 闭包 / 推导式目标 / 类体 / for-with-except 绑定 /
    try 兜底导入 / 注解 / match 捕获 / lambda …（0 误报是硬要求）；
  · 真仓现状：N 检查对当前全部 .py 报 **0 条**（静态体检 0/0 的一部分）。
"""
import ast
import io
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _check_static as C  # noqa: E402

QTIMER_IMPORT_OLD = ("from PySide6.QtCore import QEventLoop, QTime, QTimer, "
                     "Qt, QThread, QUrl, Signal")
QTIMER_IMPORT_NEW = ("from PySide6.QtCore import QEventLoop, QTime, "
                     "Qt, QThread, QUrl, Signal")


def _problems(code, name="v280_undef_sample.py"):
    """一段源码 → N 检查报出的问题（只走这一类检查，不受其它检查影响）。"""
    return C.check_undefined_names([(name, code)])[0]


def _pet_dialogs_source():
    path = os.path.join(C.ROOT, "pet_dialogs.py")
    return io.open(path, encoding="utf-8").read()


# ==================== 一、真漏必报 ====================

def test_undefined_global_is_reported():
    """用了没导入的名字 → 必须报（QTimer 那类缺陷的最小复现）。"""
    problems = _problems(
        """def go():
    return QTimer.singleShot(0, None, None)
""")
    assert problems, "未定义全局名一个都没报（这条检查等于没接线）"
    assert any("QTimer" in p for p in problems), problems
    assert any("v280_undef_sample.py" in p for p in problems), problems


def test_the_check_catches_the_v280_qtimer_defect():
    """F1 的原样复现：把 pet_dialogs 的 QTimer 从 import 行里拿掉 → 必须报出来。

    只在**内存里**改这份源码文本（不碰盘、不进影子副本）：这里问的是"这条检查抓不抓得住
    真缺陷"，也就是它作为系统性防线的资格。
    """
    raw = _pet_dialogs_source()
    assert QTIMER_IMPORT_OLD in raw, (
        "用例前提失效：pet_dialogs 的 QtCore import 行不是预期的那一行（锚点被改过？）")
    problems, _notes = C.check_undefined_names(
        [("pet_dialogs.py", raw.replace(QTIMER_IMPORT_OLD, QTIMER_IMPORT_NEW))])
    assert any("QTimer" in p for p in problems), (
        "把 QTimer 从 import 里拿掉之后 N 检查一条都没报：%r" % (problems[:5],))
    # 对照：真仓现在这一份（带 QTimer）→ 0 条（不是"见名字就报"）
    assert _problems(raw, "pet_dialogs.py") == []


def test_star_import_module_is_skipped_with_a_note():
    """`from x import *` 的模块整份跳过（名字从哪来静态判不了）——但要在"待确认"里说一声。"""
    problems, notes = C.check_undefined_names([("v280_star.py", """from os import *


def f():
    return totally_unknown_name
""")])
    assert problems == [], "有 import * 还硬报（必然误报）：%r" % (problems,)
    assert any("import *" in n for n in notes), notes


# ==================== 二、正例不报（0 误报是硬要求） ====================

OK_SAMPLES = (
    ("内置名与内建异常", """def f(xs):
    try:
        return len(xs) + int("1")
    except (ValueError, OSError):
        raise RuntimeError("x")
"""),
    ("形参 / 局部变量 / 闭包", """def outer(v):
    def inner():
        return v
    return inner
"""),
    ("推导式目标与海象", """def f(xs):
    if (n := len(xs)) > 0:
        return [x for x in xs if x]
    return n
"""),
    ("for / with-as / except-as", """def f(p):
    with open(p) as fh:
        for ln in fh:
            try:
                pass
            except OSError as e:
                return e
    return None
"""),
    ("模块级 import / 赋值 / 函数", """import os

CACHE = {}


def put(k):
    CACHE[k] = os.sep
"""),
    ("try 兜底导入", """try:
    import json as J
except ImportError:
    J = None


def f():
    return J
"""),
    ("类体里用同一类体的名字", """class A:
    W = 2
    H = W + 1
"""),
    ("方法看得到模块级同名（类体不遮模块级）", """T = 5


class A:
    T = 10

    def m(self):
        return T
"""),
    ("方法看得到外层函数局部（闭包）", """def make():
    v = 1

    class A:
        def m(self):
            return v
    return A
"""),
    ("装饰器 / 默认值 / 注解", """from typing import List


def deco(fn):
    return fn


@deco
def f(a: List[int], b=deco) -> int:
    return 0
"""),
    ("lambda 形参", """def f(xs):
    return sorted(xs, key=lambda v: v[0])
"""),
    ("global 声明过的名字", """_C = None


def init():
    global _C
    _C = 1


def use():
    return _C
"""),
    ("match 捕获", """def f(x):
    match x:
        case {"a": v}:
            return v
        case [first, *rest]:
            return first, rest
        case other:
            return other
"""),
    ("模块 dunder", """_HERE = __file__
"""),
)


@pytest.mark.parametrize("label,code", OK_SAMPLES)
def test_defined_names_are_not_reported(label, code):
    """每一条都是**合法**写法：报出来就是误报（N 检查宁可漏检也不许误报满地）。"""
    got = _problems(code)
    assert got == [], "%s 被误报：%r" % (label, got)


def test_class_scope_is_not_visible_inside_methods():
    """反向对照：类体里的名字在方法里**真的看不到**（Python 的作用域规则），这个要报。"""
    got = _problems(
        """class A:
    B = 2

    def m(self):
        return B
""")
    assert any("B" in p for p in got), got


# ==================== 三、真仓现状 ====================

def test_real_repo_has_no_undefined_globals():
    """真仓当前 0 条（与 `python -B _check_static.py` 的 0/0 一致）。

    红了先看是不是**真漏**（那就是这次要抓的东西）；确认是误报的话，修 N 检查或按
    _check_static.py 里写的口径把盲区显式列出来——不许用放宽判据的方式让它变绿。
    """
    problems, _notes = C.check_undefined_names(C.sources())
    assert problems == [], "N 检查对真仓报出未定义全局名：%r" % (problems[:5],)

def test_main_wires_the_undefined_name_check():
    """静态体检的 main() 必须真的调这条检查：函数写好了却没接线 = 等于没有。

    这条是**源码级**的（不改写也不放宽任何判据）：不真跑 main() 是因为它会 import 桌宠
    建 Qt 窗口（单跑约 110 秒），而"有没有接上线"用 AST 看调用名就够确定了。
    """
    path = os.path.join(C.ROOT, "_check_static.py")
    tree = ast.parse(io.open(path, encoding="utf-8").read())
    main_fn = [n for n in tree.body
               if isinstance(n, ast.FunctionDef) and n.name == "main"]
    assert main_fn, "静态体检没有 main()？用例前提失效"
    called = {n.func.id for n in ast.walk(main_fn[0])
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "check_undefined_names" in called, "main() 里没有调用 check_undefined_names（没接线）"
