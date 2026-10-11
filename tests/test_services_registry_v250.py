# -*- coding: utf-8 -*-
"""v2.5.0（A1）子系统构造注册表：服务构造从 PetWindow.__init__ 搬进 pet_services.ServiceRegistry。

本模块钉六件事，每条都能真失败（括号里是"把它改坏"的变异）：

  1. **构造顺序**：一次 PetWindow() 里全部 pet_xxx 构造调用的**出现序列** == v2.4.4
     __init__ 的原始序列（把 build_anim 挪到 _build_services 之前 → 红）；
  2. **服务集合 + 类型**：pet 上那批属性逐个是**原来那一类**对象（少挂一个 / 挂错类 → 红）；
  3. **只调一次注册表**：__init__ 里 ServiceRegistry(...) 恰好 1 处，且是
     `self.services = pet_services.ServiceRegistry(self, **_service_deps())` 这个形状
     （拆回 15 处字面 new → 红）；
  4. **__init__ 只剩三处 pet_xxx 构造**：fx×2 与 pet_audio.init（pet_services 的 docstring
     写明为什么这三处不搬——渲染层序 + 一次性初始化）；
  5. **不反向 import**：pet_services.py 不 import 桌宠（成环 → 红）；
  6. **发货清单**：pet_services.py 在 _check_release.SYNC_FILES 里（漏加 → 绿色版/发布包
     缺件时任何门都不响、用户双击即 ImportError → 红）。

另有一条**异常语义**用例：book 构造失败仍要"记一行日志 + book=None + 启动不中断 + 后面的
服务照建"——这是"逐位不变"的一部分，不是"顺手改好"。
"""
import ast
import io
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import 桌宠 as main  # noqa: E402
import pet_actions  # noqa: E402
import pet_ai  # noqa: E402
import pet_alarm  # noqa: E402
import pet_anim  # noqa: E402
import pet_audio  # noqa: E402
import pet_balance  # noqa: E402
import pet_behaviors  # noqa: E402
import pet_book  # noqa: E402
import pet_chat  # noqa: E402
import pet_fx  # noqa: E402
import pet_lines  # noqa: E402
import pet_menu  # noqa: E402
import pet_mood  # noqa: E402
import pet_resources  # noqa: E402
import pet_tools  # noqa: E402
import pet_voice  # noqa: E402
import pet_wander  # noqa: E402
import pet_weather  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def _read(name):
    return io.open(os.path.join(HERE, name), encoding="utf-8").read()


# v2.4.4（HEAD 2a6563c）PetWindow.__init__ 里 pet_xxx 构造调用的**出现序列**。
# 顺序就是口径：注册表可以把语句搬走，但不许改它们彼此的先后。
_GOLDEN_ORDER = (
    ("pet_resources", "RoleLibrary", "role_lib"),
    ("pet_resources", "AudioLibrary", "audio_lib"),
    ("pet_book", "Book", "book"),
    ("pet_lines", "LineService", "lines_lib"),
    ("pet_resources", "VoiceAssetLibrary", "voice_assets"),
    ("pet_wander", "WanderController", "wander"),
    ("pet_weather", "WeatherService", "weather"),
    ("pet_tools", "ToolContext", "tool_ctx"),
    ("pet_chat", "ChatService", "chat"),
    ("pet_ai", "AIService", "ai"),
    ("pet_balance", "BalanceService", "balance"),
    ("pet_actions", "ActionService", "actions"),
    ("pet_voice", "VoiceService", "voice"),
    ("pet_behaviors", "BehaviorService", "behaviors"),
    ("pet_alarm", "AlarmService", "alarms"),
    ("pet_menu", "MenuBuilder", "menu_builder"),
    ("pet_fx", "AnimatedEmote", "fx"),
    ("pet_fx", "AnimatedEmote", "fx_money"),
    ("pet_anim", "FrameAnim", "anim"),
    ("pet_mood", "Mood", "mood"),
    ("pet_audio", "init", None),
)

# __init__ 里允许**留在原地**的构造（见 pet_services.py 模块 docstring 的"没有搬的三处"）
_LEFTOVER_IN_INIT = ["pet_fx.AnimatedEmote", "pet_fx.AnimatedEmote", "pet_audio.init"]


def _pet_calls(node):
    """node 子树里所有 `pet_xxx.name(...)` 调用，按源码出现顺序。"""
    out = []
    for st in ast.walk(node):
        if isinstance(st, ast.Call) and isinstance(st.func, ast.Attribute) \
                and isinstance(st.func.value, ast.Name) and st.func.value.id.startswith("pet_"):
            out.append((st.lineno, "%s.%s" % (st.func.value.id, st.func.attr)))
    return [n for _ln, n in sorted(out)]


def _find_init(src):
    tree = ast.parse(src)
    for cls in tree.body:
        if isinstance(cls, ast.ClassDef) and cls.name == "PetWindow":
            for fn in cls.body:
                if isinstance(fn, ast.FunctionDef) and fn.name == "__init__":
                    return fn
    raise AssertionError("PetWindow.__init__ 不见了（AST 定位器坏了，不是代码问题）")


def _registry_calls(node):
    return [n for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "ServiceRegistry"]


# ---------------- 夹具 ----------------

def _point_data_dir(tmp_path):
    import pet_log
    snap = (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
            getattr(pet_log, "_data_dir", None))
    main.DATA_DIR = str(tmp_path)
    main.CONFIG_PATH = str(tmp_path / "config.json")
    main.USAGE_PATH = str(tmp_path / "usage.json")
    main.MEMORY_PATH = str(tmp_path / "memory.json")
    pet_log.set_data_dir(str(tmp_path))
    return snap


def _restore(snap):
    import pet_log
    (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
     pet_log._data_dir) = snap


@pytest.fixture
def isolated_data(tmp_path):
    snap = _point_data_dir(tmp_path)
    QApplication.instance() or QApplication([])
    try:
        yield tmp_path
    finally:
        _restore(snap)


def _install_recorders(monkeypatch):
    """把每个服务类换成"记一笔再返回真实例"的工厂。

    返回 (calls, reals)：calls 是构造调用序列（"模块.名字"），reals 是 {模块.名字: 真类}
    ——工厂返回的是**真实例**，所以 isinstance 检查与别的用例都不会因为打桩而失真。
    """
    calls, reals = [], {}
    done = set()
    for mod, name, _attr in _GOLDEN_ORDER:
        if (mod, name) in done:
            continue  # 同名构造出现多次（fx/fx_money）→ 只包一层，否则工厂套工厂会记两遍
        done.add((mod, name))
        real = getattr(sys.modules[mod], name)
        reals["%s.%s" % (mod, name)] = real

        def factory(*a, _mod=mod, _name=name, _real=real, **k):
            calls.append("%s.%s" % (_mod, _name))
            return _real(*a, **k)

        monkeypatch.setattr(sys.modules[mod], name, factory, raising=True)
    return calls, reals


# ---------------- 1/2. 构造顺序 + 服务集合与类型 ----------------

def test_service_construction_order_and_types_match_the_old_init(isolated_data, monkeypatch):
    """一次 PetWindow() 里 20 个服务构造的**先后**与**类型**都必须与旧 __init__ 一致。

    能真失败：把 pet_services._build_services() 里 wander/weather 两行对调 →
    第 1 条断言的序列立刻不同；把 build_anim() 挪到构造调用之前 → FrameAnim 提前到
    第 1 位；把某个服务的类换掉 → 第 2 条断言的 isinstance 红。
    """
    from helpers_roles import shutdown_pet

    calls, reals = _install_recorders(monkeypatch)
    win = None
    try:
        win = main.PetWindow()
        want = ["%s.%s" % (m, n) for m, n, _a in _GOLDEN_ORDER]
        assert calls == want, ("服务构造顺序变了：\n  实测 %r\n  口径 %r" % (calls, want))
        for mod, name, attr in _GOLDEN_ORDER:
            if attr is None:
                continue  # pet_audio.init：不是对象，没有可挂的属性
            obj = getattr(win, attr, None)
            assert obj is not None, "pet.%s 没挂上（原名访问不到了）" % attr
            assert isinstance(obj, reals["%s.%s" % (mod, name)]), \
                "pet.%s 不是 %s.%s 的实例：%r" % (attr, mod, name, type(obj))
    finally:
        if win is not None:
            shutdown_pet(win)


# ---------------- 3/4. __init__ 的形状 ----------------

def test_init_calls_the_registry_once_in_the_one_line_form():
    """__init__ 里注册表只被调一次，且形状就是那一行（拆回字面 new → 红）。

    能真失败：把 ServiceRegistry 那一行拆成两处调用 → 第 1 条断言红；改成逐服务字面
    new（15 处）→ 第 2 条断言红。
    """
    init = _find_init(_read("桌宠.py"))
    regs = _registry_calls(init)
    assert len(regs) == 1, "__init__ 里注册表调用点是 %d 处（应为 1 处）：%r" % (
        len(regs), [(n.lineno, ast.unparse(n)) for n in regs])
    call = regs[0]
    assert call.func.value.id == "pet_services", ast.unparse(call)
    assert len(call.args) == 1 and isinstance(call.args[0], ast.Name) \
        and call.args[0].id == "self", "注册表第一个实参不是 self：%s" % ast.unparse(call)
    kws = call.keywords
    assert len(kws) == 1 and kws[0].arg is None, \
        "注册表实参不是 **… 形式：%s" % ast.unparse(call)
    assert ast.unparse(kws[0].value).strip() == "_service_deps()", ast.unparse(call)


def test_init_keeps_only_the_three_documented_constructions():
    """搬完之后 __init__ 里只剩三处 pet_xxx 构造（fx×2 / pet_audio.init），且顺序不变。

    能真失败：把 _service_deps() 那行换成把某个服务构造写回 __init__ → 列表里多一项。
    """
    got = [n for n in _pet_calls(_find_init(_read("桌宠.py")))
           if not n.startswith("pet_services.")]  # 注册表自己那一行由上面那条用例钉
    assert got == _LEFTOVER_IN_INIT, (
        "__init__ 里剩下的 pet_xxx 构造变了：%r（口径 %r；新搬走的请看 pet_services.py）"
        % (got, _LEFTOVER_IN_INIT))


def test_service_deps_are_read_at_construction_time(isolated_data):
    """注入面必须是**调用时求值**：测试先 monkeypatch main.DATA_DIR 再建窗口，得吃到新值。

    （做成模块级常量就会在 import 时固化成真实用户目录 → 全仓"临时数据目录"夹具集体失效；
    所以它是个函数。这条用例就是那个约定的守卫。）

    能真失败：把 _service_deps 改成模块级 dict → 第一条断言拿到的是仓库真实数据目录。
    """
    deps = main._service_deps()
    assert deps["data_dir"] == str(isolated_data), deps["data_dir"]
    assert deps["config_path"] == str(isolated_data / "config.json")
    assert deps["usage_path"] == str(isolated_data / "usage.json")
    assert deps["memory_path"] == str(isolated_data / "memory.json")
    # 每一项都是**同一个对象**，不是包了一层的 lambda（包一层会改"构造期取的是哪一份"）
    for key, obj in (("log", main._log_error), ("save_cfg", main.save_config),
                     ("signals", main.signals), ("play_sound", main.play_sound),
                     ("set_redact_key", main.set_redact_key),
                     ("parse_emote", main.parse_emote_tag),
                     ("load_memory", main.load_chat_memory),
                     ("save_memory", main.save_chat_memory),
                     ("ai_prompt", main._build_ai_sys_prompt),
                     ("idle_picker", main.pick_idle_action),
                     ("autostart_enabled", main.is_autostart_enabled),
                     ("defaults", main.DEFAULT_CONFIG)):
        assert deps[key] is obj, "%s 不是原对象（被包了一层？）：%r" % (key, deps[key])


# ---------------- 5. 不反向 import ----------------

def _main_module_imports(src):
    bad = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            bad += [a.name for a in node.names if a.name == "桌宠"]
        elif isinstance(node, ast.ImportFrom) and node.module == "桌宠":
            bad.append("from 桌宠 import ...")
    return bad


def test_registry_module_does_not_import_the_main_module():
    """pet_services 不 import 桌宠：桌宠.py 要 import 它，反向 import 就是环。

    能真失败：在 pet_services.py 顶上写一行 import 桌宠 → 第一条断言红。
    """
    assert _main_module_imports(_read("pet_services.py")) == []
    # 控制组：提取器必须认得真样本（否则上面那条是空转）
    assert _main_module_imports("import 桌宠\n") == ["桌宠"]
    assert _main_module_imports("from 桌宠 import PetWindow\n") == ["from 桌宠 import ..."]
    assert _main_module_imports("import pet_lines\n") == []


# ---------------- 6. 发货清单 ----------------

def test_pet_services_is_in_the_release_sync_list():
    """新模块必须进 _check_release.SYNC_FILES，否则绿色版/发布包缺件时任何门都不响。

    能真失败：从 SYNC_FILES 里删掉 "pet_services.py" → 第一条断言红。
    """
    import _check_release as chk
    assert "pet_services.py" in chk.SYNC_FILES, "新模块没进 SYNC_FILES（缺件时发布门不响）"
    assert os.path.isfile(os.path.join(chk.ROOT, "pet_services.py"))
    # 同样的理由：桌宠.py 必须真的 import 它（否则注册表根本没被用上）
    assert "import pet_services" in _read("桌宠.py")


# ---------------- 异常语义：book 构造失败 ----------------

def test_book_construction_failure_still_falls_back(isolated_data, monkeypatch):
    """book 构造失败 → 记一行日志 + book=None + 启动不中断 + 后面的服务照建。

    这是搬迁前那条 try/except 的**逐位口径**（不是"顺手改好"）：异常照旧被吞掉，日志文案
    与 _usage 兜底 0.0 都不变。注册表只是换了产地，没换语义。

    能真失败：把 pet_services._build_libraries 里的 try/except 拿掉 → PetWindow() 直接抛
    RuntimeError，本用例在构造那一行就红。
    """
    from helpers_roles import shutdown_pet

    logs = []

    def boom(*_a, **_k):
        raise RuntimeError("boom-book")

    monkeypatch.setattr(pet_book, "Book", boom)
    monkeypatch.setattr(main, "_log_error", lambda msg: logs.append(msg))
    win = None
    try:
        win = main.PetWindow()  # 必须**不抛**
        assert win.book is None, "book 构造失败没有兜底成 None：%r" % (win.book,)
        assert any("book init failed" in m and "boom-book" in m for m in logs), \
            "没有留下那行诊断日志：%r" % (logs,)
        assert win._usage == 0.0, "_usage 兜底不是 0.0：%r" % (win._usage,)
        # 异常之后的构造照跑（旧口径：book 挂了不影响别的服务）
        assert win.role_lib is not None and win.lines_lib is not None and win.chat is not None
    finally:
        if win is not None:
            shutdown_pet(win)
