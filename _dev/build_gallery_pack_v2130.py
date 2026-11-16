# -*- coding: utf-8 -*-
"""生成第 13 轮的两个门面产物（可重复执行）：
  · docs/demo.gif              —— README 首屏 GIF（真实 idle + eat 帧，不画新图）
  · gallery/official_abyss.*   —— 1 个官方角色包 + 预览图（从 assets 派生，不用外部素材）

为什么用脚本：门面产物也要能被下一个人重建；手搓的 zip 说不清是怎么来的。
派生只做**色相旋转**（同一张 character.png / idle 帧），符合 plan §16「素材自己造或从现有素材派生」。
"""
import json
import os
import sys
import zipfile

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
DOCS = os.path.join(ROOT, "docs")
GALLERY = os.path.join(ROOT, "gallery")

RID = "official_abyss"
NAME = "深渊大肥鱼"
DESC = "官方的墨蓝配色派生版：同一只大肥鱼，换了身深水色。素材由内置 assets 色相旋转派生，无外部素材。"


def _hue_shift(src, dst, shift_deg, sat_boost=1.0, val_scale=1.0, frames=False):
    im = Image.open(src).convert("RGBA")
    hsv = im.convert("RGB").convert("HSV")
    h, s, v = hsv.split()
    h = h.point(lambda x: (x + int(shift_deg / 360.0 * 256)) % 256)
    s = s.point(lambda x: min(255, int(x * sat_boost)))
    v = v.point(lambda x: min(255, int(x * val_scale)))
    rgb = Image.merge("HSV", (h, s, v)).convert("RGB")
    out = Image.new("RGBA", im.size)
    out.paste(rgb, (0, 0))
    out.putalpha(im.getchannel("A"))
    out.save(dst, "PNG", optimize=True)
    return out


def build_gif():
    os.makedirs(DOCS, exist_ok=True)
    frames = []
    durs = []
    for i in range(10):
        frames.append(Image.open(os.path.join(ASSETS, "idle_f%02d.png" % i)).convert("RGBA"))
        durs.append(120)
    for i in range(7):
        frames.append(Image.open(os.path.join(ASSETS, "eat_f%02d.png" % i)).convert("RGBA"))
        durs.append(100)
    canvas_w, canvas_h = 320, 320
    composed = []
    for im in frames:
        bg = Image.new("RGBA", (canvas_w, canvas_h), (245, 243, 255, 255))
        im2 = im.resize((256, 256), Image.LANCZOS)
        bg.alpha_composite(im2, ((canvas_w - 256) // 2, (canvas_h - 256) // 2))
        composed.append(bg.convert("P", palette=Image.ADAPTIVE, colors=128))
    out = os.path.join(DOCS, "demo.gif")
    composed[0].save(out, save_all=True, append_images=composed[1:],
                     duration=durs, loop=0, optimize=True)
    return out, len(composed), os.path.getsize(out)


def build_pack():
    os.makedirs(GALLERY, exist_ok=True)
    tmp = os.path.join(GALLERY, "_build_roles")
    os.makedirs(tmp, exist_ok=True)
    side = os.path.join(tmp, RID + "_side.png")
    front = os.path.join(tmp, RID + "_front.png")
    _hue_shift(os.path.join(ASSETS, "character.png"), side, 175, 1.15, 0.82)
    _hue_shift(os.path.join(ASSETS, "character_front.png"), front, 175, 1.15, 0.82)
    idle = []
    for i in range(6):
        p = os.path.join(tmp, "%s_idle%02d.png" % (RID, i))
        _hue_shift(os.path.join(ASSETS, "idle_f%02d.png" % i), p, 175, 1.15, 0.82)
        idle.append(os.path.basename(p))
    role = {
        "id": RID, "name": NAME, "file": os.path.basename(side),
        "front": os.path.basename(front), "file_full": "", "form": "single",
        "frames": list(idle), "added": "",
        "forms": [{"name": "常态", "file": os.path.basename(side),
                   "front": os.path.basename(front),
                   "animations": {"idle": list(idle)}, "anim_interval_ms": 120}],
    }
    manifest = {"format": "dfypet-role", "version": 1,
                "meta": {"name": NAME, "author": "官方", "desc": DESC,
                         "tags": ["官方", "派生", "墨蓝"]},
                "role": role, "behaviors": [], "config": {},
                "excluded": ["api_key"], "alarms": []}
    out = os.path.join(GALLERY, RID + ".dfypet.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
        for name in [os.path.basename(side), os.path.basename(front)] + idle:
            z.write(os.path.join(tmp, name), "roles/" + name)
    prev = Image.open(side).convert("RGBA")
    card = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    fish = prev.resize((180, 180), Image.LANCZOS)
    card.alpha_composite(fish, (10, 10))
    preview = os.path.join(GALLERY, RID + "_preview.png")
    card.save(preview, "PNG", optimize=True)
    for p in [side, front] + [os.path.join(tmp, n) for n in idle]:
        os.remove(p)
    os.rmdir(tmp)
    return out, preview


def main():
    gif, n, size = build_gif()
    print("GIF  %s  frames=%d  %d B" % (os.path.relpath(gif, ROOT), n, size))
    pack, prev = build_pack()
    sys.path.insert(0, ROOT)
    import pet_export
    manifest, err = pet_export.validate_bundle(pack)
    if manifest is None:
        print("PACK INVALID:", err)
        return 1
    refs = pet_export._role_file_refs(manifest["role"])
    print("PACK %s  %d B  refs=%d" % (os.path.relpath(pack, ROOT), os.path.getsize(pack), len(refs)))
    print("PREV %s  %d B" % (os.path.relpath(prev, ROOT), os.path.getsize(prev)))
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())