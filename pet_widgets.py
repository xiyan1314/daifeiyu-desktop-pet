# -*- coding: utf-8 -*-
"""
浮层挂件（气泡 / 余额挂件 / 食物托盘 / 飞行食物）+ 程序化表情绘制。

独立模块：不 import 桌宠.py。BUBBLE_STYLE 由桌宠.apply_bubble_style 就地 update，
Bubble.paintEvent 直接读本模块同名全局（同一 dict 对象）。
"""
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap, QPolygonF,
)
from PySide6.QtWidgets import QWidget

from pet_screen import screen_geometry_at
import pet_log

# 气泡样式（配置驱动；桌宠.apply_bubble_style 更新，Bubble.paintEvent 读取）
BUBBLE_STYLE = {"bg": "#ffffff", "fg": "#203170", "border": "#203170", "font_size": 10, "radius": 16}


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
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor("#203170"), 2))
        p.setBrush(QColor("#ffffff"))
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
            if (gp - self._press_pos).manhattanLength() > 6:
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
        fm = QFontMetrics(QFont("Microsoft YaHei", 9, QFont.Weight.Bold))
        w = max(100, max(fm.horizontalAdvance(line1), fm.horizontalAdvance(line2)) + 36)
        self.resize(w, 46)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor("#203170"), 2))
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(QRectF(1.5, 1.5, self.width() - 3, self.height() - 3), 10, 10)
        p.setPen(QColor("#203170"))
        p.setFont(QFont("Microsoft YaHei", 9, QFont.Weight.Bold))
        p.drawText(QRectF(6, 2, self.width() - 12, 22), Qt.AlignmentFlag.AlignCenter, self._line1)
        p.setPen(QColor("#5a6b8c"))
        p.setFont(QFont("Microsoft YaHei", 8))
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
        self._timer.timeout.connect(pet_log.guard_slot("bubble.hide", self.hide))

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
        fm = QFontMetrics(QFont("Microsoft YaHei", font_size, QFont.Weight.Bold))
        r = fm.boundingRect(0, 0, 190, 400, Qt.TextFlag.TextWordWrap, text)
        w = max(88, min(236, r.width() + 60))
        h = max(52, r.height() + 46)
        self.resize(w, h)
        x = anchor_global.x() - w // 2
        y = anchor_global.y() - h - 10
        if y < scr.top():
            y = anchor_global.y() + 10
        x = max(scr.left() + 4, min(x, scr.right() - w - 4))
        y = max(scr.top() + 4, min(y, scr.bottom() - h - 4))
        self.move(x, y)
        self.show()
        self.raise_()
        self.update()
        self._timer.start(5000)

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
        p.setFont(QFont("Microsoft YaHei", font_size, QFont.Weight.Bold))
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
        p.setFont(QFont("Microsoft YaHei", 40, QFont.Weight.Bold))
        p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "?")
    elif kind == "zzz":
        p.setPen(QColor("#9aa7b8"))
        p.setFont(QFont("Microsoft YaHei", 28, QFont.Weight.Bold))
        p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "z")
    elif kind == "note":
        p.setPen(QColor("#b58cff"))
        p.setFont(QFont("Microsoft YaHei", 36, QFont.Weight.Bold))
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
