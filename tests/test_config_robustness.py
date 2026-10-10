# -*- coding: utf-8 -*-
"""配置鲁棒性：任何键被写成垃圾值，加载与启动都不得崩（用户手改 config.json / 旧版本残留）。"""
import json
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import 桌宠 as main  # noqa: E402

POISON_NUM = ["abc", "", None, [], {}, -1, 1e12, "12abc", float("nan")]
POISON_BOOL = ["abc", None, [], {}, 2, "true"]
POISON_STR = [None, [], {}, 123, True]


@pytest.fixture
def app(tmp_path, monkeypatch):
    """隔离数据目录并对**全局状态做快照/还原**。

    v2.1.4 修复（测试顺序依赖）：本文件会反复 load_config / 构造 PetWindow，
    而它们会改写进程级全局（pet_log 的数据目录、脱敏 key 缓存、FRAME_MAX）——
    此前不还原，导致后面跑的 test_memory_redact 里"非 sk- 形式 key 也应脱敏"失败。
    """
    import pet_log
    from PySide6.QtWidgets import QApplication
    monkeypatch.setattr(main, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(main, "USAGE_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setattr(main, "MEMORY_PATH", str(tmp_path / "memory.json"))
    _old_dir = getattr(pet_log, "_data_dir", None)  # 真名是 _data_dir（此前写成 _DATA_DIR → 还原永不执行）
    _old_key = getattr(pet_log, "_redact_key", None)
    _old_frame_max = getattr(__import__("pet_resources"), "FRAME_MAX", None)
    pet_log.set_data_dir(str(tmp_path))
    inst = QApplication.instance() or QApplication([])
    yield inst
    # 还原全局（保证测试顺序无关）；None 也是合法"未设置"，所以要无条件还原
    pet_log.set_data_dir(_old_dir)
    main.set_redact_key(_old_key or "")  # 内部会同步 pet_log._redact_key（无需再单独还原）
    if _old_frame_max is not None:
        __import__("pet_resources").FRAME_MAX = _old_frame_max


def _write(cfg):
    with open(main.CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False)


def _type_ok(default, value):
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, int):
        return isinstance(value, int) and not isinstance(value, bool)
    if isinstance(default, float):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if isinstance(default, str):
        return isinstance(value, str)
    if isinstance(default, list):
        return isinstance(value, list)
    if isinstance(default, dict):
        return isinstance(value, dict)
    return True


def test_load_config_survives_every_poisoned_key(app):
    """逐键灌坏值：load_config 不许抛异常，且回来的值类型必须可用。"""
    bad = []
    for key, default in main.DEFAULT_CONFIG.items():
        if isinstance(default, bool):
            poisons = POISON_BOOL
        elif isinstance(default, (int, float)):
            poisons = POISON_NUM
        elif isinstance(default, str):
            poisons = POISON_STR
        else:
            continue
        for p in poisons:
            _write({key: p})
            try:
                cfg = main.load_config()
            except Exception as e:  # noqa: BLE001
                bad.append("%s=%r 加载抛异常 %r" % (key, p, e))
                continue
            v = cfg.get(key, default)
            if not _type_ok(default, v):
                bad.append("%s=%r 归一化后类型不对：%r" % (key, p, v))
    assert not bad, "配置坏值未兜住：\n" + "\n".join(bad[:20])


def test_null_bool_keys_fall_back_to_default(app):
    """L7（v2.4）：键值是 JSON null 时必须走**默认值**。

    此前 _to_bool(None) 落到 bool(None)=False——"默认开"的 ai_rag_enabled /
    ai_tools_enabled / ai_tools_confirm（以及 always_on_top / sound）被静默关掉，
    界面上看不出任何变化，用户只会觉得"功能怎么没了"。
    """
    bool_keys = {k: d for k, d in main.DEFAULT_CONFIG.items() if isinstance(d, bool)}
    on_defaults = sorted(k for k, d in bool_keys.items() if d)
    off_defaults = sorted(k for k, d in bool_keys.items() if not d)
    assert on_defaults and off_defaults, "布尔键的默认值结构变了，用例前提不成立"

    _write({k: None for k in bool_keys})
    cfg = main.load_config()
    for k in on_defaults:
        assert cfg[k] is True, "%s=null 被静默关掉了（应走默认值 True）" % k
    for k in off_defaults:
        assert cfg[k] is False, "%s=null 应保持默认 False" % k

    # 正例对照：显式 false / true 必须照样生效（修复不能把"用户主动设置"一起吃掉）
    _write({k: False for k in bool_keys})
    cfg_off = main.load_config()
    for k in on_defaults:
        assert cfg_off[k] is False, "%s 显式关不掉了" % k
    _write({k: True for k in bool_keys})
    cfg_on = main.load_config()
    for k in off_defaults:
        assert cfg_on[k] is True, "%s 显式开不掉了" % k


def test_window_boots_with_fully_poisoned_config(app):
    """所有键同时灌坏值：主窗口必须能起来（这是最狠的一发）。"""
    cfg = {}
    for key, default in main.DEFAULT_CONFIG.items():
        if isinstance(default, bool):
            cfg[key] = "yes-please"
        elif isinstance(default, (int, float)):
            cfg[key] = "not-a-number"
        elif isinstance(default, str):
            cfg[key] = 12345
        elif isinstance(default, list):
            cfg[key] = "broken"
        elif isinstance(default, dict):
            cfg[key] = "broken"
    _write(cfg)
    win = None
    try:
        win = main.PetWindow()
        assert win.form in win.sprites
    finally:
        if win is not None:
            # L4（v2.4.1）：统一收尾——先停掉全部 QTimer 再 hide/close/deleteLater
            from helpers_roles import active_timer_count, shutdown_pet
            shutdown_pet(win)
            assert active_timer_count(win) == 0, \
                "拆完还有 %d 个活跃定时器" % active_timer_count(win)