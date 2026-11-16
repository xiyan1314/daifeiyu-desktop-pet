# -*- coding: utf-8 -*-
"""绿色版瘦身（v2.13.0 第 13 轮 · 体积与暴露面）。

策略的唯一来源是 `_check_release.PACK_PRUNE_DIRS / PACK_PY_KEEP / PACK_DLL_KEEP / PACK_KEEP`——
本脚本**不自己抄一份清单**。发布门的 `check_pack()` 用同一份清单反向检查发布包，
所以"删了又长回来"会在发版时当场红。

用法（先副本后真包）：
    python _dev/prune_green.py --root 'E:\\deep seek\\_v2130_green_trial' --dry-run
    python _dev/prune_green.py --root 'E:\\deep seek\\_v2130_green_trial' --apply
    python _dev/prune_green.py --apply          # 默认 root = _check_release.GREEN（真包）

安全底线（T0-06）：只删\*\*解析后仍在 root 之内\*\*的路径；root 必须同时有
`桌宠.py` / `main.py` / `Lib/site-packages/PySide6` 三样东西；root 不许是仓库根/盘根。
"""
import argparse
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import _check_release as rel  # noqa: E402


def _size(paths):
    n = 0
    total = 0
    for p in paths:
        if os.path.isfile(p):
            n += 1
            total += os.path.getsize(p)
        else:
            for base, _dirs, files in os.walk(p):
                for f in files:
                    n += 1
                    try:
                        total += os.path.getsize(os.path.join(base, f))
                    except OSError:
                        pass
    return n, total


def _inside(root, path):
    root = os.path.abspath(root)
    path = os.path.abspath(path)
    try:
        return os.path.commonpath([root, path]) == root and path != root
    except ValueError:
        return False


def _check_root(root):
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise SystemExit("root 不存在：%s" % root)
    if os.path.dirname(root) == root or root == os.path.abspath(ROOT):
        raise SystemExit("拒绝在仓库根/盘根上跑瘦身：%s" % root)
    for need in ("桌宠.py", "main.py", os.path.join("Lib", "site-packages", "PySide6")):
        if not os.path.exists(os.path.join(root, need)):
            raise SystemExit("root 不像绿色版（缺 %s）：%s" % (need, root))
    return root


def collect(root):
    """→ (待删路径列表, 保留项是否存在)。"""
    out = []
    for d in rel.PACK_PRUNE_DIRS:
        p = os.path.join(root, d.replace("/", os.sep))
        if os.path.exists(p):
            out.append(p)
    ps = os.path.join(root, "Lib", "site-packages", "PySide6")
    if os.path.isdir(ps):
        for name in sorted(os.listdir(ps)):
            p = os.path.join(ps, name)
            if not os.path.isfile(p):
                continue
            if name.endswith(".pyi") or name.endswith(".exe") or name == "pyside6qml.abi3.dll":
                out.append(p)
            elif name.endswith(".pyd") and name[:-4] not in rel.PACK_PY_KEEP:
                out.append(p)
            elif (name.startswith("Qt6") and name.endswith(".dll")
                  and name not in rel.PACK_DLL_KEEP):
                out.append(p)
    # 去重 + 去掉"父目录已被整目录删掉"的子项
    uniq = []
    seen = set()
    for p in sorted(set(out), key=len):
        ap = os.path.abspath(p)
        if ap in seen:
            continue
        if any(ap.startswith(q + os.sep) for q in uniq):
            continue
        seen.add(ap)
        uniq.append(ap)
    keeps = []
    for k in rel.PACK_KEEP:
        hit = []
        for base, _dirs, files in os.walk(root):
            if k in files:
                hit.append(os.path.join(base, k))
            if len(hit) >= 2:
                break
        keeps.append((k, hit))
    return uniq, keeps


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=rel.GREEN)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不删（默认行为，写出来更清楚）")
    args = ap.parse_args(argv)
    root = _check_root(args.root)
    targets, keeps = collect(root)
    before_n, before_b = _size([root])
    del_n, del_b = _size(targets)
    print("root   : %s" % root)
    print("before : %d files / %.1f MiB" % (before_n, before_b / 1048576.0))
    print("计划删 : %d 项 / %d files / %.1f MiB" % (len(targets), del_n, del_b / 1048576.0))
    print("删除后 : %d files / %.1f MiB（目标 ≤%d / %.0f MiB）"
          % (before_n - del_n, (before_b - del_b) / 1048576.0,
             rel.PACK_CAP_FILES, rel.PACK_CAP_BYTES / 1048576.0))
    for k, hit in keeps:
        print("保留项 : %-16s %s" % (k, ("OK %d 份" % len(hit)) if hit else "!! 缺失"))
    if not args.apply:
        for p in targets:
            print("  DRY %s" % os.path.relpath(p, root))
        return 0
    bad = [p for p in targets if not _inside(root, p)]
    if bad:
        raise SystemExit("拒绝：以下路径解析后不在 root 内（T0-06）：%r" % bad)
    fails = 0
    for p in targets:
        try:
            if os.path.isdir(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
        except OSError as e:
            fails += 1
            print("  FAIL %s: %r" % (os.path.relpath(p, root), e))
    after_n, after_b = _size([root])
    print("after  : %d files / %.1f MiB" % (after_n, after_b / 1048576.0))
    print("PRUNE %s（失败 %d）" % ("OK" if not fails else "PARTIAL", fails))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())