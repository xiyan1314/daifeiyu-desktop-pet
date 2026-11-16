# -*- coding: utf-8 -*-
"""事件分档表（v2.12.0 第 12 轮 · B 项）—— 「哪些算打扰 / 哪些算陪伴」的唯一真源。

为什么要有这张表：同样的两秒钟，用户对「系统通知弹出来」和「宠物自己嘀咕一句」的容忍度
完全不同。以前这条口径散在 README 的文字里和十几个调用点里，改一边漏一边无人红。
现在它是一张表，README 的「打扰还是陪伴」一节由它生成同源判据
（tests/test_action_taxonomy_v2120.py）：文档里多一个 / 少一个事件名，那条测试当场红。

分档只有两种：
  · disturb（打扰）——抢注意力、必须用户处理或至少看一眼；默认应可关、且要克制；
  · companion（陪伴）——自己发生、不要求回应，关掉只是「少点意思」，不影响使用。

⚠ 本表今天只被 README 同源判据与将来的「总开关」消费；新增任何会自己弹出来的东西，
先在这里登记分档，再写代码。没登记的 = 没有分档 = 默认按「打扰」审。
"""

# 事件名 → (分档, 一句话说明)
# 事件名用下划线小写：README 表格里以反引号标注，两边逐字相等（大小写也算）。
TAXONOMY = {
    "notify": ("disturb", "系统托盘通知（余额预警 / 备份提醒等）"),
    "alarm": ("disturb", "闹钟到点提醒"),
    "focus": ("disturb", "番茄钟到点（第 22 轮）"),
    "feed": ("companion", "喂食互动与咀嚼表演"),
    "poke": ("companion", "戳戳反应与情绪回应"),
    "idle_say": ("companion", "待机碎碎念"),
    "time_mood": ("companion", "时段问候"),
    "first_run": ("companion", "首次引导气泡"),
    "easter": ("companion", "惊喜彩蛋（第 12 轮）"),
}

KINDS = ("disturb", "companion")


def kind_of(event):
    """事件的分档；不认识就返回 None（不猜成 companion——没登记的按打扰审）。"""
    hit = TAXONOMY.get(event)
    return hit[0] if hit else None


def is_disturb(event):
    """是不是「打扰」；未登记的事件同样按打扰算（保守方向：宁可不弹）。"""
    return kind_of(event) != "companion"
