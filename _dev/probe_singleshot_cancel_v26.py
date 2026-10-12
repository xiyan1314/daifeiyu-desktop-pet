# -*- coding: utf-8 -*-
"""_dev 探针 4：QTimer.singleShot(毫秒, context, func) 挂起的定时器能否在测试里被找到并取消
（用于把"喂食后 120ms 错峰起吃帧"这一步也做成确定性，而不是等钟）。"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QTimer, QObject  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
fired = []
ctx = QObject()
QTimer.singleShot(120, ctx, lambda: fired.append(1))
kids = ctx.children()
print("children after singleShot:", [(c.metaObject().className(), repr(c)) for c in kids])
for c in kids:
    print("  deleteLater ->", c.deleteLater())
# 泵 200ms 看它还响不响
t0 = time.monotonic()
while time.monotonic() - t0 < 0.25:
    app.processEvents()
    time.sleep(0.01)
print("fired =", fired, "（0 = 成功取消，1 = 没取消）")
