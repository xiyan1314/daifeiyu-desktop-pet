# -*- coding: utf-8 -*-
r"""护栏"能真失败"自检（变异测试）：故意破坏被保护的行为，对应用例必须变红。

为什么要有这个：上一轮审查抓到过"恒真断言"——用例写得像护栏，实际怎么改都绿。
这里对 tests/test_guardrails_v24.py 的 8 条用例逐个做**定向变异**（只破坏它声称保护的那件事），
每条变异在**独立子进程**里跑（模块状态干净、互不串味），用例必须断言失败才算通过。

用法：python _dev/verify_guardrails_can_fail.py     退出码 0 = 8 条变异全部被抓
"""
import inspect
import os
import pathlib
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass  # 有意忽略：老解释器没有 reconfigure

import pet_chat  # noqa: E402
import pet_io  # noqa: E402
import pet_tools  # noqa: E402


# ---------------- 变体定义 ----------------
def _mut_readonly():
    """去掉写入工具的门控（把 4 条写工具标成 readonly）→ A1/A2 必须发现问题。"""
    for n in ("add_manual_record", "set_budget", "set_alarm", "set_timer"):
        pet_tools.TOOLS[n].readonly = True


def _mut_context_empty():
    """RAG 构建器整体退化（永远返回空串）→ A3 的"True 时要有字段"必须失败。"""
    import 桌宠 as main
    main.PetWindow._build_ai_context = lambda self, cfg: ""


def _mut_memory_overwrite():
    """回到旧的"整文件覆盖"口径（只写 history）→ A4 的 long_term 必须丢。"""
    def _old_write_memory(path, hist, max_entries, log=None, expect_epoch=None, epoch_of=None):
        pet_io.atomic_write_json(str(path), {"history": list(hist)[-max_entries:]}, indent=None)

    pet_chat.write_memory = _old_write_memory


def _shim(**over):
    """pet_tools 的代理模块：只覆盖指定常量，其余透传（制造"常量与实际行为不一致"）。"""
    base = pet_tools

    class _M(types.ModuleType):
        def __getattr__(self, k):
            return getattr(base, k)

    m = _M("pet_tools_shim")
    for k, v in over.items():
        setattr(m, k, v)
    return m


def _mut_calls_cap():
    """单轮上限实际放大（pet_chat 看到的常量是 99）→ A5 的"跳过"断言必须失败。"""
    pet_chat.pet_tools = _shim(MAX_CALLS_PER_ROUND=99)


def _mut_rounds_cap():
    """轮数上限实际放大（pet_chat 看到的常量是 9）→ A5 的请求次数断言必须失败。"""
    pet_chat.pet_tools = _shim(MAX_TOOL_ROUNDS=9)


def _mut_persona_ignored():
    """人设文件读取整体失效 → A6 的"文件优先"必须失败。"""
    import 桌宠 as main
    main._persona_file_text = lambda pid: None


def _mut_slot_blind():
    """静态检查的槽解析器失明（永远判不了）→ B7 必须失败（否则就是"恒绿"检查）。"""
    import _check_static as C
    C._slot_arity = lambda *a, **k: None


def _mut_write_blind():
    """静态检查的写盘识别失明 → B8 必须失败。"""
    import _check_static as C
    C._write_hit = lambda *a, **k: None


MUTATIONS = {
    "a1": ("test_a1_readonly_direct_and_write_gated", _mut_readonly, "写工具门控被摘掉"),
    "a2": ("test_a2_refused_writes_keep_ledger_budget_alarms", _mut_readonly, "写工具门控被摘掉"),
    "a3": ("test_a3_ai_context_privacy_switch", _mut_context_empty, "RAG 构建器退化"),
    "a4": ("test_a4_memory_history_and_long_term_do_not_clobber", _mut_memory_overwrite,
           "记忆写回旧口径（整文件覆盖）"),
    "a5c": ("test_a5_tool_rounds_and_calls_are_capped", _mut_calls_cap, "单轮上限实际放大"),
    "a5r": ("test_a5_tool_rounds_and_calls_are_capped", _mut_rounds_cap, "轮数上限实际放大"),
    "a6": ("test_a6_persona_file_overrides_builtin", _mut_persona_ignored, "人设文件读取失效"),
    "b7": ("test_b7_static_signal_arity_check", _mut_slot_blind, "信号参数解析失明"),
    "b8": ("test_b8_static_thread_write_check", _mut_write_blind, "线程写盘识别失明"),
}


class _MP(object):
    """最小 monkeypatch 替身（子进程里不需要回滚）。"""

    def setattr(self, obj, name, value, raising=True):
        setattr(obj, name, value)


def _child(case):
    import importlib
    test_name, mutate, desc = MUTATIONS[case]
    mutate()
    G = importlib.import_module("test_guardrails_v24")
    test = getattr(G, test_name)
    params = inspect.signature(test).parameters
    kwargs = {}
    if "tmp_path" in params:
        kwargs["tmp_path"] = pathlib.Path(tempfile.mkdtemp(prefix="dfy_mut_"))
    if "monkeypatch" in params:
        kwargs["monkeypatch"] = _MP()
    try:
        test(**kwargs)
    except AssertionError as e:
        lines = str(e).splitlines()
        print("CAUGHT   %-4s %-52s ← %s"
              % (case, test_name, lines[0][:70] if lines else "(空断言消息)"))
        return 0
    except Exception as e:                       # 变异引发的其它异常同样算"被抓住"
        print("CAUGHT*  %-4s %-52s ← %r" % (case, test_name, e))
        return 0
    print("SURVIVED %-4s %-52s ← 变异（%s）后用例仍然全绿" % (case, test_name, desc))
    return 1


def _driver():
    import subprocess
    bad = 0
    print("=== 变异测试：每条护栏被定向破坏后，对应用例必须变红 ===")
    for case in ("a1", "a2", "a3", "a4", "a5c", "a5r", "a6", "b7", "b8"):
        p = subprocess.run([sys.executable, os.path.abspath(__file__), case],
                           cwd=ROOT, capture_output=True, timeout=300,
                           env={**os.environ, "QT_QPA_PLATFORM": "offscreen",
                                "PYTHONIOENCODING": "utf-8"})
        out = (p.stdout or b"").decode("utf-8", errors="replace").strip()
        err = (p.stderr or b"").decode("utf-8", errors="replace").strip().splitlines()
        print(out or ("NO OUTPUT rc=%d %s" % (p.returncode, err[-1] if err else "")))
        if p.returncode != 0:
            bad += 1
    print("")
    print("变异 %d 条，未被抓住 %d 条" % (len(MUTATIONS), bad))
    print("GUARDRAIL MUTATION %s" % ("ALL CAUGHT" if bad == 0 else "HAS SURVIVORS"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(_child(sys.argv[1]) if len(sys.argv) > 1 else _driver())
