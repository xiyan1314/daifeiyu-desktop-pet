# -*- coding: utf-8 -*-
"""启动延迟装载的**变异验证**：把每处修复逐个拿掉，确认新用例真的会红。

v2.4.2（第三轮找茬收口）：变异不再原地覆写 桌宠.py——仓库整体复制到 %TEMP% 影子副本，
变异与 pytest 全在影子里做，真实仓库只写一个运行锁 _dev/.mutation.lock。

用法：python _dev/mutate_startup_defer.py [变异名关键字]
退出码：0 = 每条变异都被检出；1 = 有变异逃逸（或用例文件本身跑不过）。
结果 JSON：_dev/mutations_startup_defer_v242.json（ID/判定/rc/末行/时间戳）。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _mutate_lib import (last_line, repo_fingerprint, run_baseline, run_pytest,  # noqa: E402
                       shadow, test_error_lines, write_results)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = "桌宠.py"            # 影子副本里的相对路径（变异只写影子，真实仓库只读）
TESTS = "tests/test_startup_defer_v242.py"
RESULT_JSON = os.path.join(ROOT, "_dev", "mutations_startup_defer_v242.json")
TITLE = "启动延迟装载（帧集/状态图分片）变异验证"


MUTATIONS = [
        ('M1 帧集不再推迟（构造期把四组都解完）', SRC,
     '        if not self._custom_role:\n            self._load_default_frame_set("idle")\n',
     '        for _k, _s, _p, _c, _a in _DEFAULT_FRAME_SETS:\n            self._load_default_frame_set(_k)\n'),
    ("M2 状态图不再推迟（构造期全量构建）", SRC,
     '        self._build_state_pix(only={})\n',
     '        self._build_state_pix()\n'),
    ("M3 接力装载改成一轮做完（不再分片）", SRC,
     '        if self._closing:\n            return  # 窗口正在退出：别再往它身上解素材（单发定时器与窗口同生命周期）\n',
     '        self._ensure_default_frames()\n'
     '        while self._state_pix_pending:\n'
     '            self._build_state_pix_slice()\n'
     '        if self._closing:\n            return\n'),
    ("M4 _state_pix 不再按需补建", SRC,
     '        self._ensure_state_pix(state)  # v2.4.2：启动期没建的在这里按需补（建好后是空操作）\n',
     ''),
            ('M5 _play_idle 不再补本形态帧集', SRC,
     '        if not self._custom_role:\n            self._ensure_default_frames(("idle", "idle_full") if self.form != self.form_keys[0]\n                                        else ("idle",))\n',
     '        pass  # MUTATION：起播前不补本形态帧集（整段 if 一起拿掉，否则空 if 体是语法错）\n'),
    ("M6 feed 不再补吃帧", SRC,
     '        if self._ensure_default_frames():\n            self._wire_anim_sets()\n',
     ''),
        ('M7 _start_petting 不再补 petpet 帧集', SRC,
     '        # v2.4.2（兼容 L2）：补齐必须放在**三个早退之后**——此前它在最前面，一次普通拖动\n        # （press_dist>32）/按住未松/busy 重排都会同步解三组默认帧集（≈26ms），把"延迟装载"\n        # 又拉回了交互路径上；真起播才付这份钱。\n        self._ensure_default_frames()\n',
     ''),
    ("M8 接力收尾不再重注册帧集（eat 槽停在空集）", SRC,
     '                self._wire_anim_sets()\n',
     '                pass  # 变异：收尾不重注册\n'),
]


def _read(tree, rel):
    with io.open(os.path.join(tree, rel), encoding="utf-8") as fp:
        return fp.read()


def _write(tree, rel, text):
    with io.open(os.path.join(tree, rel), "w", encoding="utf-8") as fp:
        fp.write(text)


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    picked = [m for m in MUTATIONS if not only or only in m[0]]
    results = []
    escaped = 0
    with shadow(what="mutate_startup_defer") as tree:
        ok, rc, failed, out, note = run_baseline(tree, [TESTS])
        if not ok:
            print("基线就跑不过（影子副本，重跑了 3 遍）：%r" % (failed[:6],))
            print(last_line(out))
            print("-> 基线红的时候，某条变异有没有被抓到没有意义：本轮不产出 CAUGHT 判定；")
            print("   结果 JSON 记为 BASELINE-RED（谁红、rc 多少、末行都留着，便于回溯）")
            for name, rel, old, new in picked:
                results.append((name, "BASELINE-RED", rc, last_line(out)))
            write_results(RESULT_JSON, TITLE, results,
                          {"tests": TESTS, "script": "_dev/mutate_startup_defer.py",
                           "note": "变异只在 %TEMP% 影子副本里做，真实仓库只读；基线红 -> 本轮无判定",
                           "repo_fingerprint": repo_fingerprint(ROOT)})
            return 1
        print("基线：新用例全过（影子副本 %s）%s" % (tree, note))
        for name, rel, old, new in picked:
            orig = _read(tree, rel)
            n = orig.count(old)
            if n != 1:
                print("  [跳过] %s —— 原文匹配 %d 次（源码改过了，需同步本脚本）" % (name, n))
                results.append((name, "ANCHOR-LOST", 0, "锚点匹配 %d 次" % n))
                escaped += 1
                continue
            try:
                _write(tree, rel, orig.replace(old, new, 1))
                rc, failed, out = run_pytest(tree, [TESTS])
            finally:
                _write(tree, rel, orig)
            if rc == 0:
                print("  [逃逸] %s —— 拿掉后用例全过，说明这条修复没有护栏" % name)
                results.append((name, "NOT CAUGHT", rc, last_line(out)))
                escaped += 1
            elif not failed and test_error_lines(out):
                print("  [检出] %s → 用例 error（setup/call 抛异常）：%s"
                      % (name, test_error_lines(out)[0][:90]))
                results.append((name, "CAUGHT", rc, last_line(out)))
            elif not failed:
                print("  [变异不合法] %s —— rc=%d 但没有任何用例失败（收集期就炸）" % (name, rc))
                print("    " + last_line(out))
                results.append((name, "INVALID", rc, last_line(out)))
                escaped += 1
            else:
                print("  [检出] %s → %d 条红：%s" % (name, len(failed), "、".join(failed[:4])))
                results.append((name, "CAUGHT", rc, last_line(out)))
    total = len(picked)
    print(chr(10) + "变异验证：%d/%d 检出" % (total - escaped, total))
    write_results(RESULT_JSON, TITLE, results,
                  {"tests": TESTS, "script": "_dev/mutate_startup_defer.py",
                   "note": "变异只在 %TEMP% 影子副本里做，真实仓库只读（只写 _dev/.mutation.lock）",
                   "repo_fingerprint": repo_fingerprint(ROOT)})
    return 1 if escaped else 0


if __name__ == "__main__":
    sys.exit(main())
