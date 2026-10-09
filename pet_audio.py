# -*- coding: utf-8 -*-
"""
大肥鱼桌宠 —— 音频模块（阶段 3，R3-1）。

职责：把「参考项目音频素材 + 合成回退」统一封装，供主程序在按压 / 松手 / 喂食时播放。

对外接口：
- init(sounds_dir)：扫描 sounds_dir 下的 ya1.wav / ya2.wav / d1.wav / d2.wav，
  记录存在的文件路径；在 GUI 环境下（QCoreApplication 已创建）预建 QtMultimedia
  QSoundEffect 效果器（回退音在模块加载时已合成）。
- play(kind)：kind ∈ {press, release, feed, reply, coin}，按三级链路播放：
    1) winsound SND_FILENAME 播放 wav 文件（主链路：waveOut 渲染路径，与
       Qt 的进程级 WASAPI 会话是不同路径，实测最稳；SND_ASYNC 异步替换播放）；
    2) QSoundEffect 播放 wav 文件（仅 winsound 不存在时——非 Windows）；
    3) winsound SND_MEMORY 播放合成回退音。
  任何一级失败静默降级到下一级，绝不抛出。
- set_custom_group(group) / clear_custom_group()（v1.3.0 追加）：自定义音效组，
  group 形如 {"press": path|""|None, ...}；play() 开头先查组：""=静音，
  有效路径=winsound 直接播放（失败落回原三级链路），None/缺键=走默认链路。
- preview_file(path)（v1.3.0 追加）：试听单个 wav 文件（winsound 异步），
  成功返回 True；非 wav / 不存在 / 失败返回 False（mp3 由调用方降级 QMediaPlayer）。

实现要点：
- 仅 winsound / wave / os / math / struct 为顶层依赖；PySide6.QtMultimedia 惰性导入，
  模块本身在无 GUI 环境下也可正常 import（冒烟测试走 winsound 路径）。
- 曾用 QSoundEffect 作主链路：它在部分 Windows 机器上会「运行中静默失声」
  （status 仍 Ready、isPlaying 仍 True，但不出声），表现为音效过一会/换形态后消失；
  故主链路回归 winsound，Qt 效果器仅作备份，并监听音频设备变化自动重建。
- 所有播放路径都静默处理异常，绝不抛出，避免打断主循环。

Python 3.10+（项目运行环境 3.10.2）。

MIT License
Copyright (c) 大肥鱼桌宠项目
"""

import math
import os
import struct
import time
import wave

try:
    import winsound  # 仅 Windows 提供；非 Windows 导入失败时置 None
except ImportError:
    winsound = None


# 采样率（与素材 / 参考实现一致）
_SAMPLE_RATE = 22050

# 素材文件名（task-end-a/exp-orb 借自参考插件「任务结束音」概念）
_WAV_NAMES = ("ya1", "ya2", "d1", "d2", "task-end-a", "exp-orb")
_WAV_FILES = {name: name + ".wav" for name in _WAV_NAMES}

# 素材文件路径：name -> 存在文件的绝对路径（缺失 / 损坏为 None）
_wav_paths = {name: None for name in _WAV_NAMES}
# 素材时长：name -> 秒（float）或 None（仅冒烟/诊断打印使用，生产播放路径不消费）
_wav_duration = {name: None for name in _WAV_NAMES}
# QSoundEffect 效果器：name -> QSoundEffect 或 None（QtMultimedia 不可用 / 素材缺失）
_effects = {name: None for name in _WAV_NAMES}
# QSoundEffect 类引用缓存（init 时惰性导入一次，play() 热路径直接使用）
_QSoundEffect = None
# 默认音频设备切换钩子是否已连接（init 幂等调用防重复连接）
_device_hooked = False
# QMediaDevices 实例保活引用（PySide6 6.11 的信号需从实例连接）
_media_devices = None
# 设备切换去抖状态（_on_default_device_changed 用）
_last_rebuild_ts = 0.0
_last_device_id = None


# ---------------- 合成回退音（参考现有 play_sound 实现） ----------------
def _wav_bytes(samples, rate=_SAMPLE_RATE):
    """把 float 采样序列封成 16bit 单声道 PCM 的完整 WAV bytes。"""
    data = b"".join(struct.pack("<h", int(max(-32768, min(32767, s)))) for s in samples)
    out = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt "
    out += struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    out += b"data" + struct.pack("<I", len(data)) + data
    return out


def _synth(freq_start, freq_end, dur, vol=0.5, rate=_SAMPLE_RATE):
    """线性扫频正弦波采样序列（带线性衰减包络）。"""
    n = int(rate * dur)
    out = []
    for i in range(n):
        t = i / rate
        f = freq_start + (freq_end - freq_start) * (i / n)
        env = 1.0 - i / n
        out.append(vol * 32767 * env * math.sin(2 * math.pi * f * t))
    return out


def _build_fallback():
    """预合成 3 个回退音：下行短音=按压、上行短音=松手、喂食音。"""
    return {
        "press": _wav_bytes(_synth(900, 400, 0.09)),    # 下行短音（按压）
        "release": _wav_bytes(_synth(300, 700, 0.22)),  # 上行短音（松手）
        "feed": _wav_bytes(_synth(500, 900, 0.15)),     # 喂食音
    }


# 模块加载即合成回退音，保证即使未调用 init() 也能回退播放
_fallback = _build_fallback()


# ---------------- WAV 素材校验 ----------------
def _probe_wav(path):
    """用 wave 模块校验 WAV，返回 (存在且可读, 时长秒)；失败返回 (False, None)。"""
    try:
        with wave.open(path, "rb") as wf:
            nchannels, sampwidth, framerate, nframes, comptype, _ = wf.getparams()
        # 仅支持未压缩 PCM；压缩格式或非法参数按损坏处理；限制帧数防恶意超大声明
        if comptype != "NONE" or not framerate or nframes <= 0 or nframes > 25_000_000:
            return False, None
        return True, nframes / float(framerate)
    except Exception:
        return False, None


# ---------------- 对外接口 ----------------
def init(sounds_dir):
    """扫描并缓存素材；幂等，可重复调用。回退音已在模块导入时合成，无需重建。"""
    # 重置缓存（重复调用会覆盖旧结果，保持幂等）
    for name in _WAV_NAMES:
        _wav_paths[name] = None
        _wav_duration[name] = None
        _effects[name] = None

    for name in _WAV_NAMES:
        path = os.path.join(sounds_dir, _WAV_FILES[name])
        ok, dur = _probe_wav(path)
        if ok:
            _wav_paths[name] = path
            _wav_duration[name] = dur

    # 惰性构建 QSoundEffect 效果器：仅在 GUI 事件循环存在时（主程序已创建 QApplication）
    global _QSoundEffect
    try:
        from PySide6.QtCore import QCoreApplication, QUrl
        from PySide6.QtMultimedia import QSoundEffect
    except Exception:
        return  # QtMultimedia 不可用：play() 自动走 winsound 文件 / 合成回退
    _QSoundEffect = QSoundEffect
    if QCoreApplication.instance() is None:
        return  # 无 GUI 环境（如冒烟测试）：不构建效果器

    _rebuild_effects()

    # 音频输出设备变化（插拔耳机/切换扬声器）时重建效果器，避免切设备后无声。
    # PySide6 6.11 无 defaultAudioOutputChanged 信号，退而用 audioOutputsChanged
    # （输出设备列表变化即触发），两者皆无则保持旧行为。
    global _device_hooked, _media_devices
    if not _device_hooked:
        try:
            from PySide6.QtMultimedia import QMediaDevices
            # PySide6 6.11：信号必须从 QMediaDevices 实例连接（类属性只是 Signal 描述符）
            _media_devices = QMediaDevices()
            if hasattr(_media_devices, "defaultAudioOutputChanged"):
                _media_devices.defaultAudioOutputChanged.connect(_on_default_device_changed)
                _device_hooked = True
            elif hasattr(_media_devices, "audioOutputsChanged"):
                _media_devices.audioOutputsChanged.connect(_on_default_device_changed)
                _device_hooked = True
        except Exception:
            pass  # 无可用信号：忽略，仍按旧行为运行


def _rebuild_effects():
    """按当前 _wav_paths 重建全部 QSoundEffect 效果器（init / 设备切换共用）。"""
    from PySide6.QtCore import QUrl
    for name in _WAV_NAMES:
        path = _wav_paths.get(name)
        if path is None:
            _effects[name] = None
            continue
        old = _effects.get(name)
        if old is not None:
            try:
                old.stop()  # 停掉旧效果器再替换，避免掐断瞬间的残余播放
            except Exception:
                pass  # 有意忽略：停旧效果器失败（对象可能已销毁），替换照常（尽力而为）
        try:
            eff = _QSoundEffect()
            eff.setSource(QUrl.fromLocalFile(path))
            eff.setVolume(0.9)
            _effects[name] = eff
        except Exception:
            _effects[name] = None  # 构建失败：留给 winsound 兜底


def _on_default_device_changed(*_args):
    """音频输出设备变化：去抖合并成批事件，且仅当默认输出设备真的变了才重建。

    Windows 一次插拔会连发多个 audioOutputsChanged（新增/默认变化/状态变化），
    300ms 去抖 + 设备 id 比对避免风暴式重建（每次重建会掐断正在播的备用音）。
    """
    global _last_rebuild_ts, _last_device_id
    try:
        from PySide6.QtMultimedia import QMediaDevices
        dev_id = QMediaDevices.defaultAudioOutput().id()
    except Exception:
        dev_id = None
    now = time.monotonic()
    if dev_id is not None and dev_id == _last_device_id:
        return  # 默认设备没变：忽略列表噪声
    if now - _last_rebuild_ts < 0.3:
        return  # 去抖：合并成批事件
    _last_rebuild_ts = now
    _last_device_id = dev_id
    _rebuild_effects()


def _winsound_file_play(wav_name):
    """winsound 文件播放（主链路，waveOut 渲染路径，与 Qt 进程级 WASAPI 会话不同）。

    SND_ASYNC：异步播放，新音替换未放完的旧音（快速连按时后一声截断前一声）。
    SND_NOWAIT：现代 Windows 上为空操作，保留仅为兼容遗留系统。
    返回是否已发出（异常为 False）。
    """
    path = _wav_paths.get(wav_name)
    if winsound is None or path is None:
        return False
    # SND_ASYNC 下 PlaySound 对「已不存在/不可读」的文件仍返回成功且不抛异常，
    # 故播放前重探一次文件存在性，失败时让链路继续降级
    try:
        if not os.path.isfile(path):
            return False
    except Exception:
        return False
    try:
        winsound.PlaySound(
            path,
            winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT | winsound.SND_NOWAIT,
        )
        return True
    except Exception:
        return False


# kind -> (素材名, 回退音名)
_PLAY_MAP = {
    "press": ("ya1", "press"),
    "release": ("ya2", "release"),
    "feed": ("d2", "feed"),
    "reply": ("task-end-a", "feed"),   # AI 回复完成音（任务结束，借自参考插件概念）
    "coin": ("exp-orb", "release"),    # 余额到账音（金币）
}


# ---------------- 自定义音效组（v1.3.0 追加） ----------------
# kind -> 绝对路径 | ""（静音） | None（走默认链路）；None = 未启用自定义组
_custom_group = None


def set_custom_group(group):
    """设置自定义音效组：group 形如 {"press": path|""|None, ...}。

    值为 "" 表示该事件静音；None 或缺键表示走默认链路。非 dict 输入忽略。
    """
    global _custom_group
    if isinstance(group, dict):
        _custom_group = dict(group)
    else:
        _custom_group = None


def clear_custom_group():
    """清除自定义音效组，恢复全部默认链路。"""
    global _custom_group
    _custom_group = None


def preview_file(path):
    """试听单个音频文件：仅 wav 且存在时用 winsound 异步播放并返回 True。

    非 wav / 不存在 / 播放失败返回 False，由调用方自行降级（如 mp3 走 QMediaPlayer）。
    """
    if winsound is None:
        return False
    try:
        if not path or not isinstance(path, str):
            return False
        if os.path.splitext(path)[1].lower() != ".wav":
            return False
        if not os.path.isfile(path):
            return False
        winsound.PlaySound(
            path,
            winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT | winsound.SND_NOWAIT,
        )
        return True
    except Exception:
        return False


def _qt_playable(eff):
    """判断 QSoundEffect 是否就绪可播（需要 QSoundEffect 类可见时才能调用）。"""
    cls = _QSoundEffect
    if cls is None or eff is None:
        return False
    try:
        return eff.status() == cls.Status.Ready
    except Exception:
        return False


def play(kind):
    """播放音效：press→ya1 / release→ya2 / feed→d2，三级链路降级；未知 kind 直接返回。"""
    # 0) 自定义音效组优先（v1.3.0）：""=静音直接返回；有效路径=winsound 直接播放，
    #    播放失败继续走原三级链路；None/缺键=原链路。
    group = _custom_group
    if group:
        custom = group.get(kind)
        if custom == "":
            return  # 该事件静音
        if custom:
            try:
                if winsound is not None and os.path.isfile(custom):
                    winsound.PlaySound(
                        custom,
                        winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT | winsound.SND_NOWAIT,
                    )
                    return  # 自定义音已发出
            except Exception:
                pass  # 自定义音播放失败：继续原三级链路
    pair = _PLAY_MAP.get(kind)
    if pair is None:
        return  # 未知 kind：直接返回
    wav_name, fb_name = pair

    # 1) winsound 播放真实 wav 文件（主链路：waveOut 渲染路径，与 Qt 的进程级
    #    WASAPI 会话不同，不受 QSoundEffect 运行中静默失声影响；SND_ASYNC 异步替换）
    if _winsound_file_play(wav_name):
        return

    # 2) QSoundEffect 备用：仅在 winsound 不存在（非 Windows）时使用。
    #    在 Windows 上跳过它——Qt 的「status Ready 但无声」正是本次要修的故障，
    #    若 winsound 瞬时失败而 Qt 静默占位，会挡住第 3 级合成兜底发声。
    if winsound is None:
        eff = _effects.get(wav_name)
        if _qt_playable(eff):
            try:
                eff.play()
                return
            except Exception:
                pass  # 播放入口异常：降级到合成回退

    # 3) 合成回退音（SND_MEMORY 同步播放：CPython 硬编码禁止
    #    SND_MEMORY|SND_ASYNC 组合——会无条件抛 RuntimeError 被吞，导致兜底从不发声。
    #    同步播放会阻塞 0.09~0.24s，仅在最兜底路径发生，可接受）
    if winsound is None:
        return
    data = _fallback.get(fb_name)
    if data is None:
        return
    try:
        winsound.PlaySound(
            data,
            winsound.SND_MEMORY | winsound.SND_NODEFAULT,
        )
    except Exception:
        pass  # 任何异常静默跳过，不抛


# ---------------- 冒烟测试（无需 GUI，可直接运行本文件） ----------------
if __name__ == "__main__":
    # P0-2：以下 print 为命令行冒烟工具输出（python pet_audio.py 运行可见），保留不改为日志
    SOUNDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "sounds")

    print("=== 冒烟 1：真实素材目录（无 GUI → 不建效果器，走 winsound 文件路径） ===")
    init(SOUNDS_DIR)
    for name in _WAV_NAMES:
        p = _wav_paths[name]
        d = _wav_duration[name]
        if p is None:
            print("  %s.wav -> MISSING (None)" % name)
        else:
            dur = ("%.3fs" % d) if d is not None else "N/A"
            print("  %s.wav -> %s, 时长 %s" % (name, p, dur))
    print("  effects built:", sum(1 for e in _effects.values() if e is not None))

    print("=== 冒烟 2：不存在的目录（验证回退路径） ===")
    init(os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "__no_such_dir__"))
    for name in _WAV_NAMES:
        print("  %s.wav -> path=%s" % (name, "None" if _wav_paths[name] is None else "set"))
    for k, pair in _PLAY_MAP.items():
        fb_name = pair[1]
        fb = _fallback.get(fb_name)
        print("  fallback[%s] (via %s) -> %s" % (k, fb_name, "OK (%d bytes)" % len(fb) if fb else "None"))

    print("=== 冒烟 3：调用 play 不抛异常 ===")
    play("press")
    play("release")
    play("feed")
    play("reply")
    play("coin")
    play("未知kind")

    print("=== 冒烟 4：自定义音效组（v1.3.0 追加） ===")
    set_custom_group({
        "press": "",  # 静音
        "release": os.path.join(os.path.dirname(os.path.abspath(__file__)), "__不存在.wav"),
        "feed": None,  # 走默认链路
    })
    play("press")    # 静音：直接返回
    play("release")  # 路径不存在：落回原链路
    play("feed")     # None：原链路
    play("reply")    # 缺键：原链路
    assert preview_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), "__不存在.wav")) is False
    assert preview_file(None) is False
    clear_custom_group()
    play("press")    # 恢复后走原链路

    print("AUDIO SMOKE OK")
