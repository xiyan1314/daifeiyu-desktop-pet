# -*- coding: utf-8 -*-
"""
AI 对话入口与设置（Key 管理 / 开关 / 人设设置 / 对话记忆轮数）。

独立模块：不 import 桌宠.py；save_config / set_redact_key / _remove_files / 运行时路径
等模块全局以构造参数注入；对话框走本模块的 QInputDialog（与桌宠.QInputDialog 同一类）。
"""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QInputDialog, QLineEdit

import pet_dialogs  # AI 设置对话框（pet_dialogs 不 import 桌宠，无循环）
import pet_chat  # v2.0.4：is_local_base（本地模型免 Key 判断，pet_chat 无环）


class AIService:
    """AI 对话入口与设置：Key / 开关 / 人设 / 记忆轮数。"""

    PRAISE_KEYWORDS = ("夸", "棒", "可爱", "漂亮", "好看", "喜欢", "厉害", "乖", "萌", "聪明")

    def __init__(self, pet, chat_service, cfg_getter, save_cfg, redact_fn, remove_files,
                 paths, book_getter, log, defaults):
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
    def set_ai_enabled(self, on):
        cfg = self._cfg()
        cfg["ai_enabled"] = bool(on)
        self._save_cfg(cfg)
        if on and not cfg.get("api_key"):
            self.set_api_key()
            if not self._cfg().get("api_key"):
                cfg["ai_enabled"] = False
                self._save_cfg(cfg)
                if self.pet._ai_act:
                    self.pet._ai_act.setChecked(False)  # 同步菜单勾选状态，避免残留
                self.pet.show_bubble("要先填 DeepSeek API Key 才能开 AI 对话哦~")

    def set_api_key(self):
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
            if key:
                self._cfg()["api_key"] = key
                self._save_cfg(self._cfg())
                self._redact(key)
                pet.show_bubble("记住啦！可以和我聊天了~")

    def clear_api_key(self):
        pet = self.pet
        cfg = self._cfg()
        usage_path, data_dir, config_path, memory_path = self._paths
        cfg["api_key"] = ""
        self._redact("")
        cfg["badge"] = False
        cfg["ai_enabled"] = False
        self._save_cfg(cfg)
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
        self._remove_files((usage_path, os.path.join(data_dir, "error.log"),
                            config_path + ".tmp", usage_path + ".tmp"))  # P1-6：清 Key 连带清对话记忆
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
    def talk(self):
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
            cfg["ai_enabled"] = True
            if pet._ai_act:
                pet._ai_act.setChecked(True)
            self._save_cfg(cfg)
        # v2.0.4：本地服务（Ollama 等）无需 Key；云服务商才要求先填 Key
        if not cfg.get("api_key") and not pet_chat.is_local_base(cfg.get("ai_base_url", "")):
            self.set_api_key()
            if not self._cfg().get("api_key"):
                return  # 没填 Key：放弃本次对话
            # 刚填好 Key：继续用刚才输入的话发起对话，不用重新再打一遍
        self.chat.ask(msg)

    # ---- AI 设置 / 对话记忆 ----
    def apply_settings(self, data=None):
        """应用 AI 设置（对话框保存后回调；data 为 {配置键: 值}）。"""
        if not isinstance(data, dict):
            return
        cfg = self._cfg()
        for k, v in data.items():
            if k in self._defaults:
                cfg[k] = v
        self._save_cfg(cfg)
        self.pet.show_bubble("AI 设置已更新，下次聊天就按新口味来~")

    def set_chat_rounds(self):
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
        self._cfg()["chat_memory_rounds"] = val
        self._save_cfg(self._cfg())
        if val:
            pet.show_bubble("记住最近 %d 轮对话啦~" % val)
        else:
            pet.show_bubble("不带记忆啦，每次都是全新的鱼~")

    def open_ai_settings(self):
        pet_dialogs.open_ai_settings(self.pet)
