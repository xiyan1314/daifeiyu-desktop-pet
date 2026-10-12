# -*- coding: utf-8 -*-
"""代理C（v2.6.0）实测：校验器与安装器的两处口径差（收口前 / 收口后）。

跑法::

    python -B _dev/probe_plugin_gap_v260.py            # 当前树（收口后）
    python -B _dev/probe_plugin_gap_v260.py --before    # 模拟 v2.5.1 的旧判定（收口前）

--before 的做法是**把新加的那两条判据的结果丢掉**（包装 pet_plugin._unsafe_name_reason 与
pet_plugin._files_problems），不是另写一套校验器——所以它复现的就是"收口前校验器会怎么判"。

只读：所有包都造在临时目录里，装到临时数据目录，跑完删干净；真实仓库一个字节都不写。
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import pet_plugin
import pet_plugin_host

HOST = "2.5.0"
BEFORE = "--before" in sys.argv


def _apply_legacy(pp):
    """把校验器临时退回 v2.5.1 的口径（只丢掉 v2.6.0 新加的判定结果）。"""
    real_unsafe = pp._unsafe_name_reason
    real_files = pp._files_problems

    def legacy_unsafe(name):
        why = real_unsafe(name)
        if "Windows 非法字符" in why or "Windows 保留设备名" in why:
            return ""
        return why

    def legacy_files(files, payload_files, digests):
        return [b for b in real_files(files, payload_files, digests) if "清单是空的" not in b]

    pp._unsafe_name_reason = legacy_unsafe
    pp._files_problems = legacy_files


def _sha(d):
    return hashlib.sha256(d).hexdigest()


def _meta(**over):
    m = {"id": "official-lines-basic", "name": "x", "version": "1.0.0", "kind": "data",
         "data_kind": "lines", "code": False, "min_host_version": HOST, "api_version": 1,
         "capabilities": []}
    m.update(over)
    return m


def _manifest(entries, meta=None):
    return {"format": "dfypet-plugin", "version": 1, "payload_root": "payload/",
            "files": [{"path": n, "sha256": _sha(d), "bytes": len(d)}
                      for n, d in sorted(entries.items())],
            "plugin": _meta() if meta is None else meta}


def build(path, entries, manifest, dirs=()):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False).encode("utf-8"))
        for d in dirs:
            z.writestr(d, b"")
        for n, data in entries.items():
            z.writestr(n, data)
    return path


def case(label, entries, manifest, dirs=()):
    tmp = tempfile.mkdtemp(prefix="gapc_")
    try:
        p = build(os.path.join(tmp, "p.dfypet-plugin"), entries, manifest, dirs)
        man, err = pet_plugin.validate_plugin_zip(p, HOST)
        print("[%s] 校验器：%s  err=%r" % (label, "通过" if man is not None else "拒绝", err))
        data_dir = os.path.join(tmp, "data")
        os.makedirs(data_dir, exist_ok=True)
        host = pet_plugin_host.PluginHost(data_dir, host_version=HOST)
        ok, msg = host.install_zip(p)
        print("        安装器：ok=%s  msg=%s" % (ok, msg))
        left = os.path.join(data_dir, "plugins")
        print("        残余：%s" % (sorted(os.listdir(left)) if os.path.isdir(left) else "(无 plugins/)"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    print("模式：%s（%s）" % ("收口前（模拟 v2.5.1 判定）" if BEFORE else "当前树",
                             "丢掉新判据的结果" if BEFORE else "校验器先拒"))
    if BEFORE:
        _apply_legacy(pet_plugin)
    # 1) payload/a:b.png —— 冒号（Windows 非法字符）
    e1 = {"payload/a:b.png": b"x"}
    case("冒号", e1, _manifest(e1))
    # 2) payload/con.png —— Windows 保留设备名
    e2 = {"payload/con.png": b"x"}
    case("保留设备名", e2, _manifest(e2))
    # 3) files: [] + 空的 payload/ 目录条目
    case("files=[] 空目录", {}, _manifest({}), dirs=("payload/",))
    # 4) files: [] 且连 payload/ 目录条目都没有
    case("files=[] 无目录", {}, _manifest({}))
    # 5) 控制组：正常包（必须两侧都放行到落地那一步）
    e5 = {"payload/a.txt": b"hello"}
    case("控制组", e5, _manifest(e5))


main()
