# -*- coding: utf-8 -*-
"""v2.8.0 第 6 轮（代理 A · 交互面）：插件索引来源的设置入口 + 反馈清账 + _toast 行为层。

覆盖（编号对齐 _dev/task_v280_round.md 的 A 段与 _dev/audit_feedback_v270.md §5）：
  · A1 插件 Phase 3 的**设置入口与交互**：显示随包/远端 · 可填可改可恢复默认 ·
    地址当场校验并说清原因（非 https / file:// / 本地路径 / 空 / 超长）· 刷新失败的人话
    提示 + 可回退路径 · 刷新成功后「远端索引已更新（共 N 个插件）」且列表真的重画；
  · A2 P2-5（静态输入框 5 处改手工建框 + modal，帧动作那处按裁决保留）· P2-7/N13
    （合成框补「取消」）· P3-5/S14/S15（清除片段确认 + 回执、导入回执）· N14（添加形态回执）·
    D9（移除成员回执）· D14（删自定义动作确认 + 回执）· P3-6（新建/添加文案对照表）；
  · A3 _toast 的行为层：_closing 时 show_bubble → False、_toast → False，且**仍有兜底**
    （窗口内状态行 / 限流日志）。

写法沿用仓内既有套路（tests/test_dialogs_feedback_v270.py / test_plugin_market_v252.py）：
  · offscreen；**永不联网**（autouse 守卫把 default_fetch 换成"远端一调用就炸"）；
  · 不 exec() 模态：_warn/_info/_confirm 换成记录器（offscreen 下 exec 会挂死进程）；
  · 断言结构性事实（谁被调用了 / 盘上有什么 / 返回值是什么），不看耗时（铁律 3）。
"""
import json
import os
import sys
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pet_config          # noqa: E402
import pet_dialogs         # noqa: E402
import pet_lines           # noqa: E402
import pet_log             # noqa: E402
import pet_plugin_host     # noqa: E402
import pet_plugin_index    # noqa: E402

from PySide6.QtCore import QEventLoop, Qt, QTimer   # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton   # noqa: E402

HOST = "2.5.0"
SRC_PATH = os.path.join(ROOT, "pet_dialogs.py")

_APP = QApplication.instance()
if _APP is None:
    _APP = QApplication([])

_REAL_DEFAULT_FETCH = pet_plugin_index.default_fetch


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """**远端**取数一调用就炸（本文件永不联网）；本地路径照旧（随包索引要读）。"""
    def _guarded(url, progress=None, limit=0):
        if pet_plugin_index.is_remote(url):
            raise AssertionError("测试里不许真联网（远端取数必须注入 fetch）：%s" % url)
        return _REAL_DEFAULT_FETCH(url, progress, limit=limit)
    monkeypatch.setattr(pet_plugin_index, "default_fetch", _guarded)
    return _guarded


# ---------------- 替身：宿主 / 取数 / 索引器 ----------------

class _Pet(object):
    """最小宿主替身：插件宿主 + 配置读写 + 气泡记录（不碰真 PetWindow）。"""

    def __init__(self, host, cfg=None):
        self.plugin_host = host
        self.cfg = dict(cfg or {})
        self.saved = []
        self.fail_save = ""
        self.bubbles = []

    @property
    def plugin_index_url(self):
        return str(self.cfg.get(pet_config.PLUGIN_INDEX_URL_KEY) or "")

    def save_config(self, cfg):
        if self.fail_save:
            return self.fail_save
        self.saved.append(dict(cfg))
        self.cfg = dict(cfg)
        return None

    def show_bubble(self, text):
        self.bubbles.append(text)


def _index_bytes(plugins, host_min="2.0.0"):
    return json.dumps({"index_version": 1, "updated_at": "2026-01-01",
                       "host_min": host_min, "plugins": list(plugins)},
                      ensure_ascii=False).encode("utf-8")


def _entry(pid="market-lines", version="1.0.0"):
    return {"id": pid, "name": "市场包", "kind": "data", "data_kind": "lines", "code": False,
            "summary": "一句话", "author": "测试",
            "releases": [{"version": version, "min_host_version": HOST, "api_version": 1,
                          "url": "packs/x.zip", "sha256": "a" * 64, "bytes": 10,
                          "published_at": "2026-01-01"}]}


class _Fetcher(object):
    """假取数：url → (bytes|None, err)。记下每次取数发生在哪个线程。"""

    def __init__(self, table=None, err=None):
        self.table = dict(table or {})
        self.err = err
        self.calls = []
        self.threads = []

    def __call__(self, url, progress=None, limit=0):
        self.calls.append(url)
        self.threads.append(threading.get_ident())
        if self.err:
            return None, self.err
        data = self.table.get(url)
        if data is None:
            return None, "HTTP 404：找不到这个地址（%s）" % url
        return data, ""


def _host(tmp_path):
    lib = pet_lines.LineService(str(tmp_path))
    return pet_plugin_host.PluginHost(str(tmp_path), HOST, lines_lib=lib)


def _plugins_dir(tmp_path):
    d = tmp_path / "plugins"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _real_index(tmp_path, fetcher, index_url="", pet=None):
    """真 PluginIndex（B 的实现），取数注入 -- 老构造调用逐位兼容。"""
    return pet_plugin_index.PluginIndex(
        str(_plugins_dir(tmp_path)), fetch=fetcher, index_url=index_url, host_version=HOST,
        landing_kinds=pet_plugin_host.LANDING_KINDS,
        cfg_getter=(lambda: pet.cfg) if pet is not None else None,
        save_cfg=(pet.save_config if pet is not None else None))


class _FakeIndex(object):
    """A 侧消费端的替身：只实现对话框用到的四个入口（**不联网**）。"""

    def __init__(self, index_url="", entries=None, set_result=(True, "已改用远端索引"),
                 refresh_result=(True, "远端索引已更新（共 2 个插件，其中 2 个可安装）", 2),
                 with_set=True):
        self._index_url = index_url
        self.entries = list(entries or [])
        self.set_result = set_result
        self.refresh_result = refresh_result
        self.set_calls = []
        self.forces = []
        self.loads = []          # v2.8.0 找茬 F1：补发用例要数"注入后端被读了几次"
        if not with_set:
            # 只去掉 set_remote_base（模拟"后端还没接线"），其余照旧
            self.set_remote_base = None

    @property
    def index_url(self):
        return self._index_url

    def load_index(self):
        self.loads.append(1)
        return {"source": "远端索引", "entries": list(self.entries), "problems": []}, ""

    def source_info(self):
        return {"kind": "remote" if self._index_url else "bundled", "url": self._index_url,
                "updated_at": "2026-01-01", "count": len(self.entries), "cached": True,
                "fetched_at": "2026-01-02"}

    def cleanup(self):
        pass


def _fake_set(self, url):
    self.set_calls.append(url)
    if self.set_result and self.set_result[0]:
        self._index_url = url
    return self.set_result


def _fake_refresh(self, force=False):
    self.forces.append(bool(force))
    return self.refresh_result


_FakeIndex.set_remote_base = _fake_set
_FakeIndex.refresh = _fake_refresh


class _SyncThreads(object):
    """`pet_dialogs.threading` 的替身：Thread(...).start() **当场同步跑**目标函数。

    v2.8.0 找茬 F1 的用例要问"补发那次取数到底有没有发生"：真起后台线程就得等它，
    判据会变成"时间"（铁律 3 不许）。同步跑之后，答案完全由**注入后端的调用次数**给出。
    只覆盖 pet_dialogs 实际用到的 Thread(target=…, args=…, daemon=…).start()。
    """

    def __init__(self):
        self.started = []
        outer = self

        class _Thread(object):
            def __init__(self, target=None, args=(), daemon=None, **_kw):
                self.target = target
                self.args = tuple(args or ())
                self.daemon = bool(daemon)
                outer.started.append(target)

            def start(self):
                self.target(*self.args)

            def join(self, timeout=None):
                return None

            def is_alive(self):
                return False

        self.Thread = _Thread


# ---------------- 模态 / 气泡都换成记录器 ----------------

class _UI(object):
    """把 _warn/_info/_confirm 换成记录器，并允许用例改 confirm 结论。"""

    def __init__(self, monkeypatch):
        self.warn = []
        self.info = []
        self.confirm_result = True

        def _w(parent, title, text):
            self.warn.append((str(title), str(text)))

        def _i(parent, title, text):
            self.info.append((str(title), str(text)))

        monkeypatch.setattr(pet_dialogs, "_warn", _w)
        monkeypatch.setattr(pet_dialogs, "_info", _i)
        monkeypatch.setattr(pet_dialogs, "_confirm",
                            lambda _p, _t, _x: self.confirm_result)

    def warns_text(self):
        return "\n".join(t for _title, t in self.warn)


@pytest.fixture
def quiet(monkeypatch):
    return _UI(monkeypatch)


# ---------------- 真 PetWindow（A3 / 真实对话框用；照抄 test_dialogs_feedback_v270） ----------------

PET_TMP = {}


def _ensure_qapplication():
    app = QApplication.instance()
    if isinstance(app, QApplication):
        return app
    pytest.fail("进程里只有 QCoreApplication（不是 QApplication），QWidget 无法构造",
                pytrace=False)


def _shutdown_pet(win):
    try:
        win._closing = True
    except Exception:
        pass  # 有意忽略：测试收尾尽力而为
    try:
        win.voice.stop()
    except Exception:
        pass  # 有意忽略：没有语音服务时跳过
    for _t in win.findChildren(QTimer):
        try:
            _t.stop()
        except Exception:
            pass  # 有意忽略：单个定时器停不掉不影响其余
    try:
        win.hide()
        win.close()
        win.deleteLater()
    except Exception:
        pass  # 有意忽略：测试收尾尽力而为


@pytest.fixture(scope="module")
def pet(tmp_path_factory):
    """真 PetWindow + 全部运行时路径指向临时目录（退出时还原进程级全局）。"""
    import 桌宠 as main
    import pet_resources as _pr
    tmp = tmp_path_factory.mktemp("dlgfeedback280")
    PET_TMP["dir"] = str(tmp)
    _snap = (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
             getattr(pet_log, "_data_dir", None), getattr(main, "_redact_key", None),
             getattr(_pr, "FRAME_MAX", None))
    main.DATA_DIR = str(tmp)
    main.CONFIG_PATH = str(tmp / "config.json")
    main.USAGE_PATH = str(tmp / "usage.json")
    main.MEMORY_PATH = str(tmp / "memory.json")
    pet_log.set_data_dir(str(tmp))
    _ensure_qapplication()
    win = main.PetWindow()
    yield win
    _shutdown_pet(win)
    QApplication.processEvents()
    (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH,
     main.MEMORY_PATH) = _snap[0], _snap[1], _snap[2], _snap[3]
    pet_log.set_data_dir(_snap[4])
    main.set_redact_key(_snap[5] or "")
    if _snap[6] is not None:
        _pr.FRAME_MAX = _snap[6]


@pytest.fixture
def ui(pet, monkeypatch):
    """真 pet + 模态记录器 + 气泡记录器。"""
    seen = {"warn": [], "info": [], "confirm": True, "toast": []}

    def _w(parent, title, text):
        seen["warn"].append((str(title), str(text)))

    def _i(parent, title, text):
        seen["info"].append((str(title), str(text)))

    monkeypatch.setattr(pet_dialogs, "_warn", _w)
    monkeypatch.setattr(pet_dialogs, "_info", _i)
    monkeypatch.setattr(pet_dialogs, "_confirm", lambda _p, _t, _x: seen["confirm"])
    monkeypatch.setattr(pet, "show_bubble", lambda text: seen["toast"].append(text))
    return seen


def _log_text():
    """读日志正文：**按 pet_log 的当前目录读**。

    tests/conftest.py 的 autouse 夹具（_isolate_log_dir）会给**每条用例**换一个 tmp_path，
    所以日志落点不等于本模块 pet fixture 自己的临时目录——照 _data_dir 读才是同一条真相。
    """
    d = str(getattr(pet_log, "_data_dir", "") or PET_TMP.get("dir", ""))
    p = os.path.join(d, "error.log")
    if not os.path.isfile(p):
        return ""
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def _feed_source(dlg, res, gen=11):
    """把一次"远端刷新结果"直接喂给主线程槽（确定性：不起线程、不等事件循环）。"""
    dlg._index_active = gen
    dlg._on_source_ready(gen, res)
    return res


def _read_src():
    import io
    return io.open(SRC_PATH, encoding="utf-8").read()


def _enclosing_def_name(src, idx):
    head = src[:idx]
    pos = head.rfind("\n    def ")
    line = head[pos + 1:].split("\n", 1)[0].strip()
    return line[len("def "):].split("(")[0]


# ==================== 一、A1：索引来源（设置入口） ====================

def test_source_defaults_to_bundled_and_opening_never_networks(tmp_path, quiet):
    """默认 = 随包索引：打开对话框只读本地，一个网络请求都不发（默认零打扰）。"""
    pet = _Pet(_host(tmp_path))
    fetcher = _Fetcher()
    idx = _real_index(tmp_path, fetcher, index_url="", pet=pet)
    dlg = pet_dialogs.PluginManagerDialog(pet, index=idx)
    try:
        assert "随包索引" in dlg._src_label.text(), dlg._src_label.text()
        assert dlg._url_edit.text() == "", "默认不该往输入框里塞东西"
        assert fetcher.calls == [], "打开对话框就联网了：%r" % (fetcher.calls,)
    finally:
        dlg.close()


def test_source_shows_remote_from_config_without_network(tmp_path, quiet):
    """配置里已有远端地址 → 显示成远端索引；打开对话框仍然**不联网**。"""
    pet = _Pet(_host(tmp_path), cfg={pet_config.PLUGIN_INDEX_URL_KEY:
                                     "https://h.invalid/packs/index.json"})
    fetcher = _Fetcher()
    idx = _real_index(tmp_path, fetcher,
                      index_url=pet.cfg[pet_config.PLUGIN_INDEX_URL_KEY], pet=pet)
    dlg = pet_dialogs.PluginManagerDialog(pet, index=idx)
    try:
        text = dlg._src_label.text()
        assert "远端索引" in text and "h.invalid" in text, text
        assert "还没取回来" in text, "没有缓存却没告诉用户还要点「刷新索引」：%s" % text
        assert dlg._url_edit.text() == "https://h.invalid/packs/index.json"
        assert fetcher.calls == [], "打开对话框就联网了：%r" % (fetcher.calls,)
    finally:
        dlg.close()


BAD_URLS = (
    ("http://h.invalid/packs/index.json", "https"),
    ("file:///C:/packs/index.json", "本地路径"),
    ("C:\\packs\\index.json", "本地路径"),
    ("/home/me/packs/index.json", "本地路径"),
    ("ftp://h.invalid/index.json", "https"),
    ("https://", "主机名"),
    ("https://h.invalid/" + "x" * 2100, "太长"),
)


@pytest.mark.parametrize("url,needle", BAD_URLS)
def test_bad_source_url_is_rejected_on_the_spot_with_a_reason(tmp_path, quiet, url, needle):
    """非 https / 本地路径 / file:// / 无主机名 / 超长 → **当场拒绝并说清为什么**。

    拒绝必须发生在**写配置之前**：pet.saved 为空、cfg 里一个字符都没变。
    """
    pet = _Pet(_host(tmp_path))
    idx = _FakeIndex(index_url="")
    dlg = pet_dialogs.PluginManagerDialog(pet, index=idx)
    try:
        assert dlg.set_index_source(url) is False, "非法地址被放行了：%r" % (url,)
        assert quiet.warn, "非法地址被拒绝却什么都没说"
        assert needle in quiet.warns_text(), quiet.warns_text()
        assert pet.saved == [] and pet.cfg == {}, "被拒的地址居然写了配置"
        assert idx.set_calls == [], "界面已经拒了，还把地址交给了后端"
        assert "当前：随包索引" in dlg._src_label.text(), dlg._src_label.text()
    finally:
        dlg.close()


def test_empty_save_is_rejected_and_points_at_reset(tmp_path, quiet):
    """空地址点「保存并使用」→ 当场拒绝，并指明"要回随包索引请点恢复默认"。"""
    pet = _Pet(_host(tmp_path))
    dlg = pet_dialogs.PluginManagerDialog(pet, index=_FakeIndex(index_url=""))
    try:
        assert dlg.set_index_source("") is False
        assert "恢复默认" in quiet.warns_text(), quiet.warns_text()
        assert pet.saved == [] and pet.cfg == {}
    finally:
        dlg.close()


def test_saving_a_good_url_uses_the_backend_and_tells_the_next_step(tmp_path, quiet):
    """合法地址 → 交给后端保存；回执说明"远端索引要再点刷新索引"；**保存本身不联网**。"""
    pet = _Pet(_host(tmp_path))
    idx = _FakeIndex(index_url="",
                     set_result=(True, "已改用远端索引：https://h.invalid/（点「刷新索引」取回列表）"))
    dlg = pet_dialogs.PluginManagerDialog(pet, index=idx)
    try:
        assert dlg.set_index_source("  https://h.invalid/  ") is True
        assert idx.set_calls == ["https://h.invalid/"], "地址没有原样交给后端：%r" % (idx.set_calls,)
        assert "远端索引" in dlg._src_label.text(), dlg._src_label.text()
        assert dlg._url_edit.text() == "https://h.invalid/"
        assert pet.bubbles and "刷新索引" in pet.bubbles[-1], pet.bubbles
    finally:
        dlg.close()


def test_backend_write_failure_keeps_window_and_reports_the_reason(tmp_path, quiet):
    """后端写配置失败 → 如实回报（不假装存下了）：窗口不关、原因可见、cfg 不变。"""
    pet = _Pet(_host(tmp_path))
    idx = _FakeIndex(index_url="https://old.invalid/index.json",
                     set_result=(False, "索引地址没能保存：磁盘只读（盘上还是原值，这次改动没有生效）"))
    dlg = pet_dialogs.PluginManagerDialog(pet, index=idx)
    try:
        assert dlg.set_index_source("https://new.invalid/index.json") is False
        assert "磁盘只读" in quiet.warns_text(), quiet.warns_text()
        assert pet.cfg == {}, "失败了却把地址写进了配置"
        assert not pet.bubbles, "失败了还报成功气泡：%r" % (pet.bubbles,)
    finally:
        dlg.close()


def test_reset_to_bundled_takes_effect_and_reports(tmp_path, quiet):
    """「恢复默认」→ 清掉远端基址、回到随包索引，并给一句回执（本地直读，不联网）。"""
    d = _plugins_dir(tmp_path)
    (d / "index.json").write_bytes(_index_bytes([_entry()]))
    pet = _Pet(_host(tmp_path), cfg={pet_config.PLUGIN_INDEX_URL_KEY:
                                     "https://h.invalid/index.json"})
    idx = _FakeIndex(index_url=pet.cfg[pet_config.PLUGIN_INDEX_URL_KEY],
                     set_result=(True, "已恢复为随包索引（index.json，不联网）"))
    dlg = pet_dialogs.PluginManagerDialog(pet, index=idx)
    try:
        assert dlg.set_index_source("", clearing=True) is True
        assert idx.set_calls == [""], "恢复默认没有把空地址交给后端：%r" % (idx.set_calls,)
        assert "随包索引" in dlg._src_label.text(), dlg._src_label.text()
        assert dlg._url_edit.text() == ""
        assert pet.bubbles and "随包索引" in pet.bubbles[-1], pet.bubbles
    finally:
        dlg.close()


def test_backend_without_set_remote_base_degrades_with_a_human_message(tmp_path, quiet):
    """后端没接线（没有 set_remote_base）→ 一句人话，绝不抛异常。"""
    pet = _Pet(_host(tmp_path))
    dlg = pet_dialogs.PluginManagerDialog(pet, index=_FakeIndex(with_set=False))
    try:
        assert dlg.set_index_source("https://h.invalid/index.json") is False
        assert "set_remote_base" in quiet.warns_text(), quiet.warns_text()
    finally:
        dlg.close()


def test_dialog_wires_cfg_read_and_write_into_the_backend(tmp_path, quiet):
    """对话框**自己**现造的索引器要接上配置读写（B 的 set_remote_base 靠它落盘）。

    这条走真后端：index=None → _index_ref() 现造 PluginIndex（cfg_getter / save_cfg 由
    本文件注入）→ set_remote_base 写进 pet.cfg 与 config（替身记录）。若 A 忘了注入，
    B 会如实回报"没有接线"，本用例红。
    """
    pet = _Pet(_host(tmp_path))
    dlg = pet_dialogs.PluginManagerDialog(pet)
    try:
        assert dlg._index_ref() is not None, "用例前提：宿主可用时索引器现造得出来"
        assert dlg.set_index_source("https://h.invalid/packs/index.json") is True
        assert pet.saved, "后端没有走注入的 save_cfg（配置一个字节都没落）"
        assert pet.cfg[pet_config.PLUGIN_INDEX_URL_KEY] == "https://h.invalid/packs/index.json"
        assert "远端索引" in dlg._src_label.text(), dlg._src_label.text()
    finally:
        dlg.close()


# ==================== 二、A1：刷新（成功 / 失败 / 线程边界） ====================

def test_refresh_success_reports_count_and_repaints_the_list(tmp_path, quiet):
    """刷新成功：明确告诉用户「远端索引已更新（共 N 个插件）」，且「可安装」真的重画。"""
    pet = _Pet(_host(tmp_path))
    entries = [_entry("a"), _entry("b")]
    idx = _FakeIndex(index_url="https://h.invalid/index.json", entries=entries,
                     refresh_result=(True, "远端索引已更新（共 2 个插件，其中 2 个可安装）", 2))
    dlg = pet_dialogs.PluginManagerDialog(pet, index=idx)
    try:
        _feed_source(dlg, idx.refresh_result)
        assert dlg._market.rowCount() == 2, "列表没有真的刷新（行数 %d）" % dlg._market.rowCount()
        text = dlg._hint.text()
        assert "远端索引已更新（共 2 个插件" in text, text
        assert pet.bubbles and "远端索引已更新（共 2 个插件" in pet.bubbles[-1], pet.bubbles
    finally:
        dlg.close()


FAIL_MESSAGES = (
    "网络请求失败：名称解析不了（连不上远端索引）",
    "HTTP 404：找不到这个地址",
    "下载后核对 sha256 不符（索引里写的是 xxx，实际拿到 yyy），已拒绝",
    "远端索引过大（8388608 字节，上限 4194304）",
)


@pytest.mark.parametrize("msg", FAIL_MESSAGES)
def test_refresh_failure_shows_the_reason_and_keeps_a_way_back(tmp_path, quiet, msg):
    """网络不可用 / 404 / sha256 不符 / 体积超限：每条一个明确文案 + 保留回退随包索引的路。

    失败时**表格一个字节都不动**（B 的 refresh 失败不碰缓存与随包索引，旧列表仍然可用）。
    """
    pet = _Pet(_host(tmp_path))
    idx = _FakeIndex(index_url="https://h.invalid/index.json", entries=[_entry("a")])
    dlg = pet_dialogs.PluginManagerDialog(pet, index=idx)
    try:
        _feed_source(dlg, (True, "远端索引已更新（共 1 个插件，其中 1 个可安装）", 1))
        assert dlg._market.rowCount() == 1, "用例前提：先有一份画好的表"
        quiet.warn.clear()
        pet.bubbles.clear()          # 前置那次成功自己会发气泡，这里只关心失败这一次

        _feed_source(dlg, (False, msg, 0))
        assert msg in quiet.warns_text(), quiet.warns_text()
        assert "恢复默认" in quiet.warns_text(), "失败提示里没有可回退的路：%s" % quiet.warns_text()
        assert "恢复默认" in dlg._hint.text(), dlg._hint.text()
        assert dlg._market.rowCount() == 1, "刷新失败把已经画好的列表清掉了"
        assert not pet.bubbles, "刷新失败却发了成功气泡"
    finally:
        dlg.close()


def test_refresh_missing_result_is_treated_as_failure(tmp_path, quiet):
    """后端返回 None（没拿到结果）→ 按失败处理（统一口径：None 也算失败）。"""
    pet = _Pet(_host(tmp_path))
    dlg = pet_dialogs.PluginManagerDialog(pet, index=_FakeIndex(index_url="https://h.invalid/x"))
    try:
        _feed_source(dlg, None)
        assert quiet.warn, "None 被当成了成功"
        assert "恢复默认" in quiet.warns_text()
    finally:
        dlg.close()


def _wait_source(dlg, ms=10000):
    """等一次在途取数落地（事件驱动；超时只是防挂死兜底，断言不看耗时）。"""
    loop = QEventLoop()
    dlg.sourceReady.connect(lambda *a: loop.quit())
    QTimer.singleShot(ms, loop.quit)
    if dlg._index_active is not None:
        loop.exec()


def test_refresh_runs_off_the_main_thread_and_lands_on_it(tmp_path, quiet):
    """网络不许卡界面：取数发生在**别的**线程；结果回到主线程槽后才动机（结构性事实）。"""
    pet = _Pet(_host(tmp_path))

    class _Slow(_FakeIndex):
        def __init__(self):
            _FakeIndex.__init__(self, index_url="https://h.invalid/index.json",
                                entries=[_entry("a")])
            self.threads = []

        def refresh(self, force=False):
            self.threads.append(threading.get_ident())
            return self.refresh_result

    slow = _Slow()
    dlg = pet_dialogs.PluginManagerDialog(pet, index=slow)
    try:
        got = []
        dlg.sourceReady.connect(lambda *a: got.append(a))
        assert dlg.refresh_index(manual=True) is True, "没起取数"
        _wait_source(dlg)
        assert slow.threads and slow.threads[0] != threading.get_ident(), \
            "取数跑在主线程上（会卡界面）"
        assert got, "结果没回到主线程槽"
        assert dlg._market.rowCount() == 1, "落地后没有重画列表"
    finally:
        dlg.close()


def test_manual_refresh_forces_and_auto_refresh_prefers_cache(tmp_path, quiet):
    """force 口径：用户点「刷新索引」= 无条件重取；自动补取 = 优先用缓存（不多联网）。"""
    pet = _Pet(_host(tmp_path))
    idx = _FakeIndex(index_url="https://h.invalid/index.json")
    dlg = pet_dialogs.PluginManagerDialog(pet, index=idx)
    try:
        dlg.refresh_index(manual=True)
        _wait_source(dlg)
        dlg.refresh_index(manual=False)
        _wait_source(dlg)
        assert idx.forces == [True, False], idx.forces
    finally:
        dlg.close()


def test_manual_refresh_while_in_flight_is_replayed_after_the_source_lands(
        tmp_path, quiet, monkeypatch):
    """F1（v2.8.0 找茬审查 · 阻断发布）：在途期间再点一次「刷新索引」→ 落地后**必须补发**。

    改前 pet_dialogs 的 import 行里没有 QTimer，而两处补发都是 `QTimer.singleShot(...)`：
    `_index_pending` 置上了、落地时却抛 NameError —— PySide6 只往 stderr 打一行 traceback
    就继续跑，绿色版的 pythonw **没有控制台**，对用户就是"再点一次没反应"（审查实测
    慢取数路径下 fetch 只有 1 次、replayed=false）。

    判据 = 注入后端的取数次数与 force 口径（**不看耗时**，铁律 3）。
    变异：把 QTimer 从 import 行删掉 → 本用例红（NameError 冒泡 / 取数不补发）。
    """
    pet = _Pet(_host(tmp_path))
    idx = _FakeIndex(index_url="https://h.invalid/index.json", entries=[_entry("a")])
    sync = _SyncThreads()
    monkeypatch.setattr(pet_dialogs, "threading", sync)
    dlg = pet_dialogs.PluginManagerDialog(pet, index=idx)
    try:
        gen = 41
        dlg._index_active = gen          # 第一次取数在途（结果已 emit、槽还没轮到跑）
        assert dlg.refresh_index(manual=True) is False, "在途期间不该起第二次取数"
        assert dlg._index_pending is True, "第二次点击没有被排队（直接丢了）"
        assert idx.forces == [], "排队那次当场取数了（在途守卫没生效）"
        dlg._on_source_ready(gen, (True, "远端索引已更新（共 1 个插件）", 1))
        QApplication.processEvents()     # 只让 singleShot(0) 那次补发跑起来
        assert idx.forces == [True], (
            "补发没有发生：在途期间那次点击被吞了（注入后端取数 %r，"
            "pending=%r）" % (idx.forces, dlg._index_pending))
    finally:
        dlg.close()


def test_manual_refresh_while_in_flight_is_replayed_on_the_read_path(
        tmp_path, quiet, monkeypatch):
    """F1 的第二处落点：`_on_index_ready`（远端但后端没有 refresh() → 走后台只读）。

    同一个缺陷有两个补发点，只测一处的话另一处被删掉也没人喊——所以两处各一条。
    变异：把 QTimer 从 import 行删掉 / 删掉 `if pending:` 那一块 → 本用例红。
    """
    pet = _Pet(_host(tmp_path))
    idx = _FakeIndex(index_url="https://h.invalid/index.json", entries=[_entry("a")])
    idx.refresh = None                   # 模拟"更老的后端 / 注入替身没接线" → 走后台只读
    sync = _SyncThreads()
    monkeypatch.setattr(pet_dialogs, "threading", sync)
    dlg = pet_dialogs.PluginManagerDialog(pet, index=idx)
    try:
        gen = 42
        dlg._index_active = gen
        assert dlg.refresh_index(manual=True) is False
        assert dlg._index_pending is True
        assert idx.loads == [], "排队那次当场读了索引"
        dlg._on_index_ready(gen, {"source": "远端索引", "entries": [_entry("a")],
                                  "problems": []}, "")
        QApplication.processEvents()
        assert idx.loads, "补发没有发生（后台只读这条路）：注入后端一次都没被读"
    finally:
        dlg.close()


def test_real_backend_failure_message_reaches_the_user(tmp_path, quiet):
    """契约双向：B 的真 refresh() 给出的失败原因，A 原样端到用户面前（不放宽、不改写）。"""
    pet = _Pet(_host(tmp_path), cfg={pet_config.PLUGIN_INDEX_URL_KEY:
                                     "https://h.invalid/packs/index.json"})
    fetcher = _Fetcher(err="网络请求失败：名字解析不了")
    idx = _real_index(tmp_path, fetcher,
                      index_url=pet.cfg[pet_config.PLUGIN_INDEX_URL_KEY], pet=pet)
    dlg = pet_dialogs.PluginManagerDialog(pet, index=idx)
    try:
        res = idx.refresh(True)          # 真后端：注入的取数返回一句人话
        assert res[0] is False and "名字解析不了" in res[1], res
        _feed_source(dlg, res)
        assert "名字解析不了" in quiet.warns_text(), quiet.warns_text()
        assert "恢复默认" in quiet.warns_text(), quiet.warns_text()
    finally:
        dlg.close()


def test_real_backend_refresh_success_reports_count_and_repaints(tmp_path, quiet):
    """契约双向（成功侧）：真后端 refresh() → 真缓存 → A 画表 + 报数。"""
    base = "https://h.invalid/packs/index.json"
    pet = _Pet(_host(tmp_path), cfg={pet_config.PLUGIN_INDEX_URL_KEY: base})
    fetcher = _Fetcher({base: _index_bytes([_entry("a"), _entry("b"), _entry("c")])})
    idx = _real_index(tmp_path, fetcher, index_url=base, pet=pet)
    dlg = pet_dialogs.PluginManagerDialog(pet, index=idx)
    try:
        res = idx.refresh(True)
        assert res[0] is True and res[2] == 3, res
        _feed_source(dlg, res)
        assert dlg._market.rowCount() == 3, "缓存里的条目没有画出来：%d" % dlg._market.rowCount()
        assert "远端索引已更新（共 3 个插件" in dlg._hint.text(), dlg._hint.text()
        # 刷新后再自动刷一次：B 会直接用缓存（不再联网）
        calls_before = len(fetcher.calls)
        res2 = idx.refresh(False)
        assert res2[0] is True and len(fetcher.calls) == calls_before, "force=False 又联网了"
    finally:
        dlg.close()


# ==================== 三、A3：_toast 的行为层 ====================

def test_show_bubble_reports_false_while_closing(pet):
    """退出守卫下气泡什么都不弹 —— 生产端必须**如实回报 False**（改前是隐含的 None）。"""
    pet._closing = False
    try:
        assert pet.show_bubble("活着的时候要能弹") is True, "正常路径没弹出来"
        assert pet.bubble.isVisible() is True
        pet._closing = True
        assert pet.show_bubble("退出中不该弹") is False, "退出守卫下 show_bubble 谎报了成功"
    finally:
        pet.bubble.hide()
        pet._closing = False


def test_toast_returns_false_and_logs_when_bubble_is_refused(pet):
    """A3 验收：_closing=True → _toast 返回 False，且反馈**仍有兜底**（限流日志留痕）。"""
    pet_log._THROTTLE_SEEN.clear()
    pet._closing = True
    try:
        assert pet_dialogs._toast(pet, "唯一文案：气泡被退出守卫拦下") is False
        text = _log_text()
        assert "唯一文案：气泡被退出守卫拦下" in text, "没有兜底日志，事后复盘什么都看不到"
        # 限流：同一句话在窗口内只落一条（连点保存不会把 error.log 刷满）
        assert pet_dialogs._toast(pet, "唯一文案：气泡被退出守卫拦下") is False
        assert _log_text().count("唯一文案：气泡被退出守卫拦下") == 1, "兜底日志没有限流"
    finally:
        pet._closing = False
        pet_log._THROTTLE_SEEN.clear()


def test_toast_falls_back_to_the_dialog_status_line(pet):
    """A3 兜底第二条出口：调用方给了状态行 → 同一句话写进窗口里（用户仍能在某处看到）。"""
    lbl = QLabel("")
    pet._closing = True
    try:
        assert pet_dialogs._toast(pet, "已保存（状态行兜底）", status=lbl) is False
        assert lbl.text() == "已保存（状态行兜底）", "有状态行却没写进去"
    finally:
        pet._closing = False


def test_toast_still_true_when_bubble_really_shows(pet):
    """控制组：正常路径不许被兜底逻辑带成 False（否则"成功也没气泡"会变成常态）。"""
    pet._closing = False
    try:
        assert pet_dialogs._toast(pet, "正常回执") is True
        assert pet.bubble.isVisible() is True
    finally:
        pet.bubble.hide()


def test_toast_none_return_still_counts_as_best_effort(pet):
    """老式替身（show_bubble 不返回值）→ 仍按"尽力而为"放行 True（不改既有口径）。"""
    class _Old(object):
        def show_bubble(self, text):
            return None

    assert pet_dialogs._toast(_Old(), "x") is True


def test_toast_falls_back_when_show_bubble_raises():
    """F3（v2.8.0 找茬审查）：show_bubble **抛异常**时也要走兜底——状态行 / 日志必须有回执。

    改前 except 分支只 `log_error` 就 return False：状态行一个字符没写（日志里也没有那句
    用户能看懂的回执），用户点了保存等于什么都没发生——而 `_toast_fallback` 自己的文档
    写的就是"气泡没能显示时的兜底"。
    变异：把 except 分支里的 `_toast_fallback(text, status)` 删掉 → 本用例红。
    """
    class _Boom(object):
        def show_bubble(self, text):
            raise RuntimeError("v280 气泡炸了")

    pet_log._THROTTLE_SEEN.clear()
    lbl = QLabel("")
    assert pet_dialogs._toast(_Boom(), "唯一文案：气泡抛异常也要有回执", status=lbl) is False
    assert lbl.text() == "唯一文案：气泡抛异常也要有回执", (
        "show_bubble 抛异常时状态行没写（用户零回执）：%r" % lbl.text())

    # 没有状态行的调用点（外层对话框没有提示行）：至少在 error.log 里留一句（限流）
    assert pet_dialogs._toast(_Boom(), "唯一文案：没有状态行就落日志") is False
    assert "唯一文案：没有状态行就落日志" in _log_text(), "抛异常时日志里也没有那句话"


# ==================== 四、A2：反馈清账 ====================

def test_compose_dialog_has_cancel_and_reject_adds_nothing(pet, ui, monkeypatch):
    """P2-7 / N13：「＋合成…」内联框必须有「取消」，取消要真的放弃编辑（不留半截）。"""
    seen = {}

    def _fake_modal(dlg):
        seen["dlg"] = dlg
        dlg.show()                      # 先显示，"取消"是否真的关掉它才可观测
        for b in dlg.findChildren(QPushButton):
            if b.text() == "取消":
                b.click()               # 走按钮**自己的** clicked 接线（不绕过）
                break
        assert not dlg.isVisible(), "「取消」按钮没有接到 reject()（点了不关窗）"
        return dlg.result()             # reject() → Rejected（QDialog.DialogCode.Rejected == 0）

    monkeypatch.setattr(pet_dialogs, "modal", _fake_modal)
    # 空 id = 内置默认角色也能编辑（RoleEditDialog 会给出一个默认形态），不需要自建角色
    rid = pet.role_lib.active_id() or ""
    dlg = pet_dialogs.RoleEditDialog(pet, pet.role_lib, rid)
    monkeypatch.setattr(dlg, "_refresh_act_list", lambda *a, **k: None)
    try:
        dlg._cur_idx = 0
        before = json.dumps(dlg._forms[0].get("procs") or {}, sort_keys=True)
        dlg._add_proc_action()
        labels = [b.text() for b in seen["dlg"].findChildren(QPushButton)]
        assert "取消" in labels, "内联框没有「取消」按钮：%r" % (labels,)
        assert json.dumps(dlg._forms[0].get("procs") or {}, sort_keys=True) == before, \
            "取消（reject）居然把动作加进去了"
    finally:
        dlg._cleanup()


def test_compose_dialog_accept_still_adds(pet, ui, monkeypatch):
    """控制组：确定路径照旧能加（补取消不许把功能补没）。"""
    seen = {}

    def _fake_modal(dlg):
        seen["dlg"] = dlg
        edits = dlg.findChildren(pet_dialogs.QLineEdit)
        if edits:
            edits[0].setText("v280_proc_ok")
        return pet_dialogs.QDialog.DialogCode.Accepted

    monkeypatch.setattr(pet_dialogs, "modal", _fake_modal)
    rid = pet.role_lib.active_id() or ""
    dlg = pet_dialogs.RoleEditDialog(pet, pet.role_lib, rid)
    monkeypatch.setattr(dlg, "_refresh_act_list", lambda *a, **k: None)
    try:
        dlg._cur_idx = 0
        dlg._add_proc_action()
        assert "v280_proc_ok" in (dlg._forms[0].get("procs") or {}), \
            "确定之后动作没加进去：%r" % (dlg._forms[0].get("procs"),)
    finally:
        dlg._cleanup()


def test_static_input_dialogs_are_gone_except_the_frame_action_one():
    """P2-5：静态 QInputDialog **只剩帧动作那一处**（裁决保留），其余 5 处已走 modal()。

    静态门（源码级）：这条用例同时是"其余 5 处不许退回去"的护栏。
    变异：把任意一处改回 QInputDialog.getText/getItem 静态调用 → 本用例红。
    """
    src = _read_src()
    gets = [i for i in range(len(src)) if src.startswith("QInputDialog.getText(", i)]
    items = [i for i in range(len(src)) if src.startswith("QInputDialog.getItem(", i)]
    assert len(gets) == 1, ("静态 getText 只剩帧动作那一处，实际 %d 处" % len(gets))
    assert items == [], "还有静态 getItem 调用：%r" % (
        [_enclosing_def_name(src, i) for i in items],)
    assert _enclosing_def_name(src, gets[0]) == "_add_frame_action", \
        "留下的那一处不是帧动作（既有用例靠 monkeypatch 静态方法驱动它）：%s" % (
            _enclosing_def_name(src, gets[0]),)


def test_ask_helpers_go_through_modal(pet, monkeypatch):
    """P2-5 的新路径：_ask_text / _ask_item 手工建框 + modal()（取值走 textValue）。"""
    calls = []

    class _Dlg(object):
        def __init__(self, *_a, **_k):
            self.value = ""

        def setWindowTitle(self, *_a):
            pass

        def setLabelText(self, *_a):
            pass

        def setTextValue(self, v):
            self.value = str(v)

        def setComboBoxItems(self, items):
            calls.append(("items", list(items)))

        def setComboBoxEditable(self, _b):
            pass

        def setStyleSheet(self, *_a):
            pass

        def textValue(self):
            return self.value

    monkeypatch.setattr(pet_dialogs, "QInputDialog", _Dlg)

    def _accept(dlg):
        calls.append(("modal", dlg.value))
        return pet_dialogs.QDialog.DialogCode.Accepted

    monkeypatch.setattr(pet_dialogs, "modal", _accept)
    text, ok = pet_dialogs._ask_text(pet, "标题", "标签", "默认")
    assert ok is True and text == "默认"
    assert ("modal", "默认") in calls, calls

    calls.clear()
    monkeypatch.setattr(pet_dialogs, "modal",
                        lambda dlg: pet_dialogs.QDialog.DialogCode.Rejected)
    got, ok2 = pet_dialogs._ask_item(pet, "标题", "标签", ["甲", "乙"], 1)
    assert ok2 is False and got == "", "取消时不该回传选中项"
    assert ("items", ["甲", "乙"]) in calls, calls


def test_wording_table_is_applied_to_new_and_add_buttons(pet):
    """P3-6 文案对照表：「新建…」= 清空表单、「添加/＋…」= 加进列表，都要说明"要先保存"。"""
    assert pet_dialogs.BTN_NEW_TIP and pet_dialogs.BTN_ADD_TIP
    dlg = pet_dialogs.LinesDialog(pet)
    try:
        got = {b.text(): b.toolTip() for b in dlg.findChildren(QPushButton)}
        assert got.get("新建") == pet_dialogs.BTN_NEW_TIP, got.get("新建")
        assert got.get("新建对白") == pet_dialogs.BTN_NEW_TIP, got.get("新建对白")
        assert got.get("添加 →") == pet_dialogs.BTN_ADD_TIP, got.get("添加 →")
    finally:
        dlg.close()
    dlg2 = pet_dialogs.BehaviorDialog(pet, pet.behaviors)
    try:
        got2 = {b.text(): b.toolTip() for b in dlg2.findChildren(QPushButton)}
        assert got2.get("新建") == pet_dialogs.BTN_NEW_TIP, got2.get("新建")
        assert got2.get("添加步骤") == pet_dialogs.BTN_ADD_TIP, got2.get("添加步骤")
    finally:
        dlg2.hide()
    dlg3 = pet_dialogs.AlarmDialog(pet, pet.alarms)
    try:
        got3 = {b.text(): b.toolTip() for b in dlg3.findChildren(QPushButton)}
        assert got3.get("新建") == pet_dialogs.BTN_NEW_TIP, got3.get("新建")
    finally:
        dlg3.hide()
    dlg4 = pet_dialogs.RoleImportDialog(pet)
    try:
        got4 = {b.text(): b.toolTip() for b in dlg4.findChildren(QPushButton)}
        assert got4.get("＋ 添加形态") == pet_dialogs.BTN_ADD_TIP, got4.get("＋ 添加形态")
    finally:
        dlg4.reject()
    dlg5 = pet_dialogs.RoleEditDialog(None, None, "")
    try:
        got5 = {b.text(): b.toolTip() for b in dlg5.findChildren(QPushButton)}
        assert got5.get("＋帧动作…") == pet_dialogs.BTN_ADD_TIP, got5.get("＋帧动作…")
        assert got5.get("＋合成…") == pet_dialogs.BTN_ADD_TIP, got5.get("＋合成…")
    finally:
        dlg5._cleanup()


def test_import_wizard_add_form_gives_a_receipt_and_construction_stays_quiet(pet, ui):
    """N14：「＋ 添加形态」成功后给回执；**构造对话框本身不许发回执**（默认零打扰）。"""
    dlg = pet_dialogs.RoleImportDialog(pet)
    try:
        assert dlg._notes.text() == "", "打开向导就写状态行（默认零打扰被破坏）：%r" % dlg._notes.text()
        n0 = len(dlg._form_rows)
        dlg._add_form_btn.click()
        assert len(dlg._form_rows) == n0 + 1, "按钮没加上形态"
        assert "已添加" in dlg._notes.text(), "加了形态却没有任何回执：%r" % dlg._notes.text()
        assert dlg._form_rows[-1]["name"] in dlg._notes.text(), dlg._notes.text()
    finally:
        dlg.reject()

    # 反向：满 8 个时点按钮 → 只报警告、**不许**再给"已添加"回执
    dlg2 = pet_dialogs.RoleImportDialog(pet)
    try:
        while len(dlg2._form_rows) < 8:
            assert dlg2._add_form() is True
        dlg2._notes.setText("")
        dlg2._add_form_btn.click()
        assert len(dlg2._form_rows) == 8
        assert "已添加" not in dlg2._notes.text(), "被拒绝的那次也发了回执：%r" % dlg2._notes.text()
    finally:
        dlg2.reject()


def test_voice_event_import_receipt_and_clear_confirm(pet, ui, monkeypatch, tmp_path):
    """S14 / S15 / P3-5：导入要回执；清除要二次确认（带事件名）+ 回执；取消时盘上不变。"""
    import wave

    def _wav(p):
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(b"\x00\x00" * 800)
        return str(p)

    key = "poke"
    pet.voice.set_clip(key, None)
    src = _wav(tmp_path / "v280_clip.wav")
    monkeypatch.setattr(pet_dialogs.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (src, "")))
    dlg = pet_dialogs.VoiceDialog(pet)
    dlg.show()
    try:
        ui["toast"].clear()
        dlg._import(key)
        assert pet.voice.clip(key), "用例前提：片段没配上"
        assert any("已配好" in t for t in ui["toast"]), "导入成功零回执：%r" % (ui["toast"],)

        ui["confirm"] = False
        ui["toast"].clear()
        assert dlg._clear(key) is False
        assert pet.voice.clip(key), "取消确认却把片段清掉了"
        assert ui["toast"] == [], "取消不该有任何成功回执：%r" % (ui["toast"],)

        ui["confirm"] = True
        ui["toast"].clear()
        assert dlg._clear(key) is True
        assert pet.voice.clip(key) is None, "确认清除没生效"
        assert any("已清除" in t for t in ui["toast"]), "清除成功零回执：%r" % (ui["toast"],)
        assert "被戳" in ui["toast"][-1], "回执里没有事件名：%r" % (ui["toast"][-1],)
    finally:
        dlg.hide()


def test_dialogue_remove_member_reports_what_was_removed(pet, ui):
    """D9：对白「移除」成员成功后要有回执（此前只有列表变化，用户不知道成没成）。"""
    lib = pet.lines_lib
    ln, err = lib.add("V280 对白成员台词", pet_lines.LINE_CATEGORIES[0], None, None)
    assert ln is not None, err
    d, derr = lib.add_dialogue("V280 对白", [ln["id"]])
    assert d is not None, derr
    dlg = pet_dialogs.LinesDialog(pet)
    dlg.show()
    try:
        hit = -1
        for i in range(dlg._dlist.count()):
            if dlg._dlist.item(i).data(Qt.ItemDataRole.UserRole) == d["id"]:
                hit = i
                break
        assert hit >= 0, "新建的对白不在列表里"
        dlg._dlist.setCurrentRow(hit)
        assert dlg._members.count() == 1, "用例前提：对白里得有一条成员"
        dlg._members.setCurrentRow(0)
        ui["toast"].clear()
        dlg._remove_member()
        assert lib.get_dialogue(d["id"])["line_ids"] == [], "成员没被移除"
        assert ui["toast"] and "移除" in ui["toast"][-1], "移除成功零回执：%r" % (ui["toast"],)
        assert "台词本身不受影响" in ui["toast"][-1], ui["toast"][-1]
    finally:
        dlg.hide()
        lib.delete_dialogue(d["id"])
        lib.delete(ln["id"])


def test_role_edit_delete_action_needs_confirm_and_reports():
    """D14：删自定义动作要二次确认（说明是暂存态）+ 回执；取消时动作还在。"""
    dlg = pet_dialogs.RoleEditDialog(None, None, "")
    try:
        dlg._cur_idx = 0
        dlg._forms[0]["procs"] = {"v280_del": {"kind": "breathe", "amp": 0.02,
                                               "period_ms": 2000}}
        dlg._refresh_act_list()
        assert dlg._act_list.count() == 1, "用例前提：列表里得有一个自定义动作"
        dlg._act_list.setCurrentRow(0)

        confirms = []
        orig_warn, orig_confirm = pet_dialogs._warn, pet_dialogs._confirm
        pet_dialogs._warn = lambda _p, t, x: None
        pet_dialogs._confirm = lambda _p, t, x: (confirms.append((t, x)), False)[1]
        try:
            dlg._del_action()
        finally:
            pet_dialogs._warn, pet_dialogs._confirm = orig_warn, orig_confirm
        assert confirms, "删自定义动作没有二次确认"
        assert "v280_del" in confirms[-1][1], "确认文案里没有动作名：%r" % (confirms[-1],)
        assert "暂存" in confirms[-1][1], "没有说明它是暂存态（可整体放弃）：%r" % (confirms[-1],)
        assert "v280_del" in (dlg._forms[0].get("procs") or {}), "取消确认却把动作删了"

        # 确认 → 真删 + 回执（回执走 _toast；pet=None 时它静默返回 False，不影响删除）
        pet_dialogs._confirm = lambda _p, t, x: True
        try:
            dlg._del_action()
        finally:
            pet_dialogs._confirm = orig_confirm
        assert "v280_del" not in (dlg._forms[0].get("procs") or {}), "确认之后没删掉"
    finally:
        dlg._cleanup()


def test_role_edit_delete_action_toasts_with_a_pet(pet):
    """D14 的回执侧：带 pet 时删完必须有一句"已删除自定义动作"（不静默）。"""
    toasts = []

    class _BubblePet(object):
        def show_bubble(self, text):
            toasts.append(text)

    dlg = pet_dialogs.RoleEditDialog(_BubblePet(), None, "")
    try:
        dlg._cur_idx = 0
        dlg._forms[0]["procs"] = {"v280_del2": {"kind": "sway", "amp": 0.02,
                                                "period_ms": 2000}}
        dlg._refresh_act_list()
        dlg._act_list.setCurrentRow(0)
        orig_confirm = pet_dialogs._confirm
        pet_dialogs._confirm = lambda _p, t, x: True
        try:
            dlg._del_action()
        finally:
            pet_dialogs._confirm = orig_confirm
        assert "v280_del2" not in (dlg._forms[0].get("procs") or {})
        assert toasts and "v280_del2" in toasts[-1], toasts
    finally:
        dlg._cleanup()




# ==================== 五、本轮追查追加的 4 处缺口 ====================

def test_alarm_new_gives_a_receipt(pet, ui):
    """闹钟「新建」：表单本来就是默认状态时点下去零变化 —— 必须给一句即时回执。"""
    dlg = pet_dialogs.AlarmDialog(pet, pet.alarms)
    try:
        assert dlg._label.text() == "" and dlg._ck_enabled.isChecked(), "用例前提：表单是默认状态"
        ui["toast"].clear()
        dlg._new()
        assert ui["toast"], "点「新建」屏幕上零变化、也没有任何回执"
        assert "新建态" in ui["toast"][-1], ui["toast"][-1]
    finally:
        dlg.hide()


def test_alarm_delete_reports_exactly_once(pet, ui):
    """删除闹钟复用静默复位：**一次用户动作只说一句话**（不许「已进入新建态」+「已删除」两条）。"""
    svc = pet.alarms
    a, err = svc.add("07:30", "V280 闹钟")
    assert a, err
    dlg = pet_dialogs.AlarmDialog(pet, svc)
    try:
        hit = -1
        for i in range(dlg._list.count()):
            if dlg._list.item(i).data(Qt.ItemDataRole.UserRole) == a["id"]:
                hit = i
                break
        assert hit >= 0, "刚加的闹钟不在列表里"
        dlg._list.setCurrentRow(hit)
        ui["toast"].clear()
        dlg._delete()
        assert len(ui["toast"]) == 1, "一次删除发了多条回执：%r" % (ui["toast"],)
        assert "已删除闹钟" in ui["toast"][0], ui["toast"]
        assert dlg._label.text() == "", "删除后表单没有复位"
    finally:
        dlg.hide()


def test_new_proc_action_is_selected_and_scrolled_into_view(pet, ui, monkeypatch):
    """N12/N13「视口外」：动作列表**限高 80px** —— 新动作必须被选中并滚进视口。

    只断言"加进去了"是不够的：条目在视口外时，用户视角与"点了没反应"完全等价。
    变异：去掉 _refresh_act_list 里的 setCurrentRow + scrollToItem → 第二条断言红。
    """
    def _fake_modal(dlg):
        edits = dlg.findChildren(pet_dialogs.QLineEdit)
        if edits:
            edits[0].setText("v280_scroll_proc")
        return pet_dialogs.QDialog.DialogCode.Accepted

    monkeypatch.setattr(pet_dialogs, "modal", _fake_modal)
    rid = pet.role_lib.active_id() or ""
    dlg = pet_dialogs.RoleEditDialog(None, pet.role_lib, rid)
    dlg.show()
    try:
        dlg._cur_idx = 0
        # 先塞满 12 条（限高 80px ≈ 5 行）→ 新加的那条会落在视口外
        dlg._forms[0]["procs"] = {
            "p%02d" % i: {"kind": "breathe", "amp": 0.02, "period_ms": 2000}
            for i in range(12)}
        dlg._refresh_act_list()
        QApplication.processEvents()
        dlg._add_proc_action()
        assert "v280_scroll_proc" in (dlg._forms[0].get("procs") or {}), "动作没加上"
        cur = dlg._act_list.currentItem()
        assert cur is not None, "新动作没有被选中（列表里「有了」不等于用户看见了）"
        assert cur.text() == "v280_scroll_proc（合成）", cur.text()
        rect = dlg._act_list.visualItemRect(cur)
        assert dlg._act_list.viewport().rect().intersects(rect), \
            "新动作在视口外（%r vs %r）" % (rect, dlg._act_list.viewport().rect())
    finally:
        dlg.hide()
        dlg._cleanup()


def test_behavior_step_receipts(pet, ui):
    """N15 / D11：行为「添加步骤」「删除选中步骤」都要有成功回执（此前只有列表变化）。"""
    dlg = pet_dialogs.BehaviorDialog(pet, pet.behaviors)
    dlg.show()
    try:
        dlg._steps.clear()
        dlg._act_combo.setCurrentIndex(dlg._act_combo.findData("say"))
        dlg._param.setText("V280 步骤回执")
        ui["toast"].clear()
        dlg._add_step()
        assert dlg._steps.count() == 1, "用例前提：步骤没加上"
        assert ui["toast"] and "已添加步骤" in ui["toast"][-1], "添加步骤零回执：%r" % (ui["toast"],)
        assert dlg._steps.currentItem() is dlg._steps.item(0), "新步骤没有选中"

        dlg._steps.setCurrentRow(0)
        ui["toast"].clear()
        dlg._del_step()
        assert dlg._steps.count() == 0, "步骤没删掉"
        assert ui["toast"] and "已删除步骤" in ui["toast"][-1], "删除步骤零回执：%r" % (ui["toast"],)
    finally:
        dlg.hide()


def test_move_line_at_boundary_tells_the_user(pet, ui):
    """台词「上移/下移」到顶/到底：以前静默 return（与"点了没反应"长得一样）→ 给一句提示。"""
    lib = pet.lines_lib
    made = []
    for i in range(3):
        ln, err = lib.add("V280 排序边界台词 %d" % i, pet_lines.LINE_CATEGORIES[0], None, None)
        assert ln is not None, err
        made.append(ln["id"])
    dlg = pet_dialogs.LinesDialog(pet)
    dlg.show()
    try:
        assert dlg._list.count() >= 3, "用例前提：列表里得有台词"
        dlg._list.setCurrentRow(0)
        ui["toast"].clear()
        dlg._move_line(-1)
        assert ui["toast"] and "最上面" in ui["toast"][-1], "到顶没有任何反馈：%r" % (ui["toast"],)

        dlg._list.setCurrentRow(dlg._list.count() - 1)
        ui["toast"].clear()
        dlg._move_line(1)
        assert ui["toast"] and "最下面" in ui["toast"][-1], "到底没有任何反馈：%r" % (ui["toast"],)
    finally:
        dlg.hide()
        for lid in made:
            lib.delete(lid)


def test_lines_move_member_at_boundary_uses_the_same_wording(pet, ui):
    """P3-6：对白「上移/下移」到边界用与台词排序**同一套措辞**（同一批对话框同一动作）。"""
    lib = pet.lines_lib
    ids = []
    for i in range(2):
        ln, err = lib.add("V280 成员排序 %d" % i, pet_lines.LINE_CATEGORIES[0], None, None)
        assert ln is not None, err
        ids.append(ln["id"])
    d, derr = lib.add_dialogue("V280 排序对白", ids)
    assert d is not None, derr
    dlg = pet_dialogs.LinesDialog(pet)
    dlg.show()
    try:
        hit = -1
        for i in range(dlg._dlist.count()):
            if dlg._dlist.item(i).data(Qt.ItemDataRole.UserRole) == d["id"]:
                hit = i
                break
        assert hit >= 0, "新建的对白不在列表里"
        dlg._dlist.setCurrentRow(hit)
        assert dlg._members.count() == 2, "用例前提：对白里得有两条成员"
        dlg._members.setCurrentRow(0)
        ui["toast"].clear()
        dlg._move_member(-1)          # 第 0 条再往上 = 到顶（不换序、给一句提示）
        assert ui["toast"] and "最上面" in ui["toast"][-1], ui["toast"]
    finally:
        dlg.hide()
        lib.delete_dialogue(d["id"])
        for lid in ids:
            lib.delete(lid)


def test_new_line_scrolls_into_view(pet, ui):
    """实测（本轮补）：setCurrentRow 会把目标行**滚进视口** → 新建后断言"真的看得见"。

    审计 §4 把这一条列为"未实测"。offscreen 实测（Qt 6.11）：QListWidget 的
    setCurrentRow 会带动滚动条（value 0 → max），目标行矩形与 viewport 相交。
    所以这条断言不是"猜的"：它同时钉住"选中了新行"和"新行在视口里"两个事实。
    """
    lib = pet.lines_lib
    made = []
    for i in range(30):
        ln, err = lib.add("V280 滚动测试台词 %02d" % i, pet_lines.LINE_CATEGORIES[0], None, None)
        assert ln is not None, err
        made.append(ln["id"])
    dlg = pet_dialogs.LinesDialog(pet)
    dlg.show()
    try:
        QApplication.processEvents()
        dlg._new_line()
        dlg._text.setPlainText("V280 刚保存的这一条")
        dlg._save_line()
        assert dlg._editing, "保存没成功"
        made.append(dlg._editing)
        cur = dlg._list.currentItem()
        assert cur is not None, "新行没有被选中"
        assert cur.data(Qt.ItemDataRole.UserRole) == dlg._editing
        rect = dlg._list.visualItemRect(cur)
        assert dlg._list.viewport().rect().intersects(rect), \
            "新行选中了但不在视口里（%r vs %r）" % (rect, dlg._list.viewport().rect())
    finally:
        dlg.hide()
        for lid in made:
            lib.delete(lid)
