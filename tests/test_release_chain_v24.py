# -*- coding: utf-8 -*-
"""v2.4 发布链收口回归（M1/M2/M3 + L1/L9）。

每条用例都要求**能真的失败**：
  · 凡"合规输入必须通过"的断言，都配一条"同一路径把输入改坏就必须报"的反例；
  · 凡解析器/提取器（ci.yml 依赖行、AST 取删除名单、静态体检条目行），都先证明
    它能在真实文件上拿到东西——否则"没报错"可能只是断言空转。

背景（兼容审查实测）：
  M1 CI 不装 Pillow → tests/test_full_form_frames_v24.py 在 collection 就 ImportError，整条流水线红；
  M2 pet_log 隔离出的 error.log.bad 既躲过发布门禁、又清不掉（两处清理名单都没有它）；
  M3 发布门禁 check_zip 的 need 只查 "assets/" 前缀存不存在 → 真包 assets 140/150、
     idle_full 帧 0 个也放行；ZIP_EXTRA_NAMES 不含 repro_quiet.py → 真包混进它也不报。
"""
import ast
import os
import re
import subprocess
import sys
import threading
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _check_release as chk  # noqa: E402


def _read(name):
    with open(os.path.join(chk.ROOT, name), "r", encoding="utf-8") as f:
        return f.read()


def _lock_version(pkg):
    """requirements-lock.txt 里的 <pkg>==<版本>（没有就返回 ""）。"""
    for line in _read("requirements-lock.txt").splitlines():
        line = line.split("#", 1)[0].strip()
        m = re.match(r"^([A-Za-z0-9_.\-]+)==([0-9][0-9A-Za-z.\-]*)$", line)
        if m and m.group(1).lower() == pkg.lower():
            return m.group(2)
    return ""


# ---------------- M1：CI 必须装 Pillow（否则 collection ImportError） ----------------

def _ci_pip_packages(text):
    """ci.yml 文本 → pip install 行里的 {包名小写: 版本}（== 形式），只取安装行。"""
    out = {}
    for line in text.splitlines():
        m = re.match(r"^(?:python\s+-m\s+)?pip\s+install\s+(.*)$", line.strip())
        if not m:
            continue
        for tok in m.group(1).split():
            m = re.match(r"^([A-Za-z0-9_.\-]+)==([0-9][0-9A-Za-z.\-]*)$", tok)
            if m:
                out[m.group(1).lower()] = m.group(2)
    return out


def test_m1_ci_installs_pillow_matching_lock():
    """M1：CI 装了 Pillow，且版本与 requirements-lock.txt 逐字一致。"""
    got = _ci_pip_packages(_read(os.path.join(".github", "workflows", "ci.yml")))
    assert got, "ci.yml 的 pip install 行没解析出任何固定版本依赖（解析器或文件结构变了）"
    lock = _lock_version("Pillow")
    assert lock, "requirements-lock.txt 里没有 Pillow==<版本>，无从对齐"
    assert "pillow" in got, (
        "CI 没装 Pillow：tests/test_full_form_frames_v24.py 模块级 import PIL，"
        "collection 阶段就 ImportError（整条流水线红）。实测 CI 依赖：%r" % (got,))
    assert got["pillow"] == lock, "CI 的 Pillow==%s 与 lock 的 ==%s 不一致" % (got["pillow"], lock)


def test_m1_ci_dep_parser_can_fail():
    """控制组：解析器必须真的能判"没装 Pillow / 版本不对"，否则上面那条是空转。"""
    lock = _lock_version("Pillow")
    without = _ci_pip_packages("        pip install PySide6==6.11.2 requests==2.34.2 pytest")
    assert without == {"pyside6": "6.11.2", "requests": "2.34.2"}, without
    assert "pillow" not in without
    assert _ci_pip_packages("python -m pip install --upgrade pip") == {}, "升级 pip 那行不该被当依赖"
    wrong = _ci_pip_packages("pip install Pillow==1.0.0")
    assert wrong.get("pillow") == "1.0.0" and wrong["pillow"] != lock


def test_m1_frames_test_really_imports_pil_unguarded():
    """M1 前提复核：那道素材门的 PIL import 不许退化成 importorskip（跳过=把门丢掉）。"""
    src = _read(os.path.join("tests", "test_full_form_frames_v24.py"))
    assert re.search(r"^from PIL import Image, ImageChops, ImageStat$", src, re.M), \
        "test_full_form_frames_v24.py 的 PIL 导入形态变了，M1 的结论要重新评估"
    assert "importorskip" not in src, "素材质量门被改成 importorskip —— 等于把这道门丢掉"


# ---------------- M2：error.log.bad（隔离文件）要能进门禁、要能被清掉 ----------------

def test_m2_bad_quarantine_counts_as_residue():
    """M2：pet_log._quarantine 隔离出的 .bad 与 .old/.bak 同待遇。"""
    for name in ("error.log.bad", "error.log.old", "error.log.bak", "memory.log.bad"):
        assert chk.user_data_hit(name) == name.rsplit(".", 1)[0], name
        assert chk.residue_hit(name) == name.rsplit(".", 1)[0], name
    # 反例：stem 不是用户数据名的一律不误伤（用户自己的 notes.bad 不算）
    for name in ("notes.bad", "pet_io.py", "README.md"):
        assert chk.user_data_hit(os.path.basename(name)) == "", name
        assert chk.residue_hit(os.path.basename(name)) == "", name


def test_m2_zip_flags_bad_quarantine(tmp_path):
    """M2：发布包里混进 error.log.bad 必须被点名。"""
    z = tmp_path / "bad.zip"
    with zipfile.ZipFile(str(z), "w") as zf:
        for n in ("桌宠.py", "main.py", "python.exe", "assets/", "error.log.bad"):
            zf.writestr(n, "x")
    joined = " ".join(chk.check_zip(str(z), "9.9.9"))
    assert "error.log.bad" in joined, joined
    # 反例对照：同名但 stem 不是用户数据（notes.bad）不该被当成脏东西
    z2 = tmp_path / "clean_name.zip"
    with zipfile.ZipFile(str(z2), "w") as zf:
        zf.writestr("notes.bad", "x")
    assert "notes.bad" not in " ".join(chk.check_zip(str(z2), "9.9.9"))


def test_m2_green_dir_names_bad_quarantine(tmp_path, monkeypatch):
    """M2：绿色版目录里的 error.log.bad 也要点名（它同时是用户的实时数据目录）。"""
    monkeypatch.setattr(chk, "GREEN", str(tmp_path))
    (tmp_path / "pet_lines.py").write_text("x", encoding="utf-8")
    assert chk.check_green_dir() == [], "前提：干净目录必须放行"
    (tmp_path / "error.log.bad").write_text("坏的旧日志", encoding="utf-8")
    fails = chk.check_green_dir()
    assert any("error.log.bad" in f for f in fails), fails
    (tmp_path / "error.log.bad").unlink()
    assert chk.check_green_dir() == []


def _clear_logs_names(src):
    """从 桌宠.py 源码里取出 _clear_logs 传给 _remove_files 的文件名字面量（AST，不靠搜索）。"""
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_clear_logs")
    call = next(n for n in ast.walk(fn) if isinstance(n, ast.Call)
                and getattr(n.func, "id", "") == "_remove_files")
    return {a.value for a in ast.walk(call.args[0])
            if isinstance(a, ast.Constant) and isinstance(a.value, str)}


def test_m2_clear_logs_removes_bad_quarantine():
    """M2：桌宠「清理日志」的删除名单必须含 error.log.bad。"""
    names = _clear_logs_names(_read("桌宠.py"))
    # 正例对照：提取器必须真的拿到了现有名单（拿不到就说明它失效了，断言会失败而不是空转）
    assert {"error.log", "error.log.old", "memory.log"} <= names, "提取器没拿到真实名单：%r" % names
    assert "error.log.bad" in names, \
        "清理日志漏了 pet_log 隔离出的 .bad（可能 512KB+，用户以为擦干净了却永久留存）：%r" % names


def test_m2_clear_logs_extractor_can_fail():
    """控制组：把 .bad 那一项从源码里删掉，提取器必须看得出"名单变短了"。"""
    src = _read("桌宠.py")
    mutated = src.replace('os.path.join(DATA_DIR, "error.log.bad"),\n', "", 1)
    assert mutated != src, "变异没生效（源码形态变了？），控制组失去意义"
    names = _clear_logs_names(mutated)
    assert "error.log.bad" not in names
    assert {"error.log", "error.log.old", "memory.log"} <= names, "变异把别的项一起弄坏了"


def test_m2_clear_api_key_removes_bad_quarantine(tmp_path):
    """M2：清 API Key 的删除名单同样必须含 error.log.bad（行为级：跑真的 clear_api_key）。"""
    import pet_ai

    class _FakePet(object):
        def __init__(self):
            self.balance = type("B", (), {"stop": staticmethod(lambda: None)})()
            self.badge = type("B", (), {"hide": staticmethod(lambda: None)})()
            self._history_lock = threading.RLock()
            self._chat_history = ["旧对话"]
            self._mem_epoch = 0
            self._usage = 0.0
            self._manual_pending = False
            self._shown_balance = None
            self.bubbles = []

        def show_bubble(self, text):
            self.bubbles.append(text)

    removed = []
    cfg = {"api_key": "sk-x", "badge": True, "ai_enabled": True}
    data_dir = str(tmp_path)
    usage = os.path.join(data_dir, "usage.json")
    (tmp_path / "usage.json").write_text("{}", encoding="utf-8")
    (tmp_path / "error.log.bad").write_text("坏的旧日志", encoding="utf-8")
    svc = pet_ai.AIService(
        _FakePet(), None, lambda: cfg, lambda c: None, lambda k: None,
        lambda ps: removed.extend(ps),
        (usage, data_dir, os.path.join(data_dir, "config.json"),
         os.path.join(data_dir, "memory.json")),
        lambda: None, lambda m: None, {})
    svc.clear_api_key()
    assert usage in removed, "清 Key 连 usage.json 都不删了？名单是空的：%r" % (removed,)
    assert os.path.join(data_dir, "error.log") in removed, removed
    assert os.path.join(data_dir, "error.log.bad") in removed, (
        "清 Key 没删 .bad 隔离文件（里面可能留着脱敏前的现场）：%r" % (removed,))


# ---------------- M3：门禁必须看得见 assets 缺失与 repro_quiet.py ----------------

def _full_zip_names():
    """按新门禁的 need 清单造"什么都不缺"的条目（含 assets 全量；_verify_green.py 按设计不进包）。"""
    return [n for n in chk._sync_pairs() if n != "_verify_green.py"] + ["python.exe"]


def _make_zip(path, names, version=None, real_main=True):
    real = ""
    if real_main:
        with open(os.path.join(chk.ROOT, "桌宠.py"), "rb") as f:
            real = f.read().decode("utf-8", "replace")
    with zipfile.ZipFile(str(path), "w") as z:
        for n in names:
            if n == "桌宠.py":
                z.writestr(n, real if real_main else 'VERSION = "%s"\n' % (version,))
            else:
                z.writestr(n, "x")


def test_m3_zip_missing_ten_png_is_flagged(tmp_path):
    """M3：合成包**缺 10 张 idle_full 帧**（真包实测 assets 140/150、idle_full 0 个）必须被点名。"""
    names = _full_zip_names()
    missing = [n for n in names if n.startswith("assets/idle_full")]
    assert len(missing) >= 10, "仓库里没有 idle_full 帧集，用例前提不成立：%r" % (missing,)
    ok = tmp_path / "full.zip"
    _make_zip(ok, names)
    assert chk.check_zip(str(ok), chk.repo_version()) == [], "一张不缺的包必须放行（反例对照）"
    bad = tmp_path / "missing.zip"
    _make_zip(bad, [n for n in names if n not in missing])
    fails = chk.check_zip(str(bad), chk.repo_version())
    joined = " ".join(fails)
    assert "缺关键内容" in joined, fails
    for n in missing:
        assert n in joined, "%s 没被点名：%s" % (n, joined)
    # 只缺 1 张也要报（不是"缺 10 张以上才报"）
    one = tmp_path / "one.zip"
    _make_zip(one, [n for n in names if n != missing[0]])
    assert missing[0] in " ".join(chk.check_zip(str(one), chk.repo_version()))


def test_m3_zip_flags_repro_quiet(tmp_path):
    """M3：合成包含 repro_quiet.py（实测真包根目录就有那份残留）必须被点名。"""
    names = _full_zip_names()
    ok = tmp_path / "ok.zip"
    _make_zip(ok, names)
    assert chk.check_zip(str(ok), chk.repo_version()) == [], "反例对照：不含它必须放行"
    bad = tmp_path / "repro.zip"
    _make_zip(bad, names + ["repro_quiet.py"])
    joined = " ".join(chk.check_zip(str(bad), chk.repo_version()))
    assert "repro_quiet.py" in joined, joined


def test_m3_green_root_dev_scripts_named_but_dev_dir_exempt(tmp_path, monkeypatch):
    """M3：绿色版**根目录**的 repro_*/e2e_*/*_dev*.py 要点名；_dev/ 内的不算。"""
    monkeypatch.setattr(chk, "GREEN", str(tmp_path))
    (tmp_path / "pet_lines.py").write_text("x", encoding="utf-8")
    (tmp_path / "_dev").mkdir()
    (tmp_path / "_dev" / "repro_quiet.py").write_text("x", encoding="utf-8")
    assert chk.green_root_dev_leftovers() == [], "_dev/ 内的脚本被误伤"
    assert chk.check_green_dir() == []
    (tmp_path / "repro_quiet.py").write_text("x", encoding="utf-8")
    (tmp_path / "e2e_full_form.py").write_text("x", encoding="utf-8")
    (tmp_path / "build_dev_tool.py").write_text("x", encoding="utf-8")
    assert chk.green_root_dev_leftovers() == ["build_dev_tool.py", "e2e_full_form.py",
                                              "repro_quiet.py"]
    fails = chk.check_green_dir()
    joined = " ".join(fails)
    assert "repro_quiet.py" in joined and "e2e_full_form.py" in joined, fails
    assert "build_dev_tool.py" in joined, fails
    assert "_dev/repro_quiet.py" not in joined, "子目录不该被算进根目录残留"
    for n in ("repro_quiet.py", "e2e_full_form.py", "build_dev_tool.py"):
        (tmp_path / n).unlink()
    assert chk.check_green_dir() == []


def test_m3_need_covers_every_synced_file():
    """M3：need 与 _sync_pairs() 同源（除按设计不进包的 _verify_green.py 与 python.exe 外）。"""
    pairs = chk._sync_pairs()
    assert any(n.startswith("assets/") for n in pairs), "_sync_pairs 没覆盖 assets/，M3 的修法失效"
    n_assets = len([n for n in pairs if n.startswith("assets/")])
    assert n_assets > 100, "assets 清单过短（%d 条），M3 的修法失效" % n_assets
    import inspect
    src = inspect.getsource(chk.check_zip)
    assert "_sync_pairs()" in src, "check_zip 又退回手写名单/前缀判据了"


# ---------------- L1：静态体检 M 类条目要能解析 ----------------

def test_l1_static_m_class_line_is_parsed():
    """L1：M 类（Signal 参数一致性）失败行必须能解析出来，而不是只打印 stdout 尾巴。"""
    line = ("M 信号 frame_changed(int,int) 连到 _on_frame_changed(int)"
            "（要 1 个）→ emit 时 TypeError @ 桌宠.py:888")
    assert chk._static_fail_lines("检查中...\n" + line + "\n全部完成\n") == [line]
    assert chk._static_fail_lines("只有正常输出\n没有条目\n") == []
    # 与真实产出对齐：_check_static.py 里确实有 "M " 前缀（前缀表不是凭空写的）
    assert '"M ' in _read("_check_static.py")


def test_l1_check_static_returns_m_line_end_to_end(monkeypatch):
    """L1 端到端：静态体检因 M 类失败退出时，check_static 必须把**条目**带出来，
    而不是退化成"静态体检退出码 1；stderr: …"（那正是修复前的行为）。"""
    class _R(object):
        returncode = 1
        stdout = ("检查中...\n"
                  "M 信号 frame_changed(int,int) 连到 _on_frame_changed(int)"
                  "（要 1 个）→ emit 时 TypeError @ 桌宠.py:888\n")
        stderr = ""

    import subprocess as _sp   # check_static 内部 import subprocess → 打同一份模块对象
    monkeypatch.setattr(_sp, "run", lambda *a, **kw: _R())
    fails = chk.check_static()
    assert any("M 信号" in f for f in fails), fails
    assert all("退出码" not in f for f in fails), "退化成打印 stdout 尾巴了：%r" % (fails,)


def test_l1_prefix_list_is_single_source():
    """L1：前缀表只有一个来源（check_static 直接用它解析）。"""
    assert "M " in chk.STATIC_FAIL_PREFIXES
    assert "A " in chk.STATIC_FAIL_PREFIXES and "L " in chk.STATIC_FAIL_PREFIXES


# ---------------- L9：运行时生成的 prompts/*.txt 与 git 忽略规则 ----------------

def _git(*args):
    r = subprocess.run(["git"] + list(args), cwd=chk.ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=30)
    return r.returncode, (r.stdout or "")


def test_l9_untracked_runtime_prompts_are_ignored():
    """L9：运行时生成（未跟踪）的 prompts/*.txt 必须被 .gitignore 覆盖，不再弄脏 git status。"""
    rc, _ = _git("check-ignore", "-q", "prompts/zzz_runtime_generated.txt")
    assert rc == 0, "prompts/*.txt 没进 .gitignore：运行时生成的提示词会弄脏发布前的 git status"
    rc2, _ = _git("check-ignore", "-q", "prompts/custom/zzz_runtime.txt")
    assert rc2 == 1, "prompts/custom/*.txt 不该被一起忽略（用户自建人设要能进仓库）"


def test_l9_prompts_are_untracked_so_editing_them_no_longer_dirties_the_tree():
    """L9 收口（v2.4.1 / A9）：三份人设**不再被跟踪**——它们是运行时生成物。

    旧结论是"已跟踪 → 编辑就弄脏树，本轮明确不做"（下一条用例当时钉的就是这个边界）；
    本轮按交接清单走"不再跟踪"那条路：git rm --cached（本地文件保留）+ .gitignore 的
    prompts/*.txt 生效。此后用户改人设、删文件重生成，都不会再让发布门 check_clean_tree
    判"未提交改动"。能真失败：把 prompts/*.txt 重新 git add 回去，第一条断言立刻红。
    """
    rc, out = _git("ls-files", "prompts")
    assert out.split() == [], "prompts 下还有被跟踪的文件（生成物不该进仓库）：%r" % (out,)
    for name in ("default.txt", "sheshe.txt", "tsundere.txt"):
        rc_i, _ = _git("check-ignore", "-q", "prompts/" + name)
        assert rc_i == 0, "prompts/%s 没被忽略：它会作为未跟踪文件弄脏 git status" % name
        assert os.path.isfile(os.path.join(chk.ROOT, "prompts", name)), \
            "git rm --cached 只该停止跟踪，不该删本地文件：prompts/%s 不见了" % name
    rc_s, out_s = _git("status", "--porcelain", "--", "prompts")
    # 本次"停止跟踪"会留下一次性的已暂存删除（D）直到提交；除此之外**不许**再有任何条目：
    # 出现 " M"（改了内容）或 "??"（未跟踪）就说明忽略规则没生效，用户编辑人设又会挡住发布。
    lines = [x for x in out_s.splitlines() if x.strip()]
    assert all(x.startswith("D ") for x in lines), \
        "prompts 仍在弄脏 git status（除了一次性的已暂存删除）：%r" % (out_s,)
    # 反例对照：prompts/custom/ 下的用户自建人设**要能**进仓库（忽略规则不许一刀切）
    rc_c, _ = _git("check-ignore", "-q", "prompts/custom/zzz_runtime.txt")
    assert rc_c == 1, "prompts/custom/*.txt 被一起忽略了：用户自建人设没法进仓库"


def test_l9_persona_files_are_regenerated_from_builtin_constants(tmp_path, monkeypatch):
    """不跟踪的前提：文件丢了能自动重建（否则等于把默认人设从产品里删掉）。

    这三份文件按设计是 ensure_persona_files() 首启从内置常量写盘的**生成物**，
    仓库里那三份就是这么来的；不跟踪以后，"新克隆的仓库/新解包目录里没有它们"
    必须不影响任何人设功能。
    """
    import pet_log
    import 桌宠 as main

    monkeypatch.setattr(main, "DATA_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(pet_log, "_data_dir", str(tmp_path), raising=False)
    main.ensure_persona_files()
    for pid, text in main.PERSONA_PRESETS.items():
        p = tmp_path / "prompts" / (pid + ".txt")
        assert p.is_file(), "内置人设 %s 没有落地成文件" % pid
        assert p.read_text(encoding="utf-8").strip() == text.strip()
    assert (tmp_path / "prompts" / "custom").is_dir()
    # 只写不覆盖：用户改过的内容不许被重建冲掉（这是"生成物"能被安全不跟踪的另一半理由）
    p = tmp_path / "prompts" / "default.txt"
    p.write_text("我改过的", encoding="utf-8")
    main.ensure_persona_files()
    assert p.read_text(encoding="utf-8") == "我改过的"


# ---------------- A6（v2.4.1）：版本核对与"脏条目全量报告" ----------------

def _vi_text(version, filevers, prodvers):
    """合成一份 version_info.txt（只为喂纯函数，不碰真实文件）。"""
    return ("VSVersionInfo(ffi=FixedFileInfo(filevers=%s, prodvers=%s), kids=[StringFileInfo(["
            "StringTable('040904B0', [StringStruct('FileVersion', '%s'), "
            "StringStruct('ProductVersion', '%s')])])])"
            % (filevers, prodvers, version, version))


_L9_GOOD_CL = "## v2.4.0\n- 新\n\n## v2.3.1\n- 旧\n"


def test_version_problems_reports_each_way_of_forgetting_to_bump():
    """A6：每条判据都要能真报（合成文本即可，全部是纯函数）。"""
    vg = 'check("green version", main.VERSION == "2.4.0")\n'
    # 反例 1：数字版本停在旧版（本轮实测 version_info.txt 正是 2.2.0.0）
    bad = chk.version_problems("2.4.0", _vi_text("2.4.0", "(2, 2, 0, 0)", "(2, 2, 0, 0)"),
                               vg, _L9_GOOD_CL)
    assert any(("数字版本" in x and "filevers" in x) for x in bad), bad
    # 反例 2：filevers 与 prodvers 互相不一致
    bad = chk.version_problems("2.4.0", _vi_text("2.4.0", "(2, 4, 0, 0)", "(2, 5, 0, 0)"),
                               vg, _L9_GOOD_CL)
    assert any("filevers 与 prodvers 不一致" in x for x in bad), bad
    # 反例 3：CHANGELOG 次条 >= VERSION（没升版本，或首条被复制成了上一条）
    bad = chk.version_problems("2.4.0", _vi_text("2.4.0", "(2, 4, 0, 0)", "(2, 4, 0, 0)"), vg,
                               "## v2.4.0\n- 新\n\n## v2.4.0\n- 旧\n")
    assert any("次条" in x for x in bad), bad
    # 反例 4：字符串版本没跟上（老判据，别在重构里丢了）
    bad = chk.version_problems("2.4.0", _vi_text("2.3.1", "(2, 4, 0, 0)", "(2, 4, 0, 0)"),
                               vg, _L9_GOOD_CL)
    assert any("FileVersion" in x for x in bad) and any("ProductVersion" in x for x in bad), bad
    # 正例：全对 → 一条都不报；数字版本少写一段（"2.4"）补零后等价，不许误报
    ok = chk.version_problems("2.4.0", _vi_text("2.4.0", "(2, 4, 0, 0)", "(2, 4, 0, 0)"),
                              vg, _L9_GOOD_CL)
    assert ok == [], ok
    ok2 = chk.version_problems("2.4.0", _vi_text("2.4.0", "(2, 4)", "(2, 4)"), vg, _L9_GOOD_CL)
    assert ok2 == [], ok2


def test_全量脏条目报告(tmp_path):
    """A6 + A12：脏条目报告**全量**（此前 [:8] 截断，第 9 条起永远看不见）。

    memory.log.old（pet_main 的 512KB 轮转产物）必须在残留判据里——它是本轮 A12 的点名项。
    """
    names = ["config.json.%d.tmp" % i for i in range(12)]
    assert len(chk._full_list(names).split(",")) == 12
    assert "config.json.11.tmp" in chk._full_list(names), "第 12 条被截断了"
    assert "共 12 条" in chk._full_list(names)
    assert chk._full_list(["a", "b"]) == "a, b"        # 少条目时不加尾巴（别噪音化）
    # 绿色版目录真跑：11 个残留必须全部点名，常规用户数据一个都不点名
    for n in ["memory.log.old", "error.log.bad", "config.json.12345.678.tmp", "roles.json.bak",
              "usage.json.migrated"] + ["lines.json.%d.tmp" % i for i in range(6)]:
        (tmp_path / n).write_text("x", encoding="utf-8")
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    got = chk.green_residue(str(tmp_path))
    assert "memory.log.old" in got, "memory.log 轮转产物不在残留判据里（A12）"
    assert "config.json" not in got and "memory.log" not in got, "常规用户数据被点名了：%r" % (got,)
    assert len(got) == 11, got
    assert len(chk._full_list(got).split(",")) == 11, "残留报告仍在截断：%r" % (chk._full_list(got),)
