# -*- coding: utf-8 -*-
"""pet_windows（v2.11.0 第 11 轮 · W1-a）判据：全屏判定 / 容差 / 排除 / 多屏 / 去抖 / 节流。

**用例永远不读真桌面**：除了一条"真后端读数形状合法"的契约冒烟（它只看返回形状，与"此刻
开着什么窗口"无关），其余每条都注入假探针或假 user32——否则用例会随开发者此刻的窗口红绿，
那是最难查的一类不稳定。

每条用例的 docstring 都写了"拿掉哪一行会红"。这些不是自述：报告里的逆向验证是在 %TEMP%
**影子副本**里逐条做的（铁律 6：变异不许原地改真仓）。
"""
import ast
import io
import os
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest  # noqa: E402

import pet_windows as pw  # noqa: E402

# 物理像素（与探针读数同一坐标系）。两块屏：B 的原点不是 0 —— 专门用来钉"用传入的矩形"，
# 而不是"假设主屏从 (0,0) 开始"。
SCREEN_A = (0, 0, 1920, 1080)
SCREEN_B = (1920, 0, 3840, 1080)


def _fg(rect, hwnd=101, cls="Chrome_WidgetWin_1", visible=True):
    """造一个前台窗口快照（与探针给的东西同一形状）。"""
    left, top, right, bottom = rect
    return pw.ForegroundWindow(hwnd=hwnd, left=left, top=top, right=right,
                               bottom=bottom, class_name=cls, visible=visible)


def _const_probe(info, calls=None):
    """固定答案的探针；calls 给了就顺手数调用次数（节流的结构断言用它，不靠墙钟）。"""
    def _probe():
        if calls is not None:
            calls.append(1)
        return info
    return _probe


def _watcher(probe, **kw):
    kw.setdefault("screen_rects", [SCREEN_A])
    return pw.FullscreenWatcher(probe=probe, **kw)


# ---------------- 第一组：纯判据（覆盖 / 容差 / 排除 / 多屏） ----------------

def test_恰好铺满整块屏就是全屏():
    """正向控制：判据不是恒 False。
    能真失败：把最后四行的「<= tol」写成永不成立（或把 visible 判断取反）→ 这里红。
    """
    assert pw.is_fullscreen(SCREEN_A, _fg(SCREEN_A)) is True
    # 类名不在排除表里的（播放器 / 游戏）同样算：判据不认"白名单应用"，只认矩形
    assert pw.is_fullscreen(SCREEN_A, _fg(SCREEN_A, cls="VLC video output")) is True


def test_容差内_偏一两像素仍算全屏():
    """能真失败：把 FULLSCREEN_TOLERANCE_PX 改成 0 → 偏 1px 那几条立刻红。"""
    left, top, right, bottom = SCREEN_A
    for dx, dy in ((1, 0), (0, 1), (2, 2), (-2, -2)):
        rect = (left + dx, top + dy, right + dx, bottom + dy)
        assert pw.is_fullscreen(SCREEN_A, _fg(rect)) is True, rect


def test_容差外_偏三像素不算全屏():
    """能真失败：把 FULLSCREEN_TOLERANCE_PX 抬到 3 或 8 → 这里红。"""
    left, top, right, bottom = SCREEN_A
    for dx in (3, -3):
        rect = (left + dx, top, right + dx, bottom)
        assert pw.is_fullscreen(SCREEN_A, _fg(rect)) is False, rect


def test_比屏幕大一圈的窗口不算全屏():
    """最大化窗口的真实形态：四边各外扩 8px（Windows 的 resize border），见模块文档。

    能真失败：把「abs(right - s_right) <= tol」与「abs(bottom - s_bottom) <= tol」两条去掉
    （只留"覆盖"判据）→ 外扩的窗口会被判成全屏 → 这里红。
    """
    left, top, right, bottom = SCREEN_A
    maximized = (left - 8, top - 8, right + 8, bottom + 8)
    assert pw.is_fullscreen(SCREEN_A, _fg(maximized)) is False
    # 横跨两块屏的窗口对哪一块都是"大一圈"
    assert pw.is_fullscreen(SCREEN_A, _fg((0, 0, 3840, 1080))) is False


@pytest.mark.parametrize("cls", ["Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"])
def test_桌面与任务栏即使铺满也不算全屏(cls):
    """能真失败：把「str(foreground.class_name or "") in SHELL_CLASSES」那一行拿掉，
    并从 SHELL_CLASSES 里删掉这一类 → 这里红（两条都要动，这是刻意的双保险：
    删名单条目 vs 删判据，任一都该被抓住）。
    """
    assert pw.is_fullscreen(SCREEN_A, _fg(SCREEN_A, hwnd=7, cls=cls)) is False


def test_自己的窗口即使铺满也不算全屏():
    """点桌宠自己 → 它变成前台窗口；不排除就等于"点一下自己就藏起来"。

    能真失败：把「int(foreground.hwnd) in {int(h) for h in own_hwnds}」那一行改成
    if False → 这里红。
    """
    assert pw.is_fullscreen(SCREEN_A, _fg(SCREEN_A, hwnd=4242), own_hwnds={4242}) is False
    # 只排除**在名单里的**：同一个矩形、句柄不在名单里 → 照样算全屏
    assert pw.is_fullscreen(SCREEN_A, _fg(SCREEN_A, hwnd=4242), own_hwnds={1, 2}) is True


def test_前台窗口为_None_或不可见或没有屏幕时一律不是全屏():
    """安全侧的三条"判不了"。
    能真失败：把「if foreground is None or screen_rect is None」或「if not visible」拿掉 → 红。
    """
    assert pw.is_fullscreen(SCREEN_A, None) is False
    assert pw.is_fullscreen(None, _fg(SCREEN_A)) is False
    assert pw.is_fullscreen(SCREEN_A, _fg(SCREEN_A, visible=False)) is False


def test_零面积的屏幕不算全屏():
    """0×0 的"屏幕"与 0×0 的窗口会"相等"——那是最坏的假阳性。
    能真失败：把「s_right - s_left <= 0 or s_bottom - s_top <= 0」那条拿掉 → 这里红。
    """
    assert pw.is_fullscreen((0, 0, 0, 0), _fg((0, 0, 0, 0))) is False
    assert pw.is_fullscreen((100, 100, 100, 500), _fg((100, 100, 100, 500))) is False


def test_容差为负按_0_处理_也就是严格相等():
    """负数容差若不夹到 0，abs(d) <= -5 恒假 → 功能**静默失效**（从来不隐藏）。
    能真失败：把「tol = max(0, int(tolerance_px))」里的 max(0, ...) 拿掉 → 这里红。
    """
    assert pw.is_fullscreen(SCREEN_A, _fg(SCREEN_A), tolerance_px=-5) is True
    left, top, right, bottom = SCREEN_A
    assert pw.is_fullscreen(SCREEN_A, _fg((left + 1, top, right, bottom)),
                            tolerance_px=-5) is False


def test_多屏_同一前台窗口逐屏判定且任意一块就算全屏():
    """screen_rect 是**传进来的**：同一个窗口在 B 屏全屏、在 A 屏不是。
    能真失败：把 is_any_fullscreen 的 any 换成 all → 这里红；把 B 屏原点当 0 算 → 也红。
    """
    win_b = _fg(SCREEN_B)
    assert pw.is_fullscreen(SCREEN_B, win_b) is True
    assert pw.is_fullscreen(SCREEN_A, win_b) is False
    assert pw.is_any_fullscreen([SCREEN_A, SCREEN_B], win_b) is True
    assert pw.is_any_fullscreen([SCREEN_A], win_b) is False
    assert pw.is_any_fullscreen([], win_b) is False      # 一块屏都没有 = 判不了 = 安全侧
    # 桌宠自己的句柄在排除名单里，但前台窗口不是它 → 该算的全屏照样算
    assert pw.is_any_fullscreen([SCREEN_B], win_b, own_hwnds={999}) is True


# ---------------- 第二组：探针（筛除 + 安全侧 + ctypes 映射） ----------------

class _FakeApi:
    """假的 Win32 调用层：测探针的筛除逻辑，完全不碰 ctypes。"""

    def __init__(self, hwnd=101, rect=(0, 0, 1920, 1080), cls="Chrome_WidgetWin_1",
                 visible=True, pid=None, shell=900, available=True, error=None, rect_ok=1):
        self._hwnd = hwnd
        self._rect = rect
        self._cls = cls
        self._visible = visible
        self._pid = pid
        self._shell = shell
        self._available = available
        self._error = error
        self._rect_ok = rect_ok

    def _boom(self):
        if self._error is not None:
            raise self._error

    def available(self):
        return self._available

    def foreground_hwnd(self):
        self._boom()
        return self._hwnd

    def shell_hwnd(self):
        self._boom()
        return self._shell

    def window_rect(self, hwnd):
        self._boom()
        return self._rect if self._rect_ok else None

    def class_name(self, hwnd):
        self._boom()
        return self._cls

    def is_visible(self, hwnd):
        self._boom()
        return self._visible

    def window_pid(self, hwnd):
        self._boom()
        return self._pid


def test_探针把读数拼成前台窗口快照():
    """探针只**转述**读数，不做判定（"不可见不算全屏"是纯函数的活）。
    能真失败：把 visible=api.is_visible(hwnd) 写成 visible=True → 这里红。
    """
    probe = pw.Win32Probe(api=_FakeApi(hwnd=77, rect=(0, 0, 1920, 1080),
                                       cls="GameWindow", visible=False, pid=1234))
    info = probe.read()
    assert isinstance(info, pw.ForegroundWindow)
    assert (info.hwnd, info.left, info.top, info.right, info.bottom) == (77, 0, 0, 1920, 1080)
    assert info.class_name == "GameWindow"
    assert info.visible is False
    assert probe.fail_count == 0


def test_探针跳过桌面本身_点桌面不会变成全屏():
    """能真失败：把「if hwnd == api.shell_hwnd(): return None」那条拿掉 → 探针会给出
    Progman 的快照（矩形铺满整屏）→ 这里红。
    """
    probe = pw.Win32Probe(api=_FakeApi(hwnd=900, shell=900))
    assert probe.read() is None
    assert probe.fail_count == 0      # 这是正常形态，不是错误，不许记成失败


def test_探针跳过本进程自己的窗口():
    """对话框 / 托盘窗口的句柄会变，按 pid 排除比调用方的句柄快照稳。
    能真失败：把「if pid is not None and pid == os.getpid()」那两行拿掉 → 这里红。
    """
    assert pw.Win32Probe(api=_FakeApi(hwnd=500, pid=os.getpid())).read() is None
    assert pw.Win32Probe(api=_FakeApi(hwnd=500, pid=os.getpid())).fail_count == 0
    # 别人的 pid → 照常转述（别把"同进程"写成"任何 pid 都排除"）
    assert pw.Win32Probe(api=_FakeApi(hwnd=500, pid=os.getpid() + 1)).read() is not None
    # 取不到 pid（GetWindowThreadProcessId 返回 0）→ 不排除，照常转述
    assert pw.Win32Probe(api=_FakeApi(hwnd=500, pid=None)).read() is not None


def test_没有前台窗口时给_None():
    """锁屏 / 切换窗口途中 GetForegroundWindow 返回 NULL。
    能真失败：把「if not hwnd: return None」拿掉 → 会拼出一个 hwnd=0 的快照 → 这里红。
    """
    probe = pw.Win32Probe(api=_FakeApi(hwnd=0))
    assert probe.read() is None
    assert probe.fail_count == 0


def test_窗口在读数途中消失给_None_且不算错误():
    """alt-tab 常态：GetWindowRect 失败（窗口已销毁）。它必须是"没有信息"，不是"出错"。
    能真失败：把「if rect is None: return None」拿掉 → 解包 None 抛异常 → fail_count 变 1 → 红。
    """
    probe = pw.Win32Probe(api=_FakeApi(rect_ok=0))
    assert probe.read() is None
    assert probe.fail_count == 0


def test_显式没有后端时给_None_且不算错误():
    """非 Windows / 显式关闭："没有这个能力" ≠ "出错"，不许每拍记一条失败刷屏。
    能真失败：把「if api is None: return None」拿掉 → 立刻 AttributeError → 红。
    """
    probe = pw.Win32Probe(api=None)
    assert probe.read() is None
    assert probe.last_error is None
    assert probe.fail_count == 0


def test_后端抛错时给_None_并记下错误且转手_on_error():
    """安全侧 + 不静默：判定失败=不当全屏，但错误必须留下痕迹。
    能真失败：把 read() 的 except 分支里「return None」改成 raise → 用例炸成异常 → 红。
    """
    seen = []
    boom = RuntimeError("user32 坏了")
    probe = pw.Win32Probe(api=_FakeApi(error=boom), on_error=seen.append)
    assert probe.read() is None
    assert probe.last_error is boom
    assert probe.fail_count == 1
    assert seen == [boom]


def test_后端连构造都失败也不把探针带崩(monkeypatch):
    """ctypes 被裁 / DLL 缺失：可选能力不该把桌宠启动带崩，但也不许装没事。
    能真失败：把 Win32Probe.__init__ 里那段 try/except 拿掉 → 构造直接抛 → 红。
    """
    class _BoomUser32Api:
        def __init__(self, *a, **k):
            raise OSError("没有 windll")

    monkeypatch.setattr(pw, "User32Api", _BoomUser32Api)
    seen = []
    probe = pw.Win32Probe(on_error=seen.append)
    assert probe.read() is None
    assert isinstance(probe.last_error, OSError)
    assert probe.fail_count == 1
    assert len(seen) == 1


def test_真_ctypes_层抛错时探针不把异常漏给调用方():
    """user32 是个没有任何方法的对象（= DLL 调不通的抽象形态）：read() 必须给 None。
    漏出去就是 QTimer 槽里的一行 excepthook → 用户面前的模态弹框。
    能真失败：把 read() 的 except 分支「return None」改成 raise → 红。
    """
    api = pw.User32Api(user32=object())
    assert api.available() is True            # 后端"在"，但方法调不通
    probe = pw.Win32Probe(api=api)
    assert probe.read() is None
    assert isinstance(probe.last_error, AttributeError)
    assert probe.fail_count == 1


def _fill(ref, pairs):
    """往 ctypes.byref(x) 指着的 x 里写值。

    CPython 的 CArgObject 把被指实例放在 _obj 上（byref 的既定形态）。万一哪天变了，
    这里先炸出来——比"假后端悄悄写不进去、用例绿着"好。
    """
    target = getattr(ref, "_obj", None)
    assert target is not None, "ctypes.byref 的 _obj 形状变了 → 假后端要重写"
    for name, value in pairs:
        setattr(target, name, value)


class _FakeUser32:
    """假的 user32（ctypes 那一层）：验 User32Api 的 marshalling。"""

    def __init__(self, hwnd=101, rect=(10, 20, 1930, 1100), cls="Chrome_WidgetWin_1",
                 visible=1, pid=4242, shell=900, rect_ok=1, cls_ok=1, pid_ok=1):
        self._hwnd = hwnd
        self._rect = rect
        self._cls = cls
        self._visible = visible
        self._pid = pid
        self._shell = shell
        self._rect_ok = rect_ok
        self._cls_ok = cls_ok
        self._pid_ok = pid_ok

    def GetForegroundWindow(self):
        return self._hwnd

    def GetShellWindow(self):
        return self._shell

    def GetWindowRect(self, hwnd, ref):
        left, top, right, bottom = self._rect
        _fill(ref, [("left", left), ("top", top), ("right", right), ("bottom", bottom)])
        return self._rect_ok

    def GetClassNameW(self, hwnd, buf, size):
        if not self._cls_ok:
            return 0
        buf.value = self._cls
        return len(self._cls)

    def IsWindowVisible(self, hwnd):
        return self._visible

    def GetWindowThreadProcessId(self, hwnd, ref):
        _fill(ref, [("value", self._pid)])
        return 1 if self._pid_ok else 0


def test_User32Api_把_ctypes_读数映射成元组与标量():
    """ctypes 那一层只做形状映射；失败形态（返回 0）一律给 None / ""。
    能真失败：把 window_rect 的「if not GetWindowRect(...)」判断拿掉 → 返回值 0 的失败形态
    会被当成成功（给出 (0,0,0,0)）→ 这里红。
    """
    api = pw.User32Api(user32=_FakeUser32(rect=(10, 20, 1930, 1100), cls="GameWin",
                                          visible=1, pid=4242))
    assert api.available() is True
    assert api.foreground_hwnd() == 101
    assert api.shell_hwnd() == 900
    assert api.window_rect(101) == (10, 20, 1930, 1100)
    assert api.class_name(101) == "GameWin"
    assert api.is_visible(101) is True
    assert api.window_pid(101) == 4242
    # 三种"取不到"的失败形态
    dead = pw.User32Api(user32=_FakeUser32(rect_ok=0, cls_ok=0, pid_ok=0))
    assert dead.window_rect(1) is None
    assert dead.class_name(1) == ""
    assert dead.window_pid(1) is None


def test_真后端读一次_形状合法且构造不抛():
    """契约冒烟：真 ctypes 后端在**本机**读一次，要么 None、要么快照。

    它**不看内容**（不关心此刻前台窗口是谁），所以与"开发者开着什么窗口"无关；
    它抓的是"原型声明错了 / 后端构造抛了"这类会让整条链路在用户机器上哑掉的问题。
    """
    probe = pw.Win32Probe()
    info = probe.read()
    assert info is None or isinstance(info, pw.ForegroundWindow)


# ---------------- 第三组：状态层（去抖 + 节流 + 安全侧） ----------------

def test_去抖_连续_N_减_1_次还不算进入_第_N_次才进入():
    """能真失败：把「if self._hits >= self._enter」的 >= 改成 > → 第 3 次仍 False → 红。"""
    w = _watcher(_const_probe(_fg(SCREEN_A)))
    assert w.poll(now=0.0) is False
    assert w.poll(now=0.25) is False
    assert w.poll(now=0.50) is True


def test_离开全屏同样要连续_N_次():
    """能真失败：把「if self._misses >= self._exit」的 >= 改成 > → 第 3 次落空仍 True → 红。"""
    w = _watcher(_const_probe(_fg(SCREEN_A)))
    for t in (0.0, 0.25, 0.50):
        w.poll(now=t)
    assert w.fullscreen is True
    w.probe = _const_probe(None)
    assert w.poll(now=0.75) is True      # 落空 1 次：不立刻退出（防 alt-tab 闪）
    assert w.poll(now=1.00) is True
    assert w.poll(now=1.25) is False


def test_中途闪一下不算进入():
    """能真失败：把落空分支里的「self._hits = 0」拿掉 → 累计命中 3 次就进入 → 这里红。"""
    seq = [_fg(SCREEN_A), _fg(SCREEN_A), None, _fg(SCREEN_A), _fg(SCREEN_A)]
    it = iter(seq)
    w = _watcher(lambda: next(it))
    outs = [w.poll(now=i * 0.25) for i in range(len(seq))]
    assert outs == [False, False, False, False, False]


def test_进入后交替抖动不会累计成离开():
    """能真失败：把命中分支里的「self._misses = 0」拿掉 → 三次落空累计到 N → 这里红。"""
    state = {"fs": _fg(SCREEN_A)}
    w = _watcher(lambda: state["fs"])
    for t in (0.0, 0.25, 0.50):
        w.poll(now=t)
    assert w.fullscreen is True
    t = 0.75
    for _ in range(3):                       # 落空 → 命中 → 落空 → 命中 → 落空
        state["fs"] = None
        assert w.poll(now=t) is True
        t += 0.25
        state["fs"] = _fg(SCREEN_A)
        assert w.poll(now=t) is True
        t += 0.25
    assert w.fullscreen is True


def test_节流_窗口内连打十次只查一次():
    """能真失败：把 poll 里那段 `(t - last) * 1000.0 < self._min_ms` 的提前返回拿掉 → 这里红；
    把 < 改成 <= → 恰好 250ms 的那次不再查（probes 停在 1）→ 也红。
    """
    calls = []
    w = _watcher(_const_probe(_fg(SCREEN_A), calls))
    for i in range(10):
        w.poll(now=i * 0.01)                 # 100ms 内连打 10 次：只有第一次真查
    assert len(calls) == 1
    assert w.probes == 1
    assert w.fullscreen is False             # 去抖要 3 次**真查询**，不是 3 次调用
    w.poll(now=0.25)                         # 间隔恰好 250ms：算"过了窗口"
    assert w.probes == 2
    assert len(calls) == 2


def test_节流下限永远是_250_毫秒():
    """调用方传更小的间隔（0 是最常见的写错）不许真的生效。
    能真失败：把「self._min_ms = max(POLL_MIN_INTERVAL_MS, int(min_interval_ms))」的
    max 拆掉 → 传 0 之后 100ms 就再查一次 → 这里红。
    """
    calls = []
    w = _watcher(_const_probe(_fg(SCREEN_A), calls), min_interval_ms=0)
    w.poll(now=0.0)
    w.poll(now=0.10)
    assert len(calls) == 1
    # 传更大的值照常生效（允许更慢）
    slower = _watcher(_const_probe(_fg(SCREEN_A), calls), min_interval_ms=2000)
    slower.poll(now=0.0)
    slower.poll(now=1.0)
    assert slower.probes == 1


def test_判定失败算一次查询并占住节流窗口():
    """探针坏了不许被高频 tick 打成"查-抛-查-抛"风暴：**失败的那一拍同样占住**节流窗口。

    判据 = 探针**被真的调用了几次**（不是只看 watcher.probes 这个自报数）：250ms 窗口内
    连打 25 拍，探针只能被调 1 次；越过窗口后照常再查（否则"只查一次"可能只是永远不查）。

    能真失败（这个配方是**真的**，在 %TEMP% 影子副本上逐条实测过）：
      · 把 `self._last_poll = t` 挪进 `if self._sample():` 的成功分支（= 失败不占窗口）→
        第二拍立刻再查 → calls 变 2 → 红；
      · 整行删掉 → 同上，红。
      · ⚠ **不要**再用旧注释里那个配方（"挪到 _sample() 之后"）：`_sample()` 自己把异常
        吞成 False 返回，那一行挪到它后面（同一层、仍无条件执行）**照样执行** → 不变红
        （找茬 #5 实测，旧配方是假的）。要红就必须让"失败"走进"不记时间"的分支。
    """
    calls = []

    def _boom():
        calls.append(1)
        raise RuntimeError("坏了")

    w = _watcher(_boom)
    assert w.poll(now=0.0) is False
    for i in range(1, 25):                   # 250ms 窗口内每 10ms 一拍，共 24 拍
        assert w.poll(now=i * 0.01) is False
    assert len(calls) == 1, "节流窗口内探针被调了 %d 次（判定失败的那一拍没占住窗口）" % len(calls)
    assert w.probes == 1
    assert w.fail_count == 1
    assert isinstance(w.last_error, RuntimeError)
    # 越过窗口之后照常再查：证明上面"只查一次"是节流，不是"永远不查"
    assert w.poll(now=0.25) is False
    assert len(calls) == 2 and w.probes == 2
    assert w.fail_count == 2 and isinstance(w.last_error, RuntimeError)


def test_探针内部失败会搬到_watcher_上并转手_on_error():
    """Win32Probe 按契约不抛，错误只落在它自己的 last_error 上；watcher 是**唯一出口**。
    能真失败：把 _sample 里那行「self._sync_probe_error()」拿掉 → watcher 的 fail_count
    永远是 0、on_error 一次都不响 → 这里红。
    """
    seen = []
    boom = RuntimeError("user32 坏了")
    probe = pw.Win32Probe(api=_FakeApi(error=boom))
    w = _watcher(probe, on_error=seen.append)
    assert w.poll(now=0.0) is False
    assert w.last_error is boom
    assert w.fail_count == 1
    assert seen == [boom]
    # 同一个错误对象不重复上报（每拍都记就是刷屏）
    w.poll(now=0.25)
    assert w.fail_count == 1
    assert seen == [boom]


def test_reset_之后状态归位且下一拍立刻真查():
    """能真失败：把 reset 里的「self._last_poll = None」拿掉 → 下一拍被节流挡住 → 红。"""
    calls = []
    w = _watcher(_const_probe(_fg(SCREEN_A), calls))
    for t in (0.0, 0.25, 0.50):
        w.poll(now=t)
    assert w.fullscreen is True
    assert w.probes == 3
    w.reset()
    assert w.fullscreen is False
    w.poll(now=0.51)                         # 距上一拍只有 10ms；归位后必须立刻查
    assert w.probes == 4
    assert len(calls) == 4


def test_屏幕与句柄可以是每次现问的可调用物():
    """屏幕增删 / 句柄变化时不必重造 watcher。
    能真失败：把 _resolve 的「value() if callable(value) else value」改成直接返回 value
    → 拿到的是 lambda，解包失败 → 这里红。
    """
    screens = {"rects": [SCREEN_A]}
    own = {"hwnds": set()}
    info = _fg(SCREEN_B)
    w = pw.FullscreenWatcher(probe=lambda: info,
                             screen_rects=lambda: screens["rects"],
                             own_hwnds=lambda: own["hwnds"],
                             enter_count=1, exit_count=1)
    assert w.poll(now=0.0) is False          # B 屏的窗口，此刻只认 A 屏
    screens["rects"] = [SCREEN_A, SCREEN_B]
    assert w.poll(now=0.25) is True          # 现问的屏幕列表生效了
    own["hwnds"] = {info.hwnd}
    assert w.poll(now=0.50) is False         # 现问的排除名单生效了


def test_去抖次数传_1_等于关掉去抖():
    """写 0 / 负数也是同一个行为（有意不夹到 1：夹了行为完全一样，多一行只会骗人）。"""
    for n in (1, 0, -3):
        w = _watcher(_const_probe(_fg(SCREEN_A)), enter_count=n, exit_count=n)
        assert w.poll(now=0.0) is True, n
        w.probe = _const_probe(None)
        assert w.poll(now=0.25) is False, n


# ---------------- 第四组：结构约束（无 Qt / 只用标准库） ----------------

def test_源码只导入标准库或本仓模块():
    """W1-a 硬约束：不引第三方依赖（ctypes 就够），也不许把 Qt 拖进来。
    能真失败：在 pet_windows.py 里加 from PySide6.QtWidgets import QDialog（或
    import pygetwindow / import win32gui）→ 立刻红。
    """
    src = io.open(os.path.join(ROOT, "pet_windows.py"), encoding="utf-8").read()
    tops = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            tops.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                tops.add(node.module.split(".")[0])
    local = {os.path.splitext(n)[0] for n in os.listdir(ROOT) if n.endswith(".py")}
    third_party = sorted(t for t in tops
                         if t not in sys.stdlib_module_names and t not in local)
    assert third_party == [], "pet_windows 只许用标准库：%r" % (third_party,)
    assert "PySide6" not in tops and "PyQt6" not in tops


def test_模块能在没有_Qt_的进程里被_import():
    """干净解释器里 import 它，PySide6 / PyQt 一个都不许被拉进来。

    这是"无 GUI 环境能 import"的**直接证据**：静态扫源码只看得见直接 import，
    看不见"它 import 的某个模块 import 了 Qt"。
    能真失败：pet_windows.py 里加 from PySide6.QtWidgets import QDialog → 立刻红。
    """
    code = ("import sys; sys.path.insert(0, %r); import pet_windows; "
            "bad = sorted({m.split('.')[0] for m in sys.modules "
            "if m.split('.')[0] in ('PySide6', 'PyQt5', 'PyQt6')}); "
            "print('QT=', bad)" % ROOT)
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    proc = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True,
                          timeout=180, env=env, cwd=ROOT)
    out = proc.stdout.decode("utf-8", "replace").strip()
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-800:]
    assert out.endswith("QT= []"), "pet_windows 把 Qt 拉进来了：%s" % out
