# -*- coding: utf-8 -*-
"""发布前检查（开发用，不进绿色版）：一跑就知道包能不能发。

检查项（每个都有独立函数，便于单测）：
  check_version()  版本三处一致：桌宠.py VERSION == version_info.txt 双字段 == _verify_green.py 断言
  check_sync()     绿色版目录里每个运行时代码/文档文件与仓库逐字节一致
  check_zip()      发布包干净（无运行时数据/开发文件）、含关键内容、包内版本不是旧版

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
ZIP_EXTRA_PREFIX = ("_verify_assets/",)

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


def check_clean_tree():
    """发布时才跑：运行时代码必须已提交（有未提交改动 = 还没定版）。

    单独成一个检查（而不是塞进 check_version()），否则开发期间本地护栏长期假红。
    """
    try:
        import subprocess
        # v2.2：扩展为**全仓** git status（此前只盯 SYNC_FILES，根目录散落的临时 .py /
        # 未提交脚本拦不住——发布物必须从干净的树打出去）
        st = subprocess.run(["git", "status", "--porcelain"],
                            capture_output=True, text=True, cwd=ROOT, timeout=15)
        if st.returncode == 0 and st.stdout.strip():
            # v2.3.0（兼容审查 L7）：用 splitlines + 去状态前缀——此前 strip() 吃掉首行
            # 前导空格后再 [3:] 会把首字符切掉（实测输出 "et_ai.py"）
            dirty = [(l[3:] if len(l) > 3 else l).strip()
                     for l in st.stdout.splitlines() if l.strip()][:3]
            return ["运行时代码有未提交改动（发布前先提交并定版）：%s" % ", ".join(dirty)]
    except Exception:
        pass  # 无 git（绿色版/离线环境）：跳过
    return []


def _full_list(items):
    """报告用：**全量**列出条目（v2.4.1：此前 [:8] 截断，第 9 条起永远看不见）。

    条目多时在末尾附总数，便于一眼判断规模；一条都不省略——发布门的意义就是"看得见"。
    """
    items = [str(x) for x in items]
    tail = "（共 %d 条）" % len(items) if len(items) > 8 else ""
    return ", ".join(items) + tail


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