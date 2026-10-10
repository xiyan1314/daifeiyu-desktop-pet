# -*- coding: utf-8 -*-
"""v2.4.1（A 区一致性收口）回归：把剩下两处"自建愈合环 / 复制品"钉死在单一实现上。

背景：读侧愈合此前有三套命名——`pet_io.read_json_ex`（真源）、`pet_book._read_json`、
`pet_resources._read_json_ex`——其中后两个各自实现了一遍"读 → 判 → 回写"；`pet_alarm` /
`pet_behaviors` 又各自维护了一个"读 + 清洗 + 手工 backup + _save"的内联环。本轮把它们
收敛到 pet_io.read_json_ex / heal_json。本文件钉住剩下两处：

  1. `pet_resources._read_json_ex` 是薄壳：三元口径与 pet_io **逐位相同**（含 heal=True 时
     的 unreadable——旧实现硬编码 False，一次瞬时读失败会被报成"读到了"）；
  2. `pet_behaviors._load` 走 heal_json：坏条目 → 留 .bak + 一次回写；干净 / 读不到 →
     **一个字节都不写**（不许把完好行为库清空）。

每条断言都配了"能真失败"的对照：源码级判据把旧写法原地拼出来跑一遍，证明它不是空转。
"""
import ast
import builtins
import json
import os

import pet_behaviors
import pet_io
import pet_resources

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(p):
    with open(str(p), "r", encoding="utf-8") as f:
        return json.load(f)


def _count_text_reads(monkeypatch, path):
    """统计对 path 的**文本读** open() 次数（"rb" 不算：备份走二进制复制）。"""
    real_open = builtins.open
    hits = []

    def spy(file, mode="r", *a, **kw):
        if str(file) == str(path) and str(mode) in ("r", "rt"):
            hits.append(str(mode))
        return real_open(file, mode, *a, **kw)

    monkeypatch.setattr(builtins, "open", spy)
    return hits


def _deny_open(monkeypatch, suffix, times=1):
    """让 builtins.open 对某个后缀的文件打不开 times 次（None=一直打不开）。"""
    real_open = builtins.open
    state = {"n": 0}

    def fake_open(file, *a, **kw):
        if str(file).endswith(suffix):
            state["n"] += 1
            if times is None or state["n"] <= times:
                raise PermissionError(13, "Permission denied")
        return real_open(file, *a, **kw)

    monkeypatch.setattr(builtins, "open", fake_open)
    return state


def _src(name):
    import io
    return io.open(os.path.join(HERE, name), encoding="utf-8").read()


def _module_level_names(src):
    """模块级被绑定的名字（赋值 / 注解赋值）——只看代码，不看注释与 docstring。"""
    out = set()
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign):
            out.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out.add(node.target.id)
    return out


def _called_attrs(src):
    """源码里出现过的 "x.attr(...)" 的 attr 名集合（用来判"还调不调某个函数"）。"""
    return {n.func.attr for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}


# ================= pet_resources._read_json_ex = pet_io.read_json_ex 的薄壳 =================

def test_resources_read_helper_matches_pet_io_bit_for_bit(tmp_path, monkeypatch):
    """三元口径必须与 pet_io 完全一致——薄壳的意义就在于"没有第二份口径"。

    反例对照：旧实现（只读探测 + `os.path.exists` 拼 unreadable）在同一组用例下 **③ 会不一致**
    （旧代码 heal=True 时硬编码 unreadable=False）。下面把旧写法原地拼出来验一遍。
    """
    # ① 文件不存在
    p = str(tmp_path / "none.json")
    assert pet_resources._read_json_ex(p, dict) == pet_io.read_json_ex(p, dict) == ({}, False, False)
    assert not os.path.exists(p), "只读路径凭空空造了文件"
    # ② 真损坏（heal=True → 愈合 + .bak）
    with open(p, "w", encoding="utf-8") as f:
        f.write("{broken")
    assert pet_resources._read_json_ex(p, dict) == ({}, True, False)
    assert _read(p) == {} and (tmp_path / "none.json.bak").read_text(encoding="utf-8") == "{broken"
    # ③ 文件在、这次读不到：heal=True 也必须报 unreadable=True（旧实现报 False → 调用方会以为读到了）
    q = tmp_path / "deny.json"
    q.write_bytes(b'{"keep": 1}')
    with monkeypatch.context() as m:
        _deny_open(m, "deny.json", times=None)
        assert pet_resources._read_json_ex(str(q), dict) == ({}, False, True)
        assert pet_io.read_json_ex(str(q), dict) == ({}, False, True)
        assert q.read_bytes() == b'{"keep": 1}', "读不到被当成损坏，回写覆盖了原文件"
        assert not (tmp_path / "deny.json.bak").exists(), "没有回写就不该有 .bak"
        # 对照组：旧 heal=True 分支是 heal_json 的二元口径 + 硬编码 False → 会把"读不到"报成"读到了"
        data, corrupted = pet_io.heal_json(str(q), dict, log=lambda m2: None)
        assert (data, corrupted, False) == ({}, False, False), "对照组失效：heal_json 的二元口径变了"
        assert (data, corrupted, False) != pet_io.read_json_ex(str(q), dict), \
            "新旧口径居然一样，这条用例没有区分力"
    # ④ heal=False：真损坏也不写（RoleLibrary._load 的更强恢复路径用它）
    z = tmp_path / "noheal.json"
    z.write_text("{broken", encoding="utf-8")
    assert pet_resources._read_json_ex(str(z), dict, heal=False) == ({}, True, False)
    assert z.read_text(encoding="utf-8") == "{broken"
    assert not (tmp_path / "noheal.json.bak").exists()


def test_resources_read_helper_is_a_thin_shell_not_a_second_implementation():
    """结构判据：pet_resources 里那份"哨兵 + 两遍读"的复制品必须不再存在。

    这条能真失败：把旧实现贴回去（_PROBE 哨兵 + read_json_or 探测）立刻变红。
    """
    src = _src("pet_resources.py")
    # 用 AST 判"有没有这份实现"，不看注释/docstring——历史说明里提到 _PROBE 是合法的
    assert "_PROBE" not in _module_level_names(src), \
        "pet_resources 又拿回了 _PROBE 哨兵：读侧出现了第二份实现"
    assert "read_json_or" not in _called_attrs(src), "pet_resources 又绕开 read_json_ex 直接读探测了"
    assert "pet_io.read_json_ex(path, factory, heal=heal" in src, "薄壳没有指向 pet_io.read_json_ex"
    # 反例：旧实现必须被同一判据认出来（判据不是恒真）
    old_src = ("_PROBE = object()\n"
               "def f(path):\n"
               "    data, c = pet_io.read_json_or(path, lambda: _PROBE)\n")
    assert "_PROBE" in _module_level_names(old_src)
    assert "read_json_or" in _called_attrs(old_src)


def test_resources_read_helper_reads_corrupt_file_once(tmp_path, monkeypatch):
    """薄壳不引入额外磁盘读：真损坏读一遍（旧实现 heal=False 分支自己再拼一遍逻辑）。"""
    p = str(tmp_path / "once.json")
    with open(p, "w", encoding="utf-8") as f:
        f.write("{broken")
    reads = _count_text_reads(monkeypatch, p)
    assert pet_resources._read_json_ex(p, dict) == ({}, True, False)
    assert len(reads) == 1, "真损坏读了 %d 遍：%r" % (len(reads), reads)


# ================= pet_behaviors._load 走 heal_json =================

def test_behaviors_load_writes_nothing_when_clean(tmp_path):
    """干净文件一个字节都不写（不重写、不动 mtime、不留 .bak）。"""
    idx = tmp_path / "behaviors.json"
    idx.write_text(json.dumps({"behaviors": [
        {"id": "12345678", "name": "ok_act", "steps": [{"act": "play_action", "name": "jump"}]},
    ]}, ensure_ascii=False), encoding="utf-8")
    before = idx.stat().st_mtime_ns
    svc = pet_behaviors.BehaviorService(str(tmp_path), log=lambda m: None)
    assert [b["id"] for b in svc.list()] == ["12345678"]
    assert idx.stat().st_mtime_ns == before, "干净行为库被重写了"
    assert not (tmp_path / "behaviors.json.bak").exists()


def test_behaviors_load_heals_dirty_once_with_single_bak(tmp_path):
    """坏条目 → 清洗回写**一次**，且只有一份 .bak（自建环手工 backup + _save 是两次操作）。"""
    idx = tmp_path / "behaviors.json"
    idx.write_text(json.dumps({"behaviors": [
        {"id": "12345678", "name": "keep_me", "steps": [{"act": "jump"}]},
        {"id": "87654321", "name": "drop_me", "steps": [{"act": "fly"}]},
        "不是对象",
    ]}, ensure_ascii=False), encoding="utf-8")
    logs = []
    svc = pet_behaviors.BehaviorService(str(tmp_path), log=logs.append)
    assert [b["id"] for b in svc.list()] == ["12345678"]
    on_disk = _read(idx)
    assert [b["id"] for b in on_disk["behaviors"]] == ["12345678"]
    assert any("fly" in m for m in logs) and any("不是对象" in m for m in logs)
    baks = [n for n in os.listdir(str(tmp_path)) if n.startswith("behaviors.json.bak")]
    assert baks == ["behaviors.json.bak"], "愈合备份不是单份：%r" % (baks,)
    assert json.loads((tmp_path / "behaviors.json.bak").read_text(encoding="utf-8"))
    # 第二次加载：零报错、零写入（幂等）
    logs2 = []
    before = idx.stat().st_mtime_ns
    pet_behaviors.BehaviorService(str(tmp_path), log=logs2.append)
    assert logs2 == [] and idx.stat().st_mtime_ns == before


def test_behaviors_load_never_clobbers_when_unreadable(tmp_path, monkeypatch):
    """文件在、这次读不到 → **不重建、不回写**（一次瞬时共享冲突不许清空行为库）。"""
    idx = tmp_path / "behaviors.json"
    raw = json.dumps({"behaviors": [
        {"id": "12345678", "name": "keep_me", "steps": [{"act": "play_action", "name": "jump"}]},
    ]}, ensure_ascii=False).encode("utf-8")
    idx.write_bytes(raw)
    with monkeypatch.context() as m:
        _deny_open(m, "behaviors.json", times=None)
        svc = pet_behaviors.BehaviorService(str(tmp_path), log=lambda m2: None)
        assert svc.list() == [], "读不到时内存态应是空（宁可不显示，也不假装有）"
        assert idx.read_bytes() == raw, "读不到被当成损坏，回写把行为库清空了"
        assert not (tmp_path / "behaviors.json.bak").exists()


def test_behaviors_load_is_a_heal_json_caller_not_a_private_ring():
    """结构判据：自建"读 + backup + _save"环必须不再存在（旧写法能真让它变红）。"""
    src = _src("pet_behaviors.py")
    assert "pet_io.heal_json(self._index" in src, "_load 没走 pet_io.heal_json"
    assert "pet_io.read_json_or(self._index" not in src, "自建读环又回来了"
    assert "pet_io.backup_before_heal(self._index" not in src, "手工备份又回来了（heal_json 内部已留 .bak）"
    # 反例：旧环的特征串在同一判据下必须被认出来
    old_snippet = "pet_io.backup_before_heal(self._index, self._log)"
    assert "pet_io.backup_before_heal(self._index" in old_snippet
