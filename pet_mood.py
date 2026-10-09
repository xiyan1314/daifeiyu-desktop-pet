# -*- coding: utf-8 -*-
"""
大肥鱼桌宠 · 情绪状态机（阶段 2）
MIT License

职责：管理「戳戳情绪链 / 食物情绪 / 调皮事件」三条情绪线，
把结果一律通过信号发射出去，自身不碰任何控件：
- state(str)  ：要求主程序展示某状态图（puzzled/angry/hiss/drool/cry/smug）。
- bubble(str) ：台词气泡。
- emote(str)  ：头顶表情符号（heart/sparkle/tear/anger/exclaim/question/zzz/note/drool，
                 已有绘制器由主程序 _show_emote 提供）。

设计要点：
- 仅依赖 PySide6.QtCore（QObject / QTimer / Signal）与标准库 time/random；
  不 import QApplication/QPixmap，模块可在无 GUI 环境被 import。
- 戳链：距上次 poke 超过 2.5 秒则重置计数为 1，否则 +1；
  计数 1→puzzled、2→angry、>=3→hiss。
- 食物：food_shown 发射馋嘴并启动 8 秒单次定时器，超时触发 _withhold（cry）；
  food_hidden / fed 停掉该定时器。
- 调皮：选型 A——PetWindow 用外部周期定时器调用 tick()，内部按 45~90 秒
  随机间隔节流，到点发射 smug + 得意台词 + sparkle。

Python 3.10+（项目运行环境 3.10.2）。
"""

import random
import time

from PySide6.QtCore import QObject, QTimer, Signal


# ---------------- 台词库（中文，每组 3~5 条） ----------------
# v2.1.2：情绪台词改由台词库提供（用户可增删改）；这里只是"库不可用时的兜底常量"，
# 文本单一来源在 pet_lines（它零 Qt，不会造成循环 import）。
import pet_log  # noqa: E402
from pet_lines import (  # noqa: E402
    LINES_MOOD_PUZZLED as LINES_PUZZLED, LINES_MOOD_ANGRY as LINES_ANGRY,
    LINES_MOOD_HISS as LINES_HISS, LINES_MOOD_DROOL as LINES_DROOL,
    LINES_MOOD_CRY as LINES_CRY, LINES_MOOD_SMUG as LINES_SMUG,
    LINES_MOOD_BLUSH as LINES_BLUSH,
)
class Mood(QObject):
    """情绪状态机：戳链 / 食物 / 调皮 三条情绪线，全部经信号输出。"""

    # 信号：状态图名 / 气泡台词 / 头顶表情符号
    state = Signal(str)
    bubble = Signal(str)
    emote = Signal(str)

    # 常量
    POKE_RESET_SECONDS = 2.5    # 距上次戳超过该秒数即重置戳链计数
    FOOD_WAIT_MS = 8000         # 托盘打开后多久不给吃 → 委屈哭泣（毫秒）
    MISCHIEF_MIN_S = 45.0       # 调皮事件最短间隔（秒）
    MISCHIEF_MAX_S = 90.0       # 调皮事件最长间隔（秒）

    def __init__(self, parent=None, line_picker=None):
        super().__init__(parent)
        # v2.1.2：line_picker(category, fallback_list) -> 台词文本（由桌宠注入台词库）
        self._line_picker = line_picker

        # ---- 戳链状态 ----
        self._last_poke = 0.0
        self._poke_count = 0

        # ---- 食物情绪 ----
        # 8 秒单次定时器：托盘打开一直不给吃，超时触发 _withhold（cry）
        self._food_timer = QTimer(self)
        self._food_timer.setSingleShot(True)
        self._food_timer.setInterval(self.FOOD_WAIT_MS)
        self._food_timer.timeout.connect(pet_log.guard_slot("mood._withhold", self._withhold))

        # ---- 调皮事件（选型 A：外部周期定时器驱动 tick()）----
        # 主程序启动时先 prime_mischief() 把首次触发推迟到随机 45~90 秒后；
        # 之后每次 tick() 到点发射，再重新随机 45~90 秒的下一次间隔。
        self._next_mischief = 0.0

    def _pick(self, category, fallback):
        """情绪台词取词：优先台词库（用户可增删改）。

        v2.1.2 修复：库可用但这一类被用户删空时，取词器返回空串 → 这里也返回空串
        （由 _emit_line 跳过这句气泡），**不**回落内置常量——否则等于"删了还会念"。
        只有取词器缺失/抛异常（库不可用）时才用兜底常量，保证气泡不会因为取词崩掉。
        """
        if self._line_picker is not None:
            try:
                return self._line_picker(category, fallback) or ""
            except Exception:
                pass  # 有意忽略：取词器异常 → 回落内置常量（气泡不能因为取词崩掉）
        return random.choice(fallback) if fallback else ""

    def _emit_line(self, category, fallback):
        """取词并发射情绪气泡（空串=用户把这组删光了 → 这次不喊）。"""
        text = self._pick(category, fallback)
        if text:
            self.bubble.emit(text)

    def prime_mischief(self):
        """把下一次调皮事件推迟到随机 45~90 秒后（启动时调用，避免刚启动就坏笑）。"""
        self._next_mischief = time.monotonic() + random.uniform(self.MISCHIEF_MIN_S, self.MISCHIEF_MAX_S)

    # ================= 戳链 =================
    def poke(self):
        """戳一下：距上次超过 2.5s 重置计数为 1，否则 +1，按计数晋级情绪。"""
        now = time.monotonic()
        if self._poke_count == 0 or now - self._last_poke > self.POKE_RESET_SECONDS:
            self._poke_count = 1
        else:
            self._poke_count += 1
        self._last_poke = now

        if self._poke_count == 1:
            self.state.emit("puzzled")
            self._emit_line("mood_puzzled", LINES_PUZZLED)
            self.emote.emit("question")
        elif self._poke_count == 2:
            self.state.emit("angry")
            self._emit_line("mood_angry", LINES_ANGRY)
            self.emote.emit("anger")
        else:  # >= 3
            self.state.emit("hiss")
            self._emit_line("mood_hiss", LINES_HISS)
            self.emote.emit("anger")

    # ================= 食物情绪 =================
    def food_shown(self):
        """食物托盘打开 → 馋嘴；并启动 8 秒定时器，超时不给吃就委屈。"""
        self.state.emit("drool")
        self._emit_line("mood_drool", LINES_DROOL)
        self.emote.emit("drool")
        self._food_timer.start()  # 重复调用会重启 8 秒窗口

    def food_hidden(self):
        """托盘关闭 → 停掉 8 秒定时器（不再进入委屈）。"""
        self._food_timer.stop()

    def _withhold(self):
        """8 秒没吃到 → 委屈哭泣（私有，由食物定时器超时触发）。"""
        self.state.emit("cry")
        self._emit_line("mood_cry", LINES_CRY)
        self.emote.emit("tear")

    def fed(self):
        """已喂食：只停掉 8 秒定时器，不 emit（吃完展示由外部决定）。"""
        self._food_timer.stop()

    def blush(self):
        """被夸 → 害羞脸红。"""
        self.state.emit("blush")
        self._emit_line("mood_blush", LINES_BLUSH)
        self.emote.emit("heart")

    def stop_all(self):
        """停止全部内部定时器（退出清理用）。"""
        self._food_timer.stop()

    # ================= 调皮事件 =================
    def tick(self):
        """调皮事件调度（选型 A：由外部周期定时器调用，如 PetWindow 每 1s 调一次）。

        内部用「随机间隔」节流：距上次调皮不足当前随机间隔时直接返回；
        到点则发射 smug + 得意台词 + sparkle，并重新随机下一次 45~90 秒间隔。
        """
        now = time.monotonic()
        if now < self._next_mischief:
            return
        self._do_mischief()
        self._next_mischief = now + random.uniform(self.MISCHIEF_MIN_S, self.MISCHIEF_MAX_S)

    def _do_mischief(self):
        """实际发射「做坏事得意」情绪（由 tick() 调用，也供冒烟测试直接验证）。"""
        self.state.emit("smug")
        self._emit_line("mood_smug", LINES_SMUG)
        self.emote.emit("sparkle")


if __name__ == "__main__":
    # P0-2：以下 print 为命令行冒烟工具输出（python pet_mood.py 运行可见），保留不改为日志
    # 冒烟测试：只需 QCoreApplication（模块顶层无 GUI import），
    # 用 QTimer 分步异步驱动，避免同步连续调用受 2.5s 戳链阈值干扰。
    import sys

    from PySide6.QtCore import QCoreApplication

    app = QCoreApplication(sys.argv)

    mood = Mood()

    states, bubbles, emotes = [], [], []
    mood.state.connect(states.append)
    mood.bubble.connect(bubbles.append)
    mood.emote.connect(emotes.append)

    def step0():
        mood.poke()  # 计数 1 → puzzled
        QTimer.singleShot(100, mood, step1)

    def step1():
        mood.poke()  # 计数 2 → angry（距上次 100ms < 2.5s）
        QTimer.singleShot(100, mood, step2)

    def step2():
        mood.poke()  # 计数 3 → hiss
        QTimer.singleShot(100, mood, step3)

    def step3():
        mood.food_shown()  # → drool + 启动 8s 定时器
        QTimer.singleShot(50, mood, step4)

    def step4():
        mood._withhold()  # 手动触发超时逻辑 → cry
        QTimer.singleShot(50, mood, step5)

    def step5():
        mood.tick()  # 首次 tick() 立即触发一次 → smug
        QTimer.singleShot(50, mood, finish)

    def finish():
        # 断言戳链：puzzled → angry → hiss
        assert states[:3] == ["puzzled", "angry", "hiss"], states
        # 断言食物情绪与调皮事件
        assert "drool" in states, states
        assert "cry" in states, states
        assert "smug" in states, states
        assert states.count("smug") == 1, states
        # 断言表情符号
        assert emotes[:3] == ["question", "anger", "anger"], emotes
        assert "drool" in emotes, emotes
        assert "tear" in emotes, emotes
        assert "sparkle" in emotes, emotes
        # 断言台词气泡：每个情绪各一次，共 6 条
        assert len(bubbles) == 6, bubbles
        print("MOOD SMOKE OK")
        app.quit()

    QTimer.singleShot(0, mood, step0)
    sys.exit(app.exec())
