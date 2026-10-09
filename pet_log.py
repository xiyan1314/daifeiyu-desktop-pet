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

# ---------------- 模块级状态 ----------------
_data_dir = None      # 日志目录（桌宠.set_data_dir 同步；未同步时按 _default_dir 规则取）
_redact_key = None    # 脱敏 key 缓存（未同步 = None；桌宠.set_redact_key 同步）
_logging = False      # log_error 重入标志（防日志路径内部异常再打日志的套环）

# P0-2：DEBUG 开关——DFY_DEBUG=1 时 log_error 内部异常直抛，便于排障
DEBUG = os.environ.get("DFY_DEBUG") == "1"


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
    """写一条错误/信息日志：脱敏 → error.log 追加（512KB 轮转）。

    data_dir：桌宠._log_error 委托时传入其当前 DATA_DIR（保持 tests/verify
    对 main.DATA_DIR 的 monkeypatch 隔离仍然生效）；其余模块不传，按
    set_data_dir 同步值或 _default_dir() 规则取目录。
    """
    global _logging
    if _logging:
        # 重入：直写 stderr 立即返回，阻断套环；外层调用会正常走完整脱敏+落盘
        try:
            sys.stderr.write("[DFY] %s\n" % msg)
        except Exception:
            pass  # 有意忽略：stderr 不可写时无从记录
        return
    _logging = True
    try:
        msg = redact(msg)
        path = os.path.join(data_dir or _data_dir or _default_dir(), "error.log")
        try:
            if os.path.getsize(path) > 512 * 1024:  # 512KB 轮转，防无限累积
                os.replace(path, path + ".old")
        except Exception:
            pass  # 有意忽略：体积检查失败直接追加
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception:
            # 写盘失败（只读目录等）：回退 stderr，日志坏了也不能静默（P0-2）
            try:
                sys.stderr.write("[DFY] %s\n" % msg)
                sys.stderr.flush()
            except Exception:
                pass  # 有意忽略：stderr 不可写时无从记录
    except Exception:
        if DEBUG:
            raise  # 调试模式：异常直抛，方便定位
        try:
            sys.stderr.write("[DFY] log error: %s\n" % msg)
        except Exception:
            pass  # 有意忽略：stderr 不可写时无从记录
    finally:
        _logging = False
