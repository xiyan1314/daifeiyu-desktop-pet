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
    """包里混进运行时数据/开发文件必须被点名。"""
    p = str(tmp_path / "bad.zip")
    _make_zip(p, ["桌宠.py", "main.py", "pet_voice.py", "pet_lines.py", "pet_dialogs.py",
                  "python.exe", "assets/", "config.json", "ledger.json", "error.log",
                  "_verify_green.py", "_check_static.py", "_check_release.py", "roles/x.png"])
    fails = chk.check_zip(p, chk.repo_version())
    joined = " ".join(fails)
    assert "config.json" in joined and "ledger.json" in joined
    assert "error.log" in joined and "_verify_green.py" in joined
    assert "_check_static.py" in joined and "_check_release.py" in joined
    assert any("roles/" in f for f in fails)


def test_check_zip_flags_missing_and_stale(tmp_path):
    p = str(tmp_path / "old.zip")
    _make_zip(p, ["桌宠.py", "main.py"], version="1.0.0")  # 缺模块 + 版本旧
    fails = chk.check_zip(p, "2.0.0")
    joined = " ".join(fails)
    assert "缺关键内容" in joined
    assert "旧版本" in joined


def test_check_zip_passes_clean(tmp_path):
    p = str(tmp_path / "ok.zip")
    # v2.3.0：check_zip 的 need 改为"SYNC_FILES 里全部运行时 .py 正向校验"（修 S1：漏检
    # pet_tools.py 会静默放行一个启动即崩的包），所以合成包必须覆盖这份清单，不能再手写几项。
    _runtime = sorted(n for n in chk.SYNC_FILES
                      if n.endswith(".py") and "/" not in n and n != "_verify_green.py")
    _make_zip(p, _runtime + ["python.exe", "assets/char.png", "Lib/x.py"],
              version=chk.repo_version(), real_main=True)
    assert chk.check_zip(p, chk.repo_version()) == []


def test_check_zip_flags_same_version_but_stale_content(tmp_path):
    """M3 回归：版本号相同但内容不同（拿旧包冒充）必须被抓到。"""
    p = str(tmp_path / "stale.zip")
    _make_zip(p, ["桌宠.py", "main.py", "pet_voice.py", "pet_lines.py", "pet_dialogs.py",
                  "python.exe", "assets/char.png"], version=chk.repo_version(), real_main=False)
    fails = chk.check_zip(p, chk.repo_version())
    assert any("内容不一致" in f for f in fails), fails


def test_check_version_of_this_repo():
    """当前仓库三处版本号必须一致（护栏的一部分）。"""
    assert chk.check_version() == []
    assert chk.repo_version() not in ("", "?")


def test_check_sync_reports_list():
    """同步检查返回 (缺失, 不一致) 两个列表（结构稳定）。"""
    missing, diff = chk.check_sync()
    assert isinstance(missing, list) and isinstance(diff, list)