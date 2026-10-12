# -*- coding: utf-8 -*-
"""v2.3.0（1.2 Function Calling）：工具注册表 + 执行器 + 安全门控。

设计约束（规格 1.2）：
- **Qt-free**：本模块不 import Qt、不 import 任何业务模块——所有能力经 ToolContext 注入回调，
  由 桌宠.py 在装配时接上 balance / weather / book / alarms 与「回主线程」调度，
  因此可无 GUI 单测。
- **权限分级**：readonly=True 的工具（查余额 / 查天气 / 账本摘要 / 打开账本 / 表情 / 动作）
  直接执行；写入类（记账 / 预算 / 闹钟 / 定时提醒）**必须 confirmed=True**——ChatService
  先经主线程问用户，同意才带 confirmed=True 重入；拒绝则把"用户拒绝了"作为工具结果回给模型。
- **绝不抛出**：executor 把任何异常吞成 {"ok": False, "error": ...}，工作线程不会被打断。

工具 ↔ 现有模块映射（不新造业务逻辑）：
  check_balance      → pet_balance.BalanceService.fetch_sync()
  check_weather      → pet_weather.WeatherService.fetch_sync()
  open_ledger        → pet_balance.BalanceService.open_ledger()
  get_ledger_summary → pet_book.Book.today_usage()/week_usage()/total_amount()
  add_manual_record  → pet_balance.BalanceService.add_manual_record()
  set_budget         → pet_balance.BalanceService.set_budget()
  set_alarm          → pet_alarm.AlarmService.add()
  set_timer          → QTimer.singleShot（一次性提醒，主线程）
  show_emote         → PetWindow._show_emote()
  play_action        → pet_actions.ActionService.play_action()
"""
import json
import math
import threading
import uuid
from typing import Any, Callable, Iterable

import pet_log  # v2.6.0（D7-B ②）：确认文案生成失败要留痕（pet_log 无依赖，不成环）

# 一次对话最多几轮工具调用（防"模型自己跟自己聊"死循环）
MAX_TOOL_ROUNDS = 2
# 单轮最多执行几个工具；多余的按"跳过"回填，保证 tool 消息与 tool_calls 一一对应
MAX_CALLS_PER_ROUND = 3
# 写工具确认等待上限（秒）：超时按"用户没回应"回给模型，绝不永久卡住工作线程
CONFIRM_TIMEOUT = 60.0
# 主线程 UI 工具（表情/动作/闹钟/定时器）阻塞等待上限（秒）
UI_CALL_TIMEOUT = 20.0
# 单条工具结果回填给模型的文本上限（防一次查询把 token 打爆）
TOOL_RESULT_MAX = 600
# 表情种类（与 pet_widgets._emote_mark 的绘制分支同口径）
EMOTE_KINDS = ("heart", "sparkle", "sweat", "drool", "tear", "anger",
               "exclaim", "question", "zzz", "note")


class ToolSpec:
    """一个可被模型调用的工具：name / description / JSON schema / handler / readonly。"""

    __slots__ = ("name", "label", "description", "parameters", "handler", "readonly")

    def __init__(self, name: str, description: str, parameters: dict,
                 handler: Callable[[dict, Any], Any], readonly: bool,
                 label: str = "") -> None:
        self.name = str(name)
        self.label = str(label or name)
        self.description = str(description)
        self.parameters = (parameters if isinstance(parameters, dict)
                           else {"type": "object", "properties": {}})
        self.handler = handler
        self.readonly = bool(readonly)

    def to_openai(self) -> dict:
        """OpenAI 兼容的 tools 条目（DeepSeek / Kimi / Qwen / OpenAI 同一格式）。"""
        return {"type": "function",
                "function": {"name": self.name, "description": self.description,
                             "parameters": self.parameters}}


def build_registry(specs: Iterable[ToolSpec]) -> dict[str, ToolSpec]:
    """工具列表 → {name: ToolSpec}。重名直接报错：工具名必须唯一，否则模型指哪个都说不清。"""
    out = {}
    for spec in specs:
        if not isinstance(spec, ToolSpec):
            raise ValueError("工具项必须是 ToolSpec：%r" % (spec,))
        if spec.name in out:
            raise ValueError("工具名重复：%s" % spec.name)
        out[spec.name] = spec
    return out


def _schema(props: dict | None = None, required: Iterable[str] = ()) -> dict:
    """JSON Schema 片段（object 类型 + 属性 + required），省得每条手写。"""
    return {"type": "object", "properties": dict(props or {}), "required": list(required)}


# ---------------- 处理器：全部只做"转发 + 兜底"，业务逻辑留在各服务里 ----------------
def _provider(fn: Callable[[], tuple[Any, Any]] | None, missing: str) -> dict:
    """调用注入的数据提供者：约定返回 (ok, dict) 或 (ok, 错误文案)。"""
    if not callable(fn):
        return {"ok": False, "error": missing}
    ok, payload = fn()
    if ok:
        if isinstance(payload, dict):
            out = {"ok": True}
            out.update(payload)
            return out
        return {"ok": True, "data": payload}
    return {"ok": False, "error": str(payload or missing)}


def _ui(ctx: Any, name: str, args: Any, blocking: bool = True) -> dict:
    """主线程类工具：blocking=True 等结果；False 只投递（对话框自己给用户反馈）。"""
    fn = getattr(ctx, "ui" if blocking else "ui_async", None)
    if not callable(fn):
        return {"ok": False, "error": "界面不可用"}
    res = fn(name, args if isinstance(args, dict) else {})
    if isinstance(res, dict):
        return res
    return {"ok": True}


def _h_check_balance(args: dict, ctx: Any) -> dict:
    return _provider(getattr(ctx, "balance", None), "余额服务不可用")


def _h_check_weather(args: dict, ctx: Any) -> dict:
    return _provider(getattr(ctx, "weather", None), "天气服务不可用")


def _h_ledger_summary(args: dict, ctx: Any) -> dict:
    return _provider(getattr(ctx, "ledger", None), "账本不可用")


def _h_open_ledger(args: dict, ctx: Any) -> dict:
    return _ui(ctx, "open_ledger", args, blocking=False)


def _h_add_manual_record(args: dict, ctx: Any) -> dict:
    return _ui(ctx, "add_manual_record", args, blocking=False)


def _h_set_budget(args: dict, ctx: Any) -> dict:
    return _ui(ctx, "set_budget", args, blocking=False)


def _h_set_alarm(args: dict, ctx: Any) -> dict:
    return _ui(ctx, "set_alarm", args, blocking=True)


def _h_set_timer(args: dict, ctx: Any) -> dict:
    return _ui(ctx, "set_timer", args, blocking=True)


def _h_show_emote(args: dict, ctx: Any) -> dict:
    return _ui(ctx, "show_emote", args, blocking=True)


def _h_play_action(args: dict, ctx: Any) -> dict:
    return _ui(ctx, "play_action", args, blocking=True)


_NO_ARGS = _schema()
_TIME_PROP = {"type": "string", "description": "24 小时制时间，HH:MM，例如 07:30"}
_LABEL_PROP = {"type": "string", "description": "提醒文案，20 字以内，例如 起床"}

# 注册顺序 = tools 参数里的顺序（稳定，便于测试与阅读）
TOOL_SPECS = (
    ToolSpec(
        "check_balance",
        "查询绳匠的 DeepSeek API 账户余额（实时联网，1~10 秒）。用户问「还有多少钱 / 余额」时调用。",
        _NO_ARGS, _h_check_balance, True, label="查余额"),
    ToolSpec(
        "check_weather",
        "查询当前城市的天气（城市取配置里的城市名）。用户问天气 / 冷不冷 / 要不要带伞时调用。",
        _NO_ARGS, _h_check_weather, True, label="查天气"),
    ToolSpec(
        "get_ledger_summary",
        "读取记账摘要：今日消费、近 7 天消费、累计消费、今日预算。只读，不联网。",
        _NO_ARGS, _h_ledger_summary, True, label="看记账摘要"),
    ToolSpec(
        "open_ledger",
        "打开账本窗口给绳匠看（今日 / 近 7 天 / 全部 三个页签）。用户想看消费明细时调用。",
        _NO_ARGS, _h_open_ledger, True, label="打开账本"),
    ToolSpec(
        "add_manual_record",
        "手动记一笔账（金额 + 备注）。会先问绳匠确认，再打开记账对话框。",
        _schema({"amount": {"type": "number", "description": "金额（元），例如 38.5"},
                 "note": {"type": "string", "description": "备注，例如 奶茶（可留空）"}},
                ("amount",)),
        _h_add_manual_record, False, label="记一笔账"),
    ToolSpec(
        "set_budget",
        "设置今日预算提醒金额（0 = 关闭提醒）。会先问绳匠确认。",
        _schema({"amount": {"type": "number", "description": "预算金额（元），例如 5"}},
                ("amount",)),
        _h_set_budget, False, label="设今日预算"),
    ToolSpec(
        "set_alarm",
        "设置一个闹钟（时间 + 提醒文案），到点响铃 / 语音提醒。会先问绳匠确认。",
        _schema({"time": _TIME_PROP, "label": _LABEL_PROP}, ("time",)),
        _h_set_alarm, False, label="设闹钟"),
    ToolSpec(
        "set_timer",
        "设置一个「X 分钟后」的一次性提醒（不写进闹钟库）。会先问绳匠确认。",
        _schema({"minutes": {"type": "number", "description": "多少分钟后提醒，1~1440"},
                 "label": _LABEL_PROP}, ("minutes",)),
        _h_set_timer, False, label="设定时提醒"),
    ToolSpec(
        "show_emote",
        "在头顶显示一个表情，表达情绪（开心 / 疑惑 / 睡着…）。",
        _schema({"kind": {"type": "string", "enum": list(EMOTE_KINDS),
                          "description": "表情名"}}, ("kind",)),
        _h_show_emote, True, label="显示表情"),
    ToolSpec(
        "play_action",
        # v2.3.0（兼容审查 L1）：描述必须与真实可用动作一致——此前承诺 breath/sway/nod，
        # 内置角色全部会被拒（且内部名是 breathe），模型白跑一轮
        "播放一个动作：jump（跳一下）/ emote（表情）/ breathe（呼吸）,"
        "或当前角色自带的帧动作名。",
        _schema({"name": {"type": "string", "description": "动作名，例如 jump"}}, ("name",)),
        _h_play_action, True, label="播动作"),
)

TOOLS = build_registry(TOOL_SPECS)


# ---------------- 注册表读取 ----------------
def get_tool(name: str) -> ToolSpec | None:
    """按名取工具（未知返回 None）。"""
    return TOOLS.get(str(name or ""))


def openai_tools() -> list[dict]:
    """请求体里的 tools 参数（顺序稳定）。"""
    return [spec.to_openai() for spec in TOOL_SPECS]


def tool_names(readonly: bool | None = None) -> tuple[str, ...]:
    """工具名元组；readonly=None 全部，True 只读，False 写入。

    v2.4.1 去留判定：**有意保留的 API**（不是残留）。生产的执行/请求路径只用
    get_tool() 与 openai_tools()；本函数是注册表唯一的"按权限列名单"自省入口，也是
    契约测试的断言消息来源（tests/test_tools_v230.py）。要用就统一走这里，别自己
    遍历 TOOL_SPECS。"""
    return tuple(s.name for s in TOOL_SPECS
                 if readonly is None or bool(s.readonly) == bool(readonly))


# ---------------- 参数与结果处理（纯函数，可测） ----------------
def validate_args(spec: ToolSpec, args: Any) -> str:
    """参数粗校验：必须是对象、required 必填。返回错误文案（"" = 通过）。"""
    if not isinstance(args, dict):
        return "参数必须是 JSON 对象"
    params = spec.parameters if isinstance(spec.parameters, dict) else {}
    props = params.get("properties") or {}
    for key in (params.get("required") or []):
        if key not in props:
            continue
        val = args.get(key)
        if val is None or (isinstance(val, str) and not val.strip()):
            return "缺少参数 %s" % key
    return ""


def parse_call(call: Any) -> tuple[str, dict | None, str]:
    """OpenAI tool_call → (name, args, call_id)。arguments 坏 JSON 时 args 为 None。"""
    if not isinstance(call, dict):
        return "", {}, ""
    fn = call.get("function")
    fn = fn if isinstance(fn, dict) else {}
    name = str(fn.get("name") or "")
    # v2.3.0（找茬 M1）：模型偶尔不给 id → 空 tool_call_id 的报文非法，下一轮必 400，
    # 而工具其实已经执行完（用户看不到任何回复）。这里补 uuid；调用方把同一 id 写回
    # assistant 那条 calls 元素（pet_chat 已同步），保证 tool 消息能配对。
    call_id = str(call.get("id") or "").strip() or uuid.uuid4().hex
    raw = fn.get("arguments")
    if isinstance(raw, dict):
        return name, dict(raw), call_id
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return name, {}, call_id
    if isinstance(raw, str):
        try:
            val = json.loads(raw)
        except Exception:
            return name, None, call_id  # None = 坏 JSON（与"没有参数"的 {} 区分）
        return (name, val if isinstance(val, dict) else {}, call_id)
    return name, {}, call_id


def args_json(args: Any) -> str:
    """参数 → JSON 文本（跨线程投递用；坏值退空对象，绝不抛）。"""
    try:
        return json.dumps(args if isinstance(args, dict) else {}, ensure_ascii=False, default=str)
    except Exception:
        return "{}"


def parse_args(text: Any) -> dict:
    """JSON 文本 → dict（坏输入退空对象，绝不抛）。"""
    if isinstance(text, dict):
        return dict(text)
    try:
        val = json.loads(text or "{}")
    except Exception:
        return {}
    return val if isinstance(val, dict) else {}


def result_text(result: Any, limit: int = TOOL_RESULT_MAX) -> str:
    """工具结果 → tool 消息正文（JSON 文本；超长截断防 token 爆炸）。"""
    try:
        txt = json.dumps(result, ensure_ascii=False, default=str)
    except Exception:
        txt = str(result)
    return txt if len(txt) <= limit else txt[:limit] + "…(truncated)"


def summarize(result: Any) -> str:
    """工具结果 → 主线程气泡摘要：结果里带 summary 才有（其余由具体界面自己反馈）。"""
    if not isinstance(result, dict):
        return ""
    return str(result.get("summary") or "")[:60]


def _as_finite_number(v: Any) -> float | None:
    """v → float（有限数）；不是数值 / 是 bool / 是 nan|inf → None。

    v2.6.0（找茬审查 P2-d）：bool 是 int 的子类（float(True) == 1.0），"nan" / "inf"
    也能 float() 成功——它们都不是"用户要设的金额 / 分钟数"，与"根本格式化不出来"同样处理。
    """
    if isinstance(v, bool) or v is None:
        return None
    try:
        num = float(v)
    except (TypeError, ValueError):
        return None
    return num if math.isfinite(num) else None


def _fmt_money(v: Any) -> str | None:
    """金额 → "¥12.00"；**格式化不出来 → None**（不是字面量"一笔账"）。

    v2.6.0（找茬审查 P2-d）：旧行为是失败时返回字面量"一笔账"，于是确认框正文会写成
    「想把今日预算设成一笔账，可以吗？」——**金额看不见**，而且这条路上不写日志
    （只有 describe_call 的 except 分支才写）。而 validate_args 只查"必填有没有 / 空不空"，
    {"amount": "abc"} 能一路通过校验走到这里。钱相关文案绝不许静默降级成一句看不懂的话：
    返回 None = "这条拼不出来"，由 describe_call 退回**带参数**的保守文案并留痕。
    """
    num = _as_finite_number(v)
    return None if num is None else "¥%.2f" % num


def _describe_manual(args: dict | None) -> str | None:
    note = str((args or {}).get("note") or "").strip()
    money = _fmt_money((args or {}).get("amount"))
    if money is None:
        return None
    return "在账本里记一笔 %s%s" % (money, ("（%s）" % note[:20]) if note else "")


def _describe_budget(args: dict | None) -> str | None:
    money = _fmt_money((args or {}).get("amount"))
    return None if money is None else "把今日预算设成 %s" % money


def _describe_alarm(args: dict | None) -> str | None:
    """闹钟时间：**给了值就必须是字符串**，否则 None（关键值没格式化成功，见 P2-d）。

    值为 None / 缺失照旧显示"？"——那种情况 validate_args 已经拦掉了（"缺少参数 time"），
    这里保留一个看得懂的占位符，不为它多写一条日志。但 {"time": 800} 这种"给了个不是
    字符串的东西"必须退回带参数的保守文案：旧行为 str(800) 硬转后照念「设一个 800 的闹钟」，
    读起来像个正常时间，实际是模型给错了类型。
    """
    label = str((args or {}).get("label") or "").strip()
    tail = ("（%s）" % label[:20]) if label else ""
    raw_time = (args or {}).get("time")
    if raw_time is None:
        return "设一个 ？ 的闹钟%s" % tail
    if not isinstance(raw_time, str):
        return None
    return "设一个 %s 的闹钟%s" % (raw_time.strip() or "？", tail)


def _describe_timer(args: dict | None) -> str | None:
    """时长：**给了值就必须是有限数**，否则 None（见 P2-d）。

    口径与 _describe_alarm 一致：值为 None / 缺失照旧给占位符"一会儿"（validate_args
    已经拦掉），{"minutes": "abc"} / True / nan 这种"给了个不是数字的东西"才退回
    带参数的保守文案——旧行为写死"一会儿"，读起来像个正常时长，把参数畸形藏起来了。
    """
    label = str((args or {}).get("label") or "").strip()
    tail = ("（%s）" % label[:20]) if label else ""
    raw = (args or {}).get("minutes")
    if raw is None:
        return "设一个 一会儿 后的提醒%s" % tail
    num = _as_finite_number(raw)
    if num is None:
        return None
    return "设一个 %g 分钟后的提醒%s" % (num, tail)


_DESCRIBE: dict[str, Callable[[dict | None], str | None]] = {
    "add_manual_record": _describe_manual, "set_budget": _describe_budget,
    "set_alarm": _describe_alarm, "set_timer": _describe_timer}


def _args_preview(args: Any, limit: int = 80) -> str:
    """确认文案的兜底参数摘要（只给用户看）：单行化 + 截断。

    用 json.dumps(default=str) 优先（可读），它自己也会抛（循环引用 / 怪对象），
    所以再退一层 str()。
    v2.6.0（找茬审查 P2-d）：docstring 此前写的是"再退 str()——两条路径都不吞异常"，
    但代码里**只有 json.dumps 一条路**（文案与实现不符）。而且它现在不只被 except 分支
    调用：describe_call 在"关键值没格式化成功"时也走这里——那条路不在异常处理里，
    再抛出去就等于确认框整个打不开。所以真补上这层兜底（宁可摘要难看，不可弹不出框）。
    """
    try:
        text = json.dumps(args if isinstance(args, dict) else {}, ensure_ascii=False, default=str)
    except Exception:
        text = str(args)
    one = " ".join(text.split())
    return one[:limit] + ("…" if len(one) > limit else "")


def describe_call(name: str, args: Any) -> str:
    """工具调用 → 给用户看的一句确认文案（纯函数，可测）。"""
    spec = get_tool(name)
    label = spec.label if spec is not None else str(name or "未知操作")
    fn = _DESCRIBE.get(str(name or ""))
    detail = ""
    if fn is not None:
        try:
            detail = fn(args if isinstance(args, dict) else {})
        except Exception as e:
            # v2.6.0（D7-B ② 改逻辑）：这个函数喂的是**写入前最后一道闸**——桌宠._ask_tool_confirm
            # 拿它当确认框正文（AI 要记账/改预算/设闹钟时先问用户）。旧行为是文案拼不出来就
            # 退回通用问法"想调用「记一笔」，可以吗？"：**用户看不到 AI 到底要写什么**就点了
            # 确认，等于把闸门关掉（而"文案拼不出来"恰恰最容易发生在参数畸形的时候）。
            # 现在退回**带参数的保守文案**（宁可难看，不可看不见），并补一条限流日志。
            pet_log.log_throttled("tools.describe_call",
                                  "确认文案生成失败（已退回带参数的兜底文案）：%r" % (e,))
            detail = "「%s」（%s）" % (label, _args_preview(args))
        if not detail:
            # v2.6.0（找茬审查 P2-d）：**正常路径**也会拼不出关键值——validate_args 只查
            # "必填有没有 / 空不空"，{"amount": "abc"} / {"time": 800} 都能一路通过校验，
            # 走到 _describe_* 才发现格式化不出来。_describe_* 这时返回 None（不再返回
            # "一笔账" / "一会儿"这种"看得见但看不懂"的字面量），这里与异常路径**同一口径**：
            # 退回带参数的保守文案 + 补一条限流日志。宁可难看，不可看不见。
            pet_log.log_throttled("tools.describe_call",
                                  "确认文案里的关键值没格式化成功（已退回带参数的兜底文案）："
                                  "%s %s" % (name, _args_preview(args)))
            detail = "「%s」（%s）" % (label, _args_preview(args))
    return "想%s，可以吗？" % detail if detail else "想调用「%s」，可以吗？" % label


# ---------------- 执行器 ----------------
def execute(name: str, args: Any, ctx: Any, confirmed: bool = False) -> dict:
    """执行一次工具调用，返回结果 dict。**任何异常都吞成 {"ok": False, ...}**，绝不抛出。

    confirmed=False 时写入类工具一律拒绝（needs_confirm=True）：调用方必须要么先经主线程
    问过用户，要么在配置里显式关掉确认（ai_tools_confirm=False）后再带 confirmed=True 重入。
    """
    try:
        spec = get_tool(name)
        if spec is None:
            return {"ok": False, "error": "未知工具：%s" % (name,)}
        if args is None:
            args = {}
        err = validate_args(spec, args)
        if err:
            return {"ok": False, "error": err}
        if not spec.readonly and not confirmed:
            return {"ok": False, "needs_confirm": True,
                    "error": "「%s」会改数据，需要绳匠先确认" % spec.label}
        if not callable(spec.handler):
            return {"ok": False, "error": "工具没有处理器：%s" % spec.name}
        res = spec.handler(dict(args), ctx)
        if not isinstance(res, dict):
            res = {"ok": True, "data": res}
        res.setdefault("ok", True)
        return res
    except Exception as e:
        return {"ok": False, "error": "工具执行失败：%r" % (e,)}


# ---------------- 跨线程凭证（只用 threading，Qt-free） ----------------
class MainThreadCall:
    """worker 线程 → 主线程的一次阻塞调用凭证：worker 建、主线程 resolve、worker 等。"""

    __slots__ = ("id", "name", "args", "result", "event")

    def __init__(self, name: str, args: Any) -> None:
        self.id = uuid.uuid4().hex
        self.name = str(name)
        self.args = args if isinstance(args, dict) else {}
        self.result = {"ok": False, "error": "界面没有响应"}
        self.event = threading.Event()

    def resolve(self, result: Any) -> None:
        """主线程交回结果（非 dict 一律当成功）。"""
        self.result = result if isinstance(result, dict) else {"ok": True}
        self.event.set()

    def wait(self, timeout: float | None = None) -> bool:
        """等主线程执行完；False = 超时（调用方按失败处理）。"""
        return self.event.wait(timeout)


class ToolConfirmRequest:
    """一次写入工具的确认请求：worker 线程建、主线程答。"""

    __slots__ = ("id", "name", "args", "approved", "event")

    def __init__(self, name: str, args: Any) -> None:
        self.id = uuid.uuid4().hex
        self.name = str(name)
        self.args = args if isinstance(args, dict) else {}
        self.approved = False
        self.event = threading.Event()

    def resolve(self, approved: Any) -> None:
        self.approved = bool(approved)
        self.event.set()

    def wait(self, timeout: float | None = None) -> bool | None:
        """True=用户同意，False=用户拒绝，None=超时没回应。"""
        if not self.event.wait(timeout):
            return None
        return bool(self.approved)


class ToolContext:
    """工具执行上下文：**全部能力都是注入的回调**（本模块不认识任何业务模块）。

    - balance() / weather() / ledger()：返回 (ok, dict|错误文案)，在 worker 线程里直接跑
      （网络 / 只读，不碰 Qt）
    - ui(name, args)：投递主线程执行并等结果（表情 / 动作 / 闹钟 / 定时器）
    - ui_async(name, args)：投递主线程执行但不等结果（对话框类：账本 / 记一笔 / 预算）
    - log：出错留痕（可空）
    """

    __slots__ = ("balance", "weather", "ledger", "ui", "ui_async", "log")

    def __init__(self, balance: Callable[[], tuple[Any, Any]] | None = None,
                 weather: Callable[[], tuple[Any, Any]] | None = None,
                 ledger: Callable[[], tuple[Any, Any]] | None = None,
                 ui: Callable[[str, dict], Any] | None = None,
                 ui_async: Callable[[str, dict], Any] | None = None,
                 log: Callable[[str], Any] | None = None) -> None:
        self.balance = balance
        self.weather = weather
        self.ledger = ledger
        self.ui = ui
        self.ui_async = ui_async
        self.log = log
