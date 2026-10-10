# -*- coding: utf-8 -*-
"""
大肥鱼桌宠 —— 记账账本模块（v1.3.0 新增）。

职责：参考 dsh-whale-widget 的「记账账本」设计，记录 API 余额消费与手动记账，
提供今日 / 近 7 天 / 全部历史统计、搜索、预算与余额提醒、CSV 导出。

对外接口：
- class Book(data_dir)
    文件 data_dir/ledger.json + data_dir/ledger_archive.json；损坏自动重建；
    若存在旧 usage.json（{"date","usage","last_balance"}）且 ledger 不存在 →
    自动迁移（当日用量记为一条 kind="api" 记录并沿用 last_balance）。
    observe_balance(total)      # 余额差记账：跨天自动归档昨日并把今日清零
    add_manual(amount, note="") # 手动记账，kind="manual"，amount 必须 > 0
    today_usage() -> float      # 今日合计
    week_usage() -> float       # 最近 7 天（含今天）合计
    daily_totals(n=7) -> list   # [("2026-09-22", 1.23), ...] 由旧到新
    all_records() -> list       # archive+当前合并，按 ts 倒序；每条
                                # {"date","time","amount","kind","note"}
    search_records(term) -> list# 日期子串或备注子串匹配（不区分大小写）
    total_amount() -> float     # 全部历史合计
    total_count() -> int        # 全部记录条数
    check_alerts(total, budget, balance_alert) -> list
                                # budget/balance_alert 浮点（<=0 = 关闭）；
                                # 每类每天只提醒一次（ledger 记 alerted_* 当天日期）
    export_csv(path) -> (bool, str)  # UTF-8 with BOM，列：日期,时间,类型,金额,备注
    reset_balance_baseline()    # 清 key 时调用：last_balance=None，保留 manual 记录
    last_balance (属性) -> float|None
    has_data() -> bool

数据文件结构：
- ledger.json：{"date","last_balance","records":[{"ts","date","time","amount","kind","note"}],
                "alerted_budget","alerted_balance"}
- ledger_archive.json：{"days":{"2026-09-21":{"total","count","records":[...]}}}

归档保留：逐日记录最多 365 天、单日 records 最多 20000 条，超期/超量丢弃最旧。

实现要点：
- 纯标准库（json/os/time/datetime），不依赖 PySide6，无 GUI 可运行。
- 全部文件 IO 走「写临时文件 + os.replace」原子替换；任何异常降级，
  绝不向调用方抛异常（数据文件损坏/读写失败记入 error.log）。
- 金额统一 float 并四舍五入到分（round(x, 2)）。

Python 3.10+（项目运行环境 3.10.2）。

MIT License
Copyright (c) 大肥鱼桌宠项目
"""

import datetime
import json
import math
import os
import threading
import time

import pet_io   # v2.3.1：全仓共用原子写/安全读（分锁 + 线程唯一临时名 + replace 重试）
import pet_log

# 归档保留策略
_ARCHIVE_MAX_DAYS = 365
_DAY_MAX_RECORDS = 20000


# ---------------- 通用 IO 助手（v2.3.1：统一走 pet_io；原子替换，降级不抛） ----------------
# 哨兵：pet_io.read_json_or 只在"走到 factory()"时返回它（真数据永远是 json.load 造的新对象，
# 不可能与这个进程内对象相同）→ 用它把"文件不存在"与"文件在、这次没读到"分开。
_PROBE = object()


def _read_json(path, factory=dict, heal=True):
    """读 JSON → (data, corrupted, unreadable)，绝不抛出。

    unreadable=True：文件**在磁盘上**但这次读不到（权限/共享占用/非 UTF-8 编码）——
    与"文件不存在（首次运行）"严格区分：前者不能证明文件坏了，**绝不能回写覆盖**
    （pet_io 的契约：读取失败 ≠ 损坏；P0-B 实测：一次瞬时 PermissionError 就让
    Book.__init__ 末尾的 _save_all 把完好账本清成 records=0，连 .bak 都没有）。

    v2.3.1（读侧愈合口径一致性收口）：**真损坏即愈合回写**（pet_io.heal_json：同一把路径锁
    内复查 → 先留 "<path>.bak" → 回写 → 记日志），与 alarms/behaviors/lines/索引/voice 同口径。
    此前只靠 Book.__init__ 末尾的 _save_all / 写前恢复**间接**自愈，两个口子：
      · 全程没有 .bak——判错（或以后归一化逻辑出 bug）时无从恢复；
      · 读失败保护（P0-B）生效时会整体跳过 _save_all，坏文件就留在盘上、每次启动重报
        （error.log 实测 pet_book._read_json ×170）。
    heal=False 给"马上要把文件改名 / 另有更强恢复路径"的调用方：_migrate_usage 读完
    usage.json 就会 os.replace 把它改名，先愈合再改名只会凭空多一份 .bak 与困惑。
    **读不到（OSError / 非 UTF-8）一律不写**——这条保护不能被愈合改掉。
    """
    data, corrupted = pet_io.read_json_or(path, lambda: _PROBE, log=pet_log.log_error)
    if data is _PROBE:
        # 走到 factory() 的三种情况：文件不存在 / 读失败 / 解码失败（corrupted=False），
        # 以及**真损坏**（corrupted=True，此时 factory() 返回的正是哨兵本身）。
        if corrupted:
            # 真损坏（文件确实在盘上、内容解析不了或顶层类型非法）→ 愈合回写（含 .bak）
            if heal:
                pet_io.heal_json(path, factory, log=pet_log.log_error)
            return factory(), True, False
        # 文件不存在（首次运行）或这次读不到：**都不写盘**，只用 exists 把两者分开
        return factory(), False, os.path.exists(str(path))
    return data, corrupted, False


# v2.3.0（兼容审查 M5）：账本此前假定"只有主线程写"。1.2/1.3 之后 worker 线程每条消息都会
# 读账本（AI 摘要/工具摘要），跨天时 today_usage() → _ensure_today() 会走归档写盘路径，
# 与主线程 _save_all 抢同一个 "<file>.tmp"。这里加一把可重入锁 + 线程唯一临时名。
_BOOK_WRITE_LOCK = threading.RLock()


def _write_json(path, data):
    """原子写 JSON（v2.3.1：统一走 pet_io）；成功返回 None，失败返回错误字符串。

    v2.3.0：临时文件名带线程号 + 写盘段互斥（避免两个线程抢同一 .tmp 后各自 replace）。
    v2.3.1：实现挪进 pet_io（按路径分锁 + 线程唯一临时名 + os.replace 冲突重试），
    _BOOK_WRITE_LOCK 作为调用方锁**原样保留**（既有语义不变，额外多一层路径锁）。
    """
    return pet_io.atomic_write_json(path, data, lock=_BOOK_WRITE_LOCK, log=None)


def _today():
    return time.strftime("%Y-%m-%d")


def _date_shift(date_str, days):
    """ISO 日期字符串 +/- days 天；解析失败回退今天。"""
    try:
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d") + datetime.timedelta(days=days)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return _today()


def _normalize_record(r):
    """记录归一化：字段补全、金额取正并四舍五入到分；非法记录返回 None。"""
    if not isinstance(r, dict):
        return None
    amount = r.get("amount")
    if not isinstance(amount, (int, float)):
        return None
    amount = round(float(amount), 2)
    # v2.2.5：NaN/Inf 的 <= 0 都是 False，此前会绕过校验 → 参与 sum() 后统计全变 NaN
    if not math.isfinite(amount) or amount <= 0:
        return None
    ts = r.get("ts")
    if not isinstance(ts, (int, float)):
        ts = time.time()
    try:
        lt = time.localtime(ts)
    except Exception:
        lt = time.localtime()  # ts 非法（inf/超大值）：用当前时间兜底，保证账本永不因单条记录失效
    date = str(r.get("date") or "") or time.strftime("%Y-%m-%d", lt)
    tm = str(r.get("time") or "") or time.strftime("%H:%M:%S", lt)
    kind = r.get("kind")
    if kind not in ("api", "manual"):
        kind = "manual"
    return {
        "ts": float(ts),
        "date": date,
        "time": tm,
        "amount": amount,
        "kind": kind,
        "note": str(r.get("note") or ""),
    }


def _clean_records(raw):
    """记录列表归一化（非 list / 坏条目一律丢弃）——读侧与"恢复合并"共用同一口径。"""
    recs = raw if isinstance(raw, list) else []
    return [r for r in (_normalize_record(x) for x in recs) if r is not None]


def _merge_records(disk_records, mem_records):
    """磁盘记录 + 本次内存新增记录，按 (ts, amount, note) 去重（P0-B 恢复合并）。

    去重键与 _archive_day 一致（同一秒内的多笔记账不会被误判成重复）。
    顺序：磁盘在前、内存新增在后——"原有的不会被新写的挤掉"。
    """
    seen = set()
    out = []
    for r in list(disk_records) + list(mem_records):
        key = (r.get("ts"), r.get("amount"), r.get("note"))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _clean_days(raw_days):
    """归档 days 归一化（{date: {total,count,records}}）；非 dict 一律按空处理。"""
    days = raw_days if isinstance(raw_days, dict) else {}
    clean_days = {}
    for d, v in days.items():
        if not isinstance(v, dict):
            continue
        clean_recs = _clean_records(v.get("records"))
        total = v.get("total")
        if not isinstance(total, (int, float)):
            total = round(sum(float(r["amount"]) for r in clean_recs), 2)
        count = v.get("count")
        if not isinstance(count, int) or count <= 0:
            count = len(clean_recs)
        clean_days[str(d)] = {
            "total": round(float(total), 2),
            "count": count,
            "records": clean_recs,
        }
    return clean_days


def _new_record(amount, kind, note):
    """按当前时刻生成一条新记录。"""
    ts = time.time()
    return {
        "ts": ts,
        "date": _today(),
        "time": time.strftime("%H:%M:%S"),
        "amount": round(float(amount), 2),
        "kind": kind,
        "note": str(note or ""),
    }


def _public(r):
    """对外视图：仅暴露 date/time/amount/kind/note 五列。"""
    return {
        "date": r["date"],
        "time": r["time"],
        "amount": r["amount"],
        "kind": r["kind"],
        "note": r["note"],
    }


# ---------------- 账本 ----------------
class Book:
    """记账账本：余额差 + 手动记账，按日归档，统计 / 搜索 / 提醒 / 导出。"""

    def __init__(self, data_dir):
        self._ledger_path = os.path.join(data_dir, "ledger.json")
        self._archive_path = os.path.join(data_dir, "ledger_archive.json")
        self._ledger = {
            "date": _today(),
            "last_balance": None,
            "records": [],
            "alerted_budget": "",
            "alerted_balance": "",
        }
        self._archive = {"days": {}}
        self._read_failed = False   # P0-B：本次启动有没有"文件在但读不到"
        self._date_inferred = False  # M1（v2.4）：ledger 的日界是"读不到、按今天兜底"推出来的
        self._load()
        self._migrate_usage()
        self._ensure_today()
        if self._read_failed:
            # P0-B：读失败时**只读启动 + 标脏**，绝不在这里回写。
            # 此前无条件 _save_all()：一次瞬时读失败（权限/杀软占用）就把内存里的空账本
            # 盖回磁盘 → 用户的账记录清零、无备份、无提示。等下一次真正的写操作
            # （add_manual/observe_balance/check_alerts…）再落盘。
            try:
                pet_log.log_error("ledger 本次启动未能读到（已跳过回写，等下一次写操作再落盘）")
            except Exception:
                pass  # 有意忽略：日志通道自身异常不影响主流程
        else:
            self._save_all()  # 归一化 / 迁移 / 跨天归档后统一落盘（失败静默）

    # ---------- 内部：读写与归一化 ----------
    def _load(self):
        """读两个数据文件并归一化；**真损坏**按空结构重建，读不到则标记跳过回写。"""
        led, _led_corrupt, _led_unreadable = _read_json(self._ledger_path)
        # P2（v2.3.1 一致性收口）：顶层是对象、但**内层字段类型非法**时（records 不是列表）
        # 归一化会静默丢成空表，用户看不到任何痕迹。这里补一行日志留痕（真正的落盘由
        # 本函数末尾 / __init__ 的 _save_all 完成；真损坏那条路径已在 _read_json 里留 .bak）。
        if isinstance(led, dict) and "records" in led and not isinstance(led["records"], list):
            pet_log.log_error("ledger records 字段不是列表（已按空表重建）：%s"
                              % self._ledger_path)
        clean = _clean_records(led.get("records"))
        lb = led.get("last_balance")
        if not isinstance(lb, (int, float)):
            lb = None
        # M1（v2.4 审查）：磁盘上（或这次没读到）没有 date 时，日界只能按"今天"推断——
        # 把这个事实记下来：_recover_from_disk 读回来之后必须把磁盘日界采回来，否则
        # 磁盘上的"昨日账本"会被整体当成今日（昨日既不归档、又被算进 today_usage()，
        # 日图把昨天画进今天）。
        _date_raw = str(led.get("date") or "")
        self._date_inferred = not _date_raw
        self._ledger = {
            "date": _date_raw or _today(),
            "last_balance": round(float(lb), 2) if lb is not None else None,
            "records": clean,
            "alerted_budget": str(led.get("alerted_budget") or ""),
            "alerted_balance": str(led.get("alerted_balance") or ""),
        }
        arc, _arc_corrupt, _arc_unreadable = _read_json(self._archive_path)
        # 任一个文件"在磁盘上但没读到" → 本次启动不整体回写（_save_all 会同时写两个文件，
        # 用一个的空内存态覆盖另一个的好文件也同样是丢数据）
        self._read_failed = bool(_led_unreadable or _arc_unreadable)
        # 同上：归档 days 字段类型非法 → 归一化静默丢成空表，补一行日志留痕
        if isinstance(arc, dict) and "days" in arc and not isinstance(arc["days"], dict):
            pet_log.log_error("ledger_archive days 字段不是对象（已按空表重建）：%s"
                              % self._archive_path)
        self._archive = {"days": _clean_days(arc.get("days"))}
        self._trim_archive()

    def _recover_from_disk(self):
        """读失败之后的**第一次真实写**之前，先重试读一次磁盘并合并（P0-B 补）。

        返回 None = 可以继续写；返回错误串 = **本次落盘必须放弃**。

        - 启动时读成功过的实例（_read_failed=False）→ 直接返回 None：不每次写都重读。
        - 启动时"文件在但读不到" → 重试读两个文件：
          · 读到合法数据 → 磁盘记录与本次内存新增按 (ts, amount, note) 去重合并
            （_merge_records），归档按日期取并集（内存里的更新状态优先），
            然后**清除标记**回到正常路径；
          · 仍然读不到 → 保持标记并返回错误串（调用方放弃落盘 + 记日志），
            内存继续脏着，等下一次写再试。
        这样"读失败之后用户又记了一笔"不会把磁盘上的旧账挤掉。
        """
        if not self._read_failed:
            return None
        led, _led_corrupt, led_unreadable = _read_json(self._ledger_path)
        arc, _arc_corrupt, arc_unreadable = _read_json(self._archive_path)
        if led_unreadable or arc_unreadable:
            return "账本读不到（已放弃本次落盘，避免用空账本覆盖磁盘）"
        # M1（v2.4 审查）：日界也要采回来（不只并 records）。读不到时 date 兜底成 _today()，
        # 这里若只并 records 不并 date，磁盘上的"昨日账本"就整体被当成今日。采回日界之后
        # **必须重走一次 _ensure_today()**——否则这批旧记录会顶着"昨天"的日界留在 ledger 里
        # 继续当今天用（today_usage() 偏大、日图失真）。
        carry = []
        if self._date_inferred:
            self._date_inferred = False
            disk_date = str(led.get("date") or "")
            if disk_date:
                # 内存里本次新增的记录各自带 date（_new_record 写的是"当时推断的今天"）：
                # 与磁盘日界同日的那部分并进磁盘日界一起归档，其余（推断日）等归档完再放回。
                mem = self._ledger["records"]
                carry = [r for r in mem if str(r.get("date") or "") != disk_date]
                self._ledger["records"] = [r for r in mem
                                           if str(r.get("date") or "") == disk_date]
                self._ledger["date"] = disk_date
        self._ledger["records"] = _merge_records(_clean_records(led.get("records")),
                                                 self._ledger["records"])
        # 标量字段：内存里"本次真的动过"的值优先，否则沿用磁盘上原有的
        # （读失败时 last_balance 是 None，不能因此把用户已知的余额基准抹掉）
        if self._ledger.get("last_balance") is None:
            lb = led.get("last_balance")
            if isinstance(lb, (int, float)):
                self._ledger["last_balance"] = round(float(lb), 2)
        for _k in ("alerted_budget", "alerted_balance"):
            if not self._ledger.get(_k):
                self._ledger[_k] = str(led.get(_k) or "")
        days = _clean_days(arc.get("days"))
        days.update(self._archive.get("days") or {})   # 内存（更新的状态）优先
        self._archive["days"] = days
        self._trim_archive()
        self._read_failed = False
        if carry:
            # 采回日界后重走一次跨天归档（内部自己会再取一次 _recover_from_disk，
            # 此刻 _read_failed 已清 → 是空操作，不会递归），再把"推断日"的记录放回 ledger。
            self._ensure_today()
            self._ledger["records"] = _merge_records(self._ledger["records"], carry)
        try:
            pet_log.log_error("ledger 读取恢复：磁盘记录与本次新增已合并（共 %d 条）"
                              % len(self._ledger["records"]))
        except Exception:
            pass  # 有意忽略：日志通道自身异常不影响主流程
        return None

    def _save_all(self):
        """原子写两个数据文件；返回错误字符串或 None（调用方按需消费）。

        v2.4（审查 S1）：整段（读失败恢复 + 两个文件的快照落盘）都在 _BOOK_WRITE_LOCK
        内完成。此前只锁了"单次写盘"，另一个线程的跨天归档可以插在"写 ledger"与
        "写 archive"之间，把两份文件写成互相矛盾的快照（一边已清空、另一边还没收到）。
        """
        with _BOOK_WRITE_LOCK:
            err = self._recover_from_disk()
            if err:
                try:
                    pet_log.log_error("ledger 本次不落盘：%s" % err)
                except Exception:
                    pass  # 有意忽略：日志通道自身异常不影响主流程
                return err
            e1 = _write_json(self._ledger_path, self._ledger)
            e2 = _write_json(self._archive_path, self._archive)
            err = e1 or e2
            if err:
                # v2.2.5：失败必须留痕（5 个调用点此前把错误串全部丢弃 → 磁盘满/只读时内存已改、
                # 磁盘没落，重启即静默丢账；唯一检查返回值的是 _ensure_today）。
                try:
                    # v2.2.5（质量审查 A1）：必须用 pet_log.log_error——此前写的 self._log 是一个
                    # **不存在的方法**，AttributeError 又被下面的 except 吞掉 → "留痕"成了死代码
                    pet_log.log_error("ledger 落盘失败：%s" % err)
                except Exception:
                    pass  # 有意忽略：日志通道自身异常不影响主流程
            return err

    def _migrate_usage(self):
        """旧 usage.json → ledger 迁移：仅当 ledger.json 不存在时执行一次。

        usage.json 形如 {"date","usage","last_balance"}：当日用量记为一条
        kind="api" 记录（历史日期则入归档），last_balance 直接沿用。
        """
        if os.path.exists(self._ledger_path):
            return
        usage_path = os.path.join(os.path.dirname(self._ledger_path), "usage.json")
        if not os.path.exists(usage_path):
            return
        # heal=False：这个文件马上要被 os.replace 改名成 usage.json.migrated，先愈合回写
        # 只会凭空多一份 .bak（原始内容会原样保留在 .migrated 里），于诊断无益
        u, _u_corrupt, _u_unreadable = _read_json(usage_path, heal=False)
        if _u_unreadable:
            return  # 读不到 usage.json：不动它、也不迁移（迁移会把文件改名，等于销毁）
        try:
            usage = round(float(u.get("usage") or 0.0), 2)
        except Exception:
            usage = 0.0
        lb = u.get("last_balance")
        try:
            lb = round(float(lb), 2) if isinstance(lb, (int, float)) else None
        except Exception:
            lb = None
        self._ledger["last_balance"] = lb
        if usage > 0:
            date = str(u.get("date") or "") or _today()
            rec = {
                "ts": time.time(),
                "date": date,
                "time": time.strftime("%H:%M:%S"),
                "amount": usage,
                "kind": "api",
                "note": "旧版用量迁移",
            }
            if date == _today():
                self._ledger["records"].append(rec)
            else:
                self._archive_day(date, [rec])  # 历史日期：入归档，不污染今日
        try:
            os.replace(usage_path, usage_path + ".migrated")  # 迁移后改名，防止 ledger 重建时重复迁移
        except Exception as e:
            pet_log.log_error("pet_book._migrate_usage: usage.json 改名失败（下次启动可能重复迁移）: %r" % (e,))

    def _ensure_today(self):
        """跨天处理：先落盘归档，成功后才清 ledger 昨日记录（防写序丢数据）。

        v2.4（审查 S1）：整段「读内存态 → 归档 → 重绑 records/date」都在 _BOOK_WRITE_LOCK
        内。此前只锁了写盘（_write_json），内存态的读-改-写是裸的：worker 线程的
        today_usage() 走到这里、与主线程 add_manual 的 append 交错时，A 取走旧 records
        引用 → B 记一笔（落进新列表）→ A 重绑 self._ledger["records"] = []，把 B 那笔
        整个丢掉（归档与 ledger 都查不到，随后落盘 = 永久丢账）。
        """
        with _BOOK_WRITE_LOCK:
            today = _today()
            if self._ledger["date"] == today:
                return
            # P0-B 补：这条路径也直接写盘（归档 + ledger），同样要先过"读失败恢复"闸门：
            # 读不到就整个跳过本次跨天归档（内存保持原状，等下一次写再试），绝不用空归档覆盖磁盘。
            err = self._recover_from_disk()
            if err:
                try:
                    pet_log.log_error("ledger 跨天归档跳过：%s" % err)
                except Exception:
                    pass  # 有意忽略：日志通道自身异常不影响主流程
                return
            if self._ledger["date"] == today:
                # M1（v2.4）：_recover_from_disk 采回磁盘日界后内部已经推过一次日界——此时
                # 再按"旧日界"归档一次会把恢复放回的今日记录错记进归档并清空 ledger。
                return
            old_date, records = self._ledger["date"], self._ledger["records"]
            self._archive_day(old_date, records)
            if _write_json(self._archive_path, self._archive) is not None:
                return  # 归档落盘失败：保持内存原状，下次再试（昨日记录不丢）
            self._ledger["records"] = []
            self._ledger["date"] = today
            _write_json(self._ledger_path, self._ledger)

    def _archive_day(self, date, records):
        """把记录并入某日归档（合并排序、截断单日上限），随后统一裁剪天数。

        v2.4（审查 S1）：归档也是内存态的读-改-写（days[date] 由现有内容 + 新记录算出），
        与 _ensure_today 共用 _BOOK_WRITE_LOCK（可重入，嵌套调用不额外阻塞）。
        """
        if not date or not records:
            return
        with _BOOK_WRITE_LOCK:
            self._archive_day_locked(date, records)

    def _archive_day_locked(self, date, records):
        """_archive_day 的锁内实现（调用方必须已持有 _BOOK_WRITE_LOCK）。"""
        days = self._archive["days"]
        existing = days.get(date)
        if existing:
            # v2.3.1（P2-3）：去重键从 ts（秒级）改成 (ts, amount, note) 三元组——
            # 同一秒内的多笔记账此前会被当成重复丢掉（真实金额静默丢失）。
            seen = {(r.get("ts"), r.get("amount"), r.get("note"))
                    for r in existing["records"]}
            merged = existing["records"] + [
                r for r in records
                if (r.get("ts"), r.get("amount"), r.get("note")) not in seen]
        else:
            merged = list(records)
        merged.sort(key=lambda r: r.get("ts") or 0.0)
        if len(merged) > _DAY_MAX_RECORDS:
            merged = merged[-_DAY_MAX_RECORDS:]
        days[date] = {
            "total": round(sum(float(r["amount"]) for r in merged), 2),
            "count": len(merged),
            "records": merged,
        }
        self._trim_archive()

    def _trim_archive(self):
        """归档天数上限 365：丢弃最旧日期。"""
        days = self._archive["days"]
        if len(days) <= _ARCHIVE_MAX_DAYS:
            return
        keep = sorted(days.keys())[-_ARCHIVE_MAX_DAYS:]
        self._archive["days"] = {d: days[d] for d in keep}

    # ---------- 记账 ----------
    def observe_balance(self, total):
        """余额差记账：total < last 时记一条 kind="api"；更新 last_balance=total。

        单次降幅异常大（>20% 且 >5 元）多半是平台调整（赠送过期/退款/活动），
        不自动记为消费，只提醒用户并重置基准。返回提醒文案或 None。
        """
        try:
            total = round(float(total), 2)
        except Exception:
            return None  # 有意忽略：非法余额输入放弃本次观测（防御性）
        # v2.4（审查 S1）：_ensure_today 的跨天归档 + 这里的账目读改写 + 落盘必须在
        # 同一把锁内完成（否则另一线程重绑 self._ledger["records"] 会吞掉本次追加）。
        with _BOOK_WRITE_LOCK:
            self._ensure_today()
            last = self._ledger.get("last_balance")
            note = None
            if last is not None and total < last:
                amount = round(last - total, 2)
                if amount > 0:
                    if amount > max(5.0, last * 0.2):
                        note = "余额一下少了 ¥%.2f（可能是平台调整，未计入消费）" % amount
                    else:
                        self._ledger["records"].append(_new_record(amount, "api", "API 余额差"))
            self._ledger["last_balance"] = total
            self._save_all()
        return note

    def add_manual(self, amount, note=""):
        """手动记账（kind="manual"）；amount 必须 > 0，否则静默忽略。"""
        try:
            amount = round(float(amount), 2)
        except Exception:
            return  # 有意忽略：非法金额静默忽略（docstring 约定）
        if amount <= 0:
            return
        # v2.4（审查 S1）：跨天归档与本次 append 必须在同一把锁内——归档成功后会**整体重绑**
        # self._ledger["records"]，两段分开做时中间插进来的那笔会被重绑丢掉（见 _ensure_today）。
        with _BOOK_WRITE_LOCK:
            self._ensure_today()
            self._ledger["records"].append(_new_record(amount, "manual", note))
            self._save_all()

    # ---------- 统计 ----------
    def today_usage(self):
        """今日合计（ledger 当前日）。"""
        self._ensure_today()
        return round(sum(float(r["amount"]) for r in self._ledger["records"]), 2)

    def week_usage(self):
        """最近 7 天（含今天）合计：今天用 ledger，过去用 archive。"""
        self._ensure_today()
        total = sum(float(r["amount"]) for r in self._ledger["records"])
        for i in range(1, 7):
            day = self._archive["days"].get(_date_shift(self._ledger["date"], -i))
            if day:
                total += float(day.get("total") or 0.0)
        return round(total, 2)

    def daily_totals(self, n=7):
        """最近 n 天逐日合计 [("2026-09-22", 1.23), ...]，由旧到新（无数据为 0.0）。"""
        try:
            n = max(1, min(int(n), _ARCHIVE_MAX_DAYS))
        except Exception:
            n = 7
        self._ensure_today()
        today = self._ledger["date"]
        out = []
        for i in range(n - 1, -1, -1):
            d = _date_shift(today, -i)
            if d == today:
                total = round(sum(float(r["amount"]) for r in self._ledger["records"]), 2)
            else:
                day = self._archive["days"].get(d)
                total = round(float(day["total"]), 2) if day else 0.0
            out.append((d, total))
        return out

    def all_records(self):
        """合并 archive + 当前记录，按 ts 倒序；每条 {"date","time","amount","kind","note"}。"""
        self._ensure_today()
        rows = []
        for day in self._archive["days"].values():
            rows.extend(day.get("records") or [])
        rows.extend(self._ledger["records"])
        rows.sort(key=lambda r: r.get("ts") or 0.0, reverse=True)
        return [_public(r) for r in rows]

    def search_records(self, term):
        """按日期子串或备注子串搜索（不区分大小写）；空 term 返回全部。"""
        term = str(term or "").strip().lower()
        if not term:
            return self.all_records()
        out = []
        for r in self.all_records():
            if term in r["date"].lower() or term in (r["note"] or "").lower():
                out.append(r)
        return out

    def total_amount(self):
        """全部历史合计（四舍五入到分）。"""
        return round(sum(float(r["amount"]) for r in self.all_records()), 2)

    def total_count(self):
        """全部历史记录条数。"""
        return len(self.all_records())

    # ---------- 提醒 ----------
    def check_alerts(self, total, budget, balance_alert):
        """预算 / 余额提醒：每类每天只提醒一次。

        budget / balance_alert 为浮点（<=0 = 关闭）。
        预算超限 → "今日已用 ¥x.xx，超过预算 ¥y.yy 啦！"
        余额低于阈值 → "余额只剩 ¥x.xx，要见底啦！"
        """
        alerts = []
        try:
            total = round(float(total), 2)
            budget = round(float(budget), 2)
            balance_alert = round(float(balance_alert), 2)
        except Exception:
            return alerts
        self._ensure_today()
        today = self._ledger["date"]
        changed = False
        if budget > 0:
            # 预算口径：只统计 API 消费（手动记账是补记，不该触发消费预算）
            used = sum(r["amount"] for r in self._ledger["records"] if r["kind"] == "api")
            used = round(used, 2)
            if used > budget and self._ledger.get("alerted_budget") != today:
                alerts.append("今日 API 消费 ¥%.2f，超过预算 ¥%.2f 啦！" % (used, budget))
                self._ledger["alerted_budget"] = today
                changed = True
        if balance_alert > 0 and total < balance_alert and self._ledger.get("alerted_balance") != today:
            alerts.append("余额只剩 ¥%.2f，要见底啦！" % total)
            self._ledger["alerted_balance"] = today
            changed = True
        if changed:
            self._save_all()
        return alerts

    # ---------- 导出 / 重置 ----------
    def export_csv(self, path):
        """导出 CSV（UTF-8 with BOM，Excel 兼容）。列：日期,时间,类型,金额,备注。

        原子写（临时文件 + os.replace）。成功返回 (True, "")，失败 (False, err)。
        """
        # v2.3.1（评审报告根因 A 的同类遗留）：固定 .tmp 在多写者/共享冲突下会丢写盘
        tmp = "%s.%d.tmp" % (str(path), threading.get_ident())
        try:
            def esc(v):
                v = str(v)
                if any(ch in v for ch in ',"\r\n'):
                    return '"' + v.replace('"', '""') + '"'
                return v

            lines = ["日期,时间,类型,金额,备注"]
            for r in self.all_records():
                kind = "API消费" if r["kind"] == "api" else "手动"
                lines.append(",".join([
                    r["date"],
                    r["time"],
                    kind,
                    "%.2f" % r["amount"],
                    esc(r["note"] or ""),
                ]))
            body = "\ufeff" + "\r\n".join(lines) + "\r\n"  # BOM + CRLF，Excel 兼容
            d = os.path.dirname(os.path.abspath(str(path)))
            if d:
                os.makedirs(d, exist_ok=True)
            with open(tmp, "wb") as f:
                f.write(body.encode("utf-8"))
            os.replace(tmp, path)
            return True, ""
        except Exception as e:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass  # 有意忽略：导出失败后的临时文件清理尽力而为
            return False, str(e)

    def reset_balance_baseline(self):
        """清 API Key 时调用：重置 last_balance=None，保留手动记录。"""
        self._ledger["last_balance"] = None
        self._save_all()

    @property
    def last_balance(self):
        """最近一次观察到的余额基准（float|None）。"""
        return self._ledger.get("last_balance")

    def has_data(self):
        """是否有任何账本数据（记录 / 归档 / 余额基准）。"""
        return (bool(self._ledger["records"])
                or bool(self._archive["days"])
                or self._ledger.get("last_balance") is not None)


# ---------------- 冒烟测试（无 GUI，可直接运行本文件） ----------------
if __name__ == "__main__":
    # P0-2：以下 print 为命令行冒烟工具输出（python pet_book.py 运行可见），保留不改为日志
    import tempfile
    import shutil

    tmp = tempfile.mkdtemp(prefix="pet_book_smoke_")
    today = time.strftime("%Y-%m-%d")
    yesterday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))

    print("=== 冒烟 1：手动记账 + 余额差 ===")
    b = Book(tmp)
    assert b.last_balance is None and not b.has_data()
    assert b.today_usage() == 0.0
    b.add_manual(5.0, "小鱼干")
    b.add_manual(0)    # 非法：静默忽略
    b.add_manual(-1)   # 非法：静默忽略
    assert b.today_usage() == 5.0
    b.observe_balance(100.0)
    assert b.last_balance == 100.0 and b.today_usage() == 5.0
    b.observe_balance(98.5)  # 余额差 1.5 → api 记录
    assert abs(b.today_usage() - 6.5) < 1e-9
    assert abs(b.week_usage() - 6.5) < 1e-9

    print("=== 冒烟 2：统计 / 搜索 / 导出 / 提醒 ===")
    dt = b.daily_totals(7)
    assert len(dt) == 7 and dt[-1] == (today, 6.5) and dt[0][0] < dt[-1][0]
    recs = b.all_records()
    assert len(recs) == 2 and set(r["kind"] for r in recs) == {"api", "manual"}
    s = b.search_records("鱼")
    assert len(s) == 1 and s[0]["kind"] == "manual"
    s2 = b.search_records(today)
    assert len(s2) == 2
    assert abs(b.total_amount() - 6.5) < 1e-9 and b.total_count() == 2
    # 预算口径：仅 API 消费（api 1.5 + 手动 5.0 中只算 1.5）
    alerts = b.check_alerts(98.5, 1.0, 99.0)  # API 消费 1.5 超预算 1.0 + 余额低于阈值
    assert len(alerts) == 2, alerts
    assert "1.50" in alerts[0] and "98.50" in alerts[1]
    assert b.check_alerts(98.5, 1.0, 99.0) == []  # 当天不重复
    csv_path = os.path.join(tmp, "ledger.csv")
    ok, err = b.export_csv(csv_path)
    assert ok and err == "", err
    with open(csv_path, "rb") as f:
        raw = f.read()
    assert raw.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM
    text = raw.decode("utf-8-sig")
    assert "日期,时间,类型,金额,备注" in text and "API消费" in text and "手动" in text
    # 父路径是普通文件 → 无法建目录，必须失败且不抛异常
    blocker = os.path.join(tmp, "afile")
    with open(blocker, "w", encoding="utf-8") as f:
        f.write("x")
    assert b.export_csv(os.path.join(blocker, "sub", "x.csv"))[0] is False

    print("=== 冒烟 3：跨天归档（直接改 ledger 日期为昨天再 observe） ===")
    b._ledger["date"] = yesterday
    b.observe_balance(97.0)  # 触发归档：昨天 6.5 入 archive；今天 98.5→97.0 = 1.5
    assert abs(b.today_usage() - 1.5) < 1e-9
    assert abs(b.week_usage() - 8.0) < 1e-9
    dt2 = b.daily_totals(7)
    assert dt2[-1] == (today, 1.5) and dt2[-2] == (yesterday, 6.5)
    assert b.total_count() == 3

    print("=== 冒烟 4：持久化 / 重置 / 迁移 / 损坏重建 ===")
    b2 = Book(tmp)
    assert abs(b2.today_usage() - 1.5) < 1e-9
    assert abs(b2.total_amount() - 8.0) < 1e-9
    assert b2.last_balance == 97.0 and b2.has_data()
    b2.reset_balance_baseline()
    assert b2.last_balance is None and b2.total_count() == 3
    # 旧 usage.json → 迁移（当日）
    tmp2 = tempfile.mkdtemp(prefix="pet_book_mig_")
    with open(os.path.join(tmp2, "usage.json"), "w", encoding="utf-8") as f:
        json.dump({"date": today, "usage": 3.21, "last_balance": 42.0}, f)
    bm = Book(tmp2)
    assert bm.last_balance == 42.0
    assert abs(bm.today_usage() - 3.21) < 1e-9
    assert bm.all_records()[0]["kind"] == "api"
    # 旧 usage.json → 迁移（历史日期入归档）
    tmp3 = tempfile.mkdtemp(prefix="pet_book_mig2_")
    with open(os.path.join(tmp3, "usage.json"), "w", encoding="utf-8") as f:
        json.dump({"date": yesterday, "usage": 2.5, "last_balance": 10.0}, f)
    bm2 = Book(tmp3)
    assert bm2.today_usage() == 0.0 and abs(bm2.total_amount() - 2.5) < 1e-9
    assert bm2.last_balance == 10.0
    # 损坏的 ledger.json 自动重建
    tmp4 = tempfile.mkdtemp(prefix="pet_book_corrupt_")
    with open(os.path.join(tmp4, "ledger.json"), "w", encoding="utf-8") as f:
        f.write("{ 这不是合法 json ")
    with open(os.path.join(tmp4, "ledger_archive.json"), "w", encoding="utf-8") as f:
        f.write("[1,2,3")
    bc = Book(tmp4)
    assert bc.today_usage() == 0.0 and bc.last_balance is None
    bc.add_manual(1.0)
    bc2 = Book(tmp4)
    assert abs(bc2.today_usage() - 1.0) < 1e-9

    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(tmp2, ignore_errors=True)
    shutil.rmtree(tmp3, ignore_errors=True)
    shutil.rmtree(tmp4, ignore_errors=True)
    print("BOOK SMOKE OK")
