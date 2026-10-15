# -*- coding: utf-8 -*-
"""D7-B 静默 except 白名单：数据化登记 + 可复跑的判定器（v2.6.0）。

为什么要有这个文件（任务书硬要求 a）：
    白名单要落成数据 + 有测试钉住（新增静默 except 必须让测试红——否则白名单会变成垃圾桶）。
    所以判定逻辑写在这里（可被 tests/test_silent_except_v252.py 直接 import），
    判定结果写在 _dev/silent_except_whitelist_summary.json（**数据**，不是代码里的豁免分支；
    后缀 _summary.json 是 .gitignore 的入库白名单约定，见 WL_PATH 处的注释）。

口径：
  · 覆盖范围 = 生产路径（tests/ 与 _dev/ 之外）里 **handler 静默**（既无日志也无 raise）
    的 except —— 即审计工具的 B 档 ∪ C 档。OK 档（已有日志/上报）与 A 档（数据丢失）不在其中。
  · 键 = (文件, 函数, 结构指纹)。结构指纹剥掉标识符/常量/消息文本，只留语句与表达式结构
    （改文案、改变量名不算"变了"；把 return 改成 pass 一定算），因此它能抓"新增/改写"，
    又不会被无意义的改名打红。
  · 新增静默 except → 键不在白名单 → **测试红**（提示"先补限流日志，或登记理由"）。
  · 登记后理由必须是 REASONS 里的码，且 unreviewed 被测试显式拒绝——
    --write 只会把新键登记成 unreviewed（红着），必须有人给出真理由才会变绿。

领地外 → 已收口（v2.6.0 第 4 轮 · 找茬审查 B-3）：
    并行改造期 razor 曾把 4 个文件整个豁免掉（见 DELEGATED_FILES），代价是**82 条静默
    except 落在豁免区、razor 对它们零覆盖**——"白名单落成数据 + 新增静默 except 必须让
    测试红"这条硬要求在 pet_plugin.py / pet_plugin_host.py / pet_plugin_index.py /
    pet_dialogs.py 上根本不成立（在这 4 个文件里新写一个 except: pass，没有任何用例会红）。
    A/C 停笔后一次性收口：DELEGATED_FILES 清空，82 条逐条给出真理由码 + 一句话理由 +
    源码证据。空元组**保留**着（不是删掉这个机制）：它是"豁免名单必须显式为空"的判据，
    tests/test_silent_except_v252.py 有一条用例钉住它 = ()。

用法：
    python -B _dev/silent_except_whitelist.py            # 打印判定结果（= 测试的同一实现）
    python -B _dev/silent_except_whitelist.py --check    # 有问题则退出码 1
    python -B _dev/silent_except_whitelist.py --write    # 把新静默 except 登记成 unreviewed
    python -B _dev/silent_except_whitelist.py --write --seed   # 首次生成：用启发式先填理由
"""
import argparse
import ast
import copy
import hashlib
import importlib.util
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIT_PATH = os.path.join(HERE, "_dev", "audit_silent_except.py")
# 文件名必须落在 .gitignore 的白名单里！_dev/ 只入库 *.py / *.md / *_summary.json /
# mutations_*.json / results_*.json（v2.4.3 起）。用普通的 .json 名字 → 文件不入库 →
# CI 上 load_whitelist() 直接 FileNotFoundError（整套 razor 变红）。这里按 *_summary.json 形状命名。
WL_PATH = os.path.join(HERE, "_dev", "silent_except_whitelist_summary.json")
WL_SCHEMA = 1

# 并行改造期的豁免名单 —— **v2.6.0 第 4 轮已清空**（理由见模块 docstring）。
# 保留这个常量而不是删掉它：它是"豁免名单必须为空"的判据（测试直接断言 == ()），
# 以后再有并行改造要临时豁免，也得先让那条用例红一次，把代价摆在明面上。
DELEGATED_FILES = ()

# 理由码（闭集）：测试会拒绝任何不在这里的码，以及 unreviewed。
REASONS = {
    "reported": "失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志",
    "cleanup": "尽力而为的清理/回滚：失败只会在磁盘上留孤儿文件，不改变用户可见结果",
    "teardown": "关闭/退出/销毁路径：进程即将结束或对象即将销毁，记日志没有接收方",
    "probe": "能力/存在性探针：失败本身就是安全的假值（is_running=False / 没有这个能力）",
    "optional": "可选能力降级（音效/动画/缩放/预览/悬停提示）：失败＝该能力缺席，不丢数据",
    "fallback": "坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果",
    "self-logging": "日志设施自身的兜底：写日志失败无处可记（代码内已有 stderr 出口）",
    "unreviewed": "尚未人工判定——测试会因此变红（刻意如此：白名单不许自动扩容）",
}


def load_audit():
    """按路径加载 _dev 下的审计脚本（它不是包内模块）。"""
    spec = importlib.util.spec_from_file_location("audit_silent_except_wl", AUDIT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------- 结构指纹 ----------------
class _Anonymize(ast.NodeTransformer):
    """把标识符/常量/参数名抹平，只留"语句与表达式长什么样"。

    这样"改了消息文案/变量名/异常类型"不会让指纹变，"把 return 改成 pass"一定会变。
    """

    def visit_Name(self, node):
        return ast.copy_location(ast.Name(id="_", ctx=node.ctx), node)

    def visit_Attribute(self, node):
        self.generic_visit(node)
        return ast.copy_location(ast.Name(id="_", ctx=ast.Load()), node)

    def visit_Constant(self, node):
        return ast.copy_location(ast.Constant(value=None), node)

    def visit_arg(self, node):
        self.generic_visit(node)
        node.arg = "_"
        node.annotation = None
        return node

    def visit_keyword(self, node):
        self.generic_visit(node)
        node.arg = None
        return node

    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        node.name = "_"
        node.returns = None
        return node


def handler_shape(handler):
    """ExceptHandler → 10 位结构指纹（口径见 _Anonymize）。"""
    node = _Anonymize().visit(copy.deepcopy(handler))
    ast.fix_missing_locations(node)
    return hashlib.sha1(ast.dump(node).encode("utf-8")).hexdigest()[:10]


def _flatten(text, limit=120):
    one = re.sub(r"\s+", " ", text or "").strip()
    return one[:limit] + ("..." if len(one) > limit else "")


def _scope_map(tree):
    """节点 id -> 最近的**作用域名**：方法就给方法名（最内层函数优先），否则类名/模块。

    审计工具的 owner 取的是**最外层**名字（PetWindow 的 31 个方法都叫 "PetWindow"），
    于是白名单里 31 个不同的静默 except 会被挤成一个条目。这里改成"最内层函数名"，
    让每个方法各占一条——报告要逐条判定，razor 的报错也要指得出是哪个方法。
    """
    out = {}

    def walk(node, cur):
        for child in ast.iter_child_nodes(node):
            nm = cur
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                nm = child.name
            elif isinstance(child, ast.ClassDef) and cur is None:
                nm = child.name
            out[id(child)] = nm
            walk(child, nm)

    walk(tree, None)
    return out


def _evidence(src, handler):
    """登记用的**源码证据**：handler 原文（单行化）。报告"现行为"一列直接取它。"""
    try:
        seg = ast.get_source_segment(src, handler) or ""
    except Exception:
        seg = ""
    return _flatten(seg, 130)


# ---------------- 扫描：生产路径里的静默 handler ----------------
def scan_silent(root=None, audit_mod=None):
    """返回 (entries, findings)。

    entries: key -> {key, file, func, shape, count, tier, evidence, lines}
    findings: 审计工具的全部结果（判定 A 档要用）
    """
    audit_mod = audit_mod or load_audit()
    root = root or HERE
    findings = audit_mod.scan(root)
    prod = [f for f in findings if not f["nonprod"]]
    by_line = {}
    for f in prod:
        by_line[(f["file"], f["line"])] = f
    entries = {}
    for path in sorted(audit_mod._iter_targets(root)):
        rel = os.path.relpath(path, root).replace("\\", "/")
        try:
            with io.open(path, "r", encoding="utf-8-sig") as fh:
                src = fh.read()
            tree = ast.parse(src)
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        owner = _scope_map(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            for handler in node.handlers:
                if not audit_mod._handler_is_silent(handler):
                    continue
                f = by_line.get((rel, getattr(handler, "lineno", 0)))
                if f is None or f["tier"] not in ("B", "C"):
                    continue
                func = owner.get(id(handler), owner.get(id(node), "<module>")) or "<module>"
                shape = handler_shape(handler)
                key = "%s|%s|%s" % (rel, func, shape)
                ent = entries.get(key)
                if ent is None:
                    ent = entries[key] = dict(key=key, file=rel, func=func, shape=shape,
                                              count=0, tier=f["tier"],
                                              evidence=_evidence(src, handler),
                                              try_evidence=_evidence(src, node),
                                              tier_reason=f["reason"], lines=[])
                ent["count"] += 1
                ent["lines"].append(getattr(handler, "lineno", 0))
    for ent in entries.values():
        ent["lines"].sort()
    return entries, findings


# ---------------- 启发式种子（只在 --seed 时用；产出仍要人工过一遍） ----------------
_CLEANUP_RE = re.compile(r"(remove|rmtree|unlink|rmdir|deleteLater|delete|cleanup|purge|"
                         r"sweep|prune|popleft)", re.I)
_TEARDOWN_RE = re.compile(r"(^|_|\.)(close|stop|terminate|kill|disconnect|hide|shutdown|"
                          r"quit|deleteLater|wait|accept|ignore)(\(|$)", re.I)
_PROBE_RE = re.compile(r"(isfile|isdir|exists|getsize|islink|status|isRunning|isActive|"
                       r"pid_exists|hasattr|isNull|isValid|listdir|memory_info|screens|"
                       r"screenAt|instance|geometry|availableGeometry|create_time|"
                       r"getpreferredencoding|lookup|signature)", re.I)


# 人工复核覆盖（代理 B 逐条判定后对启发式种子的修正）。
# 每条 = (文件, 函数名, handler 原文里的稳定子串) -> 理由码；不用行号（行号会漂）。
# 为什么需要它：启发式只看"看得见的形状"，下面这些都认得出形状、认不出**语义**
# （例如"回退、恢复、默认值"三者形状一样，结论不同）。
REVIEW_OVERRIDES = [
    # bubble_style 坏值 → 回默认样式（不是探针）
    ("pet_config.py", "normalize_cfg", 'cfg["bubble_style"] = dict(defaults', "fallback"),
    # 取不到本地密钥就当作"没有本地密钥"（防御性读取 + 常量兜底）
    ("pet_export.py", "import_bundle", "_local_keys = {}", "fallback"),
    # 写盘异常记进 self.error / done，调用方在 finish 之后读它并弹"写入失败"
    ("pet_export.py", "step", "self.error = e", "reported"),
    # 首次运行没有 config.json：不是错误，按默认配置继续
    ("桌宠.py", "load_config", "首次运行", "fallback"),
    # 文件不存在（首次运行）→ 用默认值继续：不是错误，也不需要愈合
    ("pet_io.py", "_read_json_status", "FileNotFoundError", "fallback"),
    # "这堆字节是不是（几乎就是）UTF-8"——解码失败本身就是答案
    ("pet_io.py", "_almost_utf8", "UnicodeDecodeError", "probe"),
    ("pet_io.py", "_almost_utf8", "return False", "probe"),
    # 自启注册表目标键不存在：建键后继续写（环境差异，不是失败）
    ("桌宠.py", "set_autostart", "CreateKeyEx", "fallback"),
    # Pillow 新旧 API 二选一（AttributeError 就是"旧版"这个答案）
    ("生成占位角色.py", "<module>", "Image.LANCZOS", "fallback"),
    # 时间戳坏了就用当前时间兜底
    ("pet_book.py", "_normalize_record", "time.localtime()", "fallback"),
    # 帧图解码失败 → 空 QPixmap（调用方按"没图"处理）
    ("pet_anim.py", "load_frame_set", "pix = QPixmap()", "fallback"),
    ("桌宠.py", "_money_preload_step", "pix = QPixmap()", "fallback"),
    # 气泡样式值不是数字 → 保持原值
    ("pet_widgets.py", "paintEvent", "QColor(", "fallback"),
    # 子进程枚举失败 → 空列表（退出时少杀几个子进程，不留数据问题）
    ("pet_voice.py", "stop", "kids = []", "cleanup"),

    # ---- v2.6.0 第 4 轮（找茬审查 B-3）：DELEGATED_FILES 清空后新纳入的 82 条 ----
    # 这 82 条逐条人工过了一遍（启发式认得形状、认不出语义的地方在这里改口径；
    # 其余按启发式结论落盘，理由码全部来自 REASONS 闭集，没有一条是 unreviewed）。
    # 匹配口径：证据串是**handler 原文**（不是 try 体），所以同一函数下证据一模一样的
    # 那几条只能靠函数名区分（_save / _app_events / _dialog_failed 各自只有一个）。
    #
    # pet_dialogs.py —— 失败经信号 / 返回值报到界面（reported）
    ("pet_dialogs.py", "run", "已取消处理", "reported"),
    ("pet_dialogs.py", "run", 'self.failed.emit("处理失败', "reported"),
    ("pet_dialogs.py", "refresh_index", "self._apply_index(None", "reported"),
    ("pet_dialogs.py", "_index_worker", 'data, err = None, "读取索引失败', "reported"),
    ("pet_dialogs.py", "_download_worker", 'path, err = None, "下载失败', "reported"),
    # pet_dialogs.py —— 坏值回默认 / 界面刷新降级
    ("pet_dialogs.py", "_to_int", "return default", "fallback"),
    ("pet_dialogs.py", "_save", "except Exception: pass", "fallback"),
    ("pet_dialogs.py", "_refresh", "slots = None", "optional"),
    ("pet_dialogs.py", "_refresh", "binds = {}", "fallback"),
    ("pet_dialogs.py", "_refresh", "except Exception: pass", "optional"),
    ("pet_dialogs.py", "_refresh_launch_status", "st = {}", "fallback"),
    ("pet_dialogs.py", "_refresh_all", "except Exception: pass", "optional"),
    ("pet_dialogs.py", "_on_select", "吃饱图无法预览", "optional"),
    ("pet_dialogs.py", "_app_events", "except Exception: pass", "optional"),
    ("pet_dialogs.py", "_dialog_failed", "except Exception: pass", "optional"),
    # 装 aboutToQuit 钩子失败 = 退出时那次清理缺席（可选能力降级，不影响用户可见结果）
    ("pet_dialogs.py", "__init__", "except Exception: pass", "optional"),
    # pet_plugin_host.py
    ("pet_plugin_host.py", "_norm_dir", "return os.path.normcase(text)", "fallback"),
    ("pet_plugin_host.py", "_fp_json", "text = repr(obj)", "fallback"),
    ("pet_plugin_host.py", "_plan_prompts", 'data = b""', "fallback"),
    ("pet_plugin_host.py", "_lib", "except Exception: return None", "probe"),
    ("pet_plugin_host.py", "list_installed", "读取插件目录失败", "reported"),
    # pet_plugin_index.py
    ("pet_plugin_index.py", "_file_url_to_path", "return tail", "fallback"),
    ("pet_plugin_index.py", "_accepts_limit", "except (TypeError, ValueError):", "probe"),
    ("pet_plugin_index.py", "format_size", 'return "-"', "fallback"),
    ("pet_plugin_index.py", "_ensure_dir", "return made", "cleanup"),
    # pet_tools.py
    ("pet_tools.py", "_args_preview", "text = str(args)", "fallback"),
]


_BARE_CONST_RETURN_RE = re.compile(r":\s*return\s*(False|True|None|-?[0-9.]+|\[\]|\{\}|\"\"|'')\s*$")
# 裸常量赋值（wait_s = 30 / pt = None / usage = 0.0）：同样是"安全默认值"，不是"上报给调用方"
_BARE_CONST_ASSIGN_RE = re.compile(r":\s*\w+\s*=\s*(False|True|None|-?[0-9.]+|\[\]|\{\}|\"\"|''|\(\))\s*$")


def classify(ent):
    """启发式理由码（--seed 用）。

    判据全部取自**审计工具已经算出来的档位理由 + try 体/handler 体里看得见的调用**；
    判据之间是"先具体后笼统"的短路顺序（每一条都对应一类看得见的证据）：

      1. handler 自己 return 了错误文案      → reported（调用方会显示）
      2. 写权限探针 / pet_log 自身 / 日志包装 → probe / self-logging
      3. 审计已判定"只删残留 / 只轮转"        → cleanup
      4. 审计判定"以返回值/哨兵上报"或"重试循环"：
           裸常量返回（return False/None/[]…）→ probe 或 fallback（那是安全假值，不是上报）
           其余（return 错误文案 / 循环后统一 raise）→ reported
      5. try 体里看得见的动作：关停/清理/探针/类型转换 → teardown / cleanup / probe / fallback
      6. 认不出的 → optional（可选能力降级），由人工在报告里逐条复核（报告列全表）

    注意：**不要**在最后兜一句"只要 return 就算 reported"——返回常量不是"上报给调用方"。
    """
    for f, fn, sub, reason in REVIEW_OVERRIDES:
        if ent["file"] == f and ent["func"] == fn and sub in ent["evidence"]:
            return reason
    why = ent.get("tier_reason", "")
    ev = ent["evidence"]
    try_ev = ent.get("try_evidence", "")
    probe_like = bool(_PROBE_RE.search(try_ev) or _PROBE_RE.search(ev))
    if re.search(r"return\s+[^\"'\n]*,\s*[\"']", ev) or re.search(r"return\s+[^\"'\n]*[\"'][^\"']*[\"']\s*%", ev):
        return "reported"          # return X, "错误文案" / return "…%s" % e → 调用方会显示
    if "写权限探针" in why:
        return "probe"
    if ent["file"] == "pet_log.py" or "显式豁免" in why:
        return "self-logging"
    if re.match(r"^except[^:]*:\s*pass$", ev) and re.search(
            r"(pet_log\.log_error|_log_error|self\._log|_log_msg|\blog\()", try_ev):
        return "self-logging"
    if re.search(r"(_excepthook|excepthook)", ent.get("func", "")):
        return "self-logging"
    if "仅删除孤儿/残留文件" in why or "轮转到它自己的备份名" in why:
        return "cleanup"
    if why.startswith("回滚里的回滚"):
        return "cleanup"
    if why.startswith("失败以返回值/哨兵上报调用方") or why.startswith("重试/轮询循环"):
        if _BARE_CONST_RETURN_RE.search(ev) or _BARE_CONST_ASSIGN_RE.search(ev):
            # 裸常量返回/赋值（return False / wait_s = 30）：审计算成"以返回值上报"，
            # 但它其实是"安全默认值"——调用方拿到的不是"错误"，而是"没有/别用"。
            return "probe" if probe_like else "fallback"
        return "reported"
    if re.search(r"=\s*False\s*,\s*[\"']", ev):
        return "reported"           # ok, msg = False, "读不出来：..." → 调用方会显示 msg
    if _TEARDOWN_RE.search(try_ev):
        return "teardown"
    if _CLEANUP_RE.search(try_ev):
        return "cleanup"
    if probe_like:
        return "probe"
    if re.search(r"(int|float|str|bool|round|max|min)\(", try_ev):
        return "fallback"
    if _BARE_CONST_RETURN_RE.search(ev):
        return "fallback"
    return "optional"


# ---------------- 白名单读写与判定 ----------------
def load_whitelist(path=None):
    path = path or WL_PATH
    with io.open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_whitelist(data, path=None):
    path = path or WL_PATH
    with io.open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1, sort_keys=False)
        fh.write("\n")


def is_delegated(ent):
    return os.path.basename(ent["file"]) in DELEGATED_FILES


# ---------------- 源码证据"是不是真的"（v2.7.0 · 代理 C·小账 d） ----------------
# 此前 check() 只判 evidence **非空**："有证据"与"证据是真的"是两件事——抄一句别处的话、
# 或者代码改过之后没重跑 --write，白名单照样绿。这里补一条判据：evidence 必须能在它自称
# 的那个文件里**原样找到**（两边空白都归一化，_flatten 截断留下的尾部 "..." 先剥掉）。
_EVIDENCE_SRC = {}


def _norm_ws(text):
    """空白归一（与 _flatten 同一口径）：换行/缩进折叠成单个空格。"""
    return re.sub(r"\s+", " ", text or "").strip()


def _evidence_haystack(rel, root=None):
    """某个文件"空白归一"后的全文；读不动 / 不存在 → None（查不了，不误报）。"""
    path = os.path.join(os.path.abspath(root or HERE), str(rel or ""))
    if path not in _EVIDENCE_SRC:
        try:
            with io.open(path, "r", encoding="utf-8-sig") as fh:
                _EVIDENCE_SRC[path] = _norm_ws(fh.read())
        except (OSError, UnicodeDecodeError):
            _EVIDENCE_SRC[path] = None
    return _EVIDENCE_SRC[path]


def evidence_in_source(rec, root=None):
    """白名单条目自称的源码证据能不能真的在它点名的文件里找到 → (verdict, detail)。

    verdict ∈ {"ok", "missing", "unknown"}：
      · ok      —— 找到了；
      · missing —— 文件读得到，但那段"源码证据"在文件里**根本不存在**（抄来的 / 过期没刷新）；
      · unknown —— 文件不存在或读不动（合成树、相对路径不对）：查不了，**不误报**。

    取舍（若大面积假红就退成提示级）：这条是**硬判据**，因为实测 307 条全部命中（证据就是
    扫描当时从该文件里取出来的原文，不存在"口径不同"的假红）；真要放开，把 check() 里那个
    分支改成只打印即可。刷新证据：python -B _dev/silent_except_whitelist.py --write
    （它保留已有理由码，只把 evidence / lines / count 换成当前源码的）。
    """
    rec = rec if isinstance(rec, dict) else {}
    rel = str(rec.get("file") or "")
    needle = _norm_ws(rec.get("evidence"))
    if not rel or not needle:
        return "unknown", "没有可核对的文件或证据原文"
    hay = _evidence_haystack(rel, root)
    if hay is None:
        return "unknown", "文件读不到：%s" % rel
    probe = needle[:-3].strip() if needle.endswith("...") else needle
    if probe and probe in hay:
        return "ok", ""
    return "missing", "证据原文在 %s 里找不到：%s" % (rel, needle[:70])


def check(entries, wl, root=None):
    """判定：返回问题列表（空＝绿）。**测试与 CLI 用的是同一份实现**。

    root：核对源码证据时的仓库根（缺省 = 本文件所在仓库）。条目里的 file 是**相对路径**。
    """
    problems = []
    known = {}
    for e in wl.get("entries", []):
        known[e.get("key", "")] = e
    for key, ent in sorted(entries.items()):
        if is_delegated(ent):
            continue
        w = known.get(key)
        if w is None:
            problems.append(
                "新增静默 except 未登记：%s:%s %s · %s\n"
                "    → 判定三选一：①补限流日志（pet_log.log_throttled）②改逻辑 ③确实该静默（登记理由）\n"
                "    → 登记命令：python -B _dev/silent_except_whitelist.py --write"
                % (ent["file"], ",".join(str(x) for x in ent["lines"]), ent["func"],
                   ent["evidence"]))
        elif int(w.get("count", 0)) != ent["count"]:
            problems.append("静默 except 条数变了：%s:%s %s（白名单 %d 条 / 实测 %d 条）"
                            % (ent["file"], ",".join(str(x) for x in ent["lines"]), ent["func"],
                               int(w.get("count", 0)), ent["count"]))
    for key, w in sorted(known.items()):
        if key not in entries:
            problems.append("白名单条目已失效（代码改了/删了，指纹对不上）：%s" % (key,))
            continue
        if w.get("reason") not in REASONS:
            problems.append("理由码非法：%s → %r" % (key, w.get("reason")))
            continue
        if w.get("reason") == "unreviewed":
            problems.append("白名单条目仍是 unreviewed（必须给出真理由）：%s · %s"
                            % (key, w.get("evidence", "")))
            continue
        if not str(w.get("evidence", "")).strip():
            problems.append("白名单条目缺源码证据：%s" % (key,))
            continue
        # v2.7.0（代理 C·小账 d）：证据**非空**还不够，得真的出现在它自称的那个文件里。
        verdict, detail = evidence_in_source(w, root)
        if verdict == "missing":
            problems.append(
                "白名单条目的源码证据对不上：%s（%s）\n"
                "    → 代码改过就重跑 python -B _dev/silent_except_whitelist.py --write 刷新证据；"
                "证据是抄来的请抄回它自己那段 handler" % (key, detail))
    return problems


def merge_write(entries, wl, seed=False):
    """合并写回：老键保留理由；新键登记成 unreviewed（--seed 时用启发式先填）。"""
    old = {e.get("key", ""): e for e in wl.get("entries", [])}
    out = []
    added = []
    for key, ent in sorted(entries.items()):
        if is_delegated(ent):
            continue
        prev = old.get(key)
        if prev and prev.get("reason") in REASONS and prev.get("reason") != "unreviewed":
            reason = prev["reason"]
        elif seed:
            reason = classify(ent)
        else:
            reason = "unreviewed"
        if prev is None:
            added.append((key, reason, ent))
        # 入库字段刻意精简（这是 *_summary.json：_dev/ 的入库白名单形状）：
        # try_evidence / tier_reason 只在扫描与分类时用，需要时可现场重算，不落盘。
        out.append(dict(key=key, file=ent["file"], func=ent["func"], shape=ent["shape"],
                        count=ent["count"], tier=ent["tier"], reason=reason,
                        why=REASONS.get(reason, ""),
                        evidence=ent["evidence"], lines=ent["lines"]))
    dropped = [k for k in old if k not in entries]
    data = dict(schema=WL_SCHEMA,
                note=("D7-B 静默 except 白名单（数据）。判定逻辑在 _dev/silent_except_whitelist.py，"
                      "测试在 tests/test_silent_except_v252.py。改代码后先跑 --check。"),
                reasons=REASONS,
                delegated_files=list(DELEGATED_FILES),
                entries=out)
    return data, added, dropped


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="D7-B 静默 except 白名单（判定器 / 登记器）")
    ap.add_argument("--check", action="store_true", help="有问题则退出码 1")
    ap.add_argument("--write", action="store_true", help="把当前扫描写回白名单")
    ap.add_argument("--seed", action="store_true", help="首次生成：新键用启发式填理由")
    ap.add_argument("--stats", action="store_true", help="按理由码统计")
    args = ap.parse_args(argv)
    entries, findings = scan_silent()
    prod = [f for f in findings if not f["nonprod"]]
    a = [f for f in prod if f["tier"] == "A"]
    print("扫描：生产路径静默 except 条目 %d 个（领地内 %d / 领地外 %d）；A 档 %d 条"
          % (len(entries),
             len([e for e in entries.values() if not is_delegated(e)]),
             len([e for e in entries.values() if is_delegated(e)]), len(a)))
    if args.write:
        wl = load_whitelist() if os.path.exists(WL_PATH) else {"entries": []}
        data, added, dropped = merge_write(entries, wl, seed=args.seed)
        save_whitelist(data)
        print("已写 %s：条目 %d（新增 %d / 失效丢弃 %d）"
              % (os.path.relpath(WL_PATH, HERE), len(data["entries"]), len(added), len(dropped)))
        for key, reason, ent in added:
            print("  + [%s] %s:%s %s · %s" % (reason, ent["file"],
                                              ",".join(str(x) for x in ent["lines"]),
                                              ent["func"], ent["evidence"]))
        for k in dropped:
            print("  - 失效：%s" % (k,))
        return 0
    wl = load_whitelist()
    problems = check(entries, wl)
    if args.stats:
        import collections
        c = collections.Counter(e["reason"] for e in wl["entries"])
        for k, v in c.most_common():
            print("%4d  %s" % (v, k))
    if a:
        for f in a:
            print("A 档（数据丢失）：%s:%d %s · %s" % (f["file"], f["line"], f["func"], f["reason"]))
    if problems:
        print("\n判定问题 %d 条：" % len(problems))
        for p in problems:
            print("  * %s" % p)
        return 1 if args.check else 0
    print("判定通过：每个静默 except 都有归属（白名单条目 %d）" % len(wl.get("entries", [])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
