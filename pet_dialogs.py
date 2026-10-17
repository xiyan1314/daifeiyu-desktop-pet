# -*- coding: utf-8 -*-
"""
大肥鱼桌宠 —— 全部 Qt 对话框 / 面板（v1.3.0 新增）。

职责：参考 dsh-whale-widget 的「角色管理 / 音效片段管理 / 音效组 / 记账账本」
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
- class SoundPanel(QWidget)：音效片段列表（试听 / 导入 / 重命名 / 删除）+
  自定义音效组 5 行槽位（默认 / 静音 / 片段）。
- class ResourceManagerDialog(QDialog)：QTabWidget 四页签（角色 / 音效 / 声音素材 / 动作），
  内嵌 RolePanel / SoundPanel / VoiceAssetPanel / ActionPanel；initial_tab=0/1/2/3。
- class ActionPanel(QWidget)：v2.12.0（F1）「动作」页签——**纯视图**（角色 → 形态 → 动作，
  只读 + 删除 + 定位到所属角色），数据只从 roles.json 读，不新建库、不搬数据。
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
- class PluginManagerDialog(QDialog) + open_plugins(pet)：v2.5.1 PetHub 插件管理——**只读**
  列表（id / 名称 / 版本 / 类型 / 状态 / 来源）+ 安装（选本地 zip）/ 卸载 / 启用禁用 / 刷新。
  校验与落地都不在本文件：包校验在 pet_plugin（Phase 0），安装/卸载/启用禁用在
  pet_plugin_host（Phase 1）；本文件只做界面与确认文案。
- 入口函数：open_voice / open_lines / open_resource_manager / open_idle / open_physics / open_plugins
  （open_lines 与 open_resource_manager 是 v2.1 补的历史缺陷：菜单一直在调用但从未定义）。
- v2.5.0（B）尺寸与可滚动性三件套（**新增对话框必须照用**，否则 tests/test_dialog_fit_v250.py 红）：
  clamp_dialog(dlg, W, H) —— 取代写死的 self.resize(W, H)：尺寸钳进屏幕可用区域
  （上限 = 可用区域 × DIALOG_MAX_RATIO，另给下限保护，全部按逻辑像素）；
  scroll_content(dlg) —— 内容区进 QScrollArea，返回内容布局；
  stick_buttons(dlg, row) —— 按钮行钉在滚动区**之外**（确定/取消永远不会被滚走）；
  class _FitDialog(QDialog) —— 15 个对话框的公共基类，showEvent 里按所在屏幕再钳一次；
  v2.12.0（E3）起它同时是**对话框键盘路径**的唯一落点（Enter/Space 触发主按钮、Esc 关窗）。
  背景：用户报"有些窗口内容多、窗口大、看不到底，而且缩小不了"——实测根因是尺寸写死
  加上全文件没有一个滚动容器（详见 _dev/dialog_size_report.md）。

与主程序的耦合方式（全部防御性 getattr，缺省不崩）：
- pet.cfg（配置 dict）、pet.role_lib、pet.audio_lib、pet.book（可能 None）
- pet.apply_role —— 立即切换角色（主线实现；入参 role_id）
- pet.preview_audio —— 试听（主线实现：pet_audio.preview_file；入参 path|fid，
  wav 用 winsound；mp3 用 QMediaPlayer；失败弹提示）
- pet.apply_sound_group —— 保存音效组后同步进 pet_audio（主线实现；入参 group）
- pet.apply_bubble_style —— 应用气泡样式（主线实现；入参 style）
- pet.save_lines —— **兼容入口**（v2.0 语义：整体替换某类别文本；入参 pool, lines；
  v2.1 起数据落在台词库 lines.json，对话框直接用 pet.lines_lib）
- pet.lines_lib / pet.voice / pet.voice_assets / pet.behaviors：v2.1 服务对象
- pet.apply_voice / pet.apply_idle_settings —— v2.1 设置回调（入参 data，均返回 True/False）
- pet.plugin_host（v2.5.1 插件宿主）：插件管理对话框用；缺省时对话框自建一个，都拿不到
  就只给一句人话（不抛）——**本文件不 import 桌宠.py**，兜底只能取已加载的主模块
- pet.on_ledger_changed —— 刷新挂件今日已用（主线实现）
- pet.show_bubble —— 气泡（入参 text）

⚠️ 上面这些回调名**故意不带左括号**（v2.5.0 第 3 轮 L4）：两条护栏（_verify_v13 的
"ui entry points resolve" 与 _check_static 的 A 入口检查）都是**纯文本正则**扫
"pet 点名字 左括号"的形状，且只剥 # 注释、**不剥 docstring** —— 在文档里写完整调用形状，
等于让「文档里提到的名字」也被当调用解析：方法一改名，护栏就假红（名字其实还在）。
真调用（本文件下面 set_frame_max 里那两处）当然照写，它们本来就该被扫。

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
import sys
import tempfile
import threading
import time
import weakref

import pet_log

from PySide6.QtCore import QEventLoop, QTime, QTimer, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QColor, QImage, QImageReader, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QAbstractScrollArea,
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
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
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTimeEdit,
    QTreeWidget,
    QTreeWidgetItem,
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
import pet_config  # v2.8.0 · Phase 3：plugin_index_url 的键名/默认值/校验（B 的单一来源）
import pet_plugin  # v2.6.0：包判据 / 版本比较（市场页按同款四段整数比版本，不自己写一套）
import pet_plugin_host  # v2.5.1：PetHub 插件宿主（安装/卸载/启用禁用/清单/回滚；Qt-free）
import pet_plugin_index  # v2.6.0：索引读取与下载（注入式取数；Qt-free）
from pet_widgets import BUBBLE_STYLE as _BUBBLE_STYLE  # v2.1.2：气泡默认样式单一来源
# v2.4.3（兼容审查 M1）：对话框 QSS 的 font-family 也取同一条回退链——此前这里是单族
# "Microsoft YaHei"，而它被 24 处 setStyleSheet 用在**中文文本量最大**的对话框上。
# Qt 的 QSS 支持**逗号回退列表**（实测：QDialog.font().families() 拿到的就是整条链，
# 且与旧单族的度量逐项相等），所以候选不再两处各写一份，改由单一来源拼出来。
from pet_widgets import UI_FONT_FAMILIES as _UI_FONT_FAMILIES
# （pet_widgets 只依赖 pet_screen + Qt，不反向依赖本模块，无循环）


def _qss_font_family(families):
    """族名序列 → QSS 的 font-family 值（逗号分隔的回退列表；含空格的族名要带引号）。"""
    out = []
    for fam in families:
        fam = str(fam).strip()
        if not fam:
            continue
        out.append('"%s"' % fam if (" " in fam or "," in fam) else fam)
    return ", ".join(out)


DIALOG_FONT_FAMILY = _qss_font_family(_UI_FONT_FAMILIES)
# 用占位符替换，不用 % / .format()：QSS 正文全是 {} 与 #rrggbb，格式化语法会互相咬
DIALOG_QSS_FONT_TOKEN = "__UI_FONT_FAMILIES__"

# ---------------- 主题 ----------------
DIALOG_QSS = ("""
QDialog {
    background-color: #1e2234;
    color: #e8ecff;
    font-family: __UI_FONT_FAMILIES__;
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
/* v2.5.0（B）：内容区滚动容器。滚动区本身不画底/框，让 QDialog 的深色底直接透上来；
   第二个选择器只命中"滚动视口里那一层内容壳"（A > B > C 是直接子级），不波及孙控件。 */
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
""").replace(DIALOG_QSS_FONT_TOKEN, DIALOG_FONT_FAMILY)

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

# ---------------- v2.8.0 第 6 轮：本轮的时长/曲线与文案令牌（单一来源，不许散落魔法数字） ----------------
# 口径（任务书「动效时长进令牌」）：本轮出现的任何"时长/间隔"都先在这里集中定义，第 7 轮
# 再连同别的动效一起抽成 pet_motion.py。**这里只放本轮真要用的**，不做预留（预留常数
# 会被 _check_static 的"死常量"规则抓，也会变成没人读的摆设）。
TOAST_FALLBACK_LOG_GAP = 60.0
"""_toast 兜底日志的限流窗口（秒）：同一句回执在这个窗口内只落一条 error.log。

为什么是 60 秒：与 pet_log.log_throttled 的默认 gap 同量级（那里也是 60），用户连点
「保存」时日志不会被同一句话刷满；而 60 秒足够让人在事后复盘时看到"这条回执没送到"。
"""
# P3-6 文案对照表（同一动作同一套措辞 + 一句"下一步做什么"的 tooltip）：
#   · 「新建…」= 清空表单进入新建态，**不落盘**，落盘要靠「保存」；
#   · 「添加…」= 往当前（暂存的）列表里加一项，同样要靠「保存」才写进库。
# 两个词各管一类动作，不再混用（审计 P3-6：此前「新建」/「添加」混用且不说明要先保存）。
BTN_NEW_TIP = "清空表单进入新建态（先不落盘）；填好后点「保存」才会写进库里。"
BTN_ADD_TIP = "加进下面的列表（先不落盘）；点「保存」才会写进库里。"
# v2.11.0（B5）：上面那句通用措辞说「点『保存』才会写进库里」，可**导入向导里没有「保存」**
# （它的落点是「导入」）——tooltip 指着一个不存在的按钮，比没有 tooltip 更坏。决定成败的
# 信息是"加完还要点哪个按钮才真的落库"，所以这里按窗口给**它自己那句**。
BTN_ADD_TIP_IMPORT = "加进下面的形态列表（先不落盘）；点「导入」才会处理素材并写成角色。"


def _btn_tip(btn, label):
    """按 P3-6 的文案对照表给按钮贴 tooltip（对照表只在这里实现一次）。

    「新建…」= 清空表单进入新建态；「添加…」「＋…」= 往当前列表加一项。两类动作都在
    本窗口内暂存，要靠「保存」才落盘——这句话必须出现在按钮上，否则用户点完不知道
    还要再点一次（审计 P3-6 的原话：混用且不说明"要先保存"）。返回按钮本身，便于链式写。
    """
    text = str(label or "")
    if text.startswith("新建"):
        btn.setToolTip(BTN_NEW_TIP)
    elif text.startswith("添加") or text.startswith("＋"):
        btn.setToolTip(BTN_ADD_TIP)
    return btn


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
    """防御性调用 pet 方法；缺失或抛异常返回 None（返回值契约不变）。

    v2.4（静默 except 审计 A5）：这里此前是裸 pass——而它的调用方全是**用户点了按钮**
    的回调（apply_ai_settings / apply_bubble_style / apply_voice / apply_role /
    apply_idle_settings / apply_physics / apply_sound_group / clear_long_term_memory…）。
    回调抛异常时对话框照常 accept()，界面显示"保存成功"，实际没生效，error.log 里也
    没有任何线索（23 处调用点共用同一条静默路径）。现在失败先记一条日志，再按原契约
    返回 None。**只记方法名与异常，不记 args**——apply_voice / set_api_key 的参数里
    可能带后端密钥，日志宁少勿多。
    """
    try:
        fn = getattr(pet, name, None)
        if callable(fn):
            return fn(*args)
    except Exception as e:
        try:
            import traceback
            pet_log.log_error("dialog callback %s failed: %r\n%s"
                              % (name, e, traceback.format_exc()))
        except Exception:
            pass  # 有意忽略：日志自身失败无处可记
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


# ---------------- v2.8.0 第 6 轮（P2-5）：文本 / 单选输入框 —— 一律手工建框 + modal() ----------------
# 为什么不用 QInputDialog.getText/getItem 这类**静态**方法（审计 P2-5）：静态方法自己弹一个
# 自己的 exec，**不进 modal()**，也就拿不到 WindowStaysOnTopHint + activateWindow；桌宠主窗是
# WindowDoesNotAcceptFocus，Windows 前台锁下这类框可能起不来（审计列的是"一致性修复"，未实测）。
# 相同文件里的 SoundPanel._rename / AmountNoteDialog 早就是手工建框 + modal() 的写法，这里把它
# 抽成两个函数，5 处调用点共用一条路径（口径只有一份）。
# v2.9.0 第 7 轮（A10）：上一轮「按裁决保留」的那一处例外已并入这里 —— 帧动作的「动作名」框
#   现在也走 _ask_text，pet_dialogs.py 里静态 QInputDialog.getText / getItem **归零**。
#   既有用例的驱动方式同步改成 monkeypatch `_ask_text`（**加强式**：从「钉住必须用静态方法」
#   这个实现细节，改成驱动真正的生产路径；断言一条没减）。
def _ask_text(parent, title, label, default=""):
    """文本输入框 → (文本, 是否点了确定)。取消时文本是空串。"""
    dlg = QInputDialog(_qt_parent(parent))
    dlg.setWindowTitle(title)
    dlg.setLabelText(label)
    dlg.setTextValue(str(default or ""))
    dlg.setStyleSheet(DIALOG_QSS)
    ok = modal(dlg) == QDialog.DialogCode.Accepted
    return (dlg.textValue() if ok else ""), ok


def _ask_item(parent, title, label, items, current=0):
    """单选下拉框 → (选中文本, 是否点了确定)。items 为空时直接返回 ("", False)，不弹空框。"""
    items = [str(x) for x in (items or [])]
    if not items:
        return "", False
    idx = max(0, min(int(current or 0), len(items) - 1))
    dlg = QInputDialog(_qt_parent(parent))
    dlg.setWindowTitle(title)
    dlg.setLabelText(label)
    dlg.setComboBoxEditable(False)
    dlg.setComboBoxItems(items)
    dlg.setTextValue(items[idx])
    dlg.setStyleSheet(DIALOG_QSS)
    ok = modal(dlg) == QDialog.DialogCode.Accepted
    return (dlg.textValue() if ok else ""), ok


def _ask_name_clash(parent, name, other, allow_overwrite=True):
    """R3（v2.10.0）：行为重名时的**显式选择** —— 覆盖 / 两条都留 / 换个名字 / 取消。

    返回 "overwrite" / "keep" / "rename" / ""（取消 / 关掉框）。**不许静默**：这个框存在
    的意义就是"两次 add 同名时，用户至少知道发生了什么、而且是他选的"。
    `other` = 撞上的那条行为：把"撞的是哪一条"写进正文（只说"重名了"，用户还得自己去
    列表里找是哪条）。`allow_overwrite=False` 用于"改自己名字"那条路：那里的"覆盖"会把
    **别人的**条目换成这份内容 = 数据丢失，不是用户想要的，所以那一支干脆不提供。
    """
    _steps = (other or {}).get("steps") if isinstance(other, dict) else None
    box = _box(parent, QMessageBox.Icon.Question, "行为重名",
               "已经有一条叫「%s」的行为了（id %s，%d 个步骤）。\n这一步要怎么办？"
               % (name, str((other or {}).get("id") or "?"), len(_steps or [])))
    b_ov = (box.addButton("覆盖它（用现在这份内容）", QMessageBox.ButtonRole.DestructiveRole)
            if allow_overwrite else None)
    b_keep = box.addButton("两条都留（同名并存）", QMessageBox.ButtonRole.AcceptRole)
    b_ren = box.addButton("换个名字", QMessageBox.ButtonRole.ActionRole)
    box.addButton("取消（先不写）", QMessageBox.ButtonRole.RejectRole)
    modal(box)
    clicked = box.clickedButton()
    if b_ov is not None and clicked is b_ov:
        return "overwrite"
    if clicked is b_keep:
        return "keep"
    if clicked is b_ren:
        return "rename"
    return ""


# ---------------- v2.7.0 第 5 轮：反馈口径的公共出口 ----------------
# 为什么把反馈收进这里（口径见 _dev/audit_feedback_v270.md §1）：
#   · 面板内轻操作（新建/保存/删除/导出/重命名/导入成功）→ 宠物气泡：5 秒自动隐藏、
#     不打断连续操作；z 序已实测（_dev/probe_bubble_z_order_v270.py）：modal exec 期间
#     气泡仍压在上面，所以面板内也能用气泡。
#   · 失败 / 需要用户决策 → _warn / _info / _confirm（模态）。
# 全部调用点都走这两个函数：以后若要换成"内联标签"只需改这一处。
def _toast(pet, text, status=None, hold_ms=None):
    """成功回执：宠物气泡。**尽力而为**——返回 False 只表示"气泡这条路明确没通"
    （没有 pet / 没有 show_bubble / 文本为空 / show_bubble 抛异常 / **回调如实回报没显示**）。

    v2.11.0（三审 #6）：多了 `hold_ms` —— **透传给 show_bubble**（0/负数 = 常驻，
    None = 令牌默认 5s）。备份成功那条回执含 zip 全路径，值得读完；旧版只在注释里写了
    "hold_ms=0 由 show_bubble 透传"，实际调的是 `fn(str(text))`，参数根本没传下去
    （实测 5 秒就没了）。`hold_ms is None` 时**一个多余实参都不传**——用例里那些只收
    text 的老替身照旧可用。

    v2.7.0 第 5 轮（F5：文档承诺与实现不符）：改前这里写的是"返回是否**真的发出**"，
    而那时的 桌宠.show_bubble 在退出守卫下会**静默早退**（`_closing` 分支直接 return，
    实测 _toast=True 而气泡可见=False）——回调不抛异常，返回值就是 True。

    v2.8.0 第 6 轮（A3：行为层收口）：生产端现在**如实回报**——桌宠.show_bubble 在
    `_closing` 早退分支返回 False、真显示出来才返回 True。于是这里的口径变成：
      · 回调返回 None（老式替身 / 只记录的 lambda）→ 按"尽力而为"放行（True）；
      · 回调**明确返回 False** → 这次回执没送到，返回 False，并走**兜底**：
        status 可写就写进对话框自己的状态行（用户仍能在窗口里看到这句话），
        否则写一条限流日志（TOAST_FALLBACK_LOG_GAP 秒内同一句只落一条）。
    调用方仍不得把返回值当"用户看见了"：True 只说明气泡出口没被拒绝。
    """
    if not text:
        return False
    fn = _get(pet, "show_bubble")
    if not callable(fn):
        return False
    try:
        if hold_ms is None:
            res = fn(str(text))
        else:
            res = fn(str(text), hold_ms=hold_ms)
    except Exception as e:
        pet_log.log_error("show_bubble failed: %r" % (e,))
        _toast_fallback(text, status)
        return False
    if res is False:
        _toast_fallback(text, status)
        return False
    return True


def _toast_fallback(text, status=None):
    """气泡没能显示时的兜底（A3）：先写窗口内状态行，没有状态行就写一条限流日志。

    为什么兜底不能是弹窗：走到这条路径说明宠物窗口正在退出/隐藏，此刻再弹模态框既会抢
    焦点、又可能撞上正在销毁的对象；而"点了保存却什么都没发生"是审计点名的最差体验
    （_dev/audit_feedback_v270.md §1 #5/#6：日志不能当用户反馈，但**总比什么都没有强**）。
    状态行是同一句话的第二个出口：调用方传了 status（一般是对话框自己的提示行）时优先用它。
    """
    if status is not None:
        try:
            status.setText(str(text))
            return True
        except Exception as e:
            pet_log.log_error("toast status fallback failed: %r" % (e,))
    pet_log.log_throttled("toast:" + str(text)[:60],
                          "气泡回执没能显示（宠物窗口正在退出？）：%s" % (text,),
                          gap=TOAST_FALLBACK_LOG_GAP)
    return False


def _apply_result(res):
    """主窗「应用/保存」回调的返回值 → (ok, msg)。契约见 _apply_call。

    v2.7.0 第 5 轮（F2 修复）：**非空字符串 = 失败**（那个串就是原因）。
    为什么必须补：本轮把 write_config / save_config 的失败口径定成"**返回错误串**"
    （pet_config.py 的 `return err`、桌宠.save_config 原样上交），同一仓库里这种形态已经落地；
    改前这里只认 False 与二元组，裸串一路落到最后一行 `return True, ""` ——
    实测 `_apply_call(_P(), "apply_physics", {}, strict=True)` = (True, "", True)：**窗口会关**，
    用户看到的又是"保存成功"假象。空串仍按成功处理（老回调 `return ""` 的写法继续放行）。
    """
    if isinstance(res, (tuple, list)):
        if not res:
            return False, ""
        return bool(res[0]), ("" if len(res) < 2 or not res[1] else str(res[1]))
    if res is False:
        return False, ""
    if isinstance(res, str) and res.strip():
        return False, res
    return True, ""


def _apply_call(pet, name, *args, **kw):
    """调用主窗的「应用/保存」回调 → (ok, msg, explicit)。

    strict=True（与代理 B 有接口约定的三个回调 apply_ai_settings / apply_bubble_style /
    apply_physics）：**必须**拿到结果——(ok, msg) 二元组或 True 才算成功；返回 None /
    False / 方法缺失一律算失败（B：这三个回调永远返回二元组，None 说明这次调用没拿到结果，
    按 B 的明确要求当失败处理，不许当成"老契约的成功"）。
    回调返回值的完整口径（v2.7.0 第 5 轮 F2 起，_apply_result 是唯一实现处）：
      · `(ok, msg)` 二元组 → 按 ok；msg 非空时原样回给用户；
      · `True` → 成功；`False` → 失败（无原因）；
      · `None` → strict 记失败 / 非 strict（老回调）记成功；
      · **非空字符串 → 失败，串就是原因**（pet_config.write_config / 桌宠.save_config 的
        失败口径；空串按成功，兼容老回调 `return ""`）；
      · 其它（数字、对象…）→ 沿用"没明说失败就是成功"，不猜。
    strict=False（老式回调 apply_role / apply_sound_group：成功不返回东西，全仓无返回值约定）：
    None 视为成功，行为与 _call 的 None 一致。
    explicit=False 表示失败原因不是回调给的（回调抛异常或没返回值）：细节进 error.log，
    调用方只做**非模态**提示——保存回调抛异常时绝不能弹模态框（既有用例
    test_silent_logging_v24 就是在没有任何记录器的情况下直接调 AISettingsDialog._save 的）。
    """
    strict = bool(kw.pop("strict", False))
    fn = _get(pet, name)
    if not callable(fn):
        return (False, "", False) if strict else (True, "", False)
    try:
        res = fn(*args)
    except Exception as e:
        pet_log.log_error("dialog callback %s failed: %r" % (name, e))
        return False, "", False
    if res is None:
        return (False, "", False) if strict else (True, "", False)
    ok, msg = _apply_result(res)
    return ok, msg, True


def _save_failed(dlg, title, msg, explicit):
    """保存失败：**不关闭窗口** + 原因对用户可见。

    回调自己给了原因（explicit=True）→ 额外弹一次 _warn（用户当场知道为什么没保存成功）；
    原因来自异常（explicit=False）→ 只写进窗口内的状态行（非模态，不阻塞也不打断）。
    """
    text = msg or "保存失败（详情见数据目录的 error.log）"
    hint = getattr(dlg, "_save_hint", None)
    if hint is not None:
        hint.setText("⚠ " + text)
    # 没有"窗口内状态行"可写的窗口（角色面板/音效面板）一律退回模态警告——
    # 失败绝不允许重新变成静默（explicit=False 时上面那行写不进去任何东西）。
    if explicit or hint is None:
        _warn(dlg, title, text)


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


# ---------------- v2.5.0（B）：对话框尺寸钳制 + 内容区可滚动 ----------------
# 用户报的现象：有些窗口内容多、窗口大、**看不到底**，而且**缩小不了**——底部内容
# （说明文字、列表末尾，往往是确定/取消按钮）够不到。
#
# 体检实测（_dev/dialog_size_report.md）根因两条，都跟 DPI 无关，按**逻辑像素**算就对不上：
#   1) 尺寸写死：self.resize(700, 640) 这类调用把"设计尺寸"当成"实际尺寸"。VoiceDialog
#      在 100% 缩放下就长到 903 逻辑像素（800x800 逻辑屏都装不下）。
#   2) 内容区没有滚动容器（改动前全文件 QScrollArea 出现 **0** 次）：窗口被挤小之后 Qt
#      把超出的部分**裁掉**而不是给滚动条，底部内容永久够不到；而 minimumSizeHint 又被
#      布局撑大（VoiceDialog 903、RoleImportDialog 740），于是"也缩小不了"。
#
# 修法是一套，不再逐个窗口各写一份：
#   · 内容区进 QScrollArea（scroll_content）——内容再多也能滚到底；
#   · 按钮行留在滚动区**之外**（stick_buttons）——确定/取消永远不会被滚走；
#   · 尺寸钳进屏幕可用区域（clamp_dialog）——上限 = 可用区域 × 85%，另外给下限保护；
#   · 全部按**逻辑像素**：Qt 的几何本来就是逻辑像素（物理像素 = 逻辑 × devicePixelRatio），
#     所以 125% / 150% 缩放下不需要任何额外换算，也不会写出"按 1080p 物理像素写死"的值。

DIALOG_MAX_RATIO = 0.85   # 窗口最大尺寸 = 所在屏幕可用区域 × 该比例（给边框/任务栏留余量）
DIALOG_MIN_W = 320        # 下限保护：屏幕再小也别把窗口压成一条缝（逻辑像素）
DIALOG_MIN_H = 240


def dialog_available_geometry(widget=None):
    """widget **所在屏幕**的可用区域（QRect，逻辑像素，已扣任务栏/停靠区）。

    v2.5.0 B：单独抽一层，是为了让验收用例能注入"小屏"——真实屏幕尺寸在测试里
    改不了，而"窗口在 1024x600 的屏上装不下"正是用户报的那个 bug。任何异常返回 None。
    """
    try:
        screen = widget.screen() if widget is not None else None
        if screen is None:
            app = QApplication.instance()
            screen = app.primaryScreen() if app is not None else None
        if screen is None:
            return None
        return screen.availableGeometry()
    except Exception:
        return None


def dialog_size_limits(widget=None):
    """返回 (min_w, min_h, max_w, max_h)：对话框允许的尺寸区间（逻辑像素）。

    上限 = 可用区域 × DIALOG_MAX_RATIO。取不到屏幕（无 QApplication / 无屏）时退化为
    "只留下限、不设上限"——对话框构造期抛异常等于这个功能打不开，宁可少钳一次也不能崩。
    """
    min_w, min_h = DIALOG_MIN_W, DIALOG_MIN_H
    avail = dialog_available_geometry(widget)
    if avail is None:
        return min_w, min_h, 16777215, 16777215   # QWIDGETSIZE_MAX：拿不到屏就不设上限
    max_w = max(min_w, int(avail.width() * DIALOG_MAX_RATIO))
    max_h = max(min_h, int(avail.height() * DIALOG_MAX_RATIO))
    return min(min_w, max_w), min(min_h, max_h), max_w, max_h


def clamp_dialog(dlg, want_w=None, want_h=None):
    """把对话框尺寸钳进屏幕可用区域（**取代写死的 resize**），返回最终 (w, h)。

    - want_* 只是"内容希望的尺寸"（缺省取**当前尺寸**，取不到才退回 sizeHint()）；
      超出可用区域就缩回来；
    - minimumSize 给下限保护，但**不会把本来就小的框撑大**（下限取
      min(DIALOG_MIN_*, want_*)，所以 286x113 的金额框仍是 286x113）；
    - maximumSize 保证窗口**永远不可能**大过可用区域的 85%——这就是"看不到底"的根治；
    - 重复调用安全：显示前会按当前屏幕重钳一次（多屏/改缩放后仍然成立）。
    """
    min_w, min_h, max_w, max_h = dialog_size_limits(dlg)
    hint = dlg.sizeHint()
    # 缺省用**当前尺寸**而不是 sizeHint()：内容区套了 QScrollArea 之后，滚动区自己的
    # sizeHint() 是 Qt 写死的默认值（实测 432x288），**不再等于内容想要的大小**——
    # 拿它当"期望尺寸"会把设计好的 600x540 直接缩成 454x340（实测踩过）。
    # 设计尺寸由每个对话框在 __init__ 里显式传给本函数。
    if want_w is None:
        want_w = dlg.width()
    if want_h is None:
        want_h = dlg.height()
    want_w = int(want_w) if int(want_w) > 0 else max(int(hint.width()), DIALOG_MIN_W)
    want_h = int(want_h) if int(want_h) > 0 else max(int(hint.height()), DIALOG_MIN_H)
    min_w = max(1, min(DIALOG_MIN_W, want_w, max_w))
    min_h = max(1, min(DIALOG_MIN_H, want_h, max_h))
    dlg.setMinimumSize(min_w, min_h)
    dlg.setMaximumSize(max_w, max_h)
    dlg.resize(max(min_w, min(want_w, max_w)), max(min_h, min(want_h, max_h)))
    return dlg.width(), dlg.height()


def scroll_content(dlg):
    """把对话框/面板的内容区装进 QScrollArea，返回**内容布局**（按钮行别加这里）。

    结构：dlg → 外层 QVBoxLayout → [ QScrollArea(伸缩因子 1) , 按钮行(由 stick_buttons 加) ]
    内容再多也能滚到底，窗口再小也不会把底部裁掉。
    """
    outer = QVBoxLayout(dlg)
    body = QWidget()
    lay = QVBoxLayout(body)
    lay.setContentsMargins(0, 0, 0, 0)   # 边距留在外层布局，视觉与改动前一致
    area = QScrollArea()
    area.setWidgetResizable(True)        # 跟着窗口伸缩，而不是固定成内容尺寸
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    area.viewport().setAutoFillBackground(False)   # 让 QDialog 的深色底透上来
    body.setAutoFillBackground(False)
    area.setWidget(body)
    outer.addWidget(area, 1)
    dlg._scroll_area = area              # 验收用例要断言"有滚动容器 + 真能滚"
    dlg._content_body = body
    return lay


def stick_buttons(dlg, row):
    """把按钮行钉在滚动区**之外**（对话框底部），返回该行。

    确定/取消绝不能被滚走：行挂在 scroll_content() 建的那个外层布局上，
    排在滚动区后面，所以永远可见。
    """
    outer = dlg.layout()
    if outer is None:
        outer = QVBoxLayout(dlg)
    outer.addLayout(row)
    dlg._btn_row = row
    return row


# ---------------- v2.12.0（E3）：对话框侧的键盘路径 ----------------
# 任务书 E3：PetWindow 只有一个交互面（画布不接收焦点）→ 没有可排的 Tab 链；
# **对话框侧**没做。键盘可达性写在**基类**（_FitDialog）而不是逐个对话框：
# 逐个改必然漏一个，写在基类里，15 个对话框与以后新加的都自动继承（与 v2.5.0 把
# 尺寸兜底放进 showEvent 同一个理由）。
#
# 实测（本机 PySide6 6.11.2 / offscreen）：
#   · Esc：QDialog 自带 reject —— 已经是"关窗"，本类显式写出来只为**统一出口 + 可断言**；
#   · Enter：Qt 自带"触发默认按钮"（默认按钮 = 显式 setDefault，或第一个 autoDefault），
#     所以本类这一支**与 Qt 原行为等价**，价值是让"主按钮"这个概念在基类有一个落点；
#   · Space：Qt **不会**把它给默认按钮（只给焦点控件）→ 这一支是本轮**新增**的行为；
#   · Tab：**不需要动** —— 实测 15 个对话框（VoiceDialog 116 个控件的链在内）里，
#     Qt 按创建顺序串出来的链**本来就把底排按钮行排在最后**，且行内按左→右。
#     本轮试过"基类里再排一次链"，实测零行为收益，反而在 showEvent 里走
#     nextInFocusChain() 让整进程崩在 0xC0000374（堆损坏，见本轮回报）→ 代码撤掉，
#     改成**用例钉住这条不变量**（谁往按钮行后面再加控件就会红）。
_SPACE_OWNERS = (QAbstractButton, QAbstractItemView, QAbstractScrollArea,
                 QAbstractSpinBox, QComboBox, QLineEdit, QPlainTextEdit)
"""空格键有**自己语义**的控件：它们拿着焦点时，空格不算「主按钮」的快捷键。

- QLineEdit / QPlainTextEdit 里空格是**字符**（抢了 = 输入框打不出空格）；
- QAbstractButton 上是"按下这个按钮"（抢了 = 按钮被点两次）；
- 列表/表格/下拉/微调框里空格各有语义（勾选、翻页、展开、解释文本）；
- **QAbstractScrollArea（滚动区，含它的全部子类）**：内容区就是滚动区，而
  **开窗默认焦点恰恰在它身上**（实测：内容区套过 scroll_content 的对话框，show() 之后
  focusWidget() 都是 QScrollArea）—— 不豁免的话，用户刚打开窗口按一下空格，主按钮就被
  click 了（「记一笔」直接落库一笔默认 ¥1.00，见本轮 Z-1）。Qt 自己**不**把空格当翻页键
  （QAbstractScrollArea 只认 PageUp/PageDown；实测按住焦点发空格，滚动条 value 不变），
  所以豁免它 = 空格在这里**什么都不做**，与本轮 E3 之前的行为一致。
"""


class _FitDialog(QDialog):
    """所有对话框的公共基类（v2.5.0 B）：**显示前**按所在屏幕再钳一次尺寸。

    单在这一处重钳，是为了覆盖全部打开路径（modal() 的 show+exec、桌宠.py 里的裸
    exec()、测试里的 show()），以及"构造时在一屏、显示时在另一屏"（多屏用户把桌宠
    拖到副屏再打开设置）。子类自己在 __init__ 里已经钳过一次，这里只做兜底。

    v2.12.0（E3）起它同时是**对话框键盘路径**的唯一落点：Enter/Space 触发主按钮、
    Esc 关窗（Tab 顺序本身不用排——实测 Qt 默认就把底排按钮排在链尾，由用例钉住）。
    写在基类而不是逐个对话框，是为了"新加的对话框自动就有"。
    """

    def showEvent(self, event):
        clamp_dialog(self)
        super().showEvent(event)

    # ---------- v2.12.0（E3）：键盘 ----------
    def primary_button(self):
        """本窗口的「主按钮」= Qt 认定的**默认按钮**；没有这样的按钮就返回 None。

        为什么就是"默认按钮"而不是自己猜一个：默认按钮是 Qt 里"回车该触发谁"的既有口径
        （QSS 的 QPushButton:default 画的就是它），另立一套只会与界面上的高亮不一致。
        取不到（纯查看型窗口、默认按钮被禁用、控件已析构）→ None：Enter/Space 交回 Qt
        原样处理，**不把"关窗"偷偷绑到回车/空格上**。
        """
        for b in self.findChildren(QPushButton):
            if b.isDefault() and b.isEnabled():
                return b
        return None

    def _space_is_free(self):
        """空格现在算不算「主按钮」的快捷键（焦点不在自己要用空格的控件上才算）。"""
        fw = self.focusWidget()
        if fw is None or fw is self:
            return True
        return not isinstance(fw, _SPACE_OWNERS)

    def keyPressEvent(self, event):
        """对话框的键盘出口：Esc → 关窗；Enter/Space → 主按钮。

        Esc 与 Qt 默认一致（QDialog 自己就是 reject），显式写出来是为了**统一出口**并让
        "关窗"这件事可以在基类上断言；各对话框自己的 reject（_DiscardGuard 的"未保存
        改动先问一次"）照旧生效 —— 它拦的是 reject，不是按键。
        """
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.reject()
            event.accept()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) or (
                key == Qt.Key.Key_Space and self._space_is_free()):
            btn = self.primary_button()
            if btn is not None:
                # click 之前**不**调 super()：Qt 自己也会在 Return 上触发默认按钮，
                # 交给它就会点两次（实测：本机 PySide6 6.11.2 offscreen）。
                btn.click()
                event.accept()
                return
        super().keyPressEvent(event)


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
            # v2.3.1（P3-2）：take==1 时 take-1 会除零（FRAME_MAX 被设成 1 的唯一入口），
            # 用 max(1, take-1) 兜底：单帧时全部取第 0 帧，不再抛 ZeroDivisionError
            idxs = [int(round(i * (n - 1) / float(max(1, take - 1)))) for i in range(take)]
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
class RoleImportDialog(_FitDialog):
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
        clamp_dialog(self, 600, 430)   # v2.5.0 B：钳进屏幕可用区域（原来写死 resize）
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

        root = scroll_content(self)   # v2.5.0 B：内容区可滚动（按钮行在滚动区之外）
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
        # N14：按钮走 _on_add_form（加了才给回执），构造期的默认形态仍直接调 _add_form
        self._add_form_btn.clicked.connect(self._on_add_form)
        # v2.11.0（B5）：本窗口没有「保存」按钮，通用措辞会指错按钮（P3-6 的对照表是按
        # 「新建/添加」两个词发的，没区分落点动作）——这里用它自己的落点「导入」。
        self._add_form_btn.setToolTip(BTN_ADD_TIP_IMPORT)
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
        stick_buttons(self, btns)   # v2.5.0 B：按钮行钉在滚动区之外，永远可见

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

    def _on_add_form(self):
        """「＋ 添加形态」按钮（N14）：加了才给回执——此前只有行数变化，用户看不出成没成。

        回执走窗口内的状态行（_notes）：这一段本来就是"素材处理/失败原因"的说明位，
        内联、非模态、不抢焦点，正好是审计说的"气泡或内联状态行"里的第二种。
        """
        if not self._add_form():
            return
        n = len(self._form_rows)
        self._notes.setText("已添加「%s」（共 %d 个，最多 8 个）：改好名字、选好图，"
                            "最后点「导入」。" % (self._form_rows[-1].get("name") or "", n))

    def _add_form(self, name=""):
        """加一个形态行。返回**是否真的加了**（按钮回执按它给，见 _on_add_form）。"""
        if len(self._form_rows) >= 8:
            _warn(self, "形态", "最多 8 个形态")
            return False
        self._form_rows.append({"name": name or "形态%d" % (len(self._form_rows) + 1), "src": ""})
        self._form_views()
        return True

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


# ---------------- v2.9.0 第 7 轮（A1/A2/A7/A10）：动作候选下拉 + 「从图片做动作」的公共实现 ----------------
class _ActionParamCombo(QComboBox):
    """A1：行为步骤的「参数」框 = **可编辑下拉**（能从候选里挑，也能手打）。

    为什么保留 text() / setText() / setPlaceholderText() 三个与 QLineEdit 同名的薄壳：
    调用点与既有用例（v2.7.0 的 `dlg._param.setText(...)`）写的是「一个文本框」，那与
    「换成下拉」这件事无关，没必要连带改一片；而 QComboBox 自带的 clear() 是**清候选**
    （不是清输入），语义撞车，所以清输入另叫 clear_text()。

    **手填永远允许**：setInsertPolicy(NoInsert) 保证敲进去的字不会被候选顶掉、也不会被
    悄悄塞进候选列表。刷新候选时**原样保留用户已经敲进去的字**（set_choices(keep=…)）
    ——「未知名被下拉吃掉」是本轮点名的反模式（审计 E.4-1 / 任务书 A1 验收③）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)

    def text(self):
        return self.currentText()

    def setText(self, value):
        self.setEditText(str(value or ""))

    def clear_text(self):
        self.setEditText("")

    def setPlaceholderText(self, value):
        le = self.lineEdit()
        if le is not None:
            le.setPlaceholderText(str(value or ""))

    def set_choices(self, items, keep=""):
        """换一批候选，**不碰用户已经敲进去的字**（keep = 刷新前的文本）。

        刻意不做「找不到就回落第一条」：那正是把未知名吃掉。找不到就保持空选中 +
        原样回填，用户看到的就是他文件里那个名字。
        """
        keep = str(keep or "")
        self.blockSignals(True)
        try:
            self.clear()          # 清的是**候选**，不是输入
            for it in (items or []):
                self.addItem(str(it))
            self.setCurrentIndex(-1)
            self.setEditText(keep)
        finally:
            self.blockSignals(False)


def _ask_action_name(parent):
    """A10：帧动作的「动作名」框 —— 全仓最后一处静态 QInputDialog 并入统一入口。

    走 `_ask_text`（手工建框 + modal()，与其余 5 处同一口径）。既有用例改成
    monkeypatch `_ask_text`：驱动的是真入口，不再钉住「必须用静态方法」这个实现细节。
    """
    return _ask_text(parent, "帧动作", "动作名（英文字母开头，字母/数字/下划线 ≤24 字符）", "")


def _human_import_error(err, path=""):
    """把导入失败的原始异常翻成用户能懂的一句话（A7）。

    为什么不能原样显示：审计实测用户强选一张 PNG 时，界面弹出的是
    `'utf-8' codec can't decode byte 0x89 in position 0: invalid start byte`、
    选 wav 时是 `Expecting value: line 1 column 1 (char 0)` —— 英文异常对用户零信息。
    原文只进 error.log（排查要用），界面只给人话 + 下一步。
    """
    txt = str(err or "").strip()
    low = txt.lower()
    name = os.path.basename(str(path or "")) or "这个文件"
    if ("codec" in low) or ("decode" in low) or ("unicode" in low) or ("encoding" in low):
        pet_log.log_error("import behavior failed (encoding): %s <- %s" % (txt, path))
        return ("「%s」不是文本行为文件：按文本读的时候编码不对（多半是图片/音频）。\n"
                "行为设置只导入「导出…」出来的 .json。" % name)
    if ("expecting value" in low) or ("json" in low) or ("delimiter" in low):
        pet_log.log_error("import behavior failed (json): %s <- %s" % (txt, path))
        return ("「%s」不是有效的 JSON：内容坏了，或者它根本不是行为文件。\n"
                "行为设置只导入「导出…」出来的 .json。" % name)
    return txt or "导入失败"


class _StagedActionSink(object):
    """落点①：角色编辑（RoleEditDialog）——写进**内存里的暂存表单**，点「保存」才落盘。

    这一路的行为与 v2.8.0 逐位相同（含「出错时只回收本次暂存的文件」：_cleanup_staged()
    会连带删掉同会话先前已成功添加的动作帧）。
    """

    def __init__(self, dlg):
        self._dlg = dlg

    def ready(self):
        # 与改前同口径：没有库 / 没有形态时**静默**放弃（改前也是 return，没有提示）
        if self._dlg._cur_idx is None or self._dlg._lib is None:
            return False, ""
        return True, ""

    def describe(self):
        idx, nm = self._dlg._cur_idx, ""
        try:
            nm = str((self._dlg._forms[idx] or {}).get("name") or "")
        except Exception as e:
            # 不新造静默 except（本仓静默 except 有白名单 razor：新加的必须留痕）
            nm = ""
            pet_log.log_error("frame action sink: 取形态名失败，回执里用序号（%s）" % e)
        return "角色编辑·形态「%s」（暂存，点「保存」才写进角色）" % (nm or ("#%s" % idx))

    def conflict(self, name):
        fm = self._dlg._forms[self._dlg._cur_idx] or {}
        if name in (fm.get("procs") or {}):
            return "该形态已有同名合成动作，帧动作会被遮蔽，换一个名字"
        return ""

    def stage(self, src):
        return self._dlg._lib.stage_file(src)

    def put(self, name, frames):
        fm = self._dlg._forms[self._dlg._cur_idx]
        fm.setdefault("animations", {})[name] = list(frames)
        self._dlg._staged.extend(frames)   # 登记进对话框的待回收表（取消/关窗时删）
        return True, ""

    def rollback(self, frames):
        lib = self._dlg._lib
        for s in frames:
            try:
                if lib is not None:
                    p = lib.resolve(s)
                    if os.path.isfile(p):
                        os.remove(p)
            except Exception as e:
                # 与改前同语义（尽力而为），但**不新造静默 except**：留一条限流日志
                pet_log.log_throttled("role.act.rollback",
                                      "本次帧动作导入的残留清理失败：%r" % (e,))
            if s in self._dlg._staged:
                self._dlg._staged.remove(s)

    def finish(self, name):
        self._dlg._refresh_act_list("%s（帧）" % name)   # 选中 + 滚到可见处（限高 80px）


class _LiveRoleActionSink(object):
    """落点②：行为设置（BehaviorDialog）——**当场写进当前角色当前形态**（roles.json）。

    为什么这里必须真落盘：行为设置里没有「保存角色」这一步。若照角色编辑那样只写内存，
    用户一关窗动作就没了——「看起来成了、其实没成」比「没有入口」更坏（审计 A.1-P5）。
    落盘走既有 API `RoleLibrary.update(rid, {"forms": …})`，**不新增库接口**。
    写成功后与 RolePanel._edit 同口径：改的是当前角色 → apply_role 立即重载帧集。
    """

    def __init__(self, pet):
        self._pet = pet
        self._lib = _get(pet, "role_lib")
        _cfg = getattr(pet, "cfg", None)
        self._rid = str((_cfg or {}).get("role") or "") if isinstance(_cfg, dict) else ""
        keys = list(getattr(pet, "form_keys", None) or [])
        form = str(getattr(pet, "form", "") or "")
        self._idx = keys.index(form) if form in keys else 0
        self.last_added = None   # (name, frames)：刚写进角色的那个动作（撤销入口用）

    def ready(self):
        if self._lib is None or not self._rid:
            return False, ("现在用的是内置默认角色，加不了动作。\n"
                           "先在「📦 资源管理… → 角色」里导入一个角色，再回来加图片动作。")
        if self._lib.get(self._rid) is None:
            return False, "当前角色在角色库里找不到了（可能刚被删）。先换一个角色再试。"
        forms = (self._lib.get(self._rid) or {}).get("forms") or []
        if not (0 <= self._idx < len(forms)):
            return False, "当前角色没有可编辑的形态。"
        return True, ""

    def _form(self):
        r = (self._lib.get(self._rid) if self._lib is not None else None) or {}
        forms = r.get("forms") or []
        return forms[self._idx] if 0 <= self._idx < len(forms) else {}

    def describe(self):
        r = (self._lib.get(self._rid) if self._lib is not None else None) or {}
        role = str(r.get("name") or self._rid or "")
        form = str((self._form() or {}).get("name") or ("形态%d" % (self._idx + 1)))
        return "角色「%s」· 形态「%s」" % (role, form)

    def conflict(self, name):
        fm = self._form() or {}
        if name in (fm.get("procs") or {}):
            return "该形态已有同名合成动作，帧动作会被遮蔽，换一个名字"
        if name in (fm.get("animations") or {}):
            return "%s已经有同名帧动作了，换一个名字（或先去角色编辑里删掉它）" % self.describe()
        return ""

    def stage(self, src):
        return self._lib.stage_file(src)

    def put(self, name, frames):
        r = self._lib.get(self._rid) or {}
        forms = [dict(f) for f in (r.get("forms") or [])]
        if not (0 <= self._idx < len(forms)):
            return False, "这个角色没有可编辑的形态"
        anims = dict(forms[self._idx].get("animations") or {})
        anims[name] = list(frames)
        forms[self._idx]["animations"] = anims
        ok, err = self._lib.update(self._rid, {"forms": forms})
        if not ok:
            return False, err or "写入角色失败"
        # v2.9.0（质量审 6）：这个落点是**立即写盘**的，调用方需要"刚加了什么"才能给撤销入口
        self.last_added = (name, list(frames))
        return True, ""

    def undo(self, name, frames):
        """把刚加进去的动作摘掉（撤销入口用）：**先改索引，成功再删帧文件**。

        为什么必须有它：行为设置这个入口是立即落盘的（与角色编辑里的暂存态相反），
        对话框的「取消」撤不掉它 —— 不给撤销入口就等于"看起来能取消、其实不能"。
        """
        r = self._lib.get(self._rid) or {}
        forms = [dict(f) for f in (r.get("forms") or [])]
        if not (0 <= self._idx < len(forms)):
            return False, "这个角色没有可编辑的形态"
        anims = dict(forms[self._idx].get("animations") or {})
        if name not in anims:
            return False, "它已经不在这个形态上了"
        anims.pop(name, None)
        forms[self._idx]["animations"] = anims
        ok, err = self._lib.update(self._rid, {"forms": forms})
        if not ok:
            return False, err or "写入角色失败"
        for s in (frames or []):
            try:
                p = self._lib.resolve(s)
                if os.path.isfile(p):
                    os.remove(p)
            except Exception as e:
                pet_log.log_throttled("role.act.undo", "撤销后删帧文件失败：%r" % (e,))
        if self._lib is not None and self._lib.active_id() == self._rid:
            _call(self._pet, "apply_role", self._rid)
        return True, ""

    def rollback(self, frames):
        for s in frames:
            try:
                p = self._lib.resolve(s)
                if os.path.isfile(p):
                    os.remove(p)
            except Exception as e:
                pet_log.log_throttled("role.act.rollback.live",
                                      "帧动作写盘失败后的残留清理失败：%r" % (e,))

    def finish(self, name):
        # 同 RolePanel._edit：改的是**当前角色** → 立即重载（否则 roles.json 有了、
        # anim._sets 里还没有 → 候选里选得到但播不了）
        if self._lib is not None and self._lib.active_id() == self._rid:
            _call(self._pet, "apply_role", self._rid)


def add_frame_action(pet=None, parent=None, sink=None):
    """把一组图片做成一个「帧动作」（A2：行为设置与角色编辑**共用这一份实现**）。

    返回 (ok, msg)。msg 的三个语义要分清（调用方据此决定要不要再补一句回执）：
      · ok=False + msg==""  → 用户**取消**（文件框没选 / 名字框取消）→ 静默，不留半截；
      · ok=False + msg!=""  → 失败，msg 是**中文原因**（照它提示，别自己编）；
      · ok=True              → 已加好，msg 形如「已添加动作「X」（落在哪）」。

    **取消是干净的**：命名框取消时一个文件都还没暂存；所有失败路径都把本次已暂存的文件
    回收（sink.rollback），不会留下半截动作（任务书 A2 验收②）。
    """
    parent = _qt_parent(parent if parent is not None else pet)
    if sink is None:
        sink = _LiveRoleActionSink(pet)
    _ok, why = sink.ready()
    if not _ok:
        if why:
            _warn(parent, "导入图片做动作", why)
        return False, why
    files, _f = QFileDialog.getOpenFileNames(
        parent, "选择动作帧图片（2 张起）", "", "图片 (*.png *.jpg *.jpeg *.bmp *.webp)")
    if not files:
        # v2.7.0 第 5 轮（P2-4）：**取消**（文件框回空表）不是「选少了」——静默返回，
        # 与其它文件框取消路径同口径。
        return False, ""
    if len(files) < 2:
        # v2.10.0（U2）：此前只说下限（"至少 2 张图"）——**为什么不行**与**该怎么办**
        # 都没有；用户读到的是"你选错了"。换成解释性文案：1 张 = 静态姿势（这里做不了），
        # 2 张以上 = 按选择顺序的逐帧动画。⚠ 只改文案，**下限一个字没动**（U1 用户已撤回）。
        _msg = ("帧动作至少 2 张图：1 张图只是一个静态姿势，这里做不了静态姿势动作；"
                "要做一个动作，请一次选 2 张以上（最多 %d 张），它们会按选择顺序做成逐帧动画。"
                % int(pet_resources.FRAME_MAX))
        _warn(parent, "帧动作", _msg)
        return False, _msg
    max_frames = int(pet_resources.FRAME_MAX)
    if len(files) > max_frames:
        _msg = "最多 %d 帧（可在设置里调整）" % max_frames
        _warn(parent, "帧动作", _msg)
        return False, _msg
    name, asked = _ask_action_name(parent)
    name = (name or "").strip()
    if not asked or not name:
        return False, ""   # 取消命名 = 一个文件都还没暂存（干净）
    if not pet_resources.CUSTOM_ACTION_RE.match(name):
        _msg = "动作名不合法（英文字母开头，字母/数字/下划线）"
        _warn(parent, "帧动作", _msg)
        return False, _msg
    if name in pet_resources.ANIM_ACTIONS or name in pet_resources.ACTION_RESERVED:
        _msg = ("动作名与内建动作/保留名重名（%s），换一个名字"
                % "、".join(pet_resources.ANIM_ACTIONS + pet_resources.ACTION_RESERVED))
        _warn(parent, "帧动作", _msg)
        return False, _msg
    _clash = sink.conflict(name)
    if _clash:
        _warn(parent, "帧动作", _clash)
        return False, _clash
    tmpdir = tempfile.mkdtemp(prefix="role_act_")
    made = []
    try:
        outs, notes = _prepare_role_frames(files, tmpdir, same_size=False)
        if outs is None:
            _msg = "处理失败：%s" % (notes,)
            _warn(parent, "帧动作", _msg)
            return False, _msg
        for o in outs:
            s = sink.stage(o)
            if s is None:
                raise RuntimeError("写入角色目录失败")
            made.append(s)
        _ok2, _err2 = sink.put(name, made)
        if not _ok2:
            raise RuntimeError(_err2 or "保存失败")
    except Exception as e:
        sink.rollback(made)
        _msg = "导入失败：%s" % e
        _warn(parent, "帧动作", _msg)
        return False, _msg
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    sink.finish(name)
    return True, "已添加动作「%s」（%s）" % (name, sink.describe())

class RoleEditDialog(_FitDialog):
    """P1-7 轻量角色编辑：改名 / 形态改名+调序 / 换图（重新处理，不换 id）/
    渲染参数（anchor/scale/offset）/ 帧间隔 / 正面图（front）/ 状态图（states）。

    确认时把新素材经管线处理后写入 roles/ 目录（新文件名），用
    RoleLibrary.update(rid, patch) 落盘索引；成功后清理不再被引用的旧文件。
    全部编辑只在当前库的该角色上进行，不新建 id。
    """

    def __init__(self, parent=None, lib=None, role_id=""):
        super().__init__(_qt_parent(parent))
        # v2.8.0 第 6 轮（D14）：回执走宠物气泡，需要 pet 本体（可能为 None → _toast 静默降级）
        self._pet = parent
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
        clamp_dialog(self, 620, 540)   # v2.5.1 A（L5）：设计宽 600→620，消除 20px 横向滚动条

        root = scroll_content(self)   # v2.5.0 B：内容区可滚动
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
        _btn_tip(b_add_f, "＋帧动作…")   # P3-6
        _btn_tip(b_add_p, "＋合成…")     # P3-6
        b_del = QPushButton("删除")
        b_del.clicked.connect(self._del_action)
        act_btns.addWidget(b_add_f)
        act_btns.addWidget(b_add_p)
        act_btns.addWidget(b_del)
        act_head.addLayout(act_btns)
        right.addLayout(act_head)
        # v2.10.0（R1/G3）：行为设置里的「＋导入图片做动作…」**立即写盘**（加完就能播，
        # 用「撤销这次导入」收回），而这里的「＋帧动作…」是**暂存态**（点「保存」才落到
        # 角色上）。两条路做同一件事、语义相反，用户事前无从得知 —— 裁决选②：保留各自
        # 的语义，但把差异写到**用户看得见的地方**（常驻说明，不靠 tooltip/悬停）。
        # U2 的落点也在这里：顺手把"为什么至少要 2 张"说在入口旁边。
        self._act_note = QLabel(
            "「＋帧动作…」是暂存：选 2 张以上图片，按选择顺序做成逐帧动画"
            "（1 张只是静态姿势，做不了动作）；先放进这个窗口，点「保存」才落到角色上，"
            "点「取消」或关掉窗口会连同刚加的一起放弃。")
        self._act_note.setWordWrap(True)
        right.addWidget(self._act_note)

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
        stick_buttons(self, btns)   # v2.5.0 B：按钮行在滚动区之外

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
        # N2（v2.4.1）：判据必须是**键在不在**，不能是"值是不是 None"——None 是有效值
        # （用户点了「清除正面图」），用 is-not-None 会让"已清除"这一态永远显示不出来，
        # 回落成 elif 的"已有正面图"：用户点完清除，界面反而说"已有正面图"。
        if idx in self._pending_front:
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
    def _refresh_act_list(self, select=None):
        """列出当前形态的自定义动作（帧动作 + 程序化合成）；select=新条目的列表文案。

        v2.8.0 第 6 轮（N12/N13 的"视口外"）：这个列表**限高 80px**，动作一多，新加的那条就
        落在视口外面——"列表里确实有了"不等于"用户看见了"，用户视角与"点了没反应"完全等价。
        所以新增成功后，调用方把新条目的文案传进来，这里选中它并滚到可见处（照 v2.7.0 对
        行为/音效/闹钟/台词那几处"新建后选中"的同款口径）。
        """
        self._act_list.clear()
        if self._cur_idx is None or self._loading:
            return
        fm = self._forms[self._cur_idx]
        for act in (fm.get("animations") or {}):
            if act not in pet_resources.ANIM_ACTIONS:
                self._act_list.addItem("%s（帧）" % act)
        for name in sorted(fm.get("procs") or {}):
            self._act_list.addItem("%s（合成）" % name)
        if not select:
            return
        for i in range(self._act_list.count()):
            if self._act_list.item(i).text() == str(select):
                self._act_list.setCurrentRow(i)
                self._act_list.scrollToItem(self._act_list.item(i))
                break

    def _add_frame_action(self):
        """多选图片 → 统一画布管线 → 立即入角色目录（staged，取消时回收）。

        v2.9.0（A2/B2）：实现搬到模块级 `add_frame_action()` —— 行为设置里的
        「＋导入图片做动作…」调的是**同一个函数**（不许两份实现）。这里只描述
        「落点是本窗口的暂存表单」这一件事。
        """
        add_frame_action(self._pet, self, sink=_StagedActionSink(self))

    def _add_proc_action(self):
        """添加程序化合成动作（呼吸/摇摆/点头，用角色自身贴图合成，无需素材）。"""
        dlg = _FitDialog(self)   # v2.5.0 B：内联对话框也走同一套尺寸钳制（原来裸 QDialog）
        dlg.setWindowTitle("程序化合成动作")
        dlg.setStyleSheet(DIALOG_QSS)
        lay = scroll_content(dlg)
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
        # P2-7 / N13：内联框必须自带「取消」（此前只有「添加」，只能靠 Esc / × 退出）。
        # 取消走 dlg.reject() → 下面直接 return，一个 procs 都不落（不留半截编辑）。
        ok = QPushButton("添加")
        ok.setDefault(True)
        ok.clicked.connect(dlg.accept)
        cancel = QPushButton("取消")
        cancel.clicked.connect(dlg.reject)
        _btn_row = QHBoxLayout()
        _btn_row.addStretch(1)
        _btn_row.addWidget(ok)
        _btn_row.addWidget(cancel)
        stick_buttons(dlg, _btn_row)   # v2.5.0 B：按钮行在滚动区之外
        # 与其它子对话框同一条路径：modal() 负责置顶 + 抢焦点（裸 exec() 会被前台锁拦）
        if modal(dlg) != QDialog.DialogCode.Accepted:
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
        self._refresh_act_list("%s（合成）" % name)   # 选中 + 滚到可见处（限高 80px）

    def _del_action(self):
        """删除选中的自定义动作（按条目后缀只删对应类型：帧/合成同名互不影响）。

        v2.9.0 第 7 轮（A6）——**有意撤销上一轮（v2.8.0 D14）加的那个二次确认**。
        理由：它是**暂存态**，删掉的只是本窗口里待提交的动作，点「取消」/关窗会连同这次
        删除一起丢弃，**本来就是可撤销的**；给可撤销操作套不可逆确认 = 多一步 + 误导
        （旧确认文案自己都写着「这一步只是暂存…取消会放弃全部改动」）。同仓口径：导入
        向导删形态行同为暂存态、**不加**确认（审计 C.1-#14 / D#11）。
        保留的是「删掉之后能取消恢复」这条**可用性事实**——由 closeEvent/取消路径保证，
        也由 tests/test_dialogs_feedback_v280.py 的**加强式**用例钉住（改成断言「删掉后
        可取消恢复」，不是把断言删掉）。
        """
        item = self._act_list.currentItem()
        if item is None or self._cur_idx is None:
            _warn(self, "删除动作", "先在「自定义动作」里选中一个动作")
            return
        text = item.text()
        kind = "帧" if text.endswith("（帧）") else ("合成" if text.endswith("（合成）") else "")
        name = text[:-(len(kind) + 2)] if kind else text
        fm = self._forms[self._cur_idx]
        removed = False
        if kind == "帧":
            fm.setdefault("animations", {}).pop(name, None)
            removed = True
        elif kind == "合成":
            fm.setdefault("procs", {}).pop(name, None)
            removed = True
        if removed:
            self._refresh_act_list()
            # 回执里带上「可以撤销」这条事实（轻量提示 = 替代确认框的那一步）
            _toast(self._pet, "已删除自定义动作「%s」（点「取消」或关掉这个窗口，本次删除会被放弃）"
                   % name)
        else:
            _warn(self, "删除动作", "这条动作已经不在列表里了（可能刚被删过）")

    def closeEvent(self, event):
        self._cleanup()
        if self.result() != QDialog.DialogCode.Accepted:
            self._cleanup_staged()  # v2.0.1：取消/关闭时回收未提交的新文件
        super().closeEvent(event)


# ---------------- v2.0.2：行为自定义 ----------------
class _DiscardGuard(object):
    """「有未保存改动就先问一次」的公共实现（A5 口径；BehaviorDialog / AlarmDialog 共用）。

    为什么要抽出来（v2.9.0 质量审查 F1）：同一种病当时只治了 BehaviorDialog —— 闹钟的第二枚
    按钮还叫「关闭」、且丢弃未保存编辑时零提示，正是 R4 点名的硬反例。**同一语义只写一份**，
    以后再加"表单型对话框"直接混入即可。

    子类只要给两样：`_form_signature()`（当前表单的指纹）与 `_discard_prompt(why)`（问什么），
    并在**每次载入新基线**（打开/选中/新建/保存完）时更新 `self._baseline`。
    """

    _baseline = None
    # v2.9.0（找茬 delta 复跑 M15）：**一次性令牌**，不是"置位后一直有效"的闩。
    # 它只在 closeEvent →(Qt 内部)→ reject 这**一跳**内有效，用完（或被 finally）即失效。
    # 为什么必须这样：曾经的设计是"用户确认过一次就永远不问"，于是任何一次"换条目确认"
    # 只要漏清一次闩，之后【编辑 → 点标题栏 ×】就会**零确认直接关窗、改动静默丢**
    # （M15 实测：全量 1339 passed、无人抓）。令牌把这条长路径从设计上封死：
    # 令牌永远不会跨过用户的下一次操作存活。
    _close_confirmed = False

    def _form_signature(self):
        raise NotImplementedError

    def _discard_prompt(self, why="close"):
        return "表单里还有没保存的改动。"

    def _row_of(self, bid):
        """按 id 找列表行（换条目被拒时要拨回去）。没有列表/找不到 → -1。"""
        lst = getattr(self, "_list", None)
        if lst is None or not bid:
            return -1
        for _i in range(lst.count()):
            if lst.item(_i).data(Qt.ItemDataRole.UserRole) == bid:
                return _i
        return -1

    def _is_dirty(self):
        """有未保存的改动吗（A5）。没有改动就不该多问一步（原则 1）。"""
        return self._form_signature() != self._baseline

    def _confirm_discard(self, why="close"):
        """A5：有未保存改动才问；没改动直接放行。

        **没有 latch 参数**（delta 复跑 M15 的教训）：这个函数只负责"该问就问"，
        "同一跳里不重复问"由 `closeEvent` 的一次性令牌负责（见 `_close_confirmed`）。
        """
        if not self._is_dirty():
            return True
        return bool(_confirm(self, "取消编辑", self._discard_prompt(why)))

    def _on_close_confirmed(self):
        """子类钩子：确认关窗之后、真正 close 之前要做的收尾（默认什么都不做）。"""
        return None

    def _cancel(self):
        """「取消」按钮：等同关窗（有未保存改动时先问一次）。"""
        self.reject()

    def reject(self):
        """A5：Esc / 「取消」都走这里 —— 有未保存改动先问一次。

        唯一不问的情况是"**这一次关窗刚刚问过**"（`_close_confirmed`，由 closeEvent 设、
        这里消费掉）—— 标题栏 × 会走 closeEvent →(Qt)→ reject，不这样做就是连问两遍。
        """
        if self._close_confirmed:
            self._close_confirmed = False       # 消费掉：令牌只活这一跳
            super().reject()
            return
        if not self._confirm_discard():
            return
        super().reject()

    def closeEvent(self, event):
        """A5：标题栏 × 的路径。

        确认之后设一次性令牌，只为紧随其后的那一跳（Qt 从 closeEvent 调到的 reject）放行；
        `finally` 保证无论走哪条路令牌都会失效 —— 它**不会**留给用户的下一次操作。
        """
        if not self._confirm_discard():
            event.ignore()
            return
        self._on_close_confirmed()
        self._close_confirmed = True
        try:
            super().closeEvent(event)
        finally:
            self._close_confirmed = False


class BehaviorDialog(_DiscardGuard, _FitDialog):
    """行为自定义对话框：列表 + 新建/编辑/删除 + 步骤编辑 + 试播 + 导入/导出。

    待机行为 / 触发秒数 / 变身时长也在这里配置（写 pet.cfg 并 save_cfg 持久化）。
    """

    def __init__(self, pet, svc=None, save_cfg=None):
        super().__init__(pet)
        self.pet = pet
        self.svc = svc or getattr(pet, "behaviors", None)
        self._save_cfg = save_cfg or (lambda cfg: None)
        self._editing_id = None
        # v2.9.0（A11/P2-8）：常驻「新建中」状态标签的状态位
        self._new_state = False
        # v2.9.0（A5）：「取消」/关窗的未保存判据 = 表单与它被载入时是否一样
        self._baseline = ("", ())
        # v2.9.0（A5）：确认只问一次（标题栏 × 会先走 closeEvent、再由 Qt 调到 reject）
        # v2.9.0（质量审 6）：上一次「＋导入图片做动作…」加了什么（撤销入口用）
        self._last_pic_import = None
        self.setWindowTitle("行为自定义")
        self.setStyleSheet(DIALOG_QSS)
        clamp_dialog(self, 640, 500)   # v2.5.0 B
        lay = scroll_content(self)   # v2.5.0 B：内容区可滚动

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
        # v2.9.0（A11 / 按钮审计 P3-5）：`pet_dialogs.open_idle` 以前**没有 UI 入口**
        # （挂了两轮）。这里给它一个真实入口：这个下拉与「待机设置」改的是同一份
        # cfg["idle_actions"]，两套视图之间本来就该有一道能走的门（审计 D#4 流程断裂）。
        self._idle_btn = QPushButton("待机设置…")
        self._idle_btn.setToolTip("打开「待机设置」：多动作列表、播放模式、待机形态都在那里；"
                                  "这个下拉只表示「空闲时只播某一条」")
        self._idle_btn.clicked.connect(self._open_idle_settings)
        idle_row.addWidget(self._idle_btn)
        lay.addLayout(idle_row)
        self._idle_combo.currentIndexChanged.connect(self._on_idle_pick)
        self._idle_secs.valueChanged.connect(lambda _v: self._save_cfg_vals())
        self._transform_secs.valueChanged.connect(lambda _v: self._save_cfg_vals())

        # ---- v2.9.0（A9/P2-8）：常驻状态标签 ----
        # 「点「保存」才落盘」这条决定成败的信息，改前**只写在 tooltip 里**（tooltip 不可
        # 发现、键盘/触屏没有 hover）；而 P2-8 的原口径本来就是「表单区顶部常驻的内联状态
        # 标签」，v2.8.0 只做了一次性气泡＝修法不符。这里合并成一行常驻文字：既说清「现在
        # 是什么状态」，也说清「要保存才落盘」。
        self._state_label = QLabel("")
        self._state_label.setWordWrap(True)
        lay.addWidget(self._state_label)

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
        # v2.9.0（A1）：参数框从裸 QLineEdit 改成**可编辑下拉** —— 候选来自 B1 的
        # pet_behaviors.action_choices()（只给候选；手填永远允许，见 _ActionParamCombo）
        self._param = _ActionParamCombo()
        self._act_combo.currentIndexChanged.connect(lambda _i: self._sync_param())
        b_add_step = QPushButton("添加步骤")
        b_add_step.clicked.connect(self._add_step)
        _btn_tip(b_add_step, "添加步骤")   # P3-6
        add_row.addWidget(self._act_combo)
        add_row.addWidget(self._param, 1)
        add_row.addWidget(b_add_step)
        lay.addLayout(add_row)
        step_row = QHBoxLayout()
        # v2.9.0（A3）：标签写着「按顺序执行」却**没有排序按钮**（审计 B.2 缺失项）
        b_up = QPushButton("上移")
        b_up.clicked.connect(lambda: self._move_step(-1))
        b_down = QPushButton("下移")
        b_down.clicked.connect(lambda: self._move_step(1))
        b_del_step = QPushButton("删除选中步骤")
        # P1-6：以前是 lambda 直接 takeItem(currentRow())——没选中时 takeItem(-1) 只往
        # qWarning 打一行，界面上什么都没发生、也没有任何提示
        b_del_step.clicked.connect(self._del_step)
        b_up.setToolTip("把选中的步骤往上挪一格（顺序就是执行顺序）")
        b_down.setToolTip("把选中的步骤往下挪一格")
        b_del_step.setToolTip("删掉选中的那一步（点「保存」才落盘）")
        step_row.addWidget(b_up)
        step_row.addWidget(b_down)
        step_row.addWidget(b_del_step)
        step_row.addStretch(1)
        # v2.9.0（A2）：就地入口——从图片做一个动作；加完立刻出现在上面的「动作」候选里
        self._pic_btn = QPushButton("＋导入图片做动作…")
        self._pic_btn.setToolTip("选 2 张以上图片做成一个帧动作；加完就能在上面的「动作」参数里选它")
        self._pic_btn.clicked.connect(self._import_frame_action)
        step_row.addWidget(self._pic_btn)
        lay.addLayout(step_row)
        # A2：按钮旁**明写**这次动作会加在哪儿（不是加进行为库）——不指望用户去悬停
        self._act_target = QLabel("")
        self._act_target.setWordWrap(True)
        lay.addWidget(self._act_target)
        # ---- v2.9.0（A4）：窗口内状态行 ----
        # 列表内的连续操作（添加/删除/排序步骤）的回执走这里：内联、可累积、不覆盖、
        # 不需要宠物窗口在场。改前这些走宠物气泡，实测「建一个 5 步行为弹 7 条气泡」，
        # 而气泡是**单窗口覆盖式**（无队列）→ 连点时前面的根本看不见、最后一条还滞留 5 秒。
        # 同仓正例：RoleImportDialog._on_add_form 的 self._notes.setText(...)。
        self._notes = QLabel("")
        self._notes.setWordWrap(True)
        lay.addWidget(self._notes)
        # v2.9.0（质量审 6）：A2 的入口是**立即写盘**的（与角色编辑里的暂存态相反），所以
        # 必须给一个真的能收回的入口 —— 只有"刚导入过"时才亮，平时不占注意力。
        self._undo_pic_btn = QPushButton("撤销这次导入")
        self._undo_pic_btn.setToolTip("把上一次「＋导入图片做动作…」加进去的动作从角色里移除"
                                      "（帧文件一起删掉）")
        self._undo_pic_btn.clicked.connect(self._undo_pic_import)
        self._undo_pic_btn.setVisible(False)
        lay.addWidget(self._undo_pic_btn)

        # ---- 按钮 ----
        # v2.9.0（A5）：第二枚按钮从「关闭」改名「取消」——它执行的是「丢弃未保存编辑 +
        # 关窗」，叫「关闭」是标签在说谎（B3 的 R4 不变量）。有未保存改动时会先问一次；
        # **没有改动直接关**（原则 1：不给熟路加一步）。保存仍然不关窗（B3：面板型）。
        btn_row = QHBoxLayout()
        for _label, _cb, _tip in (
                ("新建", self._new, BTN_NEW_TIP),
                ("保存", self._save, "把当前表单写进行为库（写进库里窗口不关，可以接着改）"),
                ("删除", self._delete, "删掉列表里选中的那条行为（会先问一次，删了不可撤销）"),
                ("试播", self._test_play, "先保存再播一遍；保存没成功就不播（免得你看到的是旧内容）"),
                ("导入行为文件（.json）…", self._import, "导入别人分享的行为文件（.json）"),
                ("导出…", self._export, "把选中的行为导出成 .json 文件"),
                ("取消", self._cancel, "关掉这个窗口；表单里有没保存的改动时会先问一次")):
            _b = QPushButton(_label)
            _b.clicked.connect(_cb)
            _btn_tip(_b, _label)       # P3-6：新建/添加各一套措辞
            _b.setToolTip(_tip)        # A9：tooltip 只作**补充**，关键那句在常驻标签里
            btn_row.addWidget(_b)
        stick_buttons(self, btn_row)   # v2.5.0 B：按钮行在滚动区之外
        self._sync_param()
        self._refresh()
    # ---------- v2.9.0（A1/A2/A3/A4/A5/A9/A11）：状态行 / 常驻标签 / 动作候选 / 排序 / 取消 ----------

    def _note(self, text):
        """窗口内状态行（A4）：列表内连续操作的回执走这里，不用宠物气泡。

        为什么不是气泡：Bubble 是**单窗口覆盖式**（pet_widgets.py 直接 setText + show +
        5 秒定时器，无队列）——连点三次只有最后一条可见，而前面那几条用户根本没看到；
        而这一步是「列表内连续操作」，用户的眼睛在窗口里，不在宠物身上。
        """
        try:
            self._notes.setText(str(text or ""))
        except Exception as e:
            pet_log.log_error("behavior notes failed: %r" % (e,))

    def _refresh_state_label(self):
        """常驻状态标签（A11/P2-8 + A9）：新建态一直可见，直到保存或取消。

        三态（同一行文字同时承载「现在处于什么状态」与「要保存才落盘」这条决定成败的信息）：
          · 新建态     → ● 新建中（未保存）
          · 选中了某条 → ● 编辑中：<名字>
          · 都没选中   → 中性提示（刚打开窗口时）
        """
        name = self._name.text().strip()
        if self._new_state:
            txt = "● 新建中（未保存）：填好行为名与步骤后点「保存」才会写进库里"
        elif self._editing_id:
            txt = "● 编辑中：%s —— 改完点「保存」才写进库里" % (name or self._editing_id)
        else:
            txt = "点「新建」开始建一条新行为；表单里的内容点「保存」才会写进库里"
        self._state_label.setText(txt)

    def _target_text(self):
        """A2：按钮旁明写这次动作会加在哪儿（**不是加进行为库**）。"""
        sink = _LiveRoleActionSink(self.pet)
        ok, why = sink.ready()
        if not ok:
            return "（现在加不了图片动作：%s）" % ((why or "当前没有可编辑的角色").splitlines()[0])
        # v2.10.0（R1/G3·裁决②）：这个入口与「角色编辑 →＋帧动作…」做的是同一件事、
        # 语义相反（这里立即写盘，那边暂存到点「保存」）。所以这句话必须直接回答用户
        # 动手前的那个问题——"在这个窗口里点「取消」会不会撤销它"：**不会**。只写"立即"
        # 还不够：用户会把"窗口的取消"当成通用的撤销键。
        return ("（图片会做成 %s 的帧动作，立即写进角色——在这个窗口点「取消」或关掉窗口"
                "都不会撤销它（与「资源管理 → 角色 → 编辑…」里的「＋帧动作…」相反："
                "那边点「取消」就放弃）；要收回请点下面的「撤销这次导入」。"
                "它不会加进行为库）") % sink.describe()

    def _action_choices(self):
        """A1：动作候选的**唯一来源** = pet_behaviors.action_choices(pet)（B1 接口）。

        刻意**不做本地兜底**（不自己再算一份）：两份候选一旦漂移，下拉里就会出现
        「选得到、但播不了」的名字，而本轮要修的正是这条路。接口缺失/抛异常 → 空候选 +
        日志；**手填永远不受影响**（下拉是「给候选」，不是「白名单」）。
        """
        fn = getattr(pet_behaviors, "action_choices", None)
        if not callable(fn):
            pet_log.log_error("pet_behaviors.action_choices 缺失：动作候选为空（手填仍可用）")
            return []
        try:
            return [str(x) for x in (fn(self.pet) or []) if str(x or "").strip()]
        except Exception as e:
            pet_log.log_error("action_choices failed: %r" % (e,))
            return []

    def _sync_param(self):
        """按当前步骤类型刷新参数框：只有「动作」有候选，其余仍是纯文本。

        **不吞用户输入**：换类型 / 换候选时原样保留已经敲进去的字——老行为文件里的动作名
        不在候选里，也必须原样显示、原样保存（A1 验收③）。
        """
        act = self._act_combo.currentData()
        keep = self._param.text()
        self._param.setPlaceholderText(self._param_hint(act))
        self._param.set_choices(self._action_choices() if act == "play_action" else [], keep=keep)

    def _form_signature(self):
        """当前表单的指纹（A5：判断有没有未保存的改动）。"""
        steps = []
        for st in self._collect_steps():
            try:
                steps.append(tuple(sorted((str(k), str(v)) for k, v in st.items())))
            except Exception as e:
                steps.append((("act", str(st.get("act"))),))
                pet_log.log_error("behavior form signature: 步骤指纹回退（%s）" % e)
        return (self._name.text().strip(), tuple(steps))

    def _discard_prompt(self, why="close"):
        """A5：问什么（关窗与换条目两种措辞 —— 后者窗口不关，别写「并关窗」）。"""
        if why == "switch":
            return ("表单里还有没保存的改动（行为名或步骤）。\n"
                    "点「确定」= 放弃这些改动、切到另一条；点「取消」= 留在这一条接着改。")
        return ("表单里还有没保存的改动（行为名或步骤）。\n"
                "点「确定」= 放弃这些改动并关窗；点「取消」= 回去接着改。")

    def _open_idle_settings(self):
        """A11 / 按钮审计 P3-5：给 open_idle 一个**真实入口**。

        选的是「给入口」而不是「删掉/合并」：这个下拉与待机设置改的是同一份
        cfg["idle_actions"]，审计 D#4 判的是**流程断裂**（两套视图之间没有门）；
        而删掉 open_idle 还得改既有用例（tests/test_dialogs_more_v24.py 在调它），
        收益只是少一个函数名。开门既修了断裂，又让这个入口真的有人走。
        """
        open_idle(self.pet)
        self._refresh()      # 待机设置里可能改了 idle_actions → 回来把下拉重算一遍

    def _import_frame_action(self):
        """A2：「＋导入图片做动作…」——落在**当前角色的当前形态**，**立即写盘**。

        v2.9.0（质量审 6）：它和角色编辑里那个入口**语义相反**（那边是暂存态、取消即放弃）。
        这里选了「立即生效」（用户就是要快速加个动作），那就必须**把话说清**（按钮旁的常驻
        文案 + 状态行）**并给撤销入口**（`_undo_pic_import`），不能让它"看起来能取消"。
        """
        sink = _LiveRoleActionSink(self.pet)
        ok, msg = add_frame_action(self.pet, self, sink=sink)
        if not ok:
            # msg=="" 是「用户取消」（静默）；其它失败都已经由 add_frame_action 用中文
            # 提示过了，这里只在状态行留一句（不重复弹框）
            if msg:
                self._note(msg)
            return
        self._last_pic_import = getattr(sink, "last_added", None)
        self._undo_pic_btn.setVisible(bool(self._last_pic_import))
        self._note(msg + "：上面的「动作」候选里现在能选到它了"
                   "（立即生效；要收回就点「撤销这次导入」）")
        self._sync_param()

    def _undo_pic_import(self):
        """撤销上一次「＋导入图片做动作…」：把刚加的动作从角色里摘掉，帧文件一起删。

        这是"立即生效"这个选择必须配的代价项（质量审 6 的 ② 方案）：不给它，用户会以为
        对话框的「取消」能撤销这次导入。
        """
        rec = self._last_pic_import
        self._last_pic_import = None
        self._undo_pic_btn.setVisible(False)
        if not rec:
            return
        name, frames = rec
        ok, err = _LiveRoleActionSink(self.pet).undo(name, frames)
        if not ok:
            self._note("撤销失败：%s" % (err or "写入角色失败"))
            return
        self._sync_param()
        self._note("已撤销：动作「%s」已从角色里移除（帧文件也删了，候选里也没它了）" % name)

    def _move_step(self, delta):
        """A3：步骤上移 / 下移（标签写着「按顺序执行」，顺序就是语义）。

        回执走**窗口内状态行**（不是宠物气泡）：这是列表内的操作，用户在盯着列表
        （口径见任务书原则 2 与 A4；A3 那句「照 LinesDialog._move_line 的做法」指的是
        **到顶/到底也要说一句**这件事——措辞照抄，渠道按原则 2 走内联）。
        移动后选中项跟着走（否则连点两下就不知道动的是谁）。
        """
        row = self._steps.currentRow()
        if row < 0:
            _warn(self, "排序", "先在「动作序列」里选中要移动的步骤")
            return
        j = max(0, min(self._steps.count() - 1, row + int(delta)))
        if j == row:
            self._note("已经是最上面了" if int(delta) < 0 else "已经是最下面了")
            return
        item = self._steps.takeItem(row)
        self._steps.insertItem(j, item)
        self._steps.setCurrentRow(j)
        self._steps.scrollToItem(item)
        self._note("已把「%s」%s（点「保存」才落盘）"
                   % (item.text()[:24], "上移" if int(delta) < 0 else "下移"))

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

    def _idle_action_labels(self, dropped):
        """把「会被丢掉」的待机条目列成人看得懂的名字（B5 的确认文案用）。"""
        lines = []
        for a in (dropped or []):
            bid = str((a or {}).get("behavior_id") or "")
            name = ""
            if self.svc is not None and bid:
                try:
                    name = str((self.svc.get(bid) or {}).get("name") or "")
                except Exception as e:
                    name = ""
                    pet_log.log_error("behavior idle labels: 查行为名失败，回落显示 id（%s）" % e)
            lines.append("· %s" % (name or bid or "（空条目）"))
        return "\n".join(lines)

    def _on_idle_pick(self, _idx):
        """待机行为下拉：把「空闲时只播这一条」写进新待机配置（idle_actions + single）。

        v2.1：不再写旧键 idle_behavior —— 否则旧键会把用户在待机设置里删掉的行为「复活」（M2）。
        v2.9.0（B5）：改前这里是**硬编码** data = {idle_actions: [], sequential}：只要用户碰
        一下下拉，配置里原有的多条待机动作就被静默清空/覆盖成 1 条（审计实测 2 条 → 1 条，
        只有一句通用气泡）——**数据损失面**。现在「会丢什么」先由
        pet_behaviors.idle_single_change(..., apply=False) 算出来；
        **F-2（找茬）修正了确认的开关**：判据不是"dropped 非空"（那只表示"有别的条目"），
        而是**"条目数真的会减少"**（len(现在) > 1/0）——换一条（1→1）不问，
        只有会丢条目时才问，并且说清"剩几条、丢掉哪几条"。
        """
        cfg = getattr(self.pet, "cfg", None)
        if not isinstance(cfg, dict):
            return
        bid = self._idle_combo.currentData() or ""
        _before = pet_behaviors.normalize_idle_cfg(cfg)["idle_actions"]
        dropped, err = pet_behaviors.idle_single_change(cfg, bid, apply=False)
        if err:
            _warn(self, "待机设置", err)
            self._refresh()
            return
        # F-2（找茬审查）：**只有条目数真的会减少**才值得问一句。
        # 改前判的是 `if dropped`，而 dropped 的定义是「所有 behavior_id ≠ 选中项的条目」
        # —— 配置里只有 1 条待机、用户改选另一条时 dropped 也非空，于是弹一句
        # 「还有另外 1 条动作…」，**而条目数 1 变 1 根本没减少**、被丢的正是他要换掉的那条，
        # 还被文案说成「另外」。这就是用户抱怨的「多一步」。口径回到 B5 自己那句：
        # 任何一次下拉操作后条目数不减少（除非用户明确选择丢弃且有确认）—— 没减少就不该问。
        _after = 1 if bid else 0        # 选完之后列表里会剩几条（""=不启用 → 0 条）
        _shrinks = len(_before) > _after
        if _shrinks and not _confirm(
                self, "待机行为",
                "这个下拉的语义是「空闲时只播这一条」。\n"
                "当前待机列表里有 %d 条动作，继续只会剩下 %d 条，被丢掉的：\n%s\n\n"
                "想保留多条（顺序/随机/权重），请点旁边的「待机设置…」在那里改。"
                % (len(_before), _after, self._idle_action_labels(dropped))):
            self._refresh()   # 拒绝 → 拨回配置的真实状态，不留半截界面
            return
        pet_behaviors.idle_single_change(cfg, bid, apply=True)
        if _call(self.pet, "apply_idle_settings",
                 {"idle_actions": cfg["idle_actions"],
                  "idle_play_mode": cfg["idle_play_mode"]}) is None:
            self._save_cfg(cfg)  # 兜底：老 pet 没有新入口时仍保存（不崩）
        self._refresh()
        if _shrinks:
            self._note("已把待机行为设为「%s」，并按你的确认丢掉了 %d 条"
                       % (self._idle_combo.currentText(), len(dropped)))
        else:
            # 条目数没变（换了一条）= 用户意图完全达成，不该留"丢掉了"的措辞
            self._note("已把待机行为设为「%s」" % self._idle_combo.currentText())

    # ---------- 列表 ----------

    def _refresh(self):
        self._list.clear()
        _cfg = getattr(self.pet, "cfg", {}) or {}
        _behaviors = []
        if self.svc is not None:
            for b in self.svc.list():
                _behaviors.append(b)
                self._list.addItem("%s（%d 步）" % (b["name"], len(b["steps"])))
                self._list.item(self._list.count() - 1).setData(Qt.ItemDataRole.UserRole, b["id"])
        # v2.9.0（B5）：下拉状态**由配置推导**（pet_behaviors.idle_combo_state 是文案与判据
        # 的单一来源），不再硬编码「（不启用 → 默认待机）」——改前配置里明明有 2 条待机动作，
        # 下拉却显示「不启用」，用户点一下就把 2 条覆盖成 1 条（数据损失面）。
        # 多条（或 single 但不止一条）时下拉**只读**：它是「如实显示」，改多条请走旁边的
        # 「待机设置…」（审计给的两个方案里的 (a)：如实显示 + 跳转）。
        _st = pet_behaviors.idle_combo_state(
            _cfg if isinstance(_cfg, dict) else {},
            name_getter=lambda _bid: {b["id"]: b["name"] for b in _behaviors}.get(_bid, ""))
        self._idle_combo.blockSignals(True)
        try:
            self._idle_combo.clear()
            self._idle_combo.setEnabled(_st["mode"] != "list")
            if _st["mode"] == "list":
                self._idle_combo.addItem(_st["label"], "")
                self._idle_combo.setToolTip(
                    "待机列表里有 %d 条动作，顺序/随机/权重请在「待机设置…」里改" % _st["count"])
            else:
                self._idle_combo.setToolTip(
                    "空闲时只播这一条（要让多条轮流/随机，请点「待机设置…」）")
                self._idle_combo.addItem(pet_behaviors.IDLE_COMBO_OFF_LABEL, "")
                for b in _behaviors:
                    self._idle_combo.addItem("空闲时：" + b["name"], b["id"])
                if (_st["mode"] == "single"
                        and self._idle_combo.findData(_st["behavior_id"]) < 0):
                    # 配置指向的行为已经不在库里：也要如实显示（否则界面又比配置更乐观）
                    self._idle_combo.addItem(_st["label"], _st["behavior_id"])
                _found = self._idle_combo.findData(_st["behavior_id"])
                self._idle_combo.setCurrentIndex(_found if _found >= 0 else 0)
        finally:
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

        # v2.9.0（A9/A11/A2）：每次重画都把这两处**可见文字**同步一遍（它们承载的是
        # 「要保存才落盘」「动作会加在哪儿」这两条决定成败的信息）
        self._refresh_state_label()
        self._act_target.setText(self._target_text())
        self._sync_param()

    def _on_sel(self, row):
        if row < 0 or self.svc is None:
            return
        # A5（质量审查 F2）：**换列表条目**同样会丢掉未保存的表单 —— 与关窗是同一种病，
        # 改前这条路静默丢弃（实测 0 弹框）。拒绝时把选中行拨回原来那条，不留
        # 「选中看着变了、内容还是旧的」这种半截状态。
        if not self._confirm_discard(why="switch"):
            _back = self._row_of(self._editing_id)
            self._list.blockSignals(True)
            try:
                self._list.setCurrentRow(_back)
            finally:
                self._list.blockSignals(False)
            return
        _b = self.svc.get(self._list.item(row).data(Qt.ItemDataRole.UserRole))
        if _b is None:
            return
        self._editing_id = _b["id"]
        self._new_state = False     # A11：选中已有行为 = 离开新建态
        self._name.setText(_b["name"])
        self._steps.clear()
        for _st in _b["steps"]:
            _it = QListWidgetItem(self._step_text(_st))
            _it.setData(Qt.ItemDataRole.UserRole, _st)
            self._steps.addItem(_it)
        # A5：载入即基线——之后的改动才算「未保存」
        self._baseline = self._form_signature()
        self._refresh_state_label()

    def _new(self):
        """「新建」按钮：清空表单进入新建态 + 常驻状态标签立刻变成「新建中」。

        v2.9.0（A11/P2-8）：v2.8.0 只发了一次性**气泡**（修法不符）——现在起是表单上方的
        **常驻**标签：新建态一直可见，直到保存或取消。同一个意思不再说两遍（撤掉气泡）。
        """
        self._reset_form()
        self._new_state = True
        self._refresh_state_label()
        self._note("已进入新建态：填好行为名与步骤后点「保存」才会写进库里")

    def _reset_form(self):
        """只清表单（删除成功后复用，不重复发回执）。"""
        self._editing_id = None
        self._new_state = False
        self._name.clear()
        self._steps.clear()
        self._list.setCurrentRow(-1)
        self._baseline = self._form_signature()   # A5：清空即基线（此时没有未保存改动）
        self._refresh_state_label()

    def _del_step(self):
        """「删除选中步骤」：没选中时给提示（takeItem(-1) 是静默的）+ 成功回执。

        v2.8.0 第 6 轮（D11）补了回执，但走的是**宠物气泡**；v2.9.0（A4）改成窗口内
        **状态行**：列表内的连续操作不该弹气泡（气泡覆盖式、无队列，连点时前面的看不见）。
        """
        row = self._steps.currentRow()
        if row < 0:
            _warn(self, "删除步骤", "先在「动作序列」里选中要删的步骤")
            return
        item = self._steps.item(row)
        label = item.text() if item is not None else ""
        self._steps.takeItem(row)
        self._refresh_state_label()
        self._note("已删除步骤%s（点「保存」才落盘）"
                   % ("：%s" % label[:20] if label else ""))

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
        self._steps.setCurrentItem(_it)
        self._steps.scrollToItem(_it)      # 列表长时新步骤会落在视口外（同 N12/N13 口径）
        self._param.clear_text()          # A1：清**输入**（不是清候选）
        self._refresh_state_label()
        # A4：回执走**窗口内状态行**（列表内连续操作不弹宠物气泡——气泡是覆盖式的，
        # 连点时前面的看不见、最后一条还滞留 5 秒）
        self._note("已添加步骤：%s（点「保存」才落盘）" % self._step_text(norm[0])[:28])

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
        # P2-5：静态 getItem 改成手工建框 + modal()
        label, ok = _ask_item(self, "选择台词", "这条行为要读哪句台词：", labels)
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
        # P2-5：静态 getItem 改成手工建框 + modal()
        label, ok = _ask_item(self, "选择对白", "这条行为要读哪段对白：", labels)
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

    def _resolve_name_clash(self, name, allow_overwrite):
        """R3：重名判据 + 问用户（判据的**唯一来源** = pet_behaviors.find_by_name）。

        返回 (mode, name, dup_id)，mode ∈ {"add", "overwrite", "cancel"}：
          · add       → 照常新建（没重名，或用户选了「两条都留」/改了名）
          · overwrite → 覆盖撞上的那条（id 不变，这个窗口转入编辑它）
          · cancel    → 用户取消，调用方**什么都不写**

        服务对象没有 `find_by_name`（老替身 / 外部注入）时按"没有判据"退化、不阻断保存 ——
        这里**绝不自己再算一份判据**：两份判据漂移正是本轮 G3（两处入口语义相反）的病根。
        """
        _find = getattr(self.svc, "find_by_name", None)
        if not callable(_find):
            return "add", name, None
        while True:
            dup = _find(name, exclude_id=self._editing_id)
            if dup is None:
                return "add", name, None
            choice = _ask_name_clash(self, name, dup, allow_overwrite=allow_overwrite)
            if choice == "keep":
                return "add", name, None
            if choice == "overwrite":
                return "overwrite", name, dup.get("id")
            if choice != "rename":
                return "cancel", name, None
            new_name, ok = _ask_text(self, "行为改名",
                                     "已经有一条叫「%s」的行为了，换一个名字：" % name,
                                     default=name)
            new_name = (new_name or "").strip()
            if not ok or not new_name:
                return "cancel", name, None
            name = new_name

    def _save(self, quiet=False):
        """保存表单。返回**是否真的写进库里**（「试播」按它决定播不播，见 B6）。

        quiet=True 时不发「已保存」气泡：「试播」用它——一次用户动作只说一句话，
        而「试播顺带弹一句已保存」会让用户以为这是保存按钮干的（审计 #8）。
        保存**不关窗**（B3 的 R1：面板型），保存完还能接着改。
        """
        if self.svc is None:
            # 审计实测：svc 不可用时点保存是**彻底静默**（warn/info/toast 全空）
            self._note("行为库不可用：这次保存没做（检查数据目录是否可写）")
            return False
        _steps = self._collect_steps()
        # R3（v2.10.0）：重名**不静默** —— 先问用户（覆盖 / 同名并存 / 换个名字 / 取消）。
        # 判据来自 pet_behaviors.find_by_name（唯一来源）；这里只管"问法"与"落法"。
        _overwrote = False
        _mode, _name, _dup_id = self._resolve_name_clash(
            self._name.text().strip(), allow_overwrite=not self._editing_id)
        if _mode == "cancel":
            self._note("已取消：已经有一条叫「%s」的行为了，这一条没有再写进去（库里没动）"
                       % _name)
            return False
        if self._editing_id:
            _ok, _err = self.svc.update(self._editing_id, _name, _steps)
        elif _mode == "overwrite":
            # 覆盖 = 改的是**已有那条**（id 不变）：保存完这个窗口就在编辑它
            # （所以下面必须把 _editing_id 接过去，否则再点一次「保存」会又新建一条）
            _ok, _err = self.svc.update(_dup_id, _name, _steps)
            if _ok:
                self._editing_id = _dup_id
                _overwrote = True
        else:
            _b, _err = self.svc.add(_name, _steps)
            _ok = _b is not None
            if _ok:
                self._editing_id = _b["id"]  # 新建成功后进入编辑态（试播/再保存走 update）
        if not _ok:
            _warn(self, "行为编辑", _err or "保存失败")
            self._note(_err or "保存失败")
            return False
        _saved_id = self._editing_id
        _saved_name = (self.svc.get(_saved_id) or {}).get("name") or self._name.text().strip()
        self._refresh()
        # F-A（独立验收实测）：**基线必须先于 `_select_behavior` 对齐** —— 后者会显式调
        # `_on_sel` → `_confirm_discard(why="switch")`；基线没跟上的话，
        # "刚保存的内容"对上"上一条的旧基线" → 判成脏 → **点一次「保存」反而被问一句
        # 要不要放弃**（这就是用户抱怨的"多一步"，也是最刺眼的一种）。
        self._new_state = False           # A11：保存完就离开新建态（常驻标签随之变「编辑中」）
        self._baseline = self._form_signature()   # A5：保存即新基线（此时没有未保存改动）
        # P1-9：新建时 _row = currentRow() == -1 → 以前既不选中也不滚动，新行为落在列表
        # 末尾看不见（"保存了像没保存"）。现在按 id 定位新条目并滚到可见处。
        self._select_behavior(_saved_id)
        self._refresh_state_label()
        if _overwrote:
            self._note("行为「%s」已保存：覆盖了同名的旧条目（id 没变，可以直接「试播」）"
                       % _saved_name)
            if not quiet:
                _toast(self.pet, "已覆盖行为「%s」（同名的旧内容被这一份替换了）" % _saved_name)
        else:
            self._note("行为「%s」已保存（已在库里；可以接着改，或者点「试播」看一遍）"
                       % _saved_name)
            if not quiet:
                _toast(self.pet, "行为「%s」已保存" % _saved_name)
        return True

    def _select_behavior(self, bid):
        """按 id 选中并滚到可见处（正例照抄 AlarmDialog._save）。返回是否找到。"""
        if not bid:
            return False
        for _i in range(self._list.count()):
            _it = self._list.item(_i)
            if _it.data(Qt.ItemDataRole.UserRole) == bid:
                # 程序化选中**不走**未保存确认（_save/_import 之后表单与新条目本来就一致，
                # 走信号会被误判成脏 → 保存完反而弹一个"要不要放弃"）；显式重载一次表单。
                self._list.blockSignals(True)
                try:
                    self._list.setCurrentRow(_i)
                finally:
                    self._list.blockSignals(False)
                self._list.scrollToItem(_it)
                self._on_sel(_i)
                return True
        return False

    def _delete(self):
        _row = self._list.currentRow()
        if _row < 0 or self.svc is None:
            _warn(self, "删除行为", "先在列表里选中一个行为")
            return
        _bid = self._list.item(_row).data(Qt.ItemDataRole.UserRole)
        _b = self.svc.get(_bid) or {}
        _label = _b.get("name") or str(_bid)
        # P1-3：这里以前**没有二次确认**（同仓 _confirm 到处都用）——点一下就永久删掉，
        # 而且成功后没有任何"已删除"回执。
        if not _confirm(self, "删除行为",
                        "确定删除行为「%s」吗？\n删除后无法撤销（它的步骤会一起没）。" % _label):
            return
        _ok, _err = self.svc.delete(_bid)
        if not _ok:
            _warn(self, "行为编辑", _err or "删除失败")
            return
        # B4：**真的**清掉待机列表里对它的引用。
        # 改前这里判的是 cfg["idle_behavior"]（pet_config.normalize_cfg 每次加载都把它置空）
        # → 恒不命中的**死分支**；实测删掉被待机列表引用的行为后 idle_actions 原样残留，
        # 待机设置里留一条「（行为已删除：xxx）」。清理逻辑走 pet_behaviors 的单一来源。
        _cfg = getattr(self.pet, "cfg", None)
        _removed, _cerr = pet_behaviors.remove_idle_actions_for_behavior(_cfg, _bid)
        if _removed:
            self._save_cfg(_cfg)
        self._reset_form()
        self._refresh()
        _toast(self.pet, "已删除行为「%s」" % _label)
        if _removed:
            # 这条不是重复回执：它说的是**另一个事实**（这次删除顺带动了待机设置），
            # 用户不看到它，就会在待机设置里发现「少了一条」而不知道是谁干的。
            self._note("已同时从待机列表里移除 %d 条引用（它不会再被待机播到）" % len(_removed))
        elif _cerr:
            self._note("行为删掉了，但待机列表没清成：%s" % _cerr)

    def _test_play(self):
        """先保存再试播；**保存失败就不播**（B6 / 审计 #8）。

        改前：保存失败（比如行为名非法）仍然调 _run_behavior → 播的是**上次保存的旧内容**
        （_editing_id 还指向上一次成功保存的那条），用户以为在试播自己的修改。
        规则本身在 pet_behaviors.test_play_target 里（单一来源，逻辑侧用例钉它）：
        这里只负责「把结论放到内联状态行」与「调真正的播放器」。
        保存走 quiet=True：这次用户动作的回执只有一句（不再顺带弹「已保存」）。
        """
        _ok = self._save(quiet=True)
        _bid, _why = pet_behaviors.test_play_target(_ok, self._editing_id)
        if _bid is None:
            self._note(_why)
            return
        _runner = getattr(self.pet, "_run_behavior", None)
        if _runner is not None:
            self._note("正在试播「%s」（内容 = 刚保存的这一份）"
                       % ((self.svc.get(_bid) or {}).get("name") or ""))
            _runner(_bid)

    def _import(self):
        """A7：按钮只认行为文件（.json），选错了给**人话**原因。

        审计 A.1-P3 实测：文件框过滤器写死「行为 JSON (*.json)」，用户强选一张 PNG →
        界面弹出 `'utf-8' codec can't decode byte 0x89 in position 0`（英文异常）。
        两层防护：① 选完先在对话框层按扩展名预检（到这一步都还没碰库）；
        ② 真进了库还失败（比如 .json 里装的是别的东西）→ 把原因翻成人话再显示。
        """
        if self.svc is None:
            self._note("行为库不可用：这次导入没做")
            return
        _path, _f = QFileDialog.getOpenFileName(self, "导入行为文件", "", "行为文件 (*.json)")
        if not _path:
            return
        _ext = os.path.splitext(str(_path))[1].lower()
        if _ext != ".json":
            _msg = ("这个文件不是行为文件（%s）。行为设置只导入 .json —— "
                    "想用图片做动作，请点「＋导入图片做动作…」。" % (_ext or "没有扩展名"))
            _warn(self, "导入行为", _msg)
            self._note(_msg)
            return
        _b, _err = self.svc.import_file(_path)
        if _b is None:
            _msg = _human_import_error(_err, _path)   # A7：不把英文异常端给用户
            _warn(self, "导入行为", _msg)
            self._note(_msg)
            return
        self._refresh()
        self._select_behavior(_b.get("id"))
        _toast(self.pet, "已导入行为「%s」" % (_b.get("name") or _b.get("id", "")))

    def _export(self):
        _row = self._list.currentRow()
        if _row < 0 or self.svc is None:
            # E3/P1-2：未选中时以前直接静默 return，连"先选中一个"都不说
            _info(self, "导出行为", "先在列表里选中一个行为，再点「导出…」")
            return
        _bid = self._list.item(_row).data(Qt.ItemDataRole.UserRole)
        _path, _f = QFileDialog.getSaveFileName(self, "导出行为资源", "", "行为 JSON (*.json)")
        if not _path:
            return
        _ok, _err = self.svc.export_file(_bid, _path)
        if not _ok:
            _warn(self, "行为编辑", _err or "导出失败")
            return
        # E3/P1-2：成功路径以前**没有任何分支**——选完保存路径后窗口零变化，用户完全
        # 不知道导出成没成（这是"导出像没效果"最纯粹的一例）。
        _toast(self.pet, "行为已导出到 %s" % os.path.basename(_path))


# ---------------- v2.0.5：闹钟 ----------------
class AlarmDialog(_DiscardGuard, _FitDialog):
    """闹钟设置：列表 + 新建/编辑/删除 + 自定义铃声（wav/mp3）+ 启用开关 + 试听。

    v2.9.0（质量审 F1 / 兼容审）：它和 BehaviorDialog 一样是**面板型**（保存不关窗、
    表单有暂存态 `_pending_ringtone`），但第二枚按钮当时还叫「关闭」且丢弃草稿零提示 ——
    R4 点名的硬反例。现在改叫「取消」并混入 `_DiscardGuard`（无改动直接关，零额外一步）。
    """

    DEFAULT_TIME = QTime(7, 30)  # 新建闹钟默认时间（唯一来源）

    def __init__(self, pet, svc=None):
        super().__init__(pet)
        self.pet = pet
        self.svc = svc or getattr(pet, "alarms", None)
        self._editing_id = None
        self._pending_ringtone = ""  # 本次导入的新铃声文件名（保存时写入）
        self._ring_dirty = False
        self._baseline = None        # A5：打开时的表单指纹（_refresh 之后填）
        self.setWindowTitle("闹钟")
        self.setStyleSheet(DIALOG_QSS)
        clamp_dialog(self, 540, 470)   # v2.5.0 B
        lay = scroll_content(self)   # v2.5.0 B：内容区可滚动
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
        # v2.9.0（R4）：第二枚按钮执行的是「丢弃未保存编辑 + 关窗」，叫「关闭」是标签在
        # 说谎 —— 改名「取消」并走 _cancel（有未保存改动时先问一次；没改动直接关）。
        for _lbl, _cb in (("新建", self._new), ("保存", self._save),
                          ("删除", self._delete), ("取消", self._cancel)):
            _b = QPushButton(_lbl)
            _b.clicked.connect(_cb)
            _btn_tip(_b, _lbl)         # P3-6：新建/添加各一套措辞
            btn_row.addWidget(_b)
        stick_buttons(self, btn_row)   # v2.5.0 B：按钮行在滚动区之外
        self._time.setTime(self.DEFAULT_TIME)  # 打开即显示默认 07:30（点「新建」同款）
        self._refresh()
        self._baseline = self._form_signature()   # A5：打开即基线（此时没有未保存改动）

    # ---------- A5：未保存判据（与 BehaviorDialog 同一套口径，见 _DiscardGuard） ----------
    def _form_signature(self):
        """当前草稿的指纹：时间 / 文案 / 启用 / 待写入的铃声。"""
        return (self._time.time().toString("HH:mm"), self._label.text().strip(),
                bool(self._ck_enabled.isChecked()), str(self._pending_ringtone or ""))

    def _discard_prompt(self, why="close"):
        if why == "switch":
            return ("表单里还有没保存的闹钟草稿（时间/文案/铃声）。\n"
                    "点「确定」= 放弃它、切到另一个闹钟；点「取消」= 留在这一条接着改。")
        return ("表单里还有没保存的闹钟草稿（时间/文案/铃声）。\n"
                "点「确定」= 放弃它并关窗；点「取消」= 回去接着改。")

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
        # A5（与 BehaviorDialog 同一种病，同一轮修）：换列表条目也会丢草稿 —— 拒绝时
        # 把选中行拨回原来那条，不留「选中看着变了、内容还是旧的」。
        if not self._confirm_discard(why="switch"):
            _back = self._row_of(self._editing_id)
            self._list.blockSignals(True)
            try:
                self._list.setCurrentRow(_back)
            finally:
                self._list.blockSignals(False)
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
        self._baseline = self._form_signature()   # A5：载入即基线

    def _new(self):
        """「新建」按钮：清空表单进入新建态 + 一句即时回执。

        v2.8.0 第 6 轮：闹钟这处此前**漏了**——表单本来就处于默认状态时（首次打开、刚保存完、
        刚删完），点「新建」屏幕上零变化，与第 5 轮修掉的 N2/N5 是同一族（那里用气泡解决的）。
        """
        self._reset_form()
        _toast(self.pet, "已进入新建态：选好时间、填好名字，点「保存」才会加上")

    def _reset_form(self):
        """只清表单（删除成功后复用，**不**重复发回执——一次用户动作只说一句话）。"""
        self._editing_id = None
        self._time.setTime(self.DEFAULT_TIME)
        self._label.clear()
        self._ck_enabled.setChecked(True)
        self._pending_ringtone = ""
        self._ring_dirty = True  # 新建：保存时把「默认提示音」作为初始值落盘（add 走 ringtone=""）
        self._ring_label.setText("（默认提示音）")
        self._list.setCurrentRow(-1)
        self._baseline = self._form_signature()   # A5：清空即基线（点「新建」后关窗不该问）

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
        # F-A（独立验收实测）：**基线必须先于 `_on_sel` 对齐** —— 后者会走
        # `_confirm_discard(why="switch")`；基线没跟上的话，「刚保存的内容」
        # 对上"上一条的旧基线" → 判成脏 → **点一次「保存」反而被问一句要不要放弃**。
        self._baseline = self._form_signature()   # A5：保存即新基线
        # 恢复选中到刚保存的闹钟（_on_sel 回填保存后的规范化值，表单状态干净）
        # A5：程序化选中**不许**触发未保存确认（保存完表单与新条目一致，走信号会误判成脏）
        for _i in range(self._list.count()):
            if self._list.item(_i).data(Qt.ItemDataRole.UserRole) == _saved_id:
                self._list.blockSignals(True)
                try:
                    self._list.setCurrentRow(_i)
                finally:
                    self._list.blockSignals(False)
                self._list.scrollToItem(self._list.item(_i))
                self._on_sel(_i)
                break
        _toast(self.pet, "闹钟已保存~（到点气泡提醒）")

    def _delete(self):
        _row = self._list.currentRow()
        if _row < 0 or self.svc is None:
            # 未选中/无服务 = 空操作。**不许**在这里补 _warn：
            # tests/test_dialogs_more_v24.py::test_alarm_dialog_update_failure_and_delete_
            # without_selection 明确断言"未选中删除不该弹提示"（既有断言不动）。
            return
        _aid = self._list.item(_row).data(Qt.ItemDataRole.UserRole)
        _a = self.svc.get(_aid)
        _tlabel = ("「%s」%s" % (_a.get("label"), _a.get("time"))) if _a else "这个闹钟"
        if not _confirm(self, "闹钟", "删除 %s 吗？" % _tlabel):
            return
        _ok, _err = self.svc.delete(_aid)
        if not _ok:
            _warn(self, "闹钟", _err or "删除失败")
            return
        self._reset_form()          # 静默清表：回执由下面这一句给（不许一次动作两句）
        self._refresh()
        _toast(self.pet, "已删除闹钟 %s" % _tlabel)


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


class AISettingsDialog(_FitDialog):
    """AI 接口/模型/人设/回复长度设置（P1-10，OpenAI 兼容，支持本地 Ollama）。

    v2.0.4：服务商预设（一键填地址/模型）+ 连通性测试（错误归类中文提示）。"""

    def __init__(self, parent=None):
        super().__init__(_qt_parent(parent))
        self._pet = parent
        self._worker = None
        self.setWindowTitle("AI 设置")
        self.setStyleSheet(DIALOG_QSS)
        clamp_dialog(self, 560, 560)   # v2.5.0 B
        cfg = _get(parent, "cfg") or {}
        root = scroll_content(self)   # v2.5.0 B：内容区可滚动
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
        # v2.11.0（B5 · 只补"决定成败"的那两处，不铺开）：测试用的是**当前填写的**参数，
        # 而且它**不改配置**——用户很容易把它当成"保存"。tooltip 只作补充，同一句话在
        # 窗口底部还有一行常驻小字（见 _save_note），保证不悬停也看得到。
        self._test_btn.setToolTip("用当前填写的地址/模型/Key 试一次能不能通；"
                                  "它只测不改配置——要让改动生效还得点「保存」。")
        self._test_label = QLabel("")
        self._test_label.setWordWrap(True)
        test_row.addWidget(self._test_btn)
        test_row.addWidget(self._test_label, 1)
        root.addLayout(test_row)
        root.addWidget(QLabel("人设预设（选「自定义」可完全自己写）"))
        self._persona = QComboBox()
        # v2.3.0：人设列表由桌宠给（内置 + prompts/custom/*.txt）；拿不到就回退内置四项
        _choices = _call(parent, "persona_choices")
        if not _choices:
            _choices = [("default", "内置大肥鱼（又娇又赖，默认）"),
                        ("sheshe", "啥子蛇（毒舌腹黑「本专员」）"),
                        ("tsundere", "傲娇系（嘴硬心软）"),
                        ("custom", "自定义（自己写人设）")]
        for _pid, _label in _choices:
            self._persona.addItem(str(_label), str(_pid))
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
        # v2.3.0（1.2 Function Calling）：工具调用开关 + 写入确认开关
        self._tools = QCheckBox("允许 AI 主动调用工具（查余额/天气/记账/闹钟/表情）")
        self._tools.setChecked(bool(cfg.get("ai_tools_enabled", True)))
        root.addWidget(self._tools)
        self._tools_confirm = QCheckBox("写入类操作先问我（记账/预算/闹钟/定时提醒）")
        self._tools_confirm.setChecked(bool(cfg.get("ai_tools_confirm", True)))
        self._tools_confirm.setEnabled(self._tools.isChecked())
        self._tools.toggled.connect(self._tools_confirm.setEnabled)
        root.addWidget(self._tools_confirm)
        _tool_hint = QLabel("本地模型（Ollama 等）不支持工具调用，会自动退化为纯聊天。")
        _tool_hint.setWordWrap(True)
        root.addWidget(_tool_hint)
        # v2.4：隐私开关 ai_rag_enabled 此前**有配置键、没有界面入口**——README 与
        # v2.3.0 发布说明都写着"AI 设置里可关"，但本对话框既不展示也不提交该键，
        # 用户实际关不掉它（保存一次还会把旧值原样留在配置里）。这里补齐控件并纳入 _save。
        self._rag = QCheckBox("把记账摘要与长期记忆随对话发给 AI（取消勾选 = 完全不注入）")
        self._rag.setChecked(bool(cfg.get("ai_rag_enabled", True)))
        root.addWidget(self._rag)
        _rag_hint = QLabel("关掉后只发对话本身：今日消费、近 7 天、预算占比、余额、城市，"
                           "以及称呼/喜好/近况都不会进请求。")
        _rag_hint.setWordWrap(True)
        root.addWidget(_rag_hint)
        # v2.3.0（1.1/兼容 M2）：长期记忆的查看/清除入口——此前"清理日志"的提示让用户来这里，
        # 但这里根本没有这个控件（长期记忆无法在应用内删除）
        _lt_row = QHBoxLayout()
        _lt_btn = QPushButton("清除长期记忆（称呼/别名/喜好/不喜欢/近况）")
        _lt_btn.clicked.connect(self._clear_long_term)
        _lt_row.addWidget(_lt_btn)
        _lt_row.addStretch(1)
        root.addLayout(_lt_row)
        _lt_hint = QLabel("长期记忆存在 memory.json 的 long_term 段，与对话历史分开；"
                          "「清理日志」只清对话历史，不会动它。")
        _lt_hint.setWordWrap(True)
        root.addWidget(_lt_hint)
        # v2.11.0（B5）：**决定成败的那句话放在窗口里看得见的地方，而不是只写进 tooltip**。
        # 这一页改了地址/模型/人设/开关，全都要点「保存」才生效，点「取消」/关窗会丢掉本次改动；
        # 而「测试连接」只按当前填写的值试一次（不改配置）。审计的原话是"关键信息只写在 tooltip
        # 里＝等于没写"（tooltip 不可发现、键盘/触屏没有 hover）——所以这里是**常驻一行小字**，
        # 挂在滚动区之外（和按钮行一起），滚到哪儿都看得见；tooltip 只是同一句话的补充。
        self._save_note = QLabel("这一页改的东西点了「保存」才生效；点「取消」或直接关窗会丢掉"
                                 "本次改动。「测试连接」只按当前填写的地址与模型试一次，不改配置。")
        self._save_note.setWordWrap(True)
        # 外层布局由上面的 scroll_content(self) 建好（它自己 QVBoxLayout(dlg)），这里只往上挂；
        # **不写 QVBoxLayout(self) 兜底**：那正是 v2.5.0 B 的护栏禁止的"裸顶层布局"
        # （tests/test_dialog_fit_v250.py::test_pet_dialogs里没有裸顶层布局也没有写死resize）。
        _outer_lay = self.layout()
        if _outer_lay is not None:
            _outer_lay.addWidget(self._save_note)
        btns = QHBoxLayout()
        ok = QPushButton("保存")
        cancel = QPushButton("取消")
        ok.setDefault(True)
        ok.clicked.connect(self._save)
        cancel.clicked.connect(self.reject)
        ok.setToolTip("把这一页的改动写进配置、立即生效（窗口关闭）。")
        cancel.setToolTip("丢掉本次改动关窗；配置保持原样。")
        # v2.7.0 第 5 轮（P1-1）：保存失败时的**非模态**状态行——窗口不关，原因就在按钮旁边
        self._save_hint = QLabel("")
        self._save_hint.setWordWrap(True)
        self._save_hint.setStyleSheet("color:#ff8080;")
        btns.addWidget(self._save_hint, 1)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        stick_buttons(self, btns)   # v2.5.0 B：按钮行在滚动区之外

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

    def _clear_long_term(self):
        """v2.3.0（1.1/兼容 M2）：清除长期记忆（memory.json 的 long_term 段，对话历史保留）。

        v2.9.0（A11/D16）：改走统一口径 _confirm / _info / _warn —— 裸 QMessageBox.question
        / information / warning 不带 DIALOG_QSS（深色主题下与别处不一致），也不进 modal()
        （拿不到置顶 + 抢焦点）。**确认语义一字不动**：不可撤销 ⇒ 这个确认该有。
        既有用例的驱动方式同步改成给 _confirm/_info/_warn 注入替身（**加强式**：从
        「monkeypatch 静态方法」改成驱动真入口，断言一条没减）。
        """
        if not _confirm(self, "清除长期记忆",
                        "确定要让它忘掉你的称呼、别名、喜好、不喜欢和近况吗？\n"
                        "（对话历史不受影响；此操作不可撤销）"):
            return
        ok = _call(self._pet, "clear_long_term_memory")
        if ok:
            _info(self, "清除长期记忆", "已经忘掉啦~")
        else:
            _warn(self, "清除长期记忆", "清除失败，详情见 error.log")

    def _save(self):
        data = {
            "ai_base_url": self._base.text().strip().rstrip("/"),
            "ai_model": self._model.text().strip() or pet_chat.DEFAULT_MODEL,
            "ai_persona": self._persona.currentData() or "default",
            "ai_system_prompt": self._prompt.toPlainText().strip(),
            "ai_reply_len": self._reply.value(),
            "ai_max_tokens": self._tokens.value(),
            "ai_tools_enabled": self._tools.isChecked(),
            "ai_tools_confirm": self._tools_confirm.isChecked(),
            "ai_rag_enabled": self._rag.isChecked(),  # v2.4：隐私开关（此前只有键没有入口）
        }
        ok, msg, explicit = _apply_call(self._pet, "apply_ai_settings", data, strict=True)
        if not ok:
            # P1-1：以前丢弃返回值 + 无条件 accept()——人设正文/API 地址/模型/工具开关
            # 整批静默丢失，窗口照常关闭 = "保存成功"假象。现在失败就**不关窗**。
            _save_failed(self, "AI 设置", msg, explicit)
            return
        self.accept()
        _toast(self._pet, msg or "AI 设置已更新~")


class RolePanel(QWidget):
    """角色列表 + 预览 + 导入 / 设为当前 / 删除 / 恢复默认。"""

    def __init__(self, parent=None):
        super().__init__(_qt_parent(parent))
        self._pet = parent
        self._lib = _get(parent, "role_lib")
        self.setStyleSheet(DIALOG_QSS)

        root = scroll_content(self)   # v2.5.0 B：面板内容也可滚动（不再顶大容器的最小尺寸）
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
            _warn(self._parent_widget(), "切换角色", "先在列表里选中一个角色")
            return
        rid = it.data(Qt.ItemDataRole.UserRole)
        if not rid:
            return
        _name = (self._lib.get(rid) or {}).get("name") or rid
        if hasattr(self._pet, "apply_role"):
            # S22：以前丢弃返回值——失败只在 error.log 里，界面上只有 "[当前]" 标记动了
            ok, msg, explicit = _apply_call(self._pet, "apply_role", rid)
            if not ok:
                _save_failed(self._parent_widget(), "切换角色", msg, explicit)
                return
        elif not self._lib.set_active(rid):
            _warn(self._parent_widget(), "切换角色", "切换失败")
            return
        self._refresh()
        _toast(self._pet, "已切换到角色「%s」" % _name)

    def _delete(self):
        if self._lib is None:
            return
        it = self._list.currentItem()
        if it is None:
            _warn(self._parent_widget(), "删除角色", "先在列表里选中一个角色")
            return
        rid = it.data(Qt.ItemDataRole.UserRole)
        if not rid:
            return
        role = self._lib.get(rid) or {}
        _name = role.get("name") or rid
        if not _confirm(self._parent_widget(), "删除角色",
                        "确定删除角色「%s」吗？删除后无法撤销。" % _name):
            return
        ok, err = self._lib.delete(rid)
        if not ok:
            _warn(self._parent_widget(), "删除角色", err or "删除失败")
            return
        self._refresh()
        _call(self._pet, "apply_role", self._lib.active_id())
        _toast(self._pet, "已删除角色「%s」" % _name)

    def _reset_default(self):
        if self._lib is None:
            return
        if hasattr(self._pet, "apply_role"):
            # S23：以前丢弃返回值，成功也只是标记移动、失败全静默
            ok, msg, explicit = _apply_call(self._pet, "apply_role", "")
            if not ok:
                _save_failed(self._parent_widget(), "恢复默认角色", msg, explicit)
                return
        else:
            self._lib.set_active("")
        self._refresh()
        _toast(self._pet, "已恢复默认角色")

    def select_role(self, rid):
        """选中某个角色（给「动作」页签的「定位到所属角色」用）。返回是否找到。

        为什么用方法而不是让调用方自己遍历列表：列表是**本面板**的控件，行的 data 里
        存的是什么也只有这里知道（换个地方再写一遍 = 两处口径）。
        """
        rid = str(rid or "")
        if not rid:
            return False
        for i in range(self._list.count()):
            it = self._list.item(i)
            if it is not None and it.data(Qt.ItemDataRole.UserRole) == rid:
                self._list.setCurrentItem(it)
                self._list.scrollToItem(it)
                return True
        return False


# ---------------- b) 音效面板 ----------------
class SoundPanel(QWidget):
    """音效片段列表（试听 / 导入 / 重命名 / 删除）+ 自定义音效组 5 行槽位。"""

    def __init__(self, parent=None):
        super().__init__(_qt_parent(parent))
        self._pet = parent
        self._lib = _get(parent, "audio_lib")
        self.setStyleSheet(DIALOG_QSS)

        root = scroll_content(self)   # v2.5.0 B：面板内容可滚动
        root.addWidget(QLabel("音效片段（自定义音效素材）"))
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
        # S16：以前返回值被丢弃（apply_sound_group 自己 try/except 只写日志）→ 静默
        # v2.7.0 第 5 轮（L2-1）：**strict=True**。改前这里按老契约（None = 成功）判，
        # 而桌宠.apply_sound_group 内部吞异常只写日志、还丢掉 save_config 的返回值 → 一律
        # 回 None → `if not ok` 是死代码、下面的成功气泡**无条件**执行：底层抛异常时
        # 用户看到的仍是「音效组已更新~」（假成功）。生产端已同步改成返回 (ok, msg)。
        ok, msg, explicit = _apply_call(self._pet, "apply_sound_group",
                                        self._lib.group_paths(), strict=True)
        if not ok:
            _save_failed(self._parent_widget(), "音效组", msg, explicit)
            return
        _toast(self._pet, "音效组已更新~")

    # ---------- 动作 ----------
    def _preview_selected(self):
        if self._lib is None:
            return
        it = self._list.currentItem()
        if it is None:
            _warn(self._parent_widget(), "试听", "先在列表里选中一个音效片段")
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
        # N7/P1-9：新片段落在列表末尾，以前既不选中也不滚动、也没有任何提示
        self._select_fragment(frag.get("id"))
        _toast(self._pet, "已导入音频「%s」" % (frag.get("name") or ""))

    def _rename(self):
        if self._lib is None:
            return
        it = self._list.currentItem()
        if it is None:
            _warn(self._parent_widget(), "重命名", "先在列表里选中一个音效片段")
            return
        fid = it.data(Qt.ItemDataRole.UserRole)
        f = None
        for x in self._lib.fragments():
            if x["id"] == fid:
                f = x
                break
        if f is None:
            _warn(self._parent_widget(), "重命名", "这个片段已经不在库里了，刷新一下再试")
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
            # S2/P2-3：以前空名静默 return——用户删光名字点确定，什么都没发生
            _warn(self._parent_widget(), "重命名", "名字不能为空")
            return
        ok, err = self._lib.rename(fid, name)
        if not ok:
            _warn(self._parent_widget(), "重命名", err or "重命名失败")
            return
        self._refresh()
        self._select_fragment(fid)
        _toast(self._pet, "已重命名为「%s」" % name)

    def _delete_audio(self):
        if self._lib is None:
            return
        it = self._list.currentItem()
        if it is None:
            _warn(self._parent_widget(), "删除音频", "先在列表里选中一个音效片段")
            return
        fid = it.data(Qt.ItemDataRole.UserRole)
        f = None
        for x in self._lib.fragments():
            if x["id"] == fid:
                f = x
                break
        if f is None:
            _warn(self._parent_widget(), "删除音频", "这个片段已经不在库里了，刷新一下再试")
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
        _toast(self._pet, "已删除音效片段「%s」" % f["name"])

    def _select_fragment(self, fid):
        """按 id 选中并滚到可见处（新建/重命名后的落点反馈）。返回是否找到。"""
        if not fid:
            return False
        for _i in range(self._list.count()):
            _it = self._list.item(_i)
            if _it.data(Qt.ItemDataRole.UserRole) == fid:
                self._list.setCurrentRow(_i)
                self._list.scrollToItem(_it)
                return True
        return False


# ---------------- c) 资源管理对话框 ----------------
class VoiceAssetPanel(QWidget):
    """v2.1：声音素材（参考音）管理——与音效片段**分开**管理，专供声音克隆。

    导入 / 试听 / 重命名 / 删除；显示被哪些角色绑定（绑定在语音设置里改）。"""

    def __init__(self, parent=None):
        super().__init__(_qt_parent(parent))
        self._pet = parent
        self._lib = _get(parent, "voice_assets")
        self.setStyleSheet(DIALOG_QSS)

        root = scroll_content(self)   # v2.5.0 B：面板内容可滚动
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
        # N8：新素材落在列表末尾，以前只有"共 N 个"这行字变化，既不选中也不滚动
        self._select_asset(asset.get("id"))
        _toast(self._pet, "已导入参考音「%s」" % (asset.get("name") or ""))

    def _select_asset(self, sid):
        """按 id 选中并滚到可见处（新建/重命名后的落点反馈）。返回是否找到。"""
        if not sid:
            return False
        for _i in range(self._list.count()):
            _it = self._list.item(_i)
            if _it.data(Qt.ItemDataRole.UserRole) == sid:
                self._list.setCurrentRow(_i)
                self._list.scrollToItem(_it)
                return True
        return False

    def _rename(self):
        sid = self._selected()
        if not sid or self._lib is None:
            _warn(self._parent_widget(), "重命名", "先在列表里选中一个声音素材")
            return
        cur = self._lib.get_asset(sid) or {}
        # P2-5：静态 getText 改成手工建框 + modal()（前台锁口径与 SoundPanel._rename 一致）
        name, ok = _ask_text(self._parent_widget(), "重命名声音素材", "新名字：",
                             cur.get("name", ""))
        if not ok:
            return
        res = self._lib.rename(sid, name)
        if res[0] is False:
            _warn(self._parent_widget(), "重命名失败", res[1] or "重命名失败")
            return
        self._refresh()
        self._select_asset(sid)
        _toast(self._pet, "已重命名为「%s」" % (res[1] or cur.get("name", "")))

    def _delete_asset(self):
        sid = self._selected()
        if not sid or self._lib is None:
            _warn(self._parent_widget(), "删除声音素材", "先在列表里选中一个素材")
            return
        cur = self._lib.get_asset(sid) or {}
        _name = cur.get("name", sid)
        if not _confirm(self._parent_widget(), "删除声音素材",
                        "删除「%s」吗？台词里引用它的地方会变成失效引用（会明确提示，不会静默）。"
                        % _name):
            return
        res = self._lib.delete(sid)
        if res[0] is False:
            _warn(self._parent_widget(), "删除失败", res[1] or "删除失败")
            return
        self._refresh()
        _toast(self._pet, "已删除声音素材「%s」" % _name)


# ---------------- c) 「动作」页签（v2.12.0 · F1 / 审计 §12.5 第 4 条） ----------------
class ActionPanel(QWidget):
    """资源管理第 4 页签「动作」：**纯视图** —— 角色 → 形态 → 动作。

    口径（_dev/audit_behavior_assets_v290.md §E.4 第 4 条）：
      只读列表 +「删除」+「定位到所属角色」，列「角色 → 形态 → 动作（帧 N 张 / 合成 类型·幅度·周期）」。
      **不新建库、不搬数据**：数据全部从既有索引读（roles.json → forms[i].animations / procs），
      本页签只做展示与两件就地动作（删一条动作、跳到所属角色）。

    为什么值得有：审计 §E.2 实测「动作（帧/合成）没有资源视图」—— 用户无法回答
    "我到底有哪些动作 / 它们挂在哪个角色哪个形态上"（角色编辑里只看得到**当前形态**）。
    """

    def __init__(self, parent=None, locate=None):
        super().__init__(_qt_parent(parent))
        self._pet = parent
        self._lib = _get(parent, "role_lib")
        self._locate = locate          # 定位到所属角色：由 ResourceManagerDialog 提供（切页签+选中）
        self.setStyleSheet(DIALOG_QSS)

        root = scroll_content(self)   # v2.5.0 B：面板内容也可滚动
        root.addWidget(QLabel("所有角色形态上的**自定义动作**（只读清单；内建动作 "
                             "idle/eat/poke/sleep 不在这里）。选中一条可以删除它，"
                             "或定位到它所属的角色。"))
        self._tree = QTreeWidget()
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(["角色 → 形态 → 动作", "类型", "详情"])
        self._tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)  # 只读
        self._tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._tree.setRootIsDecorated(True)
        root.addWidget(self._tree, 1)
        # 状态行：本页签的回执/解释都写这里（不新开气泡、不弹框——"没选中"在纯视图里不是错误）
        self._hint = QLabel("")
        self._hint.setWordWrap(True)
        root.addWidget(self._hint)
        row = QHBoxLayout()
        self._btn_del = QPushButton("删除动作")
        self._btn_del.clicked.connect(self._delete_action)
        self._btn_locate = QPushButton("定位到所属角色")
        self._btn_locate.clicked.connect(self._locate_role)
        row.addWidget(self._btn_del)
        row.addWidget(self._btn_locate)
        row.addStretch(1)
        root.addLayout(row)
        self._refresh()

    # ---------- 数据 ----------
    def _roles(self):
        """[(role_id, name, [form...])]；角色库不可用 → []（并留痕，不静默）。"""
        out = []
        if self._lib is not None:
            try:
                for r in self._lib.list_roles():
                    out.append((r["id"], r.get("name") or r["id"], list(r.get("forms") or [])))
            except Exception as e:
                pet_log.log_error("action panel roles read failed: %r" % (e,))
                out = []
        return out

    def _refresh(self):
        """重建整棵树。默认角色也列一行 —— 审计 §E.2 的「默认角色不能加动作且**不说明**」，
        说明就放在它这一行（它用的是随包 assets/，本来就不该有自定义动作）。"""
        self._tree.clear()
        n_roles = 0
        n_acts = 0
        for rid, name, forms in self._roles():
            top = QTreeWidgetItem(["%s（%s）" % (name, rid), "角色", "%d 个形态" % len(forms)])
            top.setData(0, Qt.ItemDataRole.UserRole, None)   # 角色/形态行不是动作，不能删
            self._tree.addTopLevelItem(top)
            n_roles += 1
            for fi, fm in enumerate(forms):
                acts = self._form_actions(fm)
                node = QTreeWidgetItem(["形态 %d：%s" % (fi + 1, fm.get("name") or ""),
                                        "形态", "%d 个自定义动作" % len(acts)])
                node.setData(0, Qt.ItemDataRole.UserRole, None)
                top.addChild(node)
                if not acts:
                    empty = QTreeWidgetItem(["—（这个形态没有自定义动作）", "", ""])
                    empty.setData(0, Qt.ItemDataRole.UserRole, None)
                    node.addChild(empty)
                    continue
                for act in acts:
                    leaf = QTreeWidgetItem([act["name"], act["kind_label"], act["detail"]])
                    leaf.setData(0, Qt.ItemDataRole.UserRole,
                                 (rid, fi, act["name"], act["kind"]))
                    node.addChild(leaf)
                    n_acts += 1
            top.setExpanded(n_roles == 1)   # 默认只展开第一个角色，其余折叠
        self._tree.addTopLevelItem(self._default_role_node())
        self._tree.resizeColumnToContents(0)
        self._hint.setText("共 %d 个角色、%d 条自定义动作（只读清单；"
                           "「删除动作」会立刻写回角色索引，帧文件本身不删）" % (n_roles, n_acts))

    def _default_role_node(self):
        """默认角色那一行：它不在 roles.json 里，所以动作恒为空 —— 把原因写出来。"""
        top = QTreeWidgetItem(["默认角色", "角色", "随包素材，不能加动作"])
        top.setData(0, Qt.ItemDataRole.UserRole, None)
        why = QTreeWidgetItem(["默认角色用的是随包的 assets/ 素材（不在角色库里），"
                               "所以没有自定义动作，也不能在这里加", "", ""])
        why.setData(0, Qt.ItemDataRole.UserRole, None)
        top.addChild(why)
        return top

    @staticmethod
    def _form_actions(fm):
        """单个形态的自定义动作 → [{"name", "kind", "kind_label", "detail"}]。

        与 RoleLibrary.custom_actions() 同一口径：帧动作 = animations 里非内建键，
        合成动作 = procs。详情按审计给的三样写：帧 N 张 / 合成 类型·幅度·周期。
        """
        out = []
        for act, frames in (fm.get("animations") or {}).items():
            if act in pet_resources.ANIM_ACTIONS:
                continue
            out.append({"name": act, "kind": "frames", "kind_label": "帧",
                        "detail": "帧 %d 张" % len(frames or [])})
        for name, p in sorted((fm.get("procs") or {}).items()):
            p = p if isinstance(p, dict) else {}
            out.append({"name": name, "kind": "proc", "kind_label": "合成",
                        "detail": "合成 %s · 幅度 %s · 周期 %sms"
                                  % (p.get("kind") or "?", p.get("amp"), p.get("period_ms"))})
        return out

    def _selected(self):
        """选中的**动作叶子** → (rid, form_idx, name, kind)；选中的不是动作 → None。"""
        it = self._tree.currentItem()
        if it is None:
            return None
        data = it.data(0, Qt.ItemDataRole.UserRole)
        if not (isinstance(data, tuple) and len(data) == 4):
            return None
        return data

    # ---------- 动作 ----------
    def _delete_action(self):
        """删除选中的自定义动作（**立即写回** roles.json）。

        为什么这里要二次确认、而角色编辑里那条删动作**不加**确认（v2.9.0 A6 的裁决）：
        那条是**暂存态**（点取消就恢复，本来就是可撤销的）；本页签是纯视图，没有暂存区，
        删了就是删了。与同仓「破坏性 → 二次确认 + 说清后果」的口径一致（见事件片段「清除」）。
        """
        info = self._selected()
        if info is None:
            self._note("先在清单里选中一条动作（角色行 / 形态行不能删）")
            return
        rid, fi, name, kind = info
        role = self._lib.get(rid) if self._lib is not None else None
        if role is None:
            self._note("角色已经不在了（可能刚被删过），重新打开这个窗口看看")
            return
        forms = list(role.get("forms") or [])
        if not (0 <= fi < len(forms)):
            self._note("形态对不上了（可能刚被改过），重新打开这个窗口看看")
            return
        form_name = forms[fi].get("name") or ("形态 %d" % (fi + 1))
        kind_label = "帧" if kind == "frames" else "合成"
        if not _confirm(self._parent_widget(), "删除动作",
                        "删除角色「%s」· %s 上的%s动作「%s」吗？\n\n"
                        "· 只解除引用：磁盘上的帧文件/配置本身不删；\n"
                        "· 这一步**立即生效**（这个页签是只读清单，没有「取消就恢复」）。"
                        % (role.get("name") or rid, form_name, kind_label, name)):
            return
        new_forms = copy.deepcopy(forms)
        fm = new_forms[fi]
        if kind == "frames":
            (fm.get("animations") or {}).pop(name, None)
        else:
            (fm.get("procs") or {}).pop(name, None)
        ok, err = self._lib.update(rid, {"forms": new_forms})
        if not ok:
            _warn(self._parent_widget(), "删除动作", err or "删除失败")
            return
        self._refresh()
        self._hint.setText("已删除 %s 上的%s动作「%s」（磁盘上的帧文件没删）"
                           % (form_name, kind_label, name))
        _toast(self._pet, "已删除动作「%s」" % name)

    def _locate_role(self):
        """定位到所属角色：交给容器切到「角色」页签并选中它（**不新开窗口**）。"""
        info = self._selected()
        if info is None:
            self._note("先在清单里选中一条动作，再点「定位到所属角色」")
            return
        rid = info[0]
        if self._locate is None:
            self._note("这个窗口不支持定位（没有角色页签）")
            return
        if not self._locate(rid):
            self._note("在「角色」页签里找不到角色 %s（可能刚被删过）" % rid)

    def _note(self, text):
        """本页签的状态行回执（成功 / 没选中 / 找不到都走这里，不弹框）。"""
        self._hint.setText(str(text))

    def _parent_widget(self):
        return self._pet if isinstance(self._pet, QWidget) else self

    def showEvent(self, event):
        """切到本页签就刷新一次（角色/动作可能在别的页签里刚改过）。"""
        super().showEvent(event)
        self._refresh()


class ResourceManagerDialog(_FitDialog):
    """QTabWidget 四页签（角色 / 音效 / 声音素材 / 动作），内嵌 RolePanel / SoundPanel /
    VoiceAssetPanel / ActionPanel。"""

    def __init__(self, parent=None, initial_tab=0):
        super().__init__(_qt_parent(parent))
        self._pet = parent
        self.setWindowTitle("资源管理")
        self.setStyleSheet(DIALOG_QSS)
        clamp_dialog(self, 700, 560)   # v2.5.0 B

        root = scroll_content(self)   # v2.5.0 B：内容区可滚动
        self._tabs = QTabWidget()
        # v2.12.0（F1）：角色面板留引用 —— 「动作」页签的「定位到所属角色」要用它选中行
        self._role_panel = RolePanel(parent)
        self._tabs.addTab(self._role_panel, "角色")
        self._tabs.addTab(SoundPanel(parent), "音效")
        self._tabs.addTab(VoiceAssetPanel(parent), "声音素材")  # v2.1：与音效分开
        self._action_panel = ActionPanel(parent, locate=self._locate_role)
        self._tabs.addTab(self._action_panel, "动作")           # v2.12.0（F1）
        self._tabs.setCurrentIndex(max(0, min(3, int(initial_tab))))
        root.addWidget(self._tabs, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.reject)
        row.addWidget(close_btn)
        stick_buttons(self, row)   # v2.5.0 B：按钮行在滚动区之外

    def _locate_role(self, rid):
        """「动作」页签的「定位到所属角色」：切到「角色」页签并选中它（v2.12.0 · F1）。

        返回是否找到——找不到由调用方（ActionPanel）写状态行说清楚，这里不弹框：
        "这个角色被删了"不是错误，是清单刷新的时机差。
        """
        found = self._role_panel.select_role(rid)
        if found:
            self._tabs.setCurrentIndex(self._tabs.indexOf(self._role_panel))
        return found


# ---------------- d) 记账账本对话框 ----------------
class AmountNoteDialog(_FitDialog):
    """记一笔：金额 QDoubleSpinBox(0.01~99999) + 备注 QLineEdit + 确定/取消。"""

    def __init__(self, parent=None, amount=None, note=""):
        """amount/note 是**预填值**（v2.3.0 1.2：AI 工具 add_manual_record 带上来的金额/备注），
        用户仍要在对话框里确认/修改；非数字金额忽略预填，不给坏值任何表现机会。"""
        super().__init__(_qt_parent(parent))
        self.setWindowTitle("记一笔")
        self.setStyleSheet(DIALOG_QSS)
        root = scroll_content(self)   # v2.5.0 B：内容区可滚动
        grid = QGridLayout()
        grid.addWidget(QLabel("金额："), 0, 0)
        self._amount = QDoubleSpinBox()
        self._amount.setRange(0.01, 99999.0)
        self._amount.setDecimals(2)
        self._amount.setValue(1.0)
        try:
            if float(amount or 0) > 0:
                self._amount.setValue(max(0.01, min(99999.0, float(amount))))
        except (TypeError, ValueError):
            pass  # 有意忽略：预填值非数字就保持默认 1.00
        self._amount.setSuffix(" ¥")
        grid.addWidget(self._amount, 0, 1)
        grid.addWidget(QLabel("备注："), 1, 0)
        self._note = QLineEdit()
        self._note.setPlaceholderText("例如：买了小鱼干（可留空）")
        self._note.setText(str(note or "")[:60])
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
        stick_buttons(self, row)   # v2.5.0 B：按钮行在滚动区之外

    def values(self):
        """返回 (金额 float 保留两位, 备注 str)。"""
        return round(float(self._amount.value()), 2), self._note.text().strip()


class LedgerDialog(_FitDialog):
    """账本：汇总 + 实时搜索 + 今日 / 近 7 天 / 全部 三页签 + 记一笔 / 导出 CSV。"""

    def __init__(self, parent=None):
        super().__init__(_qt_parent(parent))
        self._pet = parent
        self._book = _get(parent, "book")
        self.setWindowTitle("记账账本")
        self.setStyleSheet(DIALOG_QSS)
        clamp_dialog(self, 680, 540)   # v2.5.0 B

        root = scroll_content(self)   # v2.5.0 B：内容区可滚动
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
        stick_buttons(self, row)   # v2.5.0 B：按钮行在滚动区之外

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
class BubbleStyleDialog(_FitDialog):
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

        root = scroll_content(self)   # v2.5.0 B：内容区可滚动
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
        # v2.2.5（P0）：必须回填当前值——QSpinBox 初值=minimum，此前不回填会让构造末尾的
        # _apply_preview() 把用户字号覆盖成 8；点一次"保存"就把 12pt 写成 8pt（无提示）。
        self._font_spin.setValue(max(8, min(18, int(self._style.get("font_size") or 10))))
        self._font_spin.valueChanged.connect(lambda _v: self._apply_preview())
        grid.addWidget(self._font_spin, 3, 1)
        grid.addWidget(QLabel("圆角"), 4, 0)
        self._radius_spin = QSpinBox()
        self._radius_spin.setRange(0, 30)
        _r0 = self._style.get("radius")
        self._radius_spin.setValue(max(0, min(30, int(_r0 if _r0 is not None else 16))))
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
        # v2.7.0 第 5 轮（P1-4）：保存失败时的非模态状态行
        self._save_hint = QLabel("")
        self._save_hint.setWordWrap(True)
        self._save_hint.setStyleSheet("color:#ff8080;")
        row.addWidget(self._save_hint, 1)
        row.addWidget(save_btn)
        row.addWidget(reset_btn)
        row.addWidget(cancel_btn)
        stick_buttons(self, row)   # v2.5.0 B：按钮行在滚动区之外

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
        ok, msg, explicit = _apply_call(self._pet, "apply_bubble_style", style, strict=True)
        if not ok:
            # P1-4：以前丢弃返回值 + 无条件 accept()——失败也照常关窗，界面零变化
            _save_failed(self, "气泡样式", msg, explicit)
            return
        self.accept()
        _toast(self._pet, msg or "气泡样式已更新~（新样式从下一条气泡开始）")

    def _reset_default(self):
        self._style = dict(_DEFAULT_BUBBLE_STYLE)
        self._font_spin.setValue(10)
        self._radius_spin.setValue(16)
        self._update_color_buttons()
        self._apply_preview()


# ---------------- f) 台词设置对话框（v2.1：独立台词自定义模块 UI） ----------------
class LinesDialog(_DiscardGuard, _FitDialog):
    """v2.9.0（兼容审）：它的第二枚按钮原来叫「关闭」→ `self.accept()`，而「台词库」页签的
    编辑器**有暂存态**（改了文本/类别/角色/声音/喂食对象不点「保存」就没了）—— R4 反例。
    现在改名「取消」并混入 `_DiscardGuard`（无改动直接关，零额外一步）。
    """
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
        clamp_dialog(self, 780, 620)   # v2.5.0 B

        root = scroll_content(self)   # v2.5.0 B：内容区可滚动
        self._banner = QLabel("")
        self._banner.setWordWrap(True)
        root.addWidget(self._banner)
        # v2.11.0 第 9 轮（V7 · 原则 4「同一语义同一种表现」）：列表内连续操作的回执走
        # **窗口内状态行**（与 BehaviorDialog 同款），不再用宠物气泡——同一语义两种表现
        # 是本轮要收掉的那类不一致。**独立于 _banner**：_refresh_all 会重写 _banner
        # （"台词库不可用"/失效引用统计），复用会把回执冲掉。
        self._notes = QLabel("")
        self._notes.setWordWrap(True)
        root.addWidget(self._notes)
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_lines_tab(), "台词库")
        self._tabs.addTab(self._build_dialogue_tab(), "对白编排")
        self._tabs.addTab(self._build_invalid_tab(), "失效引用")
        root.addWidget(self._tabs, 1)
        row = QHBoxLayout()
        self._count = QLabel("")
        row.addWidget(self._count)
        row.addStretch(1)
        # v2.9.0（R4）：「关闭」执行的是「丢弃未保存的编辑器草稿 + 关窗」——改名「取消」，
        # 走 _cancel（有未保存改动时先问一次；没有改动直接关）。
        close_btn = QPushButton("取消")
        close_btn.clicked.connect(self._cancel)
        row.addWidget(close_btn)
        stick_buttons(self, row)   # v2.5.0 B：按钮行在滚动区之外
        self._refresh_all()
        self._baseline = self._form_signature()   # A5：打开即基线

    # ---------- A5：未保存判据（与 BehaviorDialog / AlarmDialog 同一套口径） ----------
    def _form_signature(self):
        """台词编辑器草稿的指纹（只有「台词库」页签的编辑器有暂存态）。"""
        return (str(self._editing or ""), self._text.toPlainText().strip(),
                str(self._cat.currentData() or ""),
                str(self._role.currentData() or ""),
                str(self._voice.currentData() or ""),
                str(self._food.currentData() or ""))

    def _discard_prompt(self, why="close"):
        if why == "switch":
            return ("编辑器里还有没保存的台词改动。\n"
                    "点「确定」= 放弃这些改动、切到另一条；点「取消」= 留在这一条接着改。")
        return ("编辑器里还有没保存的台词改动。\n"
                "点「确定」= 放弃这些改动并关窗；点「取消」= 回去接着改。")

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
            _btn_tip(b, label)         # P3-6：「新建」= 清空表单，「保存」才落盘
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
        # A5（同一种病，同一轮修）：换一条台词会把编辑器内容整块换掉 —— 有未保存改动时
        # 先问，拒绝就把选中项拨回原来那条（信号挡住，避免递归进来）。
        if not self._confirm_discard(why="switch"):
            _back = self._row_of(self._editing)
            self._list.blockSignals(True)
            try:
                self._list.setCurrentRow(_back)
            finally:
                self._list.blockSignals(False)
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
        # v2.2.5（P0）：喂食对象也要回填——此前漏了 → 保存时用下拉当前值（默认第 1 项）
        # 覆盖掉原值，food_texts("蛋糕") 再也选不中这条台词（只闻其声不见其食）。
        _food_val = str(ln.get("food") or "")
        _fi = self._food.findData(_food_val)
        if _fi < 0 and _food_val:
            # v2.2.7（审查 轻-5）：下拉是硬编码 3 项，角色包导入可能带任意 food——
            # 找不到就补一个占位项并选中，否则保存会把原值静默改写成第 1 项（"小鱼干"）。
            self._food.addItem("（已失效：%s）" % _food_val, _food_val)
            _fi = self._food.count() - 1
        self._food.setCurrentIndex(_fi if _fi >= 0 else 0)
        self._baseline = self._form_signature()   # A5：载入即基线

    def _note(self, text):
        """窗口内状态行（V7）：列表内连续操作的回执走这里，不用宠物气泡。

        与 BehaviorDialog._note 同款（措辞与出口都一致）——为什么不是气泡：
        Bubble 是**单窗口覆盖式**（pet_widgets.py 直接 setText + show + 5 秒定时器，无队列），
        连点三次只有最后一条可见；而"到顶/到底"这类回执发生在**列表内连续操作**里，
        用户的眼睛在窗口里，不在宠物身上。
        """
        try:
            self._notes.setText(str(text or ""))
        except Exception as e:
            pet_log.log_error("lines notes failed: %r" % (e,))

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
            # v2.8.0 第 6 轮：到顶/到底以前是静默 return —— 点了没反应与"已经到边界"在
            # 用户那边长得一模一样，这里说一句。
            # v2.11.0（V7）：出口从宠物气泡改成**窗口内状态行**（措辞一个字不改）——
            # 与 BehaviorDialog 的同语义回执统一（原则 4）。
            self._note("已经是最上面了" if int(delta) < 0 else "已经是最下面了")
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
        self._food.setCurrentIndex(0)  # v2.2.5：新建台词时重置喂食对象（防上一轮编辑残留）
        self._list.setCurrentRow(-1)
        self._baseline = self._form_signature()   # A5：清空即基线
        self._text.setFocus()
        # N2：表单本来就空时，点「新建」屏幕上零变化——给一句"已进入新建态"的即时回执
        _toast(self._pet, "已进入新建态：写完台词点「保存」")

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
        _created = False
        if self._editing:
            ok, err = self._lib.save(self._editing, text=text, category=cat,
                                     role_slot=role, voice_slot=voice, food=food,
                                     clear_role=not role, clear_voice=not voice)
        else:
            ln, err = self._lib.add(text, cat, role or None, voice or None, food=food)
            ok = ln is not None
            if ok:
                self._editing = ln["id"]
                _created = True
        if not ok:
            _warn(self, "保存失败", err or "保存失败")
            return
        if _created:
            # P1-8：新行受「类别」筛选与关键词搜索约束——筛选/搜索与新建类别不一致时，
            # 新台词根本不出现，用户以为没建成。新建落库后把这两个过滤条件复位。
            self._clear_line_filters(cat)
        self._refresh_all()
        # A5：**先**把基线对齐到"刚保存的内容"，再 _select_line —— 否则它会触发
        # _on_pick_line 的未保存检查，把"保存成功"误判成"有未保存改动"（凭空多一步）。
        self._baseline = self._form_signature()
        # N3/S5/P1-8：保存成功后以前零提示、也不选中新行（长列表下等于没保存）
        self._select_line(self._editing)
        _toast(self._pet, "台词已保存~")

    def _clear_line_filters(self, cat):
        """新建台词后复位"看不见新行"的两个过滤条件（类别=全部 + 清空搜索词）。"""
        if self._filter.currentData() and self._filter.currentData() != cat:
            self._filter.setCurrentIndex(0)     # 「全部」
        if (self._search.text() or "").strip():
            self._search.clear()

    def _select_line(self, lid):
        """按 id 选中并滚到可见处（保存/新建后的落点反馈）。返回是否找到。"""
        if not lid:
            return False
        for _i in range(self._list.count()):
            _it = self._list.item(_i)
            if _it.data(Qt.ItemDataRole.UserRole) == lid:
                self._list.setCurrentRow(_i)
                self._list.scrollToItem(_it)
                return True
        return False

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
            _warn(self, "删除失败", err or "删除失败")
            return
        self._editing = None
        self._text.clear()
        self._refresh_all()
        # D4：n（真删掉几条）以前拿到了却从不显示
        _toast(self._pet, "已删除 %d 条台词" % int(n or 0))

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
        _toast(self._pet, "已清空全部台词与对白（本窗口内可「撤销删除」找回）")

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
        _btn_tip(b_new, "新建对白")    # P3-6
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
        _btn_tip(b_add, "添加 →")      # P3-6
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
                self._dlist.scrollToItem(self._dlist.item(i))
                break
        _toast(self._pet, "已新建对白「%s」，记得改名~" % (d.get("name") or ""))

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
        _toast(self._pet, "已删除对白（台词本身不受影响）")

    def _rename_dialogue(self):
        if self._lib is None or not self._editing_dlg:
            _warn(self, "对白", "先选中一段对白再改名")
            return
        ok, err = self._lib.save_dialogue(self._editing_dlg, name=self._dname.text())
        if not ok:
            _warn(self, "保存失败", err or "保存失败")
            return
        self._refresh_all()
        _toast(self._pet, "对白名称已保存~")

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
        _toast(self._pet, "已添加到对白（顺序即播放顺序）")

    def _remove_member(self):
        if self._lib is None or not self._editing_dlg:
            _warn(self, "对白", "先选中一段对白")
            return
        row = self._members.currentRow()
        if row < 0:
            _warn(self, "移除台词", "先在对白内容里选中一条台词")
            return
        if not _confirm(self, "移除台词", "把这条台词从对白里移掉吗？（台词本身不受影响）"):
            return
        _gone = self._members.item(row)
        _gone_text = _gone.text() if _gone is not None else ""
        ids = self._member_ids()
        ids.pop(row)
        ok, err = self._lib.save_dialogue(self._editing_dlg, line_ids=ids)
        if not ok:
            _warn(self, "移除失败", err or "移除失败")
            return
        self._on_pick_dialogue()
        self._refresh_dialogues()
        # D9：以前移除后只有列表变化（用户不知道成没成、也不知道台词本身还在不在）
        _toast(self._pet, "已从对白里移除：%s（台词本身不受影响）" % (_gone_text[:24] or "这条台词"))

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
            # 与台词「上移/下移」同一套措辞（P3-6：同一动作同一批对话框同一套话）
            # v2.11.0（V7）：出口同样改成窗口内状态行（与上面那句一字不差）
            self._note("已经是最上面了" if int(delta) < 0 else "已经是最下面了")
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
        # P2-5：静态 getItem 改成手工建框 + modal()
        label, ok = _ask_item(self, "修复角色", "选择要指向的角色：", labels)
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
        # P2-5：静态 getItem 改成手工建框 + modal()
        label, ok = _ask_item(self, "修复声音", "选择要指向的声音素材：", labels)
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
        if not _confirm(self, "清空引用", "把这条台词的角色/声音引用清空吗？（台词本身保留）"):
            return
        res = self._lib.save(lid, clear_role=True, clear_voice=True)
        if res[0] is False:
            _warn(self, "清空失败", res[1] or "清空失败")
            return
        self._refresh_all()
        _toast(self._pet, "已清空这条台词的角色/声音引用")

    def _delete_bad_one(self):
        lid = self._bad_selected()
        if not lid or self._lib is None:
            return
        if not _confirm(self, "删除台词", "删除这条失效台词吗？"):
            return
        # D6：以前 delete(lid) 的返回值直接丢弃——删失败也照样刷新，用户以为删了
        ok, err = self._lib.delete(lid)
        if not ok:
            _warn(self, "删除失败", err or "删除失败")
            return
        self._refresh_all()
        _toast(self._pet, "已删除失效台词")

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
        # D7：以前 delete_many 的返回值与 err 全丢——删失败/删不掉也照样刷新
        n, err = self._lib.delete_many([x["line_id"] for x in items])
        if err:
            _warn(self, "删除失败", err)
            return
        self._refresh_all()
        _toast(self._pet, "已删除 %d 条失效台词（可用「撤销删除」找回）" % int(n or 0))

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



class PhysicsDialog(_FitDialog):
    """P1-手感：甩抛物理参数设置（重力/反弹/地面摩擦/顶边反弹/力度增益）。"""

    def __init__(self, parent=None):
        super().__init__(_qt_parent(parent))
        self._pet = parent
        self.setWindowTitle("物理参数")
        self.setStyleSheet(DIALOG_QSS)
        clamp_dialog(self, 430, 330)   # v2.5.0 B
        cfg = (_get(parent, "cfg") or {}).get("physics") or {}
        root = scroll_content(self)   # v2.5.0 B：内容区可滚动
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
        # v2.7.0 第 5 轮（P1-4）：保存失败时的非模态状态行
        self._save_hint = QLabel("")
        self._save_hint.setWordWrap(True)
        self._save_hint.setStyleSheet("color:#ff8080;")
        btns.addWidget(self._save_hint, 1)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        stick_buttons(self, btns)   # v2.5.0 B：按钮行在滚动区之外

    def _save(self):
        data = {"gravity": self._spin["gravity"].value(),
                "restitution": self._spin["restitution"].value(),
                "groundFriction": self._spin["groundFriction"].value(),
                "throwPower": self._spin["throwPower"].value(),
                "ceilingBounce": self._ceil.isChecked()}
        ok, msg, explicit = _apply_call(self._pet, "apply_physics", data, strict=True)
        if not ok:
            _save_failed(self, "物理参数", msg, explicit)
            return
        self.accept()
        # P1-4：值没变时主窗返回 (True, "没有改动")——以前是静默 return，"点保存 = 什么都不知道"
        _toast(self._pet, msg or "物理参数已更新~")


# ---------------- v2.11.0（B8）：语音合成的「在途 / 失败」反馈 ----------------
# 要解决的问题（实测）：点「朗读」→ svc.speak_line() 只是**入队**就返回 True，调用方当场
# 写一句"✅ 开始朗读…"；真正的合成在 worker 线程里，云端后端首次要几秒到十几秒。这期间
# 用户看到的是"已经开始了"（其实没有），而**合成失败**只会经 桌宠.py 的 voice_error → 宠物
# 气泡（对话框是 modal + 置顶，气泡在它后面）→ 用户在窗口里永远等不到任何结果。
# 为什么不给每个 VoiceDialog 各注册一次回调：VoiceService 只有 on_*、**没有 off_***
# （本模块也不该去改 pet_voice 的公开面）——那样每开一次窗口就多一个回调，而回调捕获了
# 对话框实例 → 关窗后仍被服务强引用（写已删除控件 + 泄漏）。所以按**服务实例**只挂一次，
# 转发器再向"当前活着的对话框"发信号。
_VOICE_UI_HOOKED = weakref.WeakSet()    # 已挂钩的 VoiceService（每个实例一次）
_VOICE_UI_DIALOGS = weakref.WeakSet()   # 当前活着的 VoiceDialog


def _route_voice_event(svc, key, text=""):
    """工作线程 → 主线程：把一条语音事件转给用**这个服务**的活对话框。

    绝不直接碰控件——只 emit 对话框自己的信号，槽由 Qt 排队到主线程执行。
    逐个包 try：某个对话框正在析构（RuntimeError）不该影响其余监听者，也不该打断合成线程。
    """
    for dlg in list(_VOICE_UI_DIALOGS):
        try:
            if getattr(dlg, "_svc", None) is not svc:
                continue
            dlg._voice_evt.emit(str(key), str(text or ""))
        except RuntimeError:
            # v2.11.0 收尾（审计裁决 · 收紧）：这里要挡的只有一种情况——C++ 对象已被
            # deleteLater 回收，emit 抛 RuntimeError（正常关窗的 teardown 竞态，实测必走）。
            # 此前写的是 except Exception: pass：那会把重构引入的 AttributeError /
            # TypeError 也一起吞掉（那条路正是 B8 要修的那条，会零痕迹消失）。
            # 收紧后：真·析构竞态照旧静默（WeakSet 下一轮自然清掉），我写错了则会出声。
            pass


def _hook_voice_ui(svc):
    """按服务实例挂钩一次（幂等）：started / finished / error 三种通知转给对话框侧。

    老替身/旧注入没有这几个注册口时静默跳过——退化成"没有在途反馈"，朗读本身不受影响。
    """
    if svc is None:
        return
    try:
        if svc in _VOICE_UI_HOOKED:
            return
        _VOICE_UI_HOOKED.add(svc)
    except TypeError as e:
        # v2.11.0 第 9 轮（代理 A · 静默 except 判定）：这里**不再静默**——"钩不上"意味着
        # 这条服务上的在途/失败反馈**整条缺席**（B8 修的就是这个缺陷），必须留一条可查的痕。
        # 限流键固定：同一个不可弱引用的替身反复打开设置窗也只记一条/分钟（不刷屏）。
        pet_log.log_throttled("voice_ui_hook",
                              "语音 UI 挂钩失败（不可弱引用/不可哈希的服务对象）：%r" % (e,))
        return  # 挂钩失败即放弃本次挂钩（朗读本身不受影响）
    for _reg, _key in ((getattr(svc, "on_speaking_started", None), "started"),
                       (getattr(svc, "on_speaking_finished", None), "finished"),
                       (getattr(svc, "on_error", None), "error")):
        if not callable(_reg):
            continue
        try:
            # 只取最后一个实参：error 是 (msg,)，started/finished 是 (role_slot, line_id)
            _reg(lambda *_a, _k=_key, _s=svc: _route_voice_event(_s, _k, _a[-1] if _a else ""))
        except Exception as e:
            # v2.11.0 第 9 轮（代理 A · 静默 except 判定）：注册口在、却**不接受这个回调**
            # ＝接线/签名不匹配 → 该事件的在途反馈会永远不出现（静默失败）→ 必须留痕。
            # 按 (服务类型, 事件) 限流，别在反复打开设置窗时刷屏。
            pet_log.log_throttled("voice_ui_reg:%s:%s" % (type(svc).__name__, _key),
                                  "语音事件注册失败（%s）：%r" % (_key, e))


def open_physics(pet):
    """P1-手感：物理参数对话框入口（置顶+显式焦点，同其它对话框套路）。"""
    try:
        dlg = PhysicsDialog(pet)
        modal(dlg)
    except Exception as e:
        # S25/P1-7：这里以前只 log_error——菜单点了没反应，用户完全不知道为什么。
        # 与同文件另外 7 个入口统一走 _dialog_failed（日志 + 中文警告框）。
        _dialog_failed(pet, "物理参数", e)


class _StatusLine(object):
    """公共「试听/合成：在途 → 结果」状态行（v2.12.0 · E1）。

    **三处复用同一份实现**（每处绑一个已有控件，不新开窗口、不动设计尺寸）：
      1. 朗读台词页 → VoiceDialog._play_label（异步：合成线程发事件回来，见 _on_voice_event）
      2. 角色绑定页 → VoiceDialog._preview_hint（试听参考音；服务侧也是**入队即返回**，
         真结果同样由语音事件回来）
      3. 事件音效页 → 该行的状态位 _row_labels[key]（试听事件片段，同步调用）

    为什么"在途"必须写一句：点下去到出声之间要几秒（云端后端十几秒），此前这期间界面上
    **一个字都不变**——用户分不清"没点上"和"正在合成"（B 当初只在朗读页做了这件事）。
    """

    PENDING = "⏳ 试听中…（正在合成，好了会在这里说结果）"

    def __init__(self, label, restore=None):
        self._label = label
        self._restore = restore   # 落定后要恢复的原文（None = 由调用方自己写结果）

    def set(self, text):
        # 不包 try：写的是**活窗口自己的**标签 —— 关窗/析构那条路在 _route_voice_event
        # 就被挡住了（那边是已登记的静默出口），这里再包一层只会多一条无主的静默 except。
        self._label.setText(str(text))

    def pending(self, text=None, pump=False):
        """进入「在途」。pump=True 时顺手过一次事件循环——**阻塞调用前必须画出来**。"""
        self.set(text if text else self.PENDING)
        if pump:
            _app_events()

    def ok(self, text):
        self.set(text)

    def fail(self, text):
        self.set("❌ " + str(text or "失败"))

    def reset(self):
        """回到"没有在途"的样子（行状态位用：试听完了仍要能看出这行配没配）。"""
        self.set("" if self._restore is None else self._restore)


class VoiceDialog(_FitDialog):
    """v2.1 语言系统（AI 配音）：可插拔克隆后端 + 角色声音绑定 + 台词朗读 + 事件片段。

    存储分工：声音素材在「资源管理 → 声音素材」（资源库），本面板只做**绑定与合成播放**；
    台词文本在「台词设置」，本面板只**读取并朗读**。"""

    # v2.11.0（B8）：合成/播放通知从**工作线程**来（pet_voice._emit 在合成线程里发），
    # Qt 控件只能主线程碰——所以转发器只 emit 这个信号，槽在收到的那一刻已经在主线程
    # （跨线程 AutoConnection 自动排队，与 桌宠.py 里 voice.on_speaking_started(
    # signals.voice_started.emit) 是同一套口径）。
    _voice_evt = Signal(str, str)

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
        # v2.11.0（B8）：本窗口发起的一次朗读/试听还没落定（落定前，_play_label 归它）
        self._voice_waiting = False
        _VOICE_UI_DIALOGS.add(self)
        try:
            self._voice_evt.connect(self._on_voice_event)
        except Exception as e:
            # v2.11.0 第 9 轮（代理 A · 静默 except 判定）：连接失败就是"在途/失败反馈
            # 永远不出现"（B8 修的正是在途反馈），不许静默——留痕并按窗口类限流。
            pet_log.log_throttled("voice_ui_connect:%s" % (type(self).__name__,),
                                  "语音事件信号连接失败：%r" % (e,))
        _hook_voice_ui(self._svc)
        self.setWindowTitle("语音设置（AI 配音）")
        self.setStyleSheet(DIALOG_QSS)
        clamp_dialog(self, 700, 640)   # v2.5.0 B

        root = scroll_content(self)   # v2.5.0 B：内容区可滚动
        tabs = QTabWidget()
        tabs.addTab(self._build_voice_tab(), "配音")
        tabs.addTab(self._build_bind_tab(), "角色绑定")
        tabs.addTab(self._build_play_tab(), "朗读台词")
        tabs.addTab(self._build_event_tab(), "事件音效")
        root.addWidget(tabs, 1)
        btns = QHBoxLayout()
        ok = QPushButton("保存")
        # v2.9.0（A8 / B3 的 R4 不变量）：它执行的是 reject（丢弃未保存编辑 + 关窗），
        # 叫「关闭」是标签在说谎 —— 改名「取消」。保存**不关窗**（见 _save）。
        cancel = QPushButton("取消")
        ok.setDefault(True)
        ok.clicked.connect(self._save)
        cancel.clicked.connect(self.reject)
        btns.addStretch(1)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        stick_buttons(self, btns)   # v2.5.0 B：按钮行在滚动区之外
        # v2.12.0（E1）：三处「试听/合成：在途 → 结果」共用 _StatusLine。四个页签都建好
        # 之后再绑（_play_label 在朗读页、_preview_hint 在绑定页、_row_labels 在事件页）。
        # _pending_line = **这次在途的那一次**落在哪个状态行 —— 结论写回发起它的那一页，
        # 而不是一律写朗读页（站在绑定页发起的试听，此前结论写在用户看不见的另一页）。
        self._play_line = _StatusLine(self._play_label)
        self._preview_line = _StatusLine(self._preview_hint)
        self._pending_line = self._play_line

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
            # N3（v2.4.1）：**先刷新状态、再写结果消息**。此前顺序相反，_refresh_launch_status()
            # 会把刚写好的✅/❌结果整行覆盖成"运行中/未运行"——用户（尤其启动失败时）
            # 永远看不到失败原因，只能看到一句无关的状态。
            self._refresh_launch_status()
            self._lstatus.setText(("✅ " if ok else "❌ ") + msg)
            return
        ok, msg = res if isinstance(res, tuple) else (False, "启动失败")
        self._refresh_launch_status()
        self._lstatus.setText(("✅ " if ok else "❌ ") + msg
                              + ("（后台等就绪，稍后气泡告知）" if ok else ""))

    def _stop_backend_now(self):
        if self._svc is None:
            return
        ok, msg = self._svc.stop_backend()
        self._refresh_launch_status()   # N3：先刷新状态，结果消息最后写（不被覆盖）
        self._lstatus.setText(("✅ " if ok else "❌ ") + msg)

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
        # P2-3（v2.7.0 第 5 轮）：素材库为空时下拉只剩「（不绑定）」，和"填充坏掉"长得
        # 一模一样；而且这一页没有导入入口（「管理声音素材…」在另一个页签）。这里把
        # 空态/故障态显式说出来，并给一个就地能点的入口。
        self._bind_hint = QLabel("")
        self._bind_hint.setWordWrap(True)
        lay.addWidget(self._bind_hint)
        self._bind_area = QWidget()
        self._bind_form = QFormLayout(self._bind_area)
        lay.addWidget(self._bind_area, 1)
        _imp_row = QHBoxLayout()
        self._btn_import_assets = QPushButton("去导入参考音…")
        self._btn_import_assets.clicked.connect(self._open_assets)
        _imp_row.addWidget(self._btn_import_assets)
        # v2.12.0（E1）：这一页的「试听：在途 → 结果」状态行。**另起一个控件、绝不写
        # _bind_hint**：那一行是素材库的健康提示（空库 / 索引读不出 / 库故障三种态），
        # 硬塞试听结果会把用户刚看到的健康提示冲掉（B 当初没做的理由之一）。
        # 放在**已有的**按钮行里而不是新加一行：行高由按钮决定，设计尺寸契约不受影响。
        self._preview_hint = QLabel("")
        self._preview_hint.setWordWrap(True)
        _imp_row.addWidget(self._preview_hint, 1)
        lay.addLayout(_imp_row)
        self._refresh_bindings()
        return w

    def _assets_health(self):
        """声音素材库是否可读 → (ok, 人话原因)。

        与 _asset_items 里那条"取不到就只给（不绑定）"的兜底**分工**：那条保界面不崩，
        这条负责**留痕 + 给出原因**——"库是空的"和"库读坏了"以前在界面上分不出来。
        """
        if self._assets is None:
            return False, "声音素材库没准备好（重启桌宠试试）"
        try:
            self._assets.assets()
        except Exception as e:
            pet_log.log_error("voice assets unreadable: %r" % (e,))
            return False, "声音素材读不出来（详情见数据目录的 error.log）"
        return True, ""

    def _assets_index_unusable(self):
        """索引文件在、**库里真的一条可用素材都没有** → (True, 一句人话)；否则 (False, "")。

        为什么要它：assets() 返回 [] 有两种**完全不同**的原因——"还没导入过任何素材"
        （索引文件不存在）与"索引里有内容却读不出来"（扩展名不在白名单 / JSON 坏了）。
        两种在界面上长得一模一样，用户只会问"怎么只有不绑定的选项"。

        v2.7.0 第 5 轮（F1 修复，本轮新引入的用户可见假警报）：判据必须**两条同时成立**——
          ① 索引文件在、且内容 > 2 字节（"导入过东西"留下的痕迹）；
          ② **库里真的一条都读不出来**（assets() 为空）。
        改前只有①，于是**任何导入过参考音的健康库**一打开声音素材面板就顶一条红字假警报
        「索引里有内容，但一条都读不出来」，而它下面的下拉里素材好好地列着；同一判据还往
        error.log 写一条**误导性**限流日志（实测两处复现：手造库 + 生产对象 pet.voice_assets）。
        所以：**先问库**——assets() 非空 = 健康库，直接返回 False，索引文件都不看。
        「读不出来 / 库故障」由 _assets_health 报（三态文案互不相同，见 _refresh_bind_hint）；
        **日志只在真丢弃时落**（上面②成立）。
        """
        if self._assets is None:
            return False, ""
        try:
            if self._assets.assets():
                return False, ""   # 真读得出素材 → 没有"索引不可用"这回事（F1）
        except Exception as e:
            # 读不出来 = 三态里的"库故障"，由 _assets_health 说话（本判据不重复判、不重复报）；
            # 这里仍记一条**留痕**：读不出来本身就是要查的事，而且审计口径（_dev 静默 except
            # razor）要求每个 except 要么补日志、要么登记进白名单 —— 这条属于"补日志"。
            pet_log.log_error("voice assets unreadable (index check): %r" % (e,))
            return False, ""
        idx = getattr(self._assets, "_index", None)
        if not idx or not os.path.isfile(idx):
            return False, ""
        try:
            _size = os.path.getsize(idx)
        except OSError as e:
            pet_log.log_error("voice assets index stat failed: %r" % (e,))
            return False, ""
        if _size <= 2:          # 文件在但只有 "{}"/空白 = 就是"还没导入过"
            return False, ""
        pet_log.log_throttled(
            "voice_assets.unusable:%s" % (os.path.basename(os.path.dirname(idx)) or "data"),
            "声音素材索引有内容但一条可用素材都没读出来：%s"
            "（参考音只支持 .wav / .mp3；扩展名不符的条目会被跳过）" % idx)
        return True, ("声音素材索引里有内容，但一条都读不出来——参考音只支持 .wav / .mp3，"
                      "扩展名不符的条目会被跳过（详情见数据目录的 error.log）。")

    def _refresh_bind_hint(self):
        """按素材库的真实状态写提示行（正常 / 空库 / 索引读不出 / 库故障）。"""
        ok, why = self._assets_health()
        _unusable, _why2 = self._assets_index_unusable()
        if not ok:
            self._bind_hint.setText("⚠ %s" % why)
            self._bind_hint.setStyleSheet("color:#ff8080;")
        elif _unusable:
            self._bind_hint.setText("⚠ %s" % _why2)
            self._bind_hint.setStyleSheet("color:#ff8080;")
        elif len(self._asset_items()) <= 1:
            self._bind_hint.setText("还没有配音素材，下面只能选「（不绑定）」——"
                                    "点「去导入参考音…」导入 3~10 秒干净人声（wav 最佳）。")
            self._bind_hint.setStyleSheet("color:#ffd65a;")
        else:
            self._bind_hint.setText("")
            self._bind_hint.setStyleSheet("")

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
        self._refresh_bind_hint()

    def _on_bind_changed(self, slot, combo):
        if self._svc is None:
            return
        ok, err = self._svc.bind_voice(slot, combo.currentData() or "")
        if not ok:
            _warn(self, "绑定失败", err or "绑定失败")
            return
        _toast(self._pet, "绑定已保存~")

    def _preview(self, vs):
        """试听参考音（角色绑定页）：在途 → 结果都写**这一页**的状态行。

        v2.12.0（E1）：服务侧的 preview_asset() 也是**入队即返回**（真合成在 worker
        线程），所以"在途"这句得在这里先写上；结果由 _on_voice_event 回填到
        _pending_line —— 也就是发起它的这一页（此前一律写朗读页：站在绑定页点试听，
        结论写在用户看不见的另一页，等于没有反馈）。
        """
        if not vs:
            _warn(self, "试听", "先选一个声音素材（没有就去「管理声音素材…」导入参考音）")
            return
        if self._svc is None:
            self._preview_line.fail("语音服务不可用，这次没有试听")
            return
        self._save(silent=True)
        self._voice_waiting = True          # 落定之前，语音事件归这一页
        self._pending_line = self._preview_line
        self._preview_line.pending(pump=True)
        ok, err = self._svc.preview_asset(vs)
        if not ok:
            self._voice_waiting = False
            self._pending_line = self._play_line   # 归位：下一次朗读的结论仍写朗读页
            self._preview_line.fail(err or "试听失败")
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

    def _on_voice_event(self, key, text):
        """语音事件（主线程，由 _voice_evt 排队过来）：只反映**本窗口发起的那一次**。

        为什么只在 _voice_waiting 时写标签：这个服务是**全局**的——宠物自己在读日常台词、
        闹钟在播报时也会发同样的事件。没有这道闸，窗口里那条结论会被别处的朗读覆盖掉
        （用户刚看到"❌ 台词不存在"，一转眼变成"✅ 这条读完了。"）。

        v2.12.0（E1）：写进 _pending_line（= **发起这次合成的那一页**的状态行）而不是
        写死 _play_label —— 绑定页发起的试听，结论就写在绑定页。
        """
        if not self._voice_waiting:
            return
        if key == "started":
            self._pending_line.set("▶ 正在播放……（合成好了，这就读出来）")
            return
        self._voice_waiting = False
        if key == "error":
            # 原则 5：错误 = 发生了什么 + 下一步能做什么。合成失败的原因由服务给
            # （"参考音不见了"/"合成失败"/"缓存写不进去"），下一步固定指向两个能自己动手的入口。
            self._pending_line.set(
                "❌ 配音失败：%s\n（下一步：点「测试后端」看配置；或去「资源管理 → 声音素材」"
                "确认素材还在。详情见数据目录的 error.log）" % (text or "服务没有给出原因"))
            self._pending_line = self._play_line
            return
        self._pending_line.set("✅ 这条读完了。")
        self._pending_line = self._play_line

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
        if not ok:
            self._voice_waiting = False
            self._play_label.setText("❌ " + (err or "朗读失败"))
            return
        # v2.11.0（B8）：入队成功≠已经在播——首次合成要几秒（云端十几秒）。这句话如实说
        # "还在合成"，随后的 started / error / finished 由 _on_voice_event 接着写。
        # v2.12.0（C-15）：措辞只能是**进行态**。旧文案"✅ 已开始朗读：正在合成…"自己跟
        # 自己打架（"已开始"是完成态、"正在合成"是进行态），用户读到的是"已经在读了"。
        self._voice_waiting = True
        self._pending_line = self._play_line
        self._play_line.set("✅ 已排上队：正在合成……（首次会慢一点），"
                            "合成好会自动播放；失败会在这里说明")

    def _regen_line(self):
        """丢掉缓存重新合成并朗读。

        v2.12.0（E2 / 发布说明 A-05 的**实现侧**）：服务不可用时**不许静默 return** ——
        旧实现这里一个字都不说，用户点「重新生成」看到的是"界面毫无反应"；而发布说明
        写的是"服务不可用时会说明"，差的正是这一句。同理，没选台词也不再静默。
        """
        if self._svc is None:
            self._pending_line = self._play_line
            self._play_line.fail("语音服务不可用，这次没有重新生成")
            return
        lid = self._line_combo.currentData()
        if not lid:
            self._play_line.fail("还没有选中台词，这次没有重新生成")
            return
        ok, err = self._svc.regenerate(lid)
        if not ok:
            self._voice_waiting = False
            self._play_label.setText("❌ " + (err or "重新生成失败"))
            return
        self._speak_line()

    def _stop(self):
        if self._svc is not None:
            self._svc.stop()
        self._voice_waiting = False   # v2.11.0（B8）：用户喊停后，迟到的事件不许再盖这句
        self._pending_line = self._play_line
        self._play_label.setText("已停止。")

    def _speak_dialogue(self):
        if self._svc is None:
            # v2.12.0（E2 同族）：与 _regen_line 一模一样的静默 return —— 同页同语义，
            # 一处补了"有交代"、另一处继续不吭声就是不一致（同页 _speak_line 也会说）。
            self._pending_line = self._play_line
            self._play_line.fail("语音服务不可用，这次没有朗读对白")
            return
        did = self._dlg_combo.currentData()
        if not did:
            self._play_label.setText("❌ 还没有对白（去「💬 自定义台词… → 对白编排」新建）")
            return
        self._save(silent=True)
        ok, err = self._svc.speak_dialogue(did)
        if not ok:
            self._voice_waiting = False
            self._play_label.setText("❌ " + (err or "朗读失败"))
            return
        self._voice_waiting = True
        self._pending_line = self._play_line
        self._play_line.set("✅ 已排上队：正在合成（首次会慢一点），"
                            "一条条按顺序播完；失败会在这里说明")

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

    def _event_label(self, key):
        """事件 key → 中文事件名（文案里要指名道姓，用户才知道删的是哪一行）。"""
        for k, label in self.EVENTS:
            if k == key:
                return label
        return str(key or "")

    def _import(self, key):
        """导入事件片段（S14：导入成功也要有回执，否则只有行标记从「—」变「✓ 已配」）。"""
        src, _f = QFileDialog.getOpenFileName(self, "导入语音片段", "", "音频 (*.wav *.mp3)")
        if not src:
            return
        ok, err = _get(self._pet, "voice").set_clip(key, src)
        if not ok:
            _warn(self, "语音片段", err or "导入失败")
            return
        self._refresh_rows()
        _toast(self._pet, "「%s」的事件片段已配好（立即生效）" % self._event_label(key))

    def _row_status(self, key):
        """事件行的「试听：在途 → 结果」状态行（E1 第三处）。

        **复用已有的状态位** _row_labels[key]（本来就是这一行的状态："—" / "✓ 已配"），
        不新加控件；restore 按当前配置算，所以试听完仍能看出这行配没配。
        """
        voice = _get(self._pet, "voice")
        try:
            cur = voice.clip(key) if voice is not None else None
        except Exception as e:
            # 读不出来按"没配"显示（_test 还会再取一次，取不到就走既有提示），但要留痕：
            # 静默 except 判据里"①补限流日志"比登记成无主的静默更省事，也更好查。
            pet_log.log_throttled("action_row_status", "读事件片段配置失败：%r" % (e,))
            cur = None
        return _StatusLine(self._row_labels[key], restore="✓ 已配" if cur else "—")

    def _test(self, key):
        """试听事件片段（E1）：在途 → 结果都写在**这一行**的状态位上。

        这一段是**同步**调用（pet.preview_audio 立即返回成没成），所以不需要事件回填：
        pending → 调 → 结果三步走完，用户至少在慢路径上看得到"点上了"。
        """
        p = _get(self._pet, "voice").clip(key)
        if p is None:
            _warn(self, "试听", "该事件还没配片段")
            return
        status = self._row_status(key)
        status.pending("⏳ 试听中…", pump=True)
        if _call(self._pet, "preview_audio", p) is not True:
            status.reset()   # 失败原因走既有的警告框，状态位回到"配没配"的原义
            _warn(self, "试听", "播放失败：音频文件可能已损坏")
            return
        status.ok("✓ 已配（刚试听过）")

    def _clear(self, key):
        """清除事件片段（P3-5 / S15）：破坏性 → 二次确认（带事件名与后果）+ 成功回执。"""
        label = self._event_label(key)
        if not _confirm(self, "清除语音片段",
                        "清除「%s」的事件片段吗？\n\n"
                        "· 只清这一行：这个事件以后不再播音效（其它事件不受影响）；\n"
                        "· **只解除引用，不删磁盘上的音频文件**——文件还在你原来的位置。" % label):
            return False
        ok, err = _get(self._pet, "voice").set_clip(key, None)
        if not ok:
            _warn(self, "语音片段", err or "清除失败")
            return False
        self._refresh_rows()
        _toast(self._pet, "已清除「%s」的事件片段（音频文件没删）" % label)
        return True

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
            # v2.9.0（A8 / B3 清单）：保存**不关窗** —— 这个窗口是工作台（窗内已有 5 处
            # _save(silent=True) 就地落盘：拉起后端、试听、朗读前都要先落配置），
            # 保存一次就关窗等于把它当一次性表单用，改几条设置要重开好几次。
            # 回执走气泡：这是「一次动作一句、用户会看宠物」的场合（口径见 _toast）。
            _toast(self._pet, "语音设置已保存")


def _app_events():
    """处理一次事件循环（测试按钮的"测试中…"能立刻显示出来）。"""
    try:
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
    except Exception:
        pass  # 有意忽略：无 QApplication 时跳过（不影响功能）


# ---------------- v2.1：待机设置对话框 ----------------
class IdleDialog(_FitDialog):
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
        clamp_dialog(self, 660, 560)   # v2.5.0 B

        root = scroll_content(self)   # v2.5.0 B：内容区可滚动
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
        # v2.9.0（质量审 5 / 审计清单 #11）：上移/下移**到顶/到底**以前是静默 return ——
        # 「点了没反应」与「已经在边界」在用户那边长得一模一样。回执走窗口内状态行
        # （与 A3/A4 同一口径），措辞照抄台词库那句。
        self._move_note = QLabel("")
        self._move_note.setWordWrap(True)
        v3.addWidget(self._move_note)
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
        # v2.9.0（A8 / B3 清单 + R4）：它执行的是 reject（丢弃未保存编辑 + 关窗），
        # 叫「关闭」是标签在说谎 —— 改名「取消」。**保存仍然关窗**（表单型），
        # 所以这次改名是零额外点击（用户路径一步没多）。
        cancel = QPushButton("取消")
        ok.setDefault(True)
        ok.clicked.connect(self._save)
        cancel.clicked.connect(self.reject)
        btns.addStretch(1)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        stick_buttons(self, btns)   # v2.5.0 B：按钮行在滚动区之外
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
        # N11：新动作加在表格末尾，以前既不选中也不滚动、也没有任何提示
        self._select_action(item.get("id") if isinstance(item, dict) else "")
        _toast(self._pet, "已添加待机动作")

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
        _toast(self._pet, "已移除待机动作")

    def _select_action(self, aid):
        """按 id 选中待机动作那一行（表格）。返回是否找到。"""
        if not aid:
            return False
        for row in range(self._table.rowCount()):
            _it = self._table.item(row, 0)
            if _it is not None and _it.data(Qt.ItemDataRole.UserRole) == aid:
                self._table.setCurrentCell(row, 0)
                self._table.scrollToItem(_it)
                return True
        return False

    def _move(self, delta):
        aid = self._selected_action()
        if not aid:
            # 未选中 = 空操作，**故意不提示**：
            # tests/test_dialogs_more_v24.py::test_idle_dialog_empty_library_and_no_selection
            # 明确断言"未选中时上移/下移不弹提示"（既有断言不动，铁律 4）。
            return
        self._collect()
        _before = [a["id"] for a in self._idle["idle_actions"]]
        pet_behaviors.move_idle_action(self._idle, aid, delta)
        self._refresh_table()
        for row in range(self._table.rowCount()):
            if self._table.item(row, 0).data(Qt.ItemDataRole.UserRole) == aid:
                self._table.setCurrentCell(row, 0)
                break
        if [a["id"] for a in self._idle["idle_actions"]] == _before:
            # 到顶/到底：顺序没变**不是**"没反应"，说一句（措辞与台词库同一句）
            self._move_note.setText("已经是最上面了" if int(delta) < 0 else "已经是最下面了")
        else:
            self._move_note.setText("已%s（顺序就是待机时的轮流顺序）"
                                    % ("上移" if int(delta) < 0 else "下移"))

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


# ---------------- v2.11.0（第 11 轮 · 旧第 8 轮那批 ③）：用户数据备份 / 恢复 ----------------
# 为什么 v1 用"文件对话框 + 确认框"而不是独立窗口：恢复这件事最要紧的是**让用户先看见包里是什么**
# 再点确定 —— 这一点在确认文案里就能做到（清单摘要 + 文件数 + 备份时间），而独立窗口要过
# tests/test_dialog_fit_v250.py 的 scroll_content / stick_buttons / clamp_dialog 三件套。
# 独立窗口留作后续；今天的形态**不会**让用户在"不知道自己会覆盖什么"的情况下点确定。


def _backup_rules():
    """取用户数据目录 + 版本号 + **本版 config 的 schema 版本**。

    取法：从 sys.modules 里拿已经加载的「桌宠」模块——**不顶层 import**（避免成环；
    同 _fallback_host 的取法）。第三个返回值是 pet_backup 判断"包里的 config.json 是不是
    未来版本"要用的（见 pet_backup.current_config_schema；模块没加载时是 None = 那一项不判）。
    """
    import sys as _sys
    m = _sys.modules.get("桌宠")
    return (getattr(m, "DATA_DIR", "") or "", getattr(m, "VERSION", "") or "",
            getattr(m, "CONFIG_SCHEMA_VERSION", None))


def open_backup(pet):
    """「备份数据…」：选一个 zip 落点，把用户数据打进去，回执走气泡/兜底。"""
    import os as _os
    import pet_backup
    data_dir, version, _schema = _backup_rules()
    if not data_dir:
        _warn(pet, "备份", "拿不到数据目录，这次没有备份。")
        return False
    try:
        default_path = pet_backup.default_backup_path(data_dir)
    except Exception as e:  # noqa: BLE001 —— 算不出默认落点不是"静默无反馈"：照本仓入口惯例出声
        _dialog_failed(pet, "备份", e)
        return False
    path, _ = QFileDialog.getSaveFileName(pet, "备份到…", default_path, "备份包 (*.zip)")
    if not path:
        return False
    ok, msg = pet_backup.create_backup(data_dir, path, app_version=version)
    if ok:
        # 常驻：这件事的结果值得读完（含 zip 全路径）。hold_ms=0 现在**真的**透传到
        # show_bubble（三审 #6：旧版只把这句话写在注释里，参数没传，5 秒就没了）。
        _toast(pet, msg, hold_ms=0)
    else:
        _warn(pet, "备份没完成", msg)
    return ok


def _reload_cfg_after_restore(pet):
    """恢复成功后把**内存里的配置**换成盘上那份 → 是否成功（不抛）。

    为什么必须做（三审 #3 / 兼容 #3，两路独立命中）：恢复做完那一刻，磁盘已经是包里那份
    旧数据，而 `pet.cfg` 还是**恢复前**的内存副本；全仓二十多处 `save_config(pet.cfg)`
    （每个菜单开关、每个对话框的保存）会在用户下一次随手操作时把旧配置写回磁盘——
    恢复被悄悄盖回去，用户还以为自己恢复了。
    取法：`桌宠.load_config()`（模块级函数，与导入失败回滚 `_restore_import_state` :2700
    用的是同一条），经由 sys.modules 拿模块（与 _backup_rules 同一路数，不顶层 import）。
    失败也不抛：返回 False，由调用方在回执里把"**必须**重启"说清楚。
    """
    import sys as _sys
    m = _sys.modules.get("桌宠")
    fn = getattr(m, "load_config", None)
    if not callable(fn):
        pet_log.log_throttled("restore:reload", "恢复后拿不到 load_config：配置未能重载（必须重启）")
        return False
    try:
        cfg = fn()
    except Exception as e:  # noqa: BLE001 —— 重载失败只影响"就地上新"，不影响恢复本身已落盘的数据
        pet_log.log_error("restore reload cfg failed: %r" % (e,))
        return False
    try:
        pet.cfg = cfg
    except Exception as e:  # noqa: BLE001 —— 只读替身/宿主对象上赋值会抛，同样不算致命
        pet_log.log_error("restore apply cfg failed: %r" % (e,))
        return False
    return True


def open_restore(pet):
    """「从备份恢复…」：先给用户看清单摘要，再确认；恢复前 pet_backup 自动留快照。

    v2.11.0（三审 #3）：成功后**当场重载配置**（把"旧 cfg 写回磁盘"这条后路堵掉），
    回执常驻并明说"必须重启"——恢复只换文件，角色/台词/闹钟这些服务对象要重启才重读。
    """
    import os as _os
    import pet_backup
    data_dir, version, schema = _backup_rules()
    if not data_dir:
        _warn(pet, "恢复", "拿不到数据目录，这次没有恢复。")
        return False
    start = ""
    try:
        start = _os.path.dirname(pet_backup.default_backup_path(data_dir))
    except Exception as e:  # noqa: BLE001 —— 同上：走 _dialog_failed，不许"点了没反应"
        _dialog_failed(pet, "恢复", e)
        return False
    path, _ = QFileDialog.getOpenFileName(pet, "选一个备份包…", start, "备份包 (*.zip)")
    if not path:
        return False
    manifest, why = pet_backup.read_manifest(path)
    if not manifest:
        _warn(pet, "这个包不能用", why or "读不出清单。")
        return False
    files = manifest.get("files") or []
    summary = ("包里有 %d 个文件（%s）\n备份时间：%s\n来源版本：%s\n\n"
               "继续会用包里的内容**覆盖当前数据**（恢复前会自动留一份快照）。"
               % (len(files), pet_backup._size_text(manifest.get("total_bytes") or 0),
                  pet_backup._short_time(manifest.get("created_at")),
                  manifest.get("app_version") or "未知"))
    if not _confirm(pet, "从备份恢复", summary):
        return False
    ok, msg = pet_backup.restore_backup(path, data_dir, app_version=version,
                                        config_schema=schema)
    if ok:
        _reload_cfg_after_restore(pet)
        _toast(pet, msg, hold_ms=0)   # 常驻：这段话（含快照路径 + "必须重启"）要读完
    else:
        _warn(pet, "恢复没完成", msg)
    return ok


def open_idle(pet):
    """v2.1：待机设置对话框入口。

    v2.9.0（A11 / 按钮审计 P3-5）：此前**没有 UI 入口**（菜单走的是另一条路
    pet._open_idle_dialog，本函数只有测试在调）。现在行为设置的「待机设置…」按钮
    走这里（见 BehaviorDialog._open_idle_settings）。**选的是「给入口」而不是「删掉/
    合并」**：那个下拉与待机设置改的是同一份 cfg["idle_actions"]，审计 D#4 判的是
    流程断裂（两套视图之间没有门），开门既修了断裂、又让这个入口真的有人走；
    而删掉它还得改既有用例（tests/test_dialogs_more_v24.py 在调它），收益只是少一个名字。
    """
    try:
        dlg = IdleDialog(pet)
        modal(dlg)
    except Exception as e:
        _dialog_failed(pet, "待机设置", e)


class _VoicePickDialog(_FitDialog):
    """导出时勾选要随包带走的声音素材（默认一个都不带）。"""

    def __init__(self, pet, parent=None):
        super().__init__(_qt_parent(parent or pet))
        self.setWindowTitle("打包声音素材（可选）")
        self.setStyleSheet(DIALOG_QSS)
        clamp_dialog(self, 460, 380)   # v2.5.0 B
        lay = scroll_content(self)   # v2.5.0 B：内容区可滚动
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
        stick_buttons(self, row)   # v2.5.0 B：按钮行在滚动区之外

    def _check_all(self, on):
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(
                Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def picked(self):
        return [self._list.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self._list.count())
                if self._list.item(i).checkState() == Qt.CheckState.Checked]


def pick_role_meta(parent, default_name=""):
    """v2.3.0：导出前的「角色信息」对话框（角色名/作者/简介/标签/创建日期）。

    返回 dict 或 None（用户取消）。纯展示元数据，留空=空串，不参与任何校验。
    """
    dlg, name, author, desc, tags = build_role_meta_dialog(parent, default_name)
    if modal(dlg) != QDialog.DialogCode.Accepted:
        return None
    return {
        "name": name.text().strip()[:40],
        "author": author.text().strip()[:40],
        "description": desc.text().strip()[:120],
        "tags": [t.strip()[:16] for t in tags.text().replace("，", ",").split(",") if t.strip()][:8],
        "created_at": time.strftime("%Y-%m-%d"),
    }


def build_role_meta_dialog(parent, default_name=""):
    """v2.3.0「角色信息」对话框的**构造**部分（v2.5.0 B 抽出来，尺寸验收要用）。

    工厂只建窗口不 exec；pick_role_meta 负责 modal 与取值。返回
    (dlg, name, author, desc, tags)。"""
    dlg = _FitDialog(_qt_parent(parent))   # v2.5.0 B：原来裸 QDialog，没有屏幕钳制
    dlg.setWindowTitle("角色信息（会写进角色包，别人导入时能看到）")
    dlg.setStyleSheet(DIALOG_QSS)
    clamp_dialog(dlg, 460, 300)   # v2.5.0 B
    root = scroll_content(dlg)   # v2.5.0 B：内容区可滚动
    form = QFormLayout()
    name = QLineEdit(str(default_name or ""))
    author = QLineEdit()
    desc = QLineEdit()
    tags = QLineEdit()
    tags.setPlaceholderText("逗号分隔，例：猫,可爱,懒")
    form.addRow("角色名", name)
    form.addRow("作者", author)
    form.addRow("一句话简介", desc)
    form.addRow("标签", tags)
    root.addLayout(form)
    root.addWidget(QLabel("留空也可以，只是别人导入时看不到作者和简介~"))
    row = QHBoxLayout()
    row.addStretch(1)
    btn_ok = QPushButton("继续导出")
    btn_cancel = QPushButton("取消")
    # P0-1（v2.7.0 第 5 轮）：v2.5.0 B 把这段抽成工厂时把两条接线丢了——两个按钮只被
    # addWidget 进布局，pick_role_meta() 进 modal() 的嵌套事件循环后**关不掉窗口**
    # （导出角色包必现不可用，连"取消"都点不动，回车也触发不了）。这里补回接线与默认
    # 按钮，对齐 _VoicePickDialog 的"确定/取消导出"两行。
    btn_ok.setDefault(True)
    btn_ok.clicked.connect(dlg.accept)
    btn_cancel.clicked.connect(dlg.reject)
    row.addWidget(btn_cancel)
    row.addWidget(btn_ok)
    stick_buttons(dlg, row)   # v2.5.0 B：按钮行在滚动区之外
    return dlg, name, author, desc, tags


def pick_voice_assets(pet):
    """导出前勾选声音素材。返回 id 列表（可为空=不带）；用户取消返回 None。"""
    dlg = _VoicePickDialog(pet)
    if modal(dlg) != QDialog.DialogCode.Accepted:
        return None
    return dlg.picked()


# v2.4（技术债 B）：这里原本还有一份模块级 ask_amount()（"数值输入对话框，预算/余额预警
# 共用"）——P1-7 重构后真正的实现是 PetWindow._ask_amount（由 BalanceService 注入调用，
# pet_balance.py 里两处 self.pet._ask_amount(...)）。全仓零引用（含 tests/、_verify_v13.py、
# _check_static.py 与所有文档），属于重构残留的重复实现，已删除。


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


# ---------------- 插件管理（v2.5.1 Phase 1 → v2.6.0 Phase 2：市场页） ----------------
_PLUGIN_COLUMNS = ("插件", "名称", "版本", "类型", "状态", "来源")
# 「可安装」页签的列（A2 口径：名称 / 类型 / 大小 / 版本 / 是否已装 / 可不可装）
_INDEX_COLUMNS = ("插件", "名称", "类型", "大小", "版本", "是否已装", "可否安装")
# 禁用口径的界面文案：与 pet_plugin_host.set_enabled 的行为**逐字对齐**（只改登记、
# 不撤内容、不删目录）——"已禁用"三个字很容易被读成"卸载了"，所以每个能看到它的地方
# 都把话写全（列表提示行 + 状态格 tooltip + 确认/结果文案）。
_PLUGIN_DISABLE_TIP = ("「启用 / 禁用」只改登记：插件内容（角色 / 台词 / 音效）仍然在库里，"
                       "插件目录也不会删——不等于卸载。")


def _fallback_host(pet):
    """宿主窗口没接线时的兜底：从**已加载的**主模块取数据目录与版本，现造一个宿主。

    本模块不能 import 桌宠.py（反向 import 会成环），所以只能取 sys.modules 里那个已经
    加载的实例。取不到（模块没加载 / 没有 DATA_DIR）返回 None——调用方给一句人话，
    绝不在这里抛（构造期抛异常 = 这个对话框打不开）。
    """
    main = sys.modules.get("桌宠")
    data_dir = str(getattr(main, "DATA_DIR", "") or "") if main is not None else ""
    if not data_dir:
        return None
    version = str(getattr(main, "VERSION", "") or "") if main is not None else ""
    return pet_plugin_host.PluginHost(data_dir, version, pet)


def _plugin_kind_text(rec):
    """类型列：kind + data_kind（"data / role"）；缺一个就只显示有的那个。"""
    kind = str(rec.get("kind") or "")
    data_kind = str(rec.get("data_kind") or "")
    if kind and data_kind:
        return "%s / %s" % (kind, data_kind)
    return kind or data_kind or "-"


def _plugin_source_text(rec):
    """来源列：来源地址优先，其次"本地安装"（有安装时间才算真装过）。"""
    url = str(rec.get("source_url") or "")
    if url:
        return url
    return "本地安装" if rec.get("installed_at") else "-"


def _plugin_update_available(rec, entry):
    """已装记录 + 索引条目 → 有没有**更新的版本**可装。

    版本比较走 pet_plugin.version_key（与校验器 / 发布门同款的四段整数比较）；
    记录里没有版本号时按"有更新"处理（装的时候没记版本，就不能咬定它是新的）。
    """
    if not isinstance(rec, dict) or not isinstance(entry, dict):
        return False
    if not entry.get("installable"):
        return False
    release = entry.get("release")
    if not isinstance(release, dict):
        return False
    cur = str(rec.get("version") or "").strip()
    if not cur:
        return True
    return pet_plugin.version_key(release.get("version")) > pet_plugin.version_key(cur)


def _plugin_cfg_getter(pet):
    """B 的 PluginIndex 要的 `cfg_getter`：返回主窗**活的** cfg dict（写回要落到同一份）。"""
    return lambda: _get(pet, "cfg")


def _plugin_save_cfg(pet):
    """B 的 PluginIndex 要的 `save_cfg`：宿主自己的写盘方法优先，其次主模块的 桌宠.save_config。

    为什么宿主优先：对话框的协作对象就是 pet，测试与嵌入方换掉 pet 就该连带换掉写盘路径
    （否则用例会绕过替身直接写真实 config.json）。生产路径上 PetWindow 没有这个方法，
    于是落到本模块从 sys.modules 取到的**已加载**主模块函数（全仓唯一的配置写盘处，
    也就是 _verify_v13 / _check_static 认的那一个）。都没有就返回 None —— B 会如实回报
    "索引地址没有接线"，而不是假装存下了。
    """
    save = _get(pet, "save_config")
    if callable(save):
        return save
    main = sys.modules.get("桌宠")
    save = getattr(main, "save_config", None) if main is not None else None
    return save if callable(save) else None


def _source_result(res):
    """B 的 refresh() 返回值 → (ok, msg, count)（统一口径：None / 坏形状一律按失败）。

    判据按任务书的 (ok, msg[, count]) 口径写：`isinstance(res, tuple) and res[0]`——
    **None 也算失败**，不写 `is not True`（B 明确说过 refresh 永远返回三元组）。
    """
    if not (isinstance(res, (tuple, list)) and res):
        return False, "索引刷新没有拿到结果（详情见数据目录的 error.log）", 0
    msg = str(res[1]) if len(res) > 1 and res[1] else ""
    count = res[2] if len(res) > 2 and isinstance(res[2], int) \
        and not isinstance(res[2], bool) else 0
    if not res[0]:
        return False, msg or "索引刷新失败（详情见数据目录的 error.log）", 0
    return True, msg, count


def _plugin_market_state(rec, entry):
    """「是否已装」列：未装 / 已装 vX / 已装 vX（可更新到 vY）。"""
    if not isinstance(rec, dict):
        return "未装"
    cur = str(rec.get("version") or "").strip() or "?"
    if _plugin_update_available(rec, entry):
        return "已装 v%s（可更新到 v%s）" % (cur, entry.get("version") or "?")
    return "已装 v%s" % cur


class PluginManagerDialog(_DiscardGuard, _FitDialog):
    """v2.9.0（找茬 F-4）：它的「关闭」原来走 `reject()`，而地址框只由「保存并使用」落盘
    → 手填地址静默丢弃（第三处 R4 反例）。现在按钮改叫「取消」，并按 A5 口径在**有改动时**
    先问一句；没有改动仍然直接关（零额外一步）。
    """
    """插件管理（v2.6.0 Phase 2）：两个页签 + 安装 / 更新 / 回滚 / 卸载 / 启用禁用 / 刷新索引。

    页签：
    · 「已安装」——现有列表（插件 / 名称 / 版本 / 类型 / 状态 / 来源）+ 卸载 / 启用禁用 / 回滚；
    · 「可安装」——索引里的条目（插件 / 名称 / 类型 / 大小 / 版本 / 是否已装 / 可否安装）
      + 安装（没装过）/ 更新（装过且有更高版本时才出现）。
    索引读取 / 下载 / 校验 / 落地**都不在本文件**：索引与下载在 pet_plugin_index（Qt-free）、
    包判据在 pet_plugin、安装登记与回滚在 pet_plugin_host；本文件只做界面、确认文案与调度。

    **网络操作不许卡界面**（照 pet_balance 那套代次/守卫口径，不自创）：
    · 远端索引与插件包在后台 daemon 线程里取数，结果用信号交回主线程槽；
    · 同一时刻**只有一个在途请求**（代次 _index_active / _pack_active）；在途期间再点一次
      只置 pending，等这一代落地后补发一次，绝不起第二个线程；
    · 旧代的迟到结果一律丢弃并记一行日志（不许静默），也绝不拿它去改界面状态；
    · **落地永远在主线程**（宿主库 / 安装登记都在主线程读写，与 pet_balance"记账在主线程"同款）。

    尺寸走 v2.5.0 那一套（clamp + 可滚动 + 按钮吸附）；设计尺寸 860x560 就写在
    clamp_dialog(...) 那一行（tests/test_dialog_fit_v250.py 从**源码字面量**读它，
    所以这里不留第二份常量——两处真源迟早对不上）。
    """

    # 后台取数 → 主线程（gen = 请求代次；参数个数与下面三个槽逐一对应）
    indexReady = Signal(int, object, object)      # gen, 归一索引 | None, err
    sourceReady = Signal(int, object)             # gen, B 的 refresh() 结果 (ok,msg,count) | None
    packReady = Signal(int, object, object)       # gen, 下载好的临时文件 | None, err
    packProgress = Signal(int, int, int)          # gen, 已下载字节, 总字节（0 = 未知）

    def __init__(self, pet=None, index=None):
        super().__init__(_qt_parent(pet))
        self.pet = pet
        self._host_obj = _get(pet, "plugin_host")
        self._index_obj = index        # 测试注入（假取数，不联网）；缺省按宿主目录现造
        self._rows = []                # 已安装（宿主清单）
        self._entries = []             # 索引条目（可安装页）
        self._entries_err = ""
        self._closing = False
        # 代次守卫（与 pet_balance 同款：只有"代次"说话，线程号不参与判定）
        self._index_gen = 0
        self._index_active = None
        self._index_pending = False
        self._pack_gen = 0
        self._pack_active = None
        self._pack_entry = {}
        self.setWindowTitle("🧩 插件管理")
        self.setStyleSheet(DIALOG_QSS)
        clamp_dialog(self, 860, 560)   # v2.5.0 B：设计尺寸（口径表按源码字面量核对）
        root = scroll_content(self)    # v2.5.0 B：内容区可滚动
        tip = QLabel("插件装在数据目录的 plugins/ 下。\n"
                     "· " + _PLUGIN_DISABLE_TIP + "\n"
                     "· 「卸载」只删插件目录 plugins/<id>/，它已经导入的角色 / 台词会**保留**"
                     "（属用户数据）。\n"
                     "· 「更新」会把新版新增的内容并进库（与已落地内容相同的条目不重复导入）；"
                     "「回滚」把插件退回上一版。")
        tip.setWordWrap(True)
        root.addWidget(tip)
        # ---- v2.8.0 · Phase 3（A1）：「索引来源」区（随包 / 远端；可填、可改、可恢复默认）----
        # 只做界面与文案：取数、校验、落地全在 B 的 pet_plugin_index（本文件不写第二套判据）。
        _src_box = QGroupBox("索引来源")
        _src_lay = QVBoxLayout(_src_box)
        self._src_label = QLabel("")
        self._src_label.setWordWrap(True)
        _src_lay.addWidget(self._src_label)
        _src_row = QHBoxLayout()
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("https://…/index.json（也可以填目录；留空 = 随包索引）")
        self._btn_src_save = QPushButton("保存并使用")
        self._btn_src_save.setToolTip("校验并保存这个地址；远端索引要再点「刷新索引」才会取回来。")
        self._btn_src_reset = QPushButton("恢复默认（随包索引）")
        self._btn_src_reset.setToolTip("清掉远端地址，回到随程序出货的随包索引（离线也能用）。")
        self._btn_src_save.clicked.connect(
            lambda checked=False: self.set_index_source(self._url_edit.text()))
        self._btn_src_reset.clicked.connect(
            lambda checked=False: self.set_index_source("", clearing=True))
        _src_row.addWidget(self._url_edit, 1)
        _src_row.addWidget(self._btn_src_save)
        _src_row.addWidget(self._btn_src_reset)
        _src_lay.addLayout(_src_row)
        root.addWidget(_src_box)
        self._tabs = QTabWidget()
        page1 = QWidget()
        lay1 = QVBoxLayout(page1)
        lay1.setContentsMargins(0, 0, 0, 0)
        self._table = _detail_table(_PLUGIN_COLUMNS)
        lay1.addWidget(self._table, 1)
        page2 = QWidget()
        lay2 = QVBoxLayout(page2)
        lay2.setContentsMargins(0, 0, 0, 0)
        self._market = _detail_table(_INDEX_COLUMNS)
        lay2.addWidget(self._market, 1)
        self._tabs.addTab(page1, "已安装")
        self._tabs.addTab(page2, "可安装")
        self._tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self._tabs, 1)
        self._hint = QLabel("")
        self._hint.setWordWrap(True)
        root.addWidget(self._hint)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)          # 忙等模式：长度未知也能看出"在动"
        self._progress.setVisible(False)
        root.addWidget(self._progress)
        self._wire_signals()           # 后台取数 → 主线程槽（三个信号必须真接上）
        self._table.itemSelectionChanged.connect(self._sync_buttons)
        self._market.itemSelectionChanged.connect(self._sync_buttons)
        row = QHBoxLayout()
        self._btn_install = QPushButton("安装")
        # v2.6.0 第 4 轮（兼容审查 P1-1）：**把"选本地包安装"这个入口加回来**。
        # v2.5.1 的底排是「安装…」→ QFileDialog 选本地 zip（当时用户装第三方/自制包的
        # 唯一入口）；本轮把「安装」改成"从索引装选中条目"时，_install() 整个失去了调用点
        # ——而 6142 的提示行还在说"「安装…」选本地包仍然可用"，界面在骗用户。
        # 现在两个入口并列：安装 = 从索引下载安装；安装… = 选本地 zip（索引坏了也能用，
        # 所以它**不跟选中行/在途请求联动**，永远可用——提示行那句话才成立）。
        self._btn_install_file = QPushButton("安装…")
        self._btn_install_file.setToolTip("选一个本地的插件 zip 安装（不读索引，离线也能用）")
        self._btn_update = QPushButton("更新")
        self._btn_rollback = QPushButton("回滚")
        self._btn_uninstall = QPushButton("卸载")
        self._btn_toggle = QPushButton("启用 / 禁用")
        self._btn_refresh = QPushButton("刷新索引")
        # v2.9.0（R4）：它执行的是 reject（丢弃地址框里没保存的编辑 + 关窗），叫「关闭」
        # 是标签在说谎 —— 改名「取消」；有改动时 `_cancel` 会先问一句。
        close_btn = QPushButton("取消")
        close_btn.setDefault(True)
        self._btn_install.clicked.connect(lambda checked=False: self._install_selected())
        self._btn_install_file.clicked.connect(lambda checked=False: self._install())
        self._btn_update.clicked.connect(lambda checked=False: self._update_selected())
        self._btn_rollback.clicked.connect(lambda checked=False: self._rollback())
        self._btn_uninstall.clicked.connect(lambda checked=False: self._uninstall())
        self._btn_toggle.clicked.connect(lambda checked=False: self._toggle())
        self._btn_refresh.clicked.connect(lambda checked=False: self.refresh_index(manual=True))
        close_btn.clicked.connect(self._cancel)   # A5：有未保存的地址改动时先问一句
        for btn in (self._btn_install, self._btn_install_file, self._btn_update,
                    self._btn_rollback, self._btn_uninstall, self._btn_toggle,
                    self._btn_refresh):
            row.addWidget(btn)
        row.addStretch(1)
        row.addWidget(close_btn)
        stick_buttons(self, row)       # v2.5.0 B：按钮行在滚动区之外
        self.refresh()                 # 已安装（只读本地清单）
        idx = self._index_ref()
        if idx is not None and not idx.index_url:
            # **随包**本地索引是本地文件、毫秒级：打开就把「可安装」填好，不联网。
            # 远端索引**不在打开时自动联网**（等用户点「刷新索引」或切到那个页签）——
            # 桌面程序不在用户没要求的时候发网络请求。
            self.refresh_index()
        self._refresh_source()         # v2.8.0 A1：只读本地，绝不联网（默认零打扰）
        # （_refresh_source 里已经记好基线；这里只是让"打开即干净"这件事不依赖调用顺序）
        self._baseline = self._form_signature()

    # ---------- A5：未保存判据（地址框是这个窗口唯一有暂存态的控件） ----------
    def _form_signature(self):
        """「索引来源」地址框的指纹。"""
        return self._url_edit.text().strip()

    def _discard_prompt(self, why="close"):
        return ("地址框里填的索引地址还没保存（要按「保存并使用」才会生效）。\n"
                "点「确定」= 放弃它并关窗；点「取消」= 回去接着编辑。")

    def _on_close_confirmed(self):
        """关窗后不再响应在途结果（_closing 守卫）；已经落库的步骤不受影响。

        v2.9.0（找茬 F-4 / 父代理裁决）：标题栏 × 与「取消」是**同一道门**（都会丢掉地址框里
        没保存的编辑），所以 × 也要走 A5 的未保存确认 —— 只修按钮等于留了另一条路能走到
        同样的坏结果。**这里不再自己写 closeEvent**：守卫在 `_DiscardGuard.closeEvent` 里
        （确认 → 设一次性令牌 → 真正 close），子类只提供这一句收尾钩子。
        """
        self._closing = True

    def _wire_signals(self):
        """把三个后台信号接到主线程槽上（**必须在 __init__ 里调**）。

        后台线程只 emit，不碰控件；Qt 的自动连接按"接收者所在线程"派发，所以这三个槽
        都在主线程跑——这正是"网络不卡界面 + 落地在主线程"的实现方式。
        """
        self.indexReady.connect(self._on_index_ready)
        self.sourceReady.connect(self._on_source_ready)
        self.packReady.connect(self._on_pack_ready)
        self.packProgress.connect(self._on_pack_progress)

    # ---------- 读 ----------
    def _host_ref(self):
        """插件宿主：宿主窗口接线优先；没接线就现造一个；都拿不到返回 None。"""
        if self._host_obj is None:
            self._host_obj = _fallback_host(self.pet)
        return self._host_obj

    def _index_ref(self):
        """索引下载器：注入优先；否则按宿主目录现造（缺省只读**随包**索引，不联网）。"""
        if self._index_obj is None:
            host = self._host_ref()
            if host is None:
                return None
            self._index_obj = pet_plugin_index.PluginIndex(
                host.plugins_dir, host_version=host.host_version,
                index_url=str(_get(self.pet, "plugin_index_url") or ""),
                landing_kinds=pet_plugin_host.LANDING_KINDS,
                # v2.8.0 · Phase 3（A1）：把"读写主窗配置"和"日志"注入给 B 的索引器——
                # set_remote_base 靠这两个回调写盘（失败会如实回报，不假装存下了）。
                cfg_getter=_plugin_cfg_getter(self.pet),
                save_cfg=_plugin_save_cfg(self.pet),
                log=self._index_log)
        return self._index_obj

    def refresh(self):
        """重读已装清单并重画两个页签（只读）。坏目录 / 坏 JSON 只显示成一句提示，绝不抛。"""
        host = self._host_ref()
        if host is None:
            self._rows = []
            self._table.setRowCount(0)
            self._market.setRowCount(0)
            self._set_hint("插件宿主未接线：重启一次桌宠即可（详情见数据目录的 error.log）。")
            self._sync_buttons()
            return
        rows, problems = host.list_installed()
        self._rows = [r for r in rows if isinstance(r, dict)]
        self._table.setRowCount(len(self._rows))
        for i, rec in enumerate(self._rows):
            enabled = bool(rec.get("enabled", True))
            cells = (str(rec.get("id") or ""), str(rec.get("name") or ""),
                     str(rec.get("version") or ""), _plugin_kind_text(rec),
                     "已启用" if enabled else "已禁用",
                     _plugin_source_text(rec))
            for j, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if j == 4 and not enabled:
                    # 文案与行为一致（A3）：这三个字很容易被读成"卸载了"，补一句 tooltip
                    item.setToolTip(_PLUGIN_DISABLE_TIP)
                self._table.setItem(i, j, item)
        note = self._fill_market()
        if problems:
            self._set_hint("已安装 %d 个插件；有 %d 处读不出来：%s%s"
                           % (len(self._rows), len(problems), "；".join(problems[:3]), note))
        else:
            self._set_hint("已安装 %d 个插件。%s" % (len(self._rows), note))
        self._sync_buttons()

    def _set_hint(self, text):
        self._hint.setText(str(text or ""))

    # ---------- v2.8.0 · Phase 3（A1）：索引来源（随包 / 远端）----------
    def source_info(self):
        """当前索引来源 → dict（B 的 `source_info()`）。

        缺方法（后端还没接线 / 测试替身）时按 `index_url` 兜底——它是同一个真源，
        所以界面不会因为后端版本不同而显示成另一种来源。**只读本地，绝不联网。**
        """
        idx = self._index_ref()
        if idx is None:
            return {}
        fn = getattr(idx, "source_info", None)
        if callable(fn):
            try:
                got = fn()
            except Exception as e:
                self._index_log("source_info 失败：%r" % (e,))
                got = None
            if isinstance(got, dict):
                return got
        url = str(getattr(idx, "index_url", "") or "")
        return {"kind": "remote" if url else "bundled", "url": url, "updated_at": ""}

    def _refresh_source(self):
        """把「索引来源」区按当前后端状态重画（一句话说清"现在用的是哪一份"）。"""
        idx = self._index_ref()
        if idx is None:
            self._src_label.setText("当前：读不到索引来源（插件宿主未接线）。")
            self._mark_source_clean()
            return
        info = self.source_info()
        url = str(info.get("url") or "")
        if str(info.get("kind") or "") == "remote" and url:
            text = "当前：远端索引（%s）" % url
            extra = []
            if info.get("cached"):
                extra.append("本地缓存取回于 %s" % (info.get("fetched_at") or "未知时间"))
            else:
                extra.append("还没取回来——点「刷新索引」")
            if info.get("updated_at"):
                extra.append("索引自报更新于 %s" % info["updated_at"])
            if info.get("count"):
                extra.append("共 %d 个条目" % int(info["count"]))
            text += "；" + "，".join(extra)
        else:
            text = "当前：随包索引（随程序出货，离线也能用）"
            if info.get("updated_at"):
                text += "；索引自报更新于 %s" % info["updated_at"]
        self._src_label.setText(text)
        self._url_edit.setText(url)
        self._sync_buttons()
        self._mark_source_clean()

    def _mark_source_clean(self):
        """A5：重画之后地址框里就是"后端此刻的真实值" —— 记成新基线（不该再问）。

        保存成功、恢复默认、以及每次重画都会走到这里，所以"保存完关窗"永远不会多一步。
        """
        self._baseline = self._form_signature()

    def set_index_source(self, url, clearing=False):
        """「保存并使用」/「恢复默认（随包索引）」的唯一出口 → 是否真的换了来源。

        校验分两道，**都不在本文件写第二套判据**：
          · 界面这一道（当场拒绝、当场说清）：空（保存按钮）/ 非 https / 本地路径 / file:// /
            超长 → `pet_config.validate_plugin_index_url`（B 的实现，与真正取数时同一个判据）；
          · 后端这一道：`idx.set_remote_base(url)` —— 它还要写盘，写盘失败会如实回报
            （失败时盘上与内存都不动，这里照它的话告诉用户，不假装存下了）。
        **保存本身不取数**（零打扰）：远端要再点「刷新索引」；回随包索引是本地直读，立刻生效。
        """
        raw = pet_config.normalize_plugin_index_url(url)
        if not raw and not clearing:
            self._source_failed("要填一个 https:// 开头的远端索引地址（填目录或 .json 都行）；"
                                "想回到随包索引，请点「恢复默认（随包索引）」。")
            return False
        ok, reason = pet_config.validate_plugin_index_url(raw)
        if not ok:
            self._source_failed(reason)
            return False
        idx = self._index_ref()
        if idx is None:
            self._source_failed("插件宿主未接线：改不了索引来源（重启一次桌宠即可）。")
            return False
        fn = getattr(idx, "set_remote_base", None)
        if not callable(fn):
            self._source_failed("这个版本的后端还没接线（set_remote_base 不存在），改不了索引来源。")
            return False
        try:
            res = fn(raw)
        except Exception as e:
            self._index_log("set_remote_base 抛异常：%r" % (e,))
            res = None
        if not (isinstance(res, (tuple, list)) and res and res[0]):
            msg = ""
            if isinstance(res, (tuple, list)) and len(res) > 1 and res[1]:
                msg = str(res[1])
            self._source_failed(msg or "索引来源没能保存（详情见数据目录的 error.log）。")
            return False
        back = str(res[1]) if len(res) > 1 and res[1] else ""
        self._refresh_source()
        if not raw:
            # 回随包索引：本地直读、毫秒级 → 列表立刻跟上，回执用后端那句话（或兜底文案）
            self.refresh_index(manual=True)
            _toast(self.pet, back or "已恢复为随包索引（不联网）", status=self._hint)
        else:
            # 换远端：**不在这里联网**（保存 ≠ 取数）。后端那句已经写明下一步是「刷新索引」，
            # 真正的回执等刷新落地时的那一句（一次用户动作只说一句话）。
            self._set_hint("✓ " + (back or "已改用远端索引：%s" % raw))
            _toast(self.pet, back or "已改用远端索引（点「刷新索引」取回列表）", status=self._hint)
        return True

    def _source_failed(self, reason):
        """索引来源改不了：**不关窗** + 当场说清为什么（内联状态行 + 一次模态提示）。"""
        text = str(reason or "索引来源没能保存")
        self._set_hint("⚠ " + text)
        _warn(self, "索引来源", text)

    # ---------- 远端索引刷新（后台取数 + 代次守卫；只读本地那次仍在主线程）----------
    def _source_worker(self, gen, idx, force):
        """后台线程：取远端索引并落地（B 的 refresh）。**不碰 Qt 控件**，结果交回主线程槽。"""
        try:
            res = idx.refresh(bool(force))
        except Exception as e:
            res = None
            self._index_log("refresh 抛异常：%r" % (e,))
        if not self._emit_safe("sourceReady", gen, res):
            self._index_retire(gen, "结果没能交给主线程")

    def _on_source_ready(self, gen, res):
        """远端索引刷新落地（主线程槽）：先消费自己那一代，旧代一律丢弃。

        成功后**只读本地缓存**重画表格（B 的 load_index 不联网），所以一次刷新只有一次网络。
        """
        if self._closing_now():
            self._index_retire(gen, "窗口已关闭，丢弃索引刷新结果")
            return
        if not self._index_consume(gen, "refresh"):
            return
        pending = self._index_pending
        self._index_pending = False
        ok, msg, count = _source_result(res)
        if not ok:
            self._index_refresh_failed(msg)
        else:
            idx = self._index_ref()
            data, err = (None, "索引下载器不可用") if idx is None else idx.load_index()
            if data is None:
                self._index_refresh_failed("远端索引取回来了，但读不出来：%s" % (err or "原因未知"))
            else:
                self._apply_index(data, err)
                self._index_refresh_ok(msg, count)
        self._refresh_source()
        if pending:
            QTimer.singleShot(0, self, lambda: self.refresh_index(manual=True))   # 补发排队那次

    def _index_refresh_ok(self, msg, count):
        """刷新成功的一句回执：气泡 + 对话框内的状态行（**同一句话**，不各写一套）。"""
        text = str(msg or "").strip() or ("远端索引已更新（共 %d 个插件）" % int(count or 0))
        note = self._hint.text()
        self._set_hint(("✓ %s。%s" % (text, note)) if note else ("✓ " + text))
        _toast(self.pet, text, status=self._hint)

    def _index_refresh_failed(self, msg):
        """刷新失败：**不关窗** + 人话原因 + 明确保留"回退到随包索引"的路（P3-5 同款口径）。

        表格**一个字节都不动**：B 的 refresh 失败时不会碰缓存与随包索引，所以旧列表仍然可用；
        要换回随包索引只要点「恢复默认（随包索引）」。
        """
        text = str(msg or "").strip() or "索引刷新失败（详情见数据目录的 error.log）"
        self._set_hint("⚠ %s　可点「恢复默认（随包索引）」回到随包索引——它随程序出货，"
                       "离线也能用。" % text)
        _warn(self, "刷新索引失败",
              "%s\n\n可点「恢复默认（随包索引）」回到随包索引：它随程序出货，离线也能用。\n"
              "（磁盘上原有的索引与缓存一个字节都没动。）" % text)

    def _installed_map(self):
        """已装清单 → {id: 记录}（两处对账都用它，免得各写一份）。"""
        out = {}
        for rec in self._rows:
            if isinstance(rec, dict):
                out[str(rec.get("id") or "")] = rec
        return out

    def _fill_market(self):
        """可安装页：索引条目 + 与"已装"的对照（是否已装 / 可不可装）→ 一句索引侧提示。

        提示**返回**给调用方拼（而不是自己 setText）：refresh() 也要写提示行，
        两处各写一次会把"索引读不出来"这句盖掉（用户就看不到索引坏了）。
        """
        installed = self._installed_map()
        self._market.setRowCount(len(self._entries))
        for i, entry in enumerate(self._entries):
            eid = str(entry.get("id") or "")
            reason = str(entry.get("reason") or "")
            cells = (eid, str(entry.get("name") or ""), _plugin_kind_text(entry),
                     str(entry.get("size_text") or "-"), str(entry.get("version") or "-"),
                     _plugin_market_state(installed.get(eid), entry),
                     "可安装" if entry.get("installable") else
                     "不可安装：%s" % (reason or "原因未知"))
            for j, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if j == 6 and not entry.get("installable") and reason:
                    item.setToolTip(reason)
                self._market.setItem(i, j, item)
        if self._entries_err:
            return " 索引读不出来：%s（「安装」暂不可用；「安装…」选本地包仍然可用）" \
                % self._entries_err
        return ""

    def _selected(self):
        """已安装页选中行 → 记录 dict；没选中（或列表空）返回 None。"""
        row = self._table.currentRow()
        if row < 0 or row >= len(self._rows):
            return None
        return self._rows[row]

    def _selected_entry(self):
        """可安装页选中行 → 索引条目；没选中返回 None。"""
        row = self._market.currentRow()
        if row < 0 or row >= len(self._entries):
            return None
        return self._entries[row]

    def _on_tab_changed(self, index):
        """换页签 → 必要时补一次索引读取（远端在切页签时才联网），再重算按钮状态。"""
        if index == 1 and not self._entries and not self._entries_err:
            self.refresh_index(manual=True)
        self._sync_buttons()

    def _sync_buttons(self):
        """按钮的可用性与可见性跟着"当前页签 / 选中行 / 在途请求"走。

        「更新」**有新版本时才出现**（A2）；「回滚」只在选中了有上一版的插件时出现。
        """
        busy = self._pack_active is not None
        on_market = self._tabs.currentIndex() == 1
        entry = self._selected_entry() if on_market else None
        rec = None if on_market else self._selected()
        installed = self._installed_map()
        eid = str(entry.get("id") or "") if entry is not None else ""
        can_install = bool(entry is not None and entry.get("installable") and not busy
                           and eid not in installed)
        has_update = bool(entry is not None and not busy
                          and _plugin_update_available(installed.get(eid), entry))
        has_history = bool(rec is not None and rec.get("history") and not on_market)
        self._btn_install.setEnabled(can_install)
        self._btn_update.setVisible(has_update)
        self._btn_update.setEnabled(has_update)
        self._btn_rollback.setVisible(has_history)
        self._btn_rollback.setEnabled(has_history and not busy)
        self._btn_uninstall.setEnabled(rec is not None and not busy)
        self._btn_toggle.setEnabled(rec is not None and not busy)
        self._btn_refresh.setEnabled(not busy)
        # v2.8.0 A1：改来源要写配置（宿主没接线就改不了）——按钮状态跟着真实能力走
        has_idx = self._index_ref() is not None
        for _b in (getattr(self, "_btn_src_save", None), getattr(self, "_btn_src_reset", None)):
            if _b is not None:
                _b.setEnabled(has_idx and not busy)

    # ---------- 可安装列表：读索引（远端走后台线程 + 代次守卫） ----------
    def refresh_index(self, manual=False):
        """刷新「可安装」→ 是否**真的起了**一次取数。

        远端索引走后台线程（网络不许卡界面）；**随包本地索引**直接读——它是本地文件、
        毫秒级，没有"卡界面"的问题，也就没必要为它起线程（构造期尤其不该起）。
        代次守卫与 pet_balance 同款：同一时刻只有一个在途取数；在途期间再点一次只置
        pending，等这一代落地后自动补发一次——连点不会起第二个线程。

        v2.8.0 · Phase 3（A1）三条路，别混：
          · **远端 + 后端有 refresh()** → 后台线程跑 B 的 refresh()（全模块唯一的联网处，
            force=True 无条件重取 / force=False 优先用同地址缓存），落地后再用 load_index()
            读**本地缓存**画表（不二次联网）；
          · **随包（没有远端地址）** → 本地直读，毫秒级，不起线程（与接线前逐位一致）；
          · **远端但后端没有 refresh**（注入替身 / 更老的后端）→ 保持 v2.7.0 的后台读取口径。
        """
        idx = self._index_ref()
        if idx is None:
            self._entries, self._entries_err = [], ""
            self._market.setRowCount(0)
            self._set_hint("插件宿主未接线：重启一次桌宠即可（详情见数据目录的 error.log）。")
            self._sync_buttons()
            return False
        if self._index_active is not None:
            # 在途（含"结果已 emit、槽还没轮到跑"那一小段）：手动刷新排队，自动刷新跳过
            if manual:
                self._index_pending = True
            return False
        remote = str(getattr(idx, "index_url", "") or "")
        if remote and callable(getattr(idx, "refresh", None)):
            gen = int(self._index_gen) + 1
            self._index_gen = gen
            self._index_active = gen
            self._set_hint("正在读取远端索引…" if manual
                           else "正在读取远端索引（优先用本地缓存）…")
            self._sync_buttons()
            try:
                threading.Thread(target=self._source_worker, args=(gen, idx, bool(manual)),
                                 daemon=True).start()
            except Exception as e:
                # 起不了线程是用户要能从 error.log 追的故障（razor 只认名字带 log/warn/… 的调用，
                # 自定义的 _index_log 不算）——所以这里用全仓统一的限流日志原语记一条。
                pet_log.log_throttled("plugin_dialogs.refresh_index",
                                      "起不了索引取数线程：%r" % (e,))
                self._index_retire(gen, "线程启动失败：%r" % (e,))
                self._index_refresh_failed(
                    "起不了取数线程：%s（详情见数据目录的 error.log）" % e)
                return False
            return True
        if not remote:
            data, err = idx.load_index()
            self._apply_index(data, err)
            return not err
        gen = int(self._index_gen) + 1
        self._index_gen = gen
        self._index_active = gen
        self._set_hint("正在读取索引…")
        self._sync_buttons()
        try:
            threading.Thread(target=self._index_worker, args=(gen, idx), daemon=True).start()
        except Exception as e:
            self._index_retire(gen, "线程启动失败：%r" % (e,))
            self._apply_index(None, "取数失败：%r" % (e,))
            return False
        return True

    def _apply_index(self, data, err):
        """把一次索引读取的结果画到「可安装」页（只在主线程调用）。"""
        if data is None:
            self._entries, self._entries_err = [], str(err or "索引读不出来")
            note = self._fill_market()
            self._set_hint(note.strip() or "索引读不出来")
            self._sync_buttons()
            return
        self._entries = [e for e in (data.get("entries") or []) if isinstance(e, dict)]
        self._entries_err = ""
        problems = [str(x) for x in (data.get("problems") or [])]
        note = ("；索引里有 %d 条读不出来：%s" % (len(problems), "；".join(problems[:2]))
                if problems else "")
        installed = len(self._installed_map())
        self._set_hint("%s：%d 个条目（已装 %d 个）%s%s"
                       % (data.get("source") or "索引", len(self._entries), installed,
                          note, self._fill_market()))
        self._sync_buttons()

    def _index_worker(self, gen, idx):
        """后台线程：只读索引（网络 / 本地文件），**不碰任何 Qt 控件**，结果交回主线程槽。"""
        try:
            data, err = idx.load_index()
        except Exception as e:
            data, err = None, "读取索引失败：%r" % (e,)
        if not self._emit_safe("indexReady", gen, data, err):
            self._index_retire(gen, "结果没能交给主线程")

    def _on_index_ready(self, gen, data, err):
        """索引结果落地（主线程槽）：先消费自己那一代，旧代一律丢弃。"""
        if self._closing_now():
            self._index_retire(gen, "窗口已关闭，丢弃索引结果")
            return
        if not self._index_consume(gen, "index"):
            return
        pending = self._index_pending
        self._index_pending = False
        self._apply_index(data, err)
        if pending:
            QTimer.singleShot(0, self, lambda: self.refresh_index(manual=True))   # 补发排队那次

    def _index_consume(self, gen, source):
        """槽端消费一代：只有当前那一代才放行（旧代丢弃并记日志，绝不动界面状态）。"""
        cur = self._index_active
        if cur != gen:
            self._index_log("丢弃旧代索引结果 %s（代次 %s 已过期，当前在途 %r）"
                            % (source, gen, cur))
            return False
        self._index_active = None
        return True

    def _index_retire(self, gen, why):
        """把 gen 那一代收尾（只在它仍是当前那一代时生效）——结果交不出去时的兜底。"""
        if self._index_active == gen:
            self._index_pending = False
            self._index_active = None
        self._index_log("索引代次 %s 由收尾路径结束（%s）" % (gen, why))

    # ---------- 安装 / 更新：下载在后台线程，校验与并库在主线程 ----------
    def install_entry(self, entry):
        """按索引条目安装（「更新」走的是同一条路）→ 是否**真的起了**这次下载。

        下载（网络 + 写临时文件）在后台线程；校验与并库在主线程槽里做——宿主库与安装登记
        都不许跨线程写（与 pet_balance"记账在主线程"同款）。
        """
        host = self._host_ref()
        idx = self._index_ref()
        if host is None or idx is None:
            _warn(self, "安装插件", "插件宿主未接线，装不了（重启一次桌宠即可）。")
            return False
        if not isinstance(entry, dict) or not entry.get("installable"):
            _warn(self, "安装插件", "这个条目不能装：%s"
                  % (entry.get("reason") if isinstance(entry, dict) else "条目不可用"))
            return False
        if self._pack_active is not None:
            self._set_hint("上一个下载还没结束，等它落地（不会起第二个下载）。")
            return False
        idx.cleanup()                 # 顺手清掉上次崩溃 / 被丢弃留下的临时下载
        gen = int(self._pack_gen) + 1
        self._pack_gen = gen
        self._pack_active = gen
        self._pack_entry = dict(entry)
        self._progress.setRange(0, 0)
        self._progress.setVisible(True)
        self._set_hint("正在下载「%s」（%s）…" % (entry.get("name") or entry.get("id"),
                                                entry.get("size_text") or "大小未知"))
        self._sync_buttons()
        try:
            threading.Thread(target=self._download_worker, args=(gen, idx),
                             daemon=True).start()
        except Exception as e:
            self._pack_retire(gen, "线程启动失败：%r" % (e,))
            self._progress.setVisible(False)
            self._set_hint("下载失败：%r" % (e,))
            self._sync_buttons()
            _warn(self, "安装插件失败", "起不了下载线程：%r" % (e,))
            return False
        return True

    def _download_worker(self, gen, idx):
        """后台线程：只下载 + 落临时文件。**不碰 Qt 控件，也不碰宿主库**。"""

        def _progress(done, total):
            self._emit_safe("packProgress", gen, int(done or 0), int(total or 0))

        try:
            path, err = idx.download(self._pack_entry, progress=_progress)
        except Exception as e:
            path, err = None, "下载失败：%r" % (e,)
        if not self._emit_safe("packReady", gen, path, err):
            if path:
                idx.cleanup()         # 主线程不要这一代了：临时文件不许留下
            self._pack_retire(gen, "结果没能交给主线程")

    def _on_pack_progress(self, gen, done, total):
        """下载进度（主线程槽）：只有当前那一代才画。"""
        if self._pack_active != gen:
            return
        if total > 0:
            self._progress.setRange(0, 100)
            self._progress.setValue(max(0, min(100, int(done * 100 / total))))
            self._set_hint("正在下载…%d%%（%s / %s）"
                           % (self._progress.value(),
                              pet_plugin_index.format_size(done),
                              pet_plugin_index.format_size(total)))
        else:
            self._progress.setRange(0, 0)
            self._set_hint("正在下载…%s" % pet_plugin_index.format_size(done))

    def _on_pack_ready(self, gen, path, err):
        """下载结果落地（主线程槽）：校验 + 并库都在这里做；临时文件无论如何都清掉。"""
        if self._closing_now():
            self._pack_retire(gen, "窗口已关闭，丢弃下载结果")
            self._drop_download(path)
            return
        if not self._pack_consume(gen, "pack"):
            self._drop_download(path)     # 旧代 / 被丢弃的结果：临时文件不留
            return
        entry = dict(self._pack_entry)
        idx = self._index_ref()
        self._progress.setVisible(False)
        if path is None or idx is None:
            msg = err or "下载失败"
            self._set_hint("下载失败：%s" % msg)
            self._sync_buttons()
            _warn(self, "下载插件失败", "%s\n\n插件目录与宿主内容一个字节都没动。" % msg)
            return
        already = str(entry.get("id") or "") in self._installed_map()
        self._set_hint("正在校验并安装「%s」…" % (entry.get("name") or entry.get("id")))
        ok, msg = idx.install_file(self._host_ref(), entry, path)
        if ok:
            _info(self, "插件已更新" if already else "插件已安装", msg)
        else:
            _warn(self, "安装插件失败", msg)
        self.refresh()

    def _pack_consume(self, gen, source):
        """槽端消费一代：只有当前那一代才放行（旧代丢弃并记日志）。"""
        cur = self._pack_active
        if cur != gen:
            self._index_log("丢弃旧代下载结果 %s（代次 %s 已过期，当前在途 %r）"
                            % (source, gen, cur))
            return False
        self._pack_active = None
        return True

    def _pack_retire(self, gen, why):
        """把 gen 那一代收尾（只在它仍是当前那一代时生效）。"""
        if self._pack_active == gen:
            self._pack_active = None
        self._index_log("下载代次 %s 由收尾路径结束（%s）" % (gen, why))

    def _drop_download(self, path):
        """删掉一个下载临时文件（结果被丢弃的路径上，别把临时文件留下）。"""
        try:
            if path and os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass    # 有意忽略：删不掉不影响正确性（下次 install_entry / cleanup 还会清）

    # ---------- 后台线程的安全出口 ----------
    def _closing_now(self):
        """在退出中？取属性本身也可能抛（对象已销毁）——抛一律按"在退出"处理。"""
        try:
            return bool(self._closing)
        except Exception:
            return True     # 有意忽略：宁可不发，也不把异常带进 daemon 线程

    def _emit_safe(self, name, *args):
        """从后台线程 emit 一个信号；窗口已关闭 / 对象已销毁就不发（返回 False）。

        与 pet_balance 的 _emit 同款：emit 到已销毁的 C++ 对象会抛 RuntimeError，而这是
        daemon 线程，异常只会往 stderr 打一行就没了——所以这里必须自己兜住。
        """
        if self._closing_now():
            return False
        try:
            getattr(self, name).emit(*args)
            return True
        except Exception as e:
            self._index_log("emit %s 失败：%r" % (name, e))
            return False

    def _index_log(self, msg):
        """守卫路径 / 后台线程的日志：日志自身失败绝不影响流程（与 pet_balance 同口径）。"""
        try:
            pet_log.log_error("plugin market: %s" % msg)
        except Exception:
            pass    # 有意忽略：日志通道失败无处可记

    # ---------- 动作（界面只做确认与提示，落地全在 pet_plugin_host） ----------
    def _install_selected(self):
        """安装选中的索引条目（没装过的）。"""
        entry = self._selected_entry()
        if entry is None:
            _warn(self, "安装插件", "请先在「可安装」页签里选中一个插件。")
            return False
        return self.install_entry(entry)

    def _update_selected(self):
        """更新选中的索引条目（装过且有更高版本）。"""
        entry = self._selected_entry()
        if entry is None:
            _warn(self, "更新插件", "请先在「可安装」页签里选中一个插件。")
            return False
        rec = self._installed_map().get(str(entry.get("id") or ""))
        if not _plugin_update_available(rec, entry):
            _warn(self, "更新插件", "这个插件没有更新的版本。")
            return False
        return self.install_entry(entry)

    def _install(self):
        """安装：选一个本地 zip（「可安装」页签是从索引下载安装）。"""
        path, _filter = QFileDialog.getOpenFileName(
            self, "选择插件包", "", "插件包 (*.zip);;所有文件 (*)")
        if path:
            self.install_path(path)

    def install_path(self, path):
        """安装指定 zip → 是否装上。公开给测试与"下载后安装"用（绕开文件选择框）。"""
        host = self._host_ref()
        if host is None:
            _warn(self, "安装插件", "插件宿主未接线，装不了（重启一次桌宠即可）。")
            return False
        ok, msg = host.install_zip(path)
        if ok:
            _info(self, "安装插件", msg)
        else:
            _warn(self, "安装插件失败", msg)
        self.refresh()
        return ok

    def _uninstall(self):
        rec = self._selected()
        if rec is None:
            _warn(self, "卸载插件", "请先在列表里选中一个插件。")
            return False
        pid = str(rec.get("id") or "")
        if not _confirm(self, "卸载插件",
                        "确定卸载插件「%s」？\n\n"
                        "· 只删除插件目录 plugins/%s/；\n"
                        "· 插件已经导入的角色 / 台词会**保留**——那是你的数据，"
                        "与「导入角色包」同口径，不随插件一起删。" % (pid, pid)):
            return False
        return self.uninstall_id(pid)

    def uninstall_id(self, pid):
        """卸载指定插件 → 是否成功（文案里点明保留了什么）。"""
        host = self._host_ref()
        if host is None:
            _warn(self, "卸载插件", "插件宿主未接线，卸不了（重启一次桌宠即可）。")
            return False
        ok, msg = host.uninstall(pid)
        if ok:
            _info(self, "卸载插件", msg)
        else:
            _warn(self, "卸载插件失败", msg)
        self.refresh()
        return ok

    def _rollback(self):
        rec = self._selected()
        if rec is None:
            _warn(self, "回滚插件", "请先在「已安装」页签里选中一个插件。")
            return False
        pid = str(rec.get("id") or "")
        if not _confirm(self, "回滚插件",
                        "确定把插件「%s」回滚到上一版？\n\n"
                        "· 恢复上一版的插件目录；\n"
                        "· 只撤销**这一版新导入**的内容——你自己的角色 / 台词 / 音效"
                        "一件都不会动。" % pid):
            return False
        return self.rollback_id(pid)

    def rollback_id(self, pid):
        """回滚指定插件 → 是否成功（文案里写清楚撤销了什么）。"""
        host = self._host_ref()
        if host is None:
            _warn(self, "回滚插件", "插件宿主未接线，回滚不了（重启一次桌宠即可）。")
            return False
        ok, msg = host.rollback(pid)
        if ok:
            _info(self, "回滚插件", msg)
        else:
            _warn(self, "回滚插件失败", msg)
        self.refresh()
        return ok

    def _toggle(self):
        rec = self._selected()
        if rec is None:
            _warn(self, "启用 / 禁用", "请先在列表里选中一个插件。")
            return False
        return self.set_enabled_id(str(rec.get("id") or ""), not bool(rec.get("enabled", True)))

    def set_enabled_id(self, pid, on):
        """启用 / 禁用指定插件（只改登记，文件保留，可逆）。"""
        host = self._host_ref()
        if host is None:
            _warn(self, "启用 / 禁用", "插件宿主未接线，改不了（重启一次桌宠即可）。")
            return False
        ok, msg = host.set_enabled(pid, on)
        if ok:
            _info(self, "启用 / 禁用", msg)
        else:
            _warn(self, "启用 / 禁用失败", msg)
        self.refresh()
        return ok


def open_plugins(pet):
    """v2.5.1：插件管理入口（菜单「⚙️ 设置… → 🧩 插件管理…」）。"""
    try:
        dlg = PluginManagerDialog(pet)
        modal(dlg)
    except Exception as e:
        _dialog_failed(pet, "插件管理", e)
