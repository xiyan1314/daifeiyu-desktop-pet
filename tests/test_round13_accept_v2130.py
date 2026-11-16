# -*- coding: utf-8 -*-
"""v2.13.0（第 13 轮 · 体积与暴露面）的两条验收判据：首启 0 弹窗 / 崩溃自恢复。

## 为什么这两条要单列

plan §25.3 第 13 轮的判据里有两项不是"功能"而是**验收**：首启弹窗数 = 0；崩溃后能自恢复。
前者此前没有任何统一读数（各处只说"引导是气泡"）；后者只有 pet_guard 的纯逻辑判据，
`main.py` 那条**真的 spawn 子进程**的路径从来没端到端跑过。

## 能真失败

- 首启：把 D1 引导从气泡改成 QMessageBox（或启动路径里加任何模态框）→ `shown` 非空 → 红；
- 崩溃恢复：删掉 main.py 里的 `subprocess.Popen` / `_release_single_mutex` / 熔断记录 →
  第二次运行不会被拉起（runs.txt 停在 1）或无限拉起（runs.txt 超过 2）→ 红。
"""
import os
import shutil
import subprocess
import sys
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.dirname(os.path.abspath(__file__))
for _p in (REPO, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

import pet_first_run  # noqa: E402
import 桌宠 as main  # noqa: E402


def test_first_launch_shows_zero_modal_dialogs(tmp_path, monkeypatch):
    """真·首启（config.json 不存在）跑 3.1s：**一个模态框都不许有**，引导只走气泡一次。

    红法：把 pet_first_run.guide 的 show 回调换成 QMessageBox.information → shown 非空。
    """
    import pet_log
    from helpers_roles import shutdown_pet

    data = str(tmp_path / "data")
    os.makedirs(data, exist_ok=True)
    snap = (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
            getattr(pet_log, "_data_dir", None))
    main.DATA_DIR = data
    main.CONFIG_PATH = os.path.join(data, "config.json")
    main.USAGE_PATH = os.path.join(data, "usage.json")
    main.MEMORY_PATH = os.path.join(data, "memory.json")
    pet_log.set_data_dir(data)

    dialogs = []
    for name in ("information", "warning", "question", "critical"):
        monkeypatch.setattr(QMessageBox, name,
                            lambda *a, **k: dialogs.append((a, k)) or QMessageBox.StandardButton.Ok)
    # 非阻塞模态（setModal(True)+show()）也算"弹窗"：三审实测过，只打桩 exec 会漏掉它。
    for cls in (QMessageBox, QDialog):
        monkeypatch.setattr(cls, "exec", lambda self: dialogs.append("exec") or 0)
        monkeypatch.setattr(cls, "show", lambda self: dialogs.append("show"))
        monkeypatch.setattr(cls, "open", lambda self: dialogs.append("open"))

    QApplication.instance() or QApplication([])
    win = main.PetWindow()
    bubbles = []
    monkeypatch.setattr(win, "show_bubble", lambda text, *a, **k: bubbles.append(text) or True)
    try:
        t0 = time.monotonic()
        while time.monotonic() - t0 < 4.0:      # D1 的定时器是 2600ms；留 1.4s 余量（满载机器也不假红）
            QApplication.processEvents()
            time.sleep(0.02)
        assert dialogs == [], "首启弹了 %d 个模态框：%r" % (len(dialogs), dialogs[:3])
        assert win.cfg["first_run_done"] is True
        # 不只内存：标记必须真的落到 config.json（三审实测：把 save_config 换掉，只看内存仍绿）
        import json
        with open(main.CONFIG_PATH, encoding="utf-8") as f:
            on_disk = json.load(f)
        assert on_disk.get("first_run_done") is True, "首启标记只改了内存，没落盘：%r" % (on_disk.get("first_run_done"),)
        assert bubbles == [pet_first_run.FIRST_RUN_HINT], \
            "首启引导应恰好一条气泡，实际 %r" % (bubbles,)
    finally:
        shutdown_pet(win)
        (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
         pet_log._data_dir) = snap


FAKE_PET = '''# -*- coding: utf-8 -*-
"""验收用替身：第一次运行崩溃（SystemExit 3），被拉起后正常返回（不再重启）。"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.join(HERE, "runs.txt")


def main():
    n = 0
    try:
        with open(RUNS, "r") as f:
            n = int(f.read().strip() or 0)
    except Exception:
        n = 0
    n += 1
    with open(RUNS, "w") as f:
        f.write(str(n))
    if n == 1:
        raise SystemExit(3)
    return
'''


def test_guard_restarts_a_crashed_child_end_to_end(tmp_path):
    """真跑 main.py：第一次 SystemExit(3) → 守护拉起第二个进程 → 它正常返回 → 停。

    判据：父进程退出码 3 · runs.txt 恰好 2（拉起了且只拉起一次）· crash_recovery.json 落盘。
    红法：删掉 main.py 的 Popen → runs.txt 停在 1；删掉熔断/正常退出判定 → 无限拉起。
    **本条不证明**：单实例互斥体释放（_release_single_mutex 需要真实 pet_main 才走得通；
    替身环境里 ImportError 被吞）。那条由 A 规则静态门 + pet_guard 单测兜，别把本条读成"互斥体也验了"。
    """
    app = tmp_path / "app"
    app.mkdir()
    for name in ("main.py", "pet_guard.py", "pet_io.py", "pet_log.py"):
        shutil.copy2(os.path.join(REPO, name), str(app / name))
    (app / "桌宠.py").write_text(FAKE_PET, encoding="utf-8")

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("QT_QPA_PLATFORM", None)      # 替身不碰 Qt；保留干净环境
    r = subprocess.run([sys.executable, "main.py"], cwd=str(app), env=env,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=90)
    assert r.returncode == 3, "父进程退出码应是崩溃码 3（实际 %r，stderr=%r）" % (
        r.returncode, (r.stderr or "")[-400:])

    runs = app / "runs.txt"
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline and not (runs.is_file() and runs.read_text().strip() == "2"):
        time.sleep(0.1)
    assert runs.is_file(), "替身一次都没跑起来"
    assert runs.read_text().strip() == "2", \
        "崩溃后应恰好拉起一次（runs.txt=%r）；1=没拉起，>2=熔断没生效" % (runs.read_text().strip(),)
    assert (app / "crash_recovery.json").is_file(), "崩溃标记没落盘（跨进程的唯一依据）"