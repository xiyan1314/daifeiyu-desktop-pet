# -*- coding: utf-8 -*-
"""v2.5.0 代理 B：对话框尺寸体检 / 验收共用的取数层（**不是** pytest 用例文件）。

为什么要单独一个模块：
  B1 体检脚本（_probe_dialog_sizes.py）与 B3 验收用例（test_dialog_fit_v250.py）
  必须量的是**同一批对话框、同一套指标**，否则"体检说超了、验收说没超"无法对账。
  取数只写一份，两边 import。

口径（全部用 Qt **逻辑像素**，与 DPI 无关——物理像素 = 逻辑像素 × devicePixelRatio）：
  actual   ：show() 之后 Qt 实际给出的窗口尺寸（= 产品代码 resize() 的结果）
  hint     ：sizeHint()，内容想占多大
  min      ：minimumSizeHint()，Qt 允许缩到多小（**"缩小不了"的根因**）
  avail    ：QScreen.availableGeometry()（已扣任务栏/停靠区）
  scroll   ：窗口里有几个 QScrollArea（0 = 内容再多也滚不到底）
  btn      ：底排按钮（确定/取消/关闭…）在**窗口坐标系**里的下边界
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PySide6.QtCore import QPoint, QTimer  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QDialog, QPushButton, QScrollArea, QWidget,
)


# ---------------- PetWindow 启动（照抄 tests/test_dialogs_more_v24.py 的隔离套路） ----------------

def boot_application():
    """导入期/运行期都要拿到**真正的 QApplication**（不是 QCoreApplication）。"""
    app = QApplication.instance()
    if isinstance(app, QApplication):
        return app
    return QApplication([])


_APP = boot_application()


def make_pet(tmp_dir):
    """真 PetWindow + 全部运行时路径指向临时目录（不写用户真实数据）。"""
    import pet_log
    import 桌宠 as main

    main.DATA_DIR = str(tmp_dir)
    main.CONFIG_PATH = os.path.join(str(tmp_dir), "config.json")
    main.USAGE_PATH = os.path.join(str(tmp_dir), "usage.json")
    main.MEMORY_PATH = os.path.join(str(tmp_dir), "memory.json")
    pet_log.set_data_dir(str(tmp_dir))
    win = main.PetWindow()
    return win


def shutdown_pet(win):
    """先停表再拆：留着活跃 QTimer 会在别的用例里回调产品代码（顺序污染）。"""
    try:
        win._closing = True
    except Exception:
        pass
    try:
        win.voice.stop()
    except Exception:
        pass
    for _t in win.findChildren(QTimer):
        try:
            _t.stop()
        except Exception:
            pass
    try:
        win.hide()
        win.close()
        win.deleteLater()
    except Exception:
        pass


def silence_modals():
    """_warn/_info/_confirm 内部走 modal()=exec()，offscreen 下会挂死——换成记录器。

    返回 (恢复函数, 记录列表)。构造期任何一条落到记录里的提示都说明该对话框
    在"打开"这一步就会弹模态框，必须在报告里单独标出来（体检脚本会打印）。
    """
    import pet_dialogs
    seen = []
    saved = {}
    for name in ("_warn", "_info", "_confirm"):
        fn = getattr(pet_dialogs, name, None)
        if fn is None:
            continue
        saved[name] = fn
        setattr(pet_dialogs, name, (lambda n: (lambda *a, **k: seen.append((n, a, k))))(name))

    def restore():
        for k, v in saved.items():
            setattr(pet_dialogs, k, v)
    return restore, seen


# ---------------- 全量对话框清单（pet_dialogs.py 里每一个 QWidget 顶层类） ----------------

def dialog_factories():
    """(名字, 造窗口的可调用) —— 顺序 = 源码里出现的顺序，**必须与验收用例的清单等长**。

    pet_dialogs.py 里**全部** QDialog 子类 15 个 + 会被嵌进 ResourceManagerDialog 的
    3 个面板（它们自己也是独立窗口，用户双击/单开时同样受限）+ 1 个内联框
    （build_role_meta_dialog，原来裸 QDialog、没有屏幕钳制）。

    v2.5.0 第 3 轮 L1：此前这里只有 18 个，而验收用例的清单是 19 个、只断言 >= 18 ——
    "19 个窗口在 150% 下全部可见"那句证据实际只覆盖 18 个。第 19 个补进来后，
    tests/test_dialog_fit_v250.py 的断言同步收紧成 >= 19。
    v2.5.1：B 的插件管理对话框（PluginManagerDialog）补进来 → 20 个，断言收紧成 >= 20。
    **这份清单漏一个不会红**（1.5 倍那条只数行数），所以新对话框必须同时登记三处：
    _factories() / _DESIGN_SIZES / 这里。
    """
    import pet_dialogs as d
    return (
        ("RoleImportDialog", lambda p: d.RoleImportDialog(p)),
        ("RoleEditDialog", lambda p: d.RoleEditDialog(p)),
        ("BehaviorDialog", lambda p: d.BehaviorDialog(p, getattr(p, "behaviors", None))),
        ("AlarmDialog", lambda p: d.AlarmDialog(p, getattr(p, "alarms", None))),
        ("AISettingsDialog", lambda p: d.AISettingsDialog(p)),
        ("RolePanel", lambda p: d.RolePanel(p)),
        ("SoundPanel", lambda p: d.SoundPanel(p)),
        ("VoiceAssetPanel", lambda p: d.VoiceAssetPanel(p)),
        ("ResourceManagerDialog", lambda p: d.ResourceManagerDialog(p, 0)),
        ("ResourceManagerDialog(tab2)", lambda p: d.ResourceManagerDialog(p, 2)),
        ("AmountNoteDialog", lambda p: d.AmountNoteDialog(p)),
        ("LedgerDialog", lambda p: d.LedgerDialog(p)),
        ("BubbleStyleDialog", lambda p: d.BubbleStyleDialog(p)),
        ("LinesDialog", lambda p: d.LinesDialog(p)),
        ("PhysicsDialog", lambda p: d.PhysicsDialog(p)),
        ("VoiceDialog", lambda p: d.VoiceDialog(p)),
        ("IdleDialog", lambda p: d.IdleDialog(p)),
        ("_VoicePickDialog", lambda p: d._VoicePickDialog(p, p)),
        ("build_role_meta_dialog", lambda p: d.build_role_meta_dialog(p)[0]),
        # v2.5.1 代理B：插件管理（设计尺寸 760x520，登记口径见 _DESIGN_SIZES）
        ("PluginManagerDialog", lambda p: d.PluginManagerDialog(p)),
    )


# ---------------- 量尺寸 ----------------

def button_row_rect(win):
    """底排按钮行在**窗口坐标系**里的矩形 (x, y, w, h)；没有按钮行返回 None。

    必须用 stick_buttons() 记下的那一行，**不能**扫全部 QPushButton——内容区里也有大量
    按钮，它们被 QScrollArea 裁掉之后 isVisibleTo() 仍为 True，坐标却在窗口之外
    （实测：会把 RoleEditDialog 的"按钮下边界"报成 665，而窗口只有 540 高）。
    """
    row = getattr(win, "_btn_row", None)
    if row is None:
        return None
    g = row.geometry()
    return (g.x(), g.y(), g.width(), g.height())


def content_scroll_range(win):
    """(纵向, 横向) 滚动条可滚范围；没有滚动容器返回 (0, 0)。

    范围 > 0 = 内容真的被裁掉了、真的能滚（而不是"有个空壳容器"）。
    """
    area = getattr(win, "_scroll_area", None)
    if area is None:
        return (0, 0)
    return (int(area.verticalScrollBar().maximum()),
            int(area.horizontalScrollBar().maximum()))


def measure(win, app, screen=None):
    """把一个已构造好的窗口量成一行数据。调用方负责 show()/close()。"""
    if screen is None:
        screen = app.primaryScreen()
    avail = screen.availableGeometry()
    dpr = float(screen.devicePixelRatio())
    scrolls = win.findChildren(QScrollArea)
    return {
        "class": type(win).__name__,
        "is_dialog": isinstance(win, QDialog),
        "w": int(win.width()),
        "h": int(win.height()),
        "hint_w": int(win.sizeHint().width()),
        "hint_h": int(win.sizeHint().height()),
        "min_w": int(win.minimumSizeHint().width()),
        "min_h": int(win.minimumSizeHint().height()),
        "avail_w": int(avail.width()),
        "avail_h": int(avail.height()),
        "dpr": dpr,
        "scrolls": len(scrolls),
        "scroll_ok": any(s.widgetResizable() for s in scrolls),
        "btn_row": button_row_rect(win),
        "scroll_v": content_scroll_range(win)[0],
        "scroll_h": content_scroll_range(win)[1],
    }


def probe_shrink(win, app, target_w=200, target_h=120):
    """把窗口往小了拽，读回 Qt 实际允许的最小尺寸 —— 这就是"缩小不了"的量化。

    做法与用户拖边框一致：resize() 一次到很小，让布局按 SetDefaultConstraint 回弹。
    """
    win.resize(int(target_w), int(target_h))
    app.processEvents()
    return int(win.width()), int(win.height())


def fmt_row(m):
    row = m.get("btn_row")
    btn = "-" if row is None else "y=%d..%d" % (row[1], row[1] + row[3])
    return ("%-26s %4dx%-4d min=%4dx%-4d avail=%4dx%-4d dpr=%.2f "
            "scroll=%d vmax=%-5d btn_row=%s") % (
        m["class"], m["w"], m["h"], m["min_w"], m["min_h"],
        m["avail_w"], m["avail_h"], m["dpr"],
        m["scrolls"], m.get("scroll_v", 0), btn)
