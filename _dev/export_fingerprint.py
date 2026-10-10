# -*- coding: utf-8 -*-
"""导出包指纹（供 _dev/compare_export_baseline.py 在**两边**分别跑一次）。

在指定仓库里造同一个角色、导出同一个包，把**逐条目指纹**打到 stdout（JSON）：
  {"order": [条目名...], "entries": {名: [未压长度, CRC32, 内容 sha256]}, "manifest": {...}}
指纹只看解压后的内容与条目名，不看压缩后的字节——zip 的条目时间戳带"当前时间"，
字节级比对本来就不可重复（这一点在报告里写清楚了）。

用法：python _dev/export_fingerprint.py --repo <仓库路径> --out <输出 json>
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import zipfile


def build_role(root):
    """造一个确定性的角色：素材直接取仓库 assets/ 里的真实 PNG（两边逐字节相同）。"""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = os.path.join(here, "assets")
    names = []
    roles = os.path.join(root, "roles")
    os.makedirs(roles, exist_ok=True)
    picks = sorted(n for n in os.listdir(src)
                   if n.startswith(("idle_f", "idle_full_f", "eat_f")) and n.endswith(".png"))
    for i, n in enumerate(picks):
        dst = "fp_%02d.png" % i
        shutil.copyfile(os.path.join(src, n), os.path.join(roles, dst))
        names.append(dst)
    role = {"id": "fp1", "name": "指纹角色", "file": names[0], "form": "dual",
            "file_full": names[1], "frames": list(names), "added": "",
            "forms": [{"name": "常态", "file": names[0], "front": names[2],
                       "animations": {"idle": list(names), "eat": list(names[:3])},
                       "states": {"angry": names[3], "blush": names[4]}},
                      {"name": "吃饱", "file": names[1], "front": names[1]}]}
    with open(os.path.join(root, "roles.json"), "w", encoding="utf-8") as fp:
        json.dump({"roles": [role], "active": "fp1"}, fp, ensure_ascii=False)
    return role


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    sys.path.insert(0, os.path.abspath(args.repo))
    import pet_export
    import pet_resources

    tmp = tempfile.mkdtemp(prefix="fp_export_")
    try:
        build_role(tmp)
        lib = pet_resources.RoleLibrary(tmp)
        out = os.path.join(tmp, "fp.dfypet.zip")
        ok, err = pet_export.export_bundle(lib, None, {"role": "fp1"}, out)
        if not ok:
            print(json.dumps({"ok": False, "err": err}, ensure_ascii=False))
            return 1
        with zipfile.ZipFile(out) as zf:
            order = zf.namelist()
            entries = {}
            for info in zf.infolist():
                data = zf.read(info.filename)
                entries[info.filename] = [info.file_size, info.CRC,
                                          hashlib.sha256(data).hexdigest()]
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        with open(args.out, "w", encoding="utf-8") as fp:
            json.dump({"ok": True, "order": order, "entries": entries,
                       "manifest": manifest}, fp, ensure_ascii=False, indent=1)
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
