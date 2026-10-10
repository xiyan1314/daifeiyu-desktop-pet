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
import contextlib
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

# 不进影子副本的东西：git 元数据（测试不需要，且会让影子里的 status 语义混乱）、
# 缓存、打包产物、绿色版目录（几十上百 MB）。
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".idea", ".vscode",
             "build", "dist", "大肥鱼桌宠_绿色版", "_verify_assets"}
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


def run_pytest(tree, tests, timeout=1800):
    """在影子里跑指定用例 → (rc, 失败用例名列表, 完整输出)。"""
    cmd = [sys.executable, "-m", "pytest"] + list(tests) + [
        "-o", "addopts=", "-q", "--no-header", "-p", "no:cacheprovider"]
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)      # 别让真实仓库从 PYTHONPATH 漏进影子（会盖住变异）
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run(cmd, cwd=tree, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=timeout, env=env)
    out = p.stdout.decode("utf-8", "replace")
    failed = [ln.split("::")[-1].split(" ")[0]
              for ln in out.splitlines() if ln.startswith("FAILED ")]
    return p.returncode, failed, out


def test_error_lines(out):
    """pytest 输出里"某个具体用例 error"的行（**收集期**错误不算：那是变异本身不合法，
    不是用例检出）。rc=2 但有这种行 → 用例在 setup/call 里抛了，仍算"被检出"。
    """
    return [ln for ln in (out or "").splitlines()
            if ln.startswith("ERROR ") and "::" in ln]


def run_baseline(tree, tests, retries=2, timeout=1800, pause_s=3.0):
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
    """
    items = []
    for row in results:
        i, v, rc, tail = row[:4]
        item = {"id": i, "verdict": v, "rc": rc, "tail": tail}
        if len(row) > 4 and row[4] is not None:
            item["failed"] = list(row[4])
        items.append(item)
    payload = {
        "title": title,
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(items),
        "caught": len([x for x in items if x["verdict"] == "CAUGHT"]),
        "not_caught": len([x for x in items if x["verdict"] in
                           ("NOT CAUGHT", "SPEC-BAD", "ANCHOR-LOST", "INVALID")]),
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
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write(chr(10))
    return path


def repo_fingerprint(root=None):
    """真实仓库当前指纹（结果对应哪份源码）：关键文件 sha256 前 12 位。"""
    base = os.path.abspath(root or ROOT)
    out = {}
    for rel in ("桌宠.py", "pet_export.py", "pet_lines.py", "pet_alarm.py", "pet_behaviors.py",
                "_check_release.py"):
        p = os.path.join(base, rel)
        if os.path.isfile(p):
            with open(p, "rb") as f:
                out[rel] = hashlib.sha256(f.read()).hexdigest()[:12]
    return out
