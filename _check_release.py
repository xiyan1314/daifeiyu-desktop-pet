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
              "pet_resources.py", "pet_screen.py", "pet_voice.py", "pet_wander.py",
              "pet_weather.py", "pet_widgets.py", "version_info.txt", "_verify_green.py",
              "README.md", "README.en.md", "LICENSE", VBS_NAME]

# 用户运行时数据（绿色版目录与发布包里都不该有）
USER_DATA_NAMES = {"config.json", "roles.json", "audio.json", "voice.json", "voice_assets.json",
                   "voice_backend.json", "voice_backend.log", "alarms.json", "behaviors.json",
                   "lines.json", "ledger.json", "ledger_archive.json", "error.log",
                   "memory.log", "usage.json", "memory.json"}
USER_DATA_DIRS = ("roles", "voice", "voice_ref", "audio", "alarms", "__pycache__")
# 发布包**额外**禁止的开发/验证文件（绿色版目录里做检测时允许存在）
ZIP_EXTRA_NAMES = {"_verify_green.py", "_check_release.py", "_g_out.txt"}
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
    return fails


def check_green_dir():
    """绿色版**目录**里是否混入**用户运行时数据**。

    注意（兼容审查 S1）：_verify_green.py / _verify_assets/ 是**检测资产**，跑绿色版检测时
    必须在该目录里存在——它们只在**发布包**中被禁止（见 check_zip 的 ZIP_EXTRA_*）。
    此前把两者混在同一个黑名单里，导致本检查在任何状态下都不可能通过（自相矛盾）。
    """
    bad = []
    if not os.path.isdir(GREEN):
        return ["绿色版目录不存在：%s" % GREEN]
    for name in sorted(USER_DATA_NAMES):
        if os.path.exists(os.path.join(GREEN, name)):
            bad.append(name)
    for name in USER_DATA_DIRS:
        if os.path.isdir(os.path.join(GREEN, name)):
            bad.append(name + "/")
    return ["绿色版目录里有用户运行时数据（打包前必须清）：%s" % ", ".join(sorted(bad))] \
        if bad else []


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
            fails.append("发布包含运行时数据/开发文件：%s" % ", ".join(sorted(bad)[:5]))
        need = ["桌宠.py", "main.py", "pet_voice.py", "pet_lines.py", "pet_dialogs.py",
                "python.exe", "assets/"]
        lack = [n for n in need if not any(x == n or x.startswith(n) for x in names)]
        if lack:
            fails.append("发布包缺关键内容：%s" % ", ".join(lack))
        try:
            m = _VERSION_RE.search(z.read("桌宠.py").decode("utf-8", "replace"))
            zv = m.group(1) if m else "?"
            if zv != version:
                fails.append("发布包里是旧版本：%s（仓库是 %s）" % (zv, version))
        except KeyError:
            fails.append("发布包里没有 桌宠.py")
    return fails


def main():
    zip_path = sys.argv[1] if len(sys.argv) > 1 else ZIP_DEFAULT
    fails = []
    version = repo_version()
    print("[1] 版本一致：%s" % version)
    fails += check_version()
    fails += check_green_dir()  # L7：绿色版目录本身也不能有运行时数据
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