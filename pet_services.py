# -*- coding: utf-8 -*-
"""子系统构造注册表（v2.5.0 第 2 轮 A1）：PetWindow 的服务构造集中到这里。

为什么要有这个模块
------------------
v2.4.4 的 PetWindow.__init__ 实测 472 行、212 个方法，其中十几个服务在构造里**字面 new**，
9 个直接把 self（整个 PetWindow）当第一个参数。服务的构造参数散在四百多行里——改一个
子系统要在一屏开外找它的产地，换一个参数顺序要靠肉眼比对。本模块把那批构造语句整体搬
出来，__init__ 只留调用点。

口径一：行为逐位不变（硬约束）
------------------------------
· 本模块**只搬运**：每条构造语句的**先后顺序、实参、关键字实参**与 v2.4.4 的
  PetWindow.__init__ 逐位相同（同一批对象、同一批 lambda、同样的 try/except 兜底）。
· 异常语义同样不变：book 那条 try/except 原样保留（构造失败 → 记一行日志 + book=None，
  不阻断启动），其余构造照旧直接向上抛。
· 属性名一个不改：构完仍是 pet.role_lib / pet.chat / pet.anim …（外部与护栏都按原名访问）。
· 夹在服务构造之间的几行 PetWindow 状态初始化（_usage / _preview_player / lines_pools）
  也一并搬进来——它们的位置本身就是"逐位不变"的一部分，留在 __init__ 里反而要靠
  "反正没人读"这种论证，不如原样待着。

口径二：不 import 桌宠.py
-------------------------
桌宠.py 要 import 本模块，反向 import 会成环。模块级依赖（路径常量 / 跨线程信号 / 日志 /
配置读写 / 纯函数回调）由 桌宠.py 在构造点**按值注入**——与 pet_wander / pet_chat /
pet_balance 等既有子系统"配置/回调/信号全部构造注入"同一条口径。

调用点（顺序即构造顺序，不可调换）
----------------------------------
    pet.services = pet_services.ServiceRegistry(pet, **_service_deps())  # 核心组（原 L785~L831）
    …                                                                   # 场景/控件/精灵（非服务）
    pet.services.build_anim()                                           # 原 __init__ L965
    …                                                                   # 精灵/状态图/定时器（非服务）
    pet.services.build_mood()                                           # 原 __init__ L1025

后面两段之所以不能并进上面那一次调用：FrameAnim 要吃"已经建好的 self"（精灵/形态都在它
之前），Mood 要吃 self._mood_line，而它们的构造点被场景 / 托盘 / 精灵 / 状态图的代码夹在
中间——提前构造就是**改构造顺序**，那是被上面的硬约束禁止的。所以注册表按原位置分三段
调用，构造逻辑全在本模块。

模块名为什么带 pet_ 前缀：_check_static 与 _verify_v13 都**动态扫** pet_*.py，前缀即自动
进两条护栏（本模块里每个"pet 点名字 左括号"形状的调用都必须真实存在于 PetWindow，否则
v13 直接红）。注意那两个扫描器是**纯文本正则**、不看注释与字符串：本文件里不要写字面的
反例形状（第一次就踩了——docstring 里抄了一句含反例形状的说明，两条护栏同时红）。

本轮**没有**搬的三处（下一轮做 God Object 时不用重新考古）
----------------------------------------------------------
1/2. `pet_fx.AnimatedEmote(pet.fx_item)` 与 `pet_fx.AnimatedEmote(pet.fx_money_item)`
     （原 __init__ L910 / L916，两处）——它们绑的是场景里两个 QGraphicsPixmapItem，而那
     两个 item 的构造位置被**渲染层序**钉住：emote 要 setZValue(2) 提到最上层、撒钱
     setZValue(1) 要压在 petpet 之上，且都要紧跟 scene.addItem 之后。搬进注册表就得把
     scene / view / item / emote_item 一起提前，那是改构造顺序（硬约束禁止）。它们也不
     构造"服务"，是挂 pixmap 的视图层对象，本轮按原样留在 __init__。
3.   `pet_audio.init(...)` + `pet._apply_sound_group()`（原 __init__ L1043~L1044）——
     一次性初始化加一次配置应用，不产出服务对象，也没有构造注入面；保持原位置。
"""

from typing import Callable

import pet_actions
import pet_ai
import pet_alarm
import pet_anim
import pet_balance
import pet_behaviors
import pet_book
import pet_chat
import pet_lines
import pet_menu
import pet_mood
import pet_resources
import pet_tools
import pet_voice
import pet_wander
import pet_weather


class ServiceRegistry:
    """PetWindow 的子系统构造集中地（单一产地）。

    生命周期：PetWindow.__init__ 里构造一次；三段 build_* 按 __init__ 的原位置调用。
    构造完的对象一律**挂回 pet 的同名属性**（pet.role_lib / pet.chat / …），本类不另存副本。
    """

    def __init__(self, pet: object, *, data_dir: str, config_path: str, usage_path: str,
                 memory_path: str, defaults: dict, log: Callable[[str], None],
                 signals: object, save_cfg: Callable[[dict], None],
                 set_redact_key: Callable[[str], None],
                 remove_files: Callable[..., None], play_sound: Callable[[str], None],
                 parse_emote: Callable[..., object], load_memory: Callable[[], object],
                 save_memory: Callable[..., object], ai_prompt: Callable[[dict], str],
                 idle_picker: Callable[..., object],
                 autostart_enabled: Callable[[], bool], max_reply_len: int,
                 sleep_after: float) -> None:
        """登记依赖并按原顺序构造核心组（原 __init__ L785~L831）。

        pet —— 正在构造的 PetWindow。本模块只按鸭子类型用它（cfg / book / _usage /
        _screen_geo / _build_ai_context / _play_voice_clip / _refresh_lines…）。
        其余参数都是搬迁前 __init__ **按值**交给各服务构造的同一个对象（见模块 docstring
        口径二）；名字与 桌宠.py 里的原全局名一一对应，不做二次包装。
        """
        self.pet = pet
        self._data_dir = data_dir
        self._config_path = config_path
        self._usage_path = usage_path
        self._memory_path = memory_path
        self._defaults = defaults
        self._log = log
        self._signals = signals
        self._save_cfg = save_cfg
        self._set_redact_key = set_redact_key
        self._remove_files = remove_files
        self._play_sound = play_sound
        self._parse_emote = parse_emote
        self._load_memory = load_memory
        self._save_memory = save_memory
        self._ai_prompt = ai_prompt
        self._idle_picker = idle_picker
        self._autostart_enabled = autostart_enabled
        self._max_reply_len = max_reply_len
        self._sleep_after = sleep_after
        self._build_libraries()
        self._build_services()

    # ---------------- 第一段：库与账本（原 __init__ L785~L803） ----------------

    def _build_libraries(self) -> None:
        """角色库 / 音频库 / 账本 / 台词库 / 声音素材库 + 它们的接线。

        位置口径：_usage / _preview_player / lines_pools 三行**夹在服务构造之间**，
        原样留在此处（见模块 docstring"口径一"最后一条）。
        """
        pet = self.pet
        data_dir = self._data_dir
        log = self._log
        signals = self._signals

        pet.role_lib = pet_resources.RoleLibrary(data_dir)
        pet.audio_lib = pet_resources.AudioLibrary(data_dir)
        pet.role_lib.set_active(pet.cfg.get("role", ""))  # roles.json 与 config 同步
        try:
            pet.book = pet_book.Book(data_dir)
        except Exception as e:
            log("book init failed: %r" % (e,))
            pet.book = None
        pet._usage = pet.book.today_usage() if pet.book is not None else 0.0
        pet._preview_player = None  # mp3 试听兜底播放器（惰性构建）
        # ---- v2.1：台词库（独立台词自定义模块）+ 声音素材库（资源库内，与音效分开） ----
        pet.lines_lib = pet_lines.LineService(data_dir, log)
        pet.voice_assets = pet_resources.VoiceAssetLibrary(data_dir)
        pet._migrate_lines_extra()  # v2.0 的 cfg["lines_extra"] → v2.1 台词库（一次性）
        pet.lines_lib.on_changed(signals.lines_changed.emit)  # 跨线程安全：只 emit，不碰控件
        pet.role_lib.on_deleted(lambda rid: signals.voice_refs_changed.emit(-1))
        pet.voice_assets.on_deleted(lambda sid: signals.voice_refs_changed.emit(-1))
        pet.lines_pools = {}
        pet._refresh_lines()

    # ---------------- 第二段：服务接线（原 __init__ L792~L831） ----------------

    def _build_services(self) -> None:
        """Balance / Weather / Chat / AI / 动作 / 语音 / 行为 / 闹钟 / 菜单（P0-1 那一批）。

        原注释保留：服务不 import 桌宠——配置/回调/信号全部构造注入；守卫状态仍归属
        PetWindow（语义不变）。tool_ctx 的六个能力全是 **lambda 晚绑定**：balance / actions
        在本段靠后（甚至本段之后）才构造，而工具只会在对话真的发生时被调用。
        """
        pet = self.pet
        data_dir = self._data_dir
        log = self._log
        signals = self._signals
        save_cfg = self._save_cfg

        pet.wander = pet_wander.WanderController(pet, lambda: pet.cfg, pet._screen_geo, save_cfg)
        pet.weather = pet_weather.WeatherService(pet, signals, lambda: pet.cfg, log)
        # v2.3.0（1.2 Function Calling）：工具上下文——能力全部注入，pet_tools 不认识任何业务模块。
        # 全用 lambda 晚绑定：balance/actions 在本行之后才构造，而工具只会在对话发生时被调用。
        pet.tool_ctx = pet_tools.ToolContext(
            balance=lambda: pet.balance.fetch_sync(),      # 只读：worker 线程内联（网络 I/O）
            weather=lambda: pet.weather.fetch_sync(),      # 只读：worker 线程内联
            ledger=lambda: pet._tool_ledger_summary(),     # 只读：账本摘要
            ui=lambda name, args: pet.chat.marshal(name, args),           # 主线程执行并等结果
            ui_async=lambda name, args: pet.chat.marshal_nowait(name, args),  # 只投递（对话框）
            log=log)
        pet.chat = pet_chat.ChatService(pet, signals, lambda: pet.cfg, self._ai_prompt,
                                        self._parse_emote, self._load_memory, self._save_memory,
                                        self._play_sound, log, self._max_reply_len,
                                        context_builder=pet._build_ai_context,  # v2.3.0：1.1+1.3
                                        memory_path=self._memory_path,
                                        tool_ctx=pet.tool_ctx)  # v2.3.0（1.2）：工具调用
        pet.ai = pet_ai.AIService(pet, pet.chat, lambda: pet.cfg, save_cfg, self._set_redact_key,
                                  self._remove_files,
                                  (self._usage_path, data_dir, self._config_path,
                                   self._memory_path),
                                  lambda: pet.book, log, self._defaults)
        pet.balance = pet_balance.BalanceService(pet, signals, lambda: pet.cfg, lambda: pet.book,
                                                 self._play_sound, save_cfg, log, pet.ai.set_api_key)
        pet.actions = pet_actions.ActionService(pet, lambda: pet.cfg, self._idle_picker,
                                                self._sleep_after)
        # v2.0：语音服务（默认关闭；片段播放注入 preview_audio）
        # v2.1：升级为配音系统——注入台词库/角色库/声音素材库，可插拔克隆后端 + 播放队列
        pet.voice = pet_voice.VoiceService(data_dir, lambda: pet.cfg,
                                           pet._play_voice_clip, log,
                                           stop_clip=pet._stop_voice_clip,
                                           save_cfg=save_cfg,
                                           lines=pet.lines_lib,
                                           roles=pet.role_lib,
                                           voice_assets=pet.voice_assets)
        # v2.0.2：行为自定义服务（待机行为/行为序列；执行调度在本类主线程）
        pet.behaviors = pet_behaviors.BehaviorService(data_dir)
        # v2.0.5：闹钟服务（到点判定在主线程 QTimer 轮询）
        pet.alarms = pet_alarm.AlarmService(data_dir)
        pet.menu_builder = pet_menu.MenuBuilder(pet, save_cfg, self._autostart_enabled)

    # ---------------- 第三段：帧动画播放器（原 __init__ L965） ----------------

    def build_anim(self) -> None:
        """帧动画播放器：**必须**在精灵建好之后、状态图之前构造（原 __init__ L965）。

        调用点被 _build_sprites()（L932）与 _load_default_frame_set("idle")（L987）夹着——
        pet 的 _custom_role / _assets_dir / sprites 都在那两步之间成型，所以只能按原位置调。
        """
        self.pet.anim = pet_anim.FrameAnim(self.pet)

    # ---------------- 第四段：情绪状态机（原 __init__ L1025） ----------------

    def build_mood(self) -> None:
        """情绪状态机：取词器是 pet 自己的 _mood_line（原 __init__ L1025）。

        原注释保留：v2.1.2 情绪台词也走台词库（用户可增删改）；库为空/不可用时
        pet_mood 回落内置常量。
        """
        self.pet.mood = pet_mood.Mood(self.pet, line_picker=self.pet._mood_line)
