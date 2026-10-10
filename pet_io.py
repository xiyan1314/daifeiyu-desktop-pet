# -*- coding: utf-8 -*-
"""
大肥鱼桌宠 · 全仓共用的原子 IO 助手（v2.3.1，落地评审 P0-1 / P0-2 / P1-3 / P2-2）。

为什么要有这个模块
------------------
v2.3.0 只给 pet_book/pet_config 修了"固定 .tmp + 无锁"这一处同款 bug，其余 6 个
模块（pet_chat/pet_resources/pet_alarm/pet_behaviors/pet_voice/pet_lines）仍是旧口径：

- 固定临时名 "<file>.tmp" + 无锁：两个线程同时写同一文件会互相截断，json.dump 的
  多次 write 在字节级交错 → os.replace 把半截 JSON 提交上盘。
  （error.log 实测：load_chat_memory 读取失败 ×140、pet_book._read_json ×170）
- os.replace 在 Windows 上会因杀软/索引器/残留句柄抛 PermissionError（共享冲突），
  旧代码一律 except 吞掉 → 这次写入静默丢失、坏文件原样留在磁盘上。
- 读到坏文件只返回默认值、不回写 → 坏 JSON 每次启动重报（根因 B）。

本模块把这三件事一次做对。全部纯 stdlib、**Qt-free**（不 import pet_log / PySide6），
可脱离 GUI 单测：

- path_lock(path)          按路径分锁：同一文件的所有写者共用同一把可重入锁
- atomic_write_json(...)   原子写 JSON：线程唯一临时名 + os.replace 冲突短重试
- atomic_write_bytes(...)  原子写二进制（语音缓存等同款需求）
- read_json_or(...)        读 JSON 并**如实告知是否损坏**（文件缺失 ≠ 损坏）
- heal_json(...)           只在"文件仍然是坏的"时回写合法结构（愈合，不覆盖新数据）

并发语义（重要）
----------------
1. 锁的粒度是**绝对路径**：缓存 dict 由一把全局锁保护（不是每个调用点各拿一把
   自己的锁——那等于没锁），同一路径的所有写者因此真正串行。
2. 锁可重入（RLock）：读-改-写（pet_chat 的 memory.json 合并）能在**同一把锁**内
   完成读与写——既不会自己死锁，也不会被别的线程插进来用旧快照覆盖。
3. atomic_write_* 总是拿"路径锁"；调用方另有自己的锁时（pet_book/pet_config 保留
   历史锁语义），按固定顺序"调用方锁 → 路径锁"获取，不存在反向路径，故无死锁。
4. heal_json 在同一把路径锁内**重新读一次**：从"发现损坏"到"准备回写"之间若已有
   写者把文件修好了，这里读到的就是新数据 → 不写。这就是"愈合不覆盖更新的数据"。
5. 锁只覆盖本进程；跨进程并发不在本模块范围内（桌宠用命名互斥体保证单实例）。

日志口径：异常一律在 except 里交给调用方注入的 log 回调（默认 None=不记），
本模块**绝不向上抛异常**——持久化失败降级成返回值/日志，绝不把调用方拖崩。
"""
import json
import os
import shutil
import threading
import time

# 全局锁 → 保护 _LOCKS 这张表本身；_LOCKS[绝对路径] → 该路径的专用可重入锁
_LOCKS_GUARD = threading.Lock()
_LOCKS = {}

# os.replace 共享冲突（Windows 杀软/索引器/残留句柄）重试间隔：实测 50ms 足够让
# 瞬时句柄释放，最多重试 retries 次（默认 3 → 最坏多等 150ms，只发生在故障路径上）
_RETRY_SLEEP = 0.05


def path_lock(path):
    """取某路径的专用锁（可重入）。同一路径的所有写者拿到的必须是同一把锁。"""
    key = os.path.abspath(str(path))
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()   # 可重入：读-改-写要在同一把锁里读+写
            _LOCKS[key] = lock
        return lock


def _log(log, msg):
    """日志回调（注入式）：日志通道自身出错不影响持久化主流程。"""
    if log is None:
        return
    try:
        log(msg)
    except Exception:
        pass  # 有意忽略：日志失败绝不影响写盘


def _cleanup_tmp(tmp, log):
    """删除本次写入自己的临时文件（线程唯一名，别的线程不会用这个路径）。"""
    try:
        if os.path.exists(tmp):
            os.remove(tmp)
    except Exception as e:
        _log(log, "pet_io 临时文件清理失败 %s: %r" % (tmp, e))


def _guard(path, lock):
    """按固定顺序取锁：调用方锁（可选）→ 路径锁。返回 contextmanager。"""
    path_lk = path_lock(path)
    if lock is None or lock is path_lk:
        return path_lk
    return _MergeGuard(lock, path_lk)


class _MergeGuard(object):
    """同时持有"调用方锁 + 路径锁"的极简上下文（顺序固定 → 不会死锁）。"""

    __slots__ = ("_locks",)

    def __init__(self, *locks):
        self._locks = locks

    def __enter__(self):
        self._locks[0].acquire()
        try:
            self._locks[1].acquire()
        except Exception:
            self._locks[0].release()
            raise
        return self

    def __exit__(self, *exc):
        self._locks[1].release()
        self._locks[0].release()
        return False


def atomic_write_bytes(path, data, *, lock=None, retries=3, log=None):
    """原子写二进制：临时文件 + os.replace；成功返回 None，失败返回错误字符串（绝不抛）。

    临时名带线程号（"%s.%d.tmp" % (path, threading.get_ident())）——两个线程同时写
    同一文件也不会抢同一个 tmp 互相截断；os.replace 因共享冲突失败时 sleep 后重试
    （最多 retries 次），最终失败则清理自己的 tmp 并记日志。
    """
    path = str(path)
    tmp = "%s.%d.tmp" % (path, threading.get_ident())
    attempts = max(1, int(retries) + 1)   # 首写 1 次 + 重试 retries 次
    try:
        with _guard(path, lock):
            d = os.path.dirname(path)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(tmp, "wb") as f:
                f.write(data)
            last = None
            for i in range(attempts):
                try:
                    os.replace(tmp, path)
                    return None
                except PermissionError as e:
                    # Windows 共享冲突：杀软/索引器/残留句柄瞬时锁住目标文件
                    last = e
                    if i < attempts - 1:
                        time.sleep(_RETRY_SLEEP)
            raise last
    except Exception as e:
        _cleanup_tmp(tmp, log)   # 失败清理自己的 tmp（退出时的 *.tmp 清扫只认固定名）
        _log(log, "pet_io 写盘失败 %s: %r" % (path, e))
        return str(e)


def atomic_write_json(path, data, *, lock=None, retries=3, log=None, indent=2):
    """原子写 JSON（UTF-8 / ensure_ascii=False）；成功 None，失败错误字符串。

    indent 默认 2（与 pet_book/pet_resources/… 原口径一致）；记忆文件传 indent=None
    保持原来的紧凑单行格式（不改用户的既有文件观感）。
    """
    try:
        text = json.dumps(data, ensure_ascii=False, indent=indent)
    except Exception as e:
        _log(log, "pet_io JSON 序列化失败 %s: %r" % (path, e))
        return str(e)   # 序列化失败时还没有 tmp 落盘，无需清理
    return atomic_write_bytes(path, text.encode("utf-8"),
                              lock=lock, retries=retries, log=log)


def read_json_or(path, factory=dict, *, expect=dict, log=None):
    """读 JSON；返回 (data, corrupted: bool)。

    - 文件不存在 → (factory(), False)：首次运行不是错误，也**不需要愈合**
    - 解析失败 / 顶层类型不是 expect → (factory(), True)：真损坏，调用方可据此愈合
    - 读取本身失败但文件在（权限/共享占用等）→ (factory(), False)：**不能证明损坏**，
      绝不据此回写（否则可能用空结构覆盖掉别人的好文件）
    """
    try:
        # v2.3.1（兼容审查 S1）：用 utf-8-sig——用户用记事本另存为「UTF-8 with BOM」时
        # 内容其实完好，用 utf-8 读会抛 JSONDecodeError 被判"损坏"→ 被空结构覆盖清空。
        with open(str(path), "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except FileNotFoundError:
        return factory(), False
    except OSError as e:
        _log(log, "pet_io 读取失败（按默认值继续）%s: %r" % (path, e))
        return factory(), False
    except UnicodeDecodeError as e:
        # v2.3.1（兼容审查 S1）：解码失败 ≠ 内容损坏。GBK/ANSI 另存的文件内容完全可读，
        # 旧版对它一个字节都不动；把它判成"坏"再回写 = 原地销毁用户数据。
        # 与 OSError 同口径：不能证明损坏 → 不回写，只记一行日志。
        _log(log, "pet_io 编码不是 UTF-8（按默认值继续，不覆盖原文件）%s: %r" % (path, e))
        return factory(), False
    except Exception as e:
        # 其余（JSONDecodeError / RecursionError…）= 文件内容确实坏了
        _log(log, "pet_io 解析失败（按默认值重建）%s: %r" % (path, e))
        return factory(), True
    if expect is not None and not isinstance(data, expect):
        _log(log, "pet_io 顶层结构非法（按默认值重建）%s: %s"
             % (path, type(data).__name__))
        return factory(), True
    return data, False


def load_json(path, factory=dict, *, expect=dict, log=None):
    """read_json_or 的 ok 口径快捷版：返回 (data, ok)（ok=False=文件损坏）。"""
    data, corrupted = read_json_or(path, factory, expect=expect, log=log)
    return data, not corrupted


def heal_json(path, factory=dict, *, expect=dict, log=None, retries=3):
    """读 JSON；**只在文件仍然是坏的**时才回写 factory() 结构（一次性愈合）。

    返回 (data, corrupted)。"仍然是坏的"= 在同一把路径锁内重新读一次的结果；
    若期间已有写者修好了文件，读到的是新数据 → 不再回写，因此**绝不覆盖更新数据**。
    """
    lock = path_lock(path)
    with lock:
        data, corrupted = read_json_or(path, factory, expect=expect, log=log)
        if corrupted:
            # v2.3.1（兼容审查 S1）：愈合前先把原文件另存 .bak——万一判错了（未来又出现
            # 某种"内容可读但被判坏"的假阳性），用户的数据还在，可手工恢复。
            try:
                if os.path.exists(str(path)):
                    shutil.copyfile(str(path), str(path) + ".bak")
            except Exception as e:
                _log(log, "pet_io 愈合备份失败（继续愈合）%s: %r" % (path, e))
            # 锁还在手上：此刻没有本进程写者能在"读到坏"与"回写"之间插入新数据
            atomic_write_json(path, factory(), lock=lock, retries=retries, log=log)
    return data, corrupted
