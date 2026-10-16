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
    # v2.11.0（代理 C · V1）：夹具补一份**正确**的 pinned_ast —— 否则会多出
    # "还没有 pinned 用例体摘要"那条提示（本用例考的是指纹过期，不是那条）
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_demo.py").write_text(
        "def test_pinned():\n    assert True\n", encoding="utf-8")
    pin = chk.pinned_ast_now(str(tmp_path), ["tests/test_demo.py::test_pinned"])
    assert pin, "夹具前提：pinned 摘要算得出来"
    cur = chk.tree_fingerprint(str(tmp_path))
    assert cur.get("桌宠.py"), "夹具前提：当前树指纹算得出来"
    (dev / "mutations_ok.json").write_text(
        json.dumps({"repo_fingerprint": cur, "pinned_ast": pin}), encoding="utf-8")
    assert chk.mutation_evidence_notes(str(tmp_path)) == [], "指纹一致时不许报警"
    (dev / "mutations_stale.json").write_text(
        json.dumps({"repo_fingerprint": {"桌宠.py": "deadbeef0000"}, "pinned_ast": pin}),
        encoding="utf-8")
    notes = chk.mutation_evidence_notes(str(tmp_path))
    assert len(notes) == 1 and "mutations_stale.json" in notes[0] and "过期" in notes[0], notes
    # spec 内嵌形态（mutate_check.py 回写的 results.repo_fingerprint）也要认
    (dev / "mutations_ok.json").write_text(
        json.dumps({"mutations": [],
                    "results": {"repo_fingerprint": {"桌宠.py": "deadbeef0000"},
                                "pinned_ast": pin}}),
        encoding="utf-8")
    notes2 = chk.mutation_evidence_notes(str(tmp_path))
    assert len(notes2) == 2, notes2
    assert any("mutations_ok.json" in n for n in notes2), notes2


def test_missing_fingerprint_keys_is_pure_and_ignores_absent_files():
    """v2.6.0（代理 C）：纯函数——只点名"当前树里存在、记录里没记"的键。

    能真失败：把实现写成"清单里所有键都算缺"（或反过来恒返回 []）→ 前后两组断言红。
    当前树没有的文件无从比对（树里没有就算不出指纹），点名它只会误导。
    """
    cur = {"桌宠.py": "aaaa", "pet_plugin.py": "bbbb"}
    assert chk.missing_fingerprint_keys({"桌宠.py": "aaaa"}, cur) == ["pet_plugin.py"]
    assert chk.missing_fingerprint_keys(cur, cur) == []
    assert chk.missing_fingerprint_keys({}, cur) == []
    assert chk.missing_fingerprint_keys(None, cur) == []
    assert chk.missing_fingerprint_keys({"桌宠.py": "aaaa"}, {}) == []
    # 记录了一个当前树里不存在的名字（清单换了）：等于没记有用的键，两个都要点名
    assert chk.missing_fingerprint_keys({"gone.py": "x"}, cur) == ["pet_plugin.py", "桌宠.py"]


def test_mutation_evidence_notes_flags_evidence_missing_keys(tmp_path):
    """v2.6.0（代理 C）：证据只记了部分关键文件时，发布门要提示"这份证据缺这些键"。

    背景（v2.5.1 审查实测）：stale_fingerprints 只比对**记录里存在的键**，所以清单里后来补的
    四个模块（pet_plugin.py / pet_plugin_host.py / pet_dialogs.py / pet_menu.py）在之前 14 份
    _dev/*.json 里等于不存在——改它们**一条提示都不会有**（发布门在那几个文件上是瞎子）。
    只提示、不挡发布。

    能真失败：去掉 mutation_evidence_notes 里 missing_fingerprint_keys 那次判定（或让它恒
    返回 []）→ 第二条断言红（notes 变空）。
    """
    dev = tmp_path / "_dev"
    dev.mkdir()
    (tmp_path / "桌宠.py").write_text("x", encoding="utf-8")
    (tmp_path / "pet_plugin.py").write_text("y", encoding="utf-8")
    # v2.11.0（V1）：同样补一份正确的 pinned_ast（本用例考的是"缺键"，不是"缺 pinned 段"）
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_demo.py").write_text(
        "def test_pinned():\n    assert True\n", encoding="utf-8")
    pin = chk.pinned_ast_now(str(tmp_path), ["tests/test_demo.py::test_pinned"])
    assert pin, "夹具前提：pinned 摘要算得出来"
    cur = chk.tree_fingerprint(str(tmp_path))
    assert set(cur) == {"桌宠.py", "pet_plugin.py"}, "夹具前提：当前树里有这两个文件"
    (dev / "mutations_partial.json").write_text(
        json.dumps({"repo_fingerprint": {"桌宠.py": cur["桌宠.py"]}, "pinned_ast": pin}),
        encoding="utf-8")
    notes = chk.mutation_evidence_notes(str(tmp_path))
    assert len(notes) == 1, notes
    assert "mutations_partial.json" in notes[0], notes
    assert "pet_plugin.py" in notes[0] and "缺" in notes[0], notes
    # 控制组：补齐两个键 → 归零（别把提示变成常驻噪音）
    (dev / "mutations_partial.json").write_text(
        json.dumps({"repo_fingerprint": cur, "pinned_ast": pin}), encoding="utf-8")
    assert chk.mutation_evidence_notes(str(tmp_path)) == []


# ---------------- v2.11.0 第 9 轮（代理 C · 任务 V1）：pinned 用例体的 AST 摘要 ----------------
#
# 洞：文件指纹只覆盖 28 个键，而**承载锚点的测试文件有 39 个** —— 把某个 pinned 用例的
# **用例体清空、nodeid 一个字不动**时：nodeid 体检照样 rc=0（def 还在）、文件指纹一声不吭
# （文件不在清单里）、那条变异 CAUGHT→NOT CAUGHT。只有"用例体摘要"能出声。

def test_stale_pinned_reports_only_mismatches():
    """纯函数：pinned 摘要只报**不一致**的项（缺一边就不报）。"""
    cur = {"tests/test_a.py::test_x": "aaaa11112222", "tests/test_a.py::test_y": "bbbb33334444"}
    assert chk.stale_pinned({}, cur) == []
    assert chk.stale_pinned(None, cur) == []
    assert chk.stale_pinned(cur, cur) == []
    assert chk.stale_pinned({"tests/test_a.py::test_x": "000000000000"}, cur) == \
        ["tests/test_a.py::test_x: 000000000000→aaaa11112222"]
    assert chk.stale_pinned({"tests/test_a.py::test_gone": "x"}, cur) == [], \
        "当前树算不出摘要的项（用例被删/改名）由 nodeid 体检点名，这里不重复报"


def test_pinned_ast_digest_matches_the_mutation_lib(tmp_path):
    """**铁律 4（两处口径互为反向）**：发布门的摘要实现与 _dev/_mutate_lib.pin_digest 必须逐位一致。

    两处都有实现是没办法的事（发布门不能 import _dev —— _dev/ 不进发布包），所以必须有这条钉子：
    任何一边改了算法（哪怕只是忘了去 docstring、或改了同名 def 的排序）→ 这条红。
    """
    import importlib.util
    dev = os.path.join(chk.ROOT, "_dev")
    spec = importlib.util.spec_from_file_location(
        "mutate_lib_pinned_gate_v2110", os.path.join(dev, "_mutate_lib.py"))
    lib = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = lib
    spec.loader.exec_module(lib)

    (tmp_path / "tests").mkdir()
    src = ('# -*- coding: utf-8 -*-\n"""模块说明也不该算进摘要。"""\n\n\n'
           '@pytest.mark.parametrize("n", [1, 2])\ndef test_one(n):\n    """用例说明。"""\n'
           '    assert n\n\n\n'
           'def test_two():\n    assert 2 == 2\n')
    (tmp_path / "tests" / "test_demo.py").write_text(src, encoding="utf-8")
    nodes = ["tests/test_demo.py::test_one", "tests/test_demo.py::test_one[1]",
             "tests/test_demo.py::test_two", "tests/test_demo.py"]
    gate = chk.pinned_ast_now(str(tmp_path), nodes)
    libmap = lib.pinned_ast_map(str(tmp_path), nodes)
    assert libmap, "夹具前提：变异库那份算得出来"
    assert set(gate) == set(nodes), gate
    assert gate == libmap, "两处摘要实现漂移：发布门 %r vs 变异库 %r" % (gate, libmap)


def test_mutation_evidence_notes_flags_a_stale_pinned_digest(tmp_path):
    """pinned 用例体被改过 → 发布门必须点名（文件指纹与 nodeid 体检都看不出来的那一层）。

    能真失败：去掉 mutation_evidence_notes 里 pinned_ast 那次判定 → 第二条断言红。
    """
    dev = tmp_path / "_dev"
    dev.mkdir()
    (tmp_path / "桌宠.py").write_text("x", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    demo = tmp_path / "tests" / "test_demo.py"
    demo.write_text("def test_pinned():\n    assert True\n", encoding="utf-8")
    cur = chk.tree_fingerprint(str(tmp_path))
    pin = chk.pinned_ast_now(str(tmp_path), ["tests/test_demo.py::test_pinned"])
    assert pin, "夹具前提：摘要算得出来"
    (dev / "mutations_x.json").write_text(
        json.dumps({"repo_fingerprint": cur, "pinned_ast": pin}), encoding="utf-8")
    assert chk.mutation_evidence_notes(str(tmp_path)) == [], "摘要一致时不许报警"
    # 用例体被改（nodeid 不动）→ 摘要变 → 必须出声
    demo.write_text("def test_pinned():\n    pass\n", encoding="utf-8")
    notes = chk.mutation_evidence_notes(str(tmp_path))
    assert len(notes) == 1, notes
    assert "mutations_x.json" in notes[0] and "pinned 用例体摘要已过期" in notes[0], notes
    assert "tests/test_demo.py::test_pinned" in notes[0], notes


def test_mutation_evidence_notes_flags_evidence_without_pinned_ast(tmp_path):
    """还没有 pinned 摘要的老证据要点名（只提示）；但**不把不是证据的 JSON 算进来**。

    范围口径 = "指纹通道里的证据文件"（有 repo_fingerprint 记录的那一批）——results_batch_v270.json
    （批次日志）、mutations_proc_reset_v26.json（判据是 _verify_v13 的 FAIL 名，没有 pytest nodeid）
    这类不该被点名，否则提示会变成噪音（与 _dev/check_pinned_ast.py 的谓词逐字一致）。
    """
    dev = tmp_path / "_dev"
    dev.mkdir()
    (tmp_path / "桌宠.py").write_text("x", encoding="utf-8")
    cur = chk.tree_fingerprint(str(tmp_path))
    (dev / "mutations_old.json").write_text(json.dumps({"repo_fingerprint": cur}), encoding="utf-8")
    notes = chk.mutation_evidence_notes(str(tmp_path))
    assert len(notes) == 1, notes
    assert "还没有 pinned 用例体摘要" in notes[0] and "mutations_old.json" in notes[0], notes
    # 没有指纹段的文件不算这一批（批次日志 / v13 判据 / 摘要 json）
    (dev / "results_batch.json").write_text(json.dumps({"items": [{"target": "x"}]}),
                                            encoding="utf-8")
    assert len(chk.mutation_evidence_notes(str(tmp_path))) == 1, \
        "没有指纹段的文件不该被算进「缺 pinned 摘要」这一批"


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
    # v2.4.4（任务 1）：pet_balance.py 必须在清单里。A-1（请求代次）改了它、3 条锚点随之失效，
    # 而发布门此前一条"证据过期"都不提示。少了它，这条用例红（防的是"又漏一个关键文件"）。
    # v2.5.1（找茬审查 P3-1）：同一个盲区本轮又犯了一次——pet_plugin.py / pet_plugin_host.py /
    # pet_dialogs.py / pet_menu.py 都不在清单里，12 条 M-P*/M-L1 的锚就在前两个文件上。所以这里
    # 改成**逐项点名**（别再写成"只钉 pet_balance.py 那种"：下一个新模块照样漏）。
    # v2.6.0（找茬审查 C-5）：第三次漏新模块——pet_plugin_index.py 是本轮全新模块，
    # M-A01~M-A04 四条变异锚全在它上面，而两处清单里都没有它。加进点名元组，别再漏第四个。
    for rel in ("pet_balance.py", "pet_plugin.py", "pet_plugin_host.py", "pet_dialogs.py",
                "pet_menu.py", "pet_plugin_index.py"):
        assert rel in chk.MUTATION_FINGERPRINT_FILES, \
            "%s 不在发布门的指纹清单里（改了它不会有任何提示）：%r" % (
                rel, chk.MUTATION_FINGERPRINT_FILES)
        assert rel in files, "%s 不在变异库的指纹清单里：%r" % (rel, files)
    missing = [rel for rel in chk.MUTATION_FINGERPRINT_FILES
               if not os.path.isfile(os.path.join(chk.ROOT, rel))]
    assert missing == [], "指纹清单点名了不存在的文件（这份清单本身就是过期证据）：%r" % (missing,)


def test_mutation_verdict_notes_flags_unverified_entries(tmp_path):
    """M2（v2.4.4 兼容审查）：发布门不只提示"指纹过期"，没通过的判定也要出声。

    SPEC-BAD / ANCHOR-LOST / WRONG TEST / NOT CAUGHT / INVALID / BASELINE-RED 这些条目等于
    "这条护栏还没被验证"，此前完全静默（复核的人只会看到"N/N 全抓到"里的一个缺口）。

    能真失败：把 mutation_verdict_notes 改成恒返回 [] → 第二、三组断言红。
    """
    dev = tmp_path / "_dev"
    dev.mkdir()
    (dev / "mutations_ok.json").write_text(json.dumps({
        "mutations": [],
        "results": {"items": [{"id": "M-1", "verdict": "CAUGHT"},
                              {"id": "M-2", "verdict": "CAUGHT"}]}}), encoding="utf-8")
    assert chk.mutation_verdict_notes(str(tmp_path)) == [], "全 CAUGHT 时不许报警"
    (dev / "mutations_bad.json").write_text(json.dumps({
        "results": {"items": [{"id": "M-C10", "verdict": "SPEC-BAD"},
                              {"id": "M-C9", "verdict": "WRONG TEST"},
                              {"id": "M-3", "verdict": "CAUGHT"}]}}), encoding="utf-8")
    notes = chk.mutation_verdict_notes(str(tmp_path))
    assert len(notes) == 1 and "mutations_bad.json" in notes[0], notes
    assert "M-C10=SPEC-BAD" in notes[0] and "M-C9=WRONG TEST" in notes[0], notes
    assert "M-3" not in notes[0], "CAUGHT 的条目不该被点名：%r" % (notes[0],)
    # 旧形态（结果 JSON 顶层 items，export_slice / startup_defer 那三条单脚本驱动）也要认
    (dev / "mutations_legacy.json").write_text(json.dumps(
        {"items": [{"id": "M6 feed", "verdict": "ANCHOR-LOST"}]}), encoding="utf-8")
    notes2 = chk.mutation_verdict_notes(str(tmp_path))
    assert len(notes2) == 2, notes2
    assert any("mutations_legacy.json" in n and "ANCHOR-LOST" in n for n in notes2), notes2
    # 坏 JSON / 不是结果的文件不许把它带崩（开发期会留半成品）
    (dev / "broken.json").write_text("{ not json", encoding="utf-8")
    (dev / "other.json").write_text(json.dumps({"mutations": []}), encoding="utf-8")
    assert len(chk.mutation_verdict_notes(str(tmp_path))) == 2

# ---------------- v2.5.1（A2）：发货清单的**反向**校验 ----------------
# 盲区（本轮任务书 A2）：check_shipped_files() 只查"清单里的文件还在磁盘上"，check_zip 的
# need 也只含清单 + assets → 新增模块忘了加进清单时**任何门都不响**，用户双击即 ImportError
# （v2.5.0 的 pet_services.py 就差点这样）。下面这几条把"漏了必须报"钉死。

def test_反向校验_从清单删掉真模块必须报(monkeypatch):
    """能真失败：从 SYNC_FILES 里删掉一个**真被 import** 的模块 → 立刻点名。"""
    assert "pet_services" in chk.runtime_imports(), "前提不成立：没人 import pet_services"
    kept = [n for n in chk.SYNC_FILES if n != "pet_services.py"]
    monkeypatch.setattr(chk, "SYNC_FILES", kept)
    fails = chk.check_imported_modules_shipped()
    assert fails, "清单里删掉了 pet_services.py，反向校验却没出声"
    assert "pet_services" in fails[0] and "桌宠.py" in fails[0], fails


def test_反向校验_合成仓库能认出漏件(tmp_path, monkeypatch):
    """合成仓库：pet_alpha.py import pet_beta → pet_beta.py 不在清单里就必须报。"""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pet_alpha.py").write_text("import pet_beta\n", encoding="utf-8")
    (root / "pet_beta.py").write_text("X = 1\n", encoding="utf-8")
    monkeypatch.setattr(chk, "SYNC_FILES", ["pet_alpha.py"])
    fails = chk.check_imported_modules_shipped(str(root))
    assert len(fails) == 1 and "pet_beta" in fails[0] and "pet_alpha.py" in fails[0], fails
    monkeypatch.setattr(chk, "SYNC_FILES", ["pet_alpha.py", "pet_beta.py"])
    assert chk.check_imported_modules_shipped(str(root)) == []


def test_反向校验_认_from_import_与包路径(tmp_path, monkeypatch):
    """from pet_x import y / import pet_x.sub 都算；点号只取顶层模块名。"""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pet_alpha.py").write_text(
        "from pet_beta import thing\nimport pet_gamma.sub\n", encoding="utf-8")
    monkeypatch.setattr(chk, "SYNC_FILES", ["pet_alpha.py"])
    found = chk.imported_runtime_modules(str(root))
    assert set(found) == {"pet_beta", "pet_gamma"}, found
    fails = chk.check_imported_modules_shipped(str(root))
    assert len(fails) == 1 and "pet_beta" in fails[0] and "pet_gamma" in fails[0], fails


def test_反向校验_注释与文档里的模块名不算(tmp_path, monkeypatch):
    """扫描必须走 AST：纯文本正则会把这三种形状误判成"被 import"（本轮铁律第 3 条）。

    能真失败：把 imported_runtime_modules 换成 re.finditer 正则实现 → 这条立刻红。
    """
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pet_alpha.py").write_text(
        '"""这里提到 pet_ghost 只是文档。"""\n'
        "# import pet_ghost2\n"
        "NAME = 'pet_ghost3'\n", encoding="utf-8")
    monkeypatch.setattr(chk, "SYNC_FILES", ["pet_alpha.py"])
    assert chk.imported_runtime_modules(str(root)) == {}
    assert chk.check_imported_modules_shipped(str(root)) == []


def test_本仓被导入的运行时模块都在发货清单里():
    """真仓正例 + 控制组：扫描器真的读到了东西，且清单一个不缺。"""
    every = chk.runtime_imports()
    assert len(every) >= 20, "扫描面太小（判据会空转）：%d 个" % len(every)
    assert "pet_services" in every and "json" in every, sorted(every)[:8]
    # 判据那一层：白名单（标准库 / 随包发货的本仓模块 / 运行时第三方）之外不许有漏件
    assert chk.imported_runtime_modules() == {}, chk.imported_runtime_modules()
    assert chk.check_imported_modules_shipped() == [], chk.check_imported_modules_shipped()
    for mod in ("pet_plugin", "pet_services"):
        assert mod + ".py" in chk.SYNC_FILES, "%s 没进 SYNC_FILES" % mod


# ---------------- v2.5.1（A3）：plugins/ 的分包口径 ----------------
# 用户装了插件再打包 → 发布包里带上别人的东西。判据是白名单：plugins/ 下不在"官方集合"
# 里的一律算用户数据（plugins/<id>/、plugins/_download/…），而官方索引/说明/官方内容包
# 必须能发出去（否则用户侧下载链是断的）——所以**不能**把 plugins 整个塞进 USER_DATA_DIRS。

def test_发布包里的用户插件必须点名(tmp_path, monkeypatch):
    """能真失败：拿掉 plugin_user_data_hits 这条判据 → 两个用户条目都不会被点名。"""
    monkeypatch.setattr(chk, "plugin_official_names",
                        lambda root=None: {"plugins/index.json", "plugins/packs/official-x.zip"})
    p = str(tmp_path / "withplugins.zip")
    _make_zip(p, ["桌宠.py", "main.py", "python.exe", "assets/",
                  "plugins/index.json", "plugins/packs/official-x.zip",
                  "plugins/user-thing/manifest.json", "plugins/_download/tmp.part"])
    fails = chk.check_zip(p, chk.repo_version())
    joined = " ".join(fails)
    assert "plugins/user-thing/manifest.json" in joined, joined
    assert "plugins/_download/tmp.part" in joined, joined
    assert "plugins/index.json" not in joined, "官方索引被误判成用户数据：%s" % joined
    assert "plugins/packs/official-x.zip" not in joined, joined


def test_用户数据清单与发货清单不矛盾():
    """SYNC_FILES 里的文件不能被任何"用户数据"判据拦下（否则两处口径打架、必有一处假红）。"""
    assert "plugins" not in chk.USER_DATA_DIRS, (
        "plugins 整个进 USER_DATA_DIRS 会把官方索引与官方包一起挡在包外（v2.5.1 A3 的裁决）")
    for n in chk.SYNC_FILES:
        assert not any(n.startswith(d + "/") for d in chk.USER_DATA_DIRS), n
        if n.startswith(chk.PLUGIN_DIR):
            assert not chk.user_data_hit(os.path.basename(n)), n


def test_官方插件资产不会被当成用户数据():
    """真仓：官方集合里的东西一律不许被点名；集合为空则判据空转 → 也要报。"""
    official = chk.plugin_official_names()
    assert official, "官方插件资产集合是空的（A3 判据会空转）"
    assert chk.plugin_user_data_hits(sorted(official)) == []
    assert chk.plugin_user_data_hits(["plugins/someone-else/manifest.json"])
    # 目录条目（以 / 结尾）不是文件，不该被点名
    assert chk.plugin_user_data_hits(["plugins/user-thing/"]) == []


def test_官方插件资产缺件只提示不挡发布(tmp_path):
    """官方索引/说明还没生成时：main() 给提示（不静默），但不进 fails。"""
    notes = chk.plugin_asset_notes(str(tmp_path))
    assert len(notes) == 1 and "plugins" in notes[0], notes
    # 两种形态的文案必须能区分（v2.5.1 找错审查）：一种是"资产还没生成"，
    # 另一种是"目录在但缺件"——只说"plugins"的话复核的人分不清是哪种。
    assert "缺件" not in notes[0], notes
    (tmp_path / "plugins").mkdir()
    notes2 = chk.plugin_asset_notes(str(tmp_path))
    assert len(notes2) == 1 and "缺件" in notes2[0], notes2
    for n in chk.PLUGIN_OFFICIAL_NAMES:
        f = tmp_path / n.replace("/", os.sep)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x", encoding="utf-8")
    assert chk.plugin_asset_notes(str(tmp_path)) == []

# ---------------- v2.5.1 找茬审查：发布门三处（①②③） ----------------

def test_官方集合以index_json为准_packs里的用户文件不算官方(tmp_path, monkeypatch):
    """② 官方资产必须以 **plugins/index.json 的 url** 为准。旧判据是"packs/ 目录里磁盘上有
    什么就算什么"——用户往 packs/ 里丢一个自己的包，发布门会把它当官方内容随包发出去。

    能真失败：把 plugin_official_names 改回 os.walk(packs) → 第一条断言红。
    """
    root = tmp_path / "repo"
    (root / "plugins" / "packs").mkdir(parents=True)
    (root / "plugins" / "index.json").write_text(json.dumps({
        "index_version": 1, "host_min": "2.5.0",
        "plugins": [{"id": "official-a", "releases": [
            {"version": "1.0.0", "url": "packs/official-a-1.0.0.dfypet-plugin.zip"},
            {"version": "2.0.0", "url": "https://example.invalid/remote.zip"}]}]},
        ensure_ascii=False), encoding="utf-8")
    (root / "plugins" / "packs" / "official-a-1.0.0.dfypet-plugin.zip").write_bytes(b"PK")
    (root / "plugins" / "packs" / "someone-elses.zip").write_bytes(b"PK")
    monkeypatch.setattr(chk, "SYNC_FILES", ["plugins/index.json", "plugins/README.md"])
    official = chk.plugin_official_names(str(root))
    assert "plugins/packs/official-a-1.0.0.dfypet-plugin.zip" in official, official
    assert "plugins/packs/someone-elses.zip" not in official, "用户塞进 packs/ 的文件被当官方了"
    hits = chk.plugin_user_data_hits(
        ["plugins/packs/someone-elses.zip", "plugins/packs/official-a-1.0.0.dfypet-plugin.zip"],
        str(root))
    assert hits == ["plugins/packs/someone-elses.zip"], hits


def test_官方集合_索引坏掉时宁可不认(tmp_path, monkeypatch):
    """控制组：索引坏了 → 官方包集合退化成空（只保留清单里的 index.json / README.md），
    绝不"因为读不出来就把 packs/ 里的一切都当官方"。

    能真失败：把 plugin_official_packs 的坏 JSON 分支改成 os.walk 兜底 → 第一条断言红。
    """
    root = tmp_path / "repo"
    (root / "plugins" / "packs").mkdir(parents=True)
    (root / "plugins" / "index.json").write_text("{ 不是 json", encoding="utf-8")
    (root / "plugins" / "packs" / "who-knows.zip").write_bytes(b"PK")
    monkeypatch.setattr(chk, "SYNC_FILES", ["plugins/index.json"])
    official = chk.plugin_official_names(str(root))
    assert "plugins/packs/who-knows.zip" not in official, official
    assert official == {"plugins/index.json"}, official


def test_用户插件条目带顶层目录前缀也要点名(tmp_path, monkeypatch):
    """① 发布包条目可能带一层顶层目录（desktop-pet/plugins/<id>/…）。check_zip 的
    _normalize_names 只在"所有条目共用一个顶层段"时才剥——包里混一个根目录文件就不剥了，
    只认 n.startswith("plugins/") 的判据会整片漏判。

    能真失败：去掉 plugin_entry_rel 的"逐条剥一层" → 用户条目不再被点名，红。
    """
    monkeypatch.setattr(chk, "plugin_official_names",
                        lambda root=None: {"plugins/index.json"})
    hits = chk.plugin_user_data_hits([
        "desktop-pet/plugins/user-thing/manifest.json",
        "desktop-pet/plugins/index.json",
        "desktop-pet/README.md",
        "plugins/other-user/manifest.json"], str(tmp_path))
    assert hits == ["desktop-pet/plugins/user-thing/manifest.json",
                    "plugins/other-user/manifest.json"], hits
    # 目录条目（以 / 结尾）不是文件
    assert chk.plugin_user_data_hits(["desktop-pet/plugins/user-thing/"]) == []


def test_反向校验_白名单外的模块名也要报(tmp_path, monkeypatch):
    """③ 判据此前**只认 pet_ 前缀**：import plugin_util 这种漏件（打包时缺文件 → 用户双击
    ImportError）一条都报不出来。白名单 = 标准库 + 随包发货的本仓模块 + 运行时第三方。

    能真失败：把 imported_runtime_modules 的过滤改回 top.startswith("pet_") → 第一条断言红。
    """
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pet_alpha.py").write_text(
        "import json\nimport os.path\nimport plugin_util\nimport pet_beta\n", encoding="utf-8")
    (root / "pet_beta.py").write_text("X = 1\n", encoding="utf-8")
    monkeypatch.setattr(chk, "SYNC_FILES", ["pet_alpha.py", "pet_beta.py"])
    found = chk.imported_runtime_modules(str(root))
    assert set(found) == {"plugin_util"}, found
    fails = chk.check_imported_modules_shipped(str(root))
    assert len(fails) == 1 and "plugin_util" in fails[0] and "pet_alpha.py" in fails[0], fails


def test_第三方依赖白名单与requirements一致():
    """白名单不是拍脑袋：IMPORT_EXTERNAL_ALLOW 必须覆盖 requirements.txt 声明的运行时依赖
    （漏一个 → 反向校验对真仓假红；所以这条把两处口径钉在一起）。

    能真失败：把 "requests" 从 IMPORT_EXTERNAL_ALLOW 里删掉 → 这条红（真仓扫描也会红）。
    """
    req = io.open(os.path.join(chk.ROOT, "requirements.txt"), encoding="utf-8").read()
    for pkg in ("PySide6", "requests", "psutil"):
        assert pkg in req, "前提不成立：%s 不在 requirements.txt 里" % pkg
        assert pkg in chk.IMPORT_EXTERNAL_ALLOW, "%s 不在反向校验白名单里" % pkg
    for top in sorted(chk.runtime_imports()):
        assert (top in chk._stdlib_module_names() or top in chk.IMPORT_EXTERNAL_ALLOW
                or top in chk.shipped_module_names()), \
            "真仓 import 了一个不在白名单里的顶层模块：%s" % top


# ---------------- v2.6.0 第 4 轮（兼容审查 P2-2 / P2-3） ----------------

def test_发布包里的用户自建人设必须点名(tmp_path):
    """P2-2：prompts/custom/ 是**用户数据**——打包时必须点名（此前进出口是敞的）。

    落地目标就是 <数据目录>/prompts/custom/（插件 prompt 类内容 + 用户自建人设都在那儿），
    却在 SYNC_FILES 与 USER_DATA_DIRS 两边都没有位置：把绿色版目录整体打包时，用户自己
    的人设会随包发出去（与 plugins/<id>/ 有白名单判据的处理完全不对称）。
    能真失败：把 "prompts/custom" 从 USER_DATA_DIRS 里去掉 → 第一条断言红。
    """
    p = str(tmp_path / "withprompts.zip")
    _make_zip(p, ["桌宠.py", "main.py", "python.exe", "assets/",
                  "prompts/custom/我的人设.txt", "prompts/default.txt"])
    fails = chk.check_zip(p, chk.repo_version())
    joined = " ".join(fails)
    assert "prompts/custom/我的人设.txt" in joined, "用户自建人设没被点名：%s" % joined
    # 反向：内置预设 prompts/*.txt 是**要随包发货**的（首启从内置常量生成），不许被误伤
    assert "prompts/default.txt" not in joined, "内置预设被误判成用户数据：%s" % joined


def _git_check_ignore(*paths):
    """git check-ignore → 每条路径是否被忽略（True = 被忽略）。"""
    out = []
    for p in paths:
        r = subprocess.run(["git", "check-ignore", "-q", p], cwd=chk.ROOT,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30)
        out.append(r.returncode == 0)
    return out


def test_插件运行时刻产物必须被忽略(tmp_path):
    """P2-3：手测一次"更新"留下的 .prev-<id>/ 与 _download/ 不许弄脏 git status。

    本仓的开发方式就是"直接在仓库里跑桌宠"（仓库目录同时是数据目录）→ 缺一条忽略规则，
    发布门 check_clean_tree 就会在**手测之后**判"未跟踪文件"（门红）。
    能真失败：把 plugins/*/ 与 !plugins/packs/ 两条删掉 → 前三条断言红。
    """
    ignored = _git_check_ignore("plugins/_download/a.part",
                                "plugins/.prev-demo/manifest.json",
                                "plugins/demo/manifest.json")
    assert ignored == [True, True, True], (
        "插件运行时刻产物没进 .gitignore（手测一次市场安装就会把发布门弄红）：%r" % (ignored,))
    # 反向：随包发货的三类**必须仍可见**（plugins/*/ 不许把它们一起吞掉）
    keep = _git_check_ignore("plugins/index.json", "plugins/README.md",
                             "plugins/packs/official-lines-moyu-1.0.0.dfypet-plugin.zip")
    assert keep == [False, False, False], (
        "要随包发货的插件资产被 .gitignore 吞掉了：%r" % (keep,))
