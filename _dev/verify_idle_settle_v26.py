# -*- coding: utf-8 -*-
"""v2.6.0：新回归用例的"牙齿"实测——把收尾兜底改坏，用例必须变红（影子副本里做）。

做法：真仓只写运行锁（_dev/.mutation.lock/），变异与 pytest 全在 %TEMP% 影子副本里。
每条变异跑 tests/test_idle_settle_v26.py，期望**指定用例**出现在失败名单里。
结果写 _dev/results_idle_settle_v26.json。

用法：python -B _dev/verify_idle_settle_v26.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from _mutate_lib import shadow  # noqa: E402

TESTFILE = os.path.join("tests", "test_idle_settle_v26.py")
LOCK = os.path.join(REPO, "_dev", ".mutation.lock")
FAILED_RE = re.compile(r"^FAILED (\S+)", re.M)
SUMMARY_RE = re.compile(r"(\d+) (passed|failed)")

GUARD = ('        if (self.anim_mode == "state" and not self.busy and self._tween_anim is None\n'
         '                and not self._state_timer.isActive() and self.anim._on_finish is None):\n')
GATE_BOTH = "and not self._state_timer.isActive() and self.anim._on_finish is None"
GATE_TIMER = "and not self._state_timer.isActive()"
GATE_FIN = "and self.anim._on_finish is None"

# (id, 文件, 锚点, 变异后, 期望变红的用例（基名）, 说明)
MUTATIONS = [
    ("M-S01", "桌宠.py", GUARD,
     "        if False:  # MUT：收尾不回落待机（= 修前行为）\n",
     ["test_jump_inserted_during_proc_settles_back_to_idle",
      "test_idle_gates_usable_after_interleave"],
     "去掉兜底（回到修前）→ 交错用例与待机入口可用用例都必须红"),
    ("M-S02", "桌宠.py", GATE_BOTH, GATE_FIN,
     ["test_chain_keeps_owner_then_settles_to_idle"],
     "丢掉表情定时器这个主人 → jump 收尾会腰斩表情展示"),
    ("M-S03", "桌宠.py", GATE_BOTH, GATE_TIMER,
     ["test_frame_action_owner_is_not_truncated_by_a_tween_finish"],
     "丢掉帧动作 on_finish 这个主人 → jump 收尾腰斩在播帧动作"),
    ("M-S04", "桌宠.py", '(self.anim_mode == "state" and not self.busy',
     '(self.anim_mode in ("state", "eat") and not self.busy',
     ["test_tween_reset_during_eat_keeps_eat"],
     "把 eat 也当可回落态 → 吃帧被收尾顶掉"),
    ("M-S05", "桌宠.py", "            if self.anim_mode != \"eat\" and not self.busy:\n",
     "            if not self.busy:  # MUT：去掉 eat 例外\n",
     ["test_proc_finish_during_eat_keeps_eat"],
     "去掉 _done 的 eat 例外 → 吃帧在途时回待机（顶掉 _eat_done）"),
]


def run_tests(tree, timeout=900):
    cmd = [sys.executable, "-B", "-m", "pytest", TESTFILE,
           "-o", "addopts=", "-q", "--no-header", "-p", "no:cacheprovider"]
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run(cmd, cwd=tree, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=timeout, env=env)
    out = p.stdout.decode("utf-8", "replace")
    failed = [x.split("::")[-1].split(" ")[0] for x in FAILED_RE.findall(out)]
    m = SUMMARY_RE.search(out)
    return p.returncode, failed, (m.group(0) if m else "?"), out


def main():
    if os.path.exists(LOCK):
        print("ABORT：_dev/.mutation.lock/ 已存在（有别的变异在跑）")
        return 2
    results = []
    with shadow(what="idle_settle_v26") as tree:
        with open(os.path.join(tree, "桌宠.py"), encoding="utf-8") as f:
            real = f.read()
        print("[baseline] 影子副本（含修复）跑新用例 ...", flush=True)
        rc, failed, summary, out = run_tests(tree)
        base_ok = rc == 0 and not failed
        print("[baseline] rc=%s %s failed=%r → %s"
              % (rc, summary, failed, "OK" if base_ok else "BASELINE-RED"), flush=True)
        results.append(("BASELINE", "PASS" if base_ok else "BASELINE-RED", rc, summary, failed))
        if not base_ok:
            print(out[-2000:])
        for mid, rel, anchor, repl, expect, note in MUTATIONS:
            n = real.count(anchor)
            if n != 1:
                results.append((mid, "ANCHOR-LOST", None, "锚点命中 %d 次" % n, []))
                print("[%s] ANCHOR-LOST（%d 次）%s" % (mid, n, note), flush=True)
                continue
            with open(os.path.join(tree, rel), "w", encoding="utf-8") as f:
                f.write(real.replace(anchor, repl))
            t0 = time.time()
            rc2, failed2, summary2, out2 = run_tests(tree)
            hit = [e for e in expect if e in failed2]
            caught = rc2 != 0 and len(hit) == len(expect)
            verdict = "CAUGHT" if caught else "NOT CAUGHT"
            tail = "rc=%s %s failed=%r 命中=%d/%d 用时=%.1fs" % (
                rc2, summary2, failed2, len(hit), len(expect), time.time() - t0)
            results.append((mid, verdict, rc2, tail, hit))
            print("[%s] %-10s %s | %s" % (mid, verdict, note, tail), flush=True)
            if verdict == "NOT CAUGHT":
                print(out2[-1500:])
            with open(os.path.join(tree, rel), "w", encoding="utf-8") as f:
                f.write(real)          # 还原，逐条互不影响
    payload = {
        "title": "v2.6.0 收尾兜底（idle settle）新用例牙齿实测（影子副本）",
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(results) - 1,
        "caught": len([r for r in results[1:] if r[1] == "CAUGHT"]),
        "not_caught": len([r for r in results[1:] if r[1] not in ("CAUGHT",)]),
        "items": [{"id": r[0], "verdict": r[1], "rc": r[2], "tail": r[3], "hit": r[4]}
                  for r in results],
    }
    path = os.path.join(HERE, "results_idle_settle_v26.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write(chr(10))
    ok = (results[0][1] == "PASS"
          and all(r[1] == "CAUGHT" for r in results[1:]))
    print("=" * 60)
    print("变异 %d 条，CAUGHT %d；锁存在=%s"
          % (len(results) - 1, payload["caught"], os.path.exists(LOCK)))
    print("结果: %s" % path)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
