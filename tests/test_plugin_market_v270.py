# -*- coding: utf-8 -*-
"""v2.7.0（代理 C）插件线小账 a~d 的回归（每条都配"能真失败"的变异）。

a install_file 必须核对**索引条目的 data_kind** 与**包的 manifest data_kind** 是否一致
  （此前只核 id：索引写 lines、包里装的是 role 时，界面按索引显示成一种、落地成另一种）；
b 当前版目录不在（手工删 / 半截失败）而 .prev-<id>/ 还在时，此前 history 被清空
  （回滚点白丢）而备份原样留成孤儿 —— 现在两者必须**成对**；
c 同内容折叠（差集为空）时回滚文案不许说"撤销了本版新导入的 0 项"；
d razor（_dev/silent_except_whitelist.py）不只看"证据填没填"，还要看**证据原文能不能在
  它自称的那个文件里找到**。

判据全部是**结构性事实**（目录在不在 / 登记里记了什么 / 宿主库里有哪些条目），
没有任何"必须在 X 毫秒内"的断言（铁律 3）。
"""
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pet_lines          # noqa: E402
import pet_plugin         # noqa: E402
import pet_plugin_host    # noqa: E402
import pet_plugin_index   # noqa: E402

HOST = "2.5.0"


# ---------------- 造包 / 造索引 ----------------

def _pack(path, texts, pid="upd", version="1.0.0", data_kind="lines"):
    """真 zip（过真校验器）：payload/lines.json + 真哈希的 manifest。"""
    body = json.dumps({"lines": [{"text": t, "category": "idle"} for t in texts]},
                      ensure_ascii=False).encode("utf-8")
    manifest = {"format": pet_plugin.PLUGIN_FORMAT, "version": 1, "payload_root": "payload/",
                "created_at": "2026-01-01T00:00:00",
                "files": [{"path": "payload/lines.json",
                           "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}],
                "plugin": {"id": pid, "name": "小账包 " + pid, "version": version,
                           "kind": "data", "data_kind": data_kind, "code": False,
                           "min_host_version": HOST, "api_version": 1, "capabilities": []}}
    with zipfile.ZipFile(str(path), "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        zf.writestr("payload/lines.json", body)
    return str(path)


def _host(tmp_path, lib):
    return pet_plugin_host.PluginHost(str(tmp_path), HOST, lines_lib=lib)


def _index_entry(tmp_path, pack_path, data_kind, pid="upd", version="1.0.0"):
    """走**真索引解析**拿到归一后的条目（install_file 吃的就是这种形状）。"""
    import io
    with io.open(pack_path, "rb") as fh:
        data = fh.read()
    plugins = tmp_path / "plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    idx = {"index_version": 1, "updated_at": "2026-01-01", "host_min": "2.0.0",
           "plugins": [{"id": pid, "name": "小账包", "kind": "data", "data_kind": data_kind,
                        "code": False, "summary": "一句话", "author": "测试",
                        "releases": [{"version": version, "min_host_version": HOST,
                                      "api_version": 1, "url": "packs/p.zip",
                                      "sha256": hashlib.sha256(data).hexdigest(),
                                      "bytes": len(data), "published_at": "2026-01-01"}]}]}
    (plugins / "index.json").write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
    ix = pet_plugin_index.PluginIndex(str(plugins), host_version=HOST)
    index, err = ix.load_index()
    assert index is not None, err
    return ix, index["entries"][0]


def _reg(tmp_path):
    p = tmp_path / "plugins" / "_installed.json"
    return json.loads(p.read_text(encoding="utf-8"))["plugins"]


def _texts(lib):
    return [x["text"] for x in lib.lines()]


# ================= a：索引与包的 data_kind 必须一致 =================

def test_a_索引与包的data_kind不一致必须拒绝(tmp_path):
    """索引说「role」、包里装的是「lines」→ 拒绝安装，宿主库一个字节不动、登记表不建。

    此前只核 id：两边 id 一样就放行，市场页按索引显示成角色包、落地却往台词库塞台词。
    能真失败：去掉 install_file 里那条 data_kind 比较 → 本用例红（装上了、台词进库了）。
    """
    lib = pet_lines.LineService(str(tmp_path))
    host = _host(tmp_path, lib)
    pack = _pack(tmp_path / "wrong.zip", ["甲"], data_kind="lines")
    ix, entry = _index_entry(tmp_path, pack, data_kind="role")
    assert entry["data_kind"] == "role" and entry["id"] == "upd"

    ok, msg = ix.install_file(host, entry, pack)
    assert ok is False, msg
    assert "「role」" in msg and "「lines」" in msg, msg
    assert "已拒绝安装" in msg, msg
    assert "甲" not in _texts(lib), "拒绝了却把内容落进库了"
    assert not (tmp_path / "plugins" / "upd").exists(), "拒绝了却建了插件目录"
    reg_path = tmp_path / "plugins" / "_installed.json"
    assert not reg_path.is_file() or "upd" not in _reg(tmp_path), "拒绝了却写了安装登记"


def test_a_索引与包的data_kind一致照常安装(tmp_path):
    """反向（契约的另一半）：类别一致时照常安装——判据不许把正常包也拦掉。"""
    lib = pet_lines.LineService(str(tmp_path))
    host = _host(tmp_path, lib)
    pack = _pack(tmp_path / "good.zip", ["乙"], data_kind="lines")
    ix, entry = _index_entry(tmp_path, pack, data_kind="lines")

    ok, msg = ix.install_file(host, entry, pack)
    assert ok is True and "已安装插件" in msg, msg
    assert "乙" in _texts(lib), "类别一致却被拦下来了"
    assert (tmp_path / "plugins" / "upd").is_dir()


# ================= b：history 与 .prev-<id>/ 必须成对 =================

def test_b_当前版目录不在而备份在_回滚点不丢也不留孤儿(tmp_path):
    """v1 → v2（留下 .prev-<id>/）→ **手工删掉 plugins/<id>/** → 再装 v3。

    此前：history 被清成 []（回滚点白丢、回滚按钮变灰），.prev-<id>/ 原样留在盘上成孤儿。
    现在：备份正是 history[-1] 记的那一版 payload，配对关系还成立 → 回滚点保住、没有孤儿。
    能真失败：把 already-and-not-target_is_dir 分支里的 keep_history 改回 False → 红。
    """
    lib = pet_lines.LineService(str(tmp_path))
    host = _host(tmp_path, lib)
    assert host.install_zip(_pack(tmp_path / "v1.zip", ["甲"], version="1.0.0"))[0] is True
    assert host.install_zip(_pack(tmp_path / "v2.zip", ["甲", "乙"], version="1.1.0"))[0] is True
    prev = tmp_path / "plugins" / ".prev-upd"
    assert prev.is_dir(), "正常更新没有留下上一版备份"

    shutil.rmtree(str(tmp_path / "plugins" / "upd"))          # 极端情况：当前版目录不见了
    assert host.install_zip(_pack(tmp_path / "v3.zip", ["甲", "乙", "丙"],
                                  version="1.2.0"))[0] is True
    rec = _reg(tmp_path)["upd"]
    assert prev.is_dir(), "备份成了孤儿（没人能回滚它，也没人清它）"
    assert rec["history"], "回滚点白丢了：history 被清空，而备份还躺在盘上"
    assert rec["history"][-1]["version"] == "1.0.0", rec["history"]

    ok, msg = host.rollback("upd")
    assert ok is True and "回滚到上一版 1.0.0" in msg, msg
    assert not prev.exists(), "回滚后备份还在"
    man = json.loads((tmp_path / "plugins" / "upd" / "manifest.json").read_text(encoding="utf-8"))
    assert man["plugin"]["version"] == "1.0.0", "插件目录没有回到备份里那一版"
    assert "乙" not in _texts(lib) and "丙" not in _texts(lib), _texts(lib)
    assert "甲" in _texts(lib)


def test_b_没有备份就不许留悬空回滚点(tmp_path):
    """plugins/<id>/ 还在、.prev-<id>/ 没了 → history 一并清掉，回滚如实说"没有上一版"。

    场景：v1 → v2（有备份）→ 手工删掉 .prev-<id>/ → 再装同一个 v2（内容全一致 → 走
    "重复安装"分支）。此前那条分支把 history 原样留下：登记里记着一个**盘上不存在**的回滚点，
    点回滚只会得到"上一版目录已经不在了"。
    能真失败：把 repeat-and-target_is_dir 分支里的 keep_history 改回 True → 红。
    """
    lib = pet_lines.LineService(str(tmp_path))
    host = _host(tmp_path, lib)
    assert host.install_zip(_pack(tmp_path / "v1.zip", ["甲"], version="1.0.0"))[0] is True
    assert host.install_zip(_pack(tmp_path / "v2.zip", ["甲", "乙"], version="1.1.0"))[0] is True
    shutil.rmtree(str(tmp_path / "plugins" / ".prev-upd"))    # 只删备份：当前版目录还在
    assert (tmp_path / "plugins" / "upd").is_dir()

    ok, msg = host.install_zip(_pack(tmp_path / "v2b.zip", ["甲", "乙"], version="1.1.0"))
    assert ok is True and "完全一致" in msg, msg
    assert not (tmp_path / "plugins" / ".prev-upd").exists()
    rec = _reg(tmp_path)["upd"]
    assert rec["history"] == [], "没有可恢复的 payload 却留着回滚记录：%r" % (rec["history"],)
    ok, msg = host.rollback("upd")
    assert ok is False and "没有上一版" in msg, msg


def test_b_登记里没有这条却留着备份_一并清掉(tmp_path):
    """登记被抹掉（plugins/_installed.json 没了）而 .prev-<id>/ 还在 → 它是无主的孤儿，清掉。

    能真失败：去掉 install_zip 里那条 not-already-and-prev_is_dir 的清理 → 红。
    """
    lib = pet_lines.LineService(str(tmp_path))
    host = _host(tmp_path, lib)
    assert host.install_zip(_pack(tmp_path / "v1.zip", ["甲"], version="1.0.0"))[0] is True
    assert host.install_zip(_pack(tmp_path / "v2.zip", ["甲", "乙"], version="1.1.0"))[0] is True
    prev = tmp_path / "plugins" / ".prev-upd"
    assert prev.is_dir()
    os.remove(str(tmp_path / "plugins" / "_installed.json"))   # 登记没了：备份从此无主

    ok, msg = host.install_zip(_pack(tmp_path / "v2c.zip", ["甲", "乙"], version="1.1.0"))
    assert ok is True, msg
    assert not prev.exists(), "没有任何登记记录能跟它配对，备份却留在盘上（孤儿）"
    left = sorted(os.listdir(str(tmp_path / "plugins")))
    assert left == ["_installed.json", "upd"], left


def test_b_登记写失败时上一版目录要挪回去(tmp_path, monkeypatch):
    """更新时登记写失败 = 这次更新没成立 → 上一版目录必须**挪回去**继续可用。

    此前只撤新目录、不回挪备份：登记说装着上一版、plugins/<id>/ 却不在、真 payload 躺在
    .prev-<id>/ —— 这正是 b 那条孤儿备份的制造者（与 S1-b 提交失败分支同口径）。
    能真失败：去掉登记失败分支里的 os.replace(previous, target) → 第一条断言红。
    """
    lib = pet_lines.LineService(str(tmp_path))
    host = _host(tmp_path, lib)
    assert host.install_zip(_pack(tmp_path / "v1.zip", ["甲"], version="1.0.0"))[0] is True
    monkeypatch.setattr(pet_plugin_host.PluginHost, "_save_registry",
                        lambda self, registry: "模拟登记写失败")

    ok, msg = host.install_zip(_pack(tmp_path / "v2.zip", ["甲", "乙"], version="1.1.0"))
    assert ok is False and "安装登记失败" in msg, msg
    monkeypatch.undo()
    assert (tmp_path / "plugins" / "upd").is_dir(), "上一版目录没挪回去（插件目录整个不见了）"
    assert not (tmp_path / "plugins" / ".prev-upd").exists(), "留了备份残余"
    man = json.loads((tmp_path / "plugins" / "upd" / "manifest.json").read_text(encoding="utf-8"))
    assert man["plugin"]["version"] == "1.0.0", "挪回去的不是上一版"
    assert "乙" not in _texts(lib), "失败却把新版内容落进库了"
    assert _reg(tmp_path)["upd"]["version"] == "1.0.0", "磁盘上的登记被改动了"


# ================= c：回滚文案与行为对齐 =================

def test_c_同内容折叠回滚不说撤销了0项(tmp_path):
    """v1 → v2（内容与 v1 完全一致，按指纹一条都没重复落）→ 回滚。

    差集是空的，此前文案照念"撤销了本版新导入的 0 项内容"——用户读到一句自相矛盾的
    "撤销了 0 项"。现在 0 项时明说"没有新导入的内容"，并且**仍然真的回滚了目录与登记**。
    能真失败：把回滚成功文案改回无条件"撤销了本版新导入的 N 项" → 第二条断言红。
    """
    lib = pet_lines.LineService(str(tmp_path))
    host = _host(tmp_path, lib)
    assert host.install_zip(_pack(tmp_path / "v1.zip", ["甲"], version="1.0.0"))[0] is True
    assert host.install_zip(_pack(tmp_path / "v2.zip", ["甲"], version="1.1.0"))[0] is True
    assert _texts(lib).count("甲") == 1, "同内容折叠失效（重复落地了）"

    ok, msg = host.rollback("upd")
    assert ok is True and "回滚到上一版 1.0.0" in msg, msg
    assert "撤销了本版新导入的 0 项" not in msg, "回滚文案说了一句自相矛盾的「撤销了 0 项」：%r" % msg
    assert "没有条目需要撤销" in msg, msg
    assert _reg(tmp_path)["upd"]["version"] == "1.0.0", "文案改好了，回滚却没真的发生"


def test_c_有内容可撤时文案照旧(tmp_path):
    """契约的另一半：差集非空时仍要说清"撤销了 N 项"（不许为了 0 项那条把文案改糊）。"""
    lib = pet_lines.LineService(str(tmp_path))
    host = _host(tmp_path, lib)
    assert host.install_zip(_pack(tmp_path / "v1.zip", ["甲"], version="1.0.0"))[0] is True
    assert host.install_zip(_pack(tmp_path / "v2.zip", ["甲", "乙"], version="1.1.0"))[0] is True
    ok, msg = host.rollback("upd")
    assert ok is True and "撤销了本版新导入的 1 项" in msg, msg
    assert "乙" not in _texts(lib)


# ================= d：razor 的证据原文必须是真的 =================

def _load_wl():
    """按路径加载白名单判定器（它不是包内模块，与 tests/test_silent_except_v252.py 同款）。"""
    spec = importlib.util.spec_from_file_location(
        "silent_except_whitelist_v270", os.path.join(ROOT, "_dev", "silent_except_whitelist.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_d_razor会核对证据原文能不能找到():
    """d：evidence **非空**不够，得真的出现在它自称的那个文件里。

    正向：现有整份白名单零假红（307 条证据全部逐条命中）。
    负向：把一条真条目的证据换成"别处抄来的一句话" → 必须被点名。
    查不了的文件（合成树 / 路径不对）→ unknown，不误报。
    能真失败：把 check() 里那段 evidence_in_source 判据注释掉 → 负向断言红。
    """
    wl = _load_wl()
    data = wl.load_whitelist()
    entries, _findings = wl.scan_silent()
    assert entries and data["entries"], "扫描或白名单是空的，判据等于空转"
    assert [p for p in wl.check(entries, data) if "源码证据" in p] == [], "现有白名单有证据对不上的条目"

    fake = {"entries": [dict(e) for e in data["entries"]]}
    fake["entries"][0]["evidence"] = "except Exception: 这句话在任何源文件里都不存在"
    probs = wl.check(entries, fake)
    assert any("源码证据对不上" in p for p in probs), probs

    assert wl.evidence_in_source({"file": "并没有这个文件.py", "evidence": "x"})[0] == "unknown"
    assert wl.evidence_in_source({"file": "pet_lines.py", "evidence": ""})[0] == "unknown"
