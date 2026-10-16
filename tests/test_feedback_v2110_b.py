# -*- coding: utf-8 -*-
"""v2.11.0 第 9 轮（代理 B · 第 2 波速胜与交互）：B5 关键信息可见 · B6 错误可操作 · B8 加载进度。

**领地说明**：只覆盖代理 B 的三条（B1/B2/B3/B4/B7 落在 桌宠.py / pet_widgets.py，归代理 A，
本文件一个字都不碰那两个文件）。逐条的"为什么这样做"写在用例 docstring 里：

  · B6（pet_chat.py）：错误提示必须「发生了什么 + 下一步能做什么」。旧版把"服务商回了个看不懂
    的回复"和"我们自己的意外"统统说成"网络不好，听不清啦……"——用户去查网络永远查不出结果。
  · B5（pet_dialogs.py 的 tooltip 行段）：只补**决定成败**的信息，而且关键那句必须**看得见**
    （不是只写进 tooltip）；顺带修一处**指错按钮**的 tooltip（导入向导里没有「保存」）。
  · B8（pet_dialogs.py VoiceDialog）：朗读/重新生成这类 >1s 的操作要有在途与失败反馈——旧版
    入队成功就写"✅ 开始朗读…"，而合成失败只在宠物气泡里说，窗口是 modal 置顶，用户看不到。
  · A2/A3 的菜单接线（pet_menu.py）：A 给配置键与方法，B 接线；勾选状态读**生效值**。

写法沿用仓内套路：offscreen；不 exec() 模态（_warn/_info/_confirm 换记录器）；断言**结构性
事实**（文案里有没有下一步 / 哪个控件可见 / 回调注册了几次），不看耗时（铁律 3）。
"""
import json
import os
import sys
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pet_chat            # noqa: E402
import pet_dialogs         # noqa: E402
import pet_log             # noqa: E402
import pet_resources       # noqa: E402

from PySide6.QtCore import QPoint, QTimer                      # noqa: E402
from PySide6.QtGui import QAction                              # noqa: E402
from PySide6.QtWidgets import (QApplication, QMenu,            # noqa: E402
                               QPushButton)


# ============================================================
# B6：错误可操作（pet_chat.py）—— 假后端、无 Qt、无网络
# ============================================================
class _Sig:
    """最小信号替身：emit 直接同步回调。"""

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
    def __init__(self, payload, status=200, raw_json=None):
        self.status_code = status
        self._payload = payload
        self._raw = raw_json
        self.text = json.dumps(payload, ensure_ascii=False) if raw_json is None else raw_json

    def json(self):
        if self._raw is not None:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._payload


def _make_chat(monkeypatch, responses):
    posts = []
    it = iter(responses)

    def fake_post(url, headers=None, json=None, timeout=None):
        posts.append(json or {})
        return next(it)

    monkeypatch.setattr(pet_chat.requests, "post", fake_post)
    conf = {"api_key": "k", "ai_base_url": "", "ai_model": "m", "ai_reply_len": 60,
            "ai_max_tokens": 60, "chat_memory_rounds": 0, "sound": False,
            "ai_tools_enabled": False, "ai_tools_confirm": True}
    sig = _FakeSignals()
    chat = pet_chat.ChatService(_FakePet(), sig, lambda: conf, lambda c: "人设",
                                lambda t: ("", "", t), lambda: [], lambda h: None,
                                lambda k: None, lambda m: None, 60)
    replies = []
    sig.reply.connect(replies.append)
    return chat, sig, posts, replies


def _assert_actionable(msg, must_have):
    """「可操作」的机械判据：说清了是什么 + 给了一个用户能自己动手的入口。"""
    assert msg, "错误路径一句提示都没给（静默）"
    assert ("下一步" in msg or "去「" in msg or "点「" in msg
            or "再试" in msg or "试试" in msg), \
        "这句错误没有「你现在能做什么」：%r" % (msg,)
    for token in must_have:
        assert token in msg, "这句错误缺了 %r：%r" % (token, msg)


def test_回复结构看不懂_说成服务商回复看不懂并给下一步(monkeypatch):
    """B6 主用例：200 + 缺 choices（服务商回了个看不懂的结构）。

    旧实现：KeyError 落到最外层兜底 → 用户看到"网络不好，听不清啦……"→ 去查网络/路由器，
    而真正的下一步在「AI设置…」（接口地址要 OpenAI 兼容 / 模型名对不对）。
    """
    chat, sig, posts, replies = _make_chat(monkeypatch, [_Resp({})])
    chat._worker("在吗", "k")
    assert replies, "没有任何回复（连兜底都没走）"
    _assert_actionable(replies[-1], ["服务商回复看不懂", "KeyError", "测试连接"])
    assert "网络不好" not in replies[-1], "又把结构问题说成网络问题了：%r" % (replies[-1],)


def test_响应体不是JSON也算服务商回复看不懂(monkeypatch):
    """200 但 body 不是 JSON（网关返回 HTML 登录页）——同样是"回复看不懂"，不是网络不好。"""
    chat, sig, posts, replies = _make_chat(monkeypatch, [_Resp(None, raw_json="<html>hi</html>")])
    chat._worker("在吗", "k")
    assert replies and "服务商回复看不懂" in replies[-1], replies
    _assert_actionable(replies[-1], ["测试连接"])


def test_choices是空表也算回复看不懂(monkeypatch):
    """choices: [] → IndexError（不是 KeyError），同样要归到"回复看不懂"这一句。"""
    chat, sig, posts, replies = _make_chat(monkeypatch, [_Resp({"choices": []})])
    chat._worker("在吗", "k")
    assert replies and "服务商回复看不懂" in replies[-1] and "IndexError" in replies[-1], replies


def test_我们自己的意外不再谎称网络不好(monkeypatch):
    """兜底分支：非网络异常（这里让请求层抛 RuntimeError）必须点名"意外" + 给下一步。

    为什么必须区分：兜底把**本地故障**（磁盘写失败、注入契约不符）也说成网络问题，
    用户永远查不到原因；而 error.log 才是真线索，所以提示里要指名它。
    """
    chat, sig, posts, replies = _make_chat(monkeypatch, [])
    # 注意顺序：_make_chat 自己也会 patch requests.post —— 必须在它之后再压掉才生效
    monkeypatch.setattr(pet_chat.requests, "post",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("disk full")))
    chat._worker("在吗", "k")
    assert replies, "没有任何回复（连兜底都没走）"
    _assert_actionable(replies[-1], ["出了个意外", "RuntimeError", "error.log"])
    assert "网络不好" not in replies[-1], replies[-1]


def test_超时说成过载并给第二条路(monkeypatch):
    """超时那条原来只有"稍后再试"——再试还是超时怎么办？现在给"换模型/换服务商"。"""
    import requests as _rq

    chat, sig, posts, replies = _make_chat(monkeypatch, [])
    monkeypatch.setattr(pet_chat.requests, "post",
                        lambda *_a, **_k: (_ for _ in ()).throw(_rq.exceptions.Timeout("slow")))
    chat._worker("在吗", "k")
    _assert_actionable(replies[-1], ["它想太久了", "AI设置"])


def test_400_422给的是下一步而不是反问():
    """审计口径：错误提示要具体可操作。旧文案是"模型名与接口不兼容？"——一个反问句，
    用户读完不知道自己该干什么。现在指向「AI设置…」的「测试连接」。"""
    msg = pet_chat.explain_api_error(400)
    assert "400" in msg and "422" in msg, msg
    assert "测试连接" in msg, msg
    assert not msg.rstrip().endswith("？"), "还是那个反问句：%r" % (msg,)


def test_404与地区限制都点名去哪儿动手():
    assert "AI设置" in pet_chat.explain_api_error(404)
    assert "服务商" in pet_chat.explain_api_error(403, "country not supported")


def test_新加的错误文案都进了语音跳过表():
    """契约双向：这些句子是**错误**，不能被语音系统当台词念出来（前缀表按前缀匹配）。"""
    for prefix in ("服务商回复看不懂", "出了个意外"):
        assert prefix in pet_chat.API_ERROR_PREFIXES, prefix
    # 反向：explain_api_error 的每一条输出仍然被表覆盖（沿用 test_constants_sync 的口径）
    for st in (401, 402, 403, 404, 429, 500, 418):
        msg = pet_chat.explain_api_error(st)
        assert msg.startswith(pet_chat.API_ERROR_PREFIXES), msg


def test_工具执行失败带上工具名与别重试(monkeypatch):
    """工具异常返回给**模型**（不是气泡），所以"下一步"要写成模型能照做的动作。"""
    chat, sig, posts, replies = _make_chat(monkeypatch, [])
    monkeypatch.setattr(pet_chat.pet_tools, "execute",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    spec = type("S", (), {"readonly": True, "name": "check_balance"})()
    monkeypatch.setattr(pet_chat.pet_tools, "get_tool", lambda name: spec)
    res = chat._run_tool("check_balance", {}, True)
    assert res["ok"] is False
    assert "工具执行失败" in res["error"] and "check_balance" in res["error"], res
    assert "别重试" in res["error"], res

# ============================================================
# 真 PetWindow（照仓内既有夹具）
# ============================================================
def _shutdown_pet(win):
    try:
        win._closing = True
    except Exception:
        pass  # 有意忽略：测试收尾尽力而为
    try:
        win.voice.stop()
    except Exception:
        pass  # 有意忽略：没有语音服务时跳过
    for _t in win.findChildren(QTimer):
        try:
            _t.stop()
        except Exception:
            pass  # 有意忽略：单个定时器停不掉不影响其余
    try:
        win.hide()
        win.close()
        win.deleteLater()
    except Exception:
        pass  # 有意忽略：测试收尾尽力而为


@pytest.fixture(scope="module")
def pet(tmp_path_factory):
    """真 PetWindow + 全部运行时路径指向临时目录（退出时还原进程级全局）。"""
    from PySide6.QtWidgets import QApplication as _QA
    if _QA.instance() is None:
        _QA([])
    import 桌宠 as main
    tmp = tmp_path_factory.mktemp("feedback2110b")
    _snap = (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
             getattr(pet_log, "_data_dir", None), getattr(main, "_redact_key", None),
             getattr(pet_resources, "FRAME_MAX", None))
    main.DATA_DIR = str(tmp)
    main.CONFIG_PATH = str(tmp / "config.json")
    main.USAGE_PATH = str(tmp / "usage.json")
    main.MEMORY_PATH = str(tmp / "memory.json")
    pet_log.set_data_dir(str(tmp))
    win = main.PetWindow()
    yield win
    _shutdown_pet(win)
    QApplication.processEvents()
    (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH,
     main.MEMORY_PATH) = _snap[0], _snap[1], _snap[2], _snap[3]
    pet_log.set_data_dir(_snap[4])
    main.set_redact_key(_snap[5] or "")
    if _snap[6] is not None:
        pet_resources.FRAME_MAX = _snap[6]


@pytest.fixture
def ui(pet, monkeypatch):
    """模态三件套 + 气泡换成记录器（offscreen 下 exec() 会挂死测试进程）。"""
    seen = {"warn": [], "info": [], "confirm": True, "toast": []}
    monkeypatch.setattr(pet_dialogs, "_warn",
                        lambda _p, t, x: seen["warn"].append((str(t), str(x))))
    monkeypatch.setattr(pet_dialogs, "_info",
                        lambda _p, t, x: seen["info"].append((str(t), str(x))))
    monkeypatch.setattr(pet_dialogs, "_confirm", lambda _p, t, x: seen["confirm"])
    monkeypatch.setattr(pet, "show_bubble", lambda text: seen["toast"].append(str(text)))
    return seen


# ============================================================
# B5：tooltip 只补"决定成败"的信息，且关键那句要看得见
# ============================================================
def test_导入向导的添加形态_tooltip_指向本窗口真有的按钮(pet, ui):
    """原状（v2.8.0 P3-6 的通用措辞）："加进下面的列表（先不落盘）；点「保存」才会写进库里。"
    而**导入向导里没有「保存」按钮**——落点是「导入」。tooltip 指着一个不存在的按钮，
    比没有 tooltip 更坏：用户会去找那个按钮。"""
    dlg = pet_dialogs.RoleImportDialog(pet)
    try:
        btns = {b.text(): b for b in dlg.findChildren(QPushButton)}
        tip = btns["＋ 添加形态"].toolTip()
        assert tip == pet_dialogs.BTN_ADD_TIP_IMPORT, tip
        assert "导入" in tip, tip
        assert "保存" not in tip, "又指向不存在的按钮了：%r" % (tip,)
        # 同一句话在窗口里**看得见**（不靠悬停）：向导第一行就说"点「导入」即可"
        texts = " ".join(w.text() for w in dlg.findChildren(pet_dialogs.QLabel))
        assert "点「导入」" in texts, texts
    finally:
        dlg._cleanup()
        dlg.reject()


def test_AI设置的关键信息在窗口里看得见而不是只在tooltip里(pet, ui):
    """v2.10.0 复盘的教训（原话）："关键信息只写在 tooltip 里 = 等于没写"——tooltip 不可发现、
    键盘/触屏没有 hover。这个窗口改的每一项都要点「保存」才生效，"测试连接"只按当前填写的值
    试一次、不改配置——这两句此前**界面上一个字都没有**。

    判据分三层：① 常驻小字存在且说清了"要保存"与"取消/关窗会丢"；② 它在**滚动区之外**
    （和按钮行一样永远看得见，不会被滚走）；③ tooltip 只作补充，不是唯一出口。
    """
    dlg = pet_dialogs.AISettingsDialog(pet)
    try:
        note = dlg._save_note.text()
        assert "保存" in note and "生效" in note, note
        assert "取消" in note and "关窗" in note, note
        assert "测试连接" in note and "不改配置" in note, note
        outer = dlg.layout()
        assert outer is not None and outer.indexOf(dlg._save_note) >= 0, \
            "常驻小字没挂在外层布局上（会被滚动区带走）"
        body = getattr(dlg, "_content_body", None)
        assert body is None or body.layout().indexOf(dlg._save_note) < 0, \
            "常驻小字被放进了滚动区（内容一滚就看不见了）"
        # tooltip 只作补充：三处关键控件都有，但**关键那句在常驻小字里**
        btns = {b.text(): b for b in dlg.findChildren(QPushButton)}
        for label in ("测试连接", "保存", "取消"):
            assert btns[label].toolTip(), "%s 没有 tooltip（补充说明）" % label
        assert "保存" in btns["测试连接"].toolTip(), btns["测试连接"].toolTip()
    finally:
        dlg.hide()
        dlg.reject()


def test_其余对话框没有被铺上tooltip(pet, ui):
    """反面钉子（防"顺手铺满"）：这一轮**只**动了两处——判据是"决定成败"，不是"每个按钮都来
    一条"。这里钉住一个此前零 tooltip 的窗口仍然保持零，免得后来的人把 B5 读成"覆盖率越高越好"。"""
    dlg = pet_dialogs.PhysicsDialog(pet)
    try:
        tips = [b.toolTip() for b in dlg.findChildren(QPushButton)]
        assert tips, "这个窗口一个按钮都没有？夹具坏了"
        assert all(t == "" for t in tips), "被顺手铺上 tooltip 了：%r" % (tips,)
    finally:
        dlg.hide()
        dlg.reject()


# ============================================================
# B8：语音合成的在途 / 失败反馈（VoiceDialog 朗读页）
# ============================================================
def _voice_dialog(pet):
    dlg = pet_dialogs.VoiceDialog(pet)
    dlg.show()
    return dlg


def test_朗读入队后说正在合成而不是已经开播(pet, ui, monkeypatch):
    """>1s 的操作要有在途反馈：入队成功不等于已经在播（首次合成几秒、云端十几秒）。"""
    dlg = _voice_dialog(pet)
    try:
        dlg._line_combo.clear()
        dlg._line_combo.addItem("假台词", "ghost_line")
        monkeypatch.setattr(pet.voice, "speak_line", lambda lid, **k: (True, ""))
        dlg._speak_line()
        text = dlg._play_label.text()
        assert text.startswith("✅"), text
        assert "正在合成" in text, text
        assert dlg._voice_waiting is True, "没有进入「等结果」状态，后面的失败就写不进窗口"
    finally:
        dlg.hide()


def test_合成失败写进窗口并给下一步_且不覆盖别的朗读(pet, ui, monkeypatch):
    """三件事一起钉：
    ① 失败必须出现在**用户正在看的窗口里**（模态置顶时宠物气泡在它后面）；
    ② 文案要给下一步（原则 5）；
    ③ 全局服务的其它朗读事件**不许**覆盖已经写好的结论（"会不会覆盖用户刚看的东西"）。
    """
    dlg = _voice_dialog(pet)
    try:
        dlg._line_combo.clear()
        dlg._line_combo.addItem("假台词", "ghost_line")
        monkeypatch.setattr(pet.voice, "speak_line", lambda lid, **k: (True, ""))
        dlg._speak_line()
        # 模拟合成线程发出来的失败通知（真路径是 pet_voice._emit("error", …) → 转发器）
        pet_dialogs._route_voice_event(pet.voice, "error", "参考音不见了（声音素材被删？）")
        QApplication.processEvents()
        text = dlg._play_label.text()
        assert text.startswith("❌") and "参考音不见了" in text, text
        assert "测试后端" in text and "声音素材" in text, "失败提示没有下一步：%r" % (text,)
        assert dlg._voice_waiting is False, "落定后没退出等结果状态"
        # ③ 别处的朗读读完了 → 不许把这句结论盖掉
        pet_dialogs._route_voice_event(pet.voice, "finished")
        QApplication.processEvents()
        assert "参考音不见了" in dlg._play_label.text(), \
            "别处的朗读事件覆盖了用户刚看到的失败原因：%r" % (dlg._play_label.text(),)
    finally:
        dlg.hide()


def test_朗读成功走完会说读完了_停止后迟到事件不许再写(pet, ui, monkeypatch):
    dlg = _voice_dialog(pet)
    try:
        dlg._line_combo.clear()
        dlg._line_combo.addItem("假台词", "ghost_line")
        monkeypatch.setattr(pet.voice, "speak_line", lambda lid, **k: (True, ""))
        dlg._speak_line()
        pet_dialogs._route_voice_event(pet.voice, "started", "ghost_line")
        QApplication.processEvents()
        assert "正在播放" in dlg._play_label.text(), dlg._play_label.text()
        pet_dialogs._route_voice_event(pet.voice, "finished", "ghost_line")
        QApplication.processEvents()
        assert "读完" in dlg._play_label.text(), dlg._play_label.text()

        # 用户按下「停止」之后，迟到的事件不许把"已停止。"盖掉
        dlg._stop()
        assert dlg._play_label.text() == "已停止。"
        pet_dialogs._route_voice_event(pet.voice, "started", "ghost_line")
        QApplication.processEvents()
        assert dlg._play_label.text() == "已停止。", \
            "迟到事件覆盖了用户刚触发的「已停止。」：%r" % (dlg._play_label.text(),)
    finally:
        dlg.hide()


def test_没发起朗读时别处的事件不许动窗口(pet, ui):
    """反向：宠物自己读日常台词时也会发同样的事件——没在本窗口发起过，就一个字都不许写。"""
    dlg = _voice_dialog(pet)
    try:
        dlg._play_label.setText("（我自己写的内容）")
        pet_dialogs._route_voice_event(dlg._svc, "error", "别的地方朗读失败了")
        QApplication.processEvents()
        assert dlg._play_label.text() == "（我自己写的内容）", dlg._play_label.text()
    finally:
        dlg.hide()


def test_正常路径一次都不许命中语音UI的异常日志(pet, ui, monkeypatch):
    """v2.11.0 第 9 轮（B8 × 静默 except 判定）：A 把 _hook_voice_ui 的两处与 __init__ 的
    connect 失败从「静默 pass」改成 log_throttled —— 那种补日志**只有在真异常出口才对**：
    如果正常路径也会落，就是「每次开语音设置都往 error.log 写一条」，刷屏比静默更坏。

    这条用例把「正常路径零触发」钉成机器判据：开窗口 → 朗读/整段/重新生成/停止 → 路由
    started/finished/error → 关窗，再补一次「先删对话框、再发事件」的 teardown 竞态；
    全程 voice_ui_* 命中必须是 0。它同时是 B8 钩子「happy path 真在工作」的反证：钩子真坏了
    就会走异常出口 → 这里立刻红。
    """
    hits = []
    import pet_log
    orig = pet_log.log_throttled

    def _spy(key, *a, **k):
        if str(key).startswith("voice_ui_"):
            hits.append(str(key))
        return orig(key, *a, **k)

    monkeypatch.setattr(pet_log, "log_throttled", _spy)
    dlg = _voice_dialog(pet)
    try:
        dlg._line_combo.clear()
        dlg._line_combo.addItem("假台词", "ghost_line")
        monkeypatch.setattr(pet.voice, "speak_line", lambda lid, **k: (True, ""))
        dlg._speak_line()
        pet_dialogs._route_voice_event(pet.voice, "started", "ghost_line")
        pet_dialogs._route_voice_event(pet.voice, "finished", "ghost_line")
        pet_dialogs._route_voice_event(pet.voice, "error", "合成失败（假）")
        dlg._speak_dialogue()
        dlg._regen_line()
        dlg._stop()
        QApplication.processEvents()
    finally:
        dlg.hide()
    # teardown 竞态：对话框已删，事件还会来（真路径就是关窗那一刻）
    dead = _voice_dialog(pet)
    dead.hide()
    dead.deleteLater()
    QApplication.processEvents()
    pet_dialogs._route_voice_event(pet.voice, "started", "ghost_line")
    pet_dialogs._route_voice_event(pet.voice, "error", "合成失败（假）")
    QApplication.processEvents()
    assert hits == [], "正常路径/关闭路径命中了语音 UI 的异常日志（会刷 error.log）：%r" % (hits,)


def test_语音事件钩子按服务只挂一次(pet, ui):
    """设计约束的可执行形式：VoiceService 只有 on_*、没有 off_*，
    所以**不许**每个对话框各注册一次（否则开一次窗口泄漏一组回调，且回调捕获已关闭的窗口）。

    判据：挂钩生效后，再开 3 个 VoiceDialog，服务上的回调条数**一条都不涨**。
    """
    svc = pet.voice
    warm = _voice_dialog(pet)          # 第一个窗口负责把钩子挂上（幂等）
    try:
        counts = {k: len(v) for k, v in svc._cbs.items()}
        assert counts.get("error"), "钩子没挂上：error 一个回调都没有"
        more = [_voice_dialog(pet) for _ in range(3)]
        try:
            after = {k: len(v) for k, v in svc._cbs.items()}
            assert after == counts, "每开一个窗口就多注册一组回调：%r -> %r" % (counts, after)
        finally:
            for d in more:
                d.hide()
    finally:
        warm.hide()


# ============================================================
# A2/A3 菜单接线（pet_menu.py；配置键与方法由代理 A 提供）
# ============================================================
def _build_menu(pet, monkeypatch):
    """走真 MenuBuilder.open（真 exec 换成"只捕获就返回"，不阻塞）。"""
    captured = {}

    class _CapMenu(QMenu):
        def exec(self, *_a, **_k):                      # noqa: A003 —— Qt 的名字
            for act in self.findChildren(QAction):
                if act.text() in ("🌊 减少动效", "🔲 高对比度"):
                    captured[act.text()] = act
            return None

    monkeypatch.setattr(pet, "_new_menu", lambda: _CapMenu(pet))
    pet.menu_builder.open(QPoint(10, 10))
    return captured


def test_设置子菜单有两个无障碍开关_勾选状态读生效值(pet, ui, monkeypatch):
    """A2/A3 的菜单接线。

    为什么钉"读生效值"：reduce_motion 的配置值是 auto/on/off 三态，生效值还取决于系统设置。
    直接读配置字符串的话，"auto 且系统开着减少动效"时菜单会显示成未勾选——**界面在说谎**。
    """
    monkeypatch.setattr(pet, "_reduce_motion", lambda: True)
    monkeypatch.setattr(pet, "_high_contrast", lambda: False)
    got = _build_menu(pet, monkeypatch)
    assert set(got) == {"🌊 减少动效", "🔲 高对比度"}, \
        "设置子菜单里没有这两个开关（实际捕获到：%r）" % (sorted(got),)
    rm, hc = got["🌊 减少动效"], got["🔲 高对比度"]
    assert rm.isCheckable() and hc.isCheckable()
    assert rm.isChecked() is True, "生效值 True 却显示未勾选（界面在说谎）"
    assert hc.isChecked() is False, "生效值 False 却显示已勾选"


def test_菜单开关的勾选会调到A的方法(pet, ui, monkeypatch):
    """接线方向：勾/取消 → pet._set_reduce_motion / _set_high_contrast（立即生效由 A 内部负责）。"""
    calls = []
    monkeypatch.setattr(pet, "_set_reduce_motion", lambda on: calls.append(("rm", bool(on))))
    monkeypatch.setattr(pet, "_set_high_contrast", lambda on: calls.append(("hc", bool(on))))
    monkeypatch.setattr(pet, "_reduce_motion", lambda: False)
    monkeypatch.setattr(pet, "_high_contrast", lambda: True)
    got = _build_menu(pet, monkeypatch)
    rm, hc = got["🌊 减少动效"], got["🔲 高对比度"]
    rm.trigger()      # trigger 会翻转勾选并 emit toggled
    hc.trigger()
    assert ("rm", True) in calls, calls
    assert ("hc", False) in calls, calls


def test_无障碍开关在设置子菜单里_不在顶层(pet, ui, monkeypatch):
    """硬约束（A 点出来的）：顶层菜单有 <=18 项断言——开关必须落在「设置…」子菜单里。"""
    captured = {}

    class _CapMenu(QMenu):
        def exec(self, *_a, **_k):                      # noqa: A003
            captured["top"] = [a.text() for a in self.actions() if a.text()]
            for a in self.actions():
                if a.text().startswith("⚙️ 设置"):
                    captured["set"] = [x.text() for x in a.menu().actions() if x.text()]
            return None

    monkeypatch.setattr(pet, "_new_menu", lambda: _CapMenu(pet))
    pet.menu_builder.open(QPoint(10, 10))
    top = captured.get("top") or []
    sub = captured.get("set") or []
    assert len(top) <= 18, "顶层菜单超了 18 项：%d" % (len(top),)
    assert "🌊 减少动效" in sub and "🔲 高对比度" in sub, sub
    assert "🌊 减少动效" not in top and "🔲 高对比度" not in top, top

