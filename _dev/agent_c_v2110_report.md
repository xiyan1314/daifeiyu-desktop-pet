# v2.11.0 第 9 轮 · 代理 C 完工报告（验证欠账 V1~V7）

> **领地**：`_dev/**` 与测试文件里"断言强度 / 体检覆盖"的改动。
> **产品代码一行未动**（V7 需要产品改动 → 按领地规矩**递交**，精确补丁见 `7）。
> **结论一句话**：V1 让"pinned 用例体被清空"这种静默失效第一次能被抓住（**能判过期的变异 7/489 → 489/489**）；
> V2/V3 各收紧一处判定口径；V4 复核"已满足"；V5 三处文档过期**已更正**；
> V6 两条挂了两轮的账**结案**（① 离线实测、② 待验对象已消失）；V7 未动产品代码。

## 0. 改动面（逐文件）

| 文件 | 动作 | 说明 |
|---|---|---|
| `_dev/_mutate_lib.py` | 改 | V1：`pinned_ast_map / pin_digest / resolve_pin / stale_pinned`（+ AST 缓存，按 mtime/size 失效）；V2：`error_phase / split_teardown_errors`；V3：`failed_nodeids / errored_nodeids` 返回**整条 nodeid**；`results_payload` 增第 7 项 `errors_teardown` |
| `_dev/check_pinned_ast.py` | 新增 | 比对工具：默认查"盘上证据 vs 当前树"；`--probe` 出改前/改后覆盖数；`--selftest` 工具的能真失败自检 |
| `_dev/mutate_check.py` | 改 | V1：`spec_pinned_ast` + `evidence_extra`（回写 `pinned_ast`）；V2：judge 接 `phases`；V3：`_split / _same_file / _failed_hit` 带文件路径比对 |
| `_dev/mutate_export_slice.py` · `_dev/mutate_startup_defer.py` | 改 | V1：两份旧形态 pytest 驱动各记一条 `pinned_ast`（**整文件**粒度） |
| `_dev/probe_autoscroll_v2110.py` | 新增 | V6 结案探针：`setCurrentRow` 到底会不会滚进视口（离线可验） |
| `_dev/mutations_agent_c_v2110.json` | 新增 | 6 条变异，钉 V1/V2/V3 的新判据；实测 **6/6 CAUGHT** |
| `_dev/mutations_agent_c_v2100.json` | 改 | **重锚 M-C2100-R5-01**（我的 V2/V3 改了 judge 那行，旧锚点 0 次）→ 复跑 **9/9 CAUGHT** |
| `tests/test_pinned_ast_v2110.py` | 新增 | 15 条：摘要该报的报、不该报的不报、参数化/类方法/整文件/用例被删、recording 端到端、CLI 集成、工具自检、语料覆盖 |
| `tests/test_mutate_harness_v244.py` | 改 | 适配"整条 nodeid"；新增 V2/V3 共 8 条（含**真跑 pytest** 的参数化相位样本） |
| `_dev/README.md` | 改 | 新增 V1/V2/V3 三节 + 工具表两行 + 探针表一行 + spec 表一行；更正两处过期数字 |
| `_dev/audit_tautology_asserts_v2100.py` | 改 | V5：头部"全仓 --strict → exit 1"更正为 exit 0（实测） |
| `_dev/audit_feedback_v270.md` · `_dev/audit_behavior_assets_v290.md` · `_dev/plan_v270_rounds.md` | 改 | V6：#21 两条挂账结案（含"将来怎么验"） |

## 1. V1【P2】pinned nodeid 的**用例体 AST 摘要**

**洞（实测的反例，本轮在影子里又复现了一次）**：`check_mutation_nodeids.py` 只问"def 还在不在"。
把 `tests/test_io_v231.py::test_path_lock_merges_case_variants` 的**用例体清空**（17 行 → `pass`，nodeid 一个字不动）：

| 检查 | 改动前 | 清空 pinned 用例体后 |
|---|---|---|
| nodeid 体检 | rc=0 | **rc=0**（def 还在） |
| 文件指纹（发布门 `mutation_evidence_notes`） | — | **零提示**（`tests/test_io_v231.py` 不在 28 个键里；实测"点名它的提示 0 条"） |
| **pinned 用例体检（本轮新增）** | rc=0 | **rc=1**：`tests/test_io_v231.py::test_path_lock_merges_case_variants: e89fc5ada3de→1a97cbc6366b ← M-C2100-R4-02` |

**修法**：证据 JSON 多记一段 `pinned_ast` = {pinned nodeid: 用例体 AST 摘要}
（`mutate_check.evidence_extra` 与两份旧形态 pytest 驱动在**真实仓库**上算好写进 `results`）。
摘要 = 该 def 的 AST（**含形参与装饰器**、**不含 docstring**）的 sha256 前 12 位；
只给文件的旧形态（`tests/x.py`）摘整份模块（模块级与各函数 docstring 同样不算）。

**改前 / 改后：多少条变异能被判过期**（`python -B _dev/check_pinned_ast.py --probe` 原文）：

| 判过期的手段 | 能判过期的变异 |
|---|---|
| **改前**：文件指纹（26 个产品键 + 2 个承载锚点的测试文件） | **7 / 489** |
| **改后**：pinned 用例体 AST 摘要 | **489 / 489**（不可解析 0 条） |

（另：两份旧形态 pytest 驱动 13 条钉的是**整文件**，改后同样可判过期。
点名的测试文件实测 **39 个**，其中**只有 2 个**在指纹清单内；pinned nodeid 唯一 **400 条**，
**391 条在指纹外**——任务书写的是"38 文件 / 397 条"，我实测是 **37 文件 / 391 条**
（口径：`mutations[].tests/expect_fail` 去重；"39 个文件"这半边与任务书一致）。）

**精度（它为什么不用整文件 sha256）**：注释 / 缩进 / 换行 / docstring 都不入摘要 → 重排版、改说明不报过期；
同文件里**别的**用例改动也不报。**代价（如实写）**：同文件的 **fixture / 辅助函数**被掏空而用例体不动时，
本机制不出声（那是"整文件"粒度的事；本仓变异语料里目前没有这种形态）。

**落地状态（别误读）**：⚠ **盘上现有 36 份证据还没有 `pinned_ast` 段**（只有 3 份：`c_v2100` / `c_v2110` /
`b_v2110` —— 后两份是最近跑过的）。**定版整批复跑（铁律 5）会把它们带上**；在那之前它们只受文件指纹保护。
工具会把"还没有 pinned_ast 段的证据"**点名**（不许静默）。

**回归**：`tests/test_pinned_ast_v2110.py` **15 条** + `check_pinned_ast.py --selftest`（该报的报、不该报的不报）。
**牙齿**：`_dev/mutations_agent_c_v2110.json` 的 `M-C2110-V1-01/02/03/04`（摘要失明 / 解析器拒 nodeid /
比对器永不报 / 证据不记 `pinned_ast`），实测 **4/4 CAUGHT**。
⚠ 第一遍 `M-C2110-V1-02` 判 **WRONG TEST**：我那条 recording 用例拿 `pinned_ast_map` 跟**自己做比较**，
解析器被改坏时两边都是 `{}`、断言照样绿（**自己骗自己**）。已改成钉具体形态 + 端到端"用例体改了 → 证据里的值必须变"，复跑 CAUGHT。

**用法**：
`python -B _dev/check_pinned_ast.py`（查盘上证据，rc 0/1，可进定版流水）· `--probe`（改前/改后）· `--selftest`（自检）。

## 2. V2【P2】teardown 相位不计检出

**前提（任务书要求先确认）：相位解析对参数化 nodeid 可靠吗？——可靠，已用真 pytest 钉住。**
pytest 的 ERRORS 段小标题形如 `ERROR at teardown of test_x[参数]`（`_pytest/terminal.py:1235` 实测源码：
`msg = f"ERROR at {rep.when} of {msg}"`），取的是 `report.head_line` = 用例域名（**带 `[参数]`**）；
类方法在小标题里写作 `TestX.test_y`（点号）、`errored_nodeids` 摘出来是 `TestX::test_y`（双冒号）——
`_mutate_lib.error_phase` 两种形态都归一。回归用例
`tests/test_mutate_harness_v244.py::test_error_phases_reads_a_real_parameterized_error_and_a_teardown_error`
真跑一个 pytest（夹具在 setup 期炸的**两个参数实例** + 另一个用例在 teardown 期炸），逐条对相位。

**收紧**：`judge` 的"没通过 = FAILED + ERROR"改成 **ERROR 只认 setup/call 期**（`split_teardown_errors`）——
teardown 期 error 的汇总行是 `3 passed, 1 error`，**error 的那条用例在 passed 里**（用例体已经跑完）。
**失败方向是安全的**：相位查不出来（输出被截断 / 老调用方不传 `phases`）时**一律保留** → 与旧口径逐字一致。
**证据面**：被排除的行另存 `results.items[].errors_teardown`（口径改了就要看得见）。
**回归**：harness 里 4 条（teardown 不算检出 / setup 仍算 / 相位未知保留 / 类方法点号相位）+ 真 pytest 1 条。
**牙齿**：`M-C2110-V2-01`（把 teardown 照收）CAUGHT。

## 3. V3【P2】`_short()` 按基名跨文件顶替

**反例**：spec 写 `tests/test_a.py::test_x`，红的却是 `tests/test_b.py::test_x` → 旧口径按基名比 → **CAUGHT**（假的）。
**修法**：`_split()` 保留文件部分，`_failed_hit` 带文件比（`_same_file` 按**路径分量尾部**比，
兜住"pytest rootdir 不在仓根、nodeid 少一层前缀"的形态；`a/test_x.py` 与 `b/test_x.py` 仍是两条用例）。
**只有** spec 写裸用例名（老 spec 形态）或 pytest 输出里没有文件前缀（离线样本）时才退回按基名比。
**证据形态跟着变**：`failed_nodeids` / `errored_nodeids` 现在返回**整条 nodeid**（`tests/x.py::test_y[参数]`）——
`results.items[].failed / .errors` 里的形态随之变化（历史条目保持旧形态，不改）。
**已知边界（先写下来）**：同一文件里**两个类**各有一个同名方法时仍会顶替；本仓 spec 实测 **0 条**类前缀 nodeid。
**回归**：harness 里 3 条（跨文件拒绝 / 同文件与 rootdir 前缀接受 / 不同目录同名拒绝）。
**牙齿**：`M-C2110-V3-01`（退回基名比对）CAUGHT。

## 4. V4【P3】R4 工具 docstring 的边界 —— **已满足，本轮只做复核**

任务书要求写进去的两段，**上一轮已经写在** `_dev/audit_tautology_asserts_v2100.py` 的 docstring 里
（`:29-36` 原文）："本工具**只走函数体**——不下钻 `match` 的 case 体、不看模块级与类体级的断言…"，
以及"质量审造了 **21 种**形态，本工具**抓 11 漏 10**；但…**0 条真恒真**。**结论：窄，但无实际漏检**"。
**实现与措辞一致**（本轮读码复核）：`scan_source` 只以 `FunctionDef/AsyncFunctionDef` 为入口调 `_walk_body`，
后者只下钻 `If/While/Try/For/With`——**`Match` 与类体/模块级断言不进**。
`_dev/README.md` 的同一处边界也已在（工具表那一行的"边界"半句）。**本轮无改动**。

## 5. V5【P3】三处过期文档 —— 已更正

| # | 位置 | 原文（过期） | 更正后 | 依据 |
|---|---|---|---|---|
| 1 | `_dev/audit_tautology_asserts_v2100.py` 头部（用法两行） | "全仓：会报 3 条（全在冻结副本）→ **exit 1**" | "**列出** 3 条（全在冻结副本）但 **exit 0** —— `--strict` 只看活树" | 实测 `python -B _dev/audit_tautology_asserts_v2100.py . --strict` → **rc=0**（自打印 `--strict 只看活树的 恒真/恒假/死块：0 条`）。原句与紧接着的"`--strict` 只看活树"**自相矛盾** |
| 2 | `_dev/README.md` 工具表（原 `:324`） | "全仓实测 **378 个 .py 命中 6 条**、产品代码 0 条" | "全仓实测（2026-10-16 v2.11.0 复核）**385 个 .py 命中 3 条（全在冻结副本）**、活树/产品代码 0 条" | 实测（.py 总数会随新增文件漂，**看命中数**） |
| 3 | `_dev/README.md` `:173` | 同批 R4-01/02/03/04 …（**7/7 CAUGHT**） | 该 spec 现共 **9 条** → **9/9 CAUGHT** | 本轮复跑 `mutations_agent_c_v2100.json` = **9/9 CAUGHT** |

（另外顺手把 `零` 那段的"380 个 .py"也标了复核日期与复跑命令——同一个数字的第二次过期。）

## 6. V6【P3】#21 两条需真 GUI 的检查 —— **结案**

* **① `QListWidget.setCurrentRow` 自动滚动：已实测，而且**离线可验**。**
  探针 `python -B _dev/probe_autoscroll_v2110.py`（offscreen）实测：`setCurrentRow(第 25 行)` →
  scrollbar `0→15`、目标行矩形 `(0,120,204,12)` 与视口 `(0,0,204,138)` 相交 → **会滚**；
  `setCurrentRow(-1)` 不滚（对照）。与上一轮 `test_new_line_scrolls_into_view` 的结论一致。
  **"需要真 GUI"这个定性是错的**：offscreen 下 Qt 的几何与滚动状态就是真值。
  产品侧另有结构性消解（四处 `_select_*` 显式 `scrollToItem`）。
* **② 静态 `QInputDialog` 在 Windows 前台锁下是否真会被拦：不可离线验证 —— 但待验证的对象已消失。**
  实测全仓**静态调用点 0 处**：`QInputDialog.getText(` / `.getItem(` 在产品代码里已经没有
  （只剩两处用例在**断言它不存在**：`tests/test_dialogs_behavior_v290.py:420-421`、
  `tests/test_dialogs_feedback_v280.py:917-918`），六处全部走 `_ask_text` / `_ask_item` + `modal()`。
  **将来真要验怎么验**（只在静态门被放宽、静态调用重新出现时才需要）：
  ① 真机（**不要** offscreen）跑起来，把另一个窗口置前；② 触发那条静态调用，观察是否抢不到前台；
  ③ 把"命令 / 现象 / 裁决"三行写回 `_dev/audit_feedback_v270.md`。
  **在那之前不动代码。**
* 记录落点：`_dev/audit_feedback_v270.md` `5.1` 末尾（结案原文）+ 该文件第 10 行表格、
  `_dev/audit_behavior_assets_v290.md` 第 15/21 行、`_dev/plan_v270_rounds.md` `12.7` 的 #21 行**全部标注结案**。

## 7. V7【P3】台词库 `_move_line` 的边界回执 —— **属产品代码，未动；精确补丁递交**

**为什么不动**：领地写着"⛔ 不碰产品代码（A/B 的领地）"，而这条改的是 `pet_dialogs.py` 的 `LinesDialog`。
**事实**（读码实测）：`LinesDialog._move_line` `pet_dialogs.py:5654` 与 `_move_member` `:5963` 到边界时走
`_toast(self._pet, "已经是最上面了" / "已经是最下面了")`（宠物气泡）；而行为设置的同一语义走
`BehaviorDialog._note()` `:3153` 的**窗口内状态行**（`self._notes` `:3118`，且用例断言 `ui["toast"] == []`）。
**同一语义两种表现**（原则 4 的反例）——但**两条都是台词库的列表内操作**，建议一起统一（不是只改 `_move_line`）。

**精确补丁（给 A；三处改动 + 两处用例）**：

1. `pet_dialogs.py` `LinesDialog.__init__`（`:5432-5434` 的 `_banner` 之后）加一个**独立**状态行——
   **不要复用 `_banner`**（它记的是"失效引用 N 条"，`_refresh_all` `:6159` 会覆盖）：
   `self._notes = QLabel("")` + `setWordWrap(True)` + `root.addWidget(self._notes)`；
2. 加 `_note(self, text)`（照抄 `BehaviorDialog._note` `:3153-3163`，异常走 `pet_log.log_error`）；
3. `:5654` 与 `:5963` 两句 `_toast(...)` → `self._note(...)`（**措辞一个字不改**——
   `tests/test_dialogs_feedback_v280.py::test_lines_move_member_at_boundary_uses_the_same_wording` 钉的就是"同一套措辞"）；
4. 用例 `tests/test_dialogs_feedback_v280.py::test_move_line_at_boundary_tells_the_user`（`:1296`）改成
   断言 `dlg._notes.text() == "已经是最上面了"` / `"已经是最下面了"` + `ui["toast"] == []`
   （与行为设置那条 `test_step_move_at_boundary_says_so` 同形）；`:1323` 那条"同一套措辞"用例同样改成状态行；
5. 变异（可挂在我那份 spec 名下或 A 自己的）：把 `_note` 改回 `_toast` → 上面两条用例红。

## 8. 三查（三个数一起；单个体检会静默容忍坏输入）

| 检查 | 命令 | 读数（07:57:52，**动树窗口内**，锁存在 / 1 个 python 进程） |
|---|---|---|
| 锚点 | `python -B _dev/mutate_batch_v270.py --scan-only` | **锚点合计 531 条，坏 5 条** |
| nodeid | `python -B _dev/check_mutation_nodeids.py` | 校验范围内 **1280 条，坏 0 条** |
| 变异体 AST | `python -B _dev/check_mutation_ast.py` | **506 条变异，5 条锚点/语法不过** |
| pinned 用例体摘要（本轮新增） | `python -B _dev/check_pinned_ast.py` | 3 份证据 / 39 条 pinned / **过期 1 条**（B 的 `M-B2110-04`：`tests/test_dialogs_feedback_v280.py` 在它跑完之后被改过） |

⚠ **这次读数不作数**：跑的时候 `_dev/.mutation.lock` 存在（有人的 `mutate_check` 正在跑）+ 1 个 python 进程——
按 `VERIFY_DISCIPLINE `十，"任何护栏运行期间树必须静止"。**五个坏锚点里只有 1 条与 C 有关**：
* **M-C5@README.md(0 次)** —— 本轮 `桌宠.py` 函数数 255→290 打死（**父代理已裁决：留到定版整批前统一重锚**，因为函数数还会变）；
* **MA24-move-line-boundary-silent(0 次) · A3-M1-boundary-silent(3 次) · M-C-A38(0 次) · M-C-A39(0 次)** —— 全在 `pet_dialogs.py`，是 A 的 V7/动效改动打死的（**不是 C 的**，已点名给父代理）；
* **M-P04@桌宠.py** 07:45 那遍报"0 次"是**A 正在改那份文件的瞬态**（随后复测 count=1，不坏）。
**定版安静窗口必须重跑这三个数**（顺便把这两条锚点交给改树的人重锚）。
我这边**自己**的两份 spec 在相近窗口实测：`c_v2110` **6/6 CAUGHT** · `c_v2100` **9/9 CAUGHT** ·
`--scan-only` 对这两份 **坏 0**。
（`07:47:07` 无锁复读：**529 / 坏 2** · **1274 / 坏 0** · **504 / 1**，与上表逐数一致；但当时仍有 **4 个 python 进程**
（别的代理在跑 pytest / `_check_static.py`）→ 同样**不作数**，只作「读数稳定」的旁证。）


## 9. 父代理追加裁决 · P1：M 检查的"可解析槽比例上界" → 换成**名单 + 解析器自检**

**改了什么**（`tests/test_guardrails_v24.py`，+169/-…）：
1. **删掉上界** `assert _n_slots / len(seen) <= 0.90`（连同"按实测更新上界"那句指引），**保留**下界 0.76
   与扫描面下限 `len(seen) >= 100`（失明粗警报）；
2. 新增 `_UNRESOLVABLE_SLOTS` 名单：`文件 :: 表达式` 的**精确多重集**（11 个表达式 / 17 处），
   每条写"为什么判不了"；比对**双向** —— 多一条（新盲区）红、少一条（名单过期）红；
3. 新增 `test_b7b_解析器自检_该解析的必须解析_判不了的必须跳过`：合成样本钉
   **5 种该解析的必须解析**（self.<方法> / 模块级函数 / 内联 lambda / guard 包装 / 唯一局部绑定）
   + **4 种判不了的必须跳过**（Qt 内建 / getattr / 下标 / 调用结果）——**不依赖真仓风格**。
4. `_dev/probe_slot_resolution_v2110.py`（新增，只读）：量"当前树 vs HEAD"的比例 + 逐条列出判不了的槽；
5. `_dev/README.md` 新增"判据的形状要贴题：别拿代理量当判据"一节（含"能抓/抓不到"清单）。

**为什么这不是放宽（三条论证）**：
* **贴题**：上界想守的是"不许开始猜不可判定的槽"，而比例 = 可解析/全部候选 —— 分子分母**都会被代码风格推着走**
  （实测 HEAD 151/168 = 0.8988 → 当前树 158/175 = 0.9029，**两边都在涨**）。名单 + 自检直接钉这件事。
* **牙齿**（实测 `8/8 CAUGHT`，其中 P1 两条）：
  · `M-C2110-P1-01` 把一处**能解析**的槽换成判不了的形式（`pet_balance.py` 的 lambda → `anim.finished`）→
    名单"多出一条没登记的"→ `test_b7_static_signal_arity_check` **红**；
  · `M-C2110-P1-02` 让解析器**猜**内建方法签名（`deleteLater/accept/append` → arity 0）→
    ① `test_b7b` 的"必须跳过"四条被解析 → 红；② 名单里那 7 条消失（名单过期）→ `test_b7` 红。
* **多抓/少抓（如实）**：多抓了"新盲区必须显式登记"与"名单过期"两件事（比例完全看不见）；
  **少抓**的是——接收者动态的 `getattr(sig, name).connect(...)`（`iter_slots` 压根不当候选，
  **旧口径同样看不见**，不是新丢的）；同文件同表达式重复出现（多重集按计数比，会被计数抓到）。

**原文读数（收尾复跑）**：四个受影响文件一起跑
`python -m pytest tests/test_guardrails_v24.py tests/test_release_check.py tests/test_pinned_ast_v2110.py tests/test_mutate_harness_v244.py -o addopts= -q` → **92 passed in 20.41s**。
单跑 M 检查那一份：`python -m pytest tests/test_guardrails_v24.py -o addopts= -q -s` →
`13 passed in 6.89s`；它自己打印 `[B7 实测] 真仓槽解析：guard 包装 25 处（解析出 25）、局部变量/嵌套 def 1 处`；
单跑 B7/B7b → `2 passed in 4.86s`。`_dev/probe_slot_resolution_v2110.py --head` →
当前树 175/158（0.9029）/判不了 17；HEAD 修订 168/151（0.8988）/判不了 17。

## 10. 父代理授权的三件落地

**① `_check_release.py` 也读 `pinned_ast`（越界留痕）**：`git diff --numstat` = **+150/-2、8 个 hunk**。
新增纯函数 `_drop_docstring / _digest_nodes / _pinned_digest_of / _split_pinned / pinned_ast_now / stale_pinned`
（算法与 `_dev/_mutate_lib.pin_digest` **逐位一致**，由 `test_pinned_ast_digest_matches_the_mutation_lib` 双向钉住），
并在 `mutation_evidence_notes()` 里加两类提示：**pinned 摘要过期** + **"还没有 pinned 段的证据"汇总**。
范围谓词 = "有 `repo_fingerprint` 记录的证据文件"（与 `check_pinned_ast.py` **逐字一致**）。
**改前/改后提示条数（同树）**：**34 → 36**；新增 2 条 = pinned 摘要过期 **1**（B 的 `M-B2110-04`，真抓到的）
+ 缺 pinned 段 **1**（点名 **31 份**）。
⚠ **口径更正**：任务书引用的"36 份还没有 pinned_ast 段"是我工具**第一版宽谓词**的读数；
落地时把两个工具的谓词统一收紧成"指纹通道里的证据"，得到 **31** ——
多出来的 5 份是 `results_batch_v270.json`（批次日志）、`results_ambient_settle_v26.json` /
`results_idle_settle_v26.json` / `results_proc_reset_cross_v26.json`（v2.6.0 独立验证结果）、
`mutations_proc_reset_v26.json`（判据是 `_verify_v13` 的 FAIL 名，没有 pytest nodeid）——
**对它们 pinned_ast 不适用**，点名只会变噪音。
测试：`python -m pytest tests/test_release_check.py -o addopts= -q` → **41 passed**（37 → 41，新增 4 条；
两条老用例的夹具补了正确 `pinned_ast`，否则会被"缺 pinned 段"多算一条）。

**② 重锚**：
* **`M-C12`（`mutations_compat_v243.json`，`_check_release.py`）**：**是我自己的改动打死的** ——
  我新加的 `stale_pinned` 复制了 `if not isinstance(recorded, dict) or not recorded: return [] / out = []`
  三行 → 命中 2 次。**已重锚**（追加 `stale_fingerprints` 独有的 `for rel in sorted(recorded):` 消歧），
  `--scan-only` 复测该条坏 0；`why` 里写了"被 v2.11.0 新增的 stale_pinned 复制，原意不变"。
* **`M-C5`（README）**：**按父代理裁决留到定版整批前统一重锚**（`桌宠.py` 函数数还会变）。
* **`M-P04`**：复测 count=1，**不是坏锚点**（07:45 那次是 A 正在改 `桌宠.py` 的瞬态）。

**③ `check_pinned_ast.py` 进定版流水**：已写进 `_dev/README.md` 的**铁律 5**一节（与 `--scan-only`、
nodeid 体检并列），并注明"**旧证据要等定版整批复跑才带上 `pinned_ast` 段**"（当前 31 份）。


## 12. 收尾批（父代理第 2 次派单：A 完工后的三件）

**① 收编 A 的 spec（24 条）**：`%TEMP%\a_mutations_v2110.json` → `_dev/mutations_agent_a_v2110.json`。
* **逐字收编**：SHA256 两边一致（`31134F286A3D7B55…364AC`）· 28,885 B · **纯 LF**（CR=0）· **U+FFFD=0**
  （铁律 4「中文 nodeid 经管道一律不可信」：先验编码，再验语义）。
* **官方工具复核**（不是抄它的自述）：`python -B _dev/mutate_check.py _dev/mutations_agent_a_v2110.json`
  → **24/24 CAUGHT**（与 A 自述一致）；基线 11 条用例全过；29 条 nodeid 坏 0；24 条锚点坏 0；
  `check_mutation_ast` 不过 0。逐条 `failed` 列表见该文件 `results` 段。
* ⚠ **记账（不是缺陷，但要写明）**：这 24 条的 `expect_fail` **全是空的** → 判定走**默认口径**
  （「`tests` 里至少一条没通过」）。它比「点名必须红哪条」松一档；本轮 24/24 的每一条 `failed`
  都落在自己 `tests` 里，证据成立，但**下一个人改动这些用例时，判定会先变宽再暴露**；
  要不要补 `expect_fail` 由定版那批的人决定（补的话应从**意图**写，不是抄这次的红名单）。
* 已登记进 `_dev/README.md` 的 spec 表（锚点分布：6 个文件，其中新模块 `pet_motion.py` 3 条）。

**② `pet_motion.py` 进两处指纹清单**（父代理授权）：`_check_release.MUTATION_FINGERPRINT_FILES` 与
`_dev/_mutate_lib.repo_fingerprint` **同一次改动、逐项同序** → 两处都是 **29 个键**，
`pet_motion.py` 两侧都在；`pytest tests/test_release_check.py` → **41 passed**（一致性用例没红）。
README 的「关键文件清单 = 28 个」同步改成 **29 个**并写明理由（动效令牌表：改它 ≈ 改所有动效；
A 的 spec 有 3 条锚点在它上面，此前零提示）。
**越界留痕（A 的，父代理要求一并记）**：A 往 `_check_release.SYNC_FILES` 加了 `pet_motion.py`
（+3 行含注释）——不加则 `check_imported_modules_shipped` 必红（`桌宠.py` / `pet_widgets.py` 都 import 它）。
**这条保留**；它属于「新模块必须进发货清单」的既有口径，与两处指纹清单改动互不冲突。

**③ 重锚 4 条 + `M-C5`**（A 的对照表 + 我独立核数）：
* `MA24-move-line-boundary-silent`（a_v280）· `A3-M1-boundary-silent`（a_v290，**连上一行 `j = max(...)` 一起钉**才唯一）·
  `M-C-A38` · `M-C-A39`（c_v280，钉 `save_dialogue` 那行）—— 逐条**新 old 实测 count=1**；
  语义**不反转**（缺陷还在，只是出口从气泡换成状态行）。
* `M-C-A38` 的 new：A 的对照表写「只给 `return` 加个注释」——**那在语义上是空转**（`_note` 那行还在跑，
  用例不会红），所以按它的**意图**落成「删掉 `_note`、`return` 加注释」。**这条更正已写进该条 `why`。**
* `M-C5`：**AST 实测** `桌宠.py` = **291 函数**、`pet_dialogs.py` = **398**（与 README.md / README.en.md
  当前文字一致，`pytest -k readme` 3 passed）；锚点重锚成 `（291 函数）`、`why` 里写明「数字还会漂，
  改这两个文件就要回来同步」。
* 收尾实测：`check_mutation_ast` = **506 条 / 0 不过**；`--scan-only` = **锚点合计 555 条，坏 0 条**
  （531 + A 新 spec 24），**全库再没有坏锚点**。
* **顺手清了一个死锁**：`_dev/.mutation.lock/79048.json`（07:48:09 起、进程早已不在）——按 README
  铁律 2 的规程核过 pid 与进程、只删这一个文件（当时另一个持有者是我自己的运行，未动）。
* **重锚后重跑**（本仓口径：重锚过就得重跑才有判定）：`mutations_agent_a_v280` / `a_v290` / `c_v280`
  三份在收尾窗口各跑一遍，读数见 `13。

## 13. 收尾复跑读数（**安静窗口**：08:24:09 · 无锁 · 0 个 python 进程）

| 项 | 命令 | 读数 |
|---|---|---|
| 锚点 | `python -B _dev/mutate_batch_v270.py --scan-only` | **锚点合计 555 条，坏 0 条** |
| nodeid | `python -B _dev/check_mutation_nodeids.py` | 校验范围内 **1309 条，坏 0 条** |
| 变异体 AST | `python -B _dev/check_mutation_ast.py` | **530 条变异，0 条锚点/语法不过** |
| pinned 用例体检 | `python -B _dev/check_pinned_ast.py` | 8 份证据 / 记录 pinned nodeid **204** 条 / **过期 1 条** |
| 发布门 | `_check_release.mutation_evidence_notes()` | **33 条**（其中 pinned 相关 **2**：摘要过期 1 + 缺 pinned 段 1） |

**重锚后重跑（本仓口径：重锚过就得重跑才有判定）**：
* `mutations_agent_a_v280.json` → **25/25 CAUGHT**（08:14:29；`MA24` 红在 `test_move_line_at_boundary_tells_the_user`）
* `mutations_agent_a_v290.json` → **28/28 CAUGHT**（08:15:49；`A3-M1` 红在 `test_step_move_at_boundary_says_so`）
* `mutations_agent_c_v280.json` → **97/97 CAUGHT**（`M-C-A38` 红在 `test_move_line_at_boundary_tells_the_user`；`M-C-A39` 红在 `test_lines_move_member_at_boundary_uses_the_same_wording`）
* `mutations_compat_v243.json` → **13/13 CAUGHT**（`M-C5` 红在 `test_readme_annotation_scope_matches_the_code`；`M-C12` 红在两条发布门用例）
* `mutations_agent_a_v2110.json`（收编）→ **24/24 CAUGHT**（08:12:38）
* 相关测试：`pytest tests/test_release_check.py tests/test_guardrails_v24.py tests/test_round3_a_fixes.py` → **95 passed**

**唯一那条过期（不是我的）**：`mutations_agent_b_v2110.json` / `M-B2110-04-import-tip-points-at-save` ——
它跑完之后（07:42:46）`tests/test_dialogs_feedback_v280.py` 在 07:49:26 被改过（摘要 `3acd833e3a71→3cb488b1d9a3`）。
B 重跑那条 spec 即消。

**`c_v280` 第一次 rc=2 的复盘（如实记，别读成"基线红"）**：第一次跑在影子副本里基线崩了
（`Fatal Python error: _Py_HashRandomization_Init: failed to get random numbers to initialize Python`，
`failed` 列表为空 + runpy 栈），`mutate_check` 按设计记 BASELINE-RED 并中止。
**复核**：在**安静窗口**用同一份用例集直接跑真仓 → **81 passed in 33.38s**（rc=0）→
判定为**环境/负载偶发**（不是真基线红）；随即重跑整份 spec → **97/97 CAUGHT**。
⚠ 记账：那一次 rc=2 **没有产出任何判定**，也没被当成通过。

## 14. 静默 except 白名单登记（A 判定 17 条新键 + 1 条 count 刷新）

**做法**：`python -B _dev/silent_except_whitelist.py --write`（新键一律先落 `unreviewed`，
**理由码必须人工给**——这正是工具设计里「写进去先红着」的那一步）→ 逐条按 A 的判定填理由。

**逐条登记（17 条新键；键含结构指纹后缀）**：

| 理由码 | 条数 | 键 |
|---|---|---|
| `fallback` | 4 | `pet_motion.py` 的 `duration_ms` / `effective_duration` / `visual_scale` / `parse_hex`（坏配置值 → 回默认时长/缩放/颜色） |
| `probe` | 2 | `pet_motion.py` 的 `system_reduce_motion` / `system_dark_theme`（读不到系统设置 = 「不知道」，调用方据此**保持动效开启**） |
| `cleanup` | 10 | `pet_dialogs.py|_route_voice_event`（B 的：per listener 包 try，已析构的对话框跳过）· `pet_widgets.py` 的 `_stop_fade` / `_retire_fade` · `桌宠.py` 的 `_retire_anim` / `_retire_overlay` / `_retire_slide` / `_stop_slide` / `_stop_thinking_pulse` / `_sync_hover_glow` / `_clear_motion_overlays`（Qt 对象可能已析构，尽力而为地停/收动画） |
| `teardown` | 1 | `桌宠.py|_reset_pointer_state`（closeEvent / `_quit` / 拖到窗外松手三条打断路径共用；窗口已在析构中的极端路径） |

**count 刷新（沿用原理由码）**：`桌宠.py|_quit` **7 → 9**（`teardown` 不变；净增 2 = A 新增的「退出时收掉在途涟漪/心形」）。

⚠ **与父代理口径的对账**：父代理给的是「cleanup 12 · teardown 1 · fallback 4 · probe 2」（=19）。
实测**新键是 17 条**：cleanup **10** + teardown 1 + fallback 4 + probe 2 = 17；
**多出来的 2 条就是 `_quit` 净增的那两处**（它们在**已有键** `桌宠.py|_quit`（teardown）里，不是新键）——17 + 2 = 19，两边对得上。

**实测（收尾）**：
* `python -B _dev/silent_except_whitelist.py --check` → **判定通过（白名单条目 323，unreviewed 0）**，rc=0
* `python -m pytest tests/test_silent_except_v252.py -q` → **26 passed**（两条红都消：`test_every_silent_except_has_an_owner` + `test_whitelist_reasons_are_reviewed_and_evidenced`）
* 白名单 before/after 差集（备份 = 改动前的 306 条）：**新增 17 / 移除 0**；`pet_dialogs.py` 键数 **49 → 50**；唯一 count 变化 = `_quit` 7→9

**A 问的「两处不需要数据改动」——已确认（用差集验的，不是目测）**：
* `pet_dialogs.py|__init__|0d4b0e40a6` **count=2**（白名单**本来就是 2**，扫描也是 2）→ 无需改；
* `_hook_voice_ui` 的两条键在本轮白名单里**从来不存在**（移除 0 条）→ 无需改。
（A 说的「count 3→2 / 两条键消失」讲的是它**改代码的中间态**，不是白名单差集。）

**复核 A 对 `tests/test_silent_except_v252.py` 的改动（它请我复核）**：
* `git diff --numstat` = **+9/-1**；**唯一的非注释改动**是 `per` 断言里 `pet_dialogs.py: 49 → 50`；
* **50 是对的**（扫描实测就是 50；该用例现在绿）；改动位置与理由符合该用例自己的记账惯例；
* ⚠ **但理由里的算术是错的，我已更正**：原注释写「`_hook_voice_ui` 的两条键被移除 + connect 那条 → 净减 2 键」，
  而白名单差集是 **新增 1 / 移除 0** —— 那三条**从来没有被登记过**，所以既没有「键被移除」也没有「净减」；
  本条数字的变化**只由 B 的 `_route_voice_event` 造成**（49 + 1 = 50）。已把注释改成可核对的表述。

**一条措辞观察（不改，留给下一轮）**：理由码 `cleanup` 的说明是「尽力而为的清理/回滚：失败只会在磁盘上
留孤儿文件」，而 `pet_dialogs.py|_route_voice_event` 是**监听者扇出时的跳过**（与磁盘无关）。
**码是对的、说明偏窄**：将来若再出现「非文件类 cleanup」，可考虑把 REASONS 的 `cleanup` 文案放宽成
「尽力而为、失败不影响用户可见结果的收尾/扇出」，但那要连着白名单里 32 条 `why` 一起同步
（测试会拒绝不在 REASONS 里的码，`why` 与 REASONS 同源）——**本轮不动**。

**纪律披露**：登记全程是**纯文件操作（不取变异锁）**；`--check` 与那一次 `pytest` 跑的时候，
B 的 `mutate_check:mutations_agent_b_v2110.json` 正在跑（锁在）——两者都不取锁、且只读源码 + 白名单，
但那一段不是「无 python 进程」的安静窗口，**如实记在这里**。

## 11. 没做到 / 让步 / 疑问

1. ~~**V7 没做**（产品代码不属我的领地）~~ → **父代理已派给 A，且 A 已落地**（`M-A2110-23-lines-note-back-to-toast` 实测 CAUGHT；那两条边界用例已加强式改写成"状态行有那句话 + 气泡为空"）。本报告 §7 的补丁与 A 的落地方向一致。
2. **`pinned_ast` 现在 8 份证据上有**（收尾重跑又带上 5 份：a_v280 / a_v290 / c_v280 / compat_v243 / a_v2110），**其余 31 份等定版整批复跑**。我**没有**为了"数字好看"去手工塞键（`--update` 之类的后门一概没做）。
3. ~~**`_check_release.py` 没动**~~ → **父代理已授权、已落地**（§10：+150/-2、8 个 hunk；发布门现在读 `pinned_ast`，
   改前/改后提示 34 → 36）。**这条留档是为了记"当时为什么先不做"**（领地规矩），落地过程与越界留痕见 §10。
   V1 的声音现在有**三处**：`check_pinned_ast.py`（定版三件套之一）、发布门 notes、整批复跑。
4. ~~**两条坏锚点不属于我**（M-C5 / M-P04）~~ → **都已了结**：`M-C5` 已重锚（§12③，AST 实测 291/398）；
   `M-P04` 复测 count=1、**从来不是坏锚点**（07:45 那次是 A 正在改 `桌宠.py` 的瞬态读数）。
   **教训留档**："我改过 `_dev/mutate_check.py` 与 `_dev/_mutate_lib.py`" 这件事已让一条自己的旧锚点（R5-01）
   死过一次，收尾又让 `M-C12` 死过一次（`stale_pinned` 复制了同样的判空三行）——**改 `_dev` 里的判定器同样算"改源码"**，
   收工前必须跑 `--scan-only`。
5. **两处形态变化要记账**：`results.items[].failed / .errors` 现在存**整条 nodeid**（V3）；`errors_teardown` 是新键（V2）。
   历史条目保持旧形态，不改（记账口径见 `_dev/README.md`）。
6. **两次并发事故（我自己造成的，已收拾）**：我在 A/B 的变异批次正在跑时各起过一次 `mutate_check`
   （07:39:17 与 07:42:24），**两次都在几秒内主动 kill**，并按 README `铁律 2 的"死锁清理"规程
   **逐个删掉自己那个 `<pid>.json` 锁文件**（先核对内容里的 pid 与进程确实已退出，再删；没碰别人的锁）。
   **两次窗口都没有产出任何数字**，也没把别人的读数当结论。
