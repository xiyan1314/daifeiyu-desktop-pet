# -*- coding: utf-8 -*-
"""M1（v2.4 审查）：账本读失败恢复不还原"日界"——昨日账被整体当成今日。

场景（与审查报告一致）：ledger.json 是昨日 2×9.99，用 GBK 落盘 = "文件在磁盘上但
这次读不到"（记事本另存 ANSI / 共享占用）。旧实现里 _load 把 date 兜底成 _today()，
而 _recover_from_disk 只并 records/last_balance/alerted_*/days、**不并 date**：
文件改回 UTF-8 后再记一笔 → 落盘 = date 今日 + 4 条（含昨日 2 条），
today_usage()=25.98（应为 6 元量级），日图把昨日算进今日。

护栏：date 是"推断出来的"时必须采回磁盘值，并重走一次 _ensure_today() 把旧日记录
归档；读失败期间（日界推断为今天）新增的记录仍留在今天。
"""
import json
import time

import pytest

import pet_book

YESTERDAY = pet_book._date_shift(pet_book._today(), -1)


def _rec(amount, date, note, ts):
    return {"ts": ts, "date": date, "time": "12:00:00", "amount": amount,
            "kind": "manual", "note": note}


def _write_gbk_ledger(path, data):
    """按 GBK 落盘（模拟"文件在、内容也完好，只是解码不了"）。"""
    text = json.dumps(data, ensure_ascii=False)
    path.write_bytes(text.encode("gbk"))
    return text


def _yesterday_ledger():
    now = time.time()
    return {
        "date": YESTERDAY,
        "last_balance": 100.0,
        "records": [_rec(9.99, YESTERDAY, "昨日A", now - 7200),
                    _rec(9.99, YESTERDAY, "昨日B", now - 7100)],
        "alerted_budget": "",
        "alerted_balance": "",
    }


def test_read_failure_does_not_touch_disk(tmp_path, monkeypatch):
    """前置事实（反例的对照）：读失败期间既不回写、也不覆盖（P0-B 口径不能回退）。"""
    p = tmp_path / "ledger.json"
    text = _write_gbk_ledger(p, _yesterday_ledger())
    raw = p.read_bytes()
    b = pet_book.Book(str(tmp_path))
    assert b._read_failed is True
    assert b._date_inferred is True, "读不到时 date 只能按今天推断，必须记下这个事实"
    assert b.today_usage() == 0.0 and b.last_balance is None
    b.add_manual(5.0, "读失败期间的账")      # 落盘必须被放弃
    assert p.read_bytes() == raw, "读不到还是把账本写回去了"


def test_recovered_disk_date_is_adopted_and_yesterday_archived(tmp_path):
    """主场景：文件改回 UTF-8 → 再记一笔 → 昨日归档、today 只算今日。"""
    p = tmp_path / "ledger.json"
    text = _write_gbk_ledger(p, _yesterday_ledger())
    b = pet_book.Book(str(tmp_path))
    b.add_manual(5.0, "读失败期间的账")       # 日界推断=今天，记账只进内存
    p.write_bytes(text.encode("utf-8"))       # 用户/工具把文件修回 UTF-8
    b.add_manual(1.0, "恢复后的账")           # 第一次真实写：必须先恢复磁盘日界

    # 今日只算今日两笔（5.00 + 1.00），不是 25.98（旧实现把昨日 2×9.99 也算进来）
    assert abs(b.today_usage() - 6.0) < 1e-9, "昨日账被算进今日：%r" % (b.today_usage(),)
    assert abs(b.total_amount() - 25.98) < 1e-9, "恢复过程把账弄丢了：%r" % (b.total_amount(),)
    assert b.total_count() == 4
    totals = b.daily_totals(7)
    assert abs(totals[-1][1] - 6.0) < 1e-9
    assert abs(totals[-2][1] - 19.98) < 1e-9, "昨日没有归档：%r" % (totals[-2],)
    # 归档里是**昨日**的记录，ledger 里是**今日**的记录（两天的账不混）
    arc = json.loads((tmp_path / "ledger_archive.json").read_text(encoding="utf-8"))
    assert sorted(r["note"] for r in arc["days"][YESTERDAY]["records"]) == ["昨日A", "昨日B"]
    led = json.loads(p.read_text(encoding="utf-8"))
    assert led["date"] == pet_book._today()
    assert sorted(r["note"] for r in led["records"]) == ["恢复后的账", "读失败期间的账"]
    assert all(r["date"] == pet_book._today() for r in led["records"])
    # 重启后口径不变
    b2 = pet_book.Book(str(tmp_path))
    assert abs(b2.today_usage() - 6.0) < 1e-9
    assert abs(b2.total_amount() - 25.98) < 1e-9
    assert b2._date_inferred is False


def test_without_the_inferred_flag_yesterday_lands_in_today(tmp_path):
    """反例（能真失败）：把"日界是推断的"这个标志摘掉（= 旧实现没有它）后，同一场景
    必然把昨日算进今日、昨日不归档——证明主用例的断言真的能区分两种实现。"""
    p = tmp_path / "ledger.json"
    text = _write_gbk_ledger(p, _yesterday_ledger())
    b = pet_book.Book(str(tmp_path))
    b.add_manual(5.0, "读失败期间的账")
    b._date_inferred = False                  # ← 旧实现没有这个标志（等价于恒为假）
    p.write_bytes(text.encode("utf-8"))
    b.add_manual(1.0, "恢复后的账")
    assert abs(b.today_usage() - 25.98) < 1e-9, "没有标志居然也修好了？那主用例失去意义"
    assert b.daily_totals(7)[-2][1] == 0.0, "昨日被凭空归档了？"
    assert b._ledger["date"] == pet_book._today()


def test_today_disk_date_is_merged_not_archived(tmp_path):
    """正例：磁盘日界就是今天 → 照旧合并、不产生任何归档（别把正常路径也改了）。"""
    p = tmp_path / "ledger.json"
    text = _write_gbk_ledger(p, {
        "date": pet_book._today(),
        "last_balance": 50.0,
        "records": [_rec(3.0, pet_book._today(), "今日已有", time.time() - 60)],
        "alerted_budget": "",
        "alerted_balance": "",
    })
    b = pet_book.Book(str(tmp_path))
    assert b._read_failed is True and b._date_inferred is True
    b.add_manual(2.0, "读失败期间的账")
    p.write_bytes(text.encode("utf-8"))
    b.add_manual(1.0, "恢复后的账")
    assert abs(b.today_usage() - 6.0) < 1e-9, "今日三笔应全在今日：%r" % (b.today_usage(),)
    assert b.last_balance == 50.0
    arc = json.loads((tmp_path / "ledger_archive.json").read_text(encoding="utf-8"))
    assert arc.get("days") == {}, "日界相同却凭空归档了：%r" % (arc,)


def test_missing_date_field_still_inferred(tmp_path):
    """边界：磁盘上真的没有 date 字段 → 采不到，保持推断值（不炸、不误归档）。"""
    p = tmp_path / "ledger.json"
    # 注：GBK 与 UTF-8 只有对**非 ASCII 字符**才给出不同字节——这里放一个没用到的
    # 非 ASCII 字段，保证这次读真的是"解码失败"（纯 ASCII 内容两种编码同字节，读得到）。
    text = _write_gbk_ledger(p, {"last_balance": 7.0, "records": [],
                                 "alerted_budget": "", "alerted_balance": "",
                                 "备注": "占位"})
    b = pet_book.Book(str(tmp_path))
    assert b._date_inferred is True
    b.add_manual(1.0, "读失败期间的账")
    p.write_bytes(text.encode("utf-8"))
    b.add_manual(1.0, "恢复后的账")
    assert b._date_inferred is False
    assert b._ledger["date"] == pet_book._today()
    assert abs(b.today_usage() - 2.0) < 1e-9
    assert b.last_balance == 7.0
