# -*- coding: utf-8 -*-
"""
启动辅助：单实例互斥 / 内存自测 / _MEI 残留清理 / 自启命令行。

独立模块：不 import 桌宠.py（main() 等入口保留在桌宠.py）。
"""
import ctypes
import os
import shutil
import sys
import time
from ctypes import wintypes

import psutil

_MB = 1048576.0
MEI_MAX_AGE_SECONDS = 7 * 86400  # 启动清理：只清理超过 7 天的 _MEI* 残留（降低误删风险）

_SINGLE_MUTEX = None


def check_memory(data_dir):
    """启动内存自测（R3-4）：本进程 RSS < 1GB 为达标，结果追加写入 memory.log。"""
    try:
        rss_mb = psutil.Process().memory_info().rss / _MB
        ok = rss_mb < 1024
        path = os.path.join(data_dir, "memory.log")
        try:
            if os.path.getsize(path) > 512 * 1024:  # 与 error.log 同口径：512KB 轮转
                os.replace(path, path + ".old")
        except Exception:
            pass  # 有意忽略：体积检查失败直接追加
        with open(path, "a", encoding="utf-8") as fp:
            fp.write("memory check: %.1f MB, %s\n" % (rss_mb, "OK" if ok else "OVER 1GB"))
        return ok
    except Exception:
        return True


def cleanup_stale_mei():
    """清理 PyInstaller onefile 异常退出遗留的 %TEMP% 下 _MEI<数字> 目录。

    安全措施：排除本进程自身的解包目录(sys._MEIPASS)；仅匹配 _MEI 后跟纯数字；
    要求 mtime 与 atime 都超过阈值（降低误删仍在运行实例目录的风险）。
    """
    try:
        tmp = os.environ.get("TEMP") or os.environ.get("TMP") or ""
        if not tmp:
            return
        self_mei = os.path.abspath(getattr(sys, "_MEIPASS", "")) if getattr(sys, "frozen", False) else ""
        now = time.time()
        for name in os.listdir(tmp):
            if not name.startswith("_MEI"):
                continue
            tail = name[4:]
            if not tail or not tail.isdigit():
                continue  # 前缀过宽（如用户自建目录），跳过
            p = os.path.join(tmp, name)
            if self_mei and os.path.abspath(p) == self_mei:
                continue  # 绝不删除自身
            try:
                if os.path.islink(p):
                    continue  # 符号链接/junction：跳过，防误删面
                st = os.stat(p)
                if (now - st.st_mtime) > MEI_MAX_AGE_SECONDS and (now - st.st_atime) > MEI_MAX_AGE_SECONDS:
                    # 仅清理「本程序」的 onefile 解包残留：目录内必须含本 exe 名，
                    # 不再碰其它 PyInstaller 程序的临时目录
                    if os.path.exists(os.path.join(p, "大肥鱼桌宠.exe")) and has_pyinstaller_signature(p):
                        shutil.rmtree(p, ignore_errors=True)
            except Exception:
                pass  # 有意忽略：单条目清理失败跳过（保守策略）
    except Exception:
        pass  # 有意忽略：残留清理是尽力而为的后台动作，失败不影响启动


def has_pyinstaller_signature(dir_path):
    """目录内是否有 PyInstaller onefile 解包特征，进一步降低误删普通目录的风险。

    说明：仍无法 100% 区分「其它正在运行的 PyInstaller 程序」的解包目录，
    故配合 7 天双时间戳阈值一起作为保守策略；残余风险已尽量压低。
    """
    try:
        for name in os.listdir(dir_path):
            if name.startswith("pyi-") or name == "base_library.zip":
                return True
        return False
    except Exception:
        return False


def acquire_single_instance():
    """单实例保护：命名互斥体已存在（另一实例在跑）则返回 False。

    使用 Local\\ 命名空间（当前登录会话内可见）：不跨用户会话冲突，
    也不需要 Global\\ 所需的 SeCreateGlobalPrivilege（标准用户可用）。
    """
    global _SINGLE_MUTEX
    try:
        k32 = ctypes.windll.kernel32
        k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        k32.CreateMutexW.restype = wintypes.HANDLE
        _SINGLE_MUTEX = k32.CreateMutexW(None, False, "Local\\DaFeiYuDesktopPet")
        # 第二进程打开已存在互斥体时句柄同样非空、且 GetLastError()=183，
        # 因此必须以错误码为准判断（不能按句柄非空判成功）
        return k32.GetLastError() != 183  # 183 = ERROR_ALREADY_EXISTS：另一实例在运行
    except Exception:
        return True  # 获取失败按放行处理


# 入口文件名（v2.12.0 第 12 轮 · 遗留-1）：新包用 main.py（崩溃自动重启的守护入口），
# 老包 / 入口被改名退回 桌宠.py。顺序写死在元组里，别在两处各判一次。
ENTRY_NAMES = ("main.py", "桌宠.py")


def entry_name(app_dir):
    """应用入口文件名：**先 main.py**（守护入口），没有再退回 桌宠.py。

    纯函数（只看磁盘上那个文件在不在），不 import Qt、不读环境变量 —— 测试可以拿临时目录
    直接喂三分支（两个都在 / 只有老入口 / 都没有）。
    """
    for name in ENTRY_NAMES:
        if os.path.isfile(os.path.join(app_dir, name)):
            return name
    return ENTRY_NAMES[-1]   # 都没有：回退老入口名（拼出来的路径不存在，用户能看见"打不开"）


def autostart_command(app_dir, sys_executable):
    """自启命令行：绿色版优先用 wscript 拉起 vbs（隐藏窗口）；源码运行用 pythonw。

    v2.12.0（第 12 轮 · 遗留-1）：三条兜底路径都改指 `entry_name()` —— 此前全写死 桌宠.py，
    于是"开机自启"拉起来的永远是**没有守护**的那个入口（打包 exe 上崩溃自动重启不执行）。
    """
    base = app_dir
    entry = entry_name(base)
    vbs = os.path.join(base, "启动桌宠.vbs")
    if os.path.isfile(vbs):
        ws = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "wscript.exe")
        return '"%s" "%s"' % (ws, vbs)
    pyw = os.path.join(base, "pythonw.exe")
    main_py = os.path.join(base, entry)
    if os.path.isfile(pyw) and os.path.isfile(main_py):
        return '"%s" "%s"' % (pyw, main_py)
    # 源码运行：优先同目录 pythonw（隐藏窗口），避免登录时闪控制台
    pyw_next = os.path.join(os.path.dirname(sys_executable), "pythonw.exe")
    if os.path.isfile(pyw_next):
        return '"%s" "%s"' % (pyw_next, os.path.join(base, entry))
    return '"%s" "%s"' % (sys_executable, os.path.join(base, entry))
