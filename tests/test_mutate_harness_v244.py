# -*- coding: utf-8 -*-
"""变异验证**驱动器自身**的回归（v2.4.4）：判定口径必须认得参数化用例。

背景（本轮实测）：pytest 的 FAILED 行里，参数化实例写作
test_undecodable_index_is_backed_up_before_first_write[behaviors.json-pet_behaviors-BehaviorService]，
而 spec 里写的是**不带参数**的节点名。判定函数此前只切 "::" 与空格、不剥 "[...]" →
"用例其实红了"被记成 WRONG TEST（_dev/mutations_compat_v242.json 的 M-C9 就是这么来的，
它的 failed 列表里明明躺着那条红的参数化实例）。

这里钉三件事：
  1. 真跑一个参数化用例，从 pytest 输出里抽出来的失败名**保留** "[...]"（_mutate_lib.failed_nodeids）；
  2. 判定按**基名**比对（_dev/mutate_check.judge）：spec 不写后缀 / 写全后缀都算 CAUGHT；
  3. 汇总口径自洽：caught + not_caught == total（WRONG TEST 也必须计入 not_caught）。

v2.11.0 第 9 轮（代理 C · 任务 V2/V3）再加两条口径：
  4. **V3**：比对**带文件路径** —— spec 写 `tests/test_a.py::test_x`、红的却是另一个文件里的
     同名用例 `tests/test_b.py::test_x`，不许再算命中（以前只比基名，独立验收造出过反例）；
  5. **V2**：ERROR 行只认 **setup/call 期**（teardown 期 error 的用例在 passed 里，用例体已经跑完）；
     相位解析不出来时**保留**（失败方向安全：绝不因为解析失败把检出丢掉）。
     参数化 nodeid 的相位解析由**真跑 pytest** 的用例钉住（`test_error_phases_...`）。
"""
import importlib.util
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEV = os.path.join(HERE, "_dev")


def _load(name, path):
    """按路径加载 _dev 下的脚本（它们不是包内模块，与 test_silent_except_audit_v241 同法）。"""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mutate_check = _load("mutate_check_v244", os.path.join(DEV, "mutate_check.py"))
mutate_lib = _load("mutate_lib_v244", os.path.join(DEV, "_mutate_lib.py"))

PARAM_ID = "behaviors.json-pet_behaviors-BehaviorService"
NODE = "tests/test_x.py::test_undecodable_index_is_backed_up_before_first_write"
BARE = "test_undecodable_index_is_backed_up_before_first_write"
FAILED_LINE = "FAILED " + NODE + "[" + PARAM_ID + "]"


# ---------- 1. 真跑一个参数化用例：抽出来的失败名必须保留参数化后缀 ----------

_PARAM_TEST = '''# -*- coding: utf-8 -*-
import pytest


@pytest.mark.parametrize("n", [1, 2])
def test_param_case(n):
    assert n == 1, "第二个参数实例故意红"
'''


def test_failed_nodeids_keeps_the_parameterized_suffix(tmp_path):
    """能真失败：把抽取改回"丢掉 [...]"（或改成 file::node 全名）→ 断言红。

    用**真的 pytest** 跑一个真参数化用例，而不是自己编一行 FAILED 文本：断言的正是
    "pytest 实际怎么写这行、我们怎么读这行"。
    """
    t = tmp_path / "test_param_demo.py"
    t.write_text(_PARAM_TEST, encoding="utf-8")
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run([sys.executable, "-m", "pytest", str(t), "-o", "addopts=", "-q",
                        "--no-header", "-p", "no:cacheprovider"],
                       cwd=str(tmp_path), stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, env=env, timeout=300)
    out = p.stdout.decode("utf-8", "replace")
    assert p.returncode == 1, out[-800:]
    names = [n for n in mutate_lib.failed_nodeids(out) if "::test_param_case" in n]
    assert len(names) == 1 and names[0].endswith("::test_param_case[2]"), \
        "从 pytest 输出里抽出来的失败名丢了参数化后缀：%r（原始输出：%r）" % (names, out[-400:])
    assert names[0].split("::")[0], \
        "文件前缀被丢了（V3 起判定要带文件路径比，丢了就又会跨文件顶替）：%r" % (names[0],)


# ---------- 2. 判定口径：spec 不写后缀也必须算 CAUGHT ----------

def test_judge_accepts_a_parameterized_failure_by_base_name():
    """M-C9 的口径 bug：spec 写不带参数的节点名，红的是它的参数化实例 → 必须 CAUGHT。

    能真失败：把 _short/judge 的比对改回精确相等 → 返回 WRONG TEST → 红。
    """
    m = {"tests": [NODE], "expect_fail": [NODE]}
    verdict, failed = mutate_check.judge(m, 1, [BARE + "[" + PARAM_ID + "]"])
    assert verdict == "CAUGHT", \
        "参数化实例红了却判成 %s（结果 JSON 里就是这条把 M-C9 记成 WRONG TEST 的）" % (verdict,)
    assert failed, "failed 列表要原样留着（证据里能看到红的是哪个参数实例）"


def test_judge_accepts_a_parameterized_failure_without_expect_fail():
    """默认口径（只给 tests）同样要认得参数化后缀——旧 spec 全是这种写法。"""
    m = {"tests": [NODE]}
    verdict, _failed = mutate_check.judge(m, 1, [BARE + "[" + PARAM_ID + "]"])
    assert verdict == "CAUGHT", verdict


def test_judge_still_rejects_a_failure_of_an_unrelated_test():
    """放宽的只是"同一条用例的参数化后缀"，不是"随便哪条红了都算"。

    能真失败：把比对改成"failed 非空即命中" → 返回 CAUGHT → 红（M5 收紧就是为这个）。
    """
    m = {"tests": [NODE], "expect_fail": [NODE]}
    verdict, _failed = mutate_check.judge(m, 1, ["test_some_other_thing[1]"])
    assert verdict == "WRONG TEST", verdict


def test_judge_treats_rc_zero_as_not_caught():
    m = {"tests": [NODE], "expect_fail": [NODE]}
    verdict, _failed = mutate_check.judge(m, 0, [])
    assert verdict == "NOT CAUGHT", verdict


def test_short_keeps_the_bare_name_and_entry_suffix_does_not_leak():
    """_short：剥 "::" 前缀、剥参数化后缀、剥 pytest 的 " - 说明" 尾巴。"""
    assert mutate_check._short(NODE) == BARE
    assert mutate_check._short(NODE + "[abc-1]") == BARE
    assert mutate_check._short(BARE + "[abc-1] - ValueError: boom") == BARE
    assert mutate_check._short("tests/test_x.py") == "tests/test_x.py"


# ---------- 3. 汇总口径自洽 ----------

def test_results_payload_counts_wrong_test_as_not_caught():
    """WRONG TEST 必须计入 not_caught，否则 caught + not_caught != total（实测 compat_v242：15/14/0）。

    能真失败：把 "WRONG TEST" 从 not_caught 的集合里去掉 → 第二、三条断言红。
    """
    results = [
        ("M-1", "CAUGHT", 1, "1 failed in 0.5s", ["test_a"]),
        ("M-2", "WRONG TEST", 1, "1 failed in 0.5s", ["test_b"]),
        ("M-3", "SPEC-BAD", 0, "锚点匹配 0 次", []),
    ]
    p = mutate_lib.results_payload("t", results)
    assert p["total"] == 3 and p["caught"] == 1, p
    assert p["not_caught"] == 2, "WRONG TEST 没被算进 not_caught：%r" % (p,)
    assert p["caught"] + p["not_caught"] + p["blocked"] == p["total"], \
        "汇总口径不自洽（caught+not_caught+blocked != total）：%r" % (p,)


def test_results_payload_has_no_stray_verdicts():
    """反过来：CAUGHT 不许被算进 not_caught（口径别矫枉过正）。"""
    p = mutate_lib.results_payload("t", [("M-1", "CAUGHT", 1, "1 failed", ["test_a"])])
    assert (p["caught"], p["not_caught"], p["blocked"]) == (1, 0, 0), p

# ---------- 4. 判定口径（v2.10.0 第 8 轮 · R5）：点名到用例的 ERROR 行也算检出 ----------
#
# 实测缺口（mutations_agent_a_v290.json 的 A11-M2）：把常驻标签整个拿掉 → 用例访问
# dlg._state_label 直接 AttributeError → pytest 记的是 ERROR 行（"2 errors"），FAILED 列表
# 是空的 → 旧口径判 WRONG TEST，而变异其实被检出了。
# 新口径：没通过的用例 = FAILED 行 + **点名到用例的** ERROR 行；
#          整文件收集期错误（ERROR tests/x.py - SyntaxError...，没有 ::）仍然不算检出。

_SETUP_ERR_TEST = '''# -*- coding: utf-8 -*-
import pytest


@pytest.fixture
def boom():
    raise AttributeError("no attribute _state_label")


def test_pinned_one(boom):
    assert True


def test_pinned_two(boom):
    assert True


def test_other():
    assert True
'''


def _run_pytest_on(tmp_path, name, text):
    t = tmp_path / name
    t.write_text(text, encoding="utf-8")
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run([sys.executable, "-m", "pytest", str(t), "-o", "addopts=", "-q",
                        "--no-header", "-p", "no:cacheprovider"],
                       cwd=str(tmp_path), stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, env=env, timeout=300)
    return p.returncode, p.stdout.decode("utf-8", "replace")


def test_errored_nodeids_reads_a_real_setup_error(tmp_path):
    """真跑一遍真 pytest：fixture 里抛异常时抽出来的用例名与相位。

    能真失败：把 errored_nodeids 改成"只认 FAILED 行"（返回 []）→ 第一条断言红；
    相位抽错（拿 ERRORS 段小标题当 FAILED 行解析）→ 第二条断言红。
    """
    rc, out = _run_pytest_on(tmp_path, "test_setup_err_demo.py", _SETUP_ERR_TEST)
    assert rc == 1, out[-800:]
    names = sorted(mutate_lib.errored_nodeids(out))
    short = sorted(n.split("::")[-1] for n in names)
    assert short == ["test_pinned_one", "test_pinned_two"], \
        "点名到用例的 ERROR 行没被抽出来（原始输出：%r）" % out[-500:]
    assert all("::" in n for n in names), \
        "ERROR 行的**文件前缀**被丢了（V3 起要带文件路径比）：%r" % (names,)
    assert mutate_lib.failed_nodeids(out) == [], "这个样本里没有 FAILED 行"
    phases = mutate_lib.test_error_phases(out)
    assert phases.get("test_pinned_one") == "setup", phases
    assert "test_other" not in short, "没出错的用例不该被算进来"


def test_errored_nodeids_ignores_a_whole_file_collection_error():
    """整文件收集期错误没有 "::" —— 那是"变异本身不合法"，不是用例检出。"""
    line = "ERROR tests/test_x.py - SyntaxError: invalid syntax"
    assert mutate_lib.test_error_lines(line) == []
    assert mutate_lib.errored_nodeids(line) == []


def test_judge_counts_a_setup_error_of_the_pinned_test_as_caught():
    """A11-M2 的口径缺口：pinned 用例在 setup 期抛异常 → 必须 CAUGHT。

    能真失败：judge 的 not_passed 退回只算 failed（旧口径）→ 返回 WRONG TEST → 红。
    """
    m = {"tests": [NODE], "expect_fail": [NODE]}
    verdict, failed = mutate_check.judge(m, 1, [], [BARE])
    assert verdict == "CAUGHT", \
        "pinned 用例 error 了却判成 %s（A11-M2 就是这么被记成 WRONG TEST 的）" % verdict
    assert failed == [], "failed 列表要如实保留（ERROR 行另存 errors，别混进来）"


def test_judge_still_rejects_an_error_of_an_unrelated_test():
    """新口径**没有**放宽成"只要有用例 error 就算抓到"——必须点到 pinned 的那条。

    能真失败：把匹配改成"errors 非空即命中" → 返回 CAUGHT → 红（这正是 M5 要挡的那类假阳性）。
    """
    m = {"tests": [NODE], "expect_fail": [NODE]}
    verdict, _failed = mutate_check.judge(m, 1, [], ["test_some_other_thing"])
    assert verdict == "WRONG TEST", verdict


def test_judge_requires_every_pinned_test_to_be_not_passed():
    """expect_fail 给两条时，一条 FAILED + 一条 ERROR 也够（两条都"没通过"）。"""
    m = {"tests": [NODE, "tests/test_x.py::test_second"], "expect_fail": [NODE,
                                                                        "tests/test_x.py::test_second"]}
    verdict, _ = mutate_check.judge(m, 1, [BARE], ["test_second"])
    assert verdict == "CAUGHT", verdict
    verdict2, _ = mutate_check.judge(m, 1, [], ["test_second"])
    assert verdict2 == "WRONG TEST", verdict2


def test_results_payload_records_the_error_lines():
    """error 行的原文必须落进 results（判定认它了，证据里就得看得见是哪几行）。"""
    row = ("M-1", "CAUGHT", 1, "2 errors in 1.32s", [],
           ["test_pinned_one", "test_pinned_two"])
    p = mutate_lib.results_payload("t", [row])
    assert p["items"][0]["errors"] == ["test_pinned_one", "test_pinned_two"], p["items"][0]
    assert p["caught"] == 1 and p["not_caught"] == 0, p


_LOG_ECHO_TEST = '''# -*- coding: utf-8 -*-
import logging


def test_pinned():
    assert True


def test_other():
    logging.error("boom see tests/test_x.py::test_pinned - noise")
    assert 1 == 2
'''


def test_errored_nodeids_ignores_a_captured_log_echo(tmp_path):
    """找茬审查 P2-1（v2.10.0）：pytest 会把**失败用例的 Captured log** 原样打印出来——
    那行也以 `ERROR ` 开头、也可能含 `::`。判据扫全文时，它会变成
    「另一条用例的日志里提到了 pinned 用例名」= 把 pinned 判成 error → **假 CAUGHT**（pinned 明明全过）。

    样本是**真跑真 pytest**造出来的（不是编一行文本）：失败用例的日志里写 pinned 的名字。
    能真失败：把 _mutate_lib.summary_lines 退回「整份输出」→ 第一条断言红。
    """
    rc, out = _run_pytest_on(tmp_path, "test_log_echo_demo.py", _LOG_ECHO_TEST)
    assert rc == 1, out[-800:]
    assert "ERROR " in out and "::" in out, \
        "样本没造出 Captured log 回声（这条用例会变成空转）：%r" % out[-500:]
    assert mutate_lib.errored_nodeids(out) == [], \
        "把失败用例日志里提到的用例名当成了 error（假 CAUGHT）：%r" % (mutate_lib.errored_nodeids(out),)
    failed = [n for n in mutate_lib.failed_nodeids(out) if n.endswith("::test_other")]
    assert len(failed) == 1, mutate_lib.failed_nodeids(out)
    m = {"tests": ["tests/test_x.py::test_pinned"], "expect_fail": ["tests/test_x.py::test_pinned"]}
    verdict, _ = mutate_check.judge(m, rc, mutate_lib.failed_nodeids(out),
                                    mutate_lib.errored_nodeids(out))
    assert verdict == "WRONG TEST", verdict


# ---------- 5. 判定口径（v2.11.0 第 9 轮 · V3）：带**文件路径**比对，不许跨文件顶替 ----------
#
# 独立验收造出的反例：spec 写 `tests/test_a.py::test_x`，红的却是另一个文件里的同名用例 ——
# 以前只比基名（_short），于是照样 CAUGHT。这道题**必须**由真 pytest 之外的纯函数用例钉住
# （真 pytest 很难在同一批里造两个同名文件，是测试组织问题，不是判据问题）。

def test_judge_rejects_a_same_named_failure_in_another_file():
    """同名不同文件 = **不是同一条用例** → WRONG TEST。

    能真失败：把 _failed_hit 退回"只比基名"（或 judge 里把 expect 先 _short 掉）→ 返回 CAUGHT。
    """
    m = {"tests": ["tests/test_a.py::test_x"], "expect_fail": ["tests/test_a.py::test_x"]}
    verdict, _ = mutate_check.judge(m, 1, ["tests/test_b.py::test_x"])
    assert verdict == "WRONG TEST", \
        "红的明明是**另一个文件**里的同名用例，却算成了这条变异被抓住（跨文件顶替）"


def test_judge_accepts_the_same_test_in_the_right_file():
    """对照组：同一文件（含参数化实例 / pytest 少一层 rootdir 前缀）仍然算命中。"""
    m = {"tests": ["tests/test_a.py::test_x"], "expect_fail": ["tests/test_a.py::test_x"]}
    assert mutate_check.judge(m, 1, ["tests/test_a.py::test_x[p1]"])[0] == "CAUGHT"
    assert mutate_check.judge(m, 1, ["repo/tests/test_a.py::test_x"])[0] == "CAUGHT", \
        "rootdir 前缀不同但尾部路径一致 → 同一条用例"
    assert mutate_check.judge(m, 1, ["test_x"])[0] == "CAUGHT", \
        "pytest 输出里没有文件前缀（离线样本/裸名）时退回按基名比——**只有这一种情况**才允许"


def test_judge_still_rejects_two_different_dirs_with_the_same_name():
    """尾部匹配不许放宽成"只要最后一段同名"：`a/test_x.py` 与 `b/test_x.py` 是两条用例。"""
    m = {"tests": ["a/test_x.py::test_x"], "expect_fail": ["a/test_x.py::test_x"]}
    assert mutate_check.judge(m, 1, ["b/test_x.py::test_x"])[0] == "WRONG TEST"


# ---------- 6. 判定口径（v2.11.0 第 9 轮 · V2）：ERROR 行只认 setup/call 期 ----------
#
# teardown 期 error 的汇总行是 "3 passed, 1 error" —— error 的那条用例**在 passed 里**
# （用例体已经跑完）。上一轮把这条写成"已知边界、真出现实例再收紧"，本轮兑现收紧；
# 失败方向必须安全：相位解析不出来 → 行为与旧口径逐字一致。

def test_judge_ignores_a_teardown_error_of_the_pinned_test():
    """pinned 用例**只是清理炸了** → 不算检出（WRONG TEST）。

    能真失败：judge 里不调 split_teardown_errors（errors 全收）→ 返回 CAUGHT。
    """
    m = {"tests": [NODE], "expect_fail": [NODE]}
    assert mutate_check.judge(m, 1, [], [BARE], {BARE: "teardown"})[0] == "WRONG TEST"
    assert mutate_check.judge(m, 1, [], [BARE], {BARE: "setup"})[0] == "CAUGHT", \
        "setup 期 error 仍然要算检出（A11-M2 的口径不许被 V2 连坐）"


def test_judge_keeps_an_error_when_the_phase_is_unknown():
    """相位查不出来（phases 空 / 输出被截断）→ **保留**检出，绝不因为解析失败丢掉它。"""
    m = {"tests": [NODE], "expect_fail": [NODE]}
    assert mutate_check.judge(m, 1, [], [BARE], {})[0] == "CAUGHT"
    assert mutate_check.judge(m, 1, [], [BARE], None)[0] == "CAUGHT", \
        "不传 phases（老调用方）必须是旧口径"


def test_judge_reads_the_phase_of_a_class_method_written_with_dots():
    """pytest 小标题里类方法是点号域名（`TestX.test_y`），摘要里的 nodeid 是 `TestX::test_y`。"""
    node = "tests/test_x.py::TestX::test_y"
    m = {"tests": [node], "expect_fail": [node]}
    assert mutate_check.judge(m, 1, [], [node], {"TestX.test_y": "setup"})[0] == "CAUGHT"
    assert mutate_check.judge(m, 1, [], [node], {"TestX.test_y": "teardown"})[0] == "WRONG TEST"


def test_split_teardown_errors_is_pure_and_fails_open():
    kept, dropped = mutate_lib.split_teardown_errors(
        ["a::t1", "a::t2", "a::t3"], {"t1": "setup", "t2": "teardown", "t3": "call"})
    assert kept == ["a::t1", "a::t3"] and dropped == ["a::t2"]
    assert mutate_lib.split_teardown_errors([], {}) == ([], [])
    assert mutate_lib.split_teardown_errors(["a::t"], {}) == (["a::t"], []), "相位未知要保留"


_PHASE_TEST = '''# -*- coding: utf-8 -*-
import pytest


@pytest.fixture
def boom_setup():
    raise AttributeError("setup boom")


@pytest.fixture
def boom_teardown():
    yield None
    raise AttributeError("teardown boom")


@pytest.mark.parametrize("n", [1, 2])
def test_param_setup_error(n, boom_setup):
    assert True


def test_plain_teardown_error(boom_teardown):
    assert True
'''


def test_error_phases_reads_a_real_parameterized_error_and_a_teardown_error(tmp_path):
    """V2 的前提：**参数化 nodeid 的相位解析必须可靠**（不可靠就得先补解析再用）。

    真跑一个 pytest：夹具在 setup 期炸（两个参数实例）+ 另一个用例的夹具在 teardown 期炸。
    钉四件事：① 参数化实例的相位键带 `[参数]` 且能对上；② teardown 期真被认成 teardown；
    ③ 判定只认前者；④ errored_nodeids 抽出来的是**整条 nodeid**（V3）。
    """
    rc, out = _run_pytest_on(tmp_path, "test_phase_demo.py", _PHASE_TEST)
    assert rc == 1, out[-800:]
    phases = mutate_lib.test_error_phases(out)
    assert phases.get("test_param_setup_error[1]") == "setup", phases
    assert phases.get("test_param_setup_error[2]") == "setup", \
        "参数化实例的相位没解出来（相位键与 errored_nodeids 对不上）：%r" % (phases,)
    assert phases.get("test_plain_teardown_error") == "teardown", phases
    errors = mutate_lib.errored_nodeids(out)
    assert len(errors) == 3 and all("::" in e for e in errors), errors
    kept, dropped = mutate_lib.split_teardown_errors(errors, phases)
    assert len(kept) == 2 and len(dropped) == 1, (kept, dropped)
    assert dropped[0].endswith("::test_plain_teardown_error"), dropped
    param = [e for e in errors if "test_param_setup_error" in e][0]
    plain = [e for e in errors if "test_plain_teardown_error" in e][0]
    assert mutate_check.judge({"tests": [param], "expect_fail": [param]},
                              rc, mutate_lib.failed_nodeids(out), errors, phases)[0] == "CAUGHT"
    assert mutate_check.judge({"tests": [plain], "expect_fail": [plain]},
                              rc, mutate_lib.failed_nodeids(out), errors, phases)[0] == "WRONG TEST", \
        "teardown 期炸的 pinned 用例被算成了检出（V2 要堵的就是这个）"

