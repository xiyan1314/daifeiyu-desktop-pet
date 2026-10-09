import os, sys, time, traceback, tempfile
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
win.apply_idle_settings(win.cfg)
T0 = time.monotonic()
def ts(): return "%6.2fs" % (time.monotonic() - T0)
_real_set = win._set_form
def traced_set(form, refresh=True, cancel_transform=True, display_only=False):
    if form != win.form:
        stack = [f"{f.name}:{f.lineno}" for f in traceback.extract_stack()[-7:-1]]
        print("  >> FORM %s -> %s d=%s %s" % (win.form, form, display_only, " | ".join(stack[-4:])))
    return _real_set(form, refresh=refresh, cancel_transform=cancel_transform, display_only=display_only)
win._set_form = traced_set
def st(tag):
    print("%s %-26s form=%s busy=%s digest=%s idle_form_active=%s user=%s" % (
        ts(), tag, win.form, win.busy, win._digest_pending(), win._idle_form_active, win._user_form))

def scenario():
    st("start")
    win._start_idle("idle")            # 让待机（形态展示期）先跑起来（等价于已到点）
    st("after idle start")
    win.feed("小鱼干")                 # 待机中喂食
    st("after feed")
    win._eat_done("sim")               # 吃帧收尾（真实里 1.5s 后自动发生）
    st("after eat_done")
    win._touch_activity()              # 用户点一下（真实里就是点桌宠）
    st("after click(1)")
    win._wake()                        # 再点一下（含 _wake 路径）
    st("after wake")
    win._on_voice_finished("d", "")    # 或语音读完
    st("after voice finished")

QTimer.singleShot(800, scenario)
QTimer.singleShot(2500, app.quit)
app.exec()