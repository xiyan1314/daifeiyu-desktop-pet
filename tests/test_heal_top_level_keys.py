# -*- coding: utf-8 -*-
"""v2.4.2 回归（代理 Q · 缺陷收口）：本模块写盘不得丢【顶层】未知键。

缺陷（HEAD 实测）：条目级未知键早在 v2.3.1 就保留了（_norm_alarm / _norm_behavior
都是"复制原条目再覆盖已知键"，实测 memo 在），但**顶层**从来没人管：

  · 愈合回写是整份重建 `{"alarms": [...]}` / `{"behaviors": [...]}`；
  · 普通 _save 同样是整份重建。

结果是用户手加的自定义段 / 未来版本写进同一个文件的新键，会在"读一次就愈合"这一步
（甚至只是加一个闹钟）静默消失，且没有任何日志。

判据（每条都要求三件事同时成立，缺一即红）：
  ① 坏条目**没有**回到盘上（愈合真的发生了，不是没动手）；
  ② 顶层未知键**还在**，值逐位相同；
  ③ 第二次 _load 幂等——零写盘（mtime 不变）、零日志。

反例对照（变异验证见 _dev/mutate_check.py，M-Q1/M-Q2/M-Q3/M-Q4）：
  · 把 fixed = dict(data) 换回 `{"alarms": ...}` 原地重建 → 用例 1/2 立刻变红；
  · 把 _save 的 `dict(self._top_extra)` 换回原地重建 → 用例 3/4 立刻变红。
"""
import json

import pet_alarm
import pet_behaviors

# 顶层未知键：一个"用户手加的段"，一个"未来版本的新键"（形状刻意不同：dict / list）
CUSTOM_SECTION = {"user_note": "我手加的段", "n": 1}
FUTURE_KEY = ["v9", "预留"]


def _read(p):
    with open(str(p), "r", encoding="utf-8") as f:
        return json.load(f)


def _write(p, obj):
    raw = json.dumps(obj, ensure_ascii=False)
    p.write_text(raw, encoding="utf-8")
    return raw


# ---------------- 闹钟 ----------------

def test_alarm_heal_keeps_top_level_unknown_keys(tmp_path):
    """愈合丢掉坏条目，但顶层自定义段/未来键必须原样留下；第二次读零写盘。"""
    idx = tmp_path / "alarms.json"
    _write(idx, {
        "alarms": [
            {"id": "a1", "time": "07:30", "label": "起床"},
            {"id": "a2", "time": "不是时间"},          # 坏条目：必须被丢
        ],
        "custom_section": CUSTOM_SECTION,
        "future_key": FUTURE_KEY,
    })
    logs = []
    svc = pet_alarm.AlarmService(str(tmp_path), log=logs.append)
    assert [a["id"] for a in svc.list()] == ["a1"], "好闹钟没留下"
    assert any("bad entry" in m for m in logs), "坏条目被丢却没有留痕"

    on_disk = _read(idx)
    assert [a["id"] for a in on_disk["alarms"]] == ["a1"], "愈合没有把坏条目清掉"
    assert "a2" not in json.dumps(on_disk, ensure_ascii=False), \
        "已删除的坏条目被愈合回写带回了盘上"
    assert on_disk.get("custom_section") == CUSTOM_SECTION, \
        "顶层自定义段在愈合回写时被删掉了（整份重建的老口径）"
    assert on_disk.get("future_key") == FUTURE_KEY, "顶层未知键丢了"

    # 幂等：第二次 _load 一个字节都不写、一条日志都没有
    before_mtime = idx.stat().st_mtime_ns
    before_bytes = idx.read_bytes()
    logs2 = []
    svc2 = pet_alarm.AlarmService(str(tmp_path), log=logs2.append)
    assert [a["id"] for a in svc2.list()] == ["a1"]
    assert logs2 == [], "第二次加载又报了一次（愈合没生效）：%r" % (logs2,)
    assert idx.stat().st_mtime_ns == before_mtime, "第二次加载重写了文件"
    assert idx.read_bytes() == before_bytes


def test_alarm_unknown_top_key_survives_user_edits(tmp_path):
    """顶层未知键不只在愈合那一刻保留：用户加/删闹钟（走 _save）之后也必须还在。"""
    idx = tmp_path / "alarms.json"
    _write(idx, {"alarms": [], "custom_section": CUSTOM_SECTION, "future_key": FUTURE_KEY})
    svc = pet_alarm.AlarmService(str(tmp_path), log=lambda m: None)
    a, err = svc.add("08:00", "上班")
    assert a is not None and not err, err
    on_disk = _read(idx)
    assert [x["id"] for x in on_disk["alarms"]] == [a["id"]]
    assert on_disk.get("custom_section") == CUSTOM_SECTION, "新增闹钟把顶层自定义段覆盖掉了"
    assert on_disk.get("future_key") == FUTURE_KEY, "新增闹钟把顶层未知键覆盖掉了"
    assert svc.delete(a["id"]) == (True, "")
    on_disk = _read(idx)
    assert on_disk["alarms"] == []
    assert on_disk.get("custom_section") == CUSTOM_SECTION, "删除闹钟把顶层自定义段覆盖掉了"


# ---------------- 行为库 ----------------

def test_behaviors_heal_keeps_top_level_unknown_keys(tmp_path):
    """行为库同口径：坏条目（未知动作）被丢，顶层未知键留下；第二次读零写盘。"""
    idx = tmp_path / "behaviors.json"
    _write(idx, {
        "behaviors": [
            {"id": "12345678", "name": "keep_me",
             "steps": [{"act": "play_action", "name": "jump"}]},
            {"id": "87654321", "name": "drop_me", "steps": [{"act": "fly"}]},  # 未知动作：丢
        ],
        "custom_section": CUSTOM_SECTION,
        "future_key": FUTURE_KEY,
    })
    logs = []
    svc = pet_behaviors.BehaviorService(str(tmp_path), log=logs.append)
    assert [b["id"] for b in svc.list()] == ["12345678"]
    assert any("fly" in m for m in logs), "坏条目被丢却没有留痕"

    on_disk = _read(idx)
    assert [b["id"] for b in on_disk["behaviors"]] == ["12345678"], "愈合没有把坏条目清掉"
    assert "87654321" not in json.dumps(on_disk, ensure_ascii=False), \
        "已删除的坏条目被愈合回写带回了盘上"
    assert on_disk.get("custom_section") == CUSTOM_SECTION, \
        "顶层自定义段在愈合回写时被删掉了（整份重建的老口径）"
    assert on_disk.get("future_key") == FUTURE_KEY, "顶层未知键丢了"

    before_mtime = idx.stat().st_mtime_ns
    before_bytes = idx.read_bytes()
    logs2 = []
    svc2 = pet_behaviors.BehaviorService(str(tmp_path), log=logs2.append)
    assert [b["id"] for b in svc2.list()] == ["12345678"]
    assert logs2 == [], "第二次加载又报了一次（愈合没生效）：%r" % (logs2,)
    assert idx.stat().st_mtime_ns == before_mtime, "第二次加载重写了文件"
    assert idx.read_bytes() == before_bytes


def test_behaviors_unknown_top_key_survives_user_edits(tmp_path):
    """行为库同口径：增删行为（走 _save）之后顶层未知键仍在。"""
    idx = tmp_path / "behaviors.json"
    _write(idx, {"behaviors": [], "custom_section": CUSTOM_SECTION, "future_key": FUTURE_KEY})
    svc = pet_behaviors.BehaviorService(str(tmp_path), log=lambda m: None)
    b, err = svc.add("wave", [{"act": "wait", "ms": 200}])
    assert b is not None and not err, err
    on_disk = _read(idx)
    assert [x["id"] for x in on_disk["behaviors"]] == [b["id"]]
    assert on_disk.get("custom_section") == CUSTOM_SECTION, "新增行为把顶层自定义段覆盖掉了"
    assert on_disk.get("future_key") == FUTURE_KEY, "新增行为把顶层未知键覆盖掉了"
    assert svc.delete(b["id"]) == (True, "")
    on_disk = _read(idx)
    assert on_disk["behaviors"] == []
    assert on_disk.get("future_key") == FUTURE_KEY, "删除行为把顶层未知键覆盖掉了"
