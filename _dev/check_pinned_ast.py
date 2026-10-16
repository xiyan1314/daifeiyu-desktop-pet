# -*- coding: utf-8 -*-
"""pinned nodeid 的**用例体检**（v2.11.0 第 9 轮 · 代理 C · 任务 V1）——
`check_mutation_nodeids.py` 的下一层：那个只问"def 还在不在"，这个问"**用例体还是原来那一段吗**"。

**为什么要有它（本轮实测的反例）**：把 pinned 用例的**用例体清空、nodeid 一个字不动**时——
  · `check_mutation_nodeids.py` 照样 rc=0（def 还在）；
  · 文件指纹一声不吭（**承载锚点的 39 个测试文件里只有 2 个在指纹清单内**）；
  · 那条变异 CAUGHT → NOT CAUGHT（实测：`M-C2100-R4-01` 就是被这么造出来的）。
两道体检全静默，只有定版整批跑才会以 NOT CAUGHT 的形态暴露（而那时已经白烧一整批）。

**修法**：证据 JSON 里多记一段 `pinned_ast` = {pinned nodeid: 用例体 AST 摘要}
（`mutate_check.py` 在**真实仓库**上算好写进 `results`；两份旧形态 pytest 驱动各自补一条）。
本工具把"记录里的摘要"与"当前树上的摘要"逐条比：只要那条用例的**用例体**被改过
（清空 / 改断言 / 去装饰器 / 改形参…），摘要就变 → **这一条变异没被验证**。

**精度**（与"整文件 sha256"的区别，也是它存在的理由）：
注释 / 缩进 / 换行 / docstring 都不入摘要 → 重排版、改说明不报过期；
同文件里**别的**用例改动也不报（整文件哈希会把它们全算成过期 → 噪音淹没信号）。
**代价（如实写）**：同文件的 **fixture / 辅助函数**被掏空而用例体不动时，本工具不出声
（那是"整文件"粒度的事；本仓变异语料里目前没有这种形态）。

用法：
    python -B _dev/check_pinned_ast.py               # 查盘上证据（含 pinned_ast 的）vs 当前树
    python -B _dev/check_pinned_ast.py --probe       # 改前/改后：多少条变异**能被判过期**（只读）
    python -B _dev/check_pinned_ast.py --selftest    # 自检：临时树里动一下 pinned 用例体，必须报出来
    python -B _dev/check_pinned_ast.py --json out.json
退出码：0 = 没有过期（--probe/--selftest 通过）；1 = 有过期 / 自检失败；2 = 脚本自身出错。
"""
import argparse
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from _mutate_lib import (pinned_ast_map, repo_fingerprint, resolve_pin,  # noqa: E402
                         stale_pinned)


def _read_json(path):
    try:
        with io.open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def evidence_paths(root=None):
    dev = os.path.join(os.path.abspath(root or ROOT), "_dev")
    if not os.path.isdir(dev):
        return []
    return [os.path.join(dev, n) for n in sorted(os.listdir(dev)) if n.endswith(".json")]


def recorded_pinned(data):
    """两种落盘形态：结果 JSON 顶层 pinned_ast / spec 内嵌 results.pinned_ast。"""
    if not isinstance(data, dict):
        return None
    rec = data.get("pinned_ast")
    if not isinstance(rec, dict):
        res = data.get("results")
        rec = res.get("pinned_ast") if isinstance(res, dict) else None
    return rec if isinstance(rec, dict) else None


def recorded_fingerprint(data):
    """这份 JSON 的源码指纹段（结果 JSON 顶层 / spec 内嵌 results）——判"是不是证据文件"用。"""
    if not isinstance(data, dict):
        return None
    rec = data.get("repo_fingerprint")
    if not isinstance(rec, dict):
        res = data.get("results")
        rec = res.get("repo_fingerprint") if isinstance(res, dict) else None
    return rec if isinstance(rec, dict) else None


def mutation_ids_for(data, nodeids):
    """{nodeid: [变异 ID…]} —— 这份 spec 里点名了它的变异（旧形态结果 JSON 没有 mutations 段）。"""
    want = set(nodeids)
    out = {}
    for m in (data.get("mutations") or []):
        for key in ("tests", "expect_fail"):
            for raw in (m.get(key) or []):
                if str(raw) not in want:
                    continue
                ids = out.setdefault(str(raw), [])
                mid = m.get("id") or "?"
                if mid not in ids:      # 同一条变异可能 tests/expect_fail 都点了它：不重复列
                    ids.append(mid)
    return out


def spec_files_of(data):
    """这份证据**引用过的测试文件**（口径与写入端 mutate_check.spec_pinned_ast 逐字一致）。

    **为什么必须有它**（v2.11.0 定版实测出来的假红）：spec 里可以写**裸用例名**
    （不带 `文件::` 前缀，例如 _dev/mutations_agent_d_v280.json 的 expect_fail），
    而 _mutate_lib.resolve_pin() 解析裸名**必须知道"这份 spec 引用过哪些测试文件"**。
    写入端一直在传（所以 pinned_ast 段里键是裸名、值是算得出来的摘要），
    本工具此前**漏传** → 那两个裸名在检查时永远算不出摘要 → 被误记成"已消失"。
    **两条常驻假红会把将来真消失的用例淹没**，正是这个工具存在的意义被反噬。

    附注：check_mutation_nodeids.py 一直是接受裸名的 —— 同一份 spec 在那边过、在这边红，
    本来就是口径不一致；补上 spec_files 后两边一致。
    """
    muts = data.get("mutations") or []
    return {str(t).split("::")[0] if "::" in str(t) else str(t)
            for m in muts for t in (m.get("tests") or [])}


def run_check(root=None):
    """证据里记的 pinned 用例体摘要 vs 当前树 → 逐条点名。"""
    root = os.path.abspath(root or ROOT)
    rows = []
    total_pins = stale_n = gone_n = 0
    no_pinned = []
    for path in evidence_paths(root):
        data = _read_json(path)
        name = os.path.basename(path)
        rec = recorded_pinned(data)
        if not rec:
            # 只收"指纹通道里"的证据（有 repo_fingerprint 记录的那批）——与发布门
            # _check_release.mutation_evidence_notes() 的谓词**逐字一致**（两处数字必须一样）。
            # 不把 results_batch_v270.json（批次日志）、mutations_proc_reset_v26.json /
            # results_*_settle_v26.json（判据是 _verify_v13 的 FAIL 名，没有 pytest nodeid）
            # 算进来：对它们 pinned_ast 不适用。
            fp = recorded_fingerprint(data)
            if fp:
                no_pinned.append(name)
            continue
        # spec_files_of：解析裸用例名要用（见它的 docstring —— 漏传就是那两条假红的根因）
        cur = pinned_ast_map(root, list(rec.keys()), spec_files_of(data))
        stale = stale_pinned(rec, cur)
        gone = sorted(n for n in rec if n not in cur)
        total_pins += len(rec)
        stale_n += len(stale)
        gone_n += len(gone)
        ids = mutation_ids_for(data, [s.split(": ", 1)[0] for s in stale])
        rows.append((name, len(rec), stale, gone, ids))
    for name, n, stale, gone, ids in rows:
        bits = []
        for s in stale:
            node = s.split(": ", 1)[0]
            tag = "、".join(ids.get(node) or []) or "（旧形态：结果 JSON 里没有 mutations 段）"
            bits.append("%s ← %s" % (s, tag))
        if gone:
            bits.append("已消失/解析不了：%s" % "、".join(gone))
        print("%-42s pinned %3d 条，过期 %d 条%s" % (name, n, len(stale),
                                                    "" if not bits else "  → " + "；".join(bits)))
    print("")
    print("合计：%d 份证据带 pinned 摘要 / 记录 pinned nodeid %d 条；**过期 %d 条**、"
          "已消失 %d 条" % (len(rows), total_pins, stale_n, gone_n))
    if no_pinned:
        print("另有 %d 份证据**按设计不带 pinned_ast 段**（它们没有 repo_fingerprint 记录、"
              "判据是 _verify_v13 的 FAIL 名而不是 pytest nodeid —— 对它们 pinned_ast 不适用；"
              "它们仍受文件指纹保护）：%s%s"
              % (len(no_pinned), "、".join(no_pinned[:6]),
                 "…" if len(no_pinned) > 6 else ""))
    if not rows:
        print("（盘上还没有带 pinned_ast 的证据 —— 这是定版整批复跑之前的正常中间态，"
              "但**不许静默**：跑一次 mutate_check.py 就会带上）")
    if stale_n or gone_n:
        print("**这条证据没被验证**：pinned 用例体已变（或用例没了）——重跑对应 spec，"
              "别把它读成通过。")
    else:
        print("所有带 pinned 摘要的证据都还对着当前树（用例体逐条一致）。")
    return 1 if (stale_n or gone_n) else 0


def _split_specs(root):
    out = []
    for path in evidence_paths(root):
        data = _read_json(path)
        if isinstance(data, dict) and data.get("mutations"):
            out.append((os.path.basename(path), data))
    return out


def legacy_pytest_drivers():
    """两份旧形态 pytest 驱动（整文件粒度）：(脚本名, 测试文件, 变异条数)。"""
    import importlib.util
    out = []
    for name in ("mutate_export_slice.py", "mutate_startup_defer.py"):
        path = os.path.join(HERE, name)
        if not os.path.isfile(path):
            continue
        spec = importlib.util.spec_from_file_location("legacy_" + name[:-3], path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        out.append((name, getattr(mod, "TESTS", ""), len(getattr(mod, "MUTATIONS", []))))
    return out


def run_probe(root=None):
    """改前 / 改后：**多少条变异能被判过期**。

    改前 = 该变异至少有一条 pinned nodeid 落在**文件指纹清单**里（整文件 sha256 会计较它）；
    改后 = 至少有一条 pinned nodeid **能算出用例体 AST 摘要**（复跑后证据里自动带上）。
    """
    root = os.path.abspath(root or ROOT)
    fp = set(repo_fingerprint(root))
    specs = _split_specs(root)
    n_mut = before = after = 0
    no_after = []
    uniq = set()
    uniq_in = set()
    file_hits = {}
    for name, data in specs:
        muts = data["mutations"]
        spec_files = {str(t).split("::")[0] if "::" in str(t) else str(t)
                      for m in muts for t in (m.get("tests") or [])}
        for m in muts:
            n_mut += 1
            pins = [str(t) for k in ("tests", "expect_fail") for t in (m.get(k) or [])]
            res = [resolve_pin(p, spec_files, root) for p in pins]
            for p, r in zip(pins, res):
                if not r:
                    continue
                uniq.add(p)
                file_hits.setdefault(r[0], set()).add(p)
                if r[0] in fp:
                    uniq_in.add(p)
            if any(r and r[0] in fp for r in res):
                before += 1
            if any(res):
                after += 1
            else:
                no_after.append((name, m.get("id")))
    named_files = sorted(file_hits)
    out_files = [f for f in named_files if f not in fp]
    print("spec %d 份 / 变异 %d 条；点名的测试文件 %d 个（指纹清单内 %d / **清单外 %d**）"
          % (len(specs), n_mut, len(named_files), len(named_files) - len(out_files),
             len(out_files)))
    print("pinned nodeid %d 条（唯一）：指纹清单内 %d 条、**清单外 %d 条**"
          % (len(uniq), len(uniq_in), len(uniq) - len(uniq_in)))
    print("")
    print("改前（文件指纹能判过期）：      %3d / %d 条变异" % (before, n_mut))
    print("改后（pinned 用例体摘要能判过期）：%3d / %d 条变异" % (after, n_mut))
    if no_after:
        print("仍然判不了过期的 %d 条（点名一下，别让它静默）：%s"
              % (len(no_after), "、".join("%s::%s" % (s, i) for s, i in no_after[:8])))
    legacy = legacy_pytest_drivers()
    if legacy:
        print("")
        print("另：旧形态 pytest 驱动（钉**整文件**，改后同样能判过期）：%s"
              % "；".join("%s %d 条 → %s" % (n, k, t) for n, t, k in legacy))
    return 0


_SELFTEST_V1 = '''# -*- coding: utf-8 -*-
"""说明：docstring 变了不该算过期。"""


def test_pinned():
    assert 1 == 1


def test_other():
    assert 2 == 2
'''


def run_selftest():
    """自检（工具的"能真失败"）：临时树里动一下 pinned 用例体必须报出来；动别处不许报。"""
    node = "tests/test_demo.py::test_pinned"
    other = "tests/test_demo.py::test_other"
    whole = "tests/test_demo.py"
    bad = 0

    def _setup(tmp):
        os.makedirs(os.path.join(tmp, "tests"))
        with io.open(os.path.join(tmp, "tests", "test_demo.py"), "w",
                     encoding="utf-8", newline="") as fh:
            fh.write(_SELFTEST_V1)
        return pinned_ast_map(tmp, [node, other, whole])

    def _write(tmp, text):
        with io.open(os.path.join(tmp, "tests", "test_demo.py"), "w",
                     encoding="utf-8", newline="") as fh:
            fh.write(text)

    def _stale(tmp, rec, label, want, expect_hit=True):
        nonlocal bad
        got = stale_pinned(rec, pinned_ast_map(tmp, [node, other, whole]))
        hit = any(s.startswith(want + ": ") for s in got)
        ok = (hit == expect_hit)
        if not ok:
            bad += 1
        print("  [%s] %-38s 过期=%s（期望 %s）%s"
              % ("OK" if ok else "FAIL", label, [s.split(":")[0] for s in got],
                 "有 " + want if expect_hit else "没有 " + want,
                 "" if ok else "  ← 自检失败"))

    with tempfile.TemporaryDirectory(prefix="pinned_ast_selftest_") as tmp:
        rec = _setup(tmp)
        print("自检样本：%s" % ", ".join(sorted(rec)))
        # 1) 清空 pinned 用例体（nodeid 不动）→ 必须报
        _write(tmp, _SELFTEST_V1.replace("    assert 1 == 1\n", "    pass\n"))
        _stale(tmp, rec, "清空 pinned 用例体", node, True)
        # 2) 只动**别的**用例 → 不许报 pinned（精度）
        _write(tmp, _SELFTEST_V1.replace("    assert 2 == 2\n", "    assert 3 == 3\n"))
        _stale(tmp, rec, "只改同文件里别的用例", node, False)
        # 3) 只改注释 / 重排版 → 一律不报（AST 之外的东西）
        _write(tmp, "# 新增注释\n" + _SELFTEST_V1.replace("    assert 1 == 1",
                                                          "    assert 1 == 1   # 行尾注释"))
        _stale(tmp, rec, "只改注释/重排版", node, False)
        # 4) 只改 docstring → 不报
        _write(tmp, _SELFTEST_V1.replace("docstring 变了不该算过期", "措辞改一改"))
        _stale(tmp, rec, "只改 docstring", node, False)
        # 5) 改装饰器（用例签名变了）→ 要报
        _write(tmp, _SELFTEST_V1.replace("def test_pinned():", "@staticmethod\ndef test_pinned():"))
        _stale(tmp, rec, "改装饰器（用例签名变了）", node, True)
        # 6) 整文件粒度（旧形态驱动）：动任何一处都要报
        _write(tmp, _SELFTEST_V1.replace("    assert 2 == 2\n", "    assert 4 == 4\n"))
        _stale(tmp, rec, "整文件 pin：动 test_other", whole, True)
        # 7) 用例被删（nodeid 没了）→ 该键算不出来，点名在 gone 里
        _write(tmp, _SELFTEST_V1.replace("\n\ndef test_pinned():\n    assert 1 == 1\n", "\n"))
        cur = pinned_ast_map(tmp, [node, other, whole])
        ok = node not in cur
        if not ok:
            bad += 1
        print("  [%s] %-38s 当前树算不出它的摘要（nodeid 体检会报）"
              % ("OK" if ok else "FAIL", "pinned 用例被删"))
    print("")
    print("自检：%s" % ("通过（该报的都报了、不该报的没报）" if not bad else "**%d 项失败**" % bad))
    return 1 if bad else 0


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="pinned nodeid 用例体检（V1）")
    ap.add_argument("--probe", action="store_true", help="改前/改后覆盖数（只读）")
    ap.add_argument("--selftest", action="store_true", help="工具自身的能真失败自检")
    ap.add_argument("--json", metavar="OUT", help="把结论另存为 JSON")
    args = ap.parse_args()
    if args.selftest:
        rc = run_selftest()
    elif args.probe:
        rc = run_probe()
    else:
        rc = run_check()
    if args.json:
        with io.open(args.json, "w", encoding="utf-8", newline="") as fh:
            json.dump({"mode": "selftest" if args.selftest else ("probe" if args.probe else "check"),
                       "rc": rc}, fh, ensure_ascii=False, indent=2)
    return rc


if __name__ == "__main__":
    sys.exit(main())
