# -*- coding: utf-8 -*-
"""v1.3 无头冒烟验证（QT_QPA_PLATFORM=offscreen，无人工交互）。

覆盖：角色导入/切换、音效组、记账账本、气泡样式、自定义台词、
新菜单构建、6 个对话框、托盘/退出路径。运行时数据全部落到临时目录，
不污染真实 DATA_DIR；退出时清理。用法：python _verify_v13.py
"""
import io
import json
import os
import re
import sys
import shutil
import tempfile
import time

os.environ.setdefault("PYTHONIOENCODING", "utf-8")  # 中文 Windows 默认 GBK：print 带 ¥ 会崩
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# env 变量对 stdio 无效（启动时已定死编码）：直接 reconfigure
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass  # 有意忽略：stdio reconfigure 失败仍可按默认编码输出（尽力而为）
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

FAILS = []
CHECKS = []
EXPECT_CHECKS = 266  # v2.1.8：检查总数硬断言（每次增删检查同步更新；本检查自身不计入）


def check(name, cond, extra=""):
    CHECKS.append((name, bool(cond)))
    if not cond:
        FAILS.append("%s %s" % (name, extra))
    print("%s %s" % ("PASS" if cond else "FAIL", name), extra)


# ---------------- 隔离运行时数据 ----------------
_tmp = tempfile.mkdtemp(prefix="dfy_v13_")
import pet_dialogs  # noqa: E402
import 桌宠 as main  # noqa: E402
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402  # P1-1 异步向导等待用
main.DATA_DIR = _tmp
main.CONFIG_PATH = os.path.join(_tmp, "config.json")
main.USAGE_PATH = os.path.join(_tmp, "usage.json")
main.MEMORY_PATH = os.path.join(_tmp, "memory.json")  # P1-6：对话记忆同样隔离到临时目录
main.pet_log.set_data_dir(_tmp)  # P0-2：pet_* 直连日志同样隔离，不污染仓库目录

# ---- P1-3：配置 schema 版本 / diff 存储 / 坏值修正提示 ----
check("config schema const", main.CONFIG_SCHEMA_VERSION == 2, main.CONFIG_SCHEMA_VERSION)
_cfg_tmp = main.CONFIG_PATH
try:
    _cfg_full = dict(main.DEFAULT_CONFIG)
    _cfg_full["city"] = "上海"
    _cfg_full["scale"] = 1.5
    main.save_config(_cfg_full)
    with open(_cfg_tmp, "r", encoding="utf-8") as f:
        _cfg_on_disk = main.json.load(f)
    check("config diff save", _cfg_on_disk.get("city") == "上海"
          and _cfg_on_disk.get("scale") == 1.5
          and "ai_enabled" not in _cfg_on_disk
          and _cfg_on_disk.get("schema_version") == main.CONFIG_SCHEMA_VERSION,
          sorted(_cfg_on_disk.keys()))
    _cfg_back = main.load_config()
    check("config diff roundtrip", _cfg_back.get("city") == "上海" and _cfg_back.get("ai_model") == "deepseek-chat")
    with open(_cfg_tmp, "w", encoding="utf-8") as f:
        main.json.dump({"city": "东京", "scale": 2.0, "legacy_junk": 1}, f, ensure_ascii=False)
    _cfg_v1 = main.load_config()
    check("config v1 migrate", _cfg_v1.get("city") == "东京" and _cfg_v1.get("_resave") is True
          and "legacy_junk" not in _cfg_v1)
    main.save_config(_cfg_v1)
    with open(_cfg_tmp, "r", encoding="utf-8") as f:
        _cfg_on_disk2 = main.json.load(f)
    check("config v1 resave as v2", _cfg_on_disk2.get("schema_version") == main.CONFIG_SCHEMA_VERSION
          and "legacy_junk" not in _cfg_on_disk2)
    with open(_cfg_tmp, "w", encoding="utf-8") as f:
        main.json.dump({"scale": 99, "chat_memory_rounds": "abc"}, f, ensure_ascii=False)
    _cfg_bad = main.load_config()
    check("config bad value fix", _cfg_bad.get("scale") == 4.0 and _cfg_bad.get("_resave") is True
          and any("scale" in x for x in main.CONFIG_FIXES))
finally:
    main.save_config(dict(main.DEFAULT_CONFIG))  # 恢复隔离目录内的干净配置


def make_test_png(path, w=256, h=256):
    """生成一张带透明底的测试 PNG（供角色导入用）。"""
    from PySide6.QtGui import QImage, QPainter, QColor
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    p.setBrush(QColor("#ff5b7a"))
    p.drawEllipse(40, 40, w - 80, h - 80)
    p.end()
    ok = img.save(path, "PNG")
    return ok


def make_opaque_png(path, w=256, h=256):
    """生成一张真·不透明图（RGB32 无 alpha 通道，浅灰底 + 彩色圆），供自动去背景测试。"""
    from PySide6.QtGui import QImage, QPainter, QColor
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("#f5f5f5"))
    p = QPainter(img)
    p.setPen(QColor("#333333"))
    p.setBrush(QColor("#ff5b7a"))
    p.drawEllipse(w // 4, h // 4, w // 2, h // 2)
    p.end()
    img.save(path, "PNG")


def make_test_wav(path):
    """生成 0.2s 静音 WAV（供音频导入用）。"""
    import struct
    import wave
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        wf.writeframes(b"\x00\x00" * 4410)


def main_flow():
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setStyleSheet(main.MENU_QSS)

    pet = main.PetWindow()

    # ---- 1. 启动基础状态 ----
    check("startup cfg role default", pet.cfg.get("role") == "")
    check("book created", pet.book is not None)
    check("lines_pools built", set(pet.lines_pools) == {"sajiao", "greedy", "scared",
                                                       "happy", "idle", "startup", "petting"})
    check("bubble style default", main.BUBBLE_STYLE.get("font_size") == 10)

    # ---- 1b. 行走参数断言（v1.4.2 降速档，纯函数直测） ----
    check("walk interval", main.WALK_INTERVAL_MS == 120)
    check("walk step far", main._walk_step(1000) == main.WALK_STEP_MAX)
    check("walk step near", main._walk_step(4) == main.WALK_STEP_MIN)
    check("walk step mid", main._walk_step(60) == 6)
    check("walk step adaptive", main._walk_step(1000, 30) == 30)
    check("walk step zero", main._walk_step(0) == 0)

    # ---- 2. 角色导入 + 切换（v1.3.1：单/双形态 + 素材自动处理） ----
    png = os.path.join(_tmp, "role_test.png")
    make_test_png(png)
    role, err = pet.role_lib.import_file(png, "测试角色")
    check("role import (legacy)", role is not None and err is None, "err=%r" % (err,))
    if role:
        pet.apply_role(role["id"])
        check("role active id", pet.role_lib.active_id() == role["id"])
        check("custom role sprites", pet._custom_role and not pet.has_frames)
        check("window size > 0", pet.width() > 20 and pet.height() > 20)
        # 旧版导入无吃饱变体：单形态（仅 f0 一个形态）
        check("legacy role single form", pet.form_keys == ["f0"] and len(pet.sprites) == 1)
        pet.apply_role("")  # 恢复默认
        check("role restore default", not pet._custom_role and pet.has_frames)

    # 素材自动处理：不透明图 → 去背景 + 裁剪 + 缩放
    from PySide6.QtGui import QImage
    opaque = os.path.join(_tmp, "opaque.png")
    make_opaque_png(opaque, 800, 600)
    out1 = os.path.join(_tmp, "proc_base.png")
    okp, notesp = pet_dialogs._prepare_role_png(opaque, out1)
    check("auto-process opaque", okp and os.path.isfile(out1), "err=%r" % (notesp,))
    check("bg removal actually ran", okp and "已自动去背景" in notesp, "notes=%r" % (notesp,))
    if okp:
        img1 = QImage(out1)
        check("processed has alpha", img1.hasAlphaChannel())
        check("processed trimmed+scaled", max(img1.width(), img1.height()) <= 512
              and img1.width() < 800)
    # 已有透明通道的图：去背景不误伤
    png2 = os.path.join(_tmp, "role_test2.png")
    make_test_png(png2)
    out2 = os.path.join(_tmp, "proc_alpha.png")
    okp2, notesp2 = pet_dialogs._prepare_role_png(png2, out2)
    check("auto-process alpha png", okp2, "err=%r" % (notesp2,))

    # 双形态导入：常态+吃饱两张 → 吃饱形态切到第二张图
    full_src = os.path.join(_tmp, "full_src.png")
    make_test_png(full_src, 512, 512)
    out_full = os.path.join(_tmp, "proc_full.png")
    okf, notesf = pet_dialogs._prepare_role_png(full_src, out_full)
    dual, errd = pet.role_lib.import_processed(out1, out_full, "双形态测试")
    check("import dual", dual is not None and errd is None, "err=%r" % (errd,))
    if dual:
        check("dual form recorded", dual.get("form") == "dual"
              and bool(pet.role_lib.path_for_full(dual["id"])))
        # 重启重载回归：重建 RoleLibrary（模拟再次启动）后双形态关联不丢
        lib2 = main.pet_resources.RoleLibrary(_tmp)
        check("role reload keeps file_full", lib2.path_for_full(dual["id"]) is not None
              and lib2.get(dual["id"]).get("form") == "dual")
        pet.apply_role(dual["id"])
        check("dual sprites differ",
              pet.sprites["f1"]["side"].cacheKey() != pet.sprites["f0"]["side"].cacheKey())
        check("dual state full built", pet.state_pix["f1"].get("blush") is not None
              and pet.state_pix["f0"].get("blush") is not None)
        # 中-3：状态展示中切形态 → 立即换新形态同表情；结束后落第二形态
        pet._show_state("angry", 1000)
        pet._set_form("f1")
        check("dual state switch form",
              pet.item.pixmap().cacheKey() == pet.state_pix["f1"]["angry"].cacheKey())
        pet._state_timer.stop()
        pet._state_done()
        check("dual state done falls f1 side",
              pet.item.pixmap().cacheKey() == pet.sprites["f1"]["side"].cacheKey())
        pet._set_form("f0")
        pet._set_form("f1")
        check("dual form shows full pix",
              pet.item.pixmap().cacheKey() == pet.sprites["f1"]["side"].cacheKey())
        pet._set_form("f0")
        # H1 回归：喂食路径（squash 动画收尾）也必须落到吃饱图
        pet.apply_role(dual["id"])
        pet.feed("小鱼干")
        t0 = time.time()
        while pet.busy and time.time() - t0 < 3:
            app.processEvents()
            time.sleep(0.02)
        check("feed shows f1 pix (dual)", pet.form == "f1"
              and pet.item.pixmap().cacheKey() == pet.sprites["f1"]["side"].cacheKey())
        pet._set_form("f0")
        # M4b：双形态删除——两张素材文件都删 + active 重置
        bpath = pet.role_lib.path_for(dual["id"])
        fpath = pet.role_lib.path_for_full(dual["id"])
        okd, errd2 = pet.role_lib.delete(dual["id"])
        check("dual delete both files", okd and not os.path.exists(bpath)
              and not os.path.exists(fpath)
              and pet.role_lib.get(dual["id"]) is None
              and pet.role_lib.active_id() == "")
        pet.apply_role("")
    # 单形态导入：只有一张图 → 两形态同图
    single, errs = pet.role_lib.import_processed(out2, None, "单形态测试")
    check("import single", single is not None and errs is None, "err=%r" % (errs,))
    if single:
        check("single form recorded", single.get("form") == "single"
              and pet.role_lib.path_for_full(single["id"]) is None)
        pet.apply_role(single["id"])
        check("single sprites equal", pet.form_keys == ["f0"] and len(pet.sprites) == 1)
        # v1.3.3：自定义角色程序化表情图（不再只有气泡+头顶表情）
        st = pet._state_pix("blush")
        check("custom state pix built", st is not None and st.width() > 0)
        if st is not None:
            pet._show_state("blush", 200)
            check("custom state shown",
                  pet.item.pixmap().cacheKey() == st.cacheKey()
                  and pet.item.pixmap().cacheKey() != pet.sprites["f0"]["side"].cacheKey())
            pet._state_timer.stop()
            pet._state_done()  # S1 回归：表情结束必须恢复待机贴图
            check("custom state restored",
                  pet.item.pixmap().cacheKey() == pet.sprites["f0"]["front"].cacheKey())
            # 睡眠/唤醒恢复（S1 同源回归）
            pet._show_sleep()
            pet._wake()
            check("custom sleep restored",
                  pet.item.pixmap().cacheKey() == pet.sprites["f0"]["front"].cacheKey())
        pet.apply_role("")

    # ---- 2c. 多帧素材 / 视频抽帧（v1.3.2）----
    frame_pngs = []
    for i in range(3):
        fp_src = os.path.join(_tmp, "fr%d.png" % i)
        make_test_png(fp_src, 128 + i * 8, 128 + i * 8)
        fp_out = os.path.join(_tmp, "fr%d_proc.png" % i)
        okfp, _n = pet_dialogs._prepare_role_png(fp_src, fp_out)
        check("frame prep %d" % i, okfp)
        frame_pngs.append(fp_out)
    frole, errf = pet.role_lib.import_processed(frame_pngs[0], None, "帧动画测试", frames_src=frame_pngs)
    check("import frames", frole is not None and errf is None, "err=%r" % (errf,))
    if frole:
        check("frames recorded", len(frole.get("frames", [])) == 3
              and len(pet.role_lib.frames_for(frole["id"])) == 3)
        lib3 = main.pet_resources.RoleLibrary(_tmp)
        check("reload keeps frames", len(lib3.frames_for(frole["id"])) == 3)
        pet.apply_role(frole["id"])
        # S1 回归：_wire_anim_sets 注册的必须是 QPixmap 帧集（曾误传路径字符串致帧动画全灭）
        _idle_set = pet.anim._sets.get("idle") or []
        check("frames role animates", pet._custom_role and pet.has_frames
              and len(_idle_set) == 3
              and all(isinstance(f, main.QPixmap) and not f.isNull() for f in _idle_set))
        # 中-4：帧动画角色 × 程序化表情组合（状态结束/唤醒后恢复帧循环）
        pet._show_state("cry", 100)
        check("frames role state shown", pet.anim_mode == "state"
              and pet.item.pixmap().cacheKey() == pet.state_pix["f0"]["cry"].cacheKey())
        pet._state_timer.stop()
        pet._state_done()
        check("frames role idle restored", pet.anim_mode == "idle" and pet.anim._timer.isActive())
        pet._show_sleep()
        pet._wake()
        check("frames role sleep restored", pet.anim_mode == "idle" and pet.anim._timer.isActive())
        pet.feed("小鱼干")
        t0 = time.time()
        while pet.busy and time.time() - t0 < 3:
            app.processEvents()
            time.sleep(0.02)
        check("frames feed ok", pet.form == "f0")  # 单形态帧角色：喂食循环回 f0
        pet._set_form("f0")
        fpaths = list(pet.role_lib.frames_for(frole["id"]))
        okfd, _errfd = pet.role_lib.delete(frole["id"])
        check("frames delete files", okfd and all(not os.path.exists(p) for p in fpaths))
        pet.apply_role("")
        # 高-2 回归：文件存在但无法解码 → 回退默认角色（不能静默消失）
        corrupt = os.path.join(_tmp, "roles", "corrupt.png")
        os.makedirs(os.path.dirname(corrupt), exist_ok=True)
        with open(corrupt, "wb") as fh:
            fh.write(b"not a png at all")
        # 直接塞索引（绕过 import_file 的内容校验）
        pet.role_lib._data["roles"].append({
            "id": "corrupt1", "name": "坏角色", "file": "corrupt.png",
            "form": "single", "file_full": "", "frames": [], "added": "",
        })
        pet.role_lib._save()
        pet.role_lib.set_active("corrupt1")
        pet.cfg["role"] = "corrupt1"
        pet.apply_role("corrupt1")
        check("corrupt role falls back default", not pet._custom_role
              and pet.sprites["normal"]["side"].width() > 20)
        pet.apply_role("")
        pet.role_lib.delete("corrupt1")
        # 中-1 回归：旧版超大角色加载时一次性补偿 scale（窗口不骤缩）
        big_src = os.path.join(_tmp, "big_role.png")
        make_test_png(big_src, 800, 800)
        bigrole, _errb = pet.role_lib.import_file(big_src, "超大旧角色")  # 旧版入口：不处理直接拷贝
        if bigrole:
            pet.cfg["scale"] = 1.0
            pet.cfg["scale_compensated_role"] = ""
            pet.apply_role(bigrole["id"])
            check("big role capped", pet.sprites["f0"]["side"].width() <= 512)
            check("big role scale compensated", pet.cfg.get("scale", 1.0) > 1.0,
                  "scale=%.2f" % pet.cfg.get("scale", 1.0))
            # 二次切换不重复补偿
            s_before = pet.cfg.get("scale", 1.0)
            pet.apply_role("")
            pet.apply_role(bigrole["id"])
            check("big role no re-compensate", abs(pet.cfg.get("scale", 1.0) - s_before) < 0.01)
            pet.apply_role("")
            pet.role_lib.delete(bigrole["id"])
        # 帧数边界：1 帧 / 25 帧拒绝
        rmin, emin = pet.role_lib.import_processed(frame_pngs[0], None, "边界", frames_src=[frame_pngs[0]])
        check("frames min2 rejected", rmin is None and "至少需要 2 帧" in (emin or ""), "err=%r" % (emin,))
        rmax, emax = pet.role_lib.import_processed(frame_pngs[0], None, "边界2", frames_src=[frame_pngs[0]] * 25)
        check("frames max24 rejected", rmax is None and "最多 24 帧" in (emax or ""), "err=%r" % (emax,))
    # 抽帧错误路径：单帧 GIF / 假视频
    from PySide6.QtGui import QImageWriter
    gif1 = os.path.join(_tmp, "one.gif")
    img1 = QImage(64, 64, QImage.Format.Format_ARGB32)
    img1.fill(0)
    w = QImageWriter(gif1, b"gif")
    w.write(img1)
    rawdir = tempfile.mkdtemp(prefix="role_raw_")
    raws, errg = pet_dialogs._extract_video_frames(gif1, rawdir)
    # offscreen 下 QImageWriter 写的 GIF 可能被 QImageReader 判为无效：只断言拒绝路径
    check("gif rejected", raws is None and bool(errg), "err=%r" % (errg,))
    fake = os.path.join(_tmp, "fake.mp4")
    with open(fake, "wb") as fh:
        fh.write(b"not a video")
    raws2, errv = pet_dialogs._extract_video_frames(fake, rawdir)
    check("fake video rejected", raws2 is None, "err=%r" % (errv,))
    shutil.rmtree(rawdir, ignore_errors=True)
    # 正向抽帧（真实素材；S1 回归）：视频与多帧 GIF 都要能抽出 ≥2 帧
    vid = os.path.join(HERE, "_verify_assets", "sample.mp4")
    gif3 = os.path.join(HERE, "_verify_assets", "sample.gif")
    if os.path.isfile(vid):
        rd2 = tempfile.mkdtemp(prefix="role_raw2_")
        raws3, errv2 = pet_dialogs._extract_video_frames(vid, rd2)
        check("video extract positive", raws3 is not None and len(raws3) >= 2
              and all(os.path.isfile(p) for p in raws3),
              "n=%s err=%r" % (len(raws3) if raws3 else 0, errv2))
        shutil.rmtree(rd2, ignore_errors=True)
    else:
        check("video extract positive", False, "missing _verify_assets/sample.mp4")
    if os.path.isfile(gif3):
        rd3 = tempfile.mkdtemp(prefix="role_raw3_")
        raws4, errg2 = pet_dialogs._extract_video_frames(gif3, rd3)
        check("gif extract positive", raws4 is not None and len(raws4) >= 2
              and all(os.path.isfile(p) for p in raws4),
              "n=%s err=%r" % (len(raws4) if raws4 else 0, errg2))
        shutil.rmtree(rd3, ignore_errors=True)
    else:
        check("gif extract positive", False, "missing _verify_assets/sample.gif")
    # 统一画布：同源帧（平移保留）与多图帧（居中画布）输出尺寸一致
    if os.path.isfile(vid):
        rd4 = tempfile.mkdtemp(prefix="role_prep4_")
        raws5, _e = pet_dialogs._extract_video_frames(vid, rd4)
        if raws5:
            outs, notesu = pet_dialogs._prepare_role_frames(raws5, rd4, same_size=True)
            check("union canvas uniform", outs is not None and len(outs) == len(raws5),
                  "notes=%r" % (notesu,))
            if outs:
                from PySide6.QtGui import QImage as _QI
                dims = {( _QI(p).width(), _QI(p).height()) for p in outs}
                check("union canvas same dims", len(dims) == 1, "dims=%r" % (dims,))
        shutil.rmtree(rd4, ignore_errors=True)
        # 向导接线（高-1 回归）：_pick_video → frames_video=True → _do_import 传 same_size=True
        # P1-1 起抽帧/导入走工作线程：用事件循环等待完成（最多 40s）
        from PySide6.QtWidgets import QFileDialog
        real_gofn = QFileDialog.getOpenFileName
        real_prep = pet_dialogs._prepare_role_frames
        real_warn = pet_dialogs._warn
        calls = []

        def _rec(srcs, out_dir, same_size=True, cancel=None, progress=None):
            calls.append(bool(same_size))
            return real_prep(srcs, out_dir, same_size, cancel=cancel, progress=progress)
        pet_dialogs._prepare_role_frames = _rec
        pet_dialogs._warn = lambda *a, **k: None
        QFileDialog.getOpenFileName = lambda *a, **k: (vid, "")

        def _wait_until(cond, timeout_s):
            loop = QEventLoop()

            def _tick():
                if cond():
                    loop.quit()
                else:
                    QTimer.singleShot(50, _tick)
            QTimer.singleShot(int(timeout_s * 1000), loop.quit)
            QTimer.singleShot(0, _tick)
            loop.exec()
        try:
            wdlg = pet_dialogs.RoleImportDialog(pet)
            wdlg._pick_video()
            _wait_until(lambda: wdlg._frames_video or (wdlg._worker is None and wdlg._frames_raw), 40)
            check("wizard video flag", wdlg._frames_video is True, "video=%r" % (wdlg._frames_video,))
            wdlg._do_import()
            _wait_until(lambda: wdlg.result_data() is not None or wdlg._worker is None, 40)
            dataw = wdlg.result_data()
            check("wizard union path", bool(calls) and calls[-1] is True, "calls=%r" % (calls,))
            check("wizard frames result", dataw is not None and len(dataw.get("frames", [])) >= 2)
            wdlg.close()
        except Exception as e:
            check("wizard video flow", False, repr(e))
        finally:
            QFileDialog.getOpenFileName = real_gofn
            pet_dialogs._prepare_role_frames = real_prep
            pet_dialogs._warn = real_warn
    # 多图路径：不同尺寸两帧 → 输出同尺寸（居中画布）
    rd6 = tempfile.mkdtemp(prefix="role_prep6_")
    outs_m, notes_m = pet_dialogs._prepare_role_frames([out1, out2], rd6, same_size=False)
    check("multi canvas uniform", outs_m is not None and len(outs_m) == 2, "err=%r" % (notes_m,))
    if outs_m:
        from PySide6.QtGui import QImage as _QI2
        dims_m = {(_QI2(p).width(), _QI2(p).height()) for p in outs_m}
        check("multi canvas same dims", len(dims_m) == 1, "dims=%r" % (dims_m,))
    shutil.rmtree(rd6, ignore_errors=True)

    # ---- 2d. v1.4 多形态 + 开机自启 ----
    f3 = []
    for i in range(3):
        src3 = os.path.join(_tmp, "form%d_src.png" % i)
        make_test_png(src3, 150, 150)
        outp = os.path.join(_tmp, "form%d_out.png" % i)
        pet_dialogs._prepare_role_png(src3, outp)
        f3.append(("幼体" if i == 0 else ("成体" if i == 1 else "究极体"), outp))
    r3, e3 = pet.role_lib.import_processed(f3[0][1], None, "三形态", forms_src=f3)
    check("import 3 forms", r3 is not None and e3 is None, "err=%r" % (e3,))
    if r3:
        check("3 forms recorded", len(r3.get("forms", [])) == 3)
        pet.apply_role(r3["id"])
        check("3 form keys", pet.form_keys == ["f0", "f1", "f2"])
        for expect in ("f1", "f2", "f0"):
            pet.feed("小鱼干")
            t0 = time.time()
            while pet.busy and time.time() - t0 < 3:
                app.processEvents()
                time.sleep(0.02)
            check("feed cycle -> %s" % expect, pet.form == expect)
            # bug 审查回归：贴图必须同步切到目标形态（变量断言不够）
            check("feed pix -> %s" % expect,
                  pet.item.pixmap().cacheKey() == pet.sprites[expect]["side"].cacheKey())
        # 菜单 f1→f2 切换贴图断言
        pet._set_form("f1")
        pet._set_form("f2")
        check("menu form switch pix",
              pet.item.pixmap().cacheKey() == pet.sprites["f2"]["side"].cacheKey())
        # v2.1：消化回**用户选定形态**（不再写死第一形态）
        pet.set_user_form("f2")
        pet._set_form("f2")
        pet._digest()
        check("digest back to user form", pet.form == "f2" and pet._user_form == "f2")
        pet.set_user_form("f0")
        # 删除无孤儿：全部形态文件清理
        _form_files = [os.path.join(_tmp, "roles", m["file"]) for m in pet.role_lib.form_metas(r3["id"])]
        pet.role_lib.delete(r3["id"])
        check("3-form delete no orphans", all(not os.path.exists(p) for p in _form_files))
        pet.apply_role("")
    # bug 审查回归：形态文件缺失时启动不崩（file_full 孤儿场景）
    two = []
    for i in range(2):
        ts = os.path.join(_tmp, "t%d.png" % i)
        make_test_png(ts, 120, 120)
        to = os.path.join(_tmp, "t%d_o.png" % i)
        pet_dialogs._prepare_role_png(ts, to)
        two.append(("形态%d" % (i + 1), to))
    rt, et = pet.role_lib.import_processed(two[0][1], None, "缺文件测试", forms_src=two)
    if rt:
        f1_path = os.path.join(_tmp, "roles", pet.role_lib.form_metas(rt["id"])[1]["file"])
        os.remove(f1_path)  # 模拟 file_full 孤儿
        pet.apply_role(rt["id"])
        check("missing form no crash", pet.form_keys == ["f0", "f1"]
              and set(pet.sprites.keys()) == set(pet.form_keys))
        pet.apply_role("")
        pet.role_lib.delete(rt["id"])
    # 自启失败回弹不递归（stub set_autostart 恒失败）
    class _FakeAct:
        def __init__(self):
            self.checked = False
            self.blocked = 0
        def setChecked(self, v):
            self.checked = v
        def blockSignals(self, b):
            self.blocked += 1
    _real_setauto = main.set_autostart
    _real_act = pet._autostart_act
    _bubbles2 = []
    _real_sb2 = pet.show_bubble
    pet.show_bubble = lambda t: _bubbles2.append(t)
    main.set_autostart = lambda on: (False, "模拟失败")
    pet._autostart_act = _FakeAct()
    pet._autostart_busy = False
    try:
        pet._set_autostart(True)
        check("autostart fail no recursion", pet._autostart_act.checked is False
              and any("失败" in b for b in _bubbles2))
    finally:
        main.set_autostart = _real_setauto
        pet._autostart_act = _real_act
        pet.show_bubble = _real_sb2

    # 开机自启：往返测试打到专用探针键（CI 机器上真实 Run 键可能不可写/不存在；
    # 代码路径与真实键完全一致，仅键名不同），不再触碰用户真实设置
    _real_key = main.AUTOSTART_KEY
    main.AUTOSTART_KEY = r"Software\DaFeiYuPet\CIProbe"
    try:
        main.set_autostart(False)
        check("autostart default off", main.is_autostart_enabled() is False)
        ok_a, err_a = main.set_autostart(True)
        check("autostart set on", ok_a and main.is_autostart_enabled(), "err=%r" % (err_a,))
        ok_b, _err_b = main.set_autostart(False)
        check("autostart set off", ok_b and not main.is_autostart_enabled())
        main.set_autostart(False)  # 清理探针值
    finally:
        main.AUTOSTART_KEY = _real_key

    # ---- P3 可选项 + 人设自定义：表情解析 / 人设预设 / 点击穿透遮罩 ----
    check("persona presets", set(main.PERSONA_PRESETS) == {"default", "sheshe", "tsundere"},
          sorted(main.PERSONA_PRESETS))
    _mode, _kind, _rest = main.parse_emote_tag("【happy】hi~")
    check("ai emote parse", _mode == "emote" and _kind == "heart" and _rest == "hi~",
          "mode=%r kind=%r rest=%r" % (_mode, _kind, _rest))
    try:
        pet.cfg["click_through"] = True
        pet._update_click_mask()
        _cv = getattr(pet, "_click_composite", None)
        _ok = _cv is not None and _cv.width() == pet.width() and _cv.height() == pet.height()
        if _ok:
            # 中心（身体）不透明、角落透明：命中画布与渲染变换对齐的抽样验证
            _center = _cv.pixelColor(_cv.width() // 2, _cv.height() // 2)
            _corner = _cv.pixelColor(1, 1)
            _ok = _center.alpha() > 8 and _corner.alpha() < 8
        pet.cfg["click_through"] = False
        pet._update_click_mask()
        _cleared = getattr(pet, "_click_composite", None) is None
        check("click through composite", _ok and _cleared,
              "ok=%s cleared=%s" % (_ok, _cleared))
    except Exception as e:
        check("click through composite", False, repr(e))

    # ---- P1-手感：甩抛物理开关与飞行（合成轨迹直测，无真实拖拽） ----
    try:
        # 关闭状态守卫：默认关闭时合成快速甩动不得起飞（贴边行为等价）
        pet._set_physics(False)
        _now = time.monotonic()
        _t0 = _now - 0.3
        pet._drag_samples = [(_t0 + i * 0.015, 100 + i * 10.0, 400) for i in range(21)]
        check("physics off no throw", not pet._maybe_throw() and not pet._flying)
        # 开启状态：近地放置（摩擦滑停 ~1s，规避 0.78 弹跳链 8s+ 的完全衰减）+ 手动步进
        pet._set_physics(True)
        check("physics toggle on", bool((pet.cfg.get("physics") or {}).get("enabled")))
        _scr = pet._screen_geo(pet.frameGeometry().center())
        if _scr is not None:
            pet.move(_scr.left() + 50, _scr.bottom() - pet.height())
        _now = time.monotonic()
        _t0 = _now - 0.3
        pet._drag_samples = [(_t0 + i * 0.015, pet.x() + i * 10.0, pet.y()) for i in range(21)]
        _started = pet._maybe_throw()
        check("physics throw starts", _started and pet._flying)
        if pet._flying:
            pet._flight_timer.stop()  # 手动步进期间停掉定时器，避免双驱动
            _t_end = time.monotonic() + 15.0
            while pet._flying and time.monotonic() < _t_end:
                pet._flight_tick()
                time.sleep(0.016)
            if pet._flying:
                pet._end_flight()  # 超时兜底：复位，防残留飞行定时器干扰后续检查
        check("physics flight lands", not pet._flying)
        pet._set_physics(False)
        check("physics toggle off", not bool((pet.cfg.get("physics") or {}).get("enabled")))
    except Exception as e:
        check("physics flow", False, repr(e))
        try:
            pet._set_physics(False)
            pet._end_flight()
        except Exception:
            pass  # 有意忽略：复位失败不影响后续检查

    # ---- v2.0：语音系统（默认关闭 / 配置归一化 / 片段注册） ----
    check("voice default off", pet.cfg.get("voice", {}).get("enabled") is False)
    check("voice service", hasattr(pet, "voice") and pet.voice is not None)
    _wav = os.path.join(_tmp, "t.wav")
    import wave as _wave
    with _wave.open(_wav, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(22050)
        f.writeframes(b"\x00\x00" * 100)
    _okv, _errv = pet.voice.set_clip("reply", _wav)
    check("voice clip roundtrip", _okv and pet.voice.clip("reply") is not None
          and os.path.isfile(pet.voice.clip("reply")), "err=%r" % (_errv,))
    pet.voice.set_clip("reply", None)
    check("voice clip clear", pet.voice.clip("reply") is None)
    try:
        os.remove(_wav)
    except Exception:
        pass  # 有意忽略：临时 wav 清理尽力而为

    # ---- v2.0.1：动作自定义（命名帧动作 + 程序化合成动作） ----
    check("norm animations custom key",
          set(main.pet_resources._norm_animations({"idle": ["a.png"], "dance1": ["d.png"],
                                                   "bad name": ["x.png"], "eat": ["e.png"]}))
          == {"idle", "dance1", "eat"})
    _np = main.pet_resources._norm_procs({"s": {"kind": "sway", "amp": 9, "period_ms": 1},
                                          "b": {"kind": "fly"},
                                          "n": {"kind": "nod", "amp": 0.02, "period_ms": 900},
                                          "n12": {"kind": "nod", "amp": 12.0, "period_ms": 400},
                                          "sleep": {"kind": "sway", "amp": 0.5, "period_ms": 500},
                                          "jump": {"kind": "sway"}})
    check("norm procs whitelist+clamp",
          set(_np) == {"s", "n", "n12"} and _np["s"]["amp"] == 1.0 and _np["s"]["period_ms"] == 200
          and _np["n"]["amp"] == 1.0 and _np["n"]["period_ms"] == 900
          and _np["n12"]["amp"] == 12.0)  # nod 像素口径：默认 12px 不被钳死；内建/保留名丢弃
    check("custom action name validation",
          main.pet_resources.is_valid_custom_action("dance") is True
          and main.pet_resources.is_valid_custom_action("jump") is False
          and main.pet_resources.is_valid_custom_action("interval_ms") is False
          and main.pet_resources.is_valid_custom_action("idle") is False)
    # 构造带自定义动作的角色：dance 帧动作（2 帧）+ sway 合成动作（短周期便于快速验证）
    _ca_dir = os.path.join(_tmp, "roles")
    os.makedirs(_ca_dir, exist_ok=True)
    for _fn in ("ca_base.png", "ca_d1.png", "ca_d2.png", "ca_e0.png", "ca_e1.png"):
        make_test_png(os.path.join(_ca_dir, _fn), 96, 96)
    pet.role_lib._data["roles"].append({
        "id": "ca1", "name": "动作自定义", "file": "ca_base.png",
        "form": "single", "file_full": "", "frames": ["ca_base.png"], "added": "",
        "forms": [{"name": "常态", "file": "ca_base.png",
                   "animations": {"idle": ["ca_base.png"],
                                  "dance": ["ca_d1.png", "ca_d2.png"],
                                  "eat": ["ca_e0.png", "ca_e1.png"]},
                   "procs": {"sway": {"kind": "sway", "amp": 0.06, "period_ms": 200}}}],
    })
    pet.role_lib._save()
    pet.apply_role("ca1")
    check("custom role applied", pet._custom_role and pet.cfg.get("role") == "ca1")
    check("custom actions listed", ("dance", "frames") in pet.custom_actions()
          and ("sway", "proc") in pet.custom_actions())
    check("cur procs exposed", pet._cur_procs().get("sway", {}).get("kind") == "sway")
    _dset = pet.anim._sets.get("dance") or []
    check("custom frame action wired", len(_dset) == 2
          and all(isinstance(f, main.QPixmap) and not f.isNull() for f in _dset))
    # 菜单动态列出自定义动作
    class _MenuCA(main.QMenu):
        def exec(self, *_a, **_k):
            self._captured = self.actions()
            return None
    _real_menu_ca = main.QMenu
    main.QMenu = _MenuCA
    _cap_ca = None
    try:
        pet._open_menu(QPoint(100, 100))
        import gc as _gc
        for _o in _gc.get_objects():
            if isinstance(_o, _MenuCA) and getattr(_o, "_captured", None) is not None:
                _cap_ca = _o
                break
    except Exception as e:
        check("menu custom actions build", False, repr(e))
    finally:
        main.QMenu = _real_menu_ca
    _tca = []
    if _cap_ca is not None:
        def _walk_ca(acts):
            for _a in acts:
                if _a.text():
                    _tca.append(_a.text())
                _m2 = _a.menu()
                if _m2 is not None:
                    _walk_ca(_m2.actions())
        _walk_ca(_cap_ca._captured)
    # 捕获失败必须 FAIL（守卫式跳过会让护栏静默失明）
    check("menu lists custom actions",
          _cap_ca is not None and "✦ dance" in _tca and "✦ sway（合成）" in _tca,
          "texts=%r" % (_tca,))
    # 播放：命名帧动作 → 播完自动回待机
    pet.actions.play_action("dance")
    check("frame action plays", pet.anim_mode == "state" and pet.anim._timer.isActive())
    _t0 = time.time()
    while pet.anim_mode == "state" and time.time() - _t0 < 3:
        app.processEvents()
        time.sleep(0.02)
    check("frame action back to idle", pet.anim_mode == "idle")
    # 播放：程序化合成动作 → 变换生效，播完复位并回待机
    pet.actions.play_action("sway")
    check("proc action starts", pet.anim_mode == "state")
    _t0 = time.time()
    _moved = False
    while time.time() - _t0 < 1.2:
        app.processEvents()
        time.sleep(0.02)
        if abs(pet.squash_x - 1.0) > 1e-4:
            _moved = True
    check("proc transform applied", _moved)
    check("proc resets to idle", pet.anim_mode == "idle" and abs(pet.squash_x - 1.0) < 1e-6
          and abs(pet.squash_y - 1.0) < 1e-6 and pet._proc_offset_y == 0)
    # 审查修复回归：合成动作播放中喂食 → 吃帧收尾不被顶掉，busy 必须释放
    pet.actions.play_action("sway")
    pet.feed("小鱼干")
    _t0 = time.time()
    while pet.busy and time.time() - _t0 < 6:
        app.processEvents()
        time.sleep(0.02)
    check("feed during proc releases busy", not pet.busy and pet.anim_mode == "idle"
          and abs(pet.squash_x - 1.0) < 1e-6 and pet._proc_offset_y == 0,
          "busy=%r anim=%r sx=%.4f oy=%.4f" % (pet.busy, pet.anim_mode, pet.squash_x,
                                               pet._proc_offset_y))
    # 审查修复回归：角色切换立即停掉在途合成动作（新角色无残留振荡）
    pet.actions.play_action("sway")
    pet.apply_role("")
    check("role switch stops proc", pet._tween_anim is None
          and abs(pet.squash_x - 1.0) < 1e-6 and pet._proc_offset_y == 0)
    # 清理：删除自定义动作角色，恢复默认
    _okdel, _erdel = pet.role_lib.delete("ca1")
    check("custom role cleanup", _okdel and pet.role_lib.get("ca1") is None, "err=%r" % (_erdel,))
    pet.apply_role("")
    check("restore default after custom", not pet._custom_role and pet.cfg.get("role") == "")

    # ---- v2.0.2：行为自定义系统 + 断点#12 ----
    import pet_behaviors  # noqa: E402
    check("behavior service created", pet.behaviors is not None)
    _bhv, _bhv_err = pet.behaviors.add("hello", [
        {"act": "say", "text": "行为测试"}, {"act": "wait", "ms": 200},
        {"act": "emote", "kind": "heart"}])
    check("behavior add+get", _bhv is not None and not _bhv_err
          and pet.behaviors.get(_bhv["id"])["name"] == "hello", "err=%r" % (_bhv_err,))
    # 序列执行：say 气泡捕获 + 序列走完自清（不残留 _behavior_seq）
    _bubbles = []
    _real_bubble = pet.show_bubble
    pet.show_bubble = lambda t: _bubbles.append(t)
    try:
        pet._run_behavior(_bhv["id"])
        check("behavior seq starts", pet._behavior_seq is not None)
        _t0 = time.time()
        while pet._behavior_seq is not None and time.time() - _t0 < 4:
            app.processEvents()
            time.sleep(0.02)
    finally:
        pet.show_bubble = _real_bubble
    check("behavior seq plays+ends", pet._behavior_seq is None
          and any("行为测试" in b for b in _bubbles), "bubbles=%r" % (_bubbles,))
    # 待机行为：默认关闭（现行为等价）；配置后空闲超时触发
    check("behavior idle default off", pet.behaviors.idle(lambda: pet.cfg) is None)
    pet.cfg["idle_behavior"] = _bhv["id"]      # 旧键兼容：自动进 idle_actions
    pet.cfg["idle_trigger_delay"] = 5          # v2.1：触发 B 延迟（新键）
    pet.cfg["idle_actions"] = []               # 清掉上面 v2.1 段落的动作，隔离验证本条
    pet._last_activity = time.monotonic() - 10
    pet._last_idle_at = 0.0                    # 清掉去重窗口（隔离验证本场景）
    pet.anim_mode = "idle"
    pet.maybe_idle_behavior()
    check("idle behavior triggers", pet._behavior_seq is not None)
    pet._behavior_seq = None
    pet._idle_active = False
    # 待机触发不得重置 _last_activity（入睡计时不受影响 → 行为后仍会入睡）
    pet._last_activity = time.monotonic() - 70  # 已超入睡阈值
    _act_before = pet._last_activity
    pet._last_idle_at = 0.0
    pet.anim_mode = "idle"
    pet.maybe_idle_behavior()
    check("idle behavior keeps sleep timer", pet._last_activity == _act_before
          and pet._behavior_seq is not None)
    pet._behavior_seq = None
    pet._idle_active = False
    pet.cfg["idle_behavior"] = ""
    pet.cfg["idle_trigger_delay"] = pet_behaviors.DEFAULT_BEHAVIOR_CFG["idle_trigger_delay"]
    pet.cfg["idle_actions"] = []
    # 行为级 off 等价：默认配置下 idle_tick 仍按旧逻辑入睡（行为系统关闭=现行为）
    _sleep_calls = []
    _real_show_sleep = pet._show_sleep
    pet._show_sleep = lambda: _sleep_calls.append(1)
    pet._last_activity = time.monotonic() - 70
    pet.anim_mode = "idle"
    # v2.2.5：饭点小盹/安静期/消化窗口都会让 idle_tick 提前 return（节拍不插动作）——
    # 本项验的是"睡眠判定照常"，先把这三道新门控清掉
    if getattr(pet, "_digest_timer", None) is not None:
        pet._digest_timer.stop()
    pet._digest_zzz_timer.stop()
    pet._nap_zzz_timer.stop()
    try:
        pet.actions.idle_tick()
    finally:
        pet._show_sleep = _real_show_sleep
    check("idle tick off-equivalent sleep", len(_sleep_calls) == 1, "n=%d" % len(_sleep_calls))
    # 配置归一化：越界/坏值钳回默认口径
    _cfg_saved = dict(pet.cfg)
    pet.cfg["idle_trigger_delay"] = 99999      # v2.1：新键是唯一来源（旧键自动同步）
    pet.cfg["transform_seconds"] = "abc"
    main.save_config(pet.cfg)
    _cfg_n = main.load_config()
    check("config behavior clamp",
          _cfg_n.get("idle_trigger_delay") == 60   # 上界=入睡阈值，防死配置
          and _cfg_n.get("idle_behavior_seconds") == 60  # 旧键同步（旧版读取路径兼容）
          and _cfg_n.get("transform_seconds") == pet_behaviors.DEFAULT_BEHAVIOR_CFG["transform_seconds"],
          "s=%r t=%r" % (_cfg_n.get("idle_trigger_delay"), _cfg_n.get("transform_seconds")))
    main.save_config(_cfg_saved)
    pet.cfg = dict(_cfg_saved)
    # 断点#12：双形态角色（睡觉/变身/不参与喂食标记；字符串 "false" 不算真）
    _cb_dir = os.path.join(_tmp, "roles")
    os.makedirs(_cb_dir, exist_ok=True)
    for _fn in ("cb_a.png", "cb_b.png"):
        make_test_png(os.path.join(_cb_dir, _fn), 96, 96)
    pet.role_lib._data["roles"].append({
        "id": "cb1", "name": "行为角色", "file": "cb_a.png",
        "form": "dual", "file_full": "", "frames": ["cb_a.png"], "added": "",
        "forms": [
            {"name": "常态", "file": "cb_a.png", "sleep_form": "false"},
            {"name": "睡觉/变身", "file": "cb_b.png", "sleep_form": True,
             "transform_form": True, "no_feed": True},
        ],
    })
    pet.role_lib._save()
    pet.apply_role("cb1")
    _flags = pet.role_lib.form_role_flags("cb1")
    check("form flags normalized", len(_flags) == 2
          and _flags[0] == {"sleep_form": False, "transform_form": False, "no_feed": False}
          and _flags[1] == {"sleep_form": True, "transform_form": True, "no_feed": True},
          "flags=%r" % (_flags,))
    check("transform form entry", pet.has_transform_form is True)
    # 变身：切到标记形态，_end_transform 回原形态
    pet._do_transform()
    check("transform switches", pet.form == "f1" and pet._transform_home == "f0")
    pet._end_transform()
    check("transform returns", pet.form == "f0" and pet._transform_home is None)
    # 睡觉形态：入睡切到标记形态，醒来回原形态
    pet._show_sleep()
    check("sleep form switch", pet.form == "f1" and pet._sleep_home == "f0")
    pet._wake()
    check("wake returns home", pet.form == "f0" and pet._sleep_home is None and not pet._sleeping)
    # 不参与喂食：气泡明示且 busy 不置位
    pet._set_form("f1")
    _bubbles2 = []
    pet.show_bubble = lambda t: _bubbles2.append(t)
    pet.feed("小鱼干")
    pet.show_bubble = _real_bubble
    check("no_feed rejects", not pet.busy and bool(_bubbles2),
          "bubbles=%r busy=%r" % (_bubbles2, pet.busy))
    pet._set_form("f0")
    # v2.1.3 回归：待机不得吞掉变身/睡眠形态（用户实测反馈"待机还会吞其他形态"）
    pet.cfg["idle_form"] = "f1"          # 待机形态与变身形态同键不影响本检查（下面用 f0 区分）
    pet.cfg["idle_trigger_delay"] = 3
    pet._user_form = "f0"
    pet._set_form("f0", display_only=True)
    # 场景 1：变身进行中 → 到点的待机不得开始（_idle_ready 必须让位）
    pet._do_transform()
    _t_form = pet.form
    pet._last_activity = 0.0
    pet._last_idle_at = 0.0
    pet.maybe_idle_behavior()
    check("idle yields to transform", pet.form == _t_form and pet._idle_form_active is False
          and pet._idle_active is False,
          "form=%r idle_form=%r" % (pet.form, pet._idle_form_active))
    pet._end_transform()
    check("transform back after idle tick", pet.form == "f0", "form=%r" % pet.form)
    # 场景 2：待机形态展示期 → 用户变身 → 变身结束必须回用户形态（f0），不是待机形态
    # （需要一个与用户形态/变身形态都不同的第三形态来扮演 idle_form）
    pet.role_lib._data["roles"][-1]["forms"].append(
        {"name": "第三形态", "file": "cb_a.png"})
    pet.role_lib._save()
    pet.apply_role("cb1")
    check("third form available", "f2" in pet.sprites and "f2" in pet.form_keys,
          "forms=%r" % (pet.form_keys,))
    pet._user_form = "f0"
    pet._idle_form_active = True
    pet._set_form("f2", display_only=True)     # 模拟待机形态已覆盖（f2 = idle_form）
    pet._do_transform()
    check("transform interrupts idle form",
          pet.form == "f1" and pet._idle_form_active is False and pet._transform_home == "f0",
          "form=%r idle_form=%r home=%r" % (pet.form, pet._idle_form_active, pet._transform_home))
    pet._end_transform()
    check("transform ends at user form", pet.form == "f0", "form=%r" % pet.form)
    # 场景 3：待机形态展示期 → 入睡 → 睡形态；醒来回用户形态
    pet._idle_form_active = True
    pet._set_form("f0", display_only=True)
    pet._show_sleep()
    check("sleep interrupts idle", pet._sleeping and pet._idle_form_active is False,
          "sleeping=%r idle_form=%r" % (pet._sleeping, pet._idle_form_active))
    pet._wake()
    check("wake after idle sleep", pet.form == "f0" and not pet._sleeping, "form=%r" % pet.form)
    # v2.1.6 回归：待机形态展示期里喂食必须"先结束待机展示再按用户形态推进形态"
    # 需要第四个形态专门当"待机形态"（f1 是 no_feed 不能当展示期验证对象：喂食会被正当拒绝）
    pet.role_lib._data["roles"][-1]["forms"].append(
        {"name": "待机形态", "file": "cb_a.png"})
    pet.role_lib._save()
    pet.apply_role("cb1")
    check("fourth form available", "f3" in pet.form_keys, "forms=%r" % (pet.form_keys,))
    # 用 f3（无标记）当待机形态：喂食必须逃出展示期并把形态推进到 f2（跳过 no_feed 的 f1）
    pet.cfg["idle_form"] = "f3"
    pet._user_form = "f0"
    pet._set_form("f0", display_only=True)
    pet._idle_form_active = False
    pet._start_idle("idle")                  # 待机形态展示期（form=f3）
    _idle_disp_form = pet.form
    check("idle display shows idle form", _idle_disp_form == "f3" and pet._idle_form_active is True)
    pet.feed("小鱼干")
    check("feed escapes idle display",
          pet.form == "f2" and pet._idle_form_active is False,
          "form=%r idle_form=%r（应为 f2：按用户形态 f0 推进并跳过 no_feed 的 f1）"
          % (pet.form, pet._idle_form_active))
    _full2 = pet.form
    pet._eat_done("test")
    pet._touch_activity()                    # 点一下：不得把吃饱形态拉回用户形态
    pet._wake()
    pet._on_voice_finished("d", "")
    check("full form survives interactions", pet.form == _full2, "form=%r" % pet.form)
    pet._digest_timer.stop()
    pet._digest()
    check("digest back to user form", pet.form == "f0", "form=%r" % pet.form)
    pet.cfg.pop("idle_form", None)
    # v2.1.5 回归：消化窗口（吃饱形态保留期）内待机不得开始，否则"吃饱形态被待机吞了"
    pet.cfg["idle_form"] = "f1"
    pet._user_form = "f0"
    pet._set_form("f0", display_only=True)
    pet._idle_form_active = False
    pet.feed("小鱼干")                       # 进入吃饱形态 + 消化定时器
    _full_form = pet.form
    check("feed enters full form", _full_form != "f0", "form=%r" % (pet.form,))
    check("digest pending", pet._digest_pending() is True)
    check("idle blocked while digesting", pet._idle_ready() is False)
    pet._last_activity = 0.0                 # 无交互触发条件满足
    pet._last_idle_at = 0.0
    pet.maybe_idle_behavior()
    check("idle not swallow full form",
          pet.form == _full_form and pet._idle_form_active is False,
          "form=%r idle_form=%r" % (pet.form, pet._idle_form_active))
    pet._eat_done("test")                    # 吃帧收尾（busy 释放）
    pet._digest_timer.stop()                 # 模拟定时器到点（单发触发后本就 inactive）
    pet._digest()                            # 消化到点：回用户形态
    check("digest returns user form",
          pet.form == "f0" and pet._idle_form_active is False and not pet._digest_pending(),
          "form=%r idle_form=%r" % (pet.form, pet._idle_form_active))
    pet.cfg.pop("idle_form", None)
    # 场景 4：待机动作列表为空（只有形态）→ 展示期必须有上限，不能永久挂着 idle_form
    _acts_backup = list(pet.cfg.get("idle_actions") or [])
    pet.cfg["idle_form"] = "f1"
    pet.cfg["idle_actions"] = []
    pet._user_form = "f0"
    pet._set_form("f0", display_only=True)
    pet._idle_form_active = False
    pet._idle_active = False
    pet._start_idle("idle")
    check("form-only idle bounded",
          pet._idle_form_active is True and pet._idle_hold_timer is not None
          and pet._idle_hold_timer.isActive(),
          "idle_form=%r timer=%r" % (pet._idle_form_active, pet._idle_hold_timer))
    pet._idle_end()  # 等价于展示期到点：必须回到用户形态并清掉定时器
    check("form-only idle restores",
          pet.form == "f0" and pet._idle_form_active is False
          and pet._idle_hold_timer is None,
          "form=%r idle_form=%r timer=%r"
          % (pet.form, pet._idle_form_active, pet._idle_hold_timer))
    # 场景 5：吃饱消化（_digest）不得顶掉睡眠/变身形态（各自有回位路径）
    pet._user_form = "f0"
    pet._set_form("f0", display_only=True)
    pet._show_sleep()
    _sleep_form = pet.form
    pet._digest()
    check("digest keeps sleep form", pet.form == _sleep_form and pet._sleeping,
          "form=%r sleep_form=%r" % (pet.form, _sleep_form))
    pet._wake()
    pet._set_form("f0", display_only=True)
    pet._do_transform()
    _t_form2 = pet.form
    pet._digest()
    check("digest keeps transform form", pet.form == _t_form2 and pet._transform_home == "f0",
          "form=%r home=%r" % (pet.form, pet._transform_home))
    pet._end_transform()
    check("digest after transform back", pet.form == "f0", "form=%r" % pet.form)
    pet.cfg["idle_actions"] = _acts_backup
    pet.cfg.pop("idle_form", None)
    pet.cfg["idle_trigger_delay"] = _cfg_saved.get("idle_trigger_delay", 8)
    # 行为设置对话框冒烟
    try:
        _bd = pet_dialogs.BehaviorDialog(pet, pet.behaviors)
        _bd.show()
        app.processEvents()
        _bd.close()
        check("behavior dialog smoke", True)
    except Exception as e:
        check("behavior dialog smoke", False, repr(e))
    # 清理
    pet.apply_role("")
    pet.role_lib.delete("cb1")
    pet.behaviors.delete(_bhv["id"])

    # ---- v2.0.3：角色导出/导入（分享包） ----
    import pet_export  # noqa: E402
    _mexp, _eexp = pet_export.build_manifest(
        {"id": "x1", "name": "x", "file": "a.png", "form": "single",
         "frames": ["a.png"], "added": ""},
        [], {"api_key": "TOPSECRET", "voice": {"enabled": True}, "city": "上海"})
    check("export manifest excludes secrets",
          _mexp is not None and "TOPSECRET" not in main.json.dumps(_mexp, ensure_ascii=False)
          and "api_key" not in _mexp["config"] and "voice" in _mexp["config"]
          and "city" not in _mexp["config"], "err=%r" % (_eexp,))
    check("export rejects default role",
          pet_export.export_bundle(pet.role_lib, pet.behaviors, pet.cfg,
                                   os.path.join(_tmp, "nope.zip"))[0] is False)
    # 构造可导出角色 + 行为 → 导出 → 导入到本库（真实 handler 数据路径）
    _exp_dir = os.path.join(_tmp, "roles")
    os.makedirs(_exp_dir, exist_ok=True)
    for _fn in ("ex_a.png", "ex_b.png"):
        make_test_png(os.path.join(_exp_dir, _fn), 96, 96)
    pet.role_lib._data["roles"].append({
        "id": "ex1", "name": "导出角色", "file": "ex_a.png",
        "form": "dual", "file_full": "", "frames": ["ex_a.png"], "added": "",
        "forms": [{"name": "常态", "file": "ex_a.png"},
                  {"name": "吃饱", "file": "ex_b.png"}],
    })
    pet.role_lib._save()
    pet.apply_role("ex1")
    _eb, _ = pet.behaviors.add("bundlebhv", [{"act": "say", "text": "分享行为"}])
    _zip_path = os.path.join(_tmp, "share.dfypet.zip")
    _okx, _errx = pet_export.export_bundle(pet.role_lib, pet.behaviors, pet.cfg, _zip_path)
    check("bundle export ok", _okx, "err=%r" % (_errx,))
    import zipfile as _zf
    _namesx = []
    if _okx:
        with _zf.ZipFile(_zip_path) as _z:
            _namesx = _z.namelist()
    check("bundle contains assets",
          "manifest.json" in _namesx and any(n.startswith("roles/ex_") for n in _namesx),
          "names=%r" % (_namesx[:6],))
    # 导入到本库（新 id 不覆盖）：素材/行为/配置落地
    _cfg_before = dict(pet.cfg)
    pet.cfg["api_key"] = "KEEP-SECRET"
    _resx, _errx = pet_export.import_bundle(pet.role_lib, pet.behaviors, pet.cfg, _zip_path)
    check("bundle import ok", _resx is not None and not _errx and _resx["role_id"] != "ex1",
          "err=%r" % (_errx,))
    if _resx is not None:
        _r2 = pet.role_lib.get(_resx["role_id"])
        check("imported role files exist",
              _r2 is not None and os.path.isfile(pet.role_lib.resolve(_r2["file"])),
              "file=%r" % (_r2.get("file") if _r2 else None,))
        check("import applies cfg and keeps secrets",
              pet.cfg.get("api_key") == "KEEP-SECRET"
              and any(b["name"] == "bundlebhv" for b in pet.behaviors.list()),
              "cfg_keys=%r" % (sorted(pet.cfg.keys()),))
    pet.cfg["api_key"] = _cfg_before.get("api_key", "")
    # 缺素材包明确拒绝
    _badzip = os.path.join(_tmp, "bad.dfypet.zip")
    with _zf.ZipFile(_badzip, "w") as _z:
        _z.writestr("manifest.json", main.json.dumps(
            {"format": pet_export.BUNDLE_FORMAT,
             "role": {"id": "bb", "file": "gone.png"}}, ensure_ascii=False))
    _rb, _eb2 = pet_export.import_bundle(pet.role_lib, pet.behaviors, pet.cfg, _badzip)
    check("bundle missing asset rejects", _rb is None and "缺失" in (_eb2 or ""),
          "err=%r" % (_eb2,))
    # 清理
    pet.apply_role("")
    pet.role_lib.delete("ex1")
    if _resx is not None:
        pet.role_lib.delete(_resx["role_id"])
        for _bid in _resx.get("behavior_map", {}).values():
            pet.behaviors.delete(_bid)  # 导入的行为副本同样清掉，防脏状态干扰后续检查
    pet.behaviors.delete(_eb["id"])

    # ---- v2.0.4：其他模型 API（服务商预设 + 错误归类 + 连通性测试） ----
    import pet_chat as _pc
    # 防回归：version_info.txt 与 main.VERSION 必须同步（v2.0.2/2.0.3 曾漏更 About 版本）
    with open(os.path.join(HERE, "version_info.txt"), "r", encoding="utf-8") as _vf:
        _vraw = _vf.read()
    check("version files synced",
          ("FileVersion', '%s'" % main.VERSION) in _vraw
          and ("ProductVersion', '%s'" % main.VERSION) in _vraw)
    check("api error classify",
          "密钥" in _pc.explain_api_error(401)
          and "额度" in _pc.explain_api_error(402)
          and "地区" in _pc.explain_api_error(403, "country not supported")
          and "模型名" in _pc.explain_api_error(404)
          and "限流" in _pc.explain_api_error(429)
          and "开小差" in _pc.explain_api_error(500))
    check("api providers presets",
          all((_pc.AI_PROVIDERS.get(p) or {}).get("base_url")
              and (_pc.AI_PROVIDERS.get(p) or {}).get("model")
              for p in _pc.AI_PROVIDERS if p != "custom")
          and "custom" in _pc.AI_PROVIDERS
          and len([p for p in _pc.AI_PROVIDERS if p != "custom"]) >= 14)
    check("api defaults single source",
          _pc.DEFAULT_MODEL == _pc.AI_PROVIDERS["deepseek"]["model"]
          and _pc.DEFAULT_BASE_URL == _pc.AI_PROVIDERS["deepseek"]["base_url"])
    # 127.0.0.1:1 回环端口：REFUSED 即时失败；防火墙 DROP 也 ≤1s 超时，不依赖外网
    check("api connection unreachable",
          _pc.test_api_connection("http://127.0.0.1:1", "m", "k", timeout=1)[0] is False)
    try:
        _aid = pet_dialogs.AISettingsDialog(pet)
        _aid.show()
        app.processEvents()
        _aid.close()
        check("ai settings dialog smoke", True)
    except Exception as e:
        check("ai settings dialog smoke", False, repr(e))

    # ---- v2.0.5：闹钟系统（到点提醒 + 自定义铃声 + 语音提醒） ----
    import pet_alarm as _pa
    check("alarm service created", pet.alarms is not None)
    _alm, _aerr = pet.alarms.add("06:00", "早起")
    check("alarm add+get", _alm is not None and not _aerr
          and pet.alarms.get(_alm["id"])["time"] == "06:00", "err=%r" % (_aerr,))
    check("alarm time validation",
          _pa.valid_time("07:30") and _pa.valid_time("23:59")
          and not _pa.valid_time("24:00") and not _pa.valid_time("7:5"))
    check("alarm due pure",
          len(_pa.due_alarms([{"id": "x", "time": "06:00", "enabled": True,
                               "last_fired_date": ""}], "06:01", "2026-09-30")) == 1
          and _pa.due_alarms([{"id": "x", "time": "06:00", "enabled": True,
                               "last_fired_date": "2026-09-30"}], "06:01", "2026-09-30") == [])
    # 当日去重：mark_fired 后同日不再响
    pet.alarms.mark_fired(_alm["id"], _pa.today_str())
    check("alarm fired dedup",
          pet.alarms.get(_alm["id"])["last_fired_date"] == _pa.today_str()
          and not _pa.due_alarms(pet.alarms.list(), "23:59", _pa.today_str()))
    # 自定义铃声导入（wav）
    _ring = os.path.join(_tmp, "ring.wav")
    make_test_wav(_ring)
    _rfn, _rerr = pet.alarms.import_ringtone(_ring)
    check("alarm ringtone import", _rfn is not None and not _rerr
          and pet.alarms.ringtone_path(_rfn) is not None, "err=%r" % (_rerr,))
    # 分享包：manifest 携带闹钟设置（铃声文件不随包）
    _malm, _ealm = pet_export.build_manifest(
        {"id": "x1", "name": "x", "file": "a.png", "form": "single",
         "frames": ["a.png"], "added": ""},
        [], {}, [{"time": "06:00", "label": "早起", "enabled": True}])
    check("bundle carries alarms", isinstance(_malm.get("alarms"), list)
          and _malm["alarms"][0]["time"] == "06:00", "err=%r" % (_ealm,))
    # 导入闹钟设置：id 换新、停用状态保留、铃声缺失明确警告
    _awarns = pet._apply_imported_alarms(
        [{"time": "07:00", "label": "导入闹钟", "enabled": False, "ringtone": "x.wav"}])
    _aimp = [a for a in pet.alarms.list() if a["label"] == "导入闹钟"]
    check("import applies alarms", len(_aimp) == 1 and _aimp[0]["enabled"] is False
          and any("铃声不在包内" in w for w in _awarns), "warns=%r" % (_awarns,))
    # 闹钟对话框冒烟
    try:
        _adlg = pet_dialogs.AlarmDialog(pet, pet.alarms)
        _adlg.show()
        app.processEvents()
        _adlg.close()
        check("alarm dialog smoke", True)
    except Exception as e:
        check("alarm dialog smoke", False, repr(e))
    # 清理
    for _aid2 in [a["id"] for a in pet.alarms.list()]:
        pet.alarms.delete(_aid2)

    # ---- v2.1：台词库 / 声音素材 / 配音系统 / 待机系统 ----
    import pet_voice as _pv
    check("lines lib seeded", pet.lines_lib.count() > 30)
    _ln, _lerr = pet.lines_lib.add("v2.1 测试台词", "happy", "r_x", "v_x")
    check("line add/save", _ln is not None and not _lerr
          and pet.lines_lib.save(_ln["id"], text="改过了")[0] is True
          and pet.lines_lib.get(_ln["id"])["text"] == "改过了", "err=%r" % (_lerr,))
    _dlg1, _derr = pet.lines_lib.add_dialogue("v2.1 对白", [_ln["id"]])
    check("dialogue crud", _dlg1 is not None and not _derr
          and [x["text"] for x in pet.lines_lib.dialogue_lines(_dlg1["id"])] == ["改过了"],
          "err=%r" % (_derr,))
    _badref = pet.lines_lib.validate_references(lambda s: False, lambda s: False)
    check("validate references", any(x["line_id"] == _ln["id"] for x in _badref)
          and "角色不存在" in _badref[0]["reason"])
    _scan = pet._scan_invalid_refs(notify=False)
    check("scan invalid refs ui", isinstance(_scan, list) and len(_scan) >= 1)
    # 声音素材库（与音效片段分开）
    _ref_wav = os.path.join(_tmp, "v21_ref.wav")
    make_test_wav(_ref_wav)
    _asset, _aerr = pet.voice_assets.import_file(_ref_wav, "v21 音色")
    check("voice asset import", _asset is not None and not _aerr
          and pet.voice_assets.asset_path(_asset["id"]) is not None, "err=%r" % (_aerr,))
    _infos = _pv.backend_infos()
    check("voice backends pluggable", len(_infos) >= 7
          and {i["id"] for i in _infos} >= {"gpt_sovits", "f5_tts", "cosyvoice",
                                            "minimax", "elevenlabs"})
    check("voice bind+resolve", pet.voice.bind_voice("r_bind", _asset["id"])[0] is True
          and pet.voice.resolve_voice("r_bind", None)[0] == _asset["id"]
          and pet.voice.resolve_voice("r_unbound", None)[0] == "")
    check("voice ready gate", pet.voice.check_ready()[0] is False  # 默认关闭：阻止播放并给原因
          and bool(pet.voice.check_ready()[1]))
    pet.voice.unbind_voice("r_bind")
    # S1 回归：切后端保存后，其它后端的 Key 与参数必须原样保留（此前会被清空/串台）
    _voice_backup = dict(pet.cfg.get("voice") or {})
    try:
        _vd = pet_dialogs.VoiceDialog(pet)
        check("voice dialog local group", hasattr(_vd, "_g_local") and hasattr(_vd, "_lcmd")
              and hasattr(_vd, "_lauto"))
        # 走真实交互路径：先在控件里改 GPT-SoVITS 地址 → 切到 MiniMax 填 Key → 切回来保存
        _vd._backend.setCurrentIndex(_vd._backend.findData("gpt_sovits"))
        _vd._param_widgets["base_url"][1].setText("http://192.168.1.9:9880")
        _vd._backend.setCurrentIndex(_vd._backend.findData("minimax"))
        _vd._key.setText("MM-KEY")
        _vd._key_edited.add("minimax")
        _vd._backend.setCurrentIndex(_vd._backend.findData("gpt_sovits"))
        _vd._save(silent=True)
        _v = pet.cfg.get("voice") or {}
        check("voice save isolates backends",
              (_v.get("backend_keys") or {}).get("minimax") == "MM-KEY"
              and ((_v.get("backend_params") or {}).get("gpt_sovits") or {}).get(
                  "base_url") == "http://192.168.1.9:9880",
              "keys=%r url=%r" % ((_v.get("backend_keys") or {}).get("minimax"),
                                  ((_v.get("backend_params") or {}).get("gpt_sovits")
                                   or {}).get("base_url")))
        _vd.close()
    except Exception as e:
        check("voice save isolates backends", False, repr(e))
    finally:
        pet.cfg["voice"] = _pv.normalize_voice(_voice_backup)
        main.save_config(pet.cfg)
    # S2 回归：只有旧键 idle_behavior_seconds 的配置文件，启动后必须迁进新键（不被默认值吃掉）
    _cfg_backup2 = dict(pet.cfg)
    try:
        with open(main.CONFIG_PATH, "w", encoding="utf-8") as _f:
            json.dump({"schema_version": 2, "idle_behavior_seconds": 12}, _f,
                      ensure_ascii=False)
        _loaded = main.load_config()
        check("legacy idle seconds migrate", _loaded.get("idle_trigger_delay") == 12,
              "got=%r" % (_loaded.get("idle_trigger_delay"),))
    except Exception as e:
        check("legacy idle seconds migrate", False, repr(e))
    finally:
        pet.cfg.update(_cfg_backup2)
        main.save_config(pet.cfg)
    # v2.1.2 回归：空台词池不得崩（此前 random.choice([]) 会弹模态错误框，每轮复发）
    _pool_backup = pet.lines_pools
    try:
        pet.lines_pools = {"idle": [], "greedy": [], "happy": [], "petting": []}
        _fb = pet._pick_line(("idle", "greedy"), fallback="……")
        check("empty line pool safe", _fb == "……")
    except Exception as e:
        check("empty line pool safe", False, repr(e))
    finally:
        pet.lines_pools = _pool_backup
    # v2.1.2 回归：情绪台词删光后不得复活（库可用时不回落内置常量）
    try:
        _mood_ids = [x["id"] for x in pet.lines_lib.lines("mood_puzzled")]
        pet.lines_lib.delete_many(_mood_ids)
        import pet_lines as _pl2
        _mood_gone = pet._mood_line("mood_puzzled", _pl2.LINES_MOOD_PUZZLED) == ""
        pet.lines_lib.restore_builtins()  # 恢复内置（清删除名单）
        _mood_back = pet._mood_line("mood_puzzled", _pl2.LINES_MOOD_PUZZLED) != ""
        check("mood deletion not revived", _mood_gone and _mood_back,
              "gone=%r back=%r" % (_mood_gone, _mood_back))
    except Exception as e:
        check("mood deletion not revived", False, repr(e))
    # v2.1.2：免深拷贝取词接口存在且与 deepcopy 版一致（文档声称的性能项必须有实现）
    try:
        _a = pet.lines_lib.texts_by_category("sajiao")
        _b = pet.lines_lib.by_category("sajiao")
        check("texts_by_category exists", _a == _b and isinstance(_a, list))
    except Exception as e:
        check("texts_by_category exists", False, repr(e))
    # v2.1.1 回归：本地后端启动器（默认不自动启动 = 和以前一样；手动可启动；云端后端拒绝启动）
    _lsvc = pet.cfg.get("voice", {}).get("local_services") or {}
    check("local service default off",
          _lsvc.get("gpt_sovits", {}).get("auto_start") is False
          and _lsvc.get("gpt_sovits", {}).get("kill_on_exit") is True
          and set(_lsvc) == {"gpt_sovits", "f5_tts", "cosyvoice"})
    check("launcher empty cmd rejected",
          pet.voice.start_backend("gpt_sovits")[0] is False
          and pet.voice.start_backend("minimax")[0] is False)  # 云端：不需要启动
    check("launcher status shape", isinstance(pet.voice.launch_status(), dict)
          and "running" in pet.voice.launch_status())
    # S3 回归：旧 lines_extra 归一化不得再做 20 条/60 字截断（迁移前就丢数据）
    _cfg3 = {"lines_extra": {"sajiao": ["条%d" % _i for _i in range(25)] + ["长" * 80]}}
    main.pet_config.normalize_cfg(_cfg3, main.DEFAULT_CONFIG, frozenset())
    check("legacy lines not truncated",
          len(_cfg3["lines_extra"]["sajiao"]) == 26
          and len(_cfg3["lines_extra"]["sajiao"][-1]) == 80,
          "n=%d" % len(_cfg3["lines_extra"]["sajiao"]))
    # 待机系统：两触发 / 多动作 / 播放模式 / idle_form 不吞用户形态
    _icfg = pet.behaviors.idle_config(lambda: pet.cfg)
    check("idle cfg defaults", _icfg["idle_trigger_delay"] == 8
          and _icfg["idle_delay_after_full"] == 2 and _icfg["idle_play_mode"] == "sequential")
    _ib1, _ = pet.behaviors.add("idle_a", [{"act": "say", "text": "待机一"}])
    _ib2, _ = pet.behaviors.add("idle_b", [{"act": "say", "text": "待机二"}])
    check("idle apply settings", pet.apply_idle_settings({
        "idle_trigger_delay": 6, "idle_delay_after_full": 1, "idle_play_mode": "sequential",
        "idle_actions": [
            {"id": _ib1["id"], "behavior_id": _ib1["id"], "enabled": True, "weight": 1.0, "order": 1},
            {"id": _ib2["id"], "behavior_id": _ib2["id"], "enabled": True, "weight": 1.0, "order": 2}]}) is True
        and len(pet.behaviors.idle_config(lambda: pet.cfg)["idle_actions"]) == 2)
    _pick1, _aid1, _pe1 = pet.behaviors.idle_pick(lambda: pet.cfg, None)
    _pick2, _aid2, _pe2 = pet.behaviors.idle_pick(lambda: pet.cfg, _aid1)
    check("idle pick rotates", _pick1 is not None and _pick2 is not None
          and _pick1["id"] != _pick2["id"])
    # v2.2：恢复双触发（OR 语义）——_digest 必须登记触发 A（吃饱形态结束后+delay）
    pet._idle_after_full_at = None
    pet._digest()
    check("trigger A armed after digest", pet._idle_after_full_at is not None)
    # 正向回归：把触发 A 视作已到点，无交互条件也满足 → 待机必须能触发
    pet._idle_after_full_at = 0.0
    _hold_bak = pet.cfg.get("idle_form", "")
    _acts_bak = list(pet.cfg.get("idle_actions") or [])
    # 用**当前角色**的形态键（此处可能是默认角色 normal/full，写死 f1 会因不在 form_keys 而跳过）
    _fk_user = pet.form_keys[0]
    _fk_idle = pet.form_keys[-1] if len(pet.form_keys) > 1 else pet.form_keys[0]
    pet.cfg["idle_form"] = _fk_idle
    pet.cfg["idle_actions"] = []
    pet._user_form = _fk_user
    pet._set_form(_fk_user, display_only=True)
    pet._stop_idle_hold()
    pet._idle_form_active = False
    pet._idle_active = False
    # 先把状态清成"可待机"（前面的检查可能留下了表情展示/busy）
    pet.busy = False
    pet._petting = False
    pet._cancel_transform()
    pet.anim.stop()
    pet.anim_mode = "idle"
    pet._last_activity = 0.0
    pet._last_idle_at = 0.0
    check("idle ready for resume test", pet._idle_ready() is True)
    pet.maybe_idle_behavior()
    check("trigger A fires idle",
          pet._idle_form_active is True and pet.form == _fk_idle,
          "form=%r flag=%r expect_idle_form=%r" % (pet.form, pet._idle_form_active, _fk_idle))
    # v2.1.8（M2）：展示期结束后**重新计时**——delay 秒内不得再次触发（否则待机形态近乎常驻）
    pet._idle_end()
    pet._last_activity = 0.0          # 无交互条件满足，但刚结束待机 → 冷却窗口内不该再触发
    pet.maybe_idle_behavior()
    check("idle not retrigger within delay", pet._idle_form_active is False,
          "form=%r flag=%r" % (pet.form, pet._idle_form_active))
    pet._idle_hold_timer = None
    pet.cfg["idle_form"] = _hold_bak
    pet.cfg["idle_actions"] = _acts_bak
    # 待机形态只做展示期覆盖，结束后回到用户选定形态
    _keys = pet.form_keys
    if len(_keys) >= 2:
        pet.set_user_form(_keys[-1])
        _uf_before = pet._user_form == _keys[-1] and pet.form == _keys[-1]
        pet.apply_idle_settings({"idle_form": _keys[0]})
        pet._start_idle("test")
        _overlay = pet.form == _keys[0] and pet._user_form == _keys[-1]
        pet._idle_end()
        check("idle form overlay+restore", _uf_before and _overlay and pet.form == pet._user_form)
        pet.apply_idle_settings({"idle_form": ""})
        pet.set_user_form(_keys[0])
    else:
        check("idle form overlay+restore", True, "单形态角色：跳过形态覆盖检查")
    # 导出包：携带台词/对白，剥掉克隆后端密钥
    _vm, _ve = pet_export.build_manifest(
        {"id": "x2", "name": "y", "file": "a.png", "form": "single",
         "frames": ["a.png"], "added": ""},
        [], {"voice": {"enabled": True, "backend_keys": {"minimax": "SECRETKEY"}}},
        None, [{"id": "l1", "text": "t"}], [{"id": "d1", "name": "n", "line_ids": ["l1"]}],
        [{"id": "v1", "name": "vn", "ext": ".wav", "file": "voice_ref/v1.wav"}])
    check("bundle carries lines", bool(_vm) and isinstance(_vm.get("lines"), list)
          and _vm["lines"][0]["id"] == "l1"
          and isinstance(_vm.get("dialogues"), list)
          and isinstance(_vm.get("voice_assets"), list), "err=%r" % (_ve,))
    check("bundle scrubs voice keys", "SECRETKEY" not in json.dumps(_vm)
          and any("backend_keys" in str(x) for x in _vm.get("excluded") or []))

    # ---- 3. 音效导入 + 音效组 ----
    wav = os.path.join(_tmp, "tone.wav")
    make_test_wav(wav)
    frag, err2 = pet.audio_lib.import_file(wav, "测试音")
    check("audio import", frag is not None and err2 is None, "err=%r" % (err2,))
    if frag:
        pet.audio_lib.set_slot("press", frag["id"])
        pet.audio_lib.set_slot("coin", "")  # 静音槽
        paths = pet.audio_lib.group_paths()
        check("group paths press", isinstance(paths.get("press"), str) and os.path.isfile(paths["press"]))
        check("group paths coin silent", paths.get("coin") == "")
        # M4：面板改槽位 → apply_sound_group 实时同步进 pet_audio + 自动切自定义组
        pet.apply_sound_group(None, as_custom=True)
        check("sound group auto custom", pet.cfg.get("sound_group") == "custom")
        cg = getattr(main.pet_audio, "_custom_group", None) or {}
        check("pet_audio custom synced", cg.get("press") == paths.get("press") and cg.get("coin") == "")
        pet._set_sound_group("custom")
        check("sound group custom cfg", pet.cfg.get("sound_group") == "custom")
        pet._set_sound_group("default")
        check("sound group default cfg", pet.cfg.get("sound_group") == "default")

    # ---- 4. 记账账本 ----
    book = pet.book
    book.add_manual(12.5, "午饭")
    check("manual today usage", abs(book.today_usage() - 12.5) < 0.001)
    book.observe_balance(100.0)
    book.observe_balance(97.3)
    check("balance diff usage", abs(book.today_usage() - 15.2) < 0.001)
    # 预算口径仅 API 消费（2.7）：设 2.0 触发
    pet.cfg["budget"] = 2.0
    pet.cfg["balance_alert"] = 0.0
    msgs = book.check_alerts(97.3, pet.cfg["budget"], pet.cfg["balance_alert"])
    check("budget alert fires", len(msgs) >= 1, "msgs=%r" % (msgs,))
    msgs2 = book.check_alerts(97.3, pet.cfg["budget"], pet.cfg["balance_alert"])
    check("budget alert once/day", len(msgs2) == 0)
    pet.cfg["budget"] = 0.0
    pet.cfg["balance_alert"] = 98.0
    msgs3 = book.check_alerts(97.3, 0.0, 98.0)
    check("balance alert fires", len(msgs3) >= 1)
    csv_path = os.path.join(_tmp, "ledger.csv")
    ok_csv, err_csv = book.export_csv(csv_path)
    check("csv export", ok_csv and os.path.isfile(csv_path) and os.path.getsize(csv_path) > 0)
    recs = book.search_records("午饭")
    check("search records", len(recs) >= 1)
    pet.on_ledger_changed()
    check("ledger changed usage", abs(pet._usage - book.today_usage()) < 0.001)

    # ---- 5. 气泡样式 + 自定义台词 ----
    pet.apply_bubble_style({"bg": "#ffe9c8", "fg": "#7a4a21", "border": "#b07030", "font_size": 12, "radius": 20})
    check("bubble style applied", main.BUBBLE_STYLE.get("bg") == "#ffe9c8" and main.BUBBLE_STYLE.get("font_size") == 12)
    pet.apply_bubble_style({"bg": "#ffffff", "fg": "#203170", "border": "#203170", "font_size": 10, "radius": 16})
    # v2.1：台词数据落在台词库（lines.json）；save_lines 作为兼容入口整体替换该类别的用户条目
    _bi_before = len([x for x in pet.lines_lib.lines("sajiao") if x.get("builtin")])
    pet.save_lines("sajiao", ["这是自定义台词一", "这是自定义台词二"])
    _user_lines = [x for x in pet.lines_lib.lines("sajiao") if not x.get("builtin")]
    check("lines saved", len(_user_lines) == 2
          and {x["text"] for x in _user_lines} == {"这是自定义台词一", "这是自定义台词二"}
          and len([x for x in pet.lines_lib.lines("sajiao") if x.get("builtin")]) == _bi_before,
          "user=%d" % len(_user_lines))
    # v2.1：台词对话框（新三页签）冒烟 + 池子同步 + 失效引用页
    try:
        ldlg = pet_dialogs.LinesDialog(pet)
        _texts = [ldlg._list.item(i).text() for i in range(ldlg._list.count())]
        check("lines dialog smoke", ldlg._tabs.count() == 3
              and any("这是自定义台词一" in t for t in _texts),
              "rows=%d" % len(_texts))
        ldlg.close()
    except Exception as e:
        check("lines dialog smoke", False, repr(e))
    # v2.1：删台词 → 池子立即刷新（on_changed → 桌宠._on_lines_changed）
    _del_id = _user_lines[0]["id"]
    pet.lines_lib.delete(_del_id)
    check("lines changed refresh", "这是自定义台词一" not in pet.lines_pools["sajiao"]
          and pet.lines_lib.get(_del_id) is None)
    pet.lines_lib.undo()  # 撤销回来，后续检查不受影响

    # ---- 6. 菜单构建（stub exec，断言分区与动作数量）----
    class _Menu(main.QMenu):
        def exec(self, *_a, **_k):
            self._captured = self.actions()
            return None

    real_menu_cls = main.QMenu
    main.QMenu = _Menu
    captured = {}
    try:
        pet._open_menu(QPoint(100, 100))
        # deleteLater 后菜单仍在 Python 引用内；从最近构建的 _Menu 拿 actions
        import gc
        for obj in gc.get_objects():
            if isinstance(obj, _Menu) and getattr(obj, "_captured", None) is not None:
                captured = obj
                break
    except Exception as e:
        check("menu build", False, repr(e))
    finally:
        main.QMenu = real_menu_cls
    if captured:
        def _all_texts(acts):
            out = []
            for a in acts:
                if a.text():
                    out.append(a.text())
                m2 = a.menu()
                if m2 is not None:
                    out.extend(_all_texts(m2.actions()))
            return out
        texts = _all_texts(captured._captured)
        top = [a.text() for a in captured._captured if a.text()]
        check("menu compact top-level", len(top) <= 18, "top=%d" % len(top))
        check("menu all items", len(texts) >= 35, "count=%d" % len(texts))
        check("menu ledger item", any("账本" in t for t in texts))
        check("menu resource item", any("资源管理" in t for t in texts))
        check("menu behavior entry", any("行为设置" in t for t in texts))
        check("menu alarm entry", any("闹钟" in t for t in texts))
        check("menu lines entry", any("自定义台词" in t for t in texts))
        # v2.1.2：入口解析检查——历史上「语音设置/自定义台词/资源管理/AI设置/气泡样式」
        # 都因为入口函数没定义而"点了没反应"（异常被 Qt 槽吞掉），这里逐个解析防复发
        _missing = []
        _pet_attrs = set(dir(main.PetWindow))
        # L2 修复：用**绝对路径**读源码；读不到就判 FAIL（此前相对路径 + continue 会在
        # 非仓库根目录启动时静默退化成"空检查"，永远 PASS）
        _here = os.path.dirname(os.path.abspath(__file__))
        _mods = ["pet_menu.py", "pet_ai.py", "桌宠.py"] + [
            _f for _f in sorted(os.listdir(_here)) if _f.startswith("pet_") and _f.endswith(".py")]
        _unreadable = []
        for _mod in _mods:
            try:
                _src = io.open(os.path.join(_here, _mod), encoding="utf-8").read()
            except Exception as _e:
                _unreadable.append("%s:%r" % (_mod, _e))
                continue
            # L-9 修复：先剥掉注释行，避免"注释里提到的旧名字"被误判为缺失入口
            _src = "\n".join(_ln.split("#", 1)[0] for _ln in _src.split("\n"))
            for _m in re.finditer(r"pet_dialogs\.([A-Za-z_][A-Za-z0-9_]*)", _src):
                if not hasattr(pet_dialogs, _m.group(1)):
                    _missing.append("%s -> pet_dialogs.%s" % (_mod, _m.group(1)))
            for _m in re.finditer(r"\bpet\.(_?[a-z][A-Za-z0-9_]*)\s*\(", _src):
                if _m.group(1) not in _pet_attrs:
                    _missing.append("%s -> pet.%s" % (_mod, _m.group(1)))
        check("ui entry points resolve", not _missing and not _unreadable,
              "missing=%r unreadable=%r" % (sorted(set(_missing))[:3], _unreadable[:2]))
        check("menu idle entry", any("待机设置" in t for t in texts))
        check("menu resource entry", any("资源管理" in t or "音频片段" in t for t in texts))
        check("menu transform hidden default", not any(t == "🐡 变身" for t in texts))
        check("menu bundle entries", any("导出角色包" in t for t in texts)
              and any("导入角色包" in t for t in texts))
        check("menu role item", any("角色" in t for t in texts))
        check("menu has size slider", any(isinstance(a, main.QWidgetAction) for a in captured._captured))
        check("menu city item", any("天气城市" in t for t in texts))
        # 中-2：_set_city 对话框全路径（stub QInputDialog）
        real_qid = main.QInputDialog
        fake = {"result": main.QDialog.DialogCode.Accepted, "val": ""}
        class _FakeInput:
            def __init__(self, parent=None):
                pass
            def setWindowTitle(self, t): pass
            def setLabelText(self, t): pass
            def setTextValue(self, t): self._val = t
            def setWindowFlags(self, f): pass
            def windowFlags(self): return 0
            def show(self): pass
            def raise_(self): pass
            def activateWindow(self): pass
            def setFocus(self): pass
            def exec(self): return fake["result"]
            def textValue(self): return fake["val"]
        main.QInputDialog = _FakeInput
        bubbles = []
        real_show_bubble = pet.show_bubble
        pet.show_bubble = lambda t: bubbles.append(t)
        try:
            pet.cfg["city"] = "北京"
            fake["result"] = main.QDialog.DialogCode.Accepted
            fake["val"] = "上海"
            pet._set_city()
            check("city dialog accept", pet.cfg["city"] == "上海"
                  and main.load_config().get("city") == "上海")
            fake["val"] = ""
            pet._set_city()
            check("city dialog empty", pet.cfg["city"] == "上海"
                  and any("不能为空" in b for b in bubbles))
            fake["result"] = main.QDialog.DialogCode.Rejected
            fake["val"] = "东京"
            pet._set_city()
            check("city dialog reject", pet.cfg["city"] == "上海")
        finally:
            main.QInputDialog = real_qid
            pet.show_bubble = real_show_bubble
        pet.cfg["city"] = "北京"
        main.save_config(pet.cfg)
    else:
        check("menu captured", False, "no menu object captured")

    # ---- 7. 对话框冒烟：构建 + show + close ----
    for name, mk in (
        ("ResourceManager", lambda: pet_dialogs.ResourceManagerDialog(pet, 0)),
        ("Ledger", lambda: pet_dialogs.LedgerDialog(pet)),
        ("BubbleStyle", lambda: pet_dialogs.BubbleStyleDialog(pet)),
        ("Lines", lambda: pet_dialogs.LinesDialog(pet)),
        ("AmountNote", lambda: pet_dialogs.AmountNoteDialog(pet)),
        ("RoleImport", lambda: pet_dialogs.RoleImportDialog(pet)),
        ("Voice", lambda: pet_dialogs.VoiceDialog(pet)),  # v2.0.7：防回归（曾因布局误传 addWidget 打不开）
        # v2.1：新增面板全部进冒烟（构造期异常会被入口 try/except 吞掉，必须靠这里兜住）
        ("VoiceAssetPanel", lambda: pet_dialogs.VoiceAssetPanel(pet)),
        ("Idle", lambda: pet_dialogs.IdleDialog(pet)),
        ("ResourceManager21", lambda: pet_dialogs.ResourceManagerDialog(pet, 2)),
    ):
        try:
            dlg = mk()
            dlg.show()
            app.processEvents()
            dlg.close()
            check("dialog %s" % name, True)
        except Exception as e:
            check("dialog %s" % name, False, repr(e))

    # ---- 7b. RoleImportDialog 拒绝路径（stub _warn 防弹窗阻塞）----
    _real_warn = pet_dialogs._warn
    pet_dialogs._warn = lambda *a, **k: None
    try:
        ridlg = pet_dialogs.RoleImportDialog(pet)
        ridlg._do_import()  # 形态 0 无图 → 提示并拒绝
        check("import reject: no form img", ridlg.result_data() is None)
        ridlg._add_form("第二形态")
        ridlg._form_rows[0]["src"] = os.path.join(_tmp, "opaque.png")
        ridlg._form_views()
        ridlg._do_import()  # 形态 1 无图 → 提示并拒绝
        check("import reject: form2 missing", ridlg.result_data() is None)
        ridlg.close()
    except Exception as e:
        check("import reject paths", False, repr(e))
    finally:
        pet_dialogs._warn = _real_warn

    # ---- 8. 清理与退出 ----
    # 护栏自检：检查总数硬断言——任何守卫式跳过（少跑检查）都会让这里 FAIL，
    # 防止护栏静默失明（新增检查时同步更新 EXPECT_CHECKS）
    check("v13 total checks", len(CHECKS) == EXPECT_CHECKS,
          "total=%d expect=%d" % (len(CHECKS), EXPECT_CHECKS))
    pet._quit()  # 内部调 QApplication.quit()
    shutil.rmtree(_tmp, ignore_errors=True)


def run_module_smokes():
    """逐个跑无 GUI 模块的冒烟测试（子进程，失败即 FAIL）。"""
    import subprocess
    py = sys.executable
    here = HERE
    for mod in ("pet_anim", "pet_mood", "pet_fx", "pet_resources", "pet_book", "pet_audio",
                "pet_alarm"):
        p = subprocess.run(
            [py, os.path.join(here, mod + ".py")],
            cwd=here, capture_output=True, timeout=120,
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8"},
        )
        stdout = (p.stdout or b"").decode("utf-8", errors="replace")
        stderr = (p.stderr or b"").decode("utf-8", errors="replace")
        tail = stdout[-300:]
        ok = p.returncode == 0 and "SMOKE OK" in stdout
        check("module smoke %s" % mod, ok, "rc=%d tail=%r err=%r" % (p.returncode, tail, stderr[-120:]))


if __name__ == "__main__":
    run_module_smokes()
    main_flow()
    print("=" * 40)
    print("TOTAL CHECKS: %d, FAILS: %d" % (len(CHECKS), len(FAILS)))
    if FAILS:
        print("FAILED:")
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("V13 VERIFY ALL OK")