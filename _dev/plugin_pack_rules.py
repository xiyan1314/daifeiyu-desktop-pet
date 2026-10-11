# -*- coding: utf-8 -*-
"""PetHub 插件包 **12 条判据的参考实现**（v2.5.1 · 代理 C 的临时校验器 + 打包共用件）。

为什么有这份东西
----------------
正牌校验器是代理 A 的 pet_plugin.py（Phase 0）。本轮三路并行，官方内容插件（代理 C）
必须在 A 落地**之前**就能自证"每个包都过得了校验器"，所以这里按任务书 A1 的 12 条判据
写一份参照实现；A 落地后本模块**优先调用它**（engine="auto" 就用 pet_plugin），自己那份
只在 A 未落地时充当尺子，并用于**交叉核对**（两个引擎对同一个包必须给出同一结论）。

12 条判据（序号与 _dev/task_v251.md 的 A1 逐条对应）
--------------------------------------------------
 1  zip 可打开；条目数 <= EXPORT_MAX_ENTRIES；解压总量 <= EXPORT_MAX_BYTES（复用 pet_export 常量）
 2  manifest.json 存在、UTF-8 **无 BOM**、可解析为 dict；有 plugin 段
 3  format == "dfypet-plugin"；version 是 int 且 <= 宿主支持的格式版本
 4  全量 namelist 路径安全：== "manifest.json" 或 startswith("payload/")；无 .. / 不以斜杠或盘符
    开头 / 无反斜杠 / 无 NUL
 5  外部属性：external_attr >> 16 不得带执行位（0o111）；符号链接（0o120000）一律拒
 6  扩展名白名单：.png .jpg .jpeg .wav .mp3 .txt .json .md；其余**点名文件**拒绝
 7  code 一致性：kind == "data" 则 code is False；kind != "data" 则 code is True
 8  capabilities 必须是宿主白名单的子集
 9  双版本门：min_host_version <= 宿主 VERSION（四段整数比较）；api_version 在 API_VERSIONS 里
10  校验和：files 必须覆盖 payload 下**每一个**条目（多一个少一个都拒）；逐条核对 sha256 与 bytes
11  kind == "data" 则 data_kind 必须在 DATA_KINDS 里
12  kind == "ui" 则无条件拒绝（"本版本不支持 UI 插件"）

判据 12 在本实现里被**提到判据 7 之后**（"无条件拒绝"的字面意思：UI 包的其余字段哪怕全合法
也必须拒）。A 的实现若把它放在末尾，结论一样（都是拒），只是 err 文案可能不同。

与仓库既有件的关系
------------------
* 条目数/解压总量上限直接 import pet_export（单一来源，不复制 2000 / 512MB 两个数字）。
* 四段版本比较与 _check_release._ver_key 同口径（数字段取前 4 位、不足补 0）。
* 本模块 Qt-free，可无 GUI 直接跑（python -B _dev/plugin_pack_rules.py 自检）。
"""
import hashlib
import io
import json
import os
import re
import sys
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import pet_export   # noqa: E402  包容量上限的单一来源（EXPORT_MAX_ENTRIES / EXPORT_MAX_BYTES）

PLUGIN_FORMAT = "dfypet-plugin"
PLUGIN_FORMAT_VERSION = 1
PAYLOAD_ROOT = "payload/"
MANIFEST_NAME = "manifest.json"
API_VERSIONS_FALLBACK = (1,)

# 数据插件种类 / 宿主能力白名单：A 的 pet_plugin 落地前按主代理 2026-10-11 的裁决写死；
# pet_plugin 可用时一律以它的常量为准（见 host_data_kinds / host_capabilities）。
DATA_KINDS_FALLBACK = ("role", "lines", "audio", "voice_ref", "behaviors", "prompt")
CAPABILITIES_FALLBACK = ("assets", "lines", "audio", "voice_ref", "behaviors", "prompts")

ALLOWED_EXTS = (".png", ".jpg", ".jpeg", ".wav", ".mp3", ".txt", ".json", ".md")
# 禁止项（校验器与文档同时写死）：可执行/脚本/快捷方式 + 嵌套压缩包
FORBIDDEN_EXTS = (".py", ".pyc", ".pyd", ".dll", ".exe", ".bat", ".cmd", ".ps1", ".vbs",
                  ".js", ".com", ".scr", ".msi", ".lnk", ".zip", ".7z", ".rar", ".tar", ".gz")

# 打包参数：固定时间戳 + 固定权限位 -> 复跑产物逐字节相同（幂等判据的落点）
ZIP_DATE_TIME = (2026, 1, 1, 0, 0, 0)
ZIP_MODE = 0o600
ZIP_COMPRESSLEVEL = 9

MAX_ENTRIES = pet_export.EXPORT_MAX_ENTRIES
MAX_BYTES = pet_export.EXPORT_MAX_BYTES

# plugin.id 会被宿主当**目录名**用（<DATA_DIR>/plugins/<id>/），字符集必须收紧
# （与 pet_plugin._ID_RE / _WIN_RESERVED 同口径）
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_WIN_RESERVED = frozenset(("con", "prn", "aux", "nul")
                          + tuple("com%d" % i for i in range(1, 10))
                          + tuple("lpt%d" % i for i in range(1, 10)))


def id_problem(pid):
    """插件 id 不安全 → 人话原因；安全 → ""（与 pet_plugin._id_problem 同款）。"""
    if not isinstance(pid, str) or not pid.strip():
        return "缺少 plugin.id"
    if not _ID_RE.match(pid):
        return "plugin.id 不合法（只允许字母数字与 . _ -，字母数字开头，最长 64）：%r" % (pid,)
    if pid.endswith(".") or ".." in pid:
        return "plugin.id 不能以点结尾、也不能含 \"..\"：%r" % (pid,)
    if pid.split(".")[0].lower() in _WIN_RESERVED:
        return "plugin.id 是 Windows 保留名：%r" % (pid,)
    return ""


def payload_root_problem(root):
    """payload_root 不安全 → 人话原因；安全 → ""。"""
    if not isinstance(root, str) or not root.endswith("/"):
        return "payload_root 必须是以 / 结尾的相对目录（当前 %r）" % (root,)
    return _path_problem(root + "x")


# ---------------- 版本比较（与 _check_release._ver_key 同口径） ----------------

def ver_key(v):
    """版本串 -> 四段整数元组（"2.5.0" -> (2,5,0,0)；"2.4.1b1" -> (2,4,1,1)）。"""
    parts = [int(x) for x in re.findall(r"\d+", str(v or ""))][:4]
    return tuple(parts + [0] * (4 - len(parts)))


def host_version():
    """仓库当前版本：桌宠.py 的 VERSION 字面量（不 import 桌宠.py——那会拉 Qt）。"""
    p = os.path.join(REPO, "桌宠.py")
    with io.open(p, "r", encoding="utf-8") as f:
        text = f.read()
    m = re.search(r'^VERSION\s*=\s*"([^"]+)"', text, re.M)
    if not m:
        raise RuntimeError("读不到 桌宠.py 的 VERSION")
    return m.group(1)


# ---------------- 引擎选择：优先 A 的正牌校验器 ----------------

_PP = None
_PP_DONE = False


def pet_plugin_module():
    """A 的 pet_plugin 模块；没落地 / 导入失败返回 None（只尝试一次）。"""
    global _PP, _PP_DONE
    if not _PP_DONE:
        _PP_DONE = True
        try:
            import pet_plugin   # type: ignore
            _PP = pet_plugin
        except Exception:
            _PP = None
    return _PP


def host_data_kinds():
    m = pet_plugin_module()
    v = getattr(m, "DATA_KINDS", None) if m is not None else None
    return tuple(v) if v else DATA_KINDS_FALLBACK


def host_capabilities():
    m = pet_plugin_module()
    v = getattr(m, "CAPABILITIES", None) if m is not None else None
    return tuple(v) if v else CAPABILITIES_FALLBACK


def host_api_versions():
    m = pet_plugin_module()
    v = getattr(m, "API_VERSIONS", None) if m is not None else None
    return tuple(v) if v else API_VERSIONS_FALLBACK


def engine_status():
    """(引擎名, 常量来源说明)——报告与验证脚本用它如实标注证据口径。"""
    m = pet_plugin_module()
    if m is None:
        return ("reference", "pet_plugin 未落地：用本模块的参照实现 + 主代理裁决的常量")
    path = getattr(m, "__file__", "pet_plugin")
    return ("pet_plugin", "读 %s 的常量" % path)


def validate(path, host_ver=None, engine="auto"):
    """校验一个插件包，返回 (manifest | None, err)。

    engine="auto"：有 pet_plugin 就用它，否则用参照实现。
    engine="reference" / "pet_plugin"：强制指定（交叉核对用）。
    """
    hv = host_ver or host_version()
    if engine in ("auto", "pet_plugin"):
        m = pet_plugin_module()
        if m is not None:
            return m.validate_plugin_zip(path, hv)
        if engine == "pet_plugin":
            raise RuntimeError("pet_plugin 未落地，无法用它校验")
    return validate_reference(path, hv)


# ---------------- 参照实现：12 条判据 ----------------

def _path_problem(name):
    """条目名不安全的原因（""=安全）。"""
    if not name:
        return "条目名为空"
    if "\x00" in name:
        return "含 NUL"
    if "\\" in name:
        return "含反斜杠"
    if name.startswith("/"):
        return "以斜杠开头"
    if re.match(r"^[A-Za-z]:", name):
        return "以盘符开头"
    if ".." in name.split("/"):
        return "含 .."
    return ""


def _ext(name):
    return os.path.splitext(name)[1].lower()


def validate_reference(path, host_version_str=None):
    """12 条判据的参照实现。返回 (manifest | None, err)。"""
    hv = host_version_str or host_version()
    try:
        zf = zipfile.ZipFile(path, "r")
    except zipfile.BadZipFile:
        return None, "文件不是有效的 zip 包"
    except Exception as e:
        return None, "打开失败：%s" % e
    with zf:
        info = zf.infolist()
        names = zf.namelist()

        # 判据 1
        if len(info) > MAX_ENTRIES:
            return None, "条目过多（%d > %d）" % (len(info), MAX_ENTRIES)
        total = sum(i.file_size for i in info)
        if total > MAX_BYTES:
            return None, "解压总量过大（%d > %d 字节）" % (total, MAX_BYTES)

        # 判据 2
        try:
            raw = zf.read(MANIFEST_NAME)
        except KeyError:
            return None, "缺少 manifest.json"
        except Exception as e:
            return None, "manifest.json 读取失败：%s" % e
        if raw[:3] == b"\xef\xbb\xbf":
            return None, "manifest.json 带 UTF-8 BOM（必须无 BOM）"
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            return None, "manifest.json 不是 UTF-8：%s" % e
        try:
            mf = json.loads(text)
        except Exception as e:
            return None, "manifest.json 无法解析：%s" % e
        if not isinstance(mf, dict):
            return None, "manifest.json 顶层不是对象"
        plugin = mf.get("plugin")
        if not isinstance(plugin, dict):
            return None, "manifest.json 缺少 plugin 段"

        # 判据 3
        if mf.get("format") != PLUGIN_FORMAT:
            return None, "不是大肥鱼插件包（format=%r）" % mf.get("format")
        ver = mf.get("version")
        if isinstance(ver, bool) or not isinstance(ver, int):
            return None, "version 必须是整数（得到 %r）" % (ver,)
        if ver > PLUGIN_FORMAT_VERSION:
            return None, "包格式版本 %d 高于宿主支持的 %d" % (ver, PLUGIN_FORMAT_VERSION)
        root = mf.get("payload_root")
        if root is None or root == "":
            root = PAYLOAD_ROOT
        why_root = payload_root_problem(root)
        if why_root:
            return None, why_root

        # 判据 4
        for n in names:
            why = _path_problem(n)
            if why:
                return None, "条目名不安全（%s）：%s" % (why, n)
            if n != MANIFEST_NAME and not n.startswith(root):
                return None, "条目不在 %s 下：%s" % (root, n)

        # 判据 5
        for zi in info:
            mode = (zi.external_attr >> 16) & 0xFFFF
            if (mode & 0o170000) == 0o120000:
                return None, "条目是符号链接：%s" % zi.filename
            if mode & 0o111:
                return None, "条目带执行位（mode=%o）：%s" % (mode, zi.filename)

        # 判据 6（目录条目以 / 结尾：A 的校验器把它们排除在 files 覆盖与扩展名判据之外——
        # 实测 zipfile 写目录就是 0o40775，算进白名单会把所有带目录条目的包误拒）
        payload = [n for n in names if n != MANIFEST_NAME and not n.endswith("/")]
        for n in payload:
            got = _ext(n)
            if got not in ALLOWED_EXTS:
                mark = "（禁止项）" if got in FORBIDDEN_EXTS else ""
                return None, "不允许的文件类型%s：%s" % (mark, n)

        # 判据 7
        kind = plugin.get("kind")
        code = plugin.get("code")
        if kind == "data" and code is not False:
            return None, "数据插件必须 code=false（kind=data，code=%r）" % (code,)
        if kind != "data" and code is not True:
            return None, "非数据插件必须 code=true（kind=%r，code=%r）" % (kind, code)

        # 判据 12（提前到 7 之后：无条件拒绝）
        if kind == "ui":
            return None, "本版本不支持 UI 插件"

        # 判据 8
        caps = plugin.get("capabilities")
        if not isinstance(caps, list):
            return None, "capabilities 必须是数组"
        allow = host_capabilities()
        unknown = [c for c in caps if not isinstance(c, str) or c not in allow]
        if unknown:
            return None, "capabilities 不在宿主白名单 %s：%r" % (list(allow), unknown)

        # 判据 9
        mhv = plugin.get("min_host_version")
        if not isinstance(mhv, str) or not mhv.strip():
            return None, "缺少 min_host_version"
        if ver_key(mhv) > ver_key(hv):
            return None, "本插件要求宿主 %s，当前 %s" % (mhv.strip(), hv)
        av = plugin.get("api_version")
        if av not in host_api_versions():
            return None, "api_version=%r 不在宿主支持范围 %s" % (av, list(host_api_versions()))

        # 判据 10
        listed = mf.get("files")
        if not isinstance(listed, list):
            return None, "缺少 files 清单"
        table = {}
        for f in listed:
            if not isinstance(f, dict):
                return None, "files 里有非对象条目"
            p = f.get("path")
            if not isinstance(p, str) or not p:
                return None, "files 条目缺少 path"
            if p in table:
                return None, "files 里有重复路径：%s" % p
            table[p] = f
        in_zip = set(payload)
        extra = [p for p in payload if p not in table]
        if extra:
            return None, "payload 里有文件不在 files 清单（少 %d 条）：%s" % (
                len(extra), "、".join(sorted(extra)[:5]))
        missing = [p for p in table if p not in in_zip]
        if missing:
            return None, "files 里的条目在包里不存在（多 %d 条）：%s" % (
                len(missing), "、".join(sorted(missing)[:5]))
        for p in payload:
            f = table[p]
            data = zf.read(p)
            if f.get("bytes") != len(data):
                return None, "大小不符：%s（清单 %r，实际 %d）" % (p, f.get("bytes"), len(data))
            digest = hashlib.sha256(data).hexdigest()
            if str(f.get("sha256") or "").lower() != digest:
                return None, "sha256 不符：%s" % p

        # 判据 11
        if kind == "data":
            dk = plugin.get("data_kind")
            if dk not in host_data_kinds():
                return None, "data_kind=%r 不在 %s" % (dk, list(host_data_kinds()))

        # 判据 12 之后：plugin.id 必须是能当目录名的安全 id（A 的实现同样放在最后）
        why_id = id_problem(plugin.get("id"))
        if why_id:
            return None, why_id

        return mf, ""


# ---------------- 确定性 zip 读写（打包与变异共用一套参数） ----------------

def read_entries(path):
    """-> [(name, data, mode)]；mode = external_attr >> 16（保留权限位，便于造变异）。"""
    out = []
    with zipfile.ZipFile(path, "r") as zf:
        for zi in zf.infolist():
            out.append((zi.filename, zf.read(zi.filename), (zi.external_attr >> 16) & 0xFFFF))
    return out


def _zipinfo(name, mode):
    zi = zipfile.ZipInfo(name, ZIP_DATE_TIME)
    zi.compress_type = zipfile.ZIP_DEFLATED
    zi.create_system = 0
    zi.external_attr = (mode & 0xFFFF) << 16
    return zi


def write_zip(path, entries):
    """按固定顺序/时间戳/权限位写 zip（复跑逐字节相同）。entries=[(name, bytes[, mode])]。"""
    tmp = path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in entries:
            name, data = item[0], item[1]
            mode = item[2] if len(item) > 2 else ZIP_MODE
            zf.writestr(_zipinfo(name, mode), data, compresslevel=ZIP_COMPRESSLEVEL)
    os.replace(tmp, path)


def zip_bytes(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in entries:
            name, data = item[0], item[1]
            mode = item[2] if len(item) > 2 else ZIP_MODE
            zf.writestr(_zipinfo(name, mode), data, compresslevel=ZIP_COMPRESSLEVEL)
    return buf.getvalue()


def manifest_of(path):
    with zipfile.ZipFile(path, "r") as zf:
        return json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))


def dump_json_bytes(obj):
    """manifest/index 的统一落盘口径：UTF-8、无 BOM、两空格缩进、末尾换行、非 ASCII 不转义。"""
    return (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


if __name__ == "__main__":
    name, src = engine_status()
    print("引擎：%s（%s）" % (name, src))
    print("宿主版本：%s" % host_version())
    print("条目上限：%d / %d 字节" % (MAX_ENTRIES, MAX_BYTES))
    print("DATA_KINDS：%s" % (list(host_data_kinds()),))
    print("ALLOWED_EXTS：%s" % (list(ALLOWED_EXTS),))
    print("FORBIDDEN_EXTS：%s" % (list(FORBIDDEN_EXTS),))
    hv = host_version()
    checks = [("2.5.0 <= 2.5.0", ver_key("2.5.0") <= ver_key(hv)),
              ("2.5.1 > 2.5.0", ver_key("2.5.1") > ver_key(hv)),
              ("路径 .. 被拒", _path_problem("payload/../x") == "含 .."),
              ("反斜杠被拒", _path_problem("payload/a\\b") == "含反斜杠"),
              ("安全路径放行", _path_problem("payload/fx/a.png") == "")]
    for label, ok in checks:
        print("  [%s] %s" % ("OK" if ok else "FAIL", label))
    raise SystemExit(0 if all(ok for _l, ok in checks) else 1)
