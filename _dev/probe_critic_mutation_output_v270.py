# -*- coding: utf-8 -*-
"""v2.7.0 第 5 轮（本路）：变异**原文证据**——"这条用例红在哪一句断言上"。

为什么要有它：`mutate_check.py` 判定 CAUGHT 时**不打印**失败输出（只在未抓到/规格问题时贴尾部），
所以"N/N CAUGHT"这句话没有可复核的原文。本脚本吃**同一份 spec**
（`_dev/mutations_critic_v270.json`），逐条：

  ① 整仓复制到 %TEMP% 影子副本，改动只落在影子里（真实仓库只读，铁律 6；真仓只放运行锁
     `_dev/.mutation.lock/`，退出即删）；
  ② 先做锚点体检：spec 的 `old` 必须命中**恰好 1 次**（0 次/2 次都是"这条没被验证"）；
  ③ 跑该条点名的用例，打印 **pytest 失败断言原文**（以 "E " 开头的行）+ 失败用例名 + 末行；
  ④ 判定口径与 `mutate_check.py` 完全一致（预期用例必须真的出现在失败列表里）。

用法：python -B _dev/probe_critic_mutation_output_v270.py [--only M-R5-F1]
"""
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from _mutate_lib import failed_nodeids, last_line, run_pytest, shadow  # noqa: E402

ROOT = os.path.dirname(HERE)
SPEC = os.path.join(HERE, "mutations_critic_v270.json")


def _short(nodeid):
    last = str(nodeid).split("::")[-1].split(" ")[0]
    return last.split("[", 1)[0] if "[" in last else last


def _evidence_lines(out):
    """pytest 失败输出的**原文**：以 "E " 开头的断言行（去掉前缀，保留缩进）。"""
    return [ln[2:].rstrip() for ln in out.splitlines() if ln.startswith("E ")]


def main():
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
    spec = json.load(io.open(SPEC, encoding="utf-8"))
    muts = [m for m in spec["mutations"] if (only is None or m["id"] == only)]
    caught = 0
    for m in muts:
        with shadow(what="critic_probe:%s" % m["id"]) as tree:
            path = os.path.join(tree, m["file"])
            orig = io.open(path, encoding="utf-8").read()
            n = orig.count(m["old"])
            print("=" * 78)
            print("%s  ·  %s  ·  锚点命中 %d 次" % (m["id"], m["file"], n))
            print("  为什么：%s" % m["why"])
            if n != 1:
                print("  SPEC-BAD：锚点必须恰好命中 1 次 -> 这条没被验证")
                continue
            try:
                io.open(path, "w", encoding="utf-8").write(orig.replace(m["old"], m["new"]))
                rc, failed, out = run_pytest(tree, m["tests"])
            finally:
                io.open(path, "w", encoding="utf-8").write(orig)
            expect = [_short(t) for t in (m.get("expect_fail") or m.get("tests") or [])]
            hit = [e for e in expect if any(_short(f) == e for f in failed)]
            verdict = "CAUGHT" if (rc != 0 and len(hit) == len(expect)) else (
                "NOT CAUGHT" if rc == 0 else "WRONG TEST")
            if verdict == "CAUGHT":
                caught += 1
            print("  rc=%s  判定=%s  失败用例=%r" % (rc, verdict, [f for f in failed][:4]))
            print("  末行：%s" % last_line(out))
            ev = _evidence_lines(out)
            if not ev:
                print("  （没有以 'E ' 开头的断言原文；完整尾部见下）")
                print("\n".join(out.strip().splitlines()[-12:]))
            else:
                for ln in ev[:10]:
                    print("  原文| %s" % ln)
    print("=" * 78)
    print("共 %d 条，CAUGHT %d 条" % (len(muts), caught))
    return 0


if __name__ == "__main__":
    sys.exit(main())
