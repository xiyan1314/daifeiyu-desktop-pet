# -*- coding: utf-8 -*-
"""v2.3.1 数据持久化收口回归（评审 P0-1 / P0-2 / P1-1 / P1-2 / P1-3 / P2-2 / P2-3）。

覆盖三件事：
1. pet_io 的并发语义——多线程写同一路径不产生坏 JSON、临时名带线程号、失败清理 tmp、
   os.replace 共享冲突重试、读损坏如实告知、愈合只在"文件仍然是坏的"时才写；
2. 各模块的愈合回写——坏 memory.json / 坏 audio.json / 坏 alarms.json / 坏 behaviors.json
   读一次就被修好，且**绝不覆盖在途写者刚写好的新数据**；
3. 迁移类修复——normalize_time 宽松补零（"7:5"→"07:05"）、旧动作 act:"jump" 映射不丢。

全部纯逻辑（Qt-free），可离线跑。
"""
import ast
import json
import os
import re
import threading
import time

import pet_alarm
import pet_behaviors
import pet_book
import pet_chat
import pet_io
import pet_lines
import pet_resources
import pet_voice


# 模块导入时抓一份真 open：_deny_open 会替换 builtins.open 来模拟"应用读不到"，
# 但**测试自己检查磁盘**不该被这个注入挡住（否则断言写不出来）。
_REAL_OPEN = open


def _read(path):
    with _REAL_OPEN(str(path), "r", encoding="utf-8") as f:
        return json.load(f)


def _tmp_leftovers(d):
    return [f for f in os.listdir(str(d)) if f.endswith(".tmp")]


# ---------------- 1. pet_io：并发与原子性 ----------------

def test_concurrent_writes_keep_file_valid(tmp_path):
    """根因 A：多线程 × 多次写同一路径，读回恒为合法 JSON（固定 .tmp 无锁会半截上盘）。

    旧实现能否检出：能——8 线程共用一个 "<path>.tmp" 时，一方 json.dump 到一半被另一方
    截断，随后的 os.replace 就会把半截 JSON 提交上盘（本用例读回即 JSONDecodeError）。
    写者**断言了 atomic_write_json 的返回值**，写失败不会被吞掉。
    """
    p = str(tmp_path / "ledger.json")
    errors = []

    def worker(n):
        try:
            for i in range(40):
                err = pet_io.atomic_write_json(
                    p, {"worker": n, "seq": i, "pad": "x" * 200})
                assert err is None, err
        except Exception as e:      # 记下来在主线程断言（子线程断言不会让测试失败）
            errors.append(repr(e))

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert not errors, errors
    data = _read(p)
    assert data["pad"] == "x" * 200 and 0 <= data["worker"] < 8
    assert _tmp_leftovers(tmp_path) == []          # 没有残留半截 tmp


def test_publish_holds_path_lock_until_replace_commits(tmp_path, monkeypatch):
    """根因 A（确定性版；替换掉原来那条"结构上不可能失败"的读者用例，M2）。

    真正要钉住的不变量：**"写 tmp → os.replace"整段都在同一把路径锁内**。
    它是另外两条语义的地基——heal_json 的"锁内复查"、pet_chat 的"锁内比代次"都靠它。
    （原用例只能证明 os.replace 是原子的，而旧实现同样用 os.replace，所以永远绿。）

    做法：让 os.replace 停在提交点（此时写者还持着锁），然后
      ① 另一个线程去拿同一把路径锁读文件 → 必须阻塞；
      ② 不持锁的直接读 → 只能看到旧版本（原子提交），绝不是半截。
    旧实现（固定 "<path>.tmp"、提交不持路径锁）下 ① 会立刻返回 → 本用例失败。
    """
    p = str(tmp_path / "memory.json")
    pet_io.atomic_write_json(p, {"v": 0})
    real_replace = pet_io.os.replace
    inside = threading.Event()
    release = threading.Event()

    def slow_replace(src, dst):
        inside.set()
        assert release.wait(10), "测试没有放行提交"
        return real_replace(src, dst)

    monkeypatch.setattr(pet_io.os, "replace", slow_replace)
    done = []

    def writer():
        # 断言返回值（旧版此处丢弃返回值 → 写失败也是绿的）
        done.append(pet_io.atomic_write_json(p, {"v": 1, "pad": "x" * 4000}))

    t = threading.Thread(target=writer)
    t.start()
    assert inside.wait(10), "写者没有走到提交点"

    got = []

    def locked_reader():
        with pet_io.path_lock(p):          # 与写者同一把路径锁
            got.append(pet_io.read_json_or(p, dict, log=lambda m: None))

    r = threading.Thread(target=locked_reader)
    r.start()
    r.join(0.3)
    assert r.is_alive(), "提交不在路径锁内：读者没等锁就读到了中间态"
    assert got == []
    assert _read(p) == {"v": 0}            # 不持锁的直接读：只能看到旧版本

    release.set()
    t.join(10)
    r.join(10)
    assert done == [None], done
    assert got == [({"v": 1, "pad": "x" * 4000}, False)]
    assert _read(p)["v"] == 1
    assert _tmp_leftovers(tmp_path) == []  # 提交成功，不留 tmp


def test_tmp_name_uses_thread_id_and_is_cleaned_on_failure(tmp_path, monkeypatch):
    """临时名必须是 "<path>.<进程号>.<线程号>.tmp"，写失败时自己的 tmp 必须被清掉。

    v2.3.1（一致性收口）：加进程号——同机多实例/调试双开时两个进程的线程号可能相同，
    只带线程号会抢同一个 tmp 互相截断（P3-5）。
    """
    p = str(tmp_path / "x.json")
    seen = []
    real_replace = os.replace

    def spy(src, dst):
        seen.append(os.path.basename(src))
        return real_replace(src, dst)

    monkeypatch.setattr(pet_io.os, "replace", spy)
    assert pet_io.atomic_write_json(p, {"a": 1}) is None
    assert seen == ["x.json.%d.%d.tmp" % (os.getpid(), threading.get_ident())]

    def boom(src, dst):
        raise PermissionError(32, "The process cannot access the file")

    monkeypatch.setattr(pet_io.os, "replace", boom)
    err = pet_io.atomic_write_json(p, {"b": 2})
    assert err is not None and "file" in err.lower()
    assert _tmp_leftovers(tmp_path) == []          # 失败清理自己的 tmp
    assert _read(p) == {"a": 1}                    # 旧内容原样保留（原子性）


def test_replace_shared_conflict_retries(tmp_path, monkeypatch):
    """根因 C：os.replace 共享冲突（PermissionError）→ sleep 0.05 重试，最多 retries 次。"""
    p = str(tmp_path / "r.json")
    calls = []
    real_replace = os.replace

    def flaky(src, dst):
        calls.append(os.path.basename(src))
        if len(calls) <= 2:
            raise PermissionError(32, "sharing violation")
        return real_replace(src, dst)

    monkeypatch.setattr(pet_io.os, "replace", flaky)
    t0 = time.monotonic()
    assert pet_io.atomic_write_json(p, {"ok": True}, retries=3) is None
    assert len(calls) == 3                          # 失败 2 次 + 第 3 次成功
    assert time.monotonic() - t0 >= 0.08            # 两次重试都真的 sleep 了
    assert _read(p) == {"ok": True}

    def always_fail(src, dst):
        calls.append(os.path.basename(src))
        raise PermissionError(32, "sharing violation")

    calls.clear()
    monkeypatch.setattr(pet_io.os, "replace", always_fail)
    assert pet_io.atomic_write_json(p, {"x": 1}, retries=3) is not None
    assert len(calls) == 4                          # 首写 + 3 次重试，不再无限重试
    assert _tmp_leftovers(tmp_path) == []


def test_read_json_reports_corruption(tmp_path):
    """A：read_json_or 必须把"损坏"如实告知调用方（缺失≠损坏，结构非法=损坏）。"""
    p = str(tmp_path / "a.json")
    assert pet_io.read_json_or(p, dict) == ({}, False)      # 首次运行：不报损坏
    assert pet_io.read_json_or(p, lambda: {"d": 1}) == ({"d": 1}, False)

    with open(p, "w", encoding="utf-8") as f:
        f.write("{broken json")
    data, corrupted = pet_io.read_json_or(p, dict)
    assert data == {} and corrupted is True

    with open(p, "w", encoding="utf-8") as f:
        f.write("[1, 2, 3]")                                # 合法 JSON 但顶层类型不对
    data, corrupted = pet_io.read_json_or(p, dict)
    assert data == {} and corrupted is True

    data, ok = pet_io.load_json(p, dict)                    # ok 口径的等价入口
    assert data == {} and ok is False


def test_heal_only_writes_when_still_broken(tmp_path):
    """愈合的写入门槛：文件没坏就不动它（不重写、不更新时间戳）。"""
    p = str(tmp_path / "h.json")
    pet_io.atomic_write_json(p, {"keep": 1})
    before = os.stat(p).st_mtime_ns
    assert pet_io.heal_json(p, lambda: {"keep": 0}) == ({"keep": 1}, False)
    assert os.stat(p).st_mtime_ns == before

    with open(p, "w", encoding="utf-8") as f:
        f.write("{broken")
    data, corrupted = pet_io.heal_json(p, lambda: {"healed": True})
    assert corrupted is True and data == {"healed": True}
    assert _read(p) == {"healed": True}


def test_heal_never_clobbers_fresh_data_from_inflight_writer(tmp_path):
    """C 项核心语义：愈合前在**同一把路径锁内**复查——在途写者刚写好的数据绝不被覆盖。

    写者持锁写入并停在临界区内，愈合只能在它放锁后复查 → 读到的是新数据 → 不写。
    """
    p = str(tmp_path / "c.json")
    with open(p, "w", encoding="utf-8") as f:
        f.write("{broken")                     # 磁盘上此刻是坏的
    lock = pet_io.path_lock(p)
    done = threading.Event()

    def writer():
        with lock:
            pet_io.atomic_write_json(p, {"fresh": "data"}, lock=lock)
            done.set()
            time.sleep(0.1)                    # 仍在临界区内：愈合不得偷偷回写空结构

    t = threading.Thread(target=writer)
    t.start()
    assert done.wait(5)
    data, corrupted = pet_io.heal_json(p, lambda: {"stale": True})   # 阻塞到写者放锁
    t.join(5)
    assert corrupted is False and data == {"fresh": "data"}
    assert _read(p) == {"fresh": "data"}


# ---------------- 2. 各模块愈合回写（根因 B） ----------------

def test_memory_corrupt_heals_file_once(tmp_path):
    """C：坏 memory.json 第一次读就回写合法结构；第二次读不再报错（只愈合一次）。"""
    p = str(tmp_path / "memory.json")
    with open(p, "w", encoding="utf-8") as f:
        f.write("{broken json")
    logs = []
    assert pet_chat.read_memory(p, 10, log=logs.append) == []
    assert logs, "损坏必须留痕（error.log 有据可查）"
    assert _read(p).get("history") == []       # 坏文件已被回写成合法结构

    logs2 = []
    assert pet_chat.read_memory(p, 10, log=logs2.append) == []
    assert logs2 == []                         # 不再每次启动重报（旧日志里刷了 140 次）


def test_memory_history_and_long_term_survive_concurrent_writes(tmp_path, monkeypatch):
    """P1-1：读-改-写在同一把锁内完成——两个写者不再用旧快照互相覆盖。

    旧实现能否检出：能——旧 _write_memory_file 是"锁外读 → 改 → 写"，两个写者各自
    拿着自己读到的旧 dict 落盘，最后一次写会**整体丢掉**另一边的 history 或 long_term
    （本用例末尾两条断言分别盯这两个字段，不是恒真）。

    M2：两个写者的**落盘返回值**这里被逐个记账（write_memory 自己吞返回值，
    旧口径下"写失败"照样是绿的）——任何一次原子写返回错误串，本用例直接失败。
    """
    p = str(tmp_path / "memory.json")
    pet_chat.write_memory(p, [("user", "hi")], 10)

    real_write = pet_io.atomic_write_json
    errs = []

    def spy(*a, **kw):
        err = real_write(*a, **kw)
        errs.append(err)
        return err

    monkeypatch.setattr(pet_io, "atomic_write_json", spy)

    def hist_writer():
        for i in range(40):
            pet_chat.write_memory(p, [("user", "m%d" % i)], 10)

    def lt_writer():
        for i in range(40):
            pet_chat.write_long_term(p, {"user_name": "绳匠%d" % i}, max_entries=10)

    t1 = threading.Thread(target=hist_writer)
    t2 = threading.Thread(target=lt_writer)
    t1.start()
    t2.start()
    t1.join(30)
    t2.join(30)
    assert len(errs) == 80, len(errs)          # 两个写者各 40 次全部真的走了落盘路径
    assert all(e is None for e in errs), [e for e in errs if e]
    data = _read(p)                            # 恒为合法 JSON
    assert data["long_term"]["user_name"].startswith("绳匠")   # 长期记忆没被历史写覆盖
    assert data["history"] and data["history"][-1][0] == "user"  # 历史没被长期记忆写清空


def test_alarm_load_heals_dropped_entries(tmp_path):
    """C+D：坏条目丢弃、可恢复格式补零，且清洗结果回写磁盘（下次启动不再报）。"""
    idx = tmp_path / "alarms.json"
    idx.write_text(json.dumps({"alarms": [
        {"id": "a1", "time": "7:5", "label": "起床"},
        {"id": "a2", "time": "bad"},
    ]}, ensure_ascii=False), encoding="utf-8")
    logs = []
    svc = pet_alarm.AlarmService(str(tmp_path), log=logs.append)
    assert [a["id"] for a in svc.list()] == ["a1"]
    assert svc.get("a1")["time"] == "07:05"    # 补零而不是丢弃
    assert any("bad entry" in m for m in logs)
    on_disk = _read(idx)
    assert [a["id"] for a in on_disk["alarms"]] == ["a1"]
    assert on_disk["alarms"][0]["time"] == "07:05"   # 清洗结果已落盘

    logs2 = []
    pet_alarm.AlarmService(str(tmp_path), log=logs2.append)
    assert logs2 == []                         # 只愈合一次（旧日志里刷了 15 次）


def test_alarm_corrupt_file_is_healed(tmp_path):
    """C：坏 alarms.json 读完立刻回写合法空库。"""
    idx = tmp_path / "alarms.json"
    idx.write_text("{{{ not json", encoding="utf-8")
    assert pet_alarm.AlarmService(str(tmp_path), log=lambda m: None).list() == []
    assert _read(idx) == {"alarms": []}


def test_behaviors_load_heals_dropped_entries(tmp_path):
    """C+E：丢坏条目/迁移旧动作后回写；第二次加载零报错。"""
    idx = tmp_path / "behaviors.json"
    idx.write_text(json.dumps({"behaviors": [
        {"id": "12345678", "name": "old_jump", "steps": [{"act": "jump"}]},
        {"id": "87654321", "name": "old_fly", "steps": [{"act": "fly"}]},
    ]}, ensure_ascii=False), encoding="utf-8")
    logs = []
    svc = pet_behaviors.BehaviorService(str(tmp_path), log=logs.append)
    kept = {b["id"]: b for b in svc.list()}
    assert "12345678" in kept, "历史 jump 动作被丢了"
    assert kept["12345678"]["steps"] == [{"act": "play_action", "name": "jump"}]
    assert "87654321" not in kept              # 未知动作仍然丢弃
    assert any("fly" in m for m in logs)       # 但必须留痕
    on_disk = _read(idx)
    assert [b["id"] for b in on_disk["behaviors"]] == ["12345678"]
    assert on_disk["behaviors"][0]["steps"][0]["act"] == "play_action"

    logs2 = []
    svc2 = pet_behaviors.BehaviorService(str(tmp_path), log=logs2.append)
    assert logs2 == [] and [b["id"] for b in svc2.list()] == ["12345678"]


def test_resources_read_json_heals_corrupt_index(tmp_path):
    """C：pet_resources._read_json 损坏即回写 factory() 结构（音频索引实样）。"""
    idx = tmp_path / "audio.json"
    idx.write_text("{broken", encoding="utf-8")
    lib = pet_resources.AudioLibrary(str(tmp_path))
    assert lib._data["fragments"] == []        # 库照常可用（空索引）
    assert _read(idx) == {}                    # 坏文件被回写愈合
    data, corrupted = pet_io.read_json_or(str(idx), dict)
    assert data == {} and corrupted is False

    idx.write_text("[1,2,3]", encoding="utf-8")   # 顶层类型非法同样愈合
    pet_resources.AudioLibrary(str(tmp_path))
    assert pet_io.read_json_or(str(idx), dict) == ({}, False)


def test_role_library_keeps_original_bak_before_rebuild(tmp_path):
    """例外口径：RoleLibrary 自己有"先备份再重建"的恢复路径，愈合不得抢先覆盖原文件。"""
    idx = tmp_path / "roles.json"
    raw = '{"roles": "not a list"}'
    idx.write_text(raw, encoding="utf-8")
    pet_resources.RoleLibrary(str(tmp_path))
    bak = tmp_path / "roles.json.bak"
    assert bak.exists() and bak.read_text(encoding="utf-8") == raw


# ---------------- 3. 迁移类修复 ----------------

def test_normalize_time_lenient_padding():
    """D（P1-1）：可恢复格式补零而非丢弃；严格正则仍是最终判据。"""
    assert pet_alarm.normalize_time("7:5") == "07:05"
    assert pet_alarm.normalize_time("8:0") == "08:00"
    assert pet_alarm.normalize_time("23:5") == "23:05"
    assert pet_alarm.normalize_time("07:30:00") == "07:30"      # 带秒
    for bad in ("25:00", "12:60", "abc", "", "7", None, "7:5:xx", "7:5:30:00"):
        assert pet_alarm.normalize_time(bad) == "", bad
    assert not pet_alarm.valid_time("7:5")     # valid_time 保持严格（最终判据）


def test_legacy_act_alias_mapped_in_validate_steps():
    """E（P1-2）：validate_steps 把旧动作名映射成 play_action，而不是判不合法。"""
    steps, err = pet_behaviors.validate_steps([{"act": "jump"}, {"act": "say", "text": "嗨"}])
    assert err == "" and steps == [{"act": "play_action", "name": "jump"},
                                   {"act": "say", "text": "嗨"}]
    # 显式给了 name 就以它为准
    steps2, _ = pet_behaviors.validate_steps([{"act": "jump", "name": "wave"}])
    assert steps2 == [{"act": "play_action", "name": "wave"}]
    # 未知动作照旧拒绝（不能借别名放行任何字符串）
    assert pet_behaviors.validate_steps([{"act": "fly"}])[0] is None
    # act 是不可哈希的坏值也不能崩（手改 JSON 会出现 list/dict）
    assert pet_behaviors.validate_steps([{"act": ["jump"]}])[0] is None

def test_io_bom_and_gbk_are_not_treated_as_corrupt(tmp_path):
    """S1（兼容审查）：UTF-8 with BOM / GBK 的文件内容完好，绝不能被"愈合"清空。

    回归点：read_json_or 当初用 encoding="utf-8" + except Exception 判损坏，
    于是记事本另存为 BOM/ANSI 的用户文件会被空结构原地覆盖（旧版一个字节都不动）。
    """
    import json as _json
    import pet_io
    # ① UTF-8 with BOM：内容完好，必须原样读出且**不触发愈合**
    p = tmp_path / "bom.json"
    p.write_bytes("\ufeff".encode("utf-8") + _json.dumps({"alarms": [{"id": "a1"}]}).encode("utf-8"))
    data, corrupted = pet_io.read_json_or(str(p), dict, log=lambda m: None)
    assert corrupted is False, "带 BOM 的完好文件被判成损坏（会被清空）"
    assert data["alarms"][0]["id"] == "a1", "带 BOM 的内容没读出来：%r" % (data,)
    # ② GBK：解码失败 ≠ 损坏 → 不得回写
    g = tmp_path / "gbk.json"
    g.write_bytes(_json.dumps({"name": "中文"}, ensure_ascii=False).encode("gbk"))
    before = g.read_bytes()
    data2, corrupted2 = pet_io.read_json_or(str(g), dict, log=lambda m: None)
    assert corrupted2 is False, "GBK 文件被判成损坏（会被清空）"
    pet_io.heal_json(str(g), dict, log=lambda m: None)
    assert g.read_bytes() == before, "GBK 文件被愈合写盘覆盖了（旧版不会动它）"
    # ③ 真损坏仍然要愈合，并且**留一份 .bak**
    bad = tmp_path / "bad.json"
    bad.write_text("{ oops", encoding="utf-8")
    pet_io.heal_json(str(bad), lambda: {"ok": True}, log=lambda m: None)
    assert _json.loads(bad.read_text(encoding="utf-8")) == {"ok": True}, "真损坏没有愈合"
    assert (tmp_path / "bad.json.bak").exists(), "愈合前没有留备份（判错就无法恢复）"

# ---------------- 4. 二轮三路复核：愈合/回写不得销毁用户数据 ----------------

def _read_bytes(p):
    with _REAL_OPEN(str(p), "rb") as f:
        return f.read()


def _bom_json(obj):
    """UTF-8 with BOM（记事本「另存为 UTF-8」的默认产物）。"""
    return "\ufeff".encode("utf-8") + json.dumps(obj, ensure_ascii=False).encode("utf-8")


def _deny_open(monkeypatch, suffix, times=1):
    """让 builtins.open 对某个后缀的文件打不开 times 次（None=一直打不开），其余照常。

    模拟杀软/索引器/残留句柄造成的**瞬时**（times=1）或**持续**（times=None）共享冲突。
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


# ---- P0-A：pet_lines 的读路径 ----------------

def test_lines_bom_file_is_not_rewritten(tmp_path):
    """P0-A：带 UTF-8 BOM 的**合法** lines.json 不得被"愈合"改写成内置种子库。

    HEAD 实测：103 字节 / 1 条自定义台词 → 被改写成 20269 字节、自定义台词全丢、零日志。
    """
    p = tmp_path / "lines.json"
    raw = _bom_json({"version": 1,
                     "lines": [{"id": "u_keep", "text": "自定义台词不能被清掉",
                                "category": "happy", "role_slot": None, "voice_slot": None,
                                "order": 1, "builtin": False, "food": ""}],
                     "dialogues": [], "deleted_builtins": []})
    p.write_bytes(raw)
    svc = pet_lines.LineService(str(tmp_path), log=lambda m: None)
    assert p.read_bytes() == raw, "带 BOM 的完好文件被改写了（用户自定义台词被清空）"
    assert svc.get("u_keep") is not None
    assert svc.text_of("u_keep") == "自定义台词不能被清掉"
    assert svc.count() > 1, "种子没有在内存里补齐"
    assert not (tmp_path / "lines.json.bak").exists(), "没坏的文件不该产生 .bak"


def test_lines_gbk_file_is_not_rewritten(tmp_path):
    """P0-A：GBK 另存的 lines.json 内容完好，绝不能被"愈合"清空（旧版一个字节都不动）。"""
    p = tmp_path / "lines.json"
    raw = json.dumps({"lines": [{"id": "u_gbk", "text": "中文台词", "category": "idle"}]},
                     ensure_ascii=False).encode("gbk")
    p.write_bytes(raw)
    svc = pet_lines.LineService(str(tmp_path), log=lambda m: None)
    assert p.read_bytes() == raw, "GBK 文件被愈合写盘覆盖了"
    assert svc.count() > 0, "读不出来也要能用（内存走种子），只是不许动磁盘"


def test_lines_transient_read_failure_does_not_overwrite(tmp_path, monkeypatch):
    """P0-A：读取失败（PermissionError）不能证明文件坏了——绝不回写种子覆盖它。"""
    p = tmp_path / "lines.json"
    raw = json.dumps({"lines": [{"id": "u_keep", "text": "我的台词", "category": "happy"}]},
                     ensure_ascii=False).encode("utf-8")
    p.write_bytes(raw)
    _deny_open(monkeypatch, "lines.json")
    svc = pet_lines.LineService(str(tmp_path), log=lambda m: None)
    assert p.read_bytes() == raw, "一次瞬时读失败就把台词库覆盖成种子了"
    assert not (tmp_path / "lines.json.bak").exists()
    assert svc.count() > 0
    svc2 = pet_lines.LineService(str(tmp_path), log=lambda m: None)   # 下次启动读得动
    assert svc2.text_of("u_keep") == "我的台词"


# ---- v2.4（M4）：脏读之后**第一次编辑**必须留 .bak（此前是"下次一改就永久覆盖"） ----

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _gbk_lines_json(path, text="用户的台词，记事本 ANSI 另存"):
    """写一个 GBK（记事本「ANSI」）另存的 lines.json，返回原始字节。"""
    raw = json.dumps({"version": 1,
                      "lines": [{"id": "u_gbk", "text": text, "category": "idle", "order": 1}]},
                     ensure_ascii=False).encode("gbk")
    path.write_bytes(raw)
    return raw


def test_lines_gbk_dirty_read_backs_up_before_first_edit_v24(tmp_path):
    """M4：GBK lines.json 启动不动磁盘，但**用户下一次编辑**不许把原文永久覆盖掉。

    修复前实测：启动后字节不变 ✓、日志一条 ✓，但 svc.lines() 只有 88 条内置种子，
    随后一次 svc.add(...) 就把 UTF-8 种子库整体盖上去，GBK 原文永久消失、无 .bak。
    """
    p = tmp_path / "lines.json"
    raw = _gbk_lines_json(p)
    logs = []
    svc = pet_lines.LineService(str(tmp_path), log=logs.append)
    assert svc._dirty_read is True, "没有打脏读标记 → 下一次编辑会无备份覆盖"
    assert svc.dirty_read is True, "对外只读属性与内部标记不一致"
    assert p.read_bytes() == raw, "启动阶段就不该动文件（v2.3.1 口径）"
    assert not (tmp_path / "lines.json.bak").exists(), "启动阶段留 .bak 是多余的写盘"
    assert svc.get("u_gbk") is None, "前提不成立：用户台词本次确实看不见"

    ln, err = svc.add("新加的台词", "happy")
    assert ln is not None and not err, err
    bak = tmp_path / "lines.json.bak"
    assert bak.is_file(), "覆盖 GBK 原文之前没留 .bak —— 用户数据永久消失"
    assert bak.read_bytes() == raw, "备份的必须是 GBK 原文（逐字节）"
    assert svc._dirty_read is False, "保存成功后没有清脏读标记"
    assert svc.get(ln["id"]) is not None, "新台词没写进去"
    assert _read(p)["lines"], "新内容没落盘"


def test_lines_dirty_read_flag_lifecycle_v24(tmp_path, monkeypatch):
    """M4：写盘失败保持脏标记（保护不中断），恢复后清标记且 .bak 只留一份。"""
    p = tmp_path / "lines.json"
    raw = _gbk_lines_json(p)
    svc = pet_lines.LineService(str(tmp_path), log=lambda m: None)
    assert svc._dirty_read is True
    real = pet_io.atomic_write_json
    monkeypatch.setattr(pet_io, "atomic_write_json", lambda *a, **kw: "磁盘满了")
    _ln, err = svc.add("第一次写盘会失败", "happy")
    assert err, "注入的写盘失败没有被上报"
    assert svc._dirty_read is True, "写盘失败后脏标记被误清 → 下一次保存失去备份保护"
    bak = tmp_path / "lines.json.bak"
    assert bak.is_file() and bak.read_bytes() == raw, ".bak 没留下或被写坏"
    assert p.read_bytes() == raw, "写盘失败竟然改了原文"

    monkeypatch.setattr(pet_io, "atomic_write_json", real)
    _ln2, err2 = svc.add("这次能写", "happy")
    assert not err2, err2
    assert svc._dirty_read is False
    assert bak.read_bytes() == raw, "恢复写入时又覆盖了一次 .bak"
    svc.add("第二条", "idle")   # 标记已清 → 不该再备份
    assert bak.read_bytes() == raw, \
        "脏标记清了还在备份：.bak 被新内容盖掉，GBK 原文反而没了"


def test_lines_clean_file_is_not_dirty_v24(tmp_path):
    """M4 反例对照：正常 UTF-8 lines.json 既不打脏标记，也不产生 .bak。"""
    p = tmp_path / "lines.json"
    p.write_text(json.dumps({"version": 1, "lines": [
        {"id": "u1", "text": "正常台词", "category": "idle", "order": 1}]}, ensure_ascii=False),
        encoding="utf-8")
    svc = pet_lines.LineService(str(tmp_path), log=lambda m: None)
    assert svc._dirty_read is False
    assert svc.get("u1") is not None, "前提：正常文件必须读得出来"
    svc.add("新台词", "happy")
    assert not (tmp_path / "lines.json.bak").exists(), "没脏读却留了 .bak"


def test_lines_read_failure_also_marks_dirty_v24(tmp_path, monkeypatch):
    """M4：读取失败（PermissionError）同样是脏读——之后编辑也不能无备份覆盖。"""
    p = tmp_path / "lines.json"
    raw = json.dumps({"version": 1, "lines": [
        {"id": "u_keep", "text": "我的台词", "category": "happy", "order": 1}]},
        ensure_ascii=False).encode("utf-8")
    p.write_bytes(raw)
    _deny_open(monkeypatch, "lines.json")          # 只挡构造时那一次读
    svc = pet_lines.LineService(str(tmp_path), log=lambda m: None)
    assert svc._dirty_read is True
    svc.add("新台词", "happy")
    bak = tmp_path / "lines.json.bak"
    assert bak.is_file() and bak.read_bytes() == raw, "读失败路径没有留备份"


def test_lines_corrupt_heal_keeps_single_bak_v24(tmp_path):
    """M4 边界：真损坏走愈合路径（已经留过 .bak），不该再打脏读标记、不该二次覆盖。"""
    p = tmp_path / "lines.json"
    p.write_text("{ 这不是合法 json", encoding="utf-8")
    logs = []
    svc = pet_lines.LineService(str(tmp_path), log=logs.append)
    assert svc._dirty_read is False, "真损坏走的是愈合路径，不该同时打脏读标记"
    assert (tmp_path / "lines.json.bak").read_text(encoding="utf-8") == "{ 这不是合法 json"
    assert not any("旧备份已被本次愈合覆盖" in x for x in logs), logs


def test_lines_dirty_read_bubble_is_wired_v24(tmp_path):
    """M4：脏读必须在**启动时**提示一次；文案要与事实一致（此刻还没有 .bak）。"""
    with _REAL_OPEN(os.path.join(ROOT_DIR, "桌宠.py"), "r", encoding="utf-8") as f:
        src = f.read()
    assert "self.lines_lib.dirty_read" in src, "启动没有检查脏读 → 用户以为台词被删了"
    assert "pet_lines.DIRTY_READ_NOTICE" in src, "提示文案没有接到气泡上"
    notice = pet_lines.DIRTY_READ_NOTICE
    assert "lines.json" in notice and "UTF-8" in notice and ".bak" in notice
    assert "已备份" not in notice, \
        "文案声称『已备份』，但 .bak 是下一次保存前才落的——启动时还没有，不能这么写"


def test_lines_hidden_until_edit_premise_v24(tmp_path):
    """M4 前提复核：脏读实例的台词确实只有内置种子（用户条目一条都看不见）。"""
    p = tmp_path / "lines.json"
    _gbk_lines_json(p)
    svc = pet_lines.LineService(str(tmp_path), log=lambda m: None)
    assert svc.count() == len(pet_lines._seed_source()), \
        "脏读时台词库不只有种子（%d 条），M4 的动机描述需要复核" % svc.count()
    assert all(x["builtin"] for x in svc.lines()), "脏读时竟然读出了非内置条目"


def test_lines_corrupt_file_heals_with_bak(tmp_path):
    """P0-A/C：真损坏才愈合，且愈合**之前**留 .bak（判错可恢复）。"""
    p = tmp_path / "lines.json"
    p.write_text("{ 这不是合法 json", encoding="utf-8")
    logs = []
    svc = pet_lines.LineService(str(tmp_path), log=logs.append)
    assert svc.count() > 0
    assert (tmp_path / "lines.json.bak").read_text(encoding="utf-8") == "{ 这不是合法 json"
    assert json.loads(p.read_text(encoding="utf-8"))["lines"], "坏文件没有被回写成合法结构"
    assert logs, "愈合过程必须留痕（此前这里写的是本模块根本不存在的 _log_error）"


def test_lines_norm_keeps_unknown_fields(tmp_path):
    """P0-A（M1）：归一化"先复制再覆盖已知键"——未知字段不得在读取回写时被删掉。"""
    p = tmp_path / "lines.json"
    p.write_text(json.dumps({"version": 1, "lines": [
        {"id": "u1", "text": "带自定义字段", "category": "happy", "order": 1,
         "memo": "用户手加的备注 / 未来版本的新字段"}],
        "dialogues": [], "deleted_builtins": []}, ensure_ascii=False), encoding="utf-8")
    svc = pet_lines.LineService(str(tmp_path), log=lambda m: None)
    assert svc.get("u1").get("memo") == "用户手加的备注 / 未来版本的新字段"
    svc.add("新台词", "idle")          # 触发一次真实落盘
    on_disk = {x["id"]: x for x in _read(p)["lines"]}
    assert on_disk["u1"].get("memo") == "用户手加的备注 / 未来版本的新字段", \
        "未知字段在归一化回写时被删掉了（重建已知键口径）"


# ---- P0-B：账本读失败不得清空 ----

def test_book_transient_read_failure_keeps_ledger(tmp_path, monkeypatch):
    """P0-B：一次瞬时读失败不得清空完好账本（旧实现：Book.__init__ 末尾无条件 _save_all）。

    实测（HEAD）：ledger.json 有 1 条记录 → 注入一次文本 open() PermissionError →
    磁盘 records=0、无备份。修完：读失败只读启动 + 标脏，等下一次真正的写操作再落盘。
    """
    p = tmp_path / "ledger.json"
    pet_book.Book(str(tmp_path)).add_manual(12.5, "午饭")
    raw = _read_bytes(p)
    assert len(_read(p)["records"]) == 1
    with monkeypatch.context() as m:
        _deny_open(m, "ledger.json")
        b = pet_book.Book(str(tmp_path))
        assert _read_bytes(p) == raw, "读失败时 Book.__init__ 把账本清空了（实测 records=0）"
        assert b.today_usage() == 0.0, "读不到就是读不到：内存按空账本继续"
        assert not (tmp_path / "ledger.json.bak").exists(), "没有回写就不该有 .bak"
    # 磁盘内容没被动过：重新正常构造仍能看到那条记录
    assert len(pet_book.Book(str(tmp_path)).all_records()) == 1
    # 下一次**真实写操作**照常落盘（不是靠启动时无条件回写）
    b.add_manual(1.0, "读失败之后的真实记账")
    assert _read(p)["records"], "真实写操作没有落盘"


# ---- P0-C：另外三处自建愈合路径也要留 .bak ----

def test_alarm_heal_leaves_bak(tmp_path):
    """P0-C：pet_alarm 自建「读 + 回写」愈合此前没有备份（只有 pet_io.heal_json 有）。"""
    idx = tmp_path / "alarms.json"
    idx.write_text("{{{ not json", encoding="utf-8")
    svc = pet_alarm.AlarmService(str(tmp_path), log=lambda m: None)
    assert svc.list() == []
    assert (tmp_path / "alarms.json.bak").read_text(encoding="utf-8") == "{{{ not json"
    assert _read(idx) == {"alarms": []}


def test_behaviors_heal_leaves_bak(tmp_path):
    """P0-C：pet_behaviors 同上（清洗/丢弃坏条目也算愈合，回写前必须留证）。"""
    idx = tmp_path / "behaviors.json"
    idx.write_text("{broken", encoding="utf-8")
    svc = pet_behaviors.BehaviorService(str(tmp_path), log=lambda m: None)
    assert svc.list() == []
    assert (tmp_path / "behaviors.json.bak").read_text(encoding="utf-8") == "{broken"
    assert _read(idx) == {"behaviors": []}


# ---- P1-B：RoleLibrary 读失败不得重建 ----

def test_role_library_read_failure_does_not_rebuild(tmp_path, monkeypatch):
    """P1-B：读不到 ≠ 结构坏。一次瞬时 PermissionError 不得把角色索引重建为空表。"""
    idx = tmp_path / "roles.json"
    raw = json.dumps({"roles": [{"id": "r1", "name": "小鱼", "file": "r1.png"}], "active": "r1"},
                     ensure_ascii=False).encode("utf-8")
    idx.write_bytes(raw)
    logs = []
    with monkeypatch.context() as m:
        _deny_open(m, "roles.json")
        m.setattr(pet_resources.pet_log, "log_error", logs.append)
        lib = pet_resources.RoleLibrary(str(tmp_path))
        assert idx.read_bytes() == raw, "读失败就把索引重建成了空表（角色全部消失）"
        assert not (tmp_path / "roles.json.bak").exists()
        assert lib.list_roles() == []          # 内存空库照常可用（不崩）
    assert any("读取失败" in x for x in logs), logs
    # 下次启动读得动 → 角色还在（说明数据从没被覆盖）
    lib2 = pet_resources.RoleLibrary(str(tmp_path))
    assert [r["id"] for r in lib2.list_roles()] == ["r1"]


def test_role_library_real_corruption_still_rebuilds_with_bak(tmp_path):
    """P1-B 的反面：**真解析失败**仍然要「备份 + 重建」（别把修复一起改没了）。"""
    idx = tmp_path / "roles.json"
    idx.write_text("{broken", encoding="utf-8")
    lib = pet_resources.RoleLibrary(str(tmp_path))
    assert lib.list_roles() == []
    assert (tmp_path / "roles.json.bak").read_text(encoding="utf-8") == "{broken"
    assert _read(idx) == {"roles": [], "active": ""}


# ---- P1-A：expect_epoch 守卫 ----

def test_write_memory_expect_epoch_guard(tmp_path):
    """P1-A：epoch 不匹配时必须在**写盘函数内部**放弃这次写（并记一行日志）。"""
    p = str(tmp_path / "memory.json")
    box = {"e": 0}
    logs = []
    pet_chat.write_memory(p, [("user", "旧")], 10)
    pet_chat.write_memory(p, [("user", "旧"), ("assistant", "回")], 10,
                          log=logs.append, expect_epoch=0, epoch_of=lambda: box["e"])
    assert [c for _r, c in pet_chat.read_memory(p, 10)] == ["旧", "回"]
    box["e"] = 1                       # 用户清了日志 / 清了 Key → 代次变了
    pet_chat.write_memory(p, [("user", "不该写回来")], 10,
                          log=logs.append, expect_epoch=0, epoch_of=lambda: box["e"])
    assert [c for _r, c in pet_chat.read_memory(p, 10)] == ["旧", "回"], "代次已变还是写回去了"
    assert any("代次" in x for x in logs), logs
    # 代次一致时照常写；长期记忆走同一条守卫
    pet_chat.write_memory(p, [("user", "新")], 10, expect_epoch=1, epoch_of=lambda: box["e"])
    assert [c for _r, c in pet_chat.read_memory(p, 10)] == ["新"]
    pet_chat.write_long_term(p, {"user_name": "不该写"}, log=logs.append,
                             expect_epoch=0, epoch_of=lambda: box["e"])
    assert pet_chat.read_long_term(p)["user_name"] == ""


class _Resp:
    def __init__(self, text):
        self.status_code = 200
        self._text = text
        self.text = text

    def json(self):
        return {"choices": [{"message": {"role": "assistant", "content": self._text}}]}


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


def _clear_logs_race(tmp_path, monkeypatch, legacy_saver=False):
    """跑一次**真** ChatService._worker，在它落盘之前模拟「清理日志」。

    返回 (落盘后的 history, 内存 history)。legacy_saver=True 注入只收 1 个参数的旧式
    memory_saver（没有代次契约）——用于证明窗口真实存在、上面的用例不是恒真。
    链路：ChatService._worker → 桌宠.save_chat_memory → pet_chat.write_memory（锁内查代次）。
    """
    import 桌宠 as main
    mem = str(tmp_path / "memory.json")
    monkeypatch.setattr(main, "MEMORY_PATH", mem)
    monkeypatch.setattr(pet_chat.requests, "post", lambda *a, **kw: _Resp("我在的~"))
    pet = _FakePet()
    pet._chat_history = [("user", "早"), ("assistant", "早呀")]
    pet_chat.write_memory(mem, pet._chat_history, 10)

    started = threading.Event()
    go = threading.Event()

    if legacy_saver:
        def saver(hist):
            started.set()
            assert go.wait(10), "测试没有放行落盘"
            return main.save_chat_memory(hist)
    else:
        def saver(hist, expect_epoch=None, epoch_of=None):
            started.set()
            assert go.wait(10), "测试没有放行落盘"
            return main.save_chat_memory(hist, expect_epoch=expect_epoch, epoch_of=epoch_of)

    chat = pet_chat.ChatService(
        pet, _FakeSignals(),
        lambda: {"api_key": "k", "ai_reply_len": 60, "ai_max_tokens": 60,
                 "chat_memory_rounds": 3, "sound": False},
        lambda c: "人设", lambda t: ("", "", t), lambda: [], saver,
        lambda k: None, lambda m: None, 60)
    t = threading.Thread(target=chat._worker, args=("你好", "k"))
    t.start()
    assert started.wait(10), "worker 没有走到落盘"
    # 用户此刻点「清理日志」：顺序与修复后的 桌宠._clear_logs 一致（先 +1，再写盘）
    with pet._history_lock:
        pet._chat_history.clear()
        pet._mem_epoch += 1
    pet_chat.write_memory(mem, [], 10)
    go.set()
    t.join(10)
    return pet_chat.read_memory(mem, 10), list(pet._chat_history)


def test_clear_logs_worker_does_not_write_back(tmp_path, monkeypatch):
    """P1-A 端到端：清日志之后，在途 worker 的旧快照不得把 4 条 history 写回来。

    窗口放大：注入的 memory_saver 先等事件再落盘（实测 200ms 延迟就足够复现）。
    """
    hist, mem = _clear_logs_race(tmp_path, monkeypatch)
    assert hist == [], "清日志之后在途 worker 又把历史写回来了：%r" % (hist,)
    assert mem == []


def test_clear_logs_legacy_saver_still_has_the_window(tmp_path, monkeypatch):
    """对照：只收 1 个参数的旧式注入没有代次契约 → 这条窗口依然存在（4 条被写回）。

    这条绿恰恰说明上面那条不是恒真的：窗口是真的，挡住它的是代次守卫。
    生产注入（桌宠.save_chat_memory）已带契约；第三方替换 memory_saver 时请照抄。
    """
    hist, _mem = _clear_logs_race(tmp_path, monkeypatch, legacy_saver=True)
    assert len(hist) == 4, "窗口没被复现（那 test_clear_logs_worker_does_not_write_back 就不能证明什么）"


def test_book_corrupt_ledger_still_rebuilds(tmp_path):
    """P0-B 的反面：**真损坏**仍然按空账本重建（别把愈合一起改没了）。"""
    (tmp_path / "ledger.json").write_text("{ not json", encoding="utf-8")
    b = pet_book.Book(str(tmp_path))
    assert b.today_usage() == 0.0
    assert _read(tmp_path / "ledger.json")["records"] == [], "启动时没有把坏账本回写成合法结构"


# ---- P0-B 补：读失败之后的"第一次真实写"必须先重试读并合并 ----

def test_book_write_after_read_failure_keeps_disk_records(tmp_path, monkeypatch):
    """P0-B 补（1）：瞬时读失败 → 内存加一笔 → 触发写：磁盘原有记录必须还在。

    旧实现：这次写直接用内存里的空账本+新账覆盖 → 磁盘只剩新那笔（原有记录被挤掉）。
    """
    p = tmp_path / "ledger.json"
    pet_book.Book(str(tmp_path)).add_manual(12.5, "午饭")
    with monkeypatch.context() as m:
        _deny_open(m, "ledger.json")            # 只挡构造时的那一次读
        b = pet_book.Book(str(tmp_path))
        assert b.today_usage() == 0.0
        b.add_manual(1.0, "读失败期间的新账")     # 写前会重试读一次并合并
        assert b._read_failed is False, "恢复之后标记没有清除（会每次写都重读磁盘）"
    notes = {r["note"] for r in _read(p)["records"]}
    assert notes == {"午饭", "读失败期间的新账"}, notes
    assert abs(pet_book.Book(str(tmp_path)).total_amount() - 13.5) < 1e-9


def test_book_write_abandoned_when_read_keeps_failing(tmp_path, monkeypatch):
    """P0-B 补（2）：重试仍然读不到 → 放弃本次落盘（两个文件一字未动 + 返回错误串）。"""
    p = tmp_path / "ledger.json"
    arc = tmp_path / "ledger_archive.json"
    pet_book.Book(str(tmp_path)).add_manual(12.5, "午饭")
    raw_led, raw_arc = _read_bytes(p), _read_bytes(arc)
    with monkeypatch.context() as m:
        _deny_open(m, "ledger.json", times=None)     # 持续读不到
        b = pet_book.Book(str(tmp_path))
        b.add_manual(1.0, "不该覆盖")                # 走完整公开路径
        assert _read_bytes(p) == raw_led, "读不到还是把内存账本写上去了"
        assert _read_bytes(arc) == raw_arc, "读不到还是把归档写上去了"
        err = b._save_all()                          # 直接问错误串
        assert isinstance(err, str) and err, err
        assert b._read_failed is True, "放弃落盘后必须保持脏标记"
    # 读恢复之后：延后的那笔 + 新的一笔一起落盘，磁盘原有记录仍在（去重后不重复）
    b.add_manual(2.0, "恢复后的新账")
    notes = {r["note"] for r in _read(p)["records"]}
    assert notes == {"午饭", "不该覆盖", "恢复后的新账"}, notes


def test_book_recovery_merges_without_duplicates(tmp_path, monkeypatch):
    """P0-B 补（3）：恢复合并要去重——磁盘与内存里的同一条（ts/amount/note 相同）不写两条。"""
    p = tmp_path / "ledger.json"
    pet_book.Book(str(tmp_path)).add_manual(12.5, "午饭")
    dupe = dict(_read(p)["records"][0])
    with monkeypatch.context() as m:
        _deny_open(m, "ledger.json")
        b = pet_book.Book(str(tmp_path))
        b._ledger["records"].append(dict(dupe))      # 内存里已经有与磁盘同一条
        b.add_manual(1.0, "新账")
        assert b._read_failed is False
    recs = _read(p)["records"]
    assert len(recs) == 2, recs
    assert {r["note"] for r in recs} == {"午饭", "新账"}, recs


def test_book_merge_records_dedupe_key_is_triple():
    """去重键 = (ts, amount, note)：同一条只留一份；同额同备注但 ts 不同 = 两笔真账。"""
    r1 = {"ts": 1.0, "date": "2026-01-01", "time": "00:00:00", "amount": 1.0,
          "kind": "manual", "note": "x"}
    r2 = dict(r1, ts=2.0)
    assert pet_book._merge_records([r1], [r1, r2]) == [r1, r2]
    assert pet_book._merge_records([], [r1]) == [r1]
    assert pet_book._merge_records([r1], []) == [r1]


# ---- P2-A：音频魔数 ----

def test_audio_magics_accept_common_containers():
    """P2-A：m4a(ftyp 在偏移 4)/webm(EBML)/aac-adif 等合法格式不得被静默拒播。"""
    assert all(len(m) == 4 for m in pet_voice.AUDIO_MAGICS), \
        "AUDIO_MAGICS 里还有 2 字节死项（对 4 字节 head 永远匹配不上）"
    good_samples = (
        b"RIFF....", b"ID3\x04\x00\x00", b"OggS\x00\x02\x00\x00",
        b"fLaC\x00\x00\x00\x00", b"FORM....AIFF", b"ADIF....", b"#!AMR\n\x00",
        b"MThd\x00\x00\x00\x06", b"MAC \x00\x00\x00\x00", b"wvpk\x00\x00\x00\x00",
        b"\x1a\x45\xdf\xa3\x01\x00\x00\x00",        # webm/mkv（EBML）
        b"\xff\xfb\x90\x00", b"\xff\xf1\x50\x00",    # MPEG / AAC 帧同步
        b"\x00\x00\x00\x20ftypM4A ", b"\x00\x00\x00\x18ftypmp42",   # m4a / mp4
    )
    for good in good_samples:
        assert pet_voice._looks_like_audio(good), good
    for bad in (b"<html><body>404 not found</body>", b'{"error": "invalid api key"}',
                b"Not Found\n", b"", b"abc", b"   \r\n"):
        assert not pet_voice._looks_like_audio(bad), bad


def test_decode_json_audio_http_branch_checks_magic(monkeypatch):
    """M4：audio 以 http 开头那条分支此前漏了魔数校验（HTML 错误页会被当音频缓存）。"""
    class _HttpResp:
        def __init__(self, body):
            self.status_code = 200
            self.content = body

    def _resp(payload):
        class _R:
            def json(self):
                return payload
        return _R()

    monkeypatch.setattr(pet_voice.requests, "get",
                        lambda url, timeout=None: _HttpResp(b"<html>404</html>"))
    data, err = pet_voice._decode_json_audio(_resp({"audio": "http://x/a.wav"}), "F5-TTS")
    assert data is None and "不是音频数据" in err, (data, err)

    monkeypatch.setattr(pet_voice.requests, "get",
                        lambda url, timeout=None: _HttpResp(b"\x00\x00\x00\x20ftypM4A \x00\x00"))
    data2, err2 = pet_voice._decode_json_audio(_resp({"audio": "http://x/a.m4a"}), "F5-TTS")
    assert err2 == "" and data2.startswith(b"\x00\x00\x00\x20ftyp"), (data2, err2)


# ---- pet_io 细节：分锁 / factory 兜底 / tmp 清扫 ----

def test_path_lock_merges_case_variants(tmp_path):
    """L1：Windows/macOS 大小写不敏感——x.json 与 X.JSON 必须是同一把锁。"""
    p = str(tmp_path / "X.json")
    if os.name == "nt":
        assert pet_io.path_lock(p) is pet_io.path_lock(p.upper())
        assert pet_io.path_lock(p) is pet_io.path_lock(p.lower())
    else:
        assert pet_io.path_lock(p) is pet_io.path_lock(p)     # 同路径恒同锁


def test_factory_exception_never_escapes(tmp_path):
    """M3：本模块承诺「绝不抛」，factory 自己抛异常也不能穿透（退回空结构 + 记日志）。"""
    def boom():
        raise RuntimeError("factory 坏了")

    p = str(tmp_path / "missing.json")
    logs = []
    assert pet_io.read_json_or(p, boom, log=logs.append) == ({}, False)   # 文件不存在
    with open(p, "w", encoding="utf-8") as f:
        f.write("{ broken")
    assert pet_io.read_json_or(p, boom, log=logs.append) == ({}, True)    # 真损坏
    assert pet_io.heal_json(p, boom, log=logs.append) == ({}, True)       # 愈合也不抛
    assert _read(p) == {}                                                 # 退回空结构
    assert logs, "默认值构造失败必须留痕"


def test_clean_tmp_files_only_removes_whitelisted_names(tmp_path):
    """L4：线程唯一 tmp（<p>.<tid>.tmp）与旧固定名都要能清；非白名单文件一律不碰。"""
    target = tmp_path / "lines.json"
    target.write_text("{}", encoding="utf-8")
    (tmp_path / "lines.json.tmp").write_text("x", encoding="utf-8")          # 旧固定名
    (tmp_path / "lines.json.12345.tmp").write_text("x", encoding="utf-8")    # 线程唯一名
    keep = [tmp_path / "lines.json.abc.tmp", tmp_path / "lines.json.bak",
            tmp_path / "other.json.123.tmp"]
    for k in keep:
        k.write_text("x", encoding="utf-8")
    removed = pet_io.clean_tmp_files((str(target),), log=lambda m: None)
    assert removed == 2, removed
    assert not (tmp_path / "lines.json.tmp").exists()
    assert not (tmp_path / "lines.json.12345.tmp").exists()
    for k in keep:
        assert k.exists(), "清扫动了白名单外的文件：%s" % k


# ---- M5：closeEvent 在真退出/关机时必须放行 ----

def test_close_event_accepts_during_real_quit():
    """M5：注销/关机（或已在退出流程中）不能 ignore 关窗事件，否则 Windows 会认为
    程序阻止关机。普通 Alt+F4 仍然只收进托盘。"""
    import 桌宠 as main

    class _Ev:
        def __init__(self):
            self.actions = []

        def accept(self):
            self.actions.append("accept")

        def ignore(self):
            self.actions.append("ignore")

    class _Stub:
        closeEvent = main.PetWindow.closeEvent
        _system_is_quitting = main.PetWindow._system_is_quitting

        def __init__(self):
            self._closing = False
            self.hidden = 0
            self.quit_calls = 0

        def hide(self):
            self.hidden += 1

        def show_bubble(self, text):
            pass

        def _quit(self):
            self.quit_calls += 1

    s = _Stub()
    ev = _Ev()
    s.closeEvent(ev)                      # 普通关窗 → 收进托盘
    assert ev.actions == ["ignore"] and s.hidden == 1 and s.quit_calls == 0

    s2 = _Stub()
    s2._closing = True                    # 托盘「退出」已进入退出流程
    ev2 = _Ev()
    s2.closeEvent(ev2)
    assert ev2.actions == ["accept"], ev2.actions
    assert s2.quit_calls == 1 and s2.hidden == 0


# ---- L6：固定名 .tmp 落盘点的静态回归 ----

# 允许名单：只有原子写实现本体可以出现裸 ".tmp" 后缀（clean_tmp_files 要按后缀枚举）；
# 其余文件里出现不带 %s/%d 格式化的 ".tmp" 字符串常量 = 固定名临时文件（回归）。
_TMP_SCAN_ALLOW = {"pet_io.py"}
_TMP_SCAN_SKIP = {"_check_static.py", "_check_release.py", "_verify_v13.py", "_verify_green.py"}


def test_no_fixed_tmp_literals_in_source():
    """L6：全仓（除本测试与被跳过的开发脚本）不得再出现**固定名** .tmp 落盘点。

    判据（AST，注释天然不参与）：非 docstring 的字符串常量含 ".tmp" 时，
    必须带 %s/%d 格式化（即 <path>.<线程号>.tmp 这类线程唯一名）。
    旧写法 [路径变量] + ".tmp" 与 "lines.json.tmp" 都会被抓出来。
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bad = []
    ok = []
    for name in sorted(os.listdir(root)):
        if not name.endswith(".py") or name in _TMP_SCAN_SKIP or name in _TMP_SCAN_ALLOW:
            continue
        with open(os.path.join(root, name), encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)
        docstrings = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)):
                docstrings.add(id(node.value))       # 裸字符串说明（docstring）：不是代码
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if ".tmp" not in node.value or id(node) in docstrings:
                continue
            if re.search(r"%[sd]", node.value):
                ok.append("%s:%d" % (name, node.lineno))
                continue
            bad.append("%s:%d %r" % (name, node.lineno, node.value))
    assert ok, "扫描没找到任何线程唯一临时名（判据失效，这条绿不可信）"
    assert not bad, "仍有固定名 .tmp 字面量：%s" % "; ".join(bad)



