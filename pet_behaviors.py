# -*- coding: utf-8 -*-
"""
大肥鱼桌宠 · 行为自定义服务（v2.0.2）
MIT License

职责：行为定义（动作序列）的增删改查、JSON 持久化（behaviors.json 原子写）、
导入/导出资源文件、序列校验与参数白名单。纯逻辑、Qt-free，可无 GUI 单测。

行为结构：{"id": "<8位hex>", "name": "ASCII 安全名", "steps": [{"act": ...}]}
动作类型与参数（UI 与校验共用 BEHAVIOR_ACTS 白名单）：
  play_action: {"act":"play_action","name":动作名}
  say:         {"act":"say","text":台词（截 80 字）}
  voice:       {"act":"voice","event":reply/feed/poke/sleep/wake}
  emote:       {"act":"emote","kind":note/sparkle/heart/zzz}
  form:        {"act":"form","name":形态键 f0/f1…（截 12 字符）}
  sleep:       {"act":"sleep"}（终止步：后续步骤不再执行）
  wait:        {"act":"wait","ms":100~30000}
  speak_line:     {"act":"speak_line","line_id":台词 id}（v2.1：请语言系统读这条台词）
  speak_dialogue: {"act":"speak_dialogue","dialogue_id":对白 id}（v2.1：读整段对白）

执行调度由 PetWindow 主线程完成（_run_behavior/_behavior_step），本模块只做数据；
读台词不 import pet_voice（单向依赖）：PetWindow 收到 speak_* 步骤后转交语言系统。

v2.1 待机系统（本模块负责"数据与选择规则"，执行仍在 PetWindow）：
- 触发（v2.2 最终口径）：**两个触发，满足一个就待机**——
  ①吃饱形态结束后 idle_delay_after_full 秒（默认 2s，1s 检查保证精度）；
  ②无交互满 idle_trigger_delay 秒（默认 8s）。
  任一先满足即待机；吃饱形态展示期（消化窗口）不会被待机打断（形态保护，两触发都让位）。
- idle_actions：待机动作列表（引用行为库 id + 启用开关 + 权重 + 顺序）。
- idle_play_mode：sequential（默认，轮流）/ random / weighted / single。
- idle_form：待机展示形态（""=不改形态，保持用户选定形态）。
- pick_idle_action()：纯函数选动作（避免连播同一条）。
"""

import copy
import json
import os
import re
import tempfile
import uuid

import pet_io   # v2.3.1：全仓共用原子写/安全读（分锁 + 线程唯一临时名 + replace 重试）
import pet_log

# v2.0.2：行为动作类型白名单（单一来源：校验 / 编辑对话框共用）
# v2.1：新增 speak_line / speak_dialogue（经 PetWindow 转交语言系统，模块间不互相 import）
BEHAVIOR_ACTS = ("play_action", "say", "voice", "emote", "form", "sleep", "wait",
                 "speak_line", "speak_dialogue")
# v2.3.1（P1-2）：历史 behaviors.json 里"把动作名直接写在 act 上"的旧条目——旧版本能跑、
# 现在白名单里没有（error.log 实测「第 1 步动作类型不合法：jump」），属于**数据格式迁移缺口**
# 而不是用户乱填。这类 act 一律映射成 play_action（动作名照旧透传），而不是丢弃。
# 值 = (现用 act, 迁移后要补的默认参数值)。
_LEGACY_ACT_ALIASES = {
    # 兼容审查 L4：只保留有实测证据的 jump；breathe/sway/nod 历史数据没有实据，
    # 映射后在内置角色上必然"静默无效果"，不如照旧丢弃并记日志（口径更诚实）
    "jump": ("play_action", "jump"),        # 内建跳跃动作：play_action 的 name 就叫 jump
}
# 语音事件白名单（与 pet_voice.VOICE_EVENTS 同值；pet_behaviors 不依赖 pet_voice 的私有实现）
BEHAVIOR_VOICE_EVENTS = ("reply", "feed", "poke", "sleep", "wake")
BEHAVIOR_EMOTES = ("note", "sparkle", "heart", "zzz")
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,23}$")
WAIT_MIN_MS, WAIT_MAX_MS = 100, 30000
STEPS_MAX = 20  # 单个行为最多 20 步

# v2.0.2：空闲/变身时长钳制界限（单一来源：normalize_cfg / 对话框 / 运行时共用；
# 空闲上界 60 = 入睡阈值，超过则入睡先于待机行为触发 → 死配置）
# （旧的 IDLE_SECS_MIN/MAX 常量已挪到 IDLE_TRIGGER_* 之后，做真别名——见下方 v2.1.2 注）
TRANSFORM_SECS_MIN, TRANSFORM_SECS_MAX = 3, 60

# v2.1：待机播放模式（单一来源：归一化 / 选择逻辑 / 编辑 UI 共用）
IDLE_PLAY_MODES = ("sequential", "random", "weighted", "single")
IDLE_MODE_LABELS = {
    "sequential": "顺序轮流",
    "random": "随机",
    "weighted": "按权重随机",
    "single": "只播指定的一条",
}
IDLE_TRIGGER_MIN, IDLE_TRIGGER_MAX = 3, 60      # 无交互触发延迟（上界=入睡阈值内）
# v2.1.2（质量审查 M2）：旧的空闲秒数口径做**真别名**——此前是 5~60 与 3~60 两套并存，
# 行为设置对话框的旧旋钮会把 cfg=3 静默改写成 5。现在两处同口径，怎么改都不会互相覆盖。
IDLE_SECS_MIN, IDLE_SECS_MAX = IDLE_TRIGGER_MIN, IDLE_TRIGGER_MAX
IDLE_AFTER_FULL_MIN, IDLE_AFTER_FULL_MAX = 0, 30  # 吃饱形态结束后的延迟
IDLE_ACTIONS_MAX = 200                          # 只做性能提示用（不做硬性限制的拦截上限）
IDLE_WEIGHT_MIN, IDLE_WEIGHT_MAX = 0.1, 10.0

# 行为系统配置默认值（单一来源：桌宠 DEFAULT_CONFIG / pet_config.normalize_cfg 引用）
DEFAULT_BEHAVIOR_CFG = {
    "idle_behavior": "",          # 旧字段：单条待机行为 id（"" = 不启用；兼容保留）
    "idle_behavior_seconds": 8,   # 旧字段（v2.0.2）：现作为 idle_trigger_delay 的兼容别名
    "idle_trigger_delay": 8,      # v2.1 触发 B：无交互多少秒触发待机（默认 8）
    "idle_delay_after_full": 2,   # v2.2：触发 A——吃饱形态结束后延迟多少秒待机（0=形态一结束即可待机）
    "idle_form_hold": 8,          # v2.1.3：只有形态、没有动作可播时的展示期上限（秒）
    "idle_form": "",              # v2.1 待机形态（""=不改形态，保持用户选定形态）
    "idle_actions": [],           # v2.1 待机动作列表 [{id,behavior_id,enabled,weight,order}]
    "idle_play_mode": "sequential",  # v2.1 播放模式
    "idle_resume_on_interrupt": False,  # 被打断的动作是否视为已消费（False=下次重选）
    "transform_seconds": 8,       # 变身持续秒数
}


def _to_float(v, default=1.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _to_bool(v):
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def normalize_idle_cfg(cfg):
    """待机配置归一化（纯函数，单一来源）：返回 dict（不改入参）。

    兼容：旧键 idle_behavior_seconds 存在且新键缺失时，迁移为 idle_trigger_delay；
    旧键 idle_behavior（单条）会被补进 idle_actions，保证老配置不丢。
    注意（兼容审查 L3）：经 pet_config 走的真实路径里 idle_play_mode 已由默认值存在，
    迁移后模式是 sequential（单条动作时与 single 完全等价，无功能差异）；
    只有直接调用本函数且入参没带 idle_play_mode 时才落到 single。
    """
    src = cfg if isinstance(cfg, dict) else {}
    raw_actions = src.get("idle_actions")
    actions = []
    if isinstance(raw_actions, list):
        for a in raw_actions:
            if not isinstance(a, dict):
                continue
            bid = str(a.get("behavior_id") or "").strip()
            if not bid:
                continue
            try:
                weight = _to_float(a.get("weight", 1.0), 1.0)
            except Exception:
                weight = 1.0
            actions.append({
                "id": str(a.get("id") or bid),
                "behavior_id": bid,
                "enabled": a.get("enabled") is not False,
                "weight": max(IDLE_WEIGHT_MIN, min(IDLE_WEIGHT_MAX, weight)),
                "order": int(a.get("order") or (len(actions) + 1)),
            })
    legacy = str(src.get("idle_behavior") or "").strip()
    if legacy and all(a["behavior_id"] != legacy for a in actions):
        actions.append({"id": legacy, "behavior_id": legacy, "enabled": True,
                        "weight": 1.0, "order": len(actions) + 1})
    actions.sort(key=lambda x: x["order"])
    for i, a in enumerate(actions, 1):
        a["order"] = i
    mode = str(src.get("idle_play_mode") or "").strip()
    if mode not in IDLE_PLAY_MODES:
        mode = "single" if (legacy and len(actions) <= 1) else "sequential"
    # 触发延迟：优先新键；只有旧键时迁移旧值（钳制到新口径）
    if "idle_trigger_delay" in src:
        delay = src.get("idle_trigger_delay")
    else:
        delay = src.get("idle_behavior_seconds",
                        DEFAULT_BEHAVIOR_CFG["idle_trigger_delay"])
    try:
        delay = int(delay)
    except (TypeError, ValueError):
        delay = DEFAULT_BEHAVIOR_CFG["idle_trigger_delay"]
    delay = max(IDLE_TRIGGER_MIN, min(IDLE_TRIGGER_MAX, delay))
    try:
        after_full = int(src.get("idle_delay_after_full",
                                 DEFAULT_BEHAVIOR_CFG["idle_delay_after_full"]))
    except (TypeError, ValueError):
        after_full = DEFAULT_BEHAVIOR_CFG["idle_delay_after_full"]
    after_full = max(IDLE_AFTER_FULL_MIN, min(IDLE_AFTER_FULL_MAX, after_full))
    return {
        "idle_trigger_delay": delay,
        "idle_delay_after_full": after_full,   # v2.2：触发 A 延迟（0~30 钳制）
        # v2.1.8：形态待机的展示期上限（此前只被读取、不在归一化里 → 实际不可配）
        "idle_form_hold": _clamp_int(src.get("idle_form_hold"),
                                     DEFAULT_BEHAVIOR_CFG["idle_form_hold"], 2, 60),
        "idle_form": str(src.get("idle_form") or "").strip()[:24],
        "idle_actions": actions,
        "idle_play_mode": mode,
        "idle_resume_on_interrupt": _to_bool(src.get("idle_resume_on_interrupt")),
        # L9 修复：transform_seconds 按入参透传（此前恒返回默认值，"单一来源"返回值不可信）
        "transform_seconds": _clamp_int(src.get("transform_seconds"),
                                        DEFAULT_BEHAVIOR_CFG["transform_seconds"],
                                        TRANSFORM_SECS_MIN, TRANSFORM_SECS_MAX),
    }


def _clamp_int(v, default, lo, hi):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def pick_idle_action(actions, mode, last_id=None, rng=None):
    """按模式挑一条待机动作（纯函数，可测）。返回 action|None。

    - sequential：按 order 轮流，跳过 last_id 的下一条（循环）
    - random：随机（避免与 last_id 相同，除非只有一条）
    - weighted：按 weight 加权随机
    - single：只播第一条启用的
    """
    live = [a for a in (actions or []) if isinstance(a, dict) and a.get("enabled", True)]
    if not live:
        return None
    live.sort(key=lambda x: int(x.get("order") or 0))
    if mode == "single" or len(live) == 1:
        return dict(live[0])
    if mode == "random":
        import random as _random
        r = (rng or _random)
        pool = [a for a in live if a.get("id") != last_id] or live
        return dict(r.choice(pool))
    if mode == "weighted":
        import random as _random
        r = (rng or _random)
        pool = [a for a in live if a.get("id") != last_id] or live
        weights = [max(0.001, _to_float(a.get("weight", 1.0), 1.0)) for a in pool]
        total = sum(weights)
        x = r.random() * total
        acc = 0.0
        for a, w in zip(pool, weights):
            acc += w
            if x <= acc:
                return dict(a)
        return dict(pool[-1])
    # sequential：找 last 的下一条
    idx = 0
    for i, a in enumerate(live):
        if a.get("id") == last_id:
            idx = (i + 1) % len(live)
            break
    return dict(live[idx])


def add_idle_action(cfg, behavior_id, weight=1.0):
    """向 cfg["idle_actions"] 追加一条（就地改 cfg，返回 (action|None, err)）。"""
    bid = str(behavior_id or "").strip()
    if not bid:
        return None, "请选择行为"
    idle = normalize_idle_cfg(cfg)
    if any(a["behavior_id"] == bid for a in idle["idle_actions"]):
        return None, "这条行为已经在待机列表里了"
    item = {"id": bid, "behavior_id": bid, "enabled": True,
            "weight": max(IDLE_WEIGHT_MIN, min(IDLE_WEIGHT_MAX, _to_float(weight, 1.0))),
            "order": len(idle["idle_actions"]) + 1}
    cfg["idle_actions"] = idle["idle_actions"] + [item]
    return dict(item), ""


def remove_idle_action(cfg, action_id):
    """从待机列表移除一条（就地改 cfg）。返回 (ok, err)。"""
    idle = normalize_idle_cfg(cfg)
    left = [a for a in idle["idle_actions"] if a["id"] != str(action_id or "")]
    if len(left) == len(idle["idle_actions"]):
        return False, "待机动作不存在"
    for i, a in enumerate(left, 1):
        a["order"] = i
    cfg["idle_actions"] = left
    return True, ""


def update_idle_action(cfg, action_id, enabled=None, weight=None, order=None):
    """改待机动作的启用/权重/顺序（就地改 cfg）。返回 (ok, err)。"""
    idle = normalize_idle_cfg(cfg)
    hit = None
    for a in idle["idle_actions"]:
        if a["id"] == str(action_id or ""):
            hit = a
            break
    if hit is None:
        return False, "待机动作不存在"
    if enabled is not None:
        hit["enabled"] = bool(enabled)
    if weight is not None:
        hit["weight"] = max(IDLE_WEIGHT_MIN, min(IDLE_WEIGHT_MAX, _to_float(weight, 1.0)))
    if order is not None:
        try:
            hit["order"] = max(1, int(order))
        except (TypeError, ValueError):
            return False, "顺序必须是数字"
    items = sorted(idle["idle_actions"], key=lambda x: x["order"])
    for i, a in enumerate(items, 1):
        a["order"] = i
    cfg["idle_actions"] = items
    return True, ""


def move_idle_action(cfg, action_id, delta):
    """上移/下移一条待机动作（delta=-1 上移，+1 下移）。返回 (ok, err)。"""
    idle = normalize_idle_cfg(cfg)
    items = idle["idle_actions"]
    idx = None
    for i, a in enumerate(items):
        if a["id"] == str(action_id or ""):
            idx = i
            break
    if idx is None:
        return False, "待机动作不存在"
    j = max(0, min(len(items) - 1, idx + int(delta)))
    if j == idx:
        return True, ""
    items[idx], items[j] = items[j], items[idx]
    for i, a in enumerate(items, 1):
        a["order"] = i
    cfg["idle_actions"] = items
    return True, ""


def set_idle_play_mode(cfg, mode):
    """设置播放模式（就地改 cfg）。返回 (ok, err)。"""
    if mode not in IDLE_PLAY_MODES:
        return False, "播放模式不合法"
    cfg["idle_play_mode"] = mode
    return True, ""


def validate_name(name):
    """行为名：ASCII 安全名（英文字母开头，字母/数字/下划线 ≤24 字符）。"""
    return isinstance(name, str) and bool(NAME_RE.match(name))


def validate_steps(steps):
    """校验并归一化动作序列。返回 (norm_steps, err)；非法即 (None, 中文原因)。

    纯函数：UI 预览、导入、保存、测试共用同一口径（不静默丢步，错误明确）。
    """
    if not isinstance(steps, list) or not steps:
        return None, "动作序列不能为空"
    if len(steps) > STEPS_MAX:
        return None, "最多 %d 步" % STEPS_MAX
    out = []
    for i, st in enumerate(steps):
        if not isinstance(st, dict):
            return None, "第 %d 步不是有效动作" % (i + 1)
        raw_act = st.get("act")
        act = raw_act
        # v2.3.1（P1-2）：旧动作名先迁移再判合法性（映射而非丢弃）。
        # act 可能是任意 JSON 值（list/dict 不可哈希），先判类型再查表，防 TypeError。
        alias = _LEGACY_ACT_ALIASES.get(raw_act) if isinstance(raw_act, str) else None
        if alias is not None and act not in BEHAVIOR_ACTS:
            act, default_name = alias
            st = dict(st)   # 不改调用方的入参
            if default_name and not str(st.get("name") or "").strip():
                st["name"] = default_name   # 旧条目把动作名写在 act 上 → 补成 play_action 的 name
        if act not in BEHAVIOR_ACTS:
            return None, "第 %d 步动作类型不合法：%s" % (i + 1, raw_act)
        item = {"act": act}
        if act == "play_action":
            name = str(st.get("name") or "").strip()
            if not name:
                return None, "第 %d 步缺少动作名" % (i + 1)
            item["name"] = name
        elif act == "say":
            text = str(st.get("text") or "").strip()
            if not text:
                return None, "第 %d 步台词为空" % (i + 1)
            item["text"] = text[:80]
        elif act == "voice":
            ev = str(st.get("event") or "")
            if ev not in BEHAVIOR_VOICE_EVENTS:
                return None, "第 %d 步语音事件不合法" % (i + 1)
            item["event"] = ev
        elif act == "emote":
            kind = str(st.get("kind") or "")
            if kind not in BEHAVIOR_EMOTES:
                return None, "第 %d 步表情不合法" % (i + 1)
            item["kind"] = kind
        elif act == "form":
            fname = str(st.get("name") or "").strip()
            if not fname:
                return None, "第 %d 步缺少形态名" % (i + 1)
            item["name"] = fname[:12]
        elif act == "sleep":
            pass
        elif act == "wait":
            try:
                ms = int(st.get("ms", 500))
            except (TypeError, ValueError):
                ms = 500
            item["ms"] = min(WAIT_MAX_MS, max(WAIT_MIN_MS, ms))
        elif act == "speak_line":
            lid = str(st.get("line_id") or "").strip()
            if not lid:
                return None, "第 %d 步缺少台词 id（去台词设置里复制或选择）" % (i + 1)
            item["line_id"] = lid[:40]
        elif act == "speak_dialogue":
            did = str(st.get("dialogue_id") or "").strip()
            if not did:
                return None, "第 %d 步缺少对白 id" % (i + 1)
            item["dialogue_id"] = did[:40]
        out.append(item)
    return out, ""


class BehaviorService:
    """行为库：behaviors.json 持久化 + 增删改查 + 导入导出。主线程调用。"""

    def __init__(self, data_dir, log=None):
        self._index = os.path.join(data_dir, "behaviors.json")
        self._log = log or pet_log.log_error
        self._behaviors = {}  # {id: behavior}
        self._load()

    # ---------- 持久化 ----------
    def _load(self):
        """读行为库并归一化；**清洗过就回写愈合**（P0-2 / E）。

        此前坏条目只从内存丢掉、不落盘：磁盘上的坏数据每次启动重报
        （error.log 实测「动作序列不能为空」「动作类型不合法：jump」）。
        现在只要"损坏 / 丢条目 / 迁移或归一化确实改了内容"就 _save() 一次，
        下次启动直接读干净文件（旧动作别名迁移的结果也借此写回磁盘）。
        """
        data, corrupted = pet_io.read_json_or(self._index, dict, log=self._log)
        self._behaviors = {}
        dirty = corrupted   # 文件本身坏了：读完立刻用合法空库覆盖
        if isinstance(data, dict):
            for b in (data.get("behaviors") or []):
                nb, err = self._norm_behavior(b)
                if nb is None:
                    # 坏条目=用户资产损坏：记日志留痕（不弹窗，静默恢复空库）
                    self._log("behavior index dropped bad entry: %s" % (err or "格式非法"))
                    dirty = True
                elif nb["id"] not in self._behaviors:
                    self._behaviors[nb["id"]] = nb
                    if nb != b:
                        dirty = True   # 别名迁移/字段清洗：磁盘与内存口径必须一致
        if dirty:
            # P0-C：愈合/迁移回写**之前**先留 .bak（与 pet_io.heal_json 同口径）——
            # 原先这条自建"读 + 回写"路径没有备份，判错/迁移有 bug 就无从恢复。
            pet_io.backup_before_heal(self._index, self._log)
            self._save()   # 愈合回写（走 pet_io 的同一把路径锁，与在途写者串行）

    def _save(self):
        pet_io.atomic_write_json(self._index, {"behaviors": list(self._behaviors.values())},
                                 log=self._log)

    @staticmethod
    def _norm_behavior(b):
        """单条行为归一化：非法结构/非法名/非法序列返回 (None, err)。"""
        if not isinstance(b, dict):
            return None, "行为条目不是对象"
        bid = str(b.get("id") or "").strip()
        if len(bid) != 8 or any(c not in "0123456789abcdef" for c in bid):
            return None, "行为 id 非法"
        name = str(b.get("name") or "").strip()
        if not validate_name(name):
            return None, "行为名不合法（英文字母开头，字母/数字/下划线）"
        steps, err = validate_steps(b.get("steps"))
        if steps is None:
            return None, err
        # v2.3.1（兼容审查 M1）：保留未知键（复制原条目后覆盖已知键），
        # 避免"读取时归一化回写"把用户手加字段/未来字段永久删掉
        out = dict(b)
        out.update({"id": bid, "name": name, "steps": steps})
        return out, ""

    # ---------- 查改 ----------
    def list(self):
        """全部行为（深拷贝，按 id 排序稳定输出；调用方变异不影响库内数据）。"""
        return [copy.deepcopy(b) for b in sorted(self._behaviors.values(), key=lambda x: x["id"])]

    def get(self, bid):
        b = self._behaviors.get(str(bid or ""))
        return copy.deepcopy(b) if b is not None else None

    def add(self, name, steps):
        """新增行为。返回 (behavior|None, err)。"""
        name = str(name or "").strip()
        if not validate_name(name):
            return None, "行为名不合法（英文字母开头，字母/数字/下划线）"
        norm, err = validate_steps(steps)
        if norm is None:
            return None, err
        bid = uuid.uuid4().hex[:8]
        while bid in self._behaviors:
            bid = uuid.uuid4().hex[:8]
        b = {"id": bid, "name": name, "steps": norm}
        self._behaviors[bid] = b
        self._save()
        return dict(b), ""

    def update(self, bid, name, steps):
        """改名/改序列（id 不变）。返回 (ok, err)。"""
        bid = str(bid or "")
        if bid not in self._behaviors:
            return False, "行为不存在"
        name = str(name or "").strip()
        if not validate_name(name):
            return False, "行为名不合法（英文字母开头，字母/数字/下划线）"
        norm, err = validate_steps(steps)
        if norm is None:
            return False, err
        self._behaviors[bid]["name"] = name
        self._behaviors[bid]["steps"] = norm
        self._save()
        return True, ""

    def delete(self, bid):
        bid = str(bid or "")
        if bid not in self._behaviors:
            return False, "行为不存在"
        self._behaviors.pop(bid, None)
        self._save()
        return True, ""

    # ---------- 导入 / 导出（行为资源） ----------
    def import_file(self, path):
        """导入行为资源 JSON：单条 {"name","steps"} / {"behavior":{...}} /
        全库格式 {"behaviors":[...]}（取数组第一条）。坏结构明确报错不抛异常。
        成功返回 (behavior|None, err)；重复导入生成新 id。"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return None, "文件读取失败：%s" % e
        if isinstance(data, dict) and "behavior" in data:
            data = data["behavior"]
        if isinstance(data, dict) and "behaviors" in data:
            bl = data.get("behaviors")
            if not isinstance(bl, list) or not bl:
                return None, "行为文件内容不合法：behaviors 应为非空数组"
            data = bl[0]
        nb, err = self._norm_behavior(data)
        if nb is None:
            return None, "行为文件内容不合法：%s" % err
        nb["id"] = uuid.uuid4().hex[:8]
        while nb["id"] in self._behaviors:
            nb["id"] = uuid.uuid4().hex[:8]
        self._behaviors[nb["id"]] = nb
        self._save()
        return dict(nb), ""

    def export_file(self, bid, path):
        """导出单条行为为 JSON 资源文件。返回 (ok, err)。"""
        b = self.get(bid)
        if b is None:
            return False, "行为不存在"
        err = pet_io.atomic_write_json(path, {"behavior": b}, log=self._log)
        if err is None:
            return True, ""
        return False, "导出失败：%s" % err

    # ---------- 待机行为 ----------
    def idle(self, cfg_getter):
        """（v2.0.2 兼容）单条待机行为：旧键 idle_behavior 指定的那条。"""
        cfg = cfg_getter() or {}
        bid = str(cfg.get("idle_behavior") or "").strip()
        return self.get(bid) if bid else None

    def idle_config(self, cfg_getter):
        """v2.1：归一化后的待机配置（单一来源）。"""
        return normalize_idle_cfg(cfg_getter() or {})

    def idle_pick(self, cfg_getter, last_id=None):
        """v2.1：按模式挑一条待机动作并解析成行为。

        返回 (behavior|None, action_id|None, err)：列表为空/全部失效时 behavior=None
        且 err 说明原因（调用方决定是否提示，静默不算失败）。
        """
        idle = normalize_idle_cfg(cfg_getter() or {})
        actions = [a for a in idle["idle_actions"] if self.get(a["behavior_id"]) is not None]
        _missing = len(idle["idle_actions"]) - len(actions)
        if not actions:
            if idle["idle_actions"]:
                return None, None, "待机列表里的行为都不在了（去待机设置里重新选）"
            return None, None, ""
        # M6 修复：部分失效也要提示（此前静默跳过，用户不知道列表里有坏条目）
        warn = ("待机列表里有 %d 条行为不见了（去待机设置里重新选）" % _missing) if _missing else ""
        picked = pick_idle_action(actions, idle["idle_play_mode"], last_id)
        if picked is None:
            return None, None, ""
        b = self.get(picked["behavior_id"])
        if b is None:
            return None, picked["id"], "待机行为已被删除"
        return b, picked["id"], warn  # warn 非空=有部分条目失效，调用方据此提示


if __name__ == "__main__":
    # 命令行冒烟：无 GUI 自检（python pet_behaviors.py）
    svc = BehaviorService(os.path.join(tempfile.mkdtemp(prefix="bhv_"), "x"))
    b, err = svc.add("wave", [{"act": "say", "text": "嗨~"}, {"act": "wait", "ms": 200}])
    assert b is not None and not err, err
    assert svc.get(b["id"])["steps"][0]["act"] == "say"
    b2, _e2 = svc.add("talk", [{"act": "speak_line", "line_id": "bi_idle_01"}])
    assert b2 is not None
    assert svc.delete(b["id"]) == (True, "")
    _bad, _e = validate_steps([{"act": "fly"}])
    assert _bad is None and "不合法" in _e
    assert validate_steps([{"act": "speak_line"}])[0] is None  # 缺 line_id 报错
    # v2.1 待机：归一化 / 选择 / 列表增删
    _cfg = {}
    assert normalize_idle_cfg(_cfg)["idle_trigger_delay"] == 8
    _cfg["idle_behavior"] = b2["id"]      # 旧键迁移
    assert normalize_idle_cfg(_cfg)["idle_actions"][0]["behavior_id"] == b2["id"]
    assert add_idle_action(_cfg, b2["id"])[0] is None  # 已在列表 → 拒绝重复
    _cfg["idle_behavior"] = ""   # 清掉旧键（迁移后不再需要）
    _cfg["idle_actions"] = []
    _a1, _ = add_idle_action(_cfg, b2["id"], 2.0)
    assert _a1 is not None and _cfg["idle_actions"][0]["weight"] == 2.0
    assert update_idle_action(_cfg, _a1["id"], enabled=False)[0] is True
    assert pick_idle_action(_cfg["idle_actions"], "sequential") is None  # 全禁用
    update_idle_action(_cfg, _a1["id"], enabled=True)
    assert remove_idle_action(_cfg, _a1["id"]) == (True, "")
    assert remove_idle_action(_cfg, "nope")[0] is False
    _acts = [{"id": "a", "behavior_id": "a", "enabled": True, "weight": 1, "order": 1},
             {"id": "b", "behavior_id": "b", "enabled": True, "weight": 1, "order": 2}]
    assert pick_idle_action(_acts, "sequential", "a")["id"] == "b"  # 轮流
    assert pick_idle_action(_acts, "sequential", "b")["id"] == "a"  # 循环回第一条
    assert pick_idle_action(_acts, "single")["id"] == "a"
    assert pick_idle_action(_acts, "random")["id"] in ("a", "b")
    assert pick_idle_action(_acts, "weighted")["id"] in ("a", "b")
    print("SMOKE OK")