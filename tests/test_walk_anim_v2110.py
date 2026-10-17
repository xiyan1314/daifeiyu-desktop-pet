# -*- coding: utf-8 -*-
"""v2.11.0 第 11 轮 W2「动起来好看 I」：**走路播帧** + **状态切换交叉淡入**。

判据一律结构性（不看眼、不看墙钟）：

· 走路：移动时 anim 播的就是 "walk" 帧集（断言 anim._name / anim._frames 身份 / anim_mode），
  停下回 "idle"；**位移仍由 pet_wander 驱动**（窗口坐标真的在变）；
· 无帧集兜底（MASTER_CHECKLIST 原文的硬要求）：自定义角色 / 空帧集时 anim_mode 不进 walk、
  静态侧身图仍在、位置仍在变、**零异常**；
· 交叉淡入：切换过程中**两个绘制项都可见**（opacity 各自在 (0,1)、和在 (0,2)），结束后
  ghost 不可见、**场景对象数回到基线**（ghost 是建窗时就创建的，不是临时 addItem）；
· 「减少动效」：交叉淡入**时长 0 = 瞬时**——不产生动画对象、不留半截 opacity、结果帧正确；
· **A4 硬口径**：交叉淡入与"切到走路帧"这两个动作**一个几何量都不写**（几何五元组逐项比，
  复用 tests/test_motion_v2110._geometry 的同一份口径）；
· 令牌：时长只从 pet_motion.DUR["TRANSITION"] 来（消费点在 桌宠.py，见 C-09 的反向钉子）。

驱动方式：QVariantAnimation 用 setCurrentTime(duration) 推到终态——确定性、不看钟
（与 tests/test_motion_v2110.py / tests/test_idle_settle_v26.py 的驱动口径一致）。
"""
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import 桌宠 as main  # noqa: E402
import pet_anim  # noqa: E402
import pet_motion  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

# 与 A4 的验收**同一份**几何口径（不在本文件复制一份，否则两边会漂）
from test_motion_v2110 import _geometry  # noqa: E402


# ---------------- 夹具 ----------------

def _snapshot():
    import pet_log
    return (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
            getattr(pet_log, "_data_dir", None))


def _point_data_dir(tmp_path):
    import pet_log
    main.DATA_DIR = str(tmp_path)
    main.CONFIG_PATH = str(tmp_path / "config.json")
    main.USAGE_PATH = str(tmp_path / "usage.json")
    main.MEMORY_PATH = str(tmp_path / "memory.json")
    pet_log.set_data_dir(str(tmp_path))


def _restore(snap):
    import pet_log
    (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
     pet_log._data_dir) = snap


def _app():
    return QApplication.instance() or QApplication([])


def _quiet(win):
    """停掉会自行插进状态机/待机的周期定时器（用例要确定性）。"""
    from helpers_roles import quiet_pet_timers
    quiet_pet_timers(win)
    win.walk_timer.stop()


def _settle(win):
    """把窗口带回**确定的待机状态**：收掉开场表情（PetWindow 构造时会先放一次 "laugh"）
    与在它名下的在途交叉淡入——否则"当前是什么状态"取决于构造期那一刻，判据会飘。"""
    win._state_timer.stop()
    win._play_idle()
    if win._crossfade_anim is not None:
        _drive(win._crossfade_anim)
    assert win.anim_mode in ("idle", "form_idle"), "前提不成立：%r" % (win.anim_mode,)


def _install_bare_role(win, tmp_path, rid="bare1"):
    """装一个**没有任何帧集**的自定义角色（只有两张静态底图）→ 走路只能走静态兜底。

    ⚠ 不能用 helpers_roles.install_three_form_role(with_animations=False)：那份 raw 带
    角色级 `"frames": [...]`，RoleLibrary._normalize_role 会把它迁移成
    forms[0].animations.idle（旧角色兼容路径）→ has_frames 仍为 True，测不到"无帧集"。
    """
    from PySide6.QtGui import QColor, QImage
    d = os.path.join(str(tmp_path), "roles")
    os.makedirs(d, exist_ok=True)
    for n in ("bare_a.png", "bare_b.png"):
        img = QImage(64, 64, QImage.Format.Format_ARGB32)
        img.fill(QColor(120, 200, 255, 255))
        img.save(os.path.join(d, n))
    f0 = {"name": "常态", "file": "bare_a.png"}
    f1 = {"name": "变身", "file": "bare_b.png", "transform_form": True}
    raw = {"id": rid, "name": "无帧角色", "file": "bare_a.png", "form": "triple",
           "file_full": "", "added": "", "forms": [f0, f1]}
    norm = win.role_lib._normalize_role(raw) or raw   # 走库自己的归一化（不塞半成品）
    win.role_lib._data["roles"].append(norm)
    win.role_lib._save()
    win.apply_role(rid)
    return rid


@pytest.fixture
def win(tmp_path):
    """一个真 PetWindow（数据目录指到 tmp_path，绝不碰真配置）。"""
    snap = _snapshot()
    _point_data_dir(tmp_path)
    w = main.PetWindow()
    try:
        _quiet(w)
        _settle(w)      # 收掉开场表情（构造期那次 _show_state("laugh")）
        yield w
    finally:
        try:
            if not w._closing:
                w._quit()
        except Exception:
            pass
        _restore(snap)


# ---------------- 走路驱动（真 QPixmap 素材 / 真 tick） ----------------

def _start_walking(win):
    """让 pet_wander.tick 走"跟随鼠标"那一支：窗口挪远 → 光标在 (0,0) → 一定会走。"""
    win._sleeping = False
    win.busy = False
    win._flying = False
    win.cfg["follow_mouse"] = True
    win.cfg["wander"] = False
    win.move(600, 600)
    win.wander.tick()


def _stop_walking(win):
    """全关 = tick 走 target is None 那一支 → 停下回 idle。"""
    win.cfg["follow_mouse"] = False
    win.cfg["wander"] = False
    win.wander.tick()


def _walk_assets():
    return pet_anim.load_frame_set(os.path.join(HERE, "assets"),
                                   main._WALK_FRAME_PREFIX, main._WALK_FRAME_COUNT)


def _drive(anim):
    """把在途动画**确定性**推到终态（不看钟）。"""
    assert anim is not None, "没有在途动画：这一条动效根本没发生"
    anim.setCurrentTime(anim.duration())
    _app().processEvents()


def _assert_crossfade(win, label, base):
    """一次状态切换的交叉淡入**全过程**判据（判据 4 + 6）。"""
    anim = win._crossfade_anim
    assert anim is not None, "%s：没有交叉淡入（_crossfade_anim 为 None）" % label
    assert anim.duration() == pet_motion.DUR["TRANSITION"], \
        "%s：交叉淡入时长没走令牌表（%r）" % (label, anim.duration())
    assert win.ghost_item.isVisible(), "%s：ghost 没显示（旧帧没有淡出）" % label
    # 帧推进是**墙钟**驱动的：它可能在下面 processEvents() 里到点并插入一次收尾回调
    # （_state_done / _eat_done → _play_idle），把这次淡入顶掉。停掉帧表 → 判据确定性。
    win.anim.stop()
    geom = _geometry(win)
    # 中点：两帧都可见（两层的 opacity 都在 (0,1)，和仍在 (0,2)）
    anim.setCurrentTime(anim.duration() // 2)
    _app().processEvents()
    op_item, op_ghost = win.item.opacity(), win.ghost_item.opacity()
    assert 0.0 < op_item < 1.0, "%s：新第一帧没在淡入（item opacity=%r）" % (label, op_item)
    assert 0.0 < op_ghost < 1.0, "%s：旧最后一帧没在淡出（ghost opacity=%r）" % (label, op_ghost)
    assert 0.0 < op_item + op_ghost < 2.0, "%s：两层 opacity 之和越界" % label
    assert _geometry(win) == geom, "%s：交叉淡入改了角色几何（A4：只许动 opacity）" % label
    # 收尾：ghost 隐藏回基线、主体不透明、场景对象数不变
    anim.setCurrentTime(anim.duration())
    _app().processEvents()
    assert win._crossfade_anim is None, "%s：收尾后仍挂着动画对象" % label
    assert not win.ghost_item.isVisible(), "%s：收尾后 ghost 仍可见" % label
    assert win.item.opacity() == 1.0, "%s：收尾后主体不是不透明（留了半截 opacity）" % label
    assert len(win.scene.items()) == base, \
        "%s：场景对象数没回基线（%d != %d）" % (label, len(win.scene.items()), base)
    assert _geometry(win) == geom, "%s：收尾时改了角色几何" % label


# ===================== 判据 1 / 2：走路播帧 + 位移仍被驱动 =====================

def test_walk_plays_the_walk_frame_set_and_stops_back_to_idle(win):
    """走路时 anim 播的就是 "walk" 帧集（真 assets/walk_f*.png），停下回 "idle"。

    能真失败：
      · 删掉 _on_frame_changed 里的 "walk" → 帧集在播、item.pixmap 不更新（本用例的
        cacheKey 断言红，见下）；
      · 删掉 _walk_anim 里那次 anim.play("walk", ...) → anim._name 仍是 "idle" →
        第一条断言红；
      · 删掉 _walk_anim(False) 里的 _play_idle() → 停下那条断言红。
    """
    frames = _walk_assets()
    assert len(frames) == main._WALK_FRAME_COUNT, \
        "assets/walk_f*.png 与 _WALK_FRAME_COUNT 对不上（磁盘为准：%d 帧）" % len(frames)
    assert not (win.anim._sets.get("walk") or []), "前提：还没走过路，walk 槽应当是空的"
    before = (win.x(), win.y())
    _start_walking(win)
    assert win.anim_mode == "walk", "走路时 anim_mode 不是 walk（%r）" % (win.anim_mode,)
    assert win.anim._name == "walk", "走路时播的不是 walk 帧集（%r）" % (win.anim._name,)
    assert win.anim._frames is win.anim._sets.get("walk"), "anim 播的不是刚注册的 walk 帧集"
    assert len(win.anim._sets.get("walk") or []) == len(frames)
    assert win.anim._timer.isActive(), "走路帧没有在推进（定时器没起）"
    # 帧真的贴到画面上了（漏改 _on_frame_changed 的那条洞）
    assert win.anim.current() is not None
    assert win.item.pixmap().cacheKey() == win.anim.current().cacheKey(), \
        "anim 在播 walk、画面却不是 walk 的第一帧（_on_frame_changed 漏了 walk？）"
    # 判据 2：位移仍由 pet_wander 驱动
    assert (win.x(), win.y()) != before, "走路位移没被驱动（位置没变）"
    assert win.squash_y in (0.95, 1.0), "走路 squash 起伏没了（静态兜底那条老路也被破坏了）"
    # 停下 → 回 idle
    _stop_walking(win)
    assert win.anim_mode == "idle", "停下后 anim_mode 没回 idle（%r）" % (win.anim_mode,)
    assert win.anim._name == "idle", "停下后播的不是 idle 帧集（%r）" % (win.anim._name,)


def test_walk_assets_are_the_same_canvas_as_the_character():
    """walk 帧必须与 character.png **同画布**（否则走路时角色会一跳一跳）。"""
    from PySide6.QtGui import QPixmap
    char = QPixmap(os.path.join(HERE, "assets", "character.png"))
    frames = _walk_assets()
    assert len(frames) == main._WALK_FRAME_COUNT == 8
    assert [(f.width(), f.height()) for f in frames] == [(char.width(), char.height())] * len(frames), \
        "walk 帧画布与 character.png 不一致：%r vs %r" % (
            [(f.width(), f.height()) for f in frames], (char.width(), char.height()))
    # 物理：8 帧两两不同（否则"播帧"等于没播）
    keys = {f.cacheKey() for f in frames}
    assert len(keys) == len(frames), "walk 帧里有重复帧"


# ===================== 判据 3：无帧集角色的静态兜底 =====================

def test_role_without_walk_frames_keeps_the_static_fallback(win, tmp_path):
    """自定义角色「形态×动作」表里没有 walk → **保持静态图 + squash 走路**，零异常。

    能真失败：把 _walk_anim 里 "if not frames: return False" 那条兜底删掉（改成无条件
    anim.play("walk", ...)）→ walk 槽是空集 → FrameAnim.play 返回 False 且把 _name 置 None
    → anim_mode 变成 "walk" 而画面不更新；本用例的 anim_mode / pixmap / 定时器三条都会红。
    """
    _install_bare_role(win, tmp_path)
    _settle(win)
    assert win._custom_role and not win.has_frames, "前提：一个没有帧集的角色"
    side = win.sprites[win.form]["side"]
    before = (win.x(), win.y())
    _start_walking(win)          # 不许抛：这一行本身就是"零异常"判据
    assert win.anim_mode != "walk", "无帧集角色被切进了 walk（应当静态兜底）"
    assert not (win.anim._sets.get("walk") or []), "无帧集角色的 walk 槽不是空的"
    assert win.anim._timer.isActive() is False, "无帧集角色起了帧动画（应当静态图）"
    assert win.item.pixmap().cacheKey() == side.cacheKey(), "静态侧身图没了（画面不是 side）"
    assert (win.x(), win.y()) != before, "无帧集角色不走路了（兜底把它冻住了）"
    assert win.squash_y in (0.95, 1.0), "无帧集角色的 squash 起伏没了"


def test_walk_frames_are_not_borrowed_across_roles(win, tmp_path):
    """换到"没有 walk"的角色后，上一任角色的走路帧**不许**留在槽里被误播。

    能真失败：删掉 _wire_anim_sets 自定义分支里的 `self.anim.add_set("walk", [])` →
    默认角色解好的 8 帧还留在 anim._sets["walk"]，本用例第一条断言红（而且那个角色会
    真的播别人家的走路帧）。
    """
    from helpers_roles import install_three_form_role
    _start_walking(win)
    assert win.anim._sets.get("walk"), "前提：默认角色已经解出走路帧"
    install_three_form_role(win, tmp_path, with_animations=False)
    _settle(win)
    assert win._custom_role
    assert not (win.anim._sets.get("walk") or []), \
        "换角色后走路帧还在槽里（会被误播）：%r" % (len(win.anim._sets.get("walk") or []),)
    before = (win.x(), win.y())
    _start_walking(win)
    assert win.anim_mode != "walk"
    assert (win.x(), win.y()) != before


# ===================== 判据 4 / 6：交叉淡入 + 几何 =====================

def test_crossfade_keeps_both_frames_visible_then_returns_to_baseline(win):
    """idle → 表情：两帧同时可见（两层 opacity 都在 (0,1)），收尾后回基线。

    能真失败：
      · _begin_anim_switch 不 show ghost → "ghost 没显示"红；
      · _end_anim_switch 不做 valueChanged（只建动画不写 opacity）→ 中点两条 opacity 红；
      · 收尾不 hide ghost → "ghost 仍可见"红；
      · 把 ghost 改成临时 addItem → 场景对象数回基线那条红。
    """
    _quiet(win)
    base = len(win.scene.items())
    old = win.item.pixmap()
    assert old is not None and not old.isNull(), "前提：画面上有 idle 帧"
    win._show_state("laugh")
    assert win.ghost_item.pixmap().cacheKey() == old.cacheKey(), "ghost 上不是「上一帧」"
    new_pix = win._state_pix("laugh")
    assert new_pix is not None, "前提：laugh 状态图建不出来（这条用例就测不到了）"
    assert win.item.pixmap().cacheKey() == new_pix.cacheKey(), "item 上不是新状态的第一帧"
    _assert_crossfade(win, "idle→state", base)
    assert win.anim_mode == "state"


def test_the_frame_switch_does_not_touch_any_geometry(win):
    """**切到走路帧**这个动作本身一个几何量都不写（A4；走路 squash 是既有行为，另算）。

    能真失败：在 _walk_anim 里写 scale / squash / setFixedSize / item.setTransform 中任意
    一个 → 本用例逐项比对的五元组立刻红（这是 A4 那条硬口径的钉子）。
    """
    _quiet(win)
    win.squash_x = win.squash_y = 1.0
    win._apply_transform()
    geom = _geometry(win)
    assert win._walk_anim(True) is True, "前提：默认角色应当能切到走路帧"
    assert _geometry(win) == geom, "切到走路帧改了角色几何（交叉淡入只许动 opacity）"
    _assert_crossfade(win, "idle→walk", len(win.scene.items()))
    assert _geometry(win) == geom, "走路帧切换收尾后几何变了"


# ===================== 判据 5：减少动效 = 瞬时 =====================

def test_crossfade_is_instant_when_motion_is_reduced(win):
    """「减少动效」→ 时长 0 = 瞬时切帧：不建动画对象、不留半截 opacity、结果帧正确。

    能真失败：
      · _begin_anim_switch 不判 duration_ms（无条件建动画）→ "_crossfade_anim 不是 None"红；
      · 只把时长设 0 却仍 show ghost / 写 opacity → "ghost 可见" / "opacity != 1" 红。
    """
    _quiet(win)
    win._set_reduce_motion(True)
    assert win._reduce_motion() is True, "前提：开关没打开"
    assert pet_motion.duration_ms("TRANSITION", True) == 0
    # 结构判据：减少动效下"淡入"**根本不该开始** —— _begin_anim_switch 必须当场返回 0，
    # 而不是"建一个 0ms 动画再让它自己跑完"（后者仍产生动画对象、还可能闪一下半透明）。
    assert win._begin_anim_switch("state") == 0, \
        "减少动效下 _begin_anim_switch 仍然开始了淡入（返回了非 0 代次）"
    assert not win.ghost_item.isVisible() and win.item.opacity() == 1.0
    new_pix = win._state_pix("laugh")
    assert new_pix is not None
    win._show_state("laugh")
    assert win._crossfade_anim is None, "减少动效下仍产生了交叉淡入动画对象"
    assert not win.ghost_item.isVisible(), "减少动效下 ghost 仍被显示"
    assert win.item.opacity() == 1.0, "减少动效下留下了半截 opacity（%r）" % (win.item.opacity(),)
    assert win.item.pixmap().cacheKey() == new_pix.cacheKey(), "减少动效下结果帧不对"
    # 开关**在淡入途中的那一刻被打开**：在途交叉淡入必须立刻收到终态（不留半透画面）
    win._set_reduce_motion(False)
    win._play_idle()
    if win._crossfade_anim is None:
        win._show_state("laugh")
    assert win._crossfade_anim is not None, "前提：先起一次真的交叉淡入"
    win._set_reduce_motion(True)
    assert win._crossfade_anim is None, "打开「减少动效」后仍挂着在途的交叉淡入"
    assert not win.ghost_item.isVisible() and win.item.opacity() == 1.0, \
        "打开「减少动效」后在途淡入留下了半截画面"
    # 反向：关掉开关后同一条路径**真的**淡入（否则上面那条"不产生"是空转）
    win._set_reduce_motion(False)
    win._show_state("laugh")   # idle → state（真的换一次状态，不是重贴同一帧）
    assert win._crossfade_anim is not None, "关掉减少动效后没有交叉淡入（开关判据是空转）"
    _drive(win._crossfade_anim)
    assert not win.ghost_item.isVisible() and win.item.opacity() == 1.0


# ===================== 判据 7：令牌消费点（C-09 反向钉子） =====================

def test_crossfade_duration_comes_from_the_transition_token(win):
    """时长只从 pet_motion.DUR["TRANSITION"] 来，且消费点写在**扫描面内**的 桌宠.py。

    能真失败：
      · 把 duration_ms("TRANSITION", ...) 换成字面量 160 → C-09 的反向钉子
        （tests/test_motion_v2110.py::test_every_token_in_the_table_is_actually_used）
        会因为 TRANSITION 变成死键而红；本用例的 duration 断言也会红（160 != 200）；
      · 把开关实参写成 False → test_all_animation_durations_go_through_the_table 的
        AST 实参形状判据红。
    """
    assert 100 <= pet_motion.DUR["TRANSITION"] <= 200, "交叉淡入必须落在 100–200ms 区间"
    _quiet(win)
    win._show_state("laugh")
    anim = win._crossfade_anim
    assert anim is not None
    assert anim.duration() == pet_motion.DUR["TRANSITION"], \
        "交叉淡入时长没走令牌表（%r）" % (anim.duration(),)
    _drive(anim)
    src = open(os.path.join(HERE, "桌宠.py"), encoding="utf-8").read()
    assert 'duration_ms("TRANSITION", self._reduce_motion())' in src, \
        "消费点没写在扫描面内的 桌宠.py（或者没把开关带进去）"


# ===================== 逐条列举：每个状态切换点都要淡 =====================

def test_every_state_switch_crossfades(win):
    """idle↔walk↔eat↔poke↔sleep 每一对切换都交叉淡入（w2-b 的覆盖面本身）。

    能真失败：把任意一处 _begin_anim_switch/_end_anim_switch 删掉 → 对应那一步的
    "_crossfade_anim 为 None" 立刻红（每一步都单独走一遍淡入全过程）。
    """
    _quiet(win)
    base = len(win.scene.items())
    # ① idle → state（表情）
    win._show_state("laugh")
    _assert_crossfade(win, "idle→state", base)
    win._state_timer.stop()
    # ② state → idle
    win._play_idle()
    _assert_crossfade(win, "state→idle", base)
    # ③ idle → walk
    win._walk_anim(True)
    _assert_crossfade(win, "idle→walk", base)
    # ④ walk → idle
    win._walk_anim(False)
    _assert_crossfade(win, "walk→idle", base)
    # ⑤ idle → eat（先把吃帧集补上：否则 play 会同步回调 _eat_done，走的是嵌套切换那条路）
    win._ensure_default_frames(("eat",))
    win._wire_key = None
    win._wire_anim_sets()
    assert win.anim._sets.get("eat"), "前提：默认角色的吃帧集没补上"
    win._play_eat()
    _assert_crossfade(win, "idle→eat", base)
    win.anim.stop()
    if win._eat_watchdog is not None:
        win._eat_watchdog.stop()
    # ⑥ eat → idle
    win._play_idle()
    _assert_crossfade(win, "eat→idle", base)
    # ⑦ idle → sleep
    win._show_sleep()
    _assert_crossfade(win, "idle→sleep", base)
    # ⑧ sleep → idle（_wake 是唯一唤醒路径）
    win._wake()
    _assert_crossfade(win, "sleep→idle", base)
    assert win.anim_mode == "idle"


def test_poke_frames_and_form_idle_crossfade_too(win, tmp_path):
    """自定义角色的**帧动作（poke）**与**无帧形态（form_idle）**同样要淡。

    能真失败：删掉 _show_state 里 poke 那一支的 begin/end → "poke 帧动作"红；删掉
    _play_idle 静态分支的 force 判据（只比 anim_mode）→ form_idle 那条红
    （_set_form 已经先把 anim_mode 写成 form_idle 了）。
    """
    from helpers_roles import install_three_form_role
    install_three_form_role(win, tmp_path, with_animations=True)
    _quiet(win)
    _settle(win)
    base = len(win.scene.items())
    assert win._custom_role and win.has_frames, "前提：带帧集的自定义角色"
    assert win.anim._sets.get("poke"), "前提：这个角色的 f0 带 poke 帧"
    # poke 帧动作（loops=1，_state_done 收尾；这里手动停掉定时器，只验淡入）
    win._show_state("puzzled")
    _assert_crossfade(win, "idle→poke", base)
    win._state_timer.stop()
    win.anim.stop()
    win._play_idle()
    _drive(win._crossfade_anim)
    # form_idle：切到一个**没有 idle 帧集**的形态（f2 只有 sleep 帧）
    win._set_form("f2")
    assert win.anim_mode == "form_idle", "前提：这个形态应当走静态（%r）" % (win.anim_mode,)
    assert win._crossfade_anim is not None, "切到无帧形态（form_idle）没有交叉淡入"
    _assert_crossfade(win, "idle→form_idle", base)


# ===================== 走路停止的另一条路：restart() =====================

def test_turning_follow_off_stops_the_walk_animation(win):
    """把跟随/散步全关（走的是 WanderController.restart）也要回到 idle，不能停在走帧上。

    能真失败：删掉 restart() 里那行 pet._walk_anim(False) → 停下后 anim_mode 仍是 "walk"。
    """
    _start_walking(win)
    assert win.anim_mode == "walk"
    win.cfg["follow_mouse"] = False
    win.cfg["wander"] = False
    win.wander.restart()
    assert win.anim_mode == "idle", "关掉跟随后还停在走路帧上（%r）" % (win.anim_mode,)
    assert win.anim._name == "idle"


# ===================== 非首形态守卫：吃饱形态不借常态走帧 =====================

def test_full_form_walk_does_not_borrow_the_first_form_frames(win):
    """吃饱形态下走路**不借**常态走帧（找茬 #8：_walk_anim 的非首形态守卫零用例）。

    为什么必须有这条：默认角色的 assets/walk_f*.png 画的是**首形态（常态）**。吃饱形态
    借来播 = 把吃饱图换成常态图（v2.2.5 修的就是这个症状）；_walk_anim 里那段
    「if not self._custom_role and self.form != self.form_keys[0]」守卫此前一条用例都没
    碰过，删掉它全仓照样绿。

    能真失败：删掉那段守卫（三行）→ 吃饱形态会解出并播上常态走帧 → 本用例的
    「walk 槽为空」「anim 播的不是 walk」「画面仍在吃饱 idle 帧集里」三条会红。
    反向对照在**同一个用例内部**：切回首形态后同一个调用必须真的进 walk —— 否则前面
    "没进 walk" 可能只是"根本没走起来"（空转）。
    """
    _quiet(win)
    assert win.form == win.form_keys[0], "前提：默认角色从首形态（常态）起步"
    win._set_form(win.form_keys[1], display_only=True)     # = "full"（吃饱）
    assert win.form == win.form_keys[1], "前提：没切到吃饱形态"
    _settle(win)
    idle = win.anim._sets.get("idle") or []
    assert idle, "前提：吃饱形态没有自己的 idle 帧集（这条就测不到「不许借」）"
    assert not (win.anim._sets.get("walk") or []), "前提：此刻走路帧还没被解出来"
    idle_keys = {f.cacheKey() for f in idle}
    before = (win.x(), win.y())
    _start_walking(win)                    # 不许抛：这一行本身就是"零异常"判据
    assert win.anim_mode != "walk", \
        "吃饱形态被切进了走路帧（非首形态守卫没挡住，借了常态走帧）"
    assert win.anim._name != "walk", "吃饱形态的 anim 在播 walk 帧集"
    assert not (win.anim._sets.get("walk") or []), \
        "吃饱形态把常态走路帧解出来/注册进 walk 槽了（换了形态就会误播常态图）"
    assert win.item.pixmap() is not None and win.item.pixmap().cacheKey() in idle_keys, \
        "吃饱形态的画面被换了（不是该形态的 idle 帧）"
    assert (win.x(), win.y()) != before, "吃饱形态不走路了（守卫把位移也一起挡了）"
    # 反向对照：切回首形态，同一个调用必须真的进 walk
    win._set_form(win.form_keys[0], display_only=True)
    _settle(win)
    _start_walking(win)
    assert win.anim_mode == "walk", "切回常态后也没进走路帧（反向对照失败）"
    assert win.anim._sets.get("walk"), "切回常态后走路帧没被解出来"

# ===================== 走路停止的第三条路：三条早退（睡着 / busy / 飞行） =====================

def _walk_frame_keys(win):
    """当前 walk 槽里那批帧的 cacheKey 集合（"画面上是不是走路帧"的唯一口径）。"""
    return [f.cacheKey() for f in (win.anim._sets.get("walk") or [])]


@pytest.mark.parametrize("label,attr", [
    ("睡着", "_sleeping"),
    ("busy", "busy"),
    ("飞行", "_flying"),
])
def test_early_exits_stop_the_walk_frames(win, label, attr):
    """散步途中进入 睡着 / busy / 飞行：tick 的早退**必须**先停走帧，再 return。

    为什么必须有这条（三审找茬 #7 的另一半）：pet_wander.tick 的三条早退此前只 return、
    不调 _walk_anim(False) → 走帧集继续循环播放：喂食飞盘那 450ms（_fly_food 先置 busy，
    到落嘴才换吃帧）、甩抛飞行全程、散步中入睡 —— 用户看到的是"原地迈腿 / 空中划水"。

    判据（确定性口径，不睡墙钟、不赌定时器）：
      · anim_mode 不再 "walk"，anim 播的也不再是 walk 帧集（结构身份）；
      · 按定时器**同一个入口** anim._advance() 推进 5 帧 → 贴到画面上的**没有一帧**是
        walk 帧（"不再换帧"的可复现写法：真起定时器就得看钟，这里直接推帧）；
      · **反向对照（同用例内）**：把状态清掉后再 tick，必须**真的**回到 walk —— 否则
        上面"没进 walk"可能只是"根本没走起来"（空转）。

    能真失败：删掉 pet_wander.tick 该状态早退前的那一行 pet._walk_anim(False) →
    anim_mode 仍是 "walk"，第一条断言立刻红（影子副本实测见交付报告）。
    """
    _quiet(win)
    assert not _walk_frame_keys(win), "前提：此刻还没走过路，walk 槽应当是空的"
    _start_walking(win)
    assert win.anim_mode == "walk", "前提：先进到走路帧（%r）" % (win.anim_mode,)
    walk_keys = _walk_frame_keys(win)
    assert walk_keys, "前提：走路帧集没解出来"
    assert win.item.pixmap().cacheKey() in walk_keys, "前提：画面此刻是走路帧"
    setattr(win, attr, True)
    win.wander.tick()                       # ← 被考的那一次 tick（走早退分支）
    assert win.anim_mode != "walk", \
        "%s：tick 早退没停走帧，anim_mode 仍是 walk（走帧还在循环播放）" % label
    assert win.anim._name != "walk", "%s：anim 还在播 walk 帧集" % label
    assert win.anim._frames is not win.anim._sets.get("walk"), \
        "%s：anim 仍指向 walk 帧集（只是改了个状态名）" % label
    assert win.item.pixmap().cacheKey() not in walk_keys, \
        "%s：画面还停在走路帧上（没回 idle）" % label
    # "不再换帧"：推进 5 帧，一帧走路图都不许再露出来
    for i in range(5):
        win.anim._advance()
        assert win.item.pixmap().cacheKey() not in walk_keys, \
            "%s：停下后推进第 %d 帧又贴上了走路帧（走帧还在播）" % (label, i + 1)
    # 反向对照：状态恢复后同一个 tick 必须真的回到 walk
    setattr(win, attr, False)
    _start_walking(win)
    assert win.anim_mode == "walk", \
        "%s：状态恢复后没回到走路帧（反向对照失败，前面的判据可能是空转）" % label
    assert win.anim._name == "walk", "%s：状态恢复后 anim 没播 walk 帧集" % label
    assert win.item.pixmap().cacheKey() in walk_keys, \
        "%s：状态恢复后画面没回到走路帧" % label

