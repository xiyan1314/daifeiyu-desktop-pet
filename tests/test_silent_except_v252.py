# -*- coding: utf-8 -*-
"""v2.6.0（D7-B）静默 except 逐条判定的收口回归。

这一轮把审计工具 B 档（功能性吞咽）**逐条**判定为三选一：①补限流日志 ②改逻辑
③确实该静默（登记进白名单）。本文件钉住三件事：

1. **白名单是数据，而且真的会红**（任务书硬要求 a）：
   - 每个生产路径的静默 except 都必须有归属（白名单条目 or 已补日志）；
   - 未登记的静默 except、失效条目、非法理由码、unreviewed 占位 → 测试红；
   - razor 本身用**合成树**验证过不是空转：新写一个静默 except 一定被报出来，
     同一个 except 补上日志后就不再被报。
2. **每一处 ①/② 改动都有能真失败的用例**（构造触发路径，断言"有日志"或"行为符合预期"），
   并配控制组（正常路径**不许**写日志，否则日志会被噪音淹没）。
3. **A 档保持 0**（数据丢失/用户可见错误被吞）。

口径与数据：_dev/silent_except_whitelist.py · _dev/silent_except_whitelist_summary.json
逐条判定的依据：_dev/silent_except_report_v252.md
"""
import importlib.util
import os
import sys
import types

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import pet_log  # noqa: E402

WL_PATH = os.path.join(HERE, "_dev", "silent_except_whitelist.py")


def _load_wl():
    """按路径加载白名单判定器（它不是包内模块，与审计工具同一套加载方式）。"""
    spec = importlib.util.spec_from_file_location("silent_except_whitelist_v252", WL_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


wl = _load_wl()


@pytest.fixture(autouse=True)
def _clear_throttle():
    """限流表是进程级全局：每条用例前后清空，免得用例之间互相"限流"。"""
    pet_log._THROTTLE_SEEN.clear()
    yield
    pet_log._THROTTLE_SEEN.clear()


@pytest.fixture(scope="module")
def scan():
    """真仓扫描（模块级缓存：审计一次约 1~2 秒）。"""
    return wl.scan_silent()


def _log_text(tmp_path):
    p = tmp_path / "error.log"
    return p.read_text(encoding="utf-8") if p.is_file() else ""


# ================= 1. 白名单 razor =================

def test_a_tier_stays_zero(scan):
    """A 档（数据丢失/用户可见错误被吞）必须为 0——这一轮所有判定都不许把它顶上去。"""
    _entries, findings = scan
    a = [f for f in findings if (not f["nonprod"]) and f["tier"] == "A"]
    assert a == [], "出现 A 档静默 except：%r" % (
        [(f["file"], f["line"], f["reason"]) for f in a],)


def test_every_silent_except_has_an_owner(scan):
    """每个生产路径的静默 except 都要有归属：补了日志（不再静默）或登记进白名单。"""
    entries, _findings = scan
    problems = wl.check(entries, wl.load_whitelist())
    assert problems == [], "静默 except 判定不通过（%d 条）：\n%s" % (
        len(problems), "\n".join(problems))


def test_whitelist_reasons_are_reviewed_and_evidenced():
    """白名单条目：理由码必须来自闭集、不许是 unreviewed 占位，且每条都带源码证据。"""
    data = wl.load_whitelist()
    assert data["entries"], "白名单是空的：razor 会把全仓都判成未登记"
    bad = []
    for e in data["entries"]:
        if e["reason"] not in wl.REASONS:
            bad.append((e["key"], "非法理由码 %r" % (e["reason"],)))
        elif e["reason"] == "unreviewed":
            bad.append((e["key"], "还是 unreviewed 占位"))
        elif not str(e.get("evidence", "")).strip():
            bad.append((e["key"], "缺源码证据"))
        elif int(e.get("count", 0)) < 1:
            bad.append((e["key"], "count < 1"))
    assert bad == [], "白名单里有 %d 条不合格：%r" % (len(bad), bad[:6])


def test_razor_reports_a_new_silent_except(tmp_path):
    """razor 不是空转：合成一棵树，新写的静默 except 必须被报成"未登记"。"""
    (tmp_path / "pet_synth.py").write_text(
        "def f(x):\n"
        "    try:\n"
        "        return int(x)\n"
        "    except Exception:\n"
        "        pass\n", encoding="utf-8")
    entries, _findings = wl.scan_silent(root=str(tmp_path))
    assert entries, "合成树里的静默 except 根本没被扫出来（razor 失效）"
    probs = [p for p in wl.check(entries, wl.load_whitelist()) if "未登记" in p]
    assert probs and "pet_synth.py" in probs[0], "新增静默 except 没有被报出来：%r" % (probs,)
    # 反例对照：同一个 except 补上日志（不再是静默）→ 不该再被报
    (tmp_path / "pet_synth.py").write_text(
        "import pet_log\n\n\n"
        "def f(x):\n"
        "    try:\n"
        "        return int(x)\n"
        "    except Exception as e:\n"
        "        pet_log.log_error('%r' % (e,))\n", encoding="utf-8")
    entries2, _f2 = wl.scan_silent(root=str(tmp_path))
    probs2 = [p for p in wl.check(entries2, wl.load_whitelist()) if "未登记" in p]
    assert probs2 == [], "补了日志的 except 仍被当成静默：%r" % (probs2,)


def test_razor_reports_stale_whitelist_entry(tmp_path):
    """代码改了/删了之后，白名单里的失效条目必须被报出来（否则白名单会越积越脏）。"""
    entries, _findings = wl.scan_silent(root=str(tmp_path))     # 空树
    fake = {"entries": [{"key": "gone.py|f|0123456789", "reason": "cleanup",
                         "evidence": "except Exception: pass", "count": 1}]}
    probs = wl.check(entries, fake)
    assert any("已失效" in p for p in probs), probs


def test_razor_rejects_unreviewed_placeholder(scan):
    """--write 登记的占位（unreviewed）**不许**算绿：必须有人给出真理由。"""
    entries, _findings = scan
    data = wl.load_whitelist()
    data = {"entries": [dict(e) for e in data["entries"]]}
    data["entries"][0]["reason"] = "unreviewed"
    probs = wl.check(entries, data)
    assert any("unreviewed" in p for p in probs), probs


# ================= 2. pet_log.log_throttled（限流口径的单一实现） =================

def test_log_throttled_window_uses_injected_clock(tmp_path):
    """限流判据注入时钟：同一个 key 60s 内只落一条，窗口过后恢复（不依赖机器速度）。"""
    assert pet_log.log_throttled("t.unit", "第一条", gap=60.0, now=1000.0) is True
    assert pet_log.log_throttled("t.unit", "第二条", gap=60.0, now=1030.0) is False
    assert pet_log.log_throttled("t.unit", "第三条", gap=60.0, now=1059.9) is False
    assert pet_log.log_throttled("t.unit", "第四条", gap=60.0, now=1060.0) is True
    txt = _log_text(tmp_path)
    assert "第一条" in txt and "第四条" in txt
    assert "第二条" not in txt and "第三条" not in txt
    # 变异对照：把窗口关成 0 → 刚才被挡的两条必须都落盘（证明"挡住"的确实是限流）
    pet_log._THROTTLE_SEEN.clear()
    assert pet_log.log_throttled("t.unit0", "窗口0-A", gap=0.0, now=2000.0) is True
    assert pet_log.log_throttled("t.unit0", "窗口0-B", gap=0.0, now=2000.0) is True


def test_log_throttled_keys_are_independent(tmp_path):
    """不同 key 各记各的——"按对象限流"不能被写成"全进程一条"（v2.5.0 的 L1 教训）。"""
    assert pet_log.log_throttled("t.a", "A-1", now=10.0) is True
    assert pet_log.log_throttled("t.b", "B-1", now=10.0) is True
    assert pet_log.log_throttled("t.a", "A-2", now=20.0) is False
    txt = _log_text(tmp_path)
    assert "A-1" in txt and "B-1" in txt and "A-2" not in txt


def test_guard_slot_still_throttles_after_refactor(tmp_path):
    """guard_slot 现在走 log_throttled：同一槽连炸两次仍然只记一条，槽本身照跑。"""
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("slot-boom-synth")

    wrapped = pet_log.guard_slot("w.synth.slot", boom)
    assert wrapped() is None and wrapped() is None
    assert len(calls) == 2, "槽被限流误伤（应该每次都照跑）"
    assert _log_text(tmp_path).count("timer slot w.synth.slot failed") == 1, _log_text(tmp_path)


# ================= 3. ① 补限流日志：逐处能真失败 =================

def test_decrypt_secret_failure_is_logged(tmp_path, monkeypatch):
    """①-1 pet_config.decrypt_secret：DPAPI 解密失败不再与"没设过 Key"长得一样。"""
    import pet_config
    monkeypatch.setattr(pet_log, "_data_dir", str(tmp_path))
    assert pet_config.decrypt_secret("dpapi:@@@not-base64@@@") == "", "返回值契约被改了"
    txt = _log_text(tmp_path)
    assert "解密失败" in txt, "解密失败没有留痕：%r" % txt
    # 限流：同一条再炸一次不许刷屏
    pet_config.decrypt_secret("dpapi:@@@not-base64@@@")
    assert _log_text(tmp_path).count("解密失败") == 1, "限流失效（刷屏）"
    # 控制组：没有 dpapi: 前缀（旧版明文）与空值都不许写日志
    before = _log_text(tmp_path)
    assert pet_config.decrypt_secret("plain-key") == "plain-key"
    assert pet_config.decrypt_secret("") == ""
    assert _log_text(tmp_path) == before, "正常路径写了日志"


def test_role_stage_file_failure_is_logged(tmp_path, monkeypatch):
    """①-2 pet_resources.stage_file：复制失败不再只回一个 None（异常原文要留痕）。"""
    import pet_resources
    monkeypatch.setattr(pet_log, "_data_dir", str(tmp_path))
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    # 把 roles 目录位置先占成一个**文件**：makedirs 必炸（真触发路径，不靠 mock）
    (data_dir / "roles").write_text("x", encoding="utf-8")
    lib = pet_resources.RoleLibrary(str(data_dir))
    src = tmp_path / "in.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\n")
    assert lib.stage_file(str(src)) is None
    txt = _log_text(tmp_path)
    assert "暂存失败" in txt, "素材暂存失败没有留痕：%r" % txt
    # 控制组：目录正常时既返回文件名也不写日志
    ok_dir = tmp_path / "okdata"
    ok_dir.mkdir()
    (ok_dir / "roles").mkdir()
    lib2 = pet_resources.RoleLibrary(str(ok_dir))
    name = lib2.stage_file(str(src))
    assert name and name.endswith(".png"), name
    assert _log_text(tmp_path) == txt, "成功路径写了日志"


def test_audio_preview_failure_is_logged(tmp_path, monkeypatch):
    """①-3 pet_audio.preview_file：用户点"试听"没声音时，error.log 要能查到原因。"""
    import pet_audio
    monkeypatch.setattr(pet_log, "_data_dir", str(tmp_path))
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF....WAVEfmt ")

    class _BoomWinsound(object):
        SND_FILENAME = SND_ASYNC = SND_NODEFAULT = SND_NOWAIT = 0

        @staticmethod
        def PlaySound(*a):
            raise RuntimeError("no-audio-device-synth")

    monkeypatch.setattr(pet_audio, "winsound", _BoomWinsound)
    assert pet_audio.preview_file(str(wav)) is False
    txt = _log_text(tmp_path)
    assert "试听失败" in txt and "no-audio-device-synth" in txt, txt
    # 控制组：非 wav（调用方会走 QMediaPlayer 降级）不该写日志
    mp3 = tmp_path / "a.mp3"
    mp3.write_bytes(b"ID3")
    assert pet_audio.preview_file(str(mp3)) is False
    assert _log_text(tmp_path) == txt, "非 wav 路径写了日志（噪音）"


def test_window_preview_audio_failure_is_logged(tmp_path, monkeypatch):
    """①-4 桌宠.preview_audio：两条链路都失败时不再静默（键按文件路径限流）。"""
    import pet_audio
    import 桌宠 as main
    monkeypatch.setattr(main, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(pet_log, "_data_dir", str(tmp_path))
    wav = tmp_path / "b.wav"
    wav.write_bytes(b"RIFF....WAVEfmt ")

    def _boom(_path):
        raise RuntimeError("preview-chain-boom")

    monkeypatch.setattr(pet_audio, "preview_file", _boom)
    stub = types.SimpleNamespace()          # 不需要真窗口：异常在碰 self 之前就抛了
    assert main.PetWindow.preview_audio(stub, str(wav)) is False
    txt = _log_text(tmp_path)
    assert "试听失败" in txt and "preview-chain-boom" in txt, txt
    assert str(wav) in txt, "限流键丢了文件路径（不同文件会互相顶掉）"


def test_persona_file_text_logs_only_for_custom_personas(tmp_path, monkeypatch):
    """①-5 桌宠._persona_file_text：自建人设读不到要留痕；内置预设没有同名文件是正常的。"""
    import 桌宠 as main
    monkeypatch.setattr(main, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(pet_log, "_data_dir", str(tmp_path))
    monkeypatch.setattr(main, "_prompts_dir", lambda: str(tmp_path / "prompts"))
    (tmp_path / "prompts" / "custom").mkdir(parents=True)
    assert main._persona_file_text("file:缺失的人设") is None
    txt = _log_text(tmp_path)
    assert "自建人设" in txt and "缺失的人设" in txt, txt
    before = _log_text(tmp_path)
    assert main._persona_file_text("default") is None   # 内置预设：本来就没有同名文件
    assert _log_text(tmp_path) == before, "内置预设路径写了日志（噪音）：%r" % _log_text(tmp_path)
    # 自建人设存在时正常读出，且不写日志
    p = tmp_path / "prompts" / "custom" / "ok.txt"
    p.write_text("  你是大肥鱼  \n", encoding="utf-8")
    assert main._persona_file_text("file:ok") == "你是大肥鱼"
    assert _log_text(tmp_path) == before


# ================= 4. ② 改逻辑：确认框不许丢细节 =================

def test_describe_call_keeps_args_when_describe_raises(tmp_path, monkeypatch):
    """② pet_tools.describe_call：文案拼不出来时，确认框**不许**退成"看不见参数"的通用问法。

    背景：这个函数喂的是写入类 AI 工具的确认框（桌宠._ask_tool_confirm）。旧行为是
    异常 → detail="" → "想调用「记一笔」，可以吗？"——用户看不到 AI 要写什么就点了确认。
    """
    import pet_tools
    monkeypatch.setattr(pet_log, "_data_dir", str(tmp_path))
    monkeypatch.setitem(pet_tools._DESCRIBE, "add_manual_record",
                        lambda a: (_ for _ in ()).throw(RuntimeError("describe-boom")))
    text = pet_tools.describe_call("add_manual_record", {"amount": 38, "note": "奶茶"})
    assert "38" in text and "奶茶" in text, "确认框退成了看不见参数的通用问法：%r" % text
    assert "记一笔" in text or "add_manual_record" in text, text
    txt = _log_text(tmp_path)
    assert "确认文案生成失败" in txt and "describe-boom" in txt, txt


def test_describe_call_normal_path_is_unchanged(monkeypatch):
    """控制组：正常路径文案逐字不变（既有用例依赖"想设一个 07:30 的闹钟，可以吗？"）。"""
    import pet_tools
    assert pet_tools.describe_call("set_alarm", {"time": "07:30"}) == "想设一个 07:30 的闹钟，可以吗？"
    assert "记一笔" in pet_tools.describe_call("add_manual_record", {"amount": 38})
    assert pet_tools.describe_call("没这个工具", {})   # 未知工具仍旧走通用问法，不抛


# ================= 5. 找茬审查 P2-d：关键值格式化不出来也要"看得见" =================

def test_describe_call_amount_not_a_number_stays_visible(tmp_path, monkeypatch):
    """P2-d：金额不是数值（{"amount": "abc"}）→ 确认框**不许**写成"设成一笔账"。

    validate_args 只查"必填有没有 / 空不空"，所以这种畸形参数能一路走到确认框。
    旧行为：_fmt_money 失败返回字面量"一笔账" → 正文「想把今日预算设成一笔账，可以吗？」
    ——金额看不见，而且这条路上不写日志（只有 except 分支才写）。
    能真失败：把 _fmt_money 改回 return "一笔账" → "一笔账" not in text 那条断言红。
    """
    import pet_tools
    monkeypatch.setattr(pet_log, "_data_dir", str(tmp_path))
    # 控制组：正常金额走原文案、不写日志（别把日志变成常驻噪音）
    assert pet_tools.describe_call("set_budget", {"amount": 50}) == \
        "想把今日预算设成 ¥50.00，可以吗？"
    assert _log_text(tmp_path) == "", "正常路径不该写日志"

    text = pet_tools.describe_call("set_budget", {"amount": "abc"})
    assert "一笔账" not in text, "关键值又被吞成看不懂的字面量：%r" % text
    assert "abc" in text, "参数没露出来（用户看不到 AI 要写什么）：%r" % text
    assert "设今日预算" in text, text
    txt = _log_text(tmp_path)
    assert "确认文案里的关键值没格式化成功" in txt and "set_budget" in txt, txt


def test_describe_call_rejects_bool_and_non_finite_amounts(tmp_path, monkeypatch):
    """P2-d：bool / nan / inf 也不是金额（float(True)==1.0，"nan" 也能 float 成功）。

    断言口径：这里不看"一笔账"——记一笔账这个**工具名**本身就含这三个字（旧文案是
    「在账本里记一笔 一笔账」）。看的是"参数原文有没有露出来"：旧路径只给一句
    「想把…记一笔 一笔账，可以吗？」，连 note 都丢了。
    """
    import pet_tools
    monkeypatch.setattr(pet_log, "_data_dir", str(tmp_path))
    for bad in (True, False, "nan", float("nan"), float("inf"), {"a": 1}, [1]):
        text = pet_tools.describe_call("add_manual_record", {"amount": bad, "note": "奶茶"})
        assert "记一笔 一笔账" not in text, ("关键值又被吞成看不懂的字面量", bad, text)
        assert "奶茶" in text and '"amount"' in text, ("参数没露出来", bad, text)


def test_describe_call_alarm_time_must_be_string(tmp_path, monkeypatch):
    """P2-d：闹钟时间**给了值就必须是字符串** —— 旧行为 str(800) 硬转后照念「设一个 800 的闹钟」。

    能真失败：把 _describe_alarm 里那条 isinstance 判断去掉 → 第二条断言红。
    """
    import pet_tools
    monkeypatch.setattr(pet_log, "_data_dir", str(tmp_path))
    assert pet_tools.describe_call("set_alarm", {"time": "07:30"}) == "想设一个 07:30 的闹钟，可以吗？"
    assert "？" in pet_tools.describe_call("set_alarm", {}), "缺失照旧给占位符（validate_args 已拦）"
    text = pet_tools.describe_call("set_alarm", {"time": 800})
    assert "设一个 800 的闹钟" not in text, "非字符串时间被硬转后当成正常值：%r" % text
    assert "800" in text and "{" in text, text
    assert "关键值没格式化成功" in _log_text(tmp_path)


def test_describe_call_timer_minutes_garbage_stays_visible(tmp_path, monkeypatch):
    """P2-d：时长不是数字 → 不再写死"一会儿"，退回带参数的保守文案。"""
    import pet_tools
    monkeypatch.setattr(pet_log, "_data_dir", str(tmp_path))
    assert pet_tools.describe_call("set_timer", {"minutes": 30}) == "想设一个 30 分钟后的提醒，可以吗？"
    text = pet_tools.describe_call("set_timer", {"minutes": "一会儿", "label": "喝水"})
    assert "设一个 一会儿" not in text, "垃圾时长又被写成看得懂的字面量：%r" % text
    assert '"minutes"' in text and "喝水" in text, text


def test_args_preview_falls_back_when_dumps_raises(tmp_path, monkeypatch):
    """P2-d：_args_preview 的兜底不是摆设——循环引用会让 json.dumps 自己抛。

    docstring 此前宣称"再退 str()，两条路径都不吞异常"，代码里却只有 json.dumps 一条路，
    而它现在不只被 except 分支调用（"关键值没格式化成功"那条路不在异常处理里）。
    能真失败：去掉 _args_preview 里的 except → 这里直接抛 ValueError，红。
    """
    import pet_tools
    monkeypatch.setattr(pet_log, "_data_dir", str(tmp_path))
    d = {}
    d["self"] = d
    out = pet_tools._args_preview(d)
    assert isinstance(out, str) and "self" in out, out
    text = pet_tools.describe_call("set_budget", d)
    assert isinstance(text, str) and text, text


# ============ 1b. v2.6.0 第 4 轮（找茬审查 B-3）：4 个并行改造文件的豁免区必须收口 ============

_FOUR_FORMERLY_DELEGATED = ("pet_dialogs.py", "pet_plugin.py",
                            "pet_plugin_host.py", "pet_plugin_index.py")


def test_四个并行改造文件不再有豁免区(scan):
    """B-3：DELEGATED_FILES 必须为空——这 4 个文件名下的静默 except 已全部纳入判定。

    背景：并行改造期 razor 把这 4 个文件**整个豁免**掉，于是"白名单落成数据 + 新增静默
    except 必须让测试红"这条硬要求在这 4 个文件上根本不成立（在这 4 个文件里新写一个
    except: pass，没有任何用例会红）。而 pet_dialogs.py 是本轮改动最大的 UI 文件
    （+573 行）、pet_plugin_index.py 是全新模块（自身 8 处静默 except）。A/C 停笔后收口。
    能真失败：把任意一个文件名塞回 DELEGATED_FILES → 第一条断言红。
    """
    assert tuple(wl.DELEGATED_FILES) == (), \
        "DELEGATED_FILES 又非空了（这 4 个文件会重新变成 razor 盲区）：%r" % (wl.DELEGATED_FILES,)
    entries, _findings = scan
    per = {}
    for ent in entries.values():
        if ent["file"] in _FOUR_FORMERLY_DELEGATED:
            per[ent["file"]] = per.get(ent["file"], 0) + 1
    for fname in _FOUR_FORMERLY_DELEGATED:
        assert per.get(fname, 0) > 0, "%s 一条静默 except 都没进判定（豁免区又回来了？）" % fname
    # 数字**刻意钉死**：收口当时这 4 个文件共 85 条（豁免期实测 82 条 + 本轮 P2 修复新增 3 条：
    # pet_plugin_host._fp_named_file / pet_plugin_index._file_url_to_path / _accepts_limit）。
    # 代码一动它就会红，逼着改的人回来看一眼"新加的那条有没有理由"——这正是要的效果。
    # v2.9.0 第 7 轮：pet_dialogs.py 50 → 49 —— `RoleEditDialog._add_frame_action` 里那条
    # "导入失败回收残留文件"的静默 except 搬进了 `_StagedActionSink.rollback`（A2 抽公共实现），
    # 同时改成 `pet_log.log_throttled` 留痕（**不新造静默 except**）；其余 3 条新落点也一并留痕，
    # 所以净减 1。razor 本身没放宽：无主的静默 except 仍由 test_every_silent_except_has_an_owner 挡。
    assert per == {"pet_dialogs.py": 49, "pet_plugin.py": 5,
                   "pet_plugin_host.py": 19, "pet_plugin_index.py": 11}, per


@pytest.mark.parametrize("fname", _FOUR_FORMERLY_DELEGATED)
def test_razor_catches_a_new_silent_except_in_the_four_files(tmp_path, fname):
    """B-3 **核心验收**：在这 4 个文件里新写一个静默 except，razor 必须报"未登记"。

    这条就是"豁免区真的没了"的运行时证据（光看 DELEGATED_FILES 是空的还不够——
    万一 is_delegated 被改成恒 True，上面那条用例照样绿）。
    能真失败：is_delegated 改成恒 True，或把文件名塞回 DELEGATED_FILES → 红。
    """
    assert wl.is_delegated({"file": fname}) is False, "%s 又被豁免了" % fname
    (tmp_path / fname).write_text(
        "def f(x):\n"
        "    try:\n"
        "        return int(x)\n"
        "    except Exception:\n"
        "        pass\n", encoding="utf-8")
    entries, _findings = wl.scan_silent(root=str(tmp_path))
    assert entries, "%s 里的静默 except 根本没被扫出来（razor 在这 4 个文件上仍有盲区）" % fname
    probs = [p for p in wl.check(entries, wl.load_whitelist()) if "未登记" in p]
    assert probs and fname in probs[0], "新增静默 except 没被报出来：%r" % (probs,)
