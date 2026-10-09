import os, sys, time, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "."); sys.path.insert(0, "tests")
import 桌宠 as main
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
tmp = tempfile.mkdtemp()
main.DATA_DIR = tmp; main.CONFIG_PATH = os.path.join(tmp, "config.json")
main.USAGE_PATH = os.path.join(tmp, "usage.json"); main.MEMORY_PATH = os.path.join(tmp, "memory.json")
main.pet_log.set_data_dir(tmp)
app = QApplication([])
win = main.PetWindow()
from helpers_roles import install_three_form_role
install_three_form_role(win, tmp)
win.cfg["idle_form"] = "f3"
win.cfg["idle_trigger_delay"] = 3
win.cfg["idle_delay_after_full"] = 2
win.cfg["idle_actions"] = [{"id": "zzz1", "name": "打盹", "enabled": True, "weight": 1,
                            "steps": [{"act": "emote", "param": "zzz", "seconds": 1.5}]}]
res = win.apply_idle_settings(win.cfg)
print("apply_idle_settings ->", res)
print("idle cfg ->", win._idle_cfg())
print("idle_timer active:", win.idle_timer.isActive(), "interval:", win.idle_timer.interval())
_real = win.maybe_idle_behavior
T0 = time.monotonic()
def traced():
    now = time.monotonic()
    print("  tick %.2fs ready=%s anim=%s busy=%s digest=%s dt_activity=%.1f dt_idle=%.1f delay=%s" % (
        now - T0, win._idle_ready(), win.anim_mode, win.busy, win._digest_pending(),
        now - win._last_activity, now - getattr(win, "_last_idle_at", 0.0),
        win._idle_cfg().get("idle_trigger_delay")))
    return _real()
win.maybe_idle_behavior = traced
QTimer.singleShot(9000, app.quit)
app.exec()
print("final: form=%s idle_form_active=%s idle_active=%s" % (win.form, win._idle_form_active, win._idle_active))