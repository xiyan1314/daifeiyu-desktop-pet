import os, sys, time, tempfile, traceback
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".")
sys.path.insert(0, "tests")
import 桌宠 as main
from helpers_roles import install_three_form_role
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

def run_case(after_full, label):
    tmp = tempfile.mkdtemp()
    main.DATA_DIR = tmp; main.CONFIG_PATH = os.path.join(tmp, "config.json")
    main.USAGE_PATH = os.path.join(tmp, "usage.json"); main.MEMORY_PATH = os.path.join(tmp, "memory.json")
    main.pet_log.set_data_dir(tmp)
    win = main.PetWindow()
    install_three_form_role(win, tmp)   # f0 常态 / f1 变身+吃帧 / f2 睡觉 no_feed / f3 待机形态
    win.cfg["idle_trigger_delay"] = 8
    win.cfg["idle_delay_after_full"] = after_full
    b, err = win.behaviors.add("test_idle", [{"act": "say", "text": "zzZ"}, {"act": "wait", "ms": 1500}])
    win.cfg["idle_actions"] = [{"id": "t1", "behavior_id": b["id"], "enabled": True, "weight": 1.0, "order": 1}]
    win.cfg["idle_play_mode"] = "single"
    win.cfg["idle_form"] = "f3"
    win.apply_idle_settings(win.cfg)
    T0 = time.monotonic()
    def ts(): return "%6.2fs" % (time.monotonic() - T0)
    def lg(*a): print("   ", ts(), *a)
    _set = win._set_form
    def setf(form, refresh=True, cancel_transform=True, display_only=False):
        if form != win.form:
            st = [f"{f.name}:{f.lineno}" for f in traceback.extract_stack()[-8:-1]]
            lg("SET_FORM %s -> %s  %s" % (win.form, form, " | ".join(st[-2:])))
        return _set(form, refresh, cancel_transform, display_only)
    win._set_form = setf
    _rs = win._start_idle
    win._start_idle = lambda src: (lg("START_IDLE(%s)" % src), _rs(src))[1]
    _ie = win._idle_end
    win._idle_end = lambda: (lg("IDLE_END"), _ie())[1]
    _dg = win._digest
    win._digest = lambda: (lg("DIGEST (form=%s)" % win.form), _dg())[1]
    _bs = win._behavior_step
    win._behavior_step = lambda g: (lg("BEHAVIOR_STEP (busy=%s)" % win.busy), _bs(g))[1]
    print("== %s ==" % label)
    QTimer.singleShot(5000, lambda: (lg(">>> FEED"), win.feed("a")))
    QTimer.singleShot(30000, app.quit)
    app.exec()
    win._closing = True; win.voice.stop(); win.hide(); win.deleteLater()

app = QApplication([])
run_case(2, "4 形态角色 + 待机形态 f3 + 待机动作；吃饱后 2s")