# -*- coding: utf-8 -*-
"""v2.1 行为/待机回归：两触发配置、待机动作列表、四种播放模式、speak 步骤。"""
import os

import pet_behaviors as pb


def test_validate_speak_steps():
    ok, err = pb.validate_steps([{"act": "speak_line", "line_id": "bi_idle_01"}])
    assert ok and not err, err
    assert ok[0]["line_id"] == "bi_idle_01"
    ok2, _ = pb.validate_steps([{"act": "speak_dialogue", "dialogue_id": "d1"}])
    assert ok2 and ok2[0]["dialogue_id"] == "d1"
    assert pb.validate_steps([{"act": "speak_line"}])[0] is None
    assert pb.validate_steps([{"act": "speak_dialogue"}])[0] is None
    assert "speak_line" in pb.BEHAVIOR_ACTS and "speak_dialogue" in pb.BEHAVIOR_ACTS


def test_normalize_idle_cfg_defaults_and_clamp():
    n = pb.normalize_idle_cfg({})
    assert n["idle_trigger_delay"] == 8 and n["idle_delay_after_full"] == 2
    assert n["idle_play_mode"] == "sequential" and n["idle_actions"] == []
    assert n["idle_form"] == ""
    n2 = pb.normalize_idle_cfg({"idle_trigger_delay": 999, "idle_delay_after_full": -5,
                                "idle_play_mode": "ghost", "idle_form": "f2"})
    assert n2["idle_trigger_delay"] == pb.IDLE_TRIGGER_MAX
    assert n2["idle_delay_after_full"] == pb.IDLE_AFTER_FULL_MIN
    assert n2["idle_play_mode"] == "sequential" and n2["idle_form"] == "f2"


def test_normalize_idle_cfg_legacy_migration():
    # v2.0.2 旧键 idle_behavior + idle_behavior_seconds 迁移
    n = pb.normalize_idle_cfg({"idle_behavior": "abc12345", "idle_behavior_seconds": 30})
    assert n["idle_trigger_delay"] == 30
    assert [a["behavior_id"] for a in n["idle_actions"]] == ["abc12345"]
    assert n["idle_play_mode"] == "single"  # 单条兼容旧的单动作行为
    # 新键优先于旧键
    n2 = pb.normalize_idle_cfg({"idle_trigger_delay": 5, "idle_behavior_seconds": 30})
    assert n2["idle_trigger_delay"] == 5
    # 老配置 20 秒（v2.0.2 默认）在 60 秒上限内保持
    n3 = pb.normalize_idle_cfg({"idle_behavior_seconds": 20})
    assert n3["idle_trigger_delay"] == 20


def test_pick_idle_action_modes():
    acts = [{"id": "a", "behavior_id": "a", "enabled": True, "weight": 1, "order": 1},
            {"id": "b", "behavior_id": "b", "enabled": True, "weight": 3, "order": 2},
            {"id": "c", "behavior_id": "c", "enabled": False, "weight": 1, "order": 3}]
    assert pb.pick_idle_action(acts, "single")["id"] == "a"
    assert pb.pick_idle_action(acts, "sequential", "a")["id"] == "b"
    assert pb.pick_idle_action(acts, "sequential", "b")["id"] == "a"  # c 被禁用，循环回 a
    assert pb.pick_idle_action(acts, "random")["id"] in ("a", "b")
    assert pb.pick_idle_action(acts, "weighted")["id"] in ("a", "b")
    assert pb.pick_idle_action(acts, "sequential", "zzz")["id"] == "a"
    assert pb.pick_idle_action([], "sequential") is None
    assert pb.pick_idle_action([{"id": "x", "behavior_id": "x", "enabled": False}],
                              "random") is None
    # 避免连播：只有两条时 random 不会选到 last
    for _ in range(30):
        assert pb.pick_idle_action(acts, "random", "a")["id"] == "b"


def test_idle_action_crud(tmp_path):
    cfg = {}
    assert pb.add_idle_action(cfg, "")[0] is None
    a, err = pb.add_idle_action(cfg, "bid1", 2.5)
    assert a is not None and not err, err
    assert cfg["idle_actions"][0]["weight"] == 2.5
    assert pb.add_idle_action(cfg, "bid1")[0] is None  # 重复拒绝
    b, _ = pb.add_idle_action(cfg, "bid2")
    assert [x["behavior_id"] for x in cfg["idle_actions"]] == ["bid1", "bid2"]
    assert pb.move_idle_action(cfg, b["id"], -1)[0] is True
    assert [x["behavior_id"] for x in cfg["idle_actions"]] == ["bid2", "bid1"]
    assert pb.update_idle_action(cfg, b["id"], weight=0.01)[0] is True
    assert cfg["idle_actions"][0]["weight"] == pb.IDLE_WEIGHT_MIN
    assert pb.update_idle_action(cfg, b["id"], weight=99)[0] is True
    assert cfg["idle_actions"][0]["weight"] == pb.IDLE_WEIGHT_MAX
    assert pb.update_idle_action(cfg, "nope", enabled=False)[0] is False
    assert pb.remove_idle_action(cfg, b["id"]) == (True, "")
    assert len(cfg["idle_actions"]) == 1


def test_service_idle_pick_and_config(tmp_path):
    svc = pb.BehaviorService(str(tmp_path))
    b1, _ = svc.add("w1", [{"act": "say", "text": "一"}])
    b2, _ = svc.add("w2", [{"act": "say", "text": "二"}])
    cfg = {"idle_actions": [
        {"id": b1["id"], "behavior_id": b1["id"], "enabled": True, "weight": 1, "order": 1},
        {"id": b2["id"], "behavior_id": b2["id"], "enabled": True, "weight": 1, "order": 2},
    ], "idle_play_mode": "sequential"}
    got, aid, err = svc.idle_pick(lambda: cfg, None)
    assert got["id"] == b1["id"] and aid == b1["id"] and not err
    got2, aid2, _ = svc.idle_pick(lambda: cfg, aid)
    assert got2["id"] == b2["id"]
    assert svc.idle_config(lambda: cfg)["idle_trigger_delay"] == 8
    # 列表里全是失效行为 → 明确原因（不静默）
    cfg2 = {"idle_actions": [{"id": "ghost", "behavior_id": "ghost", "enabled": True}]}
    got3, _aid3, err3 = svc.idle_pick(lambda: cfg2, None)
    assert got3 is None and "重新选" in err3
    # 空列表 → 无待机（err 为空，静默不算失败）
    got4, _a4, err4 = svc.idle_pick(lambda: {}, None)
    assert got4 is None and err4 == ""
    # 旧键兼容：idle_behavior 单条
    cfg3 = {"idle_behavior": b1["id"]}
    got5, _a5, _e5 = svc.idle_pick(lambda: cfg3, None)
    assert got5["id"] == b1["id"]
