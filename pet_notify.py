# -*- coding: utf-8 -*-
"""系统通知（托盘气泡）—— v2.11.0 · W3-d「持续气泡 + 系统通知」的**通知那一半**。

来路（必须写清，别写成"用户要求"）
--------------------------------
本项来自**用户 #194 提交的两份附件方案**（"补-A12 精简升级方案" / "补-A13 UX 交互打磨方案"，
正文 AI 起草）里的「① 持续气泡 + 系统通知」，**2026-10-16 用户裁决并入 v2.11.0**；
登记在 `_dev/REMAINING.md` §十三 第 ① 行。**这 9 项没有一项是用户原话。**

零新依赖
--------
只用 Qt 自带的 `QSystemTrayIcon.showMessage`——现仓 `桌宠.py` 里的托盘对象早就建好了
（`self.tray = QSystemTrayIcon(self)`），只是**从来没发过一条通知**（v2.11.0 之前
`showMessage(` 全仓 0 命中）。不 import win32 / win10toast / plyer：那些会让绿色版多一份
运行库；而托盘气泡本来就是 Windows 上"不抢焦点也能提示用户"的原生通道。

为什么要把"发没发"当返回值（v2.11.0 三审 #1 修正口径）
-------------------------------------------------------
托盘通知**没有送达回执**：远程桌面、explorer 没起来、用户把托盘区折叠、系统关了通知，
`showMessage` 都会**静默什么也不做**。于是本模块只能回答"交没交给系统"，
回答不了"用户看没看见"；两者之间那段是 Qt/系统的事，本模块**不假装知道**。

所以调用方（`桌宠._notify`）**不再**拿这个返回值去决定"要不要退回气泡"——
旧口径（"只有另一条通道不可用才用第二条通道"，源自 `pet_dialogs._toast`）在这里是错的：
托盘的 False 是真的没交出去，但 True 也可能是系统把消息丢了。现在两条通道**各走各的**：
系统通知照发，宠物气泡照弹（气泡看得见就一定显示，是唯一有真回执的一条）。

返回值语义（**别读成"用户一定看见了"**）：True = 已经交给系统托盘；False = 没交出去
（静音 / 没有托盘对象 / 系统托盘不可用 / 同类正文还在限流窗口里 / showMessage 抛异常）。
Qt 不给我们更细的回执，本模块也不假装有——发布说明里同样不许写成"一定会弹出来"。
"""
import time

from PySide6.QtWidgets import QSystemTrayIcon

import pet_log

# 同类通知的默认限流窗口（秒）。30s 的依据：托盘气泡大约显示 10s，同一句话在"用户还没读完
# 上一条"时又弹一次，两条会互相顶掉（Windows 托盘只显示最新一条）——连发等于只有最后一条可见。
DEFAULT_THROTTLE_SEC = 30.0

# 限流状态：通知**正文** → 上一次尝试发送的时刻（time.monotonic 秒）。
# 键用正文而不是"标题+正文"：需求原话是"同一条文本 N 秒内只发一次"，而标题是产品名，
# 今天所有调用点都一样——拿它当键等于没限流。
_SEEN = {}


def _probe_tray_available():
    """系统托盘此刻到底有没有（**可注入探针**）。

    为什么单独抽一个函数：offscreen 平台 / 没有托盘桌面上
    `QSystemTrayIcon.isSystemTrayAvailable()` 为假——那一条**必须直接返回 False**
    （真去 showMessage 只会静默丢消息，还留一个"以为发了"的假象）。
    用例通过 monkeypatch 本函数来测"托盘可用"那一支，**不去骗 Qt**：
    探针与业务逻辑分开，两条分支才都测得到（"不可用"那条跑的是真探针）。

    探针自己出错（平台插件缺失 / Qt 未初始化）→ 按**不可用**处理（安全侧：宁可退回气泡，
    也不要抛给 UI 线程）。出错要留痕，但限流——探测失败往往是每拍都失败。
    """
    try:
        return bool(QSystemTrayIcon.isSystemTrayAvailable())
    except Exception as e:  # noqa: BLE001  平台插件缺失 / Qt 未初始化
        pet_log.log_throttled("pet_notify.probe", "系统托盘可用性探测失败：%r" % (e,))
        return False


def notify(tray, title, text, mute=False, throttle_sec=DEFAULT_THROTTLE_SEC, now=None):
    """发一条系统通知 → **到底发出去了没有**（True / False，从不抛）。

    参数：
      tray         托盘对象（`QSystemTrayIcon`；用例用只带 showMessage 的替身）。
                   为 None / 没有 showMessage → False（托盘还没建：早期启动、无桌面环境）。
      title, text  通知标题与正文。
      mute         True = 用户关了系统通知 → 不发。**也不占限流名额**：关掉的这一条不该把
                   "同一句话"的窗口占住，否则用户刚打开开关的第一条会被莫名其妙吞掉。
      throttle_sec 同类正文的限流窗口（秒，默认 DEFAULT_THROTTLE_SEC）。坏值回默认，
                   不抛——调用方可能是从配置里读出来的。
      now          注入时钟（默认 time.monotonic()）：用例据此断言"窗口内不再发、越界后又发"，
                   **不用 sleep**（本仓同款先例：pet_log.log_throttled 的 now 参数）。

    这里**每一条 return False 的路径**在 tests/test_bubble_hold_v2110.py 里都有独立用例，
    每条都写明"拿掉哪一行会红"（本仓规矩：判据必须能真失败）。
    """
    # ① 静音：最便宜的一条，连 Qt 都不问（用户关掉通知时，这条路径每拍都可能被走到）
    if mute:
        return False
    # ② 没有托盘对象：鸭子类型判据（hasattr）而不是 isinstance，
    #    这样替换身时不必伪造一个真的 QSystemTrayIcon（替身一旦要伪造 Qt 内部状态就会失真）
    if tray is None or not hasattr(tray, "showMessage"):
        return False
    # ③ 系统托盘不可用：真去调 showMessage 只会静默丢消息（offscreen / 远程桌面 / explorer 未起）
    if not _probe_tray_available():
        return False
    try:
        window = max(0.0, float(throttle_sec))
    except (TypeError, ValueError) as e:
        # 坏值回默认窗口（安全侧），但**要留痕**：throttle_sec 将来多半来自配置，
        # 静默回退会让"限流窗口怎么不生效"变成一个查不到的谜。限流日志（60s 一条）。
        pet_log.log_throttled("pet_notify.throttle_sec",
                              "通知限流窗口读不懂（按 %.0fs 处理）：%r（%r）"
                              % (DEFAULT_THROTTLE_SEC, throttle_sec, e))
        window = DEFAULT_THROTTLE_SEC
    t = time.monotonic() if now is None else float(now)
    key = str(text)
    # 先判窗口、**再**清过期记录。顺序反过来的话，"恰好到窗口"那一刻记录已经被清掉，
    # 于是 `< window` 与 `<= window` 观察不到任何差别（那条边界就成了不可测的死代码）。
    last = _SEEN.get(key)
    if last is not None and (t - last) < window:
        return False
    # 清过期记录：正文各不相同的通知（每条带时间/数字那种）不会把这张表越撑越大
    for _k in [k for k, ts in _SEEN.items() if (t - ts) >= window]:
        _SEEN.pop(_k, None)
    # ④ 限流记账放在**发送之前**：showMessage 抛异常也算"试过一次"——托盘真坏的时候重试
    #    一万次也不会成功，只会把 error.log 刷满。
    _SEEN[key] = t
    try:
        tray.showMessage(str(title), str(text))
    except Exception as e:  # noqa: BLE001  托盘对象在途被销毁等
        pet_log.log_throttled("pet_notify.showMessage", "系统通知发送失败：%r" % (e,))
        return False
    return True
