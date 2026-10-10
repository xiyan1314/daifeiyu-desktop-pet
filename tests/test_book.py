# -*- coding: utf-8 -*-
"""pet_book.Book 纯逻辑回归（余额差/跨天归档/预警口径/防误记/迁移/损坏重建）。"""
import json
import os

import pytest

import pet_book


@pytest.fixture()
def tmpdir_book(tmp_path):
    return pet_book.Book(str(tmp_path))


def test_manual_record(tmpdir_book):
    tmpdir_book.add_manual(12.5, "午饭")
    assert abs(tmpdir_book.today_usage() - 12.5) < 1e-9
    assert tmpdir_book.total_count() == 1


def test_balance_diff_records_api(tmpdir_book):
    tmpdir_book.observe_balance(100.0)
    tmpdir_book.observe_balance(97.3)
    assert abs(tmpdir_book.today_usage() - 2.7) < 1e-9
    recs = tmpdir_book.all_records()
    assert len(recs) == 1 and recs[0]["kind"] == "api"


def test_big_drop_not_recorded(tmpdir_book):
    """单次降幅 >max(5, last*0.2) 视为平台调整：不记账、返回提醒。"""
    tmpdir_book.observe_balance(100.0)
    note = tmpdir_book.observe_balance(60.0)  # 降 40 > 20
    assert note is not None
    assert abs(tmpdir_book.today_usage() - 0.0) < 1e-9  # 未记消费
    assert tmpdir_book.last_balance == 60.0  # 基准已重置


def test_budget_only_counts_api(tmpdir_book):
    tmpdir_book.add_manual(50.0, "手动")
    tmpdir_book.observe_balance(100.0)
    tmpdir_book.observe_balance(99.0)  # api 1.0
    alerts = tmpdir_book.check_alerts(99.0, 0.5, 0.0)  # api 1.0 超预算 0.5
    assert len(alerts) == 1 and "1.00" in alerts[0]  # 只算 api，不算手动 50


def test_alert_once_per_day(tmpdir_book):
    tmpdir_book.observe_balance(100.0)
    tmpdir_book.observe_balance(99.0)
    a1 = tmpdir_book.check_alerts(99.0, 0.5, 0.0)
    a2 = tmpdir_book.check_alerts(99.0, 0.5, 0.0)
    assert len(a1) == 1 and len(a2) == 0


def test_cross_day_archive(tmpdir_book, tmp_path):
    tmpdir_book.add_manual(5.0)
    led = json.loads((tmp_path / "ledger.json").read_text(encoding="utf-8"))
    led["date"] = pet_book._date_shift(pet_book._today(), -1)
    (tmp_path / "ledger.json").write_text(json.dumps(led), encoding="utf-8")
    b2 = pet_book.Book(str(tmp_path))
    assert b2.today_usage() == 0.0
    totals = b2.daily_totals(7)
    assert abs(totals[-2][1] - 5.0) < 1e-9  # 昨日归档 5 元


def test_csv_bom(tmpdir_book, tmp_path):
    tmpdir_book.add_manual(3.5, "午饭")
    p = str(tmp_path / "out.csv")
    ok, err = tmpdir_book.export_csv(p)
    assert ok and err == ""
    raw = open(p, "rb").read()
    assert raw.startswith(b"\xef\xbb\xbf")  # BOM


def test_csv_export_goes_through_pet_io(tmpdir_book, tmp_path, monkeypatch):
    """v2.4.1（A 区）：export_csv 走 pet_io.atomic_write_bytes（最后一个自建写盘点）。

    变异验证：把 pet_io.atomic_write_bytes 换成探针——旧实现自建 "临时文件 + os.replace"，
    根本不经过它，seen 会是空的（这条用例就是靠这一点能真失败）。
    """
    import pet_io
    tmpdir_book.add_manual(3.5, "午饭")
    seen = []
    real = pet_io.atomic_write_bytes

    def spy(path, data, **kw):
        seen.append((str(path), data))
        return real(path, data, **kw)

    monkeypatch.setattr(pet_io, "atomic_write_bytes", spy)
    p = str(tmp_path / "out.csv")
    ok, err = tmpdir_book.export_csv(p)
    assert ok and err == "", err
    assert len(seen) == 1 and seen[0][0] == p, "导出没走 pet_io：%r" % (seen,)
    assert seen[0][1].startswith(b"\xef\xbb\xbf"), "探针拿到的不是 CSV 正文（BOM 丢失）"
    assert open(p, "rb").read() == seen[0][1], "落盘内容与交给 pet_io 的不一致"
    # 反例：写盘失败必须如实回报（不抛、不假装成功）——父路径是普通文件，建目录必失败
    blocker = tmp_path / "afile"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(pet_io, "atomic_write_bytes", real)
    ok2, err2 = tmpdir_book.export_csv(str(blocker / "sub" / "x.csv"))
    assert ok2 is False and err2, err2
    # 失败不得留下临时文件（pet_io 自己清；导出目录里也不许有散落的 .tmp）
    assert not [f for f in os.listdir(str(tmp_path)) if f.endswith(".tmp")]


def test_corrupt_rebuild(tmp_path):
    (tmp_path / "ledger.json").write_text("{ not json", encoding="utf-8")
    b = pet_book.Book(str(tmp_path))
    assert b.today_usage() == 0.0  # 不崩、按空重建


def test_migrate_usage_json(tmp_path):
    (tmp_path / "usage.json").write_text(
        json.dumps({"date": pet_book._today(), "usage": 7.5, "last_balance": 10.0}),
        encoding="utf-8",
    )
    b = pet_book.Book(str(tmp_path))
    assert abs(b.today_usage() - 7.5) < 1e-9
    assert b.last_balance == 10.0
    assert not (tmp_path / "usage.json").exists()  # 迁移后改名

