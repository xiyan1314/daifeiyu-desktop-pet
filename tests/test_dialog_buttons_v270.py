# -*- coding: utf-8 -*-
"""v2.7.0 第 5 轮（代理 A）：对话框按钮接线契约 + 「导出角色包」P0 端到端。

背景（_dev/audit_buttons_binding_v270.md §0）：全仓 123 个按钮类控件里**只有两处零接线**
—— pet_dialogs.py:5809/5810 的「继续导出 / 取消」。v2.5.0 B 把这段抽成工厂
（build_role_meta_dialog）时把 clicked.connect 丢了：pick_role_meta 进 modal() 的嵌套
事件循环后**关不掉窗口**，导出角色包必现不可用（连取消都点不动）。
尺寸契约（tests/test_dialog_fit_v250.py）只量几何、从不点按钮，所以这类缺陷
**没有任何用例能发现**——本文件补的就是这条结构性防线。

两半：
  1. AST 契约：pet_dialogs.py 里每个 QPushButton/QToolButton 必须"有 clicked/toggled
     接线"或"在显式白名单里并写明理由"；每个 QCheckBox/QRadioButton 必须登记成状态输入，
     而且**真的被 .isChecked()/.checkState() 读过**（白名单不许变成垃圾桶，见
     test_state_inputs_... 的反向断言）。
  2. P0 端到端：真点按钮（QPushButton.click() 不需要 show），断言 result() 与返回值。
     **禁止真 exec()**：offscreen 下 modal() 会挂死整个测试进程——这里把 modal() 换成
     "点一下再读结果"。

变异（把修复注释掉必须红，已实测，见本轮回报）：
  · 注释掉 build_role_meta_dialog 里的 btn_ok/btn_cancel 两条 connect →
    test_role_meta_ok_button_accepts / test_role_meta_cancel_button_rejects /
    test_every_action_button_is_wired_or_whitelisted 三条全红；
  · 把任一条 QCheckBox 从 _STATE_INPUTS 删掉 → test_state_inputs_... 红；
  · 把扫描器改成永远返回 [] → 本文件 4 条用例全红（有非空下限断言）。
"""
import ast
import io
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pet_dialogs  # noqa: E402

from PySide6.QtWidgets import QDialog, QPushButton  # noqa: E402


SRC_PATH = os.path.join(ROOT, "pet_dialogs.py")

# 需要 clicked 接线的"动作按钮"（点一下就该发生点什么）
_ACTION_CLASSES = ("QPushButton", "QToolButton")
# 状态输入（值由保存路径主动读，不需要接线）
_STATE_CLASSES = ("QCheckBox", "QRadioButton")
_SIGNALS = ("clicked", "pressed", "released", "toggled", "stateChanged")

# 显式白名单：**确实不需要接线**的动作按钮。键 = 源码里的句柄名，值 = 为什么不需要。
# 目前为空：pet_dialogs.py 里每一个 QPushButton 都有动作（逐条见下面的 AST 契约）。
# 加白名单必须同时写理由 —— 否则 test_..._whitelist_is_justified 会红。
_ACTION_WHITELIST = {}

# 状态输入白名单：键 = 源码里的句柄名，值 = 为什么可以没有 clicked.connect。
# 判据不止"写了理由"：test_state_inputs_... 还会断言这个句柄**真的**被
# .isChecked()/.checkState() 读过（照抄 _dev/audit_buttons_binding_v270.md §3.1 的 15 条）。
_STATE_INPUTS = {
    "self._adv_rmbg": "导入选项「自动去背景」：值由 _collect_options 的 .isChecked() 读",
    "self._adv_trim": "导入选项「裁剪透明边距」：同上，状态输入",
    "self._adv_keep": "导入选项「保留原图」：同上，状态输入",
    "self._ck_sleep_form": "形态标记「睡觉形态」：批量循环读 .isChecked()",
    "self._ck_transform_form": "形态标记「变身形态」：批量循环读 .isChecked()",
    "self._ck_no_feed": "形态标记「不参与喂食」：批量循环读 .isChecked()",
    "self._ck_enabled": "闹钟「启用」：保存时读 .isChecked()",
    "self._tools_confirm": "AI「写入类操作先问我」：保存时读 .isChecked()",
    "self._rag": "AI 隐私开关 ai_rag_enabled：保存时读 .isChecked()",
    "self._ceil": "物理「顶边也反弹」：保存时读 .isChecked()",
    "self._en": "语音总开关：保存时读 .isChecked()",
    "self._daily": "语音「日常台词也用配音」：保存时读 .isChecked()",
    "self._lauto": "后端「自动拉起」：保存时读 .isChecked()",
    "self._lkill": "后端「退出时结束」：保存时读 .isChecked()",
    "self._resume": "待机「被打断算已消费」：保存时读 .isChecked()",
}


# ---------------- AST 扫描器（与 _dev 审计同一口径：方法作用域内查接线） ----------------

class _Ctl(object):
    __slots__ = ("lineno", "cls", "label", "target", "wired")

    def __init__(self, lineno, cls, label, target, wired):
        self.lineno = lineno
        self.cls = cls
        self.label = label
        self.target = target
        self.wired = wired

    def __repr__(self):
        return "%s(%s)@%d target=%r wired=%s" % (
            self.cls, self.label, self.lineno, self.target, self.wired)


def _norm(expr):
    """句柄表达式 → 规范化名字（self._b / b / None）。"""
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        base = _norm(expr.value)
        return None if base is None else base + "." + expr.attr
    return None


def _cls_name(call):
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)


def scan_controls(src):
    """扫描源码 → [_Ctl]。**方法作用域**内匹配"创建点"与"接线点"。

    能认的形态：x = QPushButton(...) 后 x.clicked.connect(...)；self._b = ... 后
    self._b.clicked.connect(...)；以及内联 QPushButton(...).clicked.connect(...)。
    认不出的（容器/返回值/跨方法传递）一律**报成未接线**——宁可要人补白名单，
    也不能让"抽成工厂时丢接线"这种缺陷溜过去。
    """
    tree = ast.parse(src)
    scopes = []

    def _collect(node, cur):
        for ch in ast.iter_child_nodes(node):
            nxt = cur
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                nxt = {"wired": set(), "inline": set()}
                scopes.append(nxt)
            _collect(ch, nxt)
        return cur

    mod = {"wired": set(), "inline": set()}
    scopes.append(mod)

    # 作用域映射：最内层 FunctionDef 优先
    def _map(node, cur, out):
        out[id(node)] = cur
        for ch in ast.iter_child_nodes(node):
            nxt = cur
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                nxt = {"wired": set(), "inline": set()}
            _map(ch, nxt, out)
    scope_of = {}
    _map(tree, mod, scope_of)

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "connect"):
            continue
        val = node.func.value
        if not (isinstance(val, ast.Attribute) and val.attr in _SIGNALS):
            continue
        sc = scope_of.get(id(node)) or mod
        nm = _norm(val.value)
        if nm is not None:
            sc["wired"].add(nm)
        if isinstance(val.value, ast.Call):
            sc["inline"].add(id(val.value))

    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        cname = _cls_name(node)
        if cname not in _ACTION_CLASSES + _STATE_CLASSES:
            continue
        sc = scope_of.get(id(node)) or mod
        target = None
        for parent in ast.walk(tree):
            if isinstance(parent, ast.Assign) and parent.value is node and len(parent.targets) == 1:
                target = _norm(parent.targets[0])
                break
        label = ""
        if node.args and isinstance(node.args[0], ast.Constant):
            label = str(node.args[0].value)
        elif node.args:
            label = "<动态文案>"
        wired = (target is not None and target in sc["wired"]) or id(node) in sc["inline"]
        out.append(_Ctl(node.lineno, cname, label, target, wired))
    out.sort(key=lambda c: c.lineno)
    return out


def _source():
    return io.open(SRC_PATH, encoding="utf-8").read()


def _use_counts(src):
    """句柄名 → 在源码里出现的次数（创建点算 1 次）。用于"这个控件真的被用过吗"。"""
    out = {}
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.Name, ast.Attribute)):
            nm = _norm(node)
            if nm:
                out[nm] = out.get(nm, 0) + 1
    return out


def _unwired(ctls):
    return [c for c in ctls if not c.wired]


# ---------------- 1. 通用契约 ----------------

def test_scanner_is_not_vacuous():
    """扫描器本身不是空转：合成源码里"零接线的按钮"必须被报出来，接了的必须不报。

    变异：把 scan_controls 改成永远返回 [] → 本用例红。
    """
    synth = ('from PySide6.QtWidgets import QPushButton\n\n\n'
             'def build(dlg):\n'
             '    ok = QPushButton("继续导出")\n'
             '    dlg.addWidget(ok)\n')
    got = _unwired(scan_controls(synth))
    assert len(got) == 1 and got[0].label == "继续导出", "扫描器没认出未接线按钮：%r" % (got,)
    synth2 = synth + '    ok.clicked.connect(dlg.accept)\n'
    assert _unwired(scan_controls(synth2)) == [], "接了线的按钮被误报成未接线"
    # 别名/内联两种形态也要认
    synth3 = ('from PySide6.QtWidgets import QPushButton\n\n\n'
              'def build(dlg):\n'
              '    QPushButton("x").clicked.connect(dlg.accept)\n')
    assert _unwired(scan_controls(synth3)) == [], "内联接线的按钮被误报"


def test_every_action_button_is_wired_or_whitelisted():
    """pet_dialogs.py 里每个动作按钮都必须有 clicked/toggled 接线或在白名单里。

    变异：注释掉 build_role_meta_dialog 的 btn_ok/btn_cancel 两条 connect → 本用例红
    （这正是 :5809/:5810 的修复前状态）。
    """
    ctls = scan_controls(_source())
    actions = [c for c in ctls if c.cls in _ACTION_CLASSES]
    # 下限断言：扫描器一旦退化（比如解析不了源码）这里立刻红，而不是"零控件全绿"
    assert len(actions) >= 60, "只扫到 %d 个动作按钮，扫描器失效了？" % len(actions)
    bad = [c for c in actions
           if not c.wired and c.target not in _ACTION_WHITELIST]
    assert bad == [], (
        "这些按钮零接线（点了没反应——见 _dev/audit_buttons_binding_v270.md）：\n%s\n"
        "修法：补 <句柄>.clicked.connect(...)，或在 _ACTION_WHITELIST 里写明"
        "「为什么可以没有接线」。" % "\n".join(
            "  pet_dialogs.py:%d %s %r" % (c.lineno, c.cls, c.label) for c in bad))


def _whitelist_problems(ctls, whitelist):
    """白名单自检（纯函数，便于自证不空转）：返回问题列表，空 = 绿。

    双向：① 每条都要写理由；② 条目对应的控件必须**还在源码里**（防白名单烂掉）；
    ③ 已经接线的控件不该挂在白名单上（防白名单变成垃圾桶）。
    """
    by_target = {c.target: c for c in ctls if c.target}
    problems = []
    for name, why in sorted(whitelist.items()):
        if not str(why or "").strip():
            problems.append("白名单条目 %r 没写理由" % (name,))
            continue
        c = by_target.get(name)
        if c is None:
            problems.append("白名单条目已失效（源码里没有这个控件了）：%r" % (name,))
        elif c.wired:
            problems.append("%r 已经接线了，应该从白名单里删掉" % (name,))
    return problems


def test_action_whitelist_checker_is_not_vacuous():
    """白名单检查器双向可证：真白名单干净；合成反例（空理由/失效/已接线）必须被报出来。

    变异：让 _whitelist_problems 无论输入都返回 [] → 本用例红。
    """
    ctls = scan_controls(_source())
    assert _whitelist_problems(ctls, _ACTION_WHITELIST) == [], (
        "真白名单本身不干净：%r" % (_whitelist_problems(ctls, _ACTION_WHITELIST),))
    wired = [c.target for c in ctls if c.cls in _ACTION_CLASSES and c.wired and c.target]
    assert wired, "源码里找不到任何已接线的按钮，合成反例做不了"
    assert _whitelist_problems(ctls, {"self.这个控件不存在": "随便写个理由"}), (
        "失效条目没被报出来（白名单会越积越脏）")
    assert _whitelist_problems(ctls, {wired[0]: "   "}), "没写理由的条目没被报出来"
    assert _whitelist_problems(ctls, {wired[0]: "它已经有动作了"}), (
        "已接线的控件挂在白名单上却没被报出来")
    idle = [c.target for c in ctls if c.cls in _STATE_CLASSES and not c.wired and c.target]
    assert idle, "源码里找不到未接线的勾选框，合成反例做不了"
    assert _whitelist_problems(ctls, {idle[0]: "状态输入：值由保存路径读"}) == [], (
        "该绿的情况被误报（检查器方向反了）")


def test_state_inputs_are_declared_and_actually_read():
    """QCheckBox/QRadioButton 必须登记成状态输入，且**真的被读过**。

    变异：把任一条从 _STATE_INPUTS 删掉 → 本用例红（白名单真的在生效）。
    """
    src = _source()
    ctls = scan_controls(src)
    checks = [c for c in ctls if c.cls in _STATE_CLASSES]
    assert len(checks) >= 10, "只扫到 %d 个状态输入，扫描器失效了？" % len(checks)
    # 有 toggled 接线的（联动别的控件）已经"接上了"，不要求登记；
    # 没有接线的**必须**登记成状态输入，并说明值由哪里读。
    undeclared = [c for c in checks if not c.wired and c.target not in _STATE_INPUTS]
    assert undeclared == [], (
        "这些勾选框既没有 clicked/toggled 接线也没登记成状态输入：\n%s"
        % "\n".join("  pet_dialogs.py:%d %s %r" % (c.lineno, c.cls, c.label)
                     for c in undeclared))
    # 白名单不许变成垃圾桶：每条"状态输入"都必须真的被读过（或至少被引用过第二次）
    uses = _use_counts(src)
    tree = ast.parse(src)
    read = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("isChecked", "checkState"):
            nm = _norm(node.func.value)
            if nm:
                read.add(nm)
    for c in checks:
        if c.wired:
            continue
        assert c.target in _STATE_INPUTS, c.target
        # 直接读（.isChecked()）或经别名读（形态标记那三条在 for 里用 _ck 读）都算；
        # 但"只有创建点、之后再没出现过"绝不能算——那说明这个控件根本没被用。
        assert c.target in read or uses.get(c.target, 0) >= 2, (
            "%r 登记成「状态输入」，但源码里既没有 .isChecked()/.checkState() 读它，"
            "也没有第二处引用——要么补接线，要么白名单理由是假的" % (c.target,))
        assert str(_STATE_INPUTS[c.target]).strip(), "状态输入 %r 没写理由" % (c.target,)
    # 反向：登记了却已经接线（或有接线能力）的条目要删掉；登记的句柄必须还在源码里
    by_target = {c.target: c for c in checks if c.target}
    for name in _STATE_INPUTS:
        assert name in by_target, "状态输入白名单条目已失效（控件不在了）：%r" % (name,)
        assert by_target[name].wired is False, (
            "%r 已经接线了，应该从 _STATE_INPUTS 里删掉" % (name,))


# ---------------- 2. P0 端到端：导出角色包的「角色信息」框 ----------------

def _buttons(dlg):
    return {b.text(): b for b in dlg.findChildren(QPushButton)}


def test_role_meta_dialog_has_both_buttons():
    """工厂返回的窗口里必须真有这两个按钮（防止改名后用例变成空转）。"""
    dlg, _n, _a, _d, _t = pet_dialogs.build_role_meta_dialog(None, "小鱼")
    texts = _buttons(dlg)
    assert "继续导出" in texts, "找不到「继续导出」按钮：%r" % (list(texts),)
    assert "取消" in texts, "找不到「取消」按钮：%r" % (list(texts),)
    assert texts["继续导出"].isDefault() is True, (
        "「继续导出」不是默认按钮（回车也触发不了，与 _VoicePickDialog 不一致）")


def test_role_meta_ok_button_accepts(monkeypatch):
    """点「继续导出」→ result()==Accepted，且 pick_role_meta 返回四个用户字段。

    变异：注释掉 btn_ok.clicked.connect(dlg.accept) → 本用例红。
    """
    dlg, name, author, desc, tags = pet_dialogs.build_role_meta_dialog(None, "小鱼")
    name.setText("阿鱼")
    author.setText("绳匠")
    desc.setText("一只懒鱼")
    tags.setText("猫，可爱, 懒")
    monkeypatch.setattr(pet_dialogs, "build_role_meta_dialog",
                        lambda *a, **k: (dlg, name, author, desc, tags))

    def _click_ok(d):
        _buttons(d)["继续导出"].click()
        return d.result()
    monkeypatch.setattr(pet_dialogs, "modal", _click_ok)

    got = pet_dialogs.pick_role_meta(None, "小鱼")
    assert got is not None, "点了「继续导出」却返回 None（按钮没接线）"
    assert got["name"] == "阿鱼" and got["author"] == "绳匠"
    assert got["description"] == "一只懒鱼"
    assert got["tags"] == ["猫", "可爱", "懒"], "标签没有按逗号切分：%r" % (got["tags"],)
    assert got.get("created_at"), "创建日期字段丢了"


def test_role_meta_cancel_button_rejects(monkeypatch):
    """点「取消」→ 对话框**真的关闭**（finished 收到 Rejected）且 pick_role_meta 返回 None。

    变异：注释掉 btn_cancel.clicked.connect(dlg.reject) → 本用例红。
    注意必须用 finished 信号判"关没关"：Rejected 的值就是 0，而 result() 的初值也是 0
    ——只看 result() 的话"取消按钮没接线"会假绿（实测踩过，见本轮回报的变异记录）。
    """
    dlg, name, author, desc, tags = pet_dialogs.build_role_meta_dialog(None, "小鱼")
    monkeypatch.setattr(pet_dialogs, "build_role_meta_dialog",
                        lambda *a, **k: (dlg, name, author, desc, tags))
    finished = []
    dlg.finished.connect(lambda r: finished.append(int(r)))

    def _click_cancel(d):
        _buttons(d)["取消"].click()
        return d.result()
    monkeypatch.setattr(pet_dialogs, "modal", _click_cancel)

    assert pet_dialogs.pick_role_meta(None, "小鱼") is None, "点了「取消」却没返回 None"
    assert finished == [int(QDialog.DialogCode.Rejected)], (
        "「取消」点了没反应：对话框**没有关闭**（finished=%r）——用户点取消也关不掉窗口"
        % (finished,))


def test_role_meta_esc_or_close_returns_none(monkeypatch):
    """Esc / 标题栏 × 的语义：走 reject → pick_role_meta 返回 None（不导出）。"""
    dlg, name, author, desc, tags = pet_dialogs.build_role_meta_dialog(None, "小鱼")
    monkeypatch.setattr(pet_dialogs, "build_role_meta_dialog",
                        lambda *a, **k: (dlg, name, author, desc, tags))
    monkeypatch.setattr(pet_dialogs, "modal",
                        lambda d: (d.reject(), d.result())[1])
    assert pet_dialogs.pick_role_meta(None, "小鱼") is None
    assert dlg.result() == QDialog.DialogCode.Rejected
