# -*- coding: utf-8 -*-
"""导出耗时探针：量出 export_bundle 里每一段的**实测**占比（只读测量，不改产品代码）。

背景：交接里"export_bundle 125~205 ms"只有一个总数。按总数猜"是 zipfile 压缩慢"之前
得先量：滚动写盘 / manifest 构造 / zlib 压缩 / 自校验各占多少，否则可能优化错地方。

三段尺子：
  · 分段：把 export_bundle 的每一步单独计时（收集引用 / 构造 manifest / 写 zip / 自校验 /
    原子替换），并**逐条目**记 zip 写入耗时。
  · 对照：同一批条目用 zipfile 的其它压缩级别再写一遍（**只是量尺，不改产品默认**），
    用来回答"压缩到底占多少、降级别能省多少"。
  · 分片：产品侧的 write_bundle(plan, ...) 按条目切片（见 pet_export 的两段式 API），
    这里驱动它一次并统计"每片占主线程多久"。

用法：
    python _dev/probe_export_cost.py                  # 默认角色规模（48 个 256px PNG）
    python _dev/probe_export_cost.py --frames 60 --size 512
    python _dev/probe_export_cost.py --rounds 5 --json _dev/export_before.json

退出码：0 = 测量有效；1 = 导出失败（测量不成立）。
"""
import argparse
import json
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

import pet_export  # noqa: E402
import pet_resources  # noqa: E402


# ---------------- 计时 ----------------
class Clock:
    def __init__(self):
        self.seg = {}

    def add(self, name, ms, n=1):
        r = self.seg.setdefault(name, [0.0, 0.0, 0])
        r[0] += ms
        r[1] = max(r[1], ms)
        r[2] += n

    def timeit(self, name, fn):
        t0 = time.perf_counter()
        try:
            return fn()
        finally:
            self.add(name, (time.perf_counter() - t0) * 1000.0)


def _png(path, w, h, seed):
    """写一张有真实内容的 PNG（纯色图会被 zlib 压成几十字节，量不出压缩成本）。"""
    import random
    from PySide6.QtGui import QColor, QImage
    rnd = random.Random(seed)
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    for _ in range(1200):
        img.setPixelColor(rnd.randrange(w), rnd.randrange(h),
                          QColor(rnd.randrange(256), rnd.randrange(256),
                                 rnd.randrange(256), 255))
    img.save(path)


def make_role(root, frames=10, forms=2, size=256, use_real_assets=True):
    """造一个"多帧多形态"角色（真实的 PNG 解码/压缩成本）→ 返回 (RoleLibrary, cfg)。"""
    roles = os.path.join(root, "roles")
    os.makedirs(roles, exist_ok=True)
    src_dir = os.path.join(HERE, "assets")
    real = []
    if use_real_assets and os.path.isdir(src_dir):
        real = sorted(n for n in os.listdir(src_dir)
                      if n.startswith(("idle_f", "idle_full_f", "eat_f")) and n.endswith(".png"))
    names = []
    for i in range(frames):
        n = "probe_f%02d.png" % i
        dst = os.path.join(roles, n)
        if real:
            shutil.copyfile(os.path.join(src_dir, real[i % len(real)]), dst)
        else:
            _png(dst, size, size, 1000 + i)
        names.append(n)
    fms = []
    for k in range(forms):
        fms.append({"name": "形态%d" % (k + 1), "file": names[k % frames],
                    "front": names[(k + 1) % frames],
                    "animations": {"idle": list(names)},
                    "states": {"angry": names[k % frames], "blush": names[(k + 2) % frames]},
                    "anim_interval_ms": 100})
    role = {"id": "probe1", "name": "探针角色", "file": names[0],
            "form": ("dual" if forms == 2 else "single"),
            "file_full": names[1] if forms == 2 else "", "frames": list(names),
            "added": "", "forms": fms}
    with open(os.path.join(root, "roles.json"), "w", encoding="utf-8") as fp:
        json.dump({"roles": [role], "active": "probe1"}, fp, ensure_ascii=False)
    lib = pet_resources.RoleLibrary(root)
    return lib, {"role": "probe1"}


def run_once(root, clk, tag):
    lib, cfg = make_role(root)
    out = os.path.join(root, "out_%s.dfypet.zip" % tag)
    rid = cfg["role"]
    role = lib.get(rid)
    refs = pet_export._role_file_refs(role)
    clk.timeit("① 收集引用（_role_file_refs + resolve/isfile）",
               lambda: [(r, os.path.isfile(lib.resolve(r))) for r in refs])
    clk.timeit("② 构造 manifest",
               lambda: pet_export.build_manifest(role, [], cfg))
    t0 = time.perf_counter()
    ok, err = pet_export.export_bundle(lib, None, cfg, out)
    total = (time.perf_counter() - t0) * 1000.0
    clk.add("⑨ export_bundle 合计", total)
    if not ok:
        return None, total, err
    clk.timeit("⑧ 自校验（validate_bundle）", lambda: pet_export.validate_bundle(out))

    # 逐条目：单独重写一份同内容的 zip，量每个条目各占多久（含 zlib 压缩）
    def per_entry():
        tmp = out + ".perentry"
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for r in refs:
                p = lib.resolve(r)
                t = time.perf_counter()
                zf.write(p, "roles/" + os.path.basename(r))
                clk.add("④ zip: roles/*.png", (time.perf_counter() - t) * 1000.0)
                clk.add("④ zip: 单条目(roles)", (time.perf_counter() - t) * 1000.0)
        os.remove(tmp)
    clk.timeit("③ zip 写入合计（roles/*）", per_entry)
    sliced(root, clk)   # 分片写一遍（片数/单片最大耗时）

    # 对照尺（**不是产品路径**）：换压缩级别看看压缩占多少
    for lvl, name in ((0, "ZIP_STORED"), (1, "deflate level=1"), (6, "deflate level=6(默认)")):
        def write_with(lvl=lvl, name=name):
            tmp = out + ".lv"
            t0b = time.perf_counter()
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=lvl) as zf:
                for r in refs:
                    zf.write(lib.resolve(r), "roles/" + os.path.basename(r))
            dt = (time.perf_counter() - t0b) * 1000.0
            size = os.path.getsize(tmp)
            os.remove(tmp)
            clk.add("⑤ 对照: %s" % name, dt)
            clk.add("⑥ 对照体积: %s (KB)" % name, size / 1024.0)
        write_with()
    return out, total, ""


def sliced(root, clk):
    """分片写（两段式 API 的第二段）：plan → BundleWriter 逐片写。统计每片占主线程多久。"""
    if not hasattr(pet_export, "BundleWriter"):
        return None
    lib, cfg = make_role(root)
    out = os.path.join(root, "sliced.dfypet.zip")
    plan, err = pet_export.plan_bundle(lib, None, cfg)
    if plan is None:
        return None
    w = pet_export.BundleWriter(plan, out)
    steps = []
    guard = 0
    while not w.done and guard < 5000:
        guard += 1
        t0 = time.perf_counter()
        w.step(budget_ms=12.0)
        steps.append((time.perf_counter() - t0) * 1000.0)
    ok, _err = w.finish()
    return (out if ok else None), steps, {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--frames", type=int, default=10)
    ap.add_argument("--forms", type=int, default=2)
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="probe_export_")
    rows = []
    try:
        for i in range(args.rounds):
            root = os.path.join(tmp, "run%d" % i)
            os.makedirs(root, exist_ok=True)
            clk = Clock()
            out, total, err = run_once(root, clk, str(i))
            if out is None:
                print("导出失败：%s" % err)
                return 1
            n_entries = 0
            with zipfile.ZipFile(out) as zf:
                infos = zf.infolist()
                n_entries = len(infos)
                raw = sum(x.file_size for x in infos)
                comp = sum(x.compress_size for x in infos)
            sl = sliced(root, clk)
            rows.append({"run": i, "total_ms": round(total, 1), "entries": n_entries,
                         "raw_kb": round(raw / 1024.0, 1), "zip_kb": round(comp / 1024.0, 1),
                         "seg": {k: [round(v[0] / max(v[2], 1), 2), round(v[1], 2), v[2]]
                                 for k, v in clk.seg.items()},
                         "sliced": (None if sl is None else
                                    {"steps": len(sl[1]), "max_ms": round(max(sl[1]), 2),
                                     "sum_ms": round(sum(sl[1]), 2)})})
            print("[run %d] 导出合计 %6.1f ms | 条目 %d | 原始 %.2f MB → 包 %.2f MB%s"
                  % (i + 1, total, n_entries, raw / 1048576.0, comp / 1048576.0,
                     "" if sl is None else " | 分片 %d 片 / 单片最大 %.1f ms"
                     % (len(sl[1]), max(sl[1]))))

        print("\n== 分段耗时（中位 ms；按调用次数平均）==")
        keys = []
        for r in rows:
            for k in r["seg"]:
                if k not in keys:
                    keys.append(k)
        agg = []
        for k in keys:
            vals = [r["seg"][k][0] for r in rows if k in r["seg"]]
            mx = max(r["seg"][k][1] for r in rows if k in r["seg"])
            n = max(r["seg"][k][2] for r in rows if k in r["seg"])
            agg.append((statistics.median(vals), k, mx, n))
        agg.sort(reverse=True)
        for med, k, mx, n in agg:
            print("  %-34s 中位 %8.2f  单次最大 %7.2f  ×%d" % (k, med, mx, n))
        tot = statistics.median([r["total_ms"] for r in rows])
        print("  %-34s 中位 %8.2f" % ("[export_bundle 合计]", tot))

        if rows[0].get("sliced"):
            print("\n== 分片写（两段式 API）==")
            print("  片数 %d、单片最大 %.2f ms、合计 %.2f ms（对比一次性 %.2f ms）"
                  % (rows[0]["sliced"]["steps"], rows[0]["sliced"]["max_ms"],
                     rows[0]["sliced"]["sum_ms"], tot))

        if args.json:
            with open(args.json, "w", encoding="utf-8") as fp:
                json.dump({"rows": rows, "frames": args.frames}, fp, ensure_ascii=False, indent=1)
            print("JSON → %s" % args.json)
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
