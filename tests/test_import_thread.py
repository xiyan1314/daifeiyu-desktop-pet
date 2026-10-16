# -*- coding: utf-8 -*-
"""P1-1 导入线程化：取消机制 / 进度回调 / 管线纯函数回归（无需 QApplication 的路径）。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import pet_dialogs  # noqa: E402

from PySide6.QtGui import QImage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    """对话框级测试共享一个 offscreen QApplication（aboutToQuit 连接需要）。

    防御：若单例已存在但只是 QGuiApplication（非 QApplication），重建为
    QApplication——否则 QDialog 等控件类会原生崩溃（0xC0000409）。"""
    from PySide6.QtWidgets import QApplication
    inst = QApplication.instance()
    if inst is None or not isinstance(inst, QApplication):
        inst = QApplication([])
    yield inst


def _mk_png(path, w=40, h=40):
    """带 alpha 的不透明色块：跳过自动去背景，处理路径最短最确定。"""
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(0xFF3366CC)
    assert img.save(path, "PNG")


def test_frames_cancel_raises(tmp_path):
    s1 = str(tmp_path / "a.png")
    s2 = str(tmp_path / "b.png")
    _mk_png(s1)
    _mk_png(s2)
    out = str(tmp_path / "out")
    os.makedirs(out)
    with pytest.raises(pet_dialogs.ImportCancelled):
        pet_dialogs._prepare_role_frames([s1, s2], out, cancel=lambda: True)


def test_frames_progress_reported(tmp_path):
    s1 = str(tmp_path / "a.png")
    s2 = str(tmp_path / "b.png")
    _mk_png(s1)
    _mk_png(s2)
    out = str(tmp_path / "out")
    os.makedirs(out)
    msgs = []
    outs, notes = pet_dialogs._prepare_role_frames([s1, s2], out, cancel=lambda: False, progress=msgs.append)
    assert outs is not None and len(outs) == 2
    assert any("1/2" in m for m in msgs), msgs
    assert any("2/2" in m for m in msgs), msgs


def test_run_import_pipeline_cancel(tmp_path):
    s1 = str(tmp_path / "a.png")
    s2 = str(tmp_path / "b.png")
    _mk_png(s1)
    _mk_png(s2)
    out = str(tmp_path / "out")
    os.makedirs(out)
    with pytest.raises(pet_dialogs.ImportCancelled):
        pet_dialogs._run_import_pipeline([("形态1", s1), ("形态2", s2)], [], False, out,
                                         cancel=lambda: True)


def test_run_import_pipeline_ok(tmp_path):
    s1 = str(tmp_path / "a.png")
    s2 = str(tmp_path / "b.png")
    _mk_png(s1)
    _mk_png(s2)
    out = str(tmp_path / "out")
    os.makedirs(out)
    res, err = pet_dialogs._run_import_pipeline([("形态1", s1), ("形态2", s2)], [], False, out)
    assert err is None and res is not None
    assert len(res["forms"]) == 2
    assert all(os.path.isfile(p) for _, p in res["forms"])
    assert res["frames"] == []


def test_pipeline_backward_compat_no_callbacks(tmp_path):
    # 老调用方式（无 cancel/progress 参数）必须照常工作（v13/绿色版直测依赖）
    s1 = str(tmp_path / "a.png")
    _mk_png(s1)
    out = str(tmp_path / "out")
    os.makedirs(out)
    ok, _ = pet_dialogs._prepare_role_png(s1, os.path.join(out, "r.png"))
    assert ok is True


# ---------------- 对话框级（需要 QApplication） ----------------

def test_stop_silent_no_error_dialog(qapp):
    dlg = pet_dialogs.RoleImportDialog(None)
    dlg._worker_kind = "extract"
    warned = []
    real_warn = pet_dialogs._warn
    pet_dialogs._warn = lambda *a, **k: warned.append(a)
    try:
        dlg._set_busy(True)  # R4 加强：先真的进忙碌态，否则"busy 已复位"这句断言无从谈起
        dlg._on_worker_failed("已取消处理")
        assert warned == []  # 主动停止不弹错误框
        # R4（v2.10.0 第 8 轮 · 代理 C）：这里原来是
        #     assert not dlg._ok.isEnabled() or True   # busy 已复位（_set_busy(False) 在槽内）
        # —— "X or True" 恒真，等于这条断言从未执行过（_ok 本来就是 enabled 的，
        # 而"没复位"这件事只有先 busy 过才看得见）。现在按 _set_busy(False) 的可见后果钉：
        assert dlg._busy_state is False, "主动停止后仍处在忙碌态"
        assert dlg._ok.isEnabled(), "导入按钮没恢复可用（忙碌态没复位）"
        assert dlg._cancel.isEnabled(), "取消按钮没恢复可用（忙碌态没复位）"
        assert dlg._stop_btn.isHidden(), "「停止处理」没收起来（忙碌态没复位）"
    finally:
        pet_dialogs._warn = real_warn
        dlg.close()


def test_close_without_worker_ok(qapp):
    dlg = pet_dialogs.RoleImportDialog(None)
    dlg._set_busy(True)  # 忙碌但无 worker（极端边缘）：关闭不再被 ignore 死锁
    dlg.close()
    assert dlg._worker is None


def test_gif_sequential_sampling_order(qapp, tmp_path):
    """GIF 顺序读采样：抽出的帧文件内容互不相同（顺序正确、无重复采样）。"""
    gif = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "_verify_assets", "sample.gif")
    if not os.path.isfile(gif):
        pytest.skip("缺少 _verify_assets/sample.gif")
    out = str(tmp_path / "raw")
    os.makedirs(out)
    raws, err = pet_dialogs._extract_video_frames(gif, out)
    assert err is None and raws is not None and len(raws) >= 2
    contents = [open(p, "rb").read() for p in raws]
    assert len(set(contents)) >= 2  # 相邻帧内容不同：顺序采样正确

