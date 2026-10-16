# -*- coding: utf-8 -*-
"""
浮层挂件（气泡 / 余额挂件 / 食物托盘 / 飞行食物）+ 程序化表情绘制。

独立模块：不 import 桌宠.py。BUBBLE_STYLE 由桌宠.apply_bubble_style 就地 update，
Bubble.paintEvent 直接读本模块同名全局（同一 dict 对象）。
"""
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
# v2.11.0 第 9 轮（B2）：气泡淡入淡出用 QVariantAnimation 驱动窗口不透明度，
# 时长/缓动一律取自 pet_motion（令牌表，含 HCI 依据）。
from PySide6.QtCore import QEasingCurve, QVariantAnimation
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap, QPolygonF,
)
from PySide6.QtWidgets import QWidget

from pet_screen import screen_geometry_at
import pet_log
import pet_motion  # v2.11.0 第 9 轮（A1）：动效令牌表（纯常量 + 纯函数）

# 气泡样式（配置驱动；桌宠.apply_bubble_style 更新，Bubble.paintEvent 读取）
BUBBLE_STYLE = {"bg": "#ffffff", "fg": "#203170", "border": "#203170", "font_size": 10, "radius": 16}
# v2.11.0 收尾：BUBBLE_STYLE 是**就地 update 的模块全局**，所以它同时也是"被跨用例共享的
# 可变状态"——某个用例改完不还原，后面"回到用户那份样式"这类断言就会红，而单跑那条又是绿的。
# 这份 canon 是它的**独立副本**（不是别名：别名会跟着一起被改），给夹具一个稳定起点。
BUBBLE_STYLE_CANON = dict(BUBBLE_STYLE)

# ---------------- v2.11.0 第 9 轮（A3）：高对比度 ----------------
# **关闭时挂件/托盘保持原配色（一个字节都不变）**；开启时走 pet_motion 的调色板——
# 每一对的对比度由 tests 用 pet_motion.contrast_ratio() 算出来钉住 ≥ 4.5:1，不靠眼看。
_HC = {"on": False, "dark": False}
_THINK_CACHE = {}


def set_high_contrast(on, dark=False):
    """高对比度开关（由 桌宠._apply_contrast 调用）。"""
    _HC["on"] = bool(on)
    _HC["dark"] = bool(dark)
    _THINK_CACHE.clear()  # 指示图配色跟着变：旧缓存作废


def _pal():
    """当前挂件配色：高对比度开启时用 pet_motion 的调色板，否则用本模块的历史配色。"""
    if _HC["on"]:
        return pet_motion.palette(_HC["dark"])
    return {"bg": "#ffffff", "fg": "#203170", "border": "#203170", "muted": "#5a6b8c"}


def thinking_pixmap(size=None):
    """B8：AI 在途指示（"它在想"）——小圆角气泡 + 三个点。

    **这是信息不是装饰**：关掉「减少动效」时它照常显示，只是不再脉动（脉动去掉、
    状态保留）。配色跟着高对比度走（同一份调色板）。
    """
    size = int(size or pet_motion.THINKING["SIZE_PX"])
    key = (size, _HC["on"], _HC["dark"])
    if key in _THINK_CACHE:
        return _THINK_CACHE[key]
    pal = _pal()
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 44.0
    p.setPen(QPen(QColor(pal["border"]), max(1.0, 2.0 * s)))
    p.setBrush(QColor(pal["bg"]))
    p.drawRoundedRect(QRectF(1.5 * s, 1.5 * s, size - 3 * s, size - 3 * s), 9 * s, 9 * s)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(pal["fg"]))
    r = max(1.4, 2.6 * s)
    for i in range(3):
        p.drawEllipse(QPointF((13.5 + i * 8.5) * s, size / 2.0), r, r)
    p.end()
    _THINK_CACHE[key] = pm
    return pm

# ---------------- 字体回退链 ----------------
# v2.4.3（第三轮找茬 P2-2）：此前本模块 8 处直接写死 QFont("Microsoft YaHei", …)，没有
# 候选族。现在统一走 ui_font()，族名按序排成一条链（QFont 的**列表重载**，Qt6 起支持；
# 列表原样保存在 QFont.families() 里，渲染时由 Qt 逐族回退）。
#
# 机理口径（审查实测，别读成"修掉了一个必现缺陷"）：Qt 的 Windows 字体引擎自己会做
# **字体链接**——候选族一个都不可用时 QFont 退到默认无衬线族（实测 Tahoma，exactMatch()
# 为 False），但只要机器上还有**任意一份** CJK 字体，inFontUcs4(0x4E2D) 仍为 True、
# advance("中") 仍算得出正常宽度，中文**可能**照常显示而不是豆腐块。所以这条链是
# "多一层候选 + 显式兜底"（链上成员都是带 CJK 的族，含 Windows 可选组件里的
# Arial Unicode MS），**不是**已证实的缺陷修复：真正一个 CJK 字体都没有的机器，
# 新旧写法同样没救。
UI_FONT_FAMILIES = ("Microsoft YaHei", "微软雅黑", "SimSun", "Arial Unicode MS")


def ui_font(size, weight=None):
    """按回退链构造 UI 字体（气泡 / 徽章 / 表情标记共用；别再散落字面字体名）。

    参数语义与原来的 QFont("Microsoft YaHei", size, weight) 一致：
    size = 点大小（int），weight = QFont.Weight（None = 默认 Normal）。
    """
    font = QFont(list(UI_FONT_FAMILIES))
    font.setPointSize(int(size))
    if weight is not None:
        font.setWeight(weight)
    return font


# ---------------- 食物：图标 / 托盘 / 飞行 ----------------
_FOOD_PIX_CACHE = {}


def food_pixmap(kind, size=48):
    key = (kind, size)
    if key in _FOOD_PIX_CACHE:
        return _FOOD_PIX_CACHE[key]
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 48.0

    def P(x, y):
        return QPointF(x * s, y * s)

    p.setPen(Qt.PenStyle.NoPen)
    if kind == "小鱼干":
        p.setBrush(QColor("#ff8c42"))
        p.drawPolygon(QPolygonF([P(34, 24), P(46, 16), P(46, 32)]))
        p.setBrush(QColor("#ffb347"))
        p.drawEllipse(QRectF(P(8, 20), P(34, 38)))
        p.setBrush(QColor("#333333"))
        p.drawEllipse(QRectF(P(13, 26), P(18, 31)))
    elif kind == "蛋糕":
        p.setBrush(QColor("#ff9ecb"))
        p.drawRoundedRect(QRectF(P(8, 26), P(40, 40)), 3, 3)
        p.setBrush(QColor("#ffe6b3"))
        p.drawRoundedRect(QRectF(P(12, 14), P(36, 26)), 3, 3)
        p.setBrush(QColor("#ff4d4d"))
        p.drawEllipse(QRectF(P(20, 5), P(28, 13)))
    elif kind == "钻石":
        p.setBrush(QColor("#7fd8ff"))
        p.drawPolygon(QPolygonF([P(24, 4), P(40, 20), P(24, 44), P(8, 20)]))
        p.setBrush(QColor("#ffffff"))
        p.drawPolygon(QPolygonF([P(24, 4), P(32, 20), P(24, 44)]))
        p.setBrush(QColor("#3fb8f5"))
        p.drawPolygon(QPolygonF([P(24, 4), P(16, 20), P(24, 44)]))
    p.end()
    _FOOD_PIX_CACHE[key] = pm
    return pm


class FoodTray(QWidget):
    """食物托盘：小鱼干/蛋糕/钻石。点击投喂，按住可拖到角色嘴里。"""

    clicked_food = Signal(str)
    drag_started = Signal(str, QPoint)

    FOODS = ["小鱼干", "蛋糕", "钻石"]

    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setFixedSize(168, 62)
        self._hover = -1
        self._press_food = -1
        self._press_pos = None

    def _rects(self):
        return [QRectF(8 + i * 52, 8, 48, 48) for i in range(3)]

    def _hit(self, pos):
        for i, r in enumerate(self._rects()):
            if r.contains(pos):
                return i
        return -1

    def paintEvent(self, event):
        pal = _pal()  # A3：高对比度开启时换调色板；关闭时与历史配色逐字节相同
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(pal["border"]), 2))
        p.setBrush(QColor(pal["bg"]))
        p.drawRoundedRect(QRectF(1.5, 1.5, self.width() - 3, self.height() - 3), 12, 12)
        for i, food in enumerate(self.FOODS):
            r = self._rects()[i]
            p.drawPixmap(int(r.x()), int(r.y()), food_pixmap(food))
            if self._hover == i:
                p.setPen(QPen(QColor("#ff9ecb"), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(r.adjusted(-2, -2, 2, 2), 8, 8)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press_food = self._hit(e.position())
            self._press_pos = e.globalPosition().toPoint() if self._press_food >= 0 else None

    def mouseMoveEvent(self, e):
        h = self._hit(e.position())
        if h != self._hover:
            self._hover = h
            self.update()  # 仅悬停项变化时重绘，避免 60Hz 空刷分层窗口
        # 拖拽判定必须校验左键仍按住：防止「按下游走出托盘、托盘外松手、
        # 再进托盘移动」触发幽灵拖拽（release 未落在本窗口时残留的按压状态）
        if (e.buttons() & Qt.MouseButton.LeftButton
                and self._press_food >= 0 and self._press_pos is not None):
            gp = e.globalPosition().toPoint()
            # B1 同一条阈值口径（令牌表单一来源）：小于阈值算"点击投喂"，不算拖到嘴边
            if (gp - self._press_pos).manhattanLength() > pet_motion.DRAG["FOOD_THRESHOLD_PX"]:
                food = self.FOODS[self._press_food]
                self._press_food = -1
                self._press_pos = None
                self.drag_started.emit(food, gp)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._press_food >= 0:
            self.clicked_food.emit(self.FOODS[self._press_food])
            self._press_food = -1
            self._press_pos = None

    def leaveEvent(self, e):
        self._hover = -1
        self._press_food = -1  # 清理按压残留，防重入时幽灵拖拽
        self._press_pos = None
        self.update()


class FoodFlyer(QWidget):
    """飞行中的食物（点击投喂/拖拽跟随）。"""

    dropped = Signal(QPoint)

    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._pm = None

    def set_food(self, kind):
        self._pm = food_pixmap(kind, 40)
        self.resize(40, 40)
        self.update()

    def paintEvent(self, event):
        if self._pm:
            p = QPainter(self)
            p.drawPixmap(0, 0, self._pm)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.dropped.emit(e.globalPosition().toPoint())


# ---------------- 气泡窗口 ----------------
class Badge(QWidget):
    """常驻余额挂件：余额 + 今日已用，数字滚动动画由 PetWindow 驱动。"""

    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._line1 = ""
        self._line2 = ""

    def set_info(self, line1, line2):
        self._line1 = line1
        self._line2 = line2
        fm = QFontMetrics(ui_font(9, QFont.Weight.Bold))
        w = max(100, max(fm.horizontalAdvance(line1), fm.horizontalAdvance(line2)) + 36)
        self.resize(w, 46)
        self.update()

    def paintEvent(self, event):
        pal = _pal()  # A3：高对比度开启时换调色板；关闭时与历史配色逐字节相同
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(pal["border"]), 2))
        p.setBrush(QColor(pal["bg"]))
        p.drawRoundedRect(QRectF(1.5, 1.5, self.width() - 3, self.height() - 3), 10, 10)
        p.setPen(QColor(pal["fg"]))
        p.setFont(ui_font(9, QFont.Weight.Bold))
        p.drawText(QRectF(6, 2, self.width() - 12, 22), Qt.AlignmentFlag.AlignCenter, self._line1)
        p.setPen(QColor(pal["muted"]))
        p.setFont(ui_font(8))
        p.drawText(QRectF(6, 24, self.width() - 12, 19), Qt.AlignmentFlag.AlignCenter, self._line2)


class Bubble(QWidget):
    """独立气泡窗口：椭圆气泡 + 尾巴 + 深蓝描边，置于角色上方、不遮挡角色。点击切换随机台词。"""

    clicked = Signal()

    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._text = ""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        # v2.11.0（B2）：到点改成**淡出**（关掉「减少动效」= 直接 hide）
        self._timer.timeout.connect(pet_log.guard_slot("bubble.hide", self._fade_out))
        # v2.11.0 第 9 轮（B2/B3）：淡入淡出 + 跟随
        self._fade_anim = None
        self._motion_reduced = False
        self._anchor = None   # 最近一次锚点（全局坐标）：跟随重定位用
        self._opacity = 1.0   # 淡入淡出的**平台无关读数**（见 _apply_opacity）

    def show_text(self, text, anchor_global):
        # P1-4：先定位屏（间隙取最近屏）；无屏直接放弃，不做半截状态变更
        scr = screen_geometry_at(anchor_global)[1]
        if scr is None:
            return
        self._text = text
        try:
            font_size = max(8, min(18, int(BUBBLE_STYLE.get("font_size", 10) or 10)))
        except Exception:
            font_size = 10
        fm = QFontMetrics(ui_font(font_size, QFont.Weight.Bold))
        r = fm.boundingRect(0, 0, 190, 400, Qt.TextFlag.TextWordWrap, text)
        w = max(88, min(236, r.width() + 60))
        h = max(52, r.height() + 46)
        self.resize(w, h)
        xy = self._anchor_xy(anchor_global, w, h)
        if xy is None:
            return
        self.move(xy[0], xy[1])
        self._anchor = QPoint(anchor_global)
        # ⚠ 必须在 show() **之前**取"是不是刚出现"：show() 之后 isVisible() 恒为真，
        # 那就等于"永远不淡入"（第一版真这么错过，被这条用例抓出来）。
        fresh = not self.isVisible()
        self.show()
        self.raise_()
        self.update()
        # B2：淡入（关掉「减少动效」→ 瞬时到位，连动画对象都不建）。
        # **只有"从看不见到看得见"才淡入**：气泡已经在显示时来了新文本（连点/连续回执），
        # 直接把新文本按满不透明度画出来——半透明的一两百毫秒里用户读不清字，
        # 那属于"用动效覆盖掉用户刚看的东西"（上一轮复盘过的那类坏改动）。
        if fresh and pet_motion.duration_ms("BUBBLE_FADE", self._motion_reduced) > 0:
            self._apply_opacity(0.0)
            self._fade_to(1.0)
        else:
            # 已经在显示（连点/连续回执的新文本）或关掉了动效 → **瞬时满不透明**：
            # 新文本绝不允许在半透明里停留（那两百毫秒用户读不清字）。
            self._fade_to(1.0, snap=True)
        # 展示时长令牌（原处硬编码 5000 已搬家：pet_motion.DUR["BUBBLE_HOLD"]）。
        # ⚠ 展示时长是"这条信息该看多久"，**不随「减少动效」归零**
        # （归零 = 气泡闪一下就没，等于没显示——那是对信息的破坏，不是降级）
        self._timer.start(pet_motion.duration_ms("BUBBLE_HOLD"))

    # ---- v2.11.0 第 9 轮（B2/B3）：定位、淡入淡出、跟随 ----
    def _anchor_xy(self, anchor_global, w, h):
        """锚点（全局）→ 窗口左上角。**show_text 与 follow_to 共用这一份**。

        两处各写一遍就会漂移成"跟随之后气泡跳一下"（B3 的验收就是"跟着走、不跳"）。
        所在屏读不到（无可用屏幕）→ None，调用方放弃（不做半截状态变更）。
        """
        scr = screen_geometry_at(anchor_global)[1]
        if scr is None:
            return None
        x = anchor_global.x() - w // 2
        y = anchor_global.y() - h - 10
        if y < scr.top():
            y = anchor_global.y() + 10
        x = max(scr.left() + 4, min(x, scr.right() - w - 4))
        y = max(scr.top() + 4, min(y, scr.bottom() - h - 4))
        return x, y

    def set_motion_reduced(self, reduced):
        """「减少动效」开关（A2）：关掉后淡入淡出**瞬时**（不建动画对象）。"""
        self._motion_reduced = bool(reduced)

    def _stop_fade(self):
        """停掉在途淡入淡出（幂等）。"""
        anim = self._fade_anim
        self._fade_anim = None
        if anim is None:
            return
        try:
            anim.stop()
            anim.deleteLater()
        except RuntimeError:
            pass  # 已被销毁：幂等

    def _apply_opacity(self, v):
        """淡入淡出的落地点：记状态 + 设窗口不透明度。

        **为什么要多存一个 _opacity**：offscreen 平台不支持窗口不透明度
        （实测打印 "This plugin does not support setting window opacity"），
        `windowOpacity()` 在测试里读不出变化——验收需要一条**平台无关**的读数，
        所以驱动值同时记进 _opacity（它与真正设进窗口的是同一个数）。
        """
        self._opacity = float(v)
        self.setWindowOpacity(self._opacity)

    def _fade_to(self, target, on_done=None, snap=False):
        """窗口不透明度淡到 target：时长/缓动走令牌表；关掉动效 → 瞬时设值。

        snap=True：**直接落到终态**（用于"新文本来了"——见 show_text 的那条注释）。
        """
        self._stop_fade()
        if snap or abs(float(self._opacity) - float(target)) < 1e-6:
            # 已经在终态（例如"淡出途中来了新文本"）：**直接落到终态，不产生空动画**。
            # 这一支就是 B2.3 要的结果——新文本必须立刻可读，不许从 0.5 再淡 180ms。
            self._apply_opacity(target)
            if on_done is not None:
                on_done()
            return
        ms = pet_motion.duration_ms("BUBBLE_FADE", self._motion_reduced)
        if ms <= 0:
            self._apply_opacity(target)
            if on_done is not None:
                on_done()
            return
        anim = QVariantAnimation(self)
        anim.setDuration(ms)
        anim.setStartValue(float(self._opacity))
        anim.setEndValue(float(target))
        anim.setEasingCurve(getattr(QEasingCurve.Type, pet_motion.easing_name("ENTER"),
                                    QEasingCurve.Type.Linear))
        anim.valueChanged.connect(self._apply_opacity)
        anim.finished.connect(lambda a=anim: self._retire_fade(a))
        self._fade_anim = anim
        anim.start()
        if on_done is not None:
            anim.finished.connect(lambda _a=None: on_done())

    def _retire_fade(self, anim):
        if self._fade_anim is anim:
            self._fade_anim = None
        try:
            anim.deleteLater()
        except RuntimeError:
            pass

    def _fade_out(self):
        """自动隐藏时间到：淡出后 hide（关掉「减少动效」→ 直接 hide）。"""
        def _done():
            self.hide()
            self._apply_opacity(1.0)  # 下次 show_text 从满不透明度起步（淡入会自己置 0）

        self._fade_to(0.0, on_done=_done)

    def follow_to(self, anchor_global):
        """B3：气泡跟随角色——按**同一份锚点算法**重定位，不重启自动隐藏计时。

        计时不重启是有意的：拖一下角色就把"这条气泡还能看多久"重置，等于用户
        永远读不完；跟随只该改位置。
        """
        if not self.isVisible():
            return
        xy = self._anchor_xy(anchor_global, self.width(), self.height())
        if xy is None:
            return
        self._anchor = QPoint(anchor_global)
        if (xy[0], xy[1]) != (self.x(), self.y()):
            self.move(xy[0], xy[1])

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        try:
            border = QColor(BUBBLE_STYLE.get("border", "#203170"))
            bg = QColor(BUBBLE_STYLE.get("bg", "#ffffff"))
            fg = QColor(BUBBLE_STYLE.get("fg", "#203170"))
            if not border.isValid():
                border = QColor("#203170")
            if not bg.isValid():
                bg = QColor("#ffffff")
            if not fg.isValid():
                fg = QColor("#203170")
            font_size = max(8, min(18, int(BUBBLE_STYLE.get("font_size", 10) or 10)))
            radius = max(0, min(30, int(BUBBLE_STYLE.get("radius", 16) or 16)))
        except Exception:
            border = QColor("#203170")
            bg = QColor("#ffffff")
            fg = QColor("#203170")
            font_size = 10
            radius = 16
        body = QRectF(4, 4, w - 8, h - 26)
        cx = w / 2
        tail = QPolygonF([QPointF(cx - 12, h - 28), QPointF(cx + 12, h - 28), QPointF(cx, h - 3)])
        path = QPainterPath()
        path.addRoundedRect(body, radius, radius)
        path.addPolygon(tail)
        p.setPen(QPen(border, 3))
        p.setBrush(bg)
        p.drawPath(path)
        p.setPen(QPen(border, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(body.right() - 30, h - 22, 14, 10))
        p.drawEllipse(QRectF(body.right() - 13, h - 13, 7, 5))
        p.setPen(fg)
        p.setFont(ui_font(font_size, QFont.Weight.Bold))
        p.drawText(body.adjusted(14, 8, -14, -8), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self._text)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


# ---------------- 程序化表情绘制（头顶 emote 与自定义角色状态图共用） ----------------
def _emote_mark(kind, size):
    """绘制表情符号：64px 画布绘制后缩放到 size。返回 QPixmap。"""
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if kind == "heart":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ff4d6d"))
        p.drawEllipse(16, 14, 16, 16)
        p.drawEllipse(32, 14, 16, 16)
        p.drawPolygon(QPolygonF([QPointF(16, 24), QPointF(48, 24), QPointF(32, 52)]))
    elif kind == "sparkle":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ffd23f"))
        p.drawPolygon(QPolygonF([
            QPointF(32, 4), QPointF(38, 26), QPointF(60, 32), QPointF(38, 38),
            QPointF(32, 60), QPointF(26, 38), QPointF(4, 32), QPointF(26, 26),
        ]))
    elif kind in ("sweat", "drool"):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#6ec6ff"))
        p.drawEllipse(18, 38, 28, 24)
        p.drawPolygon(QPolygonF([QPointF(18, 46), QPointF(46, 46), QPointF(32, 14)]))
    elif kind == "tear":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#6ec6ff"))
        p.drawEllipse(12, 38, 18, 20)
        p.drawEllipse(34, 38, 18, 20)
        p.drawPolygon(QPolygonF([QPointF(12, 44), QPointF(30, 44), QPointF(21, 18)]))
        p.drawPolygon(QPolygonF([QPointF(34, 44), QPointF(52, 44), QPointF(43, 18)]))
    elif kind == "anger":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ff4d4d"))
        p.drawRoundedRect(14, 28, 36, 10, 5, 5)
        p.drawRoundedRect(28, 14, 10, 36, 5, 5)
    elif kind == "exclaim":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ffd23f"))
        p.drawRoundedRect(26, 6, 14, 34, 7, 7)
        p.drawEllipse(24, 46, 16, 16)
    elif kind == "question":
        p.setPen(QColor("#7fb2ff"))
        p.setFont(ui_font(40, QFont.Weight.Bold))
        p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "?")
    elif kind == "zzz":
        p.setPen(QColor("#9aa7b8"))
        p.setFont(ui_font(28, QFont.Weight.Bold))
        p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "z")
    elif kind == "note":
        p.setPen(QColor("#b58cff"))
        p.setFont(ui_font(36, QFont.Weight.Bold))
        p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "♪")
    p.end()
    if size != 64:
        pm = pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return pm


# 自定义角色状态图：状态名 → 叠加的表情标记（blush 用双颊腮红）
_STATE_MARK_MAP = {
    "sleep": None, "puzzled": "question", "angry": "anger", "hiss": "anger",
    "cry": "tear", "laugh": "note", "smug": "sparkle",
    "surprised": "exclaim", "drool": "drool", "blush": "blush",
}


def _make_custom_state_pix(base, state):
    """在自定义角色底图上叠加程序化表情，生成状态图（无独立表情素材的替代）。

    blush 画粉色双颊；其余状态在顶部居中叠加对应表情标记。
    """
    if base is None or base.isNull():
        return QPixmap()  # 防御：调用链保证非空，此处仅兜底
    mark = _STATE_MARK_MAP.get(state)
    if mark is None:
        return QPixmap(base)  # 无标记状态（sleep）：直接复制底图，不做空绘
    pix = QPixmap(base)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    w, h = pix.width(), pix.height()
    s = max(w, h) / 256.0
    if mark == "blush":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 110, 140, 165))
        r = max(6, int(20 * s))
        p.drawEllipse(int(w * 0.26 - r), int(h * 0.50 - r), 2 * r, 2 * r)
        p.drawEllipse(int(w * 0.66 - r), int(h * 0.50 - r), 2 * r, 2 * r)
    else:
        size = min(max(24, int(46 * s)), max(16, int(w * 0.6)))  # 极小图防标记溢出
        m = _emote_mark(mark, size)
        p.drawPixmap((w - m.width()) // 2, 6, m)
    p.end()
    return pix
