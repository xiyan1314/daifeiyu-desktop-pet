# -*- coding: utf-8 -*-
"""v2.5.1（代理 B）PetHub Phase 1：插件安装管线验收。

被测面：pet_plugin_host（安装 / 卸载 / 启用禁用 / 只读清单）+ pet_export.land_role
（从 import_bundle 抽出来的可复用落地函数）+ 桌宠.py 的一行接线与设置子菜单入口。

每条用例的 docstring 里都写了"拿掉什么它必须红"——即它**能真失败**。命令级反向证据
（B3⑥）在这里是**控制的控制组**：把校验器里"拒 .py"的两道门都拆掉之后，同一个 evil 包
必须真的装进来（否则"点名拒绝 evil.py"那条可能只是因为包里压根没带上那个文件）。

口径（与 Phase 0 的契约，写死在这里，漂了就红）：
· manifest 顶层只有 format / version / payload_root / files / created_at，插件元数据全在
  plugin 段；files=[{path, sha256, bytes}]，path 是**含 payload_root 前缀**的完整条目名；
· 安装登记 <数据目录>/plugins/_installed.json 的形状由本模块写、由读侧
  pet_plugin.read_installed 读——test_安装登记的形状与读取方约定一致 钉住这条契约。
"""
import copy
import hashlib
import io
import json
import os
import sys
import wave
import zipfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pet_behaviors    # noqa: E402
import pet_dialogs      # noqa: E402
import pet_export       # noqa: E402
import pet_lines        # noqa: E402
import pet_plugin       # noqa: E402
import pet_plugin_host  # noqa: E402
import pet_resources    # noqa: E402

HOST_VERSION = "2.5.0"

# 1x1 透明 PNG（真图，不是随便几个字节——将来若给落地加图片校验，这里不用改）
PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63f8cf00000301010018dd8db00000000049454e44ae426082")

_KEEP_ROLE = {"id": "keep1", "name": "原有角色", "file": "keep.png", "form": "single",
              "frames": ["keep.png"], "added": ""}


# ---------------- 造包（真实哈希；口子留给"必须被拒"的包） ----------------
def _plugin_zip(path, payload, *, pid="demo-role", data_kind="role", kind="data",
                code=False, min_host_version=HOST_VERSION, api_version=1, name=None,
                plugin_version="1.0.0", payload_root="payload/", capabilities=None,
                top_format="dfypet-plugin", top_version=1, plugin=True,
                files_filter=None, extra_entries=None):
    """造一个插件包 → 路径。payload: {payload 下的相对名: bytes}。

    files 清单由真实 sha256 / bytes 生成（不是抄来的常量）——清单与内容永远一致，
    于是"这个包被拒"只可能是**被判据拒绝**，不会是清单对不上。
    """
    entries = {"%s%s" % (payload_root, rel): data for rel, data in payload.items()}
    entries.update(extra_entries or {})
    files = [{"path": arc, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
             for arc, data in sorted(entries.items())]
    if files_filter is not None:
        files = files_filter(list(files))
    manifest = {"format": top_format, "version": top_version, "payload_root": payload_root,
                "files": files, "created_at": "2026-10-11T00:00:00"}
    if plugin:
        manifest["plugin"] = {"id": pid, "name": name or pid, "version": plugin_version,
                              "kind": kind, "data_kind": data_kind, "code": code,
                              "min_host_version": min_host_version,
                              "api_version": api_version,
                              "capabilities": list(capabilities or [])}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for arc, data in sorted(entries.items()):
            zf.writestr(arc, data)
    return path


def _role_payload(fname="demo_role.png", rid="demo", name="插件角色"):
    """角色类 payload：role.json + 它引用的 png（引用是 payload 内的相对名）。"""
    role = {"id": rid, "name": name, "file": fname, "form": "single",
            "frames": [fname], "added": ""}
    return {"role.json": json.dumps(role, ensure_ascii=False).encode("utf-8"), fname: PNG_1PX}


def _role_payload_ref(fname):
    """角色类 payload：引用一个**包里没有**的文件（落地阶段必须失败）。"""
    role = {"id": "demo", "name": "坏角色", "file": fname, "form": "single",
            "frames": [fname], "added": ""}
    return {"role.json": json.dumps(role, ensure_ascii=False).encode("utf-8")}


def _plugin_dir(tmp_path, pid):
    return tmp_path / "plugins" / pid


def _assert_no_residue(tmp_path, before=None):
    """plugins/ 下不留任何文件（目录根本不存在也算过——失败的安装连目录都不该建）。

    v2.5.1 审查 ⑦：只看 plugins/ 是不够的——落地失败真正会污染的是**宿主库**
    （lines.json / roles.json / roles/ / audio/ / prompts/custom/）。给 before（_snapshot
    的结果）时连那些地方一起比。
    """
    plugins = tmp_path / "plugins"
    assert not plugins.exists() or os.listdir(str(plugins)) == [], \
        "失败的安装在 plugins/ 下留了残余：%r" % (os.listdir(str(plugins)),)
    if before is not None:
        diff = _diff(before, _snapshot(tmp_path))
        assert diff == {}, "失败路径在宿主库 / 素材目录里留了残余：%r" % (diff,)


def _registry(tmp_path):
    path = tmp_path / "plugins" / "_installed.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _make_role_lib(data_dir, roles=None):
    """真角色库：先在磁盘上写好索引再让 RoleLibrary 读它（走真实读路径，不用 _data 注入）。"""
    os.makedirs(str(data_dir), exist_ok=True)
    (data_dir / "roles.json").write_text(
        json.dumps({"roles": list(roles or []), "active": ""}, ensure_ascii=False),
        encoding="utf-8")
    return pet_resources.RoleLibrary(str(data_dir))


@pytest.fixture()
def role_lib(tmp_path):
    return _make_role_lib(tmp_path, [_KEEP_ROLE])


@pytest.fixture()
def lines_lib(tmp_path):
    return pet_lines.LineService(str(tmp_path))


@pytest.fixture()
def host(tmp_path, role_lib, lines_lib):
    return pet_plugin_host.PluginHost(str(tmp_path), HOST_VERSION,
                                      role_lib=role_lib, lines_lib=lines_lib)


# ---------------- B3① 安装：目标库条目增加且原有内容一条不少 ----------------
def test_安装合法角色包_目标库条目增加且原有内容一条不少(tmp_path, host, role_lib):
    """B3①。变异：把 land_role 里的 append 换成"整体替换 roles"（或干脆不 append）→ 本条红。"""
    zip_path = _plugin_zip(str(tmp_path / "role.zip"), _role_payload())
    before = [dict(r) for r in role_lib.list_roles()]
    assert [r["id"] for r in before] == ["keep1"]

    ok, msg = host.install_zip(zip_path, source_url="https://example.invalid/role.zip")
    assert ok is True, msg
    assert "1 个角色" in msg, "安装结果没说清楚装进来了什么：%r" % (msg,)

    after = role_lib.list_roles()
    assert [r["id"] for r in after] == ["keep1", "demo"]
    assert after[0] == before[0], "原有角色被改动了：%r" % (after[0],)
    # 素材真落进了角色库目录，且角色引用的就是它（换新名防覆盖）
    landed = after[-1]
    assert landed["file"].endswith(".png") and landed["file"] != "demo_role.png"
    assert os.path.isfile(role_lib.resolve(landed["file"]))
    assert os.path.dirname(role_lib.resolve(landed["file"])) == str(tmp_path / "roles")
    # 插件目录：manifest.json 必须留下（读侧 read_installed 靠它列清单）
    assert (_plugin_dir(tmp_path, "demo-role") / "manifest.json").is_file()
    assert (_plugin_dir(tmp_path, "demo-role") / "payload" / "role.json").is_file()


# ---------------- B3② 装完卸载：条目仍在、插件目录已删 ----------------
def test_装完卸载_宿主库条目仍在但插件目录已删(tmp_path, host, role_lib):
    """B3②。变异：卸载时顺手把 landed 的角色也删掉 → 本条红（那是用户数据，同「导入角色包」口径）。"""
    zip_path = _plugin_zip(str(tmp_path / "role.zip"), _role_payload())
    assert host.install_zip(zip_path)[0] is True
    asset = role_lib.resolve(role_lib.list_roles()[-1]["file"])
    ids_after_install = [r["id"] for r in role_lib.list_roles()]

    ok, msg = host.uninstall("demo-role")
    assert ok is True and "保留" in msg, msg
    assert not _plugin_dir(tmp_path, "demo-role").exists(), "插件目录没删掉"
    assert [r["id"] for r in role_lib.list_roles()] == ids_after_install
    assert os.path.isfile(asset), "已落地的角色素材被卸载一起删了"
    assert "demo-role" not in _registry(tmp_path)["plugins"]


# ---------------- B3③ 版本门：拒绝且 plugins/ 下不留任何文件 ----------------
def test_版本门拒绝_原因带要求版本与当前版本_且不留任何文件(tmp_path, host):
    """B3③。变异：把 install_zip 里的"先校验后建目录"顺序对调（先 mkdir 再校验）→ 本条红。"""
    zip_path = _plugin_zip(str(tmp_path / "gate.zip"), _role_payload(),
                           pid="gate-1", min_host_version="99.0.0")
    ok, msg = host.install_zip(zip_path)
    assert ok is False, "版本门没拦住：%r" % (msg,)
    assert "99.0.0" in msg and HOST_VERSION in msg, "拒绝原因没给出版本号：%r" % (msg,)
    _assert_no_residue(tmp_path)


# ---------------- B3④ 含 evil.py：点名拒绝 ----------------
def test_含evil_py的包被点名拒绝(tmp_path, host):
    """B3④。变异：见下一条（把两道门拆掉它必须能被装上）——本条因此不是空转。"""
    zip_path = _plugin_zip(str(tmp_path / "evil.zip"), _role_payload(), pid="evil-1",
                           extra_entries={"payload/evil.py": b"print('pwned')"})
    ok, msg = host.install_zip(zip_path)
    assert ok is False, "含 .py 的包被装上了：%r" % (msg,)
    assert "evil.py" in msg, "拒绝原因没点名那个文件：%r" % (msg,)
    _assert_no_residue(tmp_path)


def test_反向_拆掉扩展名两道门之后同一个evil包会被装上(tmp_path, host, monkeypatch):
    """B3⑥（反向）。拆掉校验器里"拒 .py"的两道门 → **同一个包**必须能装进来。

    这条是上一条的控制的控制组：证明上一条的拒绝确实来自白名单/禁止项，而不是"包里根本
    没带上 evil.py"或"校验器先因别的原因炸了"。变异：把下面两行 monkeypatch 删掉 → 本条红。
    """
    zip_path = _plugin_zip(str(tmp_path / "evil2.zip"), _role_payload(), pid="evil-2",
                           extra_entries={"payload/evil.py": b"print('pwned')"})
    monkeypatch.setattr(pet_plugin, "FORBIDDEN_EXEC_EXTS", frozenset())
    monkeypatch.setattr(pet_plugin, "ALLOWED_EXTS",
                        frozenset(pet_plugin.ALLOWED_EXTS) | {".py"})
    ok, msg = host.install_zip(zip_path)
    assert ok is True, "拆掉两道门之后仍装不上（说明上一条堵的不是白名单）：%r" % (msg,)
    assert (_plugin_dir(tmp_path, "evil-2") / "payload" / "evil.py").is_file()


# ---------------- B3⑤ 重复安装：覆盖更新，不重复落地 ----------------
def test_重复安装同一包_覆盖更新且内容不重复落地(tmp_path, host, role_lib):
    """B3⑤。变异：覆盖分支里照样调 _land → 角色库里出现第二个「插件角色」→ 本条红。"""
    zip_path = _plugin_zip(str(tmp_path / "role.zip"), _role_payload())
    assert host.install_zip(zip_path)[0] is True
    ids_after_first = [r["id"] for r in role_lib.list_roles()]

    ok, msg = host.install_zip(zip_path, source_url="https://example.invalid/v2.zip")
    assert ok is True, msg
    assert "更新" in msg or "覆盖" in msg, "重复安装没有按「覆盖更新」处理：%r" % (msg,)
    assert [r["id"] for r in role_lib.list_roles()] == ids_after_first, "内容被重复落地了"
    reg = _registry(tmp_path)["plugins"]
    assert list(reg) == ["demo-role"], "登记表里出现了第二条：%r" % (list(reg),)
    assert reg["demo-role"]["source_url"] == "https://example.invalid/v2.zip"


def test_覆盖更新沿用禁用状态(tmp_path, host):
    """变异：覆盖时无条件把 enabled 写回 True → 本条红（用户禁用过的插件不该被更新悄悄打开）。"""
    zip_path = _plugin_zip(str(tmp_path / "role.zip"), _role_payload())
    assert host.install_zip(zip_path)[0] is True
    assert host.set_enabled("demo-role", False)[0] is True
    assert host.install_zip(zip_path)[0] is True
    assert _registry(tmp_path)["plugins"]["demo-role"]["enabled"] is False
    rows, _problems = host.list_installed()
    assert rows[0]["enabled"] is False


# ---------------- 写入方 / 读取方对同一个形状达成一致 ----------------
def test_安装登记的形状与读取方约定一致(tmp_path, host):
    """契约：本模块写 _installed.json，读侧是 Phase 0 的 read_installed —— 两处必须对得上。

    能真失败：把 format 改个名 / 把 plugins 换成一个 list / 把 enabled 挪进别的键 →
    下面任意一条断言红（读侧会拿不到 enabled，或整个表被当坏文件跳过）。
    """
    zip_path = _plugin_zip(str(tmp_path / "role.zip"), _role_payload())
    assert host.install_zip(zip_path, source_url="https://example.invalid/a.zip")[0] is True
    assert host.set_enabled("demo-role", False)[0] is True

    reg = _registry(tmp_path)
    assert reg["format"] == "dfypet-plugins-installed" and reg["version"] == 1
    rec = reg["plugins"]["demo-role"]
    for key in ("id", "name", "version", "kind", "data_kind", "source_url", "zip_sha256",
                "installed_at", "validated", "enabled", "landed"):
        assert key in rec, "安装登记缺字段 %s" % key
    assert len(rec["zip_sha256"]) == 64 and rec["validated"]["ok"] is True
    assert rec["landed"]["roles"], "没记下落地结果（卸载/更新时要用它）"

    rows, problems = pet_plugin.read_installed(str(tmp_path / "plugins"))
    assert problems == [], problems
    assert [r["id"] for r in rows] == ["demo-role"]
    assert rows[0]["enabled"] is False
    assert rows[0]["source_url"] == "https://example.invalid/a.zip"
    assert rows[0]["name"] == "demo-role" and rows[0]["data_kind"] == "role"


# ---------------- 启用 / 禁用：只改登记，文件不动，可逆 ----------------
def test_禁用只改登记不动文件_且可逆(tmp_path, host):
    """变异：set_enabled 顺手把插件目录改名/删掉 → 本条第一条断言红。"""
    zip_path = _plugin_zip(str(tmp_path / "role.zip"), _role_payload())
    assert host.install_zip(zip_path)[0] is True
    manifest_before = (_plugin_dir(tmp_path, "demo-role") / "manifest.json").read_bytes()

    ok, msg = host.set_enabled("demo-role", False)
    assert ok is True and "禁用" in msg, msg
    assert (_plugin_dir(tmp_path, "demo-role") / "manifest.json").read_bytes() == manifest_before
    assert _registry(tmp_path)["plugins"]["demo-role"]["enabled"] is False

    assert host.set_enabled("demo-role", True)[0] is True
    assert _registry(tmp_path)["plugins"]["demo-role"]["enabled"] is True


# ---------------- 失败路径：落地失败 / 校验失败都不留残余 ----------------
def test_落地失败_角色素材缺失_不留残余且宿主库一个字节不变(tmp_path, host, role_lib):
    """变异：把 _land_role 里"素材缺失直接返回错误"改成"跳过缺失文件继续落地" → 本条红。"""
    zip_path = _plugin_zip(str(tmp_path / "missing.zip"), _role_payload_ref("missing.png"),
                           pid="broken-1")
    before = [dict(r) for r in role_lib.list_roles()]
    ok, msg = host.install_zip(zip_path)
    assert ok is False and "missing.png" in msg, msg
    assert [dict(r) for r in role_lib.list_roles()] == before
    _assert_no_residue(tmp_path)
    roles_dir = tmp_path / "roles"
    assert not roles_dir.exists() or os.listdir(str(roles_dir)) == [], \
        "落地失败却在 roles/ 里留下了半截素材：%r" % (os.listdir(str(roles_dir)),)


def test_校验失败时连plugins目录都不建(tmp_path, host):
    """变异：把 install_zip 的 mkdir 提到校验之前 → 本条红（"不留残余"变成"留一个空目录"）。"""
    zip_path = _plugin_zip(str(tmp_path / "noplugin.zip"), _role_payload(), plugin=False)
    ok, msg = host.install_zip(zip_path)
    assert ok is False and "plugin" in msg, msg
    assert not (tmp_path / "plugins").exists()


def test_没有落地管线的kind明确拒绝并说明原因(tmp_path, host, monkeypatch):
    """两类"不能落地"都必须**明确拒绝 + 给原因 + 不留残余**，不许静默装上一个空插件：

    ① 这个 kind 压根不在 LANDING_KINDS 里（拿掉某类的落地管线时的形态）；
    ② kind 认识，但对应的宿主库没接线（例如宿主窗口还没建好 / 无 GUI）。
    变异：把 install_zip 里的 LANDING_KINDS 检查或 _land_* 的"库不可用"分支删掉 → 本条红。
    """
    zip_path = _plugin_zip(str(tmp_path / "audio.zip"), {"audio/coin.wav": b"RIFF....WAVEfmt "},
                           pid="audio-1", data_kind="audio")
    assert pet_plugin.validate_plugin_zip(zip_path, HOST_VERSION)[0] is not None, \
        "前提：这个包本身必须是通过 Phase 0 校验的合法包"

    monkeypatch.setattr(pet_plugin_host, "LANDING_KINDS", ("role", "lines"))
    ok, msg = host.install_zip(zip_path)
    assert ok is False and "audio" in msg and "不支持" in msg, msg
    _assert_no_residue(tmp_path)

    monkeypatch.undo()
    ok2, msg2 = host.install_zip(zip_path)      # 这一类认识，但 host 夹具没接线音效库
    assert ok2 is False and "audio" in msg2 and "不可用" in msg2, msg2
    _assert_no_residue(tmp_path)


def test_安装包不存在或为空路径给人话错误(tmp_path, host):
    """空路径 / 不存在的路径 / 传了个目录：都必须返回 (False, 人话)，绝不抛。

    校正（v2.5.1 质量审查，实测）：本条的变异**不是**"删掉 install_zip 里的 isfile 检查"——
    那样做仍会被人话错误兜住（校验器自己会拒：打开失败 / 不是有效的 zip 包），用例照样全绿，
    旧 docstring 自称的"会抛 BadZipFile"是错的。它真正钉住的是**入口契约**：这两个函数在
    任何输入下都不许把异常抛给调用方（对话框与将来的下载安装都直接调它们）。
    能真失败：去掉 install_zip 里 `if manifest is None: return False` 那一跳（或让校验器
    的 try/except 不再兜底）→ 传目录时会 AttributeError 冒出去，红。
    """
    for bad in ("", None, str(tmp_path / "nope.zip"), str(tmp_path)):
        ok, msg = host.install_zip(bad)
        assert ok is False and isinstance(msg, str) and msg, (bad, ok, msg)


def test_卸载与启停未安装的插件给人话错误(tmp_path, host):
    """变异：把"未安装"分支删掉（直接 rmtree / 直接写登记）→ 本条静默成功或抛异常，红。"""
    assert host.uninstall("nope")[0] is False
    assert host.set_enabled("nope", False)[0] is False
    assert host.uninstall("")[0] is False and host.set_enabled("../escape", True)[0] is False


# ---------------- 清单：坏目录 / 坏 JSON 只跳过不抛 ----------------
def test_清单_坏目录与坏JSON只跳过不抛(tmp_path, host):
    """变异：list_installed 里去掉防御（让异常冒出去）→ 对话框打不开 → 本条红。"""
    zip_path = _plugin_zip(str(tmp_path / "role.zip"), _role_payload())
    assert host.install_zip(zip_path)[0] is True
    plugins = tmp_path / "plugins"
    (plugins / "stray.txt").write_text("not a plugin", encoding="utf-8")   # 普通文件
    (plugins / "broken").mkdir()                                           # 没有 manifest.json
    (plugins / "badjson").mkdir()
    (plugins / "badjson" / "manifest.json").write_text("{ not json", encoding="utf-8")

    rows, problems = host.list_installed()
    assert [r["id"] for r in rows] == ["demo-role"], rows
    assert any("broken" in p for p in problems), problems
    assert any("badjson" in p for p in problems), problems

    (plugins / "_installed.json").write_text("{ not json", encoding="utf-8")
    rows2, _problems2 = host.list_installed()          # 登记坏了也不许抛
    assert [r["id"] for r in rows2] == ["demo-role"]
    assert rows2[0]["enabled"] is True                  # 登记读不到 → 缺省启用


def test_id的写入方自保_绕过校验器也拦得住(tmp_path, host, monkeypatch):
    """校验器已经挡住坏 id；这里 stub 掉校验器，证明**写入方自保**（_safe_id）真的在拦。

    变异：把 _safe_id 的调用换成直接用 manifest 里的 id 拼路径 → 会建出 plugins/../../…
    """
    zip_path = _plugin_zip(str(tmp_path / "ok.zip"), _role_payload())
    monkeypatch.setattr(pet_plugin, "validate_plugin_zip", lambda path, host_version: (
        {"format": "dfypet-plugin", "version": 1, "payload_root": "payload/", "files": [],
         "plugin": {"id": "../../escape", "kind": "data", "data_kind": "role",
                    "code": False}}, ""))
    ok, msg = host.install_zip(zip_path)
    assert ok is False and "id" in msg, msg
    assert not (tmp_path.parent / "escape").exists()
    assert not (tmp_path / "plugins").exists()


def test_safe_id的字符集与保留名(tmp_path):
    """直测第二道门：空 / 太长 / 带分隔符 / 点结尾 / 保留名 / 下划线开头一律 ""。"""
    good = ("a", "official-lines-basic", "A.b_c-1", "x" * 64)
    bad = ("", " ", ".", "..", "a/b", "a\\b", "a.", "_hidden", "a b", "x" * 65,
           "../escape", "C:evil", "目录")
    for pid in good:
        assert pet_plugin_host._safe_id(pid) == pid, pid
    for pid in bad:
        assert pet_plugin_host._safe_id(pid) == "", pid


# ---------------- 台词类落地 ----------------
def test_台词包落地_原有台词一条不少(tmp_path, host, lines_lib):
    """变异：_land_lines 里把 lines_lib.add 换成"重建整个台词库" → 原有台词全丢，本条红。"""
    before = {ln["id"]: ln["text"] for ln in lines_lib.lines()}
    assert before, "前提：台词库里本来就有内置台词（否则「一条不少」是空断言）"
    payload = {"lines.json": json.dumps(
        {"lines": [{"text": "插件台词一", "category": "idle"}, "插件台词二"]},
        ensure_ascii=False).encode("utf-8")}
    zip_path = _plugin_zip(str(tmp_path / "lines.zip"), payload, pid="lines-1", data_kind="lines")

    ok, msg = host.install_zip(zip_path)
    assert ok is True and "2 条台词" in msg, msg
    after = {ln["id"]: ln["text"] for ln in lines_lib.lines()}
    assert len(after) == len(before) + 2
    for lid, text in before.items():
        assert after.get(lid) == text, "原有台词被改动了：%s" % lid
    assert "插件台词一" in after.values() and "插件台词二" in after.values()
    assert _registry(tmp_path)["plugins"]["lines-1"]["landed"]["lines"], "没记下落地结果"


def test_台词包内容非法时拒绝且不留残余(tmp_path, host, lines_lib):
    """变异：把 _lines_items 的空结果分支删掉（空表也当成功装上）→ 本条红。"""
    payload = {"lines.json": json.dumps({"lines": []}, ensure_ascii=False).encode("utf-8")}
    zip_path = _plugin_zip(str(tmp_path / "empty.zip"), payload, pid="lines-2",
                           data_kind="lines")
    count_before = lines_lib.count()
    ok, msg = host.install_zip(zip_path)
    assert ok is False and "台词" in msg, msg
    assert lines_lib.count() == count_before
    _assert_no_residue(tmp_path)


# ---------------- pet_export.land_role：抽出来的落地函数本身 ----------------
def test_land_role_错误文案逐字不变且内存索引回滚(tmp_path):
    """抽取的兼容承诺：错误文案与旧版 import_bundle 内联那段**逐字相同**。

    变异：把文案改成"角色保存失败"之类 → 本条红（调用方与既有用例依赖那些字面量）。
    """
    class _BadLib(object):
        def __init__(self):
            self._data = {"roles": []}

        def get(self, rid):
            return None

        def _save(self):
            return "boom"

    lib = _BadLib()
    role = {"id": "x", "name": "x", "file": "a.png"}
    rid, err = pet_export.land_role(lib, role)
    assert rid is None and err == "保存角色失败：boom", (rid, err)
    assert lib._data["roles"] == [], "写索引失败后内存索引没回滚"
    assert role["added"] == "", "added 归一化丢了"


def test_land_role_id冲突换新_不覆盖现有角色(tmp_path):
    """变异：冲突时直接 append（不换 id）→ 角色库里出现两个同 id 条目，本条红。"""
    lib = _make_role_lib(tmp_path, [_KEEP_ROLE])
    rid, err = pet_export.land_role(lib, {"id": "keep1", "name": "同名角色",
                                          "file": "b.png", "form": "single",
                                          "frames": ["b.png"], "added": ""})
    assert err == "" and rid and rid != "keep1", (rid, err)
    ids = [r["id"] for r in lib.list_roles()]
    assert ids[0] == "keep1" and len(ids) == 2


def test_落地类别与校验器的DATA_KINDS一致_且每类都有落点():
    """两个方向都钉住：① 安装器声称支持的类别必须是校验器放行的（别越过 Phase 0 自己发明）；
    ② 每一类都得有**自己的**落地函数（不是掉进"本版本不支持"那条统一拒绝）。

    能真失败：把 _land 分派表里的某个 handler 删掉 → 那一类的端到端用例与本条同时红；
    DATA_KINDS 里加了新类别而没落后，本条不会红（那是"少做一类"而不是"假装支持"），
    但 pet_plugin_host.LANDING_KINDS 一旦写上校验器不认的类别 → ① 立刻红。
    """
    assert set(pet_plugin_host.LANDING_KINDS) <= set(pet_plugin.DATA_KINDS), \
        "安装器声称支持了校验器不认识的类别：%r" % sorted(
            set(pet_plugin_host.LANDING_KINDS) - set(pet_plugin.DATA_KINDS))
    host = pet_plugin_host.PluginHost("")        # 只测分派，不碰磁盘
    missing = []
    for kind in pet_plugin_host.LANDING_KINDS:
        landed, err = host._land(kind, os.path.join(os.sep, "no_such_payload_dir"))
        if landed != {} or not err or "不支持落地" in err:
            missing.append((kind, landed, err))
    assert missing == [], "这些类别没有自己的落点（掉进了统一拒绝）：%r" % (missing,)


# ---------------- 宿主接线 + 菜单入口（真 PetWindow） ----------------
@pytest.fixture(scope="module")
def pet_window(tmp_path_factory):
    """真 PetWindow（照 tests/test_dialog_fit_v250.py 的隔离套路：先改路径常量再构造）。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import pet_log
    from PySide6.QtWidgets import QApplication

    tmp = tmp_path_factory.mktemp("pluginhost251")
    import 桌宠 as main
    snap = (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
            getattr(pet_log, "_data_dir", None))
    main.DATA_DIR = str(tmp)
    main.CONFIG_PATH = str(tmp / "config.json")
    main.USAGE_PATH = str(tmp / "usage.json")
    main.MEMORY_PATH = str(tmp / "memory.json")
    pet_log.set_data_dir(str(tmp))
    QApplication.instance() or QApplication([])
    win = main.PetWindow()
    win._plugin_test_data_dir = str(tmp)
    try:
        yield win
    finally:
        try:
            win._closing = True
            win.voice.stop()
        except Exception:
            pass
        from PySide6.QtCore import QTimer
        for timer in win.findChildren(QTimer):
            try:
                timer.stop()
            except Exception:
                pass
        try:
            win.hide()
            win.close()
            win.deleteLater()
        except Exception:
            pass
        QApplication.processEvents()
        (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH) = snap[:4]
        pet_log.set_data_dir(snap[4])


# ---------------- 六类落地：装 → 原有不变 → 卸载后已落地资产仍在 ----------------
# 每一类都用**真宿主库**（真 AudioLibrary / VoiceAssetLibrary / BehaviorService / 角色库 /
# 台词库）+ 真落地接口跑一遍；"原有内容"在安装前先由各自的真接口建起来（不是伪造的索引条目）。
def _wav_bytes(ms=60):
    """一段合法的最小 WAV（AudioLibrary / VoiceAssetLibrary 会校验头，随便几个字节过不去）。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * int(8000 * ms / 1000))
    return buf.getvalue()


_BEHAVIOR = {"id": "ab12cd34", "name": "plugin_wave",
             "steps": [{"act": "wait", "ms": 200}, {"act": "say", "text": "插件行为"}]}


def _lines_pack():
    data = {"lines": [{"key": "k1", "text": "插件台词一", "category": "idle"},
                      {"key": "k2", "text": "插件台词二", "category": "happy"}],
            "dialogues": [{"name": "插件对白", "lines": ["k1", "k2"]}]}
    return {"lines.json": json.dumps(data, ensure_ascii=False).encode("utf-8")}


_KIND_CASES = {
    "role": {
        "payload": _role_payload,
        "seed": lambda t: _make_role_lib(t, [_KEEP_ROLE]),
        "landed": lambda t: os.path.isfile(
            pet_resources.RoleLibrary(str(t)).resolve(
                pet_resources.RoleLibrary(str(t)).list_roles()[-1]["file"])),
        "existing": lambda t: [r["id"] for r in pet_resources.RoleLibrary(str(t)).list_roles()
                               ][0] == "keep1",
    },
    "lines": {
        "payload": _lines_pack,
        "seed": lambda t: pet_lines.LineService(str(t)).add("原有台词", "idle"),
        "landed": lambda t: "插件台词一" in [x["text"] for x in
                                             pet_lines.LineService(str(t)).lines()],
        "existing": lambda t: "原有台词" in [x["text"] for x in
                                             pet_lines.LineService(str(t)).lines()],
    },
    "audio": {
        "payload": lambda: {"audio/coin.wav": _wav_bytes(),
                            "audio/pack.json": json.dumps(
                                {"files": {"audio/coin.wav": "金币音"},
                                 "slots": {"coin": "coin.wav"}}).encode("utf-8")},
        "seed": lambda t: pet_resources.AudioLibrary(str(t)).import_file(
            _write_wav(t / "seed_audio.wav"), name="原有音效"),
        "landed": lambda t: "金币音" in [f["name"] for f in
                                         pet_resources.AudioLibrary(str(t)).fragments()],
        "existing": lambda t: "原有音效" in [f["name"] for f in
                                             pet_resources.AudioLibrary(str(t)).fragments()],
    },
    "voice_ref": {
        "payload": lambda: {"voice_ref/v.wav": _wav_bytes()},
        "seed": lambda t: pet_resources.VoiceAssetLibrary(str(t)).import_file(
            _write_wav(t / "seed_voice.wav"), name="原有参考音"),
        "landed": lambda t: len(pet_resources.VoiceAssetLibrary(str(t)).assets()) == 2,
        "existing": lambda t: "原有参考音" in [a["name"] for a in
                                               pet_resources.VoiceAssetLibrary(str(t)).assets()],
    },
    "behaviors": {
        "payload": lambda: {"behaviors/one.json": json.dumps(
            {"behavior": _BEHAVIOR}, ensure_ascii=False).encode("utf-8")},
        "seed": lambda t: pet_behaviors.BehaviorService(str(t)).add(
            "existing_beh", [{"act": "wait", "ms": 100}]),
        "landed": lambda t: "plugin_wave" in [b["name"] for b in
                                              pet_behaviors.BehaviorService(str(t)).list()],
        "existing": lambda t: "existing_beh" in [b["name"] for b in
                                                 pet_behaviors.BehaviorService(str(t)).list()],
    },
    "prompt": {
        "payload": lambda: {"prompts/插件人设.txt": "你是插件带来的毒舌大肥鱼".encode("utf-8")},
        "seed": lambda t: _seed_prompt(t, "原有人设"),
        "landed": lambda t: (t / "prompts" / "custom" / "插件人设.txt").is_file(),
        "existing": lambda t: (t / "prompts" / "custom" / "原有人设.txt").is_file(),
    },
}


def _write_wav(path):
    path.write_bytes(_wav_bytes())
    return str(path)


def _seed_prompt(tmp_path, name):
    target = tmp_path / "prompts" / "custom"
    target.mkdir(parents=True, exist_ok=True)
    (target / (name + ".txt")).write_text("原有", encoding="utf-8")


@pytest.mark.parametrize("kind", sorted(_KIND_CASES))
def test_六类落地端到端_装成功_原有内容不变_卸载后已落地资产仍在(tmp_path, kind):
    """六类（role / lines / audio / voice_ref / behaviors / prompt）各走一遍真接口。

    一条用例钉三件事：①装完真的并进了宿主库 ②原有的那一条没被动过（"插件不许改用户已有的
    东西"）③卸载只删插件目录、已落地资产仍在（用户数据）。
    变异：任一 _land_* 改成"清空宿主库再写"→ ②红；卸载顺手删掉落地内容 → ③红。
    """
    case = _KIND_CASES[kind]
    case["seed"](tmp_path)
    libs = {"role_lib": pet_resources.RoleLibrary(str(tmp_path)),
            "lines_lib": pet_lines.LineService(str(tmp_path)),
            "audio_lib": pet_resources.AudioLibrary(str(tmp_path)),
            "voice_assets": pet_resources.VoiceAssetLibrary(str(tmp_path)),
            "behaviors": pet_behaviors.BehaviorService(str(tmp_path))}
    host = pet_plugin_host.PluginHost(str(tmp_path), HOST_VERSION, **libs)
    assert case["existing"](tmp_path), "前提：安装前「原有内容」必须在（否则②是空断言）"

    zip_path = _plugin_zip(str(tmp_path / ("%s.zip" % kind)), case["payload"](),
                           pid="kind-%s" % kind, data_kind=kind)
    ok, msg = host.install_zip(zip_path)
    assert ok is True, "%s 类落地失败：%s" % (kind, msg)
    assert case["landed"](tmp_path), "%s 类没有真的并进宿主库" % kind
    assert case["existing"](tmp_path), "%s 类把宿主原有的内容改掉了" % kind

    ok, msg = host.uninstall("kind-%s" % kind)
    assert ok is True and "保留" in msg, msg
    assert not _plugin_dir(tmp_path, "kind-%s" % kind).exists()
    assert case["landed"](tmp_path), "%s 类：卸载把已落地的资产一起删了" % kind


def test_音效插件不动用户的音效组槽位(tmp_path):
    """C 的产品口径：包里只有"建议槽位"，**安装器不采纳**——用户现有的槽位选择不许被插件改。

    变异：_land_media 里顺手 set_slot（按 pack.json 的 slots 写）→ 本条红。
    """
    data_dir = tmp_path
    audio_lib = pet_resources.AudioLibrary(str(data_dir))
    before = audio_lib.group_slots()
    host = pet_plugin_host.PluginHost(str(data_dir), HOST_VERSION, audio_lib=audio_lib)
    payload = {"audio/coin.wav": _wav_bytes(),
               "audio/pack.json": json.dumps(
                   {"files": {"audio/coin.wav": "金币音"},
                    "slots": {"coin": "coin.wav", "press": "coin.wav"}}).encode("utf-8")}
    zip_path = _plugin_zip(str(data_dir / "a.zip"), payload, pid="slot-1", data_kind="audio")
    assert host.install_zip(zip_path)[0] is True
    assert audio_lib.group_slots() == before, "插件改了用户的音效组槽位"


def test_prompt插件不许覆盖用户已有的人设文件(tmp_path):
    """变异：_land_prompt 里去掉"同名就拒"（直接覆盖写）→ 本条红（用户人设被插件吃掉）。"""
    _seed_prompt(tmp_path, "我的毒舌版")
    host = pet_plugin_host.PluginHost(str(tmp_path), HOST_VERSION)
    payload = {"prompts/我的毒舌版.txt": "插件想覆盖".encode("utf-8")}
    zip_path = _plugin_zip(str(tmp_path / "p.zip"), payload, pid="p-1", data_kind="prompt")
    ok, msg = host.install_zip(zip_path)
    assert ok is False and "已存在" in msg, msg
    assert (tmp_path / "prompts" / "custom" / "我的毒舌版.txt").read_text(
        encoding="utf-8") == "原有"
    _assert_no_residue(tmp_path)


def test_行为id不合法时整条拒绝且原有行为一条不少(tmp_path):
    """C 踩过的坑：行为条目必须自带 8 位小写 hex id，否则 _norm_behavior 整条判非法。

    变异：把 _land_behaviors 的错误分支改成"跳过坏条目继续"（静默少导入）→ 本条红。
    """
    data_dir = tmp_path
    svc = pet_behaviors.BehaviorService(str(data_dir))
    svc.add("existing_beh", [{"act": "wait", "ms": 100}])
    before = [(b["id"], b["name"]) for b in svc.list()]
    host = pet_plugin_host.PluginHost(str(data_dir), HOST_VERSION, behaviors=svc)
    bad = dict(_BEHAVIOR)
    bad["id"] = "NOTHEX12"
    zip_path = _plugin_zip(str(data_dir / "b.zip"),
                           {"behaviors.json": json.dumps({"behaviors": [bad]},
                                                         ensure_ascii=False).encode("utf-8")},
                           pid="b-bad", data_kind="behaviors")
    ok, msg = host.install_zip(zip_path)
    assert ok is False and "行为" in msg, msg
    assert [(b["id"], b["name"]) for b in svc.list()] == before
    _assert_no_residue(tmp_path)


def test_role插件带标准角色包时走既有导入管线(tmp_path):
    """role 的两种 payload 都认：标准角色包（payload/manifest.json + payload/roles/*.png）
    走 pet_export.import_bundle（换新文件名、冲突换 id 全由它负责）。

    变异：把 _land_role 里的"有 manifest.json 就走 bundle"分支删掉 → 本条红。
    """
    role = {"id": "bundleRole", "name": "包内角色", "file": "r1.png", "form": "single",
            "frames": ["r1.png"], "added": ""}
    bundle = {"format": pet_export.BUNDLE_FORMAT, "version": 1, "meta": {}, "role": role,
              "behaviors": [], "config": {}, "excluded": [], "alarms": None, "lines": None,
              "dialogues": None, "voice_assets": None}
    payload = {"manifest.json": json.dumps(bundle, ensure_ascii=False).encode("utf-8"),
               "roles/r1.png": PNG_1PX}
    lib = _make_role_lib(tmp_path, [_KEEP_ROLE])
    host = pet_plugin_host.PluginHost(str(tmp_path), HOST_VERSION, role_lib=lib)
    zip_path = _plugin_zip(str(tmp_path / "r.zip"), payload, pid="bundle-1", data_kind="role")
    ok, msg = host.install_zip(zip_path)
    assert ok is True, msg
    roles = lib.list_roles()
    assert [r["id"] for r in roles] == ["keep1", "bundleRole"]
    assert os.path.isfile(lib.resolve(roles[-1]["file"]))
    assert roles[-1]["file"] != "r1.png", "素材没有换新名（防覆盖失效）"


def test_桌宠接线_插件宿主挂在窗口上且落在数据目录下(pet_window):
    """B2 的"一行接线"。变异：把 __init__ 里那行删掉 → 本条红（对话框只能靠兜底自建）。"""
    host = getattr(pet_window, "plugin_host", None)
    assert isinstance(host, pet_plugin_host.PluginHost), host
    assert host.plugins_dir == os.path.join(pet_window._plugin_test_data_dir, "plugins")
    assert host.list_installed() == ([], [])


def test_对话框安装卸载走真宿主_且列表自动刷新(pet_window, tmp_path, monkeypatch):
    """对话框四个动作都委托宿主（装 / 卸 / 启用禁用 / 刷新），列表跟着刷新。

    走的是**真 PetWindow 上那个 plugin_host**（= 一行接线的产物）+ 真角色库（惰性取路径），
    所以同时钉住：接线的宿主能用、对话框不自己造一套逻辑。
    变异：install_path 里不调宿主（或去掉 refresh）→ 列表里看不到装进来的插件，本条红。
    """
    shots = []
    monkeypatch.setattr(pet_dialogs, "_info",
                        lambda *a, **k: shots.append(("info", a[1] if len(a) > 1 else "")))
    monkeypatch.setattr(pet_dialogs, "_warn",
                        lambda *a, **k: shots.append(("warn", a[1] if len(a) > 1 else "")))
    dlg = pet_dialogs.PluginManagerDialog(pet_window)
    try:
        zip_path = _plugin_zip(str(tmp_path / "role.zip"), _role_payload(), pid="dlg-1")
        assert dlg.install_path(zip_path) is True

        def _ids():
            return [dlg._table.item(i, 0).text() for i in range(dlg._table.rowCount())]

        assert "dlg-1" in _ids(), "装完列表没刷新（看不到刚装的插件）"
        assert dlg.set_enabled_id("dlg-1", False) is True
        assert dlg._table.item(_ids().index("dlg-1"), 4).text() == "已禁用"
        assert dlg.uninstall_id("dlg-1") is True
        assert "dlg-1" not in _ids(), "卸完列表没刷新"
        assert [k for k, _t in shots].count("info") == 3, shots
    finally:
        dlg.close()


def test_prompt落地后主程序自己的人设清单真的认得(pet_window):
    """端到端：插件装进去的人设，必须出现在**主程序自己的**人设发现结果里。

    这是 prompt 类落地的真判据（不是"文件写到某个目录"）：pet_plugin_host 不能 import
    桌宠.py，只能镜像 prompts/custom 这个口径——所以这里直接问主程序
    persona_file_ids()，它认得才算真的落地。变异：把 PROMPTS_DIRNAME 改成别的名字
    （或落到 prompts/ 而不是 prompts/custom/）→ 本条红。
    """
    import 桌宠 as main
    assert pet_plugin_host.PROMPTS_DIRNAME == main.PROMPTS_DIRNAME, \
        "两处的 prompts 目录名漂了（本模块不能 import 桌宠.py，只能镜像）"
    data_dir = pet_window._plugin_test_data_dir
    before = set(main.persona_file_ids())
    host = pet_plugin_host.PluginHost(data_dir, HOST_VERSION)
    payload = {"prompts/插件人设A.txt": "你是插件带来的大肥鱼".encode("utf-8")}
    zip_path = _plugin_zip(os.path.join(data_dir, "prompt_e2e.zip"), payload,
                           pid="p-e2e", data_kind="prompt")
    ok, msg = host.install_zip(zip_path)
    assert ok is True, msg
    assert "file:插件人设A" in (set(main.persona_file_ids()) - before), \
        "主程序的人设清单没认到插件装进来的人设"


def test_菜单入口在设置子菜单里_顶层项数不超上限(pet_window):
    """B2 的菜单口径。变异：把入口从设置子菜单挪到顶层 → 顶层项数超上限、本条红。"""
    from PySide6.QtCore import QPoint
    import 桌宠 as main

    class _Menu(main.QMenu):
        def exec(self, *_a, **_k):
            self._captured = self.actions()
            return None

    real_menu = main.QMenu
    main.QMenu = _Menu
    captured = {}
    try:
        pet_window._open_menu(QPoint(100, 100))
        import gc
        for obj in gc.get_objects():
            if isinstance(obj, _Menu) and getattr(obj, "_captured", None) is not None:
                captured = obj
                break
    finally:
        main.QMenu = real_menu
    assert captured, "没抓到菜单对象（stub 失效）"

    def _texts(actions):
        out = []
        for act in actions:
            if act.text():
                out.append(act.text())
            sub = act.menu()
            if sub is not None:
                out.extend(_texts(sub.actions()))
        return out

    top = [a.text() for a in captured._captured if a.text()]
    assert len(top) <= 18, "顶层菜单项超上限（v13 的硬断言）：%d 项" % len(top)
    assert "🧩 插件管理…" not in top, "插件入口跑到顶层菜单去了（必须在设置子菜单里）"
    assert "🧩 插件管理…" in _texts(captured._captured), "菜单里没有插件入口"
    settings = [a for a in captured._captured if a.text().startswith("⚙️")]
    assert settings, "没找到设置子菜单"
    names = [a.text() for a in settings[0].menu().actions()]
    assert "🧩 插件管理…" in names, names

# ============ v2.5.1 审查修复（P1-1 / P1-2 / P2-1…P2-4 / P3-2 / S1-a…S1-c）============
# 这一段的每条用例都在 docstring 里写了"拿掉什么它必须红"。P1-1 / P1-2 是**实测事故**：
# 一个完全合法的包就能删掉官方内容包目录 / 让角色库在随后任何一次 get() 抛 KeyError。

# ============ v2.5.1 质量审查：承重承诺与回滚路径的灵敏度补齐 ============

def test_插件不许改用户配置_可分享配置只喂深拷贝(tmp_path):
    """承重承诺（质量审查实测：deepcopy 换成 dict(live) 后 36 条全绿——没人盯这条）。

    构造：用户 cfg 里 voice.bindings 绑着 plugRole；包内角色 id 也叫 plugRole 且与现有角色
    冲突（land_role 会换新 id）→ import_bundle 会把 bindings 重指成新 id。深拷贝时用户那份
    原样不动；浅拷贝（dict(live)）时嵌套的 voice 字典是**同一个对象** → 用户配置被就地改写。

    能真失败：把 install_zip 里的 copy.deepcopy(live) 换成 dict(live) → 下面的 cfg 断言红。
    """
    lib = _make_role_lib(tmp_path, [{"id": "plugRole", "name": "用户角色", "file": "keep.png",
                                    "form": "single", "frames": ["keep.png"], "added": ""}])
    live = {"voice": {"bindings": {"plugRole": "v1"}}, "sound_group": "custom"}
    before = copy.deepcopy(live)

    class _Pet(object):
        cfg = live

    host = pet_plugin_host.PluginHost(str(tmp_path), HOST_VERSION, _Pet(), role_lib=lib)
    role = {"id": "plugRole", "name": "包内同名角色", "file": "r1.png", "form": "single",
            "frames": ["r1.png"], "added": ""}
    bundle = {"format": pet_export.BUNDLE_FORMAT, "version": 1, "meta": {}, "role": role,
              "behaviors": [], "config": {}, "alarms": None, "lines": None,
              "dialogues": None, "voice_assets": None}
    payload = {"manifest.json": json.dumps(bundle, ensure_ascii=False).encode("utf-8"),
               "roles/r1.png": PNG_1PX}
    ok, msg = host.install_zip(_plugin_zip(str(tmp_path / "cfg.zip"), payload, pid="cfg-1",
                                          data_kind="role"))
    assert ok is True, msg
    assert live == before, "插件把用户的实时配置改了：%r" % (live,)
    assert [r["id"] for r in lib.list_roles()][0] == "plugRole", "用户角色被覆盖/改名了"


def test_对白引用了包里没有的台词_整包回滚(tmp_path):
    """回滚路径（质量审查点名：拿掉后 36 条全绿）：dialogues 引用了 lines 里不存在的 key →
    已经并进台词库的那几条必须逐条撤销，不留"半包"。

    能真失败：去掉 _rollback_lines 的调用（或只回滚对白不回滚台词）→ 红。
    """
    lines_lib = pet_lines.LineService(str(tmp_path))
    host = pet_plugin_host.PluginHost(str(tmp_path), HOST_VERSION, lines_lib=lines_lib)
    data = {"lines": [{"key": "k1", "text": "甲"}, {"key": "k2", "text": "乙"}],
            "dialogues": [{"name": "坏对白", "lines": ["k1", "不存在"]}]}
    payload = {"lines.json": json.dumps(data, ensure_ascii=False).encode("utf-8")}
    before = [x["id"] for x in lines_lib.lines()]
    zip_path = _plugin_zip(str(tmp_path / "dlg.zip"), payload, pid="dlg-bad", data_kind="lines")
    ok, msg = host.install_zip(zip_path)
    assert ok is False and "坏对白" in msg, msg
    assert [x["id"] for x in lines_lib.lines()] == before, "失败后台词没回滚"
    assert "甲" not in [x["text"] for x in lines_lib.lines()]
    _assert_no_residue(tmp_path)


def test_对白导入失败_已进库的台词逐条回滚(tmp_path):
    """回滚路径：add_dialogue 失败时，前面已经加进去的台词必须逐条撤销（不能只撤对白）。
    用薄包装把真 LineService 的 add_dialogue 换成"必失败"，其余照旧 → 走真库、真回滚。

    能真失败：去掉 _rollback_lines(lines_lib, added, made) 里对台词的撤销 → 红。
    """
    real = pet_lines.LineService(str(tmp_path))

    class _FailDialogue(object):
        def add(self, *a, **k):
            return real.add(*a, **k)

        def add_dialogue(self, *a, **k):
            return None, "模拟对白入库失败"

        def delete(self, *a, **k):
            return real.delete(*a, **k)

        def delete_dialogue(self, *a, **k):
            return real.delete_dialogue(*a, **k)

        def lines(self, *a, **k):
            return real.lines(*a, **k)

    host = pet_plugin_host.PluginHost(str(tmp_path), HOST_VERSION, lines_lib=_FailDialogue())
    before = [x["id"] for x in real.lines()]
    zip_path = _plugin_zip(str(tmp_path / "dlgfail.zip"), _lines_pack(), pid="dlgfail",
                           data_kind="lines")
    ok, msg = host.install_zip(zip_path)
    assert ok is False and "对白导入失败" in msg, msg
    assert [x["id"] for x in real.lines()] == before, "对白失败后台词没回滚"
    _assert_no_residue(tmp_path)


def test_role素材写到一半失败_已写文件删干净(tmp_path, monkeypatch):
    """回滚路径：payload 引用两张 png，拷第二张时失败 → 第一张必须删掉，roles/ 不留半截。

    能真失败：去掉 _land_role_dict 里 _remove_files(written) 那一跳 → 红。
    """
    lib = _make_role_lib(tmp_path, [])
    host = pet_plugin_host.PluginHost(str(tmp_path), HOST_VERSION, role_lib=lib)
    role = {"id": "half", "name": "半截角色", "file": "a1.png", "form": "single",
            "frames": ["a1.png", "a2.png"], "added": ""}
    payload = {"role.json": json.dumps(role, ensure_ascii=False).encode("utf-8"),
               "a1.png": PNG_1PX, "a2.png": PNG_1PX}
    zip_path = _plugin_zip(str(tmp_path / "half.zip"), payload, pid="half-1")
    before = _snapshot(tmp_path)
    real_copy = pet_plugin_host.shutil.copyfile
    calls = {"n": 0}

    def _fail_second(src, dst, *a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("模拟第二张写失败")
        return real_copy(src, dst, *a, **k)

    monkeypatch.setattr(pet_plugin_host.shutil, "copyfile", _fail_second)
    ok, msg = host.install_zip(zip_path)
    assert ok is False and "写入角色素材失败" in msg, msg
    assert [r["id"] for r in lib.list_roles()] == []
    assert _diff(before, _snapshot(tmp_path)) == {}, "roles/ 里留了半截素材"


def test_目录名与manifest_id不一致时_读侧与清单侧口径一致(tmp_path):
    """第四优先（质量审查实测）：把 plugins/<目录>/manifest.json 的 plugin.id 改成别的名字
    （手工拷进来、或后来改过 id）→ 此前读侧按**目录名**查登记表、清单侧按 **manifest id**
    合并：登记按 manifest id 存时读侧会丢掉 enabled/source_url，登记按目录名存时清单侧会把
    同一个目录列成**两行**（用户看到"装了两个插件"）。

    能真失败：去掉 read_installed 的按 id 回查兜底 / 去掉 list_installed 的"该目录已有行"判断。
    """
    plugins = tmp_path / "plugins"
    d = plugins / "drifty-dir"
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps(
        {"format": "dfypet-plugin", "version": 1, "payload_root": "payload/", "files": [],
         "plugin": {"id": "totally-other-id", "name": "漂移包", "version": "1.0.0",
                    "kind": "data", "data_kind": "lines", "code": False,
                    "min_host_version": HOST_VERSION, "api_version": 1, "capabilities": []}},
        ensure_ascii=False), encoding="utf-8")

    # ① 登记按 manifest id 存 → 读侧必须回查到 enabled / source_url
    (plugins / "_installed.json").write_text(json.dumps(
        {"format": "dfypet-plugins-installed", "version": 1,
         "plugins": {"totally-other-id": {"enabled": False,
                                          "source_url": "https://example.invalid/d.zip"}}},
        ensure_ascii=False), encoding="utf-8")
    rows, problems = pet_plugin.read_installed(str(plugins))
    assert problems == [] and len(rows) == 1, (rows, problems)
    assert rows[0]["id"] == "totally-other-id"
    assert rows[0]["enabled"] is False, "按 manifest id 存的登记没被回查到"
    assert rows[0]["source_url"] == "https://example.invalid/d.zip"

    # ② 登记按目录名存 → 清单侧不许把同一个目录列成两行
    (plugins / "_installed.json").write_text(json.dumps(
        {"format": "dfypet-plugins-installed", "version": 1,
         "plugins": {"drifty-dir": {"enabled": True, "source_url": ""}}},
        ensure_ascii=False), encoding="utf-8")
    host = pet_plugin_host.PluginHost(str(tmp_path), HOST_VERSION)
    listed, probs = host.list_installed()
    assert probs == [], probs
    assert len(listed) == 1, "同一个目录被列成了多行：%r" % ([r["id"] for r in listed],)
    assert listed[0]["id"] == "totally-other-id"


def test_role_json没有任何素材引用要拒(tmp_path):
    """边界（质量审查点名无用例）：role.json 里没有可用素材引用（也没有合法 id）→ 必须拒绝，
    绝不能"装成一个没有图的坏角色"。

    能真失败：去掉 _land_role_dict 的 id 判据与归一化那道门 → 会落一条裸条目，红。
    """
    lib = _make_role_lib(tmp_path, [_KEEP_ROLE])
    host = pet_plugin_host.PluginHost(str(tmp_path), HOST_VERSION, role_lib=lib)
    for i, role in enumerate(({"id": "no-media", "name": "没图的"},
                              {"id": "no-media", "name": "空引用", "file": "", "frames": []})):
        payload = {"role.json": json.dumps(role, ensure_ascii=False).encode("utf-8")}
        zip_path = _plugin_zip(str(tmp_path / ("nm%d.zip" % i)), payload, pid="nm-1")
        ok, msg = host.install_zip(zip_path)
        assert ok is False and msg, msg
        assert [r["id"] for r in lib.list_roles()] == ["keep1"]


def test_prompt没有可用人设文件与audio空包都给人话错误(tmp_path):
    """边界（质量审查点名无用例）：人设包里一个 .txt 都没有 / 音频包里一个音频都没有 →
    明确拒绝 + 不留残余（"任何一种 kind 在 payload 里找不到对应文件就拒绝"那条口径）。

    能真失败：去掉 _land_prompt / _land_media 的那两条判据 → 会静默装一个空插件，红。
    （人设文件名去空白后为空那条分支留着当防御，但走 _iter_files 构造不出来——
    .txt 的基名不可能为空，所以这里钉的是可达的那一条。）
    """
    host = pet_plugin_host.PluginHost(
        str(tmp_path), HOST_VERSION,
        audio_lib=pet_resources.AudioLibrary(str(tmp_path)))    # 库要接线，才轮到"包里没音频"
    cases = (("p-none", "prompt", {"prompts/readme.md": b"#"}, "没有任何"),
             ("a-none", "audio", {"audio/readme.txt": b"x"}, "没有任何"))
    for pid, kind, payload, want in cases:
        zip_path = _plugin_zip(str(tmp_path / ("%s.zip" % pid)), payload, pid=pid,
                               data_kind=kind)
        before = _snapshot(tmp_path)
        ok, msg = host.install_zip(zip_path)
        assert ok is False and want in msg, (pid, msg)
        assert _diff(before, _snapshot(tmp_path)) == {}, "%s 失败却留了残余" % pid


def test_登记里有但目录里没manifest_清单仍然列得出来(tmp_path):
    """registry-only 分支（质量审查点名无用例）：目录在、登记里有这条，但 manifest.json 坏了
    ——读侧只会报一句"缺 manifest.json"，此时清单必须还能靠**登记**把那一条列出来，
    否则用户装过一个坏掉的插件，界面上它就凭空消失了。

    能真失败：去掉 list_installed 里"登记里有、目录也在 → 补一行"那段 → 清单为空，红。
    """
    d = tmp_path / "plugins" / "brokenpack"
    d.mkdir(parents=True)
    (d / "half.txt").write_text("x", encoding="utf-8")
    (tmp_path / "plugins" / "_installed.json").write_text(json.dumps(
        {"format": "dfypet-plugins-installed", "version": 1,
         "plugins": {"brokenpack": {"id": "brokenpack", "name": "坏包", "enabled": False}}},
        ensure_ascii=False), encoding="utf-8")
    host = pet_plugin_host.PluginHost(str(tmp_path), HOST_VERSION)
    rows, problems = host.list_installed()
    assert [r["id"] for r in rows] == ["brokenpack"], rows
    assert any("manifest.json" in p for p in problems), problems     # 读侧如实报问题
    assert rows[0]["enabled"] is False


def _shipped_layout(tmp_path):
    """把仓库 plugins/（= 出货布局：index.json + README.md + packs/5 个包）整个当数据目录的 plugins/。

    这是用户拿到绿色版时的真实布局——官方内容仓库就在插件目录里。
    """
    import shutil as _sh
    dst = tmp_path / "plugins"
    _sh.copytree(os.path.join(ROOT, "plugins"), str(dst))
    return dst


def _snapshot(root):
    """数据目录的全量快照（相对路径 → 内容指纹；目录记 "dir"）。

    比 _assert_no_residue 严的地方：落地失败真正会污染的是**宿主库**（lines.json /
    roles.json / roles/ / prompts/custom/…），而"半截目录"根本不会出现在文件清单里。
    """
    out = {}
    base = str(root)
    for cur, _dirs, names in os.walk(base):
        rel = os.path.relpath(cur, base)
        if rel != ".":
            out[rel.replace(os.sep, "/") + "/"] = "dir"
        for n in names:
            p = os.path.join(cur, n)
            key = os.path.relpath(p, base).replace(os.sep, "/")
            try:
                with open(p, "rb") as f:
                    out[key] = hashlib.sha256(f.read()).hexdigest()[:12]
            except OSError:
                out[key] = "?"
    return out


def _diff(before, after):
    return {k: (before.get(k), after.get(k)) for k in set(before) | set(after)
            if before.get(k) != after.get(k)}


# ---------------- P1-1：保留名 packs（官方内容包目录）不许被插件顶掉 ----------------
def test_P1_1_出货布局上装_packs_必须拒绝且官方内容原样(tmp_path):
    """P1-1（实测事故）：plugin.id="packs" 在 pet_plugin 的字符集里完全合法；出货布局里
    plugins/packs/ 就是官方内容包目录 → 装它会把整个官方目录 rmtree 再换成插件目录，
    还返回 ok=True「已更新插件『packs』」（内容其实一条不落地）。官方 5 个包必须一个不少。

    能真失败：去掉校验器 _id_problem 里那道保留名判据与安装器的 _reserved_problem → 红。
    """
    plugins = _shipped_layout(tmp_path)
    before = sorted(os.listdir(str(plugins / "packs")))
    assert len(before) == 5, before
    host = pet_plugin_host.PluginHost(str(tmp_path), HOST_VERSION,
                                      role_lib=_make_role_lib(tmp_path, [_KEEP_ROLE]))
    zip_path = _plugin_zip(str(tmp_path / "evil.zip"), _role_payload(), pid="packs")
    ok, msg = host.install_zip(zip_path)
    assert ok is False and "保留名" in msg, msg
    assert sorted(os.listdir(str(plugins / "packs"))) == before, "官方内容包目录被插件替换了"
    for name in ("index.json", "README.md"):
        assert (plugins / name).is_file(), "%s 没了" % name
    assert not (plugins / "packs" / "manifest.json").exists()


def test_P1_1_写入方自保_绕过校验器也拦得住_packs(tmp_path, monkeypatch):
    """第二道门（写入方自保）：stub 掉校验器（假装别的版本 / 被绕过的校验器）→ 安装器
    自己也必须拦住 packs。能真失败：去掉 install_zip 里的 _reserved_problem → 官方目录被替换。
    """
    plugins = _shipped_layout(tmp_path)
    before = sorted(os.listdir(str(plugins / "packs")))
    monkeypatch.setattr(pet_plugin, "validate_plugin_zip", lambda path, host_version: (
        {"format": "dfypet-plugin", "version": 1, "payload_root": "payload/", "files": [],
         "plugin": {"id": "packs", "kind": "data", "data_kind": "role", "code": False}}, ""))
    host = pet_plugin_host.PluginHost(str(tmp_path), HOST_VERSION,
                                      role_lib=_make_role_lib(tmp_path, [_KEEP_ROLE]))
    zip_path = _plugin_zip(str(tmp_path / "evil.zip"), _role_payload(), pid="packs")
    ok, msg = host.install_zip(zip_path)
    assert ok is False and "保留名" in msg, msg
    assert sorted(os.listdir(str(plugins / "packs"))) == before


def test_P1_1_卸载_packs_必须拒绝且官方内容原样(tmp_path):
    """P1-1 卸载侧（实测）：干净布局上 uninstall("packs") 此前返回 ok=True 并删掉官方内容包
    目录、连备份都没有。大小写不同（Windows/macOS 同一个目录）也必须拒。

    能真失败：去掉 uninstall 里的 _reserved_problem → 官方目录被删。
    """
    plugins = _shipped_layout(tmp_path)
    before = sorted(os.listdir(str(plugins / "packs")))
    host = pet_plugin_host.PluginHost(str(tmp_path), HOST_VERSION)
    ok, msg = host.uninstall("packs")
    assert ok is False and "保留名" in msg, msg
    assert host.uninstall("PACKS")[0] is False
    assert host.set_enabled("packs", False)[0] is False
    assert sorted(os.listdir(str(plugins / "packs"))) == before
    assert not (tmp_path / "plugins" / "_installed.json").exists(), "还写了登记"


def test_P1_1_目标目录没有manifest且不在登记表里_拒绝覆盖(tmp_path):
    """P1-1 第二道保险：保留名只挡得住已知的那几个名字；用户自己放在 plugins/ 下的东西
    只能靠"目标目录没有 manifest.json 且登记里没这条 → 拒绝覆盖"。

    能真失败：去掉 install_zip 里 os.path.exists(target) 那条判断 → 用户文件被 rmtree。
    """
    plugins = tmp_path / "plugins"
    (plugins / "my-stuff").mkdir(parents=True)
    (plugins / "my-stuff" / "重要文件.txt").write_text("别删我", encoding="utf-8")
    host = pet_plugin_host.PluginHost(str(tmp_path), HOST_VERSION,
                                      role_lib=_make_role_lib(tmp_path, [_KEEP_ROLE]))
    zip_path = _plugin_zip(str(tmp_path / "p.zip"), _role_payload(), pid="my-stuff")
    ok, msg = host.install_zip(zip_path)
    assert ok is False and "不是一个插件目录" in msg, msg
    assert (plugins / "my-stuff" / "重要文件.txt").read_text(encoding="utf-8") == "别删我"
    assert not (plugins / "my-stuff" / "manifest.json").exists()


# ---------------- P1-2：role.json 缺 id → 拒绝，不许往角色库里塞毒条目 ----------------
def test_P1_2_role_json缺id必须拒绝_且角色库零残留(tmp_path):
    """P1-2（实测事故）：payload/role.json 少一个 id → 装成功，roles.json 里留下一条无 id
    裸条目 → 随后**任何** role_lib.get() / delete() 都 r["id"] → KeyError（桌宠启动路径就会
    走到），重启时 _normalize_role 又把它丢掉，只剩 roles/ 里的孤儿 png。

    能真失败：去掉 _land_role_dict 里的 id 判据（或去掉归一化那道门）→ "拒绝"断言红；
    只清一半（素材没回滚）→ 快照断言红。
    """
    lib = _make_role_lib(tmp_path, [_KEEP_ROLE])
    host = pet_plugin_host.PluginHost(str(tmp_path), HOST_VERSION, role_lib=lib)
    role = {"name": "没有 id 的角色", "file": "noid.png", "form": "single",
            "frames": ["noid.png"], "added": ""}
    payload = {"role.json": json.dumps(role, ensure_ascii=False).encode("utf-8"),
               "noid.png": PNG_1PX}
    zip_path = _plugin_zip(str(tmp_path / "noid.zip"), payload, pid="noid-1")
    before = _snapshot(tmp_path)                    # 快照含刚造的包（它本来就该在盘上）
    ok, msg = host.install_zip(zip_path)
    assert ok is False and "id" in msg, msg
    assert _diff(before, _snapshot(tmp_path)) == {}, "拒绝安装却留下了残余"
    assert [r["id"] for r in lib.list_roles()] == ["keep1"]
    assert lib.get("keep1") is not None and lib.get("") is None    # get() 正常工作
    assert host.uninstall("noid-1")[0] is False                    # 没装成


def test_P1_2_role_json落地前归一_重启读回来还是同一只(tmp_path):
    """P1-2 的"更稳"那一半：落地前先过角色库自己的 _normalize_role —— 落进去的形状必须
    就是重启读回来的形状（旧字段升级成 forms/…），不留"重启即消失"的条目。

    能真失败：去掉 _land_role_dict 里的 normalize 调用 → roles.json 里缺 forms/v2 等归一字段，红。
    """
    lib = _make_role_lib(tmp_path, [_KEEP_ROLE])
    host = pet_plugin_host.PluginHost(str(tmp_path), HOST_VERSION, role_lib=lib)
    ok, msg = host.install_zip(_plugin_zip(str(tmp_path / "r.zip"),
                                           _role_payload("demo_role.png", rid="norm1",
                                                         name="归一角色"),
                                           pid="norm-1"))
    assert ok is True, msg
    raw = json.loads((tmp_path / "roles.json").read_text(encoding="utf-8"))["roles"]
    entry = [r for r in raw if r.get("id") == "norm1"]
    assert len(entry) == 1, raw
    for key in ("forms", "frames", "form", "v2"):
        assert key in entry[0], "落地的角色缺归一化字段 %s：%r" % (key, sorted(entry[0]))
    again = pet_resources.RoleLibrary(str(tmp_path))      # 重启：重新读盘
    assert again.get("norm1") is not None, "重启后这只角色被读侧丢掉了"


def test_P1_2_role_json归一不通过也拒绝(tmp_path):
    """归一化是道门，不是装饰：只写了 forms、没有顶层 file 的条目，**角色库读回来时就会
    丢掉它**（_normalize_role 返回 None）——这种包直接拒，别落一条重启即消失的孤儿。

    能真失败：把归一化结果 None 的检查去掉 → 装成功但重启后角色消失，红。
    """
    lib = _make_role_lib(tmp_path, [_KEEP_ROLE])
    host = pet_plugin_host.PluginHost(str(tmp_path), HOST_VERSION, role_lib=lib)
    role = {"id": "forms-only", "name": "只有 forms",
            "forms": [{"name": "常态", "file": "f1.png",
                       "animations": {"idle": ["f1.png"]}}]}
    payload = {"role.json": json.dumps(role, ensure_ascii=False).encode("utf-8"),
               "f1.png": PNG_1PX}
    zip_path = _plugin_zip(str(tmp_path / "fo.zip"), payload, pid="fo-1")
    before = _snapshot(tmp_path)
    ok, msg = host.install_zip(zip_path)
    assert ok is False and "归一化" in msg, msg
    assert _diff(before, _snapshot(tmp_path)) == {}, "拒绝安装却留下了残余"


# ---------------- P2-1：没落地的内容必须出现在成功文案里 ----------------
def test_P2_1_role包里没落地的东西必须让用户看见(tmp_path):
    """P2-1 / S1-d（实测）：role 插件（标准角色包布局）里的台词 / 参考音 / 闹钟走的是
    "当前版本尚未支持，已忽略"分支，这些警告此前只躺在 _installed.json 里 → 界面永远看不到，
    用户只看到「并导入 1 个角色」，以为全进来了。

    能真失败：去掉 install_zip 里的 _warn_tail(_landed_warnings(landed))（或不让
    _land_role_bundle 记 warnings）→ "没有导入"断言红。
    """
    lib = _make_role_lib(tmp_path, [_KEEP_ROLE])
    host = pet_plugin_host.PluginHost(str(tmp_path), HOST_VERSION, role_lib=lib)
    bundle = {"format": pet_export.BUNDLE_FORMAT, "version": 1, "meta": {},
              "role": {"id": "wr1", "name": "带料角色", "file": "w1.png", "form": "single",
                       "frames": ["w1.png"], "added": ""},
              "behaviors": [], "config": {},
              "alarms": [{"time": "09:00", "text": "起床"}],
              "lines": [{"id": "L1", "text": "包内台词", "category": "idle"}],
              "dialogues": [],
              "voice_assets": [{"id": "V1", "name": "包内参考音", "file": "voice_ref/v1.wav"}]}
    payload = {"manifest.json": json.dumps(bundle, ensure_ascii=False).encode("utf-8"),
               "roles/w1.png": PNG_1PX,
               "voice_ref/v1.wav": _wav_bytes()}
    zip_path = _plugin_zip(str(tmp_path / "w.zip"), payload, pid="warn-1", data_kind="role")
    ok, msg = host.install_zip(zip_path)
    assert ok is True, msg
    assert "并导入 1 个角色" in msg, msg
    assert "没有导入" in msg and "台词" in msg and "闹钟" in msg and "声音素材" in msg, msg
    reg = _registry(tmp_path)["plugins"]["warn-1"]
    assert len(reg["landed"]["warnings"]) >= 3, reg["landed"]
    assert reg["landed"]["roles"], reg["landed"]


# ---------------- P2-3：同 id 换 data_kind = 另一个插件，明确拒绝 ----------------
def test_P2_3_同id换data_kind必须拒绝_不许报已更新(tmp_path):
    """P2-3（实测）：先装 id=p-same 的 lines 包、再装 id=p-same 的 role 包 → 此前 ok=True
    「已更新…内容不重复导入」、roles 0→0，登记里的 data_kind 被改成 role 而 landed 还是旧账。

    能真失败：去掉 install_zip 里那条 data_kind 比较 → 第二段（拒绝 + 登记不变）红。
    """
    lines_lib = pet_lines.LineService(str(tmp_path))
    lib = _make_role_lib(tmp_path, [])
    host = pet_plugin_host.PluginHost(str(tmp_path), HOST_VERSION, role_lib=lib,
                                      lines_lib=lines_lib)
    first = _plugin_zip(str(tmp_path / "a.zip"), _lines_pack(), pid="p-same", data_kind="lines")
    assert host.install_zip(first)[0] is True
    n_lines = len(lines_lib.lines())
    second = _plugin_zip(str(tmp_path / "b.zip"), _role_payload(), pid="p-same", data_kind="role")
    ok, msg = host.install_zip(second)
    assert ok is False and "已装为" in msg, msg
    assert lib.list_roles() == [], "拒绝安装却落地了角色"
    assert len(lines_lib.lines()) == n_lines
    reg = _registry(tmp_path)["plugins"]["p-same"]
    assert reg["data_kind"] == "lines", "登记里的 data_kind 被改掉了"
    assert reg["landed"].get("lines")


# ---------------- P2-4 / S1-c：登记表才是"已装"的依据 ----------------
def test_P2_4_登记表才是已装的依据_登记没了就重新落地(tmp_path):
    """P2-4（实测）：装完插件后删掉 plugins/（模拟"照 README 迁移清单拷贝"漏了它）→ 再装
    同一包会重复进库；而**只删 _installed.json**（目录还在）时更糟：此前报"已更新…内容已
    落地"、landed 却是空表 = 装了个空壳还报成功（S1-c）。

    这里钉住两条口径：① 登记在 → 覆盖更新、不重复落地；② 登记没了 → **照常落地**、如实说
    装了什么，绝不说"内容已落地"。

    能真失败：把 already 的判据改回 known is not None or os.path.isdir(target) → ② 红。
    """
    lines_lib = pet_lines.LineService(str(tmp_path))
    host = pet_plugin_host.PluginHost(str(tmp_path), HOST_VERSION, lines_lib=lines_lib)
    zip_path = _plugin_zip(str(tmp_path / "l.zip"), _lines_pack(), pid="p4", data_kind="lines")
    assert host.install_zip(zip_path)[0] is True
    base = len(lines_lib.lines())
    ok, msg = host.install_zip(zip_path)                      # ① 同一个包 + 登记在
    assert ok is True and "覆盖旧版本" in msg, msg
    assert "不是同一个文件" not in msg, "同一个包却提示内容变了：%r" % (msg,)
    assert len(lines_lib.lines()) == base

    os.remove(str(tmp_path / "plugins" / "_installed.json"))  # ② 登记被抹掉（目录还在）
    ok, msg = host.install_zip(zip_path)
    assert ok is True, msg
    assert "覆盖旧版本" not in msg, "登记没了还说覆盖更新：%r" % (msg,)
    assert len(lines_lib.lines()) == base + 2, "登记没了却没重新落地（空壳）"
    assert _registry(tmp_path)["plugins"]["p4"]["landed"]["lines"], "登记没有重建落地账"


def test_S1_c_手工拷进来的插件目录_装同id的真包必须真的落地(tmp_path):
    """S1-c（实测）：手工把插件目录拷进 plugins/<id>/（set_enabled 明确支持这个场景，会补一条
    登记）→ 再装同 id 的真包，此前 ok=True「已更新…（内容在首次安装时已落地）」而 landed={}、
    台词一条没进 = 装了个空壳还报成功。

    能真失败：让 already 只看"登记里有这条"（不看 landed 是否有内容）→ 内容不落地，红。
    """
    lines_lib = pet_lines.LineService(str(tmp_path))
    host = pet_plugin_host.PluginHost(str(tmp_path), HOST_VERSION, lines_lib=lines_lib)
    d = tmp_path / "plugins" / "hand"
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps(
        {"format": "dfypet-plugin", "version": 1, "payload_root": "payload/", "files": [],
         "plugin": {"id": "hand", "name": "手工拷贝", "version": "1.0.0", "kind": "data",
                    "data_kind": "lines", "code": False, "min_host_version": HOST_VERSION,
                    "api_version": 1, "capabilities": []}}, ensure_ascii=False), encoding="utf-8")
    assert host.set_enabled("hand", False)[0] is True     # 登记里出现一条 landed 为空的记录
    before = len(lines_lib.lines())
    zip_path = _plugin_zip(str(tmp_path / "l.zip"), _lines_pack(), pid="hand", data_kind="lines")
    ok, msg = host.install_zip(zip_path)
    assert ok is True, msg
    assert len(lines_lib.lines()) == before + 2, "同 id 的真包没落地（空壳）"
    assert "覆盖旧版本" not in msg, "登记里没有落地账却说内容已落地：%r" % (msg,)
    reg = _registry(tmp_path)["plugins"]["hand"]
    assert reg["landed"]["lines"], "落地账没重建"
    assert reg["enabled"] is False, "用户禁用过的状态该沿用"


def test_S1_c_包内容变了必须说清楚不会导入新内容(tmp_path):
    """S1-c 的另一半：同 id 的新包（内容变了）走覆盖更新时**不会**导入新增内容——这是产品
    口径（重复安装不重复导入），但文案必须说清楚，不许让用户以为新内容进来了。

    能真失败：去掉 install_zip 里那句 same_zip 判断 → 新包被静默当"已更新"，红。
    """
    lines_lib = pet_lines.LineService(str(tmp_path))
    host = pet_plugin_host.PluginHost(str(tmp_path), HOST_VERSION, lines_lib=lines_lib)
    v1 = {"lines.json": json.dumps({"lines": [{"text": "第一版"}]},
                                   ensure_ascii=False).encode("utf-8")}
    v2 = {"lines.json": json.dumps({"lines": [{"text": "第二版新增的"}]},
                                   ensure_ascii=False).encode("utf-8")}
    assert host.install_zip(_plugin_zip(str(tmp_path / "v1.zip"), v1,
                                        pid="upd", data_kind="lines"))[0] is True
    n = len(lines_lib.lines())
    ok, msg = host.install_zip(_plugin_zip(str(tmp_path / "v2.zip"), v2,
                                           pid="upd", data_kind="lines"))
    assert ok is True and "覆盖" in msg, msg
    assert "不是同一个文件" in msg, "包变了却没提醒新内容不会导入：%r" % (msg,)
    assert len(lines_lib.lines()) == n, "覆盖更新不该重复落地"


# ---------------- P3-2 / S1-b：提交失败不留半截目录、不留临时目录 ----------------
def test_P3_2_提交失败_不留半截插件目录也不留临时目录(tmp_path, monkeypatch):
    """P3-2 / S1-b（实测）：shutil.move 失败时 except 不清理 target → plugins/<id>/half.txt
    留着；而解包在 %TEMP%（常常在 C:）时 move 是 copytree+rmtree，非原子。现在解包在同一盘
    的 .tmp-* 里、提交用 os.replace。

    能真失败：① 把 os.replace 换回 shutil.move（本用例把两条路都 patch 成会抛）→ 失败文案
    断言红；② 去掉 except 里的 rmtree(target)，或去掉 finally 里的临时目录清理 → 快照红。
    """
    lines_lib = pet_lines.LineService(str(tmp_path))
    host = pet_plugin_host.PluginHost(str(tmp_path), HOST_VERSION, lines_lib=lines_lib)
    zip_path = _plugin_zip(str(tmp_path / "l.zip"), _lines_pack(), pid="mvfail", data_kind="lines")
    real_replace = os.replace

    def _half_then_fail(src, dst, *a, **k):
        if not str(dst).endswith("mvfail"):
            return real_replace(src, dst, *a, **k)
        os.makedirs(str(dst), exist_ok=True)          # 模拟"拷到一半"
        with open(os.path.join(str(dst), "half.txt"), "w", encoding="utf-8") as f:
            f.write("half")
        raise OSError("模拟提交到一半失败")

    def _move_fails(*a, **k):
        raise OSError("模拟跨盘 move 失败")            # 旧实现必失败，保证这条对它也红

    monkeypatch.setattr(pet_plugin_host.os, "replace", _half_then_fail)
    monkeypatch.setattr(pet_plugin_host.shutil, "move", _move_fails)
    before = _snapshot(tmp_path)
    ok, msg = host.install_zip(zip_path)
    assert ok is False and "安装插件目录失败" in msg, msg
    assert _diff(before, _snapshot(tmp_path)) == {}, "提交失败留了半截目录 / 临时目录 / 库内容"
    assert not (tmp_path / "plugins").exists(), "失败路径留了空 plugins/"


# ---------------- S1-a：登记写失败必须把已落地内容回滚 ----------------
def test_S1_a_登记写失败必须回滚已落地内容(tmp_path):
    """S1-a（实测 WinError 5）：把 plugins/_installed.json 做成**目录** → 写登记必失败。
    此前 ok=False，但插件台词**永久留在 lines.json 里**（插件管理里还看不到这个插件，
    重装还会再导一份）。

    能真失败：去掉 install_zip 登记失败分支里的 _unland 调用 → 台词留在库里，快照红。
    """
    lines_lib = pet_lines.LineService(str(tmp_path))
    host = pet_plugin_host.PluginHost(str(tmp_path), HOST_VERSION, lines_lib=lines_lib)
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    (plugins / "_installed.json").mkdir()             # 目录：写登记一定失败（真实故障形态）
    zip_path = _plugin_zip(str(tmp_path / "l.zip"), _lines_pack(), pid="regfail", data_kind="lines")
    before = _snapshot(tmp_path)
    ok, msg = host.install_zip(zip_path)
    assert ok is False and "安装登记失败" in msg, msg
    assert _diff(before, _snapshot(tmp_path)) == {}, "安装失败了，台词却留在库里"
    assert "插件台词一" not in [x["text"] for x in lines_lib.lines()]
    assert not (plugins / "regfail").exists(), "目录没撤掉"


def test_S1_a_登记写失败_音效与角色类也要回滚(tmp_path):
    """S1-a 的第二类：同一个失败分支对 role 类要把角色条目与素材一起撤掉（不然 roles/ 里
    留孤儿 png、索引里留半条记录）。

    能真失败：把 _unland 的 role 分支删掉 → 快照红。
    """
    lib = _make_role_lib(tmp_path, [_KEEP_ROLE])
    host = pet_plugin_host.PluginHost(str(tmp_path), HOST_VERSION, role_lib=lib)
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    (plugins / "_installed.json").mkdir()
    zip_path = _plugin_zip(str(tmp_path / "r.zip"), _role_payload(), pid="regrole")
    before = _snapshot(tmp_path)
    ok, msg = host.install_zip(zip_path)
    assert ok is False and "安装登记失败" in msg, msg
    assert [r["id"] for r in lib.list_roles()] == ["keep1"], "角色条目没回滚"
    roles_dir = tmp_path / "roles"
    left = [str(p) for p in roles_dir.rglob("*")] if roles_dir.exists() else []
    assert [p for p in left if os.path.isfile(p)] == [], "素材没回滚（孤儿 png）：%r" % (left,)
    assert not (plugins / "regrole").exists(), "目录没撤掉"
    # 角色库自己会重写索引（形状由它决定），所以这里比"有没有**新**文件"而不是逐字节相等
    stale = [k for k in _snapshot(tmp_path) if k not in before]
    assert stale == [], "失败路径多出了文件：%r" % (stale,)


# ---------------- S3③：prompt 类先判后建，失败不留空目录 ----------------
def test_S3_3_prompt落地失败不留空的custom目录(tmp_path):
    """S3③：_land_prompt 此前**先 makedirs 再逐条判**，任何一条不通过都留下一个空的
    prompts/custom/（"失败的安装不留残余"就不成立了）。包内重名是能触发它的真实形态。

    能真失败：把预检改回"边拷边判"（先 makedirs）→ prompts/ 目录留下，快照红。
    """
    host = pet_plugin_host.PluginHost(str(tmp_path), HOST_VERSION)
    payload = {"prompts/a/同名.txt": "甲".encode("utf-8"),
               "prompts/b/同名.txt": "乙".encode("utf-8")}
    zip_path = _plugin_zip(str(tmp_path / "p.zip"), payload, pid="p-dup", data_kind="prompt")
    before = _snapshot(tmp_path)
    ok, msg = host.install_zip(zip_path)
    assert ok is False and "重名" in msg, msg
    assert _diff(before, _snapshot(tmp_path)) == {}, "失败却留下了 prompts/custom/ 空目录"
    assert not (tmp_path / "prompts").exists(), "失败路径建了 prompts/"


def test_S3_2_safe_id不接受空白与保留名(tmp_path):
    """S3②：_safe_id 是"任何路径都不许拼出来"的最后一道 —— 补上保留名判据，并且**不再
    strip 归一**（" x" 与 "x" 是两个不同字符串，静默归一等于替包作者改名）。

    能真失败：去掉 _safe_id 里的保留名判断（或恢复 strip）→ 前两条断言红。
    """
    assert pet_plugin_host._safe_id("packs") == ""
    assert pet_plugin_host._safe_id("README.md") == ""
    assert pet_plugin_host._safe_id(" x") == "" and pet_plugin_host._safe_id("x ") == ""
    assert pet_plugin_host._safe_id("ok-id") == "ok-id"

