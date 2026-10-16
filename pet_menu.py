# -*- coding: utf-8 -*-
"""
右键菜单构建（v1.3.1 紧凑化，参考小鲸鱼挂件布局）：
大小滑块 + 高频开关平铺，低频项收进「记账」「设置…」子菜单；含动作子菜单 / 设置子菜单全部结构。

独立模块：不 import 桌宠.py。顶层 QMenu 必须经 pet._new_menu() 构造
（v13 通过 stub 桌宠.QMenu 捕获菜单结构，必须走桌宠模块级 QMenu 名字）；
动作 connect 到 pet 及其服务的原方法，菜单项文本 / 层级 / 勾选逻辑原样保留。

v2.5.0（A1/A2）：服务构造搬进 pet_services.ServiceRegistry；本模块（该子系统）补全类型注解。
"""
from typing import Any, Callable

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMenu, QSlider, QWidget,
                               QWidgetAction)

import pet_config  # v2.10.0（C-13）：三态词表（auto/on/off）的单一来源，本模块不抄字符串
import pet_dialogs  # 资源管理 / 气泡样式 / 台词 / AI 设置 / 帧数上限对话框入口


class MenuBuilder:
    def __init__(self, pet: Any, save_cfg: Callable[[dict], None],
                 autostart_enabled: Callable[[], bool]) -> None:
        self.pet = pet
        self._save_cfg = save_cfg
        self._autostart_enabled = autostart_enabled

    def open(self, gp: QPoint) -> None:
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
        # v2.10.0（D3）**去重**：此处原有「导入角色…」，它和顶层「📦 资源管理…」是**同一个调用**
        # （pet_dialogs.open_resource_manager(pet, 0)，同一个页签），而文案承诺"导入"却只打开面板
        # —— 两个入口一个目的地，用户不知道哪个是正门。删掉子菜单里这条，保留顶层那条
        # （顶层还顶着 <=18 项的硬断言，少一条不加一条）。真要导入角色：资源管理 → 角色 →
        # 「导入角色…」；要分享包：下面两条「导出/导入角色包…」是**另一件事**，不受影响。
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
        # v2.11.0 第 9 轮（A2/A3 · 代理 B 接线）：两个无障碍开关。托盘菜单里也有一份
        # （由桌宠负责，桌面类的活），但「设置…」是用户找设置的第一落点，两边文案与语义
        # **逐字一致**（原则 4：同语义同表现）。
        # · 勾选状态一律读**生效值**（auto 时跟随系统设置），不是读配置里的字符串——
        #   否则 auto 且系统开着时，菜单会显示成未勾选（界面在说谎）；
        # · 菜单每次 open 重建，所以天然读的就是"此刻的值"，不需要额外的同步信号；
        # · 立即生效（不重启）由 _set_reduce_motion / _set_high_contrast 内部负责，
        #   它们自己会弹一条回执气泡——这里不再重复回执。
        # v2.10.0（C-13）：**三态**——此前只有一个勾选框，点过一次就写死 on/off，
        # 用户**再也回不到 auto**（只能手改 config.json）。现在每个开关两条：
        #   ① 开关本身：勾选＝**生效值**（auto 时跟随系统），点它＝显式 on/off；
        #   ②「🔁 跟随系统（…）」：勾选＝配置值就是 auto（pet_config.is_auto_motion_mode），
        #      点它＝写回 auto。
        # 三态的词表**只有** pet_config.MOTION_MODES 那一份（auto/on/off），这里不另造字符串；
        # 落盘与立即生效由 _set_reduce_motion / _set_high_contrast 负责（它们收三态字符串，
        # 并各自弹一条回执气泡——这里不再重复回执）。
        # ⚠ 文案与托盘菜单那份（桌宠.py 的 __init__）**逐字一致**——同语义同表现，
        # 改了这里就要同步改那里。
        rm_act = set_menu.addAction("🌊 减少动效")
        rm_act.setCheckable(True)
        rm_act.setChecked(pet._reduce_motion())
        rm_act.toggled.connect(pet._set_reduce_motion)
        rm_auto_act = set_menu.addAction("🔁 跟随系统（减少动效）")
        rm_auto_act.setCheckable(True)
        rm_auto_act.setChecked(pet_config.is_auto_motion_mode(pet.cfg.get("reduce_motion")))
        rm_auto_act.triggered.connect(
            lambda checked=False: pet._set_reduce_motion("auto"))   # 词表见 pet_config.MOTION_MODES
        hc_act = set_menu.addAction("🔲 高对比度")
        hc_act.setCheckable(True)
        hc_act.setChecked(pet._high_contrast())
        hc_act.toggled.connect(pet._set_high_contrast)
        hc_auto_act = set_menu.addAction("🔁 跟随系统（高对比度）")
        hc_auto_act.setCheckable(True)
        hc_auto_act.setChecked(pet_config.is_auto_motion_mode(pet.cfg.get("high_contrast")))
        hc_auto_act.triggered.connect(
            lambda checked=False: pet._set_high_contrast("auto"))   # 词表见 pet_config.MOTION_MODES
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
        # v2.10.0（D4）**命名统一**：全仓把音效库的片段一律叫「音效片段」（与「🎵 音效设置」
        # 这个子菜单、与资源管理里那页签「音效」同一套词），"音频片段"这个名字**退役**——
        # 它和另一条「管理声音素材…」（语音设置里，去的是**另一个库**的页签）长得像同义词，
        # 用户分不出哪个是哪个。⚠ 另一处（pet_dialogs.py 的「管理声音素材…」）不归本包。
        snd_manage_act = snd_set.addAction("管理音效片段…")
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
        set_menu.addSeparator()
        # v2.5.1：PetHub 插件管理（**必须留在设置子菜单里**：顶层菜单有 ≤18 项的硬断言）
        plugin_act = set_menu.addAction("🧩 插件管理…")
        plugin_act.triggered.connect(lambda checked=False: pet_dialogs.open_plugins(pet))
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

    def _make_size_action(self, menu: QMenu) -> QWidgetAction:
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

        def onval(v: int) -> None:
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
