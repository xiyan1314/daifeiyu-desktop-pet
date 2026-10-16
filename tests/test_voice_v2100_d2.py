# -*- coding: utf-8 -*-
"""v2.10.0（D2 第一步）：`pet_voice.play_event` 的「有没有片段 / 这次播没播出去」返回值。

**背景**（用户已裁决的 D2）：内置音效库与语音事件片段库要合并成一条**显式优先级链** ——
「语音库有该事件片段 → 只走语音；没有 → 落回内置音效」，**不是**"删掉一边的调用"
（那会让没配音的用户丢掉内置音效）。实现前提是 `play_event` 必须能回答"这个事件到底
有没有片段"，而它此前在三条路径上全是**裸 return**。

本文件钉的就是那份契约（原文见 `pet_voice.EventClipResult` 的 docstring）：

  ① 没有可用片段       → `missing`，`fallback_allowed=True`（内置音效该接手）
  ② 有片段且能播        → `played`，`fallback_allowed=False`（同一事件只响一次）
  ③ 有片段但这次播不出来 → `failed`，**与 ① 可区分**，且 `fallback_allowed=False`
  ④ 语音总开关关着      → `voice_off`，`fallback_allowed=True`（与改动前一致：
     此前它静默返回，调用方的内置音效照常响）

边界另钉两条：绑定了但片段文件被删 → 算"没有可用片段"；`speak` 也补了 `(ok, err)`。
"""
import os
import wave

import pet_voice


def _wav(path, seconds=0.1):
    """造一个真 wav（`set_clip` 只收 wav/mp3 且不校验内容，这里给个能打开的最小文件）。"""
    rate = 8000
    n = int(rate * seconds)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * n)
    return str(path)


def _svc(tmp_path, enabled=True, play_clip=None):
    """建一个只有事件片段能力的 VoiceService（不接台词库/素材库/后端）。"""
    played = []
    cfg = {"voice": dict(pet_voice.DEFAULT_VOICE)}
    cfg["voice"]["enabled"] = bool(enabled)
    if play_clip is None:
        play_clip = played.append          # 默认：记下"被交给了播放器"的路径
    svc = pet_voice.VoiceService(str(tmp_path), lambda: cfg, play_clip, log=lambda m: None)
    return svc, played, cfg


# ---------------- ① 没有片段 ----------------

def test_play_event_without_clip_reports_missing(tmp_path):
    svc, played, _cfg = _svc(tmp_path)
    res = svc.play_event("reply")
    assert res.reason == pet_voice.EVENT_CLIP_MISSING
    assert res.has_clip is False
    assert res.played is False
    assert res.failed is False
    assert res.fallback_allowed is True, "没有片段时内置音效必须能接手"
    assert played == []


# ---------------- ② 有片段且能播 ----------------

def test_play_event_with_clip_reports_played(tmp_path):
    svc, played, _cfg = _svc(tmp_path)
    assert svc.set_clip("reply", _wav(tmp_path / "clip.wav")) == (True, "")
    res = svc.play_event("reply")
    assert res.reason == pet_voice.EVENT_CLIP_PLAYED
    assert res.has_clip is True and res.played is True and res.failed is False
    assert res.fallback_allowed is False, "语音已经响了，内置音效不许再响（只响一次）"
    assert played == [svc.clip("reply")]
    assert res.clip_path == svc.clip("reply")


# ---------------- ③ 有片段但这次播不出来（本步的关键区别） ----------------

def test_play_failure_is_distinguishable_from_missing(tmp_path):
    def boom(_path):
        raise RuntimeError("解码器坏了（测试用）")

    svc, played, _cfg = _svc(tmp_path, play_clip=boom)
    assert svc.set_clip("poke", _wav(tmp_path / "clip.wav")) == (True, "")
    failed = svc.play_event("poke")
    assert failed.reason == pet_voice.EVENT_CLIP_FAILED
    assert failed.has_clip is True, "片段确实配了 —— 这正是它与 missing 的区别"
    assert failed.played is False and failed.failed is True
    assert failed.fallback_allowed is False, "有片段但播不出来时不许落回内置音效"
    assert played == []                    # boom 没记任何东西（它不是记录器）

    # 同一个事件、同一个服务：清掉片段后必须落到**另一个** reason
    assert svc.set_clip("poke", None) == (True, "")
    missing = svc.play_event("poke")
    assert missing.reason == pet_voice.EVENT_CLIP_MISSING
    assert (failed.reason, failed.fallback_allowed, failed.has_clip) != \
           (missing.reason, missing.fallback_allowed, missing.has_clip)


# ---------------- ④ 语音总开关关着 ----------------

def test_voice_off_still_allows_builtin_sound(tmp_path):
    svc, played, _cfg = _svc(tmp_path, enabled=False)
    assert svc.set_clip("feed", _wav(tmp_path / "clip.wav")) == (True, "")
    res = svc.play_event("feed")
    assert res.reason == pet_voice.EVENT_CLIP_VOICE_OFF
    assert res.played is False and played == []
    assert res.has_clip is True, "总开关关着不影响「配没配片段」这个事实（clip() 不看总开关）"
    assert res.fallback_allowed is True, \
        "配过片段 + 关掉语音的用户，内置音效仍要响（与改动前一致）"
    # 关着语音又没配片段：同样允许回落
    os.makedirs(str(tmp_path / "b"), exist_ok=True)   # VoiceService 的数据目录先造好
    svc2, _p2, _c2 = _svc(tmp_path / "b", enabled=False)
    res2 = svc2.play_event("feed")
    assert res2.reason == pet_voice.EVENT_CLIP_VOICE_OFF
    assert res2.has_clip is False and res2.fallback_allowed is True


# ---------------- 边界：绑定了但片段文件被删 ----------------

def test_bound_but_deleted_clip_counts_as_missing(tmp_path):
    svc, played, _cfg = _svc(tmp_path)
    assert svc.set_clip("reply", _wav(tmp_path / "clip.wav")) == (True, "")
    p = svc.clip("reply")
    assert p is not None
    os.remove(p)                      # 模拟用户手删了 voice/ 里的片段文件
    res = svc.play_event("reply")
    assert res.reason == pet_voice.EVENT_CLIP_MISSING
    assert res.fallback_allowed is True, "语音不可能出声 → 内置音效接手（clip() 的既有口径）"
    assert played == []


# ---------------- speak：同一形状的静默返回也补上了 (ok, err) ----------------

def test_speak_returns_status_instead_of_bare_none(tmp_path, monkeypatch):
    svc, _played, cfg = _svc(tmp_path, enabled=False)
    ok, err = svc.speak("你好")
    assert ok is False and "总开关" in err
    cfg["voice"]["enabled"] = True
    ok, err = svc.speak("   ")
    assert ok is False and "文本" in err
    ok, err = svc.speak("你好")
    assert ok is False and "tts_mode" in err      # 没绑素材 + 固定音色关着
    # 有声音素材时：返回值必须是 speak_text 的结论（而不是丢掉它）
    monkeypatch.setattr(svc, "resolve_voice", lambda role, vs: ("asset1", ""))
    monkeypatch.setattr(svc, "speak_text",
                        lambda text, role, vs, on_error=None: (False, "测试替身：合成不了"))
    assert svc.speak("你好") == (False, "测试替身：合成不了")
