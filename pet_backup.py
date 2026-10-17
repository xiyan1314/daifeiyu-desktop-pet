# -*- coding: utf-8 -*-
"""大肥鱼桌宠 · 用户数据备份 / 恢复（v2.11.0 · W1-b）

职责：把「用户自己的数据」打成一个 zip（带 manifest + 每个文件的 sha256），以及从这样一个
zip 恢复回去。纯逻辑、Qt-free、可无 GUI 单测（与 pet_export / pet_plugin 同一路数）。

## 用户数据这条线从哪来：出货模块自带一份 + 一条钉子用例

「哪些文件是用户数据」在本仓**已经有一份**定义：发布检测脚本 _check_release 的
USER_DATA_NAMES / USER_DATA_DIRS（外加 _RESIDUE_RE 的残留形态与 SYNC_FILES 的发货清单）。
那份口径的用途是「把用户的东西**挡在发布包外面**」；备份要的就是同一句判断反过来读——

    发布包里绝不能出现的东西 = 用户自己的东西 = 备份必须带走、恢复必须写回的东西。

**但不能 import 它**（v2.11.0 实测，两个后果都很硬，别再试一次）：

  ① _check_release.py 是**开发/绿色版目录里才有**的脚本（_GREEN_ROOT_DEV_RE 明确拦它，
     它也不在 SYNC_FILES 里）→ 成品里"点备份永远看到读不到 _check_release.py"，
     这一版宣传的功能在发布包里**根本不可用**；
  ② 懒 import 也躲不过发布门 check_imported_modules_shipped —— 它按 AST 扫，函数体里的
     import 一样算，当场点名「运行时模块被 import 却没进 SYNC_FILES」。

所以口径**搬进出货模块**（见下面「一、口径」那组 RUNTIME_* 常量与 _RuntimeRules）。
"手抄"的危险从来不是"抄了一份"，而是"**抄完两边漂了没人知道**"——本仓为同一种病已经付过
四次代价（pet_balance / v2.5.1 的四个模块 / pet_plugin_index / pet_ai+pet_config）。
这里用一条**机器化的钉子**代替"记得回来同步"：

    tests/test_backup_v2110.py::test_运行期口径与发布门逐项相等

它在 _check_release 可 import 时逐项比数据（名单 / 目录 / 否决清单），再拿同一份语料
**逐条比行为**（把 _check_release 当 source 注入，走同一条代码路径）。发布门那边加一个名字
而这边忘了加，红的就是那条用例。source= 注入面保留，就是为它，也为"以后真抽成
pet_userdata.py"留一条改一行就换的路。

## 备份包的形状

    manifest.json   {"format":"dfypet-backup","schema":1,"created_at":…,"app_version":…,
                     "whitelist":{"revision":…,"names":[…],"dirs":[…],…},
                     "files":[{"name":"config.json","size":123,"sha256":"…"}, …]}
    roles/a.png     用户文件的**原始相对路径**（正斜杠），内容逐字节就是源文件

manifest 排在第一条、且用固定时间戳（1980-01-01）写——同一份数据 + 同一个注入时钟写两次，
整包**逐字节相同**（这是"原子写、没有隐藏不确定性"的机器判据，也是本模块自测的一条用例）。

## 三条不可让的关口

1. **原子写**：先写「<目标>.<pid>.<序号>.tmp」，自校验通过后才 os.replace 到正式名。
   中途失败/被杀 → 正式文件**从没被碰过**，磁盘上不会出现"半截 zip"。
2. **zip slip 一律拒**：条目名先过 pet_plugin 的"落盘名安全线"（.. / 绝对路径 / 盘符 /
   反斜杠 / Windows 保留设备名…，**同一条判据**守着插件包解压与数据恢复两处），再过"是不是
   用户数据"，最后做一次 abspath 包含性双保险。**名字级拒绝发生在解压之前**，恶意包一个字节
   都落不下来。
3. **要么全成，要么回到原样**：写盘前先自动快照（<备份包同目录>/.pre-restore-<时间>.zip），
   逐条 sha256 校验通过才开始写；写到一半失败 → 用快照回滚，并删掉这一趟**新造出来**的文件
   （快照里没有它们 = 恢复前本来不存在）。

## 已知边界（写下来而不是假装没有）

* **恢复是"盖上去"，不是"镜像"**：备份里没有的用户文件不会被删除（用户恢复一个旧备份，不该
  因此丢掉之后新拍的角色图）。要"回到一模一样"是另一件事，得先删干净再恢复。
* **认不出官方插件包时会多带**：plugins/index.json 缺失/坏掉时，packs/ 下的包认不出是官方的，
  备份会把它们当用户数据带走。发布门那条判据的失败方向是"宁可少认也不误发"，备份侧是"宁可
  多带也不落下"——**方向相反是因为目标相反**，别把它当口径不一致。
* **恢复期间别让桌宠同时写盘**：逐文件原子写能防"写坏了"，防不了"两个写者对同一个 config.json
  各写一半"。UI 侧（pet_dialogs.open_restore）恢复成功后当场重载 cfg 拦掉"旧配置写回"，
  并把回执改成"**必须**重启"——角色/台词/闹钟这些服务对象里的副本要重启才重读。
* **config.json 的 schema_version 高了就拒**（不是"尽力恢复"）：未来版本的配置一旦被写回去，
  本版会按只读兼容模式运行（配置再也不落盘）。宁可让用户先升级，也不给他一份"看起来恢复了、
  其实设置全存不下来"的数据。取不到本版版本号时这一项不判（其余关口照旧）。
* **符号链接不跟**（目录与文件都跳过）：备份不该把链接指向的盘外大树整棵搬进用户自己的 zip。
"""

import datetime
import hashlib
import itertools
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile

import pet_export   # 包容量上限**单一来源**（与角色包、插件包同一口径）
import pet_io       # 原子写**单一来源**（tmp + os.replace + 路径锁 + 清理）
import pet_plugin   # zip 条目名的安全线**单一来源**（插件包解压与数据恢复共用一条判据）

# 包格式（与 pet_export.BUNDLE_FORMAT / pet_plugin.PLUGIN_FORMAT 同一个约定：
# format 字面量 + schema 整数，读的一方只认自己 <= 的版本）
BACKUP_FORMAT = "dfypet-backup"
BACKUP_SCHEMA = 1
MANIFEST_NAME = "manifest.json"

# 恢复**唯一要读懂内容**的条目：config.json 的 schema_version 决定"这份配置本程序放不放得下"。
# 其余条目只比名字/大小/sha256，一个字节都不解析。
CONFIG_NAME = "config.json"
# 读 config.json 时的上限：合法配置只有几 KB。超了就不在**这一层**判版本（交给下面的大小 /
# 摘要校验），绝不为了看一眼版本号把一个可能很大的条目整块读进内存。
_CONFIG_PROBE_LIMIT = 4 * 1024 * 1024

# 恢复前自动快照的命名：".pre-restore-<时间>.zip"（点开头 = 和用户自己的备份包区分开）
SNAPSHOT_PREFIX = ".pre-restore-"
SNAPSHOT_SUFFIX = ".zip"

# 备份**不带**的东西：缓存目录。它出现在发布口径的 USER_DATA_DIRS 里，理由却是另一件事
# （绿色版目录不许有 __pycache__，见 _dev/README.md 铁律 1 的 .pyc 事故）；备份侧的理由更简单：
# .pyc 是可再生的编译产物，带进备份只会让包变大，恢复后还会把过期字节码铺回用户目录。
# 名单只有这一个名字，且**必须来自发布口径**（用例钉着这一条，免得我在备份侧自造一套）。
BACKUP_SKIP_DIRS = ("__pycache__",)

# 单个条目的读写块大小（与 pet_export 的大条目块同一量级：几十 MB 的参考音也只占一块内存）
_CHUNK = 256 * 1024
# 临时文件名的**进程内序号**：同一进程连续两次备份不会抢同一个 .tmp（pet_export 踩过这条）
_TMP_SEQ = itertools.count(1)


class RulesUnavailable(RuntimeError):
    """用户数据口径**不完整**（注入进来的 source 少了必需的那几件东西）。

    这是一个**拒绝服务**的异常，不是"降级"：口径不对就不去动用户的文件，也绝不现场猜一份。
    """


class _EntryTooBig(Exception):
    """条目的实际内容比清单声明的大——zip 炸弹的典型形状，读到超限立刻中止。"""


# ---------------- 一、口径：出货模块自带一份 + 钉子用例对齐发布门 ----------------
# 数据面（下面四个常量）**必须与 _check_release 的那几个**逐项相等，由
# tests/test_backup_v2110.py::test_运行期口径与发布门逐项相等 钉死（数据 + 行为两层）。
RUNTIME_RULES_NAME = "pet_backup.runtime"

# 用户数据名单（= _check_release.USER_DATA_NAMES）
RUNTIME_USER_DATA_NAMES = frozenset((
    "config.json", "roles.json", "audio.json", "voice.json", "voice_assets.json",
    "voice_backend.json", "voice_backend.log", "alarms.json", "behaviors.json",
    "lines.json", "ledger.json", "ledger_archive.json", "error.log",
    "memory.log", "usage.json", "memory.json",
    # 专注/番茄钟记录：今天还没有（v2.13.0 才做），但它是"用户攒出来的数据"，
    # 发布门与备份共用这条线——先划线，免得以后变成发布包里的残留（见 _check_release 的注释）
    "focus.json",
    # 崩溃重启的熔断标记：名字的唯一来源是 pet_guard.MARKER_FILENAME（见 _skip_names，
    # 备份**不带**它——恢复旧备份不该把"崩过几次"倒灌回去）
    "crash_recovery.json",
))
# 目录白名单（= _check_release.USER_DATA_DIRS，**含顺序**）
RUNTIME_USER_DATA_DIRS = ("roles", "voice", "voice_ref", "audio", "alarms", "__pycache__",
                          "prompts/custom")
# 残留形态（= _check_release._RESIDUE_RE 的正则原文）
RUNTIME_RESIDUE_PATTERN = r"^(?P<stem>.+?)\.(?:(?:[0-9]+\.){0,2}tmp|bak|migrated|old|bad)$"
# 发货清单里**落进了用户数据候选空间**的那些条目（今天是 plugins/ 的官方索引与说明）：
# 它们是"发布门认发货 / 备份认用户"两份口径的接口——发货清单对白名单行使否决权。
# ⚠ 这里只放"会被 is_user_data 误认成用户数据"的发货文件（plugins/ 前缀 / 落在
# USER_DATA_DIRS 里的 / 根级同名的），**不是**整份 SYNC_FILES：那有 30+ 条、每个版本都在变，
# 抄进来就是第二个漂移源。钉子用例按**同一条规则**从 _check_release.SYNC_FILES 重算一遍与
# 本元组比 —— 于是"以后有人往 roles/ 里塞随包文件"也会当场红，而不是悄悄漏掉。
RUNTIME_SYNC_FILES = ("plugins/index.json", "plugins/README.md")

# 口径对象必须具备的属性（少了就是"口径不完整"，直接拒绝，不许猜）
_RULES_ATTRS = ("USER_DATA_NAMES", "USER_DATA_DIRS", "user_data_hit", "residue_hit",
                "plugin_user_data_hits")


def _official_packs(root):
    """plugins/index.json 里上架的**本地包本体** → {"plugins/..."}。

    与 _check_release.plugin_official_packs 同一条判据：url 是绝对地址或越界路径一律跳过
    （那不是随包出货的本地文件）；索引缺失/坏 JSON/不知道根目录 → 空集。空集的后果是
    "认不出官方包" → 备份侧把它当用户数据**多带一份**（宁可多带，不可落下；发布门那边的
    失败方向相反，是"宁可少认也不误发"——目标不同，别读成口径不一致）。
    """
    if not root:
        return set()
    path = os.path.join(root, "plugins", "index.json")
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return set()
    out = set()
    for item in (data.get("plugins") if isinstance(data, dict) else None) or []:
        if not isinstance(item, dict):
            continue
        for rel in item.get("releases") or []:
            if not isinstance(rel, dict):
                continue
            url = str(rel.get("url") or "").strip().replace("\\", "/")
            if not url or "://" in url or url.startswith("/") or ".." in url.split("/"):
                continue
            local = os.path.normpath(os.path.join("plugins", *url.split("/")))
            local = local.replace(os.sep, "/")
            if os.path.isfile(os.path.join(root, *local.split("/"))):
                out.add(local)
    return out


class _RuntimeRules(object):
    """_check_release 那几个名字的**最小同形实现**（口径的出货副本）。

    形状必须一致（USER_DATA_NAMES / USER_DATA_DIRS / SYNC_FILES / user_data_hit /
    residue_hit / plugin_user_data_hits / _RESIDUE_RE）：is_user_data 与 whitelist_snapshot
    是照着"给一个口径对象"写的，两份口径可以互换——钉子用例正是靠这一点，把发布门那份
    **灌进同一条代码路径**逐条比行为（而不是比两份文本）。
    """

    NAME = RUNTIME_RULES_NAME
    USER_DATA_NAMES = RUNTIME_USER_DATA_NAMES
    USER_DATA_DIRS = RUNTIME_USER_DATA_DIRS
    SYNC_FILES = RUNTIME_SYNC_FILES
    _RESIDUE_RE = re.compile(RUNTIME_RESIDUE_PATTERN)

    @classmethod
    def residue_hit(cls, base):
        """文件名 → 命中的用户数据名（""=不是残留形态）。与发布门同一口径。"""
        m = cls._RESIDUE_RE.match(base)
        if m and m.group("stem") in cls.USER_DATA_NAMES:
            return m.group("stem")
        return ""

    @classmethod
    def user_data_hit(cls, base):
        """文件名 → 命中的用户数据名（""=没命中）；精确名与残留形态都算。"""
        if base in cls.USER_DATA_NAMES:
            return base
        return cls.residue_hit(base)

    @classmethod
    def plugin_user_data_hits(cls, names, root=None):
        """plugins/ 下**不是官方**的条目（= 用户装的插件 / 临时下载目录）。"""
        official = set(cls.SYNC_FILES)
        if root:
            official |= _official_packs(os.path.abspath(str(root)))
        out = []
        for raw in names or ():
            n = str(raw or "").replace("\\", "/")
            if not n or n.endswith("/") or not n.startswith("plugins/"):
                continue
            if n in official:
                continue
            out.append(raw)
        return sorted(out)


RUNTIME_RULES = _RuntimeRules()   # 模块级实例：is_user_data / whitelist_snapshot 的默认口径


def _source_or_load(source):
    """取口径：source（可注入）优先；None = 本模块自带的运行期口径。

    注入面留着有两个用处：① 钉子用例把 _check_release 灌进来，按**同一条代码路径**与运行期
    口径逐条比行为；② 以后真把口径抽成 pet_userdata.py 时，调用方只需换个参数。
    """
    src = RUNTIME_RULES if source is None else source
    missing = [a for a in _RULES_ATTRS if not hasattr(src, a)]
    if missing:
        raise RulesUnavailable(
            "用户数据口径不完整（缺 %s）——备份/恢复不做，免得拿一份猜出来的名单去动用户文件"
            % "、".join(missing))
    return src


def _skip_names():
    """备份**不带**的运行期状态文件：崩溃重启的熔断标记。

    为什么排除它：crash_recovery.json 记的是"这台机器崩过几次 / 多久以内"，是**运行期状态**
    而不是用户资产。恢复一个旧备份时把它一起倒灌回去，桌宠一启动就会被自己的熔断器当成崩溃
    循环（进安全模式 / 拒绝重启）——用户看到的是"恢复完备份就打不开了"。

    名字的唯一来源是 pet_guard.MARKER_FILENAME（全仓只此一处字面量），所以这里 import 它
    而不是再抄一遍字符串；拿不到就算空集（**不排除**：宁可多带一个状态文件，也不让整条备份
    链因为一个 import 成败而失效）。
    """
    try:
        import pet_guard
        return frozenset((str(pet_guard.MARKER_FILENAME),))
    except Exception:
        return frozenset()


def whitelist_snapshot(root=None, source=None):
    """当前生效的用户数据口径快照（写进 manifest，供人核对"这个包按哪一版规则打的"）。

    为什么需要 root：plugins/ 那一段要读 plugins/index.json 才知道哪些包是官方的，而"官方"
    是相对**数据目录**（绿色版里它同时是程序目录）说的。

    返回 dict：names / dirs（发布口径原样，排序）+ residue（正则原文）+ sync_files_revision
    （发货清单的摘要）+ revision（整份口径的摘要，即"白名单规则版本"）+ skip_dirs
    （备份额外跳过的目录，见 BACKUP_SKIP_DIRS）+ skip_names（备份不带的运行期状态文件，
    见 _skip_names）。
    """
    src = _source_or_load(source)
    names = sorted(str(n) for n in src.USER_DATA_NAMES)
    dirs = sorted(str(d).replace("\\", "/").strip("/") for d in src.USER_DATA_DIRS)
    syncs = sorted(str(n).replace("\\", "/") for n in src.SYNC_FILES)
    snap = {
        "source": str(getattr(src, "NAME", getattr(src, "__name__", "?"))),
        "names": names,
        "dirs": dirs,
        # 残留形态的**正则原文**：不抄内容、只记它的版本，规则一改 revision 就变
        "residue": getattr(getattr(src, "_RESIDUE_RE", None), "pattern", ""),
        "sync_files_revision": _digest(syncs),
        "skip_dirs": sorted(BACKUP_SKIP_DIRS),
        # 备份**不带**的运行期状态文件（熔断标记）：口径认它是用户数据，但备份取舍里排除它，
        # 两件事分开记 —— 读清单的人一眼能看出"名单里有它、包里却没有"是有意的
        "skip_names": sorted(_skip_names()),
    }
    snap["revision"] = _digest(snap)
    return snap


def is_user_data(rel, root=None, source=None):
    """rel（相对数据目录、正斜杠）是不是用户数据？—— 判据全部借自发布口径。

    三条来源（与 _check_release.check_zip 同构）：

    ① **目录白名单**：USER_DATA_DIRS 下的一切（roles/ / voice/ / prompts/custom/ …），但
       BACKUP_SKIP_DIRS 里的缓存目录除外；
    ② **根级精确名 / 残留形态**：user_data_hit() 是发布门自己的谓词——但备份侧对**残留形态**
       （config.json.1234.5678.tmp / .bak / .old / .bad）判 False：它们是原子写与自愈的中间
       产物，带进备份只会把半截文件铺回用户目录；恢复侧"只认白名单"这条判据也因此连
       "往用户目录写一个 .tmp"都做不到；
    ③ **用户装的插件**：plugin_user_data_hits() 也直接调用——官方索引/说明/官方内容包不算，
       plugins/<id>/、plugins/_download/ 算。

    再叠一条**否决**：SYNC_FILES 里的发货文件永远不是用户数据（哪怕它躺在某个白名单目录里，
    例如 plugins/index.json）。这是"发布门认发货 / 备份认用户"两份口径的接口处。
    运行期口径只带"会落进用户数据候选空间"的那几条（RUNTIME_SYNC_FILES），由钉子用例按同一条
    规则从 _check_release.SYNC_FILES 重算后比对——不是整份抄。
    """
    src = _source_or_load(source)
    text = str(rel or "").replace("\\", "/").strip("/")
    if not text:
        return False
    parts = text.split("/")
    if any(seg in BACKUP_SKIP_DIRS for seg in parts):
        return False
    if text in _skip_names():
        # 口径认它（发布包里不许有），但备份**不带走**：恢复旧备份不该倒灌崩溃计数，
        # 理由见 _skip_names 的 docstring
        return False
    if text in _norm_set(src.SYNC_FILES):
        return False
    for d in src.USER_DATA_DIRS:
        dd = str(d).replace("\\", "/").strip("/")
        if dd and (text == dd or text.startswith(dd + "/")):
            return True
    if len(parts) == 1 and src.user_data_hit(parts[0]):
        # 根级：精确名算，残留形态不算（理由见 docstring 第 ② 条）
        return not src.residue_hit(parts[0])
    try:
        if src.plugin_user_data_hits([text], root):
            return True
    except Exception:
        return False    # 有意忽略：索引读不动只代表"认不出官方包"，这里退回"不当用户数据"
    return False


def collect_user_files(data_dir, root=None, source=None):
    """数据目录里的用户文件（相对路径、正斜杠、排序去重）——备份的**唯一**来源。

    为什么不整棵树 os.walk：绿色版的数据目录同时是程序目录（Lib/ / PySide6/ 几千个文件），
    为了挑出十几个用户文件把整棵树走一遍是纯浪费，而且容易把无关的同名文件卷进来。这里只走
    三条来源（根一层 / 目录白名单 / plugins/），与 is_user_data 的判据一一对应。
    """
    src = _source_or_load(source)
    base = os.path.abspath(str(data_dir))
    found = []
    # ① 根一层（不递归）
    try:
        names = sorted(os.listdir(base))
    except OSError:
        names = []
    for name in names:
        ap = os.path.join(base, name)
        if os.path.isfile(ap) and not os.path.islink(ap) and is_user_data(name, base, src):
            found.append(name)
    # ② 目录白名单（含 prompts/custom 这种两层路径）
    for d in src.USER_DATA_DIRS:
        found.extend(_walk_user_files(base, d, src))
    # ③ plugins/：官方的那几条由 is_user_data 里的同一份判据挡掉
    found.extend(_walk_user_files(base, "plugins", src))
    return sorted(set(found))


def _walk_user_files(base, rel_dir, src):
    """走一个子目录，挑出其中的用户文件（相对路径）。目录不存在 = 空。"""
    top = os.path.join(base, *str(rel_dir).replace("\\", "/").strip("/").split("/"))
    if not os.path.isdir(top):
        return []
    out = []
    for cur, dirs, files in os.walk(top):
        # followlinks 默认 False 已经不下钻符号链接目录；这里连列都不列。符号链接**文件**
        # 同理跳过（理由见模块 docstring 的已知边界）
        dirs[:] = [d for d in dirs if d not in BACKUP_SKIP_DIRS
                   and not os.path.islink(os.path.join(cur, d))]
        for f in files:
            ap = os.path.join(cur, f)
            if os.path.islink(ap) or not os.path.isfile(ap):
                continue
            rel = os.path.relpath(ap, base).replace(os.sep, "/")
            if is_user_data(rel, base, src):
                out.append(rel)
    return out


def _norm_set(names):
    """发货清单 → 归一后的集合（正斜杠、去首尾斜杠）——只为了比"这条是不是发货文件"。"""
    out = set()
    for n in names or ():
        t = str(n).replace("\\", "/").strip("/")
        if t:
            out.add(t)
    return out


# ---------------- 二、路径与命名 ----------------

def default_backup_path(data_dir, now=None):
    """默认备份文件名：<数据目录>/大肥鱼备份-<年月日-时分秒>.zip（UI 用它预填文件框）。

    放在数据目录是刻意的：那里的 *.zip 本来就不在白名单里（.gitignore 也忽略），
    用户不选地方的时候也不会把备份落到"找不到的某个临时目录"。
    """
    return os.path.join(os.path.abspath(str(data_dir)),
                        "大肥鱼备份-%s%s" % (_stamp(_now_or(now)), SNAPSHOT_SUFFIX))


def snapshot_candidates(zip_path, data_dir, now=None, snapshot_dir=None):
    """恢复前快照可以落在哪些位置（按优先级，已去重、已避开同名文件）。

    "同目录"优先（用户能一眼看到"恢复前的样子"就在他选的那个备份旁边），写不进去才退到
    数据目录——快照是回滚的唯一依据，"写不出快照"等于**不许开始恢复**，所以这里要留退路。
    """
    when = _now_or(now)
    wanted = []
    if snapshot_dir:
        wanted.append(os.path.abspath(str(snapshot_dir)))
    wanted.append(os.path.dirname(os.path.abspath(str(zip_path))))
    wanted.append(os.path.abspath(str(data_dir)))
    out, seen = [], []
    for d in wanted:
        if d in seen:
            continue
        seen.append(d)
        out.append(_free_path(os.path.join(d, "%s%s%s" % (SNAPSHOT_PREFIX, _stamp(when),
                                                          SNAPSHOT_SUFFIX))))
    return out


def list_snapshots(dirpath):
    """列一个目录里的"恢复前快照"（新→旧）。UI 用它回答"我还能退回哪一步"。"""
    d = str(dirpath)
    try:
        names = os.listdir(d)
    except OSError:
        return []
    out = []
    for n in names:
        if n.startswith(SNAPSHOT_PREFIX) and n.endswith(SNAPSHOT_SUFFIX):
            p = os.path.join(d, n)
            if os.path.isfile(p):
                out.append(p)
    return sorted(out, reverse=True)   # 文件名里带时间戳 → 字典序就是时间序


# ---------------- 三、manifest ----------------

def build_manifest(data_dir, files, app_version="", now=None, root=None, source=None):
    """构造 manifest（**先算 sha256 再写包**：写的时候再算一遍，两遍不一致就作废）。

    第二遍不是浪费：它把"备份期间有人在改这个文件"变成一次**明确的失败**，而不是一个自相
    矛盾的包（manifest 里是旧内容、条目里是新内容）。
    """
    base = os.path.abspath(str(data_dir))
    records = []
    total = 0
    for rel in files:
        ap = os.path.join(base, *str(rel).split("/"))
        size = os.path.getsize(ap)
        records.append({"name": rel, "size": size, "sha256": _sha256_file(ap)})
        total += size
    return {
        "format": BACKUP_FORMAT,
        "schema": BACKUP_SCHEMA,
        "created_at": _iso(_now_or(now)),
        "app_version": str(app_version or ""),
        "data_dir": base,
        "file_count": len(records),
        "total_bytes": total,
        "whitelist": whitelist_snapshot(root if root is not None else base, source),
        "files": records,
    }


def _manifest_problem(man):
    """manifest 结构问题 → 人话原因（""=能认）。**只读，不解压任何条目。**"""
    if not isinstance(man, dict):
        return "备份清单不是一个对象"
    fmt = man.get("format")
    if fmt != BACKUP_FORMAT:
        return "这个包不是大肥鱼的用户数据备份（清单 format=%r）" % (fmt,)
    schema = man.get("schema")
    if not isinstance(schema, int) or schema < 1:
        return "备份清单的格式版本号不合法（schema=%r）" % (schema,)
    if schema > BACKUP_SCHEMA:
        return ("这份备份是更新版本的桌宠做的（清单 schema=%d，本程序只认 %d），"
                "请先升级桌宠再恢复" % (schema, BACKUP_SCHEMA))
    files = man.get("files")
    if not isinstance(files, list):
        return "备份清单里没有文件列表（files）"
    seen = set()
    for i, rec in enumerate(files):
        if not isinstance(rec, dict):
            return "备份清单第 %d 条不是对象" % (i + 1)
        name = rec.get("name")
        if not isinstance(name, str) or not name:
            return "备份清单第 %d 条缺文件名" % (i + 1)
        if name in seen:
            return "备份清单里有重名条目：%s" % name
        seen.add(name)
        digest = rec.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            return "备份清单里 %s 的 sha256 字段不合法" % name
        size = rec.get("size")
        if not isinstance(size, int) or size < 0:
            return "备份清单里 %s 的字节数字段不合法" % name
    return ""


def read_manifest(zip_path):
    """只读清单（不落盘、不解压数据条目）。返回 (manifest, err)。

    UI 用它做"恢复前先给用户看一眼：这是什么时候、哪一版、几个文件"。
    """
    path = str(zip_path)
    if not os.path.isfile(path):
        return None, "备份文件不见了：%s" % path
    try:
        with zipfile.ZipFile(path) as zf:
            return _read_manifest_from(zf)
    except zipfile.BadZipFile as e:
        return None, "这个文件不是有效的 zip（可能没下完整）：%s（%s）" % (_base_name(path), e)
    except (OSError, RuntimeError) as e:
        return None, "读备份包失败：%s（%s）" % (_base_name(path), e)


def _read_manifest_from(zf):
    """从已打开的 zip 里读 manifest → (manifest, err)。"""
    try:
        raw = zf.read(MANIFEST_NAME)
    except KeyError:
        return None, "这个包里没有备份清单（%s），不是大肥鱼的备份包" % MANIFEST_NAME
    if raw[:3] == b"\xef\xbb\xbf":
        # 与 pet_plugin 同口径：带 BOM 的清单是"别的工具重写过"的强烈信号，不吃
        return None, "备份清单带着 BOM（不是本程序写的），已拒绝"
    try:
        man = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        return None, "备份清单读不懂（%s）" % (e,)
    problem = _manifest_problem(man)
    if problem:
        return None, problem
    return man, ""


# ---------------- 四、备份 ----------------

def create_backup(data_dir, out_path, *, app_version="", now=None, root=None, source=None):
    """把数据目录里的用户文件打包到 out_path（原子写）。返回 (ok, 人话)。

    成功时那句人话可以直接当 UI 回执（含文件数/体积/落地路径）；失败时**原文件一个字节都
    没动**，磁盘上也不会留下半截 zip。
    """
    when = _now_or(now)
    base = os.path.abspath(str(data_dir))
    out = os.path.abspath(str(out_path))
    if not os.path.isdir(base):
        return False, "数据目录不存在：%s" % base
    if os.path.isdir(out):
        return False, "备份路径是个目录，不是文件：%s" % out
    try:
        files = collect_user_files(base, root=root, source=source)
        manifest = build_manifest(base, files, app_version=app_version, now=when,
                                  root=root, source=source)
    except RulesUnavailable as e:
        return False, str(e)
    except OSError as e:
        return False, "备份没写成：读不到用户数据（%s）" % (e,)
    ok, err = _write_zip_atomic(base, files, manifest, out, source)
    if not ok:
        return False, err
    if not files:
        return True, ("这次没有可备份的用户数据（刚装好就是这样），仍然生成了一个空备份：%s"
                      % out)
    return True, "已备份 %d 个文件（%s）→ %s" % (len(files), _size_text(manifest["total_bytes"]),
                                                out)


def _write_zip_atomic(base, files, manifest, out, source=None):
    """写包 → 自校验 → 原子替换。任何一步失败都清掉临时文件并返回 (False, 人话)。"""
    d = os.path.dirname(out)
    try:
        if d:
            os.makedirs(d, exist_ok=True)
    except OSError as e:
        return False, "备份没写成：建不了目标目录 %s（%s）" % (d, e)
    tmp = "%s.%d.%d.tmp" % (out, os.getpid(), next(_TMP_SEQ))
    try:
        zf = zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED)
        try:
            _write_manifest(zf, manifest)
            for rel in files:
                _add_file(zf, rel, os.path.join(base, *rel.split("/")))
        finally:
            # 关包失败的错误不要了：紧接着的自校验会给更准确的结论（包读不回来）。
            # 这里**不能**把 close 的异常往外抛——它会盖掉真正的原因（写盘失败）。
            _close_quietly(zf)
        # 自校验：写出来的包必须能读回来、且每条 sha256 与清单一致。
        # 这一遍还顺手把"备份期间有人改了源文件"变成明确的失败（见 build_manifest 的说明）。
        _entries, _man, err = _inspect_zip(tmp, base=base, source=source)
        if err:
            return False, "备份包写出来却读不回来（%s）——已放弃这次备份，原数据没动" % err
        os.replace(tmp, out)     # 原子替换：正式文件从来不是半截的
        return True, ""
    except (OSError, zipfile.BadZipFile, ValueError) as e:
        return False, "备份没写成：%s（原数据没动）" % (e,)
    finally:
        # **唯一的清理点**（以前除它之外还有两处，删掉哪一处都有别的一处兜着 —— 那种
        # "冗余清理"让用例没法证明自己有效）。成功时 tmp 已被 replace 走，这里是一次空操作；
        # 任何失败路径上 tmp 还在 → 当场删掉，磁盘上不留半截包。
        _remove(tmp)


def _write_manifest(zf, manifest):
    """manifest 用**固定时间戳**写（1980-01-01 = zip 的 DOS 时间原点）。

    与 pet_export 同一条理由：走 writestr(str) 会按当前时钟取时间，于是同一份数据隔一秒再
    备份就逐字节不同，"同一份数据 + 同一个注入时钟 → 逐字节相同"这条判据立刻失效。
    """
    zi = zipfile.ZipInfo(MANIFEST_NAME, date_time=(1980, 1, 1, 0, 0, 0))
    zi.compress_type = zf.compression
    zi.external_attr = 0o600 << 16
    zf.writestr(zi, json.dumps(manifest, ensure_ascii=False, indent=2))


def _add_file(zf, arc, src):
    """把一个源文件写进 zip。单独一层：用例从这里注入"写到第二条就失败"的故障。"""
    zf.write(src, arc)


# ---------------- 五、校验与解包（verify / stage / rollback 共用一条核心） ----------------

def current_config_schema(explicit=None):
    """本版 config 的 schema 版本号（int）→ 或 None（= 取不到，这一项就不判）。

    唯一真源是 `桌宠.CONFIG_SCHEMA_VERSION`。本模块 Qt-free、也**不许** import 桌宠
    （会成环，还会把 Qt 拖进纯逻辑用例），所以取法只有两条：
      · 调用方显式传进来（生产路径 pet_dialogs 从 sys.modules 取，见 _backup_rules）；
      · 没传就**现场看一眼** sys.modules 里有没有「桌宠」——运行期一定有（GUI 就在那儿），
        纯逻辑用例 / 命令行自检里通常没有。
    取不到只能跳过这一项判定：其余关口（manifest / 条目名 / 白名单 / 越界 / sha256）一条不少，
    所以"跳过"不是"放行恶意包"。**也不在这里猜一个版本号**：猜小了会拒绝本来能用的包，
    那比不判更糟（用户拿不到自己的数据）。
    """
    if explicit is not None:
        ver = _schema_int(explicit)
        return ver
    module = sys.modules.get("桌宠")
    return _schema_int(getattr(module, "CONFIG_SCHEMA_VERSION", None))


def _schema_int(value):
    """任意值 → 正整数版本号；bool / 浮点 / 非数字字符串 / <=0 一律 None（= 不判）。

    浮点要单独挡：`int(2.9)=2` 会静默截断成"旧版本"，正是 `桌宠._parse_schema_version`
    明确拒绝的那一类。数字字符串放行（老配置里有手写成 "2" 的）。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 1 else None
    if isinstance(value, str):
        try:
            v = int(value.strip())
        except ValueError:
            return None
        return v if v >= 1 else None
    return None


def _config_schema_problem(zf, man, config_schema=None):
    """包里 config.json 的 schema_version 高于本版 → 人话原因（""=能认）。

    为什么要有这一关（兼容审查 #4，实测）：旧版对一个 schema=9 的包恢复"成功"，之后
    `桌宠.load_config` 读到未来版本 → 兼容模式只读（_FUTURE_CFG）→ **配置再也不落盘**，
    用户只在 error.log 里看到一行。那种"恢复成功但配置被锁死"必须在**写盘之前**拒绝。

    只认 `schema_version` 一个字段、只做"高于本版"一个判断，别的坏形态一律放行：
      · 包里没有 config.json → 放行（这次恢复不碰配置）；
      · 没有 schema_version（老配置 / 手工样本）→ 放行（load_config 按 v1 迁移）；
      · 字段读不懂 / config.json 读不出来 / 体积超限 → 放行（真正的坏包由下面的名字 /
        大小 / sha256 三关去报；**不在这里新增拒绝口径**）。
    """
    rec = None
    for _rec in man.get("files") or []:
        if _rec.get("name") == CONFIG_NAME:
            rec = _rec
            break
    if rec is None:
        return ""
    current = current_config_schema(config_schema)
    if current is None:
        return ""
    size = rec.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or not 0 <= size <= _CONFIG_PROBE_LIMIT:
        return ""
    try:
        with zf.open(CONFIG_NAME) as fh:
            raw = fh.read(_CONFIG_PROBE_LIMIT + 1)
    except (KeyError, OSError, RuntimeError, zipfile.BadZipFile):
        return ""
    if len(raw) > _CONFIG_PROBE_LIMIT:
        return ""
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    ver = _schema_int(data.get("schema_version"))
    if ver is None or ver <= current:
        return ""
    return ("这份备份里的 config.json 是**更新版本**的桌宠写的（配置 schema=%d，本程序只认 %d）："
            "恢复后它会按「只读兼容模式」运行——新版本才认识的键会丢，配置也再也存不下来。"
            "所以这次恢复被拒绝；你的数据一个字节都没动。请先升级桌宠再恢复。"
            % (ver, current))


def verify_backup(zip_path, *, root=None, source=None, config_schema=None):
    """只验不落盘：结构 + 条目名 + 白名单 + 每条 sha256 + config.json 的 schema 版本。

    与恢复走**同一个核心**（_inspect_zip）：判据只写一份，"校验放行而恢复才拒"那种两处口径
    差在本模块里不可能发生。config_schema 见 current_config_schema（None = 现场取本版版本号）。
    """
    _entries, man, err = _inspect_zip(zip_path, root=root, source=source,
                                     config_schema=config_schema)
    return man, err


def _inspect_zip(zip_path, *, base=None, root=None, source=None, dest_dir=None,
                 config_schema=None, check_config_schema=True):
    """验一个备份包；给了 dest_dir 就顺手把每条落到那里（staging）。

    返回 (entries, manifest, err)。entries 每条是
    {"name", "size", "sha256", "staged"(路径或 None)}。

    **顺序是有讲究的**：先做完全部"名字级"检查（条目名安全 / 清单对齐 / 白名单 / 越界），
    再判 config.json 的版本，全过了才开始解压。所以一个带 ../evil 的恶意包连一个字节都
    落不下来——连 staging 目录都不会被创建。

    `check_config_schema=False` 只有一个用途：**回滚**（_rollback 用快照盖回去）是最后一道
    安全网，任何新加的拒绝口径都不许把它拦住——否则"恢复失败要回滚"会二次失败。
    """
    src = _source_or_load(source)
    path = str(zip_path)
    if not os.path.isfile(path):
        return [], None, "备份文件不见了：%s" % path
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile as e:
        return [], None, "这个文件不是有效的 zip（可能没下完整）：%s（%s）" % (_base_name(path), e)
    except (OSError, RuntimeError) as e:
        return [], None, "读备份包失败：%s（%s）" % (_base_name(path), e)
    try:
        with zf:
            man, err = _read_manifest_from(zf)
            if err:
                return [], None, err
            err = _names_problem(zf.namelist(), man, base, root, src)
            if err:
                return [], None, err
            if check_config_schema:
                err = _config_schema_problem(zf, man, config_schema)
                if err:
                    return [], None, err
            entries, err = _extract_entries(zf, man, dest_dir)
            if err:
                return [], None, err
            return entries, man, ""
    except zipfile.BadZipFile as e:
        return [], None, "备份包坏了（%s）——可能没下完整，或被改过" % (e,)
    except (OSError, RuntimeError) as e:
        return [], None, "读备份包时出错（%s）" % (e,)


def _names_problem(names, man, base, root, src):
    """全部"名字级"检查（**解压之前**）：重复条目 / 越界名 / 清单对齐 / 白名单 / 总量上限。"""
    listed = [rec["name"] for rec in man["files"]]
    if len(set(names)) != len(names):
        # zipfile 允许同名条目，而 zf.open(name) 只给**最后一条**——清单对不上的经典藏匿手法
        return "备份包里有重名条目（可能被改过），已拒绝"
    known = set(names)
    for n in names:
        if n == MANIFEST_NAME:
            continue
        problem = entry_name_problem(n)
        if problem:
            return ("备份包里有一条不安全的路径：%s（%s）——已拒绝，什么都没有解出来"
                    % (n, problem))
        if n not in set(listed):
            return "备份包里有清单没登记的文件：%s（可能被改过），已拒绝" % n
    missing = [n for n in listed if n not in known]
    if missing:
        return ("备份不完整：清单里有 %d 个文件在包里找不到（%s）"
                % (len(missing), _join(missing)))
    total = 0
    for rec in man["files"]:
        rel = rec["name"]
        if not is_user_data(rel, base if base is not None else root, src):
            return ("备份包里有不属于用户数据的路径：%s——可能是被改过的包，"
                    "拒绝它（否则可能覆盖程序文件）" % rel)
        if base is not None and _target(base, rel) is None:
            return "备份包里的路径越出了数据目录：%s，已拒绝" % rel
        total += rec["size"]
        if total > pet_export.EXPORT_MAX_BYTES:
            return ("备份包声明的解压总量过大（%s，上限 %s），已拒绝"
                    % (_size_text(total), _size_text(pet_export.EXPORT_MAX_BYTES)))
    return ""


def entry_name_problem(name):
    """zip 条目名 → 人话原因（""=安全）。**判据复用 pet_plugin 的落盘名安全线。**

    为什么借它：插件包解压与用户数据恢复是**同一件事**——"别人给的 zip 里的名字，敢不敢按它
    落盘"。它那份判据已经覆盖 .. / 绝对路径 / 盘符 / 反斜杠 / NUL / Windows 非法字符 / 保留
    设备名（con.png 与 con 是同一个设备）。在这里重写一遍 = 埋一个"两处迟早不一样"的口径差。
    """
    reason = pet_plugin._unsafe_name_reason(name)     # noqa: SLF001 —— 见本函数 docstring
    if reason:
        return reason
    if str(name).endswith("/"):
        return "是目录条目（备份包里只放文件）"
    return ""


def _extract_entries(zf, man, dest_dir):
    """按清单逐条读出来（dest_dir 给了就落盘）→ (entries, err)。

    边读边算 sha256，与清单比大小、比摘要；staged 文件名用 0000 这样的**平铺序号**，不用相对
    路径——staging 目录里连"按名字建目录"这一步都没有，路径穿越在这里无处可使。
    """
    entries = []
    for i, rec in enumerate(man["files"]):
        name = rec["name"]
        try:
            info = zf.getinfo(name)
        except KeyError:
            return [], "备份不完整：包里找不到 %s" % name
        staged = None if dest_dir is None else os.path.join(dest_dir, "%04d" % i)
        handle = None if staged is None else open(staged, "wb")
        try:
            got_size, got_sha = _copy_and_hash(zf, info, handle, rec["size"])
        except _EntryTooBig:
            return [], ("备份里的 %s 比清单说的大，已中止（可能是坏包或 zip 炸弹）" % name)
        finally:
            if handle is not None:
                handle.close()
        if got_size != rec["size"]:
            return [], ("备份里的 %s 大小对不上（清单说 %d 字节，实际 %d 字节），可能坏了"
                        % (name, rec["size"], got_size))
        if got_sha != rec["sha256"]:
            return [], ("备份里的 %s 内容对不上（sha256 校验失败）——可能损坏或被改过，"
                        "已拒绝恢复" % name)
        entries.append({"name": name, "size": got_size, "sha256": got_sha, "staged": staged})
    return entries, ""


def _copy_and_hash(zf, info, handle, limit):
    """流式读一个条目：算 sha256（handle 非 None 时同时落盘），超过 limit 立刻中止。"""
    digest = hashlib.sha256()
    total = 0
    with zf.open(info) as src:
        while True:
            chunk = src.read(_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise _EntryTooBig(info.filename)
            digest.update(chunk)
            if handle is not None:
                handle.write(chunk)
    return total, digest.hexdigest()


def _target(base, rel):
    """rel（已验过无 .. / 无绝对路径）→ 目标绝对路径；越界返回 None（双保险）。"""
    root = os.path.abspath(str(base))
    ap = os.path.abspath(os.path.join(root, *str(rel).split("/")))
    if ap == root or not ap.startswith(root + os.sep):
        return None
    return ap


# ---------------- 六、恢复（快照 → 落盘 → 失败回滚） ----------------

def restore_backup(zip_path, data_dir, *, now=None, snapshot_dir=None, app_version="",
                   root=None, source=None, config_schema=None):
    """从备份包恢复用户数据。返回 (ok, 人话)。

    四步，顺序不可换：

    1. **先验后写**：整包验完（名字 / 清单 / 每条 sha256）才碰数据目录——坏包、恶意包到这一步
       就结束，用户的数据一个字节都没动；
    2. **自动快照**：写盘前把"现在这个样子"打成 .pre-restore-<时间>.zip。快照写不出来 =
       **不恢复**（否则回滚没有依据，"要么全成"就成了一句空话）；
    3. **逐条落盘**：每个文件走 pet_io.atomic_write_bytes（tmp + os.replace），单文件层面永远
       不会半截；
    4. **失败回滚**：任一条写失败 → 用快照把已改的盖回去，并删掉这一趟新造出来的文件。

    成功时那句人话含：几个文件、包里是哪一版的数据、快照落在哪、建议重启。
    """
    when = _now_or(now)
    base = os.path.abspath(str(data_dir))
    if not os.path.isdir(base):
        return False, "数据目录不存在：%s" % base
    staged = None
    try:
        staged = tempfile.mkdtemp(prefix="dfypet_restore_")
        entries, man, err = _inspect_zip(zip_path, base=base, root=root, source=source,
                                        dest_dir=staged, config_schema=config_schema)
        if err:
            return False, err
        # ② 自动快照（写不出来就不恢复）
        snap, snap_err = _make_snapshot(zip_path, base, when, snapshot_dir, app_version,
                                        root, source)
        if snap_err:
            return False, ("恢复没开始：恢复前的自动快照没做成（%s）——你的数据一个字节都没动"
                           % snap_err)
        # ③ 落盘
        placed, cerr = _commit(entries, base)
        if not cerr:
            # "**必须**重启"不是客气话（三审 #3 / 兼容 #3）：恢复只把**文件**换掉，角色库 / 台词 /
            # 闹钟 / 行为这些服务对象里的副本还是旧的；调用方（pet_dialogs.open_restore）虽然会
            # 当场重载 cfg 拦掉"旧配置写回"，其余服务仍要重启才重读。
            return True, ("已从备份恢复 %d 个文件（%s 的数据，桌宠 %s 做的）；"
                          "恢复前的样子已快照到 %s；**必须重启桌宠**才会用上新数据"
                          % (len(placed), _short_time(man.get("created_at")),
                             man.get("app_version") or "?", snap))
        # ④ 回滚
        back_ok, back_msg = _rollback(snap, base, placed, now=when, root=root, source=source)
        if back_ok:
            return False, "恢复失败（%s），已经回退到恢复前的样子（快照：%s）" % (cerr, snap)
        return False, ("恢复失败（%s），而且回退也没成功（%s）：恢复前的数据在快照 %s 里，"
                       "可以手工解压找回" % (cerr, back_msg, snap))
    except RulesUnavailable as e:
        return False, str(e)
    except (OSError, RuntimeError) as e:
        return False, "恢复时出错（%s）——已中止" % (e,)
    finally:
        if staged is not None:
            _rmtree(staged)


def _make_snapshot(zip_path, base, when, snapshot_dir, app_version, root, source):
    """按候选位置依次尝试打快照 → (路径, err)。全部失败时 err 是最后一句人话。"""
    err = "没有可写的位置"
    for cand in snapshot_candidates(zip_path, base, when, snapshot_dir):
        ok, msg = create_backup(base, cand, app_version=app_version, now=when,
                                root=root, source=source)
        if ok:
            return cand, ""
        err = msg
    return "", err


def _commit(entries, base):
    """逐条落盘 → (已落盘的相对路径, err)。任一失败立刻停手（由调用方回滚）。"""
    placed = []
    for rec in entries:
        target = _target(base, rec["name"])
        if target is None:
            return placed, "目标路径越出了数据目录：%s" % rec["name"]
        try:
            with open(rec["staged"], "rb") as f:
                data = f.read()
        except OSError as e:
            return placed, "读临时文件失败（%s）" % (e,)
        err = _write_bytes(target, data)
        if err:
            return placed, "写 %s 失败（%s）" % (rec["name"], err)
        placed.append(rec["name"])
    return placed, ""


def _write_bytes(target, data):
    """落一个文件（**单一出口**：用例从这里注入"写某一条失败"的故障，不必改 pet_io）。"""
    return pet_io.atomic_write_bytes(target, data)


def _rollback(snap, base, placed, *, now=None, root=None, source=None):
    """用快照把已改的文件盖回去，并删掉这一趟新造出来的文件 → (ok, err)。"""
    staged = None
    try:
        staged = tempfile.mkdtemp(prefix="dfypet_rollback_")
        entries, _man, err = _inspect_zip(snap, base=base, root=root, source=source,
                                         dest_dir=staged, check_config_schema=False)
        if err:
            return False, "快照读不回来（%s）" % err
        keep = set(rec["name"] for rec in entries)
        _done, cerr = _commit(entries, base)
        if cerr:
            return False, "快照盖不回去（%s）" % cerr
        for rel in placed:
            if rel in keep:
                continue
            try:
                os.remove(_target(base, rel))
            except FileNotFoundError:
                continue
            except OSError as e:
                return False, "删不掉这一趟新加的文件 %s（%s）" % (rel, e)
        return True, ""
    finally:
        if staged is not None:
            _rmtree(staged)


# ---------------- 七、小工具 ----------------

def _now_or(now):
    """now 可注入（用例要"同一时钟写两次逐字节相同"这种判据）；None = 真的此刻。"""
    return datetime.datetime.now().astimezone() if now is None else now


def _stamp(when):
    """文件名时间戳：20261017-131500（字典序 = 时间序）。"""
    return when.strftime("%Y%m%d-%H%M%S")


def _iso(when):
    """manifest 里的时间：带时区偏移的 ISO-8601（用户换时区也能看出是哪一刻）。"""
    return when.isoformat(timespec="seconds")


def _short_time(text):
    """manifest 的 created_at → 给人看的一段（认不出来就原样给，不假装自己懂）。"""
    raw = str(text or "")
    try:
        return datetime.datetime.fromisoformat(raw).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return raw or "未知时间"


def _digest(obj):
    """任意可 JSON 化对象 → 12 位摘要（用来给"口径版本"一个可比较的指纹）。"""
    try:
        raw = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        raw = repr(obj)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _sha256_file(path):
    """文件的 sha256（分块读：几十 MB 的参考音也不会一次性进内存）。"""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _free_path(path):
    """同名已存在就加 -2 / -3…（同一秒里连做两次恢复不该互相覆盖快照）。"""
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    for i in range(2, 100):
        cand = "%s-%d%s" % (stem, i, ext)
        if not os.path.exists(cand):
            return cand
    return "%s-%d%s" % (stem, os.getpid(), ext)


def _size_text(size):
    """字节数 → 人话（48.2 KB）。"""
    try:
        num = int(size)
    except (TypeError, ValueError):
        return "未知大小"
    if num < 1024:
        return "%d B" % num
    for unit in ("KB", "MB", "GB"):
        num = num / 1024.0
        if num < 1024:
            return "%.1f %s" % (num, unit)
    return "%.1f TB" % (num / 1024.0)


def _join(names, limit=3):
    """列几个名字（多了就说"等 N 个"）——错误提示要能一眼看完。"""
    items = [str(n) for n in names]
    if len(items) <= limit:
        return "、".join(items)
    return "%s 等 %d 个" % ("、".join(items[:limit]), len(items))


def _base_name(path):
    return os.path.basename(str(path))


def _remove(path):
    """删一个临时文件（尽力而为：失败也只是垃圾，不该把已经成功的备份说成失败）。"""
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass    # 有意忽略：残留的 .tmp 由 pet_io.clean_tmp_files 那一套在退出时清


def _close_quietly(zf):
    """关一个可能只写了一半的 zip（失败路径上的清理，绝不再抛）。"""
    try:
        zf.close()
    except Exception:
        pass    # 有意忽略：清理路径尽力而为


def _rmtree(path):
    """删一个临时目录（staging / rollback 用；尽力而为，失败只是垃圾）。"""
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass    # 有意忽略：同上


if __name__ == "__main__":
    # 独立自检（不进产品路径）：造一个假数据目录，备份 → 改内容 → 恢复，逐条打印。
    # 跑法：python -B pet_backup.py（需要 _check_release.py 在旁边）
    _root = tempfile.mkdtemp(prefix="dfypet_backup_demo_")
    try:
        _data = os.path.join(_root, "data")
        os.makedirs(os.path.join(_data, "roles"))
        with open(os.path.join(_data, "config.json"), "wb") as _f:
            _f.write(b'{"a": 1}')
        with open(os.path.join(_data, "roles", "a.png"), "wb") as _f:
            _f.write(b"PNGDATA")
        with open(os.path.join(_data, "notes.txt"), "wb") as _f:
            _f.write(b"not user data")
        print("用户文件：", collect_user_files(_data))
        _when = datetime.datetime(2026, 10, 17, 13, 15, 0).astimezone()
        _zip = default_backup_path(_data, _when)
        print("备份：", create_backup(_data, _zip, app_version="demo", now=_when))
        print("清单：", json.dumps(read_manifest(_zip)[0], ensure_ascii=False, indent=2)[:400])
        print("校验：", verify_backup(_zip))
        with open(os.path.join(_data, "config.json"), "wb") as _f:
            _f.write(b'{"a": 2}')
        os.remove(os.path.join(_data, "roles", "a.png"))
        print("恢复：", restore_backup(_zip, _data))
        with open(os.path.join(_data, "config.json"), "rb") as _f:
            print("恢复后 config.json =", _f.read())
        with open(os.path.join(_data, "roles", "a.png"), "rb") as _f:
            print("恢复后 roles/a.png =", _f.read())
        print("快照：", list_snapshots(os.path.dirname(_zip)))
    finally:
        _rmtree(_root)
