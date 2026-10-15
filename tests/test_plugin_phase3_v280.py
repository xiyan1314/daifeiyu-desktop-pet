# -*- coding: utf-8 -*-
"""v2.8.0 第 6 轮（代理 B）：远端插件索引 Phase 3 接线（pet_plugin_index + pet_config 的键）。

覆盖（每条都配"能真失败"的变异，见各用例 docstring 的「变异」一行）：
  A 三个接口的契约 —— set_remote_base / refresh / source_info
    （校验 → 先写盘再改内存 · 缓存落地 · 成功/失败话术 · count 口径 · 空串=回随包）
  B 网络边界 —— refresh 是**唯一**联网处；load_index 生产口径（没注入 fetch）绝不联网，
    没缓存时退回随包索引并如实标注来源（"刷新失败仍能用随包索引"）
  C v2.6.0 硬化保留 —— 只收 https · 远端不许指向本地 · 体积上限前置+事后 ·
    sha256 / bytes 不符拒收且不留残余（这条链走的是**新的** refresh→缓存→load_index 全程）
  D 键名单一来源 —— pet_config 与 pet_plugin_index 两处常量必须一致

**测试永不联网**：远端取数一律注入假 fetch；autouse 守卫把 default_fetch 换成
"远端一调用就炸"（本地路径照旧——随包索引读的就是本地文件）。

    python -B -m pytest tests/test_plugin_phase3_v280.py -o addopts="" -q
"""
import hashlib
import io
import json
import os
import sys
import zipfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pet_config          # noqa: E402
import pet_plugin          # noqa: E402
import pet_plugin_index    # noqa: E402

HOST = "2.5.0"
BASE = "https://example.invalid/dir"          # 目录形态（要拼 index.json）
TARGET = BASE + "/index.json"

_REAL_DEFAULT_FETCH = pet_plugin_index.default_fetch


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """**远端**取数一调用就炸（测试永不联网）；本地路径照旧（随包索引要用）。"""
    def _guarded(url, progress=None):
        if pet_plugin_index.is_remote(url):
            raise AssertionError("测试里不许真联网（远端取数必须注入 fetch）：%s" % url)
        return _REAL_DEFAULT_FETCH(url, progress)
    monkeypatch.setattr(pet_plugin_index, "default_fetch", _guarded)
    return _guarded


# ---------------- 造包 / 造索引 / 假取数 ----------------

def _pack_bytes(lines=(), pid="phase3-lines", version="1.0.0", data_kind="lines"):
    """造一个**合法**插件包 → zip 字节（files 清单用真哈希，包一定过校验器）。"""
    payload = {"lines.json": json.dumps({"lines": list(lines)}, ensure_ascii=False).encode("utf-8")}
    files = [{"path": "payload/" + rel, "sha256": hashlib.sha256(data).hexdigest(),
              "bytes": len(data)} for rel, data in sorted(payload.items())]
    manifest = {"format": pet_plugin.PLUGIN_FORMAT, "version": 1, "payload_root": "payload/",
                "created_at": "2026-01-01T00:00:00", "files": files,
                "plugin": {"id": pid, "name": "Phase3 包 " + pid, "version": version,
                           "kind": "data", "data_kind": data_kind, "code": False,
                           "min_host_version": HOST, "api_version": 1, "capabilities": []}}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        for rel, data in sorted(payload.items()):
            zf.writestr("payload/" + rel, data)
    return buf.getvalue()


_UNSET = object()


def _release(pack, url="packs/p.zip", version="1.0.0", sha=_UNSET, size=_UNSET):
    return {"version": version, "min_host_version": HOST, "api_version": 1, "url": url,
            "sha256": hashlib.sha256(pack).hexdigest() if sha is _UNSET else sha,
            "bytes": len(pack) if size is _UNSET else size, "published_at": "2026-01-01"}


def _entry(pid, releases=(), **over):
    item = {"id": pid, "name": "Phase3 包", "kind": "data", "data_kind": "lines", "code": False,
            "summary": "一句话", "author": "测试", "releases": list(releases)}
    item.update(over)
    return item


def _index_bytes(plugins, updated_at="2026-02-02", host_min="2.0.0", index_version=1):
    return json.dumps({"index_version": index_version, "updated_at": updated_at,
                       "host_min": host_min, "plugins": list(plugins)},
                      ensure_ascii=False).encode("utf-8")


class _Fetcher(object):
    """假取数：url → bytes。calls 记下每一次取数（结构性断言：联没联网、取了几次）。"""

    def __init__(self, table=None, err=None):
        self.table = dict(table or {})
        self.err = err
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        if self.err:
            return None, self.err
        if url not in self.table:
            return None, "假取数里没有这个地址：%s" % url
        return self.table[url], ""


def _plugins_dir(tmp_path, bundled=None):
    """<tmp>/plugins（可选：写一份随包 index.json）→ 路径。"""
    d = tmp_path / "plugins"
    d.mkdir(parents=True, exist_ok=True)
    if bundled is not None:
        (d / "index.json").write_bytes(bundled)
    return str(d)


def _cfg_box(url=""):
    """注入用的配置盒子：cfg dict + 可注入失败/记录写入的 save_cfg。"""
    box = {"cfg": {pet_config.PLUGIN_INDEX_URL_KEY: url}, "saved": [], "err": None}

    def save(new):
        box["saved"].append(dict(new))
        return box["err"]

    return box, (lambda: box["cfg"]), save


def _ix(tmp_path, fetch=None, index_url="", bundled=None, cfgbox=None, **kw):
    """构造被测 PluginIndex（默认接上配置读写；bundled 给了就写随包索引）。"""
    plugins = _plugins_dir(tmp_path, bundled=bundled)
    if cfgbox is None:
        cfgbox = _cfg_box(index_url)
    box, getter, saver = cfgbox
    return pet_plugin_index.PluginIndex(plugins, fetch=fetch, index_url=index_url,
                                        host_version=HOST, cfg_getter=getter,
                                        save_cfg=saver, **kw), box


# ================= A1：set_remote_base 的契约 =================

def test_set_remote_base_成功才提交_写失败内存不变(tmp_path):
    """写盘失败 → (False, 含原因)：**内存里的地址与 self._index_url 都不许动**。

    变异：把 set_remote_base 里 `cfg.update(new)` 提前到 save 之前（改回"先改内存再写盘"）
    → 第一条断言红（cfg 已经变成新地址）。
    """
    ix, box = _ix(tmp_path, fetch=_Fetcher(), index_url="")
    box["err"] = "磁盘只读（注入）"
    ok, msg = ix.set_remote_base(BASE)
    assert ok is False and "磁盘只读（注入）" in msg, (ok, msg)
    assert "没有生效" in msg, msg
    assert box["cfg"][pet_config.PLUGIN_INDEX_URL_KEY] == "", "写失败却改了内存里的地址"
    assert ix.index_url == "", "写失败却改了生效中的索引地址"
    assert box["saved"] and box["saved"][-1][pet_config.PLUGIN_INDEX_URL_KEY] == BASE, \
        "根本没往盘上写（那这条失败就不是写失败）"

    box["err"] = None
    ok2, msg2 = ix.set_remote_base(BASE)
    assert ok2 is True and BASE in msg2, (ok2, msg2)
    assert box["cfg"][pet_config.PLUGIN_INDEX_URL_KEY] == BASE and ix.index_url == BASE
    assert ix.source_info()["kind"] == "remote"


def test_set_remote_base_空串清除远端并丢掉它的缓存(tmp_path):
    """空串 = 回到随包索引：生效地址清空 + 远端缓存删掉（免得换个地址后串味）。

    变异：删掉 set_remote_base 清除分支里的 `self._drop_cache()` → 第三条断言红。
    """
    ix, _box = _ix(tmp_path, fetch=_Fetcher({TARGET: _index_bytes([_entry("a", [])])}),
                   index_url=BASE)
    ok, _msg, _n = ix.refresh()
    assert ok is True and os.path.isfile(ix.remote_cache_path), "前提不成立：刷新没落地缓存"

    ok2, msg2 = ix.set_remote_base("")
    assert ok2 is True and "随包索引" in msg2, (ok2, msg2)
    assert ix.index_url == ""
    assert not os.path.isfile(ix.remote_cache_path), "回随包索引了，远端缓存还留在盘上"
    assert ix.source_info()["kind"] == "bundled"


def test_set_remote_base_非https与本地路径一律拒_且不落盘(tmp_path):
    """只收 https：明文 http / file:// / 盘符 / 绝对路径 / UNC / 无主机 / 超长 → 当场拒。

    变异：去掉 set_remote_base 里的 `remote_base_reason` 校验（或让它恒返回空串）
    → 每条断言都红（地址会被存进去、后面真去取数）。
    """
    ix, box = _ix(tmp_path, fetch=_Fetcher(), index_url="")
    for raw in ("http://host.invalid/index.json", "file:///C:/packs/index.json",
                "C:/packs/index.json", "/etc/passwd", "\\\\host\\share\\index.json",
                "https:///index.json", "https://h/" + "a" * 3000, "ftp://h/index.json"):
        ok, msg = ix.set_remote_base(raw)
        assert ok is False and msg.strip(), (raw, ok, msg)
        assert "https" in msg or "太长" in msg or "主机" in msg, (raw, msg)
        # M2：file:// 与盘符这两个样本必须**点名"本地路径"**（不是"只收 https"那句兜底）——
        # remote_base_reason 里那条「本地路径 / file:// 不行」的判据存在的唯一意义就是把理由说
        # 具体（后面「只收 https 前缀」那句只是兜底）。这里**按内容指名、不写行号**：那条判据
        # 已被 v2.8.0 找茬 F2 插进去的 _safe_urlsplit 往下推过一次（130-133 → 144-147）。
        # 变异：把那条判据整段删掉 → 这两个样本各红一次。
        if raw in ("file:///C:/packs/index.json", "C:/packs/index.json"):
            assert "本地路径" in msg, (raw, msg)
    assert box["saved"] == [], "被拒的地址仍然写了盘：%r" % (box["saved"],)
    assert box["cfg"][pet_config.PLUGIN_INDEX_URL_KEY] == "" and ix.index_url == ""


def test_set_remote_base_没接线时如实报错不假装存下(tmp_path):
    """没注入 cfg_getter / save_cfg → (False, 人话原因)，绝不"存了个寂寞"。

    变异：把"没接线"那条分支的 return 改成直接改 self._index_url → 第一条断言红。
    """
    plugins = _plugins_dir(tmp_path)
    ix = pet_plugin_index.PluginIndex(plugins, fetch=_Fetcher(), host_version=HOST)
    ok, msg = ix.set_remote_base(BASE)
    assert ok is False and "接线" in msg, (ok, msg)
    assert ix.index_url == "", "没接线却改了生效中的地址"


def test_配置键名两处一致_单一来源(tmp_path):
    """键名只有一份字面量（pet_plugin_index），pet_config 是**再导出**——漂了两边就分开。

    变异：把 pet_config.PLUGIN_INDEX_URL_KEY 改成另一个字面量 → 第一条断言红。
    """
    assert pet_config.PLUGIN_INDEX_URL_KEY == pet_plugin_index.PLUGIN_INDEX_URL_KEY
    assert pet_plugin_index.PLUGIN_INDEX_URL_KEY == "plugin_index_url"
    assert pet_config.PLUGIN_INDEX_URL_DEFAULT == ""
    assert pet_config.normalize_plugin_index_url(None) == ""
    assert pet_config.normalize_plugin_index_url("  ") == ""
    assert pet_config.normalize_plugin_index_url(" " + BASE + " ") == BASE
    ok, why = pet_config.validate_plugin_index_url("http://h/x.json")
    assert ok is False and "https" in why, (ok, why)
    ok2, why2 = pet_config.validate_plugin_index_url(BASE)
    assert ok2 is True and why2 == "", (ok2, why2)
    assert pet_config.validate_plugin_index_url("")[0] is True, "空串 = 回随包，必须算合法"


def test_getter_走单一来源_不是自己抄一份():
    """宿主那边的取地址 getter 也必须走 pet_config 的单源（键名 + 归一），不许自己抄一份。

    PetWindow.plugin_index_url 曾经是裸字面量 cfg.get("plugin_index_url") + 自己归一（`or ""`，
    不 strip）：键名绕开了键名单源，归一又与加载器的 normalize_cfg 差一截。本文件与
    test_dialogs_feedback_v280 的替身 `_Pet` 当初把那段逻辑**逐字镜像**了一份，于是"把缺陷
    原样改回来"也能全绿（v2.8.0 质量审查 Minor · M5）——这条用例改走**真对象**：只借属性，
    不跑 __init__（不起 Qt 窗口、不读盘）。

    变异：① getter 里写死另一个键名（"plugin_index_url_typo"）→ 第一条断言红（取到 ""）；
          ② getter 回到旧实现 str(cfg.get("plugin_index_url") or "")（自己归一、不 strip）
             → 同样红（取到 "  <BASE>  "，正是"自己归一"漏掉的那两个空格）。
    """
    import 桌宠 as main            # 只这条用例要真宿主（与 E 段"真加载器"那条同款套路）
    win = main.PetWindow.__new__(main.PetWindow)      # 不跑 __init__：只要属性，不起窗口
    win.cfg = {pet_config.PLUGIN_INDEX_URL_KEY: "  " + BASE + "  "}
    assert win.plugin_index_url == BASE, win.plugin_index_url
    win.cfg = {pet_config.PLUGIN_INDEX_URL_KEY: None}
    assert win.plugin_index_url == pet_config.PLUGIN_INDEX_URL_DEFAULT == ""


# ================= A2：refresh 的契约 =================

def test_refresh_取回校验落地并返回条目数(tmp_path):
    """正常取回 → (True, 含"N 个插件"的话术, N)；缓存落地且 load_index 直接用它（不再联网）。

    变异：删掉 refresh 里的 `self._write_cache(target, raw)` → 第二条断言红（没有缓存文件）；
    把 count 改成恒 0 → 第一条断言红。
    """
    pack = _pack_bytes([{"text": "甲的台词"}])
    remotes = _index_bytes([_entry("phase3-a", [_release(pack)]),
                            _entry("phase3-b", [], data_kind="role")])
    fetcher = _Fetcher({TARGET: remotes})
    ix, _box = _ix(tmp_path, fetch=fetcher, index_url=BASE, bundled=_index_bytes([_entry("x", [])]))

    ok, msg, count = ix.refresh()
    assert ok is True and "共 2 个插件" in msg, (ok, msg)
    assert count == 2, "count 口径 = 索引里列出的条目数：%r" % (count,)
    assert fetcher.calls == [TARGET], "该取的就是拼出来的 index.json 地址：%r" % (fetcher.calls,)
    path = ix.remote_cache_path
    assert os.path.isfile(path), "刷新成功却没落地缓存"
    cached = json.loads(io.open(path, encoding="utf-8-sig").read())
    assert cached["source_url"] == TARGET and cached["fetched_at"], cached
    assert cached["index"]["plugins"][0]["id"] == "phase3-a", cached

    before = list(fetcher.calls)
    index, err = ix.load_index()
    assert err == "" and [e["id"] for e in index["entries"]] == ["phase3-a", "phase3-b"], err
    assert "本地缓存" in index["source"], index["source"]
    assert fetcher.calls == before, "缓存命中却又联网取了一次：%r" % (fetcher.calls,)


def test_refresh_force语义_命中缓存不联网_force强制重取(tmp_path):
    """force=False 有缓存 → 直接用（不联网）；force=True → 无条件重取。

    变异：把 refresh 里 `if not force:` 那段缓存短路删掉 → 第二条断言红（calls 又变多）。
    """
    fetcher = _Fetcher({TARGET: _index_bytes([_entry("a", [])])})
    ix, _box = _ix(tmp_path, fetch=fetcher, index_url=BASE)
    assert ix.refresh()[0] is True and len(fetcher.calls) == 1

    ok, msg, count = ix.refresh()
    assert ok is True and count == 1, (ok, msg, count)
    assert len(fetcher.calls) == 1, "有缓存却联网了：%r" % (fetcher.calls,)
    assert "缓存" in msg, msg

    assert ix.refresh(force=True)[0] is True
    assert len(fetcher.calls) == 2, "force=True 必须真的重取：%r" % (fetcher.calls,)


def test_refresh_没有远端地址时如实拒绝(tmp_path):
    """随包模式点刷新 → (False, 说清"没有可刷新的远端", 0)，一次都不联网。

    变异：把开头那条 `if not base` 判断删掉 → 会拿着空地址去取数（本用例红）。
    """
    fetcher = _Fetcher()
    ix, _box = _ix(tmp_path, fetch=fetcher, index_url="")
    ok, msg, count = ix.refresh()
    assert ok is False and "随包索引" in msg and count == 0, (ok, msg, count)
    assert fetcher.calls == [], fetcher.calls


def test_refresh_失败不留假象_旧缓存与随包索引都不动(tmp_path):
    """404 / 超时 → (False, 人话原因, 0)；**已有的缓存与随包索引一个字节都不动**。

    变异：把 refresh 的失败分支改成先删缓存（或改成 (True, ...)）→ 断言红。
    """
    good = _index_bytes([_entry("a", [])], updated_at="2026-02-02")
    fetcher = _Fetcher({TARGET: good})
    ix, _box = _ix(tmp_path, fetch=fetcher, index_url=BASE,
                   bundled=_index_bytes([_entry("bundled-1", [])], updated_at="2026-01-01"))
    assert ix.refresh()[0] is True
    stamp = io.open(ix.remote_cache_path, "rb").read()

    fetcher.table.clear()
    fetcher.err = "网络请求失败：HTTP Error 404: Not Found"
    ok, msg, count = ix.refresh(force=True)
    assert ok is False and "404" in msg and count == 0, (ok, msg, count)
    assert io.open(ix.remote_cache_path, "rb").read() == stamp, "刷新失败却动了旧缓存"

    index, err = ix.load_index()
    assert err == "" and [e["id"] for e in index["entries"]] == ["a"], err


# ================= B：网络边界 =================

def test_load_index_生产口径绝不联网_没缓存退回随包索引(tmp_path):
    """没注入 fetch（= 生产）时 load_index **不联网**：退回随包索引并如实标注来源。

    变异：删掉 load_index 里 `if self._fetch is None:` 那条退路（回到"直接去取远端"）
    → 本用例红（远端取数会撞上"测试不许联网"的守卫）。
    """
    ix = pet_plugin_index.PluginIndex(
        _plugins_dir(tmp_path, bundled=_index_bytes([_entry("bundled-1", [])])),
        index_url=BASE, host_version=HOST)
    index, err = ix.load_index()
    assert err == "" and index is not None, err
    assert [e["id"] for e in index["entries"]] == ["bundled-1"]
    assert "随包索引" in index["source"] and "刷新" in index["source"], index["source"]


def test_load_index_生产口径缓存命中就能用远端清单(tmp_path):
    """刷新落地之后：同一个地址的新实例（没注入 fetch）也能读到远端清单——依然不联网。

    变异：把 load_index 里的 `self._read_cache(...)` 短路删掉 → 本用例红。
    """
    fetcher = _Fetcher({TARGET: _index_bytes([_entry("remote-a", [])])})
    ix, _box = _ix(tmp_path, fetch=fetcher, index_url=BASE)
    assert ix.refresh()[0] is True
    plugins = ix.plugins_dir

    plain = pet_plugin_index.PluginIndex(plugins, index_url=BASE, host_version=HOST)
    index, err = plain.load_index()
    assert err == "" and [e["id"] for e in index["entries"]] == ["remote-a"], err
    assert "本地缓存" in index["source"], index["source"]


def test_load_index_随包也读不出来时把两条原因都说清(tmp_path):
    """远端没缓存、随包索引也不在 → 错误里既有"还没取回来"也有随包那条原因。

    变异：把 load_index 里那条组合错误改成只报一半 → 断言里那句就找不到。
    """
    d = tmp_path / "plugins"
    d.mkdir(parents=True)          # 故意不写随包 index.json
    ix = pet_plugin_index.PluginIndex(str(d), index_url=BASE, host_version=HOST)
    index, err = ix.load_index()
    assert index is None and "还没取回来" in err, err
    # 改前这里只断言 "索引" —— 把随包那一半的原因丢掉也照样绿（代理 C 实测的**假覆盖**）。
    # 现在钉住随包取数那条人话原因（现文案来自 default_fetch 的本地分支）。
    assert "读取本地文件失败" in err, "随包那一半的原因被吞了：%r" % (err,)
    assert "index.json" in err, "随包那份的路径没出现在原因里：%r" % (err,)


def test_换站点后旧站点的缓存不许冒充新站点(tmp_path):
    """缓存自带 source_url：换过远端地址之后，A 站的清单不能当成 B 站的显示/刷新结果。

    变异：把 _read_cache 里那条 source_url 比对删掉（恒 True）→ 本用例两条断言都红
    （B 站显示的是 A 站条目、refresh 也不去真取）。
    """
    target_a = BASE + "/index.json"
    ix, _box = _ix(tmp_path, fetch=_Fetcher({target_a: _index_bytes([_entry("site-a", [])])}),
                   index_url=BASE)
    assert ix.refresh()[0] is True, "前提不成立：A 站没落地缓存"
    plugins = ix.plugins_dir

    base_b = "https://other.invalid/dir"
    target_b = base_b + "/index.json"
    plain = pet_plugin_index.PluginIndex(plugins, index_url=base_b, host_version=HOST)
    index, err = plain.load_index()
    ids = [e["id"] for e in index["entries"]] if index is not None else []
    assert ids == [], "B 站读到了 A 站的缓存（换站点串味）：%r（%s）" % (ids, err)

    box_b, getter_b, saver_b = _cfg_box(base_b)
    fetcher_b = _Fetcher({target_b: _index_bytes([_entry("site-b", [])])})
    ix_b = pet_plugin_index.PluginIndex(plugins, fetch=fetcher_b, index_url=base_b,
                                        host_version=HOST, cfg_getter=getter_b,
                                        save_cfg=saver_b)
    ok, msg, count = ix_b.refresh()          # force=False：A 站的缓存对不上 → 必须真去 B 站取
    assert ok is True and count == 1, (ok, msg, count)
    assert fetcher_b.calls == [target_b], "拿 A 站的缓存当了 B 站的结果：%r" % (fetcher_b.calls,)
    index2, err2 = ix_b.load_index()
    assert [e["id"] for e in index2["entries"]] == ["site-b"], err2


def test_直接填index_json地址也收_不重复拼路径(tmp_path):
    """填 `https://h/dir/index.json` 与填 `https://h/dir` 都要能跑通（.json 直通，不再拼一层）。

    变异：让 index_url_of 去掉 .json 直通分支、无条件拼 INDEX_NAME → 取数地址会变成
    .../index.json/index.json，本用例红（假取数里没有这个地址）。
    """
    fetcher = _Fetcher({TARGET: _index_bytes([_entry("direct", [])])})
    ix, _box = _ix(tmp_path, fetch=fetcher, index_url="")
    ok, msg = ix.set_remote_base(TARGET)          # 直接填 .json 地址
    assert ok is True, (ok, msg)
    info = ix.source_info()
    assert info["url"] == TARGET and info["index_url"] == TARGET, info

    ok2, msg2, count = ix.refresh()
    assert ok2 is True and count == 1, (ok2, msg2, count)
    assert fetcher.calls == [TARGET], "取数地址被多拼了一层：%r" % (fetcher.calls,)


def test_来源信息_随包与远端两种口径(tmp_path):
    """source_info：bundled/remote 的 kind、url、updated_at（+ 缓存命中时 fetched_at 非空）。

    变异：把 kind 写死成 "bundled"（或 url 恒空）→ 第二条断言红。
    """
    bundled = _index_bytes([_entry("b1", []), _entry("b2", [])], updated_at="2026-01-01")
    ix, _box = _ix(tmp_path, fetch=_Fetcher({TARGET: _index_bytes([_entry("r1", [])])}),
                   index_url=BASE, bundled=bundled)

    info = ix.source_info()
    assert info["kind"] == "remote" and info["url"] == BASE, info
    assert info["updated_at"] == "", "还没刷新过，不该有远端索引的更新时间：%r" % (info,)
    assert info["index_url"] == TARGET and info["cached"] is False, info

    assert ix.refresh(force=True)[0] is True
    info2 = ix.source_info()
    assert info2["updated_at"] == "2026-02-02" and info2["fetched_at"], info2
    assert info2["count"] == 1 and info2["cached"] is True, info2

    assert ix.set_remote_base("")[0] is True
    info3 = ix.source_info()
    assert info3["kind"] == "bundled" and info3["url"] == "" and info3["updated_at"] == "2026-01-01"
    assert info3["count"] == 2, info3


# ================= C：v2.6.0 硬化保留（走新链路） =================

def test_远端索引体积上限_前置传下去且事后仍判(tmp_path):
    """索引取数的上限**前置**（limit 传进取数实现）且取回来还要再判一次。

    变异：① 把 refresh 里 `self._fetch_bytes(target, self._progress, INDEX_MAX_BYTES)` 的
    上限参数去掉 → seen 记录不到上限，红；② 删掉事后那条 len(data) 判断 → 超限索引照收，红。
    """
    seen = {}

    def fetch_with_limit(url, limit=0):
        seen[url] = limit
        return _index_bytes([_entry("a", [])]), ""

    ix, _box = _ix(tmp_path, fetch_with_limit, index_url=BASE)
    assert ix.refresh()[0] is True
    assert seen[TARGET] == pet_plugin_index.INDEX_MAX_BYTES, seen

    big = b"{" + b" " * (pet_plugin_index.INDEX_MAX_BYTES + 1) + b"}"
    fresh = tmp_path / "fresh"                  # 干净目录：免得读到上一步那份合法缓存
    (fresh / "plugins").mkdir(parents=True)
    ix2 = pet_plugin_index.PluginIndex(str(fresh / "plugins"), fetch=lambda url: (big, ""),
                                       index_url=BASE, host_version=HOST)
    ok, msg, count = ix2.refresh()
    assert ok is False and "过大" in msg and count == 0, (ok, msg, count)
    assert not os.path.isfile(ix2.remote_cache_path), "超限的索引不该落地"


def test_远端包sha256与bytes不符一律拒收且不留残余(tmp_path):
    """Phase 3 全程（refresh → 缓存 → load_index → download）里 v2.6.0 的三层核对仍在。

    变异：删掉 download 里 sha256 或 bytes 那条判断 → 对应断言红（坏包会被写进 _download/）。
    """
    pack = _pack_bytes([{"text": "远端甲"}])
    bad_sha = bytes(pack[:-1] + bytes([pack[-1] ^ 0xFF]))
    url = "https://cdn.invalid/a.zip"
    remotes = _index_bytes([
        _entry("phase3-sha", [_release(pack, url=url, sha="0" * 64)]),
        _entry("phase3-bytes", [_release(pack, url=url, size=len(pack) + 7)]),
    ])
    table = {TARGET: remotes, url: pack}
    ix, _box = _ix(tmp_path, fetch=_Fetcher(table), index_url=BASE)
    assert ix.refresh()[0] is True
    index, err = ix.load_index()
    assert err == "" and len(index["entries"]) == 2, err

    for entry in index["entries"]:
        path, derr = ix.download(entry)
        assert path is None and derr, (entry["id"], derr)
        assert "不符" in derr, (entry["id"], derr)
    left = os.listdir(ix.download_dir) if os.path.isdir(ix.download_dir) else []
    assert left == [], "拒收的下载留了残余：%r" % (left,)
    assert bad_sha != pack, "用例前提：坏哈希样本与真包不同"


def test_远端索引指向本地路径_条目标不可装(tmp_path):
    """远端索引里的条目不许指向本机（跨信任域）——标不可装并给人话原因，索引本身照收。

    变异：去掉 resolve_url 的 base_remote 分支 → 条目标成可安装，红。
    """
    remotes = _index_bytes([_entry("phase3-local", [
        _release(b"x", url="file:///C:/Windows/win.ini")])])
    ix, _box = _ix(tmp_path, fetch=_Fetcher({TARGET: remotes}), index_url=BASE)
    assert ix.refresh()[0] is True
    index, err = ix.load_index()
    entry = index["entries"][0]
    assert entry["installable"] is False and "跨信任域" in entry["reason"], entry


def test_非https的远端地址_刷新前就拒且不取数(tmp_path):
    """明文 http 的基址：refresh 直接拒（含 https 原因），一个字节都不取。

    变异：把 refresh 里的 `insecure_reason` 判断删掉 → 会去取数（假取数里没有这个地址，红）。
    """
    fetcher = _Fetcher({"http://host.invalid/index.json": _index_bytes([_entry("a", [])])})
    ix, _box = _ix(tmp_path, fetch=fetcher, index_url="http://host.invalid/index.json")
    ok, msg, count = ix.refresh()
    assert ok is False and "https" in msg and count == 0, (ok, msg, count)
    assert fetcher.calls == [], fetcher.calls


def test_索引格式不认识_整份拒且不落地(tmp_path):
    """index_version 太新 / 不是对象 → 整份拒（fail-closed），缓存不落地。

    变异：把 refresh 里 parse_index 失败那条判断删掉（照写缓存）→ 第二条断言红。
    """
    for raw in (_index_bytes([_entry("a", [])], index_version=99), b'["not a dict"]'):
        ix, _box = _ix(tmp_path, fetch=lambda url, _r=raw: (_r, ""), index_url=BASE)
        ok, msg, count = ix.refresh()
        assert ok is False and count == 0, (ok, msg, count)
        assert not os.path.isfile(ix.remote_cache_path), "坏索引落地了：%s" % (msg,)


def test_刷新失败后回退路径仍在_能装随包索引里的东西(tmp_path):
    """刷新失败之后：① 随包索引照常列出来 ② 切回随包（空串）之后照常下载安装。

    变异：让 set_remote_base("") 失败（或去掉 load_index 的退路）→ 对应断言红。
    """
    pack = _pack_bytes([{"text": "随包甲"}])
    plugins = tmp_path / "plugins"
    (plugins / "packs").mkdir(parents=True)
    (plugins / "packs" / "b.zip").write_bytes(pack)
    bundled = _index_bytes([_entry("bundled-lines", [_release(pack, url="packs/b.zip")])])
    (plugins / "index.json").write_bytes(bundled)

    ix, _box = _ix(tmp_path, fetch=_Fetcher(err="网络请求失败：假网络挂了"), index_url=BASE)
    ok, msg, _n = ix.refresh()
    assert ok is False and "假网络挂了" in msg, (ok, msg)

    # 生产口径的索引对象（没注入 fetch）：刷新失败过、也没有缓存，照样能列出随包那份
    plain = pet_plugin_index.PluginIndex(ix.plugins_dir, index_url=BASE, host_version=HOST,
                                         cfg_getter=_box[0] if False else None)
    index, err = plain.load_index()
    assert err == "" and "随包索引" in index["source"], (err, index and index["source"])
    assert [e["id"] for e in index["entries"]] == ["bundled-lines"], err

    cfgbox = _cfg_box(BASE)
    ix2 = pet_plugin_index.PluginIndex(ix.plugins_dir, index_url=BASE, host_version=HOST,
                                       cfg_getter=cfgbox[1], save_cfg=cfgbox[2])
    assert ix2.set_remote_base("")[0] is True
    index2, err2 = ix2.load_index()
    assert err2 == "" and index2["source"] == "随包索引", index2["source"]
    entry = index2["entries"][0]
    assert entry["installable"] is True, entry["reason"]
    path, derr = ix2.download(entry)
    assert derr == "" and path and os.path.isfile(path), derr
    ix2.cleanup()


# ================= E：plugin_index_url 配置键（B2） =================

_DFLT = {"scale": 1.0, "ai_reply_len": 25,
         "bubble_style": {"bg": "#ffffff", "fg": "#203170", "border": "#203170",
                          "font_size": 10, "radius": 16}}


def test_配置键默认值不进diff落盘_逐字节回归(tmp_path):
    """默认值（空）的键**不写进 config.json**：带键与不带键写出来的字节完全相同。

    这就是"默认值不改变任何既有行为"的物证：老配置（没有这个键）与本版配置（键=默认值）
    在盘上逐字节一致，读回来的归一结果也一致。
    变异：把 DEFAULT_CONFIG 里的默认值改成非空（或 normalize 随手改成 " / " 之类）
    → 两份字节不再相同，红。
    """
    cfg = {"scale": 1.5, "ai_reply_len": 25, "api_key": ""}
    p_old, p_new = tmp_path / "old.json", tmp_path / "new.json"
    logs = []
    assert pet_config.write_config(str(p_old), dict(cfg), dict(_DFLT), 2,
                                   logs.append, lambda s: "") is None
    cfg_new = dict(cfg)
    cfg_new[pet_config.PLUGIN_INDEX_URL_KEY] = ""
    dflt_new = dict(_DFLT)
    dflt_new[pet_config.PLUGIN_INDEX_URL_KEY] = pet_config.PLUGIN_INDEX_URL_DEFAULT
    assert pet_config.write_config(str(p_new), cfg_new, dflt_new, 2,
                                   logs.append, lambda s: "") is None

    assert p_old.read_bytes() == p_new.read_bytes(), "默认值的键被写进了 config.json"
    assert pet_config.PLUGIN_INDEX_URL_KEY not in json.loads(
        p_new.read_text(encoding="utf-8")), "默认值的键不该出现在盘上"
    assert logs == [], "这条正常路径不该有失败日志：%r" % (logs,)


def test_配置键真的存得住_读得回来(tmp_path):
    """契约的另一半：填了 https 地址就真的落盘（写失败要能返回错误串）。

    变异：把 write_config 的 `if k in defaults` 判据换成恒 True 的另一套（或让键写不出去）
    → 第一条断言红。
    """
    cfg = {"scale": 1.5, "api_key": ""}
    cfg[pet_config.PLUGIN_INDEX_URL_KEY] = BASE
    dflt = dict(_DFLT)
    dflt[pet_config.PLUGIN_INDEX_URL_KEY] = ""
    path = tmp_path / "cfg.json"
    logs = []
    assert pet_config.write_config(str(path), cfg, dflt, 2, logs.append, lambda s: "") is None
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data[pet_config.PLUGIN_INDEX_URL_KEY] == BASE, data

    # 归一回：值两侧空白被吃掉；坏类型（null / 数字）回默认空串
    box = {pet_config.PLUGIN_INDEX_URL_KEY: "  " + BASE + "  "}
    pet_config.normalize_cfg(box, dflt, frozenset())
    assert box[pet_config.PLUGIN_INDEX_URL_KEY] == BASE, box
    for bad in (None, "   "):
        box2 = {pet_config.PLUGIN_INDEX_URL_KEY: bad}
        pet_config.normalize_cfg(box2, dflt, frozenset())
        assert box2[pet_config.PLUGIN_INDEX_URL_KEY] == "", (bad, box2)
    # 非字符串（手改 config.json 写成数字）：按全仓 string 键同款折成字符串，
    # **合法性不在这里判**——下面这条说明它逃不过真正的判据（取数/校验那条路）。
    box_num = {pet_config.PLUGIN_INDEX_URL_KEY: 123}
    pet_config.normalize_cfg(box_num, dflt, frozenset())
    assert box_num[pet_config.PLUGIN_INDEX_URL_KEY] == "123", box_num
    assert pet_config.validate_plugin_index_url("123")[0] is False, "坏地址没被校验拦下"
    box3 = {"scale": 1.0}          # 键根本不在 cfg 里 → 不凭空增添量未知键
    pet_config.normalize_cfg(box3, dflt, frozenset())
    assert pet_config.PLUGIN_INDEX_URL_KEY not in box3, box3


def test_真加载器_老config读入写出不冒出这个键(tmp_path, monkeypatch):
    """走**真** load_config / save_config：老 config.json 存一次不会多出 plugin_index_url。

    变异：从 DEFAULT_CONFIG 里删掉 plugin_index_url（或让 normalize 凭空补上它）
    → 键会冒出来 / 第二次保存的字节会变，红。
    """
    import 桌宠 as main                     # 只这条用例要真加载器（避免整文件背上 Qt）
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(main, "CONFIG_PATH", str(cfg_path))
    monkeypatch.setattr(main, "DATA_DIR", str(tmp_path))
    old = {"schema_version": 2, "scale": 1.5, "api_key": "", "city": "上海"}
    cfg_path.write_text(json.dumps(old, ensure_ascii=False, indent=2), encoding="utf-8")

    cfg = main.load_config()
    assert cfg.get(pet_config.PLUGIN_INDEX_URL_KEY) == "", "加载器没把这个键归一出来"
    assert main.save_config(cfg) is None
    first = cfg_path.read_bytes()
    data = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    assert pet_config.PLUGIN_INDEX_URL_KEY not in data, \
        "老配置存一次就冒出了这个键（默认值不该落盘）：%r" % (data,)

    assert main.save_config(main.load_config()) is None
    assert cfg_path.read_bytes() == first, "第二次保存的字节与第一次不同（不是稳定的 diff 落盘）"

    # 控制组：真的填了远端地址 → 这个键才会出现在盘上
    cfg2 = main.load_config()
    cfg2[pet_config.PLUGIN_INDEX_URL_KEY] = BASE
    assert main.save_config(cfg2) is None
    assert json.loads(cfg_path.read_text(encoding="utf-8-sig"))[
        pet_config.PLUGIN_INDEX_URL_KEY] == BASE

# ================= F：地址判据的漏网（找茬审查 F2） =================

# 6 个"没有主机名"的同形地址：netloc 非空（":8443" / "user@" / "@" …）、hostname 全是 None。
_NO_HOST = ("https://:8443/x.json", "https://user@/x.json", "https://user:pass@/x.json",
            "https://:/x.json", "https://@/x.json", "https://:8443")
# 5 个合法形态（有主机名）：这条判据一个都不许拦（防"修过头"）。
_LEGAL = ("https://example.invalid/index.json", "https://example.invalid/dir",
          "https://example.invalid:8443/packs/index.json",
          "https://user:pass@example.invalid/x.json", "https://example.invalid/dir/")


def test_无主机名地址两层都当场拒(tmp_path):
    """F2：`https://:8443/x.json` 这 6 形会被**真值判据**放过并写进配置——两层都要拒。

    · 界面那层 = `pet_config.validate_plugin_index_url`（A 的对话框点保存时当场调的就是它）；
    · 后端那层 = `PluginIndex.set_remote_base`（真写盘那道，失败必须**一个字节都不写**）。
    变异：把 remote_base_reason 里的 `parts.hostname` 改回 `urlsplit(text).netloc` → 本用例红。
    """
    for raw in _NO_HOST:
        ok, why = pet_config.validate_plugin_index_url(raw)
        assert ok is False and "主机名" in why, (raw, ok, why)
    ix, box = _ix(tmp_path, fetch=_Fetcher(), index_url="")
    for raw in _NO_HOST:
        ok2, msg2 = ix.set_remote_base(raw)
        assert ok2 is False and msg2.strip(), (raw, ok2, msg2)
    assert box["saved"] == [], "无主机名的地址竟然写了盘：%r" % (box["saved"],)
    assert box["cfg"][pet_config.PLUGIN_INDEX_URL_KEY] == "" and ix.index_url == "", \
        "无主机名的地址竟然改成了生效地址"


def test_合法地址五种形态仍然放行(tmp_path):
    """反向控制组（别修过头）：有主机名的 5 个合法形态，两层都要放行。

    变异：把 hostname 判据写成"必须 .json 结尾"之类的过窄判据 → 本用例红。
    """
    for raw in _LEGAL:
        ok, why = pet_config.validate_plugin_index_url(raw)
        assert ok is True and why == "", (raw, ok, why)
    ix, box = _ix(tmp_path, fetch=_Fetcher(), index_url="")
    for raw in _LEGAL:
        ok2, msg2 = ix.set_remote_base(raw)
        assert ok2 is True, (raw, msg2)
        assert box["cfg"][pet_config.PLUGIN_INDEX_URL_KEY] == raw, box["cfg"]
    assert len(box["saved"]) == len(_LEGAL), "合法地址没有真的逐个落盘：%r" % (len(box["saved"]),)


def test_解析不了的地址只拒不抛(tmp_path):
    """坏到 urlsplit 都解析不了的地址（`https://[abc/x.json`）→ 两层都给"拒绝 + 原因"，
    **绝不抛异常**（校验函数是界面当场调的，抛出去就是"点了没反应"）。

    变异：把 remote_base_reason 里 `parts = _safe_urlsplit(text)` 换回 `urllib.parse.urlsplit(text)`
    → 本用例在调用处抛 ValueError，红。
    """
    raw = "https://[abc/x.json"
    ok, why = pet_config.validate_plugin_index_url(raw)
    assert ok is False and why.strip(), (ok, why)
    ix, box = _ix(tmp_path, fetch=_Fetcher(), index_url="")
    ok2, msg2 = ix.set_remote_base(raw)
    assert ok2 is False and msg2.strip(), (ok2, msg2)
    assert box["saved"] == [] and ix.index_url == ""
