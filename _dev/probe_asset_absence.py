# -*- coding: utf-8 -*-
"""素材缺失探针（只读测量）：整个 assets 目录不可用时，各消费点到底怎么降级。

用法：python _dev/probe_asset_absence.py
（无参数。跑完看 stdout：每条一个 [ok] / [EXC]；有 [EXC] 时退出码 1。）

它做什么：在 %TEMP% 里造一个**临时资源根**（连 assets 目录都没有）与临时数据目录，
把 桌宠.app_dir 指过去再构造 PetWindow，然后逐条调用消费点并打印结果：
  · 构造：sprites 是否回退到 200×200 程序化占位鱼、idle 帧集是否为空；
  · 启动分片接力：直接驱动 _startup_assets_step（**不经 _gslot**，异常不许被守卫吞），
    打印收敛轮数与 pending；
  · 消费点：_play_idle / _show_state / _state_pix / feed / _start_petting / _end_petting；
  · 撒钱预载：_preload_money_fx + _money_preload_step（assets/fx 不存在）与 _fx_celebrate；
  · 音效：pet_audio.init(不存在的 sounds 目录) + 全部 kind 的 play（winsound 换成记录器，不出声）；
  · 数据文件：临时数据目录里首次启动生成了哪些文件、是否合法 JSON。

**真实 assets/ 全程只读**：探针只 os.walk + 复制/读取，不 rename/remove 任何发行素材；
数据目录也整体指向 %TEMP%（跑完删掉）。用例版本见 tests/test_asset_absence_v244.py，
用户可感知的降级清单见 _dev/asset_absence_report.md。
"""
import json
import os
import shutil
import sys
import tempfile
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass  # 有意忽略：老解释器/重定向场景下保持默认编码

import 桌宠 as main  # noqa: E402
import pet_audio  # noqa: E402
import pet_log  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

FAILS = []


def check(tag, fn):
    """调一次 fn，打印 ok/EXC；异常记进 FAILS（探针最后据此给退出码）。"""
    try:
        print("  [ok ] %-28s -> %r" % (tag, fn()))
    except Exception as e:  # noqa: BLE001
        FAILS.append(tag)
        print("  [EXC] %-28s -> %s: %s" % (tag, type(e).__name__, e))
        traceback.print_exc()


def main_probe():
    fake = tempfile.mkdtemp(prefix="probe_assets_")
    data = tempfile.mkdtemp(prefix="probe_data_")
    QApplication.instance() or QApplication([])
    main.app_dir = lambda: fake                      # 唯一的开关：资源根指到空目录
    main.DATA_DIR = data
    main.CONFIG_PATH = os.path.join(data, "config.json")
    main.USAGE_PATH = os.path.join(data, "usage.json")
    main.MEMORY_PATH = os.path.join(data, "memory.json")
    pet_log.set_data_dir(data)
    print("临时资源根：%s（没有 assets 目录）\n临时数据目录：%s\n" % (fake, data))

    print("== A. 构造 ==")
    win = main.PetWindow()
    print("  custom=%r form=%r form_keys=%r" % (win._custom_role, win.form, win.form_keys))
    print("  assets_dir=%r exists=%r" % (win._assets_dir, os.path.isdir(win._assets_dir)))
    print("  idle=%d idle_full=%d eat=%d petpet=%d has_frames=%r" % (
        len(win._idle_frames), len(win._idle_full_frames), len(win._eat_frames),
        len(win._fx_petpet), win.has_frames))
    side = win.sprites["normal"]["side"]
    print("  常态侧图：%dx%d null=%r（200×200 = 程序化占位鱼）" % (
        side.width(), side.height(), side.isNull()))

    print("\n== B. 启动分片接力（直接驱动，不经 _gslot）==")
    rounds = 0
    try:
        while not win._startup_assets_done and rounds < 40:
            rounds += 1
            win._startup_assets_step()
        print("  [ok ] 收敛：%d 轮 done=%r pending=%r" % (
            rounds, win._startup_assets_done, win._state_pix_pending))
    except Exception as e:  # noqa: BLE001
        FAILS.append("startup_relay")
        print("  [EXC] 接力：%s: %s" % (type(e).__name__, e))
        traceback.print_exc()

    print("\n== C. 消费点 ==")
    check("_play_idle()", lambda: win._play_idle())
    check("_show_state('laugh')", lambda: win._show_state("laugh"))
    check("_state_pix('angry')", lambda: win._state_pix("angry"))
    check("feed('小鱼干')", lambda: win.feed("小鱼干"))
    win.busy = False
    win._press_dist = 0
    check("_start_petting()", lambda: win._start_petting())
    print("     _petting=%r _fx_petpet_on=%r（缺 petpet 帧 → 静默跳过）"
          % (win._petting, getattr(win, "_fx_petpet_on", None)))
    check("_end_petting()", lambda: win._end_petting())

    print("\n== D. 撒钱预载（assets/fx 不存在）==")
    win._fx_money = []
    win._money_preload = None
    check("_preload_money_fx()", lambda: win._preload_money_fx())
    steps = 0
    try:
        while win._money_preload is not None and steps < 200:
            steps += 1
            win._money_preload_step()
        print("  [ok ] 收敛：%d 片 preload=%r fx_money=%d 帧" % (
            steps, win._money_preload, len(win._fx_money)))
    except Exception as e:  # noqa: BLE001
        FAILS.append("money_preload")
        print("  [EXC] 预载：%s: %s" % (type(e).__name__, e))
        traceback.print_exc()
    check("_fx_celebrate()", lambda: win._fx_celebrate())
    print("     _fx_money_on=%r（空帧集 → 不进撒钱播放态）" % (win._fx_money_on,))

    print("\n== E. 音效（sounds 目录不存在）==")
    pet_audio.init(os.path.join(fake, "assets", "sounds"))
    print("  wav_paths 全 None=%r；合成回退音=%r" % (
        all(v is None for v in pet_audio._wav_paths.values()), sorted(pet_audio._fallback)))

    class _FakeWinsound:
        SND_MEMORY = 0x4
        SND_NODEFAULT = 0x2
        SND_FILENAME = 0x20000
        SND_ASYNC = 0x1
        SND_NOWAIT = 0x2000
        calls = []

        @staticmethod
        def PlaySound(sound, flags):
            _FakeWinsound.calls.append((type(sound).__name__, flags))

    pet_audio.winsound = _FakeWinsound
    for kind in list(pet_audio._PLAY_MAP) + ["__no_such_kind__"]:
        check("play(%r)" % kind, lambda k=kind: pet_audio.play(k))
    print("  winsound 调用：%r（bytes + SND_MEMORY = 合成回退音）" % (_FakeWinsound.calls,))

    print("\n== F. 运行时数据文件（首次启动自动生成）==")
    names = sorted(os.listdir(data))
    print("  生成：%r" % (names,))
    for name in names:
        p = os.path.join(data, name)
        if os.path.isfile(p) and name.endswith(".json"):
            try:
                json.load(open(p, encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                FAILS.append("data:" + name)
                print("  [EXC] %s 不是合法 JSON：%r" % (name, e))

    win._closing = True
    win.hide()
    win.close()
    win.deleteLater()
    shutil.rmtree(fake, ignore_errors=True)
    shutil.rmtree(data, ignore_errors=True)
    print("\n%s（失败 %d 处）" % ("素材缺失探针：全部优雅降级" if not FAILS else
                                 "素材缺失探针：有异常冒出来 -> %r" % (FAILS,), len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main_probe())
