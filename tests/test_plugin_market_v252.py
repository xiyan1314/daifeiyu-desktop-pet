# -*- coding: utf-8 -*-
"""v2.6.0（代理 A）PetHub Phase 2：索引下载器 + 市场页 + 更新 / 回滚 / 内容指纹去重。

被测面（全部是**真**接口，不用替身糊过去）：
· pet_plugin_index：索引读取（随包 / 远端同一格式）、url 解析（相对 → 随包本地副本）、
  下载后的 sha256 / bytes 核对、交给 pet_plugin.validate_plugin_zip 与 PluginHost；
· pet_plugin_host：内容指纹去重合并（更新）、上一版目录 + 回滚、旧登记补账；
· pet_dialogs.PluginManagerDialog：两个页签 / 更新与回滚按钮的出现条件 / 下载走后台线程。

**测试永不联网**：所有取数都注入假 fetch，_no_real_network 把默认实现换成"一调用就炸"。
**断言不依赖机器速度**（铁律 5）：跨线程的用例只断言结构性事实（取数发生在**别的**线程、
落地发生在**主**线程、在途期间连点只起一次取数），等待一律是事件驱动 + 宽松的防挂死兜底，
没有任何"必须在 X 毫秒内"的判据。
"""
import hashlib
import json
import os
import sys
import threading
import zipfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pet_dialogs        # noqa: E402
import pet_lines          # noqa: E402
import pet_plugin         # noqa: E402
import pet_plugin_host    # noqa: E402
import pet_plugin_index   # noqa: E402

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication     # noqa: E402

HOST = "2.5.0"
PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63f8cf00000301010018dd8db00000000049454e44ae426082")

_APP = QApplication.instance()
if _APP is None:
    _APP = QApplication([])


_REAL_DEFAULT_FETCH = pet_plugin_index.default_fetch


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """**远端**取数一调用就炸（测试永不联网）；本地路径照旧（对话框读随包索引要用）。"""
    def _guarded(url, progress=None):
        if pet_plugin_index.is_remote(url):
            raise AssertionError("测试里不许真联网（远端取数必须注入 fetch）：%s" % url)
        return _REAL_DEFAULT_FETCH(url, progress)
    monkeypatch.setattr(pet_plugin_index, "default_fetch", _guarded)
    return _guarded


# ---------------- 造包 / 造索引 / 假取数 ----------------

def _pack_bytes(lines, pid="market-lines", version="1.0.0", data_kind="lines",
                min_host_version=HOST, api_version=1, kind="data", code=False):
    """造一个**合法**插件包 → zip 字节（files 清单用真实哈希，包本身一定过校验器）。"""
    payload = {"lines.json": json.dumps({"lines": lines}, ensure_ascii=False).encode("utf-8")}
    files = [{"path": "payload/" + rel, "sha256": hashlib.sha256(data).hexdigest(),
              "bytes": len(data)} for rel, data in sorted(payload.items())]
    manifest = {"format": pet_plugin.PLUGIN_FORMAT, "version": 1, "payload_root": "payload/",
                "created_at": "2026-01-01T00:00:00", "files": files,
                "plugin": {"id": pid, "name": "市场包 " + pid, "version": version,
                           "kind": kind, "data_kind": data_kind, "code": code,
                           "min_host_version": min_host_version, "api_version": api_version,
                           "capabilities": []}}
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        for rel, data in sorted(payload.items()):
            zf.writestr("payload/" + rel, data)
    return buf.getvalue()


_UNSET = object()          # "没传"与"传了空值"必须分得开（sha="" 是**故意**的坏索引）


def _release(pack, version="1.0.0", url="packs/market-lines-1.0.0.dp.zip",
             min_host_version=HOST, api_version=1, sha=_UNSET, size=_UNSET):
    """一条 release 记录（哈希 / 大小默认取真值；显式传空串 = 造一条坏索引）。"""
    return {"version": version, "min_host_version": min_host_version, "api_version": api_version,
            "url": url,
            "sha256": hashlib.sha256(pack).hexdigest() if sha is _UNSET else sha,
            "bytes": len(pack) if size is _UNSET else size, "published_at": "2026-01-01"}


def _entry(pid="market-lines", releases=(), **over):
    item = {"id": pid, "name": "市场包", "kind": "data", "data_kind": "lines", "code": False,
            "summary": "一句话", "author": "测试", "releases": list(releases)}
    item.update(over)
    return item


def _index_bytes(plugins, host_min="2.0.0", index_version=1):
    return json.dumps({"index_version": index_version, "updated_at": "2026-01-01",
                       "host_min": host_min, "plugins": list(plugins)},
                      ensure_ascii=False).encode("utf-8")


class _Fetcher(object):
    """假取数：url → bytes。顺便记下**每次取数发生在哪个线程**（结构性断言要用）。"""

    def __init__(self, table=None, err=None, gate=None):
        self.table = dict(table or {})
        self.err = err
        self.gate = gate                        # 可选 Event：挡住取数，用来造"在途"
        self.calls = []
        self.threads = []
        self.entered = threading.Event()

    def __call__(self, url):
        self.calls.append(url)
        self.threads.append(threading.get_ident())
        self.entered.set()
        if self.gate is not None and not self.gate.wait(10):
            return None, "假取数等放行超时"
        if self.err:
            return None, self.err
        if url not in self.table:
            return None, "假取数里没有这个地址：%s" % url
        return self.table[url], ""


def _host(tmp_path, **libs):
    return pet_plugin_host.PluginHost(str(tmp_path), HOST, **libs)


def _market(tmp_path, fetcher, index_url="https://example.invalid/packs/index.json",
            host_version=HOST, **kw):
    return pet_plugin_index.PluginIndex(str(tmp_path / "plugins"), fetch=fetcher,
                                        index_url=index_url, host_version=host_version, **kw)


# ================= A1：索引读取 / url 口径 / 哈希校验 =================

def test_随包索引_相对url解析到随包本地副本_不联网(tmp_path):
    """base_url 口径：index.json 里的 "packs/x.zip" 是**相对索引自己**的路径。

    能真失败：把 resolve_url 的相对分支改成"按当前工作目录"→ 本地副本找不到，红。
    """
    plugins = tmp_path / "plugins"
    (plugins / "packs").mkdir(parents=True)
    pack = _pack_bytes([{"text": "随包"}])
    (plugins / "packs" / "market-lines-1.0.0.dp.zip").write_bytes(pack)
    (plugins / "index.json").write_bytes(_index_bytes(
        [_entry(releases=[_release(pack, url="packs/market-lines-1.0.0.dp.zip")])]))

    fetcher = _Fetcher()          # 空表：真去取远端就会失败
    idx = pet_plugin_index.PluginIndex(str(plugins), fetch=fetcher, host_version=HOST)
    index, err = idx.load_index()
    assert err == "" and len(index["entries"]) == 1, err
    entry = index["entries"][0]
    assert entry["installable"] is True, entry["reason"]
    assert entry["source"][0] == "file", entry["source"]
    assert entry["source"][1] == str(plugins / "packs" / "market-lines-1.0.0.dp.zip")
    path, derr = idx.download(entry)
    assert derr == "" and os.path.isfile(path), derr
    assert open(path, "rb").read() == pack, "下载的临时文件内容与包不一致"
    assert fetcher.calls == [], "本地副本不该走注入的取数（更不该联网）：%r" % (fetcher.calls,)
    idx.cleanup()
    assert not os.path.isdir(idx.download_dir), "清理后不该留 _download/"


def test_远端索引_绝对url与相对url都取得到(tmp_path):
    """同一份索引放远端：绝对 http 原样取，相对路径接到索引所在的 URL 上。

    能真失败：resolve_url 只用 urljoin 的一个分支（绝对地址会被接成怪地址）→ 取数失败，红。
    """
    pack_a = _pack_bytes([{"text": "远端A"}], pid="market-a")
    pack_b = _pack_bytes([{"text": "远端B"}], pid="market-b")
    base = "https://example.invalid/dir/index.json"
    fetcher = _Fetcher({
        base: _index_bytes([
            _entry("market-a", [_release(pack_a, url="https://cdn.example.invalid/a.zip")]),
            _entry("market-b", [_release(pack_b, url="packs/b.zip")]),
        ]),
        "https://cdn.example.invalid/a.zip": pack_a,
        "https://example.invalid/dir/packs/b.zip": pack_b,
    })
    idx = _market(tmp_path, fetcher, index_url=base)
    index, err = idx.load_index()
    assert err == "" and [e["id"] for e in index["entries"]] == ["market-a", "market-b"], err
    assert fetcher.calls == [base], fetcher.calls
    for entry in index["entries"]:
        path, derr = idx.download(entry)
        assert derr == "" and os.path.isfile(path), (entry["id"], derr)
    assert len(fetcher.calls) == 3, fetcher.calls
    idx.cleanup()


def test_sha256不符_拒收并删掉临时文件(tmp_path):
    """下载后必须核对 sha256：不符即拒、**删临时文件**，plugins/ 下不留任何残余。

    能真失败：去掉 sha256 比对 → 坏包被当成好包交给安装器，红。
    """
    pack = _pack_bytes([{"text": "正经内容"}])
    broken = bytearray(pack)
    broken[-1] ^= 0xFF                        # 动一个字节：哈希必变
    url = "https://example.invalid/x.zip"
    fetcher = _Fetcher({url: bytes(broken)})
    idx = _market(tmp_path, fetcher, index_url="")
    entry = {"id": "market-lines", "installable": True, "source": ["http", url],
             "url": "x.zip", "release": _release(pack, url="x.zip")}
    path, err = idx.download(entry)
    assert path is None and "sha256" in err and "丢弃" in err, err
    assert not (tmp_path / "plugins").exists(), "拒绝下载却在 plugins/ 下留了目录"


def test_bytes不符_拒收且不留残余(tmp_path):
    """bytes 不符同样拒（索引与包不是同一件东西）。"""
    pack = _pack_bytes([{"text": "正经内容"}])
    url = "https://example.invalid/x.zip"
    idx = _market(tmp_path, _Fetcher({url: pack}), index_url="")
    entry = {"id": "market-lines", "installable": True, "source": ["http", url], "url": "x.zip",
             "release": _release(pack, url="x.zip", size=len(pack) + 1)}
    path, err = idx.download(entry)
    assert path is None and "字节数" in err, err
    assert not (tmp_path / "plugins").exists()


def test_索引没有sha256就不下载_fail_closed(tmp_path):
    """索引里没有 sha256 / 不是 64 位 hex → 该条目**不可装**并给出原因（不静默）。"""
    idx = _market(tmp_path, _Fetcher(), index_url="https://example.invalid/index.json")
    pack = _pack_bytes([{"text": "x"}])
    rel = _release(pack, sha="", url="packs/x.zip")
    index, err = pet_plugin_index.parse_index(
        {"index_version": 1, "plugins": [_entry(releases=[rel])]},
        "https://example.invalid/index.json", HOST, pet_plugin.DATA_KINDS)
    assert err == ""
    entry = index["entries"][0]
    assert entry["installable"] is False and "sha256" in entry["reason"], entry


def test_密钥不可装的条目也列出来_不静默隐藏(tmp_path):
    """host_min 高于宿主 → 条目**留在列表里**，标成不可装并给出"要宿主 ≥ X，当前 Y"。

    能真失败：把这类条目从 entries 里滤掉 → 用户看不到"为什么官方内容不见了"，红。
    """
    pack = _pack_bytes([{"text": "未来的包"}], min_host_version="99.0.0")
    index, err = pet_plugin_index.parse_index(
        {"index_version": 1, "host_min": "99.0.0",
         "plugins": [_entry(releases=[_release(pack, min_host_version="99.0.0")])]},
        "https://example.invalid/index.json", HOST, pet_plugin.DATA_KINDS)
    assert err == ""
    entry = index["entries"][0]
    assert entry["installable"] is False
    assert "99.0.0" in entry["reason"] and HOST in entry["reason"], entry["reason"]
    # 单看 release 的版本门也一样（index 级 host_min 不满足时同样说得出原因）
    index2, _err = pet_plugin_index.parse_index(
        {"index_version": 1, "plugins": [_entry(releases=[_release(pack, min_host_version="99.0.0")])]},
        "https://example.invalid/index.json", HOST, pet_plugin.DATA_KINDS)
    entry2 = index2["entries"][0]
    assert entry2["installable"] is False and "99.0.0" in entry2["reason"], entry2["reason"]


def test_版本比较走四段整数_1_0_10_比_1_0_9_新(tmp_path):
    """四段整数比较（与 _check_release 同款）：字符串比较会把 1.0.10 判成比 1.0.9 旧。"""
    old = _pack_bytes([{"text": "旧"}], version="1.0.9")
    new = _pack_bytes([{"text": "新"}], version="1.0.10")
    index, err = pet_plugin_index.parse_index(
        {"index_version": 1, "plugins": [_entry(releases=[
            _release(old, version="1.0.9", url="a.zip"),
            _release(new, version="1.0.10", url="b.zip")])]},
        "https://example.invalid/index.json", HOST, pet_plugin.DATA_KINDS)
    entry = index["entries"][0]
    assert err == "" and entry["version"] == "1.0.10", entry


def test_索引格式不认识就整份拒绝_fail_closed(tmp_path):
    """看不懂的索引不许当成"没有新版本"：index_version 太新 / 不是对象 / 缺 plugins 都拒。"""
    for data, want in (({"index_version": 99, "plugins": []}, "版本"),
                       (["not a dict"], "对象"),
                       ({"index_version": 1}, "plugins")):
        index, err = pet_plugin_index.parse_index(data, "", HOST, pet_plugin.DATA_KINDS)
        assert index is None and want in err, (data, err)


def test_取数失败给人话错误(tmp_path):
    """网络失败 / 半截文件都折成一句人话（绝不抛），条目仍然不可装。"""
    idx = _market(tmp_path, _Fetcher(err="网络请求失败：假网络挂了"),
                  index_url="https://example.invalid/index.json")
    index, err = idx.load_index()
    assert index is None and "假网络挂了" in err, err


# ================= A1×A3：下载 → 校验器 → 安装器 =================

def test_下载后走校验器与安装器_真装进宿主库(tmp_path):
    """端到端：远端索引 → 下载 → pet_plugin.validate_plugin_zip → PluginHost.install_zip。

    "校验器是唯一真源"也在这里钉住：index 的安装路径**必须**调它（spy 计数），
    而且被它拒的包不许进安装器。
    """
    pack = _pack_bytes([{"text": "从市场装进来的"}])
    url = "https://example.invalid/packs/x.zip"
    lines_lib = pet_lines.LineService(str(tmp_path))
    host = _host(tmp_path, lines_lib=lines_lib)
    idx = _market(tmp_path, _Fetcher({url: pack}), index_url="")
    entry = {"id": "market-lines", "name": "市场包", "installable": True, "source": ["http", url],
             "url": "x.zip", "release": _release(pack, url="x.zip")}

    seen = {"validate": 0, "install": 0}
    real_validate = pet_plugin.validate_plugin_zip
    real_install = pet_plugin_host.PluginHost.install_zip

    def spy_validate(path, host_version):
        seen["validate"] += 1
        return real_validate(path, host_version)

    def spy_install(self, path, source_url=""):
        seen["install"] += 1
        return real_install(self, path, source_url)

    import unittest.mock as _mock
    with _mock.patch.object(pet_plugin, "validate_plugin_zip", spy_validate), \
            _mock.patch.object(pet_plugin_host.PluginHost, "install_zip", spy_install):
        ok, msg = idx.install(host, entry)
    assert ok is True, msg
    # 两层各校验一次：索引这一层"解包前再走一遍校验器"（拿不到 manifest 就不交给安装器），
    # 安装器自己那一层也校验（校验器是唯一真源，但两层的门各守各的）。变异：去掉索引层
    # 那次 validate → 计数变 1 → 红。
    assert seen["validate"] == 2 and seen["install"] == 1, seen
    assert "从市场装进来的" in [x["text"] for x in lines_lib.lines()]
    assert not os.path.isdir(idx.download_dir), "装完不该留下载临时文件"
    assert not (tmp_path / "plugins" / "market-lines" / "payload" / "x.zip").exists()


def test_索引里的包被校验器拒_不留残余(tmp_path):
    """索引与包对不上（包里是别的 id）→ 拒绝安装，且**不留任何残余**：
    下载的临时文件删掉、plugins/ 不留目录、宿主库不动。"""
    pack = _pack_bytes([{"text": "其实是别的包"}], pid="totally-other")
    url = "https://example.invalid/x.zip"
    lines_lib = pet_lines.LineService(str(tmp_path))
    host = _host(tmp_path, lines_lib=lines_lib)
    idx = _market(tmp_path, _Fetcher({url: pack}), index_url="")
    entry = {"id": "market-lines", "name": "市场包", "installable": True, "source": ["http", url],
             "url": "x.zip", "release": _release(pack, url="x.zip")}
    ok, msg = idx.install(host, entry)
    assert ok is False and "totally-other" in msg, msg
    assert "其实是别的包" not in [x["text"] for x in lines_lib.lines()]
    assert not os.path.isdir(idx.download_dir)
    plugins = tmp_path / "plugins"
    assert not plugins.exists() or os.listdir(str(plugins)) == [], os.listdir(str(plugins))


# ================= A3：更新 / 回滚 / 内容指纹 =================

def _lines_pack(path, texts, version="1.0.0", pid="upd"):
    """真 zip 文件（走真安装管线）。"""
    data = _pack_bytes([{"text": t, "category": "idle"} for t in texts],
                       pid=pid, version=version)
    path = str(path)
    with open(path, "wb") as f:
        f.write(data)
    return path


def test_更新把新版新增内容并入_旧内容不重复落(tmp_path):
    """内容指纹去重：更新时"只落新的、不重复落旧的"（v2.5.1 的整包跳过口径已废）。"""
    lib = pet_lines.LineService(str(tmp_path))
    host = _host(tmp_path, lines_lib=lib)
    assert host.install_zip(_lines_pack(tmp_path / "v1.zip", ["旧台词"], "1.0.0"))[0] is True
    n = len(lib.lines())
    ok, msg = host.install_zip(_lines_pack(tmp_path / "v2.zip", ["旧台词", "新台词"], "1.1.0"))
    assert ok is True and "新增的 1 项" in msg, msg
    texts = [x["text"] for x in lib.lines()]
    assert len(texts) == n + 1 and "新台词" in texts, texts[-3:]
    assert texts.count("旧台词") == 1, "旧内容被重复落了一遍"
    # 第三次装同一个 v2：内容全一致 → 一条都不落
    ok, msg = host.install_zip(_lines_pack(tmp_path / "v2b.zip", ["旧台词", "新台词"], "1.1.0"))
    assert ok is True and "完全一致" in msg, msg
    assert len(lib.lines()) == n + 1


def test_内容指纹落在安装登记里(tmp_path):
    """登记里要真的记下**每个已落地条目**的指纹（回滚与下次更新的依据）。"""
    lib = pet_lines.LineService(str(tmp_path))
    host = _host(tmp_path, lines_lib=lib)
    assert host.install_zip(_lines_pack(tmp_path / "v1.zip", ["甲", "乙"], "1.0.0"))[0] is True
    reg = json.loads((tmp_path / "plugins" / "_installed.json").read_text(encoding="utf-8"))
    rec = reg["plugins"]["upd"]
    assert len(rec["landed_fingerprints"]["lines"]) == 2, rec["landed_fingerprints"]
    assert all(len(x) == 64 for x in rec["landed_fingerprints"]["lines"])
    assert rec["history"] == [], "第一次安装没有上一版，history 必须是空的"


def test_landed_是历次落地的累积账(tmp_path):
    """登记里的 landed 记这个插件**历次**落地过的 id（回滚差集与人工排查都读它）。

    能真失败：把 record["landed"] 写成"只记本次新落的"（不做累积）→ 第一条断言红。
    """
    lib = pet_lines.LineService(str(tmp_path))
    host = _host(tmp_path, lines_lib=lib)
    for name, texts, ver in (("v1", ["甲"], "1.0.0"), ("v2", ["甲", "乙"], "1.1.0"),
                             ("v3", ["甲", "乙", "丙"], "1.2.0")):
        assert host.install_zip(_lines_pack(tmp_path / ("%s.zip" % name), texts, ver))[0] is True
    reg = json.loads((tmp_path / "plugins" / "_installed.json").read_text(encoding="utf-8"))
    ids = reg["plugins"]["upd"]["landed"]["lines"]
    live = {x["id"] for x in lib.lines() if x["text"] in ("甲", "乙", "丙")}
    assert len(ids) == 3, ids
    assert set(ids) == live, (ids, live)
    assert len(set(ids)) == len(ids), "累积账里有重复 id"


def test_回滚_撤销本版新增_不碰用户自己的内容(tmp_path):
    """回滚三件事：恢复上一版目录 + 撤销**这一版新落地**的条目 + 登记回到上一版。

    用户自己的台词一条都不许动（它不在"这一版新落地"的差集里）。
    """
    lib = pet_lines.LineService(str(tmp_path))
    host = _host(tmp_path, lines_lib=lib)
    lib.add("用户自己写的台词", "idle")
    assert host.install_zip(_lines_pack(tmp_path / "v1.zip", ["甲"], "1.0.0"))[0] is True
    assert host.install_zip(_lines_pack(tmp_path / "v2.zip", ["甲", "乙"], "1.1.0"))[0] is True
    assert "乙" in [x["text"] for x in lib.lines()]

    ok, msg = host.rollback("upd")
    assert ok is True and "回滚到上一版 1.0.0" in msg and "撤销了本版新导入的 1 项" in msg, msg
    texts = [x["text"] for x in lib.lines()]
    assert "乙" not in texts, "本版新增的台词没被撤销"
    assert "甲" in texts, "上一版就有的台词被误删了"
    assert "用户自己写的台词" in texts, "用户自己的内容被动了"
    reg = json.loads((tmp_path / "plugins" / "_installed.json").read_text(encoding="utf-8"))
    assert reg["plugins"]["upd"]["version"] == "1.0.0"
    assert reg["plugins"]["upd"]["history"] == []
    assert not os.path.isdir(str(tmp_path / "plugins" / ".prev-upd")), "回滚后还留着上一版备份"
    assert json.loads((tmp_path / "plugins" / "upd" / "manifest.json").read_text(
        encoding="utf-8"))["plugin"]["version"] == "1.0.0", "插件目录没有回到上一版"


def test_回滚后再更新一次仍然正确(tmp_path):
    """回滚把指纹账一起退回上一版 → 再更新时新版内容会**重新**落地（不会因指纹还在而跳过）。"""
    lib = pet_lines.LineService(str(tmp_path))
    host = _host(tmp_path, lines_lib=lib)
    assert host.install_zip(_lines_pack(tmp_path / "v1.zip", ["甲"], "1.0.0"))[0] is True
    assert host.install_zip(_lines_pack(tmp_path / "v2.zip", ["甲", "乙"], "1.1.0"))[0] is True
    assert host.rollback("upd")[0] is True
    ok, msg = host.install_zip(_lines_pack(tmp_path / "v2c.zip", ["甲", "乙"], "1.1.0"))
    assert ok is True and "新增的 1 项" in msg, msg
    texts = [x["text"] for x in lib.lines()]
    assert texts.count("乙") == 1 and texts.count("甲") == 1, texts


def test_同一个版本重复安装不顶掉回滚点(tmp_path):
    """v1 → v2 → v2（同一版本、内容一致）之后再回滚，必须还能回到 **v1**。

    _dev/probe_plugin_market_v260.py 实测踩到过：重复安装会轮换 plugins/.prev-<id>/，
    把 v1 的备份顶掉 → 回滚只是"原地不动"，用户以为回到了 v1、实际还在 v2。
    能真失败：去掉 install_zip 里的 repeat 分支（照旧轮换备份）→ 第一条断言红。
    """
    lib = pet_lines.LineService(str(tmp_path))
    host = _host(tmp_path, lines_lib=lib)
    assert host.install_zip(_lines_pack(tmp_path / "v1.zip", ["甲"], "1.0.0"))[0] is True
    assert host.install_zip(_lines_pack(tmp_path / "v2.zip", ["甲", "乙"], "1.1.0"))[0] is True
    assert host.install_zip(_lines_pack(tmp_path / "v2b.zip", ["甲", "乙"], "1.1.0"))[0] is True
    ok, msg = host.rollback("upd")
    assert ok is True and "回滚到上一版 1.0.0" in msg, msg
    texts = [x["text"] for x in lib.lines()]
    assert "乙" not in texts, "回滚没撤掉 v2 新增的台词（回滚点被重复安装顶掉了）"
    assert "甲" in texts


def test_回滚没有上一版就明确拒绝(tmp_path):
    """只装过一次 / 从来没有登记 → 拒绝并说明原因（绝不假装回滚成功）。"""
    lib = pet_lines.LineService(str(tmp_path))
    host = _host(tmp_path, lines_lib=lib)
    assert host.install_zip(_lines_pack(tmp_path / "v1.zip", ["甲"], "1.0.0"))[0] is True
    ok, msg = host.rollback("upd")
    assert ok is False and "没有上一版" in msg, msg
    assert "甲" in [x["text"] for x in lib.lines()]
    assert host.rollback("nope")[0] is False
    assert host.rollback("packs")[0] is False          # 保留名照样拒


def test_六个类别都按内容去重(tmp_path):
    """role / lines / audio / voice_ref / behaviors / prompt 六类的"同一个包再装一次不重复落"。

    每一类都用**真宿主库**跑：装 → 再装同一个包 → 宿主库条目数不变、登记表仍只有一条。
    """
    import io
    import wave
    import pet_behaviors
    import pet_resources

    def _wav():
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(b"\x00\x00" * 480)
        return buf.getvalue()

    role = {"id": "dedupRole", "name": "去重角色", "file": "d.png", "form": "single",
            "frames": ["d.png"], "added": ""}
    cases = {
        "role": ({"role.json": json.dumps(role, ensure_ascii=False).encode("utf-8"),
                  "d.png": PNG_1PX}, lambda t: len(pet_resources.RoleLibrary(str(t)).list_roles())),
        "lines": ({"lines.json": json.dumps({"lines": [{"text": "去重台词"}]},
                                            ensure_ascii=False).encode("utf-8")},
                  lambda t: pet_lines.LineService(str(t)).count()),
        "audio": ({"audio/a.wav": _wav()},
                  lambda t: len(pet_resources.AudioLibrary(str(t)).fragments())),
        "voice_ref": ({"voice_ref/a.wav": _wav()},
                      lambda t: len(pet_resources.VoiceAssetLibrary(str(t)).assets())),
        # 行为名必须是 ASCII（宿主 validate_name：英文字母开头 + 字母/数字/下划线）
        "behaviors": ({"behaviors/b.json": json.dumps(
            {"behavior": {"id": "abcd1234", "name": "dedup_behavior",
                          "steps": [{"act": "wait", "ms": 100}]}},
            ensure_ascii=False).encode("utf-8")},
            lambda t: len(pet_behaviors.BehaviorService(str(t)).list())),
        "prompt": ({"prompts/去重人设.txt": "你是去重人设".encode("utf-8")},
                   lambda t: len([n for n in os.listdir(str(t / "prompts" / "custom"))
                                  if n.endswith(".txt")])),
    }
    libs = {"role_lib": pet_resources.RoleLibrary(str(tmp_path)),
            "lines_lib": pet_lines.LineService(str(tmp_path)),
            "audio_lib": pet_resources.AudioLibrary(str(tmp_path)),
            "voice_assets": pet_resources.VoiceAssetLibrary(str(tmp_path)),
            "behaviors": pet_behaviors.BehaviorService(str(tmp_path))}
    host = pet_plugin_host.PluginHost(str(tmp_path), HOST, **libs)
    for kind, (payload, count) in sorted(cases.items()):
        payload_dir = tmp_path / ("p_%s" % kind)
        payload_dir.mkdir()
        files = [{"path": "payload/" + rel, "sha256": hashlib.sha256(data).hexdigest(),
                  "bytes": len(data)} for rel, data in sorted(payload.items())]
        manifest = {"format": pet_plugin.PLUGIN_FORMAT, "version": 1, "payload_root": "payload/",
                    "files": files, "plugin": {"id": "kind-%s" % kind, "name": "去重",
                                               "version": "1.0.0", "kind": "data",
                                               "data_kind": kind, "code": False,
                                               "min_host_version": HOST, "api_version": 1,
                                               "capabilities": []}}
        path = str(tmp_path / ("k_%s.zip" % kind))
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
            for rel, data in sorted(payload.items()):
                zf.writestr("payload/" + rel, data)
        assert host.install_zip(path)[0] is True, kind
        n = count(tmp_path)
        assert n > 0, "%s 类第一次没落地" % kind
        reg = json.loads((tmp_path / "plugins" / "_installed.json").read_text(encoding="utf-8"))
        assert reg["plugins"]["kind-%s" % kind]["landed_fingerprints"], kind
        assert host.install_zip(path)[0] is True, kind
        assert count(tmp_path) == n, "%s 类：同一个包再装一次重复落地了" % kind


def test_旧登记没有指纹_也能不重复落地(tmp_path):
    """v2.5.1 的登记只有 landed、没有指纹 → 用**上一版目录**补账（不许给用户多一份内容）。

    能真失败：去掉 install_zip 里的 _legacy_ledger 那一跳 → 旧登记用户一更新就多出
    一份同样的台词（重复落地），红。
    """
    lib = pet_lines.LineService(str(tmp_path))
    host = _host(tmp_path, lines_lib=lib)
    pack = _lines_pack(tmp_path / "v1.zip", ["甲", "乙"], "1.0.0")
    assert host.install_zip(pack)[0] is True
    n = len(lib.lines())
    # 把登记改造成 v2.5.1 的形状：有 landed、没有指纹、没有 history
    reg_path = tmp_path / "plugins" / "_installed.json"
    reg = json.loads(reg_path.read_text(encoding="utf-8"))
    rec = reg["plugins"]["upd"]
    rec.pop("landed_fingerprints", None)
    rec["history"] = []
    reg_path.write_text(json.dumps(reg, ensure_ascii=False), encoding="utf-8")

    ok, msg = host.install_zip(pack)
    assert ok is True and "完全一致" in msg, msg
    assert len(lib.lines()) == n, "旧登记没有指纹时把内容又落了一遍"
    reg2 = json.loads(reg_path.read_text(encoding="utf-8"))
    assert reg2["plugins"]["upd"]["landed_fingerprints"]["lines"], "补账没有写回登记"


def test_提交失败时上一版目录还在_当前这版仍可用(tmp_path, monkeypatch):
    """更新提交失败 → 上一版目录挪回去（用户继续用原来那一版），且回滚备份不残留。"""
    lib = pet_lines.LineService(str(tmp_path))
    host = _host(tmp_path, lines_lib=lib)
    assert host.install_zip(_lines_pack(tmp_path / "v1.zip", ["甲"], "1.0.0"))[0] is True
    real_replace = os.replace

    def _fail_commit(src, dst, *a, **k):
        if str(dst).endswith(os.sep + "upd") and str(src).find(".tmp-") >= 0:
            raise OSError("模拟提交失败")
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(pet_plugin_host.os, "replace", _fail_commit)
    ok, msg = host.install_zip(_lines_pack(tmp_path / "v2.zip", ["甲", "乙"], "1.1.0"))
    assert ok is False and "安装插件目录失败" in msg, msg
    monkeypatch.undo()
    assert os.path.isdir(str(tmp_path / "plugins" / "upd")), "上一版目录没挪回去"
    assert "甲" in [x["text"] for x in lib.lines()]
    assert "乙" not in [x["text"] for x in lib.lines()], "失败却把新内容落进库了"
    assert not os.path.isdir(str(tmp_path / "plugins" / ".prev-upd")), "留了上一版备份"


def test_卸载会连上一版备份一起删(tmp_path):
    """卸载 = 这个插件不在了：plugins/<id>/ 与 .prev-<id>/ 都不留（已落地内容仍保留）。"""
    lib = pet_lines.LineService(str(tmp_path))
    host = _host(tmp_path, lines_lib=lib)
    assert host.install_zip(_lines_pack(tmp_path / "v1.zip", ["甲"], "1.0.0"))[0] is True
    assert host.install_zip(_lines_pack(tmp_path / "v2.zip", ["甲", "乙"], "1.1.0"))[0] is True
    assert os.path.isdir(str(tmp_path / "plugins" / ".prev-upd"))
    assert host.uninstall("upd")[0] is True
    left = sorted(os.listdir(str(tmp_path / "plugins")))
    assert left == ["_installed.json"], left
    assert "甲" in [x["text"] for x in lib.lines()] and "乙" in [x["text"] for x in lib.lines()]


# ================= A2：市场页（两个页签 + 后台下载） =================

class _Pet(object):
    """最小宿主替身：只要 plugin_host（对话框缺省就取它；没有 Qt 父窗口也没关系）。"""

    def __init__(self, host):
        self.plugin_host = host


class _SignalCollector(object):
    """**先挂上、再触发**：等信号必须这样写——下载在后台线程跑，等结果回来的时候它可能
    早就 emit 完了（先发起再连接 = 撞竞态，测试会随机红）。

    等待本身是事件驱动的（信号一到就返回），超时只作防挂死兜底，断言不看耗时。
    """

    def __init__(self, signal, ms=15000):
        self.got = []
        self._signal = signal
        self._loop = QEventLoop()

        def _on(*args):
            self.got.append(args)
            self._loop.quit()

        self._on = _on
        signal.connect(_on)
        QTimer.singleShot(ms, self._loop, self._loop.quit)

    def wait(self):
        if not self.got:
            self._loop.exec()
        try:
            self._signal.disconnect(self._on)
        except (RuntimeError, TypeError):
            pass
        return self.got


def _pump(ms=50):
    """把主线程事件队列跑空（跨线程信号要回主线程才轮到槽）。"""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop, loop.quit)
    loop.exec()


def test_市场页两个页签与列口径(tmp_path):
    """「已安装」保持 v2.5.1 的六列；「可安装」是索引条目的七列（名称/类型/大小/版本/是否已装/可否安装）。"""
    pack = _pack_bytes([{"text": "x"}])
    url = "https://example.invalid/x.zip"
    host = _host(tmp_path, lines_lib=pet_lines.LineService(str(tmp_path)))
    fetcher = _Fetcher({url: pack, "https://example.invalid/index.json": _index_bytes(
        [_entry(releases=[_release(pack, url="x.zip")])])})
    idx = _market(tmp_path, fetcher)
    dlg = pet_dialogs.PluginManagerDialog(_Pet(host), index=idx)
    try:
        assert [dlg._tabs.tabText(i) for i in range(dlg._tabs.count())] == ["已安装", "可安装"]
        assert dlg._table.columnCount() == 6 and dlg._market.columnCount() == 7
        assert [dlg._market.horizontalHeaderItem(i).text() for i in range(7)] == \
            ["插件", "名称", "类型", "大小", "版本", "是否已装", "可否安装"]
        assert fetcher.calls == [], "打开对话框不该联网（远端索引要用户点了才取）"
    finally:
        dlg.close()


def test_可安装页列出来源条目的状态_未装与可更新(tmp_path):
    """索引条目画进表格：未装 / 已装 / 已装（可更新到 vX）+ 不可装原因。"""
    old = _pack_bytes([{"text": "旧"}], version="1.0.0")
    new = _pack_bytes([{"text": "新"}], version="1.1.0")
    host = _host(tmp_path, lines_lib=pet_lines.LineService(str(tmp_path)))
    lines_lib = pet_lines.LineService(str(tmp_path))
    host = _host(tmp_path, lines_lib=lines_lib)
    # 先装 1.0.0（用真包）
    p = tmp_path / "v1.zip"
    p.write_bytes(old)
    assert host.install_zip(str(p))[0] is True
    index, err = pet_plugin_index.parse_index(
        {"index_version": 1, "plugins": [
            _entry("market-lines", [_release(new, version="1.1.0", url="n.zip")]),
            _entry("never-installed", [_release(new, version="1.0.0", url="n2.zip")]),
            _entry("future", [_release(new, version="9.0.0", url="f.zip",
                                       min_host_version="99.0.0")]),
        ]}, "https://example.invalid/index.json", HOST, pet_plugin.DATA_KINDS)
    assert err == ""
    dlg = pet_dialogs.PluginManagerDialog(_Pet(host), index=None)
    try:
        dlg._apply_index(index, "")
        rows = {}
        for i in range(dlg._market.rowCount()):
            rows[dlg._market.item(i, 0).text()] = [dlg._market.item(i, c).text() for c in range(7)]
        assert rows["market-lines"][5] == "已装 v1.0.0（可更新到 v1.1.0）", rows["market-lines"]
        assert rows["never-installed"][5] == "未装"
        assert rows["future"][6].startswith("不可安装：") and "99.0.0" in rows["future"][6]
        assert rows["market-lines"][3] == pet_plugin_index.format_size(len(new))
    finally:
        dlg.close()


def test_更新按钮只在有新版本时出现_回滚按钮只在有上一版时出现(tmp_path):
    """按钮的可见性跟着数据走（A2：「更新」有新版本时才出现）。"""
    old = _pack_bytes([{"text": "旧"}], version="1.0.0")
    new = _pack_bytes([{"text": "新"}], version="1.1.0")
    lib = pet_lines.LineService(str(tmp_path))
    host = _host(tmp_path, lines_lib=lib)
    p = tmp_path / "v1.zip"
    p.write_bytes(old)
    assert host.install_zip(str(p))[0] is True
    index, _err = pet_plugin_index.parse_index(
        {"index_version": 1, "plugins": [
            _entry("market-lines", [_release(new, version="1.1.0", url="n.zip")])]},
        "https://example.invalid/index.json", HOST, pet_plugin.DATA_KINDS)
    dlg = pet_dialogs.PluginManagerDialog(_Pet(host))
    try:
        dlg._apply_index(index, "")
        dlg._tabs.setCurrentIndex(0)          # 已安装页
        dlg._table.setCurrentCell(0, 0)
        assert dlg._btn_rollback.isHidden(), "只装过一次却有回滚按钮"
        dlg._tabs.setCurrentIndex(1)          # 可安装页
        dlg._market.setCurrentCell(0, 0)
        assert not dlg._btn_update.isHidden(), "有更新的版本却没出现「更新」"
        assert dlg._btn_install.isEnabled() is False, "已装过的条目不该还能「安装」"
    finally:
        dlg.close()


def test_安装走后台线程_落地在主线程(tmp_path):
    """网络不许卡界面：取数发生在**别的**线程；校验 + 并库发生在**主**线程。"""
    pack = _pack_bytes([{"text": "后台下载的"}])
    url = "https://example.invalid/x.zip"
    lines_lib = pet_lines.LineService(str(tmp_path))
    host = _host(tmp_path, lines_lib=lines_lib)
    fetcher = _Fetcher({url: pack})
    idx = _market(tmp_path, fetcher)
    entry = {"id": "market-lines", "name": "市场包", "installable": True, "source": ["http", url],
             "url": "x.zip", "release": _release(pack, url="x.zip"), "size_text": "1 KB"}
    seen = {}
    real_install = host.install_zip

    def spy(path, source_url=""):
        seen["thread"] = threading.get_ident()
        seen["path"] = str(path)
        return real_install(path, source_url)

    host.install_zip = spy
    dlg = pet_dialogs.PluginManagerDialog(_Pet(host), index=idx)
    try:
        infos = []
        import unittest.mock as _mock
        with _mock.patch.object(pet_dialogs, "_info", lambda *a, **k: infos.append(a)), \
                _mock.patch.object(pet_dialogs, "_warn", lambda *a, **k: infos.append(a)):
            collector = _SignalCollector(dlg.packReady)     # 先挂上，再发起（避免竞态）
            assert dlg.install_entry(entry) is True, "没起下载"
            assert fetcher.entered.wait(10), "后台线程没开始取数"
            assert fetcher.threads[0] != threading.get_ident(), "取数跑在主线程上（会卡界面）"
            got = collector.wait()                          # 等这一代落地（事件驱动）
        assert got, "下载结果没回到主线程槽"
        assert seen.get("thread") == threading.get_ident(), "落地没在主线程做"
        assert "后台下载的" in [x["text"] for x in lines_lib.lines()]
        assert not os.path.isfile(seen["path"]), "装完没删下载临时文件"
        assert infos and "已安装" in infos[0][1], infos
        assert dlg._progress.isVisible() is False
    finally:
        dlg.close()


def test_在途期间连点不起第二个下载_结果只落一次(tmp_path):
    """代次守卫（pet_balance 同款）：在途时再点一次**不新起取数**；这一代落地后只落一条内容。"""
    pack = _pack_bytes([{"text": "只该进来一次"}])
    url = "https://example.invalid/x.zip"
    gate = threading.Event()
    lines_lib = pet_lines.LineService(str(tmp_path))
    host = _host(tmp_path, lines_lib=lines_lib)
    fetcher = _Fetcher({url: pack}, gate=gate)
    idx = _market(tmp_path, fetcher)
    entry = {"id": "market-lines", "name": "市场包", "installable": True, "source": ["http", url],
             "url": "x.zip", "release": _release(pack, url="x.zip"), "size_text": "1 KB"}
    dlg = pet_dialogs.PluginManagerDialog(_Pet(host), index=idx)
    try:
        import unittest.mock as _mock
        with _mock.patch.object(pet_dialogs, "_info", lambda *a, **k: None), \
                _mock.patch.object(pet_dialogs, "_warn", lambda *a, **k: None):
            collector = _SignalCollector(dlg.packReady)     # 先挂上，再发起（避免竞态）
            assert dlg.install_entry(entry) is True
            assert fetcher.entered.wait(10), "后台线程没开始取数"
            # 在途：再点两次都不许新起取数（守卫）
            assert dlg.install_entry(entry) is False
            assert dlg.install_entry(entry) is False
            assert len(fetcher.calls) == 1, "在途期间起了第二个取数：%r" % (fetcher.calls,)
            gate.set()                                  # 放行第一代
            assert collector.wait(), "第一代结果没回来"
        texts = [x["text"] for x in lines_lib.lines()]
        assert texts.count("只该进来一次") == 1, texts
        assert len(fetcher.calls) == 1, "排队的那次不该真的再取一遍（同一代守卫）"
    finally:
        dlg.close()


def test_安装失败给人话错误_不留残余(tmp_path):
    """下载失败 / 索引条目不可装都要有可读提示，且不改动插件目录与宿主库。"""
    lines_lib = pet_lines.LineService(str(tmp_path))
    host = _host(tmp_path, lines_lib=lines_lib)
    idx = _market(tmp_path, _Fetcher(err="网络请求失败：假网络挂了"))
    warned = []
    dlg = pet_dialogs.PluginManagerDialog(_Pet(host), index=idx)
    try:
        import unittest.mock as _mock
        with _mock.patch.object(pet_dialogs, "_warn",
                                lambda *a, **k: warned.append(a[-1] if a else "")), \
                _mock.patch.object(pet_dialogs, "_info", lambda *a, **k: None):
            bad = {"id": "x", "installable": False, "reason": "需要宿主 ≥ 99.0.0，当前 2.5.0"}
            assert dlg.install_entry(bad) is False
            assert any("不能装" in str(w) for w in warned), warned
            good = {"id": "market-lines", "name": "市场包", "installable": True,
                    "source": ["http", "https://example.invalid/x.zip"], "url": "x.zip",
                    "release": _release(b"x", url="x.zip"), "size_text": "1 B"}
            collector = _SignalCollector(dlg.packReady)     # 先挂上，再发起（避免竞态）
            assert dlg.install_entry(good) is True
            assert collector.wait(), "失败结果没回到主线程槽"
        assert any("假网络挂了" in str(w) for w in warned), warned
        assert lines_lib.count() == len([x for x in lines_lib.lines()])
        plugins = tmp_path / "plugins"
        assert not plugins.exists() or os.listdir(str(plugins)) == [], os.listdir(str(plugins))
    finally:
        dlg.close()


def test_禁用文案与行为一致_不等于卸载(tmp_path):
    """A3 的界面口径：状态格 tooltip 与提示行都必须点明"禁用 ≠ 卸载"（只改登记）。"""
    lib = pet_lines.LineService(str(tmp_path))
    host = _host(tmp_path, lines_lib=lib)
    assert host.install_zip(_lines_pack(tmp_path / "v1.zip", ["甲"], "1.0.0"))[0] is True
    assert host.set_enabled("upd", False)[0] is True
    dlg = pet_dialogs.PluginManagerDialog(_Pet(host))
    try:
        assert dlg._table.item(0, 4).text() == "已禁用"
        tip = dlg._table.item(0, 4).toolTip()
        assert "不等于卸载" in tip and "只改登记" in tip, tip
        assert dlg._btn_toggle.text() == "启用 / 禁用"
        assert "不等于卸载" in pet_dialogs._PLUGIN_DISABLE_TIP
        # 行为与文案一致：文件还在、内容还在
        assert os.path.isfile(str(tmp_path / "plugins" / "upd" / "manifest.json"))
        assert "甲" in [x["text"] for x in lib.lines()]
    finally:
        dlg.close()


def test_回滚按钮走真宿主_列表跟着刷新(tmp_path):
    """对话框的回滚动作委托宿主并把列表刷新回上一版（界面不做第二套逻辑）。"""
    lib = pet_lines.LineService(str(tmp_path))
    host = _host(tmp_path, lines_lib=lib)
    assert host.install_zip(_lines_pack(tmp_path / "v1.zip", ["甲"], "1.0.0"))[0] is True
    assert host.install_zip(_lines_pack(tmp_path / "v2.zip", ["甲", "乙"], "1.1.0"))[0] is True
    shots = []
    dlg = pet_dialogs.PluginManagerDialog(_Pet(host))
    try:
        import unittest.mock as _mock
        with _mock.patch.object(pet_dialogs, "_info", lambda *a, **k: shots.append(a)), \
                _mock.patch.object(pet_dialogs, "_warn", lambda *a, **k: shots.append(a)):
            assert dlg.rollback_id("upd") is True
        assert shots and "回滚到上一版 1.0.0" in shots[0][2], shots
        assert dlg._table.item(0, 2).text() == "1.0.0", "列表没跟着刷新"
    finally:
        dlg.close()


def test_对话框的索引下载器按宿主目录与版本现造(tmp_path):
    """没注入 index 时：对话框按宿主目录 / 宿主版本 / 可落地类别现造一个（默认只读随包索引）。"""
    host = pet_plugin_host.PluginHost(str(tmp_path), HOST)
    plugins = tmp_path / "plugins"
    plugins.mkdir(exist_ok=True)
    (plugins / "index.json").write_bytes(_index_bytes([_entry(releases=[
        _release(_pack_bytes([{"text": "随包索引里的包"}]), url="packs/x.zip")])]))
    dlg = pet_dialogs.PluginManagerDialog(_Pet(host))
    try:
        idx = dlg._index_ref()
        assert idx is not None and idx.plugins_dir == str(plugins)
        assert idx.index_url == ""
        assert dlg._market.rowCount() == 1, "打开时没读随包索引"
        assert dlg._market.item(0, 0).text() == "market-lines"
    finally:
        dlg.close()

# ============ 找茬审查 P2-a/b/c（v2.6.0 第 4 轮）：远端路径先硬化再谈接线 ============
# 本版 plugin_index_url 还没有配置入口（远端整条链生产不可达），所以这几条钉的是**判据**，
# 不是界面行为——下一轮接线时它们就是护栏。

def test_明文http一律拒_只收https(tmp_path):
    """P2-a：远端只收 https —— http 索引 / http 包都拒，而且**在取数之前**就拒。

    索引与包**同源**（sha256 与 bytes 都写在索引里），明文链路上中间人可以同时换掉两边、
    哈希照样对得上 → 这套完整性保护等于零。
    能真失败：把 insecure_reason 改成恒返回空串 → 下面每条断言都红。
    """
    assert pet_plugin_index.is_remote("http://h/x.json") is True, "is_remote 仍要认得 http"
    assert pet_plugin_index.is_insecure_remote("http://h/x.json") is True
    assert pet_plugin_index.is_insecure_remote("HTTPS://h/x.json") is False, "大小写不该绕过"
    assert pet_plugin_index.is_insecure_remote("/tmp/x.json") is False

    kind, why = pet_plugin_index.resolve_url("http://cdn.invalid/a.zip", "")
    assert kind is None and "https" in why, why
    kind2, why2 = pet_plugin_index.resolve_url("packs/a.zip", "http://host.invalid/dir/index.json")
    assert kind2 is None and "https" in why2, why2
    fetcher = _Fetcher()
    idx = _market(tmp_path, fetcher, index_url="http://host.invalid/index.json")
    index, err = idx.load_index()
    assert index is None and "https" in err, err
    assert fetcher.calls == [], "http 索引不该被取回来再判"


def test_远端索引不许指向本地路径_随包索引不受限(tmp_path):
    """P2-b：索引来源是远端时，条目 url 不许是 file:// / 盘符 / 绝对本地路径（跨信任域）。

    远端索引若能指挥宿主读本机文件，就等于把"远端信任域"和"本机文件系统"接上了。
    **负控制组**：随包本地索引不受这条限制（它本来就是本机自己的文件）——防的是有人
    一刀切成"只许相对路径"，把离线安装也一起砍掉。
    能真失败：去掉 resolve_url 里的 base_remote 分支 → 三条跨域断言红。
    """
    base = "https://host.invalid/dir/index.json"
    for raw in ("file:///C:/Windows/win.ini", "C:/Windows/win.ini", "/etc/passwd"):
        kind, why = pet_plugin_index.resolve_url(raw, base)
        assert kind is None and "跨信任域" in why, (raw, why)
    local_base = str(tmp_path / "plugins" / "index.json")
    assert pet_plugin_index.resolve_url("file:///C:/Windows/win.ini", local_base)[0] == "file"
    assert pet_plugin_index.resolve_url("/etc/passwd", local_base)[0] == "file"

    pack = _pack_bytes([{"text": "x"}])
    index, err = pet_plugin_index.parse_index(
        {"index_version": 1, "plugins": [_entry(releases=[
            _release(pack, url="file:///C:/Windows/win.ini")])]},
        base, HOST, pet_plugin.DATA_KINDS)
    assert err == "", err
    entry = index["entries"][0]
    assert entry["installable"] is False and "跨信任域" in entry["reason"], entry


def test_上限前置_能收limit的取数在取数前就拿到上限(tmp_path):
    """P2-c：上限**前置**——收 limit 的取数实现在取数前就拿到本次上限。

    索引那条路传的是 INDEX_MAX_BYTES；包那条路传的是**索引声明的 bytes**
    （省得把一坨注定要丢的数据整个读回来）。
    能真失败：把 _fetch_bytes 的 limit 参数删掉（回到先取回来再判大小）→ 记录不到上限，红。
    """
    index_url = "https://host.invalid/index.json"
    pack_url = "https://host.invalid/x.zip"
    pack = _pack_bytes([{"text": "x"}])
    table = {index_url: _index_bytes([_entry(releases=[])]), pack_url: pack}
    seen = {}

    def fetch_with_limit(url, limit=0):
        seen[url] = limit
        if url not in table:
            return None, "假取数里没有这个地址：%s" % url
        return table[url], ""

    idx = _market(tmp_path, fetch_with_limit, index_url=index_url)
    index, err = idx.load_index()
    assert err == "" and index is not None, err
    assert seen[index_url] == pet_plugin_index.INDEX_MAX_BYTES, seen

    seen.clear()
    dl = _market(tmp_path, fetch_with_limit, index_url="")
    entry = {"id": "market-lines", "installable": True, "source": ["http", pack_url],
             "url": "x.zip", "release": _release(pack, url="x.zip")}
    path, derr = dl.download(entry)
    assert derr == "" and path and os.path.isfile(path), derr
    assert seen[pack_url] == len(pack), ("包那条路该拿声明 bytes 当前置上限", seen)
    dl.cleanup()


def test_本地取数边读边判_到上限就停手(tmp_path):
    """P2-c：本地分支分块读 + 累计，超上限立刻停手（此前是整份读完再判）。

    **结构性断言，不依赖机器速度**：错误文案里的已读字节数必须只比上限多一点，
    而文件本身远大于它——证明它是边读边判停下来的，不是读完了才说大。
    能真失败：本地分支改回一次性读完整份 → 已读字节数变成文件全长，红。
    """
    chunk = pet_plugin_index.FETCH_CHUNK
    size = chunk * 4 + 7
    big = tmp_path / "big.bin"
    big.write_bytes(b"Z" * size)
    cap = chunk + 1
    data, err = _REAL_DEFAULT_FETCH(str(big), limit=cap)
    assert data is None and "超过上限" in err, err
    done = int(err.split("已读 ")[1].split(" 字节")[0])
    assert cap < done, ("没超过上限就该正常读回，不该报错", done, cap)
    assert done <= cap + chunk, ("读过头了：停手点该在上限加一块之内", done, cap)
    assert done < size, "把整份读完了才判 = 上限根本没前置"
    data2, err2 = _REAL_DEFAULT_FETCH(str(big), limit=size)
    assert err2 == "" and len(data2) == size, err2


def test_远端ContentLength自报超限_一个字节都不读(tmp_path):
    """P2-c：对端自己在 Content-Length 里说超了 → 连第一块都不读。

    **这条护栏抓的是"前置判断被摘掉"**（v2.6.0 第 4 轮收口）：假 read 一旦被调用就抛，
    异常会被 default_fetch 的 except Exception 兜底成"网络请求失败：…"——所以断言必须
    **同时**排除那条兜底路径。此前只断言"对端自报"在错误串里，而假 read 的异常文本恰好
    自带"对端自报"四个字 → 把前置判断摘掉（if False:）用例照样绿，等于假覆盖。
    能真失败：把 pet_plugin_index.default_fetch 里那条前置判断改成 if False: →
    read 被调用，三条断言（calls / 对端自报 / 不是网络请求失败）全红。
    """
    too_big = str(pet_plugin_index.FETCH_CHUNK * 8)
    calls = []

    class _Resp(object):
        headers = {"Content-Length": too_big}

        def read(self, n=-1):
            calls.append(n)
            # 文案**刻意不含"对端自报"**：不许让取数被调用这条路径冒充前置判断的结论
            raise AssertionError("READ-CALLED")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    import unittest.mock as _mock
    with _mock.patch.object(pet_plugin_index.urllib.request, "urlopen", lambda *a, **k: _Resp()):
        data, err = _REAL_DEFAULT_FETCH("https://host.invalid/x.bin",
                                        limit=pet_plugin_index.FETCH_CHUNK)
    assert calls == [], "前置判断没生效：内容被 read 了 %r" % (calls,)
    assert data is None, err
    assert "对端自报" in err, err
    # 反例判据：取数被调用 → 兜底成"网络请求失败：…"，那条错误串绝不能算通过
    assert "网络请求失败" not in err, ("错误串来自取数被调用那条兜底路径，不是前置判断的结论", err)


def test_注入取数也有容量上限_超了不落盘(tmp_path, monkeypatch):
    """P2-c：老契约 fetch(url) 收不到 limit，但取回来后**立刻**按容量上限判一次。

    此前注入这条路上一条上限都没有：注入的取数想看多大就看多大，全进内存再写盘。
    能真失败：去掉 _fetch_bytes 里那条上限判断 → 200 字节照样落盘，红。
    """
    import pet_export
    monkeypatch.setattr(pet_export, "EXPORT_MAX_BYTES", 100)
    url = "https://host.invalid/big.zip"
    blob = b"Z" * 200
    idx = _market(tmp_path, _Fetcher({url: blob}), index_url="")
    entry = {"id": "market-lines", "installable": True, "source": ["http", url],
             "url": "big.zip", "release": _release(blob, url="big.zip")}
    path, err = idx.download(entry)
    assert path is None and "容量上限" in err, err
    assert not (tmp_path / "plugins").exists(), "超限还在 plugins/ 下落了东西"


def test_相对地址拒路径穿越与空段(tmp_path):
    """P3-2：相对 url 的每一段都要规矩（.. / 空段 / 保留设备名一律拒）。

    此前相对分支只做 if p 丢空段，".." 原样进 os.path.join —— 随包索引里的
    "../../..//evil.zip" 能把取数目标指到索引目录之外。
    能真失败：把 resolve_url 里 _rel_url_reason 那道判断去掉 → 前两条断言红。
    """
    base = str(tmp_path / "plugins" / "index.json")
    for raw in ("../../..//evil.zip", "packs/../evil.zip", "..", "a//b.zip",
                "packs/nul.png", "packs/con.png"):
        kind, why = pet_plugin_index.resolve_url(raw, base)
        assert kind is None, (raw, kind, why)
        assert "不合法" in why, (raw, why)
    # 控制组：正常相对地址照旧解析到索引旁边（别把整条相对口径一起砍掉）
    kind, target = pet_plugin_index.resolve_url("packs/x.zip", base)
    assert kind == "file" and target == str(tmp_path / "plugins" / "packs" / "x.zip"), target


def test_file_url折成本机路径(tmp_path):
    """P3-3：file:///C:/x 得到 C:\\x —— 不是 "/C:/x"（那个在 Windows 上不是绝对路径）。

    能真失败：把 _file_url_to_path 换回裸的 url[7:] → 实测值是 '/C:/x'，两条断言都红。
    """
    base = str(tmp_path / "plugins" / "index.json")
    kind, target = pet_plugin_index.resolve_url("file:///C:/Windows/win.ini", base)
    assert kind == "file", (kind, target)
    assert target == os.path.normpath("C:/Windows/win.ini"), target
    assert os.path.isabs(target), "折出来的仍旧不是绝对路径：%r" % (target,)


# ============ 兼容审查 P1-1（v2.6.0 第 4 轮）：本地包安装入口必须真的在 ============

def _bottom_row_texts(dlg):
    """底排按钮行的按钮文字（stick_buttons 记下的那一行，不是全窗口扫按钮）。"""
    row = dlg._btn_row
    out = []
    for i in range(row.count()):
        w = row.itemAt(i).widget()
        if w is not None:
            out.append(w.text())
    return out


def test_底排必须有本地包安装入口_而且真的能装(tmp_path, monkeypatch):
    """P1-1：v2.5.1 的「安装…」（选本地 zip）入口本轮被弄丢了，提示行却还在说它可用。

    背景：v2.5.1 底排是「安装…」→ QFileDialog 选本地 zip —— 那是用户装第三方 / 自制包的
    **唯一入口**；本轮把「安装」改成"从索引装选中条目"时，_install() 整个失去了调用点，
    而 6142 的提示行仍写「「安装…」选本地包仍然可用」：界面在骗用户。
    能真失败：删掉 _btn_install_file（回到只有从索引装的「安装」）→ 第一条断言红。
    """
    lib = pet_lines.LineService(str(tmp_path))
    host = _host(tmp_path, lines_lib=lib)
    dlg = pet_dialogs.PluginManagerDialog(_Pet(host))
    try:
        texts = _bottom_row_texts(dlg)
        assert "安装…" in texts, "底排没有本地包安装入口（用户装不了自制包）：%r" % (texts,)
        assert dlg._btn_install_file.isEnabled(), "本地包入口被禁用了（它不读索引，不该跟索引联动）"

        # 索引读不出来时：提示行说"选本地包仍然可用" → 那句必须是真的
        plugins = tmp_path / "plugins"
        plugins.mkdir(exist_ok=True)
        (plugins / "index.json").write_text("{ 这不是 json", encoding="utf-8")
        dlg.refresh_index()
        hint = dlg._hint.text()
        assert "安装…" in hint, "索引坏掉时的提示行不再提本地入口：%r" % (hint,)
        assert dlg._btn_install_file.isEnabled(), "提示说可用、按钮却不可用 = 界面在骗用户"

        # 它**真的**能装一个本地 zip（install_path 只有测试直接调 = 假覆盖）
        pack = _pack_bytes([{"text": "本地包装进来的"}])
        local_zip = tmp_path / "local.zip"
        local_zip.write_bytes(pack)
        monkeypatch.setattr(pet_dialogs.QFileDialog, "getOpenFileName",
                            staticmethod(lambda *a, **k: (str(local_zip), "")))
        shots = []
        monkeypatch.setattr(pet_dialogs, "_info", lambda *a, **k: shots.append(a))
        monkeypatch.setattr(pet_dialogs, "_warn", lambda *a, **k: shots.append(a))
        dlg._btn_install_file.click()       # ← 走按钮**自己的 clicked 连接**（不绕过接线）
        assert "本地包装进来的" in [x["text"] for x in lib.lines()], "本地包没装进去"
        assert shots, "装完没有任何提示"
    finally:
        dlg.close()


def test_更新且新旧内容零交集_新版进库旧版仍在(tmp_path):
    """T6：同 id 更新、新旧内容**零交集**（["甲"] → ["乙"]）——乙进库、甲仍在、目录版本变了。

    这条覆盖的是去重语义的边界：指纹账里一条都对不上时，新版内容必须**真的并进库**，
    而旧版内容**不许**被顺手清掉（更新不是替换整个库）。此前没有任何用例走这条。
    能真失败：把 _land_lines 的"指纹没见过就落地"改成"整包跳过"（v2.5.1 的老口径）→
    乙永远进不来，第二条断言红。
    """
    lib = pet_lines.LineService(str(tmp_path))
    host = _host(tmp_path, lines_lib=lib)
    assert host.install_zip(_lines_pack(tmp_path / "v1.zip", ["甲"], "1.0.0"))[0] is True
    assert "甲" in [x["text"] for x in lib.lines()]
    assert "乙" not in [x["text"] for x in lib.lines()]
    ok, msg = host.install_zip(_lines_pack(tmp_path / "v2.zip", ["乙"], "1.1.0"))
    assert ok is True, msg
    texts = [x["text"] for x in lib.lines()]
    assert "乙" in texts, "新版内容（与旧版零交集）没有并进库：%r" % (texts,)
    assert texts.count("甲") == 1, "旧版内容被更新顺手清掉/重复落了：%r" % (texts,)
    rows, problems = host.list_installed()
    assert problems == [], problems
    rec = [r for r in rows if str(r.get("id") or "") == "upd"]
    assert rec and str(rec[0].get("version")) == "1.1.0", rows
