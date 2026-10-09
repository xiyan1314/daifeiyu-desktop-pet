import os, sys, time, tempfile
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
T0 = time.monotonic()
def lg(*a): print("   %6.2fs" % (time.monotonic() - T0), *a)
_ss = win._show_state
win._show_state = lambda s, d=2500: (lg("show_state", s), _ss(s, d))[1]
_se = win._show_emote
win._show_emote = lambda e: (lg("emote", e), _se(e))[1]
_pa = win.actions.play_action
win.actions.play_action = lambda n, a=None, f=False: (lg("play_action", n, a), _pa(n, a, f))[1]
_pick = win.actions._pick
win.actions._pick = lambda: (lambda r: (lg("random_pick", r), r)[1])(_pick())

QTimer.singleShot(5000, lambda: (lg(">>> FEED"), win.feed("a")))
# 消化窗口内（8s/12s）强制调皮事件 + 情绪气泡 + 表情符号
QTimer.singleShot(8000, lambda: (lg("force mischief @8s (消化中)"), win._on_mood_state("smug"), win._mood_bubble("嘻嘻"), win._mood_emote("sparkle")))
QTimer.singleShot(12000, lambda: (lg("force mischief @12s (消化中)"), win._on_mood_state("smug"), win._mood_bubble("嘻嘻"), win._mood_emote("sparkle")))
QTimer.singleShot(19000, lambda: (lg("force mischief @19s (消化已结束，应正常显示)"), win._on_mood_state("smug")))
QTimer.singleShot(24000, app.quit)
app.exec()
win._closing = True; win.voice.stop(); win.hide(); win.deleteLater()