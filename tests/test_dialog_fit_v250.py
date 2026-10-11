# -*- coding: utf-8 -*-
"""v2.5.0（代理 B）对话框尺寸与可滚动性验收 —— 用户报的真实问题。

用户现象：「有些窗口内容多、窗口大、**看不到底**，而且**缩小不了**——底部内容
（说明文字、列表末尾，或确定/取消按钮）够不到。」

体检结论（_dev/dialog_size_report.md，实测数据）：全文件 QScrollArea 出现 0 次；
尺寸靠 self.resize(W, H) 写死；minimumSizeHint 被布局顶到 508x740 / 610x706 /
622x903（VoiceDialog 在 800x800 的逻辑屏上都装不下）。修法是一套：

    scroll_content(dlg)    → 内容区进 QScrollArea
    stick_buttons(dlg,row) → 按钮行留在滚动区之外
    clamp_dialog(dlg,W,H)  → 尺寸钳进屏幕可用区域（上限 = 可用区域 × 85%）

本文件的每条断言都对着一个**能真失败**的点：
  · 拿掉 clamp_dialog        → 尺寸不超屏 / 上限就是85% 红；
  · 拿掉 scroll_content      → 有滚动容器 / 没有裸顶层布局 红；
  · 按钮行挪进滚动区         → 按钮行在滚动区之外 红；
  · 下限保护改成无条件 320   → 本来就小的框不被撑大 红。

高 DPI（QT_SCALE_FACTOR=1.5）不是靠"再跑一遍同样的断言"覆盖的——屏幕逻辑区域会
真的变小（800x800 → 533x533），所以另起一条**子进程**用例跑真环境变量（模块内改
QT_SCALE_FACTOR 对已经建好的 QApplication 无效，改了也白改）。
"""
import json
import os
import subprocess
import sys
import tempfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pet_dialogs  # noqa: E402

from PySide6.QtCore import QRect, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QScrollArea  # noqa: E402


# ---------------- 真 PetWindow（照抄 tests/test_dialogs_more_v24.py 的隔离套路） ----------------

def _boot_application():
    app = QApplication.instance()
    if isinstance(app, QApplication):
        return app
    return QApplication([])


_APP = _boot_application()


def _ensure_qapplication():
    app = QApplication.instance()
    if isinstance(app, QApplication):
        return app
    pytest.fail("进程里只有 QCoreApplication（不是 QApplication），QWidget 无法构造——"
                "先单独跑本模块，或修掉那个先建 QCoreApplication 的模块。", pytrace=False)


def _shutdown_pet(win):
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


@pytest.fixture(scope="module")
def pet(tmp_path_factory):
    import pet_log
    import 桌宠 as main
    tmp = tmp_path_factory.mktemp("dlgfit250")
    _snap = (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
             getattr(pet_log, "_data_dir", None))
    main.DATA_DIR = str(tmp)
    main.CONFIG_PATH = str(tmp / "config.json")
    main.USAGE_PATH = str(tmp / "usage.json")
    main.MEMORY_PATH = str(tmp / "memory.json")
    pet_log.set_data_dir(str(tmp))
    _ensure_qapplication()
    win = main.PetWindow()
    yield win
    _shutdown_pet(win)
    QApplication.processEvents()
    (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH) = _snap[:4]
    pet_log.set_data_dir(_snap[4])


@pytest.fixture()
def no_modal(monkeypatch):
    """_warn/_info/_confirm 内部走 modal()=exec()，offscreen 下会挂死测试进程。"""
    seen = []
    for name in ("_warn", "_info", "_confirm"):
        monkeypatch.setattr(pet_dialogs, name,
                            (lambda n: (lambda *a, **k: seen.append((n, a, k))))(name))
    return seen


# ---------------- 全量对话框清单 ----------------

def _factories():
    """(名字, 造窗口) —— 14 个 QDialog + 3 个内嵌面板 + 2 个内联框。

    面板与内联框也进来：面板会把 ResourceManagerDialog 的最小尺寸顶大（实测 640 宽），
    内联框（角色信息 / 程序化合成动作）此前是**裸 QDialog**，完全没有屏幕钳制。
    """
    return (
        ("RoleImportDialog", lambda p: pet_dialogs.RoleImportDialog(p)),
        ("RoleEditDialog", lambda p: pet_dialogs.RoleEditDialog(p)),
        ("BehaviorDialog", lambda p: pet_dialogs.BehaviorDialog(p, p.behaviors)),
        ("AlarmDialog", lambda p: pet_dialogs.AlarmDialog(p, p.alarms)),
        ("AISettingsDialog", lambda p: pet_dialogs.AISettingsDialog(p)),
        ("RolePanel", lambda p: pet_dialogs.RolePanel(p)),
        ("SoundPanel", lambda p: pet_dialogs.SoundPanel(p)),
        ("VoiceAssetPanel", lambda p: pet_dialogs.VoiceAssetPanel(p)),
        ("ResourceManagerDialog", lambda p: pet_dialogs.ResourceManagerDialog(p, 0)),
        ("ResourceManagerDialog(tab2)", lambda p: pet_dialogs.ResourceManagerDialog(p, 2)),
        ("AmountNoteDialog", lambda p: pet_dialogs.AmountNoteDialog(p)),
        ("LedgerDialog", lambda p: pet_dialogs.LedgerDialog(p)),
        ("BubbleStyleDialog", lambda p: pet_dialogs.BubbleStyleDialog(p)),
        ("LinesDialog", lambda p: pet_dialogs.LinesDialog(p)),
        ("PhysicsDialog", lambda p: pet_dialogs.PhysicsDialog(p)),
        ("VoiceDialog", lambda p: pet_dialogs.VoiceDialog(p)),
        ("IdleDialog", lambda p: pet_dialogs.IdleDialog(p)),
        ("_VoicePickDialog", lambda p: pet_dialogs._VoicePickDialog(p, p)),
        ("build_role_meta_dialog", lambda p: pet_dialogs.build_role_meta_dialog(p)[0]),
    )


ALL_NAMES = tuple(n for n, _ in _factories())
_FACTORY_MAP = dict(_factories())

# 面板是嵌在页签里的 QWidget（不是顶层窗口），没有"底排按钮行"这回事，
# 尺寸由容器钳制，B3-3 与"最大值"判据不适用于它们。
NO_BUTTON_ROW = ("RolePanel", "SoundPanel", "VoiceAssetPanel")

# 小屏 = 1024x600 逻辑像素（≈ 1080p 屏 + 150% 缩放：1280x720 再扣任务栏）。
# 注入的是**逻辑像素**：物理像素 = 逻辑 × devicePixelRatio，所以这条注入同时代表
# "768 高的屏 @100%"和"1080p 的高 DPI 缩放"——两种情形下这些窗口都装不下。
SMALL = QRect(0, 0, 1024, 600)


def _show(pet, name):
    dlg = _FACTORY_MAP[name](pet)
    dlg.show()
    QApplication.processEvents()
    return dlg


@pytest.fixture()
def small_screen(monkeypatch):
    monkeypatch.setattr(pet_dialogs, "dialog_available_geometry",
                        lambda widget=None: QRect(SMALL))
    return SMALL


# ---------------- B3 主判据：一个窗口一次构造，量三项 ----------------
# （三条判据分三个用例会让 19 个窗口各构造 3 次——实测整套多花 ~2 分钟；
#   合成一条后失败信息里仍然点名是哪个窗口、哪一条不满足。）

@pytest.mark.parametrize("name", ALL_NAMES)
def test_每个窗口都不超屏_能滚到底_按钮可见(pet, no_modal, small_screen, name):
    min_w, min_h, max_w, max_h = pet_dialogs.dialog_size_limits(None)
    assert (max_w, max_h) == (int(SMALL.width() * pet_dialogs.DIALOG_MAX_RATIO),
                              int(SMALL.height() * pet_dialogs.DIALOG_MAX_RATIO))
    dlg = _show(pet, name)
    try:
        # ---- 1) 尺寸钳进屏幕可用区域（「看不到底」的直接判据）----
        assert dlg.width() <= max_w, "%s 宽 %d 超上限 %d" % (name, dlg.width(), max_w)
        assert dlg.height() <= max_h, "%s 高 %d 超上限 %d" % (name, dlg.height(), max_h)
        if isinstance(dlg, pet_dialogs._FitDialog):
            assert dlg.maximumWidth() <= max_w, "%s 的最大宽没被钳制" % name
            assert dlg.maximumHeight() <= max_h, "%s 的最大高没被钳制" % name

        # ---- 2) 内容区有真滚动容器 ----
        area = getattr(dlg, "_scroll_area", None)
        body = getattr(dlg, "_content_body", None)
        assert isinstance(area, QScrollArea), "%s 没有滚动容器（内容会被裁掉、够不到底）" % name
        assert area.widgetResizable(), "%s 的滚动容器不跟随窗口伸缩" % name
        assert area in dlg.findChildren(QScrollArea), "%s 的滚动容器没挂进窗口树" % name

        # ---- 3) 拖到下限之后，被裁掉的内容仍然滚得到 ----
        dlg.resize(dlg.minimumWidth(), dlg.minimumHeight())
        QApplication.processEvents()
        QApplication.processEvents()
        vmax = area.verticalScrollBar().maximum()
        hmax = area.horizontalScrollBar().maximum()
        # 内容能缩到视口里（minimumSizeHint 装得下）就不需要滚动条——
        # 这里必须比 **minimumSizeHint**：widgetResizable 的滚动区把内容壳缩到
        # 它的最小尺寸，sizeHint 只是"想要的尺寸"，Qt 不会为它出滚动条。
        fits_v = body.minimumSizeHint().height() <= area.viewport().height() + 1
        fits_h = body.minimumSizeHint().width() <= area.viewport().width() + 1
        assert vmax > 0 or fits_v, (
            "%s：内容最小高度 %d 超过视口 %d 却纵向滚不动（vmax=0，底部够不到）" % (
                name, body.minimumSizeHint().height(), area.viewport().height()))
        assert hmax > 0 or fits_h, (
            "%s：内容最小宽度 %d 超过视口 %d 却横向滚不动（hmax=0）" % (
                name, body.minimumSizeHint().width(), area.viewport().width()))
        area.verticalScrollBar().setValue(vmax)
        QApplication.processEvents()
        assert area.verticalScrollBar().value() == vmax, "%s 滚不到底" % name

        # ---- 4) 按钮行在滚动区之外、压到下限也在窗口内 ----
        if name in NO_BUTTON_ROW:
            return
        row = getattr(dlg, "_btn_row", None)
        assert row is not None, "%s 没有记下底排按钮行" % name
        outer = dlg.layout()
        assert outer is not None and outer.indexOf(row) >= 0, (
            "%s 的按钮行没挂在外层布局上（于是会被滚走）" % name)
        assert body.layout().indexOf(row) < 0, (
            "%s 的按钮行被放进了滚动区（内容一滚，确定/取消就没了）" % name)
        g = row.geometry()
        assert g.top() >= 0, "%s 的按钮行跑到窗口上边之外" % name
        assert g.bottom() <= dlg.height(), (
            "%s 拖到最小时按钮行跑出窗口（bottom=%d > h=%d）" % (name, g.bottom(), dlg.height()))
    finally:
        dlg.close()


def test_上限就是85百分比而不是写死像素(pet, no_modal, monkeypatch):
    """换一块更大的屏，上限必须跟着变大——钉住"按可用区域的百分比算逻辑像素"。

    变异：把上限写成常量（比如 510 = 600 x 0.85）就红。
    """
    monkeypatch.setattr(pet_dialogs, "dialog_available_geometry",
                        lambda widget=None: QRect(0, 0, 2000, 1200))
    assert pet_dialogs.dialog_size_limits(None)[2:] == (1700, 1020)
    dlg = _show(pet, "VoiceDialog")   # 设计尺寸 700x640：2000x1200 屏上不该被削
    try:
        assert (dlg.width(), dlg.height()) == (700, 640)
    finally:
        dlg.close()


def test_大窗口不再是缩小不了(pet, no_modal, small_screen):
    """用户原话：「而且缩小不了」。钉住下限确实降下来了。

    改动前（真实实测）：RoleImportDialog 最小 508x740、RoleEditDialog 610x706、
    VoiceDialog 622x903 —— 全都大于 600 高的屏，用户拖不动、底部够不到。
    """
    for name in ("RoleImportDialog", "RoleEditDialog", "VoiceDialog", "LinesDialog"):
        dlg = _show(pet, name)
        try:
            assert dlg.minimumHeight() <= 240, "%s 仍然缩不下去（min_h=%d）" % (
                name, dlg.minimumHeight())
            assert dlg.minimumWidth() <= 320, "%s 仍然缩不下去（min_w=%d）" % (
                name, dlg.minimumWidth())
            dlg.resize(320, 240)
            QApplication.processEvents()
            assert dlg.height() <= 240, "%s 拖到 240 高仍被布局顶回去" % name
        finally:
            dlg.close()


def test_本来就小的框不被撑大(pet, no_modal):
    """下限保护不能变成"下限托盘"：286x113 的「记一笔」必须还是 286x113。

    变异：把下限写成无条件的 DIALOG_MIN_W/H（320x240）就红。
    """
    for name, want in (("AmountNoteDialog", (286, 113)), ("BubbleStyleDialog", (282, 302))):
        dlg = _show(pet, name)
        try:
            assert (dlg.width(), dlg.height()) == want, (
                "%s 被下限撑成了 %dx%d（应保持 %s）" % (name, dlg.width(), dlg.height(), want))
        finally:
            dlg.close()


# ---------------- B3-4：模式层面钉住（拿掉任何一处就红） ----------------

def _calls_with_owner(tree):
    """[(Call 节点, 所在函数名)] —— 一趟 O(n) 遍历。

    不要写成"每个 Call 都 ast.walk 一遍找外层函数"：pet_dialogs.py 有 25 万字符、
    上万个节点，那样是 O(n^2)，实测这一条用例要跑 **198 秒**（整个模块 205 秒）。
    """
    import ast
    out = []

    def rec(node, owner):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                rec(child, child.name)
            else:
                if isinstance(child, ast.Call):
                    out.append((child, owner))
                rec(child, owner)

    rec(tree, "")
    return out


def test_pet_dialogs里没有裸顶层布局也没有写死resize():
    """静态钉住修法本身：以后新增的对话框漏了这一套，这条立刻红。

    - 顶层布局必须来自 scroll_content()（否则没有滚动容器）；
    - 不得再出现 self.resize(字面量, 字面量) 这种写死窗口尺寸。
    三个助手（scroll_content / stick_buttons / clamp_dialog）自身的实现豁免。
    """
    import ast
    import io
    src = io.open(os.path.join(ROOT, "pet_dialogs.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    HELPER_OK = ("scroll_content", "stick_buttons", "clamp_dialog")

    bad_layout, bad_resize = [], []
    for node, owner in _calls_with_owner(tree):
        if owner in HELPER_OK:
            continue
        fn = node.func
        if (isinstance(fn, ast.Name) and fn.id in ("QVBoxLayout", "QHBoxLayout")
                and len(node.args) >= 1 and isinstance(node.args[0], ast.Name)
                and node.args[0].id in ("self", "dlg")):
            bad_layout.append("%d: %s(%s)" % (node.lineno, fn.id, node.args[0].id))
        if (isinstance(fn, ast.Attribute) and fn.attr == "resize"
                and len(node.args) == 2
                and all(isinstance(a, ast.Constant) and isinstance(a.value, int)
                        for a in node.args)):
            bad_resize.append("%d: %s.resize(%s, %s)" % (
                node.lineno, ast.unparse(fn.value), node.args[0].value, node.args[1].value))

    assert bad_layout == [], (
        "这些行还在用裸的 QVBoxLayout(self) 当顶层布局（应为 scroll_content(self)）：%r"
        % (bad_layout,))
    assert bad_resize == [], (
        "这些行还在写死窗口尺寸（应改成 clamp_dialog(self, W, H)）：%r" % (bad_resize,))


def test_所有对话框都继承同一个可钳制基类():
    """_FitDialog.showEvent 是"换屏/换缩放后再钳一次"的唯一落点，14 个对话框都不能漏。"""
    import inspect
    dialogs = [pet_dialogs.RoleImportDialog, pet_dialogs.RoleEditDialog,
               pet_dialogs.BehaviorDialog, pet_dialogs.AlarmDialog,
               pet_dialogs.AISettingsDialog, pet_dialogs.ResourceManagerDialog,
               pet_dialogs.AmountNoteDialog, pet_dialogs.LedgerDialog,
               pet_dialogs.BubbleStyleDialog, pet_dialogs.LinesDialog,
               pet_dialogs.PhysicsDialog, pet_dialogs.VoiceDialog,
               pet_dialogs.IdleDialog, pet_dialogs._VoicePickDialog]
    for cls in dialogs:
        assert issubclass(cls, pet_dialogs._FitDialog), "%s 没继承 _FitDialog" % cls.__name__
    assert "showEvent" in pet_dialogs._FitDialog.__dict__
    assert "clamp_dialog" in inspect.getsource(pet_dialogs._FitDialog.showEvent)


def test_取不到屏幕时不崩也不设上限(monkeypatch):
    """防御性判据：屏幕信息拿不到时不能抛（构造期抛异常 = 这个对话框打不开）。"""
    monkeypatch.setattr(pet_dialogs, "dialog_available_geometry", lambda widget=None: None)
    assert pet_dialogs.dialog_size_limits(None) == (pet_dialogs.DIALOG_MIN_W,
                                                    pet_dialogs.DIALOG_MIN_H,
                                                    16777215, 16777215)


# ---------------- B3-5：高 DPI（真 QT_SCALE_FACTOR=1.5 子进程） ----------------

def test_高DPI1_5下所有窗口仍不超屏():
    """在 QT_SCALE_FACTOR=1.5 的真环境里跑一遍体检脚本。

    为什么必须子进程：QT_SCALE_FACTOR 是**建 QApplication 之前**读的环境变量，
    模块内改它对已经存在的应用单例无效（改了也白改，测试会假绿）。

    1.5 缩放下 offscreen 屏的逻辑可用区域是 533x533（= 800 / 1.5），上限 453 ——
    改动前 VoiceDialog 是 700x903、RoleImportDialog 是 600x740，这条在改动前必红。
    """
    probe = os.path.join(HERE, "_probe_dialog_sizes.py")
    if not os.path.isfile(probe):
        pytest.skip("体检脚本不在（%s）" % probe)
    fd, out_json = tempfile.mkstemp(suffix=".json", prefix="dlgfit150_")
    os.close(fd)
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QT_SCALE_FACTOR"] = "1.5"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.run([sys.executable, "-B", probe, "--json", out_json],
                              cwd=ROOT, env=env, capture_output=True, timeout=900)
        assert proc.returncode == 0, "1.5 缩放下体检脚本失败：%s" % (
            proc.stderr.decode("utf-8", "replace")[-2000:],)
        with open(out_json, encoding="utf-8") as f:
            data = json.load(f)
    finally:
        try:
            os.remove(out_json)
        except OSError:
            pass
    rows = data["rows"]
    assert len(rows) >= 18, "体检脚本没跑全（只拿到 %d 行）" % len(rows)
    bad = []
    for r in rows:
        if not r["ok"]:
            bad.append("%s 构造失败：%s" % (r["name"], r["error"]))
            continue
        if float(r["dpr"]) != 1.5:
            bad.append("%s 没跑在 1.5 缩放下（dpr=%s）" % (r["name"], r["dpr"]))
        max_w = int(r["avail_w"] * pet_dialogs.DIALOG_MAX_RATIO)
        max_h = int(r["avail_h"] * pet_dialogs.DIALOG_MAX_RATIO)
        if r["w"] > max_w or r["h"] > max_h:
            bad.append("%s = %dx%d 超过 %dx%d" % (r["name"], r["w"], r["h"], max_w, max_h))
        if r["scrolls"] < 1:
            bad.append("%s 没有滚动容器" % r["name"])
        br = r.get("btn_row")
        if br is not None and br[1] + br[3] > r["h"]:
            bad.append("%s 按钮行跑出窗口（bottom=%d > h=%d）" % (
                r["name"], br[1] + br[3], r["h"]))
    head = "1.5 缩放（逻辑可用 %dx%d）下有窗口超屏：" % (rows[0]["avail_w"], rows[0]["avail_h"])
    assert bad == [], head + chr(10) + chr(10).join(bad)
