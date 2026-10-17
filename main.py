# -*- coding: utf-8 -*-
"""大肥鱼桌宠 主入口（P2-4 命名治理：main.py 为规范入口）。

桌宠.py 保留为兼容壳（绿色版 启动桌宠.vbs 与老脚本仍指向它，行为不变）。

v2.11.0（第 11 轮 · 旧第 8 轮那批 ④）：**本文件兼作"崩溃自动重启"的守护入口**。
  · 正常退出（用户点「⏹ 退出」/ 关窗）→ **不重启**，只留一条"正常退出"标记；
  · 异常退出（进程级死亡 / 非 0 退出码）→ 按 pet_guard 的**退避 + 熔断**重新拉起；
  · 熔断（窗口内达上限）→ 不重启，并**用系统消息框**告诉用户（不弹 Qt 模态框 —— 那正是
    今天 excepthook 的老毛病：进程已经死了，弹框还得靠一个已经没了的 Qt 事件循环）。
判定/退避/标记全在 pet_guard（纯逻辑、可单测）；这里只做三件事：跑、判、拉。

三个必须照做的坑（来自 pet_guard 包的实测）：
  ① 拉起前要 **CloseHandle 释放单实例互斥体**，否则子进程 CreateMutexW 拿到 183 会静默退出
     （表现为"重启了但什么都没起来"）；
  ② 进 桌宠.main() 之前要 **把 --guard-restart 从 sys.argv 摘掉**（否则它会一路喂给 QApplication）；
  ③ 源码运行优先用同目录 **pythonw.exe**（用 python.exe 会闪一下黑框）。
"""
import ctypes
import os
import subprocess
import sys
import time

# 支持从任意目录运行（bat/README 均会 cd 到本目录，此处防御性补足）
APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)

import pet_guard
import pet_log
import 桌宠


def _tell_user(text):
    """进程级"告诉用户"：系统消息框（零新依赖）。**不用 Qt** —— 那时事件循环已经没了。"""
    try:
        ctypes.windll.user32.MessageBoxW(0, str(text), "大肥鱼桌宠", 0x40)
    except Exception as e:  # noqa: BLE001 —— 提示失败也不能把退出流程带崩
        # **出声**（本仓口径：写错了的错必须出声）：能写 stderr 就写一行。
        # 这里不套 try —— stderr 为 None 时才跳过（打包成无控制台的 exe 时会发生）。
        if sys.stderr is not None:
            sys.stderr.write("notify failed: %r\n" % (e,))


def _release_single_mutex():
    """坑①：把单实例互斥体放掉，子进程才起得来（先关句柄再置空）。"""
    try:
        import pet_main
        handle = getattr(pet_main, "_SINGLE_MUTEX", None)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            pet_main._SINGLE_MUTEX = None
    except Exception as e:  # noqa: BLE001 —— 放不掉只影响"能不能重启"，不影响本次退出
        sys.stderr.write("release mutex failed: %r\n" % (e,))


def _child_command():
    """坑③：源码运行优先 pythonw.exe；冻结版（PyInstaller）没有 .py 可喂，只带 flag。"""
    exe = sys.executable
    if not getattr(sys, "frozen", False):
        pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.isfile(pyw):
            exe = pyw
    entry = None if getattr(sys, "frozen", False) else os.path.join(APP_DIR, "main.py")
    return pet_guard.restart_command(exe, entry)


def run():
    """守护主循环：跑一次桌宠、判要不要再拉起、必要时退避后拉一次，然后自己退出。

    返回值 = 本次运行的退出码（让外层 bat/快捷方式/CI 能看见"是不是正常结束"）。
    """
    # 坑②：flag 只用来表达"我是被拉起的"，进 Qt 之前摘掉
    if pet_guard.RESTART_FLAG in sys.argv:
        sys.argv.remove(pet_guard.RESTART_FLAG)
    launched = pet_guard.is_guard_launch()

    marker_file = pet_guard.marker_path(APP_DIR)
    marker = pet_guard.load_marker(marker_file)

    code, clean = 0, False
    try:
        桌宠.main()
        clean = True                      # 正常返回 = 唯一路径是"已有实例"（另开一次）→ 也算正常
    except SystemExit as e:
        # 退出码**要留痕**（不是吞掉）：这条 except 被静默 except 审计按"动态调度器"看过一眼
        # （函数名 run 命中了它的正则），补一行限流日志既让审计看见"这里上报了"，也让
        # error.log 里能查到"这次是怎么退出的"。
        code = pet_guard.exit_status(e.code)
        clean = (code == 0)
        pet_log.log_throttled("guard:exit", "pet exit code=%s clean=%s" % (code, clean))
    except BaseException as e:            # noqa: BLE001 —— 任何冒到这里的异常都算崩溃
        sys.stderr.write("crash: %r\n" % (e,))
        code = 1

    now = time.time()
    # 判定**只做一次**（v2.11.0 三审 #3）：旧版先 decide 一次、再拿 marker 里的重启历史
    # 建第二个 policy 又 decide 一次，第一次的结果当场被覆盖——那是死代码，还让人误以为
    # "接管失败会退回第一次判定"（两次的入参除了 restarts 完全一样，根本没有"降级"可言）。
    # pet_guard 的接法写在自己的模块头（adopt_marker 一次 → decide → spawn → note_restart）。
    policy = pet_guard.SupervisorPolicy(clock=time.time)
    try:
        # 历史里已记过的重启次数要接上（否则熔断形同虚设：每次进程一死就忘了上次拉过）
        policy.adopt_marker(marker)
    except Exception as e:  # noqa: BLE001 —— 接管不到历史就按"没有历史"判（多给一次机会，安全侧）
        # 留痕（不许静默）：审计会把"run 里吞异常"读成"调用方以为成功"，所以这里必须出声。
        pet_log.log_throttled("guard:adopt", "adopt restarts failed: %r" % (e,))
    decision = policy.decide(code, normal_exit=clean, now=now)

    if decision.should_restart:
        time.sleep(max(0.0, float(decision.delay_seconds or 0.0)))
        cmd = _child_command()
        if not cmd:
            # 拉不起来也**不许**把"这次拉过"记进窗口：那是熔断的唯一计数依据，
            # 记一次没发生的重启 = 用户白丢一次机会（pet_guard.note_restart 的 docstring）。
            pet_guard.save_marker(marker_file, pet_guard.record_crash(
                marker, exit_code=code, now=now))
            _tell_user("自动重启没能拉起（找不到可执行文件）。")
            return code
        _release_single_mutex()
        try:
            subprocess.Popen(cmd, cwd=APP_DIR, close_fds=True,
                             creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        except Exception as e:            # noqa: BLE001 —— 拉不起来只提示，绝不记"拉起过"
            # 留痕 + 提示：**这里不是"少记一次"，是"不该记"**——spawn 抛异常就说明没拉起，
            # 旧注释写成"少记一次（免得一次崩溃被数两回）"与它自己做的事（先记后 spawn）矛盾。
            pet_log.log_throttled("guard:spawn", "restart spawn failed: %r" % (e,))
            pet_guard.save_marker(marker_file, pet_guard.record_crash(
                marker, exit_code=code, now=now))
            _tell_user("自动重启没能拉起：%s" % (e,))
            return code
        # **spawn 成功之后**才记"真的拉起过"（pet_guard：note_restart 只在拉起之后调；
        # record_crash 的 will_restart 语义同样是"真的拉起过"，不是"崩溃过"）。
        # 两处都记是有意的：policy 是**本进程内**的策略壳，盘上的 marker 才是跨进程的唯一依据
        # （下一个进程 load_marker → adopt_marker 读到它）；两次记的是同一个 now，不会算两回。
        if not policy.note_restart(now=now):
            pet_log.log_throttled("guard:clock",
                                  "note_restart 拿不到可信时钟：本次重启没进窗口计数")
        pet_guard.save_marker(marker_file, pet_guard.record_crash(
            marker, exit_code=code, now=now, will_restart=True))
        return code

    if clean:
        pet_guard.save_marker(marker_file, pet_guard.record_clean_exit(marker, now=now))
    else:
        pet_guard.save_marker(marker_file, pet_guard.record_crash(marker, exit_code=code, now=now))
        if decision.notify_user:
            _tell_user(decision.reason)
    return code


if __name__ == "__main__":
    sys.exit(run())
