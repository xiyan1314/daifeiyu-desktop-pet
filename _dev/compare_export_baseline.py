# -*- coding: utf-8 -*-
"""导出包 A/B：在**基线树**与**当前树**里各导出同一个角色，逐条目比对内容指纹。

判据（本轮的硬性要求）：包内**条目名 / 顺序 / 结构 / 内容**必须与改动前一致。
比的是解压后的内容（未压长度 + CRC32 + sha256），不是压缩后的字节——zip 条目时间戳
取"当前时间"，字节级本来就不可能重复（用"导出两次比字节"当判据会永远红）。

用法：
    python _dev/compare_export_baseline.py --baseline "E:\\deep seek\\wt-p-baseline"
退出码：0 = 两侧逐条目一致（或两侧都失败且错误文案一致）；1 = 有差异。
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fingerprint(repo):
    out = os.path.join(tempfile.gettempdir(), "fp_%d.json" % os.getpid())
    p = subprocess.run([sys.executable, os.path.join(repo, "_dev", "export_fingerprint.py"),
                        "--repo", repo, "--out", out],
                       cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if not os.path.isfile(out):
        return {"ok": False, "err": "指纹脚本没产出（rc=%d）：%s"
                % (p.returncode, p.stdout.decode("utf-8", "replace")[-400:])}
    with open(out, encoding="utf-8") as fp:
        data = json.load(fp)
    os.unlink(out)
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--current", default=HERE)
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    a = fingerprint(args.baseline)
    b = fingerprint(args.current)
    print("基线 %s\n当前 %s" % (args.baseline, args.current))
    if not a.get("ok") or not b.get("ok"):
        same = (not a.get("ok")) and (not b.get("ok")) and a.get("err") == b.get("err")
        print("两侧都没导出成功：基线 %r / 当前 %r" % (a.get("err"), b.get("err")))
        print("错误文案一致：%s" % ("是" if same else "否"))
        return 0 if same else 1

    ok = True
    if a["order"] != b["order"]:
        print("条目名/顺序不一致：\n  基线 %r\n  当前 %r" % (a["order"], b["order"]))
        ok = False
    else:
        print("条目顺序一致：%d 条 → %r" % (len(a["order"]), a["order"][:4] + ["…"]))
    diff = [k for k in a["entries"] if a["entries"][k] != b["entries"].get(k)]
    if diff:
        print("条目内容指纹不一致：%r" % diff[:8])
        for k in diff[:3]:
            print("  %s\n    基线 %r\n    当前 %r" % (k, a["entries"][k], b["entries"].get(k)))
        ok = False
    else:
        print("逐条目内容指纹一致（未压长度 + CRC32 + sha256）：%d 条" % len(a["entries"]))
    if json.dumps(a["manifest"], sort_keys=True, ensure_ascii=False) != \
            json.dumps(b["manifest"], sort_keys=True, ensure_ascii=False):
        print("manifest 内容不一致")
        ok = False
    else:
        print("manifest 内容一致")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fp:
            json.dump({"baseline": a, "current": b}, fp, ensure_ascii=False, indent=1)
        print("JSON → %s" % args.json)
    print("\n导出包产出格式：%s" % ("与改动前一致" if ok else "有差异"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
