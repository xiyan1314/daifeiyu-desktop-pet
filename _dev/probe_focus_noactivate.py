# -*- coding: utf-8 -*-
"""A-10 独立探针：**真实 PetWindow** 的 Windows 扩展风格（不进 pytest，不设 offscreen）。

为什么要它：tests/conftest.py 强制 QT_QPA_PLATFORM=offscreen，而 offscreen 下 winId() 不是
真 HWND → "点它能不能激活/拿焦点"这条**永远不可能用普通用例钉**。本探针就是这个缺口。
判据（人工读）：
  · 真 PetWindow 的 exstyle 必须含 WS_EX_NOACTIVATE(0x08000000)
  · 对它的 WM_MOUSEACTIVATE 必须回 3 = MA_NOACTIVATE
  · 数据目录必须隔离到临时目录（绝不写用户的 config.json / ledger）
用法：python -B _dev/probe_focus_noactivate.py      （退出码 0 = 两条都成立）
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WM_MOUSEACTIVATE = 0x0021

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
try:
    _GetLong = user32.GetWindowLongPtrW
except AttributeError:
    _GetLong = user32.GetWindowLongW
_GetLong.restype = ctypes.c_ssize_t
_GetLong.argtypes = [wt.HWND, ctypes.c_int]


def main():
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        print("跳过：这条判据必须在真桌面上跑（当前 QT_QPA_PLATFORM=offscreen）")
        return 0
    tmp = tempfile.mkdtemp(prefix="a10_probe_")
    import 桌宠 as main_mod
    main_mod.DATA_DIR = tmp
    main_mod.CONFIG_PATH = os.path.join(tmp, "config.json")
    main_mod.USAGE_PATH = os.path.join(tmp, "usage.json")
    main_mod.MEMORY_PATH = os.path.join(tmp, "memory.json")
    main_mod.pet_log.set_data_dir(tmp)
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    win = main_mod.PetWindow()
    win.show()
    app.processEvents()
    hwnd = int(win.winId())
    ex = _GetLong(wt.HWND(hwnd), GWL_EXSTYLE) & 0xFFFFFFFF
    ma = int(user32.SendMessageW(wt.HWND(hwnd), WM_MOUSEACTIVATE, wt.WPARAM(hwnd),
                                 wt.LPARAM((1 << 16) | 1)))
    print("真实 PetWindow: hwnd=0x%X  exstyle=0x%08X  WS_EX_NOACTIVATE=%s  WM_MOUSEACTIVATE=%d"
          % (hwnd, ex, bool(ex & WS_EX_NOACTIVATE), ma))
    ok_ex = bool(ex & WS_EX_NOACTIVATE)
    ok_ma = (ma == 3)
    print("判读① exstyle 含 WS_EX_NOACTIVATE: %s" % ok_ex)
    print("判读② WM_MOUSEACTIVATE == 3 (MA_NOACTIVATE): %s" % ok_ma)
    win._closing = True
    app.processEvents()
    print("A-10 PROBE %s" % ("OK（点击不激活 → 主窗口键盘路径在真机不可达；托盘菜单是可靠入口）"
                             if (ok_ex and ok_ma) else "UNEXPECTED"))
    return 0 if (ok_ex and ok_ma) else 1


if __name__ == "__main__":
    sys.exit(main())
