# -*- coding: utf-8 -*-
"""素材缺失时的优雅降级：发行拆分实测（引入护栏）+ v2.4.3 新代码缺口复测。

来源：外部《大肥鱼桌宠·发行拆分实测清单-2026-10-11》（14 用例 / 34 断言，基线 v2.4.2，
原文只在会话附件里、**没有进仓库**）。那份实测的结论是"素材全缺也优雅降级、不崩——
程序化占位鱼 + 合成回退音兜底"。本模块把那套实测**正规化**成仓库护栏，并补上 v2.4.2
实测不可能覆盖的三处 v2.4.3 新代码（见 B 段）。

A 段（发行拆分实测的正规化）：
  · 角色基础图 character*.png 缺 → 程序化占位鱼（200×200 橙色椭圆），不抛；
  · 帧集缺 / 空帧集 / 未注册帧集 → 静态形态图 + play() 返回 False，不抛；
  · 状态图 f_*/n_*.png 缺 → 不显示表情、记一行日志，不抛；
  · 音效目录不存在 → 合成回退音（SND_MEMORY）兜底，不抛；
  · **整个 assets 目录不可用**（连目录都没有）→ 上面全部降级叠加，窗口照常构造、
    六条消费点（待机/表情/喂食/摸头/撒钱/音效）全部存活；
  · 运行时数据文件缺 / 损坏 → 首次启动自动生成默认值 / 按默认值运行，不抛。

B 段（v2.4.3 新代码缺口，v2.4.2 的实测没覆盖）：
  ① _preload_money_fx / _money_preload_step（撒钱预载分片）在 assets/fx **整个目录
     不存在**时不抛、收敛、静默跳过（只在 error.log 留一条 incomplete）；
  ② 启动分片接力（构造期只解 idle + 开场表情，其余三组按组、状态图按片接力）在整棵
     assets 不可用时收敛（_startup_assets_done 置位、pending 清空），**直接驱动**也不抛；
  ③ 自定义角色分支（_startup_frame_sets() 只返回 petpet）缺 idle/idle_full/eat 时的兜底：
     共用素材 petpet 照解、角色自己的动画照播、没有动画就回退角色静态图。

**真实 assets/ 只读**（它是要发出去的发行素材）：所有"缺素材"场景都在 monkeypatch
出来的**临时资源根**上做——`main.app_dir` 指向 tmp 里的假 exe 目录，临时根里的素材是从
真实 assets/ **复制**过去的，全程没有 rename/remove 真实素材。自动夹具
`_real_assets_untouched` 在**每条**用例前后比对真实 assets/ 的（路径 → 大小/mtime）
清单：任何一条用例动了它都会立刻变红；`test_real_assets_are_untouched_...` 再单独钉一次。

能真失败：每条用例的 docstring 都写明"把哪条降级路径改坏会红"，并由
_dev/mutations_asset_absence_v244.json 逐条验证（python _dev/mutate_check.py
_dev/mutations_asset_absence_v244.json，判定口径要求**点名的用例真的出现在失败列表里**）。
"""
import json
import os
import shutil
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import 桌宠 as main  # noqa: E402
import pet_anim  # noqa: E402
import pet_audio  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_ASSETS = os.path.join(REPO, "assets")
REAL_SOUNDS = os.path.join(REAL_ASSETS, "sounds")

# 发行素材里被逐类点名的文件（引用的是"真实仓库里那份"，只读）
CHARACTER_FILES = ("character.png", "character_front.png",
                   "character_full.png", "character_full_front.png")
PETPET_FILES = tuple("fx/petpet_f%02d.png" % i for i in range(10))
STATE_EXCLUDE = ("f_", "n_")          # assets 根下的状态图前缀（f_angry.png / n_laugh.png …）
KEY_RELEASE_FILES = ("character.png", "idle_f00.png", "idle_full_f00.png", "eat_f06.png",
                     "f_angry.png", "n_laugh.png", "fx/petpet_f09.png",
                     "fx/money_f85.png", "sounds/ya1.wav")
CUSTOM_ROLE_ID = "absrole1"


# ---------------- 真实 assets/ 只读护栏 ----------------

def _real_assets_files():
    """真实 assets/ 的相对路径清单（/ 分隔，只读）。"""
    out = []
    for dirpath, _dirs, files in os.walk(REAL_ASSETS):
        for fn in files:
            rel = os.path.relpath(os.path.join(dirpath, fn), REAL_ASSETS)
            out.append(rel.replace(os.sep, "/"))
    return sorted(out)


def _manifest(root):
    """目录清单：相对路径 -> (大小, mtime_ns)。用来断言"一个字节都没动过"。"""
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            p = os.path.join(dirpath, fn)
            try:
                st = os.stat(p)
            except OSError:
                continue
            out[os.path.relpath(p, root).replace(os.sep, "/")] = (st.st_size, st.st_mtime_ns)
    return out


@pytest.fixture(autouse=True)
def _real_assets_untouched():
    """本模块的硬约束：真实 assets/ 只读。每条用例前后各比一次清单。

    能真失败：把任何场景改成"临时移走真实素材"（os.rename / os.remove / 写入）→ 用例
    结束时的比对立刻红。这就是"用完必须还原、并断言还原成功"在本模块的落地方式。
    """
    before = _manifest(REAL_ASSETS)
    assert before, "真实 assets/ 读不到：本模块的前提是它就在仓库里（%s）" % REAL_ASSETS
    yield
    after = _manifest(REAL_ASSETS)
    assert after == before, (
        "用例动过真实 assets/（发行素材必须保持原样）：新增 %r / 丢失 %r / 改动 %r"
        % (sorted(set(after) - set(before)), sorted(set(before) - set(after)),
           sorted(k for k in set(before) & set(after) if before[k] != after[k])))


def _stage_assets(root, include=None, exclude=()):
    """把真实 assets/ 的素材**复制**进临时资源根（真实仓库只读）。

    include=None → 全量复制；给了列表 → 只复制列出的相对路径（相对 assets/，/ 分隔）。
    exclude → 命中（相等或前缀）的不复制。
    """
    assets = os.path.join(root, "assets")
    os.makedirs(assets, exist_ok=True)
    for rel in _real_assets_files():
        if include is not None and rel not in include:
            continue
        if any(rel == x or rel.startswith(x) for x in exclude):
            continue
        dst = os.path.join(assets, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(REAL_ASSETS, *rel.split("/")), dst)


# ---------------- 数据目录隔离 / 场景工厂 ----------------

class _Scene:
    """一个"缺素材"场景：临时资源根 + 临时数据目录 + 真 PetWindow。"""

    def __init__(self, win, root, data):
        self.win = win
        self.root = root
        self.data = data


def _snapshot():
    import pet_log
    return (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
            getattr(pet_log, "_data_dir", None))


def _point_data_dir(data):
    import pet_log
    main.DATA_DIR = data
    main.CONFIG_PATH = os.path.join(data, "config.json")
    main.USAGE_PATH = os.path.join(data, "usage.json")
    main.MEMORY_PATH = os.path.join(data, "memory.json")
    pet_log.set_data_dir(data)


def _restore(snap):
    import pet_log
    (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
     pet_log._data_dir) = snap


def _write_custom_role(data, animations=(), rid=CUSTOM_ROLE_ID, n=3):
    """在临时数据目录里造一个自定义角色（真 PNG + roles.json + config.json）。

    必须**在 PetWindow() 之前**落盘：本文件测的是"启动时就是自定义角色"。
    animations 为空 = 用户没给角色配任何帧动作（走静态形态图那条兜底）。
    """
    from PySide6.QtGui import QColor, QImage

    d = os.path.join(data, "roles")
    os.makedirs(d, exist_ok=True)
    names = []
    for i in range(n):
        name = "abs_%02d.png" % i
        img = QImage(96, 96, QImage.Format.Format_ARGB32)
        img.fill(QColor(40 + i * 40, 120, 200, 255))
        img.save(os.path.join(d, name))
        names.append(name)
    form = {"name": "常态", "file": names[0],
            "animations": ({a: list(names) for a in animations} if animations else {}),
            "anim_interval_ms": 80}
    # 注意 frames：RoleLibrary 归一化会把**角色级 frames** 迁移成 forms[0].animations.idle。
    # "没有动画"的角色必须给空 frames，否则它其实是有 idle 帧的（会测成另一回事）。
    role = {"id": rid, "name": "缺素材测试角色", "file": names[0], "form": "single",
            "file_full": "", "frames": (list(names) if animations else []),
            "added": "", "forms": [form]}
    with open(os.path.join(data, "roles.json"), "w", encoding="utf-8") as f:
        json.dump({"roles": [role], "active": rid}, f, ensure_ascii=False)
    with open(os.path.join(data, "config.json"), "w", encoding="utf-8") as f:
        json.dump({"role": rid}, f, ensure_ascii=False)
    return rid


@pytest.fixture
def make_pet(tmp_path, monkeypatch):
    """场景工厂：在临时资源根上构造真 PetWindow，用例结束统一收尾并还原全局。

    assets="full"  全量素材副本（正对照：证明确实能加载）
    assets="empty" assets 目录存在但一张素材都没有
    assets="none"  连 assets 目录都没有（发行拆分的最极端情形）
    include/exclude 只在 full 下生效（按相对路径挑素材）
    custom_role     非 None 时先落盘一个自定义角色（animations 决定有没有角色自己的帧）
    """
    from helpers_roles import quiet_pet_timers, shutdown_pet

    snap = _snapshot()
    wins = []
    seq = [0]

    def _make(assets="full", include=None, exclude=(), custom_role=None, animations=()):
        seq[0] += 1
        base = tmp_path / ("scene%d" % seq[0])
        root = base / "approot"
        data = base / "data"
        os.makedirs(str(data), exist_ok=True)
        if assets == "none":
            os.makedirs(str(root), exist_ok=True)          # 连 assets 目录都不建
        else:
            os.makedirs(str(root / "assets"), exist_ok=True)
            if assets == "full":
                _stage_assets(str(root), include=include, exclude=exclude)
        _point_data_dir(str(data))
        if custom_role is not None:
            _write_custom_role(str(data), animations=animations)
        # 唯一的总开关：app_dir 变了，resource_dir/resource_path 就都落到临时根上
        monkeypatch.setattr(main, "app_dir", lambda: str(root))
        QApplication.instance() or QApplication([])
        win = main.PetWindow()
        wins.append(win)
        quiet_pet_timers(win)
        return _Scene(win, str(root), str(data))

    try:
        yield _make
    finally:
        for w in wins:
            shutdown_pet(w)
        _restore(snap)


@pytest.fixture
def audio_spy(monkeypatch):
    """把 pet_audio.winsound 换成记录器：测试不出声，还能断言回退音真的走了哪条路。"""
    calls = []

    class _WS:
        SND_ASYNC = 0x1
        SND_NODEFAULT = 0x2
        SND_MEMORY = 0x4
        SND_PURGE = 0x40
        SND_NOWAIT = 0x2000
        SND_FILENAME = 0x20000

        @staticmethod
        def PlaySound(sound, flags):
            calls.append((sound, flags))

    monkeypatch.setattr(pet_audio, "winsound", _WS, raising=True)
    return calls


# ---------------- 驱动 / 断言辅助 ----------------

def _drain_relay(win, limit=40):
    """直接驱动启动接力**直到收敛**（不经 _gslot：异常必须冒到用例里，不许被守卫吞掉）。"""
    rounds = 0
    while not win._startup_assets_done and rounds < limit:
        rounds += 1
        win._startup_assets_step()
    return rounds


def _drain_money(win, limit=500):
    """直接驱动撒钱预载分片直到收敛（同样不经 _gslot）。"""
    rounds = 0
    while win._money_preload is not None and rounds < limit:
        rounds += 1
        win._money_preload_step()
    return rounds


def _pump(seconds):
    """推进事件循环若干秒（让 QTimer.singleShot 的兜底分支真的到点）。"""
    import time as _t
    t0 = _t.monotonic()
    while _t.monotonic() - t0 < seconds:
        QApplication.processEvents()
        _t.sleep(0.005)


def _error_log(data):
    p = os.path.join(data, "error.log")
    if not os.path.isfile(p):
        return ""
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


# ================= A 段：素材缺失逐类降级（发行拆分实测的正规化） =================

def test_asset_copy_scene_is_a_working_positive_control(make_pet):
    """正对照：临时资源根上的**全量副本**必须照常加载。

    没有这条，下面"缺素材"的断言可能只是"什么都没跑起来"的假绿。本用例同时覆盖
    v2.4.3 的撒钱分片预载在素材齐全时的行为（86 帧、逐片解完、挂到 _fx_money）。

    能真失败：_stage_assets 只复制目录结构 / resource_dir 指错根 → idle 帧集或状态图
    数量立刻对不上 → 红。
    """
    sc = make_pet()
    win = sc.win
    assert len(win._idle_frames) == 10, "构造期 idle 帧集没从临时资源根加载"
    assert win.has_frames and len(win.anim._sets.get("idle") or []) == 10
    rounds = _drain_relay(win)          # 素材齐全：三组帧集 + 17 张状态图按片接力，轮数天然更多
    assert win._startup_assets_done and rounds <= 30, "素材齐全时接力没跑完（%d 轮）" % rounds
    assert (len(win._idle_full_frames), len(win._eat_frames), len(win._fx_petpet)) == (10, 7, 10)
    assert win._state_pix_pending == {} and sum(len(v) for v in win.state_pix.values()) == 17
    win._fx_money = []
    win._money_preload = None
    win._preload_money_fx()
    assert _drain_money(win) >= 1
    assert len(win._fx_money) == main._MONEY_FRAME_COUNT, \
        "撒钱帧集没解全：%d/%d" % (len(win._fx_money), main._MONEY_FRAME_COUNT)


def test_character_images_missing_fall_back_to_placeholder_fish(make_pet):
    """角色基础图 character*.png 全缺（TC8/TC11d）→ 程序化占位鱼，不抛。

    用户看到的就是那只 200×200 的橙色椭圆鱼：主画面、托盘图标都用它，程序照常跑。

    能真失败：把 _build_sprites 里 "or self._fallback_pix()" 拿掉 → sprites[...]["side"]
    变成 None → 下面 .width() 直接 AttributeError → 红（变异 M-A1）。
    """
    sc = make_pet(exclude=CHARACTER_FILES)
    win = sc.win
    want = win._fallback_pix()
    for form in ("normal", "full"):
        for view in ("side", "front"):
            pix = win.sprites[form][view]
            assert pix is not None and not pix.isNull(), "缺角色图时 %s/%s 是空的" % (form, view)
            assert (pix.width(), pix.height()) == (200, 200), \
                "占位鱼尺寸不对：%dx%d" % (pix.width(), pix.height())
            assert pix.toImage() == want.toImage(), "不是 _fallback_pix 画的那只占位鱼"
    assert not win.item.pixmap().isNull(), "缺角色图时主画面是空的（用户看到一片透明）"
    assert not win.tray.icon().pixmap(64, 64).isNull(), "缺角色图时托盘图标是空白"


def test_frame_sets_missing_degrade_to_static_form_and_still_run(make_pet, monkeypatch):
    """帧集全缺（只留角色基础图）→ 待机静态图、摸头无特效、喂食挤压兜底，全部不抛。

    能真失败：
      · 把 _play_idle 的"无帧集 → 静态形态图"分支拿掉 → 画面不再被贴回形态图 → 红；
      · 把 _start_petting 的 "if not self._fx_petpet: return" 拿掉 → 空帧集也进 _petting
        → "_petting is False" 那条红（变异 M-A2）；
      · 把 feed 的三分支兜底拿掉 → 缺吃帧时 busy 不再被置位 → 红。
    """
    sc = make_pet(include=CHARACTER_FILES)
    win = sc.win
    assert win._idle_frames == [] and win.has_frames is False, "夹具前提：帧集应当全缺"
    assert _drain_relay(win) <= 8 and win._startup_assets_done
    assert (win._idle_full_frames, win._eat_frames, win._fx_petpet) == ([], [], [])
    assert win.anim._sets.get("idle") == [] and win._frames_loaded.get("idle")
    # 待机：没有帧可播 → 不空转、画面停在静态形态图（真角色图，不是占位鱼）
    win._play_idle()
    assert win.anim._name is None and not win.anim._timer.isActive(), "没有帧集却还在播帧"
    assert win.item.pixmap().toImage() == win.sprites[win.form]["front"].toImage(), \
        "缺帧时没回退静态形态图"
    # 摸头：没有 petpet 帧 → 静默跳过（不进 _petting、也不喊摸头台词），不抛
    said = []
    monkeypatch.setattr(win, "_say_line", lambda *a, **k: said.append(a))
    win.busy = False
    win._press_dist = 0
    win._start_petting()
    assert win._petting is False and win._fx_petpet_on is False, "缺帧时摸头不该进播放态"
    assert said == [], "缺 petpet 帧却仍喊了摸头台词：%r" % (said,)
    win._end_petting()
    # 喂食：没有吃帧 → 挤压动画兜底（默认角色的 has_frames 也是 False）
    win.feed("小鱼干")
    assert win.busy is True, "缺吃帧时喂食没进入吃东西状态（挤压兜底没走通）"
    assert win.anim_mode != "eat"


def test_eat_frames_missing_falls_back_to_laugh_expression(make_pet, monkeypatch):
    """只缺吃帧（待机动画还在）→ 喂食走"大笑表情"兜底（2.2 秒）+ 立即释放 busy，不抛。

    能真失败：把 feed 的 "elif self.has_frames:" 分支拿掉 → 缺吃帧时 busy 永久卡住
    （之后喂食会被"嘴里还有呢"拒绝）→ 红。
    """
    sc = make_pet(exclude=("eat_",))
    win = sc.win
    assert win._idle_frames and win._eat_frames == [] and win.has_frames, "夹具前提：只缺吃帧"
    assert _drain_relay(win) <= 30 and win._startup_assets_done
    assert win.anim._sets.get("eat") == []
    calls = []
    monkeypatch.setattr(win, "_show_state", lambda st, ms=0: calls.append((st, ms)))
    win.busy = False
    win.feed("小鱼干")
    assert win.busy is True
    _pump(0.5)                            # 让 120ms 的兜底 singleShot 到点
    assert calls and calls[0][0] == "laugh", "缺吃帧时没走大笑表情兜底：%r" % (calls,)
    assert win.busy is False, "大笑兜底没释放 busy（之后喂食会被「嘴里还有呢」拒绝）"


def test_state_images_missing_show_nothing_and_only_log(make_pet):
    """状态图 f_*/n_*.png 全缺 → 该表情不显示（画面不变），只记一行日志，不抛。

    能真失败：把 _show_state 的 "if pix is None: _log_error(...); return" 拿掉 →
    要么抛异常、要么拿 None 去 setPixmap → 红。
    """
    sc = make_pet(exclude=STATE_EXCLUDE)
    win = sc.win
    assert _drain_relay(win) <= 8 and win._startup_assets_done
    assert win._state_pix_pending == {}, "缺状态图时 pending 没清空（接力链会空转）"
    assert sum(len(v) for v in win.state_pix.values()) == 0, "没有素材却建出了状态图"
    assert win._state_pix("angry") is None
    win._show_state("angry")            # 不抛
    log = _error_log(sc.data)
    assert "state image missing: laugh" in log, "开场表情缺图没留诊断"
    assert "state image missing: angry" in log, "按需表情缺图没留诊断"


def test_sounds_dir_missing_uses_synth_fallback(make_pet, audio_spy):
    """音效目录不存在（TC12/TC13）→ 6 条素材路径全 None、播放落到合成回退音，不抛。

    能真失败：把 play() 第 3 级（SND_MEMORY 合成音）整段拿掉 → 一条 PlaySound 都没有 → 红。
    """
    sc = make_pet(exclude=("sounds/",))
    missing = os.path.join(sc.root, "assets", "sounds")
    assert not os.path.isdir(missing), "夹具前提：临时根里没有 sounds 目录"
    pet_audio.init(missing)
    assert all(v is None for v in pet_audio._wav_paths.values()), "缺音效目录却还解析出了 wav 路径"
    assert all(v is None for v in pet_audio._wav_duration.values())
    assert sorted(pet_audio._fallback) == ["feed", "press", "release"], "合成回退音不齐"
    assert all(isinstance(v, (bytes, bytearray)) and v for v in pet_audio._fallback.values())
    audio_spy.clear()
    for kind in pet_audio._PLAY_MAP:
        pet_audio.play(kind)            # 不抛
    assert len(audio_spy) == len(pet_audio._PLAY_MAP), \
        "有事件没落到合成回退音：%r" % (audio_spy,)
    for sound, flags in audio_spy:
        assert isinstance(sound, (bytes, bytearray)), "回退音不是内存 WAV（SND_MEMORY 路径）"
        assert flags & pet_audio.winsound.SND_MEMORY, "回退音没带 SND_MEMORY：%r" % (flags,)
    pet_audio.play("__no_such_kind__")  # 未知 kind：直接返回
    # 用完必须还原，并断言还原成功（真实素材回到 _wav_paths）
    pet_audio.init(REAL_SOUNDS)
    assert all(pet_audio._wav_paths.values()), \
        "还原失败：真实音效没回到 _wav_paths（%r）" % (pet_audio._wav_paths,)


def test_empty_or_unregistered_frame_set_play_returns_false(make_pet):
    """空帧集 / 未注册帧集（TC9/TC10）→ play() 返回 False 并立即回调，不抛、不空转。

    能真失败：把 play() 的 "if not frames or loops == 0:" 分支拿掉 → 空帧集也起播
    （_advance 里 n==0 直接 return，界面永远不动却以为在播）→ 红。
    """
    sc = make_pet()
    win = sc.win
    got = []
    win.anim.add_set("idle", [])                       # 已注册但是空集
    assert win.anim.play("idle", on_finish=got.append) is False
    assert got == ["idle"], "空帧集没有立即回调（调用方会一直等收尾）"
    assert win.anim._name is None and not win.anim._timer.isActive()
    got.clear()
    assert win.anim.play("__no_such_set__", on_finish=got.append) is False
    assert got == ["__no_such_set__"], "未注册帧集没有立即回调"
    win.anim.add_set("idle", win._idle_frames)         # 有帧 + loops=0：同样立即收尾
    got.clear()
    assert win.anim.play("idle", loops=0, on_finish=got.append) is False
    assert got == ["idle"]


def test_entire_assets_dir_unavailable_keeps_every_consumer_alive(make_pet, audio_spy):
    """**整个 assets 目录不可用**（连目录都没有，TC11）：窗口照常构造，六条消费点全部存活。

    这是发行拆分的极端情形：占位鱼 + 静态形态图 + 合成回退音，功能自洽（降级态）。
    能真失败：本用例的消费点都是**直接调用**（不经 _gslot），任何降级分支抛异常都会
    当场冒出来；配合变异 M-A3（接力收口拿掉）/M-A4（消费点守卫拿掉）逐条验证。
    """
    sc = make_pet(assets="none")
    win = sc.win
    assert not os.path.isdir(os.path.join(sc.root, "assets")), "夹具前提：assets 目录不存在"
    assert win._assets_dir and not os.path.isdir(win._assets_dir)

    rounds = _drain_relay(win)
    assert win._startup_assets_done and rounds <= 8, "缺素材时启动接力没收敛（%d 轮）" % rounds
    assert win._state_pix_pending == {}
    assert sum(len(v) for v in win.state_pix.values()) == 0
    assert (win._idle_frames, win._idle_full_frames, win._eat_frames, win._fx_petpet) \
        == ([], [], [], [])
    assert win.has_frames is False
    assert not win.item.pixmap().isNull(), "缺素材时主画面是空的"

    win._play_idle()                     # 1) 待机
    win._show_state("laugh")             # 2) 表情
    assert win._state_pix("angry") is None
    win.feed("小鱼干")                    # 3) 喂食
    assert win.busy is True
    win.busy = False
    win._start_petting()                 # 4) 摸头
    assert win._petting is False and win._fx_petpet_on is False
    win._end_petting()
    win._preload_money_fx()              # 5) 撒钱（预载 + 消费点）
    assert _drain_money(win) >= 1 and win._fx_money == []
    win._fx_celebrate()
    assert win._fx_money_on is False
    audio_spy.clear()
    main.play_sound("coin")              # 6) 音效（缺素材 → 合成回退）
    main.play_sound("boing")
    main.play_sound("pop")
    main.play_sound("feed")
    assert len(audio_spy) >= 4, "缺素材时音效链路一声不响：%r" % (audio_spy,)
    # 收尾自检：窗口还是活的
    assert win.isEnabled()


def test_runtime_data_files_missing_are_regenerated(make_pet):
    """运行时数据文件全缺（新装/发行拆分去掉数据）→ 首次启动自动生成默认值，不抛。

    外加"损坏即愈合"：把 config.json 写成坏 JSON，load_config 不抛、按默认值运行。
    能真失败：把 pet_io / load_config 的"读不到就建默认"路径拿掉 → 文件不生成或直接抛 → 红。
    """
    sc = make_pet()
    win = sc.win
    assert isinstance(win.cfg, dict) and win.cfg.get("scale")
    for name in ("config.json", "roles.json", "lines.json", "ledger.json",
                 "ledger_archive.json"):
        p = os.path.join(sc.data, name)
        assert os.path.isfile(p), "首次启动没生成 %s" % name
        with open(p, encoding="utf-8") as f:
            json.loads(f.read())          # 必须是合法 JSON
    with open(os.path.join(sc.data, "config.json"), "w", encoding="utf-8") as f:
        f.write("{ 这不是 json")
    cfg = main.load_config()              # 不抛
    assert isinstance(cfg, dict) and "scale" in cfg, "坏配置没有回落到默认值"


# ================= B 段：v2.4.3 新代码缺口（v2.4.2 的实测没覆盖） =================

@pytest.mark.parametrize("assets_scene", ["none", "empty"])
def test_money_preload_with_unavailable_fx_dir_converges_silently(make_pet, monkeypatch, assets_scene):
    """v2.4.3 新代码①：撒钱预载分片在 assets/fx 整个目录不存在时不抛、收敛、静默跳过。

    期望：入口只登记在途状态；分片走完 86 个文件名（QPixmap 全为空 → 一帧不留）；
    _fx_money 保持空集；用户真撒钱时静默不播；只在 error.log 留一条 incomplete 诊断。

    能真失败：把入口改成先 os.listdir(self._fx_money_dir) 预检（"优化"掉 86 次空解码）
    → FileNotFoundError 直接冒到用例 → 红（变异 M-A5）。
    """
    sc = make_pet(assets=assets_scene)
    win = sc.win
    assert not os.path.isdir(win._fx_money_dir), "夹具前提：assets/fx 不存在"
    win._fx_money = []
    win._money_preload = None
    win._preload_money_fx()              # 不抛
    assert win._money_preload is not None, "入口没登记在途状态（用例失去区分力）"
    steps = _drain_money(win)
    assert win._money_preload is None, "预载没收敛（在途状态还挂着）"
    assert win._fx_money == [], "fx 目录不存在却解出了 %d 帧" % len(win._fx_money)
    assert 1 <= steps <= main._MONEY_FRAME_COUNT
    # 消费点：空帧集 → 静默不播。判据用"根本没进播放器"而不是 _fx_money_on——
    # 后者会被空帧集的立即收尾回调自己复位，变异 M-A4 实测能溜过去（只看它 = 假绿）。
    played = []
    monkeypatch.setattr(win.fx_money, "play", lambda *a, **k: played.append(a) or False)
    win._fx_celebrate()                  # 不抛
    assert played == [], "空帧集却把撒钱特效丢进了播放器：%r" % (played,)
    assert win._fx_money_on is False, "空帧集却进了撒钱播放态"
    assert not win.fx_money._timer.isActive()
    log = _error_log(sc.data)
    assert "fx frames money incomplete (preload): 0/%d" % main._MONEY_FRAME_COUNT in log, \
        "预载放弃时没留诊断（既不该抛，也不该连日志都没有）"


@pytest.mark.parametrize("assets_scene", ["none", "empty"])
def test_startup_relay_converges_without_any_assets(make_pet, assets_scene):
    """v2.4.3 新代码②：启动分片接力在缺素材时不抛、收敛。

    构造期只解 idle + 开场表情，其余三组帧集与全部状态图靠接力；素材全缺时每一片都是
    "空手而归"，链必须照样走到 _startup_assets_done（不能永久自排、也不能停在半路）。

    能真失败：去掉 _startup_assets_step 的 finally 收口 → 收敛断言红（变异 M-A3）；
    在 _load_default_frame_set 里加 os.listdir 预检 → 直接驱动时抛 → 红（变异 M-A2）。
    """
    sc = make_pet(assets=assets_scene)
    win = sc.win
    assert win._startup_frames_pending(), "夹具前提：构造期只解了 idle，其余三组还挂着"
    rounds = _drain_relay(win)
    assert win._startup_assets_done, "接力没收敛（跑了 %d 轮）" % rounds
    assert rounds <= 8, "缺素材时接力用了 %d 轮（收敛太慢/在空转）" % rounds
    assert win._state_pix_pending == {}, "状态图待建清单没清空：%r" % (win._state_pix_pending,)
    assert all(win._frames_loaded.get(k) for k in ("idle", "idle_full", "eat", "petpet")), \
        "缺素材时这些组没被标记为「已尝试」：%r" % (win._frames_loaded,)
    assert (win._idle_frames, win._idle_full_frames, win._eat_frames, win._fx_petpet) \
        == ([], [], [], [])
    assert win.has_frames is False
    assert sum(len(v) for v in win.state_pix.values()) == 0


def test_custom_role_without_animations_falls_back_to_static_and_keeps_petpet(make_pet):
    """v2.4.3 新代码③：自定义角色（_startup_frame_sets 只返回 petpet）缺默认三组帧集时的兜底。

    场景：用户角色没配任何帧动作 + 发行素材只剩共用的 fx/petpet。
    期望：接力只解 petpet；待机回退**角色自己的静态图**（不是占位鱼）；摸头特效照播；
    喂食不抛也不去解默认吃帧。

    能真失败：把 _startup_frame_sets 的角色判断拿掉 → 接力去解 idle/idle_full/eat →
    下面"默认三组没被碰"的断言红；把 _custom_role 的 feed 守卫拿掉 → 首喂去解默认吃帧 → 红。
    """
    sc = make_pet(include=PETPET_FILES, custom_role=True)
    win = sc.win
    assert win._custom_role and win.cfg.get("role") == CUSTOM_ROLE_ID, "夹具没进自定义角色路径"
    assert win._startup_frame_sets() == ("petpet",)
    assert win._idle_frames == [] and not win._frames_loaded.get("idle"), \
        "自定义角色构造期不该解默认 idle 帧集"
    rounds = _drain_relay(win)
    assert win._startup_assets_done and rounds <= 8
    assert len(win._fx_petpet) == 10, "共用的 petpet 素材没被接力解出来（摸头会静默失效）"
    assert not win._frames_loaded.get("idle") and not win._frames_loaded.get("idle_full") \
        and not win._frames_loaded.get("eat"), \
        "缺素材的自定义角色仍去碰默认三组帧集：%r" % (win._frames_loaded,)

    win._play_idle()                     # 角色没配帧 → 静态角色图兜底
    assert win.has_frames is False
    assert win.item.pixmap().toImage() == win.sprites[win.form]["front"].toImage(), \
        "待机没回退到角色自己的静态图"

    win.feed("小鱼干")                    # 首喂：不碰默认帧集（v2.4.3 复审 M3 的守卫）
    assert win.busy is True
    assert not win._frames_loaded.get("eat"), "自定义角色首喂去解默认吃帧了"

    win.busy = False
    win._press_dist = 0
    win._petting = False
    win._start_petting()                 # petpet 是共用素材 → 摸头照播
    assert win._petting is True and win._fx_petpet_on is True, \
        "缺默认素材时摸头特效没播（petpet 是角色共用的）"
    win._end_petting()


def test_custom_role_with_own_animations_needs_no_shipped_assets(make_pet):
    """v2.4.3 新代码③（另一半）：自定义角色自己的帧集在用户 roles/ 目录里，发行素材全缺也照播。

    期望：待机播角色自己的 idle 帧；表情走程序化合成（_custom_state_pix），不依赖 assets；
    默认素材一张都不解。

    能真失败：把 _wire_anim_sets 的自定义角色分支改成读默认素材 → 待机播不起来 → 红。
    """
    sc = make_pet(assets="none", custom_role=True, animations=("idle", "eat"))
    win = sc.win
    assert win._custom_role and win._startup_frame_sets() == ("petpet",)
    assert _drain_relay(win) <= 8 and win._startup_assets_done
    assert not win._frames_loaded.get("idle"), "默认 idle 素材不该被碰（角色有自己的帧）"

    win._play_idle()
    assert win.has_frames is True and win.anim._name == "idle", "角色自己的待机帧没播起来"
    assert win.anim._timer.isActive()
    pix = win._state_pix("angry")
    assert pix is not None and not pix.isNull(), "自定义角色表情是程序化合成，不该依赖 assets"
    win._show_state("angry")
    assert win._cur_state == "angry" and not win.item.pixmap().isNull()


# ================= 真实发行素材只读：单独钉一次 =================

def test_real_assets_are_untouched_by_this_module(make_pet):
    """真实 assets/（要发出去的发行素材）全程只读：跑完最极端的缺素材场景必须一个字节不变。

    能真失败：任何一条用例去 rename/remove 真实素材 → 清单比对或关键文件点名立刻红。
    （自动夹具 _real_assets_untouched 在**每条**用例前后都做同样的比对，这里是显式复述。）
    """
    before = _manifest(REAL_ASSETS)
    sc = make_pet(assets="none")
    _drain_relay(sc.win)
    sc.win._preload_money_fx()
    _drain_money(sc.win)
    sc.win._show_state("laugh")
    sc.win.feed("小鱼干")
    assert _manifest(REAL_ASSETS) == before, "跑完缺素材场景后真实 assets/ 变了"
    for rel in KEY_RELEASE_FILES:
        p = os.path.join(REAL_ASSETS, *rel.split("/"))
        assert os.path.isfile(p) and os.path.getsize(p) > 0, "发行素材 %s 不在了" % rel
    assert len(_real_assets_files()) >= 150, \
        "真实素材清单短了：%d 个（v2.4.3 是 150）" % len(_real_assets_files())
