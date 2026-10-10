# -*- coding: utf-8 -*-
"""v2.4.2 兼容审查修复回归：M1 / M2 / M3（含 M1' 文案）/ M4 / L2 / L4 / L5 / L6。

每条都配了"能真失败"的机制（_dev/mutations_compat_v242.json 会用变异验证再跑一遍：
把修复那几行拿掉，本文件的用例必须变红）。逐条对应关系：

  M1  导出分片无重入保护            → test_export_role_refuses_reentry_*、
                                       test_two_writers_never_share_a_tmp_name
  M2  单个大条目一片写完（822.9ms）  → test_big_entry_is_written_across_slices_*
  M3  编码回退被 GBK/单字节页抢答    → test_cp932_locale_*、test_cp1252_locale_*、
                                       test_broken_utf8_is_not_caught_by_cp1252
  M1' 气泡写死"已按 GBK 读取"        → test_fallback_notice_names_the_real_encoding、
                                       test_startup_bubble_is_wired_to_the_real_encoding
  M4  alarms/behaviors 无回退读/无备份 → test_alarms_gbk_*、test_behaviors_gbk_*、
                                       test_undecodable_index_is_backed_up_before_first_write
  L2  _start_petting 过早补帧集      → test_start_petting_does_not_load_frames_on_early_return
  L4' _play_idle 给自定义角色白解素材 → test_play_idle_skips_default_frames_for_custom_role
  L4  _quit 不作废在途导出           → test_quit_aborts_inflight_export
  L5  接力窗内 play_action 静默无反应 → test_play_action_ensures_frames_before_frame_action
  L6  abort 之后 finish 吐内部错误    → test_finish_after_abort_reports_cancelled
  B   pet_lines 顶层未知键丢失        → test_lines_keeps_top_level_unknown_keys_on_save
"""
import hashlib
import json
import locale
import os
import sys
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pet_export  # noqa: E402
import pet_io  # noqa: E402
import pet_lines  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ===================== 公共夹具 / 小工具 =====================

def _png_bytes(seed, size=60000):
    """伪随机内容（不可压缩，与真实 PNG 一样让 deflate 有活干）。"""
    return b"\x89PNG\r\n\x1a\n" + (hashlib.sha256(b"seed%d" % seed).digest() * 2000)[:size]


def _plan(tmp_path, n_small=3, small_bytes=60000, big_bytes=0):
    """手搓一个**能过 validate_bundle 自校验**的 plan（不依赖 RoleLibrary，跑得快）。"""
    roles = tmp_path / "roles"
    roles.mkdir(exist_ok=True)
    names, entries = [], []
    for i in range(n_small):
        n = "f%02d.png" % i
        (roles / n).write_bytes(_png_bytes(i, small_bytes))
        names.append(n)
        entries.append(("roles/" + n, str(roles / n)))
    if big_bytes:
        big = roles / "big_ref.bin"
        big.write_bytes(os.urandom(big_bytes))
        entries.append(("voice_ref/big_ref.bin", str(big)))
    manifest = {"format": pet_export.BUNDLE_FORMAT, "version": pet_export.BUNDLE_VERSION,
                "role": {"id": "compat01", "name": "兼容审查角色", "file": names[0],
                         "form": "single", "file_full": "", "frames": list(names), "added": "",
                         "forms": [{"name": "常态", "file": names[0], "front": names[0],
                                    "animations": {"idle": list(names)}}]},
                "behaviors": [], "config": {}, "excluded": [], "alarms": []}
    return {"manifest": manifest, "entries": entries}


def _lines_json(text, lid="u1", extra=None):
    body = {"version": 1, "lines": [{"id": lid, "text": text, "category": "idle", "order": 1}]}
    if extra:
        body.update(extra)
    return body


@pytest.fixture
def pet(tmp_path):
    """真 PetWindow（装了自定义角色）——UI 侧几条链路的共同夹具。"""
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
    from helpers_roles import install_three_form_role, quiet_pet_timers, shutdown_pet
    install_three_form_role(win, tmp_path)
    quiet_pet_timers(win)
    win._bubbles = []
    win.show_bubble = lambda t, *a, **k: win._bubbles.append(t)
    yield win
    shutdown_pet(win)
    (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
     pet_log._data_dir) = snap


# ===================== M1：导出重入守卫 + tmp 私有 =====================

def _start_big_export(pet, tmp_path, monkeypatch, outs):
    """起一次"必然还没写完"的导出，返回 (写包器列表, 文件名调用计数)。"""
    import 桌宠 as main
    from helpers_roles import install_big_frame_role

    rid, _paths = install_big_frame_role(pet, pet.role_lib._dir, n=4, size=256,
                                         rid="reent1", prefix="reent")
    pet.apply_role(rid)
    calls = {"n": 0}

    class _FD:
        @staticmethod
        def getSaveFileName(*_a, **_k):
            out = outs[min(calls["n"], len(outs) - 1)]
            calls["n"] += 1
            return out, ""

    monkeypatch.setattr(main, "QFileDialog", _FD)
    monkeypatch.setattr(main.pet_dialogs, "pick_role_meta", lambda *a, **k: {})
    # 0ms 预算 = 一片只写一条/一块 → 首片必定写不完（否则"重入"根本无从复现）
    monkeypatch.setattr(main, "_EXPORT_SLICE_MS", 0.0)
    made = []
    real_writer = main.pet_export.BundleWriter

    class WriterSpy(real_writer):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            made.append(self)

    monkeypatch.setattr(main.pet_export, "BundleWriter", WriterSpy)
    pet._export_role()
    return made, calls


def test_export_role_refuses_reentry_and_finishes_the_first_package(pet, tmp_path, monkeypatch):
    """在途导出期间再点「导出」：只提示、不起第二个写包器，第一个包必须照常落盘。

    能真失败：去掉 _export_role 开头的守卫 → 第二次点击又起一个 BundleWriter（made 变 2）、
    self._export_writer 被顶掉、第一个输出文件永远不存在（分片接力跟着新写者跑）。
    """
    from PySide6.QtWidgets import QApplication
    outs = [str(tmp_path / "first.dfypet.zip"), str(tmp_path / "second.dfypet.zip")]
    made, calls = _start_big_export(pet, tmp_path, monkeypatch, outs)
    assert len(made) == 1 and pet._export_writer is made[0], \
        "前提不成立：首片就把包写完了（这条用例要靠「在途」状态）"
    w1 = pet._export_writer
    pet._bubbles[:] = []
    pet._export_role()                      # 用户又点了一次「导出」
    assert len(made) == 1, "重入守卫失效：第二次点击又起了一个写包器"
    assert pet._export_writer is w1, "在途的导出被后来的调用顶掉了"
    assert calls["n"] == 1, "守卫没有在弹「保存到哪」对话框之前生效"
    assert pet._bubbles[-1] == "还在导出上一个角色包，稍等一下~", pet._bubbles[-2:]
    guard = 0
    while pet._export_writer is not None and guard < 8000:
        guard += 1
        QApplication.processEvents()
    assert pet._export_writer is None, "第一次导出没有收敛"
    assert os.path.isfile(outs[0]), "第一次导出没有落盘（被重入顶掉后包丢了）"
    m, err = pet_export.validate_bundle(outs[0])
    assert m is not None and not err, err
    assert not os.path.exists(outs[1]), "第二次点击居然真的导出了第二个包"


def test_two_writers_never_share_a_tmp_name(tmp_path):
    """同一输出路径的两个写包器必须各写各的 tmp（旧实现两者 tmp 名逐字相同）。

    能真失败：tmp 名去掉进程内序号（只留线程号）→ 同一线程建两个 writer 名字就撞了，
    交错写同一个文件 → 先收尾的 finish() 报 WinError 32（自校验侥幸救包）。
    """
    plan = _plan(tmp_path, n_small=3)
    out = str(tmp_path / "same.dfypet.zip")
    a = pet_export.BundleWriter(plan, out)
    b = pet_export.BundleWriter(plan, out)
    assert a.tmp != b.tmp, "两个写者共用同一个 tmp 名：%s" % a.tmp
    a.step(budget_ms=0.0)
    b.step(budget_ms=0.0)
    assert os.path.isfile(a.tmp) and os.path.isfile(b.tmp), "各写各的 tmp 没建起来"
    ok_a, err_a = a.finish()
    ok_b, err_b = b.finish()
    assert ok_a and not err_a, err_a
    assert ok_b and not err_b, err_b
    assert not [n for n in os.listdir(str(tmp_path)) if n.endswith(".tmp")], "有 tmp 残留"


# ===================== M2：大条目跨片写（产出逐位不变） =====================

_BIG_BYTES = 16 * 1024 * 1024      # 16MB 不可压缩成员：旧实现一条独占一片 ≈400ms+


def test_big_entry_is_written_across_slices_and_bytes_stay_identical(tmp_path):
    """13 条里放一个 16MB 不可压缩成员：**任何一片**都不许超过预算的量级，且产出逐位相同。

    能真失败：把大条目改回"一条一次 zf.write"（就是 v2.4.2 修之前的样子）→
    单片 ≈400ms（审查实测 24MB 那条是 822.9ms），且片数掉到 13 → 两条断言都红。
    """
    plan = _plan(tmp_path, n_small=12, big_bytes=_BIG_BYTES)
    one_shot = str(tmp_path / "one.dfypet.zip")
    sliced = str(tmp_path / "sliced.dfypet.zip")

    w1 = pet_export.BundleWriter(plan, one_shot)
    w1.step()                                  # budget_ms=None：旧的一口气写法
    ok, err = w1.finish()
    assert ok and not err, err

    w2 = pet_export.BundleWriter(plan, sliced)
    slices, steps = [], 0
    while not w2.done and steps < 200000:
        steps += 1
        t0 = time.perf_counter()
        w2.step(budget_ms=12.0)                # 与 _EXPORT_SLICE_MS 同值
        slices.append((time.perf_counter() - t0) * 1000.0)
    ok, err = w2.finish()
    assert ok and not err, err

    worst = max(slices)
    assert worst < 150.0, \
        "单片阻塞 %.1fms（16MB 不可压缩成员一条独占一片；预算 12ms）" % worst
    assert len(slices) > 20, "大条目没有跨片：只切了 %d 片" % len(slices)
    with open(one_shot, "rb") as f1, open(sliced, "rb") as f2:
        assert f1.read() == f2.read(), \
            "分块写与一次性写的整包字节不同（对外产出格式被改了）"


def test_manifest_timestamp_is_fixed_so_exports_are_reproducible(tmp_path, monkeypatch):
    """manifest 条目的时间戳必须**确定**：同一个 plan 隔几秒再导出仍逐字节相同。

    审查实测（复审 M5）：此前走 writestr(str)，它用 time.localtime(time.time())；
    同一 plan 连写两次在同 2 秒桶内相同，**隔 2.3 秒就不同**（差异只在两处 DOS 时间字段：
    本地文件头偏移 10、中央目录偏移 1140），"产出逐位不变"跨 2 秒即失效——上一条整包
    字节比较的偶发红就是它，不是测试的锅。

    能真失败：把 _open() 退回 writestr(MANIFEST_NAME, ...) → 假时钟往后拨 2 秒后整包
    字节不同（且 manifest 条目的 date_time 不再是 1980-01-01）→ 两条断言红。
    用注入的假时钟而不是 sleep(2.3s)：跨 2 秒桶是唯一差异来源，sleep 又慢又不确定。
    """
    plan = _plan(tmp_path, n_small=2)

    class _Clock(object):
        """假时钟：只骗 writestr 的"当前时间"，from_file 仍按源文件真实 mtime。"""

        def __init__(self, epoch):
            self.epoch = epoch

        def time(self):
            return self.epoch

        def localtime(self, t=None):
            return time.localtime(self.epoch if t is None else t)

    base = time.time()
    clock = _Clock(base)
    monkeypatch.setattr(pet_export.zipfile, "time", clock)   # zipfile 就在 pet_export 命名空间里
    first = str(tmp_path / "a.dfypet.zip")
    second = str(tmp_path / "b.dfypet.zip")
    w1 = pet_export.BundleWriter(plan, first)
    w1.step()
    assert w1.finish()[0]
    clock.epoch = base + 2.3                       # 跨过 2 秒的 DOS 时间桶
    w2 = pet_export.BundleWriter(plan, second)
    w2.step()
    assert w2.finish()[0]
    with open(first, "rb") as f1, open(second, "rb") as f2:
        assert f1.read() == f2.read(), \
            "隔 2 秒导出同一个 plan 字节就变了（manifest 时间戳还在取当前时钟）"
    with pet_export.zipfile.ZipFile(second) as z:
        zi = z.getinfo(pet_export.MANIFEST_NAME)
        assert zi.date_time == (1980, 1, 1, 0, 0, 0), \
            "manifest 条目时间戳不是固定值：%r" % (zi.date_time,)
        assert zi.compress_type == pet_export.zipfile.ZIP_DEFLATED, \
            "手工构造 ZipInfo 改掉了 manifest 的压缩方式（外部产出格式变了）"


# ===================== M3：编码回退顺序 + 单字节页护栏 =====================

def _patch_locale(monkeypatch, enc):
    """把本机默认编码换成 enc（pet_io 的候选顺序按它排）。"""
    monkeypatch.setattr(locale, "getpreferredencoding", lambda *a, **k: enc)


def test_cp932_locale_reads_shift_jis_lines_correctly(tmp_path, monkeypatch):
    """日文 Windows（locale=cp932）：cp932 的台词库必须按 cp932 读，不能被 GBK 抢先解成乱码。

    能真失败：候选顺序退回"固定表 gbk/cp936 在前" → 「こんにちは」按 GBK 解成
    「偙傫偵偪偼」，而且**照样能过 JSON 解析** → gbk_read=True、气泡还说"台词都还在"。
    """
    _patch_locale(monkeypatch, "cp932")
    text = "こんにちは、世界"
    raw = json.dumps(_lines_json(text), ensure_ascii=False).encode("cp932")
    p = tmp_path / "lines.json"
    p.write_bytes(raw)
    logs = []
    svc = pet_lines.LineService(str(tmp_path), log=logs.append)
    got = svc.get("u1")
    assert got is not None and got["text"] == text, "cp932 台词被别的编码抢先解了：%r" % (got,)
    assert svc.gbk_read is True and svc.dirty_read is False
    assert pet_io._codec_name(svc.read_encoding) == "cp932", svc.read_encoding
    assert svc.read_trusted is True, "本机 ANSI 页就是 cp932，不该被当成猜的"
    assert p.read_bytes() == raw, "启动阶段就动了原文件"
    assert not (tmp_path / "lines.json.bak").exists(), "读出来了就不该在启动阶段留 .bak"


def test_cp1252_locale_does_not_promise_intact_content(tmp_path, monkeypatch):
    """西欧 Windows（locale=cp1252）：按 cp1252 读出来了，但**不能**承诺"台词都还在"。

    单字节代码页能把任意字节解出来；命中它时文案必须是谨慎口径（请用户核对），
    而且要说**实际**编码，不能说成 GBK（审查实测：日志说 CP1252、气泡说 GBK）。
    """
    _patch_locale(monkeypatch, "cp1252")
    text = "café résumé naïve"
    raw = json.dumps(_lines_json(text), ensure_ascii=False).encode("cp1252")
    (tmp_path / "lines.json").write_bytes(raw)
    svc = pet_lines.LineService(str(tmp_path), log=lambda m: None)
    assert svc.get("u1")["text"] == text
    assert pet_io._codec_name(svc.read_encoding) == "cp1252", svc.read_encoding
    notice = svc.read_notice
    assert "CP1252" in notice.upper(), notice
    assert "GBK" not in notice.upper(), "文案把实际编码说成了 GBK：%r" % notice


@pytest.mark.parametrize("loc,enc,text", [
    ("cp932", "cp932", "こんにちは、世界"),
    ("cp950", "cp950", "你好，世界，繁體"),
    ("cp1252", "cp1252", "café résumé"),
])
def test_fallback_notice_names_the_real_encoding(tmp_path, monkeypatch, loc, enc, text):
    """文案必须按**实际命中编码**给（cp932/cp950/cp1252 三种 locale 各来一遍）。

    能真失败：把 UI 侧写死成 pet_lines.GBK_READ_NOTICE（v2.4.2 修之前的样子）→
    非中文 Windows 上气泡对用户说假话。
    """
    _patch_locale(monkeypatch, loc)
    raw = json.dumps(_lines_json(text), ensure_ascii=False).encode(enc)
    (tmp_path / "lines.json").write_bytes(raw)
    svc = pet_lines.LineService(str(tmp_path), log=lambda m: None)
    assert svc.get("u1")["text"] == text, "回退没读到正确内容：%r" % (svc.get("u1"),)
    notice = svc.read_notice
    assert enc.upper() in notice.upper(), notice
    assert "GBK" not in notice.upper(), notice
    if enc != "cp1252":      # CJK 页且就是本机 ANSI 页 → 才敢说"台词都还在"
        assert "都还在" in notice, notice


def test_broken_utf8_is_not_caught_by_cp1252(tmp_path, monkeypatch):
    """"坏了一个字节的 UTF-8"落到单字节西文页手里 = mojibake：宁可不读，也不能当成读到了。

    能真失败：把单字节候选的 _almost_utf8 护栏拿掉 → cp1252 把整份接住（中文变
    ÿ½ å¥½ï¼Œä¸–ç•Œ）、gbk_read=True、还显示"台词都还在"，首次保存把乱码转成 UTF-8。
    """
    _patch_locale(monkeypatch, "cp1252")
    raw = json.dumps(_lines_json("你好世界"), ensure_ascii=False).encode("utf-8")
    i = raw.index("好".encode("utf-8"))
    broken = raw[:i + 1] + b"\xff" + raw[i + 2:]      # 只把这个字的第二个字节写坏
    # 前提自证：GBK 解不出来、cp1252 能解出来、JSON 也还解析得动 —— 正是审查那条路径
    with pytest.raises(UnicodeDecodeError):
        broken.decode("gbk")
    assert isinstance(json.loads(broken.decode("cp1252")), dict)
    assert pet_io._almost_utf8(broken) is True

    p = tmp_path / "lines.json"
    p.write_bytes(broken)
    svc = pet_lines.LineService(str(tmp_path), log=lambda m: None)
    assert svc.gbk_read is False, "被 cp1252 接住当成读到了（内容是 mojibake）"
    assert svc.dirty_read is True, "没走脏读路径"
    assert svc.get("u1") is None, "乱码居然进了台词库"
    assert p.read_bytes() == broken, "脏读路径动了原文件"
    assert not (tmp_path / "lines.json.bak").exists(), "启动阶段留 .bak 是多余的写盘"
    assert svc.read_notice == ""
    svc.add("新台词", "idle")
    assert (tmp_path / "lines.json.bak").read_bytes() == broken, "覆盖原文之前没留 .bak"


def test_gbk_is_still_used_when_locale_is_not_cjk(tmp_path, monkeypatch):
    """反向：locale 不是 CJK 页（cp1252）时 GBK 仍排在前面——GBK 文件在各环境都要读对。"""
    _patch_locale(monkeypatch, "cp1252")
    text = "中文台词，笔记本来回换机器也不该丢"
    raw = json.dumps(_lines_json(text), ensure_ascii=False).encode("gbk")
    (tmp_path / "lines.json").write_bytes(raw)
    svc = pet_lines.LineService(str(tmp_path), log=lambda m: None)
    assert svc.get("u1")["text"] == text
    assert pet_io._codec_name(svc.read_encoding) == "gbk", svc.read_encoding
    assert svc.read_trusted is False, "本机不是 GBK，不该把猜的当成就是它"
    assert "GBK" in svc.read_notice.upper() and "都还在" not in svc.read_notice, \
        "猜出来的编码不能承诺内容没丢：%r" % svc.read_notice
    assert pet_io._codec_name(pet_io.fallback_encodings()[0]) == "gbk", \
        pet_io.fallback_encodings()


def test_startup_bubble_is_wired_to_the_real_encoding():
    """UI 侧必须按实际编码取文案（结构判据：写死 GBK 的那条老路只能留给 GBK 自己）。

    能真失败：把桌宠.py 改回无条件弹 pet_lines.GBK_READ_NOTICE → 缺 read_notice 接线即红。
    """
    with open(os.path.join(ROOT, "桌宠.py"), "r", encoding="utf-8") as f:
        src = f.read()
    assert "self.lines_lib.gbk_read" in src, "回退读取没有接到气泡上"
    assert "pet_lines.GBK_READ_NOTICE" in src, "GBK 那条老文案被删了（GBK 用户观感会变）"
    for token in ("self.lines_lib.read_notice", "read_is_gbk", "read_trusted"):
        assert token in src, "启动气泡没有按实际编码取文案：缺 %s" % token


# ===================== M4：alarms/behaviors 回退读 + 首次写前备份 =====================

def _alarms_gbk_raw():
    return json.dumps({"alarms": [
        {"id": "aa11bb22", "time": "07:30", "label": "起床", "ringtone": "",
         "enabled": True, "last_fired_date": "", "repeat": "", "snooze_min": 0},
        {"id": "cc33dd44", "time": "22:00", "label": "睡觉", "ringtone": "",
         "enabled": True, "last_fired_date": "", "repeat": "", "snooze_min": 0}],
        "my_custom_section": {"keep": 1}}, ensure_ascii=False).encode("gbk")


def test_alarms_gbk_index_survives_the_first_write(tmp_path):
    """GBK 的 alarms.json：启动就能看见原条目；第一次增删不许把它们和顶层键一起冲掉。

    能真失败：去掉 pet_alarm._load 里的回退读 → 内存里是空库（list()==[]）、
    第一次 add 之后盘上只剩 {"alarms": [新条目]}、无 .bak、原文不可恢复。
    """
    from pet_alarm import AlarmService
    idx = tmp_path / "alarms.json"
    raw = _alarms_gbk_raw()
    idx.write_bytes(raw)
    svc = AlarmService(str(tmp_path), log=lambda m: None)
    assert len(svc.list()) == 2, "GBK 的 alarms.json 被读成空库（原条目看不见）"
    assert idx.read_bytes() == raw, "启动阶段就动了原文件"
    assert not (tmp_path / "alarms.json.bak").exists(), "读出来了就不该在启动阶段留 .bak"
    got, err = svc.add("08:00", "上班")
    assert got is not None and not err, err
    on_disk = json.loads(idx.read_text(encoding="utf-8"))
    ids = {x["id"] for x in on_disk["alarms"]}
    assert {"aa11bb22", "cc33dd44", got["id"]} <= ids, "第一次增删把旧闹钟覆盖掉了"
    assert on_disk.get("my_custom_section") == {"keep": 1}, "自定义顶层键被删了"
    assert (tmp_path / "alarms.json.bak").read_bytes() == raw, "转存 UTF-8 之前没留 GBK 原文"


def test_behaviors_gbk_index_survives_the_first_write(tmp_path):
    """同上，作用于 behaviors.json（审查同一条实现在两个模块上都缺保护）。"""
    from pet_behaviors import BehaviorService
    idx = tmp_path / "behaviors.json"
    # 注意：内容必须含中文，否则 GBK 与 UTF-8 逐字节相同，这条用例会退化成空转
    raw = json.dumps({"behaviors": [
        {"id": "aa11bb22", "name": "wave", "steps": [{"act": "say", "text": "分享行为"}]}],
        "my_meta": {"note": "手加的备注"}}, ensure_ascii=False).encode("gbk")
    assert any(b > 127 for b in raw), "前提：这必须是**真 GBK**（含非 ASCII 字节）"
    idx.write_bytes(raw)
    svc = BehaviorService(str(tmp_path), log=lambda m: None)
    assert [b["id"] for b in svc.list()] == ["aa11bb22"], "GBK 的 behaviors.json 被读成空库"
    assert idx.read_bytes() == raw and not (tmp_path / "behaviors.json.bak").exists()
    got, err = svc.add("dance2", [{"act": "play_action", "name": "jump"}])
    assert got is not None and not err, err
    on_disk = json.loads(idx.read_text(encoding="utf-8"))
    assert {b["id"] for b in on_disk["behaviors"]} == {"aa11bb22", got["id"]}
    assert on_disk.get("my_meta") == {"note": "手加的备注"}, "自定义顶层键被删了"
    assert (tmp_path / "behaviors.json.bak").read_bytes() == raw


@pytest.mark.parametrize("fname,mod,cls", [
    ("alarms.json", "pet_alarm", "AlarmService"),
    ("behaviors.json", "pet_behaviors", "BehaviorService"),
])
def test_undecodable_index_is_backed_up_before_first_write(tmp_path, fname, mod, cls):
    """连编码回退都解不开（真乱码）时：启动一个字节都不写，**首次写前**必须留 .bak。

    能真失败：只做回退读、不做 _read_failed → 第一次增删把原文整份覆盖掉且零备份。
    """
    import importlib
    svc_cls = getattr(importlib.import_module(mod), cls)
    idx = tmp_path / fname
    raw = b"\xff\xfe\xff\xfe"
    idx.write_bytes(raw)
    svc = svc_cls(str(tmp_path), log=lambda m: None)
    assert idx.read_bytes() == raw, "读不到时动了原文件（v2.3.1 口径：一个字节都不写）"
    assert not (tmp_path / (fname + ".bak")).exists(), "启动阶段留 .bak 是多余的写盘"
    if cls == "AlarmService":
        got, err = svc.add("09:00", "测试")
    else:
        got, err = svc.add("clap", [{"act": "play_action", "name": "jump"}])
    assert got is not None and not err, err
    bak = tmp_path / (fname + ".bak")
    assert bak.is_file() and bak.read_bytes() == raw, "覆盖读不到的原文之前没留 .bak"


def test_lines_keeps_top_level_unknown_keys_on_save(tmp_path):
    """pet_lines._save 也要带回顶层未知键（与 pet_alarm/pet_behaviors 同口径）。

    能真失败：_save 重建已知段（v2.4.2 修之前的样子）→ GBK 读入 + 一次 add 之后，
    用户手加的顶层段在盘上消失。
    """
    p = tmp_path / "lines.json"
    raw = json.dumps(_lines_json("中文台词", extra={"my_section": {"a": 1}}),
                     ensure_ascii=False).encode("gbk")
    p.write_bytes(raw)
    svc = pet_lines.LineService(str(tmp_path), log=lambda m: None)
    assert svc.get("u1") is not None
    ln, err = svc.add("新台词", "idle")
    assert ln is not None and not err, err
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk.get("my_section") == {"a": 1}, "顶层未知键在保存时被删了"
    assert {"u1", ln["id"]} <= {x["id"] for x in on_disk["lines"]}


# ===================== L2 / L4'：延迟装载别在早退路径上白花钱 =====================

def test_start_petting_does_not_load_frames_on_early_return(pet, monkeypatch):
    """明确拖动（press_dist>32）早退时，不该顺手把三组默认帧集解出来（≈26ms）。

    能真失败：把 _ensure_default_frames 放回三个早退之前（v2.4.2 修之前的样子）→
    一次普通拖动就同步解码 idle_full/eat/petpet。
    """
    calls = []
    real = pet._ensure_default_frames
    monkeypatch.setattr(pet, "_ensure_default_frames",
                        lambda *a, **k: (calls.append(a), real(*a, **k))[1])
    monkeypatch.setattr(pet, "_say_line", lambda *a, **k: None)
    pet._petting = False
    pet.busy = False
    pet._press_dist = 40                    # 已明确拖动 → 必然早退
    pet._start_petting()
    assert calls == [], "早退路径上也补齐了默认帧集：%r" % (calls,)
    # 反向对照：真起播时必须补齐（别把这次调用整个删掉）
    pet._press_dist = 0
    pet._start_petting()
    assert calls, "真起播了却没补齐 petpet 帧集"
    pet._end_petting()


def test_play_idle_skips_default_frames_for_custom_role(pet, monkeypatch):
    """自定义角色的 _play_idle 不该补默认素材（role 分支根本不读那批帧，白解 ≈12ms）。

    能真失败：去掉 not self._custom_role 的包裹 → 自定义角色每次待机都白解 idle_full。
    """
    assert pet._custom_role, "前提：夹具装的是自定义角色"
    calls = []
    real = pet._ensure_default_frames
    monkeypatch.setattr(pet, "_ensure_default_frames",
                        lambda *a, **k: (calls.append(a), real(*a, **k))[1])
    pet.busy = False
    pet.anim_mode = "state"                 # 别被"吃帧进行中不复位"那条守卫拦下
    pet._play_idle()
    assert calls == [], "自定义角色也补了默认素材帧集：%r" % (calls,)


# ===================== L5：接力窗内 play_action 静默无反应 =====================

class _FakeStateTimer:
    def stop(self):
        pass


class _AnimPet:
    """最小假宠物：帧集为空（= 启动接力窗内的状态），帧动画用真的 FrameAnim。"""

    def __init__(self, frames):
        from pet_anim import FrameAnim
        self.anim = FrameAnim()
        self._frames = frames
        self._custom_role = False
        self.busy = False
        self._petting = False
        self._sleeping = False
        self.anim_mode = "idle"
        self.EAT_FRAME_MS = 140
        self._state_timer = _FakeStateTimer()
        self.ensure_calls = []
        self.idle_calls = []

    def _cfg(self):
        return {}

    def _ensure_default_frames(self, names=None):
        self.ensure_calls.append(names)
        if not self.anim._sets.get("eat"):
            self.anim.add_set("eat", self._frames)
            return True
        return False

    def _wire_anim_sets(self):
        pass

    def _stop_tween(self):
        pass

    def _cur_form_anim(self):
        return {}

    def _play_idle(self, *a, **k):
        self.idle_calls.append(1)

    def _cur_procs(self):
        return {}


def test_play_action_ensures_frames_before_frame_action():
    """接力窗内 anim 的 eat 槽是空集：play_action("eat") 必须先补齐再播，不许"点了没反应"。

    能真失败：去掉帧集分支前的 _ensure_default_frames 调用（v2.4.2 修之前的样子）→
    空帧集 play() 立刻回调 _play_idle，帧定时器根本没起来（用户视角：静默 no-op）。
    """
    from PySide6.QtGui import QPixmap
    import pet_actions
    pet = _AnimPet([QPixmap(4, 4), QPixmap(4, 4)])
    pet.anim.add_set("eat", [])             # 帧集键在、帧不在（正是接力窗内的状态）
    svc = pet_actions.ActionService(pet, pet._cfg, lambda: ("none", None), 60)
    svc.play_action("eat")
    assert pet.ensure_calls == [None], "play_action 没有补齐默认帧集：%r" % (pet.ensure_calls,)
    assert pet.idle_calls == [], "空帧集播了一次立刻回待机 = 用户点了没反应"
    assert pet.anim._timer.isActive(), "帧动画没起来"
    assert pet.anim_mode == "state"


# ===================== L4：退出时作废在途导出 =====================

def test_quit_aborts_inflight_export(pet, tmp_path, monkeypatch):
    """导出途中退出：半截 "<输出名>.<tid>.<序号>.tmp" 不许留在用户选的目录里。

    能真失败：_quit 里不加 abort（v2.4.2 修之前的样子）→ tmp 留在盘上（数据文件白名单
    扫不到这种名字），正式输出文件当然也没有。
    """
    outs = [str(tmp_path / "quit.dfypet.zip")]
    made, _calls = _start_big_export(pet, tmp_path, monkeypatch, outs)
    assert len(made) == 1 and pet._export_writer is made[0], "前提不成立：导出已经写完了"
    tmp_file = pet._export_writer.tmp
    assert os.path.isfile(tmp_file), "前提不成立：临时文件还没建起来"
    pet._quit()
    assert pet._export_writer is None, "退出后还挂着在途写包器"
    assert not os.path.exists(tmp_file), "退出留下半截临时文件：%s" % tmp_file
    assert not os.path.exists(outs[0]), "放弃的导出不该产出正式文件"


# ===================== L6：abort 之后 finish 的文案 =====================

def test_finish_after_abort_reports_cancelled(tmp_path):
    """abort() 之后再 finish()：给"已取消"，不许把解释器内部错误吐给用户。

    能真失败：finish 不判 self._zf is None（v2.4.2 修之前）→
    err == "写入失败：'NoneType' object has no attribute 'close'"。
    """
    plan = _plan(tmp_path, n_small=3)
    out = str(tmp_path / "aborted.dfypet.zip")
    w = pet_export.BundleWriter(plan, out)
    w.step(budget_ms=0.0)
    w.abort()
    ok, err = w.finish()
    assert ok is False
    assert "取消" in err, "文案不是已取消：%r" % err
    assert "NoneType" not in err and "Traceback" not in err, err
    assert not os.path.exists(out)
