# -*- coding: utf-8 -*-
"""端到端：官方索引 → 官方包 → **真安装器** → 宿主库（v2.5.1 · 代理 C）。

与另外两支探针的分工：
  * _dev/verify_plugin_packs_v251.py —— 包**合不合法**（12 条判据 + 反向变异）；
  * _dev/probe_plugin_landing_v251.py —— 五类 data_kind 的**宿主接口**能不能落地；
  * 本脚本 —— "用户能下载内容"这条**链路**：index.json 里的 url/sha256 → 本地包 →
    pet_plugin_host.PluginHost.install_zip（与插件管理对话框同一条路径）→ 宿主库条目增加
    → 卸载/禁用/重复安装的行为符合口径。

用法::

    python -B _dev/probe_plugin_install_v251.py
"""
import hashlib
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
for p in (REPO, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import plugin_pack_rules as rules        # noqa: E402
import build_official_plugins as builder  # noqa: E402

PLUGINS = os.path.join(REPO, "plugins")
RESULTS = []


def check(label, ok, detail=""):
    RESULTS.append((label, bool(ok), detail))
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", label,
                           ("  -- %s" % detail) if (detail and not ok) else ""))


def _resolve_index_url(base, url):
    """索引里的 url → 本地包路径（v2.5.1：发布时用 --base-url 重算过的绝对地址也能定位）。

    相对地址（packs/x.zip）照旧按 base 拼接；绝对地址（https://…/v2.5.1/x.zip）在本地没有
    对应文件，但发布包里**就是** plugins/packs/x.zip 那一份 → 按 basename 回落到磁盘。
    两边都不存在时返回拼出来的路径，调用方报「url 指向的包不存在」。
    """
    text = str(url or "").strip().replace(chr(92), "/")
    if "://" in text or text.startswith("/"):
        return os.path.join(base, "packs", text.rsplit("/", 1)[-1])
    return os.path.join(base, *text.split("/"))


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    host_ver = rules.host_version()
    print("官方插件链路端到端 · 宿主版本 %s" % host_ver)
    try:
        import pet_lines
        import pet_behaviors
        import pet_plugin_host
        import pet_resources
    except Exception as e:
        print("  [FAIL] 真安装器不可用（pet_plugin_host 导入失败）：%r" % (e,))
        print("\n共 1 条检查：PASS 0 / FAIL 1")
        return 1

    with open(os.path.join(PLUGINS, "index.json"), "r", encoding="utf-8") as f:
        index = json.load(f)
    releases = []          # [(插件条目, release)]
    for item in index.get("plugins") or []:
        for rel in item.get("releases") or []:
            releases.append((item, rel))
    check("索引里有可下载的包（%d 个）" % len(releases), bool(releases))

    # ---- 第 1 步：按索引取包（url 相对 index.json 所在目录解析）+ 校验哈希 ----
    packs = []
    bad = []
    for item, rel in releases:
        path = _resolve_index_url(PLUGINS, rel.get("url"))
        if not os.path.isfile(path):
            bad.append("url 指向的包不存在：%s" % rel.get("url"))
            continue
        if _sha256(path) != rel.get("sha256"):
            bad.append("%s 的 sha256 与索引不符" % rel.get("url"))
        if os.path.getsize(path) != rel.get("bytes"):
            bad.append("%s 的 bytes 与索引不符" % rel.get("url"))
        packs.append((item, rel, path))
    check("按索引 url 取到包，且 sha256/bytes 都对得上（下载前的完整性校验）",
          len(packs) == len(releases) and not bad, "；".join(bad))
    if not packs:
        return 1

    with tempfile.TemporaryDirectory(prefix="dfypet_e2e_") as td:
        role_lib = pet_resources.RoleLibrary(td)
        lines_lib = pet_lines.LineService(td)
        audio_lib = pet_resources.AudioLibrary(td)
        behaviors = pet_behaviors.BehaviorService(td)
        # 预置用户数据：装插件不许动它们
        user_line, lerr = lines_lib.add("用户自己写的台词（端到端探针）", "idle")
        check("预置：用户自己的一条台词", user_line is not None, str(lerr))
        before = {"lines": lines_lib.count(), "roles": len(role_lib.list_roles()),
                  "audio": len(audio_lib.fragments()), "behaviors": len(behaviors.list())}
        host = pet_plugin_host.PluginHost(td, host_ver, role_lib=role_lib,
                                          lines_lib=lines_lib, audio_lib=audio_lib,
                                          behaviors=behaviors)

        # ---- 第 2 步：逐个安装（走真安装器） ----
        installed = []
        for item, rel, path in packs:
            ok, msg = host.install_zip(path, source_url=str(rel.get("url")))
            if ok:
                installed.append((item, rel, path))
            check("安装「%s」: %s" % (item.get("id"), msg if ok else "失败"),
                  ok, str(msg))
        after = {"lines": lines_lib.count(), "roles": len(role_lib.list_roles()),
                 "audio": len(audio_lib.fragments()), "behaviors": len(behaviors.list())}
        prompt_dir = os.path.join(td, "prompts", "custom")
        n_prompt = len([n for n in os.listdir(prompt_dir)
                        if n.lower().endswith(".txt")]) if os.path.isdir(prompt_dir) else 0
        check("装完宿主库真的多了东西：角色 +%d / 台词 +%d / 音效 +%d / 行为 +%d / 人设 +%d"
              % (after["roles"] - before["roles"], after["lines"] - before["lines"],
                 after["audio"] - before["audio"], after["behaviors"] - before["behaviors"],
                 n_prompt),
              after["roles"] > before["roles"] and after["lines"] >= before["lines"] + 12
              and after["audio"] >= before["audio"] + 6
              and after["behaviors"] >= before["behaviors"] + 4 and n_prompt >= 1,
              "before=%r after=%r prompt=%d" % (before, after, n_prompt))
        check("原有内容一条不少：用户那条台词还在",
              any(l["text"].startswith("用户自己写的台词") for l in lines_lib.lines()))
        rows, problems = host.list_installed()
        by_id = {r.get("id"): r for r in rows}
        check("已装清单能看到全部插件（%d 个）且无问题串" % len(installed),
              all(i.get("id") in by_id for i, _r, _p in installed) and not problems,
              "problems=%r" % (problems,))
        check("登记里记下了来源 url 与启用状态",
              all(by_id[i.get("id")].get("source_url") == r.get("url")
                  and by_id[i.get("id")].get("enabled") is True for i, r, _p in installed),
              str({k: (v.get("source_url"), v.get("enabled")) for k, v in by_id.items()}))

        # ---- 第 3 步：禁用（只改登记，文件不动） ----
        pid0 = installed[0][0].get("id")
        ok, msg = host.set_enabled(pid0, False)
        rows2 = {r.get("id"): r for r in host.list_installed()[0]}
        check("禁用插件：登记变 False 且插件目录还在（可逆）",
              ok and rows2.get(pid0, {}).get("enabled") is False
              and os.path.isdir(os.path.join(td, "plugins", pid0)), str(msg))
        host.set_enabled(pid0, True)

        # ---- 第 4 步：重复安装 = 覆盖更新，内容**不重复落地** ----
        lines_mid = lines_lib.count()
        ok, msg = host.install_zip(installed[0][2], source_url=installed[0][1].get("url"))
        check("重复安装同一包：成功且**不重复落地**（台词数不变）",
              ok and lines_lib.count() == lines_mid, "%s / 台词 %d -> %d"
              % (msg, lines_mid, lines_lib.count()))

        # ---- 第 5 步：卸载（插件目录删、已落地资产保留） ----
        target = os.path.join(td, "plugins", pid0)
        lines_before_uninstall, roles_before_uninstall = lines_lib.count(), len(role_lib.list_roles())
        ok, msg = host.uninstall(pid0)
        check("卸载：插件目录已删（%s）" % pid0, ok and not os.path.isdir(target), str(msg))
        check("卸载：已落地的台词/角色**仍在**（属用户数据，与「导入角色包」同口径）",
              lines_lib.count() == lines_before_uninstall
              and len(role_lib.list_roles()) == roles_before_uninstall)
        check("卸载：登记里没有它了",
              pid0 not in {r.get("id") for r in host.list_installed()[0]})
        check("卸载后重装又装得上（链路可反复走）",
              host.install_zip(installed[0][2], source_url="")[0])

    # ---- 上架口径：pending 的包既不在索引里也不在磁盘上 ----
    disk = sorted(f for f in os.listdir(os.path.join(PLUGINS, "packs"))
                  if f.endswith(builder.BUNDLE_EXT)) if os.path.isdir(
        os.path.join(PLUGINS, "packs")) else []
    indexed = sorted(str(r.get("url") or "").rsplit("/", 1)[-1] for _i, r in releases)
    check("索引条目与磁盘上的包一一对应", disk == indexed,
          "磁盘 %s / 索引 %s" % (disk, indexed))
    pending = sorted(p["id"] for p in builder.PACKS if p.get("landing") != "ready")
    # v2.5.1：此前写成 p.startswith(tuple(pending))——pending 为空时 tuple() 是 ()，
    # str.startswith(()) 恒 False，"判据"永远绿（空转）。现在按 [id + "-"] 前缀真比对，
    # 并配一条控制组：随便拿一个 ready 的包当 pending，判据必须**当场响**。
    leaked = [f for f in disk if any(f.startswith(pid + "-") for pid in pending)]
    check("landing=pending 的包（%s）本轮不上架（宁少勿假）" % ("、".join(pending) or "无"),
          not leaked, "不该上架却在磁盘上：%s" % leaked)
    if builder.PACKS:
        fake = [builder.PACKS[0]["id"]]
        control = [f for f in disk if any(f.startswith(pid + "-") for pid in fake)]
        check("控制组：pending 判据真的会响（拿 %s 当 pending）" % fake[0], bool(control),
              "判据是空转的（拿真包当 pending 也一声不吭）")

    bad = [r for r in RESULTS if not r[1]]
    print("\n共 %d 条检查：PASS %d / FAIL %d" % (len(RESULTS), len(RESULTS) - len(bad), len(bad)))
    for label, _ok, detail in bad:
        print("  FAIL %s\n       %s" % (label, detail))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
