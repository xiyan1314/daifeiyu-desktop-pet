# -*- coding: utf-8 -*-
"""D2 菜单悬停预览的钉子（v2.12.0 第 12 轮 · C 项）。

判据（作业单 §四）：300ms 前不预览、300ms 后预览一次；ledger 前后不变；
预览期间 play_sound / voice.play_event 零调用；默认关。

## 每条能真失败在哪

- 把 HoverPreview.hover 的"同一格不重置"删掉 → test_same_key_does_not_restart 红；
- 把 enabled 判断删掉 → test_disabled_never_previews 红；
- 把 cancel 的 self._key = None 删掉 → test_cancel_drops_pending 红（移开还会补播一次）；
- 把 pet_menu 里 preview=True 删掉 → test_menu_calls_preview_mode 红（会变成真点播：
  落状态、可能发声）；
- 把 pet_actions 预览分支挪到门控之后 → test_preview_branch_precedes_gates 红。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import pet_motion  # noqa: E402
import pet_menu  # noqa: E402


class _Sink(object):
    def __init__(self):
        self.calls = []

    def __call__(self, key):
        self.calls.append(tuple(key))


def test_new_action_returns_delay():
    s = _Sink()
    hp = pet_menu.HoverPreview(300, s)
    assert hp.hover(("emote", "zzz")) == 300
    hp.fire()
    assert s.calls == [("emote", "zzz")]


def test_same_key_does_not_restart():
    s = _Sink()
    hp = pet_menu.HoverPreview(300, s)
    assert hp.hover(("jump", None)) == 300
    assert hp.hover(("jump", None)) == 0      # 同一格上晃鼠标：不重置计时
    hp.fire()
    assert s.calls == [("jump", None)]
    assert hp.hover(("jump", None)) == 300    # 播完再悬停 = 新的一轮


def test_cancel_drops_pending():
    s = _Sink()
    hp = pet_menu.HoverPreview(300, s)
    hp.hover(("jump", None))
    hp.cancel()
    hp.fire()
    assert s.calls == []                      # 移开菜单后一个动作都不许晚到


def test_disabled_never_previews():
    s = _Sink()
    hp = pet_menu.HoverPreview(300, s, enabled=False)
    assert hp.hover(("jump", None)) == 0
    hp.fire()
    assert s.calls == []


def test_no_data_is_not_previewable():
    s = _Sink()
    hp = pet_menu.HoverPreview(300, s)
    assert hp.hover(None) == 0
    assert hp.hover("jump") == 0              # 裸字符串（不是 (name, arg) 元组）不预览
    hp.fire()
    assert s.calls == []


def test_delay_comes_from_motion_token():
    assert pet_motion.duration_ms("PREVIEW") == 300
    src = open(os.path.join(HERE, "pet_menu.py"), encoding="utf-8").read()
    assert 'duration_ms("PREVIEW")' in src


def test_menu_calls_preview_mode():
    src = open(os.path.join(HERE, "pet_menu.py"), encoding="utf-8").read()
    assert "preview=True" in src
    assert "menu_hover_preview" in src
    assert "act_menu.hovered.connect" in src
    assert "act_menu.aboutToHide.connect" in src


def test_preview_branch_precedes_gates():
    src = open(os.path.join(HERE, "pet_actions.py"), encoding="utf-8").read()
    i_prev = src.index("if preview:")
    i_gate = src.index("if pet.busy or pet._petting")
    assert i_prev < i_gate, "预览分支必须在门控之前（否则开着跟随/散步时悬停没反应）"
    seg = "\n".join(ln for ln in src[i_prev:i_gate].splitlines() if not ln.strip().startswith("#"))
    for bad in ("voice.", "play_event", "ledger", "save_cfg", "_save("):
        assert bad not in seg, bad + " 不许出现在预览分支（预览不落状态、不发声）"
