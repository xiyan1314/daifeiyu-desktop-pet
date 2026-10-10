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
import json
import os
import threading
import time

import pet_alarm
import pet_behaviors
import pet_chat
import pet_io
import pet_resources


def _read(path):
    with open(str(path), "r", encoding="utf-8") as f:
        return json.load(f)


def _tmp_leftovers(d):
    return [f for f in os.listdir(str(d)) if f.endswith(".tmp")]


# ---------------- 1. pet_io：并发与原子性 ----------------

def test_concurrent_writes_keep_file_valid(tmp_path):
    """根因 A：多线程 × 多次写同一路径，读回恒为合法 JSON（固定 .tmp 无锁会半截上盘）。"""
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


def test_concurrent_readers_never_see_partial_json(tmp_path):
    """写者不停替换文件时，读者永远只能读到合法 JSON（os.replace 原子提交）。

    注：Windows 上读者恰好撞上 rename 会拿到**瞬时** PermissionError（共享冲突）——
    那是"这次读没读到"，不是"读到半截"；读侧重试即可（生产读侧 read_json_or 按
    OSError 降级且不愈合，不会用空结构覆盖好文件）。真问题是 JSONDecodeError。
    """
    p = str(tmp_path / "memory.json")
    pet_io.atomic_write_json(p, {"history": []})
    stop = threading.Event()
    bad = []

    def reader():
        while not stop.is_set():
            try:
                _read(p)
            except OSError:
                time.sleep(0.001)      # 瞬时共享冲突：重试
            except Exception as e:     # JSONDecodeError / UnicodeDecodeError = 读到半截
                bad.append(repr(e))
                return

    def writer():
        for i in range(60):
            pet_io.atomic_write_json(p, {"history": [["user", "m%d" % i]], "pad": "y" * 500})

    readers = [threading.Thread(target=reader) for _ in range(3)]
    w = threading.Thread(target=writer)
    for t in readers:
        t.start()
    w.start()
    w.join(30)
    stop.set()
    for t in readers:
        t.join(5)
    assert not bad, bad


def test_tmp_name_uses_thread_id_and_is_cleaned_on_failure(tmp_path, monkeypatch):
    """临时名必须是 "<path>.<线程号>.tmp"，写失败时自己的 tmp 必须被清掉。"""
    p = str(tmp_path / "x.json")
    seen = []
    real_replace = os.replace

    def spy(src, dst):
        seen.append(os.path.basename(src))
        return real_replace(src, dst)

    monkeypatch.setattr(pet_io.os, "replace", spy)
    assert pet_io.atomic_write_json(p, {"a": 1}) is None
    assert seen == ["x.json.%d.tmp" % threading.get_ident()]

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


def test_memory_history_and_long_term_survive_concurrent_writes(tmp_path):
    """P1-1：读-改-写在同一把锁内完成——两个写者不再用旧快照互相覆盖。"""
    p = str(tmp_path / "memory.json")
    pet_chat.write_memory(p, [("user", "hi")], 10)

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
