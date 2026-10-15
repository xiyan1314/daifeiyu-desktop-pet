# -*- coding: utf-8 -*-
"""PetHub 插件索引下载器（v2.6.0 · Phase 2）：索引读取 / 下载 / 校验 / 交给安装器。

分工（各管一段，别把判据抄第二份）
----------------------------------
· 本模块：**取数与搬运**——读索引（随包本地那份 / 远端同一格式）、按索引解析 url、
  取字节、核对 sha256 与 bytes、写临时文件、交给 PluginHost；
· pet_plugin（Phase 0）：**唯一**的包判据（12 条）——下载后解包前**必须**再走一遍
  validate_plugin_zip，本模块绝不自己写第二套"这个包合不合法"的判断；
· pet_plugin_host（Phase 1）：落地（解包 / 并入宿主库 / 写安装登记）。

Qt-free：不 import Qt、不 import 桌宠.py，可无 GUI 单测；**取数一律注入**——
构造时传 fetch(url) -> (bytes | None, err)，测试永远注入假 fetch，绝不真联网。
默认实现 default_fetch 用 urllib（远端）或直接读文件（本地）。

索引格式（plugins/index.json，远端同一格式）
--------------------------------------------
    {"index_version": 1, "updated_at": "...", "host_min": "2.5.1",
     "plugins": [{"id", "name", "kind", "data_kind", "code", "summary", "author",
                  "releases": [{"version", "min_host_version", "api_version",
                                "url", "sha256", "bytes", "published_at"}]}]}

**base_url 口径**（沿用打包工具 --base-url 那套，两处必须一致）：
release.url 是**相对索引自己所在位置**的路径，也可能是绝对 http(s) 地址。
· 远端索引 https://host/dir/index.json + "packs/x.zip" → https://host/dir/packs/x.zip；
· 随包本地索引 <程序目录>/plugins/index.json + "packs/x.zip" → 同目录的 packs/x.zip
  （= **随包出货的那份本地副本**，不联网也装得上）。
远端与本地走**同一个解析函数** resolve_url，没有第二条口径。

版本与可装性
------------
版本比较一律走 pet_plugin.version_key（与 _check_release._ver_key 同款的四段整数比较，
漂了由 tests/test_plugin_v251.py 那条逐样本对齐的用例钉住）。条目的 host_min /
min_host_version 高于宿主时，条目**标为不可装并给出人话原因**，不静默隐藏
（见 _entry_state 的 reasons 顺序）。

失败不留残余
------------
下载走 <plugins>/_download/（和安装器的 .tmp-* 一样是宿主自己的临时区，
读取侧按保留名跳过），原子写用 pet_io.atomic_write_bytes；**任何一步失败都删掉
本次写下的临时文件**，连本次新建的空目录也撤掉（_cleanup_dirs）。
"""
import hashlib
import inspect
import json
import os
import re
import time
import urllib.parse
import urllib.request

import pet_export   # 容量上限**单一来源**（索引与包同一口径，防索引炸弹）
import pet_io       # 全仓共用：原子写（线程里写盘也走它）
import pet_log      # v2.8.0：缓存/索引读不出来的**留痕**（pet_log 无依赖，安全）
import pet_plugin   # Phase 0 校验器 + 版本比较（本模块只调它，不抄判据）

INDEX_NAME = "index.json"
DOWNLOAD_DIRNAME = "_download"
# ---------------- v2.8.0 · Phase 3：远端索引的配置键与本地缓存 ----------------
# · 键名的**字面量**只在这里写一次，pet_config.PLUGIN_INDEX_URL_KEY 直接再导出它（不抄第二份）；
# · 远端索引取回来后落地成 <plugins>/index.remote.json —— **绝不覆盖随包 index.json**：
#   那份是出货资产，也是"远端挂了 / 没网"时官方内容照样装得上的退路。
PLUGIN_INDEX_URL_KEY = "plugin_index_url"
# 缓存放 <plugins>/_index_cache/ 里，与 _download/ 同一个套路：
#   · 读取侧（pet_plugin.read_installed）对 "_" 开头的名字**显式跳过**，不会报成坏插件；
#   · .gitignore 里 plugins/*/ 本来就忽略这类运行时目录 → 刷新一次不会把工作树弄脏
#     （发布门会看 git status，也会看发布包里有没有混进用户数据）。
REMOTE_CACHE_DIRNAME = "_index_cache"
REMOTE_CACHE_NAME = "index.remote.json"
REMOTE_CACHE_FORMAT = 1
REMOTE_BASE_MAX_LEN = 2048      # 地址本身不许长到离谱（配置被手改成巨型串时当场拒）
# 索引格式版本：比这更新的索引一律拒（fail-closed——看不懂的索引不许当成"没有新版本"）
INDEX_VERSION = 1
# 索引本体的体积上限：索引只是一个清单，超过这个数一定是坏东西
INDEX_MAX_BYTES = 4 * 1024 * 1024
FETCH_CHUNK = 64 * 1024
FETCH_TIMEOUT = 20
USER_AGENT = "daifeiyu-desktop-pet-plugin-index/1"

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_BAD_NAME_RE = re.compile(r"[^A-Za-z0-9._-]")


def is_remote(url):
    """url 是不是 http(s) 远端地址（其余一律当本地路径）。"""
    return str(url or "").strip().lower().startswith(("http://", "https://"))


def is_insecure_remote(url):
    """url 是不是**明文 http** 的远端地址（v2.6.0 · 找茬审查 P2-a）。

    刻意与 is_remote 分开：is_remote 回答"这是不是远端"（测试的"永不上网"守卫靠它），
    is_insecure_remote 回答"这条远端链路安不安全"。混成一个会让 http 地址被判成
    "本地路径"——那正好是"以为在读文件、其实在联网"的经典写法。
    """
    return str(url or "").strip().lower().startswith("http://")


def insecure_reason(target):
    """明文 http 的远端地址 → 拒绝理由（"" = 这条地址可以用）。

    v2.6.0（找茬审查 P2-a）：远端只收 **https**。索引与包**同源**（sha256 / bytes 都写在
    索引里），明文链路上这套完整性保护等于零：中间人可以同时换掉索引与包，两边哈希照样
    对得上。本版 plugin_index_url 还没有配置入口（远端整条链生产不可达，见
    _dev/plugin_market_report_v260.md），先把判据硬化好，下一轮接线时不必回头改这里。
    """
    if is_insecure_remote(target):
        return ("远端地址必须是 https（明文 http 上的 sha256 拦不住中间人——索引与包会被一起换掉），"
                "已拒绝取数：%s" % str(target or "").strip())
    return ""


def _safe_urlsplit(text):
    """urlsplit 的**绝不抛**版本（坏地址不该把"校验 / 读索引 / 刷新"整条打断）。

    实测（找茬审查 F2 同批）：`https://[abc/x.json` 这类手改配置会让 urlsplit 抛
    ValueError（Invalid IPv6 URL）——而校验函数是给界面**当场调用**的（调用方没有 try），
    抛出去就成了"点了没反应"。解析不了 → None，调用方按"这个地址不合法"处理。
    """
    try:
        return urllib.parse.urlsplit(str(text or ""))
    except ValueError as e:
        pet_log.log_throttled("plugin_index.urlsplit", "索引地址解析不了（按非法处理）：%r" % (e,))
        return None


def remote_base_reason(url):
    """**配置里的远端基址**（plugin_index_url）→ 拒绝理由（"" = 可以用）。

    v2.8.0 · Phase 3：与 resolve_url 的条目判据同源——远端只收 https；本地路径 / file://
    一律拒（配置里写 C:\\packs 与写在索引条目里是同一件事：远端信任域不许接上本机文件系统）。
    空串**不算错**（空串 = 清除远端、回到随包索引），由调用方按"有没有内容"分开处理。
    """
    text = str(url or "").strip()
    if not text:
        return "索引地址是空的（要回到随包索引，请用空地址清除）"
    if len(text) > REMOTE_BASE_MAX_LEN:
        return "索引地址太长（%d 个字符，最多 %d）" % (len(text), REMOTE_BASE_MAX_LEN)
    bad = insecure_reason(text)
    if bad:
        return bad
    low = text.lower()
    if low.startswith("file:") or _DRIVE_RE.match(text) or text.startswith(("\\\\", "/")) \
            or os.path.isabs(text):
        return ("远端索引地址必须是 https 链接（本地路径 / file:// 不行——远端索引是别人给的清单，"
                "不许指挥桌宠读本机文件）：%s" % text)
    if not low.startswith("https://"):
        return "远端索引地址只收 https 链接（当前：%s）" % text
    # F2（找茬审查）：判据是 **hostname**，不是 netloc —— `https://:8443/x.json`、
    # `https://user@/x.json`、`https://@/x.json` 这几形的 netloc **非空**（":8443" / "user@"），
    # 真值判据会把它们放行并写进配置（实测 6 个同形地址全过），而它们的 hostname 都是 None。
    parts = _safe_urlsplit(text)
    if parts is None:
        return "远端索引地址不是合法地址（解析不了）：%s" % text
    if not parts.hostname:
        return "远端索引地址缺少主机名：%s" % text
    return ""


def index_url_of(base):
    """配置里的基址 → **真正要取**的索引地址（两种填法都认，不逼用户背口径）。

      · 以 .json 结尾 → 原样（真源就是它自己，例如官方仓库的 .../plugins/index.json）；
      · 其余当**目录**，拼上 index.json（https://host/dir → https://host/dir/index.json）；
      · 带查询串 / 锚点的地址原样用（往它后面拼路径只会把它拼坏）。
    """
    text = str(base or "").strip()
    if not text:
        return ""
    parts = _safe_urlsplit(text)
    if parts is None:
        return text                  # 解析不了：原样交出去（判据会拒；取数那边给人话错误）
    if parts.query or parts.fragment:
        return text
    if parts.path.lower().endswith(".json"):
        return text
    return text.rstrip("/") + "/" + INDEX_NAME


def _file_url_to_path(url):
    """file:// URL → 本机路径（v2.6.0 · 找茬审查 P3-3）。

    老口径是裸的 url[7:]：file:///C:/x 得到 "/C:/x" —— URL 口径的路径，在 Windows 上
    既不是合法绝对路径（os.path.isabs 为 False），也不是用户以为的那个文件。
    url2pathname 是标准库给的同一件事（/C:/x → C:\\x）。**绝不抛**：索引是外部数据，
    解析不了就退回老口径——不能让它把"读索引"整条打断。
    """
    tail = url[7:]
    try:
        if tail[:1] == "/" and _DRIVE_RE.match(tail[1:]):
            tail = tail[1:]                 # /C:/x → C:/x（URL 口径 → 本机口径）
        return urllib.request.url2pathname(tail) or tail
    except Exception:
        return tail


def _rel_url_reason(rel):
    """相对 url → 人话原因（"" = 可以拼）；口径**复用** pet_plugin._unsafe_name_reason。

    v2.6.0（找茬审查 P3-2）：此前相对分支只做 if p 丢空段，".." 原样进 os.path.join ——
    "../../..//evil.zip" 能把取数目标指到索引目录之外（随包索引就是"随包目录之外"）。
    校验器那边（包判据）早就有这条判据，这里借同一份实现，不抄第二套。
    """
    return pet_plugin._unsafe_name_reason(str(rel or "").replace("\\", "/"))


def resolve_url(raw, base=""):
    """索引里的 url → (kind, target)；解析不了 → (None, 原因)。

    kind ∈ {"http", "file"}；base 是**索引自己的位置**（本地 index.json 的绝对路径，
    或远端 index.json 的 URL）。相对路径按 base 解析；绝对 http(s) 与绝对本地路径原样用。

    信任边界（v2.6.0 · 找茬审查 P2-a / P2-b）：
      · 远端只收 **https**（insecure_reason），明文 http 一律拒；
      · **索引来源是远端时**，条目里的 url 不许指向本地（file:// / 盘符 / 绝对路径）——
        远端索引若能指挥宿主读本机文件，就把"远端信任域"和"本机文件系统"接上了。
        随包本地索引不受这条限制（它本来就是本机自己的文件）。
    """
    url = str(raw or "").strip()
    if not url:
        return None, "索引里的 url 是空的"
    base = str(base or "").strip()
    base_remote = is_remote(base)
    if is_remote(url):
        bad = insecure_reason(url)
        if bad:
            return None, bad
        return "http", url
    if url.lower().startswith("file://") or _DRIVE_RE.match(url) or os.path.isabs(url):
        if base_remote:
            return None, ("远端索引指向了本地路径（跨信任域，拒绝）：%s" % url)
        if url.lower().startswith("file://"):
            return "file", _file_url_to_path(url)
        return "file", url
    if not base:
        return None, "索引没有给出位置，无法解析相对地址：%s" % url
    why = _rel_url_reason(url)              # v2.6.0（P3-2）：.. / 空段 / 保留名一律拒
    if why:
        return None, "相对地址不合法（%s）：%s" % (why, url)
    if base_remote:
        joined = urllib.parse.urljoin(base, url)
        bad = insecure_reason(joined)
        if bad:
            return None, bad
        return "http", joined
    head = base if os.path.isdir(base) else os.path.dirname(base)
    if not head:
        return None, "索引路径不完整，无法解析相对地址：%s" % url
    return "file", os.path.join(head, *[p for p in url.replace("\\", "/").split("/") if p])


def _byte_cap(limit):
    """本次取数的硬上限：给了正数就用它，否则退全仓容量上限（pet_export.EXPORT_MAX_BYTES）。"""
    if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0:
        return min(limit, pet_export.EXPORT_MAX_BYTES)
    return pet_export.EXPORT_MAX_BYTES


def default_fetch(url, progress=None, limit=0):
    """默认取数：http(s) 走 urllib（分块读，边读边报进度），本地路径直接读文件。

    返回 (bytes | None, err)。**绝不抛**：网络/权限/半截文件都折成一句人话。
    progress(done, total)：可选进度回调（total=0 表示对端没给长度）。
    limit：本次最多接受多少字节（<=0 = 只受 pet_export.EXPORT_MAX_BYTES 约束）。

    v2.6.0（找茬审查 P2-c）：上限**边读边判**，不是"先整份读进内存、读完再比大小"——
    本地分支此前是 f.read() 一次读完再判（一个 4 MB 的坏索引会整份进内存才被拒），
    远端分支虽然分块，但对端自报的 Content-Length 也没用上。现在：
      · 本地：分块读 + 累计，越界立刻停手；
      · 远端：先看 Content-Length（自己就说超了 → 一个字节都不读），再分块累计。

    注入的 fetch 契约仍是 fetch(url)（见模块说明）；**能收 limit 关键字**的实现会被
    多传一个（_call_* 系列问一次签名，老契约不受影响）。
    """
    target = str(url or "")
    if not target:
        return None, "取数地址是空的"
    cap = _byte_cap(limit)
    if not is_remote(target):
        try:
            chunks, done = [], 0
            with open(target, "rb") as f:
                while True:
                    chunk = f.read(FETCH_CHUNK)
                    if not chunk:
                        break
                    done += len(chunk)
                    if done > cap:
                        return None, "取数内容超过上限（已读 %d 字节，上限 %d）——已丢弃" % (done, cap)
                    chunks.append(chunk)
            data = b"".join(chunks)
        except Exception as e:
            return None, "读取本地文件失败：%s" % e
        if progress is not None:
            progress(len(data), len(data))
        return data, ""
    try:
        req = urllib.request.Request(target, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            try:
                total = int(resp.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                total = 0
            if total and total > cap:           # 前置：对端自己就说超了，不必读回来再判
                return None, ("取数内容超过上限（对端自报 %d 字节，上限 %d）——已丢弃"
                              % (total, cap))
            chunks, done = [], 0
            while True:
                chunk = resp.read(FETCH_CHUNK)
                if not chunk:
                    break
                done += len(chunk)
                if done > cap:
                    return None, "取数内容超过上限（已读 %d 字节，上限 %d）——已丢弃" % (done, cap)
                chunks.append(chunk)
                if progress is not None:
                    progress(done, total)
            return b"".join(chunks), ""
    except Exception as e:                      # URLError / HTTPError / 超时 / SSL…
        return None, "网络请求失败：%s" % e


def _accepts_limit(fn):
    """fn 能不能收 limit=<int>（v2.6.0 · 找茬审查 P2-c）。

    注入取数的老契约是 fetch(url)；上限要前置就得能传下去，但又不能把老契约的注入实现
    （含测试里的守卫版 default_fetch）打红，所以问一次签名：问不出来 / 没有这个参数
    → 按老契约办（最保守的那个答案）。
    """
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):             # 内建 / C 实现拿不到签名：当它不收
        return False
    if "limit" in params:
        return True
    return any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())


def _call_default_fetch(target, progress, limit):
    """调本模块的 default_fetch（**可能被测试换成两参的守卫版**）：收 limit 才多传一个。"""
    if _accepts_limit(default_fetch):
        return default_fetch(target, progress, limit=limit)
    return default_fetch(target, progress)


def _call_injected_fetch(fn, target, limit):
    """调注入的取数：契约是 fetch(url)；只有它自己声明收 limit 时才多传一个。"""
    if _accepts_limit(fn):
        return fn(target, limit=limit)
    return fn(target)


def sha256_bytes(data):
    """bytes 的 sha256（hex）。"""
    return hashlib.sha256(data or b"").hexdigest()


def format_size(num):
    """字节数 → 给人看的大小（"165 KB"）。非数字/负数 → "-"。"""
    try:
        n = int(num)
    except (TypeError, ValueError):
        return "-"
    if n < 0:
        return "-"
    if n < 1024:
        return "%d B" % n
    kb = n / 1024.0
    if kb < 1024:
        return "%.0f KB" % kb if kb >= 10 else "%.1f KB" % kb
    return "%.1f MB" % (kb / 1024.0)


def _safe_filename(text, fallback="pack"):
    """索引里的 id / 文件名 → 只含 [A-Za-z0-9._-] 的文件名（拼路径前必须过这一道）。"""
    name = _BAD_NAME_RE.sub("_", str(text or "").strip())[:80].strip("._")
    return name or fallback


def _version_reason(raw, what):
    """版本串是否"像个版本号"（与校验器同一口径；不懂的版本串一律拒，不按 0 放行）。"""
    if not isinstance(raw, str) or not raw.strip():
        return "%s 缺失" % what
    if not pet_plugin._is_version_like(raw):
        return "%s 不是版本号：%r" % (what, raw)
    return ""


def _release_problem(item, base):
    """一条 release 的形状判据 → 人话原因（""=过）+ 归一结果。"""
    if not isinstance(item, dict):
        return "releases 里有一项不是对象"
    reason = _version_reason(item.get("version"), "release.version")
    if reason:
        return reason
    reason = _version_reason(item.get("min_host_version"), "release.min_host_version")
    if reason:
        return reason
    api_version = item.get("api_version")
    if isinstance(api_version, bool) or api_version not in pet_plugin.API_VERSIONS:
        return "release.api_version %r 不受支持" % (api_version,)
    sha = str(item.get("sha256") or "").strip()
    if not _SHA256_RE.match(sha):
        return "release.sha256 不是 64 位十六进制（没有校验和的包一律不下载）"
    size = item.get("bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        return "release.bytes 必须是 >= 0 的整数"
    if size > pet_export.EXPORT_MAX_BYTES:
        return "release.bytes %d 超过宿主容量上限" % size
    kind, target = resolve_url(item.get("url"), base)
    if kind is None:
        return target
    return ""


def _release_of(item, base):
    """一条 release → 归一形状（含解析好的 (kind, target)）；形状不合法 → (None, 原因)。"""
    reason = _release_problem(item, base)
    if reason:
        return None, reason
    kind, target = resolve_url(item.get("url"), base)
    return {"version": str(item.get("version")).strip(),
            "min_host_version": str(item.get("min_host_version")).strip(),
            "api_version": item.get("api_version"),
            "url": str(item.get("url") or "").strip(),
            "sha256": str(item.get("sha256")).strip().lower(),
            "bytes": int(item.get("bytes")),
            "published_at": str(item.get("published_at") or ""),
            "source": (kind, target)}, ""


def _newest(releases):
    """按四段整数版本取最新的一条（同版本取先出现的，稳定）。"""
    best = None
    for rel in releases:
        if best is None or pet_plugin.version_key(rel["version"]) > \
                pet_plugin.version_key(best["version"]):
            best = rel
    return best


def _entry_state(item, base, host_version, landing_kinds, index_reason=""):
    """索引条目 → 归一形状 + **选中版本** + 可装性（不可装必须给得出人话原因）。

    reasons 的**顺序**是有意的：先说"整份索引都不行"，再说"这一类插件不行"，
    最后才是"这一版不行"——用户看到的永远是**最上游**的那个原因。
    """
    raw_releases = item.get("releases")
    raw_releases = raw_releases if isinstance(raw_releases, list) else []
    releases, bad = [], []
    for one in raw_releases:
        rel, why = _release_of(one, base)
        if rel is None:
            bad.append(why)
        else:
            releases.append(rel)
    pid = str(item.get("id") or "").strip()
    name = str(item.get("name") or pid or "(未命名)")
    kind = str(item.get("kind") or "")
    data_kind = str(item.get("data_kind") or "")
    best = _newest(releases)
    reasons = []
    if index_reason:
        reasons.append(index_reason)
    id_problem = pet_plugin._id_problem(pid)
    if id_problem:
        reasons.append(id_problem)
    if kind != "data":
        reasons.append("本版本只装数据插件（索引里是 kind=%r）" % (kind or "(缺)"))
    elif item.get("code") is not False:
        reasons.append("数据插件必须 code=false（索引里是 %r）" % (item.get("code"),))
    if data_kind not in tuple(landing_kinds):
        reasons.append("本版本不支持落地「%s」类插件" % (data_kind or "(缺)"))
    if not releases:
        reasons.append("索引里没有可用的版本（%s）" % ("；".join(bad[:2]) if bad else "releases 是空的"))
    if best is not None and pet_plugin.version_key(best["min_host_version"]) > \
            pet_plugin.version_key(host_version):
        reasons.append("需要宿主 ≥ %s，当前 %s" % (best["min_host_version"],
                                                  host_version or "未知"))
    return {"id": pid, "name": name, "kind": kind, "data_kind": data_kind,
            "summary": str(item.get("summary") or ""),
            "author": str(item.get("author") or ""),
            "code": item.get("code"),
            "releases": releases,
            "release": best,
            "installable": not reasons,
            "reason": "；".join(reasons),
            "version": best["version"] if best else "",
            "bytes": best["bytes"] if best else 0,
            "size_text": format_size(best["bytes"]) if best else "-",
            "source": list(best["source"]) if best else None,
            "url": best["url"] if best else "",
            "broken_releases": bad}


def parse_index(data, base="", host_version="", landing_kinds=None):
    """索引对象 → 归一索引（含 entries / problems）→ (index | None, err)。

    err 非空 = **整份索引用不了**（不是 dict / index_version 太新 / plugins 不是列表）；
    条目级的问题不在这里拒——它们进 entries（不可装 + 原因）或 problems（读不出来）。
    """
    if not isinstance(data, dict):
        return None, "索引不是 JSON 对象"
    version = data.get("index_version")
    if isinstance(version, bool) or not isinstance(version, int):
        return None, "索引缺少 index_version（int）"
    if version > INDEX_VERSION:
        return None, ("索引格式版本 %d 超出宿主支持（最高 %d）：请升级桌宠"
                      % (version, INDEX_VERSION))
    items = data.get("plugins")
    if not isinstance(items, list):
        return None, "索引缺少 plugins 列表"
    host_min = str(data.get("host_min") or "")
    index_reason = ""
    if host_min and pet_plugin.version_key(host_min) > pet_plugin.version_key(host_version):
        # 整份索引都要求更高的宿主：**逐条**标成不可装并说明原因，绝不静默隐藏
        index_reason = "索引要求宿主 ≥ %s，当前 %s" % (host_min, host_version or "未知")
    kinds = tuple(landing_kinds) if landing_kinds else tuple(pet_plugin.DATA_KINDS)
    entries, problems = [], []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            problems.append("plugins[%d] 不是对象，已跳过" % i)
            continue
        entry = _entry_state(item, base, host_version, kinds, index_reason)
        if not entry["id"]:
            # 没有 id 的条目照样列出来（用户能看到"索引坏了"），只是不可装
            entry["id"] = "index-entry-%d" % i
            entry["installable"] = False
            entry["reason"] = "索引条目缺少 id" + ("；" + entry["reason"] if entry["reason"] else "")
        entries.append(entry)
    return {"index_version": version,
            "updated_at": str(data.get("updated_at") or ""),
            "host_min": host_min,
            "base": str(base or ""),
            "problems": problems,
            "entries": entries}, ""


def _index_facts(raw):
    """索引原始对象 → (updated_at, 插件条目数)；读不出来就是 ("", 0)。

    只给**界面显示**用（不校验、不归一）：判据仍然只有 parse_index 那一份。
    """
    if not isinstance(raw, dict):
        return "", 0
    items = raw.get("plugins")
    return str(raw.get("updated_at") or ""), (len(items) if isinstance(items, list) else 0)


class PluginIndex(object):
    """一个插件目录（= 一套已装插件）对应的索引读取 / 下载器。

    plugins_dir：<数据目录>/plugins（随包的 index.json 与 _download/ 都在它下面）；
    fetch：注入式取数 fetch(url) -> (bytes | None, err)，缺省用 default_fetch（urllib）；
    index_url：远端索引地址；空 = 只读**随包**的本地索引（离线也装得上官方内容）；
    host_version：宿主版本字符串（与校验器同一口径）；landing_kinds：可落地的类别
    （缺省 = 校验器的 DATA_KINDS；对话框传 pet_plugin_host.LANDING_KINDS，界面才与安装器一致）。
    """

    def __init__(self, plugins_dir="", *, fetch=None, index_url="", host_version="",
                 landing_kinds=None, progress=None, log=None,
                 cfg_getter=None, save_cfg=None):
        self._plugins_dir = str(plugins_dir or "")
        self._fetch = fetch
        self._index_url = str(index_url or "")
        self._host_version = str(host_version or "")
        self._kinds = tuple(landing_kinds) if landing_kinds else tuple(pet_plugin.DATA_KINDS)
        self._progress = progress
        self._log = log
        # v2.8.0 · Phase 3：配置读写**注入**（cfg_getter() -> dict、save_cfg(cfg) -> None|错误串）。
        # 只给 set_remote_base 用：本模块 Qt-free，所以绝不 import 桌宠.py / pet_config.py。
        # 不注入也能用（只读索引 / 刷新 / 下载都不需要它们），只是 set_remote_base 会如实报
        # "没接线"，而不是假装存下了（v2.7.0 的 (ok, msg) 口径）。
        self._cfg_getter = cfg_getter
        self._save_cfg = save_cfg

    # ---------- 路径 ----------
    @property
    def plugins_dir(self):
        return self._plugins_dir

    @property
    def local_index_path(self):
        """**随包**的索引路径（<plugins>/index.json）。"""
        return os.path.join(self._plugins_dir, INDEX_NAME) if self._plugins_dir else ""

    @property
    def download_dir(self):
        return (os.path.join(self._plugins_dir, DOWNLOAD_DIRNAME)
                if self._plugins_dir else "")

    @property
    def index_url(self):
        """远端索引地址（空 = 只读**随包**的本地索引；界面按它决定走不走后台线程）。"""
        return self._index_url

    @property
    def remote_cache_path(self):
        """远端索引的本地缓存路径（<plugins>/_index_cache/index.remote.json）；没接线时是空串。"""
        return (os.path.join(self._plugins_dir, REMOTE_CACHE_DIRNAME, REMOTE_CACHE_NAME)
                if self._plugins_dir else "")

    def _note(self, text):
        """尽力记一条日志（没接线就不记；日志原语自己保证不抛）。"""
        if self._log is not None:
            self._log(text)

    # ---------- 读索引 ----------
    def load_index(self):
        """读索引 → (归一索引 | None, err)。**只读本地**：联网的边界只在 refresh() 一处。

        远端模式下的取数顺序（v2.8.0 · Phase 3）：
          ① 本地缓存 <plugins>/index.remote.json 命中（同一个地址留下的、格式认识）→ 用它；
          ② 没缓存但**注入了 fetch** 的实现 → 仍按老口径去取远端（测试 / 嵌入方驱动整条远端链）；
          ③ 生产口径（没注入 fetch）→ **绝不联网**：退回随包索引，并在 source 里如实写明
             "远端还没取回来"（界面照实显示，不假装远端索引就是这一份）。
        没有远端地址时与接线前**逐位一致**：读 <plugins>/index.json。
        """
        if self._index_url:
            bad = insecure_reason(self._index_url)
            if bad:                     # v2.6.0（P2-a）：远端索引本身也只收 https
                return None, bad
            cached = self._read_cache(self._index_url)
            if cached is not None:
                return self._index_from_cache(cached)
            if self._fetch is None:
                fallback, ferr = self._bundled_index_with_note()
                if fallback is not None:
                    return fallback, ""
                return None, ("远端索引还没取回来（点「刷新索引」）；%s"
                              % (ferr or "随包索引也读不出来"))
            data, err = self._fetch_bytes(index_url_of(self._index_url), None, INDEX_MAX_BYTES)
            base = index_url_of(self._index_url)
            source = "远端索引"
        else:
            path = self.local_index_path
            if not path:
                return None, "插件目录不可用（宿主未接线），读不了索引"
            data, err = self._fetch_bytes(path, None, INDEX_MAX_BYTES)
            base = os.path.abspath(path)
            source = "随包索引"
        if data is None:
            return None, err or "索引读不出来"
        # v2.6.0（P2-c）：这条仍是**唯一**的判据（取数那边的上限只是提前止损，
        # 注入的 fetch 未必收 limit）——上限前置不等于事后可以不判。
        if len(data) > INDEX_MAX_BYTES:
            return None, "索引文件过大（%d 字节，上限 %d）" % (len(data), INDEX_MAX_BYTES)
        try:
            text = data.decode("utf-8-sig")
            raw = json.loads(text)
        except Exception as e:
            return None, "索引不是合法的 UTF-8 JSON：%s" % e
        index, perr = parse_index(raw, base, self._host_version, self._kinds)
        if index is None:
            return None, perr
        index["source"] = source
        index["base"] = base
        return index, ""

    def _index_from_cache(self, cached):
        """缓存里的远端索引 → (归一索引 | None, err)；source 里写明它是缓存。"""
        index, perr = parse_index(cached.get("index"), str(cached.get("source_url") or ""),
                                  self._host_version, self._kinds)
        if index is None:
            return None, ("远端索引缓存用不了（%s）——点「刷新索引」重新取一次"
                          % (perr or "原因未知"))
        index["source"] = "远端索引（本地缓存）"
        index["base"] = str(cached.get("source_url") or "")
        index["fetched_at"] = str(cached.get("fetched_at") or "")
        return index, ""

    def _bundled_index_with_note(self):
        """随包索引（远端模式没缓存时的退路）→ (归一索引 | None, err)，source 写明为什么退回。

        借一个"没有远端地址"的同款实例读同一份文件：随包索引的读法与判据**只此一份**，
        绝不在这里抄第二套"读 index.json"的代码（抄第二套 = 早晚两处口径漂开）。
        """
        plain = PluginIndex(self._plugins_dir, fetch=self._fetch, index_url="",
                            host_version=self._host_version, landing_kinds=self._kinds,
                            progress=self._progress, log=self._log)
        index, err = plain.load_index()
        if index is None:
            return None, err
        index["source"] = "随包索引（远端索引还没取回来：点「刷新索引」）"
        return index, ""

    # ---------- v2.8.0 · Phase 3：远端索引（配置 / 刷新 / 来源） ----------
    def set_remote_base(self, url):
        """校验并保存 / 清除远端基址 → (ok, msg)。空串 = 回到随包索引。

        写盘走注入的 save_cfg（桌宠.save_config），且**先写盘、成功才改内存**——
        与 AIService.apply_settings 同一口径：失败时内存里一个字符都不动，也不假装存下了。
        校验走 remote_base_reason（与索引条目的取数判据同源：只收 https、不接本机路径）。
        """
        text = str(url or "").strip()
        if text:
            bad = remote_base_reason(text)
            if bad:
                return False, bad
        if self._cfg_getter is None or self._save_cfg is None:
            return False, ("索引地址没有接线（构造 PluginIndex 时要传 cfg_getter / save_cfg）——"
                           "这次改动一个字节都没落盘")
        try:
            cfg = self._cfg_getter()
        except Exception as e:
            pet_log.log_throttled("plugin_index.set_remote_base.read",
                                  "读配置失败：%r" % (e,))
            return False, "读配置失败：%r" % (e,)
        if not isinstance(cfg, dict):
            return False, "读回来的配置不是 dict，没法保存索引地址"
        new = dict(cfg)                     # 先改副本（失败时内存不变）
        new[PLUGIN_INDEX_URL_KEY] = text
        try:
            err = self._save_cfg(new)
        except Exception as e:
            pet_log.log_throttled("plugin_index.set_remote_base.save",
                                  "写配置异常：%r" % (e,))
            err = "配置写盘异常：%r" % (e,)
        if err is False or (isinstance(err, str) and err.strip()):
            why = err if isinstance(err, str) and err.strip() else "落盘回调报了失败"
            self._note("plugin_index.set_remote_base 写配置失败：%s" % (why,))
            return False, "索引地址没能保存：%s（盘上还是原值，这次改动没有生效）" % (why,)
        cfg.update(new)                     # 写盘成功才提交进内存（键顺序与原地写逐位相同）
        self._index_url = text
        if not text:
            self._drop_cache()              # 回随包索引：连这份缓存一起清（免得换个地址后串味）
            return True, "已恢复为随包索引（%s，不联网）" % INDEX_NAME
        return True, "已改用远端索引：%s（点「刷新索引」取回列表）" % text

    def refresh(self, force=False):
        """取远端 index.json → 校验 → 落地成本地缓存 → (ok, msg, count)。

        **本模块唯一联网的一处**（联网也只经注入的 fetch；没注入时才用 default_fetch）。
        失败一律 (False, 人话原因, 0)，而且**磁盘上原有的缓存与随包索引一个字节都不动**：
        刷新失败永远不破坏"东西还装得上"这件事（这就是"可回退"的物证）。
        force=False：已有同一个地址留下的可用缓存就直接用它（不联网）；force=True 无条件重取。
        count = 索引里**列出**的插件条目数（可安装几个由 msg 说清）。
        """
        base = self._index_url
        if not base:
            return False, "当前用的是随包索引（没有设置远端地址），没有可刷新的远端索引", 0
        bad = insecure_reason(base)
        if bad:
            return False, bad, 0
        target = index_url_of(base)
        if not force:
            cached = self._read_cache(base)
            if cached is not None:
                index, perr = self._index_from_cache(cached)
                if index is not None:
                    return True, ("远端索引已是本地缓存里这一份（取回于 %s，共 %d 个插件）"
                                  % (cached.get("fetched_at") or "未知时间",
                                     len(index["entries"]))), len(index["entries"])
                self._note("plugin_index.refresh 缓存用不了，改为重新取数：%s" % (perr,))
        data, err = self._fetch_bytes(target, self._progress, INDEX_MAX_BYTES)
        if data is None:
            return False, err or "远端索引取数失败", 0
        if len(data) > INDEX_MAX_BYTES:     # 上限前置只是止损；这条事后判据仍是唯一口径
            return False, ("远端索引过大（%d 字节，上限 %d）"
                           % (len(data), INDEX_MAX_BYTES)), 0
        try:
            raw = json.loads(data.decode("utf-8-sig"))
        except Exception as e:
            pet_log.log_throttled("plugin_index.remote_json",
                                  "远端索引不是合法的 UTF-8 JSON：%r" % (e,))
            return False, "远端索引不是合法的 UTF-8 JSON：%s" % e, 0
        index, perr = parse_index(raw, target, self._host_version, self._kinds)
        if index is None:
            return False, "远端索引用不了：%s" % (perr or "原因未知"), 0
        werr = self._write_cache(target, raw)
        if werr:
            return False, "远端索引取回来了，但本地缓存写盘失败：%s" % werr, 0
        entries = index["entries"]
        ready = len([one for one in entries if one.get("installable")])
        return True, ("远端索引已更新（共 %d 个插件，其中 %d 个可安装）"
                      % (len(entries), ready)), len(entries)

    def source_info(self):
        """界面显示用的来源信息 → {"kind": "bundled"|"remote", "url": str, "updated_at": str}。

        额外键都是**只读事实**，界面可用可不用：index_url（真正取数的地址，配置是目录时
        会补上 index.json）、cache_path、fetched_at（本地取回时间）、count、cached。
        **只读本地、不联网**（联网的边界只在 refresh）：远端模式下 url 是配置值，updated_at
        取本地缓存里那份索引自报的更新时间；随包模式取随包索引自报的时间。
        """
        base = self._index_url
        info = {"kind": "remote" if base else "bundled", "url": base,
                "index_url": index_url_of(base), "updated_at": "",
                "cache_path": self.remote_cache_path, "fetched_at": "",
                "count": 0, "cached": False}
        if base:
            cached = self._read_cache(base)
            if cached is not None:
                info["cached"] = True
                info["fetched_at"] = str(cached.get("fetched_at") or "")
                info["updated_at"], info["count"] = _index_facts(cached.get("index"))
            return info
        info["updated_at"], info["count"] = _index_facts(self._local_raw())
        return info

    def _local_raw(self):
        """读**随包**索引的原始 JSON（读不出来 → None）。只读本地文件，不联网、不校验。"""
        path = self.local_index_path
        if not path or not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8-sig") as fh:
                return json.load(fh)
        except Exception as e:
            pet_log.log_throttled("plugin_index.local_raw",
                                  "随包索引读不出来（%s）：%r" % (path, e))
            return None

    def _read_cache(self, base):
        """本地缓存里**属于这个地址**的远端索引 → {"source_url", "fetched_at", "index"} | None。

        解析不了 / 格式不认识 / 地址对不上 → None（调用方照"没有缓存"那条路走）：
        换过地址之后宁可重新取一次，也不能把 A 站点的清单当成 B 站点的显示给用户。

        比对用的是**解析后**的取数地址（index_url_of）：配置写目录时缓存里记的是
        .../index.json，拿原样的目录去比会永远比不上（于是"缓存命中"这条路径形同虚设）。
        """
        path = self.remote_cache_path
        if not path or not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8-sig") as fh:
                data = json.load(fh)
        except Exception as e:
            pet_log.log_throttled("plugin_index.remote_cache",
                                  "远端索引缓存读不出来（按没有缓存处理）：%s：%r" % (path, e))
            return None
        if not isinstance(data, dict) or data.get("cache_format") != REMOTE_CACHE_FORMAT:
            return None
        if str(data.get("source_url") or "") != (index_url_of(base) or str(base or "")):
            return None
        if not isinstance(data.get("index"), dict):
            return None
        return data

    def _write_cache(self, source_url, raw):
        """把刚取回来的远端索引**原子**落成本地缓存 → "" 或错误串。

        缓存自带 source_url：它记的是"这份清单是从哪个地址取回来的"，不是"现在配置的是哪个"。
        """
        path = self.remote_cache_path
        if not path:
            return "插件目录不可用（宿主未接线），没地方放索引缓存"
        made = self._ensure_dir(os.path.dirname(path))
        err = pet_io.atomic_write_json(path, {"cache_format": REMOTE_CACHE_FORMAT,
                                              "source_url": str(source_url or ""),
                                              "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                                              "index": raw}, log=self._log)
        if err:
            self._cleanup_dirs(made)
            return str(err)
        return ""

    def _drop_cache(self):
        """删掉远端索引缓存（清除远端地址时用）。删不掉只会留一个文件，不改变任何结论。"""
        path = self.remote_cache_path
        if not path or not os.path.isfile(path):
            return
        try:
            os.remove(path)
        except OSError as e:
            pet_log.log_throttled("plugin_index.drop_cache", "远端索引缓存删不掉：%r" % (e,))
        self._drop_empty_dir(os.path.dirname(path))     # 空目录也一并撤掉（不留空壳）

    # ---------- 下载 ----------
    def download(self, entry, progress=None):
        """按索引条目下载到 <plugins>/_download/ → (路径 | None, err)。

        三层核对，**一层都不过就删掉临时文件**并把可读原因交出去：
        ① 声明的 bytes（**取数前**先看：收 limit 的取数实现边读边判、当场停手，收不了的
           取回来立刻按全仓容量上限判一次）② 实际长度 ③ sha256。
        """
        if not isinstance(entry, dict):
            return None, "索引条目不可用"
        rel = entry.get("release")
        if not isinstance(rel, dict):
            return None, ("这条插件没有可用版本：%s" % (entry.get("reason") or "索引里没有版本"))
        src = entry.get("source") or []
        target = str(src[1]) if len(src) > 1 else ""
        if not target:
            return None, "索引条目没有解析出取数地址"
        if not self.download_dir:
            return None, "插件目录不可用（宿主未接线），下载不了"
        # v2.6.0（找茬审查 P2-c）：声明的 bytes **取数前**就读出来，能当上限用就当上限用
        # （收 limit 的取数实现会边读边停，不必先把一坨注定要丢的数据读完再比大小）。
        # 下面那条长度判据一行没动：它才是"字节数不符"的**唯一**口径，上限只是止损。
        want_bytes = rel.get("bytes")
        declared = _byte_cap(want_bytes) if isinstance(want_bytes, int) \
            and not isinstance(want_bytes, bool) and want_bytes > 0 else 0
        data, err = self._fetch_bytes(target, progress, declared)
        if data is None:
            return None, err or "取数失败"
        if isinstance(want_bytes, int) and not isinstance(want_bytes, bool) \
                and len(data) != want_bytes:
            return None, ("下载的字节数与索引不符（索引 %d 字节，实际 %d 字节）——"
                          "已丢弃这次下载" % (want_bytes, len(data)))
        want_sha = str(rel.get("sha256") or "").lower()
        got_sha = sha256_bytes(data)
        if got_sha != want_sha:
            return None, ("下载内容的 sha256 与索引不符（索引 %s…，实际 %s…）——"
                          "包可能被改动或索引是旧的，已丢弃这次下载"
                          % (want_sha[:12] or "(空)", got_sha[:12]))
        path = os.path.join(self.download_dir, self._download_name(entry, rel))
        made = self._ensure_dir(self.download_dir)
        werr = pet_io.atomic_write_bytes(path, data, log=self._log)
        if werr:
            self._cleanup_dirs(made)
            return None, "写入下载文件失败：%s" % werr
        return path, ""

    def _download_name(self, entry, rel):
        """下载文件的临时名：<id>-<版本>.zip（都过一遍字符集收紧）。"""
        pid = _safe_filename(entry.get("id"), "plugin")
        ver = _safe_filename(rel.get("version"), "0")
        return "%s-%s.download.zip" % (pid, ver)

    def install_file(self, host, entry, path):
        """把**已经下载好**的包装进宿主（主线程做落地）→ (ok, msg)；无论如何都删临时文件。"""
        try:
            if host is None:
                return False, "插件宿主未接线，装不了"
            manifest, verr = pet_plugin.validate_plugin_zip(path, self._host_version)
            if manifest is None:
                return False, "插件校验未通过：%s" % str(verr or "原因未知").strip()
            meta = manifest.get("plugin")
            meta = meta if isinstance(meta, dict) else {}
            want = str(entry.get("id") or "")
            got = str(meta.get("id") or "")
            if want and got and want != got:
                return False, ("索引条目「%s」里的包自报 id 是「%s」——对不上，已拒绝安装"
                               "（索引与包不是同一件东西，宁可不装）" % (want, got))
            # v2.7.0（代理 C·小账 a）：**id 对上了还不够**——类别也得对上。
            # 此前只核 id：索引写 data_kind=lines、包里装的是 role 时，市场页按索引显示成
            # 「台词包」，落地却把一只角色塞进角色库（界面与实际内容对不上，用户没有任何
            # 线索）。类别不一致 = 索引与包不是同一件东西，与 id 不一致同一个口径。
            want_kind = str(entry.get("data_kind") or "")
            got_kind = str(meta.get("data_kind") or "")
            if want_kind and got_kind and want_kind != got_kind:
                return False, ("索引条目「%s」标的是「%s」类插件，包里的 manifest 却自报"
                               "「%s」类——界面会按索引显示成一种、实际落地成另一种，"
                               "已拒绝安装（索引与包不是同一件东西，宁可不装）"
                               % (want, want_kind, got_kind))
            ok, msg = host.install_zip(path, source_url=str(entry.get("url") or ""))
            return bool(ok), msg
        finally:
            self._drop_download(path)

    def install(self, host, entry, progress=None):
        """下载 → 校验 → 交给 PluginHost.install_zip（同步版；界面走后台线程 + 主线程落地）。"""
        path, err = self.download(entry, progress)
        if path is None:
            return False, err
        return self.install_file(host, entry, path)

    # ---------- 清理 ----------
    def cleanup(self):
        """清掉 _download/ 里上一次留下的临时文件（崩溃 / 被杀留下的），返回清掉几个。"""
        d = self.download_dir
        if not d or not os.path.isdir(d):
            return 0
        n = 0
        for name in sorted(os.listdir(d)):
            full = os.path.join(d, name)
            if os.path.isfile(full):
                try:
                    os.remove(full)
                    n += 1
                except OSError:
                    pass    # 有意忽略：删不掉就留着（下次再来）
        self._drop_empty_dir(d)
        return n

    def _drop_download(self, path):
        """删掉一个下载临时文件；顺带把空的 _download/ 撤掉（失败不留残余）。"""
        try:
            if path and os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass    # 有意忽略：删不掉不影响正确性（cleanup 还会再来一次）
        self._drop_empty_dir(self.download_dir)

    @staticmethod
    def _drop_empty_dir(path):
        try:
            if path and os.path.isdir(path) and not os.listdir(path):
                os.rmdir(path)
        except OSError:
            pass    # 有意忽略：空目录删不掉不影响任何事

    def _ensure_dir(self, path):
        """建目录 → 本次**新建**的目录清单（失败路径按它撤回去）；已存在 → []。"""
        made = []
        cur = path
        while cur and not os.path.isdir(cur):
            made.append(cur)
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            return made
        return made

    def _cleanup_dirs(self, made):
        """把本次刚建出来的目录撤掉（从最深的开始）——失败的下载连空目录都不留。"""
        for d in sorted(made or [], key=len, reverse=True):
            self._drop_empty_dir(d)

    # ---------- 取数（注入优先） ----------
    def _fetch_bytes(self, target, progress, limit=0):
        """取数：**远端**走注入的 fetch（缺省 urllib），**本地路径**直接读文件。

        为什么本地路径不经过注入的 fetch：注入的是"网络取数"这一层（测试要挡的就是它），
        而"随包的本地副本"是程序自带的文件——它必须一条路都不依赖注入、也不需要网络，
        离线也要装得上（base_url 口径的另一半）。

        limit：本次最多接受多少字节（<=0 = 只受 pet_export.EXPORT_MAX_BYTES 约束）。
        v2.6.0（找茬审查 P2-c）：注入路径此前**一条上限都没有**（本地分支也会先整份读进
        内存再判）。现在：能收 limit 的取数实现边读边停；收不了的（老契约 fetch(url)）
        拿回 bytes 之后立刻按上限判一次——止损点不同，但都别让注定要丢的数据再往下走。
        """
        prog = progress if progress is not None else self._progress
        cap = _byte_cap(limit)
        if not is_remote(target) or self._fetch is None:
            return _call_default_fetch(target, prog, cap)
        try:
            data, err = _call_injected_fetch(self._fetch, target, cap)
        except Exception as e:          # 注入的取数自己抛了：折成一句人话
            return None, "取数失败：%r" % (e,)
        if data is None:
            return None, str(err or "取数失败")
        if not isinstance(data, (bytes, bytearray)):
            return None, "取数返回的不是 bytes（%r）" % (type(data).__name__,)
        data = bytes(data)
        # 注入路径的兜底上限：**全仓容量上限**，不是声明的 bytes——声明的 bytes 只当"能收
        # 就省点流量"的提示传给取数实现（收不了的实现会原样取回全部）。口径分开是为了让
        # "字节数与索引不符"永远由 download() 那条长度判据说，不出现两种说法。
        guard = pet_export.EXPORT_MAX_BYTES
        if len(data) > guard:
            return None, ("取数结果超过容量上限（%d 字节，上限 %d）——已丢弃"
                          % (len(data), guard))
        return data, ""
