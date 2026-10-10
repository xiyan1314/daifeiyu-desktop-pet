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

- path_lock(path)          按路径分锁：同一文件的所有写者共用同一把可重入锁（键已 normcase）
- atomic_write_json(...)   原子写 JSON：进程+线程唯一临时名 + os.replace 冲突短重试
- atomic_write_bytes(...)  原子写二进制（语音缓存等同款需求）
- read_json_or(...)        读 JSON 并**如实告知是否损坏**（文件缺失 ≠ 损坏）
- heal_json(...)           回写合法结构（顶层坏 / 内层类型非法，不覆盖新数据）
- backup_before_heal(...)  愈合/重建前留 "<path>.bak"（自建恢复路径的模块共用）
- clean_tmp_files(...)     清扫 "<p>.tmp" / "<p>.<线程号>.tmp" / "<p>.<进程号>.<线程号>.tmp"

v2.3.1（读侧愈合口径一致性收口，本轮）：
- 临时名加**进程号**（同机多实例/调试时不再撞名），clean_tmp_files 的白名单同步放宽；
- ".bak" 每个目标路径**只保留一份**（反复愈合覆盖旧的那份，覆盖时记一行日志说明）；
- heal_json 增加 normalize 判据：顶层合法但**内层类型非法**（如 {"history": {...}}）
  也能被检出 → 记一行日志 + .bak + 按调用方给的归一化结构重建（重建是否安全由调用方
  判定：返回 reason 为空 = 一个字节都不写，只当没这回事）；
- _MergeGuard 改成**真变参**（此前 __enter__ 只 acquire 前两把锁，第 3 把被静默忽略）。

并发语义（重要）
----------------
1. 锁的粒度是**规范化绝对路径**（normcase(abspath)）：Windows/macOS 文件系统大小写
   不敏感，"x.json" 与 "X.JSON" 是同一个文件，必须映射到同一把锁。缓存 dict 由一把
   全局锁保护（不是每个调用点各拿一把自己的锁——那等于没锁），同一路径的所有写者真正串行。
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
import re
import shutil
import threading
import time

# 全局锁 → 保护 _LOCKS 这张表本身；_LOCKS[绝对路径] → 该路径的专用可重入锁
_LOCKS_GUARD = threading.Lock()
_LOCKS = {}

# 原子写临时名的中间段（白名单判据，**单一来源**）：
#   ""                     → "<名字>.tmp"（v2.3.0 之前的固定名，历史残留仍要清）
#   "<线程号>"             → "<名字>.<线程号>.tmp"（v2.3.0/2.3.1 早期）
#   "<进程号>.<线程号>"     → "<名字>.<进程号>.<线程号>.tmp"（v2.3.1 起，见 atomic_write_bytes）
# 只认"两段以内纯十进制数字"：用户自己的 "lines.json.v2.tmp" / "x.bak" 一律不在白名单里。
# 用 [0-9] 而不是 \d：[0-9] 只认 ASCII，\d 在 Python 里还认阿拉伯-印度数字等（会误删）。
_TMP_MID_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?\Z")

# os.replace 共享冲突（Windows 杀软/索引器/残留句柄）重试间隔：实测 50ms 足够让
# 瞬时句柄释放，最多重试 retries 次（默认 3 → 最坏多等 150ms，只发生在故障路径上）
_RETRY_SLEEP = 0.05


def path_lock(path):
    """取某路径的专用锁（可重入）。同一路径的所有写者拿到的必须是同一把锁。

    v2.3.1（L1 修复）：键先 normcase(abspath)——Windows 文件系统大小写不敏感，
    "x.json" 与 "X.JSON" 指向**同一个文件**，按字面路径分锁会给出两把不同的锁
    （等于没锁：两个写者各自持锁交错写盘）。macOS 默认同款。
    """
    key = os.path.normcase(os.path.abspath(str(path)))
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
    """删除本次写入自己的临时文件（进程+线程唯一名，别人不会用这个路径）。"""
    try:
        if os.path.exists(tmp):
            os.remove(tmp)
    except Exception as e:
        _log(log, "pet_io 临时文件清理失败 %s: %r" % (tmp, e))


def _default_from(factory, expect, log, path):
    """取调用方注入的默认值；连默认值都造不出来时退回与 expect 同型的空容器。

    v2.3.1（M3）：本模块对外的承诺是"绝不抛异常"，而 factory 是**调用方注入**的
    可调用对象——它自己抛异常时不能穿透到调用栈（读文件的位置通常没有 try）。
    """
    try:
        return factory()
    except Exception as e:
        _log(log, "pet_io 默认值构造失败（改用空结构）%s: %r" % (path, e))
        if expect is dict:
            return {}
        if expect is list:
            return []
        return None


def backup_before_heal(path, log=None):
    """愈合/重建**之前**把原文件另存 "<path>.bak"（留证，判错时可手工恢复）。

    返回 True=已备份、False=文件不存在或备份失败（失败只记日志，绝不抛：
    备份失败不该反过来挡住愈合）。所有"自建读+回写愈合"的调用点都应先调它，
    与 heal_json 内部口径一致。

    **.bak 生命周期（v2.3.1 一致性收口）**：备份名是**固定**的 "<path>.bak"，不生成
    "<path>.bak.1/.2/…"。因此：
      · 单个目标路径的 .bak 数量上限恒为 1（同目录 .bak 总数 = 被愈合过的目标路径数，
        不会随愈合次数增长——愈合 N 次也只多一份"最近一次愈合前的内容"）；
      · 上一轮残留的 .bak 会被本次覆盖，覆盖时**记一行日志**说明，避免用户把新备份
        误当成最早那份坏数据（老备份没有诊断价值，这是刻意的取舍：宁可留最近的，
        也不要备份无限增殖把数据目录撑满）。
    运行时残留（.tmp/.bak）不进绿色版目录与发布包——_check_release.py 会点名。
    """
    src = str(path)
    try:
        if not os.path.exists(src):
            return False
        if os.path.exists(src + ".bak"):
            _log(log, "pet_io 旧备份已被本次愈合覆盖（同目标只保留最近一份 .bak）%s"
                 % (src + ".bak"))
        shutil.copyfile(src, src + ".bak")
        return True
    except Exception as e:
        _log(log, "pet_io 愈合备份失败（继续愈合）%s: %r" % (src, e))
        return False


def clean_tmp_files(targets, log=None):
    """清扫这些目标文件的原子写残留（三种临时名形状，见 _TMP_MID_RE）。

    v2.3.1（L4）：临时名带线程号之后，退出/清 Key 时只删固定名 ".tmp" 已经扫不到
    真正会残留的文件（崩溃时留下的是 "<p>.12345.tmp"）。
    v2.3.1（一致性收口）：临时名再加**进程号**（"<p>.<pid>.<tid>.tmp"），白名单同步放宽成
    "中间段 ≤2 段纯十进制数字"——旧形状（"<p>.tmp" / "<p>.<tid>.tmp"）仍要清（升级后
    磁盘上就有这种残留），新形状也要清。**白名单**：只认这三种形状，不动用户的其它文件
    （"<p>.v2.tmp"、"<p>.bak" 都不在白名单里）。

    返回实际删除条数，绝不抛异常。每个目标先取**同一把路径锁**：在途写者持锁期间
    （锁内是"写 tmp → os.replace"整段）它的 tmp 不可能被本函数删掉，因此运行期调用也安全。
    """
    removed = 0
    for p in (targets or ()):
        p = str(p)
        d = os.path.dirname(p) or "."
        base = os.path.basename(p)
        try:
            with path_lock(p):
                names = [base + ".tmp"]
                try:
                    for n in os.listdir(d):
                        if n.startswith(base + ".") and n.endswith(".tmp"):
                            if _TMP_MID_RE.match(n[len(base) + 1:-4]):
                                names.append(n)
                except OSError as e:
                    _log(log, "pet_io 临时文件枚举失败 %s: %r" % (d, e))
                for n in names:
                    fp = os.path.join(d, n)
                    try:
                        if os.path.isfile(fp):
                            os.remove(fp)
                            removed += 1
                    except OSError as e:
                        _log(log, "pet_io 临时文件清理失败 %s: %r" % (fp, e))
        except Exception as e:
            _log(log, "pet_io 临时文件清理跳过 %s: %r" % (p, e))
    return removed


def _guard(path, lock):
    """按固定顺序取锁：调用方锁（可选）→ 路径锁。返回 contextmanager。"""
    path_lk = path_lock(path)
    if lock is None or lock is path_lk:
        return path_lk
    return _MergeGuard(lock, path_lk)


class _MergeGuard(object):
    """同时持有"调用方锁 + 路径锁（可以更多把）"的极简上下文（顺序固定 → 不会死锁）。

    v2.3.1（一致性收口）：此前 __enter__ 写死了 self._locks[0] / [1]——传第 3 把锁会被
    **静默忽略**（调用方以为自己持锁了，其实没有；这比直接报错危险得多）。现在改成真变参：
    按传入顺序逐个 acquire，中途失败就**逆序回滚**已拿到的那几把；__exit__ 逆序释放。
    同一个锁对象被重复传入时只 acquire 一次（否则非可重入锁会自己把自己锁死）。
    """

    __slots__ = ("_locks",)

    def __init__(self, *locks):
        uniq = []
        seen = set()
        for lk in locks:
            if id(lk) in seen:      # 重复传入同一对象：只算一把（RLock 之外的自锁死保护）
                continue
            seen.add(id(lk))
            uniq.append(lk)
        self._locks = tuple(uniq)

    def __enter__(self):
        held = []
        try:
            for lk in self._locks:
                lk.acquire()
                held.append(lk)
        except Exception:
            for lk in reversed(held):   # 中途失败：把自己已经拿到的锁还回去
                lk.release()
            raise
        return self

    def __exit__(self, *exc):
        for lk in reversed(self._locks):
            lk.release()
        return False


def atomic_write_bytes(path, data, *, lock=None, retries=3, log=None):
    """原子写二进制：临时文件 + os.replace；成功返回 None，失败返回错误字符串（绝不抛）。

    临时名带**进程号 + 线程号**（"%s.%d.%d.tmp" % (path, pid, tid)）——两个线程同时写
    同一文件不会抢同一个 tmp 互相截断，**同机多实例/调试双开**时也不会撞名（两个进程的
    线程号完全可能相同，只带线程号挡不住跨进程撞名）。os.replace 因共享冲突失败时 sleep
    后重试（最多 retries 次），最终失败则清理自己的 tmp 并记日志。
    clean_tmp_files 按同一形状白名单清扫（见 _TMP_MID_RE）。
    """
    path = str(path)
    tmp = "%s.%d.%d.tmp" % (path, os.getpid(), threading.get_ident())
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
        _cleanup_tmp(tmp, log)   # 失败清理自己的 tmp（退出时的 *.tmp 清扫见 clean_tmp_files）
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

    与 heal_json 同口径：factory 自己抛异常也不外泄（M3），退回与 expect 同型的空容器。
    """
    try:
        # v2.3.1（兼容审查 S1）：用 utf-8-sig——用户用记事本另存为「UTF-8 with BOM」时
        # 内容其实完好，用 utf-8 读会抛 JSONDecodeError 被判"损坏"→ 被空结构覆盖清空。
        with open(str(path), "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except FileNotFoundError:
        return _default_from(factory, expect, log, path), False
    except OSError as e:
        _log(log, "pet_io 读取失败（按默认值继续）%s: %r" % (path, e))
        return _default_from(factory, expect, log, path), False
    except UnicodeDecodeError as e:
        # v2.3.1（兼容审查 S1）：解码失败 ≠ 内容损坏。GBK/ANSI 另存的文件内容完全可读，
        # 旧版对它一个字节都不动；把它判成"坏"再回写 = 原地销毁用户数据。
        # 与 OSError 同口径：不能证明损坏 → 不回写，只记一行日志。
        _log(log, "pet_io 编码不是 UTF-8（按默认值继续，不覆盖原文件）%s: %r" % (path, e))
        return _default_from(factory, expect, log, path), False
    except Exception as e:
        # 其余（JSONDecodeError / RecursionError…）= 文件内容确实坏了
        _log(log, "pet_io 解析失败（按默认值重建）%s: %r" % (path, e))
        return _default_from(factory, expect, log, path), True
    if expect is not None and not isinstance(data, expect):
        _log(log, "pet_io 顶层结构非法（按默认值重建）%s: %s"
             % (path, type(data).__name__))
        return _default_from(factory, expect, log, path), True
    return data, False


def load_json(path, factory=dict, *, expect=dict, log=None):
    """read_json_or 的 ok 口径快捷版：返回 (data, ok)（ok=False=文件损坏）。"""
    data, corrupted = read_json_or(path, factory, expect=expect, log=log)
    return data, not corrupted


def _safe_normalize(normalize, data, log, path):
    """跑调用方注入的"内层结构"判据，返回 (fixed, reason)，绝不抛。

    normalize(data) 应当返回 (fixed, reason)：
      · reason 为空（None/""/False）= 内层结构合法 → 调用方**一个字节都不该被写**；
      · reason 非空 = 顶层合法但内层类型非法（如 {"history": {...}}）→ fixed 是"能被
        安全重建"的结构，本模块据此记日志 + 留 .bak + 回写。
    判据自己抛异常、或返回值不是二元组（写错了 API）时按"没坏"处理——**宁可少写一次，
    也不能因为判据写错就把用户的文件洗掉**。
    """
    try:
        fixed, reason = normalize(data)
    except Exception as e:
        _log(log, "pet_io 内层结构检查失败（按原样继续，不写盘）%s: %r" % (path, e))
        return data, None
    if not reason:
        return data, None
    return fixed, str(reason)


def heal_json(path, factory=dict, *, expect=dict, log=None, retries=3, indent=2,
              normalize=None):
    """读 JSON；**只在文件仍然是坏的**时才回写 factory() 结构（一次性愈合）。

    返回 (data, corrupted)。"仍然是坏的"= 在同一把路径锁内重新读一次的结果；
    若期间已有写者修好了文件，读到的是新数据 → 不再回写，因此**绝不覆盖更新数据**。

    indent：愈合回写的缩进口径，默认 2（各索引文件的既有口径）；memory.json 这类
    原本是**紧凑单行**的文件由调用方传 indent=None（L2：愈合不能顺手改变文件格式）。

    normalize（v2.3.1 一致性收口，可选）：内层类型判据 callable(data) -> (fixed, reason)。
    顶层结构合法、但内层字段类型非法（P2：{"history": {...}}、"clips": [...] 这类）以前
    **静默返回空、无日志、不愈合**；给判据后统一成：reason 非空 → 记一行日志 + 留 .bak
    + 回写 fixed（与顶层损坏同一把锁、同一份备份口径），并把 fixed 作为返回的 data
    （让调用方内存态与盘上内容一致）。reason 为空 → 原样返回，不写。
    只有"能被归一化安全重建"的字段才该由调用方给出 fixed；不安全的（重建会丢用户
    能用的数据）请让判据自己记日志并返回 reason=None。
    """
    lock = path_lock(path)
    with lock:
        data, corrupted = read_json_or(path, factory, expect=expect, log=log)
        if corrupted:
            # v2.3.1（兼容审查 S1）：愈合前先把原文件另存 .bak——万一判错了（未来又出现
            # 某种"内容可读但被判坏"的假阳性），用户的数据还在，可手工恢复。
            backup_before_heal(path, log)
            # 锁还在手上：此刻没有本进程写者能在"读到坏"与"回写"之间插入新数据
            atomic_write_json(path, _default_from(factory, expect, log, path),
                              lock=lock, retries=retries, log=log, indent=indent)
        elif normalize is not None:
            # 锁在手上 → "读到内层非法"与"回写"之间同样插不进本进程写者（口径与上面一致）
            fixed, reason = _safe_normalize(normalize, data, log, path)
            if reason:
                backup_before_heal(path, log)
                _log(log, "pet_io 内层结构非法（已留 .bak 并按归一化结构重建）%s: %s"
                     % (path, reason))
                atomic_write_json(path, fixed, lock=lock, retries=retries, log=log,
                                  indent=indent)
                data = fixed
    return data, corrupted
