# -*- coding: utf-8 -*-
"""v2.6.0 牙齿实测：把"合成动作/帧动作的收尾与复位"改坏，新判据必须变红（影子副本里做）。

背景：CI #52 的 "proc resets to idle" 是墙钟判据，根因是交互插播时 _done 有意跳过
_play_idle 而 jump 自己的收尾不恢复 anim_mode（anim_mode 永久卡 'state'）。本次把它
改成"主动驱动到终态 + 结构性判据"。这里逐条把复位/收尾逻辑改坏，验证新判据**真的会红**
（改坏不红 = 护栏失明）。

全部在 %TEMP% 影子副本里变异（_dev/_mutate_lib.shadow：真仓只写 _dev/.mutation.lock）。
结果写 _dev/mutations_proc_reset_v26.json。

用法：python -B _dev/mutate_proc_reset_v26.py
"""
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from _mutate_lib import last_line, shadow, write_results  # noqa: E402

# (id, 文件, 锚点原文, 变异后, 期望变红的 check 名, 说明)
MUTATIONS = [
    ("M-P01", "桌宠.py",
     "        anim.finished.connect(lambda: self._finish_tween(cb))\n",
     "        pass  # MUT: finished 不接收尾回调\n",
     ["proc resets to idle"],
     "QVariantAnimation 的 finished 不接 _finish_tween → 复位分支根本不执行"),
    ("M-P02", "桌宠.py",
     "        def _done():\n            self.squash_x = 1.0\n            self.squash_y = 1.0\n"
     "            self._proc_offset_y = 0\n            self._apply_transform()\n",
     "        def _done():\n            self._apply_transform()  # MUT: 不复位变换\n",
     ["proc resets to idle"],
     "_done 的复位分支不执行（形变保留在动画末值/被顶替时的中间值）"),
    ("M-P03", "桌宠.py",
     '            if self.anim_mode != "eat" and not self.busy:\n                self._play_idle()',
     "            if False:  # MUT: 收尾不回待机\n                self._play_idle()",
     ["proc resets to idle"],
     "_done 收尾不回待机 → anim_mode 卡在 'state'（CI #52 的症状本身）"),
    ("M-P04", "桌宠.py",
     "        self._run_anim(int(period * cycles), _onv, on_finished=_done)",
     "        self._run_anim(int(period * cycles), _onv)  # MUT: 收尾走默认 _reset_squash",
     ["proc resets to idle"],
     "合成动作不接自己的收尾回调（默认 _reset_squash 不恢复 anim_mode）"),
    ("M-P05", "桌宠.py",
     "            self._tween_anim = None\n            self._finish_tween(self._tween_finish_cb)",
     "            self._tween_anim = None\n            # MUT: 顶替不跑收尾回调",
     ["proc resets to idle"],
     "被顶替时不跑收尾回调 → 顶替路径的复位丢失（CI #52 走的正是这条）"),
    ("M-P06", "桌宠.py",
     "            self._tween_anim = None\n            self._finish_tween(self._tween_finish_cb)",
     "            self._finish_tween(self._tween_finish_cb)  # MUT: 顶替不清动画槽",
     ["proc resets to idle"],
     "顶替后动画槽不清 → 残留振荡（结构性：_tween_anim 仍指向旧动画）"),
    ("M-P07", "桌宠.py",
     "        cycles = 2  # 播 2 个周期",
     "        cycles = 1  # MUT: 只播 1 个周期",
     ["proc transform applied"],
     "合成动作只播 1 个周期 → 半波段数 4→2（波形结构性判据）"),
    ("M-P08", "桌宠.py",
     "                self.squash_y = 1.0 - amp * 0.6 * ph",
     "                self.squash_y = 1.0  # MUT: 纵向不跟着形变",
     ["proc transform applied"],
     "sway 的 squash_y 分量不生效 → 振幅判据（sy 上界/下界）"),
    ("M-P09", "pet_actions.py",
     "            pet.anim.play(name, interval, loops=1, on_finish=pet._play_idle)",
     "            pet.anim.play(name, interval, loops=-1, on_finish=pet._play_idle)  # MUT",
     ["frame action back to idle"],
     "命名帧动作改成无限循环 → 永远不回调收尾、不回待机"),
    ("M-P10", "pet_anim.py",
     "            cb, self._on_finish = self._on_finish, None\n            if cb:\n"
     "                cb(self._name)",
     "            cb, self._on_finish = self._on_finish, None\n            if False:  # MUT\n"
     "                cb(self._name)",
     ["frame action back to idle"],
     "帧动画播完不回调收尾（_play_idle 不会跑）→ 状态机停在 'state'"),
    ("M-P11", "桌宠.py",
     "    def _play_eat(self):\n        self._stop_tween()  # v2.0.1：吃帧开始前停合成动作",
     "    def _play_eat(self):\n        pass  # MUT: 吃帧前不停合成动作",
     ["feed during proc releases busy"],
     "喂食路径不停在途合成动作 → 残留振荡（结构判据：_tween_anim 仍非 None）"),
    ("M-P12", "桌宠.py",
     "    def _eat_done(self, _name):\n        self.busy = False",
     "    def _eat_done(self, _name):\n        self.busy = True  # MUT: 不释放 busy",
     ["feed during proc releases busy"],
     "吃帧收尾不释放 busy → 卡死在忙态"),
]

TOTAL_RE = re.compile(r"TOTAL CHECKS: (\d+), FAILS: (\d+)")


def run_verify(tree, timeout=900):
    cmd = [sys.executable, "-B", "_verify_v13.py"]
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run(cmd, cwd=tree, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=timeout, env=env)
    out = p.stdout.decode("utf-8", "replace")
    m = TOTAL_RE.search(out)
    total = int(m.group(1)) if m else -1
    fails = int(m.group(2)) if m else -1
    red = [ln[4:].split("：")[0].split(" ")[0] for ln in out.splitlines()
           if ln.startswith("  - ")]
    # 上面的切法对含空格的名字不适用，这里只用于展示；判定一律用"FAIL <名字>"子串。
    return p.returncode, total, fails, out, red


def main():
    results = []
    with shadow(what="proc_reset_v26") as tree:
        real = {}
        for _id, rel, _a, _b, _exp, _note in MUTATIONS:
            if rel not in real:
                with open(os.path.join(tree, rel), "r", encoding="utf-8") as f:
                    real[rel] = f.read()
        print("[baseline] 影子副本跑新护栏 ...", flush=True)
        rc, total, fails, out, _red = run_verify(tree)
        base_ok = (rc == 0 and total == 273 and fails == 0)
        print("[baseline] rc=%s total=%s fails=%s → %s" % (rc, total, fails,
                                                           "OK" if base_ok else "BASELINE-RED"),
              flush=True)
        results.append(("BASELINE", "PASS" if base_ok else "BASELINE-RED", rc,
                        "total=%s fails=%s" % (total, fails), []))
        if not base_ok:
            write_results(os.path.join(HERE, "mutations_proc_reset_v26.json"),
                          "v2.6.0 proc-reset 结构性判据牙齿实测", results,
                          {"baseline_ok": False})
            return 1
        for mid, rel, anchor, repl, expect, note in MUTATIONS:
            src = real[rel]
            if src.count(anchor) != 1:
                verdict, rc2, tail = "ANCHOR-LOST", None, "锚点命中 %d 次" % src.count(anchor)
                results.append((mid, verdict, rc2, tail, []))
                print("[%s] ANCHOR-LOST %s" % (mid, note), flush=True)
                continue
            with open(os.path.join(tree, rel), "w", encoding="utf-8") as f:
                f.write(src.replace(anchor, repl))
            t0 = time.time()
            rc2, total2, fails2, out2, _r2 = run_verify(tree)
            hit = [e for e in expect if ("FAIL " + e) in out2]
            caught = rc2 != 0 and fails2 >= 1 and len(hit) == len(expect)
            verdict = "CAUGHT" if caught else "NOT CAUGHT"
            tail = "rc=%s total=%s fails=%s 命中=%s 用时=%.1fs" % (rc2, total2, fails2, hit,
                                                                  time.time() - t0)
            results.append((mid, verdict, rc2, tail, hit))
            print("[%s] %-10s %s | %s" % (mid, verdict, note, tail), flush=True)
            with open(os.path.join(tree, rel), "w", encoding="utf-8") as f:
                f.write(src)      # 还原，逐条互不影响
    path = write_results(os.path.join(HERE, "mutations_proc_reset_v26.json"),
                         "v2.6.0 proc-reset 结构性判据牙齿实测（影子副本）", results,
                         {"baseline_ok": True, "note": "12 条变异全部针对收尾/复位逻辑"})
    caught = len([r for r in results if r[1] == "CAUGHT"])
    print("=" * 60)
    print("共 %d 条，CAUGHT %d，未捕获 %d" % (len(results) - 1, caught, len(results) - 1 - caught))
    print("结果: %s" % path)
    return 0 if caught == len(MUTATIONS) else 1


if __name__ == "__main__":
    sys.exit(main())
