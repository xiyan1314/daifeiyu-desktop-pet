# -*- coding: utf-8 -*-
"""v2.9.0 · 代理 B（行为/配置后端与契约）的回归用例。

B1 · 动作候选集合的唯一来源（`pet_behaviors.action_choices`）——A 的行为设置
     「动作」可编辑下拉就吃这个接口，所以这里的判据全部是**接口契约**，不是实现细节：
       ① 候选里同时有自定义动作与内建动作；
       ② **默认角色（没有自定义角色）时也有候选**（内建动作恒在）——这条是硬要求，
          否则"默认角色不能加动作"这个功能缺失没被解决；
       ③ 候选是"候选"不是白名单：含未知动作名的老行为文件，候选里没有它，
          但**读入 → 保存 → 重新加载之后它仍在**（下拉不许吃掉它）。
     变异：把 action_choices 的候选来源换成空列表 → ①② 必红。

判据全部是结构性事实（集合成员 / 排序 / 磁盘内容），不看墙钟、不依赖机器速度。
"""
import json
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pet_behaviors as pb          # noqa: E402
import pet_resources as pr          # noqa: E402


# ---------------- B1：候选集合 ----------------

class _StubPet(object):
    """最小替身：只要 custom_actions() / anim._sets 两个读取点（接口就是这两个）。"""

    def __init__(self, customs=None, sets=None):
        self._customs = list(customs or [])
        self.anim = type("_Anim", (), {"_sets": dict(sets or {})})()

    def custom_actions(self):
        return list(self._customs)


def test_action_choices_always_has_builtins_even_without_custom_actions():
    """② 默认角色（custom_actions() == []）也必须返回内建动作。

    变异：候选来源换成空列表（return []）→ 本条红。
    """
    got = pb.action_choices(_StubPet())
    assert got, "默认角色下候选为空——'默认角色不能加动作'这条功能缺失没有被解决"
    for name in ("jump", "emote"):
        assert name in got, "内建点播分支 %s 不在候选里：%r" % (name, got)
    for name in pr.ANIM_ACTIONS:
        assert name in got, "内建帧动作 %s 不在候选里：%r" % (name, got)


def test_action_choices_includes_custom_actions():
    """① 候选里同时有自定义动作（帧 / 合成）与内建动作。

    变异：候选来源漏掉 custom_actions() → 本条红。
    """
    # 替身**只**供自定义动作：sets 里不放任何内建名 → 下面断言的内建名只可能来自常量来源
    pet = _StubPet(customs=[("dance", "frames"), ("sway", "proc")], sets={"dance": []})
    got = pb.action_choices(pet)
    assert "dance" in got and "sway" in got, "自定义动作没进候选：%r" % (got,)
    assert "jump" in got, "内建点播分支被自定义动作挤掉了：%r" % (got,)
    # "poke" 只可能来自 pet_resources.ANIM_ACTIONS（替身的 customs / sets / jump·emote 都不供它）
    assert "poke" in got, "ANIM_ACTIONS 这一支来源没被隔离到：%r" % (got,)


def test_action_choices_is_deduped_and_stably_sorted():
    """去重 + 稳定排序：同一状态多次调用逐位相同，重复来源只出现一次。

    变异：改成 list(...) 不去重 / 不排序 → 本条红。
    """
    pet = _StubPet(customs=[("dance", "frames"), ("dance", "proc")],
                   sets={"dance": [], "idle": [], "eat": []})
    got = pb.action_choices(pet)
    assert got == sorted(got), "候选不是稳定排序：%r" % (got,)
    assert got == pb.action_choices(pet), "同一状态两次调用结果不同：%r" % (got,)
    assert got.count("dance") == 1, "重复来源没有被去重：%r" % (got,)


def test_action_choices_tolerates_missing_pet_and_odd_shapes():
    """pet 为 None / 缺 anim / custom_actions 抛错 都不许把"选动作"整条路打断。

    变异：去掉 getattr 兜底直接 pet.custom_actions() → 本条红（AttributeError）。
    """
    assert pb.action_choices(None) == sorted(set(pr.ANIM_ACTIONS)
                                             | set(pb.BUILTIN_PLAY_ACTIONS))

    class _Boom(object):
        def custom_actions(self):
            raise RuntimeError("角色索引坏了")

    got = pb.action_choices(_Boom())
    assert "jump" in got and "idle" in got, "读自定义动作失败时不该连内建候选一起没：%r" % (got,)

    class _StrCustom(object):
        def custom_actions(self):
            return ["nod", "", None]

    got2 = pb.action_choices(_StrCustom())
    assert "nod" in got2 and "" not in got2, "字符串型替身条目没被吃住：%r" % (got2,)


def test_action_choices_excludes_the_noop_name():
    """"none" 是 play_action 的显式空操作，不是可播动作——不进候选（但仍可手填保存）。"""
    pet = _StubPet(sets={"none": [], "idle": []})
    got = pb.action_choices(pet)
    assert "none" not in got, "空操作分支不该出现在「动作」候选里：%r" % (got,)


def test_unknown_action_name_survives_read_and_write(tmp_path):
    """③ 候选不是白名单：老行为文件里的未知动作名，读入 → 保存 → 重新加载后仍在。

    "下拉不许吃掉它"的契约在这里被钉死——候选里没有它（第一段断言），
    但它必须原样落盘、原样读回（第二、三段断言）。
    变异：把 validate_steps 改成按 action_choices 白名单过滤 → 本条红。
    """
    unknown = "my_new_action_from_old_file"
    assert unknown not in pb.action_choices(_StubPet()), "前置：这个名字本来就不该在候选里"

    d = str(tmp_path / "data")
    os.makedirs(d, exist_ok=True)
    svc = pb.BehaviorService(d)
    b, err = svc.add("legacy", [{"act": "play_action", "name": unknown}])
    assert b is not None and not err, err
    assert svc.get(b["id"])["steps"][0]["name"] == unknown, "保存时被吃掉了"

    # 直接看盘上的 behaviors.json（不是只看内存）
    with open(os.path.join(d, "behaviors.json"), "r", encoding="utf-8") as f:
        raw = json.load(f)
    assert raw["behaviors"][0]["steps"][0]["name"] == unknown, "落盘时被吃掉了：%r" % (raw,)

    svc2 = pb.BehaviorService(d)
    assert svc2.get(b["id"])["steps"][0]["name"] == unknown, "重新加载时被吃掉了"
    assert unknown not in pb.action_choices(_StubPet()), "候选集合不该被写脏"


def test_action_choices_against_real_pet_window(tmp_path_factory):
    """对**真 PetWindow**（自定义角色）跑一遍：接口在真对象上成立且能真失败。

    真对象上 custom_actions() 依赖 role_lib + 当前形态，替身测不到这一段。
    """
    import 桌宠 as main
    import pet_log
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QColor, QImage

    tmp = tmp_path_factory.mktemp("b1")
    snap = (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
            getattr(pet_log, "_data_dir", None))
    main.DATA_DIR = str(tmp)
    main.CONFIG_PATH = str(tmp / "config.json")
    main.USAGE_PATH = str(tmp / "usage.json")
    main.MEMORY_PATH = str(tmp / "memory.json")
    pet_log.set_data_dir(str(tmp))
    QApplication.instance() or QApplication([])
    win = main.PetWindow()
    try:
        # 默认角色：没有自定义角色 → custom_actions() 返回 []，候选仍必须非空
        assert win.custom_actions() == [], "前置：此时不该有自定义动作"
        got = pb.action_choices(win)
        assert "jump" in got and "emote" in got and "idle" in got,             "默认角色下真 PetWindow 的候选不完整：%r" % (got,)

        # 装一个带自定义帧动作 + 合成动作的角色
        rd = os.path.join(str(tmp), "roles")
        os.makedirs(rd, exist_ok=True)
        for n in ("b1_base.png", "b1_d1.png", "b1_d2.png"):
            img = QImage(64, 64, QImage.Format.Format_ARGB32)
            img.fill(QColor(120, 200, 255, 255))
            img.save(os.path.join(rd, n))
        win.role_lib._data["roles"].append({
            "id": "b1role", "name": "候选角色", "file": "b1_base.png",
            "form": "single", "file_full": "", "frames": ["b1_base.png"], "added": "",
            "forms": [{"name": "常态", "file": "b1_base.png",
                       "animations": {"idle": ["b1_base.png"],
                                      "dance": ["b1_d1.png", "b1_d2.png"]},
                       "procs": {"nod2": {"kind": "nod", "amp": 6.0, "period_ms": 400}}}]})
        win.role_lib._save()
        win.apply_role("b1role")
        got2 = pb.action_choices(win)
        assert "dance" in got2, "真 PetWindow 上自定义帧动作没进候选：%r" % (got2,)
        assert "nod2" in got2, "真 PetWindow 上合成动作没进候选：%r" % (got2,)
        assert "jump" in got2 and "idle" in got2, "内建动作被挤掉了：%r" % (got2,)
        assert got2 == sorted(got2), "真对象上不是稳定排序：%r" % (got2,)
    finally:
        main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH = snap[:4]
        pet_log.set_data_dir(snap[4])

# ---------------- B4：删除行为时清掉待机引用 ----------------

def _cfg_two(bid_a="aaaa1111", bid_b="bbbb2222"):
    return {
        "idle_actions": [
            {"id": bid_a, "behavior_id": bid_a, "enabled": True, "weight": 1.0, "order": 1},
            {"id": bid_b, "behavior_id": bid_b, "enabled": True, "weight": 2.0, "order": 2},
        ],
        "idle_play_mode": "sequential",
        "idle_behavior": "",
    }


def test_remove_idle_refs_clears_the_reference():
    """删掉被待机列表引用的行为后，cfg["idle_actions"] 不再含它（B4 的核心验收）。

    变异：把匹配改回旧死分支（拿恒为 "" 的 cfg["idle_behavior"] 去比）→ 本条红。
    """
    cfg = _cfg_two()
    removed, err = pb.remove_idle_actions_for_behavior(cfg, "aaaa1111")
    assert err == "" and len(removed) == 1, (removed, err)
    assert removed[0]["behavior_id"] == "aaaa1111"
    left = [a["behavior_id"] for a in cfg["idle_actions"]]
    assert "aaaa1111" not in left, "被删除的行为还留在待机列表里：%r" % (cfg,)
    assert left == ["bbbb2222"]
    assert cfg["idle_actions"][0]["order"] == 1, "剩下的条目 order 没重排：%r" % (cfg,)
    # 归一化视图（运行时真正用的口径）也必须干净
    assert [a["behavior_id"] for a in pb.normalize_idle_cfg(cfg)["idle_actions"]] == ["bbbb2222"]


def test_remove_idle_refs_is_idempotent_and_touches_nothing_when_no_hit():
    """没有引用时：返回 ([], "") 且一个字节都不动 cfg（幂等 + 不误伤）。

    变异：去掉"没命中就早退" → 本条红（归一化回写会把别的条目的手加未知键冲掉）。
    """
    cfg = {"idle_actions": [{"behavior_id": "bbbb2222", "note": "用户手加的键", "order": 1}],
           "idle_play_mode": "sequential"}
    before = json.loads(json.dumps(cfg))
    assert pb.remove_idle_actions_for_behavior(cfg, "aaaa1111") == ([], "")
    assert cfg == before, "没有引用要清时却改了 cfg：%r" % (cfg,)
    assert pb.remove_idle_actions_for_behavior(cfg, "aaaa1111") == ([], ""), "不幂等"
    assert pb.remove_idle_actions_for_behavior(cfg, "") == ([], ""), "空 id 不该动 cfg"
    assert pb.remove_idle_actions_for_behavior(None, "x")[1] != "", "非 dict 要给中文原因"


def test_remove_idle_refs_does_not_hurt_other_entries():
    """只清目标引用，其它条目连未知键都原样保留（不许"顺手归一化"）。"""
    cfg = {"idle_actions": [
        {"id": "a1", "behavior_id": "aaaa1111", "enabled": True, "weight": 1.0, "order": 1,
         "note": "keep-me"},
        {"id": "b2", "behavior_id": "bbbb2222", "enabled": False, "weight": 3.5, "order": 2,
         "note": "keep-me-too"},
        {"id": "c3", "behavior_id": "cccc3333", "enabled": True, "weight": 1.0, "order": 3},
    ], "idle_play_mode": "weighted"}
    removed, _ = pb.remove_idle_actions_for_behavior(cfg, "bbbb2222")
    assert [a["behavior_id"] for a in removed] == ["bbbb2222"]
    left = cfg["idle_actions"]
    assert [a["behavior_id"] for a in left] == ["aaaa1111", "cccc3333"]
    assert left[0]["note"] == "keep-me", "别的条目的未知键被冲掉了：%r" % (left[0],)
    assert left[0]["enabled"] is True and left[0]["weight"] == 1.0
    assert [a["order"] for a in left] == [1, 2], "order 没重排成 1..N：%r" % (left,)


def test_remove_idle_refs_clears_legacy_key_too():
    """旧键 idle_behavior 指向被删行为时也要清——不清就会被 normalize 迁回来"复活"。"""
    cfg = {"idle_behavior": "aaaa1111", "idle_actions": [], "idle_play_mode": "sequential"}
    removed, _ = pb.remove_idle_actions_for_behavior(cfg, "aaaa1111")
    assert len(removed) == 1, "旧键迁移出来的那条没被认出来：%r" % (removed,)
    assert cfg["idle_behavior"] == ""
    assert pb.normalize_idle_cfg(cfg)["idle_actions"] == [], "被删行为从旧键复活了"


def test_delete_behavior_then_clear_idle_refs_end_to_end(tmp_path):
    """端到端（后端侧）：行为库删掉 + 待机配置清引用 → 待机选择器再也挑不到它。"""
    d = str(tmp_path / "data")
    os.makedirs(d, exist_ok=True)
    svc = pb.BehaviorService(d)
    b1, _ = svc.add("keepme", [{"act": "say", "text": "在"}])
    b2, _ = svc.add("dropme", [{"act": "say", "text": "删"}])
    cfg = {}
    assert pb.add_idle_action(cfg, b1["id"])[0] is not None
    assert pb.add_idle_action(cfg, b2["id"])[0] is not None
    assert len(svc.idle_config(lambda: cfg)["idle_actions"]) == 2

    assert svc.delete(b2["id"]) == (True, "")
    removed, _ = pb.remove_idle_actions_for_behavior(cfg, b2["id"])
    assert len(removed) == 1
    left = [a["behavior_id"] for a in svc.idle_config(lambda: cfg)["idle_actions"]]
    assert left == [b1["id"]], "删除后待机列表没清干净：%r" % (left,)
    # 待机选择器：挑出来的只能是还在的那条
    for _ in range(6):
        picked, aid, err = svc.idle_pick(lambda: cfg)
        assert picked is not None and picked["id"] == b1["id"], (picked, aid, err)
        assert "不见了" not in (err or ""), "还有悬挂引用：%r" % (err,)


# ---------------- B5：待机下拉状态由配置推导 + 不许静默丢条目 ----------------

def test_idle_combo_state_two_entries_is_not_off():
    """审计实测的那条：配置里 2 条 + sequential，下拉却显示「（不启用 → 默认待机）」。

    变异：idle_combo_state 硬编码返回 off/label=IDLE_COMBO_OFF_LABEL → 本条红。
    """
    cfg = _cfg_two()
    st = pb.idle_combo_state(cfg)
    assert st["mode"] == "list", "2 条待机动作被显示成 %r" % (st,)
    assert st["count"] == 2 and st["enabled_count"] == 2
    assert st["label"] != pb.IDLE_COMBO_OFF_LABEL, "下拉在说谎：%r" % (st,)
    assert "2" in st["label"], "文案没如实说有几条：%r" % (st,)
    assert st["show_list_hint"] is True
    # 真 OFF 只在列表真的空时出现
    assert pb.idle_combo_state({})["mode"] == "off"
    assert pb.idle_combo_state({"idle_actions": [], "idle_play_mode": "sequential"})["label"] \
        == pb.IDLE_COMBO_OFF_LABEL


def test_idle_combo_state_single_and_first_only():
    """单条 single → 显示那一条；single 但列表不止一条 → 如实说"只播第一条"。"""
    bid = "aaaa1111"
    cfg = {"idle_actions": [{"id": bid, "behavior_id": bid, "enabled": True,
                             "weight": 1.0, "order": 1}],
           "idle_play_mode": "single"}
    st = pb.idle_combo_state(cfg, name_getter=lambda b: "摸鱼" if b == bid else "")
    assert st["mode"] == "single" and st["behavior_id"] == bid
    assert st["label"] == "空闲时：摸鱼"

    # 查名字失败不许把下拉打断：回落显示 id
    def _boom(_b):
        raise RuntimeError("行为库坏了")

    assert pb.idle_combo_state(cfg, name_getter=_boom)["label"] == "空闲时：" + bid
    assert pb.idle_combo_state(cfg, name_getter=lambda _b: "")["label"] == "空闲时：" + bid
    assert pb.idle_combo_state(cfg)["label"] == "空闲时：" + bid

    cfg2 = _cfg_two()
    cfg2["idle_play_mode"] = "single"
    st2 = pb.idle_combo_state(cfg2)
    assert st2["mode"] == "list" and st2["plays_first_only"] is True
    assert st2["label"] != pb.IDLE_COMBO_OFF_LABEL and st2["count"] == 2


def test_idle_single_change_dry_run_does_not_touch_cfg():
    """apply=False 只算不写：UI 可以拿它做确认文案，而配置一个字节不变。"""
    cfg = _cfg_two()
    before = json.loads(json.dumps(cfg))
    dropped, err = pb.idle_single_change(cfg, "bbbb2222")
    assert err == "" and [a["behavior_id"] for a in dropped] == ["aaaa1111"]
    assert cfg == before, "dry-run 改了配置：%r" % (cfg,)
    assert cfg["idle_play_mode"] == "sequential"


def test_idle_single_change_apply_reports_every_entry_it_drops():
    """**结构性不变量**：任何一次"下拉操作"里消失的条目，必须全部出现在返回值里。

    这就是 B5 的"不许静默丢条目"的可执行形态（现树的下拉直接覆盖 2 条只给一句通用气泡）。
    变异：把 dropped 恒返回 []（静默丢弃）→ 本条红。
    """
    cfg = _cfg_two()
    cfg["idle_actions"].append({"id": "c3", "behavior_id": "cccc3333", "enabled": True,
                                "weight": 1.0, "order": 3})
    before = [a["behavior_id"] for a in pb.normalize_idle_cfg(cfg)["idle_actions"]]
    assert len(before) == 3

    for choice in ["", "aaaa1111", "bbbb2222", "cccc3333", "dddd4444"]:
        _cfg = json.loads(json.dumps(cfg))
        dropped, _err2 = pb.idle_single_change(_cfg, choice, apply=True)
        after = [a["behavior_id"] for a in pb.normalize_idle_cfg(_cfg)["idle_actions"]]
        dropped_ids = [a["behavior_id"] for a in dropped]
        if choice:
            assert after == [choice], "选 %r 之后待机列表不是那一条：%r" % (choice, after)
        else:
            assert after == [], "选「不启用」之后列表没清空：%r" % (after,)
        lost = [b for b in before if b not in after]
        assert all(x in dropped_ids for x in lost), \
            "有条目被静默丢掉：lost=%r dropped=%r" % (lost, dropped_ids)
        # 正常情形（选中的条目本来就在列表里）减少量必须逐条对得上
        if choice in before:
            assert len(lost) == len(dropped_ids) == len(before) - 1


def test_idle_single_change_clears_legacy_key_so_dropped_do_not_resurrect():
    """apply 时必须清旧键 idle_behavior：否则 normalize 会把被丢掉的条目迁回来。"""
    cfg = {"idle_behavior": "aaaa1111", "idle_actions": [], "idle_play_mode": "sequential"}
    before = [a["behavior_id"] for a in pb.normalize_idle_cfg(cfg)["idle_actions"]]
    assert before == ["aaaa1111"]          # 前置：旧键真的会被迁进来
    dropped, _ = pb.idle_single_change(cfg, "bbbb2222", apply=True)
    assert len(dropped) == 1
    assert cfg["idle_behavior"] == ""
    after = [a["behavior_id"] for a in pb.normalize_idle_cfg(cfg)["idle_actions"]]
    assert after == ["bbbb2222"], "被丢掉的旧键条目复活了：%r" % (after,)


def test_idle_single_change_enables_the_chosen_entry_and_keeps_its_fields():
    """用户在下拉里明确选了一条 → 它必须真的会播（enabled=True），且原条目的手加键保留。"""
    cfg = {"idle_actions": [{"id": "b2", "behavior_id": "bbbb2222", "enabled": False,
                             "weight": 4.0, "order": 1, "note": "手加"}],
           "idle_play_mode": "sequential"}
    pb.idle_single_change(cfg, "bbbb2222", apply=True)
    kept = cfg["idle_actions"][0]
    assert kept["enabled"] is True, "选了它却还是禁用的：%r" % (kept,)
    assert kept["note"] == "手加" and kept["weight"] == 4.0
    assert cfg["idle_play_mode"] == "single"
    assert pb.pick_idle_action(pb.normalize_idle_cfg(cfg)["idle_actions"], "single") is not None

# ---------------- B6：试播只在保存成功之后 ----------------

def test_test_play_target_refuses_when_save_failed():
    """保存失败 → 不许播。**关键**：此时 _editing_id 还指向上一次成功保存的旧行为，
    它绝不能被当成试播目标返回（审计实测 3 号：播的是旧内容）。

    变异：把 `if not save_ok:` 改成 `if False:`（= 恢复"失败也播"）→ 本条红。
    """
    bid, why = pb.test_play_target(False, "old12345")
    assert bid is None, "保存失败却给了一个可播的 id（会播旧内容）：%r" % (bid,)
    assert why, "只说「不播」不说原因"
    assert why.strip(), why
    for bad in (None, 0, "", False):
        assert pb.test_play_target(bad, "old12345")[0] is None, \
            "save_ok=%r 被当成了「保存成功」（fail-safe 方向错了）" % (bad,)


def test_test_play_target_plays_only_after_successful_save():
    """保存成功 → 播的必须是**这一次**保存下来的那条（id 原样返回）。"""
    bid, why = pb.test_play_target(True, "abcd1234")
    assert bid == "abcd1234" and why == "", (bid, why)
    # 非字符串替身（老调用方/测试替身）也要能落到字符串上
    assert pb.test_play_target(True, "  abcd1234  ")[0] == "abcd1234"


def test_test_play_target_needs_a_saved_behavior():
    """保存成功但没有可播的 id（空表单）→ 不播，并给人话。"""
    for empty in (None, "", "   "):
        bid, why = pb.test_play_target(True, empty)
        assert bid is None and why, (empty, bid, why)


def test_test_play_target_never_plays_a_stale_id():
    """结构性断言：**失败路径上不存在任何能播的 id**（对全部候选 id 逐个验）。

    变异：把函数的第一个分支删掉 / 改成 `save_ok or True` → 本条红。
    """
    for stale in ("", "old12345", "deadbeef", None, 12345):
        assert pb.test_play_target(False, stale)[0] is None, \
            "save_ok=False 时 %r 被放行了" % (stale,)


def test_test_play_target_reason_is_human_readable():
    """给用户的原因是中文人话，不许把原始异常/英文栈透出去（原则 5）。"""
    for ok, bid in ((False, "x"), (True, "")):
        why = pb.test_play_target(ok, bid)[1]
        for bad in ("codec", "Traceback", "Expecting value", "Error", "None"):
            assert bad not in why, "原因里透出了原始异常字样 %r：%r" % (bad, why)
        assert any("\u4e00" <= ch <= "\u9fff" for ch in why), "原因不是中文人话：%r" % (why,)
# ---------------- R3（v2.10.0）：重名判据的唯一来源 ----------------

def test_find_by_name_is_the_single_judgement_for_duplicate_names(tmp_path):
    """R3：`find_by_name` 是重名判据的**唯一来源**（UI 侧只按它的结论问用户）。

    变异：让它恒返回 None（判据空转）→ 本条红，且对话框那几条重名用例一起红。
    """
    svc = pb.BehaviorService(str(tmp_path))
    a, err = svc.add("same", [{"act": "say", "text": "一"}])
    assert a is not None, err
    got = svc.find_by_name("same")
    assert got is not None and got["id"] == a["id"], "同名查不到：%r" % (got,)
    got["name"] = "被调用方改了"
    assert svc.get(a["id"])["name"] == "same", "交出去的不是深拷贝（库内数据被调用方改掉）"
    assert svc.find_by_name("  same  ") is not None, "名字两侧空白没归一"
    assert svc.find_by_name("nope") is None, "不存在的名字也命中了"
    assert svc.find_by_name("") is None and svc.find_by_name(None) is None, "空名字命中了"
    assert svc.find_by_name("same", exclude_id=a["id"]) is None, "改自己名字时把自己算成撞名"
    b, err2 = svc.add("other", [{"act": "say", "text": "二"}])
    assert b is not None, err2
    assert svc.find_by_name("same", exclude_id=b["id"])["id"] == a["id"], "排除项把别人也排掉了"
    c, err3 = svc.add("same", [{"act": "say", "text": "三"}])
    assert c is not None, err3
    assert svc.find_by_name("same")["id"] == min(a["id"], c["id"]), (
        "同名多条时返回值不稳定（按 id 排序才可复核）")


def test_add_itself_still_allows_duplicates_so_the_ui_owns_the_question(tmp_path):
    """控制组：判据**不在** `add` 里 —— 服务层保持"只答撞没撞"、不自己弹框/拒写。

    为什么钉这条：判据（find_by_name）与问法（对话框）分家是本轮的修法。若有人图省事
    在 `add` 里直接拒写，插件导入 / 角色包导入这些**没有用户在场**的调用点会一起坏掉。
    """
    svc = pb.BehaviorService(str(tmp_path))
    a, err = svc.add("same", [{"act": "say", "text": "一"}])
    assert a is not None, err
    b, err2 = svc.add("same", [{"act": "say", "text": "二"}])
    assert b is not None, "服务层的 add 被改成拒绝重名了（插件/导入路径会一起坏）"
    assert b["id"] != a["id"]
    assert len([x for x in svc.list() if x["name"] == "same"]) == 2
