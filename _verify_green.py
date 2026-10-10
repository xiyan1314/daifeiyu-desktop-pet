# -*- coding: utf-8 -*-
"""绿色版成品检测（发布前检测环节）。

由绿色版自带的 python.exe 在绿色版目录内运行：真实启动桌宠主程序（offscreen），
覆盖关键子系统与角色/菜单/记账路径，全部通过返回 0。

用法（在绿色版目录内）：
    .\python.exe _verify_green.py
运行时数据隔离到临时目录，不污染绿色版；退出时清理。
"""
import os
import sys

sys.dont_write_bytecode = True  # v2.1.4：检测不得在绿色版目录里生成 __pycache__（会让发布检测假失败）
import tempfile
import shutil
import time

os.environ.setdefault("PYTHONIOENCODING", "utf-8")  # 中文 Windows GBK 控制台
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# env 变量对 stdio 无效（启动时已定死编码）：直接 reconfigure
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass  # 有意忽略：stdio reconfigure 失败仍可按默认编码输出（尽力而为）
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # 绿色版目录：导入的是打包产物，不是源码树

_tmp = tempfile.mkdtemp(prefix="dfy_green_")
FAILS = []


def check(name, cond, extra=""):
    print("%s %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        FAILS.append(name)


import pet_resources  # noqa: E402
import pet_dialogs  # noqa: E402
import 桌宠 as main  # noqa: E402
main.DATA_DIR = _tmp
main.CONFIG_PATH = os.path.join(_tmp, "config.json")
main.USAGE_PATH = os.path.join(_tmp, "usage.json")
main.MEMORY_PATH = os.path.join(_tmp, "memory.json")  # P1-6：记忆文件同样隔离到临时目录
main.pet_log.set_data_dir(_tmp)  # P0-2：pet_* 直连日志同样隔离

check("green version", main.VERSION == "2.2.3", main.VERSION)

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
app.setStyleSheet(main.MENU_QSS)

pet = main.PetWindow()
check("window boot", pet.width() > 20 and pet.height() > 20)
check("default sprites", pet.sprites["normal"]["side"].width() > 20)
check("book ok", pet.book is not None)
check("role/audio lib ok", pet.role_lib is not None and pet.audio_lib is not None)
check("lines pools ok", len(pet.lines_pools.get("sajiao", [])) > 0)
check("default idle frames", pet.has_frames and len(pet.anim._sets.get("idle", [])) > 0)
check("assets fx present", os.path.isdir(os.path.join(HERE, "assets", "fx"))
      and os.path.isdir(os.path.join(HERE, "assets", "sounds")))

# 菜单构建（stub exec）
from PySide6.QtCore import QPoint  # noqa: E402


class _Menu(main.QMenu):
    def exec(self, *_a, **_k):
        self._captured = self.actions()
        return None


_real_menu = main.QMenu
main.QMenu = _Menu
try:
    pet._open_menu(QPoint(100, 100))
    import gc
    top = []
    for obj in gc.get_objects():
        if isinstance(obj, _Menu) and getattr(obj, "_captured", None) is not None:
            top = [a.text() for a in obj._captured if a.text()]
            break
    check("menu compact", len(top) <= 18, "top=%d" % len(top))
    check("menu has slider", any(isinstance(a, main.QWidgetAction)
                                  for a in gc.get_objects() if isinstance(a, main.QWidgetAction)))
finally:
    main.QMenu = _real_menu

# 记账
pet.book.add_manual(3.5, "检测")
check("book write", abs(pet.book.today_usage() - 3.5) < 0.001)

# 帧动画角色端到端（导入 → 动画 → 删除）
from PySide6.QtGui import QImage, QPainter, QColor  # noqa: E402


def mkpng(path, size, color):
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    p.setBrush(QColor(color))
    p.drawEllipse(8, 8, size - 16, size - 16)
    p.end()
    img.save(path, "PNG")


frames = []
for i in range(2):
    src = os.path.join(_tmp, "g%d.png" % i)
    out = os.path.join(_tmp, "g%d_p.png" % i)
    mkpng(src, 100 + i * 20, "#ff5b7a")
    okf, _n = pet_dialogs._prepare_role_png(src, out)
    check("frame prep %d" % i, okf)
    frames.append(out)
role, err = pet.role_lib.import_processed(frames[0], None, "检测角色", frames_src=frames)
check("frames import", role is not None and err is None, "err=%r" % (err,))
if role:
    pet.apply_role(role["id"])
    check("frames animate", pet._custom_role and pet.has_frames
          and len(pet.anim._sets.get("idle", [])) == 2)
    pet.apply_role("")
    pet.role_lib.delete(role["id"])
    check("frames cleaned", not os.path.exists(os.path.join(_tmp, "roles", role["id"] + ".png")))

# 抽帧链路：QtMultimedia ffmpeg 后端与 GIF 插件必须打进包（本版头条功能）
check("multimedia backend", os.path.isfile(os.path.join(
    HERE, "Lib", "site-packages", "PySide6", "plugins", "multimedia", "ffmpegmediaplugin.dll")))
check("gif plugin", os.path.isfile(os.path.join(
    HERE, "Lib", "site-packages", "PySide6", "plugins", "imageformats", "qgif.dll")))
# 正向抽帧（检测环节临时拷入 _verify_assets，跑完由外部移除；缺失则跳过）
_vid = os.path.join(HERE, "_verify_assets", "sample.mp4")
if os.path.isfile(_vid):
    _rd = tempfile.mkdtemp(prefix="role_rawg_")
    _raws, _errv = pet_dialogs._extract_video_frames(_vid, _rd)
    check("video extract in green", _raws is not None and len(_raws) >= 2,
          "n=%s err=%r" % (len(_raws) if _raws else 0, _errv))
    shutil.rmtree(_rd, ignore_errors=True)
else:
    check("video extract in green", False, "missing _verify_assets/sample.mp4")

pet._quit()
shutil.rmtree(_tmp, ignore_errors=True)
print("=" * 40)
print("GREEN CHECKS: %d FAILS" % len(FAILS))
if FAILS:
    print("FAILED:")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("GREEN VERIFY OK")
