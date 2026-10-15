# -*- coding: utf-8 -*-
"""v2.7.0 第 5 轮（代理 A）：pet_dialogs.py 的反馈契约（成功有回执 / 失败不静默）。

覆盖（编号对齐 _dev/audit_feedback_v270.md 与 _dev/task_v270_round.md 的 A 段）：
  P1-1 AISettingsDialog 保存静默丢数据 · P1-2 导出行为成功零提示 ·
  P1-3 删除行为无二次确认 · P1-4 气泡样式 / 物理参数保存双静默 ·
  P2-3 绑定下拉空态 · D6/D7 失效引用删除丢弃返回值 · D11 删除选中步骤 takeItem(-1) ·
  S22/S23 设为当前 / 恢复默认 · N3/N6/P1-8/P1-9 新建后选中新条目并给出回执 ·
  S2 空名重命名静默 · S25 物理入口打不开静默 ·
  **P0 端到端**：菜单「导出角色包」真实路径（角色信息框 → 继续导出 → 产出包 → 能被导入读回）。

写法沿用仓内既有套路（tests/test_dialogs_more_v24.py）：
  · offscreen + 真 PetWindow + 临时数据目录；
  · **不 exec() 模态**：_warn/_info/_confirm 换成记录器（offscreen 下 exec 会挂死进程）；
  · 成功回执断言"宠物气泡收到了什么"（把 pet.show_bubble 换成记录器），不做像素断言；
  · 每条都配反向对照：失败不得关窗 / 取消不得改数据 / 未选中不得弹文件框。

变异：本文件**每一条**用例都对应一条"注释掉修复"的变异，逐条实测记录见本轮回报
（_dev 里不放脚本；驱动脚本在系统 TEMP，不改变交付内容）。典型：
  · 注释掉 build_role_meta_dialog 的两条 connect → 两条导出端到端用例红（红在"对话框没关"）；
  · AISettingsDialog._save 改回丢弃返回值 + 无条件 accept → P1-1 三条用例红；
  · 导出行为删掉成功分支 → test_behavior_export_ok_toasts_filename 红；
  · 删除行为删掉 _confirm → test_behavior_delete_needs_confirm 红；
  · 物理/气泡样式改回丢弃返回值 → 四条用例红；
  · strict=True 去掉 → test_ai_settings_none_return_is_failure 红；
  · 导入回执拼装退回 `"；".join(_res["warnings"][:2])`（v2.7.0 第 6 轮验收 P1-1 部分修）
    → 三条回执用例红（写失败被上限吃掉 / 有警告被静默丢弃）。
"""
import os
import sys
import wave

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pet_lines  # noqa: E402
import pet_log  # noqa: E402
import pet_dialogs  # noqa: E402

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QPushButton  # noqa: E402


# ---------------- 隔离：真 PetWindow + 临时数据目录（照抄 test_dialogs_more_v24） ----------------

def _boot_application():
    """导入期就拿到**真正的 QApplication**（QCoreApplication 之后再建会 RuntimeError）。"""
    app = QApplication.instance()
    if app is None:
        return QApplication([])
    return app


_APP = _boot_application()


def _ensure_qapplication():
    app = QApplication.instance()
    if isinstance(app, QApplication):
        return app
    pytest.fail("进程里只有 QCoreApplication（不是 QApplication），QWidget 无法构造",
                pytrace=False)


def _shutdown_pet(win):
    """先停表再拆（留着活跃 QTimer 会在别的用例里回调产品代码）。"""
    try:
        win._closing = True
    except Exception:
        pass  # 有意忽略：测试收尾尽力而为
    try:
        win.voice.stop()
    except Exception:
        pass  # 有意忽略：没有语音服务时跳过
    for _t in win.findChildren(QTimer):
        try:
            _t.stop()
        except Exception:
            pass  # 有意忽略：单个定时器停不掉不影响其余
    try:
        win.hide()
        win.close()
        win.deleteLater()
    except Exception:
        pass  # 有意忽略：测试收尾尽力而为


@pytest.fixture(scope="module")
def pet(tmp_path_factory):
    """真 PetWindow + 全部运行时路径指向临时目录（退出时还原进程级全局）。"""
    import 桌宠 as main
    import pet_resources as _pr
    tmp = tmp_path_factory.mktemp("dlgfeedback270")
    _snap = (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
             getattr(pet_log, "_data_dir", None), getattr(main, "_redact_key", None),
             getattr(_pr, "FRAME_MAX", None))
    main.DATA_DIR = str(tmp)
    main.CONFIG_PATH = str(tmp / "config.json")
    main.USAGE_PATH = str(tmp / "usage.json")
    main.MEMORY_PATH = str(tmp / "memory.json")
    pet_log.set_data_dir(str(tmp))
    _ensure_qapplication()
    win = main.PetWindow()
    from helpers_roles import install_three_form_role
    install_three_form_role(win, tmp)
    yield win
    _shutdown_pet(win)
    QApplication.processEvents()
    (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH,
     main.MEMORY_PATH) = _snap[0], _snap[1], _snap[2], _snap[3]
    pet_log.set_data_dir(_snap[4])
    main.set_redact_key(_snap[5] or "")
    if _snap[6] is not None:
        _pr.FRAME_MAX = _snap[6]


@pytest.fixture
def ui(pet, monkeypatch):
    """模态提示 + 宠物气泡都换成记录器。

    · warn/info/confirm：offscreen 下 modal() 的 exec() 会阻塞测试进程；
    · toast：断言"用户真的看到了回执"——记录 pet.show_bubble 收到的文案
      （气泡是独立置顶窗口，不做像素断言，见代理 B 的 _dev/probe_bubble_z_order_v270.py）。
    """
    seen = {"warn": [], "info": [], "confirm": True, "toast": []}

    def _rec(bucket):
        def _f(_parent, title, text):
            bucket.append((title, text))
        return _f

    monkeypatch.setattr(pet_dialogs, "_warn", _rec(seen["warn"]))
    monkeypatch.setattr(pet_dialogs, "_info", _rec(seen["info"]))
    monkeypatch.setattr(pet_dialogs, "_confirm", lambda _p, _t, _x: seen["confirm"])
    monkeypatch.setattr(pet, "show_bubble", lambda text: seen["toast"].append(text))
    return seen


def _accept_spy(dlg, monkeypatch):
    """记录 dlg.accept() 被调用了几次 —— "窗口关没关"的结构性事实。"""
    calls = []
    monkeypatch.setattr(dlg, "accept", lambda *a, **k: calls.append(1))
    return calls


def _select_row(widget, key):
    """按 UserRole 选中一行（列表/表格的第一列）。返回是否找到。"""
    for i in range(widget.count()):
        if widget.item(i).data(Qt.ItemDataRole.UserRole) == key:
            widget.setCurrentRow(i)
            return True
    return False


# ================= 1. 接口约定（与代理 B 对齐）=================

def test_apply_call_normalizes_new_and_old_contracts():
    """(ok,msg) 新契约 / True-False 老契约 / None 老成功 / 异常 / 方法缺失 全部归一。"""
    class _P(object):
        def new_fail(self, data):
            return (False, "写不进去")

        def new_nochange(self, data):
            return (True, "没有改动")

        def bool_true(self, data):
            return True

        def bool_false(self, data):
            return False

        def none_ok(self, data):
            return None

        def boom(self, data):
            raise RuntimeError("apply-boom")

    p = _P()
    assert pet_dialogs._apply_call(p, "new_fail", {}) == (False, "写不进去", True)
    assert pet_dialogs._apply_call(p, "new_nochange", {}) == (True, "没有改动", True)
    assert pet_dialogs._apply_call(p, "bool_true", {}) == (True, "", True)
    assert pet_dialogs._apply_call(p, "bool_false", {}) == (False, "", True)
    # 非严格模式（apply_role / apply_sound_group 这类没有返回值约定的老回调）：None = 成功
    assert pet_dialogs._apply_call(p, "none_ok", {})[0] is True, "老回调的 None 被误判成失败"
    assert pet_dialogs._apply_call(p, "no_such_method", {})[0] is True, "老回调缺失要按老 pet 兼容放行"
    # 严格模式（与 B 有接口约定的三个回调）：None / 方法缺失一律算失败（B 的明确要求）
    assert pet_dialogs._apply_call(p, "none_ok", {}, strict=True) == (False, "", False), (
        "strict 模式下 None 被当成了成功——B 说这三个回调永远返回二元组，None = 没拿到结果")
    assert pet_dialogs._apply_call(p, "no_such_method", {}, strict=True)[0] is False
    ok, msg, explicit = pet_dialogs._apply_call(p, "boom", {})
    assert (ok, explicit) == (False, False), "回调抛异常必须判失败且标记 explicit=False"


def test_toast_degrades_without_bubble(pet):
    """没有 show_bubble 能力的 pet 不许让回执把主流程弄崩（静默降级）。"""
    class _B(object):
        def __init__(self, got):
            self._got = got

        def show_bubble(self, text):
            self._got.append(text)
    assert pet_dialogs._toast(None, "x") is False
    assert pet_dialogs._toast(object(), "x") is False
    assert pet_dialogs._toast(pet, "") is False
    got = []
    assert pet_dialogs._toast(_B(got), "已保存~") is True
    assert got == ["已保存~"]


# ================= 2. P1-1 AI 设置保存 =================

def test_ai_settings_save_failure_keeps_window_open(pet, ui, monkeypatch):
    """apply 返回失败 → 不关窗 + 弹警告 + 不弹成功气泡。"""
    monkeypatch.setattr(pet, "apply_ai_settings", lambda data: (False, "磁盘只读，写不进去"))
    dlg = pet_dialogs.AISettingsDialog(pet)
    dlg.show()
    try:
        calls = _accept_spy(dlg, monkeypatch)
        dlg._model.setText("qwen2.5")
        dlg._save()
        assert calls == [], "保存失败却关窗了（=「保存成功」假象，P1-1 本体）"
        assert ui["warn"] and "磁盘只读" in ui["warn"][-1][1], \
            "保存失败没有给用户原因：%r" % (ui["warn"],)
        assert ui["toast"] == [], "失败却弹了成功气泡"
    finally:
        dlg.hide()


def test_ai_settings_save_success_closes_and_toasts(pet, ui, monkeypatch):
    """成功 → 关窗 + 有气泡（控制组：证明上面的"没关窗"不是因为 _save 没跑）。"""
    monkeypatch.setattr(pet, "apply_ai_settings", lambda data: (True, "AI 设置已更新"))
    dlg = pet_dialogs.AISettingsDialog(pet)
    dlg.show()
    try:
        calls = _accept_spy(dlg, monkeypatch)
        dlg._save()
        assert calls == [1], "保存成功却没有关窗"
        assert ui["toast"] and "AI 设置已更新" in ui["toast"][-1], \
            "保存成功没有气泡：%r" % (ui["toast"],)
        assert ui["warn"] == []
    finally:
        dlg.hide()


def test_ai_settings_save_exception_stays_open_without_modal(pet, ui, monkeypatch):
    """回调抛异常：窗口不关、原因写在窗口内的状态行里、**不弹模态框**。

    为什么不弹模态：tests/test_silent_logging_v24.py 在没有 _warn 记录器的情况下直接调
    AISettingsDialog._save（回调必炸）——那里弹模态框会 exec() 挂死整个测试进程。
    """
    def _boom(data):
        raise RuntimeError("apply_ai_settings-boom")
    monkeypatch.setattr(pet, "apply_ai_settings", _boom)
    dlg = pet_dialogs.AISettingsDialog(pet)
    calls = _accept_spy(dlg, monkeypatch)
    dlg._save()
    assert calls == [], "回调抛异常却关窗了（用户以为保存成功）"
    assert ui["warn"] == [], "异常路径不该弹模态框（会挂死无记录器的既有用例）"
    assert "保存失败" in dlg._save_hint.text(), \
        "窗口里没有可见的失败提示：%r" % (dlg._save_hint.text(),)


# ================= 3. P1-2 导出行为 JSON =================

def _mk_behavior(svc, name):
    b, err = svc.add(name, [{"act": "say", "text": name}])
    assert b is not None, "用例前提不成立：%s" % err
    return b


def test_behavior_export_ok_toasts_filename(pet, ui, monkeypatch, tmp_path):
    """成功 → 气泡文案含文件名（以前成功路径没有任何分支）。"""
    svc = pet.behaviors
    b = _mk_behavior(svc, "v270_export_ok")
    dlg = pet_dialogs.BehaviorDialog(pet, svc)
    dlg.show()
    try:
        assert _select_row(dlg._list, b["id"]), "行为没出现在列表里"
        out = tmp_path / "v270_行为.json"
        monkeypatch.setattr(pet_dialogs.QFileDialog, "getSaveFileName",
                            staticmethod(lambda *a, **k: (str(out), "")))
        dlg._export()
        assert out.is_file() and out.stat().st_size > 0, "导出没有写出文件（用例前提）"
        assert ui["toast"], "导出成功一个字的提示都没有（P1-2 本体）"
        assert out.name in ui["toast"][-1], "气泡里没有文件名：%r" % (ui["toast"][-1],)
    finally:
        dlg.hide()
        svc.delete(b["id"])


def test_behavior_export_without_selection_prompts(pet, ui, monkeypatch):
    """未选中 → 有人话提示，且**不弹文件框**（以前静默 return）。"""
    dlg = pet_dialogs.BehaviorDialog(pet, pet.behaviors)
    dlg.show()
    try:
        dlg._list.setCurrentRow(-1)
        opened = []
        monkeypatch.setattr(pet_dialogs.QFileDialog, "getSaveFileName",
                            staticmethod(lambda *a, **k: (opened.append(1), ("", ""))[1]))
        dlg._export()
        assert opened == [], "没选中行为却弹了「另存为」文件框"
        assert ui["info"] or ui["warn"], "未选中时沉默不响（用户不知道要先选一个）"
        assert "选" in (ui["info"] or ui["warn"])[-1][1]
    finally:
        dlg.hide()


# ================= 4. P1-3 删除行为二次确认 =================

def test_behavior_delete_needs_confirm(pet, ui, monkeypatch):
    """确认框返回 False → 一个字节都不许动；返回 True → 真删 + 有回执。"""
    svc = pet.behaviors
    b = _mk_behavior(svc, "v270_del")
    dlg = pet_dialogs.BehaviorDialog(pet, svc)
    dlg.show()
    try:
        assert _select_row(dlg._list, b["id"])
        ui["confirm"] = False
        dlg._delete()
        assert svc.get(b["id"]) is not None, "在确认框点了取消，行为却被删了"
        assert ui["toast"] == [], "取消删除却给了「已删除」回执"

        ui["confirm"] = True
        dlg._delete()
        assert svc.get(b["id"]) is None, "确认了却没删掉"
        assert ui["toast"] and "已删除" in ui["toast"][-1], \
            "删除成功没有回执：%r" % (ui["toast"],)
    finally:
        dlg.hide()
        svc.delete(b["id"])


def test_behavior_delete_without_selection_prompts(pet, ui):
    """未选中 → 提示（以前静默 return）。"""
    dlg = pet_dialogs.BehaviorDialog(pet, pet.behaviors)
    try:
        dlg._list.setCurrentRow(-1)
        dlg._delete()
        assert ui["warn"], "未选中时沉默不响"
    finally:
        dlg.hide()


# ================= 5. D11 删除选中步骤 =================

def _click_button(dlg, text):
    """按文案点真按钮（走 clicked 连接本身，而不是绕过接线直接调方法）。"""
    for b in dlg.findChildren(QPushButton):
        if b.text() == text:
            b.click()
            return True
    return False


def test_behavior_delete_step_without_selection_prompts(pet, ui):
    """未选中步骤 → takeItem(-1) 以前只往 qWarning 打一行，界面零反应。

    走**真按钮**：把 clicked.connect(self._del_step) 换回原来的 lambda 必须红。
    """
    dlg = pet_dialogs.BehaviorDialog(pet, pet.behaviors)
    try:
        dlg._steps.setCurrentRow(-1)
        dlg._steps.clear()
        assert _click_button(dlg, "删除选中步骤"), "找不到「删除选中步骤」按钮"
        assert ui["warn"], "没选中步骤却什么都没说"
        assert dlg._steps.count() == 0
    finally:
        dlg.hide()


def test_behavior_delete_step_removes_selected(pet, ui):
    """控制组：选中了就真删一行，且不弹提示。"""
    dlg = pet_dialogs.BehaviorDialog(pet, pet.behaviors)
    try:
        dlg._steps.clear()
        from PySide6.QtWidgets import QListWidgetItem
        dlg._steps.addItem(QListWidgetItem("say 测试"))
        dlg._steps.addItem(QListWidgetItem("wait 500"))
        dlg._steps.setCurrentRow(0)
        ui["warn"].clear()
        assert _click_button(dlg, "删除选中步骤")
        assert dlg._steps.count() == 1 and ui["warn"] == []
    finally:
        dlg.hide()


# ================= 6. P1-9 / N6 新建后选中新条目 =================

def test_behavior_save_selects_new_row(pet, ui):
    """新建行为保存后：当前行就是新条目（以前 currentRow()==-1 → 不选中不滚动）。"""
    svc = pet.behaviors
    dlg = pet_dialogs.BehaviorDialog(pet, svc)
    dlg.show()
    try:
        dlg._steps.clear()
        dlg._act_combo.setCurrentIndex(dlg._act_combo.findData("say"))
        dlg._param.setText("你好呀")
        dlg._add_step()
        assert dlg._steps.count() == 1, "用例前提：步骤没加上"
        dlg._name.setText("v270_new_behavior")
        dlg._save()
        cur = dlg._list.currentItem()
        assert cur is not None, "保存后没有选中任何行（新行为落在列表末尾看不见）"
        bid = cur.data(Qt.ItemDataRole.UserRole)
        got = svc.get(bid)
        assert got is not None and got["name"] == "v270_new_behavior"
        assert ui["toast"], "保存成功没有回执"
    finally:
        dlg.hide()
        for x in svc.list():
            if x.get("name") == "v270_new_behavior":
                svc.delete(x["id"])


# ================= 7. P1-4 气泡样式 / 物理参数 =================

def test_bubble_style_save_failure_keeps_window_open(pet, ui, monkeypatch):
    monkeypatch.setattr(pet, "apply_bubble_style", lambda style: (False, "样式写不进去"))
    dlg = pet_dialogs.BubbleStyleDialog(pet)
    calls = _accept_spy(dlg, monkeypatch)
    dlg._save()
    assert calls == [], "保存失败却关窗"
    assert ui["warn"] and "样式写不进去" in ui["warn"][-1][1]
    assert ui["toast"] == []


def test_bubble_style_save_success_toasts(pet, ui, monkeypatch):
    monkeypatch.setattr(pet, "apply_bubble_style", lambda style: (True, "气泡样式已更新"))
    dlg = pet_dialogs.BubbleStyleDialog(pet)
    calls = _accept_spy(dlg, monkeypatch)
    dlg._save()
    assert calls == [1] and ui["toast"], "保存成功却零反馈"


def test_physics_save_reports_no_change(pet, ui, monkeypatch):
    """值未变（主窗返回 (True, "没有改动")）也必须有回执——以前是绝对静默。"""
    monkeypatch.setattr(pet, "apply_physics", lambda data: (True, "没有改动"))
    dlg = pet_dialogs.PhysicsDialog(pet)
    calls = _accept_spy(dlg, monkeypatch)
    dlg._save()
    assert calls == [1], "值未变不该拦住关窗"
    assert ui["toast"] and "没有改动" in ui["toast"][-1], \
        "「点保存什么都没发生」：%r" % (ui["toast"],)


def test_physics_save_failure_keeps_window_open(pet, ui, monkeypatch):
    monkeypatch.setattr(pet, "apply_physics", lambda data: (False, "物理参数写不进去"))
    dlg = pet_dialogs.PhysicsDialog(pet)
    calls = _accept_spy(dlg, monkeypatch)
    dlg._save()
    assert calls == [] and ui["warn"] and ui["toast"] == []


# ================= 8. D6 / D7 失效引用删除接住返回值 =================

class _FailDelete(object):
    """只让 delete / delete_many 失败，其余全部转发给真库。"""

    def __init__(self, real):
        self._real = real

    def delete(self, lid):
        return False, "磁盘只读"

    def delete_many(self, ids):
        return 0, "磁盘只读"

    def __getattr__(self, name):
        return getattr(self._real, name)


class _OkDeleteMany(object):
    def __init__(self, real, n):
        self._real = real
        self._n = n

    def delete_many(self, ids):
        return self._n, ""

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_delete_bad_one_surfaces_failure(pet, ui):
    dlg = pet_dialogs.LinesDialog(pet)
    dlg.show()
    try:
        _fill_bad_row(dlg, "v270_bad_1")
        dlg._lib = _FailDelete(pet.lines_lib)
        ui["confirm"] = True
        dlg._delete_bad_one()
        assert ui["warn"] and "磁盘只读" in ui["warn"][-1][1], \
            "删失败被丢弃（用户以为删了）：%r" % (ui["warn"],)
        assert ui["toast"] == [], "删失败却给了成功回执"
    finally:
        dlg.hide()


def test_delete_all_bad_surfaces_failure_and_success(pet, ui, monkeypatch):
    dlg = pet_dialogs.LinesDialog(pet)
    dlg.show()
    try:
        monkeypatch.setattr(dlg, "_scan", lambda: [{"line_id": "L1"}, {"line_id": "L2"}])
        dlg._lib = _FailDelete(pet.lines_lib)
        ui["confirm"] = True
        dlg._delete_all_bad()
        assert ui["warn"] and "磁盘只读" in ui["warn"][-1][1], "一键删除失败被静默吞掉"
        assert ui["toast"] == []

        ui["warn"].clear()
        dlg._lib = _OkDeleteMany(pet.lines_lib, 2)
        dlg._delete_all_bad()
        assert ui["toast"] and "2" in ui["toast"][-1], \
            "成功删除没有回执（条数已在手却从不显示）：%r" % (ui["toast"],)
    finally:
        dlg.hide()


def _fill_bad_row(dlg, lid):
    from PySide6.QtWidgets import QTableWidgetItem
    dlg._bad.setRowCount(0)
    dlg._bad.insertRow(0)
    it = QTableWidgetItem(lid)
    it.setData(Qt.ItemDataRole.UserRole, lid)
    dlg._bad.setItem(0, 0, QTableWidgetItem("失效台词"))
    dlg._bad.setItem(0, 1, it)
    dlg._bad.setCurrentCell(0, 1)


# ================= 9. S22 / S23 设为当前 / 恢复默认 =================

def test_role_set_active_failure_warns_and_success_toasts(pet, ui, monkeypatch):
    panel = pet_dialogs.RolePanel(pet)
    try:
        assert panel._list.count() >= 1, "用例前提：至少一个角色"
        panel._list.setCurrentRow(0)
        rid = panel._list.currentItem().data(Qt.ItemDataRole.UserRole)

        def _boom(role_id):
            raise RuntimeError("apply_role-boom")
        monkeypatch.setattr(pet, "apply_role", _boom)
        panel._set_active()
        assert ui["warn"], "切换角色失败却全静默（只在 error.log 留一行）"
        assert ui["toast"] == []

        monkeypatch.setattr(pet, "apply_role", lambda role_id: (True, ""))
        ui["warn"].clear()
        panel._set_active()
        assert ui["toast"], "切换角色成功零反馈（界面只有 [当前] 标记在动）"
        assert rid is not None
    finally:
        panel.hide()


def test_role_reset_default_failure_warns(pet, ui, monkeypatch):
    panel = pet_dialogs.RolePanel(pet)
    try:
        def _boom(role_id):
            raise RuntimeError("apply_role-boom")
        monkeypatch.setattr(pet, "apply_role", _boom)
        panel._reset_default()
        assert ui["warn"], "恢复默认失败全静默"
    finally:
        panel.hide()


# ================= 10. P2-3 绑定下拉空态 / 故障态 =================

class _EmptyAssets(object):
    def assets(self):
        return []


class _BoomAssets(object):
    def assets(self):
        raise RuntimeError("voice-assets-boom")


def test_bind_empty_state_shows_hint_and_import_entry(pet, ui):
    """素材库为空 → 下拉只有「（不绑定）」**且**有"去导入"的提示与入口。"""
    dlg = pet_dialogs.VoiceDialog(pet)
    try:
        dlg._assets = _EmptyAssets()
        dlg._refresh_bindings()
        cb = dlg._bind_combos[""]
        assert cb.count() == 1 and cb.itemText(0) == "（不绑定）", "空态前提不成立"
        assert "还没有配音素材" in dlg._bind_hint.text(), \
            "空态与故障态不可区分（用户只会问「怎么只有不绑定的选项」）"
        assert dlg._btn_import_assets.text(), "没有就地导入入口"
        assert dlg._btn_import_assets.isEnabled()
    finally:
        dlg.close()


def test_bind_broken_library_logs_and_says_why(pet, ui, tmp_path):
    """素材库读坏了 → error.log 有一条 + 界面说得出原因（以前 except 静默吞掉）。"""
    dlg = pet_dialogs.VoiceDialog(pet)
    try:
        dlg._assets = _BoomAssets()
        dlg._refresh_bindings()
        assert "读不出来" in dlg._bind_hint.text(), \
            "故障态没有告诉用户原因：%r" % (dlg._bind_hint.text(),)
        log = tmp_path / "error.log"
        txt = log.read_text(encoding="utf-8") if log.is_file() else ""
        assert "voice assets unreadable" in txt and "voice-assets-boom" in txt, \
            "素材库异常没有留痕：%r" % (txt,)
    finally:
        dlg.close()


# ================= 11. S2 空名重命名不再静默 =================

def test_sound_rename_empty_name_warns(pet, ui, monkeypatch, tmp_path):
    dlg = pet_dialogs.SoundPanel(pet)
    try:
        assert dlg._lib is not None, "用例前提：音效库可用"
        dlg._lib.import_file(_wav(tmp_path / "v270_rename.wav"))
        dlg._refresh()
        assert dlg._list.count() >= 1
        dlg._list.setCurrentRow(0)
        before = dlg._lib.fragments()[0]["name"]

        class _Val(object):
            def textValue(self):
                return "   "

        monkeypatch.setattr(pet_dialogs, "QInputDialog", _FakeInputDialog(_Val()))
        monkeypatch.setattr(pet_dialogs, "modal",
                            lambda _d: QDialog.DialogCode.Accepted)
        dlg._rename()
        assert ui["warn"], "删光名字点确定 → 什么都没发生（S2 静默）"
        assert dlg._lib.fragments()[0]["name"] == before, "空名居然被写进去了"
    finally:
        dlg.close()


class _FakeInputDialog(object):
    """把 QInputDialog(...) 换成"直接 accept 的假框"，textValue 由用例给。"""

    def __init__(self, value_holder):
        self._v = value_holder

    def __call__(self, *a, **k):
        return self

    def setWindowTitle(self, *a):
        pass

    def setLabelText(self, *a):
        pass

    def setTextValue(self, *a):
        pass

    def setStyleSheet(self, *a):
        pass

    def textValue(self):
        return self._v.textValue()


def _wav(path):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 800)
    return str(path)


# ================= 12. N3/P1-8 台词保存：过滤复位 + 选中新行 + 回执 =================

def test_lines_save_new_line_clears_filters_and_toasts(pet, ui):
    dlg = pet_dialogs.LinesDialog(pet)
    dlg.show()
    try:
        cats = list(pet_lines.LINE_CATEGORIES)
        new_cat, other_cat = cats[0], cats[-1]
        if new_cat == other_cat:
            # v2.7.0 第 5 轮收尾：这里以前是 pytest.skip（**当前不可达**的前提守卫——
            # 类别只有一个才跳过）。skip 会让"前提塌了"看起来像"没事发生"，改成 fail
            # （pytrace=False：这是前提断言，不是产品缺陷，不要打印无关调用栈）。
            pytest.fail("类别只有一个，用例前提不成立", pytrace=False)
        dlg._cat.setCurrentIndex(dlg._cat.findData(new_cat))
        dlg._filter.setCurrentIndex(dlg._filter.findData(other_cat))
        dlg._search.setText("绝不匹配的关键词")
        dlg._text.setPlainText("v270 反馈回归台词")
        dlg._save_line()

        assert dlg._filter.currentData() in ("", None), "类别筛选没有复位，新台词看不见"
        assert dlg._search.text() == "", "搜索词没有清掉，新台词看不见"
        row = -1
        for i in range(dlg._list.count()):
            if dlg._list.item(i).data(Qt.ItemDataRole.UserRole) == dlg._editing:
                row = i
                break
        assert row >= 0, "保存后的新台词不在列表里（P1-8：筛选/搜索把它藏了）"
        assert dlg._list.currentRow() == row, "没有选中刚保存的台词"
        assert ui["toast"], "台词保存成功零提示"
    finally:
        dlg.hide()
        if dlg._editing:
            pet.lines_lib.delete(dlg._editing)


# ================= 13. B 的接口约定：None 必须当失败 =================

def test_ai_settings_none_return_is_failure(pet, ui, monkeypatch):
    """回调返回 None（没拿到结果）→ 必须当失败：不关窗 + 窗口里有可见提示。

    变异：把这一处的 strict=True 去掉（None 就会被当成"老契约的成功"）→ 本用例红。
    """
    monkeypatch.setattr(pet, "apply_ai_settings", lambda data: None)
    dlg = pet_dialogs.AISettingsDialog(pet)
    calls = _accept_spy(dlg, monkeypatch)
    dlg._save()
    assert calls == [], "回调返回 None 却被当成保存成功（B 明确要求按失败处理）"
    assert "保存失败" in dlg._save_hint.text(), (
        "窗口里没有可见的失败提示：%r" % (dlg._save_hint.text(),))


# ================= 14. P2-3：索引"有内容却读不出"必须与"空库"区分 =================

def test_bind_index_unusable_is_not_the_empty_state(pet, ui, monkeypatch, tmp_path):
    """真坏索引（文件在、条目全被跳过）→ 提示走"读不出来"，且与 _asset_items 的兜底无关。

    两条独立证据：
      ① 把 _asset_items 换成"永远只有（不绑定）"的桩，提示行**照旧**走"读不出来"
         —— 说明这条判据不经过那个仍然静默的 except: pass；
      ② error.log 里真有这行（用户查得到原因）。
    变异：删掉 _assets_index_unusable 的分支 → 本用例红（退回"还没有配音素材"）。
    """
    import pet_resources
    data_dir = tmp_path / "corrupt_index"
    data_dir.mkdir()
    (data_dir / "voice_assets.json").write_text(
        '{"assets": [{"id": "a1", "name": "本该能用", "file": "a1.wav", "ext": "m4a"},'
        ' {"id": "a2", "name": "没扩展名", "file": "a2.wav"}]}', encoding="utf-8")
    lib = pet_resources.VoiceAssetLibrary(str(data_dir))
    assert lib.assets() == [], "用例前提：坏索引一条可用素材都读不出来"
    assert (data_dir / "voice_assets.json").is_file(), "用例前提：索引文件还在（不是被删掉）"

    dlg = pet_dialogs.VoiceDialog(pet)
    try:
        dlg._assets = lib
        # 证据①：把 _asset_items 变成"永远只有（不绑定）"的桩，提示行不该跟着变成空态
        monkeypatch.setattr(dlg, "_asset_items", lambda: [("", "（不绑定）")])
        dlg._refresh_bindings()
        hint = dlg._bind_hint.text()
        assert "读不出来" in hint, (
            "索引里有内容却按「还没有素材」报，用户看不出是坏了：%r" % (hint,))
        assert "还没有配音素材" not in hint, "两条提示撞在一起了：%r" % (hint,)
        # 独立性：健康探测说"读得出来"，是"索引不可用"这条判据在说话（两者互不依赖）
        assert dlg._assets_health() == (True, ""), "健康探测不该把坏索引报成异常"
        assert dlg._assets_index_unusable()[0] is True
    finally:
        dlg.close()
    # 证据②：error.log 里有那行
    log = tmp_path / "error.log"
    txt = log.read_text(encoding="utf-8") if log.is_file() else ""
    assert "声音素材索引有内容但一条可用素材都没读出来" in txt, (
        "这条提示没有留痕，用户/我们事后查不到：%r" % (txt,))


# ================= 15. P0 端到端：菜单「导出角色包」真实路径 =================

def _drive_modal(closed, *labels):
    """把 modal() 换成"点某个文案的按钮，再看它到底关没关"。

    用 **finished 信号**判"关没关"，不用 result()：result() 的初值就是 Rejected(0)，
    没接线的按钮点下去 result 不变，会和"用户点了取消"撞成同一个值（假绿）。
    """
    def _f(dlg):
        seen = []
        dlg.finished.connect(lambda r: seen.append(int(r)))
        btns = {b.text(): b for b in dlg.findChildren(QPushButton)}
        label = next((t for t in labels if t in btns), None)
        assert label is not None, "对话框里找不到候选按钮 %r：%r" % (labels, list(btns))
        btns[label].click()
        closed.append((label, list(seen)))
        return dlg.result()
    return _f


def test_export_role_bundle_end_to_end(pet, ui, monkeypatch, tmp_path):
    """真实路径：菜单「导出角色包」→ 角色信息框 →「继续导出」→ 产出包 → 能被导入读回。

    这一条复刻用户被卡死的路径（不是单测接线）：对话框必须**真的关闭**（finished 收到
    Accepted）、导出必须**真的跑完并产出** .dfypet.zip、且这个包能被「导入角色包」
    重新读回来（角色与形态齐）。
    变异：注释掉 build_role_meta_dialog 的两条 connect → 本用例红，红在"对话框没关"。
    """
    import pet_resources  # noqa: F401（与导入侧同源，确认模块可用）
    orig_role = pet.cfg.get("role")
    assert pet._custom_role and orig_role, "用例前提：夹具装的是自定义角色"
    _exported_forms = len((pet.role_lib.get(orig_role) or {}).get("forms") or [])
    assert _exported_forms >= 1, "用例前提：角色有形态"

    out = tmp_path / "e2e_角色包.dfypet.zip"
    monkeypatch.setattr(pet_dialogs.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    monkeypatch.setattr(pet_dialogs.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    closed = []
    monkeypatch.setattr(pet_dialogs, "modal", _drive_modal(closed, "继续导出"))

    pet._export_role()
    assert closed, "导出流程根本没走到「角色信息」框（pick_role_meta 没被调用）"
    label, finished = closed[-1]
    assert finished == [int(QDialog.DialogCode.Accepted)], (
        "「%s」点了没反应：对话框**没有关闭**（finished=%r）——这正是用户被卡死的那一步"
        % (label, finished))
    guard = 0
    while pet._export_writer is not None and guard < 8000:
        guard += 1
        QApplication.processEvents()
    assert pet._export_writer is None, "分片导出没有收敛"
    assert out.is_file() and out.stat().st_size > 0, "导出流程没有产出角色包文件"
    assert any("角色包已导出" in t for t in ui["toast"]), (
        "导出成功没有回执：%r" % (ui["toast"],))

    # ---- 真导入读回（同一个包，走真实入口）----
    before = {r["id"] for r in pet.role_lib.list_roles()}
    ui["toast"].clear()
    try:
        pet._import_role_bundle()
        assert any("角色包导入成功" in t for t in ui["toast"]), (
            "导入没有成功回执：%r" % (ui["toast"],))
        new = [r for r in pet.role_lib.list_roles() if r["id"] not in before]
        assert len(new) == 1, "导入没有落地新角色：%r" % ([r["id"] for r in new],)
        forms = new[0].get("forms") or []
        assert len(forms) == _exported_forms, (
            "导入回来的形态数与导出不一致：%d vs %d" % (len(forms), _exported_forms))
        for f in forms:
            assert f.get("file"), "形态缺贴图字段：%r" % (f,)
    finally:
        for r in pet.role_lib.list_roles():
            if r["id"] not in before:
                pet.role_lib.delete(r["id"])
        pet.apply_role(orig_role)


def test_export_role_bundle_cancel_writes_nothing(pet, ui, monkeypatch, tmp_path):
    """点「取消」→ 对话框真的关闭 + 一个文件都不产出。

    变异：注释掉 btn_cancel.clicked.connect(dlg.reject) → 本用例红，红在"对话框没关"
    （finished 为空）——用 result() 判会假绿，因为 Rejected 就是 0。
    """
    out = tmp_path / "cancel_角色包.dfypet.zip"
    monkeypatch.setattr(pet_dialogs.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    closed = []
    monkeypatch.setattr(pet_dialogs, "modal", _drive_modal(closed, "取消"))
    pet._export_role()
    assert closed, "导出流程没走到「角色信息」框"
    label, finished = closed[-1]
    assert finished == [int(QDialog.DialogCode.Rejected)], (
        "「%s」点了没反应：对话框**没有关闭**（finished=%r）" % (label, finished))
    assert not out.exists(), "取消导出却产出了文件"
    assert pet._export_writer is None, "取消导出却起了写包器"


# ================= 16. F1 反向用例：健康库不许报「索引不可用」 =================

def test_bind_hint_quiet_on_healthy_library(pet, ui, monkeypatch, tmp_path):
    """**健康库**（assets() 真读出 N 条）→ 提示行必须为空，且不许写那条误导日志。

    为什么必须有这条（F1b 的洞）：上面第 14 条断的是**谓词** `_assets_index_unusable()[0] is True`
    —— 而"坏索引"与"健康库"在改前的判据里**都是 True**（只看索引文件在不在、> 2 字节），
    用例天生分不出这两态，F1 于是溜了过去：任何导入过参考音的健康库一打开声音素材对话框
    就顶一条红字假警报「索引里有内容，但一条都读不出来」，而它下面的下拉里素材好好地列着。
    所以这条的断点放在**提示文案**上（不是谓词），并同时钉住"下拉里真的有素材"。
    变异：把 _assets_index_unusable 里的 `assets()` 判据删掉（退回只看文件大小）→ 本用例红。
    """
    import pet_resources
    data_dir = tmp_path / "healthy_index"
    data_dir.mkdir()
    (data_dir / "voice_assets.json").write_text(
        '{"assets": [{"id": "h1", "name": "干净人声", "file": "h1.wav", "ext": "wav"},'
        ' {"id": "h2", "name": "第二段", "file": "h2.mp3", "ext": "mp3"}]}', encoding="utf-8")
    lib = pet_resources.VoiceAssetLibrary(str(data_dir))
    assert len(lib.assets()) == 2, "用例前提：健康库真读得出 2 条"
    assert (data_dir / "voice_assets.json").stat().st_size > 2,         "用例前提：索引文件非空（正好命中改前的误判条件）"

    logged = []
    monkeypatch.setattr(pet_log, "log_throttled",
                        lambda key, msg, **kw: logged.append((key, msg)))
    dlg = pet_dialogs.VoiceDialog(pet)
    try:
        dlg._assets = lib
        dlg._refresh_bindings()
        hint = dlg._bind_hint.text()
        assert hint == "", ("健康库被报成坏库（用户可见的红色假警报）：%r" % (hint,))
        assert dlg._assets_index_unusable() == (False, ""), (
            "健康库被判成「索引不可用」：%r" % (dlg._assets_index_unusable(),))
        combos = list(dlg._bind_combos.values())
        assert combos, "用例前提：至少有一行绑定下拉"
        assert all(cb.count() >= 3 for cb in combos), (
            "下拉里没有列出健康库的素材：%r" % ([cb.count() for cb in combos],))
    finally:
        dlg.close()
    assert not [k for k, _m in logged if "unusable" in str(k)], (
        "健康库往 error.log 写了那条误导日志（索引有内容却读不出来）：%r" % (logged,))


# ================= 17. F2：裸错误串 = 失败（strict 下不许关窗） =================

def test_apply_result_treats_bare_error_string_as_failure():
    """失败口径统一：**非空字符串 = 失败**（pet_config.write_config / 桌宠.save_config 的形态）。

    改前实测 `_apply_call(_P(), "apply_physics", {}, strict=True)` = (True, "", True)——同一
    仓库里 write_config 已经改成"失败返回错误串"，裸串却落进最后一行 `return True, ""`，
    于是窗口照关、用户看到"保存成功"。
    """
    class _P(object):
        def bare_err(self, data):
            return "磁盘只读：写不进去"

        def empty_str(self, data):
            return ""

        def true_val(self, data):
            return True

    p = _P()
    assert pet_dialogs._apply_result("磁盘只读：写不进去") == (False, "磁盘只读：写不进去")
    assert pet_dialogs._apply_call(p, "bare_err", {}, strict=True) == (
        False, "磁盘只读：写不进去", True), "裸错误串被当成了成功"
    # 空串仍是成功（老回调 return "" 的写法继续放行）；True 也仍是成功
    assert pet_dialogs._apply_result("") == (True, "")
    assert pet_dialogs._apply_call(p, "empty_str", {}, strict=True)[0] is True
    assert pet_dialogs._apply_call(p, "true_val", {}, strict=True) == (True, "", True)


def test_physics_dialog_keeps_window_open_on_bare_error_string(pet, ui, monkeypatch):
    """真消费端：物理回调返回**裸错误串** → 不关窗 + 原因可见（F2 的用户可见面）。

    变异：把 _apply_result 里那条 `isinstance(res, str)` 判据删掉 → 本用例红（窗口关了）。
    """
    monkeypatch.setattr(pet, "apply_physics", lambda data: "磁盘只读：写不进去")
    dlg = pet_dialogs.PhysicsDialog(pet)
    calls = _accept_spy(dlg, monkeypatch)
    dlg._save()
    assert calls == [], "裸错误串被当成保存成功 → 窗口关掉了（用户看到的就是成功假象）"
    assert "磁盘只读" in dlg._save_hint.text(), (
        "失败原因没写进窗口内的状态行：%r" % (dlg._save_hint.text(),))


# ================= 18. F4：写盘失败时内存 cfg 一个字都不许改 =================

def test_ai_apply_settings_failure_leaves_memory_untouched(pet, monkeypatch):
    """落盘失败 → (False, 原因)，且**内存 cfg 一个字节没变**（F4）。

    改前是"先原地改 cfg、再 save"：用户看到"没能保存"，本次会话却已经在用新的 API 地址 /
    模型 / 人设，重启才回旧值 —— 同一件事两个真相。现在先改副本、落盘成功才提交。
    变异：把 pet_ai 里的 `new = dict(cfg)` 改回 `new = cfg`（恢复原地改）→ 本用例红。
    """
    before = dict(pet.cfg)
    order_before = list(pet.cfg)
    monkeypatch.setattr(pet.ai, "_save_cfg", lambda _cfg: "磁盘只读（注入）")
    ok, msg = pet.ai.apply_settings({"ai_reply_len": 17, "ai_max_tokens": 4242})
    assert ok is False and "磁盘只读（注入）" in msg, (ok, msg)
    assert pet.cfg.get("ai_reply_len") != 17 and pet.cfg.get("ai_max_tokens") != 4242,         "写盘失败却已经把新设置写进内存（本次会话已经在用新值）"
    assert dict(pet.cfg) == before, "写盘失败却改了内存 cfg：%r" % (pet.cfg,)
    assert list(pet.cfg) == order_before, "写盘失败却改了键顺序：%r" % (list(pet.cfg),)


def test_ai_apply_settings_success_commit_is_bit_identical(pet):
    """成功路径**逐位不变**（F4 选了"先改副本再提交"就必须钉住这条）。

    提交方式 `cfg.update(new)` 与原"原地改"必须给出同一份内容、同一个键顺序。
    变异：提交写成"清空再灌"（`cfg.clear(); cfg.update(new)`）→ 键顺序断言红。
    """
    before = dict(pet.cfg)
    order_before = list(pet.cfg)
    try:
        ok, msg = pet.ai.apply_settings({"ai_reply_len": 21, "ai_max_tokens": 777})
        assert ok is True and msg.strip(), (ok, msg)
        assert pet.cfg.get("ai_reply_len") == 21 and pet.cfg.get("ai_max_tokens") == 777
        expected = dict(before)
        expected["ai_reply_len"] = 21
        expected["ai_max_tokens"] = 777
        assert dict(pet.cfg) == expected, "成功路径改了不该改的键：%r" % (pet.cfg,)
        assert list(pet.cfg) == order_before, (
            "成功路径把键顺序改了（与原地改不再等价）：%r" % (list(pet.cfg),))
    finally:
        pet.cfg.update(before)   # 只还原内存（不落盘），给同模块后面的用例留干净状态


# ================= 19. L2-1：音效后端失败不许报「已更新」 =================

def test_sound_panel_backend_failure_does_not_claim_success(pet, ui, monkeypatch):
    """底层音效后端抛异常 → 有失败提示 + **没有**「音效组已更新~」。

    改前：桌宠.apply_sound_group 内部吞异常只写日志、连 save_config 的返回值也丢 → 返回 None
    → 面板按老契约（None=成功）判 → `if not ok` 是死代码 → 成功气泡无条件执行。
    变异：把 pet_dialogs 那处 strict=True 去掉（或把生产端改回不返回东西）→ 本用例红。
    """
    import pet_audio
    panel = pet_dialogs.SoundPanel(pet)
    try:
        def _boom(_paths):
            raise RuntimeError("audio-backend-down")

        monkeypatch.setattr(pet_audio, "set_custom_group", _boom)
        monkeypatch.setattr(panel, "_parent_widget", lambda: pet)
        panel._on_slot("press")     # 默认槽位 → set_slot(None) 必然成功，失败只可能来自后端
        # _warn 记录的是 (标题, 正文)：标题固定是「音效组」，正文视失败来源而定
        # （回调给了原因 → 原因原文；回调没给结果 → 通用那句"保存失败…"）
        assert [t for t, _x in ui["warn"]] == ["音效组"], (
            "音效后端失败却一句提示都没有：warns=%r" % (ui["warn"],))
        assert not any("音效组已更新" in t for t in ui["toast"]), (
            "底层失败却报了成功：toasts=%r" % (ui["toast"],))
    finally:
        panel.deleteLater()


def test_sound_panel_treats_none_return_as_failure(pet, ui, monkeypatch):
    """契约（L2-1 的另一半）：音效组回调**返回 None** 时不许当成成功。

    为什么单列一条：生产端修好（返回二元组）之后，"消费端 strict" 在正常路径上看不出差别
    ——只有生产端**没给结果**（老版本 / 回调自己把结果吞了）时才分得出来。B 的口径是这三个
    回调必须给结果，所以这条用"回调返回 None"把 strict 钉死。
    变异：把 _apply_call 那处的 strict=True 去掉 → 本用例红（None 被当成老契约的成功）。
    """
    panel = pet_dialogs.SoundPanel(pet)
    try:
        monkeypatch.setattr(panel, "_parent_widget", lambda: pet)
        monkeypatch.setattr(pet, "apply_sound_group", lambda *a, **k: None)
        panel._on_slot("press")
        assert [t for t, _x in ui["warn"]] == ["音效组"], (
            "回调没给结果（None）却被当成成功，一句提示都没有：warns=%r" % (ui["warn"],))
        assert not any("音效组已更新" in t for t in ui["toast"]), (
            "回调没给结果（None）却报了成功：toasts=%r" % (ui["toast"],))
    finally:
        panel.deleteLater()


# ================= 20. P2-4：帧动作「取消」不是「选少了」 =================

def test_frame_action_cancel_is_not_reported_as_too_few(pet, ui, monkeypatch):
    """文件框取消（返回空表）→ 静默返回；只有**真选了 1 张**才报「至少 2 张图」。

    改前 `if len(files) < 2` 把"取消"和"只选 1 张"合并成一句警告：用户点了取消却被训一句。
    变异：删掉 `if not files: return` → 前半段红。
    """
    rid = str(pet.cfg.get("role") or "")
    assert rid, "用例前提：夹具装了自定义角色"
    dlg = pet_dialogs.RoleEditDialog(pet, pet.role_lib, rid)
    try:
        monkeypatch.setattr(pet_dialogs.QFileDialog, "getOpenFileNames",
                            staticmethod(lambda *a, **k: ([], "")))
        dlg._add_frame_action()
        assert ui["warn"] == [], (
            "「取消」被报成了帧动作「至少 2 张图」：%r" % (ui["warn"],))
        monkeypatch.setattr(pet_dialogs.QFileDialog, "getOpenFileNames",
                            staticmethod(lambda *a, **k: (["/nowhere/only_one.png"], "")))
        dlg._add_frame_action()
        assert any("至少 2 张图" in t for _ti, t in ui["warn"]), (
            "真只选 1 张时反而没有提示（修过头了）：%r" % (ui["warn"],))
    finally:
        dlg.close()


# ================= 21. P2-1 / P3-1 / P3-2：写失败不许改内存、不许假反馈 =================

def test_clear_api_key_save_failure_keeps_key_and_says_so(pet, monkeypatch):
    """清 Key 写盘失败 → 不说「已清空」、内存 Key 还在、**一个字节都没删**（兼容审查 P2-1）。

    变异：把 clear_api_key 改回"先清内存 / 删文件、再 save"→ 本用例三条断言一起红。
    """
    pet.cfg["api_key"] = "sk-测试-不落盘"
    removed = []
    bubbles = []
    monkeypatch.setattr(pet.ai, "_remove_files", lambda paths: removed.append(paths))
    monkeypatch.setattr(pet, "show_bubble", lambda t: bubbles.append(t))

    monkeypatch.setattr(pet.ai, "_save_cfg", lambda _cfg: "磁盘只读（注入）")
    pet.ai.clear_api_key()
    assert bubbles, "清 Key 失败却没有任何反馈"
    assert "已清空" not in bubbles[-1], "写盘失败却报了「已清空」：%r" % (bubbles[-1],)
    assert "磁盘只读（注入）" in bubbles[-1], "失败原因没告诉用户：%r" % (bubbles[-1],)
    assert pet.cfg.get("api_key") == "sk-测试-不落盘", "写盘失败却把内存里的 Key 清了"
    assert removed == [], "写盘失败却删了数据文件：%r" % (removed,)

    # 成功后仍然照旧（成功路径行为不变）
    monkeypatch.setattr(pet.ai, "_save_cfg", lambda _cfg: None)
    bubbles[:] = []
    pet.ai.clear_api_key()
    assert pet.cfg.get("api_key") == "", "成功路径反而不清内存里的 Key 了"
    assert bubbles and "已清空" in bubbles[-1], "成功路径的文案被改坏了：%r" % (bubbles,)
    assert removed, "成功路径不再清理数据文件（行为被改坏）"


def test_bubble_style_and_physics_roll_back_cfg_on_write_failure(pet, monkeypatch):
    """真写失败（atomic_write_json 返回错误串）→ **cfg 与磁盘一致**（兼容审查 P3-1）。

    改前写失败后 cfg 已是新值（内存改 / 盘未改 / 引擎未改三处不一致），下一次保存别的键
    会把这次没写成的值一起带上盘。
    变异：删掉两个失败分支里的回滚 → 本用例红。
    """
    import 桌宠 as main
    import pet_io
    monkeypatch.setattr(pet_io, "atomic_write_json", lambda *a, **k: "磁盘只读（注入）")
    before_style = dict(pet.cfg.get("bubble_style") or {})
    before_phys = dict(pet.cfg.get("physics") or {})
    before_engine = dict(main.BUBBLE_STYLE)

    ok, msg = pet.apply_bubble_style({"bg": "#0a0b0c", "font_size": 15})
    assert ok is False and "磁盘只读（注入）" in msg, (ok, msg)
    assert dict(pet.cfg.get("bubble_style") or {}) == before_style,         "写失败却把 cfg 里的气泡样式改了：%r" % (pet.cfg.get("bubble_style"),)
    assert dict(main.BUBBLE_STYLE) == before_engine, "写失败却把样式应用到内存引擎了"

    ok2, msg2 = pet.apply_physics({"gravity": 0.77})
    assert ok2 is False and "磁盘只读（注入）" in msg2, (ok2, msg2)
    assert dict(pet.cfg.get("physics") or {}) == before_phys,         "写失败却把 cfg 里的物理参数改了：%r" % (pet.cfg.get("physics"),)


def test_ai_toggle_second_save_failure_is_reported(pet, monkeypatch):
    """「没 Key 就把开关退回关」那一次落盘失败也要说（兼容审查 P3-2）。

    变异：把那处 `_err2` 判据删回"调用完就不管" → 本用例红。
    """
    calls = []

    def _save(cfg):
        calls.append(dict(cfg))
        return None if len(calls) == 1 else "磁盘只读（注入）"

    bubbles = []
    monkeypatch.setattr(pet.ai, "_save_cfg", _save)
    monkeypatch.setattr(pet.ai, "set_api_key", lambda: None)   # 不弹输入框 = 用户没填 Key
    monkeypatch.setattr(pet, "show_bubble", lambda t: bubbles.append(t))
    before_enabled = pet.cfg.get("ai_enabled")
    monkeypatch.setitem(pet.cfg, "api_key", "")
    try:
        pet.ai.set_ai_enabled(True)
        assert len(calls) == 2, (
            "用例前提：这条路要落盘两次（开开关 / 没 Key 退回关），实际 %d 次" % len(calls))
        assert bubbles and "AI 开关也没能保存" in bubbles[-1], (
            "第二次落盘失败被吞了（勾选状态与磁盘不一致却不说）：%r" % (bubbles,))
    finally:
        pet.cfg["ai_enabled"] = before_enabled


# ================= 22. F5：_toast 的返回值是「尽力而为」，不是送达回执 =================

def test_toast_is_best_effort_not_a_delivery_receipt(pet):
    """F5：文档承诺与实现必须一致 —— 返回值只表示"尝试发了"，不表示"用户看见了"。

    实测：桌宠.show_bubble 在 `_closing` 早退分支下什么都不显示、也不抛异常，`_toast`
    照样返回 True（气泡可见=False）。要让返回值变成硬承诺得改主窗公共接口，所以取**改动
    最小且诚实**的一条：把口径写成"尽力而为"。
    变异：把文档改回"返回是否真的发出" → 本用例红。
    """
    doc = pet_dialogs._toast.__doc__ or ""
    assert "尽力而为" in doc, "文档又变回了「真的发出」那种硬承诺：%r" % (doc,)
    # 断在**第一行摘要**上：解释性正文里出现"真的发出"是允许的（它在讲改前的错误承诺），
    # 但摘要必须只说"尽力而为"——复核者/下一个调用方读的就是摘要。
    _summary = doc.strip().splitlines()[0]
    assert "尽力而为" in _summary, (
        "文档第一行没写「尽力而为」这个口径：%r" % (_summary,))
    assert "真的发出" not in _summary, (
        "文档第一行又承诺「真的发出」（返回值不是送达回执）：%r" % (_summary,))

    class _Swallowed(object):
        """学 show_bubble 的 _closing 早退：调用不抛异常，但什么都没显示。"""

        def __init__(self):
            self.called = []

        def show_bubble(self, text):
            self.called.append(text)

    s = _Swallowed()
    assert pet_dialogs._toast(s, "已保存~") is True
    assert s.called == ["已保存~"], "根本没调用 show_bubble（那就不叫「尽力而为」）"
    assert pet_dialogs._toast(None, "已保存~") is False, "没有 pet 时必须返回 False"

# ================= 23. 验收 P1-1（部分修）：导入回执不许吃掉「后果性警告」/ 不许静默丢条 =================

def _stub_import_bundle(monkeypatch, pet, warnings):
    """把 `pet_export.import_bundle` 换成"导入成功、但带 N 条别的警告"的假包。

    只驱动 `_import_role_bundle` 的回执拼装那一段，不产生真实角色库/素材副作用
    （真实包只产生 0~1 条警告，正是这条洞一直没被看见的原因）。
    """
    import pet_export
    res = {"role_id": pet.cfg.get("role"), "warnings": list(warnings), "meta": {}}
    monkeypatch.setattr(pet_export, "import_bundle", lambda *a, **k: (res, None))
    monkeypatch.setattr(pet_dialogs.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: ("假的角色包.dfypet.zip", "")))
    return res


def test_import_receipt_keeps_bubble_style_failure_behind_two_other_warnings(pet, ui, monkeypatch):
    """验收 P1-1（部分修）：**2 条别的警告排前面**时，写失败那句仍必须出现在气泡里。

    改前气泡 = 「角色包导入成功！（别的警告 A；别的警告 B）」——"气泡样式没能应用"被
    `_res["warnings"][:2]` 整条吃掉（验收员实测复现）。真实包通常只 0~1 条警告，所以这条洞
    一直没被看见，但"写失败必被说出来"在 >=2 条警告时并不成立。
    变异：回执拼装退回 `"；".join(_res["warnings"][:2])` → 本用例红（断在"写失败不见了"）。
    """
    import 桌宠 as main
    warnings = ["别的警告 A", "别的警告 B"]
    res = _stub_import_bundle(monkeypatch, pet, warnings)
    # 真写失败：走 apply_bubble_style 自己的失败分支（不 monkeypatch 它本身）
    monkeypatch.setattr(main, "save_config", lambda cfg: "磁盘只读（注入）")
    ui["toast"].clear()
    pet._import_role_bundle()
    ok_msg = [t for t in ui["toast"] if "角色包导入成功" in t]
    assert ok_msg, "导入连成功回执都没有：%r" % (ui["toast"],)
    text = ok_msg[-1]
    assert res["warnings"][:2] == warnings, "用例前提：两条别的警告先入列（写失败排第 3 条）"
    assert "气泡样式没能应用" in text, (
        "后果性警告被回执上限吃掉了——这正是验收员复现的那条洞：%r" % (text,))
    assert "磁盘只读（注入）" in text, "失败原因没带给用户：%r" % (text,)


def test_import_receipt_never_silently_drops_warnings(pet, ui, monkeypatch):
    """验收 P1-1（部分修）：5 条警告**一条都不许被静默丢弃**——要么都在，要么明写被截条数。

    改前 `[:2]` 只留前两条：被扔掉的 3 条既不在气泡里、也不在日志里（静默丢）。
    变异：回执拼装退回 `"；".join(_res["warnings"][:2])` → 本用例红（断在"条数没说"）。
    """
    five = ["警告 1", "警告 2", "警告 3", "警告 4", "警告 5"]
    _stub_import_bundle(monkeypatch, pet, five)
    logs = []
    monkeypatch.setattr(pet_log, "log_error", lambda msg, **kw: logs.append(str(msg)))
    ui["toast"].clear()
    pet._import_role_bundle()
    ok_msg = [t for t in ui["toast"] if "角色包导入成功" in t]
    assert ok_msg, "导入连成功回执都没有：%r" % (ui["toast"],)
    text = ok_msg[-1]
    missing = [w for w in five if w not in text]
    assert not missing or ("…等其余 %d 条（详见 error.log）" % len(missing)) in text, (
        "有 %d 条警告被静默丢弃（气泡既没写它们、也没写被截条数）：%r" % (len(missing), text))
    for w in missing:
        assert any(w in m for m in logs), (
            "被截掉的警告连 error.log 都没留痕（「详见 error.log」是一句空话）：%r <- %r"
            % (w, logs))


def test_import_receipt_must_show_and_rest_count_coexist(pet, ui, monkeypatch):
    """后果性警告与超限计数**同时成立**：3 条别的警告 + 写失败。

    期望：写失败必在（不计入上限），其余 3 条里装不下的那 1 条用"等其余 1 条"明写。
    变异：回执拼装退回 `"；".join(_res["warnings"][:2])` → 本用例红（两条断言都红）。
    """
    import 桌宠 as main
    _stub_import_bundle(monkeypatch, pet, ["警告 1", "警告 2", "警告 3"])
    monkeypatch.setattr(main, "save_config", lambda cfg: "磁盘只读（注入）")
    ui["toast"].clear()
    pet._import_role_bundle()
    ok_msg = [t for t in ui["toast"] if "角色包导入成功" in t]
    assert ok_msg, "导入连成功回执都没有：%r" % (ui["toast"],)
    text = ok_msg[-1]
    assert "气泡样式没能应用" in text, "后果性警告被上限吃掉了：%r" % (text,)
    assert "…等其余 1 条（详见 error.log）" in text, (
        "超限的那 1 条既没显示也没写条数（静默丢）：%r" % (text,))
