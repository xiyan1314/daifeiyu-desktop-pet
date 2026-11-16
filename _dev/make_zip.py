# -*- coding: utf-8 -*-
"""白名单打包（v2.13.0 · 可重复执行）：绿色版目录 → `daifeiyu-desktop-pet.zip`。

**绝不许整目录打包**：数据/插件白名单来自 `_check_release`（`USER_DATA_NAMES` /
`USER_DATA_DIRS` / `ZIP_EXTRA_NAMES` / `ZIP_EXTRA_PREFIX` + `plugin_official_names()`），
本脚本另加自己的开发件规则（`SKIP_DIRS` 与 `requirements*.txt`）——**这两条不在** `_check_release` 里，
所以口径不是"单一来源"而是"收窄 + 复核"：产出后由发布门的 `check_zip()`（用户数据/插件）
与 `check_pack()`（顶集/瘦身/体积）**各自独立复核一遍**，两边都跑才无洞。

用法：`python -B _dev/make_zip.py [输出路径]`
"""
import hashlib
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import _check_release as rel  # noqa: E402

# 发布包里**按设计**不带的目录（开发/验证/用户人设生成物）。
# prompts/ 整个跳过：三份内置预设是首启**从内置常量生成**的（桌宠.py 的 SYSTEM_PROMPT 等），
# 历次发布包都没有它；用户自建的 prompts/custom 更是用户数据。
SKIP_DIRS = ("_dev", "_verify_assets", "prompts", "__pycache__", "_index_cache")


def _skip(relpath):
    parts = relpath.split("/")
    if parts[0] in SKIP_DIRS:
        return True
    base = parts[-1]
    if base in rel.ZIP_EXTRA_NAMES:
        return True
    # 源码运行的依赖清单是开发件（绿色版自带解释器与依赖），v2.12.0 的包里也没有它。
    if base.startswith("requirements") and base.endswith(".txt"):
        return True
    if any(relpath.startswith(p) for p in rel.ZIP_EXTRA_PREFIX):
        return True
    if rel.user_data_hit(base):
        return True
    if any(parts[0] == d or relpath.startswith(d + "/") for d in rel.USER_DATA_DIRS):
        return True
    return False


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else rel.ZIP_DEFAULT
    green = rel.GREEN
    official = rel.plugin_official_names()
    entries = []
    for base, dirs, files in os.walk(green):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in sorted(files):
            full = os.path.join(base, f)
            relpath = os.path.relpath(full, green).replace(os.sep, "/")
            if _skip(relpath):
                continue
            if relpath.startswith(rel.PLUGIN_DIR) and relpath not in official:
                continue
            entries.append((full, relpath))
    entries.sort(key=lambda x: x[1])
    tmp = out + ".tmp"
    total = 0
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for full, arc in entries:
            total += os.path.getsize(full)
            z.write(full, arc)
    os.replace(tmp, out)
    h = hashlib.sha256()
    with open(out, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    print("PACK %s" % out)
    print("  entries=%d  uncompressed=%.1f MiB  compressed=%d B  sha256=%s"
          % (len(entries), total / 1048576.0, os.path.getsize(out), h.hexdigest()))
    print("  top=%r" % sorted({a.split("/")[0] for _f, a in entries})[:6])
    return 0


if __name__ == "__main__":
    sys.exit(main())