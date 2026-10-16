# -*- coding: utf-8 -*-
"""
大肥鱼桌宠 · 帧动画播放器（阶段 1）
MIT License

职责：按帧集（list[QPixmap]）顺序循环 / 有限次播放帧动画，供 PetWindow 的角色动画使用。

设计要点：
- 仅依赖 PySide6.QtCore（QObject / QTimer / Signal）与 QtGui.QPixmap；
  不 import QApplication，模块可在无 GUI 环境被 import（构造 QPixmap 才需要 GUI 应用）。
- 帧集只保存 QPixmap 引用、不复制像素（list() 浅拷贝仍指向同一批 QPixmap 对象）。
- 内部由单个 QTimer 驱动；重复 play 先停旧再开新；stop 只停定时器、保持当前帧不变。
- **帧率倍率**（v2.11.0 发版轮 D1）：play(..., rate_factor=F) / set_rate_factor(F) 按倍率缩放
  **相邻帧的间隔**（1.0 = 原速；0.5 = 半速，即间隔 ×2）。倍率是"放慢"，**不是停帧**——
  无论倍率多小，间隔都是有限正数（非法值一律按 1.0 原速）。运行中改倍率当场重设定时器，
  不重置帧下标、不打断播放（「减少动效」开关随时可切，帧仍在推进，只是更慢）。

Python 3.10+（项目运行环境 3.10.2）。
"""

import math
import os

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QPixmap
import pet_log


# v2.11.0 发版轮（D1）：帧间隔的**兜底值**（与 桌宠.IDLE_FRAME_MS 同值）。
# 只在"调用方没给间隔"且从没 play 过时被读到（此时定时器根本没起）。
_DEFAULT_INTERVAL_MS = 140


def _safe_rate_factor(value):
    """帧率倍率 → **有限的正常数**；非法值（0 / 负数 / NaN / inf / 非数值）一律 1.0（原速）。

    为什么要有这道闸：倍率是"减少动效 = 放慢"的载体，一旦漏进 0 或负数，
    相除得到的间隔会变成 0 / 负数 / 无穷 → 要么把角色**冻成一张图**（D1 明令不许），
    要么让定时器空转烧 CPU。兜底取原速（1.0）是这里唯一安全的默认。
    """
    try:
        r = float(value)
    except (TypeError, ValueError):
        return 1.0
    if not math.isfinite(r) or r <= 0.0:
        return 1.0
    return r


class FrameAnim(QObject):
    """帧动画播放器：注册多组帧集，按名字播放。

    用法::

        anim = FrameAnim()
        anim.add_set("idle", load_frame_set(assets_dir, "idle", 10))
        anim.frame_changed.connect(lambda i: item.setPixmap(frames[i]))
        anim.play("idle", interval_ms=140, loops=-1)
        # 减少动效开着时：帧照播，只是慢一半（帧率倍率 0.5 → 相邻帧间隔 ×2）
        anim.set_rate_factor(0.5)
    """

    # 每次切帧发射帧下标（0 起，按帧集顺序）
    frame_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sets = {}          # name -> list[QPixmap]（引用，不复制像素）
        self._frames = []        # 当前播放中的帧集引用
        self._name = None        # 当前播放的帧集名
        self._index = 0          # 当前帧下标
        self._emitted = 0        # 本次已发射帧数：play 立即发射首帧并计 1，故 N 遍 = 共发射 N×len 帧
        self._loops = -1         # 目标循环遍数；-1 表示无限
        self._on_finish = None   # 播放结束回调
        self._interval_ms = _DEFAULT_INTERVAL_MS  # 调用方给的**基准**相邻帧间隔（倍率之前）
        self._rate = 1.0         # 帧率倍率（1.0 = 原速；0.5 = 半速 = 间隔 ×2）
        self._timer = QTimer(self)
        self._timer.timeout.connect(pet_log.guard_slot("anim._advance", self._advance))

    # ---- 帧集管理 ----
    def add_set(self, name, pixmaps):
        """注册（或覆盖）名为 name 的帧集。只存 QPixmap 引用，不复制像素。"""
        self._sets[name] = list(pixmaps)

    # ---- 播放控制 ----
    def play(self, name, interval_ms=140, loops=-1, on_finish=None, rate_factor=1.0):
        """播放指定帧集。

        loops=-1 无限循环；loops=N 播 N 遍后自动 stop 并回调 on_finish(name)；
        loops=0 或帧集缺失/为空则立即回调 on_finish(name)（若有）并返回 False；
        成功返回 True。

        rate_factor：帧率倍率（v2.11.0 发版轮 D1）——1.0 原速、0.5 半速（相邻帧间隔 ×2）。
        非法倍率按 1.0；**倍率再小也不会把帧停住**（实际间隔恒为 >=1 的整数）。
        """
        self.stop()  # 重复 play：先停旧再开新
        # 基准间隔与倍率**先记下**：即使下面"帧集为空 / loops=0"早退，
        # effective_interval_ms() 读到的也是这次请求的口径（吃帧看门狗按它算时长）。
        self._interval_ms = int(interval_ms)
        self._rate = _safe_rate_factor(rate_factor)
        frames = self._sets.get(name)
        if not frames or loops == 0:
            self._on_finish = None
            self._name = None
            if on_finish:
                on_finish(name)
            return False

        self._frames = frames
        self._name = name
        self._index = 0
        self._emitted = 1
        self._loops = loops
        self._on_finish = on_finish
        self._timer.setInterval(self.effective_interval_ms())
        self._timer.start()
        self.frame_changed.emit(0)  # 立即显示首帧
        return True

    # ---- 帧率倍率（v2.11.0 发版轮 D1：「减少动效」= 放慢素材帧，不是停帧） ----
    def effective_interval_ms(self):
        """当前**实际**的相邻帧间隔（毫秒）= 基准间隔 ÷ 帧率倍率，恒为 >=1 的整数。

        这就是"相邻两帧的时间间隔"本身（定时器用的就是它），判据直接读它，不用看眼。
        """
        return max(1, int(round(float(self._interval_ms) / self._rate)))

    def rate_factor(self):
        """当前帧率倍率（1.0 = 原速；0.5 = 半速）。"""
        return self._rate

    def set_rate_factor(self, factor):
        """运行中改帧率倍率：**当场**按新倍率重设定时器，不重置帧下标、不打断播放。

        返回实际生效的相邻帧间隔（毫秒）。未在播放时只记录倍率，下次 play 生效。
        """
        self._rate = _safe_rate_factor(factor)
        ms = self.effective_interval_ms()
        if self._timer.isActive():
            self._timer.setInterval(ms)
        return ms

    def stop(self):
        """停止播放，保持当前帧不动；清理待触发的结束回调。"""
        if self._timer.isActive():
            self._timer.stop()
        self._on_finish = None

    def current(self):
        """返回当前帧 QPixmap；从未播放时返回 None。"""
        if self._frames:
            return self._frames[self._index]
        return None

    # ---- 内部 ----
    def _advance(self):
        """定时器回调：切到下一帧；有限循环播完后自动 stop 并回调 on_finish。"""
        n = len(self._frames)
        if n == 0:
            return
        self._index = (self._index + 1) % n
        self._emitted += 1
        self.frame_changed.emit(self._index)
        if self._loops > 0 and self._emitted >= self._loops * n:
            self._timer.stop()
            cb, self._on_finish = self._on_finish, None
            if cb:
                cb(self._name)


def load_frame_set(dir_path, prefix, count):
    """加载 dir_path 下名为 prefix_f%02d.png（i=0..count-1）的帧集。

    加载失败（文件不存在 / QPixmap.isNull()）跳过且不抛异常；可能返回空列表。
    """
    frames = []
    for i in range(count):
        path = os.path.join(dir_path, "%s_f%02d.png" % (prefix, i))
        try:
            pix = QPixmap(path)
        except Exception:
            pix = QPixmap()  # 坏文件按空帧处理
        if pix.isNull():
            continue
        frames.append(pix)
    return frames


if __name__ == "__main__":
    # P0-2：以下 print 为命令行冒烟工具输出（python pet_anim.py 运行可见），保留不改为日志
    import sys

    # QPixmap 在 Qt6 下需要 QGuiApplication（只建 QCoreApplication 会崩溃）。
    # 仅在冒烟测试处引入，模块顶层保持无 GUI 依赖。
    from PySide6.QtGui import QGuiApplication, QColor

    app = QGuiApplication(sys.argv)
    anim = FrameAnim()

    # 3 帧假 QPixmap，填充不同颜色
    colors = [QColor("#ff5b5b"), QColor("#5bff7a"), QColor("#5b8cff")]
    frames = [QPixmap(4, 4) for _ in colors]
    for p, c in zip(frames, colors):
        p.fill(c)
    anim.add_set("demo", frames)

    switch_count = [0]

    def on_frame(_i):
        switch_count[0] += 1

    anim.frame_changed.connect(on_frame)

    ok = anim.play("demo", interval_ms=30, loops=2)
    print("play() ->", ok)

    def stop_and_report():
        anim.stop()
        cur = anim.current()
        print("frame switch count:", switch_count[0])
        print("current frame:", "None" if cur is None else "%dx%d" % (cur.width(), cur.height()))
        print("FRAMEANIM SMOKE OK")
        app.quit()

    QTimer.singleShot(100, anim, stop_and_report)
    sys.exit(app.exec())
