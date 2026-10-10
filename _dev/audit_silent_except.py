# -*- coding: utf-8 -*-
"""静默 except 分类审计（只读分析工具，不修改任何仓库文件）。

用法：
    python _dev/audit_silent_except.py                # Markdown 报告（stdout）
    python _dev/audit_silent_except.py --format csv   # CSV 报告（stdout）
    python _dev/audit_silent_except.py --tier A       # 只看 A 档
    python _dev/audit_silent_except.py --all          # 附 OK 的按文件计数

分档口径（全部为静态启发式；本工具不改代码、不写文件）：

  A 档（数据丢失 / 用户可见错误被吞）
      handler 静默（既没 log 也没 raise/弹窗），且满足任一：
        A1 写盘   : try 体内有持久化调用（open(w/a/x/+)、os.replace/remove/rename/
                    makedirs、json.dump、write_text/write_bytes、save()、
                    pet_io.atomic_write*、shutil.*、zipfile/pickle/csv 落盘…）
        A2 网络   : try 体内有网络调用（requests/urllib/http/socket/httpx…）
        A3 后端启停: try 体内有进程/后端启停调用（Popen/subprocess.*/QProcess.start/
                    terminate/kill），且所在函数名含 start/stop/restart/backend/…
        A4 用户动作: 所在函数名是强持久化动词（save/write/export/import/persist/
                    backup/restore/commit/upload/encrypt/decrypt/apply）——用户点了
                    保存却什么都没发生，且没有任何提示。
      A 档不因 handler 里写了“有意忽略”而降级：注释掉的是数据，注释不是证据
      （报告会标 annotated=1 供人工复核）。

  B 档（功能性吞咽，可恢复）
      静默且执行了动作（调用了别的函数），但不含写盘/网络/进程调用——
      多为防御性读、UI 刷新、可选能力探测。只进报告，不改代码。

  C 档（良性）
      静默且 handler 体只有 pass/continue/break/return 常量，try 体内也无
      写盘/网络/进程调用——清理、兜底、尽力而为收尾。

  另两类不计入三档统计：
      OK   : handler 非静默（有 log/raise/弹窗），已处理。
      非生产路径(N): tests/** 与 _dev/** 的静默 except 不计 A 档（测试有意吞异常）。

退出码：0=扫描完成（审计工具不是门禁）。
"""
import argparse
import ast
import io
import os
import re
import sys
from collections import Counter, defaultdict

# ---------------- 路径与文件过滤 ----------------
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".idea", ".vscode", "node_modules",
             "build", "dist", "大肥鱼桌宠_绿色版", "_promo", "_verify_assets", "gallery"}
EDITABLE = ("pet_log.py", "pet_dialogs.py", "桌宠.py", "pet_menu.py")
FORBIDDEN = ("pet_io.py", "pet_book.py", "pet_voice.py", "pet_chat.py", "pet_resources.py",
             "pet_lines.py", "pet_alarm.py", "pet_behaviors.py", "_check_release.py",
             "_verify_v13.py", "_check_static.py")

# ---------------- 判定用名字表 ----------------
# 只有“无名歧义”的持久化方法：出现在任何对象上都基本等于落盘
PERSIST_ATTRS = {
    "write_text", "write_bytes", "atomic_write", "atomic_write_bytes",
    "atomic_write_text", "write_config", "write_json", "write_memory",
    "write_long_term", "writestr", "writerow", "writerows", "extractall", "save",
    "savefig", "dump",
}
# 有歧义的方法：必须落在明确的文件/持久化模块上才算（排除 self.move() / msg.replace()）
PERSIST_ATTRS_QUALIFIED = {
    "write", "writelines", "replace", "rename", "renames", "remove", "unlink",
    "rmtree", "rmdir", "removedirs", "makedirs", "mkdir", "copy", "copy2",
    "copyfile", "copytree", "move", "fsync", "truncate", "touch", "chmod",
    "encrypt", "decrypt",
}
FILE_MODULES = {"os", "shutil", "pathlib", "Path", "pet_io", "pet_config",
                "tempfile", "zipfile", "json", "pickle", "csv", "sqlite3",
                "struct", "marshal", "shelve", "dbm", "codecs"}
# 注意：不含 pet_log——日志设施本身就是错误出口，"写日志失败"不等于"写盘被吞"
# （pet_log.py 内部的兜底另有 EXEMPT_FILES 与 stderr 处理）。
PERSIST_MODULES = {"pet_io", "pet_config", "shutil", "zipfile", "pickle", "csv",
                   "sqlite3", "struct", "marshal", "shelve", "dbm"}
NET_MODULES = {"requests", "urllib", "urllib2", "urllib3", "http", "socket", "httpx",
               "aiohttp", "ftplib", "smtplib", "telnetlib", "xmlrpc", "webbrowser"}
NET_ATTRS = {"urlopen", "urlretrieve", "geturl", "request", "post", "put", "patch",
             "recv", "connect", "create_connection"}
PROC_ATTRS = {"Popen", "run", "call", "check_call", "check_output", "start", "startDetached",
              "terminate", "kill", "spawn", "spawnv", "execv", "system", "killpg"}
PROC_FN_RE = re.compile(r"(start|stop|restart|backend|spawn|launch|shutdown|close|kill|"
                        r"service|daemon|worker|process|thread)", re.I)
# A4 只看“用户动作动词”作为独立词段（snake_case / 驼峰边界），避免 check_thread_writes
# 这类诊断函数被误判成持久化动作。
STRONG_VERB_RE = re.compile(r"(^|_)(save|write|export|import|persist|backup|restore|commit|"
                            r"upload|encrypt|decrypt|apply)(_|$)", re.I)
# 显式豁免：这些位置“写失败”本身就是信号或根本无处可记，归 C 档并在报告里写明理由。
# A5：动态调度器（_call/_invoke/_dispatch…）——静态分析看不到被调方法的实现，
# 但它的调用方全是"用户点了按钮"的回调（保存/应用/切换），吞掉异常＝用户以为成功。
DISPATCH_FN_RE = re.compile(r"^_?(call|invoke|dispatch|apply|run|exec|emit|forward)$", re.I)
EXEMPT_FN_RE = re.compile(r"(data_dir|default_dir|writable|write_probe)", re.I)
EXEMPT_FILES = {"pet_log.py": {"log_error", "_default_dir", "redact"}}
NOISE_NAMES = {"raise", "print", "log_error", "show_bubble", "_warn", "_info",
               "_dialog_failed", "_confirm", "warnings", "warn", "warning", "error",
               "info", "debug", "critical", "exception", "log", "traceback", "format_exc"}
NOISE_BASES = {"pet_log", "logging", "logger", "traceback", "warnings"}
NOISE_TOKENS = ("log", "warn", "error", "info", "debug", "exception", "traceback",
                "print", "raise", "bubble", "dialog_failed", "confirm")
OUT_STREAMS = {"stderr", "stdout", "log", "logger", "fh", "fd", "f", "out", "err"}
ANNOTATION_RE = re.compile(r"有意忽略|intentional|deliberate", re.I)


def _dotted(node):
    """把 Call.func 还原成点号名字：a.b.c() -> a.b.c；取不到返回空串。"""
    parts = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


def _open_is_write(call):
    """open(path, w/a/x/+) / 带 mode= 关键字的写模式。"""
    mode = None
    if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
        mode = call.args[1].value
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            mode = kw.value.value
    if not isinstance(mode, str):
        return False
    return any(c in mode for c in "wax+")


def _classify_try_body(try_node):
    """返回 (写盘?, 网络?, 进程启停?, 证据列表)。"""
    persist = net = proc = False
    why = []
    for call in [n for n in ast.walk(try_node) if isinstance(n, ast.Call)]:
        dotted = _dotted(call.func)
        base = dotted.split(".")[0] if dotted else ""
        last = dotted.split(".")[-1] if dotted else ""
        _is_stdio = ("stderr" in dotted) or ("stdout" in dotted)
        if base == "open" and _open_is_write(call):
            persist = True
            why.append("open(写)@%d" % getattr(call, "lineno", 0))
        elif not _is_stdio and (
                last in PERSIST_ATTRS
                or (last in PERSIST_ATTRS_QUALIFIED and base in FILE_MODULES)
                or (base in PERSIST_MODULES
                    and not re.match(r"(read|load|get|list|has|is|parse|scan|probe|check)",
                                     last or ""))):
            persist = True
            why.append("%s()@%d" % (dotted or "?", getattr(call, "lineno", 0)))
        if base in NET_MODULES:
            net = True
            why.append("%s()@%d" % (dotted, getattr(call, "lineno", 0)))
        elif last in NET_ATTRS and base in {"session", "s", "http", "client", "conn"}:
            net = True
            why.append("%s()@%d" % (dotted, getattr(call, "lineno", 0)))
        if last in PROC_ATTRS and base in {"subprocess", "os", "QProcess", "psutil", "shutil"}:
            proc = True
            why.append("%s()@%d" % (dotted, getattr(call, "lineno", 0)))
    return persist, net, proc, why[:4]


CLEANUP_ATTRS = {"remove", "unlink", "rmtree", "rmdir", "removedirs"}
READONLY_ATTRS = {"isfile", "isdir", "exists", "getsize", "abspath", "join", "listdir",
                  "basename", "dirname", "splitext", "normpath", "realpath"}


def _is_pure_cleanup(try_node):
    """try 体只做"删残留文件"（存在性判断 + remove/rmtree），没有任何写入/复制/建目录。
    这种 handler 静默失败只会在磁盘上留个孤儿文件，不属于数据丢失/用户可见错误。"""
    saw_remove = False
    for call in [n for n in ast.walk(try_node) if isinstance(n, ast.Call)]:
        dotted = _dotted(call.func)
        base = dotted.split(".")[0] if dotted else ""
        last = dotted.split(".")[-1] if dotted else ""
        if base == "open":
            return False
        if last in CLEANUP_ATTRS or re.match(r"(clean|purge|sweep|prune)", last or ""):
            saw_remove = True
            continue
        if last in READONLY_ATTRS:
            continue
        if last in PERSIST_ATTRS or last in PERSIST_ATTRS_QUALIFIED or base in PERSIST_MODULES:
            return False
        # 其它调用（如 self._lib.resolve）视为无害辅助
    return saw_remove


def _has_dynamic_call(try_node):
    """try 体内有"动态派发"调用：裸名字调用 fn(*args) 或 getattr(obj, name)。

    这是调度器（_call/_invoke）的特征——静态分析看不到目标方法，也就无法判断
    它是不是写盘；普通属性调用（pet_log.log_error()）不算。
    """
    for call in [n for n in ast.walk(try_node) if isinstance(n, ast.Call)]:
        if isinstance(call.func, ast.Name) and call.func.id not in (
                "open", "int", "float", "str", "bool", "len", "list", "dict", "set",
                "tuple", "print", "range", "max", "min", "round", "isinstance", "getattr"):
            return True
        if _dotted(call.func) == "getattr":
            return True
    return False


def _returns_report(handler):
    """handler 体只有 return（且至少一个 return 带非常量值）→ 失败被显式转成返回值上报调用方。

    "静默"在这里是**没有日志也没有 raise**的意思；而把异常拼成返回值（例如
    return None, "无法创建角色目录：%s" % e）属于显式上报，调用方据此弹提示。
    静态分析看不到调用方，所以这类归 B 档留在报告里，不当作数据丢失。
    """
    def _walk(stmts):
        saw = False
        for stmt in stmts:
            if isinstance(stmt, (ast.Pass, ast.Continue, ast.Break)):
                continue
            if isinstance(stmt, ast.Return):
                if stmt.value is not None:   # 含哨兵常量（return ""/False/None）
                    saw = True
                continue
            if isinstance(stmt, ast.If):
                ok_body = _walk(stmt.body)
                # 没有 else 分支 = 剩余语句接着处理，视为已上报（后面每条语句仍要过检查）
                ok_else = _walk(stmt.orelse) if stmt.orelse else True
                if not (ok_body and ok_else):
                    return False
                saw = True
                continue
            return False
        return saw

    return _walk(handler.body)


def _handler_is_silent(handler):
    """handler 里既没日志/弹窗，也没 raise（含裸 raise 重抛）→ 静默。"""
    for node in ast.walk(handler):
        if isinstance(node, ast.Raise):
            return False
        if isinstance(node, ast.Call):
            dotted = _dotted(node.func)
            base = dotted.split(".")[0] if dotted else ""
            last = (dotted.split(".")[-1] if dotted else "").lower()
            if base in NOISE_NAMES or last in NOISE_NAMES or base in NOISE_BASES:
                return False
            if any(tok in last for tok in NOISE_TOKENS):
                return False
            if base in OUT_STREAMS and last in {"write", "writelines", "flush", "print"}:
                return False
            if "stderr" in dotted or "stdout" in dotted:
                return False
    return True


def _handler_body_trivial(handler):
    """handler 体只有 pass/continue/break/return 常量。"""
    for stmt in handler.body:
        if isinstance(stmt, (ast.Pass, ast.Continue, ast.Break)):
            continue
        if isinstance(stmt, ast.Return):
            if stmt.value is None or isinstance(stmt.value, ast.Constant):
                continue
            return False
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue
        return False
    return True


# ---------------- v2.4.1（B1）A 档收紧：三类已知误报 ----------------
# 收紧前 A=19，其中三类不是"被吞"：
#   ① 重试 / 轮询循环：handler 只把异常存进变量，循环结束统一 return/raise/记日志；
#   ② 防御性读取：try 体只做取字段 / 类型转换，坏了用常量兜底，不改变用户可见结果；
#   ③ 同一 try 的多个 handler：同一次写盘被数成 2-3 条 A。
# 判据都写成"证据式"的：认不出证据就保持原判（宁可留着让人看，也不悄悄放宽）。

def _handler_lines_text(src, handler):
    """handler 覆盖的源码行（**含注释**）。

    ast 的源码片段在最后一条语句结束处就截断了，于是 `pass  # 有意忽略：…` 这种**同行尾注释**
    被漏掉，"已注释"一列会误报成否。按行号取整段就没有这个问题（v2.4.1 B1 顺带修）。
    """
    lo = getattr(handler, "lineno", 1)
    hi = getattr(handler, "end_lineno", lo)
    return "\n".join(src.splitlines()[lo - 1:hi])


def _ends_with_report(stmts):
    """一组语句"最后一步"是不是把失败上报出去（return 非常量值 / raise）。

    v2.4.1（B1）：`_returns_report` 太严——handler 里先清理残留、再 `return None, "复制失败"`
    的写法它认不出（见到第一条非 return 语句就放弃），于是 pet_resources 的 6 处复制失败、
    pet_export 的打包失败都被算成"A 档数据丢失"。清理语句不该抹掉上报结论。
    """
    stmts = [s for s in stmts if not isinstance(s, (ast.Pass,))]
    if not stmts:
        return False
    last = stmts[-1]
    if isinstance(last, ast.Raise):
        return True
    if isinstance(last, ast.Return):
        return last.value is not None and not isinstance(last.value, ast.Constant)
    if isinstance(last, ast.If) and last.orelse:
        return _ends_with_report(last.body) and _ends_with_report(last.orelse)
    return False


def _handler_ends_with_report(handler):
    """handler 的最后一步把失败上报给调用方（清理由此之前的语句负责）。"""
    return _ends_with_report(handler.body)


def _innermost_func(tree, target):
    """target 所属的最内层函数节点（模块级语句返回 None）。"""
    best = None
    ln = getattr(target, "lineno", 0)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.lineno <= ln <= getattr(node, "end_lineno", node.lineno):
                if best is None or node.lineno >= best.lineno:
                    best = node
    return best


def _assigned_names(node):
    """节点里被赋值的局部变量名（handler 把异常存进 last/err 这类变量的写法）。"""
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Assign):
            out.update(t.id for t in n.targets if isinstance(t, ast.Name))
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            out.add(n.target.id)
    return out


def _reported_later(func_node, try_node, names):
    """try 之后（同一函数内）有没有把这个变量 return / raise / 记日志出去。

    重试循环的常见写法是"handler 里只存错误，循环结束再统一上报"——handler 静态上看是
    静默的，但失败并没有被吞。判据要求真的看到"同一个变量名出现在其后的上报语句里"，
    认不出就不降级。
    """
    if not names or func_node is None:
        return False
    ln = getattr(try_node, "lineno", 0)
    for n in ast.walk(func_node):
        if not isinstance(n, (ast.Return, ast.Raise, ast.Call)):
            continue
        if getattr(n, "lineno", 0) <= ln:
            continue
        if isinstance(n, ast.Call):
            dotted = _dotted(n.func)
            last = (dotted.split(".")[-1] if dotted else "").lower()
            if not (dotted.split(".")[-1:] and (last in NOISE_NAMES
                                                or any(tok in last for tok in NOISE_TOKENS))):
                continue
        if any(isinstance(x, ast.Name) and x.id in names for x in ast.walk(n)):
            return True
    return False


def _pure_defensive_read(try_node):
    """try 体只做"取字段 / 类型转换"这类无副作用动作（坏了就用常量兜底）→ True。

    这种静默 except 不改变用户看得见的结果（值本来就是可选的），不该按"A4 用户动作失败
    无提示"计。带读 open()、写盘、网络、子进程的一律返回 False（读配置回填这类失败会丢
    真实数据，保留 A 让人看）。
    """
    read_only = READONLY_ATTRS | {"get", "dict", "list", "set", "tuple", "int", "float",
                                  "str", "bool", "len", "isinstance", "strip", "lower",
                                  "upper", "split", "format", "loads", "keys", "values",
                                  "items", "copy", "deepcopy"}
    for call in [n for n in ast.walk(try_node) if isinstance(n, ast.Call)]:
        dotted = _dotted(call.func)
        base = dotted.split(".")[0] if dotted else ""
        last = dotted.split(".")[-1] if dotted else ""
        if base == "open":
            return False
        if not last or last not in read_only:
            return False
        if base in NET_MODULES or base in PERSIST_MODULES or base in FILE_MODULES:
            return False
    return True


def _snippet(text, node, limit=150):
    """打平一段源码做单行摘要。"""
    try:
        seg = ast.get_source_segment(text, node) or ""
    except Exception:
        seg = ""
    seg = re.sub(r"\s+", " ", seg).strip()
    return (seg[:limit] + "...") if len(seg) > limit else seg


def _enclosing_map(tree):
    """节点 id -> 最近的外层函数/类名。"""
    owner = {}
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for child in ast.walk(fn):
                owner.setdefault(id(child), fn.name)
    return owner


def _iter_targets(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


def scan(root):
    findings = []
    a_seen = set()   # 同一 try 只计一次 A（v2.4.1 B1：多 handler 不重复计数）
    for path in sorted(_iter_targets(root)):
        rel = os.path.relpath(path, root).replace("\\", "/")
        try:
            with io.open(path, "r", encoding="utf-8") as f:
                src = f.read()
            lines = src.splitlines()
            tree = ast.parse(src)
        except (SyntaxError, UnicodeDecodeError, OSError) as e:
            findings.append(dict(tier="SKIP", file=rel, line=0, func="", reason="%r" % (e,),
                                 snippet="", editable=False, forbidden=False,
                                 annotated=False, nonprod=False))
            continue
        owner = _enclosing_map(tree)
        # 非生产路径：tests/_dev + 仓库根的下划线维护脚本（_verify_*/_check_* 等，不随包发布）
        nonprod = (rel.startswith("tests/") or rel.startswith("_dev/")
                   or (("/" not in rel) and os.path.basename(rel).startswith("_")))
        basename = os.path.basename(rel)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            for handler in node.handlers:
                silent = _handler_is_silent(handler)
                func = owner.get(id(handler), owner.get(id(node), "<module>"))
                annotated = bool(ANNOTATION_RE.search(_handler_lines_text(src, handler)))
                persist, net, proc, why = _classify_try_body(node)
                trivial = _handler_body_trivial(handler)
                exempt = ""
                if rel in EXEMPT_FILES and func in EXEMPT_FILES[rel]:
                    exempt = "日志设施自身：写日志失败无处可记（代码内已有 stderr 兜底）"
                elif EXEMPT_FN_RE.search(func or ""):
                    exempt = "写权限探针：失败＝目录不可写（回退信号，不是错误）"
                n_calls = len([n for n in ast.walk(node) if isinstance(n, ast.Call)])
                cleanup_only = persist and _is_pure_cleanup(node)
                if not silent:
                    tier, reason = "OK", "已处理（有 log/raise/弹窗）"
                elif exempt:
                    tier, reason = "C", "良性（显式豁免）：" + exempt
                elif cleanup_only:
                    tier, reason = "C", "良性：仅删除孤儿/残留文件，失败只留文件，无数据丢失"
                elif _returns_report(handler) or _handler_ends_with_report(handler):
                    tier, reason = "B", "失败以返回值/哨兵上报调用方（静态看不到调用方怎么处理）"
                elif _reported_later(_innermost_func(tree, node), node,
                                     _assigned_names(handler)):
                    tier, reason = "B", ("重试/轮询循环：handler 只存错误，其后"
                                         " return/raise/日志统一上报（不是吞掉）")
                elif persist:
                    tier, reason = "A", "A1 写盘被吞: " + ",".join(why)
                elif net:
                    tier, reason = "A", "A2 网络被吞: " + ",".join(why)
                elif proc and PROC_FN_RE.search(func):
                    tier, reason = "A", "A3 后端启停被吞: " + ",".join(why)
                elif (STRONG_VERB_RE.search(func or "") and n_calls
                      and not _pure_defensive_read(node)):
                    tier, reason = "A", "A4 用户动作(%s)失败无提示" % func
                elif (DISPATCH_FN_RE.match(func or "") and n_calls
                      and _has_dynamic_call(node)):
                    tier, reason = "A", "A5 动态调度器(%s)吞掉回调异常：调用方以为成功" % func
                elif trivial:
                    tier, reason = "C", "良性: handler 为空/常量返回，无写盘网络"
                else:
                    tier, reason = "B", "功能性吞咽（可恢复，无写盘/网络）"
                if tier == "A":
                    if id(node) in a_seen:
                        tier, reason = "B", "同一 try 的另一个 handler（A 档只计一次，同一次写盘不重复计数）"
                    else:
                        a_seen.add(id(node))
                if nonprod and tier == "A":
                    tier, reason = "N", "非生产路径(tests/_dev)不计 A 档: " + reason
                findings.append(dict(
                    tier=tier, file=rel, line=getattr(handler, "lineno", 0),
                    func=func, reason=reason, snippet=_snippet(src, node),
                    editable=(basename in EDITABLE and not nonprod),
                    forbidden=(basename in FORBIDDEN), annotated=annotated,
                    nonprod=nonprod))
    return findings


def report_md(findings, show_all):
    out = []
    counts = Counter(f["tier"] for f in findings)
    prod = [f for f in findings if not f["nonprod"]]
    pc = Counter(f["tier"] for f in prod)
    out.append("# 静默 except 审计报告（只读分析，未修改任何代码）")
    out.append("")
    out.append("- 扫描 .py 文件：%d 个；except handler 总数：%d"
               % (len({f["file"] for f in findings}), len(findings)))
    out.append("- 生产路径三档统计（tests/ 与 _dev/ 不计入 A 档）："
               "A=%d（数据丢失/用户可见错误被吞）, B=%d（功能性吞咽）, "
               "C=%d（良性）, OK=%d（已处理）"
               % (pc["A"], pc["B"], pc["C"], pc["OK"]))
    out.append("- 含非生产路径的全量：A=%d, B=%d, C=%d, OK=%d, N(测试/_dev 静默)=%d, SKIP=%d"
               % (counts["A"], counts["B"], counts["C"], counts["OK"],
                  counts["N"], counts["SKIP"]))
    out.append("")
    out.append("## A 档按文件分布（生产路径）")
    out.append("")
    out.append("| 文件 | A 档条数 | 本次可改 |")
    out.append("|---|---|---|")
    per_file = defaultdict(int)
    editable_file = {}
    for f in prod:
        if f["tier"] == "A":
            per_file[f["file"]] += 1
            editable_file[f["file"]] = f["editable"]
    for name in sorted(per_file, key=lambda k: (-per_file[k], k)):
        out.append("| %s | %d | %s |" % (name, per_file[name],
                                         "是" if editable_file[name] else "否（文件禁区）"))
    if not per_file:
        out.append("| - | 0 | - |")
    out.append("")
    for tier, title in (("A", "A 档：数据丢失 / 用户可见错误被吞（应补日志）"),
                        ("B", "B 档：功能性吞咽（可恢复；只报告，不改代码）"),
                        ("C", "C 档：良性（只报告，不改代码）")):
        rows = [f for f in prod if f["tier"] == tier]
        out.append("## %s（%d 条）" % (title, len(rows)))
        out.append("")
        if not rows:
            out.append("（无）")
            out.append("")
            continue
        out.append("| 文件:行 | 函数 | 可改 | 已注释 | 理由 | 片段 |")
        out.append("|---|---|---|---|---|---|")
        for f in sorted(rows, key=lambda x: (x["file"], x["line"])):
            out.append("| %s:%d | %s | %s | %s | %s | %s |" % (
                f["file"], f["line"], f["func"] or "-",
                "是" if f["editable"] else ("禁区" if f["forbidden"] else "否"),
                "是" if f["annotated"] else "-",
                f["reason"].replace("|", "/"), f["snippet"].replace("|", "/")))
        out.append("")
    others = [f for f in findings if f["tier"] in ("N", "SKIP")]
    out.append("## 非生产路径（tests/_dev，不计 A 档，仅供参考）：%d 条" % len(others))
    out.append("")
    if others:
        out.append("| 文件:行 | 档 | 理由 |")
        out.append("|---|---|---|")
        for f in sorted(others, key=lambda x: (x["file"], x["line"]))[:40]:
            out.append("| %s:%d | %s | %s |" % (f["file"], f["line"], f["tier"],
                                                f["reason"].replace("|", "/")))
        if len(others) > 40:
            out.append("| ... | ... | 其余 %d 条用 --format csv 看全量 |" % (len(others) - 40))
    else:
        out.append("（无）")
    if show_all:
        out.append("")
        out.append("## OK：已处理的 except（按文件计数）")
        out.append("")
        ok_by_file = Counter(f["file"] for f in findings if f["tier"] == "OK")
        for name in sorted(ok_by_file):
            out.append("- %s：%d" % (name, ok_by_file[name]))
    return "\n".join(out)


def report_csv(findings):
    def q(s):
        return '"%s"' % str(s).replace('"', "'")
    out = ["tier,file,line,func,editable,forbidden,annotated,reason,snippet"]
    for f in sorted(findings, key=lambda x: (x["tier"], x["file"], x["line"])):
        out.append(",".join([f["tier"], q(f["file"]), str(f["line"]), q(f["func"]),
                             "1" if f["editable"] else "0",
                             "1" if f.get("forbidden") else "0",
                             "1" if f["annotated"] else "0",
                             q(f["reason"]), q(f["snippet"])]))
    return "\n".join(out)


def main(argv=None):
    # 报告含中文与 emoji（片段来自源码）；Windows 控制台默认 GBK 会 UnicodeEncodeError，
    # 这里把 stdout 固定成 UTF-8（只影响本进程的输出编码，不写文件）。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="静默 except 分类审计（只读，不改代码）")
    ap.add_argument("--root",
                    default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    help="仓库根目录（默认脚本上一级）")
    ap.add_argument("--format", choices=("md", "csv"), default="md")
    ap.add_argument("--tier", choices=("A", "B", "C", "all"), default="all")
    ap.add_argument("--all", action="store_true", help="附 OK 的按文件计数")
    args = ap.parse_args(argv)
    findings = scan(args.root)
    if args.format == "csv":
        sel = findings if args.tier == "all" else [f for f in findings if f["tier"] == args.tier]
        sys.stdout.write(report_csv(sel) + "\n")
    else:
        sys.stdout.write(report_md(findings, args.all) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
