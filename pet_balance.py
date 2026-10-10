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
        threading.Thread(target=self._worker, args=(key,), daemon=True).start()

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

    def _worker(self, key):
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
            self.signals.balance_updated.emit(float(total), currency, float(granted))
        except Exception as e:
            self._log("balance_worker: %r" % (e,))
            self.signals.balance_err.emit()

    # ---- 信号落地（主线程槽） ----
    def on_updated(self, total, currency, granted):
        pet = self.pet
        if pet._closing:
            return  # P1-5：退出中不再响应在途余额结果
        pet._fetching_balance = False
        if pet._pending_manual:
            pet._pending_manual = False
            QTimer.singleShot(0, self, lambda: self.refresh(manual=True))  # 补发排队的手动查询
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
            QTimer.singleShot(0, self, lambda: self.refresh(manual=True))  # 补发排队的手动查询
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
    def set_budget(self):
        cfg = self._cfg()
        cur = cfg.get("budget", 0.0) or 0.0
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

    def add_manual_record(self):
        pet = self.pet
        book = self._book()
        if book is None:
            return
        try:
            dlg = pet_dialogs.AmountNoteDialog(pet)
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
