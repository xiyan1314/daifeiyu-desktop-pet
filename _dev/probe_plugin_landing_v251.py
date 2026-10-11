# -*- coding: utf-8 -*-
"""官方内容插件的**落地实测**（v2.5.1 · 代理 C）：5 个包真的装进一个临时数据目录。

为什么有这个脚本：任务书要求"先确认每类的落地可行性再打包"。光读接口不算数——这里把每个
官方包的 payload 真的喂给**宿主现成的落地管线**（全部 Qt-free，无 GUI），并断言：

  * 目标库里条目**增加**了正确数量；
  * 装之前就存在的用户数据**一条不少**（不覆盖、不删除）；
  * 包文件删掉之后，已落地的条目仍在（资产属用户数据，与"导入角色包"同口径）。

落地管线（插件侧零新代码，每条都对应一个现成的宿主接口）：

    audio     -> pet_resources.AudioLibrary.import_file(path, name)
    lines     -> pet_lines.LineService.add(text, category, role_slot, voice_slot) + add_dialogue
    role      -> pet_export.import_bundle(role_lib, behaviors_svc, cfg, 由 payload 打的临时 zip)
    behaviors -> pet_behaviors.BehaviorService.import_file(path)
    prompt    -> 拷进 <数据目录>/prompts/custom/<名字>.txt（桌宠.persona_file_ids 自动认）

用法::

    python -B _dev/probe_plugin_landing_v251.py
"""
import json
import os
import shutil
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
for p in (REPO, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import plugin_pack_rules as rules        # noqa: E402
import build_official_plugins as builder  # noqa: E402
import pet_behaviors                      # noqa: E402
import pet_export                         # noqa: E402
import pet_lines                          # noqa: E402
import pet_resources                      # noqa: E402

PACKS = os.path.join(REPO, "plugins", "packs")
RESULTS = []


def check(label, ok, detail=""):
    RESULTS.append((label, bool(ok), detail))
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", label,
                           ("  -- %s" % detail) if (detail and not ok) else ""))


def _pack_zip(pack_id):
    return os.path.join(PACKS, "%s-%s%s" % (pack_id, builder.PACK_VERSION, builder.BUNDLE_EXT))


def _payload_dir(pack_id, dest):
    """把包的 payload/ 解到一个临时目录，返回 payload 根路径。"""
    out = os.path.join(dest, pack_id)
    with zipfile.ZipFile(_pack_zip(pack_id)) as zf:
        zf.extractall(out)
    return os.path.join(out, "payload")


def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def case_audio(data_dir, payload):
    lib = pet_resources.AudioLibrary(data_dir)
    seed, serr = lib.import_file(os.path.join(payload, "audio", "ya1.wav"), name="用户已有的片段")
    check("audio：预置一条用户片段", seed is not None, str(serr))
    before = len(lib.fragments())
    meta = _read_json(os.path.join(payload, "audio", "pack.json"))
    items = [{"file": os.path.basename(f["file"]), "name": f["name"]} for f in meta["files"]]
    bad = []
    for item in items:
        frag, err = lib.import_file(os.path.join(payload, "audio", item["file"]),
                                    name=item["name"])
        if frag is None:
            bad.append("%s: %s" % (item["file"], err))
    after = lib.fragments()
    check("audio：%d 段全部落地（AudioLibrary.import_file）" % len(items),
          not bad and len(after) == before + len(items), "；".join(bad))
    check("audio：原有片段一条不少（%d -> %d）" % (before, len(after)),
          len(after) == before + len(items))
    names = {f["name"] for f in after}
    check("audio：新片段都带上了包里的显示名",
          all(i["name"] in names for i in items), str(sorted(names)))
    check("audio：每段都能取到真实文件（fragment_path）",
          all(lib.fragment_path(f["id"]) for f in after))
    return len(after)


def case_lines(data_dir, payload):
    svc = pet_lines.LineService(data_dir)
    user, uerr = svc.add("用户自己写的台词（不许被动）", "idle")
    check("lines：预置一条用户台词", user is not None, str(uerr))
    before = svc.count()
    meta = _read_json(os.path.join(payload, "lines.json"))
    bad, key_map = [], {}
    for item in meta["lines"]:
        got, err = svc.add(item["text"], item["category"],
                           item.get("role_slot") or None, item.get("voice_slot") or None)
        if got is None:
            bad.append("%s: %s" % (item["key"], err))
        else:
            key_map[item["key"]] = got["id"]
    check("lines：%d 条全部落地（LineService.add）" % len(meta["lines"]),
          not bad and len(key_map) == len(meta["lines"]), "；".join(bad))
    check("lines：原有台词一条不少（%d -> %d）" % (before, svc.count()),
          svc.count() == before + len(meta["lines"]))
    check("lines：用户那条还在",
          any(l["text"].startswith("用户自己写的") for l in svc.lines()))
    check("lines：类别都在 pet_lines.LINE_CATEGORIES 里",
          all(i["category"] in pet_lines.LINE_CATEGORIES for i in meta["lines"]))
    for d in meta["dialogues"]:
        ids = [key_map[k] for k in d.get("lines") or [] if k in key_map]
        obj, derr = svc.add_dialogue(d["name"], ids)
        check("lines：对白「%s」落地（add_dialogue，%d 条）" % (d["name"], len(ids)),
              obj is not None and len(obj.get("line_ids") or []) == len(ids), str(derr))
    return svc.count()


def case_behaviors(data_dir, payload):
    svc = pet_behaviors.BehaviorService(data_dir)
    got, err = svc.add("user_made", [{"act": "say", "text": "用户自己的行为"}])
    check("behaviors：预置一条用户行为", got is not None, str(err))
    before = len(svc.list())
    files = sorted(os.path.join(payload, "behaviors", n)
                   for n in os.listdir(os.path.join(payload, "behaviors")))
    bad = []
    for p in files:
        obj, ierr = svc.import_file(p)
        if obj is None:
            bad.append("%s: %s" % (os.path.basename(p), ierr))
    after = svc.list()
    check("behaviors：%d 条全部落地（BehaviorService.import_file）" % len(files),
          not bad and len(after) == before + len(files), "；".join(bad))
    check("behaviors：原有行为一条不少（%d -> %d）" % (before, len(after)),
          len(after) == before + len(files))
    check("behaviors：用户那条还在", any(b["name"] == "user_made" for b in after))
    check("behaviors：每条都能过宿主自己的 validate_steps",
          all(pet_behaviors.validate_steps(b["steps"])[1] == "" for b in after),
          str([pet_behaviors.validate_steps(b["steps"])[1] for b in after]))
    check("behaviors：行为名都过 validate_name（ASCII 安全名）",
          all(pet_behaviors.validate_name(b["name"]) for b in after))
    return len(after)


def _payload_entries(payload):
    """payload 目录 -> [(相对路径, bytes)]（按路径排序）。"""
    out = []
    for root, _dirs, files in os.walk(payload):
        for fn in files:
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, payload).replace(os.sep, "/")
            with open(p, "rb") as f:
                out.append((rel, f.read()))
    out.sort(key=lambda kv: kv[0])
    return out


def case_role(data_dir, payload, work):
    lib = pet_resources.RoleLibrary(data_dir)
    before = len(lib.list_roles())
    seed, serr = lib.import_processed(os.path.join(payload, "daifeiyu.png"),
                                      name="用户自己导的角色")
    check("role：预置一个用户角色（RoleLibrary.import_processed）", seed is not None, str(serr))
    seed_id = (seed or {}).get("id") or ""
    # 落地口径（与 pet_plugin_host._land_role_dict 同一套）：payload/role.json 的素材引用
    # 是 payload 根下的 png 文件名 → 换新名复制进 roles/ → _remap_role_files → land_role
    role = _read_json(os.path.join(payload, "role.json"))
    refs = pet_export._role_file_refs(role)
    name_map, missing = {}, []
    for ref in refs:
        srcp = os.path.join(payload, *ref.split("/"))
        if not os.path.isfile(srcp):
            missing.append(ref)
            continue
        new_name = "probe%s.png" % len(name_map)
        dst = lib.resolve(new_name)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(srcp, dst)
        name_map[ref] = new_name
    check("role：role.json 的 %d 个素材引用全部命中 payload 里的文件" % len(refs),
          not missing, "缺：%s" % missing)
    rid, ierr = pet_export.land_role(lib, pet_export._remap_role_files(role, name_map))
    check("role：pet_export.land_role 落地成功（与「导入角色包」同一套口径）",
          bool(rid), str(ierr))
    if not rid:
        return len(lib.list_roles())
    got = lib.get(rid)
    check("role：角色进库，双形态 + 名字带过来",
          got is not None and len(got.get("forms") or []) == 2
          and got.get("name") == role.get("name"),
          repr(got and (got.get("name"), len(got.get("forms") or []))))
    # form_state_paths 返回的是**逐形态**对齐的 [{"state": 绝对路径}, ...]（不是一维路径表）
    paths = lib.form_state_paths(rid) if got else []
    ok_states = (isinstance(paths, list) and len(paths) == 2
                 and len(paths[0]) == 10 and len(paths[1]) == 7
                 and all(os.path.isfile(p) for m in paths for p in m.values()))
    check("role：双形态状态图逐形态对齐（常态 10 / 吃饱 7，文件都在，走生产查表）",
          ok_states,
          "常态 %d / 吃饱 %d" % (len(paths[0]) if paths else -1,
                                 len(paths[1]) if len(paths) > 1 else -1))
    check("role：原有角色一条不少（%d -> %d）" % (before + 1, len(lib.list_roles())),
          len(lib.list_roles()) == before + 2)
    check("role：预置的用户角色没被动过", bool(seed_id) and lib.get(seed_id) is not None)
    name_map2 = {}
    for ref in refs:
        new_name = "probe2_%s.png" % len(name_map2)
        shutil.copyfile(os.path.join(payload, *ref.split("/")), lib.resolve(new_name))
        name_map2[ref] = new_name
    rid2, _e2 = pet_export.land_role(lib, pet_export._remap_role_files(role, name_map2))
    check("role：重复导入不覆盖（换新 id）",
          bool(rid2) and rid2 != rid, "两次 id=%r/%r" % (rid, rid2))
    return len(lib.list_roles())


def case_prompt(data_dir, payload):
    custom = os.path.join(data_dir, "prompts", "custom")
    os.makedirs(custom, exist_ok=True)
    with open(os.path.join(custom, "既有人设.txt"), "w", encoding="utf-8") as f:
        f.write("用户自己写的人设\n")
    src = os.path.join(payload, "prompts", builder.PERSONA_NAME + ".txt")
    dst = os.path.join(custom, os.path.basename(src))
    shutil.copyfile(src, dst)
    names = sorted(os.listdir(custom))
    check("prompt：人设文件落地到 prompts/custom/", os.path.basename(src) in names, str(names))
    # 复刻 桌宠.persona_file_ids 的判据（那段代码在 桌宠.py 里，import 会拉 Qt；判据逐字照抄）
    ids = set()
    for n in names:
        if n.lower().endswith(".txt") and len(n) > 4 and os.path.isfile(os.path.join(custom, n)):
            ids.add("file:" + n[:-4])
    check("prompt：宿主的发现规则认得出它（file:%s）" % builder.PERSONA_NAME,
          ("file:" + builder.PERSONA_NAME) in ids, str(sorted(ids)))
    check("prompt：原有人设文件仍在", "既有人设.txt" in names)
    with open(dst, "r", encoding="utf-8") as f:
        text = f.read()
    check("prompt：人设文本非空且是 UTF-8", len(text.strip()) > 30, "%d 字符" % len(text))


def main():
    print("官方内容插件落地实测 · 宿主版本 %s" % rules.host_version())
    for pack in builder.PACKS:
        if not os.path.isfile(_pack_zip(pack["id"])):
            print("缺少包：%s（先跑 _dev/build_official_plugins.py）" % _pack_zip(pack["id"]))
            return 1
    with tempfile.TemporaryDirectory(prefix="dfypet_landing_") as work:
        data_dir = os.path.join(work, "data")
        os.makedirs(data_dir, exist_ok=True)
        payloads = {p["id"]: _payload_dir(p["id"], work) for p in builder.PACKS}
        print("-- audio（AudioLibrary）")
        case_audio(data_dir, payloads["official-audio-core"])
        print("-- lines（LineService）")
        case_lines(data_dir, payloads["official-lines-moyu"])
        print("-- behaviors（BehaviorService）")
        case_behaviors(data_dir, payloads["official-behaviors-idle"])
        print("-- role（pet_export.import_bundle）")
        case_role(data_dir, payloads["official-role-daifeiyu"], work)
        print("-- prompt（prompts/custom/*.txt）")
        case_prompt(data_dir, payloads["official-persona-moyu"])
    bad = [r for r in RESULTS if not r[1]]
    print("\n共 %d 条检查：PASS %d / FAIL %d" % (len(RESULTS), len(RESULTS) - len(bad), len(bad)))
    for label, _ok, detail in bad:
        print("  FAIL %s\n       %s" % (label, detail))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
