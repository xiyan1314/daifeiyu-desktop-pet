# -*- coding: utf-8 -*-
"""v2.5.0（A2）按子系统补的类型注解：只覆盖"本轮搬走的那几个子系统"的模块。

范围（52 个函数，全部参数 + 返回值，含私有/嵌套）：
  · pet_services.py（新模块，A1 的产地）
  · pet_wander.py / pet_weather.py / pet_menu.py / pet_mood.py / pet_ai.py

**故意不在范围内**（不是漏了）：
  · pet_dialogs.py / pet_voice.py / pet_resources.py —— 本轮别的代理在动（任务书点名不要动）；
  · pet_anim.py / pet_actions.py —— README「类型注解口径」表把它们的 (已注解, 总数) 钉成
    (0, 13) / (0, 7)；补注解会让 tests/test_round3_a_fixes 的 README 用例变红，而"改 README
    其它数字"不在本轮的授权口径里。下一轮连同 README 一起做；
  · pet_chat / pet_balance / pet_alarm / pet_behaviors / pet_book —— 同一个 README 表把它们
    写成"❌ 0 / 本轮未新增注解"，补了会让那张表当场变成假话。
  口径就是一句话：**README 注解表没点到的子系统模块，本轮补全；点到的一律不碰。**

三条断言都能真失败（括号里是变异）：
  1. 范围内每个函数都必须"参数 + 返回值"齐全（删掉任意一个 -> int / 加一个没注解的函数 → 红）；
  2. 注解必须能在运行时解析（typing.get_type_hints；写错名字 / 漏 import → 红）；
  3. 不许"标 -> None 却 return 值"（注解与真实行为不符 → 红）。
"""
import ast
import io
import os
import sys
import typing

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

SCOPE = ("pet_services.py", "pet_wander.py", "pet_weather.py", "pet_menu.py",
         "pet_mood.py", "pet_ai.py")
# 到期复核的"范围外"对照：README 表钉住的三个（值变了就要连 README 一起改，见上）
OUT_OF_SCOPE_PINNED = {"pet_anim.py": (0, 13), "pet_actions.py": (0, 7)}


def _read(name):
    return io.open(os.path.join(HERE, name), encoding="utf-8").read()


def _missing_annotations(node):
    """函数缺哪些注解 → ["参数 a", "参数 *a", "参数 **kw", "返回值"]；齐全返回 []。"""
    miss = []
    for arg in list(node.args.posonlyargs) + list(node.args.args) + list(node.args.kwonlyargs):
        if arg.arg not in ("self", "cls") and arg.annotation is None:
            miss.append("参数 %s" % arg.arg)
    if node.args.vararg is not None and node.args.vararg.annotation is None:
        miss.append("参数 *%s" % node.args.vararg.arg)
    if node.args.kwarg is not None and node.args.kwarg.annotation is None:
        miss.append("参数 **%s" % node.args.kwarg.arg)
    if node.returns is None:
        miss.append("返回值")
    return miss


def _returns_value_despite_none(node):
    if not (isinstance(node.returns, ast.Constant) and node.returns.value is None):
        return False
    return any(isinstance(x, ast.Return) and x.value is not None for x in ast.walk(node))


def _class_paths(src):
    """("类.方法" | "模块级函数") 列表——**只**沿 ClassDef 往下走。

    嵌套函数（函数里的函数）没有可解析的运行时路径（不是属性），所以这里不收集；它们由
    上面那条 ast.walk 版的完整性用例覆盖（"每个函数都要有注解"），两条分工互补。
    """
    out = []

    def walk(node, prefix):
        for child in getattr(node, "body", []):
            if isinstance(child, ast.ClassDef):
                walk(child, prefix + child.name + ".")
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.append(prefix + child.name)
    walk(ast.parse(src), "")
    return out


def _find(src, dotted):
    parts = dotted.split(".")
    node = ast.parse(src)
    for i, part in enumerate(parts):
        want = (ast.FunctionDef, ast.AsyncFunctionDef) if i == len(parts) - 1 else (ast.ClassDef,)
        node = next((c for c in ast.walk(node) if isinstance(c, want) and c.name == part), None)
        if node is None:
            return None
    return node


def _resolve(mod, dotted):
    obj = mod
    for part in dotted.split("."):
        obj = getattr(obj, part)
    return obj


# ---------------- 控制组：检查器本身必须能失败 ----------------

def test_annotation_checkers_can_fail():
    """反例：两个检查器要认得出合成坏样本，否则下面两条正例是空转。"""
    tree = ast.parse("def f(a, b: int) -> int:\n    return a\n")
    assert _missing_annotations(tree.body[0]) == ["参数 a"]
    assert _missing_annotations(ast.parse("def f(*a, **kw) -> int:\n    return 0\n").body[0]) \
        == ["参数 *a", "参数 **kw"]
    assert _missing_annotations(ast.parse("def f(a: int) -> int:\n    return a\n").body[0]) == []
    assert _returns_value_despite_none(ast.parse("def f() -> None:\n    return 1\n").body[0]) is True
    assert _returns_value_despite_none(ast.parse("def f() -> None:\n    return\n").body[0]) is False
    assert _class_paths("class A:\n    def m(self):\n        pass\n") == ["A.m"]
    assert _find("class A:\n    def m(self):\n        pass\n", "A.m") is not None
    assert _find("class A:\n    def m(self):\n        pass\n", "A.nope") is None


# ---------------- 1. 范围内全注解 ----------------

def test_scope_modules_are_fully_annotated():
    """范围内 52 个函数（含私有/嵌套）每个都要"参数 + 返回值"齐全。

    能真失败：把任意一个签名改回没注解（例如 pet_weather.WeatherService.fetch 去掉 -> None）
    → missing 里立刻出现那一项。
    """
    missing, checked = {}, 0
    for name in SCOPE:
        src = _read(name)
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            checked += 1
            bad = _missing_annotations(node)
            if bad:
                missing["%s:%d %s" % (name, node.lineno, node.name)] = bad
    assert missing == {}, missing
    assert checked >= 52, "只查到 %d 个函数（范围应 ≥52，检查器可能退化了）" % checked


# ---------------- 2/3. 注解可解析 + 与真实行为一致 ----------------

def test_scope_annotations_resolve_and_match_behavior():
    """注解能在运行时解析（写错类型名 / 漏 import 会抛），且没有"标 -> None 却 return 值"。

    能真失败：把某个返回注解写成不存在的名字（-> NoSuchType）→ get_type_hints 抛 NameError；
    给一个"return 值"的函数标上 -> None → 第三条断言红。
    """
    import importlib
    checked = 0
    for name in SCOPE:
        mod = importlib.import_module(name[:-3])
        src = _read(name)
        for dotted in _class_paths(src):
            node = _find(src, dotted)
            assert node is not None, "AST 定位失败（检查器坏了）：%s %s" % (name, dotted)
            obj = _resolve(mod, dotted)
            fn = obj.fget if isinstance(obj, property) else obj
            typing.get_type_hints(fn)          # 抛异常 = 注解不可解析
            assert _returns_value_despite_none(node) is False, "%s.%s" % (name, dotted)
            checked += 1
    assert checked >= 40, "只解析了 %d 个函数？范围明显缩水" % checked


def test_out_of_scope_modules_are_left_alone():
    """范围外那两个被 README 钉住的模块必须还是零注解（要动就得连 README 一起动）。

    能真失败：顺手给 pet_anim.py 补注解 → 第一条断言红（同时 README 用例也会红，两处互相印证）。
    """
    for name, (ret, tot) in OUT_OF_SCOPE_PINNED.items():
        src = _read(name)
        got_ret = got_tot = 0
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                got_tot += 1
                got_ret += 1 if node.returns is not None else 0
        assert (got_ret, got_tot) == (ret, tot), \
            "%s 的注解数变了：实测 (%d, %d)，README 表钉的是 (%d, %d)" % (
                name, got_ret, got_tot, ret, tot)
