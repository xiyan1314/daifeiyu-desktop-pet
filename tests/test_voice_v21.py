# -*- coding: utf-8 -*-
"""v2.1 语言系统回归：后端注册/归一化/绑定解析/队列播放/缓存命中/停止/重新生成。

用假后端（stub）验证管线，不依赖任何真实克隆服务。
"""
import os
import struct
import threading
import time
import wave

import pet_lines
import pet_resources
import pet_voice


def _wav(path, seconds=0.2):
    rate = 8000
    n = int(rate * seconds)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<%dh" % n, *([0] * n)))
    return str(path)


class StubBackend(pet_voice.VoiceBackend):
    id = "stub"
    label = "测试后端"
    needs_reference = True
    default_params = {"base_url": "http://127.0.0.1:1"}

    def __init__(self):
        self.calls = []

    def synthesize(self, reference_audio_path, text, params, key=""):
        self.calls.append((reference_audio_path, text))
        if not reference_audio_path or not os.path.isfile(reference_audio_path):
            return None, "参考音不存在"
        return b"RIFF" + b"\x00" * 200, ""


class FailBackend(StubBackend):
    id = "fail"

    def synthesize(self, reference_audio_path, text, params, key=""):
        return None, "后端故意失败（测试用）"


import pytest


@pytest.fixture(autouse=True)
def _isolate_backends():
    """每个用例前后恢复后端注册表（L4：测试注入不得污染全局，避免顺序相关失败）。"""
    snapshot = dict(pet_voice.BACKENDS)
    try:
        yield
    finally:
        pet_voice.BACKENDS.clear()
        pet_voice.BACKENDS.update(snapshot)


def _register(backend):
    """注册测试后端，并保证用完清理（L4：全局注册表不能被测试污染，否则顺序相关失败）。"""
    pet_voice.BACKENDS[backend.id] = backend
    return backend


def _unregister(*ids):
    for i in ids:
        pet_voice.BACKENDS.pop(i, None)


def _env(tmp_path, stub):
    lines = pet_lines.LineService(str(tmp_path / "d"))
    assets = pet_resources.VoiceAssetLibrary(str(tmp_path / "d"))
    asset, err = assets.import_file(_wav(tmp_path / "ref.wav"), "测试音色")
    assert asset is not None and not err, err
    played = []
    finished = threading.Event()
    errors = []
    cfg = {"voice": dict(pet_voice.DEFAULT_VOICE)}
    cfg["voice"]["enabled"] = True
    cfg["voice"]["backend"] = stub.id
    svc = pet_voice.VoiceService(str(tmp_path / "d"), lambda: cfg, played.append,
                                 lines=lines, voice_assets=assets,
                                 save_cfg=lambda c: None)
    svc.on_speaking_finished(lambda *a: finished.set())
    svc.on_error(lambda m: errors.append(m))
    return lines, assets, asset, cfg, svc, played, finished, errors


def _wait(pred, timeout=8.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred():
            return True
        time.sleep(0.02)
    return False


def test_backend_registry_and_normalize():
    infos = pet_voice.backend_infos()
    ids = [i["id"] for i in infos]
    assert ids[:5] == ["gpt_sovits", "f5_tts", "cosyvoice", "minimax", "elevenlabs"]
    assert any(i["needs_key"] for i in infos) and any(i["needs_service"] for i in infos)
    n = pet_voice.normalize_voice({"backend": "ghost", "cache_max": 1,
                                   "bindings": {"a": "b", "c": ""},
                                   "backend_keys": {"minimax": "k"},
                                   "backend_params": {"gpt_sovits": {"base_url": "http://x"}}})
    assert n["backend"] == pet_voice.DEFAULT_BACKEND
    assert n["cache_max"] == 50  # 钳制下界
    assert n["bindings"] == {"a": "b"}
    assert n["backend_keys"]["minimax"] == "k"
    assert n["backend_params"]["gpt_sovits"]["base_url"] == "http://x"
    assert n["backend_params"]["f5_tts"]["base_url"]  # 默认值补齐
    # A11 去重（v2.4.2，代理 Q）：原先这里还有一句
    # assert normalize_voice(None) == DEFAULT_VOICE——与 tests/test_voice.py::test_normalize_defaults
    # 逐字同句（那边还逐字段核对 enabled/tts_mode/backend/bindings/backend_params），已合并过去。
    # 本条只留"传入坏 backend 配置时的归一化"这一独有部分。


def test_bind_and_resolve(tmp_path):
    stub = StubBackend()
    pet_voice.BACKENDS["stub"] = stub
    lines, assets, asset, cfg, svc, played, fin, errs = _env(tmp_path, stub)
    assert svc.bind_voice("role_a", asset["id"]) == (True, "")
    assert svc.bindings() == {"role_a": asset["id"]}
    assert svc.resolve_voice("role_a", None) == (asset["id"], "")
    assert svc.resolve_voice("role_b", None)[0] == ""  # 没绑也没兜底 → 明确报错
    assert svc.resolve_voice("role_b", asset["id"]) == (asset["id"], "")  # 台词指定优先
    assert svc.bind_voice("role_c", "nope")[0] is False  # 素材不存在
    assert svc.unbind_voice("role_a") == (True, "")
    assert svc.bindings() == {}
    # 兜底绑定（"" 键）对所有角色生效
    cfg["voice"]["bindings"] = {"": asset["id"]}
    assert svc.resolve_voice("anyone", None) == (asset["id"], "")


def test_speak_line_queue_and_cache(tmp_path):
    stub = StubBackend()
    pet_voice.BACKENDS["stub"] = stub
    lines, assets, asset, cfg, svc, played, fin, errs = _env(tmp_path, stub)
    cfg["voice"]["bindings"] = {"": asset["id"]}
    ln, err = lines.add("你好呀，我是大肥鱼", voice_slot=asset["id"])
    assert ln is not None and not err, err
    ok, err = svc.speak_line(ln["id"])
    assert ok and not err, err
    assert _wait(lambda: fin.is_set()), "播放未完成"
    assert len(played) == 1 and os.path.isfile(played[0])
    assert len(stub.calls) == 1
    assert not errs
    # 同声音同文本第二次：命中缓存，不再调后端
    fin.clear()
    ok, err = svc.speak_line(ln["id"])
    assert ok and not err
    assert _wait(lambda: fin.is_set())
    assert len(stub.calls) == 1, "缓存未命中（重复调用后端）"
    assert len(played) == 2
    # 重新生成：清缓存后再次调后端
    assert svc.regenerate(ln["id"]) == (True, "")
    fin.clear()
    svc.speak_line(ln["id"])
    assert _wait(lambda: fin.is_set())
    assert len(stub.calls) == 2


def test_speak_dialogue_order(tmp_path):
    stub = StubBackend()
    pet_voice.BACKENDS["stub"] = stub
    lines, assets, asset, cfg, svc, played, fin, errs = _env(tmp_path, stub)
    a, _ = lines.add("第一句", voice_slot=asset["id"])
    b, _ = lines.add("第二句", voice_slot=asset["id"])
    d, err = lines.add_dialogue("对白", [a["id"], b["id"]])
    assert d is not None and not err
    order = []
    svc.on_speaking_started(lambda role, lid: order.append(lid))
    done = threading.Event()
    svc.on_dialogue_finished(lambda: done.set())
    ok, err = svc.speak_dialogue(d["id"])
    assert ok and not err, err
    assert _wait(lambda: done.is_set()), "对白未播完"
    assert order == [a["id"], b["id"]]  # 按编排顺序、各自声音
    assert len(played) == 2


def test_errors_and_stop(tmp_path):
    fail = FailBackend()
    pet_voice.BACKENDS["fail"] = fail
    lines, assets, asset, cfg, svc, played, fin, errs = _env(tmp_path, fail)
    ln, _ = lines.add("会失败的台词", voice_slot=asset["id"])
    ok, err = svc.speak_line(ln["id"])
    assert ok  # 入队成功，失败经回调明确告知
    assert _wait(lambda: len(errs) > 0)
    assert "故意失败" in errs[0]
    assert played == []
    # 总开关关闭 → 阻止播放并明确原因
    cfg["voice"]["enabled"] = False
    ok, err = svc.speak_line(ln["id"])
    assert not ok and "总开关" in err
    cfg["voice"]["enabled"] = True
    # 台词被删 → 明确报错
    assert lines.delete(ln["id"]) == (True, "")
    ok, err = svc.speak_line(ln["id"])
    assert not ok and "不存在" in err
    # 没绑声音 → 明确报错
    ln2, _ = lines.add("没绑声音")
    ok, err = svc.speak_line(ln2["id"])
    assert not ok and "声音" in err
    # stop 清空队列
    cfg["voice"]["bindings"] = {"": asset["id"]}
    for i in range(3):
        lines.add("排队台词%d" % i, voice_slot=asset["id"])
    ids = [x["id"] for x in lines.lines() if x["text"].startswith("排队台词")]
    for i in ids:
        svc.speak_line(i)
    svc.stop()
    assert svc.queue_size() == 0


def test_event_clip_and_preview(tmp_path):
    stub = StubBackend()
    pet_voice.BACKENDS["stub"] = stub
    lines, assets, asset, cfg, svc, played, fin, errs = _env(tmp_path, stub)
    src = _wav(tmp_path / "clip.wav")
    assert svc.set_clip("reply", src) == (True, "")
    assert svc.clip("reply") is not None
    svc.play_event("reply")
    assert played and played[-1] == svc.clip("reply")
    assert svc.set_clip("reply", None) == (True, "")
    assert svc.clip("reply") is None
    assert svc.set_clip("nope", src)[0] is False
    # 试听声音素材
    fin.clear()
    ok, err = svc.preview_asset(asset["id"])
    assert ok and not err, err
    assert _wait(lambda: fin.is_set())
    assert svc.preview_asset("ghost")[0] is False


def test_test_backend_reports(tmp_path):
    stub = StubBackend()
    pet_voice.BACKENDS["stub"] = stub
    try:
        lines, assets, asset, cfg, svc, played, fin, errs = _env(tmp_path, stub)
        ok, msg = svc.test_backend("stub")
        assert ok, msg
        ok2, msg2 = svc.test_backend("minimax")  # 缺 Key
        assert not ok2 and "Key" in msg2
        ok3, msg3 = svc.test_backend("gpt_sovits")
        # 本机若真跑着 GPT-SoVITS（9880 通了）也算通过：这里只断言"结论明确、不是静默"
        assert ok3 or ("连不上" in msg3 or "无响应" in msg3 or "探测失败" in msg3), msg3
    finally:
        pet_voice.BACKENDS.pop("stub", None)  # L4：清理注入，避免污染其它测试/顺序相关失败
