# -*- coding: utf-8 -*-
"""_check_release.py 的自测：合成坏包/好包，验证各项检查真的会报错/放行。

v2.4.2（第三轮找茬收口）补三条"工作树缺件"判据的用例：删除（D）条目 / 素材清单 /
变异锁——每条都配了**能真失败**的对照（纯函数合成输入 + 真 git 仓库删文件两条路）。

v2.4.3 追加：中文路径不许显示成 git 八进制转义（兼容审查 L9）· 被 .gitignore 忽略的
素材不算"未入库"（质量审查 L2）· 变异证据的源码指纹过期要点名（质量审查 M4）·
影子副本（无 .git）里真仓用例 skip 而不是假红（质量审查 M3）。
"""
import ast
import io
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _check_release as chk  # noqa: E402


def _make_zip(path, names, version="9.9.9", real_main=False):
    """real_main=True 时 桌宠.py 用仓库真实内容（v2.1.4 起 check_zip 会比内容 hash）。"""
    real = ""
    if real_main:
        with open(os.path.join(chk.ROOT, "桌宠.py"), "rb") as f:
            real = f.read().decode("utf-8", "replace")
    with zipfile.ZipFile(path, "w") as z:
        for n in names:
            if n == "桌宠.py":
                z.writestr(n, real if real_main else ('VERSION = "%s"\n' % version))
            else:
                z.writestr(n, "x")


def test_check_zip_flags_runtime_data(tmp_path):
    """包里混进运行时数据/开发文件必须被点名（含 v2.4 M2 的 .bad / M3 的 repro_quiet.py）。

    脏条目**恰好放 8 条**：失败报告只列前 8 条（sorted(bad)[:8]），多放一条就会把
    排序靠后的挤出去，断言会变成"测截断"而不是"测判据"。
    """
    p = str(tmp_path / "bad.zip")
    _make_zip(p, ["桌宠.py", "main.py", "python.exe", "assets/",
                  "config.json", "ledger.json", "error.log.old", "error.log.bad",
                  "repro_quiet.py", "_verify_green.py", "_check_release.py", "roles/x.png"])
    fails = chk.check_zip(p, chk.repo_version())
    joined = " ".join(fails)
    for n in ("config.json", "ledger.json", "error.log.old", "error.log.bad",
              "repro_quiet.py", "_verify_green.py", "_check_release.py"):
        assert n in joined, "%s 没被点名：%s" % (n, joined)
    assert "roles/x.png" in joined, "子目录里的用户数据没被点名：%s" % joined


def test_check_zip_flags_missing_and_stale(tmp_path):
    p = str(tmp_path / "old.zip")
    _make_zip(p, ["桌宠.py", "main.py"], version="1.0.0")  # 缺模块 + 版本旧
    fails = chk.check_zip(p, "2.0.0")
    joined = " ".join(fails)
    assert "缺关键内容" in joined
    assert "旧版本" in joined


def test_check_zip_passes_clean(tmp_path):
    p = str(tmp_path / "ok.zip")
    # v2.4（M3）：need 改成 _sync_pairs() 全量正向校验（SYNC_FILES + assets/ 每一个文件）——
    # 此前只查 "assets/" 前缀存不存在，真包 assets 140/150、idle_full 0 个也放行。
    # 合成包必须覆盖这份清单，不能再手写几项。
    names = [n for n in chk._sync_pairs() if n != "_verify_green.py"] + ["python.exe", "Lib/x.py"]
    _make_zip(p, names, version=chk.repo_version(), real_main=True)
    assert chk.check_zip(p, chk.repo_version()) == []


def test_check_zip_flags_same_version_but_stale_content(tmp_path):
    """M3 回归：版本号相同但内容不同（拿旧包冒充）必须被抓到。"""
    p = str(tmp_path / "stale.zip")
    _make_zip(p, ["桌宠.py", "main.py", "pet_voice.py", "pet_lines.py", "pet_dialogs.py",
                  "python.exe", "assets/char.png"], version=chk.repo_version(), real_main=False)
    fails = chk.check_zip(p, chk.repo_version())
    assert any("内容不一致" in f for f in fails), fails


def test_check_version_of_this_repo():
    """当前仓库的版本一致性：**严格**全绿（含数字版本 filevers/prodvers）。

    v2.4.1 收紧（质量审查）：此前为了绕开 version_info.txt 里 (2, 2, 0, 0) 的历史漂移，这里
    只校验"非数字项"，等于把新判据在开发期关掉了——而本轮真实踩到的正是这条漂移。现在
    version_info.txt 已同步成 (2, 4, 0, 0)，这里恢复严格：任何一项（字符串 / 数字 / CHANGELOG
    首条与次条）出问题都让本用例变红；数字判据的"能真报"由 test_release_chain_v24.py 的
    合成文本用例（反例 1）单独钉住。
    """
    assert chk.check_version() == []
    assert chk.repo_version() not in ("", "?")


def test_check_sync_reports_list():
    """同步检查返回 (缺失, 不一致) 两个列表（结构稳定）。"""
    missing, diff = chk.check_sync()
    assert isinstance(missing, list) and isinstance(diff, list)


# ---------------- v2.4.2（第三轮找茬收口）：工作树缺件 ----------------
# 本轮真踩到：assets/idle_f03.png 被外部脚本删掉 → 工作树出现 " D" 条目、3 条用例变红，
# 而"首屏至少 9 帧非空图"这条探针不变量照样 PASS（9 帧仍然成立）。check_clean_tree 当时
# 只说"有未提交改动"，check_zip 只查包内 assets——只有全量 pytest 抓得住，排查方向被带偏。

def _init_git_repo(path, files):
    """造一个最小 git 仓库（files 是 仓库相对路径 -> 内容）并提交。返回仓库路径。

    没有 git 就 skip（CI 与开发机都有；绿色版/离线环境不跑这条）。
    """
    if shutil.which("git") is None:
        pytest.skip("没有 git：本条要用真仓库验证发布门的缺件判据")
    os.makedirs(path, exist_ok=True)
    base = ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
            "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false"]
    for rel, text in files.items():
        full = os.path.join(path, rel.replace("/", os.sep))
        d = os.path.dirname(full)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(text)
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "init"]):
        p = subprocess.run(base + args, cwd=path, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        assert p.returncode == 0, "git %s 失败：%s" % (args, (p.stderr or "").strip())
    return path


def test_clean_tree_points_at_deleted_entries():
    """发布门必须把 " D" 条目**单独点名**，不能与"代码改了没提交"混成一句。

    能真失败：把 clean_tree_problems 退回旧的一行汇总（把 deleted 与 changed 混进同一个
    dirty 列表），"删除"二字就不会出现在报告里 → 第一条断言立刻红。
    """
    text = " D assets/idle_f03.png\n M pet_lines.py\n?? scratch.py\n"
    fails = chk.clean_tree_problems(text)
    assert len(fails) == 3, fails
    assert any("idle_f03.png" in f and "删除" in f for f in fails), fails
    # 分类：普通改动那条不许把删除条目一起卷进来（否则分类等于没做）
    changed = [f for f in fails if "未提交改动" in f]
    assert changed and "idle_f03.png" not in changed[0], changed
    cls = chk.classify_status(text)
    assert cls["deleted"] == ["assets/idle_f03.png"], cls
    assert cls["changed"] == ["pet_lines.py"] and cls["untracked"] == ["scratch.py"], cls
    # 反例对照：干净文本一条都不许报（否则上面可能是恒真断言）
    assert chk.clean_tree_problems("") == []
    # 改名不算删除；已暂存删除（"D "）同样要报
    assert chk.classify_status("R  old.py -> new.py\n")["deleted"] == []
    assert chk.classify_status("D  gone.py\n")["deleted"] == ["gone.py"]


def test_clean_tree_reports_a_really_deleted_file(tmp_path):
    """真仓库对照：提交过的文件在磁盘上被删掉（不 git add）→ check_clean_tree 必须报删除。"""
    repo = _init_git_repo(str(tmp_path / "r"), {"a.py": "x\n", "assets/idle_f03.png": "png\n"})
    assert chk.check_clean_tree(repo) == [], "反例对照：干净的合成仓库不许报"
    os.remove(os.path.join(repo, "assets", "idle_f03.png"))
    fails = chk.check_clean_tree(repo)
    assert any("idle_f03.png" in f for f in fails), fails
    assert any("删除" in f for f in fails), fails


def test_asset_manifest_catches_a_deleted_asset():
    """合成"删掉一张 assets 图"：索引里有、磁盘上没有 → 必须报（反向也要报）。

    能真失败：把 asset_manifest_problems 的 missing 判据删掉（只留 extra），第一条断言红。
    """
    tracked = ["assets/a.png", "assets/idle_f03.png"]
    assert chk.asset_manifest_problems(tracked, tracked) == []
    fails = chk.asset_manifest_problems(tracked, ["assets/a.png"])
    assert len(fails) == 1 and "idle_f03.png" in fails[0], fails
    extra = chk.asset_manifest_problems(["assets/a.png"], ["assets/a.png", "assets/new.png"])
    assert len(extra) == 1 and "new.png" in extra[0], extra


def test_asset_manifest_reports_a_missing_shipped_asset(tmp_path):
    """真仓库对照：check_asset_manifest 抓到"少了一张已入库素材"（本轮事故的合成版）。"""
    repo = _init_git_repo(str(tmp_path / "r"), {"assets/a.png": "a", "assets/idle_f03.png": "b"})
    assert chk.check_asset_manifest(repo) == [], "反例对照：素材齐时不许报"
    os.remove(os.path.join(repo, "assets", "idle_f03.png"))
    fails = chk.check_asset_manifest(repo)
    assert any("idle_f03.png" in f for f in fails), fails
    with open(os.path.join(repo, "assets", "brand_new.png"), "w", encoding="utf-8") as f:
        f.write("c")
    assert any("brand_new.png" in f for f in chk.check_asset_manifest(repo)), "磁盘上多了没入库的素材也要报"


def test_this_repo_has_no_missing_shipped_assets():
    """当前真仓：不许有"git 里有、磁盘上没有"的素材（只在危险方向硬断言）。

    反向（磁盘多了没入库的新素材）在这里不硬断言：开发中新增素材是正常中间态，由
    check_clean_tree 的未跟踪判据负责；本条要钉的是本轮那次"素材被删"。
    """
    tracked = chk.tracked_assets()
    if not tracked:
        # v2.4.3（质量审查 M3）：_mutate_lib 的影子副本不带 .git（SKIP_DIRS）→ tracked 为空。
        # 那是**环境**不是失败：此前这里硬断言，影子里 2 failed/49 passed，"基线"结论跟着
        # 失真，relay 用例于是天然落在变异证据之外。真仓（有 .git）仍然照跑。
        pytest.skip("无 git / assets 未入库（影子副本）：本条只在真仓上有意义")
    disk = chk.disk_assets()
    assert len(tracked) > 100, "git 里读不到 assets 清单（用例前提不成立）：%d" % len(tracked)
    missing = sorted(set(tracked) - set(disk))
    assert missing == [], "工作区少了已入库素材：%s" % (missing,)
    assert chk.check_shipped_files() == [], chk.check_shipped_files()


def test_mutation_lock_blocks_or_warns(tmp_path):
    """变异进行中 → 发布门拒绝判定；陈旧锁（进程崩了）→ 只提示，不挡发布。

    能真失败：把 mutation_lock_problems 改成恒返回 ([], [])，第一条断言红。
    """
    root = tmp_path / "repo"
    (root / "_dev").mkdir(parents=True)
    (root / "assets").mkdir()
    assert chk.mutation_lock_problems(str(root)) == ([], [])
    lock = root / "_dev" / ".mutation.lock"
    lock.write_text(json.dumps({"pid": 1234, "what": "mutate_x", "started_at": "刚刚"},
                               ensure_ascii=False), encoding="utf-8")
    fails, notes = chk.mutation_lock_problems(str(root))
    assert fails and not notes and "变异" in fails[0], (fails, notes)
    assert "1234" in fails[0] and "mutate_x" in fails[0], fails[0]
    old = time.time() - (chk.MUTATION_LOCK_STALE_H + 1) * 3600
    os.utime(str(lock), (old, old))
    fails2, notes2 = chk.mutation_lock_problems(str(root))
    assert fails2 == [] and notes2 and "陈旧" in notes2[0], (fails2, notes2)
    # 目录形态（新口径：一个持有者一个 <pid>.json，能同时挂多个变异进程——
    # 单文件锁曾被"后写的顶掉先写的 + 先结束的无条件删锁"搞出过"变异在跑但门看不见锁"）
    os.remove(str(lock))
    lock.mkdir()
    for pid, what in ((111, "mutate_a"), (222, "mutate_b")):
        (lock / ("%d.json" % pid)).write_text(
            json.dumps({"pid": pid, "what": what}), encoding="utf-8")
    f3, n3 = chk.mutation_lock_problems(str(root))
    assert f3 and not n3, (f3, n3)
    assert "111" in f3[0] and "222" in f3[0] and "mutate_a" in f3[0], f3[0]
    # 只留一个**陈旧**条目 → 只提示不挡发布（也别把空目录/坏 JSON 当成在跑）
    (lock / "111.json").unlink()
    (lock / "222.json").unlink()
    (lock / "333.json").write_text("{坏 json", encoding="utf-8")
    old2 = time.time() - (chk.MUTATION_LOCK_STALE_H + 1) * 3600
    os.utime(str(lock / "333.json"), (old2, old2))
    f4, n4 = chk.mutation_lock_problems(str(root))
    assert f4 == [] and n4 and "陈旧" in n4[0], (f4, n4)
    (lock / "333.json").unlink()
    assert chk.mutation_lock_problems(str(root)) == ([], []), "空锁目录不该报警"


# ---------------- v2.4.3（兼容审查 L9）：中文路径要可读 ----------------

def test_clean_tree_shows_utf8_paths_not_octal_escapes(tmp_path):
    r"""发布门报告里的中文路径必须是**可读的 UTF-8**，不是 git 的八进制转义。

    现场：`check_clean_tree` 的 git status 没关 core.quotepath，桌宠.py 显示成
    \346\241\214\345\256\240...——最该一眼看到的入口文件反而最难认。

    能真失败：把 check_clean_tree 里的 "-c core.quotepath=false" 拿掉 → git 输出八进制
    转义 → 断言找不到"桌宠.py" → 红。
    """
    repo = _init_git_repo(str(tmp_path / "r"), {"桌宠.py": "VERSION = '1'\n"})
    with open(os.path.join(repo, "桌宠.py"), "a", encoding="utf-8") as f:
        f.write("# touch\n")
    joined = " ".join(chk.check_clean_tree(repo))
    assert "桌宠.py" in joined, "报告里看不到入口文件（路径没解转义）：%s" % joined
    assert "\\346" not in joined, "报告里仍是 git 八进制转义：%s" % joined
    # 反例对照：干净仓库照样不报（别为了可读性把判据改坏）
    clean = _init_git_repo(str(tmp_path / "r2"), {"桌宠.py": "VERSION = '1'\n"})
    assert chk.check_clean_tree(clean) == []


# ---------------- v2.4.3（质量审查 L2）：被忽略的素材不算"未入库" ----------------

def test_asset_manifest_ignores_gitignored_files(tmp_path):
    """磁盘上多出来的素材里，**被 .gitignore 忽略**的那些不算"忘了 git add"。

    审查实测：.gitignore 加 *.bak、assets/ 下放 a.png.bak → 发布门报"未入库素材 1 个"。
    真仓今天不误报只是因为恰好没有 assets 相关的忽略规则。

    能真失败：check_asset_manifest 退回 asset_manifest_problems(tracked, disk)（不传
    untracked_assets）→ 第一条断言红。
    """
    repo = _init_git_repo(str(tmp_path / "r"),
                          {"assets/a.png": "a", ".gitignore": "*.bak\n"})
    with open(os.path.join(repo, "assets", "a.png.bak"), "w", encoding="utf-8") as f:
        f.write("backup")
    assert chk.check_asset_manifest(repo) == [], \
        "被 .gitignore 忽略的文件被当成未入库素材：%r" % (chk.check_asset_manifest(repo),)
    # 纯函数口径：new_files=None 是旧口径（两个都报），传了就只报没被忽略的那个
    tracked, disk = ["assets/a.png"], ["assets/a.png", "assets/a.png.bak", "assets/new.png"]
    assert len(chk.asset_manifest_problems(tracked, disk)) == 1
    only_new = chk.asset_manifest_problems(tracked, disk, ["assets/new.png"])
    assert len(only_new) == 1 and "new.png" in only_new[0] and "bak" not in only_new[0], only_new
    # 反向对照：没被忽略的新素材仍要报（别把判据一起放行）
    with open(os.path.join(repo, "assets", "brand_new.png"), "w", encoding="utf-8") as f:
        f.write("c")
    fails = chk.check_asset_manifest(repo)
    assert any("brand_new.png" in f for f in fails), fails
    assert not any("a.png.bak" in f for f in fails), fails


# ---------------- v2.4.3（第三轮找茬复审 L③）：判据没生效要出声 ----------------

def test_asset_manifest_notes_when_the_check_cannot_run(tmp_path):
    """素材清单判据**没生效**时必须至少给一句提示，不许静默"通过"（复审 L③）。

    能真失败：把 asset_manifest_notes 改成恒返回 [] → 第一条断言红。
    """
    root = tmp_path / "nogit"
    (root / "assets").mkdir(parents=True)
    (root / "assets" / "a.png").write_text("a", encoding="utf-8")
    assert chk.check_asset_manifest(str(root)) == [], "无 git 时这条判据本身不报错"
    notes = chk.asset_manifest_notes(str(root))
    assert notes and "没生效" in notes[0], notes
    # 有 git 且素材入库 → 不再提示（别把提示变成常驻噪音）
    repo = _init_git_repo(str(tmp_path / "g"), {"assets/a.png": "a"})
    assert chk.asset_manifest_notes(repo) == []
    # 连 assets 目录都没有 → 同样要提示
    bare = tmp_path / "bare"
    bare.mkdir()
    assert chk.asset_manifest_notes(str(bare)), "assets 目录不存在时也该提示"


# ---------------- v2.4.3（质量审查 M4）：变异证据的源码指纹过期要点名 ----------------

def test_stale_fingerprints_reports_only_mismatches():
    """纯函数：记录指纹 vs 当前指纹 → 只报**不一致**的项（缺一边就不报）。"""
    cur = {"桌宠.py": "aaaa", "pet_export.py": "bbbb"}
    assert chk.stale_fingerprints({}, cur) == []
    assert chk.stale_fingerprints(None, cur) == []
    assert chk.stale_fingerprints(cur, cur) == []
    assert chk.stale_fingerprints({"桌宠.py": "old1", "pet_export.py": "bbbb"}, cur) == \
        ["桌宠.py: old1→aaaa"]
    assert chk.stale_fingerprints({"gone.py": "x"}, cur) == [], "当前树没有的文件无从比对"


def test_mutation_evidence_notes_flags_a_stale_result_json(tmp_path):
    """结果 JSON 记的指纹 ≠ 当前树 → 发布门必须提示"该证据已过期"，不许静默。

    能真失败：把 mutation_evidence_notes 改成恒返回 [] → 第二条断言红。
    """
    dev = tmp_path / "_dev"
    dev.mkdir()
    (tmp_path / "桌宠.py").write_text("x", encoding="utf-8")
    cur = chk.tree_fingerprint(str(tmp_path))
    assert cur.get("桌宠.py"), "夹具前提：当前树指纹算得出来"
    (dev / "mutations_ok.json").write_text(json.dumps({"repo_fingerprint": cur}),
                                           encoding="utf-8")
    assert chk.mutation_evidence_notes(str(tmp_path)) == [], "指纹一致时不许报警"
    (dev / "mutations_stale.json").write_text(
        json.dumps({"repo_fingerprint": {"桌宠.py": "deadbeef0000"}}), encoding="utf-8")
    notes = chk.mutation_evidence_notes(str(tmp_path))
    assert len(notes) == 1 and "mutations_stale.json" in notes[0] and "过期" in notes[0], notes
    # spec 内嵌形态（mutate_check.py 回写的 results.repo_fingerprint）也要认
    (dev / "mutations_ok.json").write_text(
        json.dumps({"mutations": [], "results": {"repo_fingerprint": {"桌宠.py": "deadbeef0000"}}}),
        encoding="utf-8")
    notes2 = chk.mutation_evidence_notes(str(tmp_path))
    assert len(notes2) == 2, notes2
    assert any("mutations_ok.json" in n for n in notes2), notes2


def test_fingerprint_file_list_matches_the_mutation_lib():
    """发布门与 _dev/_mutate_lib.repo_fingerprint 的"关键文件"清单不许漂移。

    否则发布门比对的字段与证据里记的字段不是一套，过期提示会永远沉默。
    """
    src = io.open(os.path.join(chk.ROOT, "_dev", "_mutate_lib.py"), encoding="utf-8").read()
    files = None
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == "repo_fingerprint":
            for sub in ast.walk(node):
                if isinstance(sub, ast.For) and isinstance(sub.iter, (ast.Tuple, ast.List)):
                    files = [e.value for e in sub.iter.elts if isinstance(e, ast.Constant)]
    assert files, "在 _dev/_mutate_lib.py 里找不到 repo_fingerprint 的文件清单"
    assert tuple(files) == tuple(chk.MUTATION_FINGERPRINT_FILES), \
        "两处清单漂移：%r vs %r" % (files, chk.MUTATION_FINGERPRINT_FILES)