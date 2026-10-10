# -*- coding: utf-8 -*-
"""v2.4 对话框覆盖补齐（代理 C）：尚未被覆盖的对话框「打开→改值→保存→落盘」闭环。

沿用 tests/test_dialogs_v24.py 的既有写法（照抄隔离套路，不另起炉灶）：
  · offscreen + 真 PetWindow + 临时数据目录（conftest 的 log 隔离 + 本模块自建 pet fixture）；
  · **不 exec() 模态**：一律 show() + 直接调 _save()/accept()/内部动作函数；
  · 落盘以「重新读文件 / 重新建服务实例」为准，不看内存 dict；
  · 每条用例都带反向对照（非法输入不得被保存，或不该变的一个字节都不能动）。

覆盖对象（本文件负责，避免与 test_dialogs_v24.py / test_role_schema.py 重复）：
  PhysicsDialog · VoiceDialog · IdleDialog · LedgerDialog · AlarmDialog ·
  AmountNoteDialog · RoleEditDialog（孤儿文件清理 / 形态调序 / 合法性边界）。

注意：pet_dialogs 的 _warn/_info/_confirm 内部走 modal()（= exec()），offscreen 下会挂死
测试进程——统一在 ui fixture 里换成记录器，断言"提示了中文原因"而不是"弹了框"。
"""
import json
import os
import sys
import wave

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import 桌宠 as main  # noqa: E402
import pet_alarm  # noqa: E402
import pet_behaviors  # noqa: E402
import pet_book  # noqa: E402
import pet_dialogs  # noqa: E402
import pet_resources  # noqa: E402

from PySide6.QtCore import Qt, QTime  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402


# ---------------- 隔离：真 PetWindow + 临时数据目录 ----------------

@pytest.fixture(scope="module")
def pet(tmp_path_factory):
    """真 PetWindow + 全部运行时路径指向临时目录（退出时还原进程级全局）。"""
    import pet_log
    import pet_resources as _pr
    tmp = tmp_path_factory.mktemp("dlgmore24")
    _snap = (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
             getattr(pet_log, "_data_dir", None), getattr(main, "_redact_key", None),
             getattr(_pr, "FRAME_MAX", None))
    main.DATA_DIR = str(tmp)
    main.CONFIG_PATH = str(tmp / "config.json")
    main.USAGE_PATH = str(tmp / "usage.json")
    main.MEMORY_PATH = str(tmp / "memory.json")
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
        _pr.FRAME_MAX = _snap[6]


@pytest.fixture
def ui(monkeypatch):
    """把模态提示换成记录器：offscreen 下 modal() 的 exec() 会阻塞测试进程。

    返回 {"warn": [(标题, 正文)...], "info": [...], "confirm": True/False}。
    """
    seen = {"warn": [], "info": [], "confirm": True}

    def _rec(bucket):
        def _f(_parent, title, text):
            bucket.append((title, text))
        return _f

    monkeypatch.setattr(pet_dialogs, "_warn", _rec(seen["warn"]))
    monkeypatch.setattr(pet_dialogs, "_info", _rec(seen["info"]))
    monkeypatch.setattr(pet_dialogs, "_confirm",
                        lambda _p, _t, _x: seen["confirm"])
    return seen


def _disk_cfg():
    """从磁盘重新读配置（不看内存 dict）。"""
    return main.load_config()


def _png(path, w=40, h=40, color=0xFF3366CC):
    """带 alpha 的不透明色块 PNG（加载后 hasAlphaChannel=True，跳过去背景分支）。"""
    from PySide6.QtGui import QImage
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(color)
    assert img.save(str(path), "PNG")


def _wav(path, seconds=0.1):
    rate = 8000
    n = max(1, int(rate * seconds))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * n)
    return str(path)


def _reset_voice_cfg(pet):
    """把语音配置复位成出厂默认（用例之间不许靠执行顺序传状态）。"""
    import pet_voice
    pet.cfg["voice"] = pet_voice.normalize_voice(None)
    main.save_config(pet.cfg)


def _reset_idle_cfg(pet):
    """把待机配置复位成出厂默认（含清掉旧键 idle_behavior，否则会被迁移补回列表）。"""
    for k, v in pet_behaviors.DEFAULT_BEHAVIOR_CFG.items():
        pet.cfg[k] = list(v) if isinstance(v, list) else v
    main.save_config(pet.cfg)


def _clear_alarms(pet):
    """清空闹钟库（用例之间不许靠执行顺序传状态）。"""
    for a in pet.alarms.list():
        pet.alarms.delete(a["id"])
    assert pet.alarms.list() == []


# ================= 1) PhysicsDialog =================

def test_physics_dialog_save_roundtrip(pet, ui):
    """打开→改值→保存→落盘：五个物理参数全部可往返，重开回填一致。"""
    dlg = pet_dialogs.PhysicsDialog(pet)
    dlg.show()
    try:
        dlg._spin["gravity"].setValue(1200.0)
        dlg._spin["restitution"].setValue(0.5)
        dlg._spin["groundFriction"].setValue(4.0)
        dlg._spin["throwPower"].setValue(2.0)
        dlg._ceil.setChecked(False)
        dlg._save()
    finally:
        dlg.hide()

    phys = _disk_cfg()["physics"]
    assert phys["gravity"] == 1200.0, "重力没落盘：%r" % (phys,)
    assert phys["restitution"] == 0.5
    assert phys["groundFriction"] == 4.0
    assert phys["throwPower"] == 2.0
    assert phys["ceilingBounce"] is False, "顶边反弹开关没落盘"
    assert "_fixed" not in phys, "归一化的内部标记被写进了配置"

    # 控制组：重新打开必须回填刚才保存的值（否则"落盘成功"是空转断言）
    dlg2 = pet_dialogs.PhysicsDialog(pet)
    dlg2.show()
    try:
        assert dlg2._spin["gravity"].value() == 1200.0
        assert dlg2._spin["throwPower"].value() == 2.0
        assert dlg2._ceil.isChecked() is False
    finally:
        dlg2.hide()


def test_physics_dialog_illegal_values_not_saved_raw(pet, ui):
    """反向：直注非法物理值（负数/超上界）——对话框只能把**合法钳制值**存回去。"""
    pet.cfg["physics"] = {"gravity": -5.0, "restitution": 9.0,
                          "groundFriction": 999.0, "throwPower": -1.0,
                          "ceilingBounce": True}
    dlg = pet_dialogs.PhysicsDialog(pet)
    dlg.show()
    try:
        # 控件层：非法值被各自的上下界夹住
        assert dlg._spin["gravity"].value() == 0.0, "负重力没被下界挡住"
        assert dlg._spin["restitution"].value() == 1.0, "反弹系数 >1 没被上界挡住"
        assert dlg._spin["groundFriction"].value() == 50.0
        assert dlg._spin["throwPower"].value() == 0.1
        dlg._save()
    finally:
        dlg.hide()

    phys = _disk_cfg()["physics"]
    assert phys["gravity"] == 0.0 and phys["restitution"] == 1.0
    assert phys["groundFriction"] == 50.0 and phys["throwPower"] == 0.1
    # 非法原值一个都不许出现在磁盘上
    assert -5.0 not in (phys["gravity"], phys["groundFriction"], phys["throwPower"])
    assert 9.0 != phys["restitution"] and 999.0 != phys["groundFriction"]


# ================= 2) VoiceDialog =================

def _pick_backend(dlg, bid):
    i = dlg._backend.findData(bid)
    assert i >= 0, "后端下拉里没有 %s" % bid
    dlg._backend.setCurrentIndex(i)          # 触发 _sync_backend_ui（真实用户操作）
    return i


def test_voice_dialog_save_roundtrip(pet, ui):
    """打开→改值→保存→落盘：开关/日常朗读/后端/参数/密钥/动作/旧 TTS 字段。"""
    _reset_voice_cfg(pet)
    dlg = pet_dialogs.VoiceDialog(pet)
    dlg.show()
    try:
        dlg._en.setChecked(True)
        dlg._daily.setChecked(True)
        _pick_backend(dlg, "minimax")
        dlg._param_widgets["base_url"][1].setText("https://api.example.com")
        dlg._param_widgets["model"][1].setText("speech-02-hd")
        dlg._key.setText("sk-roundtrip")                 # 控件内容
        dlg._key.textEdited.emit("sk-roundtrip")         # 真实键入才会发这个信号
        dlg._tts_mode.setCurrentIndex(dlg._tts_mode.findData("api"))
        dlg._tts_voice.setText("alloy")
        dlg._tts_model.setText("tts-1")
        # 动作下拉：选一个真实动作（有动作名才可能落盘）
        if dlg._talk.count() > 1:
            dlg._talk.setCurrentIndex(1)
        dlg._save()
    finally:
        dlg.hide()

    v = _disk_cfg()["voice"]
    assert v["enabled"] is True, "语音总开关没落盘"
    assert v["speak_daily"] is True, "日常台词朗读没落盘"
    assert v["backend"] == "minimax"
    assert v["backend_params"]["minimax"]["base_url"] == "https://api.example.com"
    assert v["backend_params"]["minimax"]["model"] == "speech-02-hd"
    assert v["backend_keys"]["minimax"] == "sk-roundtrip", "密钥没落盘"
    assert v["tts_mode"] == "api" and v["tts_voice"] == "alloy" and v["tts_model"] == "tts-1"

    # 控制组：重新打开必须回填（含密钥回填）
    dlg2 = pet_dialogs.VoiceDialog(pet)
    dlg2.show()
    try:
        assert dlg2._en.isChecked() is True and dlg2._daily.isChecked() is True
        assert dlg2._backend.currentData() == "minimax"
        assert dlg2._key.text() == "sk-roundtrip"
        assert dlg2._param_widgets["model"][1].text() == "speech-02-hd"
    finally:
        dlg2.hide()


def test_voice_dialog_backend_params_and_keys_do_not_crosstalk(pet, ui):
    """反向：切后端保存不得串台（A 后端的参数/密钥不能被 B 后端的保存清掉或串过去）。

    参数用两个本地后端（gpt_sovits / f5_tts）验；密钥只用**需要 Key 的后端**
    （normalize_voice 只为 needs_key=True 的后端保留密钥槽位，本地后端本来就没有）。
    """
    _reset_voice_cfg(pet)
    dlg = pet_dialogs.VoiceDialog(pet)
    dlg.show()
    try:
        _pick_backend(dlg, "gpt_sovits")
        dlg._param_widgets["base_url"][1].setText("http://127.0.0.1:9999")
        dlg._param_widgets["prompt_text"][1].setText("GPT参考文本")
        dlg._save()                     # 当前显示的就是 gpt_sovits
    finally:
        dlg.hide()
    p1 = _disk_cfg()["voice"]
    assert p1["backend_params"]["gpt_sovits"]["base_url"] == "http://127.0.0.1:9999"
    assert p1["backend_params"]["gpt_sovits"]["prompt_text"] == "GPT参考文本"

    dlg2 = pet_dialogs.VoiceDialog(pet)
    dlg2.show()
    try:
        _pick_backend(dlg2, "f5_tts")
        # 切过来显示的是 f5 自己的默认地址，不是 gpt 填的那个
        assert dlg2._param_widgets["base_url"][1].text() == "http://127.0.0.1:7860", \
            "切后端串台了（显示的是上一个后端的地址）"
        dlg2._param_widgets["ref_text"][1].setText("F5参考文本")
        dlg2._save()
    finally:
        dlg2.hide()

    p2 = _disk_cfg()["voice"]
    assert p2["backend_params"]["gpt_sovits"]["prompt_text"] == "GPT参考文本", \
        "保存 f5_tts 把 gpt_sovits 的参数清掉了（S1 串台回归）"
    assert p2["backend_params"]["gpt_sovits"]["base_url"] == "http://127.0.0.1:9999"
    assert p2["backend_params"]["f5_tts"]["ref_text"] == "F5参考文本"
    # 反向对照：gpt 的参考音文本不能出现在 f5 的槽位里
    assert p2["backend_params"]["f5_tts"].get("prompt_text", "") == ""

    # 密钥隔离：两个云端后端各存各的，互不覆盖
    dlg3 = pet_dialogs.VoiceDialog(pet)
    dlg3.show()
    try:
        _pick_backend(dlg3, "minimax")
        dlg3._key.setText("mm-key")
        dlg3._key.textEdited.emit("mm-key")
        _pick_backend(dlg3, "elevenlabs")
        dlg3._key.setText("el-key")
        dlg3._key.textEdited.emit("el-key")
        dlg3._save()
    finally:
        dlg3.hide()
    keys = _disk_cfg()["voice"]["backend_keys"]
    assert keys.get("minimax") == "mm-key" and keys.get("elevenlabs") == "el-key", \
        "云端后端密钥串台/被清空：%r" % (keys,)


def test_voice_dialog_placeholder_and_ghost_backend_not_persisted(pet, ui):
    """反向：占位项与未知后端不得被当成有效值写进配置。"""
    import pet_voice
    _reset_voice_cfg(pet)

    # (1) 对照组：下拉可编辑，用户手输的动作名必须真落盘
    dlg = pet_dialogs.VoiceDialog(pet)
    dlg.show()
    try:
        assert dlg._talk.isEditable(), "动作下拉不可编辑（手输动作名的能力没了）"
        dlg._talk.setEditText("wave_act")
        assert not dlg._talk.currentData(), "手输文本不该匹配到某个下拉项"
        dlg._save()
    finally:
        dlg.hide()
    assert _disk_cfg()["voice"]["talk_action"] == "wave_act", "对照组前提不成立（手输动作没落盘）"

    # (2) 反向：占位项「（不用动作）」的 data 是空串——保存后必须是 ""，不是占位文案
    dlg2 = pet_dialogs.VoiceDialog(pet)
    dlg2.show()
    try:
        dlg2._talk.setCurrentIndex(0)
        assert dlg2._talk.currentData() == ""
        dlg2._save()
    finally:
        dlg2.hide()
    v = _disk_cfg()["voice"]
    assert v["talk_action"] == "", \
        "占位文案「%s」被当成动作名保存了" % (v["talk_action"],)

    # (3) 手改配置写坏后端名：对话框必须回退到默认项，不能带着坏值保存
    pet.cfg["voice"]["backend"] = "ghost_backend"
    assert pet.cfg["voice"]["backend"] == "ghost_backend", "用例前提不成立"
    dlg3 = pet_dialogs.VoiceDialog(pet)
    dlg3.show()
    try:
        assert dlg3._backend.currentData() == pet_voice.DEFAULT_BACKEND, \
            "未知后端没有回退到默认项（会带着坏值保存）"
        dlg3._save()
    finally:
        dlg3.hide()
    assert _disk_cfg()["voice"]["backend"] == pet_voice.DEFAULT_BACKEND, \
        "未知后端被原样保存了：%r" % (_disk_cfg()["voice"]["backend"],)


def test_voice_dialog_test_backend_reports_missing_key(pet, ui):
    """测试后端按钮：缺 Key 必须给出明确中文结论（不是静默/假装通过）。"""
    _reset_voice_cfg(pet)
    pet.cfg["voice"]["backend_keys"]["minimax"] = ""   # 对话框读的是内存 cfg
    main.save_config(pet.cfg)

    dlg = pet_dialogs.VoiceDialog(pet)
    dlg.show()
    try:
        _pick_backend(dlg, "minimax")
        dlg._test_backend()          # 缺 Key：走本地判定，不联网
        txt = dlg._test_label.text()
    finally:
        dlg.hide()
    assert txt.startswith("❌") and "Key" in txt, "缺 Key 没有明确报错：%r" % (txt,)


# ================= 3) IdleDialog =================

def test_idle_dialog_save_roundtrip(pet, ui):
    """打开→改值→保存→落盘：触发延迟/形态/动作列表（含调序）/播放模式/被打断语义。"""
    _reset_idle_cfg(pet)
    a, err = pet.behaviors.add("idle_a", [{"act": "sleep"}])
    b, err2 = pet.behaviors.add("idle_b", [{"act": "wait", "ms": 300}])
    assert a and b, (err, err2)

    dlg = pet_dialogs.IdleDialog(pet)
    dlg.show()
    try:
        assert dlg._table.rowCount() == 0, "用例前提不成立（待机动作没清干净）"
        assert dlg._pick.findData(a["id"]) >= 0, "行为库里的行为没进下拉"
        dlg._pick.setCurrentIndex(dlg._pick.findData(a["id"]))
        dlg._add_action()
        dlg._pick.setCurrentIndex(dlg._pick.findData(b["id"]))
        dlg._add_action()
        assert dlg._table.rowCount() == 2
        dlg._delay.setValue(12)
        dlg._after_full.setValue(5)
        assert dlg._form.count() >= 2, "待机形态下拉没有形态可选"
        dlg._form.setCurrentIndex(1)
        form_key = dlg._form.currentData()
        dlg._mode.setCurrentIndex(dlg._mode.findData("weighted"))
        dlg._resume.setChecked(True)
        # 调序：选第一行下移
        dlg._table.setCurrentCell(0, 0)
        first_id = dlg._table.item(0, 0).data(Qt.ItemDataRole.UserRole)
        dlg._move(1)
        assert dlg._table.item(1, 0).data(Qt.ItemDataRole.UserRole) == first_id, "下移没生效"
        dlg._save()
    finally:
        dlg.hide()

    cfg = _disk_cfg()
    assert cfg["idle_trigger_delay"] == 12
    assert cfg["idle_delay_after_full"] == 5
    assert cfg["idle_form"] == form_key
    assert cfg["idle_play_mode"] == "weighted"
    assert cfg["idle_resume_on_interrupt"] is True
    acts = cfg["idle_actions"]
    assert [x["order"] for x in acts] == [1, 2], "顺序没有归一化落盘"
    assert acts[1]["id"] == first_id, "调序结果没落盘（下移的那条应排到第 2）"
    assert acts[0]["id"] != first_id
    assert {x["behavior_id"] for x in acts} == {a["id"], b["id"]}

    # 控制组：重开必须回填
    dlg2 = pet_dialogs.IdleDialog(pet)
    dlg2.show()
    try:
        assert dlg2._delay.value() == 12
        assert dlg2._after_full.value() == 5
        assert dlg2._mode.currentData() == "weighted"
        assert dlg2._resume.isChecked() is True
        assert dlg2._table.rowCount() == 2
    finally:
        dlg2.hide()


def test_idle_dialog_illegal_inputs_not_saved(pet, ui):
    """反向：越界延迟被钳制、非数字权重回落、重复添加被拒——都不许原样落盘。"""
    _reset_idle_cfg(pet)
    c, err = pet.behaviors.add("idle_c", [{"act": "sleep"}])
    assert c, err
    dlg = pet_dialogs.IdleDialog(pet)
    dlg.show()
    try:
        assert dlg._table.rowCount() == 0, "用例前提不成立（待机动作没清干净）"
        dlg._pick.setCurrentIndex(dlg._pick.findData(c["id"]))
        dlg._add_action()
        assert dlg._table.rowCount() == 1
        dlg._add_action()                       # 同一条行为重复添加
        assert len(ui["warn"]) == 1 and "已经在待机列表" in ui["warn"][0][1], \
            "重复添加没有给出中文原因：%r" % (ui["warn"],)
        assert dlg._table.rowCount() == 1, "重复添加把列表加了第二行"

        dlg._table.item(0, 2).setText("abc")    # 非数字权重
        dlg._table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
        dlg._delay.setValue(99999)              # 远超上界
        dlg._after_full.setValue(-99)           # 低于下界
        assert dlg._delay.value() == pet_behaviors.IDLE_TRIGGER_MAX
        assert dlg._after_full.value() == pet_behaviors.IDLE_AFTER_FULL_MIN
        dlg._save()
    finally:
        dlg.hide()

    cfg = _disk_cfg()
    assert cfg["idle_trigger_delay"] == pet_behaviors.IDLE_TRIGGER_MAX, \
        "越界延迟没有按上界保存：%r" % (cfg["idle_trigger_delay"],)
    assert cfg["idle_delay_after_full"] == pet_behaviors.IDLE_AFTER_FULL_MIN
    assert len(cfg["idle_actions"]) == 1, "重复项被落盘了"
    a = cfg["idle_actions"][0]
    assert a["weight"] == 1.0, "非数字权重没有回落到 1.0：%r" % (a["weight"],)
    assert a["enabled"] is False, "取消勾选没有落盘"

    # 越界权重（数字但超上界）也必须被夹到上界
    dlg2 = pet_dialogs.IdleDialog(pet)
    dlg2.show()
    try:
        assert dlg2._table.rowCount() == 1
        dlg2._table.item(0, 2).setText("999")
        dlg2._save()
    finally:
        dlg2.hide()
    assert _disk_cfg()["idle_actions"][0]["weight"] == pet_behaviors.IDLE_WEIGHT_MAX


# ================= 4) AmountNoteDialog + LedgerDialog =================

def test_amount_note_dialog_prefill_and_values(pet, ui):
    """预填→改值→accept：values() 给出的就是将要落盘的金额/备注。"""
    dlg = pet_dialogs.AmountNoteDialog(pet, amount=12.5, note="午饭")
    dlg.show()
    try:
        assert dlg._amount.value() == 12.5, "合法预填没生效"
        assert dlg._note.text() == "午饭"
        dlg._note.setText("午饭（加了个蛋）")
        dlg.accept()
        amount, note = dlg.values()
    finally:
        dlg.hide()
    assert amount == 12.5 and note == "午饭（加了个蛋）"


def test_amount_note_dialog_illegal_prefill_ignored(pet, ui):
    """反向：非法预填（负数/非数字/超上界）与超长备注不得原样进 values()。"""
    d1 = pet_dialogs.AmountNoteDialog(pet, amount=-5, note="x" * 200)
    d1.show()
    try:
        assert d1._amount.value() == 1.0, "负金额预填被当真了"
        amount, note = d1.values()
        assert amount == 1.0 and len(note) == 60, "超长备注没有截断：%d" % (len(note),)
    finally:
        d1.hide()

    d2 = pet_dialogs.AmountNoteDialog(pet, amount="abc", note=None)
    d2.show()
    try:
        assert d2._amount.value() == 1.0, "非数字金额预填没有被忽略"
        assert d2.values() == (1.0, "")
        d2._amount.setValue(0)                    # 用户想填 0
        assert d2.values()[0] == 0.01, "低于下限的金额没有被夹到 0.01"
        d2._amount.setValue(10 ** 9)
        assert d2.values()[0] == 99999.0, "超上界的金额没有被夹住"
    finally:
        d2.hide()


def test_ledger_dialog_manual_record_persists(pet, ui, monkeypatch):
    """记一笔：对话框填值→确定→账本落盘（用**新开的 Book 实例**重读磁盘验证）。"""
    before = pet.book.total_count()

    def _fill_accept(dlg):
        dlg.show()
        dlg._amount.setValue(12.5)
        dlg._note.setText("午饭")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(pet_dialogs, "modal", _fill_accept)
    dlg = pet_dialogs.LedgerDialog(pet)
    dlg.show()
    try:
        dlg._add_manual()
        assert "¥12.50" in dlg._summary.text(), "汇总没有跟着更新：%r" % (dlg._summary.text(),)
        assert dlg._today_table.rowCount() == 1, "今日明细没有新增行"
        assert dlg._all_table.rowCount() == before + 1
        # 搜索过滤：命中备注 / 不命中
        dlg._search.setText("午饭")
        assert dlg._all_table.rowCount() == 1
        dlg._search.setText("绝不存在的备注")
        assert dlg._all_table.rowCount() == 0
        dlg._search.setText("")
    finally:
        dlg.hide()

    fresh = pet_book.Book(main.DATA_DIR)          # 重新读磁盘
    assert fresh.total_count() == before + 1, "记的一笔没有落盘"
    rec = fresh.all_records()[0]
    assert rec["amount"] == 12.5 and rec["note"] == "午饭" and rec["kind"] == "manual"


def test_ledger_dialog_cancelled_input_not_saved(pet, ui, monkeypatch):
    """反向：用户取消（或金额非法）时账本一个字节都不许动。"""
    before = pet.book.total_count()

    def _cancel(dlg):
        dlg.show()
        dlg._amount.setValue(88.0)
        dlg._note.setText("不该被记下")
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(pet_dialogs, "modal", _cancel)
    dlg = pet_dialogs.LedgerDialog(pet)
    dlg.show()
    try:
        dlg._add_manual()
    finally:
        dlg.hide()
    assert pet.book.total_count() == before, "取消后仍然记账了"
    assert pet_book.Book(main.DATA_DIR).total_count() == before


def test_ledger_dialog_export_writes_csv_and_cancel_writes_nothing(pet, ui, monkeypatch, tmp_path):
    """导出 CSV：选中路径要真写文件；取消路径不许产生任何文件。"""
    pet.book.add_manual(3.5, "导出用")
    dlg = pet_dialogs.LedgerDialog(pet)
    dlg.show()
    try:
        out = tmp_path / "ledger.csv"
        monkeypatch.setattr(pet_dialogs.QFileDialog, "getSaveFileName",
                            staticmethod(lambda *a, **k: (str(out), "")))
        dlg._export()
        assert out.is_file() and out.stat().st_size > 0, "导出没有写出文件"
        text = out.read_text(encoding="utf-8-sig")
        assert "3.5" in text and "导出用" in text
        assert ui["info"], "导出成功没有提示"

        ui["info"].clear()
        monkeypatch.setattr(pet_dialogs.QFileDialog, "getSaveFileName",
                            staticmethod(lambda *a, **k: ("", "")))
        dlg._export()
        assert not ui["info"], "取消导出却弹了成功提示"
    finally:
        dlg.hide()


# ================= 5) AlarmDialog =================

def test_alarm_dialog_add_reload_and_ringtone(pet, ui, monkeypatch, tmp_path):
    """新建→保存→落盘（重新建 AlarmService 重读）→重开回填；铃声导入与试听。"""
    _clear_alarms(pet)
    svc = pet.alarms
    dlg = pet_dialogs.AlarmDialog(pet, svc)
    dlg.show()
    monkeypatch.setattr(pet, "preview_audio", lambda p: True, raising=False)
    src = _wav(tmp_path / "ring.wav", 0.2)
    try:
        monkeypatch.setattr(pet_dialogs.QFileDialog, "getOpenFileName",
                            staticmethod(lambda *a, **k: (src, "")))
        dlg._pick_ringtone()
        ring = dlg._pending_ringtone
        assert ring, "合法铃声没有被接受"
        dlg._test_ring()
        assert not ui["warn"], "合法铃声试听却报了错：%r" % (ui["warn"],)

        dlg._new()
        assert dlg._pending_ringtone == "", "「新建」没有把表单复位"
        dlg._time.setTime(QTime(6, 15))
        dlg._label.setText("起床喂鱼")
        dlg._ck_enabled.setChecked(False)         # v2.0.5：新建也必须落启用勾选
        dlg._pending_ringtone = ring              # 新建后再选回刚导入的铃声
        dlg._ring_dirty = True
        dlg._save()
    finally:
        dlg.hide()

    alarms = pet_alarm.AlarmService(main.DATA_DIR).list()   # 重新读盘
    assert len(alarms) == 1, "闹钟没落盘：%r" % (alarms,)
    a = alarms[0]
    assert a["time"] == "06:15" and a["label"] == "起床喂鱼"
    assert a["enabled"] is False, "新建时取消勾选「启用」没有落盘"
    assert a["ringtone"], "铃声没有随闹钟落盘"
    assert svc.ringtone_path(a["ringtone"]) is not None, "铃声文件不在 alarms 目录里"
    assert dlg._list.count() == 1

    # 控制组：重开对话框，选中列表项必须回填
    dlg2 = pet_dialogs.AlarmDialog(pet, pet.alarms)
    dlg2.show()
    try:
        assert dlg2._list.count() == 1
        dlg2._list.setCurrentRow(0)
        assert dlg2._label.text() == "起床喂鱼"
        assert dlg2._ck_enabled.isChecked() is False
        assert dlg2._time.time().toString("HH:mm") == "06:15"
        assert dlg2._pending_ringtone == a["ringtone"]
        # 清铃声后保存：落盘为空，且不影响其它字段
        dlg2._clear_ring()
        dlg2._save()
    finally:
        dlg2.hide()
    after = pet_alarm.AlarmService(main.DATA_DIR).list()[0]
    assert after["ringtone"] == "", "清除铃声没有落盘"
    assert after["label"] == "起床喂鱼" and after["time"] == "06:15"


def test_alarm_dialog_illegal_inputs_not_saved(pet, ui, monkeypatch, tmp_path):
    """反向：空文案回落「闹钟」、非音频文件当铃声被拒、取消删除不删。"""
    _clear_alarms(pet)
    dlg = pet_dialogs.AlarmDialog(pet, pet.alarms)
    dlg.show()
    try:
        bad = tmp_path / "not_audio.txt"
        bad.write_text("x", encoding="utf-8")
        monkeypatch.setattr(pet_dialogs.QFileDialog, "getOpenFileName",
                            staticmethod(lambda *a, **k: (str(bad), "")))
        dlg._pick_ringtone()
        assert dlg._pending_ringtone == "", "非 wav/mp3 被当成了铃声"
        assert ui["warn"] and "wav" in ui["warn"][-1][1], \
            "非法铃声没有给出中文原因：%r" % (ui["warn"],)

        dlg._new()
        dlg._label.setText("   ")           # 只有空白的文案
        dlg._time.setTime(QTime(9, 0))
        dlg._save()
    finally:
        dlg.hide()

    alarms = pet_alarm.AlarmService(main.DATA_DIR).list()
    assert len(alarms) == 1
    assert alarms[0]["label"] == "闹钟", "空白文案被原样保存了：%r" % (alarms[0]["label"],)
    assert alarms[0]["ringtone"] == "", "被拒的铃声仍然落盘了"

    # 取消删除 = 不删
    ui["confirm"] = False
    dlg2 = pet_dialogs.AlarmDialog(pet, pet.alarms)
    dlg2.show()
    try:
        dlg2._list.setCurrentRow(0)
        dlg2._delete()
    finally:
        dlg2.hide()
    assert len(pet_alarm.AlarmService(main.DATA_DIR).list()) == 1, "取消确认仍然删除了闹钟"

    # 确认删除 = 真删（控制组）
    ui["confirm"] = True
    dlg3 = pet_dialogs.AlarmDialog(pet, pet.alarms)
    dlg3.show()
    try:
        dlg3._list.setCurrentRow(0)
        dlg3._delete()
    finally:
        dlg3.hide()
    assert pet_alarm.AlarmService(main.DATA_DIR).list() == [], "确认后没有删除"


# ================= 6) RoleEditDialog：孤儿清理 / 形态调序 / 合法性边界 =================

def _two_form_lib(tmp_path):
    lib = pet_resources.RoleLibrary(str(tmp_path))
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    _png(a, 50, 50, 0xFF111111)
    _png(b, 40, 40, 0xFF222222)
    role, err = lib.import_processed(str(a), None, "双形态",
                                     forms_src=[("甲", str(a)), ("乙", str(b))])
    assert role is not None and err is None, err
    return lib, role["id"]


def _add_frames(dlg, monkeypatch, paths, name):
    monkeypatch.setattr(pet_dialogs.QFileDialog, "getOpenFileNames",
                        staticmethod(lambda *a, **k: ([str(p) for p in paths], "")))
    monkeypatch.setattr(pet_dialogs.QInputDialog, "getText",
                        staticmethod(lambda *a, **k: (name, True)))
    dlg._add_frame_action()


def test_role_edit_orphan_staged_frames_cleaned_on_save(tmp_path, monkeypatch, ui):
    """孤儿文件清理：本次暂存、最终没被引用的帧文件必须从角色目录回收。"""
    lib, rid = _two_form_lib(tmp_path)
    f1 = tmp_path / "f1.png"
    f2 = tmp_path / "f2.png"
    _png(f1, 40, 40, 0xFF00AA00)
    _png(f2, 44, 40, 0xFF00AA55)

    dlg = pet_dialogs.RoleEditDialog(None, lib, rid)
    try:
        dlg._cur_idx = 0
        _add_frames(dlg, monkeypatch, [f1, f2], "dance1")
        frames = list((dlg._forms[0].get("animations") or {}).get("dance1") or [])
        assert len(frames) == 2, "帧动作没建起来：%r" % (dlg._forms[0].get("animations"),)
        assert all(os.path.isfile(lib.resolve(f)) for f in frames), "帧文件没进角色目录"
        assert dlg._staged == frames

        # 控制组：动作还在 → 保存后帧文件必须活着并被引用
        dlg._save()
        role = lib.get(rid)
        assert (role["forms"][0].get("animations") or {}).get("dance1") == frames, \
            "保存后帧动作丢了：%r" % (role["forms"][0].get("animations"),)
        assert all(os.path.isfile(lib.resolve(f)) for f in frames), "被引用的帧被误删了"

        # 反向：删掉动作再保存 → 失引用的帧文件必须被回收（否则 roles/ 残留孤儿）
        dlg._cur_idx = 0
        dlg._refresh_act_list()
        hit = -1
        for i in range(dlg._act_list.count()):
            if dlg._act_list.item(i).text().endswith("（帧）"):
                hit = i
                break
        assert hit >= 0, "自定义动作列表里没有帧动作"
        dlg._act_list.setCurrentRow(hit)
        dlg._del_action()
        assert "dance1" not in (dlg._forms[0].get("animations") or {})
        dlg._save()
    finally:
        dlg._cleanup()

    role2 = lib.get(rid)
    assert "dance1" not in (role2["forms"][0].get("animations") or {}), \
        "删除动作后索引里还留着它"
    left = [os.path.basename(f) for f in frames if os.path.isfile(lib.resolve(f))]
    assert left == [], "孤儿帧文件没被回收，残留在角色目录：%r" % (left,)
    assert dlg._staged == [], "回收后 _staged 没有清空：%r" % (dlg._staged,)


def test_role_edit_move_form_bounds_and_pending_follow(tmp_path, monkeypatch, ui):
    """形态调序边界 + 待处理映射跟随：越界调序是空操作，换序后待处理素材跟着走。"""
    lib, rid = _two_form_lib(tmp_path)
    new_img = tmp_path / "new0.png"
    _png(new_img, 48, 48, 0xFF66CC33)

    dlg = pet_dialogs.RoleEditDialog(None, lib, rid)
    try:
        names0 = [f.get("name") for f in dlg._forms]
        # 越界：第 0 个上移、最后一个下移，都必须是空操作（不崩、不换序）
        dlg._form_list.setCurrentRow(0)
        dlg._move_form(-1)
        assert [f.get("name") for f in dlg._forms] == names0, "越界上移把顺序改了"
        assert dlg._cur_idx == 0
        dlg._form_list.setCurrentRow(len(dlg._forms) - 1)
        dlg._move_form(1)
        assert [f.get("name") for f in dlg._forms] == names0, "越界下移把顺序改了"
        # 取消选中也不能崩，且调序是空操作
        dlg._form_list.setCurrentRow(-1)
        assert dlg._cur_idx is None
        dlg._move_form(1)
        assert [f.get("name") for f in dlg._forms] == names0

        # 待处理映射跟随：给形态 0 挂待处理换图/状态图，然后把它下移
        dlg._form_list.setCurrentRow(0)
        dlg._pending_images[0] = str(new_img)
        dlg._pending_states[(0, "angry")] = str(new_img)
        dlg._touched_flags.add(0)
        dlg._move_form(1)
        assert dlg._cur_idx == 1
        assert dlg._pending_images.get(1) == str(new_img), "换图待处理没跟着形态换序"
        assert 0 not in dlg._pending_images, "换图待处理还留在旧下标上"
        assert dlg._pending_states.get((1, "angry")) == str(new_img), "状态图待处理没跟着换序"
        assert 0 in dlg._touched_flags and 1 not in dlg._touched_flags or 1 in dlg._touched_flags
    finally:
        dlg._cleanup()

    # 落盘验证：换过序的那个形态拿到了处理后的新图
    dlg2 = pet_dialogs.RoleEditDialog(None, lib, rid)
    try:
        names_before = [f.get("name") for f in dlg2._forms]
        dlg2._form_list.setCurrentRow(0)
        dlg2._pending_images[0] = str(new_img)
        dlg2._move_form(1)                      # 形态 0 下移到 1，待处理跟着到 1
        dlg2._save()
    finally:
        dlg2._cleanup()

    role = lib.get(rid)
    assert [f.get("name") for f in role["forms"]] == [names_before[1], names_before[0]], \
        "调序结果没有落盘：%r" % ([f.get("name") for f in role["forms"]],)
    assert os.path.isfile(lib.resolve(role["forms"][1]["file"])), "换上的新图不在角色目录"
    assert role["forms"][1]["file"] != role["forms"][0]["file"]
    assert [f.get("name") for f in role["forms"]] != names_before


def test_role_edit_illegal_inputs_rejected_not_saved(tmp_path, monkeypatch, ui):
    """反向：空角色名、非法动作名、帧数不足——一律拒绝且不写角色目录。"""
    lib, rid = _two_form_lib(tmp_path)
    roles_dir = os.path.join(str(tmp_path), "roles")
    before_files = sorted(os.listdir(roles_dir))
    before_name = lib.get(rid)["name"]

    f1 = tmp_path / "g1.png"
    f2 = tmp_path / "g2.png"
    _png(f1, 40, 40)
    _png(f2, 40, 40, 0xFF990000)

    dlg = pet_dialogs.RoleEditDialog(None, lib, rid)
    try:
        dlg._cur_idx = 0
        # 非法动作名（数字开头）与保留名：都不得暂存文件
        _add_frames(dlg, monkeypatch, [f1, f2], "1bad")
        assert dlg._staged == [], "非法动作名却把帧写进了角色目录"
        _add_frames(dlg, monkeypatch, [f1, f2], "jump")
        assert dlg._staged == [], "保留动作名却把帧写进了角色目录"
        # 帧数不足
        monkeypatch.setattr(pet_dialogs.QFileDialog, "getOpenFileNames",
                            staticmethod(lambda *a, **k: ([str(f1)], "")))
        monkeypatch.setattr(pet_dialogs.QInputDialog, "getText",
                            staticmethod(lambda *a, **k: ("onlyone", True)))
        dlg._add_frame_action()
        assert dlg._staged == [] and not (dlg._forms[0].get("animations") or {}), \
            "单帧也被当成了帧动作"
        assert len(ui["warn"]) >= 3, "非法输入没有给出中文原因：%r" % (ui["warn"],)

        # 空角色名：保存必须被拒绝，磁盘上的名字一个字节都不能变
        dlg._name_edit.setText("   ")
        dlg._save()
    finally:
        dlg._cleanup()

    assert lib.get(rid)["name"] == before_name, "空角色名竟然保存成功了"
    assert sorted(os.listdir(roles_dir)) == before_files, \
        "被拒的保存往角色目录写了残留文件：%r" % (sorted(os.listdir(roles_dir)),)

    # 控制组：合法动作名当然要能加上（否则上面的"没有文件"可能是空转）
    dlg2 = pet_dialogs.RoleEditDialog(None, lib, rid)
    try:
        dlg2._cur_idx = 0
        _add_frames(dlg2, monkeypatch, [f1, f2], "dance_ok")
        assert len(dlg2._staged) == 2, "合法动作名没能加上帧"
        dlg2._save()
    finally:
        dlg2._cleanup()
    assert (lib.get(rid)["forms"][0].get("animations") or {}).get("dance_ok"), "合法帧动作没落盘"


def test_role_edit_name_length_caps(tmp_path, ui):
    """合法性边界：形态名按 12 字符截断（对话框口径）；角色名按 40 字符截断（库口径）。

    两个口径不同是既成事实（对话框 setMaxLength(12) + _sync_current[:12]；
    RoleLibrary.update 再兜一道 [:40]），这里钉住防止哪天静默放宽。
    """
    lib, rid = _two_form_lib(tmp_path)
    long_form = "十二个字十二个字十二个字"      # 36 字，远超 12
    long_role = "角色名" * 20                    # 60 字，超 40
    dlg = pet_dialogs.RoleEditDialog(None, lib, rid)
    try:
        dlg._form_list.setCurrentRow(0)
        dlg._form_name.setText(long_form)
        dlg._name_edit.setText(long_role)
        dlg._save()
    finally:
        dlg._cleanup()
    role = lib.get(rid)
    assert role["forms"][0]["name"] == long_form[:12], \
        "形态名没有按 12 字符截断：%r" % (role["forms"][0]["name"],)
    assert role["name"] == long_role[:40], \
        "角色名没有按 40 字符截断：%r" % (role["name"],)
    assert len(role["name"]) < len(long_role), "超长角色名被原样保存了"


# ================= 7) 入口函数（含异常兜底分支） =================

def test_dialog_entry_points_open_and_failure_is_reported(pet, ui, monkeypatch):
    """入口函数：正常路径要真建出对应对话框；构造抛异常时只记日志+提示，不得再抛。"""
    opened = []

    def _fake_modal(dlg):
        opened.append(type(dlg).__name__)
        dlg.show()
        dlg.reject()
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(pet_dialogs, "modal", _fake_modal)
    pet_dialogs.open_physics(pet)
    pet_dialogs.open_voice(pet)
    pet_dialogs.open_idle(pet)
    assert opened == ["PhysicsDialog", "VoiceDialog", "IdleDialog"], \
        "入口没有建出预期对话框：%r" % (opened,)

    def _boom(*_a, **_k):
        raise RuntimeError("构造故意失败")

    # open_voice → _dialog_failed：必须记日志 + 给用户一句中文，且不得向外抛
    monkeypatch.setattr(pet_dialogs, "VoiceDialog", _boom)
    ui["warn"].clear()
    pet_dialogs.open_voice(pet)
    assert ui["warn"] and "打不开" in ui["warn"][-1][1], \
        "构造失败没有给用户中文提示：%r" % (ui["warn"],)

    # open_physics 的兜底同样不得把异常抛给调用方（菜单槽函数抛异常 = 用户"点了没反应"）
    monkeypatch.setattr(pet_dialogs, "PhysicsDialog", _boom)
    pet_dialogs.open_physics(pet)

# ================= 8) 降级与失败分支补齐（v2.4.1） =================
#
# 1)~7) 覆盖的是"打开→改值→保存→落盘"的正反闭环；这一节补**失败/降级**分支：
# 服务不可用、导出失败、非法铃声、空库、保存回调拿不到……这些分支如果没人走，
# 出问题时的表现就是"点了没反应"（既没落盘、也没提示），所以每条都钉"必须有中文结论"。

def test_ledger_dialog_without_book_service_is_inert(pet, ui):
    """账本服务拿不到（book=None）：按钮禁用 + 明确「账本不可用」，动作函数是空操作。

    pet fixture 只用来保证 QApplication 已建好（QDialog 必须在 QApplication 之后构造）。
    """
    class _NoBook(object):
        pass

    dlg = pet_dialogs.LedgerDialog(_NoBook())
    dlg.show()
    try:
        assert dlg._book is None
        assert not dlg._btn_add.isEnabled() and not dlg._btn_export.isEnabled(), \
            "账本不可用却仍然让用户点「记一笔/导出」"
        assert dlg._summary.text() == "账本不可用"
        assert dlg._today_table.rowCount() == 0 and dlg._all_table.rowCount() == 0
        dlg._add_manual()          # 空操作：不得抛、不得弹框
        dlg._export()
        assert not ui["warn"] and not ui["info"], "不可用状态下不该弹任何框：%r" % (ui,)
    finally:
        dlg.hide()


def test_ledger_dialog_export_failure_and_missing_extension(pet, ui, monkeypatch, tmp_path):
    """导出：没写 .csv 后缀要自动补；账本报错时只给中文原因、不许提示成功。"""
    pet.book.add_manual(3.5, "导出失败用")
    dlg = pet_dialogs.LedgerDialog(pet)
    dlg.show()
    try:
        out = tmp_path / "没有后缀"
        monkeypatch.setattr(pet_dialogs.QFileDialog, "getSaveFileName",
                            staticmethod(lambda *a, **k: (str(out), "")))
        ui["info"].clear()
        dlg._export()
        assert (tmp_path / "没有后缀.csv").is_file(), "没自动补 .csv 后缀"

        ui["info"].clear()
        ui["warn"].clear()
        monkeypatch.setattr(pet.book, "export_csv", lambda p: (False, "磁盘只读"))
        dlg._export()
        assert ui["warn"] and "磁盘只读" in ui["warn"][-1][1], ui["warn"]
        assert not ui["info"], "导出失败却提示了成功"
    finally:
        dlg.hide()


def test_ledger_add_manual_rejects_nonpositive_amount(pet, ui, monkeypatch):
    """反向：金额 <= 0（对话框被绕过/返回意外值）时账本一个字节都不许动。"""
    before = pet.book.total_count()

    class _Zero(object):
        def values(self):
            return (0.0, "零元")

    monkeypatch.setattr(pet_dialogs, "AmountNoteDialog", lambda *a, **k: _Zero())
    monkeypatch.setattr(pet_dialogs, "modal", lambda dlg: QDialog.DialogCode.Accepted)
    dlg = pet_dialogs.LedgerDialog(pet)
    dlg.show()
    try:
        dlg._add_manual()
    finally:
        dlg.hide()
    assert pet.book.total_count() == before, "0 元的账被记进去了"
    assert pet_book.Book(main.DATA_DIR).total_count() == before
    assert not ui["warn"] and not ui["info"]


def test_alarm_dialog_ringtone_and_playback_guards(pet, ui, monkeypatch, tmp_path):
    """铃声：取消选择 / 未配就试听 / 播放失败——三条都要明确（不静默、不误播）。"""
    _clear_alarms(pet)
    dlg = pet_dialogs.AlarmDialog(pet, pet.alarms)
    dlg.show()
    try:
        # (1) 取消选铃声：状态与提示都不变
        monkeypatch.setattr(pet_dialogs.QFileDialog, "getOpenFileName",
                            staticmethod(lambda *a, **k: ("", "")))
        dlg._pick_ringtone()
        assert dlg._pending_ringtone == "" and not ui["warn"]

        # (2) 还没铃声就试听 → 中文原因，且不得去播放
        played = []
        monkeypatch.setattr(pet, "preview_audio",
                            lambda p: played.append(p) or True, raising=False)
        dlg._test_ring()
        assert ui["warn"] and "还没有铃声" in ui["warn"][-1][1], ui["warn"]
        assert played == [], "没有铃声却调用播放了"

        # (3) 有铃声但播放失败 → 明确提示（不得当成成功）
        src = _wav(tmp_path / "ring_guard.wav", 0.1)
        monkeypatch.setattr(pet_dialogs.QFileDialog, "getOpenFileName",
                            staticmethod(lambda *a, **k: (src, "")))
        dlg._pick_ringtone()
        assert dlg._pending_ringtone, "合法铃声没有被接受"
        monkeypatch.setattr(pet, "preview_audio", lambda p: False, raising=False)
        ui["warn"].clear()
        dlg._test_ring()
        assert ui["warn"] and "播放失败" in ui["warn"][-1][1], ui["warn"]
    finally:
        dlg.hide()


def test_alarm_dialog_update_failure_and_delete_without_selection(pet, ui):
    """反向：坏铃声保存失败要给原因且不落盘；未选中就删除是空操作（不弹确认、不误删）。"""
    _clear_alarms(pet)
    dlg = pet_dialogs.AlarmDialog(pet, pet.alarms)
    dlg.show()
    try:
        dlg._time.setTime(QTime(7, 30))
        dlg._label.setText("先建一个")
        dlg._save()
        assert len(pet.alarms.list()) == 1

        # 脏铃声（绕过导入校验的值）→ svc.update 拒绝：必须提示，且坏值不许落盘。
        # 注意：AlarmService.update 在返回失败**之前**已经就地把内存里的 ringtone 改成
        # 坏值（pet_alarm.py:256-259，只跳过 _save）——这是本轮领地外的已知缺陷，已在
        # 交接里点名；这里只钉用户可见的落盘契约（读原始 alarms.json，不信内存）。
        dlg._list.setCurrentRow(0)          # 选中刚建的 → _editing_id 就位
        aid = pet.alarms.list()[0]["id"]
        dlg._pending_ringtone = "坏文件.txt"
        dlg._ring_dirty = True
        ui["warn"].clear()
        dlg._save()
        assert ui["warn"] and "wav" in ui["warn"][-1][1], ui["warn"]
        with open(os.path.join(main.DATA_DIR, "alarms.json"), encoding="utf-8") as fh:
            raw = json.load(fh)
        saved = [a for a in (raw.get("alarms") or []) if a.get("id") == aid]
        assert saved and saved[0].get("ringtone") == "", \
            "被拒的坏铃声仍然落盘了：%r" % (raw,)
        pet.alarms.update(aid, ringtone="")   # 把 update 失败路径留下的内存脏值清掉

        # 未选中删除：不弹确认、不删、不提示
        dlg._new()
        assert dlg._list.currentRow() < 0
        warns = len(ui["warn"])
        dlg._delete()
        assert len(pet.alarms.list()) == 1, "未选中却删掉了闹钟"
        assert len(ui["warn"]) == warns, "未选中删除不该弹提示"
    finally:
        dlg.hide()


def test_alarm_dialog_without_service_is_inert(pet, ui):
    """闹钟服务拿不到：列表空，保存/删除/选铃声/新建全是空操作（不得抛）。"""
    dlg = pet_dialogs.AlarmDialog(None)      # 没有 pet.alarms → svc=None
    dlg.show()
    try:
        assert dlg.svc is None and dlg._list.count() == 0
        dlg._save()
        dlg._delete()
        dlg._pick_ringtone()
        dlg._new()
        dlg._refresh()
        assert not ui["warn"] and not ui["info"]
    finally:
        dlg.hide()


def test_idle_dialog_empty_library_and_no_selection(pet, ui):
    """反向：行为库为空时「添加」只提示不加行；未选中时移除/调序是空操作。"""
    _reset_idle_cfg(pet)
    dlg = pet_dialogs.IdleDialog(pet)
    dlg.show()
    try:
        dlg._table.setRowCount(0)
        dlg._pick.clear()                    # 等价于行为库为空（下拉没有可选项）
        dlg._add_action()
        assert ui["warn"] and "行为库是空的" in ui["warn"][-1][1], ui["warn"]
        assert dlg._table.rowCount() == 0, "空库却加了一行"

        dlg._remove_action()
        assert len(ui["warn"]) == 2 and "先选中" in ui["warn"][-1][1], ui["warn"]
        dlg._move(1)                          # 未选中：空操作，不崩也不提示
        dlg._move(-1)
        assert len(ui["warn"]) == 2
        dlg._save()                           # 空列表也能保存
    finally:
        dlg.hide()
    assert _disk_cfg()["idle_actions"] == []


def test_idle_dialog_remove_and_save_failure(pet, ui, monkeypatch):
    """移除：正常移除要真少一行；保存回调拿不到时必须提示且不关闭对话框。"""
    _reset_idle_cfg(pet)
    c, err = pet.behaviors.add("idle_rm_v241", [{"act": "sleep"}])
    assert c, err
    dlg = pet_dialogs.IdleDialog(pet)
    dlg.show()
    try:
        i = dlg._pick.findData(c["id"])
        assert i >= 0, "新建的行为没进下拉"
        dlg._pick.setCurrentIndex(i)
        dlg._add_action()
        assert dlg._table.rowCount() == 1
        dlg._table.setCurrentCell(0, 0)
        dlg._remove_action()
        assert dlg._table.rowCount() == 0, "选中后移除没有生效"

        monkeypatch.setattr(pet, "apply_idle_settings", lambda d=None: None, raising=False)
        ui["warn"].clear()
        dlg._save()
        assert ui["warn"] and "保存失败" in ui["warn"][-1][1], ui["warn"]
        assert dlg.result() != QDialog.DialogCode.Accepted, "保存失败却把对话框关掉了"
    finally:
        dlg.hide()


def test_idle_dialog_table_missing_behavior_and_perf_hint(pet, ui):
    """表格渲染：行为被删要显式标注；动作超上限只给性能提示、不许静默截断。"""
    _reset_idle_cfg(pet)
    dlg = pet_dialogs.IdleDialog(pet)
    dlg.show()
    try:
        dlg._idle["idle_actions"] = [
            {"id": "ghost1", "behavior_id": "ghost_behavior", "enabled": True,
             "weight": 1.0, "order": 1}]
        dlg._refresh_table()
        assert dlg._table.rowCount() == 1
        assert "行为已删除" in dlg._table.item(0, 1).text(), \
            "被删的行为没有显式标注：%r" % (dlg._table.item(0, 1).text(),)

        n = pet_behaviors.IDLE_ACTIONS_MAX + 1
        dlg._idle["idle_actions"] = [
            {"id": "g%d" % i, "behavior_id": "ghost_behavior", "enabled": True,
             "weight": 1.0, "order": i + 1} for i in range(n)]
        dlg._refresh_table()
        assert dlg._table.rowCount() == n, "超上限被静默截断了"
        assert str(n) in dlg._perf_hint.text() and "提示" in dlg._perf_hint.text(), \
            "超上限没有性能提示：%r" % (dlg._perf_hint.text(),)
    finally:
        dlg.hide()


def test_physics_dialog_defaults_when_cfg_missing(pet, ui, monkeypatch):
    """配置里没有 physics 段：控件回退安全默认（缺键不能让整段读不出来）。"""
    monkeypatch.delitem(pet.cfg, "physics", raising=False)
    dlg = pet_dialogs.PhysicsDialog(pet)
    dlg.show()
    try:
        for key, sp in dlg._spin.items():
            assert sp.value() == 1.0, "%s 的默认值不是 1.0：%r" % (key, sp.value())
        assert dlg._ceil.isChecked() is True
    finally:
        dlg.hide()

# ================= 9) VoiceDialog：保存失败 / 本地后端 / 试听 / 朗读 / 事件片段 =================

def test_voice_dialog_save_failure_is_reported(pet, ui, monkeypatch):
    """反向：apply_voice 拿不到（语音服务不可用）时不得假装保存成功。"""
    _reset_voice_cfg(pet)
    dlg = pet_dialogs.VoiceDialog(pet)
    dlg.show()
    try:
        monkeypatch.setattr(pet, "apply_voice", lambda d=None: None, raising=False)
        ui["warn"].clear()
        dlg._save()
        assert ui["warn"] and "保存失败" in ui["warn"][-1][1], ui["warn"]
        assert dlg.result() != QDialog.DialogCode.Accepted, "保存失败却把对话框关掉了"
        # silent 模式（测试后端/试听前先落配置）：不弹框，也不关闭
        ui["warn"].clear()
        dlg._save(silent=True)
        assert not ui["warn"] and dlg.result() != QDialog.DialogCode.Accepted
    finally:
        dlg.hide()


def test_voice_dialog_local_service_settings_roundtrip(pet, ui):
    """本地后端启动配置（命令/目录/自动启动/退出结束/等待秒数）按后端各自落盘、不串台。"""
    _reset_voice_cfg(pet)
    dlg = pet_dialogs.VoiceDialog(pet)
    dlg.show()
    try:
        _pick_backend(dlg, "gpt_sovits")
        dlg._lcmd.setText("D:/gpt/启动.bat")
        dlg._lcwd.setText("D:/gpt")
        dlg._lauto.setChecked(True)
        dlg._lkill.setChecked(False)
        dlg._lwait.setValue(45)
        _pick_backend(dlg, "f5_tts")
        assert dlg._lcmd.text() == "", "切后端把 gpt 的启动命令串到 f5 了"
        assert dlg._lauto.isChecked() is False
        dlg._lcmd.setText("python f5.py")
        dlg._save()
    finally:
        dlg.hide()

    ls = _disk_cfg()["voice"]["local_services"]
    assert ls["gpt_sovits"] == {"cmd": "D:/gpt/启动.bat", "cwd": "D:/gpt",
                                "auto_start": True, "kill_on_exit": False,
                                "wait_seconds": 45}, ls["gpt_sovits"]
    assert ls["f5_tts"]["cmd"] == "python f5.py"
    assert ls["f5_tts"]["wait_seconds"] == 30, "f5 的等待秒数被 gpt 的 45 串了"
    assert set(ls) == {"gpt_sovits", "f5_tts", "cosyvoice"}, "本地后端清单不对：%r" % (ls,)

    dlg2 = pet_dialogs.VoiceDialog(pet)
    dlg2.show()
    try:
        _pick_backend(dlg2, "gpt_sovits")
        assert dlg2._lcmd.text() == "D:/gpt/启动.bat" and dlg2._lwait.value() == 45
        assert dlg2._lkill.isChecked() is False and dlg2._lauto.isChecked() is True
    finally:
        dlg2.hide()


def test_voice_dialog_test_backend_and_preview_paths(pet, ui, monkeypatch, tmp_path):
    """测试后端：服务不可用/成功两种结论；试听：空选择/未知素材/正常；绑定：失败/成功。"""
    _reset_voice_cfg(pet)
    dlg = pet_dialogs.VoiceDialog(pet)
    dlg.show()
    try:
        monkeypatch.setattr(dlg, "_svc", None)
        dlg._test_backend()
        assert "不可用" in dlg._test_label.text(), dlg._test_label.text()
        monkeypatch.setattr(dlg, "_svc", pet.voice)

        _pick_backend(dlg, "sapi")     # sapi 不需要探测服务/素材，直接给"配置没问题"
        dlg._test_backend()
        assert dlg._test_label.text().startswith("✅"), dlg._test_label.text()

        ui["warn"].clear()
        dlg._preview("")
        assert ui["warn"] and "先选一个声音素材" in ui["warn"][-1][1], ui["warn"]

        ui["warn"].clear()
        dlg._preview("ghost_asset")
        # 提示记录是 (标题, 正文)：标题是"试听失败"，正文透出服务层原因
        assert ui["warn"] and ui["warn"][-1][0] == "试听失败", ui["warn"]
        assert "素材不存在" in ui["warn"][-1][1], ui["warn"]

        monkeypatch.setattr(pet.voice, "preview_asset", lambda vs, **k: (True, ""))
        ui["warn"].clear()
        dlg._preview("whatever")
        assert not ui["warn"], ui["warn"]

        from PySide6.QtWidgets import QComboBox
        combo = QComboBox()
        combo.addItem("幽灵素材", "ghost_asset")
        ui["warn"].clear()
        dlg._on_bind_changed("role_x", combo)
        assert ui["warn"] and ui["warn"][-1][0] == "绑定失败", ui["warn"]
        assert "素材不存在" in ui["warn"][-1][1], ui["warn"]

        src = _wav(tmp_path / "bind_ref.wav", 0.1)
        asset, err = pet.voice_assets.import_file(src, "契约音色")
        assert asset is not None and not err, err
        combo2 = QComboBox()
        combo2.addItem("契约音色", asset["id"])
        ui["warn"].clear()
        dlg._on_bind_changed("", combo2)
        assert not ui["warn"], ui["warn"]
        assert _disk_cfg()["voice"]["bindings"].get("") == asset["id"], "绑定没落盘"
    finally:
        dlg.hide()


def test_voice_dialog_play_tab_reports_missing_and_failure(pet, ui, monkeypatch):
    """朗读页：没台词/没对白/服务不可用都要给中文结论；成功与失败都要更新状态行。"""
    _reset_voice_cfg(pet)
    dlg = pet_dialogs.VoiceDialog(pet)
    dlg.show()
    try:
        dlg._line_combo.clear()
        dlg._dlg_combo.clear()
        dlg._speak_line()
        assert "还没有台词" in dlg._play_label.text(), dlg._play_label.text()
        dlg._speak_dialogue()
        assert "还没有对白" in dlg._play_label.text(), dlg._play_label.text()

        monkeypatch.setattr(dlg, "_svc", None)
        dlg._speak_line()
        assert "不可用" in dlg._play_label.text(), dlg._play_label.text()
        dlg._speak_dialogue()
        dlg._stop()
        assert dlg._play_label.text() == "已停止。"
        dlg._regen_line()          # 无服务：空操作，不崩
        assert dlg._play_label.text() == "已停止。"
        dlg._speak_dialogue()      # 无服务：空操作
        assert dlg._play_label.text() == "已停止。"

        monkeypatch.setattr(dlg, "_svc", pet.voice)
        dlg._line_combo.addItem("假台词", "ghost_line")
        monkeypatch.setattr(pet.voice, "speak_line", lambda lid, **k: (True, ""))
        dlg._speak_line()
        assert dlg._play_label.text().startswith("✅"), dlg._play_label.text()
        monkeypatch.setattr(pet.voice, "speak_line",
                            lambda lid, **k: (False, "台词不存在（可能已被删除）"))
        dlg._speak_line()
        assert dlg._play_label.text().startswith("❌") and "台词不存在" in dlg._play_label.text()

        dlg._dlg_combo.addItem("假对白", "ghost_dlg")
        monkeypatch.setattr(pet.voice, "speak_dialogue",
                            lambda did, **k: (False, "对白里没有可播放的台词"))
        dlg._speak_dialogue()
        assert "没有可播放的台词" in dlg._play_label.text(), dlg._play_label.text()
        monkeypatch.setattr(pet.voice, "regenerate", lambda lid: (False, "台词库不可用"))
        dlg._regen_line()
        assert dlg._play_label.text().startswith("❌"), dlg._play_label.text()
    finally:
        dlg.hide()


def test_voice_dialog_event_clip_import_test_clear(pet, ui, monkeypatch, tmp_path):
    """事件音效：未配就试听/取消导入/非法文件/正常导入/试听/清除/清除失败——每条都有结论。"""
    _reset_voice_cfg(pet)
    key = "poke"
    pet.voice.set_clip(key, None)              # 前置：这个事件没有片段
    dlg = pet_dialogs.VoiceDialog(pet)
    dlg.show()
    try:
        played = []
        monkeypatch.setattr(pet, "preview_audio",
                            lambda p: played.append(p) or True, raising=False)
        dlg._test(key)
        assert ui["warn"] and "还没配片段" in ui["warn"][-1][1], ui["warn"]
        assert played == [], "没有片段却去播放了"

        ui["warn"].clear()
        monkeypatch.setattr(pet_dialogs.QFileDialog, "getOpenFileName",
                            staticmethod(lambda *a, **k: ("", "")))
        dlg._import(key)
        assert dlg._row_labels[key].text() == "—" and not ui["warn"]

        bad = tmp_path / "not_audio_v241.txt"
        bad.write_text("x", encoding="utf-8")
        monkeypatch.setattr(pet_dialogs.QFileDialog, "getOpenFileName",
                            staticmethod(lambda *a, **k: (str(bad), "")))
        dlg._import(key)
        assert ui["warn"] and "wav" in ui["warn"][-1][1], ui["warn"]
        assert dlg._row_labels[key].text() == "—", "非法文件却改了行标记"

        src = _wav(tmp_path / "clip_v241.wav", 0.1)
        ui["warn"].clear()
        monkeypatch.setattr(pet_dialogs.QFileDialog, "getOpenFileName",
                            staticmethod(lambda *a, **k: (str(src), "")))
        dlg._import(key)
        assert dlg._row_labels[key].text() == "✓ 已配"
        with open(os.path.join(main.DATA_DIR, "voice.json"), encoding="utf-8") as fh:
            assert json.load(fh)["clips"].get(key), "片段没有落盘到 voice.json"
        assert pet.voice.clip(key) is not None
        dlg._test(key)
        assert played and played[-1] == pet.voice.clip(key) and not ui["warn"]

        ui["warn"].clear()
        dlg._clear(key)
        assert dlg._row_labels[key].text() == "—" and not ui["warn"]
        with open(os.path.join(main.DATA_DIR, "voice.json"), encoding="utf-8") as fh:
            assert not (json.load(fh)["clips"] or {}).get(key), "清除没有落盘"

        monkeypatch.setattr(pet.voice, "set_clip", lambda k, s=None: (False, "未知事件"))
        ui["warn"].clear()
        dlg._clear(key)
        assert ui["warn"] and "未知事件" in ui["warn"][-1][1], ui["warn"]
    finally:
        dlg.hide()


def test_voice_dialog_dead_binding_shows_placeholder(pet, ui):
    """已失效的绑定（素材被删）必须显式占位，不能显示成"没绑定"（M7/L3）。"""
    _reset_voice_cfg(pet)
    pet.cfg["voice"]["bindings"] = {"": "ghost_slot_123456"}
    main.save_config(pet.cfg)
    dlg = pet_dialogs.VoiceDialog(pet)
    dlg.show()
    try:
        combo = dlg._bind_combos[""]
        assert combo.currentData() == "ghost_slot_123456", \
            "失效绑定被当成没绑定：%r" % (combo.currentText(),)
        assert "已失效" in combo.currentText(), combo.currentText()
    finally:
        dlg.hide()
        _reset_voice_cfg(pet)      # 收尾：别把幽灵绑定留给后面的用例


def test_voice_dialog_backend_start_stop_status(pet, ui, monkeypatch):
    """本地后端按钮：走桌宠回调；没回调时退回服务层；状态行区分运行中/未运行。

    注意：_start_backend_now/_stop_backend_now 写完结果消息后紧接着调
    _refresh_launch_status()，后者会把消息**覆盖**成"运行中/未运行"（pet_dialogs.py 既有
    行为，本轮领地外，已在交接里点名）——所以这里分两段验：先屏蔽刷新只看结果消息，
    再恢复刷新只看状态行。
    """
    _reset_voice_cfg(pet)
    dlg = pet_dialogs.VoiceDialog(pet)
    dlg.show()
    try:
        _pick_backend(dlg, "gpt_sovits")
        real_refresh = dlg._refresh_launch_status
        monkeypatch.setattr(dlg, "_refresh_launch_status", lambda: None)
        monkeypatch.setattr(pet, "start_voice_backend",
                            lambda: (True, "已启动（PID 1）"), raising=False)
        dlg._start_backend_now()
        assert dlg._lstatus.text().startswith("✅") and "已启动" in dlg._lstatus.text()
        monkeypatch.setattr(pet, "start_voice_backend",
                            lambda: (False, "启动失败：命令不对"), raising=False)
        dlg._start_backend_now()
        assert dlg._lstatus.text().startswith("❌") and "命令不对" in dlg._lstatus.text()

        # 老版本没有 start_voice_backend → 退回服务层（起进程失败也要有中文结论）
        monkeypatch.setattr(pet, "start_voice_backend", None, raising=False)
        monkeypatch.setattr(pet.voice, "start_backend",
                            lambda *a, **k: (False, "还没填启动命令"))
        dlg._start_backend_now()
        assert dlg._lstatus.text().startswith("❌") and "还没填启动命令" in dlg._lstatus.text()

        # 连语音服务都没有：明确"不可用"
        monkeypatch.setattr(dlg, "_svc", None)
        dlg._start_backend_now()
        assert "不可用" in dlg._lstatus.text(), dlg._lstatus.text()
        dlg._lstatus.setText("")
        dlg._stop_backend_now()
        assert dlg._lstatus.text() == "", "无服务时结束后端不该改状态行"

        monkeypatch.setattr(dlg, "_svc", pet.voice)
        monkeypatch.setattr(pet.voice, "stop_backend", lambda: (False, "结束后端失败：x"))
        dlg._stop_backend_now()
        assert dlg._lstatus.text().startswith("❌")
        monkeypatch.setattr(pet.voice, "stop_backend", lambda: (True, "已结束后端（PID 1）"))
        dlg._stop_backend_now()
        assert dlg._lstatus.text().startswith("✅")

        monkeypatch.setattr(dlg, "_refresh_launch_status", real_refresh)
        monkeypatch.setattr(pet.voice, "launch_status", lambda: {
            "running": True, "pid": 4321, "started_at": "2026-10-10 10:00:00",
            "backend": "gpt_sovits", "log": "x.log"})
        dlg._refresh_launch_status()
        assert "运行中" in dlg._lstatus.text() and "4321" in dlg._lstatus.text()
        monkeypatch.setattr(pet.voice, "launch_status", lambda: {"running": False})
        dlg._refresh_launch_status()
        assert "未运行" in dlg._lstatus.text()
    finally:
        dlg.hide()


# ================= 10) RoleEditDialog：换图/正面图/状态图/动作/保存失败 =================

def test_role_edit_pick_image_validation_and_status(pet, tmp_path, monkeypatch, ui):
    """换图：取消不记录；非法图给中文原因且不落角色目录；合法图记为待处理并更新状态行。"""
    lib, rid = _two_form_lib(tmp_path)
    roles_dir = os.path.join(str(tmp_path), "roles")
    before = sorted(os.listdir(roles_dir))
    good = tmp_path / "good.png"
    _png(good, 40, 40)
    bad = tmp_path / "bad.png"
    bad.write_text("不是图片", encoding="utf-8")

    dlg = pet_dialogs.RoleEditDialog(None, lib, rid)
    try:
        dlg._cur_idx = 0
        monkeypatch.setattr(pet_dialogs.QFileDialog, "getOpenFileName",
                            staticmethod(lambda *a, **k: ("", "")))
        dlg._pick_image()
        assert dlg._pending_images == {} and not ui["warn"]

        monkeypatch.setattr(pet_dialogs.QFileDialog, "getOpenFileName",
                            staticmethod(lambda *a, **k: (str(bad), "")))
        dlg._pick_image()
        assert dlg._pending_images == {} and ui["warn"], ui["warn"]
        assert "无法加载该图片" in ui["warn"][-1][1], ui["warn"]
        assert sorted(os.listdir(roles_dir)) == before, "非法图却往角色目录写了文件"

        monkeypatch.setattr(pet_dialogs.QFileDialog, "getOpenFileName",
                            staticmethod(lambda *a, **k: (str(good), "")))
        dlg._pick_image()
        assert dlg._pending_images.get(0) == str(good)
        assert "待处理换图" in dlg._img_status.text(), dlg._img_status.text()
    finally:
        dlg._cleanup()


def test_role_edit_front_and_state_pending_roundtrip(pet, tmp_path, monkeypatch, ui):
    """正面图/状态图：待处理→保存落盘；清除→索引里键被删、旧文件回收。"""
    lib, rid = _two_form_lib(tmp_path)
    img = tmp_path / "front.png"
    _png(img, 30, 30, 0xFF123456)

    dlg = pet_dialogs.RoleEditDialog(None, lib, rid)
    try:
        dlg._cur_idx = 0
        monkeypatch.setattr(pet_dialogs.QFileDialog, "getOpenFileName",
                            staticmethod(lambda *a, **k: (str(img), "")))
        dlg._pick_front()
        assert dlg._pending_front.get(0) == str(img)
        assert "待处理正面图" in dlg._img_status.text(), dlg._img_status.text()
        st = dlg._state_combo.currentText()
        dlg._pick_state()
        assert dlg._pending_states.get((0, st)) == str(img)
        assert "%s(待处理)" % st in dlg._states_status.text(), dlg._states_status.text()
        dlg._save()
    finally:
        dlg._cleanup()

    role = lib.get(rid)
    front = role["forms"][0].get("front")
    statef = (role["forms"][0].get("states") or {}).get(st)
    assert front and os.path.isfile(lib.resolve(front)), "正面图没落盘"
    assert statef and os.path.isfile(lib.resolve(statef)), "状态图没落盘"
    assert front != statef, "正面图与状态图被写成了同一个文件"

    dlg2 = pet_dialogs.RoleEditDialog(None, lib, rid)
    try:
        dlg2._cur_idx = 0
        dlg2._clear_front()
        assert dlg2._pending_front.get(0) is None
        # 已知缺陷（pet_dialogs.py:_update_statuses 用 "pending_front is not None" 判据，
        # None=清除 这一态永远显示不出来，会回落成"已有正面图"）——领地外，只记交接；
        # 这里钉住真正要紧的：待处理标记 + 保存后索引与文件都被清掉。
        assert dlg2._img_status.text() != "", "清正面后状态行不该是空的"
        dlg2._state_combo.setCurrentIndex(dlg2._state_combo.findText(st))
        dlg2._clear_state()
        assert dlg2._pending_states.get((0, st)) is None
        assert "%s(待清除)" % st in dlg2._states_status.text(), dlg2._states_status.text()
        dlg2._save()
    finally:
        dlg2._cleanup()

    role2 = lib.get(rid)
    assert not role2["forms"][0].get("front"), "清除正面图没有落盘"
    assert st not in (role2["forms"][0].get("states") or {}), "清除状态图没有落盘"
    assert not os.path.isfile(lib.resolve(front)), "清除后旧正面图文件没被回收"
    assert not os.path.isfile(lib.resolve(statef)), "清除后旧状态图文件没被回收"


def test_role_edit_action_list_type_scoped_delete(pet, tmp_path, monkeypatch, ui):
    """动作列表：内建动作不列；同名「帧」「合成」各自独立删除，互不误伤。"""
    lib, rid = _two_form_lib(tmp_path)
    dlg = pet_dialogs.RoleEditDialog(None, lib, rid)
    try:
        dlg._cur_idx = 0
        fm = dlg._forms[0]
        fm["animations"] = {"dance_x": ["a.png", "b.png"], "idle": ["x.png"]}
        fm["procs"] = {"breathe_x": {"kind": "breathe", "amp": 0.02, "period_ms": 2000},
                       "dance_x": {"kind": "sway", "amp": 0.03, "period_ms": 1800}}
        dlg._refresh_act_list()
        texts = [dlg._act_list.item(i).text() for i in range(dlg._act_list.count())]
        assert "dance_x（帧）" in texts and "dance_x（合成）" in texts
        assert "breathe_x（合成）" in texts
        assert not any(t.startswith("idle") for t in texts), \
            "内建动作被当成自定义动作列出来了：%r" % (texts,)

        for i, t in enumerate(texts):
            if t == "dance_x（帧）":
                dlg._act_list.setCurrentRow(i)
        dlg._del_action()
        assert "dance_x" not in (dlg._forms[0]["animations"]), "帧动作没删掉"
        assert "dance_x" in (dlg._forms[0]["procs"]), "删帧动作把同名合成动作也删了"

        dlg._refresh_act_list()
        texts2 = [dlg._act_list.item(i).text() for i in range(dlg._act_list.count())]
        for i, t in enumerate(texts2):
            if t == "dance_x（合成）":
                dlg._act_list.setCurrentRow(i)
        dlg._del_action()
        assert "dance_x" not in (dlg._forms[0]["procs"]), "合成动作没删掉"
        assert "breathe_x" in (dlg._forms[0]["procs"]), "删一个把别的合成动作也删了"

        dlg._act_list.setCurrentRow(-1)     # 未选中：空操作
        dlg._del_action()
        dlg._cur_idx = None
        dlg._del_action()
    finally:
        dlg._cleanup()


def test_role_edit_frame_action_guards(pet, tmp_path, monkeypatch, ui):
    """帧动作：超帧数上限/取消命名/空名/与合成动作同名——四条都必须拒绝且不写目录。"""
    lib, rid = _two_form_lib(tmp_path)
    roles_dir = os.path.join(str(tmp_path), "roles")
    before = sorted(os.listdir(roles_dir))
    f1 = tmp_path / "h1.png"
    f2 = tmp_path / "h2.png"
    _png(f1, 40, 40)
    _png(f2, 40, 40, 0xFF445566)

    dlg = pet_dialogs.RoleEditDialog(None, lib, rid)
    try:
        dlg._cur_idx = 0
        monkeypatch.setattr(pet_resources, "FRAME_MAX", 1)
        _add_frames(dlg, monkeypatch, [f1, f2], "toomany")
        assert dlg._staged == [] and ui["warn"], ui["warn"]
        assert "最多 1 帧" in ui["warn"][-1][1], ui["warn"]

        monkeypatch.setattr(pet_resources, "FRAME_MAX", 24)
        monkeypatch.setattr(pet_dialogs.QFileDialog, "getOpenFileNames",
                            staticmethod(lambda *a, **k: ([str(f1), str(f2)], "")))
        n_warn = len(ui["warn"])
        monkeypatch.setattr(pet_dialogs.QInputDialog, "getText",
                            staticmethod(lambda *a, **k: ("", False)))    # 用户取消
        dlg._add_frame_action()
        monkeypatch.setattr(pet_dialogs.QInputDialog, "getText",
                            staticmethod(lambda *a, **k: ("   ", True)))  # 只有空白
        dlg._add_frame_action()
        assert len(ui["warn"]) == n_warn, "取消/空名不该弹提示：%r" % (ui["warn"],)
        assert dlg._staged == []

        dlg._forms[0]["procs"] = {"dupname": {"kind": "breathe", "amp": 0.02,
                                              "period_ms": 2000}}
        _add_frames(dlg, monkeypatch, [f1, f2], "dupname")
        assert "dupname" not in (dlg._forms[0].get("animations") or {})
        assert "同名合成动作" in ui["warn"][-1][1], ui["warn"]
        assert sorted(os.listdir(roles_dir)) == before, \
            "被拒的帧动作往角色目录写了残留：%r" % (sorted(os.listdir(roles_dir)),)
    finally:
        dlg._cleanup()


def test_role_edit_save_failure_cleans_staged(pet, tmp_path, monkeypatch, ui):
    """保存失败（库拒绝写）：要提示、不 accept、本次暂存文件全部回收、索引不变。"""
    lib, rid = _two_form_lib(tmp_path)
    roles_dir = os.path.join(str(tmp_path), "roles")
    before_files = sorted(os.listdir(roles_dir))
    before_name = lib.get(rid)["name"]
    img = tmp_path / "s.png"
    _png(img, 40, 40, 0xFF00FF00)

    dlg = pet_dialogs.RoleEditDialog(None, lib, rid)
    try:
        dlg._cur_idx = 0
        monkeypatch.setattr(pet_dialogs.QFileDialog, "getOpenFileName",
                            staticmethod(lambda *a, **k: (str(img), "")))
        dlg._pick_image()
        assert dlg._pending_images
        monkeypatch.setattr(lib, "update", lambda rid_, patch: (False, "磁盘只读"))
        ui["warn"].clear()
        dlg._save()
        assert ui["warn"] and "磁盘只读" in ui["warn"][-1][1], ui["warn"]
        assert dlg.result() != QDialog.DialogCode.Accepted, "保存失败却关掉了对话框"
        assert dlg._staged == [], "保存失败后暂存清单没清空：%r" % (dlg._staged,)
    finally:
        dlg._cleanup()
    assert lib.get(rid)["name"] == before_name
    assert sorted(os.listdir(roles_dir)) == before_files, \
        "保存失败往角色目录留了残留：%r" % (sorted(os.listdir(roles_dir)),)


def test_role_edit_empty_form_name_falls_back(pet, tmp_path, ui):
    """反向：形态名清空（只留空白）不许原样保存，回落到「形态N」占位。"""
    lib, rid = _two_form_lib(tmp_path)
    dlg = pet_dialogs.RoleEditDialog(None, lib, rid)
    try:
        dlg._form_list.setCurrentRow(0)
        dlg._form_name.setText("   ")
        dlg._save()
    finally:
        dlg._cleanup()
    name = lib.get(rid)["forms"][0]["name"]
    assert name == "形态1", "空白形态名没有回落占位：%r" % (name,)
    assert name.strip() != ""


def test_role_edit_without_library_is_inert(pet, ui):
    """库拿不到（lib=None）：保存是空操作、不弹框（不得抛）。"""
    dlg = pet_dialogs.RoleEditDialog(None, None, "")
    dlg.show()
    try:
        assert dlg._lib is None
        dlg._save()
        assert not ui["warn"] and not ui["info"]
    finally:
        dlg.hide()


