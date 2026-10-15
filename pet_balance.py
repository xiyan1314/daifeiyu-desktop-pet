# -*- coding: utf-8 -*-
"""
余额服务：轮询 / 手动查询 / 记账联动 / 预算与余额预警 / 挂件刷新。

独立模块：不 import 桌宠.py；signals / cfg / book / play_sound / save_config 全部注入。
守卫状态（_balance_gen / _balance_active_gen / _manual_pending / _pending_manual）仍归属
PetWindow；v2.4.4（A-1）把"在途"从**一个布尔**换成**请求代次**——原因见 refresh/_worker/
_consume 的注释，一句话：布尔会被"结果已 emit、槽还没轮到跑"的窗口提前复位。
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
        """发起一次刷新：**同一时刻最多一个在途请求**，多出来的手动查询排队等它落地。

        v2.4.4（A-1，审查探针实测 started==2）：调度判据从一个布尔 _fetching_balance
        换成**请求代次**。旧口径里 worker 的 finally 无条件复位标志，而结果这时还在事件
        队列里排队等槽跑——用户在这一小段窗口里再点一次「查询余额」会真的起第二个并发
        线程；随后先到的槽把新请求的标记一起抹掉，于是**反馈会落到别的结果上**（重复 /
        错配：气泡、金币音、撒钱按"当前那一代"的标记算，而不是发起它的那一次点击）。
        （v2.4.4 质量审查校正：此前这里写的是"两个请求各弹一次气泡、各放一次金币音、各撒
        一次钱"——那句从旧代码推不出来，能验证的口径只有上面这句。）
        现在 _balance_active_gen 只在**槽消费完那一代**（或结果根本没交出去，见 _retire）
        时才清空，窗口内再来一次只会置 _pending_manual 排队：连点不再多起一个并发请求，
        反馈也不再错配。
        """
        key = self._cfg().get("api_key", "")
        if not key:
            return
        # v2.4.4（兼容审查 L2）：与 _consume/_retire 同口径用 getattr 读——refresh 是 Qt 槽
        # （菜单 / 补发定时器）调的，替身 pet 或属性改名时裸取会在这里抛 AttributeError，
        # 症状就是"点查询余额毫无反应"。
        if getattr(self.pet, "_balance_active_gen", None) is not None:
            # 在途请求未结束（含"结果已 emit、槽还没轮到跑"那一小段）：手动查询排队，
            # 本次结果落地后由槽补发；自动轮询直接跳过（下一次轮询再来）。
            if manual:
                self.pet._pending_manual = True
            return
        gen = int(getattr(self.pet, "_balance_gen", 0) or 0) + 1
        self.pet._balance_gen = gen          # 代次单调自增：请求与结果一一对应
        self.pet._balance_active_gen = gen   # 在途/待消费的那一代（None = 空闲）
        self.pet._manual_pending = manual    # 手动标记只对**这一代**有效
        try:
            threading.Thread(target=self._worker, args=(key, gen), daemon=True).start()
        except Exception as e:
            # v2.4.3（第三轮找茬复审 M1）：start() 自己也会抛（线程/句柄耗尽、解释器关闭期
            # "can't start new thread"）。不兜住的话标志恒真，此后 refresh 一个线程都起不来
            # ——症状与 P1-1 那条守卫泄漏一模一样（点"查询余额"毫无反应），而泄漏点在 worker
            # 之外，worker 的收尾兜不住。异常时：记日志 + 把这一代交回 balance_err 路径。
            self._log_safe("balance thread start failed: %r" % (e,))
            if not self._emit("balance_err", gen):
                self._retire(gen, "线程启动失败且 balance_err 也交不出去")

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

    def _retire(self, gen, why):
        """把 gen 那一代收尾（只在它**仍是当前那一代**时生效）——worker 交不出去时的兜底。

        v2.4.4（A-1）：worker 不再无条件复位守卫（那会让"结果已在队列里、槽还没跑"的
        窗口提前放行 → 第二个并发线程）。只有当结果**没能**交给槽时（退出中 / emit 抛），
        才由 worker 自己收尾，否则那一代永远挂着，后续查询全被"在途"挡住（= P1-1 那条
        守卫泄漏）。旧代不许动新代的状态——这正是"先到的槽抹掉新请求标记"的根因。
        """
        pet = self.pet
        try:
            if getattr(pet, "_balance_active_gen", None) == gen:
                # v2.4.4（兼容审查 L1）：**先清手动标记，再放行代次**——反过来的话主线程只要
                # 在这两条语句之间抢到 GIL 并跑 refresh(manual=True)，新开的这代会拿到
                # "已被上一代清成 False"的 _manual_pending：结果照常落地却不再弹气泡/放金币音
                # /撒钱（与上一段"旧代不许动新代状态"矛盾）。
                pet._manual_pending = False   # 该代的手动标记随代次一起作废
                pet._balance_active_gen = None
        except Exception:
            pass  # 有意忽略：窗口已销毁时连标志都不用管（进程正在退出）
        self._log_safe("balance: 代次 %s 由 worker 收尾（%s）" % (gen, why))

    def _consume(self, gen, source):
        """槽端消费一代：**只有当前那一代**才放行，返回它的手动标记（None = 旧代，已丢弃）。

        v2.4.4（A-1）：这里才是"在途"真正结束的地方——所以"结果已 emit、槽还没轮到跑"
        的那一小段窗口里，refresh() 会老老实实排队（不会起第二个并发线程）。旧代的迟到
        结果一律丢弃并**记一条日志**（不许静默）：它既不能再弹气泡/放音/撒钱，也不许
        碰新一代的标记。
        """
        pet = self.pet
        cur = getattr(pet, "_balance_active_gen", None)
        if cur != gen:
            self._log_safe("balance: 丢弃旧代结果 %s（代次 %s 已过期，当前在途 %r）"
                           % (source, gen, cur))
            return None
        manual = bool(getattr(pet, "_manual_pending", False))
        pet._balance_active_gen = None
        pet._manual_pending = False
        return manual

    def _worker(self, key, gen):
        """后台查一次余额并把结果（带**代次** gen）emit 出去（daemon 线程）。**绝不向上抛**。

        v2.4.3（第三轮找茬 P1-1）：此前 emit 裸露在 try 之外——① PetWindow 已销毁时
        emit 打到 deleted 的 C++ 对象上（RuntimeError），daemon 线程静默崩；② 若
        _request_balance 之后的某一行在 try 外抛，守卫标志会**永真**，此后所有轮询与
        手动查询都被"在途"挡住（静默失效：用户点"查询余额"毫无反应）。

        现在：顶层 try/except + 交不出去才收尾——
          · emit 前判 pet._closing（见 _emit），销毁/退出中直接不发；
          · 兜底 except 记日志并补发 balance_err（幂等：槽里已有 _closing 守卫）；
          · 结果**真的交给了槽**时这一代留着（由槽在 on_updated/on_err 里消费）——
            绝不能在这里提前复位，否则就又回到 A-1 的第二个并发线程；
          · 没交出去（退出中 / emit 抛）才 _retire 自己那一代，守卫照样不会挂死。
        """
        handed = False
        try:
            ok, payload = self._request_balance(key)
            if ok:
                total, currency, granted = payload
                handed = self._emit("balance_updated", gen, float(total), currency,
                                    float(granted))
            else:
                self._log_safe("balance_worker: %s" % (payload,))
                handed = self._emit("balance_err", gen)
        except Exception as e:
            # _request_balance 内部已全兜；这里防的是"它之后的行"（含参数解包、标志读写）
            self._log_safe("balance_worker crashed: %r" % (e,))
            handed = self._emit("balance_err", gen)
        if not handed:
            self._retire(gen, "结果没能交给槽")

    def fetch_sync(self):
        """v2.3.0（1.2 Function Calling）：工具 check_balance 的同步只读数据源。

        由 ChatService 的**工作线程**直接调用：只发 HTTP，不碰 Qt，也**不改守卫状态**
        （_balance_gen/_balance_active_gen/_manual_pending 属于轮询与手动查询的状态机，
        工具查询不参与，免得把在途轮询的状态搅乱）。返回 (True, dict) 或 (False, 错误文案)。
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
    def on_updated(self, gen, total, currency, granted):
        """结果落地：先消费**自己那一代**（旧代直接丢，见 _consume），再按手动标记给反馈。

        v2.4.4（A-1）：手动标记从"全局一个 _manual_pending"改成"随代次一起被消费"——
        旧代结果不再借用新一代的标记去弹气泡/放金币音/撒钱（那正是审查看到的双份副作用）。
        """
        pet = self.pet
        if pet._closing:
            # v2.4.4（兼容审查 L1）：早退也要收尾。结果已经 emit 出去了（worker 那边把这一代
            # 留着等槽消费），这里直接 return 会让它**永久挂在非 None**。生产上进程正在退出、
            # 无感；但探针/夹具会把 _closing 改回 False 继续用同一个窗口（_dev/probe_ui_freeze.py、
            # tests/test_full_form_frames_v24.py），之后就撞上"点查询余额毫无反应"。
            self._retire(gen, "退出中丢弃结果")
            return  # P1-5：退出中不再响应在途余额结果
        manual = self._consume(gen, "balance_updated")
        if manual is None:
            return   # 旧代迟到结果：丢弃（_consume 已记日志）
        if pet._pending_manual:
            pet._pending_manual = False
            # v2.3.1（P2-1）：receiver 必须是 QObject——BalanceService 不是，传 self 会
            # TypeError/连接异常；pet（QWidget）才是合法 receiver（同时保证窗口销毁后不再回调）
            QTimer.singleShot(0, self.pet, lambda: self.refresh(manual=True))  # 补发排队的手动查询
        if not self._cfg().get("api_key"):
            return  # Key 已清空，忽略在途请求结果
        pet._currency = currency
        pet._usage = self.update_ledger(total)  # 记账在主线程，避免跨线程读写
        if manual:
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

    def on_err(self, gen):
        """错误落地：同样先消费**自己那一代**；旧代的错误不许再弹提示（见 _consume）。"""
        pet = self.pet
        if pet._closing:
            self._retire(gen, "退出中丢弃错误结果")  # 同上：早退也要收尾（v2.4.4 兼容审查 L1）
            return  # P1-5：退出中不再响应在途余额错误
        manual = self._consume(gen, "balance_err")
        if manual is None:
            return  # 旧代迟到结果：丢弃（_consume 已记日志）
        if pet._pending_manual:
            pet._pending_manual = False
            # v2.3.1（P2-1）：receiver 必须是 QObject——BalanceService 不是，传 self 会
            # TypeError/连接异常；pet（QWidget）才是合法 receiver（同时保证窗口销毁后不再回调）
            QTimer.singleShot(0, self.pet, lambda: self.refresh(manual=True))  # 补发排队的手动查询
        if manual:
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
        """记一笔。v2.3.0（1.2）：工具带上的金额/备注只作对话框**预填**，最终由用户确认。

        v2.8.0 第 6 轮（代理 B · 反馈清账 S20 / P3-3）两处"点了没反应"补上可见提示，
        口径与 open_ledger 一致（日志 + 宠物气泡，**不 import** pet_dialogs 的私有助手）：
          · 对话框构建/弹出失败：此前只写日志 —— 用户点了菜单毫无反应；
          · 金额 <= 0（含清空后确定）：此前静默丢弃 —— 用户以为记上了，账本里却没有。
        """
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
                else:
                    # 确凿的"没记"要说出**没记**（否则用户以为已经记上，账本里却找不到）
                    pet.show_bubble("金额要大于 0 才记得上哦~（这笔没有记）")
        except Exception as e:
            self._log("add_manual_record failed: %r" % (e,))
            try:
                pet.show_bubble("「记一笔」打不开：%s\n（详情见数据目录的 error.log）" % (e,))
            except Exception as e2:
                self._log("add_manual_record notify failed: %r" % (e2,))

    def open_ledger(self):
        """账本对话框入口（菜单「📒 账本…」）。

        v2.7.0（B2）：打不开时不再只写日志——用户点了菜单毫无反应（_dev/audit_feedback_v270.md
        S25 的五处入口之一）。口径同 pet_dialogs._dialog_failed（日志 + 一句中文），但这里
        **不 import 那个私有助手**（领地互斥），按同一口径用宠物气泡 + 日志：气泡 5 秒自动
        隐藏、不抢焦点，比模态框更适合"入口没打开"这种一次性告知。
        """
        try:
            dlg = pet_dialogs.LedgerDialog(self.pet)
            pet_dialogs.modal(dlg)
        except Exception as e:
            self._log("ledger dialog failed: %r" % (e,))
            try:
                self.pet.show_bubble("「账本」打不开：%s\n（详情见数据目录的 error.log）" % (e,))
            except Exception as e2:
                self._log("ledger dialog notify failed: %r" % (e2,))
