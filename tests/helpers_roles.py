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