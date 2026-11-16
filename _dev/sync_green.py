# -*- coding: utf-8 -*-
"""绿色版同步（v2.13.0 · 可重复执行）：只同步 `_check_release._sync_pairs()` 列出的文件。

规矩（沿用 v2.11.0 runbook ⑩）：
  · 判据单一来源 = `_check_release.SYNC_FILES` + 官方插件资产 + `assets/` 全量；
  · **显式目标路径逐个拷**（`Copy-Item -Destination <目录>` 会拍平路径）；
  · 逐文件 sha256 比对；不碰用户数据（config/ledger/roles/lines/error.log…）。
  · 跑完打印 `_check_release.check_sync()` 的 (缺失, 不一致)。

用法：`python -B _dev/sync_green.py`（默认 GREEN）。
"""
import hashlib
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import _check_release as rel  # noqa: E402


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    green = rel.GREEN
    if not os.path.isdir(green):
        raise SystemExit("绿色版目录不存在：%s" % green)
    copied = skipped = 0
    fails = []
    for name in rel._sync_pairs():
        src = os.path.join(ROOT, name.replace("/", os.sep))
        dst = os.path.join(green, name.replace("/", os.sep))
        if not os.path.isfile(src):
            fails.append("仓库缺文件：%s" % name)
            continue
        d = os.path.dirname(dst)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        if os.path.isfile(dst) and _sha(src) == _sha(dst):
            skipped += 1
            continue
        shutil.copy2(src, dst)
        if _sha(src) != _sha(dst):
            fails.append("拷贝后哈希不一致：%s" % name)
        copied += 1
    # 清缓存：绿色版目录里不许有 __pycache__ / _index_cache
    removed = 0
    for base, dirs, _files in os.walk(green):
        for d in list(dirs):
            if d in ("__pycache__", "_index_cache"):
                shutil.rmtree(os.path.join(base, d), ignore_errors=True)
                dirs.remove(d)
                removed += 1
    missing, diff = rel.check_sync()
    print("同步：拷贝 %d / 已一致 %d / 清缓存目录 %d" % (copied, skipped, removed))
    print("check_sync：缺失 %d / 不一致 %d" % (len(missing), len(diff)))
    for label, items in (("缺失", missing), ("不一致", diff)):
        for n in items:
            print("  %s %s" % (label, n))
    for f in fails:
        print("  FAIL", f)
    return 0 if not (missing or diff or fails) else 1


if __name__ == "__main__":
    sys.exit(main())