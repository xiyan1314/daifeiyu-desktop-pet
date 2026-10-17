# -*- coding: utf-8 -*-
"""v2.11.0 第 11 轮**产品接线层**的判据（找茬 #4/#9 · 质量 #3/#8）。

为什么单独一个文件：判据分两层——
  · 纯逻辑层（pet_windows / pet_notify / pet_time_mood / pet_backup / pet_guard）已经各有
    自己的测试文件，钉的是"判据本身对不对"；
  · 本文件钉的是**接线**：这几块判定真的被接进桌宠 / main.run 了吗？接错了（该退不退、
    默认值翻了、失败也算一次重启）纯逻辑层一条都不会红。

覆盖的五条回执 / 守护路径
------------------------
1. 桌宠._notify 的三种组合：开关关 → 气泡；notify 返回 False → 退回气泡；
   notify 返回 True → **也补气泡**（v2.11.0 修复后的口径：托盘接受 ≠ 用户看见，
   系统静默丢弃代码无法感知，所以第二条通道照发）。
2. 桌宠._check_fullscreen / set_fullscreen_hide：全屏藏、退出复原、**手动 _show_pet()
   后本轮豁免**（这条今天零判据，_fs_override 此前是死字段）。
3. 桌宠._time_mood_tick：show_bubble 早退（没真显示出来）时**不记账**
   （time_mood_sent 不变，当天名额不被吃掉）。
4. main.run：正常退出不重启 / 异常退出调用 spawn / **spawn 失败不占熔断名额**
   （pet_guard.note_restart 的契约：只有真的拉起过才算一次）。
5. 附带：备份 / 恢复成功回执必须**常驻**（质量 #4：含 zip 全路径那句 5 秒就没了）。

每条用例的 docstring 都写了「拿掉哪一行会红」。**A 代理的修复已落地**（_notify 双通道、
_show_pet 置豁免位、main.run 的记账顺序、备份/恢复回执的 hold_ms=0），本文件在修复前的
真树上对应四条是红的、修复后全绿 —— 它就是那几行修复的牙齿。
"""
import datetime as real_datetime
import json
import os
import sys
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import pet_dialogs  # noqa: E402
import pet_notify  # noqa: E402
import 桌宠 as petwin  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

# 守护入口（main.py 是"崩溃自动重启"的守护壳，不是桌宠本体）
import main as guard  # noqa: E402


# ---------------- 夹具：真 PetWindow（数据目录指到 tmp，绝不碰真配置） ----------------

def _snapshot():
    import pet_log
    return (petwin.DATA_DIR, petwin.CONFIG_PATH, petwin.USAGE_PATH, petwin.MEMORY_PATH,
            getattr(pet_log, "_data_dir", None))


def _point_data_dir(tmp_path):
    import pet_log
    petwin.DATA_DIR = str(tmp_path)
    petwin.CONFIG_PATH = str(tmp_path / "config.json")
    petwin.USAGE_PATH = str(tmp_path / "usage.json")
    petwin.MEMORY_PATH = str(tmp_path / "memory.json")
    pet_log.set_data_dir(str(tmp_path))


def _restore(snap):
    import pet_log
    (petwin.DATA_DIR, petwin.CONFIG_PATH, petwin.USAGE_PATH, petwin.MEMORY_PATH,
     pet_log._data_dir) = snap


def _app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(tmp_path):
    """一个真 PetWindow（周期定时器全停 → 判据确定性；收尾走 _quit）。"""
    snap = _snapshot()
    _point_data_dir(tmp_path)
    w = petwin.PetWindow()
    try:
        from helpers_roles import quiet_pet_timers
        quiet_pet_timers(w)
        for name in ("walk_timer", "_fullscreen_timer"):
            getattr(w, name).stop()          # 否则 300ms 后 _check_fullscreen 自己插进来
        # 收掉构造期那次开场表情（与 test_walk_anim_v2110._settle 同一口径）
        w._state_timer.stop()
        w._play_idle()
        if w._crossfade_anim is not None:
            w._crossfade_anim.setCurrentTime(w._crossfade_anim.duration())
            _app().processEvents()
        yield w
    finally:
        try:
            if not w._closing:
                w._quit()
        except Exception:
            pass
        _restore(snap)


# ---------------- 辅助 ----------------

class _StubWatch:
    """全屏判定器的替身：**只**钉接线（poll → 藏/显），去抖/节流有 37 条用例在管。

    用替身是为了确定性：真 FullscreenWatcher 有 250ms 节流与 3 次去抖，"这一拍是全屏"
    要靠推进墙钟才能摆出来；接线判据不该被那些时序拖累。
    """

    def __init__(self):
        self.value = False
        self.resets = 0

    def poll(self, now=None):
        return self.value

    def reset(self):
        self.resets += 1
        self.value = False


def _bubble_spy(win, monkeypatch, result=True):
    """把 win.show_bubble 换成"记参数 + 给固定返回值"的替身。

    注意：产品侧调用形式可能是 show_bubble(text) 或 show_bubble(text, hold_ms=...)，
    替身两种都收（hold_ms 缺省 None），断言里再判它有没有被透传。
    """
    calls = []

    def spy(text, hold_ms=None):
        calls.append({"text": text, "hold_ms": hold_ms})
        return result

    monkeypatch.setattr(win, "show_bubble", spy)
    return calls


# ================= 0. 新功能的默认值（质量 #5 · 「默认开」的显式登记） ================

def test_new_switches_have_the_documented_defaults(win):
    """全屏隐藏 / 系统通知默认**开**，时段问候默认**关** —— 这是发布说明写的口径。

    能真失败：把 DEFAULT_CONFIG 里 fullscreen_hide / notify 改成 False、或 time_mood
    改成 True → 对应断言红。默认值翻掉是"老用户升级后行为突变"，必须有机器判据看着。
    """
    assert win.cfg.get("fullscreen_hide") is True, "全屏自动隐藏的默认值不是「开」"
    assert win.cfg.get("notify") is True, "系统通知的默认值不是「开」"
    assert win.cfg.get("time_mood") is False, "时段问候的默认值不是「关」（老用户升级不该突然多气泡）"


# ================= 1. _notify：三条回执路径 =================

def test_notify_switch_off_goes_bubble_only(win, monkeypatch):
    """用户关掉「系统通知」→ 不发托盘通知，直接走气泡（回执不许静默丢）。

    能真失败：把 _notify 里 `if self.cfg.get("notify", True) is not False` 那个判断删掉
    （无条件发通知）→ notified 非空 → 红；把 `bubble = self.show_bubble(...)` 改成
    `bubble = delivered`（不弹气泡）→ calls 空 → 红。
    """
    notified = []
    monkeypatch.setattr(pet_notify, "notify",
                        lambda *a, **k: notified.append(a) or True)
    win.cfg["notify"] = False
    calls = _bubble_spy(win, monkeypatch, result=True)
    assert win._notify("回执：开关关着", hold_ms=0) is True
    assert notified == [], "开关关着仍然发了系统通知"
    assert [c["text"] for c in calls] == ["回执：开关关着"], "开关关着时气泡这条路没走"
    assert calls[0]["hold_ms"] == 0, "hold_ms 没透传给气泡（常驻回执被降回默认 5 秒）"


def test_notify_false_falls_back_to_the_bubble(win, monkeypatch):
    """pet_notify 返回 False（托盘不可用 / 被限流 / 发送失败）→ **退回气泡**。

    能真失败：把 `bubble = self.show_bubble(text, hold_ms=hold_ms)` 改成
    `bubble = False`（不弹气泡、直接 return bool(delivered)）→ calls 空 → 红。
    """
    monkeypatch.setattr(pet_notify, "notify", lambda *a, **k: False)
    win.cfg["notify"] = True
    calls = _bubble_spy(win, monkeypatch, result=False)
    assert win._notify("回执：托盘发不出去") is False
    assert [c["text"] for c in calls] == ["回执：托盘发不出去"], "notify 返回 False 时没退回气泡"
    assert win._notify("回执：托盘发不出去 2") is False


def test_notify_accepted_still_adds_a_bubble(win, monkeypatch):
    """notify 返回 True（已交给托盘）→ **仍然补一条气泡**。

    为什么：Windows 托盘没有送达回执（远程桌面 / explorer 没起 / 用户折叠托盘 / 系统关了
    通知时 showMessage 静默什么都不做）。只认返回值 = 闹钟可能在托盘这一层被静默吞掉，
    而音效也关着时用户零感知（相对 v2.10.0 的回归）。

    能真失败：把 _notify 改回旧口径（`if delivered: return True` 挡在 show_bubble 之前）
    → calls 空 → 红；或把 `bubble = self.show_bubble(...)` 改成 `bubble = False` → 同样红。
    """
    notified = []
    monkeypatch.setattr(pet_notify, "notify",
                        lambda *a, **k: notified.append(a) or True)
    win.cfg["notify"] = True
    calls = _bubble_spy(win, monkeypatch, result=True)
    assert win._notify("回执：托盘接受了") is True
    assert len(notified) == 1, "前提：通知这条路真的走了（否则这条什么都没验到）"
    assert [c["text"] for c in calls] == ["回执：托盘接受了"], \
        "托盘接受之后没有补气泡 —— 系统静默丢弃时用户零感知（回执又变成单通道）"
    assert len(calls) == 1, "气泡补了不止一条（同一句回执弹两遍）"


# ================= 2. _check_fullscreen：藏 / 显 / 手动豁免 =================

def test_fullscreen_poll_hides_then_restores(win, monkeypatch):
    """全屏 → 藏；退出全屏 → 复原。这是「默认开」功能的两跳，此前在 tests 里 0 命中。

    能真失败：删掉 _check_fullscreen 里 `self.hide()` → 第一段红；删掉 `self.show()` →
    第二段红；把 `self._hidden_for_fullscreen = now_fs` 删掉 → 第三段（状态位）红。
    """
    watch = _StubWatch()
    win._fs_watch = watch
    win.show()
    assert win.isVisible(), "前提：桌宠先得是显示着的"
    assert win._hidden_for_fullscreen is False
    watch.value = True
    win._check_fullscreen()
    assert not win.isVisible(), "全屏了却没藏（默认开的功能没接线）"
    assert win._hidden_for_fullscreen is True
    win._check_fullscreen()                  # 第二拍依旧全屏：不许抖回来
    assert not win.isVisible()
    watch.value = False
    win._check_fullscreen()
    assert win.isVisible(), "退出全屏没有复原"
    assert win._hidden_for_fullscreen is False


def test_fullscreen_switch_off_releases_a_hidden_pet(win, monkeypatch):
    """关掉开关：停定时器 + 判定器归位 + **把被我们藏起来的放出来**；此后再全屏也不许藏。

    能真失败：删掉 set_fullscreen_hide 里 `if not self.isVisible(): self.show()` → 第二段红；
    删掉 `self._fs_watch.reset()` → resets 断言红；删掉 cfg 落盘 → cfg 断言红。
    """
    watch = _StubWatch()
    win._fs_watch = watch
    win.show()
    watch.value = True
    win._check_fullscreen()
    assert not win.isVisible(), "前提：先被藏起来"
    win.set_fullscreen_hide(False)
    assert win.isVisible(), "关掉开关后被藏起来的没放出来（用户会以为程序没了）"
    assert win.cfg.get("fullscreen_hide") is False, "开关没落盘"
    assert win._fullscreen_timer.isActive() is False, "关掉开关后轮询定时器还在跑"
    assert watch.resets == 1, "关开关没让判定器归位（旧去抖计数会跨开关生效）"
    watch.value = True
    win._check_fullscreen()
    assert win.isVisible(), "开关关着仍被自动藏"


def test_manual_show_is_exempt_for_this_fullscreen_round(win, monkeypatch):
    """手动叫出来（_show_pet）→ **本轮全屏内不再自动藏**；退出全屏后豁免失效。

    为什么必须有这条：`_fs_override` 在修复前是**死字段**（全仓只有三处赋值且都是 False），
    「手动叫出来不再藏」当时只是靠 `_hidden_for_fullscreen` 的旧值**巧合**成立 —— 改一行
    就会又藏回去。这条把豁免位与行为一起钉住。

    能真失败：_show_pet 里不置 `self._fs_override = True` → 第二条断言红；
    把 _check_fullscreen 里 `(now_fs and self._fs_override)` 那个短路删掉 → 「手动叫出来后
    又被藏回去」红；把 `if not now_fs: self._fs_override = False` 删掉 → 「再进全屏该藏」
    红（豁免从此永久有效）。
    """
    watch = _StubWatch()
    win._fs_watch = watch
    win.show()
    watch.value = True
    win._check_fullscreen()
    assert not win.isVisible(), "前提：先真的被藏起来"
    win._show_pet()
    assert win.isVisible(), "手动叫出来却没显示"
    assert win._fs_override is True, \
        "手动叫出来后没置「本轮豁免」位（_fs_override 仍是死字段）——此时靠 _hidden_for_fullscreen 巧合挡住"
    # 摆在真正的「全屏仍在、但桌宠是用户自己叫出来的」状态：豁免必须**独立**挡住，
    # 而不是靠"我们藏起来"这个已经过时的状态位。
    win._hidden_for_fullscreen = False
    win._check_fullscreen()
    assert win.isVisible(), "手动叫出来后又被自动藏回去了（豁免没生效）"
    # 退出全屏 → 豁免失效（它只对「本轮」有效）
    watch.value = False
    win._check_fullscreen()
    assert win._fs_override is False, "退出全屏后豁免位没复位"
    assert win.isVisible()
    # 再进全屏 → 该藏
    watch.value = True
    win._check_fullscreen()
    assert not win.isVisible(), "豁免没有随「退出全屏」失效：下一轮全屏再也不藏了"


# ================= 3. _time_mood_tick：没真显示出来就不记账 =================

class _FixedNow(real_datetime.datetime):
    """把桌宠里的 datetime.datetime.now() 钉在「早安」段中间（08:30）。"""

    @classmethod
    def now(cls, tz=None):
        return real_datetime.datetime(2026, 10, 16, 8, 30, 0)


def test_time_mood_tick_does_not_book_when_the_bubble_is_refused(win, monkeypatch):
    """show_bubble 返回 False（在途气泡没让位 / 正在退出 / 无可用屏幕）→ **不记账**。

    为什么：due() 只判"该不该发"，remember() 才落账；先记账再弹的写法会让"没显示出来"
    也吃掉当天名额 —— 用户当天就再也收不到这句问候。

    能真失败：删掉 _time_mood_tick 里 `if not shown: return` 那两行 → time_mood_sent
    被写上 → 红。正反两面都在本用例里（第二段：真显示了必须记账），防止"永远不记账"也绿。
    """
    monkeypatch.setattr(petwin, "datetime", types.SimpleNamespace(datetime=_FixedNow))
    win._set_time_mood(True)                 # 走真正的开关（落盘 + 立即生效）
    assert win.cfg.get("time_mood") is True
    win.cfg["time_mood_sent"] = {}
    win.bubble.hide()                        # 低优先（早安）不压在途气泡：先摆好前提
    tried = []

    def _refused(text, hold_ms=None):
        tried.append(text)
        return False

    monkeypatch.setattr(win, "show_bubble", _refused)
    win._time_mood_tick()
    assert tried, "前提：这一拍确实走到了 show_bubble（否则这条什么都没验到）"
    assert win.cfg.get("time_mood_sent") == {}, \
        "气泡没显示出来却记了账（当天名额被吃掉）：%r" % (win.cfg.get("time_mood_sent"),)
    # 反向控制：真显示了就必须记账（否则上面那条「不变」可能只是永远不记账）
    shown = []
    monkeypatch.setattr(win, "show_bubble",
                        lambda text, hold_ms=None: (shown.append(text), True)[1])
    win._time_mood_tick()
    assert shown, "前提：第二次也走到了 show_bubble"
    assert win.cfg.get("time_mood_sent") == {"morning": "2026-10-16"}, \
        "真显示出来了却没记账（同一天会反复弹同一句）：%r" % (win.cfg.get("time_mood_sent"),)


# ================= 4. 备份 / 恢复成功回执必须常驻（质量 #4） =================

def test_backup_success_receipt_is_persistent(win, monkeypatch, tmp_path):
    """备份成功回执要**常驻**（hold_ms ≤ 0）：那句里带着 zip 的完整落点，5 秒就没了等于没说。

    能真失败：把 open_backup 里的 `_toast(pet, msg, hold_ms=0)` 改回 `_toast(pet, msg)`，
    或把 _toast 里 hold_ms 的分支删掉（只传 text）→ hold_ms 是 None → 红。
    判据落在「桌宠.show_bubble 最终收到的 hold_ms」上，所以 A 无论改 _toast 签名还是在
    open_backup 里直接弹，都绕不过这一条。
    """
    import pet_backup
    msg = "已备份 12 个文件到：E:/备份/backup.zip"
    monkeypatch.setattr(pet_backup, "create_backup", lambda *a, **k: (True, msg))

    class _FakeFileDialog:
        @staticmethod
        def getSaveFileName(*a, **k):
            return (str(tmp_path / "backup.zip"), "备份包 (*.zip)")

    monkeypatch.setattr(pet_dialogs, "QFileDialog", _FakeFileDialog)
    calls = _bubble_spy(win, monkeypatch, result=True)
    assert pet_dialogs.open_backup(win) is True, "前提：备份这条路成功返回"
    assert [c["text"] for c in calls] == [msg]
    hold = calls[0]["hold_ms"]
    assert hold is not None and hold <= 0, \
        "备份成功回执不是常驻（hold_ms=%r；含 zip 全路径那句 5 秒后就没了）" % (hold,)


def test_restore_success_receipt_is_persistent(win, monkeypatch, tmp_path):
    """恢复成功回执同样常驻（恢复是低频高风险操作，结果必须留得住）。

    能真失败：同 open_backup —— 回执退回默认 5s（hold_ms=None）→ 红。
    """
    import pet_backup
    msg = "已从备份恢复 12 个文件（快照：E:/备份/snap.zip）"
    manifest = {"files": [{"name": "a.json"}], "total_bytes": 1024,
                "created_at": 1000.0, "app_version": "2.11.0"}
    monkeypatch.setattr(pet_backup, "read_manifest", lambda path: (manifest, ""))
    monkeypatch.setattr(pet_backup, "restore_backup", lambda *a, **k: (True, msg))
    monkeypatch.setattr(pet_dialogs, "_confirm", lambda *a, **k: True)

    class _FakeFileDialog:
        @staticmethod
        def getOpenFileName(*a, **k):
            return (str(tmp_path / "backup.zip"), "备份包 (*.zip)")

    monkeypatch.setattr(pet_dialogs, "QFileDialog", _FakeFileDialog)
    calls = _bubble_spy(win, monkeypatch, result=True)
    assert pet_dialogs.open_restore(win) is True, "前提：恢复这条路成功返回"
    assert [c["text"] for c in calls] == [msg]
    hold = calls[0]["hold_ms"]
    assert hold is not None and hold <= 0, \
        "恢复成功回执不是常驻（hold_ms=%r；用户看不到「要不要重启」这类关键句）" % (hold,)


# ================= 5. main.run：守护的三种结局 =================

def _run_guard(tmp_path, monkeypatch, outcome, *, popen_raises=False):
    """把 main.run 的外部世界全换成可数的替身 → (code, marker, events, popens, told)。

    · 桌宠.main 按 outcome 正常返回 / 抛异常；
    · marker_path 指到 tmp（真的读写 JSON，走 pet_guard 的原子写）；
    · time 换成固定钟（now=1000.0），sleep 只记不睡（1s 退避不该真等）；
    · Popen 只记不启；_release_single_mutex / _tell_user 只记。
    """
    marker_file = tmp_path / "crash_recovery.json"
    events, popens, told = [], [], []
    monkeypatch.setattr(guard.pet_guard, "marker_path", lambda data_dir: str(marker_file))
    monkeypatch.setattr(guard, "time", types.SimpleNamespace(
        time=lambda: 1000.0, sleep=lambda s: events.append(("sleep", float(s)))))

    def _fake_main():
        if isinstance(outcome, BaseException):
            raise outcome

    monkeypatch.setattr(guard.桌宠, "main", _fake_main)
    monkeypatch.setattr(guard, "_release_single_mutex", lambda: events.append("release"))
    monkeypatch.setattr(guard, "_tell_user", lambda text: told.append(text))

    def _fake_popen(cmd, **kw):
        popens.append(list(cmd))
        events.append("spawn")
        if popen_raises:
            raise OSError("拉不起来（模拟 exe 被删 / 权限不足）")
        return object()

    monkeypatch.setattr(guard.subprocess, "Popen", _fake_popen)

    code = guard.run()
    data = None
    if marker_file.is_file():
        data = json.loads(marker_file.read_text(encoding="utf-8"))
    return code, data, events, popens, told


def test_guard_normal_exit_does_not_restart(tmp_path, monkeypatch):
    """正常退出（桌宠.main() 正常返回）→ **不重启**、不睡、不留崩溃记录。

    能真失败：把 `clean = True` 那行删掉 → 会被判成异常退出 → popens 非空 → 红；
    把 `if clean: save_marker(record_clean_exit(...))` 改成 record_crash → crash_count 红。
    """
    code, data, events, popens, told = _run_guard(tmp_path, monkeypatch, None)
    assert code == 0
    assert popens == [] and events == [], "正常退出仍然 sleep/spawn 了：%r" % (events,)
    assert told == [], "正常退出不该弹系统消息框"
    assert data is not None, "正常退出后连标记都没落盘"
    assert data["crash_count"] == 0 and data["restarts"] == []
    assert data["last_clean_at"] == 1000.0


def test_guard_crash_spawns_exactly_one_restart(tmp_path, monkeypatch):
    """异常退出 → 退避后拉起一次；拉起成功**才**把这次记进重启窗口。

    能真失败：
      · 删掉 Popen 那段 → popens 空 → 红；
      · restart_command 没带 --guard-restart → 子进程认不出自己（坑②）→ 红；
      · 先 release 后 spawn 的顺序反了 → release/spawn 的顺序断言红；
      · 真的拉起了却不记账（note_restart / will_restart=True 丢了）→ restarts 为空 → 红。
    """
    code, data, events, popens, told = _run_guard(
        tmp_path, monkeypatch, RuntimeError("模拟进程级崩溃"))
    assert code == 1
    assert len(popens) == 1, "异常退出没有拉起新进程"
    assert popens[0][-1] == guard.pet_guard.RESTART_FLAG, \
        "拉起的子进程没带 %s（它认不出自己是崩溃后被拉起的）" % guard.pet_guard.RESTART_FLAG
    assert ("sleep", 1.0) in events, "第一次重启前没有按 pet_guard 的 base_delay 退避：%r" % (events,)
    assert "release" in events and "spawn" in events
    assert events.index("release") < events.index("spawn"), \
        "先 spawn 再放单实例互斥体（坑①：子进程会拿到 183 静默退出）"
    assert data is not None
    assert data["crash_count"] == 1, "一次崩溃记成了不止一次"
    assert len(data["restarts"]) == 1, "真的拉起了一次却没有记进重启窗口（熔断永远数不够）"
    assert told == [], "拉起成功还弹了系统消息框"


def test_guard_spawn_failure_does_not_burn_a_restart_slot(tmp_path, monkeypatch):
    """spawn 失败（exe 被删 / 权限）→ 崩溃照记，但**不占**熔断名额、要告诉用户。

    为什么：pet_guard.SupervisorPolicy.note_restart 的口径是「只有**真的拉起过**才记账」——
    "判定要重启但没拉起来"也计数的话，熔断会被根本没成功的重启提前耗尽，用户一次新机会
    都没得到。

    能真失败：把 `record_crash(..., will_restart=True)` 挪回 sleep/spawn **之前**（旧写法）
    → spawn 抛异常后盘上 marker 里仍有一条重启记录 → restarts 断言红。
    """
    code, data, events, popens, told = _run_guard(
        tmp_path, monkeypatch, RuntimeError("模拟进程级崩溃"), popen_raises=True)
    assert code == 1
    assert len(popens) == 1, "前提：确实尝试过拉起"
    assert told, "拉不起来时必须告诉用户（静默失败 = 用户以为它还开着）"
    assert data is not None
    assert data["restarts"] == [], \
        "spawn 失败也把这次记进了重启窗口（熔断名额被白吃）：%r" % (data["restarts"],)
    assert data["crash_count"] == 1, "崩溃本身仍要记（否则排障时看不到这次崩溃）"
