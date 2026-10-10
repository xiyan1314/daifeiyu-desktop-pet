# -*- coding: utf-8 -*-
r"""并发写盘"静默丢失"复现（v2.3.1 发布说明引用的那组数字，此前仓库里没有可复现脚本）。

背景（_release_notes_v231.md 第一节）：
  v2.3.0 及以前有 6 个模块各自写一份"临时文件 + os.replace"，其中**临时文件名固定**
  （始终是 "<path>.tmp"）、**没有锁**、且异常一律 "except: pass" 吞掉。多线程/多入口
  同时写同一个文件时：
    1) 两个线程共用一个 tmp：A 刚写好，B 打开同一个 tmp 把它截断 → A 的 os.replace
       搬走的是 B 的半成品；B 随后再 replace 时 tmp 已经没了 → FileNotFoundError；
    2) 这些异常被吞掉 → **这一次写入就这么静默没了**，磁盘上留旧值或半截 JSON；
    3) 读到坏 JSON 只返回默认值、不回写 → 下次启动继续报，用户侧看不到任何提示。
  v2.3.1 起统一走 pet_io.atomic_write_json：**按路径分锁**（RLock）+ **线程唯一临时名**
  （"<path>.<线程号>.tmp"）+ os.replace 共享冲突**重试** + 失败清理自己的 tmp + 绝不抛
  （返回错误串让调用方决定），因此同款并发下不再有写入丢失。

本脚本把两种口径放在**同一份负载**下对跑（同一路径、同线程数、同写入次数）：
  - 旧口径：本文件内的 _write_json_old（固定 "<path>.tmp"、无锁、except 吞掉，与
    v2.3.0 的 pet_book/pet_chat/pet_resources/pet_alarm/pet_behaviors/pet_voice 同款）
  - 新口径：真实 pet_io.atomic_write_json（用仓库里那份，不是复制品）

统计两个数字（发布说明里的"次丢失"就是第 1 个）：
  A. 写入返回错误串 / 异常被吞掉的次数（= 这次写入没落盘 → 丢失）
  B. 写完后立刻读回、JSONDecodeError 的次数（= 磁盘上是坏 JSON）

负载取 8 线程 × 50 次/轮 = 400 次写入/轮（共 5 轮）：与发布说明记录的
"8 线程同写：183/180/173/180/154 次丢失 → 新版 0"同一量级（本机实测 190/171/183/164/161）。
逐轮 ±10% 的波动属正常：丢的是**竞态窗口**，不是确定值；关键结论是"新实现恒为 0"。

跑法：python _dev/repro_io_conflict.py
退出码：0 = 新实现 0 丢失；1 = 新实现有丢失（或统计口径被破坏）
输出可直接贴进发布说明：末行形如 "旧 190/171/183/164/161 → 新 0/0/0/0/0"。
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time

# v2.2.7 同款：默认 GBK 控制台下打印中文/箭头会 UnicodeEncodeError → 全过也 exit 1
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass  # 有意忽略：老解释器/非标准流上没有 reconfigure，退化为原编码

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import pet_io  # noqa: E402

# 负载参数：8 线程（与发布说明"8 线程同写"一致）× 每线程 25 次 = 每轮 200 次写入
THREADS = 8
WRITES_PER_THREAD = 50
ROUNDS = 5
PAD = "x" * 200  # 单条记录体积与真实 ledger/资源索引同量级


def _write_json_old(path, data):
    """旧口径（v2.3.0 及以前）：

    固定 "<path>.tmp" + 无锁 + 异常全吞。旧代码里这个 except 是 "pass"（连日志都没有），
    这里按调用方现在能看到的口径返回错误串——"吞掉"发生在调用点，丢失则已经发生。
    """
    tmp = str(path) + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, str(path))
        return None
    except Exception as e:
        # 旧代码：except Exception: pass  ← 就是"静默"两个字
        return "%s: %s" % (type(e).__name__, e)


def _write_json_new(path, data):
    """新口径：真实 pet_io 实现（按路径分锁 + 线程唯一 tmp + 重试 + 失败清理）。"""
    return pet_io.atomic_write_json(path, data, indent=2)


def _read_back(path):
    """写完立刻读回；返回 "ok" / "bad"（JSONDecodeError）/ "io"（其它读取错误）。"""
    try:
        with open(str(path), "r", encoding="utf-8") as f:
            json.load(f)
        return "ok"
    except json.JSONDecodeError:
        return "bad"
    except OSError:
        return "io"


def _one_round(target, impl):
    """一轮并发写：返回该轮的 (写入失败次数, 读回坏 JSON 次数, 读回 IO 错误次数)。"""
    write = _write_json_old if impl == "old" else _write_json_new
    stats = {"err": 0, "bad": 0, "io": 0}
    lock = threading.Lock()

    def worker(tid):
        local_err = local_bad = local_io = 0
        for seq in range(WRITES_PER_THREAD):
            err = write(target, {"thread": tid, "seq": seq, "pad": PAD})
            if err:
                local_err += 1
            got = _read_back(target)
            if got == "bad":
                local_bad += 1
            elif got == "io":
                local_io += 1
        with lock:
            stats["err"] += local_err
            stats["bad"] += local_bad
            stats["io"] += local_io

    threads = [threading.Thread(target=worker, args=(n,), daemon=True)
               for n in range(THREADS)]
    t0 = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join(120)
    return stats["err"], stats["bad"], stats["io"], time.monotonic() - t0


def main():
    tmp = tempfile.mkdtemp(prefix="dfy_io_conflict_")
    old_path = os.path.join(tmp, "old.json")
    new_path = os.path.join(tmp, "new.json")
    rows = []
    print("=== 并发写盘静默丢失对照（%d 线程 × %d 次/线程 = %d 次/轮，共 %d 轮）==="
          % (THREADS, WRITES_PER_THREAD, THREADS * WRITES_PER_THREAD, ROUNDS))
    print("目标文件：同一路径反复重写（%s）" % os.path.basename(old_path))
    print("%-4s | %-22s | %-18s" % ("轮次", "旧口径：写入被吞(丢失)", "新口径：写入被吞(丢失)"))
    print("-" * 56)
    for i in range(1, ROUNDS + 1):
        o_err, o_bad, o_io, o_sec = _one_round(old_path, "old")
        n_err, n_bad, n_io, n_sec = _one_round(new_path, "new")
        rows.append((o_err, o_bad, o_io, n_err, n_bad, n_io))
        print("%-4d | %-22s | %-18s" % (
            i, "%d 次（读回坏 JSON %d）" % (o_err, o_bad),
            "%d 次（读回坏 JSON %d）" % (n_err, n_bad)))
    old_loss = [r[0] for r in rows]
    new_loss = [r[3] for r in rows]
    old_bad = sum(r[1] for r in rows)
    new_bad = sum(r[4] for r in rows)
    print("-" * 56)
    print("旧口径写入失败合计：%d / %d 次；读回坏 JSON 合计：%d 次"
          % (sum(old_loss), THREADS * WRITES_PER_THREAD * ROUNDS, old_bad))
    print("新口径写入失败合计：%d / %d 次；读回坏 JSON 合计：%d 次"
          % (sum(new_loss), THREADS * WRITES_PER_THREAD * ROUNDS, new_bad))
    print("（写入失败 = 这次写入没落盘 = 静默丢失；旧代码把这些异常 except: pass 了）")
    print("")
    print("旧 %s → 新 %s" % ("/".join(str(x) for x in old_loss),
                             "/".join(str(x) for x in new_loss)))
    leftovers = sorted(f for f in os.listdir(tmp) if f.endswith(".tmp"))
    print("残留 .tmp 文件：%d 个 %s" % (len(leftovers), leftovers[:4]))
    if sum(old_loss) == 0:
        print("注意：本机旧口径没有复现出丢失（时序相关）——机制仍在，但这次没撞上。")
    shutil.rmtree(tmp, ignore_errors=True)
    # 退出码只看新实现：新口径任何一次丢失/坏读回都算失败（发布说明的承诺就是这个）
    ok = sum(new_loss) == 0 and new_bad == 0
    print("REPRO %s" % ("OK（新实现 0 丢失 / 0 坏 JSON）" if ok else "FAILED（新实现出现丢失）"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
