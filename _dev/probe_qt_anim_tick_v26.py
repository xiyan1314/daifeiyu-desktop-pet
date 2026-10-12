# -*- coding: utf-8 -*-
"""_dev 探针 2：Qt 统一动画定时器被"饿死"时 QVariantAnimation 的收尾行为（纯 Qt，无产品代码）。

问题：CI #52 上 sway 合成动作 400ms 的 QVariantAnimation 在 5s 轮询内没触发 finished，
但 squash 已经回到 1.0000（末值被应用）。本地正常路径是"每 ~16ms 一跳，跳满 400ms 后
finished 同步触发"。本探针穷举"跳变稀疏 / 只跳一次 / 迟到很多"的情况，看 finished 到底
在什么条件下会丢。
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QVariantAnimation, QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)


def run(label, *, pre_sleep, pump_ms, pump_step=0.01, cpu_ms=0):
    state = {"vals": [], "fin": [], "statechg": []}
    anim = QVariantAnimation()
    anim.setDuration(400)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.valueChanged.connect(lambda v: state["vals"].append(round(float(v), 6)))
    anim.finished.connect(lambda: state["fin"].append(time.monotonic()))
    anim.stateChanged.connect(lambda n, o: state["statechg"].append((int(o.value), int(n.value))))
    t0 = time.monotonic()
    anim.start()
    if pre_sleep:
        time.sleep(pre_sleep)
    end = time.monotonic() + pump_ms / 1000.0
    pumps = 0
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        pumps += 1
        if cpu_ms:
            _b = time.monotonic()
            while time.monotonic() - _b < cpu_ms / 1000.0:
                pass
        time.sleep(pump_step)
    # 再补几拍，看迟到的收尾
    for _ in range(5):
        QCoreApplication.processEvents()
        time.sleep(0.02)
    print("%-34s state=%-2d curTime=%-5d dur=%d  vals=%d last=%s fin=%d statechg=%s pumps=%d"
          % (label, int(anim.state().value), anim.currentTime(), anim.duration(),
             len(state["vals"]), state["vals"][-1] if state["vals"] else None,
             len(state["fin"]), state["statechg"], pumps))
    sys.stdout.flush()
    anim.stop()
    anim.deleteLater()


print("--- Qt 版本 / 平台 ---")
print("Qt", __import__("PySide6").__version__, "platform", app.platformName())
run("A 常规 20ms 轮询 600ms", pre_sleep=0, pump_ms=600)
run("B 阻塞 1.0s 后单拍", pre_sleep=1.0, pump_ms=0)
run("C 阻塞 1.0s 后再轮询 200ms", pre_sleep=1.0, pump_ms=200)
run("D 阻塞 0.5s 后单拍", pre_sleep=0.5, pump_ms=0)
run("E 每拍 40ms CPU 忙等 + 20ms 轮询 600ms", pre_sleep=0, pump_ms=600, cpu_ms=40)
run("F 不阻塞但只泵一次", pre_sleep=0, pump_ms=0)
run("G 阻塞 3.0s 后单拍", pre_sleep=3.0, pump_ms=0)
