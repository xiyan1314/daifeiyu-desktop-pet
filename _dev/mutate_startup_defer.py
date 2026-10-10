# -*- coding: utf-8 -*-
"""启动延迟装载的**变异验证**：把每处修复逐个拿掉，确认新用例真的会红。

只做三件事：① 精确替换 桌宠.py 里的一小段；② 跑 tests/test_startup_defer_v242.py；
③ **无论结果如何都把原文件还原**（finally）。任何一条变异"没被检出"都算验证失败
（那说明对应用例没有区分力，是假护栏）。

用法：python _dev/mutate_startup_defer.py
退出码：0 = 每条变异都被检出；1 = 有变异逃逸（或用例文件本身跑不过）。
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "桌宠.py")
TESTS = "tests/test_startup_defer_v242.py"

# (变异名, 原文, 替换成)
MUTATIONS = [
    ("M1 帧集不再推迟（构造期把四组都解完）",
     '        self._load_default_frame_set("idle")\n',
     '        for _k, _s, _p, _c, _a in _DEFAULT_FRAME_SETS:\n'
     '            self._load_default_frame_set(_k)\n'),
    ("M2 状态图不再推迟（构造期全量构建）",
     '        self._build_state_pix(only={})\n',
     '        self._build_state_pix()\n'),
    ("M3 接力装载改成一轮做完（不再分片）",
     '        if self._closing:\n            return  # 窗口正在退出：别再往它身上解素材（单发定时器与窗口同生命周期）\n',
     '        self._ensure_default_frames()\n'
     '        while self._state_pix_pending:\n'
     '            self._build_state_pix_slice()\n'
     '        if self._closing:\n            return\n'),
    ("M4 _state_pix 不再按需补建",
     '        self._ensure_state_pix(state)  # v2.4.2：启动期没建的在这里按需补（建好后是空操作）\n',
     ''),
    ("M5 _play_idle 不再补本形态帧集",
     '        self._ensure_default_frames(("idle", "idle_full") if self.form != self.form_keys[0]\n'
     '                                     else ("idle",))\n',
     ''),
    ("M6 feed 不再补吃帧",
     '        if self._ensure_default_frames():\n            self._wire_anim_sets()\n',
     ''),
    ("M7 _start_petting 不再补 petpet 帧集",
     '        # v2.4.2（启动耗时 P2）：petpet 帧集同样延迟装载，开播前先补齐（已就位则无开销）。\n'
     '        self._ensure_default_frames()\n',
     ''),
    ("M8 接力收尾不再重注册帧集（eat 槽停在空集）",
     '                self._wire_anim_sets()\n',
     '                pass  # 变异：收尾不重注册\n'),
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
    with open(SRC, encoding="utf-8") as fp:
        orig = fp.read()
    try:
        rc, failed = run_tests()
        if rc == 0:
            print("基线：新用例全过（%s）" % TESTS)
        else:
            print("基线就跑不过（rc=%d，%r）：先修好再谈变异" % (rc, failed[:5]))
            return 1
        escaped = []
        for name, old, new in MUTATIONS:
            if only and only not in name:
                continue
            if orig.count(old) != 1:
                print("  [跳过] %s —— 原文匹配 %d 次（源码改过了，需同步本脚本）"
                      % (name, orig.count(old)))
                escaped.append(name + "（锚点失效）")
                continue
            try:
                with open(SRC, "w", encoding="utf-8") as fp:
                    fp.write(orig.replace(old, new, 1))
                rc, failed = run_tests(verbose_tail=15)
            finally:
                with open(SRC, "w", encoding="utf-8") as fp:
                    fp.write(orig)
            if rc == 0:
                print("  [逃逸] %s —— 拿掉后用例全过，说明这条修复没有护栏" % name)
                escaped.append(name)
            elif not failed:
                # 收集期就炸（语法/导入错）：那不是"用例检出"，是变异本身不合法
                print("  [变异不合法] %s —— rc=%d 但没有任何用例失败" % (name, rc))
                escaped.append(name + "（变异不合法）")
            else:
                print("  [检出] %s → %d 条红：%s" % (name, len(failed), "、".join(failed[:4])))
        print("\n变异验证：%d/%d 检出" % (len(MUTATIONS) - len(escaped), len(MUTATIONS)))
        return 1 if escaped else 0
    finally:
        with open(SRC, "w", encoding="utf-8") as fp:   # 双保险：任何异常路径都还原
            fp.write(orig)


if __name__ == "__main__":
    sys.exit(main())
