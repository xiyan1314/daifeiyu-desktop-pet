# -*- coding: utf-8 -*-
"""D2「菜单悬停预览」+ 两个 UX 开关入口的钉子（v2.12.0 第 12 轮 · C/D2）。

判据全部是**行为**的：起一份 fake pet / fake 服务，调用真 `play_action(..., preview=True)`
与真 `MenuBuilder.open`，看它究竟做了什么、没做什么。旧版那种 grep 源码字串的断言
（如 `test_preview_branch_precedes_gates`）已删除——把默认值改掉它也不会红。

## 每条能真失败在哪（都在 %TEMP% 影子副本里实测变红过）

- `test_preview_writes_no_ledger_or_state`：预览分支里加一句
  `pet.balance.record_action(name)` → ledger.json 字节变长 / 配置被改 → 红；
- `test_preview_makes_no_sound_and_does_not_speak`：预览分支里加
  `pet.play_sound("pop")` 或 `pet.voice.play_event("preview")` → 红；
- `test_preview_really_shows_emote_and_frames`：把预览分支掏空成只剩 `return` → 红；
- `test_busy_and_eating_block_preview`：删掉 `if pet.busy or anim_mode == "eat"`
  这道忙闸 → 吃帧时 `anim.play` 仍被调用 → 红；
- `test_preview_is_not_swallowed_by_follow_or_wander_gates`：把预览分支挪到普通门控
  之后 → 开着「跟随鼠标/散步」时预览不演 → 红；
- `test_proc_actions_are_not_previewed`：把 `_play_proc` 接进预览 → `pet.procs`
  非空 → 红（真播路径本身不许动，见 pet_actions 里的分支注释）；
- `test_menu_hover_preview_default_is_off`：把 桌宠.DEFAULT_CONFIG 里
  `menu_hover_preview` 改成 True → 红（读的是**值**，不是源码字串）；
- `test_real_pet_exposes_the_two_setters`：把 PetWindow 的 `_set_easter_eggs` /
  `_set_menu_hover_preview` 删掉或改名 → 红（pet_menu 是直连，按约定不吞
  AttributeError，真机上右键菜单会整个打不开）；
- `test_two_settings_toggles_*`：删掉任一入口 / `toggled` 接错方法 / 勾选态硬编码 /
  读错配置键或丢掉默认值 → 红；
- `test_menu_build_does_not_fire_toggle_callbacks`：把 `setChecked` 挪到 `connect`
  之后 → 建菜单就回调写配置 → 红；
- `test_hover_fires_preview_once_after_delay`：删掉 `preview=True`、不接
  `hovered` / `timeout` / `aboutToHide` → 红。

测试不读真桌面：动作判据用 fake pet；菜单判据用 fake pet + offscreen QMenu；
不构造 PetWindow，不碰用户目录。
"""
import copy
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import pytest  # noqa: E402
from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QMenu, QWidget  # noqa: E402

import pet_actions  # noqa: E402
import pet_menu  # noqa: E402
import pet_motion  # noqa: E402


# ============================================================
# 一、play_action(preview=True) 的行为判据
# ============================================================
class _FakeAnim(object):
    def __init__(self):
        self._sets = {"wave": ["f0", "f1"]}
        self.plays = []

    def play(self, name, interval_ms=140, loops=-1, on_finish=None, rate_factor=1.0):
        self.plays.append({"name": name, "interval_ms": interval_ms, "loops": loops,
                           "on_finish": on_finish, "rate_factor": rate_factor})
        return True


class _FakeVoice(object):
    def __init__(self):
        self.events = []

    def play_event(self, event):
        self.events.append(event)
        return None


class _FakeBalance(object):
    """真账本替身：record_action 会往磁盘追加一行（预览一旦误走它，字节判据就红）。"""

    def __init__(self, ledger_path):
        self.ledger_path = ledger_path
        self.records = []

    def record_action(self, name):
        self.records.append(name)
        with open(self.ledger_path, "ab") as f:
            f.write(("ACTION %s\n" % name).encode("utf-8"))


class _PreviewPet(object):
    EAT_FRAME_MS = 140

    def __init__(self, ledger_path):
        self.busy = False
        self._petting = False
        self._sleeping = False
        self.anim_mode = "idle"
        self.anim = _FakeAnim()
        self.voice = _FakeVoice()
        self.cfg = {"follow_mouse": False, "wander": False}
        self.sounds = []
        self.emotes = []
        self.procs = []
        self.idle_calls = 0
        self.ledger_path = ledger_path
        self.balance = _FakeBalance(ledger_path)

    # ---- 被预览分支 / 真播分支引用的协作者 ----
    def play_sound(self, kind):
        self.sounds.append(kind)

    def _show_emote(self, kind):
        self.emotes.append(kind)

    def _play_proc(self, name, spec):
        self.procs.append((name, spec))

    def _play_idle(self):
        self.idle_calls += 1

    def _cur_form_anim(self):
        return {"interval_ms": 120}

    def _frame_rate_factor(self):
        return 1.0

    def _cur_procs(self):
        return {"breathe": {"kind": "breathe", "amp": 0.05, "period_ms": 1200}}

    def _wake(self):
        self._sleeping = False

    def _ensure_default_frames(self):
        return False

    def _wire_anim_sets(self):
        pass

    def _stop_tween(self):
        pass

    def show_bubble(self, text):
        pass


@pytest.fixture
def pet(tmp_path):
    ledger = tmp_path / "ledger.json"
    ledger.write_bytes(b'{"entries": [{"id": 1, "amount": 2.5}]}')
    return _PreviewPet(str(ledger))


def _service(pet):
    return pet_actions.ActionService(pet, lambda: pet.cfg,
                                     lambda: ("none", None), 99999)


def test_preview_writes_no_ledger_or_state(pet):
    """预览 = 一眼，不是一次真点播：ledger 逐字节不变、cfg 不变、不记统计。

    红法：在 pet_actions 预览分支里加 `pet.balance.record_action(name)`
    （或任何写 cfg / 落统计的调用）→ 字节比对或 cfg 比对立刻红。
    """
    before = open(pet.ledger_path, "rb").read()
    cfg_before = copy.deepcopy(pet.cfg)
    svc = _service(pet)
    for name, arg in (("emote", "note"), ("jump", None), ("wave", None), ("breathe", None)):
        svc.play_action(name, arg, preview=True)
    assert open(pet.ledger_path, "rb").read() == before, \
        "预览改了 ledger.json 的字节（预览不该落账）"
    assert pet.balance.records == [], "预览被当成一次真动作记进了统计：%r" % (pet.balance.records,)
    assert pet.cfg == cfg_before, "预览改了配置：%r -> %r" % (cfg_before, pet.cfg)


def test_preview_makes_no_sound_and_does_not_speak(pet):
    """预览零发声：`pet.play_sound` 与 `pet.voice.play_event` 调用次数 == 0。

    红法：把 `pet.play_sound("pop")` 或 `pet.voice.play_event("preview")` 挪进
    预览分支 → 两个 spy 立刻各记一条 → 红。
    """
    svc = _service(pet)
    for name, arg in (("emote", "zzz"), ("jump", None), ("wave", None)):
        svc.play_action(name, arg, preview=True)
    assert pet.sounds == [], "预览弹了音效：%r" % (pet.sounds,)
    assert pet.voice.events == [], "预览触发了语音事件：%r" % (pet.voice.events,)


def test_preview_really_shows_emote_and_frames(pet):
    """预览必须真的"演一下"：表情给 `_show_emote`、帧动作给 `anim.play`。

    红法：把预览分支掏空（只剩 `return`）→ 下面三条全红。
    """
    svc = _service(pet)
    svc.play_action("emote", "heart", preview=True)
    assert pet.emotes == ["heart"], "表情预览没演（emotes=%r）" % (pet.emotes,)
    assert pet.anim.plays == []

    pet.emotes.clear()
    svc.play_action("jump", preview=True)
    assert pet.emotes == ["note"], "跳跃预览至少要给头顶表情（emotes=%r）" % (pet.emotes,)

    pet.emotes.clear()
    svc.play_action("wave", preview=True)
    assert len(pet.anim.plays) == 1, "帧动作预览没有真的播一次：%r" % (pet.anim.plays,)
    call = pet.anim.plays[0]
    assert call["name"] == "wave" and call["loops"] == 1
    assert call["interval_ms"] == 120, "帧间隔没走当前形态（120ms）"
    assert call["on_finish"] == pet._play_idle, "播完没回待机（on_finish 丢了）"
    assert call["rate_factor"] == 1.0, "帧率倍率没传"


def test_busy_and_eating_block_preview(pet):
    """忙闸最先：`pet.busy` / `anim_mode == "eat"` 时预览一个像素都不动。

    红法：删掉 `if pet.busy or getattr(pet, "anim_mode", "") == "eat": return`
    → 吃帧时 `anim.play` 仍被调用（真机上这会 stop 掉吃帧的 _eat_done，busy 卡到
    看门狗），表情也会亮 → 红。
    """
    svc = _service(pet)
    pet.busy = True
    svc.play_action("emote", "note", preview=True)
    svc.play_action("wave", preview=True)
    assert pet.emotes == [] and pet.anim.plays == [], "busy 期间预览仍发生了"

    pet.busy = False
    pet.anim_mode = "eat"
    svc.play_action("emote", "note", preview=True)
    svc.play_action("wave", preview=True)
    assert pet.emotes == [] and pet.anim.plays == [], "吃帧期间预览仍发生了"


def test_preview_is_not_swallowed_by_follow_or_wander_gates(pet):
    """预览仍在普通门控**之前**：开着跟随/散步（且不忙）时，悬停照样演。

    红法：把整个 `if preview:` 分支挪到
    `if pet.busy or pet._petting or ...` 之后 → 这里 emotes 为空 → 红。
    这是旧 `test_preview_branch_precedes_gates` 源码字串断言的行为版。
    """
    svc = _service(pet)
    pet.cfg["follow_mouse"] = True
    pet.cfg["wander"] = True
    svc.play_action("emote", "note", preview=True)
    svc.play_action("wave", None, preview=True)
    assert pet.emotes == ["note"], "跟随/散步门控把预览吞了（emotes=%r）" % (pet.emotes,)
    assert len(pet.anim.plays) == 1, "跟随/散步门控把帧动作预览吞了"


def test_proc_actions_are_not_previewed(pet):
    """合成动作（菜单里的「✦ xxx（合成）」）不预览：不调 `_play_proc`，静默跳过。

    红法：把 `pet._play_proc(name, ...)` 接进预览分支（或删掉 `if preview:`
    让它掉进真播分派）→ pet.procs 非空 → 红。真播路径本身不归本判据管。
    """
    svc = _service(pet)
    svc.play_action("breathe", None, preview=True)
    assert pet.procs == [], "合成动作被预览真播了：%r" % (pet.procs,)
    assert pet.emotes == [] and pet.anim.plays == [], "合成动作预览还额外演了别的"


# ============================================================
# 二、默认值 / 菜单入口
# ============================================================
def test_menu_hover_preview_default_is_off():
    """默认关：`桌宠.DEFAULT_CONFIG["menu_hover_preview"]` 必须是 False。

    红法：把 桌宠.py 里那条默认值改成 True（旧用例 8 条全绿的那个洞）→ 红。
    这里直接读运行期常量（不是 grep 源码字串），改值一定红。
    """
    import 桌宠 as main
    assert main.DEFAULT_CONFIG["menu_hover_preview"] is False, \
        "悬停预览默认值不是 False（老用户升级后手一抖就动）"


def test_real_pet_exposes_the_two_setters():
    """两个 setter 必须真长在 PetWindow 上（pet_menu 直连、按约定不吞 AttributeError）。

    红法：把 桌宠.PetWindow._set_easter_eggs / _set_menu_hover_preview 删掉或改名 →
    菜单一 open 就抛 AttributeError（真机上右键菜单整个打不开），本条先红。
    """
    import 桌宠 as main
    assert callable(getattr(main.PetWindow, "_set_easter_eggs", None)), \
        "PetWindow 上没有 _set_easter_eggs（菜单 toggled 直连它）"
    assert callable(getattr(main.PetWindow, "_set_menu_hover_preview", None)), \
        "PetWindow 上没有 _set_menu_hover_preview（菜单 toggled 直连它）"


def _noop(*args, **kwargs):
    return None


class _Any(object):
    """菜单构造只要求"有这个属性"，不要求真做事的协作者。

    属性一律给**真函数**（PySide 的 connect 会反射调用对象的 dunder；给它一个
    __getattr__ 什么都返回的自定义对象会在 C++ 侧踩到访问冲突——实测过）。
    """

    def __init__(self, name="?"):
        self.name = name

    def __getattr__(self, item):
        if item.startswith("__"):
            raise AttributeError(item)
        return _noop


class _RoleLib(object):
    def list_roles(self):
        return []


class _FoodTray(object):
    def isVisible(self):
        return False


class _Actions(object):
    def __init__(self):
        self.calls = []

    def play_action(self, name, arg=None, force=False, preview=False):
        self.calls.append((name, arg, force, preview))
        return None

    def show_system_status(self):
        pass


class _MenuPet(QWidget):
    """只够 `MenuBuilder.open` 跑完的假桌宠（QWidget：真 _new_menu 就是 QMenu(pet)；
    offscreen，不读桌面、不写配置）。"""

    def __init__(self, cfg=None):
        super().__init__()
        self.cfg = {
            "always_on_top": True, "sound": True, "ai_enabled": False, "physics": {},
            "role": "", "badge": False, "click_through": False, "fullscreen_hide": True,
            "notify": True, "time_mood": False, "reduce_motion": "off",
            "high_contrast": "off", "menu_hover_preview": False, "easter_eggs": True,
        }
        if cfg:
            self.cfg.update(cfg)
        self.scale = 1.0
        self._shown_balance = None
        self._currency = "CNY"
        self._usage = 0.0
        self.form_keys = ["default"]
        self.form_names = {"default": "默认"}
        self.form = "default"
        self.has_transform_form = False
        self._top_act = self._ai_act = self._follow_act = self._wander_act = None
        self._autostart_act = None
        self._hover_preview = None
        self._hover_preview_timer = None
        self.role_lib = _RoleLib()
        self.food_tray = _FoodTray()
        self.ai = _Any("ai")
        self.wander = _Any("wander")
        self.balance = _Any("balance")
        self.actions = _Actions()
        self.mood = _Any("mood")
        self.weather = _Any("weather")
        self.last_menu = None
        self.toggled_calls = []
        for name in ("_schedule_scale_save", "set_scale", "_set_always_on_top",
                     "_set_sound", "_set_physics", "feed", "_set_food_tray",
                     "set_user_form", "apply_role", "_export_role", "_import_role_bundle",
                     "_set_badge", "_set_click_through", "set_fullscreen_hide",
                     "_set_notify", "_set_time_mood", "_set_reduce_motion",
                     "_set_high_contrast", "_set_sound_group", "_set_autostart",
                     "_clear_logs", "_about", "_quit", "_set_city",
                     "_open_behavior_dialog", "_menu_start_voice_backend",
                     "_open_idle_dialog", "_open_alarm_dialog", "_play_idle"):
            setattr(self, name, _noop)
        # 只有这两个是**真 spy**：接错名字 / 没接 → toggled_calls 对不上。
        self._set_easter_eggs = lambda on: self.toggled_calls.append(("easter_eggs", bool(on)))
        self._set_menu_hover_preview = lambda on: self.toggled_calls.append(
            ("menu_hover_preview", bool(on)))

    def _new_menu(self):
        self.last_menu = _CaptureMenu(self)
        return self.last_menu

    def _reduce_motion(self):
        return False

    def _high_contrast(self):
        return False

    def custom_actions(self):
        return []


_CAPTURED = {}


class _CaptureMenu(QMenu):
    def exec(self, *_a, **_k):  # noqa: A003 —— Qt 的名字
        _CAPTURED["top"] = list(self.actions())
        for act in self.actions():
            if act.text().startswith("⚙️ 设置"):
                _CAPTURED["settings"] = act.menu()
        return None


def _build_menu(pet):
    _CAPTURED.clear()
    pet_menu.MenuBuilder(pet, lambda cfg: None, lambda: False).open(QPoint(5, 5))
    return _CAPTURED["settings"], _CAPTURED["top"]


def _settings_actions(pet):
    settings, top = _build_menu(pet)
    return {a.text(): a for a in settings.actions() if a.text()}, settings, top


def test_two_settings_toggles_exist_and_read_effective_values():
    """两个 UI 入口必须存在、可勾、在「⚙️ 设置…」子菜单里、勾选态读**配置值**。

    红法（任一都红）：
    - 删掉 `egg_act` / `hover_act` 的任一入口 → 找不到 action；
    - 设成 `setCheckable(False)` 或把 `toggled` 接错方法 → 触发后 spy 对不上；
    - 勾选态硬编码（不读 cfg）→ cfg=False/True 下的勾选态反了；
    - 把入口加到**顶层** → 顶层名单里出现且超 9 项。
    """
    pet = _MenuPet({"easter_eggs": False, "menu_hover_preview": True})
    acts, _settings, top = _settings_actions(pet)
    egg = acts.get("🎁 惊喜彩蛋")
    hover = acts.get("👀 菜单悬停预览")
    assert egg is not None, "「⚙️ 设置…」里没有「🎁 惊喜彩蛋」（现有：%r）" % (sorted(acts),)
    assert hover is not None, "「⚙️ 设置…」里没有「👀 菜单悬停预览」（现有：%r）" % (sorted(acts),)
    assert egg.isCheckable() and hover.isCheckable(), "两个入口必须可勾选"
    assert egg.isChecked() is False, "cfg easter_eggs=False 却显示为勾选"
    assert hover.isChecked() is True, "cfg menu_hover_preview=True 却显示为未勾选"

    top_texts = [a.text() for a in top if a.text()]
    assert "🎁 惊喜彩蛋" not in top_texts, "彩蛋开关不许加到顶层（硬上限 9 项）"
    assert "👀 菜单悬停预览" not in top_texts, "悬停预览开关不许加到顶层（硬上限 9 项）"
    assert len(top_texts) <= 9, "顶层菜单超了 9 项：%d" % (len(top_texts),)

    assert pet.toggled_calls == [], "建菜单就调了 setter（应只在用户点击时落盘）"
    egg.trigger()
    assert pet.toggled_calls[-1] == ("easter_eggs", True), \
        "「🎁 惊喜彩蛋」的 toggled 没接到 _set_easter_eggs（实际：%r）" % (pet.toggled_calls,)
    hover.trigger()
    assert pet.toggled_calls[-1] == ("menu_hover_preview", False), \
        "「👀 菜单悬停预览」的 toggled 没接到 _set_menu_hover_preview（实际：%r）" % (pet.toggled_calls,)


def test_settings_toggles_use_defaults_when_keys_missing():
    """配置里没这两个键时，勾选态必须落到默认值：彩蛋开、悬停预览关。

    红法：把 `pet.cfg.get("easter_eggs", True)` 的默认值去掉（→ None→未勾选）或把
    `menu_hover_preview` 的默认值写成 True → 红。
    """
    pet = _MenuPet()
    acts, _settings, _top = _settings_actions(pet)
    assert acts["🎁 惊喜彩蛋"].isChecked() is True, "彩蛋缺省应为开"
    assert acts["👀 菜单悬停预览"].isChecked() is False, "悬停预览缺省应为关"


def test_menu_build_does_not_fire_toggle_callbacks():
    """打开菜单只读值、不写值：两个 cfg 都是 True 时建菜单也不许回调 setter。

    红法：把 `setChecked(True)` 挪到 `toggled.connect(...)` 之后 → 建菜单那一刻
    QAction 由未勾→勾会 emit toggled → toggled_calls 非空 → 红（等于每开一次菜单就
    落盘一次、还可能弹一条回执气泡）。
    """
    pet = _MenuPet({"easter_eggs": True, "menu_hover_preview": True})
    _settings_actions(pet)
    assert pet.toggled_calls == [], "建菜单触发了 setter：%r" % (pet.toggled_calls,)


def test_hover_fires_preview_once_after_delay():
    """悬停 → 起 300ms 单发计时器 → 到点调一次 `play_action(..., preview=True)`。

    不用 sleep：手动 `timeout.emit()` 模拟到点。红法：去掉 `preview=True`（会变成
    真点播）、不接 `hovered` / `timeout` / `aboutToHide`（计时器不起、动作不到或
    移开后还补播一次）→ 红。
    """
    pet = _MenuPet({"menu_hover_preview": True})
    _settings, top = _build_menu(pet)
    act_menu = next(a.menu() for a in top if a.text().startswith("🎭 动作"))
    jump = next(a for a in act_menu.actions()
                if a.data() is not None and tuple(a.data()) == ("jump", None))

    act_menu.hovered.emit(jump)
    timer = pet._hover_preview_timer
    assert timer is not None and timer.isActive(), "悬停没起计时器"
    assert timer.interval() == pet_motion.duration_ms("PREVIEW") == 300

    timer.timeout.emit()
    assert pet.actions.calls == [("jump", None, True, True)], \
        "到点没有以 preview=True 播一次（实际：%r）" % (pet.actions.calls,)

    act_menu.aboutToHide.emit()
    assert not timer.isActive(), "菜单收起后计时器还在跑（会晚到补播）"
    timer.timeout.emit()
    assert len(pet.actions.calls) == 1, "移开菜单后还补播了一次"


def test_hover_preview_is_off_by_default():
    """默认关的**行为**版：配置缺省时根本不建预览计时器，悬停也不会点播。

    红法：把 `if cfg.get("menu_hover_preview"):` 去掉（一律建表）→ 红。
    """
    pet = _MenuPet()
    _settings, top = _build_menu(pet)
    assert pet._hover_preview_timer is None, "默认关却建了预览计时器"
    assert pet._hover_preview is None
    act_menu = next(a.menu() for a in top if a.text().startswith("🎭 动作"))
    jump = next(a for a in act_menu.actions()
                if a.data() is not None and tuple(a.data()) == ("jump", None))
    act_menu.hovered.emit(jump)
    assert pet.actions.calls == [], "默认关却因为悬停点播了：%r" % (pet.actions.calls,)


# ============================================================
# 三、HoverPreview 判定器（纯逻辑，零 QTimer，无需 sleep）
# ============================================================
class _Sink(object):
    def __init__(self):
        self.calls = []

    def __call__(self, key):
        self.calls.append(tuple(key))


def test_new_action_returns_delay():
    """首次悬停返回 300 → fire 播一次。红法：hover 恒返回 0 → 红。"""
    s = _Sink()
    hp = pet_menu.HoverPreview(300, s)
    assert hp.hover(("emote", "zzz")) == 300
    hp.fire()
    assert s.calls == [("emote", "zzz")]


def test_same_key_does_not_restart():
    """同一格里晃鼠标不重置计时。红法：去掉 `if key == self._key: return 0` → 红。"""
    s = _Sink()
    hp = pet_menu.HoverPreview(300, s)
    assert hp.hover(("jump", None)) == 300
    assert hp.hover(("jump", None)) == 0
    hp.fire()
    assert s.calls == [("jump", None)]
    assert hp.hover(("jump", None)) == 300    # 播完再悬停 = 新的一轮


def test_cancel_drops_pending():
    """移开菜单不许晚到补播。红法：cancel 里不把 `_key` 清 None → 红。"""
    s = _Sink()
    hp = pet_menu.HoverPreview(300, s)
    hp.hover(("jump", None))
    hp.cancel()
    hp.fire()
    assert s.calls == []


def test_disabled_never_previews():
    """开关关掉时一次都不起表。红法：删掉 `not self.enabled` 判断 → 红。"""
    s = _Sink()
    hp = pet_menu.HoverPreview(300, s, enabled=False)
    assert hp.hover(("jump", None)) == 0
    hp.fire()
    assert s.calls == []


def test_no_data_is_not_previewable():
    """分隔线 / 子菜单 / 裸字符串不预览。红法：去掉类型判断 → 红。"""
    s = _Sink()
    hp = pet_menu.HoverPreview(300, s)
    assert hp.hover(None) == 0
    assert hp.hover("jump") == 0
    hp.fire()
    assert s.calls == []


def test_delay_token_is_300ms():
    """延时令牌值本身：改成 0/其它值 → 红（菜单侧计时器用同一令牌）。"""
    assert pet_motion.duration_ms("PREVIEW") == 300
