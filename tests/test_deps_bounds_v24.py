# -*- coding: utf-8 -*-
"""v2.4（技术债 E）+ v2.4.3（兼容审查 M3）：依赖区间口径。

为什么值得一条测试：这些包都出过"上个新大版本就改 API / 改支持范围"的历史
（Pillow 10 删 Image.ANTIALIAS、废 textsize；psutil 6/7 改 Process 与内存接口；
requests 3.x 会动 Session/json/异常层级；PyInstaller 7.x 改 spec 与分析器行为；
pytest 9 → 10 可能改收集/断言行为），而 psutil / requests / PySide6 还是**运行时**依赖——
没上界时全新环境一次 pip install 就可能装到未验证的下一个大版本，桌宠直接起不来。

v2.4.3（兼容审查 M3）口径收敛：包名清单不再写在这里，也不写在 test_round3_a_fixes.py 里
——"每个声明的包都必须有上界"由 tests/helpers_deps_bounds.py 一条规则统一守（此前漏了
pytest：两个文件的清单都没有它）。
"""
import pytest

from helpers_deps_bounds import (LOCK_NAME, REQ_NAME, lock_specs, locked_version,
                                  packages_without_upper_bound, requirements_specs,
                                  satisfies, specs)


def test_every_declared_package_has_an_upper_bound():
    """requirements.txt 里**每一个**包都要有 `<` 上界（清单 = 文件本身，不手写）。

    能真失败：把 `pytest>=7.0,<10` 改回 `pytest>=7.0`（或新增一个没写上界的依赖）
    → missing 里立刻出现它 → 红。
    """
    sp = requirements_specs()
    assert len(sp) >= 6, "requirements.txt 只解析出 %d 个包：%r" % (len(sp), sorted(sp))
    missing = packages_without_upper_bound(sp)
    assert missing == [], ("这些包没有上界（全新环境一次 pip install 就可能装到未验证的"
                           "大版本）：%r" % (missing,))


def test_lock_versions_satisfy_requirements_bounds():
    """requirements-lock.txt 里的实测版本必须落在 requirements.txt 的区间内。"""
    sp = requirements_specs()
    lock = lock_specs()
    checked = []
    for name in sorted(sp):
        ver = locked_version(lock, name)
        if not ver:
            continue
        assert satisfies(ver, sp[name]), \
            "lock 的 %s==%s 不满足 requirements.txt 的 %r" % (name, ver, sp[name])
        checked.append(name)
    # 覆盖率：声明的包绝大多数都在 lock 里锁了实测版本（锁不上的只有测试期工具）
    assert len(checked) >= 5, "lock 里只核对到 %d 个包：%r" % (len(checked), checked)
    for name in ("pillow", "psutil", "requests", "pyinstaller"):
        assert name in checked, "lock 里没有 %s 的锁定版本，区间无从验证" % name


def test_bounds_check_can_fail():
    """控制组：上界判据必须真的能拒——合成一份没写上界的 requirements，必须被点名。

    没有这条，"missing == []" 可能只是解析器什么都没解析出来的假绿。
    """
    bad = specs("foo>=1.0\nbar>=2.0,<3\nbaz\n")
    assert packages_without_upper_bound(bad) == ["foo"], bad
    good = specs("foo>=1.0,<2\n")
    assert packages_without_upper_bound(good) == []
    # 区间判断本身也要能拒
    assert not satisfies("99.0.0", specs("pillow>=9.0,<13")["pillow"]), "上界形同虚设"
    assert not satisfies("0.1", specs("psutil>=5.9,<8")["psutil"]), "下界形同虚设"
