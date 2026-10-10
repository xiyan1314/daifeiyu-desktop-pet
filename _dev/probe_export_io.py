# -*- coding: utf-8 -*-
"""导出耗时归因（二）：**首次读盘 vs 缓存命中**占多少（只读测量）。

probe_export_cost.py 给出的是"export_bundle 合计 ≈130 ms，其中自带的 zip 写盘段 ≈100 ms"；
可同一批文件**再写一遍**只要 ≈19 ms。差额不是 zlib，是**第一次把这些 PNG 从磁盘读出来**
（实测 600 KB 冷读 65.6 ms、再读 0.98 ms；同一批文件冷写 zip 75.9 ms、温写 16.3 ms）。

这个结论决定了"剩余耗时为什么不再继续优化"：
  · 冷读是文件系统/杀软路径上的 I/O，不是 Python 也不是压缩——不把文件写进包就省不掉；
  · 真正能省的只有压缩：level 6 → level 1 省 ≈1 ms/600KB，→ STORED 省 ≈12 ms/600KB，
    代价是**改变产出字节**（本轮硬性要求：包内条目名/结构/内容与旧版一致），
    而且 deflate 对已压缩的 PNG 只买到 0.13% 体积（593.29 KB vs 594.07 KB）——
    留作后续单独立项（要先改"产出格式不变"的验收口径）。

用法：python _dev/probe_export_io.py [--rounds 3]
退出码：0 = 测出来了；1 = 前置条件不成立（造不出角色）。
"""
import argparse
import os
import shutil
import statistics
import sys
import tempfile
import time
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from probe_export_cost import make_role  # noqa: E402

import pet_export  # noqa: E402


def _zip_write(paths, out, level=None):
    t0 = time.perf_counter()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=level) as zf:
        for p in paths:
            zf.write(p, "roles/" + os.path.basename(p))
    return (time.perf_counter() - t0) * 1000.0, os.path.getsize(out)


def one_round(root):
    lib, cfg = make_role(root)          # 素材是本轮刚 copy 出来的 = 真实的"冷"
    refs = pet_export._role_file_refs(lib.get("probe1"))
    paths = [lib.resolve(r) for r in refs]
    total = sum(os.path.getsize(p) for p in paths)
    t0 = time.perf_counter()
    for p in paths:
        with open(p, "rb") as f:
            f.read()
    cold = (time.perf_counter() - t0) * 1000.0
    t0 = time.perf_counter()
    for p in paths:
        with open(p, "rb") as f:
            f.read()
    warm = (time.perf_counter() - t0) * 1000.0
    z_cold, size = _zip_write(paths, os.path.join(root, "cold.zip"))
    z_warm, _ = _zip_write(paths, os.path.join(root, "warm.zip"))
    z_stored, size_store = _zip_write(paths, os.path.join(root, "store.zip"), level=0)
    z_l1, size_l1 = _zip_write(paths, os.path.join(root, "l1.zip"), level=1)
    t0 = time.perf_counter()
    ok, err = pet_export.export_bundle(lib, None, cfg, os.path.join(root, "bundle.zip"))
    bundle = (time.perf_counter() - t0) * 1000.0
    return {"files": len(paths), "bytes": total, "cold_read": cold, "warm_read": warm,
            "zip_cold": z_cold, "zip_warm": z_warm, "zip_stored": z_stored, "zip_l1": z_l1,
            "size_l6": size, "size_store": size_store, "size_l1": size_l1,
            "export_bundle": bundle, "ok": ok, "err": err}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3)
    args = ap.parse_args()
    tmp = tempfile.mkdtemp(prefix="probe_export_io_")
    rows = []
    try:
        for i in range(args.rounds):
            root = os.path.join(tmp, "r%d" % i)
            os.makedirs(root, exist_ok=True)
            r = one_round(root)
            if not r["ok"]:
                print("导出失败：%s" % r["err"])
                return 1
            rows.append(r)
            print("[run %d] %d 个文件 / %.0f KB：冷读 %.1f ms · 再读 %.1f ms · "
                  "冷写 zip %.1f ms · 温写 zip %.1f ms · export_bundle %.1f ms"
                  % (i + 1, r["files"], r["bytes"] / 1024.0, r["cold_read"], r["warm_read"],
                     r["zip_cold"], r["zip_warm"], r["export_bundle"]))

        def med(key):
            return statistics.median([r[key] for r in rows])

        print("\n== 中位（%d 轮）==" % len(rows))
        print("  首次读盘（冷）        %8.2f ms   ← 导出耗时的主体，且与压缩无关" % med("cold_read"))
        print("  再读一次（缓存命中）   %8.2f ms" % med("warm_read"))
        print("  写 zip（冷文件）      %8.2f ms" % med("zip_cold"))
        print("  写 zip（温文件）      %8.2f ms   ← 其中 deflate level6 ≈ %.1f ms"
              % (med("zip_warm"), med("zip_warm") - med("zip_stored")))
        print("  export_bundle 合计    %8.2f ms" % med("export_bundle"))
        print("\n== 换压缩级别能省多少（**会改变产出字节，本轮不采用**）==")
        print("  deflate level=6（现行为）%8.2f ms   包 %.2f KB"
              % (med("zip_warm"), med("size_l6") / 1024.0))
        print("  deflate level=1        %8.2f ms   包 %.2f KB"
              % (med("zip_l1"), med("size_l1") / 1024.0))
        print("  ZIP_STORED（不压缩）    %8.2f ms   包 %.2f KB"
              % (med("zip_stored"), med("size_store") / 1024.0))
        print("\n结论：PNG 本身已压缩，deflate 只省 %.2f%% 体积却占写盘 CPU 的大头；"
              % (100.0 * (1 - med("size_l6") / max(med("size_store"), 1e-9))))
        print("      但改压缩级别会改变包内字节，本轮硬性要求「产出格式不变」，故不动。")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
