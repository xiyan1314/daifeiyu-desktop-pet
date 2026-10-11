# -*- coding: utf-8 -*-
"""官方内容插件验收（v2.5.1 · 代理 C）：正向 5 包 + 反向 22 条变异 + 索引自洽 + 幂等。

用法::

    python -B _dev/verify_plugin_packs_v251.py            # 全部检查，末尾打印 PASS/FAIL 计数
    python -B _dev/verify_plugin_packs_v251.py -v         # 每条都打印

证据口径
--------
* 正向：每个官方包都用**代理 A 的真校验器** pet_plugin.validate_plugin_zip 跑一遍（必须
  返回 (manifest, "")），再用本目录的参照实现（plugin_pack_rules）交叉跑一遍——两个引擎
  结论必须一致（A 未落地时只有参照实现，脚本会如实标注）。
* 反向：把真包**逐字节改一处**（少一条 files / 改一位 sha256 / 塞 .py / .. / 符号链接 /
  执行位 / BOM / 坏 JSON / ui / 越界 capability / 假 data_kind / 超版本门 / 2001 条目 …），
  每个变异都必须被拒——这就是"这些护栏能真失败"的证据。
* 索引：index.json 里每条 release 的 sha256/bytes/url 必须与磁盘上的包逐字节对得上；
  磁盘上的包与索引里的条目必须一一对应（多一个少一个都红）。
* 幂等：调 build_official_plugins.build() 打到临时目录，与 plugins/ 逐文件比较。
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
for p in (REPO, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import plugin_pack_rules as rules        # noqa: E402
import build_official_plugins as builder  # noqa: E402

PLUGINS = os.path.join(REPO, "plugins")
PACKS = os.path.join(PLUGINS, "packs")

RESULTS = []
VERBOSE = False


def check(label, ok, detail=""):
    RESULTS.append((label, bool(ok), detail))
    if VERBOSE or not ok:
        print("  [%s] %s%s" % ("PASS" if ok else "FAIL", label,
                               ("  —— %s" % detail) if detail else ""))
    return bool(ok)


def _engine_note():
    name, why = rules.engine_status()
    return "%s（%s）" % (name, why)


# ---------------- 变异用的小工具 ----------------

def _load_entries(path):
    return rules.read_entries(path)


def _url_ok(url, fn):
    """索引里的 url 合不合法（v2.5.1 参数化）：相对地址**恰好**是 packs/<文件名>；

    绝对地址（发布时 --base-url 重算成 GitHub Release 链接的那种）必须指向同名包——
    它对应磁盘上的同一个包本体（verify 仍然用 basename 去 packs/ 里核对哈希）。
    """
    text = str(url or "").strip().replace(chr(92), "/")
    if text == "packs/" + fn:
        return True
    return "://" in text and text.endswith("/" + fn) and fn in _packs_on_disk()


def _repack(src, dst, manifest=None, extra=(), drop=(), mode=None):
    """把 src 重写成 dst：manifest 替换（若给）/ 追加 extra / 丢掉 drop / 改某条目的权限位。

    mode=(条目名, 新 mode)：改 external_attr 的高 16 位（执行位 / 符号链接变异用）。
    """
    out = []
    for name, data, m in _load_entries(src):
        if name in drop:
            continue
        if name == rules.MANIFEST_NAME and manifest is not None:
            data = (manifest if isinstance(manifest, (bytes, bytearray))
                    else rules.dump_json_bytes(manifest))
        if mode is not None and name == mode[0]:
            m = mode[1]
        out.append((name, data, m))
    out.extend(extra)
    rules.write_zip(dst, out)
    return dst


def _packs_on_disk():
    if not os.path.isdir(PACKS):
        return []
    return sorted(f for f in os.listdir(PACKS) if f.endswith(builder.BUNDLE_EXT))


def _payload_names(path):
    """payload 下的**文件**条目（目录条目不参与 files 覆盖计数，与 A 的校验器同口径）。"""
    import zipfile
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
    root = rules.PAYLOAD_ROOT
    return sorted(n for n in names if n != rules.MANIFEST_NAME and not n.endswith("/")
                  and n.startswith(root))


def check_positive(host_ver):
    packs = _packs_on_disk()
    want = [p["id"] + "-" + builder.PACK_VERSION + builder.BUNDLE_EXT
            for p in builder.shipped_packs()]
    check("正向：磁盘上正好是打包工具声明的 %d 个上架包" % len(want), packs == sorted(want),
          "磁盘 %s / 声明 %s" % (packs, sorted(want)))
    field_bad = []
    for fn in packs:
        path = os.path.join(PACKS, fn)
        mf, err = rules.validate(path, host_ver)
        check("正向：%s 过校验器（%s）" % (fn, _engine_note()), mf is not None and err == "", err)
        ref_mf, ref_err = rules.validate_reference(path, host_ver)
        check("交叉核对：%s 两个引擎结论一致" % fn, (ref_mf is None) == (mf is None),
              "参照实现 err=%r" % (ref_err,))
        if mf is None:
            continue
        meta = mf.get("plugin") or {}
        top_dup = [k for k in ("id", "kind", "data_kind", "code", "capabilities",
                               "api_version", "min_host_version") if k in mf]
        for label, ok in (
                ("顶层 format", mf.get("format") == rules.PLUGIN_FORMAT),
                ("顶层 version 是 int 1", isinstance(mf.get("version"), int)
                 and not isinstance(mf.get("version"), bool) and mf.get("version") == 1),
                ("顶层 payload_root == payload/", mf.get("payload_root") == rules.PAYLOAD_ROOT),
                ("顶层没有插件元数据的重复键（单一真源）", not top_dup),
                ("plugin.kind == data", meta.get("kind") == "data"),
                ("plugin.code is False", meta.get("code") is False),
                ("plugin.capabilities == []", meta.get("capabilities") == []),
                ("plugin.api_version == 1", meta.get("api_version") == 1),
                ("plugin.min_host_version == 宿主版本", meta.get("min_host_version") == host_ver),
                ("plugin.data_kind 在 DATA_KINDS", meta.get("data_kind") in rules.host_data_kinds()),
                ("files 不多不少覆盖 payload", len(mf.get("files") or []) == len(_payload_names(path))),
                ("plugin.id 与文件名前缀一致", fn.startswith(str(meta.get("id")) + "-")),
        ):
            if not ok:
                field_bad.append("%s: %s" % (fn, label))
    check("正向：5 个包的字段口径（kind/code/capabilities/data_kind/单真源/files 覆盖）",
          not field_bad, "；".join(field_bad[:8]))


def check_install(host_ver):
    """上架门槛：每个上架包都必须能被**真安装器**装上；pending 的一律不许在磁盘上。

    这是比"过校验器"更硬的一道门——过校验器只说明包合法，这里说明用户真的装得上
    （走 pet_plugin_host.PluginHost.install_zip，与插件管理对话框同一条路径）。
    """
    shipped = sorted(p["id"] + "-" + builder.PACK_VERSION + builder.BUNDLE_EXT
                     for p in builder.shipped_packs())
    pending = sorted(p["id"] + "-" + builder.PACK_VERSION + builder.BUNDLE_EXT
                     for p in builder.PACKS if p.get("landing") != "ready")
    leaked = sorted(set(pending) & set(_packs_on_disk()))
    check("上架口径：landing=pending 的包一个都不在磁盘上（宁少勿假）", not leaked, str(leaked))
    check("上架口径：每个上架包都声明了 landing=ready",
          all(p.get("landing") == "ready"
              for p in builder.shipped_packs()), "有包没写 landing")
    try:
        import pet_behaviors
        import pet_lines
        import pet_plugin_host
        import pet_resources
    except Exception as e:
        check("上架门槛：真安装器可用（pet_plugin_host + 宿主库，Qt-free）", False, repr(e))
        return
    with tempfile.TemporaryDirectory(prefix="dfypet_verify_install_") as td:
        role_lib = pet_resources.RoleLibrary(td)
        lines_lib = pet_lines.LineService(td)
        audio_lib = pet_resources.AudioLibrary(td)
        behaviors = pet_behaviors.BehaviorService(td)
        host = pet_plugin_host.PluginHost(td, host_ver, role_lib=role_lib,
                                          lines_lib=lines_lib, audio_lib=audio_lib,
                                          behaviors=behaviors)
        bad = []
        for fn in shipped:
            ok, msg = host.install_zip(os.path.join(PACKS, fn), source_url="verify://")
            if not ok:
                bad.append("%s: %s" % (fn, msg))
        rows, problems = host.list_installed()
        n_roles, n_lines = len(role_lib.list_roles()), lines_lib.count()
        n_audio, n_beh = len(audio_lib.fragments()), len(behaviors.list())
        prompt_dir = os.path.join(td, "prompts", "custom")
        n_prompt = len([n for n in os.listdir(prompt_dir)
                        if n.lower().endswith(".txt")]) if os.path.isdir(prompt_dir) else 0
    check("上架门槛：%d 个上架包都能被 PluginHost.install_zip 装上" % len(shipped),
          not bad, "；".join(bad))
    check("上架门槛：装完 list_installed 看得到全部插件且无问题串",
          len(rows) == len(shipped) and not problems,
          "rows=%r problems=%r" % ([r.get("id") for r in rows], problems))
    check("上架门槛：装完宿主库真的多了东西（角色 %d / 台词 %d / 音效 %d / 行为 %d / 人设 %d）"
          % (n_roles, n_lines, n_audio, n_beh, n_prompt),
          n_roles >= 1 and n_lines >= 12 and n_audio >= 6 and n_beh >= 4 and n_prompt >= 1,
          "角色 %d / 台词 %d / 音效 %d / 行为 %d / 人设 %d"
          % (n_roles, n_lines, n_audio, n_beh, n_prompt))


def check_index(host_ver):
    path = os.path.join(PLUGINS, "index.json")
    if not os.path.isfile(path):
        check("索引：index.json 存在", False)
        return
    with open(path, "r", encoding="utf-8") as f:
        idx = json.load(f)
    check("索引：index_version == 1", idx.get("index_version") == 1, repr(idx.get("index_version")))
    check("索引：host_min == 宿主版本 %s" % host_ver, idx.get("host_min") == host_ver,
          repr(idx.get("host_min")))
    check("索引：updated_at 是日期串", bool(idx.get("updated_at")),
          repr(idx.get("updated_at")))
    plugins = idx.get("plugins")
    check("索引：plugins 是数组且条数 == 包数",
          isinstance(plugins, list) and len(plugins) == len(_packs_on_disk()),
          "%r" % (len(plugins) if isinstance(plugins, list) else plugins,))
    if not isinstance(plugins, list):
        return
    bad = []
    seen = set()
    for item in plugins:
        rels = item.get("releases")
        if not isinstance(rels, list) or not rels:
            bad.append("%s 没有 releases" % item.get("id"))
            continue
        for rel in rels:
            url = str(rel.get("url") or "")
            fn = url.rsplit("/", 1)[-1]
            seen.add(fn)
            # v2.5.1：url 口径参数化——相对地址必须恰好是 packs/<文件名>；发布时用
            # --base-url 重算过的绝对地址（https://…/v2.5.1/<文件名>）也认，只要它的
            # basename 命中磁盘上的同名包（本地校验的对象始终是那个包本体）。
            if not _url_ok(url, fn):
                bad.append("%s 的 url 既不是 packs/%s，也不是指向同名包的绝对地址：%r"
                           % (item.get("id"), fn, url))
            p = os.path.join(PACKS, fn)
            if not os.path.isfile(p):
                bad.append("索引里的包不在磁盘上：%s" % fn)
                continue
            if rules.sha256_file(p) != rel.get("sha256"):
                bad.append("%s 的 sha256 与包不符" % fn)
            if os.path.getsize(p) != rel.get("bytes"):
                bad.append("%s 的 bytes 与包不符" % fn)
            if rel.get("min_host_version") != idx.get("host_min"):
                bad.append("%s 的 min_host_version 与 host_min 不一致" % fn)
            if rules.ver_key(rel.get("min_host_version")) > rules.ver_key(host_ver):
                bad.append("%s 的 min_host_version 高于宿主" % fn)
            mf, err = rules.validate(p, host_ver)
            if mf is None:
                bad.append("%s 过不了校验器：%s" % (fn, err))
                continue
            meta = mf.get("plugin") or {}
            for key, got, want_v in (("id", meta.get("id"), item.get("id")),
                                     ("kind", meta.get("kind"), item.get("kind")),
                                     ("data_kind", meta.get("data_kind"), item.get("data_kind")),
                                     ("code", meta.get("code"), item.get("code")),
                                     ("version", str(meta.get("version")), str(rel.get("version")))):
                if got != want_v:
                    bad.append("%s 的 %s：索引 %r vs 包内 %r" % (fn, key, want_v, got))
    check("索引：每条 release 的 sha256/bytes/url/id/kind/data_kind/version 与包逐条一致",
          not bad, "；".join(bad[:8]))
    check("索引：磁盘上的包与索引条目一一对应", seen == set(_packs_on_disk()),
          "只在磁盘 %s / 只在索引 %s" % (sorted(set(_packs_on_disk()) - seen), sorted(seen - set(_packs_on_disk()))))


def check_trackable():
    """官方包必须能被 git 跟踪（.gitignore 的 *.zip 需要一条 ! 例外，否则发布门看不到它们）。"""
    ignored = []
    for fn in _packs_on_disk():
        r = subprocess.run(["git", "check-ignore", "-q",
                            os.path.join("plugins", "packs", fn)], cwd=REPO)
        if r.returncode == 0:
            ignored.append(fn)
    check("可提交：官方包没有被 .gitignore 忽略", not ignored, "被忽略：%s" % ignored)


def check_idempotent(host_ver, stamp, base_url):
    """复跑：临时重打一遍，与 plugins/ 逐字节相同。"""
    with tempfile.TemporaryDirectory(prefix="dfypet_verify_idem_") as td:
        builder.build(td, stamp, host_ver, base_url, quiet=True)
        diffs = builder._diff_dirs(PLUGINS, td)
    check("幂等：复跑产物与 plugins/ 逐字节相同", not diffs, "；".join(diffs[:6]))


def check_negatives(host_ver, tmp):
    """反向：每个变异都必须被拒（两个引擎都拒；点名类断言看真校验器的 err）。"""
    import copy
    import itertools

    base = os.path.join(PACKS, "official-lines-moyu-%s%s"
                        % (builder.PACK_VERSION, builder.BUNDLE_EXT))
    if not os.path.isfile(base):
        check("反向：基准包存在", False, base)
        return
    mf0 = rules.manifest_of(base)
    seq = itertools.count(1)

    def out(name):
        return os.path.join(tmp, "%02d_%s" % (next(seq), name))

    def expect(label, path, needle=()):
        if isinstance(needle, str):
            needle = (needle,)
        got, err = rules.validate(path, host_ver)
        rgot, rerr = rules.validate_reference(path, host_ver)
        detail = "err=%r" % (err,)
        if got is not None:
            detail = "真校验器**放行**了（%s）" % detail
            ok = False
        elif rgot is not None:
            detail = "参照实现放行了（err=%r）" % (rerr,)
            ok = False
        else:
            lack = [n for n in needle if n not in err]
            ok = not lack
            if lack:
                detail = "err 里没有 %r：%s" % (lack, detail)
        check("反向：%s 必须被拒%s" % (label, ("，且 err 点名 %s" % list(needle)) if needle else ""),
              ok, detail)

    def top(**kw):
        m = copy.deepcopy(mf0)
        m.update(kw)
        return m

    def meta(**kw):
        m = copy.deepcopy(mf0)
        m["plugin"].update(kw)
        return m

    def add_entry(m, path, data):
        m["files"].append({"path": path, "sha256": rules.sha256_bytes(data),
                           "bytes": len(data)})
        return [ (path, data) ]

    # ---- 判据 10：校验和 / 覆盖 ----
    m = copy.deepcopy(mf0)
    m["files"] = m["files"][:-1]
    expect("files 少一条（payload 有文件没进清单）",
           _repack(base, out("fewer.zip"), manifest=m), "没进 files")
    m = copy.deepcopy(mf0)
    h = m["files"][0]["sha256"]
    m["files"][0]["sha256"] = ("0" if h[0] != "0" else "1") + h[1:]
    expect("sha256 改一位", _repack(base, out("hash.zip"), manifest=m), m["files"][0]["path"])
    m = copy.deepcopy(mf0)
    m["files"][0]["bytes"] = int(m["files"][0]["bytes"]) + 1
    expect("bytes 改一位", _repack(base, out("bytes.zip"), manifest=m), m["files"][0]["path"])
    m = copy.deepcopy(mf0)
    m["files"].append({"path": "manifest.json", "sha256": "0" * 64, "bytes": 1})
    expect("files 多列了 manifest.json", _repack(base, out("mf_in_files.zip"), manifest=m),
           "manifest.json")
    expect("payload 多一个文件（不在 files 里）",
           _repack(base, out("extra.zip"), extra=[("payload/extra.txt", b"hi")]), "extra.txt")

    # ---- 判据 6：禁止项 / 白名单（点名文件） ----
    evil = b"print('owned')\n"
    m = copy.deepcopy(mf0)
    extra = add_entry(m, "payload/evil.py", evil)
    expect("payload 里塞 evil.py", _repack(base, out("evil.zip"), manifest=m, extra=extra),
           "evil.py")
    nest = b"PK\x05\x06" + b"\x00" * 18
    m = copy.deepcopy(mf0)
    extra = add_entry(m, "payload/nested.zip", nest)
    expect("payload 里塞嵌套压缩包 nested.zip",
           _repack(base, out("nested.zip"), manifest=m, extra=extra), "nested.zip")
    exe = b"MZ"
    m = copy.deepcopy(mf0)
    extra = add_entry(m, "payload/tool.exe", exe)
    expect("payload 里塞 tool.exe", _repack(base, out("exe.zip"), manifest=m, extra=extra),
           "tool.exe")

    # ---- 判据 4：路径安全 ----
    dot = b"x"
    m = copy.deepcopy(mf0)
    extra = add_entry(m, "payload/../escape.txt", dot)
    expect("条目名含 ..", _repack(base, out("dotdot.zip"), manifest=m, extra=extra), "..")
    # 注意：zipfile 在 Windows 上会把条目名里的反斜杠规范化成 "/"（ZipInfo.__init__），
    # 所以这条变异必须**构造后改写 filename** 才造得出来（否则造出来的是合法路径，测不到判据 4）
    bs = out("backslash.zip")
    with zipfile.ZipFile(bs, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data, mode_v in _load_entries(base):
            zi = zipfile.ZipInfo(name, rules.ZIP_DATE_TIME)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.create_system = 0
            zi.external_attr = (mode_v & 0xFFFF) << 16
            zf.writestr(zi, data, compresslevel=rules.ZIP_COMPRESSLEVEL)
        zi = zipfile.ZipInfo("payload/win.txt", rules.ZIP_DATE_TIME)
        zi.filename = "payload" + chr(92) + "win.txt"     # 真反斜杠
        zi.compress_type = zipfile.ZIP_DEFLATED
        zi.create_system = 0
        zi.external_attr = rules.ZIP_MODE << 16
        zf.writestr(zi, dot, compresslevel=rules.ZIP_COMPRESSLEVEL)
    got_bs, err_bs = rules.validate(bs, host_ver)
    ref_bs, _ref_err = rules.validate_reference(bs, host_ver)
    check("反向：条目名含反斜杠（真 zip）必须被拒",
          got_bs is None and ref_bs is None, "err=%r" % (err_bs,))
    with zipfile.ZipFile(bs) as zf_bs:
        seen = zf_bs.namelist()
    # 如实记录一个**不可达分支**：python 的 zipfile 在**读取**时就会把条目名里的 os.sep（\）
    # 规范化成 "/"（ZipInfo.__init__），Windows 上 namelist() 永远看不到反斜杠——所以上面
    # 那条真包是被判据 10（files 覆盖）拦下的，不是判据 4。判据 4 的反斜杠分支只能**单元级**核对。
    check("备注：真 zip 读回时反斜杠已被 zipfile 规范化（判据 4 该分支在 Windows 真包上不可达）",
          not any(chr(92) in n for n in seen), "读回 %r" % (seen,))
    import pet_plugin as _pp
    probe = "payload" + chr(92) + "win.txt"
    check("判据 4 反斜杠分支（单元级）：pet_plugin 与参照实现的判定函数都判为不安全",
          bool(_pp._unsafe_name_reason(probe)) and bool(rules._path_problem(probe)),
          "pet_plugin=%r / reference=%r" % (_pp._unsafe_name_reason(probe),
                                            rules._path_problem(probe)))

    # ---- 判据 2：manifest.json 本身 ----
    expect("manifest.json 带 BOM",
           _repack(base, out("bom.zip"), manifest=b"\xef\xbb\xbf" + rules.dump_json_bytes(mf0)),
           "BOM")
    expect("manifest.json 不是 UTF-8（GBK）",
           _repack(base, out("gbk.zip"), manifest=json.dumps(mf0, ensure_ascii=False).encode("gbk")),
           "UTF-8")
    expect("manifest.json 是坏 JSON", _repack(base, out("badjson.zip"), manifest=b"{ not json"),
           "解析")
    expect("包里没有 manifest.json",
           _repack(base, out("nomf.zip"), drop=(rules.MANIFEST_NAME,)), "缺少 manifest.json")
    notzip = out("notzip.zip")
    with open(notzip, "wb") as f:
        f.write(b"this is definitely not a zip")
    expect("根本不是 zip", notzip, "不是有效的 zip")

    # ---- 判据 3：format / 包格式版本 / plugin 段 ----
    expect('format="dfypet-role"', _repack(base, out("fmt.zip"), manifest=top(format="dfypet-role")),
           "插件包")
    expect("顶层 version=2", _repack(base, out("v2.zip"), manifest=top(version=2)), "格式版本")
    expect('顶层 version="1"（字符串，不是 int）',
           _repack(base, out("vstr.zip"), manifest=top(version="1")), "int")
    m = copy.deepcopy(mf0)
    m.pop("plugin")
    expect("缺 plugin 段", _repack(base, out("noplugin.zip"), manifest=m), "plugin")
    expect('payload_root 不以 / 结尾',
           _repack(base, out("root.zip"), manifest=top(payload_root="payload")), "payload_root")

    # ---- 判据 5：外部属性 ----
    victim = _payload_names(base)[0]        # 拿包里真实存在的第一个 payload 条目当变异对象
    expect("某 payload 条目带执行位（0o755）",
           _repack(base, out("execbit.zip"), mode=(victim, 0o755)), "执行位")
    expect("某条目是符号链接（0o120777）",
           _repack(base, out("symlink.zip"), mode=(victim, 0o120777)), "符号链接")

    # ---- 判据 7 / 12：kind / code / ui ----
    expect("kind=data 却 code=true", _repack(base, out("code.zip"), manifest=meta(code=True)),
           "code")
    expect("code=0（不是 bool）", _repack(base, out("codeint.zip"), manifest=meta(code=0)), "bool")
    expect("kind=ui（无条件拒）",
           _repack(base, out("ui.zip"), manifest=meta(kind="ui", code=True)), "UI")
    expect("kind=未知值", _repack(base, out("kind.zip"), manifest=meta(kind="shell")), "kind")

    # ---- 判据 8：capabilities ----
    expect("capabilities 越界 network",
           _repack(base, out("cap_net.zip"), manifest=meta(capabilities=["network"])), "network")
    expect("capabilities 越界 fx（不是合法 data_kind）",
           _repack(base, out("cap_fx.zip"), manifest=meta(capabilities=["fx"])), "fx")

    # ---- 判据 9：双版本门 ----
    expect("min_host_version=99.0.0（err 要点出要求与当前）",
           _repack(base, out("minhost.zip"), manifest=meta(min_host_version="99.0.0")),
           ("99.0.0", host_ver))
    expect("api_version=2", _repack(base, out("api2.zip"), manifest=meta(api_version=2)))

    # ---- 判据 11：data_kind ----
    expect('data_kind="fx"（本轮没有帧素材落地管线）',
           _repack(base, out("dk_fx.zip"), manifest=meta(data_kind="fx")), "fx")

    # ---- plugin.id 字符集 / Windows 保留名 ----
    expect("plugin.id 含空格", _repack(base, out("id_space.zip"), manifest=meta(id="official lines")),
           "id")
    expect("plugin.id 是 Windows 保留名（con）",
           _repack(base, out("id_con.zip"), manifest=meta(id="con")), "保留名")

    # ---- 判据 1：容量门（2001 个 payload 文件 + manifest = 2002 条目） ----
    big = [("payload/big/f%04d.txt" % i, b"x") for i in range(2001)]
    m = {"format": rules.PLUGIN_FORMAT, "version": 1, "payload_root": rules.PAYLOAD_ROOT,
         "files": [{"path": n, "sha256": rules.sha256_bytes(d), "bytes": len(d)}
                   for n, d in big],
         "plugin": copy.deepcopy(mf0["plugin"])}
    too = out("toomany.zip")
    rules.write_zip(too, [("manifest.json", rules.dump_json_bytes(m))] + big)
    expect("条目数超过 2000（zip 炸弹门）", too, "过多")

    # ---- 正例：目录条目（0o40775）**不算**违规（A 实测踩过的误拒） ----
    d = _repack(base, out("withdir.zip"), extra=[("payload/lines/", b"", 0o40775)])
    got, err = rules.validate(d, host_ver)
    check("正例：包内带目录条目（0o40775）仍然通过（目录条目不计入 files）",
          got is not None and err == "", err)


def main(argv=None):
    global VERBOSE
    ap = argparse.ArgumentParser(description="官方内容插件验收（正向 + 反向 + 索引 + 幂等）")
    ap.add_argument("-v", "--verbose", action="store_true", help="每条都打印（含 PASS）")
    ap.add_argument("--stamp", default=builder.DEFAULT_STAMP)
    ap.add_argument("--base-url", default=builder.DEFAULT_BASE_URL)
    ap.add_argument("--skip-negative", action="store_true")
    args = ap.parse_args(argv)
    VERBOSE = args.verbose
    host_ver = rules.host_version()
    print("宿主版本 %s · 校验引擎 %s" % (host_ver, _engine_note()))
    check_positive(host_ver)
    check_install(host_ver)
    check_index(host_ver)
    check_trackable()
    check_idempotent(host_ver, args.stamp, args.base_url)
    if not args.skip_negative:
        with tempfile.TemporaryDirectory(prefix="dfypet_verify_mut_") as tmp:
            check_negatives(host_ver, tmp)
    bad = [r for r in RESULTS if not r[1]]
    print("\n共 %d 条检查：PASS %d / FAIL %d" % (len(RESULTS), len(RESULTS) - len(bad), len(bad)))
    for label, _ok, detail in bad:
        print("  FAIL %s\n       %s" % (label, detail))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
