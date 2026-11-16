# -*- coding: utf-8 -*-
"""v2.13.0（体积与暴露面）的两个门面判据：README 首屏 GIF + gallery 官方包。

- 首屏 GIF：必须要有一个**真的能播**的 GIF（帧数/尺寸/体积都钉），且 README 首屏引用它；
- 官方包：gallery/ 里必须恰好一对 `<id>.dfypet.zip` + `<id>_preview.png`，包能过
  `pet_export.validate_bundle`，包内只有 manifest + roles/*.png（审核标准：不许带脚本/可执行），
  且 README（中英）的表格链接到它。

能真失败：删掉 GIF / 把 README 引用改成坏路径 / 包里塞一个 .exe / 预览图与包不成对 → 红。
"""
import os
import zipfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GIF = os.path.join(REPO, "docs", "demo.gif")
GALLERY = os.path.join(REPO, "gallery")


def test_readme_first_screen_references_an_existing_gif():
    assert os.path.isfile(GIF), "README 首屏 GIF 不存在：docs/demo.gif"
    for name in ("README.md", "README.en.md"):
        text = open(os.path.join(REPO, name), encoding="utf-8").read()
        head = text[:4000]
        assert "docs/demo.gif" in head, "%s 首屏没有引用 docs/demo.gif" % name


def test_gif_is_a_real_multi_frame_animation():
    from PIL import Image
    im = Image.open(GIF)
    assert im.size == (320, 320), im.size
    assert getattr(im, "n_frames", 1) >= 12, "GIF 只有 %d 帧（要能看出待机/吃播）" % getattr(im, "n_frames", 1)
    assert os.path.getsize(GIF) <= 1024 * 1024, "GIF 太大（README 首屏要秒开）：%d B" % os.path.getsize(GIF)


def _packs():
    return sorted(n for n in os.listdir(GALLERY) if n.endswith(".dfypet.zip"))


def test_gallery_has_exactly_one_official_pack():
    packs = _packs()
    assert packs == ["official_abyss.dfypet.zip"], "gallery/ 里应恰好 1 个官方包：%r" % (packs,)
    prev = os.path.join(GALLERY, "official_abyss_preview.png")
    assert os.path.isfile(prev), "官方包缺预览图（规范要求成对）"
    from PIL import Image
    im = Image.open(prev)
    assert max(im.size) <= 200, "预览图超过 200×200：%r" % (im.size,)


def test_official_pack_is_valid_and_clean():
    import sys
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    import pet_export
    pack = os.path.join(GALLERY, "official_abyss.dfypet.zip")
    manifest, err = pet_export.validate_bundle(pack)
    assert manifest is not None, err
    assert manifest["role"]["name"], "角色没有名字"
    assert manifest.get("meta", {}).get("author") == "官方"
    with zipfile.ZipFile(pack) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
    bad = [n for n in names if not (n == "manifest.json" or n.startswith("roles/"))]
    assert bad == [], "官方包里有不该带的东西：%r" % (bad,)
    exe = [n for n in names if n.lower().endswith((".exe", ".dll", ".py", ".bat", ".ps1"))]
    assert exe == [], "官方包里带了可执行/脚本：%r" % (exe,)
    refs = pet_export._role_file_refs(manifest["role"])
    missing = [r for r in refs if "roles/" + r not in names]
    assert missing == [], "包内缺素材：%r" % (missing,)


def test_readme_tables_link_the_official_pack():
    for name in ("README.md", "README.en.md"):
        text = open(os.path.join(REPO, name), encoding="utf-8").read()
        assert "gallery/official_abyss.dfypet.zip" in text, "%s 没有链到官方包" % name
        assert "gallery/official_abyss_preview.png" in text, "%s 没有链到预览图" % name