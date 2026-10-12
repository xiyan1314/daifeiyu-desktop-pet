# -*- coding: utf-8 -*-
"""已迁移 —— 本脚本不再执行任何变异（v2.6.0 第 4 轮 / 找茬审查 B-5）。

原来的 12 条变异（8 条改产品代码 + 4 条改白名单数据）**在真仓里原地覆写**：
  · 被强杀会留下半变异的产品源码（_dev/_mutate_lib.py 的模块说明就是为这类事故写的）；
  · 不写 _dev/.mutation.lock → 它跑在 A/C 并行窗口里，别的进程会看到"来源不明的红"；
  · 原地改写 _dev/silent_except_whitelist_summary.json，中断会把白名单**截断**；
  · 判定只看 rc != 0，不查"红的是不是预期那条用例"（违反仓内 M5 的 expect_fail / WRONG TEST 口径）；
  · 没有结果 JSON → 全仓带指纹证据里没有它，**发布门看不见**。

现在它们已经迁成 _mutate_lib 的 spec 形态（影子副本 + 运行锁 + expect_fail 判定 +
结果 JSON 带 repo_fingerprint），并补上了本轮 P1/P2/P3 修复的 7 条：

    python -B _dev/mutate_check.py _dev/mutations_silent_except_v260.json

M-S1..M-S12 = 原来那 12 条；M-S13..M-S19 = 第 4 轮新修的（只收 https / 跨信任域 /
相对地址路径穿越 / file:// 折本机路径 / 金额格式化 / prompt 更新按指纹 / 本地包入口接线）。

这个文件**故意留着**（不是可以顺手删掉的残骸）：它挡住"照旧习惯敲 python -B
_dev/silent_except_mutate.py"的人——那条路现在会走到这里，而不是又去原地改真仓。
"""
import sys

MSG = ("_dev/silent_except_mutate.py 已停用（原地变异，见文件说明）。\n"
       "请改用：python -B _dev/mutate_check.py _dev/mutations_silent_except_v260.json\n")


def main():
    sys.stdout.write(MSG)
    return 2


if __name__ == "__main__":
    sys.exit(main())
