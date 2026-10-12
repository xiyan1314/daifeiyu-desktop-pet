# -*- coding: utf-8 -*-
"""_dev 探针 3：QVariantAnimation.setCurrentTime() 能否作为**确定性**驱动（不看钟）。

要回答：运行中的动画被 setCurrentTime 逐步推到 duration 时，
  · valueChanged 是否照常发（变换真的被驱动）
  · 到 duration 的那一刻 finished 是否发出、状态是否变 Stopped
  · 是否需要额外泵一次事件
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QVariantAnimation, QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
RUNNING, STOPPED = 2, 0


def mk():
    st = {"vals": [], "fin": []}
    a = QVariantAnimation()
    a.setDuration(400)
    a.setStartValue(0.0)
    a.setEndValue(1.0)
    a.valueChanged.connect(lambda v: st["vals"].append(round(float(v), 4)))
    a.finished.connect(lambda: st["fin"].append(1))
    return a, st


def show(tag, a, st):
    print("%-38s state=%d cur=%d vals=%d last=%s fin=%d"
          % (tag, int(a.state().value), a.currentTime(), len(st["vals"]),
             st["vals"][-1] if st["vals"] else None, len(st["fin"])))
    sys.stdout.flush()


print("Qt", __import__("PySide6").__version__)
# 1) 起步后一次性推到 duration
a, st = mk(); a.start(); a.setCurrentTime(400); show("1 setCurrentTime(dur) 直推", a, st)
QCoreApplication.processEvents(); show("1b 再泵一次", a, st)

# 2) 固定步进 10 步到 duration
a, st = mk(); a.start()
for t in range(0, 401, 40):
    a.setCurrentTime(t)
show("2 固定 40ms × 11 步", a, st)
QCoreApplication.processEvents(); show("2b 再泵一次", a, st)

# 3) 步进到 dur-1，再落 dur
a, st = mk(); a.start()
for t in range(0, 400, 40):
    a.setCurrentTime(t)
show("3a 步进到 360", a, st)
a.setCurrentTime(399); show("3b 到 399", a, st)
a.setCurrentTime(400); show("3c 到 400", a, st)
QCoreApplication.processEvents(); show("3d 再泵一次", a, st)

# 4) 先 setPaused 再推（另一种口径）
a, st = mk(); a.start(); a.setPaused(True); a.setCurrentTime(400); show("4 暂停后推 dur", a, st)
a.setPaused(False); show("4b 取消暂停", a, st)
QCoreApplication.processEvents(); show("4c 再泵一次", a, st)

# 5) 真实时钟路径对照：正常轮询
a, st = mk(); a.start()
t0 = time.monotonic()
while time.monotonic() - t0 < 0.6:
    QCoreApplication.processEvents(); time.sleep(0.01)
show("5 真实轮询 600ms（对照）", a, st)
