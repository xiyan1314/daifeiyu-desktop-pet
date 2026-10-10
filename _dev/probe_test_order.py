# -*- coding: utf-8 -*-
"""反序探针（pytest 插件）：把某个用例文件挪到**收集顺序的最前或最后**，用来判定
"这些红是不是被别的模块污染"（模块级状态串味）——收集顺序一变就消失/出现的失败，
才叫污染；顺序无关的失败是**真失败**。

来历（2026-10-10 第三轮找茬）：有审查员在树里看到 test_export_slice_v242 的 3 条红，
第一反应是"测试污染"。实际是两个因素叠加：① assets/idle_f03.png 被外部脚本删掉
（工作树出现 D 条目）；② 变异脚本当时**原地覆写** pet_export.py。本探针把该用例挪到
最前/最后，结果一致 → 排除"收集顺序污染"这一解释。
（_mutate_lib.py 的 %TEMP% 影子副本就是这次事故的产物：变异不再碰真实仓库。）

用法（在仓库根跑；插件在 _dev/ 下，所以要把它加进 PYTHONPATH）：
    $env:PYTHONPATH = "_dev"
    $env:EXPORT_POS = "last"     # 或 "first"
    python -m pytest tests -o addopts="" -q -p probe_test_order

只挪 tests/test_export_slice_v242.py；要挪别的文件自己改 TARGET。
"""
import os

TARGET = "test_export_slice_v242"


def pytest_collection_modifyitems(session, config, items):
    pos = os.environ.get("EXPORT_POS", "last")
    mine = [i for i in items if TARGET in str(i.fspath)]
    rest = [i for i in items if TARGET not in str(i.fspath)]
    if pos == "first":
        items[:] = mine + rest
    else:
        items[:] = rest + mine
    print(chr(10) + "[reorder] %s items=%d pos=%s total=%d"
          % (TARGET, len(mine), pos, len(items)))
