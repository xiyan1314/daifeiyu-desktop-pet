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


@pytest.fixture(scope="session", autouse=True)
def _pin_system_animations():
    """把宿主的「系统动画开没开」这一层钉死（v2.11.0 收尾 · 公开 CI #58 修复）。

    为什么要它
    ----------
    `pet_motion.system_reduce_motion()` 在 Windows 上真读
    `SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION)`（用户在「辅助功能 → 视觉效果 →
    动画效果」里关掉动画时为 True），而 `reduce_motion_enabled("auto", 系统值)` 是
    **跟随系统**的。于是同一份代码在两台机器上跑出两个结论：

      · 开发机（动画效果 = 开）→ `system_reduce_motion()` is False → 生效值「减少动效 = off」
        → 动效照跑；**全仓动效用例都是在这个前提下写的**。
      · GitHub Actions 的 windows-latest（动画效果 = 关）→ True → 生效值「减少动效 = on」
        → 涟漪 / 贴边缓动 / 气泡淡入 / 在途脉动 / 合成动作**一律不发生** → 二十多条用例
        整片红。公开 CI run #58（提交 5f043ec）的第一跑就是这个：那批动效用例此前**从没在
        CI 上跑过**（上一次 CI 绿是 v2.9.0 的 209875e），换台机器就红 —— **坏的是用例
        （依赖宿主设置），不是产品**。

    产品行为是对的（「跟随系统」是设计意图；系统读不到时保持动效开启，见
    pet_motion.reduce_motion_enabled / 桌宠.PetWindow._reduce_motion）。所以这里**只动
    测试**：测试期把那一层钉成「系统动画 = 开」（即 `system_reduce_motion()` 返回 False），
    与开发机默认一致，**产品代码零改动**。

    为什么是 session 作用域（不能是 function）
    ------------------------------------------
    `桌宠.PetWindow.__init__` **建窗时**就把系统值读进 `self._sys_reduce_motion` 缓存
    （`self._sys_reduce_motion = pet_motion.system_reduce_motion()`），而
    `tests/test_idle_settle_v26.py` 的 `pet` 夹具是 **module 作用域**的。函数级 autouse
    夹具**晚于** module 级夹具实例化 —— 等补丁打上，窗早建完、缓存早写死了（实测：本用例
    集在"系统动画 = 关"下红的第一条就是它）。session 级是 pytest 里唯一能保证"早于任何
    module 级夹具"的作用域。

    为什么不是产品侧的环境变量开关
    ------------------------------
    这一层本来就是"问一次系统"，产品不必为测试开口子（那要动 pet_motion.py 这份产品源码
    与它的变异指纹）。要测「跟随系统」的用例也不受影响：它们**自己** monkeypatch
    `pet_motion.system_reduce_motion` 并逐向断言两边
    （test_motion_v2110.test_default_follows_system_and_never_downgrades、
    test_host_v2100_round.test_reduce_motion_auto_rereads_the_system_setting、
    test_host_v2100_round.test_tray_menu_represents_three_states_and_auto_is_reachable）
    —— monkeypatch 叠在这一层之上，测完自动还原。
    """
    import pet_motion
    real = pet_motion.system_reduce_motion
    pet_motion.system_reduce_motion = lambda: False
    try:
        yield
    finally:
        pet_motion.system_reduce_motion = real
