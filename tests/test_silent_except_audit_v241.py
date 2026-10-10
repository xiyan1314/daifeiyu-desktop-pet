# -*- coding: utf-8 -*-
"""v2.4.1（B1）静默 except 审计脚本的 A 档收紧回归。

背景：审计脚本把 `except: pass` 分成 A（数据丢失/用户可见错误被吞）/ B / C / OK 四档，
供人工过一遍。收紧前 A=19，其中约半数是**误报**（同一 try 的多 handler 重复计数、
重试循环里"先存错误、循环外统一上报"、防御性读取加常量兜底、handler 先清理再 return 错误）。
本文件把四类收紧判据与"真吞掉仍然要报"的正例都钉死——判据放松（或退回旧行为）立刻变红。
"""
import importlib.util
import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIT_PATH = os.path.join(HERE, "_dev", "audit_silent_except.py")


def _load_audit():
    """按路径加载 _dev 下的审计脚本（它不是包内模块）。"""
    spec = importlib.util.spec_from_file_location("audit_silent_except_v241", AUDIT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


audit = _load_audit()


def _scan_source(tmp_path, src):
    """把源码写成一个"生产路径"模块并扫描，返回 A 档 findings。"""
    d = tmp_path / "proj"
    d.mkdir(exist_ok=True)
    (d / "synthetic.py").write_text(src, encoding="utf-8")
    findings = [f for f in audit.scan(str(d)) if f["file"].endswith("synthetic.py")]
    return [f for f in findings if f["tier"] == "A"], findings


def test_genuine_swallow_is_still_tier_a(tmp_path):
    """正例：真把写盘失败吞掉（handler 只有 pass）必须还是 A——判据不许被放松成恒 B。"""
    a, _ = _scan_source(tmp_path, """
import os


def save_thing(path):
    try:
        os.replace("a.tmp", path)
    except Exception:
        pass
""")
    assert len(a) == 1, "真吞掉的写盘失败没被报成 A：%r" % (a,)
    assert "A1" in a[0]["reason"], a[0]["reason"]


def test_same_try_multiple_handlers_counted_once(tmp_path):
    """收紧 ①：同一 try 的多个 handler 只能算一条 A（同一次写盘不重复计数）。"""
    a, _ = _scan_source(tmp_path, """
import os


def save_thing(path):
    try:
        os.replace("a.tmp", path)
    except PermissionError:
        pass
    except OSError:
        pass
    except Exception:
        pass
""")
    assert len(a) == 1, "同一 try 被重复计数：%r" % ([f["line"] for f in a],)


def test_retry_loop_that_reports_afterwards_is_not_a(tmp_path):
    """收紧 ②：重试循环里 handler 只存错误、循环外统一 raise/return → 不是吞掉。"""
    a, _ = _scan_source(tmp_path, """
import os
import time


def save_thing(path, attempts=3):
    last = None
    for i in range(attempts):
        try:
            os.replace("a.tmp", path)
            return None
        except PermissionError as e:
            last = e
            if i < attempts - 1:
                time.sleep(0.1)
    raise last
""")
    assert a == [], "重试循环被误报成 A：%r" % ([f["reason"] for f in a],)


def test_returns_error_after_cleanup_is_not_a(tmp_path):
    """收紧 ③：handler 先清理残留、最后 return (None, 错误文案) → 失败已上报调用方。"""
    a, _ = _scan_source(tmp_path, """
import os
import shutil


def copy_thing(src, dst):
    try:
        shutil.copyfile(src, dst)
    except Exception:
        if os.path.exists(dst):
            os.remove(dst)
        return None, "复制文件失败"
""")
    assert a == [], "先清理再 return 错误的写法被误报成 A：%r" % ([f["reason"] for f in a],)
    # 反例对照：把最后的 return 换成 pass（真的吞掉）→ 必须回到 A，证明上一条不是空转
    a2, _ = _scan_source(tmp_path, """
import os
import shutil


def copy_thing2(src, dst):
    try:
        shutil.copyfile(src, dst)
    except Exception:
        if os.path.exists(dst):
            os.remove(dst)
""")
    assert len(a2) == 1, "对照组失效：同样结构改成真吞掉也没报 A"


def test_defensive_read_with_constant_fallback_is_not_a(tmp_path):
    """收紧 ④：用户动作函数里的"取字段 + 常量兜底"不是数据丢失。"""
    a, _ = _scan_source(tmp_path, """
def import_bundle(cfg, manifest):
    try:
        voice = (cfg or {}).get("voice") or {}
        keys = dict(voice)
    except Exception:
        keys = {}
    try:
        ver = int(manifest.get("version") or 1)
    except (TypeError, ValueError):
        ver = 1
    return keys, ver
""")
    assert a == [], "防御性读取被误报成 A：%r" % ([f["reason"] for f in a],)
    # 反例对照：同一个函数里改成"读旧配置失败就清空字段"（真丢数据）→ 必须报 A
    a2, _ = _scan_source(tmp_path, """
import json
import os


def import_bundle2(path, out):
    try:
        with open(path, "r", encoding="utf-8") as f:
            old = json.load(f)
        out["api_key"] = str(old.get("api_key") or "")
    except Exception:
        out["api_key"] = ""
    return out
""")
    assert len(a2) == 1, "对照组失效：读配置文件失败被静默清空也没报 A"


def test_annotated_silent_except_is_still_listed(tmp_path):
    """注释"有意忽略"**不**降级（脚本的既有原则）：注释不是证据，仍要列出来给人看。"""
    a, _ = _scan_source(tmp_path, """
import os


def save_thing(path):
    try:
        os.replace("a.tmp", path)
    except Exception:
        pass  # 有意忽略：清理尽力而为
""")
    assert len(a) == 1 and a[0]["annotated"] is True, a
