# -*- coding: utf-8 -*-
"""
右键菜单构建（v1.3.1 紧凑化，参考小鲸鱼挂件布局）：
大小滑块 + 高频开关平铺，低频项收进「记账」「设置…」子菜单；含动作子菜单 / 设置子菜单全部结构。

独立模块：不 import 桌宠.py。顶层 QMenu 必须经 pet._new_menu() 构造
（v13 通过 stub 桌宠.QMenu 捕获菜单结构，必须走桌宠模块级 QMenu 名字）；
动作 connect 到 pet 及其服务的原方法，菜单项文本 / 层级 / 勾选逻辑原样保留。
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QWidget, QWidgetAction

import pet_dialogs  # 资源管理 / 气泡样式 / 台词 / AI 设置 / 帧数上限对话框入口


class MenuBuilder:
    def __init__(self, pet, save_cfg, autostart_enabled):
        self.pet = pet
        self._save_cfg = save_cfg
        self._autostart_enabled = autostart_enabled

    def open(self, gp):
        pet = self.pet
        menu = pet._new_menu()

        # 顶部信息行：余额 / 今日已用（仅展示，不可点）
        if pet._shown_balance is not None:
            if pet._currency == "CNY":
                info_text = "💰 余额 ¥%.2f · 今日已用 ¥%.2f" % (pet._shown_balance, pet._usage or 0.0)
            else:
                info_text = "💰 余额 %s %.2f · 今日已用 %.2f" % (pet._currency, pet._shown_balance, pet._usage or 0.0)
        else:
            info_text = "📒 今日已用 %.2f" % (pet._usage or 0.0)
        menu.addAction(info_text).setEnabled(False)
        menu.addSeparator()

        # 大小滑块（拖动实时缩放，替代原来的 6 项子菜单）
        menu.addAction(self._make_size_action(menu))

        pet._top_act = menu.addAction("📌 窗口置顶")
        pet._top_act.setCheckable(True)
        pet._top_act.setChecked(pet.cfg.get("always_on_top", True))
        pet._top_act.toggled.connect(pet._set_always_on_top)
        sound_act = menu.addAction("🔊 音效")
        sound_act.setCheckable(True)
        sound_act.setChecked(pet.cfg.get("sound", True))
        sound_act.toggled.connect(pet._set_sound)
        pet._ai_act = menu.addAction("🤖 AI对话")
        pet._ai_act.setCheckable(True)
        pet._ai_act.setChecked(pet.cfg.get("ai_enabled", False))
        pet._ai_act.toggled.connect(pet.ai.set_ai_enabled)
        # P1-手感：甩抛物理开关（默认关闭；开启后拖动变弹簧跟手、松手可甩飞）
        phys_act = menu.addAction("🌀 甩抛物理")
        phys_act.setCheckable(True)
        phys_act.setChecked(bool((pet.cfg.get("physics") or {}).get("enabled")))
        phys_act.toggled.connect(pet._set_physics)
        menu.addSeparator()

        talk_act = menu.addAction("💭 和它说话")
        talk_act.triggered.connect(pet.ai.talk)

        food_menu = menu.addMenu("🍖 喂食")
        for food in ("小鱼干", "蛋糕", "钻石"):
            act = food_menu.addAction(food)
            act.triggered.connect(lambda checked=False, f=food: pet.feed(f))
        food_menu.addSeparator()
        tray_act = food_menu.addAction("🍱 食物托盘")
        tray_act.setCheckable(True)
        tray_act.setChecked(pet.food_tray.isVisible())
        tray_act.toggled.connect(pet._set_food_tray)
        food_menu.addSeparator()
        form_menu = food_menu.addMenu("🐡 形态")
        for key in pet.form_keys:
            name = pet.form_names.get(key, key)
            if key == pet.form:
                name += " ✓"
            act = form_menu.addAction(name)
            # v2.1：菜单选形态 = 用户显式选择（记为 user_selected_form，待机不得覆盖）
            act.triggered.connect(lambda checked=False, k=key: pet.set_user_form(k))

        role_menu = menu.addMenu("🐟 角色")
        role_group = QActionGroup(menu)
        role_group.setExclusive(True)  # 单选互斥：勾选状态不残留
        role_def = role_menu.addAction("默认角色")
        role_def.setCheckable(True)
        role_def.setChecked(not pet.cfg.get("role"))
        role_def.triggered.connect(lambda checked=False: pet.apply_role(""))
        role_group.addAction(role_def)
        for r in pet.role_lib.list_roles():
            act = role_menu.addAction("🖼️ " + str(r.get("name", r.get("id", ""))))
            act.setCheckable(True)
            act.setChecked(pet.cfg.get("role") == r.get("id"))
            act.triggered.connect(lambda checked=False, rid=r.get("id"): pet.apply_role(rid))
            role_group.addAction(act)
        role_menu.addSeparator()
        role_import_act = role_menu.addAction("导入角色…")
        role_import_act.triggered.connect(lambda: pet_dialogs.open_resource_manager(pet, 0))
        # v2.0.3：角色包导出/导入（分享含素材/行为/可分享配置，敏感键默认不导出）
        role_export_act = role_menu.addAction("📦 导出角色包…")
        role_export_act.triggered.connect(lambda checked=False: pet._export_role())
        bundle_import_act = role_menu.addAction("📦 导入角色包…")
        bundle_import_act.triggered.connect(lambda checked=False: pet._import_role_bundle())

        book_menu = menu.addMenu("💰 记账")
        balance_act = book_menu.addAction("查询余额")
        balance_act.triggered.connect(pet.balance.fetch)
        badge_act = book_menu.addAction("📊 余额挂件")
        badge_act.setCheckable(True)
        badge_act.setChecked(pet.cfg.get("badge", False))
        badge_act.toggled.connect(pet._set_badge)
        book_menu.addSeparator()
        ledger_act = book_menu.addAction("📒 账本…")
        ledger_act.triggered.connect(pet.balance.open_ledger)
        manual_act = book_menu.addAction("✏️ 记一笔…")
        manual_act.triggered.connect(pet.balance.add_manual_record)
        book_menu.addSeparator()
        budget_act = book_menu.addAction("💸 今日预算…")
        budget_act.triggered.connect(pet.balance.set_budget)
        bal_alert_act = book_menu.addAction("🚨 余额预警…")
        bal_alert_act.triggered.connect(pet.balance.set_balance_alert)

        res_act = menu.addAction("📦 资源管理…")
        res_act.triggered.connect(lambda: pet_dialogs.open_resource_manager(pet, 0))

        set_menu = menu.addMenu("⚙️ 设置…")
        pet._follow_act = set_menu.addAction("🖱️ 跟随鼠标")
        pet._follow_act.setCheckable(True)
        pet._follow_act.setChecked(pet.cfg.get("follow_mouse", False))
        pet._follow_act.toggled.connect(pet.wander.set_follow)
        pet._wander_act = set_menu.addAction("🚶 散步")
        pet._wander_act.setCheckable(True)
        pet._wander_act.setChecked(pet.cfg.get("wander", False))
        pet._wander_act.toggled.connect(pet.wander.set_wander)
        set_menu.addSeparator()
        bubble_style_act = set_menu.addAction("🎨 气泡样式…")
        bubble_style_act.triggered.connect(lambda: pet_dialogs.open_bubble_style(pet))
        # P3-1：透明区点击穿透（只命中身体，默认关闭保持旧行为）
        ct_act = set_menu.addAction("🖱️ 透明区穿透")
        ct_act.setCheckable(True)
        ct_act.setChecked(pet.cfg.get("click_through", False))
        ct_act.toggled.connect(pet._set_click_through)
        # P3-5+：帧数上限用户可调（导入与加载共用）
        fm_act = set_menu.addAction("🎞️ 帧数上限…")
        # P1-手感：物理参数设置（重力/反弹/摩擦/顶边/力度）
        phys_param_act = set_menu.addAction("🌀 物理参数…")
        phys_param_act.triggered.connect(lambda: pet_dialogs.open_physics(pet))
        # v2.0：语音设置（开关/合成方式/事件片段）
        voice_act = set_menu.addAction("🎤 语音设置…")
        voice_act.triggered.connect(lambda: pet_dialogs.open_voice(pet))
        # v2.0.2：行为设置（待机行为/行为编辑/变身时长）
        beh_act = set_menu.addAction("🧩 行为设置…")
        beh_act.triggered.connect(lambda checked=False: pet._open_behavior_dialog())
        # v2.1.1：手动启动本地配音后端（自动启动默认关，随时可手动来一次）
        vstart_act = set_menu.addAction("🎙 启动配音后端")
        vstart_act.triggered.connect(lambda checked=False: pet._menu_start_voice_backend())
        # v2.1：待机设置（两触发/待机形态/多动作/播放模式）
        idle_act = set_menu.addAction("😴 待机设置…")
        idle_act.triggered.connect(lambda checked=False: pet._open_idle_dialog())
        # v2.0.5：闹钟（到点提醒 + 自定义铃声 + 语音提醒）
        alarm_act = set_menu.addAction("⏰ 闹钟…")
        alarm_act.triggered.connect(lambda checked=False: pet._open_alarm_dialog())
        fm_act.triggered.connect(lambda: pet_dialogs.set_frame_max(pet, self._save_cfg))
        snd_set = set_menu.addMenu("🎵 音效设置")
        grp_group = QActionGroup(menu)
        grp_group.setExclusive(True)  # 单选互斥：勾选状态不残留
        grp_def = snd_set.addAction("默认音效")
        grp_def.setCheckable(True)
        grp_def.setChecked(pet.cfg.get("sound_group") != "custom")
        grp_def.triggered.connect(lambda checked=False: pet._set_sound_group("default"))
        grp_group.addAction(grp_def)
        grp_cus = snd_set.addAction("自定义音效组")
        grp_cus.setCheckable(True)
        grp_cus.setChecked(pet.cfg.get("sound_group") == "custom")
        grp_cus.triggered.connect(lambda checked=False: pet._set_sound_group("custom"))
        grp_group.addAction(grp_cus)
        snd_set.addSeparator()
        snd_manage_act = snd_set.addAction("管理音频片段…")
        snd_manage_act.triggered.connect(lambda: pet_dialogs.open_resource_manager(pet, 1))
        lines_act = set_menu.addAction("💬 自定义台词…")
        lines_act.triggered.connect(lambda: pet_dialogs.open_lines(pet))
        set_menu.addSeparator()
        pet._autostart_act = set_menu.addAction("🚀 开机自启")
        pet._autostart_act.setCheckable(True)
        pet._autostart_act.setChecked(self._autostart_enabled())
        pet._autostart_act.toggled.connect(pet._set_autostart)
        key_act = set_menu.addAction("🔑 设置DeepSeek API Key")
        key_act.triggered.connect(pet.ai.set_api_key)
        clear_key_act = set_menu.addAction("🧹 清除DeepSeek API Key")
        clear_key_act.triggered.connect(pet.ai.clear_api_key)
        set_menu.addSeparator()
        ai_set_act = set_menu.addAction("🤖 AI设置…")  # P1-10：接口/模型/人设/长度
        ai_set_act.triggered.connect(pet.ai.open_ai_settings)
        mem_act = set_menu.addAction("🧠 对话记忆…")  # P1-6：上下文轮数
        mem_act.triggered.connect(pet.ai.set_chat_rounds)
        clear_logs_act = set_menu.addAction("🧹 清理日志…")  # P2-1：日志/记忆卫生
        clear_logs_act.triggered.connect(pet._clear_logs)
        menu.addSeparator()

        # P3-2：右键点播任意动画（与闲逛加权目录共用 play_action）
        act_menu = menu.addMenu("🎭 动作")
        jump_act = act_menu.addAction("原地小跳")
        jump_act.triggered.connect(lambda checked=False: pet.actions.play_action("jump", force=True))
        for _label, _arg in (("打盹 zzz", "zzz"), ("音符", "note"), ("星光", "sparkle"), ("爱心", "heart")):
            a = act_menu.addAction(_label)
            a.triggered.connect(lambda checked=False, k=_arg: pet.actions.play_action("emote", k, force=True))
        # v2.0.1：自定义命名动作（帧动作/程序化合成）动态列出
        _custom = pet.custom_actions()
        if _custom:
            act_menu.addSeparator()
            for _name, _kind in _custom:
                _label = "✦ %s（合成）" % _name if _kind == "proc" else "✦ %s" % _name
                a = act_menu.addAction(_label)
                a.triggered.connect(lambda checked=False, n=_name: pet.actions.play_action(n, force=True))

        # v2.0.2 断点#12：变身（仅自定义角色有变身形态时显示）
        if pet.has_transform_form:
            tf_act = menu.addAction("🐡 变身")
            tf_act.triggered.connect(lambda checked=False: pet._do_transform())

        praise_act = menu.addAction("❤️ 夸夸她")
        praise_act.triggered.connect(lambda checked=False: pet.mood.blush())
        weather_act = menu.addAction("☀️ 今日天气")
        weather_act.triggered.connect(pet.weather.fetch)
        city_act = menu.addAction("📍 天气城市…")
        city_act.triggered.connect(pet._set_city)
        cpu_act = menu.addAction("🖥️ 系统状态")
        cpu_act.triggered.connect(pet.actions.show_system_status)
        about_act = menu.addAction("ℹ️ 关于")
        about_act.triggered.connect(pet._about)
        menu.addSeparator()
        quit_act = menu.addAction("⏹ 退出")
        quit_act.triggered.connect(pet._quit)

        menu.exec(gp)
        pet._top_act = pet._follow_act = pet._wander_act = pet._ai_act = pet._autostart_act = None
        menu.deleteLater()

    def _make_size_action(self, menu):
        """大小滑块（QWidgetAction）：拖动实时缩放，落盘走 400ms 防抖。"""
        pet = self.pet
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(12, 2, 12, 2)
        lbl = QLabel("🎚️ 大小")
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(20, 400)  # 与 set_scale 的 0.2~4.0 夹紧一致（滚轮可到 4x）
        slider.setFixedWidth(130)
        pct = QLabel()
        lay.addWidget(lbl)
        lay.addWidget(slider, 1)
        lay.addWidget(pct)

        def onval(v):
            pct.setText("%d%%" % v)
            pet.set_scale(v / 100.0)
            pet.cfg["scale"] = pet.scale
            pet._schedule_scale_save()

        slider.valueChanged.connect(onval)
        # 先设值再预填文本：scale 恰为滑块当前值时不触发信号，标签也要有初值
        slider.setValue(int(round(pet.scale * 100)))
        pct.setText("%d%%" % slider.value())
        act = QWidgetAction(menu)
        act.setDefaultWidget(w)
        return act
