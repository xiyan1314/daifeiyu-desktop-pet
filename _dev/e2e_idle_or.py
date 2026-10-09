import os, sys, time, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".")
import 桌宠 as main
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
main.DIGEST_MS = 3000

def run_case(name, feed_at=None, watch=12):
    tmp = tempfile.mkdtemp()
    main.DATA_DIR = tmp; main.CONFIG_PATH = os.path.join(tmp, "config.json")
    main.USAGE_PATH = os.path.join(tmp, "usage.json"); main.MEMORY_PATH = os.path.join(tmp, "memory.json")
    main.pet_log.set_data_dir(tmp)
    win = main.PetWindow()
    win.cfg["idle_trigger_delay"] = 8
    win.cfg["idle_delay_after_full"] = 2
    win.apply_idle_settings(win.cfg)
    T0 = time.monotonic()
    ev = []
    _rs = win._start_idle
    win._start_idle = lambda src: (ev.append((time.monotonic() - T0, "IDLE(%s)" % src)), _rs(src))[1]
    _rd = win._digest
    win._digest = lambda: (ev.append((time.monotonic() - T0, "DIGEST")), _rd())[1]
    print("== %s ==" % name)
    if feed_at is not None:
        QTimer.singleShot(int(feed_at * 1000), lambda: (ev.append((time.monotonic() - T0, "FEED")), win.feed("a")))
    QTimer.singleShot(int(watch * 1000), app.quit)
    app.exec()
    for e in ev:
        print("   %5.2fs  %-10s" % e)
    win._closing = True; win.voice.stop(); win.hide(); win.deleteLater()

app = QApplication([])
run_case("A 无喂食：期望 ~8s 待机（触发 B）")
run_case("B 喂食：期望 消化(4s) + 2s = ~6s 待机（触发 A）", feed_at=1.0, watch=12)