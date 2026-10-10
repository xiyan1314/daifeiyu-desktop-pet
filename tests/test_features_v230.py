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