# -*- coding: utf-8 -*-
"""导出两段式 API 的**变异验证**：把每处修复逐个拿掉，确认新用例真的会红。

v2.4.2（第三轮找茬收口）：变异不再原地覆写产品源码——仓库整体复制到 %TEMP% 影子副本，
变异与 pytest 全在影子里做，真实仓库只写一个运行锁 _dev/.mutation.lock。
（旧做法在变异窗口里被别的进程跑全量门时会看到"来源不明的红"，本轮真的发生过。）

用法：python _dev/mutate_export_slice.py [变异名关键字]
退出码：0 = 每条变异都被检出；1 = 有变异逃逸（或用例本身跑不过）。
结果 JSON：_dev/mutations_export_slice_v242.json（ID/判定/rc/末行/时间戳）。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _mutate_lib import (last_line, repo_fingerprint, run_baseline, run_pytest,  # noqa: E402
                       shadow, test_error_lines, write_results)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = "pet_export.py"      # 影子副本里的相对路径（变异只写影子，真实仓库只读）
UI = "桌宠.py"
TESTS = "tests/test_export_slice_v242.py"
RESULT_JSON = os.path.join(ROOT, "_dev", "mutations_export_slice_v242.json")
TITLE = "导出两段式（pet_export.BundleWriter + UI 分片）变异验证"


MUTATIONS = [
    ("E1 export_bundle 不再走两段式（自己内联写盘）", SRC,
     '    w = BundleWriter(plan, out_path)\n'
     '    w.step()          # budget_ms=None：一口气写完 = 旧行为\n'
     '    return w.finish()\n',
     '    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:\n'
     '        zf.writestr(MANIFEST_NAME, json.dumps(plan["manifest"], ensure_ascii=False, indent=2))\n'
     '        for arc, src in plan["entries"]:\n'
     '            zf.write(src, arc)\n'
     '    return True, ""\n'),
    ("E2 step 忽略 budget_ms（一次写光）", SRC,
     '                if budget_ms is not None and (time.perf_counter() - t0) * 1000.0 >= budget_ms:\n'
     '                    break\n',
     '                if False:\n                    break\n'),
    ("E3 不写 manifest.json", SRC,
     '            self._zf.writestr(MANIFEST_NAME,\n'
     '                              json.dumps(self.plan["manifest"], ensure_ascii=False, indent=2))\n',
     '            pass\n'),
    ("E4 abort 不清理临时文件", SRC,
     '        self._cleanup_tmp()\n        self.done = True\n\n    def finish(self):',
     '        self.done = True\n\n    def finish(self):'),
    ("E5 UI 侧不分片（budget_ms=None）", UI,
     '        w.step(budget_ms=_EXPORT_SLICE_MS)\n',
     '        w.step()\n'),
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
    with shadow(what="mutate_export_slice") as tree:
        ok, rc, failed, out, note = run_baseline(tree, [TESTS])
        if not ok:
            print("基线就跑不过（影子副本，重跑了 3 遍）：%r" % (failed[:6],))
            print(last_line(out))
            print("-> 基线红的时候，某条变异有没有被抓到没有意义：本轮不产出 CAUGHT 判定；")
            print("   结果 JSON 记为 BASELINE-RED（谁红、rc 多少、末行都留着，便于回溯）")
            for name, rel, old, new in picked:
                results.append((name, "BASELINE-RED", rc, last_line(out)))
            write_results(RESULT_JSON, TITLE, results,
                          {"tests": TESTS, "script": "_dev/mutate_export_slice.py.py",
                           "note": "变异只在 %TEMP% 影子副本里做，真实仓库只读；基线红 → 本轮无判定",
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
                  {"tests": TESTS, "script": "_dev/mutate_export_slice.py",
                   "note": "变异只在 %TEMP% 影子副本里做，真实仓库只读（只写 _dev/.mutation.lock）",
                   "repo_fingerprint": repo_fingerprint(ROOT)})
    return 1 if escaped else 0


if __name__ == "__main__":
    sys.exit(main())
