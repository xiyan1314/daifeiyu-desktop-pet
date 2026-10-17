# -*- coding: utf-8 -*-
"""崩溃自动重启判定层（pet_guard.py · v2.11.0 · W3-c）的判据。

来路：用户 #194 提交的附件方案 + 2026-10-16 用户裁决并入 v2.11.0
（登记：_dev/REMAINING.md 十三 ④）。**不是"用户原话要求"。**

本文件覆盖任务书要求的 8 条判据，一条一个块，每块标注"能真失败"（拿掉/改坏哪一行会红）：

    ① 正常退出不重启 ................ test_正常退出不重启 + 两个反例
    ② 首次异常退出重启（delay>0）..... test_首次异常退出_重启且延迟为正 + now 必填
    ③ 窗口内达上限不重启 + 人话 ...... test_窗口内达上限_不重启且reason是人话
    ④ 退避递增 ....................... test_退避随窗口内次数递增 + 封顶
    ⑤ 窗口滑过计数失效 ............... test_窗口滑过之后计数失效 + 半开区间
    ⑥ 时钟倒退不崩 ................... test_时钟倒退不站队 + 时钟坏掉
    ⑦ 坏参数安全侧 ................... test_坏参数一律不抛 + 退出码边界 + 垃圾条目
    ⑧ 标记文件往返 ................... test_标记写读往返 + 坏 JSON + 字段归一化

另有 6 条结构判据（不 spawn / 纯函数 / 命令组装 / 路径注入 / 策略壳时钟），见文件末尾。
"""
import ast
import io
import json
import os

import pytest

import pet_guard

# 统一参数：退避 1→2→4，窗口 5 分钟，上限 3 次。判据里的数字都用它，避免各处散落魔数。
BASE = pet_guard.GuardParams(max_restarts=3, window_seconds=300.0,
                             base_delay=1.0, backoff_factor=2.0, max_delay=30.0)
NOW = 1000.0


def _decide(restarts=(), code=3, normal=False, now=NOW, params=BASE):
    """判定的一次调用（把 4 个注入点摊平，读用例时只看变化的那一个）。"""
    return pet_guard.decide_restart(code, normal_exit=normal, restarts=list(restarts),
                                    now=now, params=params)


# ---------------- 判据 ① 正常退出不重启 ----------------
def test_正常退出不重启():
    """判据①。能真失败：把 decide_restart 开头那段 if bool(normal_exit) and code == 0
    整段拿掉 → 落到"允许重启"分支，should_restart 变 True，第一条断言红。"""
    d = _decide(code=0, normal=True)
    assert d.should_restart is False
    assert d.delay_seconds == 0.0
    assert d.notify_user is False and d.tripped is False
    assert "正常退出" in d.reason


def test_退出码0但没有正常退出标记_仍按异常退出走熔断():
    """退出码 0 也可能是 os._exit(0) / 被"结束任务" / 标记还没写：没有标记就不算正常。

    能真失败：把条件改成只看退出码（if code == 0）→ 这条返回 should_restart False，红。"""
    d = _decide(code=0, normal=False)
    assert d.should_restart is True
    assert d.delay_seconds == BASE.base_delay


def test_有正常退出标记但退出码非0_不静默当正常():
    """两个信号都成立才算正常退出。

    能真失败：把条件收窄成 if bool(normal_exit):（不看退出码）→ 这条 should_restart
    变 False，红。"""
    d = _decide(code=3, normal=True)
    assert d.should_restart is True
    assert "异常退出" in d.reason


# ---------------- 判据 ② 首次异常退出重启 ----------------
def test_首次异常退出_重启且延迟为正():
    """判据②。能真失败：把 delay = backoff_delay(len(hits), p) 换成 delay = 0.0
    （或让 backoff_delay 返回 0）→ 第二条断言红（0 延迟 = 热循环）。"""
    d = _decide(code=3)
    assert d.should_restart is True
    assert d.delay_seconds > 0
    assert d.delay_seconds == BASE.base_delay
    assert d.restarts_in_window == 0
    assert "退出码 3" in d.reason and "自动重启" in d.reason


def test_判定必须显式给now_不许偷偷读时钟():
    """判据②的机制面：判定层不许自己读时钟，否则时钟倒退这类判据没法确定性复现。

    能真失败：给 decide_restart 的 now 加一个默认值（例如 now=None 或 now=time.time()）
    → 不再抛 TypeError，红。"""
    with pytest.raises(TypeError):
        pet_guard.decide_restart(3, normal_exit=False, restarts=[])


# ---------------- 判据 ③ 达上限不重启 + 人话 ----------------
def test_窗口内达上限_不重启且reason是人话():
    """判据③。能真失败：把 if len(hits) >= p.max_restarts 改成 > → 第 4 次仍重启，红。"""
    restarts = [NOW - 10.0, NOW - 20.0, NOW - 30.0]
    d = _decide(restarts=restarts)
    assert d.should_restart is False
    assert d.delay_seconds == 0.0
    assert d.tripped is True and d.notify_user is True     # "该告诉用户了"的信号
    assert d.restarts_in_window == 3
    r = d.reason
    # 人话 = 有上限数字 + 为什么停手 + 用户下一步做什么；且不许漏出实现细节（None/nan/字典）
    assert "上限 3 次" in r
    assert "无限重启循环" in r
    assert "手动打开桌宠" in r and "error.log" in r
    assert "None" not in r and "nan" not in r.lower()
    assert len(r) >= 30 and r.endswith("。")


def test_上限前一次仍然重启():
    """能真失败：把阈值改成 max(0, p.max_restarts - 1) → 第 3 次就停手，第一条断言红。"""
    d = _decide(restarts=[NOW - 10.0, NOW - 20.0])
    assert d.should_restart is True
    assert d.restarts_in_window == 2
    assert d.delay_seconds == 4.0        # 同时钉住退避：第 3 次 = 1 * 2**2


# ---------------- 判据 ④ 退避递增 ----------------
def test_退避随窗口内次数递增():
    """判据④。能真失败：把 backoff_delay 里的 p.backoff_factor ** k 改成 ** 0（常数）
    → delays 变成 [1.0, 1.0, 1.0]，相等断言与递增断言双红。"""
    delays = []
    for n in range(3):
        restarts = [NOW - 1.0 - i * 10.0 for i in range(n)]
        d = _decide(restarts=restarts)
        assert d.should_restart is True
        delays.append(d.delay_seconds)
    assert delays == [1.0, 2.0, 4.0]
    assert delays[0] < delays[1] < delays[2]


def test_退避封顶不超过max_delay():
    """能真失败：把 backoff_delay 末尾 if delay > p.max_delay 那段拿掉 → 第 4 次是
    16.0 > 8.0，第二条断言红。"""
    p = pet_guard.GuardParams(max_restarts=8, window_seconds=300.0, base_delay=1.0,
                              backoff_factor=2.0, max_delay=8.0)
    assert pet_guard.backoff_delay(0, p) == 1.0
    assert pet_guard.backoff_delay(3, p) == 8.0
    assert pet_guard.backoff_delay(5, p) == 8.0
    assert pet_guard.backoff_delay("坏", p) == 1.0        # 非数值次数 = 第 0 次


# ---------------- 判据 ⑤ 窗口滑过之后计数失效 ----------------
def test_窗口滑过之后计数失效():
    """判据⑤。能真失败：把 _window_hits 里的 elif delta < window: 改成 elif True:
    （不再判窗口）→ 三条旧记录都算进窗口，should_restart 变 False，第一条断言红。"""
    old = [NOW - 301.0, NOW - 500.0, NOW - 900.0]
    d = _decide(restarts=old)
    assert d.should_restart is True
    assert d.restarts_in_window == 0
    assert d.delay_seconds == BASE.base_delay       # 计数归零 → 退避也回到最短


def test_窗口边界是半开区间():
    """正好等于窗口宽度的记录算"已经滑出"，差一秒仍在窗口里。

    能真失败：把 delta < window 改成 delta <= window → 第一条的 0 变 1，红。"""
    on_edge = _decide(restarts=[NOW - 300.0])
    assert on_edge.restarts_in_window == 0
    inside = _decide(restarts=[NOW - 299.0])
    assert inside.restarts_in_window == 1
    assert inside.delay_seconds == 2.0              # 窗口内已有 1 次 → 第 2 次退避


# ---------------- 判据 ⑥ 时钟倒退不崩 ----------------
def test_时钟倒退不站队_未来时间戳走安全侧():
    """判据⑥。能真失败：把 if future: 那一段整段拿掉 → 返回 should_restart True，红。"""
    d = _decide(restarts=[NOW + 60.0])
    assert d.should_restart is False
    assert d.delay_seconds == 0.0
    assert d.tripped is True and d.notify_user is True
    assert "时钟" in d.reason
    # now 直接被拨回到很早以前（比记录小一大截）：同样不许抛、不许拉
    d2 = _decide(restarts=[1e9], now=-5.0)
    assert d2.should_restart is False
    assert "时钟" in d2.reason


def test_时钟读数坏掉也不崩():
    """能真失败：去掉 decide_restart 里的 if stamp is None: 分支 → 后面 now - t
    对字符串/None 抛 TypeError，红（而且是启动器路径上的异常）。"""
    for bad in (None, "现在", float("nan"), float("inf"), object()):
        d = _decide(restarts=[], now=bad)
        assert d.should_restart is False, bad
        assert d.notify_user is True, bad
        assert "时间" in d.reason, bad


# ---------------- 判据 ⑦ 坏参数安全侧 ----------------
@pytest.mark.parametrize("params", [
    {"max_restarts": 0}, {"max_restarts": -3}, {"max_restarts": "三"},
    {"window_seconds": 0}, {"window_seconds": -5.0}, {"window_seconds": None},
    {"base_delay": 0}, {"base_delay": -1.0}, {"backoff_factor": 0.2},
    {"max_delay": 0.5}, {"max_delay": -1.0},
    None, 42, "不是参数", object(),
])
def test_坏参数一律不抛且落在安全侧(params):
    """判据⑦。能真失败：把 GuardParams.normalize 里任一处兜底去掉（例如 max_restarts 直接
    int(...)、window 直接参与比较）→ 对应参数抛 TypeError/ValueError，红。"""
    d = _decide(params=params)
    assert isinstance(d, pet_guard.RestartDecision)
    assert isinstance(d.reason, str) and d.reason
    if d.should_restart:
        assert d.delay_seconds > 0          # 允许"按文档化默认"，但绝不许 0 延迟热循环
    else:
        assert d.delay_seconds == 0.0


def test_上限设成0或负数等于关闭():
    """熔断参数为 0/负数 = 关闭自动重启（安全侧），且不冒充"熔断告警"。

    能真失败：把 normalize 里 if max_restarts < 0: max_restarts = 0 拿掉 → 归一化后的
    上限仍是 -3，第一条断言（必须夹到 0）红。"""
    assert pet_guard.GuardParams.normalize({"max_restarts": -3}).max_restarts == 0
    assert pet_guard.GuardParams.normalize({"max_restarts": 0}).max_restarts == 0
    for bad in (0, -1, -99):
        d = _decide(params={"max_restarts": bad})
        assert d.should_restart is False
        assert d.notify_user is False and d.tripped is False
        assert "关闭" in d.reason


def test_退出码None或负数不重启():
    """退出码不可判时站安全侧（不拉、但要告诉用户）。

    能真失败：把 if code is None: 与 if code < 0: 两段拿掉 → None 走到"允许重启"
    （code == 0 为假），负数还会被当成崩溃计数，第一条断言红。"""
    for bad in (None, -1, -1073741819, "3", object()):
        d = _decide(code=bad)
        assert d.should_restart is False, repr(bad)
        assert d.notify_user is True, repr(bad)
        assert "手动打开桌宠" in d.reason, repr(bad)


def test_重启历史里的垃圾条目被丢掉():
    """能真失败：把 _clean_timestamps 换成 list(...)（不筛坏值）→ 窗口里混进 None/字符串，
    now - t 抛 TypeError，或者计数变成 7 条，红。"""
    restarts = [None, "x", float("nan"), float("inf"), True, object(), NOW - 10.0]
    d = _decide(restarts=restarts)
    assert d.restarts_in_window == 1
    assert d.should_restart is True


def test_restarts不是序列也不抛():
    """能真失败：把 _clean_timestamps 里的 try/except TypeError 拿掉 → int/None 进 for
    抛 TypeError，红。"""
    for bad in (5, "abc", None, {"a": 1}):
        d = pet_guard.decide_restart(3, normal_exit=False, restarts=bad, now=NOW, params=BASE)
        assert d.should_restart is True, repr(bad)


def test_exit_status_把SystemExit的code归一成进程退出码():
    """main.py 的唯一入口：sys.exit() / sys.exit(0) / sys.exit("msg") / sys.exit(3)。

    能真失败：把末尾 return 1 改成 return 0 → 字符串与对象那两条红。"""
    assert pet_guard.exit_status(None) == 0
    assert pet_guard.exit_status(0) == 0
    assert pet_guard.exit_status(3) == 3
    assert pet_guard.exit_status("出错了") == 1
    assert pet_guard.exit_status(object()) == 1


# ---------------- 判据 ⑧ 标记文件往返 ----------------
def test_标记写读往返逐字节一致(tmp_path):
    """判据⑧。能真失败：把 save_marker 里的 payload = normalize_marker(marker) 改成直接写
    marker，再把一条坏字段塞进去 → 读回来被归一化，相等断言红。"""
    path = str(tmp_path / pet_guard.MARKER_FILENAME)
    m = pet_guard.record_crash(pet_guard.empty_marker(), exit_code=3, now=NOW, will_restart=True)
    m = pet_guard.record_crash(m, exit_code=-1, now=NOW + 5.0, will_restart=False)
    assert pet_guard.save_marker(path, m) is None
    got = pet_guard.load_marker(path)
    assert got == pet_guard.normalize_marker(m)
    assert got["crash_count"] == 2
    assert got["restarts"] == [NOW]                  # 只有 will_restart=True 那一次
    assert got["last_exit_code"] == -1
    assert got["last_crash_at"] == NOW + 5.0
    # 盘上的内容本身必须是"已归一化"的：喂一份带坏字段的标记进去，写出来的 JSON
    # 不许留着字符串计数 / 垃圾时间戳（否则下一个读的人（可能是旧版本）还得自己再归一化一遍）
    junk = {"crash_count": "3", "restarts": [1, "坏", None, True], "last_exit_code": "x"}
    assert pet_guard.save_marker(path, junk) is None
    on_disk = json.loads(io.open(path, encoding="utf-8").read())
    # 字符串计数不是数值 → 归一化成 0（安全默认）；重点是盘上**不许**留着 "3"
    assert on_disk["crash_count"] == 0 and isinstance(on_disk["crash_count"], int)
    assert on_disk["restarts"] == [1.0]
    assert on_disk["last_exit_code"] is None
    assert pet_guard.save_marker(path, m) is None
    # 再写一遍：字节完全一致（幂等写；diff 里不会出现无意义 churn）
    first = io.open(path, "rb").read()
    assert pet_guard.save_marker(path, m) is None
    assert io.open(path, "rb").read() == first
    # 原子写不留 tmp
    assert [n for n in os.listdir(str(tmp_path)) if n.endswith(".tmp")] == []


def test_坏JSON退回安全默认且不抛且不覆盖(tmp_path):
    """判据⑧。能真失败：去掉 load_marker 里的 try/except（或改成裸 json 读）→ 半截 JSON
    抛 JSONDecodeError，红；把"读侧不修补"改成顺手回写 → 第三条断言红。"""
    p = tmp_path / "crash_recovery.json"
    bad = '{"crash_count": 2, "restarts": [1, 2'
    p.write_text(bad, encoding="utf-8")
    assert pet_guard.load_marker(str(p)) == pet_guard.empty_marker()
    assert p.read_text(encoding="utf-8") == bad        # 读侧一个字节都不动
    for raw in ("null", "[]", '"x"', "3", "{}"):
        p.write_text(raw, encoding="utf-8")
        assert pet_guard.load_marker(str(p)) == pet_guard.empty_marker(), raw
    # 文件不存在 / 路径为空（调用方没给数据目录）
    assert pet_guard.load_marker(str(tmp_path / "nope.json")) == pet_guard.empty_marker()
    assert pet_guard.load_marker("") == pet_guard.empty_marker()
    assert pet_guard.save_marker("", {}) is not None    # 写不出去 → 返回错误字符串，但不抛


def test_标记里的坏字段被逐字段归一化(tmp_path):
    """能真失败：把 _clean_timestamps(raw.get("restarts")) 换成 list(...) →
    坏/None/True 留在列表里，相等断言红（后面窗口数学也会吃到脏值）。"""
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"schema": "x", "crash_count": -5,
                             "restarts": [1, "坏", None, True, 2.5],
                             "last_exit_code": "3", "last_crash_at": "昨天"}),
                 encoding="utf-8")
    got = pet_guard.load_marker(str(p))
    assert got["schema"] == pet_guard.MARKER_SCHEMA
    assert got["crash_count"] == 0                    # 负数不许原样留在盘上
    assert got["restarts"] == [1.0, 2.5]
    assert got["last_exit_code"] is None and got["last_crash_at"] is None
    # NaN / Infinity 是 Python json 能读出来的"合法"文本：必须当脏值丢掉
    p.write_text('{"restarts": [NaN, Infinity, -Infinity, 7]}', encoding="utf-8")
    assert pet_guard.load_marker(str(p))["restarts"] == [7.0]


def test_重启历史超过上限只留最近的():
    """能真失败：把 normalize_marker 里的 [-MAX_KEPT_RESTARTS:] 拿掉 → 99 条全留，红。"""
    got = pet_guard.normalize_marker({"restarts": list(range(1, 100))})
    assert len(got["restarts"]) == pet_guard.MAX_KEPT_RESTARTS
    assert got["restarts"][-1] == 99.0 and got["restarts"][0] == 36.0


def test_正常退出清零崩溃计数与重启窗口():
    """能真失败：把 record_clean_exit 里的 m["restarts"] = [] 拿掉 → 关一次桌宠后旧窗口
    还压着，第二条断言红。"""
    m = {"crash_count": 5, "restarts": [1.0, 2.0], "last_exit_code": 3, "last_crash_at": 9.0}
    got = pet_guard.record_clean_exit(m, now=NOW)
    assert got["crash_count"] == 0
    assert got["restarts"] == []
    assert got["last_exit_code"] == 0 and got["last_clean_at"] == NOW
    assert got["last_crash_at"] == 9.0                # 历史崩溃时间保留（取证用）
    assert m["crash_count"] == 5                      # 入参没被改（纯函数）


def test_标记路径由调用方注入_不写死数据目录():
    """能真失败：把 marker_path 改成写死某个绝对路径（或 os.path.join(DATA_DIR, ...)）→
    第一条断言红。"""
    assert pet_guard.marker_path(r"E:\某用户数据") == os.path.join(
        r"E:\某用户数据", "crash_recovery.json")
    assert pet_guard.MARKER_FILENAME == "crash_recovery.json"
    for bad in ("", None, "   ", 123):
        assert pet_guard.marker_path(bad) == "", repr(bad)


# ---------------- 结构判据（判定层的边界） ----------------
BANNED_IMPORTS = {"subprocess", "shlex", "multiprocessing"}
BANNED_ATTRS = {"system", "popen", "spawn", "spawnv", "spawnl", "spawnve",
                "startfile", "fork", "execv", "execvp", "execve"}


def test_本模块不许自己拉起进程():
    """判定层一旦偷偷 spawn，"要不要重启"就没法确定性测了（而且会真的起进程）。

    能真失败：在 pet_guard.py 里加一行 import subprocess（或任何 os.system(...)、
    os.startfile(...)）→ 对应断言红。"""
    src = io.open(pet_guard.__file__, encoding="utf-8").read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                assert a.name.split(".")[0] not in BANNED_IMPORTS, a.name
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] not in BANNED_IMPORTS, node.module
        elif isinstance(node, ast.Attribute):
            assert node.attr not in BANNED_ATTRS, "pet_guard 里出现了拉起进程的入口: " + node.attr


def test_判定是纯函数_重复调用相等且不改入参():
    """能真失败：decide_restart 里对 restarts 做原地排序/append → 第二条红；
    返回值里掺时间相关的东西（随机抖动、读时钟）→ 第一条红。"""
    restarts = [NOW - 10.0, NOW - 25.0]
    before = list(restarts)
    # 直接把**同一个 list 对象**喂进去（不经 _decide 复制）：函数内部若原地 sort/append 才抓得住
    d1 = pet_guard.decide_restart(3, normal_exit=False, restarts=restarts, now=NOW, params=BASE)
    d2 = pet_guard.decide_restart(3, normal_exit=False, restarts=restarts, now=NOW, params=BASE)
    assert d1 == d2
    assert restarts == before
    assert d1.as_dict() == d2.as_dict()
    assert json.dumps(d1.as_dict(), ensure_ascii=False)    # 能直接进日志


def test_重启命令行组装():
    """能真失败：把 restart_command 开头 if not exe: return () 拿掉 →
    空 exe 会拼出 ("--guard-restart",)，第三条断言红。"""
    exe = r"C:\Python310\python.exe"
    entry = r"E:\deep seek\desktop-pet\main.py"
    assert pet_guard.restart_command(exe, entry) == (exe, entry, pet_guard.RESTART_FLAG)
    assert pet_guard.restart_command(exe) == (exe, pet_guard.RESTART_FLAG)   # 冻结版无入口脚本
    assert pet_guard.restart_command("") == ()
    assert pet_guard.restart_command(None) == ()
    assert pet_guard.restart_command(exe, entry, ["--guard-restart"]) == \
        (exe, entry, pet_guard.RESTART_FLAG)                                  # flag 不重复
    assert pet_guard.restart_command(exe, entry, [None, 3, "--x"]) == \
        (exe, entry, "--x", pet_guard.RESTART_FLAG)                           # 坏参数被丢掉
    cmd = pet_guard.restart_command(exe, entry)
    assert all(isinstance(a, str) for a in cmd)          # 全程 list 形态，不经过 shell


def test_is_guard_launch_认标记():
    """能真失败：把 environ 那条分支的 == "1" 改成 in ("1", "0") → 最后一条红。"""
    assert pet_guard.is_guard_launch(["pet.exe", pet_guard.RESTART_FLAG], environ={}) is True
    assert pet_guard.is_guard_launch(["pet.exe"], environ={pet_guard.GUARD_RESTART_ENV: "1"}) is True
    assert pet_guard.is_guard_launch(["pet.exe"], environ={}) is False
    assert pet_guard.is_guard_launch([], environ={pet_guard.GUARD_RESTART_ENV: "0"}) is False
    assert pet_guard.is_guard_launch(5, environ={}) is False            # 坏 argv 不抛
    assert pet_guard.is_guard_launch(["pet.exe"], environ=[]) is False  # 坏 environ 不抛


def test_策略壳用注入时钟_确定性地跑():
    """能真失败：SupervisorPolicy.__init__ 里把 clock if callable(clock) else time.time
    改成总是 time.time（吃掉注入）→ 第二条断言（delay 2.0）红。"""
    t = {"v": 100.0}
    pol = pet_guard.SupervisorPolicy(params=BASE, clock=lambda: t["v"])
    d1 = pol.decide(3, normal_exit=False)
    assert d1.should_restart is True and d1.delay_seconds == 1.0
    assert pol.note_restart() is True
    t["v"] = 101.0
    d2 = pol.decide(3, normal_exit=False)
    assert d2.delay_seconds == 2.0
    assert pol.restarts() == (100.0,)
    # 显式 now 优先于注入时钟（测试全靠它确定性地跨窗口）
    d3 = pol.decide(3, normal_exit=False, now=1000.0)     # 900 秒后：窗口已滑过
    assert d3.restarts_in_window == 0 and d3.delay_seconds == 1.0


def test_正常退出后策略壳也要清历史():
    """标记与策略壳是两份状态：常驻启动器在正常退出后必须把内存里的历史一起清掉。

    能真失败：把 forget_restarts 里的 self._restarts = [] 拿掉 → 第二条断言红
    （历史还压着，用户正常关过一次再崩却被判"已达上限"）。"""
    pol = pet_guard.SupervisorPolicy(params=BASE, clock=lambda: NOW)
    pol.adopt_marker({"restarts": [NOW - 10.0, NOW - 20.0, NOW - 30.0]})
    assert pol.decide(3, normal_exit=False).should_restart is False      # 满 3 次：熔断
    pol.forget_restarts()
    d = pol.decide(3, normal_exit=False)
    assert d.should_restart is True and d.delay_seconds == 1.0
    assert pol.restarts() == ()


def test_策略壳的时钟抛异常也不崩():
    """能真失败：把 now() 里的 try/except 拿掉 → RuntimeError 冒到调用方，红。"""
    def boom():
        raise RuntimeError("时钟坏了")

    pol = pet_guard.SupervisorPolicy(params=BASE, clock=boom)
    d = pol.decide(3, normal_exit=False)
    assert d.should_restart is False and d.notify_user is True
    assert pol.note_restart() is False
    assert pol.restarts() == ()


def test_adopt_marker_接管历史():
    """能真失败：adopt_marker 里不做 normalize（直接 marker["restarts"]）→ 喂 "坏的" 时
    抛 AttributeError/KeyError，最后一条断言红。"""
    pol = pet_guard.SupervisorPolicy(params=BASE, clock=lambda: 1000.0)
    pol.adopt_marker({"restarts": [990.0, 980.0, 970.0]})
    d = pol.decide(3, normal_exit=False)
    assert d.should_restart is False and "上限" in d.reason
    pol.adopt_marker({"restarts": "坏的"})
    assert pol.restarts() == ()
