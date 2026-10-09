import os, sys, time, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".")
import 桌宠 as main
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

def run_case(name, idle_form, feed_at, watch=40, idle_delay=8, after_full=2):
    tmp = tempfile.mkdtemp()
    main.DATA_DIR = tmp; main.CONFIG_PATH = os.path.join(tmp, "config.json")
    main.USAGE_PATH = os.path.join(tmp, "usage.json"); main.MEMORY_PATH = os.path.join(tmp, "memory.json")
    main.pet_log.set_data_dir(tmp)
    win = main.PetWindow()
    win.cfg["idle_form"] = idle_form
    win.cfg["idle_trigger_delay"] = idle_delay
    win.cfg["idle_delay_after_full"] = after_full
    win.apply_idle_settings(win.cfg)
    print("=" * 70)
    print("CASE %s  role=%r forms=%s idle_form=%r delay=%s after_full=%s" % (
        name, win.cfg.get("role"), win.form_keys, win._idle_cfg().get("idle_form"),
        win._idle_cfg().get("idle_trigger_delay"), win._idle_cfg().get("idle_delay_after_full")))
    T0 = time.monotonic()
    log = []
    _real = win._set_form
    def traced(form, refresh=True, cancel_transform=True, display_only=False):
        if form != win.form:
            log.append("%5.1fs %s -> %s%s" % (time.monotonic() - T0, win.form, form,
                                              " (临时展示)" if display_only else ""))
        return _real(form, refresh=refresh, cancel_transform=cancel_transform, display_only=display_only)
    win._set_form = traced
    def tick():
        win._last_activity = win._last_activity if False else win._last_activity
        win.maybe_idle_behavior()   # 模拟每拍检查（真实 idle_timer 15s 一拍）
    t1 = QTimer(); t1.timeout.connect(tick); t1.start(1000)
    QTimer.singleShot(int(feed_at * 1000), lambda: win.feed("小鱼干"))
    QTimer.singleShot(int(watch * 1000), lambda: (t1.stop(), app.quit()))
    app.exec()
    print("  形态变化时间线：")
    for l in log:
        print("   ", l)
    print("  结束态：form=%s user=%s" % (win.form, win._user_form))
    win._closing = True; win.voice.stop(); win.hide(); win.deleteLater()

app = QApplication([])
# 场景 1：默认角色，不配待机形态（用户最朴素用法）：喂食后吃饱形态应保持 ~12s
run_case("默认角色/无待机形态", "", feed_at=3, watch=20)
# 场景 2：默认角色，待机形态=常态（吃饱形态=full）：待机展示期里喂食 → 必须出现吃饱形态并保持
run_case("待机形态=常态(待机展示中喂食)", "normal", feed_at=12, watch=28)
# 场景 3：默认角色，待机形态=吃饱(full)：待机展示期里喂食 → 也不能把吃饱吞掉/跳过
run_case("待机形态=吃饱(待机展示中喂食)", "full", feed_at=12, watch=28)