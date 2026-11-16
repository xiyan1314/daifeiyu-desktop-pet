# -*- coding: utf-8 -*-
"""v2.13.0（第 13 轮 · 素材热重载）的钉子。

判据分三层，三层都必须是**行为**的：
1. 纯逻辑（pet_hotreload）：文件签名怎么算、什么算变化、删除算不算；
2. 接线（真 PetWindow）：2s 定时器真的起着、Watcher 接的是当前素材根；
3. 端到端（真 PetWindow + 临时素材根）：改一张 character.png → 调一拍 → **同一个窗口**
   的贴图真的换了，不用重启。

能真失败：
- 把 poll() 的"没基线先起基线"删掉 → 首拍把所有文件当变化（测试里第一条就红）；
- 把签名里的 size 去掉、只留 mtime → 同 mtime 下换同尺寸内容不红（本条保留 size 有理由）；
- 删掉 _hot_reload_tick 里的 busy 守卫 → test_busy_tick_does_not_reload 红；
- 删掉 _reload_sprites() 调用 → 端到端那条的像素不变 → 红；
- 把定时器删掉/停掉 → test_window_owns_a_running_watch_timer 红。
"""
import os
import shutil
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import pet_hotreload  # noqa: E402
import 桌宠 as main  # noqa: E402

REPO = HERE
REAL_ASSETS = os.path.join(REPO, "assets")


# ===================== 一、纯逻辑 ======================
def _fake_stat(table):
    class _St(object):
        def __init__(self, mtime_ns, size):
            self.st_mtime_ns = mtime_ns
            self.st_size = size

    def _stat(p):
        if p not in table:
            raise OSError(p)
        return _St(*table[p])

    return _stat


def test_snapshot_returns_mtime_and_size():
    """签名 = (mtime_ns, size)。collect 侧只收存在的文件，所以这里不管"缺失"。"""
    snap = pet_hotreload.snapshot(["a"], _fake_stat({"a": (1, 10)}))
    assert snap == {"a": (1, 10)}


def test_diff_reports_add_modify_delete():
    old = {"a": (1, 10), "b": (2, 20), "d": (4, 40)}
    new = {"a": (1, 10), "b": (2, 21), "c": (3, 30), "d": (4, 40)}
    assert pet_hotreload.diff(old, new) == ["b", "c"]
    assert pet_hotreload.diff({}, {"x": (1, 1)}) == ["x"]
    assert pet_hotreload.diff({"x": (1, 1)}, {}) == ["x"]


def test_watcher_first_poll_is_not_a_change(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("one", encoding="utf-8")
    w = pet_hotreload.Watcher(lambda: [str(p)])
    assert w.poll() == [], "第一次看到文件不等于素材变了（否则首拍就重载一次）"
    assert w.prime() == 1
    assert w.poll() == []


def test_watcher_detects_modify_add_delete(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("one", encoding="utf-8")
    # 契约：collect 只返回存在的文件（删除 = 从清单里消失 → diff 视为变化）
    w = pet_hotreload.Watcher(lambda: [str(p) for p in (a, b) if p.exists()])
    w.prime()
    a.write_text("one-two", encoding="utf-8")
    b.write_text("new", encoding="utf-8")
    changed = w.poll()
    assert str(a) in changed and str(b) in changed
    assert w.poll() == [], "同一份内容两次 poll 必须安静（否则会每 2s 重载一次）"
    b.unlink()
    assert w.poll() == [str(b)], "删除也要算变化"


def test_snapshot_size_is_part_of_the_signature(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("one", encoding="utf-8")
    w = pet_hotreload.Watcher(lambda: [str(p)])
    w.prime()
    st = os.stat(p)
    p.write_text("one-two", encoding="utf-8")
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))   # 只改内容长度、mtime 钉回原值
    assert w.poll() == [str(p)], "签名必须含 size（mtime 相同但内容长了）"


# ===================== 二、真窗口：接线 + 端到端 ======================
@pytest.fixture(scope="module")
def _assets_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("hotrel")
    shutil.copytree(REAL_ASSETS, str(root / "assets"))
    return str(root)


@pytest.fixture(autouse=True)
def _restore_character(_assets_root):
    """用例会改模块级素材副本里的 character.png —— 每条用例后逐字节还原。"""
    p = os.path.join(_assets_root, "assets", "character.png")
    with open(p, "rb") as f:
        data = f.read()
    yield
    with open(p, "wb") as f:
        f.write(data)


@pytest.fixture
def win(_assets_root, tmp_path, monkeypatch):
    import pet_log
    from helpers_roles import quiet_pet_timers, shutdown_pet

    data = str(tmp_path / "data")
    os.makedirs(data, exist_ok=True)
    snap = (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
            getattr(pet_log, "_data_dir", None))
    main.DATA_DIR = data
    main.CONFIG_PATH = os.path.join(data, "config.json")
    main.USAGE_PATH = os.path.join(data, "usage.json")
    main.MEMORY_PATH = os.path.join(data, "memory.json")
    pet_log.set_data_dir(data)
    monkeypatch.setattr(main, "app_dir", lambda: _assets_root)
    QApplication.instance() or QApplication([])
    w = main.PetWindow()
    quiet_pet_timers(w)
    try:
        yield w
    finally:
        shutdown_pet(w)
        (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
         pet_log._data_dir) = snap


def _settle(win):
    """测试前置：收敛到待机态（窗口刚建时会先播开场表情，2.5s 内 anim_mode=state）。"""
    win.busy = False
    win._sleeping = False
    win._petting = False
    win._state_timer.stop()
    win.anim_mode = ""
    win._play_idle()
    assert win.anim_mode in ("idle", "form_idle", ""), win.anim_mode


def test_window_owns_a_running_watch_timer(win, _assets_root):
    """2s 定时器必须真的起着、Watcher 指向当前素材根。"""
    t = win._asset_watch_timer
    assert t is not None and t.isActive(), "素材热重载定时器没起"
    assert t.interval() == main.ASSET_WATCH_INTERVAL_MS == 2000
    paths = win._asset_watch_paths()
    # 监听**面**也要钉住：只认 assets/ 全树 + 根级 character*.png。
    # （三审实测：把 resource_dir("assets") 改成 app_dir() 会监听整个应用目录
    #  158→459 个路径，旧版本只查后缀，仍然绿。）
    assets = os.path.join(_assets_root, "assets")
    outside = [p for p in paths
               if not (p == assets or p.startswith(assets + os.sep))
               and os.path.basename(p) not in main.PetWindow._ASSET_ROOT_FILES]
    assert outside == [], "监听面越界（不该监听这些）：%r" % (outside[:5],)
    assert any(p.endswith("character.png") for p in paths), paths[:3]
    assert all(os.path.isabs(p) for p in paths)
    assert len(paths) >= 100, "assets 全树只监听到 %d 个文件（漏面）" % len(paths)


def test_timeout_signal_really_triggers_the_tick(win, monkeypatch, _assets_root):
    """定时器的 timeout 必须真的接到 _hot_reload_tick。

    独立验收实测：只删 桌宠.py 的 timeout.connect 那一行，isActive()/interval 两条判据
    和端到端用例**都仍绿** —— 自动重载整条死掉而套件看不见。所以直接 emit 一次 timeout。
    """
    _settle(win)
    calls = []
    monkeypatch.setattr(win, "_reload_sprites", lambda: calls.append(1))
    changed = os.path.join(_assets_root, "assets", "character.png")
    _write_png(changed, (5, 6, 7, 255))
    win._asset_watch_timer.timeout.emit()
    assert calls == [1], "定时器 timeout 没接到 _hot_reload_tick（自动重载失效）"


def test_no_change_tick_is_silent(win, monkeypatch):
    calls = []
    monkeypatch.setattr(win, "_reload_sprites", lambda: calls.append(1))
    assert win._hot_reload_tick() is False
    assert calls == [], "素材没变却重载了"


def test_busy_tick_does_not_reload(win, monkeypatch, _assets_root):
    """忙 / 吃帧时这一拍跳过：改文件也不许在吃帧中途重载。"""
    calls = []
    monkeypatch.setattr(win, "_reload_sprites", lambda: calls.append(1))
    changed = os.path.join(_assets_root, "assets", "character.png")
    _write_png(changed, (255, 0, 255, 255))
    try:
        win.busy = True
        assert win._hot_reload_tick() is False
        assert calls == []
    finally:
        win.busy = False


def test_eating_and_state_modes_skip_reload(win, monkeypatch, _assets_root):
    """非待机态（吃帧/表情/走路/睡觉）一律不重载：等下一拍待机再说。

    三审实测：把 guard 改成只判 busy=True（去掉 anim_mode 检查）→ 旧版本 10 条全绿。
    """
    _settle(win)
    calls = []
    monkeypatch.setattr(win, "_reload_sprites", lambda: calls.append(1))
    changed = os.path.join(_assets_root, "assets", "character.png")
    _write_png(changed, (9, 9, 9, 255))
    for mode in ("eat", "state", "sleep", "walk"):
        win.anim_mode = mode
        assert win._hot_reload_tick() is False, "anim_mode=%s 时重载了" % (mode,)
    assert calls == []
    win.anim_mode = "idle"
    assert win._hot_reload_tick() is True, "回到待机后应该重载"
    assert calls == [1]


def _write_png(path, color, size=None):
    if size is None:
        img = QImage(path)
        size = (img.width(), img.height())
    img = QImage(size[0], size[1], QImage.Format.Format_ARGB32)
    img.fill(QColor(*color))
    img.save(path)


def test_changing_character_png_reloads_the_same_window(win, _assets_root):
    """端到端：改 character.png → 一拍 → **同一个窗口**的贴图换色，不用重启。

    红法：删掉 _hot_reload_tick 里的 _reload_sprites() → 像素不变 → 红。
    """
    _settle(win)
    target = os.path.join(_assets_root, "assets", "character.png")
    before = win.sprites["normal"]["side"].toImage().pixelColor(2, 2)
    before_size = (win.width(), win.height())
    _write_png(target, (0, 200, 0, 255))
    assert win._hot_reload_tick() is True, "文件变了却没重载"
    after = win.sprites["normal"]["side"].toImage().pixelColor(2, 2)
    assert (after.red(), after.green(), after.blue()) != (before.red(), before.green(), before.blue()), \
        "重载了但贴图没换（还是旧图）：%r -> %r" % (before.getRgb(), after.getRgb())
    assert (win.width(), win.height()) == before_size, \
        "同尺寸素材重载后窗口几何变了：%r -> %r" % (before_size, (win.width(), win.height()))


def test_new_asset_file_also_triggers_a_reload(win, _assets_root, monkeypatch):
    """新增素材文件也算变化（用户往 assets/ 里丢一张新图）。"""
    _settle(win)
    calls = []
    monkeypatch.setattr(win, "_reload_sprites", lambda: calls.append(1))
    new_file = os.path.join(_assets_root, "assets", "hotreload_new_probe.png")
    _write_png(new_file, (1, 2, 3, 255), size=(8, 8))
    try:
        assert win._hot_reload_tick() is True
        assert calls == [1]
    finally:
        os.remove(new_file)