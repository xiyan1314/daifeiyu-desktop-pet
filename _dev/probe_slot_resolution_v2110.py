# -*- coding: utf-8 -*-
"""M 检查「可解析槽比例」的**构造复核探针**（v2.11.0 第 9 轮 · 代理 C · P1 登记）。

**为什么要复核这条判据**：`tests/test_guardrails_v24.py` 里那条上界（原 0.90）按"实测更新到
0.93"被抬起过一次（已撤回）。抬上界这件事本身说明**这个形状有问题**：
比例 = 可解析候选 / 全部候选，而"可解析"取决于**树里出现了哪些写法**——显式接线（self._on_x、
模块级函数）天然可解析，Qt 内建/动态槽天然不可解析。**代码风格往显式走，比例就合法地涨**；
于是固定上界迟早假红。这个探针把两件事分开量：

  ① 当前树 vs HEAD 修订的比例（证明"涨"是代码增长/风格，不是解析器变了）；
  ② 逐条列出**判不了**的槽（人工核对：它们是不是真的判不了 —— 判不了就必须跳过，不许猜）。

用法：`python -B _dev/probe_slot_resolution_v2110.py [--head]`
退出码 0（只读测量，不作判定）。
"""
import ast
import io
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import _check_static as C  # noqa: E402


def _ratio(files, label):
    """跑一遍 check_signal_arity，**按实参记账**（不能拿 iter_slots 的结果去 zip —— 只有
    "信号名在本仓声明里"的候选才会走到 _slot_arity，两者数量不同、对齐会错位）。"""
    seen = []
    orig = C._slot_arity

    def _spy(slot, fname, funcs, methods, scopes=None, lineno=0):
        res = orig(slot, fname, funcs, methods, scopes, lineno)
        seen.append((res, fname, lineno, slot))
        return res

    C._slot_arity = _spy
    try:
        problems, notes = C.check_signal_arity(files)
    finally:
        C._slot_arity = orig
    ok = [r for r, _f, _l, _s in seen if r is not None]
    print("%-14s 候选 %3d，可解析 %3d（%.4f），判不了 %3d；check_signal_arity → 问题 %d / 待确认 %d"
          % (label, len(seen), len(ok), (len(ok) / float(len(seen))) if seen else 0.0,
             len(seen) - len(ok), len(problems), len(notes)))
    return seen


def _form(slot):
    """槽表达式 → 形态标签（人工核对用）。"""
    if isinstance(slot, ast.Lambda):
        return "内联 lambda"
    if isinstance(slot, ast.Name):
        return "裸名字"
    if isinstance(slot, ast.Attribute):
        inner = slot.value
        if isinstance(inner, ast.Name) and inner.id == "self":
            return "self.<方法>"
        if isinstance(inner, (ast.Attribute, ast.Call)):
            return "属性链/调用链"
        return "<对象>.<方法>"
    if isinstance(slot, ast.Call):
        f = slot.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        if name in C._GUARD_WRAPPERS:
            return "guard 包装"
        return "调用结果（dynamic）"
    if isinstance(slot, ast.Subscript):
        return "下标取值（dynamic）"
    return type(slot).__name__


def _head_files():
    """HEAD 修订的源码集合（与 C.sources() 同一份文件清单），不碰工作树。"""
    out = []
    for f in sorted(os.listdir(ROOT)):
        if not f.endswith(".py") or f in C.SKIP:
            continue
        p = subprocess.run(["git", "show", "HEAD:" + f], cwd=ROOT,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        if p.returncode == 0:
            out.append((f, p.stdout.decode("utf-8", "replace")))
    return out


def main():
    cur = C.sources()
    seen = _ratio(cur, "当前树")
    if "--head" in sys.argv:
        _ratio(_head_files(), "HEAD 修订")
    forms = {}
    for res, _f, _l, slot in seen:
        d = forms.setdefault(_form(slot), [0, 0])
        d[1] += 1
        if res is not None:
            d[0] += 1
    print("")
    print("—— 形态分布（可解析 / 共）——")
    for tag in sorted(forms, key=lambda t: -forms[t][1]):
        ok, total = forms[tag]
        print("  %-18s %3d / %3d" % (tag, ok, total))
    print("")
    print("—— 判不了的槽（逐条：形态 + 位置；它们**必须**被跳过，猜了就会误报）——")
    for res, fname, lineno, slot in seen:
        if res is None:
            print("  [跳过] %-18s %s:%d  %s" % (_form(slot), fname, lineno,
                                                 ast.unparse(slot)[:70]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
