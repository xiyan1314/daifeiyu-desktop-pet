# -*- coding: utf-8 -*-
"""v2.0.2 行为自定义服务回归：序列校验 / 增删改查 / 持久化容错 / 导入导出 / 待机默认。

纯逻辑，无需 Qt。
"""
import json
import os

import pytest

import pet_behaviors


def _steps_full():
    """覆盖全部 7 种动作类型的合法序列。"""
    return [
        {"act": "play_action", "name": "dance"},
        {"act": "say", "text": "嗨~"},
        {"act": "voice", "event": "poke"},
        {"act": "emote", "kind": "heart"},
        {"act": "form", "name": "第二形态"},
        {"act": "sleep"},
        {"act": "wait", "ms": 300},
    ]


def test_validate_steps_all_acts():
    out, err = pet_behaviors.validate_steps(_steps_full())
    assert err == "" and out is not None
    assert [s["act"] for s in out] == ["play_action", "say", "voice", "emote", "form", "sleep", "wait"]


def test_validate_steps_bad_inputs():
    for bad in (None, {}, "x", []):
        out, err = pet_behaviors.validate_steps(bad)
        assert out is None and err, bad
    out, err = pet_behaviors.validate_steps([{"act": "fly"}])
    assert out is None and "不合法" in err
    out, err = pet_behaviors.validate_steps([{"act": "play_action"}])
    assert out is None and "动作名" in err
    out, err = pet_behaviors.validate_steps([{"act": "say"}])
    assert out is None and "台词" in err
    out, err = pet_behaviors.validate_steps([{"act": "voice", "event": "bark"}])
    assert out is None and "语音事件" in err
    out, err = pet_behaviors.validate_steps([{"act": "emote", "kind": "fire"}])
    assert out is None and "表情" in err


def test_validate_steps_wait_clamp():
    out, _ = pet_behaviors.validate_steps([{"act": "wait", "ms": 50}])
    assert out[0]["ms"] == pet_behaviors.WAIT_MIN_MS
    out, _ = pet_behaviors.validate_steps([{"act": "wait", "ms": 999999}])
    assert out[0]["ms"] == pet_behaviors.WAIT_MAX_MS
    out, _ = pet_behaviors.validate_steps([{"act": "wait", "ms": "abc"}])
    assert out[0]["ms"] == 500  # 非数字回默认
    out, _ = pet_behaviors.validate_steps([{"act": "wait"}])
    assert out[0]["ms"] == 500


def test_validate_steps_cap():
    out, err = pet_behaviors.validate_steps([{"act": "wait"}] * 21)
    assert out is None and "最多" in err


def test_validate_name():
    assert pet_behaviors.validate_name("hello") is True
    assert pet_behaviors.validate_name("Wave2_x") is True
    for bad in ("", "9abc", "bad name", "中文", None, 123, "x" * 25):
        assert pet_behaviors.validate_name(bad) is False, bad


def test_crud_and_roundtrip(tmp_path):
    svc = pet_behaviors.BehaviorService(str(tmp_path))
    assert svc.list() == []
    b, err = svc.add("wave", _steps_full())
    assert b is not None and not err, err
    assert len(b["id"]) == 8 and svc.get(b["id"])["name"] == "wave"
    assert len(svc.list()) == 1
    ok, err = svc.update(b["id"], "wave2", [{"act": "sleep"}])
    assert ok and not err and svc.get(b["id"])["name"] == "wave2"
    ok, err = svc.update("nope", "x", [{"act": "sleep"}])
    assert not ok and "不存在" in err
    # 持久化：重建实例仍可读
    svc2 = pet_behaviors.BehaviorService(str(tmp_path))
    assert svc2.get(b["id"])["steps"] == [{"act": "sleep"}]
    ok, err = svc2.delete(b["id"])
    assert ok and not err and svc2.get(b["id"]) is None
    ok, err = svc2.delete(b["id"])
    assert not ok and "不存在" in err


def test_add_invalid(tmp_path):
    svc = pet_behaviors.BehaviorService(str(tmp_path))
    b, err = svc.add("bad name", [{"act": "sleep"}])
    assert b is None and "不合法" in err
    b, err = svc.add("okname", [{"act": "fly"}])
    assert b is None and "不合法" in err
    assert svc.list() == []


def test_corrupted_index(tmp_path):
    idx = tmp_path / "behaviors.json"
    idx.write_text("{{{ not json", encoding="utf-8")
    svc = pet_behaviors.BehaviorService(str(tmp_path))
    assert svc.list() == []  # 损坏不崩，空库兜底
    # 非 dict 的 json 同样兜底
    idx.write_text("[1,2,3]", encoding="utf-8")
    svc2 = pet_behaviors.BehaviorService(str(tmp_path))
    assert svc2.list() == []


def test_import_export(tmp_path):
    svc = pet_behaviors.BehaviorService(str(tmp_path))
    src = tmp_path / "b.json"
    src.write_text(json.dumps({"behavior": {"id": "12345678", "name": "hi",
                                            "steps": [{"act": "say", "text": "哦嗨哟~"}]}},
                              ensure_ascii=False), encoding="utf-8")
    b, err = svc.import_file(str(src))
    assert b is not None and not err, err
    assert b["name"] == "hi" and b["id"] != "12345678"  # 导入换新 id 防覆盖
    # 全库格式：取第一条
    src2 = tmp_path / "b2.json"
    src2.write_text(json.dumps({"behaviors": [{"id": "87654321", "name": "yo",
                                               "steps": [{"act": "sleep"}]}]},
                               ensure_ascii=False), encoding="utf-8")
    b2, err = svc.import_file(str(src2))
    assert b2 is not None and b2["name"] == "yo"
    # 坏文件
    src3 = tmp_path / "b3.json"
    src3.write_text(json.dumps({"name": "no id", "steps": []}, ensure_ascii=False),
                    encoding="utf-8")
    b3, err = svc.import_file(str(src3))
    assert b3 is None and "不合法" in err
    # 坏结构：behaviors 非数组/空数组 → 明确报错不抛异常
    src4 = tmp_path / "b4.json"
    src4.write_text(json.dumps({"behaviors": {"not": "a list"}}, ensure_ascii=False),
                    encoding="utf-8")
    b4, err = svc.import_file(str(src4))
    assert b4 is None and "非空数组" in err
    src5 = tmp_path / "b5.json"
    src5.write_text(json.dumps({"behaviors": []}, ensure_ascii=False), encoding="utf-8")
    b5, err = svc.import_file(str(src5))
    assert b5 is None and "非空数组" in err
    # 导出 roundtrip
    out = tmp_path / "out.json"
    ok, err = svc.export_file(b["id"], str(out))
    assert ok and not err and json.loads(out.read_text(encoding="utf-8"))["behavior"]["name"] == "hi"
    ok, err = svc.export_file("nope", str(out))
    assert not ok and "不存在" in err


def test_idle_default_off(tmp_path):
    svc = pet_behaviors.BehaviorService(str(tmp_path))
    assert svc.idle(lambda: {}) is None  # 未配置 → 现行为等价
    b, _ = svc.add("idle1", [{"act": "say", "text": "发呆中"}])
    got = svc.idle(lambda: {"idle_behavior": b["id"]})
    assert got is not None and got["name"] == "idle1"
    assert svc.idle(lambda: {"idle_behavior": "deadbeef"}) is None  # id 不存在 → 现行为
    assert svc.idle(lambda: None) is None


def test_default_cfg_sane():
    d = pet_behaviors.DEFAULT_BEHAVIOR_CFG
    assert d["idle_behavior"] == ""
    # 上界不变量：≤ 入睡阈值 60，否则待机行为永远不可达
    assert pet_behaviors.IDLE_SECS_MIN <= d["idle_behavior_seconds"] <= pet_behaviors.IDLE_SECS_MAX
    assert pet_behaviors.TRANSFORM_SECS_MIN <= d["transform_seconds"] <= pet_behaviors.TRANSFORM_SECS_MAX


# A11 去重（v2.4.2，代理 Q）：这里原本是 test_voice_events_match_pet_voice——
# tuple(BEHAVIOR_VOICE_EVENTS) == tuple(VOICE_EVENTS)，与
# tests/test_constants_sync.py::test_voice_events_match 同一句（那一处是严格等值 + 两侧
# 容器类型断言，更强）。跨模块常量同步归 test_constants_sync.py 这一处维护，不再两份。
