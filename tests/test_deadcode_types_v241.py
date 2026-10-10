# -*- coding: utf-8 -*-
"""v2.4.1（代理 D）回归：未使用导入清理 + "仅测试引用"函数去留 + 本轮类型注解。

每组锁都自带**反例对照**（同一检查器喂合成坏样本必须报错），避免"检查器恒通过"的空转。
覆盖的事实（依据见回报与各处代码注释）：
- pet_dialogs.py 的 QRadioButton 是真死导入，已删；桌宠.py 的 QWidgetAction **不是**——
  它是 _verify_v13.py:1529 / _verify_green.py:87 依赖的再导出，删了护栏直接 AttributeError。
- 桌宠.py 的 ctypes.wintypes 必须是**显式子模块导入**：裸 import ctypes 不绑定它，
  而 nativeEvent 用的是 ctypes.wintypes.MSG。改法去掉了未使用的模块级名字 wintypes。
- pet_behaviors.set_idle_play_mode / pet_resources.state_resource 判定为残留（生产零引用
  且与真正的生产路径重复）已删；pet_tools.tool_names / pet_io.load_json 判定为有意保留。
- pet_tools.py（39 个函数）与 pet_lines.py（43 个函数）的本轮注解必须完整、可解析、
  与**真实返回形状**一致，且不得"标 -> None 却 return 值"。注解检查按 "类.方法" 精确定位：
  MainThreadCall.wait 与 ToolConfirmRequest.wait 同名不同类，只按名字查会张冠李戴。
"""
import ast
import io
import os
import re
import types
import typing

import pytest

import pet_behaviors
import pet_lines
import pet_resources
import pet_tools

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 与 _check_static.py 的 H 检查同口径：四个开发/护栏脚本不进扫描
SKIP_SCAN = {"_check_static.py", "_check_release.py", "_verify_v13.py", "_verify_green.py"}


def _read(name):
    return io.open(os.path.join(HERE, name), encoding="utf-8").read()


# ---------------- 导入检查器（先证明它能失败） ----------------
def _imported_names(src):
    """源码里被 import 绑定的名字集合（含 from-import 的每个别名）。"""
    out = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            out.update(a.asname or a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            out.update(a.asname or a.name for a in node.names if a.name != "*")
    return out


def _unused_imports(src):
    """源码里"零引用且整条语句没标 noqa"的导入名 → [名字]（= 修正版静态 H 检查）。

    _check_static.py 的 H 检查对**多行 import 块**失明：它拿语句首行当 lineno，于是
    "QRadioButton," 这一行自己就被数成一次使用。这里按 ast 别名行号、并把**整个语句区间**
    （含续行）排除在外，多行块里每个名字各自判定；语句里有 noqa 的整条豁免（有意保留的再导出）。
    """
    lines = src.split("\n")
    unused = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        lo, hi = node.lineno, getattr(node, "end_lineno", node.lineno)
        if "noqa" in "\n".join(lines[lo - 1:hi]):
            continue
        for a in node.names:
            if a.name == "*":
                continue
            nm = ((a.asname or a.name.split(".")[0]) if isinstance(node, ast.Import)
                  else (a.asname or a.name))
            if not any(not (lo <= i <= hi)
                       and re.search(r"\b%s\b" % re.escape(nm), l.split("#", 1)[0])
                       for i, l in enumerate(lines, 1)):
                unused.append(nm)
    return unused


def test_unused_import_checker_can_fail():
    """反例：检查器必须能认出合成样本里的未使用导入——尤其是**多行块**（静态 H 的盲区）。"""
    assert _unused_imports("import os\nimport sys\nprint(sys.path)\n") == ["os"]
    assert _unused_imports("from x import (\n    a,\n    b,\n)\nprint(b)\n") == ["a"]
    assert _unused_imports("from x import (a,  # noqa: F401\n                 b)\n") == []
    assert _unused_imports("import os\nimport os.path\nprint(os.path.join('a'))\n") == []


def test_no_unused_imports_outside_noqa():
    """正例（全仓运行时代码）：除显式 noqa 的再导出外，不得有零引用导入。

    这条把静态体检 H 的盲区补上（QRadioButton 正是那样漏掉的）。
    """
    bad = {}
    for f in sorted(os.listdir(HERE)):
        if not f.endswith(".py") or f in SKIP_SCAN:
            continue
        u = _unused_imports(_read(f))
        if u:
            bad[f] = u
    assert bad == {}, "有未使用导入（要么删掉，要么加 noqa 并写清为什么留）：%r" % (bad,)


def test_removed_unused_import_stay_removed():
    """pet_dialogs.py：删掉的那个不得复活；同一个多行块里的在用品不得被"整块删掉"式误删。"""
    names = _imported_names(_read("pet_dialogs.py"))
    assert "QRadioButton" not in names
    assert {"QPushButton", "QSpinBox", "QTableWidget", "QDoubleSpinBox"} <= names


def test_wintypes_is_explicit_submodule_import():
    """桌宠.py：ctypes.wintypes 必须显式导入——裸 import ctypes **不会**绑定这个子模块。"""
    def _explicit(src):
        return bool(re.search(
            r"^(?:import ctypes\.wintypes|from ctypes import [^\n]*\bwintypes\b)", src, re.M))

    # 反例：只 import ctypes 的写法在运行时会 AttributeError（nativeEvent 的 ctypes.wintypes.MSG）
    assert not _explicit("import ctypes\n\nmsg = ctypes.wintypes.MSG.from_address(0)\n")
    assert _explicit("from ctypes import wintypes\n")
    assert _explicit("import ctypes.wintypes\n")
    assert _explicit(_read("桌宠.py"))


def test_wintypes_bound_and_dead_name_not_leaked():
    """运行时复核：ctypes.wintypes 可用；未使用的模块级名字 wintypes 不得被绑回来。"""
    import 桌宠 as main
    assert hasattr(main.ctypes, "wintypes"), "ctypes.wintypes 没绑定 → nativeEvent 会 AttributeError"
    assert "wintypes" not in vars(main), (
        "模块级名字 wintypes 又绑回来了（未使用导入复活）：要么改回 import ctypes.wintypes，"
        "要么让它真的被用到")


def test_qwidgetaction_reexport_is_load_bearing():
    """桌宠.py 的 QWidgetAction 看似零引用，实为护栏再导出（照"死导入"删掉会让 v13 直接红）。"""
    import 桌宠 as main
    saved = main.QWidgetAction
    assert isinstance(saved, type)
    try:
        del main.QWidgetAction            # 模拟"把它当死导入删掉"
        with pytest.raises(AttributeError):
            main.QWidgetAction            # _verify_v13.py:1529 的写法
    finally:
        main.QWidgetAction = saved
    assert main.QWidgetAction is saved
    for f in ("_verify_v13.py", "_verify_green.py"):
        assert re.search(r"main\.QWidgetAction", _read(f)), (
            "%s 不再引用 main.QWidgetAction：这个再导出可以重新评估去留了" % f)


def test_dead_helpers_removed_live_apis_kept():
    """去留判定的回归锁：删掉的不得复活；判定为保留的、以及生产在用的同族接口必须还在。"""
    # 删（生产零引用 + 与真正的生产路径重复）
    assert not hasattr(pet_behaviors, "set_idle_play_mode")   # 对话框直接写 cfg["idle_play_mode"]
    assert not hasattr(pet_resources, "state_resource")       # 生产走 RoleLibrary.form_state_paths
    # 留（有意保留的 API；用途写在各自 docstring 里）
    assert pet_tools.tool_names(), "tool_names 是注册表唯一的按权限列名单入口"
    assert not (set(pet_tools.tool_names(readonly=True))
                & set(pet_tools.tool_names(readonly=False))), "只读/写入两组不该有交集"
    import pet_io
    assert callable(pet_io.load_json), "load_json 是 read_json_or 的 ok 口径公开薄壳"
    # 防误删：UI / 生产真正在用的同族接口
    for name in ("add_idle_action", "remove_idle_action", "move_idle_action",
                 "update_idle_action", "normalize_idle_cfg", "pick_idle_action"):
        assert callable(getattr(pet_behaviors, name)), name
    for name in ("animation_frames", "form_render"):
        assert callable(getattr(pet_resources, name)), name
    assert callable(pet_resources.RoleLibrary.form_state_paths)


# ---------------- 注解检查器（同样先证明能失败） ----------------
# 故意不加注解的白名单（当前为空 = 这两个文件是全量注解，不是抽样板）。格式 {"路径": "为什么不加"}
_UNANNOTATED_OK = {}


def _func_paths(src):
    """源码里所有 FunctionDef 的路径（"f" / "Cls.m" / 嵌套 "f.inner"）。"""
    out = []

    def walk(node, prefix):
        for child in getattr(node, "body", []):
            if isinstance(child, ast.ClassDef):
                walk(child, prefix + child.name + ".")
            elif isinstance(child, ast.FunctionDef):
                out.append(prefix + child.name)
                walk(child, prefix + child.name + ".")

    walk(ast.parse(src), "")
    return out


# 本轮加了注解的函数全量清单（pet_tools 39 个 + pet_lines 43 个 = 82）。
# pet_lines.LineService.dirty_read 是 @property → 断言时取 getter。
_PINNED = {
    pet_tools: ["build_registry", "get_tool", "openai_tools", "tool_names", "validate_args",
                "parse_call", "args_json", "parse_args", "result_text", "summarize",
                "describe_call", "execute", "_schema", "_provider", "_ui",
                "ToolSpec.__init__", "ToolSpec.to_openai",
                "_h_check_balance", "_h_check_weather", "_h_ledger_summary", "_h_open_ledger",
                "_h_add_manual_record", "_h_set_budget", "_h_set_alarm", "_h_set_timer",
                "_h_show_emote", "_h_play_action",
                "_fmt_money", "_describe_manual", "_describe_budget", "_describe_alarm",
                "_describe_timer",
                "MainThreadCall.__init__", "MainThreadCall.resolve", "MainThreadCall.wait",
                "ToolConfirmRequest.__init__", "ToolConfirmRequest.resolve",
                "ToolConfirmRequest.wait", "ToolContext.__init__"],
    pet_lines: ["_seed_source", "_food_key",
                "LineService.__init__", "LineService.dirty_read", "LineService._load",
                "LineService._merge_builtins", "LineService._reindex", "LineService._save",
                "LineService._norm_line_checked", "LineService._norm_line",
                "LineService._norm_dialogue", "LineService._emit_changed",
                "LineService._snapshot", "LineService._invalidate_undo",
                "LineService.on_changed", "LineService.off_changed",
                "LineService.on_invalid_reference", "LineService.off_invalid_reference",
                "LineService.emit_invalid_reference", "LineService.lines", "LineService.get",
                "LineService.text_of", "LineService.by_category",
                "LineService.texts_by_category", "LineService.food_texts",
                "LineService.dialogues", "LineService.get_dialogue",
                "LineService.dialogue_lines", "LineService.categories", "LineService.count",
                "LineService.undo", "LineService.can_undo", "LineService.add",
                "LineService.save", "LineService.delete", "LineService.delete_many",
                "LineService.clear_all", "LineService.restore_builtins", "LineService.reorder",
                "LineService.add_dialogue", "LineService.save_dialogue",
                "LineService.delete_dialogue", "LineService.validate_references"],
}


def _resolve(mod, dotted):
    """"模块.类.属性" → 对象（兼容模块级函数与会话内方法）。"""
    obj = mod
    for part in dotted.split("."):
        obj = getattr(obj, part)
    return obj


def _find_func(src, dotted):
    """按 "函数" 或 "类.方法" 精确定位 FunctionDef → node；不存在返回 None。

    必须按路径定位：MainThreadCall.wait / ToolConfirmRequest.wait 同名不同类，
    只按名字查会**张冠李戴**（查了 A 类却以为在查 B 类，正例就成了空转）。
    """
    parts = dotted.split(".")
    node = ast.parse(src)
    for i, part in enumerate(parts):
        want = (ast.FunctionDef,) if i == len(parts) - 1 else (ast.ClassDef, ast.FunctionDef)
        node = next((c for c in ast.walk(node) if isinstance(c, want) and c.name == part), None)
        if node is None:
            return None
    return node


def _missing_annotations(src, dotted):
    """源码里 dotted（"函数" 或 "类.方法"）缺哪些注解 → ["参数 a", "返回值"]；不存在返回 None。"""
    node = _find_func(src, dotted)
    if node is None:
        return None
    miss = []
    a = node.args
    for arg in list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs):
        if arg.arg not in ("self", "cls") and arg.annotation is None:
            miss.append("参数 %s" % arg.arg)
    if a.vararg is not None and a.vararg.annotation is None:
        miss.append("参数 *%s" % a.vararg.arg)
    if a.kwarg is not None and a.kwarg.annotation is None:
        miss.append("参数 **%s" % a.kwarg.arg)
    if node.returns is None:
        miss.append("返回值")
    return miss


def _returns_value_despite_none(src, dotted):
    """dotted 标了 -> None 却在函数体里 return <值> → True（注解与真实行为不符）；不存在 None。"""
    node = _find_func(src, dotted)
    if node is None:
        return None
    if not (isinstance(node.returns, ast.Constant) and node.returns.value is None):
        return False
    return any(isinstance(x, ast.Return) and x.value is not None for x in ast.walk(node))


def test_annotation_checkers_can_fail():
    """反例：两个注解检查器必须能认出合成坏样本（否则下面的正例是空转）。"""
    assert _missing_annotations("def f(a, b: int) -> int:\n    return a + b\n", "f") == ["参数 a"]
    assert _missing_annotations("def f(a):\n    return a\n", "f") == ["参数 a", "返回值"]
    assert _missing_annotations("def f(a: int) -> int:\n    return a\n", "f") == []
    assert _missing_annotations("def f(*a, **kw) -> int:\n    return 0\n", "f") == ["参数 *a", "参数 **kw"]
    assert _missing_annotations("def g(a):\n    return a\n", "f") is None
    # 反例（同名跨类）：必须按 "类.方法" 定位，别把 A 类的 wait 当成 B 类的
    _two = ("class A:\n"
            "    def wait(self):\n"
            "        pass\n"
            "class B:\n"
            "    def wait(self, t: int) -> bool:\n"
            "        return True\n")
    assert _missing_annotations(_two, "A.wait") == ["返回值"]
    assert _missing_annotations(_two, "B.wait") == []
    assert _missing_annotations(_two, "C.wait") is None
    assert _missing_annotations(_two, "B.nope") is None
    assert _returns_value_despite_none("def f() -> None:\n    return 1\n", "f") is True
    assert _returns_value_despite_none("def f() -> None:\n    return\n", "f") is False
    assert _returns_value_despite_none("def f() -> int:\n    return 1\n", "f") is False


def test_pinned_annotations_are_complete():
    """正例：本轮注解的纯函数必须"每个参数 + 返回值"都有注解，且清单不得缩水。

    非空转护栏：_PINNED 必须**恰好等于**两个文件里的全部函数路径（除 _UNANNOTATED_OK）——
    把 _PINNED 清空（本用例会退化成恒真）、或新增函数却忘了登记，都必须红。
    """
    # 非空转：护栏必须在**循环外**——_PINNED = {} 时循环体一次都不跑，
    # 写在循环里的断言等于没有（这条是被变异验证抓出来的，别挪回去）
    assert set(_PINNED) == {pet_tools, pet_lines}, "两个模块都必须登记：%r" % (list(_PINNED),)
    missing = {}
    for mod, names in _PINNED.items():
        assert names, "%s 一条函数都没登记" % mod.__name__
        src = io.open(mod.__file__, encoding="utf-8").read()
        expected = [p for p in _func_paths(src) if p not in _UNANNOTATED_OK]
        assert sorted(names) == sorted(expected), (
            "%s 的 _PINNED 与源码函数表不一致：漏登记 %r，多登记 %r"
            % (mod.__name__, sorted(set(expected) - set(names)),
               sorted(set(names) - set(expected))))
        for name in names:
            miss = _missing_annotations(src, name)
            assert miss is not None, "%s.%s 不见了？" % (mod.__name__, name)
            if miss:
                missing["%s.%s" % (mod.__name__, name)] = miss
    assert missing == {}, missing


def test_scope_files_have_no_unannotated_functions():
    """pet_tools.py / pet_lines.py 的**每个**函数（含私有、嵌套）都必须有完整注解。

    这不是"抽几个样板"：把 count() 的 `-> int` 删掉、或新加一个没注解的函数，本用例必红。
    真要有意不加，就写进 _UNANNOTATED_OK 并说清理由（当前为空）。
    """
    assert not _UNANNOTATED_OK or all(len(v) > 8 for v in _UNANNOTATED_OK.values()), \
        "豁免必须写清理由（一句话）"
    missing = {}
    checked = 0
    for mod in (pet_tools, pet_lines):
        src = io.open(mod.__file__, encoding="utf-8").read()
        for path in _func_paths(src):
            if path in _UNANNOTATED_OK:
                continue
            checked += 1
            miss = _missing_annotations(src, path)
            assert miss is not None, "定位失败（检查器坏了，不是代码问题）：%s" % path
            if miss:
                missing["%s.%s" % (mod.__name__, path)] = miss
    assert missing == {}, missing
    assert checked >= 80, "只查到 %d 个函数？两个文件本轮共 82 个" % checked


def test_pinned_annotations_resolve_and_match_behavior():
    """正例：注解能在运行时解析（写错名字/漏 import 会抛），且没有"标 -> None 却 return 值"。"""
    assert _PINNED, "_PINNED 空 → 本用例空转"
    for mod, names in _PINNED.items():
        src = io.open(mod.__file__, encoding="utf-8").read()
        for name in names:
            obj = _resolve(mod, name)
            fn = obj.fget if isinstance(obj, property) else obj
            typing.get_type_hints(fn)      # 抛异常 = 注解不可解析
            assert _returns_value_despite_none(src, name) is False, name


# ---------------- 形状校验：声明的返回注解 ↔ 真实返回值 ----------------
def _ann_classes(hint):
    """注解 → 可在运行时 isinstance 的类元组（支持内建类型 / Any / X | None / 容器泛型）。

    检查器不认识的形式**直接报错**：宁可在测试里说"不认识这个注解"，也不假装检查过了。
    """
    if hint is typing.Any:
        return (object,)
    if hint is type(None):
        return (type(None),)
    origin = typing.get_origin(hint)
    if origin is typing.Union or origin is types.UnionType:      # X | None
        out = ()
        for arg in typing.get_args(hint):
            out += _ann_classes(arg)
        return out
    if origin is not None and isinstance(origin, type):          # list[dict] / tuple[bool, str]
        return (origin,)
    if isinstance(hint, type):
        return (hint,)
    raise AssertionError("检查器不认识这个注解：%r（要支持就扩 _ann_classes）" % (hint,))


def _check_return(fn, value, label):
    """按 fn 声明的返回注解校验真实返回值 value → 不符则 AssertionError。"""
    hint = typing.get_type_hints(fn).get("return")
    assert hint is not None, "%s 没有返回注解" % label
    assert isinstance(value, _ann_classes(hint)), \
        "%s 声明返回 %r，真实返回 %r（%s）" % (label, hint, value, type(value).__name__)


def test_return_shape_checker_can_fail():
    """反例：形状校验器必须能认出"注解与真实返回不符"（否则下面的正例是空转）。"""
    def _bad_int() -> int:
        return "不是整数"

    def _bad_list() -> list:
        return {}

    assert _ann_classes(int) == (int,)
    assert _ann_classes(str | None) == (str, type(None))
    assert _check_return(_bad_int, 1, "_bad_int") is None         # 正对照：对的必须过
    with pytest.raises(AssertionError):
        _check_return(_bad_int, _bad_int(), "_bad_int")
    with pytest.raises(AssertionError):
        _check_return(_bad_list, _bad_list(), "_bad_list")
    with pytest.raises(AssertionError):
        _check_return(lambda: None, 3, "无注解")
    with pytest.raises(AssertionError):                           # 不认识的注解不许静默通过
        _ann_classes(typing.Literal["a"])


def test_annotation_matches_real_return_shapes():
    """抽查 pet_tools 的"注解 ↔ 真实返回形状"（只查语法不算数：注解必须与真实行为一致）。"""
    _check_return(pet_tools.tool_names, pet_tools.tool_names(), "tool_names")
    _check_return(pet_tools.build_registry,
                  pet_tools.build_registry(pet_tools.TOOL_SPECS), "build_registry")
    _check_return(pet_tools.get_tool, pet_tools.get_tool("不存在"), "get_tool")
    _check_return(pet_tools.openai_tools, pet_tools.openai_tools(), "openai_tools")
    _check_return(pet_tools.parse_call,
                  pet_tools.parse_call({"function": {"arguments": "{broken"}}), "parse_call(坏)")
    _check_return(pet_tools.parse_call,
                  pet_tools.parse_call({"function": {"arguments": "{}"}}), "parse_call(好)")
    _check_return(pet_tools.args_json, pet_tools.args_json(None), "args_json")
    _check_return(pet_tools.parse_args, pet_tools.parse_args("{broken"), "parse_args")
    _check_return(pet_tools.result_text, pet_tools.result_text({"a": 1}), "result_text")
    _check_return(pet_tools.summarize, pet_tools.summarize(None), "summarize")
    _check_return(pet_tools.validate_args,
                  pet_tools.validate_args(pet_tools.get_tool("set_alarm"), {}), "validate_args")
    _check_return(pet_tools.describe_call, pet_tools.describe_call("set_alarm", {}), "describe_call")
    _check_return(pet_tools.execute, pet_tools.execute("不存在", {}, None), "execute")
    # 具体口径也钉一下（形状对但语义反了同样要红）
    assert isinstance(pet_tools.tool_names(), tuple)
    assert all(isinstance(x, str) for x in pet_tools.tool_names())
    assert pet_tools.get_tool("不存在") is None
    assert pet_tools.parse_call({"function": {"arguments": "{broken"}})[1] is None
    assert isinstance(pet_tools.parse_call({"function": {"arguments": "{}"}})[1], dict)
    assert pet_tools.parse_args("{broken") == {}
    assert pet_tools.args_json(None) == "{}"


def test_lines_annotations_match_real_return_shapes(tmp_path):
    """真跑一遍 LineService：声明的返回注解必须与实际返回值的类型一致。

    比"注解写没写"更硬：把 count() 标成 -> str、把 undo() 标成 -> bool 都要红。
    """
    svc = pet_lines.LineService(str(tmp_path))
    assert isinstance(svc.dirty_read, bool)                        # @property -> bool
    _check_return(pet_lines.LineService.count, svc.count(), "count")
    _check_return(pet_lines.LineService.categories, svc.categories(), "categories")
    _check_return(pet_lines.LineService.lines, svc.lines(), "lines")
    _check_return(pet_lines.LineService.dialogues, svc.dialogues(), "dialogues")
    _check_return(pet_lines.LineService.get, svc.get("不存在"), "get(缺)")
    _check_return(pet_lines.LineService.get_dialogue, svc.get_dialogue("不存在"),
                  "get_dialogue(缺)")
    _check_return(pet_lines.LineService.text_of, svc.text_of("不存在"), "text_of(缺)")
    _check_return(pet_lines.LineService.food_texts, svc.food_texts("小鱼干"), "food_texts")
    _check_return(pet_lines.LineService.texts_by_category, svc.texts_by_category("idle"),
                  "texts_by_category")
    _check_return(pet_lines.LineService.can_undo, svc.can_undo(), "can_undo")
    _check_return(pet_lines.LineService.undo, svc.undo(), "undo(无快照)")
    _check_return(pet_lines.LineService.delete_many, svc.delete_many([]), "delete_many(空)")
    _check_return(pet_lines.LineService.reorder, svc.reorder([]), "reorder(空)")
    _check_return(pet_lines.LineService.add_dialogue, svc.add_dialogue("空", []),
                  "add_dialogue(空)")
    _check_return(pet_lines.LineService.validate_references,
                  svc.validate_references(lambda s: True, lambda s: True), "validate_references")
    ln, err = svc.add("注解形状")
    assert isinstance(ln, dict) and isinstance(err, str)
    _check_return(pet_lines.LineService.add, (ln, err), "add")
    _check_return(pet_lines.LineService.save, svc.save(ln["id"], text="改过"), "save")
    _check_return(pet_lines.LineService.delete, svc.delete(ln["id"]), "delete")
    _check_return(pet_lines.LineService.undo, svc.undo(), "undo(有快照)")
    _check_return(pet_lines.LineService.restore_builtins, svc.restore_builtins(),
                  "restore_builtins")
    assert isinstance(svc.lines()[0], dict)
    assert all(isinstance(x, str) for x in svc.categories())
