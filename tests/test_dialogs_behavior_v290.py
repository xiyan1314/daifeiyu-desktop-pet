# -*- coding: utf-8 -*-
"""v2.9.0 第 7 轮（代理 A · 对话框与交互）：行为设置这条路补齐 + 反馈载体改造。

依据：_dev/audit_behavior_assets_v290.md（21 条清单）与 _dev/task_v290_round.md 的 A 段。
本文件覆盖 A1/A2/A3/A4/A5/A6/A7/A8/A9/A11 的 **UI 侧**（B4/B5/B6 的 UI 侧也在这里，
它们的纯逻辑由 tests/test_behavior_v290.py 钉住）。写法沿用仓内既有套路：

  · offscreen；不 exec() 模态（_warn/_info/_confirm 换成记录器，offscreen 下 exec 会挂死）；
  · 断言**结构性事实**（谁被调用了 / 组合框里有什么 / 盘上有什么 / 标签文本是什么），
    不看耗时（铁律 3）；
  · 替身**只给死值或只记录调用**，不镜像被测实现的逻辑（v2.8.0 教训 2）。
"""
import json
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pet_behaviors        # noqa: E402
import pet_dialogs          # noqa: E402
import pet_log              # noqa: E402
import pet_resources        # noqa: E402

from PySide6.QtCore import QTimer                                  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QPushButton   # noqa: E402

_APP = QApplication.instance()
if _APP is None:
    _APP = QApplication([])

SRC_PATH = os.path.join(ROOT, "pet_dialogs.py")


def _read_src():
    import io
    return io.open(SRC_PATH, encoding="utf-8").read()


def _png(path, w=40, h=40, color=0xFF3366CC):
    """带 alpha 的不透明色块 PNG（加载后 hasAlphaChannel=True，跳过去背景分支）。"""
    from PySide6.QtGui import QImage
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(color)
    assert img.save(str(path), "PNG")


def _buttons(dlg):
    return {b.text(): b for b in dlg.findChildren(QPushButton)}


# ---------------- 真 PetWindow（照 test_dialogs_feedback_v280.py 的夹具） ----------------

PET_TMP = {}


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
    tmp = tmp_path_factory.mktemp("dlgbehavior290")
    PET_TMP["dir"] = str(tmp)
    _snap = (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
             getattr(pet_log, "_data_dir", None), getattr(main, "_redact_key", None),
             getattr(pet_resources, "FRAME_MAX", None))
    main.DATA_DIR = str(tmp)
    main.CONFIG_PATH = str(tmp / "config.json")
    main.USAGE_PATH = str(tmp / "usage.json")
    main.MEMORY_PATH = str(tmp / "memory.json")
    pet_log.set_data_dir(str(tmp))
    win = main.PetWindow()
    yield win
    _shutdown_pet(win)
    QApplication.processEvents()
    (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH,
     main.MEMORY_PATH) = _snap[0], _snap[1], _snap[2], _snap[3]
    pet_log.set_data_dir(_snap[4])
    main.set_redact_key(_snap[5] or "")
    if _snap[6] is not None:
        pet_resources.FRAME_MAX = _snap[6]


@pytest.fixture
def ui(pet, monkeypatch):
    """真 pet + 模态记录器 + 气泡记录器（confirm 结论可由用例改）。"""
    seen = {"warn": [], "info": [], "confirm": True, "confirm_calls": [], "toast": []}

    def _w(parent, title, text):
        seen["warn"].append((str(title), str(text)))

    def _i(parent, title, text):
        seen["info"].append((str(title), str(text)))

    def _c(parent, title, text):
        seen["confirm_calls"].append((str(title), str(text)))
        return seen["confirm"]

    monkeypatch.setattr(pet_dialogs, "_warn", _w)
    monkeypatch.setattr(pet_dialogs, "_info", _i)
    monkeypatch.setattr(pet_dialogs, "_confirm", _c)
    monkeypatch.setattr(pet, "show_bubble", lambda text: seen["toast"].append(text))
    return seen


@pytest.fixture
def dlg(pet, ui):
    """一个真 BehaviorDialog（用完 hide，绝不 exec）。"""
    d = pet_dialogs.BehaviorDialog(pet, pet.behaviors)
    d.show()
    try:
        yield d
    finally:
        d.hide()


def _clear_cfg(pet, **vals):
    """把待机相关配置恢复成给定值（用例之间不留串扰）。"""
    pet.cfg["idle_actions"] = vals.get("idle_actions", [])
    pet.cfg["idle_play_mode"] = vals.get("idle_play_mode", "sequential")
    pet.cfg["idle_behavior"] = ""


# ==================== A1：动作参数 = 可编辑下拉 ====================

def test_action_param_is_an_editable_combo_with_candidates(dlg):
    """A1 验收①：步骤类型选「动作」时，参数框是**可编辑下拉**且候选非空。

    候选的唯一来源是 B1 的 pet_behaviors.action_choices(pet)（内建 idle/eat/poke/sleep
    + jump/emote 恒在）。
    变异：把候选来源换成空列表（_action_choices 直接 return []）→ 本用例红。
    """
    dlg._act_combo.setCurrentIndex(dlg._act_combo.findData("play_action"))
    assert dlg._param.isEditable(), "参数框不是可编辑下拉（用户又只能手打了）"
    items = [dlg._param.itemText(i) for i in range(dlg._param.count())]
    assert items, "「动作」参数框里一个候选都没有"
    for _builtin in pet_resources.ANIM_ACTIONS:
        assert _builtin in items, "内建动作 %r 不在候选里：%r" % (_builtin, items)
    assert "jump" in items and "emote" in items, items
    assert items == sorted(items), "候选顺序不稳定（B1 契约：去重 + 稳定排序）"
    dlg._act_combo.setCurrentIndex(dlg._act_combo.findData("say"))
    assert dlg._param.count() == 0, "台词步的参数框里出现了动作候选（那时参数是纯文本）"


def test_action_choices_come_from_the_single_source(pet, ui, monkeypatch):
    """A1：候选**只**来自 pet_behaviors.action_choices —— 不许自己再算一份。

    变异：在 _action_choices 里加一份本地兜底（或改成硬编码列表）→ 本用例红。
    """
    monkeypatch.setattr(pet_behaviors, "action_choices", lambda _pet: ["v290_only_choice"])
    d = pet_dialogs.BehaviorDialog(pet, pet.behaviors)
    d.show()
    try:
        d._act_combo.setCurrentIndex(d._act_combo.findData("play_action"))
        d._sync_param()
        items = [d._param.itemText(i) for i in range(d._param.count())]
        assert items == ["v290_only_choice"], (
            "候选不是来自 action_choices（有第二份来源）：%r" % (items,))
    finally:
        d.hide()


def test_typed_action_name_that_is_not_a_candidate_is_kept(dlg):
    """A1 验收②：手填一个不在候选里的名字，仍能加进步骤（下拉不许「纠正」用户）。

    变异：让 `setText` 不写进 lineEdit（或让 `text()` 在候选里找不到时回落第一条）→ 本用例红。
    **注意**：`set_choices` 的"回填分支"不在本用例的路径上（这里是"先设候选、再手填"，
    手填不经过回填）——那条分支由 `test_unknown_action_name_survives_load_and_save` 钉住。
    （原来这里写的是"把候选回落第一条 → 本用例红"，C 的 A 批实测**不成立**，已改正。）
    """
    dlg._act_combo.setCurrentIndex(dlg._act_combo.findData("play_action"))
    made_up = "v290_not_a_real_action"
    assert made_up not in [dlg._param.itemText(i) for i in range(dlg._param.count())]
    dlg._param.setText(made_up)
    assert dlg._param.text() == made_up, "手填的字被下拉吃掉了"
    dlg._add_step()
    steps = dlg._collect_steps()
    assert steps and steps[-1].get("name") == made_up, (
        "手填的动作名没有原样进步骤：%r" % (steps,))
    assert dlg._steps.item(0).text() == "动作：%s" % made_up, (
        "步骤列表显示的名字被改写了：%r" % (dlg._steps.item(0).text(),))


def test_unknown_action_name_survives_load_and_save(dlg, pet):
    """A1 验收③（UI 侧）：老行为文件里的未知动作名，读入后**原样显示、原样保存**。

    数据侧由 B 的用例钉住（validate_steps 从不校验名字存在性）；这里钉的是 **UI 侧**的
    另一个失败点：下拉/回填把未知名清成空、或回落成第一条候选。
    变异：set_choices 把 keep 丢掉（setEditText("") 或 setCurrentIndex(0)）→ 本用例红。
    """
    name = "v290_legacy_unknown_action"
    b, err = pet.behaviors.add("v290_unknown_act", [{"act": "play_action", "name": name}])
    assert b is not None, err
    try:
        dlg._refresh()
        assert dlg._select_behavior(b["id"]), "新行为没出现在列表里"
        assert dlg._collect_steps() == [{"act": "play_action", "name": name}], (
            "读入时动作名已经变了：%r" % (dlg._collect_steps(),))
        dlg._act_combo.setCurrentIndex(dlg._act_combo.findData("play_action"))
        dlg._param.setText(name)   # 这个名字此刻就在参数框里（不在候选里）
        dlg._sync_param()          # 刷新候选：这一步最容易把未知名吃掉
        assert dlg._param.text() == name, "刷新候选把未知动作名改掉了：%r" % (dlg._param.text(),)
        assert name not in [dlg._param.itemText(i) for i in range(dlg._param.count())], (
            "用例前提：这个动作名不该在候选里")
        dlg._save()
        got = pet.behaviors.get(b["id"])
        assert got["steps"] == [{"act": "play_action", "name": name}], (
            "保存后动作名变了：%r" % (got["steps"],))
    finally:
        pet.behaviors.delete(b["id"])


# ==================== A2 / A10：从图片做动作（就地入口 + 公共实现） ====================

def _install_role(pet, tmp_path, name="v290角色"):
    """给真 pet 装一个 2 形态自定义角色并切过去（返回 rid；调用方负责恢复）。"""
    a = tmp_path / "r_a.png"
    b = tmp_path / "r_b.png"
    _png(a, 50, 50, 0xFF114466)
    _png(b, 44, 44, 0xFF662211)
    role, err = pet.role_lib.import_processed(str(a), None, name,
                                              forms_src=[("甲", str(a)), ("乙", str(b))])
    assert role is not None and err is None, err
    pet.apply_role(role["id"])
    return role["id"]


def test_import_images_makes_an_action_on_the_current_role(pet, ui, monkeypatch, tmp_path):
    """A2 验收①：从行为设置走完「选图 → 命名 → 出现在动作候选里」。

    **落在当前角色当前形态**（roles.json），不是行为库；加完下拉里能选到它。
    变异：把落点写进行为库（或写进别的形态）→ 本用例红。
    """
    old_rid = str(pet.cfg.get("role") or "")
    rid = _install_role(pet, tmp_path)
    srcs = [tmp_path / "f1.png", tmp_path / "f2.png"]
    _png(srcs[0], 40, 40, 0xFF00AA00)
    _png(srcs[1], 44, 40, 0xFF00AA55)
    before_behaviors = [x["id"] for x in pet.behaviors.list()]
    d = pet_dialogs.BehaviorDialog(pet, pet.behaviors)
    d.show()
    try:
        monkeypatch.setattr(pet_dialogs.QFileDialog, "getOpenFileNames",
                            staticmethod(lambda *a, **k: ([str(p) for p in srcs], "")))
        monkeypatch.setattr(pet_dialogs, "_ask_text", lambda *a, **k: ("v290_pic_act", True))
        d._import_frame_action()
        forms = (pet.role_lib.get(rid) or {}).get("forms") or []
        frames = (forms[0].get("animations") or {}).get("v290_pic_act")
        assert frames and len(frames) == 2, (
            "动作没落到当前角色当前形态：%r" % (forms[0].get("animations"),))
        assert [x["id"] for x in pet.behaviors.list()] == before_behaviors, (
            "图片动作被写进了行为库（落点错了）")
        assert not (forms[1].get("animations") or {}).get("v290_pic_act"), "动作落到了别的形态上"
        d._act_combo.setCurrentIndex(d._act_combo.findData("play_action"))
        # **不自己刷候选**（质量审 4）：断言的必须是**对话框自己**刷出来的那一次 ——
        # 用例替被测对象把活干了，这条"加完立刻出现在候选里"就没有牙齿
        # （实测：删掉 _import_frame_action 末尾的 _sync_param() 仍然全绿）。
        items = [d._param.itemText(i) for i in range(d._param.count())]
        assert "v290_pic_act" in items, "加完动作后候选里选不到它：%r" % (items,)
        assert "v290_pic_act" in d._notes.text(), "加完没有回执：%r" % (d._notes.text(),)
        assert ui["toast"] == [], "列表内的操作不该弹宠物气泡：%r" % (ui["toast"],)
    finally:
        d.hide()
        pet.apply_role(old_rid)


def test_import_images_cancel_leaves_nothing_behind(pet, ui, monkeypatch, tmp_path):
    """A2 验收②：**取消是干净的**（不产生半截动作、不留孤儿文件）。

    两条取消路径都测：文件框取消（一个文件都没选）、命名框取消（选了图但没命名）。
    """
    old_rid = str(pet.cfg.get("role") or "")
    rid = _install_role(pet, tmp_path, "v290角色2")
    srcs = [tmp_path / "c1.png", tmp_path / "c2.png"]
    _png(srcs[0], 40, 40, 0xFF00AA00)
    _png(srcs[1], 40, 40, 0xFF00AA55)
    d = pet_dialogs.BehaviorDialog(pet, pet.behaviors)
    d.show()
    asked = []
    try:
        roles_dir = pet.role_lib._dir
        before_files = sorted(os.listdir(roles_dir))
        monkeypatch.setattr(pet_dialogs.QFileDialog, "getOpenFileNames",
                            staticmethod(lambda *a, **k: ([], "")))
        d._import_frame_action()
        assert ui["warn"] == [], "文件框取消被报成了错误：%r" % (ui["warn"],)
        monkeypatch.setattr(pet_dialogs.QFileDialog, "getOpenFileNames",
                            staticmethod(lambda *a, **k: ([str(p) for p in srcs], "")))
        monkeypatch.setattr(pet_dialogs, "_ask_text",
                            lambda *a, **k: (asked.append(1), ("", False))[1])
        d._import_frame_action()
        assert asked, "选了图却没问动作名（用例前提不成立）"
        assert sorted(os.listdir(roles_dir)) == before_files, (
            "取消之后角色目录里多了文件：%r" % (sorted(os.listdir(roles_dir)),))
        forms = (pet.role_lib.get(rid) or {}).get("forms") or []
        assert not (forms[0].get("animations") or {}), "取消却留下了半截动作"
        assert ui["warn"] == [], "取消不该弹任何提示：%r" % (ui["warn"],)
    finally:
        d.hide()
        pet.apply_role(old_rid)


def test_import_images_failure_leaves_no_orphan_files(pet, ui, monkeypatch, tmp_path):
    """A2 验收②（失败侧）：落盘失败 → 本次暂存的帧文件**全部回收**，角色里不留半截动作。

    这条走的是 add_frame_action 的 rollback 路径（成功路径由上面两条覆盖）。
    变异：去掉 sink.rollback(made) → 第一条断言红（角色目录里会多出 2 个孤儿文件）。
    """
    old_rid = str(pet.cfg.get("role") or "")
    rid = _install_role(pet, tmp_path, "v290角色3")
    srcs = [tmp_path / "o1.png", tmp_path / "o2.png"]
    _png(srcs[0], 40, 40, 0xFF00AA00)
    _png(srcs[1], 40, 40, 0xFF00AA55)
    d = pet_dialogs.BehaviorDialog(pet, pet.behaviors)
    d.show()
    try:
        roles_dir = pet.role_lib._dir
        before_files = sorted(os.listdir(roles_dir))
        monkeypatch.setattr(pet_dialogs.QFileDialog, "getOpenFileNames",
                            staticmethod(lambda *a, **k: ([str(p) for p in srcs], "")))
        monkeypatch.setattr(pet_dialogs, "_ask_text", lambda *a, **k: ("v290_orphan", True))
        monkeypatch.setattr(pet.role_lib, "update", lambda *a, **k: (False, "写不进去（用例注入）"))
        d._import_frame_action()
        assert sorted(os.listdir(roles_dir)) == before_files, (
            "落盘失败却把帧文件留在了角色目录：%r" % (sorted(os.listdir(roles_dir)),))
        forms = (pet.role_lib.get(rid) or {}).get("forms") or []
        assert not (forms[0].get("animations") or {}).get("v290_orphan"), "失败却加了动作"
        assert ui["warn"], "落盘失败却一句话都没有"
        assert "写不进去" in ui["warn"][-1][1], ui["warn"]
    finally:
        d.hide()
        pet.apply_role(old_rid)

def test_frame_action_default_role_says_why_instead_of_failing_silently(pet, ui, monkeypatch):
    """A2/P5-前置：「默认角色加不了动作」这条硬门槛必须**说明原因**（不是静默失败）。

    审计实测：默认角色（custom_actions() 返回 []）此前零说明，用户只会看到「点了没反应」。
    """
    old_rid = str(pet.cfg.get("role") or "")
    pet.cfg["role"] = ""
    d = pet_dialogs.BehaviorDialog(pet, pet.behaviors)
    d.show()
    opened = []
    try:
        monkeypatch.setattr(pet_dialogs.QFileDialog, "getOpenFileNames",
                            staticmethod(lambda *a, **k: (opened.append(1), ([], ""))[1]))
        d._import_frame_action()
        assert opened == [], "默认角色连文件框都不该弹（先得说清为什么不行）"
        assert ui["warn"], "默认角色加不了动作却一句解释都没有"
        assert "角色" in ui["warn"][-1][1], ui["warn"]
        assert "默认角色" in d._act_target.text(), (
            "按钮旁边没有写明现在加不了：%r" % (d._act_target.text(),))
    finally:
        d.hide()
        pet.cfg["role"] = old_rid


def test_role_edit_frame_action_is_a_thin_wrapper(monkeypatch, tmp_path):
    """A2/B2：角色编辑的「＋帧动作…」调的是**同一个**模块级实现（不许两份实现）。

    变异：让 _add_frame_action 自己再写一份导入逻辑（不走公共函数）→ 本用例红。
    """
    lib = pet_resources.RoleLibrary(str(tmp_path))
    a = tmp_path / "w_a.png"
    _png(a, 50, 50)
    role, err = lib.import_processed(str(a), None, "wrapper")
    assert role is not None and err is None, err
    calls = []

    def _fake(pet=None, parent=None, sink=None):
        calls.append((pet, parent, type(sink).__name__))
        return False, ""

    monkeypatch.setattr(pet_dialogs, "add_frame_action", _fake)
    d = pet_dialogs.RoleEditDialog(None, lib, role["id"])
    try:
        d._cur_idx = 0
        d._add_frame_action()
        assert calls and calls[-1][2] == "_StagedActionSink", (
            "角色编辑没有走公共实现（或落点不是暂存表单）：%r" % (calls,))
        assert calls[-1][1] is d, "公共实现没拿到本窗口做 parent：%r" % (calls,)
    finally:
        d._cleanup()


def test_no_static_input_dialog_is_left_in_the_source():
    """A10：pet_dialogs.py 里静态 QInputDialog.getText/getItem **归零**（源码级门）。

    （上一轮那条「只剩帧动作一处」的护栏在本轮改成「一处不剩」——加强，不是放宽。）
    变异：把任意一处改回静态调用 → 本用例红。
    """
    src = _read_src()
    assert "QInputDialog.getText(" not in src, "还有静态 getText 调用"
    assert "QInputDialog.getItem(" not in src, "还有静态 getItem 调用"
    assert "_ask_action_name(" in src, "帧动作的命名框没有走统一入口"


# ==================== A3：步骤上移 / 下移 ====================

def _three_steps(dlg):
    dlg._steps.clear()
    for txt in ("A", "B", "C"):
        dlg._act_combo.setCurrentIndex(dlg._act_combo.findData("say"))
        dlg._param.setText("步骤" + txt)
        dlg._add_step()


def test_step_move_up_and_down_reorders_and_follows_selection(dlg):
    """A3：补上移/下移；移动后**选中项跟着走**（否则连点两下不知道动的是谁）。

    变异：去掉 setCurrentRow（移动后不跟随）→ 第二条断言红。
    """
    _three_steps(dlg)
    assert [s["text"] for s in dlg._collect_steps()] == ["步骤A", "步骤B", "步骤C"]
    dlg._steps.setCurrentRow(2)              # 选中第 3 步
    dlg._move_step(-1)
    assert [s["text"] for s in dlg._collect_steps()] == ["步骤A", "步骤C", "步骤B"], (
        dlg._collect_steps())
    assert dlg._steps.currentRow() == 1, "移动之后选中项没跟着走"
    dlg._move_step(-1)
    assert [s["text"] for s in dlg._collect_steps()] == ["步骤C", "步骤A", "步骤B"]
    assert dlg._steps.currentRow() == 0
    dlg._move_step(1)
    assert [s["text"] for s in dlg._collect_steps()] == ["步骤A", "步骤C", "步骤B"]
    assert dlg._steps.currentRow() == 1


def test_step_move_at_boundary_says_so(dlg, ui):
    """A3：到顶/到底给回执（措辞照抄 LinesDialog._move_line）。

    渠道按任务书原则 2 走**窗口内状态行**（列表内操作不弹宠物气泡）。
    变异：去掉边界那一支的提示 → 前两条断言红。
    """
    _three_steps(dlg)
    dlg._steps.setCurrentRow(0)
    dlg._notes.setText("")
    dlg._move_step(-1)
    assert dlg._notes.text() == "已经是最上面了", dlg._notes.text()
    assert [s["text"] for s in dlg._collect_steps()] == ["步骤A", "步骤B", "步骤C"], "顺序被动了"
    dlg._steps.setCurrentRow(2)
    dlg._move_step(1)
    assert dlg._notes.text() == "已经是最下面了", dlg._notes.text()
    assert ui["toast"] == [], "列表内的边界提示不该弹宠物气泡：%r" % (ui["toast"],)


def test_step_move_without_selection_prompts(dlg, ui):
    """A3：没选中就点上移/下移 → 给一句提示（同「删除选中步骤」的口径）。"""
    _three_steps(dlg)
    dlg._steps.setCurrentRow(-1)
    ui["warn"].clear()
    dlg._move_step(-1)
    assert ui["warn"], "没选中步骤点「上移」却什么都没说"


# ==================== A4：列表内操作的回执走内联状态行 ====================

def test_step_receipts_use_the_inline_status_line_not_the_bubble(dlg, ui):
    """A4：添加/删除步骤的回执走**窗口内状态行**，且**不**再弹宠物气泡。

    背景（审计实测）：建一个 5 步行为弹 7 条气泡，而气泡是单窗口覆盖式、无队列 ——
    连点时前面的根本看不见、最后一条还滞留 5 秒；用户的眼睛其实在窗口里。
    变异：把 _note(...) 改回 _toast(...) → 第二条断言（ui["toast"] == []）红。
    """
    dlg._notes.setText("")
    for i in range(5):
        dlg._act_combo.setCurrentIndex(dlg._act_combo.findData("say"))
        dlg._param.setText("第%d步" % (i + 1))
        dlg._add_step()
        assert "已添加步骤" in dlg._notes.text(), (
            "第 %d 次添加后状态行没有更新：%r" % (i + 1, dlg._notes.text()))
        assert dlg._steps.count() == i + 1
    assert ui["toast"] == [], "建 5 步行为弹了 %d 条气泡：%r" % (len(ui["toast"]), ui["toast"])
    dlg._steps.setCurrentRow(0)
    dlg._del_step()
    assert "已删除步骤" in dlg._notes.text(), dlg._notes.text()
    assert ui["toast"] == [], "删除步骤弹了气泡：%r" % (ui["toast"],)


def test_new_state_is_a_resident_label_not_a_one_shot_bubble(dlg):
    """A11/P2-8：**常驻**的「新建中」标签（上一轮只做了一次性气泡＝修法不符）。

    三态：新建中 / 编辑中 / 什么都没选中。
    变异：把标签去掉（或只在点的一瞬间写一次然后清掉）→ 第三条断言红。
    """
    dlg._reset_form()
    assert "新建" in dlg._state_label.text() and "保存" in dlg._state_label.text(), (
        dlg._state_label.text())
    dlg._new()
    assert "● 新建中" in dlg._state_label.text(), dlg._state_label.text()
    # 「常驻」：中间穿插别的操作，标签仍然是新建中（不是一次性回执）
    dlg._act_combo.setCurrentIndex(dlg._act_combo.findData("say"))
    dlg._param.setText("x")
    dlg._add_step()
    assert "● 新建中" in dlg._state_label.text(), (
        "新建态标签没有常驻（中间的操作把它清了）：%r" % (dlg._state_label.text(),))
    dlg._name.setText("v290_new_label")
    dlg._save()
    assert "● 编辑中" in dlg._state_label.text(), dlg._state_label.text()
    assert "新建" not in dlg._state_label.text(), (
        "保存之后标签还在说新建中：%r" % (dlg._state_label.text(),))


def test_key_information_is_visible_not_only_in_a_tooltip(dlg):
    """A9：「点「保存」才落盘」这条决定成败的信息必须在**界面上看得见**。

    审计实测：169 个按钮只有 12 个有 tooltip（7.1%），而这条信息**只写在 tooltip 里**
    （不可发现、键盘/触屏没有 hover）。
    变异：把常驻标签那一行删掉 → 红。
    """
    txt = dlg._state_label.text()
    assert "保存" in txt, "界面上看不到「要保存才落盘」：%r" % (txt,)
    assert ("库" in txt) or ("落盘" in txt), txt
    btns = _buttons(dlg)
    for _label in ("保存", "删除", "试播", "导入行为文件（.json）…", "导出…", "取消"):
        assert _label in btns, "找不到按钮 %r：%r" % (_label, sorted(btns))
        assert btns[_label].toolTip(), "%r 没有 tooltip（只作补充，但不该是空的）" % (_label,)


# ==================== A5：「关闭」→「取消」+ 未保存确认 ====================

def test_cancel_with_unsaved_edits_asks_and_keeps_the_window(dlg, ui):
    """A5：有未保存改动 → 先确认；拒绝时窗口**仍然开着**、步骤还在。

    变异：把 _confirm_discard 里的 _confirm 去掉（直接 return True）→ 第一条断言红。
    """
    dlg._new()
    dlg._act_combo.setCurrentIndex(dlg._act_combo.findData("say"))
    dlg._param.setText("没保存的一步")
    dlg._add_step()
    assert dlg._is_dirty(), "用例前提：表单应该是脏的"
    finished = []
    dlg.finished.connect(lambda r: finished.append(int(r)))
    ui["confirm"] = False
    dlg._cancel()
    assert ui["confirm_calls"], "有未保存改动却直接关窗（草稿被静默丢弃）"
    assert finished == [], "用户点了「回去接着改」，窗口却关了"
    assert dlg._steps.count() == 1, "拒绝之后步骤没了"
    ui["confirm"] = True
    dlg._cancel()
    assert finished == [int(QDialog.DialogCode.Rejected)], (
        "确认放弃之后窗口没关：%r" % (finished,))


def test_cancel_without_edits_does_not_ask(dlg, ui):
    """A5（反向，原则 1）：**没有改动就直接关**，不许给熟路多加一步。

    变异：把 _is_dirty 的判据去掉（无脑弹确认）→ 本用例红。
    """
    dlg._reset_form()
    assert not dlg._is_dirty(), "用例前提：表单应该是干净的"
    finished = []
    dlg.finished.connect(lambda r: finished.append(int(r)))
    dlg._cancel()
    assert ui["confirm_calls"] == [], (
        "没有任何改动却弹了确认框（多一步）：%r" % (ui["confirm_calls"],))
    assert finished == [int(QDialog.DialogCode.Rejected)], finished


def test_save_does_not_close_and_the_second_button_is_cancel(dlg, pet):
    """A5/A8/R4：保存**不关窗**（B3 的 R1：面板型）；第二枚按钮叫「取消」不叫「关闭」。"""
    btns = _buttons(dlg)
    assert "取消" in btns, "第二枚按钮还叫「关闭」（它执行的是丢弃编辑 + 关窗）：%r" % (sorted(btns),)
    assert "关闭" not in btns, "还留着一个叫「关闭」的按钮：%r" % (sorted(btns),)
    dlg._act_combo.setCurrentIndex(dlg._act_combo.findData("say"))
    dlg._param.setText("保存不关窗")
    dlg._add_step()
    dlg._name.setText("v290_save_keeps_open")
    finished = []
    dlg.finished.connect(lambda r: finished.append(int(r)))
    dlg._save()
    assert finished == [], "保存之后窗口关了（B3 判它属于面板型：保存不该关窗）"
    got = [x for x in pet.behaviors.list() if x["name"] == "v290_save_keeps_open"]
    assert got, "保存没写进库里"
    pet.behaviors.delete(got[0]["id"])


# ==================== A7：「导入…」改名 + 非 JSON 给人话 ====================

def test_import_button_says_it_is_a_json_file(dlg):
    """A7：按钮文案写清它只认行为文件（.json），不再让人以为能导入素材。"""
    labels = sorted(_buttons(dlg))
    assert "导入行为文件（.json）…" in labels, labels
    assert "导入…" not in labels, "旧文案还在：%r" % (labels,)


def test_import_non_json_gives_a_human_reason(pet, ui, monkeypatch, tmp_path):
    """A7：把 PNG 丢进「导入行为文件」→ **人话原因**，不出现英文异常。

    审计实测改前：utf-8 codec can not decode byte 0x89 ... 直接弹给用户。
    变异：去掉扩展名预检（放行到 svc.import_file）→ 第二条断言（import_file 没被调用）红。
    """
    png = tmp_path / "not_a_behavior.png"
    _png(png, 20, 20)
    d = pet_dialogs.BehaviorDialog(pet, pet.behaviors)
    d.show()
    try:
        monkeypatch.setattr(pet_dialogs.QFileDialog, "getOpenFileName",
                            staticmethod(lambda *a, **k: (str(png), "")))
        called = []
        monkeypatch.setattr(pet.behaviors, "import_file",
                            lambda *a, **k: (called.append(1), (None, "不该走到这里"))[1])
        d._import()
        assert called == [], "非 .json 文件被直接丢给了导入器（会抛英文异常）"
        assert ui["warn"], "选错文件却一句话都没有"
        text = ui["warn"][-1][1]
        assert "codec" not in text and "Expecting value" not in text, (
            "把原始英文异常端给了用户：%r" % (text,))
        assert ".json" in text, "没有告诉用户该选什么：%r" % (text,)
        assert "不是行为文件" in text, text
    finally:
        d.hide()


def test_import_json_that_fails_in_the_library_also_gets_a_human_reason(pet, ui, monkeypatch, tmp_path):
    """A7 第二层，**走生产路径**：.json 过了扩展名预检、但库层读失败 → 界面也只出现人话。

    为什么必须单独钉（C 的 A 批把这条判成 NOT CAUGHT）：`_human_import_error` 的单测只调函数
    本身；而 `test_import_non_json_gives_a_human_reason` 在**扩展名预检**就被拦下，
    **永远到不了 `import_file` 的失败分支** —— 于是「库层失败时翻人话」在生产路径上没有任何
    用例守着。这里让**真的** `BehaviorService.import_file` 去读一个 .json 名字的 PNG 字节，
    它必然抛原始英文 codec 异常，再由对话框翻成人话。
    变异：把 `_msg = _human_import_error(_err, _path)` 改回 `_err or "导入失败"` → 本用例红。
    """
    bad = tmp_path / "looks_like_a_behavior.json"
    bad.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 24)   # PNG 魔数 + 二进制垃圾
    before = [x["id"] for x in pet.behaviors.list()]
    d = pet_dialogs.BehaviorDialog(pet, pet.behaviors)
    d.show()
    try:
        monkeypatch.setattr(pet_dialogs.QFileDialog, "getOpenFileName",
                            staticmethod(lambda *a, **k: (str(bad), "")))
        d._import()
        assert ui["warn"], "库层导入失败却一句话都没有"
        text = ui["warn"][-1][1]
        assert "codec" not in text and "decode" not in text and "Expecting value" not in text, (
            "库层的原始英文异常被端给了用户：%r" % (text,))
        assert ".json" in text, "没有告诉用户该选什么：%r" % (text,)
        # 关键：命中库层那条分支（文件名只出现在 _human_import_error 的文案里；
        # 扩展名预检那条路不带文件名）——否则这条用例会被"预检拦下"骗过。
        assert bad.name in text, "没走到库层的翻译分支（被扩展名预检拦下了）：%r" % (text,)
        assert [x["id"] for x in pet.behaviors.list()] == before, "失败却往库里写了东西"
    finally:
        d.hide()

def test_raw_import_errors_are_translated_to_human_reasons():
    """A7 的第二层（真进了库还失败）：原始异常一律翻成人话，原文只进 error.log。

    变异：把 _human_import_error 改成直接 return str(err) → 本用例红。
    """
    raw = ("文件读取失败：" + chr(39) + "utf-8" + chr(39) + " codec can" + chr(39)
           + "t decode byte 0x89 in position 0: invalid start byte")
    got = pet_dialogs._human_import_error(raw, "C:/tmp/x.png")
    assert "codec" not in got and "decode" not in got, got
    assert "不是文本行为文件" in got, got
    got2 = pet_dialogs._human_import_error("Expecting value: line 1 column 1 (char 0)", "y.json")
    assert "Expecting value" not in got2, got2
    assert "JSON" in got2, got2
    # 中文原因原样透传（别把已经说清楚的话再「翻译」一遍）
    assert pet_dialogs._human_import_error("动作序列不能为空", "z.json") == "动作序列不能为空"
    assert pet_dialogs._human_import_error("", "z.json") == "导入失败"


# ==================== A8：统一提交模型（B3 清单） ====================

def test_voice_save_keeps_the_window_and_second_button_is_cancel(pet, ui):
    """A8/B3：VoiceDialog 是工作台（窗内 5 处 _save(silent=True) 就地落盘）→ 保存不关窗；
    第二枚按钮按 R4 从「关闭」改名「取消」（它执行的是 reject）。"""
    d = pet_dialogs.VoiceDialog(pet)
    d.show()
    try:
        btns = _buttons(d)
        assert "取消" in btns and "关闭" not in btns, sorted(btns)
        finished = []
        d.finished.connect(lambda r: finished.append(int(r)))
        d._save()
        assert finished == [], "语音设置保存之后把窗口关了（B3 判它是工作台）"
    finally:
        d.hide()


def test_idle_save_still_closes_and_second_button_is_cancel(pet, ui):
    """A8/B3：IdleDialog 是表单型 → 保存仍关窗（零额外点击），但第二枚按钮改叫「取消」。

    判据是**用户路径一步没多**：保存照旧关窗，改的只是那个说谎的标签。
    """
    d = pet_dialogs.IdleDialog(pet)
    d.show()
    try:
        btns = _buttons(d)
        assert "取消" in btns and "关闭" not in btns, sorted(btns)
        finished = []
        d.finished.connect(lambda r: finished.append(int(r)))
        d._save()
        assert finished, "待机设置的保存没有关窗（表单型应该关窗）"
    finally:
        d.hide()


# ==================== A11：open_idle 的真实入口 ====================

def test_idle_settings_has_a_real_entry_from_the_behavior_dialog(dlg, monkeypatch):
    """A11 / 按钮审计 P3-5：`pet_dialogs.open_idle` 以前**没有 UI 入口**（挂了两轮）。

    这一轮选的是「给入口」：行为设置的「待机设置…」按钮走它（两套视图改的是同一份
    cfg["idle_actions"]，审计 D#4 判的是流程断裂）。
    变异：删掉那个按钮（或改成不接线）→ 第一条断言红。
    """
    btns = _buttons(dlg)
    assert "待机设置…" in btns, "行为设置里没有通往待机设置的门：%r" % (sorted(btns),)
    seen = []

    def _fake_modal(d):
        seen.append(type(d).__name__)
        d.reject()
        return int(QDialog.DialogCode.Rejected)

    monkeypatch.setattr(pet_dialogs, "modal", _fake_modal)
    btns["待机设置…"].click()
    assert seen == ["IdleDialog"], "按钮没有真的打开待机设置：%r" % (seen,)


# ==================== B4（UI 侧）：删行为时清待机引用 ====================

def test_delete_behavior_clears_idle_references(dlg, pet, ui):
    """B4（UI 侧）：删掉被待机列表引用的行为 → cfg["idle_actions"] 不再含它，且有回执。

    改前这里是**死分支**（判的是 pet_config 每次加载都置空的旧键）→ 待机设置里留一条
    「（行为已删除：xxx）」。
    变异：把清理改回死分支 → 第一条断言红。
    """
    b, err = pet.behaviors.add("v290_idle_ref", [{"act": "say", "text": "待机用"}])
    assert b is not None, err
    _clear_cfg(pet, idle_actions=[{"id": b["id"], "behavior_id": b["id"], "enabled": True,
                                   "weight": 1.0, "order": 1}],
               idle_play_mode="single")
    try:
        dlg._refresh()
        assert dlg._select_behavior(b["id"])
        ui["confirm"] = True
        ui["toast"].clear()
        dlg._delete()
        assert pet.behaviors.get(b["id"]) is None, "行为没删掉"
        left = [a for a in (pet.cfg.get("idle_actions") or [])
                if a.get("behavior_id") == b["id"]]
        assert left == [], "删除行为后待机列表里的引用还在：%r" % (pet.cfg.get("idle_actions"),)
        assert "待机列表" in dlg._notes.text(), (
            "清掉引用这件事没有回执：%r" % (dlg._notes.text(),))
    finally:
        _clear_cfg(pet)
        pet.behaviors.delete(b["id"])


# ==================== B5（UI 侧）：待机下拉与配置一致 ====================

def test_idle_combo_shows_the_real_config_state(pet, ui):
    """B5（UI 侧）：配置里有 2 条待机动作时，下拉**不许**再显示「（不启用 → 默认待机）」。

    改前实测：显示「不启用」，点一下就把 2 条覆盖成 1 条（**数据损失面**）。
    变异：把下拉状态改回硬编码「（不启用 → 默认待机）」→ 第一条断言红。
    """
    b1, e1 = pet.behaviors.add("v290_idle_a", [{"act": "say", "text": "a"}])
    b2, e2 = pet.behaviors.add("v290_idle_b", [{"act": "say", "text": "b"}])
    assert b1 is not None and b2 is not None, (e1, e2)
    try:
        _clear_cfg(pet, idle_actions=[
            {"id": b1["id"], "behavior_id": b1["id"], "enabled": True, "weight": 1.0, "order": 1},
            {"id": b2["id"], "behavior_id": b2["id"], "enabled": True, "weight": 1.0, "order": 2},
        ], idle_play_mode="sequential")
        d = pet_dialogs.BehaviorDialog(pet, pet.behaviors)
        d.show()
        try:
            txt = d._idle_combo.currentText()
            assert "不启用" not in txt, "配置里有 2 条待机动作，下拉却说「不启用」：%r" % (txt,)
            assert "2" in txt, "下拉没有如实说清有几条：%r" % (txt,)
            assert d._idle_combo.isEnabled() is False, (
                "多条待机动作时下拉应该是只读的（改多条请去待机设置）")
            assert len(pet.cfg["idle_actions"]) == 2, "只是打开窗口就把配置改了"
        finally:
            d.hide()
    finally:
        _clear_cfg(pet)
        pet.behaviors.delete(b1["id"])
        pet.behaviors.delete(b2["id"])


def test_idle_combo_pick_never_silently_drops_entries(pet, ui):
    """B5（UI 侧）：下拉操作**不许静默丢条目** —— 有得丢就先问，拒绝则原样不动。

    变异：把 idle_single_change(apply=False) 那段确认去掉（直接 apply=True）→ 第二条断言红。
    """
    b1, e1 = pet.behaviors.add("v290_idle_c", [{"act": "say", "text": "c"}])
    b2, e2 = pet.behaviors.add("v290_idle_d", [{"act": "say", "text": "d"}])
    assert b1 is not None and b2 is not None, (e1, e2)
    try:
        _clear_cfg(pet, idle_actions=[
            {"id": b1["id"], "behavior_id": b1["id"], "enabled": True, "weight": 1.0, "order": 1},
            {"id": b2["id"], "behavior_id": b2["id"], "enabled": True, "weight": 1.0, "order": 2},
        ], idle_play_mode="sequential")
        d = pet_dialogs.BehaviorDialog(pet, pet.behaviors)
        d.show()
        try:
            # 只读态是给"多条"用的（上一条用例测了）；这里直接给这个处理器一份确定的
            # 输入 = "用户在下拉里选了 B2"，看它会不会静默把那 2 条丢掉。
            d._idle_combo.blockSignals(True)
            d._idle_combo.clear()
            d._idle_combo.addItem(pet_behaviors.IDLE_COMBO_OFF_LABEL, "")
            d._idle_combo.addItem("空闲时：" + b2["name"], b2["id"])
            d._idle_combo.setCurrentIndex(1)
            d._idle_combo.blockSignals(False)
            ui["confirm"] = False
            ui["confirm_calls"].clear()
            d._on_idle_pick(1)
            assert ui["confirm_calls"], "会把 2 条丢成 1 条却连问都不问"
            assert len(pet.cfg["idle_actions"]) == 2, (
                "用户点了取消，条目还是被丢了：%r" % (pet.cfg["idle_actions"],))
            assert {a["behavior_id"] for a in pet.cfg["idle_actions"]} == {b1["id"], b2["id"]}
            # 明确同意 → 才允许变成 1 条（且是用户选的那条）
            # 上一次被拒之后 _refresh() 已经按配置重建过组合框（多条 → 只读单行），
            # 所以这里要重新摆一遍"用户在下拉里选了 B2"这个输入
            ui["confirm"] = True
            d._idle_combo.blockSignals(True)
            d._idle_combo.clear()
            d._idle_combo.addItem(pet_behaviors.IDLE_COMBO_OFF_LABEL, "")
            d._idle_combo.addItem("空闲时：" + b2["name"], b2["id"])
            d._idle_combo.setCurrentIndex(1)
            d._idle_combo.blockSignals(False)
            d._on_idle_pick(1)
            acts = pet.cfg["idle_actions"]
            assert len(acts) == 1 and acts[0]["behavior_id"] == b2["id"], acts
            assert pet.cfg["idle_play_mode"] == "single", pet.cfg["idle_play_mode"]
        finally:
            d.hide()
    finally:
        _clear_cfg(pet)
        pet.behaviors.delete(b1["id"])
        pet.behaviors.delete(b2["id"])


# ==================== B6（UI 侧）：保存失败不许试播旧内容 ====================

def test_test_play_does_not_play_when_save_fails(dlg, pet, ui, monkeypatch):
    """B6（UI 侧）：保存失败 → **不播** + 状态行说清原因（改前会播上一次保存的旧内容）。

    变异：把 _save 的返回值丢掉（或恢复「失败也播」）→ 第一条断言红。
    """
    played = []
    monkeypatch.setattr(pet, "_run_behavior", lambda bid: played.append(bid))
    b, err = pet.behaviors.add("v290_play_ok", [{"act": "say", "text": "能播的"}])
    assert b is not None, err
    try:
        dlg._refresh()
        assert dlg._select_behavior(b["id"])
        dlg._name.setText("1bad")          # 故意改成非法名 → 保存必定失败
        ui["toast"].clear()
        dlg._test_play()
        assert played == [], "保存失败却播了（播的还是上一次保存的旧内容）：%r" % (played,)
        assert dlg._notes.text(), "不播了却不说为什么"
        assert "保存" in dlg._notes.text(), dlg._notes.text()
    finally:
        pet.behaviors.delete(b["id"])


def test_test_play_plays_and_does_not_say_saved_twice(dlg, pet, ui, monkeypatch):
    """B6 的另一半（审计 #8）：正常试播**不再顺带弹「已保存」**，回执只有一句。"""
    played = []
    monkeypatch.setattr(pet, "_run_behavior", lambda bid: played.append(bid))
    dlg._act_combo.setCurrentIndex(dlg._act_combo.findData("say"))
    dlg._param.setText("试播内容")
    dlg._add_step()
    dlg._name.setText("v290_play_ok2")
    ui["toast"].clear()
    dlg._test_play()
    assert len(played) == 1, "没播（或播了不止一次）：%r" % (played,)
    assert ui["toast"] == [], "试播顺带弹了回执：%r" % (ui["toast"],)
    assert "试播" in dlg._notes.text(), dlg._notes.text()
    got = [x for x in pet.behaviors.list() if x["name"] == "v290_play_ok2"]
    assert got, "试播前那次保存没写进库里"
    pet.behaviors.delete(got[0]["id"])


# ==================== A6：删自定义动作不再二次确认（有意撤销上一轮） ====================

def test_delete_custom_action_can_be_undone_by_cancelling(tmp_path):
    """A6：删自定义动作**不再**二次确认（暂存态、可整体放弃）；删掉后取消能恢复。

    这是**有意撤销上一轮（v2.8.0 D14）**加的那个确认：给可撤销操作套不可逆确认 =
    多一步 + 误导（旧文案自己都写着「这一步只是暂存…取消会放弃全部改动」）。
    加强式改写：原来断言「弹了确认」，现在断言「没弹确认 **且** 取消之后角色没变」。
    """
    a = tmp_path / "u_a.png"
    _png(a, 50, 50)
    lib = pet_resources.RoleLibrary(str(tmp_path))
    role, err = lib.import_processed(str(a), None, "undo")
    assert role is not None and err is None, err
    rid = role["id"]
    before = json.dumps(lib.get(rid), ensure_ascii=False, sort_keys=True)
    confirms = []
    # 三件套一起换（v2.9.0 规矩：被测路径可能弹真框就先全 stub —— 否则"本该红"会变成"挂住"）
    orig_confirm, orig_warn = pet_dialogs._confirm, pet_dialogs._warn
    orig_info = pet_dialogs._info
    pet_dialogs._confirm = lambda _p, t, x: (confirms.append((t, x)), True)[1]
    pet_dialogs._warn = lambda _p, t, x: None
    pet_dialogs._info = lambda _p, t, x: None
    try:
        d = pet_dialogs.RoleEditDialog(None, lib, rid)
        try:
            d._cur_idx = 0
            d._forms[0]["procs"] = {"v290_undo": {"kind": "breathe", "amp": 0.02,
                                                  "period_ms": 2000}}
            d._refresh_act_list()
            d._act_list.setCurrentRow(0)
            d._del_action()
            assert confirms == [], "删自定义动作还在弹二次确认：%r" % (confirms,)
            assert "v290_undo" not in (d._forms[0].get("procs") or {}), "没删掉"
        finally:
            d._cleanup()
    finally:
        pet_dialogs._confirm, pet_dialogs._warn = orig_confirm, orig_warn
        pet_dialogs._info = orig_info
    # 「删掉后可取消恢复」：那个删除从头到尾只活在暂存态里，角色一个字节都没变
    assert json.dumps(lib.get(rid), ensure_ascii=False, sort_keys=True) == before, (
        "暂存态里的删除被写进了角色（取消本该整体放弃）")



# ==================== 质量审 6：A2 的"立即生效"必须说清 + 给撤销入口 ====================

def test_import_images_says_it_takes_effect_now(pet, ui, tmp_path):
    """质量审 6：行为设置里这个入口**立即写进角色**，必须写在按钮旁边（不能只靠猜）。

    它和角色编辑里的同名动作**语义相反**（那边是暂存态、取消即放弃）—— 所以文案里要有
    「立即」二字，否则用户会以为关窗就撤销了。
    变异：把 _target_text 改回不含「立即」的那句 → 本用例红。
    """
    old_rid = str(pet.cfg.get("role") or "")
    _install_role(pet, tmp_path, "v290角色5")   # 要有可编辑的角色才走"能加"那一支
    d = pet_dialogs.BehaviorDialog(pet, pet.behaviors)
    d.show()
    try:
        txt = d._act_target.text()
        assert "立即" in txt, "按钮旁没说清这一步立即生效：%r" % (txt,)
        assert "撤销" in txt, "没说清可以撤销：%r" % (txt,)
    finally:
        d.hide()
        pet.apply_role(old_rid)


def test_import_images_can_be_undone_from_the_dialog(pet, ui, monkeypatch, tmp_path):
    """质量审 6：加完有**真的撤销入口**（立即生效 ≠ 不能收回）。

    撤销必须把索引改回去**并且**删掉帧文件（否则角色目录里留孤兒）。
    变异：把 _undo_pic_import 里那次 sink.undo(...) 去掉 → 前两条断言红。
    """
    old_rid = str(pet.cfg.get("role") or "")
    rid = _install_role(pet, tmp_path, "v290角色4")
    srcs = [tmp_path / "z1.png", tmp_path / "z2.png"]
    _png(srcs[0], 40, 40, 0xFF207040)
    _png(srcs[1], 44, 40, 0xFF207099)
    d = pet_dialogs.BehaviorDialog(pet, pet.behaviors)
    d.show()
    try:
        roles_dir = pet.role_lib._dir
        before_files = sorted(os.listdir(roles_dir))
        assert d._undo_pic_btn.isHidden() is True, "还没导入就把撤销按钮亮着"
        monkeypatch.setattr(pet_dialogs.QFileDialog, "getOpenFileNames",
                            staticmethod(lambda *a, **k: ([str(p) for p in srcs], "")))
        monkeypatch.setattr(pet_dialogs, "_ask_text", lambda *a, **k: ("v290_undo_act", True))
        d._import_frame_action()
        anims = ((pet.role_lib.get(rid) or {}).get("forms") or [{}])[0].get("animations") or {}
        assert "v290_undo_act" in anims, "用例前提：动作没加进去"
        assert d._undo_pic_btn.isHidden() is False, "加完不给撤销入口（用户会以为取消就没了）"
        assert "撤销" in d._notes.text(), d._notes.text()
        d._undo_pic_btn.click()          # 走真按钮（接线断了这条会红）
        anims2 = ((pet.role_lib.get(rid) or {}).get("forms") or [{}])[0].get("animations") or {}
        assert "v290_undo_act" not in anims2, "撤销之后动作还在角色上：%r" % (anims2,)
        assert sorted(os.listdir(roles_dir)) == before_files, (
            "撤销之后帧文件没删掉（留孤儿）：%r" % (sorted(os.listdir(roles_dir)),))
        assert "已撤销" in d._notes.text(), d._notes.text()
        assert d._undo_pic_btn.isHidden() is True, "撤销完按钮还亮着"
    finally:
        d.hide()
        pet.apply_role(old_rid)


# ==================== 审计 #11：待机设置的边界回执 ====================

def test_idle_move_at_boundary_says_so(pet, ui):
    """审计清单 #11：待机设置「上移/下移」到顶/到底以前**静默**（顺序不变、零反馈）。

    措辞照抄台词库那句（同一语义同一句话），渠道走窗口内状态行（同 A3/A4 口径）。
    变异：把 _move 里那个边界分支删掉 → 第一条断言红。
    """
    b1, e1 = pet.behaviors.add("v290_idle_m1", [{"act": "say", "text": "m1"}])
    b2, e2 = pet.behaviors.add("v290_idle_m2", [{"act": "say", "text": "m2"}])
    assert b1 is not None and b2 is not None, (e1, e2)
    try:
        _clear_cfg(pet, idle_actions=[
            {"id": b1["id"], "behavior_id": b1["id"], "enabled": True, "weight": 1.0, "order": 1},
            {"id": b2["id"], "behavior_id": b2["id"], "enabled": True, "weight": 1.0, "order": 2},
        ], idle_play_mode="sequential")
        d = pet_dialogs.IdleDialog(pet)
        d.show()
        try:
            d._table.setCurrentCell(0, 0)
            d._move(-1)
            assert "已经是最上面了" in d._move_note.text(), d._move_note.text()
            assert [a["behavior_id"] for a in d._idle["idle_actions"]] == [b1["id"], b2["id"]]
            d._table.setCurrentCell(1, 0)
            d._move(1)
            assert "已经是最下面了" in d._move_note.text(), d._move_note.text()
            d._table.setCurrentCell(1, 0)
            d._move(-1)
            assert "上移" in d._move_note.text(), d._move_note.text()
            assert [a["behavior_id"] for a in d._idle["idle_actions"]] == [b2["id"], b1["id"]]
        finally:
            d.hide()
    finally:
        _clear_cfg(pet)
        pet.behaviors.delete(b1["id"])
        pet.behaviors.delete(b2["id"])


# ==================== 质量审 F1 / 兼容审：R4 反例（AlarmDialog / LinesDialog） ====================

def test_alarm_second_button_is_cancel_and_guards_the_draft(pet, ui):
    """F1：闹钟第二枚按钮原来叫「关闭」→ `accept()`，丢弃草稿**零提示**（R4 硬反例）。

    修法：改名「取消」= `reject()`；有草稿先问，没改动直接关（零额外一步）。
    变异：把按钮改回 ("关闭", self.accept) → 第一条断言红；去掉 _cancel 的确认 → 第三条红。
    """
    d = pet_dialogs.AlarmDialog(pet)
    d.show()
    try:
        btns = _buttons(d)
        assert "取消" in btns and "关闭" not in btns, sorted(btns)
        finished = []
        d.finished.connect(lambda r: finished.append(int(r)))
        # ① 没有改动 → 直接关，不多问一步
        ui["confirm_calls"].clear()
        d._cancel()
        assert ui["confirm_calls"] == [], "没有任何草稿却弹了确认框（多一步）"
        assert finished == [int(QDialog.DialogCode.Rejected)], finished
    finally:
        d.hide()
    d2 = pet_dialogs.AlarmDialog(pet)
    d2.show()
    try:
        d2._label.setText("v290_alarm_draft")
        assert d2._is_dirty(), "用例前提：填了草稿应该是脏的"
        finished2 = []
        d2.finished.connect(lambda r: finished2.append(int(r)))
        ui["confirm"] = False
        ui["confirm_calls"].clear()
        d2._cancel()
        assert ui["confirm_calls"], "有未保存草稿却直接关窗（草稿静默丢弃）"
        assert finished2 == [], "用户点了「回去接着改」，窗口却关了"
        ui["confirm"] = True
        d2._cancel()
        assert finished2 == [int(QDialog.DialogCode.Rejected)], finished2
    finally:
        d2.hide()
    assert not [a for a in pet.alarms.list() if a.get("label") == "v290_alarm_draft"], \
        "点取消却把草稿存进库了"


def test_lines_second_button_is_cancel_and_guards_the_editor(pet, ui):
    """兼容审：台词设置第二枚按钮原来叫「关闭」→ `accept()`，会丢编辑器的草稿（R4 反例）。"""
    d = pet_dialogs.LinesDialog(pet)
    d.show()
    try:
        btns = _buttons(d)
        assert "取消" in btns and "关闭" not in btns, sorted(btns)
        d._text.setPlainText("v290 台词草稿没保存")
        assert d._is_dirty(), "用例前提：改了编辑器应该是脏的"
        finished = []
        d.finished.connect(lambda r: finished.append(int(r)))
        ui["confirm"] = False
        ui["confirm_calls"].clear()
        d._cancel()
        assert ui["confirm_calls"], "有未保存的台词草稿却直接关窗"
        assert finished == [], "用户点了「回去接着改」，窗口却关了"
        assert d._text.toPlainText() == "v290 台词草稿没保存", "拒绝之后草稿没了"
        ui["confirm"] = True
        d._cancel()
        assert finished == [int(QDialog.DialogCode.Rejected)], finished
    finally:
        d.hide()


def test_lines_cancel_without_edits_does_not_ask(pet, ui):
    """A5 的反向（**零额外点击**）：编辑器没改动 → 直接关，不许多问一步。

    这条是给 `_DiscardGuard` 上的保险：确认只有在**真脏**时才出现。
    变异：把 _confirm_discard 里的 `not self._is_dirty()` 去掉（无脑弹）→ 本用例红。
    """
    d = pet_dialogs.LinesDialog(pet)
    d.show()
    try:
        assert not d._is_dirty(), "刚打开就判成脏的（会凭空多出一步）"
        finished = []
        d.finished.connect(lambda r: finished.append(int(r)))
        ui["confirm_calls"].clear()
        d._cancel()
        assert ui["confirm_calls"] == [], "没有改动却弹了确认框（多一步）"
        assert finished == [int(QDialog.DialogCode.Rejected)], finished
    finally:
        d.hide()


def test_alarm_cancel_without_edits_does_not_ask(pet, ui):
    """A5 的反向（**零额外点击**）：闹钟没改动 → 直接关（点「新建」之后也算干净）。

    点「新建」会重置表单并置 _ring_dirty —— 那是"保存时要写默认铃声"的标记，**不是**脏。
    变异：让 _reset_form 不更新基线 → 点完「新建」关窗就会凭空多问一步 → 本用例红。
    """
    d = pet_dialogs.AlarmDialog(pet)
    d.show()
    try:
        d._new()                      # 清空表单进入新建态
        assert not d._is_dirty(), "点完「新建」就判成脏的（关窗时会凭空多问一步）"
        finished = []
        d.finished.connect(lambda r: finished.append(int(r)))
        ui["confirm_calls"].clear()
        d._cancel()
        assert ui["confirm_calls"] == [], "点完「新建」直接关窗却弹了确认框"
        assert finished == [int(QDialog.DialogCode.Rejected)], finished
    finally:
        d.hide()


# ==================== 找茬 F-2：待机下拉的确认只该在"条目数真的变少"时出现 ====================

def test_idle_pick_replacing_one_entry_does_not_ask(pet, ui):
    """F-2：配置里只有 1 条待机、用户改选另一条 → **条目数 1 变 1 没减少**，不该问。

    改前判据是 `if dropped`，而 dropped = "所有 behavior_id ≠ 选中项的条目" —— 1 条时也非空，
    于是弹「还有另外 1 条动作…」，而被丢的**正是用户要换掉的那条**。这就是用户抱怨的"多一步"。
    变异：把判据改回 `if dropped` → 第一条断言红。
    """
    b1, e1 = pet.behaviors.add("v290_idle_e", [{"act": "say", "text": "e"}])
    b2, e2 = pet.behaviors.add("v290_idle_f", [{"act": "say", "text": "f"}])
    assert b1 is not None and b2 is not None, (e1, e2)
    try:
        _clear_cfg(pet, idle_actions=[
            {"id": b1["id"], "behavior_id": b1["id"], "enabled": True, "weight": 1.0, "order": 1},
        ], idle_play_mode="single")
        d = pet_dialogs.BehaviorDialog(pet, pet.behaviors)
        d.show()
        try:
            # 给下拉摆一份"用户选了 B2"的确定输入（single 态下它是可编辑的）
            d._idle_combo.blockSignals(True)
            d._idle_combo.clear()
            d._idle_combo.addItem(pet_behaviors.IDLE_COMBO_OFF_LABEL, "")
            d._idle_combo.addItem("空闲时：" + b1["name"], b1["id"])
            d._idle_combo.addItem("空闲时：" + b2["name"], b2["id"])
            d._idle_combo.setCurrentIndex(2)
            d._idle_combo.blockSignals(False)
            ui["confirm_calls"].clear()
            d._on_idle_pick(2)
            assert ui["confirm_calls"] == [], (
                "只是换一条（1 条 → 1 条，条目数没减少）却弹了确认框：%r" % (ui["confirm_calls"],))
            acts = pet.cfg["idle_actions"]
            assert len(acts) == 1 and acts[0]["behavior_id"] == b2["id"], acts
        finally:
            d.hide()
    finally:
        _clear_cfg(pet)
        pet.behaviors.delete(b1["id"])
        pet.behaviors.delete(b2["id"])


# ==================== 找茬 F-4：插件管理第三处 R4 反例 ====================

def test_plugin_second_button_is_cancel_and_guards_the_url(pet, ui):
    """F-4：插件管理「关闭」原来走 `reject()`，而地址框只由「保存并使用」落盘 → 静默丢弃。

    修法同 R4/A5：改名「取消」；**有改动才问**，没改动直接关（零额外一步）。
    变异：把按钮改回 ("关闭" → self.reject) 且不接 _cancel → 第一条断言红。
    """
    d = pet_dialogs.PluginManagerDialog(pet)
    d.show()
    try:
        btns = _buttons(d)
        assert "取消" in btns and "关闭" not in btns, sorted(btns)
        finished = []
        d.finished.connect(lambda rr: finished.append(int(rr)))
        ui["confirm_calls"].clear()
        d._cancel()
        assert ui["confirm_calls"] == [], "地址框没改动却弹了确认框（多一步）"
        assert finished == [int(QDialog.DialogCode.Rejected)], finished
    finally:
        d.hide()
    d2 = pet_dialogs.PluginManagerDialog(pet)
    d2.show()
    try:
        d2._url_edit.setText("https://v290.invalid/index.json")
        assert d2._is_dirty(), "用例前提：改了地址框应该是脏的"
        finished2 = []
        d2.finished.connect(lambda rr: finished2.append(int(rr)))
        ui["confirm"] = False
        ui["confirm_calls"].clear()
        d2._cancel()
        assert ui["confirm_calls"], "地址框有未保存的编辑却直接关窗（静默丢弃）"
        assert finished2 == [], "用户点了「回去接着编辑」，窗口却关了"
        ui["confirm"] = True
        d2._cancel()
        assert finished2 == [int(QDialog.DialogCode.Rejected)], finished2
    finally:
        d2.hide()


# ==================== 质量审 F2：换列表条目也要问（关窗那条路的同一个病） ====================

def test_switching_rows_asks_before_dropping_the_draft(dlg, pet, ui):
    """F2：**换列表条目**同样会丢掉未保存的表单 —— 改前这条路静默丢弃（实测 0 弹框）。
    A5 当时只补了"关窗"那条路，同一个病在 `_on_sel`（currentRowChanged）上原样留着。
    拒绝时不仅要不切，还要把**选中行拨回去**（否则界面看着已经切了、内容还是旧的）。
    变异：去掉 _on_sel 开头那句 _confirm_discard(latch=False, why="switch") → 第一/二条断言红。
    """
    a, e1 = pet.behaviors.add("v290_switch_a", [{"act": "say", "text": "a"}])
    b, e2 = pet.behaviors.add("v290_switch_b", [{"act": "say", "text": "b"}])
    assert a is not None and b is not None, (e1, e2)
    try:
        dlg._refresh()
        assert dlg._select_behavior(a["id"]), "用例前提：A 没出现在列表里"
        dlg._name.setText("v290_switch_a_edited")     # 弄脏
        assert dlg._is_dirty(), "用例前提：表单应该是脏的"
        ui["confirm"] = False
        ui["confirm_calls"].clear()
        dlg._list.setCurrentRow(dlg._row_of(b["id"]))    # 用户点了另一条
        assert ui["confirm_calls"], "换条目却直接丢掉了未保存的编辑"
        assert dlg._editing_id == a["id"], "点了「回去接着改」却还是切过去了"
        assert dlg._name.text() == "v290_switch_a_edited", "拒绝之后草稿没了"
        assert dlg._list.currentRow() == dlg._row_of(a["id"]), "选中行没拨回去（界面与内容不一致）"
        ui["confirm"] = True
        dlg._list.setCurrentRow(dlg._row_of(b["id"]))
        assert dlg._editing_id == b["id"], "确认之后没切过去"
        assert dlg._name.text() == "v290_switch_b", dlg._name.text()
    finally:
        pet.behaviors.delete(a["id"])
        pet.behaviors.delete(b["id"])


def test_plugin_window_close_also_guards_the_url(pet, ui):
    """F-4 的另一道门（父代理裁决）：**标题栏 × 与「取消」是同一道门**，也要问。

    「手填地址静默丢弃」这个病灶不止按钮一条路 —— 只修按钮，同一份损失还有一道门开着。
    变异：把 closeEvent 里的 `_confirm_discard` 去掉 → 第二条断言红。
    """
    d = pet_dialogs.PluginManagerDialog(pet)
    d.show()
    try:
        d._url_edit.setText("https://v290.invalid/index.json")
        assert d._is_dirty(), "用例前提：改了地址框应该是脏的"
        ui["confirm"] = False
        ui["confirm_calls"].clear()
        d.close()                       # 模拟标题栏 ×
        assert ui["confirm_calls"], "标题栏 × 直接关窗，地址框里的编辑静默丢了"
        assert d.isVisible(), "用户点了「回去接着编辑」，窗口却没了"
        ui["confirm"] = True
        ui["confirm_calls"].clear()
        d.close()
        assert len(ui["confirm_calls"]) == 1, (
            "标题栏 × 应该**只问一次**（closeEvent 之后 Qt 还会调到 reject，靠一次性令牌防连问）：%r"
            % (ui["confirm_calls"],))
        QApplication.processEvents()
        assert d.isVisible() is False, "确认放弃之后窗口没关"
    finally:
        d.hide()


# ==================== 独立验收 F-A：点「保存」绝不该弹确认（最刺眼的"多一步"） ====================

def test_saving_never_asks_to_discard(dlg, pet, ui):
    """F-A（独立验收实测）：保存成功后 `_select_behavior` 会显式调 `_on_sel` → 未保存检查，

    而当时基线**还没**对齐到"刚保存的内容" → 判成脏 → **点一次「保存」反而被问一句
    "要不要放弃"**。修法：基线必须先于 `_select_behavior` 对齐。
    变异：把 `_baseline = self._form_signature()` 挪回 `_select_behavior` 之后 → 本用例红。
    """
    dlg._new()
    dlg._act_combo.setCurrentIndex(dlg._act_combo.findData("say"))
    dlg._param.setText("v290_save_no_prompt")
    dlg._add_step()
    dlg._name.setText("v290_save_no_prompt")
    ui["confirm_calls"].clear()
    assert dlg._save() is True, "用例前提：保存要成功"
    assert ui["confirm_calls"] == [], (
        "点一次「保存」却弹了确认框（保存完反而问要不要放弃）：%r" % (ui["confirm_calls"],))
    # 控制组：**改一次再点保存**同样一次都不问（编辑态走 update 分支，同样会 _select_behavior）
    dlg._name.setText("v290_save_no_prompt2")
    ui["confirm_calls"].clear()
    assert dlg._save() is True, "用例前提：再保存也要成功"
    assert ui["confirm_calls"] == [], (
        "编辑态保存也弹了确认框：%r" % (ui["confirm_calls"],))
    got = [x for x in pet.behaviors.list() if x["name"] == "v290_save_no_prompt2"]
    assert got, "命名没落库"
    pet.behaviors.delete(got[0]["id"])


def test_alarm_saving_never_asks_to_discard(pet, ui):
    """F-A 的另一半：闹钟「保存」同样不许弹确认（同一个顺序问题，同一轮修）。

    变异：把 AlarmDialog._save 里的 `_baseline` 挪到 `_on_sel(_i)` 之后 → 本用例红。
    """
    d = pet_dialogs.AlarmDialog(pet)
    d.show()
    try:
        d._label.setText("v290_alarm_no_prompt")
        d._time.setTime(pet_dialogs.QTime(6, 30))
        ui["confirm_calls"].clear()
        d._save()
        assert ui["confirm_calls"] == [], (
            "点一次闹钟「保存」却弹了确认框：%r" % (ui["confirm_calls"],))
        assert [a for a in pet.alarms.list() if a.get("label") == "v290_alarm_no_prompt"], (
            "用例前提：闹钟没存进去")
    finally:
        d.hide()
    # 清理
    for a in pet.alarms.list():
        if a.get("label") == "v290_alarm_no_prompt":
            pet.alarms.delete(a["id"])


# ============ 找茬 delta 复跑 M15：换条目那次确认不许给"之后的关窗"免问 ============

def test_switch_confirm_does_not_grant_a_later_close(dlg, pet, ui):
    """M15（找茬 delta 复跑）：**换条目时的那次确认，绝不许给之后的关窗"免问"**。

    改前的闩是"置位后一直有效"：换条目确认过一次 → 再编辑 → 点标题栏 × → **0 次确认、
    窗口关掉、改动静默丢**（探针实测；而当时全量 1339 passed，没人抓）。
    现在"闩"是一次性令牌：只在 closeEvent→reject 那一跳内有效，永不跨过用户的下一次操作。
    变异：让 `_confirm_discard` 在任意一次确认后把 `_close_confirmed` 置位且不清（退回旧闩）
    → 本用例红。
    """
    a, e1 = pet.behaviors.add("v290_latch_a", [{"act": "say", "text": "a"}])
    b, e2 = pet.behaviors.add("v290_latch_b", [{"act": "say", "text": "b"}])
    assert a is not None and b is not None, (e1, e2)
    try:
        dlg._refresh()
        assert dlg._select_behavior(a["id"])
        dlg._name.setText("v290_latch_a_edited")          # 弄脏
        ui["confirm"] = True                              # 换条目：同意放弃
        ui["confirm_calls"].clear()
        dlg._list.setCurrentRow(dlg._row_of(b["id"]))
        assert ui["confirm_calls"], "用例前提：换条目应该问过一次"
        assert dlg._editing_id == b["id"], "用例前提：应该切到 B 了"
        # 再弄脏，然后走**关窗**这条路（标题栏 × / closeEvent）
        dlg._name.setText("v290_latch_b_edited")
        assert dlg._is_dirty(), "用例前提：应该是脏的"
        ui["confirm"] = False
        ui["confirm_calls"].clear()
        dlg.close()
        assert ui["confirm_calls"], (
            "换条目那次确认把后面的关窗也免问了 → 改动静默丢（M15 复现）")
        assert dlg.isVisible(), "拒绝之后窗口被关掉了"
    finally:
        pet.behaviors.delete(a["id"])
        pet.behaviors.delete(b["id"])


# ============ 找茬 delta 复跑 M8b：选中已有闹钟 → 新建 → 取消，不该弹 ============

def test_alarm_new_after_select_does_not_ask(pet, ui):
    """M8b：**先选中一条已有闹钟 → 再点「新建」→ 取消** 不该弹确认。

    这条路径此前**没有任何用例覆盖**：现有那条用的是"刚打开的窗口"，前后基线本来就一样，
    所以"`_reset_form` 不更新基线"这类变异不会红（找茬的探针正是这么发现的）。
    变异：把 `AlarmDialog._reset_form` 末尾的 `_baseline = self._form_signature()` 去掉 → 本用例红。
    """
    a, err = pet.alarms.add("06:45", "v290_alarm_sel", "", enabled=True)
    assert a is not None, err
    d = pet_dialogs.AlarmDialog(pet)
    d.show()
    try:
        assert d._list.count() >= 1, "用例前提：库里得有闹钟"
        d._list.setCurrentRow(0)                  # 选中已有闹钟（表单被它填满）
        assert d._editing_id == a["id"], "用例前提：应该载入了那条闹钟"
        d._new()                                  # 点「新建」= 清成默认草稿（不是用户改动）
        assert not d._is_dirty(), "点完「新建」就判成脏的（关窗时会凭空多问一步）"
        finished = []
        d.finished.connect(lambda rr: finished.append(int(rr)))
        ui["confirm_calls"].clear()
        d._cancel()
        assert ui["confirm_calls"] == [], (
            "选中已有闹钟 → 新建 → 取消，却弹了确认框（多一步）：%r" % (ui["confirm_calls"],))
        assert finished == [int(QDialog.DialogCode.Rejected)], finished
    finally:
        d.hide()
        for x in pet.alarms.list():
            if x.get("label") == "v290_alarm_sel":
                pet.alarms.delete(x["id"])
