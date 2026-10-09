# -*- coding: utf-8 -*-
"""
大肥鱼桌宠 · 特效帧动画（AnimatedEmote，阶段 3）
MIT License
Copyright (c) 大肥鱼桌宠项目

职责：把一个「一次性特效」的帧序列（如摸摸头 petpet_f00..09、撒钱 money_f00..85）
画在主程序已有的 QGraphicsPixmapItem 上（主程序在 QGraphicsScene 里创建的 emote_item），
由 QTimer 驱动换帧，播完后自动收起。

典型用法（主程序侧）::

    # __init__：item 由调用方创建并 addItem（与现有 emote_item 用法一致）
    self.emote_item = QGraphicsPixmapItem()
    self.emote_item.hide()
    self.scene.addItem(self.emote_item)
    self.fx = pet_fx.AnimatedEmote(self.emote_item, self)

    # 摸摸头
    self.fx.play(pet_fx.load_frame_set(fx_dir, "petpet", 10),
                 interval_ms=66, loops=1, on_finish=lambda em: self._on_fx_done())

    # 撒钱（更长的帧集可以配更短的间隔）
    self.fx.play(pet_fx.load_frame_set(fx_dir, "money", 86), interval_ms=30, loops=1)

    # 也可只监听信号：self.fx.finished.connect(self._on_fx_done)

对外接口：
- AnimatedEmote(item, parent=None)：绑定一个 QGraphicsPixmapItem。
- play(frames, interval_ms=66, loops=1, on_finish=None) -> bool：
  frames 为 QPixmap 列表（由 pet_anim.load_frame_set 加载）；loops=-1 无限循环，
  loops>=1 播完对应遍数后停止；空列表 / loops=0 视为「立即播完」，回调照发、返回 False。
  播放前自动 stop() 上一次，首帧立即 setPixmap + show()。
- stop(hide=True)：停表并隐藏 item（hide=False 可保留最后一帧）。
- is_playing：只读属性，定时器在跑即为 True。
- finished 信号：自然播完时（有限遍数播完 / 空帧集立即结束）发射一次；
  被 stop() 主动打断不发。

设计要点：
- 定时器选型：复用 __init__ 里建好的单个成员 QTimer（不每次 play 新建 / deleteLater）。
  理由：摸摸头这类交互会高频重复触发，复用定时器不产生对象堆积，也不会出现
  「旧定时器已 deleteLater 但事件循环里仍排队一次 timeout」的边界问题；
  换帧间隔用 setInterval 就地改，开销可忽略。这与 pet_anim.FrameAnim 的既有做法一致。
- 帧集只保存 QPixmap 引用，不复制像素。
- 异常策略：真实异常经 pet_log 记日志后兜底；销毁竞态（item / 定时器已销毁
  的 RuntimeError）与用户回调异常有意静默（# 有意忽略 注释），绝不抛出打断主循环。
- 仅依赖 PySide6.QtCore / QtGui 与 pet_anim，模块可在无 GUI 环境 import。

Python 3.10+（项目运行环境 3.10.2）。
"""

from PySide6.QtCore import QObject, QTimer, Signal

import pet_log

# 复用项目既有帧集加载工具（读 <prefix>_f%02d.png）；同时方便外部 from pet_fx import load_frame_set
from pet_anim import load_frame_set


class AnimatedEmote(QObject):
    """帧序列特效播放器：驱动一个 QGraphicsPixmapItem 播放帧集。

    一个实例对应一个 item（主程序通常就是 emote_item），可反复 play 不同帧集；
    每次 play 都会先 stop() 上一次播放，因此重复触发（例如连续摸头）是幂等安全的。
    """

    # 自然播完时发射（有限遍数播完 / 空帧集立即结束）；stop() 主动打断不发。
    finished = Signal()

    def __init__(self, item, parent=None):
        """item：调用方创建并 addItem 的 QGraphicsPixmapItem；parent：可选 QObject 父对象。"""
        super().__init__(parent)

        self._item = item       # 目标 item（只引用，不接管所有权）
        self._frames = []       # 当前帧集（QPixmap 引用，不复制像素）
        self._index = 0         # 当前帧下标
        self._emitted = 0       # 本次已展示帧数：play 立即展示首帧并计 1，N 遍共展示 N×len(frames) 帧
        self._loops = 1         # 目标遍数：-1 无限，>=1 有限
        self._on_finish = None  # 播完回调（单参数，收 self）
        self._finishing = False  # 防重入：收尾过程中回调里再次 play 不会重复收尾

        # 定时器选型：单个成员 QTimer 复用（理由见模块 docstring）
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)

    # ---------------- 对外接口 ----------------
    def play(self, frames, interval_ms=66, loops=1, on_finish=None):
        """播放帧集，成功返回 True。

        - frames 为 QPixmap 列表；空列表视为「立即播完」：回调 on_finish 与 finished 照发，返回 False。
        - loops=-1 无限循环（需外部 stop()）；loops>=1 播完对应遍数后自动停止并回调。
        - 播放前自动 stop() 上一次；首帧立即 setPixmap 并 show()。
        - on_finish 为单参数回调，收 self；任何异常都被吞掉，绝不抛出。
        """
        try:
            self.stop()  # 重复 play：先停旧再开新（幂等安全）

            try:
                frame_list = list(frames) if frames else []
            except Exception:
                frame_list = []  # 帧集不可迭代：按空集处理

            self._frames = frame_list
            self._index = 0
            self._emitted = 0
            try:
                self._loops = int(loops)
            except Exception:
                self._loops = 1
            self._on_finish = on_finish

            if not frame_list or self._loops == 0:
                # 没有可播内容（或显式 0 遍）：视为「立即播完」，照样回调 + 发信号
                self._finish()
                return False

            # 首帧立即上屏
            self._item.setPixmap(frame_list[0])
            self._item.show()
            self._emitted = 1

            # 边界：单帧 + loops=1 —— 首帧已经是唯一一帧，直接收尾
            if self._loops > 0 and self._emitted >= self._loops * len(frame_list):
                self._finish()
                return True

            self._timer.setInterval(max(1, int(interval_ms)))
            self._timer.start()
            return True
        except Exception:
            # 任何异常（含 item 已销毁）：静默收尾，不向上抛
            self.stop()
            return False

    def stop(self, hide=True):
        """停止播放并清理待触发的回调；hide=True（默认）时同时隐藏 item。

        选择「默认隐藏」的原因：本类服务的是「一次性特效」（摸摸头 / 撒钱），
        被打断或播完后就该从画面上消失，这与主程序 emote_item 的既有用法一致。
        若调用方需要保留最后一帧（例如把特效当静态贴图钉在场景里），传 hide=False。
        """
        try:
            if self._timer.isActive():
                self._timer.stop()
            self._on_finish = None  # 主动停止 / 重新 play 时，旧回调不再触发
            if hide:
                self._item.hide()
        except Exception:
            pass  # item / 定时器可能已随 C++ 对象销毁，静默跳过

    @property
    def is_playing(self):
        """只读：是否正在播放（定时器在跑）。"""
        try:
            return bool(self._timer.isActive())
        except Exception:
            return False

    def current(self):
        """返回当前帧 QPixmap；从未播放过时返回 None。"""
        try:
            if self._frames:
                return self._frames[self._index]
        except Exception as e:
            pet_log.log_error("pet_fx.current: %r" % (e,))
        return None

    # ---------------- 内部 ----------------
    def _advance(self):
        """定时器回调：切到下一帧；有限遍数播满后收尾。"""
        try:
            n = len(self._frames)
            if n == 0:
                self._finish()
                return

            self._index = (self._index + 1) % n
            self._emitted += 1
            self._item.setPixmap(self._frames[self._index])

            if self._loops > 0 and self._emitted >= self._loops * n:
                self._finish()
        except Exception:
            # 换帧出错就静默收尾，避免定时器空转
            self._finish()

    def _finish(self):
        """收尾：停表 + 隐藏 + 发 finished 信号 + 回调 on_finish(self)。

        防重入只在「收尾动作本身」期间生效；进入回调/发信号前先复位 _finishing，
        否则回调里重入 play() 的立即收尾会被吞掉（L2 修复）。
        """
        if self._finishing:
            return
        self._finishing = True
        try:
            cb = self._on_finish  # 先取回调：stop() 会清空 _on_finish
            self.stop()
            self._finishing = False  # 回调期间允许重入 play
            self.finished.emit()  # 注：Qt 信号槽内异常由 Qt 捕获打印，emit 侧 try 捕获不到（不包）
            if cb:
                try:
                    cb(self)
                except Exception:
                    pass  # 回调里出错不影响播放器状态
        except Exception as e:
            pet_log.log_error("pet_fx._finish 兜底: %r" % (e,))
        finally:
            self._finishing = False


# ---------------- 冒烟测试（无显示器环境，可直接运行本文件） ----------------
if __name__ == "__main__":
    # P0-2：以下 print 为命令行冒烟工具输出（python pet_fx.py 运行可见），保留不改为日志
    import os
    import sys

    # 无头运行：必须在 QApplication 创建前设置（已显式指定时尊重外部设置）
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QGraphicsScene, QGraphicsPixmapItem

    ASSETS_FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fx")

    app = QApplication(sys.argv)
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem()
    item.hide()
    scene.addItem(item)

    fx = AnimatedEmote(item)

    petpet = load_frame_set(ASSETS_FX, "petpet", 10)   # 10 帧
    money = load_frame_set(ASSETS_FX, "money", 86)     # 86 帧

    fails = []
    finished_count = [0]
    calls = []

    fx.finished.connect(lambda: finished_count.__setitem__(0, finished_count[0] + 1))

    def check(name, cond, extra=""):
        print("  [%s] %s%s" % ("PASS" if cond else "FAIL", name, (" — " + extra) if extra else ""))
        if not cond:
            fails.append(name)

    print("=== pet_fx.AnimatedEmote 冒烟测试（offscreen） ===")
    print("assets/fx:", ASSETS_FX)
    print("petpet 帧数:", len(petpet), "| money 帧数:", len(money))
    check("素材加载：petpet 10 帧", len(petpet) == 10)
    check("素材加载：money 86 帧", len(money) == 86)

    # ---- 阶段 1：petpet（10 帧，默认 interval_ms=66，loops=1） ----
    def petpet_start():
        ok = fx.play(petpet, loops=1, on_finish=lambda em: calls.append(("petpet", em)))
        check("petpet: play() 返回 True", ok is True)
        check("petpet: 首帧立即 setPixmap",
              item.pixmap().cacheKey() == petpet[0].cacheKey())
        check("petpet: 首帧立即 show()（item 可见）", item.isVisible())
        check("petpet: is_playing == True", fx.is_playing is True)

    def petpet_done():
        check("petpet: 播完后 is_playing == False", fx.is_playing is False)
        check("petpet: 播完后 item 隐藏", not item.isVisible())
        check("petpet: finished 信号触发 1 次", finished_count[0] == 1,
              "得到 %d 次" % finished_count[0])
        check("petpet: on_finish 回调 1 次且参数为 AnimatedEmote 实例",
              len(calls) == 1 and calls[0][0] == "petpet" and calls[0][1] is fx)

    # ---- 阶段 2：money（86 帧，interval_ms=30，loops=1） ----
    def money_start():
        ok = fx.play(money, interval_ms=30, loops=1, on_finish=lambda em: calls.append(("money", em)))
        check("money: play() 返回 True", ok is True)
        check("money: 首帧立即 setPixmap",
              item.pixmap().cacheKey() == money[0].cacheKey())
        check("money: is_playing == True", fx.is_playing is True)

    def money_done():
        check("money: 播完后 is_playing == False", fx.is_playing is False)
        check("money: 播完后 item 隐藏", not item.isVisible())
        check("money: finished 信号累计 2 次", finished_count[0] == 2,
              "得到 %d 次" % finished_count[0])
        check("money: on_finish 回调累计 2 次且第二次带 self",
              len(calls) == 2 and calls[1][0] == "money" and calls[1][1] is fx)

    # ---- 阶段 3：无限循环 loops=-1 + stop() ----
    def inf_start():
        finished_count[0] = 0
        ok = fx.play(petpet, interval_ms=30, loops=-1)
        check("无限循环: play() 返回 True", ok is True)
        check("无限循环: is_playing == True", fx.is_playing is True)
        check("无限循环: item 可见", item.isVisible())

    def inf_done():
        check("无限循环: 400ms 后仍在播放（未自动收尾）", fx.is_playing is True)
        fx.stop()
        check("无限循环: stop() 后 is_playing == False", fx.is_playing is False)
        check("无限循环: stop() 后 item 隐藏", not item.isVisible())
        check("无限循环: stop() 不发 finished（非自然播完）", finished_count[0] == 0,
              "得到 %d 次" % finished_count[0])

    # ---- 阶段 4：边界（空帧集 / 重复 play 幂等） ----
    def edge_cases():
        finished_count[0] = 0
        empty_calls = []
        ret = fx.play([], interval_ms=30, loops=1, on_finish=lambda em: empty_calls.append(em))
        check("空帧集: 返回 False", ret is False)
        check("空帧集: on_finish 立即回调且带 self",
              len(empty_calls) == 1 and empty_calls[0] is fx)
        check("空帧集: 视为立即播完，finished 触发 1 次", finished_count[0] == 1)
        check("空帧集: 未进入播放态", fx.is_playing is False)

        for _ in range(3):  # 连续 play：旧定时器复用，不抛、不堆积
            fx.play(money, interval_ms=30, loops=-1)
            fx.play(petpet, interval_ms=30, loops=-1)
        check("重复 play 幂等: 连续 6 次 play 后仍在播放", fx.is_playing is True)
        fx.stop()
        check("重复 play 幂等: stop() 后停止且隐藏",
              fx.is_playing is False and not item.isVisible())

    def finish():
        print("-----------")
        if fails:
            print("PET_FX SMOKE FAILED: %d 项未通过 -> %s" % (len(fails), fails))
            app.exit(1)
        else:
            print("PET_FX SMOKE OK")
            app.exit(0)

    # 时序驱动：每步执行后等一段（留足动画时间）再进下一步
    plan = [
        ("阶段 1：petpet 10 帧（默认 66ms，loops=1）", petpet_start, 1000),
        ("阶段 1 校验：播完状态", petpet_done, 20),
        ("阶段 2：money 86 帧（30ms，loops=1）", money_start, 3400),
        ("阶段 2 校验：播完状态", money_done, 20),
        ("阶段 3：无限循环 loops=-1", inf_start, 400),
        ("阶段 3 校验：stop() 生效", inf_done, 20),
        ("阶段 4：边界（空帧集 / 重复 play）", edge_cases, 20),
    ]

    def drive():
        if not plan:
            finish()
            return
        title, func, delay = plan.pop(0)
        print("-- " + title)
        func()
        QTimer.singleShot(delay, drive)

    QTimer.singleShot(0, drive)
    sys.exit(app.exec())
