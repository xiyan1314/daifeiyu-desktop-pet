# -*- coding: utf-8 -*-
"""pinned nodeid 的**用例体 AST 摘要**（v2.11.0 第 9 轮 · 代理 C · 任务 V1）的回归。

背景（本轮实测的反例）：承载锚点的 39 个测试文件里只有 2 个在文件指纹清单内 ——
把 pinned 用例的**用例体清空（nodeid 不动）**时：`check_mutation_nodeids.py` 照样 rc=0
（def 还在）、文件指纹一声不吭（文件不在清单里）、那条变异 CAUGHT → NOT CAUGHT。
修法 = 证据里多记一段 `pinned_ast`（pinned nodeid → 用例体 AST 摘要），
由 `_dev/check_pinned_ast.py` 与当前树逐条比。

这里钉四件事：
  1. **用例体被改必须报**（清空 / 改断言 / 改装饰器 / 参数化标记）；
  2. **不该报的不报**（精度：注释 / 重排版 / docstring / 同文件里**别的**用例）——
     这是它比"整文件 sha256"值得存在的地方；
  3. 形态：参数化 nodeid、类方法（`TestX::test_y`）、只给文件的旧形态、用例被删；
  4. 真话：`mutate_check.spec_pinned_ast` 真的把它记进证据；工具自检 rc=0；
     当前语料里**每条变异**至少有一条可解析的 pinned nodeid（V1 的覆盖面本身）。
"""
import importlib.util
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEV = os.path.join(HERE, "_dev")


def _load(name, path):
    """按路径加载 _dev 下的脚本（它们不是包内模块，与 test_mutate_harness_v244 同法）。"""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mutate_lib = _load("mutate_lib_pinned_v2110", os.path.join(DEV, "_mutate_lib.py"))
mutate_check = _load("mutate_check_pinned_v2110", os.path.join(DEV, "mutate_check.py"))

DEMO = '''# -*- coding: utf-8 -*-
"""docstring 变了不算用例变了。"""


def test_pinned():
    assert 1 == 1


def test_other():
    assert 2 == 2
'''

PIN = "tests/test_demo.py::test_pinned"
OTHER = "tests/test_demo.py::test_other"
WHOLE = "tests/test_demo.py"
PINS = [PIN, OTHER, WHOLE]


def _make_repo(tmp_path, text=DEMO):
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "test_demo.py").write_text(text, encoding="utf-8")
    return mutate_lib.pinned_ast_map(str(tmp_path), PINS)


def _rewrite(tmp_path, text):
    (tmp_path / "tests" / "test_demo.py").write_text(text, encoding="utf-8")


def _stale(tmp_path, recorded):
    return mutate_lib.stale_pinned(recorded, mutate_lib.pinned_ast_map(str(tmp_path), PINS))


def test_clearing_the_pinned_body_is_detected(tmp_path):
    """本轮反例本身：nodeid 不动、用例体清空 → **必须**判过期。

    能真失败：把 pin_digest 改成恒返回同一个值（或 pinned_ast_map 恒返回 {}）→ 断言红。
    """
    rec = _make_repo(tmp_path)
    assert PIN in rec and WHOLE in rec, "用例前提：摘要得先算出来"
    _rewrite(tmp_path, DEMO.replace("    assert 1 == 1\n", "    pass\n"))
    got = _stale(tmp_path, rec)
    assert any(s.startswith(PIN + ": ") for s in got), \
        "用例体被清空却没人出声（nodeid 体检也会 rc=0 —— 这正是 V1 要堵的洞）：%r" % (got,)


def test_changing_an_assertion_is_detected(tmp_path):
    rec = _make_repo(tmp_path)
    _rewrite(tmp_path, DEMO.replace("    assert 1 == 1\n", "    assert 1 == 1 or True\n"))
    assert any(s.startswith(PIN + ": ") for s in _stale(tmp_path, rec)), \
        "断言被改弱（加了 or True）却没判过期"


def test_dropping_the_decorator_is_detected(tmp_path):
    """装饰器/形参变了也是实质变化（parametrize / skipif 换个写法，跑的就不是同一件事）。"""
    rec = _make_repo(tmp_path)
    _rewrite(tmp_path, DEMO.replace("def test_pinned():", "@staticmethod\ndef test_pinned():"))
    assert any(s.startswith(PIN + ": ") for s in _stale(tmp_path, rec)), \
        "装饰器变了却没判过期"


def test_unrelated_edit_in_the_same_file_is_not_reported(tmp_path):
    """**精度**：同文件里别的用例改了，pinned 那一条不该被算成过期（整文件哈希会误报）。

    能真失败：把 pin_digest 换成整文件 sha256 → 断言红。
    """
    rec = _make_repo(tmp_path)
    _rewrite(tmp_path, DEMO.replace("    assert 2 == 2\n", "    assert 3 == 3\n"))
    got = _stale(tmp_path, rec)
    assert not any(s.startswith(PIN + ": ") for s in got), \
        "同文件里**别的**用例改了，却把 pinned 用例也算成过期（这就是「整文件哈希」的噪音）：%r" % (got,)
    assert any(s.startswith(WHOLE + ": ") for s in got), \
        "整文件粒度的那个 pin 应当报（对照组，证明这一次改动真的发生了）：%r" % (got,)


def test_comment_and_reformat_are_not_reported(tmp_path):
    """注释 / 行尾注释 / 空行都不入 AST —— 重排版不该刷证据过期。"""
    rec = _make_repo(tmp_path)
    _rewrite(tmp_path, "# 新增注释\n\n" + DEMO.replace("    assert 1 == 1",
                                                       "    assert 1 == 1   # 行尾注释"))
    assert _stale(tmp_path, rec) == [], "只加注释就报过期（噪音）"


def test_docstring_change_is_not_reported(tmp_path):
    """docstring 是本仓用例的"变异说明"位，措辞变了不算用例变了。"""
    rec = _make_repo(tmp_path)
    _rewrite(tmp_path, DEMO.replace("docstring 变了不算用例变了", "换个说法"))
    assert _stale(tmp_path, rec) == [], "只改 docstring 就报过期（噪音）"


def test_whole_file_pin_reports_any_change_in_that_file(tmp_path):
    """只给文件的旧形态（export_slice / startup_defer 两份驱动）→ 整份模块粒度。"""
    rec = _make_repo(tmp_path)
    _rewrite(tmp_path, DEMO.replace("    assert 2 == 2\n", "    assert 4 == 4\n"))
    assert any(s.startswith(WHOLE + ": ") for s in _stale(tmp_path, rec)), \
        "整文件 pin 没覆盖到 test_other 的改动"


def test_a_deleted_pinned_case_cannot_be_digested(tmp_path):
    """用例被删/改名：当前树算不出摘要 → 不写键（那一段由 nodeid 体检 rc=1 点名）。"""
    _make_repo(tmp_path)
    _rewrite(tmp_path, DEMO.replace("\n\ndef test_pinned():\n    assert 1 == 1\n", "\n"))
    cur = mutate_lib.pinned_ast_map(str(tmp_path), PINS)
    assert PIN not in cur, "用例没了却还算得出摘要"
    assert OTHER in cur, "别的用例不该受影响"


def test_parameterized_and_class_nodeids_resolve_to_the_same_body(tmp_path):
    """`test_y[参数]` 与 `TestX::test_y` 都要能解析（判定那边就是这么写的）。"""
    src = ("# -*- coding: utf-8 -*-\nimport pytest\n\n\n"
           "@pytest.mark.parametrize(\"n\", [1, 2])\ndef test_param(n):\n    assert n\n\n\n"
           "class TestX:\n    def test_m(self):\n        assert True\n")
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "test_demo.py").write_text(src, encoding="utf-8")
    base = mutate_lib.pinned_ast_map(str(tmp_path), ["tests/test_demo.py::test_param"])
    par = mutate_lib.pinned_ast_map(str(tmp_path), ["tests/test_demo.py::test_param[1]"])
    cls = mutate_lib.pinned_ast_map(str(tmp_path), ["tests/test_demo.py::TestX::test_m"])
    assert base and par and cls, (base, par, cls)
    assert list(base.values()) == list(par.values()), "参数化实例与不带参数的 nodeid 应指同一段用例体"
    assert set(cls) == {"tests/test_demo.py::TestX::test_m"}


def test_stale_pinned_is_pure_and_ignores_missing_keys():
    """与 stale_fingerprints 同口径：空/None → []；只比两边都有的键；用例没了不在这里报。"""
    cur = {"a::t": "111111111111"}
    assert mutate_lib.stale_pinned(None, cur) == []
    assert mutate_lib.stale_pinned({}, cur) == []
    assert mutate_lib.stale_pinned(cur, cur) == []
    got = mutate_lib.stale_pinned({"a::t": "000000000000", "gone::t": "222222222222"}, cur)
    assert got == ["a::t: 000000000000→111111111111"], got


def test_spec_pinned_ast_writes_the_body_digests():
    """`mutate_check.spec_pinned_ast` 真的按 `mutations[].tests/expect_fail` 记摘要。"""
    spec = {"mutations": [{"id": "M-1", "file": "pet_x.py",
                           "tests": [PIN, OTHER], "expect_fail": [PIN]}]}
    got = mutate_check.spec_pinned_ast(spec, HERE)
    assert got == {}, "对真实仓根跑——这两个 nodeid 在仓里不存在，必须**不写键**"
    spec2 = {"mutations": [{"id": "M-2", "file": "pet_x.py",
                            "tests": ["tests/test_mutate_harness_v244.py::test_short_keeps_the_bare_name_and_entry_suffix_does_not_leak"],
                            "expect_fail": []}]}
    got2 = mutate_check.spec_pinned_ast(spec2, HERE)
    assert list(got2) == spec2["mutations"][0]["tests"], got2


def test_evidence_extra_records_the_pinned_digests(tmp_path):
    """**录进去**这一步本身：`mutate_check.evidence_extra` 里必须有非空的 pinned_ast。

    能真失败：把 evidence_extra 里 `pinned_ast` 那一行删掉（或改成 {}）→ 断言红。
    这条钉的是 V1 最容易被"改回去"的一步——摘要算得再对，没写进证据就是空转。
    """
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "test_demo.py").write_text(DEMO, encoding="utf-8")
    spec = {"mutations": [{"id": "M-1", "file": "pet_x.py",
                           "tests": [PIN, OTHER], "expect_fail": [PIN]}]}
    extra = mutate_check.evidence_extra(spec, "x.json", [PIN, OTHER], root=str(tmp_path))
    assert extra["repo_fingerprint"] is not None, "指纹那一段也不许丢"
    got = extra["pinned_ast"]
    # ⚠ 不拿 pinned_ast_map 跟自己做比较 —— 那在"解析器被改坏"的变异下两边都是 {}，
    # 断言照样绿（M-C2110-V1-02 第一遍就是这么判成 WRONG TEST 的）。这里钉**具体形态**：
    assert set(got) == {PIN, OTHER}, "证据里没记全 pinned 摘要：%r" % (got,)
    assert all(isinstance(v, str) and len(v) == 12 for v in got.values()), got
    assert got[PIN] != got[OTHER], "两条不同的用例体算出同一个摘要（摘要退化成常量）：%r" % (got,)
    # 端到端：用例体改了 → **证据里那个值**必须跟着变
    (tmp_path / "tests" / "test_demo.py").write_text(
        DEMO.replace("    assert 1 == 1\n", "    pass\n"), encoding="utf-8")
    extra2 = mutate_check.evidence_extra(spec, "x.json", [PIN], root=str(tmp_path))
    assert extra2["pinned_ast"][PIN] != got[PIN], \
        "用例体清空了，证据里记的摘要却没变（记了个常量）：%r" % (extra2["pinned_ast"],)


def test_run_check_flags_a_stale_evidence_file(tmp_path):
    """集成：一份带 pinned_ast 的证据 + 用例体被改 → §check_pinned_ast.run_check§ 必须点名并 rc=1。

    这条走的是 CLI 真正用的那条路（§_dev/*.json§ → recorded_pinned → 当前树比对），
    不是只测纯函数。
    """
    import json as _json
    checker = _load("check_pinned_ast_v2110", os.path.join(DEV, "check_pinned_ast.py"))
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_demo.py").write_text(DEMO, encoding="utf-8")
    (tmp_path / "_dev").mkdir()
    rec = mutate_lib.pinned_ast_map(str(tmp_path), [PIN])
    evidence = {"spec": "x.json",
                "mutations": [{"id": "M-X", "tests": [PIN], "expect_fail": [PIN]}],
                "results": {"pinned_ast": rec}}
    (tmp_path / "_dev" / "mutations_x.json").write_text(
        _json.dumps(evidence, ensure_ascii=False), encoding="utf-8")
    assert checker.run_check(str(tmp_path)) == 0, "什么都没改时不许报警"
    (tmp_path / "tests" / "test_demo.py").write_text(
        DEMO.replace("    assert 1 == 1\n", "    pass\n"), encoding="utf-8")
    assert checker.run_check(str(tmp_path)) == 1, "用例体被清空却没报警（V1 的全部意义就在这里）"


def test_tool_selftest_passes():
    """工具的"能真失败"自检（该报的报、不该报的不报）——没有它，扫描 0 条与工具坏了长得一样。"""
    p = subprocess.run([sys.executable, "-B", os.path.join(DEV, "check_pinned_ast.py"),
                        "--selftest"], cwd=HERE, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, timeout=300)
    out = p.stdout.decode("utf-8", "replace")
    assert p.returncode == 0, out[-1500:]
    assert "自检：通过" in out, out[-1500:]


def test_every_mutation_in_the_corpus_has_a_pinned_body_digest():
    """V1 的覆盖面本身：全库每条变异至少要有一条**能算出用例体摘要**的 pinned nodeid。

    能真失败：把 resolve_pin 对带 "::" 的 nodeid 直接 return None → 断言红（会点名是哪些变异）。
    ⚠ 这条不是在跑 pytest，是纯 AST 解析（秒级）。真新增了本工具不认识的 pinned 形态时，
    **先让 _mutate_lib.resolve_pin 认识它**，别把这条删掉了事。
    """
    import io
    import json
    bad = []
    total = 0
    for name in sorted(os.listdir(DEV)):
        if not (name.startswith("mutations_") and name.endswith(".json")):
            continue
        with io.open(os.path.join(DEV, name), encoding="utf-8") as fh:
            data = json.load(fh)
        muts = data.get("mutations") or []
        spec_files = {str(t).split("::")[0] if "::" in str(t) else str(t)
                      for m in muts for t in (m.get("tests") or [])}
        for m in muts:
            total += 1
            pins = [str(t) for k in ("tests", "expect_fail") for t in (m.get(k) or [])]
            if not any(mutate_lib.resolve_pin(p, spec_files, HERE) for p in pins):
                bad.append("%s::%s" % (name, m.get("id")))
    assert total > 300, "语料规模不对（找到 %d 条变异）——多半是收 spec 的路径写错了" % total
    assert not bad, "这些变异没有一条 pinned nodeid 能算出用例体摘要（V1 覆盖不到它们）：%r" % bad[:8]
