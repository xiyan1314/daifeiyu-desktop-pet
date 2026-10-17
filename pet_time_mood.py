# -*- coding: utf-8 -*-
"""大肥鱼桌宠 · 时间感知情绪（UX E2）：按时段给一句台词。纯逻辑、Qt-free、时钟与记账都可注入。

来路（不是「用户要求」，谁问都查这一段）
----------------------------------------
本模块 = 「用户 #194 提交的两份附件方案」里的 UX E2，「用户 2026-10-16 裁决并入 v2.11.0」。
· 登记：_dev/REMAINING.md §十三 第 ⑧ 行（那一节写明：这 9 项没有一项是用户原话，
  全部来自 #194 的两份 AI 起草附件）；
· 作业单：_dev/task_r11_v2110_round.md W4-c（领地 = pet_mood.py · 桌宠.py；本模块按协调者的
  切分只做纯逻辑，接线由持有 桌宠.py 的人落地，接线路点见本模块尾部的注释块）；
· 原方案一条判据都没写 —— 判据全部由 tests/test_time_mood_v2110.py 承担。

五段（照方案原文的时段，窗口一字没改）
--------------------------------------
    00:00-06:00  催睡        sleep    （低优先）
    08:00-09:30  早安        morning  （低优先）
    12:00-13:00  午餐        lunch
    14:00-15:00  咖啡打哈欠  coffee
    22:00 之后   该休息      rest     （「之后」的右端点 = 24:00，见下面口径 2）

为什么独立成模块，而不塞进 pet_mood.py（W4-c 的硬约束是「不许与 pet_mood 现有机制打架」）
------------------------------------------------------------------------------------------
1. pet_mood 是 Qt 状态机（Signal / QTimer / 每个用例都要 QApplication）。本模块 0 个 Qt
   import，于是「一天 1440 分钟穷举」这种判据能在一秒内跑完，不需要窗口、不需要 offscreen。
2. 时刻必须是参数。要验「09:29:59 归早安、09:30:00 不归」，就得能在任意时刻上问同一个
   问题；自己读系统时钟的模块只能等明天再验一次。
3. 优先级这件事只能有一个答案。pet_mood 的三条情绪线（戳链 / 食物 / 调皮）今天与「几点」
   无关，混进去以后「这句话该不该压掉那句话」就没有单一来源了。本模块只产出
   (slot_key, text) 与 priority，压不压由调用方裁决（may_interrupt 就是那条规则的可执行版本）。

为什么台词是「模块内默认表 + 可注入覆盖」，不动 lines.json
----------------------------------------------------------
lines.json 是用户数据（_check_release.USER_DATA_NAMES 里有它），而台词类目表
pet_lines.LINE_CATEGORIES 是个固定元组 —— 想从台词库喂这五类，得改 pet_lines.py（本轮不在本包
领地里）。所以：默认表在模块内，overrides={key: [文案…]} 是唯一外部入口 —— 将来谁把五类并进
台词库，也只是把 lines.json 的取值塞进 overrides，本模块一行都不用改。

为什么默认关闭（enabled 缺省 False，且只认 True）
-------------------------------------------------
这 9 项是「加餐」：老用户升级后不该突然多出一堆气泡（尤其「催睡」这种带管教的台词）。
默认关闭 + 只认 True（1 / "true" / "on" 一律不算）是本模块的立场：没被明确打开，就不打扰。
配置侧的 "true" 这类字符串必须先过 pet_config 的归一化变成真布尔 —— 把「配置没归一化」
降级成「少一句问候」，而不是「用户没开却开始弹」。

四条口径（判据 ④ / ⑤ / ⑦ 钉的就是它们）
----------------------------------------
1. 左闭右开 [start_min, end_min)，按分钟判定（秒与微秒故意不进界）：
   09:29:59 → 第 569 分钟 → 早安；09:30:00 → 第 570 分钟 → 无。
   为什么秒不进界：1s 一次的轮询根本分辨不到，而「09:29:59.999 与 09:30:00.000 之间还要再
   定义一次」这件事没有任何用户价值。
2. 相邻两段不许重叠、也不许留洞：rest 的右端点是 24:00（= 1440），sleep 的左端点是 0 ——
   0 点整归催睡，不归「该休息」。这两段跨午夜首尾相接，判据 ⑤ 的 1440 分钟穷举把这条钉死。
3. 跨天自动清零：state 记的是「每个时段最近一次发过的日期」（与 pet_alarm.due_alarms 的
   last_fired_date 同口径）；日期 ≠ 今天 → 可再发。
4. 坏输入不抛、也不猜：now 不是 datetime、state 不是映射 → 一律 None（这一次不弹）。
   反过来的两个方向都更糟：猜成「今天没发过」= 一天弹两遍；猜成「今天已发」= 永远不弹。

对外接口
--------
    slots()                                五段时段表（唯一真源，不可变元组）
    slot(key) / priority_of(key)           按 key 取一段 / 取优先级（不认识 → None）
    slot_at(now)                           某时刻属于哪一段（不属于任何一段 → None）
    pick_line(key, now, overrides=None)    取一句文案（空串 = 这次不念）
    due(now, state=None, *, enabled=False, overrides=None) -> (slot_key, text) | None
    remember(state, now, key)              把「今天发过 key」写进 state 的新副本（不改入参）
    may_interrupt(key, bubble_in_flight)   低优先（早安 / 催睡）不压在途气泡

纯函数（判据不信口头承诺）：due / remember / pick_line / slot_at 都不改入参、不读全局状态、
不碰文件、不取系统时钟。测试里 1440 次 due 之后会回头断言 state 还是那个空字典。
"""

import datetime as _dt
from collections.abc import Mapping
from dataclasses import dataclass

# ---------------- 优先级：只给调用方裁决用，本模块自己不压任何人 ----------------
# 数值大小 = 谁更能压住在途气泡。为什么用数字而不是字符串：调用方将来要把「在途气泡」的
# 优先级也记下来（闹钟 / 记账回执将来也可能想声明低优先），两个数字比一下就有答案；
# 字符串就得再维护一张「谁比谁大」的表 —— 那是第二份真源。
PRIORITY_LOW = 10     # 早安 / 催睡：可被在途气泡覆盖（不刷屏）
PRIORITY_NORMAL = 20  # 午餐 / 咖啡 / 该休息


@dataclass(frozen=True)
class TimeSlot:
    """一段固定时段的台词：[start_min, end_min) 左闭右开，单位 = 当天第几分钟。

    frozen：这张表是唯一真源，用例直接拿它做结构断言（段数 / 端点 / 相邻关系）；
    一旦可变，「跑完 1440 分钟穷举再回头断言表没变」就失去意义了。
    """

    key: str
    label: str                  # 中文名：日志 / 回执 / 报告里用人话说得清
    start_min: int              # 含
    end_min: int                # 不含；1440 = 当天结束（24:00）
    priority: int
    lines: tuple                # 默认台词池（overrides 可覆盖；删光 = 不念）


# 五段：照方案原文的窗口，顺序按当天时间排（0 点在最前、24 点收尾），
# 于是「首尾在午夜相接」这件事在表里就是 SLOTS[0].start_min == 0 与 SLOTS[-1].end_min == 1440。
# 台词写「大肥鱼」的口吻（与 pet_lines 的内置台词同调），但不进 lines.json（见模块头）。
SLOTS = (
    TimeSlot(
        key="sleep", label="催睡", start_min=0, end_min=6 * 60, priority=PRIORITY_LOW,
        lines=(
            "这么晚还不睡？明天有你哭的。",
            "熬夜伤身，快去睡觉！",
            "再不睡，我可要趴在你键盘上睡着了。",
        ),
    ),
    TimeSlot(
        key="morning", label="早安", start_min=8 * 60, end_min=9 * 60 + 30,
        priority=PRIORITY_LOW,
        lines=(
            "早上好呀！今天也要元气满满~",
            "起床啦起床啦，太阳都晒屁股了！",
            "早安，早饭吃了没？",
        ),
    ),
    TimeSlot(
        key="lunch", label="午餐", start_min=12 * 60, end_min=13 * 60,
        priority=PRIORITY_NORMAL,
        lines=(
            "十二点啦，该吃饭了！",
            "午饭时间到，别饿着自己~",
            "闻到饭香没有？我闻到啦！",
        ),
    ),
    TimeSlot(
        key="coffee", label="咖啡打哈欠", start_min=14 * 60, end_min=15 * 60,
        priority=PRIORITY_NORMAL,
        lines=(
            "哈——欠——下午最难熬的就是这会儿。",
            "来杯咖啡？我也想喝一口。",
            "别硬撑啦，站起来走两步吧。",
        ),
    ),
    TimeSlot(
        # 「22:00 之后」的右端点定在 24:00：再往后 0 点是催睡段的地盘（见口径 2）。
        key="rest", label="该休息", start_min=22 * 60, end_min=24 * 60,
        priority=PRIORITY_NORMAL,
        lines=(
            "十点多了，收收心准备休息吧。",
            "今天已经很努力了，早点睡。",
            "再刷五分钟就变成一个钟头了哦。",
        ),
    ),
)


def slots() -> tuple:
    """五段时段表（唯一真源）。返回常量本身（元组不可变），调用方不许就地改。"""
    return SLOTS


def slot(key) -> "TimeSlot | None":
    """按 key 取一段；不认识 → None（不抛：调用方的 key 可能来自旧配置 / 旧记账）。"""
    for s in SLOTS:
        if s.key == key:
            return s
    return None


def priority_of(key) -> "int | None":
    """这一段的优先级；不认识 → None。

    为什么返回 None 而不是给个默认值：调用方要拿它跟「在途气泡」比大小，给个默认值等于
    替调用方瞎猜（猜小了该压的不压，猜大了低优先也能压人）。
    """
    s = slot(key)
    return s.priority if s is not None else None


def slot_at(now) -> "TimeSlot | None":
    """某时刻属于哪一段（不属于任何一段 → None）。

    只看 hour / minute，秒与微秒故意不进界（口径 1）。now 不是 datetime → None。
    """
    if not isinstance(now, _dt.datetime):
        return None
    minute = now.hour * 60 + now.minute
    for s in SLOTS:
        if s.start_min <= minute < s.end_min:
            return s
    return None


def pick_line(key, now, overrides=None) -> str:
    """取一句文案。空串 = 这次不念（「删光了」与「取不到」共用这一个出口）。

    三个决定：
    · overrides 里这一组被删空 → 空串，不回落内置表。否则等于「删了还会念」
      （与 pet_mood._pick 的口径逐字一致）；
    · overrides 里这一组是坏类型（数字 / 字典…）→ 当作「库不可用」，回落内置表：
      用户的类别还在、只是值坏了，念一句内置的比整个功能消失好；
    · 同一天同一段总是同一句：下标 = (日期序数 + 段起点分钟) % 池长。不用 random：
      气泡文案要能复现，用例不能靠种子；而「今天这一句」固定下来，用户重开桌宠看到的
      还是同一句，不会一天内换八遍（那看起来像故障，不像人味）。
    """
    s = slot(key)
    if s is None:
        return ""
    pool = None
    if isinstance(overrides, Mapping) and key in overrides:
        cand = overrides[key]
        if isinstance(cand, (list, tuple)):
            pool = [x.strip() for x in cand if isinstance(x, str) and x.strip()]
        # cand 不是序列：pool 保持 None → 走下面的内置表（见上「坏类型」）
    if pool is None:
        pool = list(s.lines)
    if not pool:
        return ""
    if not isinstance(now, _dt.datetime):
        return pool[0]  # 时钟不认识：给第一句（保证「文案非空」这条契约，且不抛）
    return pool[(now.date().toordinal() + s.start_min) % len(pool)]


def _last_fired(state, key) -> "str | None":
    """state 里这个时段最近一次发过的日期；state 整体不是映射 → None（坏输入）。

    state = {slot_key: "YYYY-MM-DD"}，即「每个时段最近一次发过的日期」—— 这就是「今天已经
    发过哪些」的映射：日期 == 今天 ⇒ 今天已发过。与 pet_alarm 的 last_fired_date 同口径，
    谁看都认得。

    单个值坏了（数字 / None）→ 当作「没发过」（返回 ""）：只坏了这一格，没必要让整天的问候
    都停掉；而「猜成今天已发」会把当天的名额永久占住，那是更坏的方向。
    """
    if state is None:
        return ""
    if not isinstance(state, Mapping):
        return None
    v = state.get(key)
    return v if isinstance(v, str) else ""


def due(now, state=None, *, enabled=False, overrides=None) -> "tuple | None":
    """到点判定（纯函数）：该发就返回 (slot_key, text)，否则 None。

    参数
    ----
    now       : datetime，注入（生产侧传 datetime.now()，用例传任意时刻）
    state     : {slot_key: "YYYY-MM-DD"}；None / {} = 什么都没发过
    enabled   : 默认 False，且只认 True（见模块头「为什么默认关闭」）
    overrides : {slot_key: [文案…]}，可选注入（台词库 / 用例）

    为什么 due 不改 state（判据把这条钉死）
    --------------------------------------
    改 state 就必须顺手落盘，于是「问到了但气泡没弹出来」（在途气泡没让位、程序正在退出）
    也会把当天的名额吃掉 —— 用户当天就再也收不到这句问候了。现在 due 只回答「该不该发」，
    remember 由调用方在气泡真的显示出来了之后再调（show_bubble 返回 True 才记账）。
    这条分工让「吃了一天的名额却什么都没看见」变成不可能，代价是调用方多写一行。
    """
    if enabled is not True:
        return None
    s = slot_at(now)
    if s is None:
        return None
    last = _last_fired(state, s.key)
    if last is None:
        return None  # state 是坏类型：这一次不弹，也不猜（口径 4）
    if last == now.date().isoformat():
        return None  # 今天已经发过这一段
    text = pick_line(s.key, now, overrides)
    if not text:
        return None  # 这一组被删光了
    return (s.key, text)


def remember(state, now, key) -> dict:
    """把「今天发过 key」写进 state 的新副本（入参一个字节都不改）。

    为什么返回新副本而不是就地改：due 是纯函数，用例可以拿同一个 state 连问十遍断言
    「只出一次」；如果这里就地改，「先问后记」中间任何一步失败都会半截生效。
    为什么坏 state 直接重建成新表：坏到读不出日期时，没人能说出它「昨天发过什么」，
    从今天重新记账是唯一不猜的做法（且 due 在坏 state 上根本不会放行，见上）。
    """
    out = dict(state) if isinstance(state, Mapping) else {}
    if isinstance(now, _dt.datetime):
        out[str(key)] = now.date().isoformat()
    return out


def may_interrupt(key, bubble_in_flight) -> bool:
    """这段台词此刻能不能压住正在显示的气泡（「不刷屏」的可执行版本）。

    口径（作业单 W4-c）：早安 / 催睡 = 低优先 → 不压在途气泡（等它自己收，1 秒后再看）；
    午餐 / 咖啡 / 该休息 = 普通 → 允许覆盖。

    为什么规则写在这里、而「有没有气泡在显示」由参数传进来：本模块 Qt-free（没有窗口可问），
    而「在途气泡」只有调用方知道（桌宠.bubble.isVisible()）。规则留在模块里才有单一来源，
    也才有一句能真失败的判据（见 tests 的 may_interrupt 那条）。

    不认识的 key → False（宁可这次不弹，也不替调用方瞎压别人的气泡）。
    """
    p = priority_of(key)
    if p is None:
        return False
    return p > PRIORITY_LOW or not bubble_in_flight


# ============================================================================
# 接线路点（**不在本包领地**：写在这里是给持有 桌宠.py / pet_menu.py 的人照抄）
# ============================================================================
# ① 定时器：**一格都不新建**。桌宠.py 已经有一个 1 秒的 self.mood_timer
#    （:1082-1085，timeout → _mood_tick）。在 :1085 之后再加一条同一个定时器的槽即可：
#        self.mood_timer.timeout.connect(self._gslot('_time_mood_tick', self._time_mood_tick))
#    为什么不另开 QTimer：任务书 §四.3 要求「新建定时器要有收尾回基线断言」，
#    复用既有 1s 拍子 = 0 个新对象、_quit 的停止元组（:6000）一个字都不用改。
# ② 槽本体（放 _mood_tick 附近）：三个既有闸门直接复用，不新增状态位——
#    ⚠ 桌宠.py 今天只有 import time（:17），**没有 datetime** —— 接线时先加一行 import datetime
#    （_check_static 的 N 检查会抓「用了没 import 的名字」，先写上省一次红）。
#        def _time_mood_tick(self):
#            if self._closing or self._sleeping or self.busy or self._petting:
#                return
#            now = datetime.now()
#            got = pet_time_mood.due(now, self.cfg.get("time_mood_sent"),
#                                    enabled=self.cfg.get("time_mood") is True)
#            if got is None:
#                return
#            key, text = got
#            if not pet_time_mood.may_interrupt(key, self.bubble.isVisible()):
#                return          # 低优先不压在途气泡：**不记账**，1 秒后再看（名额还在）
#            if not self.show_bubble(text):
#                return          # 没真显示出来（_closing / 无屏）：同样不记账
#            self.cfg["time_mood_sent"] = pet_time_mood.remember(
#                self.cfg.get("time_mood_sent"), now, key)
#            save_config(self.cfg)   # 既有落盘出口；失败也不回滚已弹出的气泡
# ③ 开关：pet_menu.py 的「⚙️ 设置…」子菜单里，紧跟「🎨 气泡样式…」（:146-147）之后加一条
#    「⏰ 时段问候」（setCheckable(True)，默认不勾）。**顶层菜单不许加项**（18 项上限，
#    _verify_green.py:86），这也是 C-34 的旧账。
# ④ 配置：桌宠.DEFAULT_CONFIG（:194-252，末尾 high_contrast 之后）加两个键：
#        "time_mood": False,           # 布尔；归一化走 pet_config（_to_bool）
#        "time_mood_sent": {},         # {slot_key: "YYYY-MM-DD"}，当日记账
#    并在 pet_config.normalize_cfg 里归一化（坏值 → False / {}），这是 pet_config.py 的领地。
# ⑤ 发行清单：_check_release.SYNC_FILES（:43-62）必须加 "pet_time_mood.py"（跟在
#    :61 的 "pet_motion.py" 后面）。漏了这一行，绿色版 / 发布包会缺件，而且只要没人 import
#    它，反向校验（check_imported_modules_shipped）也不会点它的名。
