# -*- coding: utf-8 -*-
"""v2.1 分享包回归：台词/对白随包、声音素材可选打包、槽位与角色映射重指、密钥不入包。"""
import json
import os
import struct
import wave
import zipfile

import pet_export
import pet_lines
import pet_resources


def _wav(path):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(struct.pack("<800h", *([0] * 800)))
    return str(path)


def _png(path):
    # 最小合法 PNG（1x1 透明）：导出只校验存在与引用名
    data = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c63000100000500010d0a2db4"
        "0000000049454e44ae426082")
    with open(str(path), "wb") as f:
        f.write(data)
    return str(path)


def _role(tmp_path, rid="r1"):
    _png(tmp_path / "a.png")
    return {"id": rid, "name": "分享角色", "file": "a.png", "form": "single",
            "frames": ["a.png"], "added": ""}


def test_manifest_carries_lines_and_scrubs_keys():
    m, err = pet_export.build_manifest(
        _dummy_role(), [], {"voice": {"enabled": True,
                                      "backend_keys": {"minimax": "SECRET"},
                                      "bindings": {"r1": "v1"}}},
        [{"time": "06:00"}],
        [{"id": "l1", "text": "台词", "category": "idle", "role_slot": "r1",
          "voice_slot": "v1", "order": 1, "builtin": False, "food": ""}],
        [{"id": "d1", "name": "对白", "line_ids": ["l1"]}],
        [{"id": "v1", "name": "音色", "ext": ".wav", "file": "voice_ref/v1.wav"}])
    assert m is not None and not err, err
    blob = json.dumps(m, ensure_ascii=False)
    assert "SECRET" not in blob  # 克隆后端密钥不入包
    assert any("backend_keys" in x for x in m["excluded"])
    assert m["lines"][0]["id"] == "l1" and m["dialogues"][0]["id"] == "d1"
    assert m["voice_assets"][0]["file"] == "voice_ref/v1.wav"
    assert m["alarms"][0]["time"] == "06:00"


def _dummy_role(rid="r1"):
    return {"id": rid, "name": "分享角色", "file": "a.png", "form": "single",
            "frames": ["a.png"], "added": ""}


def test_roundtrip_lines_voice_and_bindings(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    role_lib = pet_resources.RoleLibrary(str(src))
    role, err = role_lib.import_file(_png(src / "a.png"), "分享角色")
    assert role is not None and not err, err
    role_lib.set_active(role["id"])
    assets = pet_resources.VoiceAssetLibrary(str(src))
    asset, _e3 = assets.import_file(_wav(src / "ref.wav"), "分享音色")
    assert asset is not None
    lines = pet_lines.LineService(str(src))
    ln, _e = lines.add("要对白的话", "idle", role["id"], asset["id"])  # 台词自带声音槽位
    dlg, _e2 = lines.add_dialogue("开场", [ln["id"]])
    cfg = {"role": role["id"], "voice": {"enabled": True,
                                         "backend_keys": {"minimax": "SECRET"},
                                         "bindings": {role["id"]: asset["id"]}}}
    bundle = str(tmp_path / "share.dfypet.zip")
    ok, err = pet_export.export_bundle(
        role_lib, None, cfg, bundle,
        lines_getter=lambda: [x for x in lines.lines() if not x.get("builtin")],
        dialogues_getter=lines.dialogues,
        voice_assets_getter=lambda: [dict(asset, path=assets.asset_path(asset["id"]))],
        include_voice_ids=[asset["id"]])
    assert ok and os.path.isfile(bundle), err
    with zipfile.ZipFile(bundle) as zf:
        assert any(n.startswith("voice_ref/") for n in zf.namelist())
        man = json.loads(zf.read("manifest.json").decode("utf-8"))
    assert "SECRET" not in json.dumps(man)

    # 导入到干净环境
    dst = tmp_path / "dst"
    dst.mkdir()
    rl2 = pet_resources.RoleLibrary(str(dst))
    ln2 = pet_lines.LineService(str(dst))
    va2 = pet_resources.VoiceAssetLibrary(str(dst))
    cfg2 = {}

    def _voice_apply(items, extract_dir):
        mapping = {}
        for a in items:
            p = os.path.join(extract_dir, os.path.basename(a["file"]))
            na, _err = va2.import_file(p, a.get("name"))
            if na:
                mapping[a["id"]] = na["id"]
        return mapping

    warns = []

    def _lines_apply(ls, dlgs, maps):
        id_map = {}
        for x in ls:
            vm = maps["voice"]
            vs = vm.get(str(x.get("voice_slot") or ""), "")
            na, _err = ln2.add(x["text"], x.get("category") or "idle",
                               maps["role"].get(str(x.get("role_slot") or ""), "") or None,
                               vs or None)
            if na:
                id_map[x["id"]] = na["id"]
        for d in (dlgs or []):
            ids = [id_map.get(str(i)) for i in d.get("line_ids") or []]
            ids = [i for i in ids if i]
            if ids:
                ln2.add_dialogue(d.get("name"), ids)
        warns.append(len(ls))
        return []

    res, err2 = pet_export.import_bundle(rl2, None, cfg2, bundle,
                                         voice_apply=_voice_apply, lines_apply=_lines_apply)
    assert res is not None, err2
    assert warns == [1]
    # 台词落地且声音槽位重指到新素材 id
    got = [x for x in ln2.lines() if x["text"] == "要对白的话"]
    assert len(got) == 1
    assert got[0]["voice_slot"] and got[0]["voice_slot"] != asset["id"]
    assert va2.asset_path(got[0]["voice_slot"]) is not None
    # 角色映射：绑定重指到新角色 id
    binds = (cfg2.get("voice") or {}).get("bindings") or {}
    assert list(binds.keys()) == [res["role_id"]]
    assert binds[res["role_id"]] == got[0]["voice_slot"]
    # 对白也落地
    assert len(ln2.dialogues()) == 1
    assert res["voice_map"][asset["id"]] == got[0]["voice_slot"]


def test_export_without_voice_files(tmp_path):
    """默认不勾选：包里没有 voice_ref/ 文件，但元数据为 None。"""
    src = tmp_path / "s2"
    src.mkdir()
    role_lib = pet_resources.RoleLibrary(str(src))
    role, _ = role_lib.import_file(_png(src / "a.png"), "角色")
    role_lib.set_active(role["id"])
    cfg = {"role": role["id"]}
    bundle = str(tmp_path / "n.zip")
    ok, err = pet_export.export_bundle(role_lib, None, cfg, bundle)
    assert ok, err
    with zipfile.ZipFile(bundle) as zf:
        names = zf.namelist()
        man = json.loads(zf.read("manifest.json").decode("utf-8"))
    assert not any(n.startswith("voice_ref/") for n in names)
    assert man["lines"] is None and man["voice_assets"] is None
