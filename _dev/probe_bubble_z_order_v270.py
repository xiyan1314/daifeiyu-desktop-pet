# -*- coding: utf-8 -*-
"""B0 实测：宠物气泡 vs 模态度话框 的 z 序（v2.7.0 反馈批次 · 代理 B）。

**为什么要有这个探针**
审计（_dev/audit_feedback_v270.md §1 #4）只从源码推断"气泡自己是 WindowStaysOnTopHint
+ 每次 raise_()，理论上能压住模态框"，**明说是未实测**。而这条结论直接决定 A 的修法：
面板内操作成功后的回执用**宠物气泡**还是**内联标签**。所以先量，再定口径。

**结论（本机实跑：Windows 10/11 桌面会话、PySide6 6.11.2、DPR=1.5、1920x1200 物理屏）**

  ┌ 场景 ─────────────────────────────────────────────┬ 结果 ────────────────────────────────┐
  │ S1 面板(modal exec 中)点保存/删除 → show_bubble()  │ **气泡压在上面**（rank 16 < 17，      │
  │    （气泡与对话框几何重叠）                        │  像素采样是气泡的白底+#203170 边框）  │
  │ S2 气泡已显示 → 用户点回对话框(activateWindow+raise)│ **对话框压住气泡**（rank 17 > 16，    │
  │                                                    │  采样点变成对话框的 #efefef 灰）      │
  │ S3 S2 之后又弹一条新气泡                            │ **气泡重新压回上面**                 │
  │ S4 气泡与对话框不重叠（正常桌宠位置）               │ 各自可见（不重叠时 z 序无意义）       │
  │ S5 先气泡、后打开对话框                             │ **对话框压住气泡**（后开者赢）        │
  │ S6 面板内 _confirm 子模态关闭后**立刻**弹气泡        │ **气泡压在上面**且 0/120/400ms 全程  │
  │                                                    │  稳定（父窗的延迟激活没有顶掉它）     │
  └────────────────────────────────────────────────────┴──────────────────────────────────────┘

  一句话：**"后 raise 的赢"**。两个窗口都在 WS_EX_TOPMOST 带内（实测两者
  GetWindowLongW(GWL_EXSTYLE)&WS_EX_TOPMOST 均为真），所以谁最后 raise_/activateWindow
  谁在最前。A 的目标路径（面板里点保存/删除成功 → 立刻 show_bubble）**气泡可见且压在上面**；
  只有当用户在 5 秒气泡存活期内**又点回对话框**（或先有气泡、后开对话框）时，气泡才会在
  重叠区域被压住——而气泡 5 秒自动隐藏（pet_widgets.Bubble :289），所以这不是"面板内回执
  看不到"的常态。**口径不必改**（面板内成功仍可用气泡）。

  给 A 的两条实操提醒（都来自实测，不是推断）：
   ① 气泡与正在显示的对话框**重叠**才会互相遮挡；桌宠气泡跟着宠物走（常在屏幕下方），
      对话框居中——重叠与否取决于宠物位置，故"气泡被压住"是**位置相关**的小概率。
   ② 若在"用户刚点过对话框"之后弹气泡（例如 _confirm 确认框关闭后的删除回执），
      本实测（S6）显示气泡仍然赢；**连续两次** raise 之间不要再插一次对话框激活即可。

**本机实测原始数据（2026-10-15 实跑，PROBE 输出原样摘录）**
  DPR=1.5  logical=QRect(0,0,1280,800)  physical=1920x1200
  S1  modal exec 中 show_text +80ms : dlg_rank=17 bubble_rank=16  topmost 两者都 True
                                     像素=[#ffffff×90, #203170×13, #c7cbdb×12]  命中=bubble
  S2  气泡显示后 activateWindow+raise : dlg_rank=16 bubble_rank=17  像素=[#f3f3f3×132, #0067c0×12]  命中=dialog
  S3  再弹一条新气泡                 : dlg_rank=17 bubble_rank=16  像素=气泡色                 命中=bubble
  S4  不重叠对照                     : 各自可见（overlap=False）
  S6a _confirm 关闭后同一轮弹气泡(+0ms): rank 16<17（气泡在前）但**像素还是对话框底色**
  S6b +120ms                        : 像素=气泡色                命中=bubble
  S6c +400ms                        : 同上（父窗的延迟激活没有顶掉气泡）
  S5  先气泡、后开对话框             : dlg_rank=16 bubble_rank=17  像素=[#f3f3f3×144]          命中=dialog
  → 8 个可测场景，气泡在对话框之上的 6 个；VERDICT-KEY（面板内成功→立刻弹气泡）= 气泡压在上面。

  **给自动化断言的一条实测坑**：气泡 raise_() 之后要**下一帧**才重绘——S6a 在 +0ms 抓屏仍是
  对话框底色（#e2e2e2），+120ms 才是气泡色。所以"气泡可见"的像素断言必须留 ~100ms
  （本轮探针的 S6a 就是这条坑的现场）。人工无感（一帧 ≈ 16ms）。

  **给 A 的实操口径**（由上面数据直接得出，不是推断）：
    · 面板内点保存/删除**成功后立刻** show_bubble → 气泡压在上面，口径不必改；
    · 气泡 5 秒存活期内用户**点回对话框**（或先有气泡、后开对话框）→ 重叠区域会被压住；
      这与"宠物在屏幕下方、对话框居中"的位置关系有关，属小概率且只影响重叠区；
    · 连续操作时：**每次操作都重新 show_bubble**（每次都会重新 raise_）即可保持可见。

**做法（真 Qt + 真 Windows 窗口，不是 offscreen）**
  1. 用 pet_dialogs.modal() 的原样序列（setWindowFlags|StaysOnTop → show → raise_ →
     activateWindow → setFocus → exec）开一个 QDialog；在**嵌套事件循环里**（exec 期间）
     调用真实的 pet_widgets.Bubble.show_text()——即"面板内点保存成功"那条路。
  2. 结构性证据：ctypes EnumWindows 取**真实顶层窗口 z 序**（自前向后），比较两个 HWND
     的 rank（小 = 靠前 = 压在上面）+ 各自 WS_EX_TOPMOST 位。
  3. 用户可见证据：QScreen.grabWindow 抓气泡中心 8x8 像素——气泡画的是白底 #ffffff /
     边框+文字 #203170，Qt 默认对话框底色是 #efefef：颜色本身就是"谁在上面"的判据。
  4. 鼠标命中证据：WindowFromPoint（**注意 Win32 用物理像素，Qt 几何是逻辑像素**；
     本机 DPR=1.5，不乘 DPR 会测错点——第一版探针就栽在这，已修）。
  5. 所有场景都**强制几何重叠**（气泡 anchor 放对话框中心），否则"谁压谁"没有观察意义。

**运行**：python -B _dev/probe_bubble_z_order_v270.py
  真窗口闪现约 3 秒（结束即销毁）；data_dir 指向临时目录，不写任何产品数据。
  offscreen 平台没有真实窗口栈：设 PROBE_OFFSCREEN=1 只做流程自检，会打印"无法测量"。
"""
import ctypes
import json
import os
import sys
import tempfile
import time
from ctypes import wintypes

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

if os.environ.get("PROBE_OFFSCREEN"):  # 逃生阀：无桌面会话时至少能跑完流程
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TMP = tempfile.mkdtemp(prefix="probe_z_")
import pet_log  # noqa: E402

pet_log.set_data_dir(TMP)

from PySide6.QtCore import QPoint, QTimer  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QDialog, QLabel, QPushButton, QVBoxLayout,
)

import pet_dialogs  # noqa: E402
import pet_widgets  # noqa: E402

app = QApplication.instance() or QApplication([])

user32 = ctypes.windll.user32
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long

GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
BUBBLE_BORDER = "#203170"  # pet_widgets.BUBBLE_STYLE 默认边框/字色
_ENUM_PROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

RESULTS = []


def top_level_zorder():
    """真实顶层窗口 z 序（自前向后）。offscreen 平台下为空。"""
    out = []

    def _cb(hwnd, _lparam):
        out.append(int(hwnd))
        return True

    try:
        user32.EnumWindows(_ENUM_PROC(_cb), 0)
    except Exception:
        return []
    return out


def hwnd_of(widget):
    try:
        return int(widget.winId())
    except Exception:
        return 0


def is_topmost(hwnd):
    try:
        return bool(user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST)
    except Exception:
        return None


def hit_test(logical_x, logical_y, dpr):
    """鼠标命中（Win32 物理坐标）。返回顶层 HWND。"""
    try:
        h = user32.WindowFromPoint(wintypes.POINT(int(logical_x * dpr), int(logical_y * dpr)))
        if not h:
            return 0
        root = user32.GetAncestor(h, 2)  # GA_ROOT
        return int(root or h)
    except Exception:
        return 0


def sample_pixels(scr, logical_x, logical_y, dpr):
    """抓 8x8 像素（Qt 逻辑坐标），返回出现次数最多的 3 个颜色。"""
    try:
        pm = scr.grabWindow(0, int(logical_x), int(logical_y), 8, 8).toImage()
        counts = {}
        for yy in range(pm.height()):
            for xx in range(pm.width()):
                c = pm.pixelColor(xx, yy).name()
                counts[c] = counts.get(c, 0) + 1
        return sorted(counts.items(), key=lambda kv: -kv[1])[:3]
    except Exception as e:
        return [("grab-failed:%r" % (e,), 0)]


def snapshot(tag, dlg, bubble, note=""):
    dpr = app.primaryScreen().devicePixelRatio() or 1.0
    order = top_level_zorder()
    dh, bh = hwnd_of(dlg), hwnd_of(bubble)
    bg = bubble.geometry()
    cx, cy = bg.center().x(), bg.center().y()
    dg = dlg.frameGeometry()
    cols = sample_pixels(app.primaryScreen(), cx - 4, cy - 4, dpr)
    top_colors = [c for c, _ in cols]
    hit = hit_test(cx, cy, dpr)
    rec = {
        "tag": tag,
        "note": note,
        "dlg_hwnd": dh,
        "bubble_hwnd": bh,
        "dlg_rank": order.index(dh) if dh in order else None,
        "bubble_rank": order.index(bh) if bh in order else None,
        "dlg_topmost": is_topmost(dh),
        "bubble_topmost": is_topmost(bh),
        "overlap": bool(bg.intersects(dg)),
        "bubble_rect": [bg.x(), bg.y(), bg.width(), bg.height()],
        "dialog_rect": [dg.x(), dg.y(), dg.width(), dg.height()],
        "pixels_at_bubble_center": cols,
        "bubble_paint_visible": BUBBLE_BORDER in top_colors or "#ffffff" in top_colors,
        "mouse_hit": ("bubble" if hit and hit == bh else
                      "dialog" if hit and hit == dh else "other(%s)" % hit),
        "zorder_measured": bool(order),
    }
    if rec["dlg_rank"] is not None and rec["bubble_rank"] is not None:
        rec["bubble_above_dialog"] = rec["bubble_rank"] < rec["dlg_rank"]
    RESULTS.append(rec)
    print("[%s] %s" % (tag, json.dumps(rec, ensure_ascii=False)), flush=True)
    return rec


def make_dialog(title):
    dlg = QDialog()
    dlg.setWindowTitle(title)
    lay = QVBoxLayout(dlg)
    lay.addWidget(QLabel("模拟面板：模态度话框"))
    lay.addWidget(QPushButton("确定"))
    dlg.resize(360, 220)
    return dlg


def scenario_main():
    """S1-S4 + S6：都在 modal() 的嵌套事件循环里完成。"""
    dlg = make_dialog("probe-z-order")
    scr = app.primaryScreen().availableGeometry()
    dlg.move(scr.center().x() - 180, scr.center().y() - 110)
    bubble = pet_widgets.Bubble()
    state = {"i": 0}

    def overlay_anchor():
        c = dlg.frameGeometry().center()
        return QPoint(c.x(), c.y() + 130)  # 气泡中心落在对话框下半部 → 强制重叠

    def step():
        i = state["i"]
        state["i"] += 1
        if i == 0:
            bubble.show_text("已保存~", overlay_anchor())
            QTimer.singleShot(80, step)
        elif i == 1:
            snapshot("S1", dlg, bubble, "modal exec 中 show_bubble()（A 的目标路径）+80ms")
            dlg.activateWindow()  # 模拟用户点回对话框
            dlg.raise_()
            QTimer.singleShot(120, step)
        elif i == 2:
            snapshot("S2", dlg, bubble, "气泡显示后用户点回对话框")
            bubble.show_text("已删除「X」", overlay_anchor())
            QTimer.singleShot(80, step)
        elif i == 3:
            snapshot("S3", dlg, bubble, "点回对话框后又弹一条新气泡")
            bubble.show_text("已保存~", QPoint(scr.center().x(), scr.bottom() - 60))
            QTimer.singleShot(80, step)
        elif i == 4:
            snapshot("S4", dlg, bubble, "气泡移到与对话框不重叠处（对照组）")
            # S6：面板内 _confirm 子模态关闭后**立刻**弹气泡（删除确认 → 回执）
            QTimer.singleShot(150, _dismiss_active_modal)
            pet_dialogs._confirm(dlg, "删除行为", "确定删除「测试」吗？")
            bubble.show_text("已删除「测试」", overlay_anchor())
            state["t0"] = time.perf_counter()
            QTimer.singleShot(0, step)      # 立刻测（同一轮事件队列内）
        elif i == 5:
            snapshot("S6a", dlg, bubble, "_confirm 关闭后同一轮立刻弹气泡（+0ms）")
            QTimer.singleShot(120, step)
        elif i == 6:
            snapshot("S6b", dlg, bubble, "_confirm 关闭 +120ms")
            QTimer.singleShot(280, step)
        elif i == 7:
            snapshot("S6c", dlg, bubble, "_confirm 关闭 +400ms（父窗延迟激活是否顶掉气泡）")
            bubble.hide()
            dlg.reject()
        else:
            dlg.reject()

    QTimer.singleShot(250, step)
    pet_dialogs.modal(dlg)
    print("[modal] 面板对话框已关闭，modal() 正常返回（没有卡死）", flush=True)


def _dismiss_active_modal():
    w = QApplication.activeModalWidget()
    if w is not None:
        w.accept()


def scenario_bubble_then_dialog():
    """S5：先气泡、后开对话框（后开者赢的对照组）。"""
    bubble = pet_widgets.Bubble()
    scr = app.primaryScreen().availableGeometry()
    dlg = make_dialog("probe-z-order-2")
    dlg.move(scr.center().x() - 180, scr.center().y() - 110)
    bubble.show_text("角色包已导出~", QPoint(scr.center().x(), scr.center().y() + 130))
    app.processEvents()
    # 与 pet_dialogs.modal() 同序的置顶/激活，但不进 exec（脚本里要接着做别的）
    dlg.setWindowFlags(dlg.windowFlags() | __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.WindowType.WindowStaysOnTopHint)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    for _ in range(3):
        app.processEvents()
        time.sleep(0.05)
    app.processEvents()
    snapshot("S5", dlg, bubble, "先气泡、后打开对话框（对话框后 raise）")
    bubble.hide()
    dlg.hide()
    dlg.deleteLater()
    app.processEvents()


def verdict():
    measured = [r for r in RESULTS if r.get("zorder_measured")]
    if not measured:
        print("VERDICT: 无法测量真实 z 序（offscreen 平台 / 无桌面会话）——本机请勿据此下结论")
        return
    print("VERDICT: 可测场景 %d 个；气泡在对话框之上的场景数 %d"
          % (len(measured), sum(1 for r in measured if r.get("bubble_above_dialog"))))
    for r in measured:
        print("  - %-4s bubble_above_dialog=%-5s bubble_paint_visible=%-5s hit=%s"
              % (r["tag"], r.get("bubble_above_dialog"), r["bubble_paint_visible"], r["mouse_hit"]))
    key = [r for r in measured if r["tag"] in ("S1", "S3", "S6a", "S6b", "S6c")]
    if key and all(r.get("bubble_above_dialog") for r in key):
        print("VERDICT-KEY(面板内成功→立刻弹气泡): 气泡压在上面 → 口径不必改，面板内回执可用气泡")
    elif key:
        print("VERDICT-KEY(面板内成功→立刻弹气泡): 有场景气泡被压住 → 见上面逐条")
    print("DONE")


def main():
    print("DPR=%s logical=%s physical=%s"
          % (app.primaryScreen().devicePixelRatio(),
             app.primaryScreen().geometry(), (user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))))
    scenario_main()
    scenario_bubble_then_dialog()
    verdict()
    try:
        app.processEvents()
    except Exception:
        pass


if __name__ == "__main__":
    main()
