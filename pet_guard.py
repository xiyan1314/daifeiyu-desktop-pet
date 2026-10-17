# -*- coding: utf-8 -*-
"""崩溃自动重启的**判定层**（v2.11.0 · W3-c · 代理 ④）。

来路（口径，不许写错）
----------------------
用户 **#194 提交的附件方案**（两份 AI 起草的方案）+ **2026-10-16 用户裁决并入 v2.11.0**
（登记：`_dev/REMAINING.md` §十三 第 ④ 项；作业单：`_dev/task_r11_v2110_round.md` §一 · W3-c）。
方案里的四条是：**退出码非 0 才重启 · 崩溃计数 · 3 次上限（熔断）· `crash_recovery.json` 落盘**。
⚠ 它不是"用户原话要求"，任何文档都不许那样写。

为什么单独成模块（而不是直接写进 main.py）
------------------------------------------
「要不要重启」是**策略**，「拉起 / 计时 / 弹提示」是**动作**。混在一起的后果是策略只能靠
真起进程来测——而真起进程的用例既慢又不稳（Windows 上还牵扯控制台窗口与单实例互斥体）。
所以这里只留策略：**本模块不 spawn、不 sleep、不弹框、判定时不读墙钟**；拉起由 `main.py` 做。
于是「熔断 / 退避 / 时钟倒退 / 坏参数」这些判据都能拿合成输入确定性地复现。

判定规则（一句话）
------------------
正常退出（退出码 0 **且** 有正常退出标记）→ 不重启；
异常退出 → 滑动窗口内"真的拉起过"的次数 < 上限才重启，间隔 `base * factor**n` 递增（封顶）；
已达上限 → 不重启，并在 `reason` 里给一句**人能照着做**的话（`notify_user=True`）。
**拿不准的一律站安全侧：不重启、不抛异常。**

为什么"两个信号都成立才算正常退出"
----------------------------------
只认退出码 0：`os._exit(0)` / 被任务管理器"结束任务" / 启动器被父进程收走，进程都可能是 0，
但桌宠的退出清理一行没跑（`桌宠.py` 的 `_quit` 没执行）。只认标记：标记是在 `main()`
正常返回**之后**写的，之后到进程真正结束之间仍可能崩。两个都成立才放过，代价是偶尔多拉
一次——宁多拉一次，也不许"用户以为它还开着，其实早没了"。

接法（main.py 侧，伪码）
------------------------
    marker = load_marker(marker_path(DATA_DIR))
    policy = SupervisorPolicy(params=None, clock=time.time)
    policy.adopt_marker(marker)
    code = ...            # 本次进程退出码（SystemExit.code 先过 exit_status）
    clean = (code == 0)   # 只有"正常返回 / 正常 quit"这条路径才为真
    d = policy.decide(code, normal_exit=clean)
    if d.should_restart:
        save_marker(path, record_crash(marker, exit_code=code, now=t, will_restart=True))
        spawn(restart_command(sys.executable, main_py))   # ← 动作在 main.py，不在本模块
    elif d.notify_user:
        save_marker(path, record_crash(marker, exit_code=code, now=t, will_restart=False))
        <把 d.reason 告诉用户>
    else:
        save_marker(path, record_clean_exit(marker, now=t))
"""
import math
import os
import sys
import time
from dataclasses import dataclass

import pet_io

# ---------------- 常量（文件名 / 参数默认值 / 上限） ----------------
# 文件名单独一个常量：`_check_release.USER_DATA_NAMES` 要按**同一个字符串**登记，
# 全仓再写一处字面量就会出现"门里改了、这里没改"的静默漏登记。
MARKER_FILENAME = "crash_recovery.json"

# 被自动拉起的进程靠它认出自己：argv 里带这个 flag（或环境变量 = 1）。
# 为什么两套：Qt 会解析 QApplication 的命令行，未知参数在个别版本上会被吞/告警；
# 环境变量是退路，两条路任一命中就算"我是崩溃后拉起的"。
RESTART_FLAG = "--guard-restart"
GUARD_RESTART_ENV = "DAFEIYU_GUARD_RESTART"

DEFAULT_MAX_RESTARTS = 3        # 熔断上限：窗口内最多自动拉起 3 次（方案原文的"3 次"）
DEFAULT_WINDOW_SECONDS = 300.0  # 滑动窗口 5 分钟：窗口太短 = 慢慢崩的循环永远撞不到上限
DEFAULT_BASE_DELAY = 1.0        # 第一次重启前等 1 秒：给崩溃残留（文件句柄/端口）一点释放时间
DEFAULT_BACKOFF_FACTOR = 2.0    # 1s → 2s → 4s：连崩时用户看得清"它又没了"，而不是屏幕抽搐
DEFAULT_MAX_DELAY = 30.0        # 封顶：再崩也别让用户等半分钟以上（重启不是惩罚）

MARKER_SCHEMA = 1               # 标记结构版本（升/降级都按字段尽力读，不因版本号拒绝）
MAX_KEPT_RESTARTS = 64          # 标记里最多留多少条重启时间戳：只用于窗口计数，留太多没意义


# ---------------- 取值归一化（所有"可能坏"的入口都走这里） ----------------
def _number(value):
    """任意值 → 有限 float；不是有限数值就 None（bool 不算数值）。

    为什么单独一层：熔断与退避的**每一个**输入都可能来自磁盘（被用户/编辑器改坏的 JSON）
    或外部时钟。任何一处抛异常，启动器就会在"决定要不要救自己"的路上崩掉——那比不重启更糟。
    """
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError, OverflowError):
        return None          # 超大整数（float() 会 OverflowError）也算"不是可用数值"
    return f if math.isfinite(f) else None


def _as_int(value, default):
    """任意值 → int；非数值 / 坏数值退回 default（不抛）。"""
    f = _number(value)
    if f is None:
        return default
    try:
        return int(f)
    except (ValueError, OverflowError):   # 有限 float 的 int() 不会抛，留着兜底以防将来改实现
        return default


def _exit_int(code):
    """退出码 → int 或 None（None = 拿不到可靠退出码）。

    **不要**在这里把字符串强转成整数：`sys.exit("出错了")` 的 `SystemExit.code` 是字符串，
    而进程真正的退出码是 1。字符串在这里一律当"拿不到"（安全侧）；要变成 1 请先过 `exit_status`。
    """
    if isinstance(code, bool):
        return int(code)
    if isinstance(code, int):
        return code
    f = _number(code)
    return None if f is None else int(f)


def exit_status(code):
    """`SystemExit.code` → 进程退出码的整数形态（None→0、整数原样、其它→1）。

    这是给 main.py 的**唯一**入口：Python 的约定是 `sys.exit()` = 0、`sys.exit("msg")`
    打印一行后按 1 退出。自动重启必须按"进程真实的退出码"判断，不能拿字符串去比 0。
    """
    if code is None:
        return 0
    if isinstance(code, int):        # bool 也是 int：True→1 / False→0，与 CPython 一致
        return int(code)
    return 1


def _clean_timestamps(values):
    """时间戳序列 → 只留有限数值（坏条目静默丢弃）；不可迭代 → []。"""
    try:
        items = list(values)
    except TypeError:
        return []
    out = []
    for v in items:
        f = _number(v)
        if f is not None:
            out.append(f)
    return out


# ---------------- 参数（熔断 + 退避） ----------------
@dataclass(frozen=True)
class GuardParams:
    """熔断 / 退避的可注入参数。**只通过 normalize() 得到实例**，坏值不抛。

    各字段的坏值口径（normalize 的文档化默认）：
      · `max_restarts <= 0` → **0 = 关闭**（负数不猜"用户本来想要几次"；这是最安全的读法，
        而且给了产品一个"关掉自动重启"的开关）。
      · `window_seconds <= 0` / 缺 → **300 秒**（0 窗口 = 谁都不算，等于没熔断，绝不能默认）；
      · `base_delay <= 0` / 缺 → **1 秒**（0 延迟 = 热循环，正是要防的东西）；
      · `backoff_factor < 1` → **抬到 1.0**（退避不许变成"越来越快"）；
      · `max_delay < base_delay` → **抬到 base_delay**（延迟永远不许低于 base）。
    """

    max_restarts: int = DEFAULT_MAX_RESTARTS
    window_seconds: float = DEFAULT_WINDOW_SECONDS
    base_delay: float = DEFAULT_BASE_DELAY
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR
    max_delay: float = DEFAULT_MAX_DELAY

    @classmethod
    def normalize(cls, params=None):
        """任何输入（None / dict / 本类 / 别的东西）→ 一份能安全参与判定的参数。

        绝不抛：调用方可能是 main.py 在崩溃后的第一条语句，这里抛就等于把启动器也带走。
        """

        def raw(name, default):
            if isinstance(params, dict):
                return params.get(name, default)
            return getattr(params, name, default)

        max_restarts = _as_int(raw("max_restarts", DEFAULT_MAX_RESTARTS), DEFAULT_MAX_RESTARTS)
        if max_restarts < 0:
            max_restarts = 0

        window = _number(raw("window_seconds", DEFAULT_WINDOW_SECONDS))
        if window is None or window <= 0:
            window = DEFAULT_WINDOW_SECONDS

        base = _number(raw("base_delay", DEFAULT_BASE_DELAY))
        if base is None or base <= 0:
            base = DEFAULT_BASE_DELAY

        factor = _number(raw("backoff_factor", DEFAULT_BACKOFF_FACTOR))
        if factor is None:
            factor = DEFAULT_BACKOFF_FACTOR
        elif factor < 1.0:
            factor = 1.0

        cap = _number(raw("max_delay", DEFAULT_MAX_DELAY))
        if cap is None or cap <= 0:
            cap = DEFAULT_MAX_DELAY
        if cap < base:
            cap = base

        return cls(max_restarts=max_restarts, window_seconds=window,
                   base_delay=base, backoff_factor=factor, max_delay=cap)


@dataclass(frozen=True)
class RestartDecision:
    """一次判定的人话结论（frozen：判定出来之后不许被下游悄悄改）。

    `reason` 直接可以给用户看；`notify_user` = "这次没有自动拉起，而且**该告诉用户**了"
    （熔断 / 时钟不可信 / 退出码不可判）。调用方不需要再拼文案，避免两处口径不一致。
    """

    should_restart: bool
    delay_seconds: float
    reason: str
    restarts_in_window: int = 0
    tripped: bool = False          # 熔断/安全侧动作过（历史不可信 或 已到上限）
    notify_user: bool = False
    exit_code: object = None       # 原始输入，只为日志/取证；可能是 None 或非整数

    def as_dict(self):
        """给日志用的一层薄封装（字段名与 dataclass 一致）。"""
        return {
            "should_restart": self.should_restart,
            "delay_seconds": self.delay_seconds,
            "reason": self.reason,
            "restarts_in_window": self.restarts_in_window,
            "tripped": self.tripped,
            "notify_user": self.notify_user,
            "exit_code": self.exit_code,
        }


# ---------------- 窗口与退避 ----------------
def _window_hits(restarts, now, window):
    """→ (窗口内的重启时间戳列表, 未来时间戳个数)。

    窗口是**半开区间** `[now - window, now)`：正好等于窗口宽度的记录算"已经滑出"
    （第 ⑤ 条判据就靠这个边界；用 `<=` 会让"刚好 5 分钟前那次"永远压在计数里）。
    `now - t < 0`（记录比"现在"还晚）= 时钟倒退/被改过：**不计入窗口，单独计数**——
    这类记录一条都不能证明熔断已清，调用方据此站安全侧。
    """
    hits = []
    future = 0
    for t in _clean_timestamps(restarts):
        delta = now - t
        if delta < 0:
            future += 1
        elif delta < window:
            hits.append(t)
    return hits, future


def backoff_delay(n, params=None):
    """窗口内第 n 次（0 基）重启前的等待秒数：`base * factor**n`，封顶 `max_delay`。

    为什么按"窗口内已有几次"而不是"总崩溃次数"：窗口滑过之后计数归零，下一次崩溃应立刻用
    最短延迟拉起——否则用户隔天崩一次也要先等 8 秒，把"救急"变成"罚站"。
    """
    p = GuardParams.normalize(params)
    try:
        k = max(0, int(n))
    except (TypeError, ValueError, OverflowError):
        k = 0
    try:
        delay = p.base_delay * (p.backoff_factor ** k)
    except OverflowError:        # factor**k 溢出（k 很大）：直接落封顶，不抛
        delay = p.max_delay
    if not math.isfinite(delay):
        delay = p.max_delay
    if delay > p.max_delay:
        delay = p.max_delay
    if delay <= 0:               # 归一化后走不到这里；兜底保证"永不返回 0 延迟"
        delay = p.base_delay
    return float(delay)


# ---------------- 判定（纯函数：唯一入口） ----------------
def decide_restart(exit_code, *, normal_exit, restarts=(), now, params=None):
    """这次退出要不要自动拉起 → RestartDecision。**不读时钟、不写盘、不 spawn。**

    入参
    ----
    exit_code   进程退出码（int；None = 拿不到）。`SystemExit.code` 请先过 `exit_status()`；
                直接喂字符串/对象在这里按"拿不到"处理（安全侧）。
    normal_exit 本次会话是否走到了**正常退出路径**（main.py 在 `桌宠.main()` 正常返回 /
                SystemExit 且退出码为 0 时置真）。它和退出码**都**成立才算正常退出：
                任一说"不正常"就按异常退出走熔断——宁可多拉一次，也不许静默消失。
    restarts    最近若干次**真的自动拉起**的时间戳（必须与 now 同一时间基准）。
    now         **必填**：当前时间。本模块不自己读时钟，判据才能确定性复现
                （时钟倒退 / 未来时间戳 / 黑洞时钟都能直接构造）。
    params      GuardParams / dict / None；坏值一律归一化，绝不抛。
    """
    p = GuardParams.normalize(params)
    code = _exit_int(exit_code)

    # ① 正常退出：进程自己走完了清理路径，用户本来就想关它——拉起来等于跟用户对着干。
    if bool(normal_exit) and code == 0:
        return RestartDecision(False, 0.0,
                               "正常退出（退出码 0，且有正常退出标记）：不自动重启。",
                               exit_code=exit_code)

    # 上限 0 = 功能关闭。放在"退出码可疑"之前：配置优先，别让一次配置关停还附带告警。
    if p.max_restarts <= 0:
        return RestartDecision(False, 0.0,
                               "自动重启上限被设成 0（= 关闭）：本次不自动重启。",
                               exit_code=exit_code)

    # ② 退出码不可判：分不清"真崩溃"与"用户手动结束"。重启它可能变成拉锯战，
    #    而且没有可靠退出码就没有可靠计数——安全侧 = 不拉，但**必须**告诉用户。
    if code is None:
        return RestartDecision(False, 0.0,
                               "拿不到可靠的退出码：分不清是崩溃还是被手动结束，"
                               "安全侧 = 不自动重启；需要时请手动打开桌宠。",
                               notify_user=True, exit_code=exit_code)
    if code < 0:
        return RestartDecision(False, 0.0,
                               "退出码是负数（Windows 上通常=被系统或用户强制结束）："
                               "安全侧 = 不自动重启，避免和手动结束拉锯；需要时请手动打开桌宠。",
                               notify_user=True, exit_code=exit_code)

    # ③ 时间基准不可信：窗口数学无从谈起，任何"补拉"都可能把熔断绕过去。
    stamp = _number(now)
    if stamp is None:
        return RestartDecision(False, 0.0,
                               "读不到可信的当前时间：无法判断熔断状态，"
                               "安全侧 = 不自动重启；需要时请手动打开桌宠。",
                               notify_user=True, exit_code=exit_code)

    hits, future = _window_hits(restarts, stamp, p.window_seconds)

    # ④ 时钟倒退：历史里有"未来"记录时，无法确认窗口内到底几次 → 站安全侧。
    if future:
        return RestartDecision(False, 0.0,
                               "崩溃记录里有晚于当前时间的时间戳（系统时钟疑似被回拨）："
                               "无法确认熔断状态，安全侧 = 不自动重启；需要时请手动打开桌宠。",
                               restarts_in_window=len(hits), tripped=True, notify_user=True,
                               exit_code=exit_code)

    # ⑤ 熔断：窗口内已经拉起到上限 → 停手，并给一句能照做的话（"看 error.log 再手动开"）。
    if len(hits) >= p.max_restarts:
        return RestartDecision(
            False, 0.0,
            "最近 %d 秒内已经自动重启 %d 次（上限 %d 次）：为避免无限重启循环，"
            "这次不再自动拉起。请先看 error.log 里的报错，确认原因后手动打开桌宠。"
            % (int(p.window_seconds), len(hits), p.max_restarts),
            restarts_in_window=len(hits), tripped=True, notify_user=True,
            exit_code=exit_code)

    # ⑥ 允许重启：退避按"窗口内已有几次"算，第一次最短。
    delay = backoff_delay(len(hits), p)
    return RestartDecision(
        True, delay,
        "上次是异常退出（退出码 %d）：窗口内第 %d/%d 次自动重启，%.1f 秒后拉起。"
        % (code, len(hits) + 1, p.max_restarts, delay),
        restarts_in_window=len(hits), exit_code=exit_code)


class SupervisorPolicy:
    """有状态的薄壳：参数 + 注入的时钟 + 最近重启时间戳；判定全交给 decide_restart。

    **状态是显式的**：`note_restart()` 只在**真的拉起之后**调，`adopt_marker()` 只在启动时
    调一次；`decide()` 自身不改任何状态（同一份输入调两次结果必须相等）。
    这样"日志里记的判定"与"实际动作"不会因为隐式状态而错位。
    """

    def __init__(self, params=None, clock=None, restarts=()):
        self.params = GuardParams.normalize(params)
        # 生产默认用 time.time：崩溃标记里的时间戳是墙钟，跨进程只能靠墙钟对齐；
        # 测试一律注入（或直接给 decide(now=...)），默认时间源从不参与断言。
        self._clock = clock if callable(clock) else time.time
        self._restarts = _clean_timestamps(restarts)[-MAX_KEPT_RESTARTS:]

    def now(self, now=None):
        """当前时间：显式给 now 就原样用，否则读注入的时钟。

        时钟自己抛异常（被换成坏对象 / 系统调用失败）→ 返回 None，decide_restart 会走
        "读不到可信时间"的安全侧——**不许**让启动器因为读时钟而崩。
        """
        if now is not None:
            return now
        try:
            return self._clock()
        except Exception:
            return None

    def decide(self, exit_code, normal_exit=False, *, now=None):
        """见 decide_restart；now 缺省时读注入时钟（测试可显式给）。"""
        return decide_restart(exit_code, normal_exit=normal_exit,
                              restarts=self._restarts, now=self.now(now),
                              params=self.params)

    def note_restart(self, now=None):
        """记一次**真的拉起了**的重启（spawn 成功后调；没 spawn 别调）。

        为什么"拉起过"才记：判定要重启但 spawn 失败（exe 被删/权限）时若也计数，
        熔断会被"根本没成功的重启"提前耗尽——用户一次新的机会都没得到。
        返回 False = 时钟不可用，什么都没记（调用方自己决定要不要记日志）。
        """
        stamp = _number(self.now(now))
        if stamp is None:
            return False
        self._restarts = (self._restarts + [stamp])[-MAX_KEPT_RESTARTS:]
        return True

    def adopt_marker(self, marker):
        """用崩溃标记里的历史接管（启动时调一次）；坏标记 → 空历史，不抛。"""
        self._restarts = list(normalize_marker(marker)["restarts"])
        return self._restarts

    def forget_restarts(self):
        """清空重启历史（**正常退出后**调；等价于 record_clean_exit 在盘上的效果）。

        为什么要有：标记与策略壳是两份状态。一个常驻的启动器（不是"拉起后自己退出"那种）
        在用户正常关掉桌宠之后，若不把内存里的历史一起清掉，下一次崩溃会被上一轮的计数
        压住——用户明明正常关过，再崩一次却被判"已达上限"。
        """
        self._restarts = []
        return self._restarts

    def restarts(self):
        """当前持有的重启时间戳（副本：外部改不到内部状态）。"""
        return tuple(self._restarts)


# ---------------- 崩溃标记（路径由调用方注入，本模块不认识 DATA_DIR） ----------------
def marker_path(data_dir):
    """数据目录 → 崩溃标记的完整路径；data_dir 为空 → ""（调用方据此当作"不落盘"）。

    **不写死 DATA_DIR**：路径是 main.py 的职责（绿色版/源码运行/CI 各不相同），
    这里只保证"文件名只有一处字面量"，`_check_release.USER_DATA_NAMES` 用它登记。
    """
    text = data_dir if isinstance(data_dir, str) else ""
    if not text.strip():
        return ""
    return os.path.join(text, MARKER_FILENAME)


def empty_marker():
    """空白崩溃标记（首次运行 / 文件不存在 / 内容坏掉时的安全默认）。"""
    return {"schema": MARKER_SCHEMA, "crash_count": 0, "restarts": [],
            "last_exit_code": None, "last_crash_at": None, "last_clean_at": None}


def normalize_marker(raw):
    """任意读到的内容 → 一份**合法**标记（字段逐个归一化，绝不抛）。

    为什么按字段归一化而不是"坏就整份丢掉"：`crash_count` / `restarts` 是熔断的唯一依据，
    一个坏字段不该连带丢掉能读的部分；但读不出来的字段一律回到"没崩溃过"的安全默认——
    宁可多给一次重启机会，也不许因为一个坏字段把用户永久挡在"不自动拉起"里。
    """
    out = empty_marker()
    if not isinstance(raw, dict):
        return out
    out["schema"] = max(0, _as_int(raw.get("schema"), MARKER_SCHEMA))
    out["crash_count"] = max(0, min(_as_int(raw.get("crash_count"), 0), 1000000))
    out["restarts"] = _clean_timestamps(raw.get("restarts"))[-MAX_KEPT_RESTARTS:]
    out["last_exit_code"] = _exit_int(raw.get("last_exit_code"))
    out["last_crash_at"] = _number(raw.get("last_crash_at"))
    out["last_clean_at"] = _number(raw.get("last_clean_at"))
    return out


def record_crash(marker, *, exit_code=None, now=None, will_restart=False):
    """记一次异常退出 → **新**标记（纯函数：不改入参）。

    `will_restart=True` 才把 now 追加进 `restarts`：那里的语义是"**真的拉起过**"，
    不是"崩溃过"（理由见 SupervisorPolicy.note_restart）。now 不可用时只记崩溃计数。
    """
    m = normalize_marker(marker)
    m["crash_count"] = m["crash_count"] + 1
    m["last_exit_code"] = _exit_int(exit_code)
    stamp = _number(now)
    if stamp is not None:
        m["last_crash_at"] = stamp
        if will_restart:
            m["restarts"] = (m["restarts"] + [stamp])[-MAX_KEPT_RESTARTS:]
    return m


def record_clean_exit(marker, *, now=None):
    """记一次**正常退出** → 新标记：崩溃计数与重启窗口清零（熔断只治"连续崩溃"）。

    用户关一次桌宠就说明"这一轮不是崩溃循环"，下次崩溃应立刻得到最短延迟的重启机会；
    保留 `last_crash_at` 只作取证（"上次崩是什么时候"是排障要看的）。
    """
    m = normalize_marker(marker)
    m["crash_count"] = 0
    m["restarts"] = []
    m["last_exit_code"] = 0
    stamp = _number(now)
    if stamp is not None:
        m["last_clean_at"] = stamp
    return m


def load_marker(path, *, log=None):
    """读崩溃标记 → **永远**返回一份合法标记（缺文件 / 坏 JSON / 读不到 → 空标记）。

    读侧**不修补**：坏文件一个字节都不动（与 pet_io.read_json_ex 同口径）——
    下一次正常退出会用 record_clean_exit 覆盖它，但"读一下就顺手改写"会让用户/后续版本
    失去现场（真出问题时要能拿到那份坏文件）。
    """
    if not path:
        return empty_marker()
    try:
        data, _corrupted = pet_io.read_json_or(path, dict, expect=dict, log=log)
    except Exception:            # pet_io 承诺不抛；这层兜底是为了"启动器绝不因读标记而崩"
        return empty_marker()
    return normalize_marker(data)


def save_marker(path, marker, *, log=None):
    """原子写崩溃标记：成功返回 None，失败返回错误字符串（**绝不抛**）。

    走 `pet_io.atomic_write_json`（全仓唯一的原子写实现：进程+线程唯一临时名、replace
    冲突重试、失败清自己的 tmp）——这里再写一份"差不多"的实现，就是下一次"改一处漏一处"。
    写入前先归一化：保证"写进去的"与"读出来归一化的"逐字段一致（往返判据靠它）。
    """
    if not path:
        return "未提供崩溃标记路径"
    payload = normalize_marker(marker)
    try:
        return pet_io.atomic_write_json(path, payload, indent=2, log=log)
    except Exception as e:       # 兜底：写标记失败不许把启动器带走
        return str(e)


# ---------------- 重启命令行（只拼字符串，不 spawn） ----------------
def restart_command(executable, entry=None, extra_args=()):
    """组装"重新拉起桌宠"的命令行 → tuple；拼不出来时返回 `()`（调用方据此不重启）。

    · 冻结版（PyInstaller）没有入口脚本：`entry=None`，命令就是 `<exe> --guard-restart`；
    · 源码运行：entry = main.py 的路径；
    · 一律**不经 shell**（list 形态），参数里的空格 / 中文 / 引号不会被二次解释；
    · 自动带 `RESTART_FLAG`：被拉起的进程可用 is_guard_launch() 认出"我是崩溃后拉起的"。
    本函数不检查文件是否存在（那是调用方的环境问题），也不 spawn——副作用留在 main.py。
    """
    exe = executable.strip() if isinstance(executable, str) else ""
    if not exe:
        return ()
    cmd = [exe]
    if isinstance(entry, str) and entry.strip():
        cmd.append(entry.strip())
    if isinstance(extra_args, str):
        extra = [extra_args]
    else:
        try:
            extra = list(extra_args)
        except TypeError:
            extra = []
    for a in extra:
        if isinstance(a, str) and a and a != RESTART_FLAG:
            cmd.append(a)
    if RESTART_FLAG not in cmd:
        cmd.append(RESTART_FLAG)
    return tuple(cmd)


def is_guard_launch(argv=None, environ=None):
    """本次进程是不是"崩溃后被自动拉起的"（argv 标记或环境变量，任一命中即真）。

    argv / environ 都可注入：产品里不传（读 sys.argv / os.environ），测试里传合成值
    （绝不读宿主环境，否则"在谁的机器上跑"会改变结论）。
    """
    args = sys.argv if argv is None else argv
    try:
        for a in args or ():
            if a == RESTART_FLAG:
                return True
    except TypeError:            # 喂了不可迭代的坏 argv：不抛
        pass
    env = os.environ if environ is None else environ
    try:
        return str(env.get(GUARD_RESTART_ENV, "")) == "1"
    except Exception:
        return False
