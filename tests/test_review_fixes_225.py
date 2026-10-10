# -*- coding: utf-8 -*-
"""v2.2.5 回归：三轮审查报告命中问题的"护栏化"测试（每条对应一处真实修复）。

覆盖：
  1) pet_balance 缺 import pet_log → 开余额监控 NameError
  2) 气泡样式对话框不回填字号/圆角 → 点保存把用户设置重置成 8pt/直角
  3) 台词编辑不回填"喂食对象" → 保存把 food 改成下拉默认值
  4) lines.json 字段类型异常（order 非数值）→ 启动即崩
  5) 记账金额 NaN/Inf 绕过校验
  6) 角色删除路径未净化（可越出数据目录）
  7) 配置归一化：一个坏值连带重置另外两个合法值
  8) 日志重入标志应为线程局部（跨线程误判会丢日志）
"""
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pet_balance  # noqa: E402
import pet_book  # noqa: E402
import pet_config  # noqa: E402
import pet_lines  # noqa: E402
import pet_log  # noqa: E402
import pet_resources  # noqa: E402


def test_balance_module_has_pet_log():
    """① pet_balance.start() 用 pet_log.guard_slot 包轮询槽——模块必须 import pet_log。"""
    assert hasattr(pet_balance, "pet_log"), "pet_balance 未 import pet_log（开监控会 NameError）"
    assert callable(pet_balance.pet_log.guard_slot)


def test_dialog_p0_backfills_are_present():
    """②③ 两个 P0 的"回填"代码必须还在（否则打开对话框点保存会静默改写用户设置）。

    源码级护栏：这两处是"少一行就静默丢数据"的类型，构造期回填无法用纯单元测试低成本覆盖
    （需要真窗口 + QDialog），因此锁住关键语句的存在。
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "pet_dialogs.py"), encoding="utf-8").read()
    # 必须匹配"构造期那一整行"——裸 setValue( 在 _reset_default() 里也有（默认 10/16），
    # 只查裸子串会恒真（质量审查 D1 实测：删掉构造期回填断言仍通过）。
    assert 'self._font_spin.setValue(max(8, min(18, int(self._style.get("font_size") or 10))))' in src, \
        "气泡样式：字号未按当前设置回填（点保存会把用户字号重置为 8）"
    assert 'self._radius_spin.setValue(max(0, min(30, int(_r0 if _r0 is not None else 16))))' in src, \
        "气泡样式：圆角未按当前设置回填（点保存会把圆角重置为 0）"
    assert 'self._food.findData(ln.get("food")' in src, \
        "台词编辑：喂食对象未回填（保存会把 food 改成下拉默认值）"


def test_book_rejects_nan_and_inf():
    """⑤ NaN/Inf 的 <= 0 都是 False，此前会绕过校验污染统计。"""
    base = {"date": "2026-01-01", "ts": time.time(), "kind": "api", "note": ""}
    for bad in (float("nan"), float("inf"), float("-inf")):
        r = dict(base, amount=bad)
        assert pet_book._normalize_record(r) is None, "坏金额未被拒绝：%r" % (bad,)
    assert pet_book._normalize_record(dict(base, amount=1.5)) is not None


def test_lines_bad_order_does_not_crash(tmp_path):
    """④ 字段类型异常不再让 LineService 构造抛异常（此前程序启动即失败）。"""
    p = tmp_path / "lines.json"
    p.write_text(json.dumps({
        "version": 1,
        "lines": [{"id": "a1", "text": "手改坏值", "category": "idle", "order": "abc"},
                  {"id": "a2", "text": "正常", "category": "idle", "order": 3}],
        "dialogues": []}, ensure_ascii=False), encoding="utf-8")
    svc = pet_lines.LineService(str(tmp_path), lambda m: None)  # 不得抛异常
    items = svc.lines("idle")
    # 真正的回归点就是"构造不抛异常且条目仍在"（isinstance(int) 恒真，已删——质量审查 D2）
    assert any(x["id"] == "a1" for x in items), "坏 order 的条目不该被整库丢弃"


def test_role_delete_rejects_traversal(tmp_path):
    """⑥ id/文件含分隔符或越界路径时，删除必须拒绝且不动数据目录外的文件。"""
    lib = pet_resources.RoleLibrary(str(tmp_path))
    outside = tmp_path.parent / "victim.png"
    outside.write_bytes(b"x")
    lib._data["roles"] = [{"id": "..", "name": "bad",
                           "file": "../../victim.png", "file_front": "",
                           "file_full": "", "file_full_front": ""}]
    ok, err = lib.delete("..")
    assert ok is False and err, "越界 id 的删除必须被拒绝"
    assert outside.exists(), "数据目录外的文件被删了（路径穿越）"


def test_role_delete_inside_dir_guard(tmp_path):
    """⑥b 直接覆盖 _inside_dir 防线（质量审查 D3）：id 合法但 file 越界时，
    数据目录外的文件必须保留（此前这条分支零覆盖——删掉 _inside_dir 测试也照样绿）。"""
    lib = pet_resources.RoleLibrary(str(tmp_path))
    outside = tmp_path.parent / "victim2.png"
    outside.write_bytes(b"y")
    lib._data["roles"] = [{"id": "okid", "name": "ok",
                           "file": "../../victim2.png", "file_front": "",
                           "file_full": "", "file_full_front": ""}]
    lib.delete("okid")                     # id 合法 → 走到 _inside_dir 分支
    assert outside.exists(), "数据目录外的文件被删了（_inside_dir 防线失效）"


def test_book_save_failure_is_logged(tmp_path):
    """④b 记账落盘失败必须留痕（质量审查 A1/D4）：此前调用了不存在的 self._log，
    异常被吞 → "留痕"是死代码，7 条护栏又恰好没覆盖它。"""
    pet_log.set_data_dir(str(tmp_path))
    book = pet_book.Book(str(tmp_path))
    real = pet_book._write_json
    pet_book._write_json = lambda path, data: "disk full"
    try:
        err = book._save_all()
    finally:
        pet_book._write_json = real
    assert err, "写盘失败应返回错误串"
    txt = (tmp_path / "error.log").read_text(encoding="utf-8")
    assert "ledger 落盘失败" in txt, "落盘失败没有留痕：%r" % txt[-200:]


def test_config_bad_ai_key_keeps_others(tmp_path):
    """⑦ 一个坏 AI 键不得连带重置另外两个合法值。"""
    cfg = {"chat_memory_rounds": 7, "ai_max_tokens": "oops", "ai_reply_len": 40}
    pet_config.normalize_cfg(cfg, {}, frozenset())
    assert cfg["chat_memory_rounds"] == 7, "坏值牵连重置了 chat_memory_rounds"
    assert cfg["ai_reply_len"] == 40, "坏值牵连重置了 ai_reply_len"
    assert cfg["ai_max_tokens"] == 60, "坏值未回退默认"


def test_log_flag_is_thread_local(tmp_path):
    """⑧ 两个线程同时报错时都必须落盘（此前进程级标志会把后到的线程当重入→丢日志）。"""
    pet_log.set_data_dir(str(tmp_path))
    hold = threading.Event()
    release = threading.Event()

    def worker():
        pet_log._tls.logging = True   # 该线程"占住"重入标志（模拟正在写日志）
        hold.set()
        release.wait(3)
        pet_log._tls.logging = False

    t = threading.Thread(target=worker)
    t.start()
    assert hold.wait(3)
    try:
        pet_log.log_error("主线程的日志必须落盘")
    finally:
        release.set()
        t.join()
    txt = (tmp_path / "error.log").read_text(encoding="utf-8")
    assert "主线程的日志必须落盘" in txt, "别的线程占标志把本线程日志吞了（标志不是线程局部）"