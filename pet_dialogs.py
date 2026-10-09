# -*- coding: utf-8 -*-
"""
大肥鱼桌宠 —— 全部 Qt 对话框 / 面板（v1.3.0 新增）。

职责：参考 dsh-whale-widget 的「角色管理 / 音频片段管理 / 音效组 / 记账账本」
面板设计，提供资源管理、记账账本、气泡样式、台词设置四个交互界面。

对外接口（全部在主线程使用；构造签名 parent 为桌宠主窗口）：
- DIALOG_QSS（常量）：统一深色圆角主题（#1e2234 底 / #2e3560 控件底 /
  #e8ecff 文字 / #ffd65a 强调 / 圆角 8px），覆盖 QDialog/QPushButton/
  QListWidget/QTableWidget/QComboBox/QTabWidget/QLineEdit/QPlainTextEdit/
  QSpinBox/QDoubleSpinBox/QLabel/QRadioButton，以及弹窗类
  QMessageBox/QInputDialog/QFileDialog 与滚动条/表头等辅助控件。
- modal(dlg)：加 WindowStaysOnTopHint + show/raise_/activateWindow/setFocus
  后 exec（应对 Windows 前台锁，参考主程序 _set_api_key）。
- class RolePanel(QWidget)：角色列表 + 预览 + 导入 / 设为当前 / 删除 / 恢复默认。
- class RoleImportDialog(QDialog)：角色导入向导——1~8 个形态自由增删、
  每个形态独立命名选图；素材自动处理（去背景/裁剪/缩放）；
  支持多帧动画素材（多选图片 = 帧序列、视频/GIF 自动抽帧，统一画布处理）。
  P1-1 起：素材处理与视频/GIF 抽帧在 _ImportWorker 工作线程执行（可取消、
  进度信号回主线程），UI 不阻塞、无 QApplication.processEvents。
- class SoundPanel(QWidget)：音频片段列表（试听 / 导入 / 重命名 / 删除）+
  自定义音效组 5 行槽位（默认 / 静音 / 片段）。
- class ResourceManagerDialog(QDialog)：QTabWidget 三页签（角色 / 音效 / 声音素材），
  内嵌 RolePanel / SoundPanel / VoiceAssetPanel；initial_tab=0/1/2。
- class LedgerDialog(QDialog)：今日 / 近 7 天 / 全部 三个页签 + 实时搜索 +
  记一笔（AmountNoteDialog）+ 导出 CSV。
- class AmountNoteDialog(QDialog)：金额 QDoubleSpinBox(0.01~99999) + 备注输入。
- class BubbleStyleDialog(QDialog)：背景 / 文字 / 描边三色 + 字号 8~18 +
  圆角 0~30 + 实时预览，保存回调 pet.apply_bubble_style。
- class LinesDialog(QDialog)：v2.1 台词自定义——「台词库 / 对白编排 / 失效引用」三页签，
  直接读写 pet_lines.LineService（lines.json 是唯一来源；内置台词也可删、可撤销）。
- class VoiceDialog(QDialog)：v2.1 AI 配音——「配音 / 角色绑定 / 朗读台词 / 事件音效」四页签；
  后端参数与密钥**按后端隔离**，保存时整体深合并（不会清掉其它后端的 Key）。
- class VoiceAssetPanel(QWidget)：声音素材（参考音）管理，嵌在资源管理第三页签。
- class IdleDialog(QDialog)：待机设置（两触发 / 待机形态 / 待机动作列表 / 播放模式）。
- class _VoicePickDialog(QDialog) + pick_voice_assets(pet)：导出时勾选要随包带的参考音。
- 入口函数：open_voice / open_lines / open_resource_manager / open_idle / open_physics
  （open_lines 与 open_resource_manager 是 v2.1 补的历史缺陷：菜单一直在调用但从未定义）。

与主程序的耦合方式（全部防御性 getattr，缺省不崩）：
- pet.cfg（配置 dict）、pet.role_lib、pet.audio_lib、pet.book（可能 None）
- pet.apply_role(role_id)：立即切换角色（主线实现）
- pet.preview_audio(path|fid)：试听（主线实现：pet_audio.preview_file，
  wav 用 winsound；mp3 用 QMediaPlayer；失败弹提示）
- pet.apply_sound_group(group)：保存音效组后同步进 pet_audio（主线实现）
- pet.apply_bubble_style(style)：应用气泡样式（主线实现）
- pet.save_lines(pool, lines)：**兼容入口**（v2.0 语义：整体替换某类别文本；
  v2.1 起数据落在台词库 lines.json，对话框直接用 pet.lines_lib）
- pet.lines_lib / pet.voice / pet.voice_assets / pet.behaviors：v2.1 服务对象
- pet.apply_voice(data) / pet.apply_idle_settings(data)：v2.1 设置回调（均返回 True/False）
- pet.on_ledger_changed()：刷新挂件今日已用（主线实现）
- pet.show_bubble(text)

实现要点：
- 不 import 桌宠.py（避免循环依赖）；顶层 import PySide6 没问题。
- 所有对话框统一 DIALOG_QSS 深色主题；角色导入支持多形态（1~8 个，
  名字自定义），素材导入时自动处理（无透明通道自动去背景、裁剪透明边距、
  超大图等比缩小）。
- 金额统一 "%.2f" 显示，表格金额列右对齐。

Python 3.10+（项目运行环境 3.10.2）。

MIT License
Copyright (c) 大肥鱼桌宠项目
"""

import copy
import os
import shutil
import tempfile
import time

import pet_log

from PySide6.QtCore import QEventLoop, QTime, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QColor, QImage, QImageReader, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

import pet_audio
import pet_resources  # P3-5+：FRAME_MAX（帧上限用户可调）
import pet_behaviors  # v2.0.2：行为动作白名单/序列校验（BehaviorDialog 共用口径）
import pet_chat  # v2.0.4：服务商预设/错误归类/连通性测试（pet_chat 无 Qt 依赖，无环）
import pet_alarm  # v2.0.5：闹钟服务（AlarmDialog 共用时间校验/铃声导入口径）
import pet_lines  # v2.1：台词库（类别/标签单一来源；LinesDialog 直接用服务接口）
import pet_voice  # v2.1：可插拔配音后端清单（VoiceDialog 用）
from pet_widgets import BUBBLE_STYLE as _BUBBLE_STYLE  # v2.1.2：气泡默认样式单一来源
# （pet_widgets 只依赖 pet_screen + Qt，不反向依赖本模块，无循环）

# ---------------- 主题 ----------------
DIALOG_QSS = """
QDialog {
    background-color: #1e2234;
    color: #e8ecff;
    font-family: "Microsoft YaHei";
    font-size: 12px;
}
QWidget { color: #e8ecff; }
QLabel { color: #e8ecff; background: transparent; }
QPushButton {
    background-color: #2e3560;
    color: #e8ecff;
    border: 1px solid #3d477f;
    border-radius: 8px;
    padding: 5px 14px;
}
QPushButton:hover { background-color: #3d477f; }
QPushButton:pressed { background-color: #27304f; }
QPushButton:default {
    background-color: #ffd65a;
    color: #1e2234;
    border: 1px solid #ffd65a;
    font-weight: bold;
}
QPushButton:disabled { color: #6b7290; background-color: #262b40; border-color: #2e3560; }
QListWidget, QTableWidget, QComboBox, QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {
    background-color: #2e3560;
    color: #e8ecff;
    border: 1px solid #3d477f;
    border-radius: 8px;
    padding: 4px 6px;
}
QListWidget::item, QTableWidget::item { padding: 4px; }
QListWidget::item:selected, QTableWidget::item:selected { background-color: #4a5590; color: #ffffff; }
QListWidget::item:hover { background-color: #3a4375; }
QComboBox QAbstractItemView {
    background-color: #2e3560;
    color: #e8ecff;
    border: 1px solid #3d477f;
    selection-background-color: #4a5590;
    selection-color: #ffffff;
}
QTabWidget::pane { border: 1px solid #3d477f; border-radius: 8px; top: -1px; }
QTabBar::tab {
    background-color: #2e3560;
    color: #8f97c0;
    padding: 6px 16px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 2px;
}
QTabBar::tab:selected { background-color: #3d477f; color: #ffd65a; }
QTabBar::tab:hover:!selected { color: #e8ecff; }
QTableWidget { gridline-color: #3d477f; alternate-background-color: #232842; }
QHeaderView::section {
    background-color: #2e3560;
    color: #8f97c0;
    border: none;
    border-right: 1px solid #3d477f;
    border-bottom: 1px solid #3d477f;
    padding: 5px 8px;
}
QTableCornerButton::section { background-color: #2e3560; border: none; }
QScrollBar:vertical { background: #262b40; width: 10px; border-radius: 5px; }
QScrollBar::handle:vertical { background: #3d477f; border-radius: 5px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #262b40; height: 10px; border-radius: 5px; }
QScrollBar::handle:horizontal { background: #3d477f; border-radius: 5px; min-width: 24px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QMessageBox, QInputDialog, QFileDialog { background-color: #1e2234; color: #e8ecff; }
"""

# 音效组槽位：kind -> 面板行标签
_SLOT_LABELS = (("press", "戳一下"), ("release", "松开"), ("feed", "喂食"),
                ("reply", "AI 回复"), ("coin", "金币"))

# （v2.0 的 _LINE_POOLS 常量已删除：v2.1 起台词类别与标签统一由 pet_lines 提供，
#   避免"两处维护类别名"的漂移风险）

# 气泡默认样式：单一来源 pet_widgets.BUBBLE_STYLE（v2.1.2 质量审查 L2：此前是两份同值常量，
# 改真源不会跟着改）。这里保留别名只为可读性，值直接引用真源。
_DEFAULT_BUBBLE_STYLE = dict(_BUBBLE_STYLE)

# QMediaPlayer 保活引用（异步播放期间防 GC 回收，最多保留 4 个）
_MEDIA_KEEPALIVE = []


# ---------------- 通用助手 ----------------
def modal(dlg):
    """置顶 + 显式请求焦点后 exec（桌宠主窗口 WindowDoesNotAcceptFocus，
    子对话框不这么做会被 Windows 前台锁拦下）。返回 exec() 结果。"""
    dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    dlg.setFocus()
    return dlg.exec()


def _get(pet, name):
    """防御性取 pet 属性；任何异常返回 None。"""
    try:
        return getattr(pet, name, None)
    except Exception:
        return None  # 有意忽略：防御性取属性，异常按缺失处理（缺省不崩）


def _call(pet, name, *args):
    """防御性调用 pet 方法；缺失或抛异常返回 None。"""
    try:
        fn = getattr(pet, name, None)
        if callable(fn):
            return fn(*args)
    except Exception:
        pass  # 有意忽略：防御性调用，缺失/异常按失败处理（缺省不崩）
    return None


def _box(parent, icon, title, text):
    box = QMessageBox(parent)
    box.setIcon(icon)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStyleSheet(DIALOG_QSS)
    return box


def _warn(parent, title, text):
    modal(_box(parent, QMessageBox.Icon.Warning, title, text))


def _info(parent, title, text):
    modal(_box(parent, QMessageBox.Icon.Information, title, text))


def _confirm(parent, title, text):
    """确认框：确定 / 取消；返回是否确定。"""
    box = _box(parent, QMessageBox.Icon.Question, title, text)
    yes = box.addButton("确定", QMessageBox.ButtonRole.YesRole)
    box.addButton("取消", QMessageBox.ButtonRole.NoRole)
    modal(box)
    return box.clickedButton() is yes


def _preview_audio(pet, path):
    """试听：优先 pet.preview_audio；缺省时本地兜底
    （wav → pet_audio.preview_file；mp3 → QMediaPlayer）。返回是否已播出。"""
    if not path:
        return False
    if _call(pet, "preview_audio", path) is True:
        return True
    try:
        if pet_audio.preview_file(path):
            return True
    except Exception:
        pass  # 有意忽略：本地试听失败继续尝试 mp3 兜底
    if os.path.splitext(str(path))[1].lower() == ".mp3":
        try:
            from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
            player = QMediaPlayer()
            out = QAudioOutput()
            player.setAudioOutput(out)  # Qt 6.11 默认 audioOutput 为 None：不设会静音
            player.setSource(QUrl.fromLocalFile(str(path)))
            player.play()
            _MEDIA_KEEPALIVE.append((player, out))
            if len(_MEDIA_KEEPALIVE) > 4:
                old_p, _old_o = _MEDIA_KEEPALIVE.pop(0)
                try:
                    old_p.stop()  # 先停再释放，避免正在播放的兜底音被 GC 掐断
                except Exception:
                    pass  # 有意忽略：停旧播放器失败直接丢弃（尽力而为）
            return True
        except Exception as e:
            pet_log.log_error("pet_dialogs._preview_audio: mp3 兜底播放失败 %r" % (e,))
    return False


def _detail_table(headers):
    """构建统一风格的明细 QTableWidget。"""
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(list(headers))
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setAlternatingRowColors(True)
    t.setStyleSheet(DIALOG_QSS)
    hh = t.horizontalHeader()
    hh.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    hh.setStretchLastSection(True)
    return t


def _fill_detail(table, records):
    """明细表填充：日期/时间/类型(API消费/手动)/金额/备注；金额右对齐 %.2f。"""
    table.setRowCount(len(records))
    for i, r in enumerate(records):
        kind = "API消费" if r["kind"] == "api" else "手动"
        cells = (r["date"], r["time"], kind, "%.2f" % r["amount"], r["note"] or "")
        for j, text in enumerate(cells):
            item = QTableWidgetItem(str(text))
            if j == 3:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(i, j, item)


# ---------------- 角色素材自动处理（导入向导用） ----------------
_IMG_MAX_PROCESS_PX = 2048   # 去背景前的预缩放上限（限制泛洪耗时）
_IMG_TARGET_MAX_PX = 512     # 输出统一上限（角色太大/太小都不合适）
_IMG_BG_TOL = 40             # 去背景颜色容差（RGB 各通道最大差值）
_IMG_MIN_PX = 8


class ImportCancelled(Exception):
    """P1-1：用户取消导入/抽帧处理（工作线程内抛出，上层转为友好提示）。"""


def _remove_background(img, cancel=None):
    """无透明通道图自动去背景：从四边泛洪「与边界同色相连」的区域并置透明。

    返回处理后的 QImage；若剩余内容不足 1%（背景色与主体大面积同色相连）
    判定失败并返回 None（调用方保留原图并提示）。
    """
    from collections import deque
    w, h = img.width(), img.height()
    if w <= 0 or h <= 0:
        return None
    try:
        raw = bytearray(img.bits())
    except Exception:
        return None  # 有意忽略：像素读取失败按处理失败返回（调用方保留原图并提示）
    bpl = img.bytesPerLine()
    n = w * h
    visited = bytearray(n)
    dq = deque()
    for x in range(w):
        dq.append((x, 0))
        dq.append((x, h - 1))
    for y in range(1, h - 1):
        dq.append((0, y))
        dq.append((w - 1, y))
    processed = 0
    while dq:
        x, y = dq.popleft()
        i = y * w + x
        if visited[i]:
            continue
        visited[i] = 1
        processed += 1
        if processed % 8192 == 0:
            if cancel is not None and cancel():
                raise ImportCancelled()
        p = y * bpl + x * 4  # 行对齐：与 _content_bbox 的 y*bpl+x*4 一致
        r, g, b = raw[p], raw[p + 1], raw[p + 2]
        if x > 0 and not visited[i - 1]:
            q = p - 4
            if abs(raw[q] - r) <= _IMG_BG_TOL and abs(raw[q + 1] - g) <= _IMG_BG_TOL and abs(raw[q + 2] - b) <= _IMG_BG_TOL:
                dq.append((x - 1, y))
        if x < w - 1 and not visited[i + 1]:
            q = p + 4
            if abs(raw[q] - r) <= _IMG_BG_TOL and abs(raw[q + 1] - g) <= _IMG_BG_TOL and abs(raw[q + 2] - b) <= _IMG_BG_TOL:
                dq.append((x + 1, y))
        if y > 0 and not visited[i - w]:
            q = p - bpl
            if abs(raw[q] - r) <= _IMG_BG_TOL and abs(raw[q + 1] - g) <= _IMG_BG_TOL and abs(raw[q + 2] - b) <= _IMG_BG_TOL:
                dq.append((x, y - 1))
        if y < h - 1 and not visited[i + w]:
            q = p + bpl
            if abs(raw[q] - r) <= _IMG_BG_TOL and abs(raw[q + 1] - g) <= _IMG_BG_TOL and abs(raw[q + 2] - b) <= _IMG_BG_TOL:
                dq.append((x, y + 1))
    keep = 0
    for y in range(h):
        row = y * bpl
        for x in range(w):
            i = y * w + x
            if visited[i]:
                raw[row + x * 4 + 3] = 0
            elif raw[row + x * 4 + 3] > 0:
                keep += 1
    if keep < max(64, n // 100):
        return None  # 几乎全被吃：判定失败，保留原图
    out = QImage(raw, w, h, bpl, QImage.Format.Format_ARGB32)
    return out.copy()


def _content_bbox(img, cancel=None):
    """非透明像素包围盒 (x, y, w, h)；全透明返回 None。"""
    w, h = img.width(), img.height()
    try:
        raw = bytearray(img.bits())
    except Exception:
        return None  # 有意忽略：像素读取失败按包围盒计算失败返回（调用方保留原图）
    bpl = img.bytesPerLine()
    minx, miny, maxx, maxy = w, h, -1, -1
    for y in range(h):
        row = y * bpl
        if y % 256 == 0:
            if cancel is not None and cancel():
                raise ImportCancelled()
        for x in range(w):
            if raw[row + x * 4 + 3] > 8:
                if x < minx:
                    minx = x
                if x > maxx:
                    maxx = x
                if y < miny:
                    miny = y
                if y > maxy:
                    maxy = y
    if maxx < 0:
        return None
    return (minx, miny, maxx - minx + 1, maxy - miny + 1)


def _load_prepared(src, max_px=None, cancel=None, remove_bg=True):
    """加载素材并做通用预处理：预缩放 → 无透明通道自动去背景（P1-7 可关）。

    max_px=None 用全局 _IMG_MAX_PROCESS_PX（2048）；帧动画可传 1024 控制峰值。
    remove_bg=False 跳过自动去背景（P1-7 高级选项；默认 True = 现行为）。
    返回 (img, notes) 或 (None, None)。notes 为这一阶段的说明列表。
    cancel 为可调用的取消检测（工作线程内周期询问），取消时抛 ImportCancelled。
    """
    img = QImage(src)
    if img.isNull():
        return None, None
    # 必须先查原图的 alpha（convertToFormat 成 ARGB32 后 hasAlphaChannel 恒为 True）
    had_alpha = img.hasAlphaChannel()
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    notes = []
    cap = int(max_px) if max_px else _IMG_MAX_PROCESS_PX
    if max(img.width(), img.height()) > cap:
        img = img.scaled(cap, cap,
                         Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
        notes.append("超大图已预缩放")
    if not had_alpha:
        if remove_bg:
            removed = _remove_background(img, cancel=cancel)
            if removed is None:
                notes.append("背景与主体相连，保留原图")
            else:
                img = removed
                notes.append("已自动去背景")
        else:
            notes.append("未去背景（高级选项）")
    return img, notes


def _prepare_role_png(src, out_path, cancel=None, remove_bg=True, trim=True):
    """导入素材自动处理：无透明通道→去背景；裁剪透明边距；>512px 等比缩小。

    P1-7 高级选项：remove_bg=False 跳过去背景、trim=False 跳过透明边距裁剪
    （均默认 True = 现行为）。成功返回 (True, notes)；失败返回 (False, err)。
    notes 为中文说明列表。
    """
    img, notes = _load_prepared(src, cancel=cancel, remove_bg=remove_bg)
    if img is None:
        return False, "无法加载该图片"
    if trim:
        bbox = _content_bbox(img, cancel=cancel)
        if bbox is None:
            return False, "图片没有可见内容"
        x, y, w, h = bbox
        if (x, y, w, h) != (0, 0, img.width(), img.height()):
            img = img.copy(x, y, w, h)
            notes.append("已裁剪透明边距")
    else:
        notes.append("未裁剪透明边距（高级选项）")
    if max(img.width(), img.height()) > _IMG_TARGET_MAX_PX:
        img = img.scaled(_IMG_TARGET_MAX_PX, _IMG_TARGET_MAX_PX,
                         Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
        notes.append("已等比缩放（最长边 ≤%dpx）" % _IMG_TARGET_MAX_PX)
    if img.width() < _IMG_MIN_PX or img.height() < _IMG_MIN_PX:
        return False, "图片内容太小"
    if not img.save(out_path, "PNG"):
        return False, "保存处理结果失败"
    return True, notes


def _prepare_role_frames(srcs, out_dir, same_size=True, cancel=None, progress=None,
                          remove_bg=True):
    """批量处理帧素材到统一画布（帧动画导入用）。

    same_size=True（视频/GIF 抽帧，原始尺寸一致）：先算全部帧的内容**并集 bbox**，
    所有帧裁到同一矩形（保留主体平移的动画信息），再统一等比缩放（长边 ≤512）。
    same_size=False（多选图片，尺寸可能不一）：逐帧独立处理（去背景/裁剪/缩放），
    最后把每帧内容居中放进最大帧尺寸的透明画布（尺寸一致、防帧间跳动）。
    P1-7：remove_bg=False 跳过自动去背景（高级选项，默认 True = 现行为）；
    帧间对齐依赖统一画布，裁剪恒开（不做 trim 开关）。
    返回 (out_paths, notes) 或 (None, err)。
    cancel 为取消检测回调（工作线程内周期询问）；progress 为进度文本回调。
    """
    n = len(srcs)
    imgs = []
    for i, s in enumerate(srcs):
        if cancel is not None and cancel():
            raise ImportCancelled()
        if progress is not None:
            progress("处理帧 %d/%d…" % (i + 1, n))
        img, _load_notes = _load_prepared(s, max_px=1024, cancel=cancel,
                                          remove_bg=remove_bg)  # 帧序列峰值控制（输出 ≤512）
        if img is None:
            return None, "第 %d 帧无法加载" % (i + 1)
        imgs.append(img)
    if same_size:
        # 并集 bbox：所有帧裁到同一矩形，保留帧间平移
        union = None
        for img in imgs:
            b = _content_bbox(img, cancel=cancel)
            if b is None:
                return None, "存在空白帧"
            if union is None:
                union = (b[0], b[1], b[0] + b[2], b[1] + b[3])
            else:
                union = (min(union[0], b[0]), min(union[1], b[1]),
                         max(union[2], b[0] + b[2]), max(union[3], b[1] + b[3]))
        ux, uy, ux2, uy2 = union
        uw, uh = ux2 - ux, uy2 - uy
        scale = min(1.0, _IMG_TARGET_MAX_PX / float(max(uw, uh)))
        cw, ch = max(1, int(round(uw * scale))), max(1, int(round(uh * scale)))
        outs = []
        for i, img in enumerate(imgs):
            if cancel is not None and cancel():
                raise ImportCancelled()
            crop = img.copy(ux, uy, uw, uh)
            if scale < 1.0:
                crop = crop.scaled(cw, ch, Qt.AspectRatioMode.IgnoreAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            out = os.path.join(out_dir, "frame_f%02d.png" % i)
            if not crop.save(out, "PNG"):
                return None, "保存第 %d 帧失败" % (i + 1)
            outs.append(out)
        notes = ["统一画布 %dx%d（并集裁剪，保留平移）" % (cw, ch)]
        if scale < 1.0:
            notes.append("已等比缩放（最长边 ≤%dpx）" % _IMG_TARGET_MAX_PX)
        return outs, notes
    # 多选图片：逐帧独立处理 → 居中放进统一画布
    processed = []
    for i, img in enumerate(imgs):
        if cancel is not None and cancel():
            raise ImportCancelled()
        b = _content_bbox(img, cancel=cancel)
        if b is None:
            return None, "第 %d 帧没有可见内容" % (i + 1)
        x, y, w, h = b
        crop = img.copy(x, y, w, h)
        if max(w, h) > _IMG_TARGET_MAX_PX:
            crop = crop.scaled(_IMG_TARGET_MAX_PX, _IMG_TARGET_MAX_PX,
                               Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        processed.append(crop)
    max_w = max(p.width() for p in processed)
    max_h = max(p.height() for p in processed)
    outs = []
    for i, p in enumerate(processed):
        if cancel is not None and cancel():
            raise ImportCancelled()
        canvas = QImage(max_w, max_h, QImage.Format.Format_ARGB32)
        canvas.fill(0)
        painter = QPainter(canvas)
        painter.drawImage((max_w - p.width()) // 2, (max_h - p.height()) // 2, p)
        painter.end()
        out = os.path.join(out_dir, "frame_f%02d.png" % i)
        if not canvas.save(out, "PNG"):
            return None, "保存第 %d 帧失败" % (i + 1)
        outs.append(out)
    notes = ["统一画布 %dx%d（逐帧居中）" % (max_w, max_h)]
    return outs, notes


def _qt_parent(pet):
    """pet 必须是 Qt 窗口才能作父对象；否则用 None（缺省不崩）。"""
    return pet if isinstance(pet, QWidget) else None


# ---------------- 视频 / GIF 抽帧 ----------------


def _pump_events(ms=10):
    """局部事件循环泵：在当前线程内处理事件（工作线程泵 QtMultimedia 帧投递）。
    P1-1：替代 QApplication.processEvents。注意：若在主线程调用，效果等同
    QApplication.processEvents 的局部版（同样会分发 GUI 事件）——生产路径全在
    工作线程，主线程只可能出现在 v13/绿色版无头直测中。"""
    loop = QEventLoop()
    t0 = time.time()
    while time.time() - t0 < ms / 1000.0:
        loop.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
        time.sleep(0.002)


def _extract_video_frames(src, out_dir, cancel=None, progress=None):
    """从视频（mp4/webm/mov/avi 等）或 GIF 均匀抽帧（视频 3~20 帧、GIF 3~FRAME_MAX 帧；
    上限随用户配置 role_frame_max，抽帧时即按上限采样，不会白处理后再被导入拒绝）。

    视频走 QtMultimedia（QMediaPlayer + QVideoSink，绿色版自带 ffmpeg 后端），
    GIF 走 QImageReader（同步逐帧读，无事件循环依赖）。返回
    (原始帧 png 路径列表, err)；失败返回 (None, err)。
    捕获时即缩到 ≤1024（控制 4K 大视频的内存峰值），后续统一走
    _prepare_role_frames（并集画布 + 统一缩放，保留主体平移）。

    P1-1：全程可在工作线程调用（cancel/progress 可选回调）；视频路径的帧投递
    由本线程局部事件循环泵送，不阻塞 UI、不重入主事件循环。
    """
    ext = os.path.splitext(str(src))[1].lower()
    raws = []

    def _cap(img):
        if img is None or img.isNull():
            return
        if max(img.width(), img.height()) > 1024:
            img = img.scaled(1024, 1024, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        raws.append(img)

    try:
        if ext == ".gif":
            reader = QImageReader(src)
            n = reader.imageCount()
            if n < 0:
                return None, "无法读取 GIF 帧数（文件可能损坏？）"
            if n <= 1:
                return None, "GIF 只有 %d 帧，帧动画至少需要 2 帧" % n
            if n > 120:
                return None, "GIF 帧数太多（%d 帧），建议改用视频或减少帧数" % n
            take = min(int(pet_resources.FRAME_MAX or 24), n)  # P3-5+：上限用户可调
            idxs = [int(round(i * (n - 1) / float(take - 1))) for i in range(take)]
            need = set(idxs)
            # 顺序读帧并只保留采样点：部分 GIF 插件 jumpToImage 返回 False
            # 但 read() 仍按序推进——用顺序读最稳，且最多只驻留 take 帧的内存
            i = 0
            while i < n:
                if cancel is not None and cancel():
                    raise ImportCancelled()
                img = reader.read()
                if img is None or img.isNull():
                    break
                if i in need:
                    if progress is not None:
                        progress("读取 GIF 帧 %d/%d…" % (i + 1, n))
                    _cap(img.convertToFormat(QImage.Format.Format_ARGB32))
                i += 1
        else:
            from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
            player = QMediaPlayer()
            sink = QVideoSink()
            player.setVideoSink(sink)
            player.setSource(QUrl.fromLocalFile(os.path.abspath(src)))
            t0 = time.time()
            while player.duration() <= 0 and time.time() - t0 < 5:
                if cancel is not None and cancel():
                    player.stop()
                    raise ImportCancelled()
                _pump_events(20)
            dur = player.duration()
            if dur <= 0:
                player.stop()
                return None, "无法读取视频时长（格式不支持？可改用多选图片）"
            if not player.hasVideo():
                player.stop()
                return None, "该文件没有视频画面（纯音频？）"
            # 每约 0.4s 一帧；视频自身 ≤20 与用户配置上限取更小者（P3-5+）
            take = max(3, min(20, int(pet_resources.FRAME_MAX or 24), int(dur / 400)))
            got = []

            def _on_frame(frame):
                if frame.isValid() and not got:
                    got.append(frame.toImage())

            sink.videoFrameChanged.connect(_on_frame)
            if progress is not None:
                progress("读取首帧…")
            # S1：Qt6 ffmpeg 后端只在播放/暂停态向 sink 投帧——先 play() 拿首帧再 pause()
            # 大文件/高分辨率解码慢：首帧超时随文件大小放宽（无 GPU 软解 HEVC 场景）
            first_cap = 10 if os.path.getsize(src) > 50 * 1024 * 1024 else 5
            player.play()
            t0 = time.time()
            while not got and time.time() - t0 < first_cap:
                if cancel is not None and cancel():
                    player.stop()
                    raise ImportCancelled()
                _pump_events(10)
            player.pause()
            if not got:
                sink.videoFrameChanged.disconnect(_on_frame)
                player.stop()
                return None, "无法从视频读取画面"
            _cap(got[0])  # 首帧（t=0 位置）
            for i in range(1, take):
                if cancel is not None and cancel():
                    player.stop()
                    raise ImportCancelled()
                if progress is not None:
                    progress("抽视频帧 %d/%d…" % (i + 1, take))
                t = int(dur * i / float(take))
                del got[:]
                player.setPosition(t)  # 暂停态下 seek 仍会投递目标帧
                t1 = time.time()
                while not got and time.time() - t1 < 3:
                    if cancel is not None and cancel():
                        player.stop()
                        raise ImportCancelled()
                    _pump_events(10)
                if got:
                    _cap(got[0])
            sink.videoFrameChanged.disconnect(_on_frame)
            player.stop()
            # 注：worker 线程无事件循环，deleteLater 的 DeferredDelete 永不处理会泄漏 C++ 对象；
            # player/sink 均为局部变量，返回后由引用计数安全释放（sink 连接随析构断开）
    except ImportCancelled:
        raise
    except Exception as e:
        return None, "抽帧失败：%s" % e
    if len(raws) < 2:
        return None, "只抽到 %d 帧，帧动画至少需要 2 帧（可改用多选图片）" % len(raws)
    paths = []
    for i, img in enumerate(raws):
        p = os.path.join(out_dir, "raw_f%02d.png" % i)
        if not img.save(p, "PNG"):
            return None, "保存抽帧结果失败"
        paths.append(p)
    return paths, None


# ---------------- P1-1：导入工作线程 ----------------


def _run_import_pipeline(forms, frames_raw, frames_video, tmpdir, cancel=None, progress=None,
                         options=None):
    """角色导入的纯处理部分（无 UI），在工作线程内执行。

    options（P1-7 高级选项，全部可选，缺省 = 现行为）：
      {"remove_bg": bool, "trim": bool, "interval_ms": int|None,
       "render": dict|list, "keep_source": bool}
    返回 (result_dict, None) 或 (None, err)。result_dict 与旧 _do_import 一致，
    但不含 name（由主线程在完成时从控件实时读取，保持旧行为）；P1-7 起附加
    "options"（interval_ms/render/keep_source 回传落库用）与 "sources"
    （keep_source 时的原图路径列表）。
    """
    options = options or {}
    remove_bg = bool(options.get("remove_bg", True))
    trim = bool(options.get("trim", True))
    # P1-7：新选项仅在非默认时透传——保持旧调用签名完全兼容
    # （v13/绿色版用 stub 替换 _prepare_role_frames 时不接受新关键字参数）
    frame_kwargs = {}
    if not remove_bg:
        frame_kwargs["remove_bg"] = False
    png_kwargs = {}
    if not remove_bg:
        png_kwargs["remove_bg"] = False
    if not trim:
        png_kwargs["trim"] = False
    frames_out = []
    if frames_raw:
        if progress is not None:
            progress("帧动画统一画布处理…")
        frames_out, notesf = _prepare_role_frames(
            frames_raw, tmpdir, same_size=bool(frames_video), cancel=cancel,
            progress=progress, **frame_kwargs)
        if frames_out is None:
            return None, "帧处理失败：%s" % notesf
        base_out = frames_out[0]
        notes = ["帧动画 %d 帧：%s" % (len(frames_out), "、".join(notesf))]
        forms_out = [(forms[0][0], base_out)]
    else:
        base_out = os.path.join(tmpdir, "role_base.png")
        if progress is not None:
            progress("处理第 1 形态…")
        ok1, notes1 = _prepare_role_png(forms[0][1], base_out, cancel=cancel, **png_kwargs)
        if not ok1:
            return None, "第 1 形态处理失败：%s" % notes1
        notes = ["第 1 形态：%s" % ("、".join(notes1) if notes1 else "无需处理")]
        forms_out = [(forms[0][0], base_out)]
    for i, (nm, src) in enumerate(forms[1:], start=1):
        if cancel is not None and cancel():
            raise ImportCancelled()
        if progress is not None:
            progress("处理第 %d 形态（%s）…" % (i + 1, nm))
        fp = os.path.join(tmpdir, "form%d.png" % i)
        okf, notesf = _prepare_role_png(src, fp, cancel=cancel, **png_kwargs)
        if not okf:
            return None, "第 %d 形态处理失败：%s" % (i + 1, notesf)
        forms_out.append((nm, fp))
        notes.append("第 %d 形态（%s）：%s" % (i + 1, nm, "、".join(notesf) if notesf else "无需处理"))
    result = {"base": base_out, "frames": frames_out, "forms": forms_out, "notes": notes}
    # P1-7：高级选项回传（RolePanel 落库用；keep_source 时附带原图路径）
    result["options"] = {
        "interval_ms": options.get("interval_ms"),
        "render": options.get("render"),
        "keep_source": bool(options.get("keep_source")),
    }
    if options.get("keep_source"):
        sources = []
        for _nm, src in forms:
            if src and isinstance(src, str) and os.path.isfile(src):
                sources.append(src)
        sources.extend(frames_raw or [])
        result["sources"] = sources
    return result, None


class _ImportWorker(QThread):
    """P1-1：素材处理工作线程（图像管线 / 视频-GIF 抽帧）。

    任务 dict：{"kind": "extract", "src", "out_dir", "name_hint"} 或
    {"kind": "import", "forms", "frames_raw", "frames_video", "tmpdir"}。
    进度 progress(str)、结果 done_ok(object)、失败 failed(str) 经信号回主线程；
    cancel() 请求取消（管线周期检查，最终以 failed("已取消处理") 结束）。
    """
    progress = Signal(str)
    done_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, task, parent=None):
        super().__init__(parent)
        self._task = task
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _is_cancelled(self):
        return self._cancelled

    def run(self):
        task = self._task
        try:
            if task["kind"] == "extract":
                raws, err = _extract_video_frames(
                    task["src"], task["out_dir"],
                    cancel=self._is_cancelled, progress=self.progress.emit)
                if err:
                    self.failed.emit(err)
                else:
                    self.done_ok.emit({"raws": raws, "name_hint": task.get("name_hint", "")})
            else:
                res, err = _run_import_pipeline(
                    task["forms"], task.get("frames_raw") or [], task.get("frames_video", False),
                    task["tmpdir"], cancel=self._is_cancelled, progress=self.progress.emit,
                    options=task.get("options"))
                if err:
                    self.failed.emit(err)
                else:
                    self.done_ok.emit(res)
        except ImportCancelled:
            self.failed.emit("已取消处理")
        except Exception as e:
            self.failed.emit("处理失败：%s" % e)


# ---------------- 角色导入向导 ----------------
class RoleImportDialog(QDialog):
    """导入角色向导：1~8 个形态自由增删、每个形态独立命名选图（喂食循环切换）。

    素材支持静态图与多帧动画（多选图片 / 视频-GIF 抽帧）；
    点「导入」时自动处理（去背景/裁剪/缩放，静态走 _prepare_role_png、
    帧动画走 _prepare_role_frames 统一画布），结果经 result_data() 交
    RolePanel 落库；临时文件在 closeEvent 清理。
    """

    MAX_BYTES = 10 * 1024 * 1024

    def __init__(self, parent=None):
        super().__init__(_qt_parent(parent))
        self.setWindowTitle("导入角色")
        self.setStyleSheet(DIALOG_QSS)
        self.resize(600, 430)
        self._tmpdir = None
        self._result = None
        self._worker = None       # P1-1：在途工作线程（None=空闲）
        self._worker_kind = None  # P1-1：当前任务类型（extract/import）
        self._busy_state = False  # P1-1：处理中标志（形态行按钮随 busy 禁用）
        self._stopping = False    # P1-1：停止请求中（吞掉迟到进度，防覆盖「正在停止…」文案）
        # P1-1：应用退出前收敛在途工作线程（父窗口析构路径不经过 closeEvent，
        # 必须挂 aboutToQuit，否则 QThread: Destroyed while thread is still running）。
        # 注意：绑定方法会被应用单例强引用——closeEvent 真正关闭时必须 disconnect，
        # 否则每次打开向导泄漏一个隐藏对话框。
        try:
            QApplication.instance().aboutToQuit.connect(self._shutdown_worker)
        except Exception:
            pass  # instance() 为 None（无应用上下文）时静默跳过：此时也不存在退出流程

        root = QVBoxLayout(self)
        root.addWidget(QLabel("选好图片点「导入」即可：自动去背景、裁剪边距、统一大小。"))

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("角色名"))
        self._name_edit = QLineEdit()
        name_row.addWidget(self._name_edit, 1)
        root.addLayout(name_row)

        self._frames_raw = []   # 原始帧 png 路径（多选图片 / 视频抽帧）
        self._frames_video = False  # 帧是否来自同源视频/GIF（并集画布）
        self._name_hint = ""    # 素材源文件名（名字回退用，避免 raw_f00 当角色名）
        self._rawdir = None     # 抽帧临时目录
        # 形态列表（v1.4 多形态：1~8 个、名字自定义，喂食依次切换、12 秒后回第一形态）
        forms_head = QHBoxLayout()
        forms_head.addWidget(QLabel("形态（可改名；喂食依次切换，12 秒后回第一形态）"))
        self._add_form_btn = QPushButton("＋ 添加形态")
        self._add_form_btn.clicked.connect(self._add_form)
        forms_head.addStretch(1)
        forms_head.addWidget(self._add_form_btn)
        root.addLayout(forms_head)
        self._form_rows = []   # [{"name": str, "src": str}]，名字在导入时从控件读取
        self._forms_box = QVBoxLayout()
        root.addLayout(self._forms_box)
        self._add_form("常态")
        # 多帧素材（v1.3.2）：多选图片 = 帧序列；视频/GIF 自动抽帧
        fr_row = QHBoxLayout()
        fr_row.addWidget(QLabel("多帧动画"))
        m_btn = QPushButton("选多张图片…")
        m_btn.clicked.connect(self._pick_multi)
        v_btn = QPushButton("视频/GIF 抽帧…")
        v_btn.clicked.connect(self._pick_video)
        fr_row.addWidget(m_btn)
        fr_row.addWidget(v_btn)
        fr_row.addStretch(1)
        root.addLayout(fr_row)
        self._frames_status = QLabel("静态素材：也可选多张图片或视频/GIF 做帧动画")
        self._frames_status.setWordWrap(True)
        root.addWidget(self._frames_status)
        self._mat_btns = (m_btn, v_btn, self._add_form_btn)  # 素材选择按钮：处理期间统一禁用防重入

        # ---- P1-7 高级折叠区（全部可选，默认 = 现行为）----
        adv = QGroupBox("高级")
        adv.setCheckable(True)
        adv.setChecked(False)  # 默认折叠，不打扰常规导入
        adv_grid = QGridLayout(adv)
        self._adv_interval_chk = QCheckBox("自定义帧间隔")
        self._adv_interval = QSpinBox()
        self._adv_interval.setRange(10, 10000)
        self._adv_interval.setValue(140)
        self._adv_interval.setSuffix(" ms/帧")
        self._adv_interval.setEnabled(False)
        self._adv_interval_chk.toggled.connect(self._adv_interval.setEnabled)
        self._adv_rmbg = QCheckBox("自动去背景（无透明通道时）")
        self._adv_rmbg.setChecked(True)   # 默认开 = 现行为
        self._adv_trim = QCheckBox("裁剪透明边距")
        self._adv_trim.setChecked(True)   # 默认开 = 现行为
        self._adv_keep = QCheckBox("保留原图到角色目录 source/")
        self._adv_keep.setChecked(False)  # P2-6：默认关以减小体积
        self._adv_render_chk = QCheckBox("自定义渲染参数（锚点/缩放/偏移）")
        self._adv_anchor_x = QDoubleSpinBox()
        self._adv_anchor_x.setRange(0.0, 1.0)
        self._adv_anchor_x.setSingleStep(0.05)
        self._adv_anchor_x.setDecimals(2)
        self._adv_anchor_x.setValue(0.5)
        self._adv_anchor_y = QDoubleSpinBox()
        self._adv_anchor_y.setRange(0.0, 1.0)
        self._adv_anchor_y.setSingleStep(0.05)
        self._adv_anchor_y.setDecimals(2)
        self._adv_anchor_y.setValue(0.5)
        self._adv_scale = QDoubleSpinBox()
        self._adv_scale.setRange(0.1, 4.0)
        self._adv_scale.setSingleStep(0.05)
        self._adv_scale.setDecimals(2)
        self._adv_scale.setValue(1.0)
        self._adv_off_x = QSpinBox()
        self._adv_off_x.setRange(-300, 300)
        self._adv_off_y = QSpinBox()
        self._adv_off_y.setRange(-300, 300)
        self._adv_render_widgets = (
            self._adv_anchor_x, self._adv_anchor_y, self._adv_scale,
            self._adv_off_x, self._adv_off_y)
        for _w in self._adv_render_widgets:
            _w.setEnabled(False)
        self._adv_render_chk.toggled.connect(
            lambda on: [w.setEnabled(on) for w in self._adv_render_widgets])
        adv_grid.addWidget(self._adv_interval_chk, 0, 0)
        adv_grid.addWidget(self._adv_interval, 0, 1)
        adv_grid.addWidget(self._adv_rmbg, 1, 0)
        adv_grid.addWidget(self._adv_trim, 1, 1)
        adv_grid.addWidget(self._adv_keep, 2, 0, 1, 2)
        adv_grid.addWidget(self._adv_render_chk, 3, 0, 1, 2)
        adv_grid.addWidget(QLabel("锚点 X"), 4, 0)
        adv_grid.addWidget(self._adv_anchor_x, 4, 1)
        adv_grid.addWidget(QLabel("锚点 Y"), 5, 0)
        adv_grid.addWidget(self._adv_anchor_y, 5, 1)
        adv_grid.addWidget(QLabel("缩放倍率"), 6, 0)
        adv_grid.addWidget(self._adv_scale, 6, 1)
        adv_grid.addWidget(QLabel("偏移 X"), 7, 0)
        adv_grid.addWidget(self._adv_off_x, 7, 1)
        adv_grid.addWidget(QLabel("偏移 Y"), 8, 0)
        adv_grid.addWidget(self._adv_off_y, 8, 1)
        root.addWidget(adv)

        prev_row = QHBoxLayout()
        base_lay, self._prev_base = self._make_preview("形态 1（待机/动画）")
        full_lay, self._prev_full = self._make_preview("形态 2（若有）")
        prev_row.addLayout(base_lay)
        prev_row.addLayout(full_lay)
        root.addLayout(prev_row)

        self._notes = QLabel("")
        self._notes.setWordWrap(True)
        root.addWidget(self._notes)

        btns = QHBoxLayout()
        self._ok = QPushButton("导入")
        self._cancel = QPushButton("取消")
        self._stop_btn = QPushButton("停止处理")  # P1-1：处理中可见，可取消工作线程
        self._stop_btn.clicked.connect(self._stop_worker)
        self._stop_btn.setVisible(False)
        self._ok.setDefault(True)
        self._ok.clicked.connect(self._do_import)
        self._cancel.clicked.connect(self.reject)
        btns.addStretch(1)
        btns.addWidget(self._stop_btn)
        btns.addWidget(self._ok)
        btns.addWidget(self._cancel)
        root.addLayout(btns)

    @staticmethod
    def _make_preview(title):
        """构建「标题 + 预览框」子布局；返回 (QLayout, QLabel)。

        注意：不能用局部包装 QWidget 挂预览框——局部变量被 GC 会连带销毁
        子控件的 C++ 对象（libshiboken 已删除错误），必须返回布局交给调用方挂载。
        """
        lay = QVBoxLayout()
        cap = QLabel(title)
        cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prev = QLabel("未选择")
        prev.setFixedSize(240, 170)
        prev.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prev.setStyleSheet(
            "background-color:#2e3560;border:1px solid #3d477f;"
            "border-radius:8px;color:#8f97c0;")
        lay.addWidget(cap)
        lay.addWidget(prev, 0, Qt.AlignmentFlag.AlignCenter)
        return lay, prev

    def _form_views(self):
        """按 _form_rows 重建形态行（≤8 行，重建成本可忽略）。"""
        for i in reversed(range(self._forms_box.count())):
            w = self._forms_box.itemAt(i).widget()
            if w is not None:
                w.deleteLater()
        for i, fr in enumerate(self._form_rows):
            row_w = QWidget()
            lay = QHBoxLayout(row_w)
            lay.setContentsMargins(0, 0, 0, 0)
            name_edit = QLineEdit(fr["name"])
            name_edit.setFixedWidth(90)
            name_edit.setMaxLength(12)  # 与库侧截断一致，超长不再静默丢失
            name_edit.setPlaceholderText("形态%d" % (i + 1))
            file_edit = QLineEdit(fr.get("src", ""))
            file_edit.setReadOnly(True)
            file_edit.setPlaceholderText("第 %d 形态图（必选）" % (i + 1))
            pick = QPushButton("浏览…")
            pick.clicked.connect(lambda _c=False, fi=i: self._pick_form(fi))
            rem = QPushButton("✕")
            rem.setFixedWidth(28)
            rem.clicked.connect(lambda _c=False, fi=i: self._del_form(fi))
            lay.addWidget(name_edit)
            lay.addWidget(file_edit, 1)
            lay.addWidget(pick)
            lay.addWidget(rem)
            self._forms_box.addWidget(row_w)
            fr["name_edit"] = name_edit
            fr["file_edit"] = file_edit
            fr["pick"] = pick
            fr["rem"] = rem
            pick.setEnabled(not self._busy_state)  # P1-1：处理中禁改形态，防快照与界面不一致
            rem.setEnabled(not self._busy_state)

    def _add_form(self, name=""):
        if len(self._form_rows) >= 8:
            _warn(self, "形态", "最多 8 个形态")
            return
        self._form_rows.append({"name": name or "形态%d" % (len(self._form_rows) + 1), "src": ""})
        self._form_views()

    def _del_form(self, i):
        if len(self._form_rows) <= 1:
            _warn(self, "形态", "至少保留 1 个形态")
            return
        self._form_rows.pop(i)
        self._form_views()

    def _pick_form(self, i):
        src, _f = QFileDialog.getOpenFileName(
            self, "选择第 %d 形态图" % (i + 1), "", "图片 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not src:
            return
        if i == 0:
            self._apply_static_form(src)  # 形态 0 与静态图同源：清帧 + 命名回退
            return
        pix, err = self._validate_image(src, "形态图")
        if pix is None:
            _warn(self, "形态图", err)
            return
        self._form_rows[i]["src"] = src
        self._form_views()
        # 预览：形态 0 → 左框；形态 1 → 右框；其余不重复预览
        if i == 0:
            self._prev_base.setText("")
            self._prev_base.setPixmap(pix.scaled(240, 170, Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation))
        elif i == 1:
            self._prev_full.setText("")
            self._prev_full.setPixmap(pix.scaled(240, 170, Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation))
        if not self._name_edit.text().strip() and i == 0:
            self._name_edit.setText(os.path.splitext(os.path.basename(src))[0])

    def _set_busy(self, on, text="处理中…"):
        """处理期间统一禁/启用导入、取消与全部素材选择按钮（防重入嵌套抽帧）；
        P1-1：处理中显示「停止处理」按钮，窗口本身保持可拖动。"""
        self._busy_state = bool(on)
        self._ok.setEnabled(not on)
        self._cancel.setEnabled(not on)
        self._ok.setText(text if on else "导入")
        self._stop_btn.setVisible(on)
        self._stop_btn.setEnabled(on)
        for b in self._mat_btns:
            b.setEnabled(not on)
        for fr in self._form_rows:  # P1-1：形态行按钮同步禁用，防处理中改形态列表
            for k in ("pick", "rem"):
                btn = fr.get(k)
                if btn is not None:
                    btn.setEnabled(not on)

    def _start_worker(self, task):
        """启动工作线程并接线进度/结果/失败信号（P1-1）。"""
        w = _ImportWorker(task, self)
        w.progress.connect(self._on_worker_progress)
        w.done_ok.connect(self._on_worker_done)
        w.failed.connect(self._on_worker_failed)
        w.finished.connect(w.deleteLater)
        self._worker = w
        self._worker_kind = task["kind"]
        w.start()

    def _stop_worker(self):
        """请求取消在途处理：管线周期检查后以「已取消处理」结束。"""
        if self._worker is not None:
            self._worker.cancel()
            self._stopping = True  # 吞掉迟到进度，防覆盖「正在停止……」文案
            self._stop_btn.setEnabled(False)
            self._notes.setText("正在停止……")

    def _shutdown_worker(self):
        """取消并等待在途工作线程收敛（≤3s；超时 terminate 兜底）。

        供 closeEvent 与应用 aboutToQuit 共用：任何销毁路径都不让
        QThread 在运行中被析构（Qt fatal）。等待前断开信号，避免收敛期间
        排队中的 failed 在稍后主线程恢复事件循环时弹出多余提示。"""
        w = self._worker
        if w is None:
            return
        w.cancel()
        for sig in (w.done_ok, w.failed, w.progress):
            try:
                sig.disconnect()
            except (RuntimeError, TypeError):
                pass  # 有意忽略：信号未连接/已断开时 disconnect 抛错（幂等断开）
        if not w.wait(3000):
            try:
                w.terminate()  # 极端兜底：管线卡死时强杀，防退出卡住
                w.wait(1000)
                w.deleteLater()  # terminate 不发射 finished，手动释放防泄漏
            except Exception:
                pass  # 有意忽略：极端兜底强杀失败不阻塞退出（已尽力收敛线程）
        self._worker = None
        self._worker_kind = None

    def _on_worker_progress(self, text):
        if self._stopping:
            return  # 停止请求中：迟到进度不再覆盖「正在停止……」文案
        self._notes.setText(text)
        self._frames_status.setText(text)

    def _on_worker_done(self, res):
        self._worker = None
        self._worker_kind = None
        self._stopping = False
        if "raws" in res:
            # 抽帧完成
            self._set_busy(False)
            self._set_frames(res["raws"],
                             "已抽 %d 帧（视频/GIF 均匀采样，导入时统一自动处理）" % len(res["raws"]),
                             name_hint=res.get("name_hint") or "", video=True)
            return
        # 导入处理完成：补名字（完成时从控件实时读取，保持旧行为）
        res["name"] = self._name_edit.text().strip() or getattr(self, "_name_hint", "") or "未命名"
        self._set_busy(False)
        self._result = res
        self.accept()

    def _on_worker_failed(self, err):
        kind = self._worker_kind
        self._worker = None
        self._worker_kind = None
        self._stopping = False
        self._set_busy(False)
        if kind == "import":
            self._cleanup_tmp()  # 线程已结束，此时清理临时目录安全
        if err == "已取消处理":
            self._notes.setText("已停止处理")  # 主动停止不是错误：静默恢复 UI，不弹错误框
            return
        _warn(self, "抽帧" if kind == "extract" else "导入角色", err)

    def _validate_image(self, src, title):
        """素材校验：存在/大小/可加载。返回 (pix, err)。"""
        try:
            if os.path.getsize(src) > self.MAX_BYTES:
                return None, "文件超过 10MB，无法导入"
            pix = QPixmap(src)
            if pix.isNull():
                return None, "无法加载该图片"
        except Exception:
            return None, "读取图片失败"
        return pix, None

    def _apply_static_form(self, src):
        """校验并写入形态 0 + 预览 + 清帧选择（形态行选择与多选单文件共用）。"""
        pix, err = self._validate_image(src, "形态图")
        if pix is None:
            _warn(self, "形态图", err)
            return False
        if not self._form_rows:
            self._add_form("常态")
        self._form_rows[0]["src"] = src
        self._form_views()
        self._frames_raw = []  # 换单图必须清掉旧帧，否则导入仍走旧帧（M1）
        self._frames_video = False
        self._name_hint = os.path.splitext(os.path.basename(src))[0]
        self._frames_status.setText("静态素材：也可选多张图片或视频/GIF 做帧动画")
        self._prev_base.setText("")
        self._prev_base.setPixmap(pix.scaled(
            240, 170, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        if not self._name_edit.text().strip():
            self._name_edit.setText(os.path.splitext(os.path.basename(src))[0])
        return True

    def _set_frames(self, raws, note, name_hint=None, video=False):
        """设置帧序列：清空静态图，展示首帧预览与帧数状态。

        video=True 表示同源帧（视频/GIF 抽帧）→ 导入走并集画布保留平移。
        """
        self._frames_raw = list(raws)
        self._frames_video = bool(video)
        self._name_hint = name_hint or os.path.splitext(os.path.basename(raws[0]))[0]
        self._frames_status.setText(note)
        first = QPixmap(raws[0])
        self._prev_base.setText("")
        self._prev_base.setPixmap(first.scaled(
            240, 170, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        if not self._name_edit.text().strip():
            self._name_edit.setText(name_hint or os.path.splitext(os.path.basename(raws[0]))[0])

    def _pick_multi(self):
        files, _f = QFileDialog.getOpenFileNames(
            self, "选择多张图片（按文件名排序作为帧序）", "",
            "图片 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if len(files) <= 1:
            if files:
                self._apply_static_form(files[0])  # 单文件：同套校验（L9）
            return
        _max_frames = int(pet_resources.FRAME_MAX or 24)  # P3-5+：上限用户可调
        if len(files) > _max_frames:
            _warn(self, "多帧动画", "最多 %d 帧（可在设置里调整），当前选了 %d 张"
                  % (_max_frames, len(files)))
            return
        files = sorted(files)
        self._set_frames(files, "已选 %d 帧（多选图片，按文件名排序）" % len(files),
                         name_hint=os.path.splitext(os.path.basename(files[0]))[0])

    def _pick_video(self):
        src, _f = QFileDialog.getOpenFileName(
            self, "选择视频/GIF 抽帧", "",
            "视频 (*.mp4 *.webm *.mov *.avi *.mkv *.m4v *.wmv);;GIF (*.gif)")
        if not src:
            return
        try:
            if os.path.getsize(src) > 200 * 1024 * 1024:
                _warn(self, "抽帧", "文件超过 200MB，太大啦")
                return
        except Exception:
            pass  # 有意忽略：体积检查失败不拦抽帧（200MB 只是软上限）
        # P1-1：每次抽帧前重建临时目录——重试成功后旧 raw_fXX.png 不残留
        if self._rawdir:
            shutil.rmtree(self._rawdir, ignore_errors=True)
        self._rawdir = tempfile.mkdtemp(prefix="role_raw_")
        self._set_busy(True, text="抽帧中…")
        self._frames_status.setText("正在抽帧……")
        # P1-1：抽帧移入工作线程，UI 不再阻塞（窗口可拖动、可「停止处理」）
        self._start_worker({
            "kind": "extract",
            "src": src,
            "out_dir": self._rawdir,
            "name_hint": os.path.splitext(os.path.basename(src))[0],
        })

    def _do_import(self):
        # 收集形态（名字从控件实时读）
        forms = []
        for i, fr in enumerate(self._form_rows):
            nm = (fr.get("name_edit") and fr["name_edit"].text().strip()) or ("形态%d" % (i + 1))
            src = fr.get("src", "")
            if i == 0 and self._frames_raw:
                src = ""  # 帧动画角色：形态 0 用首帧，不要求选图
            elif not src or not os.path.isfile(src):
                _warn(self, "导入角色", "第 %d 形态还没选图" % (i + 1))
                return
            forms.append((nm, src))
        if not forms:
            _warn(self, "导入角色", "请先添加形态并选图")
            return
        # P1-7：高级折叠区选项收集（缺省 = 现行为）
        options = {
            "remove_bg": self._adv_rmbg.isChecked(),
            "trim": self._adv_trim.isChecked(),
            "keep_source": self._adv_keep.isChecked(),
        }
        if self._adv_interval_chk.isChecked():
            options["interval_ms"] = self._adv_interval.value()
        if self._adv_render_chk.isChecked():
            options["render"] = {
                "anchor": {"x": self._adv_anchor_x.value(), "y": self._adv_anchor_y.value()},
                "scale": self._adv_scale.value(),
                "offset": {"x": self._adv_off_x.value(), "y": self._adv_off_y.value()},
            }
        # P1-1：图像管线（去背景/裁剪/缩放，可能数秒）移入工作线程
        self._set_busy(True)
        self._notes.setText("正在自动处理素材（去背景 / 裁剪 / 缩放）……")
        self._tmpdir = tempfile.mkdtemp(prefix="role_prep_")
        self._start_worker({
            "kind": "import",
            "forms": forms,
            "frames_raw": list(self._frames_raw),
            "frames_video": bool(self._frames_video),
            "tmpdir": self._tmpdir,
            "options": options,
        })

    def _cleanup_tmp(self):
        """只清理本次导入的处理临时目录（保留原始抽帧供失败重试）。"""
        if self._tmpdir:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None

    def _cleanup(self):
        self._cleanup_tmp()
        if self._rawdir:
            shutil.rmtree(self._rawdir, ignore_errors=True)
            self._rawdir = None

    def closeEvent(self, event):
        if self._worker is not None:
            self._shutdown_worker()  # P1-1：关闭先收敛在途线程（防 QThread 运行中析构）
            self._set_busy(False)    # 取消处理即视为结束：允许本次关闭继续
        # P1-1：真正关闭时断开 aboutToQuit 连接——绑定方法被应用单例强引用，
        # 不断开会泄漏对话框（_tmpdir/_result 常驻、临时目录永不清理）
        try:
            QApplication.instance().aboutToQuit.disconnect(self._shutdown_worker)
        except Exception:
            pass  # 有意忽略：未连接/已断开时 disconnect 抛错（幂等断开）
        self._cleanup()
        super().closeEvent(event)

    def result_data(self):
        """accepted 后取处理结果：{"name","base","frames","forms","notes"} 或 None。

        P1-7 起 result 附加 "options"（interval_ms/render/keep_source）与
        "sources"（keep_source 时的原图路径）。
        """
        return self._result


class RoleEditDialog(QDialog):
    """P1-7 轻量角色编辑：改名 / 形态改名+调序 / 换图（重新处理，不换 id）/
    渲染参数（anchor/scale/offset）/ 帧间隔 / 正面图（front）/ 状态图（states）。

    确认时把新素材经管线处理后写入 roles/ 目录（新文件名），用
    RoleLibrary.update(rid, patch) 落盘索引；成功后清理不再被引用的旧文件。
    全部编辑只在当前库的该角色上进行，不新建 id。
    """

    def __init__(self, parent=None, lib=None, role_id=""):
        super().__init__(_qt_parent(parent))
        self._lib = lib
        self._role_id = str(role_id or "")
        self._role = (lib.get(self._role_id) if lib else None) or {}
        self._forms = copy.deepcopy(self._role.get("forms") or [])
        if not self._forms:
            self._forms = [{"name": "常态", "file": self._role.get("file", "")}]
        self._cur_idx = 0
        self._loading = False
        self._pending_images = {}    # form_idx -> src（换图，待重新处理）
        self._pending_front = {}     # form_idx -> src|None（None=清除）
        self._pending_states = {}    # (form_idx, state) -> src|None（None=删除）
        self._touched_name = set()
        self._touched_render = set()
        self._touched_interval = set()
        self._touched_flags = set()   # v2.0.2 断点#12：形态角色标记触碰集合
        self._staged = []            # 本次写入 roles/ 的新文件名（失败/取消时清理）
        self._tmpdir = None

        self.setWindowTitle("编辑角色「%s」" % self._role.get("name", ""))
        self.setStyleSheet(DIALOG_QSS)
        self.resize(600, 540)

        root = QVBoxLayout(self)
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("角色名"))
        self._name_edit = QLineEdit(self._role.get("name", ""))
        name_row.addWidget(self._name_edit, 1)
        root.addLayout(name_row)

        body = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("形态（选中后编辑；上移/下移调整喂食顺序）"))
        self._form_list = QListWidget()
        self._form_list.setMinimumWidth(190)
        self._form_list.currentRowChanged.connect(self._on_form_selected)
        left.addWidget(self._form_list, 1)
        reorder = QHBoxLayout()
        up_btn = QPushButton("上移")
        up_btn.clicked.connect(lambda: self._move_form(-1))
        down_btn = QPushButton("下移")
        down_btn.clicked.connect(lambda: self._move_form(1))
        reorder.addWidget(up_btn)
        reorder.addWidget(down_btn)
        reorder.addStretch(1)
        left.addLayout(reorder)
        body.addLayout(left)

        right = QVBoxLayout()
        self._preview = QLabel("预览")
        self._preview.setFixedSize(180, 130)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setStyleSheet(
            "background-color:#2e3560;border:1px solid #3d477f;"
            "border-radius:8px;color:#8f97c0;")
        right.addWidget(self._preview, 0, Qt.AlignmentFlag.AlignCenter)

        fn_row = QHBoxLayout()
        fn_row.addWidget(QLabel("形态名"))
        self._form_name = QLineEdit()
        self._form_name.setMaxLength(12)
        self._form_name.textChanged.connect(lambda _t: self._mark("name"))
        fn_row.addWidget(self._form_name, 1)
        right.addLayout(fn_row)

        img_row = QHBoxLayout()
        self._img_btn = QPushButton("换图（重新处理）…")
        self._img_btn.clicked.connect(self._pick_image)
        self._front_btn = QPushButton("设正面图…")
        self._front_btn.clicked.connect(self._pick_front)
        self._front_clear = QPushButton("清正面")
        self._front_clear.clicked.connect(self._clear_front)
        img_row.addWidget(self._img_btn)
        img_row.addWidget(self._front_btn)
        img_row.addWidget(self._front_clear)
        right.addLayout(img_row)
        self._img_status = QLabel("")
        self._img_status.setWordWrap(True)
        right.addWidget(self._img_status)

        render_box = QGroupBox("渲染参数（解决多形态切换跳变；默认 = 原行为）")
        rg = QGridLayout(render_box)
        self._anchor_x = QDoubleSpinBox()
        self._anchor_x.setRange(0.0, 1.0)
        self._anchor_x.setSingleStep(0.05)
        self._anchor_x.setDecimals(2)
        self._anchor_y = QDoubleSpinBox()
        self._anchor_y.setRange(0.0, 1.0)
        self._anchor_y.setSingleStep(0.05)
        self._anchor_y.setDecimals(2)
        self._scale = QDoubleSpinBox()
        self._scale.setRange(0.1, 4.0)
        self._scale.setSingleStep(0.05)
        self._scale.setDecimals(2)
        self._off_x = QSpinBox()
        self._off_x.setRange(-300, 300)
        self._off_y = QSpinBox()
        self._off_y.setRange(-300, 300)
        self._interval = QSpinBox()
        self._interval.setRange(0, 10000)
        self._interval.setSpecialValueText("默认")
        self._interval.setSuffix(" ms/帧")
        for _w in (self._anchor_x, self._anchor_y, self._scale,
                   self._off_x, self._off_y):
            _w.valueChanged.connect(lambda _v, _w=_w: self._mark("render"))
        self._interval.valueChanged.connect(lambda _v: self._mark("interval"))
        # v2.0.2 断点#12：形态角色标记（睡觉/变身/不参与喂食）
        self._ck_sleep_form = QCheckBox("睡觉形态")
        self._ck_transform_form = QCheckBox("变身形态")
        self._ck_no_feed = QCheckBox("不参与喂食")
        for _ck in (self._ck_sleep_form, self._ck_transform_form, self._ck_no_feed):
            _ck.toggled.connect(lambda _on: self._mark("flags"))
        rg.addWidget(QLabel("锚点 X"), 0, 0)
        rg.addWidget(self._anchor_x, 0, 1)
        rg.addWidget(QLabel("锚点 Y"), 1, 0)
        rg.addWidget(self._anchor_y, 1, 1)
        rg.addWidget(QLabel("缩放倍率"), 2, 0)
        rg.addWidget(self._scale, 2, 1)
        rg.addWidget(QLabel("偏移 X"), 3, 0)
        rg.addWidget(self._off_x, 3, 1)
        rg.addWidget(QLabel("偏移 Y"), 4, 0)
        rg.addWidget(self._off_y, 4, 1)
        rg.addWidget(QLabel("动画帧间隔"), 5, 0)
        rg.addWidget(self._interval, 5, 1)
        rg.addWidget(QLabel("角色标记"), 6, 0)
        _fl_row = QHBoxLayout()
        _fl_row.addWidget(self._ck_sleep_form)
        _fl_row.addWidget(self._ck_transform_form)
        _fl_row.addWidget(self._ck_no_feed)
        _fl_row.addStretch(1)
        rg.addLayout(_fl_row, 6, 1)
        right.addWidget(render_box)

        st_row = QHBoxLayout()
        st_row.addWidget(QLabel("状态图"))
        self._state_combo = QComboBox()
        self._state_combo.addItems(list(pet_resources.STATE_NAMES))
        st_pick = QPushButton("选图…")
        st_pick.clicked.connect(self._pick_state)
        st_clear = QPushButton("清除")
        st_clear.clicked.connect(self._clear_state)
        st_row.addWidget(self._state_combo, 1)
        st_row.addWidget(st_pick)
        st_row.addWidget(st_clear)
        right.addLayout(st_row)
        self._states_status = QLabel("")
        self._states_status.setWordWrap(True)
        right.addWidget(self._states_status)

        # v2.0.1：自定义动作（当前形态）：命名帧动作 + 程序化合成动作
        act_head = QHBoxLayout()
        act_head.addWidget(QLabel("自定义动作"))
        self._act_list = QListWidget()
        self._act_list.setMaximumHeight(80)
        act_head.addWidget(self._act_list, 1)
        act_btns = QVBoxLayout()
        b_add_f = QPushButton("＋帧动作…")
        b_add_f.clicked.connect(self._add_frame_action)
        b_add_p = QPushButton("＋合成…")
        b_add_p.clicked.connect(self._add_proc_action)
        b_del = QPushButton("删除")
        b_del.clicked.connect(self._del_action)
        act_btns.addWidget(b_add_f)
        act_btns.addWidget(b_add_p)
        act_btns.addWidget(b_del)
        act_head.addLayout(act_btns)
        right.addLayout(act_head)

        body.addLayout(right, 1)
        root.addLayout(body)

        btns = QHBoxLayout()
        self._ok = QPushButton("保存")
        self._cancel = QPushButton("取消")
        self._ok.setDefault(True)
        self._ok.clicked.connect(self._save)
        self._cancel.clicked.connect(self.reject)
        btns.addStretch(1)
        btns.addWidget(self._ok)
        btns.addWidget(self._cancel)
        root.addLayout(btns)

        self._refresh_form_list()

    # ---------- 表单同步 ----------
    def _mark(self, group):
        """用户改动标记：仅被触碰过的字段组写回索引（未触碰保持原结构）。"""
        if self._loading or self._cur_idx is None:
            return
        getattr(self, "_touched_%s" % group).add(self._cur_idx)

    def _sync_current(self):
        """把控件值写回 self._forms[self._cur_idx]（切换形态 / 保存前调用）。"""
        if self._cur_idx is None or self._loading:
            return
        fm = self._forms[self._cur_idx]
        fm["name"] = self._form_name.text().strip()[:12] or ("形态%d" % (self._cur_idx + 1))
        if self._cur_idx in self._touched_render:
            fm["anchor"] = {"x": round(self._anchor_x.value(), 2), "y": round(self._anchor_y.value(), 2)}
            fm["scale"] = round(self._scale.value(), 2)
            fm["offset"] = {"x": self._off_x.value(), "y": self._off_y.value()}
        if self._cur_idx in self._touched_interval:
            v = self._interval.value()
            if v > 0:
                fm["anim_interval_ms"] = v
            else:
                fm.pop("anim_interval_ms", None)
        # v2.0.2 断点#12：形态角色标记——勾选即 True，取消即删除键（缺省 False）
        if self._cur_idx in self._touched_flags:
            for _flag, _ck in (("sleep_form", self._ck_sleep_form),
                               ("transform_form", self._ck_transform_form),
                               ("no_feed", self._ck_no_feed)):
                if _ck.isChecked():
                    fm[_flag] = True
                else:
                    fm.pop(_flag, None)

    def _refresh_form_list(self):
        self._loading = True
        try:
            self._form_list.clear()
            for i, fm in enumerate(self._forms):
                self._form_list.addItem("%d. %s" % (i + 1, fm.get("name") or "形态%d" % (i + 1)))
            self._cur_idx = 0
            self._form_list.setCurrentRow(0)
            self._load_form(0)
        finally:
            self._loading = False

    def _on_form_selected(self, row):
        if self._loading:
            return
        self._sync_current()
        self._cur_idx = row if row is not None and 0 <= row < len(self._forms) else None
        if self._cur_idx is not None:
            self._load_form(self._cur_idx)

    def _load_form(self, idx):
        fm = self._forms[idx]
        self._loading = True
        try:
            self._form_name.setText(fm.get("name") or "")
            anchor = fm.get("anchor") or {"x": 0.5, "y": 0.5}
            self._anchor_x.setValue(float(anchor.get("x", 0.5)))
            self._anchor_y.setValue(float(anchor.get("y", 0.5)))
            self._scale.setValue(float(fm.get("scale") or 1.0))
            off = fm.get("offset") or {"x": 0, "y": 0}
            self._off_x.setValue(int(off.get("x", 0)))
            self._off_y.setValue(int(off.get("y", 0)))
            aiv = fm.get("anim_interval_ms")
            self._interval.setValue(int(aiv) if isinstance(aiv, (int, float)) and aiv > 0 else 0)
            # v2.0.2 断点#12：形态角色标记回填（_loading 期间 toggled 不触碰 _touched_flags）。
            # 用 _flag_true 与运行时同口径：直注数据带 "false"/"0" 字符串时不误勾
            self._ck_sleep_form.setChecked(pet_resources._flag_true(fm.get("sleep_form")))
            self._ck_transform_form.setChecked(pet_resources._flag_true(fm.get("transform_form")))
            self._ck_no_feed.setChecked(pet_resources._flag_true(fm.get("no_feed")))
        finally:
            self._loading = False
        self._update_statuses()
        self._refresh_act_list()  # v2.0.1：切形态刷新自定义动作列表

    def _update_statuses(self):
        idx = self._cur_idx
        if idx is None:
            return
        fm = self._forms[idx]
        pending_img = self._pending_images.get(idx)
        pending_front = self._pending_front.get(idx)
        lines = []
        if pending_img:
            lines.append("待处理换图：%s" % os.path.basename(pending_img))
        if pending_front is not None:
            lines.append("待处理正面图：%s" % (os.path.basename(pending_front) if pending_front else "清除"))
        elif fm.get("front"):
            lines.append("已有正面图")
        st_lines = []
        for st in pet_resources.STATE_NAMES:
            if (idx, st) in self._pending_states:
                st_lines.append("%s(待%s)" % (st, "处理" if self._pending_states[(idx, st)] else "清除"))
            elif (fm.get("states") or {}).get(st):
                st_lines.append(st)
        self._img_status.setText("；".join(lines) if lines else "未选择新素材")
        self._states_status.setText(("状态图：%s" % "、".join(st_lines)) if st_lines else "状态图：未配置（走程序化表情）")
        self._preview.setText("")
        p = self._lib.resolve(fm.get("file") or "") if self._lib else ""
        if p and os.path.isfile(p):
            pix = QPixmap(p)
            if not pix.isNull():
                self._preview.setPixmap(pix.scaled(
                    180, 130, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
                return
        self._preview.setText("无法预览")

    # ---------- 动作 ----------
    def _move_form(self, delta):
        idx = self._cur_idx
        if idx is None:
            return
        j = idx + delta
        if not (0 <= j < len(self._forms)):
            return
        self._sync_current()
        self._forms[idx], self._forms[j] = self._forms[j], self._forms[idx]
        # 待处理映射与触碰标记同步换序
        for table in (self._pending_images, self._pending_front):
            a, b = table.get(idx), table.get(j)
            table.pop(idx, None)
            table.pop(j, None)
            if b is not None:
                table[idx] = b
            if a is not None:
                table[j] = a
        new_states = {}
        for (fi, st), v in self._pending_states.items():
            fi2 = j if fi == idx else (idx if fi == j else fi)
            new_states[(fi2, st)] = v
        self._pending_states = new_states
        for touched in (self._touched_name, self._touched_render, self._touched_interval,
                         self._touched_flags):
            if idx in touched or j in touched:
                new_t = set()
                for fi in touched:
                    new_t.add(j if fi == idx else (idx if fi == j else fi))
                touched.clear()
                touched.update(new_t)
        # 重建列表期间屏蔽 currentRowChanged，避免把旧控件值写回已换序的形态
        self._loading = True
        try:
            self._form_list.clear()
            for i, fm in enumerate(self._forms):
                self._form_list.addItem("%d. %s" % (i + 1, fm.get("name") or "形态%d" % (i + 1)))
            self._cur_idx = j
            self._form_list.setCurrentRow(j)
        finally:
            self._loading = False
        self._load_form(j)

    def _pick_image(self):
        if self._cur_idx is None:
            return
        src, _f = QFileDialog.getOpenFileName(
            self, "选择新的形态图", "", "图片 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not src:
            return
        pix, err = self._validate_image(src)
        if pix is None:
            _warn(self, "换图", err)
            return
        self._pending_images[self._cur_idx] = src
        self._update_statuses()

    def _pick_front(self):
        if self._cur_idx is None:
            return
        src, _f = QFileDialog.getOpenFileName(
            self, "选择正面图（缺省与侧面同图）", "", "图片 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not src:
            return
        pix, err = self._validate_image(src)
        if pix is None:
            _warn(self, "正面图", err)
            return
        self._pending_front[self._cur_idx] = src
        self._update_statuses()

    def _clear_front(self):
        if self._cur_idx is None:
            return
        self._pending_front[self._cur_idx] = None
        self._update_statuses()

    def _pick_state(self):
        if self._cur_idx is None:
            return
        st = self._state_combo.currentText()
        src, _f = QFileDialog.getOpenFileName(
            self, "选择状态图「%s」（未配置走程序化表情）" % st, "", "图片 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not src:
            return
        pix, err = self._validate_image(src)
        if pix is None:
            _warn(self, "状态图", err)
            return
        self._pending_states[(self._cur_idx, st)] = src
        self._update_statuses()

    def _clear_state(self):
        if self._cur_idx is None:
            return
        st = self._state_combo.currentText()
        self._pending_states[(self._cur_idx, st)] = None
        self._update_statuses()

    def _validate_image(self, src):
        try:
            if os.path.getsize(src) > 10 * 1024 * 1024:
                return None, "文件超过 10MB，无法使用"
            pix = QPixmap(src)
            if pix.isNull():
                return None, "无法加载该图片"
        except Exception:
            return None, "读取图片失败"
        return pix, None

    def _process_pending(self):
        """把待处理的换图/正面图/状态图跑默认管线（去背景+裁剪），返回 (ok, err)。"""
        if not (self._pending_images or any(v for v in self._pending_front.values())
                or any(v for v in self._pending_states.values())):
            return True, ""
        self._tmpdir = tempfile.mkdtemp(prefix="role_edit_")
        self._process_list = []  # [(kind, idx|(idx,state), tmp_path)]
        try:
            n = 0
            for idx, src in self._pending_images.items():
                out = os.path.join(self._tmpdir, "img%d.png" % n)
                okp, notesp = _prepare_role_png(src, out)
                if not okp:
                    return False, "形态 %d 换图处理失败：%s" % (idx + 1, notesp)
                self._process_list.append(("image", idx, out))
                n += 1
            for idx, src in self._pending_front.items():
                if not src:
                    continue
                out = os.path.join(self._tmpdir, "img%d.png" % n)
                okp, notesp = _prepare_role_png(src, out)
                if not okp:
                    return False, "形态 %d 正面图处理失败：%s" % (idx + 1, notesp)
                self._process_list.append(("front", idx, out))
                n += 1
            for (idx, st), src in self._pending_states.items():
                if not src:
                    continue
                out = os.path.join(self._tmpdir, "img%d.png" % n)
                okp, notesp = _prepare_role_png(src, out)
                if not okp:
                    return False, "形态 %d 状态图「%s」处理失败：%s" % (idx + 1, st, notesp)
                self._process_list.append(("state", (idx, st), out))
                n += 1
            return True, ""
        except Exception as e:
            return False, "处理失败：%s" % e

    def _save(self):
        if self._lib is None:
            return
        self._sync_current()
        okp, errp = self._process_pending()
        if not okp:
            _warn(self, "编辑角色", errp)
            return
        name = self._name_edit.text().strip()
        if not name:
            _warn(self, "编辑角色", "角色名不能为空")
            return
        patch_forms = copy.deepcopy(self._forms)
        just_staged = []  # 本次保存尝试新暂存的文件（失败只回收这些，不动先前会话的暂存）
        # 处理结果写入 roles/ 目录（新文件名，不换 id）
        try:
            for kind, key, tmp_path in getattr(self, "_process_list", []):
                staged = self._lib.stage_file(tmp_path)
                if staged is None:
                    raise RuntimeError("写入角色目录失败")
                self._staged.append(staged)
                just_staged.append(staged)
                if kind == "image":
                    patch_forms[key]["file"] = staged
                elif kind == "front":
                    patch_forms[key]["front"] = staged
                else:
                    idx, st = key
                    patch_forms[idx].setdefault("states", {})[st] = staged
            for idx, src in self._pending_front.items():
                if src is None:
                    patch_forms[idx].pop("front", None)
            for (idx, st), src in self._pending_states.items():
                if src is None:
                    patch_forms[idx].setdefault("states", {}).pop(st, None)
        except Exception:
            for s in just_staged:
                p = self._lib.resolve(s)
                try:
                    if os.path.isfile(p):
                        os.remove(p)
                except Exception:
                    pass  # 有意忽略：本次写入残留清理尽力而为
                if s in self._staged:
                    self._staged.remove(s)
            _warn(self, "编辑角色", "素材写入失败")
            return
        # M1 修复：旧引用集合用库的 _role_paths 全量收集（含 animations 帧），
        # 避免换图后误删仍被 animations.idle 引用的首帧（帧动画静默丢失）
        old_refs = set(self._lib._role_paths(self._role))
        ok, err = self._lib.update(self._role_id, {"name": name, "forms": patch_forms})
        if not ok:
            for s in just_staged:
                p = self._lib.resolve(s)
                try:
                    if os.path.isfile(p):
                        os.remove(p)
                except Exception:
                    pass  # 有意忽略：本次写入残留清理尽力而为
                if s in self._staged:
                    self._staged.remove(s)
            _warn(self, "编辑角色", err or "保存失败")
            return
        # 成功：清理不再被引用的旧素材文件
        new_refs = set(self._lib._role_paths(self._lib.get(self._role_id)))
        for f in sorted(old_refs - new_refs):
            if f:
                p = self._lib.resolve(f)
                try:
                    if os.path.isfile(p):
                        os.remove(p)
                except Exception:
                    pass  # 有意忽略：旧文件清理尽力而为（索引已更新，残留仅占空间）
        # v2.0.1：本次暂存但最终未被引用的新文件（如刚添加又删除的动作帧）同样回收，
        # 否则 roles/ 目录会残留孤儿帧文件
        for fn in list(self._staged):
            p = self._lib.resolve(fn)
            if os.path.abspath(p) not in new_refs:
                try:
                    if os.path.isfile(p):
                        os.remove(p)
                except Exception:
                    pass  # 有意忽略：暂存文件清理尽力而为（不阻塞保存）
                self._staged.remove(fn)
        self.accept()

    def _cleanup_staged(self):
        """删除本次写入但未提交（或提交失败）的新文件。"""
        for fn in self._staged:
            p = self._lib.resolve(fn)
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except Exception:
                pass  # 有意忽略：孤儿文件清理尽力而为
        self._staged = []

    def _cleanup(self):
        if self._tmpdir:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None

    # ---------- v2.0.1：自定义动作（当前形态） ----------
    def _refresh_act_list(self):
        """列出当前形态的自定义动作（帧动作 + 程序化合成）。"""
        self._act_list.clear()
        if self._cur_idx is None or self._loading:
            return
        fm = self._forms[self._cur_idx]
        for act in (fm.get("animations") or {}):
            if act not in pet_resources.ANIM_ACTIONS:
                self._act_list.addItem("%s（帧）" % act)
        for name in sorted(fm.get("procs") or {}):
            self._act_list.addItem("%s（合成）" % name)

    def _add_frame_action(self):
        """多选图片 → 统一画布管线 → 立即入角色目录（staged，取消时回收）。"""
        files, _f = QFileDialog.getOpenFileNames(
            self, "选择动作帧图片（2 张起）", "", "图片 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if len(files) < 2:
            _warn(self, "帧动作", "帧动作至少 2 张图")
            return
        max_frames = int(pet_resources.FRAME_MAX)
        if len(files) > max_frames:
            _warn(self, "帧动作", "最多 %d 帧（可在设置里调整）" % max_frames)
            return
        name, ok = QInputDialog.getText(self, "帧动作", "动作名（英文字母开头，字母/数字/下划线 ≤24 字符）")
        name = (name or "").strip()
        if not ok or not name:
            return
        if not pet_resources.CUSTOM_ACTION_RE.match(name):
            _warn(self, "帧动作", "动作名不合法（英文字母开头，字母/数字/下划线）")
            return
        if name in pet_resources.ANIM_ACTIONS or name in pet_resources.ACTION_RESERVED:
            _warn(self, "帧动作", "动作名与内建动作/保留名重名（%s），换一个名字"
                  % "、".join(pet_resources.ANIM_ACTIONS + pet_resources.ACTION_RESERVED))
            return
        idx = self._cur_idx
        if idx is None or self._lib is None:
            return
        if name in (self._forms[idx].get("procs") or {}):
            _warn(self, "帧动作", "该形态已有同名合成动作，帧动作会被遮蔽，换一个名字")
            return
        tmpdir = tempfile.mkdtemp(prefix="role_act_")
        staged = []
        try:
            outs, notes = _prepare_role_frames(files, tmpdir, same_size=False)
            if outs is None:
                _warn(self, "帧动作", "处理失败：%s" % (notes,))
                return
            for o in outs:
                s = self._lib.stage_file(o)
                if s is None:
                    raise RuntimeError("写入角色目录失败")
                staged.append(s)
                self._staged.append(s)
            self._forms[idx].setdefault("animations", {})[name] = staged
            self._refresh_act_list()
        except Exception as e:
            # 只回收本次尝试暂存的文件——_cleanup_staged() 会连带删掉同会话先前
            # 已成功添加的动作帧，保存后动作静默变空
            for s in staged:
                p = self._lib.resolve(s)
                try:
                    if os.path.isfile(p):
                        os.remove(p)
                except Exception:
                    pass  # 有意忽略：本次导入残留清理尽力而为
                if s in self._staged:
                    self._staged.remove(s)
            _warn(self, "帧动作", "导入失败：%s" % e)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _add_proc_action(self):
        """添加程序化合成动作（呼吸/摇摆/点头，用角色自身贴图合成，无需素材）。"""
        dlg = QDialog(self)
        dlg.setWindowTitle("程序化合成动作")
        dlg.setStyleSheet(DIALOG_QSS)
        lay = QVBoxLayout(dlg)
        nm = QLineEdit()
        nm.setPlaceholderText("动作名（英文/数字/下划线）")
        lay.addWidget(nm)
        kind_box = QComboBox()
        kind_box.addItem("呼吸（整体轻微缩放）", "breathe")
        kind_box.addItem("摇摆（左右晃动）", "sway")
        kind_box.addItem("点头（上下位移）", "nod")
        lay.addWidget(kind_box)
        amp = QDoubleSpinBox()
        amp.setDecimals(3)
        lay.addWidget(amp)
        period = QSpinBox()
        period.setRange(200, 10000)
        lay.addWidget(period)

        def _apply_proc_defaults():
            # 幅度/周期默认与钳制范围随 kind 走单一来源（DEFAULT_PROC_PARAMS/PROC_AMP_BOUNDS）
            k = kind_box.currentData()
            lo, hi = pet_resources.PROC_AMP_BOUNDS.get(k, (0.001, 1.0))
            d = pet_resources.DEFAULT_PROC_PARAMS[k]
            amp.setRange(lo, hi)
            amp.setValue(float(d["amp"]))
            period.setValue(int(d["period_ms"]))
        kind_box.currentIndexChanged.connect(lambda _i: _apply_proc_defaults())
        _apply_proc_defaults()
        ok = QPushButton("添加")
        ok.clicked.connect(dlg.accept)
        lay.addWidget(ok)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name = nm.text().strip()
        if not pet_resources.CUSTOM_ACTION_RE.match(name):
            _warn(self, "合成动作", "动作名不合法（英文字母开头，字母/数字/下划线）")
            return
        if name in pet_resources.ANIM_ACTIONS or name in pet_resources.ACTION_RESERVED:
            _warn(self, "合成动作", "动作名与内建动作/保留名重名（%s），会无法从菜单播放，换一个名字"
                  % "、".join(pet_resources.ANIM_ACTIONS + pet_resources.ACTION_RESERVED))
            return
        if self._cur_idx is None or self._lib is None:
            return
        if name in (self._forms[self._cur_idx].get("animations") or {}):
            _warn(self, "合成动作", "该形态已有同名帧动作，合成动作会被遮蔽，换一个名字")
            return
        self._forms[self._cur_idx].setdefault("procs", {})[name] = {
            "kind": kind_box.currentData(), "amp": amp.value(), "period_ms": period.value()}
        self._refresh_act_list()

    def _del_action(self):
        """删除选中的自定义动作（按条目后缀只删对应类型：帧/合成同名互不影响）。"""
        item = self._act_list.currentItem()
        if item is None or self._cur_idx is None:
            return
        text = item.text()
        fm = self._forms[self._cur_idx]
        removed = False
        if text.endswith("（帧）"):
            fm.setdefault("animations", {}).pop(text[:-len("（帧）")], None)
            removed = True
        elif text.endswith("（合成）"):
            fm.setdefault("procs", {}).pop(text[:-len("（合成）")], None)
            removed = True
        if removed:
            self._refresh_act_list()

    def closeEvent(self, event):
        self._cleanup()
        if self.result() != QDialog.DialogCode.Accepted:
            self._cleanup_staged()  # v2.0.1：取消/关闭时回收未提交的新文件
        super().closeEvent(event)


# ---------------- v2.0.2：行为自定义 ----------------
class BehaviorDialog(QDialog):
    """行为自定义对话框：列表 + 新建/编辑/删除 + 步骤编辑 + 试播 + 导入/导出。

    待机行为 / 触发秒数 / 变身时长也在这里配置（写 pet.cfg 并 save_cfg 持久化）。
    """

    def __init__(self, pet, svc=None, save_cfg=None):
        super().__init__(pet)
        self.pet = pet
        self.svc = svc or getattr(pet, "behaviors", None)
        self._save_cfg = save_cfg or (lambda cfg: None)
        self._editing_id = None
        self.setWindowTitle("行为自定义")
        self.setStyleSheet(DIALOG_QSS)
        self.resize(640, 500)
        lay = QVBoxLayout(self)

        # ---- 待机行为设置（断点：待机行为红线） ----
        idle_row = QHBoxLayout()
        idle_row.addWidget(QLabel("待机行为"))
        self._idle_combo = QComboBox()
        self._idle_secs = QSpinBox()
        # 上界 = 入睡阈值：超过则待机行为永远不触发（界限单一来源 pet_behaviors）
        self._idle_secs.setRange(pet_behaviors.IDLE_SECS_MIN, pet_behaviors.IDLE_SECS_MAX)
        self._idle_secs.setSuffix(" 秒")
        idle_row.addWidget(self._idle_combo, 1)
        idle_row.addWidget(QLabel("空闲"))
        idle_row.addWidget(self._idle_secs)
        idle_row.addWidget(QLabel("触发；变身时长"))
        self._transform_secs = QSpinBox()
        self._transform_secs.setRange(pet_behaviors.TRANSFORM_SECS_MIN,
                                      pet_behaviors.TRANSFORM_SECS_MAX)
        self._transform_secs.setSuffix(" 秒")
        idle_row.addWidget(self._transform_secs)
        lay.addLayout(idle_row)
        self._idle_combo.currentIndexChanged.connect(self._on_idle_pick)
        self._idle_secs.valueChanged.connect(lambda _v: self._save_cfg_vals())
        self._transform_secs.valueChanged.connect(lambda _v: self._save_cfg_vals())

        # ---- 行为列表 ----
        lay.addWidget(QLabel("已有行为（双击试播）"))
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_sel)
        self._list.itemDoubleClicked.connect(lambda _i: self._test_play())
        lay.addWidget(self._list, 2)

        # ---- 名称与步骤编辑 ----
        nm_row = QHBoxLayout()
        nm_row.addWidget(QLabel("行为名"))
        self._name = QLineEdit()
        self._name.setPlaceholderText("英文字母开头，字母/数字/下划线")
        nm_row.addWidget(self._name, 1)
        lay.addLayout(nm_row)
        lay.addWidget(QLabel("动作序列（按顺序执行，wait 控制间隔）"))
        self._steps = QListWidget()
        lay.addWidget(self._steps, 3)
        add_row = QHBoxLayout()
        self._act_combo = QComboBox()
        for act in pet_behaviors.BEHAVIOR_ACTS:
            self._act_combo.addItem(self._act_label(act), act)
        self._param = QLineEdit()
        self._act_combo.currentIndexChanged.connect(
            lambda _i: self._param.setPlaceholderText(self._param_hint(self._act_combo.currentData())))
        self._param.setPlaceholderText(self._param_hint(self._act_combo.currentData()))
        b_add_step = QPushButton("添加步骤")
        b_add_step.clicked.connect(self._add_step)
        add_row.addWidget(self._act_combo)
        add_row.addWidget(self._param, 1)
        add_row.addWidget(b_add_step)
        lay.addLayout(add_row)
        del_row = QHBoxLayout()
        b_del_step = QPushButton("删除选中步骤")
        b_del_step.clicked.connect(lambda: self._steps.takeItem(self._steps.currentRow()))
        del_row.addWidget(b_del_step)
        del_row.addStretch(1)
        lay.addLayout(del_row)

        # ---- 按钮 ----
        btn_row = QHBoxLayout()
        for _label, _cb in (("新建", self._new), ("保存", self._save), ("删除", self._delete),
                            ("试播", self._test_play), ("导入…", self._import), ("导出…", self._export),
                            ("关闭", self.accept)):
            _b = QPushButton(_label)
            _b.clicked.connect(_cb)
            btn_row.addWidget(_b)
        lay.addLayout(btn_row)
        self._refresh()

    # ---------- 展示辅助 ----------
    @staticmethod
    def _act_label(act):
        return {"play_action": "动作", "say": "台词", "voice": "语音",
                "emote": "表情", "form": "切形态", "sleep": "入睡", "wait": "等待",
                "speak_line": "读台词", "speak_dialogue": "读整段对白"}.get(act, act)

    @staticmethod
    def _param_hint(act):
        return {"play_action": "动作名（帧动作/合成动作）", "say": "台词内容",
                "voice": "事件：reply/feed/poke/sleep/wake",
                "emote": "表情：note/sparkle/heart/zzz",
                "form": "形态键（f0/f1 等内部键，见角色形态列表）", "sleep": "无需参数（终止步）",
                "wait": "等待毫秒数（100~30000）",
                "speak_line": "点「选择台词…」挑一条（用语言系统的配音朗读）",
                "speak_dialogue": "点「选择对白…」挑一段（按顺序朗读整段对白）"}.get(act, "")

    @staticmethod
    def _step_text(st):
        """步骤列表显示文本。v2.1 修复：支持 speak_line/speak_dialogue，并对未知动作
        用 .get 兜底——此前落到 st["ms"] 会 KeyError，选中该行为即抛异常，
        保存时步骤列表被清空 = 静默数据丢失。"""
        act = st.get("act")
        if act == "play_action":
            return "动作：%s" % (st.get("name") or "?")
        if act == "say":
            return "台词：%s" % (st.get("text") or "")
        if act == "voice":
            return "语音：%s" % (st.get("event") or "?")
        if act == "emote":
            return "表情：%s" % (st.get("kind") or "?")
        if act == "form":
            return "切形态：%s" % (st.get("name") or "?")
        if act == "sleep":
            return "入睡"
        if act == "speak_line":
            return "读台词：%s" % (st.get("line_id") or "?")
        if act == "speak_dialogue":
            return "读对白：%s" % (st.get("dialogue_id") or "?")
        if act == "wait":
            return "等待 %d ms" % int(st.get("ms") or 0)
        return "未知步骤：%s" % act

    # ---------- 待机/时长设置 ----------
    def _save_cfg_vals(self):
        """写回行为/待机时长。v2.1：空闲秒数写新键 idle_trigger_delay（旧键只是兼容别名，
        写入旧键不会生效——M1 修复）。"""
        cfg = getattr(self.pet, "cfg", None)
        if not isinstance(cfg, dict):
            return
        cfg["idle_trigger_delay"] = self._idle_secs.value()
        cfg["idle_behavior_seconds"] = self._idle_secs.value()  # 旧键同步（兼容旧版读取）
        cfg["transform_seconds"] = self._transform_secs.value()
        self._save_cfg(cfg)

    def _on_idle_pick(self, _idx):
        """待机行为下拉（旧控件）：v2.1 起改写成**新待机配置**（idle_actions + single 模式），
        不再写旧键 idle_behavior —— 否则旧键会把用户在待机设置里删掉的行为"复活"（M2）。"""
        cfg = getattr(self.pet, "cfg", None)
        if not isinstance(cfg, dict):
            return
        bid = self._idle_combo.currentData() or ""
        data = {"idle_actions": [], "idle_play_mode": "sequential"}
        if bid:
            data = {"idle_actions": [{"id": bid, "behavior_id": bid, "enabled": True,
                                      "weight": 1.0, "order": 1}],
                    "idle_play_mode": "single"}
        if _call(self.pet, "apply_idle_settings", data) is None:
            self._save_cfg(cfg)  # 兜底：老 pet 没有新入口时仍保存（不崩）

    # ---------- 列表 ----------
    def _refresh(self):
        self._list.clear()
        _cfg = getattr(self.pet, "cfg", {}) or {}
        # 待机行为下拉：不启用 + 全部行为
        self._idle_combo.blockSignals(True)
        self._idle_combo.clear()
        self._idle_combo.addItem("（不启用 → 默认待机）", "")
        if self.svc is not None:
            for b in self.svc.list():
                self._list.addItem("%s（%d 步）" % (b["name"], len(b["steps"])))
                self._list.item(self._list.count() - 1).setData(Qt.ItemDataRole.UserRole, b["id"])
                self._idle_combo.addItem("空闲时：" + b["name"], b["id"])
        # 当前待机取自新配置：idle_actions 只有一条且模式 single 时显示它
        _acts = _cfg.get("idle_actions") or []
        _cur = str(_acts[0].get("behavior_id") or "") if (
            _cfg.get("idle_play_mode") == "single" and len(_acts) == 1) else ""
        _found = self._idle_combo.findData(_cur)
        self._idle_combo.setCurrentIndex(_found if _found >= 0 else 0)
        self._idle_combo.blockSignals(False)
        try:
            self._idle_secs.blockSignals(True)
            self._idle_secs.setValue(int(_cfg.get("idle_behavior_seconds",
                                                  pet_behaviors.DEFAULT_BEHAVIOR_CFG["idle_behavior_seconds"])))
            self._transform_secs.blockSignals(True)
            self._transform_secs.setValue(int(_cfg.get("transform_seconds",
                                                       pet_behaviors.DEFAULT_BEHAVIOR_CFG["transform_seconds"])))
        except (TypeError, ValueError):
            # 有意忽略：坏值回默认（load 时 normalize 已兜底，此处防御外部直改 cfg）
            self._idle_secs.setValue(pet_behaviors.DEFAULT_BEHAVIOR_CFG["idle_behavior_seconds"])
            self._transform_secs.setValue(pet_behaviors.DEFAULT_BEHAVIOR_CFG["transform_seconds"])
        finally:
            self._idle_secs.blockSignals(False)
            self._transform_secs.blockSignals(False)

    def _on_sel(self, row):
        if row < 0 or self.svc is None:
            return
        _b = self.svc.get(self._list.item(row).data(Qt.ItemDataRole.UserRole))
        if _b is None:
            return
        self._editing_id = _b["id"]
        self._name.setText(_b["name"])
        self._steps.clear()
        for _st in _b["steps"]:
            _it = QListWidgetItem(self._step_text(_st))
            _it.setData(Qt.ItemDataRole.UserRole, _st)
            self._steps.addItem(_it)

    def _new(self):
        self._editing_id = None
        self._name.clear()
        self._steps.clear()
        self._list.setCurrentRow(-1)

    def _add_step(self):
        act = self._act_combo.currentData()
        raw = self._param.text().strip()
        st = {"act": act}
        if act == "play_action":
            if not raw:
                _warn(self, "行为编辑", "请填动作名")
                return
            st["name"] = raw
        elif act == "say":
            if not raw:
                _warn(self, "行为编辑", "请填台词")
                return
            st["text"] = raw
        elif act == "voice":
            st["event"] = raw or "poke"
        elif act == "emote":
            st["kind"] = raw or "note"
        elif act == "form":
            if not raw:
                _warn(self, "行为编辑", "请填形态名")
                return
            st["name"] = raw
        elif act == "wait":
            st["ms"] = raw or "500"
        elif act == "speak_line":
            lid = raw or self._pick_from_lines()
            if not lid:
                return
            st["line_id"] = lid
        elif act == "speak_dialogue":
            did = raw or self._pick_from_dialogues()
            if not did:
                return
            st["dialogue_id"] = did
        norm, err = pet_behaviors.validate_steps([st])
        if norm is None:
            _warn(self, "行为编辑", err)
            return
        _it = QListWidgetItem(self._step_text(norm[0]))
        _it.setData(Qt.ItemDataRole.UserRole, norm[0])
        self._steps.addItem(_it)
        self._param.clear()

    def _pick_from_lines(self):
        """行为步骤「读台词」：从台词库选一条（返回 line_id 或 ""）。"""
        lib = _get(self.pet, "lines_lib")
        if lib is None:
            _warn(self, "行为编辑", "台词库不可用")
            return ""
        items = lib.lines()
        if not items:
            _warn(self, "行为编辑", "台词库是空的，先去「💬 自定义台词…」建一条")
            return ""
        labels = _unique_labels(
            ["[%s] %s" % (pet_lines.CATEGORY_LABELS.get(x["category"], x["category"]),
                          x["text"].replace("\n", " ")[:24]) for x in items])
        label, ok = QInputDialog.getItem(self, "选择台词", "这条行为要读哪句台词：", labels, 0, False)
        if not ok:
            return ""
        return items[labels.index(label) if label in labels else 0]["id"]

    def _pick_from_dialogues(self):
        """行为步骤「读整段对白」：从对白列表选一段（返回 dialogue_id 或 ""）。"""
        lib = _get(self.pet, "lines_lib")
        if lib is None:
            _warn(self, "行为编辑", "台词库不可用")
            return ""
        items = lib.dialogues()
        if not items:
            _warn(self, "行为编辑", "还没有对白，先去「💬 自定义台词… → 对白编排」建一段")
            return ""
        labels = _unique_labels(["%s（%d 条）" % (x["name"], len(x["line_ids"])) for x in items])
        label, ok = QInputDialog.getItem(self, "选择对白", "这条行为要读哪段对白：", labels, 0, False)
        if not ok:
            return ""
        return items[labels.index(label) if label in labels else 0]["id"]

    def _collect_steps(self):
        out = []
        for _i in range(self._steps.count()):
            _st = self._steps.item(_i).data(Qt.ItemDataRole.UserRole)
            if isinstance(_st, dict):
                out.append(_st)
        return out

    def _save(self):
        if self.svc is None:
            return
        _steps = self._collect_steps()
        if self._editing_id:
            _ok, _err = self.svc.update(self._editing_id, self._name.text(), _steps)
        else:
            _b, _err = self.svc.add(self._name.text(), _steps)
            _ok = _b is not None
            if _ok:
                self._editing_id = _b["id"]  # 新建成功后进入编辑态（试播/再保存走 update）
        if not _ok:
            _warn(self, "行为编辑", _err or "保存失败")
            return
        _row = self._list.currentRow()
        self._refresh()
        if _row >= 0 and _row < self._list.count():
            self._list.setCurrentRow(_row)

    def _delete(self):
        _row = self._list.currentRow()
        if _row < 0 or self.svc is None:
            return
        _bid = self._list.item(_row).data(Qt.ItemDataRole.UserRole)
        _ok, _err = self.svc.delete(_bid)
        if not _ok:
            _warn(self, "行为编辑", _err)
            return
        # 删除的若是当前待机行为 → 同步清配置（防悬挂引用静默失效）
        _cfg = getattr(self.pet, "cfg", None)
        if isinstance(_cfg, dict) and str(_cfg.get("idle_behavior") or "") == _bid:
            _cfg["idle_behavior"] = ""
            self._save_cfg(_cfg)
        self._new()
        self._refresh()

    def _test_play(self):
        self._save()  # 先保存再试播（试播内容 = 已保存内容）
        if self._editing_id:
            _runner = getattr(self.pet, "_run_behavior", None)
            if _runner is not None:
                _runner(self._editing_id)

    def _import(self):
        if self.svc is None:
            return
        _path, _f = QFileDialog.getOpenFileName(self, "导入行为资源", "", "行为 JSON (*.json)")
        if not _path:
            return
        _b, _err = self.svc.import_file(_path)
        if _b is None:
            _warn(self, "行为编辑", _err)
            return
        self._refresh()

    def _export(self):
        _row = self._list.currentRow()
        if _row < 0 or self.svc is None:
            return
        _bid = self._list.item(_row).data(Qt.ItemDataRole.UserRole)
        _path, _f = QFileDialog.getSaveFileName(self, "导出行为资源", "", "行为 JSON (*.json)")
        if not _path:
            return
        _ok, _err = self.svc.export_file(_bid, _path)
        if not _ok:
            _warn(self, "行为编辑", _err)


# ---------------- v2.0.5：闹钟 ----------------
class AlarmDialog(QDialog):
    """闹钟设置：列表 + 新建/编辑/删除 + 自定义铃声（wav/mp3）+ 启用开关 + 试听。"""

    DEFAULT_TIME = QTime(7, 30)  # 新建闹钟默认时间（唯一来源）

    def __init__(self, pet, svc=None):
        super().__init__(pet)
        self.pet = pet
        self.svc = svc or getattr(pet, "alarms", None)
        self._editing_id = None
        self._pending_ringtone = ""  # 本次导入的新铃声文件名（保存时写入）
        self._ring_dirty = False
        self.setWindowTitle("闹钟")
        self.setStyleSheet(DIALOG_QSS)
        self.resize(540, 470)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("闹钟列表（到点气泡提醒 + 铃声 + 语音播报；"
                             "今天已过的时刻会立即响一次）"))
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_sel)
        lay.addWidget(self._list, 2)
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("时间"))
        self._time = QTimeEdit()
        self._time.setDisplayFormat("HH:mm")
        row1.addWidget(self._time)
        row1.addWidget(QLabel("文案"))
        self._label = QLineEdit()
        self._label.setPlaceholderText("到点气泡与语音文案（默认「闹钟」）")
        row1.addWidget(self._label, 1)
        lay.addLayout(row1)
        row2 = QHBoxLayout()
        self._ring_btn = QPushButton("选铃声…（wav/mp3）")
        self._ring_btn.clicked.connect(self._pick_ringtone)
        self._ring_clear = QPushButton("清除铃声")
        self._ring_clear.clicked.connect(self._clear_ring)
        self._ring_test = QPushButton("试听")
        self._ring_test.clicked.connect(self._test_ring)
        row2.addWidget(self._ring_btn)
        row2.addWidget(self._ring_clear)
        row2.addWidget(self._ring_test)
        self._ck_enabled = QCheckBox("启用")
        self._ck_enabled.setChecked(True)
        row2.addWidget(self._ck_enabled)
        row2.addStretch(1)
        lay.addLayout(row2)
        self._ring_label = QLabel("（默认提示音）")
        self._ring_label.setWordWrap(True)
        lay.addWidget(self._ring_label)
        btn_row = QHBoxLayout()
        for _lbl, _cb in (("新建", self._new), ("保存", self._save),
                          ("删除", self._delete), ("关闭", self.accept)):
            _b = QPushButton(_lbl)
            _b.clicked.connect(_cb)
            btn_row.addWidget(_b)
        lay.addLayout(btn_row)
        self._time.setTime(self.DEFAULT_TIME)  # 打开即显示默认 07:30（点「新建」同款）
        self._refresh()

    # ---------- 列表 ----------
    def _refresh(self):
        self._list.clear()
        if self.svc is None:
            return
        for a in self.svc.list():
            _mark = "🔔" if a.get("ringtone") else "🔕"
            _state = "已启用" if a.get("enabled") else "已停用"
            _it = QListWidgetItem("%s  %s　%s　%s" % (a["time"], _mark, a["label"], _state))
            _it.setData(Qt.ItemDataRole.UserRole, a["id"])
            self._list.addItem(_it)

    def _on_sel(self, row):
        if row < 0 or self.svc is None:
            return
        _a = self.svc.get(self._list.item(row).data(Qt.ItemDataRole.UserRole))
        if _a is None:
            return
        self._editing_id = _a["id"]
        _t = QTime.fromString(_a["time"], "HH:mm")
        self._time.setTime(_t if _t.isValid() else self.DEFAULT_TIME)
        self._label.setText(_a.get("label") or "")
        self._ck_enabled.setChecked(bool(_a.get("enabled")))
        self._pending_ringtone = _a.get("ringtone") or ""
        self._ring_dirty = False
        self._ring_label.setText("铃声：" + self._pending_ringtone if self._pending_ringtone
                                 else "（默认提示音）")

    def _new(self):
        self._editing_id = None
        self._time.setTime(self.DEFAULT_TIME)
        self._label.clear()
        self._ck_enabled.setChecked(True)
        self._pending_ringtone = ""
        self._ring_dirty = True  # 新建：保存时把「默认提示音」作为初始值落盘（add 走 ringtone=""）
        self._ring_label.setText("（默认提示音）")
        self._list.setCurrentRow(-1)

    # ---------- 铃声 ----------
    def _pick_ringtone(self):
        if self.svc is None:
            return
        _path, _f = QFileDialog.getOpenFileName(
            self, "选铃声", "", "音频 (*%s)" % " *".join(pet_alarm.RINGTONE_EXTS))
        if not _path:
            return
        _fn, _err = self.svc.import_ringtone(_path)
        if _fn is None:
            _warn(self, "闹钟", _err)
            return
        self._pending_ringtone = _fn
        self._ring_dirty = True
        self._ring_label.setText("铃声：" + _fn)

    def _clear_ring(self):
        self._pending_ringtone = ""
        self._ring_dirty = True
        self._ring_label.setText("（默认提示音）")

    def _test_ring(self):
        _fn = self._pending_ringtone
        _path = self.svc.ringtone_path(_fn) if (self.svc and _fn) else None
        if not _path:
            _warn(self, "闹钟", "还没有铃声，先选一个（或直接保存用默认提示音）")
            return
        if _call(self.pet, "preview_audio", _path) is not True:
            _warn(self, "闹钟", "播放失败：铃声文件可能已损坏")

    # ---------- 保存/删除 ----------
    def _save(self):
        if self.svc is None:
            return
        _t = self._time.time().toString("HH:mm")
        _label = self._label.text().strip() or "闹钟"
        _enabled = self._ck_enabled.isChecked()
        if self._editing_id:
            _ok, _err = self.svc.update(self._editing_id, time_s=_t, label=_label,
                                        enabled=_enabled,
                                        ringtone=self._pending_ringtone if self._ring_dirty else None)
            _saved_id = self._editing_id
        else:
            # v2.0.5 修复：新建也必须落「启用」勾选（此前恒启用，违背用户意图）
            _a, _err = self.svc.add(_t, _label, self._pending_ringtone, enabled=_enabled)
            _ok = _a is not None
            _saved_id = _a["id"] if _ok else None
        if not _ok:
            _warn(self, "闹钟", _err or "保存失败")
            return
        self._refresh()
        # 恢复选中到刚保存的闹钟（_on_sel 回填保存后的规范化值，表单状态干净）
        for _i in range(self._list.count()):
            if self._list.item(_i).data(Qt.ItemDataRole.UserRole) == _saved_id:
                self._list.setCurrentRow(_i)
                break

    def _delete(self):
        _row = self._list.currentRow()
        if _row < 0 or self.svc is None:
            return
        _aid = self._list.item(_row).data(Qt.ItemDataRole.UserRole)
        _a = self.svc.get(_aid)
        _tlabel = ("「%s」%s" % (_a.get("label"), _a.get("time"))) if _a else "这个闹钟"
        if not _confirm(self, "闹钟", "删除 %s 吗？" % _tlabel):
            return
        _ok, _err = self.svc.delete(_aid)
        if not _ok:
            _warn(self, "闹钟", _err)
            return
        self._new()
        self._refresh()


# ---------------- a) 角色面板 ----------------
class _ApiTestWorker(QThread):
    """v2.0.4：AI 连通性测试（工作线程；结果经 Signal 回主线程，绝不跨线程触 UI）。"""

    result = Signal(str)

    def __init__(self, base_url, model, key, parent=None):
        super().__init__(parent)
        self._args = (base_url, model, key)

    def run(self):
        try:
            _ok, _msg = pet_chat.test_api_connection(self._args[0], self._args[1],
                                                     self._args[2], timeout=10)
            self.result.emit(("✅ " if _ok else "❌ ") + _msg)
        except Exception:
            # 有意忽略：test_api_connection 已兜底不抛；此处防御性收尾（线程内不触 UI）
            self.result.emit("❌ 测试失败，请稍后再试")


# v2.0.4：在途测试线程登记表——退出路径（桌宠._quit → shutdown_api_tests）
# 收敛所有在途 QThread，防「运行中析构 QThread」Qt6 致命崩溃
_API_TEST_WORKERS = set()


def shutdown_api_tests():
    """退出前收敛在途 API 测试线程（wait 至测试超时；仍不死才 terminate）。"""
    for w in list(_API_TEST_WORKERS):
        try:
            if not w.isRunning():
                continue
            w.wait(11000)
            if w.isRunning():
                w.terminate()
                w.wait(2000)
        except RuntimeError:
            pass  # 有意忽略：线程已被删除（幂等收敛）


class AISettingsDialog(QDialog):
    """AI 接口/模型/人设/回复长度设置（P1-10，OpenAI 兼容，支持本地 Ollama）。

    v2.0.4：服务商预设（一键填地址/模型）+ 连通性测试（错误归类中文提示）。"""

    def __init__(self, parent=None):
        super().__init__(_qt_parent(parent))
        self._pet = parent
        self._worker = None
        self.setWindowTitle("AI 设置")
        self.setStyleSheet(DIALOG_QSS)
        self.resize(560, 560)
        cfg = _get(parent, "cfg") or {}
        root = QVBoxLayout(self)
        # v2.0.4：服务商预设（选中即填接口地址与模型名，仍可手改）
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("服务商预设"))
        self._preset = QComboBox()
        for _pid, _p in pet_chat.AI_PROVIDERS.items():
            self._preset.addItem(_p["name"], _pid)
            if _pid in ("qianfan", "siliconflow"):
                self._preset.insertSeparator(self._preset.count())  # 国内/国际/本地分组分隔线
        self._preset.setCurrentIndex(self._preset.findData("custom"))
        self._preset.currentIndexChanged.connect(self._on_preset_changed)
        preset_row.addWidget(self._preset, 1)
        root.addLayout(preset_row)
        root.addWidget(QLabel("接口地址（OpenAI 兼容；留空 = DeepSeek 官方）"))
        self._base = QLineEdit(cfg.get("ai_base_url", ""))
        self._base.setPlaceholderText(pet_chat.DEFAULT_BASE_URL)
        root.addWidget(self._base)
        root.addWidget(QLabel("模型名（本地 Ollama 可填 qwen2.5 之类）"))
        self._model = QLineEdit(cfg.get("ai_model", pet_chat.DEFAULT_MODEL))
        root.addWidget(self._model)
        # v2.0.4：连通性测试（错误归类中文提示）
        test_row = QHBoxLayout()
        self._test_btn = QPushButton("测试连接")
        self._test_btn.clicked.connect(self._test_connection)
        self._test_label = QLabel("")
        self._test_label.setWordWrap(True)
        test_row.addWidget(self._test_btn)
        test_row.addWidget(self._test_label, 1)
        root.addLayout(test_row)
        root.addWidget(QLabel("人设预设（选「自定义」可完全自己写）"))
        self._persona = QComboBox()
        self._persona.addItem("内置大肥鱼（又娇又赖，默认）", "default")
        self._persona.addItem("啥子蛇（毒舌腹黑「本专员」）", "sheshe")
        self._persona.addItem("傲娇系（嘴硬心软）", "tsundere")
        self._persona.addItem("自定义（自己写人设）", "custom")
        root.addWidget(self._persona)
        self._persona.currentIndexChanged.connect(self._on_persona_changed)
        cur_persona = str(cfg.get("ai_persona", "default") or "default")
        _pi = self._persona.findData(cur_persona)
        if _pi >= 0:
            self._persona.setCurrentIndex(_pi)
        root.addWidget(QLabel("自定义人设（选「自定义」预设后生效；留空 = 内置大肥鱼人设）"))
        self._prompt = QPlainTextEdit()
        self._prompt.setPlainText(cfg.get("ai_system_prompt", ""))
        self._prompt.setPlaceholderText("例：你是一只高冷的猫猫桌宠，只对绳匠一个人温柔……")
        root.addWidget(self._prompt, 1)
        self._on_persona_changed(self._persona.currentIndex())
        row = QHBoxLayout()
        row.addWidget(QLabel("回复字数上限"))
        self._reply = QSpinBox()
        self._reply.setRange(4, 50)
        self._reply.setValue(int(cfg.get("ai_reply_len", 25) or 25))  # norm-ok（配置加载时已归一化）
        row.addWidget(self._reply)
        row.addWidget(QLabel("max_tokens"))
        self._tokens = QSpinBox()
        self._tokens.setRange(16, 512)
        self._tokens.setValue(int(cfg.get("ai_max_tokens", 60) or 60))  # norm-ok
        row.addWidget(self._tokens)
        row.addStretch(1)
        root.addLayout(row)
        btns = QHBoxLayout()
        ok = QPushButton("保存")
        cancel = QPushButton("取消")
        ok.setDefault(True)
        ok.clicked.connect(self._save)
        cancel.clicked.connect(self.reject)
        btns.addStretch(1)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        root.addLayout(btns)

    def _on_persona_changed(self, _idx):
        """预设选择：仅「自定义」时启用人设编辑框。"""
        self._prompt.setEnabled(self._persona.currentData() == "custom")

    def _on_preset_changed(self, _idx):
        """v2.0.4：服务商预设——选中即填接口地址与模型名（custom 不覆盖用户输入）。"""
        _pid = self._preset.currentData()
        _p = pet_chat.AI_PROVIDERS.get(_pid)
        if not _p or _pid == "custom":
            return
        self._base.setText(_p.get("base_url", ""))
        self._model.setText(_p.get("model", ""))

    def _test_connection(self):
        """v2.0.4：用当前填写的地址/模型/Key 发最小请求，结果归类中文提示。"""
        try:
            _running = self._worker is not None and self._worker.isRunning()
        except RuntimeError:
            _running = False  # 已删除的线程包装（幂等防御）
        if _running:
            return  # 测试进行中：不重复发起
        cfg = _get(self._pet, "cfg") or {}
        _key = str(cfg.get("api_key") or "")
        _base_now = self._base.text().strip().rstrip("/")
        if not _key and not pet_chat.is_local_base(_base_now):
            # 云服务商需要 Key；本地服务（Ollama 等）放行空 Key
            self._test_label.setText("❌ 云服务商要先填 API Key（本地 Ollama 无需 Key）")
            return
        self._test_btn.setEnabled(False)
        self._test_label.setText("测试中……")
        # 线程不挂父对象：对话框关闭不能拖线程下水（运行中销毁 QThread 会崩）；
        # finished → deleteLater 由绑定方法自持引用，线程自然结束后自删；
        # 同时登记进全局表，退出路径由 shutdown_api_tests 收敛
        self._worker = _ApiTestWorker(_base_now, self._model.text().strip(), _key, None)
        self._worker.result.connect(self._on_test_result)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.finished.connect(lambda w=self._worker: _API_TEST_WORKERS.discard(w))
        _API_TEST_WORKERS.add(self._worker)
        self._worker.start()

    def _on_test_result(self, msg):
        """测试结果（主线程）：回填标签并恢复按钮。"""
        self._test_label.setText(msg)
        self._test_btn.setEnabled(True)
        self._worker = None  # 结果已回：释放引用，线程由 finished→deleteLater 收尾

    def closeEvent(self, event):
        """关闭对话框：在途测试线程断连结果槽后自然结束（不随窗口销毁）。"""
        _w = getattr(self, "_worker", None)
        try:
            _running = _w is not None and _w.isRunning()
        except RuntimeError:
            _running = False  # 已删除的线程包装（幂等防御）
        if _running:
            try:
                _w.result.disconnect(self._on_test_result)
            except (TypeError, RuntimeError):
                pass  # 有意忽略：已断开或槽不存在（幂等）
        super().closeEvent(event)

    def _save(self):
        data = {
            "ai_base_url": self._base.text().strip().rstrip("/"),
            "ai_model": self._model.text().strip() or pet_chat.DEFAULT_MODEL,
            "ai_persona": self._persona.currentData() or "default",
            "ai_system_prompt": self._prompt.toPlainText().strip(),
            "ai_reply_len": self._reply.value(),
            "ai_max_tokens": self._tokens.value(),
        }
        _call(self._pet, "apply_ai_settings", data)
        self.accept()


class RolePanel(QWidget):
    """角色列表 + 预览 + 导入 / 设为当前 / 删除 / 恢复默认。"""

    def __init__(self, parent=None):
        super().__init__(_qt_parent(parent))
        self._pet = parent
        self._lib = _get(parent, "role_lib")
        self.setStyleSheet(DIALOG_QSS)

        root = QHBoxLayout(self)
        left = QVBoxLayout()
        self._info = QLabel("当前：默认角色")
        left.addWidget(self._info)
        self._list = QListWidget()
        self._list.setMinimumWidth(340)
        self._list.currentItemChanged.connect(self._on_select)
        left.addWidget(self._list, 1)
        btns = QHBoxLayout()
        self._btn_import = QPushButton("导入角色…")
        self._btn_set = QPushButton("设为当前")
        self._btn_edit = QPushButton("编辑…")
        self._btn_del = QPushButton("删除")
        self._btn_default = QPushButton("恢复默认")
        for b in (self._btn_import, self._btn_set, self._btn_edit,
                  self._btn_del, self._btn_default):
            btns.addWidget(b)
        self._btn_import.clicked.connect(self._import)
        self._btn_set.clicked.connect(self._set_active)
        self._btn_edit.clicked.connect(self._edit)
        self._btn_del.clicked.connect(self._delete)
        self._btn_default.clicked.connect(self._reset_default)
        left.addLayout(btns)
        root.addLayout(left, 1)

        right = QVBoxLayout()
        cap1 = QLabel("形态 1")
        cap1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right.addWidget(cap1)
        self._preview = QLabel("预览")
        self._preview.setFixedSize(200, 200)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setStyleSheet(
            "background-color:#2e3560;border:1px solid #3d477f;"
            "border-radius:8px;color:#8f97c0;")
        right.addWidget(self._preview)
        cap2 = QLabel("形态 2")
        cap2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right.addWidget(cap2)
        self._preview_full = QLabel("预览")
        self._preview_full.setFixedSize(200, 200)
        self._preview_full.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_full.setStyleSheet(
            "background-color:#2e3560;border:1px solid #3d477f;"
            "border-radius:8px;color:#8f97c0;")
        right.addWidget(self._preview_full)
        self._meta = QLabel("")
        self._meta.setWordWrap(True)
        right.addWidget(self._meta)
        right.addStretch(1)
        root.addLayout(right)

        self._refresh()

    # ---------- 内部 ----------
    def _refresh(self):
        self._list.clear()
        if self._lib is None:
            self._list.addItem("角色库不可用")
            for b in (self._btn_import, self._btn_set, self._btn_edit,
                      self._btn_del, self._btn_default):
                b.setEnabled(False)
            self._info.setText("当前：默认角色")
            self._preview.setText("角色库不可用")
            self._preview.setPixmap(QPixmap())
            self._preview_full.setText("角色库不可用")
            self._preview_full.setPixmap(QPixmap())
            self._meta.setText("")
            return
        for b in (self._btn_import, self._btn_set, self._btn_edit,
                  self._btn_del, self._btn_default):
            b.setEnabled(True)
        active = self._lib.active_id()
        active_name = ""
        for role in self._lib.list_roles():
            size_text = "?x?"
            p = self._lib.path_for(role["id"])
            if p:
                try:
                    pix = QPixmap(p)
                    if not pix.isNull():
                        size_text = "%dx%d" % (pix.width(), pix.height())
                except Exception:
                    pass  # 有意忽略：尺寸探测失败显示 ?x?（预览信息尽力而为）
            mark = " [当前]" if role["id"] == active else ""
            nf = len(role.get("forms") or [])
            form_text = ("%d形态" % nf) if nf >= 2 else "单形态"
            if role.get("frames"):
                form_text += "+%d帧" % len(role["frames"])
            it = QListWidgetItem("%s  %s  %s  %s%s" % (role["name"], size_text, form_text, role.get("added", ""), mark))
            it.setData(Qt.ItemDataRole.UserRole, role["id"])
            self._list.addItem(it)
            if role["id"] == active:
                active_name = role["name"]
                self._list.setCurrentItem(it)
        self._info.setText(("当前：%s" % active_name) if active else "当前：默认角色")
        if self._list.count() == 0:
            self._preview.setPixmap(QPixmap())
            self._preview.setText("暂无角色\n点「导入角色…」加一个")
            self._preview_full.setPixmap(QPixmap())
            self._preview_full.setText("暂无角色")
            self._meta.setText("")

    def _on_select(self, item, _prev):
        if item is None or self._lib is None:
            self._preview.setPixmap(QPixmap())
            self._preview_full.setPixmap(QPixmap())
            self._meta.setText("")
            return
        rid = item.data(Qt.ItemDataRole.UserRole)
        p = self._lib.path_for(rid)
        if not p:
            self._preview.setPixmap(QPixmap())
            self._preview.setText("文件缺失，无法预览")
            self._preview_full.setPixmap(QPixmap())
            self._meta.setText("")
            return
        pix = QPixmap(p)
        if pix.isNull():
            self._preview.setPixmap(QPixmap())
            self._preview.setText("无法预览")
            self._preview_full.setPixmap(QPixmap())
            self._meta.setText("")
            return
        scaled = pix.scaled(200, 200, Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
        self._preview.setText("")
        self._preview.setPixmap(scaled)
        fp = self._lib.path_for_full(rid)
        if fp:
            try:
                pf = QPixmap(fp)
                if not pf.isNull():
                    self._preview_full.setText("")
                    self._preview_full.setPixmap(pf.scaled(
                        200, 200, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation))
                    self._meta.setText(self._meta_text(rid, pix))
                else:
                    self._preview_full.setPixmap(QPixmap())
                    self._preview_full.setText("形态 2 无法预览")
                    self._meta.setText(self._meta_text(rid, pix))
            except Exception:
                self._preview_full.setPixmap(QPixmap())
                self._preview_full.setText("吃饱图无法预览")
        else:
            self._preview_full.setPixmap(QPixmap())
            self._preview_full.setText("单形态：无第二形态")
            self._meta.setText(self._meta_text(rid, pix))

    def _parent_widget(self):
        return self._pet if isinstance(self._pet, QWidget) else self

    def _meta_text(self, rid, pix):
        """预览元信息：尺寸 + 形态数（≥3 形态注明仅预览前 2 个）。"""
        nf = len(self._lib.form_metas(rid)) if self._lib else 0
        if nf <= 1:
            return "%dx%d · 单形态" % (pix.width(), pix.height())
        if nf == 2:
            return "%dx%d · 双形态" % (pix.width(), pix.height())
        return "%dx%d · %d形态（仅预览前 2 个）" % (pix.width(), pix.height(), nf)

    # ---------- 动作 ----------
    def _import(self):
        """导入角色：弹出向导（多形态自定 + 素材自动处理）→ 落库 → 切换。"""
        if self._lib is None:
            return
        dlg = RoleImportDialog(self._parent_widget())
        try:
            if modal(dlg) != QDialog.DialogCode.Accepted:
                return
            data = dlg.result_data()
            if not data:
                return
            forms_src = data.get("forms") or None
            opts = data.get("options") or {}
            role, err = self._lib.import_processed(
                data["base"], None, data["name"],
                frames_src=data.get("frames") or None,
                forms_src=forms_src,
                interval_ms=opts.get("interval_ms"),
                render=opts.get("render"),
                keep_source=bool(opts.get("keep_source")),
                source_files=data.get("sources"),
            )
            if role is None:
                _warn(self._parent_widget(), "导入角色", err or "导入失败")
                return
            _call(self._pet, "apply_role", role["id"])  # 导入即切换为新角色
            self._refresh()
            n_forms = len(forms_src or [])
            if data.get("frames"):
                tip = ("帧动画角色：待机循环播放 %d 帧；喂食在 %d 个形态间切换，12 秒后回第一形态。"
                       % (len(data["frames"]), max(1, n_forms)))
            elif n_forms >= 2:
                tip = ("%d 形态角色：喂食依次切换形态，12 秒后回「%s」。"
                       % (n_forms, forms_src[0][0]))
            else:
                tip = "单形态角色：喂食后仍是同一形象（可重新导入添加更多形态）。"
            _info(self._parent_widget(), "导入角色",
                  "导入成功！\n\n· %s\n\n%s" % ("\n· ".join(data["notes"]), tip))
        finally:
            dlg._cleanup()  # 任何路径都清理向导临时文件（含取消/失败）

    def _edit(self):
        """P1-7：编辑选中角色（改名/换图/调序/渲染参数/状态图，不换 id）。"""
        if self._lib is None:
            return
        it = self._list.currentItem()
        if it is None:
            _warn(self._parent_widget(), "编辑角色", "先在列表里选中一个角色")
            return
        rid = it.data(Qt.ItemDataRole.UserRole)
        if not rid:
            return
        dlg = RoleEditDialog(self._parent_widget(), self._lib, rid)
        try:
            if modal(dlg) != QDialog.DialogCode.Accepted:
                return
            role = self._lib.get(rid) or {}
            self._refresh()
            # 编辑的是当前角色 → 立即重载贴图（换图/调参实时生效）
            if self._lib.active_id() == rid:
                _call(self._pet, "apply_role", rid)
            _info(self._parent_widget(), "编辑角色",
                  "已保存「%s」的修改。" % role.get("name", ""))
        finally:
            dlg._cleanup()  # 任何路径都清理编辑临时目录

    def _set_active(self):
        if self._lib is None:
            return
        it = self._list.currentItem()
        if it is None:
            return
        rid = it.data(Qt.ItemDataRole.UserRole)
        if not rid:
            return
        if hasattr(self._pet, "apply_role"):
            _call(self._pet, "apply_role", rid)  # 主线内部 set_active + 保存 + 重载贴图
        elif not self._lib.set_active(rid):
            _warn(self._parent_widget(), "切换角色", "切换失败")
            return
        self._refresh()

    def _delete(self):
        if self._lib is None:
            return
        it = self._list.currentItem()
        if it is None:
            return
        rid = it.data(Qt.ItemDataRole.UserRole)
        if not rid:
            return
        role = self._lib.get(rid) or {}
        if not _confirm(self._parent_widget(), "删除角色",
                        "确定删除角色「%s」吗？" % role.get("name", "")):
            return
        ok, err = self._lib.delete(rid)
        if not ok:
            _warn(self._parent_widget(), "删除角色", err or "删除失败")
            return
        self._refresh()
        _call(self._pet, "apply_role", self._lib.active_id())

    def _reset_default(self):
        if self._lib is None:
            return
        if hasattr(self._pet, "apply_role"):
            _call(self._pet, "apply_role", "")
        else:
            self._lib.set_active("")
        self._refresh()


# ---------------- b) 音效面板 ----------------
class SoundPanel(QWidget):
    """音频片段列表（试听 / 导入 / 重命名 / 删除）+ 自定义音效组 5 行槽位。"""

    def __init__(self, parent=None):
        super().__init__(_qt_parent(parent))
        self._pet = parent
        self._lib = _get(parent, "audio_lib")
        self.setStyleSheet(DIALOG_QSS)

        root = QVBoxLayout(self)
        root.addWidget(QLabel("音频片段（自定义音效素材）"))
        top = QHBoxLayout()
        self._list = QListWidget()
        self._list.setMinimumHeight(130)
        top.addWidget(self._list, 1)
        rbtns = QVBoxLayout()
        b_preview = QPushButton("试听")
        b_import = QPushButton("导入音频…")
        b_rename = QPushButton("重命名")
        b_del = QPushButton("删除")
        for b in (b_preview, b_import, b_rename, b_del):
            rbtns.addWidget(b)
        b_preview.clicked.connect(self._preview_selected)
        b_import.clicked.connect(self._import_audio)
        b_rename.clicked.connect(self._rename)
        b_del.clicked.connect(self._delete_audio)
        rbtns.addStretch(1)
        top.addLayout(rbtns)
        root.addLayout(top)

        root.addWidget(QLabel("自定义音效组（留默认 = 用内置音效，静音 = 该事件不出声）"))
        grid = QGridLayout()
        self._combos = {}
        for i, (kind, label) in enumerate(_SLOT_LABELS):
            cb = QComboBox()
            cb.currentIndexChanged.connect(lambda _idx, k=kind: self._on_slot(k))
            grid.addWidget(QLabel(label), i, 0)
            grid.addWidget(cb, i, 1)
            self._combos[kind] = cb
        root.addLayout(grid)

        self._refresh()

    def _parent_widget(self):
        return self._pet if isinstance(self._pet, QWidget) else self

    # ---------- 内部 ----------
    def _refresh(self):
        self._list.clear()
        frags = self._lib.fragments() if self._lib else []
        for f in frags:
            dur = f.get("duration")
            dur_text = ("%.1fs" % dur) if isinstance(dur, (int, float)) else "?s"
            it = QListWidgetItem("%s  ·  %s  ·  %s" % (f["name"], dur_text, f.get("ext", "")))
            it.setData(Qt.ItemDataRole.UserRole, f["id"])
            self._list.addItem(it)
        slots = None
        if self._lib is not None:
            try:
                slots = self._lib.group_slots().get("custom", {})
            except Exception:
                slots = None
        for kind, cb in self._combos.items():
            cb.blockSignals(True)
            cb.clear()
            cb.addItem("默认")
            cb.addItem("静音")
            for f in frags:
                label = f["name"] + ("（仅试听）" if str(f.get("ext", "")).lower() != ".wav" else "")
                cb.addItem(label)
            val = slots.get(kind) if slots else None
            if val == "":
                cb.setCurrentIndex(1)
            elif val:
                idx = -1
                for i, f in enumerate(frags):
                    if f["id"] == val:
                        idx = i
                        break
                cb.setCurrentIndex(2 + idx if idx >= 0 else 0)
            else:
                cb.setCurrentIndex(0)
            cb.setEnabled(self._lib is not None)
            cb.blockSignals(False)

    def _on_slot(self, kind):
        if self._lib is None:
            return
        cb = self._combos[kind]
        idx = cb.currentIndex()
        frags = self._lib.fragments()
        if idx == 0:
            fid = None      # 默认：走内置音效
        elif idx == 1:
            fid = ""        # 静音
        else:
            fi = idx - 2
            fid = frags[fi]["id"] if 0 <= fi < len(frags) else None
        if not self._lib.set_slot(kind, fid):
            _warn(self._parent_widget(), "音效组",
                  "该槽位仅支持 wav 片段（mp3 可以试听，但事件播放不支持）")
            self._refresh()  # 回滚组合框显示
            return
        _call(self._pet, "apply_sound_group", self._lib.group_paths())

    # ---------- 动作 ----------
    def _preview_selected(self):
        if self._lib is None:
            return
        it = self._list.currentItem()
        if it is None:
            _warn(self._parent_widget(), "试听", "先在列表里选中一个音频片段")
            return
        fid = it.data(Qt.ItemDataRole.UserRole)
        path = self._lib.fragment_path(fid)
        if not path:
            _warn(self._parent_widget(), "试听", "音频文件丢失，无法试听")
            return
        if not _preview_audio(self._pet, path):
            _warn(self._parent_widget(), "试听", "该音频暂不支持试听（仅 wav/mp3）")

    def _import_audio(self):
        if self._lib is None:
            return
        src, _f = QFileDialog.getOpenFileName(self._parent_widget(), "导入音频", "",
                                              "音频文件 (*.wav *.mp3)")
        if not src:
            return
        frag, err = self._lib.import_file(src)
        if frag is None:
            _warn(self._parent_widget(), "导入音频", err or "导入失败")
            return
        self._refresh()

    def _rename(self):
        if self._lib is None:
            return
        it = self._list.currentItem()
        if it is None:
            return
        fid = it.data(Qt.ItemDataRole.UserRole)
        f = None
        for x in self._lib.fragments():
            if x["id"] == fid:
                f = x
                break
        if f is None:
            return
        dlg = QInputDialog(self._parent_widget())
        dlg.setWindowTitle("重命名片段")
        dlg.setLabelText("新名字：")
        dlg.setTextValue(f["name"])
        dlg.setStyleSheet(DIALOG_QSS)
        if modal(dlg) != QDialog.DialogCode.Accepted:
            return
        name = dlg.textValue().strip()
        if not name:
            return
        ok, err = self._lib.rename(fid, name)
        if not ok:
            _warn(self._parent_widget(), "重命名", err or "重命名失败")
            return
        self._refresh()

    def _delete_audio(self):
        if self._lib is None:
            return
        it = self._list.currentItem()
        if it is None:
            return
        fid = it.data(Qt.ItemDataRole.UserRole)
        f = None
        for x in self._lib.fragments():
            if x["id"] == fid:
                f = x
                break
        if f is None:
            return
        if not _confirm(self._parent_widget(), "删除音频",
                        "确定删除片段「%s」吗？\n引用它的音效组槽位将变为静音。" % f["name"]):
            return
        ok, err = self._lib.delete(fid)
        if not ok:
            _warn(self._parent_widget(), "删除音频", err or "删除失败")
            return
        self._refresh()
        _call(self._pet, "apply_sound_group", self._lib.group_paths())


# ---------------- c) 资源管理对话框 ----------------
class VoiceAssetPanel(QWidget):
    """v2.1：声音素材（参考音）管理——与音效片段**分开**管理，专供声音克隆。

    导入 / 试听 / 重命名 / 删除；显示被哪些角色绑定（绑定在语音设置里改）。"""

    def __init__(self, parent=None):
        super().__init__(_qt_parent(parent))
        self._pet = parent
        self._lib = _get(parent, "voice_assets")
        self.setStyleSheet(DIALOG_QSS)

        root = QVBoxLayout(self)
        root.addWidget(QLabel("声音素材（参考音）：声音克隆用，建议 3~10 秒干净人声（wav 最佳）"))
        top = QHBoxLayout()
        self._list = QListWidget()
        self._list.setMinimumHeight(150)
        top.addWidget(self._list, 1)
        rbtns = QVBoxLayout()
        b_preview = QPushButton("试听")
        b_import = QPushButton("导入参考音…")
        b_rename = QPushButton("重命名")
        b_del = QPushButton("删除")
        for b in (b_preview, b_import, b_rename, b_del):
            rbtns.addWidget(b)
        b_preview.clicked.connect(self._preview_selected)
        b_import.clicked.connect(self._import_asset)
        b_rename.clicked.connect(self._rename)
        b_del.clicked.connect(self._delete_asset)
        rbtns.addStretch(1)
        top.addLayout(rbtns)
        root.addLayout(top)
        self._hint = QLabel("")
        self._hint.setWordWrap(True)
        root.addWidget(self._hint)
        root.addStretch(1)
        self._refresh()

    def _parent_widget(self):
        return self._pet if isinstance(self._pet, QWidget) else self

    def _selected(self):
        it = self._list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it is not None else None

    def _refresh(self):
        self._list.clear()
        assets = self._lib.assets() if self._lib else []
        binds = {}
        try:
            binds = _get(self._pet, "voice").bindings()
        except Exception:
            binds = {}
        used = {}
        for role, vs in (binds or {}).items():
            used.setdefault(vs, []).append(role or "默认")
        for a in assets:
            dur = a.get("duration")
            dur_text = ("%.1fs" % dur) if isinstance(dur, (int, float)) else "?s"
            who = used.get(a["id"]) or []
            it = QListWidgetItem("%s  ·  %s%s  ·  %s" % (
                a["name"], dur_text, ("  ·  绑定：" + "、".join(who)) if who else "", a.get("ext", "")))
            it.setData(Qt.ItemDataRole.UserRole, a["id"])
            self._list.addItem(it)
        self._hint.setText("共 %d 个声音素材。绑定了角色的素材才能用于朗读（语音设置里绑定）。"
                           % len(assets))

    def _preview_selected(self):
        sid = self._selected()
        if not sid:
            _warn(self._parent_widget(), "声音素材", "先选中一个素材")
            return
        ok, err = _get(self._pet, "voice").preview_asset(sid) if _get(self._pet, "voice") else (False, "语音服务不可用")
        if not ok:
            _warn(self._parent_widget(), "试听", err or "试听失败")

    def _import_asset(self):
        if self._lib is None:
            return
        path, _f = QFileDialog.getOpenFileName(self._parent_widget(), "导入参考音", "",
                                               "音频 (*.wav *.mp3)")
        if not path:
            return
        asset, err = self._lib.import_file(path)
        if asset is None:
            _warn(self._parent_widget(), "导入失败", err or "导入失败")
            return
        self._refresh()

    def _rename(self):
        sid = self._selected()
        if not sid or self._lib is None:
            return
        cur = self._lib.get_asset(sid) or {}
        name, ok = QInputDialog.getText(self._parent_widget(), "重命名", "新名字：",
                                        text=cur.get("name", ""))
        if not ok:
            return
        res = self._lib.rename(sid, name)
        if res[0] is False:
            _warn(self._parent_widget(), "重命名失败", res[1])
            return
        self._refresh()

    def _delete_asset(self):
        sid = self._selected()
        if not sid or self._lib is None:
            return
        cur = self._lib.get_asset(sid) or {}
        if not _confirm(self._parent_widget(), "删除声音素材",
                        "删除「%s」吗？台词里引用它的地方会变成失效引用（会明确提示，不会静默）。"
                        % cur.get("name", sid)):
            return
        res = self._lib.delete(sid)
        if res[0] is False:
            _warn(self._parent_widget(), "删除失败", res[1])
            return
        self._refresh()


class ResourceManagerDialog(QDialog):
    """QTabWidget 三页签（角色 / 音效 / 声音素材），内嵌 RolePanel / SoundPanel / VoiceAssetPanel。"""

    def __init__(self, parent=None, initial_tab=0):
        super().__init__(_qt_parent(parent))
        self._pet = parent
        self.setWindowTitle("资源管理")
        self.setStyleSheet(DIALOG_QSS)
        self.resize(700, 560)

        root = QVBoxLayout(self)
        self._tabs = QTabWidget()
        self._tabs.addTab(RolePanel(parent), "角色")
        self._tabs.addTab(SoundPanel(parent), "音效")
        self._tabs.addTab(VoiceAssetPanel(parent), "声音素材")  # v2.1：与音效分开
        self._tabs.setCurrentIndex(max(0, min(2, int(initial_tab))))
        root.addWidget(self._tabs, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.reject)
        row.addWidget(close_btn)
        root.addLayout(row)


# ---------------- d) 记账账本对话框 ----------------
class AmountNoteDialog(QDialog):
    """记一笔：金额 QDoubleSpinBox(0.01~99999) + 备注 QLineEdit + 确定/取消。"""

    def __init__(self, parent=None):
        super().__init__(_qt_parent(parent))
        self.setWindowTitle("记一笔")
        self.setStyleSheet(DIALOG_QSS)
        root = QVBoxLayout(self)
        grid = QGridLayout()
        grid.addWidget(QLabel("金额："), 0, 0)
        self._amount = QDoubleSpinBox()
        self._amount.setRange(0.01, 99999.0)
        self._amount.setDecimals(2)
        self._amount.setValue(1.0)
        self._amount.setSuffix(" ¥")
        grid.addWidget(self._amount, 0, 1)
        grid.addWidget(QLabel("备注："), 1, 0)
        self._note = QLineEdit()
        self._note.setPlaceholderText("例如：买了小鱼干（可留空）")
        grid.addWidget(self._note, 1, 1)
        root.addLayout(grid)
        row = QHBoxLayout()
        ok_btn = QPushButton("确定")
        cancel_btn = QPushButton("取消")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(ok_btn)
        row.addWidget(cancel_btn)
        root.addLayout(row)

    def values(self):
        """返回 (金额 float 保留两位, 备注 str)。"""
        return round(float(self._amount.value()), 2), self._note.text().strip()


class LedgerDialog(QDialog):
    """账本：汇总 + 实时搜索 + 今日 / 近 7 天 / 全部 三页签 + 记一笔 / 导出 CSV。"""

    def __init__(self, parent=None):
        super().__init__(_qt_parent(parent))
        self._pet = parent
        self._book = _get(parent, "book")
        self.setWindowTitle("记账账本")
        self.setStyleSheet(DIALOG_QSS)
        self.resize(680, 540)

        root = QVBoxLayout(self)
        self._summary = QLabel("")
        self._summary.setStyleSheet("font-weight:bold;color:#ffd65a;")
        root.addWidget(self._summary)

        srow = QHBoxLayout()
        srow.addWidget(QLabel("搜索："))
        self._search = QLineEdit()
        self._search.setPlaceholderText("按日期或备注搜索（实时过滤）")
        self._search.textChanged.connect(self._refresh)
        srow.addWidget(self._search, 1)
        root.addLayout(srow)

        self._tabs = QTabWidget()
        self._today_table = _detail_table(("日期", "时间", "类型", "金额", "备注"))
        self._week_table = _detail_table(("日期", "金额", "笔数"))
        self._all_table = _detail_table(("日期", "时间", "类型", "金额", "备注"))
        self._tabs.addTab(self._today_table, "今日")
        self._tabs.addTab(self._week_table, "近 7 天")
        self._tabs.addTab(self._all_table, "全部")
        self._tabs.currentChanged.connect(lambda _i: self._refresh())
        root.addWidget(self._tabs, 1)

        row = QHBoxLayout()
        self._btn_add = QPushButton("记一笔…")
        self._btn_export = QPushButton("导出 CSV…")
        close_btn = QPushButton("关闭")
        self._btn_add.clicked.connect(self._add_manual)
        self._btn_export.clicked.connect(self._export)
        close_btn.clicked.connect(self.reject)
        row.addWidget(self._btn_add)
        row.addWidget(self._btn_export)
        row.addStretch(1)
        row.addWidget(close_btn)
        root.addLayout(row)

        if self._book is None:
            self._btn_add.setEnabled(False)
            self._btn_export.setEnabled(False)
        self._refresh()

    # ---------- 内部 ----------
    def _refresh(self):
        book = self._book
        if book is None:
            self._summary.setText("账本不可用")
            for t in (self._today_table, self._week_table, self._all_table):
                t.setRowCount(0)
            return
        today = book.today_usage()
        week = book.week_usage()
        total = book.total_amount()
        count = book.total_count()
        self._summary.setText("今日 ¥%.2f · 近7天 ¥%.2f · 累计 ¥%.2f / %d 笔"
                              % (today, week, total, count))
        term = self._search.text().strip().lower()

        # 今日明细
        tdate = time.strftime("%Y-%m-%d")
        today_recs = [r for r in book.all_records() if r["date"] == tdate]
        if term:
            today_recs = [r for r in today_recs
                          if term in r["date"].lower() or term in (r["note"] or "").lower()]
        _fill_detail(self._today_table, today_recs)

        # 近 7 天按日汇总
        counts = {}
        for r in book.all_records():
            counts[r["date"]] = counts.get(r["date"], 0) + 1
        week_rows = [(d, amt, counts.get(d, 0)) for d, amt in book.daily_totals(7)]
        if term:
            week_rows = [w for w in week_rows if term in w[0].lower()]
        self._week_table.setRowCount(len(week_rows))
        for i, (d, amt, n) in enumerate(week_rows):
            for j, text in enumerate((d, "%.2f" % amt, str(n))):
                item = QTableWidgetItem(text)
                if j == 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._week_table.setItem(i, j, item)

        # 全部明细
        all_recs = book.search_records(term) if term else book.all_records()
        _fill_detail(self._all_table, all_recs)

    def _parent_widget(self):
        return self._pet if isinstance(self._pet, QWidget) else self

    # ---------- 动作 ----------
    def _add_manual(self):
        book = self._book
        if book is None:
            return
        dlg = AmountNoteDialog(self)
        if modal(dlg) != QDialog.DialogCode.Accepted:
            return
        amount, note = dlg.values()
        if amount <= 0:
            return
        book.add_manual(amount, note)
        self._refresh()
        _call(self._pet, "on_ledger_changed")
        _call(self._pet, "show_bubble", "记下啦：¥%.2f" % amount)

    def _export(self):
        book = self._book
        if book is None:
            return
        default_path = os.path.join(os.path.expanduser("~"), "ledger.csv")
        path, _f = QFileDialog.getSaveFileName(self._parent_widget(), "导出 CSV",
                                               default_path, "CSV 文件 (*.csv)")
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        ok, err = book.export_csv(path)
        if ok:
            _info(self._parent_widget(), "导出成功", "已导出到：\n%s" % path)
        else:
            _warn(self._parent_widget(), "导出失败", err or "导出失败")


# ---------------- e) 气泡样式对话框 ----------------
class BubbleStyleDialog(QDialog):
    """气泡样式：三色 + 字号 8~18 + 圆角 0~30 + 实时预览。"""

    def __init__(self, parent=None):
        super().__init__(_qt_parent(parent))
        self._pet = parent
        self.setWindowTitle("气泡样式")
        self.setStyleSheet(DIALOG_QSS)
        self._style = dict(_DEFAULT_BUBBLE_STYLE)
        # 从配置取当前样式（防御性：缺键 / 类型非法都回退默认）
        try:
            cfg = _get(parent, "cfg") or {}
            s = cfg.get("bubble_style") if isinstance(cfg, dict) else None
            if isinstance(s, dict):
                for k in self._style:
                    v = s.get(k)
                    if v is not None:
                        self._style[k] = v
        except Exception:
            pass  # 有意忽略：样式配置异常回退默认（防御性）

        root = QVBoxLayout(self)
        grid = QGridLayout()
        self._color_btns = {}
        for i, (label, key) in enumerate((("背景色", "bg"), ("文字色", "fg"), ("描边色", "border"))):
            btn = QPushButton()
            btn.setFixedSize(72, 26)
            btn.clicked.connect(lambda _checked=False, k=key: self._pick(k))
            self._color_btns[key] = btn
            grid.addWidget(QLabel(label), i, 0)
            grid.addWidget(btn, i, 1)
        grid.addWidget(QLabel("字号"), 3, 0)
        self._font_spin = QSpinBox()
        self._font_spin.setRange(8, 18)
        self._font_spin.valueChanged.connect(lambda _v: self._apply_preview())
        grid.addWidget(self._font_spin, 3, 1)
        grid.addWidget(QLabel("圆角"), 4, 0)
        self._radius_spin = QSpinBox()
        self._radius_spin.setRange(0, 30)
        self._radius_spin.valueChanged.connect(lambda _v: self._apply_preview())
        grid.addWidget(self._radius_spin, 4, 1)
        root.addLayout(grid)

        self._preview = QLabel("绳匠，小鱼干呢？")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setMinimumSize(260, 84)
        root.addWidget(self._preview)

        row = QHBoxLayout()
        save_btn = QPushButton("保存")
        reset_btn = QPushButton("恢复默认")
        cancel_btn = QPushButton("取消")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        reset_btn.clicked.connect(self._reset_default)
        cancel_btn.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(save_btn)
        row.addWidget(reset_btn)
        row.addWidget(cancel_btn)
        root.addLayout(row)

        self._update_color_buttons()
        self._apply_preview()

    # ---------- 内部 ----------
    @staticmethod
    def _to_int(v, default):
        try:
            return int(v)
        except Exception:
            return default

    def _update_color_buttons(self):
        for key, btn in self._color_btns.items():
            c = str(self._style.get(key, "#ffffff"))
            btn.setStyleSheet(
                "QPushButton { background-color: %s; border: 1px solid #3d477f;"
                " border-radius: 6px; }" % c)

    def _apply_preview(self):
        s = self._style
        s["font_size"] = self._font_spin.value()
        s["radius"] = self._radius_spin.value()
        self._preview.setStyleSheet(
            "QLabel { background-color: %s; color: %s; border: 2px solid %s;"
            " border-radius: %dpx; padding: 12px 16px; font-size: %dpt; }"
            % (s["bg"], s["fg"], s["border"], self._to_int(s["radius"], 16),
               self._to_int(s["font_size"], 10)))

    def _pick(self, key):
        cur = QColor(str(self._style.get(key, "#ffffff")))
        c = QColorDialog.getColor(cur, self, "选择颜色")
        if c.isValid():
            self._style[key] = c.name()
            self._update_color_buttons()
            self._apply_preview()

    # ---------- 动作 ----------
    def _save(self):
        self._style["font_size"] = self._font_spin.value()
        self._style["radius"] = self._radius_spin.value()
        style = {
            "bg": str(self._style["bg"]),
            "fg": str(self._style["fg"]),
            "border": str(self._style["border"]),
            "font_size": self._to_int(self._style["font_size"], 10),
            "radius": self._to_int(self._style["radius"], 16),
        }
        _call(self._pet, "apply_bubble_style", style)
        self.accept()

    def _reset_default(self):
        self._style = dict(_DEFAULT_BUBBLE_STYLE)
        self._font_spin.setValue(10)
        self._radius_spin.setValue(16)
        self._update_color_buttons()
        self._apply_preview()


# ---------------- f) 台词设置对话框（v2.1：独立台词自定义模块 UI） ----------------
class LinesDialog(QDialog):
    """台词自定义：台词库（增删改查/排序/批量/清空/撤销）/ 对白编排 / 失效引用。

    v2.1：内置台词也可删（真删不留正文，只记 id 防复活）；条数不限，
    单条长度上限见 pet_lines.TEXT_MAX（超出明确报错，不静默截断）；
    删除走二次确认 + 可撤销（撤销最近一次删除/清空）。"""

    def __init__(self, parent=None):
        super().__init__(_qt_parent(parent))
        self._pet = parent
        self._lib = _get(parent, "lines_lib")
        self._editing = None          # 正在编辑的台词 id（None=新建）
        self._editing_dlg = None      # 正在编辑的对白 id
        self.setWindowTitle("台词设置")
        self.setStyleSheet(DIALOG_QSS)
        self.resize(780, 620)

        root = QVBoxLayout(self)
        self._banner = QLabel("")
        self._banner.setWordWrap(True)
        root.addWidget(self._banner)
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_lines_tab(), "台词库")
        self._tabs.addTab(self._build_dialogue_tab(), "对白编排")
        self._tabs.addTab(self._build_invalid_tab(), "失效引用")
        root.addWidget(self._tabs, 1)
        row = QHBoxLayout()
        self._count = QLabel("")
        row.addWidget(self._count)
        row.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        root.addLayout(row)
        self._refresh_all()

    # ---------- 公共数据 ----------
    def _role_items(self):
        out = [("", "默认角色")]
        lib = _get(self._pet, "role_lib")
        try:
            for r in (lib.list_roles() if lib is not None else []):
                out.append((r["id"], r.get("name") or r["id"]))
        except Exception:
            pass  # 有意忽略：角色列表取不到就只给默认角色（不崩）
        return out

    def _voice_items(self):
        out = [("", "（跟随角色绑定）")]
        lib = _get(self._pet, "voice_assets")
        try:
            for a in (lib.assets() if lib is not None else []):
                out.append((a["id"], a.get("name") or a["id"]))
        except Exception:
            pass  # 有意忽略：声音素材取不到就只给"跟随绑定"
        return out

    @staticmethod
    def _fill_combo(combo, items, cur=None, dead_label=None):
        """填下拉；cur 不在候选里时（引用已失效）加一条显式占位项，避免静默清空。"""
        combo.clear()
        for val, label in items:
            combo.addItem(label, val)
        want = cur if cur is not None else ""
        if want and combo.findData(want) < 0 and dead_label:
            combo.addItem(dead_label % str(want)[:12], want)
        idx = combo.findData(want)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _selected_ids(self):
        return [it.data(Qt.ItemDataRole.UserRole) for it in self._list.selectedItems()]

    # ---------- 页签 1：台词库 ----------
    def _build_lines_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        top = QHBoxLayout()
        top.addWidget(QLabel("类别"))
        self._filter = QComboBox()
        self._filter.addItem("全部", "")
        for cat in pet_lines.LINE_CATEGORIES:
            self._filter.addItem(pet_lines.CATEGORY_LABELS.get(cat, cat), cat)
        self._filter.currentIndexChanged.connect(lambda _i: self._refresh_lines())
        top.addWidget(self._filter)
        top.addWidget(QLabel("搜索"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("输入关键词过滤台词")
        self._search.textChanged.connect(lambda _t: self._refresh_lines())
        top.addWidget(self._search, 1)
        lay.addLayout(top)

        body = QHBoxLayout()
        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._list.currentItemChanged.connect(lambda *_: self._on_pick_line())
        body.addWidget(self._list, 3)

        editor = QVBoxLayout()
        editor.addWidget(QLabel("台词文本（可换行；单条最长 %d 字，超出会明确提示）"
                                % pet_lines.TEXT_MAX))
        self._text = QPlainTextEdit()
        self._text.setPlaceholderText("在这里写台词；留空无法保存")
        editor.addWidget(self._text, 2)
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("类别"))
        self._cat = QComboBox()
        for cat in pet_lines.LINE_CATEGORIES:
            self._cat.addItem(pet_lines.CATEGORY_LABELS.get(cat, cat), cat)
        r1.addWidget(self._cat)
        editor.addLayout(r1)
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("角色"))
        self._role = QComboBox()
        r2.addWidget(self._role, 1)
        editor.addLayout(r2)
        r3 = QHBoxLayout()
        r3.addWidget(QLabel("声音"))
        self._voice = QComboBox()
        r3.addWidget(self._voice, 1)
        editor.addLayout(r3)
        # L4 修复：喂食类台词要知道喂给什么食物（否则 food_texts 永远选不中它）
        self._food_row = QWidget()
        _fr = QHBoxLayout(self._food_row)
        _fr.setContentsMargins(0, 0, 0, 0)
        _fr.addWidget(QLabel("喂食对象"))
        self._food = QComboBox()
        for _f in ("小鱼干", "蛋糕", "钻石"):
            self._food.addItem(_f, _f)
        _fr.addWidget(self._food, 1)
        editor.addWidget(self._food_row)
        self._cat.currentIndexChanged.connect(
            lambda _i: self._food_row.setVisible(self._cat.currentData() == "food"))
        self._food_row.setVisible(self._cat.currentData() == "food")
        grid = QGridLayout()
        self._btns = {}
        for i, (label, cb) in enumerate((("新建", self._new_line), ("保存", self._save_line),
                                         ("上移", lambda: self._move_line(-1)),
                                         ("下移", lambda: self._move_line(1)),
                                         ("删除选中", self._delete_selected),
                                         ("清空全部", self._clear_all),
                                         ("恢复内置", self._restore_builtins),
                                         ("撤销删除", self._undo))):
            b = QPushButton(label)
            b.clicked.connect(cb)
            grid.addWidget(b, i // 2, i % 2)
            self._btns[label] = b
        editor.addLayout(grid)
        editor.addStretch(1)
        body.addLayout(editor, 2)
        lay.addLayout(body, 1)
        return w

    def _refresh_lines(self):
        if self._lib is None:
            return
        cat = self._filter.currentData() or ""
        kw = (self._search.text() or "").strip()
        self._list.clear()
        for ln in self._lib.lines(cat or None):
            if kw and kw not in ln["text"]:
                continue
            mark = "" if ln.get("builtin") else "✎"
            it = QListWidgetItem("%s[%s]%s %s" % (
                "★" if ln.get("builtin") else " ", pet_lines.CATEGORY_LABELS.get(
                    ln["category"], ln["category"]), mark, ln["text"].replace("\n", " ")[:60]))
            it.setData(Qt.ItemDataRole.UserRole, ln["id"])
            self._list.addItem(it)

    def _on_pick_line(self):
        it = self._list.currentItem()
        if it is None or self._lib is None:
            return
        ln = self._lib.get(it.data(Qt.ItemDataRole.UserRole))
        if ln is None:
            return
        self._editing = ln["id"]
        self._text.setPlainText(ln["text"])
        idx = self._cat.findData(ln["category"])
        self._cat.setCurrentIndex(idx if idx >= 0 else 0)
        # L3 修复：失效槽位给显式占位项，避免"显示成默认/跟随绑定"→ 保存时静默清空引用
        self._fill_combo(self._role, self._role_items(), ln.get("role_slot") or "",
                         dead_label="（已失效：%s）")
        self._fill_combo(self._voice, self._voice_items(), ln.get("voice_slot") or "",
                         dead_label="（已失效：%s）")

    def _move_line(self, delta):
        """台词排序（上移/下移）：按当前列表顺序整体重排，立即落盘。"""
        if self._lib is None:
            return
        row = self._list.currentRow()
        if row < 0:
            _warn(self, "排序", "先在列表里选中一条台词")
            return
        ids = [self._list.item(i).data(Qt.ItemDataRole.UserRole)
               for i in range(self._list.count())]
        j = max(0, min(len(ids) - 1, row + int(delta)))
        if j == row:
            return
        ids[row], ids[j] = ids[j], ids[row]
        ok, err = self._lib.reorder(ids)
        if not ok:
            _warn(self, "排序失败", err or "排序失败")
            return
        self._refresh_lines()
        self._list.setCurrentRow(j)

    def _new_line(self):
        self._editing = None
        self._text.clear()
        self._fill_combo(self._role, self._role_items(), "")
        self._fill_combo(self._voice, self._voice_items(), "")
        self._list.setCurrentRow(-1)
        self._text.setFocus()

    def _save_line(self):
        if self._lib is None:
            return
        text = self._text.toPlainText().strip()
        if not text:
            _warn(self, "保存失败", "台词不能为空")
            return
        cat = self._cat.currentData() or "idle"
        role = self._role.currentData() or ""
        voice = self._voice.currentData() or ""
        food = self._food.currentData() if cat == "food" else ""
        if self._editing:
            ok, err = self._lib.save(self._editing, text=text, category=cat,
                                     role_slot=role, voice_slot=voice, food=food,
                                     clear_role=not role, clear_voice=not voice)
        else:
            ln, err = self._lib.add(text, cat, role or None, voice or None, food=food)
            ok = ln is not None
            if ok:
                self._editing = ln["id"]
        if not ok:
            _warn(self, "保存失败", err or "保存失败")
            return
        self._refresh_all()

    def _delete_selected(self):
        if self._lib is None:
            return
        ids = self._selected_ids()
        if not ids:
            _warn(self, "删除台词", "先在列表里选中要删的台词（可多选）")
            return
        if not _confirm(self, "删除台词", "删除选中的 %d 条台词吗？\n"
                        "内置台词也会被删掉（可用「恢复内置」找回）。" % len(ids)):
            return
        n, err = self._lib.delete_many(ids)
        if err:
            _warn(self, "删除失败", err)
            return
        self._editing = None
        self._text.clear()
        self._refresh_all()

    def _clear_all(self):
        if self._lib is None:
            return
        if not _confirm(self, "清空全部台词", "清空全部台词与对白吗？此操作可在本窗口内「撤销删除」找回。"):
            return
        ok, err = self._lib.clear_all()
        if not ok:
            _warn(self, "清空失败", err or "清空失败")
            return
        self._editing = None
        self._text.clear()
        self._refresh_all()

    def _restore_builtins(self):
        if self._lib is None:
            return
        n = self._lib.restore_builtins()
        _info(self, "恢复内置台词", "已补回 %d 条内置台词。" % n)
        self._refresh_all()

    def _undo(self):
        if self._lib is None:
            return
        ok, err = self._lib.undo()
        if not ok:
            _warn(self, "撤销", err or "没有可撤销的操作")
            return
        self._refresh_all()

    # ---------- 页签 2：对白编排 ----------
    def _build_dialogue_tab(self):
        w = QWidget()
        lay = QHBoxLayout(w)
        left = QVBoxLayout()
        left.addWidget(QLabel("对白（多角色按顺序朗读）"))
        self._dlist = QListWidget()
        self._dlist.currentItemChanged.connect(lambda *_: self._on_pick_dialogue())
        left.addWidget(self._dlist, 1)
        r = QHBoxLayout()
        b_new = QPushButton("新建对白")
        b_new.clicked.connect(self._new_dialogue)
        b_del = QPushButton("删除对白")
        b_del.clicked.connect(self._delete_dialogue)
        r.addWidget(b_new)
        r.addWidget(b_del)
        left.addLayout(r)
        lay.addLayout(left, 1)

        right = QVBoxLayout()
        rn = QHBoxLayout()
        rn.addWidget(QLabel("名称"))
        self._dname = QLineEdit()
        self._dname.setPlaceholderText("对白名称")
        rn.addWidget(self._dname, 1)
        b_rename = QPushButton("保存名称")
        b_rename.clicked.connect(self._rename_dialogue)
        rn.addWidget(b_rename)
        right.addLayout(rn)
        right.addWidget(QLabel("对白内容（顺序即播放顺序，各自用自己的声音）"))
        self._members = QListWidget()
        right.addWidget(self._members, 1)
        ra = QHBoxLayout()
        self._pick_line = QComboBox()
        ra.addWidget(self._pick_line, 1)
        b_add = QPushButton("添加 →")
        b_add.clicked.connect(self._add_member)
        ra.addWidget(b_add)
        right.addLayout(ra)
        rb = QHBoxLayout()
        for label, cb in (("移除", self._remove_member), ("上移", lambda: self._move_member(-1)),
                          ("下移", lambda: self._move_member(1)),
                          ("朗读整段", self._speak_dialogue)):
            b = QPushButton(label)
            b.clicked.connect(cb)
            rb.addWidget(b)
        right.addLayout(rb)
        lay.addLayout(right, 2)
        return w

    def _refresh_dialogues(self):
        if self._lib is None:
            return
        self._dlist.clear()
        for d in self._lib.dialogues():
            it = QListWidgetItem("%s（%d 条）" % (d["name"], len(d["line_ids"])))
            it.setData(Qt.ItemDataRole.UserRole, d["id"])
            self._dlist.addItem(it)
        self._pick_line.clear()
        for ln in self._lib.lines():
            self._pick_line.addItem("[%s] %s" % (
                pet_lines.CATEGORY_LABELS.get(ln["category"], ln["category"]),
                ln["text"].replace("\n", " ")[:40]), ln["id"])

    def _on_pick_dialogue(self):
        it = self._dlist.currentItem()
        if it is None or self._lib is None:
            return
        did = it.data(Qt.ItemDataRole.UserRole)
        self._editing_dlg = did
        d = self._lib.get_dialogue(did)
        if d is None:
            return
        self._dname.setText(d["name"])
        self._members.clear()
        for ln in self._lib.dialogue_lines(did):
            _it = QListWidgetItem("%s ｜ %s" % (
                pet_lines.CATEGORY_LABELS.get(ln["category"], ln["category"]), ln["text"][:50]))
            _it.setData(Qt.ItemDataRole.UserRole, ln["id"])
            self._members.addItem(_it)

    def _new_dialogue(self):
        if self._lib is None:
            return
        ids = [it.data(Qt.ItemDataRole.UserRole) for it in self._list.selectedItems()]
        if not ids:
            ids = [x["id"] for x in self._lib.lines()[:1]]
        d, err = self._lib.add_dialogue("新对白", ids)
        if d is None:
            _warn(self, "新建对白", err or "新建失败")
            return
        self._refresh_all()
        for i in range(self._dlist.count()):
            if self._dlist.item(i).data(Qt.ItemDataRole.UserRole) == d["id"]:
                self._dlist.setCurrentRow(i)
                break

    def _delete_dialogue(self):
        if self._lib is None or not self._editing_dlg:
            _warn(self, "删除对白", "先选中一段对白")
            return
        if not _confirm(self, "删除对白", "删除这段对白吗？（台词本身不受影响）"):
            return
        ok, err = self._lib.delete_dialogue(self._editing_dlg)
        if not ok:
            _warn(self, "删除失败", err or "删除失败")
            return
        self._editing_dlg = None
        self._refresh_all()

    def _rename_dialogue(self):
        if self._lib is None or not self._editing_dlg:
            _warn(self, "对白", "先选中一段对白再改名")
            return
        ok, err = self._lib.save_dialogue(self._editing_dlg, name=self._dname.text())
        if not ok:
            _warn(self, "保存失败", err or "保存失败")
            return
        self._refresh_all()

    def _member_ids(self):
        return [self._members.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self._members.count())]

    def _add_member(self):
        if self._lib is None or not self._editing_dlg:
            _warn(self, "对白", "先新建或选中一段对白")
            return
        lid = self._pick_line.currentData()
        if not lid:
            return
        ids = self._member_ids() + [lid]
        ok, err = self._lib.save_dialogue(self._editing_dlg, line_ids=ids)
        if not ok:
            _warn(self, "添加失败", err or "添加失败")
            return
        self._on_pick_dialogue()
        self._refresh_dialogues()

    def _remove_member(self):
        if self._lib is None or not self._editing_dlg:
            _warn(self, "对白", "先选中一段对白")
            return
        row = self._members.currentRow()
        if row < 0:
            _warn(self, "移除台词", "先在对白内容里选中一条台词")
            return
        ids = self._member_ids()
        ids.pop(row)
        ok, err = self._lib.save_dialogue(self._editing_dlg, line_ids=ids)
        if not ok:
            _warn(self, "移除失败", err or "移除失败")
            return
        self._on_pick_dialogue()
        self._refresh_dialogues()

    def _move_member(self, delta):
        if self._lib is None or not self._editing_dlg:
            _warn(self, "对白", "先选中一段对白")
            return
        row = self._members.currentRow()
        if row < 0:
            _warn(self, "排序", "先在对白内容里选中一条台词")
            return
        ids = self._member_ids()
        j = max(0, min(len(ids) - 1, row + int(delta)))
        if j == row:
            return
        ids[row], ids[j] = ids[j], ids[row]
        ok, _err = self._lib.save_dialogue(self._editing_dlg, line_ids=ids)
        if not ok:
            _warn(self, "移动失败", _err or "移动失败")  # M3：err 不再被吞掉
            return
        self._on_pick_dialogue()
        self._members.setCurrentRow(j)

    def _speak_dialogue(self):
        if not self._editing_dlg:
            _warn(self, "朗读对白", "先选中一段对白")
            return
        res = _call(self._pet, "speak_dialogue", self._editing_dlg)
        if res is None:
            res = _get(self._pet, "voice").speak_dialogue(self._editing_dlg) \
                if _get(self._pet, "voice") else (False, "语音服务不可用")
        if isinstance(res, tuple) and res and res[0] is False:
            _warn(self, "朗读失败", res[1] or "朗读失败")

    # ---------- 页签 3：失效引用 ----------
    def _build_invalid_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self._bad_hint = QLabel("")
        self._bad_hint.setWordWrap(True)
        lay.addWidget(self._bad_hint)
        self._bad = QTableWidget(0, 3)
        self._bad.setHorizontalHeaderLabels(["台词", "缺失", "可能原因"])
        self._bad.horizontalHeader().setStretchLastSection(True)
        self._bad.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        lay.addWidget(self._bad, 1)
        r1 = QHBoxLayout()
        b_scan = QPushButton("重新扫描")
        b_scan.clicked.connect(lambda: (self._scan(), self._refresh_invalid()))
        b_fix_role = QPushButton("修复角色…")
        b_fix_role.clicked.connect(self._fix_role)
        b_fix_voice = QPushButton("修复声音…")
        b_fix_voice.clicked.connect(self._fix_voice)
        b_clear = QPushButton("清空引用")
        b_clear.clicked.connect(self._clear_refs)
        for b in (b_scan, b_fix_role, b_fix_voice, b_clear):
            r1.addWidget(b)
        r1.addStretch(1)
        lay.addLayout(r1)
        r2 = QHBoxLayout()
        b_del = QPushButton("删除该台词")
        b_del.clicked.connect(self._delete_bad_one)
        b_del_all = QPushButton("一键删除所有失效台词")
        b_del_all.clicked.connect(self._delete_all_bad)
        r2.addStretch(1)
        r2.addWidget(b_del)
        r2.addWidget(b_del_all)
        lay.addLayout(r2)
        return w

    def _scan(self):
        # L1 修复：面板内扫描不要弹气泡（每次编辑都会重扫，否则气泡刷屏）
        res = _call(self._pet, "_scan_invalid_refs", False)
        return res if isinstance(res, list) else (_get(self._pet, "_invalid_refs") or [])

    def _refresh_invalid(self):
        items = self._scan()
        self._bad.setRowCount(0)
        for it in items:
            row = self._bad.rowCount()
            self._bad.insertRow(row)
            self._bad.setItem(row, 0, QTableWidgetItem(it.get("text_preview") or it["line_id"]))
            miss = []
            if it.get("missing_role"):
                miss.append("角色")
            if it.get("missing_voice"):
                miss.append("声音素材")
            c1 = QTableWidgetItem("、".join(miss))
            c1.setData(Qt.ItemDataRole.UserRole, it["line_id"])
            self._bad.setItem(row, 1, c1)
            self._bad.setItem(row, 2, QTableWidgetItem(it.get("reason") or ""))
        n = len(items)
        self._bad_hint.setText(
            "没有失效引用，一切正常。" if n == 0 else
            "有 %d 条台词引用的角色/声音素材不存在了。可以逐条修复、清空引用或删除；"
            "系统不会自动删、也不会静默替换。" % n)

    def _bad_selected(self, allow_behavior=False):
        """选中的失效项。行为步骤类失效（line_id 为空）只在 allow_behavior 时返回标记。"""
        row = self._bad.currentRow()
        if row < 0:
            _warn(self, "失效引用", "先在上表选中一条")
            return None
        item = self._bad.item(row, 1)
        lid = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not lid:
            _warn(self, "失效引用", "这条是**行为步骤**里的引用（读台词/读对白），"
                  "请到「行为设置…」里改这一步骤。")
            return None
        return lid

    def _fix_role(self):
        lid = self._bad_selected()
        if not lid or self._lib is None:
            return
        items = self._role_items()
        labels = _unique_labels([x[1] for x in items])
        label, ok = QInputDialog.getItem(self, "修复角色", "选择要指向的角色：", labels, 0, False)
        if not ok:
            return
        slot = items[labels.index(label) if label in labels else 0][0]
        res = self._lib.save(lid, role_slot=slot, clear_role=not slot)
        if res[0] is False:
            _warn(self, "修复失败", res[1])
        self._refresh_all()

    def _fix_voice(self):
        lid = self._bad_selected()
        if not lid or self._lib is None:
            return
        items = self._voice_items()
        labels = _unique_labels([x[1] for x in items])
        label, ok = QInputDialog.getItem(self, "修复声音", "选择要指向的声音素材：", labels, 0, False)
        if not ok:
            return
        slot = items[labels.index(label) if label in labels else 0][0]
        res = self._lib.save(lid, voice_slot=slot, clear_voice=not slot)
        if res[0] is False:
            _warn(self, "修复失败", res[1])
        self._refresh_all()

    def _clear_refs(self):
        lid = self._bad_selected()
        if not lid or self._lib is None:
            return
        res = self._lib.save(lid, clear_role=True, clear_voice=True)
        if res[0] is False:
            _warn(self, "清空失败", res[1])
        self._refresh_all()

    def _delete_bad_one(self):
        lid = self._bad_selected()
        if not lid or self._lib is None:
            return
        if not _confirm(self, "删除台词", "删除这条失效台词吗？"):
            return
        self._lib.delete(lid)
        self._refresh_all()

    def _delete_all_bad(self):
        if self._lib is None:
            return
        items = self._scan()
        if not items:
            _info(self, "失效引用", "当前没有失效台词。")
            return
        if not _confirm(self, "一键删除失效台词",
                        "删除全部 %d 条失效台词吗？删除后可用「台词库 → 撤销删除」找回。" % len(items)):
            return
        self._lib.delete_many([x["line_id"] for x in items])
        self._refresh_all()

    # ---------- 刷新 ----------
    def _refresh_all(self):
        if self._lib is None:
            self._banner.setText("台词库不可用（初始化失败）")
            return
        self._fill_combo(self._role, self._role_items(),
                         self._role.currentData() if self._role.count() else "")
        self._fill_combo(self._voice, self._voice_items(),
                         self._voice.currentData() if self._voice.count() else "")
        self._refresh_lines()
        self._refresh_dialogues()
        self._refresh_invalid()
        self._count.setText("共 %d 条台词 / %d 段对白" % (
            self._lib.count(), len(self._lib.dialogues())))
        # 无可撤销内容时置灰（此前常亮，点了才提示）
        try:
            if "撤销删除" in getattr(self, "_btns", {}):
                self._btns["撤销删除"].setEnabled(bool(self._lib.can_undo()))
        except Exception:
            pass  # 有意忽略：按钮态刷新失败不影响功能
        n = len(_get(self._pet, "_invalid_refs") or [])
        self._banner.setText("" if n == 0 else
                             "⚠ 有 %d 条台词引用失效（见「失效引用」页签）：缺角色或声音素材，"
                             "未修复前无法朗读。" % n)
        self._banner.setStyleSheet("color:#ff8080;" if n else "color:#8f97c0;")



class PhysicsDialog(QDialog):
    """P1-手感：甩抛物理参数设置（重力/反弹/地面摩擦/顶边反弹/力度增益）。"""

    def __init__(self, parent=None):
        super().__init__(_qt_parent(parent))
        self._pet = parent
        self.setWindowTitle("物理参数")
        self.setStyleSheet(DIALOG_QSS)
        self.resize(430, 330)
        cfg = (_get(parent, "cfg") or {}).get("physics") or {}
        root = QVBoxLayout(self)
        root.addWidget(QLabel("甩抛手感参数（重力 0 = 漂浮模式；非法值自动回退默认）"))
        self._spin = {}
        for label, key, lo, hi in (
                ("重力 gravity（px/s²）", "gravity", 0.0, 10000.0),
                ("反弹 restitution（0~1）", "restitution", 0.0, 1.0),
                ("地面摩擦 groundFriction", "groundFriction", 0.0, 50.0),
                ("力度增益 throwPower", "throwPower", 0.1, 10.0)):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            sp = QDoubleSpinBox()
            sp.setRange(lo, hi)
            sp.setDecimals(2)
            # norm-ok（physics 段已归一化为数值）
            sp.setValue(float(cfg.get(key, 1.0)))
            row.addWidget(sp)
            row.addStretch(1)
            root.addLayout(row)
            self._spin[key] = sp
        self._ceil = QCheckBox("顶边也反弹（ceilingBounce）")
        self._ceil.setChecked(bool(cfg.get("ceilingBounce", True)))
        root.addWidget(self._ceil)
        btns = QHBoxLayout()
        ok = QPushButton("保存")
        cancel = QPushButton("取消")
        ok.setDefault(True)
        ok.clicked.connect(self._save)
        cancel.clicked.connect(self.reject)
        btns.addStretch(1)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        root.addLayout(btns)

    def _save(self):
        data = {"gravity": self._spin["gravity"].value(),
                "restitution": self._spin["restitution"].value(),
                "groundFriction": self._spin["groundFriction"].value(),
                "throwPower": self._spin["throwPower"].value(),
                "ceilingBounce": self._ceil.isChecked()}
        _call(self._pet, "apply_physics", data)
        self.accept()


def open_physics(pet):
    """P1-手感：物理参数对话框入口（置顶+显式焦点，同其它对话框套路）。"""
    try:
        dlg = PhysicsDialog(pet)
        modal(dlg)
    except Exception as e:
        pet_log.log_error("physics dialog failed: %r" % (e,))


class VoiceDialog(QDialog):
    """v2.1 语言系统（AI 配音）：可插拔克隆后端 + 角色声音绑定 + 台词朗读 + 事件片段。

    存储分工：声音素材在「资源管理 → 声音素材」（资源库），本面板只做**绑定与合成播放**；
    台词文本在「台词设置」，本面板只**读取并朗读**。"""

    EVENTS = (("reply", "AI 回复"), ("feed", "喂食"), ("poke", "被戳"),
              ("sleep", "睡觉"), ("wake", "醒来"))

    def __init__(self, parent=None):
        super().__init__(_qt_parent(parent))
        self._pet = parent
        self._svc = _get(parent, "voice")
        cfg = _get(parent, "cfg") or {}
        self._vcfg = dict(cfg.get("voice") or {}) if isinstance(cfg, dict) else {}
        self._assets = _get(parent, "voice_assets")
        self._lines = _get(parent, "lines_lib")
        self._param_widgets = {}
        self._bind_combos = {}
        self.setWindowTitle("语音设置（AI 配音）")
        self.setStyleSheet(DIALOG_QSS)
        self.resize(700, 640)

        root = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._build_voice_tab(), "配音")
        tabs.addTab(self._build_bind_tab(), "角色绑定")
        tabs.addTab(self._build_play_tab(), "朗读台词")
        tabs.addTab(self._build_event_tab(), "事件音效")
        root.addWidget(tabs, 1)
        btns = QHBoxLayout()
        ok = QPushButton("保存")
        cancel = QPushButton("关闭")
        ok.setDefault(True)
        ok.clicked.connect(self._save)
        cancel.clicked.connect(self.reject)
        btns.addStretch(1)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        root.addLayout(btns)

    # ---------- 页 1：后端与开关 ----------
    def _build_voice_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self._en = QCheckBox("开启语音（默认关闭）")
        self._en.setChecked(bool(self._vcfg.get("enabled")))
        lay.addWidget(self._en)
        self._daily = QCheckBox("日常台词也用配音朗读（气泡同时显示；关闭则只有气泡）")
        self._daily.setChecked(bool(self._vcfg.get("speak_daily")))
        lay.addWidget(self._daily)
        r0 = QHBoxLayout()
        r0.addWidget(QLabel("读台词时播放动作"))
        self._talk = QComboBox()
        self._talk.setEditable(True)
        self._talk.addItem("（不用动作）", "")
        for name in self._action_names():
            self._talk.addItem(name, name)
        idx = self._talk.findData(str(self._vcfg.get("talk_action") or ""))
        self._talk.setCurrentIndex(idx if idx >= 0 else 0)
        r0.addWidget(self._talk, 1)
        lay.addLayout(r0)

        lay.addWidget(QLabel("声音克隆后端（本地后端需先自行启动服务；云端后端需填 Key）"))
        self._backend = QComboBox()
        self._infos = pet_voice.backend_infos()
        for info in self._infos:
            self._backend.addItem(info["label"], info["id"])
        bidx = self._backend.findData(str(self._vcfg.get("backend") or pet_voice.DEFAULT_BACKEND))
        if bidx >= 0:
            self._backend.setCurrentIndex(bidx)
        self._backend.currentIndexChanged.connect(lambda _i: self._sync_backend_ui())
        lay.addWidget(self._backend)

        form = QFormLayout()
        # v2.1 修复（S1）：每个后端的参数与密钥各自保存，切后端只换显示，不串台、不清空
        self._all_params = {}
        _raw_params = self._vcfg.get("backend_params") or {}
        for info in self._infos:
            src = _raw_params.get(info["id"]) if isinstance(_raw_params.get(info["id"]), dict) else {}
            one = dict(info.get("default_params") or {})
            one.pop("cloned", None)  # 云端克隆缓存不进 UI
            one.update({k: v for k, v in src.items() if k != "cloned"})
            self._all_params[info["id"]] = {k: str(v or "") for k, v in one.items()}
        self._all_keys = {}
        for info in self._infos:
            self._all_keys[info["id"]] = str(
                (self._vcfg.get("backend_keys") or {}).get(info["id"]) or "")
        self._key_edited = set()  # 用户手动改过 Key 的后端（没改过就不动已存密钥）
        # v2.1.1：本地后端启动配置（每个本地服务一份，切后端不串台）
        self._local_all = {}
        _raw_ls = self._vcfg.get("local_services") or {}
        for info in self._infos:
            if not info.get("needs_service"):
                continue
            src = _raw_ls.get(info["id"]) if isinstance(_raw_ls.get(info["id"]), dict) else {}
            self._local_all[info["id"]] = {
                "cmd": str(src.get("cmd") or ""),
                "cwd": str(src.get("cwd") or ""),
                "auto_start": bool(src.get("auto_start")),
                "kill_on_exit": bool(src.get("kill_on_exit", True)),
                "wait_seconds": int(src.get("wait_seconds") or 30),
            }
        for key, label in (("base_url", "服务地址"), ("api", "接口版本（v1/v2）"),
                           ("model", "模型"), ("voice", "声音名"),
                           ("prompt_text", "参考音文本（可选，填了更像）"),
                           ("ref_text", "参考音文本（可选）"),
                           ("text_lang", "朗读语言"), ("prompt_lang", "参考音语言"),
                           ("split_method", "切句方式")):
            ed = QLineEdit()
            form.addRow(label, ed)
            self._param_widgets[key] = (label, ed)
        self._key_label = QLabel("API Key")
        self._key = QLineEdit()
        self._key.setEchoMode(QLineEdit.EchoMode.Password)
        self._shown_backend = self._backend.currentData()  # 控件里当前显示的后端
        self._key.textEdited.connect(lambda _t: self._key_edited.add(self._backend.currentData()))
        form.addRow(self._key_label, self._key)
        lay.addLayout(form)
        self._hint = QLabel("")
        self._hint.setWordWrap(True)
        lay.addWidget(self._hint)
        r1 = QHBoxLayout()
        b_test = QPushButton("测试后端")
        b_test.clicked.connect(self._test_backend)
        b_assets = QPushButton("管理声音素材…（导入/试听/删除）")
        b_assets.clicked.connect(self._open_assets)
        r1.addWidget(b_test)
        r1.addWidget(b_assets)
        r1.addStretch(1)
        lay.addLayout(r1)
        # M9 修复：补回"AI 回复朗读"（旧固定音色链路）的入口——v2.0 有、v2.1 一度丢失，
        # 导致该项只能手改 config.json。没绑声音素材时 AI 回复就走这条链路。
        g_tts = QGroupBox("AI 回复朗读（没绑声音素材时用它念 AI 回复）")
        f_tts = QFormLayout(g_tts)
        self._tts_mode = QComboBox()
        for _val, _label in (("off", "关闭（只显示文字）"), ("sapi", "Windows 系统语音（离线）"),
                             ("api", "OpenAI 兼容 /audio/speech")):
            self._tts_mode.addItem(_label, _val)
        _mi = self._tts_mode.findData(str(self._vcfg.get("tts_mode") or "off"))
        self._tts_mode.setCurrentIndex(_mi if _mi >= 0 else 0)
        f_tts.addRow("合成方式", self._tts_mode)
        self._tts_voice = QLineEdit(str(self._vcfg.get("tts_voice") or ""))
        self._tts_voice.setPlaceholderText("声音名/系统语音包，如 Microsoft Huihui Desktop 或 alloy")
        f_tts.addRow("声音", self._tts_voice)
        self._tts_model = QLineEdit(str(self._vcfg.get("tts_model") or ""))
        self._tts_model.setPlaceholderText("留空用 tts-1")
        f_tts.addRow("模型", self._tts_model)
        lay.addWidget(g_tts)

        # v2.1.1：本地后端服务（启动命令/工作目录/自动启动开关/手动按钮/就绪等待）
        self._g_local = QGroupBox("本地后端服务（GPT-SoVITS / F5-TTS / CosyVoice 要自己启动）")
        f_local = QFormLayout(self._g_local)
        _row_cmd = QHBoxLayout()
        self._lcmd = QLineEdit()
        self._lcmd.setPlaceholderText("启动命令，例如 D:\\GPT-SoVITS\\go-api.bat 或 python api.py")
        _b_cmd = QPushButton("选脚本…")
        _b_cmd.clicked.connect(self._pick_launch_cmd)
        _row_cmd.addWidget(self._lcmd, 1)
        _row_cmd.addWidget(_b_cmd)
        f_local.addRow("启动命令", _row_cmd)
        _row_cwd = QHBoxLayout()
        self._lcwd = QLineEdit()
        self._lcwd.setPlaceholderText("工作目录（可选；有些脚本要求在自己的目录里跑）")
        _b_cwd = QPushButton("选目录…")
        _b_cwd.clicked.connect(self._pick_launch_cwd)
        _row_cwd.addWidget(self._lcwd, 1)
        _row_cwd.addWidget(_b_cwd)
        f_local.addRow("工作目录", _row_cwd)
        self._lwait = QSpinBox()
        self._lwait.setRange(5, 120)
        self._lwait.setSuffix(" 秒")
        self._lwait.setValue(30)
        f_local.addRow("等就绪最长", self._lwait)
        # 默认和以前一样：不自动启动，用户自己开（要用就勾上）
        self._lauto = QCheckBox("启动桌宠时自动拉起后端（默认关：和以前一样自己启动）")
        f_local.addRow("", self._lauto)
        self._lkill = QCheckBox("桌宠退出时结束它自己拉起的后端（手动开的不动）")
        self._lkill.setChecked(True)
        f_local.addRow("", self._lkill)
        _row_btn = QHBoxLayout()
        self._lstart = QPushButton("立即启动后端")
        self._lstart.clicked.connect(self._start_backend_now)
        self._lstop = QPushButton("结束后端（只关桌宠拉起的）")
        self._lstop.clicked.connect(self._stop_backend_now)
        _row_btn.addWidget(self._lstart)
        _row_btn.addWidget(self._lstop)
        _row_btn.addStretch(1)
        f_local.addRow("", _row_btn)
        self._lstatus = QLabel("")
        self._lstatus.setWordWrap(True)
        f_local.addRow("状态", self._lstatus)
        lay.addWidget(self._g_local)
        self._test_label = QLabel("")
        self._test_label.setWordWrap(True)
        lay.addWidget(self._test_label)
        lay.addStretch(1)
        self._load_backend_ui()  # 全部控件就绪后再按后端填值（含可见性/密钥/提示）
        return w

    def _action_names(self):
        names = []
        try:
            lib = _get(self._pet, "role_lib")
            rid = lib.active_id() if lib is not None else ""
            if rid:
                act = getattr(self._pet, "actions", None)
                if act is not None and hasattr(act, "action_names"):
                    names = list(act.action_names())
        except Exception:
            names = []
        return names

    def _backend_info(self):
        bid = self._backend.currentData()
        for info in self._infos:
            if info["id"] == bid:
                return info
        return self._infos[0]

    # ---------- v2.1.1：本地后端服务 ----------
    def _local_cfg(self, bid=None):
        bid = bid or self._backend.currentData()
        one = (self._local_all or {}).get(bid) or {}
        return dict(one)

    def _stash_local_ui(self, bid=None):
        """把本地后端服务控件值存回对应后端（切后端/保存前调用，防串台）。"""
        bid = bid or getattr(self, "_shown_backend", None)
        if not bid:
            return
        self._local_all[bid] = {
            "cmd": self._lcmd.text().strip(),
            "cwd": self._lcwd.text().strip(),
            "auto_start": self._lauto.isChecked(),
            "kill_on_exit": self._lkill.isChecked(),
            "wait_seconds": int(self._lwait.value()),
        }

    def _load_local_ui(self):
        bid = self._backend.currentData()
        one = self._local_cfg(bid)
        self._lcmd.setText(str(one.get("cmd") or ""))
        self._lcwd.setText(str(one.get("cwd") or ""))
        self._lauto.setChecked(bool(one.get("auto_start")))
        self._lkill.setChecked(bool(one.get("kill_on_exit", True)))
        try:
            self._lwait.setValue(int(one.get("wait_seconds") or 30))
        except (TypeError, ValueError):
            self._lwait.setValue(30)
        self._refresh_launch_status()

    def _refresh_launch_status(self):
        st = {}
        try:
            if self._svc is not None:
                st = self._svc.launch_status()
        except Exception:
            st = {}
        if st.get("running"):
            self._lstatus.setText("运行中：PID %s（%s 启动，后端 %s）\n日志：%s"
                                  % (st.get("pid"), st.get("started_at"),
                                     st.get("backend") or "-", st.get("log")))
        else:
            self._lstatus.setText("未运行（桌宠没有拉起的后端；你自己启动的服务不受影响）")

    def _pick_launch_cmd(self):
        path, _f = QFileDialog.getOpenFileName(
            self, "选择后端启动脚本", "", "启动脚本 (*.bat *.cmd *.exe *.ps1);;所有文件 (*)")
        if path:
            self._lcmd.setText(path)

    def _pick_launch_cwd(self):
        path = QFileDialog.getExistingDirectory(self, "选择工作目录")
        if path:
            self._lcwd.setText(path)

    def _start_backend_now(self):
        """立即启动本地后端。

        M-1 修复：不再在本函数里 spawn 工作线程去调 show_bubble（那会在子线程碰 Qt 控件），
        统一走 PetWindow.start_voice_backend()——它负责起进程 + 用 Qt 信号把就绪结果送回主线程。
        """
        self._stash_local_ui()
        self._save(silent=True)  # 先落配置，启动用最新命令
        res = _call(self._pet, "start_voice_backend")
        if res is None:  # 桌宠没有该方法（老版本/异常）：退回直接调服务，不起线程
            if self._svc is None:
                self._lstatus.setText("❌ 语音服务不可用")
                return
            ok, msg = self._svc.start_backend()
            self._lstatus.setText(("✅ " if ok else "❌ ") + msg)
            self._refresh_launch_status()
            return
        ok, msg = res if isinstance(res, tuple) else (False, "启动失败")
        self._lstatus.setText(("✅ " if ok else "❌ ") + msg
                              + ("（后台等就绪，稍后气泡告知）" if ok else ""))
        self._refresh_launch_status()

    def _stop_backend_now(self):
        if self._svc is None:
            return
        ok, msg = self._svc.stop_backend()
        self._lstatus.setText(("✅ " if ok else "❌ ") + msg)
        self._refresh_launch_status()

    def _stash_backend_ui(self, bid=None):
        """把控件的参数/密钥暂存回**指定后端**的槽位。

        必须显式传 bid：currentIndexChanged 触发时索引已经变了，用 currentData()
        会把旧后端的值写进新后端（这正是"切后端串台"的根因）。"""
        bid = bid or getattr(self, "_shown_backend", None)
        if not bid:
            return
        info = self._backend_info()
        defaults = info.get("default_params") or {}
        one = dict(self._all_params.get(bid) or {})
        for key, (_label, ed) in self._param_widgets.items():
            if key in defaults:
                one[key] = ed.text().strip()
        self._all_params[bid] = one
        if bid in self._key_edited:
            self._all_keys[bid] = self._key.text().strip()

    def _load_backend_ui(self):
        """把本后端的参数/密钥填进控件（含可见性）。"""
        bid = self._backend.currentData()
        info = self._backend_info()
        defaults = info.get("default_params") or {}
        one = self._all_params.get(bid) or {}
        for key, (label, ed) in self._param_widgets.items():
            show = key in defaults
            ed.setVisible(show)
            for lab in self.findChildren(QLabel, label):
                lab.setVisible(show)
            if show:
                ed.setText(str(one.get(key, defaults.get(key, "")) or ""))
        need_key = bool(info.get("needs_key"))
        self._key.setVisible(need_key)
        self._key_label.setVisible(need_key)
        self._key.setText(str(self._all_keys.get(bid) or ""))
        if hasattr(self, "_g_local"):
            self._g_local.setVisible(bool(info.get("needs_service")))  # 只有本地后端需要启动
        _hint = getattr(self, "_hint", None)
        if _hint is not None:
            _hint.setText(info.get("help_text") or "")

    def _sync_backend_ui(self):
        """切后端：先把"控件里当前显示的旧后端"的值存回旧槽位，再按新后端重填。

        本地后端服务控件（v2.1.1）同样按后端隔离。

        S1 修复：分别在两处踩过坑——(1) 此前完全不重载参数/密钥；(2) 用 currentData()
        暂存，但信号触发时索引已变 → 旧值写进新后端。故用 _shown_backend 记录。"""
        _old = getattr(self, "_shown_backend", None)
        self._stash_backend_ui(_old)
        if _old and getattr(self, "_local_all", None):
            self._stash_local_ui(_old)
        self._shown_backend = self._backend.currentData()
        self._load_backend_ui()
        if getattr(self, "_local_all", None):
            self._load_local_ui()

    def _test_backend(self):
        if self._svc is None:
            self._test_label.setText("❌ 语音服务不可用")
            return
        self._test_label.setText("测试中……")
        _app_events()
        self._save(silent=True)  # 先落配置，测试用最新参数
        ok, msg = self._svc.test_backend(self._backend.currentData())
        self._test_label.setText(("✅ " if ok else "❌ ") + msg)

    def _open_assets(self):
        dlg = ResourceManagerDialog(self._pet, initial_tab=2)
        modal(dlg)
        # 轻 12 修复：素材可能被删/改名，返回后刷新绑定下拉与朗读列表
        self._refresh_bindings()
        self._refresh_play_lists()

    # ---------- 页 2：角色绑定 ----------
    def _build_bind_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("给角色绑定声音素材（朗读台词时用它）。台词若自己指定了声音，"
                             "以台词为准。"))
        self._bind_area = QWidget()
        self._bind_form = QFormLayout(self._bind_area)
        lay.addWidget(self._bind_area, 1)
        self._refresh_bindings()
        return w

    def _role_items(self):
        out = [("", "默认角色（兜底声音）")]
        try:
            lib = _get(self._pet, "role_lib")
            for r in (lib.list_roles() if lib is not None else []):
                out.append((r["id"], r.get("name") or r["id"]))
        except Exception:
            pass  # 有意忽略：角色列表取不到就只给默认角色
        return out

    def _asset_items(self):
        out = [("", "（不绑定）")]
        try:
            for a in (self._assets.assets() if self._assets is not None else []):
                out.append((a["id"], a.get("name") or a["id"]))
        except Exception:
            pass  # 有意忽略：素材列表取不到就只给"不绑定"
        return out

    def _refresh_bindings(self):
        while self._bind_form.rowCount():
            self._bind_form.removeRow(0)
        self._bind_combos = {}
        cur = {}
        try:
            cur = self._svc.bindings() if self._svc else {}
        except Exception:
            cur = {}
        for slot, label in self._role_items():
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            cb = QComboBox()
            items = self._asset_items()
            for val, text in items:
                cb.addItem(text, val)
            _want = cur.get(slot, "")
            if _want and cb.findData(_want) < 0:
                # M7/L3：槽位已失效（素材被删）——显式占位，别让用户以为"没绑定"
                cb.addItem("（已失效：%s）" % _want[:12], _want)
            i = cb.findData(_want)
            cb.setCurrentIndex(i if i >= 0 else 0)
            cb.currentIndexChanged.connect(
                lambda _i, s=slot, c=cb: self._on_bind_changed(s, c))
            h.addWidget(cb, 1)
            b = QPushButton("试听")
            b.clicked.connect(lambda _c=False, c=cb: self._preview(c.currentData()))
            h.addWidget(b)
            self._bind_form.addRow(label, row)
            self._bind_combos[slot] = cb

    def _on_bind_changed(self, slot, combo):
        if self._svc is None:
            return
        ok, err = self._svc.bind_voice(slot, combo.currentData() or "")
        if not ok:
            _warn(self, "绑定失败", err or "绑定失败")

    def _preview(self, vs):
        if not vs:
            _warn(self, "试听", "先选一个声音素材（没有就去「管理声音素材…」导入参考音）")
            return
        if self._svc is None:
            return
        self._save(silent=True)
        ok, err = self._svc.preview_asset(vs)
        if not ok:
            _warn(self, "试听失败", err or "试听失败")

    # ---------- 页 3：朗读台词 ----------
    def _build_play_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("选一条台词或一段对白，用角色绑定的声音读出来"
                             "（首次生成会稍慢，之后命中缓存）"))
        r1 = QHBoxLayout()
        self._line_combo = QComboBox()
        self._line_combo.setMinimumWidth(320)
        r1.addWidget(self._line_combo, 1)
        b_speak = QPushButton("朗读")
        b_speak.clicked.connect(self._speak_line)
        b_regen = QPushButton("重新生成")
        b_regen.clicked.connect(self._regen_line)
        b_stop = QPushButton("停止")
        b_stop.clicked.connect(self._stop)
        for b in (b_speak, b_regen, b_stop):
            r1.addWidget(b)
        lay.addLayout(r1)
        r2 = QHBoxLayout()
        self._dlg_combo = QComboBox()
        self._dlg_combo.setMinimumWidth(320)
        r2.addWidget(self._dlg_combo, 1)
        b_dspeak = QPushButton("朗读整段对白")
        b_dspeak.clicked.connect(self._speak_dialogue)
        r2.addWidget(b_dspeak)
        lay.addLayout(r2)
        b_edit = QPushButton("编辑台词/对白…（台词设置）")
        b_edit.clicked.connect(lambda: modal(LinesDialog(self._pet)))
        lay.addWidget(b_edit)
        self._play_label = QLabel("")
        self._play_label.setWordWrap(True)
        lay.addWidget(self._play_label)
        lay.addStretch(1)
        self._refresh_play_lists()
        return w

    def _refresh_play_lists(self):
        self._line_combo.clear()
        if self._lines is not None:
            for ln in self._lines.lines():
                self._line_combo.addItem("[%s] %s" % (
                    pet_lines.CATEGORY_LABELS.get(ln["category"], ln["category"]),
                    ln["text"].replace("\n", " ")[:32]), ln["id"])
        self._dlg_combo.clear()
        if self._lines is not None:
            for d in self._lines.dialogues():
                self._dlg_combo.addItem("%s（%d 条）" % (d["name"], len(d["line_ids"])), d["id"])

    def _speak_line(self):
        if self._svc is None or self._lines is None:
            self._play_label.setText("❌ 语音/台词服务不可用")
            return
        lid = self._line_combo.currentData()
        if not lid:
            self._play_label.setText("❌ 还没有台词（去「💬 自定义台词…」新建）")
            return
        self._save(silent=True)
        ok, err = self._svc.speak_line(lid)
        self._play_label.setText(("✅ 开始朗读…" if ok else "❌ " + (err or "朗读失败")))

    def _regen_line(self):
        if self._svc is None:
            return
        lid = self._line_combo.currentData()
        if not lid:
            return
        ok, err = self._svc.regenerate(lid)
        if not ok:
            self._play_label.setText("❌ " + (err or "重新生成失败"))
            return
        self._speak_line()

    def _stop(self):
        if self._svc is not None:
            self._svc.stop()
        self._play_label.setText("已停止。")

    def _speak_dialogue(self):
        if self._svc is None:
            return
        did = self._dlg_combo.currentData()
        if not did:
            self._play_label.setText("❌ 还没有对白（去「💬 自定义台词… → 对白编排」新建）")
            return
        self._save(silent=True)
        ok, err = self._svc.speak_dialogue(did)
        self._play_label.setText(("✅ 开始按顺序朗读…" if ok else "❌ " + (err or "朗读失败")))

    # ---------- 页 4：事件音效（v2.0 能力，保留） ----------
    def _build_event_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("事件片段（自己准备的 wav/mp3；导入即用，可试听/清除）"))
        self._row_labels = {}
        for key, label in self.EVENTS:
            r = QHBoxLayout()
            r.addWidget(QLabel(label))
            st = QLabel("—")
            r.addWidget(st)
            self._row_labels[key] = st
            b1 = QPushButton("导入…")
            b1.clicked.connect(lambda _c=False, k=key: self._import(k))
            b2 = QPushButton("试听")
            b2.clicked.connect(lambda _c=False, k=key: self._test(k))
            b3 = QPushButton("清除")
            b3.clicked.connect(lambda _c=False, k=key: self._clear(k))
            for b in (b1, b2, b3):
                r.addWidget(b)
            lay.addLayout(r)
        lay.addStretch(1)
        self._refresh_rows()
        return w

    def _refresh_rows(self):
        voice = _get(self._pet, "voice")
        for key, lbl in self._row_labels.items():
            cur = voice.clip(key) if voice is not None else None
            lbl.setText("✓ 已配" if cur else "—")

    def _import(self, key):
        src, _f = QFileDialog.getOpenFileName(self, "导入语音片段", "", "音频 (*.wav *.mp3)")
        if not src:
            return
        ok, err = _get(self._pet, "voice").set_clip(key, src)
        if not ok:
            _warn(self, "语音片段", err or "导入失败")
            return
        self._refresh_rows()

    def _test(self, key):
        p = _get(self._pet, "voice").clip(key)
        if p is None:
            _warn(self, "试听", "该事件还没配片段")
            return
        if _call(self._pet, "preview_audio", p) is not True:
            _warn(self, "试听", "播放失败：音频文件可能已损坏")

    def _clear(self, key):
        ok, err = _get(self._pet, "voice").set_clip(key, None)
        if not ok:
            _warn(self, "语音片段", err or "清除失败")
            return
        self._refresh_rows()

    # ---------- 保存 ----------
    def _save(self, silent=False):
        """保存：提交**全部后端**的参数与密钥（按后端深合并），中文占位不落脏值。

        S1 修复：此前只提交当前后端 → 保存一次就清空其它后端的密钥/参数。"""
        self._stash_backend_ui(getattr(self, "_shown_backend", None)
                               or self._backend.currentData())
        if getattr(self, "_local_all", None):
            self._stash_local_ui(getattr(self, "_shown_backend", None)
                                 or self._backend.currentData())
        bid = self._backend.currentData()
        talk = self._talk.currentData() or ""
        if not talk:
            _t = self._talk.currentText().strip()
            talk = "" if _t in ("（不用动作）", "不用动作") else _t
        data = {
            "enabled": self._en.isChecked(),
            "backend": bid,
            "backend_params": {k: dict(v) for k, v in self._all_params.items()},
            "backend_keys": dict(self._all_keys),
            "local_services": {k: dict(v) for k, v in (self._local_all or {}).items()},
            "speak_daily": self._daily.isChecked(),
            "talk_action": talk,
            # 旧字段（AI 回复朗读）：v2.1 起界面提供入口，不再只做透传
            "tts_mode": self._tts_mode.currentData() if hasattr(self, "_tts_mode")
            else self._vcfg.get("tts_mode", "off"),
            "tts_model": self._tts_model.text().strip() if hasattr(self, "_tts_model")
            else self._vcfg.get("tts_model", ""),
            "tts_voice": self._tts_voice.text().strip() if hasattr(self, "_tts_voice")
            else self._vcfg.get("tts_voice", ""),
        }
        res = _call(self._pet, "apply_voice", data)
        if not silent and res is None:
            _warn(self, "保存", "保存失败（语音服务不可用）")
            return
        # 合并回本地缓存，供后续"测试/试听"用最新参数
        try:
            self._vcfg = dict(((_get(self._pet, "cfg") or {}).get("voice")) or {})
        except Exception:
            pass  # 有意忽略：缓存刷新失败不影响已保存的配置
        if not silent:
            self.accept()


def _app_events():
    """处理一次事件循环（测试按钮的"测试中…"能立刻显示出来）。"""
    try:
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
    except Exception:
        pass  # 有意忽略：无 QApplication 时跳过（不影响功能）


# ---------------- v2.1：待机设置对话框 ----------------
class IdleDialog(QDialog):
    """待机设置：双触发（满足一个就待机）/ 待机形态 / 待机动作列表（按模式挑选）/ 播放模式。

    - 触发 A：吃饱形态结束后 idle_delay_after_full 秒（默认 2s；0=形态一结束即可待机）。
    - 触发 B：无交互 idle_trigger_delay 秒（默认 8s）。任一先满足即待机。
    - 待机形态 idle_form 只做展示期覆盖，不改用户选定形态；留空 = 不切形态。
    - 待机动作是**列表**（引用行为库），可增删、启停、调权重与顺序；播放模式四种。"""

    def __init__(self, parent=None):
        super().__init__(_qt_parent(parent))
        self._pet = parent
        self._svc = _get(parent, "behaviors")
        cfg = _get(parent, "cfg") or {}
        self._idle = pet_behaviors.normalize_idle_cfg(cfg if isinstance(cfg, dict) else {})
        self.setWindowTitle("待机设置")
        self.setStyleSheet(DIALOG_QSS)
        self.resize(660, 560)

        root = QVBoxLayout(self)
        # 触发
        box1 = QGroupBox("触发条件（两个来源，满足一个就待机）")
        f1 = QFormLayout(box1)
        self._delay = QSpinBox()
        self._delay.setRange(pet_behaviors.IDLE_TRIGGER_MIN, pet_behaviors.IDLE_TRIGGER_MAX)
        self._delay.setSuffix(" 秒")
        self._delay.setValue(int(self._idle["idle_trigger_delay"]))
        f1.addRow("无交互多少秒后待机", self._delay)
        self._after_full = QSpinBox()
        self._after_full.setRange(pet_behaviors.IDLE_AFTER_FULL_MIN,
                                  pet_behaviors.IDLE_AFTER_FULL_MAX)
        self._after_full.setSuffix(" 秒")
        self._after_full.setValue(int(self._idle["idle_delay_after_full"]))
        f1.addRow("吃饱形态结束后延迟", self._after_full)
        _tip = QLabel("说明：两个条件**满足一个**就待机——①吃饱形态结束后等上格秒数（默认 2 秒）；"
                      "②无交互满上格秒数（默认 8 秒）。吃饱形态展示期间本身不会被打断。")
        _tip.setWordWrap(True)
        f1.addRow("", _tip)
        root.addWidget(box1)

        # 形态
        box2 = QGroupBox("待机形态（留空 = 保持用户选定形态，不会被待机改掉）")
        f2 = QFormLayout(box2)
        self._form = QComboBox()
        self._form.addItem("（不切形态）", "")
        for key, name in self._forms():
            self._form.addItem("%s（%s）" % (name, key), key)
        i = self._form.findData(self._idle["idle_form"])
        self._form.setCurrentIndex(i if i >= 0 else 0)
        f2.addRow("待机时展示", self._form)
        root.addWidget(box2)

        # 动作列表
        box3 = QGroupBox("待机动作列表（每次待机按模式选一条播放）")
        v3 = QVBoxLayout(box3)
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["启用", "行为", "权重", "顺序"])
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        v3.addWidget(self._table, 1)
        add_row = QHBoxLayout()
        self._pick = QComboBox()
        for b in self._behaviors():
            self._pick.addItem("%s（%s）" % (b["name"], b["id"]), b["id"])
        add_row.addWidget(self._pick, 1)
        b_add = QPushButton("添加")
        b_add.clicked.connect(self._add_action)
        add_row.addWidget(b_add)
        for label, cb in (("移除", self._remove_action), ("上移", lambda: self._move(-1)),
                          ("下移", lambda: self._move(1))):
            b = QPushButton(label)
            b.clicked.connect(cb)
            add_row.addWidget(b)
        v3.addLayout(add_row)
        self._perf_hint = QLabel("")
        self._perf_hint.setWordWrap(True)
        v3.addWidget(self._perf_hint)
        root.addWidget(box3, 1)

        # 模式
        box4 = QGroupBox("播放规则")
        f4 = QFormLayout(box4)
        self._mode = QComboBox()
        for m in pet_behaviors.IDLE_PLAY_MODES:
            self._mode.addItem(pet_behaviors.IDLE_MODE_LABELS.get(m, m), m)
        i2 = self._mode.findData(self._idle["idle_play_mode"])
        self._mode.setCurrentIndex(i2 if i2 >= 0 else 0)
        f4.addRow("播放模式", self._mode)
        self._resume = QCheckBox("被打断的动作算已消费（下次不再重播它）")
        self._resume.setChecked(bool(self._idle["idle_resume_on_interrupt"]))
        f4.addRow("", self._resume)
        root.addWidget(box4)

        btns = QHBoxLayout()
        ok = QPushButton("保存")
        cancel = QPushButton("关闭")
        ok.setDefault(True)
        ok.clicked.connect(self._save)
        cancel.clicked.connect(self.reject)
        btns.addStretch(1)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        root.addLayout(btns)
        self._refresh_table()

    # ---------- 数据 ----------
    def _forms(self):
        keys = _get(self._pet, "form_keys") or []
        names = _get(self._pet, "form_names") or {}
        out = []
        for k in keys:
            out.append((k, names.get(k, k)))
        return out

    def _behaviors(self):
        try:
            return self._svc.list() if self._svc is not None else []
        except Exception:
            return []

    def _refresh_table(self):
        acts = self._idle["idle_actions"]
        self._table.setRowCount(0)
        if len(acts) > pet_behaviors.IDLE_ACTIONS_MAX:
            # 只做性能提示（不拦用户：规格要求"不写死数量"）
            self._perf_hint.setText("提示：待机动作已有 %d 条，太多会让选动作变慢"
                                    % len(acts))
        else:
            self._perf_hint.setText("")
        names = {b["id"]: b["name"] for b in self._behaviors()}
        for a in acts:
            row = self._table.rowCount()
            self._table.insertRow(row)
            ck = QTableWidgetItem("")
            ck.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            ck.setCheckState(Qt.CheckState.Checked if a.get("enabled", True)
                             else Qt.CheckState.Unchecked)
            ck.setData(Qt.ItemDataRole.UserRole, a["id"])
            self._table.setItem(row, 0, ck)
            name = names.get(a["behavior_id"])
            self._table.setItem(row, 1, QTableWidgetItem(
                name or ("（行为已删除：%s）" % a["behavior_id"])))
            self._table.setItem(row, 2, QTableWidgetItem("%.2f" % float(a.get("weight", 1.0))))
            self._table.setItem(row, 3, QTableWidgetItem(str(a.get("order", row + 1))))

    def _selected_action(self):
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _collect(self):
        """从表格收集回配置（启用/权重/顺序），保持列表顺序。"""
        acts = []
        for row in range(self._table.rowCount()):
            ck = self._table.item(row, 0)
            name_item = self._table.item(row, 1)
            w_item = self._table.item(row, 2)
            aid = ck.data(Qt.ItemDataRole.UserRole) if ck is not None else ""
            src = None
            for a in self._idle["idle_actions"]:
                if a["id"] == aid:
                    src = a
                    break
            if src is None:
                continue
            try:
                weight = float(w_item.text()) if w_item is not None else 1.0
            except (TypeError, ValueError):
                weight = 1.0
            acts.append({"id": src["id"], "behavior_id": src["behavior_id"],
                         "enabled": ck.checkState() == Qt.CheckState.Checked if ck else True,
                         "weight": max(pet_behaviors.IDLE_WEIGHT_MIN,
                                       min(pet_behaviors.IDLE_WEIGHT_MAX, weight)),
                         "order": row + 1})
        self._idle["idle_actions"] = acts
        return acts

    # ---------- 操作 ----------
    def _add_action(self):
        bid = self._pick.currentData()
        if not bid:
            _warn(self, "添加待机动作", "行为库是空的，先去「行为设置…」建一个行为")
            return
        self._collect()
        item, err = pet_behaviors.add_idle_action(self._idle, bid)
        if item is None:
            _warn(self, "添加待机动作", err or "添加失败")
            return
        self._refresh_table()

    def _remove_action(self):
        aid = self._selected_action()
        if not aid:
            _warn(self, "移除", "先选中一条待机动作")
            return
        self._collect()
        ok, err = pet_behaviors.remove_idle_action(self._idle, aid)
        if not ok:
            _warn(self, "移除失败", err or "移除失败")
            return
        self._refresh_table()

    def _move(self, delta):
        aid = self._selected_action()
        if not aid:
            return
        self._collect()
        pet_behaviors.move_idle_action(self._idle, aid, delta)
        self._refresh_table()
        for row in range(self._table.rowCount()):
            if self._table.item(row, 0).data(Qt.ItemDataRole.UserRole) == aid:
                self._table.setCurrentCell(row, 0)
                break

    def _save(self):
        self._collect()
        data = {
            "idle_trigger_delay": int(self._delay.value()),
            "idle_delay_after_full": int(self._after_full.value()),  # v2.2：恢复参与触发
            "idle_form": self._form.currentData() or "",
            "idle_actions": self._idle["idle_actions"],
            "idle_play_mode": self._mode.currentData(),
            "idle_resume_on_interrupt": self._resume.isChecked(),
        }
        res = _call(self._pet, "apply_idle_settings", data)
        if res is None or res is False:
            _warn(self, "保存", "保存失败（配置不可用）")
            return
        self.accept()



def open_voice(pet):
    """v2.0：语音设置（AI 配音）对话框入口。"""
    try:
        dlg = VoiceDialog(pet)
        modal(dlg)
    except Exception as e:
        _dialog_failed(pet, "语音设置", e)


def open_lines(pet):
    """v2.1：台词设置对话框入口（菜单「💬 自定义台词…」）。

    历史缺陷：菜单一直在调用本函数但从未定义（AttributeError 被 Qt 槽吞掉，
    表现为"点了没反应"）——v2.1 一并修好。"""
    try:
        dlg = LinesDialog(pet)
        modal(dlg)
    except Exception as e:
        _dialog_failed(pet, "台词设置", e)


def open_resource_manager(pet, initial_tab=0):
    """资源管理对话框入口（角色 / 音效 / 声音素材）。同样修复未定义的历史缺陷。"""
    try:
        dlg = ResourceManagerDialog(pet, initial_tab)
        modal(dlg)
    except Exception as e:
        _dialog_failed(pet, "资源管理", e)


def _unique_labels(labels):
    """把可能重复的标签变成唯一（重复的追加「（2）」…）。

    L1 修复：QInputDialog.getItem 只回传文本，调用方用 labels.index(文本) 反查下标，
    而台词/对白/声音的标签是内容派生的（text[:24] 截断且 add 不去重）——重复标签会让
    用户选第 2 条却静默绑定到第 1 条；标签漂移时 .index() 还会抛 ValueError。
    """
    seen = {}
    out = []
    for s in labels:
        s = str(s)
        n = seen.get(s, 0)
        seen[s] = n + 1
        out.append(s if n == 0 else "%s（%d）" % (s, n + 1))
    return out


def _dialog_failed(pet, name, err):
    """对话框打不开时的统一兜底：既写日志，也给用户一句中文（M4：别"点了没反应"）。"""
    pet_log.log_error("%s dialog failed: %r" % (name, err))
    try:
        _warn(pet if isinstance(pet, QWidget) else None, name,
              "「%s」打不开：%s\n（详情见数据目录的 error.log）" % (name, err))
    except Exception:
        pass  # 有意忽略：连提示框都弹不出来时只能靠日志


def open_ai_settings(pet):
    """AI 设置对话框入口（菜单「🤖 AI设置…」→ pet.ai.open_ai_settings → 这里）。

    历史缺陷：本函数从未定义而菜单一直在调用（AttributeError 被 Qt 槽吞掉，
    表现为 AI 设置点了没反应）——v2.1.2 补齐，并加进 v13 的入口解析检查。"""
    try:
        dlg = AISettingsDialog(pet)
        modal(dlg)
    except Exception as e:
        _dialog_failed(pet, "AI 设置", e)


def open_bubble_style(pet):
    """气泡样式对话框入口（菜单「🎨 气泡样式…」）。同样修复未定义的历史缺陷。"""
    try:
        dlg = BubbleStyleDialog(pet)
        modal(dlg)
    except Exception as e:
        _dialog_failed(pet, "气泡样式", e)


def open_idle(pet):
    """v2.1：待机设置对话框入口（菜单也走 pet._open_idle_dialog）。"""
    try:
        dlg = IdleDialog(pet)
        modal(dlg)
    except Exception as e:
        _dialog_failed(pet, "待机设置", e)


class _VoicePickDialog(QDialog):
    """导出时勾选要随包带走的声音素材（默认一个都不带）。"""

    def __init__(self, pet, parent=None):
        super().__init__(_qt_parent(parent or pet))
        self.setWindowTitle("打包声音素材（可选）")
        self.setStyleSheet(DIALOG_QSS)
        self.resize(460, 380)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("默认不打包参考音（体积与隐私考虑）。勾选要带上的："))
        self._list = QListWidget()
        assets = []
        try:
            assets = _get(pet, "voice_assets").assets() or []
        except Exception:
            assets = []
        for a in assets:
            it = QListWidgetItem(a.get("name") or a["id"])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Unchecked)
            it.setData(Qt.ItemDataRole.UserRole, a["id"])
            self._list.addItem(it)
        lay.addWidget(self._list, 1)
        row = QHBoxLayout()
        b_all = QPushButton("全选")
        b_all.clicked.connect(lambda: self._check_all(True))
        b_none = QPushButton("全不选")
        b_none.clicked.connect(lambda: self._check_all(False))
        row.addWidget(b_all)
        row.addWidget(b_none)
        row.addStretch(1)
        ok = QPushButton("确定")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        cancel = QPushButton("取消导出")
        cancel.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(cancel)
        lay.addLayout(row)

    def _check_all(self, on):
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(
                Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def picked(self):
        return [self._list.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self._list.count())
                if self._list.item(i).checkState() == Qt.CheckState.Checked]


def pick_voice_assets(pet):
    """导出前勾选声音素材。返回 id 列表（可为空=不带）；用户取消返回 None。"""
    dlg = _VoicePickDialog(pet)
    if modal(dlg) != QDialog.DialogCode.Accepted:
        return None
    return dlg.picked()


def ask_amount(pet, title, label, cur):
    """数值输入对话框（预算 / 余额预警共用）：置顶 + 显式焦点，规避前台锁。"""
    dlg = QInputDialog(pet)
    dlg.setWindowTitle(title)
    dlg.setLabelText(label)
    dlg.setInputMode(QInputDialog.InputMode.DoubleInput)
    dlg.setDoubleRange(0.0, 99999.0)
    dlg.setDoubleDecimals(2)
    dlg.setDoubleValue(cur)
    dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    dlg.setFocus()
    if dlg.exec() == QDialog.DialogCode.Accepted:
        return round(max(0.0, dlg.doubleValue()), 2)
    return None


def set_frame_max(pet, save_cfg):
    """P3-5+：帧动画帧数上限（读侧与导入管线共用，改完立即生效）。"""
    cur = int(pet.cfg.get("role_frame_max", 24) or 24)
    dlg = QInputDialog(pet)
    dlg.setWindowTitle("帧数上限")
    dlg.setLabelText("帧动画角色最多多少帧？（2~60，对导入与加载立即生效）")
    dlg.setInputMode(QInputDialog.InputMode.IntInput)
    dlg.setIntRange(2, 60)
    dlg.setIntValue(cur)
    dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    dlg.setFocus()
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return
    val = dlg.intValue()
    pet.cfg["role_frame_max"] = val
    save_cfg(pet.cfg)
    pet_resources.FRAME_MAX = val
    # 已载入角色立即按新上限重建（调小立即截断生效；调大下次导入即用）
    try:
        pet.role_lib._load()
        pet.apply_role(pet.cfg.get("role", ""))
    except Exception:
        pass  # 有意忽略：重建失败下次启动自愈，不影响上限已落盘
    pet.show_bubble("帧上限改为 %d 帧啦~" % val)
