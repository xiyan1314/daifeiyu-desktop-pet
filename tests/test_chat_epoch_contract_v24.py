# -*- coding: utf-8 -*-
"""M3（v2.4 审查）：expect_epoch 兼容判定只查一个 kwarg —— 契约半开。

_accepts_epoch_kwargs 只看 "expect_epoch" 就判 True，而 _save_snapshot 真调用时同时传
expect_epoch= 与 epoch_of= → 只收一个 kwarg 的注入方（含测试替身/第三方注入）抛
TypeError: unexpected keyword argument 'epoch_of' → 被 _worker 末尾的兜底 except 吞掉 →
用户看到"网络不好，听不清啦……"，且本轮记忆不落盘。

护栏：判据 = "两个 kwarg 都在" 或 "有 VAR_KEYWORD 变参"；否则老实走只传 1 个参数的旧口径。
"""
import threading

import pytest

import pet_chat


class _Resp:
    def __init__(self, text):
        self.status_code = 200
        self.text = text

    def json(self):
        return {"choices": [{"message": {"role": "assistant", "content": self.text}}]}


class _Sig:
    def __init__(self):
        self.slots = []

    def connect(self, fn):
        self.slots.append(fn)

    def emit(self, *a):
        for fn in list(self.slots):
            fn(*a)


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


def _chat(saver, signals=None, pet=None):
    return pet_chat.ChatService(
        pet or _FakePet(), signals or _FakeSignals(),
        lambda: {"api_key": "k", "ai_reply_len": 60, "ai_max_tokens": 60,
                 "chat_memory_rounds": 3, "sound": False},
        lambda c: "人设", lambda t: ("", "", t), lambda: [], saver,
        lambda k: None, lambda m: None, 60)


# "参数根本没传"与"传了 None"必须分开：默认值哨兵 + 统一记法
_MISSING = object()
NOT_PASSED = "<未传>"      # 该参数存在，但这次调用没传
NO_PARAM = "<未收到>"      # 该替身根本没有这个参数（走 **kwargs 时才可能被记成真值）


def _rep(v):
    return NOT_PASSED if v is _MISSING else v


def _stub(kind):
    """四种注入替身：只收 expect_epoch / 只收 epoch_of / 两个都收 / 收 VAR_KEYWORD。

    每个替身把"实际收到了什么"记进 seen —— 调用形态（新契约 vs 旧口径）由此可判定，
    而不是只看"没抛异常"。
    """
    seen = []
    if kind == "expect_only":
        def saver(hist, expect_epoch=_MISSING):
            seen.append({"hist": list(hist), "expect_epoch": _rep(expect_epoch),
                         "epoch_of": NO_PARAM})
    elif kind == "epoch_of_only":
        def saver(hist, epoch_of=_MISSING):
            seen.append({"hist": list(hist), "expect_epoch": NO_PARAM,
                         "epoch_of": _rep(epoch_of)})
    elif kind == "both":
        def saver(hist, expect_epoch=_MISSING, epoch_of=_MISSING):
            seen.append({"hist": list(hist), "expect_epoch": _rep(expect_epoch),
                         "epoch_of": _rep(epoch_of)})
    else:  # kwargs
        def saver(hist, **kw):
            seen.append({"hist": list(hist),
                         "expect_epoch": kw.get("expect_epoch", NO_PARAM),
                         "epoch_of": kw.get("epoch_of", NO_PARAM)})
    return saver, seen


KINDS = [("expect_only", False), ("epoch_of_only", False), ("both", True), ("kwargs", True)]

# 走旧口径时，每个替身应当"一个代次 kwarg 都没收到"（默认值必须仍是哨兵）
LEGACY_EXPECT = {
    "expect_only": {"expect_epoch": NOT_PASSED, "epoch_of": NO_PARAM},
    "epoch_of_only": {"expect_epoch": NO_PARAM, "epoch_of": NOT_PASSED},
}


@pytest.mark.parametrize("kind,ok", KINDS)
def test_contract_judgement_requires_both_kwargs(kind, ok):
    """判据：只有一个 kwarg 的注入方必须判 False（旧实现判 True）。"""
    saver, _seen = _stub(kind)
    assert pet_chat._accepts_epoch_kwargs(saver) is ok


@pytest.mark.parametrize("kind,ok", KINDS)
def test_save_snapshot_never_raises_and_takes_the_right_branch(kind, ok):
    """四种替身分别走对分支且都不抛（旧实现下前两种直接 TypeError）。"""
    saver, seen = _stub(kind)
    chat = _chat(saver)
    assert chat._saver_epoch is ok
    snap = [("user", "早"), ("assistant", "早呀")]
    chat._save_snapshot(snap, 7)          # ← 旧实现：只收一个 kwarg 的替身在这里炸
    assert len(seen) == 1
    assert seen[0]["hist"] == snap
    if ok:
        assert seen[0]["expect_epoch"] == 7
        assert seen[0]["epoch_of"] == chat._epoch_now, "新契约必须同时传出代次读取器"
    else:
        # 旧口径：**只传 1 个位置参数**（两个代次 kwarg 一个都没传）
        want = LEGACY_EXPECT[kind]
        assert seen[0]["expect_epoch"] == want["expect_epoch"]
        assert seen[0]["epoch_of"] == want["epoch_of"]


def test_old_rule_would_call_the_one_kwarg_saver_and_raise():
    """反例（能真失败）：旧判据会把只收 expect_epoch 的替身判成"支持"，真调用即 TypeError。

    这条绿 = 上面两条不是恒真护栏：它们挡住的正是审查报告里的真实异常路径。
    """
    def saver(hist, expect_epoch=None):
        return "saved"

    assert pet_chat._accepts_epoch_kwargs(saver) is False       # 新判据
    with pytest.raises(TypeError):
        saver([("user", "x")], expect_epoch=1, epoch_of=lambda: 1)   # 旧判据的调用形态


def test_worker_saves_memory_with_one_kwarg_saver(tmp_path, monkeypatch):
    """端到端：只收 expect_epoch 的注入方下，真实 _worker 必须"正常回复 + 落盘"，
    而不是被兜底 except 变成"网络不好，听不清啦……"（旧实现就是这样）。"""
    monkeypatch.setattr(pet_chat.requests, "post", lambda *a, **kw: _Resp("我在的~"))
    saved = []

    def saver(hist, expect_epoch=None):
        saved.append(list(hist))

    signals = _FakeSignals()
    pet = _FakePet()
    replies = []
    signals.reply.connect(replies.append)
    _chat(saver, signals=signals, pet=pet)._worker("你好", "k")
    assert replies == ["我在的~"], "回复被兜底 except 吞了：%r" % (replies,)
    assert saved, "本轮记忆没落盘（被 TypeError 打断）"
    assert saved[0][-2:] == [("user", "你好"), ("assistant", "我在的~")], saved
    assert pet._chat_history[-2:] == [("user", "你好"), ("assistant", "我在的~")]
