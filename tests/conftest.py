# -*- coding: utf-8 -*-
"""pytest 共享配置：项目根入路径 + offscreen 平台（Qt 模块无显示器可跑）。"""
import os
import sys

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_log_dir(tmp_path):
    """把所有测试的日志目录重定向到临时目录（v2.1.4）。

    兼容审查实测：此前有 4 个旧测试会把日志写进**真实数据目录**（源码运行时＝仓库根，
    全量跑一次 error.log 从 128B 涨到 2751B）。这里统一隔离并在结束后还原。
    """
    try:
        import pet_log
    except Exception:
        yield
        return
    _old = getattr(pet_log, "_data_dir", None)
    pet_log.set_data_dir(str(tmp_path))
    try:
        yield
    finally:
        pet_log.set_data_dir(_old)


@pytest.fixture(autouse=True)
def _ensure_qapp():
    """需要 Qt 的测试保证有 QApplication 实例（v2.1.4：test_screens 单独跑必失败）。

    只有装了 PySide6 才建；建不出来就跳过这个 fixture 的职责（具体测试自己会报错）。
    """
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:
        yield
        return
    inst = QApplication.instance() or QApplication([])
    yield inst
