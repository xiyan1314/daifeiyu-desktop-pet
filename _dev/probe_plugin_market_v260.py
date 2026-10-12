# -*- coding: utf-8 -*-
"""代理 A（v2.6.0 Phase 2）实测探针：索引下载器 + 更新/回滚/内容指纹去重（**只读真仓**）。

跑法（在仓库根目录）：python -B _dev/probe_plugin_market_v260.py

它做四件事，全部用**真**代码路径（真索引文件 / 真 zip / 真宿主库 / 真安装登记），
只在临时目录里落数据：
  1. 读**随包**的 plugins/index.json（不联网），打印每个条目的版本/大小/可装性；
  2. 用一个最小的台词包演示"更新按内容指纹合并"：v1 → v2（新增 1 条）→ v2 再装（0 条新增）；
  3. 演示回滚：撤销本版新落地、恢复上一版目录与登记，用户自己的台词一件不动；
  4. 打印安装登记的 landed / landed_fingerprints / history 三个字段的真实内容。
"""
import json
import os
import shutil
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pet_lines            # noqa: E402
import pet_plugin           # noqa: E402
import pet_plugin_host      # noqa: E402
import pet_plugin_index     # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print("  [%s] %s%s" % ("OK" if ok else "FAIL", label, ("  —— " + str(detail)) if detail else ""))
    if not ok:
        FAILED.append(label)


def _pack(path, texts, version, pid="probe-lines"):
    payload = {"lines.json": json.dumps({"lines": [{"text": t, "category": "idle"}
                                                   for t in texts]}, ensure_ascii=False).encode("utf-8")}
    files = [{"path": "payload/lines.json", "sha256": __import__("hashlib").sha256(
        payload["lines.json"]).hexdigest(), "bytes": len(payload["lines.json"])}]
    manifest = {"format": pet_plugin.PLUGIN_FORMAT, "version": 1, "payload_root": "payload/",
                "files": files, "plugin": {"id": pid, "name": "探针包", "version": version,
                                           "kind": "data", "data_kind": "lines", "code": False,
                                           "min_host_version": "2.5.0", "api_version": 1,
                                           "capabilities": []}}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        for rel, data in payload.items():
            zf.writestr("payload/" + rel, data)
    return path


print("== 1. 随包索引（不联网）==")
index = pet_plugin_index.PluginIndex(os.path.join(ROOT, "plugins"), host_version="2.5.1")
data, err = index.load_index()
check("随包索引读得出来", data is not None and err == "", err)
if data:
    print("     来源=%s 更新于=%s 条目=%d 问题=%r"
          % (data["source"], data["updated_at"], len(data["entries"]), data["problems"]))
    for entry in data["entries"]:
        print("     %-26s v%-7s %8s %s" % (entry["id"], entry["version"], entry["size_text"],
                                           "可安装" if entry["installable"] else
                                           "不可安装：" + entry["reason"]))
    check("5 个官方包在 2.5.1 上全部可安装",
          len(data["entries"]) == 5 and all(e["installable"] for e in data["entries"]))

tmp = tempfile.mkdtemp(prefix="probe_market_")
try:
    print("== 2. 更新：按内容指纹合并（真安装管线）==")
    lib = pet_lines.LineService(tmp)
    host = pet_plugin_host.PluginHost(tmp, "2.5.0", lines_lib=lib)
    lib.add("用户自己写的台词", "idle")
    base = len(lib.lines())
    ok1, msg1 = host.install_zip(_pack(os.path.join(tmp, "v1.zip"), ["甲"], "1.0.0"))
    print("     v1：(%s) %s" % (ok1, msg1))
    ok2, msg2 = host.install_zip(_pack(os.path.join(tmp, "v2.zip"), ["甲", "乙"], "1.1.0"))
    print("     v2：(%s) %s" % (ok2, msg2))
    texts = [x["text"] for x in lib.lines()]
    check("新版新增的「乙」真的进库", texts.count("乙") == 1, texts[-4:])
    check("上一版就有的「甲」没有重复落", texts.count("甲") == 1)
    ok3, msg3 = host.install_zip(_pack(os.path.join(tmp, "v2b.zip"), ["甲", "乙"], "1.1.0"))
    print("     v2 再装一次：(%s) %s" % (ok3, msg3))
    check("内容一致时一条都不再落", "完全一致" in msg3 and len(lib.lines()) == base + 2)

    reg_path = os.path.join(tmp, "plugins", "_installed.json")
    reg = json.load(open(reg_path, encoding="utf-8"))["plugins"]["probe-lines"]
    print("     landed            = %s" % json.dumps(reg["landed"], ensure_ascii=False))
    print("     fingerprints      = %d 条（每条 64 位 hex）"
          % len(reg["landed_fingerprints"].get("lines", [])))
    print("     history           = %d 条上一版记录" % len(reg["history"]))
    check("指纹账里有 2 条", len(reg["landed_fingerprints"].get("lines", [])) == 2)
    check("上一版记录留了一份", len(reg["history"]) == 1)
    check("上一版目录真的在盘上", os.path.isdir(os.path.join(tmp, "plugins", ".prev-probe-lines")))

    print("== 3. 回滚 ==")
    ok4, msg4 = host.rollback("probe-lines")
    print("     rollback：(%s) %s" % (ok4, msg4))
    texts = [x["text"] for x in lib.lines()]
    check("本版新增的「乙」被撤销", "乙" not in texts)
    check("上一版的「甲」还在", "甲" in texts)
    check("用户自己的台词一件没动", "用户自己写的台词" in texts)
    reg = json.load(open(reg_path, encoding="utf-8"))["plugins"]["probe-lines"]
    check("登记回到上一版 1.0.0", reg["version"] == "1.0.0", reg["version"])
    check("上一版备份目录用完即删",
          not os.path.isdir(os.path.join(tmp, "plugins", ".prev-probe-lines")))

    print("== 4. 回滚后再更新一次 ==")
    ok5, msg5 = host.install_zip(_pack(os.path.join(tmp, "v2c.zip"), ["甲", "乙"], "1.1.0"))
    print("     再更新：(%s) %s" % (ok5, msg5))
    texts = [x["text"] for x in lib.lines()]
    check("回滚后新版内容重新落地", texts.count("乙") == 1 and texts.count("甲") == 1)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("")
print("探针结论：%s" % ("全部通过" if not FAILED else "有 %d 项失败：%r" % (len(FAILED), FAILED)))
raise SystemExit(0 if not FAILED else 1)
