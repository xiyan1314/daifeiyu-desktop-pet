# -*- coding: utf-8 -*-
"""
DeepSeek 大肥鱼桌宠 (PySide6 / Qt6)
MIT License
一只又娇又耍赖、贪吃、被吓到就浑身发抖的大肥鱼桌宠。
名台词：喜欢的，就咬住不放~
运行：绿色版双击 启动桌宠.vbs；源码运行双击 启动桌宠.bat（或 python 桌宠.py）。
"""
# entry-marker: daifeiyu_pet_main（绿色版启动器靠此 ASCII 标记定位主程序，勿删）

import os
import sys
import json
import math
import random
import threading
import time
import copy
import ctypes
import re
from ctypes import wintypes

import psutil

from PySide6.QtCore import (
    Qt, QTimer, QPoint, QVariantAnimation, QObject, Signal,
)
from PySide6.QtGui import (
    QPixmap, QImage, QTransform, QColor, QPainter, QCursor, QIcon,
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QMenu, QGraphicsView, QGraphicsScene,
    QGraphicsPixmapItem, QInputDialog, QMessageBox, QFrame,
    QSystemTrayIcon, QDialog, QWidgetAction, QFileDialog,
)

import pet_log
import pet_physics
import pet_voice
import pet_anim
import pet_fx
import pet_mood
import pet_audio
import pet_resources
import pet_book
import pet_dialogs
import pet_screen
import pet_config
import pet_lines
import pet_widgets
import pet_wander
import pet_chat
import pet_weather
import pet_balance
import pet_menu
import pet_ai
import pet_actions
import pet_main
import pet_behaviors
import pet_export
import pet_alarm


APP_NAME = "大肥鱼桌宠"
VERSION = "2.1.3"
PAD = 1.25  # 窗口相对角色的透明边距（为压扁/回弹预留空间）
IDLE_FRAME_MS = 140      # 待机帧间隔
IDLE_FORM_HOLD_SECS = 8  # v2.1.3：只有形态、没有动作可播时的展示期上限（到期回用户形态）
EAT_FRAME_MS = 110       # 进食帧间隔
SLEEP_AFTER_SECONDS = 60 # 无交互多久入睡
STATE_DURATION_MS = 2500 # 状态图默认展示时长
# 跟随/散步行走参数（v1.4.2 降速档）实现迁至 pet_wander：此处保留模块级名字（tests/v13 依赖）
from pet_wander import WALK_INTERVAL_MS, WALK_EASE, WALK_STEP_MIN, WALK_STEP_MAX, _walk_step  # noqa: E402,F401
SOUND_KIND_MAP = {"boing": "press", "pop": "release", "feed": "feed"}


# ---------------- 路径 / 配置 ----------------
def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resource_dir(rel):
    """目录级资源定位：优先 exe/脚本同目录，冻结环境回退 _MEIPASS。"""
    p = os.path.join(app_dir(), rel)
    if os.path.isdir(p):
        return p
    if getattr(sys, "frozen", False):
        p2 = os.path.join(getattr(sys, "_MEIPASS", app_dir()), rel)
        if os.path.isdir(p2):
            return p2
    return p


def resource_path(rel):
    p = os.path.join(app_dir(), rel)
    if os.path.exists(p):
        return p
    if getattr(sys, "frozen", False):
        p2 = os.path.join(getattr(sys, "_MEIPASS", app_dir()), rel)
        if os.path.exists(p2):
            return p2
    return p


def _data_dir():
    """数据目录：优先 exe 同目录（便携）；不可写则回退 %APPDATA%。"""
    d = app_dir()
    probe = os.path.join(d, ".write_probe")
    try:
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
        return d
    except Exception:
        pass  # 有意忽略：探针失败=目录不可写，按规则回退 APPDATA
    alt = os.path.join(os.environ.get("APPDATA", d), "大肥鱼桌宠")
    try:
        os.makedirs(alt, exist_ok=True)
        return alt
    except Exception:
        return d


DATA_DIR = _data_dir()
pet_log.set_data_dir(DATA_DIR)
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
DEFAULT_CONFIG = {
    "scale": 1.0,
    "always_on_top": True,
    "ai_enabled": False,
    "api_key": "",
    "city": "北京",
    "follow_mouse": False,
    "wander": False,
    "sound": True,
    "badge": False,
    "role": "",          # 自定义角色 id（"" = 默认角色）
    "sound_group": "default",  # "default" | "custom"（自定义音效组）
    "bubble_style": {"bg": "#ffffff", "fg": "#203170", "border": "#203170", "font_size": 10, "radius": 16},
    "lines_extra": {"sajiao": [], "greedy": [], "happy": [], "idle": []},
    "budget": 0.0,       # 今日预算提醒（<=0 关闭）
    "balance_alert": 0.0,  # 余额预警阈值（<=0 关闭）
    "scale_compensated_role": "",  # 旧版超大角色素材的 scale 一次性补偿标记（文件名）
    "chat_memory_rounds": 3,  # P1-6：对话上下文轮数（0~10；0=不带记忆）
    "ai_base_url": "",        # P1-10：AI 接口地址（空=默认 api.deepseek.com）
    "ai_model": pet_chat.DEFAULT_MODEL,  # P1-10：模型名（单一来源 pet_chat.DEFAULT_MODEL）
    "ai_system_prompt": "",   # P1-10：人设（空=内置大肥鱼人设）
    "ai_max_tokens": 60,
    "ai_reply_len": 25,
    "ai_persona": "default",  # P1-10+：人设预设 id（default/sheshe/tsundere/custom）
    "click_through": False,   # P3-1：透明区点击穿透（只命中身体，默认关闭）
    "role_frame_max": 24,     # P3-5+：帧动画帧数上限（2~60，用户可调）
    # P1-手感：甩抛物理（默认关闭=行为与旧版逐像素一致；参数与 pet_physics.DEFAULT_PHYSICS 同构）
    "physics": {"enabled": False, "gravity": 1400.0, "restitution": 0.78,
                "groundFriction": 2.5, "ceilingBounce": True, "throwPower": 1.0},
    # v2.0：语音系统（默认关闭；默认值单一来源 pet_voice.DEFAULT_VOICE）
    "voice": pet_voice.DEFAULT_VOICE,
    # v2.0.2：行为系统（默认值单一来源 pet_behaviors.DEFAULT_BEHAVIOR_CFG；
    # 待机行为默认关闭 = 行为与旧版完全等价）
    "idle_behavior": pet_behaviors.DEFAULT_BEHAVIOR_CFG["idle_behavior"],
    "idle_behavior_seconds": pet_behaviors.DEFAULT_BEHAVIOR_CFG["idle_behavior_seconds"],
    "transform_seconds": pet_behaviors.DEFAULT_BEHAVIOR_CFG["transform_seconds"],
    # v2.1：待机系统（两触发 + 多动作 + idle_form；默认值单一来源 pet_behaviors）
    "idle_trigger_delay": pet_behaviors.DEFAULT_BEHAVIOR_CFG["idle_trigger_delay"],
    "idle_delay_after_full": pet_behaviors.DEFAULT_BEHAVIOR_CFG["idle_delay_after_full"],
    "idle_form": pet_behaviors.DEFAULT_BEHAVIOR_CFG["idle_form"],
    "idle_actions": pet_behaviors.DEFAULT_BEHAVIOR_CFG["idle_actions"],
    "idle_play_mode": pet_behaviors.DEFAULT_BEHAVIOR_CFG["idle_play_mode"],
    "idle_resume_on_interrupt": pet_behaviors.DEFAULT_BEHAVIOR_CFG["idle_resume_on_interrupt"],
}

# P1-3：config.json schema 版本（1=旧版全量存储；2=diff 只存改动项）
CONFIG_SCHEMA_VERSION = 2
# P1-3：本次加载被自动修正的字段说明（load_config 重置，启动提示一次后不再提示）
CONFIG_FIXES = []
# P1-3：软归一化键——合法值的美化（bool 字符串、strip、rstrip 等）不算「坏值」：
# 静默重存但不弹修正提示；其余键的改动才算「坏值已修正」
_SOFT_FIX_KEYS = {"always_on_top", "ai_enabled", "follow_mouse", "wander", "sound", "badge",
                  "ai_base_url", "ai_model", "ai_system_prompt", "lines_extra",
                  "sound_group", "role", "scale_compensated_role",
                  "ai_persona", "click_through", "role_frame_max", "physics", "voice",
                  "idle_behavior", "idle_behavior_seconds", "transform_seconds",
                  "idle_trigger_delay", "idle_delay_after_full", "idle_form", "idle_actions",
                  "idle_play_mode", "idle_resume_on_interrupt"}


def _fix_entry(k, a, b):
    """单条修正说明：嵌套 dict/list 只报键名，标量报前后值，总长截断防气泡爆炸。"""
    if isinstance(a, (dict, list)) or isinstance(b, (dict, list)):
        return "%s 已修正" % k
    entry = "%s: %r→%r" % (k, a, b)
    if len(entry) > 30:
        entry = entry[:27] + "…"
    return entry


def set_redact_key(key):
    """由 PetWindow 在 key 载入 / 修改 / 清除后同步，并同步给 pet_log 的脱敏缓存。"""
    global _redact_key
    _redact_key = str(key or "")
    pet_log.set_redact_key(_redact_key)


def _redact(msg):
    """日志脱敏（P0-2：实现迁至 pet_log，保留函数名供全仓/tests 调用）。"""
    return pet_log.redact(msg)


def _log_error(msg):
    """统一日志（P0-2：实现迁至 pet_log，保留函数名供全仓调用）。"""
    pet_log.log_error(msg, data_dir=DATA_DIR)


def _remove_files(paths):
    """批量删除运行时文件（尽力而为），返回删除条数。清 Key / 清日志 / 退出共用。"""
    removed = 0
    for p in paths:
        try:
            if os.path.exists(p):
                os.remove(p)
                removed += 1
        except Exception:
            pass  # 有意忽略：运行时文件清理尽力而为（幂等清理）
    return removed


# ---- 模块级名字保留（tests/_verify_v13 依赖；实现迁至独立模块，行为不变） ----
from pet_screen import SCREEN_EDGE_MARGIN_X, SCREEN_EDGE_MARGIN_Y, screen_geometry_at  # noqa: E402,F401
from pet_config import encrypt_secret, decrypt_secret  # noqa: E402,F401
from pet_lines import (LINES_SAJIAO, LINES_GREEDY, LINES_SCARED, LINES_HAPPY,  # noqa: E402,F401
                       LINES_IDLE, LINES_STARTUP, LINES_PETTING, FOOD_LINES)
from pet_widgets import (BUBBLE_STYLE, food_pixmap, FoodTray, FoodFlyer, Badge, Bubble,  # noqa: E402,F401
                         _emote_mark, _STATE_MARK_MAP, _make_custom_state_pix)
from pet_weather import WEATHER_CODES  # noqa: E402,F401

# 右键菜单美化：深色圆角紧凑主题（参考小鲸鱼挂件布局：滑块 + 平铺开关 + 少量子菜单）
MENU_QSS = """
QMenu {
    background-color: rgba(26, 30, 48, 0.97);
    color: #e8ecff;
    border: 1px solid #3b4370;
    border-radius: 10px;
    padding: 4px;
}
QMenu::item {
    padding: 5px 24px 5px 12px;
    border-radius: 6px;
    font-size: 12px;
}
QMenu::item:selected { background-color: #39426e; }
QMenu::item:disabled { color: #6b7399; }
QMenu::separator { height: 1px; background: #333a5e; margin: 3px 10px; }
QMenu::indicator { width: 13px; height: 13px; }
QSlider::groove:horizontal {
    height: 4px; background: #2e3560; border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 12px; margin: -5px 0; background: #ffd65a; border-radius: 6px;
}
QSlider::sub-page:horizontal { background: #ffd65a; border-radius: 2px; }
"""


# ---------------- P1-3：配置 schema 版本与迁移 ----------------
def _migrate_1_to_2(data):
    """v1(全量存储、无 schema_version) → v2(diff 存储)：字段名无变化，仅登记版本。

    旧版多余字段由 load_config 的 DEFAULT_CONFIG 白名单自然丢弃；
    本函数为将来字段重命名/拆分的迁移留位。"""


_CONFIG_MIGRATIONS = {1: _migrate_1_to_2}


def migrate_config(data, from_ver):
    """按版本链把旧配置迁移到当前 schema（就地修改 dict）。

    返回 True 表示迁移完整到达当前版本；False 表示某步迁移缺失/失败——
    此时**不**升级版本号，调用方按「未迁移」处理，避免半成品数据被标成最新版本。"""
    v = from_ver
    while v < CONFIG_SCHEMA_VERSION:
        fn = _CONFIG_MIGRATIONS.get(v)
        if fn is None:
            _log_error("migrate_config: 缺少 %d→%d 迁移函数，中止迁移" % (v, v + 1))
            return False
        try:
            fn(data)
        except Exception as e:
            _log_error("migrate_config %d→%d 失败: %r" % (v, v + 1, e))
            return False
        v += 1
    data["schema_version"] = CONFIG_SCHEMA_VERSION
    return True


def _parse_schema_version(raw):
    """schema_version 必须是 1..N 的整数；缺失/非法（浮点/负数/字符串）一律按 v1 处理。"""
    if isinstance(raw, float):
        return 1  # int(2.5)=2 会静默截断：显式拒绝
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return 1
    if v < 1:
        return 1
    return v


def load_config():
    global CONFIG_FIXES
    CONFIG_FIXES = []
    cfg = dict(DEFAULT_CONFIG)
    future_cfg = False  # P1-3：读到未来版本配置时禁写回（防降级覆盖未来键）
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            ver = _parse_schema_version(data.get("schema_version"))
            if ver > CONFIG_SCHEMA_VERSION:
                # 未来版本写出的配置：只合并认识的键，不迁移、不回写（兼容模式只读）
                future_cfg = True
                _log_error("load_config: schema v%d 高于当前 v%d，按兼容模式读取"
                           % (ver, CONFIG_SCHEMA_VERSION))
            elif ver < CONFIG_SCHEMA_VERSION:
                if migrate_config(data, ver):
                    cfg["_resave"] = True  # 旧版配置：迁移成功后立即按新 schema（diff）重存
            for k, v in data.items():
                if k in DEFAULT_CONFIG:
                    cfg[k] = v
            # v2.1 迁移（必须在合并默认值之后、归一化之前，且以**原始文件**为准）：
            # 新键 idle_trigger_delay 在 DEFAULT_CONFIG 里天然存在，若只让 normalize 判断
            # "新键缺失才读旧键"，旧用户设的 idle_behavior_seconds 会被默认值吃掉（S2）。
            if "idle_trigger_delay" not in data and "idle_behavior_seconds" in data:
                cfg["idle_trigger_delay"] = data.get("idle_behavior_seconds")
            # 同理：旧自定义台词（lines_extra）在 normalize 里已被历史截断逻辑处理过，
            # 迁移必须用原始值，否则 20 条/60 字的旧限制会在迁移时把数据吃掉（S3）。
            if isinstance(data.get("lines_extra"), dict):
                cfg["_legacy_lines_extra"] = data.get("lines_extra")
    except FileNotFoundError:
        # 兼容审查 L4：**首次运行**（还没有 config.json）不是错误，不该往 error.log 里写
        # 吓人的"读取失败"。与 pet_resources._read_json 的"首次无文件=静默"口径保持一致。
        set_redact_key("")
    except Exception as e:
        _log_error("load_config 读取失败（按默认值运行）: %r" % (e,))
        set_redact_key("")  # 配置读不到=没有 key：同步脱敏缓存，阻断 _redact 兜底重读的日志环
    # 密文 key 解密：放在修正快照之前，避免 dpapi: 前缀被误判为「被修正」
    raw_key = str(cfg.get("api_key", "") or "")
    if raw_key and not raw_key.startswith("dpapi:"):
        if not future_cfg:
            cfg["_resave"] = True  # 旧版明文 key，立即重加密
    cfg["api_key"] = decrypt_secret(raw_key)
    if raw_key.startswith("dpapi:") and not cfg["api_key"]:
        # DPAPI 解密失败（换用户/换机器）：本次按空 Key 运行，不改写磁盘防密文被误清
        _log_error("load_config: api_key DPAPI 解密失败，本次按空 Key 运行（不改写磁盘）")
    before = copy.deepcopy(cfg)  # P1-3：归一化前快照，用于检测「被自动修正的字段」
    # P0-1：归一化逻辑迁至 pet_config（纯逻辑、无模块全局依赖）
    pet_config.normalize_cfg(cfg, DEFAULT_CONFIG, frozenset(PERSONA_PRESETS))
    # P1-3：坏值修正检测——与快照对比。软归一化（合法值美化）静默重存不弹提示；
    # 硬修正（越界/类型非法）记入 CONFIG_FIXES 供启动气泡提示一次
    soft_changed = False
    for k in tuple(before):
        if k not in DEFAULT_CONFIG:
            continue
        if before[k] != cfg[k]:
            if k in _SOFT_FIX_KEYS:
                soft_changed = True
            else:
                CONFIG_FIXES.append(_fix_entry(k, before[k], cfg[k]))
    if (CONFIG_FIXES or soft_changed) and not future_cfg:
        cfg["_resave"] = True
    return cfg


def save_config(cfg):
    # P0-1：diff 存储核心迁至 pet_config（api_key 密文特通道 + 原子替换）
    pet_config.write_config(CONFIG_PATH, cfg, DEFAULT_CONFIG, CONFIG_SCHEMA_VERSION,
                            _log_error, encrypt_secret)


# ---------------- 音效（参考项目音频 + 合成回退，统一由 pet_audio 管理） ----------------
def play_sound(kind):
    """kind: boing(按压)/pop(松手)/feed(喂食) → pet_audio.play(press/release/feed)。"""
    pet_audio.play(SOUND_KIND_MAP.get(kind, kind))


MAX_REPLY_LEN = 25
SYSTEM_PROMPT = (
    "你是一只叫大肥鱼的桌面宠物，又娇又耍赖、贪吃、被吓到就浑身发抖。"
    "性格参考绝区零的希希芙（网友叫她「啥子蛇」）：自称只遵循本能、自私任性的「坏蛋」，"
    "嘴上冷血毒舌，其实心软护短；经常「嘶~」地吐蛇信子，爱用「本专员」自称，"
    "把贪吃耍赖包装成案件调查（比如小鱼干失踪案、蛋糕失窃案）。"
    "你把用户称呼为「绳匠」。"
    "回答必须中文、俏皮贱萌、不超过%d个字。"
    "喜欢说：喜欢的，就咬住不放~"
) % MAX_REPLY_LEN

# P1-10+：人设预设库——用户可在「AI设置」里换人设，或选「自定义」完全自己写。
# 注：定义在 load_config 之后但只在其运行时引用（模块加载完成后才调用），无 NameError。
PERSONA_PRESETS = {
    "default": SYSTEM_PROMPT,
    "sheshe": (
        "你是一只叫「啥子蛇」的蛇系桌宠，本体是绝区零希希芙那种坏蛋蛇。"
        "自称「本专员」，嘴上冷血毒舌、贪吃耍赖，其实心软护短；经常「嘶~」吐蛇信子。"
        "把贪吃包装成案件调查（小鱼干失踪案、蛋糕失窃案），把用户称呼为「绳匠」。"
        "回答必须中文、毒舌又贱萌、不超过%d个字。"
    ) % MAX_REPLY_LEN,
    "tsundere": (
        "你是一只叫大肥鱼的傲娇桌宠，典型傲娇：嘴上嫌弃（才不是关心你呢），"
        "行为上偷偷护着主人。爱吃小鱼干、爱面子，被戳破心事会「哼！」一声别过头。"
        "把用户称呼为「绳匠」。回答必须中文、傲娇可爱、不超过%d个字。"
    ) % MAX_REPLY_LEN,
}

# P3-3：AI 回复可带出的表情标记（回复开头【xxx】，解析后剥除，不进记忆）
# 值 = (模式, 表情)：state → _show_state（状态图），emote → _show_emote（程序化表情）
AI_EMOTE_TAGS = {
    "happy": ("emote", "heart"),
    "laugh": ("state", "laugh"),
    "angry": ("state", "angry"),
    "blush": ("state", "blush"),
    "cry": ("state", "cry"),
    "smug": ("state", "smug"),
    "puzzled": ("state", "puzzled"),
    "note": ("emote", "note"),
    "sparkle": ("emote", "sparkle"),
}

_EMOTE_INSTRUCTION = (
    "回复可在开头用【表情】标记当前心情（可选：%s），例如【happy】今天心情不错~；"
    "不标记也可以。"
) % "、".join(sorted(AI_EMOTE_TAGS))


def parse_emote_tag(text):
    """P3-3：解析回复开头的【表情】标记。返回 (emote_kind, 剥除后的文本)。

    无合法标记时 emote_kind 为 None、原样返回文本。"""
    m = re.match(r"^【([^】]+)】\s*(.*)$", text or "")
    if not m:
        return None, None, (text or "")
    tag = m.group(1).strip()
    pair = AI_EMOTE_TAGS.get(tag)
    if pair is None:
        return None, None, (text or "")
    rest = m.group(2).strip()
    return pair[0], pair[1], rest


# P3-2：闲逛动作目录（名称, 参数, 权重）——_idle_tick 加权随机，右键「动作」点播复用
# 权重刻意保留「大约 65% 有动作」（与旧 0.35/0.65 节奏相当），新动作从无事占比中拆出
IDLE_ACTIONS = [
    ("none", None, 35),        # 安静待着（保持旧节奏）
    ("emote", "zzz", 30),      # 打盹气泡
    ("jump", None, 25),        # 原地小跳
    ("emote", "note", 4),      # 音符
    ("emote", "sparkle", 3),   # 星光
    ("emote", "heart", 3),     # 爱心
]


def pick_idle_action(rnd=None):
    """P3-2：按权重随机挑一个闲逛动作（纯函数，供测试与 _idle_tick 共用）。"""
    r = (rnd or random.random)()
    total = sum(w for _, _, w in IDLE_ACTIONS)
    acc = 0.0
    for name, arg, w in IDLE_ACTIONS:
        acc += w / total
        if r < acc:
            return name, arg
    return IDLE_ACTIONS[0][0], IDLE_ACTIONS[0][1]


# ---------------- 跨线程信号 ----------------
class Signals(QObject):
    reply = Signal(str)
    reply_ok = Signal()  # AI 回复成功（主线程播任务完成音）
    ai_emote = Signal(str, str)  # P3-3：AI 回复带出表情（mode=state/emote, kind）
    voice_play = Signal(str)  # v2.0：合成 worker 线程 → 主线程播放投递（QMediaPlayer 仅主线程）
    voice_error = Signal(str)  # v2.0：合成失败原因 → 主线程气泡（不跨线程碰 Qt 控件）
    # v2.1：语言系统（配音）worker 线程 → 主线程（角色槽位, 台词 id）
    voice_started = Signal(str, str)   # 开始朗读一条
    voice_finished = Signal(str, str)  # 读完一条
    voice_dialogue_done = Signal()     # 整段对白读完
    lines_changed = Signal()           # 台词库变化（池子/UI 刷新）
    voice_refs_changed = Signal(int)   # 失效引用数量（启动扫描/删除后）
    voice_backend_msg = Signal(str)    # v2.1.1：本地后端启动/就绪结果（worker 线程 → 气泡）
    weather = Signal(str)
    weather_done = Signal()
    ai_done = Signal()
    balance_updated = Signal(float, str, float)
    balance_err = Signal()


signals = Signals()


# ---------------- 记账 ----------------
# v1.3 起账本由 pet_book.Book 管理（ledger.json / ledger_archive.json）。
# USAGE_PATH 仅为旧版 usage.json 的清理/迁移入口，不再写入。
USAGE_PATH = os.path.join(DATA_DIR, "usage.json")

# P1-6：对话记忆持久化（全量落盘，上下文只取最近 N 轮）
MEMORY_PATH = os.path.join(DATA_DIR, "memory.json")
_MEMORY_MAX = 200  # 最多保留 100 轮对话（每条一问一答）


def load_chat_memory():
    """读取 memory.json 对话历史（P0-1：实现迁至 pet_chat，保留模块级名字供全仓/tests）。"""
    return pet_chat.read_memory(MEMORY_PATH, _MEMORY_MAX, _log_error)


def save_chat_memory(hist):
    """原子落盘对话记忆（P0-1：实现迁至 pet_chat）。"""
    pet_chat.write_memory(MEMORY_PATH, hist, _MEMORY_MAX, _log_error)


def _build_ai_sys_prompt(cfg):
    """人设 → 系统提示词（含 P3-3 表情标记指令）；由 ChatService 注入使用。"""
    persona = cfg.get("ai_persona", "default")
    if persona == "custom":
        sys_prompt = (cfg.get("ai_system_prompt") or "").strip() or SYSTEM_PROMPT
    else:
        sys_prompt = PERSONA_PRESETS.get(persona, SYSTEM_PROMPT)
    return sys_prompt + "\n" + _EMOTE_INSTRUCTION

# ---------------- 主窗口 ----------------
class PetWindow(QWidget):
    # v2.0.1：帧间隔默认值以类属性暴露（pet_actions 等服务不 import 桌宠，须经实例访问）
    IDLE_FRAME_MS = IDLE_FRAME_MS
    EAT_FRAME_MS = EAT_FRAME_MS

    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.cfg = load_config()
        set_redact_key(self.cfg.get("api_key", ""))
        if self.cfg.pop("_resave", False):
            save_config(self.cfg)
        # P1-3：启动提示一次——本次加载被自动修正的坏值（修正后已重存，下次不再提示）
        if CONFIG_FIXES:
            n = len(CONFIG_FIXES)
            fixes = list(CONFIG_FIXES)  # 拷贝进闭包：1.5s 后展示时不被后续 load_config 重置串味
            detail = "、".join(fixes[:2]) + ("…" if n > 2 else "")
            QTimer.singleShot(1500, lambda: self.show_bubble(
                "配置有 %d 处坏值，已自动修正：%s" % (n, detail)))
        # ---- v1.3：角色库 / 音频库 / 记账账本 ----
        pet_resources.FRAME_MAX = int(self.cfg.get("role_frame_max", 24) or 24)  # P3-5+：帧上限用户可调
        self.role_lib = pet_resources.RoleLibrary(DATA_DIR)
        self.audio_lib = pet_resources.AudioLibrary(DATA_DIR)
        self.role_lib.set_active(self.cfg.get("role", ""))  # roles.json 与 config 同步
        try:
            self.book = pet_book.Book(DATA_DIR)
        except Exception as e:
            _log_error("book init failed: %r" % (e,))
            self.book = None
        self._usage = self.book.today_usage() if self.book is not None else 0.0
        self._preview_player = None  # mp3 试听兜底播放器（惰性构建）
        # ---- v2.1：台词库（独立台词自定义模块）+ 声音素材库（资源库内，与音效分开） ----
        self.lines_lib = pet_lines.LineService(DATA_DIR, _log_error)
        self.voice_assets = pet_resources.VoiceAssetLibrary(DATA_DIR)
        self._migrate_lines_extra()  # v2.0 的 cfg["lines_extra"] → v2.1 台词库（一次性）
        self.lines_lib.on_changed(signals.lines_changed.emit)  # 跨线程安全：只 emit，不碰控件
        self.role_lib.on_deleted(lambda rid: signals.voice_refs_changed.emit(-1))
        self.voice_assets.on_deleted(lambda sid: signals.voice_refs_changed.emit(-1))
        self.lines_pools = {}
        self._refresh_lines()

        # ---- P0-1：服务接线（Balance/Weather/Chat/Wander/Menu/AI/动作 抽至独立模块） ----
        # 服务不 import 桌宠：配置/回调/信号全部构造注入；守卫状态仍归属 PetWindow（语义不变）
        self.wander = pet_wander.WanderController(self, lambda: self.cfg, self._screen_geo, save_config)
        self.weather = pet_weather.WeatherService(self, signals, lambda: self.cfg, _log_error)
        self.chat = pet_chat.ChatService(self, signals, lambda: self.cfg, _build_ai_sys_prompt,
                                         parse_emote_tag, load_chat_memory, save_chat_memory,
                                         play_sound, _log_error, MAX_REPLY_LEN)
        self.ai = pet_ai.AIService(self, self.chat, lambda: self.cfg, save_config, set_redact_key,
                                   _remove_files, (USAGE_PATH, DATA_DIR, CONFIG_PATH, MEMORY_PATH),
                                   lambda: self.book, _log_error, DEFAULT_CONFIG)
        self.balance = pet_balance.BalanceService(self, signals, lambda: self.cfg, lambda: self.book,
                                                  play_sound, save_config, _log_error, self.ai.set_api_key)
        self.actions = pet_actions.ActionService(self, lambda: self.cfg, pick_idle_action,
                                                 SLEEP_AFTER_SECONDS)
        # v2.0：语音服务（默认关闭；片段播放注入 preview_audio）
        # v2.1：升级为配音系统——注入台词库/角色库/声音素材库，可插拔克隆后端 + 播放队列
        self.voice = pet_voice.VoiceService(DATA_DIR, lambda: self.cfg,
                                            self._play_voice_clip, _log_error,
                                            stop_clip=self._stop_voice_clip,
                                            save_cfg=save_config,
                                            lines=self.lines_lib,
                                            roles=self.role_lib,
                                            voice_assets=self.voice_assets)
        # v2.0.2：行为自定义服务（待机行为/行为序列；执行调度在本类主线程）
        self.behaviors = pet_behaviors.BehaviorService(DATA_DIR)
        # v2.0.5：闹钟服务（到点判定在主线程 QTimer 轮询）
        self.alarms = pet_alarm.AlarmService(DATA_DIR)
        self.menu_builder = pet_menu.MenuBuilder(self, save_config, is_autostart_enabled)

        self.bubble = Bubble()
        self.badge = Badge()
        self.food_tray = FoodTray()
        self.food_flyer = FoodFlyer()
        # 预热原生窗口句柄：把「创建原生窗口」这一步提前到启动期，
        # 首次 show（气泡/托盘/飞行食物）只做显示，不再产生瞬时卡顿
        for _w in (self.bubble, self.badge, self.food_tray, self.food_flyer):
            try:
                _w.winId()
            except Exception:
                pass  # 有意忽略：预热 winId 尽力而为，失败窗口仍可用
        self._dragging_food = None
        self._fetching_balance = False
        self._shown_balance = None
        self._balance_anim = None
        self._currency = "CNY"
        self._manual_pending = False
        self._pending_manual = False  # 在途自动刷新结束后需补发的手动查询
        self._closing = False  # P1-5：退出标志（在途网络请求信号守卫）
        self._weather_inflight = False
        self._ai_inflight = False
        self._save_scale_timer = None
        self._chat_history = load_chat_memory()  # P1-6：全量对话记忆（重启仍记得）
        self._history_lock = threading.Lock()  # 保护 _chat_history 的跨线程读写
        self._drag_timer = QTimer(self)
        self._drag_timer.setInterval(30)
        self._drag_timer.timeout.connect(self._drag_tick)
        self._food_shown_timer = QTimer(self)  # 托盘馋嘴错峰（可取消的单次定时器）
        self._food_shown_timer.setSingleShot(True)
        self._food_shown_timer.timeout.connect(self._food_shown_guarded)
        self.food_tray.clicked_food.connect(self._fly_food)
        self.food_tray.drag_started.connect(self._start_food_drag)
        self.food_flyer.dropped.connect(self._on_food_dropped)

        # 角色场景
        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene, self)
        self.view.setStyleSheet("background: transparent;")
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        self.view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.view.viewport().setAutoFillBackground(False)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.view.setInteractive(False)
        self.view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.view.viewport().setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.item = QGraphicsPixmapItem()
        self.scene.addItem(self.item)
        self.emote_item = QGraphicsPixmapItem()
        self.emote_item.hide()
        self.scene.addItem(self.emote_item)
        self._emote_gen = 0
        self._emote_anim = None
        self._cur_state = None  # 当前展示的表情/睡眠状态名（切形态重绘用）
        # 帧特效层（摸摸头 petpet / 撒钱 money，借参考插件动图概念）
        self.fx_item = QGraphicsPixmapItem()
        self.fx_item.hide()
        self.scene.addItem(self.fx_item)
        self.fx = pet_fx.AnimatedEmote(self.fx_item)
        # 撒钱用独立层：与摸摸头互不抢占（S2 修复）
        self.fx_money_item = QGraphicsPixmapItem()
        self.fx_money_item.hide()
        self.fx_money_item.setZValue(1)  # 撒钱在 petpet 之上
        self.scene.addItem(self.fx_money_item)
        self.fx_money = pet_fx.AnimatedEmote(self.fx_money_item)
        self.fx_money.finished.connect(lambda: setattr(self, "_fx_money_on", False))  # 只连一次
        # emote 提到最上层，避免被特效层完全遮挡（S3 修复）
        self.emote_item.setZValue(2)
        self._petting = False  # 摸摸头进行中
        self._press_dist = 0   # 本次按压累计移动距离（摸头 32px 阈值判定）
        self._fx_petpet_on = False  # petpet 特效层在播（缩放跟随用，独立于 money）
        self._fx_money_on = False   # money 特效层在播
        self._pet_watchdog_ended = False  # 摸摸头被看门狗结束（松手不戳）
        self._hold_timer = QTimer(self)  # 长按 1.5s 触发摸摸头
        self._hold_timer.setSingleShot(True)
        self._hold_timer.timeout.connect(self._start_petting)
        self._pet_max = QTimer(self)  # 摸摸头最长 15s 看门狗（release 丢失兜底）
        self._pet_max.setSingleShot(True)
        self._pet_max.timeout.connect(self._on_pet_watchdog)

        self._build_sprites()
        self.form = self.form_keys[0]
        # v2.1：用户显式选定的形态（待机/idle_form/睡眠/变身/喂食都不得覆盖）
        self._user_form = self.form_keys[0]
        # v2.1：待机系统状态（两触发 + 多动作轮换 + idle_form 展示期覆盖）
        self._idle_active = False
        self._idle_form_active = False
        self._idle_hold_timer = None         # v2.1.3：形态待机的展示期封顶（防永久吞用户形态）
        self._idle_after_full_at = None      # 触发 A 到点时刻（None=无待触发）
        self._idle_last_action = ""          # 顺序模式记上次播到哪
        self._last_idle_at = 0.0
        self._speaking_voice = False         # 正在读台词（高优先级，待机让位）
        self._invalid_refs = []              # 台词失效引用（UI 提示用）
        self._digest_timer = None
        # P1-7：各形态尺寸可能不同：窗口按较大者定（v2 角色计入形态 scale），避免溢出/不居中
        self.base_w, self.base_h = self._compute_base_size()
        self.item.setPixmap(self.sprites[self.form]["front"])
        self._using_front = True

        # ---- 阶段1：帧动画 ----
        self.anim = pet_anim.FrameAnim(self)
        assets_dir = resource_dir("assets")
        self._idle_frames = pet_anim.load_frame_set(assets_dir, "idle", 10)
        self._eat_frames = pet_anim.load_frame_set(assets_dir, "eat", 7)
        self._fx_petpet = pet_anim.load_frame_set(os.path.join(assets_dir, "fx"), "petpet", 10)
        if len(self._fx_petpet) != 10:
            _log_error("fx frames petpet incomplete: %d/10" % len(self._fx_petpet))
        self._fx_money = []  # 86 帧较大：首次撒钱时才加载（约 6.7MB）
        self._fx_money_dir = os.path.join(assets_dir, "fx")
        self._wire_anim_sets()
        self.anim.frame_changed.connect(self._on_frame_changed)
        self._build_state_pix()
        self.anim_mode = "idle"
        self._sleeping = False
        self._last_activity = time.monotonic()
        self._state_timer = QTimer(self)
        self._state_timer.setSingleShot(True)
        self._state_timer.timeout.connect(self._state_done)

        # ---- 阶段2：情绪状态机 ----
        # v2.1.2：情绪台词也走台词库（用户可增删改）；库为空/不可用时 pet_mood 回落内置常量
        self.mood = pet_mood.Mood(self, line_picker=self._mood_line)
        self.mood.state.connect(self._on_mood_state)
        self.mood.bubble.connect(self._mood_bubble)  # busy 门控：喂食/跳跃中不覆盖互动气泡
        self.mood.emote.connect(self._mood_emote)
        # 首次调皮事件推迟到随机 45~90 秒后，避免刚启动就坏笑
        self.mood.prime_mischief()
        self.mood_timer = QTimer(self)
        self.mood_timer.setInterval(1000)
        self.mood_timer.timeout.connect(self._mood_tick)
        self.mood_timer.start()

        # v2.0.5：闹钟轮询（15s 一拍，秒级精度足够；到点判定纯函数）
        self._alarm_timer = QTimer(self)
        self._alarm_timer.setInterval(15000)
        self._alarm_timer.timeout.connect(self._alarm_tick)
        self._alarm_timer.start()

        # ---- 阶段3：音频（参考项目 WAV + 合成回退）----
        pet_audio.init(os.path.join(resource_dir("assets"), "sounds"))
        self._apply_sound_group()  # v1.3：自定义音效组

        self.scale = 1.0
        self.squash_x = 1.0
        self.squash_y = 1.0
        self.flip = 1  # 1 = 朝左，-1 = 朝右
        self.busy = False
        self.walk_phase = 0
        self._walk_interval = WALK_INTERVAL_MS
        self._wander_target = None
        self._click_composite = None  # P3-1：点击穿透命中画布（关闭/未启用时 None）
        self._click_cache_key = None
        self._tween_anim = None
        self._tween_finish_cb = None  # P1-2：当前动画的收尾回调（被顶替时手动执行）
        self._behavior_seq = None     # v2.0.2：在途行为序列（切角色/退出时取消）
        self._transform_timer = None  # v2.0.2：变身回切定时器
        self._transform_home = None   # v2.0.2：变身前的形态（回切目标）
        self._sleep_home = None       # v2.0.2：因睡觉形态切换前的原形态（醒来回切）
        self._mem_epoch = 0  # P1-6：记忆代次（清理记忆后 +1，在途 AI 回复据此判断是否入记忆）
        self._fly_timer = None
        self._anchor_bottom = False
        # ---- P1-手感：甩抛物理（默认关闭，行为与旧版逐像素一致） ----
        self._flying = False        # 飞行中（不响应戳戳/摸摸头/贴边）
        self._flight_vx = 0.0
        self._flight_vy = 0.0
        self._flight_last = 0.0
        self._land_squash = 1.0
        self._proc_offset_y = 0     # v2.0.1：程序化「点头」动作竖向位移（恒 0 除非播放中）
        self._drag_samples = []     # [(t, x, y)] 拖拽轨迹采样（松手估速，只留最近 200ms）
        self._spring_vx = 0.0       # 过阻尼弹簧跟手状态（K=200/C=30）
        self._spring_vy = 0.0
        self._last_drag_t = None
        self._flight_timer = QTimer(self)
        self._flight_timer.setInterval(16)
        self._flight_timer.timeout.connect(self._flight_tick)

        scale = self.cfg.get("scale", 1.0)
        if not os.path.exists(CONFIG_PATH):
            try:
                scr = QApplication.primaryScreen()
                if scr is not None:
                    scale = max(0.25, min(1.0, round(scr.availableGeometry().height() * 0.18 / self.base_h, 2)))
            except Exception:
                pass  # 有意忽略：无屏/首屏不可用时按默认缩放
        self.set_scale(scale)
        self.cfg["scale"] = self.scale
        self._play_idle()

        # 初始位置：主屏右下（P1-4：SCREEN_EDGE_MARGIN 常量；无屏极端场景留原地）
        try:
            scr = QApplication.primaryScreen()
            if scr is not None:
                ag = scr.availableGeometry()
                self.move(ag.right() - self.width() - SCREEN_EDGE_MARGIN_X,
                          ag.bottom() - self.height() - SCREEN_EDGE_MARGIN_Y)
        except Exception:
            pass  # 有意忽略：无屏极端场景留原地

        # 拖动状态
        self._drag_offset = None
        self._press_global = None
        self._moved = False
        self._was_walking = False

        # 菜单项引用（用于同步勾选）
        self._follow_act = None
        self._wander_act = None
        self._top_act = None
        self._ai_act = None
        self._autostart_act = None
        self._autostart_busy = False

        # 定时器
        self.idle_timer = QTimer(self)
        self.idle_timer.timeout.connect(self.actions.idle_tick)
        self.idle_timer.start(15000)

        self.walk_timer = QTimer(self)
        self.walk_timer.timeout.connect(self.wander.tick)

        self._last_cpu = 0.0
        self.cpu_timer = QTimer(self)
        self.cpu_timer.timeout.connect(self.actions.cpu_tick)
        self.cpu_timer.start(6000)
        try:
            psutil.cpu_percent(interval=None)
        except Exception:
            pass  # 有意忽略：首次采样失败不影响后续定时采样

        # 跨线程信号
        signals.weather.connect(self.show_bubble)
        signals.reply.connect(self.show_bubble)
        signals.reply.connect(self._on_reply_voice)  # v2.0：AI 回复语音（默认关闭）
        signals.voice_play.connect(self.preview_audio)  # v2.0：主线程播放合成/片段
        signals.voice_error.connect(self.show_bubble)  # v2.0：合成失败原因主线程气泡
        # v2.1：语言系统（配音）回调——worker 线程 emit → 主线程槽（不跨线程碰控件）
        self.voice.on_speaking_started(signals.voice_started.emit)
        self.voice.on_speaking_finished(signals.voice_finished.emit)
        self.voice.on_dialogue_finished(signals.voice_dialogue_done.emit)
        self.voice.on_error(signals.voice_error.emit)
        signals.voice_started.connect(self._on_voice_started)
        signals.voice_finished.connect(self._on_voice_finished)
        signals.voice_dialogue_done.connect(self._on_voice_dialogue_done)
        signals.lines_changed.connect(self._on_lines_changed)
        signals.voice_refs_changed.connect(lambda n: self._scan_invalid_refs())
        signals.voice_backend_msg.connect(self.show_bubble)
        # v2.1.1：本地后端**默认不自动启动**（和以前一样，用户自己开）；勾了开关才拉起
        QTimer.singleShot(4000, self, lambda: self._auto_start_voice_backend())
        # v2.1：启动扫描一次失效引用（有失效就气泡提示，绝不静默）
        QTimer.singleShot(4000, self, lambda: self._scan_invalid_refs())
        signals.ai_emote.connect(self.chat.on_ai_emote)  # P3-3：AI 回复带出的表情
        signals.reply_ok.connect(self.chat.on_reply_ok)  # 任务完成音回主线程播
        signals.balance_updated.connect(self.balance.on_updated)
        signals.balance_err.connect(self.balance.on_err)
        signals.weather_done.connect(self.weather.on_done)
        signals.ai_done.connect(lambda: setattr(self, "_ai_inflight", False))
        self.bubble.clicked.connect(self._cycle_line)

        self.show()
        if self.cfg.get("badge") and self.cfg.get("api_key"):
            self._update_badge()
            self.badge.show()
            self._position_badge()
            self.balance.start()
        self._show_state("laugh", 3200)  # 开场第一个表情：开心大笑
        # v2.1：开场台词也来自台词库（用户可增删改「开场」类别），空池兜底
        self._say_line(self._pick_line(("startup",), fallback="绳匠，你来啦！"))

        # ---- 托盘图标（窗口被遮挡/找不到时的兜底入口）----
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(QIcon(self.sprites[self.form_keys[0]]["front"]))
        tray_menu = QMenu()
        show_act = tray_menu.addAction("🐟 显示桌宠")
        show_act.triggered.connect(self._show_pet)
        tray_menu.addSeparator()
        quit_act = tray_menu.addAction("⏹ 退出")
        quit_act.triggered.connect(self._quit)
        self.tray.setContextMenu(tray_menu)
        self.tray.setToolTip("大肥鱼桌宠 · 喜欢的，就咬住不放~")
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

        # v1.3：有 Key 且开了 AI 对话（未开挂件）时，启动后补一次余额观测刷新账本基线
        if self.cfg.get("api_key") and self.cfg.get("ai_enabled") and not self.cfg.get("badge"):
            QTimer.singleShot(2500, lambda: self.balance.refresh(manual=False))
        # B3：启动 3s 后预加载撒钱帧（主线程一次性 ~100ms），避免首次查余额瞬间卡顿
        QTimer.singleShot(3000, self._preload_money_fx)

    def _preload_money_fx(self):
        """预热撒钱帧集（86 帧约 6.7MB）：在启动空闲期加载，首次撒钱不再卡。"""
        try:
            if not self._fx_money:
                self._fx_money = pet_anim.load_frame_set(self._fx_money_dir, "money", 86)
        except Exception:
            pass  # 有意忽略：预加载失败不碍事，撒钱时 _fx_money 为空会走完整检查并记日志

    # ---------- 角色加载 ----------
    def _load_img(self, names):
        for name in names:
            p = resource_path(name)
            if os.path.exists(p):
                pix = QPixmap(p)
                if not pix.isNull():
                    return pix
        return None

    def _fallback_pix(self):
        pix = QPixmap(200, 200)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor("#ffb347"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(20, 40, 160, 120)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(60, 80, 26, 26)
        p.drawEllipse(120, 80, 26, 26)
        p.setBrush(QColor("#333333"))
        p.drawEllipse(70, 90, 12, 12)
        p.drawEllipse(130, 90, 12, 12)
        p.end()
        return pix

    def _build_form_meta(self):
        """形态元数据：键列表 + 显示名（默认角色常态/吃饱；自定义角色来自角色记录）。"""
        if self._custom_role:
            metas = self.role_lib.form_metas(self.cfg.get("role", ""))
            if not metas:
                metas = [{"name": "常态"}]
            self.form_keys = ["f%d" % i for i in range(len(metas))]
            self.form_names = {k: (m.get("name") or "形态%d" % (i + 1))
                               for i, (k, m) in enumerate(zip(self.form_keys, metas))}
        else:
            self.form_keys = ["normal", "full"]
            self.form_names = {"normal": "常态", "full": "吃饱"}

    # ---------- P1-7：形态渲染参数 / 动画查表 ----------
    def _role_render_params(self):
        """逐形态渲染参数（与 form_keys 对齐）：[{"anchor": (x, y), "scale": s|None,
        "offset": (x, y)}, ...]；纯计算用 pet_resources.form_render 同一口径。
        仅新结构（v2）角色调用。"""
        if not self._custom_role or not self.role_lib:
            return None
        rid = self.cfg.get("role", "")
        role = self.role_lib.get(rid) or {}
        out = []
        for i in range(len(self._role_metas or [])):
            out.append(pet_resources.form_render(role, i))
        return out

    def _cur_form_anim(self):
        """P1-7：当前形态的动画元信息 {"idle": [...], "eat": [...], "interval_ms": N|None}；
        默认角色/无动画返回 {}。"""
        if not self._custom_role:
            return {}
        idx = self.form_keys.index(self.form) if self.form in self.form_keys else 0
        anims = self._role_anims or []
        return anims[idx] if 0 <= idx < len(anims) else {}

    def _cur_procs(self):
        """v2.0.1：当前形态的程序化合成动作 {name: {kind, amp, period_ms}}。"""
        if not self._custom_role:
            return {}
        rid = self.cfg.get("role", "")
        idx = self.form_keys.index(self.form) if self.form in self.form_keys else 0
        return self.role_lib.procs(rid, idx)

    def custom_actions(self):
        """v2.0.1：当前形态的命名动作清单 [(name, kind)]（frames/proc），供菜单/行为系统引用。"""
        if not self._custom_role:
            return []
        rid = self.cfg.get("role", "")
        idx = self.form_keys.index(self.form) if self.form in self.form_keys else 0
        return self.role_lib.custom_actions(rid, idx)

    def _play_proc(self, name, spec):
        """v2.0.1：程序化合成动作——用角色自身贴图按参数振荡（呼吸/摇摆/点头）。"""
        import math as _math
        # 统一走归一化：默认值/钳制单一来源（DEFAULT_PROC_PARAMS/PROC_AMP_BOUNDS），
        # 非法 spec 归一化为空 → 不播（菜单/行为系统传入的都是已归一化数据，此为兜底）
        spec = pet_resources._norm_procs({str(name): spec or {}}).get(str(name))
        if not spec:
            return
        kind = spec["kind"]
        amp = float(spec["amp"])
        period = float(spec["period_ms"])
        cycles = 2  # 播 2 个周期

        def _onv(v):
            ph = _math.sin(v * cycles * 2 * _math.pi)
            if kind == "nod":
                self._proc_offset_y = int(round(amp * ph))
            elif kind == "sway":
                self.squash_x = 1.0 + amp * ph
                self.squash_y = 1.0 - amp * 0.6 * ph
            else:  # breathe
                self.squash_x = 1.0 + amp * ph
                self.squash_y = 1.0 + amp * ph
            self._apply_transform()

        def _done():
            self.squash_x = 1.0
            self.squash_y = 1.0
            self._proc_offset_y = 0
            self._apply_transform()
            # 吃帧/其它互动进行中不回待机（避免 anim.play('idle') 内部 stop()
            # 静默丢弃 _eat_done 等收尾回调 → busy 永久卡死；它们的收尾自会回待机）
            if self.anim_mode != "eat" and not self.busy:
                self._play_idle()  # v2.0.1：合成动作播完回待机（与命名帧动作 loops=1 同语义）

        self.anim_mode = "state"
        self._state_timer.stop()
        self._run_anim(int(period * cycles), _onv, on_finished=_done)

    # ---------- v2.0.2：行为系统与断点#12 ----------
    def _action_exists(self, name):
        """行为引用查表：内建分支 / 帧集动作 / 合成动作（供行为执行前校验，防静默 no-op）。"""
        return (name in ("jump", "emote", "none")
                or name in (self.anim._sets or {})
                or name in self._cur_procs())

    def _form_role_flags(self):
        """当前角色的逐形态角色标记（与 form_keys 对齐）；默认角色返回 []。"""
        if not self._custom_role:
            return []
        return self.role_lib.form_role_flags(self.cfg.get("role", ""))

    def _flag_forms(self, flag):
        """带某标记（sleep_form/transform_form/no_feed）的形态键列表。"""
        out = []
        for _k, _f in zip(self.form_keys, self._form_role_flags()):
            if _f.get(flag):
                out.append(_k)
        return out

    @property
    def has_transform_form(self):
        """v2.0.2：当前角色是否配置了变身形态（菜单「变身」入口显示条件）。"""
        return bool(self._flag_forms("transform_form"))

    def _form_no_feed(self):
        """当前形态是否标记「不参与喂食」。"""
        _idx = self.form_keys.index(self.form) if self.form in self.form_keys else 0
        _flags = self._form_role_flags()
        return bool(_flags and 0 <= _idx < len(_flags) and _flags[_idx].get("no_feed"))

    def _sleep_form_key(self):
        """睡觉形态键（无标记返回 None=现状）。"""
        _sf = self._flag_forms("sleep_form")
        return _sf[0] if _sf else None

    def _cancel_transform(self):
        """停掉变身回切定时器并复位状态（幂等）。"""
        if self._transform_timer is not None:
            try:
                self._transform_timer.stop()
                self._transform_timer.deleteLater()
            except RuntimeError:
                pass  # 有意忽略：定时器可能已被销毁（幂等清理）
            self._transform_timer = None
        self._transform_home = None

    def _do_transform(self):
        """v2.0.2 断点#12：切到变身形态，transform_seconds 后自动回原形态；
        已在变身形态时再点一次提前变回来。"""
        if self.busy or self._petting or self._sleeping:
            return  # 互动/睡眠中不切形态（睡眠中想变先唤醒）
        _tf = self._flag_forms("transform_form")
        if not _tf:
            return
        _target = _tf[0]
        _d_secs = pet_behaviors.DEFAULT_BEHAVIOR_CFG["transform_seconds"]
        _uf = getattr(self, "_user_form", "") or self.form_keys[0]
        if self.form == _target:
            _home = self._transform_home
            self._cancel_transform()
            if _home and _home in self.form_keys:
                self._set_form(_home, display_only=True)
            elif self.form != _uf:
                # 手动停在变身形态且无回切目标：回用户选定形态（与喂食消化回位同语义）
                self._set_form(_uf, display_only=True)
            self.show_bubble("变回来啦~")
            return
        self._cancel_transform()
        # v2.1.3 修复：**先**打断待机（含结束 idle_form 展示期、恢复用户形态），再记
        # _transform_home。顺序反了会出两个 bug：①变身期间待机形态覆盖变身形态；
        # ②_transform_home 记成待机形态 → 变身结束后"回"到待机形态，用户选定形态被吞掉。
        self._touch_activity()  # 内部 _idle_interrupt：待机让位并恢复用户形态
        self._transform_home = self.form
        self._set_form(_target, cancel_transform=False, display_only=True)  # 变身是临时展示
        self.show_bubble("变身！")
        try:
            _secs = int(self.cfg.get("transform_seconds", _d_secs) or _d_secs)
        except (TypeError, ValueError):
            _secs = _d_secs  # 有意忽略：坏值回默认（normalize 已兜底，此处防御直改 cfg）
        self._transform_timer = QTimer(self)
        self._transform_timer.setSingleShot(True)
        self._transform_timer.timeout.connect(self._end_transform)
        self._transform_timer.start(max(pet_behaviors.TRANSFORM_SECS_MIN,
                                        min(pet_behaviors.TRANSFORM_SECS_MAX, _secs)) * 1000)

    def _end_transform(self):
        _home = self._transform_home  # 先取回切目标（_cancel_transform 会清空）
        self._cancel_transform()
        _uf = getattr(self, "_user_form", "") or self.form_keys[0]
        _back = _home if (_home and _home in self.form_keys) else _uf
        if self.form != _back:
            self._set_form(_back, cancel_transform=False, display_only=True)

    # ---------- v2.1：待机系统（两触发 + 分层优先级 + 多动作 + idle_form） ----------
    def _idle_cfg(self):
        """归一化后的待机配置（默认值/钳制单一来源 pet_behaviors）。"""
        return self.behaviors.idle_config(lambda: self.cfg)

    def _idle_ready(self):
        """待机能否开始：不忙/不摸头/没睡/**没在变身**/处于待机表现/没在读台词/没有待机动作在播。

        v2.1.3 修复：此前漏判"变身进行中"，导致变身期间待机会把 idle_form 画上去
        （表现为"待机吞了变身形态"，且变身结束时回切到的是待机形态）。"""
        if self.busy or self._petting or self._sleeping:
            return False
        if getattr(self, "_transform_home", None) is not None:
            return False  # 变身进行中：这是更高优先级的展示，待机必须让位
        if getattr(self, "_speaking_voice", False) or self.voice.is_speaking():
            return False
        if self.anim_mode not in ("idle", "form_idle"):
            return False
        return not self._idle_active

    def maybe_idle_behavior(self):
        """待机轮询（idle_tick 每拍调用）。两个触发来源共用同一套动作与形态规则：

        触发 A：吃饱形态结束后 idle_delay_after_full 秒（原「吃饱后卖萌」语义，保留）；
        触发 B：无任何交互满 idle_trigger_delay 秒。
        任一触发后重置另一个；待机进行中不重复触发；被打断后两触发都重新计时。"""
        now = time.monotonic()
        # 触发 A（到点即检查；条件不满足则作废本次，避免无限等待）
        if self._idle_after_full_at is not None:
            if now >= self._idle_after_full_at:
                if self._idle_ready():
                    self._start_idle("full")
                self._idle_after_full_at = None
            return
        # 触发 B
        cfg = self._idle_cfg()
        delay = int(cfg.get("idle_trigger_delay") or 0)
        if delay <= 0 or now - self._last_activity < delay:
            return
        if now - getattr(self, "_last_idle_at", 0.0) < delay:
            return
        if not self._idle_ready():
            return
        self._start_idle("idle")

    def _start_idle(self, source):
        """开始一次待机：选动作（按模式）→ 切 idle_form（展示期）→ 播行为序列。"""
        cfg = self._idle_cfg()
        self._idle_after_full_at = None  # 两触发互斥：触发即消费
        self._last_idle_at = time.monotonic()
        b, aid, err = self.behaviors.idle_pick(lambda: self.cfg, self._idle_last_action)
        if err:
            # 引用失效不静默，但同一原因最多 60s 提示一次（此前每拍都弹，气泡刷屏）
            _now = time.monotonic()
            if _now - getattr(self, "_idle_err_at", 0.0) > 60:
                self._idle_err_at = _now
                self.show_bubble(err)
        if aid:
            self._idle_last_action = aid
        form = str(cfg.get("idle_form") or "")
        if form and form in self.form_keys and form != self.form:
            self._set_form(form, cancel_transform=False, display_only=True)
            self._idle_form_active = True
        if b is None:
            # 没有可播动作：只做「形态待机」。v2.1.3 修复：必须给展示期封顶——
            # 此前直接 return，_idle_form_active 永远挂着、_idle_end 永不被调用，
            # 表现为"待机把用户形态永久吞掉"（用户实测反馈）。
            if self._idle_form_active:
                self._start_idle_hold()
            return
        self._idle_active = True
        self._run_behavior(b["id"], as_idle=True)

    def _stop_idle_hold(self):
        """停掉形态待机的展示期定时器（幂等）。"""
        if getattr(self, "_idle_hold_timer", None) is not None:
            try:
                self._idle_hold_timer.stop()
                self._idle_hold_timer.deleteLater()
            except RuntimeError:
                pass  # 有意忽略：定时器可能已被销毁
            self._idle_hold_timer = None

    def _start_idle_hold(self):
        """形态待机（没有动作可播）的展示期封顶：到期自动 _idle_end 回用户形态。"""
        try:
            _secs = int(self._idle_cfg().get("idle_form_hold") or IDLE_FORM_HOLD_SECS)
        except (TypeError, ValueError):
            _secs = IDLE_FORM_HOLD_SECS  # 有意忽略：坏值回默认
        if self._idle_hold_timer is not None:
            self._idle_hold_timer.stop()
            try:
                self._idle_hold_timer.deleteLater()
            except RuntimeError:
                pass  # 有意忽略：定时器可能已被销毁（幂等清理）
        self._idle_hold_timer = QTimer(self)
        self._idle_hold_timer.setSingleShot(True)
        self._idle_hold_timer.timeout.connect(self._idle_end)
        self._idle_hold_timer.start(max(2, min(60, _secs)) * 1000)

    def _idle_end(self):
        """待机动作自然播完：恢复用户选定形态，允许下一次触发。

        M5 修复：待机动作里带 sleep 步骤时（已入睡）不复位形态——否则会"睡着却显示
        用户形态"，醒来也回不到睡眠形态。"""
        self._idle_active = False
        self._stop_idle_hold()
        if self._sleeping:
            self._idle_form_active = False  # 睡眠形态接管，待机形态覆盖就此结束
            return
        self._restore_user_form()

    def _idle_interrupt(self, why=""):
        """高优先级动作/交互（说话、拖拽、喂食、摸头、手动切形态…）打断待机。

        待机是最低优先级：立即停序列、恢复用户形态，两个触发来源都重新计时。"""
        was_active = bool(self._idle_active) or bool(getattr(self, "_idle_form_active", False))
        self._idle_active = False
        self._stop_idle_hold()
        self._idle_after_full_at = None
        if getattr(self, "_behavior_is_idle", False) and self._behavior_seq is not None:
            self._behavior_gen = getattr(self, "_behavior_gen", 0) + 1  # 顶替旧链（挂起 singleShot 失效）
            self._behavior_seq = None
            self._behavior_is_idle = False
        cfg = self._idle_cfg()
        if not cfg.get("idle_resume_on_interrupt"):
            self._idle_last_action = ""  # 未消费：下次重新选（顺序模式从头/继续由 last 决定）
        if was_active:
            self._restore_user_form()
        self._last_idle_at = time.monotonic()

    def _restore_user_form(self):
        """待机结束/被打断：回到用户选定形态（idle_form 只做展示期覆盖）。

        展示期（吃帧/睡眠/变身）不复位：那些形态是更高优先级动作主动切的。"""
        if not getattr(self, "_idle_form_active", False):
            return
        if self.busy or self._sleeping or getattr(self, "_transform_home", None) is not None:
            return
        self._idle_form_active = False
        uf = getattr(self, "_user_form", "") or self.form_keys[0]
        if uf in self.sprites and self.form != uf:
            self._set_form(uf, cancel_transform=False, display_only=True)

    def set_user_form(self, form):
        """用户显式选择形态（菜单）：记为 user_selected_form，待机不得覆盖它。"""
        if form not in self.sprites:
            return
        self._user_form = form
        self._idle_interrupt("user_form")
        self._set_form(form)

    def _touch_activity(self):
        """记一次「用户交互」：重置无交互计时 + 打断待机（两触发重新计时）。"""
        self._last_activity = time.monotonic()
        self._idle_interrupt("activity")

    def _run_behavior(self, bid, as_idle=False):
        """v2.0.2：启动行为序列（主线程、QTimer 逐步骤调度；不设 busy）。

        序列带代次 token：重触发时旧序列挂起的 singleShot 触发后因代次不符立即退出，
        不会并行驱动新序列（防 wait 节奏错乱/步骤重叠）。
        v2.1：as_idle=True 时按待机规则执行（忽略 form 步骤、结束后回调 _idle_end）。"""
        _b = self.behaviors.get(bid)
        if _b is None or not _b.get("steps"):
            if as_idle:
                self._idle_end()
            return
        _gen = getattr(self, "_behavior_gen", 0) + 1
        self._behavior_gen = _gen
        self._behavior_is_idle = bool(as_idle)
        self._behavior_seq = {"steps": list(_b["steps"]), "idx": 0, "gen": _gen,
                              "as_idle": bool(as_idle)}
        self._behavior_step(_gen)

    def _behavior_step(self, gen):
        """行为序列的下一步（wait 控制步进；喂食/戳戳忙碌时跳过互斥步骤）。"""
        _seq = self._behavior_seq
        if _seq is None or _seq.get("gen") != gen:
            return  # 序列已被新触发顶替：旧链静默退出（幂等）
        if _seq["idx"] >= len(_seq["steps"]):
            _was_idle = bool(_seq.get("as_idle"))
            self._behavior_seq = None
            self._behavior_is_idle = False
            if _was_idle:
                self._idle_end()  # 待机动作播完：恢复用户形态
            return
        _st = _seq["steps"][_seq["idx"]]
        _act = _st["act"]
        _as_idle = bool(_seq.get("as_idle"))
        if _act == "play_action":
            # 与 play_action 同款门控：busy/摸摸头时有意跳过（互斥语义，非静默失败）
            if not (self.busy or self._petting):
                # 红线：引用的动作已不存在时不静默跳过，气泡明示
                if self._action_exists(_st["name"]):
                    self.actions.play_action(_st["name"])
                else:
                    self.show_bubble("动作「%s」不见了，跳过~" % _st["name"])
        elif _act == "say":
            self.show_bubble(_st["text"])
        elif _act == "voice":
            self.voice.play_event(_st["event"])
        elif _act == "emote":
            self._show_emote(_st["kind"])
        elif _act == "form":
            # v2.1：待机行为里的 form 步骤按规格忽略（形态以 idle_form / 用户选定形态为准）；
            # 用户手动播放的行为仍允许切形态（手动编排可能就是要切形态）。
            if _as_idle:
                pass
            elif not (self.busy or self._petting):
                if _st["name"] in self.form_keys:
                    self._stop_tween()  # 与合成动作互斥：先停振荡再切形态
                    self.set_user_form(_st["name"])  # 用户编排的切形态=用户意图，记为用户形态
                else:
                    self.show_bubble("形态「%s」不存在，跳过~" % _st["name"])
        elif _act == "sleep":
            if not (self.busy or self._petting):
                self._stop_tween()
                self._show_sleep()
                # sleep 为终止步：入睡中继续播后续步骤会被 _wake 回切撤销、语义混乱
                self._behavior_seq = None
                self._behavior_is_idle = False
                self._idle_active = False
                if _as_idle:
                    self._idle_end()  # 已入睡：_idle_end 内部会跳过形态复位（M5）
                return
        elif _act == "speak_line":
            # v2.1：读台词交给语言系统（本模块不 import pet_voice，经 PetWindow 转交）
            self._behavior_speak_line(_st.get("line_id") or "")
        elif _act == "speak_dialogue":
            self._behavior_speak_dialogue(_st.get("dialogue_id") or "")
        _wait = _st.get("ms", 500) if _act == "wait" else 400
        _seq["idx"] += 1
        QTimer.singleShot(_wait, self, lambda: self._behavior_step(gen))

    def _behavior_speak_line(self, line_id):
        """v2.1：行为步骤 speak_line → 语言系统朗读（引用失效时明确提示，不静默）。"""
        if not line_id:
            return
        self._idle_speak_self = line_id if getattr(self, "_behavior_is_idle", False) else ""
        ok, err = self.voice.speak_line(line_id)
        self._idle_speak_self = ""
        if not ok:
            self.show_bubble(err or "这条台词读不了")

    def _behavior_speak_dialogue(self, dialogue_id):
        """v2.1：行为步骤 speak_dialogue → 语言系统按顺序朗读整段对白。"""
        if not dialogue_id:
            return
        ok, err = self.voice.speak_dialogue(dialogue_id)
        if not ok:
            self.show_bubble(err or "这段对白读不了")

    def _open_behavior_dialog(self):
        """v2.0.2：行为设置对话框（菜单入口）。"""
        try:
            pet_dialogs.BehaviorDialog(self, self.behaviors, save_config).exec()
        except Exception as e:
            _log_error("behavior dialog: %r" % (e,))

    def _open_idle_dialog(self):
        """v2.1：待机设置对话框（两触发/待机形态/待机动作列表/播放模式）。"""
        try:
            pet_dialogs.IdleDialog(self).exec()
        except Exception as e:
            _log_error("idle dialog: %r" % (e,))

    def apply_idle_settings(self, data=None):
        """v2.1：待机设置回调（归一化后落盘；立即生效，不影响正在进行的动作）。"""
        if not isinstance(data, dict):
            return False
        norm = pet_behaviors.normalize_idle_cfg({**self.cfg, **data})
        self.cfg["idle_trigger_delay"] = norm["idle_trigger_delay"]
        self.cfg["idle_delay_after_full"] = norm["idle_delay_after_full"]
        self.cfg["idle_form"] = norm["idle_form"]
        self.cfg["idle_actions"] = norm["idle_actions"]
        self.cfg["idle_play_mode"] = norm["idle_play_mode"]
        self.cfg["idle_resume_on_interrupt"] = norm["idle_resume_on_interrupt"]
        self.cfg["idle_behavior_seconds"] = norm["idle_trigger_delay"]  # 旧键同步（兼容旧版读取）
        # M3 修复：迁移已完成，清掉旧键——否则 normalize 每次都把旧行为补回列表，
        # 用户"移除待机动作"会复活（也关不掉）。
        self.cfg["idle_behavior"] = ""
        save_config(self.cfg)
        n = len([a for a in norm["idle_actions"] if a.get("enabled")])
        self.show_bubble("待机设置已更新~（%d 条动作，%s）" % (
            n, pet_behaviors.IDLE_MODE_LABELS.get(norm["idle_play_mode"], "")))
        return True

    # ---------- v2.0.5：闹钟系统 ----------
    def _alarm_tick(self):
        """闹钟轮询：到点 → 记已响 + 气泡 + 铃声（自定义优先，缺省系统音）+ 语音提醒。"""
        try:
            due = pet_alarm.due_alarms(self.alarms.list(), pet_alarm.now_hhmm(),
                                       pet_alarm.today_str())
        except Exception as e:
            _log_error("alarm tick: %r" % (e,))  # 有意忽略：判定失败本轮跳过，下拍重试
            return
        for _a, _t in due:
            # per-alarm 兜底：单条闹钟的任何异常不得延后剩余闹钟
            try:
                self.alarms.mark_fired(_a["id"], pet_alarm.today_str())
                _label = _a.get("label") or "闹钟"
                self.show_bubble("⏰ %s 到点啦！" % _label)
                _rt = self.alarms.ringtone_path(_a.get("ringtone") or "")
                # 铃声与默认音统一受「音效」开关控制（关闭=只气泡+语音，不响铃）
                if _rt and self.cfg.get("sound", True):
                    if self.preview_audio(_rt) is not True:
                        _log_error("alarm ringtone play failed: %s" % _a.get("ringtone"))
                elif self.cfg.get("sound", True):
                    play_sound("coin")  # 缺省提示音
                # 语音提醒：语音系统开启且合成方式非 off 时朗读标签（speak 内部自检）
                self.voice.speak("⏰ %s，时间到了" % _label,
                                 on_error=signals.voice_error.emit)
            except Exception as e:
                _log_error("alarm fire: %r" % (e,))  # 有意忽略：单条失败不拖累后续闹钟

    def _open_alarm_dialog(self):
        """v2.0.5：闹钟设置对话框（菜单入口）。"""
        try:
            pet_dialogs.AlarmDialog(self, self.alarms).exec()
        except Exception as e:
            _log_error("alarm dialog: %r" % (e,))  # 有意忽略：对话框失败只记日志不崩主程序

    # ---------- v2.0.3：角色导出/导入（分享包） ----------
    def _export_role(self):
        """导出当前自定义角色（素材+行为+可分享配置）为 .dfypet.zip。"""
        if not self._custom_role:
            self.show_bubble("默认角色不能导出，先在「角色」里选一个自定义角色吧~")
            return
        _path, _f = QFileDialog.getSaveFileName(
            self, "导出角色包", os.path.join(DATA_DIR, "角色包.dfypet.zip"),
            "角色包 (*.dfypet.zip)")
        if not _path:
            return
        # v2.1：参考音默认不打包，用户可勾选要带上的声音素材（体积/隐私考虑）
        _voice_ids = None
        if self.voice_assets.assets():
            _voice_ids = pet_dialogs.pick_voice_assets(self)
            if _voice_ids is None:
                return  # 用户取消整个导出
        _ok, _err = pet_export.export_bundle(
            self.role_lib, self.behaviors, self.cfg, _path,
            alarms_getter=self.alarms.list,
            # v2.1：只带**用户写的**台词（内置台词对面也有，避免每包重复一份语料）
            lines_getter=lambda: [x for x in self.lines_lib.lines() if not x.get("builtin")],
            dialogues_getter=self.lines_lib.dialogues,  # v2.1：对白随包
            voice_assets_getter=self._voice_asset_files,
            include_voice_ids=_voice_ids)
        if _ok:
            _extra = ("（含 %d 个参考音）" % len(_voice_ids)) if _voice_ids else ""
            self.show_bubble("角色包已导出%s，可以分享给朋友啦~" % _extra)
        else:
            self.show_bubble("导出失败：%s" % _err)

    def _voice_asset_files(self):
        """v2.1：声音素材（含可打包的绝对路径），供导出勾选用。"""
        out = []
        for a in self.voice_assets.assets():
            p = self.voice_assets.asset_path(a["id"])
            if p:
                item = dict(a)
                item["path"] = p
                out.append(item)
        return out

    def _apply_imported_voice_assets(self, items, extract_dir):
        """v2.1：导入包内声音素材 → 返回 {旧槽位: 新槽位} 映射。"""
        mapping = {}
        for a in (items or []):
            if not isinstance(a, dict):
                continue
            _old = str(a.get("id") or "")
            _base = os.path.basename(str(a.get("file") or ""))
            _src = os.path.join(extract_dir or "", _base)
            if not _old or not os.path.isfile(_src):
                continue
            _new, _err = self.voice_assets.import_file(_src, a.get("name") or _old)
            if _new is None:
                _log_error("import voice asset failed: %s" % _err)
                continue
            mapping[_old] = _new["id"]
        return mapping

    def _apply_imported_lines(self, lines, dialogues, maps):
        """v2.1：导入包内台词与对白（id 换新、槽位按映射重指、对白引用同步重写）。"""
        warnings = []
        vmap = (maps or {}).get("voice") or {}
        rmap = (maps or {}).get("role") or {}
        id_map = {}
        dlg_map = {}
        for ln in (lines or []):
            if not isinstance(ln, dict):
                continue
            _text = str(ln.get("text") or "").strip()
            if not _text:
                continue
            _role = rmap.get(str(ln.get("role_slot") or ""), ln.get("role_slot") or "")
            _voice = vmap.get(str(ln.get("voice_slot") or ""), ln.get("voice_slot") or "")
            if ln.get("voice_slot") and not vmap.get(str(ln.get("voice_slot"))):
                warnings.append("台词「%s」的声音不在包内，已改为跟随角色绑定"
                                % _text[:10])
                _voice = ""
            if ln.get("role_slot") and not rmap.get(str(ln.get("role_slot"))):
                _role = ""  # 角色不在包内：清空引用（不静默指向别的角色）
            _new, _err = self.lines_lib.add(_text, ln.get("category") or "idle",
                                            _role or None, _voice or None,
                                            food=ln.get("food") or "")  # L2：喂食归属一并带过来
            if _new is None:
                warnings.append("台词未导入：%s" % _err)
                continue
            id_map[str(ln.get("id") or "")] = _new["id"]
        if isinstance(dialogues, list):
            for d in dialogues:
                if not isinstance(d, dict):
                    continue
                # 包内对白可能同时引用"用户台词"与"内置台词"：用户台词按新 id 映射，
                # 内置台词 id 在本地同样存在（种子 id 稳定）→ 原样保留，其余丢弃
                _ids = []
                for _x in (d.get("line_ids") or []):
                    _k = str(_x)
                    _mapped = id_map.get(_k)
                    if _mapped:
                        _ids.append(_mapped)
                    elif self.lines_lib.get(_k) is not None:
                        _ids.append(_k)
                if not _ids:
                    continue
                _nd, _err = self.lines_lib.add_dialogue(d.get("name") or "导入对白", _ids)
                if _nd is None:
                    warnings.append("对白未导入：%s" % _err)
                else:
                    dlg_map[str(d.get("id") or "")] = _nd["id"]
        # M6 修复：把包内**行为**里的读台词/读对白步骤重指到新 id
        # （必须在对白导入之后：speak_dialogue 要用 dlg_map）
        _bm = (maps or {}).get("behavior") or {}
        for _bid in _bm.values():
            _b = self.behaviors.get(_bid)
            if _b is None or not _b.get("steps"):
                continue
            _steps, _changed = [], False
            for _st in _b["steps"]:
                _st = dict(_st)
                if _st.get("act") == "speak_line" and _st.get("line_id") in id_map:
                    _st["line_id"] = id_map[_st["line_id"]]
                    _changed = True
                elif _st.get("act") == "speak_dialogue" and _st.get("dialogue_id") in dlg_map:
                    _st["dialogue_id"] = dlg_map[_st["dialogue_id"]]
                    _changed = True
                _steps.append(_st)
            if _changed:
                _ok, _err = self.behaviors.update(_bid, _b["name"], _steps)
                if not _ok:
                    warnings.append("行为「%s」的读台词步骤未重指：%s" % (_b["name"], _err))
        self._refresh_lines()
        self._scan_invalid_refs(notify=False)  # 导入后立刻刷新失效引用（不打扰，面板可见）
        return warnings

    def _import_role_bundle(self):
        """导入角色包：素材/行为/可分享配置落地，缺资源明确提示，成功即切换展示。"""
        _path, _f = QFileDialog.getOpenFileName(self, "导入角色包", "", "角色包 (*.dfypet.zip)")
        if not _path:
            return
        _res, _err = pet_export.import_bundle(
            self.role_lib, self.behaviors, self.cfg, _path,
            alarms_apply=self._apply_imported_alarms,
            voice_apply=self._apply_imported_voice_assets,
            lines_apply=self._apply_imported_lines)
        if _res is None:
            self.show_bubble("导入失败：%s" % _err)
            return
        # M7 修复：包内未带参考音时，绑定会指向不存在的槽位（界面还显示"未绑定"）——
        # 明确清掉并告知，避免"看起来绑定了其实没有"的静默失效。
        try:
            _binds = dict((self.cfg.get("voice") or {}).get("bindings") or {})
            _dead = [k for k, v in _binds.items()
                     if v and self.voice_assets.get_asset(v) is None]
            if _dead:
                for k in _dead:
                    _binds.pop(k, None)
                self.cfg.setdefault("voice", {})["bindings"] = _binds
                _res["warnings"].append(
                    "包内 %d 个声音绑定没有随包参考音，已清空（去语音设置重新绑定）" % len(_dead))
        except Exception as e:
            _log_error("clean bindings failed: %r" % (e,))  # 有意忽略：清理失败不影响导入
        # M1 修复：老分享包（v2.0.x）的自定义台词存在 cfg.lines_extra 里，导入后要立刻迁移，
        # 否则要重启才进台词库（且重启时可能被旧截断逻辑吃掉）。
        self._migrate_lines_extra()
        save_config(self.cfg)  # 可分享配置（语音开关等）已应用 → 持久化
        # 立即生效（不必重启）：气泡样式/音效组走现成应用入口
        if "bubble_style" in self.cfg:
            self.apply_bubble_style(self.cfg["bubble_style"])
        if "sound_group" in self.cfg:
            self._set_sound_group(self.cfg["sound_group"])
        self.apply_role(_res["role_id"])  # 导入即切换展示
        _msg = "角色包导入成功！"
        if _res["warnings"]:
            _msg += "（%s）" % "；".join(_res["warnings"][:2])
        self.show_bubble(_msg)

    def _apply_imported_alarms(self, alarms_list):
        """v2.0.5：导入包内闹钟设置（id 换新；铃声文件不随包 → 明确提示换默认音；
        预留字段 repeat/snooze_min 一并透传）。"""
        warnings = []
        for a in (alarms_list or []):
            try:
                if not isinstance(a, dict):
                    warnings.append("跳过非法闹钟条目")
                    continue
                _t = str(a.get("time") or "")
                if not pet_alarm.valid_time(_t):
                    warnings.append("闹钟「%s」时间非法，已跳过" % (_t or "?"))
                    continue
                _na, _err = self.alarms.add(
                    _t, str(a.get("label") or "闹钟"),
                    enabled=a.get("enabled") is not False,
                    repeat=str(a.get("repeat") or ""),
                    snooze_min=a.get("snooze_min")
                    if isinstance(a.get("snooze_min"), int) else 0)
                if _na is None:
                    warnings.append("闹钟「%s」未导入：%s" % (_t, _err))
                    continue
                if a.get("ringtone"):
                    warnings.append("闹钟「%s」的铃声不在包内，已用默认提示音" % _t)
            except Exception as e:
                # 有意忽略：单条坏数据不中断整个导入（转警告）
                warnings.append("闹钟导入异常，已跳过：%s" % e)
        return warnings

    def _compute_base_size(self):
        """P1-7：窗口基准尺寸。旧角色 = 各形态侧图最大尺寸（现行为）；
        v2 角色 = 各形态 (宽×形态scale, 高×形态scale) 的最大值，保证
        anchor 对齐在窗口坐标系里一致。"""
        if self._role_render:
            sizes = []
            for k, rp in zip(self.form_keys, self._role_render):
                sp = self.sprites[k]["side"]
                fs = rp["scale"] or 1.0
                sizes.append((max(1, int(round(sp.width() * fs))),
                              max(1, int(round(sp.height() * fs)))))
            return max(s[0] for s in sizes), max(s[1] for s in sizes)
        return (max(self.sprites[k]["side"].width() for k in self.form_keys),
                max(self.sprites[k]["side"].height() for k in self.form_keys))

    def _build_sprites(self):
        role_pix = self._role_pix()
        if role_pix is not None:
            self._custom_role = True
            rid = self.cfg.get("role", "")
            # M2：用 form_paths（与 form_metas 逐项对齐）装配，保证 form_keys 与 sprites 键集一致
            paths = self.role_lib.form_paths(rid)
            # P1-7 断点#7 side/front：forms[i].front 可选正面图，缺省与 side 同图
            front_paths = self.role_lib.form_front_paths(rid)
            # P1-7：形态元信息（渲染参数）与逐形态动画帧（与 form_keys 对齐，
            # 供 _apply_transform 装配与 _wire_anim_sets 按「形态×动作」查表）
            self._role_metas = self.role_lib.form_metas(rid)
            self._role_anims = self.role_lib.form_animations(rid)
            self._role_render = self._role_render_params() if self.role_lib.is_v2(rid) else None
            if not paths:
                paths = [None]  # 兜底：全部形态缺失时退化成单形态 base
            self.sprites = {}
            for i, p in enumerate(paths):
                if p:
                    pix = self._cap_role_pix(QPixmap(p), p) or role_pix
                else:
                    pix = role_pix  # 该形态文件缺失：回退 base，键集仍完整
                front_pix = pix
                if i < len(front_paths) and front_paths[i]:
                    try:
                        fp = self._cap_role_pix(QPixmap(front_paths[i]), front_paths[i])
                        if fp is not None and not fp.isNull():
                            front_pix = fp
                    except Exception:
                        pass  # 有意忽略：front 图加载失败回退 side（缺省行为）
                self.sprites["f%d" % i] = {"side": pix, "front": front_pix}
            self._build_form_meta()
            return
        self._custom_role = False
        # P1-7：回默认角色时清空自定义角色的逐形态元信息（防旧值泄漏）
        self._role_metas = []
        self._role_anims = []
        self._role_render = None
        normal_side = self._load_img(["character.png", "assets/character.png"]) or self._fallback_pix()
        normal_front = self._load_img(["character_front.png", "assets/character_front.png"]) or normal_side
        full_side = self._load_img(["character_full.png", "assets/character_full.png"]) or normal_side
        full_front = self._load_img(["character_full_front.png", "assets/character_full_front.png"]) or full_side
        self.sprites = {
            "normal": {"side": normal_side, "front": normal_front},
            "full": {"side": full_side, "front": full_front},
        }
        self._build_form_meta()

    def _cap_role_pix(self, pix, path=None):
        """旧版超大角色素材加载时归一化到 512（与导入管线一致）。

        防状态图生成时的内存峰值（v1.3.0 旧角色可能 2048px+，10 状态 × 2 形态
        每张全尺寸副本可达数百 MB）。为防升级后桌宠窗口突然缩小，对超大素材
        一次性按比例补偿 cfg scale 并落盘（标记键防重复补偿）。

        P1-7 断点#11：全局 scale 补偿是旧角色兼容路径——新结构角色（v2，
        带 anchor/scale/offset/front/states 等）跳过补偿，仅截断尺寸，
        渲染交给 anchor/scale/offset 正常装配。
        """
        if pix is None or pix.isNull():
            return pix
        w, h = pix.width(), pix.height()
        if max(w, h) <= 512:
            return pix
        try:
            # 标记按角色 id 记：多形态角色各形态都超大时只补偿一次（L1）
            mark = self.cfg.get("role", "")
            v2 = bool(mark) and self.role_lib and self.role_lib.is_v2(mark)
            if path and not v2 and self.cfg.get("scale_compensated_role") != mark:
                factor = min(max(w, h) / 512.0, 4.0 / max(self.cfg.get("scale", 1.0), 0.2))
                self.cfg["scale"] = min(4.0, round(self.cfg.get("scale", 1.0) * factor, 2))
                self.cfg["scale_compensated_role"] = mark
                save_config(self.cfg)
        except Exception:
            pass  # 有意忽略：补偿计算失败按原图缩放处理；save_config 自身已记日志
        return pix.scaled(512, 512, Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)

    def _role_pix(self):
        """自定义角色图：config 激活且文件存在则返回 QPixmap，否则 None（回退默认角色）。"""
        rid = self.cfg.get("role", "")
        if not rid:
            return None
        try:
            if self.role_lib.active_id() != rid:
                return None
            path = self.role_lib.active_path()
            if not path or not os.path.isfile(path):
                return None
            # 文件存在但解码失败（损坏/占位文件）：必须回退默认角色而非返回 null
            return self._cap_role_pix(QPixmap(path), path) or None
        except Exception as e:
            _log_error("_role_pix: %r" % (e,))
            return None

    def _pix_frames(self, paths):
        """P1-7：动画帧路径列表 → [QPixmap]（经 _cap_role_pix 统一尺寸口径）。

        任一帧加载失败返回 []（整动作回退静态，不播残缺动画）。"""
        if not paths:
            return []
        frames = []
        try:
            for p in paths:
                pix = QPixmap(p)
                if pix.isNull():
                    return []
                frames.append(self._cap_role_pix(pix, p))
        except Exception:
            return []
        return frames

    def _role_frames(self):
        """自定义角色的动画帧 [QPixmap]；无帧动画角色返回 []。"""
        rid = self.cfg.get("role", "")
        if not rid:
            return []
        try:
            paths = self.role_lib.frames_for(rid)
            frames = []
            for p in paths:
                pix = QPixmap(p)
                if pix.isNull():
                    return []  # 坏帧：整体回退静态
                frames.append(self._cap_role_pix(pix, p))  # 与静态底图同一尺寸口径
            return frames
        except Exception:
            return []

    def _wire_anim_sets(self):
        """把当前角色对应的帧集注册进 FrameAnim（init 与角色切换共用）。

        P1-7：自定义角色按「形态×动作」查表（forms[i].animations 内建
        idle/eat/poke/sleep + v2.0.1 自定义命名帧动作，RoleLibrary.form_animations
        已解析为绝对路径）；旧角色级 frames 已由 RoleLibrary._load 迁移为
        forms[0].animations.idle（兼容路径，行为不变）。
        默认角色用内置 idle 帧；eat 集仅默认角色注册（自定义角色吃帧按形态查表）。
        """
        if self._custom_role:
            cur = self._cur_form_anim()
            # S1 修复：form_animations 返回的是绝对路径，必须转 QPixmap 再进 FrameAnim；
            # 任一帧损坏 → 整动作空集（回退静态），与 form_animations 的 isfile 语义一致
            # v2.0.1：注册全部动作键（内建 idle/eat/poke/sleep + 自定义命名帧动作）
            for act in (pet_resources.ANIM_ACTIONS + tuple(sorted(
                    k for k in cur if k not in ("interval_ms",) and k not in pet_resources.ANIM_ACTIONS))):
                self.anim.add_set(act, self._pix_frames(cur.get(act) or []))
            self.has_frames = bool(self.anim._sets.get("idle"))
            return
        role_frames = self._role_frames() if self._custom_role else []
        self.has_frames = bool(role_frames) or (bool(self._idle_frames) and not self._custom_role)
        if self.has_frames:
            self.anim.add_set("idle", role_frames if role_frames else self._idle_frames)
        else:
            self.anim.add_set("idle", [])
        self.anim.add_set("eat", self._eat_frames if (self.has_frames and not self._custom_role) else [])

    def apply_role(self, role_id):
        """切换角色（""=默认角色）：持久化并立即重载贴图，无需重启。"""
        rid = str(role_id or "")
        self.cfg["role"] = rid
        save_config(self.cfg)
        self.role_lib.set_active(rid)
        self._reload_sprites()

    def _reload_sprites(self):
        """重建角色贴图 / 窗口尺寸 / 动画能力（角色切换与恢复默认共用）。"""
        if self._digest_timer is not None:
            self._digest_timer.stop()  # 切换角色：作废旧角色的消化定时器（L1）
        self._stop_tween()  # v2.0.1：切角色立即停合成动作，防旧角色振荡残留到新角色
        self._behavior_seq = None      # v2.0.2：切角色取消在途行为序列
        self._behavior_is_idle = False
        self._cancel_transform()       # v2.0.2：切角色取消变身回切定时器
        self._sleep_home = None
        # v2.1：切角色重置待机状态与用户选定形态（旧角色的形态键在新角色上无意义）
        self._idle_active = False
        self._idle_form_active = False
        self._idle_after_full_at = None
        self._idle_last_action = ""
        self._build_sprites()
        self._build_state_pix()  # 自定义角色：程序化表情图随底图重建
        # P1-7：各形态尺寸可能不同：窗口按较大者定（v2 角色计入形态 scale），避免溢出/不居中
        self.base_w, self.base_h = self._compute_base_size()
        if self.form not in self.sprites:
            self.form = self.form_keys[0]  # 角色形态数变少：回第一形态
        self._user_form = self.form if self.form in self.form_keys else self.form_keys[0]
        self._wire_anim_sets()
        if self.busy and self.anim_mode == "eat":
            self.busy = False  # S1：吃帧被角色切换打断，_eat_done 不会再回调，显式释放
        self.anim.stop()
        self.anim_mode = ""  # 强制 _play_idle 按新角色重绘当前形态
        self._using_front = False
        self.set_scale(self.scale)  # 按新角色尺寸重算窗口
        self._play_idle()
        try:
            self.tray.setIcon(QIcon(self.sprites[self.form_keys[0]]["front"]))
        except Exception:
            pass  # 有意忽略：托盘图标更新失败不影响主窗口显示
        if self.emote_item.isVisible() and getattr(self, "_last_emote_kind", None):
            self._show_emote(self._last_emote_kind)  # 头顶表情随新窗口尺寸重排

    # ---------- 阶段1：帧动画与状态 ----------
    def _on_frame_changed(self, _idx):
        # 帧下标由信号携带，但直接以 current() 为唯一取帧入口（单一事实来源）
        # P1-7：state/sleep 也纳入（poke 动画/睡眠动画走帧播放；静态展示时 anim 已停不发帧）
        if self.anim_mode in ("idle", "eat", "state", "sleep"):
            pix = self.anim.current()
            if pix is not None and not pix.isNull():
                self.item.setPixmap(pix)

    def _play_idle(self, _name=None):
        self._sleeping = False
        self._cur_state = None  # 离开表情/睡眠展示
        if self._custom_role:
            self._wire_anim_sets()  # P1-7：待机前按当前形态重查「形态×动作」帧集
        idle_frames = self.anim._sets.get("idle") or []
        # P1-7：帧间隔——自定义角色 forms[i].anim_interval_ms 优先，缺省沿用 IDLE_FRAME_MS
        interval = IDLE_FRAME_MS
        if self._custom_role:
            interval = self._cur_form_anim().get("interval_ms") or IDLE_FRAME_MS
        if self.form != self.form_keys[0] and not idle_frames:
            # 非首形态且该形态无待机帧：显示该形态静态图（P1-7 之前非首形态永远静态；
            # 现在 forms[i].animations.idle 存在时走下方帧动画分支）
            if self.anim_mode != "form_idle":
                self.anim.stop()
                self.anim_mode = "form_idle"
            # H1：setPixmap 必须在守卫外——f1→f2 时 anim_mode 已是 form_idle，否则旧形态滞留
            self.item.setPixmap(self.sprites[self.form]["side"])
            self._using_front = False
        elif idle_frames:
            if self.anim_mode != "idle":
                self.anim_mode = "idle"
                self.anim.play("idle", interval, loops=-1)
        else:
            if self.anim_mode != "idle":
                self.anim.stop()
                self.anim_mode = "idle"
                # S1：从表情/睡眠返回待机必须强制恢复 front（_using_front 可能仍为 True，
                # 仅当非待机转入时才换贴图，否则表情图会永久滞留）
                self.item.setPixmap(self.sprites[self.form]["front"])
                self._using_front = True
            elif not self._using_front:
                self.item.setPixmap(self.sprites[self.form]["front"])
                self._using_front = True
        self._apply_transform()

    def _play_eat(self):
        self._stop_tween()  # v2.0.1：吃帧开始前停合成动作（防 squash 污染 + 收尾顶掉 _eat_done）
        self.anim_mode = "eat"
        # P1-7：帧间隔——自定义角色 forms[i].anim_interval_ms 优先，缺省沿用 EAT_FRAME_MS
        interval = EAT_FRAME_MS
        if self._custom_role:
            interval = self._cur_form_anim().get("interval_ms") or EAT_FRAME_MS
        # 若 "eat" 帧集未注册（空集），play() 会立即回调 on_finish 并返回 False，无需兜底分支
        self.anim.play("eat", interval, loops=2, on_finish=self._eat_done)

    def _eat_done(self, _name):
        self.busy = False
        self._play_idle()

    # 吃饱形态缺图（用户素材只有 7 张吃饱版状态图）时用同形态近义图兜底，避免显示瘦图
    FULL_STATE_ALIAS = {"hiss": "angry", "drool": "laugh", "surprised": "puzzled"}

    def _build_state_pix(self):
        """构建状态图：默认角色加载内置表情素材；自定义角色生成程序化表情图。

        P2-5 状态图优先级（P1-7 可选状态图，本方法与 _custom_state_pix 为合并点）：
        1) forms[i].states[state] 资源图（用户配置，优先）；
        2) 程序化叠图 _make_custom_state_pix 兜底（未配置/加载失败时，向后兼容）。
        吃饱版缺图回退常态版同名的 R2-5 语义仍在 _state_pix 的 alias 逻辑里保留。
        """
        names = tuple(_STATE_MARK_MAP)  # 状态名单一来源，避免双处维护
        if self._custom_role:
            self.state_pix = {}
            rid = self.cfg.get("role", "")
            states_paths = self.role_lib.form_state_paths(rid) if self.role_lib else []
            for i, k in enumerate(self.form_keys):
                base = self.sprites[k]["side"]
                res = states_paths[i] if i < len(states_paths) else {}
                self.state_pix[k] = {
                    s: self._custom_state_pix(res.get(s), base, s) for s in names
                }
            return
        self.state_pix = {"normal": {}, "full": {}}
        for form in ("normal", "full"):
            for s in names:
                pix = self._load_img(["assets/%s_%s.png" % (form[0], s)])
                if pix is not None:
                    self.state_pix[form][s] = pix

    def _custom_state_pix(self, res_path, base, state):
        """P2-5 状态图合并点：资源图（forms[i].states[state]）优先；
        缺失/加载失败 → 程序化叠图 _make_custom_state_pix 兜底（向后兼容）。"""
        if res_path:
            try:
                pix = QPixmap(res_path)
                if not pix.isNull():
                    return self._cap_role_pix(pix, res_path) or pix
            except Exception:
                pass  # 有意忽略：资源图加载失败走程序化叠图兜底
        return _make_custom_state_pix(base, state)

    def _state_pix(self, state):
        pix = self.state_pix.get(self.form, {}).get(state)
        if pix is None and self.form == "full":
            alias = self.FULL_STATE_ALIAS.get(state)
            if alias:
                pix = self.state_pix.get("full", {}).get(alias)
        if pix is None and self.form != self.form_keys[0]:
            pix = self.state_pix.get(self.form_keys[0], {}).get(state)
        return pix

    POKE_STATES = ("puzzled", "angry", "hiss")

    def _show_state(self, state, duration_ms=STATE_DURATION_MS):
        self._stop_tween()  # v2.0.1：戳戳/表情开始前停合成动作（与吃帧同语义，防振荡叠加）
        # P1-7：戳戳状态优先播「poke 动画帧」（一次），无配置则回退静态状态图
        if state in self.POKE_STATES and self._custom_role:
            poke_frames = self.anim._sets.get("poke") or []
            if poke_frames:
                self.anim.stop()
                self.anim_mode = "state"
                self._cur_state = state
                self._state_timer.stop()
                interval = self._cur_form_anim().get("interval_ms") or EAT_FRAME_MS
                self.anim.play("poke", interval, loops=1, on_finish=self._state_done)
                return
        pix = self._state_pix(state)
        if pix is None:
            _log_error("state image missing: %s" % state)
            return
        self.anim.stop()
        self.anim_mode = "state"
        self._cur_state = state  # 记录当前表情，供切形态时按新形态素材重绘
        self._state_timer.stop()
        self.item.setPixmap(pix)
        self._state_timer.start(duration_ms)

    def _state_done(self, _name=None):
        if self.anim_mode == "state":
            self._play_idle()

    def _show_sleep(self):
        if self._sleeping:
            return  # v2.0.2：已在睡时重入直接返回（防二次睡眠语音/zzz 重播）
        self.voice.play_event("sleep")  # v2.0：睡眠语音片段（未配置/关闭则静默）
        # v2.1.3 修复：入睡前先打断待机（否则待机的形态展示期与行为序列会跟着睡着继续跑，
        # 睡着期间还可能被待机步骤切形态）。放在记 _sleep_home 之前，保证醒来回的是用户形态。
        self._idle_interrupt("sleep")
        # v2.0.2 断点#12：配置了睡觉形态则先切过去（醒来回到原形态）
        if self._custom_role and not self._sleeping:
            _sf = self._sleep_form_key()
            if _sf and _sf != self.form:
                self._sleep_home = self.form
                self._set_form(_sf, display_only=True)  # 睡眠是临时展示，不改用户选定形态
        self.anim.stop()
        self.anim_mode = "sleep"
        self._cur_state = "sleep"
        self._sleeping = True
        # P1-7：睡眠优先播「sleep 动画帧」（循环），无配置回退静态睡眠图
        sleep_frames = (self.anim._sets.get("sleep") or []) if self._custom_role else []
        if sleep_frames:
            interval = self._cur_form_anim().get("interval_ms") or IDLE_FRAME_MS
            self.anim.play("sleep", interval, loops=-1)
        else:
            pix = self._state_pix("sleep")
            if pix is not None:
                self.item.setPixmap(pix)
        self._show_emote("zzz")

    def _wake(self):
        self._touch_activity()  # 唤醒=交互：重置无交互计时并打断待机
        if self._sleeping:
            self.voice.play_event("wake")  # v2.0：唤醒语音片段
            _uf = getattr(self, "_user_form", "") or self.form_keys[0]
            if _uf in self.form_keys and self.form != _uf:
                self._set_form(_uf, display_only=True)  # v2.1：醒来回到用户选定形态
            self._sleep_home = None
            self._play_idle()

    def _show_pet(self):
        """把桌宠带回视野（置顶显示在最前）。"""
        self.show()
        self.raise_()
        self._wake()
        self.show_bubble("我在这里~")

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self._show_pet()

    # ---------- 阶段2：情绪状态机 ----------
    MOOD_STATE_DURATION_MS = {"puzzled": 2500, "angry": 2500, "hiss": 2500,
                              "drool": 3000, "cry": 3000, "smug": 2500, "blush": 2800}

    def _on_mood_state(self, state):
        self._wake()
        if self.busy or self._petting:
            return  # 动画进行中 / 摸摸头中：丢弃情绪展示（S3 补全）
        self._show_state(state, self.MOOD_STATE_DURATION_MS.get(state, STATE_DURATION_MS))

    def _mood_bubble(self, text):
        if not self.busy:
            self.show_bubble(text)

    def _mood_emote(self, kind):
        if not self.busy and not self._petting:  # 摸摸头期间抑制 heart 等（S3 修复）
            self._show_emote(kind)

    def _mood_tick(self):
        if not self._sleeping and not self.busy and not self._petting:
            self.mood.tick()  # 摸摸头中不切 smug/angry（S3 补全）

    _emote_cache = {}

    def _emote_pixmap(self, kind, size):
        key = (kind, size)
        if key in self._emote_cache:
            return self._emote_cache[key]
        pm = _emote_mark(kind, size)
        if len(self._emote_cache) > 80:
            self._emote_cache.clear()  # 缩放连续变化会产生大量尺寸，上限防无界增长
        self._emote_cache[key] = pm
        return pm

    def _start_petting(self):
        """长按 1.5 秒：播放摸摸头帧动画 + 台词（借参考插件 petpet 动图概念）。"""
        if self._petting:
            return
        if self._press_dist > 32:
            return  # 已明确拖动（与取消阈值一致），不再触发（M-3 修复）
        if self.busy:
            # busy（吃帧/跳跃）中暂不触发：继续按住则 400ms 后补判（M1 修复）
            self._hold_timer.start(400)
            return
        if not self._fx_petpet:
            return
        self._petting = True
        self._touch_activity()  # v2.1：摸头=交互（打断待机 + 重新计时）
        self._fx_petpet_on = True
        self._place_fx("petpet")
        self.fx.play(self._fx_petpet, interval_ms=80, loops=-1)
        self._pet_max.start(15000)  # 看门狗：release 丢失时 15s 自停（M2 修复）
        # v2.1.2（M-2）：库可用时不回落内置常量（删掉的台词不复活）；空池就这次不喊
        _pet_lines_pool = self.lines_pools.get("petting") or []
        if _pet_lines_pool:
            self._say_line(random.choice(_pet_lines_pool))

    def _on_pet_watchdog(self):
        """看门狗超时结束摸摸头：标记后收尾，随后的松手不再算「戳一下」。"""
        self._pet_watchdog_ended = True
        self._end_petting()

    def _end_petting(self):
        self._petting = False
        self._fx_petpet_on = False
        self._pet_max.stop()
        self.fx.stop()

    def _place_fx(self, kind):
        """按当前缩放摆放特效层（贴头顶，水平居中）。缩放变化后由 set_scale 重排。"""
        w = self.width()
        if kind == "petpet":
            fw = self._fx_petpet[0].width() if self._fx_petpet else 128
            self.fx_item.setScale(self.scale)
            self.fx_item.setPos((w - fw * self.scale) / 2, 0)
        elif kind == "money":
            fw = self._fx_money[0].width() if self._fx_money else 160
            self.fx_money_item.setScale(self.scale)
            self.fx_money_item.setPos((w - fw * self.scale) / 2, 0)

    def _fx_celebrate(self):
        """余额到账：撒钱帧动画（借参考插件 money 动图概念，独立特效层）。"""
        if not self._fx_money:
            self._fx_money = pet_anim.load_frame_set(self._fx_money_dir, "money", 86)
            if len(self._fx_money) != 86:
                _log_error("fx frames money incomplete: %d/86" % len(self._fx_money))
        if not self._fx_money:
            return
        self._fx_money_on = True
        self._place_fx("money")
        self.fx_money.play(self._fx_money, interval_ms=30, loops=1)

    def _show_emote(self, kind):
        if self._emote_anim is not None:
            try:
                self._emote_anim.stop()  # 停掉旧动画，避免与新的叠加
                self._emote_anim.deleteLater()  # stop 不触发 finished，需显式回收防累积
            except RuntimeError:
                pass  # 旧动画已被 finished→deleteLater 释放
            self._emote_anim = None
        size = max(24, int(48 * self.scale))
        pix = self._emote_pixmap(kind, size)
        self._emote_gen += 1
        gen = self._emote_gen
        self.emote_item.setPixmap(pix)
        self.emote_item.setOpacity(1.0)
        w = self.width()
        pad_top = self._pad_top()
        x = (w - pix.width()) / 2
        y = max(0, pad_top - pix.height() - 4)
        self.emote_item.setPos(x, y)
        self.emote_item.show()
        self._last_emote_kind = kind  # 角色热切换时据此重排表情
        anim = QVariantAnimation(self)
        anim.setDuration(1500)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)

        def onval(v):
            if gen != self._emote_gen:
                return
            self.emote_item.setOpacity(1.0 - v * 0.85)
            self.emote_item.setPos(x, y - v * 26)

        anim.valueChanged.connect(onval)
        anim.finished.connect(lambda g=gen: self._hide_emote(g))
        anim.finished.connect(lambda: setattr(self, "_emote_anim", None))  # 自然结束即清引用
        anim.finished.connect(anim.deleteLater)
        self._emote_anim = anim  # 防御性保活引用（动画以 self 为 parent，正常由 finished→deleteLater 回收）
        anim.start()

    def _hide_emote(self, gen):
        if gen == self._emote_gen:
            self.emote_item.hide()

    # ---------- 变换 ----------
    def _apply_transform(self):
        sx = self.scale * self.squash_x * self.flip
        sy = self.scale * self.squash_y
        w = self.width()
        h = self.height()
        t = QTransform()
        # P1-7 断点#11：新结构角色按形态渲染参数（anchor/scale/offset）装配，
        # 解决多形态切换跳变；旧角色走原变换（行为完全不变）
        render = self._role_render[self.form_keys.index(self.form)]             if (self._role_render and self.form in self.form_keys) else None
        if render is not None:
            ax, ay = render["anchor"]
            fs = render["scale"] or 1.0
            ox, oy = render["offset"]
            sx *= fs
            sy *= fs
            # 锚点取当前贴图自身尺寸（状态图/动画帧尺寸可能与底图不同，仍按锚点对齐）
            pm = self.item.pixmap()
            if pm is None or pm.isNull():
                pw, ph = self.sprites[self.form]["side"].width(), self.sprites[self.form]["side"].height()
            else:
                pw, ph = pm.width(), pm.height()
            t.translate(w / 2.0 + ox * self.scale, h / 2.0 + oy * self.scale)
            t.scale(sx, sy)
            t.translate(-pw * ax, -ph * ay)
        else:
            t.translate(w / 2.0, h / 2.0)
            t.scale(sx, sy)
            t.translate(-self.base_w / 2.0, -self.base_h / 2.0)
        self.item.setTransform(t)
        # v2.0.1：_proc_offset_y 为程序化「点头」动作的竖向位移（其余时间恒 0）
        _poy = int(getattr(self, "_proc_offset_y", 0) or 0)
        if getattr(self, "_anchor_bottom", False):
            dy = self.base_h * self.scale * (self.squash_y - 1.0) / 2.0
            self.item.setPos(0, -dy + _poy)
        else:
            self.item.setPos(0, _poy)
        self._update_click_mask()  # P3-1：缩放/贴图变化后重建穿透遮罩（关闭时清遮罩，开销可忽略）

    def set_scale(self, s):
        self.scale = max(0.2, min(4.0, float(s)))
        w = max(28, int(round(self.base_w * self.scale * PAD)))
        h = max(28, int(round(self.base_h * self.scale * PAD)))
        self.setFixedSize(w, h)
        self.view.setGeometry(0, 0, w, h)
        self.scene.setSceneRect(0, 0, w, h)
        self._apply_transform()
        if self._fx_petpet_on:
            self._place_fx("petpet")  # 特效层各自跟随缩放（L1 修复）
        if self._fx_money_on:
            self._place_fx("money")
        self._ensure_on_screen()

    def _ensure_on_screen(self):
        """窗口基本离开所有屏幕（分辨率切换/拔显示器）时收回最近屏右下角。

        P1-4：可见性判据收紧——中心在某屏上，或与某屏完整 geometry 相交面积
        ≥25%（任意 1px 相交不算可见，避免只剩一条边挂屏上点不到）；判据用
        完整 geometry() 而非 availableGeometry()：拖到任务栏后方藏大半是合法
        玩法，不算离屏。回收目标用 availableGeometry 落点（避开任务栏），
        且回收到**最近屏**（负坐标副屏/竖屏均正确），而不是盲目回主屏。"""
        try:
            geo = self.frameGeometry()
            center = geo.center()
            area = max(1, geo.width() * geo.height())
            for scr in QApplication.screens():
                g = scr.geometry()
                if g.contains(center):
                    return
                inter = g.intersected(geo)
                if inter.width() * inter.height() >= area * 0.25:
                    return
            _, ag = screen_geometry_at(center)
            if ag is not None:
                self.move(ag.right() - self.width() - SCREEN_EDGE_MARGIN_X,
                          ag.bottom() - self.height() - SCREEN_EDGE_MARGIN_Y)
        except Exception:
            pass  # 有意忽略：掉屏回收失败保持原位，下个 tick 再试

    def _reset_squash(self):
        self.squash_x = 1.0
        self.squash_y = 1.0
        self._apply_transform()
        self.busy = False
        if self._tween_anim is not None:
            try:
                self._tween_anim.deleteLater()
            except RuntimeError:
                pass  # 动画已被自身 finished→deleteLater 释放
            self._tween_anim = None

    # ---------- 气泡 ----------
    def _pad_top(self):
        return int((self.height() - self.base_h * self.scale) / 2)

    def show_bubble(self, text):
        if self._closing:
            return  # P1-5：退出后不再弹气泡（在途信号守卫）
        if not text:
            return
        pad_top = self._pad_top()
        gp = QPoint(self.x() + self.width() // 2, self.y() + pad_top)
        if self.badge.isVisible():
            gp = QPoint(self.badge.x() + self.badge.width() // 2, self.badge.y())
        self.bubble.show_text(text, gp)

    def _cycle_line(self):
        """戳一戳随机台词：v2.1 起来自台词库（用户可增删改），空池兜中性句子。

        走日常台词出口（_say_line）：开了「日常台词也用配音」时会用角色声音读出来。"""
        self._say_line(self._pick_line(
            ("sajiao", "greedy", "scared", "happy", "idle", "petting")))

    # ---------- 余额挂件 ----------
    def moveEvent(self, event):
        super().moveEvent(event)
        self._position_badge()
        self._position_food_tray()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_badge()
        self._position_food_tray()

    def _position_badge(self):
        if not self.badge.isVisible():
            return
        pad_top = self._pad_top()
        x = self.x() + (self.width() - self.badge.width()) // 2
        y = self.y() + pad_top - self.badge.height() - 6
        self.badge.move(x, y)

    # ---------- 食物托盘（喂食交互） ----------
    def _position_food_tray(self):
        if not self.food_tray.isVisible():
            return
        pad_top = self._pad_top()
        x = self.x() + self.width() + 8
        y = self.y() + pad_top
        scr = self._screen_geo(self.frameGeometry().center())
        if scr is None:
            return  # 无屏（headless 极端场景）：不动托盘
        if x + self.food_tray.width() > scr.right():
            x = self.x() - self.food_tray.width() - 8
        # P1-4：y 也钳进所在屏——负 y 竖屏副屏顶部不再出屏
        if y + self.food_tray.height() > scr.bottom():
            y = max(scr.top(), scr.bottom() - self.food_tray.height() - 4)
        y = max(scr.top(), y)
        self.food_tray.move(max(scr.left(), x), y)

    def _set_food_tray(self, on):
        if self.food_tray.isVisible() == bool(on):
            return  # 状态一致，避免重复触发 food_shown/food_hidden
        if on:
            self.food_tray.show()
            self._position_food_tray()
            # 错峰 150ms：先让托盘窗口完成显示，再切馋嘴状态/气泡，避免同 tick 爆发。
            # 成员单次定时器：快速开→关→开时 restart 覆盖旧调度，不会重复触发
            if self._food_shown_timer is not None:
                self._food_shown_timer.start(150)
        else:
            self.food_tray.hide()
            if self._food_shown_timer is not None:
                self._food_shown_timer.stop()  # 关托盘：取消待触发的馋嘴错峰
            self.mood.food_hidden()

    def _food_shown_guarded(self):
        if self.food_tray.isVisible():
            self.mood.food_shown()

    def _fly_food(self, food):
        if self.busy:
            self.show_bubble(random.choice(["嘴里还有呢，等一下~", "还没咽下去啦！"]))
            return
        self.busy = True
        # 不在此播音：食物落嘴时 feed() 会播喂食音，避免「松手音」语义错位
        start = QPoint(self.food_tray.x() + self.food_tray.width() // 2, self.food_tray.y() + 16)
        end = QPoint(self.x() + self.width() // 2, self.y() + self._pad_top() + int(self.base_h * self.scale * 0.45))
        self.food_flyer.set_food(food)
        self.food_flyer.move(start.x() - 20, start.y() - 20)
        self.food_flyer.show()

        # 30ms 步进（≈33fps）：顶层窗口 move 走 SetWindowPos，比 QVariantAnimation 的
        # ~60Hz 少一半窗口移动，避免投喂时窗口移动风暴造成卡顿
        steps = 15
        self._fly_step = 0

        def tick():
            self._fly_step += 1
            v = self._fly_step / steps
            if v >= 1.0:
                if self._fly_timer is not None:
                    self._fly_timer.stop()
                    try:
                        self._fly_timer.deleteLater()
                    except RuntimeError:
                        pass  # 有意忽略：定时器可能已被销毁（幂等清理）
                    self._fly_timer = None
                self.food_flyer.hide()
                self.busy = False
                self.feed(food)
                return
            x = start.x() + (end.x() - start.x()) * v
            y = start.y() + (end.y() - start.y()) * v - math.sin(v * math.pi) * 70
            self.food_flyer.move(int(x) - 20, int(y) - 20)

        if self._fly_timer is not None:
            self._fly_timer.stop()
            try:
                self._fly_timer.deleteLater()
            except RuntimeError:
                pass  # 有意忽略：定时器可能已被销毁（幂等清理）
        self._fly_timer = QTimer(self)
        self._fly_timer.timeout.connect(tick)
        self._fly_timer.start(30)

    def _start_food_drag(self, food, gp):
        if self.busy:
            return
        self._dragging_food = food
        self.food_flyer.set_food(food)
        self.food_flyer.move(gp.x() - 20, gp.y() - 20)
        self.food_flyer.show()
        self._drag_timer.start()

    def _drag_tick(self):
        pos = QCursor.pos()
        # 兜底：左键已松开（release 落在别的窗口导致 flyer 收不到 dropped）时收尾，
        # 避免 flyer 永久跟随光标 / 定时器空转
        if not (QApplication.mouseButtons() & Qt.MouseButton.LeftButton):
            self._on_food_dropped(pos)
            return
        self.food_flyer.move(pos.x() - 20, pos.y() - 20)

    def _on_food_dropped(self, gp):
        self._drag_timer.stop()
        food = self._dragging_food
        self._dragging_food = None
        self.food_flyer.hide()
        if food and self.frameGeometry().contains(gp):
            self.feed(food)

    def _update_badge(self):
        bal = self._shown_balance if self._shown_balance is not None else 0.0
        if self._currency == "CNY":
            line1 = "余额 ¥%.2f" % bal
        else:
            line1 = "余额 %s %.2f" % (self._currency, bal)
        if self._currency == "CNY":
            line2 = "今日已用 ¥%.2f" % (self._usage or 0.0)
        else:
            line2 = "今日已用 %.2f" % (self._usage or 0.0)
        self.badge.set_info(line1, line2)
        self._position_badge()

    def _set_badge(self, on):
        self.cfg["badge"] = bool(on)
        save_config(self.cfg)
        if on:
            if not self.cfg.get("api_key"):
                self.ai.set_api_key()
            if not self.cfg.get("api_key"):
                self.cfg["badge"] = False
                save_config(self.cfg)
                self.show_bubble("要先在菜单填 DeepSeek API Key 才能开余额挂件哦~")
                return
            self.badge.show()
            self._position_badge()
            self.balance.start()
        else:
            self.balance.stop()
            self.badge.hide()

    # ---------- 互动 ----------
    def _finish_tween(self, cb):
        """收尾回调统一出口：自然结束与被顶替共用；幂等，异常不向外抛。"""
        self._tween_finish_cb = None
        if cb is not None:
            try:
                cb()
            except Exception as e:
                _log_error("tween finish cb: %r" % (e,))

    def _stop_tween(self):
        """v2.0.1：停掉在途 QVariantAnimation 并执行其收尾回调（幂等）。

        单动画槽被顶替（_run_anim）之外，喂食/戳戳/切角色等走 FrameAnim 的路径
        也要显式停合成动作，防 squash/_proc_offset_y 继续振荡污染新状态。"""
        if self._tween_anim is not None:
            try:
                self._tween_anim.stop()
                self._tween_anim.deleteLater()
            except RuntimeError:
                pass  # 有意忽略：动画可能已被销毁（幂等清理）
            self._tween_anim = None
            self._finish_tween(self._tween_finish_cb)

    def _run_anim(self, duration, on_value, keyframes=None, end=1.0, easing=None, on_finished=None):
        # P1-2：单动画槽——新动画启动前停掉上一个；stop() 不发 finished，
        # 手动执行旧动画的收尾回调，防 busy/squash 状态滞留
        self._stop_tween()
        cb = on_finished if on_finished is not None else self._reset_squash
        self._tween_finish_cb = cb
        anim = QVariantAnimation(self)
        anim.setDuration(duration)
        anim.setStartValue(0.0)
        anim.setEndValue(end)
        if keyframes:
            for t, v in keyframes:
                anim.setKeyValueAt(t, v)
        if easing is not None:
            anim.setEasingCurve(easing)
        anim.valueChanged.connect(on_value)
        anim.finished.connect(lambda: self._finish_tween(cb))
        anim.finished.connect(anim.deleteLater)
        self._tween_anim = anim
        anim.start()
        return anim

    def _set_form(self, form, refresh=True, cancel_transform=True, display_only=False):
        """切换展示形态。

        display_only=False（默认）= 用户意图表达的切换（菜单/行为编排）→ 记为
        user_selected_form；True = 临时展示（待机/睡眠/变身/喂食形态推进），
        不改 user_selected_form——待机与临时状态因此永远不会吞掉用户选定的形态。"""
        if form not in self.sprites:
            return
        if form == self.form:
            return  # 同形态重选：什么都不做，避免待机动画重启造成的帧跳/卡顿
        if cancel_transform:
            self._cancel_transform()  # v2.0.2：手动切形态取消变身回切定时器（防 8s 后强制弹回）
        if not display_only:
            self._user_form = form  # 用户选定形态：待机/idle_form 不得覆盖
        self.form = form
        if self._custom_role:
            # P1-7：形态切换后帧集按「形态×动作」重查；若正在播待机帧，
            # 先停掉旧帧引用（FrameAnim 正在播放的帧集是旧列表），
            # 让 refresh 分支的 _play_idle 用新帧集重启
            self._wire_anim_sets()
            if self.anim_mode == "idle":
                self.anim.stop()
                self.anim_mode = "form_idle"
        if refresh:
            if self.anim_mode in ("idle", "form_idle"):
                self._play_idle()
            elif self.anim_mode in ("state", "sleep") and self._cur_state:
                # 表情/睡眠展示中切形态：立即换成新形态的同一表情，避免瞬时旧形态形象
                pix = self._state_pix(self._cur_state)
                if pix is not None:
                    self.item.setPixmap(pix)
        self._apply_transform()

    def _digest(self):
        """吃饱形态结束：回用户选定形态，并登记触发 A（延迟 idle_delay_after_full 后待机）。"""
        _uf = getattr(self, "_user_form", "") or self.form_keys[0]
        # v2.1.3 修复：睡眠/变身期间不做形态回位——那两个是更高优先级的"临时展示"，
        # 各自有自己的回位路径（醒来 / 变身到时）。此前会"吃饱把睡眠形态顶掉"。
        _busy_display = bool(self._sleeping) or getattr(self, "_transform_home", None) is not None
        if self.form != _uf and not _busy_display:
            # _set_form 内已在待机态回位；状态图展示中不掐断（state 结束时自然回待机）
            self._set_form(_uf, display_only=True)
        try:
            _delay = int(self._idle_cfg().get("idle_delay_after_full") or 0)
        except (TypeError, ValueError):
            _delay = 0  # 有意忽略：坏值按 0（立即待机）
        self._idle_after_full_at = time.monotonic() + max(0, _delay)
        self._last_idle_at = 0.0  # 触发 A 立即生效（不受触发 B 去重窗口影响）
        self._show_emote("sparkle")
        if self._custom_role:
            # 显示形态**名字**而不是形态键（f0/f1）
            self.show_bubble("变回「%s」啦~" % self.form_names.get(_uf, _uf))
        else:
            self.show_bubble(random.choice(["消化完啦，又饿了~", "瘦回来啦！", "还能再吃一点……"]))

    def feed(self, food):
        if self.busy:
            self.show_bubble(random.choice(["嘴里还有呢，等一下~", "别急嘛，还在吃！", "呜……咽不下去啦！"]))
            return
        # v2.0.2 断点#12：当前形态标记「不参与喂食」→ 明确拒绝，不静默
        if self._form_no_feed():
            self.show_bubble(random.choice(["这个形态不吃东西啦~", "本形态拒绝投喂！",
                                            "现在只想安静地当一条鱼~"]))
            return
        self.busy = True
        if self.cfg.get("sound", True):
            play_sound("feed")
        self.voice.play_event("feed")  # v2.0：喂食语音片段
        # v2.1：喂食台词来自台词库（用户可增删改；库空则回落内置 FOOD_LINES）
        line = random.choice(self.lines_lib.food_texts(food))
        _uf = getattr(self, "_user_form", "") or self.form_keys[0]
        was_first = self.form == _uf  # 必须在 _set_form 之前记录（相对用户形态判定「首形态」）
        self.mood.fed()
        # 喂食：形态顺次前进（多形态循环），refresh=False 先播吃帧再落新形态；
        # 临时展示语义：吃完消化回 user_selected_form，不吞掉用户选定的形态
        cur_idx = self.form_keys.index(self.form) if self.form in self.form_keys else 0
        next_idx = (cur_idx + 1) % len(self.form_keys)
        self._touch_activity()  # v2.1 修复：先记交互/打断待机，再切喂食形态
        # （此前先切形态再打断，_idle_interrupt→_restore_user_form 会把刚切的形态拉回去）
        self._set_form(self.form_keys[next_idx], refresh=False, display_only=True)
        if self._digest_timer is not None:
            self._digest_timer.stop()
            try:
                self._digest_timer.deleteLater()
            except RuntimeError:
                pass  # 有意忽略：定时器可能已被销毁（幂等清理）
        self._digest_timer = QTimer(self)
        self._digest_timer.setSingleShot(True)
        self._digest_timer.timeout.connect(self._digest)
        self._digest_timer.start(12000)
        if self.has_frames and was_first:
            # 首形态 → 下一形态：错峰 120ms 启动吃帧；busy 在 _eat_done 释放
            QTimer.singleShot(120, self, self._play_eat)  # 带 context：窗口销毁自动取消
        elif self.has_frames:
            # 已在非首形态：不重播吃帧（吃帧是首形态形象，会顶掉当前形态），
            # 以大笑表情表达「又吃到了」，并立即释放 busy
            def _full_refeed():
                self._show_state("laugh", 2200)
                self.busy = False
            QTimer.singleShot(120, self, _full_refeed)
        else:
            def onval(v):
                s = math.sin(v * math.pi * 5)
                self.squash_x = 1.0 + 0.12 * s
                self.squash_y = 1.0 - 0.12 * s
                self._apply_transform()

            def _squash_done():
                self._reset_squash()
                self._play_idle()  # H1：无吃帧角色（自定义角色）喂食后落到吃饱形态贴图

            self._run_anim(900, onval, on_finished=_squash_done)
        self._show_emote("note")
        self._say_line(line)  # v2.1：日常台词出口（气泡；开了「日常台词也用配音」则朗读）

    # ---------- 天气 ----------
    def _set_city(self):
        """设置天气城市（open-meteo 免费接口，默认北京）。"""
        dlg = QInputDialog(self)
        dlg.setWindowTitle("天气城市")
        dlg.setLabelText("输入天气城市名（如 北京 / 上海 / 东京）：")
        dlg.setTextValue(self.cfg.get("city", "北京"))
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        dlg.setFocus()
        if dlg.exec() == QDialog.DialogCode.Accepted:
            city = dlg.textValue().strip()[:20]
            if not city:
                self.show_bubble("城市名不能为空哦~")
                return
            self.cfg["city"] = city
            save_config(self.cfg)
            self.show_bubble("天气城市改成「%s」啦~" % city)

    # ---------- 屏幕 ----------
    def _screen_geo(self, pt):
        """pt 所在屏（间隙/屏外取最近屏）的 availableGeometry；无屏返回 None（调用方守卫）。"""
        return screen_geometry_at(pt)[1]

    def _press_squash(self, pressed):
        if pressed and self.busy:
            return  # 吃帧/跳跃进行中：不叠加压扁变换，避免视觉错位
        # release 侧不门控：busy 期间松手也复位 anchor/squash，防止 _anchor_bottom 滞留 True
        self._anchor_bottom = pressed
        if pressed:
            self.squash_x = 0.92
            self.squash_y = 1.06
        else:
            self.squash_x = 1.0
            self.squash_y = 1.0
        self._apply_transform()

    def _snap_to_edge(self):
        if self._flying:
            return  # P1-手感：飞行中不触发吸附，落地静止后再允许
        # P1-4：以「所在屏」（间隙取最近屏）吸附，混合 DPI 下用逻辑坐标天然对齐
        scr = self._screen_geo(self.frameGeometry().center())
        if scr is None:
            return
        cx = self.pos().x() + self.width() // 2
        cy = self.pos().y() + self.height() // 2
        x, y = self.pos().x(), self.pos().y()
        if cx < scr.left() + scr.width() / 4:
            x = scr.left()
        elif cx > scr.left() + 3 * scr.width() / 4:
            x = scr.right() - self.width()
        if cy < scr.top() + scr.height() / 4:
            y = scr.top()
        elif cy > scr.top() + 3 * scr.height() / 4:
            y = scr.bottom() - self.height()
        self.move(x, y)

    # ---------- 鼠标事件 ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            if self._flying:
                return  # P1-手感：飞行中不响应戳戳/摸摸头（落地静止后恢复）
            self._wake()
            self._touch_activity()  # v2.1：点击=交互（打断待机 + 两触发重新计时）
            self._drag_samples = []  # P1-手感：新一轮拖拽轨迹采样
            self._spring_vx = 0.0
            self._spring_vy = 0.0
            self._last_drag_t = time.monotonic()
            self._press_global = e.globalPosition().toPoint()
            self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._moved = False
            self._press_dist = 0  # 本次按压累计移动距离（摸头 32px 阈值判定）
            self._was_walking = self.walk_timer.isActive()
            self.walk_timer.stop()
            self._press_squash(True)
            if self.cfg.get("sound", True):
                play_sound("boing")
            self._hold_timer.start(1500)  # 长按 1.5 秒 → 摸摸头
        elif e.button() == Qt.MouseButton.RightButton:
            self._hold_timer.stop()
            if self._petting:
                self._pet_watchdog_ended = True  # 右键取消同看门狗语义：后续松手不戳
                self._end_petting()
            # 菜单会抓走后续 release：这里完整复位按压状态，防压扁/散步滞留
            self._drag_offset = None
            self._press_global = None
            self._press_squash(False)
            self.wander.on_drag_end()
            self._open_menu(e.globalPosition().toPoint())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton and self._drag_offset is not None:
            gp = e.globalPosition().toPoint()
            dist = (gp - self._press_global).manhattanLength()
            self._press_dist = max(self._press_dist, dist)
            if dist > 4:
                self._moved = True
            if dist > 32:
                # 明确是拖动（>32px）才取消长按，避免 4px 手抖误判（M-3 修复）
                self._hold_timer.stop()
                if self._petting:
                    self._end_petting()
            if self._physics_on() and not self._flying:
                self._record_drag_sample(gp)  # P1-手感：仅开启物理时采样（默认关闭零开销）
                self._physics_drag_move(gp)  # 过阻尼弹簧跟手（K=200/C=30，ζ≈1.06）
            else:
                self.move(gp - self._drag_offset)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            if self._flying and self._press_global is None:
                return  # P1-手感：飞行中点到宠物（press 被忽略）——release 一并忽略，防状态陈旧
            self._drag_offset = None
            self._press_global = None
            self._hold_timer.stop()
            was_petting = self._petting or self._pet_watchdog_ended
            self._pet_watchdog_ended = False
            if self._petting:
                self._end_petting()
            self._press_squash(False)
            if self.cfg.get("sound", True):
                play_sound("pop")
            self.wander.on_drag_end()
            if was_petting:
                return  # 摸头成功的松手：不戳、不贴边（M-1 修复）
            if not self._moved:
                self.mood.poke()
                self.voice.play_event("poke")  # v2.0：被戳语音片段
            else:
                # P1-手感：仅开启物理时估速甩抛；默认关闭走原贴边逻辑（逐字节等价）
                if self._physics_on():
                    self._record_drag_sample(e.globalPosition().toPoint())
                    if self._maybe_throw():
                        return
                self._snap_to_edge()

    # ---------- P1-手感：甩抛物理（默认关闭） ----------
    def _physics_on(self):
        return bool((self.cfg.get("physics") or {}).get("enabled"))

    def _record_drag_sample(self, gp):
        """拖拽轨迹采样：只保留最近 SAMPLE_WINDOW（200ms），估速窗口内才保留。"""
        self._drag_samples.append((time.monotonic(), gp.x(), gp.y()))
        self._drag_samples = pet_physics.trim_samples(self._drag_samples)

    def _physics_drag_move(self, gp):
        """过阻尼弹簧跟手（K=200 / C=30，ζ≈1.06 不过冲）：不再直接 self.move()。"""
        now = time.monotonic()
        if self._last_drag_t is None:
            self._last_drag_t = now
        dt = min(0.05, max(0.002, now - self._last_drag_t))
        self._last_drag_t = now
        target = gp - self._drag_offset
        cur = self.pos()
        K, C = 200.0, 30.0
        self._spring_vx += (K * (target.x() - cur.x()) - C * self._spring_vx) * dt
        self._spring_vy += (K * (target.y() - cur.y()) - C * self._spring_vy) * dt
        self.move(cur.x() + int(round(self._spring_vx * dt)),
                  cur.y() + int(round(self._spring_vy * dt)))

    def _maybe_throw(self):
        """松手估速：超过死区（500px/s）进入甩抛飞行，返回 True；否则 False（走贴边）。"""
        if not self._physics_on():
            return False  # 严重修复：默认关闭绝不甩飞（旧版贴边行为）
        phys = self.cfg.get("physics") or {}
        vx, vy = pet_physics.estimate_throw(
            self._drag_samples, now=time.monotonic(),
            throw_power=float(phys.get("throwPower", 1.0)))
        if not (vx or vy):
            return False
        self._flying = True
        self._flight_vx = vx
        self._flight_vy = vy
        self._flight_last = time.monotonic()
        self._flight_start = time.monotonic()
        self._air_static_ticks = 0
        self._flight_timer.start(pet_physics.FLIGHT_TICK_MS)
        return True

    def _flight_rect(self):
        """当前所在屏的可用区域 (left, top, right, bottom)；无屏返回 None。"""
        scr = self._screen_geo(self.frameGeometry().center())
        if scr is None:
            return None
        r = scr.getRect()  # (x, y, w, h)
        return r[0], r[1], r[0] + r[2], r[1] + r[3]

    def _flight_tick(self):
        """飞行积分步进：重力+四边反弹+地面摩擦。

        落地冲击（step_physics 返回的 impact）≥300 时播 Q 弹（与静止判定解耦）；
        静止收尾：贴地双速极小，或空中连续 N 拍双速极小，或飞行超 5s（防漂浮软锁）。"""
        phys = self.cfg.get("physics") or {}
        rect = self._flight_rect()
        if rect is None:
            self._end_flight()
            return
        now = time.monotonic()
        if now - getattr(self, "_flight_start", now) > pet_physics.FLIGHT_MAX_SECONDS:
            self._end_flight()  # 飞行时长上限：漂浮模式等任何情况都不会软锁
            return
        dt = min(pet_physics.DT_MAX, max(0.001, now - self._flight_last))
        self._flight_last = now
        nx, ny, nvx, nvy, on_ground, impact = pet_physics.step_physics(
            float(self.x()), float(self.y()), self._flight_vx, self._flight_vy,
            self.width(), self.height(), rect, dt, phys)
        self._flight_vx, self._flight_vy = nvx, nvy
        self.move(int(round(nx)), int(round(ny)))
        if impact >= pet_physics.SQUASH_LIGHT_IMPACT:
            self._land_squash = pet_physics.landing_squash(impact)
            if self._land_squash < 1.0:
                self._play_landing_bounce()
        if on_ground and abs(nvy) < pet_physics.STATIC_VY and abs(nvx) < pet_physics.STATIC_VX:
            self._end_flight()
            return
        # 空中静止判定（gravity=0 漂浮模式不会触地）：连续 N 拍双速极小 → 收尾
        if not on_ground and abs(nvy) < pet_physics.STATIC_VY and abs(nvx) < pet_physics.STATIC_VX:
            self._air_static_ticks = getattr(self, "_air_static_ticks", 0) + 1
            if self._air_static_ticks >= pet_physics.AIR_STATIC_TICKS:
                self._end_flight()
        else:
            self._air_static_ticks = 0

    def _play_landing_bounce(self):
        """落地 Q 弹（220ms 曲线）：经 _run_anim 单动画槽。

        显式收尾回调只复位 squash、不动 busy（喂食等动作的 busy 由各自流程管理，
        避免 Q 弹结束把吃帧的 busy 提前误清）。"""
        squash = self._land_squash

        def _bounce_done():
            self.squash_x = 1.0
            self.squash_y = 1.0
            self._apply_transform()

        self._run_anim(
            int(pet_physics.BOUNCE_DURATION * 1000),
            lambda v: self._set_bounce_scale(v, squash),
            on_finished=_bounce_done)

    def _set_bounce_scale(self, t01, squash):
        sy = pet_physics.bounce_scale(t01 * pet_physics.BOUNCE_DURATION, squash)
        self.squash_y = sy
        self.squash_x = max(pet_physics.SQUASH_MIN_X, 2.0 - sy)  # 体积守恒：压扁时横向鼓出
        self._apply_transform()

    def _end_flight(self):
        """落地收尾：停飞行、贴边、恢复散步（按压前在散步则续走）。"""
        self._flying = False
        self._flight_timer.stop()
        self._flight_vx = 0.0
        self._flight_vy = 0.0
        self._drag_samples = []
        self._snap_to_edge()
        if self._was_walking and self.cfg.get("wander"):
            self.walk_timer.start(self._walk_interval)

    def _set_physics(self, on):
        """P1-手感：甩抛物理开关（立即生效并落盘）。关闭时若正在飞行则立即收尾。"""
        phys = dict(self.cfg.get("physics") or {})
        phys["enabled"] = bool(on)
        self.cfg["physics"] = phys
        save_config(self.cfg)
        if not on and self._flying:
            self._end_flight()  # 关闭=停止：不打断预期之外继续飞
        self.show_bubble("甩抛物理已开启，使劲把我甩出去吧~" if on else "甩抛物理已关闭~")

    def apply_physics(self, data=None):
        """P1-手感：物理参数回调——与 load_config 同口径归一化（负数/超界回退钳制），
        数据未变不弹提示。"""
        if not isinstance(data, dict):
            return
        phys = dict(self.cfg.get("physics") or {})
        phys.update({k: v for k, v in data.items()
                     if k in ("gravity", "restitution", "groundFriction", "ceilingBounce", "throwPower")})
        phys = pet_config.normalize_physics(phys)
        if phys.get("_fixed"):
            _log_error("apply_physics: 参数非法已修正: %s" % ",".join(phys.pop("_fixed")))
        if phys == (self.cfg.get("physics") or {}):
            return  # 值未变：静默返回
        self.cfg["physics"] = phys
        save_config(self.cfg)
        self.show_bubble("物理参数已更新~")

    def wheelEvent(self, e):
        delta = e.angleDelta().y()
        factor = 1.1 if delta > 0 else (1.0 / 1.1)
        center_before = self.frameGeometry().center()  # 以中心为锚，避免「往右下长」
        self.set_scale(self.scale * factor)
        self.cfg["scale"] = self.scale
        self._schedule_scale_save()
        center_after = self.frameGeometry().center()
        self.move(self.pos() + (center_before - center_after))

    # ---------- 右键菜单（v1.3 美化：分区标题 + emoji 图标 + 信息行） ----------
    def _new_menu(self):
        """顶层菜单工厂：走 桌宠 模块级 QMenu 名字（v13 菜单结构验证靠 stub 捕获）。"""
        return QMenu(self)

    def _open_menu(self, gp):
        """右键菜单（P0-1：结构迁至 pet_menu.MenuBuilder，菜单项/层级/勾选原样）。"""
        self.menu_builder.open(gp)

    def _schedule_scale_save(self):
        """缩放落盘防抖：滚动/滑块停止 400ms 后才写 config.json（高频操作不整写）。"""
        if self._save_scale_timer is None:
            self._save_scale_timer = QTimer(self)
            self._save_scale_timer.setSingleShot(True)
            self._save_scale_timer.timeout.connect(lambda: save_config(self.cfg))
        self._save_scale_timer.start(400)

    def _set_always_on_top(self, on):
        self.cfg["always_on_top"] = bool(on)
        save_config(self.cfg)
        self._apply_flags()

    def _set_sound(self, on):
        self.cfg["sound"] = bool(on)
        save_config(self.cfg)

    def _set_click_through(self, on):
        """P3-1：透明区点击穿透开关（立即生效；命中画布按当前贴图重建）。"""
        self.cfg["click_through"] = bool(on)
        save_config(self.cfg)
        self._update_click_mask()

    def _update_click_mask(self):
        """P3-1：重建「变换后身体」的逐像素命中画布（与 _apply_transform 严格同变换）。

        不用 setMask：setMask 会按窗口形状裁剪绘制（表情被裁、身体错位）。
        改为 nativeEvent 里对 WM_NCHITTEST 按本画布 alpha 判定，透明像素返回
        HTTRANSPARENT（点击落到桌面），身体像素正常——无视觉裁剪、命中与所见一致。
        关闭时清空画布（缓存键守卫，动画帧高频调用开销可忽略）。"""
        try:
            if not self.cfg.get("click_through"):
                self._click_composite = None
                self._click_cache_key = None
                return
            item = getattr(self, "item", None)
            pix = item.pixmap() if item is not None else None
            if pix is None or pix.isNull():
                self._click_composite = None
                self._click_cache_key = None
                return
            key = (pix.cacheKey(), self.width(), self.height(),
                   self.scale, self.squash_x, self.squash_y, self.flip, item.pos())
            if key == getattr(self, "_click_cache_key", None) and self._click_composite is not None:
                return
            canvas = QImage(self.width(), self.height(), QImage.Format.Format_ARGB32)
            canvas.fill(QColor(0, 0, 0, 0))
            painter = QPainter(canvas)
            painter.setTransform(item.transform())
            painter.translate(item.pos())
            painter.drawPixmap(0, 0, pix)
            painter.end()
            self._click_composite = canvas
            self._click_cache_key = key
        except Exception as e:
            _log_error("click composite: %r" % (e,))
            self._click_composite = None

    def nativeEvent(self, eventType, message):
        """P3-1：WM_NCHITTEST 逐像素命中判定——命中画布透明处返回 HTTRANSPARENT。

        （无 setMask，渲染不被裁剪；关闭穿透时完全走 Qt 默认路径，行为与旧版一致。）"""
        try:
            if eventType != b"windows_generic_MSG" or not self.cfg.get("click_through"):
                return False, 0
            canvas = getattr(self, "_click_composite", None)
            if canvas is None:
                return False, 0
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if int(msg.message) != 0x0084:  # WM_NCHITTEST
                return False, 0
            sx = int(msg.lParam) & 0xFFFF
            sy = (int(msg.lParam) >> 16) & 0xFFFF
            if sx > 32767:
                sx -= 65536  # 有符号虚拟屏坐标（多屏负坐标副屏）
            if sy > 32767:
                sy -= 65536
            lp = self.mapFromGlobal(QPoint(sx, sy))
            if lp.x() < 0 or lp.y() < 0 or lp.x() >= canvas.width() or lp.y() >= canvas.height():
                return False, 0
            if canvas.pixelColor(lp.x(), lp.y()).alpha() < 8:
                return True, -1  # HTTRANSPARENT：点击落到桌面
        except Exception:
            pass  # 有意忽略：命中画布失败按常规命中处理（每条鼠标消息都走这里，不刷日志）
        return False, 0

    def _set_autostart(self, on):
        """开机自启开关（默认关闭）：写入/删除 HKCU Run 键。

        失败回弹用 blockSignals + 守卫标志，避免回弹再次触发 toggled 造成
        提示互相覆盖或无限递归。"""
        if getattr(self, "_autostart_busy", False):
            return
        self._autostart_busy = True
        try:
            ok, err = set_autostart(bool(on))
            if not ok:
                self._autostart_act.blockSignals(True)
                self._autostart_act.setChecked(not on)  # 失败回弹勾选（不触发信号）
                self._autostart_act.blockSignals(False)
                self.show_bubble("开机自启设置失败：%s" % (err or "未知错误"))
                return
            self.show_bubble("开机自启已开启，下次开机我会自己跑出来~" if on else "开机自启已关闭~")
        finally:
            self._autostart_busy = False

    # ---------- v1.3：音效组 / 试听 / 气泡样式 / 台词 / 记账 / 资源对话框 ----------
    def _set_sound_group(self, name):
        self.cfg["sound_group"] = "custom" if name == "custom" else "default"
        save_config(self.cfg)
        self._apply_sound_group()

    def apply_sound_group(self, group=None, as_custom=True):
        """面板改槽位 / 菜单切组后调用：group=已解析槽位 dict 或 None（用库内当前组）；
        as_custom=True 时自动把配置切到自定义组并落盘，保证改完立刻生效。"""
        try:
            if as_custom:
                self.cfg["sound_group"] = "custom"
                save_config(self.cfg)
            if self.cfg.get("sound_group") == "custom":
                pet_audio.set_custom_group(self.audio_lib.group_paths() if group is None else group)
            else:
                pet_audio.clear_custom_group()
        except Exception as e:
            _log_error("apply_sound_group failed: %r" % (e,))

    def _apply_sound_group(self):
        """启动 / 菜单切组时按配置把音效组同步进 pet_audio（不改变配置）。"""
        self.apply_sound_group(None, as_custom=False)

    def _play_voice_clip(self, path):
        """v2.0：语音片段/合成结果播放。合成 worker 线程经 signals 投递回主线程
        （QMediaPlayer 只能在主线程使用；wav 的 winsound 链路线程安全但统一走主线程更稳）。"""
        if threading.current_thread() is not threading.main_thread():
            signals.voice_play.emit(path)
        else:
            self.preview_audio(path)

    # ---------- v2.1.1：本地配音后端（自动/手动启动） ----------
    def _auto_start_voice_backend(self):
        """启动时按开关自动拉起本地后端：默认关（= 和以前一样，用户自己启动）。

        自动失败也会明确告知，用户随时可以用「🎙 启动配音后端」手动来一次。"""
        try:
            started, msg = self.voice.start_backend_if_configured()
        except Exception as e:
            _log_error("auto start voice backend failed: %r" % (e,))
            return
        if not started:
            return
        self.show_bubble("配音后端：" + msg)
        threading.Thread(target=self._wait_voice_backend, daemon=True).start()

    def _wait_voice_backend(self):
        """后台等后端就绪，结果经信号回主线程（不阻塞 UI）。"""
        try:
            ok, msg = self.voice.wait_backend_ready()
        except Exception as e:
            ok, msg = False, "等待后端就绪出错：%s" % e
        signals.voice_backend_msg.emit(("✅ " if ok else "⚠ ") + msg)

    def start_voice_backend(self):
        """手动启动本地后端（菜单/对话框共用）。返回 (ok, msg)。"""
        ok, msg = self.voice.start_backend()
        if ok:
            threading.Thread(target=self._wait_voice_backend, daemon=True).start()
        return ok, msg

    def _menu_start_voice_backend(self):
        """菜单项：手动启动配音后端。"""
        ok, msg = self.start_voice_backend()
        if not ok:
            self.show_bubble("配音后端没起来：%s" % msg)

    def _stop_voice_clip(self):
        """v2.1：停止当前播放（配音 stop() 用）。winsound 与 QMediaPlayer 两条链路都停。"""
        try:
            import winsound
            winsound.PlaySound(None, winsound.SND_PURGE)  # wav 链路：立即静音
        except Exception:
            pass  # 有意忽略：非 Windows / 无播放时无需处理
        try:
            if self._preview_player is not None:
                self._preview_player.stop()
        except Exception:
            pass  # 有意忽略：播放器可能未创建或已销毁（停止尽力而为）

    # ---------- v2.1：语言系统（配音）回调（均在主线程） ----------
    def _on_voice_started(self, role_slot, line_id):
        """开始朗读：打断待机 + 播「说话」动作（对上动作/行为模块的自定义）。

        M3 修复：**待机序列自己发起的朗读不算外部打断**——否则序列刚说出第一步，
        speaking_started 就把这条序列的 gen 顶掉，后面所有步骤都不执行。"""
        if line_id and line_id == getattr(self, "_idle_speak_self", ""):
            self._speaking_voice = True  # 本序列自己的朗读：只标记，不打断
            return
        self._idle_interrupt("speak")
        self._speaking_voice = True
        name = str((self.cfg.get("voice") or {}).get("talk_action") or "").strip()
        if name and self._action_exists(name):
            self.actions.play_action(name)

    def _on_voice_finished(self, role_slot, line_id):
        """读完一条：解除说话态；无其他动作时回待机表现。"""
        self._speaking_voice = False
        if not (self.busy or self._petting):
            self._play_idle()

    def _on_voice_dialogue_done(self):
        self._speaking_voice = False
        self.show_bubble("对白读完啦~")

    def _on_lines_changed(self):
        """台词库变化：刷新池子 + 重新扫描失效引用（语言系统队列由自身清理）。"""
        try:
            self._refresh_lines()
        except Exception as e:
            _log_error("refresh lines failed: %r" % (e,))
        self._scan_invalid_refs()

    def _scan_invalid_refs(self, notify=True):
        """v2.1：扫描台词库失效引用；返回失效列表。

        启动 / 删除角色或声音素材 / 打开面板 / 台词变化时调用；有失效就明确提示
        （气泡 + 面板红色提示条），**不自动删、不静默替换**。"""
        try:
            items = self.lines_lib.validate_references(
                lambda slot: self.role_lib.get(slot) is not None,
                lambda slot: self.voice_assets is not None and self.voice_assets.exists(slot))
        except Exception as e:
            _log_error("validate refs failed: %r" % (e,))
            return []
        # M6 修复：行为步骤里的读台词/读对白也会失效（分享包换 id 后可命中），一并扫描
        try:
            for _b in self.behaviors.list():
                for _st in (_b.get("steps") or []):
                    if _st.get("act") == "speak_line":
                        if self.lines_lib.get(_st.get("line_id")) is None:
                            items.append({
                                "line_id": "", "behavior_id": _b["id"],
                                "text_preview": "行为「%s」：读台词" % _b["name"],
                                "missing_role": None, "missing_voice": None,
                                "reason": "行为里要读的台词不存在了（可能被删或分享包换过 id）"})
                    elif _st.get("act") == "speak_dialogue":
                        if self.lines_lib.get_dialogue(_st.get("dialogue_id")) is None:
                            items.append({
                                "line_id": "", "behavior_id": _b["id"],
                                "text_preview": "行为「%s」：读对白" % _b["name"],
                                "missing_role": None, "missing_voice": None,
                                "reason": "行为里要读的对白不存在了"})
        except Exception as e:
            _log_error("scan behavior refs failed: %r" % (e,))  # 有意忽略：扫描失败不影响台词扫描
        self._invalid_refs = items
        self.lines_lib.emit_invalid_reference(items)
        if notify and items:
            self.show_bubble("有 %d 处引用失效了，去「台词设置 → 失效引用」看看~" % len(items))
        return items

    def _on_reply_voice(self, text):
        """v2.0：AI 回复 → 语音播放。优先级：reply 片段 > TTS 合成；错误提示文本不朗读。

        v2.0.4：跳过判定改为前缀匹配（pet_chat.API_ERROR_PREFIXES 与 explain_api_error
        同源维护）——旧精确匹配表在错误文案归类化后已成死条目。"""
        text = (text or "").strip()
        if not text or text.startswith(pet_chat.API_ERROR_PREFIXES):
            return
        p = self.voice.clip("reply")
        if p is not None:
            self._play_voice_clip(p)
            return
        self.voice.speak(text, on_error=signals.voice_error.emit)

    def apply_voice(self, data=None):
        """v2.0：语音设置回调（归一化后落盘）。返回 True（供对话框判断成败）。

        v2.1 修复：backend_params / backend_keys **按后端深合并**——此前顶层浅合并 +
        只回传当前后端 → 保存一次就把其它后端的 Key 清空、参数回落默认（凭据丢失）。"""
        if not isinstance(data, dict):
            return False
        merged = {**self.cfg.get("voice", {})}
        for k, v in data.items():
            if k in ("backend_params", "backend_keys") and isinstance(v, dict):
                old = dict(merged.get(k) or {})
                for bid, sub in v.items():
                    if isinstance(sub, dict):
                        cur = dict(old.get(bid) or {})
                        cur.update(sub)
                        old[bid] = cur
                    else:
                        old[bid] = sub
                merged[k] = old
            else:
                merged[k] = v
        self.cfg["voice"] = pet_voice.normalize_voice(merged)
        save_config(self.cfg)
        if not data.get("_silent"):
            self.show_bubble("语音设置已更新~")
        return True

    def preview_audio(self, path):
        """试听：wav 走 winsound 主链路；mp3 等降级 QMediaPlayer。返回是否发出。"""
        if not path or not os.path.isfile(path):
            return False
        try:
            if pet_audio.preview_file(path):
                return True
            from PySide6.QtCore import QUrl
            from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
            if self._preview_player is None:
                self._preview_player = QMediaPlayer(self)
                self._preview_out = QAudioOutput(self)
                self._preview_player.setAudioOutput(self._preview_out)
            self._preview_player.setSource(QUrl.fromLocalFile(path))
            self._preview_player.play()
            return True
        except Exception:
            return False

    def apply_bubble_style(self, style):
        if not isinstance(style, dict):
            return
        st = dict(BUBBLE_STYLE)
        for k in ("bg", "fg", "border"):
            v = style.get(k)
            if isinstance(v, str) and QColor(v).isValid():
                st[k] = v
        for k in ("font_size", "radius"):
            try:
                v = int(style.get(k))
                st[k] = max(8 if k == "font_size" else 0, min(18 if k == "font_size" else 30, v))
            except (TypeError, ValueError):
                pass  # 有意忽略：非数字样式值保持原值
        self.cfg["bubble_style"] = st
        save_config(self.cfg)
        BUBBLE_STYLE.update(st)
        self.bubble.update()

    def save_lines(self, pool, lines):
        """兼容入口（v2.0 台词对话框语义）：整体替换某类别的台词文本。

        v2.1 起数据落在台词库 lines.json（用户条目），旧的 cfg["lines_extra"] 只作迁移来源。"""
        pool = pool if pool in pet_lines.LINE_CATEGORIES else "idle"
        kept_ids = [ln["id"] for ln in self.lines_lib.lines(pool) if not ln.get("builtin")]
        if kept_ids:
            self.lines_lib.delete_many(kept_ids)
        added = 0
        for x in (lines or []):
            s = str(x).strip()
            if s:
                ln, err = self.lines_lib.add(s, pool)
                if ln is not None:
                    added += 1
                else:
                    _log_error("save_lines add failed: %s" % err)
        self._refresh_lines()
        self.show_bubble("台词库更新啦~（%s：%d 条）" % (
            pet_lines.CATEGORY_LABELS.get(pool, pool), added))

    # v2.1：台词池回落表（库被清空/类别为空时的兜底，保证气泡永不空）
    _LINE_FALLBACK = {"sajiao": LINES_SAJIAO, "greedy": LINES_GREEDY, "scared": LINES_SCARED,
                      "happy": LINES_HAPPY, "idle": LINES_IDLE, "startup": LINES_STARTUP,
                      "petting": LINES_PETTING}

    def _refresh_lines(self):
        """v2.1：从台词库（lines.json）刷新随机台词池。

        M12 修复：**库可用时不再回落内置常量**——用户把某类台词删光后，回落会让
        被删的内置台词"复活"（与「内置可删」矛盾）。只有整个库为空/不可用时才回落，
        且取词处用 _pick_line 兜中性句子，避免 random.choice([]) 崩。"""
        pools = {}
        try:
            _empty = self.lines_lib.count() == 0
        except Exception:
            _empty = True
        for cat, builtin in self._LINE_FALLBACK.items():
            try:
                texts = self.lines_lib.texts_by_category(cat)  # 免深拷贝（几千条时明显更快）
            except Exception:
                texts = []
            pools[cat] = (texts or list(builtin)) if _empty else texts
        self.lines_pools = pools

    def _mood_line(self, category, fallback):
        """情绪台词取词（pet_mood 注入）。

        v2.1.2 修复（S2/M-2）：**库可用时永不回落内置常量**——用户把这组情绪台词删光后
        就不该再念（否则"删了还会念"，与「内置可删」矛盾）。只有整个台词库为空
        （首次运行/数据损坏）时才用内置兜底；该类为空则返回空串，pet_mood 跳过这句气泡。"""
        try:
            texts = self.lines_lib.texts_by_category(category)  # 免深拷贝（戳/托盘/调皮都会调）
        except Exception:
            texts = []
        if texts:
            return random.choice(texts)
        try:
            if self.lines_lib.count() == 0:
                return random.choice(fallback) if fallback else ""
        except Exception:
            return random.choice(fallback) if fallback else ""
        return ""

    def _pick_line(self, cats, fallback=None):
        """从若干类别池随机取一句；池子为空时给中性兜底（不崩、不复活已删台词）。"""
        pool = []
        for c in cats:
            pool.extend(self.lines_pools.get(c) or [])
        if not pool:
            return fallback if fallback is not None else "……"
        return random.choice(pool)

    def _migrate_lines_extra(self):
        """把 v2.0 的 cfg["lines_extra"]（只能追加的 4 池）迁进 v2.1 台词库，然后清空该键。

        幂等：只补库中不存在的文本；迁移后 cfg 不再保存该键（数据单一来源=lines.json）。"""
        # 优先用 load_config 保存的**原始文件值**（normalize 之前），迁移不丢数据（S3）
        le = self.cfg.get("_legacy_lines_extra") or self.cfg.get("lines_extra")
        if not isinstance(le, dict) or not le:
            self.cfg.pop("_legacy_lines_extra", None)
            return
        moved = 0
        for cat, texts in le.items():
            if cat not in pet_lines.LINE_CATEGORIES or not isinstance(texts, list):
                continue
            have = {x["text"] for x in self.lines_lib.lines(cat)}
            for t in texts:
                s = str(t).strip()
                if not s or s in have:
                    continue
                if self.lines_lib.add(s, cat)[0] is not None:
                    moved += 1
                    have.add(s)
        self.cfg["lines_extra"] = {}
        self.cfg.pop("_legacy_lines_extra", None)
        save_config(self.cfg)
        if moved:
            _log_error("lines_extra migrated: %d" % moved)
            QTimer.singleShot(2600, lambda: self.show_bubble(
                "已把 %d 条自定义台词迁进新的台词库~" % moved))

    def speak_dialogue(self, dialogue_id):
        """v2.1：朗读整段对白（对话框/行为/菜单共用入口）。返回 (ok, err)。"""
        return self.voice.speak_dialogue(dialogue_id)

    def speak_line(self, line_id):
        """v2.1：朗读单条台词（对话框/行为共用入口）。返回 (ok, err)。"""
        return self.voice.speak_line(line_id)

    def _say_line(self, text):
        """v2.1：日常台词出口——气泡 + （可选）用角色声音读出来。

        cfg["voice"]["speak_daily"] 打开且配音就绪时走克隆后端；否则纯气泡（老行为）。"""
        text = str(text or "")
        self.show_bubble(text)
        vcfg = self.cfg.get("voice") or {}
        if not (vcfg.get("speak_daily") and vcfg.get("enabled") and text):
            return
        # v2.1 修复：先确认"确实绑定了可用声音"再朗读——否则每条日常台词都会被
        # 「没绑定声音」的错误气泡顶掉（把刚显示的台词覆盖掉）。
        vs, _err = self.voice.resolve_voice("", None)
        if not vs:
            return
        self.voice.speak_text(text, "", vs, on_error=signals.voice_error.emit)

    def on_ledger_changed(self):
        """账本变化（记一笔 / 余额差）后刷新挂件今日已用。"""
        if self.book is not None:
            self._usage = self.book.today_usage()
            self._update_badge()

    def apply_ai_settings(self, data=None):
        """应用 AI 设置（对话框保存后回调；P0-1：实现迁至 pet_ai.AIService）。"""
        self.ai.apply_settings(data)

    def _clear_logs(self):
        """清理 error.log(.old) / memory.log / 对话记忆文件（P2-1 日志卫生）。"""
        removed = _remove_files((os.path.join(DATA_DIR, "error.log"),
                                 os.path.join(DATA_DIR, "error.log.old"),
                                 os.path.join(DATA_DIR, "memory.log"),
                                 MEMORY_PATH, MEMORY_PATH + ".tmp"))
        with self._history_lock:
            self._chat_history.clear()
            self._mem_epoch += 1  # 代次 +1：在途 AI 回复不再把本次对话写回记忆
        self.show_bubble("日志和对话记忆都清干净啦~" if removed else "本来就干干净净的~")

    def _ask_amount(self, title, label, cur):
        """数值输入（预算/余额预警共用，BalanceService 注入调用）。"""
        dlg = QInputDialog(self)
        dlg.setWindowTitle(title)
        dlg.setLabelText(label)
        dlg.setInputMode(QInputDialog.InputMode.DoubleInput)
        dlg.setDoubleRange(0.0, 99999.0)
        dlg.setDoubleDecimals(2)
        dlg.setDoubleValue(cur)
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        dlg.setFocus()
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return round(max(0.0, dlg.doubleValue()), 2)
        return None

    def _apply_flags(self):
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        if self.cfg.get("always_on_top", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.show()

    def _about(self):
        box = QMessageBox(self)
        box.setWindowTitle("关于")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText("%s v%s<br>PySide6 桌宠 · MIT License<br>喜欢的，就咬住不放~<br><br>"
                    "📢 不喜欢新版？怀旧版下载："
                    "<a href='https://github.com/xiyan1314/daifeiyu-desktop-pet/releases/tag/v1.4.2'>v1.4.2</a> · "
                    "<a href='https://github.com/xiyan1314/daifeiyu-desktop-pet/releases/tag/v1.4.1'>v1.4.1</a>"
                    % (APP_NAME, VERSION))
        box.setWindowFlags(box.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        box.show()
        box.raise_()
        box.activateWindow()
        box.setFocus()
        box.exec()

    def _quit(self):
        """退出：停止全部定时器/动画、隐藏窗口、清理临时文件，然后结束进程。"""
        self._closing = True  # P1-5：先立退出标志，在途网络请求信号/气泡被守卫拦下
        # v2.1：停配音（清空队列 + 停播放），避免退出时后台线程还在合成
        try:
            self.voice.stop()
        except Exception:
            pass  # 有意忽略：退出清理尽力而为
        # v2.1.1：勾了「退出时结束后端」才关——且只关桌宠自己拉起的那个进程
        try:
            _need, _msg = self.voice.stop_backend_if_ours()
            if _need and _msg:
                _log_error("voice backend stop on exit: %s" % _msg)
        except Exception:
            pass  # 有意忽略：退出清理尽力而为
        # v2.0.4：等在途 API 测试线程收敛（运行中析构 QThread 是 Qt6 致命错误）
        try:
            pet_dialogs.shutdown_api_tests()
        except Exception:
            pass  # 有意忽略：退出清理尽力而为（无在途线程时为空操作）
        try:
            self.bubble.hide()
            self.badge.hide()
            self.food_tray.hide()
            self.food_flyer.hide()
            self.tray.hide()
            self.hide()
            self.anim.stop()
            try:
                self.fx.stop()
                self.fx_money.stop()
            except Exception:
                pass  # 有意忽略：退出清理尽力而为
            self.mood.stop_all()
            self.balance.stop()
            for t in (self.idle_timer, self.walk_timer, self.cpu_timer, self.mood_timer,
                      self._state_timer, self._drag_timer, self._digest_timer,
                      self._fly_timer, self._save_scale_timer, self._food_shown_timer,
                      self._hold_timer, self._pet_max, self._flight_timer,  # P1-手感
                      self._transform_timer,  # v2.1.2（L-1）：变身回切定时器此前漏停
                      self._idle_hold_timer,   # v2.1.3：形态待机展示期定时器（可能为 None，stop 前过滤）
                      self._alarm_timer):  # v2.0.5：闹钟轮询
                if t is not None:
                    t.stop()
            # 缩放防抖未到期就退出：立即落盘，避免最后一次调大小丢失
            if self._save_scale_timer is not None and self._save_scale_timer.isActive():
                save_config(self.cfg)
            for a in (getattr(self, "_tween_anim", None), getattr(self, "_emote_anim", None),
                      getattr(self, "_balance_anim", None)):
                if a is not None:
                    try:
                        a.stop()
                        a.deleteLater()
                    except RuntimeError:
                        pass  # 有意忽略：动画可能已被销毁（退出清理尽力而为）
            try:
                if self._preview_player is not None:
                    self._preview_player.stop()
            except Exception:
                pass  # 有意忽略：退出时停预览播放器尽力而为
            _remove_files((CONFIG_PATH + ".tmp", USAGE_PATH + ".tmp",
                           os.path.join(DATA_DIR, "ledger.json.tmp"),
                           os.path.join(DATA_DIR, "ledger_archive.json.tmp"),
                           os.path.join(DATA_DIR, "roles.json.tmp"),
                           os.path.join(DATA_DIR, "audio.json.tmp"),
                           # v2.1.2（L-3）：v2.0/v2.1 新增的索引也要清残留（崩溃后可能留半截 tmp）
                           os.path.join(DATA_DIR, "lines.json.tmp"),
                           os.path.join(DATA_DIR, "behaviors.json.tmp"),
                           os.path.join(DATA_DIR, "alarms.json.tmp"),
                           os.path.join(DATA_DIR, "voice.json.tmp"),
                           os.path.join(DATA_DIR, "voice_assets.json.tmp"),
                           os.path.join(DATA_DIR, "voice_backend.json.tmp"),
                           MEMORY_PATH + ".tmp"))  # P1-6：退出清记忆原子写残留
        except Exception:
            pass  # 有意忽略：退出清理环节任何失败都不阻塞退出
        QApplication.quit()  # 事件循环退出后主线程结束，daemon 线程随进程回收



def _excepthook(exc_type, exc_value, tb):
    import traceback
    try:
        msg = "".join(traceback.format_exception(exc_type, exc_value, tb))
        _log_error("未捕获异常: " + msg)  # P0-2：走统一日志出口（脱敏+轮转+重入守卫）
    except Exception:
        pass  # 有意忽略：异常钩子自身写盘失败，无处可记（尽力而为）
    try:
        if threading.current_thread() is threading.main_thread():
            # v2.1.2（L-6）：同一条异常 60 秒内只弹一次框——此前 QTimer 槽里反复触发
            # （例如空台词池）会一次次弹模态框，把桌宠卡住且用户无从下手。
            _key = "%s:%s" % (getattr(exc_type, "__name__", "?"), str(exc_value)[:80])
            _now = time.monotonic()
            _seen = globals().setdefault("_EXC_BOX_SEEN", {})
            if _now - float(_seen.get(_key, 0.0)) < 60:
                return
            _seen[_key] = _now
            # 父窗口优先取桌宠本体（顶层可见窗口顺序不契约，可能先匹配到气泡等小窗）
            parent = None
            app = QApplication.instance()
            if app is not None:
                for w in app.topLevelWidgets():
                    if isinstance(w, PetWindow) and w.isVisible():
                        parent = w
                        break
                if parent is None:
                    for w in app.topLevelWidgets():
                        if w.isVisible():
                            parent = w
                            break
            box = QMessageBox(parent)
            box.setWindowFlags(box.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
            box.setWindowTitle("大肥鱼桌宠出错了")
            box.setText("发生了未处理的错误，详情见 error.log")
            box.exec()
    except Exception:
        pass  # 有意忽略：错误弹框失败不阻塞（已处于异常路径）


# ---------------- 开机自启（默认关闭，用户自选） ----------------
AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_NAME = "大肥鱼桌宠"


def is_autostart_enabled():
    """读取 HKCU Run 键判断是否已开启自启（任何异常视为未开启）。

    命令与当前启动命令不一致（程序搬家后）视为未开启，避免勾选失实。
    """
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY) as k:
            val, _ = winreg.QueryValueEx(k, AUTOSTART_NAME)
        return bool(val) and str(val).strip() == pet_main.autostart_command(app_dir(), sys.executable)
    except Exception:
        return False


def set_autostart(on):
    """写入/删除 HKCU Run 键。返回 (ok, err)。"""
    try:
        import winreg
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE)
        except FileNotFoundError:
            # 目标键不存在（个别环境 Run 键缺失）：创建后写入，不把环境差异当错误
            key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE)
        if on:
            winreg.SetValueEx(key, AUTOSTART_NAME, 0, winreg.REG_SZ,
                              pet_main.autostart_command(app_dir(), sys.executable))
        else:
            try:
                winreg.DeleteValue(key, AUTOSTART_NAME)
            except FileNotFoundError:
                pass  # 有意忽略：值不存在=已是关闭状态（幂等删除）
        winreg.CloseKey(key)
        return True, ""
    except Exception as e:
        return False, str(e)


def main():
    if not pet_main.acquire_single_instance():
        return  # 已有实例在运行，静默退出
    sys.excepthook = _excepthook
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(MENU_QSS)  # v1.3：右键菜单美化（托盘菜单同主题）
    app.setQuitOnLastWindowClosed(False)
    pet_main.cleanup_stale_mei()
    pet = PetWindow()
    pet_main.check_memory(DATA_DIR)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
