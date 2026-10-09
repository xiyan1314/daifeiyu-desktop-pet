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

Python 3.10+（项目运行环境 3.10.2）。
"""

import os

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QPixmap


class FrameAnim(QObject):
    """帧动画播放器：注册多组帧集，按名字播放。

    用法::

        anim = FrameAnim()
        anim.add_set("idle", load_frame_set(assets_dir, "idle", 10))
        anim.frame_changed.connect(lambda i: item.setPixmap(frames[i]))
        anim.play("idle", interval_ms=140, loops=-1)
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
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)

    # ---- 帧集管理 ----
    def add_set(self, name, pixmaps):
        """注册（或覆盖）名为 name 的帧集。只存 QPixmap 引用，不复制像素。"""
        self._sets[name] = list(pixmaps)

    # ---- 播放控制 ----
    def play(self, name, interval_ms=140, loops=-1, on_finish=None):
        """播放指定帧集。

        loops=-1 无限循环；loops=N 播 N 遍后自动 stop 并回调 on_finish(name)；
        loops=0 或帧集缺失/为空则立即回调 on_finish(name)（若有）并返回 False；
        成功返回 True。
        """
        self.stop()  # 重复 play：先停旧再开新
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
        self._timer.setInterval(int(interval_ms))
        self._timer.start()
        self.frame_changed.emit(0)  # 立即显示首帧
        return True

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

    QTimer.singleShot(100, stop_and_report)
    sys.exit(app.exec())
