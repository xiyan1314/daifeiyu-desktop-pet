# -*- coding: utf-8 -*-
"""v2.1.1 本地后端启动器回归：启动/判活/结束/日志；默认不自动启动（开关由用户选）。"""
import os
import sys
import time

import pet_voice


def _launcher(tmp_path):
    return pet_voice.VoiceLauncher(str(tmp_path))


def _sleep_cmd(seconds=6):
    return '"%s" -c "import time; time.sleep(%d)"' % (sys.executable, seconds)


def test_no_command_reports_clearly(tmp_path):
    ln = _launcher(tmp_path)
    ok, msg = ln.start("", "", "gpt_sovits")
    assert ok is False and "启动命令" in msg
    assert ln.is_running() is False
    assert ln.status()["running"] is False


def test_start_and_stop_roundtrip(tmp_path):
    ln = _launcher(tmp_path)
    ok, msg = ln.start(_sleep_cmd(), "", "gpt_sovits")
    assert ok and ln.is_running(), msg
    st = ln.status()
    assert st["pid"] > 0 and st["backend"] == "gpt_sovits"
    assert os.path.isfile(st["log"])  # 日志文件已创建
    assert ln.stop()[0] is True
    assert ln.is_running() is False
    assert ln.status()["pid"] == 0
    # 幂等：再停一次也成功（不抛错）
    assert ln.stop()[0] is True


def test_second_start_is_idempotent(tmp_path):
    ln = _launcher(tmp_path)
    assert ln.start(_sleep_cmd(8), "", "f5_tts")[0] is True
    try:
        ok, msg = ln.start("should-not-run", "", "f5_tts")
        assert ok is True and "已经在跑" in msg  # 已在运行就不重复拉起
        assert ln.is_running() is True
    finally:
        ln.stop()


def test_stale_pid_is_not_running(tmp_path):
    ln = _launcher(tmp_path)
    ln._state = {"pid": 999999, "cmd": "ghost", "backend": "x", "started_at": ""}
    assert ln.is_running() is False
    ok, msg = ln.stop()  # 进程早没了：视为已完成
    assert ok is True


def test_defaults_off_and_switch(tmp_path):
    """默认和以前一样：不自动启动；用户勾了开关才自动。"""
    v = pet_voice.normalize_voice(None)
    for bid in ("gpt_sovits", "f5_tts", "cosyvoice"):
        assert v["local_services"][bid]["auto_start"] is False
        assert v["local_services"][bid]["kill_on_exit"] is True
        assert v["local_services"][bid]["wait_seconds"] == 30
    on = pet_voice.normalize_voice({"local_services": {
        "gpt_sovits": {"cmd": "run.bat", "auto_start": True, "wait_seconds": 5}}})
    assert on["local_services"]["gpt_sovits"]["cmd"] == "run.bat"
    assert on["local_services"]["gpt_sovits"]["auto_start"] is True
    assert on["local_services"]["gpt_sovits"]["wait_seconds"] == 5
    # 只对本地后端保留该配置（云端后端没有）：
    assert set(on["local_services"]) == {"gpt_sovits", "f5_tts", "cosyvoice"}


def test_service_helpers(tmp_path):
    cfg = {"voice": pet_voice.normalize_voice(None)}
    svc = pet_voice.VoiceService(str(tmp_path), lambda: cfg, lambda p: None,
                                 save_cfg=lambda c: None)
    assert svc.is_local_backend("gpt_sovits") is True
    assert svc.is_local_backend("openai") is False
    # 手动启动云端后端：明确拒绝（不需要启动）
    ok, msg = svc.start_backend("minimax")
    assert ok is False and "不需要启动" in msg
    # 本地后端没填命令：明确报错
    ok2, msg2 = svc.start_backend("gpt_sovits")
    assert ok2 is False and "启动命令" in msg2
    # 默认不自动启动（语音默认关闭 + auto_start 默认 False）
    assert svc.start_backend_if_configured() == (False, "")
    cfg["voice"]["enabled"] = True
    assert svc.start_backend_if_configured() == (False, "")  # 没勾开关 → 依旧不动
    cfg["voice"]["local_services"]["gpt_sovits"]["auto_start"] = True
    cfg["voice"]["local_services"]["gpt_sovits"]["cmd"] = _sleep_cmd(6)
    started, msg3 = svc.start_backend_if_configured()
    try:
        assert started is True and svc.launcher.is_running()
        assert svc.start_backend_if_configured() == (False, "")  # 已在跑：不重复启动
    finally:
        svc.stop_backend()
    # 退出清理开关
    cfg["voice"]["local_services"]["gpt_sovits"]["cmd"] = _sleep_cmd(6)
    svc.start_backend("gpt_sovits")
    try:
        need, _m = svc.stop_backend_if_ours()
        assert need is True and svc.launcher.is_running() is False
    finally:
        svc.stop_backend()
    cfg["voice"]["local_services"]["gpt_sovits"]["kill_on_exit"] = False
    svc.start_backend("gpt_sovits")
    try:
        assert svc.stop_backend_if_ours() == (False, "")  # 用户选了不清理 → 不动
        assert svc.launcher.is_running() is True
    finally:
        svc.stop_backend()


def test_wait_ready_reports_failure(tmp_path):
    """没启动任何东西时 wait_ready 必须给出明确原因（不静默）。"""
    ln = _launcher(tmp_path)
    ok, msg = ln.wait_ready("http://127.0.0.1:1", timeout=3)
    assert ok is False and msg
    assert ("连不上" in msg or "超时" in msg or "进程已退出" in msg)
