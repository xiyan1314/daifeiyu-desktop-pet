# -*- coding: utf-8 -*-
"""v2.1 语言系统（AI 配音读台词）：可插拔声音克隆后端 + 角色声音绑定 + 播放队列。

三层职责（与资源库/台词模块解耦）
--------------------------------
1. 事件音效：用户导入的 reply/feed/poke/sleep/wake 片段（v2.0 能力，保留）。
2. 固定音色合成（旧）：sapi（Windows 离线）/ openai（OpenAI 兼容 /audio/speech），
   用于 AI 回复朗读；**不再作为配音读台词的最终方案**。
3. 声音克隆配音（v2.1 新）：参考音（声音素材）+ 台词 → 后端合成 → 播放。
   后端可插拔（VoiceBackend 子类）：GPT-SoVITS / F5-TTS / CosyVoice（本地服务）
   + MiniMax / ElevenLabs（云端克隆 API）。**不假装实现**：服务没起/没 Key/模型
   不支持时，明确报错并在界面提示，绝不退化成固定音色糊弄。

对外接口
--------
VoiceBackend.synthesize(reference_audio_path, text, params, key) -> (bytes|None, err)
backend_infos() / get_backend(id) / BACKENDS / DEFAULT_BACKEND / BACKEND_PARAM_LABELS
VoiceService(data_dir, cfg_getter, play_clip, log=None, stop_clip=None, save_cfg=None,
             lines=None, roles=None, voice_assets=None)
  事件片段：clip / set_clip / play_event
  绑定：bind_voice / unbind_voice / bindings / resolve_voice
  朗读：speak_line / speak_dialogue / speak_text / speak（旧：AI 回复朗读）
  控制：stop / regenerate / preview_asset / check_ready / test_backend
  通知（轻量回调，零 Qt）：on_speaking_started / on_speaking_finished /
        on_dialogue_finished / on_error
class VoiceBackend            # 统一接口：synthesize(reference_audio_path, text, params)
BACKENDS / backend_infos()    # 后端注册表（UI 用）
class VoiceService            # 事件片段 + 绑定 + 合成队列 + 播放控制
    speak_line(line_id) / speak_dialogue(dialogue_id) / speak_text(text, role_slot, voice_slot)
    stop() / regenerate(line_id) / preview_asset(voice_slot, text)
    bind_voice(role_slot, voice_slot) / unbind_voice(role_slot) / bindings()
    on_speaking_started / on_speaking_finished / on_dialogue_finished / on_error
"""
import copy
import hashlib
import json
import os
import subprocess
import threading
import time

import pet_log
import requests

# 事件名（片段注册表 voice.json 的键）
VOICE_EVENTS = ("reply", "feed", "poke", "sleep", "wake")

# 旧的固定音色 API 错误 → 中文原因（界面直接提示，不隐藏问题）
TTS_API_ERRORS = {
    401: "密钥无效",
    402: "额度不足",
    403: "地区限制或服务不可用",
    404: "当前接口不支持语音合成（服务商无 /audio/speech）",
    429: "请求太频繁，稍后再试",
}


def explain_tts_error(status_code):
    """API 状态码 → 中文原因（纯函数，可测）。未知码返回通用原因。"""
    return TTS_API_ERRORS.get(status_code, "服务不可用（HTTP %d）" % status_code)


def explain_backend_error(status_code):
    """克隆后端 HTTP 状态码 → 中文原因（纯函数，可测）。"""
    if status_code == 400:
        return "后端拒绝了请求（参数/参考音格式不对，或参考音里没检测到人声）"
    if status_code == 401:
        return "后端鉴权失败（API Key 无效）"
    if status_code == 402:
        return "后端余额/额度不足"
    if status_code == 403:
        return "后端拒绝访问（地区限制、权限不足或 Key 无该模型权限）"
    if status_code == 404:
        return "后端没有这个接口（服务版本不匹配，或地址填错了）"
    if status_code == 413:
        return "参考音太大，后端拒绝接收"
    if status_code == 422:
        return "后端参数校验失败（检查参考音与参数）"
    if status_code == 429:
        return "请求太频繁，稍后再试"
    if status_code >= 500:
        return "后端服务出错（HTTP %d），稍后再试" % status_code
    return "后端返回异常（HTTP %d）" % status_code


# ---------------- v2.1：可插拔声音克隆后端 ----------------
class VoiceBackend:
    """后端统一接口：参考音 + 文本 → 音频字节。

    子类实现 synthesize()；返回 (audio_bytes|None, err)。绝不抛异常。
    needs_reference=True 的后端必须要参考音（声音素材）；False 的是固定音色。
    """

    id = "base"
    label = "抽象后端"
    needs_reference = True
    needs_key = False
    needs_service = False       # 需要用户自己启动的服务（本地后端）
    default_params = {}         # 该后端的默认参数（UI 展示/归一化用）
    help_text = ""

    def info(self):
        return {"id": self.id, "label": self.label,
                "needs_reference": bool(self.needs_reference),
                "needs_key": bool(self.needs_key),
                "needs_service": bool(self.needs_service),
                "default_params": dict(self.default_params),
                "help_text": self.help_text}

    def synthesize(self, reference_audio_path, text, params, key=""):
        raise NotImplementedError

    # ---- 子类共用的 HTTP 帮手 ----
    @staticmethod
    def _clean_base(params):
        return str((params or {}).get("base_url") or "").strip().rstrip("/")

    def _post(self, url, *, json_body=None, data=None, files=None, headers=None, timeout=60):
        """POST 并返回 (resp|None, err)。网络异常归类成中文。"""
        try:
            resp = requests.post(url, json=json_body, data=data, files=files,
                                 headers=headers or {}, timeout=timeout)
        except requests.exceptions.Timeout:
            return None, "连接后端超时（服务没启动或响应太慢）"
        except requests.exceptions.ConnectionError:
            return None, "连不上后端服务（检查地址、服务是否已启动）"
        except Exception as e:
            return None, "请求后端失败：%s" % e
        return resp, ""

    def _get(self, url, *, params=None, headers=None, timeout=60):
        try:
            resp = requests.get(url, params=params, headers=headers or {}, timeout=timeout)
        except requests.exceptions.Timeout:
            return None, "连接后端超时（服务没启动或响应太慢）"
        except requests.exceptions.ConnectionError:
            return None, "连不上后端服务（检查地址、服务是否已启动）"
        except Exception as e:
            return None, "请求后端失败：%s" % e
        return resp, ""


class GptSoVitsBackend(VoiceBackend):
    """GPT-SoVITS 本地 api 服务（推荐：中文效果最接近剪映，免费离线）。

    参考音走**本机路径**（服务与桌宠跑在同一台机器）：api_v2 用 GET /tts，
    api_v1 用 POST /tts（json）。prompt_text 是参考音对应的文本，填了效果更好。
    """

    id = "gpt_sovits"
    label = "GPT-SoVITS（本地服务，推荐）"
    needs_reference = True
    needs_service = True
    default_params = {"base_url": "http://127.0.0.1:9880", "api": "v2",
                      "prompt_text": "", "text_lang": "zh", "prompt_lang": "zh",
                      "split_method": "cut5"}
    help_text = ("先自行安装并启动 GPT-SoVITS 的 api 服务（默认 127.0.0.1:9880）；"
                 "参考音建议 3~10 秒干净人声（wav 最佳）")

    def synthesize(self, reference_audio_path, text, params, key=""):
        params = params or {}
        base = self._clean_base(params)
        if not base:
            return None, "没填 GPT-SoVITS 服务地址（默认 http://127.0.0.1:9880）"
        if not reference_audio_path or not os.path.isfile(reference_audio_path):
            return None, "参考音文件不存在（声音素材被删了？去资源管理重新导入）"
        api = str(params.get("api") or "v2").lower()
        prompt_text = str(params.get("prompt_text") or "")
        tlang = str(params.get("text_lang") or "zh")
        plang = str(params.get("prompt_lang") or "zh")
        if api == "v1":
            body = {"refer_wav_path": reference_audio_path, "prompt_text": prompt_text,
                    "prompt_language": plang, "text": text, "text_language": tlang}
            resp, err = self._post(base + "/tts", json_body=body)
        else:
            q = {"text": text, "text_lang": tlang,
                 "ref_audio_path": reference_audio_path, "prompt_text": prompt_text,
                 "prompt_lang": plang,
                 "text_split_method": str(params.get("split_method") or "cut5"),
                 "media_type": "wav", "streaming_mode": "false"}
            resp, err = self._get(base + "/tts", params=q)
        if resp is None:
            return None, err
        if resp.status_code != 200:
            return None, "GPT-SoVITS：%s" % explain_backend_error(resp.status_code)
        if not resp.content:
            return None, "GPT-SoVITS 返回空音频（检查参考音与 prompt_text）"
        return resp.content, ""


class F5TtsBackend(VoiceBackend):
    """F5-TTS 本地服务（零样本克隆，英文/中文均可）。

    约定接口：POST {base_url}/tts，multipart 字段 ref_audio(文件)/ref_text/gen_text，
    返回音频字节；若返回 JSON 则取其中的 audio(base64)/url/path 字段。
    """

    id = "f5_tts"
    label = "F5-TTS（本地服务）"
    needs_reference = True
    needs_service = True
    default_params = {"base_url": "http://127.0.0.1:7860", "ref_text": ""}
    help_text = "先启动 F5-TTS 的 HTTP 服务；服务接口需支持 /tts（见说明文档）"

    def synthesize(self, reference_audio_path, text, params, key=""):
        params = params or {}
        base = self._clean_base(params)
        if not base:
            return None, "没填 F5-TTS 服务地址（默认 http://127.0.0.1:7860）"
        if not reference_audio_path or not os.path.isfile(reference_audio_path):
            return None, "参考音文件不存在（声音素材被删了？去资源管理重新导入）"
        try:
            with open(reference_audio_path, "rb") as f:
                files = {"ref_audio": (os.path.basename(reference_audio_path), f, "audio/wav")}
                data = {"ref_text": str(params.get("ref_text") or ""), "gen_text": text}
                resp, err = self._post(base + "/tts", data=data, files=files)
        except Exception as e:
            return None, "读取参考音失败：%s" % e
        if resp is None:
            return None, err
        if resp.status_code != 200:
            return None, "F5-TTS：%s" % explain_backend_error(resp.status_code)
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "json" in ctype:
            return _decode_json_audio(resp, "F5-TTS")
        if not resp.content:
            return None, "F5-TTS 返回空音频"
        return resp.content, ""


class CosyVoiceBackend(VoiceBackend):
    """CosyVoice（通义，零样本克隆）本地服务。

    约定接口：POST {base_url}/inference_zero_shot，multipart 字段
    tts_text/prompt_text/prompt_wav(文件)，返回 wav 字节。
    """

    id = "cosyvoice"
    label = "CosyVoice（本地服务）"
    needs_reference = True
    needs_service = True
    default_params = {"base_url": "http://127.0.0.1:50000", "prompt_text": ""}
    help_text = "先启动 CosyVoice 的 HTTP 服务；服务接口需支持 /inference_zero_shot"

    def synthesize(self, reference_audio_path, text, params, key=""):
        params = params or {}
        base = self._clean_base(params)
        if not base:
            return None, "没填 CosyVoice 服务地址（默认 http://127.0.0.1:50000）"
        if not reference_audio_path or not os.path.isfile(reference_audio_path):
            return None, "参考音文件不存在（声音素材被删了？去资源管理重新导入）"
        try:
            with open(reference_audio_path, "rb") as f:
                files = {"prompt_wav": (os.path.basename(reference_audio_path), f, "audio/wav")}
                data = {"tts_text": text, "prompt_text": str(params.get("prompt_text") or "")}
                resp, err = self._post(base + "/inference_zero_shot", data=data, files=files)
        except Exception as e:
            return None, "读取参考音失败：%s" % e
        if resp is None:
            return None, err
        if resp.status_code != 200:
            return None, "CosyVoice：%s" % explain_backend_error(resp.status_code)
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "json" in ctype:
            return _decode_json_audio(resp, "CosyVoice")
        if not resp.content:
            return None, "CosyVoice 返回空音频"
        return resp.content, ""


class MiniMaxBackend(VoiceBackend):
    """MiniMax 语音克隆（云端）：首次用参考音克隆出 voice_id，之后复用。

    流程：/v1/files/upload(purpose=voice_clone) → /v1/voice_clone → /v1/t2a_v2。
    克隆出的 voice_id 缓存在 params["cloned"][voice_slot_key]，避免每次克隆。
    """

    id = "minimax"
    label = "MiniMax 语音克隆（云端，需 Key）"
    needs_reference = True
    needs_key = True
    default_params = {"base_url": "https://api.minimax.chat", "model": "speech-02-hd",
                      "cloned": {}}
    help_text = ("需要 MiniMax API Key（填在下方密钥框）；参考音会**上传到 MiniMax 云端**"
                 "用于克隆，介意请改用本地后端")

    def synthesize(self, reference_audio_path, text, params, key=""):
        params = params or {}
        base = self._clean_base(params) or "https://api.minimax.chat"
        if not key:
            return None, "没填 MiniMax API Key（云端克隆必须）"
        if not reference_audio_path or not os.path.isfile(reference_audio_path):
            return None, "参考音文件不存在（声音素材被删了？去资源管理重新导入）"
        headers = {"Authorization": "Bearer " + key}
        slot = str(params.get("_slot") or reference_audio_path)
        cloned = params.setdefault("cloned", {})
        voice_id = str(cloned.get(slot) or "")
        if voice_id:
            return self._minimax_speak(base, headers, voice_id, text, params)  # 复用已克隆的声线
        try:
            with open(reference_audio_path, "rb") as f:
                files = {"file": (os.path.basename(reference_audio_path), f, "audio/wav")}
                resp, err = self._post(base + "/v1/files/upload",
                                       data={"purpose": "voice_clone"},
                                       files=files, headers=headers)
        except Exception as e:
            return None, "读取参考音失败：%s" % e
        if resp is None:
            return None, err
        if resp.status_code != 200:
            return None, "MiniMax 上传参考音失败：%s" % explain_backend_error(resp.status_code)
        try:
            file_id = ((resp.json() or {}).get("file") or {}).get("file_id")
        except Exception:
            file_id = None
        if not file_id:
            return None, "MiniMax 没有返回 file_id（接口返回格式变了？）"
        resp2, err2 = self._post(base + "/v1/voice_clone",
                                 json_body={"file_id": file_id}, headers=headers)
        if resp2 is None:
            return None, err2
        if resp2.status_code != 200:
            return None, "MiniMax 克隆失败：%s" % explain_backend_error(resp2.status_code)
        try:
            _j2 = resp2.json() or {}
            voice_id = _j2.get("voice_id")
            if not voice_id:
                _br = _j2.get("base_resp") or {}
                if _br:
                    return None, "MiniMax 克隆失败：%s（code=%s）" % (
                        _br.get("status_msg") or "未知原因", _br.get("status_code"))
        except Exception as e:
            return None, "MiniMax 克隆返回无法解析：%s" % e
        if not voice_id:
            return None, "MiniMax 没有返回 voice_id（克隆未成功）"
        cloned[slot] = str(voice_id)  # M8：记住克隆结果，之后同素材不再重复克隆
        return self._minimax_speak(base, headers, str(voice_id), text, params)

    def _minimax_speak(self, base, headers, voice_id, text, params):
        """用已克隆的 voice_id 合成（克隆只在首次上传/创建）。"""
        body = {"model": str(params.get("model") or "speech-02-hd"), "text": text,
                "voice_setting": {"voice_id": voice_id, "speed": 1.0, "vol": 1.0, "pitch": 0},
                "audio_setting": {"format": "mp3", "sample_rate": 32000}}
        resp3, err3 = self._post(base + "/v1/t2a_v2", json_body=body, headers=headers)
        if resp3 is None:
            return None, err3
        if resp3.status_code != 200:
            return None, "MiniMax 合成失败：%s" % explain_backend_error(resp3.status_code)
        try:
            data = resp3.json() or {}
            _br = data.get("base_resp") or {}
            hex_audio = ((data.get("data") or {}).get("audio")) or ""
            if hex_audio:
                return bytes.fromhex(hex_audio), ""
            if _br:
                return None, "MiniMax 合成失败：%s（code=%s）" % (
                    _br.get("status_msg") or "未知原因", _br.get("status_code"))
        except Exception as e:
            return None, "MiniMax 返回内容无法解析：%s" % e
        return None, "MiniMax 没有返回音频数据"


class ElevenLabsBackend(VoiceBackend):
    """ElevenLabs 声音克隆（云端）：Instant Voice Cloning 后合成。

    流程：/v1/voices/add（multipart，files 传参考音）→ voice_id → /v1/text-to-speech/{id}。
    """

    id = "elevenlabs"
    label = "ElevenLabs 声音克隆（云端，需 Key）"
    needs_reference = True
    needs_key = True
    default_params = {"base_url": "https://api.elevenlabs.io", "model": "eleven_multilingual_v2"}
    help_text = ("需要 ElevenLabs API Key；参考音会**上传到 ElevenLabs 云端**用于克隆，"
                 "介意请改用本地后端")

    def synthesize(self, reference_audio_path, text, params, key=""):
        params = params or {}
        base = self._clean_base(params) or "https://api.elevenlabs.io"
        if not key:
            return None, "没填 ElevenLabs API Key（云端克隆必须）"
        if not reference_audio_path or not os.path.isfile(reference_audio_path):
            return None, "参考音文件不存在（声音素材被删了？去资源管理重新导入）"
        headers = {"xi-api-key": key}
        slot = str(params.get("_slot") or reference_audio_path)
        cloned = params.setdefault("cloned", {})
        _cached = str(cloned.get(slot) or "")
        if _cached:
            return self._elevenlabs_speak(base, headers, _cached, text, params)  # 复用克隆声线
        try:
            with open(reference_audio_path, "rb") as f:
                files = {"files": (os.path.basename(reference_audio_path), f, "audio/wav")}
                data = {"name": "daifeiyu_%s" % time.strftime("%Y%m%d%H%M%S")}
                resp, err = self._post(base + "/v1/voices/add", data=data, files=files,
                                       headers=headers)
        except Exception as e:
            return None, "读取参考音失败：%s" % e
        if resp is None:
            return None, err
        if resp.status_code != 200:
            return None, "ElevenLabs 克隆失败：%s" % explain_backend_error(resp.status_code)
        try:
            voice_id = (resp.json() or {}).get("voice_id")
        except Exception:
            voice_id = None
        if not voice_id:
            return None, "ElevenLabs 没有返回 voice_id（克隆未成功）"
        cloned[slot] = str(voice_id)  # M8：记住克隆结果，之后同素材不再重复克隆
        return self._elevenlabs_speak(base, headers, str(voice_id), text, params)

    def _elevenlabs_speak(self, base, headers, voice_id, text, params):
        """用已克隆的 voice_id 合成（克隆只在首次上传/创建）。"""
        resp2, err2 = self._post(
            base + "/v1/text-to-speech/" + voice_id,
            json_body={"text": text,
                       "model_id": str(params.get("model") or "eleven_multilingual_v2")},
            headers=headers)
        if resp2 is None:
            return None, err2
        if resp2.status_code != 200:
            return None, "ElevenLabs 合成失败：%s" % explain_backend_error(resp2.status_code)
        if not resp2.content:
            return None, "ElevenLabs 返回空音频"
        return resp2.content, ""


class OpenAISpeechBackend(VoiceBackend):
    """旧的 OpenAI 兼容固定音色（/audio/speech）——保留给 AI 回复朗读，不做克隆。"""

    id = "openai"
    label = "OpenAI 兼容固定音色（旧，不克隆）"
    needs_reference = False
    needs_key = True
    default_params = {"model": "tts-1", "voice": "alloy"}
    help_text = "用 AI设置 里的接口地址与 Key；固定音色，不支持声音克隆"

    def synthesize(self, reference_audio_path, text, params, key=""):
        params = params or {}
        cfg_base = self._clean_base(params)
        if not cfg_base:
            return None, "没填 OpenAI 兼容接口地址（默认用 AI设置 里的地址）"
        body = {"model": str(params.get("model") or "tts-1"), "input": text,
                "voice": str(params.get("voice") or "alloy")}
        resp, err = self._post(cfg_base + "/audio/speech", json_body=body,
                               headers={"Authorization": "Bearer " + (key or "")})
        if resp is None:
            return None, err
        if resp.status_code != 200:
            return None, "语音合成受限：%s" % explain_tts_error(resp.status_code)
        if not resp.content:
            return None, "语音合成返回空内容（服务商异常）"
        return resp.content, ""


class SapiBackend(VoiceBackend):
    """Windows 系统语音（离线、固定音色）——保留给 AI 回复朗读。"""

    id = "sapi"
    label = "Windows 系统语音（离线，固定音色）"
    needs_reference = False
    default_params = {"voice": ""}
    help_text = "用系统自带语音包，离线可用；固定音色，不支持克隆"

    def synthesize(self, reference_audio_path, text, params, key=""):
        import tempfile
        voice = str((params or {}).get("voice") or "")
        tmp = os.path.join(tempfile.gettempdir(), "dfy_tts_%s.wav" % hashlib.md5(
            ("%s|%s" % (text, voice)).encode("utf-8")).hexdigest()[:12])
        ps = ("Add-Type -AssemblyName System.Speech; "
              "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; ")
        if voice:
            ps += "try { $s.SelectVoice('%s') } catch {}; " % voice.replace("'", "''")
        ps += "$s.SetOutputToWaveFile('%s'); $s.Speak('%s'); $s.Dispose();" % (
            tmp.replace("'", "''"), text.replace("'", "''"))
        try:
            proc = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                                   "-Command", ps], capture_output=True, timeout=60)
        except FileNotFoundError:
            return None, "系统没有 PowerShell，本地语音不可用"
        except subprocess.TimeoutExpired:
            return None, "本地语音合成超时"
        if proc.returncode != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) <= 44:
            err = (proc.stderr or b"").decode("utf-8", "replace").strip()
            return None, "本地语音不可用（%s）" % (err[:80] or "系统没有可用语音包")
        try:
            with open(tmp, "rb") as f:
                data = f.read()
        except Exception as e:
            return None, "读取合成结果失败：%s" % e
        finally:
            try:
                if os.path.isfile(tmp):
                    os.remove(tmp)  # L6 修复：临时 wav 用完即删，不在 %TEMP% 堆积
            except Exception:
                pass  # 有意忽略：临时文件清理尽力而为
        return data, ""


AUDIO_MAGICS = (b"RIFF", b"ID3", b"OggS", b"fLaC", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")


def _looks_like_audio(data):
    """音频字节粗校验（容器魔数）：防把非音频内容写进缓存后无声播放。"""
    if not data or len(data) < 4:
        return False
    head = bytes(data[:4])
    if head in (b"RIFF", b"OggS", b"fLaC") or head[:3] == b"ID3":
        return True
    return head[0] == 0xFF and (head[1] & 0xE0) == 0xE0  # MPEG 帧同步（mp3/aac）


def _audio_duration(path):
    """音频时长（秒）：wav 读头精确；其它（mp3 等）按 128kbps 估算并夹在 0.6~20s。

    仅用于"等这条播完再播下一条"的节奏控制，不追求帧级精确。"""
    try:
        if str(path).lower().endswith(".wav"):
            import wave
            with wave.open(str(path), "rb") as w:
                rate = w.getframerate() or 8000
                return max(0.2, min(60.0, w.getnframes() / float(rate)))
        size = os.path.getsize(path)
        return max(0.6, min(20.0, size / 16000.0))  # 128kbps ≈ 16KB/s
    except Exception:
        return 1.2  # 有意忽略：读不出时长时给一个保守估计，避免队列卡死


def _decode_json_audio(resp, who):
    """部分本地服务返回 JSON（audio 为 base64 / url / path），统一取出音频字节。"""
    import base64
    try:
        data = resp.json() or {}
    except Exception as e:
        return None, "%s 返回内容无法解析：%s" % (who, e)
    audio = data.get("audio") if isinstance(data, dict) else None
    if isinstance(audio, str) and audio:
        if audio.startswith("http"):
            try:
                r = requests.get(audio, timeout=60)
                if r.status_code == 200 and r.content:
                    return r.content, ""
                return None, "%s 下载音频失败（HTTP %d）" % (who, r.status_code)
            except Exception as e:
                return None, "%s 下载音频失败：%s" % (who, e)
        try:
            raw = base64.b64decode(audio, validate=True)  # 严格 base64：坏字符直接报错
        except Exception:
            raw = None
        if raw is not None:
            if _looks_like_audio(raw):
                return raw, ""
            # M13 修复：服务把普通文本塞进 audio 时，别把垃圾字节当音频缓存并无声播放
            return None, "%s 返回的 audio 不是音频数据（已拒绝）" % who
    for k in ("url", "path", "file"):
        v = (data or {}).get(k)
        if isinstance(v, str) and v:
            if v.startswith("http"):
                try:
                    r = requests.get(v, timeout=60)
                    if r.status_code == 200 and r.content:
                        return r.content, ""
                except Exception as e:
                    return None, "%s 下载音频失败：%s" % (who, e)
            elif os.path.isfile(v):
                try:
                    with open(v, "rb") as f:
                        return f.read(), ""
                except Exception as e:
                    return None, "%s 读取音频失败：%s" % (who, e)
    return None, "%s 返回里没有音频数据" % who


# 后端注册表（单一来源：UI 下拉与合成分发共用）
BACKENDS = {b.id: b for b in (
    GptSoVitsBackend(), F5TtsBackend(), CosyVoiceBackend(),
    MiniMaxBackend(), ElevenLabsBackend(), OpenAISpeechBackend(), SapiBackend(),
)}
DEFAULT_BACKEND = "gpt_sovits"


def backend_infos():
    """UI 用后端清单（按注册顺序）。"""
    return [b.info() for b in BACKENDS.values()]


def get_backend(backend_id):
    return BACKENDS.get(str(backend_id or "")) or BACKENDS[DEFAULT_BACKEND]


# ---------------- v2.1.1：本地后端启动器 ----------------
class VoiceLauncher:
    """本地配音后端（GPT-SoVITS / F5-TTS / CosyVoice）进程启动器。

    只负责「把用户填的命令跑起来」和「结束我们自己拉起的那个进程」，绝不碰用户手动启动的服务；
    状态记录在 data/voice_backend.json，日志重定向到 data/voice_backend.log。
    """

    def __init__(self, data_dir, log=None):
        self._state_path = os.path.join(data_dir, "voice_backend.json")
        self._log_path = os.path.join(data_dir, "voice_backend.log")
        self._log = log or pet_log.log_error
        self._state = self._load_state()

    def _load_state(self):
        try:
            with open(self._state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}  # 有意忽略：首次运行/损坏 → 视为没启动过

    def _save_state(self):
        try:
            tmp = self._state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._state, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._state_path)
        except Exception as e:
            self._log("voice backend state save failed: %r" % (e,))  # 有意忽略：丢状态不影响运行

    def _clear_state(self):
        self._state = {}
        try:
            if os.path.isfile(self._state_path):
                os.remove(self._state_path)
        except Exception:
            pass  # 有意忽略：清状态尽力而为

    def pid(self):
        try:
            return int(self._state.get("pid") or 0)
        except (TypeError, ValueError):
            return 0

    def is_running(self):
        """我们启动的后端进程是否还活着。"""
        pid = self.pid()
        if not pid:
            return False
        try:
            import psutil
            return bool(psutil.pid_exists(pid))
        except Exception:
            try:
                os.kill(pid, 0)
                return True
            except Exception:
                return False

    def status(self):
        return {"running": self.is_running(), "pid": self.pid(),
                "cmd": str(self._state.get("cmd") or ""),
                "backend": str(self._state.get("backend") or ""),
                "started_at": str(self._state.get("started_at") or ""),
                "log": self._log_path}

    def start(self, cmd, cwd="", backend_id=""):
        """按用户填的命令启动后端。返回 (ok, msg)。"""
        cmd = str(cmd or "").strip()
        if not cmd:
            return False, "还没填启动命令（语音设置 → 本地后端服务 → 启动命令）"
        if self.is_running():
            return True, "后端已经在跑了（PID %d）" % self.pid()
        try:
            _dir = os.path.dirname(self._log_path)
            if _dir:
                os.makedirs(_dir, exist_ok=True)
            f = open(self._log_path, "a", encoding="utf-8", errors="replace")
            f.write("\n===== %s 启动：%s（%s）=====\n"
                    % (time.strftime("%Y-%m-%d %H:%M:%S"), cmd, backend_id or "-"))
            f.flush()
            kwargs = {"cwd": (str(cwd).strip() or None), "stdout": f,
                      "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL,
                      "shell": True}
            if os.name == "nt":
                kwargs["creationflags"] = 0x00000200  # CREATE_NEW_PROCESS_GROUP
            proc = subprocess.Popen(cmd, **kwargs)
        except Exception as e:
            return False, "启动失败：%s" % e
        self._state = {"pid": int(proc.pid), "cmd": cmd, "backend": str(backend_id or ""),
                       "started_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        self._save_state()
        return True, "已启动（PID %d），正在等它就绪…" % proc.pid

    def stop(self):
        """结束我们启动的后端（含子进程树）；没启动过视为已完成。"""
        pid = self.pid()
        if not pid:
            return True, "没有需要结束的后端（桌宠没启动过后端）"
        try:
            import psutil
            try:
                proc = psutil.Process(pid)
            except Exception:
                self._clear_state()
                return True, "后端进程已经不在了"
            try:
                kids = proc.children(recursive=True)
            except Exception:
                kids = []  # 有意忽略：取不到子进程就直接结束父进程
            for p in kids + [proc]:
                try:
                    p.terminate()
                except Exception:
                    pass  # 有意忽略：单个失败继续处理其它
            _gone, alive = psutil.wait_procs(kids + [proc], timeout=5)
            for p in alive:
                try:
                    p.kill()
                except Exception:
                    pass  # 有意忽略：强杀失败只能交给用户手动关
            self._clear_state()
            return True, "已结束后端（PID %d）" % pid
        except Exception as e:
            try:
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                               capture_output=True, timeout=15)
                self._clear_state()
                return True, "已结束后端（PID %d）" % pid
            except Exception as e2:
                return False, "结束后端失败：%s / %s" % (e, e2)

    def wait_ready(self, base_url, timeout=30):
        """轮询探测后端是否就绪（能连上就算就绪）。返回 (ok, msg)。"""
        base = str(base_url or "").strip().rstrip("/")
        if not base:
            return False, "没填服务地址，无法判断后端是否就绪"
        t0 = time.time()
        last = ""
        while time.time() - t0 < max(3, int(timeout or 30)):
            if not self.is_running():
                return False, "后端进程已退出（看日志：%s）" % self._log_path
            try:
                r = requests.get(base, timeout=2)
                return True, "后端已就绪（HTTP %d）：%s" % (r.status_code, base)
            except requests.exceptions.ConnectionError:
                last = "还连不上：%s" % base
            except requests.exceptions.Timeout:
                last = "探测超时：%s" % base
            except Exception as e:
                last = "探测失败：%s" % e
            time.sleep(1.0)
        return False, "%s（等了 %d 秒；启动命令或地址可能不对，看日志 %s）" % (
            last or "后端没起来", max(3, int(timeout or 30)), self._log_path)


# ---------------- v2.1：语言系统服务 ----------------
class VoiceService:
    """语言系统：事件片段 + 角色声音绑定 + 克隆合成队列 + 播放控制。主线程调用。

    依赖注入（单向：本模块可 import pet_lines/pet_resources，反过来不行）：
      lines=LineService / roles=RoleLibrary / voice_assets=VoiceAssetLibrary
      play_clip(path) / stop_clip() / save_cfg(cfg)
    没注入的能力**明确报错**（例如没接台词库时说"读台词不可用"），不静默、不假装。
    """

    def __init__(self, data_dir, cfg_getter, play_clip, log=None, stop_clip=None,
                 save_cfg=None, lines=None, roles=None, voice_assets=None):
        self._dir = os.path.join(data_dir, "voice")
        self._index = os.path.join(data_dir, "voice.json")
        self._cache_dir = os.path.join(self._dir, "tts_cache")
        self._cfg = cfg_getter
        self._play_clip = play_clip
        self._stop_clip = stop_clip
        self._save_cfg = save_cfg
        self._lines = lines
        self._roles = roles
        self._assets = voice_assets
        self._log = log or pet_log.log_error
        self._clips = {}
        self._queue = []
        self._lock = threading.Lock()
        self._gen = 0
        self._speaking = False
        self._cbs = {"started": [], "finished": [], "dialogue": [], "error": []}
        self.launcher = VoiceLauncher(data_dir, self._log)  # v2.1.1：本地后端启动器
        self._load()

    # ---------------- 持久化（事件片段） ----------------
    def _load(self):
        try:
            with open(self._index, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = None  # 有意忽略：首次使用/损坏 → 空表（首次运行常态）
        clips = {}
        if isinstance(data, dict):
            src = data.get("clips") if isinstance(data.get("clips"), dict) else data
            for k, v in src.items():
                if k in VOICE_EVENTS and isinstance(v, str) and v.lower().endswith((".wav", ".mp3")):
                    clips[k] = v
        self._clips = clips

    def _save(self):
        try:
            os.makedirs(self._dir, exist_ok=True)
            tmp = self._index + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"version": 2, "clips": self._clips}, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._index)
        except Exception as e:
            self._log("voice index save failed: %r" % (e,))

    # ---------------- 变更/播放通知（轻量回调，零 Qt） ----------------
    def on_speaking_started(self, cb):
        if cb not in self._cbs["started"]:
            self._cbs["started"].append(cb)

    def on_speaking_finished(self, cb):
        if cb not in self._cbs["finished"]:
            self._cbs["finished"].append(cb)

    def on_dialogue_finished(self, cb):
        if cb not in self._cbs["dialogue"]:
            self._cbs["dialogue"].append(cb)

    def on_error(self, cb):
        if cb not in self._cbs["error"]:
            self._cbs["error"].append(cb)

    def _emit(self, key, *args):
        for cb in list(self._cbs.get(key) or []):
            try:
                cb(*args)
            except Exception as e:
                self._log("voice cb %s failed: %r" % (key, e))  # 有意忽略：单监听者失败不影响其余

    # ---------------- 事件片段（v2.0 能力，保留） ----------------
    def clip(self, event):
        """事件片段的绝对路径；未配置返回 None。"""
        fname = self._clips.get(event)
        if not fname:
            return None
        p = os.path.join(self._dir, fname)
        return p if os.path.isfile(p) else None

    def set_clip(self, event, src_path=None):
        """导入/清除事件片段（复制进 voice/）。返回 (ok, err)。"""
        if event not in VOICE_EVENTS:
            return False, "未知事件"
        try:
            os.makedirs(self._dir, exist_ok=True)
        except Exception as e:
            return False, "语音目录创建失败：%s" % e
        if src_path is None:
            old = self._clips.pop(event, None)
            self._save()
            if old:
                try:
                    p = os.path.join(self._dir, old)
                    if os.path.isfile(p):
                        os.remove(p)
                except Exception:
                    pass  # 有意忽略：旧片段清理尽力而为
            return True, ""
        try:
            if not os.path.isfile(src_path):
                return False, "音频文件不存在"
            ext = os.path.splitext(src_path)[1].lower()
            if ext not in (".wav", ".mp3"):
                return False, "仅支持 wav/mp3"
            if os.path.getsize(src_path) > 20 * 1024 * 1024:
                return False, "文件超过 20MB，无法导入"
            fname = "%s_%s%s" % (event, hashlib.md5(src_path.encode("utf-8")).hexdigest()[:8], ext)
            dest = os.path.join(self._dir, fname)
            with open(src_path, "rb") as fin, open(dest, "wb") as fout:
                fout.write(fin.read())
            old = self._clips.get(event)
            self._clips[event] = fname
            self._save()
            if old and old != fname:
                try:
                    p = os.path.join(self._dir, old)
                    if os.path.isfile(p):
                        os.remove(p)
                except Exception:
                    pass  # 有意忽略：旧片段清理尽力而为
            return True, ""
        except Exception as e:
            return False, "导入失败：%s" % e

    def play_event(self, event):
        """事件触发：仅播放事件片段（不合成朗读）；语音关闭则静默。"""
        cfg = self._cfg() or {}
        vcfg = cfg.get("voice") or {}
        if not vcfg.get("enabled"):
            return
        p = self.clip(event)
        if p is not None:
            try:
                self._play_clip(p)
            except Exception as e:
                self._log("voice clip play failed: %r" % (e,))

    # ---------------- v2.1.1：本地后端启动 / 结束 ----------------
    def local_service_cfg(self, backend_id=None):
        """某本地后端的启动配置（cmd/cwd/auto_start/kill_on_exit/wait_seconds）。"""
        bid = backend_id or self.backend_id()
        cfg = self._cfg() or {}
        services = (cfg.get("voice") or {}).get("local_services")
        if not isinstance(services, dict):
            return {}
        one = services.get(bid)
        return dict(one) if isinstance(one, dict) else {}

    def is_local_backend(self, backend_id=None):
        return bool(get_backend(backend_id or self.backend_id()).needs_service)

    def launch_status(self):
        """启动器状态（含我们启动的进程是否还活着）。"""
        return self.launcher.status()

    def start_backend(self, backend_id=None):
        """手动/自动启动本地后端（只拉起进程，不等就绪）。返回 (ok, msg)。"""
        bid = backend_id or self.backend_id()
        backend = get_backend(bid)
        if not backend.needs_service:
            return False, "「%s」是云端/离线后端，不需要启动本地服务" % backend.label
        one = self.local_service_cfg(bid)
        return self.launcher.start(one.get("cmd") or "", one.get("cwd") or "", bid)

    def start_backend_if_configured(self):
        """启动时自动拉起：仅当语音开启 + 当前后端是本地服务 + 勾了"自动启动"。

        返回 (started, msg)：started=False 且 msg 为空 = 配置没让自动启动（静默跳过）。
        """
        cfg = self._cfg() or {}
        vcfg = cfg.get("voice") or {}
        if not vcfg.get("enabled"):
            return False, ""
        bid = self.backend_id()
        if not get_backend(bid).needs_service:
            return False, ""
        one = self.local_service_cfg(bid)
        if not one.get("auto_start"):
            return False, ""
        if self.launcher.is_running():
            return False, ""  # 已经在跑：不重复启动、也不打扰用户
        ok, msg = self.start_backend(bid)
        return (True, msg) if ok else (True, msg or "自动启动失败")

    def wait_backend_ready(self, backend_id=None, timeout=None):
        """等本地后端就绪（阻塞；调用方应放到工作线程）。返回 (ok, msg)。"""
        bid = backend_id or self.backend_id()
        one = self.local_service_cfg(bid)
        _t = timeout if timeout is not None else int(one.get("wait_seconds") or 30)
        base = self._params_for(bid).get("base_url") or ""
        return self.launcher.wait_ready(base, _t)

    def stop_backend(self):
        return self.launcher.stop()

    def stop_backend_if_ours(self):
        """退出时清理：只结束我们启动的、且该后端勾了"退出时结束"。"""
        bid = str(self.launcher.status().get("backend") or "") or self.backend_id()
        one = self.local_service_cfg(bid)
        if not one.get("kill_on_exit"):
            return False, ""
        if not self.launcher.is_running():
            return False, ""
        ok, msg = self.launcher.stop()
        return True, msg if ok else ("结束失败：" + msg)

    # ---------------- 角色 ↔ 声音绑定 ----------------
    def bindings(self):
        """角色槽位 → 声音素材槽位（副本；"" 键 = 默认角色/兜底声音）。"""
        cfg = self._cfg() or {}
        b = (cfg.get("voice") or {}).get("bindings")
        return dict(b) if isinstance(b, dict) else {}

    def bind_voice(self, role_slot, voice_slot):
        """绑定角色 → 声音素材。返回 (ok, err)。"""
        if self._assets is None:
            return False, "声音素材库不可用"
        voice_slot = str(voice_slot or "")
        if voice_slot and self._assets.get_asset(voice_slot) is None:
            return False, "声音素材不存在（先在资源管理导入）"
        cfg = self._cfg()
        if not isinstance(cfg, dict):
            return False, "配置不可用"
        vcfg = cfg.setdefault("voice", {})
        binds = dict(vcfg.get("bindings") or {})
        key = str(role_slot or "")
        if voice_slot:
            binds[key] = voice_slot
        else:
            binds.pop(key, None)
        vcfg["bindings"] = binds
        if self._save_cfg:
            self._save_cfg(cfg)
        return True, ""

    def unbind_voice(self, role_slot):
        return self.bind_voice(role_slot, "")

    def resolve_voice(self, role_slot, voice_slot=None):
        """解析最终声音素材：台词指定 > 角色绑定 > 默认兜底绑定。

        返回 (voice_slot|"", err)：都没有 → 明确报错（不静默播放）。
        """
        binds = self.bindings()
        vs = str(voice_slot or "") or binds.get(str(role_slot or "")) or binds.get("") or ""
        if not vs:
            return "", "这条台词没有指定声音，也没给角色绑定声音（去语音设置绑定一个）"
        if self._assets is None:
            return "", "声音素材库不可用"
        if self._assets.get_asset(vs) is None:
            return "", "声音素材不存在（可能已删除）：%s" % vs
        return vs, ""

    # ---------------- 缓存 ----------------
    def _params_for(self, backend_id):
        cfg = self._cfg() or {}
        vcfg = cfg.get("voice") or {}
        params = dict((vcfg.get("backend_params") or {}).get(backend_id) or {})
        bip = get_backend(backend_id).default_params
        for k, v in bip.items():
            if k not in params or params[k] is None:
                # L3 修复：可变默认值必须深拷贝——否则会就地污染后端类的 default_params
                params[k] = copy.deepcopy(v) if isinstance(v, (dict, list)) else v
        if backend_id == "openai":  # 旧后端沿用 AI 设置里的地址
            if not params.get("base_url"):
                params["base_url"] = str(cfg.get("ai_base_url") or "").strip().rstrip("/")
        if backend_id == "sapi":
            # M9 修复：显式用 tts_voice（此前 setdefault 被默认值 "" 挡住，用户填的音色包永不生效）
            params["voice"] = str(vcfg.get("tts_voice") or params.get("voice") or "")
        return params

    def _key_for(self, backend_id, voice_slot, text, params):
        # 内部键（cloned / _slot 等，以 _ 开头或显式排除）**不进签名**：
        # 否则写入与删除（regenerate）算出的路径不同 → 重新生成永远删不掉旧缓存。
        sig = json.dumps({k: v for k, v in (params or {}).items()
                          if k != "cloned" and not str(k).startswith("_")},
                         ensure_ascii=False, sort_keys=True)
        raw = "%s|%s|%s|%s" % (backend_id, voice_slot, text, sig)
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:20]

    def _cache_path(self, backend_id, voice_slot, text, params):
        ext = "mp3" if backend_id in ("openai", "minimax", "elevenlabs") else "wav"
        return os.path.join(self._cache_dir, "%s.%s" % (
            self._key_for(backend_id, voice_slot, text, params), ext))

    def _cache_ok(self, path):
        try:
            return os.path.isfile(path) and os.path.getsize(path) > 44
        except Exception:
            return False

    def _write_cache(self, path, data):
        try:
            os.makedirs(self._cache_dir, exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)  # 原子写：半截文件不会被当作缓存命中
            self._prune_cache()
            return True
        except Exception as e:
            self._log("voice cache write failed: %r" % (e,))
            return False

    def _persist_cloned(self, backend_id, cloned):
        """把云端后端新克隆出的 voice_id 写回配置（下次同素材直接复用，不重复克隆）。"""
        if not isinstance(cloned, dict) or not cloned or not self._save_cfg:
            return
        cfg = self._cfg()
        if not isinstance(cfg, dict):
            return
        try:
            vcfg = cfg.setdefault("voice", {})
            params = dict((vcfg.get("backend_params") or {}).get(backend_id) or {})
            old = params.get("cloned") if isinstance(params.get("cloned"), dict) else {}
            if old == cloned:
                return
            params["cloned"] = dict(cloned)
            allp = dict(vcfg.get("backend_params") or {})
            allp[backend_id] = params
            vcfg["backend_params"] = allp
            self._save_cfg(cfg)
        except Exception as e:
            self._log("persist cloned failed: %r" % (e,))  # 有意忽略：存不下就下次再克隆

    def _prune_cache(self):
        """缓存条数软上限（超出删最旧），防目录无限膨胀。"""
        cfg = self._cfg() or {}
        try:
            cap = int((cfg.get("voice") or {}).get("cache_max") or 400)
        except (TypeError, ValueError):
            cap = 400
        try:
            files = [os.path.join(self._cache_dir, f) for f in os.listdir(self._cache_dir)]
            files = [f for f in files if os.path.isfile(f)]
            if len(files) <= cap:
                return
            files.sort(key=lambda p: os.path.getmtime(p))
            for p in files[:len(files) - cap]:
                try:
                    os.remove(p)
                except Exception:
                    pass  # 有意忽略：清理尽力而为
        except Exception as e:
            self._log("voice cache prune failed: %r" % (e,))

    def regenerate(self, line_id):
        """清掉该台词（当前声音+当前后端）的缓存，下次朗读重新合成。返回 (ok, err)。"""
        if self._lines is None:
            return False, "台词库不可用"
        ln = self._lines.get(line_id)
        if ln is None:
            return False, "台词不存在"
        vs, err = self.resolve_voice(ln.get("role_slot"), ln.get("voice_slot"))
        if not vs:
            return False, err
        for bid in BACKENDS:
            p = self._cache_path(bid, vs, ln["text"], self._params_for(bid))
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except Exception:
                pass  # 有意忽略：删缓存失败就当作没删（下次仍命中旧缓存）
        return True, ""

    # ---------------- 合成与播放 ----------------
    def backend_id(self):
        cfg = self._cfg() or {}
        bid = str((cfg.get("voice") or {}).get("backend") or DEFAULT_BACKEND)
        return bid if bid in BACKENDS else DEFAULT_BACKEND

    def test_backend(self, backend_id=None):
        """后端可用性自检（不合成）：返回 (ok, msg)。"""
        bid = backend_id or self.backend_id()
        b = get_backend(bid)
        cfg = self._cfg() or {}
        vcfg = cfg.get("voice") or {}
        params = self._params_for(bid)
        if b.needs_key and not ((vcfg.get("backend_keys") or {}).get(bid) or ""):
            return False, "「%s」需要 API Key（在密钥框填写）" % b.label
        if b.needs_reference and (self._assets is None or not self._assets.assets()):
            return False, "还没导入声音素材（资源管理 → 声音素材 → 导入）"
        if b.needs_service:
            base = self._clean_url(params.get("base_url"))
            if not base:
                return False, "没填服务地址"
            try:
                r = requests.get(base, timeout=4)
                return True, "服务可达（HTTP %d）" % r.status_code
            except requests.exceptions.Timeout:
                return False, "服务无响应（超时）：确认已启动：%s" % base
            except requests.exceptions.ConnectionError:
                return False, "连不上服务：确认已启动：%s" % base
            except Exception as e:
                return False, "探测失败：%s" % e
        return True, "配置看起来没问题（云端后端会在首次使用时验证）"

    @staticmethod
    def _clean_url(u):
        return str(u or "").strip().rstrip("/")

    def is_speaking(self):
        with self._lock:
            return bool(self._speaking)

    def queue_size(self):
        with self._lock:
            return len(self._queue)

    def _enqueue(self, jobs):
        with self._lock:
            self._queue.extend(jobs)
        self._ensure_worker()

    def _ensure_worker(self):
        with self._lock:
            if not self._queue:
                return
            if getattr(self, "_worker", None) is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(target=self._run_queue, daemon=True)
            self._worker.start()

    def _next_job(self):
        with self._lock:
            return self._queue.pop(0) if self._queue else None

    def _run_queue(self):
        """工作线程：逐条合成 + 播放（UI 只经回调，不在此线程碰控件）。

        v2.1 修复：取任务与"确认队列为空"在同一把锁内完成（否则弹空到线程退出之间
        入队的任务会永久滞留）；循环体整体兜异常（后端抛异常不再打死 worker，
        否则 _speaking 永久 True 会让待机彻底失效）。"""
        while True:
            with self._lock:
                if self._queue:
                    job = self._queue.pop(0)
                else:
                    self._speaking = False
                    self._worker = None  # 允许 _enqueue 兜底重启
                    return
            try:
                with self._lock:
                    self._speaking = True
                if job.get("kind") == "dialogue_end":
                    self._emit("dialogue")
                    continue
                if job.get("gen") != self._gen:
                    continue  # 已被 stop/清空：丢弃
                self._process_job(job)
            except Exception as e:
                self._log("voice queue job failed: %r" % (e,))
                self._emit("error", "朗读出错：%s" % e)  # 有意忽略：单条失败不断队列

    def _process_job(self, job):
        text = job["text"]
        bid = job["backend"]
        vs = job["voice_slot"]
        line_id = job.get("line_id")
        params = self._params_for(bid)
        params["_slot"] = vs  # M8：云端后端按"声音素材槽位"复用已克隆声线
        backend = get_backend(bid)
        key = (self._cfg() or {}).get("voice", {}).get("backend_keys", {}) or {}
        api_key = str(key.get(bid) or "")
        if bid in ("openai", "sapi"):
            api_key = api_key or str((self._cfg() or {}).get("api_key") or "")
        ref = self._assets.asset_path(vs) if (backend.needs_reference and self._assets) else None
        if backend.needs_reference and not ref:
            self._emit("error", "参考音不见了（声音素材被删？）：%s" % vs)
            return
        cache = self._cache_path(bid, vs, text, params)
        path = cache if self._cache_ok(cache) else None
        if path is None:
            data, err = backend.synthesize(ref, text, params, api_key)
            if data is None or not data:
                self._emit("error", err or "合成失败（后端没有返回音频）")
                return
            if not self._write_cache(cache, data):
                # v2.1 修复：写缓存失败不再静默（既不播也没提示 = 用户点了没反应）
                self._emit("error", "语音缓存写入失败（磁盘满/无权限？），本次没有播放")
                return
            path = cache
        self._persist_cloned(bid, params.get("cloned"))  # M8：把新克隆出的声线存回配置
        if job.get("gen") != self._gen:
            return  # 合成期间被 stop：不播
        self._emit("started", job.get("role_slot") or "", line_id or "")
        try:
            self._play_clip(path)
        except Exception as e:
            self._log("voice play failed: %r" % (e,))
            self._emit("error", "播放失败：%s" % e)
            return
        # v2.1 修复：按音频时长等待播完再取下一条——否则多角色对白会互相掐断
        # （winsound/QMediaPlayer 都是"新音替换旧音"语义，不等就只有最后一条能听全）
        self._wait_playback(path, job.get("gen"))
        self._emit("finished", job.get("role_slot") or "", line_id or "")

    def _wait_playback(self, path, gen):
        """按音频时长等待播放结束（每 100ms 检查一次代次，stop() 可立即打断）。"""
        total = _audio_duration(path)
        waited = 0.0
        while waited < total:
            time.sleep(0.1)
            waited += 0.1
            if gen != self._gen:
                return  # 被 stop/清空：不再等

    def stop(self):
        """停止播放并清空队列（正在合成的那条也会作废）。"""
        with self._lock:
            self._gen += 1
            self._queue = []
        if self._stop_clip:
            try:
                self._stop_clip()
            except Exception as e:
                self._log("voice stop_clip failed: %r" % (e,))  # 有意忽略：停止尽力而为

    # ---- 对外：朗读台词/对白 ----
    def speak_line(self, line_id, on_error=None):
        """朗读一条台词（角色声音由台词槽位/角色绑定决定）。返回 (ok, err)。"""
        if self._lines is None:
            return False, "台词库不可用"
        ln = self._lines.get(line_id)
        if ln is None:
            return False, "台词不存在（可能已被删除）"
        return self.speak_text(ln["text"], ln.get("role_slot"), ln.get("voice_slot"),
                               line_id=ln["id"], on_error=on_error)

    def speak_dialogue(self, dialogue_id, on_error=None):
        """按顺序朗读整段对白（各自声音）。返回 (ok, err)。"""
        if self._lines is None:
            return False, "台词库不可用"
        d = self._lines.get_dialogue(dialogue_id)
        if d is None:
            return False, "对白不存在（可能已被删除）"
        items = self._lines.dialogue_lines(dialogue_id)
        if not items:
            return False, "对白里没有可播放的台词"
        jobs = []
        bad = []
        for ln in items:
            vs, err = self.resolve_voice(ln.get("role_slot"), ln.get("voice_slot"))
            if not vs:
                bad.append(err)
                continue
            jobs.append({"kind": "line", "text": ln["text"], "voice_slot": vs,
                         "role_slot": ln.get("role_slot") or "", "line_id": ln["id"],
                         "backend": self.backend_id(), "gen": self._gen})
        if bad:
            return False, "有 %d 条台词不能播放：%s" % (len(bad), bad[0])
        ok, msg = self.check_ready()
        if not ok:
            return False, msg
        jobs.append({"kind": "dialogue_end", "gen": self._gen})
        self._enqueue(jobs)
        return True, ""

    def check_ready(self, backend_id=None):
        """播放前校验（总开关/后端配置）。返回 (ok, err)。backend_id 缺省用当前后端。"""
        cfg = self._cfg() or {}
        vcfg = cfg.get("voice") or {}
        if not vcfg.get("enabled"):
            return False, "配音总开关是关的（语音设置里打开「开启语音」）"
        bid = backend_id or self.backend_id()
        b = get_backend(bid)
        if b.needs_key and not ((vcfg.get("backend_keys") or {}).get(bid) or ""):
            return False, "「%s」还没填 API Key" % b.label
        return True, ""

    def speak_text(self, text, role_slot=None, voice_slot=None, line_id=None, on_error=None):
        """按文本朗读（台词/日常/AI 回复共用）。返回 (ok, err)。"""
        text = str(text or "").strip()
        if not text:
            return False, "没有可朗读的文本"
        ok, err = self.check_ready()
        if not ok:
            if on_error:
                on_error(err)
            return False, err
        vs, verr = self.resolve_voice(role_slot, voice_slot)
        if not vs:
            if on_error:
                on_error(verr)
            return False, verr
        self._enqueue([{"kind": "line", "text": text, "voice_slot": vs,
                        "role_slot": str(role_slot or ""), "line_id": line_id or "",
                        "backend": self.backend_id(), "gen": self._gen}])
        return True, ""

    def preview_asset(self, voice_slot, text=None, backend_id=None):
        """试听某声音素材（合成一句短话）。返回 (ok, err)。"""
        if self._assets is None or self._assets.get_asset(voice_slot) is None:
            return False, "声音素材不存在（先在资源管理导入）"
        text = str(text or "").strip() or "你好呀，我是大肥鱼，这是我的声音~"
        bid = backend_id or self.backend_id()
        ok, err = self.check_ready(bid)  # v2.1：试听按**所选后端**校验（此前用全局后端，口径不一致）
        if not ok:
            return False, err
        self._enqueue([{"kind": "line", "text": text, "voice_slot": str(voice_slot),
                        "role_slot": "", "line_id": "", "backend": bid, "gen": self._gen}])
        return True, ""

    # ---- 兼容：AI 回复朗读（v2.0 行为） ----
    def speak(self, text, on_error=None):
        """AI 回复朗读：绑定了声音素材就走克隆后端；否则沿用旧固定音色（sapi/api）。

        语音关闭/空文本 → 静默返回（与 v2.0 语义一致）。"""
        cfg = self._cfg() or {}
        vcfg = cfg.get("voice") or {}
        if not vcfg.get("enabled"):
            return
        text = (text or "").strip()
        if not text:
            return
        # 优先：绑定/兜底声音 → 克隆后端
        binds = self.bindings()
        _has_binding = bool(binds.get("") )
        vs, _verr = self.resolve_voice("", None)
        if vs:
            self.speak_text(text, "", vs, on_error=on_error)
            return
        if _has_binding:
            # v2.1 修复：绑定了声音但素材已失效 —— 明确报错，**不得**退化到固定音色糊弄
            err = _verr or "绑定的声音素材不存在了（去语音设置重新绑定）"
            self._emit("error", err)
            if on_error:
                on_error(err)
            return
        mode = vcfg.get("tts_mode", "off")
        if mode == "off":
            return
        bid = "sapi" if mode == "sapi" else "openai"
        self._enqueue([{"kind": "line", "text": text, "voice_slot": "",
                        "role_slot": "", "line_id": "", "backend": bid, "gen": self._gen}])


def _to_bool(v):
    """与 pet_config._to_bool 同口径：字符串 "false"/"0" 判 False（手改配置不误开）。"""
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


# 后端参数字段白名单（单一来源：归一化 / UI / 合成共用）
BACKEND_PARAM_KEYS = ("base_url", "api", "model", "voice", "prompt_text", "ref_text",
                      "text_lang", "prompt_lang", "split_method")
BACKEND_KEYS_MAX = 200
BINDINGS_MAX = 200


def normalize_voice(v):
    """voice 配置归一化（纯函数，单一来源）：开关/后端/参数/密钥/绑定。

    始终返回新 dict；未知后端回退默认，坏值不抛异常。密钥字段不进导出包（见 pet_export）。
    """
    if not isinstance(v, dict):
        v = {}
    bid = str(v.get("backend") or DEFAULT_BACKEND)
    if bid not in BACKENDS:
        bid = DEFAULT_BACKEND
    # 后端参数：每个后端只保留白名单键 + 自带默认值
    raw_params = v.get("backend_params") if isinstance(v.get("backend_params"), dict) else {}
    params = {}
    for pbid, backend in BACKENDS.items():
        src = raw_params.get(pbid) if isinstance(raw_params.get(pbid), dict) else {}
        one = {}
        for k in BACKEND_PARAM_KEYS:
            if k in src:
                one[k] = str(src[k] or "")[:300]
        for k, dval in backend.default_params.items():
            one.setdefault(k, dval)
        cloned = src.get("cloned")
        if isinstance(cloned, dict):
            one["cloned"] = {str(k)[:64]: str(x)[:64] for k, x in list(cloned.items())[:200]}
        params[pbid] = one
    # 密钥：只为需要的后端保留（不进导出包）
    raw_keys = v.get("backend_keys") if isinstance(v.get("backend_keys"), dict) else {}
    keys = {}
    for pbid, backend in BACKENDS.items():
        if backend.needs_key:
            keys[pbid] = str(raw_keys.get(pbid) or "")[:BACKEND_KEYS_MAX]
    # 绑定：角色槽位 → 声音素材槽位
    raw_binds = v.get("bindings") if isinstance(v.get("bindings"), dict) else {}
    binds = {}
    for k, val in list(raw_binds.items())[:BINDINGS_MAX]:
        ks, vs = str(k or "")[:64], str(val or "")[:64]
        if vs:
            binds[ks] = vs
    # v2.1.1：本地后端启动配置（每个本地服务一份；auto_start/kill_on_exit 默认开启自动、默认退出清理）
    raw_ls = v.get("local_services") if isinstance(v.get("local_services"), dict) else {}
    services = {}
    for pbid, backend in BACKENDS.items():
        if not backend.needs_service:
            continue
        src = raw_ls.get(pbid) if isinstance(raw_ls.get(pbid), dict) else {}
        try:
            wait_s = int(src.get("wait_seconds") or 30)
        except (TypeError, ValueError):
            wait_s = 30
        services[pbid] = {
            "cmd": str(src.get("cmd") or "")[:500],
            "cwd": str(src.get("cwd") or "")[:500],
            "auto_start": _to_bool(src.get("auto_start")),
            "kill_on_exit": _to_bool(src.get("kill_on_exit", True)),
            "wait_seconds": max(5, min(120, wait_s)),
        }
    try:
        cache_max = int(v.get("cache_max") or 400)
    except (TypeError, ValueError):
        cache_max = 400
    return {
        "enabled": _to_bool(v.get("enabled")),
        "tts_mode": v.get("tts_mode") if v.get("tts_mode") in ("off", "sapi", "api") else "off",
        "tts_model": str(v.get("tts_model") or "").strip()[:60],
        "tts_voice": str(v.get("tts_voice") or "").strip()[:60],
        "backend": bid,
        "backend_params": params,
        "backend_keys": keys,
        "bindings": binds,
        "speak_daily": _to_bool(v.get("speak_daily")),
        "talk_action": str(v.get("talk_action") or "").strip()[:24],
        "cache_max": max(50, min(5000, cache_max)),
        "local_services": services,
    }


DEFAULT_VOICE = normalize_voice(None)


if __name__ == "__main__":
    # 命令行冒烟：无 GUI 自检（python pet_voice.py）
    import sys
    import tempfile
    _cfg = {"voice": dict(DEFAULT_VOICE)}
    _svc = VoiceService(tempfile.mkdtemp(prefix="voice_"), lambda: _cfg, lambda p: None)
    assert _svc.clip("reply") is None
    assert set(BACKENDS) >= {"gpt_sovits", "f5_tts", "cosyvoice", "minimax", "elevenlabs",
                             "openai", "sapi"}
    assert get_backend("nope").id == DEFAULT_BACKEND
    _n = normalize_voice({"backend": "ghost", "cache_max": 99999, "bindings": {"r": "v"}})
    assert _n["backend"] == DEFAULT_BACKEND and _n["cache_max"] == 5000
    assert _n["bindings"] == {"r": "v"}
    assert explain_backend_error(401).startswith("后端鉴权失败")
    # v2.1.1：本地后端启动器（命令为空要明确报错；没启动过时 stop 视为已完成）
    _ln = VoiceLauncher(tempfile.mkdtemp(prefix="launch_"))
    assert _ln.start("", "", "gpt_sovits")[0] is False
    assert _ln.stop() == (True, "没有需要结束的后端（桌宠没启动过后端）")
    _ok_l, _msg_l = _ln.start('"%s" -c "import time; time.sleep(4)"' % sys.executable,
                              "", "gpt_sovits")
    assert _ok_l and _ln.is_running(), _msg_l
    assert _ln.status()["pid"] > 0
    assert _ln.stop()[0] is True and not _ln.is_running()
    assert _n["local_services"]["gpt_sovits"]["kill_on_exit"] is True
    assert _n["local_services"]["gpt_sovits"]["wait_seconds"] == 30
    # 后端缺服务/缺 Key 时必须明确报错（不假装实现）
    _b = get_backend("gpt_sovits")
    _data, _err = _b.synthesize("", "你好", {"base_url": ""})
    assert _data is None and _err
    _b2 = get_backend("minimax")
    _data2, _err2 = _b2.synthesize("x.wav", "你好", {}, "")
    assert _data2 is None and "Key" in _err2
    print("SMOKE OK")


