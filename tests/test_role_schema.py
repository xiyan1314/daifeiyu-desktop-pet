# -*- coding: utf-8 -*-
"""P1-7 角色模型自由度 schema 升级回归：迁移 / 动画查表 / 状态图优先级 /
update() / 读侧 FRAME_MAX 与 animations 共存 / 导入新参数 / 编辑对话框。

纯逻辑部分无需 Qt；涉及 QPixmap 的用例用模块级 offscreen QApplication。
"""
import json
import os

import pytest

import pet_resources


@pytest.fixture(scope="module")
def qapp():
    """状态图/编辑对话框用例共享一个 offscreen QApplication。"""
    from PySide6.QtWidgets import QApplication
    inst = QApplication.instance()
    if inst is None or not isinstance(inst, QApplication):
        inst = QApplication([])
    yield inst


def _mk_png(path, w=40, h=40, color=0xFF3366CC):
    """带 alpha 的不透明色块 PNG（跳过自动去背景，处理路径最短）。"""
    from PySide6.QtGui import QImage
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(color)
    assert img.save(path, "PNG")


def _write_index(tmp_path, roles, active=""):
    with open(tmp_path / "roles.json", "w", encoding="utf-8") as f:
        json.dump({"roles": roles, "active": active}, f, ensure_ascii=False)


# ---------------- 迁移（旧 frames/file_full 到新结构、行为不变） ----------------

def test_legacy_frames_migrate_to_animations(tmp_path):
    """旧角色级 frames 升级为 forms[0].animations.idle；顶层 frames 保留兼容视图。"""
    _write_index(tmp_path, [{
        "id": "old1", "name": "旧帧角色", "file": "old1.png",
        "form": "dual", "file_full": "old1_full.png",
        "frames": ["old1_f00.png", "old1_f01.png", "old1_f02.png"],
        "forms": [{"name": "常态", "file": "old1.png"},
                  {"name": "吃饱", "file": "old1_full.png"}],
        "added": "",
    }], active="old1")
    lib = pet_resources.RoleLibrary(str(tmp_path))
    role = lib.get("old1")
    assert role is not None
    # 迁移结果：帧进入 forms[0].animations.idle
    assert pet_resources.animation_frames(role, 0, "idle") == [
        "old1_f00.png", "old1_f01.png", "old1_f02.png"]
    # 兼容视图：顶层 frames 与 idle 一致（v13/老调用方依赖）
    assert role["frames"] == pet_resources.animation_frames(role, 0, "idle")
    # file 保留作 still；file_full/forms 不变 → 升级后行为与升级前一致
    assert role["forms"][0]["file"] == "old1.png"
    assert role["forms"][1]["file"] == "old1_full.png"
    assert role["file_full"] == "old1_full.png"
    assert role["form"] == "dual"
    assert role.get("v2") is False  # 纯旧结构不算 v2（保留全局 scale 补偿路径）


def test_legacy_forms_keep_still_and_reload(tmp_path):
    """旧 file/file_full（无 forms 键）迁移后重载行为一致。"""
    _write_index(tmp_path, [{
        "id": "a1", "name": "旧双形态", "file": "a1.png",
        "form": "dual", "file_full": "a1_full.png", "added": "",
    }])
    lib = pet_resources.RoleLibrary(str(tmp_path))
    assert [m["name"] for m in lib.form_metas("a1")] == ["常态", "吃饱"]
    assert lib.get("a1")["forms"][1]["file"] == "a1_full.png"
    # 重载后结构一致（frames 视图为空）
    lib2 = pet_resources.RoleLibrary(str(tmp_path))
    assert lib2.get("a1")["frames"] == []


# ---------------- 新结构动画查表（纯逻辑） ----------------

def test_animation_frames_lookup():
    """animation_frames 按「形态×动作」查表：多形态、缺动作、越界。"""
    role = {
        "forms": [
            {"file": "a.png",
             "animations": {"idle": ["f00.png", "f01.png"], "eat": ["e0.png"]}},
            {"file": "b.png",
             "animations": {"idle": ["g00.png"], "sleep": ["s0.png", "s1.png"]}},
        ],
    }
    assert pet_resources.animation_frames(role, 0, "idle") == ["f00.png", "f01.png"]
    assert pet_resources.animation_frames(role, 0, "eat") == ["e0.png"]
    assert pet_resources.animation_frames(role, 1, "idle") == ["g00.png"]
    assert pet_resources.animation_frames(role, 1, "sleep") == ["s0.png", "s1.png"]
    assert pet_resources.animation_frames(role, 0, "sleep") == []  # 未配置动作
    assert pet_resources.animation_frames(role, 2, "idle") == []   # 越界形态
    assert pet_resources.animation_frames({}, 0, "idle") == []


def test_form_render_defaults():
    """form_render 缺省 = 旧行为（居中/不缩放/无位移）。"""
    role = {"forms": [{"file": "a.png"}]}
    r = pet_resources.form_render(role, 0)
    assert r == {"anchor": (0.5, 0.5), "scale": None, "offset": (0, 0)}
    role2 = {"forms": [{"file": "a.png", "anchor": {"x": 0.5, "y": 1.0},
                        "scale": 1.5, "offset": {"x": 3, "y": -4}}]}
    r2 = pet_resources.form_render(role2, 0)
    assert r2["anchor"] == (0.5, 1.0) and r2["scale"] == 1.5 and r2["offset"] == (3, -4)


def test_animations_loaded_via_form_animations(tmp_path):
    """form_animations 解析绝对路径；帧缺失的动作整体回退（与旧 frames_for 语义一致）。"""
    (tmp_path / "roles").mkdir(exist_ok=True)
    for fn in ("r1_f00.png", "r1_f01.png", "r1_e0.png"):
        (tmp_path / "roles" / fn).write_bytes(b"fakepng")
    _write_index(tmp_path, [{
        "id": "r1", "name": "x", "file": "r1.png", "form": "single",
        "forms": [{"name": "常态", "file": "r1.png",
                   "animations": {"idle": ["r1_f00.png", "r1_f01.png"],
                                  "eat": ["r1_e0.png", "r1_missing.png"]},
                   "anim_interval_ms": 90}],
        "added": "",
    }])
    lib = pet_resources.RoleLibrary(str(tmp_path))
    anims = lib.form_animations("r1")
    assert len(anims) == 1
    assert len(anims[0]["idle"]) == 2
    assert "eat" not in anims[0]  # 帧缺失：该动作整体视为无动画
    assert anims[0]["interval_ms"] == 90
    # 旧接口 frames_for = forms[0].animations.idle
    assert len(lib.frames_for("r1")) == 2
    assert lib.form_animations("不存在") == []


# ---------------- 状态图优先级（资源图优先、程序化兜底） ----------------

def test_states_priority_resource_first(tmp_path, qapp):
    """forms[i].states[state] 资源图优先；未配置走程序化叠图（P2-5 合并点）。"""
    import 桌宠 as main
    from PySide6.QtGui import QPixmap
    (tmp_path / "roles").mkdir(exist_ok=True)
    _mk_png(str(tmp_path / "roles" / "r1.png"), color=0xFF3366CC)
    _mk_png(str(tmp_path / "roles" / "r1_angry.png"), color=0xFFFF0000)
    _write_index(tmp_path, [{
        "id": "r1", "name": "x", "file": "r1.png", "form": "single",
        "forms": [{"name": "常态", "file": "r1.png",
                   "states": {"angry": "r1_angry.png"}}],
        "added": "",
    }])
    lib = pet_resources.RoleLibrary(str(tmp_path))
    base_pix = QPixmap(str(tmp_path / "roles" / "r1.png"))

    class _Stub:
        _custom_role = True
        form_keys = ["f0"]
        cfg = {"role": "r1"}
        role_lib = lib
        sprites = {"f0": {"side": base_pix, "front": base_pix}}

        def _cap_role_pix(self, pix, path=None):
            return pix

    _Stub._custom_state_pix = main.PetWindow._custom_state_pix
    stub = _Stub()
    main.PetWindow._build_state_pix(stub)
    angry = stub.state_pix["f0"]["angry"]
    # 资源图优先：angry 用用户配置图而非叠图
    assert angry is not None
    assert angry.cacheKey() == QPixmap(str(tmp_path / "roles" / "r1_angry.png")).cacheKey()
    # 程序化兜底：未配置的 blush 用叠图（与底图不同）
    blush = stub.state_pix["f0"]["blush"]
    assert blush is not None and blush.cacheKey() != base_pix.cacheKey()
    # 资源图文件缺失 → 回退程序化叠图（向后兼容）：
    # 不再等于资源图，且与底图不同（叠上了表情标记）
    resource_key = angry.cacheKey()
    (tmp_path / "roles" / "r1_angry.png").unlink()
    main.PetWindow._build_state_pix(stub)
    fallback = stub.state_pix["f0"]["angry"]
    assert fallback is not None
    assert fallback.cacheKey() != resource_key
    assert fallback.cacheKey() != base_pix.cacheKey()


def test_form_state_paths_is_the_production_state_lookup(tmp_path, qapp):
    """生产查表入口 RoleLibrary.form_state_paths：配了且文件在 → 绝对路径；未配置/缺文件不出现。

    v2.4.1：原 test_state_resource_pure 测的 pet_resources.state_resource(role, form_idx, state)
    已删除——全仓零生产引用（显示侧走 form_state_paths → 桌宠._build_state_pix），只有那一个
    用例引用它。这里把同一套「查表口径」钉在**真正的生产入口**上，并补两个负例。
    """
    (tmp_path / "roles").mkdir(exist_ok=True)
    _mk_png(str(tmp_path / "roles" / "r1_angry.png"))
    _write_index(tmp_path, [{
        "id": "r1", "name": "x", "file": "r1.png", "form": "single",
        "forms": [{"name": "常态", "file": "r1.png",
                   "states": {"angry": "r1_angry.png",
                              "cry": "r1_cry_missing.png"}}],
        "added": "",
    }])
    lib = pet_resources.RoleLibrary(str(tmp_path))
    paths = lib.form_state_paths("r1")
    assert paths[0]["angry"] == str(tmp_path / "roles" / "r1_angry.png")  # 配置 + 文件在
    assert "cry" not in paths[0]        # 负例：配了但文件缺失 → 不出现（显示侧走叠图兜底）
    assert "blush" not in paths[0]      # 负例：压根没配置
    assert lib.form_state_paths("不存在") == []   # 负例：角色不存在


# ---------------- update() patch ----------------

def test_update_patch(tmp_path):
    """update：改名/形态替换（改名/调序/渲染参数）/frames 超上限拒绝；id 不变。"""
    (tmp_path / "roles").mkdir(exist_ok=True)
    (tmp_path / "roles" / "r1.png").write_bytes(b"fakepng")
    (tmp_path / "roles" / "r1_full.png").write_bytes(b"fakepng")
    _write_index(tmp_path, [{
        "id": "r1", "name": "原名", "file": "r1.png", "form": "dual",
        "file_full": "r1_full.png", "added": "",
    }])
    lib = pet_resources.RoleLibrary(str(tmp_path))
    # 改名
    assert lib.update("r1", {"name": "  新名 "}) == (True, "")
    assert lib.get("r1")["name"] == "新名"
    # 形态整体替换：调序 + 渲染参数（结构统一归一化）
    ok, err = lib.update("r1", {"forms": [
        {"name": "第二", "file": "r1_full.png", "anchor": {"x": 0.5, "y": 1.0}},
        {"name": "第一", "file": "r1.png", "scale": 1.2, "offset": {"x": 1, "y": -2}},
    ]})
    assert ok and err == "", err
    role = lib.get("r1")
    assert role["id"] == "r1"
    assert [m["name"] for m in role["forms"]] == ["第二", "第一"]
    assert role["file"] == "r1_full.png"  # 顶层视图与 forms[0] 同步
    assert role["forms"][0]["anchor"] == {"x": 0.5, "y": 1.0}
    assert role["forms"][1]["scale"] == 1.2
    assert role.get("v2") is True
    # 重载持久化
    lib2 = pet_resources.RoleLibrary(str(tmp_path))
    assert lib2.get("r1")["forms"][0]["name"] == "第二"
    # frames 超上限拒绝（FRAME_MAX=24）
    ok2, err2 = lib.update("r1", {"frames": ["f%02d.png" % i for i in range(25)]})
    assert ok2 is False and "24" in err2
    # 形态数非法拒绝
    ok3, err3 = lib.update("r1", {"forms": []})
    assert ok3 is False and "1~8" in err3
    # 角色不存在 / 名字为空
    assert lib.update("nope", {"name": "x"}) == (False, "角色不存在")
    assert lib.update("r1", {"name": "  "}) == (False, "名字不能为空")


# ---------------- 读侧 FRAME_MAX 与 animations 共存 ----------------

def test_framemax_truncates_animations_per_action(tmp_path, monkeypatch):
    """读侧上限作用于每个动画动作；与旧 frames 视图口径一致。"""
    monkeypatch.setattr(pet_resources, "FRAME_MAX", 5)
    frames8 = ["f%02d.png" % i for i in range(8)]
    _write_index(tmp_path, [{
        "id": "r1", "name": "x", "file": "r1.png", "form": "single",
        "forms": [{"name": "常态", "file": "r1.png",
                   "animations": {"idle": list(frames8), "eat": list(frames8)}}],
        "added": "",
    }])
    lib = pet_resources.RoleLibrary(str(tmp_path))
    role = lib.get("r1")
    anims = role["forms"][0]["animations"]
    assert len(anims["idle"]) == 5 and len(anims["eat"]) == 5
    assert role["frames"] == anims["idle"]  # 兼容视图同口径
    # 导入侧拒绝带当前上限文案
    ok, err = lib.import_processed(None, None, "y", frames_src=[frames8[0]] * 6)
    assert ok is None and "5" in (err or "")


def test_framemax_legacy_frames_view(tmp_path, monkeypatch):
    """旧角色级 frames 的读侧截断仍生效（与 animations 迁移后一致）。"""
    monkeypatch.setattr(pet_resources, "FRAME_MAX", 5)
    _write_index(tmp_path, [{
        "id": "r1", "name": "x", "file": "r1.png", "form": "single",
        "frames": ["f%02d.png" % i for i in range(8)], "added": "",
    }])
    lib = pet_resources.RoleLibrary(str(tmp_path))
    role = next(r for r in lib._data["roles"] if r["id"] == "r1")
    assert len(role["frames"]) == 5
    assert len(role["forms"][0]["animations"]["idle"]) == 5


# ---------------- 导入新参数（向后兼容签名） ----------------

def test_import_processed_new_params(tmp_path):
    """interval_ms/render/keep_source 生效；旧调用方式（不传新参数）仍工作。"""
    p = tmp_path / "p.png"
    p.write_bytes(b"fakepng")
    lib = pet_resources.RoleLibrary(str(tmp_path))
    role, err = lib.import_processed(str(p), None, "新参数", interval_ms=90,
                                     render={"anchor": {"x": 0.5, "y": 1.0},
                                             "scale": 1.5, "offset": {"x": 2, "y": -3}},
                                     keep_source=True, source_files=[str(p)])
    assert err is None and role is not None, err
    assert role["v2"] is True
    f0 = role["forms"][0]
    assert f0["anim_interval_ms"] == 90
    assert f0["anchor"] == {"x": 0.5, "y": 1.0}
    assert f0["scale"] == 1.5
    assert f0["offset"] == {"x": 2, "y": -3}
    # 原图保留目录
    src_dir = tmp_path / "roles" / role["id"] / "source"
    assert src_dir.is_dir() and any(src_dir.iterdir())
    # 旧调用方式（不带新参数）完全兼容
    role2, err2 = lib.import_processed(str(p), None, "旧方式")
    assert err2 is None and role2 is not None
    assert role2.get("v2") is False
    assert role2["forms"][0].get("anim_interval_ms") is None
    # 删除角色连带清理 source 目录
    assert lib.delete(role["id"]) == (True, "")
    assert not src_dir.exists()
    # interval 非法拒绝
    role3, err3 = lib.import_processed(str(p), None, "x", interval_ms=-5)
    assert role3 is None and "10~10000" in (err3 or "")


def test_import_processed_states(tmp_path):
    """states 状态图随导入复制进角色目录并写入 forms[0].states。"""
    p = tmp_path / "p.png"
    p.write_bytes(b"fakepng")
    sp = tmp_path / "s.png"
    sp.write_bytes(b"fakepng2")
    lib = pet_resources.RoleLibrary(str(tmp_path))
    role, err = lib.import_processed(str(p), None, "带状态", states={"angry": str(sp)})
    assert err is None and role is not None, err
    st_file = role["forms"][0]["states"]["angry"]
    assert st_file.endswith(".png") and os.path.isfile(lib.resolve(st_file))


# ---------------- 编辑对话框（换图重跑管线不换 id） ----------------

def test_edit_dialog_reprocess_keeps_id(tmp_path, qapp):
    """RoleEditDialog：换图重跑管线不换 id；旧文件清理、新文件就位、索引落盘。"""
    import pet_dialogs
    old_p = tmp_path / "old.png"
    _mk_png(str(old_p), 60, 60, 0xFF3366CC)
    lib = pet_resources.RoleLibrary(str(tmp_path))
    role, err = lib.import_processed(str(old_p), None, "编辑前")
    assert err is None and role is not None, err
    rid = role["id"]
    old_file = lib.resolve(role["forms"][0]["file"])
    assert os.path.isfile(old_file)
    new_p = tmp_path / "new.png"
    _mk_png(str(new_p), 48, 48, 0xFF33CC66)
    dlg = pet_dialogs.RoleEditDialog(None, lib, rid)
    try:
        dlg._name_edit.setText("编辑后")
        dlg._pending_images[0] = str(new_p)
        dlg._save()
        role2 = lib.get(rid)
        assert role2["name"] == "编辑后"
        assert role2["id"] == rid  # 不换 id
        new_file = lib.resolve(role2["forms"][0]["file"])
        assert new_file != old_file and os.path.isfile(new_file)
        assert not os.path.exists(old_file)  # 旧文件被清理
        # 重载持久化
        lib2 = pet_resources.RoleLibrary(str(tmp_path))
        assert lib2.get(rid)["name"] == "编辑后"
    finally:
        dlg._cleanup()


def test_edit_dialog_reorder_and_front(tmp_path, qapp):
    """编辑对话框：形态调序 + 设正面图 + 状态图落盘。"""
    import pet_dialogs
    from PySide6.QtGui import QPixmap
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    f = tmp_path / "f.png"
    s = tmp_path / "s.png"
    _mk_png(str(a), 50, 50, 0xFF111111)
    _mk_png(str(b), 40, 40, 0xFF222222)
    _mk_png(str(f), 40, 40, 0xFF333333)
    _mk_png(str(s), 40, 40, 0xFF444444)
    lib = pet_resources.RoleLibrary(str(tmp_path))
    role, err = lib.import_processed(str(a), None, "双形态", forms_src=[("甲", str(a)), ("乙", str(b))])
    assert err is None and role is not None, err
    rid = role["id"]
    dlg = pet_dialogs.RoleEditDialog(None, lib, rid)
    try:
        # 调序：把乙换到第一（先选中形态乙，再上移）
        dlg._form_list.setCurrentRow(1)
        dlg._move_form(-1)
        assert dlg._forms[0]["name"] == "乙"
        # 设正面图 + 状态图
        dlg._cur_idx = 0
        dlg._pending_front[0] = str(f)
        dlg._pending_states[(0, "angry")] = str(s)
        dlg._save()
        role2 = lib.get(rid)
        assert [m["name"] for m in role2["forms"]] == ["乙", "甲"]
        f0 = role2["forms"][0]
        assert f0.get("front") and os.path.isfile(lib.resolve(f0["front"]))
        assert f0["states"].get("angry") and os.path.isfile(lib.resolve(f0["states"]["angry"]))
        # 正面图与侧图不同
        assert QPixmap(lib.resolve(f0["front"])).cacheKey() != QPixmap(lib.resolve(f0["file"])).cacheKey()
    finally:
        dlg._cleanup()

# ---------------- v2.0.1：动作自定义（命名帧动作 + 程序化合成动作） ----------------

def test_norm_animations_custom_keys():
    """自定义动作键（ASCII 安全名）保留；非法键/保留词/非 PNG/超限帧按口径丢弃截断。"""
    v = {"idle": ["a.png"], "dance1": ["d1.png", "d2.png"], "bad name": ["x.png"],
         123: ["n.png"], "eat": ["e.png"],
         "jump": ["j.png"], "interval_ms": ["i.png"],
         "spin": ["s%02d.png" % i for i in range(30)]}
    out = pet_resources._norm_animations(v)
    assert set(out) == {"idle", "dance1", "eat", "spin"}
    assert out["dance1"] == ["d1.png", "d2.png"]
    assert len(out["spin"]) == pet_resources.FRAME_MAX  # 超过上限截断
    assert "bad name" not in out and 123 not in out
    assert "jump" not in out and "interval_ms" not in out  # 保留词：死条目/合并键冲突 → 丢弃


def test_norm_procs():
    """程序化动作：kind 白名单、按 kind 钳 amp、非法/内建名/保留词丢弃。"""
    v = {"sway": {"kind": "sway", "amp": 99, "period_ms": 10},
         "bad": {"kind": "fly"},
         "nod": {"kind": "nod", "amp": 0.02, "period_ms": 900},
         "nod12": {"kind": "nod", "amp": 12.0, "period_ms": 400},
         "bad name": {"kind": "breathe"},
         "junk": "not-a-dict",
         "idle": {"kind": "breathe", "amp": 0.5, "period_ms": 500},
         "jump": {"kind": "sway"}}
    out = pet_resources._norm_procs(v)
    assert set(out) == {"sway", "nod", "nod12"}
    # 与内建动作/保留词重名：play_action 分支永远命中不了 → 丢弃
    assert "idle" not in out and "jump" not in out
    assert out["sway"]["amp"] == 1.0 and out["sway"]["period_ms"] == 200  # 钳到边界
    assert out["nod"]["amp"] == 1.0 and out["nod"]["period_ms"] == 900  # nod 像素口径下钳 1px
    assert out["nod"]["kind"] == "nod"
    assert out["nod12"]["amp"] == 12.0  # nod 像素口径：12px 默认值原样保留（不被钳死）


def test_is_valid_custom_action():
    """命名校验：保留词/内建名/非法名拒绝，与归一化丢弃同口径。"""
    assert pet_resources.is_valid_custom_action("dance") is True
    assert pet_resources.is_valid_custom_action("sway2") is True
    for bad in ("idle", "eat", "poke", "sleep", "jump", "emote", "none",
                "interval_ms", "bad name", "", "9abc", None, 123):
        assert pet_resources.is_valid_custom_action(bad) is False, bad


def test_custom_actions_accessors(tmp_path):
    """custom_actions/procs 暴露自定义动作（不含内建动作）；未知角色/越界形态为空。"""
    _write_index(tmp_path, [{
        "id": "r1", "name": "x", "file": "r1.png", "form": "single",
        "frames": ["r1_f00.png"],
        "forms": [{"name": "常态", "file": "r1.png",
                   "animations": {"idle": ["r1_f00.png"], "dance": ["d1.png"],
                                  "sleep": ["s1.png"]},
                   "procs": {"sway": {"kind": "sway", "amp": 0.05, "period_ms": 1600}}}],
        "added": "",
    }], active="r1")
    lib = pet_resources.RoleLibrary(str(tmp_path))
    acts = lib.custom_actions("r1", 0)
    assert ("dance", "frames") in acts
    assert ("sway", "proc") in acts
    # 内建动作不在自定义清单里
    assert all(a[0] not in pet_resources.ANIM_ACTIONS for a in acts)
    procs = lib.procs("r1", 0)
    assert procs["sway"] == {"kind": "sway", "amp": 0.05, "period_ms": 1600}
    assert lib.custom_actions("nope") == [] and lib.custom_actions("r1", 9) == []
    assert lib.procs("nope") == {} and lib.procs("r1", 9) == {}


def test_form_role_flags(tmp_path):
    """v2.0.2 断点#12：形态角色标记归一化与访问器（"false"/"0" 字符串不算真）。"""
    _write_index(tmp_path, [{
        "id": "r3", "name": "x", "file": "a.png", "form": "dual",
        "frames": ["a.png"],
        "forms": [{"name": "常态", "file": "a.png", "sleep_form": "false", "no_feed": "0"},
                  {"name": "二", "file": "b.png", "sleep_form": True,
                   "transform_form": "true", "no_feed": 1}],
        "added": "",
    }], active="r3")
    lib = pet_resources.RoleLibrary(str(tmp_path))
    flags = lib.form_role_flags("r3")
    assert flags == [{"sleep_form": False, "transform_form": False, "no_feed": False},
                     {"sleep_form": True, "transform_form": True, "no_feed": True}]
    assert lib.form_role_flags("nope") == []


def test_delete_removes_custom_action_frames(tmp_path):
    """v2.0.1：自定义帧动作的文件也参与角色删除清理（_role_paths 收全动作键）。"""
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    for fn in ("r_base.png", "r_d1.png", "r_d2.png"):
        _mk_png(str(roles_dir / fn), 24, 24)
    _write_index(tmp_path, [{
        "id": "r2", "name": "x", "file": "r_base.png", "form": "single",
        "frames": ["r_base.png"],
        "forms": [{"name": "常态", "file": "r_base.png",
                   "animations": {"idle": ["r_base.png"],
                                  "dance": ["r_d1.png", "r_d2.png"]}}],
        "added": "",
    }], active="r2")
    lib = pet_resources.RoleLibrary(str(tmp_path))
    assert pet_resources.animation_frames(lib.get("r2"), 0, "dance") == ["r_d1.png", "r_d2.png"]
    ok, err = lib.delete("r2")
    assert ok and not err, err
    assert not (roles_dir / "r_d1.png").exists()
    assert not (roles_dir / "r_d2.png").exists()
    assert not (roles_dir / "r_base.png").exists()


