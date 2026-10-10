# -*- coding: utf-8 -*-
"""变异验证：把修复拿掉，对应的新测试必须变红（"能真失败"的证据）。

用法: python _dev/mutate_check.py <spec.json>

spec.json 结构：
  {"mutations": [
     {"id": "M-Q1", "why": "一句话说明这行代码在守什么",
      "file": "pet_alarm.py", "old": "源码里唯一的字面量片段", "new": "替换成什么",
      "tests": ["tests/test_x.py::test_y", ...],
      "expect_fail": ["tests/test_x.py::test_y", ...]}]}   # 可选，见下

v2.4.3（质量审查 M5）判定收紧：此前只要 rc != 0 就算 CAUGHT——别的用例被负载抖红也算
"这条变异被抓住了"。现在要求**预期用例真的出现在失败列表里**：
  · expect_fail 给了 → 它点名的用例必须**全部**在 failed 里；
  · 没给 → m["tests"] 里**至少一条**必须在 failed 里（默认口径）；
  · rc != 0 但没有预期用例 → 判定 WRONG TEST（不算抓到，同样计入未抓到）。
results 里同时存下这一轮的 failed 列表，便于复核"红的是不是它"。

v2.4.2（第三轮找茬收口）两处收紧：
  ① 变异不再**原地覆写**产品源码——整仓复制到 %TEMP% 影子副本（见 _dev/_mutate_lib.py），
     变异与 pytest 全在影子里做，真实仓库只读（只写 _dev/.mutation.lock 供发布门提示）。
     旧做法在变异窗口里被别的进程跑全量门时会看到"来源不明的红"，本轮真发生过。
  ② 跑完把结果**回写进 spec.json 的 "results" 段**（时间戳 + 每条 ID/结果/rc/末行 +
     未抓到计数）——此前只有 spec 没有结果，"N/N 全抓到"这句结论无法复核（质量审查 M7）。

退出码：0=全部被抓到；1=有变异没被抓到（NOT CAUGHT）；2=脚本自身出错（基线/规格问题）。
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _mutate_lib import (last_line, repo_fingerprint, results_payload,  # noqa: E402
                       run_baseline, run_pytest, shadow)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


def _write(path, text):
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _short(nodeid):
    """用例 nodeid → 只留最后一段（run_pytest 的 FAILED 行也是这个口径）。"""
    return str(nodeid).split("::")[-1].split(" ")[0]


def judge(mutation, rc, failed):
    """(verdict, failed 列表) —— rc != 0 **且**预期用例真的红了才算 CAUGHT。

    v2.4.3（质量审查 M5）：只看 rc 会把"别的用例被负载抖红"记成 CAUGHT
    （test_startup_defer_v242 的 60ms 阈值在影子里会抖，_mutate_lib 自己都记过
    96.4/70.3/97.2ms）。没有这条，"N/N 全抓到"里混着假阳性也看不出来。
    """
    if rc == 0:
        return "NOT CAUGHT", list(failed)
    expect = [_short(t) for t in (mutation.get("expect_fail") or [])]
    if not expect:
        expect = [_short(t) for t in mutation.get("tests") or []]
        hit = [e for e in expect if e in failed]
        if hit:
            return "CAUGHT", list(failed)
    else:
        miss = [e for e in expect if e not in failed]
        if not miss:
            return "CAUGHT", list(failed)
    return "WRONG TEST", list(failed)


def _write_results(spec_path, title, results, extra):
    """把本轮结果写回 spec.json 的 "results" 段（不影响 mutations 段）。"""
    try:
        spec = json.loads(_read(spec_path))
        spec["results"] = results_payload(title, results, extra)
        _write(spec_path, json.dumps(spec, ensure_ascii=False, indent=2) + chr(10))
        print("结果已回写到 %s 的 results 段" % os.path.basename(spec_path))
    except Exception as e:
        print("[结果回写] 失败（不影响本轮判定）：%r" % (e,))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    spec_path = sys.argv[1]
    if not os.path.isabs(spec_path):
        spec_path = os.path.join(ROOT, spec_path)
    if not os.path.isfile(spec_path):
        print("spec 不存在：%s" % spec_path)
        return 2
    spec = json.loads(_read(spec_path))
    muts = spec["mutations"]
    baseline = sorted({t for m in muts for t in m["tests"]})
    results = []
    bad = 0
    with shadow(what="mutate_check:" + os.path.basename(spec_path)) as tree:
        ok, rc, failed, out, note = run_baseline(tree, baseline)
        if not ok:
            print("基线就跑不过（影子副本，已重跑一次）：%r" % (failed[:5],))
            print(last_line(out))
            return 2
        print("基线：%d 条用例全过（影子副本 %s）%s" % (len(baseline), tree, note))
        for m in muts:
            path = os.path.join(tree, m["file"])
            orig = _read(path)
            n = orig.count(m["old"])
            if n != 1:
                print("[%s] 替换片段命中 %d 次（要求恰好 1 次）→ 脚本判据失效" % (m["id"], n))
                results.append((m["id"], "SPEC-BAD", 0, "锚点匹配 %d 次" % n, []))
                bad += 1
                continue
            try:
                _write(path, orig.replace(m["old"], m["new"]))
                rc, failed, out = run_pytest(tree, m["tests"])
            finally:
                _write(path, orig)
            verdict, failed = judge(m, rc, failed)
            results.append((m["id"], verdict, rc, last_line(out), failed))
            if verdict != "CAUGHT":
                bad += 1
                print(out[-3000:])
    print(chr(10) + "%-10s %-11s %-4s %s" % ("ID", "结果", "rc", "末行"))
    for mid, st, rc, tail, failed in results:
        print("%-10s %-11s %-4s %s%s" % (mid, st, rc, tail,
                                         ("  [红的是 %s]" % ",".join(failed[:3])) if failed else ""))
    print(chr(10) + "%d 条变异，%d 条未被抓到（判定口径：预期用例必须真的在失败列表里）"
          % (len(results), bad))
    _write_results(spec_path, "变异验证 spec：%s" % os.path.basename(spec_path), results,
                   {"spec": os.path.basename(spec_path), "tests": baseline,
                    "note": "变异只在 %TEMP% 影子副本里做，真实仓库只读（只写 _dev/.mutation.lock）",
                    "repo_fingerprint": repo_fingerprint(ROOT)})
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
