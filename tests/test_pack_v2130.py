# -*- coding: utf-8 -*-
"""v2.13.0（体积与暴露面）打包白名单 / 瘦身清单的钉子。

这些判据守的是**清单本身**，不是某一次打包的读数：
- 瘦身清单只能删产品不用的东西：产品真 import 的 PySide6 模块必须都在 KEEP 里；
- KEEP 里写着的绑定必须真的被用（否则白留一块），唯一的例外是 QtNetwork（QtMultimedia 动态 import）；
- 两个明令保留的大件（opengl32sw.dll / avcodec-61.dll）在清单里且不会被瘦身规则命中；
- 发布包体积/条目/顶层白名单三条上限 = 150 MiB / 1300 / PACK_TOP_ALLOWED。

真包那几条（zip / 绿色版目录存在时才跑）在 CI 上没有 zip，会 skip——这是有意的：
CI 的职责是守清单，发版机才守读数。
"""
import os
import re
import sys
import zipfile

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import _check_release as rel  # noqa: E402


def _product_pyside_modules():
    """仓库根 *.py 里 `from PySide6.X import` / `import PySide6.X` 的 X 集合。"""
    pat = re.compile(r"(?:from|import)\s+PySide6\.([A-Za-z0-9_]+)")
    mods = set()
    for name in os.listdir(HERE):
        if not name.endswith(".py"):
            continue
        with open(os.path.join(HERE, name), encoding="utf-8", errors="replace") as f:
            for m in pat.finditer(f.read()):
                mods.add(m.group(1))
    return mods


def test_every_kept_binding_is_actually_imported():
    """KEEP 里的绑定必须真被产品 import（白留 = 白占体积）。

    红法：把某模块从产品代码里删掉却忘了从 PACK_PY_KEEP 移除 → 这里红。
    唯一豁免：QtNetwork —— QtMultimedia 的抽帧路径在 C++ 侧动态 import 它
    （实测：删掉 QtNetwork.pyd → 'libshiboken: could not import module PySide6.QtNetwork'）。
    """
    used = _product_pyside_modules()
    keep = set(rel.PACK_PY_KEEP)
    assert keep - used == {"QtNetwork"}, "KEEP 里有产品根本没 import 的绑定：%r" % (keep - used - {"QtNetwork"},)


def test_pruned_bindings_are_not_imported_by_product():
    """反过来：产品 import 的每个 PySide6 模块都必须在 KEEP 里（不许删到还在用的）。

    红法：新增 `from PySide6.QtSvg import ...` 却没往 KEEP 加 → 瘦身后用户双击 ImportError。
    """
    used = _product_pyside_modules()
    assert used <= set(rel.PACK_PY_KEEP), "产品用了会被瘦身删掉的绑定：%r" % (used - set(rel.PACK_PY_KEEP),)


def test_prune_hits_only_expected_shapes():
    """瘦身规则命中面：qml/resources/未用绑定/未用 DLL/Qt 开发 exe/类型桩/abi3 qml 库。"""
    hit = rel.pack_prune_hits
    assert hit(["Lib/site-packages/PySide6/qml/QtQuick/plugin.dll"])
    assert hit(["Lib/site-packages/PySide6/resources/qtwebengine_devtools_resources.pak"])
    assert hit(["Lib/site-packages/PySide6/QtOpenGL.pyd"])
    assert hit(["Lib/site-packages/PySide6/Qt6Pdf.dll"])
    assert hit(["Lib/site-packages/PySide6/assistant.exe"])
    assert hit(["Lib/site-packages/PySide6/QtCore.pyi"])
    assert hit(["Lib/site-packages/PySide6/pyside6qml.abi3.dll"])
    assert hit(["Lib/distutils/__init__.py"])
    # 保留面：四个真绑定 + QtNetwork + Qt6 核心 DLL + 两个大件都不许命中
    for keep in ("QtCore.pyd", "QtGui.pyd", "QtWidgets.pyd", "QtMultimedia.pyd",
                 "QtNetwork.pyd", "Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll",
                 "Qt6Multimedia.dll", "Qt6Network.dll", "Qt6OpenGL.dll",
                 "opengl32sw.dll", "avcodec-61.dll"):
        assert hit(["Lib/site-packages/PySide6/" + keep]) == [], keep
    # 产品文件/素材绝不能被瘦身规则命中
    assert hit(["桌宠.py", "main.py", "assets/character.png", "plugins/index.json"]) == []


def test_keep_list_is_the_two_declared_big_items():
    """§23.4 明令保留的两个大件：清单必须是这两个，一个不多一个不少。"""
    assert tuple(rel.PACK_KEEP) == ("opengl32sw.dll", "avcodec-61.dll")


def test_caps_match_the_round_requirement():
    """第 13 轮的硬指标：解压 ≤150 MiB、条目 ≤1300。"""
    assert rel.PACK_CAP_FILES == 1300
    assert rel.PACK_CAP_BYTES == 150 * 1024 * 1024


def test_top_level_whitelist_covers_all_shipped_runtime_modules():
    """顶层白名单必须覆盖 SYNC_FILES 里每一个顶层条目。

    红法：新增模块进 SYNC_FILES 但忘了进 PACK_TOP_ALLOWED → 打包后发布门红（这里先红）。
    例外：plugins/ 下的文件（顶层是 plugins）与 _verify_green.py（按设计不进包）。
    """
    for name in rel.SYNC_FILES:
        if name == "_verify_green.py" or name.startswith("plugins/"):
            continue
        top = name.split("/")[0]
        assert top in rel.PACK_TOP_ALLOWED, "SYNC_FILES 的 %r 不在顶层白名单里" % (name,)




def _clean_zip(path):
    """一个最小"合法包"：顶层全在白名单 + 两个保留项都在。"""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("main.py", "print('x')")
        z.writestr("Lib/site-packages/PySide6/opengl32sw.dll", "dll")
        z.writestr("Lib/site-packages/PySide6/avcodec-61.dll", "dll")
    return path


def test_check_pack_accepts_a_minimal_clean_zip(tmp_path):
    """正对照：不先证明"干净包能过"，后面三条红就分不清是判据准还是它恒红。"""
    zpath = _clean_zip(str(tmp_path / "clean.zip"))
    assert rel.check_pack(zpath) == [], rel.check_pack(zpath)


def test_check_pack_flags_whitelist_and_prune_hits(tmp_path):
    """**发布门本身**也要有判据：顶层白名单外的文件、瘦身清单里的开发件，都必须点名。

    红法：把 check_pack 改成 return [] → 本条红（v2.13.0 三审实测过这个洞：check_pack
    此前一条用例都没调）。
    """
    zpath = tmp_path / "evil.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("evil_top.py", "x")
        z.writestr("Lib/site-packages/PySide6/qml/QtQuick/plugin.dll", "x")
        z.writestr("Lib/site-packages/PySide6/opengl32sw.dll", "dll")
        z.writestr("Lib/site-packages/PySide6/avcodec-61.dll", "dll")
    fails = rel.check_pack(str(zpath))
    joined = " | ".join(fails)
    assert "白名单" in joined and "evil_top.py" in joined, joined
    assert "瘦身" in joined and "qml" in joined, joined


def test_check_pack_enforces_both_caps(monkeypatch, tmp_path):
    """条目数与解压体积两条上限：改小上限，干净包也必须红（否则上限是摆设）。"""
    zpath = _clean_zip(str(tmp_path / "caps.zip"))
    monkeypatch.setattr(rel, "PACK_CAP_FILES", 2)
    assert any("条目数" in f for f in rel.check_pack(zpath)), rel.check_pack(zpath)
    monkeypatch.setattr(rel, "PACK_CAP_FILES", 1300)
    monkeypatch.setattr(rel, "PACK_CAP_BYTES", 8)
    assert any("解压体积" in f for f in rel.check_pack(zpath)), rel.check_pack(zpath)


def test_check_pack_requires_the_two_kept_big_items(tmp_path):
    """§23.4 明令保留的两个大件：缺一个就红（防止瘦身顺手把它们删了）。"""
    zpath = tmp_path / "nokeep.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("main.py", "x")
        z.writestr("Lib/site-packages/PySide6/opengl32sw.dll", "dll")
    fails = rel.check_pack(str(zpath))
    assert any("avcodec-61.dll" in f for f in fails), fails

ZIP = os.path.join(HERE, "daifeiyu-desktop-pet.zip")


@pytest.mark.skipif(not os.path.isfile(ZIP), reason="发版机才有真包（CI 不守读数）")
def test_real_zip_is_within_budget_and_clean():
    """真包读数：≤1300 条目 / ≤150 MiB / 顶层全在白名单 / 没有一个瘦身命中。

    红法：重新打包时把整棵绿色版塞进去（带回 qml/resources）→ 条目与体积双超。
    """
    count, total, tops = rel.pack_stats(ZIP)
    assert count <= rel.PACK_CAP_FILES, "真包 %d 条目" % (count,)
    assert total <= rel.PACK_CAP_BYTES, "真包 %.1f MiB" % (total / 1048576.0,)
    assert tops <= rel.PACK_TOP_ALLOWED, "真包顶层越界：%r" % (sorted(tops - rel.PACK_TOP_ALLOWED),)
    with zipfile.ZipFile(ZIP) as z:
        names = [i.filename for i in z.infolist() if not i.is_dir()]
    assert rel.pack_prune_hits(names) == [], "真包里还有该删的开发件"


@pytest.mark.skipif(not os.path.isdir(rel.GREEN), reason="发版机才有绿色版目录")
def test_real_green_dir_is_already_pruned():
    """绿色版目录本身也要干净：瘦身清单里的路径一个都不许还在（否则下次打包又带回去）。"""
    left = []
    for base, _dirs, files in os.walk(rel.GREEN):
        for f in files:
            relpath = os.path.relpath(os.path.join(base, f), rel.GREEN).replace(os.sep, "/")
            if rel.pack_prune_hits([relpath]):
                left.append(relpath)
    assert left == [], "绿色版里还剩 %d 个该删的开发件：%r" % (len(left), left[:8])