# -*- coding: utf-8 -*-
"""动效令牌表（v2.11.0 第 9 轮 · A1）——**全仓动效时长 / 缓动 / 幅度 / 阈值的单一来源**。

为什么要有这张表
----------------
动效参数此前散落在各处（头顶表情上浮写死 1500、无吃帧角色的咀嚼写死 900、
气泡自动隐藏写死 5000、拖拽判定散落 4 / 6 / 32 三个数…）。散落的后果不是"不好看"，
而是**同一个决定有多份实现**：改一处漏一处；更要紧的是"减少动效"这种横切开关
无处可挂——要么漏掉几条，要么每条都手写一遍 if。

HCI 依据（每个令牌按它属于哪一档给值；档位是通行口径，不是拍脑袋）
------------------------------------------------------------------
· **局部反馈**（悬停光晕、按下描边、点亮）：**≤100 ms**。反馈超过 100ms 就从"跟手"
  变成"迟钝"——用户会以为没点上而重复操作。
· **状态转换**（气泡淡入淡出、描边/光晕的出现与消失）：**150–250 ms**。短于此人眼
  读不出"变化"，长于此会挡在用户下一条操作前面（"它还在动"）。
· **大位移**（贴边滑动、涟漪扩散）：**≈300 ms**。位移越大可容忍的时长越长；
  300ms 是"看得见移动、但不觉得拖沓"的档位。
· **循环 / 持续动效**（呼吸、摇摆、帧动画）**不在这张表里**：它们的节奏由素材帧率
  决定（`IDLE_FRAME_MS` / `EAT_FRAME_MS` / 角色自带 `period_ms`），不是 HCI 档位。

「减少动效」开关（无障碍）
--------------------------
**不是"少一点"，是可预期地关掉**：`duration_ms()` 在开关打开时一律返回 **0**（瞬时），
`animation_enabled()` 为假，一次性的动效（涟漪 / 心形）**根本不产生**。
默认值不在这里定：见 `reduce_motion_enabled()`——读得到系统设置就跟随系统，
读不到就**不擅自替用户降级**（保持动效开启）。

本模块是**纯常量 + 纯函数**：不在模块层 import Qt（缓动以字符串名字给出，消费方自己
映射成 `QEasingCurve.Type`），不产生任何副作用；产品代码与测试同时导入它。
"""
import os

# ---------------- 时长（毫秒） ----------------
# 键名一律"用途/档位"，消费点用 pet_motion.duration_ms("<键>", reduce_motion)；
# 产品代码里**不许再出现这些毫秒字面量**（改一处漏一处的直接来源）。
DUR = {
    # —— 局部反馈档（≤100ms）——
    "FEEDBACK": 100,     # 悬停光晕淡入 / 按下描边的出现（跟手感的上限）
    # —— 状态转换档（150–250ms）——
    "TRANSITION": 200,   # 通用状态转换（备用档位；消费点用下面更具体的键）
    "BUBBLE_FADE": 180,  # 气泡淡入 / 淡出（B2）
    # —— 大位移档（≈300ms）——
    "LARGE": 300,        # 大位移通用档
    "EDGE": 300,         # A5 贴边滑动：目标位置计算不变，位移走这个时长
    "RIPPLE": 320,       # A4 点击涟漪：一次性扩散（比 300 略长是因为它还要"自己消失"）
    "HEART": 700,        # B4 摸头心形：一串上浮后自己消失
    "THINKING_PULSE": 900,  # B8 AI 在途指示的脉动周期（**信息不是装饰**：关掉动效只停脉动）
    # —— 既有常量显式搬家（原来写死在别处，原处只留指路注释）——
    "EMOTE_FLOAT": 1500,  # 原 桌宠.py _show_emote 的 anim.setDuration(1500)
    "EAT_SQUASH": 900,    # 原 桌宠.py _play_eat 无吃帧分支的 _run_anim(900, ...)
    "PET_HOLD": 1500,     # 原 桌宠.py mousePressEvent 的 _hold_timer.start(1500)
    "BUBBLE_HOLD": 5000,  # 原 pet_widgets.Bubble.show_text 的 self._timer.start(5000)
}

# ---------------- 缓动 ----------------
# 值是 QEasingCurve.Type 的成员名（字符串），由消费方映射——本模块因此不必 import Qt。
EASE = {
    "STANDARD": "OutCubic",   # 参数动效通用：快起慢收，观感最"轻"
    "IN_OUT": "InOutQuad",    # 往返类（贴边滑动、涟漪）：两端都慢，中间快
    "ENTER": "OutCubic",      # 出现（淡入 / 光晕亮起）
    "EXIT": "InCubic",        # 消失（淡出 / 涟漪扩散到淡出）
    "LINEAR": "Linear",       # 线性（只有确实需要匀速时用）
}

# ---------------- 幅度 ----------------
# A4 的硬口径：**悬停只做光晕、按下只补描边**，两者都不改角色几何。
# 因此这两个缩放因子必须恒为 1.0——用例逐个钉住，并逐项断言
# scale / squash / 窗口尺寸 / item 变换在悬停与按压期间一个都不变。
SCALE = {
    "HOVER": 1.0,   # 悬停**不缩放**（缩放会与角色自己的呼吸/摇摆相位打架 → 看着像抖动）
    "PRESS": 1.0,   # 按下**不缩放**（同上：按压缩放会叠加在呼吸相位上）
}
GLOW = {            # 悬停光晕（画在角色之下，几何无关）
    "RADIUS_PX": 18,    # 光晕比角色轮廓外扩多少
    "ALPHA": 96,        # 峰值不透明度（0–255）
    "COLOR": "#ffd65a",  # 暖黄：与默认角色的青蓝身体对比明显，但不刺眼
}
OUTLINE = {         # 按下描边（画在角色周围，几何无关）
    "WIDTH_PX": 3,
    "ALPHA": 210,
    "MARGIN_PX": 2,     # 描边离角色包围盒的间距
    "COLOR": "#203170",  # 与气泡边框/菜单同一支深蓝（本仓主题色）
}
RIPPLE = {          # 点击涟漪：从点击点扩散、不阻塞交互、自己消失
    "MIN_RADIUS_PX": 4,
    "MAX_RADIUS_PX": 120,
    "WIDTH_PX": 3,
    "ALPHA": 200,
    "COLOR": "#ffffff",
}
THINKING = {        # B8 AI 在途指示（'它在想'）：圆角气泡 + 三个点
    "SIZE_PX": 44,
    "MIN_OPACITY": 0.55,  # 脉动的最暗值（关掉动效时恒 1.0，静止可见）
    "GAP_PX": 4,
}
HEART = {           # B4 摸头心形：一次一串、会自己消失
    "COUNT": 3,          # 一串几颗
    "SPREAD_PX": 30,     # 同串之间的横向错开
    "RISE_PX": 44,       # 上浮距离
    "SIZE_PX": 22,
    "COLOR": "#ff4d6d",
}
# ---------------- 交互阈值（像素） ----------------
DRAG = {
    "THRESHOLD_PX": 8,     # B1：小于它**不进入拖拽态**（拖窗口/拖食物都要过这一关，防误触）
    "PET_CANCEL_PX": 32,   # 既有：明确拖动后取消"长按摸头"（与 _press_dist 判定同口径）
    "FOOD_THRESHOLD_PX": 6,  # 既有：食物托盘"点击投喂 vs 拖到嘴边"的分界
}

# ---------------- 高对比度（A3） ----------------
# 对比度按 WCAG 2.1 计算（contrast_ratio），两套调色板的每一对都由用例算出来钉住
# **≥ 4.5:1**（正文小字的 AA 门槛）——不靠眼看。
CONTRAST_MIN = 4.5
PALETTE_LIGHT = {"bg": "#ffffff", "fg": "#12233f", "border": "#12233f", "muted": "#3d4a63"}
PALETTE_DARK = {"bg": "#0f1420", "fg": "#f2f6ff", "border": "#f2f6ff", "muted": "#c3cdde"}


def duration_ms(name, reduce_motion=False):
    """令牌名 → 毫秒。reduce_motion=True → **0（瞬时）**，不是"短一点"。"""
    if reduce_motion:
        return 0
    try:
        return max(0, int(DUR.get(str(name), 0)))
    except TypeError:
        # v2.11.0 收尾（审计裁决 · 收紧）：str(name) 之后 ValueError 只可能来自
        # 「表里写了非数值」（例如 "1500ms"）——那是我们自己写错，不许静默回 0
        # （等于那条动效偷偷消失）。这里只挡 int() 对非数值类型的 TypeError；
        # 表值错误由 tests/test_motion_v2110.py 的「表值必须是数值」那条用例钉住。
        return 0


def effective_duration(ms, reduce_motion=False):
    """**数据驱动**的动效时长（角色自带的动作周期等）→ 关掉动效时归零（瞬时）。

    与 duration_ms 的分工：duration_ms 查令牌表（HCI 档位）；这个给"时长来自数据"的
    动效用（例如自定义角色的合成动作 period_ms）——它们**同样**必须能被开关关掉，
    但它们的基准值不该进令牌表（那是角色数据，不是 HCI 决策）。

    **已知边界（有意划定）**：素材帧序列（assets/idle_f* 的"呼吸帧"、petpet/money 特效帧）
    **不**随本开关停——那是角色的表现素材、不是代码驱动的动效，且没有"瞬时"语义
    （停掉等于把角色冻成一张图）。要覆盖它得先有产品决策。
    """
    if reduce_motion:
        return 0
    try:
        return max(0, int(ms))
    except (TypeError, ValueError):
        return 0


def animation_enabled(reduce_motion=False):
    """一次性的动效（涟漪 / 心形）此刻**该不该产生**。

    关掉动效时是"不产生"，不是"产生一个 0 毫秒的"——后者会留下一帧残影。
    """
    return not bool(reduce_motion)


def easing_name(name="STANDARD"):
    """缓动令牌名 → Qt `QEasingCurve.Type` 的成员名（本模块不 import Qt）。"""
    return str(EASE.get(str(name), EASE["STANDARD"]))


def visual_scale(name):
    """悬停 / 按下时**角色几何**的缩放因子——A4 定为恒 1.0（见 SCALE 的注释）。"""
    try:
        return float(SCALE.get(str(name), 1.0))
    except (TypeError, ValueError):
        return 1.0


def system_reduce_motion():
    """读系统"关闭动画 / 减少动效"设置：True / False，**读不到返回 None**。

    Windows：`SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION)`——用户在
    「辅助功能 → 视觉效果 → 动画效果」里关掉动画时为 True（= 应当减少动效）。
    其它平台或调用失败 → None：**不猜**，由调用方按"默认开启动效"处理。
    """
    if os.name != "nt":
        return None
    try:
        import ctypes
        import ctypes.wintypes  # noqa: F401  （裸 import ctypes 不绑定这个子模块）
        spi_getclientareaanimation = 0x1042
        enabled = ctypes.wintypes.BOOL()
        ok = ctypes.windll.user32.SystemParametersInfoW(
            spi_getclientareaanimation, 0, ctypes.byref(enabled), 0)
        if not ok:
            return None
        return not bool(enabled.value)
    except Exception:
        return None


def reduce_motion_enabled(cfg_value="auto", system_value=None):
    """「减少动效」的**生效值**。

    配置优先：on/true/1 → True；off/false/0 → False；auto（或不认识的值）→ 跟随系统。
    **系统读不到（None）→ False**（默认开启动效，不擅自替用户降级）。
    """
    v = str("auto" if cfg_value is None else cfg_value).strip().lower()
    if v in ("on", "true", "1", "yes", "always"):
        return True
    if v in ("off", "false", "0", "no", "never"):
        return False
    return bool(system_value)


def system_dark_theme():
    """读系统深色主题：True / False，读不到返回 None（Qt < 6.5、平台不支持、未起 app）。"""
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        scheme = QGuiApplication.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return True
        if scheme == Qt.ColorScheme.Light:
            return False
        return None  # Unknown：不猜
    except Exception:
        return None


def high_contrast_enabled(cfg_value="auto", system_dark=None):
    """高对比度的**生效值**：配置优先（on/off），auto → 跟随系统深色主题；读不到 → False。"""
    v = str("auto" if cfg_value is None else cfg_value).strip().lower()
    if v in ("on", "true", "1", "yes", "always"):
        return True
    if v in ("off", "false", "0", "no", "never"):
        return False
    return bool(system_dark)


def palette(dark=False):
    """高对比度调色板（深 / 浅两套，每套的对比度由用例逐对计算并钉 ≥ 4.5:1）。"""
    return dict(PALETTE_DARK if dark else PALETTE_LIGHT)


def parse_hex(color, default=(0, 0, 0)):
    """'#rgb' / '#rrggbb'（'#' 可省）→ (r, g, b)。坏值给 default，**不抛**。"""
    s = str(color if color is not None else "").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        return default
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return default


def to_hex(rgb):
    """(r, g, b) → '#rrggbb'（分量夹到 0–255）。"""
    return "#%02x%02x%02x" % (max(0, min(255, int(rgb[0]))),
                              max(0, min(255, int(rgb[1]))),
                              max(0, min(255, int(rgb[2]))))


def _linear(channel):
    """sRGB 分量（0–255）→ 线性光（WCAG 2.1 的传递函数）。"""
    v = max(0.0, min(1.0, channel / 255.0))
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def relative_luminance(color):
    """WCAG 2.1 相对亮度（0.0–1.0）。"""
    r, g, b = parse_hex(color)
    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def contrast_ratio(fg, bg):
    """WCAG 对比度（1.0–21.0）。A3 的"≥ 4.5:1"由这个函数算出来验，不靠眼看。"""
    a = relative_luminance(fg)
    b = relative_luminance(bg)
    hi, lo = (a, b) if a >= b else (b, a)
    return (hi + 0.05) / (lo + 0.05)


def ensure_min_contrast(fg, bg, minimum=CONTRAST_MIN):
    """把前景色调到与背景的对比度 ≥ minimum（只改明度，尽量不动色相）。

    先向黑靠（本仓"深字浅底"的常态），不够再向白靠；两者都试过仍不达标（背景本身是
    中灰）就返回过程中对比度最高的那个。**确定性**：同样输入永远同样输出。
    """
    fg_s, bg_s = str(fg), str(bg)
    if contrast_ratio(fg_s, bg_s) >= minimum:
        return fg_s
    rgb = parse_hex(fg_s)
    best_ratio, best_hex = contrast_ratio(fg_s, bg_s), fg_s
    for target in ((0, 0, 0), (255, 255, 255)):
        for i in range(1, 101):
            t = i / 100.0
            cand = to_hex(tuple(rgb[j] + (target[j] - rgb[j]) * t for j in range(3)))
            ratio = contrast_ratio(cand, bg_s)
            if ratio >= minimum:
                return cand
            if ratio > best_ratio:
                best_ratio, best_hex = ratio, cand
    return best_hex


def bubble_colors(style, high_contrast=False, dark=False):
    """气泡三色：高对比度**关闭时原样返回**（绝不悄悄改用户自定义样式）；
    打开时换成高对比度调色板（每对 ≥ 4.5:1）。font_size / radius 原样带过。"""
    out = dict(style or {})
    if not high_contrast:
        return out
    pal = palette(dark)
    out["bg"] = pal["bg"]
    out["fg"] = pal["fg"]
    out["border"] = pal["border"]
    return out


if __name__ == "__main__":
    # 独立自检（不进产品路径）：把表打出来，并对两套调色板各算一次对比度。
    for _k in sorted(DUR):
        print("DUR.%-12s %5d ms" % (_k, DUR[_k]))
    for _dark in (False, True):
        _pal = palette(_dark)
        print("palette dark=%-5s fg/bg=%.2f:1  border/bg=%.2f:1  muted/bg=%.2f:1"
              % (_dark, contrast_ratio(_pal["fg"], _pal["bg"]),
                 contrast_ratio(_pal["border"], _pal["bg"]),
                 contrast_ratio(_pal["muted"], _pal["bg"])))
    print("SCALE hover=%.3f press=%.3f  拖动阈值=%dpx"
          % (visual_scale("HOVER"), visual_scale("PRESS"), DRAG["THRESHOLD_PX"]))
