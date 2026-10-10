# -*- coding: utf-8 -*-
"""v2.3.0 回归：Function Calling（1.2）——注册表 / 执行器 / 权限分级 / schema / 跨线程凭证。

pet_tools 是 Qt-free 的：这些用例不 import 桌宠、不起 QApplication，纯逻辑可单测。
"""
import json
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import pet_tools  # noqa: E402

# 规格 1.2 的权限分级：只读直接执行 / 写入需用户确认
READONLY = {"check_balance", "check_weather", "open_ledger", "get_ledger_summary",
            "show_emote", "play_action"}
WRITE = {"add_manual_record", "set_budget", "set_alarm", "set_timer"}


class _Ctx:
    """假工具上下文：默认数据源可用，并记录"界面到底有没有被调用"。"""

    def __init__(self, balance=None, weather=None, ledger=None, ui=None, ui_async=None):
        self.balance = balance or (lambda: (True, {"balance": 45.6, "summary": "余额 ¥45.60"}))
        self.weather = weather or (lambda: (True, {"city": "北京", "weather": "北京今天晴",
                                                   "summary": "北京今天晴"}))
        self.ledger = ledger or (lambda: (True, {"today": 3.2, "week": 18.5, "total": 99.9,
                                                 "summary": "今日 ¥3.20"}))
        self.ui_calls = []
        self.async_calls = []
        self.ui = ui or self._ui
        self.ui_async = ui_async or self._ui_async

    def _ui(self, name, args):
        self.ui_calls.append((name, args))
        return {"ok": True, "handled": name}

    def _ui_async(self, name, args):
        self.async_calls.append((name, args))
        return {"ok": True, "opened": True}


def test_registry_structure():
    """注册表结构：每条都有 name / description / JSON schema / handler / readonly 标记。"""
    assert set(pet_tools.TOOLS) == READONLY | WRITE, pet_tools.tool_names()
    for spec in pet_tools.TOOL_SPECS:
        assert spec.name == spec.name.strip() and spec.name
        assert len(spec.description) >= 8, spec.name
        assert callable(spec.handler), spec.name
        assert isinstance(spec.readonly, bool), spec.name
        assert isinstance(spec.parameters, dict), spec.name
        assert pet_tools.TOOLS[spec.name] is spec
    # to_openai 的结构（模型侧看到的形状）
    item = pet_tools.get_tool("set_alarm").to_openai()
    assert item["type"] == "function" and item["function"]["name"] == "set_alarm"
    assert pet_tools.get_tool("不存在") is None


def test_permission_split():
    """权限分级：只读组直接执行，写入组必须 confirmed=True。"""
    assert set(pet_tools.tool_names(readonly=True)) == READONLY
    assert set(pet_tools.tool_names(readonly=False)) == WRITE
    assert set(pet_tools.tool_names()) == READONLY | WRITE


def test_tool_names_unique():
    """工具名不重复；重复/坏项在构建注册表时就报错（不是悄悄覆盖）。"""
    names = [s.name for s in pet_tools.TOOL_SPECS]
    assert len(names) == len(set(names)), "有重名工具：%r" % (names,)
    dup = pet_tools.ToolSpec("x", "说明说明", {}, lambda a, c: {"ok": True}, True)
    with pytest.raises(ValueError):
        pet_tools.build_registry([dup, dup])
    with pytest.raises(ValueError):
        pet_tools.build_registry([dup, "不是 ToolSpec"])


def test_schema_json_serializable():
    """schema 合法：整体 JSON 可序列化；parameters 是 object，required ⊆ properties。"""
    payload = pet_tools.openai_tools()
    assert len(payload) == len(pet_tools.TOOL_SPECS)
    txt = json.dumps(payload, ensure_ascii=False)
    assert json.loads(txt) == payload, "tools 参数不能无损 JSON 往返"
    for item in payload:
        fn = item["function"]
        assert set(fn) == {"name", "description", "parameters"}, fn
        params = fn["parameters"]
        assert params["type"] == "object"
        assert isinstance(params["properties"], dict)
        assert isinstance(params["required"], list)
        assert set(params["required"]) <= set(params["properties"]), fn["name"]
        for prop in params["properties"].values():
            assert prop.get("type") in ("string", "number", "integer",
                                        "boolean", "object", "array"), prop
    # 表情枚举与绘制分支同口径（模型只能点得到的表情）
    kinds = pet_tools.TOOLS["show_emote"].parameters["properties"]["kind"]["enum"]
    assert set(kinds) == set(pet_tools.EMOTE_KINDS) and len(kinds) >= 8


def test_readonly_tools_execute_directly():
    """只读工具直接执行：余额/天气/账本摘要拿数据，打开账本与表情/动作走主线程通道。"""
    ctx = _Ctx()
    assert pet_tools.execute("check_balance", {}, ctx)["balance"] == 45.6
    assert "北京" in pet_tools.execute("check_weather", {}, ctx)["weather"]
    led = pet_tools.execute("get_ledger_summary", {}, ctx)
    assert led["ok"] is True and led["today"] == 3.2 and led["total"] == 99.9
    # 对话框类：只投递（不等结果），所以不能走阻塞通道
    opened = pet_tools.execute("open_ledger", {}, ctx)
    assert opened["ok"] is True and ctx.async_calls == [("open_ledger", {})]
    assert ctx.ui_calls == []
    # 表情/动作：阻塞通道
    assert pet_tools.execute("show_emote", {"kind": "heart"}, ctx)["ok"] is True
    assert ctx.ui_calls[-1] == ("show_emote", {"kind": "heart"})
    assert pet_tools.execute("play_action", {"name": "jump"}, ctx)["ok"] is True
    assert ctx.ui_calls[-1] == ("play_action", {"name": "jump"})


def test_write_tools_refused_without_confirm():
    """写入工具在 confirmed=False（默认）时必须被拒，且**不能**碰界面或业务。"""
    ctx = _Ctx()
    for name, args in (("add_manual_record", {"amount": 38}),
                       ("set_budget", {"amount": 5}),
                       ("set_alarm", {"time": "07:30"}),
                       ("set_timer", {"minutes": 10})):
        res = pet_tools.execute(name, args, ctx)
        assert res["ok"] is False, "%s 没确认就执行了：%r" % (name, res)
        assert res.get("needs_confirm") is True, res
    assert ctx.ui_calls == [] and ctx.async_calls == [], "未确认却动了界面"
    # 用户同意（或配置里关掉确认）后带 confirmed=True 才真正执行
    ok = pet_tools.execute("set_alarm", {"time": "07:30", "label": "起床"}, ctx, confirmed=True)
    assert ok["ok"] is True and ctx.ui_calls[-1] == ("set_alarm", {"time": "07:30", "label": "起床"})
    # 只读工具不受 confirmed 影响
    assert pet_tools.execute("check_balance", {}, ctx, confirmed=False)["ok"] is True


def test_executor_swallows_exceptions():
    """执行器把任何异常都吞成 {"ok": false, ...}，绝不抛到线程外。"""
    def boom():
        raise RuntimeError("数据源炸了")

    res = pet_tools.execute("check_balance", {}, _Ctx(balance=boom))
    assert res["ok"] is False and "数据源炸了" in res["error"], res
    # 提供者返回失败：原样转成错误文案
    ctx2 = _Ctx(weather=lambda: (False, "天气服务开小差了……"))
    assert pet_tools.execute("check_weather", {}, ctx2) == {"ok": False,
                                                            "error": "天气服务开小差了……"}
    # 处理器自身抛异常（用会炸的 handler 临时替换注册表项）
    spec = pet_tools.TOOLS["get_ledger_summary"]
    old = spec.handler
    try:
        spec.handler = lambda args, ctx: 1 / 0
        r = pet_tools.execute("get_ledger_summary", {}, _Ctx())
        assert r["ok"] is False and "工具执行失败" in r["error"], r
    finally:
        spec.handler = old
    # 界面通道抛异常同样兜住
    def boom_ui(name, args):
        raise OSError("界面炸了")

    r2 = pet_tools.execute("show_emote", {"kind": "heart"}, _Ctx(ui=boom_ui))
    assert r2["ok"] is False and "界面炸了" in r2["error"]
    # 未知工具 / 参数不是对象 / 缺必填 / 上下文整个缺失
    assert pet_tools.execute("没这个工具", {}, _Ctx())["ok"] is False
    assert pet_tools.execute("check_balance", "不是对象", _Ctx())["ok"] is False
    miss = pet_tools.execute("set_alarm", {}, _Ctx(), confirmed=True)
    assert miss["ok"] is False and "time" in miss["error"]
    assert pet_tools.execute("check_balance", {}, None)["ok"] is False
    assert pet_tools.execute(None, None, None)["ok"] is False


def test_parse_call_and_result_helpers():
    """tool_calls 解析 / 结果文本 / 参数 JSON / 确认文案（全是纯函数）。"""
    name, args, cid = pet_tools.parse_call(
        {"id": "c1", "function": {"name": "set_alarm", "arguments": '{"time": "07:30"}'}})
    assert (name, cid, args) == ("set_alarm", "c1", {"time": "07:30"})
    assert pet_tools.parse_call({"function": {"name": "x", "arguments": "{坏 JSON"}})[1] is None
    assert pet_tools.parse_call({"function": {"name": "x"}})[1] == {}
    assert pet_tools.parse_call("不是 dict")[0] == ""
    assert pet_tools.parse_call({"function": {"name": "x", "arguments": {"a": 1}}})[1] == {"a": 1}
    # 结果文本：可 JSON 往返 + 超长截断（防 token 爆炸）
    assert json.loads(pet_tools.result_text({"ok": True})) == {"ok": True}
    long_txt = pet_tools.result_text({"ok": True, "big": "x" * 3000})
    assert long_txt.endswith("…(truncated)")
    assert len(long_txt) <= pet_tools.TOOL_RESULT_MAX + 16
    # 参数 JSON 往返；坏值不抛
    assert pet_tools.parse_args(pet_tools.args_json({"a": 1})) == {"a": 1}
    assert pet_tools.parse_args("{坏") == {} and pet_tools.args_json(object()) == "{}"
    # 摘要只认 summary 字段（其余由具体界面自己反馈，避免重复气泡）
    assert pet_tools.summarize({"ok": True, "summary": "余额 ¥45.60"}) == "余额 ¥45.60"
    assert pet_tools.summarize({"ok": True}) == "" and pet_tools.summarize("坏值") == ""
    # 确认文案：把模型给的参数翻成人话
    text = pet_tools.describe_call("set_alarm", {"time": "07:30", "label": "起床"})
    assert "07:30" in text and "起床" in text and text.endswith("可以吗？")
    assert "记一笔" in pet_tools.describe_call("add_manual_record", {"amount": 38, "note": "奶茶"})
    assert pet_tools.describe_call("没这个工具", {})  # 未知工具也不能抛


def test_cross_thread_credentials():
    """跨线程凭证：确认请求三态 + 主线程调用凭证的结果回传。"""
    req = pet_tools.ToolConfirmRequest("set_alarm", {"time": "07:30"})
    assert req.wait(0.01) is None, "没人答复时应当超时（而不是当作同意/拒绝）"
    req.resolve(True)
    assert req.wait(0.1) is True
    req2 = pet_tools.ToolConfirmRequest("set_budget", {})
    req2.resolve(False)
    assert req2.wait(0.1) is False
    assert len({req.id, req2.id}) == 2, "请求 id 必须唯一（worker 与主线程靠它配对）"

    call = pet_tools.MainThreadCall("show_emote", {"kind": "heart"})
    assert call.wait(0.01) is False and call.result["ok"] is False  # 超时=失败兜底
    box = {}

    def _worker_side():
        box["waited"] = call.wait(5)
        box["result"] = call.result

    t = threading.Thread(target=_worker_side, daemon=True)
    t.start()
    call.resolve({"ok": True, "emote": "heart"})
    t.join(5)
    assert box.get("waited") is True and box.get("result") == {"ok": True, "emote": "heart"}
    call.resolve("不是 dict")
    assert call.result == {"ok": True}


def test_tool_context_injection_only():
    """ToolContext 只做注入：缺哪个回调就哪条路失败，不影响其它工具。"""
    ctx = pet_tools.ToolContext(balance=lambda: (True, {"balance": 1.0}))
    assert pet_tools.execute("check_balance", {}, ctx)["ok"] is True
    assert pet_tools.execute("check_weather", {}, ctx)["ok"] is False   # 没注入天气
    assert pet_tools.execute("show_emote", {"kind": "note"}, ctx)["ok"] is False  # 没注入界面

# ---------------- 1.2 核心：ChatService._worker 的工具循环（假后端，无 Qt 无网络） ----------------
class _Sig:
    """最小信号替身：emit 直接同步回调（worker 线程协作在测试里就是同线程调用）。"""

    def __init__(self):
        self.slots = []

    def connect(self, fn):
        self.slots.append(fn)

    def emit(self, *args):
        for fn in list(self.slots):
            fn(*args)


class _FakeSignals:
    def __init__(self):
        for name in ("reply", "reply_ok", "ai_emote", "ai_done", "tool_confirm_required",
                     "tool_call", "tool_ui", "tool_result"):
            setattr(self, name, _Sig())


class _FakePet:
    """ChatService 只用到这几个守卫状态（语义与 PetWindow 一致）。"""

    def __init__(self):
        self._ai_inflight = False
        self._chat_history = []
        self._history_lock = threading.Lock()
        self._mem_epoch = 0


class _Resp:
    def __init__(self, payload, status=200):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload


def _tool_call_msg(name, args, cid="c1"):
    return {"choices": [{"message": {
        "role": "assistant", "content": None,
        "tool_calls": [{"id": cid, "type": "function",
                        "function": {"name": name, "arguments": json.dumps(args)}}]}}]}


def _text_msg(text):
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


def _make_chat(monkeypatch, responses, cfg=None, ctx=None):
    """装配一个 ChatService（假 requests.post + 假信号），返回 (chat, signals, posts, replies)。"""
    import pet_chat

    posts = []
    it = iter(responses)

    def fake_post(url, headers=None, json=None, timeout=None):
        posts.append(json or {})
        return next(it)

    monkeypatch.setattr(pet_chat.requests, "post", fake_post)
    conf = {"api_key": "k", "ai_base_url": "", "ai_model": "m", "ai_reply_len": 60,
            "ai_max_tokens": 60, "chat_memory_rounds": 0, "sound": False,
            "ai_tools_enabled": True, "ai_tools_confirm": True}
    conf.update(cfg or {})
    sig = _FakeSignals()
    chat = pet_chat.ChatService(_FakePet(), sig, lambda: conf, lambda c: "人设",
                                lambda t: ("", "", t), lambda: [], lambda h: None,
                                lambda k: None, lambda m: None, 60, tool_ctx=ctx)
    replies = []
    sig.reply.connect(replies.append)
    return chat, sig, posts, replies


def test_worker_runs_readonly_tool_then_replies(monkeypatch):
    """只读工具在工作线程直接执行，结果作为 role=tool 消息回灌后再请求一轮（≤2 轮）。"""
    ctx = _Ctx()
    chat, sig, posts, replies = _make_chat(
        monkeypatch, [_Resp(_tool_call_msg("check_balance", {})), _Resp(_text_msg("余额还有 45.6 哦~"))],
        ctx=ctx)
    results = []
    sig.tool_result.connect(lambda name, summary: results.append((name, summary)))
    chat._worker("我还有多少钱", "k")
    assert len(posts) == 2, "没有把工具结果回灌给模型（posts=%d）" % len(posts)
    assert "tools" in posts[0] and len(posts[0]["tools"]) == len(pet_tools.TOOL_SPECS)
    fed = posts[1]["messages"][-1]
    assert fed["role"] == "tool" and fed["tool_call_id"] == "c1" and "45.6" in fed["content"]
    assert replies == ["余额还有 45.6 哦~"], replies
    assert results and results[0][0] == "check_balance" and "45.6" in results[0][1]


def test_worker_asks_confirmation_and_reports_refusal(monkeypatch):
    """写入工具必经用户确认：拒绝 → 把"拒绝"作为工具结果回给模型，界面不被调用。"""
    ctx = _Ctx()
    chat, sig, posts, replies = _make_chat(
        monkeypatch,
        [_Resp(_tool_call_msg("set_alarm", {"time": "07:30", "label": "起床"})),
         _Resp(_text_msg("好吧，那就不设了"))],
        ctx=ctx)

    def _refuse(req_id, name, args_json):
        assert name == "set_alarm" and "07:30" in args_json
        assert chat.confirm(req_id, False) is True  # 主线程答复 true=答复被受理

    sig.tool_confirm_required.connect(_refuse)
    chat._worker("帮我设个闹钟", "k")
    fed = posts[1]["messages"][-1]
    assert fed["role"] == "tool" and "拒绝" in fed["content"], fed
    assert ctx.ui_calls == [], "用户拒绝了界面还是被调用了"
    assert replies == ["好吧，那就不设了"], replies


def test_worker_runs_write_tool_after_approval_and_skips_confirm_when_off(monkeypatch):
    """用户同意 → 执行；ai_tools_confirm=False → 不再问用户，直接执行。"""
    ctx = _Ctx()
    chat, sig, posts, replies = _make_chat(
        monkeypatch,
        [_Resp(_tool_call_msg("set_timer", {"minutes": 10})), _Resp(_text_msg("十分钟后叫你"))],
        ctx=ctx)
    sig.tool_confirm_required.connect(lambda rid, n, a: chat.confirm(rid, True))
    chat._worker("十分钟后提醒我", "k")
    assert ctx.ui_calls[-1] == ("set_timer", {"minutes": 10})
    assert replies == ["十分钟后叫你"]

    # 关掉确认：写工具直接执行（不再发确认请求）
    ctx2 = _Ctx()
    chat2, sig2, posts2, _r2 = _make_chat(
        monkeypatch,
        [_Resp(_tool_call_msg("set_timer", {"minutes": 5})), _Resp(_text_msg("好"))],
        cfg={"ai_tools_confirm": False}, ctx=ctx2)
    asked = []
    sig2.tool_confirm_required.connect(lambda *a: asked.append(a))
    chat2._worker("五分钟后提醒我", "k")
    assert asked == [] and ctx2.ui_calls[-1] == ("set_timer", {"minutes": 5})


def test_worker_degrades_for_local_and_unsupported_backends(monkeypatch):
    """不支持 function calling 的后端（本地 Ollama）不发 tools；400/422 自动退化为纯对话。"""
    ctx = _Ctx()
    chat, _sig, posts, replies = _make_chat(
        monkeypatch, [_Resp(_text_msg("本地模式也能聊~"))],
        cfg={"ai_base_url": "http://localhost:11434/v1"}, ctx=ctx)
    chat._worker("在吗", "k")
    assert "tools" not in posts[0], "本地后端不该收到 tools"
    assert replies == ["本地模式也能聊~"]

    # 云端但服务端不认 tools：先带 tools 试一次，400 后去掉 tools 重发
    chat2, _s2, posts2, replies2 = _make_chat(
        monkeypatch, [_Resp({"error": "tools unsupported"}, status=400), _Resp(_text_msg("那就普通聊"))],
        ctx=ctx)
    chat2._worker("在吗", "k")
    assert "tools" in posts2[0] and "tools" not in posts2[1]
    assert replies2 == ["那就普通聊"]


def test_worker_truncates_tool_rounds_and_unknown_tool(monkeypatch):
    """最多 2 轮工具调用；未知工具/坏 JSON 参数不崩，且每个 tool_call 都有对应回答。"""
    ctx = _Ctx()
    chat, _sig, posts, replies = _make_chat(
        monkeypatch,
        [_Resp(_tool_call_msg("check_balance", {}, "c1")),
         _Resp(_tool_call_msg("没这个工具", {}, "c2")),
         _Resp(_tool_call_msg("check_balance", {}, "c3")),   # 第 3 轮：轮数用完，直接用它的正文
         ], ctx=ctx)
    chat._worker("查余额", "k")
    assert len(posts) == 3, "工具轮数没有卡在 %d 轮（posts=%d）" % (pet_tools.MAX_TOOL_ROUNDS,
                                                                   len(posts))
    unknown = posts[2]["messages"][-1]
    assert unknown["role"] == "tool" and "没这个工具" in unknown["content"], unknown
    # 坏 JSON 参数：同样回一条 tool 消息（而不是炸掉整轮）
    chat2, _s2, posts2, _r2 = _make_chat(
        monkeypatch,
        [_Resp({"choices": [{"message": {"content": None, "tool_calls": [
            {"id": "c9", "type": "function",
             "function": {"name": "set_alarm", "arguments": "{坏 JSON"}}]}}]}),
         _Resp(_text_msg("再说一次时间？"))], ctx=ctx)
    chat2._worker("设闹钟", "k")
    assert "合法 JSON" in posts2[1]["messages"][-1]["content"]


def test_marshal_roundtrip_and_timeout():
    """worker → 主线程的 UI 工具通道：能回结果；主线程不回则超时失败（不永久卡住）。"""
    import pet_chat
    ctx = _Ctx()
    chat, sig, _posts, _replies = _make_chat(_NoopMonkey(), [], ctx=ctx)
    sig.tool_call.connect(lambda cid, name, args_json: chat.resolve_call(
        cid, ctx.ui(name, pet_tools.parse_args(args_json))))
    assert chat.marshal("show_emote", {"kind": "heart"}) == {"ok": True, "handled": "show_emote"}
    # 没人应答 → 超时失败
    chat2, _s2, _p2, _r2 = _make_chat(_NoopMonkey(), [], ctx=ctx)
    assert chat2.marshal("show_emote", {"kind": "heart"}, timeout=0.05)["ok"] is False
    # 迟到的结果不会炸（找不到等待方返回 False）
    assert chat2.resolve_call("不存在", {"ok": True}) is False
    assert chat2.confirm("不存在", True) is False
    assert pet_chat is not None


class _NoopMonkey:
    """给 _make_chat 用的"假 monkeypatch"（不需要真正打补丁的用例）。"""

    def setattr(self, obj, name, value):
        setattr(obj, name, value)

