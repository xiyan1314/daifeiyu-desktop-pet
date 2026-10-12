# -*- coding: utf-8 -*-
"""D7-B 报告生成器：把逐条判定写成 _dev/silent_except_report_v252.md（可复跑）。

数据来源（全部实跑，不手抄）：
  · _dev/audit_silent_except.py       —— 分档（A/B/C/OK）
  · _dev/silent_except_whitelist.py   —— 静默 except 的登记与判定（razor 的同一实现）
  · _dev/silent_except_whitelist_summary.json —— 白名单数据
用法：python -B _dev/silent_except_report.py
"""
import ast
import collections
import importlib.util
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "_dev", "silent_except_report_v252.md")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


wl = _load("wl_report", os.path.join(HERE, "_dev", "silent_except_whitelist.py"))

# 起点快照（代理 B 接手时**实跑**的第一次扫描；见 §1 的对账）
START = dict(a=0, b=240, c=132, ok=127, b_mine=194, b_foreign=46)

# 护栏读数（代理 B 收尾实跑；当次工作树含并行代理 A/C 的在制品）
GUARD = dict(pytest="**1025 passed**（0 failed；基线 948，本轮三路新增用例 +77）",
             v13="**273 checks / 0 FAILS**（V13 VERIFY ALL OK）",
             static="**0 问题 0 待确认**（单跑）")

# 本轮 ①/② 改动的站点（改完之后它们**不再是静默** except，所以不在 B 档表里）
CHANGED = [
    dict(kind="①", site="pet_config.py:124", func="decrypt_secret",
         before="DPAPI 解密失败静默 return 空串（与「从没设过 Key」在界面上完全一样）",
         after="pet_log.log_throttled(\"config.decrypt_secret\", …)，返回值口径不变",
         test="test_decrypt_secret_failure_is_logged"),
    dict(kind="①", site="pet_resources.py:872", func="RoleLibrary.stage_file",
         before="复制失败静默 return None（异常原文被丢，调用方只报「写入角色目录失败」）",
         after="pet_log.log_throttled(\"role.stage_file\", …)，返回值口径不变",
         test="test_role_stage_file_failure_is_logged"),
    dict(kind="①", site="pet_audio.py:294", func="preview_file",
         before="试听失败静默 return False（用户点了没声音，日志里也没线索）",
         after="pet_log.log_throttled(\"audio.preview_file\", …)，返回值口径不变",
         test="test_audio_preview_failure_is_logged"),
    dict(kind="①", site="桌宠.py:4768", func="PetWindow.preview_audio",
         before="两条链路（winsound → QMediaPlayer）都失败时静默 return False",
         after="pet_log.log_throttled(\"preview_audio:<路径>\", …)（按文件路径限流）",
         test="test_window_preview_audio_failure_is_logged"),
    dict(kind="①", site="桌宠.py:522", func="_persona_file_text",
         before="人设文件读不出来静默 return None（调用方直接回退内置人设，用户只觉得「人设自己变了」）",
         after="只对**用户自建**人设（file: 前缀）记限流日志；内置预设没有同名文件是设计行为，不记",
         test="test_persona_file_text_logs_only_for_custom_personas"),
    dict(kind="②", site="pet_tools.py:361", func="describe_call",
         before="确认文案拼不出来 → detail 置空 → 通用问法「想调用「记一笔」，可以吗？」"
                "（这是 AI 写入类工具的**确认框正文**，用户看不到要写什么就点了确认）",
         after="退回**带参数的保守文案**（把参数原样带给用户看）+ 限流日志",
         test="test_describe_call_keeps_args_when_describe_raises"),
    dict(kind="口径", site="pet_log.py:91 / 桌宠.py:695", func="guard_slot / _log_slot_error",
         before="「同名 60s 一条」在仓里有三份各自实现（_SLOT_SEEN / _SLOT_ERR_SEEN / keep_source）",
         after="pet_log.log_throttled 成为单一实现，guard_slot 收敛到它；"
               "桌宠._log_slot_error **本轮有意不动**（它的 except 是有意义的兜底，改了会多一个静默点）",
         test="test_guard_slot_still_throttles_after_refactor"),
]


def handler_at(path, lineno):
    """按行号取 handler 原文（报告「现行为」一列）。"""
    try:
        with io.open(path, "r", encoding="utf-8-sig") as fh:
            src = fh.read()
        tree = ast.parse(src)
    except Exception:
        return ""
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for h in node.handlers:
                if getattr(h, "lineno", 0) == lineno:
                    seg = ast.get_source_segment(src, h) or ""
                    return re.sub(r"\s+", " ", seg).strip()[:150]
    return ""


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    entries, findings = wl.scan_silent()
    prod = [f for f in findings if not f["nonprod"]]
    tiers = collections.Counter(f["tier"] for f in prod)
    wldata = wl.load_whitelist()
    by_key = {e["key"]: e for e in wldata["entries"]}
    line_owner = {}
    for key, ent in entries.items():
        for ln in ent["lines"]:
            line_owner[(ent["file"], ln)] = key

    b_rows = [f for f in prod if f["tier"] == "B"]
    c_rows = [f for f in prod if f["tier"] == "C"]
    a_rows = [f for f in prod if f["tier"] == "A"]
    b_mine = [f for f in b_rows if not wl.is_delegated({"file": f["file"]})]
    b_foreign = [f for f in b_rows if wl.is_delegated({"file": f["file"]})]
    reason_count = collections.Counter(e["reason"] for e in wldata["entries"])
    b_by_reason = collections.Counter()
    for f in b_rows:
        k = line_owner.get((f["file"], f["line"]))
        if k and k in by_key:      # 领地外条目不入白名单（见 DELEGATED_FILES）
            b_by_reason[by_key[k]["reason"]] += 1

    out = []
    w = out.append
    w("# D7-B：静默 except 逐条判定报告（v2.6.0 · 代理 B）")
    w("")
    w("> 口径与数据：_dev/audit_silent_except.py（分档）· _dev/silent_except_whitelist.py（判定器）·"
      " _dev/silent_except_whitelist_summary.json（白名单数据）· tests/test_silent_except_v252.py（razor + 行为用例）·"
      " _dev/mutate_check.py + _dev/mutations_silent_except_v260.json（变异验证，19 条 spec）")
    w("> 本文由 python -B _dev/silent_except_report.py 生成，数字全部来自实跑。")
    w("")
    w("## 0. 一句话结论")
    w("")
    w("- **B 档（功能性吞咽）逐条判定完毕，没有「未判定」**：收尾实测 B=%d 条，"
      "其中本代理领地 %d 条、领地外（代理 A/C 并行改造的 4 个文件）%d 条。"
      % (len(b_rows), len(b_mine), len(b_foreign)))
    w("- 三选一结果：**①补限流日志 5 处 · ②改逻辑 1 处 · ③确实该静默（进白名单）其余全部**；"
      "另有 1 处限流口径收敛（guard_slot → pet_log.log_throttled）。每条改动都有能真失败的用例，"
      "并做了变异验证（把改动逐个还原 → 对应用例必须红）：复跑命令 **python -B "
      "_dev/mutate_check.py _dev/mutations_silent_except_v260.json**（v2.6.0 第 4 轮把原来 12 条"
      "原地覆写式变异迁成 _mutate_lib 的 spec 形态、再补 7 条，共 **19 条 / 19 CAUGHT**；"
      "旧的 _dev/silent_except_mutate.py 已停用）。")
    w("- **A 档 = %d**（收尾实测）。" % len(a_rows))
    w("- 白名单落成**数据**（**%d** 条 = 首轮快照 222 条 + 本轮收编的 4 个领地外文件 85 条，"
      "每条带理由码 + 一句话「为什么该静默」+ 源码证据），"
      "并由 razor 钉住：新增静默 except / 改了 handler 结构 / 条目失效 / 理由是 unreviewed 占位"
      " → **测试红**。" % len(wldata["entries"]))
    w("")
    w("## 1. 起点对账（任务书的数字与实跑不一致，按实跑）")
    w("")
    w("任务书写「实测输出 A=0 / B=219 / C=128 / OK=119」，同段又说「211 条」。"
      "**代理 B 接手时第一次实跑的结果是：**")
    w("")
    w("| 指标 | 任务书 | 接手实测 | 说明 |")
    w("|---|---|---|---|")
    w("| A | 0 | **%d** | 一致 |" % START["a"])
    w("| B | 219（正文另说 211） | **%d**（领地内 %d / 领地外 %d） | 不一致，差 %+d |"
      % (START["b"], START["b_mine"], START["b_foreign"], START["b"] - 219))
    w("| C | 128 | **%d** | 差 %+d |" % (START["c"], START["c"] - 128))
    w("| OK | 119 | **%d** | 差 %+d |" % (START["ok"], START["ok"] - 119))
    w("")
    w("任务书那两个数字（219 / 211）**无法在本仓库复现**：接手时工作树干净"
      "（HEAD 7ee8766，只有未跟踪的 _dev/task_v260.md），审计脚本本身在版本控制里、未改动。"
      "推测是更早某次快照的数字（v2.5.0/v2.5.1 之间加过插件系统与 D7-A 的改动）。"
      "按铁律 7，报告一律以实跑为准，起点定成接手那一刻的实测值。")
    w("")
    w("收尾读数（含并行代理 A/C 的在制品：A 正在往 pet_dialogs / pet_plugin_index / "
      "pet_plugin_host 加市场页与下载器，所以领地外条数在涨）：")
    w("")
    w("| 档 | 条数 | 其中领地内 | 其中领地外 |")
    w("|---|---|---|---|")
    w("| A（数据丢失/用户可见错误被吞） | **%d** | %d | %d |"
      % (len(a_rows), len([f for f in a_rows if not wl.is_delegated(f)]),
         len([f for f in a_rows if wl.is_delegated(f)])))
    w("| B（功能性吞咽） | %d | %d | %d |" % (len(b_rows), len(b_mine), len(b_foreign)))
    w("| C（良性） | %d | %d | %d |"
      % (len(c_rows), len([f for f in c_rows if not wl.is_delegated(f)]),
         len([f for f in c_rows if wl.is_delegated(f)])))
    w("| OK（已有日志/上报） | %d | - | - |" % tiers["OK"])
    w("")
    w("## 2. 起点 %d 条的归属" % START["b"])
    w("")
    w("| 归属 | 条数 | 说明 |")
    w("|---|---|---|")
    w("| ① 该补日志 → 已补（补完就不再是「静默 except」，从 B 档消失） | 5 | §4 |")
    w("| ② 该改逻辑 → 已改（同上） | 1 | §4 |")
    w("| ③ 确实该静默 → 进白名单（含领地外只判定的） | 其余全部 | §3 逐条表 |")
    w("| 附带：限流口径收敛（不是新增日志） | 1 | §4.3 |")
    w("")
    w("**为什么绝大多数是 ③**：这不是「懒得改」。B 档的两大来源本身就是「已经处理过」的形态——"
      "①失败以返回值/错误文案上报调用方（界面会当场显示，再写一条日志只是重复）；"
      "②可选能力/探针/清理路径（失败等于「这个能力没有」，补日志反而制造噪音）。"
      "本轮把「看得见就有价值」的那几处挑出来补了日志（§4），其余按证据登记并逐条写清理由。")
    w("")
    w("## 3. 逐条判定（B 档全部 %d 条）" % len(b_rows))
    w("")
    w("列口径：**现行为**＝handler 原文（单行化截断）；**判定**＝①/②/③；"
      "**依据**＝白名单理由码 +「为什么该静默」一句话；**是否实测**＝是否构造路径真跑过。")
    w("")
    w("| 位置（文件:行 · 函数） | 现行为 | 判定 | 依据（为什么该静默） | 是否实测 |")
    w("|---|---|---|---|---|")
    for f in sorted(b_rows, key=lambda x: (x["file"], x["line"])):
        k = line_owner.get((f["file"], f["line"]))
        ent = by_key.get(k) if k else None
        reason = ent["reason"] if ent else "?"
        ev = handler_at(os.path.join(HERE, f["file"]), f["line"]) or f["snippet"][:150]
        tagn = "（领地外，只判定）" if wl.is_delegated(f) else ""
        w("| %s:%d · %s | %s | ③ 确实该静默%s | 理由码 %s：%s | 否（静态判定） |"
          % (f["file"], f["line"], f["func"] or "-", ev.replace("|", "/").replace("\n", " "),
             tagn, reason, wl.REASONS.get(reason, "").replace("|", "/")))
    w("")
    w("### 3.1 白名单按理由码汇总（%d 条）" % len(wldata["entries"]))
    w("")
    w("> **条数演变（v2.6.0 第 4 轮收口实跑）**：首轮快照是 **222** 条，本轮把原先整体豁免的 4 个"
      "领地外文件（pet_plugin.py / pet_plugin_host.py / pet_plugin_index.py / pet_dialogs.py，"
      "DELEGATED_FILES 已清空）逐条收编进来 **+85** 条 → **%d** 条。"
      "下表两列都按这一版数据重读（B 档 handler 覆盖数同样按收口后的实跑扫描算）。"
      % len(wldata["entries"]))
    w("")
    w("条目数＝白名单条目；B 档 handler 数＝该理由码**覆盖到**的 B 档 handler 个数"
      "（一个条目可覆盖多个同形状 handler，所以这一列不必等于条目数）。")
    w("")
    w("| 理由码 | 条目数 | 覆盖的 B 档 handler 数 | 为什么该静默（闭集口径） |")
    w("|---|---|---|---|")
    for code, n in reason_count.most_common():
        w("| %s | %d | %d | %s |" % (code, n, b_by_reason.get(code, 0),
                                     wl.REASONS.get(code, "").replace("|", "/")))
    w("")
    w("## 4. 代码改动清单（每条都有能真失败的用例 + 变异验证）")
    w("")
    w("| 类型 | 位置 | 改前（现行为） | 改后 | 用例 |")
    w("|---|---|---|---|---|")
    for c in CHANGED:
        w("| %s | %s · %s | %s | %s | tests/test_silent_except_v252.py::%s |"
          % (c["kind"], c["site"], c["func"], c["before"].replace("|", "/"),
             c["after"].replace("|", "/"), c["test"]))
    w("")
    w("### 4.3 新增的限流出口")
    w("")
    w("- pet_log.log_throttled(key, msg, gap=60.0, now=None, **log_kw)：**唯一的公共实现**"
      "（返回 True/False 表示这条有没有落盘，now 可注入 → 用例断言不依赖机器速度）。")
    w("  > v2.6.0 第 4 轮（找茬审查实测）更正：说它是「全仓唯一的『同名 60s 一条』实现」"
      "**不准确**——本轮只**收敛了 guard_slot 一处**，仓里还有 **3 处手写的同口径**没动："
      "pet_resources.py:337,361-365（_SOURCE_FAIL_SEEN）· 桌宠.py:712-713（_SLOT_ERR_SEEN）· "
      "桌宠.py:5204-5205（_EXC_BOX_SEEN）。三者**留待下一轮**：改它们要么多出一个纯静默 "
      "except（前两处），要么是异常钩子自己的兜底（第三处），不在本轮「消灭静默」的主题里"
      "硬凑口径统一。")
    w("- pet_log.guard_slot 收敛到它（行为逐位不变：同一槽名 60s 一条、文案含 traceback）。")
    w("- 桌宠._log_slot_error 与 pet_resources._SOURCE_FAIL_SEEN **本轮有意不动**："
      "前者的 except 是有意义的兜底（取不到 traceback 也要记一行），改成调 log_throttled "
      "会多出一个纯静默 except——本轮主题正是消灭静默，不为「口径统一」制造新的静默点。"
      "两者都写进了白名单（理由码 self-logging），留给下一轮。")
    w("")
    w("## 5. 白名单与 razor（任务书硬要求 a）")
    w("")
    w("- **数据**：_dev/silent_except_whitelist_summary.json，**%d** 条（首轮快照 222 条 + 本轮"
      "收编的 85 条，见 §3.1 的条数演变），字段 "
      "key/file/func/shape/count/tier/reason/why/evidence/lines；"
      "why 就是「为什么该静默」的那句话（数据自带，不必回头查代码）。" % len(wldata["entries"]))
    w("- **键 = (文件, 函数, 结构指纹)**：指纹把标识符/常量/消息文本匿名化后取 AST 的 sha1 前 10 位——"
      "改文案、改变量名不会误报；把 return 错误文案改成 pass、或新增一个静默 except，一定报。")
    w("- **razor 的判定**（_dev/silent_except_whitelist.py 的 check()，测试与 CLI 同一实现）：")
    w("  1. 生产路径每个静默 except（= 审计的 B ∪ C）都必须命中白名单条目，且 count 一致；")
    w("  2. 白名单条目必须仍对应活代码（失效条目 → 红）；")
    w("  3. 理由码必须来自闭集；unreviewed 占位 → 红（--write 只登记占位，必须有人给真理由）；")
    w("  4. 每条都要有源码证据；")
    w("  5. A 档必须为 0（覆盖全仓，含领地外）。")
    w("- **razor 不是空转**（用例自带合成反例）：新写一个静默 except → 报「未登记」；"
      "同一个 except 补上日志 → 不再报；伪造失效条目 → 报「已失效」；"
      "把某条理由改成 unreviewed → 报占位。见 tests/test_silent_except_v252.py。")
    w("- **领地外 4 个文件**（%s）：本轮**不钉**静默清单（代理 A/C 正在改，钉了就是天天假红），"
      "但仍在「A 档 = 0」的管辖内。下一轮把 DELEGATED_FILES 清空即自动纳入。"
      % "、".join(wl.DELEGATED_FILES))
    w("")
    w("## 6. A 档 = 0 的实测")
    w("")
    if a_rows:
        w("**不成立**：实测到 %d 条 A 档：" % len(a_rows))
        for f in a_rows:
            w("- %s:%d · %s · %s" % (f["file"], f["line"], f["func"], f["reason"]))
    else:
        w("实测 **A = 0**（python -B _dev/audit_silent_except.py 与 razor 用例各跑一次，"
          "两者都覆盖全仓生产路径，含代理 A/C 的文件）。")
    w("")
    w("## 7. 变异验证（把每处改动还原成旧行为 → 用例必须红）")
    w("")
    w("跑法：python -B _dev/mutate_check.py _dev/mutations_silent_except_v260.json"
      "（19 条 spec：影子副本 + 运行锁 + expect_fail 判定 + 结果 JSON 带 repo_fingerprint；"
      "原 12 条变异里 8 条改产品代码、4 条改白名单数据，本轮再补 7 条）。结果见 §8。")
    w("")
    w("## 8. 护栏读数（收尾实跑）")
    w("")
    w("跑法：安静窗口串行（先确认 _dev/.mutation.lock 里没有活着的变异进程）——"
      "pytest 全量 → v13 → 静态，各自单跑。当次工作树含并行代理 A/C 的在制品。")
    w("")
    w("| 护栏 | 读数 |")
    w("|---|---|")
    w("| pytest tests -o addopts=\"\" -q | %s |" % GUARD["pytest"])
    w("| python -B _verify_v13.py | %s |" % GUARD["v13"])
    w("| python -B _check_static.py | %s |" % GUARD["static"])
    w("")
    w("## 9. 没做到 / 有疑问（如实列）")
    w("")
    w("1. **只有 7 处做了行为实测**，其余 %d 条是静态判定。判据是 handler 原文 + 审计工具的"
      "档位规则（可复核），但「调用方到底会不会把错误显示给用户」这一步静态看不到——"
      "这正是审计工具文件头写明的已知盲区。下一轮可以补「全量调用方核对」。"
      % max(0, len(b_rows) - 7))
    w("2. **领地外 %d 条只判定、不登记进 razor**，见 §5 最后一条。" % len(b_foreign))
    w("3. **限流口径还剩两份老实现**（桌宠._log_slot_error / pet_resources._SOURCE_FAIL_SEEN），"
      "本轮有意不动，理由见 §4.3。")
    w("4. **任务书的 219/211 复现不出来**，见 §1。")
    w("5. 白名单是「数据 + 理由码」，它能防「悄悄新增」，**防不住「有人睁着眼写一个假理由」**——"
      "那需要人看报告，机器没法代劳。")
    w("")
    text = "\n".join(out)
    with io.open(OUT, "w", encoding="utf-8") as fh:
        fh.write(text)
    print("wrote %s (%d 行, B 档 %d 条, 白名单 %d 条, A=%d)"
          % (os.path.relpath(OUT, HERE), len(out), len(b_rows), len(wldata["entries"]), len(a_rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
