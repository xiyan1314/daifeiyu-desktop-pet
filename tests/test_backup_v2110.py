# -*- coding: utf-8 -*-
"""pet_backup（v2.11.0 · W1-b）的回归：往返 / 清单 / 坏包 / zip slip / 原子性 / 快照 / 回滚。

每条用例都带一句「能真失败：…」，写的是**把哪一行拿掉或改坏它就红**——没有这句话的用例，
在这一仓等于没有证据（判据必须能真失败，见 _dev/VERIFY_DISCIPLINE.md §二、§三）。

样本布局：备份包一律放 tmp_path，**数据目录是 tmp_path/data**。这个分离是刻意的——
zip slip 攻击的落点（../evil.txt）正好落在 tmp_path 里，用例可以当场断言"那里也没有文件"，
而不用去碰盘上的任何真实路径。
"""
import datetime
import hashlib
import json
import os
import zipfile

import pytest

import _check_release     # 白名单口径的真源：用例直接拿它做对照（证明我没手抄一份）
import pet_backup
import pet_plugin         # 条目名安全线的真源：与 pet_backup 共用同一条判据


# ---------------- 测试用的小工具 ----------------

# 注入时钟的时区：**显式**写出来，绝不从本机取。
# CI #60 的事故：旧版 _now() 是 datetime(...).astimezone()——拿到的是**跑测机器**的偏移，
# 断言却写死了东八区那一串；本机（东八区）绿、GitHub runner（UTC）红。同一条判据两种
# 结论，那就不是判据。显式 tzinfo 之后，"哪一刻 + 哪个偏移"只由用例自己决定。
_TZ8 = datetime.timezone(datetime.timedelta(hours=8))


def _now():
    """注入时钟：manifest 的 created_at 由它决定，断言自己算一份来比（不比字符串写死的偏移）。"""
    return datetime.datetime(2026, 10, 17, 13, 15, 0, tzinfo=_TZ8)


def _put(base, rel, data):
    """在 base 下写一个文件（自动建目录）。"""
    ap = os.path.join(str(base), *rel.split("/"))
    parent = os.path.dirname(ap)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(ap, "wb") as f:
        f.write(data)
    return ap


def _get(base, rel):
    with open(os.path.join(str(base), *rel.split("/")), "rb") as f:
        return f.read()


def _tree(base):
    """base 下所有文件的相对路径集合——判"数据一个字节都没动"用它。"""
    out = set()
    par = str(base)
    for cur, _dirs, files in os.walk(par):
        for f in files:
            out.add(os.path.relpath(os.path.join(cur, f), par).replace(os.sep, "/"))
    return out


def _sha(data):
    return hashlib.sha256(data).hexdigest()


# 用户数据（按发布口径的 USER_DATA_NAMES / USER_DATA_DIRS 挑的样本）
USER_FILES = {
    "config.json": b'{"sound": true}',
    "roles.json": b'{"roles": []}',
    "roles/a.png": b"\x89PNG-A",
    "roles/sub/b.png": b"\x89PNG-B",
    "prompts/custom/mine.txt": "自定义人设".encode("utf-8"),
    "plugins/myplug/manifest.json": b'{"id": "myplug"}',
}
# 不是用户数据的东西（每一条都对应发布口径里的一条判据）
NON_USER_FILES = {
    "notes.txt": b"not user data",                      # 名字不在名单里
    "assets/char.png": b"\x89PNG-ASSET",                 # 随包发货的素材
    "prompts/default.txt": "内置预设".encode("utf-8"),  # 只认 prompts/custom
    "plugins/index.json": b'{"plugins": []}',            # 官方索引（发货文件）
    "__pycache__/x.cpython-310.pyc": b"\x00\x01",       # 缓存
}


@pytest.fixture
def data_dir(tmp_path):
    """一份有代表性的数据目录：用户数据 + 一堆"不是用户数据"的东西。"""
    d = tmp_path / "data"
    for rel, data in list(USER_FILES.items()) + list(NON_USER_FILES.items()):
        _put(d, rel, data)
    return d


def _good_backup(data_dir, tmp_path, name="backup.zip"):
    """打一个正常备份，返回路径。"""
    path = tmp_path / name
    ok, msg = pet_backup.create_backup(data_dir, path, app_version="2.11.0", now=_now())
    assert ok, msg
    return path


def _rebuild(src_zip, out_zip, drop=(), replace=None):
    """把备份包原样重打一遍：可丢掉某个条目、可替换某个条目的内容（造坏样本用）。"""
    with zipfile.ZipFile(src_zip) as zf:
        items = [(info, zf.read(info.filename)) for info in zf.infolist()]
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for info, data in items:
            if info.filename in drop:
                continue
            if replace and info.filename in replace:
                data = replace[info.filename]
            zf.writestr(info, data)
    return out_zip


def _hostile_zip(path, entry_name, payload=b"pwned"):
    """造一个"内容和清单自洽、但条目名越界"的包——zip slip 攻击样本。"""
    man = {
        "format": pet_backup.BACKUP_FORMAT,
        "schema": 1,
        "created_at": _now().isoformat(),
        "app_version": "2.11.0",
        "files": [{"name": entry_name, "size": len(payload), "sha256": _sha(payload)}],
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(pet_backup.MANIFEST_NAME, json.dumps(man, ensure_ascii=False))
        zf.writestr(entry_name, payload)
    return path


# ---------------- 一、往返 ----------------

def test_往返逐字节一致(data_dir, tmp_path):
    """备份 → 改坏/删掉 → 恢复，每个用户文件逐字节回到备份时的样子。

    能真失败：把 _commit 里那句 _write_bytes 换成"只记录不写盘"，恢复后文件内容对不上 → 红。
    也钉住"备份里刚好是这 6 个文件"——多带/少带都会红。
    """
    zb = _good_backup(data_dir, tmp_path)
    # 改坏 + 删掉，确保恢复真的从包里取内容，而不是"本来就一样"
    _put(data_dir, "config.json", b"CHANGED")
    os.remove(os.path.join(str(data_dir), "roles", "a.png"))
    _put(data_dir, "roles/sub/b.png", b"CHANGED-TOO")
    ok, msg = pet_backup.restore_backup(zb, data_dir, now=_now())
    assert ok, msg
    assert "已从备份恢复" in msg
    assert _get(data_dir, "config.json") == USER_FILES["config.json"]
    assert _get(data_dir, "roles/a.png") == USER_FILES["roles/a.png"]
    assert _get(data_dir, "roles/sub/b.png") == USER_FILES["roles/sub/b.png"]
    assert _get(data_dir, "prompts/custom/mine.txt") == USER_FILES["prompts/custom/mine.txt"]
    man, err = pet_backup.read_manifest(zb)
    assert err == ""
    assert [f["name"] for f in man["files"]] == sorted(USER_FILES)


def test_恢复不删掉备份里没有的用户文件(data_dir, tmp_path):
    """恢复是"盖上去"，不是"镜像"：恢复一个空备份，现有的用户文件一个都不许少。

    能真失败：在 _commit 前面加一段"先把数据目录清空"，这条立刻红——而那句清空是数据丢失事故。
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    zb = tmp_path / "empty.zip"
    ok, msg = pet_backup.create_backup(empty, zb, now=_now())
    assert ok, msg
    assert "没有可备份的用户数据" in msg
    before = _tree(data_dir)
    ok, msg = pet_backup.restore_backup(zb, data_dir, now=_now())
    assert ok, msg
    assert _tree(data_dir) == before
    assert _get(data_dir, "config.json") == USER_FILES["config.json"]


# ---------------- 二、manifest ----------------

def test_manifest_内容(data_dir, tmp_path):
    """manifest 的每个字段都是真的：摘要独立算一遍、计数/体积/时间/版本对得上。

    能真失败：把 _sha256_file 换成"返回固定串"，下面逐条比摘要立刻红；
    把 created_at 改成 datetime.now() 而不是注入时钟，时间断言红。
    """
    zb = _good_backup(data_dir, tmp_path)
    man, err = pet_backup.read_manifest(zb)
    assert err == ""
    assert man["format"] == pet_backup.BACKUP_FORMAT
    assert man["schema"] == pet_backup.BACKUP_SCHEMA
    # created_at 与注入时钟比"哪一刻"，不与字符串比——断言里没有任何写死的时区偏移，
    # 所以东八区的本机与 UTC 的 runner 是同一条判据（CI #60 红的就是这一行）。
    created = datetime.datetime.fromisoformat(man["created_at"])
    assert created == _now(), man["created_at"]                          # 同一时刻
    assert created.utcoffset() == _now().utcoffset(), man["created_at"]  # 注入的偏移原样落盘
    assert man["created_at"].startswith("2026-10-17T13:15:00"), man["created_at"]  # 墙钟没被改写
    assert man["app_version"] == "2.11.0"
    assert man["file_count"] == len(USER_FILES)
    assert man["total_bytes"] == sum(len(v) for v in USER_FILES.values())
    by_name = {f["name"]: f for f in man["files"]}
    for rel, data in USER_FILES.items():
        assert by_name[rel]["sha256"] == _sha(data), rel          # 用例自己算一遍（不抄被测实现）
        assert by_name[rel]["size"] == len(data), rel
    # 白名单那一段是"按哪一版规则打的"的证据，必须等于发布门当前的口径
    assert man["whitelist"]["names"] == sorted(_check_release.USER_DATA_NAMES)
    assert man["whitelist"]["dirs"] == sorted(
        str(d).replace("\\", "/").strip("/") for d in _check_release.USER_DATA_DIRS)
    assert man["whitelist"]["source"] == pet_backup.RUNTIME_RULES_NAME
    assert len(man["whitelist"]["revision"]) == 12
    assert man["whitelist"]["revision"] == pet_backup.whitelist_snapshot()["revision"]


def test_备份范围跟着口径对象走而不是写死在代码里(tmp_path, monkeypatch):
    """给什么口径就按什么口径算：往口径对象里加一个名字，备份范围与"规则版本"立刻跟着变。

    这是"运行期自带一份口径"那件事的**行为面**证据：本模块里没有第二份写死的名单，
    is_user_data / collect_user_files 全是照着"口径对象"算的（默认对象是 RUNTIME_RULES，
    它的数据由下一条钉子用例与发布门逐项对齐）。

    能真失败（_dev/probe_backup_v2110.py 的 M07 实测 CAUGHT）：把 is_user_data 里那句
    src.user_data_hit(parts[0]) 换成写死的 ("config.json", "roles.json") → niche.json
    不会进包 → 红。
    """
    d = tmp_path / "data"
    _put(d, "config.json", b"A")
    _put(d, "niche.json", b"N")
    assert pet_backup.collect_user_files(d) == ["config.json"]
    rev0 = pet_backup.whitelist_snapshot()["revision"]
    monkeypatch.setattr(pet_backup._RuntimeRules, "USER_DATA_NAMES",
                        set(pet_backup.RUNTIME_USER_DATA_NAMES) | {"niche.json"})
    assert pet_backup.collect_user_files(d) == ["config.json", "niche.json"]
    assert pet_backup.whitelist_snapshot()["revision"] != rev0


def test_缓存目录不进包(data_dir, tmp_path):
    """__pycache__ 是发布口径里的 USER_DATA_DIRS 之一，但备份**不带**它（.pyc 是可再生产物）。

    能真失败：把 BACKUP_SKIP_DIRS 置空 → __pycache__/x.cpython-310.pyc 进包 → 红。
    """
    zb = _good_backup(data_dir, tmp_path)
    man, _err = pet_backup.read_manifest(zb)
    names = [f["name"] for f in man["files"]]
    assert not [n for n in names if "__pycache__" in n], names
    assert pet_backup.is_user_data("__pycache__/x.pyc") is False


def test_发货文件即使躺在白名单目录里也不进包(tmp_path, monkeypatch):
    """发货清单对白名单目录行使**否决权**（"发布门认发货 / 备份认用户"的接口处）。

    真实例子是 plugins/index.json（官方索引：既在 SYNC_FILES 里、又躺在 plugins/ 下）。
    这里用 monkeypatch 造一个更直接的样本（roles/keepme.png 假装是随包发货的文件），
    免得与"官方插件"那条判据混在一起；运行期否决清单本身由钉子用例与发布门对齐。

    能真失败（_dev/probe_backup_v2110.py 的 M03 实测 CAUGHT）：把 is_user_data 里那句
    SYNC_FILES 否决删掉 → 下面两条都变成 True → 红。
    """
    d = tmp_path / "data"
    _put(d, "roles/keepme.png", b"SHIPPED")
    assert pet_backup.is_user_data("roles/keepme.png", d) is True
    monkeypatch.setattr(pet_backup._RuntimeRules, "SYNC_FILES",
                        tuple(pet_backup.RUNTIME_SYNC_FILES) + ("roles/keepme.png",))
    assert pet_backup.is_user_data("roles/keepme.png", d) is False
    assert pet_backup.collect_user_files(d) == []


def test_残留形态不进包(data_dir, tmp_path):
    """原子写/自愈的残留（config.json.<pid>.<tid>.tmp 之类）不进备份，恢复也不许写它。

    能真失败：把 is_user_data 末尾那句 "return not src.residue_hit(...)" 改成 "return True"
    → .tmp 进了包、也进了白名单 → 两条断言都红。
    """
    _put(data_dir, "config.json.4242.99.tmp", b"half written")
    assert pet_backup.is_user_data("config.json.4242.99.tmp") is False
    assert pet_backup.is_user_data("error.log.old") is False
    zb = _good_backup(data_dir, tmp_path)
    man, _err = pet_backup.read_manifest(zb)
    assert "config.json.4242.99.tmp" not in [f["name"] for f in man["files"]]


def test_白名单外的文件不进包(data_dir, tmp_path):
    """裸文件、随包素材、内置预设一律不进包；白名单里的一个都不少。

    能真失败：把 collect_user_files 的根一层判断改成"什么都收"，notes.txt 立刻进包 → 红；
    把目录白名单那段删掉，roles/a.png 不在包里 → 红（另一侧同样有牙）。
    """
    zb = _good_backup(data_dir, tmp_path)
    man, _err = pet_backup.read_manifest(zb)
    names = [f["name"] for f in man["files"]]
    for rel in ("notes.txt", "assets/char.png", "prompts/default.txt", "plugins/index.json"):
        assert rel not in names, rel
    for rel in USER_FILES:
        assert rel in names, rel


# ---------------- 三、坏包 ----------------

def test_断zip必须拒绝(data_dir, tmp_path):
    """被截断的包（没下完整）不许动数据。

    能真失败：把 _inspect_zip 里对 zipfile.BadZipFile 的处理换成"继续往下走"，会抛栈出来 → 红。
    """
    zb = _good_backup(data_dir, tmp_path)
    raw = zb.read_bytes()
    broken = tmp_path / "broken.zip"
    broken.write_bytes(raw[:len(raw) * 6 // 10])
    before = _tree(data_dir)
    ok, msg = pet_backup.restore_backup(broken, data_dir, now=_now())
    assert ok is False
    assert "zip" in msg
    assert _tree(data_dir) == before
    man, err = pet_backup.read_manifest(broken)
    assert man is None and "zip" in err


def test_空zip必须拒绝(data_dir, tmp_path):
    """合法但空的 zip（没有任何条目）不是备份包：没有清单就不许恢复。

    能真失败：把 _read_manifest_from 里 KeyError 的兜底删掉（或让它返回空 dict），
    代码会走到"清单结构不对"以外的地方，断言红。
    """
    empty = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty, "w"):
        pass
    before = _tree(data_dir)
    ok, msg = pet_backup.restore_backup(empty, data_dir, now=_now())
    assert ok is False
    assert "清单" in msg
    assert _tree(data_dir) == before


def test_缺文件必须拒绝(data_dir, tmp_path):
    """清单里有、包里没有 → 拒绝（否则恢复出来的数据是"缺一块"的，用户还以为成功了）。

    能真失败：把 _names_problem 里 missing 那段删掉，恢复会"成功"只写 5 个文件 → 红。
    """
    zb = _good_backup(data_dir, tmp_path)
    missing = _rebuild(zb, tmp_path / "missing.zip", drop=("roles/a.png",))
    before = _tree(data_dir)
    ok, msg = pet_backup.restore_backup(missing, data_dir, now=_now())
    assert ok is False
    assert "找不到" in msg or "不完整" in msg
    assert _tree(data_dir) == before


@pytest.mark.parametrize("payload, expect", [
    (b"XXXXXX", "sha256"),                  # 同样长度、内容换了 → 只可能是摘要对不上
    (b"XX", "大小对不上"),                   # 变短了 → 字节数先对不上
    (b"TOO-LONG-CONTENT", "比清单说的大"),    # 变长了 → 读到超限立刻中止（zip 炸弹那道闸）
])
def test_内容被改过的包必须拒绝(data_dir, tmp_path, payload, expect):
    """逐个文件比 sha256/字节数，对不上就拒绝（这一步在写盘之前）。

    能真失败：把 _extract_entries 里比摘要那三行删掉，篡改过的包会被"恢复成功" → 红。
    """
    zb = _good_backup(data_dir, tmp_path)
    bad = _rebuild(zb, tmp_path / "tampered.zip",
                   replace={"roles/a.png": payload})
    before = _tree(data_dir)
    ok, msg = pet_backup.restore_backup(bad, data_dir, now=_now())
    assert ok is False
    assert expect in msg
    assert _tree(data_dir) == before


def test_清单结构不对要有人话(data_dir, tmp_path):
    """format 不对 / schema 太新 / sha256 字段坏 —— 都要一句能直接给用户看的话。

    能真失败：把 _manifest_problem 里 schema 上界那条删掉，"更新版本做的备份"会被放行 → 红。
    """
    good = _good_backup(data_dir, tmp_path)
    cases = [
        ({"format": "something-else"}, "不是大肥鱼"),
        ({"schema": pet_backup.BACKUP_SCHEMA + 1}, "升级"),
        ({"files": [{"name": "config.json", "size": 1, "sha256": "x"}]}, "sha256"),
    ]
    for i, (patch, expect) in enumerate(cases):
        with zipfile.ZipFile(good) as zf:
            man = json.loads(zf.read(pet_backup.MANIFEST_NAME).decode("utf-8"))
        man.update(patch)
        bad = tmp_path / ("meta%d.zip" % i)
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr(pet_backup.MANIFEST_NAME, json.dumps(man, ensure_ascii=False))
        ok, msg = pet_backup.restore_backup(bad, data_dir, now=_now())
        assert ok is False, i
        assert expect in msg, (i, msg)


# ---------------- 四、zip slip ----------------

@pytest.mark.parametrize("entry, layer, outside", [
    ("../evil.txt", "不安全的路径", "evil.txt"),
    ("roles/../../evil.png", "不安全的路径", "evil.png"),
    ("roles/..\\..\\evil.png", "不安全的路径", None),
    ("/abs/evil.txt", "不安全的路径", None),
    ("C:/evil.txt", "不安全的路径", None),
    ("con.png", "不安全的路径", None),
    ("roles/", "不安全的路径", None),
    ("assets/char.png", "不属于用户数据", None),
])
def test_zip_slip_必须拒绝且目标目录不留文件(data_dir, tmp_path, entry, layer, outside):
    """越界条目名一律拒（连解压都不开始）；名字合法的"非用户数据"由白名单那一层拒。

    能真失败：把 _names_problem 里 entry_name_problem 那段删掉 → ../evil.txt 会穿过名字层；
    再把 is_user_data 那句删掉 → 内容真的写到数据目录外面（用例断言 outside 那个文件不存在）。
    两个断言分别钉住两层，所以"只删一层"也会红（报错文案换人就对不上了）。
    """
    hostile = _hostile_zip(tmp_path / "hostile.zip", entry)
    before = _tree(data_dir)
    ok, msg = pet_backup.restore_backup(hostile, data_dir, now=_now())
    assert ok is False, entry
    assert layer in msg, (entry, msg)
    assert _tree(data_dir) == before, entry
    if outside:
        assert not (tmp_path / outside).exists(), outside


def test_重名条目必须拒绝(tmp_path, data_dir):
    """同名条目出现两次：zipfile 只给最后一条，清单对不上 → 拒绝（经典藏匿手法）。

    能真失败：把 _names_problem 开头那句重名判断删掉，包会被当成"只有最后一条"正常恢复 → 红。
    """
    evil = tmp_path / "dup.zip"
    first, second = b"AAAA", b"BBBB"
    man = {
        "format": pet_backup.BACKUP_FORMAT, "schema": 1,
        "created_at": _now().isoformat(), "app_version": "2.11.0",
        "files": [{"name": "config.json", "size": len(first), "sha256": _sha(first)}],
    }
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr(pet_backup.MANIFEST_NAME, json.dumps(man, ensure_ascii=False))
        # zipfile 自己会为同名条目发一条 UserWarning：这里把它当**预期**（样本本来就要重名），
        # 免得它在汇总行里变成一条来源不明的噪音
        with pytest.warns(UserWarning):
            zf.writestr("config.json", first)
            zf.writestr("config.json", second)
    before = _tree(data_dir)
    ok, msg = pet_backup.restore_backup(evil, data_dir, now=_now())
    assert ok is False
    assert "重名" in msg
    assert _tree(data_dir) == before


def test_条目名安全线与插件包共用一条判据():
    """同一条判据守着两处解包：插件包（pet_plugin）与用户数据恢复（本模块）。

    能真失败：在本模块里自己抄一份"含 .. / 以 / 开头"的简化判据（漏掉保留设备名与非法字符），
    下面 con / a:b 两个样本立刻红。
    """
    samples = ("roles/a.png", "manifest.json", "../evil", "/abs", "C:/x", "con.png",
               "roles/a:b.png", "roles/", "", "roles//x.png")
    for name in samples:
        assert pet_backup.entry_name_problem(name) == (
            pet_plugin._unsafe_name_reason(name)
            or ("是目录条目（备份包里只放文件）" if name.endswith("/") else "")), name


# ---------------- 五、原子性与快照 ----------------

def test_原子性_写到一半失败不留残件(data_dir, tmp_path, monkeypatch):
    """写包写到第二条炸了：正式文件不存在、临时件也清干净、原数据没动。

    能真失败（_dev/probe_backup_v2110.py 的 M17 实测 CAUGHT）：把 _write_zip_atomic 末尾
    那**唯一**的清理点（finally 里的 _remove(tmp)）拿掉 → *.tmp 留在磁盘上 → 红。
    另：把 os.replace(tmp, out) 提前到写之前（"先建个空文件占位"），out 会存在 → 也红。
    """
    out = tmp_path / "out" / "b.zip"
    calls = {"n": 0}
    real = pet_backup._add_file

    def boom(zf, arc, src):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise OSError("磁盘满了")
        return real(zf, arc, src)

    monkeypatch.setattr(pet_backup, "_add_file", boom)
    ok, msg = pet_backup.create_backup(data_dir, out, now=_now())
    assert ok is False
    assert "没写成" in msg
    assert not out.exists()
    assert [p.name for p in out.parent.glob("*.tmp")] == []
    assert _get(data_dir, "config.json") == USER_FILES["config.json"]


def test_同一份数据同一个时钟两次备份逐字节相同(data_dir, tmp_path):
    """manifest 用固定时间戳写：同一份数据 + 同一个注入时钟 → 整包逐字节相同。

    能真失败：把 _write_manifest 换成 zf.writestr(MANIFEST_NAME, ...)（按当前时钟取时间），
    manifest 条目的 date_time 不再是 1980-01-01 → 第一条断言就红。
    """
    a = _good_backup(data_dir, tmp_path, "a.zip")
    b = _good_backup(data_dir, tmp_path, "b.zip")
    assert a.read_bytes() == b.read_bytes()
    with zipfile.ZipFile(a) as zf:
        assert zf.getinfo(pet_backup.MANIFEST_NAME).date_time == (1980, 1, 1, 0, 0, 0)


def test_恢复前先留快照_且快照能单独恢复(data_dir, tmp_path):
    """写盘前自动快照：落在备份包同目录、名字是 .pre-restore-时间、内容是一份**能用的**备份。

    能真失败：把 restore_backup 里 _make_snapshot 那段删掉 → 快照不存在 → 红；
    把 create_backup 换成"写个空 zip"→ 快照恢复不出内容 → 红。
    """
    zb = _good_backup(data_dir, tmp_path)
    _put(data_dir, "config.json", b"AFTER-BACKUP")
    ok, msg = pet_backup.restore_backup(zb, data_dir, now=_now())
    assert ok, msg
    snaps = pet_backup.list_snapshots(tmp_path)
    assert len(snaps) == 1, snaps
    assert os.path.basename(snaps[0]).startswith(pet_backup.SNAPSHOT_PREFIX)
    assert snaps[0] in msg                      # 回执里要告诉用户快照落在哪
    assert _get(data_dir, "config.json") == USER_FILES["config.json"]
    # 快照本身必须是一份能救场的完整备份
    ok, msg = pet_backup.restore_backup(snaps[0], data_dir, now=_now())
    assert ok, msg
    assert _get(data_dir, "config.json") == b"AFTER-BACKUP"


def test_快照写不出来就不许开始恢复(data_dir, tmp_path, monkeypatch):
    """没有回滚依据 = 不恢复（"要么全成"才不是一句空话）。

    能真失败：把 restore_backup 里 snap_err 那段的返回值改成"继续往下写"，数据会被改动 → 红。
    """
    zb = _good_backup(data_dir, tmp_path)
    _put(data_dir, "config.json", b"AFTER-BACKUP")
    monkeypatch.setattr(pet_backup, "create_backup",
                        lambda *a, **k: (False, "模拟：快照目录写不进去"))
    before = _tree(data_dir)
    ok, msg = pet_backup.restore_backup(zb, data_dir, now=_now())
    assert ok is False
    assert "快照" in msg
    assert _tree(data_dir) == before


# ---------------- 六、失败回滚 ----------------

def test_恢复失败回滚_数据回到恢复前的样子(tmp_path, monkeypatch):
    """写到一半失败 → 用快照盖回已改的，并删掉这一趟新造出来的文件。

    场景（条目按名字排序：audio.json < config.json < roles/z.png）：
      · 备份里有 audio.json / config.json / roles/z.png 三份"旧"内容；
      · 恢复前：三份都是"新"内容，其中 audio.json 被用户删掉了（= 恢复时会新建）；
      · 注入：写 roles/z.png 时失败 → 此时 audio.json 与 config.json 已被盖成旧内容。

    期望：config.json 回到"新"内容（快照盖回）、audio.json 不存在（新造的删掉）、
    roles/z.png 保持"新"（它压根没被写成功）。

    能真失败（两条，各自独立）：
      · 把 _rollback 里"删掉 placed 且不在快照里的文件"那段删掉 → audio.json 残留 → 红；
      · 把 restore_backup 里 _rollback 这次调用删掉 → config.json 停在旧内容 → 红。
    """
    d = tmp_path / "data"
    _put(d, "config.json", b"OLD-CONFIG")
    _put(d, "audio.json", b"OLD-AUDIO")
    _put(d, "roles/z.png", b"OLD-Z")
    zb = _good_backup(d, tmp_path)
    _put(d, "config.json", b"NOW-CONFIG")
    _put(d, "roles/z.png", b"NOW-Z")
    os.remove(os.path.join(str(d), "audio.json"))     # 恢复时会被"新造"出来

    real = pet_backup._write_bytes
    state = {"failed": False}

    def boom(target, data):
        # 只失败**一次**：真实世界里更常见的是"这个文件被某个程序短暂占用"。
        # 若让它一直失败，回滚盖 roles/z.png 时同样会失败——那是另一条分支，见下一条用例。
        if not state["failed"] and target.replace("\\", "/").endswith("roles/z.png"):
            state["failed"] = True
            return "模拟：文件被占用"
        return real(target, data)

    monkeypatch.setattr(pet_backup, "_write_bytes", boom)
    ok, msg = pet_backup.restore_backup(zb, d, now=_now())
    assert ok is False
    assert "回退" in msg
    assert "已经回退" in msg
    assert _get(d, "config.json") == b"NOW-CONFIG"
    assert not os.path.exists(os.path.join(str(d), "audio.json"))
    assert _get(d, "roles/z.png") == b"NOW-Z"
    assert pet_backup.list_snapshots(tmp_path)          # 快照留着，用户还能自己退回


def test_回滚也失败时_说清楚快照在哪(tmp_path, monkeypatch):
    """回滚本身也写不进去时，必须给一句可操作的话（快照路径 + "手工解压找回"），不许假装回滚成功。

    能真失败：把 restore_backup 里 _rollback 的返回值丢掉（永远报"已经回退"），
    第一条断言（"回退也没成功"）立刻红——用户会以为数据回来了，其实没有。
    """
    d = tmp_path / "data"
    _put(d, "config.json", b"OLD-CONFIG")
    _put(d, "roles/z.png", b"OLD-Z")
    zb = _good_backup(d, tmp_path)
    _put(d, "config.json", b"NOW-CONFIG")

    real = pet_backup._write_bytes

    def boom(target, data):
        if target.replace("\\", "/").endswith("roles/z.png"):
            return "模拟：一直被占用"
        return real(target, data)

    monkeypatch.setattr(pet_backup, "_write_bytes", boom)
    ok, msg = pet_backup.restore_backup(zb, d, now=_now())
    assert ok is False
    assert "回退也没成功" in msg
    snaps = pet_backup.list_snapshots(tmp_path)
    assert snaps and snaps[0] in msg, msg
    assert _get(d, "config.json") == b"NOW-CONFIG"   # 回滚先写的那几条仍然被救回来了


# ---------------- 七、口径拿不到时不许自己编 ----------------

def test_口径不完整时拒绝而不是猜一份(tmp_path):
    """注入的口径缺了必需属性：备份/恢复都返回人话失败，一个文件都不碰。

    能真失败（_dev/probe_backup_v2110.py 的 M23 实测 CAUGHT）：把 _source_or_load 里那句
    "缺属性就 raise" 删掉（= 缺了就凑合跑）→ 备份会**成功**写一个包出来 → 第一条断言红。
    """
    d = tmp_path / "data"
    _put(d, "config.json", b"A")
    out = tmp_path / "b.zip"
    ok, msg = pet_backup.create_backup(d, out, source=object())
    assert ok is False
    assert "口径不完整" in msg
    assert not out.exists()
    ok, msg = pet_backup.restore_backup(tmp_path / "whatever.zip", d, source=object())
    assert ok is False
    assert "口径不完整" in msg


# ---------------- 八、口径的两条钉子（出货副本 ↔ 发布门 / 熔断标记） ----------------

def test_运行期口径与发布门逐项相等(tmp_path):
    """出货模块自带的口径必须与发布检测脚本的那份**逐项相等**（数据面 + 行为面）。

    这是"运行期自带一份口径"这个决定的**唯一保险**：本仓四次"两份清单漂了"的事故都是
    "抄完之后没人再比"。发布门加一个名字而这里忘了加 → 数据面第一条断言红；口径的判据
    （含 plugins/ 那一支）被改歪 → 行为面那条红。

    能真失败（_dev/probe_backup_v2110.py 的 M26 实测 CAUGHT）：往 RUNTIME_USER_DATA_NAMES
    里多塞一个名字 → 逐项相等当场红。
    """
    # ① 数据面
    assert pet_backup.RUNTIME_USER_DATA_NAMES == _check_release.USER_DATA_NAMES
    assert pet_backup.RUNTIME_USER_DATA_DIRS == _check_release.USER_DATA_DIRS
    # 否决清单 = 发货清单里**落进用户数据候选空间**的那些（今天是 plugins/ 的两条）。
    # 这条断言是"以后有人往用户数据目录里塞一个随包文件"的报警器：那种条目会掉进下面这条
    # 规则里，而 RUNTIME_SYNC_FILES 没跟着加 → 红。
    dirs = [str(d).replace("\\", "/").strip("/") for d in _check_release.USER_DATA_DIRS]
    space = [n for n in _check_release.SYNC_FILES
             if n.startswith("plugins/")
             or any(n == d or n.startswith(d + "/") for d in dirs)
             or ("/" not in n and n in _check_release.USER_DATA_NAMES)]
    assert sorted(pet_backup.RUNTIME_SYNC_FILES) == sorted(space)
    # ② 行为面：同一份语料走同一条代码路径，两份口径必须给一样的答案
    d = tmp_path / "data"
    for rel in ("config.json", "roles/a.png", "prompts/custom/a.txt", "audio/snd/a.wav",
                "voice/ref.wav", "plugins/pk/a.zip", "plugins/index.json",
                "assets/x.png", "notes.txt", "config.json.1.2.tmp", "error.log.old",
                "crash_recovery.json", "__pycache__/a.pyc"):
        _put(d, rel, b"x")
    corpus = sorted(_tree(d)) + ["roles", "plugins/_download/x.zip", "manifests-ish.json"]
    for rel in corpus:
        assert (pet_backup.is_user_data(rel, d)
                == pet_backup.is_user_data(rel, d, source=_check_release)), rel


def test_熔断标记不进备份(data_dir, tmp_path):
    """crash_recovery.json 是运行期熔断状态：口径认它（发布包里不许有），备份**不带走**。

    为什么：恢复一个旧备份时把"崩过几次"一起倒灌回去，桌宠一启动就会被自己的熔断器当成
    崩溃循环——用户看到的是"恢复完备份就打不开了"。

    能真失败（_dev/probe_backup_v2110.py 的 M27 实测 CAUGHT）：把 _skip_names() 的返回值
    改成空集，或把 is_user_data 里那句 text in _skip_names() 删掉 → 它进包 → 红。
    """
    import pet_guard     # 在用例里 import：它不归本包管辖，不该成为本文件的收集期依赖

    _put(data_dir, pet_guard.MARKER_FILENAME, b'{"crashes": 3}')
    assert pet_backup.is_user_data(pet_guard.MARKER_FILENAME) is False
    zb = _good_backup(data_dir, tmp_path)
    man, _err = pet_backup.read_manifest(zb)
    assert pet_guard.MARKER_FILENAME not in [f["name"] for f in man["files"]]
    # 反向对照的另一半：它在**发布口径**里（否则"不带走"只是因为它本来就不是用户数据）
    assert pet_guard.MARKER_FILENAME in _check_release.USER_DATA_NAMES
