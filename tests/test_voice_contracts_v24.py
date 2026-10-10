# -*- coding: utf-8 -*-
"""v2.4 语音后端「服务端契约」测试（代理 C）：不联网，用假 HTTP 钉住各家请求体。

目的：以后改后端适配（换地址/改字段名/换返回解析）时，破了契约立刻变红。
每个后端都钉四件事：
  1. **URL 拼接**（含 base_url 带尾斜杠 / 缺失地址）；
  2. **请求字段名与形态**（payload 键、multipart 字段名、参考音字段名、鉴权头）；
  3. **返回解析**（裸音频字节 / JSON 里的 base64 / url / path / hex）；
  4. **错误码映射**（HTTP 状态码 → 中文原因，绝不能静默）。

另覆盖三条降级路径：后端不支持（未知 id / 缺地址）、请求超时、返回坏 JSON。
所有网络调用都被 tests 内的假 requests 顶掉——用例里**不会**有任何真实连接。

v2.4.1 补齐（本轮）：
  · SAPI（唯一不走 HTTP 的后端）：它的"请求体"是那条 powershell 命令——命令内容、
    单引号转义、返回解析、临时 wav 清理、四种失败（退出码/空文件/没有 powershell/超时）；
  · MiniMax 上传返回**不是对象**（数组/字符串/null）时不得让 AttributeError 穿透；
  · _decode_json_audio 的 file 键（真音频/文本/缺失）与 url 下载失败（非 200 / 抛异常）；
  · 服务层契约：旧链路（sapi/openai）没填自己的 Key 时回退 AI 设置里的 api_key、
    缓存扩展名按后端定（云端三家 mp3，其余 wav）、注册表 key 与 backend.id 一致。
"""
import base64
import io
import json
import os
import re
import subprocess
import sys
import wave

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pet_voice  # noqa: E402


# ---------------- 假 HTTP ----------------

class FakeResp(object):
    """最小响应替身：只提供后端代码真正会碰的字段。"""

    def __init__(self, status=200, content=b"RIFF" + b"\x00" * 200,
                 json_data=None, headers=None, json_exc=None):
        self.status_code = status
        self.content = content
        self.headers = dict(headers or {})
        self._json = json_data
        self._json_exc = json_exc

    def json(self):
        if self._json_exc is not None:
            raise self._json_exc
        return self._json


class FakeRequests(object):
    """记录全部调用并按剧本返回；剧本用尽即报错（防止用例漏配响应而"看起来通过"）。"""

    class exceptions(object):
        class Timeout(Exception):
            pass

        class ConnectionError(Exception):
            pass

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def _do(self, method, url, **kw):
        call = {"method": method, "url": url}
        call.update(kw)
        self.calls.append(call)
        if not self.replies:
            raise AssertionError("测试脚本没给这次请求准备响应：%s %s" % (method, url))
        r = self.replies.pop(0)
        if isinstance(r, BaseException):
            raise r
        if callable(r):
            return r(url, kw)
        return r

    def post(self, url, **kw):
        return self._do("post", url, **kw)

    def get(self, url, **kw):
        return self._do("get", url, **kw)

    # 断言辅助
    def only(self):
        assert len(self.calls) == 1, "期望恰好一次请求，实际 %d 次" % (len(self.calls),)
        return self.calls[0]


@pytest.fixture
def http(monkeypatch):
    """装一个假 requests（返回值即记录器），用完自动还原。"""

    def _install(*replies):
        fake = FakeRequests(replies)
        monkeypatch.setattr(pet_voice, "requests", fake)
        return fake

    return _install


@pytest.fixture
def ref_wav(tmp_path):
    """一个真实的参考音 wav（multipart 上传路径需要真文件）。"""
    p = tmp_path / "参考音.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 160)
    return str(p)


def _backend(bid):
    return pet_voice.get_backend(bid)


# ================= GPT-SoVITS：GET /tts（api v2）/ POST /tts（api v1） =================

def test_gpt_sovits_v2_get_contract(http, ref_wav):
    """v2（默认）：GET {base}/tts + 查询参数名逐个钉住；200 裸字节原样返回。"""
    fake = http(FakeResp(200, b"RIFF" + b"\x01" * 64))
    data, err = _backend("gpt_sovits").synthesize(
        ref_wav, "你好呀", {"base_url": "http://127.0.0.1:9880/", "api": "v2",
                            "prompt_text": "参考文本", "text_lang": "zh",
                            "prompt_lang": "ja", "split_method": "cut3"})
    assert err == "" and data.startswith(b"RIFF")
    c = fake.only()
    assert c["method"] == "get"
    assert c["url"] == "http://127.0.0.1:9880/tts", "尾斜杠没吃掉或路径拼错：%r" % (c["url"],)
    assert c["params"] == {"text": "你好呀", "text_lang": "zh",
                           "ref_audio_path": ref_wav, "prompt_text": "参考文本",
                           "prompt_lang": "ja", "text_split_method": "cut3",
                           "media_type": "wav", "streaming_mode": "false"}, \
        "GPT-SoVITS v2 查询参数名变了：%r" % (c["params"],)
    assert c["timeout"] == 60


def test_gpt_sovits_v1_post_contract(http, ref_wav):
    """v1：POST {base}/tts + JSON 体字段名（refer_wav_path/prompt_language/text_language）。"""
    fake = http(FakeResp(200, b"RIFF" + b"\x02" * 64))
    data, err = _backend("gpt_sovits").synthesize(
        ref_wav, "早上好", {"base_url": "http://127.0.0.1:9880", "api": "v1",
                            "prompt_text": "pt", "text_lang": "zh", "prompt_lang": "en"})
    assert err == "" and data.startswith(b"RIFF")
    c = fake.only()
    assert c["method"] == "post" and c["url"] == "http://127.0.0.1:9880/tts"
    assert c["json"] == {"refer_wav_path": ref_wav, "prompt_text": "pt",
                         "prompt_language": "en", "text": "早上好",
                         "text_language": "zh"}, "GPT-SoVITS v1 请求体字段名变了：%r" % (c["json"],)
    assert "params" not in c or not c.get("params")


def test_gpt_sovits_error_and_empty_paths(http, ref_wav):
    """错误码映射 + 空音频 + 缺地址/缺参考音的明确报错（绝不静默）。"""
    b = _backend("gpt_sovits")
    fake = http(FakeResp(401))
    data, err = b.synthesize(ref_wav, "x", {"base_url": "http://h"})
    assert data is None and err == "GPT-SoVITS：后端鉴权失败（API Key 无效）", err
    fake = http(FakeResp(404))
    assert "后端没有这个接口" in b.synthesize(ref_wav, "x", {"base_url": "http://h"})[1]
    fake = http(FakeResp(413))
    assert "参考音太大" in b.synthesize(ref_wav, "x", {"base_url": "http://h"})[1]
    fake = http(FakeResp(418))
    assert "HTTP 418" in b.synthesize(ref_wav, "x", {"base_url": "http://h"})[1]
    fake = http(FakeResp(200, b""))
    assert "返回空音频" in b.synthesize(ref_wav, "x", {"base_url": "http://h"})[1]
    # 缺地址 / 参考音不存在：直接给中文原因，一个请求都不发
    fake = http()
    d, e = b.synthesize(ref_wav, "x", {"base_url": "  "})
    assert d is None and "没填 GPT-SoVITS 服务地址" in e and fake.calls == []
    d, e = b.synthesize(os.path.join(os.path.dirname(ref_wav), "没了.wav"), "x",
                        {"base_url": "http://h"})
    assert d is None and "参考音文件不存在" in e and fake.calls == []


# ================= F5-TTS：POST /tts（multipart ref_audio/ref_text/gen_text） =================

def _files_summary(files):
    """把 multipart files 归一成 {字段名: (文件名, 内容类型)}（文件对象只取元信息）。"""
    out = {}
    for k, v in (files or {}).items():
        name, fobj, ctype = v
        out[k] = (name, ctype)
    return out


def test_f5_tts_multipart_contract(http, ref_wav):
    """F5-TTS：POST {base}/tts，multipart 字段名 ref_audio/ref_text/gen_text。"""
    fake = http(FakeResp(200, b"RIFF" + b"\x03" * 64, headers={"Content-Type": "audio/wav"}))
    data, err = _backend("f5_tts").synthesize(
        ref_wav, "hello 你好", {"base_url": "http://127.0.0.1:7860/", "ref_text": "参考"})
    assert err == "" and data.startswith(b"RIFF")
    c = fake.only()
    assert c["method"] == "post" and c["url"] == "http://127.0.0.1:7860/tts"
    assert c["data"] == {"ref_text": "参考", "gen_text": "hello 你好"}, \
        "F5-TTS 表单字段名变了：%r" % (c["data"],)
    assert _files_summary(c["files"]) == {"ref_audio": (os.path.basename(ref_wav), "audio/wav")}, \
        "F5-TTS 参考音字段名/类型变了：%r" % (_files_summary(c["files"]),)


def test_f5_tts_json_and_bad_json_paths(http, ref_wav):
    """F5-TTS：Content-Type=json 时走 _decode_json_audio（base64 / url / 坏 JSON）。"""
    wav = b"RIFF" + b"\x04" * 128
    fake = http(FakeResp(200, b"{}", json_data={"audio": base64.b64encode(wav).decode()},
                         headers={"Content-Type": "application/json"}))
    data, err = _backend("f5_tts").synthesize(ref_wav, "t", {"base_url": "http://h"})
    assert err == "" and data == wav

    fake = http(FakeResp(200, b"{}", json_data={"url": "http://h/out.wav"},
                         headers={"Content-Type": "application/json; charset=utf-8"}),
                FakeResp(200, wav))
    data, err = _backend("f5_tts").synthesize(ref_wav, "t", {"base_url": "http://h"})
    assert err == "" and data == wav
    assert fake.calls[1]["url"] == "http://h/out.wav"

    # 坏 JSON：解析失败必须给中文原因，不能抛
    fake = http(FakeResp(200, b"not json", headers={"Content-Type": "application/json"},
                         json_exc=ValueError("Expecting value")))
    data, err = _backend("f5_tts").synthesize(ref_wav, "t", {"base_url": "http://h"})
    assert data is None and "F5-TTS 返回内容无法解析" in err, err

    # JSON 里没有音频字段
    fake = http(FakeResp(200, b"{}", json_data={"ok": True},
                         headers={"Content-Type": "application/json"}))
    data, err = _backend("f5_tts").synthesize(ref_wav, "t", {"base_url": "http://h"})
    assert data is None and "没有音频数据" in err, err

    # JSON 里 audio 是 base64 的 HTML：必须拒绝，别把垃圾写进缓存
    fake = http(FakeResp(200, b"{}",
                         json_data={"audio": base64.b64encode(b"<html>err</html>").decode()},
                         headers={"Content-Type": "application/json"}))
    data, err = _backend("f5_tts").synthesize(ref_wav, "t", {"base_url": "http://h"})
    assert data is None and "不是音频数据" in err, err

    # 200 + 空 body + 非 json 类型
    fake = http(FakeResp(200, b"", headers={"Content-Type": "audio/wav"}))
    data, err = _backend("f5_tts").synthesize(ref_wav, "t", {"base_url": "http://h"})
    assert data is None and "返回空音频" in err, err


# ================= CosyVoice：POST /inference_zero_shot =================

def test_cosyvoice_multipart_contract(http, ref_wav):
    """CosyVoice：POST {base}/inference_zero_shot，字段 tts_text/prompt_text/prompt_wav。"""
    fake = http(FakeResp(200, b"RIFF" + b"\x05" * 64, headers={"Content-Type": "audio/wav"}))
    data, err = _backend("cosyvoice").synthesize(
        ref_wav, "读这句", {"base_url": "http://127.0.0.1:50000", "prompt_text": "参考"})
    assert err == "" and data.startswith(b"RIFF")
    c = fake.only()
    assert c["method"] == "post"
    assert c["url"] == "http://127.0.0.1:50000/inference_zero_shot"
    assert c["data"] == {"tts_text": "读这句", "prompt_text": "参考"}, \
        "CosyVoice 字段名变了：%r" % (c["data"],)
    assert _files_summary(c["files"]) == {"prompt_wav": (os.path.basename(ref_wav), "audio/wav")}, \
        "CosyVoice 参考音字段名变了：%r" % (_files_summary(c["files"]),)


def test_cosyvoice_error_paths(http, ref_wav):
    """CosyVoice：状态码映射 + JSON 返回 + 空音频 + 缺地址。"""
    b = _backend("cosyvoice")
    http(FakeResp(422))
    assert "后端参数校验失败" in b.synthesize(ref_wav, "x", {"base_url": "http://h"})[1]
    http(FakeResp(200, b"", headers={"Content-Type": "audio/wav"}))
    assert "返回空音频" in b.synthesize(ref_wav, "x", {"base_url": "http://h"})[1]
    http(FakeResp(200, b"{}", json_data={"audio": base64.b64encode(b"OggS" + b"\x06" * 64).decode()},
                  headers={"Content-Type": "application/json"}))
    data, err = b.synthesize(ref_wav, "x", {"base_url": "http://h"})
    assert err == "" and data.startswith(b"OggS")
    fake = http()
    d, e = b.synthesize(ref_wav, "x", {"base_url": ""})
    assert d is None and "没填 CosyVoice 服务地址" in e and fake.calls == []


# ================= MiniMax：上传 → 克隆 → 合成 =================

def _minimax_params(extra=None):
    p = {"base_url": "https://api.minimax.chat", "model": "speech-02-hd", "cloned": {}}
    p.update(extra or {})
    return p


def test_minimax_clone_then_speak_contract(http, ref_wav):
    """MiniMax：/v1/files/upload(purpose=voice_clone) → /v1/voice_clone → /v1/t2a_v2。"""
    fake = http(FakeResp(200, b"{}", json_data={"file": {"file_id": "fid-1"}}),
                FakeResp(200, b"{}", json_data={"voice_id": "vid-9"}),
                FakeResp(200, b"{}", json_data={"data": {"audio": (b"RIFF" + b"\x07" * 32).hex()}}))
    params = _minimax_params({"_slot": "asset-1"})
    data, err = _backend("minimax").synthesize(ref_wav, "你好", params, key="mm-key")
    assert err == "" and data.startswith(b"RIFF"), err
    assert params["cloned"]["asset-1"] == "vid-9", "克隆结果没有记进 params['cloned']"

    up, clone, t2a = fake.calls
    assert up["method"] == "post" and up["url"] == "https://api.minimax.chat/v1/files/upload"
    assert up["data"] == {"purpose": "voice_clone"}, up["data"]
    assert _files_summary(up["files"]) == {"file": (os.path.basename(ref_wav), "audio/wav")}
    assert up["headers"] == {"Authorization": "Bearer mm-key"}, "MiniMax 鉴权头变了"

    assert clone["url"] == "https://api.minimax.chat/v1/voice_clone"
    assert clone["json"] == {"file_id": "fid-1"}, clone["json"]
    assert clone["headers"] == {"Authorization": "Bearer mm-key"}

    assert t2a["url"] == "https://api.minimax.chat/v1/t2a_v2"
    assert t2a["json"] == {
        "model": "speech-02-hd", "text": "你好",
        "voice_setting": {"voice_id": "vid-9", "speed": 1.0, "vol": 1.0, "pitch": 0},
        "audio_setting": {"format": "mp3", "sample_rate": 32000}}, \
        "MiniMax 合成请求体变了：%r" % (t2a["json"],)


def test_minimax_reuses_cloned_voice(http, ref_wav):
    """复用已克隆声线：只发 /v1/t2a_v2，不再重复上传/克隆。"""
    fake = http(FakeResp(200, b"{}", json_data={"data": {"audio": (b"RIFF" + b"\x08" * 32).hex()}}))
    params = _minimax_params({"cloned": {"asset-1": "vid-cached"}, "_slot": "asset-1"})
    data, err = _backend("minimax").synthesize(ref_wav, "再来一句", params, key="k")
    assert err == "" and data.startswith(b"RIFF")
    assert len(fake.calls) == 1 and fake.calls[0]["url"].endswith("/v1/t2a_v2")
    assert fake.calls[0]["json"]["voice_setting"]["voice_id"] == "vid-cached"


def test_minimax_error_paths(http, ref_wav):
    """MiniMax 三阶段（上传→克隆→合成）的错误路径都要有中文原因。

    v2.4.1 红→绿说明：本轮实测的红就是这条用例。原因是**用例自己搭错了剧本**——
    "合成阶段 base_resp 报错"这一格必须让 MiniMax 走**复用已克隆声线**的分支
    （params["cloned"] 里有该槽位 + params["_slot"] 指过去），否则代码会先打
    /v1/files/upload，而那条假响应里没有 file_id，于是报"没有返回 file_id"——
    断言"MiniMax 合成失败"自然不成立。代码侧的错误路径本身是对的：
      · 上传 200 但 base_resp 非 0 → "MiniMax 上传参考音失败：<msg>（code=…）"；
      · 克隆 200 但 base_resp 非 0 → "MiniMax 克隆失败：<msg>（code=…）"；
      · 合成 200 但 base_resp 非 0 → "MiniMax 合成失败：<msg>（code=…）"。
    没有为了变绿弱化断言：去掉上面任何一条 base_resp 透出，本用例立刻变红
    （变异验证 M1/M2，见交接）。
    """
    b = _backend("minimax")
    fake = http()
    d, e = b.synthesize(ref_wav, "x", _minimax_params(), key="")
    assert d is None and "没填 MiniMax API Key" in e and fake.calls == []

    http(FakeResp(200, b"{}", json_data={"file": {}}))
    assert "没有返回 file_id" in b.synthesize(ref_wav, "x", _minimax_params(), key="k")[1]

    # 上传阶段 HTTP 200 但 body 里 base_resp 报错 → 必须透出服务端原因，别报"格式变了"
    http(FakeResp(200, b"{}", json_data={"base_resp": {"status_code": 1002,
                                                       "status_msg": "余额不足"}}))
    d, e = b.synthesize(ref_wav, "x", _minimax_params(), key="k")
    assert d is None and "MiniMax 上传参考音失败" in e and "余额不足" in e and "1002" in e, e
    # base_resp 是成功码（0）但没 file → 仍是"格式变了"，别把 success 当失败报
    http(FakeResp(200, b"{}", json_data={"base_resp": {"status_code": 0,
                                                       "status_msg": "success"}}))
    d, e = b.synthesize(ref_wav, "x", _minimax_params(), key="k")
    assert d is None and "没有返回 file_id" in e, e

    # 克隆阶段返回 base_resp 报错
    http(FakeResp(200, b"{}", json_data={"file": {"file_id": "fid"}}),
         FakeResp(200, b"{}", json_data={"base_resp": {"status_code": 1002,
                                                       "status_msg": "余额不足"}}))
    d, e = b.synthesize(ref_wav, "x", _minimax_params(), key="k")
    assert d is None and "MiniMax 克隆失败" in e and "余额不足" in e and "1002" in e, e

    # 合成阶段返回 base_resp 报错（复用已克隆声线）
    http(FakeResp(200, b"{}", json_data={"base_resp": {"status_code": 1004,
                                                       "status_msg": "声线不存在"}}))
    d, e = b.synthesize(ref_wav, "x", _minimax_params({"cloned": {"a": "v"}, "_slot": "a"}), key="k")
    assert d is None and "MiniMax 合成失败" in e and "声线不存在" in e, e

    # 克隆阶段 HTTP 失败 → 状态码映射
    http(FakeResp(401))
    assert "后端鉴权失败" in b.synthesize(ref_wav, "x", _minimax_params(), key="k")[1]

    # 克隆返回坏 JSON
    http(FakeResp(200, b"{}", json_data={"file": {"file_id": "fid"}}),
         FakeResp(200, b"oops", json_exc=ValueError("bad json")))
    d, e = b.synthesize(ref_wav, "x", _minimax_params(), key="k")
    assert d is None and "MiniMax 克隆返回无法解析" in e, e

    # 合成返回里既没有 audio 也没有 base_resp
    http(FakeResp(200, b"{}", json_data={"data": {}}))
    d, e = b.synthesize(ref_wav, "x", _minimax_params({"cloned": {"a": "v"}, "_slot": "a"}), key="k")
    assert d is None and "没有返回音频数据" in e, e

    # 合成返回坏 JSON
    http(FakeResp(200, b"oops", json_exc=ValueError("bad json")))
    d, e = b.synthesize(ref_wav, "x", _minimax_params({"cloned": {"a": "v"}, "_slot": "a"}), key="k")
    assert d is None and "MiniMax 返回内容无法解析" in e, e


# ================= ElevenLabs：克隆 → 合成 =================

def test_elevenlabs_clone_then_speak_contract(http, ref_wav):
    """ElevenLabs：/v1/voices/add（multipart files）→ /v1/text-to-speech/{voice_id}。"""
    fake = http(FakeResp(200, b"{}", json_data={"voice_id": "el-vid"}),
                FakeResp(200, b"ID3" + b"\x09" * 64))
    params = {"base_url": "https://api.elevenlabs.io", "model": "eleven_multilingual_v2",
              "cloned": {}, "_slot": "asset-e"}
    data, err = _backend("elevenlabs").synthesize(ref_wav, "hi 你好", params, key="el-key")
    assert err == "" and data.startswith(b"ID3"), err
    assert params["cloned"]["asset-e"] == "el-vid"

    add, tts = fake.calls
    assert add["url"] == "https://api.elevenlabs.io/v1/voices/add"
    assert add["headers"] == {"xi-api-key": "el-key"}, "ElevenLabs 鉴权头变了"
    assert _files_summary(add["files"]) == {"files": (os.path.basename(ref_wav), "audio/wav")}, \
        "ElevenLabs 参考音字段名变了：%r" % (_files_summary(add["files"]),)
    assert add["data"]["name"].startswith("daifeiyu_"), add["data"]

    assert tts["url"] == "https://api.elevenlabs.io/v1/text-to-speech/el-vid"
    assert tts["json"] == {"text": "hi 你好", "model_id": "eleven_multilingual_v2"}
    assert tts["headers"] == {"xi-api-key": "el-key"}


def test_elevenlabs_error_paths(http, ref_wav):
    """ElevenLabs：缺 Key / 缺 voice_id / 空音频 / 状态码映射 / 坏 JSON。"""
    b = _backend("elevenlabs")
    fake = http()
    d, e = b.synthesize(ref_wav, "x", {"base_url": "", "cloned": {}}, key="")
    assert d is None and "没填 ElevenLabs API Key" in e and fake.calls == []
    http(FakeResp(200, b"{}", json_data={}))
    assert "没有返回 voice_id" in b.synthesize(ref_wav, "x", {"cloned": {}}, key="k")[1]
    http(FakeResp(200, b"oops", json_exc=ValueError("bad")))
    assert "没有返回 voice_id" in b.synthesize(ref_wav, "x", {"cloned": {}}, key="k")[1]
    http(FakeResp(429))
    assert "请求太频繁" in b.synthesize(ref_wav, "x", {"cloned": {}}, key="k")[1]
    # 复用缓存声线时：空音频要明确报错（槽位键用 _slot，走的是"跳过克隆"分支）
    http(FakeResp(200, b""))
    d, e = b.synthesize(ref_wav, "x", {"cloned": {"asset-e": "vid"}, "_slot": "asset-e"}, key="k")
    assert d is None and "返回空音频" in e, e


# ================= OpenAI 兼容固定音色（/audio/speech） =================

def test_openai_speech_contract_and_errors(http):
    """OpenAI 兼容：POST {base}/audio/speech + Bearer 头 + 状态码用 explain_tts_error 口径。"""
    fake = http(FakeResp(200, b"ID3" + b"\x0a" * 64))
    data, err = _backend("openai").synthesize(
        None, "读我", {"base_url": "https://api.example.com/", "model": "tts-1", "voice": "alloy"},
        key="sk-1")
    assert err == "" and data.startswith(b"ID3")
    c = fake.only()
    assert c["url"] == "https://api.example.com/audio/speech", c["url"]
    assert c["json"] == {"model": "tts-1", "input": "读我", "voice": "alloy"}
    assert c["headers"] == {"Authorization": "Bearer sk-1"}

    http(FakeResp(404))
    assert _backend("openai").synthesize(
        None, "x", {"base_url": "http://h"}, key="k")[1] == \
        "语音合成受限：当前接口不支持语音合成（服务商无 /audio/speech）"
    http(FakeResp(429))
    assert "请求太频繁" in _backend("openai").synthesize(
        None, "x", {"base_url": "http://h"}, key="k")[1]
    http(FakeResp(200, b""))
    assert "返回空内容" in _backend("openai").synthesize(
        None, "x", {"base_url": "http://h"}, key="k")[1]
    fake = http()
    d, e = _backend("openai").synthesize(None, "x", {"base_url": ""}, key="k")
    assert d is None and "没填 OpenAI 兼容接口地址" in e and fake.calls == []


# ================= 错误码映射（纯函数口径） =================

def test_error_code_mapping_is_stable():
    """状态码 → 中文原因：每个码都钉住关键词，未知码必须带状态码。"""
    assert "参数/参考音" in pet_voice.explain_backend_error(400)
    assert "鉴权失败" in pet_voice.explain_backend_error(401)
    assert "额度不足" in pet_voice.explain_backend_error(402)
    assert "拒绝访问" in pet_voice.explain_backend_error(403)
    assert "没有这个接口" in pet_voice.explain_backend_error(404)
    assert "参考音太大" in pet_voice.explain_backend_error(413)
    assert "参数校验失败" in pet_voice.explain_backend_error(422)
    assert "频繁" in pet_voice.explain_backend_error(429)
    assert "HTTP 500" in pet_voice.explain_backend_error(500)
    assert "HTTP 503" in pet_voice.explain_backend_error(503)
    assert "HTTP 418" in pet_voice.explain_backend_error(418)
    # 旧固定音色链路（TTS_API_ERRORS）单独一套口径，不能被克隆后端的映射覆盖
    assert pet_voice.explain_tts_error(401) == "密钥无效"
    assert pet_voice.explain_tts_error(402) == "额度不足"
    assert pet_voice.explain_tts_error(403) == "地区限制或服务不可用"
    assert "不支持语音合成" in pet_voice.explain_tts_error(404)
    assert pet_voice.explain_tts_error(429) == "请求太频繁，稍后再试"
    assert pet_voice.explain_tts_error(500) == "服务不可用（HTTP 500）"


# ================= 降级路径 1：后端不支持 =================

def test_unknown_backend_falls_back_not_crashes(http, tmp_path):
    """未知后端 id：注册表回退默认，服务层也不崩（配置写坏不能把语音打死）。"""
    assert pet_voice.get_backend("ghost").id == pet_voice.DEFAULT_BACKEND
    assert pet_voice.get_backend(None).id == pet_voice.DEFAULT_BACKEND
    assert pet_voice.get_backend("").id == pet_voice.DEFAULT_BACKEND

    cfg = {"voice": dict(pet_voice.DEFAULT_VOICE)}
    cfg["voice"]["backend"] = "ghost_backend"
    cfg["voice"]["enabled"] = True
    svc = pet_voice.VoiceService(str(tmp_path), lambda: cfg, lambda p: None, log=lambda m: None)
    assert svc.backend_id() == pet_voice.DEFAULT_BACKEND
    ok, msg = svc.check_ready()          # 缺 Key 的云端后端才该拦；本地后端放行
    assert ok and msg == ""
    ok2, msg2 = svc.check_ready("minimax")
    assert not ok2 and "API Key" in msg2, msg2


def test_backend_without_capability_reports_clearly(http, ref_wav):
    """能力缺失（未填地址/未实现）必须明确报错，绝不假装成功。"""
    b = pet_voice.get_backend("gpt_sovits")
    fake = http()
    d, e = b.synthesize(ref_wav, "x", {})
    assert d is None and e and fake.calls == [], "缺地址时不该发请求，且必须给中文原因"
    # 抽象基类不假装实现
    with pytest.raises(NotImplementedError):
        pet_voice.VoiceBackend().synthesize(None, "x", {})


# ================= 降级路径 2：超时 / 连不上 =================

@pytest.mark.parametrize("bid,params,key", [
    ("gpt_sovits", {"base_url": "http://h"}, ""),
    ("f5_tts", {"base_url": "http://h"}, ""),
    ("cosyvoice", {"base_url": "http://h"}, ""),
    ("minimax", {"base_url": "http://h", "cloned": {}}, "k"),
    ("elevenlabs", {"base_url": "http://h", "cloned": {}}, "k"),
    ("openai", {"base_url": "http://h"}, "k"),
])
def test_timeout_and_connection_error_are_translated(http, ref_wav, bid, params, key):
    """超时 / 连不上：中文原因（不是裸异常，也不是静默失败）。"""
    b = pet_voice.get_backend(bid)
    fake = http(FakeRequests.exceptions.Timeout())
    d, e = b.synthesize(ref_wav, "x", params, key=key)
    assert d is None and e == "连接后端超时（服务没启动或响应太慢）", (bid, e)

    fake = http(FakeRequests.exceptions.ConnectionError())
    d, e = b.synthesize(ref_wav, "x", params, key=key)
    assert d is None and e == "连不上后端服务（检查地址、服务是否已启动）", (bid, e)

    http(RuntimeError("socket 爆炸"))          # 其它异常也不能穿透
    d, e = b.synthesize(ref_wav, "x", params, key=key)
    assert d is None and e.startswith("请求后端失败："), (bid, e)


def test_test_backend_reports_timeout_without_network(http, tmp_path, ref_wav):
    """后端自检：探测超时 → 明确的中文结论（走假 requests，不联网）。"""
    import pet_resources
    assets = pet_resources.VoiceAssetLibrary(str(tmp_path))
    asset, err = assets.import_file(ref_wav, "自检音色")
    assert asset is not None and not err, err
    cfg = {"voice": dict(pet_voice.DEFAULT_VOICE)}
    svc = pet_voice.VoiceService(str(tmp_path), lambda: cfg, lambda p: None,
                                 log=lambda m: None, voice_assets=assets)
    fake = http(FakeRequests.exceptions.Timeout())
    ok, msg = svc.test_backend("gpt_sovits")
    assert not ok and "服务无响应（超时）" in msg, msg
    assert fake.calls[0]["url"].startswith("http://127.0.0.1:9880")
    fake = http(FakeResp(200))
    ok, msg = svc.test_backend("gpt_sovits")
    assert ok and "服务可达（HTTP 200）" in msg, msg


# ================= 降级路径 3：返回坏 JSON =================

def test_decode_json_audio_bad_payloads(monkeypatch):
    """_decode_json_audio：坏 JSON / 缺字段 / 非音频内容，三条都要有中文原因。"""
    resp = FakeResp(200, b"", json_exc=ValueError("Expecting value"))
    d, e = pet_voice._decode_json_audio(resp, "某后端")
    assert d is None and "某后端 返回内容无法解析" in e
    resp = FakeResp(200, b"", json_data={"nope": 1})
    assert "没有音频数据" in pet_voice._decode_json_audio(resp, "某后端")[1]
    resp = FakeResp(200, b"", json_data={"audio": ""})
    assert "没有音频数据" in pet_voice._decode_json_audio(resp, "某后端")[1]
    # 合法 base64 但内容是 HTML 文本 → 必须按"不是音频数据"拒绝（别写进缓存无声播放）
    html_b64 = base64.b64encode(b"<html>error page</html>").decode("ascii")
    resp = FakeResp(200, b"", json_data={"audio": html_b64})
    assert "不是音频数据" in pet_voice._decode_json_audio(resp, "某后端")[1]
    # 连 base64 都不是（且没有 url/path/file 兜底）→ 明确"没有音频数据"
    resp = FakeResp(200, b"", json_data={"audio": "!!!不是base64!!!"})
    assert "没有音频数据" in pet_voice._decode_json_audio(resp, "某后端")[1]
    # path 指向一个真实存在的文本文件 → 魔数/文本判定必须拒绝
    import tempfile
    p = os.path.join(tempfile.mkdtemp(prefix="dfy_json_"), "x.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write("<html>错误页</html>")
    resp = FakeResp(200, b"", json_data={"path": p})
    assert "不是音频数据" in pet_voice._decode_json_audio(resp, "某后端")[1]
    # url 下载到 HTML → 拒绝
    fake = FakeRequests([FakeResp(200, "<html>err</html>".encode("utf-8"))])
    monkeypatch.setattr(pet_voice, "requests", fake)
    resp = FakeResp(200, b"", json_data={"url": "http://h/x.wav"})
    d, e = pet_voice._decode_json_audio(resp, "某后端")
    assert d is None and "下载到的 url 不是音频数据" in e, e

# ================= SAPI：Windows 系统语音（唯一不走 HTTP 的后端） =================

class _FakeProc(object):
    def __init__(self, returncode=0, stderr=b""):
        self.returncode = returncode
        self.stderr = stderr


class _FakeSubprocess(object):
    """假 subprocess：记录 powershell 命令，并按剧本把 wav 写到命令里的目标路径。"""

    TimeoutExpired = subprocess.TimeoutExpired   # SapiBackend 要 except 这个类型

    def __init__(self, *, write=None, returncode=0, stderr=b"", exc=None):
        self.write = write
        self.returncode = returncode
        self.stderr = stderr
        self.exc = exc
        self.calls = []

    def run(self, cmd, **kw):
        self.calls.append({"cmd": list(cmd), "kwargs": dict(kw)})
        if self.exc is not None:
            raise self.exc
        if self.write is not None:
            path = _wav_path_in(cmd[-1])
            assert path, "命令里没有 SetOutputToWaveFile：%r" % (cmd[-1],)
            with open(path, "wb") as f:
                f.write(self.write)
        return _FakeProc(self.returncode, self.stderr)


def _sapi(monkeypatch, **kw):
    fake = _FakeSubprocess(**kw)
    monkeypatch.setattr(pet_voice, "subprocess", fake)
    return fake


def _wav_path_in(ps):
    """从 powershell 命令里取出 SetOutputToWaveFile 的目标路径（非贪婪：后面还有 Speak('…')）。"""
    m = re.search(r"SetOutputToWaveFile\('(.*?)'\)", ps)
    return m.group(1) if m else None


def test_sapi_backend_powershell_command_and_cleanup(monkeypatch):
    """SAPI 契约：powershell 命令内容/参数、返回解析、临时 wav 用完即删。

    它没有 HTTP 请求体，"请求体"就是那条 powershell 命令——少一句 Add-Type、少转义
    一个单引号，在真机上就是"点了没声音"，所以在测试里逐项钉住。
    """
    wav = b"RIFF" + b"\x00" * 200
    fake = _sapi(monkeypatch, write=wav)
    b = _backend("sapi")
    data, err = b.synthesize(None, "你好'呀", {"voice": "Microsoft Huihui Desktop"}, "")
    assert err == "" and data == wav, err

    c = fake.calls[0]
    assert c["cmd"][:4] == ["powershell", "-NoProfile", "-NonInteractive", "-Command"], c["cmd"][:4]
    ps = c["cmd"][4]
    assert "Add-Type -AssemblyName System.Speech" in ps
    assert "New-Object System.Speech.Synthesis.SpeechSynthesizer" in ps
    assert "SelectVoice('Microsoft Huihui Desktop')" in ps
    assert "SetOutputToWaveFile('" in ps and "$s.Speak('" in ps and "$s.Dispose()" in ps
    assert "'你好''呀'" in ps, "文本里的单引号没转义（PowerShell 字符串会被截断）：%r" % ps
    assert c["kwargs"] == {"capture_output": True, "timeout": 60}, c["kwargs"]

    # L6：合成用的临时 wav 用完即删（否则 %TEMP% 里越堆越多）
    tmp = _wav_path_in(ps)
    assert tmp and tmp.lower().endswith(".wav"), "临时 wav 路径不对：%r" % (tmp,)
    assert not os.path.exists(tmp), "临时 wav 没有清理：%s" % tmp

    # 没填音色包时不得出现 SelectVoice（PowerShell 里 select 失败会被 catch 吞掉）
    fake2 = _sapi(monkeypatch, write=wav)
    assert b.synthesize(None, "hi", {}, "")[0] == wav
    assert "SelectVoice" not in fake2.calls[0]["cmd"][4]


def test_sapi_backend_failure_paths(monkeypatch):
    """SAPI：退出码非 0 / 只写出文件头 / 没有 PowerShell / 超时——四条都要中文原因。"""
    b = _backend("sapi")

    _sapi(monkeypatch, write=None, returncode=1, stderr="没有可用的语音包".encode("utf-8"))
    d, e = b.synthesize(None, "x", {})
    assert d is None and "本地语音不可用" in e and "没有可用的语音包" in e, e

    # 退出码 0，但只写了 14 字节（<=44 = 只有容器头、没有音频数据）→ 也算失败
    _sapi(monkeypatch, write=b"RIFF" + b"\x00" * 10)
    d, e = b.synthesize(None, "y", {})
    assert d is None and "本地语音不可用" in e, e

    _sapi(monkeypatch, exc=FileNotFoundError("no powershell"))
    d, e = b.synthesize(None, "z", {})
    assert d is None and "没有 PowerShell" in e, e

    _sapi(monkeypatch, exc=subprocess.TimeoutExpired("powershell", 60))
    d, e = b.synthesize(None, "t", {})
    assert d is None and "本地语音合成超时" in e, e


# ================= MiniMax：上传返回体不是对象 =================

def test_minimax_upload_body_not_dict_is_reported(http, ref_wav):
    """上传返回不是对象（数组/字符串/null）→ 中文原因，AttributeError 不得穿透。"""
    b = _backend("minimax")
    for payload in ([{"file": {"file_id": "x"}}], "oops", None):
        http(FakeResp(200, b"{}", json_data=payload))
        d, e = b.synthesize(ref_wav, "x", _minimax_params(), key="k")
        assert d is None and "没有返回 file_id" in e, (payload, e)


# ================= _decode_json_audio：file 键 / 下载失败 =================

def test_decode_json_audio_file_key_and_download_failures(monkeypatch, tmp_path):
    """file 键（真音频 / 文本 / 缺失）与 url 下载失败（非 200 / 抛异常）。"""
    wav = b"RIFF" + b"\x00" * 100
    p = tmp_path / "a.wav"
    p.write_bytes(wav)
    resp = FakeResp(200, b"", json_data={"file": str(p)})
    d, e = pet_voice._decode_json_audio(resp, "某后端")
    assert d == wav and e == "", e

    t = tmp_path / "b.txt"
    t.write_text("<html>错误页</html>", encoding="utf-8")
    resp = FakeResp(200, b"", json_data={"file": str(t)})
    assert "不是音频数据" in pet_voice._decode_json_audio(resp, "某后端")[1]

    resp = FakeResp(200, b"", json_data={"path": str(tmp_path / "missing.wav")})
    assert "没有音频数据" in pet_voice._decode_json_audio(resp, "某后端")[1]

    monkeypatch.setattr(pet_voice, "requests", FakeRequests([FakeResp(404, b"")]))
    resp = FakeResp(200, b"", json_data={"url": "http://h/x.wav"})
    d, e = pet_voice._decode_json_audio(resp, "某后端")
    assert d is None and "下载音频失败（HTTP 404）" in e, e

    # 200 但内容为空：也要说清楚（不能掉到"返回里没有音频数据"这种含糊结论）
    monkeypatch.setattr(pet_voice, "requests", FakeRequests([FakeResp(200, b"")]))
    resp = FakeResp(200, b"", json_data={"url": "http://h/empty.wav"})
    d, e = pet_voice._decode_json_audio(resp, "某后端")
    assert d is None and "空内容" in e, e

    monkeypatch.setattr(pet_voice, "requests", FakeRequests([FakeRequests.exceptions.Timeout()]))
    resp = FakeResp(200, b"", json_data={"file": "http://h/y.wav"})
    d, e = pet_voice._decode_json_audio(resp, "某后端")
    assert d is None and "下载音频失败" in e, e


# ================= 服务层：密钥来源 / 缓存扩展名 =================

class _KeyRecorder(pet_voice.VoiceBackend):
    """最小后端：只记录 synthesize 收到的 key（钉服务层的密钥来源）。"""

    id = "probe"
    needs_reference = False

    def __init__(self):
        self.keys = []

    def synthesize(self, reference_audio_path, text, params, key=""):
        self.keys.append(key)
        return b"RIFF" + b"\x00" * 64, ""


def test_service_key_source_and_cache_ext(monkeypatch, tmp_path):
    """服务层契约：旧链路回退 AI 设置里的 api_key；缓存扩展名按后端定。

    backend_keys 优先；sapi/openai 这两个"旧固定音色"后端在没填自己的 Key 时沿用
    AI 设置里的 api_key（v2.0 行为），别的后端不许借用那把 Key。
    """
    svc = pet_voice.VoiceService(str(tmp_path / "d"), lambda: {}, lambda p: None,
                                 log=lambda m: None)
    for bid in ("openai", "minimax", "elevenlabs"):
        assert svc._cache_path(bid, "v", "t", {}).endswith(".mp3"), \
            "%s 的缓存扩展名与真实容器不一致" % bid
    for bid in ("sapi", "gpt_sovits", "f5_tts", "cosyvoice"):
        assert svc._cache_path(bid, "v", "t", {}).endswith(".wav"), bid

    rec = _KeyRecorder()
    monkeypatch.setitem(pet_voice.BACKENDS, "sapi", rec)
    monkeypatch.setitem(pet_voice.BACKENDS, "openai", rec)
    cfg = {"api_key": "cfg-key", "voice": dict(pet_voice.DEFAULT_VOICE)}
    cfg["voice"]["backend"] = "sapi"
    svc2 = pet_voice.VoiceService(str(tmp_path / "d2"), lambda: cfg, lambda p: None,
                                  log=lambda m: None)
    monkeypatch.setattr(svc2, "_wait_playback", lambda *a: None)   # 不真等播放时长

    def _job(bid, text):
        return {"kind": "line", "text": text, "voice_slot": "", "role_slot": "",
                "line_id": "", "backend": bid, "gen": svc2._gen}

    svc2._process_job(_job("sapi", "甲"))
    assert rec.keys == ["cfg-key"], "sapi 没有回退 AI 设置里的 api_key：%r" % (rec.keys,)

    cfg["voice"]["backend_keys"] = {"sapi": "own-key"}
    svc2._process_job(_job("sapi", "乙"))
    assert rec.keys[-1] == "own-key", "backend_keys 没有优先于 cfg.api_key：%r" % (rec.keys,)

    # openai 同属旧固定音色链路：没填自己的 Key → 回退 AI 设置里的 api_key
    cfg["voice"]["backend_keys"] = {"sapi": "own-key"}
    svc2._process_job(_job("openai", "丙"))
    assert rec.keys[-1] == "cfg-key", "openai 没回退 AI 设置里的 api_key：%r" % (rec.keys,)

    cfg["voice"]["backend_keys"] = {"openai": "oa-key"}
    svc2._process_job(_job("openai", "丁"))
    assert rec.keys[-1] == "oa-key", "openai 自己的 Key 没有优先：%r" % (rec.keys,)

    # 克隆后端（不是旧链路）既不借别人的 Key、也不回退 cfg.api_key
    monkeypatch.setitem(pet_voice.BACKENDS, "minimax", rec)
    monkeypatch.setitem(pet_voice.BACKENDS, "elevenlabs", rec)
    cfg["api_key"] = "cfg-key-2"
    cfg["voice"]["backend_keys"] = {"openai": "oa-key", "elevenlabs": "el-key"}
    svc2._process_job(_job("minimax", "戊"))
    assert rec.keys[-1] == "", "克隆后端借用了别人的 Key：%r" % (rec.keys,)
    svc2._process_job(_job("elevenlabs", "己"))
    assert rec.keys[-1] == "el-key", rec.keys


def test_backend_registry_integrity():
    """注册表完整性：key == backend.id、info() 与类属性同口径、7 家一个不少。"""
    assert set(pet_voice.BACKENDS) == {"gpt_sovits", "f5_tts", "cosyvoice", "minimax",
                                       "elevenlabs", "openai", "sapi"}
    for bid, b in pet_voice.BACKENDS.items():
        assert b.id == bid, "注册键与后端 id 不一致：%r vs %r" % (bid, b.id)
        info = b.info()
        assert info["id"] == bid and info["label"], info
        assert info["needs_key"] == bool(b.needs_key)
        assert info["needs_service"] == bool(b.needs_service)
        assert info["needs_reference"] == bool(b.needs_reference)
        assert isinstance(info["default_params"], dict)
    assert pet_voice.DEFAULT_BACKEND in pet_voice.BACKENDS
    for bid in ("gpt_sovits", "f5_tts", "cosyvoice"):
        assert pet_voice.BACKENDS[bid].needs_service is True, bid
    for bid in ("minimax", "elevenlabs", "openai"):
        assert pet_voice.BACKENDS[bid].needs_key is True, bid
    assert pet_voice.BACKENDS["sapi"].needs_key is False
    assert pet_voice.BACKENDS["sapi"].needs_service is False

# ================= voice.json 读侧：扁平旧格式（v2.0 前）与坏 clips 同文件 =================

def test_voice_index_flat_format_still_read_after_corrupt_clips_heal(tmp_path):
    """旧扁平格式 + 类型非法的 clips：治愈后扁平绑定必须仍然被读到（不许静默丢）。

    L3 推演的行为收窄：_normalize_index 把坏 clips 重建成空对象之后，_load 里
    「src = raw if isinstance(raw, dict) else data」判定为真 → 退回扁平的分支再也走不到，
    同文件里的 reply/feed 等扁平键被静默丢掉（旧实现在 clips 非 dict 时会退回扁平）。
    修复口径：**clips 表为空时，先看顶层有没有可用的扁平绑定，有就退回扁平解析**
    （治愈回写的形状不变，仍由 test_persistence_consistency 钉住 {"clips": {}}）。
    """
    idx = tmp_path / "voice.json"
    idx.write_text(json.dumps({"version": 2, "clips": [1, 2],
                               "reply": "reply_flat.wav", "feed": "feed_flat.mp3"},
                              ensure_ascii=False), encoding="utf-8")
    logs = []
    svc = pet_voice.VoiceService(str(tmp_path), lambda: {}, lambda p: None, log=logs.append)
    assert svc._clips == {"reply": "reply_flat.wav", "feed": "feed_flat.mp3"}, \
        "扁平旧格式被治愈后的空 clips 挡掉了：%r" % (svc._clips,)
    assert any("clips" in m for m in logs), "坏 clips 没有留痕：%r" % (logs,)
    assert os.path.isfile(str(idx) + ".bak"), "治愈前没有留 .bak"
    healed = json.loads(idx.read_text(encoding="utf-8"))
    assert healed.get("reply") == "reply_flat.wav" and healed.get("feed") == "feed_flat.mp3", \
        "治愈回写把同文件的扁平键抹掉了：%r" % (healed,)
    again = pet_voice.VoiceService(str(tmp_path), lambda: {}, lambda p: None, log=lambda m: None)
    assert again._clips == svc._clips, "第二次读（盘上已是治愈后结构）结果不一致"


def test_voice_index_flat_and_canonical_priority(tmp_path):
    """对照组：clips 表非空时以它为准；纯扁平文件照旧能读；不可用的扁平值不算绑定。"""
    canon = tmp_path / "canon"
    canon.mkdir()
    (canon / "voice.json").write_text(json.dumps(
        {"version": 2, "clips": {"reply": "a.wav"}, "poke": "b.mp3"}), encoding="utf-8")
    svc = pet_voice.VoiceService(str(canon), lambda: {}, lambda p: None, log=lambda m: None)
    assert svc._clips == {"reply": "a.wav"}, \
        "clips 表非空时被顶层扁平键抢了：%r" % (svc._clips,)

    flat = tmp_path / "flat"
    flat.mkdir()
    (flat / "voice.json").write_text(json.dumps({"reply": "x.wav", "poke": "y.mp3"}),
                                     encoding="utf-8")
    svc2 = pet_voice.VoiceService(str(flat), lambda: {}, lambda p: None, log=lambda m: None)
    assert svc2._clips == {"reply": "x.wav", "poke": "y.mp3"}

    bad = tmp_path / "badval"
    bad.mkdir()
    (bad / "voice.json").write_text(json.dumps({"version": 2, "clips": {},
                                                "reply": "不是音频.ogg"}), encoding="utf-8")
    svc3 = pet_voice.VoiceService(str(bad), lambda: {}, lambda p: None, log=lambda m: None)
    assert svc3._clips == {}, "不可用的扁平值被当成了绑定：%r" % (svc3._clips,)


