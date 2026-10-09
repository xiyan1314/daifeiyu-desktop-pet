# -*- coding: utf-8 -*-
"""v2.1 资源库回归：声音素材库（参考音）与音效片段分开管理 + 角色删除通知。"""
import os

import pet_resources


def _lib(tmp_path):
    return pet_resources.VoiceAssetLibrary(str(tmp_path))


def _wav(path, seconds=0.1):
    import struct
    import wave
    rate = 8000
    n = int(rate * seconds)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<%dh" % n, *([0] * n)))
    return str(path)


def test_empty_and_corrupt(tmp_path):
    lib = _lib(tmp_path)
    assert lib.assets() == []
    assert lib.asset_path("nope") is None and lib.get_asset("nope") is None
    (tmp_path / "voice_assets.json").write_text("{{{bad", encoding="utf-8")
    lib2 = _lib(tmp_path)
    assert lib2.assets() == []


def test_import_rename_delete(tmp_path):
    lib = _lib(tmp_path)
    src = _wav(tmp_path / "ref.wav")
    a, err = lib.import_file(src, "小肥鱼音色")
    assert a is not None and not err, err
    assert lib.asset_path(a["id"]) is not None
    assert lib.exists(a["id"]) is True
    assert lib.get_asset(a["id"])["name"] == "小肥鱼音色"
    assert lib.rename(a["id"], "新名字") == (True, "")
    assert lib.get_asset(a["id"])["name"] == "新名字"
    assert lib.rename(a["id"], " ")[0] is False
    hits = []
    lib.on_deleted(lambda sid: hits.append(sid))
    assert lib.delete(a["id"]) == (True, "")
    assert lib.asset_path(a["id"]) is None
    assert hits == [a["id"]]  # 删除通知已发
    assert lib.delete(a["id"])[0] is False


def test_reject_bad_input(tmp_path):
    lib = _lib(tmp_path)
    assert lib.import_file(str(tmp_path / "nope.wav"))[1] == "文件不存在"
    txt = tmp_path / "a.txt"
    txt.write_text("x", encoding="utf-8")
    assert "wav" in lib.import_file(str(txt))[1]
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not a wave file")
    assert lib.import_file(str(bad))[1] is not None  # 内容损坏拒绝
    big = _wav(tmp_path / "big.wav")
    lib.MAX_BYTES = 10
    assert "20MB" in lib.import_file(big)[1]
    lib.MAX_BYTES = 20 * 1024 * 1024


def test_assets_persist(tmp_path):
    lib = _lib(tmp_path)
    a, _ = lib.import_file(_wav(tmp_path / "p.wav"), "持久化")
    lib2 = _lib(tmp_path)
    assert lib2.get_asset(a["id"])["name"] == "持久化"
    assert lib2.asset_path(a["id"]) is not None


def test_role_delete_notifies(tmp_path):
    lib = pet_resources.RoleLibrary(str(tmp_path))
    hits = []
    lib.on_deleted(lambda rid: hits.append(rid))
    # 造一个最小角色记录（文件可缺，delete 容错）
    lib._data["roles"].append({"id": "r1", "name": "测试", "file": "r1.png",
                               "form": "single", "file_full": "", "frames": ["r1.png"],
                               "added": ""})
    assert lib.delete("r1") == (True, "")
    assert hits == ["r1"]
    assert lib.delete("r1")[0] is False  # 不存在
