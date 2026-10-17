# -*- coding: utf-8 -*-
"""前台窗口是否全屏（v2.11.0 第 11 轮 · W1-a）——「全屏自动隐藏」的判据底座。

为什么单独抽一个模块
------------------
「全屏自动隐藏」（W3-a）和将来的「窗口吸附 / 攀爬」都要同一个事实：**此刻前台窗口是不是
盖住了整块屏幕**。计划里把这条写成"先抽 pet_windows.py"（_dev/plan_v270_rounds.md:54），
理由是本项目踩过的老坑——**同一个事实有两份实现，就必然分叉**。

三层分工（分开才测得动）
----------------------
1. `is_fullscreen` / `is_any_fullscreen`：**纯函数**。只吃"屏幕矩形 + 前台窗口快照"，
   一次系统调用都不做、不看时钟、不读全局状态。判定口径全在这一层，测试不需要真桌面。
2. `Win32Probe`：**唯一**碰 Win32 的地方（ctypes + user32）。只负责"读出前台窗口现在
   长什么样"，不做判定；读数失败一律给 None。
3. `FullscreenWatcher`：**状态层**。把"多久查一次"（节流）与"连续几次算数"（去抖）
   从"查什么"里拆出来——调用方的 tick 可能因为拖动 / 动画快到 16ms，而查询 250ms 一次就够；
   两件事写在一处，改一个必然连带另一个。

可注入
------
两层入口都能换：`FullscreenWatcher(probe=...)` 收任意 `() -> ForegroundWindow | None`
可调用物；`Win32Probe(api=...)` 换掉底层 Win32 调用层。offscreen / CI / 非 Windows 上
用假数据就能测——**用例永远不读真桌面**，否则它会随"开发者此刻开着什么窗口"红绿。

出错一律走安全侧，但**不静默**
--------------------------
判定失败（探针抛错、读数拿不到、屏幕列表为空、形状不对）**一律不作为全屏**：
宁可"该藏的时候没藏"（用户看得见桌宠，可以关掉功能），也绝不"不该藏的时候藏了"
（用户会以为程序崩了）。
但"安全侧"不等于"当没发生"：每一次被折成"不是全屏"的异常都记在 `last_error` /
`fail_count` 上，并由 `on_error` 回调转手出去（接线路点建议挂
`pet_log.log_throttled`）。**对象已死不吭声（窗口在读数途中消失是 alt-tab 常态），
写错的错必须出声**（形状错、后端坏都有记录）。

坐标系（最容易踩的坑，消费方必读）
------------------------------
`GetWindowRect` 给的是**物理像素**；Qt 的 `QScreen.geometry()` 给的是**逻辑(DIP)像素**。
两者只在整机 100% 缩放时相等。本模块**不做任何换算**——换算要问 Qt 或系统，那它就不再是
纯函数了。所以 `screen_rect` 必须与探针**同一坐标系（物理像素）**；接线路点见报告。

已知边界（有意划定，不是缺陷）
--------------------------
* **最大化窗口不算全屏**：Windows 的最大化窗口矩形比显示器**外扩一圈**（resize border；
  本机实测：最大化的 Chrome 是 left -7 / right +12 / bottom +8，主屏 1280×800），而真正的
  全屏 / 无边框全屏与显示器矩形**逐像素相同**。默认容差 2px 因此
  把最大化窗口排除在外——这正是想要的：最大化窗口的边缘没被遮住，桌宠在上面依然看得见。
  真需要"最大化也隐藏"，做法是**抬 `tolerance_px`**；**不要**把判据改成"覆盖即算"
  （那样最大化窗口会被一并算进来，且从此分不开这两种情形）。
* **跨屏窗口不算全屏**：一块屏一条判据，`is_any_fullscreen` 逐屏问。盖住两块屏的窗口对
  每一块屏都是"比屏幕大一圈"，按上一条的同一理由不算全屏。
* **不看窗口样式**：不查 WS_MAXIMIZE / WS_POPUP / WS_CAPTION。样式是"应用打算怎么画"，
  矩形是"屏幕上实际占了什么"——判据只认后者，也省掉一大片 ctypes 面。

为什么不用 pygetwindow / pywin32
------------------------------
两者都是第三方依赖（requirements.txt 里没有它们，_check_release.py 还要按
requirements-lock.txt 核对）。ctypes 是标准库，够用。
"""

import ctypes
import os
import time
from typing import NamedTuple

# ---------------- 可调口径 ----------------

# 容差（px）：为什么是 2，不是 0 也不是 8
#   · 0 太紧：DPI 取整、系统边框折算会让真正的全屏差 1px，功能就会"时灵时不灵"；
#   · 8 太松：Windows 最大化窗口的 resize border 外扩 7~12px（本机实测 7/12/8），
#     容差一到那里，"最大化"就会被误判成"全屏"（见模块文档的已知边界）。
FULLSCREEN_TOLERANCE_PX = 2

# 最小查询间隔（ms）：Win32 **不提供**"前台窗口变了"的通知，只能轮询；而一次查询是 5~6 次
# 系统调用。250ms 是"人眼能接受的最短打扰"与"调用成本"的折中：真按 16ms 查，一秒 60 次 ×
# 6 个系统调用，纯属白烧。调用方（QTimer 间隔）可以更慢，**不许更快**——所以下面取 max。
POLL_MIN_INTERVAL_MS = 250

# 去抖次数：连续 3 次命中才算进入（离开同理）。为什么需要：alt-tab 切到全屏应用时，前台窗口
# 会在几百毫秒内抖几下（桌面 → 目标 → 目标的全屏子窗口），1 次就下结论会让桌宠"先闪一下再藏"，
# 比不隐藏更烦。3 × 250ms ≈ 0.75s，人感上仍是"立刻"，但足以滤掉抖动。
# 传 0 或负数等价于"关掉去抖"（第一次命中就生效）；**有意不夹到 1**：夹了行为完全一样，
# 多一行代码只会让人以为这里做了别的事。
DEBOUNCE_ENTER_COUNT = 3
DEBOUNCE_EXIT_COUNT = 3

# 不算"候选前台窗口"的窗口类名：桌面两兄弟 + 任务栏两兄弟。
#   · 桌面的 Progman / WorkerW 铺满整块屏——不排除就等于"用户一点桌面桌宠就消失"，
#     这是致命误判（比"没隐藏"严重得多）；
#   · 任务栏正常是条状（覆盖率判据本来就挡得住），但"自动隐藏的任务栏被唤出后成为前台窗口"
#     这种形态确实出现过，Windows 自己的 QUNS 判定也把它们排除在外——留着，
#     代价只是两次字符串比较。
SHELL_CLASSES = frozenset((
    "Progman",                  # 桌面（经典形态）
    "WorkerW",                  # 桌面（壁纸宿主，Win10 起常见）
    "Shell_TrayWnd",            # 主任务栏
    "Shell_SecondaryTrayWnd",   # 副屏任务栏
))

# `Win32Probe(api=...)` 的"自动选真后端"哨兵。显式传 None = 我知道这里没有 Win32
# （例如在 Linux 上用假探针跑用例），这与"自动"必须能分开：混成一个值就没法测"没后端"那条路。
_AUTO = object()


class ForegroundWindow(NamedTuple):
    """前台窗口快照（**物理像素**；`right`/`bottom` 是 left+width 语义，与 Win32 RECT 一致）。

    用 NamedTuple 而不是 dict 或带方法的类：它是纯数据，不该有行为；tuple 形状还让
    "探针给了 None" 与 "探针给了信息" 在用例里一眼可分。
    """
    hwnd: int
    left: int
    top: int
    right: int
    bottom: int
    class_name: str = ""
    visible: bool = True


def is_fullscreen(screen_rect, foreground, own_hwnds=(), tolerance_px=FULLSCREEN_TOLERANCE_PX):
    """前台窗口是否**恰好盖住** `screen_rect` 这一块屏（四边都在容差内）。

    参数：
      screen_rect  (left, top, right, bottom)，**物理像素**，right/bottom 是 x+width 语义。
                   传 None（屏幕还没就绪）→ False，不猜。
      foreground   `ForegroundWindow` 或 None（探针读不到 / 没有前台窗口）。只要有
                   hwnd/left/top/right/bottom/class_name/visible 这几个属性即可（鸭子类型）。
      own_hwnds    本进程窗口的句柄集合（int）。**必传**：桌宠自己是置顶窗口，点它就变成
                   前台窗口；不排除的话"点一下自己就藏起来"。
      tolerance_px 容差（px）。负数按 0 处理，见下面注释。

    返回 True 只代表"这块屏此刻被一个全屏应用盖住了"，**不代表**"该藏桌宠"：
    隐藏策略（要不要去抖、只看哪些屏、菜单开关）在 `FullscreenWatcher` 与调用方。

    **纯函数，没有 try/except**：传错形状（例如 own_hwnds 里塞了控件对象）是本仓自己写错，
    按 pet_motion.duration_ms 的口径**让它响亮地抛**——抛在 watcher 里会被记成
    `last_error` 并走安全侧，不会崩，但**不会悄悄当成"不是全屏"**。
    """
    if foreground is None or screen_rect is None:
        return False
    s_left, s_top, s_right, s_bottom = (int(v) for v in screen_rect)
    if s_right - s_left <= 0 or s_bottom - s_top <= 0:
        # 0×0 的"屏幕"是还没初始化 / 时序未到（Qt 在某些时机确实会给 0×0）。
        # 拿它跟同样 0×0 的窗口比会"相等"——那是最坏的一种假阳性，必须先挡掉。
        return False
    if not foreground.visible:
        return False  # 隐藏 / 最小化的窗口盖不住任何东西
    if int(foreground.hwnd) in {int(h) for h in own_hwnds}:
        return False
    if str(foreground.class_name or "") in SHELL_CLASSES:
        return False
    # 负数容差会把 abs() 比较变成**恒假**——等于悄悄关掉整个功能，症状是"从来不隐藏"，
    # 最难查的那种。夹到 0 让它退化成严格相等：失败方向仍然是安全侧。
    tol = max(0, int(tolerance_px))
    return (abs(int(foreground.left) - s_left) <= tol
            and abs(int(foreground.top) - s_top) <= tol
            and abs(int(foreground.right) - s_right) <= tol
            and abs(int(foreground.bottom) - s_bottom) <= tol)


def is_any_fullscreen(screen_rects, foreground, own_hwnds=(),
                      tolerance_px=FULLSCREEN_TOLERANCE_PX):
    """多屏版：**任意一块**屏被盖住就算全屏（桌宠在副屏时，主屏的全屏电影照样该藏）。

    `screen_rects` 为空 = 一块屏都没有 / 屏幕信息还没就绪 → False（安全侧，不猜）。
    """
    if not screen_rects:
        return False
    return any(is_fullscreen(rect, foreground, own_hwnds, tolerance_px)
               for rect in screen_rects)


# ---------------- 第二层：Win32 读数（唯一碰 ctypes 的地方） ----------------

class _Rect(ctypes.Structure):
    """Win32 RECT（四个 LONG）。

    自己定义四个 int32 而不 import ctypes.wintypes：wintypes 在非 Windows 上的行为不值得
    依赖，而本模块要能在**任何**平台上被 import（无 GUI、无 Win32 的 CI 也要跑得动）。
    """
    _fields_ = [("left", ctypes.c_int32), ("top", ctypes.c_int32),
                ("right", ctypes.c_int32), ("bottom", ctypes.c_int32)]


class User32Api:
    """user32 的 ctypes 调用层：**只取数**，不判定、不兜底（兜底在 `Win32Probe`）。

    为什么每个方法都直接抛（不在这里吞异常）：吞在哪一层，就该记在哪一层。这一层只管
    "函数调不通就抛"，由 `Win32Probe` 统一记成 `last_error` —— 出口只有一个，才不会
    "有的错记了、有的错漏了"。

    为什么要钉 argtypes/restype（不是洁癖）：HWND 在 x64 上是**64 位指针**，而不声明
    argtypes 时 ctypes 把 Python int 按 **C int（32 位）**传 —— 句柄高位被截断，
    GetWindowRect 就会失败、或者查到一个不存在的小句柄。这类错在开发机上经常
    "看起来能跑"（被测窗口的句柄恰好很小），换台机器就时灵时不灵。
    """

    def __init__(self, user32=None):
        if user32 is None:                      # None = 用真后端（可能没有，见 _load）
            user32 = self._load()
            if user32 is not None:
                self._declare(user32)
        self._user32 = user32

    @staticmethod
    def _load():
        """真后端：ctypes.windll.user32。非 Windows / 没有 windll 时返回 None（**不抛**）。"""
        try:
            return ctypes.windll.user32
        except (AttributeError, OSError):
            return None

    @staticmethod
    def _declare(user32):
        """给真后端钉上原型（理由见类文档）。只对真后端做——假后端没有 argtypes 可设。"""
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        user32.GetShellWindow.restype = ctypes.c_void_p
        user32.GetWindowRect.argtypes = (ctypes.c_void_p, ctypes.POINTER(_Rect))
        user32.GetWindowRect.restype = ctypes.c_int
        user32.GetClassNameW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int)
        user32.GetClassNameW.restype = ctypes.c_int
        user32.IsWindowVisible.argtypes = (ctypes.c_void_p,)
        user32.IsWindowVisible.restype = ctypes.c_int
        user32.GetWindowThreadProcessId.argtypes = (ctypes.c_void_p,
                                                    ctypes.POINTER(ctypes.c_ulong))
        user32.GetWindowThreadProcessId.restype = ctypes.c_ulong

    def available(self):
        """后端在不在。"不在"不是错误：非 Windows 平台本来就没有 user32。"""
        return self._user32 is not None

    def foreground_hwnd(self):
        hwnd = self._user32.GetForegroundWindow()
        return int(hwnd or 0)                    # NULL → 0（锁屏 / 切换中）

    def shell_hwnd(self):
        return int(self._user32.GetShellWindow() or 0)

    def window_rect(self, hwnd):
        """→ (left, top, right, bottom)；窗口已经消失（GetWindowRect 失败）→ None。"""
        rc = _Rect()
        if not self._user32.GetWindowRect(hwnd, ctypes.byref(rc)):
            return None
        return int(rc.left), int(rc.top), int(rc.right), int(rc.bottom)

    def class_name(self, hwnd):
        """窗口类名；取不到（GetClassNameW 返回 0）→ ""。"""
        buf = ctypes.create_unicode_buffer(256)
        if not self._user32.GetClassNameW(hwnd, buf, 256):
            return ""
        return str(buf.value)

    def is_visible(self, hwnd):
        return bool(self._user32.IsWindowVisible(hwnd))

    def window_pid(self, hwnd):
        """窗口所属进程 id；取不到（返回 0）→ None。"""
        pid = ctypes.c_ulong(0)
        if not self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)):
            return None
        return int(pid.value)


def _report(cb, exc):
    """把异常转手给调用方的回调（探针与状态层的**唯一**上报出口）。

    回调自己失败就到此为止：它是调用方给的（接线路点建议挂 pet_log.log_throttled），
    失败时无处可记——再抛出去只会把"记录失败"变成"主路径失败"（与 pet_log.guard_slot
    同口径：日志设施自身出错不许影响主流程）。
    """
    if cb is None:
        return
    try:
        cb(exc)
    except Exception:  # noqa: BLE001
        pass


class Win32Probe:
    """前台窗口探针：`probe()` / `read()` → `ForegroundWindow | None`。

    它做两处"读完立刻就能定"的筛除，理由都是**这些窗口根本不是"用户正在用的应用"**：
      * 桌面本身（GetShellWindow 的句柄）：点桌面时它就是前台窗口，矩形铺满整屏；
      * 本进程自己的窗口（按 pid）：桌宠置顶，点一下就变前台；按 pid 排除比调用方传进来的
        `own_hwnds` **快照**更稳（对话框 / 托盘窗口的句柄会变）。
    其余筛除（类名、可见性、覆盖率）留在纯函数里——那里能直接测，不必造 ctypes。

    读数失败 → None（安全侧），异常记进 `last_error` / `fail_count`，并转手 `on_error`。
    **不能让它抛**：调用点是 QTimer 槽，槽里抛异常会走 excepthook 弹模态框，
    用户看到的是"桌宠卡住了"。
    """

    def __init__(self, api=_AUTO, on_error=None):
        self.last_error = None
        self.fail_count = 0
        self._on_error = on_error
        if api is _AUTO:
            try:
                api = User32Api()
            except Exception as e:  # noqa: BLE001
                # 后端连**构造**都失败（ctypes 被裁 / DLL 缺失）：可选能力不该把桌宠启动带崩，
                # 但也不能装没事——记下来，由 on_error 出声。
                self.last_error = e
                self.fail_count += 1
                _report(self._on_error, e)
                api = None
        self._api = api

    def __call__(self):
        return self.read()

    def read(self):
        api = self._api
        if api is None:
            return None   # 显式关闭 / 构造就失败：**不是错误**，别每拍记一条失败
        try:
            if not api.available():
                # 没有后端（非 Windows）：同样不是错误。放在 try 里是因为"有没有后端"这件事
                # 本身也是问后端要的——它要是也抛，那必须走下面的记录路径，而不是漏出去。
                return None
            hwnd = api.foreground_hwnd()
            if not hwnd:
                return None                          # 锁屏 / 切换窗口途中：没有前台窗口
            if hwnd == api.shell_hwnd():
                return None                          # 桌面本身（点桌面时它会成为前台窗口）
            pid = api.window_pid(hwnd)
            if pid is not None and pid == os.getpid():
                return None                          # 自己（桌宠 / 设置窗 / 托盘菜单）
            rect = api.window_rect(hwnd)
            if rect is None:
                return None                          # 窗口在读数途中消失（alt-tab 常态）
            left, top, right, bottom = rect
            return ForegroundWindow(hwnd=hwnd, left=left, top=top,
                                    right=right, bottom=bottom,
                                    class_name=api.class_name(hwnd),
                                    visible=api.is_visible(hwnd))
        except Exception as e:  # noqa: BLE001
            # **宽口径是有意的**：这里的错误域是 ctypes / 系统调用（ArgumentError、OSError、
            # AttributeError、假后端给的任何东西），穷举不完；而失败方向是安全的
            # （当不成全屏 = 不藏桌宠）。窄口径的唯一效果是"某类错在用户机器上炸成弹框"。
            # 代价用**记录**补回来：last_error / fail_count / on_error，一条都不静默。
            self.last_error = e
            self.fail_count += 1
            _report(self._on_error, e)
            return None


# ---------------- 第三层：状态（节流 + 去抖） ----------------

def _resolve(value):
    """值或可调用物 → 值。

    屏幕布局与自身句柄**都会变**，所以两者都允许传"每次现问"的可调用物：
    `screen_rects=lambda: [...]`、`own_hwnds=lambda: {int(win.winId())}`。
    固定值当然也行——由调用方决定要不要订阅"屏幕增删"。
    """
    return value() if callable(value) else value


class FullscreenWatcher:
    """全屏状态机：**节流**（多久查一次）+ **去抖**（连续几次算数）+ **安全侧**。

    为什么不把节流放进调用方的 QTimer：那是"多久**调用**一次"，与"多久**查**一次"是两件事
    （调用方可能因为拖动 / 动画把 tick 提到 16ms，而查询 250ms 一次就够）。两件事写在一处，
    改一个必然连带另一个——本仓"同一个决定多份实现"的老病。

    用法（接线路点见报告）::

        w = FullscreenWatcher(probe=Win32Probe(),
                              screen_rects=lambda: [物理矩形…],
                              own_hwnds=lambda: {int(self.winId())},
                              on_error=lambda e: log_throttled("全屏探针", repr(e)))
        # QTimer tick（建议 250ms；更快也不会多查）：
        now_fs = w.poll()
        if now_fs != self._hidden_for_fullscreen:
            ...  # 藏 / 显示，由调用方决定（本模块不碰 Qt、不碰窗口）

    返回值是**状态**，不是"这一拍有没有变化"——要看变化就自己记着上一次，因为
    "该不该藏"是产品决定，不是判据决定。
    """

    def __init__(self, probe=None, screen_rects=(), own_hwnds=(), *,
                 tolerance_px=FULLSCREEN_TOLERANCE_PX,
                 enter_count=DEBOUNCE_ENTER_COUNT, exit_count=DEBOUNCE_EXIT_COUNT,
                 min_interval_ms=POLL_MIN_INTERVAL_MS, now=None, on_error=None):
        self.probe = probe if probe is not None else Win32Probe()
        # 这两个是**可重设的普通属性**（屏幕布局变了直接赋值），不是隐藏状态。
        self.screen_rects = screen_rects
        self.own_hwnds = own_hwnds
        self._tol = tolerance_px
        self._enter = int(enter_count)
        self._exit = int(exit_count)
        # ≥ POLL_MIN_INTERVAL_MS：调用方可以更慢，不允许更快（理由见常量注释）。
        self._min_ms = max(POLL_MIN_INTERVAL_MS, int(min_interval_ms))
        self._now = now if now is not None else time.monotonic
        self._on_error = on_error
        self.fullscreen = False
        self.probes = 0        # 真查询次数：让"节流"能被**结构断言**，不必靠墙钟
        self.fail_count = 0
        self.last_error = None
        self._hits = 0
        self._misses = 0
        self._last_poll = None
        self._last_probe_error = None

    def poll(self, now=None):
        """查一次（或在节流窗口内**不查**）→ 去抖后的当前结论（True = 全屏）。"""
        t = float(self._now() if now is None else now)
        last = self._last_poll
        if last is not None and (t - last) * 1000.0 < self._min_ms:
            # 节流窗口内：不查、不改状态、**不动计数器**——否则调用方 tick 越快，
            # 去抖越早成立（等于把 "N 次" 变成 "N 次 × 未知间隔"，判据就散了）。
            return self.fullscreen
        # 先记时间再查：探针坏了也占住这个窗口，否则高频 tick 会把
        # "查 → 抛 → 查 → 抛" 打成死循环（每 16ms 一次系统调用风暴）。
        self._last_poll = t
        self.probes += 1
        if self._sample():
            self._hits += 1
            self._misses = 0
            if self._hits >= self._enter:
                self.fullscreen = True
        else:
            self._misses += 1
            self._hits = 0
            if self._misses >= self._exit:
                self.fullscreen = False
        return self.fullscreen

    def reset(self):
        """归位：状态清成"不是全屏"、计数清零、**下一拍立刻真查**（不受上一拍的节流窗口约束）。

        什么时候用：菜单把功能关掉再打开、屏幕布局变了、桌宠刚被用户手动叫出来。
        留着旧的去抖计数会让"重新打开的功能"头几拍拿旧账下结论。
        """
        self.fullscreen = False
        self._hits = 0
        self._misses = 0
        self._last_poll = None

    def _sample(self):
        """一次取样 → 是否全屏。**任何**失败都折成 False（安全侧：判定失败 = 不当全屏）。"""
        try:
            rects = _resolve(self.screen_rects)
            own = _resolve(self.own_hwnds)
            fg = self.probe()
            self._sync_probe_error()
            return is_any_fullscreen(rects, fg, own, self._tol)
        except Exception as e:  # noqa: BLE001
            # 宽口径：注入的探针 / 屏幕列表是调用方的代码，形状错什么都可能抛；
            # 失败方向安全（不藏）。但一条不落地记下来，并转手 on_error。
            self.last_error = e
            self.fail_count += 1
            _report(self._on_error, e)
            return False

    def _sync_probe_error(self):
        """把探针内部记下的错误搬到自己身上。

        为什么需要：`Win32Probe` 按契约**不抛**（抛出去就是用户面前的弹框），错误只落在它
        自己的 `last_error` 上。watcher 是**唯一的错误出口**——不搬过来，那类错误就真的
        静默了（而它恰恰是真实用户机器上最可能发生的那类：ctypes 调不通）。
        """
        err = getattr(self.probe, "last_error", None)
        if err is not None and err is not self._last_probe_error:
            self._last_probe_error = err
            self.last_error = err
            self.fail_count += 1
            _report(self._on_error, err)
