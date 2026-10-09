import os, sys, time, tempfile, traceback
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".")
import 桌宠 as main
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

def run_case(feed_at, watch, label):
    tmp = tempfile.mkdtemp()
    main.DATA_DIR = tmp; main.CONFIG_PATH = os.path.join(tmp, "config.json")
    main.USAGE_PATH = os.path.join(tmp, "usage.json"); main.MEMORY_PATH = os.path.join(tmp, "memory.json")
    main.pet_log.set_data_dir(tmp)
    win = main.PetWindow()
    # 配置：无交互 8s、吃饱后 2s、一个简单待机动作
    win.cfg["idle_trigger_delay"] = 8
    win.cfg["idle_delay_after_full"] = 2
    b, err = win.behaviors.add("test_idle", [{"act": "say", "text": "zzZ"}, {"act": "wait", "ms": 1500}])
    if b is None:
        print("  add behavior FAIL", err)
        return
    win.cfg["idle_actions"] = [{"id": "t1", "behavior_id": b["id"], "enabled": True, "weight": 1.0, "order": 1}]
    win.cfg["idle_play_mode"] = "single"
    win.apply_idle_settings(win.cfg)
    T0 = time.monotonic()
    def ts(): return "%6.2fs" % (time.monotonic() - T0)
    def lg(*a): print("   ", ts(), *a)
    _set = win._set_form
    def setf(form, refresh=True, cancel_transform=True, display_only=False):
        if form != win.form:
            st = [f"{f.name}:{f.lineno}" for f in traceback.extract_stack()[-9:-1]]
            lg("SET_FORM %s -> %s  %s" % (win.form, form, " | ".join(st[-3:])))
        return _set(form, refresh, cancel_transform, display_only)
    win._set_form = setf
    _pa = win.actions.play_action
    win.actions.play_action = lambda name, arg=None, force=False: (lg("play_action", name, arg), _pa(name, arg, force))[1]
    _pick = win.actions._pick
    win.actions._pick = lambda: (lambda r: (lg("random_pick", r), r)[1])(_pick())
    _ss = win._show_state
    win._show_state = lambda s, d=2500: (lg("show_state", s), _ss(s, d))[1]
    _se = win._show_emote
    win._show_emote = lambda e: (lg("emote", e), _se(e))[1]
    _rs = win._start_idle
    win._start_idle = lambda src: (lg("START_IDLE(%s)" % src), _rs(src))[1]
    _ie = win._idle_end
    win._idle_end = lambda: (lg("IDLE_END"), _ie())[1]
    _dg = win._digest
    win._digest = lambda: (lg("DIGEST (form=%s)" % win.form), _dg())[1]
    _bs = win._behavior_step
    win._behavior_step = lambda g: (lg("BEHAVIOR_STEP (busy=%s, idle_active=%s)" % (win.busy, win._idle_active)), _bs(g))[1]
    print("== %s ==" % label)
    QTimer.singleShot(int(feed_at * 1000), lambda: (lg(">>> FEED"), win.feed("a")))
    QTimer.singleShot(int(watch * 1000), app.quit)
    app.exec()
    win._closing = True; win.voice.stop(); win.hide(); win.deleteLater()

app = QApplication([])
run_case(5.0, 30, "喂食 5s（消化 5~17s；tick 15s 落在消化窗口内）")