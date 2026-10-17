# -*- coding: utf-8 -*-
"""发行拆分契约（v2.11.0 · 旧第 8 轮那批第 5 项）：把「什么算用户数据」这条线钉死。

**为什么这条判据就是本项的全部交付，而不是真去分包**：
方向 13（AI 视频管线）/ 15（屏幕观察）/ 19（Live2D）**今天一个都没实现**，所以本轮
不可能真的把"核心版 vs 可选包"拆开。但 plan §14.1 早就点出了这条路的前提 ——
**先把"什么算用户数据"这条线划出来**（它同时被备份/恢复与发布包白名单共用）。
所以本项本轮的交付 = ① 台账（_check_release.USER_DATA_NAMES / USER_DATA_DIRS）
                       ② 一条**能真失败**的契约用例（本文件）
                       ③ 一份写明"这是契约不是实现"的文档（_dev/core_pack_plan_v2110.md）**。

⚠ 本文件的判据刻意写成"清单 + 人话理由"两个部分：
   · 清单部分保证**覆盖**（这份台账至少要能认出这些东西）；
   · 反向对照部分保证**不是恒真**（拿一个只放了 config.json 的假台账走同一个表达式，必须报缺失；
     并且运行时 .py 必须**不**被判成用户数据）。
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import _check_release as rel  # noqa: E402

# 「用户会心疼的东西」—— 每一条都写清"丢了会怎样"。
# 加新键时**必须**同时给理由（这个 dict 就是台账的人话版）。
REQUIRED_USER_FILES = {
    "config.json": "设置总表：缩放、开关、人设、阈值、跟随/散步全在里面",
    "roles.json": "用户导入并按自己口味改过名的角色清单",
    "ledger.json": "记账流水 —— 少了它等于丢了钱",
    "ledger_archive.json": "归档账本（跨月之后的老账）",
    "lines.json": "用户自定义的台词库",
    "memory.log": "对话记忆 —— 它对用户说过的唯一长时记忆",
    "usage.json": "用量统计（今日/累计）",
    "focus.json": "v2.13.0 番茄钟的专注记录（今天还不存在，提前划线）",
}

REQUIRED_USER_DIRS = {
    "roles": "导入的角色素材（PNG/帧集）",
    "voice": "用户合成的语音资产",
    "voice_ref": "参考音（音色克隆的输入）",
    "audio": "用户导入的音效片段",
    "alarms": "闹钟附件（如果有）",
    "prompts/custom": "用户自建人设（插件落地的人设也在这里）",
}


def _missing(ledger, required):
    """纯函数：台账里缺了哪些键（**判据本体**，测试与反向对照共用同一个表达式）。"""
    return sorted(k for k in required if k not in ledger)


def test_user_data_ledger_covers_every_thing_a_user_would_miss():
    """台账必须覆盖「用户会心疼的东西」—— 缺一个就在发布包里被当残留删掉。"""
    miss_files = _missing(rel.USER_DATA_NAMES, REQUIRED_USER_FILES)
    assert miss_files == [], (
        "发布门的用户数据台账漏了这些文件（打包/备份时会被当残留）：%r\n逐条理由：%r"
        % (miss_files, {k: REQUIRED_USER_FILES[k] for k in miss_files}))
    miss_dirs = _missing(rel.USER_DATA_DIRS, REQUIRED_USER_DIRS)
    assert miss_dirs == [], (
        "发布门的用户数据台账漏了这些目录：%r\n逐条理由：%r"
        % (miss_dirs, {k: REQUIRED_USER_DIRS[k] for k in miss_dirs}))


def test_focus_json_is_registered_even_before_the_feature_exists():
    """v2.13.0 才做的番茄钟，它的数据文件**今天**就要进台账（提前划线，零成本）。

    能真失败：把 "focus.json" 从 USER_DATA_NAMES 删掉 → 本条 + 上一条都红。
    """
    assert "focus.json" in rel.USER_DATA_NAMES, (
        "focus.json（专注记录）不在用户数据台账里 —— 它一出生就会被发布门当成残留")
    assert "focus.json" in REQUIRED_USER_FILES, "契约清单自己漏了它（本文件内部不一致）"


def test_the_ledger_check_is_not_vacuous():
    """反向对照：同一个表达式必须**能报出缺失**，并且不能把运行时模块当用户数据。

    没有这一段，上面两条可能只是"全 True 的空转"——本仓反复踩过的形状。
    """
    # ① 拿一个**故意残缺**的假台账走同一个表达式 → 必须点名缺什么
    fake = {"config.json"}
    fake_missing = _missing(fake, REQUIRED_USER_FILES)
    assert fake_missing, "残缺台账居然通过了 —— 判据是空转"
    assert "ledger.json" in fake_missing and "focus.json" in fake_missing, fake_missing
    # ② 运行时 .py 绝不能进用户数据台账（那会把发出去的代码全挡在包外）
    leaked = sorted(n for n in rel.USER_DATA_NAMES if n.endswith(".py"))
    assert leaked == [], "运行时 .py 被误判成用户数据：%r" % (leaked,)
    # ③ 发布门自己的判定函数必须与台账一致（防止"台账改了、判定函数没跟着改"）
    for name in ("config.json", "ledger.json", "memory.log", "focus.json"):
        assert rel.user_data_hit(name) in rel.USER_DATA_NAMES, (
            "user_data_hit(%r) = %r 不在台账里（判定函数与台账脱节）"
            % (name, rel.user_data_hit(name)))
    # ④ 反例：一个明确的**运行时**文件名必须不被判成用户数据
    assert rel.user_data_hit("pet_ai.py") not in rel.USER_DATA_NAMES
