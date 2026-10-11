# -*- coding: utf-8 -*-
"""大肥鱼桌宠 · 插件包校验器（v2.5.1 Phase 0）

职责：**只做"看懂一个插件包"**——把 .dfypet-plugin zip 按 12 条判据验一遍，给出
manifest 或一句人话错误。不安装、不落盘、不碰 UI、不碰启动路径；纯逻辑、Qt-free，
可无 GUI 单测（与 pet_export 的 validate_bundle 同一路数）。

manifest.json 口径（v1，**单一真源：顶层只放包级字段，插件元数据全在 plugin 段**）::

    {
      "format": "dfypet-plugin",   # 必填：字面量
      "version": 1,                # 必填：**包格式版本**，int 且 1 <= version <= PLUGIN_FORMAT_VERSION
      "payload_root": "payload/",  # 可选，缺省 "payload/"：payload 单根目录（须以 / 结尾）
      "files": [{"path": "payload/a.png", "sha256": "<64 位 hex>", "bytes": 123}],
      "created_at": "...",         # 可选，仅记录
      "plugin": {                  # 必填：插件自己的元数据（**校验器只读这一段**）
        "id": "official-lines-basic",  # 必填：安全 id（宿主把它当目录名用，故有字符集约束）
        "name": "示例台词包",      # 可选（缺省用 id）
        "version": "1.0.0",        # 可选：插件自身版本（int 或 str，仅记录）
        "author": "...", "homepage": "...", "license": "...",
        "description": "...", "summary": "...",
        "kind": "data",            # 必填："data" | "ui"
        "data_kind": "lines",      # kind == "data" 时必填，取值见 DATA_KINDS
        "code": False,             # 必填 bool：kind == "data" ⇒ False；否则 ⇒ True
        "min_host_version": "2.5.0",   # 必填：宿主版本下限（四段整数比较）
        "max_host_version": "...",     # 可选：仅记录，本轮**不参与判定**
        "api_version": 1,              # 必填：∈ API_VERSIONS
        "capabilities": [],            # 可选：宿主权限白名单的子集；空表 = 纯数据零权限
        "events": [...], "signature": "..."   # 可选：**本轮不验签**（Phase 0 只做结构校验）
      }
    }

顶层只读 format / version / payload_root / files / created_at；若 plugin 段里的键
（id / name / kind …）在顶层又写了一份，顶层那份**一律忽略**（**不是拒绝**）——单一真源，
免得两处漂移。宿主版本 host_version 是**字符串**（如 "2.5.0"，即桌宠.VERSION），
不是元组。

12 条判据（按序判定，任何一条不过 → 返回 (None, 人话原因)）：

  1  zip 可打开；条目数 ≤ pet_export.EXPORT_MAX_ENTRIES；解压总量 ≤ pet_export.EXPORT_MAX_BYTES
  2  存在 manifest.json、UTF-8 **无 BOM**、可解析为 dict
  3  顶层 format == PLUGIN_FORMAT；顶层 version 是 int 且 ≤ PLUGIN_FORMAT_VERSION；
     存在 plugin 段（dict）
  4  全量 namelist 路径安全：每条 == "manifest.json" 或以 payload_root 开头；不含 ".."、
     不以 "/" 或盘符开头、不含反斜杠、不含 NUL、无空路径段
  5  zip 外部属性：不得带执行位（mode & 0o111）；符号链接（0o120000）一律拒
  6  扩展名白名单 ALLOWED_EXTS；FORBIDDEN_EXTS（可执行/脚本 + 嵌套压缩包）**点名文件**拒
  7  code 一致性：kind == "data" ⇒ code is False；kind != "data" ⇒ code is True
  8  capabilities ⊆ CAPABILITIES（缺省 = 空表 = 零权限）
  9  双版本门硬拒：min_host_version ≤ host_version（四段整数比较，与发布门同款）；
     api_version ∉ API_VERSIONS 也拒
  10 校验和：files 逐条核对 path / sha256 / bytes，且必须**不多不少**覆盖 payload_root 下
     的每一个文件条目（目录条目与 manifest.json 都不算）
  11 kind == "data" ⇒ data_kind ∈ DATA_KINDS
  12 kind == "ui" ⇒ 无条件拒绝（本版本不支持 UI 插件）

**禁止项清单**（与 _dev/plugin_format_v251.md 同时写死，两处必须一致）：
  可执行/脚本：.py .pyc .pyd .dll .exe .bat .cmd .ps1 .vbs .js .com .scr .msi .lnk
  嵌套压缩包：.zip .7z .rar .tar .gz
"""
import hashlib
import json
import os
import re
import stat
import zipfile

import pet_export   # 包容量上限**单一来源**：条目数/解压总量与角色包同一口径

PLUGIN_FORMAT = "dfypet-plugin"
# 包格式版本（manifest 顶层 version）：宿主能看懂的**最高**格式版本
PLUGIN_FORMAT_VERSION = 1
# 宿主支持的 API 版本（插件 plugin.api_version 必须落在里面）
API_VERSIONS = {1}

# 数据类插件的落点（每个都有现成的宿主落地管线；v1 只支持这六个）
DATA_KINDS = frozenset(("role", "lines", "audio", "voice_ref", "behaviors", "prompt"))
# 宿主权限白名单（v1）：只有"喂给某个宿主子系统"这一种权限，取值与 DATA_KINDS 同一套
# 名字（同一个真源，免得以后改一处漂一处）。空表 = 纯数据、零权限（缺省即此）。
CAPABILITIES = DATA_KINDS

# 扩展名白名单：插件 payload 允许出现的文件类型
ALLOWED_EXTS = frozenset((".png", ".jpg", ".jpeg", ".wav", ".mp3", ".txt", ".json", ".md"))
# 禁止项清单（一）：可执行/脚本——payload 里出现**任何**一个都拒，并点名该文件
FORBIDDEN_EXEC_EXTS = frozenset((".py", ".pyc", ".pyd", ".dll", ".exe", ".bat", ".cmd",
                                 ".ps1", ".vbs", ".js", ".com", ".scr", ".msi", ".lnk"))
# 禁止项清单（二）：嵌套压缩包（zip 炸弹/绕过扩展名白名单的常见载体）
FORBIDDEN_NESTED_EXTS = frozenset((".zip", ".7z", ".rar", ".tar", ".gz"))
FORBIDDEN_EXTS = FORBIDDEN_EXEC_EXTS | FORBIDDEN_NESTED_EXTS

MANIFEST_NAME = "manifest.json"
DEFAULT_PAYLOAD_ROOT = "payload/"
INSTALLED_INDEX_NAME = "_installed.json"
# 宿主安装目录里必须跳过的名字：_download（临时下载）/ _installed.json / .tmp 之类
_SKIP_PREFIX = ("_", ".")

# v2.5.1（兼容审查 P1-1 / P2-2）：出货布局的 plugins/ 里**不是插件**的名字——官方内容仓库
# （index.json / README.md / packs/）与宿主自己的安装登记、临时下载目录。
# 两个后果都必须挡住：① 它们被当插件 id 用时，安装器会**整棵替换** <数据目录>/plugins/<id>/
# （把官方内容包目录 rmtree 掉）；② 读清单时不跳过，对话框会对官方目录永远报
# "插件目录缺 manifest.json，已跳过：packs"。写入侧（pet_plugin_host）与读取侧共用这一份，
# 绝不各写一份（两份保留名清单 = 早晚漂移）。
RESERVED_PLUGIN_NAMES = frozenset(("packs", "index.json", "README.md",
                                   "_installed.json", "_download"))
_RESERVED_LOWER = frozenset(n.lower() for n in RESERVED_PLUGIN_NAMES)


def is_reserved_plugin_name(name):
    """name 是不是 plugins/ 下的**保留名**（官方仓库文件 / 宿主登记与临时目录）。

    Windows 与 macOS 的文件系统大小写不敏感：`packs` 与 `PACKS` 是同一个目录，所以这里
    一律按小写比对——否则把 id 换个大小写就绕过了保留名。
    """
    return str(name or "").strip().lower() in _RESERVED_LOWER


# id 会被宿主当**目录名**用（<DATA_DIR>/plugins/<id>/），所以字符集必须收紧：
# 字母数字开头，只允许字母数字与 . _ -，且不许以点结尾、不许出现 ".."、不许是保留名。
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_WIN_RESERVED = frozenset(("con", "prn", "aux", "nul")
                          + tuple("com%d" % i for i in range(1, 10))
                          + tuple("lpt%d" % i for i in range(1, 10)))
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def _is_version_like(raw):
    """版本串至少要有"数字开头 + 一段数字"（S2-a：version_key 对非数字串恒返回 0 段）。

    "2.5.0" / "2.4" / "(2, 4, 0, 0)" / "2.4.1b1" 都算；"abc" / "latest" / "" 不算。
    """
    text = str(raw or "").strip()
    return bool(text) and text[0].isdigit() and bool(re.search(r"\d", text))


def version_key(v):
    """版本串 / 数字串 → 可比较的四段整数元组（与 _check_release._ver_key 同款口径）。

    "2.4.0" 与 "(2, 4, 0, 0)" 等价；非数字成分跳过（"2.4.1b1" → (2,4,1,1)）；
    不足四段补 0，免得 "2.4" 与 "2.4.0" 比出"前者更小"这种假拒绝。
    两处口径由 tests/test_plugin_v251.py 的一条用例逐样本对齐（漂了就红）。
    """
    parts = [int(x) for x in re.findall(r"\d+", str(v or ""))][:4]
    return tuple(parts + [0] * (4 - len(parts)))


def _fail(err):
    """统一的失败返回（保持 (None, str) 形状，调用方只管取 err）。"""
    return None, err


def _unsafe_name_reason(name):
    """条目名不安全 → 人话原因；安全 → ""。"""
    if not isinstance(name, str) or not name:
        return "空条目名"
    if "\x00" in name:
        return "条目名含 NUL"
    if "\\" in name:
        return "条目名含反斜杠"
    if name.startswith("/"):
        return "条目名是绝对路径（以 / 开头）"
    if _DRIVE_RE.match(name):
        return "条目名以盘符开头"
    body = name.rstrip("/")
    if not body:
        return "空条目名"
    for seg in body.split("/"):
        if seg == "":
            return "条目名含空路径段"
        if seg == ".":
            return "条目名含 \".\" 段"
        if seg == "..":
            return "条目名含 \"..\" 段（路径穿越）"
    return ""


def _external_attr_reason(info):
    """zip 外部属性不安全 → 人话原因；安全 → ""。

    external_attr >> 16 是 Unix 模式位（Windows 打的包通常是 0，当作安全）。
    执行位 = 脚本/二进制的第一道门；符号链接位 = "解压时写到包外"的经典手法。
    """
    mode = (info.external_attr >> 16) & 0xFFFF
    if stat.S_ISLNK(mode):
        return "条目 %s 是符号链接" % info.filename
    # 目录条目的执行位是**正常**的（0o40775 是 zipfile 自己写目录时的标准权限），
    # 只对**文件**条目判执行位，否则所有带目录条目的合法包都会被误拒。
    if not info.is_dir() and mode & 0o111:
        return "条目 %s 带执行位（mode=0o%o）" % (info.filename, mode)
    return ""


def _payload_files(names, payload_root):
    """payload 下的**文件**条目（目录条目以 / 结尾，不算；manifest.json 不算）。"""
    out = []
    for n in names:
        if n == MANIFEST_NAME or n.endswith("/"):
            continue
        if n.startswith(payload_root):
            out.append(n)
    return sorted(out)


def _id_problem(pid):
    """插件 id 不安全 → 人话原因；安全 → ""。"""
    if not isinstance(pid, str) or not pid.strip():
        return "缺少 plugin.id"
    if not _ID_RE.match(pid):
        return "plugin.id 不合法（只允许字母数字与 . _ -，字母数字开头，最长 64）：%r" % (pid,)
    if pid.endswith(".") or ".." in pid:
        return "plugin.id 不能以点结尾、也不能含 \"..\"：%r" % (pid,)
    if pid.split(".")[0].lower() in _WIN_RESERVED:
        return "plugin.id 是 Windows 保留名：%r" % (pid,)
    if is_reserved_plugin_name(pid):
        # v2.5.1（兼容审查 P1-1）：packs / index.json / README.md 的字符集本身合法，但它们在
        # <数据目录>/plugins/ 下有别的用途（官方内容仓库）——装一个 id="packs" 的包会把官方
        # 内容包目录整棵替换掉，所以校验器这一关就点名拒绝（安装器另有第二道自保）。
        return ("plugin.id 是宿主的保留名（plugins/ 下另有用处：%s）：%r"
                % (" / ".join(sorted(RESERVED_PLUGIN_NAMES)), pid))
    return ""


def _files_problems(files, payload_files, digests):
    """判据 10：files 逐条核对 + 必须不多不少覆盖 payload 文件；返回问题列表（空=过）。

    digests：{条目名: (sha256 hex, 真实字节数)}——**分块边读边算**出来的摘要，不是把整个
    payload 留在内存里（v2.5.1 找茬审查 S2-b：旧实现用 zf.read 一次读进 texts 字典，
    512MB 上限下实测峰值 141MB/64MB ≈ 2.2×，按上限外推 >1GB）。
    """
    bad = []
    if not isinstance(files, list):
        return ["files 段不是列表（应当逐条列出 payload 下每个文件的 path/sha256/bytes）"]
    listed = []
    for i, item in enumerate(files):
        if not isinstance(item, dict):
            bad.append("files[%d] 不是对象" % i)
            continue
        path = item.get("path")
        if not isinstance(path, str) or not path:
            bad.append("files[%d] 缺 path" % i)
            continue
        listed.append(path)
        if path not in digests:
            bad.append("files 里的 %s 在包里不存在" % path)
            continue
        got_sha, got_bytes = digests[path]
        want_sha = item.get("sha256")
        if not isinstance(want_sha, str) or not want_sha.strip():
            bad.append("%s 缺 sha256" % path)
        elif want_sha.strip().lower() != got_sha:
            bad.append("%s 的 sha256 与内容不符（包被改过或清单是旧的）" % path)
        want_bytes = item.get("bytes")
        if isinstance(want_bytes, bool) or not isinstance(want_bytes, int):
            bad.append("%s 缺 bytes（int）" % path)
        elif want_bytes != got_bytes:
            bad.append("%s 的 bytes 与内容不符（清单 %r，实际 %d）"
                       % (path, want_bytes, got_bytes))
    if len(set(listed)) != len(listed):
        bad.append("files 里有重复 path")
    extra = sorted(set(listed) - set(payload_files))
    lack = sorted(set(payload_files) - set(listed))
    if extra:
        bad.append("files 多列了包外/非 payload 条目：%s" % "、".join(extra[:5]))
    if lack:
        bad.append("payload 下有文件没进 files 清单：%s" % "、".join(lack[:5]))
    return bad


def validate_plugin_zip(path, host_version):
    """校验插件包（12 条判据）。返回 (manifest | None, err)；err 为 "" 表示通过。

    host_version：宿主版本**字符串**（如桌宠.VERSION = "2.5.0"）。传空视为"宿主版本未知"，
    此时任何 min_host_version 都拒（fail-closed：宁可拒装，也不要装上一个不知道能不能跑的东西）。
    """
    try:
        zf = zipfile.ZipFile(path, "r")
    except zipfile.BadZipFile:
        return _fail("文件不是有效的 zip 包")
    except Exception as e:                      # 权限/加密/半截文件…
        return _fail("打开失败：%s" % e)
    with zf:
        # ---- 判据 1：容量上限（与角色包同一口径，防 zip 炸弹）----
        info = zf.infolist()
        if (len(info) > pet_export.EXPORT_MAX_ENTRIES
                or sum(i.file_size for i in info) > pet_export.EXPORT_MAX_BYTES):
            return _fail("插件包条目过多或体积过大，已拒绝")
        names = zf.namelist()
        # ---- 判据 2：manifest.json 存在 / 无 BOM / UTF-8 / 是 dict ----
        if MANIFEST_NAME not in names:
            return _fail("不是插件包：缺少 manifest.json")
        try:
            raw = zf.read(MANIFEST_NAME)
        except Exception as e:
            return _fail("manifest.json 读不出来：%s" % e)
        if raw[:3] == b"\xef\xbb\xbf":
            return _fail("manifest.json 带 UTF-8 BOM（必须无 BOM 的 UTF-8）")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            return _fail("manifest.json 不是 UTF-8：%s" % e)
        try:
            manifest = json.loads(text)
        except Exception as e:
            return _fail("manifest.json 无法解析：%s" % e)
        if not isinstance(manifest, dict):
            return _fail("manifest 不是对象")
        # ---- 判据 3：format / 包格式版本 / plugin 段 ----
        if manifest.get("format") != PLUGIN_FORMAT:
            return _fail("不是大肥鱼插件包（format=%r，应当是 %r）"
                         % (manifest.get("format"), PLUGIN_FORMAT))
        fmt_ver = manifest.get("version")
        if isinstance(fmt_ver, bool) or not isinstance(fmt_ver, int):
            return _fail("包格式 version 必须是 int（当前 %r）" % (fmt_ver,))
        if fmt_ver < 1 or fmt_ver > PLUGIN_FORMAT_VERSION:
            return _fail("插件包格式版本 %d 超出宿主支持（最高 %d）"
                         % (fmt_ver, PLUGIN_FORMAT_VERSION))
        meta = manifest.get("plugin")
        if not isinstance(meta, dict):
            return _fail("缺少 plugin 段（插件元数据必须写在 plugin 段里）")
        # payload 单根：缺省 "payload/"
        payload_root = manifest.get("payload_root", DEFAULT_PAYLOAD_ROOT)
        if payload_root is None or payload_root == "":
            payload_root = DEFAULT_PAYLOAD_ROOT
        if not isinstance(payload_root, str) or not payload_root.endswith("/"):
            return _fail("payload_root 必须是以 / 结尾的相对目录（当前 %r）" % (payload_root,))
        root_reason = _unsafe_name_reason(payload_root + "x")
        if root_reason:
            return _fail("payload_root 不合法：%s" % root_reason)
        # ---- 判据 4：全量 namelist 路径安全 + 单根 ----
        for n in names:
            reason = _unsafe_name_reason(n)
            if reason:
                return _fail("插件包含不安全的条目名（%s）：%r" % (reason, n))
            if n != MANIFEST_NAME and not n.startswith(payload_root):
                return _fail("插件包含 payload 之外的文件（必须单根 %s）：%s"
                             % (payload_root, n))
        # ---- 判据 5：外部属性（执行位 / 符号链接）----
        for i in info:
            reason = _external_attr_reason(i)
            if reason:
                return _fail("插件包含不安全的外部属性：%s" % reason)
        # ---- 判据 6：扩展名白名单（禁止项**点名文件**拒）----
        payload_files = _payload_files(names, payload_root)
        for n in payload_files:
            ext = os.path.splitext(n)[1].lower()
            if ext in FORBIDDEN_EXEC_EXTS:
                return _fail("插件包含禁止的可执行/脚本文件：%s" % n)
            if ext in FORBIDDEN_NESTED_EXTS:
                return _fail("插件包含禁止的嵌套压缩包：%s" % n)
            if ext not in ALLOWED_EXTS:
                return _fail("插件包含不在白名单里的文件类型：%s（只允许 %s）"
                             % (n, " ".join(sorted(ALLOWED_EXTS))))
        # ---- 判据 7：code 与 kind 一致 ----
        kind = meta.get("kind")
        if kind not in ("data", "ui"):
            return _fail("plugin.kind 不合法（当前 %r，只支持 \"data\"）" % (kind,))
        code = meta.get("code")
        if not isinstance(code, bool):
            return _fail("plugin.code 必须是 bool（当前 %r）" % (code,))
        if kind == "data" and code is not False:
            return _fail("kind=data 的插件必须 code=false（当前 %r）" % (code,))
        if kind != "data" and code is not True:
            return _fail("kind=%s 的插件必须 code=true（当前 %r）" % (kind, code))
        # ---- 判据 8：capabilities ⊆ CAPABILITIES ----
        caps = meta.get("capabilities", [])
        if caps is None:
            caps = []
        if not isinstance(caps, list) or any(not isinstance(c, str) for c in caps):
            return _fail("plugin.capabilities 必须是字符串列表（当前 %r）" % (caps,))
        over = sorted(set(caps) - CAPABILITIES)
        if over:
            return _fail("插件申请了宿主不支持的权限：%s（宿主白名单 %s）"
                         % ("、".join(over), " ".join(sorted(CAPABILITIES))))
        # ---- 判据 9：双版本门（min_host_version + api_version）----
        min_host = meta.get("min_host_version")
        if not isinstance(min_host, str) or not min_host.strip():
            return _fail("缺少 plugin.min_host_version（宿主无法判断兼容性）")
        # v2.5.1（找茬审查 S2-a）：版本串必须先"像个版本号"再比。version_key 只抽数字，
        # "abc"/"latest" 会被抽成 (0,0,0,0) 而**恒放行**（fail-open：写错版本号反而没人管）。
        # 这里 fail-closed：不是数字版本就直接拒。
        if not _is_version_like(min_host):
            return _fail("plugin.min_host_version 不是版本号：%r（要形如 2.5.0；"
                         "写错版本串的包一律拒绝，不按「无版本要求」放行）" % (min_host,))
        if version_key(min_host) > version_key(host_version):
            return _fail("插件要求宿主版本 ≥ %s，当前 %s（min_host_version 不满足，已拒绝）"
                         % (min_host.strip(), host_version or "未知"))
        api_version = meta.get("api_version")
        if isinstance(api_version, bool) or api_version not in API_VERSIONS:
            return _fail("插件 API 版本 %r 不受支持（宿主支持 %s）"
                         % (api_version, " ".join(str(v) for v in sorted(API_VERSIONS))))
        # ---- 判据 10：校验和（逐条 sha256 + bytes，且不多不少覆盖 payload）----
        # v2.5.1（找茬审查 S2-b）：**分块边读边算摘要**，不把整个 payload 读进内存
        # （旧实现 zf.read 全量进 texts 字典：实测峰值 ≈2.2× 内容体积，512MB 上限下 >1GB）；
        # 同时按**真实解压字节**再记一次总数——判据 1 只看中央目录声明的 file_size，
        # 那只是第一道闸，真实体积由这里兜底。
        cap = pet_export.EXPORT_MAX_BYTES
        digests = {}
        total_real = 0
        for n in payload_files:
            h = hashlib.sha256()
            size = 0
            try:
                with zf.open(n, "r") as src:
                    for chunk in iter(lambda: src.read(1024 * 1024), b""):
                        size += len(chunk)
                        total_real += len(chunk)
                        h.update(chunk)
            except Exception as e:
                return _fail("payload 条目读不出来（%s）：%s" % (n, e))
            if total_real > cap:
                return _fail("插件解压后的总体积超过上限（已读 %d 字节，上限 %d），已拒绝"
                             % (total_real, cap))
            digests[n] = (h.hexdigest(), size)
        bad = _files_problems(manifest.get("files"), payload_files, digests)
        if bad:
            return _fail("插件包校验和不对：%s" % "；".join(bad[:5]))
        # ---- 判据 11：data_kind 必须在 DATA_KINDS 里 ----
        if kind == "data":
            data_kind = meta.get("data_kind")
            if data_kind not in DATA_KINDS:
                return _fail("plugin.data_kind 不在支持范围（当前 %r，支持 %s）"
                             % (data_kind, " ".join(sorted(DATA_KINDS))))
        # ---- 判据 12：UI 插件本版本无条件拒绝 ----
        if kind == "ui":
            return _fail("本版本不支持 UI 插件（kind=ui 一律拒绝）")
        pid_problem = _id_problem(meta.get("id"))
        if pid_problem:
            return _fail(pid_problem)
        return manifest, ""


def _read_json(path):
    """读一个 JSON 文件 → (对象 | None, 原因)；**绝不抛**。BOM 容忍（只读展示用）。"""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f), ""
    except Exception as e:                      # 坏 JSON / 权限 / 半截文件…
        return None, "%s" % e


def _installed_index(plugins_dir, problems):
    """<plugins_dir>/_installed.json → {id: 记录}；坏文件只记问题、返回 {}。

    形状（宿主写、这里读）：{"format": "dfypet-plugins-installed", "version": 1,
    "plugins": {<id>: {"enabled": bool, "source_url": str, ...}}}；也容忍裸的 {id: {...}}。
    """
    path = os.path.join(plugins_dir, INSTALLED_INDEX_NAME)
    if not os.path.isfile(path):
        return {}
    data, why = _read_json(path)
    if data is None:
        problems.append("%s 读不出来，按\"全部未记录\"处理：%s" % (INSTALLED_INDEX_NAME, why))
        return {}
    if not isinstance(data, dict):
        problems.append("%s 不是对象，已跳过" % INSTALLED_INDEX_NAME)
        return {}
    raw = data.get("plugins")
    if raw is None:
        raw = data
    if not isinstance(raw, dict):
        problems.append("%s 的 plugins 段不是对象，已跳过" % INSTALLED_INDEX_NAME)
        return {}
    return {str(k): v for k, v in raw.items() if isinstance(v, dict)}


def _plugin_item(path, dir_name, record, problems):
    """一个插件目录 → 条目 dict；不是插件（缺/坏 manifest）→ None 并记问题。"""
    mpath = os.path.join(path, MANIFEST_NAME)
    if not os.path.isfile(mpath):
        problems.append("插件目录缺 manifest.json，已跳过：%s" % dir_name)
        return None
    data, why = _read_json(mpath)
    if data is None:
        problems.append("插件 %s 的 manifest.json 读不出来，已跳过：%s" % (dir_name, why))
        return None
    if not isinstance(data, dict):
        problems.append("插件 %s 的 manifest.json 不是对象，已跳过" % dir_name)
        return None
    meta = data.get("plugin")
    if not isinstance(meta, dict):
        problems.append("插件 %s 的 manifest.json 没有 plugin 段，已跳过" % dir_name)
        return None
    pid = meta.get("id")
    if not isinstance(pid, str) or not pid.strip():
        # 宿主安装时用的目录名就是 id（<plugins>/<id>/），manifest 缺 id 不致命
        pid = dir_name
    return {"id": pid,
            "name": str(meta.get("name") or pid),
            "version": meta.get("version", ""),
            "kind": str(meta.get("kind") or ""),
            "data_kind": str(meta.get("data_kind") or ""),
            "enabled": bool(record.get("enabled", True)),
            "source_url": str(record.get("source_url") or ""),
            "dir": os.path.abspath(path)}


def read_installed(plugins_dir):
    """只读扫描已安装插件 → (list[dict], list[str])；**坏目录/坏 JSON 只跳过并进问题串，绝不抛**。

    条目的 id/name/version/kind/data_kind 来自 <plugins_dir>/<id>/manifest.json 的 plugin 段，
    enabled/source_url 来自 <plugins_dir>/_installed.json（缺省 enabled=True、source_url=""）。
    目录不存在 → ([], [])。名字以 _ 或 . 开头的一律跳过（_download 临时目录、_installed.json），
    plugins/ 下的**保留名**（官方内容仓库：packs/、index.json、README.md）同样静默跳过
    ——它们本来就不是插件，报成"读不出来"只会误导用户（见 RESERVED_PLUGIN_NAMES）。
    """
    problems = []
    base = str(plugins_dir or "")
    if not base or not os.path.isdir(base):
        return [], []
    index = _installed_index(base, problems)
    try:
        entries = sorted(os.listdir(base))
    except OSError as e:
        problems.append("插件目录读不出来（%s）：%s" % (base, e))
        return [], problems
    out = []
    for name in entries:
        # v2.5.1（兼容审查 P2-2）：保留名**显式跳过**——packs/ 是官方内容包目录，
        # 它没有 manifest.json 是当然的，不该再报"读不出来"（用户会以为插件坏了）。
        if name.startswith(_SKIP_PREFIX) or is_reserved_plugin_name(name):
            continue
        path = os.path.join(base, name)
        if not os.path.isdir(path):
            continue                            # 普通文件：不是插件目录，跳过
        item = _plugin_item(path, name, index.get(name) or {}, problems)
        if item is None:
            continue
        # v2.5.1（找茬审查 第四优先）：目录名与 manifest 里的 plugin.id 不一致时（手工拷进来、
        # 后来改过 id 的包），登记表可能按**另一个**名字存（安装那一刻的 id）——只按目录名查
        # 会让 enabled/source_url 静默丢掉。按 manifest id 再回查一次兜底。
        if str(item.get("id") or "") != name:
            rec = index.get(str(item.get("id"))) or {}
            if rec:
                item["enabled"] = bool(rec.get("enabled", item.get("enabled", True)))
                item["source_url"] = str(rec.get("source_url") or item.get("source_url") or "")
        out.append(item)
    return out, problems
