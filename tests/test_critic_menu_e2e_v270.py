# -*- coding: utf-8 -*-
"""v2.7.0 第 5 轮（F6 + 兼容审查 P1-1）：从**菜单项**起步的端到端。

为什么要另开一条（覆盖缺口的原文）：A 的 E2E 从 `pet._export_role()` 起步、并把 `modal()`
换成"点按钮驱动器"—— 于是「**菜单项 → handler**」这条接线与真 `exec()` 循环不在覆盖内：
把 pet_menu.py 里 `role_export_act.triggered.connect(...)` 摘掉，A 的两条导出用例照样绿
（它们直接调 handler，接线断没断根本看不出来）。本文件把这一段收成正式用例。

用例：
  ① F6  `test_menu_export_role_item_runs_full_path`：真 `pet._open_menu(gp)` → 真菜单树 →
     找到「📦 导出角色包…」→ `QAction.trigger()` → 全路径到产物（.dfypet.zip 真存在、有字节）
     + 真回执（气泡）+ 真关闭（finished 收到 Accepted）；
  ② P1-1 `test_bundle_import_reports_bubble_style_write_failure`：角色包导入时
     `apply_bubble_style` 写失败的原因**必须出现在回执里**（不许只有「角色包导入成功！」）。

写法沿用仓内套路（tests/test_dialogs_feedback_v270.py）：offscreen + 真 PetWindow + 临时数据
目录；`QMenu.exec` 换成"捕获菜单"（offscreen 下真 exec 会阻塞）；`modal()` 换成"点按钮 +
看 finished"的驱动器；断言全部是**结构性事实**（文件在不在 / finished 收到什么 / 气泡收到
什么），收尾自旋是"有界循环 + 结构性退出条件"，**不依赖机器速度**（无墙钟阈值）。

变异（影子副本里验，铁律 6）：
  · 注释掉 pet_menu.py 的 `role_export_act.triggered.connect(...)`（或把菜单项文本改掉）
    → ① 红（红在"点了菜单项什么都没发生"）；
  · 把 `_res["warnings"].append("气泡样式没能应用…")` 删掉（退回丢弃返回值）→ ② 红。
"""
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pet_dialogs  # noqa: E402
import pet_log  # noqa: E402

from PySide6.QtCore import QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QAction  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QPushButton  # noqa: E402


# ---------------- 隔离：真 PetWindow + 临时数据目录（照抄 test_dialogs_feedback_v270） ----------------

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
    tmp = tmp_path_factory.mktemp("criticmenu270")
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
    """模态提示 + 宠物气泡都换成记录器（offscreen 下 modal() 的 exec() 会阻塞测试进程）。"""
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


# ---------------- 驱动器 ----------------

def _open_menu_capture(pet, monkeypatch, inspect):
    """走**真** `pet._open_menu()`（含 pet_menu 末尾那次真 `menu.exec()` 循环）。

    为什么不用"把 QMenu.exec 换掉"：PySide6 的类级替换对 C++ 侧调用点不生效（实测：真 exec
    照样阻塞），而**实例属性**替换生效。这里只替换 `pet._new_menu`（拿到刚建好的那棵树
    —— 真由 MenuBuilder 建出来的，不是测试拼的替身），留给 exec 的是**真循环**：
    定时器在循环里跑 `inspect(menu)`（用例在这一刻触发 QAction），随后 `menu.close()`
    退出循环 —— 无论 inspect 成功与否都关，**绝不留挂死的用例**。
    返回 (problems, menus)。
    """
    menus, problems = [], []
    orig_new_menu = pet._new_menu

    def _new_menu():
        m = orig_new_menu()
        menus.append(m)
        return m

    monkeypatch.setattr(pet, "_new_menu", _new_menu)

    def _menu_now():
        # 主路径 = 我们自己捕获的实例；兜底 = Qt 的当前弹出菜单（实测 exec 期间能拿到）
        return menus[-1] if menus else QApplication.activePopupWidget()

    def _fire():
        try:
            menu = _menu_now()
            if menu is None:
                problems.append("菜单没建出来（menus=%r，popup=%r）"
                                % (menus, QApplication.activePopupWidget()))
                return
            inspect(menu)
        except Exception as e:
            problems.append("菜单驱动异常：%r" % (e,))
        finally:
            m = _menu_now()
            if m is not None:
                m.close()                       # 退出真 exec() 循环
                QTimer.singleShot(200, m.hide)  # 再补一枪：close 没结束循环时兜底

    QTimer.singleShot(0, _fire)
    pet._open_menu(QPoint(10, 10))
    return problems, menus


def _find_action(menu, text):
    """在菜单树里按文案找 QAction（子菜单的动作也是它的后代）。"""
    for act in menu.findChildren(QAction):
        if act.text() == text:
            return act
    return None


def _menu_texts(menu):
    return [a.text() for a in menu.findChildren(QAction)]


def _drive_modal(closed, *labels):
    """把 modal() 换成"点某个文案的按钮，再看它到底关没关"（用 finished 信号判，不用 result）。"""
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


def _wait_writer(pet):
    """等分片写包收尾：有界自旋 + **结构性**退出条件（没有墙钟阈值）。"""
    guard = 0
    while pet._export_writer is not None and guard < 8000:
        guard += 1
        QApplication.processEvents()
    assert pet._export_writer is None, "分片导出没有收敛（%d 轮事件循环后仍在写）" % guard


def _patch_export_dialogs(pet, monkeypatch, out_path, closed):
    monkeypatch.setattr(pet_dialogs.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out_path), "")))
    monkeypatch.setattr(pet_dialogs, "modal", _drive_modal(closed, "继续导出"))


def _export_through_menu(pet, monkeypatch, out_path):
    """从**菜单项**导出（真 connect → 真 handler），返回 modal 驱动器的记录。"""
    closed = []
    _patch_export_dialogs(pet, monkeypatch, out_path, closed)
    clicked = []

    def _inspect(menu):
        act = _find_action(menu, "📦 导出角色包…")
        assert act is not None, (
            "菜单里没有「📦 导出角色包…」项，实际有：%r" % (_menu_texts(menu),))
        act.trigger()      # ← 从菜单项开始：这一下必须真的走到 pet._export_role()
        clicked.append(act)

    problems, menus = _open_menu_capture(pet, monkeypatch, _inspect)
    assert menus, "右键菜单根本没构造出来（pet._open_menu → MenuBuilder.open 没走到 exec）"
    assert not problems, problems[0]
    assert clicked, "菜单驱动没跑起来（exec 循环里那次 trigger 没轮到）"
    return closed


def _export_direct(pet, monkeypatch, out_path):
    """直接调 handler 导出（只给需要"先有一个包"的用例当夹具用）。"""
    closed = []
    _patch_export_dialogs(pet, monkeypatch, out_path, closed)
    pet._export_role()
    return closed


# ---------------- ① F6：菜单项 → handler → 产物 ----------------

def test_menu_export_role_item_runs_full_path(pet, ui, monkeypatch, tmp_path):
    """真菜单 → 「📦 导出角色包…」→ 全路径产出角色包（从 QAction.trigger() 起步）。

    这一条盯的是**接线**：A 的 E2E 从 pet._export_role() 起步，把 pet_menu.py 的 connect
    摘掉也照样绿——本用例才会红。
    变异：注释掉 `role_export_act.triggered.connect(...)` → 本用例红，红在
    "点了菜单项什么都没发生"（closed 为空）。
    """
    assert pet._custom_role and pet.cfg.get("role"), "用例前提：夹具装的是自定义角色"
    out = tmp_path / "menu_角色包.dfypet.zip"
    ui["toast"].clear()
    closed = _export_through_menu(pet, monkeypatch, out)
    assert closed, (
        "点了「📦 导出角色包…」什么都没发生：导出流程没走到「角色信息」框（菜单项没接线？）")
    label, finished = closed[-1]
    assert finished == [int(QDialog.DialogCode.Accepted)], (
        "「%s」点了没反应：对话框**没有关闭**（finished=%r）" % (label, finished))
    _wait_writer(pet)
    assert out.is_file() and out.stat().st_size > 0, "菜单项跑完了却没产出角色包文件"
    assert any("角色包已导出" in t for t in ui["toast"]), (
        "菜单路径上没有成功回执：%r" % (ui["toast"],))


def test_menu_export_role_item_is_present_in_role_submenu(pet, monkeypatch):
    """同一棵树里的**结构**钉子：菜单项确实挂在「🐟 角色」子菜单里（不是别处冒出来的）。

    与上一条互为补充：上一条证明"点了有用"，这条证明"它在菜单里的位置/文案没漂"。
    """
    seen = {}

    def _inspect(menu):
        subs = [m.title() for m in menu.findChildren(QMenu)]
        seen["subs"] = subs
        role_menu = [m for m in menu.findChildren(QMenu) if m.title() == "🐟 角色"]
        seen["role_texts"] = _menu_texts(role_menu[0]) if role_menu else []

    problems, menus = _open_menu_capture(pet, monkeypatch, _inspect)
    assert menus, "菜单没构造出来"
    assert not problems, problems[0]
    assert "🐟 角色" in seen.get("subs", []), (
        "菜单里没有「🐟 角色」子菜单：%r" % (seen.get("subs"),))
    assert "📦 导出角色包…" in seen.get("role_texts", []), (
        "「🐟 角色」子菜单里没有「📦 导出角色包…」：%r" % (seen.get("role_texts"),))


# ---------------- ② P1-1：导入角色包时气泡样式写失败要说出来 ----------------

def test_bundle_import_reports_bubble_style_write_failure(pet, ui, monkeypatch, tmp_path):
    """角色包导入时 apply_bubble_style 写失败 → 回执里必须带原因（兼容审查 P1-1）。

    改前 `self.apply_bubble_style(...)` 的返回值被**丢弃**（AST: DISCARD）：写盘失败时
    气泡样式静默不生效，紧接着那句「角色包导入成功！」照说不误。
    变异：把 `_res["warnings"].append("气泡样式没能应用…")` 删掉 → 本用例红。
    """
    import 桌宠 as main
    out = tmp_path / "p11_角色包.dfypet.zip"
    closed = _export_direct(pet, monkeypatch, out)
    assert closed, "用例前提：要先有一个真包（导出流程没走到角色信息框）"
    _wait_writer(pet)
    assert out.is_file() and out.stat().st_size > 0, "用例前提：导出真的产出了包"

    orig_role = pet.cfg.get("role")
    before = {r["id"] for r in pet.role_lib.list_roles()}
    monkeypatch.setattr(pet_dialogs.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    # 注入"真写失败"（不抛异常、返回错误串，与 pet_io / pet_config 的口径一致）
    monkeypatch.setattr(main, "save_config", lambda cfg: "磁盘只读（注入）")
    ui["toast"].clear()
    try:
        pet._import_role_bundle()
        ok_msg = [t for t in ui["toast"] if "角色包导入成功" in t]
        assert ok_msg, "导入连成功回执都没有：%r" % (ui["toast"],)
        assert "气泡样式没能应用" in ok_msg[-1], (
            "写失败时气泡样式静默不生效，回执里却只有「导入成功」：%r" % (ok_msg[-1],))
        assert "磁盘只读（注入）" in ok_msg[-1], (
            "失败原因没带给用户：%r" % (ok_msg[-1],))
    finally:
        for r in pet.role_lib.list_roles():
            if r["id"] not in before:
                pet.role_lib.delete(r["id"])
        if orig_role:
            pet.apply_role(orig_role)
