# -*- coding: utf-8 -*-
"""变异验证公共设施（v2.4.2 · 第三轮找茬收口）：在 %TEMP% 影子副本里变异，真实仓库只读。

为什么要有它（本轮真实事故）：以前 _dev/mutate_*.py 一律**原地覆写**产品源码
（精确替换 → 跑 pytest → finally 还原）。正常路径没问题，但两条真实事故：
  ① 变异窗口里如果别的进程正好跑全量门，会看到来源不明的红（"看似测试污染"），
     本轮为此浪费了两位审查员的时间——他们看到的红其实是"素材被删 + 变异残留"叠加；
  ② 脚本被 Ctrl-C / 强杀时 finally 不一定跑得到（SIGKILL 就没有），磁盘上会留下
     半变异的产品源码，而 git status 只会说"有未提交改动"。
现在：仓库整体复制到 %TEMP% 影子副本（不含 .git/绿版/构建产物），变异与 pytest 全在
影子里做；真实仓库**只写一个运行锁** _dev/.mutation.lock 供发布门提示"此刻结果不可信"。

用法：
    from _mutate_lib import shadow, run_pytest, last_line, write_results
    with shadow(what="mutate_x") as tree:          # tree = 影子仓库根（随便改）
        rc, failed, out = run_pytest(tree, ["tests/test_x.py"])
结果 JSON 一律写回**真实仓库**的 _dev/（M7：ID / 判定 / rc / 末行 / 时间戳）。
"""
import ast
import contextlib
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCK_NAME = ".mutation.lock"

# 本进程里每个仓库根已持有的锁层数（v2.4.3 质量审查 L3：同进程**嵌套**调用时，
# 内层 finally 会把外层的锁一起删掉——文件名是 <pid>.json，两层用同一个名字。
# 跨进程不受影响（各写各的 pid 文件）；这里用引用计数，最外层退出才真删。）
_LOCK_DEPTH = {}

# 不进影子副本的东西：缓存、打包产物、绿色版目录（几十上百 MB）。
#
# v2.5.0 第 3 轮（质量审查 M1）：此前还把 **.git 与 _verify_assets** 也排除了 —— 影子副本
# 于是与真仓**不等价**，3 条用例在影子里**永久必红**：
#   · tests/test_release_chain_v24.py 的两条 L9（git check-ignore / git ls-files prompts）
#     需要 .git；· tests/test_voice.py 需要 _verify_assets/sample.mp4。
# 后果三条：①任何"以全量套件为判据"的 spec 在影子里基线只能记 BASELINE-RED；②这 3 条
# 结构上永远进不了变异覆盖；③别人会把影子里的 3 红读成"测试污染"（为此排查过两次）。
# 实测两者合计只有 **8.9 MB / 381 文件**（.git 8.8MB/379 + _verify_assets 0.1MB/2），
# 复制成本可忽略，所以直接带上。注意：影子里变异的文件会让影子内的 git status 变脏 ——
# 上面那两条用例只用 check-ignore / ls-files（与工作树状态无关），实测影子全量 = 真仓全量。
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".idea", ".vscode",
             "build", "dist", "大肥鱼桌宠_绿色版"}
SKIP_FILES = {LOCK_NAME}


def _ignore(_dir, names):
    return [n for n in names
            if n in SKIP_DIRS or n in SKIP_FILES or n.endswith(".pyc") or n.endswith(".pyo")]


def shadow_repo(root=None, prefix="dfy_mut_"):
    """真实仓库 → %TEMP% 影子副本，返回影子仓库根路径（调用方负责删）。"""
    src = os.path.abspath(root or ROOT)
    holder = tempfile.mkdtemp(prefix=prefix)
    dst = os.path.join(holder, "repo")
    shutil.copytree(src, dst, ignore=_ignore)
    return dst


@contextlib.contextmanager
def mutation_lock(root, what):
    """真实仓库里放运行锁：发布门（_check_release.mutation_lock_problems）据此拒绝判定。

    锁是**目录** _dev/.mutation.lock/，里面一个持有者一个 <pid>.json——同时跑两个变异脚本
    时互不覆盖、各删各的。此前是单文件锁：后写的顶掉先写的，先结束的那个又无条件 os.remove，
    于是出现过"变异还在跑、发布门却看不见锁"（实测踩到过）。退出时只删自己的文件，
    目录空了才跟着删掉。
    """
    repo = os.path.abspath(root)
    lockdir = os.path.join(repo, "_dev", LOCK_NAME)
    mine = os.path.join(lockdir, "%d.json" % os.getpid())
    depth = _LOCK_DEPTH.get(repo, 0)
    if depth == 0:                   # 只有最外层真的建锁；嵌套层只加计数
        if os.path.isfile(lockdir):  # 兼容旧版单文件锁：那是没有进程持有的残留
            try:
                os.remove(lockdir)
            except OSError:
                pass
        os.makedirs(lockdir, exist_ok=True)
        with open(mine, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "what": what,
                       "started_at": time.strftime("%Y-%m-%d %H:%M:%S")}, f,
                      ensure_ascii=False)
    _LOCK_DEPTH[repo] = depth + 1
    try:
        yield mine
    finally:
        left = _LOCK_DEPTH.get(repo, 1) - 1
        if left > 0:                 # 还有外层持有者：不删锁（v2.4.3 质量审查 L3）
            _LOCK_DEPTH[repo] = left
        else:
            _LOCK_DEPTH.pop(repo, None)
            try:
                os.remove(mine)
            except OSError:
                pass
            try:
                os.rmdir(lockdir)    # 只有空了才删得掉（别人还持有时 OSError → 忽略）
            except OSError:
                pass


@contextlib.contextmanager
def shadow(root=None, what="mutation"):
    """影子副本 + 真实仓库运行锁。yield 影子仓库根路径。"""
    repo = os.path.abspath(root or ROOT)
    with mutation_lock(repo, what):
        tree = shadow_repo(repo)
        try:
            yield tree
        finally:
            shutil.rmtree(os.path.dirname(tree), ignore_errors=True)


_SUMMARY_MARK = "short test summary info"


def summary_lines(out):
    """pytest 输出的 **short test summary info 段**里的行（判定只认这一段）。

    v2.10.0 第 8 轮（代理 C · 找茬审查 P2-1 修复）：此前 failed_nodeids / test_error_lines
    **扫的是整份输出**，而 pytest 还会把**失败用例的 Captured log/stdout** 原样打印出来——
    那行也以 ERROR（或 FAILED）开头。实测复现（真 pytest；样本与 tests/test_mutate_harness_v244.py
    里那条回归用例同款）：

        def test_pinned(): assert True
        def test_other():
            logging.error("boom see tests/test_x.py::test_pinned - noise")
            assert 1 == 2

    输出里真有一行
        ERROR    root:test_x.py:10 boom see tests/test_x.py::test_pinned - noise
    旧实现把它读成"test_pinned error 了" → **pinned 用例全过却判成 CAUGHT（假阳性）**。
    现在按段收窄：只读 short summary 段。

    找不到这一段（输出被截断 / pytest 超时折叠 / 压根没跑到汇总）时**退回全量扫描**——
    那是旧行为，不会比原来更差。
    """
    lines = (out or "").splitlines()
    for i, ln in enumerate(lines):
        if _SUMMARY_MARK in ln:
            return lines[i + 1:]
    return lines


def failed_nodeids(out):
    """pytest 输出里的失败用例 nodeid：`FAILED tests/x.py::test_y[id] - 说明` →
    `tests/x.py::test_y[id]`（**文件前缀 + 参数化后缀都保留**）。

    v2.4.4：参数化后缀**保留**（判定那边按基名比对，见 mutate_check._split）——这里剥掉就
    再也看不出红的是哪个参数实例了。
    v2.10.0（找茬 P2-1）：只读 short summary 段，见 summary_lines 的 docstring。
    v2.11.0 第 9 轮（代理 C · 任务 V3）：**文件前缀也保留** —— 判定要带文件路径比，
    否则 spec 写 `tests/test_a.py::test_x`、红的是 `tests/test_b.py::test_x` 也会算命中
    （跨文件顶替，独立验收造出过反例）。
    """
    names = []
    for ln in summary_lines(out):
        if not ln.startswith("FAILED "):
            continue
        node = ln[len("FAILED "):].split(" - ")[0].strip()
        if node:
            names.append(node)
    return names


def run_pytest(tree, tests, timeout=600):
    """在影子里跑指定用例 → (rc, 失败用例名列表, 完整输出)。

    timeout 默认 600s（v2.8.0 第 6 轮 · 代理 C 从 1800 收紧）：一条变异把用例推进不会退出的
    模态框时，超时是**唯一**的止损点；1800s 会让整批多烧半小时。全量套件本身 2~4 分钟，
    单条变异跑的只是它的子集，600s 已经非常宽松。超时折成 rc=3（见下面的 except）。
    """
    cmd = [sys.executable, "-m", "pytest"] + list(tests) + [
        "-o", "addopts=", "-q", "--no-header", "-p", "no:cacheprovider"]
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)      # 别让真实仓库从 PYTHONPATH 漏进影子（会盖住变异）
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        p = subprocess.run(cmd, cwd=tree, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=timeout, env=env)
    except subprocess.TimeoutExpired as e:
        # v2.8.0 第 6 轮（代理 C）：变异把用例推进一个**不会退出的模态框**时（offscreen 下的
        # 真 QMessageBox.exec()），这一跑会一直挂到 timeout。此前 TimeoutExpired 直接冒泡 →
        # 整批 mutate_check 当场崩掉、**后面的变异一条都跑不到**（本轮实测：89 条那批在第 8 条
        # 报销，白烧 20 分钟）。现在折成 rc=3 + 一句说明：判定自然落 WRONG TEST（= 这条没被
        # 验证），批次照常跑完，超时那条也不会被误读成"通过"。
        part = e.stdout if isinstance(e.stdout, bytes) else b""
        out = part.decode("utf-8", "replace")
        return 3, [], (out + "\n[MUTATE-HARNESS] 影子里的 pytest 超时（%ss）——这条变异没被"
                             "验证（多半是变异把用例推进了不会退出的模态框）" % timeout)
    out = p.stdout.decode("utf-8", "replace")
    return p.returncode, failed_nodeids(out), out


def test_error_lines(out):
    """pytest 输出里"某个具体用例 error"的行（**收集期**错误不算：那是变异本身不合法，
    不是用例检出）。rc=2 但有这种行 → 用例在 setup/call 里抛了，仍算"被检出"。

    这条函数一直存在，但直到 v2.10.0 第 8 轮才接进判定（见 errored_nodeids / mutate_check.judge）。
    v2.10.0（找茬 P2-1）：只读 short summary 段——Captured log 回声里也有一模一样开头的行。
    """
    return [ln for ln in summary_lines(out)
            if ln.startswith("ERROR ") and "::" in ln]


def errored_nodeids(out):
    """pytest 输出里**点名到具体用例**的 ERROR 行 → nodeid（与 failed_nodeids 同口径：
    **文件前缀 + 参数化后缀都保留**）。

    v2.10.0 第 8 轮（代理 C · 任务 R5）：判定要认"用例在 setup/call 里抛异常"这种检出。
    实测输出形态（pytest，-q）：
        ERROR tests/x.py::test_y - AttributeError: no attribute _state_label     ← 认
        ERROR tests/x.py - Failed: 'yield' keyword is allowed in fixtures...     ← 不认（整文件收集期）
    只认前者：后者说明**变异本身不合法**（源码语法/收集就炸），不是用例检出——这条边界与
    test_error_lines 里那句"收集期错误不算"完全一致。
    """
    names = []
    for ln in test_error_lines(out):
        rest = ln.split(" ", 1)[1] if " " in ln else ""
        node = rest.split(" - ")[0].strip()
        if node:
            names.append(node)          # V3：整条 nodeid（文件前缀留着给判定比）
    return names


def test_error_phases(out):
    """{用例名: setup/call/teardown} —— 从 ERRORS 段的小标题解析，**只用于证据可读性**，不参与判定。

    标题形态实测：一连串下划线包着的 -- ERROR at setup of test_setup_error --。
    判据不依赖相位（口径是"这条用例没通过"），但复核的人应该能一眼看出"是调用期炸的，
    不是收尾时炸的"——这就是把相位也记下来的全部理由。
    """
    phases = {}
    for ln in (out or "").splitlines():
        s = ln.strip().strip("_").strip()
        if s.startswith("ERROR at ") and " of " in s:
            head, name = s.split(" of ", 1)
            phases[name.strip()] = head[len("ERROR at "):].strip()
    return phases


def error_phase(nodeid, phases):
    """这条 error 是哪一相位（setup / call / teardown）；查不到 → None。

    v2.11.0 第 9 轮（代理 C · 任务 V2）：相位表来自 test_error_phases（pytest ERRORS 段的
    小标题，形如 `ERROR at teardown of test_x[参数]`）。小标题里的用例名是 **head_line
    （domain）**：顶层函数就是 `test_x[参数]`，类方法写作 `TestX.test_x[参数]`（点号），
    而 errored_nodeids 抽出来的是 `TestX::test_x[参数]`（双冒号）——两种形态都在这里归一。
    """
    if not phases:
        return None
    raw = str(nodeid).split(" ")[0]
    rest = raw.split("::", 1)[1] if "::" in raw else raw
    for key in (rest, rest.replace("::", "."), rest.split("::")[-1]):
        if key in phases:
            return phases[key]
    return None


def split_teardown_errors(errors, phases):
    """(算检出的 error, **teardown 期**被排除的 error)。

    v2.11.0 第 9 轮（代理 C · 任务 V2）：判据从"ERROR 行一律算检出"收紧到 **setup/call 期
    才算** —— teardown 期 error 的汇总行是 "3 passed, 1 error"，**error 的那条用例在 passed 里**
    （用例体已经跑完），把它算检出等于"断言体全过、只有清理炸了"也记 CAUGHT。
    **失败方向是安全的**：相位查不出来（phases 为空 / 输出被截断 / 小标题形态变了）时
    **一律保留** → 与旧口径逐字一致，绝不因为解析失败把检出丢掉。
    """
    kept, dropped = [], []
    for e in (errors or []):
        if error_phase(e, phases) == "teardown":
            dropped.append(e)
        else:
            kept.append(e)
    return kept, dropped


def run_baseline(tree, tests, retries=2, timeout=600, pause_s=3.0):
    """变异前的基线自检：失败时**重跑**再判——时序敏感的用例在冷缓存/并发负载下会偶发抖动。

    实测（v2.4.2 第三轮）：test_startup_defer_v242.py::test_startup_task_is_chunked_not_one_shot
    断言"单轮 < 60ms"，而刚复制出来的影子副本在 C: 上第一遍是冷缓存 + 机器上还有别的会话
    在跑 pytest，出现过 [96.4, 70.3, 97.2, ...] 的首轮耗时 → 基线 1 failed；紧接着重跑就
    0.55~0.99s 全过。这不是变异被发现，是测量环境，所以基线要重跑几次再判。
    返回 (ok, rc, failed, out, note)。
    """
    last = (1, [], "")
    for i in range(retries + 1):
        rc, failed, out = run_pytest(tree, tests, timeout=timeout)
        if rc == 0:
            note = "" if i == 0 else "（第 %d 次才过：前几遍是冷缓存/负载抖动，不是真失败）" % (i + 1)
            return True, rc, failed, out, note
        last = (rc, failed, out)
        if i < retries:
            time.sleep(pause_s)   # 让机器喘一下再重跑（对方会话的 pytest 也在抢 CPU）
    return False, last[0], last[1], last[2], ""


def last_line(out):
    lines = [ln for ln in (out or "").strip().splitlines() if ln.strip()]
    return lines[-1][:160] if lines else ""


def results_payload(title, results, extra=None):
    """结果 dict（质量审查 M7 的口径）：ID / 判定 / rc / 末行 / 时间戳计数。

    v2.4.3（质量审查 M5）：条目可以是 5 元组 (id, verdict, rc, tail, failed)——
    failed 是**这一轮真的红了哪些用例**（判定"预期用例必须在 failed 列表里"的依据），
    4 元组的老调用方照旧（不写 failed 字段）。
    v2.10.0 第 8 轮（代理 C · R5）：可再带第 6 项 errors —— 点名到用例的 ERROR 行。
    判定口径改认它之后，证据里必须留下"当时是哪几行 ERROR"，否则复核的人无从分辨
    "调用期 AttributeError" 与 "收集期就炸"。
    v2.11.0 第 9 轮（代理 C · V2）：可再带第 7 项 errors_teardown —— 被判据**排除**的
    teardown 期 ERROR 行。收紧之后必须让人看得见"哪几条被排除了"，否则复核者只会看到
    "verdict 变了"而找不到原因（口径改了、证据里就得看得见）。
    """
    items = []
    for row in results:
        i, v, rc, tail = row[:4]
        item = {"id": i, "verdict": v, "rc": rc, "tail": tail}
        if len(row) > 4 and row[4] is not None:
            item["failed"] = list(row[4])
        if len(row) > 5 and row[5] is not None:
            item["errors"] = list(row[5])
        if len(row) > 6 and row[6] is not None:
            item["errors_teardown"] = list(row[6])
        items.append(item)
    payload = {
        "title": title,
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(items),
        "caught": len([x for x in items if x["verdict"] == "CAUGHT"]),
        # v2.4.4（兼容审查 L4）：这里此前漏了 "WRONG TEST" → caught + not_caught != total
        # （实测 mutations_compat_v242.json：total 15 / caught 14 / not_caught 0）。
        # 口径与 mutate_check.judge 的 "verdict != CAUGHT" 对齐。
        "not_caught": len([x for x in items if x["verdict"] in
                           ("NOT CAUGHT", "WRONG TEST", "SPEC-BAD", "ANCHOR-LOST", "INVALID")]),
        "blocked": len([x for x in items if x["verdict"] == "BASELINE-RED"]),
        "items": items,
    }
    if extra:
        payload.update(extra)
    return payload


def write_results(path, title, results, extra=None):
    """结果落盘（单独的结果 JSON；spec 内嵌那种见 results_payload）。"""
    payload = results_payload(title, results, extra)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    # newline="" 同 mutate_check._write：别让 Windows 的文本模式把 LF 翻成 CRLF
    # （v2.10.0 质量审查：官方工具回写一次就把"纯 LF 收编"的 spec 变成 325 个 CRLF）。
    with open(path, "w", encoding="utf-8", newline="") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write(chr(10))
    return path


# ---------------- pinned nodeid 的**用例体 AST 摘要**（v2.11.0 第 9 轮 · 代理 C · 任务 V1） ----------------
#
# 它补的是 v2.10.0 R6 剩下的那个洞：R6 给指纹清单补了 12 个"有锚点却零提示"的**产品**文件，
# 但"承载锚点的测试文件"只补了 2 个（它们自己上面有锚点）。实测（python -B _dev/check_pinned_ast.py --probe）：
# 全库 28 份 spec / 489 条变异点名的 **39 个测试文件**里只有 2 个在指纹清单内 → 另 37 个文件 /
# **400 条 pinned nodeid**（其中 390 条在指纹外）的用例体被清空（nodeid 不动）时：
#   · check_mutation_nodeids.py 照样 rc=0（def 还在）；
#   · 文件指纹一声不吭（文件不在清单里）；
#   · 那条变异 CAUGHT → NOT CAUGHT，**静默失效**。
# 所以这里不按"整文件 sha256"钉（那会把同文件里的无关改动也算过期），而是**逐 pinned nodeid**
# 摘用例体的 AST 摘要：
#   · `tests/x.py::test_y` → 只摘 `test_y` 这个 def（**含形参与装饰器**：parametrize/skip 变了
#     也算实质变化；**不含 docstring**：本仓用例的 docstring 里有"变异：…"这类说明，
#     改说明不该刷证据过期）；
#   · 只给文件的旧形态（`tests/x.py`，如 export_slice / startup_defer 两份旧驱动）→ 摘整份模块
#     （模块级与各函数的 docstring 同样不算）。
#   · 注释 / 缩进 / 换行不入 AST → 重排版、加注释都不算；同文件里**别的**用例改动也不算。
# 边界（如实写）：**不钉同文件里的 fixture / 辅助函数**——把 fixture 掏空而用例体不动，本机制不出声
# （那是"整文件"粒度的事；本仓变异语料里目前没有这种形态）。
_AST_CACHE = {}


def _module_ast(root, rel):
    """tests/x.py 的 AST；按 (path, mtime_ns, size) 缓存（同一进程里文件被改过会自动失效）。"""
    path = os.path.join(os.path.abspath(root), rel.replace("/", os.sep))
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (st.st_mtime_ns, st.st_size)
    hit = _AST_CACHE.get(path)
    if hit is not None and hit[0] == key:
        return hit[1]
    try:
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
    except Exception:
        tree = None
    _AST_CACHE[path] = (key, tree)
    return tree


def test_def_names(root, rel):
    """文件里定义的所有用例名（顶层函数 + 类方法）；文件不存在/读不动 → None。"""
    tree = _module_ast(root, rel)
    if tree is None:
        return None
    return {n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def resolve_pin(nodeid, spec_files=(), root=None):
    """nodeid → (文件, 用例名 or None)；解析不了 → None。

    与 `_dev/check_mutation_nodeids.py` 的判据**同源**（那边问"名字还在不在"，
    这边问"该摘哪一段 AST"）：带 "::" 的找文件里的 def；只给文件的旧形态返回 (文件, None)；
    裸用例名在这份 spec 引用过的测试文件里找。
    """
    root = os.path.abspath(root or ROOT)
    raw = str(nodeid or "").strip()
    if not raw:
        return None
    if "::" not in raw:
        if raw.endswith(".py"):
            p = os.path.join(root, raw.replace("/", os.sep))
            return (raw, None) if os.path.isfile(p) else None
        want = raw.split("[", 1)[0].split(".")[-1]
        for rel in sorted(spec_files):
            names = test_def_names(root, rel)
            if names and want in names:
                return (rel, want)
        return None
    rel, func = raw.split("::", 1)
    names = test_def_names(root, rel)
    if names is None:
        return None
    want = func.split("::")[-1].split("[", 1)[0]
    return (rel, want) if want in names else None


def _drop_doc(node):
    """摘掉 node.body 开头的 docstring（说明文字变了不算用例变了）。"""
    body = node.body
    if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        node.body = body[1:] or [ast.Pass()]
    return node


def _strip_docstring(fn):
    return _drop_doc(copy.deepcopy(fn))


def _strip_module_docstrings(tree):
    """整份模块也按同一口径去 docstring（模块级 + 每个函数/类），否则文件粒度会把
    "改一句说明"也报成过期——那与逐用例粒度的精度口径自相矛盾。"""
    tree = copy.deepcopy(tree)
    _drop_doc(tree)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            _drop_doc(node)
    return tree


def _digest_nodes(nodes):
    h = hashlib.sha256()
    for n in nodes:
        h.update(ast.dump(n, annotate_fields=True, include_attributes=False).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:12]


def pin_digest(root, rel, func=None):
    """pinned nodeid 的用例体 AST 摘要（sha256 前 12 位）；文件/用例不存在 → None。

    同名 def 出现多次（类方法重名）时按源码位置排序后**一起**入摘要——那样多一个同名 def
    也算变化（宁可多报，也不漏）。
    """
    tree = _module_ast(root, rel)
    if tree is None:
        return None
    if func is None:                       # 只给文件的旧形态：整份模块（粗粒度，够用）
        return _digest_nodes([_strip_module_docstrings(tree)])
    hits = [n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func]
    if not hits:
        return None
    hits.sort(key=lambda n: (n.lineno, n.col_offset))
    return _digest_nodes([_strip_docstring(n) for n in hits])


def pinned_ast_map(root, nodeids, spec_files=()):
    """{nodeid: 用例体摘要} —— 解析不了的**不写键**（由调用方点名，见 check_pinned_ast.py）。"""
    root = os.path.abspath(root or ROOT)
    out = {}
    for raw in nodeids:
        raw = str(raw)
        if raw in out:
            continue
        hit = resolve_pin(raw, spec_files, root)
        if not hit:
            continue
        d = pin_digest(root, hit[0], hit[1])
        if d:
            out[raw] = d
    return out


def stale_pinned(recorded, current):
    """记录里的 pinned 摘要 vs 当前树 → 不一致项（"nodeid: 旧→新"）。recorded 空/非 dict → []。

    与 stale_fingerprints 同口径：**只比对两边都有的键**——用例被删/改名时当前树算不出摘要，
    那种情况由 nodeid 体检（check_mutation_nodeids.py，rc=1）点名，这里不重复报。
    """
    if not isinstance(recorded, dict) or not recorded:
        return []
    out = []
    for nodeid in sorted(recorded):
        got, want = recorded.get(nodeid), (current or {}).get(nodeid)
        if got and want and got != want:
            out.append("%s: %s→%s" % (nodeid, got, want))
    return out


def repo_fingerprint(root=None):
    """真实仓库当前指纹（结果对应哪份源码）：关键文件 sha256 前 12 位。"""
    base = os.path.abspath(root or ROOT)
    out = {}
    # v2.4.4（任务 1）：清单里原本没有 pet_balance.py —— A-1 改了它、3 条锚点失效，而发布门
    # 一条"证据过期"都不会提示（真盲区）。与 _check_release.MUTATION_FINGERPRINT_FILES 同口径，
    # 由 tests/test_release_check.py 的 test_fingerprint_file_list_matches_the_mutation_lib 钉住。
    # v2.5.1（找茬审查 P3-1）：补进本轮新模块——pet_plugin.py / pet_plugin_host.py /
    # pet_dialogs.py / pet_menu.py。少了它们，改这些文件不会有任何"证据过期"提示
    # （v2.4.4 给 pet_balance.py 补过同一个盲区）。与
    # _check_release.MUTATION_FINGERPRINT_FILES **逐项一致**（顺序也一致），
    # tests/test_release_check.py 有一条用例钉住两处不许漂。
    # v2.6.0（找茬审查 C-5）：补进 pet_plugin_index.py —— 本轮新模块、M-A01~M-A04 的锚点全在
    # 它上面，而它在清单里缺席（与 _check_release.MUTATION_FINGERPRINT_FILES **逐项一致**、
    # 顺序也一致；tests/test_release_check.py 有一条用例钉住两处不许漂）。
    # v2.9.0 第 7 轮（代理 C · 任务 C-2）：补进 pet_ai.py 与 pet_config.py —— 实测**全库 40 条**
    # 变异的锚点落在这两个文件上（pet_ai.py **31** 条 = agent_b_v270 的 9 条 + agent_b_v280 的
    # 7 条（M-B10~B14/B20/B21）+ agent_b_v290 的 2 条（B7-M1/M2）+ critic_v270 的 3 条 +
    # agent_c_v280 的 10 条（M-C-B30~B39）；pet_config.py **9** 条 = agent_b_v270 的 CFG-RETERR
    # 1 条 + agent_b_v280 的 M-B08 1 条 + agent_c_v280 的 6 条（M-C-B08/09/29/40/41/42）+
    # silent_except 的 M-S1 1 条），
    # 而两处清单里都没有它们 → 改这两个文件**一条「证据过期」提示都不会有**（同一盲区第 4 次）。
    # 复现：python -B _dev/probe_fingerprint_gap_v290.py（补前 20 个文件 / 84 条变异零提示）。
    # 补完 14 个键，与 _check_release.MUTATION_FINGERPRINT_FILES 仍逐项一致（同一条用例钉住）。
    # v2.10.0 第 8 轮（代理 C · R6）：补 12 个"有锚点、却零提示"的文件（pet_io.py 一处就 9 条；
    # _check_static.py 按 _check_release.py 已被收进清单的同一条逻辑）。未覆盖从 50 条降到 20 条，
    # 逐条裁决与"为什么另外 9 个文件不进"见 _dev/fingerprint_coverage_v2100.md。
    for rel in ("桌宠.py", "pet_export.py", "pet_lines.py", "pet_alarm.py", "pet_behaviors.py",
                "_check_release.py", "pet_balance.py", "pet_plugin.py", "pet_plugin_host.py",
                "pet_dialogs.py", "pet_menu.py", "pet_plugin_index.py", "pet_ai.py", "pet_config.py",
                "pet_io.py", "pet_services.py", "pet_widgets.py", "pet_resources.py",
                "pet_tools.py", "pet_voice.py", "pet_audio.py", "pet_chat.py",
                "pet_log.py", "pet_actions.py", "pet_book.py", "_check_static.py",
                # v2.11.0 第 9 轮：动效令牌表（后续所有动效都挂在它上面；A 的 spec 有 3 条锚点在它上面）
                # 与 _check_release.MUTATION_FINGERPRINT_FILES **逐项一致**（顺序也一致）。
                "pet_motion.py",
                # v2.10.0 第 8 轮（质量审必修 A）：**承载锚点的两个测试文件**也进清单——
                # 用例体被清空（nodeid 不动）时 check_mutation_nodeids 照样 rc=0，
                # 而变异会静默失效；只有指纹能出声。**不是整个 tests/**（那是噪音）。
                "tests/test_dialog_buttons_v270.py", "tests/test_import_thread.py"):
        p = os.path.join(base, rel)
        if os.path.isfile(p):
            with open(p, "rb") as f:
                out[rel] = hashlib.sha256(f.read()).hexdigest()[:12]
    return out
