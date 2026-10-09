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
print("forms:", win.form_keys)
T0 = time.monotonic()
_real = win._set_form
def traced(form, refresh=True, cancel_transform=True, display_only=False):
    if form != win.form:
        print("   %5.1fs %s -> %s" % (time.monotonic() - T0, win.form, form))
    return _real(form, refresh=refresh, cancel_transform=cancel_transform, display_only=display_only)
win._set_form = traced
QTimer.singleShot(2000, lambda: (print("2.0s 第一次喂食"), win.feed("a")))
QTimer.singleShot(6000, lambda: (print("6.0s 第二次喂食（消化中）"), win.feed("b")))
QTimer.singleShot(9000, lambda: (print("9.0s 第三次喂食（消化中）"), win.feed("c")))
QTimer.singleShot(20000, app.quit)
app.exec()
print("结束 form=%s user=%s" % (win.form, win._user_form))