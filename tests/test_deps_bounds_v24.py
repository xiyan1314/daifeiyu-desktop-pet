# -*- coding: utf-8 -*-
"""v2.4（技术债 E）：requirements.txt 的 Pillow / psutil 必须有上界，且与 lock 相容。

为什么值得一条测试：这两个包都出过"上个新大版本就改 API/改支持范围"的历史
（Pillow 10 删 Image.ANTIALIAS、废 textsize；psutil 6/7 改动 Process 与内存接口），
而 psutil 还是**运行时**依赖——没上界时全新环境一次 pip install 就可能装到未验证的
下一个大版本，桌宠直接起不来。requirements-lock.txt 里的实测版本必须落在上界之内。
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEED_BOUNDS = ("Pillow", "psutil")


def _read(name):
    with open(os.path.join(ROOT, name), "r", encoding="utf-8") as f:
        return f.read()


def _specs(text):
    """requirements.txt -> {包名小写: [(op, 版本), ...]}（忽略注释与空行）。"""
    out = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or "==" not in line and ">" not in line and "<" not in line:
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)\s*(.*)$", line)
        if not m:
            continue
        name, rest = m.group(1), m.group(2)
        out[name.lower()] = re.findall(r"(==|>=|<=|>|<|~=)\s*([0-9][0-9A-Za-z.\-]*)", rest)
    return out


def _ver(text):
    return tuple(int(x) for x in re.findall(r"\d+", text)) or (0,)


def _satisfies(version, specs):
    v = _ver(version)
    for op, want in specs:
        w = _ver(want)
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


def test_pillow_and_psutil_have_upper_bounds():
    specs = _specs(_read("requirements.txt"))
    for name in NEED_BOUNDS:
        key = name.lower()
        assert key in specs, "requirements.txt 没有声明 %s" % name
        ops = [op for op, _w in specs[key]]
        assert "<" in ops, "%s 没有上界（全新环境可能装到未验证的大版本）：%r" % (name, specs[key])


def test_lock_versions_satisfy_requirements_bounds():
    specs = _specs(_read("requirements.txt"))
    lock = _read("requirements-lock.txt")
    checked = []
    for line in lock.splitlines():
        line = line.split("#", 1)[0].strip()
        m = re.match(r"^([A-Za-z0-9_.\-]+)==([0-9][0-9A-Za-z.\-]*)$", line)
        if not m:
            continue
        name, ver = m.group(1).lower(), m.group(2)
        if name not in specs:
            continue
        assert _satisfies(ver, specs[name]), \
            "lock 的 %s==%s 不满足 requirements.txt 的 %r" % (name, ver, specs[name])
        checked.append(name)
    for name in NEED_BOUNDS:
        assert name.lower() in checked, "lock 里没有 %s 的锁定版本，区间无从验证" % name


def test_bounds_check_can_fail():
    """控制组：区间判断必须真的能拒绝越界版本，否则上面两条是空转。"""
    specs = _specs(_read("requirements.txt"))
    assert not _satisfies("99.0.0", specs["pillow"]), "上界形同虚设"
    assert not _satisfies("0.1", specs["psutil"]), "下界形同虚设"
