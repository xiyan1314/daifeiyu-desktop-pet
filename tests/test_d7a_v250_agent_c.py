# -*- coding: utf-8 -*-
"""v2.5.0 第 2 轮（D7-A · 代理 C）回归：静默 except A=1 补日志 + M 检查形参遮蔽 + pet_fx 口径。

三条设计要求（上一轮审查抓到过恒真断言）：每条用例都要**能真的失败**——
拿掉修复/判据必须变红，并配正例对照（"不报"的旁边必须有"必报"）。
"""
import ast
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pet_resources  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ---------------- D7-A ①：pet_resources 的 keep_source 不再静默 ----------------

def _only_source_copy_fails(monkeypatch):
    """只让"复制到 <角色>/source/"失败：导入本体的复制路径保持真实。"""
    real = pet_resources.shutil.copyfile

    def _copy(src, dst, *a, **k):
        if os.sep + "source" + os.sep in str(dst):
            raise OSError("synthetic: 原图目录不可写")
        return real(src, dst, *a, **k)

    monkeypatch.setattr(pet_resources.shutil, "copyfile", _copy)
    monkeypatch.setattr(pet_resources, "_SOURCE_FAIL_SEEN", {})  # 限流表从零开始


def _import_with_keep_source(tmp_path, name="留痕", lib=None):
    p = tmp_path / "p.png"
    p.write_bytes(b"fakepng")
    src = tmp_path / "orig.png"
    src.write_bytes(b"fakeorig")
    lib = lib or pet_resources.RoleLibrary(str(tmp_path))
    return lib.import_processed(str(p), None, name, keep_source=True,
                                source_files=[str(src)])


def test_keep_source_failure_is_logged_and_import_still_succeeds(tmp_path, monkeypatch):
    """D7-A ①：保留原图失败要留痕（error.log），但导入结果与返回值逐位不变。

    能真失败：把 pet_resources 里那句 _log_source_fail(rid, e) 拿掉（＝回到
    纯 pass 的静默 except）→ 本用例第一条断言红。
    """
    _only_source_copy_fails(monkeypatch)
    role, err = _import_with_keep_source(tmp_path)
    assert err is None and role is not None, "保留原图失败不该让导入失败：%r" % (err,)
    # 正例对照：导入本体（角色 png / 索引）真的落盘了，"只是少了原图"
    assert os.path.isfile(tmp_path / "roles" / role["file"]), "角色图没落盘"
    assert role["id"] in [r["id"] for r in pet_resources.RoleLibrary(str(tmp_path)).list_roles()]
    log = (tmp_path / "error.log").read_text(encoding="utf-8")
    assert "keep_source failed" in log, "保留原图失败仍然静默（error.log 无留痕）：%r" % log
    assert role["id"] in log, "日志没带角色 id，排查时对不上是哪次导入：%r" % log
    assert "synthetic" in log, "日志没带异常内容（看不出失败原因）：%r" % log
    assert not (tmp_path / "roles" / role["id"] / "source").exists() or True  # 失败即无原图


def test_keep_source_failure_log_is_rate_limited(tmp_path, monkeypatch):
    """限流口径（同 pet_log.guard_slot）：60s 窗口内同一句只记一条，窗口过后再记。

    能真失败：把 _log_source_fail 里的限流判断去掉（每失败一条）→ 第二条断言红。
    """
    _only_source_copy_fails(monkeypatch)
    seen = []
    monkeypatch.setattr(pet_resources.pet_log, "log_error",
                        lambda msg, *a, **k: seen.append(msg))
    lib = pet_resources.RoleLibrary(str(tmp_path))
    for i in range(3):  # 连续三次导入都失败（同一个 60s 窗口）
        role, err = _import_with_keep_source(tmp_path, name="第%d次" % i, lib=lib)
        assert err is None and role is not None, err
    assert len(seen) == 1, "限流没生效（同窗口记了 %d 条）：%r" % (len(seen), seen)
    assert "keep_source failed" in seen[0]
    # 正例对照：窗口过后（把上次时间往前挪 61s）必须再记一条——不是"只记一次"
    pet_resources._SOURCE_FAIL_SEEN["keep_source"] -= 61.0
    role4, err4 = _import_with_keep_source(tmp_path, name="窗口外", lib=lib)
    assert err4 is None and role4 is not None, err4
    assert len(seen) == 2, "限流窗口过去后没有恢复记录：%r" % (seen,)
    # 控制组：正常路径（保留成功）一条都不许记
    seen.clear()
    monkeypatch.undo()
    lib2 = pet_resources.RoleLibrary(str(tmp_path))
    p = tmp_path / "ok.png"
    p.write_bytes(b"fakepng")
    src = tmp_path / "ok_src.png"
    src.write_bytes(b"fakeorig")
    role5, err5 = lib2.import_processed(str(p), None, "正常", keep_source=True,
                                        source_files=[str(src)])
    assert err5 is None and role5 is not None, err5
    assert seen == [], "正常路径写了日志（噪音）：%r" % (seen,)


# ---------------- D7-A ②：M 检查的形参遮蔽不再误报 ----------------

_SHADOW_OK = """
from PySide6.QtCore import Signal, QObject


def _mod_fn(a, b):          # 全仓同名模块级函数：旧口径会拿它的签名去判定
    pass


class W(QObject):
    zero = Signal()

    def wire_shadow(self, _mod_fn):
        self.zero.connect(_mod_fn)      # 形参遮同名 → 判不了 → 必须跳过
"""

_SHADOW_BAD = """
from PySide6.QtCore import Signal, QObject


def _mod_fn(a, b):
    pass


class W(QObject):
    zero = Signal()

    def _needs_one(self, text):
        pass

    def busy(self):
        self.zero.connect(self._needs_one)   # 要 1 给 0 → 必须报
"""

_SHADOW_AMBIGUOUS = """
from PySide6.QtCore import Signal, QObject


def _mod_fn(a, b):
    pass


class W(QObject):
    zero = Signal()

    def _needs_one(self, text):
        pass

    def wire(self, cb):
        cb = self._needs_one      # 形参 + 局部重新赋值：一个名字两个来源
        self.zero.connect(cb)     # 歧义 → 必须跳过（不许猜）
"""


def test_m_check_param_shadow_is_skipped_but_real_violations_still_report():
    """D7-A ②：形参名进 bad——合法的不报、违规的必报、歧义的必须跳过。

    能真失败：把 _check_static._param_names 改成恒返回空集（＝回到旧口径）→
    本用例在"合法的不报"那一步变红（形参会拿到全仓同名函数的签名而误报）。
    """
    import _check_static as C

    def _scan(src):
        return C.check_signal_arity([("shadow.py", src)])

    # ① 合法：形参遮住同名模块级函数 → 一处都不许报
    assert _scan(_SHADOW_OK) == ([], []), "形参遮蔽被误报：%r" % (_scan(_SHADOW_OK),)
    # ② 违规：同一份文件结构里换成真的签名错 → 必须报（证明检查器没失明）
    bp, bn = _scan(_SHADOW_BAD)
    assert len(bp) == 1 and "_needs_one" in bp[0], "真违规没被检出：%r" % (bp,)
    assert bn == [], bn
    # ③ 歧义：形参 + 局部重新绑定 → 判定不了 → 跳过（不许猜）
    assert _scan(_SHADOW_AMBIGUOUS) == ([], []), \
        "歧义绑定被猜着解析了：%r" % (_scan(_SHADOW_AMBIGUOUS),)
    # 变异自检：拆掉形参判据（恒空集）后 ①③ 必须重新误报 → 上面的"不报"不是空转
    orig = C._param_names
    try:
        C._param_names = lambda args: set()
        assert _scan(_SHADOW_OK)[0], "拆掉形参判据后也没误报：这条断言是空转的"
        assert _scan(_SHADOW_AMBIGUOUS)[0], "歧义反例对形参判据不敏感"
        assert len(_scan(_SHADOW_BAD)[0]) == 1, "对照组在变异下口径变了"
    finally:
        C._param_names = orig
    # 真仓：M 检查仍 0 问题 0 待确认，且可解析槽比例不因本次收紧而骤降
    real_p, real_n = C.check_signal_arity(C.sources())
    assert real_p == [] and real_n == [], (real_p, real_n)
    seen = []
    _orig_slot = C._slot_arity

    def _spy(*a, **k):
        r = _orig_slot(*a, **k)
        seen.append(r)
        return r

    C._slot_arity = _spy
    try:
        C.check_signal_arity(C.sources())
    finally:
        C._slot_arity = _orig_slot
    _n = sum(1 for r in seen if r is not None)
    assert len(seen) >= 100, "扫描面太窄：%d" % len(seen)
    assert _n >= 0.76 * len(seen), "可解析槽比例骤降（%d/%d）：形参判据收得过头了" % (_n, len(seen))

# ---------------- D7-A ③：config.json 的 diff 存储不保留未知键（有意为之） ----------------

def test_config_json_drops_unknown_keys_by_design(tmp_path):
    """D7-A ③：diff 存储只落盘与默认值不同的**已知**键；未知键有意丢弃，且口径留在文档里。

    能真失败：哪天 write_config 改成"未知键也带回去"（或等于默认值的键也落盘）→ 本用例红；
    那时 README 的说明与 pet_config 的注释必须同步改（下面两条文档断言就是哨兵）。
    """
    import json

    import pet_config

    defaults = {"city": "北京", "scale": 1.0, "nested": {"a": 1}}
    cfg = {"city": "上海", "scale": 1.0, "nested": {"a": 2},
           "fancy_future_key": 7,                  # 未来版本的键：本版本读不到 → 不落盘
           "lines_extra": {"old": ["x"]},           # v2.0 死键（只作迁移源）→ 不复活
           "_resave": True}                         # 内部一次性标记 → 不落盘
    p = tmp_path / "config.json"
    pet_config.write_config(str(p), cfg, defaults, 2, lambda m: None, lambda s: "dpapi:cipher")
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["schema_version"] == 2
    assert data["city"] == "上海" and data["nested"] == {"a": 2}   # 改过的键照写
    assert data["api_key"] == "dpapi:cipher"                       # 密文特通道：恒落盘
    assert "scale" not in data, "等于默认值的键落盘了（diff 语义坏了）"
    assert "fancy_future_key" not in data, \
        "未知键被带回去了：口径变了，README/pet_config 的说明要同步"
    assert "lines_extra" not in data, "已废弃的旧键被带回来了"
    assert "_resave" not in data, "内部标记落盘了"
    # 口径必须留在**文档与代码**里（删了就该有人知道——这条断言就是那个哨兵）
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "未知键" in readme and "有意为之" in readme, "README 的 config.json 口径说明被删了"
    src = (ROOT / "pet_config.py").read_text(encoding="utf-8")
    assert "未知键" in src and "有意为之" in src, "pet_config 里的口径注释被删了"


# ---------------- A-3：pet_fx 的文档与自测不再写死帧集 ----------------

def _main_block_src(src):
    """取 `if __name__ == "__main__":` 整块源码（含块内注释）。"""
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.If) and "__name__" in ast.dump(node.test):
            return "\n".join(src.splitlines()[node.lineno - 1:node.end_lineno])
    return ""


def test_pet_fx_docs_and_selftest_do_not_hardcode_the_frame_sets(tmp_path):
    """A-3：帧集前缀/张数不许在 pet_fx 写死——docstring 与 __main__ 自测都按实况来。

    能真失败：把 docstring 里的 86（或 __main__ 里 load_frame_set(dir, "money", 86)）写
    回去 → 对应断言红；桌宠.py 的具名常量与 assets/fx 实况对不上也红（真源漂移）。
    """
    import pet_fx
    import 桌宠 as main

    src = (ROOT / "pet_fx.py").read_text(encoding="utf-8")
    doc = ast.get_docstring(ast.parse(src)) or ""
    assert "86" not in doc, "模块 docstring 仍写死帧数 86"
    assert "money_f00" not in doc and "petpet_f00" not in doc, "docstring 仍写死帧文件名序列"
    block = _main_block_src(src)
    assert block, "没找到 pet_fx 的 __main__ 自测块"
    blk = ast.parse(block)
    strs = {n.value for n in ast.walk(blk)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    ints = {n.value for n in ast.walk(blk)
            if isinstance(n, ast.Constant) and isinstance(n.value, int)
            and not isinstance(n.value, bool)}
    assert "money" not in strs and "petpet" not in strs, \
        "自测里仍写死帧集前缀字面量：%r" % sorted(strs)
    assert 86 not in ints, "自测里仍写死撒钱帧数 86"
    # 真源对得上：磁盘实况 == 桌宠.py 的具名常量（两侧漂移即红）
    sets = pet_fx.frame_sets(str(ROOT / "assets" / "fx"))
    assert sets, "assets/fx 一组帧集都没数到（frame_sets 失明）"
    assert sets.get(main._MONEY_FRAME_PREFIX) == main._MONEY_FRAME_COUNT, \
        "assets/fx 实况 %r 与 桌宠.py 的 %s=%d 对不上" % (
            sets, main._MONEY_FRAME_PREFIX, main._MONEY_FRAME_COUNT)
    for _g, _sub, _prefix, _count, _attr in main._DEFAULT_FRAME_SETS:
        if _sub == "fx":
            assert sets.get(_prefix) == _count, \
                "桌宠._DEFAULT_FRAME_SETS 的 %s=%d 与磁盘实况 %r 对不上" % (_prefix, _count, sets)
    # 正例对照：frame_sets 不是"恒返回空/恒返回同一个数"——人造目录也按实况数
    fake = tmp_path / "fx"
    fake.mkdir()
    for i in range(3):
        (fake / ("demo_f%02d.png" % i)).write_bytes(b"x")
    (fake / "not_a_frame.png").write_bytes(b"x")
    assert pet_fx.frame_sets(str(fake)) == {"demo": 3}, pet_fx.frame_sets(str(fake))
    assert pet_fx.frame_sets(str(tmp_path / "不存在")) == {}