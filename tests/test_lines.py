# -*- coding: utf-8 -*-
"""v2.1 台词模块回归：种子/增删改/排序/对白/撤销/内置删除防复活/引用校验。"""
import json
import os

import pet_lines


def _svc(tmp_path):
    return pet_lines.LineService(str(tmp_path))


def test_seed_and_categories(tmp_path):
    svc = _svc(tmp_path)
    assert svc.count() == (len(pet_lines.LINES_SAJIAO) + len(pet_lines.LINES_GREEDY)
                           + len(pet_lines.LINES_SCARED) + len(pet_lines.LINES_HAPPY)
                           + len(pet_lines.LINES_IDLE) + len(pet_lines.LINES_STARTUP)
                           + len(pet_lines.LINES_PETTING)
                           + sum(len(v) for v in pet_lines.FOOD_LINES.values())
                           + sum(len(v) for v in pet_lines.MOOD_LINES.values()))
    # v2.1.2：情绪台词也进库（用户可增删改），不再是写死的常量
    assert svc.by_category("mood_puzzled") == pet_lines.LINES_MOOD_PUZZLED
    assert "mood_cry" in svc.categories() and "mood_blush" in svc.categories()
    assert set(svc.categories()) == set(pet_lines.LINE_CATEGORIES)
    assert svc.by_category("startup") == pet_lines.LINES_STARTUP
    assert svc.food_texts("蛋糕") == pet_lines.FOOD_LINES["蛋糕"]
    # order 连续无空洞
    orders = [ln["order"] for ln in svc.lines()]
    assert orders == list(range(1, len(orders) + 1))


def test_add_save_delete_undo(tmp_path):
    svc = _svc(tmp_path)
    ln, err = svc.add("新台词", "happy", role_slot="r1", voice_slot="v1")
    assert ln is not None and not err, err
    assert svc.get(ln["id"])["role_slot"] == "r1"
    assert svc.save(ln["id"], text="改过了", category="idle")[0] is True
    assert svc.get(ln["id"])["text"] == "改过了"
    assert svc.save(ln["id"], clear_role=True)[0] is True
    assert svc.get(ln["id"])["role_slot"] is None
    assert svc.save(ln["id"], text="  ")[0] is False  # 空文本拒绝
    assert svc.save("nope", text="x")[0] is False
    assert svc.delete(ln["id"]) == (True, "")
    assert svc.get(ln["id"]) is None
    assert svc.undo() == (True, "")
    assert svc.get(ln["id"]) is not None  # 撤销恢复
    assert svc.undo()[0] is False  # 只能撤销一次


def test_delete_builtin_no_revive(tmp_path):
    svc = _svc(tmp_path)
    bi = svc.lines("sajiao")[0]
    assert bi["builtin"] is True
    assert svc.delete(bi["id"]) == (True, "")
    svc2 = _svc(tmp_path)  # 重新加载
    assert svc2.get(bi["id"]) is None  # 删过的内置不复活
    # 数据文件里不留正文
    raw = json.loads(open(os.path.join(str(tmp_path), "lines.json"), encoding="utf-8").read())
    assert all(x["id"] != bi["id"] for x in raw["lines"])
    assert bi["id"] in raw["deleted_builtins"]
    # 恢复内置可补回
    assert svc2.restore_builtins() >= 1
    assert svc2.get(bi["id"]) is not None


def test_clear_all_and_batch_delete(tmp_path):
    svc = _svc(tmp_path)
    ids = [ln["id"] for ln in svc.lines()[:3]]
    n, err = svc.delete_many(ids)
    assert n == 3 and not err
    assert all(svc.get(i) is None for i in ids)
    assert svc.delete_many([])[1] == "没有选中台词"
    assert svc.clear_all() == (True, "")
    assert svc.count() == 0
    assert svc.undo()[0] is True and svc.count() > 0  # 清空可撤销


def test_dialogues_and_line_delete_reorder(tmp_path):
    svc = _svc(tmp_path)
    a = svc.add("台词A")[0]
    b = svc.add("台词B")[0]
    c = svc.add("台词C")[0]
    d, err = svc.add_dialogue("开场对白", [a["id"], b["id"], c["id"]])
    assert d is not None and not err, err
    assert [x["text"] for x in svc.dialogue_lines(d["id"])] == ["台词A", "台词B", "台词C"]
    # 删除中间一条 → 对白自动重排不留空洞
    assert svc.delete(b["id"]) == (True, "")
    assert [x["text"] for x in svc.dialogue_lines(d["id"])] == ["台词A", "台词C"]
    assert svc.get_dialogue(d["id"])["line_ids"] == [a["id"], c["id"]]
    # 改顺序
    assert svc.save_dialogue(d["id"], line_ids=[c["id"], a["id"]])[0] is True
    assert [x["text"] for x in svc.dialogue_lines(d["id"])] == ["台词C", "台词A"]
    assert svc.save_dialogue(d["id"], line_ids=["nope"])[0] is False
    assert svc.add_dialogue("空", [])[1] == "对白至少要有一条台词"
    assert svc.delete_dialogue(d["id"]) == (True, "")
    assert svc.get_dialogue(d["id"]) is None


def test_reorder_lines(tmp_path):
    svc = _svc(tmp_path)
    lines = svc.lines("happy")
    rev = [ln["id"] for ln in reversed(lines)]
    assert svc.reorder(rev)[0] is True
    got = [ln["id"] for ln in svc.lines("happy")]
    assert got == rev
    assert svc.reorder([])[0] is False


def test_validate_references(tmp_path):
    svc = _svc(tmp_path)
    ok = svc.add("好台词", role_slot="r_ok", voice_slot="v_ok")[0]
    bad = svc.add("坏台词", role_slot="r_gone", voice_slot="v_gone")[0]
    items = svc.validate_references(lambda s: s == "r_ok", lambda s: s == "v_ok")
    assert len(items) == 1
    it = items[0]
    assert it["line_id"] == bad["id"]
    assert it["missing_role"] == "r_gone" and it["missing_voice"] == "v_gone"
    assert "角色不存在" in it["reason"] and "声音素材不存在" in it["reason"]
    assert it["text_preview"] == "坏台词"
    assert svc.get(ok["id"]) is not None  # 不自动删
    assert svc.get(bad["id"])["role_slot"] == "r_gone"  # 不自动清


def test_changed_callbacks(tmp_path):
    svc = _svc(tmp_path)
    hits = []
    svc.on_changed(lambda: hits.append(1))
    inv = []
    svc.on_invalid_reference(lambda items: inv.append(len(items)))
    svc.add("x")
    assert len(hits) == 1
    svc.emit_invalid_reference([{"line_id": "a"}])
    assert inv == [1]
    svc.off_changed(svc._changed_cbs[0])
    svc.add("y")
    assert len(hits) == 1  # 注销后不再回调


def test_empty_text_entry_is_dropped(tmp_path):
    """空文本脏条目直接丢弃（不复活成空台词）。

    A11 去重（v2.4.2，代理 Q）：本条原先叫 test_corrupt_file_recovers，前半段
    "坏 lines.json → count() > 0 自动重建种子" 归
    tests/test_io_v231.py::test_lines_corrupt_file_heals_with_bak——那边还多验 .bak 原文、
    愈合后盘上是合法 JSON 且 lines 非空、愈合留痕，严格更强。这里只留原来独有的这一半。
    """
    p = tmp_path / "lines.json"
    p.write_text(json.dumps({"lines": [{"id": "x", "text": ""}]}), encoding="utf-8")
    svc = pet_lines.LineService(str(tmp_path))
    assert svc.get("x") is None  # 空文本脏条目丢弃
