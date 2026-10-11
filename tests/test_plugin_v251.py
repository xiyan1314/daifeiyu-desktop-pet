# -*- coding: utf-8 -*-
"""v2.5.1 代理A：Phase 0 插件包校验器（pet_plugin.py）的验收用例。

14 条主验收（每条都能真失败）：
  合法数据包通过 · 缺 plugin 段拒 · kind=data 却 code=true 拒 · payload 里有 evil.py 点名拒绝 ·
  条目名含 ".." 拒 · min_host_version=99.0.0 拒且 err 含 99.0.0 与当前版本 · api_version=2 拒 ·
  sha256 改一位拒并点名文件 · 某 payload 文件不在 files 里拒 · kind=ui 拒 ·
  plugins 目录不存在返回空不抛 · 目录里放普通文件跳过不抛 · plugins/x/ 无 manifest 跳过不抛 ·
  回归：validate_bundle 行为逐位不变

另加若干"能真失败"的加固用例（BOM / 上限 / 外部属性 / 禁止项清单 / capabilities / data_kind /
单根 / 顶层重复键忽略 / read_installed 容错 / id 安全 / 版本口径与发布门对齐 / 文档与校验器
清单一致）。

约定：zip 条目名一律写全（"payload/a.txt"）；_pack 的 payload 参数是 **payload 内相对名**。
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
sys.path.insert(0, ROOT)

import pet_export      # noqa: E402
import pet_plugin      # noqa: E402

HOST = "2.5.0"


# ---------------- 造包工具 ----------------

def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _meta(**over):
    """合法的 plugin 段；over 用来逐条破坏。"""
    m = {"id": "official-lines-basic", "name": "示例台词包", "version": "1.0.0",
         "author": "官方", "description": "示例", "kind": "data", "data_kind": "lines",
         "code": False, "min_host_version": HOST, "api_version": 1, "capabilities": []}
    m.update(over)
    return m


def _files_for(entries):
    return [{"path": n, "sha256": _sha(d), "bytes": len(d)} for n, d in sorted(entries.items())]


def _manifest(entries, meta=None, top=None, payload_root="payload/"):
    """entries 的键是**完整 zip 条目名**。"""
    m = {"format": "dfypet-plugin", "version": 1, "payload_root": payload_root,
         "created_at": "2026-10-11T00:00:00", "files": _files_for(entries),
         "plugin": _meta() if meta is None else meta}
    if top:
        m.update(top)
    return m


def _write_zip(path, entries, manifest, *, omit_manifest=False, manifest_bytes=None):
    """entries: {完整条目名: bytes}；manifest 为 dict（或 manifest_bytes 直接给原始字节）。"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        if not omit_manifest:
            if manifest_bytes is not None:
                z.writestr(pet_plugin.MANIFEST_NAME, manifest_bytes)
            else:
                z.writestr(pet_plugin.MANIFEST_NAME,
                           json.dumps(manifest, ensure_ascii=False).encode("utf-8"))
        for n, data in entries.items():
            z.writestr(n, data)
    return str(path)


def _pack(tmp_path, payload=None, meta=None, top=None, name="p.dfypet-plugin",
          payload_root="payload/", manifest=None, entries=None):
    """一个"合法数据包"（可逐条改坏）。payload 的键是 payload 内相对名，会被加上根前缀。"""
    payload = {"a.txt": b"hello"} if payload is None else payload
    entries = {payload_root + k: v for k, v in payload.items()} if entries is None else entries
    if manifest is None:
        manifest = _manifest(entries, meta=meta, top=top, payload_root=payload_root)
    return _write_zip(str(tmp_path / name), entries, manifest)


def _err(path):
    """校验并返回 err（断言必须拒绝时用）。"""
    manifest, err = pet_plugin.validate_plugin_zip(path, HOST)
    assert manifest is None, "本该拒绝却通过了：%r" % (manifest,)
    assert err, "拒绝了但没有原因"
    return err


def _ok(path):
    """校验并断言通过，返回 manifest。"""
    manifest, err = pet_plugin.validate_plugin_zip(path, HOST)
    assert err == "", "本该通过却被拒：%s" % err
    return manifest


# ---------------- 1. 正向 ----------------

def test_合法数据包通过(tmp_path):
    """正例：一个字段齐全的数据包必须返回 (manifest, "")。"""
    manifest = _ok(_pack(tmp_path))
    assert manifest["plugin"]["id"] == "official-lines-basic"
    assert manifest["files"][0]["path"] == "payload/a.txt"


def test_空能力表与缺省_payload_root_也通过(tmp_path):
    """C 口径：capabilities 允许 []；payload_root 缺省 payload/。"""
    assert _ok(_pack(tmp_path, meta=_meta(capabilities=[]))) is not None
    entries = {"payload/a.txt": b"hello"}
    m = _manifest(entries)
    del m["payload_root"]
    p2 = _write_zip(str(tmp_path / "noroot.dfypet-plugin"), entries, m)
    assert _ok(p2) is not None


def test_顶层与_plugin_段重复时以_plugin_段为准(tmp_path):
    """单一真源：顶层又写了一份 id/kind 一律**忽略**（不是拒绝）。"""
    entries = {"payload/a.txt": b"hello"}
    m = _manifest(entries, top={"id": "顶层冒充", "kind": "ui", "code": True,
                                "min_host_version": "99.0.0", "api_version": 9})
    p = _write_zip(str(tmp_path / "dup.dfypet-plugin"), entries, m)
    manifest = _ok(p)
    assert manifest["plugin"]["kind"] == "data"


# ---------------- 2~5. 结构判据 ----------------

def test_缺_plugin_段拒(tmp_path):
    """缺 plugin 段（元数据写在顶层）→ 拒；真角色包也不能混进来。"""
    entries = {"payload/a.txt": b"hello"}
    m = {"format": "dfypet-plugin", "version": 1, "files": _files_for(entries)}
    p = _write_zip(str(tmp_path / "noplugin.dfypet-plugin"), entries, m)
    assert "plugin 段" in _err(p)
    role = {"format": "dfypet-role", "version": 1, "role": {"id": "r1", "file": "a.png"}}
    p2 = _write_zip(str(tmp_path / "role.dfypet-plugin"), {"roles/a.png": b"x"}, role)
    assert "format" in _err(p2)


def test_kind_data_却_code_true拒(tmp_path):
    assert "code=false" in _err(_pack(tmp_path, meta=_meta(code=True)))
    # 反向：非 data 且 code=false 也拒（kind=ui 的 code 判据先于"UI 一律拒"那条，才看得到这句话）
    p2 = _pack(tmp_path, meta=_meta(kind="ui", code=False), name="k2.dfypet-plugin")
    assert "code=true" in _err(p2)
    # 未知 kind 直接拒（不是"非 data 就算代码插件"）
    p2b = _pack(tmp_path, meta=_meta(kind="other", code=False), name="k2b.dfypet-plugin")
    assert "kind" in _err(p2b)
    # code 不是 bool 也拒
    p3 = _pack(tmp_path, meta=_meta(code=0), name="k3.dfypet-plugin")
    assert "bool" in _err(p3)


def test_payload_里有_evil_py_点名拒绝(tmp_path):
    entries = {"payload/ok.txt": b"hi", "payload/evil.py": b"import os\n"}
    p = _write_zip(str(tmp_path / "evil.dfypet-plugin"), entries, _manifest(entries))
    err = _err(p)
    assert "evil.py" in err, "禁止项必须点名文件：%s" % err
    assert ".py" in err
    # 必须走"禁止项"那一条判据——只靠扩展名白名单的话，禁止项清单被注释掉也照样拒
    # （实测：白名单分支同样会点名 evil.py，所以"点名"本身不够，措辞也要钉住）
    assert "禁止" in err, err


@pytest.mark.parametrize("ext", sorted(pet_plugin.FORBIDDEN_NESTED_EXTS))
def test_嵌套压缩包点名拒绝(tmp_path, ext):
    entry = "payload/inner" + ext
    entries = {entry: b"PK\x03\x04"}
    p = _write_zip(str(tmp_path / ("nest%s.dfypet-plugin" % ext.replace(".", "_"))),
                   entries, _manifest(entries))
    err = _err(p)
    # 光断言「err 里有文件名」不够：白名单分支的文案里也有文件名（质量审查实测：
    # 把判据 6 的嵌套压缩包分支删掉，err 变成「不在白名单里的文件类型：payload/inner.zip」，
    # 旧断言照样绿）。必须点名**原因**。
    assert "嵌套压缩包" in err and entry in err, err


def test_条目名含双点拒(tmp_path):
    entries = {"payload/../evil.txt": b"x"}
    p = _write_zip(str(tmp_path / "dotdot.dfypet-plugin"), entries, _manifest(entries))
    assert ".." in _err(p)


@pytest.mark.parametrize("name", ["/abs.txt", "C:/x.txt", "payload\\win.txt",
                                  "payload/a\x00b.txt", "other/outside.txt", "payload/./x.txt"])
def test_不安全条目名都拒(tmp_path, name):
    entries = {name: b"x"}
    p = _write_zip(str(tmp_path / "unsafe.dfypet-plugin"), entries, _manifest(entries))
    assert _err(p)


def test_payload_之外的干净文件也拒_单根(tmp_path):
    entries = {"payload/a.txt": b"x", "extra/b.txt": b"y"}
    m = _manifest({"payload/a.txt": b"x"})
    p = _write_zip(str(tmp_path / "singleroot.dfypet-plugin"), entries, m)
    assert "单根" in _err(p)


def test_扩展名白名单外的文件拒(tmp_path):
    entries = {"payload/note.exe": b"x"}
    p = _write_zip(str(tmp_path / "ext.dfypet-plugin"), entries, _manifest(entries))
    assert "note.exe" in _err(p)


def test_manifest_带BOM拒(tmp_path):
    entries = {"payload/a.txt": b"hello"}
    body = json.dumps(_manifest(entries), ensure_ascii=False).encode("utf-8")
    p = _write_zip(str(tmp_path / "bom.dfypet-plugin"), entries, None,
                   manifest_bytes=b"\xef\xbb\xbf" + body)
    err = _err(p)
    # json 自己的报错里本来就带 Unexpected UTF-8 BOM——只断言含 BOM 是**蒙的**
    # （质量审查实测：把判据 2 的显式 BOM 检查删掉，走 json 解析失败分支，旧断言仍然绿）。
    assert "必须无 BOM" in err, err


def test_缺manifest与坏json都拒(tmp_path):
    p = _write_zip(str(tmp_path / "nomanifest.dfypet-plugin"), {"payload/a.txt": b"x"},
                   None, omit_manifest=True)
    assert "manifest.json" in _err(p)
    p2 = _write_zip(str(tmp_path / "badjson.dfypet-plugin"), {"payload/a.txt": b"x"}, None,
                    manifest_bytes=b"{not json")
    assert "无法解析" in _err(p2)
    p3 = _write_zip(str(tmp_path / "notdict.dfypet-plugin"), {"payload/a.txt": b"x"}, None,
                    manifest_bytes=b"[1, 2]")
    assert "不是对象" in _err(p3)


def test_条目数与解压总量上限走_pet_export_同一来源(tmp_path, monkeypatch):
    """上限**复用** pet_export 的常量：改小它，校验器立刻跟着拒。"""
    assert pet_plugin.pet_export is pet_export
    entries = {"payload/a.txt": b"hello", "payload/b.txt": b"world"}
    p = _write_zip(str(tmp_path / "two.dfypet-plugin"), entries, _manifest(entries))
    assert _ok(p) is not None
    monkeypatch.setattr(pet_export, "EXPORT_MAX_ENTRIES", 1)
    assert "条目过多" in _err(p)
    monkeypatch.setattr(pet_export, "EXPORT_MAX_ENTRIES", 2000)
    monkeypatch.setattr(pet_export, "EXPORT_MAX_BYTES", 2)
    assert "体积过大" in _err(p)


def test_外部属性执行位与符号链接拒(tmp_path):
    entries = {"payload/a.txt": b"hello"}
    man = json.dumps(_manifest(entries), ensure_ascii=False).encode("utf-8")
    p = str(tmp_path / "exec.dfypet-plugin")
    with zipfile.ZipFile(p, "w") as z:
        z.writestr(pet_plugin.MANIFEST_NAME, man)
        zi = zipfile.ZipInfo("payload/a.txt")
        zi.external_attr = (0o100755 << 16)
        z.writestr(zi, b"hello")
    assert "执行位" in _err(p)

    p2 = str(tmp_path / "link.dfypet-plugin")
    with zipfile.ZipFile(p2, "w") as z:
        z.writestr(pet_plugin.MANIFEST_NAME, man)
        zi = zipfile.ZipInfo("payload/a.txt")
        zi.external_attr = (0o120777 << 16)
        z.writestr(zi, b"hello")
    assert "符号链接" in _err(p2)


# ---------------- 6~8. 版本门 / 校验和 ----------------

def test_min_host_version_99_拒且_err_含要求与当前(tmp_path):
    err = _err(_pack(tmp_path, meta=_meta(min_host_version="99.0.0")))
    assert "99.0.0" in err, err
    assert HOST in err, "err 里必须给出当前宿主版本：%s" % err
    # 边界：正好等于宿主版本要放行（"2.5" 与 "2.5.0" 同口径）
    assert _ok(_pack(tmp_path, meta=_meta(min_host_version="2.5"), name="eq.dfypet-plugin"))


def test_缺少_min_host_version拒(tmp_path):
    m = _meta()
    del m["min_host_version"]
    assert "min_host_version" in _err(_pack(tmp_path, meta=m))


def test_api_version_2_拒(tmp_path):
    err = _err(_pack(tmp_path, meta=_meta(api_version=2)))
    assert "API" in err and "2" in err, err


def test_sha256_改一位拒并点名文件(tmp_path):
    entries = {"payload/a.txt": b"hello", "payload/b.txt": b"world"}
    m = _manifest(entries)
    good = m["files"][0]["sha256"]
    m["files"][0]["sha256"] = ("0" if good[0] != "0" else "1") + good[1:]
    p = _write_zip(str(tmp_path / "sha.dfypet-plugin"), entries, m)
    err = _err(p)
    assert m["files"][0]["path"] in err, err
    assert "sha256" in err


def test_bytes_不符也拒(tmp_path):
    entries = {"payload/a.txt": b"hello"}
    m = _manifest(entries)
    m["files"][0]["bytes"] = 999
    p = _write_zip(str(tmp_path / "bytes.dfypet-plugin"), entries, m)
    err = _err(p)
    assert "bytes" in err and "a.txt" in err


def test_某_payload_文件不在_files_里拒(tmp_path):
    entries = {"payload/a.txt": b"hello", "payload/b.txt": b"world"}
    m = _manifest({"payload/a.txt": b"hello"})           # b.txt 故意漏掉
    p = _write_zip(str(tmp_path / "lack.dfypet-plugin"), entries, m)
    assert "b.txt" in _err(p)
    # 反向：多列一条 payload 之外的
    m2 = _manifest(entries)
    m2["files"].append({"path": "manifest.json", "sha256": _sha(b"x"), "bytes": 1})
    p2 = _write_zip(str(tmp_path / "extra.dfypet-plugin"), entries, m2)
    assert "多列" in _err(p2)


def test_目录条目不算漏列(tmp_path):
    """写包工具常带目录条目（payload/）——它不该被算成"没进 files"。"""
    entries = {"payload/a.txt": b"hello"}
    p = str(tmp_path / "dirs.dfypet-plugin")
    with zipfile.ZipFile(p, "w") as z:
        z.writestr(pet_plugin.MANIFEST_NAME,
                   json.dumps(_manifest(entries), ensure_ascii=False).encode("utf-8"))
        z.writestr("payload/", b"")
        z.writestr("payload/a.txt", b"hello")
    assert _ok(p) is not None


# ---------------- 9~12. 能力 / data_kind / UI ----------------

def test_kind_ui_拒(tmp_path):
    err = _err(_pack(tmp_path, meta=_meta(kind="ui", code=True, data_kind=None)))
    assert "UI" in err, err


def test_data_kind_越界拒(tmp_path):
    err = _err(_pack(tmp_path, meta=_meta(data_kind="fx")))
    assert "data_kind" in err and "fx" in err, err
    for kind in sorted(pet_plugin.DATA_KINDS):
        assert _ok(_pack(tmp_path, meta=_meta(data_kind=kind),
                         name="dk_%s.dfypet-plugin" % kind)), kind


def test_capabilities_越界拒(tmp_path):
    err = _err(_pack(tmp_path, meta=_meta(capabilities=["lines", "network"])))
    assert "network" in err, err
    for cap in sorted(pet_plugin.CAPABILITIES):
        assert _ok(_pack(tmp_path, meta=_meta(capabilities=[cap]),
                         name="cap_%s.dfypet-plugin" % cap)), cap


@pytest.mark.parametrize("pid", ["../evil", "a/b", "con", "tail.", "a..b", "", "x" * 65])
def test_不安全_id_拒(tmp_path, pid):
    assert _err(_pack(tmp_path, meta=_meta(id=pid)))


def test_包格式版本必须是_int_且不超宿主(tmp_path):
    assert "int" in _err(_pack(tmp_path, top={"version": "1"}))
    assert "格式版本" in _err(_pack(tmp_path, top={"version": 2}, name="v2.dfypet-plugin"))


# ---------------- 18. Phase 0 的形态约束（Qt-free / 不落盘） ----------------

def test_校验器是_Qt_free_纯逻辑模块():
    """子进程里 import pet_plugin：不许把 PySide6/PyQt 拉进来（Phase 0 要能无 GUI 单测）。

    能真失败：在 pet_plugin.py 顶部加一句 `from PySide6.QtWidgets import QDialog` → 立刻红。
    """
    import subprocess
    code = ("import sys; sys.path.insert(0, %r); import pet_plugin; "
            "bad = sorted({m.split('.')[0] for m in sys.modules "
            "if m.split('.')[0] in ('PySide6', 'PyQt5', 'PyQt6')}); "
            "print('QT=', bad)" % ROOT)
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env.pop("PYTHONPATH", None)
    proc = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True,
                          timeout=180, env=env, cwd=ROOT)
    out = proc.stdout.decode("utf-8", "replace").strip()
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-800:]
    assert out.endswith("QT= []"), "pet_plugin 把 Qt 拉进来了：%s" % out


def test_校验器只读不落盘也不碰启动路径():
    """Phase 0 只"看懂一个包"：源码里不许出现解压/删改文件的调用，也不许 import 入口模块。"""
    src = io.open(os.path.join(ROOT, "pet_plugin.py"), encoding="utf-8").read()
    banned = ("extractall", "shutil.", "os.remove", "os.rename", "os.makedirs", "os.replace",
              '"w"', "'w'", '"wb"', "import 桌宠", "from 桌宠")
    hit = [b for b in banned if b in src]
    assert hit == [], "校验器不该做这些事（Phase 0 只读）：%r" % (hit,)
    # 控制组：它确实在读文件（否则上面那条是空转）
    assert 'open(path, "r", encoding="utf-8-sig")' in src


def test_版本比较口径与发布门一致():
    """pet_plugin.version_key 与 _check_release._ver_key 同款——漂了这条就红。"""
    import _check_release as chk
    for v in ("2.5.0", "2.4", "2.4.1b1", "(2, 4, 0, 0)", "", None, "10.0.0.9",
              "2.10.0", "0.0.0.1", 3):
        assert pet_plugin.version_key(v) == chk._ver_key(v), v


# ---------------- 13~15. read_installed ----------------

def _install(tmp_path, pid="official-lines-basic", meta=None, index=None, extra_files=None):
    """造一个 plugins 目录，返回它。"""
    base = tmp_path / "plugins"
    d = base / pid
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(
        json.dumps({"format": "dfypet-plugin", "version": 1, "files": [],
                    "plugin": _meta(id=pid) if meta is None else meta}, ensure_ascii=False),
        encoding="utf-8")
    if index is not None:
        (base / pet_plugin.INSTALLED_INDEX_NAME).write_text(
            json.dumps(index, ensure_ascii=False), encoding="utf-8")
    for rel, data in (extra_files or {}).items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return str(base)


def test_plugins_目录不存在返回空不抛(tmp_path):
    assert pet_plugin.read_installed(str(tmp_path / "nope")) == ([], [])
    assert pet_plugin.read_installed("") == ([], [])


def test_目录里放普通文件跳过不抛(tmp_path):
    base = tmp_path / "plugins"
    base.mkdir()
    (base / "readme.txt").write_text("hi", encoding="utf-8")
    (base / pet_plugin.INSTALLED_INDEX_NAME).write_text("{坏 json", encoding="utf-8")
    items, problems = pet_plugin.read_installed(str(base))
    assert items == []
    assert problems and pet_plugin.INSTALLED_INDEX_NAME in problems[0]


def test_插件目录无_manifest_跳过不抛(tmp_path):
    base = tmp_path / "plugins"
    (base / "x" / "payload").mkdir(parents=True)
    items, problems = pet_plugin.read_installed(str(base))
    assert items == []
    assert any("manifest.json" in p and "x" in p for p in problems), problems


def test_read_installed_读到条目与启用状态(tmp_path):
    base = _install(tmp_path, index={"format": "dfypet-plugins-installed", "version": 1,
                                     "plugins": {"official-lines-basic": {
                                         "enabled": False, "source_url": "https://x/y.zip"}}})
    items, problems = pet_plugin.read_installed(base)
    assert problems == [], problems
    assert len(items) == 1
    it = items[0]
    assert it["id"] == "official-lines-basic" and it["enabled"] is False
    assert it["source_url"] == "https://x/y.zip"
    assert it["kind"] == "data" and it["data_kind"] == "lines"
    assert it["name"] == "示例台词包"


def test_read_installed_坏manifest与下划线目录都跳过(tmp_path):
    base = _install(tmp_path)
    bad = os.path.join(base, "broken")
    os.makedirs(bad)
    with io.open(os.path.join(bad, "manifest.json"), "w", encoding="utf-8") as f:
        f.write("{oops")
    os.makedirs(os.path.join(base, "_download"))          # 临时目录：静默跳过
    with io.open(os.path.join(base, "_download", "a.part"), "w", encoding="utf-8") as f:
        f.write("x")
    items, problems = pet_plugin.read_installed(base)
    assert len(items) == 1 and items[0]["id"] == "official-lines-basic"
    assert any("broken" in p for p in problems), problems
    assert not any("_download" in p for p in problems), problems


# ---------------- 16. 回归：角色包行为不动 ----------------

def test_回归_validate_bundle_行为逐位不变(tmp_path):
    """插件校验器不得改变角色包校验：常量、通过路径、错误文案都逐字不变。"""
    assert pet_export.EXPORT_MAX_ENTRIES == 2000
    assert pet_export.EXPORT_MAX_BYTES == 512 * 1024 * 1024
    assert pet_export.BUNDLE_FORMAT == "dfypet-role"
    good = {"format": "dfypet-role", "version": 1,
            "role": {"id": "r1", "file": "a.png", "name": "鱼"}}
    p = _write_zip(str(tmp_path / "role.dfypet.zip"), {"roles/a.png": b"x"}, good)
    manifest, err = pet_export.validate_bundle(p)
    assert err == "" and manifest["role"]["id"] == "r1"
    # 错误文案逐字不变
    p2 = _write_zip(str(tmp_path / "nomani.dfypet.zip"), {"roles/a.png": b"x"}, None,
                    omit_manifest=True)
    assert pet_export.validate_bundle(p2) == (None, "不是角色包：缺少 manifest.json")
    bad_fmt = {"format": "dfypet-plugin", "version": 1, "plugin": {}}
    p3 = _write_zip(str(tmp_path / "wrongfmt.dfypet.zip"), {"x.txt": b"x"}, bad_fmt)
    assert pet_export.validate_bundle(p3) == (
        None, "不是大肥鱼角色包（format=%r）" % "dfypet-plugin")
    # 插件校验器也不认角色包（两个校验器互不串门）
    assert pet_plugin.validate_plugin_zip(p, HOST)[0] is None


# ---------------- 17. 文档与校验器清单一致（同时写死） ----------------

def test_禁止项清单与文档同时写死():
    doc = io.open(os.path.join(ROOT, "_dev", "plugin_format_v251.md"), encoding="utf-8").read()
    for ext in sorted(pet_plugin.FORBIDDEN_EXTS):
        assert ext in doc, "禁止项 %s 没写进 _dev/plugin_format_v251.md" % ext
    for kind in sorted(pet_plugin.DATA_KINDS):
        assert kind in doc, "DATA_KINDS 的 %s 没写进文档" % kind
    assert pet_plugin.PLUGIN_FORMAT in doc

# ---------------- 19. v2.5.1 审查修复：版本门 fail-closed / 分块读 / 保留名 ----------------

@pytest.mark.parametrize("bad", ["abc", "latest", "v2.5.0", "LTS", "二点五"])
def test_min_host_version不是版本号一律拒(tmp_path, bad):
    """S2-a（找茬审查实测）：version_key 只抽数字 → "abc"/"latest" 被抽成 (0,0,0,0)，
    判据 9 恒放行——写错版本号的包反而畅通无阻（fail-open）。

    能真失败：去掉 validate_plugin_zip 里的 _is_version_like 那一关 → 这些包全被放行，红。
    """
    path = _pack(tmp_path, meta=_meta(min_host_version=bad))
    err = _err(path)
    assert "版本号" in err, err


def test_min_host_version数字版本照旧按版本比(tmp_path):
    """控制组：正常数字版本仍然按版本号比——不能为了 fail-closed 把好包一起拒了。

    能真失败：把 _is_version_like 写成"永远 False"（或拿去判 host_version）→ 第一条断言红。
    """
    fine = _pack(tmp_path, name="fine.dfypet-plugin", meta=_meta(min_host_version="2.5"))
    assert _ok(fine)["plugin"]["min_host_version"] == "2.5"
    old = _pack(tmp_path, name="old.dfypet-plugin", meta=_meta(min_host_version="99.0.0"))
    assert "99.0.0" in _err(old)


def test_判据10分块读_不把payload整份读进内存(tmp_path, monkeypatch):
    """S2-b（实测）：判据 10 此前 zf.read 把每个 payload 文件整份读进 texts 字典
    （64MB payload 实测峰值 141MB，按 512MB 上限外推 >1GB）。现在分块边读边算摘要。

    能真失败：把分块循环改回 zf.read(n) → 这个 stub 立刻抛 AssertionError，红。
    """
    path = _pack(tmp_path, payload={"a.txt": b"hi",
                                    "big.txt": b"x" * (2 * 1024 * 1024 + 7)})
    real_read = zipfile.ZipFile.read

    def _no_slurp(self, name, pwd=None):
        if str(name).startswith("payload/"):
            raise AssertionError("payload 条目被整份读进内存了：%s" % name)
        return real_read(self, name, pwd)

    monkeypatch.setattr(zipfile.ZipFile, "read", _no_slurp)
    manifest = _ok(path)
    assert [f["path"] for f in manifest["files"]] == ["payload/a.txt", "payload/big.txt"]

    # 控制组：摘要真的算了——清单里的 sha256 改坏一位，分块路径必须抓住（否则上面是空转）
    one = {"payload/a.txt": b"hi"}
    bad = _manifest(one, meta=_meta())
    bad["files"][0]["sha256"] = "0" * 64
    bad_path = _write_zip(str(tmp_path / "bad.dfypet-plugin"), one, bad)
    assert "sha256" in _err(bad_path)


def test_判据10按真实解压字节记账():
    """S2-b 的第二半：判据 1 只看 zip 中央目录**声明**的 file_size（可以是假的），所以读的
    时候必须按**真实**字节再记一次总数并与上限比。

    能真失败：去掉 total_real 的累计（或那句超限判断）→ 这条红。
    为什么不写成"造一个超限包"的用例：用 zipfile 造不出"声明小、实际大"的包——伪造的
    usize 会被 zipfile 自己的 CRC / 长度校验挡住（审查也确认过），所以只能钉住这段记账本身。
    """
    src = io.open(os.path.join(ROOT, "pet_plugin.py"), encoding="utf-8").read()
    assert 'with zf.open(n, "r") as src' in src, "payload 不是分块读的（又回到整份读？）"
    assert "total_real += len(chunk)" in src, "判据 10 没有累计真实解压字节"
    assert "if total_real > cap:" in src, "真实解压体积没有跟上限比"


def test_出货布局的保留名静默跳过_packs不再报读不出来(tmp_path):
    """P2-2（实测）：plugins/packs/ 是官方内容包目录，没有 manifest.json 是当然的；此前
    read_installed 对它报"插件目录缺 manifest.json，已跳过：packs"，对话框永远显示
    「共 0 个插件；有 1 处读不出来：…packs」。

    能真失败：去掉 read_installed 里 is_reserved_plugin_name 那一跳 → problems 非空，红。
    """
    base = tmp_path / "plugins"
    (base / "packs").mkdir(parents=True)
    (base / "packs" / "official-lines-1.0.0.dfypet-plugin.zip").write_bytes(b"PK")
    (base / "index.json").write_text("{}", encoding="utf-8")
    (base / "README.md").write_text("官方内容仓库", encoding="utf-8")
    (base / "broken").mkdir()                       # 控制组：真坏的目录还是要报
    items, problems = pet_plugin.read_installed(str(base))
    assert items == []
    assert any("broken" in p for p in problems), problems
    assert not any("packs" in p for p in problems), problems
    assert not any("index.json" in p for p in problems), problems


def test_保留名判据大小写不敏感(tmp_path):
    """Windows / macOS 的文件系统大小写不敏感：PACKS 与 packs 是同一个目录——比对必须按
    小写，否则把 id 换个大小写就绕过了保留名。

    能真失败：把 is_reserved_plugin_name 的 lower() 去掉 → 下面第二条断言红。
    """
    for name in ("packs", "PACKS", "Packs", "index.json", "INDEX.JSON", "readme.md",
                 "README.md", "_download", "_installed.json"):
        assert pet_plugin.is_reserved_plugin_name(name) is True, name
    for name in ("official-lines-basic", "my-pack", "packs2", "index.json.bak", ""):
        assert pet_plugin.is_reserved_plugin_name(name) is False, name

# ---------------- 20. v2.5.1 质量审查：承重判据的灵敏度补齐 ----------------

def test_白名单兜底_既不在禁止清单也不在白名单的扩展名要拒(tmp_path):
    """质量审查实测：if ext not in ALLOWED_EXTS（白名单兜底）拿掉后 A 的 52 条全绿——
    因为旧用例用的是 note.exe（走**禁止清单**分支，压根没碰白名单）。

    能真失败：删掉白名单兜底那一跳 → .flac/.svg 会被放行，红。
    """
    for ext in (".flac", ".svg", ".heic", ""):
        entry = "payload/song" + ext if ext else "payload/song"
        entries = {entry: b"x"}
        p = _write_zip(str(tmp_path / ("wl%s.dfypet-plugin" % ext.replace(".", "_"))),
                       entries, _manifest(entries))
        err = _err(p)
        assert "白名单" in err, err
    # 控制组：白名单里的扩展名照旧通过（别把好包一起拒了）
    entries = {"payload/a.txt": b"x", "payload/b.png": b"x", "payload/c.json": b"{}",
               "payload/d.md": b"#"}
    assert _ok(_write_zip(str(tmp_path / "wl_ok.dfypet-plugin"), entries,
                          _manifest(entries))) is not None


def test_kind枚举_未知的kind一律拒(tmp_path):
    """质量审查实测：判据 7 的 if kind not in ("data", "ui") 拿掉后 A 的 52 条 + C 的 111
    条全绿——kind=shell 且 code=true 会被校验器放行（安装器仍拒，端到端不破，所以没人发现）。

    能真失败：删掉 kind 枚举那一跳 → shell 会被放行（后面只判 code 与 kind 的关系），红。
    """
    for kind in ("shell", "role", "", None, 1):
        path = _pack(tmp_path, name="kind_%s.dfypet-plugin" % (kind,),
                     meta=_meta(kind=kind, code=True))
        err = _err(path)
        assert "kind" in err, err
    # 控制组：kind=ui + code=true 走到的是「本版本不支持 UI 插件」，不是被枚举拒
    assert "UI 插件" in _err(_pack(tmp_path, name="ui.dfypet-plugin",
                                   meta=_meta(kind="ui", code=True)))


def test_payload_root必须以斜杠结尾(tmp_path):
    """判据（payload_root 归一）：不以 / 结尾的单根一律拒——"payload" 会被当前缀匹配上
    "payloadX/y.txt"，单根保证就漏了。

    能真失败：去掉那条 endswith 判断 → 下面这个包通过，红。
    """
    entries = {"payload/a.txt": b"x"}
    m = _manifest(entries, payload_root="payload")
    p = _write_zip(str(tmp_path / "noroot.dfypet-plugin"), entries, m)
    assert "payload_root" in _err(p)


@pytest.mark.parametrize("root", ["../payload/", "/payload/", "C:/payload/", "pay\\load/"])
def test_payload_root自身路径必须安全(tmp_path, root):
    """判据（payload_root 路径安全）：越界 / 绝对 / 带反斜杠的单根一律拒——它是**解包时的
    根前缀**，不安全就等于把 zip 里的名字当路径用。

    能真失败：去掉那段路径安全检查 → 这些包全过，红。
    """
    entries = {"payload/a.txt": b"x"}
    m = _manifest(entries, payload_root=root)
    p = _write_zip(str(tmp_path / "badroot.dfypet-plugin"), entries, m)
    assert "payload_root" in _err(p)


def test_files清单里重复path要拒(tmp_path):
    """判据 10：files 里同一个 path 出现两次 → 拒（第二条可以带一份假哈希来「盖章」）。

    能真失败：删掉那条 len(set(listed)) != len(listed) 判断 → 重复清单被放行，红。
    """
    entries = {"payload/a.txt": b"x"}
    m = _manifest(entries)
    m["files"] = m["files"] + [dict(m["files"][0])]
    p = _write_zip(str(tmp_path / "dup.dfypet-plugin"), entries, m)
    assert "重复" in _err(p)


def test_capabilities形态非法要拒(tmp_path):
    """判据 8：capabilities 必须是**字符串列表**——不是列表、元素不是字符串都拒
    （只判「越界」是不够的：非字符串元素会让宿主权限白名单的比较失去意义）。

    能真失败：把 isinstance 那两跳去掉 → 下列包全过，红。
    """
    for i, caps in enumerate(("lines", {"lines": 1}, [1], [None], ["lines", 2])):
        path = _pack(tmp_path, name="caps_%d.dfypet-plugin" % i,
                     meta=_meta(capabilities=caps))
        err = _err(path)
        assert "capabilities" in err, err
    # 控制组：合法空表与合法子集照旧通过
    assert _ok(_pack(tmp_path, name="caps_ok.dfypet-plugin",
                     meta=_meta(capabilities=sorted(pet_plugin.CAPABILITIES)))) is not None



@pytest.mark.parametrize("pid", ["packs", "PACKS", "index.json", "README.md"])
def test_保留名不许当插件id(tmp_path, pid):
    """P1-1 的第一道门：id="packs" 在字符集里完全合法，但它在 plugins/ 下有别的用途
    （官方内容包目录）——校验器直接点名拒绝；安装器另有第二道自保（见 host 用例）。

    能真失败：去掉 _id_problem 里的 is_reserved_plugin_name 那一跳 → 这些包通过，红。
    """
    err = _err(_pack(tmp_path, meta=_meta(id=pid)))
    assert "保留名" in err, err

