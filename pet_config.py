# -*- coding: utf-8 -*-
"""
配置辅助模块：DPAPI 加解密 + 配置归一化 + diff 落盘核心。

独立模块：不 import 桌宠.py（避免循环依赖）。
load_config / save_config 因 tests/_verify_v13 monkeypatch 桌宠.CONFIG_PATH 而保留在桌宠.py，
本模块只承载无模块全局依赖的纯逻辑部分。
"""
import base64
import ctypes
import json
import math
import threading

# v2.2.5：配置写盘互斥锁 + 唯一临时名。语音 worker 线程（云端 TTS 首次克隆出 voice_id 时
# 会就地改共享 cfg 并保存）与主线程（约 20 个保存点）此前共用同一个 "config.json.tmp"，
# os.replace 可能因共享冲突抛 PermissionError 被 except 吞掉 → 该次配置写入静默丢失。
_CFG_WRITE_LOCK = threading.Lock()

import pet_io  # v2.3.1：全仓共用原子写（分锁 + 线程唯一临时名 + replace 重试）
import pet_log  # P1-手感：物理参数非法时记日志（pet_log 无任何依赖，安全）
import pet_plugin_index  # v2.8.0：远端索引地址的判据**单一来源**（Qt-free，无环：
                         #   pet_plugin_index → pet_export / pet_io / pet_plugin，都不回头 import 本模块）
import pet_physics  # P1-手感：默认值单一来源（pet_physics 无 Qt 依赖，无环）
import pet_voice  # v2.0：语音配置归一化（pet_voice 无环）
import pet_behaviors  # v2.0.2：行为配置默认值单一来源（pet_behaviors 无环）
import pet_chat  # v2.0.4：AI 默认接口/模型单一来源（pet_chat 无 Qt、无环）

# ---------------- v2.8.0 · Phase 3：远端插件索引地址（plugin_index_url） ----------------
# 键名/默认值在这里**再导出**（字面量只有 pet_plugin_index 那一份），远端地址的判据也只有
# 那一份（remote_base_reason：只收 https、本地路径/file:// 一律拒、超长拒）——本模块只把它
# 包成 (ok, msg) 给界面用，绝不抄第二套判断（两套判据 = 早晚漂开）。
PLUGIN_INDEX_URL_KEY = pet_plugin_index.PLUGIN_INDEX_URL_KEY
PLUGIN_INDEX_URL_DEFAULT = ""      # 空 = 只读**随包**索引（不联网、离线也装得上官方内容）

# 上界与设置对话框同口径（pet_dialogs.PhysicsDialog 的 spinbox 范围）
_PHYS_MAX = {"gravity": 10000.0, "restitution": 1.0,
             "groundFriction": 50.0, "throwPower": 10.0}


def normalize_plugin_index_url(value):
    """配置里的 plugin_index_url → 归一值（null / 空白 → ""＝随包索引）。

    只管**类型与空白**：非字符串按全仓 string 键同款折成字符串（手改 config.json 写成 123
    时不会崩，也不会凭空消失），**地址合法性一律交给 validate_plugin_index_url /
    remote_base_reason 判**——归一管"长什么样"，判据管"能不能用"，两件事不混。
    """
    if value is None:
        return PLUGIN_INDEX_URL_DEFAULT
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def validate_plugin_index_url(url):
    """远端索引地址 → (ok, msg)。**空串算合法**（= 清除远端、回到随包索引）。

    给界面"当场拒绝 + 说清为什么"用；判据本身在 pet_plugin_index.remote_base_reason
    （与真正取数时**同一个**函数，不存在"界面放行、取数时才发现不对"的两套口径）。
    """
    text = normalize_plugin_index_url(url)
    if not text:
        return True, ""
    bad = pet_plugin_index.remote_base_reason(text)
    if bad:
        return False, bad
    return True, ""


def normalize_physics(ph):
    """P1-手感：物理参数 dict 归一化（load_config 与 apply_physics 共用）。

    默认值取 pet_physics.DEFAULT_PHYSICS（单一来源）；负数/非数字回退默认、
    上界钳制，非法键收集进返回 dict 的 "_fixed" 列表（调用方记日志后剥除）。"""
    pd = dict(pet_physics.DEFAULT_PHYSICS)
    bad = []
    for k in ("gravity", "restitution", "groundFriction", "throwPower"):
        try:
            v = float(ph.get(k, pd[k]))
            if v < 0:
                raise ValueError
            pd[k] = min(v, _PHYS_MAX[k])
        except (TypeError, ValueError):
            bad.append(k)
    pd["enabled"] = _to_bool(ph.get("enabled", False), False)
    pd["ceilingBounce"] = _to_bool(ph.get("ceilingBounce", True), True)
    if bad:
        pd["_fixed"] = bad
    return pd
from ctypes import wintypes

from PySide6.QtGui import QColor

# ---------------- 安全：Windows DPAPI 加密 API Key ----------------
# 说明：未使用 optional entropy——密文可被同一 Windows 用户上下文内的进程解密；
# 威胁边界 = 账户隔离（DPAPI-CurrentUser 的业界标准用法）。
class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


_crypt32 = getattr(getattr(ctypes, "windll", None), "crypt32", None)
_kernel32 = getattr(getattr(ctypes, "windll", None), "kernel32", None)
if _crypt32 is not None:
    _crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB), ctypes.c_wchar_p, ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(_DATA_BLOB),
    ]
    _crypt32.CryptProtectData.restype = ctypes.c_bool
    _crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB), ctypes.POINTER(ctypes.c_wchar_p), ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(_DATA_BLOB),
    ]
    _crypt32.CryptUnprotectData.restype = ctypes.c_bool
if _kernel32 is not None:
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p


# 注意：不使用 optional entropy。实测在熵 blob + 互斥锁同时存在时，杀软 ML 启发式
# （Defender 报 Wacapew.C!ml）会把整个 exe 误判删除；去掉熵后稳定存活。
# 威胁边界 = DPAPI-CurrentUser 账户隔离（业界标准用法），README 已说明。
def _dpapi_protect(data):
    if _crypt32 is None:
        raise OSError("DPAPI unavailable")
    b_in = _DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    b_out = _DATA_BLOB()
    ok = _crypt32.CryptProtectData(ctypes.byref(b_in), "deskpet", None, None, None, 0, ctypes.byref(b_out))
    if not ok:
        raise OSError("CryptProtectData failed")
    try:
        return ctypes.string_at(b_out.pbData, b_out.cbData)
    finally:
        _kernel32.LocalFree(b_out.pbData)


def _dpapi_unprotect(data):
    if _crypt32 is None:
        raise OSError("DPAPI unavailable")
    b_in = _DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    b_out = _DATA_BLOB()
    ok = _crypt32.CryptUnprotectData(ctypes.byref(b_in), None, None, None, None, 0, ctypes.byref(b_out))
    if not ok:
        raise OSError("CryptUnprotectData failed")
    try:
        return ctypes.string_at(b_out.pbData, b_out.cbData)
    finally:
        _kernel32.LocalFree(b_out.pbData)


def encrypt_secret(text):
    if not text:
        return ""
    return "dpapi:" + base64.b64encode(_dpapi_protect(text.encode("utf-8"))).decode("ascii")


def decrypt_secret(stored):
    if not stored:
        return ""
    if stored.startswith("dpapi:"):
        try:
            return _dpapi_unprotect(base64.b64decode(stored[6:])).decode("utf-8")
        except Exception as e:
            # v2.6.0（D7-B ①）：此前这里静默返回 ""——DPAPI 解密失败与"从没设过 Key"在界面上
            # **长得一模一样**（设置页的 Key 框变空），用户只会以为自己没存过（换机器/换用户
            # /凭据被清都会走到这里）。补一条限流日志：失败原因留在 error.log；
            # 返回值口径逐位不变（""＝按未设置处理），调用方与既有断言都不受影响。
            pet_log.log_throttled("config.decrypt_secret",
                                  "API Key 解密失败（按未设置处理）：%r" % (e,))
            return ""
    return stored  # 兼容旧版明文（仅读取，不再写入）


def _to_bool(v, default=False):
    """配置值 → bool。v is None（手改 config.json 写成 null）时用 default。

    v2.4（兼容审查 L7）：此前 None 落到 bool(None)=False——把**默认开**的开关静默关掉：
    "ai_rag_enabled": null 之后用户数据摘要不再注入，"ai_tools_enabled"/"ai_tools_confirm"
    同款（关掉工具调用/写入确认），界面上看不出任何变化，只有把 config.json 翻出来才知道。
    always_on_top/sound/ceilingBounce 也是"默认 True"的键，同一口径一起修。
    """
    if v is None:
        return bool(default)
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


# ---------------- v2.10.0（C-13）：两个无障碍开关的**三态词表**（单一来源） ----------------
# 合法值只有这三个：auto（跟随系统）/ on（总是开）/ off（总是关）。
# ⚠ **不许在别处再造一套字符串**（"true"/"1"/"always"/"system"…）：那会让手写的配置值
# 从"生效"静默变成"跟随系统"（语义窄化）。
# 消费点：pet_menu 的三态菜单（勾选态 + 写回）、桌宠._set_reduce_motion / _set_high_contrast
# （落盘与立即生效）、pet_motion.reduce_motion_enabled / high_contrast_enabled（换算生效值）。
MOTION_MODES = ("auto", "on", "off")
MOTION_MODE_KEYS = ("reduce_motion", "high_contrast")


def normalize_motion_mode(value):
    """三态开关的配置值 → auto/on/off 之一；其余（null / 坏值 / 空串）一律回 auto。

    回 auto 而不是 off：这不是"默认开"，是**不擅自替用户做无障碍决定**——与
    pet_motion.reduce_motion_enabled 的"读得到系统设置就跟随、读不到保持动效开启"同口径。
    """
    v = str(value if value is not None else "auto").strip().lower()
    return v if v in MOTION_MODES else "auto"


def is_auto_motion_mode(value):
    """配置值是否＝三态里的 auto（跟随系统）。

    给"跟随系统"这种**第三条菜单项**的勾选态用；调用方不许自己比字符串——
    词表的单一来源在本模块（pet_menu 的三态菜单与桌宠的托盘菜单共用它）。
    """
    return normalize_motion_mode(value) == "auto"


# ---------------- P1-3：配置归一化（load_config 用，就地修正） ----------------
def normalize_cfg(cfg, defaults, persona_ids):
    """P1-3 配置归一化：就地修正坏值 / 美化合法值，返回 cfg。

    defaults=调用方 DEFAULT_CONFIG、persona_ids=人设预设 id 集合（人设预设定义在
    load_config 之后，运行时注入才可用）。
    """
    try:
        # v2.3.1（P3-3）：float("nan") 不抛异常，min/max 也拦不住 NaN——
        # NaN 会一路传到 setFixedSize(nan, nan)。非有限值一律回退默认倍率。
        _sc = float(cfg.get("scale", 1.0))
        cfg["scale"] = max(0.2, min(4.0, _sc)) if math.isfinite(_sc) else 1.0
    except (TypeError, ValueError):
        cfg["scale"] = 1.0
    # v2.4（L7）：每个键都把"默认值"一起传进 _to_bool——config.json 里的 null 必须走默认值，
    # 不能静默变 False（"默认开"的四个键尤其致命）。第二个参数与 .get 的默认值必须一致。
    cfg["always_on_top"] = _to_bool(cfg.get("always_on_top", True), True)
    cfg["ai_enabled"] = _to_bool(cfg.get("ai_enabled", False), False)
    cfg["follow_mouse"] = _to_bool(cfg.get("follow_mouse", False), False)
    cfg["wander"] = _to_bool(cfg.get("wander", False), False)
    cfg["city"] = str(cfg.get("city", "北京") or "北京")
    cfg["sound"] = _to_bool(cfg.get("sound", True), True)
    cfg["ai_rag_enabled"] = _to_bool(cfg.get("ai_rag_enabled", True), True)  # v2.3.0（1.3）：用户数据摘要注入开关
    # v2.3.0（1.2 Function Calling）：工具调用总开关 + 写入确认开关。
    # 坏值一律按 bool 兜底——tests/test_config_robustness.py 对 DEFAULT_CONFIG 逐键灌坏值，
    # 归一化后类型必须仍然是 bool。
    cfg["ai_tools_enabled"] = _to_bool(cfg.get("ai_tools_enabled", True), True)
    cfg["ai_tools_confirm"] = _to_bool(cfg.get("ai_tools_confirm", True), True)
    cfg["badge"] = _to_bool(cfg.get("badge", False), False)
    # ---- v2.11.0 第 11 轮（旧第 8 轮那批）：四个新键的归一化 ----
    # 三个开关走 _to_bool（手改 config.json 塞 "true"/1/null/[] 都不许把功能静默带偏）；
    # time_mood_sent 是"当天已发过哪些"的映射，坏值一律回空表（宁可多发一次问候，也不许
    # 因为一条坏记录让用户永远收不到）。**归一化后类型必须仍然是 bool / dict** ——
    # tests/test_config_robustness.py 会逐个键塞毒值来钉这一条。
    for _k, _d in (("fullscreen_hide", True), ("notify", True), ("time_mood", False)):
        cfg[_k] = _to_bool(cfg.get(_k, _d), _d)
    _sent = cfg.get("time_mood_sent", {})
    cfg["time_mood_sent"] = dict(_sent) if isinstance(_sent, dict) else {}
    # ---- v1.3 新增配置归一化 ----
    cfg["role"] = str(cfg.get("role", "") or "")
    cfg["scale_compensated_role"] = str(cfg.get("scale_compensated_role", "") or "")
    # v2.2.5：三个键**各自独立** try——此前共用一个 except，任一键坏值会把另外两个用户
    # 有效设置一起重置（与下方 role_frame_max 的独立 try 口径也不一致）。
    for _k, _lo, _hi, _d in (("chat_memory_rounds", 0, 10, 3),
                             ("ai_max_tokens", 16, 512, 60),
                             ("ai_reply_len", 4, 50, 25)):
        try:
            cfg[_k] = max(_lo, min(_hi, int(cfg.get(_k, _d) or _d)))
        except (TypeError, ValueError):
            cfg[_k] = _d
    cfg["ai_base_url"] = str(cfg.get("ai_base_url", "") or "").strip().rstrip("/")
    cfg["ai_model"] = str(cfg.get("ai_model", pet_chat.DEFAULT_MODEL) or pet_chat.DEFAULT_MODEL).strip()
    cfg["ai_system_prompt"] = str(cfg.get("ai_system_prompt", "") or "")
    cfg["ai_persona"] = str(cfg.get("ai_persona", "default") or "default")
    if cfg["ai_persona"] not in persona_ids and cfg["ai_persona"] != "custom":
        cfg["ai_persona"] = "default"  # 未知预设 id：回退内置人设
    cfg["click_through"] = _to_bool(cfg.get("click_through", False), False)
    try:
        cfg["role_frame_max"] = max(2, min(60, int(cfg.get("role_frame_max", 24) or 24)))
    except (TypeError, ValueError):
        cfg["role_frame_max"] = 24
    # P1-手感：物理参数归一化（默认值单一来源 pet_physics.DEFAULT_PHYSICS；
    # 负数/非数字回退默认并记日志、上界按设置对话框同口径钳制，不崩）
    _phys = cfg.get("physics")
    if not isinstance(_phys, dict):
        _phys = {}
    _pd = normalize_physics(_phys)
    if _pd.get("_fixed"):
        pet_log.log_error("load_config: 物理参数非法已回退默认: %s" % ",".join(_pd["_fixed"]))
        _pd.pop("_fixed")
    cfg["physics"] = _pd
    # v2.0：语音配置归一化（默认关闭；tts_mode 白名单）
    cfg["voice"] = pet_voice.normalize_voice(cfg.get("voice"))
    # v2.0.2/v2.1：行为与待机配置归一化（默认值/钳制单一来源 pet_behaviors）
    _bcfg = pet_behaviors.DEFAULT_BEHAVIOR_CFG
    # 迁移来源：旧键 idle_behavior（单条）+ idle_behavior_seconds（秒数）
    cfg["idle_behavior"] = str(cfg.get("idle_behavior", "") or "").strip()
    # v2.1：待机系统（两触发 + 多动作 + idle_form）——normalize_idle_cfg 会把上面两个旧键
    # 迁进 idle_actions / idle_trigger_delay；反向同步旧秒数键，保证旧版读取路径兼容。
    # （旧的 5~60 钳制块已删除：它在下面立刻被覆盖，是死路径，容易误导读者。）
    _icfg = pet_behaviors.normalize_idle_cfg(cfg)
    cfg["idle_trigger_delay"] = _icfg["idle_trigger_delay"]
    cfg["idle_delay_after_full"] = _icfg["idle_delay_after_full"]
    cfg["idle_form"] = _icfg["idle_form"]
    cfg["idle_actions"] = _icfg["idle_actions"]
    cfg["idle_play_mode"] = _icfg["idle_play_mode"]
    cfg["idle_resume_on_interrupt"] = _icfg["idle_resume_on_interrupt"]
    cfg["idle_behavior_seconds"] = _icfg["idle_trigger_delay"]
    # M3 修复：旧键已迁移进 idle_actions，置空以防"移除待机动作"被旧键复活
    cfg["idle_behavior"] = ""
    try:
        cfg["transform_seconds"] = max(
            pet_behaviors.TRANSFORM_SECS_MIN,
            min(pet_behaviors.TRANSFORM_SECS_MAX,
                int(cfg.get("transform_seconds",
                            _bcfg["transform_seconds"]) or _bcfg["transform_seconds"])))
    except (TypeError, ValueError):
        cfg["transform_seconds"] = _bcfg["transform_seconds"]
    cfg["sound_group"] = "custom" if cfg.get("sound_group") == "custom" else "default"
    # v2.11.0 第 9 轮收尾 / v2.10.0（C-13）收口：无障碍两键（reduce_motion / high_contrast）
    # 是**三态枚举**，词表与归一都走本模块顶部的 MOTION_MODES / normalize_motion_mode
    # ——菜单的「跟随系统」与桌宠的落地点从同一处取词，别处不许再抄第二套字符串。
    # 为什么必须在这里归一化：DEFAULT_CONFIG 里它们是 str，而 tests/test_config_robustness.py
    # 对每个键灌坏值后要求"归一化后类型必须仍然可用"——此前这两键漏在归一化之外，
    # 手改 config.json 塞 null/[]/123 会一路带进 桌宠._reduce_motion()（枚举比较恒假）。
    for _k in MOTION_MODE_KEYS:
        cfg[_k] = normalize_motion_mode(cfg.get(_k, "auto"))
    try:
        bs = cfg.get("bubble_style")
        if not isinstance(bs, dict):
            bs = {}
        bs = {
            "bg": str(bs.get("bg", "") or "#ffffff"),
            "fg": str(bs.get("fg", "") or "#203170"),
            "border": str(bs.get("border", "") or "#203170"),
            "font_size": int(bs.get("font_size", 10) or 10),
            "radius": int(bs.get("radius", 16) or 16),
        }
        for k in ("bg", "fg", "border"):
            if not QColor(bs[k]).isValid():
                bs[k] = defaults["bubble_style"][k]
        bs["font_size"] = max(8, min(18, bs["font_size"]))
        bs["radius"] = max(0, min(30, bs["radius"]))
        cfg["bubble_style"] = bs
    except Exception:
        cfg["bubble_style"] = dict(defaults["bubble_style"])
    for k in ("budget", "balance_alert"):
        try:
            cfg[k] = round(max(0.0, float(cfg.get(k, 0.0) or 0.0)), 2)
        except (TypeError, ValueError):
            cfg[k] = 0.0
    # v2.1：lines_extra 已是**死键**（台词库 lines.json 是唯一来源），只作一次性迁移源。
    # S3 修复：这里**不再做 20 条/60 字截断**——旧限制会在迁移时把用户数据吃掉，
    # 与 v2.0.6「解除数量与长度限制」的承诺冲突。原样保留，交给迁移逻辑处理。
    le = cfg.get("lines_extra")
    if not isinstance(le, dict):
        le = {}
    cfg["lines_extra"] = {k: [str(x).strip() for x in (v or []) if str(x).strip()]
                          for k, v in le.items() if isinstance(v, list)}
    # v2.8.0 · Phase 3：远端插件索引地址（默认空 = 随包索引）。**只在键已存在时**归一：
    # 这个键由 桌宠.DEFAULT_CONFIG 声明（本模块不往 cfg 里增添量未知键——write_config 的
    # diff 存储本来就只认 defaults 里的键，凭空加进去只会让人以为它存得住）。
    if PLUGIN_INDEX_URL_KEY in cfg:
        cfg[PLUGIN_INDEX_URL_KEY] = normalize_plugin_index_url(cfg[PLUGIN_INDEX_URL_KEY])
    return cfg


def write_config(path, cfg, defaults, schema_version, log, encrypt_fn):
    """save_config 核心：diff 存储（api_key 特殊处理）+ 原子替换。

    **返回值契约（v2.7.0 第 5 轮 · 代理 B）**：成功返回 None；失败返回**错误串**
    （pet_io 的错误原文，或本函数自身异常的描述）——调用方据此给用户提示。
    在此之前恒返回 None，写失败只写日志，调用方无从判断（见函数末尾注释）。
    

    diff 存储 = 只落盘**与 defaults 不同**的键（外加 schema_version 与 api_key 密文）。
    于是**不在 defaults 里的顶层未知键会被丢弃——这是有意为之，不是缺陷**
    （v2.5.0 · D7-A 把口径写清楚，免得每轮审查重提一遍）：

      ① config.json 是**程序按 schema 自有**的配置文件，不是用户数据文件。合法键由
         DEFAULT_CONFIG 定义，未知键没有任何代码路径会读它；带回去只会让已废弃的键
         （例如 v2.0 的 lines_extra——现在只作迁移源）永久复活。
      ② diff 存储的基准是"代码里的默认值"：写回 = 默认值 × 用户改动。若把未知键一起
         带回去，就变成"旧文件 × 新代码"，两版之间字段的废弃/改名永远清不掉。
      ③ 未来版本的键**不靠保留来保护，靠不写回**：桌宠.save_config 读到更高的
         schema_version 时进兼容模式（只读运行，任何保存都不落盘）——不会出现
         "新版本配置被本版本降级覆盖"。

    对照：alarms.json / behaviors.json / lines.json 这些**用户数据**文件的顶层未知键
    必须原样保留（v2.4.2 起）——它们的合法内容由用户写，不由代码 schema 定义。
    要新增配置项：先把键加进 桌宠.DEFAULT_CONFIG（或另开一个自己的数据文件）。
    """
    try:
        # P1-3：diff 存储——只落盘与默认值不同的键（api_key 特殊处理），schema 版本随写
        # v2.5.0（D7-A）：k not in defaults 的未知键**有意丢弃**——理由见本函数 docstring。
        out = {"schema_version": schema_version}
        for k, v in cfg.items():
            if k in defaults and v != defaults[k]:
                out[k] = v
        try:
            out["api_key"] = encrypt_fn(str(cfg.get("api_key", "") or ""))
        except Exception:
            # 加密失败：绝不落盘明文。磁盘旧值仅当是 dpapi: 密文时才回写；
            # 旧值是 legacy 明文/缺失则写空串（防把明文重落盘）。
            # 已知边界：此时内存中的新 key 与磁盘旧值可能不一致，重启后以磁盘为准。
            log("encrypt_secret failed, keeping stored ciphertext only")
            try:
                with open(path, "r", encoding="utf-8") as f:
                    old = json.load(f)
                old_key = str(old.get("api_key", "") or "")
                out["api_key"] = old_key if old_key.startswith("dpapi:") else ""
            except Exception as e:
                # v2.4.1（B1 静默 except 审计 A 档）：这里读不到旧配置 → 写盘时 api_key 会
                # 变成空串（内存里的新 key 与磁盘旧值不一致，重启后以磁盘为准）。不记一行
                # 的话，用户只会看到"Key 自己没了"，连排查线索都没有。
                log("read old config for api_key failed, api_key cleared: %r" % (e,))
                out["api_key"] = ""
        # v2.2.5：整段写盘加锁 + 临时文件带线程标识，避免两个线程抢同一个 tmp。
        # v2.3.1：实现挪进 pet_io（多一层按路径分锁 + os.replace 共享冲突短重试），
        # _CFG_WRITE_LOCK 作为调用方锁原样保留——并发语义不变。
        err = pet_io.atomic_write_json(path, out, lock=_CFG_WRITE_LOCK, log=None)
        if err is not None:
            log("save_config failed: %s" % err)
        return err      # v2.7.0 第 5 轮（代理 B · 闭环 P1-1）：**把失败交回调用方**
        # 为什么必须回：此前无论成败都返回 None，于是"磁盘满/只读/被占用"这类**真实写失败**
        # 只有 error.log 里一行，调用方（桌宠.save_config → AIService.apply_settings →
        # AI 设置对话框）全链路都判不出来 → 窗口照常关闭 = "保存成功"假象。
    except Exception as e:
        log("save_config failed: %r" % (e,))
        return "配置写盘异常：%r" % (e,)
