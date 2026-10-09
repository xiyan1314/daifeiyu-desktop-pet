# -*- coding: utf-8 -*-
"""
大肥鱼桌宠 · 角色导出/导入（v2.0.3）
MIT License

职责：把「角色（含全部素材文件）+ 行为库 + 可分享配置（语音开关/音效组/气泡样式/
自定义台词/待机行为选择）」打包成单个 .dfypet.zip 分享文件；导入侧解包、
校验素材完整性、生成新 id 防覆盖、缺资源明确报错。纯逻辑、Qt-free，可无 GUI 单测。

敏感内容默认不导出：config 只取白名单键（api_key 等密钥一律排除，manifest 里
记录被排除的键名）；语音只导出开关/合成参数，不导出用户音频片段文件。

包结构：
  manifest.json  {"format":"dfypet-role","version":1,"role":{...},"behaviors":[...],
                  "config":{...},"excluded":["api_key",...],"alarms":[闹钟设置]}
  roles/<文件名>  角色引用的全部 png（manifest.role 内以文件名引用）

闹钟设置（系统⑥）v2.0.5 已启用：manifest.alarms 携带闹钟列表
（铃声文件不随包，导入侧换默认提示音并明确警告）；缺失/未知字段宽容处理。
"""

import json
import os
import shutil
import tempfile
import uuid
import zipfile

BUNDLE_FORMAT = "dfypet-role"
BUNDLE_VERSION = 1
MANIFEST_NAME = "manifest.json"

# 包容量上限（导出/校验同口径单一来源）：放宽到合法大角色必然往返成功
# （role_frame_max 可调至 60 帧 × 8 形态 × 多动作 + 各形态 side/front/states）
EXPORT_MAX_ENTRIES = 2000
EXPORT_MAX_BYTES = 512 * 1024 * 1024

# 可分享配置键白名单（导出/导入共用；api_key 等敏感键永不在此列）
EXPORT_CONFIG_KEYS = ("voice", "sound_group", "bubble_style", "lines_extra", "idle_behavior",
                      # v2.1：待机系统（两触发/待机形态/待机动作列表/播放模式）
                      "idle_trigger_delay", "idle_delay_after_full", "idle_form",
                      "idle_actions", "idle_play_mode", "idle_resume_on_interrupt")

# v2.1：voice 配置里必须剥掉的敏感子键（导出包不得带密钥）
VOICE_SECRET_KEYS = ("backend_keys",)
# 敏感键：默认不导出（manifest.excluded 记录，导入侧自然缺省）
SENSITIVE_KEYS = ("api_key",)


def _role_file_refs(role):
    """角色 dict 引用的全部相对文件名（file/file_full/顶层 frames 兼容视图/
    forms 的 file·front·animations 各动作帧·states 状态图），去重排序。

    与 RoleLibrary._role_paths 同口径 + 顶层 frames（第三方旧格式包兼容）；
    非字符串值（坏数据）一律跳过，防逐字符/整 list 冒充文件名造成乱码报错。"""
    names = []
    for v in (role.get("file"), role.get("file_full")):
        if isinstance(v, str) and v:
            names.append(v)
    if isinstance(role.get("frames"), list):
        names.extend(x for x in role["frames"] if isinstance(x, str))
    for fm in role.get("forms") or []:
        if not isinstance(fm, dict):
            continue
        for v in (fm.get("file"), fm.get("front")):
            if isinstance(v, str) and v:
                names.append(v)
        anims = fm.get("animations")
        if isinstance(anims, dict):
            for act in anims:
                lst = anims.get(act)
                if isinstance(lst, list):
                    names.extend(x for x in lst if isinstance(x, str))
        states = fm.get("states")
        if isinstance(states, dict):
            names.extend(v for v in states.values() if isinstance(v, str))
    return sorted(set(names))


def _remap_role_files(role, name_map):
    """把 role dict 里的全部文件名按 name_map 换成新名（导入防同名覆盖）。"""
    def _map(v):
        return name_map.get(str(v), str(v))
    out = dict(role)
    if out.get("file"):
        out["file"] = _map(out["file"])
    if out.get("file_full"):
        out["file_full"] = _map(out["file_full"])
    if isinstance(out.get("frames"), list):
        out["frames"] = [_map(x) for x in out["frames"] if isinstance(x, str)]
    forms = []
    for fm in out.get("forms") or []:
        if not isinstance(fm, dict):
            forms.append(fm)
            continue
        f2 = dict(fm)
        if f2.get("file"):
            f2["file"] = _map(f2["file"])
        if f2.get("front"):
            f2["front"] = _map(f2["front"])
        if isinstance(f2.get("animations"), dict):
            f2["animations"] = {a: [_map(x) for x in lst] if isinstance(lst, list) else lst
                                for a, lst in f2["animations"].items()}
        if isinstance(f2.get("states"), dict):
            f2["states"] = {s: _map(p) if isinstance(p, str) else p
                            for s, p in f2["states"].items()}
        forms.append(f2)
    if forms:
        out["forms"] = forms
    return out


def _scrub_config(config):
    """剥掉嵌套敏感子键与 URL 内嵌凭据（导出包不得携带任何密钥）。

    - voice.backend_keys：各家克隆后端的 API Key
    - base_url 里的 query 串：形如 https://x?key=xxx / &token=xxx 的内嵌凭据（L10）
    """
    out = dict(config or {})
    v = out.get("voice")
    if isinstance(v, dict):
        v = dict(v)
        for k in VOICE_SECRET_KEYS:
            v.pop(k, None)
        params = v.get("backend_params")
        if isinstance(params, dict):
            params = dict(params)
            for bid, sub in list(params.items()):
                if isinstance(sub, dict) and isinstance(sub.get("base_url"), str):
                    sub = dict(sub)
                    sub["base_url"] = _strip_url_creds(sub["base_url"])
                    params[bid] = sub
            v["backend_params"] = params
        out["voice"] = v
    return out


def _strip_url_creds(url):
    """去掉 URL query 里的凭据参数（key/token/secret/access_key 等），保留其余部分。"""
    u = str(url or "")
    if "?" not in u:
        return u
    base, _q, query = u.partition("?")
    keep = []
    for part in query.split("&"):
        name = part.split("=", 1)[0].strip().lower()
        if name in ("key", "api_key", "apikey", "token", "access_token", "secret",
                    "access_key", "sk"):
            continue
        if part:
            keep.append(part)
    return base + (("?" + "&".join(keep)) if keep else "")


def build_manifest(role, behaviors, cfg, alarms=None, lines=None, dialogues=None,
                   voice_assets=None):
    """构造导出 manifest。返回 (manifest, err)；角色缺文件引用报错。

    role=role_lib.get(rid)；behaviors=行为 dict 列表；cfg=当前配置 dict；
    alarms=闹钟 dict 列表（v2.0.5）；lines/dialogues=台词与对白（v2.1）；
    voice_assets=随包的声音素材元数据（v2.1，默认 None=不带参考音文件）。
    """
    if not isinstance(role, dict) or not role.get("id"):
        return None, "角色不存在或数据为空"
    config = {}
    for k in EXPORT_CONFIG_KEYS:
        if k in cfg:
            config[k] = cfg[k]
    config = _scrub_config(config)
    manifest = {
        "format": BUNDLE_FORMAT,
        "version": BUNDLE_VERSION,
        "role": dict(role),
        "behaviors": [dict(b) for b in (behaviors or []) if isinstance(b, dict)],
        "config": config,
        # 记录本次实际被排除的敏感键（cfg 里存在的那些；白名单才是真防线）
        "excluded": [k for k in SENSITIVE_KEYS if k in cfg]
                    + (["voice." + k for k in VOICE_SECRET_KEYS
                        if isinstance(cfg.get("voice"), dict) and k in cfg["voice"]]),
        # v2.0.5：闹钟设置（铃声文件不随包，导入侧明确提示换默认音）
        "alarms": list(alarms) if isinstance(alarms, list) else None,
        # v2.1：台词 / 对白 /（可选）声音素材。L8 修复：非 dict 元素过滤掉（与 behaviors 同口径），
        # 否则伪造/坏数据会在导出时抛 TypeError（只能看到笼统的"导出失败"）。
        "lines": [dict(x) for x in lines if isinstance(x, dict)] if isinstance(lines, list) else None,
        "dialogues": [dict(x) for x in dialogues if isinstance(x, dict)]
        if isinstance(dialogues, list) else None,
        "voice_assets": [dict(x) for x in voice_assets if isinstance(x, dict)]
        if isinstance(voice_assets, list) else None,
    }
    return manifest, ""


def export_bundle(role_lib, behaviors_svc, cfg, out_path, alarms_getter=None,
                  lines_getter=None, dialogues_getter=None,
                  voice_assets_getter=None, include_voice_ids=None):
    """导出角色包到 out_path（zip）。返回 (ok, err)。

    收集 role_lib 当前角色的全部素材文件进 roles/ 子目录；缺文件明确报错。
    alarms_getter（可选）：闹钟设置（不含铃声文件）。
    lines_getter/dialogues_getter（可选）：台词与对白（v2.1，随包分享）。
    voice_assets_getter（可选）+ include_voice_ids（勾选的素材 id）：
        把参考音文件打进 voice_ref/（**默认不打包**，体积与隐私考虑，用户勾选才带）。
    """
    rid = str((cfg or {}).get("role") or "")
    role = role_lib.get(rid) if rid else None
    if role is None:
        return False, "请先在「角色」面板选择一个自定义角色再导出"
    try:
        entries = []
        for ref in _role_file_refs(role):
            if ref != os.path.basename(ref):
                # 引用含路径分隔符 = 角色数据异常（正常管线不产生），拒绝自产坏包
                return False, "角色数据异常：引用含路径「%s」，请重新导入该角色" % ref
            p = role_lib.resolve(ref)
            if not os.path.isfile(p):
                return False, "角色素材缺失，无法导出：%s" % ref
            entries.append((ref, p))
        _behaviors = behaviors_svc.list() if behaviors_svc is not None else []
        _alarms = alarms_getter() if alarms_getter is not None else None
        _lines = lines_getter() if lines_getter is not None else None
        _dlgs = dialogues_getter() if dialogues_getter is not None else None
        # v2.1：参考音默认不打包；勾选（include_voice_ids）才带文件
        _vmeta, _vfiles = None, []
        if voice_assets_getter is not None and include_voice_ids:
            _want = {str(x) for x in include_voice_ids}
            for a in (voice_assets_getter() or []):
                if str(a.get("id")) not in _want:
                    continue
                _p = a.get("path")
                if not _p or not os.path.isfile(_p):
                    return False, "声音素材文件缺失，无法导出：%s" % a.get("name", a.get("id"))
                _ext = os.path.splitext(_p)[1].lower()
                _vmeta = (_vmeta or [])
                _vmeta.append({"id": str(a.get("id")), "name": str(a.get("name") or ""),
                               "ext": _ext, "file": "voice_ref/%s%s" % (a.get("id"), _ext)})
                _vfiles.append(("voice_ref/%s%s" % (a.get("id"), _ext), _p))
        manifest, err = build_manifest(role, _behaviors, cfg or {}, _alarms, _lines, _dlgs, _vmeta)
        if manifest is None:
            return False, err
        tmp = out_path + ".tmp"
        try:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
                for ref, p in entries:
                    zf.write(p, "roles/" + os.path.basename(ref))
                for arc, p in _vfiles:
                    zf.write(p, arc)
            os.replace(tmp, out_path)  # 原子替换：半截包不会被当作有效文件
        except Exception as e:
            try:
                if os.path.isfile(tmp):
                    os.remove(tmp)
            except Exception:
                pass  # 有意忽略：残留临时文件清理尽力而为
            return False, "写入失败：%s" % e
        # 导出侧自校验：容量上限同口径，导出时即报错而不是让接收方导入才踩坑
        _m, _err = validate_bundle(out_path)
        if _m is None:
            try:
                os.remove(out_path)
            except Exception:
                pass  # 有意忽略：自校验失败包的清理尽力而为
            return False, "导出包自校验失败：%s" % _err
        return True, ""
    except Exception as e:
        return False, "导出失败：%s" % e


def validate_bundle(zip_path):
    """校验角色包结构与素材完整性。返回 (manifest, err)。"""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            # 恶意包防御：条目数/解压总量上限（防 zip 炸弹）——先于任何解压读取
            info = zf.infolist()
            if len(info) > EXPORT_MAX_ENTRIES or sum(i.file_size for i in info) > EXPORT_MAX_BYTES:
                return None, "角色包条目过多或体积过大，已拒绝"
            try:
                manifest = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
            except KeyError:
                return None, "不是角色包：缺少 manifest.json"
            except Exception as e:
                return None, "manifest.json 无法解析：%s" % e
            if not isinstance(manifest, dict):
                return None, "manifest 不是对象"
            if manifest.get("format") != BUNDLE_FORMAT:
                return None, "不是大肥鱼角色包（format=%r）" % manifest.get("format")
            role = manifest.get("role")
            if not isinstance(role, dict) or not role.get("file"):
                return None, "角色包缺少角色数据"
            # 坏结构明确报错：id 必须为非空字符串（缺失/数字 id 会产出幽灵角色）
            if not isinstance(role.get("id"), str) or not role.get("id", "").strip():
                return None, "角色包缺少角色 id"
            names = zf.namelist()
            missing = []
            for ref in _role_file_refs(role):
                if ref != os.path.basename(ref):
                    # 非法引用（含路径分隔符/上级目录）：直接拒绝，不做 basename 归一
                    return None, "角色包引用非法文件名：%s" % ref
                if "roles/" + ref not in names:
                    missing.append(ref)
            if missing:
                return None, "角色包素材缺失：%s" % "、".join(missing[:5])
            return manifest, ""
    except zipfile.BadZipFile:
        return None, "文件不是有效的 zip 包"
    except Exception as e:
        return None, "打开失败：%s" % e


def import_bundle(role_lib, behaviors_svc, cfg, zip_path, alarms_apply=None,
                  voice_apply=None, lines_apply=None):
    """导入角色包：解包素材（换新文件名防覆盖）、注册角色与行为（新 id）、
    应用可分享配置与闹钟设置。返回 (result|None, err)；任何缺资源/坏结构明确报错。

    alarms_apply（可选）：接收包内闹钟设置列表、返回警告列表的回调。
    voice_apply（可选）：接收（声音素材列表, 解包目录）、返回 {旧槽位: 新槽位} 映射的回调。
    lines_apply（可选）：接收（台词列表, 对白列表, 映射表）、返回警告列表的回调；
        映射表 = {"voice": 旧→新声音槽位, "role": 旧→新角色 id}。
    result = {"role_id", "behavior_map": {旧id: 新id}, "warnings": [...]}
    """
    manifest, err = validate_bundle(zip_path)
    if manifest is None:
        return None, err
    warnings = []
    written = []          # 本次已解包的文件（异常时回滚）
    role_appended = False
    role_map = {}         # v2.1：旧角色 id → 新角色 id（绑定/台词引用重映射用）
    extract_dir = None    # v2.1：随包声音素材的临时解包目录（用完即删）
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            role = dict(manifest["role"])
            _old_rid = str(role.get("id") or "")
            # 素材换新文件名（防与现有角色文件同名覆盖），并重写全部引用
            name_map = {}
            for ref in _role_file_refs(role):
                new_name = "%s_i%s.png" % (uuid.uuid4().hex[:8], uuid.uuid4().hex[:6])
                src = zf.read("roles/" + os.path.basename(ref))
                dst = role_lib.resolve(new_name)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, "wb") as f:
                    f.write(src)
                name_map[ref] = new_name
                written.append(dst)
            role = _remap_role_files(role, name_map)
            # 行为：全部换新 id 导入，记录旧→新映射（供 idle_behavior 重映射）
            # 恶意/坏结构防御：behaviors 非列表或条目非对象 → 跳过并记警告，不崩
            behavior_map = {}
            _bhvs = manifest.get("behaviors")
            if not isinstance(_bhvs, list):
                warnings.append("包内行为数据格式非法，已跳过")
                _bhvs = []
            for b in _bhvs:
                if not isinstance(b, dict):
                    warnings.append("跳过非法行为条目")
                    continue
                nb, berr = behaviors_svc.add(str(b.get("name") or "imported"),
                                             b.get("steps"))
                if nb is not None:
                    behavior_map[str(b.get("id") or "")] = nb["id"]
                else:
                    warnings.append("行为「%s」未导入：%s" % (b.get("name"), berr))
            # 应用可分享配置（白名单键；idle_behavior 经映射重指；
            # 坏值跳过并记警告——伪造包不得污染运行配置）
            # S1 修复：导出包**不含**密钥，导入时若整段覆盖会把用户自己的 Key 清掉 →
            # 先把本地 backend_keys 备份出来，应用配置后回填。
            _local_keys = {}
            try:
                _lv = (cfg or {}).get("voice") or {}
                if isinstance(_lv.get("backend_keys"), dict):
                    _local_keys = dict(_lv["backend_keys"])
            except Exception:
                _local_keys = {}  # 有意忽略：拿不到就当作没有本地密钥
            _cfg = manifest.get("config") or {}
            if "idle_behavior" in _cfg:
                if not isinstance(_cfg["idle_behavior"], str):
                    warnings.append("包内待机行为配置非法，已跳过")
                    _cfg.pop("idle_behavior", None)
                else:
                    _old = str(_cfg["idle_behavior"] or "")
                    _cfg["idle_behavior"] = behavior_map.get(_old, "")
                    if _old and not _cfg["idle_behavior"]:
                        warnings.append("待机行为不在包内，已置为不启用")
            # v2.1：待机动作列表里的行为 id 要按映射重指；失效的行为条目丢弃并提示
            if "idle_actions" in _cfg:
                _ia = _cfg.get("idle_actions")
                if not isinstance(_ia, list):
                    warnings.append("包内待机动作列表非法，已跳过")
                    _cfg.pop("idle_actions", None)
                else:
                    _kept = []
                    for _a in _ia:
                        if not isinstance(_a, dict):
                            continue
                        _old_b = str(_a.get("behavior_id") or "")
                        _new_b = behavior_map.get(_old_b)
                        if not _new_b:
                            continue
                        _kept.append({"id": _new_b, "behavior_id": _new_b,
                                      "enabled": _a.get("enabled") is not False,
                                      "weight": _a.get("weight", 1.0),
                                      "order": _a.get("order", len(_kept) + 1)})
                    if len(_kept) != len(_ia):
                        warnings.append("待机列表里有行为不在包内，已跳过")
                    _cfg["idle_actions"] = _kept
            # 待机形态属于具体角色：导入包里的形态键可能不存在，交给用户重选
            if _cfg.get("idle_form"):
                warnings.append("待机形态沿用包内设置（%s），若当前角色没有该形态会自动忽略"
                                % _cfg["idle_form"])
            for k in ("voice", "bubble_style", "lines_extra"):
                if k in _cfg and not isinstance(_cfg[k], dict):
                    warnings.append("包内「%s」配置格式非法，已跳过" % k)
                    _cfg.pop(k, None)
            if "sound_group" in _cfg and _cfg["sound_group"] not in ("default", "custom"):
                warnings.append("包内音效组配置非法，已跳过")
                _cfg.pop("sound_group", None)
            for k in EXPORT_CONFIG_KEYS:
                if k not in _cfg:
                    continue
                if k == "voice":
                    # L7 修复：别人的后端/地址不该替换本机已配置的（只补空缺），否则导入一个包
                    # 就把本地配音设置顶掉。声音绑定另行处理（已在上面按映射重指/清理）。
                    _local = dict(cfg.get("voice") or {})
                    _incoming = dict(_cfg["voice"]) if isinstance(_cfg["voice"], dict) else {}
                    _merged = dict(_incoming)
                    for _key in ("backend", "backend_params", "backend_keys"):
                        if _local.get(_key) and not _incoming.get(_key):
                            _merged[_key] = _local[_key]
                    if _local.get("backend") and _incoming.get("backend") \
                            and _local["backend"] != _incoming["backend"]:
                        warnings.append("包里的配音后端与本机不同，仍用本机的（%s）"
                                        % _local["backend"])
                        _merged["backend"] = _local["backend"]
                        _merged["backend_params"] = _local.get("backend_params") or {}
                    cfg["voice"] = _merged
                    continue
                cfg[k] = _cfg[k]
            # S1 修复：回填本地密钥（包内本来就不带密钥；只补回用户自己没有的后端）
            if _local_keys:
                _v = cfg.setdefault("voice", {})
                _bk = dict(_v.get("backend_keys") or {})
                for _bid, _val in _local_keys.items():
                    if _val and not _bk.get(_bid):
                        _bk[_bid] = _val
                _v["backend_keys"] = _bk
            try:
                _ver = int(manifest.get("version") or BUNDLE_VERSION)
            except (TypeError, ValueError):
                _ver = BUNDLE_VERSION
            if _ver > BUNDLE_VERSION:
                warnings.append("包版本高于当前支持，部分内容可能未生效")
            # v2.1：随包声音素材先解到临时目录（文件读取不受 with 块限制）
            _va = manifest.get("voice_assets")
            if isinstance(_va, list) and _va and voice_apply is not None:
                extract_dir = tempfile.mkdtemp(prefix="dfypet_voice_")
                for a in _va:
                    if not isinstance(a, dict):
                        continue
                    arc = str(a.get("file") or "")
                    if not arc or not arc.startswith("voice_ref/"):
                        continue
                    try:
                        data = zf.read(arc)
                    except KeyError:
                        warnings.append("包内声音素材缺失：%s" % (a.get("name") or a.get("id")))
                        continue
                    with open(os.path.join(extract_dir, os.path.basename(arc)), "wb") as f:
                        f.write(data)
            # 角色最后入库：id 冲突换新（不覆盖现有角色）；写索引失败必须回滚
            if role_lib.get(str(role.get("id") or "")) is not None:
                role["id"] = uuid.uuid4().hex[:8]
            role_map[_old_rid] = role["id"]
            role["added"] = ""
            role_lib._data.setdefault("roles", []).append(role)
            role_appended = True
            _serr = role_lib._save()
            if _serr:
                role_lib._data["roles"] = [x for x in role_lib._data.get("roles", [])
                                           if x is not role]
                role_appended = False
                for p in written:
                    try:
                        if os.path.isfile(p):
                            os.remove(p)
                    except Exception:
                        pass  # 有意忽略：回滚清理尽力而为
                return None, "保存角色失败：%s" % _serr
            # v2.1：先落声音素材（拿到「旧槽位→新槽位」映射），再落台词/对白
            # （台词的声音引用与角色绑定都要按映射改写）；最后才应用闹钟。
            _voice_map = {}
            _va2 = manifest.get("voice_assets")
            if _va2 is not None:
                if not isinstance(_va2, list):
                    warnings.append("包内声音素材格式非法，已跳过")
                elif voice_apply is not None:
                    try:
                        _voice_map = voice_apply(list(_va2), extract_dir) or {}
                    except Exception as e:
                        warnings.append("声音素材应用失败，已跳过：%s" % e)
                else:
                    warnings.append("包内含声音素材，当前版本尚未支持，已忽略")
            # 绑定重映射：包内绑定引用的角色/声音槽位都是旧 id
            _vb = (cfg.get("voice") or {}).get("bindings")
            if isinstance(_vb, dict) and (role_map or _voice_map):
                _new_b = {}
                for _rs, _vs in _vb.items():
                    _nr = role_map.get(str(_rs), str(_rs))
                    _nv = _voice_map.get(str(_vs), str(_vs))
                    if _nv:
                        _new_b[_nr] = _nv
                cfg.setdefault("voice", {})["bindings"] = _new_b
            _lines_in = manifest.get("lines")
            if _lines_in is not None:
                if not isinstance(_lines_in, list):
                    warnings.append("包内台词格式非法，已跳过")
                elif lines_apply is not None:
                    try:
                        warnings.extend(lines_apply(
                            list(_lines_in), manifest.get("dialogues"),
                            {"voice": _voice_map, "role": role_map}) or [])
                    except Exception as e:
                        warnings.append("台词应用失败，已跳过：%s" % e)
                else:
                    warnings.append("包内含台词，当前版本尚未支持，已忽略")
            # 闹钟设置最后应用：角色入库成功才落地（导入事务性）；
            # 应用回调异常转警告，不撤销已成功的角色导入
            _alarms = manifest.get("alarms")
            if _alarms is not None:
                if not isinstance(_alarms, list):
                    warnings.append("包内闹钟设置格式非法，已跳过")
                elif alarms_apply is not None:
                    try:
                        warnings.extend(alarms_apply(list(_alarms)))
                    except Exception as e:
                        warnings.append("闹钟设置应用失败，已跳过：%s" % e)
                else:
                    warnings.append("包内含闹钟设置，当前版本尚未支持，已忽略")
            return {"role_id": role["id"], "behavior_map": behavior_map,
                    "voice_map": _voice_map, "warnings": warnings}, ""
    except Exception as e:
        # 非事务回滚：清理本次已入索引的角色条目与已解包文件（尽力而为）
        if role_appended:
            try:
                role_lib._data["roles"].remove(role)
                role_lib._save()
            except Exception:
                pass  # 有意忽略：回滚保存尽力而为
        for p in written:
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except Exception:
                pass  # 有意忽略：回滚清理尽力而为
        return None, "导入失败：%s" % e
    finally:
        if extract_dir:
            shutil.rmtree(extract_dir, ignore_errors=True)  # 随包参考音临时目录用完即删


if __name__ == "__main__":
    # 命令行冒烟：无 GUI 自检（python pet_export.py）
    import tempfile
    _d = tempfile.mkdtemp(prefix="exp_")
    _role = {"id": "r1", "name": "x", "file": "a.png", "form": "single",
             "frames": ["a.png"], "added": ""}
    _m, _e = build_manifest(_role, [], {"api_key": "SECRET", "voice": {"enabled": False},
                                       "bubble_style": {}})
    assert _m is not None and not _e
    # 与 pytest 同口径：敏感值不进包、敏感键不进 config；excluded 记录键名（有意设计）
    assert "SECRET" not in json.dumps(_m)
    assert "api_key" not in _m["config"]
    assert _m["excluded"] == ["api_key"]
    assert "voice" in _m["config"] and "bubble_style" in _m["config"]
    print("SMOKE OK")
