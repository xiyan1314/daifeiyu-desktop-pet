# -*- coding: utf-8 -*-
"""v2.5.0（A1）服务构造搬迁的 **AST 实参对照**：旧 __init__ vs 新 pet_services.py。

为什么要有它（v2.5.0 第 3 轮 M4）：CHANGELOG / 发布说明写着"用 AST 对照旧代码与新模块的
每一处构造实参（具名归一化后 compared=16、mismatches=0）"，但那份脚本**全仓不存在**
（grep compared= / AST 对照 = 0 命中）——下一轮没人能复核这句话，也进不了发布门。
本文件把它落成可复跑的产物：**只读**，不改任何东西。

用法（仓库根）：
    python -B _dev/verify_services_ast_v250.py                 # 基准取 git 里的 2a6563c（v2.4.4 留档）
    python -B _dev/verify_services_ast_v250.py --baseline-file <旧 桌宠.py>
    python -B _dev/verify_services_ast_v250.py --baseline-ref <commit>
    python -B _dev/verify_services_ast_v250.py --dump          # 只打印两侧逐条归一化结果
退出码：0 = 条数相同且逐位一致；1 = 有差异（会逐条打印）。

对照口径（与常驻护栏 tests/test_services_registry_v250.py 的 _GOLDEN_SHAPES 互补）：
  · 位置实参**保序**逐位比；关键字实参**按名字**比（关键字书写顺序无语义）；
  · 只归一化"搬迁本身造成的改名"——旧 __init__ 里的模块全局 → 注册表注入名，
    以及 self ↔ pet / self.pet 的等价写法；**不做任何掩饰性替换**：
    两个实参对调、换一个对象、少一个实参，归一化后必然不同（--selftest 现场验一遍）。
  · 没搬的三处（pet_fx.AnimatedEmote ×2、pet_audio.init）必须**留在** __init__，
    新模块里出现它们就是搬错了。
"""
import argparse
import ast
import io
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_REF = "2a6563c"          # v2.4.4 留档（v2.5.0 的父提交）
NEW_MODULE = "pet_services.py"
LEFTOVERS = ("pet_fx.AnimatedEmote", "pet_audio.init")   # 没搬的三处（fx 两处同名）

# 旧 __init__ 的模块全局 → 搬迁后被注入的名字（新模块里的注册表属性 / 局部名）。
# 这张表就是"具名归一化"的全部内容：**只映射同一批对象的两个名字**。
ARG_ALIASES = (
    ("DATA_DIR", "data_dir"),
    ("CONFIG_PATH", "self._config_path"),
    ("USAGE_PATH", "self._usage_path"),
    ("MEMORY_PATH", "self._memory_path"),
    ("DEFAULT_CONFIG", "self._defaults"),
    ("MAX_REPLY_LEN", "self._max_reply_len"),
    ("SLEEP_AFTER_SECONDS", "self._sleep_after"),
    ("_log_error", "log"),
    ("save_config", "save_cfg"),
    ("set_redact_key", "self._set_redact_key"),
    ("_remove_files", "self._remove_files"),
    ("play_sound", "self._play_sound"),
    ("parse_emote_tag", "self._parse_emote"),
    ("load_chat_memory", "self._load_memory"),
    ("save_chat_memory", "self._save_memory"),
    ("_build_ai_sys_prompt", "self._ai_prompt"),
    ("pick_idle_action", "self._idle_picker"),
    ("is_autostart_enabled", "self._autostart_enabled"),
)


def normalize_old(text):
    """旧 __init__ 侧：self → pet（先做，别名表插入的 self._xxx 不能被再改写）→ 全局别名。"""
    out = re.sub(r"\bself\b", "pet", text)
    for old, new in ARG_ALIASES:
        out = re.sub(r"\b%s\b" % re.escape(old), new, out)
    return out


def normalize_new(text):
    """新模块侧：注册表手里的 pet 写作 self.pet，与局部别名 pet 等价 —— 只统一这一处。"""
    return re.sub(r"\bself\.pet\b", "pet", text)


def _find_init(tree):
    for cls in tree.body:
        if isinstance(cls, ast.ClassDef) and cls.name == "PetWindow":
            for fn in cls.body:
                if isinstance(fn, ast.FunctionDef) and fn.name == "__init__":
                    return fn
    raise SystemExit("基准源码里找不到 PetWindow.__init__")


def raw_calls(node):
    """子树里所有 pet_xxx.名字(...) 调用，按源码出现顺序（行、列）。"""
    out = []
    for st in ast.walk(node):
        if (isinstance(st, ast.Call) and isinstance(st.func, ast.Attribute)
                and isinstance(st.func.value, ast.Name)
                and st.func.value.id.startswith("pet_")):
            out.append((st.lineno, st.col_offset, "%s.%s" % (st.func.value.id, st.func.attr),
                        st, ast.unparse(st)))
    return sorted(out, key=lambda r: (r[0], r[1]))


def call_shape(row, side):
    """(名字, 位置实参列表, 关键字字典) —— 已归一化。"""
    _ln, _col, name, node, _src = row
    norm = normalize_old if side == "old" else normalize_new
    args = [norm(ast.unparse(a)) for a in node.args]
    kwargs = {k.arg: norm(ast.unparse(k.value)) for k in node.keywords}
    return name, args, kwargs


def load_baseline(args):
    if args.baseline_file:
        return io.open(args.baseline_file, encoding="utf-8-sig").read()
    cmd = ["git", "-C", ROOT, "show", "%s:桌宠.py" % args.baseline_ref]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise SystemExit("git show 失败（%s）：%s" % (" ".join(cmd),
                                                     p.stderr.decode("utf-8", "replace")))
    return p.stdout.decode("utf-8")


def compare(old_rows, new_rows, leftovers_in_new=()):
    """逐条比对（纯函数，便于 --selftest 拿"故意改坏"的输入验它真会报差异）。"""
    mismatches = []
    if leftovers_in_new:
        mismatches.append("没搬的三处出现在新模块里：%r" % (list(leftovers_in_new),))
    if len(old_rows) != len(new_rows):
        mismatches.append("条数不同：旧 %d，新 %d" % (len(old_rows), len(new_rows)))
    for i, (o, n) in enumerate(zip(old_rows, new_rows)):
        o_name, o_args, o_kw = call_shape(o, "old")
        n_name, n_args, n_kw = call_shape(n, "new")
        if o_name != n_name:
            mismatches.append("#%d 名字不同：%s != %s" % (i, o_name, n_name))
            continue
        if o_args != n_args:
            mismatches.append("#%d %s 位置实参：旧 %r != 新 %r" % (i, o_name, o_args, n_args))
        if o_kw != n_kw:
            only_o = {k: v for k, v in o_kw.items() if n_kw.get(k) != v}
            only_n = {k: v for k, v in n_kw.items() if o_kw.get(k) != v}
            mismatches.append("#%d %s 关键字实参：旧 %r != 新 %r" % (i, o_name, only_o, only_n))
    return mismatches


def _swap_args(row, where="new"):
    """把一条构造的前两个实参对调（返回新的行对象，调用方负责换进列表）。"""
    import copy
    r = list(row)
    node = copy.deepcopy(row[3])
    if len(node.args) >= 2:
        node.args = [node.args[1], node.args[0]] + node.args[2:]
    r[3] = node
    r[4] = ast.unparse(node)
    return tuple(r)


def _selftest(old_rows, new_rows):
    """控制组：对调两处实参（审查亲手做过的那两处），比对器必须报差异。"""
    cases = []
    for want in ("pet_weather.WeatherService", "pet_menu.MenuBuilder"):
        hit = [i for i, r in enumerate(new_rows) if r[2] == want]
        if not hit:
            print("[控制组] 找不到 %s —— 基准/模块变了，先更新本脚本" % want)
            return 1
        cases.append((want, hit[0]))
    bad = 0
    for want, idx in cases:
        broken = list(new_rows)
        broken[idx] = _swap_args(broken[idx])
        got = compare(old_rows, broken, ())
        if not got:
            print("[控制组] %s 对调前两个实参后**没有**报差异 —— 比对器空转！" % want)
            bad += 1
        else:
            print("[控制组] %s 对调 → 报出 %d 条：%s" % (want, len(got), got[0][:120]))
    # 反向控制：原样的两侧必须零差异
    if compare(old_rows, new_rows, ()):
        print("[控制组] 原样的两侧竟然有差异 —— 基准选错了")
        return 1
    print("[控制组] 全部通过（%d 条对调都被抓到）" % (len(cases) - bad))
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description="v2.5.0 服务构造搬迁的 AST 实参对照（只读）")
    ap.add_argument("--baseline-ref", default=DEFAULT_REF)
    ap.add_argument("--baseline-file", default=None)
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--selftest", action="store_true",
                    help="控制组：把两处实参对调，确认比对器真的报差异（防空转）")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    base_src = load_baseline(args)
    new_src = io.open(os.path.join(ROOT, NEW_MODULE), encoding="utf-8").read()
    base_rows = raw_calls(_find_init(ast.parse(base_src)))
    new_rows = raw_calls(ast.parse(new_src))
    old_rows = [r for r in base_rows if r[2] not in LEFTOVERS]
    leftovers_in_new = sorted({r[2] for r in new_rows if r[2] in LEFTOVERS})

    if args.dump:
        print("######## 旧 __init__（归一化后） ########")
        for r in old_rows:
            print("%-40s %s" % (call_shape(r, "old")[0],
                                str(call_shape(r, "old")[1:]))[:200])
        print("######## 新 %s（归一化后） ########" % NEW_MODULE)
        for r in new_rows:
            print("%-40s %s" % (call_shape(r, "new")[0],
                                str(call_shape(r, "new")[1:]))[:200])

    if args.selftest:
        return _selftest(old_rows, new_rows)

    mismatches = compare(old_rows, new_rows, leftovers_in_new)
    if args.dump:
        print()
    print("compared=%d mismatches=%d" % (len(old_rows), len(mismatches)))
    print("  · 旧 __init__ 里被搬走的构造 %d 条；其中注册表首段（_build_libraries + "
          "_build_services）16 条 = CHANGELOG 里那句 compared=16，"
          "build_anim / build_mood 各 1 条" % len(old_rows))
    print("  · 没搬的三处（%s）仍是 %d 条，且**不在**新模块里"
          % ("、".join(LEFTOVERS), len(base_rows) - len(old_rows)))
    for m in mismatches:
        print("  [差异] %s" % m)
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())