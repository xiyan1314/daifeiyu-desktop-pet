# -*- coding: utf-8 -*-
"""变异验证：把修复拿掉，对应的新测试必须变红（代理 Q 的"能真失败"证据）。

用法: python _dev/mutate_check.py <spec.json> [--keep-on-fail]

spec.json 结构：
  {"mutations": [
     {"id": "M-Q1", "why": "一句话说明这行代码在守什么",
      "file": "pet_alarm.py", "old": "源码里唯一的字面量片段", "new": "替换成什么",
      "tests": ["tests/test_x.py::test_y", ...]}]}

流程（每条变异）：备份 → 字面量替换（要求唯一命中）→ 跑指定测试 → 还原本文件 →
校验 sha256 与备份一致。只写 file 指定的文件，绝不动别的文件；异常路径也会还原。
退出码：0=全部被抓到；1=有变异没被抓到（NOT CAUGHT）；2=脚本自身出错。

v2.4.2（_dev 卫生）：跑完把结果**回写进 spec.json 的 "results" 段**（时间戳 + 每条
ID/结果/rc/末行 + 未抓到计数）——此前只有 spec 没有结果，"N/N 全抓到"这句结论无法复核。
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _write_results(spec_path, results, bad):
    """把本轮结果写回 spec.json 的 "results" 段（追加/覆盖均可，不影响 mutations 段）。"""
    try:
        with open(spec_path, "r", encoding="utf-8") as f:
            spec = json.load(f)
        spec["results"] = {
            "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total": len(results),
            "not_caught": bad,
            "items": [{"id": mid, "verdict": st, "rc": rc, "tail": tail}
                      for mid, st, rc, tail in results],
        }
        with open(spec_path, "w", encoding="utf-8") as f:
            json.dump(spec, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print("结果已回写到 %s 的 results 段" % os.path.basename(spec_path))
    except Exception as e:
        print("[结果回写] 失败（不影响本轮判定）：%r" % (e,))


def _run(tests):
    cmd = [sys.executable, "-m", "pytest"] + list(tests) + ["-o", "addopts=", "-q"]
    p = subprocess.run(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=1800)
    out = p.stdout.decode("utf-8", "replace")
    return p.returncode, out


def main():
    spec_path = sys.argv[1]
    with open(spec_path, "r", encoding="utf-8") as f:
        spec = json.load(f)
    tmpdir = tempfile.mkdtemp(prefix="mutq_")
    results = []
    bad = 0
    for m in spec["mutations"]:
        path = os.path.join(ROOT, m["file"])
        before_sha = _sha(path)
        bak = os.path.join(tmpdir, m["id"] + "_" + os.path.basename(path))
        shutil.copyfile(path, bak)
        try:
            with open(path, "r", encoding="utf-8") as f:
                src = f.read()
            n = src.count(m["old"])
            if n != 1:
                print("[%s] 替换片段命中 %d 次（要求恰好 1 次）→ 脚本判据失效" % (m["id"], n))
                results.append((m["id"], "SPEC-BAD", 0, ""))
                bad += 1
                continue
            with open(path, "w", encoding="utf-8") as f:
                f.write(src.replace(m["old"], m["new"]))
            rc, out = _run(m["tests"])
            tail = [ln for ln in out.strip().splitlines() if ln.strip()][-1:]
            caught = rc != 0
            results.append((m["id"], "CAUGHT" if caught else "NOT CAUGHT", rc,
                            (tail[0] if tail else "")[:120]))
            if not caught:
                bad += 1
                print(out[-3000:])
        finally:
            shutil.copyfile(bak, path)
            after_sha = _sha(path)
            if after_sha != before_sha:
                print("[%s] 还原失败！%s 的哈希与备份不一致" % (m["id"], m["file"]))
                return 2
            shutil.rmtree(tmpdir, ignore_errors=True)
            os.makedirs(tmpdir, exist_ok=True)
    print("\n%-10s %-11s %-4s %s" % ("ID", "结果", "rc", "末行"))
    for mid, st, rc, tail in results:
        print("%-10s %-11s %-4s %s" % (mid, st, rc, tail))
    print("\n%d 条变异，%d 条未被抓到" % (len(results), bad))
    _write_results(spec_path, results, bad)
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
