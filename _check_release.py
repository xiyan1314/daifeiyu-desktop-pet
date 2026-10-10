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
# 发布包**额外**禁止的开发/验证文件（绿色版目录里做检测时允许存在）
ZIP_EXTRA_NAMES = {"_verify_green.py", "_check_release.py", "_check_static.py", "_g_out.txt"}
ZIP_EXTRA_PREFIX = ("_verify_assets/",)

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


def check_version():
    """版本三处一致检查。返回失败说明列表（空=通过）。"""
    version = repo_version()
    fails = []
    if not version:
        return ["桌宠.py 里读不到 VERSION"]
    vi = io.open(os.path.join(ROOT, "version_info.txt"), encoding="utf-8").read()
    vg = io.open(os.path.join(ROOT, "_verify_green.py"), encoding="utf-8").read()
    for field in ("FileVersion", "ProductVersion"):
        if not re.search(r"'%s'\s*,\s*'%s'" % (field, re.escape(version)), vi):
            fails.append("version_info.txt %s 与桌宠.py VERSION(%s) 不一致" % (field, version))
    # L-4 修复：用**断言语句**匹配（此前是全文子串匹配，注释里出现版本号也能蒙混过关）
    if not re.search(r'check\(\s*"green version"\s*,\s*main\.VERSION\s*==\s*"%s"'
                     % re.escape(version), vg):
        fails.append("_verify_green.py 的 green version 断言不是 %s" % version)
    # 版本号必须**升过**：如果该版本号已经有 git tag，说明改完代码没升版本号
    # （三处一致检查查不出这种漏升），发布前必须发现。
    # 版本号必须**升过**：三处一致检查查不出"改完代码没升版本"，改用两个不依赖 tag 的判据
    # （本仓库 v2.x 线从未打 tag，用 tag 判据会静默失效；给已发布版本打 tag 后又会误红）：
    #   ① CHANGELOG 的**首条**版本必须等于 VERSION（改完没写变更/没升版本 → 报）
    #   ② 运行时代码必须已提交（有未提交改动说明还没定版 → 报）
    try:
        cl = io.open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
        m_top = re.search(r"^##\s*v([0-9][\w.]*)", cl, re.M)
        top = m_top.group(1) if m_top else ""
        if top != version:
            fails.append("CHANGELOG.md 首条版本是 %r，与 VERSION %r 不一致（忘了升版本/写变更？）"
                         % (top or "无", version))
    except Exception as e:
        fails.append("CHANGELOG.md 读不到：%r" % (e,))
    return fails


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


def check_green_dir():
    """绿色版**目录**是否可打包（只查目录存在性）。

    v2.2.2 安全修复：绿色版目录**同时是用户正在使用的实时副本**——此前本检查把
    config.json/roles.json/ledger/roles 等**用户数据**当"打包前必须清"，
    导致每次发布都把用户的自定义角色（roles.json + roles 素材）删掉（真实事故）。
    打包安全其实不依赖这个检查：zip 从**白名单暂存目录**构建，用户数据根本进不了包。
    因此本检查只保留"目录存在"，用户数据永不要求清除。
    """
    if not os.path.isdir(GREEN):
        return ["绿色版目录不存在：%s" % GREEN]
    return []


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
               if os.path.basename(n) in USER_DATA_NAMES
               or os.path.basename(n) in ZIP_EXTRA_NAMES
               or any(n.startswith(p) for p in ZIP_EXTRA_PREFIX)
               or any(n.startswith(d + "/") for d in USER_DATA_DIRS)]
        if bad:
            fails.append("发布包含运行时数据/开发文件：%s" % ", ".join(sorted(bad)[:8]))
        # v2.3.0（兼容审查 S1）：need 必须覆盖**所有运行时 .py**——此前漏了 pet_tools.py，
        # 出包时白名单漏拷该文件会静默放行一个"双击即 ModuleNotFoundError"的包。
        # 正向校验：凡仓库里被 SYNC_FILES 列为运行时 .py 的，包里必须存在同名条目。
        # 注意排除 _verify_green.py：它随绿色版目录同步，但**按设计不进发布包**（自检脚本）
        _runtime_py = sorted(n for n in SYNC_FILES
                             if n.endswith(".py") and "/" not in n and n != "_verify_green.py")
        need = _runtime_py + ["python.exe", "assets/"]
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
        r = subprocess.run([sys.executable, script], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", cwd=ROOT, timeout=180, env=env)
    except Exception as e:
        return ["静态体检跑不起来：%r" % (e,)]
    if r.returncode == 0:
        return []
    lines = [x.strip() for x in (r.stdout or "").split("\n") if x.strip().startswith(("A ", "B ", "C ", "D ", "F ", "G ", "L "))]
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
    fails += check_green_dir()  # v2.2.2：只查目录存在；用户数据是用户实时数据，永不要求清除
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