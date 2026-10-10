# -*- coding: utf-8 -*-
"""导出两段式 API 的**变异验证**：把每处修复逐个拿掉，确认新用例真的会红。

与 _dev/mutate_startup_defer.py 同套路：精确替换一小段 → 跑用例 → **无论如何还原**。
任何一条变异"没被检出"都算验证失败（说明对应用例没有区分力）。

用法：python _dev/mutate_export_slice.py
退出码：0 = 每条变异都被检出；1 = 有变异逃逸（或用例本身跑不过）。
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "pet_export.py")
UI = os.path.join(ROOT, "桌宠.py")
TESTS = "tests/test_export_slice_v242.py"

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


def run_tests(verbose_tail=0):
    p = subprocess.run([sys.executable, "-m", "pytest", TESTS, "-o", "addopts=", "-q",
                        "--no-header", "-p", "no:cacheprovider"],
                       cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = p.stdout.decode("utf-8", "replace")
    failed = [ln.split("::")[-1].split(" ")[0]
              for ln in out.splitlines() if ln.startswith("FAILED ")]
    if p.returncode != 0 and not failed and verbose_tail:
        print("    （rc=%d 但没有 FAILED 行，输出尾部：）" % p.returncode)
        for ln in out.splitlines()[-verbose_tail:]:
            print("      " + ln)
    return p.returncode, failed


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    orig = {}
    for path in (SRC, UI):
        with open(path, encoding="utf-8") as fp:
            orig[path] = fp.read()
    try:
        rc, _failed = run_tests()
        if rc != 0:
            print("基线就跑不过：先修好再谈变异")
            return 1
        print("基线：新用例全过（%s）" % TESTS)
        escaped = []
        for name, path, old, new in MUTATIONS:
            if only and only not in name:
                continue
            if orig[path].count(old) != 1:
                print("  [跳过] %s —— 原文匹配 %d 次（源码改过了，需同步本脚本）"
                      % (name, orig[path].count(old)))
                escaped.append(name + "（锚点失效）")
                continue
            try:
                with open(path, "w", encoding="utf-8") as fp:
                    fp.write(orig[path].replace(old, new, 1))
                rc, failed = run_tests(verbose_tail=15)
            finally:
                with open(path, "w", encoding="utf-8") as fp:
                    fp.write(orig[path])
            if rc == 0:
                print("  [逃逸] %s —— 拿掉后用例全过，说明没有护栏" % name)
                escaped.append(name)
            elif not failed:
                print("  [变异不合法] %s —— rc=%d 但没有任何用例失败" % (name, rc))
                escaped.append(name + "（变异不合法）")
            else:
                print("  [检出] %s → %d 条红：%s" % (name, len(failed), "、".join(failed[:4])))
        n = len([m for m in MUTATIONS if not only or only in m[0]])
        print("\n变异验证：%d/%d 检出" % (n - len(escaped), n))
        return 1 if escaped else 0
    finally:
        for path, text in orig.items():
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(text)


if __name__ == "__main__":
    sys.exit(main())
