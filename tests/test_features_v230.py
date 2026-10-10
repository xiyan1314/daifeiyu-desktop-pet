# -*- coding: utf-8 -*-
"""v2.3.0 回归：人设提示词外置（1.4）+ 角色包元数据（2.1）。"""
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pet_export  # noqa: E402


def _reload_main(tmp_path, monkeypatch):
    """把 桌宠.DATA_DIR 指到临时目录后重载模块（人设文件落在这里）。"""
    import importlib
    import 桌宠 as main
    main = importlib.reload(main)          # 重载会重新计算 DATA_DIR，所以补丁必须放在重载之后
    monkeypatch.setattr(main, "DATA_DIR", str(tmp_path), raising=False)
    return main


def test_persona_files_written_once_and_editable(tmp_path, monkeypatch):
    """1.4：首次启动写内置人设文件；**不覆盖**用户已编辑的内容。"""
    main = _reload_main(tmp_path, monkeypatch)
    main.ensure_persona_files()
    p = tmp_path / "prompts" / "default.txt"
    assert p.is_file(), "内置人设文件没有生成"
    assert (tmp_path / "prompts" / "custom").is_dir(), "custom/ 目录没有生成"
    # 用户编辑后再次启动不得被覆盖
    p.write_text("我的人设：只准说好话", encoding="utf-8")
    main.ensure_persona_files()
    assert p.read_text(encoding="utf-8").strip() == "我的人设：只准说好话", "重写覆盖了用户修改"


def test_persona_file_overrides_builtin_prompt(tmp_path, monkeypatch):
    """1.4：prompts/<id>.txt 存在时，系统提示词用它（而不是内置常量）。"""
    main = _reload_main(tmp_path, monkeypatch)
    main.ensure_persona_files()
    (tmp_path / "prompts" / "default.txt").write_text("文件版人设", encoding="utf-8")
    sysp = main._build_ai_sys_prompt({"ai_persona": "default"})
    assert sysp.startswith("文件版人设"), "人设文件没有生效：%r" % sysp[:40]
    # 删掉文件 → 回退内置常量
    (tmp_path / "prompts" / "default.txt").unlink()
    sysp2 = main._build_ai_sys_prompt({"ai_persona": "default"})
    assert sysp2.startswith(main.SYSTEM_PROMPT[:12]), "文件缺失时没有回退内置人设"


def test_custom_persona_choice_and_normalize(tmp_path, monkeypatch):
    """1.4：prompts/custom/*.txt 自动成为可选人设，且配置归一化不会把它打回默认。"""
    main = _reload_main(tmp_path, monkeypatch)
    main.ensure_persona_files()
    (tmp_path / "prompts" / "custom" / "我的毒舌版.txt").write_text("毒舌人设", encoding="utf-8")
    ids = main.persona_file_ids()
    assert "file:我的毒舌版" in ids
    labels = dict(main.persona_choices())
    assert "file:我的毒舌版" in labels and "我的毒舌版" in labels["file:我的毒舌版"]
    # 白名单放行：归一化后仍是这个 id（此前会被当成非法预设打回 default）
    cfg = {"ai_persona": "file:我的毒舌版"}
    import pet_config
    pet_config.normalize_cfg(cfg, {"ai_persona": "default"},
                             frozenset(main.PERSONA_PRESETS) | main.persona_file_ids())
    assert cfg["ai_persona"] == "file:我的毒舌版"
    assert main._build_ai_sys_prompt(cfg).startswith("毒舌人设")


def test_manifest_meta_written_and_tolerated(tmp_path):
    """2.1：meta 写进 manifest；缺 meta 的旧包照常通过校验（不参与校验）。"""
    role = {"id": "r1", "name": "懒懒猫", "file": "a.png", "file_front": "",
            "file_full": "", "file_full_front": ""}
    (tmp_path / "a.png").write_bytes(b"png")
    man, err = pet_export.build_manifest(role, [], {}, meta={
        "author": "绳匠小张", "description": "一只永远睡不醒的橘猫",
        "tags": ["猫", "可爱"]})
    assert err == "" and man["meta"]["author"] == "绳匠小张"
    assert man["meta"]["tags"] == ["猫", "可爱"]
    # 非 dict 的 meta 宽容成空对象（不炸）
    man2, _ = pet_export.build_manifest(role, [], {}, meta="oops")
    assert man2["meta"] == {}
    # 旧包（无 meta 键）仍能通过结构校验
    z = tmp_path / "old.dfypet.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("manifest.json", json.dumps({
            "format": pet_export.BUNDLE_FORMAT, "version": 1, "role": role,
            "behaviors": [], "config": {}}, ensure_ascii=False))
        f.writestr("roles/a.png", b"png")
    m2, e2 = pet_export.validate_bundle(str(z))
    assert m2 is not None and e2 == "", "缺 meta 的旧包被判失败了：%s" % e2


def test_manifest_meta_roundtrip_through_import(tmp_path):
    """2.1：带 meta 的包导入后，调用方能拿到作者/简介（导入完成气泡要用）。"""
    rid = "rt1"
    role = {"id": rid, "name": "懒懒猫", "file": "rt.png", "file_front": "",
            "file_full": "", "file_full_front": ""}
    (tmp_path / "rt.png").write_bytes(b"png")
    z = tmp_path / "rt.dfypet.zip"
    man, _ = pet_export.build_manifest(role, [], {}, meta={"author": "阿鱼"})
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("manifest.json", json.dumps(man, ensure_ascii=False))
        f.writestr("roles/rt.png", b"png")
    m, e = pet_export.validate_bundle(str(z))
    assert m is not None, e
    assert m["meta"]["author"] == "阿鱼"

def test_long_term_roundtrip_keeps_history(tmp_path):
    """1.1：长期记忆与对话历史**互不覆盖**（同一个 memory.json）。"""
    import pet_chat
    p = str(tmp_path / "memory.json")
    pet_chat.write_memory(p, [("user", "你好"), ("assistant", "嗨")], 10)
    pet_chat.write_long_term(p, {"user_name": "小明", "preferences": ["喜欢吃蛋糕"]})
    assert pet_chat.read_memory(p, 10) == [("user", "你好"), ("assistant", "嗨")], "写长期记忆把历史冲掉了"
    pet_chat.write_memory(p, [("user", "在吗")], 10)
    lt = pet_chat.read_long_term(p)
    assert lt["user_name"] == "小明" and lt["preferences"] == ["喜欢吃蛋糕"], "写历史把长期记忆冲掉了"


def test_long_term_sanitize_limits(tmp_path):
    """1.1：去重 + 截断 + FIFO 限量 + 体积兜底。"""
    import pet_chat
    lt = pet_chat.sanitize_long_term({
        "preferences": ["a"] * 60 + ["a", "b"],
        "nicknames": "不是列表",
        "recent_topics": ["x" * 200]})
    assert len(lt["preferences"]) <= pet_chat.LONG_TERM_MAX
    assert lt["preferences"].count("a") == 1, "重复项没有去重"
    assert lt["nicknames"] == [], "非列表字段应归一化为空列表"
    assert len(lt["recent_topics"][0]) <= 60, "超长条目没有被截断"


def test_extract_long_term_rules():
    """1.1：规则抽取（零 API 成本）——喜好/称呼/近况。"""
    import pet_chat
    r = pet_chat.extract_long_term("我喜欢吃蛋糕，不喜欢早起")
    assert "吃蛋糕" in r.get("preferences", []), r
    assert pet_chat.extract_long_term("我叫小明")["user_name"] == "小明"
    assert pet_chat.extract_long_term("嗨") == {}, "太短的输入不该抽出话题"
    assert pet_chat.extract_long_term("x" * 300) == {}, "超长输入直接跳过（防噪声入库）"


def test_ai_context_switch_and_content(tmp_path, monkeypatch):
    """1.3：ai_rag_enabled=False 完全不注入；开启时注入记账摘要与长期记忆。"""
    main = _reload_main(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "MEMORY_PATH", str(tmp_path / "memory.json"))

    class _Stub:
        book = None
        _shown_balance = 12.5

    s = _Stub()
    assert main.PetWindow._build_ai_context(s, {"ai_rag_enabled": False}) == "", \
        "隐私开关关闭时仍在注入用户数据"
    txt = main.PetWindow._build_ai_context(s, {"ai_rag_enabled": True, "city": "北京"})
    assert "【用户数据摘要】" in txt and "北京" in txt and "12.50" in txt, txt
    main.pet_chat.write_long_term(str(tmp_path / "memory.json"),
                                  {"preferences": ["喜欢吃蛋糕"]})
    txt2 = main.PetWindow._build_ai_context(s, {"ai_rag_enabled": True})
    assert "【关于绳匠的记忆】" in txt2 and "喜欢吃蛋糕" in txt2, txt2

def test_clear_history_keeps_long_term(tmp_path):
    """S1（找茬审查）：清理日志/清 Key 只清 history，**长期记忆必须留下**（此前整文件删）。"""
    import pet_chat
    p = str(tmp_path / "memory.json")
    pet_chat.write_long_term(p, {"user_name": "小明", "preferences": ["吃辣"]})
    pet_chat.write_memory(p, [("user", "hi"), ("assistant", "嗨")], 6)
    pet_chat.write_memory(p, [], 6)          # 等价于「清理日志」的动作
    assert pet_chat.read_memory(p, 10) == [], "对话历史没清掉"
    lt = pet_chat.read_long_term(p)
    assert lt["user_name"] == "小明" and lt["preferences"] == ["吃辣"], \
        "清历史把长期记忆一起删了（S1 回归）"


def test_extract_polarity_likes_vs_dislikes():
    """M4（找茬审查）："我讨厌X"不能落进 preferences——否则会被渲染成"喜好：X"反着推荐。"""
    import pet_chat
    r = pet_chat.extract_long_term("我讨厌香菜")
    assert "香菜" in r.get("dislikes", []), r
    assert "香菜" not in r.get("preferences", []), "讨厌的东西被记成了喜好：%r" % r
    r2 = pet_chat.extract_long_term("我不喜欢吃甜食")
    assert r2.get("dislikes") and not r2.get("preferences"), r2
    r3 = pet_chat.extract_long_term("我最喜欢吃蛋糕")
    assert "吃蛋糕" in r3.get("preferences", []) and not r3.get("dislikes"), r3
    assert pet_chat.sanitize_long_term({"dislikes": ["香菜"]})["dislikes"] == ["香菜"]


def test_tool_call_missing_id_gets_generated():
    """M1（找茬审查）：tool_call 缺 id 时必须补一个非空 id（空 id 会构造非法报文）。"""
    import pet_tools
    _n, _a, _cid = pet_tools.parse_call({"function": {"name": "check_balance", "arguments": "{}"}})
    assert _cid, "缺 id 时没有补 uuid → tool_call_id 会是空串（非法报文）"
    _n2, _a2, _cid2 = pet_tools.parse_call({"id": "keep-me",
                                            "function": {"name": "check_balance", "arguments": "{}"}})
    assert _cid2 == "keep-me", "模型给的 id 不该被覆盖"
    # 非 dict 的调用必须被拒（M2 同源：坏结构不能变出调用）
    assert pet_tools.parse_call("abc") == ("", {}, "")
    assert pet_tools.parse_call({"x": 1})[0] == ""
