import os, sys, time, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".")
import 桌宠 as main
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
tmp = tempfile.mkdtemp()
main.DATA_DIR = tmp; main.CONFIG_PATH = os.path.join(tmp, "config.json")
main.USAGE_PATH = os.path.join(tmp, "usage.json"); main.MEMORY_PATH = os.path.join(tmp, "memory.json")
main.pet_log.set_data_dir(tmp)
app = QApplication([])
win = main.PetWindow()
win.cfg["idle_trigger_delay"] = 8
win.cfg["idle_delay_after_full"] = 2
win.apply_idle_settings(win.cfg)
T0 = time.monotonic()
def lg(*a): print("   %6.2fs" % (time.monotonic() - T0), *a)
_set = win._set_form
win._set_form = lambda form, *a, **k: (lg("SET_FORM %s -> %s" % (win.form, form)), _set(form, *a, **k))[1]
_dg = win._digest
win._digest = lambda: (lg("DIGEST (form=%s)" % win.form), _dg())[1]

# 场景1：用户选定形态 = 吃饱（full）
win.set_user_form("full")
lg("user form =", win._user_form)
QTimer.singleShot(3000, lambda: (lg(">>> FEED（用户形态=吃饱）"), win.feed("a")))
QTimer.singleShot(9000, lambda: (lg(">>> CLICK（恢复用户形态）"), win._touch_activity()))
QTimer.singleShot(18000, app.quit)
app.exec()
win._closing = True; win.voice.stop(); win.hide(); win.deleteLater()