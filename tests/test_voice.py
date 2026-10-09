# -*- coding: utf-8 -*-
"""v2.0 语音系统纯逻辑回归：配置归一化 / 错误映射 / 片段注册表。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import pet_voice  # noqa: E402


# ---------------- 归一化 ----------------

def test_normalize_defaults():
    v = pet_voice.normalize_voice(None)
    # v2.0 的四个基础字段（默认关闭、固定音色合成为 off）
    assert v["enabled"] is False and v["tts_mode"] == "off"
    assert v["tts_model"] == "" and v["tts_voice"] == ""
    # v2.1 新增：可插拔后端 / 绑定 / 参数（默认值单一来源 DEFAULT_VOICE）
    assert v == pet_voice.DEFAULT_VOICE
    assert v["backend"] == pet_voice.DEFAULT_BACKEND
    assert v["bindings"] == {} and v["speak_daily"] is False
    assert set(v["backend_params"]) == set(pet_voice.BACKENDS)
    assert all(k in v["backend_params"] for k in ("gpt_sovits", "f5_tts", "cosyvoice",
                                                  "minimax", "elevenlabs"))


def test_normalize_whitelist_mode():
    assert pet_voice.normalize_voice({"tts_mode": "sapi"})["tts_mode"] == "sapi"
    assert pet_voice.normalize_voice({"tts_mode": "api"})["tts_mode"] == "api"
    assert pet_voice.normalize_voice({"tts_mode": "xxx"})["tts_mode"] == "off"
    assert pet_voice.normalize_voice({"enabled": "true"})["enabled"] is True
    assert pet_voice.normalize_voice({"enabled": "false"})["enabled"] is False  # 字符串 false 不误开


# ---------------- 错误映射（明确提示、不静默） ----------------

def test_explain_tts_error_mapping():
    assert "密钥无效" in pet_voice.explain_tts_error(401)
    assert "额度不足" in pet_voice.explain_tts_error(402)
    assert "地区限制" in pet_voice.explain_tts_error(403)
    assert "不支持语音合成" in pet_voice.explain_tts_error(404)
    assert "频繁" in pet_voice.explain_tts_error(429)
    assert "500" in pet_voice.explain_tts_error(500)  # 未知码带状态码


# ---------------- 片段注册表 ----------------

@pytest.fixture
def voice_svc(tmp_path):
    played = []

    def _play(p):
        played.append(p)
    svc = pet_voice.VoiceService(str(tmp_path), lambda: {"voice": {"enabled": True}},
                                 _play, log=lambda m: None)
    yield svc, played


def test_clip_roundtrip(voice_svc):
    svc, played = voice_svc
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                       "_verify_assets", "sample.mp4")
    ok, err = svc.set_clip("reply", src)
    assert not ok and "仅支持" in err  # 非 wav/mp3 拒绝
    # 造一个 wav（放 tmp_path，不污染仓库）
    import wave as _w
    wav = os.path.join(str(os.path.dirname(svc._index)), "t.wav")
    with _w.open(wav, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(22050)
        f.writeframes(b"\x00\x00" * 100)
    ok, err = svc.set_clip("reply", wav)
    assert ok and not err
    p = svc.clip("reply")
    assert p is not None and os.path.isfile(p)
    # 播放事件：语音开启 + 有片段 → 回调
    svc.play_event("reply")
    assert played and played[0] == p
    # 覆盖导入（换一个源路径 → 新文件名）：旧片段文件被清理（不残留孤儿）
    wav2 = os.path.join(str(os.path.dirname(svc._index)), "t2.wav")
    with _w.open(wav2, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(22050)
        f.writeframes(b"\x00\x00" * 200)
    ok2, err2 = svc.set_clip("reply", wav2)
    assert ok2 and not err2
    p2 = svc.clip("reply")
    assert p2 is not None and os.path.isfile(p2)
    assert p2 != p
    assert not os.path.isfile(p)  # 旧片段已清
    os.remove(wav2)
    # 清除
    ok3, err3 = svc.set_clip("reply", None)
    assert ok3 and svc.clip("reply") is None
    if os.path.isfile(wav):
        os.remove(wav)


def test_voice_disabled_silent(tmp_path):
    played = []
    svc = pet_voice.VoiceService(str(tmp_path), lambda: {"voice": {"enabled": False}},
                                 lambda p: played.append(p), log=lambda m: None)
    svc.play_event("reply")
    svc.speak("你好")
    assert played == []  # 默认关闭：完全不发声
