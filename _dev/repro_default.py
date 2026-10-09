import os, sys, time, tempfile, traceback
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
print("forms=", win.form_keys, "role=", repr(win.cfg.get("role")), "has_frames=", win.has_frames)
T0 = time.monotonic()
def ts(): return "%6.2fs" % (time.monotonic() - T0)
def lg(*a): print("   ", ts(), *a)

_set = win._set_form
def setf(form, refresh=True, cancel_transform=True, display_only=False):
    if form != win.form:
        st = [f"{f.name}:{f.lineno}" for f in traceback.extract_stack()[-8:-1]]
        lg("SET_FORM %s -> %s  %s" % (win.form, form, " | ".join(st[-3:])))
    return _set(form, refresh, cancel_transform, display_only)
win._set_form = setf
_pa = win.actions.play_action
win.actions.play_action = lambda name, arg=None: (lg("play_action", name, arg), _pa(name, arg))[1]
_pick = win.actions._pick
win.actions._pick = lambda: (lambda r: (lg("random_pick", r), r)[1])(_pick())
_ss = win._show_state
win._show_state = lambda s, d=2500: (lg("show_state", s, d), _ss(s, d))[1]
_se = win._show_emote
win._show_emote = lambda e: (lg("emote", e), _se(e))[1]
_sleep = win._show_sleep
win._show_sleep = lambda: (lg("SHOW_SLEEP"), _sleep())[1]
_eat = win._play_eat
win._play_eat = lambda: (lg("PLAY_EAT"), _eat())[1]
_ed = win._eat_done
win._eat_done = lambda n: (lg("EAT_DONE"), _ed(n))[1]
_dg = win._digest
win._digest = lambda: (lg("DIGEST (form=%s)" % win.form), _dg())[1]

def feed():
    lg(">>> FEED")
    win.feed("小鱼干")
QTimer.singleShot(5000, feed)
QTimer.singleShot(45000, app.quit)
app.exec()