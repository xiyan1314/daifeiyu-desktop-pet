# -*- coding: utf-8 -*-
"""UI 卡顿探针 v2（**只读测量**，不改产品代码）。

三段：
  A 场景段：每个用户操作在主线程同步执行 → 记录"主线程被占住多久"与"事件循环实际缺口"
    （缺口靠 10ms 心跳量；场景跑完后先转一次事件循环再读缺口，否则恒为 0）。
  B 画像段：稳态跑 ~8 秒事件循环，sys.setprofile 采集主线程上每个函数的总耗时/单次最大耗时
    ——专抓"定时器里偷偷做 I/O / 长循环"这类周期性卡顿。
  C 交互段：模拟按压/拖动/滚轮。

用法：python _dev/probe_ui_freeze.py [--json out.json] [--steady 8]
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# v2.4.1：报告里有 ↳ 这类非 GBK 字符，Windows 默认控制台编码会让脚本走到一半就
# UnicodeEncodeError（实测：A 场景段跑到一半崩，JSON 一个都没落盘）。固定成 UTF-8。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tests"))

TMP = tempfile.mkdtemp(prefix="probe_freeze_")

import pet_log  # noqa: E402

pet_log.set_data_dir(TMP)

import 桌宠 as main  # noqa: E402
import pet_config  # noqa: E402
import pet_dialogs  # noqa: E402
import pet_export  # noqa: E402
import pet_io  # noqa: E402
import pet_resources  # noqa: E402
import pet_voice  # noqa: E402

main.DATA_DIR = TMP
main.CONFIG_PATH = os.path.join(TMP, "config.json")
main.USAGE_PATH = os.path.join(TMP, "usage.json")
main.MEMORY_PATH = os.path.join(TMP, "memory.json")

from PySide6.QtCore import QEvent, QPointF, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QImage, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

# ---------------- 心跳：事件循环真实缺口 ----------------
_TICK = {"last": time.perf_counter(), "max_gap": 0.0}


def _tick():
    now = time.perf_counter()
    gap = (now - _TICK["last"]) * 1000.0
    if gap > _TICK["max_gap"]:
        _TICK["max_gap"] = gap
    _TICK["last"] = now


_heart = QTimer()
_heart.setInterval(10)
_heart.timeout.connect(_tick)
_heart.start()

RESULTS = []


def pump(seconds=0.08):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < seconds:
        app.processEvents()
        time.sleep(0.003)


def reset_tick():
    _TICK["max_gap"] = 0.0
    _TICK["last"] = time.perf_counter()


def read_gap():
    """先转一次事件循环（让被卡住的心跳补发），再读最大缺口。"""
    app.processEvents()
    time.sleep(0.001)
    app.processEvents()
    return _TICK["max_gap"]


def run(name, fn):
    pump(0.12)
    reset_tick()
    t0 = time.perf_counter()
    try:
        out = fn()
        err = ""
    except Exception as e:  # noqa: BLE001
        out, err = None, "%r" % (e,)
    dt = (time.perf_counter() - t0) * 1000.0
    gap = read_gap()
    RESULTS.append({"scene": name, "main_thread_ms": round(dt, 1),
                    "loop_gap_ms": round(gap, 1), "err": err})
    print("[%8.1f ms 主线程 | %7.1f ms 循环缺口] %s%s"
          % (dt, gap, name, ("  ERR=" + err) if err else ""))
    return out


# ---------------- 内部函数画像（归因用） ----------------
PROF = {}


def instrument(obj, name, label=None):
    try:
        orig = getattr(obj, name)
    except AttributeError:
        return
    tag = label or ("%s.%s" % (getattr(obj, "__name__", type(obj).__name__), name))

    def wrapper(*a, **k):
        t0 = time.perf_counter()
        try:
            return orig(*a, **k)
        finally:
            if threading.current_thread() is threading.main_thread():
                d = (time.perf_counter() - t0) * 1000.0
                rec = PROF.setdefault(tag, [0.0, 0.0, 0])
                rec[0] += d
                rec[1] = max(rec[1], d)
                rec[2] += 1

    try:
        setattr(obj, name, wrapper)
    except Exception:  # noqa: BLE001
        pass


# ---------------- 素材 ----------------
def _png(path, w, h, color):
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(QColor(*color))
    img.save(path)


def real_frame_size():
    from PySide6.QtGui import QImageReader
    p = os.path.join(HERE, "assets", "idle_full_f00.png")
    r = QImageReader(p)
    return (r.size().width(), r.size().height(), os.path.getsize(p))


def make_frames_role(n_frames, forms, rid, src_dir=None, src_names=None):
    """n 帧 / forms 形态角色。src_dir/src_names 给了就复制**真实素材**（真实解码成本）。"""
    d = os.path.join(TMP, "roles")
    os.makedirs(d, exist_ok=True)
    names = []
    for i in range(n_frames):
        n = "%s_f%02d.png" % (rid, i)
        dst = os.path.join(d, n)
        if src_names:
            shutil.copyfile(os.path.join(src_dir, src_names[i % len(src_names)]), dst)
        else:
            _png(dst, 512, 512, (120 + i % 60, 200, 255, 255))
        names.append(n)
    fms = []
    for k in range(forms):
        fms.append({"name": "形态%d" % (k + 1), "file": names[k % n_frames],
                    "animations": {"idle": names, "eat": names[:6]},
                    "anim_interval_ms": 80})
    raw = {"id": rid, "name": "重角色", "file": names[0],
           "form": ("multi" if forms > 1 else "single"),
           "frames": names, "added": "", "forms": fms}
    norm = win.role_lib._normalize_role(raw) or raw
    win.role_lib._data["roles"].append(norm)
    win.role_lib._save()
    return rid


def make_big_files():
    for n, kb in (("lines.json", 900), ("roles.json", 400)):
        with open(os.path.join(TMP, n), "a", encoding="utf-8") as f:
            f.write(" " * (kb * 1024))


# ---------------- 归因插桩 ----------------
for _o, _n in (
    (main.PetWindow, "apply_role"), (main.PetWindow, "_reload_sprites"),
    (main.PetWindow, "_build_sprites"), (main.PetWindow, "_build_state_pix"),
    (main.PetWindow, "_pix_frames"), (main.PetWindow, "_wire_anim_sets"),
    (main.PetWindow, "_snapshot_import_state"), (main.PetWindow, "_restore_import_state"),
    (main.PetWindow, "_clear_logs"), (main.PetWindow, "_play_idle"),
    (main.PetWindow, "_update_click_mask"), (main.PetWindow, "_apply_transform"),
    (main.PetWindow, "_show_emote"), (main.PetWindow, "_update_badge"),
    (main.PetWindow, "_open_menu"),
    (pet_resources.RoleLibrary, "delete"), (pet_resources.RoleLibrary, "import_processed"),
    (pet_resources.RoleLibrary, "form_paths"), (pet_resources.RoleLibrary, "form_animations"),
    (pet_resources.RoleLibrary, "form_metas"), (pet_resources.RoleLibrary, "_save"),
    (pet_resources.RoleLibrary, "_cleanup_files"), (pet_export, "validate_bundle"),
    (pet_export, "export_bundle"), (pet_export, "import_bundle"),
    (pet_export, "_role_file_refs"), (main, "save_config"),
    (main.PetWindow, "_refresh_lines"), (main.PetWindow, "_scan_invalid_refs"),
    (main.PetWindow, "_migrate_lines_extra"), (main.PetWindow, "apply_bubble_style"),
    (main.PetWindow, "_apply_imported_voice_assets"), (main.PetWindow, "_apply_imported_lines"),
    (pet_voice.VoiceLauncher, "stop"), (pet_voice.VoiceLauncher, "is_running"),
    (pet_dialogs, "_extract_video_frames"),
):
    instrument(_o, _n)

# ---------------- 建窗口 ----------------
from helpers_roles import install_three_form_role  # noqa: E402

print("真实素材帧：%s" % (real_frame_size(),))
print("== A 场景段 ==")
_box = {}


def _mk():
    _box["w"] = main.PetWindow()
    return _box["w"]


run("PetWindow() 构造（启动）", _mk)
win = _box["w"]
BUBBLES = []
win.show_bubble = lambda t, *a, **k: BUBBLES.append(t)
install_three_form_role(win, TMP)
make_big_files()

SRC = os.path.join(HERE, "assets")
SRC_NAMES = sorted(n for n in os.listdir(SRC)
                   if n.startswith(("idle_full_f", "eat_f")) and n.endswith(".png"))
print("素材源：%d 个真实 PNG（%s…）" % (len(SRC_NAMES), SRC_NAMES[0]))

run("apply_role(默认)", lambda: win.apply_role(""))
R60 = make_frames_role(60, 1, "big60", SRC, SRC_NAMES)
run("apply_role(60 帧 真实素材 256px 单形态)", lambda: win.apply_role(R60))
R60_4 = make_frames_role(60, 4, "big60x4", SRC, SRC_NAMES)
run("apply_role(60 帧×4 形态 真实素材 256px)", lambda: win.apply_role(R60_4))
run("apply_role(默认) 回切", lambda: win.apply_role(""))

# 512px 素材（导入管线上限，真实最坏情况）
D512 = os.path.join(TMP, "src512")
os.makedirs(D512, exist_ok=True)
NAMES512 = []
for i in range(6):
    n = "f%02d.png" % i
    _png(os.path.join(D512, n), 512, 512, (120 + i * 10, 200, 255, 255))
    NAMES512.append(n)
R512 = make_frames_role(60, 4, "big512x4", D512, NAMES512)
# 真实美术 512px（把真素材平滑放大再存 PNG）：单形态 60 帧的最坏解码成本
D512R = os.path.join(TMP, "src512real")
os.makedirs(D512R, exist_ok=True)
NAMES512R = []
from PySide6.QtGui import QImageReader as _QR  # noqa: E402
for i in range(6):
    n = "r%02d.png" % i
    _im = _QR(os.path.join(SRC, SRC_NAMES[i])).read()
    _im.scaled(512, 512, Qt.AspectRatioMode.KeepAspectRatio,
               Qt.TransformationMode.SmoothTransformation).save(os.path.join(D512R, n))
    NAMES512R.append(n)
R512R = make_frames_role(60, 1, "real512", D512R, NAMES512R)
print("  真实美术 512px 单帧体积：%.1f KB" % (os.path.getsize(os.path.join(D512R, NAMES512R[0])) / 1024.0))
run("apply_role(60 帧 真实美术 512px 单形态)", lambda: win.apply_role(R512R))
# 统计一次 apply_role 里对同一批 PNG 的解码次数
_real_pixmap = main.QPixmap
DEC = []


def _counting_pixmap(*a, **k):
    if a and isinstance(a[0], str):
        DEC.append(a[0])
    return _real_pixmap(*a, **k)


main.QPixmap = _counting_pixmap
run("apply_role(60 帧×4 形态 512px)", lambda: win.apply_role(R512))
main.QPixmap = _real_pixmap
print("  ↳ 本次 apply_role 的 PNG 解码次数：%d（角色素材文件数：%d）"
      % (len(DEC), len(set(os.listdir(os.path.join(TMP, "roles"))))))

# 导出 / 导入（**当前角色就是重角色**时导出，否则 _export_role 直接 return）
_zip = os.path.join(TMP, "out.dfypet.zip")
_orig_fd = main.QFileDialog
main.QFileDialog = type("FD", (), {
    "getSaveFileName": staticmethod(lambda *a, **k: (_zip, "")),
    "getOpenFileName": staticmethod(lambda *a, **k: (_zip, "")),
})
pet_dialogs.pick_voice_assets = lambda *a, **k: None
pet_dialogs.pick_role_meta = lambda *a, **k: {}
run("_export_role（当前=60 帧×4 形态 512px 平色）", lambda: win._export_role())
print("  ↳ 包大小：%.2f MB" % (os.path.getsize(_zip) / 1048576.0))
run("role_lib.delete(该重角色) 腾位", lambda: win.role_lib.delete(R512))
run("_import_role_bundle（导入该包并切换）", lambda: win._import_role_bundle())

# 真实美术大包：60 帧×1 形态 512px 真实 PNG（≈12MB）→ 导出/导入是主线程长循环的高发区
run("apply_role(60 帧 真实美术 512px)", lambda: win.apply_role(R512R))
_zip2 = os.path.join(TMP, "real.dfypet.zip")
main.QFileDialog = type("FD", (), {
    "getSaveFileName": staticmethod(lambda *a, **k: (_zip2, "")),
    "getOpenFileName": staticmethod(lambda *a, **k: (_zip2, "")),
})
run("_export_role（真实美术 512px×60 帧）", lambda: win._export_role())
print("  ↳ 包大小：%.2f MB" % (os.path.getsize(_zip2) / 1048576.0))
run("role_lib.delete(腾位)", lambda: win.role_lib.delete(R512R))
run("_import_role_bundle（真实美术大包）", lambda: win._import_role_bundle())
main.QFileDialog = _orig_fd

# 后端：两级进程树（父进程再起子进程）结束耗时
_nested = ('import subprocess,sys,time;'
           'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"]);'
           'time.sleep(60)')
win.cfg["voice"].setdefault("local_services", {})["gpt_sovits"] = {
    "cmd": '"%s" -c "%s"' % (sys.executable, _nested.replace('"', '\\"')),
    "cwd": "", "auto_start": True, "kill_on_exit": True, "wait_seconds": 5}
run("voice.start_backend（两级进程树）", lambda: win.voice.start_backend())
pump(0.6)
run("voice.stop_backend（两级进程树：terminate+wait_procs）", lambda: win.voice.stop_backend())
run("_clear_logs()", lambda: win._clear_logs())
main.QFileDialog = _orig_fd

run("role_lib.delete(60 帧×4 形态 256px)", lambda: win.role_lib.delete(R60_4))
run("role_lib.delete(60 帧 256px)", lambda: win.role_lib.delete(R60))

# 声音素材导入（3.3MB wav）
import struct  # noqa: E402

_bigwav = os.path.join(TMP, "big.wav")
with open(_bigwav, "wb") as f:
    f.write(b"RIFF" + struct.pack("<I", 44100 * 120 + 36) + b"WAVEfmt ")
    f.write(struct.pack("<IHHIIHH", 16, 1, 1, 44100, 88200, 2, 16))
    f.write(b"data" + struct.pack("<I", 44100 * 120))
    f.write(b"\x00" * (44100 * 120 // 8))
run("voice_assets.import_file(6.6MB wav)", lambda: win.voice_assets.import_file(_bigwav))
run("audio import_fragment(6.6MB wav)", lambda: win.audio_lib.import_fragment(_bigwav))

# GIF 抽帧：确认是否在工作线程（主线程只应花"起线程"的时间）
GIF = os.path.join(HERE, "_verify_assets", "sample.gif")
if os.path.isfile(GIF):
    run("_extract_video_frames(GIF, 主线程直调对照)",
        lambda: pet_dialogs._extract_video_frames(GIF, os.path.join(TMP, "gifframes")))

# 后端启停：真起一个假后端再结束
win.cfg.setdefault("voice", {})
win.cfg["voice"]["enabled"] = True
win.cfg["voice"]["backend"] = "gpt_sovits"
win.cfg["voice"].setdefault("local_services", {})["gpt_sovits"] = {
    "cmd": '"%s" -c "import time; time.sleep(60)"' % sys.executable,
    "cwd": "", "auto_start": True, "kill_on_exit": True, "wait_seconds": 5}
run("voice.start_backend()（真起进程）", lambda: win.voice.start_backend())
pump(0.3)
run("voice.start_backend()（已在跑：幂等）", lambda: win.voice.start_backend())
run("voice.launcher.is_running()", lambda: win.voice.launcher.is_running())
run("voice.stop_backend()（真结束进程树）", lambda: win.voice.stop_backend())

# 后端已就绪探测：地址连不上时应立刻返回（is_running 守卫）
run("voice.wait_backend_ready(5s)", lambda: win.voice.wait_backend_ready(timeout=5))

# ---------------- C 交互段 ----------------
print("\n== C 交互段 ==")
run("apply_role(默认) 复位", lambda: win.apply_role(""))


def _mouse(kind, x, y, buttons=Qt.MouseButton.LeftButton):
    typ = {"press": QEvent.Type.MouseButtonPress,
           "move": QEvent.Type.MouseMove,
           "release": QEvent.Type.MouseButtonRelease}[kind]
    ev = QMouseEvent(typ, QPointF(x, y), QPointF(x + 100, y + 100),
                     Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier)
    return QApplication.sendEvent(win, ev)


run("按压（press）", lambda: _mouse("press", 40, 40))
run("拖动 20 次（move）", lambda: [_mouse("move", 40 + i, 40 + i) for i in range(20)])
run("松手（release）", lambda: _mouse("release", 60, 60, Qt.MouseButton.NoButton))


class _Wheel(object):
    def __init__(self, d):
        self._d = d

    def angleDelta(self):
        from PySide6.QtCore import QPoint
        return QPoint(0, self._d)


run("滚轮缩放 ×5", lambda: [win.wheelEvent(_Wheel(120)) for _ in range(5)])

# ---------------- B 画像段 ----------------
print("\n== B 稳态画像段（%.0fs，主线程 sys.setprofile） ==" % 0.0)
ap = argparse.ArgumentParser()
ap.add_argument("--json", default="")
ap.add_argument("--steady", type=float, default=8.0)
ARGS, _ = ap.parse_known_args()

STATS = {}


def _prof(frame, event, arg):
    if event not in ("call", "return"):
        return
    if threading.current_thread() is not threading.main_thread():
        return
    code = frame.f_code
    key = "%s:%d %s" % (os.path.basename(code.co_filename), code.co_firstlineno, code.co_name)
    if event == "call":
        st = STATS.get(key)
        if st is None:
            st = STATS[key] = {"n": 0, "tot": 0.0, "max": 0.0, "t0": 0.0}
        st["n"] += 1
        st["t0"] = time.perf_counter()
    else:
        st = STATS.get(key)
        if st is not None and st["t0"]:
            d = (time.perf_counter() - st["t0"]) * 1000.0
            st["tot"] += d
            st["max"] = max(st["max"], d)
            st["t0"] = 0.0


reset_tick()
win._closing = False
sys.setprofile(_prof)
t0 = time.perf_counter()
while time.perf_counter() - t0 < ARGS.steady:
    app.processEvents()
    time.sleep(0.002)
sys.setprofile(None)
steady_gap = _TICK["max_gap"]
print("稳态 %.1fs：最大循环缺口 %.1f ms" % (ARGS.steady, steady_gap))

print("\n-- 主线程累计耗时 Top 20 --")
for k, v in sorted(STATS.items(), key=lambda kv: -kv[1]["tot"])[:20]:
    print("%9.1f ms  n=%-6d max=%7.1f ms  %s" % (v["tot"], v["n"], v["max"], k))
print("\n-- 主线程单次最大耗时 Top 15 --")
for k, v in sorted(STATS.items(), key=lambda kv: -kv[1]["max"])[:15]:
    print("%9.1f ms  n=%-6d tot=%9.1f ms  %s" % (v["max"], v["n"], v["tot"], k))

# ---------------- 汇总 ----------------
print("\n== A 场景段排序（主线程阻塞 Top 15） ==")
for r in sorted(RESULTS, key=lambda x: -x["main_thread_ms"])[:15]:
    print("%8.1f ms  gap=%8.1f ms  %s" % (r["main_thread_ms"], r["loop_gap_ms"], r["scene"]))

print("\n== 归因（插桩函数：总耗时 / 单次最大 / 次数，单位 ms） ==")
for k, v in sorted(PROF.items(), key=lambda kv: -kv[1][0])[:20]:
    print("%9.1f  max=%8.1f  n=%-5d %s" % (v[0], v[1], v[2], k))

if ARGS.json:
    with open(ARGS.json, "w", encoding="utf-8") as f:
        json.dump({"scenes": RESULTS, "steady_gap_ms": steady_gap,
                   "profile": {k: v for k, v in STATS.items()},
                   "instrumented": PROF}, f, ensure_ascii=False, indent=1)
    print("saved", ARGS.json)

try:
    win._closing = True
    win.voice.stop()
    win.hide()
except Exception:
    pass
shutil.rmtree(TMP, ignore_errors=True)
