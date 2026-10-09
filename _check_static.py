# -*- coding: utf-8 -*-
"""全项目静态体检（开发用，不进绿色版）：把易错模式机器扫出来。

检查项：
  A 入口/属性解析   pet_dialogs.* / pet.* / pet.<服务>.* / _call|_get(pet,"x")
  B 配置键一致      cfg["k"]=写 / cfg.get("k") 读 必须在 DEFAULT_CONFIG（或所属子段白名单）里
  C 空序列取词      random.choice(可能为空) 且无兜底 → IndexError 风险
  D 数值转换       int(...)/float(...) 直接吃用户配置且不在 try 内 → ValueError 风险
  F 定时器清单     构造的 QTimer 是否都在退出时停止
  G 线程安全       threading.Thread 的目标函数里是否直接碰 Qt 控件
  H 未使用导入
  I 死常量        模块级大写常量零引用
  L 散落 print     非 __main__ 块里的 print

用法：python _check_static.py   退出码 0=无问题 1=有问题（"待确认"只打印、不阻塞）
"""
import ast
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
MAIN = "桌宠.py"
SKIP = {"_check_static.py", "_check_release.py", "_verify_v13.py", "_verify_green.py"}


def sources():
    out = []
    for f in sorted(os.listdir(ROOT)):
        if f.endswith(".py") and f not in SKIP:
            out.append((f, io.open(os.path.join(ROOT, f), encoding="utf-8").read()))
    return out


def load_main():
    sys.path.insert(0, ROOT)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import importlib
    return importlib.import_module("桌宠")


def strip_comments(src):
    out = []
    for ln in src.split("\n"):
        s = ln.split("#", 1)[0]
        out.append(s)
    return "\n".join(out)


def main():
    problems = []
    notes = []
    try:
        main_mod = load_main()
    except Exception as e:
        # 无 Qt / 依赖缺失时给一句能看懂的结论（而不是裸 traceback 让发布检测只剩"退出码 1"）
        print("静态体检无法运行（缺少 Qt 或依赖）：%r" % (e,))
        return 1
    import pet_dialogs
    pet_attrs = set(dir(main_mod.PetWindow))
    defaults = set(main_mod.DEFAULT_CONFIG)
    files = sources()

    # ---------- A 入口/属性解析 ----------
    for name, raw in files:
        src = strip_comments(raw)
        for m in re.finditer(r"pet_dialogs\.([A-Za-z_][A-Za-z0-9_]*)", src):
            if not hasattr(pet_dialogs, m.group(1)):
                problems.append("A pet_dialogs.%s 未定义 @ %s" % (m.group(1), name))
        for m in re.finditer(r"\bpet\.(_?[a-z][A-Za-z0-9_]*)\s*\(", src):
            n = m.group(1)
            if n not in pet_attrs:
                problems.append("A pet.%s 未定义 @ %s" % (n, name))
        for m in re.finditer(r"_call\(\s*[a-z_.]*pet[a-z_.]*\s*,\s*\"([A-Za-z_][A-Za-z0-9_]*)\"", src):
            if m.group(1) not in pet_attrs:
                problems.append("A _call(pet,%r) 未定义 @ %s" % (m.group(1), name))
        for m in re.finditer(r"getattr\(\s*(?:pet|self\._pet|self\.pet)\s*,\s*\"([A-Za-z_][A-Za-z0-9_]*)\"", src):
            pass  # 防御性 getattr 允许取不到

    # ---------- B 配置键 ----------
    try:
        import pet_voice, pet_config
        vkeys = set(pet_voice.normalize_voice(None).keys())
        # 物理子段白名单：normalize_physics 在 pet_config（不在 pet_physics）；
        # 它要 dict 入参（None 会 AttributeError），所以传空 dict
        pkeys = set(pet_config.normalize_physics({}).keys())
    except Exception as e:
        vkeys, pkeys = set(), set()
        problems.append("B 子段白名单读取失败（会导致大量误报）：%r" % (e,))  # 不能让检查悄悄退化
    for name, raw in files:
        src = strip_comments(raw)
        for m in re.finditer(r"(\w*cfg)\[\s*\"([a-z_][A-Za-z0-9_]*)\"\s*\]\s*=", src):
            var, key = m.group(1), m.group(2)
            if var == "cfg" and key not in defaults and not key.startswith("_"):
                problems.append("B cfg[%r]= 不在 DEFAULT_CONFIG（保存会被丢弃）@ %s" % (key, name))
        for m in re.finditer(r"cfg\.get\(\s*\"([a-z_][A-Za-z0-9_]*)\"", src):
            key = m.group(1)
            if key not in defaults and key not in vkeys and key not in pkeys:
                notes.append("B? cfg.get(%r) 不在白名单（可能是子段键/错拼）@ %s" % (key, name))

    # ---------- C2 空池（AST 精确判定，质量审查 L2）----------
    # random.choice/sample/secrets.choice 的参数若是空字面量，或 .get(k) 缺默认值 → problem
    # （这是 v2.1.2"空台词池崩"的结构性防线，此前正则版永不命中）
    for name, raw in files:
        if name == "_check_static.py":
            continue
        try:
            tree = ast.parse(raw)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            fnn = node.func
            fname = fnn.attr if isinstance(fnn, ast.Attribute) else getattr(fnn, "id", "")
            if fname not in ("choice", "sample"):
                continue
            arg = node.args[0]
            if isinstance(arg, (ast.List, ast.Tuple)) and not getattr(arg, "elts", None):
                problems.append("C 空字面量取词（必抛 IndexError）@ %s:%d" % (name, node.lineno))
            elif (isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute)
                  and arg.func.attr == "get" and len(arg.args) < 2):
                problems.append("C 取词参数是 .get(k) 无默认值（可能 None）@ %s:%d"
                                % (name, node.lineno))

    # ---------- D 数值转换 ----------
    for name, raw in files:
        lines = raw.split("\n")
        src = strip_comments(raw)
        for m in re.finditer(r"\b(int|float)\(\s*(?:self\.)?_?cfg\.get\(|\b(int|float)\(\s*self\.cfg\[|\b(int|float)\(\s*cfg\[", src):
            ln = src[:m.start()].count("\n") + 1
            ctx = "\n".join(lines[max(0, ln - 8):ln + 2])
            if any("norm-ok" in lines[_i] for _i in range(max(0, ln - 6), ln)):
                continue  # 显式标注"上游已归一化，这里安全"（注释可写在上面几行）
            if "except" not in ctx and "try:" not in ctx:
                problems.append("D %s(...) 直接吃配置且附近无 try @ %s:%d" % (m.group(1) or m.group(2) or m.group(3), name, ln))

    # ---------- F 定时器清单 ----------
    main_src = dict(files).get(MAIN, "")
    # L4 家族：QTimer.singleShot(ms, lambda...) 无 context → 窗口销毁后仍回调（会冒到 excepthook）
    for name, raw in files:
        for m in re.finditer(r"QTimer\.singleShot\(([^\n]*)\)", raw):
            args = m.group(1)
            depth = 0
            parts = []
            cur = ""
            for ch in args:
                if ch in "([{":
                    depth += 1
                elif ch in ")]}":
                    depth -= 1
                if ch == "," and depth == 0:
                    parts.append(cur)
                    cur = ""
                else:
                    cur += ch
            parts.append(cur)
            if len(parts) == 2:  # (ms, 回调) → 没有 context 对象
                ln = raw[:m.start()].count("\n") + 1
                notes.append("F? QTimer.singleShot 无 context（建议 singleShot(ms, self, fn)）@ %s:%d"
                             % (name, ln))
    created = set(re.findall(r"self\.(_\w+)\s*=\s*QTimer\(", main_src))
    quit_src = main_src[main_src.find("def _quit("):]
    # 判据（质量审查 M4）：必须**真的停止**——出现 self.X.stop()，或 X 出现在 for t in (...) 停止元组里。
    # 此前用"名字在 _quit 前 6000 字符内出现过"，任何引用都算已停（假阴性），且 6000 是硬编码。
    _tuple_txt = ""
    _tm = re.search(r"for t in \((.*?)\):", quit_src, re.S)
    if _tm:
        _tuple_txt = _tm.group(1)
    for t in sorted(created):
        if re.search(r"self\.%s\s*\.\s*stop\(" % re.escape(t), quit_src):
            continue
        if re.search(r"self\.%s\b" % re.escape(t), _tuple_txt):
            continue
        problems.append("F 定时器 self.%s 构造后未在 _quit 停止（既没 stop() 也不在停止元组里）" % t)

    # ---------- G 线程安全 ----------
    qt_calls = re.compile(r"(show_bubble|setText|setPixmap|\.move\(|\.show\(|\.hide\(|QMessageBox|\.item\.)")
    for name, raw in files:
        for m in re.finditer(r"threading\.Thread\(\s*target\s*=\s*([A-Za-z_.]+)", raw):
            tgt = m.group(1)
            fn = tgt.split(".")[-1]
            # 边界：下一个同级/上级定义，或模块级代码（\n\S）——否则"类里最后一个方法"会被漏检
            mm = re.search(r"def %s\(self[^)]*\):(.*?)(?=\n    def |\nclass |\n\S|\Z)"
                           % re.escape(fn), raw, re.S)
            if mm and qt_calls.search(mm.group(1)):
                problems.append("G 线程目标 %s 直接碰 Qt 控件 @ %s" % (tgt, name))


    # ---------- H 未使用导入 ----------
    for name, raw in files:
        tree = ast.parse(raw)
        imported = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    imported[(a.asname or a.name.split(".")[0])] = node.lineno
            elif isinstance(node, ast.ImportFrom):
                for a in node.names:
                    imported[(a.asname or a.name)] = node.lineno
        for k, ln in imported.items():
            if ln <= 0 or any(("noqa" in l and k in l) for l in raw.split("\n")[max(0, ln - 2):ln + 2]):
                continue  # 显式 noqa / 位置未知：尊重开发者意图
            # 文本计数：除导入行本身以外的出现次数（比 AST 名字集更贴近"实际是否使用"）
            used_text = 0
            for i, l in enumerate(raw.split("\n"), 1):
                if i == ln:
                    continue
                if re.search(r"\b%s\b" % re.escape(k), l.split("#", 1)[0]):
                    used_text += 1
            if used_text == 0:
                notes.append("H? 未使用导入 %s @ %s:%d" % (k, name, ln))

    # ---------- I 死常量 ----------
    for name, raw in files:
        src = strip_comments(raw)
        for m in re.finditer(r"^([A-Z][A-Z0-9_]{3,})\s*=", src, re.M):
            const = m.group(1)
            uses = 0  # 统计"引用"，排除以该常量名开头的定义行
            for _oname, oraw in files:
                for ln in strip_comments(oraw).split("\n"):
                    if re.search(r"\b%s\b" % re.escape(const), ln) and not re.match(
                            r"\s*%s\s*=" % re.escape(const), ln):
                        uses += 1
            if uses == 0:
                notes.append("I? 常量 %s 零引用 @ %s" % (const, name))

    # ---------- L 散落 print ----------
    # 只查运行时代码（pet_*.py / 桌宠.py / main.py）；去背景.py、生成占位角色.py 是独立开发脚本，
    # 它们的 print 是给人看的正常输出。
    runtime_files = [x for x in files if x[0].startswith(("pet_", "桌宠", "main"))]
    for name, raw in runtime_files:
        lines = raw.split("\n")
        in_main_block = False
        for i, ln in enumerate(lines):
            if ln.startswith('if __name__'):
                in_main_block = True
            if not in_main_block and re.match(r"\s+print\(", ln):
                problems.append("L 非 __main__ 块的 print @ %s:%d" % (name, i + 1))

    print("=== 问题（必须修/确认）===")
    for p in sorted(set(problems)):
        print("  " + p)
    print("\n=== 待人工确认（启发式，可能有误报）===")
    for n in sorted(set(notes)):
        print("  " + n)
    print("\n问题 %d 条，待确认 %d 条" % (len(set(problems)), len(set(notes))))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())