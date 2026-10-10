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
import os
import threading

# v2.2.5：配置写盘互斥锁 + 唯一临时名。语音 worker 线程（云端 TTS 首次克隆出 voice_id 时
# 会就地改共享 cfg 并保存）与主线程（约 20 个保存点）此前共用同一个 "config.json.tmp"，
# os.replace 可能因共享冲突抛 PermissionError 被 except 吞掉 → 该次配置写入静默丢失。
_CFG_WRITE_LOCK = threading.Lock()

import pet_log  # P1-手感：物理参数非法时记日志（pet_log 无任何依赖，安全）
import pet_physics  # P1-手感：默认值单一来源（pet_physics 无 Qt 依赖，无环）
import pet_voice  # v2.0：语音配置归一化（pet_voice 无环）
import pet_behaviors  # v2.0.2：行为配置默认值单一来源（pet_behaviors 无环）
import pet_chat  # v2.0.4：AI 默认接口/模型单一来源（pet_chat 无 Qt、无环）

# 上界与设置对话框同口径（pet_dialogs.PhysicsDialog 的 spinbox 范围）
_PHYS_MAX = {"gravity": 10000.0, "restitution": 1.0,
             "groundFriction": 50.0, "throwPower": 10.0}


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
    pd["enabled"] = _to_bool(ph.get("enabled", False))
    pd["ceilingBounce"] = _to_bool(ph.get("ceilingBounce", True))
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
        except Exception:
            return ""
    return stored  # 兼容旧版明文（仅读取，不再写入）


def _to_bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


# ---------------- P1-3：配置归一化（load_config 用，就地修正） ----------------
def normalize_cfg(cfg, defaults, persona_ids):
    """P1-3 配置归一化：就地修正坏值 / 美化合法值，返回 cfg。

    defaults=调用方 DEFAULT_CONFIG、persona_ids=人设预设 id 集合（人设预设定义在
    load_config 之后，运行时注入才可用）。
    """
    try:
        cfg["scale"] = max(0.2, min(4.0, float(cfg.get("scale", 1.0))))
    except (TypeError, ValueError):
        cfg["scale"] = 1.0
    cfg["always_on_top"] = _to_bool(cfg.get("always_on_top", True))
    cfg["ai_enabled"] = _to_bool(cfg.get("ai_enabled", False))
    cfg["follow_mouse"] = _to_bool(cfg.get("follow_mouse", False))
    cfg["wander"] = _to_bool(cfg.get("wander", False))
    cfg["city"] = str(cfg.get("city", "北京") or "北京")
    cfg["sound"] = _to_bool(cfg.get("sound", True))
    cfg["ai_rag_enabled"] = _to_bool(cfg.get("ai_rag_enabled", True))  # v2.3.0（1.3）：用户数据摘要注入开关
    # v2.3.0（1.2 Function Calling）：工具调用总开关 + 写入确认开关。
    # 坏值一律按 bool 兜底——tests/test_config_robustness.py 对 DEFAULT_CONFIG 逐键灌坏值，
    # 归一化后类型必须仍然是 bool。
    cfg["ai_tools_enabled"] = _to_bool(cfg.get("ai_tools_enabled", True))
    cfg["ai_tools_confirm"] = _to_bool(cfg.get("ai_tools_confirm", True))
    cfg["badge"] = _to_bool(cfg.get("badge", False))
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
    cfg["click_through"] = _to_bool(cfg.get("click_through", False))
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
    return cfg


def write_config(path, cfg, defaults, schema_version, log, encrypt_fn):
    """save_config 核心：diff 存储（api_key 特殊处理）+ 原子替换。"""
    try:
        # P1-3：diff 存储——只落盘与默认值不同的键（api_key 特殊处理），schema 版本随写
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
            except Exception:
                out["api_key"] = ""
        # v2.2.5：整段写盘加锁 + 临时文件带线程标识，避免两个线程抢同一个 tmp
        with _CFG_WRITE_LOCK:
            tmp = "%s.%d.tmp" % (path, threading.get_ident())
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(out, f, ensure_ascii=False, indent=2)
                os.replace(tmp, path)
            except Exception:
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)  # 失败清理自己的 tmp（与 pet_book._write_json 同口径）
                except Exception:
                    pass  # 有意忽略：清理失败不影响主流程
                raise
    except Exception as e:
        log("save_config failed: %r" % (e,))
