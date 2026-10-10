# -*- coding: utf-8 -*-
"""跨模块常量一致性：同值定义两处时必须锁死，防止将来只改一处导致漂移。"""
import pet_behaviors
import pet_lines
import pet_voice
import pet_widgets


def test_voice_events_match():
    """语音事件白名单：pet_voice.VOICE_EVENTS 与 pet_behaviors.BEHAVIOR_VOICE_EVENTS 必须一致。

    A11 去重（v2.4.2，代理 Q）：合并 tests/test_behaviors.py::test_voice_events_match_pet_voice。
    被合并条写的是 tuple(a) == tuple(b)——把容器类型差异吃掉，**比等值更弱**（一边 list
    一边 tuple 时它仍然绿）；本条的等值断言已经蕴含它。这里再把两侧容器类型也钉住，
    合起来严格强于原两条之和。
    """
    assert isinstance(pet_voice.VOICE_EVENTS, tuple)
    assert isinstance(pet_behaviors.BEHAVIOR_VOICE_EVENTS, tuple)
    assert pet_voice.VOICE_EVENTS == pet_behaviors.BEHAVIOR_VOICE_EVENTS


def test_bubble_style_single_source():
    """气泡默认样式：对话框引用的默认值必须等于 pet_widgets.BUBBLE_STYLE（单一来源）。"""
    import pet_dialogs
    assert pet_dialogs._DEFAULT_BUBBLE_STYLE == pet_widgets.BUBBLE_STYLE


def test_mood_categories_exist():
    """情绪台词类别必须都在台词库类别表里（pet_mood 依赖它们取词）。"""
    moods = ("mood_puzzled", "mood_angry", "mood_hiss", "mood_drool", "mood_cry",
             "mood_smug", "mood_blush")
    for cat in moods:
        assert cat in pet_lines.LINE_CATEGORIES
        assert pet_lines.MOOD_LINES.get(cat)
        assert pet_lines.CATEGORY_LABELS.get(cat)


def test_voice_placeholder_prefixes_cover_errors():
    """错误提示前缀表必须覆盖 explain_api_error 的全部输出（语音跳过表按它匹配）。"""
    import pet_chat
    cases = [pet_chat.explain_api_error(401), pet_chat.explain_api_error(402),
             pet_chat.explain_api_error(403), pet_chat.explain_api_error(404),
             pet_chat.explain_api_error(429), pet_chat.explain_api_error(500),
             pet_chat.explain_api_error(418)]
    for msg in cases:
        assert msg.startswith(pet_chat.API_ERROR_PREFIXES), msg