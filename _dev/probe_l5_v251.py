# -*- coding: utf-8 -*-
"""v2.5.1 代理A · L5 取数：RoleEditDialog 设计宽 vs 内容最小宽（实测）。

跑法（仓库根）：python -B _dev/probe_l5_v251.py
只读、不改任何产品状态；输出 key=value，便于贴进报告。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QRect                      # noqa: E402
from PySide6.QtWidgets import QApplication            # noqa: E402

app = QApplication.instance() or QApplication([])
import pet_dialogs                                    # noqa: E402

pet_dialogs.dialog_available_geometry = lambda widget=None: QRect(0, 0, 2000, 1200)

dlg = pet_dialogs.RoleEditDialog(None, None, "")
dlg.show()
for _ in range(3):
    app.processEvents()

area = dlg._scroll_area
body = dlg._content_body


def snap(tag):
    sb = area.horizontalScrollBar()
    print("%s window=%dx%d viewport=%dx%d body_min=%dx%d hmax=%d vmax=%d hbar_visible=%s" % (
        tag, dlg.width(), dlg.height(),
        area.viewport().width(), area.viewport().height(),
        body.minimumSizeHint().width(), body.minimumSizeHint().height(),
        sb.maximum(), area.verticalScrollBar().maximum(), not sb.isHidden()))


snap("design600:")
dlg.resize(620, 540)
for _ in range(3):
    app.processEvents()
snap("width620:")
dlg.close()
