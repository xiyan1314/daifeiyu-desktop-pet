# -*- coding: utf-8 -*-
"""W1-a 探针：在**真机**上看一眼 pet_windows 的读数与判据（只读，不改任何东西）。

用法：
    python -B _dev/probe_windows_v2110.py

它回答四个"用例答不了"的问题：
  1. 真实的 ctypes 链路在**这台机器上**通不通（原型声明、argtypes、类名缓冲）；
  2. 此刻前台窗口到底被读成了什么（句柄 / 类名 / 矩形 / 可见性）；
  3. 按主屏矩形判定的结论（主屏矩形一律用 Win32 取**物理像素**，与探针同坐标系；
     换用 Qt 的逻辑像素来比，就是在给自己造那个"150% 缩放下永远不触发"的坑）；
  4. 节流是不是真的在拦：连打 5 次 poll，真查询次数应该停在 1。

⚠ 本脚本的输出只对本机此刻成立（它读的是真桌面）。它**不是**用例：
用例必须能在任何机器上红/绿一致，所以用例全部注入假数据。
"""
import ctypes
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pet_windows as pw  # noqa: E402


def primary_screen_rect():
    """主屏矩形（**物理像素**）：GetSystemMetrics(SM_CXSCREEN/SM_CYSCREEN)。

    为什么不用 Qt：探针要验证的正是"探针读数与屏幕矩形同一坐标系"这条口径；
    拿 Qt 的逻辑像素来比，混合 DPI 下会把差异伪装成"判定不对"。
    """
    try:
        user32 = ctypes.windll.user32
    except AttributeError:
        return None
    return (0, 0, int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1)))


def main():
    print("== pet_windows 真机探针（W1-a） ==")
    print("口径：容差 %d px · 节流 %d ms · 去抖 进 %d / 出 %d"
          % (pw.FULLSCREEN_TOLERANCE_PX, pw.POLL_MIN_INTERVAL_MS,
             pw.DEBOUNCE_ENTER_COUNT, pw.DEBOUNCE_EXIT_COUNT))
    print("排除类名：%s" % ", ".join(sorted(pw.SHELL_CLASSES)))

    api = pw.User32Api()
    print("user32 后端可用：%s" % api.available())
    if not api.available():
        print("（非 Windows：探针只能走到「没有后端 → None」这条安全路径，这是预期）")
        return 0

    shell = api.shell_hwnd()
    print("GetShellWindow 句柄：%r" % shell)

    errors = []
    probe = pw.Win32Probe(on_error=errors.append)
    info = probe.read()
    print("前台窗口快照：%r" % (info,))
    if info is not None:
        print("  类名=%r 可见=%r 矩形=(%d,%d,%d,%d) 尺寸=%dx%d"
              % (info.class_name, info.visible, info.left, info.top, info.right,
                 info.bottom, info.right - info.left, info.bottom - info.top))
        print("  是桌面本身吗：%s" % (info.hwnd == shell))
        print("  是本进程吗：%s" % (api.window_pid(info.hwnd) == os.getpid()))
    print("探针内部错误数：%d（last_error=%r）" % (probe.fail_count, probe.last_error))
    if errors:
        print("on_error 收到：%r" % (errors,))

    rect = primary_screen_rect()
    print("主屏矩形（物理像素）：%r" % (rect,))
    if rect is not None:
        print("按主屏判定 is_fullscreen：%s" % pw.is_fullscreen(rect, info))
        print("  同一窗口对第二块屏（假设 1920..3840）：%s"
              % pw.is_fullscreen((1920, 0, 3840, 1080), info))

    # 节流实测：连打 5 次，真查询次数应停在 1（第 6 次要等过 250ms 才查）
    watcher = pw.FullscreenWatcher(probe=probe,
                                  screen_rects=[rect] if rect else [],
                                  on_error=lambda e: print("  watcher on_error：%r" % (e,)))
    for _ in range(5):
        watcher.poll()
    print("连打 5 次 poll → 真查询 %d 次（节流生效时应为 1）" % watcher.probes)
    time.sleep(pw.POLL_MIN_INTERVAL_MS / 1000.0 + 0.02)
    watcher.poll()
    print("等到节流窗口之后再来一次 → 真查询 %d 次（应为 2）" % watcher.probes)
    print("去抖后的结论：fullscreen=%r（真查询才 %d 次，够不到 %d 次进入阈值）"
          % (watcher.fullscreen, watcher.probes, pw.DEBOUNCE_ENTER_COUNT))
    print("watcher 错误数：%d" % watcher.fail_count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
