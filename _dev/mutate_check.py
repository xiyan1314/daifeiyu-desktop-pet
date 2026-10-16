# -*- coding: utf-8 -*-
"""变异验证：把修复拿掉，对应的新测试必须变红（"能真失败"的证据）。

用法: python _dev/mutate_check.py <spec.json>

spec.json 结构：
  {"mutations": [
     {"id": "M-Q1", "why": "一句话说明这行代码在守什么",
      "file": "pet_alarm.py", "old": "源码里唯一的字面量片段", "new": "替换成什么",
      "tests": ["tests/test_x.py::test_y", ...],
      "expect_fail": ["tests/test_x.py::test_y", ...]}]}   # 可选，见下

v2.4.4（判定口径 bug）：比对按**基名**——pytest 的参数化实例写成 `test_x[参数]`，spec 里
通常只写不带参数的节点名；此前不剥后缀，用例真红了也被记成 WRONG TEST。

v2.4.3（质量审查 M5）判定收紧：此前只要 rc != 0 就算 CAUGHT——别的用例被负载抖红也算
"这条变异被抓住了"。现在要求**预期用例真的出现在失败列表里**：
  · expect_fail 给了 → 它点名的用例必须**全部**没通过；
  · 没给 → m["tests"] 里**至少一条**没通过（默认口径）；
  · rc != 0 但没有预期用例没通过 → 判定 WRONG TEST（不算抓到，同样计入未抓到）。
results 里同时存下这一轮的 failed 列表，便于复核"红的是不是它"。

v2.10.0 第 8 轮（代理 C · R5）判定再补齐一处口径缺口：**"没通过" = FAILED 行 + 点名到用例的
ERROR 行**（setup/call 期抛异常）。此前只看 FAILED 行，于是"把控件整个拿掉 → 用例访问它直接
AttributeError"这种检出被记成 WRONG TEST（实测 A11-M2：rc=1、2 errors、failed 为空）。
边界与理由写在 judge() 的 docstring 里；整文件收集期错误（ERROR tests/x.py - ... ，没有 ::）
仍然不算检出。ERROR 行原文也会存进 results 的 errors 字段，便于逐条复核。

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

from _mutate_lib import (errored_nodeids, last_line, pinned_ast_map,  # noqa: E402
                       repo_fingerprint, results_payload, run_baseline, run_pytest,
                       shadow, split_teardown_errors, test_error_phases)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


def _write(path, text):
    # v2.10.0（质量审查）：newline="" —— 文本模式在 Windows 上会把 LF 翻成 CRLF，
    # 于是"逐字节收编、纯 LF"的 spec 被工具回写一次就变成 325 个 CRLF（实测）。
    # 锚点比对走 universal newlines 不受影响，但**文件形态的账要能对得上**，所以显式关掉转换。
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _split(nodeid):
    """nodeid → (文件 or None, 用例基名)。

    v2.11.0 第 9 轮（代理 C · 任务 V3）：**文件部分要留着** —— 判定此前只按基名比，
    于是 spec 写 §tests/test_a.py::test_x§、红的却是**另一个文件**里的同名用例
    §tests/test_b.py::test_x§，也照样命中（**跨文件顶替**，独立验收造出过反例）。
    参数化后缀照旧剥掉（v2.4.4 的 M-C9：pytest 写
    §test_x[behaviors.json-pet_behaviors-BehaviorService]§，spec 里通常写不带参数的名字）。
    """
    raw = str(nodeid).split(" - ")[0].strip()      # 去 pytest 行尾的 " - 说明"
    raw = raw.split(" ", 1)[0]
    last = raw.split("::")[-1]
    base = last.split("[", 1)[0] if "[" in last else last
    rel = raw.split("::")[0].replace("\\", "/") if "::" in raw else None
    return rel, base


def _short(nodeid):
    """（保留旧名，给展示/旧用例用）用例基名 = _split(nodeid)[1]。"""
    return _split(nodeid)[1]


def _same_file(a, b):
    """两个 nodeid 里的文件是不是同一个：按**路径分量尾部**比。

    正常情况（pytest.ini 在仓根，spec 写 §tests/x.py§）就是逐字相等；尾部匹配是为了兜住
    "pytest 的 rootdir 不在仓根、nodeid 少了一层前缀"这种形态，同时**不**把
    §a/test_x.py§ 与 §b/test_x.py§ 当成同一个文件（分量个数必须对得上）。
    """
    if not a or not b:
        return False
    pa = [p for p in str(a).replace("\\", "/").split("/") if p]
    pb = [p for p in str(b).replace("\\", "/").split("/") if p]
    n = min(len(pa), len(pb))
    return pa[-n:] == pb[-n:]


def _failed_hit(expect, not_passed):
    """expect 是否命中这一轮**没通过**的用例：**带文件路径**比对（V3），参数化后缀照旧剥。

    v2.11.0 第 9 轮（代理 C · 任务 V3）：此前只比基名 —— expect 写
    §tests/test_a.py::test_x§、红的是 §tests/test_b.py::test_x§ 也照样命中。
    现在：spec 里写了文件，文件也必须对上；**只有** spec 写裸用例名（老 spec 形态）
    或 pytest 输出里没有文件前缀（离线样本）时才退回按基名比。
    已知边界（先写下来，不为想象中的情况加复杂度）：同一文件里**两个类**各有一个同名方法时
    仍会互相顶替（§file::A::test_y§ 与 §file::B::test_y§ 基名相同）。本仓 spec 实测
    **0 条**类前缀 nodeid（§check_pinned_ast.py --probe§ 同源统计）。
    """
    want_file, want_base = _split(expect)
    for f in not_passed:
        got_file, got_base = _split(f)
        if got_base != want_base:
            continue
        if want_file and got_file and not _same_file(want_file, got_file):
            continue
        return True
    return False


def judge(mutation, rc, failed, errors=None, phases=None):
    """(verdict, failed 列表) —— rc != 0 **且**预期用例真的没通过才算 CAUGHT。

    v2.4.3（质量审查 M5）：只看 rc 会把"别的用例被负载抖红"记成 CAUGHT
    （test_startup_defer_v242 的 60ms 阈值在影子里会抖，_mutate_lib 自己都记过
    96.4/70.3/97.2ms）。没有这条，"N/N 全抓到"里混着假阳性也看不出来。

    v2.10.0 第 8 轮（代理 C · R5）：**"没通过"要连 ERROR 行一起算**。
    实测（A11-M2，mutations_agent_a_v290.json）：把常驻标签整个拿掉 → 用例访问
    dlg._state_label 直接 AttributeError → pytest 记的是 **ERROR 行**（"2 errors"），
    FAILED 列表是空的 → 旧口径判 WRONG TEST，而**变异其实被检出了**。
      ① setup 期 error 的那条用例不在 passed 里（pytest 汇总行 "1 failed, 2 passed, 2 errors"）；
      ② 判据仍然要求"**点名的那条**用例没通过"：ERROR 行必须点到 expect_fail/tests 里的那条；
      ③ 整文件收集期错误（ERROR tests/x.py - SyntaxError...，**没有 :: **）**不算**：那是变异
         本身不合法（_mutate_lib.test_error_lines 的边界）；
      ④ 两份旧形态驱动一直在用 test_error_lines() 记 CAUGHT，这里是补口径一致性。

    v2.11.0 第 9 轮（代理 C · 任务 V2）：**收紧到 setup/call 期**。
    上一轮把"理由说到 setup/call 为止"写成了边界、把收紧留给"真出现实例时"——本轮兑现：
    **teardown 期 error 不算检出**。理由就是上轮自己写下的那条：teardown 期 error 的汇总行是
    "3 passed, 1 error"，**error 的那条用例在 passed 里**（用例体已经跑完），把它算检出等于
    "断言体全过、只有清理炸了"也记 CAUGHT。判定路径 = _mutate_lib.split_teardown_errors()。
    **失败方向是安全的**：相位解析不出来（输出被截断 / 小标题形态变了）时**一律保留** →
    行为与旧口径逐字一致，绝不因为解析失败把检出丢掉。参数化 nodeid 的相位键与
    errored_nodeids 同源（都是 pytest ERRORS 段小标题里的用例名，含 `[参数]`）——
    已有真 pytest 回归用例（tests/test_mutate_harness_v244.py）。

    v2.11.0（同轮 · 任务 V3）：比对**带文件路径**，不再按基名跨文件顶替，见 _failed_hit()。
    """
    failed = list(failed)
    if rc == 0:
        return "NOT CAUGHT", failed
    kept, _dropped = split_teardown_errors(errors, phases)   # ERROR 行里只留非 teardown 的
    not_passed = failed + kept
    # V3：**原始 nodeid**（带文件）交给 _failed_hit 比 —— 这里若先 _short() 就把文件丢了，
    # 跨文件顶替会再回来（第一版真这么错过，探针当场抓到）
    expect = [t for t in (mutation.get("expect_fail") or [])]
    if not expect:
        expect = [t for t in mutation.get("tests") or []]
        if any(_failed_hit(e, not_passed) for e in expect):
            return "CAUGHT", failed
    elif all(_failed_hit(e, not_passed) for e in expect):
        return "CAUGHT", failed
    return "WRONG TEST", failed


def spec_pinned_ast(spec, root=ROOT):
    """这份 spec 点名的**全部 pinned nodeid** → {nodeid: 用例体 AST 摘要}（V1）。

    范围与 nodeid 体检**逐字一致**（mutations[].tests / expect_fail；顶层 evidence.tests 与
    results 里那些历史记录不算）。算不出来的 nodeid **不写键** —— 那种由
    check_mutation_nodeids.py（rc=1）点名，两份工具各管一段。
    """
    muts = spec.get("mutations") or []
    nodeids = [t for m in muts for k in ("tests", "expect_fail") for t in (m.get(k) or [])]
    spec_files = {str(t).split("::")[0] if "::" in str(t) else str(t)
                  for m in muts for t in (m.get("tests") or [])}
    return pinned_ast_map(root, nodeids, spec_files)

def evidence_extra(spec, spec_name, baseline, root=ROOT):
    """回写进 spec 的 results 段：源码指纹 + **pinned nodeid 的用例体摘要**（V1）。

    单独成函数是为了让它**可被回归用例直接调**（V1 的价值全在"证据里真的记上了"这一步：
    记不上，整套摘要就是空转）。
    """
    return {"spec": spec_name, "tests": baseline,
            "note": "变异只在 %TEMP% 影子副本里做，真实仓库只读（只写 _dev/.mutation.lock）",
            "repo_fingerprint": repo_fingerprint(root),
            # V1：用例体被清空而 nodeid 不动时，只有这段摘要能出声
            # （逐条理由见 _dev/check_pinned_ast.py 的 docstring）
            "pinned_ast": spec_pinned_ast(spec, root)}


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
            errors = errored_nodeids(out)
            phases = test_error_phases(out)
            _kept, dropped = split_teardown_errors(errors, phases)   # V2：teardown 不算检出
            verdict, failed = judge(m, rc, failed, errors, phases)
            if dropped:
                print("[%s] 忽略 %d 条 teardown 期 error（用例体已经跑完，不算检出）：%s"
                      % (m["id"], len(dropped), "、".join(dropped[:3])))
            results.append((m["id"], verdict, rc, last_line(out), failed, errors, dropped))
            if verdict != "CAUGHT":
                bad += 1
                print(out[-3000:])
    print(chr(10) + "%-10s %-11s %-4s %s" % ("ID", "结果", "rc", "末行"))
    for row in results:
        mid, st, rc, tail, failed = row[:5]
        errors = list(row[5]) if len(row) > 5 and row[5] else []
        detail = ""
        if failed:
            detail = "  [红的是 %s]" % ",".join(failed[:3])
        elif errors:
            detail = "  [error 的是 %s]" % ",".join(errors[:3])
        print("%-10s %-11s %-4s %s%s" % (mid, st, rc, tail, detail))
    print(chr(10) + "%d 条变异，%d 条未被抓到（判定口径：预期用例必须真的没通过 —— "
                    "FAILED 行 + 点名到用例的 **setup/call 期** ERROR 行；"
                    "teardown 期不计，见 _dev/README.md）" % (len(results), bad))
    _write_results(spec_path, "变异验证 spec：%s" % os.path.basename(spec_path), results,
                   evidence_extra(spec, os.path.basename(spec_path), baseline))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
