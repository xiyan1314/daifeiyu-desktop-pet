# -*- coding: utf-8 -*-
"""v2.3.1 读侧愈合口径一致性收口回归（本轮）。

覆盖四件事（每条都对着一个**能真失败**的旧行为）：
1. 读侧愈合口径统一——pet_voice 的 _load_state/_load、pet_book 的 _read_json 以前
   "读到坏文件只返回默认值"（不愈合、不打日志，坏文件每次启动重报），现在与
   alarms/behaviors/lines/索引同口径：**真损坏才回写愈合 + 愈合前留 .bak + 记日志**；
   而"文件在磁盘上但这次读不到（OSError/非 UTF-8）"**一个字节都不写**。
2. 嵌套类型损坏（P2）——{"history": {...}} / {"clips": [...]} 这类"顶层对象、内层类型错"
   以前静默返回空、无日志、不愈合；现在可检出 + 记一行日志，且只对**能被归一化安全
   重建**的字段愈合（留 .bak），重建不了的只记日志（别把用户手写的绑定删掉）。
3. pet_io 收尾：.bak 固定单份不增殖（覆盖旧备份时记日志）、临时名带进程号且
   clean_tmp_files 同步放宽、_MergeGuard 真变参（此前只认前两把锁）。
4. _check_release.py 的"用户数据"判据从精确名改成**名字模式**，使
   "<名字>.<进程号>.<线程号>.tmp" / "<名字>.bak" 这类残留**在绿色版目录与发布包里
   都被点名**；AUDIO_MAGICS 不得有多余/不可达项。

全部纯逻辑（Qt-free），可离线跑。
"""
import json
import os
import threading
import zipfile

import pytest

import _check_release as chk
import pet_book
import pet_chat
import pet_io
import pet_voice

# 模块导入时抓一份真 open：_deny_open 会替换 builtins.open 来模拟"应用读不到"，
# 但**测试自己检查磁盘**不该被这个注入挡住（否则断言写不出来）。
_REAL_OPEN = open


def _text(path):
    with _REAL_OPEN(str(path), "r", encoding="utf-8") as f:
        return f.read()


def _bytes(path):
    with _REAL_OPEN(str(path), "rb") as f:
        return f.read()


def _json(path):
    return json.loads(_text(path))


def _deny_open(monkeypatch, suffix, times=None):
    """让 builtins.open 对某个后缀的文件打不开（None=一直打不开），其余路径照常。

    模拟杀软/索引器/残留句柄造成的**持续**共享冲突（times=None），与 test_io_v231 同款。
    """
    import builtins
    real_open = builtins.open
    state = {"n": 0}

    def fake_open(file, *a, **kw):
        if str(file).endswith(suffix):
            state["n"] += 1
            if times is None or state["n"] <= times:
                raise PermissionError(13, "Permission denied")
        return real_open(file, *a, **kw)

    monkeypatch.setattr(builtins, "open", fake_open)
    return state


# ---------------- 3. pet_io：.bak 生命周期 / 临时名进程号 / _MergeGuard ----------------

def test_tmp_name_carries_pid_and_tid(tmp_path, monkeypatch):
    """P3-5：临时名必须是 "<path>.<进程号>.<线程号>.tmp"（同机多实例/调试双开不撞名）。

    只带线程号挡不住跨进程撞名：两个进程的线程号完全可能相同，抢同一个 tmp 会互相截断。
    旧断言是 "x.json.<tid>.tmp" → 这条会红。
    """
    p = str(tmp_path / "x.json")
    seen = []
    real_replace = os.replace

    def spy(src, dst):
        seen.append(os.path.basename(src))
        return real_replace(src, dst)

    monkeypatch.setattr(pet_io.os, "replace", spy)
    assert pet_io.atomic_write_json(p, {"a": 1}) is None
    assert seen == ["x.json.%d.%d.tmp" % (os.getpid(), threading.get_ident())], seen
    assert _json(p) == {"a": 1}


def test_clean_tmp_files_covers_new_and_old_tmp_shapes(tmp_path):
    """P3-5：白名单要覆盖三种形状（固定名 / 线程号 / 进程号+线程号），其它文件一律不碰。"""
    target = tmp_path / "lines.json"
    target.write_text("{}", encoding="utf-8")
    doomed = ["lines.json.tmp",                                  # v2.3.0 之前的固定名
              "lines.json.12345.tmp",                            # v2.3.0/2.3.1 早期：线程号
              "lines.json.%d.%d.tmp" % (os.getpid(), threading.get_ident())]  # 现行：进程+线程
    keep = ["lines.json.bak", "lines.json.abc.tmp", "lines.json.v2.tmp",
            "lines.json.1.2.3.tmp",      # 三段数字：不在白名单（只认 ≤2 段）
            "other.json.1.2.tmp"]        # 别的目标
    for n in doomed + keep:
        (tmp_path / n).write_text("x", encoding="utf-8")
    removed = pet_io.clean_tmp_files((str(target),), log=lambda m: None)
    assert removed == len(doomed), removed
    for n in doomed:
        assert not (tmp_path / n).exists(), "该清的临时文件没清：%s" % n
    for n in keep:
        assert (tmp_path / n).exists(), "清扫动了白名单外的文件：%s" % n


def test_merge_guard_really_holds_every_lock():
    """P3-4：_MergeGuard 此前只 acquire 前两把锁，第 3 把被**静默忽略**（等于没锁）。"""
    a, b, c = threading.Lock(), threading.Lock(), threading.Lock()
    with pet_io._MergeGuard(a, b, c):
        for name, lk in (("a", a), ("b", b), ("c", c)):
            assert not lk.acquire(blocking=False), "%s 没有被真正持有" % name
    for name, lk in (("a", a), ("b", b), ("c", c)):
        assert lk.acquire(blocking=False), "%s 退出时没有释放" % name
        lk.release()


def test_merge_guard_rolls_back_when_a_later_acquire_fails():
    """P3-4 反面：第 3 把锁 acquire 失败时，前面两把必须**还回去**（否则永久占锁）。"""
    class _Boom(object):
        def __init__(self):
            self.acquires = 0

        def acquire(self):
            self.acquires += 1
            raise RuntimeError("锁坏了")

        def release(self):
            pass

    first, second, boom = threading.Lock(), threading.Lock(), _Boom()
    with pytest.raises(RuntimeError):
        with pet_io._MergeGuard(first, second, boom):
            pass          # 旧实现根本不会碰第 3 把锁 → 这里不抛 → 用例红
    assert boom.acquires == 1
    assert first.acquire(blocking=False), "中途失败没把第一把锁还回去"
    assert second.acquire(blocking=False), "中途失败没把第二把锁还回去"
    first.release()
    second.release()


def test_backup_before_heal_keeps_single_bak_and_logs_overwrite(tmp_path):
    """P3-4：.bak 固定单份（反复愈合不增殖成 .bak.1/.bak.2…），覆盖旧备份时记一行日志。"""
    p = tmp_path / "ledger.json"
    logs = []
    p.write_text('{"v": 1', encoding="utf-8")
    assert pet_io.backup_before_heal(str(p), logs.append) is True
    first = _bytes(tmp_path / "ledger.json.bak")
    p.write_text('{"v": 2', encoding="utf-8")
    assert pet_io.backup_before_heal(str(p), logs.append) is True
    baks = sorted(n for n in os.listdir(str(tmp_path)) if n.endswith(".bak"))
    assert baks == ["ledger.json.bak"], baks
    assert _bytes(tmp_path / "ledger.json.bak") != first, "旧备份没被本次覆盖"
    assert _text(tmp_path / "ledger.json.bak") == '{"v": 2'
    assert any("覆盖" in m for m in logs), logs


# ---------------- 1. pet_voice：读侧愈合口径 ----------------

def test_voice_launcher_state_corrupt_heals_with_bak(tmp_path):
    """P1-1：坏 voice_backend.json 以前"不愈合也不打日志" → 现在 .bak + 回写 {} + 记日志。"""
    p = tmp_path / "voice_backend.json"
    p.write_text('{"pid": 1234', encoding="utf-8")
    logs = []
    ln = pet_voice.VoiceLauncher(str(tmp_path), log=logs.append)
    assert ln.pid() == 0 and ln.is_running() is False
    assert _text(tmp_path / "voice_backend.json.bak") == '{"pid": 1234'
    assert _json(p) == {}
    assert any("解析失败" in m for m in logs), logs


def test_voice_launcher_state_read_failure_writes_nothing(tmp_path, monkeypatch):
    """P1-1 反面：读不到（OSError）不等于损坏 → 一个字节都不写、也不留 .bak。"""
    p = tmp_path / "voice_backend.json"
    raw = b'{"pid": 4321, "create_time": 1.0}'
    p.write_bytes(raw)
    logs = []
    with monkeypatch.context() as m:
        _deny_open(m, "voice_backend.json")
        ln = pet_voice.VoiceLauncher(str(tmp_path), log=logs.append)
        assert ln.pid() == 0, "读不到就是读不到：内存按空状态继续"
        assert _bytes(p) == raw, "读失败被当成损坏，回写覆盖了原文件"
        assert not (tmp_path / "voice_backend.json.bak").exists(), "没有回写就不该有 .bak"
    assert any("读取失败" in m for m in logs), logs


def test_voice_index_corrupt_heals_with_bak(tmp_path):
    """P1-1：坏 voice.json 以前静默返回空表（无日志、不愈合）→ 现在 .bak + 合法空结构。"""
    idx = tmp_path / "voice.json"
    idx.write_text("{{{ not json", encoding="utf-8")
    logs = []
    svc = pet_voice.VoiceService(str(tmp_path), lambda: {}, lambda p: None, log=logs.append)
    assert svc._clips == {}
    assert _text(tmp_path / "voice.json.bak") == "{{{ not json"
    assert _json(idx) == {"version": 2, "clips": {}}, "坏文件没有愈合回写"
    assert any("解析失败" in m for m in logs), logs


def test_voice_index_read_failure_writes_nothing(tmp_path, monkeypatch):
    """P1-1 反面：voice.json 读不到 → 不愈合、不留 .bak；下次读得动时绑定还在。"""
    idx = tmp_path / "voice.json"
    raw = json.dumps({"version": 2, "clips": {"reply": "c.wav"}}).encode("utf-8")
    idx.write_bytes(raw)
    logs = []
    with monkeypatch.context() as m:
        _deny_open(m, "voice.json")
        svc = pet_voice.VoiceService(str(tmp_path), lambda: {}, lambda p: None, log=logs.append)
        assert svc._clips == {}
        assert _bytes(idx) == raw, "读失败被当成损坏，回写覆盖了原文件"
        assert not (tmp_path / "voice.json.bak").exists(), "没有回写就不该有 .bak"
    assert any("读取失败" in m for m in logs), logs
    svc2 = pet_voice.VoiceService(str(tmp_path), lambda: {}, lambda p: None, log=logs.append)
    assert svc2._clips == {"reply": "c.wav"}, "绑定被读失败路径弄丢了"


def test_voice_index_missing_file_is_not_created(tmp_path):
    """反面：首次运行（文件不存在）不是损坏 —— 只读路径不得凭空空造一个 voice.json。"""
    svc = pet_voice.VoiceService(str(tmp_path), lambda: {}, lambda p: None,
                                 log=lambda m: None)
    assert svc._clips == {}
    assert not (tmp_path / "voice.json").exists()
    assert not (tmp_path / "voice.json.bak").exists()


def test_voice_index_valid_file_is_not_rewritten(tmp_path):
    """反面：合法 voice.json 读一遍必须**逐字节不动**（读侧不许有副作用）。"""
    idx = tmp_path / "voice.json"
    original = '{"version": 2, "clips": {"reply": "a.wav", "poke": "b.mp3"}, "future": 7}'
    idx.write_text(original, encoding="utf-8")
    svc = pet_voice.VoiceService(str(tmp_path), lambda: {}, lambda p: None,
                                 log=lambda m: None)
    assert svc._clips == {"reply": "a.wav", "poke": "b.mp3"}
    assert _text(idx) == original
    assert not (tmp_path / "voice.json.bak").exists()


# ---------------- 2. P2：嵌套类型损坏（可检出 + 记日志 + 能安全重建才愈合） ----------------

def test_voice_index_nested_clips_type_healed_keeps_other_keys(tmp_path):
    """P2：{"clips": [...]}（顶层对象、内层类型错）以前静默空表 → 现在检出 + 愈合 + .bak。

    同时钉住"未知顶层键不许被读侧回写删掉"（未来版本加的字段）。
    """
    idx = tmp_path / "voice.json"
    original = '{"version": 2, "clips": [1, 2], "future_key": 7}'
    idx.write_text(original, encoding="utf-8")
    logs = []
    svc = pet_voice.VoiceService(str(tmp_path), lambda: {}, lambda p: None, log=logs.append)
    assert svc._clips == {}
    assert _text(tmp_path / "voice.json.bak") == original
    assert _json(idx) == {"version": 2, "clips": {}, "future_key": 7}
    assert any("clips" in m for m in logs), logs


def test_voice_index_unknown_entries_logged_without_rewrite(tmp_path):
    """P2 的另一半：条目级问题**只记日志不重写**——那可能是用户手写的 .ogg/.m4a 绑定，
    重写会把它永久删掉（旧实现的毛病是"静默"丢，不是"不删"）。"""
    idx = tmp_path / "voice.json"
    original = json.dumps({"version": 2,
                           "clips": {"reply": "c.wav", "unknown_event": "b.wav",
                                     "poke": "d.ogg"}}, ensure_ascii=False)
    idx.write_text(original, encoding="utf-8")
    logs = []
    svc = pet_voice.VoiceService(str(tmp_path), lambda: {}, lambda p: None, log=logs.append)
    assert set(svc._clips) == {"reply"}
    assert _text(idx) == original, "条目级问题不该重写整个文件"
    assert not (tmp_path / "voice.json.bak").exists()
    assert any("忽略" in m for m in logs), logs


def test_memory_nested_history_type_healed_with_bak(tmp_path):
    """P2：{"history": {...}} 以前静默返回 []、无日志、不愈合 → 现在日志 + .bak + 重建，
    **long_term 与未知键都要原样活下来**（朴素地回写空结构会把用户偏好全清掉）。"""
    p = tmp_path / "memory.json"
    original = json.dumps({
        "history": {"0": ["user", "你好"]},
        "long_term": {"user_name": "小鱼", "nicknames": ["阿鱼"]},
        "future_key": 7,
    }, ensure_ascii=False)
    p.write_text(original, encoding="utf-8")
    logs = []
    assert pet_chat.read_memory(str(p), 10, log=logs.append) == []
    assert _text(tmp_path / "memory.json.bak") == original
    healed = _json(p)
    assert healed["history"] == []
    assert healed["long_term"]["user_name"] == "小鱼", "愈合把长期记忆清掉了"
    assert healed["long_term"]["nicknames"] == ["阿鱼"]
    assert healed["future_key"] == 7, "未知顶层键被读侧回写删掉了"
    assert any("history" in m for m in logs), logs
    assert "\n" not in _text(p), "memory.json 是紧凑单行格式，愈合不许改格式（L2）"
    # 再读一次：文件已经干净 → 不应该再写（幂等，不反复备份）
    before = _bytes(p)
    assert pet_chat.read_memory(str(p), 10, log=logs.append) == []
    assert _bytes(p) == before


def test_memory_nested_long_term_type_healed_keeps_history(tmp_path):
    """P2 反面：long_term 类型错 → 重建 long_term，但 history 里能用的对话**一条都不能丢**。"""
    p = tmp_path / "memory.json"
    original = json.dumps({"history": [["user", "你好"], ["assistant", "在的"]],
                           "long_term": ["坏类型"]}, ensure_ascii=False)
    p.write_text(original, encoding="utf-8")
    logs = []
    assert pet_chat.read_memory(str(p), 10, log=logs.append) == [("user", "你好"),
                                                                ("assistant", "在的")]
    assert _text(tmp_path / "memory.json.bak") == original
    healed = _json(p)
    assert healed["history"] == [["user", "你好"], ["assistant", "在的"]]
    assert isinstance(healed["long_term"], dict) and healed["long_term"]["user_name"] == ""
    assert any("long_term" in m for m in logs), logs


def test_memory_valid_file_is_not_rewritten(tmp_path):
    """反面：合法 memory.json 读一遍逐字节不动（读侧无副作用，不产生 .bak）。"""
    p = tmp_path / "memory.json"
    original = json.dumps({"history": [["user", "早"]],
                           "long_term": {"user_name": "小鱼"}}, ensure_ascii=False)
    p.write_text(original, encoding="utf-8")
    assert pet_chat.read_memory(str(p), 10, log=lambda m: None) == [("user", "早")]
    assert _text(p) == original
    assert not (tmp_path / "memory.json.bak").exists()


def test_memory_read_failure_writes_nothing(tmp_path, monkeypatch):
    """反面（P0-B 同款保护）：memory.json 读不到 → 不愈合、不写、不留 .bak。"""
    p = tmp_path / "memory.json"
    raw = json.dumps({"history": [["user", "别删我"]]}, ensure_ascii=False).encode("utf-8")
    p.write_bytes(raw)
    logs = []
    with monkeypatch.context() as m:
        _deny_open(m, "memory.json")
        assert pet_chat.read_memory(str(p), 10, log=logs.append) == []
        assert _bytes(p) == raw, "读失败被当成损坏，回写覆盖了原文件"
        assert not (tmp_path / "memory.json.bak").exists()
    assert any("读取失败" in m for m in logs), logs


def test_memory_missing_file_is_not_created(tmp_path):
    """反面：首次运行（文件不存在）不是损坏 → 只读路径不得凭空造 memory.json。"""
    p = tmp_path / "memory.json"
    assert pet_chat.read_memory(str(p), 10, log=lambda m: None) == []
    assert not p.exists()
    assert not (tmp_path / "memory.json.bak").exists()


# ---------------- 1/2. pet_book：_read_json 愈合 + 内层类型记日志 ----------------

def test_book_corrupt_ledger_heals_with_bak(tmp_path):
    """P1-2：坏 ledger.json 以前只靠 __init__ 末尾的 _save_all 间接自愈（**没有 .bak**）。"""
    p = tmp_path / "ledger.json"
    p.write_text("{{{ not json", encoding="utf-8")
    b = pet_book.Book(str(tmp_path))
    assert b.all_records() == []
    assert _text(tmp_path / "ledger.json.bak") == "{{{ not json"
    assert _json(p)["records"] == [], "坏账本没有愈合回写"


def test_book_corrupt_archive_heals_with_bak(tmp_path):
    """P1-2：归档文件同口径（坏 ledger_archive.json 也要留 .bak 再重建）。"""
    p = tmp_path / "ledger_archive.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")     # 顶层类型非法
    pet_book.Book(str(tmp_path))
    assert _text(tmp_path / "ledger_archive.json.bak") == "[1, 2, 3]"
    assert _json(p)["days"] == {}, "顶层类型非法的归档没有愈合回写"


def test_book_read_failure_writes_nothing_and_no_bak(tmp_path, monkeypatch):
    """P1-2 反面（P0-B 保护必须原样有效）：账本读不到 → 不写、不备份、下一次写再落盘。"""
    p = tmp_path / "ledger.json"
    pet_book.Book(str(tmp_path)).add_manual(12.5, "午饭")
    raw = _bytes(p)
    with monkeypatch.context() as m:
        _deny_open(m, "ledger.json")
        b = pet_book.Book(str(tmp_path))
        assert _bytes(p) == raw, "读失败被当成损坏，回写覆盖了完好账本"
        assert not (tmp_path / "ledger.json.bak").exists(), "没有回写就不该有 .bak"
        assert b.today_usage() == 0.0
    assert len(pet_book.Book(str(tmp_path)).all_records()) == 1


def test_book_nested_records_type_logged(tmp_path, monkeypatch):
    """P2：{"records": {...}}（顶层对象、内层类型错）以前静默丢成空表、零日志。"""
    p = tmp_path / "ledger.json"
    p.write_text(json.dumps({"date": "2026-01-01", "records": {"0": {"amount": 5}},
                             "last_balance": None}, ensure_ascii=False), encoding="utf-8")
    logs = []
    monkeypatch.setattr(pet_book.pet_log, "log_error", logs.append)
    b = pet_book.Book(str(tmp_path))
    assert b.all_records() == []
    assert any("records" in m for m in logs), logs
    assert _json(p)["records"] == []      # 归一化后照常落盘（老行为不变）


def test_book_nested_days_type_logged(tmp_path, monkeypatch):
    """P2：{"days": [...]}（归档内层类型错）同样要留一行日志。"""
    p = tmp_path / "ledger_archive.json"
    p.write_text(json.dumps({"days": [1, 2]}, ensure_ascii=False), encoding="utf-8")
    logs = []
    monkeypatch.setattr(pet_book.pet_log, "log_error", logs.append)
    pet_book.Book(str(tmp_path))
    assert any("days" in m for m in logs), logs
    assert _json(p)["days"] == {}


def test_book_missing_files_leave_no_bak(tmp_path):
    """反面：首次运行（两个文件都不存在）不是损坏 → 不许凭空产生 .bak。"""
    pet_book.Book(str(tmp_path))
    assert not (tmp_path / "ledger.json.bak").exists()
    assert not (tmp_path / "ledger_archive.json.bak").exists()


def test_heal_json_bad_normalize_never_writes(tmp_path):
    """防御：normalize 判据自己抛异常 / 返回值不是二元组时，**一个字节都不能写**。

    判据是调用方注入的（pet_chat/pet_voice 各一份），判据写错不能反过来把用户的文件洗掉
    ——"宁可少写一次"是这条的取舍。
    """
    p = tmp_path / "x.json"
    original = '{"history": {"坏": 1}}'
    p.write_text(original, encoding="utf-8")

    def boom(_d):
        raise RuntimeError("判据坏了")

    assert pet_io.heal_json(str(p), dict, log=lambda m: None,
                            normalize=boom) == ({"history": {"坏": 1}}, False)
    assert _text(p) == original
    assert not (tmp_path / "x.json.bak").exists()

    # 返回值不是二元组（API 用错）：同样按"没坏"处理，不写盘
    assert pet_io.heal_json(str(p), dict, log=lambda m: None,
                            normalize=lambda _d: "不是二元组的坏返回值") \
        == ({"history": {"坏": 1}}, False)
    assert _text(p) == original
    assert not (tmp_path / "x.json.bak").exists()


# ---------------- 4. _check_release：用户数据判据改成名字模式 ----------------

def test_release_user_data_matcher_covers_residues():
    """P3-6：精确名匹配挡不住残留 → <名字>.<pid>.<tid>.tmp / <名字>.bak 都要被点名。"""
    tid = threading.get_ident()
    for name in ("ledger.json.%d.%d.tmp" % (os.getpid(), tid),
                 "ledger.json.%d.tmp" % tid,
                 "config.json.tmp",
                 "memory.json.bak",
                 "usage.json.migrated",
                 "error.log.old"):
        assert chk.user_data_hit(name), name
        assert chk.residue_hit(name), name
        assert chk.user_data_hit(name) in chk.USER_DATA_NAMES, name
    # 精确名：user_data_hit 命中，但绿色版目录检查（residue_hit）不算残留
    assert chk.user_data_hit("ledger.json") == "ledger.json"
    assert chk.residue_hit("ledger.json") == ""
    # 不是用户数据的文件一律不命中（不许误伤正常文件）
    for name in ("pet_io.py", "notes.tmp", "old.json", "config.json.bak.tmp",
                 "assets/char.png", "README.md"):
        assert chk.user_data_hit(os.path.basename(name)) == "", name
        assert chk.residue_hit(os.path.basename(name)) == "", name


def test_release_zip_flags_tmp_and_bak_residue(tmp_path):
    """P3-6：发布包里混进 "<名字>.<pid>.<tid>.tmp"/"<名字>.bak" 必须被点名。"""
    z = tmp_path / "bad.zip"
    tid = threading.get_ident()
    with zipfile.ZipFile(str(z), "w") as zf:
        for n in ("桌宠.py", "main.py", "python.exe", "assets/",
                  "ledger.json.%d.%d.tmp" % (os.getpid(), tid),
                  "memory.json.bak", "error.log.old", "voice.json.%d.tmp" % tid):
            zf.writestr(n, "x")
    joined = " ".join(chk.check_zip(str(z), "9.9.9"))
    assert "ledger.json.%d.%d.tmp" % (os.getpid(), tid) in joined, joined
    assert "memory.json.bak" in joined, joined
    assert "error.log.old" in joined, joined
    assert "voice.json.%d.tmp" % tid in joined, joined


def test_release_green_dir_names_residue_but_not_plain_user_data(tmp_path, monkeypatch):
    """P3-6：绿色版目录里的残留要点名；**常规用户数据文件照旧允许存在**（v2.2.2 事故：
    当年把"打包前清用户数据"当检查项，把用户的 roles.json/素材删掉过）。"""
    monkeypatch.setattr(chk, "GREEN", str(tmp_path))
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    (tmp_path / "roles.json").write_text("{}", encoding="utf-8")
    (tmp_path / "error.log").write_text("", encoding="utf-8")
    (tmp_path / "pet_io.py").write_text("x", encoding="utf-8")
    assert chk.check_green_dir() == [], "常规用户数据不该被当成打包阻塞项"

    resid_name = "ledger.json.%d.%d.tmp" % (os.getpid(), threading.get_ident())
    (tmp_path / resid_name).write_text("x", encoding="utf-8")
    (tmp_path / "memory.json.bak").write_text("x", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "roles.json.tmp").write_text("x", encoding="utf-8")
    fails = chk.check_green_dir()
    joined = " ".join(fails)
    assert len(fails) == 1, fails
    assert resid_name in joined and "memory.json.bak" in joined, joined
    assert "assets/roles.json.tmp" in joined, "子目录里的残留没被扫到：%s" % joined
    assert "config.json" not in joined, "常规用户数据被一起点名了：%s" % joined

    (tmp_path / resid_name).unlink()
    (tmp_path / "memory.json.bak").unlink()
    (tmp_path / "assets" / "roles.json.tmp").unlink()
    assert chk.check_green_dir() == [], "残留清掉后必须放行"


# ---------------- 5. AUDIO_MAGICS：不许有多余/死项 ----------------

def test_audio_magics_all_reachable_unique_and_load_bearing(monkeypatch):
    """P3-7：AUDIO_MAGICS 判据（任一不满足 = 死项/多余项）：
      ① 恒 4 字节——比较的是 4 字节 head，长度不是 4 的**永远匹配不上**
         （v2.3.1 已删掉 ID3 / FF FB 这类死项，别再混回来）；
      ② 不重复；
      ③ **真的在起作用**：把该项从表里拿掉后，同一个"像纯文本"的载荷必须由"放行"
         转为"拒绝"——拿掉不拿掉一个样，说明这一项是多余的；
      ④ 没有被更早的分支抢走（ID3 前缀 / EBML / MPEG 帧同步）。
    """
    magics = pet_voice.AUDIO_MAGICS
    assert magics, "魔数表被清空了？"
    assert len(set(magics)) == len(magics), "AUDIO_MAGICS 有重复项：%r" % (magics,)
    payload = b"hello world"      # 纯 ASCII：没有魔数时会被 _looks_like_text 拦下
    for m in magics:
        assert isinstance(m, bytes) and len(m) == 4, "非 4 字节魔数永远匹配不上：%r" % (m,)
        assert m[:3] != b"ID3", "被 head[:3] == b'ID3' 抢走（死项）：%r" % (m,)
        assert m != pet_voice._EBML_MAGIC, "被 EBML 分支抢走（死项）：%r" % (m,)
        assert not (m[0] == 0xFF and (m[1] & 0xE0) == 0xE0), "被 MPEG 帧同步抢走：%r" % (m,)
        assert pet_voice._looks_like_audio(m + payload) is True, "入表了却通不过：%r" % (m,)
        monkeypatch.setattr(pet_voice, "AUDIO_MAGICS",
                            tuple(x for x in magics if x != m))
        assert pet_voice._looks_like_audio(m + payload) is False, \
            "拿掉 %r 结果不变 → 这一项是多余的" % (m,)
        monkeypatch.setattr(pet_voice, "AUDIO_MAGICS", magics)
