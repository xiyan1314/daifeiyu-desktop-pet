# -*- coding: utf-8 -*-
"""PetHub 插件宿主（v2.5.1 · Phase 1）：数据插件的安装 / 卸载 / 启用禁用 / 只读清单。

与 Phase 0 的分工（各管一段，别把校验抄第二份）
----------------------------------------------
· pet_plugin（Phase 0）：只**看懂**一个包——12 条判据、不落盘、不碰 UI；
· 本模块（Phase 1）：**落地**——调上面那个校验器 → 解包到 <数据目录>/plugins/<id>/
  → 把插件内容并进宿主库 → 写安装登记 plugins/_installed.json。
· 对话框（pet_dialogs 的插件管理）只读地调本模块；安装/卸载/启用禁用都在主线程做。

Qt-free：不 import Qt、不 import 桌宠.py（反向 import 会成环）。宿主库通过构造注入，
或第三个参数传宿主窗口后用属性名惰性取——所以本模块可无 GUI 单测。

三条事务性硬口径（每条都有能真失败的对应用例）
----------------------------------------------
1. **校验不通过一个字节都不落盘**：先校验、后建目录；失败返回具体原因。
2. **失败不留残余**：解包在 plugins/ 下的同盘临时目录（.tmp-xxxx）里做，成功才
   os.replace 进 plugins/<id>/；任何一步失败都删临时目录，plugins/ 下不留任何文件
   （连空的 plugins/ 都不新建）、也**不留半截 plugins/<id>/**；已经并进宿主库的内容
   要么随后被登记成"已装"，要么逐条回滚（登记写不进去 = 这次安装没成立）。
3. **卸载不删用户数据**：插件带进角色库 / 台词库 / 音效库…的内容是用户数据（与
   「导入角色包」同口径），卸载只删 plugins/<id>/；确认框文案里必须写明（见 pet_dialogs）。

**插件不许改用户已有的东西**（C 的产品口径，与本条一致）：落地只**新增**条目，
不碰用户现有的音效组槽位 / 待机行为列表 / 配置；role 包里的"可分享配置"只喂给
import_bundle 的一份**深拷贝**，不写回宿主配置。

**保留名**（v2.5.1 兼容审查 P1-1）：plugins/ 下的 packs / index.json / README.md /
_installed.json / _download 是出货布局里的官方内容仓库与宿主自己的目录，安装与卸载都
**明确拒绝**把它们当插件 id 用（目录整体替换会把官方内容包目录 rmtree 掉）；读取侧
（pet_plugin.read_installed）同样静默跳过。清单只有一份：pet_plugin.RESERVED_PLUGIN_NAMES。
第二道保险：目标目录存在却**既没有 manifest.json、又不在登记表里** → 拒绝覆盖（那不是
我们装的插件，多半是用户的文件）。

重复安装同一个 id = **覆盖更新**：目录整体替换、登记表仍只有一条、enabled 沿用旧值。
**v2.6.0（Phase 2）起，更新会把新版新增的内容真正并进宿主库**：每个已落地条目都按
**内容指纹**记账（landed_fingerprints），更新时"只落新的、不重复落旧的"——同一个包再装
一次不会多出一份角色/台词，而新版里新增的条目会真的进库（旧口径是整包跳过）。
**"已装"以安装登记为准**（P2-4 / S1-c）：登记里没有这条、或这条的 landed / 指纹都是空的
（内容从来没落地过，例如手工拷进来的目录），就按**新装**处理——照常落地内容，绝不
报一句"内容已落地"了事。同 id 换 data_kind 是另一个插件 → 明确拒绝（P2-3），不把两套
内容装串。
**v2.5.1 时代的旧登记没有指纹**（只有 landed）：更新时用**上一版目录**里的 payload 补一次账
（_legacy_ledger），照样不会重复落地；补不出来才退回"这一版不合并新内容"的老口径，并在
结果文案里说明。

landed 里存的是**各宿主库自己的 id**（prompt 类是文件名）——回滚（_unland / rollback）与
更新都要靠它；landed_fingerprints 是**内容**的账（按 key 与 landed 平行）；warnings 是包内
**没有落地**的内容（台词/参考音/闹钟…），必须出现在给用户看的成功文案里（P2-1），
不许只躺在 _installed.json 里。

**更新 / 回滚的目录账**（v2.6.0 Phase 2）
----------------------------------------
· 更新前把当前插件目录整棵挪到 `plugins/.prev-<id>/`（同盘 os.replace，原子），再把新目录
  换上去——所以"上一个版本的 payload"是**真的留着**的，不是靠记忆重放；登记里同时留一份
  上一版记录（history，深度 1），里面有它自己的 landed / 指纹；
· `rollback(pid)` = 撤销**这一版新落地**的条目（当前 landed 减去上一版 landed，用户自己的
  内容一件都不动）+ 把 .prev-<id> 换回 <id>/ + 登记回到上一版那条。回滚后**再更新一次**
  仍然正确：指纹账随记录一起退回上一版，新版内容会被重新落地。
· .prev-* 以 "." 开头 → 读取侧（pet_plugin._SKIP_PREFIX）当它不存在；卸载会一起删掉。

安装登记 plugins/_installed.json 的形状（**写入方与读取方共用的契约**；读取方是
pet_plugin.read_installed，它按 <id> 查这张表）::

    {"format": "dfypet-plugins-installed", "version": 1,
     "plugins": {"<id>": {"id", "name", "version", "kind", "data_kind", "code",
                          "source_url", "zip_sha256", "installed_at",
                          "validated": {...}, "enabled": bool, "landed": {...}}}}

落地口径（payload 里放什么就并进哪个库；payload 根由 manifest 的 payload_root 指定）
------------------------------------------------------------------------------------
· role      ← payload/ 本身就是标准 **.dfypet.zip 角色包**（payload/manifest.json +
              payload/roles/*.png）→ 打成临时角色包交给既有的 pet_export.import_bundle；
              也认简化写法 payload/role.json（角色 dict，素材相对 payload 根）→ 走
              pet_export.land_role + 素材换新名复制。
· lines     ← payload/lines.json：{"lines": [{key, text, category, role_slot, voice_slot}]}，
              可选 "dialogues": [{name, lines: [key…]}]（key → 新台词 id 映射后编排）。
· audio     ← payload 下任意层级的 .wav / .mp3 → AudioLibrary.import_file 逐个入库。
· voice_ref ← 同上，进 VoiceAssetLibrary（参考音）。
· behaviors ← payload/behaviors.json（单条 / 数组 / {"behaviors": [...]}）或 payload 下
              其余行为 JSON → 逐条交给 BehaviorService.import_file（它自己校验 8 位 hex id）。
· prompt    ← payload 下任意层级的 .txt → <数据目录>/prompts/custom/<文件名>.txt
              （**同名一律拒绝，绝不覆盖用户已有的人设**）。
（audio / voice_ref 的可选 payload/<kind>/pack.json 只用于"建议显示名"，
              槽位建议一律不采纳——选择权留给用户。）

任何一种 kind 在 payload 里找不到对应文件 → **明确拒绝并给可读原因**，不静默装一个空插件。
"""
from typing import Any, Callable, Iterable

import copy
import hashlib
import json
import os
import shutil
import tempfile
import time
import uuid
import zipfile

import pet_export   # 角色落地管线（import_bundle / land_role / _role_file_refs 单一产地）
import pet_io       # 全仓共用：原子写 + 安全读
import pet_lines    # 台词类别常量（DEFAULT_CATEGORY）
import pet_plugin   # Phase 0 校验器 / 已装清单（本模块调它，绝不重复实现校验）

PLUGINS_DIRNAME = "plugins"
INSTALLED_RECORD = "_installed.json"
INSTALLED_FORMAT = "dfypet-plugins-installed"
INSTALLED_VERSION = 1

MANIFEST_NAME = "manifest.json"
ROLE_PAYLOAD = "role.json"
LINES_PAYLOAD = "lines.json"
BEHAVIORS_PAYLOAD = "behaviors.json"
DEFAULT_PAYLOAD_ROOT = "payload/"

# v2.6.0（Phase 2）：内容指纹账（更新时"只落新的、不重复落旧的"）与上一版目录（回滚要用）。
# 指纹键与 landed 键**平行**（roles / lines / dialogues / audio / voice_ref / behaviors / prompts）。
FINGERPRINT_KEY = "landed_fingerprints"
PREVIOUS_PREFIX = ".prev-"

# 保留名（与读取侧**同一份**，见 pet_plugin.RESERVED_PLUGIN_NAMES）：packs / index.json /
# README.md / _installed.json / _download —— 它们在 plugins/ 下有别的用途，绝不是插件 id。
RESERVED_NAMES = pet_plugin.RESERVED_PLUGIN_NAMES
# 解包用的同盘临时目录（P3-2）：与 target 同盘才能用 os.replace 原子提交；名字以 "."
# 开头 → 读取侧（_SKIP_PREFIX）不会把它当插件目录。前缀**内联在 mkdtemp 调用处**：
# 临时名必须带随机性（tests/test_io_v231.py 的 L6 审计只放行 %s/%d 格式化或 mkdtemp
# 自己的随机后缀，"模块级常量 + 固定名" 会被抓）。

# 落地类别（= Phase 0 的 DATA_KINDS，逐类都有落地管线；多一类少一类由用例钉住）
LANDING_KINDS = ("role", "lines", "audio", "voice_ref", "behaviors", "prompt")
MEDIA_EXTS = (".wav", ".mp3")

# 与 桌宠.py 的 PROMPTS_DIRNAME / persona_file_ids 同一口径（本模块不能 import 桌宠.py，
# 只能镜像这两个常量；tests/test_plugin_host_v251.py 有一条用例钉住两处一致）
PROMPTS_DIRNAME = "prompts"
PROMPTS_CUSTOM_DIRNAME = "custom"

ID_MAX_CHARS = 64
ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")

Log = Callable[[str], Any]


# ---------------- 纯函数助手 ----------------
def _safe_id(raw: Any) -> str:
    """插件 id → 目录名；不合法（空 / 过长 / 字符集外 / 首字符非字母数字 / **保留名**）返回 ""。

    与 pet_plugin 的 id 判据同一口径（校验器已经拒过一次，这里是"写入方自保"的第二道：
    目录名是拼接出来的，不校验就等于把 zip 里的字符串当路径用）。

    v2.5.1（找茬审查 S3② 两条都补上）：
    · **不做 strip 归一**——" x" 与 "x" 是两个不同的字符串，静默归一等于把 zip 里的
      字符串改写成另一个目录名（校验器也不会放行带空白的 id）；
    · **保留名一律 ""**（packs / index.json / README.md …）：它们是官方内容仓库的名字，
      谁都不许拿它当插件目录。调用方先用 _reserved_problem 拿**具体**的拒绝原因，
      这里只是最后一道"任何路径都不许拼出来"的兜底。
    """
    pid = str(raw or "")
    if not pid or pid != pid.strip() or len(pid) > ID_MAX_CHARS:
        return ""
    if any(c not in ID_CHARS for c in pid):
        return ""
    if not pid[0].isalnum() or pid.endswith(".") or ".." in pid or pid.startswith("_"):
        return ""
    if pet_plugin.is_reserved_plugin_name(pid):
        return ""
    return pid


def _norm_dir(path: Any) -> str:
    """目录路径 → 比较用的规范形（绝对路径 + normcase：Windows/macOS 上大小写不敏感）。"""
    text = str(path or "")
    if not text:
        return ""
    try:
        return os.path.normcase(os.path.abspath(text))
    except Exception:
        return os.path.normcase(text)   # 有意忽略：拿不到绝对路径就按原样比


def _reserved_problem(raw: Any):
    """插件 id 撞上保留名 → 给用户看的拒绝原因；不是保留名 → ""。

    单独一条函数（而不是塞进 _safe_id 的一个 ""）是为了让拒绝**说得清**：告诉用户
    "packs 在 plugins/ 下有别的用途"，而不是笼统的"id 不合法"。
    """
    name = str(raw or "").strip()
    if name and pet_plugin.is_reserved_plugin_name(name):
        return ("插件 id「%s」是宿主保留名（plugins/ 下的官方内容仓库与登记文件：%s）——"
                "拿它当插件 id 会整棵替换掉那个目录，已拒绝；插件目录与官方内容一个字节"
                "都没动。" % (name, " / ".join(sorted(RESERVED_NAMES))))
    return ""


def _payload_root(manifest: dict) -> str:
    """manifest 的 payload 单根（校验器已保证以 / 结尾；这里兜一层缺省）。"""
    root = str(manifest.get("payload_root") or DEFAULT_PAYLOAD_ROOT)
    if not root.endswith("/"):
        root += "/"
    return root


def _posix_path(raw: Any) -> str:
    """插件内的相对路径统一成 posix 分隔（zip 条目名本来就是 /；Windows 上把 os.sep 也认了）。"""
    return str(raw or "").strip().replace(os.sep, "/")


def _resolve_inside(base_dir: str, rel: str) -> str:
    """把插件内的相对引用解析成 base_dir 里的绝对路径；越界/绝对路径返回 ""。"""
    rel = _posix_path(rel)
    if not rel or rel.startswith("/") or ".." in rel.split("/"):
        return ""
    target = os.path.abspath(os.path.join(base_dir, *[x for x in rel.split("/") if x]))
    base = os.path.abspath(base_dir)
    if target != base and not target.startswith(base + os.sep):
        return ""
    return target


def _iter_files(base_dir: str, exts: Iterable) -> list:
    """base_dir 下（含子目录）扩展名命中的文件 → 相对路径列表（posix 分隔，排序稳定）。"""
    wanted = tuple(str(e).lower() for e in exts)
    out = []
    for root, _dirs, names in os.walk(base_dir):
        for name in names:
            if os.path.splitext(name)[1].lower() not in wanted:
                continue
            full = os.path.join(root, name)
            out.append(os.path.relpath(full, base_dir).replace(os.sep, "/"))
    return sorted(out)


def _read_json_file(path: str, expect: Any = dict) -> tuple:
    """读一个 JSON 文件 → (对象 | None, 原因)；不存在/坏 JSON 都给可读原因，绝不抛。"""
    if not os.path.isfile(path):
        return None, "文件不存在"
    data, corrupted = pet_io.read_json_or(path, dict, expect=expect, log=None)
    if corrupted:
        return None, "JSON 解析失败或顶层结构非法"
    return data, ""


def _pack_names(payload_dir: str) -> dict:
    """payload 里可选的建议显示名（<kind>/pack.json / pack.json）→ {相对路径: 名字}。

    只认两种写法：{"files": {"a.wav": "金币音"}} 与 {"files": [{"file","name"}]}；
    坏结构一律当"没有建议名"（不影响落地，用文件名兜底）。槽位建议**有意不采纳**。
    """
    out = {}
    for rel in ("pack.json", "audio/pack.json", "voice_ref/pack.json"):
        data, _err = _read_json_file(os.path.join(payload_dir, *rel.split("/")), dict)
        files = data.get("files") if isinstance(data, dict) else None
        if isinstance(files, dict):
            for key, value in files.items():
                if isinstance(value, str) and value.strip():
                    out[_posix_path(key)] = value.strip()
        elif isinstance(files, list):
            for item in files:
                if isinstance(item, dict) and item.get("file"):
                    out[_posix_path(item["file"])] = str(item.get("name") or "").strip()
    return {k: v for k, v in out.items() if v}


def _lines_items(data: Any) -> tuple:
    """lines payload → ([{text,category,role_slot,voice_slot,keys}], [对白 dict])。

    台词：字符串 / {"text","category","role_slot","voice_slot","key"}；
    对白：{"name","lines"|"line_ids"|"keys": [key…]}（key 指向台词条目的 key）。
    """
    if isinstance(data, dict):
        raw_lines = data.get("lines")
        raw_dialogues = data.get("dialogues")
    else:
        raw_lines, raw_dialogues = data, None
    items = []
    if isinstance(raw_lines, list):
        for item in raw_lines:
            if isinstance(item, str):
                text, cat, slot, voice, key = item, pet_lines.DEFAULT_CATEGORY, None, None, ""
            elif isinstance(item, dict):
                text = str(item.get("text") or "")
                cat = str(item.get("category") or pet_lines.DEFAULT_CATEGORY)
                slot = item.get("role_slot")
                voice = item.get("voice_slot")
                key = str(item.get("key") or "")
            else:
                continue
            text = text.strip()
            if not text:
                continue
            keys = [k for k in (key, text) if k]
            items.append({"text": text, "category": cat,
                          "role_slot": str(slot) if slot else None,
                          "voice_slot": str(voice) if voice else None, "keys": keys})
    dialogues = []
    if isinstance(raw_dialogues, list):
        for item in raw_dialogues:
            if not isinstance(item, dict):
                continue
            refs = item.get("lines")
            if refs is None:
                refs = item.get("line_ids")
            if refs is None:
                refs = item.get("keys")
            if not isinstance(refs, list) or not refs:
                continue
            dialogues.append({"name": str(item.get("name") or "未命名对白"),
                              "refs": [str(x) for x in refs]})
    return items, dialogues


def _behavior_records(payload_dir: str) -> list:
    """behaviors payload → [(来源说明, 行为 dict)]。

    优先 payload/behaviors.json（单条 / 数组 / {"behaviors": [...]}）；否则扫其余 JSON，
    认出"有 name 与 steps 的对象"（以及 {"behavior": {...}} 包装）——这样包里的文件名
    怎么起都行（C 的打包工具用的是逐文件导出格式，两者都认）。
    """
    out = []
    main = os.path.join(payload_dir, BEHAVIORS_PAYLOAD)
    if os.path.isfile(main):
        data, _err = _read_json_file(main, None)
        if isinstance(data, dict) and "behavior" in data:
            data = data["behavior"]
        if isinstance(data, dict) and "behaviors" in data:
            data = data.get("behaviors")
        if isinstance(data, dict):
            out.append((BEHAVIORS_PAYLOAD, data))
        elif isinstance(data, list):
            for i, item in enumerate(data):
                if isinstance(item, dict):
                    out.append(("%s[%d]" % (BEHAVIORS_PAYLOAD, i), item))
        return out
    for rel in _iter_files(payload_dir, (".json",)):
        if os.path.basename(rel) == BEHAVIORS_PAYLOAD:
            continue
        data, _err = _read_json_file(os.path.join(payload_dir, *rel.split("/")), None)
        if isinstance(data, dict) and isinstance(data.get("behavior"), dict):
            data = data["behavior"]
        if isinstance(data, dict) and isinstance(data.get("behaviors"), list):
            data = data["behaviors"]
        if isinstance(data, dict) and "name" in data and "steps" in data:
            out.append((rel, data))
        elif isinstance(data, list):
            for i, item in enumerate(data):
                if isinstance(item, dict) and "name" in item and "steps" in item:
                    out.append(("%s[%d]" % (rel, i), item))
    return out


def _sha256_file(path: str) -> str:
    """文件 sha256（hex）；读不出来返回 ""（调用方按"没算出来"处理）。"""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    except Exception:
        return ""
    return h.hexdigest()


def _remove_files(paths: Any, log: Log | None = None, drop_empty_parents: bool = False) -> None:
    """尽力删除一批文件（回滚用）；单个失败只记一行日志，不打断回滚。

    drop_empty_parents：删完顺手把**空**的父目录也撤掉（失败路径"零残留"——
    落素材到一半失败时 roles/ 可能只剩一个空壳，那是本次刚建出来的）。
    """
    parents = []
    for p in list(paths or []):
        try:
            if p and os.path.isfile(p):
                os.remove(p)
                parents.append(os.path.dirname(str(p)))
        except Exception as e:
            if log is not None:
                try:
                    log("插件落地回滚：删除 %s 失败：%r" % (p, e))
                except Exception:
                    pass  # 有意忽略：日志自身失败无处可记
    if drop_empty_parents:
        for d in parents:
            _drop_empty_dir(d)


def _drop_empty_dir(path: str) -> None:
    """尽力删掉一个**空**目录（失败路径"零残留"用）；非空 / 删不掉都原样留着。

    刚落地的素材被回滚删掉后，roles/ / audio/ / voice_ref/ / prompts/custom/ 可能只剩一个
    空壳——那是本次安装刚建出来的，留着就是"残余"。
    """
    try:
        if path and os.path.isdir(path) and not os.listdir(path):
            os.rmdir(path)
    except OSError:
        pass    # 有意忽略：删不掉一个空目录不影响任何事（别人刚往里写了东西就留着）


def _extract_zip(zip_path: str, dest_dir: str, payload_root: str) -> None:
    """把包解到 dest_dir（manifest.json + payload 单根，逐条再验一次路径安全）。

    校验器已经验过一遍；这里是"写入方自保"的第二道——解包是唯一往磁盘写任意名字的
    动作，zip-slip 的代价太大，重复判一次很便宜。越界条目直接抛 ValueError。
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            name = info.filename
            if info.is_dir():
                continue
            if name != MANIFEST_NAME and not name.startswith(payload_root):
                raise ValueError("条目不在 payload 单根内：%s" % name)
            target = os.path.abspath(os.path.join(dest_dir, *name.split("/")))
            base = os.path.abspath(dest_dir)
            if not target.startswith(base + os.sep):
                raise ValueError("条目解包后越界：%s" % name)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info, "r") as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)


_LANDED_LABELS = (("roles", "个角色"), ("lines", "条台词"), ("dialogues", "组对白"),
                  ("audio", "个音效"), ("voice_ref", "个参考音"), ("behaviors", "个行为"),
                  ("prompts", "个人设"))


def _landed_text(landed: Any) -> str:
    """落地结果 → 一句人话（给用户看的安装结果里带上"装进来了什么"）。"""
    if not isinstance(landed, dict):
        return ""
    parts = []
    for key, unit in _LANDED_LABELS:
        count = len(landed.get(key) or []) if isinstance(landed.get(key), list) else 0
        if count:
            parts.append("%d %s" % (count, unit))
    return "、".join(parts)


def _has_landed(landed: Any, fingerprints: Any = None) -> bool:
    """登记里的 landed（或 v2.6.0 的内容指纹账）是否**真的记下了落地内容**（P2-4 / S1-c）。

    空表（或只有 warnings）说明内容从来没并进宿主库——手工拷进来的插件目录、登记被抹掉
    之后补的占位记录都是这种形状。这种"已装"是假的：必须照常落地，也不许对用户说
    "内容已落地"。
    v2.6.0：指纹账也算数——包的每一条内容都与已落地的一致时，landed 可能是空的，
    但那次安装**确实**把内容并进了库（指纹就是证据），不该被当成"没装过"。
    """
    if isinstance(landed, dict):
        if any(isinstance(landed.get(k), list) and landed.get(k)
               for k, _unit in _LANDED_LABELS):
            return True
    if isinstance(fingerprints, dict):
        return any(isinstance(v, list) and v for v in fingerprints.values())
    return False


def _landed_warnings(landed: Any) -> list:
    """落地时**没有落地**的内容提示（包内台词 / 参考音 / 闹钟…）→ 要出现在成功文案里。"""
    if not isinstance(landed, dict):
        return []
    return [str(x).strip() for x in (landed.get("warnings") or []) if str(x).strip()]


def _warn_tail(warnings: Any) -> str:
    """把"没有落地"的提示拼成给用户看的一段（最多列 5 条，其余只给总数）。

    P2-1：这 4 条警告此前只躺在 _installed.json 里，界面永远看不到；现在装完就打在
    结果文案上——"装上了，但有 N 项没进来"必须让人看得见，而不是让人以为全进来了。
    """
    items = [str(x).strip() for x in (warnings or []) if str(x).strip()]
    if not items:
        return ""
    head = "；".join(items[:5])
    more = "；…（共 %d 项）" % len(items) if len(items) > 5 else ""
    return "\n\n⚠ 有 %d 项内容没有导入：%s%s" % (len(items), head, more)


# ---------------- v2.6.0（Phase 2）：内容指纹 / 落地账 / 包内计划 ----------------
# 一条已落地内容 → 一个**内容指纹**（sha256）。更新的语义就靠它："指纹见过的条目不再落，
# 没见过的（= 新版新增 / 改动过的）真并进宿主库"。指纹一律取**内容**（不是包内路径、不是
# 随机 id）：同一个包重装 → 指纹一模一样 → 一条都不重复落。
def _fp_text(text):
    """字符串 → 指纹。"""
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _fp_json(obj):
    """结构化内容 → 指纹（键序无关：sort_keys；中文不转义：与落盘口径一致）。"""
    try:
        text = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        text = repr(obj)        # 有意忽略：拿不到规范形就退化用 repr（同一条内容仍然稳定）
    return _fp_text(text)


def _fp_bytes(data):
    """bytes → 指纹。"""
    return hashlib.sha256(bytes(data or b"")).hexdigest()


def _fp_file(path):
    """文件内容 → 指纹（分块读）；读不出来返回 ""（调用方按"没有指纹"处理＝照常落地）。"""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    except Exception:
        return ""
    return h.hexdigest()


def _fp_named(name, data):
    """带名字的内容指纹（人设类：文件名就是用户看到的预设名，改名＝另一件东西）。"""
    return hashlib.sha256(str(name).encode("utf-8") + b"\x00"
                          + bytes(data or b"")).hexdigest()


def _fp_named_file(name, path):
    """盘上文件按"带名字的内容指纹"算一份；读不出来 → ""（调用方按"不是本插件落的"处理）。

    v2.6.0 第 4 轮（兼容审查 P2-1）：判断"用户改过没有人设文件"要拿**盘上现在这份**的
    指纹跟落账比——"读不出来"必须走最保守的那条（当成用户的东西，不动它），所以返回 ""
    而不是抛。空串永远不会出现在落账里（指纹是 sha256 hex），不会被误判成"是本插件落的"。
    """
    try:
        with open(path, "rb") as f:
            data = f.read()
    except Exception:
        return ""
    return _fp_named(name, data)


def _ledger_sets(raw):
    """指纹账 → 可变的 {key: set(fp)}（键集与 landed 平行）。

    两种形状都认：登记里的是 list（JSON），内部流转的是 set——_land 会把**已经**是 set 的
    账再走一遍本函数（"接口两边都能收"），所以这里必须同时吃 list 与 set。
    """
    out = {}
    if isinstance(raw, dict):
        for key, _unit in _LANDED_LABELS:
            vals = raw.get(key)
            if isinstance(vals, (list, tuple, set, frozenset)):
                out[key] = {str(x) for x in vals if str(x)}
    return out


def _ledger_json(ledger):
    """{key: set(fp)} → 登记里的形状（排序稳定：同一份账写出同样的字节）。"""
    out = {}
    for key, _unit in _LANDED_LABELS:
        vals = sorted({str(x) for x in (ledger or {}).get(key) or set() if str(x)})
        if vals:
            out[key] = vals
    return out


def _ledger_live(ledger):
    """把账变成**调用方也能看见改动**的可变形状（{key: set}）。

    已经是 {key: set} 的原样返回**同一个对象**——install_zip 要靠它在落地之后写回登记；
    JSON 形状（{key: [fp…]}）才转一份新的（那是登记边界，调用方本来就只看返回值）。
    """
    if isinstance(ledger, dict) and all(isinstance(v, set) for v in ledger.values()):
        return ledger
    return _ledger_sets(ledger)


def _fresh(items, key, ledger, still_there=None):
    """计划条目 → **还没落地过**的那些（顺带把所有条目的指纹记进账，幂等）。

    still_there：可选的"这一条真的还在库里吗"判据。用户手动删掉落地内容之后再更新，
    按指纹会被跳过（那是"不重复落旧的"的直接后果）——这几类给了判据就能自动补回来
    （prompt 看文件在不在、lines 看台词文本还在不在）。
    """
    seen = ledger.setdefault(key, set())
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        fp = str(it.get("fp") or "")
        if fp and fp in seen and (still_there is None or still_there(it)):
            continue
        if fp:
            seen.add(fp)
        out.append(it)
    return out


def _landed_count(landed):
    """一次落地**新并进宿主库**的条目数（不含 warnings / skipped）。"""
    if not isinstance(landed, dict):
        return 0
    return sum(len(landed.get(k) or []) for k, _unit in _LANDED_LABELS
               if isinstance(landed.get(k), list))


def _merge_landed(old, new):
    """上一版 landed + 本次新落地的 landed → 累积账（按 key 去重、保持先来后到）。

    "累积"是回滚判据的前提：rollback = 当前 landed − 上一版 landed，所以 landed 必须记
    **这个插件历次落地过的全部 id**，而不是只有最后一次的。
    """
    out = {}
    for key, _unit in _LANDED_LABELS:
        vals = []
        for src in (old, new):
            for x in ((src or {}).get(key) or []) if isinstance(src, dict) else []:
                s = str(x)
                if s and s not in vals:
                    vals.append(s)
        if vals:
            out[key] = vals
    warns = [str(x) for x in ((new or {}).get("warnings") or []) if str(x).strip()]
    if warns:
        out["warnings"] = warns
    out["skipped"] = int((new or {}).get("skipped") or 0)
    return out


def _landed_diff(cur, prev):
    """当前 landed − 上一版 landed：**这一版新落地**的条目（回滚要撤销的就是它）。"""
    out = {}
    for key, _unit in _LANDED_LABELS:
        before = {str(x) for x in ((prev or {}).get(key) or []) if str(x)}
        new = [str(x) for x in ((cur or {}).get(key) or []) if str(x) and str(x) not in before]
        if new:
            out[key] = new
    return out


def _plan_lines(payload_dir):
    """lines payload → (台词计划, 对白计划, 原因)；形状不对 → (None, None, 原因)。"""
    data, rerr = _read_json_file(os.path.join(payload_dir, LINES_PAYLOAD), None)
    if data is None:
        return None, None, "lines 插件缺少 %s：%s" % (LINES_PAYLOAD, rerr)
    items, dialogues = _lines_items(data)
    if not items and not dialogues:
        return None, None, "%s 里没有任何台词（空表或格式不对）" % LINES_PAYLOAD
    texts = {}
    for item in items:
        for key in item["keys"]:            # keys = [声明的 key, 文本本身]：两种引用都认
            texts.setdefault(key, item["text"])
    plan_lines = [{"fp": _fp_json([it["text"], it["category"], it["role_slot"],
                                   it["voice_slot"]]), "item": it} for it in items]
    plan_dialogues = [{"fp": _fp_json([d["name"], [texts.get(r) for r in d["refs"]]]),
                       "dialogue": d, "texts": [texts.get(r) for r in d["refs"]]}
                      for d in dialogues]
    return plan_lines, plan_dialogues, ""


def _plan_media(payload_dir, label):
    """音频类 payload → ([{指纹, 相对路径}], 原因)。"""
    files = _iter_files(payload_dir, MEDIA_EXTS)
    if not files:
        return None, "%s插件里没有任何 .wav / .mp3 文件" % label
    return [{"fp": _fp_file(os.path.join(payload_dir, *rel.split("/"))), "rel": rel}
            for rel in files], ""


def _plan_behaviors(payload_dir):
    """行为类 payload → ([{指纹, 来源, 行为 dict}], 原因)。"""
    records = _behavior_records(payload_dir)
    if not records:
        return None, ("behaviors 插件里没有任何行为（缺 %s，也没有认出 name+steps 的 JSON）"
                      % BEHAVIORS_PAYLOAD)
    return [{"fp": _fp_json(record), "src": src, "record": record}
            for src, record in records], ""


def _plan_prompts(payload_dir):
    """人设类 payload → ([{指纹, 相对路径}], 原因)。指纹带文件名（文件名 = 预设名）。"""
    files = _iter_files(payload_dir, (".txt",))
    if not files:
        return None, "prompt 插件里没有任何 .txt 人设文件"
    out = []
    for rel in files:
        full = os.path.join(payload_dir, *rel.split("/"))
        try:
            with open(full, "rb") as f:
                data = f.read()
        except Exception:
            data = b""             # 有意忽略：读不出来就按"没有指纹"处理（照常落地）
        out.append({"fp": _fp_named(os.path.basename(rel), data), "rel": rel})
    return out, ""


def _role_fingerprint(payload_dir):
    """role payload（标准角色包 / role.json 两种形态）→ (指纹, 形态)；算不出来 → ("", 形态)。

    指纹覆盖**角色内容 + 它引用的素材内容**：只改了一张 png 也算新内容（该重新落地）。
    """
    if os.path.isfile(os.path.join(payload_dir, MANIFEST_NAME)):
        manifest, _err = _read_json_file(os.path.join(payload_dir, MANIFEST_NAME), dict)
        if not isinstance(manifest, dict):
            return "", "bundle"
        parts = [_fp_json(manifest.get("role") or {})]
        for rel in _iter_files(payload_dir, pet_plugin.ALLOWED_EXTS):
            parts.append("%s:%s" % (rel, _fp_file(os.path.join(payload_dir, *rel.split("/")))))
        return _fp_json(parts), "bundle"
    role, _err = _read_json_file(os.path.join(payload_dir, ROLE_PAYLOAD), dict)
    if not isinstance(role, dict):
        return "", "dict"
    parts = [_fp_json(role)]
    for ref in sorted(pet_export._role_file_refs(role) or []):
        srcp = _resolve_inside(payload_dir, ref)
        parts.append("%s:%s" % (ref, _fp_file(srcp) if srcp else ""))
    return _fp_json(parts), "dict"


def _package_fingerprints(data_kind, payload_dir):
    """（尽力而为）一个 payload 里**全部**条目的指纹 → {账本键: [指纹]}。

    只给 _legacy_ledger 用：v2.5.1 的登记没有指纹，用上一版目录里的内容把账补上。
    任何一类读不出来就跳过它（返回能读到的部分），绝不让"补账"变成新的失败路径。
    """
    out = {}
    if data_kind == "lines":
        items, dialogues, err = _plan_lines(payload_dir)
        if not err:
            out["lines"] = [it["fp"] for it in items]
            out["dialogues"] = [it["fp"] for it in dialogues]
        return out
    if data_kind in ("audio", "voice_ref"):
        items, err = _plan_media(payload_dir, "音效")
        if not err:
            out[data_kind] = [it["fp"] for it in items]
        return out
    if data_kind == "behaviors":
        items, err = _plan_behaviors(payload_dir)
        if not err:
            out["behaviors"] = [it["fp"] for it in items]
        return out
    if data_kind == "prompt":
        items, err = _plan_prompts(payload_dir)
        if not err:
            out["prompts"] = [it["fp"] for it in items]
        return out
    if data_kind == "role":
        fp, _mode = _role_fingerprint(payload_dir)
        if fp:
            out["roles"] = [fp]
        return out
    return out


class _NoBehaviors(object):
    """宿主行为库不可用时的替身：import_bundle 只在包内带行为时才调它（返回明确错误）。"""

    def add(self, name: Any, steps: Any) -> tuple:
        return None, "宿主行为库不可用"

    def list(self) -> list:
        return []


# ---------------- 宿主 ----------------
class PluginHost(object):
    """插件宿主：一个数据目录 = 一套已装插件（<数据目录>/plugins/）。

    role_lib / lines_lib / audio_lib / voice_assets / behaviors：宿主库；显式注入优先
    （单测直接给），否则用宿主窗口惰性取（构造期那些库可能还没建好，所以**只在真正落地
    时**取，不在构造期缓存）。log：可选日志回调（Callable[[str], None]，缺省不记）。
    """

    def __init__(self, data_dir: Any, host_version: Any = "", pet: Any = None, *,
                 role_lib: Any = None, lines_lib: Any = None, audio_lib: Any = None,
                 voice_assets: Any = None, behaviors: Any = None,
                 log: Log | None = None) -> None:
        self._data_dir = str(data_dir or "")
        self._host_version = str(host_version or "")
        self._pet = pet
        self._libs = {"role_lib": role_lib, "lines_lib": lines_lib, "audio_lib": audio_lib,
                      "voice_assets": voice_assets, "behaviors": behaviors}
        self._log = log
        # 构造期**不做任何 I/O**（PetWindow 构造路径上会 new 一个，不能建目录/读盘）
        self._plugins_dir = (os.path.join(self._data_dir, PLUGINS_DIRNAME)
                             if self._data_dir else "")

    # ---------- 路径 ----------
    @property
    def plugins_dir(self) -> str:
        """插件根目录（<数据目录>/plugins）。"""
        return self._plugins_dir

    @property
    def host_version(self) -> str:
        """宿主版本字符串（校验器与索引都用它判兼容性；只读）。"""
        return self._host_version

    @property
    def installed_path(self) -> str:
        """安装登记文件路径（<数据目录>/plugins/_installed.json）。"""
        return (os.path.join(self._plugins_dir, INSTALLED_RECORD)
                if self._plugins_dir else "")

    def previous_dir(self, pid: Any) -> str:
        """**上一版**插件目录（<plugins>/.prev-<id>）；没有上一版时它不存在。

        以 "." 开头 → 读取侧（pet_plugin._SKIP_PREFIX）不会把它当插件目录；id 已经过
        _safe_id（不许以 "." 开头），所以插件自己的目录永远撞不到这个前缀。
        """
        safe = _safe_id(pid)
        if not safe or not self._plugins_dir:
            return ""
        return os.path.join(self._plugins_dir, PREVIOUS_PREFIX + safe)

    def _lib(self, name: str) -> Any:
        """宿主库：显式注入优先，其次从宿主窗口惰性取（构造期还没有也不怕）。"""
        explicit = self._libs.get(name)
        if explicit is not None:
            return explicit
        if self._pet is None:
            return None
        try:
            return getattr(self._pet, name, None)
        except Exception:
            return None  # 有意忽略：取不到宿主库就按"不可用"处理（调用方给人话原因）

    # ---------- 安装 ----------
    def install_zip(self, path: Any, source_url: Any = "") -> tuple:
        """安装一个插件包（本地 zip）。返回 (ok, msg)；msg 是给用户看的具体原因。

        source_url：包的来源（Phase 2 的索引下载会填；本地选文件留空）。
        失败路径：**plugins/ 下不留任何残余**——校验先于建目录，解包在系统临时目录里做。
        """
        src = str(path or "")
        if not src or not os.path.isfile(src):
            return False, "插件包不存在：%s" % (src or "(空路径)")
        if not self._plugins_dir:
            return False, "插件数据目录不可用（宿主未接线），装不了"
        manifest, err = pet_plugin.validate_plugin_zip(src, self._host_version)
        if manifest is None:
            return False, "插件校验未通过：%s" % str(err or "原因未知").strip()
        meta = manifest.get("plugin")
        meta = meta if isinstance(meta, dict) else {}
        # P1-1：保留名**先判**（packs / index.json / README.md …）。它们的字符集本身合法，
        # 一旦被当 id 用，下面就按 <plugins>/<id>/ 整棵替换 → 官方内容包目录被删掉。
        reserved = _reserved_problem(meta.get("id"))
        if reserved:
            return False, reserved
        pid = _safe_id(meta.get("id"))
        if not pid:
            return False, "插件包缺少合法的 id（只允许字母数字与 . _ -，最长 %d）" % ID_MAX_CHARS
        kind = str(meta.get("kind") or "")
        if kind != "data":
            return False, "本版本只安装数据插件（kind=data），收到 kind=%r" % (kind or "(缺)")
        data_kind = str(meta.get("data_kind") or "")
        if data_kind not in LANDING_KINDS:
            return False, ("本版本不支持落地「%s」类插件（已接 %s）；已拒绝安装，"
                           "插件目录未做任何改动"
                           % (data_kind or "(缺)", " / ".join(LANDING_KINDS)))
        registry = self._load_registry()
        known = registry["plugins"].get(pid)
        target = os.path.join(self._plugins_dir, pid)
        # P2-3：同一个 id 换 data_kind = 另一个插件。此前只按"目录在不在"判已装，于是报一句
        # "已更新…内容不重复导入"、内容却一条都不落地（登记里的 data_kind 还被悄悄改掉）。
        # 登记里没记类型（手工拷进来的目录 / 旧版本登记）不算冲突：那种记录本来就什么都没说，
        # 按"没装过"处理（S1-c：内容必须真的落地）。
        known_kind = str(known.get("data_kind") or "") if known is not None else ""
        if known is not None and known_kind and known_kind != data_kind:
            return False, ("插件 id「%s」已装为「%s」类，这次的包是「%s」类——同一个 id 换"
                           "类型会把两套内容装串，已拒绝：请先卸载旧插件（或让包的作者换"
                           "一个 id）。" % (pid, known.get("data_kind") or "(未知)", data_kind))
        # P2-4 / S1-c：**安装登记为准**。只有登记里这条 data_kind 相同、且 landed 真的记下
        # 了内容，才算"内容已经落地过"（重复安装才不重复导入）；登记没了 / landed 是空表，
        # 就按新装落地——绝不出现"报已更新、内容一条不进"的空壳。
        already = (known is not None and known_kind == data_kind
                   and _has_landed(known.get("landed"), known.get(FINGERPRINT_KEY)))
        # P1-1 第二道保险：目标存在却不是插件目录（没有 manifest.json）、登记里也没这条 →
        # 那是官方内容仓库（packs/）或用户自己的文件，绝不覆盖。
        if not already and os.path.exists(target) \
                and not os.path.isfile(os.path.join(target, MANIFEST_NAME)):
            return False, ("plugins/%s 已存在，但它不是一个插件目录（没有 %s）、安装登记里"
                           "也没有这条——为免覆盖你的文件，已拒绝安装；请先移走它，或让包"
                           "的作者换一个 id。" % (pid, MANIFEST_NAME))
        made_dir = not os.path.isdir(self._plugins_dir)
        try:
            os.makedirs(self._plugins_dir, exist_ok=True)
        except Exception as e:
            return False, "无法创建插件目录：%s" % e
        # P3-2：解包目录与 target **同盘**（都在 plugins/ 下）→ 提交用 os.replace（同盘
        # rename 原子）。此前解包在 %TEMP%（多在 C:），绿色版在别的盘时 shutil.move 走
        # copytree+rmtree：中途失败留半截 plugins/<id>/，下次装同包被当"已装"→ 内容永远
        # 不落地。临时目录名以 "." 开头 → 读取侧不会把它当插件目录。
        tmp = ""
        try:
            try:
                tmp = tempfile.mkdtemp(prefix=".tmp-", dir=self._plugins_dir)
            except Exception as e:
                return False, "无法创建插件临时目录：%s" % e
            try:
                _extract_zip(src, tmp, _payload_root(manifest))
            except Exception as e:
                return False, "解包失败：%s" % e
            payload_dir = os.path.join(tmp, *_payload_root(manifest).rstrip("/").split("/"))
            if not os.path.isdir(payload_dir):
                return False, ("插件包里没有 payload 目录（payload_root=%r）"
                               % _payload_root(manifest))
            # v2.6.0（Phase 2）：更新 = **按内容指纹去重后合并**——新版新增的条目真的进库，
            # 与已落地内容相同的一条都不重复落（旧口径是整包跳过，新版内容永远进不来）。
            ledger = _ledger_sets((known or {}).get(FINGERPRINT_KEY))
            ledger_note = ""
            if already and not _ledger_json(ledger):
                # v2.5.1 的旧登记只有 landed、没有指纹：用**上一版目录**里的 payload 补一次账
                ledger, ledger_note = self._legacy_ledger(data_kind, target, payload_dir, ledger)
            landed, lerr = self._land(data_kind, payload_dir, ledger)
            if lerr:
                return False, lerr
            # 覆盖更新：先把当前目录整棵挪到 .prev-<id>/（回滚要用**真的上一版 payload**，
            # 不靠记忆重放），再把新目录换上去。两处都是同盘 os.replace（原子）。
            # 例外：**完全同一个版本的重复安装**（版本没变、内容一条不新）不换目录、也不轮换
            # 回滚点——否则用户再点一次「更新」就把上一版的备份顶掉了（_dev/probe_plugin_market_v260.py
            # 实测踩到：v1 → v2 → v2 之后回滚到的是 v2，"能回到 v1"这件事被悄悄弄丢了）。
            added = _landed_count(landed)
            skipped = int(landed.get("skipped") or 0)
            same_version = (str(meta.get("version") if meta.get("version") is not None else "")
                            == str((known or {}).get("version") or ""))
            repeat = bool(already and added == 0 and skipped > 0 and same_version)
            previous = self.previous_dir(pid)
            # v2.7.0（代理 C·小账 b）：**history 与 .prev-<id>/ 必须成对**。
            # v2.6.0 起 history[-1] 是"上一版目录里那份 payload 对应的登记"，轮换
            # （target → .prev-、新包 → target）保证了两者一一对应。但当前版目录**不在**时
            # （用户手工清过 plugins/<id>/、上一次提交半途失败、杀软删过）此前走的是 else
            # 分支：history 被清成 []（回滚点白丢、回滚按钮变灰），而 .prev-<id>/ 原样留在
            # 盘上成了孤儿（没人能回滚它、也没人清它）。新口径：
            #   · 目录不在而 .prev 在 → 那份 payload 正是 history[-1] 记的那一版，配对关系
            #     还成立：**既不轮换也不清**（回滚点保住）；
            #   · 两边都不在 → history 一并清掉（不留指向空气的回滚点）；
            #   · 登记里没有这条却留着 .prev → 孤儿（上次安装半途失败留下的），一并清掉。
            target_is_dir = os.path.isdir(target)
            prev_is_dir = bool(previous) and os.path.isdir(previous)
            moved_prev = False
            keep_history = False
            try:
                if repeat and target_is_dir:
                    # 目录原样留着（它里面就是这一版的内容）；tmp 由 finally 清掉。
                    moved_prev = False
                    keep_history = prev_is_dir   # .prev 不在 → 悬空回滚点一并清掉
                elif already and not target_is_dir:
                    # 当前版目录不在了：没有可轮换的 payload，直接换上新目录。
                    keep_history = prev_is_dir
                    os.replace(tmp, target)
                    tmp = ""                # 已经搬走：finally 不必再删
                else:
                    if already and target_is_dir:
                        if prev_is_dir:
                            shutil.rmtree(previous, ignore_errors=True)
                        os.replace(target, previous)
                        moved_prev = True
                    elif target_is_dir:
                        shutil.rmtree(target)
                    if not already and prev_is_dir:
                        # 登记里没有这条，却留着一份 .prev-<id>/：没有任何记录能跟它配对
                        shutil.rmtree(previous, ignore_errors=True)
                    os.replace(tmp, target)
                    tmp = ""                # 已经搬走：finally 不必再删
            except Exception as e:
                # S1-b：失败不留半截插件目录；**本次**新并进宿主库的那几条也要撤掉（否则库里
                # 永久留一份用户看不见的插件内容，重装还会再来一份）。上一版的目录要挪回去：
                # 这次更新没成立，用户该继续用原来那一版。
                shutil.rmtree(target, ignore_errors=True)
                if moved_prev:
                    try:
                        os.replace(previous, target)
                    except Exception as back:
                        self._log_rollback("上一版目录", back)
                self._unland(data_kind, landed)
                return False, ("安装插件目录失败：%s（已清理半截目录，并回滚本次导入的内容）" % e)
            # 累积账：landed 记**历次**落地过的 id（回滚判据 = 当前 − 上一版），指纹账随内容
            # 一起累积；history 里放上一版那条记录（深度 1）——它是回滚要恢复的登记状态。
            prev_record = dict(known) if isinstance(known, dict) else {}
            prev_record.pop("history", None)
            record = {
                "id": pid,
                "name": str(meta.get("name") or pid),
                "version": str(meta.get("version") if meta.get("version") is not None else ""),
                "kind": kind,
                "data_kind": data_kind,
                "code": bool(meta.get("code")),
                "source_url": str(source_url or ""),
                "zip_sha256": _sha256_file(src),
                "installed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "validated": {"ok": True, "host_version": self._host_version, "err": ""},
                "enabled": bool((known or {}).get("enabled", True)),
                "landed": _merge_landed(known.get("landed") if already else None, landed),
                FINGERPRINT_KEY: _ledger_json(ledger),
                # history 的三种口径（v2.7.0 代理 C·小账 b）：轮换了目录 → 记被换下去的那条；
                # 没轮换但 .prev 还在（当前版目录丢了 / 同版本重复安装）→ 沿用原记录，回滚点
                # 不丢；其余（没有可恢复的 payload）→ 空表，不许留悬空回滚点。
                "history": ([prev_record] if (already and moved_prev and prev_record)
                            else (list(known.get("history") or []) if keep_history else [])),
            }
            registry["plugins"][pid] = record
            werr = self._save_registry(registry)
            if werr:
                # S1-a：登记失败 = 这次安装没成立。目录撤掉（保持"装了就有登记"），**并且**
                # 把刚并进宿主库的条目逐条回滚——否则用户看到"安装失败"，而台词/角色其实
                # 已经永久进了库（插件管理里还看不到它，重装再来一份）。
                shutil.rmtree(target, ignore_errors=True)
                if moved_prev:
                    # v2.7.0（代理 C·小账 b 的连带）：目录轮换也要退回去——这次更新没成立，
                    # 用户该继续用原来那一版（与 S1-b 提交失败分支同口径）。少了这一步会留下
                    # "登记说装着上一版、plugins/<id>/ 却不在、真 payload 躺在 .prev-<id>/"
                    # 的错位状态——正是 b 那条孤儿备份的制造者。
                    try:
                        os.replace(previous, target)
                    except Exception as back:
                        self._log_rollback("上一版目录", back)
                self._unland(data_kind, landed)
                return False, ("写入安装登记失败：%s（已撤掉插件目录，并回滚本次导入的内容）"
                               % werr)
            warns = _warn_tail(_landed_warnings(landed))
            state = "" if record["enabled"] else "（沿用上一次的「已禁用」状态）"
            if already:
                # v2.6.0：更新会**真的合并**新版新增内容，所以文案必须说清这次进了多少项、
                # 有多少项与上一版一致（没重复导入）——不许再让用户猜"新内容进来了没有"。
                if added:
                    head = ("已更新插件「%s」%s：覆盖旧版本，并把新版新增的 %d 项内容并入"
                            "（另有 %d 项与已落地的一致，未重复导入）。"
                            % (record["name"], state, added, skipped))
                else:
                    head = ("已更新插件「%s」%s：覆盖旧版本；这一版的内容与已落地的完全一致"
                            "（没有新增内容）。" % (record["name"], state))
                return True, head + ledger_note + warns
            what = _landed_text(landed)
            tail = "可在插件管理里卸载（已导入的内容会保留）。"
            head = ("已安装插件「%s」%s，并导入 %s。" % (record["name"], state, what)
                    if what else "已安装插件「%s」%s。" % (record["name"], state))
            return True, head + tail + warns
        finally:
            if tmp and os.path.isdir(tmp):
                shutil.rmtree(tmp, ignore_errors=True)
            self._drop_empty_plugins_dir(made_dir)

    # ---------- 卸载 / 启用禁用 / 清单 ----------
    def uninstall(self, pid: Any) -> tuple:
        """卸载插件：删 plugins/<id>/ 与登记项。返回 (ok, msg)。

        **已落地到宿主库的资产不删**：角色/台词/音效已经在各自的库里，属用户数据
        （与「导入角色包」同口径）——msg 里点明，确认框也照这个口径写。
        **保留名一律拒绝**（P1-1）：干净布局上 uninstall("packs") 此前返回 ok=True 并
        rmtree 掉官方内容包目录，连备份都没有。
        """
        reserved = _reserved_problem(pid)
        if reserved:
            return False, reserved
        safe = _safe_id(pid)
        if not safe:
            return False, "插件 id 不合法：%r" % (pid,)
        target = os.path.join(self._plugins_dir, safe)
        registry = self._load_registry()
        if not os.path.isdir(target) and safe not in registry["plugins"]:
            return False, "插件未安装：%s" % safe
        try:
            if os.path.isdir(target):
                shutil.rmtree(target)
            # 上一版的备份也一起删：卸载就是"这个插件不在了"，留一份 .prev-* 是残余
            previous = self.previous_dir(safe)
            if previous and os.path.isdir(previous):
                shutil.rmtree(previous, ignore_errors=True)
        except Exception as e:
            return False, "删除插件目录失败：%s" % e
        registry["plugins"].pop(safe, None)
        werr = self._save_registry(registry)
        if werr:
            return False, "插件目录已删，但安装登记写入失败：%s" % werr
        return True, ("已卸载插件「%s」；它导入到角色库 / 台词库 / 音效库的内容**保留**"
                      "（属用户数据，不随插件删除）" % safe)

    # ---------- 回滚（v2.6.0 Phase 2） ----------
    def rollback(self, pid: Any) -> tuple:
        """回滚到**上一版**：恢复上一版目录 + 撤销这一版新落地的条目 + 登记回到上一版。

        三件事一起做，缺一件都不算回滚：
        ① 撤销"当前 landed − 上一版 landed"里的条目——**只撤这一版新落的**，用户自己的
           角色 / 台词 / 音效一件都不动（它们不在这个差集里）；
        ② 把 plugins/.prev-<id>/ 换回 plugins/<id>/（上一版 payload 是真留着的那一份）；
        ③ 登记整条换成上一版那条（连同它的 landed 与内容指纹账）——于是"回滚后再更新一次"
           会把新版内容重新并进来，不会因为指纹还留着而一条都不落。
        没有上一版（只装过一次 / 目录被手工删了）→ 明确拒绝并说明原因，绝不假装回滚成功。
        """
        reserved = _reserved_problem(pid)
        if reserved:
            return False, reserved
        safe = _safe_id(pid)
        if not safe or not self._plugins_dir:
            return False, "插件 id 不合法：%r" % (pid,)
        registry = self._load_registry()
        record = registry["plugins"].get(safe)
        if not isinstance(record, dict):
            return False, ("插件「%s」没有安装登记（可能从来没装过），回滚不了" % safe)
        history = record.get("history")
        prev = history[-1] if isinstance(history, list) and history else None
        if not isinstance(prev, dict) or not prev:
            return False, ("插件「%s」没有上一版可回滚（只装过一次，或者上一版记录已经用掉）"
                           % safe)
        previous = self.previous_dir(safe)
        if not previous or not os.path.isdir(previous):
            return False, ("插件「%s」的上一版目录已经不在了（%s）——没有可恢复的 payload，"
                           "这次回滚没有做任何改动" % (safe, previous or "(无)"))
        new_only = _landed_diff(record.get("landed"), prev.get("landed"))
        count = sum(len(v) for v in new_only.values())
        target = os.path.join(self._plugins_dir, safe)
        try:
            shutil.rmtree(target, ignore_errors=True)
            os.replace(previous, target)
        except Exception as e:
            # 目录没换成 = 这次回滚没成立：**先别撤内容**（撤了就两边都不对了），如实报错
            return False, ("恢复上一版插件目录失败：%s——这次回滚没有生效，当前这一版仍在用"
                           % e)
        self._unland(str(record.get("data_kind") or ""), new_only)
        restored = dict(prev)
        restored["history"] = []      # 上一版记录自己的 history 不继承；键保持存在（形状稳定）
        registry["plugins"][safe] = restored
        werr = self._save_registry(registry)
        if werr:
            undone = ("已撤销本版新导入的 %d 项内容" % count if count
                      else "本版没有新导入的内容需要撤销")
            return False, ("已恢复上一版目录，但安装登记写入失败：%s（%s，"
                           "请重开插件管理看看当前状态）" % (werr, undone))
        # v2.7.0（代理 C·小账 c）：文案必须与行为对齐。同内容折叠（这一版的内容与上一版
        # 完全一致、按指纹一条都没重复落）时差集是空的，此前文案照念"撤销了本版新导入的
        # 0 项内容"——用户读到一句自相矛盾的"撤销了 0 项"，分不清是回滚没生效还是本来就没
        # 内容。0 项时改说"没有新导入的内容"，不再提"撤销"。
        done = ("撤销了本版新导入的 %d 项内容" % count if count
                else "这一版没有新导入的内容（与上一版一致），没有条目需要撤销")
        return True, ("已把插件「%s」回滚到上一版 %s：%s"
                      "（你自己的角色 / 台词 / 音效一件没动）"
                      % (safe, restored.get("version") or "(未知)", done))

    def set_enabled(self, pid: Any, on: Any) -> tuple:
        """启用/禁用插件：只改登记里的 enabled，**文件一个不动**（可逆）。返回 (ok, msg)。"""
        reserved = _reserved_problem(pid)
        if reserved:
            return False, reserved
        safe = _safe_id(pid)
        if not safe:
            return False, "插件 id 不合法：%r" % (pid,)
        target = os.path.join(self._plugins_dir, safe)
        registry = self._load_registry()
        record = registry["plugins"].get(safe)
        if record is None:
            if not os.path.isdir(target):
                return False, "插件未安装：%s" % safe
            record = {"id": safe, "name": safe}    # 手工拷进来的目录：补一条登记，保证可逆
            registry["plugins"][safe] = record
        record["enabled"] = bool(on)
        werr = self._save_registry(registry)
        if werr:
            return False, "写入安装登记失败：%s" % werr
        return True, "已%s插件「%s」（文件保留，可随时改回来）" % ("启用" if on else "禁用", safe)

    def list_installed(self) -> tuple:
        """已装插件清单 → (list[dict], list[str])。

        清单本体调 Phase 0 的 read_installed（**单一读取口径**：坏目录/坏 JSON 只跳过并
        进问题串），这里补上登记表里的 enabled / 来源 / 安装时间，并按 id 排序。
        """
        if not self._plugins_dir:
            return [], ["插件数据目录不可用（宿主未接线）"]
        try:
            rows, problems = pet_plugin.read_installed(self._plugins_dir)
        except Exception as e:      # 兜底：清单读不出来也不该让对话框打不开
            rows, problems = [], ["读取插件目录失败：%s" % e]
        registry = self._load_registry()["plugins"]
        merged = {}
        seen_dirs = set()
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            pid = _safe_id(row.get("id"))
            if not pid:
                continue
            item = dict(registry.get(pid) or {})
            for key, value in row.items():
                if value not in (None, ""):
                    item[key] = value
            item["id"] = pid
            item.setdefault("name", pid)
            item.setdefault("enabled", True)
            merged[pid] = item
            seen_dirs.add(_norm_dir(row.get("dir")))
        for pid, record in registry.items():
            if pid in merged or pet_plugin.is_reserved_plugin_name(pid):
                # 保留名不是插件：登记里出现只可能是旧版本留下的脏数据（P2-2 同源）
                continue
            # 第四优先：manifest 里的 id 与目录名不一致时，上面那行已经代表了这个目录——
            # 登记再补一行就是**同一个目录列出两条**（用户看到"装了两个插件"）。
            if _norm_dir(os.path.join(self._plugins_dir, pid)) in seen_dirs:
                continue
            if os.path.isdir(os.path.join(self._plugins_dir, pid)):
                item = dict(record)
                item.update({"id": pid, "name": item.get("name") or pid,
                             "enabled": bool(item.get("enabled", True))})
                merged[pid] = item
        return [merged[k] for k in sorted(merged)], [str(x) for x in (problems or [])]

    # ---------- 落地（把 payload 并进宿主库） ----------
    def _land(self, data_kind: str, payload_dir: str, ledger: Any = None) -> tuple:
        """按 data_kind 分派落地 → (landed | {}, err)。

        ledger：内容指纹账（{key: [fp…]}，来自安装登记）。里面的条目**不再重复落地**，
        只有没见过指纹的才是"新版新增"，真正并进宿主库。缺省空账 = 全部落地（首次安装）。
        """
        handler = {"role": self._land_role, "lines": self._land_lines,
                   "audio": self._land_audio, "voice_ref": self._land_voice_ref,
                   "behaviors": self._land_behaviors, "prompt": self._land_prompt}.get(data_kind)
        if handler is None:
            return {}, ("本版本不支持落地「%s」类插件（已接 %s）"
                        % (data_kind, " / ".join(LANDING_KINDS)))
        return handler(payload_dir, _ledger_live(ledger))

    def _legacy_ledger(self, data_kind: str, old_dir: str, new_payload_dir: str,
                       ledger: dict) -> tuple:
        """v2.5.1 的旧登记没有内容指纹 → 用**上一版目录**里的 payload 补一次账。

        为什么不能"没账就当全新落地"：旧登记明明记着"内容已落地"，那样用户一更新就会多出
        一份角色 / 台词。补账读不出上一版目录时才退一步：把**新版**的指纹全部当成已落地
        （宁可少合并，也不给用户多一份重复内容），并如实告诉用户。
        返回 (ledger, 说明文案)。

        v2.6.0 第 4 轮（找茬审查 A-3）：这条兜底分支的**文案**此前与行为不符——它说"没有
        合并新版内容"，但落地的 _fresh 还有一条 still_there 判据（宿主库里已经查不到那条
        内容时照常补回来，"内容真的不在了就补回来"与 prompt 类同一个口径），所以**库里还缺
        的条目这一版照样会进来**。补了一条用例钉住它，文案也改成说得准的那句。
        """
        old_payload = ""
        manifest, _err = _read_json_file(os.path.join(str(old_dir or ""), MANIFEST_NAME), dict)
        if isinstance(manifest, dict):
            root = _payload_root(manifest).rstrip("/")
            cand = os.path.join(str(old_dir), *root.split("/")) if root else str(old_dir)
            if os.path.isdir(cand):
                old_payload = cand
        if old_payload:
            for key, fps in _package_fingerprints(data_kind, old_payload).items():
                ledger.setdefault(key, set()).update(str(x) for x in fps if str(x))
            return ledger, ""
        for key, fps in _package_fingerprints(data_kind, new_payload_dir).items():
            ledger.setdefault(key, set()).update(str(x) for x in fps if str(x))
        return ledger, ("⚠ 上一版安装登记里没有内容指纹、上一版目录也读不出来：这次的"
                        "「哪些内容已经落过」是按**新版自己**的指纹补的账——宿主库里已经有的"
                        "不会重复落，**还缺的照常补回来**（下次更新就能按上一版内容精确合并了）。")

    # ---- role ----
    def _land_role(self, payload_dir: str, ledger: dict) -> tuple:
        """角色类：payload 是标准角色包就用既有导入管线；是简化写法就走 land_role。

        指纹覆盖角色内容与它引用的素材：同一个角色包再装一次不会再多出一只角色。
        （有意不查"那只角色还在不在库里"：角色是用户能改名/删除的对象，按内容判"装过了"
        就够了；要重新装一只请先卸载插件——见 _dev/plugin_market_report_v260.md。）
        """
        fp, mode = _role_fingerprint(payload_dir)
        if fp and fp in ledger.get("roles", set()):
            return {"roles": [], "skipped": 1}, ""
        if fp:
            ledger.setdefault("roles", set()).add(fp)
        if mode == "bundle":
            return self._land_role_bundle(payload_dir)
        return self._land_role_dict(payload_dir)

    def _land_role_bundle(self, payload_dir: str) -> tuple:
        """payload 本身就是标准 .dfypet.zip 角色包 → 打成临时角色包交给 import_bundle。

        这是"零新代码"的落地路径：换新文件名防覆盖、角色冲突换 id、行为导入、失败回滚
        全部由 pet_export.import_bundle 既有事务逻辑负责（C 的打包工具就产出这个布局）。
        **配置传深拷贝**：包里带的"可分享配置"不写回宿主配置（插件不许改用户已有设置）。
        """
        role_lib = self._lib("role_lib")
        if role_lib is None:
            return {}, "宿主角色库不可用（role_lib 未接线），role 插件无法落地"
        manifest, merr = _read_json_file(os.path.join(payload_dir, MANIFEST_NAME), dict)
        if manifest is None:
            return {}, "%s 读取失败：%s" % (MANIFEST_NAME, merr)
        if manifest.get("format") != pet_export.BUNDLE_FORMAT:
            return {}, ("payload 里的 %s 不是角色包（format=%r，应当是 %r）——"
                        "role 插件应当放标准角色包或 role.json"
                        % (MANIFEST_NAME, manifest.get("format"), pet_export.BUNDLE_FORMAT))
        tmp_root = tempfile.mkdtemp(prefix="dfypet_role_")
        try:
            bundle = os.path.join(tmp_root, "bundle.dfypet.zip")
            with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(pet_export.MANIFEST_NAME,
                            json.dumps(manifest, ensure_ascii=False, indent=2))
                for rel in _iter_files(payload_dir, pet_plugin.ALLOWED_EXTS):
                    if rel == MANIFEST_NAME:
                        continue
                    zf.write(os.path.join(payload_dir, *rel.split("/")), rel)
            cfg = {}
            if self._pet is not None:
                live = getattr(self._pet, "cfg", None)
                if isinstance(live, dict):
                    cfg = copy.deepcopy(live)   # 插件不许改用户现有配置
            behaviors = self._lib("behaviors") or _NoBehaviors()
            result, rerr = pet_export.import_bundle(role_lib, behaviors, cfg, bundle)
            if result is None:
                hint = ""
                if "引用非法文件名" in str(rerr):
                    hint = ("（角色包里的 role.file 必须是**纯文件名**、素材放 roles/ 下——"
                            "与 .dfypet.zip 角色包同一格式）")
                return {}, "角色落地失败：%s%s" % (rerr, hint)
            warnings = [str(x) for x in (result.get("warnings") or [])]
            landed = {"roles": [str(result.get("role_id") or "")], "warnings": warnings}
            # 标准角色包自带的行为也会真的并进行为库（import_bundle 里逐个 add）——登记
            # 要如实记账：用户该看到"多了几个行为"，安装失败要按这些 id 回滚。
            behavior_ids = [str(x) for x in (result.get("behavior_map") or {}).values() if x]
            if behavior_ids:
                landed["behaviors"] = behavior_ids
            return landed, ""
        finally:
            shutil.rmtree(tmp_root, ignore_errors=True)

    def _land_role_dict(self, payload_dir: str) -> tuple:
        """简化写法：payload/role.json（角色 dict，素材相对于 payload 根）。"""
        role_lib = self._lib("role_lib")
        if role_lib is None:
            return {}, "宿主角色库不可用（role_lib 未接线），role 插件无法落地"
        role, rerr = _read_json_file(os.path.join(payload_dir, ROLE_PAYLOAD), dict)
        if role is None:
            return {}, ("role 插件的 payload 里既没有标准角色包（%s）也没有 %s：%s"
                        % (MANIFEST_NAME, ROLE_PAYLOAD, rerr))
        # P1-2：缺 id 的角色条目会在角色库里留下一条**没有 id 的裸记录**——随后任何
        # role_lib.get() / delete() / update() 都直接 r["id"] → KeyError（桌宠启动路径上
        # 就会踩到），而重启时 _normalize_role 又把它丢掉，只剩 roles/ 里的孤儿 png。
        # bundle 路径一直有这道硬门（pet_export.validate_bundle："角色包缺少角色 id"），
        # role.json 路径此前没有 —— 这里补上。
        if not str(role.get("id") or "").strip():
            return {}, "%s 缺少角色 id（角色条目必须有非空字符串 id）" % ROLE_PAYLOAD
        # 归一化再交给 land_role：用角色库自己的读侧归一（旧字段升级成 forms/…、非法条目
        # 返回 None），落地进去的形状 = 重启后读回来的形状。归一化不通过（例如只写了 forms
        # 没有顶层 file）就当落地失败——落一条重启即消失的条目毫无意义。
        normalize = getattr(role_lib, "_normalize_role", None)
        if callable(normalize):
            try:
                normalized = normalize(dict(role))
            except Exception as e:
                return {}, "%s 归一化失败：%s" % (ROLE_PAYLOAD, e)
            if normalized is None:
                return {}, ("%s 不是合法的角色条目（角色库归一化不通过：需要非空 id + "
                            "顶层 file 指向 .png）" % ROLE_PAYLOAD)
            role = normalized
        refs = pet_export._role_file_refs(role)
        if not refs:
            return {}, "%s 里没有任何角色素材引用（file / forms / frames 全空）" % ROLE_PAYLOAD
        name_map = {}
        written = []
        for ref in refs:
            srcp = _resolve_inside(payload_dir, ref)
            if not srcp or not os.path.isfile(srcp):
                _remove_files(written, self._log, drop_empty_parents=True)
                return {}, "role 插件的角色素材缺失：%s" % ref
            if os.path.splitext(srcp)[1].lower() != ".png":
                _remove_files(written, self._log, drop_empty_parents=True)
                return {}, "role 插件的角色素材必须是 .png：%s" % ref
            new_name = "%s_p%s.png" % (uuid.uuid4().hex[:8], uuid.uuid4().hex[:6])
            dst = role_lib.resolve(new_name)
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copyfile(srcp, dst)
            except Exception as e:
                _remove_files(written, self._log, drop_empty_parents=True)
                return {}, "写入角色素材失败：%s" % e
            written.append(dst)
            name_map[ref] = new_name
        new_role = pet_export._remap_role_files(role, name_map)
        rid, lerr = pet_export.land_role(role_lib, new_role)   # 与「导入角色包」同一套口径
        if lerr:
            _remove_files(written, self._log, drop_empty_parents=True)
            return {}, lerr
        return {"roles": [rid] if rid else []}, ""

    # ---- lines ----
    def _land_lines(self, payload_dir: str, ledger: dict) -> tuple:
        """台词类：**只落指纹没见过的**台词（可选对白按 key → id 映射后 add_dialogue）。

        v2.6.0：更新时新版新增的台词会真的进库；与上一版内容相同的那些按指纹跳过（不重复
        落地）。对白引用改按"key → 文本 → 库内 id"解析——被跳过的旧台词也能被新对白引用。
        失败逐条回滚。
        """
        lines_lib = self._lib("lines_lib")
        if lines_lib is None:
            return {}, "宿主台词库不可用（lines_lib 未接线），lines 插件无法落地"
        plan_lines, plan_dialogues, perr = _plan_lines(payload_dir)
        if perr:
            return {}, perr
        live = self._live_line_ids(lines_lib)
        fresh_lines = _fresh(plan_lines, "lines", ledger,
                             still_there=(lambda it: it["item"]["text"] in live)
                             if live is not None else None)
        fresh_dialogues = _fresh(plan_dialogues, "dialogues", ledger)
        skipped = ((len(plan_lines) + len(plan_dialogues))
                   - (len(fresh_lines) + len(fresh_dialogues)))
        if not fresh_lines and not fresh_dialogues:
            return {"lines": [], "skipped": skipped}, ""
        added, keyed = [], {}
        for it in fresh_lines:
            item = it["item"]
            line, lerr = lines_lib.add(item["text"], item["category"],
                                       item["role_slot"], item["voice_slot"])
            if line is None:
                self._rollback_lines(lines_lib, added, [])
                return {}, "台词导入失败（%s）：%s" % (item["text"][:12], lerr)
            lid = str(line.get("id") or "")
            added.append(lid)
            for key in item["keys"]:
                keyed.setdefault(key, lid)
        made = []
        for it in fresh_dialogues:
            dialogue, texts = it["dialogue"], it["texts"]
            unknown = [ref for ref, text in zip(dialogue["refs"], texts) if text is None]
            if unknown:
                self._rollback_lines(lines_lib, added, made)
                return {}, ("对白「%s」引用了包里没有的台词：%s"
                            % (dialogue["name"], "、".join(unknown[:3])))
            ids = [keyed.get(ref) or (live or {}).get(text)
                   for ref, text in zip(dialogue["refs"], texts)]
            missing = [ref for ref, new_id in zip(dialogue["refs"], ids) if not new_id]
            if missing:
                self._rollback_lines(lines_lib, added, made)
                return {}, ("对白「%s」引用的台词在台词库里找不到（可能被删掉了）：%s"
                            "——先卸载这个插件再装一次就能修好"
                            % (dialogue["name"], "、".join(missing[:3])))
            made_line, derr = lines_lib.add_dialogue(dialogue["name"], ids)
            if made_line is None:
                self._rollback_lines(lines_lib, added, made)
                return {}, "对白导入失败（%s）：%s" % (dialogue["name"], derr)
            made.append(str(made_line.get("id") or ""))
        landed = {"lines": [x for x in added if x], "skipped": skipped}
        if made:
            landed["dialogues"] = [x for x in made if x]
        return landed, ""

    def _live_line_ids(self, lines_lib: Any) -> Any:
        """台词库里现存的 {文本: id}（取不到 → None：调用方按"判不了"处理，只按指纹去重）。

        为什么要它：对白引用的 key 只存在于**包内**，被指纹跳过（= 上一版已落地）的台词
        不会有"本次新 id"，只能按文本回查库里的那一条。
        """
        try:
            rows = lines_lib.lines()
        except Exception as e:
            self._log_rollback("台词库清单", e)
            return None
        out = {}
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            text = str(row.get("text") or "")
            lid = str(row.get("id") or "")
            if text and lid:
                out.setdefault(text, lid)
        return out

    def _rollback_lines(self, lines_lib: Any, line_ids: Any, dialogue_ids: Any) -> None:
        """回滚已经并进台词库的条目（尽力而为：失败只记日志）。"""
        for did in reversed([x for x in (dialogue_ids or []) if x]):
            try:
                lines_lib.delete_dialogue(did)
            except Exception as e:
                self._log_rollback("对白 %s" % did, e)
        for lid in reversed([x for x in (line_ids or []) if x]):
            try:
                lines_lib.delete(lid)
            except Exception as e:
                self._log_rollback("台词 %s" % lid, e)

    def _log_rollback(self, what: str, err: Any) -> None:
        """回滚失败只记一行（不打断回滚，也不把异常冒给用户）。"""
        if self._log is not None:
            try:
                self._log("插件落地回滚失败（%s）：%r" % (what, err))
            except Exception:
                pass  # 有意忽略：日志自身失败无处可记

    # ---- audio / voice_ref（同一套"逐文件入库"接口） ----
    def _land_audio(self, payload_dir: str, ledger: dict) -> tuple:
        return self._land_media("audio_lib", payload_dir, "音效", ledger)

    def _land_voice_ref(self, payload_dir: str, ledger: dict) -> tuple:
        return self._land_media("voice_assets", payload_dir, "参考音", ledger)

    def _land_media(self, lib_name: str, payload_dir: str, label: str,
                    ledger: dict) -> tuple:
        """音频类：payload 下每个 .wav/.mp3 逐个 import_file（名字取 pack.json 建议，缺省用文件名）。

        只导入条目、**不动用户的音效组槽位**（插件不许改用户已有的东西）。
        v2.6.0：指纹 = **文件内容的 sha256**——同一个音频（哪怕换了文件名/显示名）不会重复入库，
        新版里新增的音频会真的进库。有意**不**把显示名算进指纹：改个名字不该多出一份同样的音。
        """
        lib = self._lib(lib_name)
        if lib is None:
            return {}, "宿主%s库不可用（%s 未接线），该类插件无法落地" % (label, lib_name)
        key = "audio" if lib_name == "audio_lib" else "voice_ref"
        plan, perr = _plan_media(payload_dir, label)
        if perr:
            return {}, perr
        fresh = _fresh(plan, key, ledger)
        skipped = len(plan) - len(fresh)
        if not fresh:
            return {key: [], "skipped": skipped}, ""
        names = _pack_names(payload_dir)
        ids = []
        for it in fresh:
            rel = it["rel"]
            srcp = os.path.join(payload_dir, *rel.split("/"))
            name = names.get(rel) or os.path.splitext(os.path.basename(rel))[0]
            item, err = lib.import_file(srcp, name=name)
            if item is None:
                self._rollback_media(lib, ids, label)
                return {}, "%s导入失败（%s）：%s" % (label, rel, err)
            ids.append(str(item.get("id") or ""))
        # landed 记**库内 id**（不是包内路径）：安装最终失败时 _unland 靠它逐条回滚
        return {key: ids, "skipped": skipped}, ""

    def _rollback_media(self, lib: Any, ids: Any, label: str) -> None:
        for fid in reversed([x for x in (ids or []) if x]):
            try:
                lib.delete(fid)
            except Exception as e:
                self._log_rollback("%s %s" % (label, fid), e)

    # ---- behaviors ----
    def _land_behaviors(self, payload_dir: str, ledger: dict) -> tuple:
        """行为类：逐条交给既有 BehaviorService.import_file（id 校验/新 id 都由它负责）。

        v2.6.0：指纹 = 行为 dict 的规范形——import_file **每次都会分配新 id**，不按内容去重
        的话每次更新都会多出一份同样的行为。
        """
        svc = self._lib("behaviors")
        if svc is None:
            return {}, "宿主行为库不可用（behaviors 未接线），behaviors 插件无法落地"
        plan, perr = _plan_behaviors(payload_dir)
        if perr:
            return {}, perr
        fresh = _fresh(plan, "behaviors", ledger)
        skipped = len(plan) - len(fresh)
        if not fresh:
            return {"behaviors": [], "skipped": skipped}, ""
        tmp_dir = tempfile.mkdtemp(prefix="dfypet_beh_")
        added, landed = [], []
        try:
            for i, it in enumerate(fresh):
                one = os.path.join(tmp_dir, "b%d.json" % i)
                try:
                    with open(one, "w", encoding="utf-8") as f:
                        json.dump({"behavior": it["record"]}, f, ensure_ascii=False)
                except Exception as e:
                    self._rollback_behaviors(svc, added)
                    return {}, "行为文件准备失败（%s）：%s" % (it["src"], e)
                item, err = svc.import_file(one)
                if item is None:
                    self._rollback_behaviors(svc, added)
                    return {}, "行为导入失败（%s）：%s" % (it["src"], err)
                added.append(str(item.get("id") or ""))
                landed.append(str(item.get("id") or ""))   # 记库内 id：_unland 靠它回滚
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        return {"behaviors": landed, "skipped": skipped}, ""

    def _rollback_behaviors(self, svc: Any, ids: Any) -> None:
        for bid in reversed([x for x in (ids or []) if x]):
            try:
                svc.delete(bid)
            except Exception as e:
                self._log_rollback("行为 %s" % bid, e)

    # ---- 撤销落地（S1-a / S1-b）：安装最终失败时把已经并进宿主库的条目撤回去 ----
    def _unland(self, data_kind: str, landed: Any) -> None:
        """撤销一次**已经并进宿主库**的落地；尽力而为，失败只记日志、不外泄异常。

        为什么需要它：落地发生在"提交插件目录 + 写安装登记"之前，而这两步都可能失败。
        只删插件目录的话，用户看到的是"安装失败"，台词/角色却已经永久进了库（插件管理里
        还看不到这个插件，重装还会再导一份）——库和登记必须一起走。

        与 _land_* 一一对应；landed 里存的是各库自己的 id（prompt 类存文件名）。role 走
        标准角色包布局时会连带导入包内行为，所以 data_kind=role 也要撤 behaviors。
        """
        if not isinstance(landed, dict):
            return

        def _ids(key: str) -> list:
            return [str(x) for x in (landed.get(key) or []) if str(x)]

        if data_kind == "lines":
            self._rollback_lines(self._lib("lines_lib"), landed.get("lines"),
                                 landed.get("dialogues"))
        elif data_kind == "role":
            self._rollback_behaviors(self._lib("behaviors"), _ids("behaviors"))
            self._rollback_roles(_ids("roles"))
        elif data_kind == "audio":
            self._rollback_media(self._lib("audio_lib"), _ids("audio"), "音效")
        elif data_kind == "voice_ref":
            self._rollback_media(self._lib("voice_assets"), _ids("voice_ref"), "参考音")
        elif data_kind == "behaviors":
            self._rollback_behaviors(self._lib("behaviors"), _ids("behaviors"))
        elif data_kind == "prompt":
            self._rollback_prompts(_ids("prompts"))
        # 回滚删完素材后可能只剩空目录：那是本次安装刚建出来的，一起撤掉
        if self._data_dir:
            for sub in ("roles", "audio", "voice_ref", "prompts/custom"):
                _drop_empty_dir(os.path.join(self._data_dir, *sub.split("/")))

    def _rollback_roles(self, ids: Any) -> None:
        """删掉刚并进角色库的条目（delete 会连同本次刚拷进去的素材文件一起删）。"""
        lib = self._lib("role_lib")
        for rid in reversed([x for x in (ids or []) if x]):
            try:
                lib.delete(rid)
            except Exception as e:
                self._log_rollback("角色 %s" % rid, e)

    def _rollback_prompts(self, names: Any) -> None:
        """删掉刚拷进 prompts/custom/ 的人设文件（只删本插件写进去的那几个名字）。"""
        if not self._data_dir:
            return
        target_dir = os.path.join(self._data_dir, PROMPTS_DIRNAME, PROMPTS_CUSTOM_DIRNAME)
        for name in [x for x in (names or []) if x]:
            path = os.path.join(target_dir, os.path.basename(str(name)))
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except Exception as e:
                self._log_rollback("人设 %s" % name, e)

    def _drop_empty_plugins_dir(self, made_dir: bool) -> None:
        """失败的安装连空的 plugins/ 都不留（P3-2：解包临时目录现在建在 plugins/ 里）。

        只在这个目录是**本次调用刚建出来的**、且确实空时删——用户自己的空目录不动
        （他可能就是准备手放插件目录）。
        """
        if made_dir and self._plugins_dir:
            _drop_empty_dir(self._plugins_dir)

    # ---- prompt（人设文件） ----
    def _land_prompt(self, payload_dir: str, ledger: dict) -> tuple:
        """人设类：payload 下每个 .txt 拷进 <数据目录>/prompts/custom/（**同名一律拒绝**）。

        与 桌宠.persona_file_ids 的口径一致：custom/<文件名>.txt 会自动出现在 AI 设置里。
        绝不覆盖用户已有的人设文件（那是用户数据）。
        v2.6.0：指纹 = 文件名 + 内容——更新时同样的人设不会重写一遍（用户改过它也不会被
        覆盖回去）；但**文件真的不在了**（用户删了）就补回来。
        """
        if not self._data_dir:
            return {}, "插件数据目录不可用（宿主未接线），prompt 插件无法落地"
        items, perr = _plan_prompts(payload_dir)
        if perr:
            return {}, perr
        target_dir = os.path.join(self._data_dir, PROMPTS_DIRNAME, PROMPTS_CUSTOM_DIRNAME)
        # S3③：**先把所有判据过一遍，再建目录**。此前先 makedirs 再逐条判，任何一条不通过
        # 都会留下一个空的 prompts/custom/（"失败的安装不留残余"就不成立了）。
        plan, seen, skipped, warnings, blocked = [], set(), 0, [], []
        for it in items:
            rel = it["rel"]
            stem = os.path.splitext(os.path.basename(rel))[0].strip()
            if not stem:
                return {}, "人设文件名不合法：%s" % rel
            name = stem + ".txt"
            if name in seen:
                return {}, ("人设文件在包内重名（%s）：两个不同目录下的同名文件会互相覆盖"
                            % name)
            seen.add(name)
            dst = os.path.join(target_dir, name)
            fp = str(it.get("fp") or "")
            mine = ledger.get("prompts")
            mine = mine if isinstance(mine, set) else set(mine or ())
            if fp and fp in mine and os.path.isfile(dst):
                skipped += 1                 # 同一个人设已经落地过：不重写（也不动用户改过的它）
                continue
            if os.path.exists(dst):
                # v2.6.0 第 4 轮（兼容审查 P2-1）：**按内容指纹区分两种情况**，不再一律整包失败。
                # 旧行为是"目标文件存在 → 整个更新失败"：新版只改了自己上次落地的那份同名
                # 人设（用户一个字没动），用户就完全更新不了（实测 v1→v2 改一份内容 → 拒装、
                # 快照 0 变化）。
                #   ① 盘上这份的内容 == 本插件落地过的某一版（用户没动过）→ 允许覆盖更新；
                #   ② 用户改过（盘上内容不是本插件落的任何一版）→ 跳过该文件 + 人话警告，
                #      其余内容照常落地：保住用户数据，但不拿它把整包更新顶掉。
                if _fp_named_file(name, dst) not in mine:
                    blocked.append(name)
                    warnings.append("「%s」是你自己改过的，这一版没有覆盖它"
                                    "（插件其余内容照常落地）" % name)
                    continue
            if fp:
                ledger.setdefault("prompts", set()).add(fp)
            plan.append((rel, dst, name))
        if blocked and not plan and not skipped:
            # 包里**一条**内容都没进得去（全被用户已有文件挡住）：那是失败，不是"装上了"。
            # 这条保住了 v2.5.1 的判据（同名就拒、用户人设不被插件吃掉）——只是不再拿它
            # 去顶掉"部分内容被挡住、其余照常落地"的正常更新（见上面 P2-1 的两种情形）。
            return {}, ("人设文件已存在且不是本插件落地的，插件不许覆盖：%s"
                        % "、".join(blocked[:3]))
        try:
            os.makedirs(target_dir, exist_ok=True)
        except Exception as e:
            return {}, "无法创建人设目录：%s" % e
        written, landed = [], []
        for rel, dst, name in plan:
            try:
                shutil.copyfile(os.path.join(payload_dir, *rel.split("/")), dst)
            except Exception as e:
                _remove_files(written, self._log, drop_empty_parents=True)
                return {}, "写入人设文件失败（%s）：%s" % (rel, e)
            written.append(dst)
            landed.append(name)
        return {"prompts": landed, "skipped": skipped, "warnings": warnings}, ""

    # ---------- 安装登记（_installed.json） ----------
    def _load_registry(self) -> dict:
        """读 _installed.json → 规范形状；坏文件/坏结构按空表（绝不抛，绝不覆盖别人的插件）。"""
        if not self.installed_path:
            return {"format": INSTALLED_FORMAT, "version": INSTALLED_VERSION, "plugins": {}}
        data, _corrupted = pet_io.read_json_or(self.installed_path, dict,
                                               expect=dict, log=self._log)
        raw = data.get("plugins") if isinstance(data, dict) else None
        if isinstance(raw, list):                  # 容忍 list 形态（手写/早期版本）
            raw = {str(r.get("id")): r for r in raw
                   if isinstance(r, dict) and r.get("id")}
        if not isinstance(raw, dict):
            raw = {}
        return {"format": INSTALLED_FORMAT, "version": INSTALLED_VERSION,
                "plugins": {str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)}}

    def _save_registry(self, registry: dict) -> str:
        """原子写 _installed.json；成功 ""，失败错误串。"""
        if not self.installed_path:
            return "插件数据目录不可用（宿主未接线）"
        err = pet_io.atomic_write_json(self.installed_path, registry, log=self._log)
        return err or ""
