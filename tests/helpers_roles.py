# -*- coding: utf-8 -*-
"""测试辅助：给 PetWindow 装一个三形态角色（含睡眠/变身/不参与喂食标记 + 真实帧集）。

v2.1.4 改进（审查员 M2）：
  · 带 animations（idle/eat/sleep）→ has_frames=True，喂食走**吃帧路径**
    （此前走 squash 分支，导致"吃帧收尾回调被吞→busy 卡死"这条路径完全没被覆盖）；
  · 经 RoleLibrary._normalize_role 归一化后再入库（不再塞半成品 dict），
    避免"改被测对象以通过测试"。
"""
import os


def _png(path, w=64, h=64, color=(120, 200, 255, 255)):
    from PySide6.QtGui import QColor, QImage
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(QColor(*color))
    img.save(path)


def install_big_frame_role(win, roles_dir, n=8, size=512, noise=True, rid="bigframes1",
                          prefix="big_idle"):
    """装一个"大帧集"角色（n 张 size×size 的 idle 帧）→ 返回 (rid, [绝对路径...])。

    v2.4.1（找茬 M4）：分片解码（_anim_start_async / _anim_chunk_step / _anim_pending）
    此前**零覆盖**——install_three_form_role 的 idle 只有 1 帧，整批永远落在首片里，
    分片状态机一次都没跑过（M3 那个"同步臂作废在途分片"的漏就是这么漏的）。
    噪声内容让 PNG 不可压缩、单帧解码 ~10ms 量级（纯色 512px 图几毫秒就解完，分不出片）。
    只**装**不切换：调用方自己 apply_role（先切再冷缓存，才能复现"冷加载"）。
    roles_dir 传 RoleLibrary._dir（= <数据目录>/roles，角色素材就解析在这里）。
    """
    import random
    from PySide6.QtGui import QColor, QImage

    d = str(roles_dir)
    os.makedirs(d, exist_ok=True)
    rnd = random.Random(20240712)
    names = []
    for i in range(n):
        name = "%s_%02d.png" % (prefix, i)
        img = QImage(size, size, QImage.Format.Format_ARGB32)
        img.fill(QColor(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)))
        if noise:
            for _k in range(3000):
                img.setPixelColor(rnd.randrange(size), rnd.randrange(size),
                                  QColor(rnd.randrange(256), rnd.randrange(256),
                                         rnd.randrange(256)))
        img.save(os.path.join(d, name))
        names.append(name)
    f0 = {"name": "常态", "file": names[0], "animations": {"idle": list(names)},
          "anim_interval_ms": 80}
    raw = {"id": rid, "name": "大帧角色", "file": names[0], "form": "triple",
           "file_full": "", "frames": [names[0]], "added": "", "forms": [f0]}
    norm = win.role_lib._normalize_role(raw) or raw   # 走库自己的归一化（不塞半成品）
    win.role_lib._data["roles"].append(norm)
    win.role_lib._save()
    return rid, [os.path.join(d, x) for x in names]


def install_three_form_role(win, tmp, with_animations=True):
    """装一个三角色：f0 常态（可喂）/ f1 变身 / f2 睡觉（不参与喂食）。"""
    d = os.path.join(str(tmp), "roles")
    os.makedirs(d, exist_ok=True)
    names = ["inv_a.png", "inv_b.png", "inv_eat1.png", "inv_eat2.png", "inv_sleep.png"]
    for n in names:
        _png(os.path.join(d, n))
    f0 = {"name": "常态", "file": "inv_a.png"}
    f1 = {"name": "变身", "file": "inv_b.png", "transform_form": True}
    f2 = {"name": "睡觉", "file": "inv_b.png", "sleep_form": True, "no_feed": True}
    if with_animations:
        f0["animations"] = {"idle": ["inv_a.png"], "eat": ["inv_eat1.png", "inv_eat2.png"],
                            "poke": ["inv_a.png"]}
        f0["anim_interval_ms"] = 80
        # 变身形态也带吃帧：默认角色就是"吃饱形态带吃帧"，喂食后必须走吃帧路径
        f1["animations"] = {"idle": ["inv_b.png"], "eat": ["inv_eat1.png", "inv_eat2.png"]}
        f1["anim_interval_ms"] = 80
        f2["animations"] = {"sleep": ["inv_sleep.png"]}
        f2["anim_interval_ms"] = 80
    f3 = {"name": "待机形态", "file": "inv_b.png"}  # 专用：给 idle_form 用，避开喂食循环
    raw = {"id": "inv1", "name": "不变量角色", "file": "inv_a.png", "form": "triple",
           "file_full": "", "frames": ["inv_a.png"], "added": "", "forms": [f0, f1, f2, f3]}
    norm = win.role_lib._normalize_role(raw) or raw   # 走库自己的归一化（不塞半成品）
    win.role_lib._data["roles"].append(norm)
    win.role_lib._save()
    win.apply_role("inv1")
    return win


def rewrite_big_frames(paths, size=512, seed=7, noise=True, bump_ns=10 ** 9):
    """把既有大帧**原地重写**成新噪声并推 mtime（让 Qt 内部 pixmap 缓存失效）。

    Qt 的 QPixmap(path) 自带按 (文件名, mtime) 记忆的内部缓存：同一个文件第二次解码实测
    只要 0.2ms，只有"没解过的新文件 / mtime 变过"才会真的重解（512px 实测 ~6ms/帧）。
    所以"冷解码"用例必须重写 + 推 mtime，否则首片永远不超预算、分片路径根本跑不到。
    （顺带覆盖 M2：同一路径换了素材，指纹里的 mtime 必须失配。）
    """
    import random
    import time
    from PySide6.QtGui import QColor, QImage

    rnd = random.Random(seed)
    for p in paths:
        img = QImage(size, size, QImage.Format.Format_ARGB32)
        img.fill(QColor(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)))
        if noise:
            for _k in range(3000):
                img.setPixelColor(rnd.randrange(size), rnd.randrange(size),
                                  QColor(rnd.randrange(256), rnd.randrange(256),
                                         rnd.randrange(256)))
        img.save(p)
    time.sleep(0.02)                      # 文件系统时间戳粒度兜底（避免"改了但签名没变"）
    for p in paths:
        st = os.stat(p)
        os.utime(p, ns=(st.st_atime_ns + bump_ns, st.st_mtime_ns + bump_ns))


def drain_anim_slices(win, limit=400):
    """把在途的分片解码跑完（**同步驱动**，不依赖事件循环时序）→ 返回每步阻塞毫秒数。

    v2.4.1（找茬 M4）：_anim_chunk_step 靠 QTimer(0) 接力，而 processEvents 一次可能排空
    多个 0-timer、也可能一个都不排，用例要确定地跑完就只能直接驱动。
    前提是真的分片了（win._anim_pending is not None）。
    """
    import time as _t
    from PySide6.QtWidgets import QApplication
    steps = []
    guard = 0
    while getattr(win, "_anim_pending", None) is not None and guard < limit:
        guard += 1
        t0 = _t.perf_counter()
        win._anim_chunk_step()
        steps.append((_t.perf_counter() - t0) * 1000.0)
    QApplication.processEvents()      # 让残留的 0-timer 也到点（此时应当什么都不做）
    return steps


def drain_startup_assets(win, limit_s=3.0):
    """把"首帧之后的接力装载"跑完（v2.4.2 启动耗时 P2）。

    v2.4.2 起，PetWindow() 构造期只同步解 idle 帧集 + 开场表情状态图；idle_full/eat/
    petpet 三组帧集与其余状态图由 QTimer(0) 接力装载（_startup_assets_step），
    每轮事件循环解一小片。生产路径里这发生在窗口出画面之后（用户无感），但**用例**
    若在构造后立刻断言这些素材，就必须先把接力装载驱动完——本函数就是那个驱动器
    （与 drain_anim_slices 同思路：同步驱动，不依赖事件循环时序）。

    返回是否真的跑完（False = 超时，调用方自行断言）。
    """
    import time as _t
    from PySide6.QtWidgets import QApplication
    t0 = _t.time()
    while not getattr(win, "_startup_assets_done", False) and _t.time() - t0 < limit_s:
        QApplication.processEvents()
        _t.sleep(0.002)
    QApplication.processEvents()
    return bool(getattr(win, "_startup_assets_done", False))


def quiet_pet_timers(win):
    """停掉会自行插进 _play_idle / 状态机的周期定时器（用例要确定性的起播计数）。"""
    for attr in ("_idle_check_timer", "mood_timer", "_mood_timer", "_alarm_timer",
                 "_state_timer", "_flight_timer", "_digest_timer", "_nap_zzz_timer"):
        t = getattr(win, attr, None)
        stop = getattr(t, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception:
                pass  # 有意忽略：测试辅助，停不掉不影响断言


def shutdown_pet(win):
    """测试收尾：**先停掉全部 QTimer**，再 hide/close/deleteLater（可重复调用、对普通控件安全）。

    v2.4.1（质量审查 L4）：真窗口 fixture 收尾只 hide() 时，实测拆完仍有 6 个 QTimer 活跃
    （3.2s/1s/15s/15s/1s/6s）——deleteLater 要等事件循环处理 DeferredDelete 才销毁对象，
    在那之前窗口是"活的"：后续用例只要 pump 一次事件循环，这些定时器就会回调产品代码。
    （与 test_dialogs_more_v24.py 里那份同思路；那个文件在别人手里，这里独立一份给其余模块用。）
    """
    from PySide6.QtCore import QTimer
    try:
        win._closing = True
    except Exception:
        pass  # 有意忽略：普通控件没有 _closing
    try:
        win.voice.stop()
    except Exception:
        pass  # 有意忽略：没有语音服务时跳过
    try:
        for _t in win.findChildren(QTimer):
            _t.stop()
    except Exception:
        pass  # 有意忽略：测试收尾尽力而为
    try:
        win.anim.stop()
    except Exception:
        pass  # 有意忽略：没有 anim 的普通控件
    try:
        win.hide()
        win.close()
        win.deleteLater()
    except Exception:
        pass  # 有意忽略：测试收尾尽力而为


def active_timer_count(win):
    """仍有活跃（isActive）子定时器的个数——fixture 收尾自检用（要求拆完为 0）。"""
    from PySide6.QtCore import QTimer
    try:
        return len([t for t in win.findChildren(QTimer) if t.isActive()])
    except Exception:
        return 0
