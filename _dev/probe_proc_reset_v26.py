# -*- coding: utf-8 -*-
"""_dev 探针：定位 CI #52 'proc resets to idle' 墙钟失红的**真实机制**（产品代码零改动）。

做法：在导入 桌宠 之后、跑真脚本之前，把 PetWindow.busy / anim_mode 换成会记账的
property（记录"谁把它设成了什么"），并给 _play_proc / _run_anim / _finish_tween /
_play_idle / _stop_tween / _reset_squash / _play_eat / _eat_done 打上进出日志；
另起一条采样线程按 10ms 记录 anim_mode/busy/squash/oy（纯 Python 属性，不碰 Qt 对象）。
然后用 runpy 原样执行 _verify_v13.py。日志落到 _dev/probe_proc_reset_v26.log。

用法：python -B _dev/probe_proc_reset_v26.py [--force jump@200] [--force stall]
  --force jump@N  : 在 sway 起播后 N ms 用 QTimer.singleShot 触发一次 do_jump
                    （模拟 idle_tick 在合成动作播放中插播跳跃）
"""
import os
import runpy
import sys
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

LOGPATH = os.path.join(HERE, "probe_proc_reset_v26.log")
LOG = open(LOGPATH, "w", encoding="utf-8", buffering=1)
T0 = time.monotonic()


def log(msg):
    LOG.write("%10.3f %s\n" % (time.monotonic() - T0, msg))


import 桌宠 as main  # noqa: E402

# ---------------- 账本式 property：谁把 busy / anim_mode 改成了什么 ----------------
_SKIP = {"instrument", "<module>"}


def _who(skip=2):
    out = []
    for fr in traceback.extract_stack()[:-skip]:
        fn = os.path.basename(fr.filename)
        if fn in _SKIP:
            continue
        out.append("%s:%d(%s)" % (fn, fr.lineno, fr.name))
    return " <- ".join(out[-4:])


def _make_prop(priv, label):
    def getter(self):
        return self.__dict__.get(priv)

    def setter(self, val):
        old = self.__dict__.get(priv, "<unset>")
        if old != val:
            log("SET %s: %r -> %r   [%s]" % (label, old, val, _who()))
        self.__dict__[priv] = val
    return property(getter, setter)


main.PetWindow.busy = _make_prop("_probe_busy", "busy")
main.PetWindow.anim_mode = _make_prop("_probe_mode", "anim_mode")

# ---------------- 方法进出日志 ----------------
WATCH = ("_play_proc", "_run_anim", "_finish_tween", "_play_idle", "_stop_tween",
         "_reset_squash", "_show_state", "_play_eat", "_eat_done", "_set_form",
         "_apply_transform")
NOISY = {"_apply_transform"}
ANIM = {"obj": None, "id": None}


def instrument():
    for name in WATCH:
        orig = getattr(main.PetWindow, name, None)
        if orig is None:
            continue

        def make(orig=orig, name=name):
            def wrapper(self, *a, **k):
                if name not in NOISY:
                    log(">> %s(%r) mode=%s busy=%s" % (name, a[:2],
                                                       self.__dict__.get("_probe_mode"),
                                                       self.__dict__.get("_probe_busy")))
                try:
                    r = orig(self, *a, **k)
                except BaseException as e:
                    log("!! %s RAISED %s: %s" % (name, type(e).__name__, e))
                    raise
                extra = ""
                if name == "_run_anim":
                    ANIM["obj"], ANIM["id"] = r, id(r)
                    extra = " anim#%s dur=%r state=%r" % (id(r) % 10000,
                                                          a[0] if a else k.get("duration"),
                                                          _state(r))
                if name not in NOISY:
                    log("<< %s%s mode=%s busy=%s sx=%.4f sy=%.4f oy=%r" % (
                        name, extra, self.__dict__.get("_probe_mode"),
                        self.__dict__.get("_probe_busy"), self.squash_x,
                        self.squash_y, getattr(self, "_proc_offset_y", None)))
                return r
            return wrapper
        setattr(main.PetWindow, name, make())


def _state(anim, cur=None):
    try:
        return (int(anim.state()), anim.currentTime(), anim.duration())
    except Exception as e:  # 对象可能已被 deleteLater 销毁
        return "<%s>" % (e,)


# ---------------- 采样线程 ----------------
_STOP = threading.Event()


def sampler(pet_holder):
    last = None
    while not _STOP.is_set():
        pet = pet_holder.get("pet")
        if pet is not None:
            try:
                snap = (pet.__dict__.get("_probe_mode"), pet.__dict__.get("_probe_busy"),
                        round(float(pet.squash_x), 4), getattr(pet, "_proc_offset_y", None),
                        _state(ANIM["obj"]) if ANIM["obj"] is not None else None)
            except Exception as e:
                snap = ("<sampler err %r>" % (e,),)
            if snap != last:
                log("   sample %r" % (snap,))
                last = snap
        _STOP.wait(0.01)


def main_probe():
    instrument()
    pet_holder = {"pet": None}
    # 抓 PetWindow 实例：patch __init__
    orig_init = main.PetWindow.__init__

    def init(self, *a, **k):
        orig_init(self, *a, **k)
        pet_holder["pet"] = self
        log("PetWindow created")
    main.PetWindow.__init__ = init

    force = None
    if "--force" in sys.argv:
        force = sys.argv[sys.argv.index("--force") + 1]

    if force == "prejump":
        # 模拟"上一拍闲逛节拍在**别的 check 的事件循环里**插播了一次 jump，此后没有任何
        # 事件处理 → 动画冻结在途、busy 一直为真"——本段第一个 play_action 有 busy 门控。
        def arm(pet):
            # 注入点选在"动作自定义"段落**之前**最后一个会走到的产品入口（开菜单）：
            # 在那里起一次 jump，之后到本段落开始为止不再泵事件 → 动画冻结在途、busy 为真。
            _om = pet._open_menu

            def wrap(*a, **k):
                r = _om(*a, **k)
                if not getattr(pet, "_probe_prejumped", False):
                    pet._probe_prejumped = True
                    log("PREJUMP: 在动作自定义段落开始前制造一次在途 jump（此后不泵事件）")
                    pet.actions.do_jump()
                return r
            pet._open_menu = wrap
        _orig_init2 = main.PetWindow.__init__

        def init2(self, *a, **k):
            _orig_init2(self, *a, **k)
            arm(self)
        main.PetWindow.__init__ = init2

    if force and force.startswith("jump@"):
        delay = int(force.split("@", 1)[1])
        orig_pp = main.PetWindow._play_proc

        _fired = {"n": 0}

        def pp(self, *a, **k):
            r = orig_pp(self, *a, **k)
            if a and a[0] == "sway" and ("--every" in sys.argv or _fired["n"] == 0):
                _fired["n"] += 1
                log("FORCE: %dms 后触发 do_jump（模拟 idle_tick 插播，第 %d 次 sway）"
                    % (delay, _fired["n"]))
                from PySide6.QtCore import QTimer
                QTimer.singleShot(delay, self, self.actions.do_jump)
            return r
        main.PetWindow._play_proc = pp

    th = threading.Thread(target=sampler, args=(pet_holder,), daemon=True)
    th.start()
    try:
        runpy.run_path(os.path.join(REPO, "_verify_v13.py"), run_name="__main__")
    except SystemExit as e:
        log("verify SystemExit: %r" % (e.code,))
    finally:
        _STOP.set()
        log("done")


if __name__ == "__main__":
    main_probe()
