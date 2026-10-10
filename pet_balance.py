# -*- coding: utf-8 -*-
"""
余额服务：轮询 / 手动查询 / 记账联动 / 预算与余额预警 / 挂件刷新。

独立模块：不 import 桌宠.py；signals / cfg / book / play_sound / save_config 全部注入。
守卫状态（_fetching_balance / _manual_pending / _pending_manual）仍归属 PetWindow（语义不变）。
"""
import threading

import requests
from PySide6.QtCore import QEasingCurve, QTimer, QVariantAnimation
from PySide6.QtWidgets import QDialog

import pet_dialogs  # 账本 / 记一笔对话框（pet_dialogs 不 import 桌宠，无循环）
import pet_log  # v2.2.5：start() 里用 pet_log.guard_slot 包轮询槽，此前漏 import → 开启余额监控直接 NameError


class BalanceService:
    """余额线程服务：daemon thread + signals.balance_updated/balance_err。

    pet 提供：守卫标志（见模块说明）、_shown_balance/_currency/_usage/_balance_anim
    （挂件状态）、show_bubble/_show_emote/_fx_celebrate/_update_badge/on_ledger_changed/
    _ask_amount（预算/预警数值对话框，保留在桌宠）。
    """

    def __init__(self, pet, signals, cfg_getter, book_getter, play_sound, save_cfg, log, ask_api_key):
        self.pet = pet
        self.signals = signals
        self._cfg = cfg_getter
        self._book = book_getter
        self._play = play_sound
        self._save_cfg = save_cfg
        self._log = log
        self._ask_key = ask_api_key
        self._timer = None  # 5 分钟轮询定时器（对应原 pet._balance_timer）

    # ---- 轮询开关 ----
    def start(self):
        if self._timer is None:
            self._timer = QTimer(self.pet)
            self._timer.timeout.connect(pet_log.guard_slot("balance.refresh", lambda: self.refresh(manual=False)))
        self.refresh(manual=False)
        self._timer.start(300000)  # 5 分钟轮询：60s 太密，浪费额度且易被限流

    def stop(self):
        if self._timer is not None:
            self._timer.stop()

    # ---- 手动 / 定时刷新 ----
    def refresh(self, manual=False):
        key = self._cfg().get("api_key", "")
        if not key:
            return
        if self.pet._fetching_balance:
            # 在途请求未结束：手动查询排队，本次响应落地后自动补发
            if manual:
                self.pet._pending_manual = True
            return
        self.pet._fetching_balance = True
        self.pet._manual_pending = manual
        try:
            threading.Thread(target=self._worker, args=(key,), daemon=True).start()
        except Exception as e:
            # v2.4.3（第三轮找茬复审 M1）：start() 自己也会抛（线程/句柄耗尽、解释器关闭期
            # "can't start new thread"）。不兜住的话标志恒真，此后 refresh 一个线程都起不来
            # ——症状与 P1-1 那条守卫泄漏一模一样（点"查询余额"毫无反应），而泄漏点在 worker
            # 之外，worker 的 finally 兜不住。异常时复位标志 + 记日志 + 走 balance_err 路径。
            self.pet._fetching_balance = False
            self._log_safe("balance thread start failed: %r" % (e,))
            self._emit("balance_err")

    def fetch(self):
        """菜单「查询余额」：无 Key 先弹设置框；随后手动刷新。"""
        key = self._cfg().get("api_key", "")
        if not key:
            self._ask_key()
            if not self._cfg().get("api_key"):
                return
        self.pet._show_emote("question")
        self.pet.show_bubble("查余额中……等我一下下~")
        self.refresh(manual=True)

    def _request_balance(self, key):
        """同步查一次余额（纯 HTTP，不碰 Qt）。返回 (True, (总额, 币种, 赠送)) 或 (False, 详情)。"""
        try:
            resp = requests.get(
                "https://api.deepseek.com/user/balance",
                headers={"Authorization": "Bearer " + key},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            infos = data.get("balance_infos") or []
            total = granted = 0.0
            for info in infos:
                total += float(info.get("total_balance", "0") or 0)
                granted += float(info.get("granted_balance", "0") or 0)
            currency = (infos[0].get("currency") if infos else None) or "CNY"
            return True, (float(total), currency, float(granted))
        except Exception as e:
            return False, repr(e)

    def _closing(self):
        """退出中？（emit 端也要判——槽端 on_updated/on_err 早就判了，emit 端此前没判）

        取属性本身也可能抛（PetWindow 已销毁 → RuntimeError: wrapped C/C++ object ...），
        所以**抛**的时候一律按"在退出"处理：宁可不发，也不把异常带进 daemon 线程。

        v2.4.3（第三轮找茬复审 L①）：但"属性**不存在**"与"取属性抛"要分开——用
        getattr(..., False)。审查实测：shiboken6.delete(w) 之后 w._closing 照常返回，
        真正兜住"emit 到已删对象"的是 _emit 里的 except；而原先那种写法（直接访问 +
        兜底 True）在属性哪天改名时会把余额结果**永久丢弃且一行日志都不记**（静默）。
        改名后取到 False → 正常发；对象真销毁 → 取属性抛 → 仍按在退出处理。
        """
        try:
            return bool(getattr(self.pet, "_closing", False))
        except Exception:
            return True

    def _log_safe(self, msg):
        """日志回调自身出错不影响 worker（与 pet_io._log 同口径）。"""
        try:
            self._log(msg)
        except Exception:
            pass  # 有意忽略：日志通道失败绝不影响余额状态机

    def _emit(self, name, *args):
        """emit 一个信号；返回 True = 真的交出去了（False = 没交，调用方按兜底处理）。

        v2.4.3（第三轮找茬 P1-1）：退出中/对象已销毁一律不发——emit 到已 deleted 的
        C++ 对象会抛 RuntimeError，而这是 daemon 线程，异常只会往 stderr 打一行就没了。
        """
        if self._closing():
            return False
        try:
            getattr(self.signals, name).emit(*args)
            return True
        except Exception as e:
            self._log_safe("balance emit %s failed: %r" % (name, e))
            return False

    def _worker(self, key):
        """后台查一次余额并 emit 结果（daemon 线程）。**绝不向上抛，绝不漏复位守卫**。

        v2.4.3（第三轮找茬 P1-1）：此前 emit 裸露在 try 之外——① PetWindow 已销毁时
        emit 打到 deleted 的 C++ 对象上（RuntimeError），daemon 线程静默崩；② 若
        _request_balance 之后的某一行在 try 外抛，_fetching_balance 会**永真**，此后
        所有轮询与手动查询都被"在途"挡住（静默失效：用户点"查询余额"毫无反应）。

        现在：顶层 try/except/finally——
          · emit 前判 pet._closing（见 _emit），销毁/退出中直接不发；
          · 兜底 except 记日志并补发 balance_err（幂等：槽里已有 _closing 守卫）；
          · finally 里**无条件**复位 _fetching_balance（幂等，重复置 False 无副作用）。
        交出去的结果仍由槽（on_updated/on_err）按原语义处理；提前复位只影响"emit 已发出、
        槽还没轮到跑"的那一小段窗口——那个窗口里再来一次手动查询至多多发一次 HTTP，
        不会卡死，也不会丢掉排队的手动查询（_pending_manual 仍由槽消费）。
        """
        try:
            ok, payload = self._request_balance(key)
            if ok:
                total, currency, granted = payload
                self._emit("balance_updated", float(total), currency, float(granted))
            else:
                self._log_safe("balance_worker: %s" % (payload,))
                self._emit("balance_err")
        except Exception as e:
            # _request_balance 内部已全兜；这里防的是"它之后的行"（含参数解包、标志读写）
            self._log_safe("balance_worker crashed: %r" % (e,))
            self._emit("balance_err")
        finally:
            try:
                self.pet._fetching_balance = False
            except Exception:
                pass  # 有意忽略：pet 已销毁时连标志都不用管（进程正在退出）

    def fetch_sync(self):
        """v2.3.0（1.2 Function Calling）：工具 check_balance 的同步只读数据源。

        由 ChatService 的**工作线程**直接调用：只发 HTTP，不碰 Qt，也**不改守卫标志**
        （_fetching_balance/_manual_pending 属于轮询与手动查询的状态机，工具查询不参与，
        免得把在途轮询的状态搅乱）。返回 (True, dict) 或 (False, 错误文案)。
        """
        key = self._cfg().get("api_key", "")
        if not key:
            return False, "还没设置 API Key，先让绳匠填一下"
        ok, payload = self._request_balance(key)
        if not ok:
            self._log("balance fetch_sync failed: %s" % (payload,))
            return False, "余额查不到（检查 API Key 或网络）"
        total, currency, granted = payload
        unit = "¥" if currency == "CNY" else (str(currency) + " ")
        return True, {"balance": round(total, 2), "currency": currency,
                      "granted": round(granted, 2),
                      "summary": "余额 %s%.2f（赠送 %.2f）" % (unit, total, granted)}

    # ---- 信号落地（主线程槽） ----
    def on_updated(self, total, currency, granted):
        pet = self.pet
        if pet._closing:
            return  # P1-5：退出中不再响应在途余额结果
        pet._fetching_balance = False
        if pet._pending_manual:
            pet._pending_manual = False
            # v2.3.1（P2-1）：receiver 必须是 QObject——BalanceService 不是，传 self 会
            # TypeError/连接异常；pet（QWidget）才是合法 receiver（同时保证窗口销毁后不再回调）
            QTimer.singleShot(0, self.pet, lambda: self.refresh(manual=True))  # 补发排队的手动查询
        if not self._cfg().get("api_key"):
            return  # Key 已清空，忽略在途请求结果
        pet._currency = currency
        pet._usage = self.update_ledger(total)  # 记账在主线程，避免跨线程读写
        if pet._manual_pending:
            pet._manual_pending = False
            if currency == "CNY":
                pet.show_bubble("余额 ¥%.2f · 今日已用 ¥%.2f（赠送 ¥%.2f）" % (total, pet._usage, granted))
            else:
                pet.show_bubble("余额 %s %.2f · 今日已用 %.2f（赠送 %.2f）" % (currency, total, pet._usage, granted))
            if self._cfg().get("sound", True):
                self._play("coin")  # 金币音（借参考插件任务结束音概念）
            pet._fx_celebrate()     # 撒钱动画
        if pet._balance_anim is not None:
            try:
                pet._balance_anim.stop()
                pet._balance_anim.deleteLater()
            except RuntimeError:
                pass  # 对象可能已被自然结束路径删除
            pet._balance_anim = None
        if pet._shown_balance is None or abs(pet._shown_balance - total) < 0.005:
            pet._shown_balance = float(total)
            pet._update_badge()
            return
        start = pet._shown_balance
        anim = QVariantAnimation(pet)
        anim.setDuration(700)
        anim.setStartValue(float(start))
        anim.setEndValue(float(total))
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def onval(v):
            pet._shown_balance = float(v)
            pet._update_badge()

        anim.valueChanged.connect(onval)
        anim.finished.connect(lambda: setattr(pet, "_shown_balance", float(total)))
        anim.finished.connect(lambda: setattr(pet, "_balance_anim", None))  # 自然结束即清引用，防悬空
        anim.finished.connect(anim.deleteLater)
        pet._balance_anim = anim
        anim.start()

    def on_err(self):
        pet = self.pet
        if pet._closing:
            return  # P1-5：退出中不再响应在途余额错误
        pet._fetching_balance = False
        if pet._pending_manual:
            pet._pending_manual = False
            # v2.3.1（P2-1）：receiver 必须是 QObject——BalanceService 不是，传 self 会
            # TypeError/连接异常；pet（QWidget）才是合法 receiver（同时保证窗口销毁后不再回调）
            QTimer.singleShot(0, self.pet, lambda: self.refresh(manual=True))  # 补发排队的手动查询
        if pet._manual_pending:
            pet._manual_pending = False
            pet.show_bubble("余额查不到……API Key 对吗？")
        # 网络抖动：沿用最近余额，不报错（参考项目行为）

    def update_ledger(self, total):
        """余额差记账（v1.3 起由 pet_book.Book 承担）：跨天归档 + 今日累计 + 预算/余额预警。"""
        pet = self.pet
        book = self._book()
        if book is None:
            return 0.0
        try:
            note = book.observe_balance(total)
            if note:
                pet.show_bubble(note)
            usage = book.today_usage()
            cfg = self._cfg()
            alerts = book.check_alerts(total, cfg.get("budget", 0.0), cfg.get("balance_alert", 0.0))
            for msg in alerts:
                pet.show_bubble(msg)
                if cfg.get("sound", True):
                    self._play("reply")
            return usage
        except Exception as e:
            self._log("update_usage_ledger failed: %r" % (e,))
            return 0.0

    # ---- 预算 / 预警 / 记一笔 / 账本（对话框入口，原 PetWindow 方法迁移） ----
    def set_budget(self, amount=None):
        """今日预算。v2.3.0（1.2）：工具调用传来的金额只作输入框**预填值**，仍由用户确认。"""
        cfg = self._cfg()
        cur = cfg.get("budget", 0.0) or 0.0
        if amount is not None:
            try:
                cur = max(0.0, float(amount))
            except (TypeError, ValueError):
                cur = cfg.get("budget", 0.0) or 0.0  # 非数字：忽略预填，用现值
        val = self.pet._ask_amount("今日预算", "今日已用超过多少元时提醒？\n（0 = 关闭提醒）", cur)
        if val is None:
            return
        cfg["budget"] = val
        self._save_cfg(cfg)
        self.pet.show_bubble("预算 %.2f 元%s" % (val, "" if val > 0 else "（提醒已关闭）"))

    def set_balance_alert(self):
        cfg = self._cfg()
        cur = cfg.get("balance_alert", 0.0) or 0.0
        val = self.pet._ask_amount("余额预警", "余额低于多少元时提醒？\n（0 = 关闭提醒）", cur)
        if val is None:
            return
        cfg["balance_alert"] = val
        self._save_cfg(cfg)
        self.pet.show_bubble("余额预警 %.2f 元%s" % (val, "" if val > 0 else "（提醒已关闭）"))

    def add_manual_record(self, amount=None, note=""):
        """记一笔。v2.3.0（1.2）：工具带上的金额/备注只作对话框**预填**，最终由用户确认。"""
        pet = self.pet
        book = self._book()
        if book is None:
            return
        try:
            dlg = pet_dialogs.AmountNoteDialog(pet, amount, note)
            pet_dialogs.modal(dlg)
            if dlg.result() == QDialog.DialogCode.Accepted:
                amount, note = dlg.values()
                if amount and amount > 0:
                    book.add_manual(amount, note)
                    pet.on_ledger_changed()
                    pet.show_bubble("记好啦：%.2f 元" % amount)
        except Exception as e:
            self._log("add_manual_record failed: %r" % (e,))

    def open_ledger(self):
        try:
            dlg = pet_dialogs.LedgerDialog(self.pet)
            pet_dialogs.modal(dlg)
        except Exception as e:
            self._log("ledger dialog failed: %r" % (e,))
