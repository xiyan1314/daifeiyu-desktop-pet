# -*- coding: utf-8 -*-
"""v2.4 静默 except 收口回归：A 档补日志（对话回调）+ C 项 error.log 坏文件隔离。

对应改动：
  · pet_dialogs._call（静默 except 审计 A5）：用户点"保存/应用"的回调抛异常时，
    界面照常显示成功、error.log 里却没有任何线索 → 现在记一条；
  · pet_log.log_error（技术债 C）：轮转失败/追加失败不再 pass——坏文件改名
    error.log.bad，且这条日志要**重试落盘**（不丢），最后才回退 stderr。
"""
import builtins
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pet_dialogs  # noqa: E402
import pet_log  # noqa: E402


def _log_text(tmp_path):
    p = tmp_path / "error.log"
    return p.read_text(encoding="utf-8") if p.is_file() else ""


# ---------------- A 档：对话回调不再静默吞异常 ----------------

class _BoomPet(object):
    """最小 stub：只有 AI 设置对话框需要的那几个接口，保存回调必炸。"""

    cfg = {"ai_model": "deepseek-chat", "ai_persona": "default"}

    def persona_choices(self):
        return [("default", "内置大肥鱼")]

    def apply_ai_settings(self, data):
        raise RuntimeError("save-path-boom")


def test_call_logs_swallowed_callback_exception(tmp_path):
    """回调抛异常：返回值契约不变（None），但 error.log 必须留下方法名与异常。"""
    res = pet_dialogs._call(_BoomPet(), "apply_ai_settings", {"ai_model": "x"})
    assert res is None, "防御性返回值契约被改掉了"
    txt = _log_text(tmp_path)
    assert "apply_ai_settings" in txt, "回调异常没有留痕：%r" % txt
    assert "save-path-boom" in txt, "异常内容没有留痕：%r" % txt


def test_call_does_not_log_when_callback_is_missing_or_fine(tmp_path):
    """控制组：方法不存在（正常降级）与正常返回都不得写日志，否则日志会被噪音淹没。"""
    class _Ok(object):
        def apply_ai_settings(self, data):
            return True

    assert pet_dialogs._call(_Ok(), "apply_ai_settings", {}) is True
    assert pet_dialogs._call(_Ok(), "no_such_method") is None
    assert _log_text(tmp_path) == "", "正常路径写了日志：%r" % _log_text(tmp_path)


def test_ai_settings_dialog_save_failure_is_logged(tmp_path):
    """端到端：AI 设置对话框"保存"时回调炸掉 → 有日志（用户不再是白点一下）。"""
    dlg = pet_dialogs.AISettingsDialog(_BoomPet())
    dlg.show()
    try:
        dlg._model.setText("qwen2.5")
        dlg._save()          # 内部走 _call → 吞掉异常但留痕
    finally:
        dlg.hide()
    txt = _log_text(tmp_path)
    assert "apply_ai_settings" in txt and "save-path-boom" in txt, \
        "对话框保存失败没有留痕：%r" % txt


# ---------------- C 项：error.log 坏文件隔离 ----------------

def test_log_rotation_moves_oversized_file(tmp_path):
    """超限轮转：老内容进 error.log.old，新日志进新的 error.log。"""
    p = tmp_path / "error.log"
    p.write_text("旧" * (pet_log.MAX_BYTES // 2 + 10), encoding="utf-8")
    old_size = p.stat().st_size
    pet_log.log_error("轮转后的第一条")
    assert (tmp_path / "error.log.old").is_file(), "超限没有轮转"
    assert (tmp_path / "error.log.old").stat().st_size == old_size, "轮转把旧日志弄丢了"
    assert "轮转后的第一条" in _log_text(tmp_path)


def test_unwritable_log_is_quarantined_and_message_kept(tmp_path, monkeypatch):
    """追加失败（坏/被占用）→ 改名 error.log.bad，并且**这条日志仍要落盘**。"""
    p = tmp_path / "error.log"
    p.write_text("坏的旧日志\n", encoding="utf-8")
    real_open = builtins.open
    state = {"left": 1}

    def fake_open(file, mode="r", *a, **k):
        if str(file) == str(p) and "a" in str(mode) and state["left"] > 0:
            state["left"] -= 1
            raise PermissionError("locked by test")
        return real_open(file, mode, *a, **k)

    monkeypatch.setattr(builtins, "open", fake_open)
    pet_log.log_error("这条不能被丢掉")
    monkeypatch.undo()

    assert (tmp_path / "error.log.bad").is_file(), "坏文件没有被隔离成 .bad"
    assert (tmp_path / "error.log.bad").read_text(encoding="utf-8") == "坏的旧日志\n", \
        "隔离时改动了原文件内容（现场没保留）"
    assert "这条不能被丢掉" in _log_text(tmp_path), "隔离后没有重试落盘，日志丢了"


def test_rotation_failure_quarantines_instead_of_silent_pass(tmp_path, monkeypatch):
    """轮转失败（.old 被拒）→ 退一步隔离成 .bad，而不是静默 pass 卡在坏文件上。"""
    p = tmp_path / "error.log"
    p.write_text("满" * (pet_log.MAX_BYTES + 32), encoding="utf-8")
    real_replace = os.replace

    def fake_replace(src, dst):
        if str(dst).endswith(".old"):
            raise PermissionError("busy by test")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", fake_replace)
    pet_log.log_error("轮转失败之后也要能写")
    monkeypatch.undo()

    assert (tmp_path / "error.log.bad").is_file(), "轮转失败后没有隔离坏文件"
    assert (tmp_path / "error.log.bad").stat().st_size > pet_log.MAX_BYTES
    assert "轮转失败之后也要能写" in _log_text(tmp_path), "隔离后日志没能重建"


def test_total_write_failure_falls_back_to_stderr(tmp_path, monkeypatch, capsys):
    """最后兜底：彻底写不进去时也不能抛异常，消息要能到 stderr。"""
    real_open = builtins.open

    def fake_open(file, mode="r", *a, **k):
        if str(file).endswith("error.log") and "a" in str(mode):
            raise PermissionError("ro dir by test")
        return real_open(file, mode, *a, **k)

    monkeypatch.setattr(builtins, "open", fake_open)
    pet_log.log_error("只能去 stderr 了")   # 不得抛异常
    monkeypatch.undo()
    err = capsys.readouterr().err
    assert "只能去 stderr 了" in err, "没有回退 stderr：%r" % err
