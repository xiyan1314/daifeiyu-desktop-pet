# -*- coding: utf-8 -*-
"""pet_backup 的「还原就红」探针（v2.11.0 · W1-b）：把每条判据逐个拿掉，点名的用例必须变红。

为什么要有它：本仓的判据标准不是"跑过了"，而是"**把这一行拿掉，那条用例必须红**"
（_dev/VERIFY_DISCIPLINE.md §二/§三）。tests/test_backup_v2110.py 的每条用例 docstring 里都写了
一句"能真失败：…"，那些话必须能当场兑现——这个脚本就是兑现的地方。

为什么在影子副本里改（而不是原地）：_dev/README.md 铁律 6。整棵仓太大（绿色版几百 MB），
这里只复制**跑得起来的最小集合**（备份模块 + 它 import 的三个模块 + 白名单真源 + 测试文件），
真仓全程只读。

跑法：
    python -B _dev/probe_backup_v2110.py            # 全部
    python -B _dev/probe_backup_v2110.py zip_slip   # 只跑 id 含该子串的
退出码 0 = 每条都 CAUGHT（且有基线）；1 = 有 ANCHOR-LOST / NOT CAUGHT / WRONG TEST。

判定口径（与 _dev/mutate_check.py 同一取舍，不许放宽）：
  · 基线必须先绿（不绿就等于"探针坏了"，此时"全 CAUGHT"与"什么都没测到"长得一模一样）；
  · 变异后 rc != 0 **且** 点名的用例出现在 FAILED/ERROR 行里，才算 CAUGHT；
  · rc != 0 但红的是别的用例 = WRONG TEST（同样算没被验证）。
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# 影子副本需要的最小集合（多一个文件都不复制：这样"影子能跑"本身就是一条口径）
COPIES = ("pet_backup.py",            # 被测模块
          "pet_io.py", "pet_export.py", "pet_plugin.py",   # 它 import 的三个运行时模块
          "pet_guard.py",   # _skip_names() 惰性 import 它取熔断标记的文件名（M27 用它）
          "pet_log.py", "pet_motion.py",                   # tests/conftest.py 的两个夹具 import 它们
          "_check_release.py",                             # 白名单真源
          "pytest.ini",
          "tests/conftest.py", "tests/test_backup_v2110.py")

TESTFILE = "tests/test_backup_v2110.py"
TARGET = "pet_backup.py"


def _m(mid, test, why, *edits):
    """一条变异：把 TARGET 里的 old 换成 new（old 必须**恰好命中 1 次**）。"""
    return {"id": mid, "test": test, "why": why, "edits": list(edits)}


MUTATIONS = [
    _m("M01-条目名安全线",
       "test_zip_slip_必须拒绝且目标目录不留文件",
       "删掉越界条目名那道闸（../evil.txt 就能穿过名字层）",
       ("""        problem = entry_name_problem(n)
        if problem:
            return ("备份包里有一条不安全的路径：%s（%s）——已拒绝，什么都没有解出来"
                    % (n, problem))
""", "        pass\n")),

    _m("M02-白名单否决",
       "test_zip_slip_必须拒绝且目标目录不留文件",
       "删掉\"是不是用户数据\"那道闸（assets/char.png 这类非用户数据就能被写回去）",
       ("""        if not is_user_data(rel, base if base is not None else root, src):
            return ("备份包里有不属于用户数据的路径：%s——可能是被改过的包，"
                    "拒绝它（否则可能覆盖程序文件）" % rel)
""", "")),

    _m("M03-发货清单否决",
       "test_发货文件即使躺在白名单目录里也不进包",
       "删掉 SYNC_FILES 对白名单目录的否决权",
       ("""    if text in _norm_set(src.SYNC_FILES):
        return False
""", "")),

    _m("M04-缓存目录",
       "test_缓存目录不进包",
       "把 BACKUP_SKIP_DIRS 置空（.pyc 会进备份）",
       ('BACKUP_SKIP_DIRS = ("__pycache__",)', "BACKUP_SKIP_DIRS = ()")),

    _m("M05-残留形态",
       "test_残留形态不进包",
       "把残留形态（.tmp/.bak/.old/.bad）也算成用户数据",
       ("        return not src.residue_hit(parts[0])", "        return True")),

    _m("M06-根一层筛选",
       "test_白名单外的文件不进包",
       "数据目录根一层\"什么都收\"（notes.txt / assets 都进包）",
       ("        if os.path.isfile(ap) and not os.path.islink(ap) and is_user_data(name, base, src):",
        "        if os.path.isfile(ap) and not os.path.islink(ap):")),

    _m("M07-手抄名单",
       "test_备份范围跟着口径对象走而不是写死在代码里",
       "把发布口径换成本模块里抄死的一份名单（nsiche.json 立刻不被认）",
       ("    if len(parts) == 1 and src.user_data_hit(parts[0]):",
        '    if len(parts) == 1 and parts[0] in ("config.json", "roles.json"):')),

    _m("M08-摘要字段",
       "test_manifest_内容",
       "_sha256_file 恒返回固定串（清单里的摘要是假的）",
       ("    return digest.hexdigest()\n\n\ndef _free_path",
        '    return "0" * 64\n\n\ndef _free_path')),

    _m("M09-断包",
       "test_断zip必须拒绝",
       "把\"不是有效 zip\"当成\"空备份\"放行",
       ("""    except zipfile.BadZipFile as e:
        return [], None, "这个文件不是有效的 zip（可能没下完整）：%s（%s）" % (_base_name(path), e)
""", """    except zipfile.BadZipFile:
        return [], {"format": BACKUP_FORMAT, "schema": 1, "files": []}, ""
""")),

    _m("M10-缺清单",
       "test_空zip必须拒绝",
       "把\"包里没有 manifest\"当成\"空备份\"放行",
       ('        return None, "这个包里没有备份清单（%s），不是大肥鱼的备份包" % MANIFEST_NAME',
        '        return {"format": BACKUP_FORMAT, "schema": 1, "files": []}, ""')),

    _m("M11-缺文件",
       "test_缺文件必须拒绝",
       "缺失的条目静默跳过（恢复少一个文件还说成功）——两处判据是**冗余**的，"
       "只拿掉一处还会被另一处兜住，所以两处一起拿掉才问得出\"这条用例有没有牙\"",
       ("    missing = [n for n in listed if n not in known]", "    missing = []"),
       ("""        try:
            info = zf.getinfo(name)
        except KeyError:
            return [], "备份不完整：包里找不到 %s" % name
""", """        try:
            info = zf.getinfo(name)
        except KeyError:
            continue
""")),

    _m("M12-sha校验",
       "test_内容被改过的包必须拒绝",
       "删掉逐条 sha256 比对",
       ("""        if got_sha != rec["sha256"]:
            return [], ("备份里的 %s 内容对不上（sha256 校验失败）——可能损坏或被改过，"
                        "已拒绝恢复" % name)
""", "        pass\n")),

    _m("M13-字节数校验",
       "test_内容被改过的包必须拒绝",
       "删掉逐条字节数比对",
       ("""        if got_size != rec["size"]:
            return [], ("备份里的 %s 大小对不上（清单说 %d 字节，实际 %d 字节），可能坏了"
                        % (name, rec["size"], got_size))
""", "        pass\n")),

    _m("M14-schema上界",
       "test_清单结构不对要有人话",
       "删掉\"清单版本比本程序新\"那道门",
       ("""    if schema > BACKUP_SCHEMA:
        return ("这份备份是更新版本的桌宠做的（清单 schema=%d，本程序只认 %d），"
                "请先升级桌宠再恢复" % (schema, BACKUP_SCHEMA))
""", "")),

    _m("M15-重名条目",
       "test_重名条目必须拒绝",
       "删掉重名条目判断（zipfile 只认最后一条）",
       ("""    if len(set(names)) != len(names):
        # zipfile 允许同名条目，而 zf.open(name) 只给**最后一条**——清单对不上的经典藏匿手法
        return "备份包里有重名条目（可能被改过），已拒绝"
""", "")),

    _m("M16-安全线手抄",
       "test_条目名安全线与插件包共用一条判据",
       "在本模块里抄一份简化判据（漏掉保留设备名与非法字符）",
       ("""    reason = pet_plugin._unsafe_name_reason(name)     # noqa: SLF001 —— 见本函数 docstring
    if reason:
        return reason
""", """    if ".." in str(name) or str(name).startswith("/"):
        return "越界"
""")),

    _m("M17-临时件清理",
       "test_原子性_写到一半失败不留残件",
       "拿掉唯一的清理点（失败后磁盘上留下半截包）",
       ("        _remove(tmp)\n", "        pass\n")),

    _m("M18-manifest固定时间戳",
       "test_同一份数据同一个时钟两次备份逐字节相同",
       "manifest 条目改用当前时钟写（同一份数据两次备份不再逐字节相同）",
       ("""    zi = zipfile.ZipInfo(MANIFEST_NAME, date_time=(1980, 1, 1, 0, 0, 0))
    zi.compress_type = zf.compression
    zi.external_attr = 0o600 << 16
    zf.writestr(zi, json.dumps(manifest, ensure_ascii=False, indent=2))
""", """    zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
""")),

    _m("M19-快照是废包",
       "test_恢复前先留快照_且快照能单独恢复",
       "快照写成 0 字节（文件在、但不能用来回滚）",
       ("""        if ok:
            return cand, ""
""", """        if ok:
            with open(cand, "wb") as _f:
                _f.write(b"")
            return cand, ""
""")),

    _m("M20-快照失败也继续",
       "test_快照写不出来就不许开始恢复",
       "快照失败不再中止（没有回滚依据也照写）",
       ("""        if snap_err:
            return False, ("恢复没开始：恢复前的自动快照没做成（%s）——你的数据一个字节都没动"
                           % snap_err)
""", """        if snap_err:
            snap = os.path.join(base, ".no-snapshot.zip")
""")),

    _m("M21-删掉新造文件",
       "test_恢复失败回滚_数据回到恢复前的样子",
       "回滚时不再删掉这一趟新造出来的文件",
       ("""        for rel in placed:
            if rel in keep:
                continue
            try:
                os.remove(_target(base, rel))
            except FileNotFoundError:
                continue
            except OSError as e:
                return False, "删不掉这一趟新加的文件 %s（%s）" % (rel, e)
""", "")),

    _m("M22-回滚结果丢掉",
       "test_回滚也失败时_说清楚快照在哪",
       "回滚失败也报\"已经回退\"（用户以为数据回来了）",
       ('        if back_ok:\n            return False, "恢复失败（%s），已经回退到恢复前的样子（快照：%s）" % (cerr, snap)',
        '        if True:\n            return False, "恢复失败（%s），已经回退到恢复前的样子（快照：%s）" % (cerr, snap)')),

    _m("M23-口径不完整也凑合跑",
       "test_口径不完整时拒绝而不是猜一份",
       "注入的口径缺属性时不再拒绝，悄悄退回运行期口径（等于把\"调用方给错了\"吞掉）",
       ("""    if missing:
        raise RulesUnavailable(
            "用户数据口径不完整（缺 %s）——备份/恢复不做，免得拿一份猜出来的名单去动用户文件"
            % "、".join(missing))
""", """    if missing:
        return RUNTIME_RULES
""")),

    _m("M24-落盘改空转",
       "test_往返逐字节一致",
       "恢复时只记录不写盘（回执照样说成功）",
       ("        err = _write_bytes(target, data)", '        err = ""')),

    _m("M25-镜像式恢复",
       "test_恢复不删掉备份里没有的用户文件",
       "恢复前先把数据目录清空（镜像式恢复 = 用户数据丢失）",
       ("    placed = []\n    for rec in entries:",
        "    placed = []\n    for _cur, _dirs, _files in os.walk(base):\n"
        "        for _name in _files:\n            os.remove(os.path.join(_cur, _name))\n"
        "    for rec in entries:")),

    _m("M26-口径漂移",
       "test_运行期口径与发布门逐项相等",
       "往运行期口径里多塞一个发布门没有的名字（两份清单开始漂）",
       ("RUNTIME_USER_DATA_NAMES = frozenset((",
        'RUNTIME_USER_DATA_NAMES = frozenset(("extra_drift.json",')),

    _m("M27-熔断标记",
       "test_熔断标记不进备份",
       "把熔断标记从\"备份不带走\"里去掉（恢复旧备份会把崩溃计数倒灌回去）",
       ("""    if text in _skip_names():
        # 口径认它（发布包里不许有），但备份**不带走**：恢复旧备份不该倒灌崩溃计数，
        # 理由见 _skip_names 的 docstring
        return False
""", "")),
]


def _shadow():
    """在 %TEMP% 建一份最小影子副本（真仓只读）。"""
    tmp = tempfile.mkdtemp(prefix="w1b_shadow_")
    for rel in COPIES:
        src = os.path.join(REPO, *rel.split("/"))
        dst = os.path.join(tmp, *rel.split("/"))
        d = os.path.dirname(dst)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        shutil.copy2(src, dst)
    return tmp


def _restore(shadow):
    """把被测文件恢复成真仓那一份（每条变异之前都重来一次，互不污染）。"""
    shutil.copy2(os.path.join(REPO, TARGET), os.path.join(shadow, TARGET))


def _apply(shadow, edits):
    """应用一条变异。old 必须恰好命中 1 次，否则返回人话原因（ANCHOR-LOST）。"""
    path = os.path.join(shadow, TARGET)
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    for old, new in edits:
        hits = text.count(old)
        if hits != 1:
            return "锚点命中 %d 次（应为 1）：%r" % (hits, old.split("\n")[0][:60])
        text = text.replace(old, new)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return ""


def _run(shadow, nodeid):
    """在影子里跑一条用例 → (rc, 输出)。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["QT_QPA_PLATFORM"] = "offscreen"
    env.pop("PYTHONPATH", None)
    proc = subprocess.run([sys.executable, "-B", "-m", "pytest", nodeid, "-o", "addopts=", "-q"],
                          cwd=shadow, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, timeout=600)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _short(output, nodeid):
    """pytest 输出里的 FAILED/ERROR 行（判定用；找不到就给最后一行）。"""
    base = nodeid.split("::")[-1]
    hits = [ln.strip() for ln in output.splitlines()
            if (ln.startswith("FAILED ") or ln.startswith("ERROR ")) and base in ln]
    if hits:
        return hits[0]
    tail = [ln for ln in output.splitlines() if ln.strip()]
    return tail[-1] if tail else ""


def _judge(rc, output, nodeid):
    """(判定, 一行证据)。"""
    if rc == 0:
        return "NOT CAUGHT", "rc=0（拿掉判据它照样过）"
    base = nodeid.split("::")[-1]
    for ln in output.splitlines():
        if (ln.startswith("FAILED ") or ln.startswith("ERROR ")) and base in ln:
            return "CAUGHT", ln.strip()
    return "WRONG TEST", "rc=%d 红的是别的用例：%s" % (rc, _short(output, nodeid))


def main(argv):
    only = argv[1] if len(argv) > 1 else ""
    shadow = _shadow()
    try:
        print("影子副本：%s" % shadow)
        print("基线（不改任何源码）必须先绿：")
        rc, out = _run(shadow, TESTFILE)
        print("  rc=%d  %s" % (rc, _short(out, TESTFILE)))
        if rc != 0:
            print("基线不绿 —— 这次探针的结果一律不作数（别把它读成\"判据都有牙\"）")
            return 1
        picked = [m for m in MUTATIONS if not only or only in m["id"] or only in m["test"]]
        bad = []
        for i, mut in enumerate(picked, 1):
            _restore(shadow)
            err = _apply(shadow, mut["edits"])
            if err:
                print("[%2d/%d] %-22s ANCHOR-LOST  %s" % (i, len(picked), mut["id"], err))
                bad.append(mut["id"])
                continue
            t0 = time.time()
            rc, out = _run(shadow, "%s::%s" % (TESTFILE, mut["test"]))
            used = time.time() - t0
            verdict, why = _judge(rc, out, "%s::%s" % (TESTFILE, mut["test"]))
            print("[%2d/%d] %-22s %-11s rc=%-2d %5.1fs  %s"
                  % (i, len(picked), mut["id"], verdict, rc, used, why))
            if verdict != "CAUGHT":
                bad.append("%s（%s）" % (mut["id"], mut["why"]))
        print("-" * 78)
        if bad:
            print("没被验证的 %d / %d 条：%s" % (len(bad), len(picked), "；".join(bad)))
            return 1
        print("全部 CAUGHT：%d / %d 条（基线 rc=0）" % (len(picked), len(picked)))
        return 0
    finally:
        _restore(shadow)
        shutil.rmtree(shadow, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
