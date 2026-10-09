# -*- coding: utf-8 -*-
"""
AI 对话线程 + 对话记忆持久化（P1-6 / P1-10 / P3-3 / v2.0.4 多模型 API）。

独立模块：不 import 桌宠.py。signals / cfg / 人设构造 / 表情解析 / 记忆读写全部注入；
_py/_chat_history/_history_lock/_mem_epoch 等守卫状态仍归属 PetWindow（语义不变）。
"""
import json
import os
import threading

import requests

# ---------------- v2.0.4：其他模型 API（服务商预设 + 错误归类 + 连通性测试） ----------------
# 默认接口/模型单一来源（全仓引用：对话、测试连接、配置归一化、AI 设置对话框）
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"

# 错误提示前缀（语音跳过表按前缀匹配，错误提示不朗读；与 explain_api_error 同源维护）
API_ERROR_PREFIXES = ("密钥无效", "额度不足", "地区限制", "权限不足", "接口地址或模型名不存在",
                      "请求参数不被接受", "请求太频繁", "服务商服务器", "服务异常",
                      "连不上接口地址", "响应超时", "它想太久了", "网络不好")


def is_local_base(base_url):
    """是否本地服务（localhost/回环地址）：本地模型不需要 API Key。"""
    return ("localhost" in (base_url or "")) or ("127.0.0.1" in (base_url or ""))         or ("[::1]" in (base_url or ""))

# 服务商预设（可配置：选中即填 base_url/model，用户仍可手改；custom 为手动配置）。
# 均为 OpenAI 兼容 /chat/completions 端点；模型名只是默认参考值，可随时改，
# 「测试连接」会如实校验（doubao/minimax/spark 三家的模型名建议以官方控制台为准）。
AI_PROVIDERS = {
    # ---- 国内主流 ----
    "deepseek": {"name": "DeepSeek 官方", "base_url": "https://api.deepseek.com",
                 "model": "deepseek-chat"},
    "kimi": {"name": "月之暗面 Kimi（Moonshot）", "base_url": "https://api.moonshot.cn/v1",
             "model": "moonshot-v1-8k"},
    "doubao": {"name": "豆包（火山方舟 Ark）", "base_url": "https://ark.cn-beijing.volces.com/api/v3",
               "model": "doubao-1-5-lite-32k-250115"},
    "qwen": {"name": "通义千问（DashScope 兼容）",
             "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
             "model": "qwen-plus"},
    "zhipu": {"name": "智谱 GLM", "base_url": "https://open.bigmodel.cn/api/paas/v4",
              "model": "glm-4-flash"},
    "hunyuan": {"name": "腾讯混元", "base_url": "https://api.hunyuan.cloud.tencent.com/v1",
                "model": "hunyuan-turbos-latest"},
    "spark": {"name": "讯飞星火", "base_url": "https://spark-api-open.xf-yun.com/v1",
              "model": "generalv3.5"},
    "qianfan": {"name": "百度千帆", "base_url": "https://qianfan.baidubce.com/v2",
                "model": "ernie-4.0-turbo-8k"},
    # ---- 国际 ----
    "openai": {"name": "OpenAI 官方", "base_url": "https://api.openai.com/v1",
               "model": "gpt-4o-mini"},
    "groq": {"name": "Groq（超快推理）", "base_url": "https://api.groq.com/openai/v1",
             "model": "llama-3.3-70b-versatile"},
    "openrouter": {"name": "OpenRouter（多模型聚合）", "base_url": "https://openrouter.ai/api/v1",
                   "model": "meta-llama/llama-3.3-70b-instruct"},
    "minimax": {"name": "MiniMax", "base_url": "https://api.minimax.chat/v1",
                "model": "MiniMax-Text-01"},
    "siliconflow": {"name": "硅基流动 SiliconFlow（开源模型聚合）",
                    "base_url": "https://api.siliconflow.cn/v1",
                    "model": "Qwen/Qwen2.5-7B-Instruct"},
    # ---- 本地 ----
    "ollama": {"name": "本地 Ollama（免费离线）", "base_url": "http://localhost:11434/v1",
               "model": "qwen2.5"},
    "custom": {"name": "自定义（手动填接口地址/模型名）", "base_url": "", "model": ""},
}


def explain_api_error(status, body=""):
    """HTTP 状态码 + 响应体 → 中文原因（纯函数，可测；未知状态给通用原因）。

    覆盖目标：密钥无效 / 额度不足 / 地区限制 / 服务不可用 / 模型或地址不存在 /
    限流——全部界面直接提示，绝不静默。响应体做关键词嗅探细化（服务商文案各异）。
    """
    b = (body or "").lower()
    # 先按状态码归类：403 必须早于 body 嗅探（网关 403 页面常含 unauthorized 字样，
    # 不能误报成「密钥无效」）；body 嗅探只作服务商文案各异的细化兜底
    if status == 403:
        if "region" in b or "country" in b or "geographic" in b or "unsupported" in b:
            return "地区限制：当前网络所在地区不被该服务支持"
        if "quota" in b or "billing" in b or "balance" in b:
            return "额度不足或账户欠费，去平台充值或换个 Key"
        return "权限不足（403）：检查 Key 的权限与账户状态"
    if status == 401 or "invalid_api_key" in b or ("invalid" in b and "key" in b) \
            or "authentication" in b or "unauthorized" in b:
        return "密钥无效或已过期，去「设置DeepSeek API Key」检查一下"
    if status == 402 or "insufficient_quota" in b or "insufficient balance" in b \
            or "余额不足" in b or ("quota" in b and "exceeded" in b):
        return "额度不足或账户欠费，去平台充值或换个 Key"
    if status == 404 or ("model" in b and "not found" in b) or "not_found" in b:
        return "接口地址或模型名不存在（404），检查 base_url 和模型名"
    if status in (400, 422):
        return "请求参数不被接受（400/422）：模型名与接口不兼容？"
    if status == 429 or "rate limit" in b or "too many" in b or "rate_limit" in b:
        return "请求太频繁被限流啦，歇几秒再试"
    if status >= 500:
        return "服务商服务器开小差了（HTTP %d），稍后再试" % status
    return "服务异常（HTTP %d），稍后再试" % status


def test_api_connection(base_url, model, key, timeout=10):
    """连通性测试：发一条 max_tokens=1 的最小请求。返回 (ok, message)。

    纯函数（工作线程调用）：任何失败都归类成中文原因，绝不抛异常。
    """
    try:
        url = (base_url or "").strip().rstrip("/")
        url = (url + "/chat/completions") if url else DEFAULT_BASE_URL + "/chat/completions"
        model = (model or "").strip() or DEFAULT_MODEL
        resp = requests.post(
            url,
            headers={"Authorization": "Bearer " + (key or ""),
                     "Content-Type": "application/json"},
            json={"model": model, "messages": [{"role": "user", "content": "ping"}],
                  "max_tokens": 1, "temperature": 0.0},
            timeout=timeout,
        )
        if resp.status_code == 200:
            return True, "连接成功，模型响应正常~"
        try:
            body = resp.text or ""
        except Exception:
            body = ""  # 有意忽略：响应体读取失败不影响状态码归类
        return False, explain_api_error(resp.status_code, body)
    except requests.exceptions.Timeout:
        return False, "响应超时：服务商可能过载，或接口地址不是 OpenAI 兼容端点"
    except requests.exceptions.ConnectionError:
        return False, "连不上接口地址：检查网络/代理/地址（本地 Ollama 要先启动）"
    except Exception:
        # 有意忽略：未知异常只给通用中文（原始英文对小白不友好，调用方有日志兜底）
        return False, "连接失败，请检查接口地址与网络设置"


# ---------------- P1-6：对话记忆持久化（全量落盘，上下文只取最近 N 轮） ----------------
def read_memory(path, max_entries, log=None):
    """读取 memory.json 对话历史 [(role, content), ...]；缺失/损坏返回 []。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("history"), list):
            out = []
            for item in data["history"]:
                # 跳过畸形条目（非二元组/非字符串），不让一条坏数据毁掉整段记忆
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    r, c = item
                    if isinstance(r, str) and isinstance(c, str):
                        out.append((r, c))
            return out[-max_entries:]
    except FileNotFoundError:
        pass  # 首次运行还没有 memory.json：不是错误，别往 error.log 写吓人记录
    except Exception as e:
        if log is not None:
            log("load_chat_memory 读取失败（从空记忆开始）: %r" % (e,))
    return []


def write_memory(path, hist, max_entries, log=None):
    """原子落盘对话记忆；失败进日志（不再静默）。"""
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"history": list(hist)[-max_entries:]}, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as e:
        if log is not None:
            log("save_chat_memory 写盘失败: %r" % (e,))


class ChatService:
    """AI 对话线程：请求 / 人设 / 记忆 / 表情标记解析（P3-3 先剥标记再截断）。

    pet 提供（守卫语义与旧版一致）：_ai_inflight、_chat_history、_history_lock、_mem_epoch。
    """

    def __init__(self, pet, signals, cfg_getter, prompt_builder, parse_emote,
                 memory_loader, memory_saver, play_sound, log, default_reply_len):
        self.pet = pet
        self.signals = signals
        self._cfg = cfg_getter
        self._prompt = prompt_builder
        self._parse_emote = parse_emote
        self._load_memory = memory_loader
        self._save_memory = memory_saver
        self._play = play_sound
        self._log = log
        self._default_reply_len = default_reply_len

    def inflight(self):
        return self.pet._ai_inflight

    def ask(self, msg):
        self.pet._ai_inflight = True
        threading.Thread(target=self._worker, args=(msg, self._cfg().get("api_key", "")), daemon=True).start()

    def on_reply_ok(self):
        """AI 回复成功（主线程）：播任务完成音（借参考插件概念）。"""
        if self._cfg().get("sound", True):
            self._play("reply")

    def on_ai_emote(self, mode, kind):
        """P3-3：AI 回复带出的表情（主线程播放，data 驱动）。busy/睡眠中跳过，避免打断动作。"""
        pet = self.pet
        if pet.busy or pet._sleeping or pet._petting:
            return
        if mode == "state":
            pet._show_state(kind, 2600)
        else:
            pet._show_emote(kind)

    def _worker(self, msg, key):
        # P1-10：接口/模型/人设/长度全部配置驱动（OpenAI 兼容，支持本地 Ollama）
        # 配置读取与转换全部在 try 内：任何异常都走统一的"网络不好"回复，绝不卡死 _ai_inflight
        pet = self.pet
        try:
            cfg = self._cfg()
            base_url = (cfg.get("ai_base_url") or "").strip().rstrip("/")
            url = (base_url + "/chat/completions") if base_url else DEFAULT_BASE_URL + "/chat/completions"
            model = (cfg.get("ai_model") or "").strip() or DEFAULT_MODEL
            # P1-10+：人设预设（default/sheshe/tsundere）或用户自定义（custom → ai_system_prompt）
            sys_prompt = self._prompt(cfg)
            # 这三个键在 load_config 归一化时已被强制成 int（见 tests/test_config_robustness.py），
            # 这里直接转换是安全的：norm-ok
            max_tokens = int(cfg.get("ai_max_tokens", 60) or 60)
            reply_len = int(cfg.get("ai_reply_len", self._default_reply_len) or self._default_reply_len)
            rounds = int(cfg.get("chat_memory_rounds", 3) or 3)
            mem_epoch = pet._mem_epoch  # 记录清记忆代次：清理动作发生在请求在途时，本次回复不入记忆
            with pet._history_lock:
                history = list(pet._chat_history[-(rounds * 2):]) if rounds > 0 else []
            messages = [{"role": "system", "content": sys_prompt}]
            messages += [{"role": r, "content": c} for r, c in history]
            messages.append({"role": "user", "content": msg})
            resp = requests.post(
                url,
                headers={
                    "Authorization": "Bearer " + key,
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": 1.0,
                },
                timeout=20,
            )
            if resp.status_code != 200:
                # v2.0.4：密钥无效/额度不足/地区限制/服务不可用等一律归类成中文原因
                # 直接气泡提示（不再笼统「网络不好」）
                try:
                    body = resp.text or ""
                except Exception:
                    body = ""  # 有意忽略：响应体读取失败不影响状态码归类
                self.signals.reply.emit(explain_api_error(resp.status_code, body))
                return
            data = resp.json()
            text = data["choices"][0]["message"]["content"].strip().replace("\n", " ")
            # P3-3：先剥表情标记再截断——截断永远不会切进标记；标记剥除后才展示/入记忆
            mode, kind, text = self._parse_emote(text)
            if mode:
                self.signals.ai_emote.emit(mode, kind)
            if len(text) > reply_len:
                text = text[:reply_len]
            if not text:
                text = "…"  # 纯表情回复：气泡兜底
            with pet._history_lock:
                # Key 已被清除 / 记忆被清理（代次变化）时丢弃本次对话记忆，
                # 清除语义不可被在途请求撤销。
                # 注：_history_lock 只互斥 _chat_history 的 append/clear；cfg["api_key"]
                # 字段本身由 GIL 保证单条赋值原子性，不在此锁覆盖范围。
                if cfg.get("api_key") and pet._mem_epoch == mem_epoch:
                    pet._chat_history.append(("user", msg))
                    pet._chat_history.append(("assistant", text))
                    snapshot = list(pet._chat_history)
                else:
                    snapshot = None
            if snapshot is not None:
                self._save_memory(snapshot)  # P1-6：锁外落盘，原子写不阻塞其他线程
            self.signals.reply_ok.emit()  # 回复成功：由主线程播任务完成音（线程安全）
            self.signals.reply.emit(text)
        except requests.exceptions.Timeout:
            self._log("ai_worker timeout")
            self.signals.reply.emit("它想太久了……服务商可能过载，稍后再试")
        except requests.exceptions.ConnectionError:
            self._log("ai_worker connection error")
            self.signals.reply.emit("连不上接口地址：检查网络/代理/地址（本地 Ollama 要先启动）")
        except Exception as e:
            self._log("ai_worker: %r" % (e,))
            self.signals.reply.emit("网络不好，听不清啦……")
        finally:
            self.signals.ai_done.emit()
