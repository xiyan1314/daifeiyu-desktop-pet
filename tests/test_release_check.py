# -*- coding: utf-8 -*-
"""_check_release.py 的自测：合成坏包/好包，验证四项检查真的会报错/放行。"""
import os
import sys
import zipfile

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