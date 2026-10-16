# -*- coding: utf-8 -*-
"""V6 结案探针：`QListWidget.setCurrentRow` 到底会不会把目标行滚进视口（**离线可验**）。

**背景**：#21 的两条"需真 GUI"里，① 这条在 `_dev/audit_feedback_v270.md:269` 与
`_dev/audit_behavior_assets_v290.md:185/292` 挂了两轮，而且**记录互相矛盾**——
audit_feedback_v270.md:302 写"本轮已实测：offscreen / Qt 6.11 下会带动滚动条"，
另一处又写"仍未实测"。v2.11.0 第 9 轮（代理 C）把它**一次测清楚**并留成可复跑脚本。

**结论（本轮实测）**：offscreen 平台下 Qt 的几何与滚动状态是**完整**的（没有窗口管理器，
但 `viewport()` 与 `visualItemRect()` 都是真值）——所以这条**本来就不该被列成"需真 GUI"**。
产品侧另有一层结构性消解：四个 `_select_*` 都显式调了 `scrollToItem`，不再依赖 Qt 的隐式滚动。

用法：`python -B _dev/probe_autoscroll_v2110.py`
退出码：0 = 跑出结论（stdout 里 `结论：…` 一行）；1 = 环境起不来（Qt 缺失等，**不是结论**）。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    from PySide6.QtWidgets import QApplication, QListWidget, QListWidgetItem
except Exception as e:                                   # pragma: no cover
    print("跑不起来（没有 PySide6 / offscreen 起不来）：%r" % (e,))
    sys.exit(1)


def _rect_in_view(seq, row):
    """目标行是否真在视口内（几何判据，不依赖肉眼）。"""
    r = seq.visualItemRect(seq.item(row))
    vp = seq.viewport().rect()
    return vp.intersects(r), r, vp


def _make(app, rows=30):
    w = QListWidget()
    w.resize(220, 140)                     # 小视口：一屏放不下 30 行，否则"滚没滚"看不出来
    for i in range(rows):
        w.addItem(QListWidgetItem("第 %d 行" % i))
    w.show()
    app.processEvents()
    return w


def main():
    app = QApplication.instance() or QApplication([])
    bad = 0

    def _check(label, fn, want_scrolled, want_visible=None):
        if want_visible is None:
            want_visible = want_scrolled      # 清选中那种对照只判"没滚"，不要求目标行可见
        nonlocal bad
        w = _make(app)
        row = w.count() - 5
        before = w.verticalScrollBar().value()
        fn(w, row)
        app.processEvents()
        after = w.verticalScrollBar().value()
        ok, rect, vp = _rect_in_view(w, row)
        scrolled = after > before
        verdict = "会滚" if scrolled else "不滚"
        good = (scrolled == want_scrolled) and (ok == want_visible)
        if not good:
            bad += 1
        print("  [%s] %-30s scrollbar %d→%d（%s）；目标行矩形 %s，视口 %s，在视口内=%s"
              % ("OK" if good else "FAIL", label, before, after, verdict,
                 (rect.x(), rect.y(), rect.width(), rect.height()),
                 (vp.x(), vp.y(), vp.width(), vp.height()), ok))
        w.hide()
        return scrolled, ok

    print("offscreen 探针（PySide6 / QT_QPA_PLATFORM=%s）" % os.environ.get("QT_QPA_PLATFORM"))
    print("对照与实测：")
    _check("setCurrentRow(第 25 行)", lambda w, r: w.setCurrentRow(r), True)
    _check("setCurrentItem(item(第 25 行))", lambda w, r: w.setCurrentItem(w.item(r)), True)
    _check("只 setCurrentRow(-1)（清选中）", lambda w, r: w.setCurrentRow(-1), False, False)
    w = _make(app)
    row = w.count() - 5
    w.setCurrentRow(row)
    app.processEvents()
    scrolled, ok = w.verticalScrollBar().value() > 0, _rect_in_view(w, row)[0]
    print("")
    if scrolled and ok:
        print("结论：**offscreen 下 setCurrentRow 会把目标行滚进视口**（几何判据成立）——")
        print("      这条「要真 GUI 才能验」的定性是错的，**离线可验**；产品的四个 _select_*")
        print("      另用显式 scrollToItem 做了结构性消解（不依赖这条行为）。")
    else:
        print("结论：**offscreen 下不会自动滚**（scrollbar=%d，在视口内=%s）——"
              "那就更要用显式 scrollToItem（产品已经这么做了）。" % (w.verticalScrollBar().value(), ok))
        print("      两种结论都**不需要真 GUI**：几何在 offscreen 下就是真值。")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
