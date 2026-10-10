# -*- coding: utf-8 -*-
"""UI 卡顿可复现测量脚本（v2.4.1 · B 区 C1-C3）。

**只读测量**，不改产品代码。用于回答两个问题：

  1. 每个"卡点"修前/修后，主线程被连续占住多久？（main_thread_ms）
  2. 事件循环真的卡住了吗？（loop_gap_ms = 心跳定时器的最大间隔，
     等于主线程连续不让出事件循环的时长——用户感知的"假死"就是它）

指标口径：
  · main_thread_ms —— 场景函数**同步返回**所花的墙钟时间。
  · loop_gap_ms   —— 5ms 心跳定时器在整个场景窗口（含其后泵事件循环的时间）里的最大间隔。
  · ready_ms      —— 场景开始到"帧集真正装好"的耗时（异步分片路径下 > main_thread_ms）。
    就绪判据 = **win._anim_pending is None 且指纹已收敛**（_anim_pending 是"这一批分片跑完了"
    的唯一权威信号）。**不要退回 bool(win.anim._sets.get("idle"))**：分片在途时那上面还挂着
    上一次注册的帧集（旧角色/上一个形态），判据恒真 → ready_ms 恒等于 main_thread_ms
    （实测 ui_freeze_raw.json 里 40 行每行都相等，与本文件"异步路径下应 >"的说法自相矛盾）。
  · gap_after_ready —— 起播那一刻的最大循环缺口（异步路径下所有分片的最大值）。

用法：
    python _dev/repro_frame_freeze.py --label before
    python _dev/repro_frame_freeze.py --label after
结果累积写入 _dev/ui_freeze_raw.json（按 label 分段），并打印对照表。
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tests"))

TMP = tempfile.mkdtemp(prefix="repro_freeze_")

import pet_log  # noqa: E402

pet_log.set_data_dir(TMP)

import 桌宠 as main  # noqa: E402
import pet_dialogs  # noqa: E402

main.DATA_DIR = TMP
main.CONFIG_PATH = os.path.join(TMP, "config.json")
main.USAGE_PATH = os.path.join(TMP, "usage.json")
main.MEMORY_PATH = os.path.join(TMP, "memory.json")

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QImage, QImageReader  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

_TICK = {"last": time.perf_counter(), "max_gap": 0.0}


def _tick():
    now = time.perf_counter()
    gap = (now - _TICK["last"]) * 1000.0
    if gap > _TICK["max_gap"]:
        _TICK["max_gap"] = gap
    _TICK["last"] = now


_heart = QTimer()
_heart.setInterval(5)
_heart.timeout.connect(_tick)
_heart.start()


def reset():
    _TICK["max_gap"] = 0.0
    _TICK["last"] = time.perf_counter()


def pump(seconds=0.05):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < seconds:
        app.processEvents()
        time.sleep(0.002)


def read_gap():
    app.processEvents()
    time.sleep(0.001)
    app.processEvents()
    return _TICK["max_gap"]


ROWS = []


def scene(name, fn, ready=None, timeout=6.0):
    """跑一个场景；ready 非空时泵事件循环直到 ready() 为真（异步分片路径）。"""
    pump(0.12)
    reset()
    t0 = time.perf_counter()
    err = ""
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        err = "%r" % (e,)
    main_ms = (time.perf_counter() - t0) * 1000.0
    ready_ms = main_ms
    if ready is not None and not err:
        while not ready() and (time.perf_counter() - t0) < timeout:
            app.processEvents()
            time.sleep(0.002)
        ready_ms = (time.perf_counter() - t0) * 1000.0
    gap = read_gap()
    ROWS.append({"scene": name, "main_thread_ms": round(main_ms, 1),
                 "ready_ms": round(ready_ms, 1), "loop_gap_ms": round(gap, 1),
                 "err": err})
    print("  [%8.1f ms 主线程 | %8.1f ms 就绪 | %8.1f ms 循环缺口] %s%s"
          % (main_ms, ready_ms, gap, name, ("  ERR=" + err) if err else ""))
    return main_ms, gap


# ---------------- 素材：真实美术 512px（最坏解码成本） ----------------
def _role_frames(rid, n_frames, src_dir, src_names, size):
    d = os.path.join(TMP, "roles")
    os.makedirs(d, exist_ok=True)
    names = []
    for i in range(n_frames):
        n = "%s_f%02d.png" % (rid, i)
        dst = os.path.join(d, n)
        im = QImageReader(os.path.join(src_dir, src_names[i % len(src_names)])).read()
        im.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                  Qt.TransformationMode.SmoothTransformation).save(dst)
        names.append(n)
    return names


def install(rid, n_frames, forms, size, src_dir, src_names):
    names = _role_frames(rid, n_frames, src_dir, src_names, size)
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


SRC = os.path.join(HERE, "assets")
SRC_NAMES = sorted(n for n in os.listdir(SRC)
                   if n.startswith(("idle_full_f", "eat_f")) and n.endswith(".png"))

print("== 建窗 ==")
_box = {}
scene("PetWindow() 构造（启动）", lambda: _box.__setitem__("w", main.PetWindow()))
win = _box["w"]
BUBBLES = []
win.show_bubble = lambda t, *a, **k: BUBBLES.append(t)

# 小角色（8 帧 64px）：用来证明"小帧集仍走同步路径、行为不变"
D_SMALL = os.path.join(TMP, "src_small")
os.makedirs(D_SMALL, exist_ok=True)
SMALL_NAMES = []
for i in range(4):
    img = QImage(64, 64, QImage.Format.Format_ARGB32)
    img.fill(QColor(120 + i * 20, 200, 255, 255))
    n = "s%02d.png" % i
    img.save(os.path.join(D_SMALL, n))
    SMALL_NAMES.append(n)
R_SMALL = install("small8", 8, 1, 64, D_SMALL, SMALL_NAMES)
R_BIG = install("big60", 60, 1, 512, SRC, SRC_NAMES)
R_BIG4 = install("big60x4", 60, 4, 512, SRC, SRC_NAMES)
print("  真实素材源：%d 个 PNG；512px 单帧 %.1f KB"
      % (len(SRC_NAMES), os.path.getsize(os.path.join(TMP, "roles", R_BIG + "_f00.png")) / 1024.0))


def idle_ready():
    """帧集是否**真正装好**（异步分片路径下要泵到这一刻才算就绪）。

    判据是 _anim_pending is None（本批分片收尾的唯一权威信号）+ 指纹收敛到当前角色/形态。
    别用 anim._sets.get("idle") 非空：分片在途时它仍是上一次注册的帧集 → 恒真 → ready_ms
    等于 main_thread_ms，"异步路径下 ready_ms > main_thread_ms"永远不会成立（实测如此）。
    """
    return lambda: (getattr(win, "_anim_pending", None) is None
                    and win._wire_key == win._wire_anim_key())


print("\n== C1 角色切换（apply_role） ==")
scene("apply_role(默认角色)", lambda: win.apply_role(""))
scene("apply_role(小角色 8 帧 64px)", lambda: win.apply_role(R_SMALL))
scene("apply_role(60 帧 512px 真实美术)", lambda: win.apply_role(R_BIG),
      ready=idle_ready())
print("  -> 就绪后该角色实际注册的 idle 帧数：%d（就绪判据 = _anim_pending is None）"
      % len(win.anim._sets.get("idle") or []))
scene("apply_role(默认) 回切", lambda: win.apply_role(""))
scene("apply_role(60 帧 512px) 第二次（预热）", lambda: win.apply_role(R_BIG),
      ready=idle_ready())
scene("apply_role(60 帧×4 形态 512px)", lambda: win.apply_role(R_BIG4),
      ready=idle_ready())

print("\n== C2 待机热路径（_play_idle 反复重查帧集） ==")
scene("_play_idle() ×5（自定义 60 帧×4 形态）",
      lambda: [win._play_idle() for _ in range(5)])
scene("_wire_anim_key() ×20（热路径指纹计算）",
      lambda: [win._wire_anim_key() for _ in range(20)])
scene("_play_idle() ×5（稳定态再来一遍）",
      lambda: [win._play_idle() for _ in range(5)])
scene("apply_role(默认) 后 _play_idle() ×5",
      lambda: (win.apply_role(""), [win._play_idle() for _ in range(5)]))

print("\n== C3 导入导出（pet_export 长循环） ==")
win.apply_role(R_BIG)
ZIP = os.path.join(TMP, "out.dfypet.zip")
_orig_fd = main.QFileDialog
main.QFileDialog = type("FD", (), {
    "getSaveFileName": staticmethod(lambda *a, **k: (ZIP, "")),
    "getOpenFileName": staticmethod(lambda *a, **k: (ZIP, "")),
})
pet_dialogs.pick_voice_assets = lambda *a, **k: None
pet_dialogs.pick_role_meta = lambda *a, **k: {}
import pet_export  # noqa: E402

scene("pet_export.export_bundle(60 帧 512px 真实美术)",
      lambda: pet_export.export_bundle(win.role_lib, win.behaviors, win.cfg, ZIP))
print("  -> 包大小：%.2f MB" % (os.path.getsize(ZIP) / 1048576.0))
scene("role_lib.delete(腾位)", lambda: win.role_lib.delete(R_BIG))
scene("_import_role_bundle(60 帧 512px 真实美术包)", lambda: win._import_role_bundle(),
      ready=idle_ready())
main.QFileDialog = _orig_fd

print("\n== 汇总（按主线程阻塞降序） ==")
for r in sorted(ROWS, key=lambda x: -x["main_thread_ms"]):
    print("  %8.1f ms 就绪=%8.1f 缺口=%8.1f  %s"
          % (r["main_thread_ms"], r["ready_ms"], r["loop_gap_ms"], r["scene"]))

worst = max(ROWS, key=lambda x: x["loop_gap_ms"])
print("\n最差循环缺口：%.1f ms（%s）" % (worst["loop_gap_ms"], worst["scene"]))

ap = argparse.ArgumentParser()
ap.add_argument("--label", default="run")
ARGS, _ = ap.parse_known_args()

out = os.path.join(HERE, "_dev", "ui_freeze_raw.json")
data = {}
if os.path.isfile(out):
    try:
        with open(out, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:  # noqa: BLE001
        data = {}
data[ARGS.label] = {"rows": ROWS, "worst_gap_ms": round(worst["loop_gap_ms"], 1)}
with open(out, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=1)
print("saved", out, "label=", ARGS.label)

try:
    win._closing = True
    win.voice.stop()
    win.hide()
except Exception:  # noqa: BLE001
    pass
shutil.rmtree(TMP, ignore_errors=True)
