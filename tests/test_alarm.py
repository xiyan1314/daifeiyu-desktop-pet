# -*- coding: utf-8 -*-
"""v2.0.5 闹钟系统回归：时间校验/到点判定/CRUD/持久化容错/铃声导入/预留字段透传。

纯逻辑，无需 Qt。
"""
import json
import os

import pet_alarm


def test_valid_and_normalize_time():
    assert pet_alarm.valid_time("00:00") and pet_alarm.valid_time("23:59")
    assert pet_alarm.valid_time("07:30")
    for bad in ("24:00", "12:60", "7:5", "abc", "", None, "12:3x"):
        assert not pet_alarm.valid_time(bad), bad
    assert pet_alarm.normalize_time("07:05") == "07:05"
    # v2.3.1（P1-1）：normalize_time 改为**宽松补零**（valid_time 仍是严格最终判据）——
    # 历史/手编数据里的 "7:5"/"8:0"/带秒格式此前被直接丢弃
    assert pet_alarm.normalize_time("7:5") == "07:05"
    assert pet_alarm.normalize_time("8:0") == "08:00"
    assert pet_alarm.normalize_time("07:30:00") == "07:30"
    assert pet_alarm.normalize_time("24:00") == "" and pet_alarm.normalize_time("abc") == ""


def test_due_alarms_semantics():
    base = {"id": "a1", "time": "08:00", "label": "x", "enabled": True,
            "ringtone": "", "last_fired_date": ""}
    # 未到点
    assert pet_alarm.due_alarms([base], "07:59", "2026-09-30") == []
    # 到点（now >= time）
    due = pet_alarm.due_alarms([base], "08:00", "2026-09-30")
    assert len(due) == 1 and due[0][1] == "08:00"
    # 同日已触发 → 不再响
    base2 = dict(base, last_fired_date="2026-09-30")
    assert pet_alarm.due_alarms([base2], "09:00", "2026-09-30") == []
    # 跨天重新待命
    assert pet_alarm.due_alarms([base2], "09:00", "2026-10-01")
    # disabled / 坏时间条目跳过
    assert pet_alarm.due_alarms([dict(base, enabled=False)], "09:00", "2026-09-30") == []
    assert pet_alarm.due_alarms([dict(base, time="bad")], "09:00", "2026-09-30") == []
    assert pet_alarm.due_alarms(["junk"], "09:00", "2026-09-30") == []


def test_crud_roundtrip(tmp_path):
    svc = pet_alarm.AlarmService(str(tmp_path))
    assert svc.list() == []
    a, err = svc.add("07:30", "起床啦")
    assert a is not None and not err, err
    assert len(a["id"]) == 8 and svc.get(a["id"])["label"] == "起床啦"
    # 标签截断
    a2, _ = svc.add("08:00", "x" * 100)
    assert svc.get(a2["id"])["label"] == "x" * pet_alarm.ALARM_LABEL_MAX
    ok, err = svc.update(a["id"], time_s="09:15", label="改名", enabled=False)
    assert ok and not err
    assert svc.get(a["id"])["time"] == "09:15" and svc.get(a["id"])["enabled"] is False
    ok, err = svc.update(a["id"], time_s="25:00")
    assert not ok and "HH:MM" in err
    ok, err = svc.update("nope", label="x")
    assert not ok and "不存在" in err
    # 持久化 roundtrip
    svc2 = pet_alarm.AlarmService(str(tmp_path))
    assert svc2.get(a["id"])["label"] == "改名"
    ok, err = svc2.delete(a["id"])
    assert ok and not err and svc2.get(a["id"]) is None
    ok, err = svc2.delete(a["id"])
    assert not ok and "不存在" in err


def test_add_invalid_and_cap(tmp_path):
    svc = pet_alarm.AlarmService(str(tmp_path))
    a, err = svc.add("bad")
    assert a is None and "HH:MM" in err
    for i in range(pet_alarm.ALARMS_MAX):
        svc.add("%02d:%02d" % (i // 60, i % 60))
    a, err = svc.add("23:59")
    assert a is None and "最多" in err


def test_corrupted_index(tmp_path):
    idx = tmp_path / "alarms.json"
    idx.write_text("{{{ not json", encoding="utf-8")
    svc = pet_alarm.AlarmService(str(tmp_path))
    assert svc.list() == []
    idx.write_text('{"alarms": [{"time": "bad"}]}', encoding="utf-8")
    svc2 = pet_alarm.AlarmService(str(tmp_path))
    assert svc2.list() == []  # 坏时间条目丢弃


def test_mark_fired(tmp_path):
    svc = pet_alarm.AlarmService(str(tmp_path))
    a, _ = svc.add("07:00")
    svc.mark_fired(a["id"], "2026-09-30")
    assert svc.get(a["id"])["last_fired_date"] == "2026-09-30"
    svc.mark_fired("nope", "2026-09-30")  # 不存在：静默无副作用
    assert svc.get(a["id"])["last_fired_date"] == "2026-09-30"


def test_toggle(tmp_path):
    svc = pet_alarm.AlarmService(str(tmp_path))
    a, _ = svc.add("07:00")
    ok, err = svc.toggle(a["id"], False)
    assert ok and not err and svc.get(a["id"])["enabled"] is False
    ok, err = svc.toggle(a["id"], True)
    assert ok and svc.get(a["id"])["enabled"] is True


def test_ringtone_import(tmp_path):
    svc = pet_alarm.AlarmService(str(tmp_path))
    src = tmp_path / "tone.wav"
    src.write_bytes(b"RIFF fake wav data")
    fn, err = svc.import_ringtone(str(src))
    assert fn is not None and not err, err
    assert fn.endswith(".wav") and svc.ringtone_path(fn) is not None
    assert svc.ringtone_path("") is None and svc.ringtone_path("nope.wav") is None
    # 坏扩展/缺失文件
    bad = tmp_path / "tone.txt"
    bad.write_bytes(b"x")
    fn2, err2 = svc.import_ringtone(str(bad))
    assert fn2 is None and "wav/mp3" in err2
    fn3, err3 = svc.import_ringtone(str(tmp_path / "gone.mp3"))
    assert fn3 is None and "不存在" in err3
    # update 的铃声字段校验
    a, _ = svc.add("07:00", ringtone=fn)
    ok, err = svc.update(a["id"], ringtone="x.txt")
    assert not ok and "wav/mp3" in err


def test_reserved_fields_passthrough(tmp_path):
    """repeat/snooze_min 预留字段：导入数据透传不丢（未来版本回填逻辑）。"""
    idx = tmp_path / "alarms.json"
    idx.write_text(json.dumps({"alarms": [{"id": "12345678", "time": "08:00",
                                           "label": "x", "enabled": True,
                                           "ringtone": "", "last_fired_date": "",
                                           "repeat": "daily", "snooze_min": 5}]},
                              ensure_ascii=False), encoding="utf-8")
    svc = pet_alarm.AlarmService(str(tmp_path))
    a = svc.get("12345678")
    assert a is not None
    # 预留字段原样透传：repeat 字符串、snooze_min 非负 int（未来版本直接升级不丢数据）
    assert a["repeat"] == "daily" and a["snooze_min"] == 5


def test_due_multiple_and_midnight():
    base = {"id": "a", "time": "08:00", "enabled": True, "last_fired_date": ""}
    alarms = [dict(base, id="a1", time="08:00"), dict(base, id="a2", time="08:30"),
              dict(base, id="a3", time="23:59")]
    due = pet_alarm.due_alarms(alarms, "23:59", "2026-09-30")
    assert sorted(a["id"] for a, _t in due) == ["a1", "a2", "a3"]  # 同拍到点全触发
    # 跨午夜：次日 00:00 时 23:59 闹钟不得重响（"00:00" >= "23:59" 为假）
    assert pet_alarm.due_alarms(alarms, "00:00", "2026-10-01") == []
    # 00:00 闹钟在新的一天 00:00 触发
    assert len(pet_alarm.due_alarms([dict(base, id="a0", time="00:00")],
                                    "00:00", "2026-10-01")) == 1


def test_norm_alarm_rejects_path_ringtone():
    a, err = pet_alarm.AlarmService._norm_alarm(
        {"id": "x", "time": "08:00", "ringtone": os.path.join("..", "..", "evil.wav")})
    assert a is not None and not err
    assert a["ringtone"] == ""  # 路径注入清洗为默认提示音


def test_ringtone_size_cap(tmp_path):
    svc = pet_alarm.AlarmService(str(tmp_path))
    src = tmp_path / "big.wav"
    src.write_bytes(b"x" * 100)
    svc.RINGTONE_MAX_BYTES = 10  # 收紧阈值验证上限先于读取
    fn, err = svc.import_ringtone(str(src))
    assert fn is None and "太大" in err


def test_due_alarms_compares_structurally_not_as_strings():
    """P3-5（v2.4.1）：到点判定用**分钟数**比较，不再比字符串。

    旧实现 `now >= t` 是字符串比较："7:59" >= "08:00" 为真（'7' > '0'）→ 07:59 就把
    08:00 的闹钟响了；now="abc" 更是全表齐响。生产侧 now_hhmm() 总是补零，所以线上没炸过，
    但 API 一被误用就是"闹钟提前响/乱响"。
    """
    a = {"id": "a1", "time": "08:00", "enabled": True, "last_fired_date": ""}
    # 反例（旧实现必红）：未补零的 now 不得把未来的闹钟提前响
    assert pet_alarm.due_alarms([a], "7:59", "2026-09-30") == []
    # 正例：同一时刻的两种写法都要响，且返回的仍是归一化时间串
    assert pet_alarm.due_alarms([a], "08:00", "2026-09-30")[0][1] == "08:00"
    assert len(pet_alarm.due_alarms([a], "8:00", "2026-09-30")) == 1
    assert pet_alarm.due_alarms([a], "8:00:00", "2026-09-30")[0][1] == "08:00"
    # now 非法 → 一个都不响（旧字符串比较会全表齐响）
    for bad in ("abc", "", None, "25:00", "7"):
        assert pet_alarm.due_alarms([a], bad, "2026-09-30") == [], bad
    # 边界：23:59 的闹钟在当天 23:59 响、次日 00:00 不响（结构化比较的跨午夜口径）
    night = dict(a, time="23:59")
    assert pet_alarm.due_alarms([night], "23:58", "2026-09-30") == []
    assert pet_alarm.due_alarms([night], "23:59", "2026-09-30")
    assert pet_alarm.due_alarms([night], "00:00", "2026-09-30") == []


def test_alarm_load_heals_through_heal_json(tmp_path, monkeypatch):
    """v2.4.1（A 区）：闹钟的愈合环走 pet_io.heal_json（锁内复查 + 统一 .bak/日志口径）。

    变异验证：把 heal_json 换成探针——自建环会绕过它（seen 为空），本条即红。
    """
    import pet_io
    idx = tmp_path / "alarms.json"
    idx.write_text("{{{ not json", encoding="utf-8")
    seen = []
    real = pet_io.heal_json

    def spy(path, factory=dict, **kw):
        seen.append((str(path), kw.get("normalize") is not None))
        return real(path, factory, **kw)

    monkeypatch.setattr(pet_io, "heal_json", spy)
    svc = pet_alarm.AlarmService(str(tmp_path), log=lambda m: None)
    assert svc.list() == []
    assert seen == [(str(idx), True)], "闹钟没走 pet_io.heal_json：%r" % (seen,)
    assert json.loads(idx.read_text(encoding="utf-8")) == {"alarms": []}
    assert (tmp_path / "alarms.json.bak").read_text(encoding="utf-8") == "{{{ not json"


def test_alarm_clean_file_is_not_rewritten(tmp_path, monkeypatch):
    """反面：合法 alarms.json 读一遍**一个字节都不写**（normalize 判据返回空 reason）。"""
    import pet_io
    idx = tmp_path / "alarms.json"
    original = json.dumps({"alarms": [{"id": "a1", "time": "08:00", "label": "起床",
                                       "ringtone": "", "enabled": True,
                                       "last_fired_date": "", "repeat": "", "snooze_min": 0}]},
                          ensure_ascii=False)
    idx.write_text(original, encoding="utf-8")
    writes = []
    real = pet_io.atomic_write_json
    monkeypatch.setattr(pet_io, "atomic_write_json",
                        lambda *a, **kw: (writes.append(a), real(*a, **kw))[1])
    svc = pet_alarm.AlarmService(str(tmp_path), log=lambda m: None)
    assert [x["id"] for x in svc.list()] == ["a1"]
    assert writes == [], "合法文件被重写了（读侧不该有副作用）"
    assert idx.read_text(encoding="utf-8") == original
    assert not (tmp_path / "alarms.json.bak").exists()


def test_alarm_read_failure_writes_nothing(tmp_path, monkeypatch):
    """反面（P0-B 同款保护）：文件在磁盘上但这次读不到 → 不愈合、不写、不留 .bak。

    这条对"改成 heal_json"尤其关键：自建环的写入门槛是 dirty，heal_json 的门槛是
    corrupted/normalize reason——接线错了就会把"读不到"当成"损坏"清空用户的闹钟。
    """
    import builtins
    idx = tmp_path / "alarms.json"
    raw = json.dumps({"alarms": [{"id": "a1", "time": "08:00", "label": "起床"}]},
                     ensure_ascii=False).encode("utf-8")
    idx.write_bytes(raw)
    real_open = builtins.open

    def deny(file, *a, **kw):
        if str(file).endswith("alarms.json"):
            raise PermissionError(13, "Permission denied")
        return real_open(file, *a, **kw)

    monkeypatch.setattr(builtins, "open", deny)
    logs = []
    svc = pet_alarm.AlarmService(str(tmp_path), log=logs.append)
    assert svc.list() == [], "读不到就是读不到：内存按空库继续"
    with real_open(str(idx), "rb") as f:
        assert f.read() == raw, "读不到被当成损坏，回写覆盖了完好闹钟库"
    assert not (tmp_path / "alarms.json.bak").exists(), "没有回写就不该有 .bak"
    assert any("读取失败" in m for m in logs), logs


def test_alarm_heals_only_once_through_normalize(tmp_path):
    """正向：清洗（丢坏条目 / 补零）确实回写；第二次启动零日志（旧日志里刷了 15 次）。"""
    idx = tmp_path / "alarms.json"
    idx.write_text(json.dumps({"alarms": [{"id": "a1", "time": "7:5", "label": "起床"},
                                          {"id": "a2", "time": "bad"}]}, ensure_ascii=False),
                   encoding="utf-8")
    logs = []
    svc = pet_alarm.AlarmService(str(tmp_path), log=logs.append)
    assert [a["id"] for a in svc.list()] == ["a1"] and svc.get("a1")["time"] == "07:05"
    assert any("bad entry" in m for m in logs)
    assert [a["time"] for a in json.loads(idx.read_text(encoding="utf-8"))["alarms"]] == ["07:05"]
    logs2 = []
    pet_alarm.AlarmService(str(tmp_path), log=logs2.append)
    assert logs2 == []
