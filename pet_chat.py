# -*- coding: utf-8 -*-
"""
AI 对话线程 + 对话记忆持久化（P1-6 / P1-10 / P3-3 / v2.0.4 多模型 API）。

独立模块：不 import 桌宠.py。signals / cfg / 人设构造 / 表情解析 / 记忆读写全部注入；
_py/_chat_history/_history_lock/_mem_epoch 等守卫状态仍归属 PetWindow（语义不变）。
"""
import json
import time
import os
import threading

import requests

import pet_tools  # v2.3.0（1.2）：工具注册表/执行器（Qt-free，无环）

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


# v2.3.0（1.2 Function Calling）：已知不支持 function calling 的网关关键词。
# 判据用**接口地址**而不是模型名——模型名用户可随手改，地址命中即视为不支持，
# 不发 tools、退化为纯对话（规格 1.2「本地模型兼容」）。
NO_TOOLS_HOSTS = ("ollama", "lmstudio", "lm-studio", "text-generation-webui",
                  "koboldcpp", "gpt4all")


def tools_supported(base_url):
    """当前后端是否支持 OpenAI 兼容的 function calling。

    本地地址（localhost/127.0.0.1）= 用户自架服务（Ollama 等）→ 一律不发 tools；
    云端服务商（DeepSeek/Kimi/Qwen/OpenAI…）默认支持；空地址 = DeepSeek 官方。
    """
    base = str(base_url or "").strip().lower()
    if not base:
        return True
    if is_local_base(base):
        return False
    return not any(host in base for host in NO_TOOLS_HOSTS)

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


# v2.3.0（1.1 长期记忆）：memory.json 增加 long_term 段，跨会话记住偏好/昵称/近期话题。
LONG_TERM_MAX = 50                 # 每个列表最多留多少条（FIFO）
LONG_TERM_KEYS = ("user_name", "nicknames", "preferences", "dislikes", "recent_topics")


def _read_memory_raw(path, log=None):
    """读整个 memory.json（dict）。缺失/损坏 → {}。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}   # 首次运行：不是错误
    except Exception as e:
        if log is not None:
            log("memory.json 读取失败（按空处理）: %r" % (e,))
        return {}


def _write_memory_file(path, hist=None, long_term=None, max_entries=3, log=None):
    """原子写 memory.json：**history 与 long_term 合并写**，谁都不覆盖谁。"""
    data = _read_memory_raw(path, log)
    if hist is not None:
        data["history"] = list(hist)[-max_entries:]
    if long_term is not None:
        data["long_term"] = sanitize_long_term(long_term)
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as e:
        if log is not None:
            log("save_chat_memory 写盘失败: %r" % (e,))
    return data


def write_memory(path, hist, max_entries, log=None):
    """原子落盘对话记忆（保留 long_term 段，不再整文件覆盖）。"""
    _write_memory_file(path, hist=hist, max_entries=max_entries, log=log)


def sanitize_long_term(lt):
    """长期记忆归一化：只要认识的键；列表去重、截断长度、FIFO 限量；总量控制在 4KB 内。"""
    out = {"user_name": "", "nicknames": [], "preferences": [], "dislikes": [], "recent_topics": []}
    if not isinstance(lt, dict):
        return out
    out["user_name"] = str(lt.get("user_name") or "")[:24]
    for k in LONG_TERM_KEYS[1:]:   # user_name 是标量，单独处理
        vals = lt.get(k)
        if not isinstance(vals, list):
            continue
        seen = []
        for v in vals:
            s = str(v or "").strip()[:60]
            if s and s not in seen:
                seen.append(s)
        out[k] = seen[-LONG_TERM_MAX:]
    # token/体积兜底：拼出来超过 4KB 就从最老的开始丢
    while len(json.dumps(out, ensure_ascii=False)) > 4096 and (out["preferences"] or out["recent_topics"]):
        for k in ("recent_topics", "preferences"):
            if out[k]:
                out[k].pop(0)
                break
    out["last_updated"] = str(lt.get("last_updated") or "")
    return out


def read_long_term(path, log=None):
    """读长期记忆（缺失/损坏 → 空结构）。"""
    return sanitize_long_term(_read_memory_raw(path, log).get("long_term"))


def write_long_term(path, long_term, max_entries=3, log=None):
    """写长期记忆（保留 history 段）。返回归一化后的结构。"""
    lt = sanitize_long_term(long_term)
    lt["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _write_memory_file(path, long_term=lt, max_entries=max_entries, log=log)
    return lt


# 规则抽取：零 API 成本、可测。命中即记一条偏好/称呼/话题（首版不做 LLM 抽取，避免多花一次额度）
# v2.3.0（找茬 M4）：**区分极性**——此前"我讨厌香菜"会落成 preferences:["香菜"]，
# 再被渲染成"喜好：香菜"，模型反而会主动推荐用户讨厌的东西。
_EXTRACT_RULES = (
    ("dislikes", ("我最讨厌", "最讨厌", "我不喜欢", "我不爱吃", "我受不了", "我讨厌")),
    ("preferences", ("我最喜欢", "我最爱吃", "我喜欢", "我爱吃", "我爱喝", "我最爱", "我爱")),
    # v2.3.0（兼容审查 M3）：去掉"我是"——它是口语高频词（"我是说真的"→ 称呼"说真的"），
    # 只保留明确的自我介绍口径
    ("user_name", ("我叫", "我的名字是", "我的名字叫")),
    ("nicknames", ("可以叫我", "叫我")),
)


def extract_long_term(user_msg):
    """从一轮对话里抽长期记忆（规则式）。返回 {字段: 值/列表}（可能为空）。

    v2.3.0（找茬 L4）：去掉此前没被使用的 reply/limit 两个死参数。
    """
    out = {}
    text = str(user_msg or "").strip()
    if not text or len(text) > 200:
        return out
    for key, pats in _EXTRACT_RULES:
        for pat in pats:
            i = text.find(pat)
            if i < 0:
                continue
            frag = text[i + len(pat):]
            for sep in ("。", "！", "？", "，", ",", ".", "；", ";", "\n", " "):
                j = frag.find(sep)
                if j >= 0:
                    frag = frag[:j]
            frag = frag.strip()[:40]
            # v2.3.0（质量 M3）：形状约束——口语高频词不该被当成身份长期记住
            # （实测："我是说这个不对"曾是 user_name="说这个不对"）
            if key in ("user_name", "nicknames"):
                if len(frag) < 2 or len(frag) > 6 or frag[0] in "说问想在没的不把被让给和跟对是从就会要与": 
                    break
            if 1 <= len(frag):
                if key == "user_name":
                    out[key] = frag
                else:
                    out.setdefault(key, []).append(frag)
            break
    # 近况：用户这轮说了较长的内容 → 记一句话题（帮助下次"上次你说…"）
    if len(text) >= 12:
        out.setdefault("recent_topics", []).append(text[:40])
    return out


class ChatService:
    """AI 对话线程：请求 / 人设 / 记忆 / 表情标记解析（P3-3 先剥标记再截断）。

    pet 提供（守卫语义与旧版一致）：_ai_inflight、_chat_history、_history_lock、_mem_epoch。
    """

    def __init__(self, pet, signals, cfg_getter, prompt_builder, parse_emote,
                 memory_loader, memory_saver, play_sound, log, default_reply_len,
                 context_builder=None, memory_path=None, tool_ctx=None):
        self.pet = pet
        self.signals = signals
        self._cfg = cfg_getter
        self._prompt = prompt_builder
        self._parse_emote = parse_emote
        self._load_memory = memory_loader
        # v2.3.0（1.1/1.3）：上下文摘要构建器（长期记忆 + 记账/偏好摘要），由桌宠注入
        self._context = context_builder
        self._mem_path = memory_path  # v2.3.0（1.1）：长期记忆落盘目标（None=不启用抽取）
        self._save_memory = memory_saver
        self._play = play_sound
        self._log = log
        self._default_reply_len = default_reply_len
        # v2.3.0（1.2 Function Calling）：工具上下文（None=该实例不支持工具调用）
        self._tool_ctx = tool_ctx
        # worker 线程 ↔ 主线程的工具协作表：UI 工具调用 + 写入确认（各自带 Event）
        self._ui_lock = threading.Lock()
        self._ui_calls = {}       # {call_id: pet_tools.MainThreadCall}
        self._tool_confirms = {}  # {req_id: pet_tools.ToolConfirmRequest}

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

    # ---------- v2.3.0（1.2 Function Calling）：worker 线程 ↔ 主线程协作 ----------
    def marshal(self, name, args, timeout=None):
        """worker 线程请主线程执行一次 UI 工具并等结果（表情/动作/闹钟/定时器）。

        超时按失败返回（绝不无限等）：主线程忙/退出时工作线程仍能收尾。
        """
        call = pet_tools.MainThreadCall(name, args)
        if timeout is None:
            timeout = pet_tools.UI_CALL_TIMEOUT
        with self._ui_lock:
            self._ui_calls[call.id] = call
        try:
            self.signals.tool_call.emit(call.id, call.name, pet_tools.args_json(call.args))
            if not call.wait(timeout):
                return {"ok": False, "error": "界面没有响应"}
            return call.result
        finally:
            with self._ui_lock:
                self._ui_calls.pop(call.id, None)

    def marshal_nowait(self, name, args):
        """worker 线程请主线程打开对话框（不等结果：对话框本身会给用户反馈）。"""
        self.signals.tool_ui.emit(str(name), pet_tools.args_json(args))
        return {"ok": True, "opened": True}

    def resolve_call(self, call_id, result):
        """主线程：把 UI 工具的执行结果交回等待中的 worker（找不到=已超时，忽略）。"""
        with self._ui_lock:
            call = self._ui_calls.get(str(call_id))
        if call is None:
            return False
        call.resolve(result)
        return True

    def confirm(self, req_id, approved):
        """主线程：回答一次写入确认（True=同意执行，False=拒绝）。"""
        with self._ui_lock:
            req = self._tool_confirms.get(str(req_id))
        if req is None:
            return False  # 已超时收尾：迟到的答复忽略
        req.resolve(approved)
        return True

    def _run_tool(self, name, args, confirm_writes):
        """执行一次工具调用（worker 线程）：只读直接跑，写入先问用户。绝不抛异常。

        只读工具（查余额/天气/账本/表情/动作）在本线程执行：网络 I/O 不上 UI 线程；
        UI 类工具经 signals 投递主线程，写入类工具先经 signals.tool_confirm_required 问用户。
        """
        try:
            spec = pet_tools.get_tool(name)
            if spec is None:
                return {"ok": False, "error": "我还不会做这个（未知工具：%s）" % (name,)}
            if spec.readonly or not confirm_writes:
                return pet_tools.execute(name, args, self._tool_ctx, confirmed=True)
            req = pet_tools.ToolConfirmRequest(name, args)
            with self._ui_lock:
                self._tool_confirms[req.id] = req
            try:
                self.signals.tool_confirm_required.emit(req.id, spec.name,
                                                        pet_tools.args_json(args))
                approved = req.wait(pet_tools.CONFIRM_TIMEOUT)
            finally:
                with self._ui_lock:
                    self._tool_confirms.pop(req.id, None)
            if approved is None:
                return {"ok": False, "error": "绳匠没有回应，这次先不做"}
            if not approved:
                return {"ok": False, "error": "绳匠拒绝了这次操作，别重试，用自然语言回应就好"}
            return pet_tools.execute(name, args, self._tool_ctx, confirmed=True)
        except Exception as e:
            if self._log is not None:
                self._log("tool run failed: %r" % (e,))
            return {"ok": False, "error": "工具执行失败"}

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
            # v2.3.0（1.1 长期记忆 + 1.3 用户数据摘要）：拼在 system 尾部，token 开销极小；
            # ai_rag_enabled=False 时构建器返回空串（隐私开关）
            if self._context is not None:
                try:
                    _ctx = self._context(cfg) or ""
                except Exception as _e:
                    _ctx = ""
                    if self._log is not None:
                        self._log("ai context build failed: %r" % (_e,))
                if _ctx:
                    sys_prompt = sys_prompt + "\n" + _ctx
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
            # v2.3.0（1.2 Function Calling）：总开关 + 后端能力探测（Ollama 等不发 tools，
            # 退化为纯对话）；cfg 每轮重新取快照——工具执行期间用户可能已清 Key/改配置。
            use_tools = (bool(cfg.get("ai_tools_enabled", True)) and self._tool_ctx is not None
                         and tools_supported(base_url))
            confirm_writes = bool(cfg.get("ai_tools_confirm", True))
            tool_rounds = 0
            _exhausted = False  # v2.3.0：工具轮数用尽 → 文案兜底且本次不入记忆（兼容审查 M4）
            message = {}
            while True:
                payload = {"model": model, "messages": messages,
                           "max_tokens": max_tokens, "temperature": 1.0}
                if use_tools:
                    payload["tools"] = pet_tools.openai_tools()
                resp = requests.post(
                    url,
                    headers={
                        "Authorization": "Bearer " + key,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=20,
                )
                if use_tools and tool_rounds == 0 and resp.status_code in (400, 422):
                    # 后端/模型不认 tools：这一发退化为纯对话重发，而不是把 400 甩给用户
                    use_tools = False
                    self._log("tools rejected by backend (HTTP %d), degraded to plain chat"
                              % resp.status_code)
                    continue
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
                message = data["choices"][0]["message"] or {}
                # v2.3.0（找茬 M2）：非 list 会被当可迭代对象——"abc" 会迭代出 3 个空名调用、
                # 追加 3 条 tool_call_id:"" 的非法消息，还把坏结构原样回灌。这里只认 list[dict]。
                _calls_raw = message.get("tool_calls")
                calls = [c for c in _calls_raw if isinstance(c, dict)] \
                    if isinstance(_calls_raw, list) else []
                if not calls:
                    break  # 没有工具调用：这条 message 就是最终回复
                if tool_rounds >= pet_tools.MAX_TOOL_ROUNDS:
                    # v2.3.0（兼容审查 M4）：轮数用尽但模型还想调工具——此前直接 break，把带
                    # tool_calls 的空正文当回复 → 用户只看到"…"，还会被写进对话记忆。
                    # 现在给一句明确文案，并标记本次不入记忆（避免污染下一轮上下文）。
                    _exhausted = True  # 见下方：本次不入记忆
                    message = {"content": "（这次要做的事情有点多，先到这儿~ 再说一次我接着弄）"}
                    break
                tool_rounds += 1
                # 助手这条消息（含 tool_calls）必须原样放回上下文，否则下一轮请求不合法
                messages.append({"role": "assistant", "content": message.get("content") or "",
                                 "tool_calls": calls})
                for _i, _call in enumerate(calls):
                    _name, _args, _cid = pet_tools.parse_call(_call)
                    # v2.3.0（找茬 M1）：模型没给 id 时 parse_call 补了 uuid，必须同步写回
                    # assistant 这条 calls 元素，否则 tool 消息的 tool_call_id 无处对应 → 下一轮 400
                    # v2.3.0（质量 L1）：判据必须与 parse_call 的归一化一致——纯空白 "   " 或
                    # 整数 id 也会被归一化，用 not call.get("id") 会漏掉，导致 id 对不上 → 下一轮 400
                    if _cid and _call is not None and _call.get("id") != _cid:
                        _call["id"] = _cid
                    if _i >= pet_tools.MAX_CALLS_PER_ROUND:
                        _res = {"ok": False, "error": "一次最多执行 %d 个工具，这个先跳过"
                                % pet_tools.MAX_CALLS_PER_ROUND}
                    elif _args is None:
                        _res = {"ok": False, "error": "参数不是合法 JSON，请重新调用一次"}
                    else:
                        _res = self._run_tool(_name, _args, confirm_writes)
                    # 每个 tool_call 都必须有对应的 tool 消息，否则服务端会拒绝下一轮
                    messages.append({"role": "tool", "tool_call_id": _cid,
                                     "content": pet_tools.result_text(_res)})
                    _summary = pet_tools.summarize(_res)
                    if _summary:
                        self.signals.tool_result.emit(_name, _summary)
            text = str(message.get("content") or "").strip().replace("\n", " ")
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
            # v2.3.0（1.1 长期记忆）：回复成功后**规则抽取**一条记忆并合并落盘。
            # 用规则而不是再调一次模型：零 API 成本、可单测，也不会因为额度和网络多一次失败面。
            if snapshot is not None and self._mem_path and not _exhausted:
                try:
                    _lt = read_long_term(self._mem_path, self._log)
                    _new = extract_long_term(msg)
                    _changed = False
                    if _new.get("user_name"):
                        _lt["user_name"] = _new["user_name"]
                        _changed = True
                    for _k in ("nicknames", "preferences", "recent_topics"):
                        for _v in (_new.get(_k) or []):
                            if _v not in _lt[_k]:
                                _lt[_k].append(_v)
                                _changed = True
                    if _changed:
                        write_long_term(self._mem_path, _lt, log=self._log)
                except Exception as _e:
                    if self._log is not None:
                        self._log("long_term extract failed: %r" % (_e,))
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
