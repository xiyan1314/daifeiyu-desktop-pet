# -*- coding: utf-8 -*-
"""v2.5.0 第 2 轮 D7-A（代理 C）三条改动的**定向变异验证**：把修复逐个拿掉，用例必须变红。

与 _dev/mutate_*.py 同一套设施（_mutate_lib：%TEMP% 影子副本里变异，真实仓库只读，
只写运行锁 _dev/.mutation.lock）。**不产出结果 JSON**——本文件只做一次性/可复跑的
"这条护栏是不是空转"验证，报告里贴它的输出即可（不新增会过期的指纹证据）。

用法：python _dev/verify_d7a_v250_agent_c.py
退出码：0 = 三条变异全部被检出；1 = 有逃逸（用例其实是恒绿的）。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _mutate_lib import last_line, run_pytest, shadow  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = ["tests/test_d7a_v250_agent_c.py"]

# (变异名, 文件, 原锚点, 替换) —— 锚点为**精确字符串**，匹配次数 != 1 就报 SKIP 让人同步
MUTATIONS = [
    ("M1 keep_source 补的那条日志被拿掉（回到纯静默）", "pet_resources.py",
     "                    _log_source_fail(rid, e)\n",
     "                    pass  # MUTATION：D7-A 补的日志被拿掉\n"),
    # v2.5.0 第 3 轮 L1 重锚：限流键由常量 "keep_source" 改成角色 id，锚点跟着换；
    # 判定口径不变（同一角色连记两次 → 新用例的"同角色限流"断言红）。
    ("M2 限流判断被拿掉（每失败都记一条）", "pet_resources.py",
     "    if now - _SOURCE_FAIL_SEEN.get(key, 0.0) < _SOURCE_FAIL_GAP_S:",
     "    if False:  # MUTATION：限流窗口被拿掉"),
    ("M3 形参不进 bad（＝回到旧的遮蔽误报口径）", "_check_static.py",
     "            vals, defs, bad = _scope_bindings(node.body, _param_names(node.args))",
     "            vals, defs, bad = _scope_bindings(node.body)"),
    ("M4 diff 存储把未知键也带回去", "pet_config.py",
     "            if k in defaults and v != defaults[k]:",
     "            if k not in defaults or v != defaults.get(k):  # MUTATION"),
    ("M5 pet_fx 自测重新写死 money/86", "pet_fx.py",
     "    sets = frame_sets(ASSETS_FX)\n",
     "    sets = frame_sets(ASSETS_FX)\n    sets[\"money\"] = 86  # MUTATION\n"),
    ("M6 README 的 config.json 口径说明被删", "README.md",
     "这是**有意为之**，不是缺陷：",
     "这是副作用："),
]


def _read(tree, rel):
    with io.open(os.path.join(tree, rel), encoding="utf-8") as fp:
        return fp.read()


def _write(tree, rel, text):
    with io.open(os.path.join(tree, rel), "w", encoding="utf-8") as fp:
        fp.write(text)


def main():
    escaped = 0
    with shadow(root=ROOT, what="verify_d7a_v250_agent_c") as tree:
        rc, failed, out = run_pytest(tree, TESTS)
        print("基线：rc=%d failed=%r  %s" % (rc, failed, last_line(out)))
        if rc != 0:
            print("基线不绿（影子副本里这条用例本来就红）→ 下面的判定没有意义")
            return 1
        for name, rel, old, new in MUTATIONS:
            orig = _read(tree, rel)
            n = orig.count(old)
            if n != 1:
                print("  [SKIP] %s —— 锚点匹配 %d 次（源码改过了，需同步本脚本）" % (name, n))
                escaped += 1
                continue
            try:
                _write(tree, rel, orig.replace(old, new, 1))
                rc2, failed2, out2 = run_pytest(tree, TESTS)
            finally:
                _write(tree, rel, orig)
            if rc2 != 0 and failed2:
                print("  [检出] %s → rc=%d 红：%s" % (name, rc2, "、".join(failed2[:3])))
            else:
                print("  [逃逸] %s → rc=%d failed=%r（用例没被这条变异触发）"
                      % (name, rc2, failed2))
                escaped += 1
    print("")
    print("D7-A 变异验证：%d/%d 检出" % (len(MUTATIONS) - escaped, len(MUTATIONS)))
    return 1 if escaped else 0


if __name__ == "__main__":
    sys.exit(main())
