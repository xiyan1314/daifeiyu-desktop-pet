# -*- coding: utf-8 -*-
"""v2.4 对话框闭环回归（item D）：offscreen + 真 PetWindow，覆盖"打开→改值→保存→落盘"。

约定（照做，别改成模态 exec）：
  · 一律 show() + 直接调 _save()/_save_line()/accept()——**不 exec()**：
    offscreen 下模态 exec 会阻塞测试进程；
  · 落盘一律以**重新读文件/重新建对话框**为准（config.json / memory.json /
    lines.json / roles.json），不看内存里的 dict；
  · 每条用例都带"控制组"（该变的必须变、不该变的一个字节都不能动），
    避免"永远通过"的空转断言（上一轮审查抓到过这种）。
"""
import json
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import 桌宠 as main  # noqa: E402
import pet_chat  # noqa: E402
import pet_dialogs  # noqa: E402

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402


@pytest.fixture(scope="module")
def pet(tmp_path_factory):
    """真 PetWindow + 全部运行时路径指向临时目录（退出时还原进程级全局）。"""
    import pet_log
    import pet_resources
    tmp = tmp_path_factory.mktemp("dlg24")
    _snap = (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
             getattr(pet_log, "_data_dir", None), getattr(main, "_redact_key", None),
             getattr(pet_resources, "FRAME_MAX", None))
    main.DATA_DIR = str(tmp)
    main.CONFIG_PATH = str(tmp / "config.json")
    main.USAGE_PATH = str(tmp / "usage.json")
    main.MEMORY_PATH = str(tmp / "memory.json")
    import pet_lines
    if hasattr(pet_lines, "LINES_PATH"):
        pass  # 台词库路径由 LineService 自己按 DATA_DIR 取，不需要额外补丁
    pet_log.set_data_dir(str(tmp))
    QApplication.instance() or QApplication([])
    win = main.PetWindow()
    from helpers_roles import install_three_form_role
    install_three_form_role(win, tmp)
    yield win
    try:
        win._closing = True
        win.voice.stop()
        win.hide()
        win.deleteLater()
    except Exception:
        pass  # 有意忽略：测试收尾
    (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH,
     main.MEMORY_PATH) = _snap[0], _snap[1], _snap[2], _snap[3]
    pet_log.set_data_dir(_snap[4])
    main.set_redact_key(_snap[5] or "")
    if _snap[6] is not None:
        pet_resources.FRAME_MAX = _snap[6]


def _disk_cfg():
    """从磁盘重新读配置（不看内存 dict）。"""
    return main.load_config()


# ---------------- 1) AISettingsDialog ----------------

def test_ai_settings_dialog_save_roundtrip(pet):
    """打开→改值→保存→**落盘**：模型/地址/字数/max_tokens/工具开关全部可往返。"""
    dlg = pet_dialogs.AISettingsDialog(pet)
    dlg.show()
    try:
        dlg._base.setText("http://127.0.0.1:11434/v1/")   # 末尾斜杠必须被吃掉
        dlg._model.setText("qwen2.5:7b")
        dlg._reply.setValue(18)
        dlg._tokens.setValue(80)
        dlg._tools.setChecked(False)
        dlg._tools_confirm.setChecked(False)
        dlg._save()
    finally:
        dlg.hide()

    cfg = _disk_cfg()
    assert cfg["ai_base_url"] == "http://127.0.0.1:11434/v1", "地址没落盘或没去尾斜杠"
    assert cfg["ai_model"] == "qwen2.5:7b"
    assert cfg["ai_reply_len"] == 18
    assert cfg["ai_max_tokens"] == 80
    assert cfg["ai_tools_enabled"] is False
    assert cfg["ai_tools_confirm"] is False

    # 控制组：重新打开必须回填刚才保存的值（否则"落盘成功"这条断言是空转的）
    dlg2 = pet_dialogs.AISettingsDialog(pet)
    dlg2.show()
    try:
        assert dlg2._model.text() == "qwen2.5:7b"
        assert dlg2._reply.value() == 18
        assert dlg2._tools.isChecked() is False
    finally:
        dlg2.hide()


def test_ai_settings_privacy_switch_persists_both_ways(pet):
    """v2.4：ai_rag_enabled 隐私开关必须有界面入口，且两个方向都能落盘。

    这条用例对应用户可见缺陷：README/发布说明写着"AI 设置里可关"，但对话框此前
    既不展示也不提交该键——用户实际关不掉。
    """
    assert hasattr(pet_dialogs.AISettingsDialog(pet), "_rag"), "隐私开关控件不存在"

    dlg = pet_dialogs.AISettingsDialog(pet)
    dlg.show()
    try:
        assert dlg._rag.isChecked() is True, "默认应为开启（与 DEFAULT_CONFIG 一致）"
        dlg._rag.setChecked(False)
        dlg._save()
    finally:
        dlg.hide()
    assert _disk_cfg()["ai_rag_enabled"] is False, "关掉隐私开关没有落盘"

    dlg2 = pet_dialogs.AISettingsDialog(pet)
    dlg2.show()
    try:
        assert dlg2._rag.isChecked() is False, "重新打开没有回填 False（开关没接配置）"
        dlg2._rag.setChecked(True)      # 控制组：反向也要能存回去
        dlg2._save()
    finally:
        dlg2.hide()
    assert _disk_cfg()["ai_rag_enabled"] is True


def test_ai_settings_clear_long_term_keeps_history(pet, monkeypatch):
    """「清除长期记忆」按钮：long_term 落盘清空，**对话历史必须保留**。"""
    pet_chat.write_long_term(main.MEMORY_PATH, {
        "user_name": "绳匠", "nicknames": ["小鱼干"], "preferences": ["睡懒觉"],
        "dislikes": ["加班"], "recent_topics": ["记账"]}, log=None)
    # history 的格式是 [role, content] 二元组列表（见 pet_chat.read_memory）
    main.save_chat_memory([["user", "你好"], ["assistant", "嘶~"]])
    assert pet_chat.read_long_term(main.MEMORY_PATH).get("user_name") == "绳匠", "用例前提不成立"
    assert len(main.load_chat_memory()) == 2, "用例前提不成立（历史没写进去）"

    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: QMessageBox.StandardButton.Ok)
    dlg = pet_dialogs.AISettingsDialog(pet)
    dlg.show()
    try:
        dlg._clear_long_term()
    finally:
        dlg.hide()

    lt = pet_chat.read_long_term(main.MEMORY_PATH)
    assert not lt.get("user_name") and not lt.get("nicknames") and not lt.get("dislikes"), \
        "长期记忆没被清掉：%r" % (lt,)
    assert len(main.load_chat_memory()) == 2, "清除长期记忆把对话历史也删了"


# ---------------- 2) BubbleStyleDialog ----------------

def test_bubble_style_dialog_keeps_loaded_font_and_radius(pet, monkeypatch):
    """字号/圆角回填后**原样保存**（v2.2.5 的 P0：不回填会把 15pt 写成 8pt）。"""
    style = {"bg": "#112233", "fg": "#445566", "border": "#778899",
             "font_size": 15, "radius": 22}
    cfg = pet.cfg
    cfg["bubble_style"] = dict(style)
    main.save_config(cfg)
    assert _disk_cfg()["bubble_style"]["font_size"] == 15, "用例前提不成立"

    dlg = pet_dialogs.BubbleStyleDialog(pet)
    dlg.show()
    try:
        assert dlg._font_spin.value() == 15, "字号没有回填（保存会把它重置）"
        assert dlg._radius_spin.value() == 22, "圆角没有回填"
        dlg._save()          # 一个字都没改就直接保存
    finally:
        dlg.hide()

    got = _disk_cfg()["bubble_style"]
    assert got["font_size"] == 15, "原样保存后字号被改成了 %r" % (got["font_size"],)
    assert got["radius"] == 22, "原样保存后圆角被改成了 %r" % (got["radius"],)
    assert got["bg"] == "#112233" and got["fg"] == "#445566" and got["border"] == "#778899"

    # 控制组：真改了就必须落盘（否则上面的"没变"可能只是因为保存根本没生效）
    dlg2 = pet_dialogs.BubbleStyleDialog(pet)
    dlg2.show()
    try:
        dlg2._font_spin.setValue(9)
        dlg2._radius_spin.setValue(3)
        dlg2._save()
    finally:
        dlg2.hide()
    got2 = _disk_cfg()["bubble_style"]
    assert (got2["font_size"], got2["radius"]) == (9, 3), "改了值却没落盘：%r" % (got2,)


# ---------------- 3) LinesDialog ----------------

def _row_of(dlg, line_id):
    for i in range(dlg._list.count()):
        if dlg._list.item(i).data(Qt.ItemDataRole.UserRole) == line_id:
            return i
    return -1


def test_lines_dialog_unknown_food_is_not_rewritten(pet):
    """喂食对象是未知值时：下拉给占位项，保存**不得**改写成第 1 项（小鱼干）。"""
    lib = pet.lines_lib
    ln, err = lib.add("这条喂的是怪味豆（自定义食物）", "food", None, None, food="怪味豆")
    assert ln is not None, "台词没建起来：%s" % err
    ln2, err2 = lib.add("这条喂的是蛋糕（已知食物）", "food", None, None, food="蛋糕")
    assert ln2 is not None, "台词没建起来：%s" % err2

    dlg = pet_dialogs.LinesDialog(pet)
    dlg.show()
    try:
        row = _row_of(dlg, ln["id"])
        assert row >= 0, "新建的台词没出现在列表里"
        dlg._list.setCurrentRow(row)                 # 触发 _on_pick_line 回填
        assert dlg._food.currentData() == "怪味豆", \
            "喂食对象没有回填，当前值是 %r" % (dlg._food.currentData(),)
        dlg._save_line()                             # 原样保存
        row2 = _row_of(dlg, ln2["id"])
        dlg._list.setCurrentRow(row2)
        dlg._save_line()
    finally:
        dlg.hide()

    again = {x["id"]: x for x in lib.lines()}
    assert again[ln["id"]]["food"] == "怪味豆", \
        "未知喂食对象被静默改写成了 %r" % (again[ln["id"]]["food"],)
    assert again[ln["id"]]["food"] != "小鱼干", "落回了下拉第 1 项（正是要防的缺陷）"
    # 控制组：已知值当然也要原样保留
    assert again[ln2["id"]]["food"] == "蛋糕"
    assert again[ln["id"]]["text"] == "这条喂的是怪味豆（自定义食物）"


# ---------------- 3b) 死代码守卫（技术债 B） ----------------

def test_duplicate_ask_amount_stays_deleted(pet):
    """模块级 ask_amount 是重构残留的重复实现（全仓零引用）——只保留 PetWindow._ask_amount。"""
    assert not hasattr(pet_dialogs, "ask_amount"), "重复实现又回来了"
    assert callable(getattr(main.PetWindow, "_ask_amount", None)), \
        "唯一在用的实现 PetWindow._ask_amount 不见了"


# ---------------- 4) RoleEditDialog ----------------

def test_role_edit_dialog_form_switch_and_save(pet):
    """形态切换不崩 + 改名能落盘（roles.json 重新读）。"""
    rid = "inv1"
    before = pet.role_lib.get(rid)
    assert before is not None and len(before.get("forms") or []) >= 3, "用例前提不成立"

    dlg = pet_dialogs.RoleEditDialog(pet, lib=pet.role_lib, role_id=rid)
    dlg.show()
    try:
        n = dlg._form_list.count()
        assert n == len(dlg._forms) >= 3
        for row in (1, 2, 0):            # 来回切形态（旧实现切到越界/空列表会崩）
            dlg._form_list.setCurrentRow(row)
            assert dlg._cur_idx == row
        dlg._form_list.setCurrentRow(-1)  # 取消选中也不能崩
        dlg._form_list.setCurrentRow(0)
        dlg._form_name.setText("常态改")
        dlg._save()
    finally:
        dlg.hide()

    after = pet.role_lib.get(rid)
    assert after is not None, "保存后角色丢了"
    assert after["forms"][0]["name"] == "常态改", "改名没有落盘：%r" % (after["forms"][0],)
    assert len(after["forms"]) == len(before["forms"]), "形态数量被保存流程改掉了"
    assert after["id"] == rid, "编辑不该改角色 id"


def test_role_edit_dialog_move_form_keeps_all_forms(pet):
    """形态调序：顺序变、集合不变（不丢形态、不重复）。"""
    rid = "inv1"
    dlg = pet_dialogs.RoleEditDialog(pet, lib=pet.role_lib, role_id=rid)
    dlg.show()
    try:
        names_before = [f.get("name") for f in dlg._forms]
        dlg._form_list.setCurrentRow(0)
        dlg._move_form(1)                 # 形态 0 下移一位
        names_after = [f.get("name") for f in dlg._forms]
        assert names_after != names_before, "调序没有生效"
        assert sorted(names_after) == sorted(names_before), "调序把形态弄丢/弄重了"
        assert dlg._form_list.count() == len(dlg._forms)
    finally:
        dlg.hide()
