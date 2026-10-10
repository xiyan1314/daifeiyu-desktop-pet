# -*- coding: utf-8 -*-
"""发布前检查（开发用，不进绿色版）：一跑就知道包能不能发。

检查项（每个都有独立函数，便于单测）：
  check_version()  版本三处一致：桌宠.py VERSION == version_info.txt 双字段 == _verify_green.py 断言
  check_sync()     绿色版目录里每个运行时代码/文档文件与仓库逐字节一致
  check_zip()      发布包干净（无运行时数据/开发文件）、含关键内容、包内版本不是旧版
  check_clean_tree()     工作树必须已提交；**删除（D）条目单独点名**（v2.4.3）
  check_asset_manifest() 工作区 assets 清单完整：git 索引 vs 磁盘（v2.4.3）
  check_shipped_files()  SYNC_FILES（代码/文档）在磁盘上都还在（v2.4.3）
  mutation_lock_problems() 变异验证进行中 → 结果不可信，拒绝判定（v2.4.3）
  mutation_evidence_notes() 变异结果 JSON 的源码指纹过期 → 提示"该证据需复跑"（v2.4.3）
  asset_manifest_notes() 素材清单判据没生效（无 git / 素材未入库）→ 提示（v2.4.3）

用法：python _check_release.py [zip路径]；退出码 0=通过，1=有问题（逐条打印）
"""
import hashlib
import io
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
GREEN = os.path.join(ROOT, "大肥鱼桌宠_绿色版")
ZIP_DEFAULT = os.path.join(ROOT, "daifeiyu-desktop-pet.zip")

# 必须与仓库保持一致的绿色版文件（运行时代码 + 文档 + 版本信息）
# 绿色版里"用户双击的入口"必须与仓库一致（兼容审查 M3：仓库此前根本没有这个文件）
VBS_NAME = "启动桌宠.vbs"

SYNC_FILES = ["桌宠.py", "main.py", "pet_actions.py", "pet_ai.py", "pet_alarm.py", "pet_anim.py",
              "pet_audio.py", "pet_balance.py", "pet_behaviors.py", "pet_book.py", "pet_chat.py",
              "pet_config.py", "pet_dialogs.py", "pet_export.py", "pet_fx.py", "pet_lines.py",
              "pet_io.py",   # v2.3.1：全仓共用原子 IO（被 8 个模块 import，漏了包必崩）
              "pet_log.py", "pet_main.py", "pet_menu.py", "pet_mood.py", "pet_physics.py",
              "pet_resources.py", "pet_screen.py", "pet_tools.py", "pet_voice.py", "pet_wander.py",
              "pet_weather.py", "pet_widgets.py", "version_info.txt", "_verify_green.py",
              "README.md", "README.en.md", "LICENSE", VBS_NAME]

# 用户运行时数据（绿色版目录与发布包里都不该有）
USER_DATA_NAMES = {"config.json", "roles.json", "audio.json", "voice.json", "voice_assets.json",
                   "voice_backend.json", "voice_backend.log", "alarms.json", "behaviors.json",
                   "lines.json", "ledger.json", "ledger_archive.json", "error.log",
                   "memory.log", "usage.json", "memory.json"}
USER_DATA_DIRS = ("roles", "voice", "voice_ref", "audio", "alarms", "__pycache__")

# v2.3.1（一致性收口）：精确名匹配挡不住**残留形态**——它们一样是用户数据（甚至是坏数据），
# 绝不能随绿色版目录或发布包出货，此前却能悄悄混进去：
#   <名字>.tmp / <名字>.<线程号>.tmp / <名字>.<进程号>.<线程号>.tmp
#        原子写临时文件（pet_io.atomic_write_bytes；崩溃/被杀时留下的正是这三种形状）
#   <名字>.bak      愈合前备份（pet_io.backup_before_heal）
#   <名字>.migrated pet_book 迁移旧 usage.json 时改的名
#   <名字>.old      pet_log 512KB 轮转出来的上一份日志（error.log.old）
#   <名字>.bad      pet_log._quarantine 隔离出来的坏/满日志（error.log.bad，v2.4 M2 补）
# 单独写成一个判据函数（单一来源），check_zip（发布包）与 check_green_dir（绿色版目录）共用。
_RESIDUE_RE = re.compile(r"^(?P<stem>.+?)\.(?:(?:[0-9]+\.){0,2}tmp|bak|migrated|old|bad)$")


def residue_hit(base):
    """文件名 → 命中的用户数据名（**只看残留形态**，精确名不算）；""=没命中。

    绿色版目录检查用它：那只目录同时是用户的实时数据目录，常规数据文件（config.json…）
    照旧允许存在（v2.2.2 事故），只有残留才点名。
    """
    m = _RESIDUE_RE.match(base)
    if m and m.group("stem") in USER_DATA_NAMES:
        return m.group("stem")
    return ""


def user_data_hit(base):
    """文件名 → 命中的用户数据名（""=没命中）。精确名与残留形态都算命中。

    发布包检查用它（包里出现用户数据或其残片都算不干净）。
    base 必须传 basename（发布包条目先取 basename；绿色版目录传文件名）。
    只认这几种形状，不会误伤正常文件：pet_io.py、assets/char.png、notes.tmp
    （stem 不是用户数据名）一律不算命中。
    """
    if base in USER_DATA_NAMES:
        return base
    return residue_hit(base)


# 发布包**额外**禁止的开发/验证文件（绿色版目录里做检测时允许存在）
# v2.4（M2/M3）：repro_quiet.py 是排障脚本——实测真包根目录里混进过一份
# （5820B，来自绿色版根目录的残留），而 ZIP_EXTRA_NAMES 不含它 → 门禁不报。
ZIP_EXTRA_NAMES = {"_verify_green.py", "_check_release.py", "_check_static.py", "_g_out.txt",
                   "repro_quiet.py"}
# v2.4.1（质量审查 L3）：整目录打包时 _dev/（开发脚本 + 审计报告 + 探针）会整体进包，
# 此前只有 _verify_assets/ 一条前缀黑名单拦不住 → 补 "_dev/"。（SYNC_FILES **不要**加
# _dev/ 里的报告文件：绿色版目录里没有它们，会让 check_sync 假红。）
ZIP_EXTRA_PREFIX = ("_verify_assets/", "_dev/")

# v2.4（M3）：绿色版**根目录**不许留下的开发脚本（_dev/ 里的同名前缀脚本不算——
# 那是绿色版的开发目录，按设计存在）。实测真包根目录混进过 repro_quiet.py。
# 只判根目录一层：os.walk 到子目录会误伤 _dev/。
_GREEN_ROOT_DEV_RE = re.compile(r"^(?:(?:repro_|e2e_).*|.*_dev.*\.py)$", re.IGNORECASE)

_VERSION_RE = re.compile(r'VERSION\s*=\s*"([^"]+)"')


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def repo_version():
    """仓库当前版本号（桌宠.py 的 VERSION）。"""
    src = io.open(os.path.join(ROOT, "桌宠.py"), encoding="utf-8").read()
    m = _VERSION_RE.search(src)
    return m.group(1) if m else ""


_NUM_VER_RE = re.compile(r"\b(filevers|prodvers)\s*=\s*\(([^)]*)\)")


def _ver_key(v):
    """版本串/数字串 → 可比较的四段整数元组（"2.4.0" 与 "(2, 4, 0, 0)" 等价）。

    非数字成分直接跳过（"2.4.1b1" → (2,4,1,1)）；不足四段补 0，避免 "2.4" 与 "2.4.0"
    比出"前者更小"这种假报警。
    """
    parts = [int(x) for x in re.findall(r"\d+", str(v or ""))][:4]
    return tuple(parts + [0] * (4 - len(parts)))


def numeric_versions(vi_text):
    """version_info.txt 文本 → {"filevers": (2,2,0,0), "prodvers": (...)}；读不到就不在表里。"""
    return {m.group(1): _ver_key(m.group(2)) for m in _NUM_VER_RE.finditer(vi_text or "")}


def version_problems(version, vi_text, vg_text, changelog_text):
    """版本一致性核对的**纯函数**（喂合成文本才能做"能失败"的对照）。

    判据（每条都对应一种真实"漏升版本 / 漏改字段"的方式）：
      ① version_info.txt 的 FileVersion / ProductVersion 字符串 == VERSION；
      ② **数字版本** filevers / prodvers == VERSION 的数字形态（v2.4.1 补：此前只比字符串，
         于是 exe 属性里的数字版本停在 2.2.0.0 也没人喊）；且 filevers 与 prodvers 必须一致；
      ③ _verify_green.py 的 green version 断言里是 VERSION（用断言语句匹配，注释不算）；
      ④ CHANGELOG **首条** == VERSION（改完没写变更/没升版本）；
      ⑤ VERSION 必须**大于 CHANGELOG 次条**（"首条被复制成上一条版本"这种漏升也能抓到）。
    运行时代码是否已提交由 check_clean_tree() 单独负责（开发期不能长期假红）。
    """
    fails = []
    for field in ("FileVersion", "ProductVersion"):
        if not re.search(r"'%s'\s*,\s*'%s'" % (field, re.escape(version)), vi_text or ""):
            fails.append("version_info.txt %s 与桌宠.py VERSION(%s) 不一致" % (field, version))
    nums = numeric_versions(vi_text)
    want = _ver_key(version)
    for field in ("filevers", "prodvers"):
        got = nums.get(field)
        if got is None:
            fails.append("version_info.txt 里读不到 %s（数字版本）" % field)
        elif got != want:
            fails.append("version_info.txt 的数字版本 %s=(%s) 与 VERSION %s（%s）不一致"
                         "（exe 属性里的文件版本会显示旧版：要么同步这两个数字，"
                         "要么在 version_info.txt 里写清它不受本判据管）"
                         % (field, ", ".join(str(x) for x in got), version,
                            ", ".join(str(x) for x in want)))
    if nums.get("filevers") is not None and nums.get("prodvers") is not None \
            and nums["filevers"] != nums["prodvers"]:
        fails.append("version_info.txt 的 filevers 与 prodvers 不一致：%r vs %r"
                     % (nums["filevers"], nums["prodvers"]))
    # L-4 修复：用**断言语句**匹配（此前是全文子串匹配，注释里出现版本号也能蒙混过关）
    if not re.search(r'check\(\s*"green version"\s*,\s*main\.VERSION\s*==\s*"%s"'
                     % re.escape(version), vg_text or ""):
        fails.append("_verify_green.py 的 green version 断言不是 %s" % version)
    m_all = re.findall(r"^##\s*v([0-9][\w.]*)", changelog_text or "", re.M)
    top = m_all[0] if m_all else ""
    if top != version:
        fails.append("CHANGELOG.md 首条版本是 %r，与 VERSION %r 不一致（忘了升版本/写变更？）"
                     % (top or "无", version))
    elif len(m_all) > 1 and _ver_key(version) <= _ver_key(m_all[1]):
        fails.append("VERSION %s 没有比 CHANGELOG 次条 v%s 大（版本号没升，或首条被复制成了上一条）"
                     % (version, m_all[1]))
    return fails


def check_version():
    """版本一致检查（读仓库真实文件 → version_problems 纯函数）。返回失败说明列表（空=通过）"""
    version = repo_version()
    if not version:
        return ["桌宠.py 里读不到 VERSION"]
    for name in ("version_info.txt", "_verify_green.py", "CHANGELOG.md"):
        if not os.path.isfile(os.path.join(ROOT, name)):
            return ["%s 读不到（发布门需要它）" % name]
    vi = io.open(os.path.join(ROOT, "version_info.txt"), encoding="utf-8").read()
    vg = io.open(os.path.join(ROOT, "_verify_green.py"), encoding="utf-8").read()
    cl = io.open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
    return version_problems(version, vi, vg, cl)


def check_clean_tree(root=None):
    """发布时才跑：运行时代码必须已提交（有未提交改动 = 还没定版）。

    单独成一个检查（而不是塞进 check_version()），否则开发期间本地护栏长期假红。

    v2.4.3（第三轮找茬收口）：判据抽成纯函数 clean_tree_problems()——删除（D）条目与
    普通未提交改动必须**分别点名**（见那里的说明）。root 可换，便于用合成 git 仓库做
    "能真失败"的对照用例。
    """
    base = os.path.abspath(root or ROOT)
    try:
        import subprocess
        # v2.2：扩展为**全仓** git status（此前只盯 SYNC_FILES，根目录散落的临时 .py /
        # 未提交脚本拦不住——发布物必须从干净的树打出去）
        # v2.4.3（兼容审查 L9）：-c core.quotepath=false + 显式 utf-8 解码。此前 git 把非
        # ASCII 路径按八进制转义输出（桌宠.py 显示成 \346\241\214...），最该一眼看到的入口
        # 文件反而最难认；关掉 quotepath 后 git 输出 UTF-8 原始路径，必须按 utf-8 解。
        st = subprocess.run(["git", "-c", "core.quotepath=false", "status", "--porcelain"],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", cwd=base, timeout=15)
        if st.returncode == 0 and st.stdout.strip():
            return clean_tree_problems(st.stdout)
    except Exception:
        pass  # 无 git（绿色版/离线环境）：跳过
    return []


_FULL_LIST_MAX = 200   # 报告里最多列出的条目数（超出只给计数，不静默）


def _full_list(items):
    """报告用：列出条目（v2.4.1：此前 [:8] 截断，第 9 条起永远看不见）。

    条目多时在末尾附总数，便于一眼判断规模。v2.4.1（找茬 L3）：这里此前是**无上限**全量，
    脏包/脏目录一旦有成千条残留，失败行会长得没法看（发布门要的是"看得见"，不是刷屏）
    → 上限 _FULL_LIST_MAX 条，超出部分**只给计数**（总数照报，不算静默）。
    """
    items = [str(x) for x in items]
    total = len(items)
    if total > _FULL_LIST_MAX:
        return ", ".join(items[:_FULL_LIST_MAX]) + "（共 %d 条，此处只列前 %d 条）" % (
            total, _FULL_LIST_MAX)
    tail = "（共 %d 条）" % total if total > 8 else ""
    return ", ".join(items) + tail


# ---------------- v2.4.3（第三轮找茬收口）：工作树删除 / 素材清单 / 变异锁 ----------------
# 三条都是本轮**真实踩到**的口子，且共同点是"只有全量门能抓，探针不变量照样 PASS"：
#   ① assets/idle_f03.png 被外部脚本删掉（工作树出现 ` D` 条目），3 条用例变红，
#      而"首屏至少 9 帧非空图"这条不变量依然 PASS（9 帧仍然成立）——从失败现象完全看不出
#      是"素材被删"还是"代码改坏了"；check_clean_tree 当时只说"有未提交改动"。
#   ② check_zip 只比对**包内** assets（包齐不齐），工作区少一张 shipped 素材它看不见。
#   ③ _dev 的变异脚本此前**原地覆写**产品源码：变异窗口里跑全量门会看到来源不明的红。

def classify_status(status_text):
    """git status --porcelain 文本 → {"deleted","renamed","changed","untracked"} 四类清单。

    条目名按 v2.3.0（兼容审查 L7）的口径取：splitlines + 去掉两字符状态 + strip
    （**不要**先 strip 整行再切片，会把首字符切掉）。
    """
    out = {"deleted": [], "renamed": [], "changed": [], "untracked": []}
    for line in (status_text or "").splitlines():
        if not line.strip():
            continue
        xy = line[:2]
        name = (line[3:] if len(line) > 3 else line).strip().strip('"')
        if xy == "??":
            out["untracked"].append(name)
        elif "R" in xy:
            out["renamed"].append(name)
        elif "D" in xy:
            out["deleted"].append(name)
        else:
            out["changed"].append(name)
    return out


def clean_tree_problems(status_text):
    """纯函数：git status --porcelain 文本 → 失败说明列表（空文本 = 干净）。

    分类而不是一句话概括（便于以后一眼分辨"素材被删"与"代码未提交"）：
      删除（D） → 受版本控制的文件在磁盘上没了。**独立一条**，因为它是"发布物缺件"
                   而不是"还没定版"；素材被外部脚本/清理工具带走就是这个形态。
      改动/改名  → 常见形态：代码改了还没提交。
      未跟踪（??）→ 也会随发布物流出的新文件。
    """
    cls = classify_status(status_text)
    fails = []
    if cls["deleted"]:
        fails.append("工作树里有**删除（D）**条目 %d 条（受版本控制的文件在磁盘上没了，"
                     "素材被外部脚本删掉就是这种形态；探针不变量可能照样 PASS）：%s"
                     % (len(cls["deleted"]), _full_list(cls["deleted"])))
    rest = cls["changed"] + cls["renamed"]
    if rest:
        fails.append("运行时代码有未提交改动（发布前先提交并定版）：%s" % _full_list(rest))
    if cls["untracked"]:
        fails.append("工作树里有未跟踪文件（发布物必须从干净的树打出去）：%s"
                     % _full_list(cls["untracked"]))
    return fails


ASSET_DIR = "assets"


def asset_manifest_problems(tracked, on_disk, new_files=None):
    """纯函数：git 索引里的 assets 清单 vs 磁盘实际文件 → 失败说明列表。

    tracked / on_disk 都是仓库相对路径（正斜杠）。两个方向都要报，各自对应一种真实事故：
      ① 索引里有、磁盘上没有 → "工作区少了一张 shipped 素材"（本轮真踩到的那条：
         idle_full 帧/角色图少一张时，包内自检与探针都可能照样过）。
      ② 磁盘上有、索引里没有 → 新素材没入库（发布包里那份与仓库不一致，且第二天
         别人 clone 就少文件）。

    v2.4.3（质量审查 L2）：② 只对**未被 .gitignore 忽略**的文件报（new_files 传
    git ls-files -o --exclude-standard 的结果）。此前实测：.gitignore 加一条 *.bak、
    assets/ 下再放个 a.png.bak，发布门就把它报成"未入库素材"——被明确忽略的文件不是
    "忘了 git add"，真仓今天不误报只是因为恰好没有 assets 相关的忽略规则。
    new_files=None（无 git / 老调用方）退回旧口径：所有磁盘多出来的都报。
    """
    missing = sorted(set(tracked) - set(on_disk))
    extra = sorted(set(on_disk) - set(tracked))
    if new_files is not None:
        extra = sorted(set(extra) & set(new_files))
    fails = []
    if missing:
        fails.append("工作区缺少已入库素材 %d 个（git 里有、磁盘上没有：素材被删或被清理工具"
                     "带走）：%s" % (len(missing), _full_list(missing)))
    if extra:
        fails.append("工作区有未入库素材 %d 个（磁盘上有、git 里没有：先 git add 再发布）：%s"
                     % (len(extra), _full_list(extra)))
    return fails


def _git_out(root, args, timeout=20):
    """git 命令 → stdout（rc!=0 或无 git 返回 None）。"""
    import subprocess
    try:
        r = subprocess.run(["git"] + list(args), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", cwd=root, timeout=timeout)
    except Exception:
        return None
    return r.stdout if r.returncode == 0 else None


def tracked_assets(root=None):
    """git 索引里的 assets/ 文件清单（正斜杠相对路径，排序）；无 git/无 assets → []。"""
    base = os.path.abspath(root or ROOT)
    out = _git_out(base, ["ls-files", "-z", "--", ASSET_DIR])
    if not out:
        return []
    return sorted(p.replace("\\", "/") for p in out.split("\0") if p.strip())


def disk_assets(root=None):
    """磁盘上 assets/ 下的全部文件（正斜杠相对路径，排序）。"""
    base = os.path.abspath(root or ROOT)
    top = os.path.join(base, ASSET_DIR)
    out = []
    if not os.path.isdir(top):
        return out
    for cur, _dirs, files in os.walk(top):
        for f in files:
            out.append(os.path.relpath(os.path.join(cur, f), base).replace("\\", "/"))
    return sorted(out)


def untracked_assets(root=None):
    """assets/ 下**未被 .gitignore 忽略**的新文件（正斜杠相对路径，排序）。

    无 git / 命令失败 → None（调用方退回旧口径，不因读不到而放行整个判据）。
    """
    base = os.path.abspath(root or ROOT)
    try:
        import subprocess
        r = subprocess.run(["git", "ls-files", "-o", "--exclude-standard", "-z", "--", ASSET_DIR],
                           capture_output=True, cwd=base, timeout=20)
    except Exception:
        return None
    if r.returncode != 0:
        return None
    text = r.stdout.decode("utf-8", "replace")
    return sorted(p.replace("\\", "/") for p in text.split("\0") if p.strip())


def check_asset_manifest(root=None):
    """工作区素材清单完整性（v2.4.3 新增）。

    为什么单独一条：check_zip 只比对**包内**条目、check_sync 只比对**绿色版目录**——
    两个都发现不了"仓库工作区少了一张 shipped 素材"（包从工作区构建，工作区缺件才会
    让包缺件；但那时的报错是"包缺关键内容"，排查方向被带偏）。无 git（绿色版/离线）跳过。
    """
    base = os.path.abspath(root or ROOT)
    if not os.path.isdir(os.path.join(base, ASSET_DIR)):
        return []
    tracked = tracked_assets(base)
    if not tracked:
        return []   # 无 git / assets 未入库：交给 check_clean_tree 的未跟踪判据
    return asset_manifest_problems(tracked, disk_assets(base), untracked_assets(base))


def asset_manifest_notes(root=None):
    """素材清单判据**没有生效**时的一句提示（不挡发布，但绝不静默）。

    v2.4.3（第三轮找茬复审 L③）：此前 tracked_assets() 为空（无 git / assets 未入库 /
    assets 目录不存在）时 check_asset_manifest() 直接 return []——看起来"通过"，其实这条
    判据一次都没跑。真仓/绿色版都可能落到这个分支，所以给一句提示。
    """
    base = os.path.abspath(root or ROOT)
    if not os.path.isdir(os.path.join(base, ASSET_DIR)):
        return ["素材清单判据没生效：%s 目录不存在" % ASSET_DIR]
    if not tracked_assets(base):
        return ["素材清单判据没生效：git 里读不到 %s 的清单（无 git，或素材全未入库）"
                "——'工作区缺件'这一路这次没有检查" % ASSET_DIR]
    return []


def check_shipped_files(root=None):
    """SYNC_FILES（运行时代码 + 文档）在工作区是否都还在。缺失 = 同样的"发布物缺件"。"""
    base = os.path.abspath(root or ROOT)
    gone = [n for n in SYNC_FILES
            if not os.path.isfile(os.path.join(base, n.replace("/", os.sep)))]
    if not gone:
        return []
    return ["工作区缺少运行时/文档文件 %d 个（发布物清单里有、磁盘上没有）：%s"
            % (len(gone), _full_list(gone))]


MUTATION_LOCK = os.path.join(ROOT, "_dev", ".mutation.lock")
MUTATION_LOCK_STALE_H = 2.0   # 超过这么久的锁按"陈旧"处理（进程崩了别把发布门永久卡死）


def _lock_entries(path, now):
    """锁路径 → [(条目名, info, 小时数)]。

    两种形态都认：**目录**（新口径：一个持有者一个 <pid>.json，能同时挂多个变异进程）与
    **文件**（旧版单文件锁，仍可能是别人手上留下的）。
    """
    import json as _json
    if os.path.isdir(path):
        paths = [os.path.join(path, n) for n in sorted(os.listdir(path))
                 if os.path.isfile(os.path.join(path, n))]
    elif os.path.isfile(path):
        paths = [path]
    else:
        return []
    out = []
    for p in paths:
        try:
            info = _json.load(open(p, encoding="utf-8"))
        except Exception:
            info = {}
        try:
            age = (now - os.path.getmtime(p)) / 3600.0
        except OSError:
            age = 0.0
        out.append((os.path.basename(p), info, age))
    return out


def _lock_who(info):
    """锁条目里的人类可读身份（pid/what/开始时间）；读不出来就空串。"""
    if not isinstance(info, dict):
        return ""
    return " pid=%s what=%s started=%s" % (info.get("pid", "?"), info.get("what", "?"),
                                           info.get("started_at", "?"))


def mutation_lock_problems(root=None, now=None):
    """变异验证运行锁 → (fails, notes)。

    v2.4.3：_dev 的变异脚本现在一律在 %TEMP% 影子副本里变异（真实仓库只读），这个锁是
    **双保险**：万一手工在树内做了变异（或旧脚本还在跑），发布门要明确说"此刻的测试结果
    不可信"，而不是让人对着一堆无关用例的失败猜（本轮真发生过，浪费了两位审查员的时间）。
    活的锁 → fails（拒绝判定）；陈旧锁（进程崩了没清）→ notes（只提示，不挡发布）。
    """
    import time as _time
    base = os.path.abspath(root or ROOT)
    path = os.path.join(base, "_dev", os.path.basename(MUTATION_LOCK))
    if now is None:
        now = _time.time()
    entries = _lock_entries(path, now)
    live = [e for e in entries if e[2] <= MUTATION_LOCK_STALE_H]
    stale = [e for e in entries if e[2] > MUTATION_LOCK_STALE_H]
    fails, notes = [], []
    if live:
        fails.append("变异验证正在运行（%s%s）：此刻的测试/门禁结果不可信——等它跑完"
                     "（或确认进程已停后清掉该锁）再重跑发布检查。"
                     % (path, "".join(_lock_who(i) for _n, i, _a in live)))
    if stale:
        notes.append("发现**陈旧**的变异锁 %s（%s）：进程大概已崩，确认没有变异在跑后清掉它即可"
                     "（现在的变异脚本都在 %%TEMP%% 影子副本里跑，正常退出不会留锁）。"
                     % (path, "；".join("%s：%.1f 小时前%s" % (n, a, _lock_who(i))
                                        for n, i, a in stale)))
    return fails, notes


# ---------------- v2.4.3（质量审查 M4）：变异证据的源码指纹必须对着出货修订 ----------------
# _dev/_mutate_lib.repo_fingerprint 记录的是**变异当时**那几个关键文件的 sha256 前 12 位，
# 但此前没有任何人比对：结果 JSON 里 桌宠.py 记的是 059b7abfa512 / 2ac5743967b1，当前树是
# 另一个值 —— 也就是说那些"N/N 全抓到"不是对着出货的那份源码测的。
# 这里只做**提示**（不进 fails）：证据过期是开发期的正常中间态；但绝不能静默。
# 文件清单与 _dev/_mutate_lib.repo_fingerprint 同口径，由 tests/test_release_check.py 的
# 一条用例钉住"两处清单不许漂移"。
MUTATION_FINGERPRINT_FILES = ("桌宠.py", "pet_export.py", "pet_lines.py", "pet_alarm.py",
                              "pet_behaviors.py", "_check_release.py")


def file_fingerprint(path):
    """sha256 前 12 位；读不到 → 空串（与 _dev/_mutate_lib.repo_fingerprint 同口径）。"""
    import hashlib
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:12]
    except OSError:
        return ""


def tree_fingerprint(root=None):
    """当前树的关键文件指纹（只在文件存在时收录）。"""
    base = os.path.abspath(root or ROOT)
    out = {}
    for rel in MUTATION_FINGERPRINT_FILES:
        p = os.path.join(base, rel)
        if os.path.isfile(p):
            out[rel] = file_fingerprint(p)
    return out


def stale_fingerprints(recorded, current):
    """记录指纹 vs 当前指纹 → 不一致项（"文件: 旧→新"）。recorded 为空/非 dict → []。"""
    if not isinstance(recorded, dict) or not recorded:
        return []
    out = []
    for rel in sorted(recorded):
        got, want = recorded.get(rel), (current or {}).get(rel)
        if got and want and got != want:
            out.append("%s: %s→%s" % (rel, got, want))
    return out


def mutation_evidence_notes(root=None, current=None):
    """_dev/*.json 里记的源码指纹 ≠ 当前树 → 每条一句"该证据已过期，需复跑"提示。

    两种落盘形态都认：结果 JSON 顶层 repo_fingerprint、以及 spec 内嵌的
    results.repo_fingerprint（mutate_check.py 回写的那种）。没有指纹段的 JSON 跳过。
    """
    import json as _json
    base = os.path.abspath(root or ROOT)
    dev = os.path.join(base, "_dev")
    cur = current if current is not None else tree_fingerprint(base)
    notes = []
    if not os.path.isdir(dev):
        return notes
    for name in sorted(os.listdir(dev)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(dev, name), encoding="utf-8") as f:
                data = _json.load(f)
        except Exception:
            continue
        rec = data.get("repo_fingerprint") if isinstance(data, dict) else None
        if not isinstance(rec, dict) and isinstance(data, dict):
            res = data.get("results")
            rec = res.get("repo_fingerprint") if isinstance(res, dict) else None
        stale = stale_fingerprints(rec, cur)
        if stale:
            notes.append("变异证据 %s 的源码指纹已过期（不是对着当前树测的，复核前请重跑"
                         "对应 spec）：%s" % (name, "；".join(stale)))
    return notes


def green_residue(root=None):
    """绿色版目录里的用户数据**残留**清单（相对路径，排序）；不含常规用户数据文件。

    残留 = <用户数据名> + 后缀（见 _RESIDUE_RE）：临时文件 / 愈合备份 / 迁移改名 / 轮转日志。
    它们是原子写与自愈流程的中间产物，没有任何保留价值，留在打包目录里就是"可能混进
    发布物"的风险。本函数**只点名不删除**（要移走还是清掉由用户决定）。
    """
    base = os.path.abspath(root or GREEN)
    out = []
    if not os.path.isdir(base):
        return out
    for cur, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d != "__pycache__"]   # 目录本身另有判据（USER_DATA_DIRS）
        for f in files:
            if residue_hit(f):      # 只看残留：常规用户数据文件不在这里点名（v2.2.2）
                out.append(os.path.relpath(os.path.join(cur, f), base).replace("\\", "/"))
    return sorted(out)


def green_root_dev_leftovers(root=None):
    """绿色版**根目录**里残留的开发/排障脚本（相对名，排序）；_dev/ 内的不算。

    v2.4（M3）：实测真包根目录混进过 repro_quiet.py（来自绿色版根目录那份），
    而 check_zip 的 ZIP_EXTRA_NAMES 此前不含它 → 门禁放行。这里在**源头**（绿色版目录）
    点名：打包脚本按"根目录白名单/整目录复制"两种做法都会把它带进包。
    """
    base = os.path.abspath(root or GREEN)
    out = []
    if not os.path.isdir(base):
        return out
    for f in sorted(os.listdir(base)):
        if os.path.isfile(os.path.join(base, f)) and _GREEN_ROOT_DEV_RE.match(f):
            out.append(f)
    return out


def check_green_dir():
    """绿色版**目录**是否可打包（目录存在 + 没有用户数据残留 + 根目录没有开发脚本）。

    v2.2.2 安全修复：绿色版目录**同时是用户正在使用的实时副本**——此前本检查把
    config.json/roles.json/ledger/roles 等**用户数据**当"打包前必须清"，
    导致每次发布都把用户的自定义角色（roles.json + roles 素材）删掉（真实事故）。
    打包安全其实不依赖这个检查：zip 从**白名单暂存目录**构建，用户数据根本进不了包。
    因此**常规用户数据文件名永不作为失败项**（config.json/roles.json/账本…照旧留着）。

    v2.3.1（一致性收口）：只说"目录存在"还不够——残留形态（<名字>.tmp /
    <名字>.<pid>.<tid>.tmp / <名字>.bak / <名字>.migrated / <名字>.old / <名字>.bad）是崩溃
    与自愈的中间产物，混进绿色版目录就可能被一起打包 → 这里点名（只报不移）。

    v2.4（M2/M3）：再加两类——① .bad（pet_log 隔离出的坏/满日志）；② 根目录的
    repro_*/e2e_*/*_dev*.py 排障脚本（_dev/ 内的不算）。两项都是实测真包里出现过的东西。
    """
    if not os.path.isdir(GREEN):
        return ["绿色版目录不存在：%s" % GREEN]
    fails = []
    residue = green_residue()
    if residue:
        fails.append("绿色版目录里有用户数据残留（临时文件/愈合备份/轮转日志，打包前请移出）：%s"
                     % _full_list(residue))
    # v2.4（M3）：根目录的开发/排障脚本同样是"会随包发出去"的东西（实测 repro_quiet.py
    # 进过真包）。_dev/ 里的同名脚本按设计保留，不算。
    dev = green_root_dev_leftovers()
    if dev:
        fails.append("绿色版根目录有开发/排障脚本残留（_dev/ 内的不算，打包前请移出）：%s"
                     % _full_list(dev))
    return fails


def _sync_pairs():
    """要对比的（相对路径）清单：显式文件 + assets/ 下全部文件（M3：素材漂移也要能发现）。"""
    out = list(SYNC_FILES)
    a_dir = os.path.join(ROOT, "assets")
    if os.path.isdir(a_dir):
        for root, _dirs, files in os.walk(a_dir):
            for f in sorted(files):
                out.append(os.path.relpath(os.path.join(root, f), ROOT).replace("\\", "/"))
    return out


def check_sync():
    """绿色版与仓库同步检查。返回 (缺失列表, 内容不一致列表)。"""
    missing, diff = [], []
    for name in _sync_pairs():
        a = os.path.join(ROOT, name.replace("/", os.sep))
        b = os.path.join(GREEN, name.replace("/", os.sep))
        if not os.path.isfile(b):
            missing.append(name)
        elif os.path.isfile(a) and _sha(a) != _sha(b):
            diff.append(name)
    return missing, diff


def _normalize_names(names):
    """把"整包套了一层顶层目录"的条目名剥掉那层前缀（M2：否则前缀检查全失效）。

    判定：所有条目的第一段只有一种取值、且不存在与该段同名的文件条目。
    """
    parts = {n.split("/", 1)[0] for n in names if n}
    if len(parts) != 1:
        return list(names)
    top = parts.pop()
    if top in names:
        return list(names)  # 既有同名文件又有同名前缀目录：不当作"整包套目录"
    return [(n[len(top) + 1:] if n.startswith(top + "/") else n) for n in names]


def check_zip(zip_path, version=None):
    """发布包检查（干净/完整/版本）。返回失败说明列表。"""
    version = version or repo_version()
    if not os.path.isfile(zip_path):
        return ["发布包不存在：%s" % zip_path]
    fails = []
    with zipfile.ZipFile(zip_path) as z:
        names = _normalize_names(z.namelist())
        bad = [n for n in names
               if user_data_hit(os.path.basename(n))
               or os.path.basename(n) in ZIP_EXTRA_NAMES
               or any(n.startswith(p) for p in ZIP_EXTRA_PREFIX)
               or any(n.startswith(d + "/") for d in USER_DATA_DIRS)]
        if bad:
            fails.append("发布包含运行时数据/残留/开发文件：%s" % _full_list(sorted(bad)))
        # v2.3.0（兼容审查 S1）：need 必须覆盖**所有运行时 .py**——此前漏了 pet_tools.py，
        # 出包时白名单漏拷该文件会静默放行一个"双击即 ModuleNotFoundError"的包。
        # v2.4（M2/M3）：need 改成**全量正向校验**——直接用 _sync_pairs()（SYNC_FILES +
        # assets/ 下每一个文件）。此前只查 "assets/" 这个**前缀**存不存在 → 实测真包里
        # idle_full 帧条目 0 个、assets 只有 140/150 也照样放行：素材漏拷能一路发出去。
        # 唯一的例外仍是 _verify_green.py：它随绿色版目录同步，但**按设计不进发布包**
        # （自检脚本，进包反而会被 ZIP_EXTRA_NAMES 判为不干净）。
        need = [n for n in _sync_pairs() if n != "_verify_green.py"] + ["python.exe"]
        lack = [n for n in need if not any(x == n or x.startswith(n) for x in names)]
        if lack:
            fails.append("发布包缺关键内容：%s" % ", ".join(lack))
        try:
            raw = z.read("桌宠.py")
            m = _VERSION_RE.search(raw.decode("utf-8", "replace"))
            zv = m.group(1) if m else "?"
            if zv != version:
                fails.append("发布包里是旧版本：%s（仓库是 %s）" % (zv, version))
            # M3：版本号相同也可能是旧包 → 再比内容（包内 桌宠.py 必须与仓库逐字节一致）
            import hashlib
            repo_main = os.path.join(ROOT, "桌宠.py")
            if os.path.isfile(repo_main):
                with open(repo_main, "rb") as f:
                    repo_raw = f.read()
                if hashlib.sha256(raw).hexdigest() != hashlib.sha256(repo_raw).hexdigest():
                    fails.append("发布包里的 桌宠.py 与仓库内容不一致（包是旧的/未重新打包）")
            # v2.4.1（质量审查 L2）：数字版本判据此前只覆盖**仓库根**那份 version_info.txt
            # （version_problems 读的是 ROOT），而真正发出去的是包内那份——包里那份停在
            # (2, 2, 0, 0) 也照样能装出去（exe 属性显示旧版本号）。这里直接读包内那份比。
            try:
                _vi_raw = z.read("version_info.txt").decode("utf-8", "replace")
            except KeyError:
                _vi_raw = ""
            _nums = numeric_versions(_vi_raw)
            _want = _ver_key(version)
            for _field in ("filevers", "prodvers"):
                _got = _nums.get(_field)
                if _got is not None and _got != _want:
                    fails.append(
                        "发布包里 version_info.txt 的数字版本 %s=(%s) 与 VERSION %s（%s）不一致"
                        "（exe 属性会显示旧版本；根目录那份对了不代表包内那份对）"
                        % (_field, ", ".join(str(x) for x in _got), version,
                           ", ".join(str(x) for x in _want)))
        except KeyError:
            fails.append("发布包里没有 桌宠.py")
    return fails


# v2.4（L1）：静态体检 stdout 里"失败条目"的行前缀（单一来源，供下面的解析与单测共用）。
# M 类（Signal 参数一致性）此前不在表里 → 它失败时解析不出条目，只能退化打印 stdout 尾巴。
STATIC_FAIL_PREFIXES = ("A ", "B ", "C ", "D ", "F ", "G ", "L ", "M ")


def _static_fail_lines(stdout):
    """静态体检 stdout → 失败条目行（去空白、按前缀过滤）。"""
    return [x.strip() for x in (stdout or "").split("\n")
            if x.strip().startswith(STATIC_FAIL_PREFIXES)]


def check_static():
    """跑静态体检（_check_static.py），有问题就带进发布检测结果。"""
    import subprocess
    script = os.path.join(ROOT, "_check_static.py")
    if not os.path.isfile(script):
        return []
    try:
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["PYTHONIOENCODING"] = "utf-8"
        # v2.3.1（M1）：静态体检单跑实测 120.4s（并发跑其它检查时更慢），180s 会随机超时
        # → 发布门随机变红。放宽到 600s：宁可慢一点，也不要"体检没跑完就报失败"。
        r = subprocess.run([sys.executable, script], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", cwd=ROOT, timeout=600, env=env)
    except Exception as e:
        return ["静态体检跑不起来：%r" % (e,)]
    if r.returncode == 0:
        return []
    lines = _static_fail_lines(r.stdout)
    if lines:
        return ["静态体检有问题：%s" % "; ".join(lines[:5])]
    # 没解析出条目时把 stdout/stderr 尾巴都带上（否则只有一句"退出码 1"，没法排障；
    # 注意"缺少 Qt/依赖"这类友好结论是打在 **stdout** 上的）
    tail = " | ".join([x.strip() for x in ((r.stdout or "") + "\n" + (r.stderr or "")).split("\n")
                       if x.strip()][-3:])
    return ["静态体检退出码 %d%s" % (r.returncode, ("；stderr: " + tail) if tail else "")]


def main():
    zip_path = sys.argv[1] if len(sys.argv) > 1 else ZIP_DEFAULT
    fails = []
    version = repo_version()
    print("[1] 版本一致：%s" % version)
    fails += check_version()
    fails += check_clean_tree()  # v2.1.4：发布时运行时代码必须已提交（定版）
    # v2.4.3（第三轮找茬收口）：工作区缺件与素材清单——本轮 assets/idle_f03.png 被外部
    # 脚本删掉时只有全量 pytest 变红，发布门（check_clean_tree）只说"有未提交改动"、
    # check_zip 只查包内，谁都没点名"少了一张 shipped 素材"。
    _lock_fails, _lock_notes = mutation_lock_problems()
    fails += _lock_fails
    for _note in _lock_notes + mutation_evidence_notes() + asset_manifest_notes():
        print("  [提示] %s" % _note)
    print("[1b] 工作区清单：assets 索引 %d 个 / 磁盘 %d 个，SYNC_FILES %d 个"
          % (len(tracked_assets()), len(disk_assets()), len(SYNC_FILES)))
    fails += check_shipped_files()
    fails += check_asset_manifest()
    fails += check_static()  # v2.1.4：静态体检（入口解析/配置键/空池/类型转换/定时器/线程…）
    # v2.2.2：用户数据是用户实时数据，永不要求清除（只查目录存在 + 残留点名）
    fails += check_green_dir()
    missing, diff = check_sync()
    print("[2] 绿色版同步：%d 个文件（缺失 %d，不一致 %d）"
          % (len(SYNC_FILES), len(missing), len(diff)))
    if missing:
        fails.append("绿色版缺文件：%s" % ", ".join(missing))
    if diff:
        fails.append("绿色版内容与仓库不一致（需重新同步）：%s" % ", ".join(diff))
    if os.path.isfile(zip_path):
        print("[3] 发布包：%s" % zip_path)
        fails += check_zip(zip_path, version)
    else:
        fails.append("发布包不存在：%s" % zip_path)
    if fails:
        print("\nFAILED:")
        for f in fails:
            print("  -", f)
        return 1
    print("\nRELEASE CHECK OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())