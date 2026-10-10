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
    # 覆盖面统计：把 _slot_arity 换成记账版（**用 *a/**k**，解析器以后加参数不会让这里失联）
    seen = []
    orig = C._slot_arity

    def _spy(*a, **k):
        res = orig(*a, **k)
        seen.append(res)
        return res

    C._slot_arity = _spy
    try:
        C.check_signal_arity(real)
    finally:
        C._slot_arity = orig
    # v2.4.1：阈值从 50 提到 116——实测本仓 .connect(...) 共 145 处候选、其中 116 处能解析。
    # v2.4.1（找茬 M6）：**改成比例**。写死 116 == 当时实测值、余量 0，任何良性重构都会假红。
    # v2.4.2：M 检查补了 guard 包装与局部变量两类解析 → 可解析数 116 → 117（分母不变，
    # 比例 0.800 → 0.807），阈值同步 0.75 → 0.76，仍然留约 5 个百分点余量。
    # 重测：python -c "import _check_static as C; s=[]; o=C._slot_arity; C._slot_arity=lambda *a,**k:(s.append(o(*a,**k)) or s[-1]); C.check_signal_arity(C.sources()); print(sum(1 for r in s if r is not None), len(s))"
    _n_slots = sum(1 for r in seen if r is not None)
    # 分母本身也要有下限：sources() 万一扫成 0 个文件，"0 >= 0" 会让整条断言空转
    assert len(seen) >= 100, "扫描面太窄（%d 处 .connect）：sources() 可能没扫到文件" % len(seen)
    assert _n_slots >= 0.76 * len(seen), \
        "可解析槽比例骤降（%d/%d = %.3f）：检查可能已经失明（重测方法见上面注释）" \
        % (_n_slots, len(seen), _n_slots / float(len(seen)))
    # 反向 tripwire：比例**大涨**（＝解析器开始猜了，例如把内建方法也硬解出签名）同样要人复核，
    # 别让"多解析了几处"悄悄变成误报源。改了扫描面/判据就按实测更新这里的上界并说明原因。
    assert _n_slots / float(len(seen)) <= 0.90, \
        "可解析比例异常偏高（%d/%d = %.3f）：是否开始猜测不可判定的槽？" \
        % (_n_slots, len(seen), _n_slots / float(len(seen)))
    # v2.4.2：新增的两类解析必须在**真仓**真的被用到，否则扩展就是死代码（解析器退化了也测不出来）。
    #   guard 包装实测 25 处、其中 24 处解析得出（pet_widgets.py:235 的 self.hide 是 Qt 自带方法，
    #   签名不在本仓 → 按设计判不了）；局部变量/嵌套 def 实测 1 处（pet_anim.py:152 的 on_frame，
    #   模块级 if __name__ 块里的嵌套 def）。数字变了就按实测改这里，别把断言删掉。
    _funcs, _methods = C._def_index(real)
    _guard = [orig(slot, fname, _funcs, _methods, scopes, lineno)
              for fname, lineno, _sig, slot, scopes in C.iter_slots(real)
              if C._is_guard_wrapper(slot)]
    _guard_ok = sum(1 for r in _guard if r is not None)
    assert len(_guard) >= 5, "真仓几乎找不到 guard 包装槽（%d 处）：扫描面或判据不对" % len(_guard)
    assert _guard_ok >= 0.8 * len(_guard), \
        "guard 包装槽解析率骤降（%d/%d）：解开包装这条扩展可能已失效" % (_guard_ok, len(_guard))
    assert sum(1 for r in seen if r is not None and "local" in r[3]) >= 1, \
        "真仓没有一处走局部变量解析：这条扩展可能已失效（或 pet_anim 冒烟块被删，按实测数改这一行）"


def test_b9_guard_wrapped_slot_is_parsed():
    """B9：guard 包装（guard_slot / _gslot）要**解开**继续解析——里面的签名错必须报出来。

    变异验证：把 _check_static._is_guard_wrapper 改成恒 False（＝回到 v2.4 的"包装一律不
    解析"），本用例必须变红（problems 由 1 变 0）。
    """
    import _check_static as C

    src = '''
from PySide6.QtCore import Signal, QObject
import pet_log


class W(QObject):
    zero = Signal()
    pair = Signal(str, str)

    def _needs_one(self, text):
        pass

    def _zero(self):
        pass

    def wire(self):
        self.zero.connect(pet_log.guard_slot("w.needs_one", self._needs_one))   # 要 1 给 0 → 问题
        self.pair.connect(pet_log.guard_slot("w.zero", self._zero))            # 只收 0 给 2 → 待确认
        self.zero.connect(self._gslot("w.zero2", lambda: None))                # 合法
        self.pair.connect(pet_log.guard_slot("w.two", lambda a, b: None))      # 合法
        self.zero.connect(pet_log.guard_slot("w.hide", self.hide))             # 包内是 Qt 内建 → 跳过
'''
    problems, notes = C.check_signal_arity([("guard_bad.py", src)])
    assert len(problems) == 1, "guard 包装里的签名错没被检出：%r" % (problems,)
    assert "zero" in problems[0] and "_needs_one" in problems[0], problems[0]
    assert "guard" in problems[0], "报告没点明是 guard 包装：%s" % problems[0]
    assert len(notes) == 1 and "pair" in notes[0] and "_zero" in notes[0], notes
    # 包装器收 *args 且转手给 fn（PySide6 6.11.2 实测不替它裁参数）→ 不能套用直接连接那句文案
    assert "丢弃" not in notes[0], "包装槽不该套用「多余参数被丢弃」：%s" % notes[0]

    # 负例对照：不套包装、直接连同一个方法——同样的签名错也必须报（证明上面不是靠包装才报的）
    direct = '''
from PySide6.QtCore import Signal, QObject


class W(QObject):
    zero = Signal()

    def _needs_one(self, text):
        pass

    def wire(self):
        self.zero.connect(self._needs_one)
'''
    dp, _dn = C.check_signal_arity([("direct_bad.py", direct)])
    assert len(dp) == 1 and "_needs_one" in dp[0], "直接连接的对照组没报：%r" % (dp,)


def test_b10_local_variable_slot_is_parsed():
    """B10：局部变量指向的 lambda/方法、嵌套 def 要解析；**有歧义的绑定必须仍旧跳过**。

    变异验证：去掉 _check_static._resolve 里 ast.Name 的局部绑定分支，本用例变红
    （problems 由 2 变 0）。
    """
    import _check_static as C

    src = '''
from PySide6.QtCore import Signal, QObject


class W(QObject):
    zero = Signal()
    pair = Signal(str, str)

    def _needs_one(self, text):
        pass

    def _zero(self):
        pass

    def wire(self):
        _cb = self._needs_one                 # 局部变量指向方法
        self.zero.connect(_cb)                # 要 1 给 0 → 问题
        cb2 = lambda a, b: None               # 局部变量指向 lambda（合法）
        self.pair.connect(cb2)

        def _nested(a):                       # 嵌套 def
            pass

        self.zero.connect(_nested)            # 要 1 给 0 → 问题
        for _lbl, loop_cb in (("x", self._zero), ("y", self._needs_one)):
            self.zero.connect(loop_cb)        # 循环变量：绑定不唯一 → 必须跳过

    def wire2(self):
        dupe = self._zero
        dupe = self._needs_one                # 多次绑定 → 判不了 → 跳过
        self.zero.connect(dupe)
        self.pair.connect(later)              # 绑在使用之后 → 跳过
        later = lambda a, b: None
'''
    problems, notes = C.check_signal_arity([("local_bad.py", src)])
    assert len(problems) == 2, "局部变量/嵌套 def 的签名错没被检出：%r" % (problems,)
    joined = " | ".join(problems)
    assert "_needs_one" in joined and "_nested" in joined, problems
    assert "loop_cb" not in joined and "dupe" not in joined and "later" not in joined, \
        "歧义绑定被猜着解析了（必须跳过）：%r" % (problems,)
    assert notes == [], notes


def test_b11_v242_extensions_are_mutation_verified(monkeypatch):
    """B11（变异验证）：把 v2.4.2 的两处扩展分别**拆掉**，B9/B10 必须真的变红。

    "能失败的测试"不能只靠嘴说：这里在同一个进程里做定向变异再跑一遍同一条用例——
    用例不红就说明它其实是恒绿的（护栏空转）。这也是 v2.4.2 那两处改动的变异证据。
    """
    import _check_static as C

    def _must_fail(tag, name, value, case):
        with monkeypatch.context() as m:
            m.setattr(C, name, value)
            try:
                case()
            except AssertionError:
                return
        raise AssertionError("%s：变异后 %s 仍然全绿（这条护栏是空转的）" % (tag, case.__name__))

    # ① 拆掉 guard 解包（＝回到 v2.4"包装一律不解析"）→ B9 必须红
    _must_fail("guard 解包被拆", "_is_guard_wrapper", lambda node: False,
               test_b9_guard_wrapped_slot_is_parsed)
    # ② 拆掉局部变量解析（作用域表恒空）→ B10 必须红
    _must_fail("局部变量解析被拆", "_scope_table", lambda tree: [],
               test_b10_local_variable_slot_is_parsed)
    # ③ 拆掉 P 的跨模块一层（恒返回 []＝回到 v2.4"只追同文件"）→ B12 必须红
    _must_fail("P 跨模块一层被拆", "_cross_module_bodies", lambda *a, **k: [],
               test_b12_thread_write_follows_one_cross_module_hop)
    # 正例对照：不施加任何变异时三条用例必须是绿的（否则上面的"变红"毫无意义）
    test_b9_guard_wrapped_slot_is_parsed()
    test_b10_local_variable_slot_is_parsed()
    test_b12_thread_write_follows_one_cross_module_hop()


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


def test_b12_thread_write_follows_one_cross_module_hop():
    """B12：P 检查要跨模块追**一层**——线程目标 →（同文件函数）→ 其它模块函数里的裸写盘。

    变异验证：把 _check_static._cross_module_bodies 改成恒返回 []（＝回到 v2.4"只追同文件"），
    本用例必须变红（跨模块那处写盘会漏检）。
    """
    import _check_static as C

    # 被调用的"其它模块"：一个真写盘、一个只读、一个只做**第二层**转发
    writelib = '''
import os


def flush(path, data):
    with open(path, "w", encoding="utf-8") as f:
        f.write(data)


def read_only(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def nested_only(path):
    deep(path)          # 第二层：一层深度设计上**不追**（避免爆炸）


def deep(path):
    os.replace(path + ".tmp", path)
'''
    # 约定的写盘出口：豁免模块（下钻只会把 pet_io 自己的 os.replace 报成"裸写盘"）
    pet_io_like = '''
import os


def atomic_write_json(path, obj):
    os.replace(path + ".tmp", path)
'''
    thr = '''
import threading
import pet_io
import writelib


def _save(path, data):
    writelib.flush(path, data)


def _worker(n):
    _save("x.json", str(n))
    writelib.read_only("y.json")


def _worker_direct(n):
    writelib.flush("d.json", str(n))       # 目标自己直接跨模块 → 同样算一层


def _deep_worker(n):
    writelib.nested_only("z.json")         # 只有第二层写盘 → 设计上不报


def _io_worker(n):
    pet_io.atomic_write_json("q.json", {"n": n})


def start():
    threading.Thread(target=_worker, daemon=True).start()
    threading.Thread(target=_worker_direct, daemon=True).start()
    threading.Thread(target=_deep_worker, daemon=True).start()
    threading.Thread(target=_io_worker, daemon=True).start()
'''
    files = [("thr.py", thr), ("writelib.py", writelib), ("pet_io.py", pet_io_like)]
    problems, notes = C.check_thread_writes(files)
    assert problems == [], problems
    joined = "\n".join(notes)
    assert "_worker " in joined and "writelib.py:" in joined, \
        "跨模块一层的裸写盘没被检出（只追同文件＝漏检）：%r" % (notes,)
    assert "open(mode='w')" in joined, notes
    assert "_worker_direct" in joined, "线程目标自己直接跨模块调用被漏检：%r" % (notes,)
    assert "_deep_worker" not in joined, "追过头了（第二层不该追）：%r" % (notes,)
    assert "_io_worker" not in joined, "豁免模块（pet_io）被下钻误报：%r" % (notes,)
    # 反例对照：把"其它模块"改成**不同名**后仍要报 → 证明报的是真跨模块，不是同文件巧合
    assert joined.count("P? 线程目标") == 2, "待确认条数不对：%r" % (notes,)
