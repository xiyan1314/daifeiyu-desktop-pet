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
    names = [n for n in mutate_lib.failed_nodeids(out) if n.startswith("test_param_case")]
    assert names == ["test_param_case[2]"], \
        "从 pytest 输出里抽出来的失败名丢了参数化后缀：%r（原始输出：%r）" % (names, out[-400:])


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
