import os, sys, time, traceback, tempfile, json
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
# 用户式配置：待机形态 = f3，待机动作 = 默认 zzz，无交互 3 秒触发，吃饱后 2 秒
win.cfg["idle_form"] = "f3"
win.cfg["idle_trigger_delay"] = 3
win.cfg["idle_delay_after_full"] = 2
win.cfg["idle_actions"] = [{"id": "zzz1", "name": "打盹", "enabled": True, "weight": 1,
                            "steps": [{"act": "emote", "param": "zzz", "seconds": 1.5}]}]
win.apply_idle_settings(win.cfg)
print("forms:", win.form_keys, "idle_form:", win._idle_cfg().get("idle_form"))

T0 = time.monotonic()
def ts(): return "%6.2fs" % (time.monotonic() - T0)
_real_set = win._set_form
def traced_set(form, refresh=True, cancel_transform=True, display_only=False):
    if form != win.form:
        stack = [f"{f.name}:{f.lineno}" for f in traceback.extract_stack()[-7:-1]]
        print("  >> FORM %s -> %s d=%s %s" % (win.form, form, display_only, " | ".join(stack[-4:])))
    return _real_set(form, refresh=refresh, cancel_transform=cancel_transform, display_only=display_only)
win._set_form = traced_set
def sample():
    print("%s form=%s anim=%s busy=%s digest=%s idle_form_active=%s idle_active=%s hold=%s user=%s" % (
        ts(), win.form, win.anim_mode, win.busy, win._digest_pending(), win._idle_form_active,
        win._idle_active, win._idle_hold_timer is not None, win._user_form))

# 场景：先让待机跑起来（等 4 秒），再喂食，看吃饱形态能撑多久
QTimer.singleShot(4000, lambda: (print("%s === FEED ===" % ts()), win.feed("小鱼干")))
t = QTimer(); t.timeout.connect(sample); t.start(1000)
QTimer.singleShot(22000, app.quit)
app.exec()