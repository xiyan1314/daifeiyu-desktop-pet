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


def failed_nodeids(out):
    """pytest 输出里的失败用例名：`tests/x.py::test_y[id] - 说明` → `test_y[id]`。

    v2.4.4：参数化后缀**保留**（判定那边按基名比对，见 mutate_check._short）——这里剥掉就
    再也看不出红的是哪个参数实例了。
    """
    return [ln.split("::")[-1].split(" ")[0]
            for ln in (out or "").splitlines() if ln.startswith("FAILED ")]


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
    """
    return [ln for ln in (out or "").splitlines()
            if ln.startswith("ERROR ") and "::" in ln]


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
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write(chr(10))
    return path


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
    for rel in ("桌宠.py", "pet_export.py", "pet_lines.py", "pet_alarm.py", "pet_behaviors.py",
                "_check_release.py", "pet_balance.py", "pet_plugin.py", "pet_plugin_host.py",
                "pet_dialogs.py", "pet_menu.py", "pet_plugin_index.py", "pet_ai.py", "pet_config.py"):
        p = os.path.join(base, rel)
        if os.path.isfile(p):
            with open(p, "rb") as f:
                out[rel] = hashlib.sha256(f.read()).hexdigest()[:12]
    return out
