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


# ---------------- v2.4.2（B2）：第二波收紧（④ 纯轮转 / ⑤ 信号 0 探针 / ⑥ 回滚里的回滚） ----------------
# 这一波的目标：把 A=4 里剩下的三条误报摘掉（A → 1）。每条都配**双向**反例：
# 既要证明"该降的降了"，也要证明"真吞掉的照样报 A"——只朝一个方向写的用例是空转的。

def test_pure_rotation_is_not_a(tmp_path):
    """收紧④：把已有文件轮转到**它自己的备份名**（X → X + 后缀）的静默失败不是数据丢失。"""
    a, _ = _scan_source(tmp_path, """
import os


def rotate(path):
    try:
        if os.path.getsize(path) > 512 * 1024:
            os.replace(path, path + ".old")
    except Exception:
        pass
""")
    assert a == [], "日志轮转失败被误报成 A：%r" % ([f["reason"] for f in a],)
    # 反例对照①：**提交式改名**（目的名不是"源名 + 后缀"）失败被吞 → 必须仍是 A
    a2, _ = _scan_source(tmp_path, """
import os


def commit(tmp, final):
    try:
        os.replace(tmp, final)
    except Exception:
        pass
""")
    assert len(a2) == 1 and "A1" in a2[0]["reason"], \
        "对照组失效：提交式改名失败被吞也没报 A：%r" % (a2,)
    # 反例对照②：轮转旁边还有一次真写盘 → 必须仍是 A
    a3, _ = _scan_source(tmp_path, """
import json
import os


def rotate_and_write(path, data):
    try:
        if os.path.getsize(path) > 512 * 1024:
            os.replace(path, path + ".old")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass
""")
    assert len(a3) == 1 and "A1" in a3[0]["reason"], \
        "对照组失效：轮转 + 真写盘被吞也没报 A：%r" % (a3,)


def test_signal0_probe_is_not_a(tmp_path):
    """收紧⑤：`os.kill(pid, 0)` 是存活探针，不是"后端启停被吞"。"""
    a, _ = _scan_source(tmp_path, """
import os


def check_backend_running(pid):
    try:
        os.kill(pid, 0)
    except Exception:
        pass
""")
    assert a == [], "进程存活探针被误报成 A3：%r" % ([f["reason"] for f in a],)
    # 反例对照：真发信号（不是 0）必须仍是 A3
    a2, _ = _scan_source(tmp_path, """
import os


def stop_backend(pid):
    try:
        os.kill(pid, 9)
    except Exception:
        pass
""")
    assert len(a2) == 1 and "A3" in a2[0]["reason"], a2


def test_rollback_inside_reporting_handler_is_not_a(tmp_path):
    """收紧⑥：删残留的回滚清理，嵌在**已经上报错误**的 handler 内部 → 不是"用户不知道"。

    口径要卡准：这条只在"try 体是 `_is_pure_cleanup` 但 `persist` 认不出来"时才起作用
    （receiver 不是文件模块，例如 `role_lib._data["roles"].remove(...)` + `_save()`）——
    那种组合 `cleanup_only`（需要 persist）兜不住，只剩函数名动词触发的 A4 会把回滚报成
    "用户动作失败无提示"。反例用**真·文件模块写**（os.makedirs）来证明独立写盘不放行。
    """
    a, _ = _scan_source(tmp_path, """
def import_bundle(lib, role):
    try:
        lib.commit()
    except Exception as e:
        try:
            lib.roles.remove(role)
            lib._save()
        except Exception:
            pass
        return None, "导入失败：%s" % e
""")
    assert a == [], "已上报错误的 handler 里的回滚清理被误报成 A：%r" % ([f["reason"] for f in a],)
    # 反例对照①：外层**不上报**（handler 只 pass）→ 内层静默必须仍旧被报出来
    a2, _ = _scan_source(tmp_path, """
def import_bundle2(lib, role):
    try:
        lib.commit()
    except Exception:
        try:
            lib.roles.remove(role)
            lib._save()
        except Exception:
            pass
""")
    assert a2, "对照组失效：外层不上报时内层的静默也没报 A"
    # 反例对照②：内层是**独立写盘**（不是回滚清理）→ 即使外层上报也必须留在 A
    a3, _ = _scan_source(tmp_path, """
import os


def import_bundle3(path, keep):
    try:
        os.replace("a.tmp", path)
    except Exception as e:
        try:
            os.makedirs(keep, exist_ok=True)
        except Exception:
            pass
        return None, "导入失败：%s" % e
""")
    assert a3, "对照组失效：外层已上报也不能放过内层的独立写盘（判据收得不够紧）"


def test_bom_file_is_scanned_not_skipped(tmp_path):
    """v2.4.2：带 UTF-8 BOM 的 .py 是**合法 Python**，审计必须扫它（此前整体 SKIP＝整文件盲区）。"""
    d = tmp_path / "proj"
    d.mkdir()
    (d / "bom.py").write_text(
        '\ufeffimport os\n\n\ndef save_thing(path):\n    try:\n'
        '        os.replace("a.tmp", path)\n    except Exception:\n        pass\n',
        encoding="utf-8")
    f = audit.scan(str(d))
    assert not [x for x in f if x["tier"] == "SKIP"], "带 BOM 的文件被整份跳过了：%r" % (f,)
    assert len([x for x in f if x["tier"] == "A"]) == 1, f


def test_unparseable_file_in_tests_is_not_counted_as_production(tmp_path):
    """v2.4.2：解析失败的文件若在 tests/_dev 下，不能被算成"生产路径"（此前 nonprod 恒 False）。"""
    d = tmp_path / "proj" / "tests"
    d.mkdir(parents=True)
    (d / "broken.py").write_text("def f(:\n", encoding="utf-8")
    f = audit.scan(str(tmp_path / "proj"))
    skip = [x for x in f if x["tier"] == "SKIP"]
    assert skip and all(x["nonprod"] for x in skip), skip


def test_v242_tightenings_are_mutation_verified(tmp_path, monkeypatch):
    """变异验证：把 v2.4.2 三条收紧分别关掉，对应合成反例必须**重新**回到 A 档。

    否则"收紧后不再报 A"有可能只是因为反例本身就不成立（空转断言）。
    """
    rotation = """
import os


def rotate(path):
    try:
        if os.path.getsize(path) > 512 * 1024:
            os.replace(path, path + ".old")
    except Exception:
        pass
"""
    probe = """
import os


def check_backend_running(pid):
    try:
        os.kill(pid, 0)
    except Exception:
        pass
"""
    rollback = """
def import_bundle(lib, role):
    try:
        lib.commit()
    except Exception as e:
        try:
            lib.roles.remove(role)
            lib._save()
        except Exception:
            pass
        return None, "导入失败：%s" % e
"""
    for src, attr in ((rotation, "_is_pure_rotation"),
                      (probe, "_is_signal0_probe"),
                      (rollback, "_rollback_in_reporting_handler")):
        with monkeypatch.context() as m:
            m.setattr(audit, attr, lambda *a, **k: False)
            a, _ = _scan_source(tmp_path, src)
            assert a, "关掉 %s 后合成反例没回到 A 档：该收紧没有被反例真正覆盖" % attr
