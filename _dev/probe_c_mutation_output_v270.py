# -*- coding: utf-8 -*-
"""小账 a~d 的变异**原文证据**（v2.7.0 · 代理 C）。

为什么单独跑一遍：mutate_check.py 只在**没抓到**的时候才打印输出，抓到的时候只留一行
"CAUGHT / 红的是 xxx"。用户要求"不许假装修好"——每条修复要贴**实际输出原文**：
  ① 变异到底改了哪两行（old → new）；② 跑的确切命令；③ 失败断言的原文；④ 还原后是否绿。

本脚本在 %TEMP% 影子副本里逐条做同一件事（真仓只读），输出可直接贴进报告。
用法：python -B _dev/probe_c_mutation_output_v270.py
"""
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from _mutate_lib import last_line, run_pytest, shadow  # noqa: E402

SPEC = os.path.join(HERE, "mutations_plugin_c_v270.json")


def _excerpt(out, limit=14):
    """被变异触发的那段失败原文（pytest 的 E 行 / 断言上下文 / FAILED 行）。"""
    keep = []
    for ln in (out or "").splitlines():
        s = ln.strip()
        if s.startswith(("E ", "FAILED ")) or s.startswith("> "):
            keep.append(ln[:200])
    return keep[:limit]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass  # 有意忽略：老解释器没有 reconfigure
    with io.open(SPEC, encoding="utf-8") as fh:
        spec = json.load(fh)
    print("spec：_dev/mutations_plugin_c_v270.json（判定口径与判据实现 = _dev/mutate_check.py）")
    print("等价命令：python -B _dev/mutate_check.py _dev/mutations_plugin_c_v270.json")
    bad = 0
    with shadow(what="probe_c_mutation_output_v270") as tree:
        for m in spec["mutations"]:
            path = os.path.join(tree, m["file"])
            with io.open(path, encoding="utf-8") as fh:
                orig = fh.read()
            print("\n" + "=" * 78)
            print("[%s] %s" % (m["id"], m["why"]))
            print("  文件：%s" % m["file"])
            print("  被测用例：%s" % ", ".join(m["tests"]))
            for tag, text in (("变异前", m["old"]), ("变异后", m["new"])):
                for ln in (text.splitlines() or [""]):
                    print("    %s| %s" % (tag, ln))
            print("  锚点命中次数：%d（要求恰好 1）" % orig.count(m["old"]))
            try:
                with io.open(path, "w", encoding="utf-8") as fh:
                    fh.write(orig.replace(m["old"], m["new"]))
                rc, failed, out = run_pytest(tree, m["tests"])
            finally:
                with io.open(path, "w", encoding="utf-8") as fh:
                    fh.write(orig)
            print("  变异后：rc=%d  失败用例=%s" % (rc, failed or "(无)"))
            for ln in _excerpt(out):
                print("      %s" % ln)
            if not failed:
                print("      " + last_line(out))
                bad += 1
            rc2, failed2, _out2 = run_pytest(tree, m["tests"])
            print("  还原后：rc=%d  失败用例=%s  → %s"
                  % (rc2, failed2 or "(无)", "绿（护栏在变异拿掉后确实红、装回去确实绿）"
                     if rc2 == 0 else "仍然红（异常，需排查）"))
            if rc2 != 0:
                bad += 1
    print("\n%d 条变异：%d 条异常" % (len(spec["mutations"]), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
