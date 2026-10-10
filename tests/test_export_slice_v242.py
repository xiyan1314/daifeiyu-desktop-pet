# -*- coding: utf-8 -*-
"""v2.4.2 导出耗时 P2：两段式导出 API（收集 / 分片逐条写）回归。

背景（_dev/probe_export_cost.py 实测，10 个 61KB PNG）：
  export_bundle 合计 ≈130 ms，其中 zipfile 写盘 ≈100 ms（zlib 压缩 + CRC + 读盘），
  收集引用 ≈1 ms、manifest ≈0.02 ms、自校验 ≈0.5 ms。也就是说：**时间全在写盘长循环**，
  而那一段是主线程同步跑的——导出期间窗口一次事件循环都不转（用户看到假死）。
  修法不是"加快压缩"（改压缩级别会改变产出字节，本轮明确不允许），而是把它拆成
  plan_bundle（收集）+ BundleWriter（逐条写）两段，UI 侧按片驱动（桌宠._export_step）。

本模块钉四件事，每条都能真失败：
  1. export_bundle 仍是**薄壳**：收集与写两段都被真的调用（把写盘内联回 export_bundle → 红）；
  2. 分片写与一次性写的产出**逐条目相同**（条目名/顺序/CRC/内容/manifest 全等；
     把分片写改成"少写一条/换顺序"→ 红）；
  3. 分片真的分片（budget_ms 生效，多次 step 才写完；把 budget 忽略 → 红）；
  4. abort 不留半截包（正式输出文件从没被创建；不清理 tmp → 红）。
另有一条端到端：桌宠._export_role 必须把写盘交给分片器驱动（改回同步写 → 红）。
"""
import hashlib
import json
import os
import sys
import zipfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pet_export  # noqa: E402
import pet_resources  # noqa: E402


def _mk_role(tmp_path, role_id="r1", n_frames=6):
    """造一个"有真实体积"的角色（zip 压缩才有活干，分片才测得出差别）。"""
    roles = tmp_path / "roles"
    roles.mkdir(exist_ok=True)
    names = []
    for i in range(n_frames):
        n = "f%02d.png" % i
        # 60KB 伪随机内容：不可压缩（和真实 PNG 一样，deflate 省不下体积）
        blob = hashlib.sha256(b"seed%d" % i).digest() * 2000
        (roles / n).write_bytes(b"\x89PNG\r\n\x1a\n" + blob[:60000])
        names.append(n)
    role = {"id": role_id, "name": "分享角色", "file": names[0], "form": "single",
            "file_full": "", "frames": list(names), "added": "",
            "forms": [{"name": "常态", "file": names[0], "front": names[0],
                       "animations": {"idle": list(names)}}]}
    (tmp_path / "roles.json").write_text(
        json.dumps({"roles": [role], "active": role_id}, ensure_ascii=False), encoding="utf-8")
    return pet_resources.RoleLibrary(str(tmp_path)), {"role": role_id}


def _entry_hashes(zip_path):
    """逐条目指纹：(条目名, 未压长度, CRC, 内容 sha256)——比"文件字节"更本质。"""
    out = {}
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            data = zf.read(info.filename)
            out[info.filename] = (info.file_size, info.CRC,
                                  hashlib.sha256(data).hexdigest())
    return out


# ---------------- 1. 旧签名是薄壳 ----------------

def test_export_bundle_is_a_thin_shell_over_plan_and_writer(tmp_path, monkeypatch):
    """export_bundle 必须真的走 plan_bundle + BundleWriter（不是自己内联写盘）。

    能真失败：把写盘那段内联回 export_bundle（或绕过 plan_bundle）→ 这里的调用记录
    立刻对不上。
    """
    lib, cfg = _mk_role(tmp_path)
    calls = {}
    real_plan = pet_export.plan_bundle
    real_writer = pet_export.BundleWriter

    def plan_spy(*a, **k):
        calls["plan_args"] = (a, k)
        return real_plan(*a, **k)

    class WriterSpy(real_writer):
        def __init__(self, plan, out_path, *a, **k):
            calls.setdefault("writers", []).append((plan, out_path, a, k))
            super().__init__(plan, out_path, *a, **k)

        def step(self, budget_ms=None):
            calls.setdefault("steps", []).append(budget_ms)
            return super().step(budget_ms=budget_ms)

        def finish(self):
            calls["finished"] = calls.get("finished", 0) + 1
            return super().finish()

    monkeypatch.setattr(pet_export, "plan_bundle", plan_spy)
    monkeypatch.setattr(pet_export, "BundleWriter", WriterSpy)
    out = str(tmp_path / "share.dfypet.zip")
    ok, err = pet_export.export_bundle(lib, None, cfg, out)
    assert ok and not err, err
    assert "plan_args" in calls, "export_bundle 没有调 plan_bundle（收集阶段被内联了）"
    assert len(calls.get("writers", [])) == 1, "export_bundle 没有走 BundleWriter"
    _plan, _path, _a, _k = calls["writers"][0]
    assert _path == out and _plan["entries"], "BundleWriter 拿到的 plan/输出路径不对"
    assert calls.get("steps") == [None], "一次性导出必须 step(budget_ms=None)，实为 %r" \
        % (calls.get("steps"),)
    assert calls.get("finished") == 1, "finish() 没被调用（没做原子替换/自校验）"
    assert os.path.isfile(out)


# ---------------- 2. 分片写与一次性写逐条目相同 ----------------

def test_sliced_write_is_entry_for_entry_identical(tmp_path):
    """同一角色：一次性写 vs 每条一片写 → 条目名/顺序/CRC/内容/manifest 全等。

    能真失败：分片器漏写 manifest、换条目顺序、写错源文件 → 任一断言红。
    """
    lib, cfg = _mk_role(tmp_path, n_frames=6)
    one_shot = str(tmp_path / "one.dfypet.zip")
    sliced = str(tmp_path / "sliced.dfypet.zip")
    ok, err = pet_export.export_bundle(lib, None, cfg, one_shot)
    assert ok and not err, err

    plan, err = pet_export.plan_bundle(lib, None, cfg)
    assert plan is not None, err
    w = pet_export.BundleWriter(plan, sliced)
    steps = 0
    while not w.done and steps < 500:
        steps += 1
        w.step(budget_ms=0.0)      # 每条一片
    ok, err = w.finish()
    assert ok and not err, err

    with zipfile.ZipFile(one_shot) as a, zipfile.ZipFile(sliced) as b:
        assert a.namelist() == b.namelist(), \
            "条目名/顺序不一致：\n  %r\n  %r" % (a.namelist(), b.namelist())
    ha, hb = _entry_hashes(one_shot), _entry_hashes(sliced)
    assert ha == hb, "逐条目内容指纹不一致：\n  %r\n  %r" % (ha, hb)
    with zipfile.ZipFile(one_shot) as a, zipfile.ZipFile(sliced) as b:
        assert json.loads(a.read("manifest.json").decode("utf-8")) == \
            json.loads(b.read("manifest.json").decode("utf-8")), "manifest 内容不一致"


# ---------------- 3. 分片真的分片 ----------------

def test_writer_step_honours_budget(tmp_path):
    """budget_ms 必须真的限制"一片写几条"：条目多时一片写不完。

    能真失败：step 忽略 budget_ms（一次写光）→ 片数掉到 1，第一条断言红。
    """
    lib, cfg = _mk_role(tmp_path, n_frames=6)
    plan, err = pet_export.plan_bundle(lib, None, cfg)
    assert plan is not None and len(plan["entries"]) == 6, err
    w = pet_export.BundleWriter(plan, str(tmp_path / "s.zip"))
    w.step(budget_ms=0.0)          # 0ms 预算 = 每片至少写一条
    assert w.written == 1 and not w.done, \
        "一片写了 %d 条（应当只写 1 条就回事件循环）" % w.written
    n = 0
    while not w.done and n < 100:
        n += 1
        w.step(budget_ms=0.0)
    assert n == 5, "剩下的 5 条应当各占一片，实为 %d 片" % n
    ok, err = w.finish()
    assert ok and not err, err


# ---------------- 4. abort 不留半截包 ----------------

def test_abort_removes_tmp_and_never_touches_output(tmp_path):
    """中途放弃：正式输出文件不存在，临时文件也不残留。

    能真失败：abort 不清理 tmp（或直接 os.replace 出一个半截包）→ 红。
    """
    lib, cfg = _mk_role(tmp_path, n_frames=4)
    plan, err = pet_export.plan_bundle(lib, None, cfg)
    out = str(tmp_path / "abort.dfypet.zip")
    w = pet_export.BundleWriter(plan, out)
    w.step(budget_ms=0.0)
    assert w.written == 1
    assert os.path.isfile(w.tmp), "前提不成立：临时文件没建起来"
    w.abort()
    assert not os.path.exists(out), "放弃后不该出现输出文件"
    assert not os.path.exists(w.tmp), "放弃后临时文件没清掉：%s" % w.tmp
    assert not [n for n in os.listdir(str(tmp_path)) if n.endswith(".tmp")], "还有 tmp 残留"


# ---------------- 5. UI 侧端到端：分片驱动 ----------------

@pytest.fixture
def pet(tmp_path):
    import pet_log
    import 桌宠 as main
    from PySide6.QtWidgets import QApplication

    snap = (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
            getattr(pet_log, "_data_dir", None))
    main.DATA_DIR = str(tmp_path)
    main.CONFIG_PATH = str(tmp_path / "config.json")
    main.USAGE_PATH = str(tmp_path / "usage.json")
    main.MEMORY_PATH = str(tmp_path / "memory.json")
    pet_log.set_data_dir(str(tmp_path))
    QApplication.instance() or QApplication([])
    win = main.PetWindow()
    from helpers_roles import (active_timer_count, install_three_form_role,
                               quiet_pet_timers, shutdown_pet)
    install_three_form_role(win, tmp_path)     # 装自定义角色（_export_role 要求非默认角色）
    quiet_pet_timers(win)
    win._bubbles = []
    win.show_bubble = lambda t, *a, **k: win._bubbles.append(t)
    yield win
    # 收尾（v2.4.2 隔离加固）：**用例断言失败也要**把窗口拆干净、把全局值还原。
    # 旧写法把还原放在 yield 之后平铺——只要中间任何一步抛异常，DATA_DIR/CONFIG_PATH
    # 就会一直指向本用例的临时目录，后续模块会往已删除的 tmp 里写盘（本仓踩过的坑）。
    try:
        # 在途的分片导出先作废（正常情况下用例已驱动到收敛，这里是断言失败时的兜底）：
        # 否则半截临时包会留在临时目录里，且 QTimer(0) 接力还挂在窗口上。
        if getattr(win, "_export_writer", None) is not None:
            win._export_writer.abort()
            win._export_writer = None
        shutdown_pet(win)
        # 与其它真窗口模块同一把尺子：拆完一个活跃子定时器都不许剩（停表漏了就地红）
        assert active_timer_count(win) == 0, \
            "拆完还有 %d 个活跃定时器" % active_timer_count(win)
    finally:
        (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
         pet_log._data_dir) = snap


def test_export_role_drives_the_writer_in_slices(pet, tmp_path, monkeypatch):
    """_export_role 必须把写盘交给**分片器**驱动（不是同步写完）。

    能真失败：把 _export_role 改回同步调用 export_bundle → 既不构造 BundleWriter、
    step 也不会带 budget_ms → 前两条断言红。
    （用例角色故意做大：16 张 256px 噪声帧 ≈4MB，一个 12ms 切片写不完 → 必须多片。）
    """
    import 桌宠 as main
    from PySide6.QtWidgets import QApplication
    from helpers_roles import install_big_frame_role

    rid, _paths = install_big_frame_role(pet, pet.role_lib._dir, n=16, size=256,
                                         rid="bigexp1", prefix="bigexp")
    pet.apply_role(rid)
    out = str(tmp_path / "ui_export.dfypet.zip")

    class _FD:
        @staticmethod
        def getSaveFileName(*_a, **_k):
            return out, ""

    monkeypatch.setattr(main, "QFileDialog", _FD)
    monkeypatch.setattr(main.pet_dialogs, "pick_role_meta", lambda *_a, **_k: {})

    made = []
    real_writer = main.pet_export.BundleWriter

    class WriterSpy(real_writer):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.steps = []
            made.append(self)

        def step(self, budget_ms=None):
            self.steps.append(budget_ms)
            return super().step(budget_ms=budget_ms)

    monkeypatch.setattr(main.pet_export, "BundleWriter", WriterSpy)

    pet._export_role()
    assert made, "导出没有走 BundleWriter（还是同步的 export_bundle？）"
    assert made[0].steps and made[0].steps[0] == main._EXPORT_SLICE_MS, \
        "第一片没有按 _EXPORT_SLICE_MS 预算切（steps=%r）" % (made[0].steps,)
    assert pet._bubbles and pet._bubbles[-1].startswith("正在导出角色包"), \
        "首个气泡不是进度：%r" % (pet._bubbles[-1:],)

    guard = 0
    while pet._export_writer is not None and guard < 4000:
        guard += 1
        QApplication.processEvents()
    assert pet._export_writer is None, "分片写没有收敛"
    assert os.path.isfile(out), "导出文件没落盘"
    m, err = pet_export.validate_bundle(out)
    assert m is not None and not err, err
    assert pet._bubbles[-1].startswith("角色包已导出"), \
        "完成气泡文案变了：%r" % (pet._bubbles[-1],)
    assert len(made[0].steps) >= 2, "只切了一片（等于没分片）：%r" % (made[0].steps,)


def test_export_role_reports_the_same_error_text(pet, tmp_path, monkeypatch):
    """收集阶段失败时，气泡文案必须与旧版 export_bundle 的错误文案逐字一致。

    能真失败：把 _export_role 的错误前缀从"导出失败："改掉、或吞掉 plan_bundle 的 err → 红。
    """
    import 桌宠 as main

    class _FD:
        @staticmethod
        def getSaveFileName(*_a, **_k):
            return str(tmp_path / "x.zip"), ""

    monkeypatch.setattr(main, "QFileDialog", _FD)
    monkeypatch.setattr(main.pet_dialogs, "pick_role_meta", lambda *_a, **_k: {})
    # 让角色的第一个素材"消失" → plan_bundle 报"角色素材缺失，无法导出：<文件名>"
    rid = str(pet.cfg.get("role") or "")
    ref = pet.role_lib.form_paths(rid)[0]
    os.remove(pet.role_lib.resolve(ref))
    pet._export_role()
    assert pet._export_writer is None, "收集失败时不该起分片器"
    assert pet._bubbles and pet._bubbles[-1].startswith("导出失败："), pet._bubbles[-1:]
    assert "缺失" in pet._bubbles[-1], pet._bubbles[-1]
