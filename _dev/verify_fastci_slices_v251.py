# -*- coding: utf-8 -*-
"""公开 CI 红门禁修复的验证（v2.5.2）：三条用例在**快机器**上仍然成立，且还有牙齿。

背景：tests/test_export_slice_v242.py::test_export_role_drives_the_writer_in_slices 与
tests/test_anim_slice_v241.py 的两条，判据原先依赖"真实解码/压缩耗时能撞破 12ms 预算"——
开发机（慢）全绿、windows-latest（快）上 CI #46~#50 连续五红。修法是注入"每单位固定变慢"
的 spy（每次取帧 5ms / 每次写条目 8ms）+ 把判据换成结构性计数。

本脚本在 %TEMP% 影子副本里跑四组实验（真实仓库只读，只写 _dev/.mutation.lock）：

  A  基线                     三条用例原样 → 必须全过
  B  读数                     影子里加一行 print（判据一字不改）→ 记下"每片几张/几片"
                              + 每次忙等的实测毫秒（看注入成本有没有被负载放大）
  C  快机器模拟（不该假红）     C1 把活变小（帧缩到 16px / 角色包帧缩到 8px：真解码≈0）
                              C2 预算 ×10 且单位成本 ×10（比值不变 = 同比例的另一台机器）
                              C4 只拿掉"慢"（注入失效）而保留 512px 重活 → 本机仍绿：
                                 正说明"靠真实耗时撞预算"的判据只能看机器脸色（CI 现场）
  C3 拿掉注入 + 活变小        = 复现 CI #50：**三条必须全红**（证明绿是注入在保，不是运气）
  D  牙齿（必须红）            D1 分片步忽略预算 / D2 进异步分支不再自损 /
                              D3 首片同步段忽略预算 / D4 UI 侧 budget_ms=None /
                              D5 BundleWriter.step 忽略 budget_ms

用法：python _dev/verify_fastci_slices_v251.py          结果 JSON 落在 _dev/ 下。
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _mutate_lib import last_line, repo_fingerprint, run_pytest, shadow  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 命名随仓里的 .gitignore 白名单（_dev/results_*.json 入库，其余 _dev/* 忽略）
RESULT_JSON = os.path.join(ROOT, "_dev", "results_fastci_slices_v251.json")

ANIM = "tests/test_anim_slice_v241.py"
EXPORT = "tests/test_export_slice_v242.py"
TOUCHED = [ANIM, EXPORT, "tests/helpers_roles.py", "桌宠.py", "pet_export.py"]
T_ANIM_M4 = ANIM + "::test_cold_big_frame_set_is_sliced_and_completes"
T_ANIM_M2 = ANIM + "::test_async_window_does_not_play_the_previous_roles_frames"
T_EXP_UI = EXPORT + "::test_export_role_drives_the_writer_in_slices"
ALL3 = [T_ANIM_M4, T_ANIM_M2, T_EXP_UI]

# ---- 读数插桩（只在影子里加；真实仓库的用例没有 print，判据一字不改）----
METRICS = [
    (ANIM, "    # (d) 不多起播：本批只该由 _anim_ready 起一次",
     "    print('METRICS m4 per_step=%r cap=%d sync_units=%d decodes=%d steps=%d spin=%s'\n"
     "          % (per_step, cap, sync_units, decodes['n'], len(per_step), _spin_summary()))\n"
     "    # (d) 不多起播：本批只该由 _anim_ready 起一次"),
    (ANIM, '        "异步批总共取了 %d 次帧，应当恰好 %d 次（每帧一次）" % (sum(per_step), len(paths)))',
     '        "异步批总共取了 %d 次帧，应当恰好 %d 次（每帧一次）" % (sum(per_step), len(paths)))'
     "\n    print('METRICS m2 per_step=%r cap=%d steps=%d spin=%s'"
     "\n          % (per_step, cap, len(per_step), _spin_summary()))"),
    (EXPORT, '    assert w.marks[-1] == w.total, "收尾时条目数对不上：%d/%d" % (w.marks[-1], w.total)',
     '    assert w.marks[-1] == w.total, "收尾时条目数对不上：%d/%d" % (w.marks[-1], w.total)'
     "\n    print('METRICS export steps=%d deltas=%r cap=%d total=%d spin=%s'"
     "\n          % (len(w.steps), deltas, cap, w.total, _spin_summary()))"),
    # 每次忙等的实测毫秒（看注入成本有没有被机器负载放大）
    (ANIM, "_SLOW_FRAME_MS = 5.0", "_SLOW_FRAME_MS = 5.0\n_SPIN_MS = []"
     "\n\n\ndef _spin_summary():\n"
     "    if not _SPIN_MS:\n        return '[]'\n"
     "    xs = sorted(_SPIN_MS)\n"
     "    return 'n=%d min=%.1f med=%.1f max=%.1f' % (len(xs), xs[0], xs[len(xs) // 2], xs[-1])"),
    (ANIM, "    t0 = time.perf_counter()\n    while (time.perf_counter() - t0) * 1000.0 < ms:\n        pass",
     "    t0 = time.perf_counter()\n    while (time.perf_counter() - t0) * 1000.0 < ms:\n        pass"
     "\n    _SPIN_MS.append((time.perf_counter() - t0) * 1000.0)"),
    (EXPORT, "_WRITER_UNIT_MS = 8.0", "_WRITER_UNIT_MS = 8.0\n_SPIN_MS = []"
     "\n\n\ndef _spin_summary():\n"
     "    if not _SPIN_MS:\n        return '[]'\n"
     "    xs = sorted(_SPIN_MS)\n"
     "    return 'n=%d min=%.1f med=%.1f max=%.1f' % (len(xs), xs[0], xs[len(xs) // 2], xs[-1])"),
    (EXPORT, "    import time\n    t0 = time.perf_counter()\n    while (time.perf_counter() - t0) * 1000.0 < ms:\n        pass",
     "    import time\n    t0 = time.perf_counter()\n    while (time.perf_counter() - t0) * 1000.0 < ms:\n        pass"
     "\n    _SPIN_MS.append((time.perf_counter() - t0) * 1000.0)"),
]

# ---- C1：把活变小（真解码/真压缩 ≈ 0，只剩注入成本）----
SHRINK = [
    ("tests/helpers_roles.py", "n=8, size=512, noise=True", "n=8, size=16, noise=True"),
    ("tests/helpers_roles.py", "def rewrite_big_frames(paths, size=512, seed=7",
     "def rewrite_big_frames(paths, size=16, seed=7"),
    (EXPORT, "n=16, size=256,", "n=16, size=8,"),
]

# ---- C2：预算与单位成本同比 ×10（比值不变）----
RATIO10 = [
    (ANIM, "_SLOW_FRAME_MS = 5.0", "_SLOW_FRAME_MS = 50.0"),
    (EXPORT, "_WRITER_UNIT_MS = 8.0", "_WRITER_UNIT_MS = 80.0"),
    ("桌宠.py", "_FRAME_SLICE_MS = 12.0", "_FRAME_SLICE_MS = 120.0"),
    ("桌宠.py", "_EXPORT_SLICE_MS = 12.0", "_EXPORT_SLICE_MS = 120.0"),
]

# ---- C3/C4：注入失效（_spin_ms 直接返回 = 拿掉 spy 的"慢"）----
NO_SPIN = [(ANIM, "    t0 = time.perf_counter()\n    while (time.perf_counter() - t0) * 1000.0 < ms:\n        pass",
            "    return"),
           (EXPORT, "    import time\n    t0 = time.perf_counter()\n    while (time.perf_counter() - t0) * 1000.0 < ms:\n        pass",
            "    return")]

# ---- D：牙齿（破坏产品逻辑，必须被抓）----
D1 = [("桌宠.py",
       "                if (time.perf_counter() - t0) * 1000.0 >= _FRAME_SLICE_MS:\n"
       "                    _rescheduled = True\n"
       '                    QTimer.singleShot(0, self, self._gslot("anim_chunk", self._anim_chunk_step))',
       "                if False:\n"
       "                    _rescheduled = True\n"
       '                    QTimer.singleShot(0, self, self._gslot("anim_chunk", self._anim_chunk_step))')]
D2 = [("桌宠.py", '            self.anim.add_set("idle", [])', "            pass")]
D3 = [("桌宠.py",
       "                    if (time.perf_counter() - t0) * 1000.0 >= _FRAME_SLICE_MS:\n"
       "                        done = False",
       "                    if False:\n"
       "                        done = False")]
D4 = [("桌宠.py", "w.step(budget_ms=_EXPORT_SLICE_MS)", "w.step(budget_ms=None)")]
D5 = [("pet_export.py",
       "if budget_ms is not None and (time.perf_counter() - t0) * 1000.0 >= budget_ms:",
       "if False:")]


def _read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def _write(p, t):
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(t)


def _digest(tree):
    return {rel: hashlib.sha256(_read(os.path.join(tree, rel)).encode("utf-8")).hexdigest()[:12]
            for rel in TOUCHED}


def apply_patches(tree, patches):
    """按 (文件, old, new) 打补丁 → 返回 {文件: 真原件}（**同一文件只记第一次**，见 revert）。"""
    originals = {}
    for rel, old, new in patches:
        p = os.path.join(tree, rel)
        orig = _read(p)
        n = orig.count(old)
        if n != 1:
            revert(tree, originals)
            raise AssertionError("锚点在 %s 命中 %d 次（要求 1）：%r" % (rel, n, old[:60]))
        originals.setdefault(rel, orig)     # 同一文件多补丁：只留真原件
        _write(p, orig.replace(old, new))
    return originals


def revert(tree, originals):
    """还原：**每个文件只写回一次真原件**。

    （第一版按补丁逐条还原，同一文件两个补丁时会把"打完第一个补丁的中间态"写回去——
    影子副本于是带着上一个实验的预算/尺寸跑下一个实验，读数全废。现在按文件去重。）
    """
    for rel, orig in (originals or {}).items():
        _write(os.path.join(tree, rel), orig)


def metrics(out):
    return [ln.strip() for ln in (out or "").splitlines() if ln.strip().startswith("METRICS")]


def brief(out, pat, n=4):
    return [ln.strip() for ln in (out or "").splitlines() if pat in ln][:n]


def run_variant(tree, name, patches, expect_green, expect_failed, results, manifest):
    originals = {}
    try:
        originals = apply_patches(tree, patches) if patches else {}
        rc, failed, out = run_pytest(tree, ALL3 + ["-s"])
    finally:
        revert(tree, originals)
    dirty = [k for k, v in _digest(tree).items() if manifest.get(k) != v]
    if dirty:                                # 影子被上一个实验污染：结果不可信，直接吵出来
        raise AssertionError("影子副本没还原干净：%r" % (dirty,))
    if expect_green is None:
        ok = True                                   # 观察组：结果本身就是要报的现象
    elif expect_green:
        ok = (rc == 0)
    else:
        want = {e.split("::")[-1] for e in expect_failed}
        got = {f.split("::")[-1].split("[")[0] for f in failed}
        ok = (rc != 0) and want.issubset(got)
    results.append({
        "id": name,
        "expect": "观察" if expect_green is None else ("GREEN" if expect_green else "RED"),
        "expect_failed": [] if expect_green else [e.split("::")[-1] for e in expect_failed],
        "rc": rc, "verdict": "OK" if ok else "MISMATCH",
        "failed": failed, "tail": last_line(out), "metrics": metrics(out),
        "asserts": brief(out, "AssertionError", 6),
    })
    print("[%-32s] rc=%d %s | failed=%s" % (name, rc, "OK" if ok else "**MISMATCH**", failed))
    for m in metrics(out):
        print("      " + m)
    if not ok:
        print(out[-2500:])
    return out


def main():
    print("影子副本里跑四组实验（真实仓库只读，只写 _dev/.mutation.lock）")
    results = []
    with shadow(what="verify_fastci_slices_v251") as tree:
        manifest = _digest(tree)
        run_variant(tree, "A 基线（原样）", [], True, [], results, manifest)
        d = apply_patches(tree, METRICS)         # 读数插桩：后面所有实验都带
        manifest = _digest(tree)                 # 插桩后的基准指纹（每个实验跑完必须回到这里）
        try:
            run_variant(tree, "B 读数（每片几张/几片）", [], True, [], results, manifest)
            run_variant(tree, "C1 快机器：活变小", SHRINK, True, [], results, manifest)
            run_variant(tree, "C2 预算与单位成本同比 ×10", RATIO10, True, [], results, manifest)
            # C4：只把注入改成空转（保留 512px 重活）——本机慢，三条里两条却已经红：
            # 同一条代码在不同机器上给出不同结论，正是 CI #50 那个病根，所以这一组只观察。
            run_variant(tree, "C4 只拿掉'慢'（保留 512px 重活）", NO_SPIN, None, [], results, manifest)
            out_c3 = run_variant(tree, "C3 拿掉注入+活变小（复现 CI #50）", NO_SPIN + SHRINK,
                                 False, ALL3, results, manifest)
        finally:
            revert(tree, d)
    bad = [r for r in results if r["verdict"] != "OK"]
    print("\n--- D 组（牙齿）---")
    with shadow(what="verify_fastci_slices_v251_teeth") as tree:
        d = apply_patches(tree, METRICS)
        manifest = _digest(tree)
        try:
            run_variant(tree, "D1 分片步忽略预算", D1, False, [T_ANIM_M4, T_ANIM_M2], results, manifest)
            run_variant(tree, "D2 进异步分支不再自损", D2, False, [T_ANIM_M2], results, manifest)
            run_variant(tree, "D3 首片同步段忽略预算", D3, False, [T_ANIM_M4, T_ANIM_M2], results, manifest)
            run_variant(tree, "D4 UI 侧 budget_ms=None", D4, False, [T_EXP_UI], results, manifest)
            run_variant(tree, "D5 step 忽略 budget_ms", D5, False, [T_EXP_UI], results, manifest)
        finally:
            revert(tree, d)
    bad = [r for r in results if r["verdict"] != "OK"]
    print("\n%-34s %-6s %-5s %-4s %s" % ("实验", "预期", "rc", "判定", "红了哪些"))
    for r in results:
        print("%-34s %-6s %-5d %-4s %s" % (r["id"], r["expect"], r["rc"], r["verdict"],
                                           ",".join(x.split("::")[-1] for x in r["failed"])))
    print("\n%d 组实验，%d 组与预期不符" % (len(results), len(bad)))
    print("\n--- C3（复现 CI #50）里的断言原文 ---")
    for ln in brief(out_c3, "AssertionError", 6):
        print("  " + ln)
    payload = {"title": "v2.5.2 分片判据去墙钟化：快机器不假红 + 牙齿", "results": results,
               "note": "变异/插桩只在 %TEMP% 影子副本里做，真实仓库只读（只写 _dev/.mutation.lock）",
               "repo_fingerprint": repo_fingerprint(ROOT)}
    with open(RESULT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write(chr(10))
    print("结果已写：%s" % os.path.relpath(RESULT_JSON, ROOT))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
