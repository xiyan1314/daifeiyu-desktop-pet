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

v2.9.0（代理 B 的后端与契约，全部 Qt-free 纯逻辑）：
- action_choices(pet)：行为步骤「动作」参数的**候选动作名**（可编辑下拉的唯一来源；
  **候选 ≠ 白名单**——候选之外的老动作名照样读入/保存）。
- remove_idle_actions_for_behavior(cfg, bid)：删除行为时清掉待机列表里的引用
  （幂等；没有引用时一个字节都不动 cfg）。
- idle_combo_state(cfg, name_getter=None)：待机下拉该显示什么**由配置推导**（取代硬编码）。
- idle_single_change(cfg, bid, apply=False)：把「换成单条」先算后写，返回值如实报告会丢几条。
- test_play_target(save_ok, bid)：「试播」的判据——保存没成功就不许播（播的必须是刚保存的内容）。
"""

import copy
import json
import os
import re
import tempfile
import uuid

import pet_io   # v2.3.1：全仓共用原子写/安全读（分锁 + 线程唯一临时名 + replace 重试）
import pet_log
# v2.9.0（B1）：行为步骤「动作」候选的**内建帧动作**来源（单一来源 = pet_resources.ANIM_ACTIONS，
# 不在本模块抄第二份）。pet_resources 是 Qt-free 无环模块（只依赖 pet_io/pet_log），
# 不会把本模块变成 Qt 依赖，也不会与 pet_config（它 import 本模块）成环。
import pet_resources

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
# v2.9.0（B1）：play_action 的**内建点播分支**（与 桌宠.PetWindow._action_exists 的第一个分支
# 同源）。内建帧动作 idle/eat/poke/sleep 不在这里抄第二份——单一来源是 pet_resources.ANIM_ACTIONS。
# "none" 是 ActionService.play_action 里的**显式空操作**，它是 _action_exists 的合法值、
# 但**不是"可播动作"**，所以不进候选清单（下拉里列一个"什么都不做"只会让用户困惑）；
# 用户手填 "none" 依旧能保存（validate_steps 不校验名字存在性）。
BUILTIN_PLAY_ACTIONS = ("jump", "emote")
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


def action_choices(pet):
    """v2.9.0（B1）：行为步骤「动作」参数的**候选动作名**（单一来源，去重 + 稳定排序）。

    = pet_resources.ANIM_ACTIONS（内建帧动作 idle/eat/poke/sleep）
      ∪ BUILTIN_PLAY_ACTIONS（内建点播分支 jump/emote）
      ∪ pet.custom_actions()（当前角色当前形态的命名帧动作 / 程序化合成动作）
      ∪ 运行期已注册帧集 pet.anim._sets 的键（"此刻真的能播"的最强证据）

    **这是候选，不是白名单**：调用方（行为设置把参数改成"可编辑下拉"）必须允许用户手填
    候选之外的任何名字——老行为文件里的动作名不在候选里，也必须原样读入、原样保存。
    本模块 validate_steps 对 play_action 只校验"非空"，从不校验名字是否存在
    （存在性校验在**播放时**，见桌宠._behavior_step 的"动作不见了"气泡）。
    本函数只读不写、不改 pet 的任何状态，也不过问调用方手里的值。

    默认角色（无自定义角色 → custom_actions() 返回 []）也有候选：内建动作恒在。
    pet 为 None / 缺属性（测试替身、无角色场景）按空处理，不抛异常。
    """
    names = set(pet_resources.ANIM_ACTIONS)
    names.update(BUILTIN_PLAY_ACTIONS)
    _getter = getattr(pet, "custom_actions", None)
    if callable(_getter):
        try:
            _custom = _getter() or []
        except Exception as e:
            # 读角色索引失败不该让"选动作"整条路打不开：退回内建候选并留痕
            _custom = []
            pet_log.log_error("action_choices: 读取自定义动作失败，只列内建动作（%s）" % e)
        for _item in _custom:
            # custom_actions() 的条目是 (name, kind)；也容忍直接给字符串的替身
            _name = _item[0] if isinstance(_item, (tuple, list)) and _item else _item
            _name = str(_name or "").strip()
            if _name:
                names.add(_name)
    _sets = getattr(getattr(pet, "anim", None), "_sets", None)
    if isinstance(_sets, dict):
        for _k in _sets:
            _k = str(_k or "").strip()
            if _k:
                names.add(_k)
    names.discard("none")
    names.discard("")
    return sorted(names)


def remove_idle_actions_for_behavior(cfg, behavior_id):
    """v2.9.0（B4）：删除/失效某行为时，清掉待机列表里对它的引用（就地改 cfg）。

    与 add_idle_action / remove_idle_action / move_idle_action 同族（同样就地改 cfg、
    同样返回 (值, err)）。返回 (removed, err)：removed = 被清掉的待机动作条目
    （深拷贝 list[dict]，顺序即原顺序），调用方据此给回执（"已同时从待机列表移除 N 条"）。
    err 只在 cfg 不是 dict 时非空。

    语义（三条硬保证）：
      1. **幂等**：没有引用时返回 ([], "") 且**一个字节都不动 cfg**；连调两次第二次必为 ([], "")。
      2. **不误伤**：只按 behavior_id 精确匹配，其它条目**原样保留**（不重写它们的字段，
         包括用户手加的未知键）；被清掉后剩余的 order 重排为 1..N（只改 order）。
      3. **顺带清旧键**：cfg["idle_behavior"] == 该 id 时一并清空——它是 v2.0.2 的单条旧键，
         normalize_idle_cfg 会把它迁进 idle_actions；不清就会"复活"被删的行为。
        （pet_config.normalize_cfg 每次加载都把该键置空 → 只判这个旧键的清理分支是死分支。）

    这就是 pet_dialogs.BehaviorDialog._delete 里那条死分支的正确语义（旧写法只判恒为 "" 的
    cfg["idle_behavior"]，永远判不中）。
    """
    if not isinstance(cfg, dict):
        return [], "配置不可用"
    bid = str(behavior_id or "").strip()
    if not bid:
        return [], ""
    idle = normalize_idle_cfg(cfg)      # 归一化视图：只用来判"到底有没有引用"
    removed = [dict(a) for a in idle["idle_actions"] if a["behavior_id"] == bid]
    legacy_hit = str(cfg.get("idle_behavior") or "").strip() == bid
    if not removed and not legacy_hit:
        return [], ""                   # 没有引用：原样返回，不碰 cfg
    # 从**原始**列表重建（不是拿归一化结果覆盖），保证别的条目连未知键都不变
    raw = cfg.get("idle_actions")
    left = []
    if isinstance(raw, list):
        for a in raw:
            if isinstance(a, dict) and str(a.get("behavior_id") or "").strip() == bid:
                continue
            left.append(a)
    _n = 0
    for a in left:
        if isinstance(a, dict):
            _n += 1
            a["order"] = _n
    cfg["idle_actions"] = left
    if legacy_hit:
        cfg["idle_behavior"] = ""
    return removed, ""


# v2.9.0（B5）：待机下拉的"不启用"档文案（UI 文案的**单一来源**，不许在对话框里硬编码第二份）
IDLE_COMBO_OFF_LABEL = "（不启用 → 默认待机）"


def idle_combo_state(cfg, name_getter=None):
    """v2.9.0（B5）：**由配置推导**「待机行为」下拉此刻该显示什么（取代硬编码"不启用"）。

    返回 dict：
      mode          "off" | "single" | "list"
                    off    = 待机列表为空（真的不启用）
                    single = 只播指定的一条（play_mode == "single" 且列表正好 1 条）
                    list   = 按待机设置的多条（顺序/随机/权重，或 single 但列表不止 1 条）
      behavior_id   mode == "single" 时那条的 behavior_id，否则 ""
      count         归一化后条目数（不被 enabled 过滤）
      enabled_count 其中 enabled 的条数
      play_mode     归一化后的播放模式（原样给出，供 UI 显示"顺序轮流/随机/…"）
      plays_first_only  True = play_mode == "single" 但列表不止一条（**只有第一条会播**，
                        这是个真实的配置状态，不该被显示成"不启用"）
      label         可直接放进下拉的文案（UI 不必自己拼）
      show_list_hint True = 该显示成"去待机设置里改"的只读态，而不是一个可选项

    name_getter：可选，签名 name_getter(behavior_id) -> 行为名；给了就用「空闲时：<名>」，
    没给/返回空/抛异常一律回落到「空闲时：<id>」（**绝不因为查名字失败而让下拉打不开**）。
    """
    idle = normalize_idle_cfg(cfg)
    actions = idle["idle_actions"]
    count = len(actions)
    enabled_count = len([a for a in actions if a.get("enabled", True)])
    play_mode = idle["idle_play_mode"]
    state = {"behavior_id": "", "count": count, "enabled_count": enabled_count,
             "play_mode": play_mode, "plays_first_only": False, "show_list_hint": False}
    if count == 0:
        state.update({"mode": "off", "label": IDLE_COMBO_OFF_LABEL})
        return state
    if play_mode == "single" and count == 1:
        bid = actions[0]["behavior_id"]
        name = ""
        if callable(name_getter):
            try:
                name = str(name_getter(bid) or "").strip()
            except Exception as e:
                name = ""
                pet_log.log_error("idle_combo_state: 查行为名失败，回落显示 id（%s）" % e)
        state.update({"mode": "single", "behavior_id": bid, "label": "空闲时：" + (name or bid)})
        return state
    first_only = (play_mode == "single")
    state.update({"mode": "list", "plays_first_only": first_only, "show_list_hint": True,
                  "label": ("只播第一条（列表里共 %d 条）" % count) if first_only
                           else ("按待机设置（%d 条动作）" % count)})
    return state


def idle_single_change(cfg, behavior_id, apply=False):
    """v2.9.0（B5）：把「待机 = 只播这一条」这件事**先算清楚再动手**（不许静默丢条目）。

    行为设置里那个「待机行为」下拉的语义就是"换成单条"；列表里原本有多条时，它是**数据
    损失面**——所以这里把"会丢什么"变成返回值：

      返回 (dropped, err)：dropped = 会被丢弃的其它条目（深拷贝 list[dict]）。
      apply=False（默认）：**只算不写**，cfg 一个字节都不动 → UI 拿它做确认文案；
      apply=True        ：就地改 cfg（idle_actions=[这一条]，idle_play_mode="single"）。

    behavior_id 为空 = 下拉里的「不启用」那一档：dropped = 现有全部条目，
    apply 时清空 idle_actions 并把模式回落 sequential。

    两条硬保证：
      1. **条目数只在用户明确选"换成单条/不启用"时才减少**，且减少量必然等于 len(dropped)
         （UI 只要把 dropped 报出去，就不存在"静默"丢条目）；
      2. apply 时**同时清掉旧键 cfg["idle_behavior"]** —— 不清的话 normalize_idle_cfg 会把
         它迁回 idle_actions，被"丢掉"的那条会自己复活（条目数不减反增）。
    """
    if not isinstance(cfg, dict):
        return [], "配置不可用"
    idle = normalize_idle_cfg(cfg)
    actions = idle["idle_actions"]
    bid = str(behavior_id or "").strip()
    if not bid:
        dropped = [dict(a) for a in actions]
        if apply:
            cfg["idle_actions"] = []
            cfg["idle_play_mode"] = "sequential"
            cfg["idle_behavior"] = ""
        return dropped, ""
    dropped = [dict(a) for a in actions if a["behavior_id"] != bid]
    if apply:
        keep = None
        raw = cfg.get("idle_actions")
        if isinstance(raw, list):
            for a in raw:
                if isinstance(a, dict) and str(a.get("behavior_id") or "").strip() == bid:
                    keep = dict(a)          # 原条目照搬（含用户手加的未知键）
                    break
        if keep is None:
            keep = {"id": bid, "behavior_id": bid, "enabled": True, "weight": 1.0}
        keep["behavior_id"] = bid
        keep["enabled"] = True              # 用户在下拉里明确选了它 → 它必须真的会播
        keep["order"] = 1
        cfg["idle_actions"] = [keep]
        cfg["idle_play_mode"] = "single"
        cfg["idle_behavior"] = ""
    return dropped, ""


def test_play_target(save_ok, behavior_id):
    """v2.9.0（B6）：「试播」到底该播哪一条（纯函数，单一来源）。

    返回 (bid|None, reason)：bid 非空 = 可以播它；bid 为空 = **不许播**，reason 是给用户的
    中文原因（调用方放进内联状态行，不弹气泡）。

    规则只有一条：**试播播的必须是"刚保存成功的内容"**。
      · save_ok 不为真 → (None, 中文原因)
      · save_ok 为真但没有可播的 id → (None, "先保存一个行为，再点「试播」")
      · 否则 → (str(behavior_id), "")

    为什么需要它：改前 BehaviorDialog._test_play 的判据是"只要有 _editing_id 就播"，而
    _editing_id 在**保存失败时仍指向上一次成功保存的那条**（保存失败只弹了警告、没有清 id）
    → 用户点了「试播」，播的却是旧内容，还以为在看自己的修改（审计实测 3 号）。
    **save_ok 传 None/未知一律按"没成功"处理**（fail-safe：宁可这次不播，也不播没验证过的内容）。
    """
    if not save_ok:
        return None, ("保存没成功，这次不试播——试播的永远是刚保存的内容，"
                      "不是上一次保存下来的旧内容")
    bid = str(behavior_id or "").strip()
    if not bid:
        return None, "先保存一个行为，再点「试播」"
    return bid, ""


class BehaviorService:
    """行为库：behaviors.json 持久化 + 增删改查 + 导入导出。主线程调用。"""

    def __init__(self, data_dir, log=None):
        self._index = os.path.join(data_dir, "behaviors.json")
        self._log = log or pet_log.log_error
        self._behaviors = {}  # {id: behavior}
        # v2.4.2（Q）：behaviors.json 顶层未知键的暂存（读取时收集，_save 时原样带回）
        self._top_extra = {}
        # v2.4.2（兼容 M4）：这次启动"文件在磁盘上却没读到"（编码不是 UTF-8 且回退也解不开 /
        # 权限 / 共享占用）或"按回退编码读到、原文不是 UTF-8"。两种情况下用户**第一次**
        # 增删行为都会把原文改掉，所以首次写前必须先留一份 .bak——与 pet_lines/pet_book 同口径。
        self._read_failed = False
        self._reencoded_read = False
        self._backed_before_write = False
        self._load()

    # ---------- 持久化 ----------
    def _load(self):
        """读行为库并归一化；**清洗过就回写愈合**（P0-2 / E）。

        此前坏条目只从内存丢掉、不落盘：磁盘上的坏数据每次启动重报
        （error.log 实测「动作序列不能为空」「动作类型不合法：jump」）。
        现在只要"损坏 / 丢条目 / 迁移或归一化确实改了内容"就愈合回写一次，
        下次启动直接读干净文件（旧动作别名迁移的结果也借此写回磁盘）。

        v2.4.1（A 区一致性收口）：自建"读 + 清洗 + 手工 backup + _save"环改成
        pet_io.heal_json（清洗判据走它的 normalize 入参）——读、判、回写都在**同一把
        路径锁内**完成，与闹钟/台词/角色索引共用同一套 .bak 与日志口径；不再自己维护
        一份（自建环的两个弱点：从"读到坏"到"回写"之间本进程写者能插进来；备份与回写
        是两次独立操作，口径容易与 pet_io 漂移）。
        """
        self._behaviors = {}
        self._top_extra = {}
        self._read_failed = False
        self._reencoded_read = False
        self._backed_before_write = False
        _normalize_ran = []      # 判据跑过 = pet_io 这次**真读到了**文件内容（见文件末尾）

        def _normalize(data):
            """内层结构判据（交给 heal_json）→ (fixed, reason)。

            reason 非空 = 内存态与盘上内容不一致（损坏 / 丢条目 / 别名迁移）→ 需要回写愈合；
            为空 = **一个字节都不写**。data 一定是 dict（read_json_ex 的 expect=dict 兜着）。
            """
            _normalize_ran.append(True)   # 判据只在"真读到内容"时才被调（见 read_json_ex 的 unreadable 口径）
            clean = {}
            dirty = False
            for b in (data.get("behaviors") or []):
                nb, err = self._norm_behavior(b)
                if nb is None:
                    # 坏条目=用户资产损坏：记日志留痕（不弹窗，静默恢复空库）
                    self._log("behavior index dropped bad entry: %s" % (err or "格式非法"))
                    dirty = True
                elif nb["id"] not in clean:
                    clean[nb["id"]] = nb
                    if nb != b:
                        dirty = True   # 别名迁移/字段清洗：磁盘与内存口径必须一致
            # 内存态与**本次真读到的**内容一致（含愈合后的）；一个字节都不写时也走这里
            self._behaviors = clean
            self._top_extra = {k: v for k, v in data.items() if k != "behaviors"}
            if not dirty:
                return data, None
            # v2.4.2（Q）：愈合回写**保留顶层未知键**（与 pet_alarm._load 同口径）。
            # 条目级未知键早就保留（_norm_behavior 复制原条目再覆盖已知键），顶层此前整份重建 →
            # 用户手加的段/未来版本的键在愈合时永久消失。fixed 只覆盖已知段，坏条目不回带。
            fixed = dict(data)
            fixed["behaviors"] = list(clean.values())
            return fixed, "behaviors 索引含坏条目/非法结构"

        _data, _corrupted = pet_io.heal_json(self._index, lambda: {"behaviors": []},
                                             log=self._log, normalize=_normalize)
        # v2.4.2（兼容 M4）：heal_json 的 unreadable 分支**不跑判据**（那时手里只有 factory()
        # 默认值，拿它判"脏"就是对着没读到过的文件回写——v2.4.1 找茬 S1 的口径，不动）。
        # 于是"判据没跑过 + 文件确实存在"就等于"这次没读到"：编码不是 UTF-8（记事本「ANSI」
        # 另存）或权限/共享占用。前者先试编码回退（与 pet_lines 同一个 pet_io 实现）——
        # 能读到就一条不丢；连回退都解不开才置 _read_failed（首次写前留 .bak，见 _save）。
        # 修之前这里是**零保护**：GBK 的 behaviors.json 读到空库，用户第一次加行为就把原文
        # 整份覆盖成 {"behaviors": [新条目]}，旧条目与自定义顶层键一起消失、不可恢复。
        if not _normalize_ran and not _corrupted and os.path.exists(self._index):
            fb, _enc = pet_io.read_json_fallback(self._index, expect=dict, log=self._log)
            if fb is not None:
                _normalize(fb)          # 同一套清洗判据（只改内存态，不写盘）
                self._reencoded_read = bool(_enc)
                if _enc:
                    self._log("behaviors.json 不是 UTF-8，已按 %s 读取（内容正常，未改写原文件）"
                              % str(_enc).upper())
            else:
                self._read_failed = True
                self._log("behaviors.json 在磁盘上但读不出来（编码/占用），本次按空库继续；"
                          "改动前会先备份成 behaviors.json.bak")

    def _save(self):
        # v2.4.2（Q）：顶层未知键原样带回（与 pet_alarm._save 同口径）。
        data = dict(self._top_extra)
        data["behaviors"] = list(self._behaviors.values())
        # v2.4.2（兼容 M4）：本次启动没读到原文（脏读）→ 这一写会把用户原文整份覆盖成内存里的
        # 空库 + 新条目；回退读到的原文同样会在这一写里被改成 UTF-8。两种情况下**写前**先留
        # 一份 .bak（一次脏读只留一份：写失败重试不重复覆盖，成功后清标记回到正常路径）。
        _reencode = self._read_failed or self._reencoded_read
        if _reencode and not self._backed_before_write:
            if pet_io.backup_before_overwrite(self._index, self._log):
                self._backed_before_write = True
        err = pet_io.atomic_write_json(self._index, data, log=self._log)
        if err is None and _reencode:
            _had_bak = self._backed_before_write
            _why = ("原文件不是 UTF-8（回退读取），本次已转存为 UTF-8"
                    if self._reencoded_read else "原文件此前读不到")
            self._read_failed = False
            self._reencoded_read = False
            self._backed_before_write = False
            self._log("behaviors.json 已按 UTF-8 重建（%s；%s）"
                      % (_why, "原文已留 .bak" if _had_bak else "**备份失败**，原文已被覆盖"))

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

    def find_by_name(self, name, exclude_id=None):
        """按名字找一条行为（**R3：重名判据的唯一来源**）。返回深拷贝或 None。

        为什么要有它：`add` 只管名字合不合法、不查重名，于是两次 `add("same")` 都进库，
        列表里出现两条同名条目、用户分辨不出哪条是哪条（三审记账为"静默"）。判据只写在
        这里一份，UI 侧（`pet_dialogs.BehaviorDialog`）用它决定"要不要问用户"——
        **判据与问法是两件事**：这里答"撞没撞"，问不问、怎么问由调用方决定。
        `exclude_id` 用于"改自己名字"的场景（自己不算撞名，否则每次改名都会撞上自己）。
        """
        key = str(name or "").strip()
        if not key:
            return None
        ex = str(exclude_id or "")
        for b in sorted(self._behaviors.values(), key=lambda x: x["id"]):
            if ex and b["id"] == ex:
                continue
            if str(b.get("name") or "").strip() == key:
                return copy.deepcopy(b)
        return None

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
    # v2.9.0：候选动作 / 待机引用清理 / 下拉状态推导
    assert "jump" in action_choices(None) and "idle" in action_choices(None)
    _c2 = {"idle_actions": [{"behavior_id": "aaa", "order": 1},
                            {"behavior_id": "bbb", "order": 2}]}
    assert remove_idle_actions_for_behavior(_c2, "aaa")[0][0]["behavior_id"] == "aaa"
    assert [a["behavior_id"] for a in _c2["idle_actions"]] == ["bbb"]
    assert remove_idle_actions_for_behavior(_c2, "aaa") == ([], "")   # 幂等
    assert idle_combo_state(_c2)["mode"] == "list"
    _c3 = {"idle_actions": [{"behavior_id": "aaa", "order": 1},
                            {"behavior_id": "bbb", "order": 2}],
           "idle_play_mode": "sequential"}
    assert [a["behavior_id"] for a in idle_single_change(_c3, "bbb")[0]] == ["aaa"]  # 只算不写
    assert len(_c3["idle_actions"]) == 2, "apply=False 不许改 cfg"
    idle_single_change(_c3, "bbb", apply=True)
    assert [a["behavior_id"] for a in _c3["idle_actions"]] == ["bbb"]
    assert _c3["idle_play_mode"] == "single" and idle_combo_state(_c3)["mode"] == "single"
    print("SMOKE OK")