# -*- coding: utf-8 -*-
"""
AI 对话入口与设置（Key 管理 / 开关 / 人设设置 / 对话记忆轮数）。

独立模块：不 import 桌宠.py；save_config / set_redact_key / _remove_files / 运行时路径
等模块全局以构造参数注入；对话框走本模块的 QInputDialog（与桌宠.QInputDialog 同一类）。

v2.5.0（A1/A2）：服务构造搬进 pet_services.ServiceRegistry；本模块（该子系统）补全类型注解。
"""
import os
from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QInputDialog, QLineEdit

import pet_dialogs  # AI 设置对话框（pet_dialogs 不 import 桌宠，无循环）
import pet_chat  # v2.0.4：is_local_base（本地模型免 Key 判断，pet_chat 无环）


class AIService:
    """AI 对话入口与设置：Key / 开关 / 人设 / 记忆轮数。"""

    PRAISE_KEYWORDS = ("夸", "棒", "可爱", "漂亮", "好看", "喜欢", "厉害", "乖", "萌", "聪明")

    def __init__(self, pet: Any, chat_service: Any, cfg_getter: Callable[[], dict],
                 save_cfg: Callable[[dict], None], redact_fn: Callable[[str], None],
                 remove_files: Callable[..., None], paths: tuple[str, ...],
                 book_getter: Callable[[], Any], log: Callable[[str], None],
                 defaults: dict) -> None:
        self.pet = pet
        self.chat = chat_service
        self._cfg = cfg_getter
        self._save_cfg = save_cfg
        self._redact = redact_fn
        self._remove_files = remove_files
        self._paths = paths  # (USAGE_PATH, DATA_DIR, CONFIG_PATH, MEMORY_PATH)
        self._book = book_getter
        self._log = log
        self._defaults = defaults

    # ---- AI 对话开关 ----
    def set_ai_enabled(self, on: Any) -> None:
        cfg = self._cfg()
        # v2.8.0 第 6 轮（代理 B · 先写盘再改内存）：改前是"先原地改 cfg、再 save"——写失败后
        # 用户看到"没能保存"，**本次会话的开关状态却已经变了**（重启才回旧值），被同时骗两次。
        # 现在与 apply_settings 同一口径：先改副本 → 写盘 → 成功才 cfg.update（见 B3 用例）。
        new = dict(cfg)
        new["ai_enabled"] = bool(on)
        err = self._save_cfg(new)
        if err:
            # v2.7.0 第 5 轮（B · 闭环）：开关写盘失败时只说"开关没生效"，不再让勾选状态
            # 假装已经持久化（重启就变回去 = 用户以为设置丢了）
            # v2.8.0：失败还要**留痕**（内存不变 + 日志 + 如实气泡，不复用成功话术）。
            self._log("ai set_ai_enabled save failed: %s" % (err,))
            self.pet.show_bubble("AI 开关没能保存：%s\n（详情见数据目录的 error.log）" % (err,))
            return
        cfg.update(new)          # 写盘成功才提交进内存（内容与键顺序与"原地改"逐位相同）
        if on and not cfg.get("api_key"):
            self.set_api_key()
            if not self._cfg().get("api_key"):
                new2 = dict(cfg)                 # 第二次落盘同样先写副本
                new2["ai_enabled"] = False
                # v2.7.0 第 5 轮（兼容审查 P3-2）：第二次落盘的返回值此前**丢弃**——
                # "没 Key 就把开关退回关"这一步没写进去时，勾选状态与磁盘不一致（重启后
                # 又是开的）。现在按同一口径判，失败就一并说出来（成功路径文案逐字不变）。
                _err2 = self._save_cfg(new2)
                _bad2 = _err2 is False or (isinstance(_err2, str) and _err2.strip())
                if not _bad2:
                    cfg.update(new2)     # v2.8.0：这次写盘成功才提交（失败时内存保持第一次提交后的状态）
                else:
                    self._log("ai set_ai_enabled rollback save failed: %s"
                              % (_err2 if isinstance(_err2, str) and _err2.strip()
                                 else "save callback returned False"))
                if self.pet._ai_act:
                    # v2.8.0 第 6 轮（裁决 ③ · A 临时跨入 B 的领地改这一处）：**界面 = cfg**。
                    # 改前硬写 False：第二次写盘（把开关退回关）失败时内存仍是已提交的 True，
                    # 菜单勾选却已经打回未选中 —— 同一件事两个真相。回读 cfg 的实际值即可。
                    self.pet._ai_act.setChecked(bool(self._cfg().get("ai_enabled")))
                if _bad2:
                    self.pet.show_bubble("要先填 DeepSeek API Key 才能开 AI 对话哦~\n"
                                         "（另外：AI 开关也没能保存：%s）" % (_err2,))
                else:
                    self.pet.show_bubble("要先填 DeepSeek API Key 才能开 AI 对话哦~")

    def set_api_key(self) -> None:
        # 挂到桌宠窗口（置顶窗口的子对话框必然显示在最上层）：
        # 桌宠本身 WindowDoesNotAcceptFocus + 无父对话框会被 Windows 前台锁拦下（只响一声）
        pet = self.pet
        dlg = QInputDialog(pet)
        dlg.setWindowTitle("设置DeepSeek API Key")
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        if self._cfg().get("api_key"):
            dlg.setLabelText("已配置 Key（加密保存）。输入新值可覆盖；清空请用菜单「清除DeepSeek API Key」：")
        else:
            dlg.setLabelText("请输入 DeepSeek API Key（sk-开头）：")
        dlg.setTextEchoMode(QLineEdit.EchoMode.Password)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        dlg.setFocus()  # 前台锁残余风险：显式请求键盘焦点
        if dlg.exec() == QDialog.DialogCode.Accepted:
            key = dlg.textValue().strip()
            if not key:
                # v2.7.0 第 5 轮（代理 B · 审计 S17）：改前这里**什么都不做、也不说一句话**
                # ——用户清空输入框点确定 = 完全静默（"点了没效果"，error.log 里也查不到）。
                # 只补一句反馈，**绝不动已有 Key**（清空有专门的菜单项，标签里也写明了），
                # 所以这条改动不存在"手滑把 Key 清掉"的数据风险。
                pet.show_bubble("没有输入 Key，什么都没改~（要清空请用菜单「清除DeepSeek API Key」）")
                return
            # v2.8.0 第 6 轮（代理 B · 先写盘再改内存）：改前先改内存再写盘——写失败时内存里
            # 已经是新 Key（本次会话照用新值），用户却读到"没能保存"。现在与 apply_settings 同口径。
            cfg = self._cfg()
            new = dict(cfg)
            new["api_key"] = key
            err = self._save_cfg(new)
            # 用户已经把这个值打进过输入框（也可能已经进了日志之外的任何地方）→ 不论落盘成败
            # 都要登记脱敏：失败时内存里虽然没提交，但脱敏登记不会因此变多此一举。
            self._redact(key)
            if err:
                # v2.7.0 第 5 轮（B · 闭环）：写失败不许再回「记住啦！」——那是"保存成功"假象
                # v2.8.0：内存不变 + 留痕 + 如实说（不复用成功话术）。
                self._log("ai set_api_key save failed: %s" % (err,))
                pet.show_bubble("Key 没能保存：%s\n（详情见数据目录的 error.log）" % (err,))
                return
            cfg.update(new)     # 写盘成功才提交进内存（内容与键顺序与"原地改"逐位相同）
            pet.show_bubble("记住啦！可以和我聊天了~")

    def clear_api_key(self) -> None:
        pet = self.pet
        cfg = self._cfg()
        usage_path, data_dir, config_path, memory_path = self._paths
        # v2.7.0 第 5 轮（兼容审查 P2-1）：**先在副本上改，写盘成功才提交**。
        # 改前无论写盘成败都往下走：内存里 Key / 开关已清、盘上一个字节没写（重启后 Key
        # 又回来），而余额基准、对话记忆、日志**已经真删了**，用户看到的却是"已清空"
        # —— 既是假反馈，删掉的记忆还找不回来。现在失败就**什么都不清**、如实说明。
        new = dict(cfg)
        new["api_key"] = ""
        new["badge"] = False
        new["ai_enabled"] = False
        err = self._save_cfg(new)
        if err is False or (isinstance(err, str) and err.strip()):
            self._log("clear_api_key save failed: %s"
                      % (err if isinstance(err, str) and err.strip()
                         else "save callback returned False"))
            pet.show_bubble("API Key 没能清空：%s\n（盘上还是旧值；余额基准 / 对话记忆 / 日志"
                            "这次一个都没动，详情见数据目录的 error.log）"
                            % (err if isinstance(err, str) and err.strip()
                               else "落盘回调报了失败"))
            return
        cfg.update(new)
        self._redact("")   # 只有真清掉了才注销脱敏：失败时 Key 还在内存里，必须继续脱敏
        pet.balance.stop()
        pet.badge.hide()
        pet._shown_balance = None
        pet._usage = 0.0
        pet._manual_pending = False
        with pet._history_lock:
            pet._chat_history.clear()  # 聊天记忆一并清空（与 ChatService 追加互斥）
            pet._mem_epoch += 1  # 代次 +1：在途 AI 回复检测到后不再把本次对话写回记忆
        book = self._book()
        if book is not None:
            book.reset_balance_baseline()  # 只清余额基准，手动记账保留
        pet._usage = book.today_usage() if book is not None else 0.0
        # P1-6：清 Key 连带清对话记忆。v2.4（M2）：error.log.bad（pet_log._quarantine
        # 隔离出的坏/满日志）此前不在名单里 → 里面可能留着脱敏前的现场，清 Key 清不掉。
        self._remove_files((usage_path, os.path.join(data_dir, "error.log"),
                            os.path.join(data_dir, "error.log.bad")))
        # L4：临时名现在带线程号（"<p>.<tid>.tmp"），只删固定名扫不到真正会残留的文件。
        # clean_tmp_files 对每个目标取同一把路径锁 → 不会删掉在途写者正在用的 tmp。
        try:
            import pet_io as _io
            _io.clean_tmp_files((config_path, usage_path, memory_path), self._log)
        except Exception as _e:
            if self._log is not None:
                self._log("clear key tmp sweep: %r" % (_e,))
        # v2.3.0（找茬 S1）：这里以前把 memory.json 整个删掉。1.1 之后该文件还存着长期记忆
        # （称呼/别名/喜好/不喜欢/近况），整删 = 清一次 Key 就把"它记得你"一起抹掉。
        # 现在只清 history，long_term 保留。
        try:
            import pet_chat as _pc
            _pc.write_memory(memory_path, [], 6, log=self._log)
        except Exception as _e:
            if self._log is not None:
                self._log("clear memory on key clear: %r" % (_e,))
        pet.show_bubble("API Key 已清空，余额基准和日志擦干净啦（手动记账保留；"
                        "它还记得你的称呼和喜好，可在「AI 设置」里清除长期记忆）~")

    # ---- 和它说话 ----
    def talk(self) -> None:
        pet = self.pet
        if self.chat.inflight():
            pet.show_bubble("还在想呢，等一下下~")
            return
        dlg = QInputDialog(pet)  # 挂到桌宠窗口，确保对话框正常显示（见 set_api_key 注释）
        dlg.setWindowTitle("和它说话")
        dlg.setLabelText("你想对大肥鱼说什么？")
        dlg.setTextValue("")
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        dlg.setFocus()  # 前台锁残余风险：显式请求键盘焦点
        ok = dlg.exec() == QDialog.DialogCode.Accepted
        msg = dlg.textValue().strip()
        if not (ok and msg):
            return
        # 夸夸检测：本地触发害羞脸红，无需 API Key；先排除否定语境（"不好看"等）
        neg_words = ("不", "别", "没", "讨厌", "难看", "丑", "烦")
        if any(k in msg for k in self.PRAISE_KEYWORDS) and not any(n in msg for n in neg_words):
            pet.mood.blush()
        cfg = self._cfg()
        if not cfg.get("ai_enabled"):
            # v2.8.0 第 6 轮（代理 B · 同族第 4 处）：改前是"先改内存、再 save"**且丢弃返回值**
            # —— 写失败时内存 True、菜单已勾选、盘上没有这个键、零气泡零日志，而对话照常发起；
            # 重启又变回关（用户以为设置丢了，且没有任何线索）。现在与 set_api_key /
            # set_ai_enabled / set_chat_rounds 同一口径：先写盘、成功才提交。
            new = dict(cfg)
            new["ai_enabled"] = True
            err = self._save_cfg(new)
            if err:
                # 如实说、**不复用成功话术**；对话**照常发起**（用户目的是说话，不是改开关——
                # 落盘失败只影响"下次启动要不要重新打开"，不该把这次对话掐掉）。
                self._log("ai talk auto-enable save failed: %s" % (err,))
                pet.show_bubble("AI 开关没能保存：%s\n（这次对话照常；重启后开关会回到关闭，"
                                "详情见数据目录的 error.log）" % (err,))
            else:
                cfg.update(new)      # 写盘成功才提交进内存
            if pet._ai_act:
                # 界面 = cfg（与 set_ai_enabled 的裁决同口径）：勾选回读 cfg 的**实际值**。
                # **必须屏蔽信号**：不屏蔽的话 setChecked 会 emit toggled → set_ai_enabled 再写一次
                # 盘；没填 Key 时那条路还会再弹一次 API Key 输入框（实测：一次"和它说话"变成
                # 两次落盘 / 两次询问）。这里我们已经自己写过了，不需要它再代劳。
                _was = pet._ai_act.blockSignals(True)
                try:
                    pet._ai_act.setChecked(bool(self._cfg().get("ai_enabled")))
                finally:
                    pet._ai_act.blockSignals(_was)
        # v2.0.4：本地服务（Ollama 等）无需 Key；云服务商才要求先填 Key
        if not cfg.get("api_key") and not pet_chat.is_local_base(cfg.get("ai_base_url", "")):
            self.set_api_key()
            if not self._cfg().get("api_key"):
                return  # 没填 Key：放弃本次对话
            # 刚填好 Key：继续用刚才输入的话发起对话，不用重新再打一遍
        self.chat.ask(msg)

    # ---- AI 设置 / 对话记忆 ----
    def apply_settings(self, data: Any = None) -> tuple[bool, str]:
        """应用 AI 设置（对话框保存后回调；data 为 {配置键: 值}）→ **(ok, msg)**。

        v2.7.0 第 5 轮（代理 B，闭环 P1-1）：本方法此前返回 None（成功也 None）**且自己弹气泡**
        —— 调用方（桌宠.apply_ai_settings → AI 设置对话框）无从判断成败，"窗口照常关闭 =
        保存成功假象"的根源就在这里（_dev/audit_feedback_v270.md S10/P1-1）。现在：
          · 成功 → (True, "AI 设置已更新，下次聊天就按新口味来~")；
          · 失败 → (False, 可读原因) **+ 记一条日志**（入参不是 dict / 落盘回调抛异常 /
            落盘回调返回错误串或 False，三种都算失败）；
          · **不再自己弹气泡**：一次用户动作只给一句反馈，气泡由调用方给
            （桌宠.apply_ai_settings 把 msg 原样交回对话框，对话框按 msg 弹气泡）。
            否则同一次「保存」会出现两条同文案气泡。
        """
        if not isinstance(data, dict):
            return False, "AI 设置格式不对，没有保存"
        try:
            cfg = self._cfg()
            # v2.7.0 第 5 轮（F4：写盘失败时内存里的 cfg 已经被改）。改前是"先原地改 cfg、
            # 再 save"：写失败后用户看到的是"没能保存"，**本次会话却已经在用新的 API 地址/
            # 模型/人设**，重启才回旧值 —— 用户被同时骗了两次（一次说没保存、一次说没生效）。
            # 取**方案②（先改副本、成功后再提交）**而不是①（只改文案），理由三条：
            #   1) 交付物要求"同一件事只能有一个真相"：口径既然是"没保存"，内存就不该变；
            #   2) 这个函数的入口只有 AI 设置对话框（modal，失败不关窗、值还在控件里），
            #      不提交**不会**让用户丢输入，重试一次即可；
            #   3) 提交是 `cfg.update(new)`，对成功路径**逐位等价**（同一批键、同一批值、
            #      键顺序也相同：既有键 update 不挪位置、新键与原地写一样追加在末尾），
            #      落盘字节由 write_config 从 dict 内容算出 → 与改前完全一致（有用例钉住）。
            new = dict(cfg)
            for k, v in data.items():
                if k in self._defaults:
                    new[k] = v
            err = self._save_cfg(new)
        except Exception as e:
            self._log("ai apply_settings failed: %r" % (e,))
            return False, "AI 设置没能保存：%s" % (e,)
        # 落盘回调的失败信号：错误串（pet_io/pet_config 的口径）或裸 False。
        # v2.7.0 第 5 轮（F3 更正：原注释写于本轮前半，已经过期）：现网注入的正是
        # 桌宠.save_config，而它自本轮起**原样上交** pet_config.write_config 的返回值
        # （桌宠.py `return pet_config.write_config(...)`；pet_config.py 失败时 `return err`、
        # 成功 None），只读兼容模式另有一句原因串。链条已经通了 —— 上面这条判据在现网
        # 链路里是**真起作用**的，不是防御性代码。
        if err is False or (isinstance(err, str) and err.strip()):
            self._log("ai apply_settings save failed: %s"
                      % (err if isinstance(err, str) and err.strip() else "save callback returned False"))
            return False, "AI 设置没能保存：%s" % (
                err if isinstance(err, str) and err.strip() else "落盘回调报了失败（详情见 error.log）")
        cfg.update(new)      # F4：落盘成功才提交进内存（内容与键顺序与"原地改"逐位相同）
        return True, "AI 设置已更新，下次聊天就按新口味来~"

    def set_chat_rounds(self) -> None:
        pet = self.pet
        dlg = QInputDialog(pet)
        dlg.setWindowTitle("对话记忆")
        dlg.setLabelText("聊天时带最近几轮上下文？（0 = 不带记忆，1~10）")
        dlg.setInputMode(QInputDialog.InputMode.IntInput)
        dlg.setIntRange(0, 10)
        dlg.setIntValue(int(self._cfg().get("chat_memory_rounds", 3) or 3))
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        dlg.setFocus()
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        val = dlg.intValue()
        cfg = self._cfg()
        # v2.8.0 第 6 轮（代理 B · 先写盘再改内存）：与 set_api_key / set_ai_enabled / apply_settings
        # 同一口径——写失败时内存里的轮数一个数都不变（也不许回成功话术）。
        new = dict(cfg)
        new["chat_memory_rounds"] = val
        err = self._save_cfg(new)
        if err:
            # v2.7.0 第 5 轮（B · 闭环）：写失败就不许回「记住最近 N 轮啦~」（假象）
            # v2.8.0：再补一条日志（此前只有气泡，error.log 里查不到这次失败）。
            self._log("ai set_chat_rounds save failed: %s" % (err,))
            pet.show_bubble("对话记忆没能保存：%s\n（详情见数据目录的 error.log）" % (err,))
            return
        cfg.update(new)         # 写盘成功才提交进内存
        if val:
            pet.show_bubble("记住最近 %d 轮对话啦~" % val)
        else:
            pet.show_bubble("不带记忆啦，每次都是全新的鱼~")

    def open_ai_settings(self) -> None:
        pet_dialogs.open_ai_settings(self.pet)
