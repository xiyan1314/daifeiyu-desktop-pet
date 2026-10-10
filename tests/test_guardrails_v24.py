# -*- coding: utf-8 -*-
"""v2.4 护栏回归：A（v2.3.0 功能面 6 项端到端）+ B（静态体检新增的 M/P 两项）。

设计要求（上一轮审查抓到过恒真断言）：每条用例都**能真的失败**——
既有"合法输入必须通过"，也有"故意违规必须被检出"，并用**正例对照**排除空转断言
（例如"拒绝没改数据"必须配上"同一条路径带确认真的会改数据"）。
"""
import json
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pet_io  # noqa: E402
import pet_tools  # noqa: E402

# 写入工具（与 pet_tools.TOOL_SPECS 的 readonly 标记同口径）
WRITE_CALLS = (("add_manual_record", {"amount": 38}),
               ("set_budget", {"amount": 5}),
               ("set_alarm", {"time": "07:30"}),
               ("set_timer", {"minutes": 10}))


def _ctx(ui=None, ui_async=None, calls=None):
    """假工具 backend：只读提供者可用；主线程通道记账，可注入副作用。"""
    calls = [] if calls is None else calls

    def _ui(name, args):
        calls.append(("ui", name))
        return ui(name, args) if ui is not None else {"ok": True, "handled": name}

    def _ui_async(name, args):
        calls.append(("ui_async", name))
        return ui_async(name, args) if ui_async is not None else {"ok": True, "opened": True}

    return pet_tools.ToolContext(
        balance=lambda: (True, {"balance": 45.6, "summary": "余额 ¥45.60"}),
        ledger=lambda: (True, {"today": 3.2, "total": 99.9, "summary": "今日 ¥3.20"}),
        ui=_ui, ui_async=_ui_async)


# ---------------- A1/A2：工具权限门控 ----------------

def test_a1_readonly_direct_and_write_gated():
    """A1：只读工具直执行；4 条写入工具未确认必须被拒（ok=False + needs_confirm=True）。"""
    calls = []
    ctx = _ctx(calls=calls)
    for name in ("check_balance", "get_ledger_summary"):
        res = pet_tools.execute(name, {}, ctx, confirmed=False)
        assert res["ok"] is True, (name, res)
    assert pet_tools.execute("check_balance", {}, ctx)["balance"] == 45.6
    assert pet_tools.execute("get_ledger_summary", {}, ctx)["today"] == 3.2
    for name, args in WRITE_CALLS:
        res = pet_tools.execute(name, args, ctx, confirmed=False)
        assert res["ok"] is False and res.get("needs_confirm") is True, (name, res)
    assert calls == [], "未确认的写入动了主线程通道：%r" % (calls,)
    # 正例对照：带 confirmed=True 后必须真的进 handler（否则"没执行"的断言是空转的）
    ok = pet_tools.execute("set_alarm", {"time": "07:30", "label": "起床"}, ctx, confirmed=True)
    assert ok["ok"] is True and calls == [("ui", "set_alarm")], (ok, calls)


def test_a2_refused_writes_keep_ledger_budget_alarms(tmp_path):
    """A2：拒绝路径跑完，账本记录/预算/闹钟内容必须逐字段一致（假界面**真的会写**）。"""
    import pet_alarm
    import pet_book

    book = pet_book.Book(str(tmp_path))
    book.add_manual(12.5, "午饭")
    alarms = pet_alarm.AlarmService(str(tmp_path))
    assert alarms.add("07:30", "起床")[0] is not None, "闹钟没建起来，用例前提不成立"
    cfg = {"budget": 20.0}
    touched = []

    def _mutate(name, args):
        touched.append(name)
        if name == "set_alarm":
            alarms.add("08:00", "漏出来的闹钟")
        return {"ok": True}

    def _mutate_async(name, args):
        touched.append(name)
        if name == "add_manual_record":
            book.add_manual(38.0, "漏出来的账")
        elif name == "set_budget":
            cfg["budget"] = 5.0
        return {"ok": True}

    def _sig():
        return (len(book._ledger["records"]), round(book.total_amount(), 2),
                cfg["budget"], json.dumps(alarms.list(), sort_keys=True, ensure_ascii=False))

    ctx = _ctx(ui=_mutate, ui_async=_mutate_async)
    before = _sig()
    for name, args in WRITE_CALLS:
        res = pet_tools.execute(name, args, ctx, confirmed=False)
        assert res["ok"] is False and res.get("needs_confirm") is True, (name, res)
    assert _sig() == before, "拒绝路径改了数据：%r → %r" % (before, _sig())
    assert touched == [], "拒绝路径碰了界面：%r" % (touched,)
    # 正例对照：同一 ctx 带 confirmed=True 真的会改 → 上面的"没改"才有意义
    pet_tools.execute("set_budget", {"amount": 5}, ctx, confirmed=True)
    pet_tools.execute("add_manual_record", {"amount": 1}, ctx, confirmed=True)
    assert cfg["budget"] == 5.0, "对照组没生效：用例失去意义"
    assert len(book._ledger["records"]) == before[0] + 1, "对照组没写进账本"


# ---------------- A3/A4：AI 上下文与两段记忆 ----------------

def test_a3_ai_context_privacy_switch(tmp_path, monkeypatch):
    """A3：ai_rag_enabled=False 返回空串；True 时摘要里必须出现记账字段与长期记忆。"""
    import pet_log
    import 桌宠 as main

    mem = str(tmp_path / "memory.json")
    monkeypatch.setattr(main, "DATA_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(main, "MEMORY_PATH", mem, raising=False)
    monkeypatch.setattr(pet_log, "_data_dir", str(tmp_path), raising=False)  # 导入 桌宠 会重设日志目录
    main.pet_chat.write_long_term(mem, {"user_name": "小明", "preferences": ["吃辣"]})

    class _Book:
        def today_usage(self):
            return 12.5

        def week_usage(self):
            return 30.0

        def total_amount(self):
            return 99.9

    class _Stub:
        book = _Book()
        _shown_balance = 45.6

    off = main.PetWindow._build_ai_context(_Stub(), {"ai_rag_enabled": False})
    assert off == "", "隐私开关关闭时仍在注入用户数据：%r" % (off,)
    txt = main.PetWindow._build_ai_context(
        _Stub(), {"ai_rag_enabled": True, "city": "北京", "budget": 20.0})
    assert "【用户数据摘要】" in txt and "今日消费" in txt and "北京" in txt, repr(txt)
    assert "【关于绳匠的记忆】" in txt and "小明" in txt and "吃辣" in txt, txt


def test_a4_memory_history_and_long_term_do_not_clobber(tmp_path):
    """A4：history / long_term 互不覆盖往返（真实写入路径），并留一条旧口径反例。"""
    import pet_chat

    p = str(tmp_path / "memory.json")
    pet_chat.write_memory(p, [("user", "你好"), ("assistant", "嗨")], 10)
    pet_chat.write_long_term(p, {"user_name": "小明", "preferences": ["喜欢吃蛋糕"]})
    assert pet_chat.read_memory(p, 10) == [("user", "你好"), ("assistant", "嗨")],         "写 long_term 把 history 冲掉了"
    pet_chat.write_memory(p, [("user", "在吗")], 10)
    lt = pet_chat.read_long_term(p)
    assert pet_chat.read_memory(p, 10) == [("user", "在吗")], "history 往返丢了"
    assert lt["user_name"] == "小明" and lt["preferences"] == ["喜欢吃蛋糕"],         "写 history 把 long_term 冲掉了：%r" % (lt,)
    # 反例对照：旧的"拿着旧 dict 整文件覆盖"口径**确实**会丢 long_term（证明上面不是恒真）
    pet_io.atomic_write_json(p, {"history": []}, indent=None)
    assert pet_chat.read_long_term(p) == pet_chat.sanitize_long_term(None), "覆盖口径没丢 long_term？"
    assert pet_chat.read_memory(p, 10) == []


# ---------------- A5：工具轮数 / 单轮数量封顶 ----------------

class _Sig(object):
    def __init__(self):
        self.slots = []

    def connect(self, fn):
        self.slots.append(fn)

    def emit(self, *args):
        for fn in list(self.slots):
            fn(*args)


class _FakeSignals(object):
    def __init__(self):
        for name in ("reply", "reply_ok", "ai_emote", "ai_done", "tool_confirm_required",
                     "tool_call", "tool_ui", "tool_result"):
            setattr(self, name, _Sig())


class _FakePet(object):
    def __init__(self):
        self._ai_inflight = False
        self._chat_history = []
        self._history_lock = threading.Lock()
        self._mem_epoch = 0


class _Resp(object):
    def __init__(self, payload, status=200):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload


def _multi_call_msg(n, cid_prefix="c"):
    calls = [{"id": "%s%d" % (cid_prefix, i), "type": "function",
              "function": {"name": "get_ledger_summary", "arguments": "{}"}}
             for i in range(n)]
    return {"choices": [{"message": {"role": "assistant", "content": None,
                                     "tool_calls": calls}}]}


def _make_chat(monkeypatch, responses, ctx):
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
    sig = _FakeSignals()
    chat = pet_chat.ChatService(_FakePet(), sig, lambda: conf, lambda c: "人设",
                                lambda t: ("", "", t), lambda: [], lambda h: None,
                                lambda k: None, lambda m: None, 60, tool_ctx=ctx)
    return chat, posts


def test_a5_tool_rounds_and_calls_are_capped(monkeypatch):
    """A5：轮数与单轮数量封顶；**每个** tool_call（含被跳过的）都要有 tool 消息配对。"""
    assert isinstance(pet_tools.MAX_TOOL_ROUNDS, int) and pet_tools.MAX_TOOL_ROUNDS >= 1
    assert isinstance(pet_tools.MAX_CALLS_PER_ROUND, int) and pet_tools.MAX_CALLS_PER_ROUND >= 1
    per = pet_tools.MAX_CALLS_PER_ROUND
    over = per + 2                      # 单轮故意超量 2 个
    responses = [_Resp(_multi_call_msg(over)) for _ in range(10)]
    chat, posts = _make_chat(monkeypatch, responses, _ctx())
    chat._worker("查账本摘要", "k")
    assert len(posts) == pet_tools.MAX_TOOL_ROUNDS + 1,         "工具轮数没有卡在 %d 轮（posts=%d）" % (pet_tools.MAX_TOOL_ROUNDS, len(posts))
    msgs = posts[-1]["messages"]
    asked = [c["id"] for m in msgs if m.get("role") == "assistant"
             for c in (m.get("tool_calls") or [])]
    tool_msgs = [m for m in msgs if m.get("role") == "tool"]
    answered = [m["tool_call_id"] for m in tool_msgs]
    assert asked == answered, "tool_call 与 tool 消息没配对（下一轮会被服务端 400）：%r" % (asked,)
    assert len(answered) == pet_tools.MAX_TOOL_ROUNDS * over, len(answered)
    skipped = [m for m in tool_msgs if "先跳过" in m["content"]]
    assert len(skipped) == pet_tools.MAX_TOOL_ROUNDS * (over - per),         "超量调用没有拿到「跳过」tool 消息：%d" % len(skipped)
    # 负例对照：把单轮上限调大（同一份输入）→ 不该再有"跳过"（证明断言跟着常量走，不是写死）
    monkeypatch.setattr(pet_tools, "MAX_CALLS_PER_ROUND", over)
    chat2, posts2 = _make_chat(monkeypatch, [_Resp(_multi_call_msg(over)) for _ in range(10)],
                               _ctx())
    chat2._worker("查账本摘要", "k")
    tool_msgs2 = [m for m in posts2[-1]["messages"] if m.get("role") == "tool"]
    assert not [m for m in tool_msgs2 if "先跳过" in m["content"]], "上限放大后还在跳过"
    assert len(tool_msgs2) == pet_tools.MAX_TOOL_ROUNDS * over


# ---------------- A6：人设文件优先 ----------------

def test_a6_persona_file_overrides_builtin(tmp_path, monkeypatch):
    """A6：prompts/default.txt 存在就用它（含表情指令），删掉/写空白后回退内置常量。"""
    import pet_log
    import 桌宠 as main

    monkeypatch.setattr(main, "DATA_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(pet_log, "_data_dir", str(tmp_path), raising=False)
    p = tmp_path / "prompts" / "default.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("文件人设：只说好话", encoding="utf-8")
    sysp = main._build_ai_sys_prompt({"ai_persona": "default"})
    assert sysp.splitlines()[0] == "文件人设：只说好话", "人设文件没有生效：%r" % sysp[:40]
    assert main._EMOTE_INSTRUCTION in sysp, "表情指令被一起替换掉了（应拼在人设后面）"
    p.unlink()
    fallback = main._build_ai_sys_prompt({"ai_persona": "default"})
    assert fallback.startswith(main.PERSONA_PRESETS["default"][:12]),         "文件缺失时没有回退内置人设：%r" % fallback[:40]
    assert not fallback.startswith("文件人设")
    p.write_text("   \n", encoding="utf-8")   # 空白文件同样按"没有"处理
    assert main._build_ai_sys_prompt({"ai_persona": "default"}).startswith(
        main.PERSONA_PRESETS["default"][:12]), "空白人设文件没有回退"


# ---------------- B：静态体检新增两项 ----------------

def test_b7_static_signal_arity_check():
    """B7：Signal 声明↔槽参数检查——违规必须报出来，合法/判不了的不能误报。"""
    import _check_static as C

    bad = [("bad_signals.py", '''
from PySide6.QtCore import Signal, QObject
class W(QObject):
    pair = Signal(str, str)
    zero = Signal()
    def _one(self, text):
        pass
    def _zero(self):
        pass
    def wire(self):
        self.pair.connect(self._one)             # 槽收得下多余的 → 待确认（参数被丢弃）
        self.zero.connect(lambda a: a)           # 槽要 1 个、信号给 0 个 → 问题（emit 时 TypeError）
        self.zero.connect(self._zero)            # 合法
        self.pair.connect(lambda a, b: None)     # 合法
        self.pair.connect(local_cb)              # 局部变量：判不了 → 必须跳过
        self.pair.connect(self.deleteLater)      # 内建：判不了 → 必须跳过
''')]
    problems, notes = C.check_signal_arity(bad)
    assert len(problems) == 1, "故意违规没被检出：%r" % (problems,)
    assert "zero" in problems[0] and "lambda" in problems[0], problems[0]
    assert len(notes) == 1 and "pair" in notes[0] and "_one" in notes[0], notes
    # 合法样板：一条都不许报
    good = [("good_signals.py", '''
from PySide6.QtCore import Signal, QObject
class W(QObject):
    pair = Signal(str, str)
    zero = Signal()
    def _two(self, a, b):
        pass
    def _zero(self):
        pass
    def wire(self):
        self.pair.connect(self._two)
        self.zero.connect(self._zero)
        self.pair.connect(lambda a, b: None)
        self.zero.connect(lambda: None)
''')]
    assert C.check_signal_arity(good) == ([], []), C.check_signal_arity(good)
    # 真实仓库：当前 0 问题；且解析器**真的在解析**（否则"0 问题"是失明而不是干净）
    real = C.sources()
    real_p, real_n = C.check_signal_arity(real)
    assert real_p == [] and real_n == [], (real_p, real_n)
    seen = []
    orig = C._slot_arity

    def _spy(slot, fname, funcs, methods):
        res = orig(slot, fname, funcs, methods)
        seen.append(res)
        return res

    C._slot_arity = _spy
    try:
        C.check_signal_arity(real)
    finally:
        C._slot_arity = orig
    # v2.4.1：阈值从 50 提到 116——实测本仓 .connect(...) 共 145 处、其中 116 处能解析成
    # 具体槽（其余是 lambda / 局部函数 / Qt 自带信号，按设计跳过）。阈值远低于真实值，
    # "解析器失明"（比如正则被改坏、sources() 少扫文件）就发现不了；贴着真实值才拦得住。
    # 重测：python -c "import _check_static as C; s=[]; o=C._slot_arity; C._slot_arity=lambda *a:(s.append(o(*a)) or s[-1]); C.check_signal_arity(C.sources()); print(sum(1 for r in s if r is not None), len(s))"
    _n_slots = sum(1 for r in seen if r is not None)
    assert _n_slots >= 116,         "可解析槽数骤降（%d/%d）：检查可能已经失明（重测方法见上面注释）" % (_n_slots, len(seen))


def test_b8_static_thread_write_check():
    """B8：线程目标里的裸写盘/改模块级容器必须报"待确认"；只读/走 pet_io 的不报。"""
    import _check_static as C

    src = '''
import os
import threading
import pet_io
_CACHE = {}
def _flush(path, data):
    with open(path, "w", encoding="utf-8") as f:
        f.write(data)
    os.replace(path + ".tmp", path)
    _CACHE[path] = len(data)
def _worker(n):
    _flush("x.json", str(n))
def _reader(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
def _read_worker(n):
    _reader("y.json")
def _io_worker(n):
    pet_io.atomic_write_json("z.json", {"n": n})
def start():
    threading.Thread(target=_worker, daemon=True).start()
    threading.Thread(target=_read_worker, daemon=True).start()
    threading.Thread(target=_io_worker, daemon=True).start()
'''
    problems, notes = C.check_thread_writes([("thr.py", src)])
    assert problems == [], problems
    joined = "\n".join(notes)
    assert "open(mode='w')" in joined, "open(...,'w') 没被检出：%r" % (notes,)
    assert "os.replace" in joined, "os.replace 没被检出：%r" % (notes,)
    assert "_CACHE[...] = ..." in joined, "模块级容器写入没被检出：%r" % (notes,)
    assert "_reader" not in joined, "只读线程目标被误报：%r" % (notes,)   # 既读又在线程里 ≠ 写盘
    assert "_io_worker" not in joined, "走 pet_io 的线程目标被误报：%r" % (notes,)
    # 真实仓库：当前 0 待确认（真有裸写盘时这里会红 → 提醒改走 pet_io）
    real_p, real_n = C.check_thread_writes(C.sources())
    assert real_p == [] and real_n == [], real_n
