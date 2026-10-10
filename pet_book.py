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
import time

import pet_log

# 归档保留策略
_ARCHIVE_MAX_DAYS = 365
_DAY_MAX_RECORDS = 20000


# ---------------- 通用 IO 助手（原子替换，降级不抛） ----------------
def _read_json(path, factory=dict):
    """读 JSON；文件缺失 / 损坏时返回 factory() 默认值，绝不抛出。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception as e:
        # 首次运行无文件=正常（静默）；文件存在但读取失败=真实故障，记日志
        if os.path.exists(path):
            pet_log.log_error("pet_book._read_json 读取失败（按默认值重建）: %r" % (e,))
    return factory()


def _write_json(path, data):
    """原子写 JSON（临时文件 + os.replace）；成功返回 None，失败返回错误字符串。"""
    tmp = path + ".tmp"
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return None
    except Exception as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass  # 有意忽略：临时文件清理尽力而为，失败不影响主流程
        return str(e)


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
        self._load()
        self._migrate_usage()
        self._ensure_today()
        self._save_all()  # 归一化 / 迁移 / 跨天归档后统一落盘（失败静默）

    # ---------- 内部：读写与归一化 ----------
    def _load(self):
        """读两个数据文件并归一化；损坏的文件按空结构重建。"""
        led = _read_json(self._ledger_path)
        records = led.get("records") if isinstance(led.get("records"), list) else []
        clean = [r for r in (_normalize_record(x) for x in records) if r is not None]
        lb = led.get("last_balance")
        if not isinstance(lb, (int, float)):
            lb = None
        self._ledger = {
            "date": str(led.get("date") or "") or _today(),
            "last_balance": round(float(lb), 2) if lb is not None else None,
            "records": clean,
            "alerted_budget": str(led.get("alerted_budget") or ""),
            "alerted_balance": str(led.get("alerted_balance") or ""),
        }
        arc = _read_json(self._archive_path)
        days = arc.get("days") if isinstance(arc.get("days"), dict) else {}
        clean_days = {}
        for d, v in days.items():
            if not isinstance(v, dict):
                continue
            recs = v.get("records") if isinstance(v.get("records"), list) else []
            clean_recs = [r for r in (_normalize_record(x) for x in recs) if r is not None]
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
        self._archive = {"days": clean_days}
        self._trim_archive()

    def _save_all(self):
        """原子写两个数据文件；返回错误字符串或 None（调用方按需消费）。"""
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
        u = _read_json(usage_path)
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
        """跨天处理：先落盘归档，成功后才清 ledger 昨日记录（防写序丢数据）。"""
        today = _today()
        if self._ledger["date"] == today:
            return
        old_date, records = self._ledger["date"], self._ledger["records"]
        self._archive_day(old_date, records)
        if _write_json(self._archive_path, self._archive) is not None:
            return  # 归档落盘失败：保持内存原状，下次再试（昨日记录不丢）
        self._ledger["records"] = []
        self._ledger["date"] = today
        _write_json(self._ledger_path, self._ledger)

    def _archive_day(self, date, records):
        """把记录并入某日归档（合并排序、截断单日上限），随后统一裁剪天数。"""
        if not date or not records:
            return
        days = self._archive["days"]
        existing = days.get(date)
        if existing:
            seen = {r.get("ts") for r in existing["records"]}
            merged = existing["records"] + [r for r in records if r.get("ts") not in seen]
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
        tmp = str(path) + ".tmp"
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
