import os, sys, time, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".")
import 桌宠 as main
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
main.DIGEST_MS = 3000   # 把消化压到 3s，便于测量

def run_case(name, feed_at=None, click_at=None, watch=16):
    tmp = tempfile.mkdtemp()
    main.DATA_DIR = tmp; main.CONFIG_PATH = os.path.join(tmp, "config.json")
    main.USAGE_PATH = os.path.join(tmp, "usage.json"); main.MEMORY_PATH = os.path.join(tmp, "memory.json")
    main.pet_log.set_data_dir(tmp)
    win = main.PetWindow()
    win.cfg["idle_trigger_delay"] = 8
    win.cfg["idle_delay_after_full"] = 2
    win.cfg["idle_form"] = ""
    win.apply_idle_settings(win.cfg)
    T0 = time.monotonic()
    events = []
    _real_start = win._start_idle
    def traced(source):
        events.append((time.monotonic() - T0, source, win.form))
        return _real_start(source)
    win._start_idle = traced
    _real_digest = win._digest
    def traced_digest():
        events.append((time.monotonic() - T0, "DIGEST", win.form))
        return _real_digest()
    win._digest = traced_digest
    print("== %s ==" % name)
    if feed_at is not None:
        QTimer.singleShot(int(feed_at * 1000), lambda: (events.append((time.monotonic() - T0, "FEED", win.form)), win.feed("a")))
    if click_at is not None:
        QTimer.singleShot(int(click_at * 1000), lambda: (events.append((time.monotonic() - T0, "CLICK", win.form)), win._touch_activity()))
    t = QTimer(); t.timeout.connect(win.maybe_idle_behavior); t.start(500)   # 模拟 tick（真实 15s 粒度太粗）
    QTimer.singleShot(int(watch * 1000), lambda: (t.stop(), app.quit()))
    app.exec()
    for e in events:
        print("   %5.2fs  %-9s form=%s" % (e[0], e[1], e[2]))
    win._closing = True; win.voice.stop(); win.hide(); win.deleteLater()

app = QApplication([])
run_case("A 无交互（期望 ~8s 待机）")
run_case("B 喂食后（期望 消化后 +2s 待机）", feed_at=1.0)
run_case("C 喂食 + 消化后点击（期望 点击后 8s）", feed_at=1.0, click_at=4.5)