# -*- coding: utf-8 -*-
"""
大肥鱼桌宠 —— 统一日志模块（P0-2 全量清扫新建）。

用途：全仓共用的日志出口。pet_* 模块不能 import 桌宠（会循环依赖），
因此把日志脱敏（redact）与错误落盘（log_error）统一收进本模块；
桌宠.py 启动时调用 set_data_dir() / set_redact_key() 同步数据目录与
脱敏 key，其 _log_error / _redact 只做一行委托（保留函数名供全仓与
tests 调用）。pet_dialogs / pet_resources / pet_book / pet_fx 等模块
直接 import pet_log 调用，不再各自实现日志。

日志文件：<数据目录>/error.log，512KB 轮转（旧文件改名 error.log.old）；
写盘失败回退 stderr；DFY_DEBUG=1 时内部异常直抛，便于排障。
"""

import os
import re
import sys
import threading

# ---------------- 模块级状态 ----------------
_data_dir = None      # 日志目录（桌宠.set_data_dir 同步；未同步时按 _default_dir 规则取）
_redact_key = None    # 脱敏 key 缓存（未同步 = None；桌宠.set_redact_key 同步）
_tls = threading.local()  # v2.2.5：重入标志改为**线程局部**——原为进程级 bool，
# 多个后台线程（chat/voice/balance/weather）同时报错时后到的线程会被误判"重入"而只写
# stderr；pythonw.exe 下 stderr 不可见 → 这些错误彻底消失。

# P0-2：DEBUG 开关——DFY_DEBUG=1 时 log_error 内部异常直抛，便于排障
DEBUG = os.environ.get("DFY_DEBUG") == "1"

# v2.4（技术债收口 C）：单文件体积上限（超过即轮转）与坏文件隔离后缀
MAX_BYTES = 512 * 1024
BAD_SUFFIX = ".bad"


def _to_stderr(text):
    """把一行文本写 stderr（日志自身出故障时的唯一出口）。"""
    try:
        sys.stderr.write(text if text.endswith("\n") else text + "\n")
        sys.stderr.flush()
    except Exception:
        pass  # 有意忽略：stderr 不可写时无从记录


def _quarantine(path):
    """把坏/满/写不进去的日志文件改名成 error.log.bad（保留现场，不静默丢弃）。

    返回隔离后的路径；改名失败（被独占锁等）返回空串。已有 .bad 会被覆盖——
    同一次故障反复触发不堆文件；要看更早的历史还有 error.log.old。
    """
    bad = path + BAD_SUFFIX
    try:
        os.replace(path, bad)
        return bad
    except Exception:
        return ""


def _rotate_if_needed(path):
    """512KB 轮转；轮转失败（被占用/无权限）退一步隔离成 .bad。

    返回要报给维护者的说明（空串 = 正常）。日志自身的故障只能写 stderr，
    这里只返回文案、不自己写，保持"出口唯一"。
    """
    try:
        if os.path.getsize(path) <= MAX_BYTES:
            return ""
    except Exception:
        return ""  # 文件不存在（首次写）或读不到体积：交给追加失败分支去报
    try:
        os.replace(path, path + ".old")
        return ""
    except Exception as e:
        if _quarantine(path):
            return "error.log 轮转失败（%r），已改名 error.log%s 重新开始" % (e, BAD_SUFFIX)
        return "error.log 轮转失败且无法改名（%r）" % (e,)


def set_data_dir(path):
    """设置日志目录（桌宠.py 在 DATA_DIR 计算后调用）。"""
    global _data_dir
    _data_dir = path


def set_redact_key(key):
    """同步脱敏 key 缓存（桌宠.set_redact_key 内部调用）。"""
    global _redact_key
    _redact_key = key


def guard_slot(name, fn):
    """定时器槽守卫（共享实现）：槽内异常只记日志（含 traceback）并继续跑。

    为什么需要：QTimer 槽里未捕获的异常会走 sys.excepthook → 弹模态错误框，
    高频 tick 会反复弹，表现为桌宠"卡住不动"。定时器槽是后台心跳，出错应该记日志、
    下一拍继续。（v2.1.4：主窗口 _gslot 与各服务模块的槽统一走这里。）
    """
    import functools

    @functools.wraps(fn)
    def _run(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            try:
                import time as _t
                import traceback
                _seen = globals().setdefault("_SLOT_SEEN", {})
                _now = _t.monotonic()
                if _now - float(_seen.get(name, 0.0)) >= 60:  # 限流：同一槽 60s 一条
                    _seen[name] = _now
                    log_error("timer slot %s failed: %r\n%s" % (name, e, traceback.format_exc()))
            except Exception:
                pass  # 有意忽略：日志自身失败无处可记
            return None

    return _run


def _default_dir():
    """默认日志目录：与 桌宠.py 的 _data_dir() 同规则（可写探测 → APPDATA 回退）。

    注：本函数以 pet_log.__file__ 所在目录为基准（非 frozen 下与 app_dir() 等价；
    frozen 单文件解包目录差异无实际影响——主流程 import 即 set_data_dir 覆盖）。"""
    d = os.path.dirname(os.path.abspath(__file__))
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


def redact(msg):
    """日志脱敏：API Key（缓存命中才替换）+ sk- / Bearer / api_key 字段 / 裸 ?key= 查询参数形态。

    各条正则与 桌宠.py 原 _redact 完全一致（阈值 6 位，后两条 re.IGNORECASE）；
    _redact_key 由桌宠.set_redact_key 同步，未同步（None）时不重读 config
    直接跳过 key 替换——脱敏缓存与配置读取解耦，避免反向依赖。
    **调用方注意：必须先同步 key（桌宠启动即同步），否则该 key 形态的日志漏脱敏。**
    """
    try:
        if _redact_key:
            msg = msg.replace(_redact_key, "***APIKEY***")
    except Exception:
        pass  # 有意忽略：key 替换失败不影响其余脱敏规则
    msg = re.sub(r"(sk-[A-Za-z0-9_-]{6,})", "sk-***", msg)
    msg = re.sub(r"(Bearer\s+)[A-Za-z0-9._-]+", r"\1***", msg)
    # P2-1：覆盖 api_key= 字段形态（阈值 6、含 URL 编码字符）与裸 ?key= 查询参数形态
    msg = re.sub(r"(api[_-]?key\s*[=:]\s*[\"']?)[A-Za-z0-9._\-%/+]{6,}", r"\1***", msg, flags=re.IGNORECASE)
    msg = re.sub(r"([?&]key\s*=\s*[\"']?)[^\s&\"']{6,}", r"\1***", msg, flags=re.IGNORECASE)
    return msg


def log_error(msg, data_dir=None):
    """写一条错误/信息日志：脱敏 → error.log 追加（512KB 轮转；坏文件隔离成 .bad）。

    data_dir：桌宠._log_error 委托时传入其当前 DATA_DIR（保持 tests/verify
    对 main.DATA_DIR 的 monkeypatch 隔离仍然生效）；其余模块不传，按
    set_data_dir 同步值或 _default_dir() 规则取目录。

    v2.4（技术债收口 C）：此前"轮转失败"和"追加失败"两个分支都是 pass——坏日志
    文件既没被修好也没被隔离，之后每条日志都往同一个坏文件上撞（pythonw 下 stderr
    不可见 = 全丢）。现在：①轮转失败 → 改名 error.log.bad 重新开始；②追加失败 →
    隔离成 .bad 后**重试一次**（新建干净文件，这条消息不会丢）；③仍然失败才回退
    stderr。轮转/隔离的结果会写一行 stderr——这是日志设施自身唯一可用的出口。
    """
    if getattr(_tls, "logging", False):
        # 重入：直写 stderr 立即返回，阻断套环；外层调用会正常走完整脱敏+落盘
        _to_stderr("[DFY] %s" % msg)
        return
    _tls.logging = True
    try:
        msg = redact(msg)
        path = os.path.join(data_dir or _data_dir or _default_dir(), "error.log")
        note = _rotate_if_needed(path)
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
            if note:
                _to_stderr("[DFY] " + note)
        except Exception as e:
            # 追加失败（只读目录 / 文件被占用 / 坏文件）：先把坏文件隔离掉，
            # 再重试一次——别让一条坏文件把这条日志（以及后面所有日志）吃掉。
            quarantined = _quarantine(path)
            if quarantined:
                try:
                    with open(path, "a", encoding="utf-8") as f:
                        f.write(msg + "\n")
                    _to_stderr("[DFY] error.log 写入失败（%r）→ 已隔离为 %s 并重建"
                               % (e, os.path.basename(quarantined)))
                    return
                except Exception as e2:
                    e = e2
            # 彻底写不进去：回退 stderr，日志坏了也不能静默（P0-2）
            _to_stderr("[DFY] %s" % msg)
    except Exception:
        if DEBUG:
            raise  # 调试模式：异常直抛，方便定位
        _to_stderr("[DFY] log error: %s" % msg)
    finally:
        _tls.logging = False  # 线程局部：只清本线程的重入标志
