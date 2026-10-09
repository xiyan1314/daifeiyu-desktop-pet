import os, sys, time, traceback, tempfile
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
print("role=%r custom=%r forms=%r has_frames=%r" % (win.cfg.get("role"), win._custom_role, win.form_keys, win.has_frames))
print("idle cfg:", {k: v for k, v in win._idle_cfg().items() if k in ("idle_form", "idle_trigger_delay", "idle_delay_after_full", "idle_actions")})

T0 = time.monotonic()
def ts():
    return "%6.2fs" % (time.monotonic() - T0)

changes = []
_real_set = win._set_form
def traced_set(form, refresh=True, cancel_transform=True, display_only=False):
    if form != win.form:
        stack = [f"{f.name}:{f.lineno}" for f in traceback.extract_stack()[-6:-1]]
        changes.append((ts(), win.form, form, display_only, stack))
        print("  >> FORM %s -> %s display_only=%s  %s" % (win.form, form, display_only, " | ".join(stack)))
    return _real_set(form, refresh=refresh, cancel_transform=cancel_transform, display_only=display_only)
win._set_form = traced_set

def sample():
    print("%s form=%s anim=%s busy=%s digest=%s idle_form=%s user=%s" % (
        ts(), win.form, win.anim_mode, win.busy, win._digest_pending(), win._idle_form_active, win._user_form))

def feed():
    print("%s === FEED ===" % ts())
    win.feed("小鱼干")
    print("%s after feed: form=%s busy=%s digest=%s" % (ts(), win.form, win.busy, win._digest_pending()))

QTimer.singleShot(500, feed)
t = QTimer()
t.timeout.connect(sample)
t.start(1000)
QTimer.singleShot(20000, app.quit)
app.exec()
print("=== 形态变化次数: %d ===" % len(changes))
for c in changes:
    print("   ", c[0], c[1], "->", c[2], "display_only=", c[3], "|", " | ".join(c[4][-3:]))