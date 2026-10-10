# -*- coding: utf-8 -*-
"""requirements 上界口径的**单一来源**（v2.4.3 · 兼容审查 M3）。

背景：此前"必须有上界的包名"在两个测试文件里各写一份清单
（test_deps_bounds_v24.py 的 NEED_BOUNDS 与 test_round3_a_fixes.py 的字面元组）——
新增依赖要改两处，漏一处就永远不会红：pytest 就是这么漏的（本文件里别的包都写了上界、
唯独 pytest 没有，而 CI 自己那条注释还写着"pytest 9.x → 10.x 会让 CI 毫无预兆地变红"）。

现在把"包名清单"这件事整个去掉：口径是
    **requirements.txt 里声明的每个包都必须有上界（`<`）**。
文件自己就是单一来源——新增依赖忘了写上界会直接变红，不必再去改测试。
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQ_NAME = "requirements.txt"
LOCK_NAME = "requirements-lock.txt"


def read(name):
    """读仓库根下的文本文件。"""
    with open(os.path.join(ROOT, name), "r", encoding="utf-8") as f:
        return f.read()


def specs(text):
    """requirements 文本 → {包名小写: [(op, 版本), ...]}（忽略注释与空行）。"""
    out = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or "==" not in line and ">" not in line and "<" not in line:
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)\s*(.*)$", line)
        if not m:
            continue
        out[m.group(1).lower()] = re.findall(r"(==|>=|<=|>|<|~=)\s*([0-9][0-9A-Za-z.\-]*)",
                                             m.group(2))
    return out


def parse_version(text):
    """版本串 → 数字元组（"6.22.2" → (6, 22, 2)）。"""
    return tuple(int(x) for x in re.findall(r"\d+", text)) or (0,)


def satisfies(version, spec_list):
    """version 是否满足 [(op, 版本), ...]（逐段比较，缺段补 0）。"""
    v = parse_version(version)
    for op, want in spec_list:
        w = parse_version(want)
        n = max(len(v), len(w))
        vv, ww = v + (0,) * (n - len(v)), w + (0,) * (n - len(w))
        if op == "==" and vv != ww:
            return False
        if op == ">=" and not vv >= ww:
            return False
        if op == ">" and not vv > ww:
            return False
        if op == "<=" and not vv <= ww:
            return False
        if op == "<" and not vv < ww:
            return False
    return True


def packages_without_upper_bound(specs_map):
    """没有 `<` 上界的包名（排序）。空列表 = 全部合规。"""
    return sorted(name for name, items in specs_map.items()
                  if "<" not in [op for op, _v in items])


def locked_version(specs_map, name):
    """lock 里 `==` 精确锁定的版本号；没有则空串。"""
    for op, ver in specs_map.get(name.lower(), []):
        if op == "==":
            return ver
    return ""


def requirements_text():
    return read(REQ_NAME)


def lock_text():
    return read(LOCK_NAME)


def requirements_specs():
    return specs(read(REQ_NAME))


def lock_specs():
    return specs(read(LOCK_NAME))
