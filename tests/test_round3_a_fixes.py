# -*- coding: utf-8 -*-
"""第三轮找茬（v2.4.3）代理 A 修复回归：P1-1 / P2-2 / P2-3 / P3-1 / P3-2 / P3-3 / P3-4 + 注解口径。

每条都配了"能真失败"的机制（本轮统一用 _dev/mutate_check.py 再验一遍：把修复那几行拿掉，
本文件的用例必须变红）：

  P1-1  BalanceService._worker 的 emit 裸露在 try 之外 → test_worker_* 一组：emit 打在
        已销毁对象上 / _request_balance 抛 / 退出中，守卫标志都必须复位、异常都不许外抛；
        test_control_naked_worker_really_leaks 是控制组（修复前的写法必须真的泄漏）；
  P2-2  pet_widgets 8 处 QFont 硬编码字体名 → 字体族列表断言 + AST"不许再出现硬编码族名"；
  P2-3  requirements.txt 的 requests/PyInstaller 缺上界 → 上界断言 + 越界必须被拒；
  P3-1  pet_chat.last_updated 无时区 → 必须带 ±HHMM 且能被 strptime("%z") 解析；
  P3-2  CI 不锁 pytest → ci.yml 必须与 lock 同版本，且安装行不许出现裸 pytest；
  P3-3  pet_export 依赖 zipfile 私有属性 _compresslevel → "换压缩级别必须换产出字节"
        反证它仍被消费（属性被改名/改语义 → 两个级别会写出相同字节 → 红）；
  P3-4  pet_io._almost_utf8 极小文件退化 → 文档说明 + 边界行为（纯西文小文件仍被拒）；
  口径   README（中/英）的类型注解表格必须与 AST 实测数字一致，防止再写成"全仓完成"。
"""
import ast
import datetime
import json
import os
import re
import sys
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pet_balance  # noqa: E402
import pet_chat  # noqa: E402
import pet_export  # noqa: E402
import pet_io  # noqa: E402
import pet_widgets  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
# v2.4.3（兼容审查 M3）：依赖区间口径的单一来源（不再在本文件手写包名清单）
from helpers_deps_bounds import (lock_text, parse_version, satisfies,  # noqa: E402
                                specs as req_specs, requirements_text)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANNOTATED_MODULES = ("pet_tools.py", "pet_lines.py", "pet_io.py", "pet_book.py")


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


# ===================== P1-1：balance worker =====================

class _Signal(object):
    """最小信号替身：记录 emit 实参；boom 非 None 时模拟"打到已删除的 C++ 对象"。"""

    def __init__(self, boom=None):
        self.calls = []
        self.boom = boom

    def emit(self, *args):
        self.calls.append(args)
        if self.boom is not None:
            raise self.boom


class _Signals(object):
    def __init__(self, updated_boom=None, err_boom=None):
        self.balance_updated = _Signal(updated_boom)
        self.balance_err = _Signal(err_boom)


class _Pet(object):
    """BalanceService 只用到这几个守卫状态（语义与 PetWindow 一致）。"""

    def __init__(self, closing=False, fetching=True):
        self._closing = closing
        self._fetching_balance = fetching
        self._manual_pending = False


def _service(pet, signals, logs):
    return pet_balance.BalanceService(
        pet, signals, lambda: {"api_key": "k"}, lambda: None,
        lambda *a: None, lambda *a: None, logs.append, lambda: None)


def _deleted_cpp():
    return RuntimeError("wrapped C/C++ object of type PetWindow has been deleted")


def test_worker_emits_result_and_resets_guard_on_success():
    pet, logs = _Pet(), []
    signals = _Signals()
    svc = _service(pet, signals, logs)
    svc._request_balance = lambda key: (True, (1.5, "CNY", 0.25))
    svc._worker("k")
    assert signals.balance_updated.calls == [(1.5, "CNY", 0.25)]
    assert signals.balance_err.calls == []
    assert pet._fetching_balance is False, "成功路径也必须复位在途守卫"


def test_worker_emits_err_and_resets_guard_on_http_failure():
    pet, logs = _Pet(), []
    signals = _Signals()
    svc = _service(pet, signals, logs)
    svc._request_balance = lambda key: (False, "timeout")
    svc._worker("k")
    assert signals.balance_err.calls == [()]
    assert signals.balance_updated.calls == []
    assert pet._fetching_balance is False
    assert any("timeout" in m for m in logs)


def test_worker_survives_request_exception_and_resets_guard():
    """_request_balance 之后的某行在 try 外抛时，守卫此前会永真卡死。"""
    pet, logs = _Pet(), []
    signals = _Signals()
    svc = _service(pet, signals, logs)

    def boom(key):
        raise ValueError("worker 内部的意外异常")

    svc._request_balance = boom
    svc._worker("k")                     # 修复前：异常直接冲出 daemon 线程
    assert pet._fetching_balance is False, "异常路径泄漏了 _fetching_balance（查询会被永久挡住）"
    assert signals.balance_err.calls == [()], "异常路径必须补发 balance_err"
    assert any("crashed" in m for m in logs)


def test_worker_survives_emit_on_deleted_object():
    """PetWindow 已销毁时 emit 会抛 RuntimeError——不许冲出 worker，且守卫要复位。"""
    pet, logs = _Pet(), []
    signals = _Signals(updated_boom=_deleted_cpp())
    svc = _service(pet, signals, logs)
    svc._request_balance = lambda key: (True, (2.0, "CNY", 0.0))
    svc._worker("k")                     # 修复前：RuntimeError 从 daemon 线程冒出
    assert pet._fetching_balance is False
    assert any("balance emit balance_updated failed" in m for m in logs)


def test_worker_survives_both_signals_raising():
    """两个信号都打在已销毁对象上（退出时序竞态）：worker 仍不许抛，守卫仍复位。"""
    pet, logs = _Pet(), []
    signals = _Signals(updated_boom=_deleted_cpp(), err_boom=_deleted_cpp())
    svc = _service(pet, signals, logs)
    svc._request_balance = lambda key: (False, "boom")
    svc._worker("k")
    svc._worker("k")                     # 幂等：再来一次也不许抛
    assert pet._fetching_balance is False


def test_worker_does_not_emit_while_closing():
    """退出中（_closing=True）：emit 端此前不判，会把信号打到正在销毁的窗口上。"""
    pet, logs = _Pet(closing=True), []
    signals = _Signals()
    svc = _service(pet, signals, logs)
    svc._request_balance = lambda key: (True, (3.0, "CNY", 0.0))
    svc._worker("k")
    assert signals.balance_updated.calls == [], "退出中不该再 emit 余额结果"
    assert pet._fetching_balance is False

    pet2, signals2 = _Pet(closing=True), _Signals()
    svc2 = _service(pet2, signals2, [])
    svc2._request_balance = lambda key: (False, "boom")
    svc2._worker("k")
    assert signals2.balance_err.calls == [], "退出中不该再 emit 错误"


def test_refresh_resets_guard_when_thread_start_fails(monkeypatch):
    """refresh() 自己也要兜住 start() 的异常（复审 M1）。

    Windows 线程/句柄耗尽、解释器关闭期，threading.Thread.start() 真会抛
    RuntimeError("can't start new thread")。此前那两行（置标志 + start）不在 try 里：
    标志恒真 → 此后 refresh 一个线程都起不来、只置 _pending_manual=True → 症状与 P1-1
    的守卫泄漏**一模一样**（点"查询余额"毫无反应），而泄漏点在 worker 之外，finally 兜不住。

    能真失败：把 refresh() 里的 try/except 拿掉 → 异常冲出 refresh（调用方是 Qt 槽，
    只会被吞掉），三条断言全红。
    """
    pet, logs = _Pet(fetching=False), []
    signals = _Signals()
    svc = _service(pet, signals, logs)

    class _DeadThread(object):
        def __init__(self, *a, **k):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(pet_balance.threading, "Thread", _DeadThread)
    svc.refresh(manual=True)                    # 不许抛
    assert pet._fetching_balance is False, "start() 抛了却没复位在途守卫（此后一次都起不来）"
    assert signals.balance_err.calls == [()], "启动失败要补发 balance_err"
    assert any("thread start failed" in m for m in logs), logs
    # 反例对照：start() 正常时照旧走原路径（别把守卫改成永远复位）
    monkeypatch.undo()
    started = []

    class _GoodThread(object):
        def __init__(self, target=None, args=(), **k):
            started.append((target, args))

        def start(self):
            started.append("start")

    monkeypatch.setattr(pet_balance.threading, "Thread", _GoodThread)
    svc.refresh(manual=False)
    assert pet._fetching_balance is True and started[-1] == "start", started


def test_closing_flag_renamed_does_not_silently_drop_results():
    """L①：`_closing` 读不到（属性**不存在**）不该被当成"在退出"而永久丢弃结果。

    能真失败：把 _closing() 退回 `bool(self.pet._closing)`（属性不存在 → AttributeError →
    兜底 True）→ 第一条断言红（emit 被丢掉且一行日志都没有）。
    """
    class _Renamed(object):
        def __init__(self):
            self._fetching_balance = True
            self._manual_pending = False
            # 故意没有 _closing（模拟哪天被改名/搬家）

    pet, logs = _Renamed(), []
    signals = _Signals()
    svc = _service(pet, signals, logs)
    svc._request_balance = lambda key: (True, (1.0, "CNY", 0.0))
    svc._worker("k")
    assert signals.balance_updated.calls == [(1.0, "CNY", 0.0)],         "属性改名后余额结果被静默丢弃了（_closing 兜底方向反了）"
    assert pet._fetching_balance is False


def test_worker_treats_unreadable_closing_flag_as_closing():
    """pet 已被销毁（取属性就抛）时按"在退出"处理：不发、不抛、守卫照样复位。"""
    class _Gone(object):
        """pet 已被销毁的替身：连 _closing 都读不出来（属性访问直接抛）。"""

        def __init__(self):
            self._fetching_balance = True
            self._manual_pending = False

        @property
        def _closing(self):
            raise _deleted_cpp()

    pet, logs = _Gone(), []
    signals = _Signals()
    svc = _service(pet, signals, logs)
    svc._request_balance = lambda key: (True, (1.0, "CNY", 0.0))
    svc._worker("k")
    assert signals.balance_updated.calls == []
    assert pet._fetching_balance is False


def test_refresh_is_not_wedged_after_an_emit_failure(monkeypatch):
    """端到端：emit 炸过之后，守卫必须已放行——下一次 refresh 还得能真发请求。

    修复前 _fetching_balance 只在槽里复位，emit 一炸槽永远不跑 → 之后所有轮询/手动
    查询都被"在途"挡住（用户点"查询余额"毫无反应）。
    """
    class _InlineThread(object):
        """把 BalanceService 起的线程改成同步执行（本用例只关心状态机）。"""

        def __init__(self, target=None, args=(), daemon=None, **kw):
            self._target, self._args = target, args

        def start(self):
            self._target(*self._args)

    monkeypatch.setattr(pet_balance, "threading", types.SimpleNamespace(Thread=_InlineThread))
    calls = []

    class _PetWithKey(_Pet):
        pass

    pet = _PetWithKey(fetching=False)
    signals = _Signals(updated_boom=_deleted_cpp())
    svc = _service(pet, signals, [])
    svc._request_balance = lambda key: (calls.append(key) or (True, (1.0, "CNY", 0.0)))

    svc.refresh(manual=True)
    assert len(calls) == 1
    assert pet._fetching_balance is False, "emit 失败后守卫没放行：后续查询全被挡住"
    svc.refresh(manual=True)
    assert len(calls) == 2, "第二次 refresh 被永真的 _fetching_balance 挡住了"


def test_control_naked_worker_really_leaks():
    """控制组：修复前的写法（emit 裸露、无 finally）必须真的泄漏守卫/抛异常。

    这条保证上面几条断言不是空转——真把 try/finally 拿掉，行为就是这个样子。
    """
    pet = _Pet(fetching=True)
    signals = _Signals(updated_boom=_deleted_cpp())

    def naked_worker(key):               # v2.4.2 的写法
        ok, payload = True, (1.0, "CNY", 0.0)
        if ok:
            signals.balance_updated.emit(*payload)

    with pytest.raises(RuntimeError):
        naked_worker("k")
    assert pet._fetching_balance is True, "控制组失效：这就不是修复前那条路径了"


# ===================== P2-2：QFont 回退链 =====================

def _hardcoded_qfont_families(src):
    """源码里 QFont 直接用**字符串字面量族名**的地方 → [(行号, 族名)]。

    只看第一个位置参数是字符串常量的调用：QFont(list(UI_FONT_FAMILIES)) 这类不算。
    """
    out = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
        if name != "QFont" or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            out.append((node.lineno, first.value))
    return out


def _ui_font_calls(src):
    n = 0
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name == "ui_font":
                n += 1
    return n


def test_hardcoded_qfont_checker_can_fail():
    """控制组：硬编码检测器必须能认出坏样本（否则下面那条断言是空转）。"""
    bad = 'from PySide6.QtGui import QFont\nf = QFont("Microsoft YaHei", 9)\n'
    assert _hardcoded_qfont_families(bad) == [(2, "Microsoft YaHei")]
    good = 'from PySide6.QtGui import QFont\nf = QFont(list(UI_FONT_FAMILIES), 9)\n'
    assert _hardcoded_qfont_families(good) == []


def test_widgets_never_hardcode_a_font_family():
    src = _read("pet_widgets.py")
    hard = _hardcoded_qfont_families(src)
    assert hard == [], ("pet_widgets.py 仍有硬编码字体名（非中文 Windows 上会变方块）：%r" % (hard,))
    assert _ui_font_calls(src) >= 8, "8 处字体构造都应走 ui_font 助手"


def test_ui_font_uses_the_fallback_chain():
    fams = list(pet_widgets.UI_FONT_FAMILIES)
    assert len(fams) >= 3, "回退链太短：一个族不可用时没有后备"
    assert fams[0] == "Microsoft YaHei"
    assert "SimSun" in fams and "Arial Unicode MS" in fams
    f = pet_widgets.ui_font(9, QFont.Weight.Bold)
    assert list(f.families()) == fams, "QFont 没拿到整条族列表（Qt6 才支持列表重载）"
    assert f.pointSize() == 9
    assert f.weight() == QFont.Weight.Bold
    plain = pet_widgets.ui_font(12)
    assert plain.pointSize() == 12 and plain.weight() == QFont.Weight.Normal


# ---- v2.4.3（兼容审查 M1）：QSS 也是字体名的一部分，守卫必须覆盖全仓而不只是 pet_widgets ----

def _shipped_py_sources():
    """仓库根下的产品 .py（静态检查与发布流程读的就是这些）。"""
    out = {}
    for name in sorted(os.listdir(HERE)):
        if name.endswith(".py"):
            out[name] = _read(name)
    return out


def _font_family_declarations(text):
    """文本里所有 font-family 声明 → [(行号, 值)]（.py 里的 QSS 常量与独立 .qss 都适用）。"""
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        m = re.search(r"font-family\s*:\s*([^;}\n]+)", line)
        if m:
            out.append((i, m.group(1).strip()))
    return out


def _unfallback_font_declarations(text, token=None):
    """**单族**（没有逗号回退）的 font-family 声明 → [(行号, 值)]。

    token = "由单一来源注入"的占位符：它在源码里就该是单值，替换后才是整条链。
    """
    if token is None:
        token = pet_dialogs_qss_token()
    out = []
    for lineno, value in _font_family_declarations(text):
        if token and token in value:
            continue
        names = [p for p in value.split(",") if p.strip()]
        if len(names) < 2:
            out.append((lineno, value))
    return out


def pet_dialogs_qss_token():
    """对话框 QSS 的族占位符（从产品源码里取，避免测试另写一份字面量）。"""
    return "".join(re.findall(r'DIALOG_QSS_FONT_TOKEN = "([^"]+)"',
                              _read("pet_dialogs.py"))) or "__UI_FONT_FAMILIES__"


def _font_chain_comment(src):
    """UI_FONT_FAMILIES 上方的机理注释块（从"字体回退链"标题到常量定义）。"""
    start = src.find("字体回退链")
    end = src.find("UI_FONT_FAMILIES = ")
    return src[start:end] if 0 <= start < end else ""


def _unhedged_font_claims(text):
    """把"必现缺陷"式的绝对说法挑出来（复审 M4：措辞要用"可能"）。"""
    return [p for p in ("就回退到默认无衬线", "显示成", "会显示成方块") if p in text]


def test_font_fallback_mechanism_comment_is_hedged():
    """机理描述必须是"多一层候选 + 显式兜底（Qt 自身仍会做字体链接）"，用"可能"不用"不会"。

    审查实测（复审 M4）：候选族全不存在时 Qt 回退到 Tahoma 且 exactMatch()==False，
    但 inFontUcs4(0x4E2D)==True、advance("中") 仍是正常宽度 → **只要机器上还有任意一份
    CJK 字体就不会变方块**，新增链的成员也全是有 CJK 的族。旧注释把回退链写成了
    "修掉中文变方块这个必现缺陷"，属于把防御性加固说成缺陷修复。

    能真失败：把旧那句写回（"Qt 找不到该族就回退到默认无衬线 → 中文…显示成方块"）
    → "字体链接"缺失 + _unhedged_font_claims 非空 → 红。
    """
    text = _font_chain_comment(_read("pet_widgets.py"))
    assert text, "没找到 UI_FONT_FAMILIES 上方的机理注释块"
    assert "字体链接" in text, "注释没写 Qt 自身的字体链接（这才是中文不变方块的真正原因）"
    assert "可能" in text, "措辞要用'可能'，不能写成绝对断言"
    assert "多一层候选" in text or "显式兜底" in text, "没写清这是'多一层候选 + 显式兜底'"
    bad = _unhedged_font_claims(text)
    assert bad == [], "又把回退链写成了必现缺陷修复（命中绝对说法 %r）" % (bad,)
    # 控制组：旧那句必须被认出来（否则上面那条是空转）
    old = ("# 卸载中文字体的环境里，Qt 找不到该族就回退到默认无衬线 → 中文气泡与余额徽章显示成\n"
           "# **方块**（豆腐块）。")
    assert _unhedged_font_claims(old), "检测器认不出旧说法"
    assert "字体链接" not in old


def test_font_family_checker_can_fail():
    """控制组：单族声明必须被认出来（否则下面那条断言是空转）。"""
    bad = 'QDialog {\n    font-family: "Microsoft YaHei";\n}'
    assert _unfallback_font_declarations(bad) == [(2, '"Microsoft YaHei"')]
    good = 'QDialog { font-family: "Microsoft YaHei", "SimSun"; }'
    assert _unfallback_font_declarations(good) == []
    tok = "QDialog { font-family: __UI_FONT_FAMILIES__; }"
    assert _unfallback_font_declarations(tok) == []
    assert _font_family_declarations('QLabel { color: #fff; }') == []


def test_no_shipped_source_hardcodes_a_single_font_family():
    """**全仓**（不只 pet_widgets）：QSS 的 font-family 不许单族，QFont 不许吃字符串字面量。

    能真失败：把 DIALOG_QSS 改回 font-family: "Microsoft YaHei";（或把占位符换成字面量）
    → 红；把任一处 QFont("Microsoft YaHei", …) 写回 → 红。审查实测：此前这条守卫只读
    pet_widgets.py，pet_dialogs 里那 24 处 setStyleSheet 用的 QSS 谁也管不着。
    """
    offenders = {}
    for name, src in _shipped_py_sources().items():
        hard = _hardcoded_qfont_families(src)
        single = _unfallback_font_declarations(src)
        if hard or single:
            offenders[name] = {"QFont 字面量": hard, "单族 font-family": single}
    assert offenders == {}, "仍有硬编码/无回退的字体声明：%r" % (offenders,)


def test_dialog_qss_uses_the_single_source_fallback_chain():
    """对话框 QSS 的族列表必须**由 pet_widgets.UI_FONT_FAMILIES 拼出**（不是两处各写一份）。

    能真失败：把 DIALOG_FONT_FAMILY 换成字面量 "Microsoft YaHei"（两处会漂移）→ 红；
    把 QSS 末尾的 .replace(...) 拿掉（占位符残留、链根本没进 QSS）→ 红。
    """
    import pet_dialogs
    fams = list(pet_widgets.UI_FONT_FAMILIES)
    qss = pet_dialogs.DIALOG_QSS
    assert pet_dialogs.DIALOG_QSS_FONT_TOKEN not in qss, "QSS 里的族占位符没被替换掉"
    assert pet_dialogs._qss_font_family(fams) == pet_dialogs.DIALOG_FONT_FAMILY, \
        "DIALOG_FONT_FAMILY 不是由 UI_FONT_FAMILIES 拼出来的"
    assert len(fams) >= 3 and pet_dialogs.DIALOG_FONT_FAMILY.count(",") >= 2, \
        "QSS 的族列表太短：%r" % (pet_dialogs.DIALOG_FONT_FAMILY,)
    for fam in fams:
        assert fam in qss, "回退链成员 %r 没进 QSS（两处口径漂移了）" % fam
    # 反向：换一条链，QSS 必须跟着换（否则说明 QSS 是另写死的一份）
    assert pet_dialogs._qss_font_family(("A", "B")) == "A, B"
    assert pet_dialogs._qss_font_family(("Microsoft YaHei",)) == '"Microsoft YaHei"'
    # 含空格的族名要带引号，否则 QSS 解析器只认第一个词
    assert pet_dialogs._qss_font_family(("SimSun",)) == "SimSun"


# ===================== P2-3：依赖上界（口径在 helpers_deps_bounds 单一来源） =====================
# v2.4.3（兼容审查 M3）：本文件此前自己写了一份"要检查的包名"元组，与
# test_deps_bounds_v24.py 的 NEED_BOUNDS 各写一份——新增依赖要改两处，漏一处就永远
# 不红（pytest 就是这么漏的）。现在解析与"必须有上界"的规则都来自
# tests/helpers_deps_bounds.py（那里的口径是"requirements.txt 里每个包都要有上界"），
# 本文件只钉 requests / PyInstaller 这两个**具体上界的数值**。

def test_requests_and_pyinstaller_have_upper_bounds():
    specs = req_specs(requirements_text())
    for name in ("requests", "PyInstaller"):
        key = name.lower()
        assert key in specs, "requirements.txt 没有声明 %s" % name
        bounds = dict(specs[key])
        assert "<" in bounds, "%s 没有上界（全新环境可能装到未验证的大版本）" % name
        assert ">=" in bounds, "%s 的下界被弄丢了" % name
    assert parse_version(dict(specs["requests"])["<"]) == (3,)
    assert parse_version(dict(specs["pyinstaller"])["<"]) == (7,)


def test_lock_versions_fit_inside_the_new_bounds():
    specs = req_specs(requirements_text())
    lock = req_specs(lock_text())
    for name in ("requests", "PyInstaller"):
        key = name.lower()
        assert key in lock, "lock 里没有 %s 的实测版本" % name
        pinned = [v for op, v in lock[key] if op == "=="]
        assert pinned, "lock 里 %s 不是精确锁定" % name
        assert satisfies(pinned[0], specs[key]), \
            "lock 的 %s==%s 落在 requirements.txt 区间之外" % (name, pinned[0])


def test_bound_checker_rejects_out_of_range_versions():
    """控制组：上界必须真的能拒——越界版本被判过关的话上面两条形同虚设。"""
    specs = req_specs(requirements_text())
    assert not satisfies("3.0.0", specs["requests"])
    assert not satisfies("2.27", specs["requests"])
    assert not satisfies("7.0", specs["pyinstaller"])
    assert not satisfies("5.9", specs["pyinstaller"])
    assert satisfies("2.34.2", specs["requests"])
    assert satisfies("6.22.2", specs["pyinstaller"])


# ===================== P3-2：CI 锁 pytest =====================

_BARE_PYTEST = re.compile(r"(?<![\w=])pytest(?!\s*==)")


def test_ci_pins_pytest_to_the_lock_version():
    ci = _read(os.path.join(".github", "workflows", "ci.yml"))
    lock = _read("requirements-lock.txt")
    m = re.search(r"^pytest==([0-9][0-9A-Za-z.\-]*)$", lock, re.M)
    assert m, "requirements-lock.txt 里没有锁定 pytest"
    want = "pytest==%s" % m.group(1)
    assert want in ci, "CI 没把 pytest 锁到 lock 的版本（%s）" % want
    installs = [ln for ln in ci.splitlines() if "pip install" in ln]
    assert installs, "没找到 CI 的 pip install 行"
    for ln in installs:
        assert not _BARE_PYTEST.search(ln), "CI 安装行里还有未锁版本的 pytest：%r" % ln


def test_bare_pytest_detector_can_fail():
    assert _BARE_PYTEST.search("pip install Pillow==12.1.1 pytest")
    assert not _BARE_PYTEST.search("pip install Pillow==12.1.1 pytest==9.1.1")


# ===================== P3-1：last_updated 时区 =====================

def test_last_updated_carries_timezone_offset(tmp_path):
    path = str(tmp_path / "memory.json")
    lt = pet_chat.write_long_term(path, {"preferences": ["香菜"]}, max_entries=3)
    stamp = lt["last_updated"]
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{4}$", stamp), \
        "last_updated 没有时区偏移：%r" % (stamp,)
    dt = datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S%z")
    assert dt.utcoffset() is not None
    assert stamp in _read_text(path), "落盘的 last_updated 与返回值不一致"


def _read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ===================== P3-3：zipfile 私有属性仍被消费 =====================

def _big_plan(tmp_path):
    """一个能过 validate_bundle 的 plan：**唯一**的条目就是跨片写的大素材。

    为什么只留一条：小条目走 stdlib 的 zf.write()（它自己会设私有属性），会把"大条目
    有没有设 _compresslevel"的差异盖住——那样本用例会变成空转（第一版就是这样，
    _dev/mutate_check.py 的 M-A10 变异没被抓到，见回报）。整包字节比较必须只被
    大条目的压缩结果影响。
    """
    roles = tmp_path / "roles"
    roles.mkdir(exist_ok=True)
    big = roles / "f00.png"
    big.write_bytes(b"abcdefghij" * 40000)          # 400KB 可压缩内容（级别差异看得见）
    assert os.path.getsize(str(big)) > pet_export._BIG_ENTRY_MIN_BYTES
    manifest = {"format": pet_export.BUNDLE_FORMAT, "version": pet_export.BUNDLE_VERSION,
                "role": {"id": "r3a", "name": "第三轮 A", "file": "f00.png",
                         "form": "single", "file_full": "", "frames": ["f00.png"],
                         "added": "", "forms": [{"name": "常态", "file": "f00.png",
                                                 "front": "f00.png",
                                                 "animations": {"idle": ["f00.png"]}}]},
                "behaviors": [], "config": {}, "excluded": [], "alarms": []}
    return {"manifest": manifest, "entries": [("roles/f00.png", str(big))]}


def _write_with_level(tmp_path, plan, level, name):
    """按片驱动写出一个包；返回 (整包字节, _big_begin 调用次数)。"""
    out = str(tmp_path / name)
    w = pet_export.BundleWriter(plan, out, compresslevel=level)
    stats = {"big": 0}
    real_begin = w._big_begin

    def spy(arc, src):
        stats["big"] += 1
        return real_begin(arc, src)

    w._big_begin = spy
    guard = 0
    while not w.done:
        w.step(budget_ms=0.5)
        guard += 1
        assert guard < 200, "分片驱动没有收敛（测试自身兜底）"
    ok, err = w.finish()
    assert ok, err
    with open(out, "rb") as f:
        return f.read(), stats["big"]


def test_zipinfo_compresslevel_is_still_consumed(tmp_path):
    """私有属性 _compresslevel 必须仍被 CPython 消费：换级别 → 产出字节必须不同。

    能真失败：删掉 pet_export._big_begin 里的 "zinfo._compresslevel = ..."（或未来某个
    Python 版本不再读它），zinfo 就退回默认级别（None → zlib 6），1 与 9 两个级别写出
    完全相同的字节 → 本用例红（这正是报告 P3-3 担心的静默失效）。
    """
    plan = _big_plan(tmp_path)
    b1, big1 = _write_with_level(tmp_path, plan, 1, "lvl1.zip")
    b9, big9 = _write_with_level(tmp_path, plan, 9, "lvl9.zip")
    assert big1 >= 1 and big9 >= 1, "大条目没走 _big_begin：这条用例没验证到私有属性那条路径"
    assert b1 != b9, "压缩级别没有生效：zipfile 私有属性 _compresslevel 已不再被消费"
    assert len(b1) != len(b9)
    # 双保险：直接看**大条目**的压缩尺寸（整包字节里还混着 manifest 等固定内容）
    import zipfile
    with zipfile.ZipFile(str(tmp_path / "lvl1.zip")) as z1, \
            zipfile.ZipFile(str(tmp_path / "lvl9.zip")) as z9:
        assert z1.getinfo("roles/f00.png").compress_size != \
            z9.getinfo("roles/f00.png").compress_size, \
            "大条目的压缩尺寸不随级别变：_compresslevel 没被消费"


def test_zipinfo_still_has_the_private_attribute():
    """依赖存在性前置断言：属性被改名时给出直白原因（而不是只在字节比较里变红）。"""
    import zipfile
    zi = zipfile.ZipInfo("x")
    assert hasattr(zi, "_compresslevel"), "CPython 的 ZipInfo 已经没有 _compresslevel 了"
    assert zi._compresslevel is None, "默认值变了：产出字节口径要重新对拍"


# ===================== P3-4：_almost_utf8 极小文件退化 =====================

def test_tiny_western_file_is_not_almost_utf8():
    """<200 字节时段数上限退化为 1，但判据二仍须把纯西文小文件挡住。"""
    raw = b"caf\xe9 price 12.00"
    assert len(raw) < 200
    assert pet_io._almost_utf8(raw) is False, "纯西文小文件被误判成坏 UTF-8（会按 GBK 读成乱码）"
    tiny_cn = "中文测试".encode("utf-8")[:-1]        # 截断尾巴：1 个损坏段 + 3 个完好汉字
    assert len(tiny_cn) < 200
    assert pet_io._almost_utf8(tiny_cn) is True, "极小文件里的坏 UTF-8 中文应仍能被救回"


def test_almost_utf8_documents_the_small_file_degradation():
    doc = pet_io._almost_utf8.__doc__ or ""
    assert "退化" in doc, "极小文件退化这条已知取舍必须有文档说明（报告 P3-4）"
    src = _read("pet_io.py")
    assert "极小文件会退化" in src, "常量区的退化说明丢了"


# ===================== 口径：README 注解表格必须与实测一致 =====================

def _annotation_counts(name):
    """(带返回注解的函数数, 函数总数)。"""
    tree = ast.parse(_read(name))
    tot = ret = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            tot += 1
            ret += 1 if node.returns is not None else 0
    return ret, tot


def _readme_rows(text):
    """README 注解表格 → {模块名: (已注解, 总数)}。

    v2.4.3（质量审查 M1）：两类行都解析——
      · ✅/⚠️ 行：`| `mod.py` | ✅ 39/39 | …` → (39, 39)；
      · ❌ 行：同一格里并排多个模块，`` `桌宠.py`（253 函数）/ `pet_dialogs.py`（251） ``
        → (0, N)（英文 README 是 `(253 funcs)`，中英括号都要认）。
    此前只认 ✅/⚠️ 且只对 ANNOTATED_MODULES 取，`桌宠.py`（248 函数）那一行**没有任何
    用例看着**：实测把 248 改成 999，两条 README 用例都过。
    """
    out = {}
    for name in ANNOTATED_MODULES:
        m = re.search(r"\|\s*`%s`\s*\|\s*(?:✅|⚠️)\s*(\d+)/(\d+)" % re.escape(name), text)
        if m:
            out[name] = (int(m.group(1)), int(m.group(2)))
    for line in text.splitlines():
        if not line.lstrip().startswith("|") or "❌" not in line:
            continue
        for mod, num in re.findall(r"`([A-Za-z0-9_.\u4e00-\u9fff\-]+\.py)`\s*[（(]\s*(\d+)",
                                   line):
            out.setdefault(mod, (0, int(num)))
    return out


def test_readme_annotation_scope_matches_the_code():
    """README 里的 注解数/函数数 必须是 AST 实测值（防表格过期 / 又写成"全仓完成"）。

    v2.4.3（质量审查 M1）：❌ 行里点名的大文件同样要被 AST 核对（此前那行无人守）。
    """
    for readme in ("README.md", "README.en.md"):
        rows = _readme_rows(_read(readme))
        assert set(rows) >= set(ANNOTATED_MODULES), \
            "%s 的注解表格缺模块：%r" % (readme, sorted(set(ANNOTATED_MODULES) - set(rows)))
        # 口径澄清的核心就是这三个大文件：必须在表里被点名（且数字要被核对）
        for big in ("桌宠.py", "pet_dialogs.py"):
            assert big in rows, ("%s 的表格没有点名 %s 的函数总数（大文件口径无人守）"
                                 % (readme, big))
        for name, (claimed_ret, claimed_tot) in rows.items():
            got = _annotation_counts(name)
            assert (claimed_ret, claimed_tot) == got, \
                "%s 里 %s 写成 %d/%d，实际是 %d/%d" % (readme, name, claimed_ret, claimed_tot,
                                                        got[0], got[1])


def test_readme_says_the_big_files_are_not_done():
    zh = _read("README.md")
    assert "类型注解口径" in zh
    assert "单独立项" in zh and "桌宠.py" in zh and "pet_dialogs.py" in zh
    assert "82/82" in zh, "必须点名澄清 v2.4.1 那句 82/82 的口径，否则还会被误读"
    en = _read("README.en.md")
    assert "Type-annotation scope" in en and "82/82" in en and "pet_dialogs.py" in en


def test_module_docstrings_state_the_annotation_scope():
    """口径也要写在代码里：读 pet_io / pet_chat 头注释的人不该被"82/82"误导。"""
    for mod in (pet_io, pet_chat):
        doc = mod.__doc__ or ""
        assert "类型注解口径" in doc, "%s 的模块注释没写注解口径" % mod.__name__
        assert "单独立项" in doc, "%s 的注释没说清大文件是单独立项" % mod.__name__
        assert "82" in doc, "%s 的注释没点名澄清 82/82 那句口径" % mod.__name__


def test_readme_row_parser_can_fail():
    """控制组：表格解析器认不出被改坏的表格（否则上面的断言是空转）。"""
    good = "| `pet_tools.py` | ✅ 39/39 | x |"
    assert _readme_rows(good) == {"pet_tools.py": (39, 39)}
    assert _readme_rows("| pet_tools.py | 39/39 |") == {}
    # v2.4.3（M1）：❌ 行里的 "(N 函数)" 也要解析，中英两种括号都要认
    zh = "| `桌宠.py`（253 函数）/ `pet_dialogs.py`（251） | ❌ 0 | x |"
    assert _readme_rows(zh) == {"桌宠.py": (0, 253), "pet_dialogs.py": (0, 251)}
    en = "| `桌宠.py` (253 funcs) / `pet_dialogs.py` (251) | ❌ 0 | x |"
    assert _readme_rows(en) == {"桌宠.py": (0, 253), "pet_dialogs.py": (0, 251)}
    # 没写数字的行不许瞎猜（"❌ 0" 那格本身不是函数总数）
    assert _readme_rows("| `pet_chat.py` / `pet_balance.py` | ❌ 0 | x |") == {}
    # ✅ 行不能把 ❌ 行的数字吸进来，反之亦然
    assert _readme_rows(good + chr(10) + zh) == {"pet_tools.py": (39, 39),
                                                 "桌宠.py": (0, 253),
                                                 "pet_dialogs.py": (0, 251)}
