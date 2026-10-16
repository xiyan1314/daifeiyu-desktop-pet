# 代理 C · v2.10.0 第 8 轮报告（R4 断言强度 · R5 judge 口径 · R6 指纹覆盖）

## 0. 一句话

**三件都落地，三件都带"能真失败"的证据**：R4 全仓扫出 6 条恒真/弱断言、清掉 4 条（另 2 条在冻结基线副本里，
只留档），并加了一条守卫 + 7 条新变异（**7/7 CAUGHT**）；R5 把 judge 口径接到"点名到用例的 ERROR 行"，
**影响面是实测的**（全库非 CAUGHT 只有 1 条，就是登记在案的 `A11-M2`，且**不是为了让它变绿**——
口径变更理由与反向用例都写在下文）；R6 逐文件裁决 21 个盲区文件，**补进 12 个**，
未覆盖从 **50 条降到 20 条**（覆盖率 89.5% → 95.8%）。

---

## 1. R4：恒真/弱断言系统性清理

### 1.1 先有工具，再有清单

`_dev/audit_tautology_asserts_v2100.py`（新增，AST 层、只读、秒级）。五类判定码：

| 码 | 判据 | 是否挡 `--strict` |
|---|---|---|
| 恒真-T | `assert True` / 任何真值常量 / `X or True` / `a == a`、`a is a`、`a <= a` / `assert not x` 而 x 是恒假常量 | 挡 |
| 恒假-F | `X and False` / `a != a` / 恒假常量（**永远不会过 = 死断言**） | 挡 |
| 死块-D | 落在 `if False:` / `while False:` 里的断言 | 挡 |
| 已保证-R | 断言的是同一函数里刚赋过的**不可变**字面量（`x = "s"` 之后 `assert x`） | 不挡 |
| 重复调用-W | `assert f(x) == f(x)`（自比较里含**真函数调用**） | 不挡（只列） |

`--selftest` **从样本自己的标记（`# EXP:` / `# NOT`）解析期望**、逐条对数——
不手抄行号（"照抄一遍"这件事本轮刚被 nodeid 工具教训过）。实测：**12 条命中逐条对上、5 条反例未报**。
**没有这一步，"扫描 0 条"与"扫描器坏了"长得一模一样。**

### 1.2 全仓扫描结果（`.` 共扫 .py，含产品代码）

```
恒真-T     _dev/_compat270/base/tests/test_import_thread.py:108
恒真-T     tests/test_import_thread.py:108
重复调用-W   _dev/_compat270/base/tests/test_io_v231.py:1287
重复调用-W   _dev/_compat270/base/tests/test_plugin_host_v251.py:1643
重复调用-W   tests/test_io_v231.py:1287
重复调用-W   tests/test_plugin_host_v251.py:1643
合计 6 条：恒真-T 2 · 重复调用-W 4
```

**产品代码 0 条**，全部落在测试文件里；**活树 3 条 + 冻结副本 3 条**。
另有 **1 条是人读出来的**（工具判据之外的 `and`/`or` 优先级写错，`test_dialogs_more_v24.py:880`）——
所以"要处理的"是 **4 条**（活树 3 + 人眼 1），冻结副本那 3 条只留档。

**清完之后的复核（兼容审按现树复算）**：全仓 **380 个 .py / 3 条**，**全在冻结副本里**
（活 `tests/` = 0、产品代码 = 0）。⚠ **记账更正**：本节初稿把"工具口径 6 条"与"compat270 同样两处"
混在一起写了——**compat270 实测是 3 处**（恒真 1 + 重复调用 2）。

### 1.3 逐条处置

| # | 位置 | 判定 | 处置 |
|---|---|---|---|
| 1 | `tests/test_import_thread.py:108` | 恒真-T | **加强**：`_set_busy(True)` 先真进忙碌态 → 钉 `_busy_state is False` / `_ok`、`_cancel` 恢复可用 / `_stop_btn.isHidden()` |
| 2 | `tests/test_io_v231.py:1287` | 重复调用-W | **加强**：`./` 变体必须同锁 · 不同路径必须不同锁 · 锁可重入（acquire 两次）；并**移出 Windows 走不到的 else 分支** |
| 3 | `tests/test_plugin_host_v251.py:1643` | 重复调用-W | **加强**：在用例里独立算一遍公式 `sha256(名字 utf-8 + 0x00 + 内容)` + 长度 64（指纹是**落账格式**） |
| 4 | `tests/test_dialogs_more_v24.py:880` | 优先级写错（非恒真） | **加强**：`and` 比 `or` 紧 → 原句等价于"0 或 1 在里面"，把重映射删掉照样绿 → 改成 `dlg._touched_flags == {1}` |
| 5·6 | `_dev/_compat270/base/tests/**` | 恒真-T · 重复调用-W | **不改，留档**：冻结副本改了就不再是"当时那份基线"（父代理已确认同意） |

### 1.4 新失败模式：断言被平台条件"藏"起来（父代理点名单独登记）

第 2 条的原始写法是在 `if os.name == "nt": … else:` 的 **else 分支**里 —— 本机是 Windows，
**那条断言对本地每一次全量门来说从未执行过**。它与恒真**同源**（写了等于没写），但**更隐蔽**：
恒真还能被静态扫出来，平台条件分支**静态看完全正常**。
**抓法只有一个：变异。** 本轮把 `abspath` 归一拿掉后，这条变异**第一遍跑出 NOT CAUGHT（rc=0，1 passed）**
——那一刻才知道"这条断言在本机根本没跑"。处置：平台无关的检查提到 `if` 之前，平台特有的留在里面。
**全仓复查**：`tests/**` 里平台条件只有 3 处，另两处是 `test_config.py:187/199` 的
`skipif(sys.platform != "win32")` —— **不改**（skip 会出现在 pytest 汇总行里，是**可见**的；
但记账清楚：DPAPI 那两条在非 Windows 上永远不验证）。已同步进 `_dev/README.md` 的"假覆盖"一节。

### 1.5 防回归（缺一不可的两条）

1. `tests/test_assertion_strength_v2100.py`（新增 3 条）：扫 `tests/**`，出现 恒真/恒假/死块 就红；
   外加"本轮清掉的四条**确实不再是那个写法**"的点名钉子——**按 AST 的断言表达式比，不按文本**：
   本轮在旧断言上方留了"原来是 X"的说明，**文本匹配第一次跑就被自己的说明误报拦下**，
   改成 `ast.unparse` + 归一化（去空白与引号）之后才准确。
2. `_dev/mutations_agent_c_v2100.json` 的 `M-C2100-R4-05`：把恒真断言**原样塞回** `tests/test_import_thread.py`，
   守卫必须当场红（实测两条用例同时红）。**守卫自己也要有"能真失败"的证据，否则它自己就是新的假覆盖。**

### 1.6 工具自己的教训（写下来免得下一个人重犯）

第一版把"`x = []` 之后 `assert x == []`""也算恒真 → 一口气报 **63 条**，
逐条看下来 **63/63 全是误报**（那是**捕获列表**，被测代码可以通过别名往里追加）。
于是把"已保证-R"收紧成**只认不可变标量**，并把 `assert f(x) == f(x)` 从"恒真"改判成"重复调用-W（只列不挡）"。
**判据宁可窄而准——宽而吵的工具，没人会看第二眼。**

---

## 2. R5：judge 口径接上 ERROR 行

### 2.1 新口径与边界

**没通过 = FAILED 行 + 点名到用例的 ERROR 行。**

```
ERROR tests/x.py::test_y - AttributeError: no attribute _state_label     ← 认（用例级 error）
ERROR tests/x.py - Failed: 'yield' keyword is allowed in fixtures...     ← 不认（整文件收集期）
```

`_mutate_lib.errored_nodeids()`（新增）只认前者；`test_error_phases()` 另把相位
（setup / call / teardown）解出来**只供证据可读性**。

### 2.2 为什么它更正确（不是为了放水，四条）

1. **pytest 自己的汇总行**就是 `1 failed, 2 passed, 2 errors`——error 的那条用例**不在 passed 里**，
   "它没通过"是原文事实；
2. **判据一点没松**：仍然要求 **spec 点名的那条**用例没通过，M5 要挡的"**别的**用例被负载抖红"
   原样被挡（反向用例 `test_judge_still_rejects_an_error_of_an_unrelated_test` 钉住）；
3. **本仓早就这么认了**：两份旧形态驱动 `mutate_export_slice.py:103` / `mutate_startup_defer.py:110`
   一直在用 `test_error_lines()` 把"用例 error（setup/call 抛异常）"记成 CAUGHT，
   **只有 spec 形态的 judge 没接**——这是**口径不一致**，不是发明新标准；
4. **不合法变异仍然不算检出**：整文件收集期错误没有 `::`，那是"变异本身不合法"。

### 2.3 影响面对账（**实测**，不是估计）

对照脚本 `_dev/probe_judge_error_lines_v2100.py`（新增）：默认 `--dry-run`（不跑 pytest），
`--run` 才真在影子里重跑候选。**实跑原文**：

```
=== 全库 results 里非 CAUGHT 的条目 ===
mutations_agent_a_v290.json :: A11-M2-label-degraded-to-one-shot
  旧判定 WRONG TEST / rc=1 / failed=[] / 末行 2 errors in 1.32s
  预测：**只能靠 ERROR 行翻**（旧口径：rc!=0 但 FAILED 列表为空）
合计 1 条非 CAUGHT。

（--run）
[mutations_agent_a_v290.json] 基线 2 条用例全过（影子）
  A11-M2-label-degraded-to-one-shot   rc=1  旧 WRONG TEST  → 新 CAUGHT   ★ 翻转
      FAILED []
      ERROR  test_new_state_is_a_resident_label_not_a_one_shot_bubble   [setup]
      ERROR  test_key_information_is_visible_not_only_in_a_tooltip   [setup]
      末行 2 errors in 2.03s
对账结果：翻 1 条 · 不翻 0 条 · 跳过 0 条
```

盘上其余非 CAUGHT 条目 `rc=0`（NOT CAUGHT 那一类），新口径**不可能**翻它们。
**换句话说：这次改口径的净效果只有"把一条本来就该算检出的判定改对"，没有连带放行。**

### 2.4 回归与证据

- `tests/test_mutate_harness_v244.py` **+6 条**（含**真跑一次真 pytest** 的 setup-error 样本：
  从输出里抽名字、验证相位、确认没出错的用例不被算进来）；
- 口径本身的"能真失败"：`M-C2100-R5-01`（judge 退回只看 FAILED 行）与
  `M-C2100-R5-02`（`errored_nodeids` 抽空）——**两条都 CAUGHT**；
- 结果 JSON 多一个 `errors` 字段（判定认它，证据里就得看得见是哪几行）。

### 2.5 已知边界（如实写）

teardown 期 error 也计入（pytest 把那条例用记成 error、不在 passed 里）。语义上最弱，
但**本仓变异语料里目前一条都没有**（A11-M2 那两条相位实测都是 `setup`）；
真出现时按"这条用例没通过"读，并**先看 `errors` 字段与相位**再下结论。
**不为想象中的情况加复杂度**——真出现实例再决定要不要收紧成"只认 setup/call"。

---

## 3. R6：指纹覆盖残留

### 3.1 数据（`probe_fingerprint_gap_v290.py`，只读，本轮实测）

| | 改前 | 改后 |
|---|---|---|
| 指纹键 | 14 个 | **26 个** |
| 覆盖 | 14 文件 / **428 条**（89.5%） | **26 文件 / 458 条**（95.8%） |
| 零提示盲区 | **21 文件 / 50 条** | **9 文件 / 20 条** |

（上轮是 18 文件 / 46 条；**多的 3 文件 / 4 条是本轮代理 C 自己的新 spec 造成的**——如实记账。）

### 3.2 裁决（逐条理由见 `_dev/fingerprint_coverage_v2100.md`）

- **该进、已进（12 个文件 / 30 条）**：`pet_io.py`（**一处就 9 条，全库最大单点盲区**）·
  `pet_services.py` · `pet_widgets.py` · `pet_resources.py` · `pet_tools.py` ·
  `pet_voice.py` · `pet_audio.py` · `pet_chat.py` · `pet_log.py` · `pet_actions.py` ·
  `pet_book.py` · `_check_static.py`（按 `_check_release.py` 已被收进清单的**同一条逻辑**：它自己就是被测对象）。
- **不该进（9 个文件 / 20 条，逐条写了理由与"什么情况下回来改判"）**：`_dev/**` 自指 4 个
  （判定器/影子库/白名单/格式文档——它们**不进发布包**，且把"证据生产机器"计入指纹会让每轮编辑都把所有证据标过期）·
  `tests/**` 2 个（改测试文件本来就会被 nodeid 体检与判定当场抓到）· `README.md` · `requirements.txt` ·
  `.github/workflows/ci.yml`。
- **一条原则写下来**：**"指纹 = 被测源码的版本戳"**，它回答"这份证据是对着这一版**被测代码**跑的吗"，
  不是"这棵树跟当时一模一样吗"（后者由 `checked_at` + `--scan-only` + nodeid 体检分别回答）。

### 3.3 落地与越界留痕（照上一轮的格式）

**越界留痕**：本轮在 `_check_release.py:739-742` 的 `MUTATION_FINGERPRINT_FILES` 里
**追加了 12 个文件名字符串（零逻辑，一处一处可 `git diff -U0` 复核）** —— 这是**代理 C 领地之外**的文件
（任务书 ⛔"不要碰产品代码"）。**依据**：① 两处清单被 `tests/test_release_check.py` 钉成**逐项一致**，
只改一处必然全量红；② 这正是 R6 要解决的事，而它不在任何人的领地里；③ 与 v2.9.0 第 7 轮同类越界同口径，
**本轮已经父代理显式授权（选①）**。
`git diff -U0 -- _check_release.py` 实测只有一个 hunk：**+6 行（2 行注释 + 4 行文件名字符串）/ -1 行**，
**没有任何逻辑行**。同时改了 `_dev/_mutate_lib.repo_fingerprint`（我的领地）的同一份元组，
两处**逐项一致（顺序也一致）**——探针实测 `发布门 26 个 / 变异库 26 个 —— 逐项一致`，
`pytest tests/test_release_check.py` 实测 **37 passed**。

### 3.4 预期副作用（别误读）

盘上 **30 份**证据（有指纹段的共 32 份）都**没有**这 12 个新键 → 发布门会多出 **362 条"缺键"提示**（只提示、不进 fails），
直到**定版整批复跑**（铁律 5）补齐指纹。（口径：`python -B` 直接调 `_check_release.missing_fingerprint_keys` 逐份统计，2026-10-16 实测。）
这正是 README 早就写好的那条路（"消掉缺键只有两条路：重跑对应 spec，或在报告里点名"）。
另外 **`_check_release.py` 自己的哈希变了**（我改的），所以所有证据对它都报"过期"——
同样由定版批跑消掉。

---

## 4. 数字（本轮实测，附出处）

| 指标 | 数值 | 出处（本轮实跑） |
|---|---|---|
| 锚点体检 | **503 条 / 坏 0** | `python -B _dev/mutate_batch_v270.py --scan-only`（PRE/POST 三查：lock=False · python=0） |
| nodeid 体检 | **1157 个 / 坏 0**（范围外 441） | `python -B _dev/check_mutation_nodeids.py` |
| 变异体语法自检 | **478 条 / 0 不过** | `python -B _dev/check_mutation_ast.py` |
| 本轮新 spec | 7 条变异 / 14 nodeid / **7/7 CAUGHT**（收尾又加 2 条口径回归 → **9/9**，见 §8） | `python -B _dev/mutate_check.py _dev/mutations_agent_c_v2100.json`（基线 9 条用例全过） |
| 恒真断言扫描 | 378 个 .py，**6 条命中 / 产品代码 0 条** | `python -B _dev/audit_tautology_asserts_v2100.py .` |
| 扫描器自检 | **12 条命中逐条对上 / 5 条反例未报** | `python -B _dev/audit_tautology_asserts_v2100.py --selftest` |
| 受影响用例 | **164 passed**（6 个文件） | `pytest tests/test_release_check.py tests/test_mutate_harness_v244.py tests/test_assertion_strength_v2100.py tests/test_import_thread.py tests/test_io_v231.py tests/test_dialogs_more_v24.py` |
| 发布门清单一致性 | `pytest tests/test_release_check.py` → **37 passed** | 同上 |
| 指纹覆盖 | **26 文件 / 458 条覆盖 · 9 文件 / 20 条盲区** | `python -B _dev/probe_fingerprint_gap_v290.py` |

**收编 A 的 9 条之后的最终读数（父代理收尾要求）**：

| 指标 | 数值 | 出处 |
|---|---|---|
| 锚点体检 | **512 条 / 坏 0**（其中 `mutations_agent_a_v2100.json` 9 · `mutations_agent_c_v2100.json` 7） | `python -B _dev/mutate_batch_v270.py --scan-only`（PRE/POST：lock=False · python=0） |
| nodeid 体检 | **1220 条 / 坏 0** | `python -B _dev/check_mutation_nodeids.py` |
| 变异体语法自检 | **487 条 / 0 不过** | `python -B _dev/check_mutation_ast.py` |
| 代理 A 的 9 条（**官方工具**复核） | **9/9 CAUGHT**，基线 16 条用例全过 | `python -B _dev/mutate_check.py _dev/mutations_agent_a_v2100.json` |
| 逐条对账（expect_fail vs 实测 FAILED） | 16 条（A 9 + C 7）**全部逐条对上：无缺、无多** | 本轮脚本（按基名比对，逐条打印） |

⚠ **归因说明**：`--scan-only` 从 496 → 512 的 **+16 = 我的 7 条 + A 的 9 条**；
nodeid 从 1139 → 1220 里的 **+14 是我的、+63 是 A 的（45 tests + 18 expect_fail）**。
**本报告只对「我经手的那两份 spec + 三处文档改动」负责。**

---

## 5. 没做到 / 让步 / 疑问（如实写，不许写成做完了）

1. **全量 pytest 本轮没跑**：任务书要求"任何护栏跑动期间树必须静止"，而本轮 A/B 在并行改树
   （`pet_dialogs.py` 在我工作期间从 `4bc0e8c868bb` 漂到 `1d46810817ab`）。
   我跑的是**受影响文件的定向子集**（164 passed）与**影子里的变异**——**都不是出货证据**，定版批跑才算。
2. **`--scan-only` 的 503/坏 0 是"PRE/POST 三查都干净"那一刻的读数**，但树里**仍有**别人在写；
   **按纪律这不构成出货证据**，只是 R4/R5/R6 改动的自检。
3. **R6 的两处清单我只改了这两个元组**，没有动 `_check_release.py` 的任何判据、没有任何新增/删除的检查逻辑；
   **`_check_release.py` 的哈希因此变了**，**30 份**证据对它报"过期"（`mutation_evidence_notes()` 实测返回 **31 条**：
30 条过期 + 1 条缺键汇总）——这是**预期内**的，由定版批跑消掉。
4. **"重复调用-W" 只列不挡**：它是弱断言不是恒真，本轮只改了在锚点上的那两条；
   如果有更强的判据（例如"自比较里两侧含调用"一律要求改成与独立算出的期望值比），那是下一轮的事。
5. **R4 的扫描器是结构判据，不是语义判据**：它能抓"结构上恒真"，抓不了"虽然能红、但红的条件与本意无关"
   （例如断言了实现细节而恰好总是成立）。这类只能靠**变异**（本轮正是靠变异抓出 1.4 那条平台隐藏）。
6. **疑问（留给下一轮）**：`_dev/silent_except_whitelist.py` 上挂着 **5 条**变异（本轮裁决"不进指纹"）——
   它不在发布包里，但它**决定**静默 except 的口径；如果它哪天被改坏而 `tests/test_silent_except_v252.py` 没兜住，
   本轮的裁决前提就不成立（已在文档里写明"什么情况下回来改判"）。

---

## 6. 复跑入口（给下一个人）

```powershell
# R4：恒真断言（秒级、只读）
python -B _dev/audit_tautology_asserts_v2100.py --selftest
python -B _dev/audit_tautology_asserts_v2100.py . --strict

# R5：判定口径的影响面对账（默认不跑 pytest；--run 才真跑影子）
python -B _dev/probe_judge_error_lines_v2100.py
python -B _dev/probe_judge_error_lines_v2100.py --run

# R4/R5 自己的"能真失败"证据（7 条）
python -B _dev/mutate_check.py _dev/mutations_agent_c_v2100.json

# R6：指纹覆盖
python -B _dev/probe_fingerprint_gap_v290.py
python -B -m pytest tests/test_release_check.py -o addopts= -q

# 三项体检（改过 _dev/ 或 tests/ 的人收工前跑）
python -B _dev/mutate_batch_v270.py --scan-only
python -B _dev/check_mutation_nodeids.py
python -B _dev/check_mutation_ast.py
```
---

## 7. 收尾追加（父代理 2026-10-16 要求的三件）

### 7.1 ⚠ `_dev/mutate_check.py` 的「半成品」已修好，并**用它自己跑通**（不是等价驱动器）

**事件**：我把 `results.append(...)` 从 5 元组改成 6 元组之后，**同一批编辑里漏改了下面的打印循环**
（`for mid, st, rc, tail, failed in results`）→ `ValueError: too many values to unpack`。
**代理 A 正好撞进这个窗口**（它后来改用自备的影子驱动器）。**这是我造成的半成品，责任在我。**

**修复与证据**：打印循环改成 `row[:5]` + 第 6 项单独取（`_dev/mutate_check.py:173-181`，文件 mtime 06:02:41），
并**用官方工具实跑**（原文见 §4 表）：`python -B _dev/mutate_check.py _dev/mutations_agent_c_v2100.json` → **7/7 CAUGHT、rc=0**；
`…mutations_agent_a_v2100.json` → **9/9 CAUGHT、rc=0**。**6 元组 / 5 元组这个坑已消。**
**教训（值得写进纪律）**：**改数据结构（元组长度）时，「写」与「读」必须一起改，且改完必须真跑一次**——
我是在跑的时候才发现的，但那已经是**另一个代理可能正在用这个工具**的窗口。

### 7.2 收编 A 的 9 条（`_dev/mutations_agent_a_v2100.json`）并用官方工具复核

- **逐字节收编**：`%TEMP%\a_v2100\mutations_agent_a_v2100.json` → `_dev/mutations_agent_a_v2100.json`
  （13152 B · sha256 前 12 位 `813e302867df` · 纯 LF：`CRLF=0 / 裸 LF=168` · **回读逐字节相同**）。
  **只追加了一句 `note`**（记录入库来源与官方复核），`mutations` 段一个字符没动。
- **官方工具复核**：**9/9 CAUGHT**（基线 16 条用例全过）——A 当时用的是「等价驱动器」，**这是官方口径的复核**。
- **逐条对账**（父代理要求）：16 条（A 9 + C 7）的 `expect_fail` 与实测 `failed` **全部逐条对上：无缺、无多**。
- 预检：`check_mutation_ast.py` 9 条 0 不过 · `check_mutation_nodeids.py` 全对得上。

### 7.3 落盘 B3 文档（`_dev/b3_submit_model_v290.md`）

① **§二之补 · G3（R1）选②**：两处入口的窗口内常驻说明（行为设置 `_target_text` / 角色编辑 `_act_note`）、
为什么不选①、证据用例与两条变异（M-A2100-02/03）；附带记了 U2 的解释性文案（**只改文案、下限一个字没动**）。
② **§三 · R2 落档 = 明确接受「不统一」**：逐对话框实测表（11 行）· **窗口级保存 8 个 → 3 不关窗 / 5 关窗** ·
三条理由（按类型分 / 表单型要补出口 / R4 不变量全成立）· 加牙的用例 `test_submit_model_is_split_by_type_and_every_save_is_pinned` + 变异 M-A2100-09。
③ **⚠ 两处过期改正（我独立复核过）**：原文说 `AlarmDialog` 与台词设置有「R4 反例待修」——
**实测在 HEAD `209875e` 里就已修好**：`git show HEAD:pet_dialogs.py` 里 `("关闭", self.accept)` **count=0**、
`AlarmDialog` 的第二枚是 `("取消", self._cancel)`；现树 `LinesDialog` 是 `close_btn = QPushButton("取消")`（`:5418`）+ `clicked.connect(self._cancel)`（`:5419`）。
仍叫「关闭」的两处是 `ResourceManagerDialog:5062` / `LedgerDialog:5151`，**都 `→ self.reject`、没有暂存态** → 与原文「不是反例」的判断一致。
**顺带更正了上一轮的读数**：「6 关窗 vs 3 不关窗」是 **A8（VoiceDialog）落地之前**、且把 `LinesDialog` 当时的「关闭」→`accept` 算进去的旧读数；正确读数是 **3 不关窗 / 5 关窗**。
**教训**：**文档比代码旧会害人**（下一个人会去修一个已修的问题）；旧行号同样会漂（`3652/5090/…` 引用前先 grep）。

### 7.4 A 报的两个数字（我复核）

A 报 `--scan-only 502 / nodeid 1153`——**与我的读数一致的只有「那一时刻」**：
它取数时我的 spec 还是 6 条、且它的 9 条还没入库。**当前（A 的 9 条入库后、三查 PRE/POST 均 lock=False · python=0）**：
**512 / 坏 0 · nodeid 1220 / 坏 0 · AST 487 / 0 不过**。它报的两个哈希（`pet_dialogs.py=1d46810817ab` · `pet_behaviors.py=732273f95fb4`）
**与我实测一致**（本轮 probe 输出的「当前树」一栏）。
---

## 8. 两审（找茬 + 兼容）报回来的问题：逐条处置（v2.10.0 最后一批）

**两审各报了一部分，兼容审在两处上说得更重**；下面每条都注「是谁报的」与「我怎么验的」。

### 8.1 ⚠ P2-1（找茬）判据扫全文 → 会把 Captured log 回声当成「用例 error」（**假 CAUGHT**）· 已修

**机制我独立复现过**（真 pytest）：失败用例的日志里写一行含 `::` 的 `logging.error`，
pytest 会把 **Captured log call** 原样打印——那行也以 `ERROR ` 开头：

```
ERROR    root:test_p21_demo.py:10 boom see tests/test_x.py::test_pinned - noise
（旧实现）errored_nodeids = ['test_pinned']     ← test_pinned 明明全过
（旧实现）judge(...) = CAUGHT                    ← **假阳性**
```

**修法**：`_mutate_lib.summary_lines()` —— 只读 `short test summary info` 段；
`failed_nodeids` 与 `test_error_lines` 都改走它；找不到这一段（输出被截断 / 超时折叠）**退回全量扫描**（旧行为）。
**修后实测**：`errored_nodeids = []`、`judge = WRONG TEST` ✓。
**回归**：`tests/test_mutate_harness_v244.py::test_errored_nodeids_ignores_a_captured_log_echo`（真跑真 pytest 造样本）；
**能真失败**：`M-C2100-P21-01`（把抽取退回扫全文）→ **CAUGHT**。
**可达性如实说**：真仓 `tests/**` 现在没有这种打印（grep 0 命中），所以它是**潜在洞**、不是正在骗人的洞——
但假阳性比漏判贵，按段收窄的成本只有几行。

### 8.2 ⚠ P2-2（找茬）理由① 比事实大：teardown 期 error 的那条**在 passed 里** · 已改口径表述

**它的实测**：teardown 期 error → 汇总行 `3 passed, 1 error`，**error 的那条用例就在 passed 里**。
所以「error 的那条不在 passed 里」**只对 setup/call 成立**。**行为不改**（判据仍不猜相位），
但 `judge` docstring 与 README 的**理由 ① 已收窄到 setup/call**，并把 teardown 的取舍写清楚：
宁可把「清理炸了」算成检出，也不去猜相位；真出现实例时的收紧路径（叠加 `test_error_phases()` 过滤）也写在同处。
**教训**：**理由只说到事实支持的地方**——这正是本仓反复踩的「措辞比证据大」。

### 8.3 ⚠ P3-1 / 必修 2（两审各自独立造出同一反例）分档用例对 BehaviorDialog 只钉住了失败路径 · 已修

**反例**：给 `BehaviorDialog._save` **成功路径末尾**加 `accept()` → 那条分档用例**照样 passed**。
**根因（实测）**：用例对 BehaviorDialog 用的是**空表单** → `_save` 在落库前失败早退，失败路径本来就不发 `finished`。
**修法**：先用仓里现成的 `_fill_new_behavior` 填一条**有效草稿**再进保存入口（并先清同名探针、跑完删掉）→ **8/8 一起钉住**。
**能真失败**：新增 `M-C2100-P31-01`（成功路径加 `accept()`）→ **CAUGHT**（此前这条变异会假绿）。
用例 docstring 的自述也一并改准（它原来那句「这条用例就是那个必须」名不副实）。

### 8.4 ⚠ 必修 1 / P3-2（兼容 + 找茬）§3.2 的核心理由立在假前提上 · **重写了理由**

原文「5 个关窗窗口**全是**表单型」是**错的**，且与同文件 §3.1 表第 5 行（`RoleEditDialog`｜面板 R1③）自相矛盾。
**改成**：**4 个表单型**（Idle / AISettings / BubbleStyle / Physics）**+ 1 个特批面板型**（RoleEditDialog，
它第二枚按钮已经叫「取消」，改成不关窗会让「走人」读起来像「放弃刚保存的东西」）。
**理由错了就重写理由，不能把错的事实配上对的结论**——这句也写进文档里了。

### 8.5 记账更正（兼容审挑出来的，全部照改）

| 项 | 原文（错） | 实测（对） | 出处 |
|---|---|---|---|
| 缺键提示份数 | 「31 份证据缺键」 | **30 份**（有指纹段的共 32 份）· 缺键条数合计 **362** · `mutation_evidence_notes()` 返回 **31 条** | 直接调 `_check_release.missing_fingerprint_keys` 逐份统计 |
| `fingerprint_coverage_v2100.md` 第 7 行 | 「本轮只出裁决与补丁，**没有落地**」 | **已落地**：两处清单 26 键 · 覆盖 26 文件/458 条 · 盲区 9 文件/20 条 · `test_release_check.py` 37 passed —— 并补上「458 条要等定版批跑才在盘上成立」 | 探针 + 用例复跑 |
| 「另三处 关闭→reject」 | 三处 | **现树全仓只有 2 枚**（ResourceManagerDialog:5062 · LedgerDialog:5151） | `grep close_btn` |
| R4 记账 | 「全仓命中 6 条 / compat270 同样两处」 | 工具口径 **6 条 = 活 3 + 冻结 3**；compat270 **实测 3 处**；**另 1 条是人眼发现的优先级问题**；清完后全仓 **380 .py / 3 条全在冻结副本**（活 tests = 0、产品代码 = 0） | 工具复跑 + 兼容审现树复核 |
| `git status --porcelain -- tests/` 口径 | 转述的「6+3」 | **8 条 = 7 个既有测试文件 + 1 个新文件**（另 2 个新 .py 在 `_dev/`） | 兼容审实测 |

**R6 裁决的「未能证伪」也记账了**：`requirements.txt` / `README.md` / `.github/workflows/ci.yml`
**不该进指纹**这三条，审查方**没有找到反例**，但**也没有证明**它们永远不会成为盲区——写进
`fingerprint_coverage_v2100.md` §三（不改裁决，但别把它读成「已证明」）。

### 8.6 本轮最终读数（修复后）

| 指标 | 数值 | 出处 |
|---|---|---|
| 锚点体检 | **514 条 / 坏 0** | `python -B _dev/mutate_batch_v270.py --scan-only`（PRE/POST：lock=False；POST python=0） |
| nodeid 体检 | **1224 条 / 坏 0** | `python -B _dev/check_mutation_nodeids.py` |
| 变异体语法自检 | **489 条 / 0 不过** | `python -B _dev/check_mutation_ast.py` |
| 代理 C 的 spec | **9/9 CAUGHT**（新增 P21-01 / P31-01 两条） | `python -B _dev/mutate_check.py _dev/mutations_agent_c_v2100.json` |
| 受影响用例 | **112 passed**（test_dialogs_behavior_v290 + test_mutate_harness_v244 + test_assertion_strength_v2100 + test_release_check） | `pytest …` |

**新增 / 改动的用例 nodeid**：
- 新增 `tests/test_mutate_harness_v244.py::test_errored_nodeids_ignores_a_captured_log_echo`（P2-1 回归）
- 加强（**未改名**，nodeid 不变）`tests/test_dialogs_behavior_v290.py::test_submit_model_is_split_by_type_and_every_save_is_pinned`（P3-1）
- 加强（**未改名**）`tests/test_import_thread.py::test_stop_silent_no_error_dialog` ·
  `tests/test_io_v231.py::test_path_lock_merges_case_variants` ·
  `tests/test_plugin_host_v251.py::test_prompt指纹带文件名_文件名就是预设名` ·
  `tests/test_dialogs_more_v24.py::test_role_edit_move_form_bounds_and_pending_follow`（R4 那四条）
---

## 9. 质量审回报：一条真缺口 + 一条工具用法坑 + 两条重写副作用（第 8 轮最后一批）

### 9.1 ⚠ 必修 A（真缺口）`tests/**` 不进指纹的理由**只部分成立** · 已改判并落地

**它挖出的缺口**：把 `tests/test_import_thread.py` 那条用例体**清空（nodeid 不动）** →
`check_mutation_nodeids` **rc=0 / 坏 0**（名字还在），而同一条变异 `M-C2100-R4-01`
**CAUGHT → NOT CAUGHT**，**指纹一声不吭**。（§8.2 里那条「nodeid 体检兜得住测试文件」的前提因此**部分不成立**。）

**处置（采纳它的建议，不扩大）**：只把**承载锚点的两个测试文件**加进两处清单——
`tests/test_dialog_buttons_v270.py`（3 条锚点）+ `tests/test_import_thread.py`（1 条），
**不是整个 `tests/**`**（整目录会把每次测试改动都变成过期噪音）。
**实测**：清单 26 → **28 个键**、两处**逐项一致**；覆盖 26 文件/467 条 → **28 文件 / 472 条**，
盲区 9 文件/20 条 → **7 文件 / 17 条**；`pytest tests/test_release_check.py` = **37 passed**。
**其余 8 条「不进」的理由它认为成立**（README 那条还有实例：`test_d7a_v250_agent_c.py:265`、
`test_round3_a_fixes.py:1074` 真读 README 钉句子/数字）。
**越界留痕（第二次，同样获授权）**：又往 `_check_release.py` 追加了 2 个文件名字符串（含注释），零逻辑。

### 9.2 ⚠ 必修 B（工具用法坑）`--strict` 全仓 exit=1，被文档当复跑入口 · 已修

现树 .py 里仍有 **3 条命中，全在 `_dev/_compat270/base/tests/**`（冻结副本，故意不改）** →
照文档跑 `--strict` 会 exit=1，**下一个人会误判成「回归了」**。
**修法（按构造消除，不只靠文档）**：工具新增 `FROZEN_PREFIXES` —— 冻结副本的命中**单独列一段**、
**不计入 `--strict` 的退出码**；docstring 写明两条正确命令与期望读数：

```
python -B _dev/audit_tautology_asserts_v2100.py tests --strict   # 活树期望「活树合计 0 条」、exit 0
python -B _dev/audit_tautology_asserts_v2100.py . --strict       # 全仓：活树 0 + 冻结副本 3（单独列段）、exit 0
```

**实测**：`tests --strict` → 活树 0 条 / exit 0；`. --strict` → 活树 0 条 + 冻结副本 3 条列出 / **exit 0**；
`--selftest` 仍 12 条对上 / 5 条反例未报。
**边界也写进 docstring 了**（质量审实测）：**只走函数体、不下钻 `match`、不看模块级与类体级**；
它造 21 种形态本工具**抓 11 漏 10**，但拿同一套判据扫那 10 种写法在全仓的落点 → **0 条真恒真** ⇒
**窄，但无实际漏检**（「窄而准」要写在明处，否则下一个人会以为它全能）。

### 9.3 ⚠ 必修 C（重写副作用）工具回写把 LF 翻成 CRLF · 已修 + 已归一化

**实测**：`mutations_agent_a_v2100.json` 收编时 13152 B / 纯 LF，被官方工具回写一次后变成
**20183 B / 325 个 CRLF / 0 裸 LF**（Windows 文本模式）。
**修法**：`mutate_check._write` 与 `_mutate_lib.write_results` 都加 `newline=""`；
两个 v2100 spec 已归一化回**纯 LF**（A 的 20183→**19858 B / CRLF=0**，C 的 14201→**13929 B / CRLF=0**）。
**措辞也改准了**：`逐字节收编` 现在明确限定为**收编那一刻**（note 里写清「之后由工具重写、`mutations` 段未改一个字符」）。

### 9.4 记账更正（它点出我们自己的文档又过期了）

| 项 | 原文（错/过期） | 实测/现状 |
|---|---|---|
| C 的 spec 标题 | 「…证据（**6 条**）」 | 改成 **9 条**（7 条 + 收尾按两审必修补的 2 条口径回归） |
| `_dev/README` | 「**6/6 CAUGHT**」 | 已改 **9/9**；并补上 `M-C2100-P21-01` 与 P31-01 |
| 本报告 §4 | 「**7/7**」 | 已加「收尾又加 2 条口径回归 → **9/9**，见 §8」 |
| `tautology_scan_v2100.json` | 被 gitignore（原始读数不入库） | **在工具 docstring 与 README 脚本表写明**：原始读数不入库、复跑即得（本仓既有口径） |
| 任务书「6 个既有测试文件」 | 6 | 实测 `git status --porcelain -- tests/` = **8 条 = 7 个既有测试文件 + 1 个新文件** |
| 本报告 §5.1 的「受影响 6 个测试文件」 | 容易被读成 git 计数 | 那是**一次 pytest 的跑单**（6 个文件），与 git 计数不是一回事——两个数都对，口径不同 |

### 9.5 它确认/保留的两条

- **teardown 相位是唯一真放宽**（实测 `2 passed, 1 error`、ERROR 点名 pinned、相位 teardown → 判 CAUGHT 而用例在 passed 里）：
  **语料 0 例**，收紧路径是现成的 `test_error_phases()` 过滤（一行）——**本报告与 README 已如实写明，保持现状**；
- **质量审独立复核**：16 条变异 **16/16 CAUGHT、额外红 0**；喂自己的预期给官方 judge **17/17 一致**；反查手脚干净
  （7 个既有测试文件 + 1 新、删除 6 行、无 skip/xfail/mark、`_check_release.py` 一个 hunk +6/-1）。

### 9.6 本批收尾读数（**要用冻结那一刻的读数**——本批改过 `_dev/**` 与 tests）

| 指标 | 数值 | 出处 |
|---|---|---|
| 锚点体检 | **514 条 / 坏 0** | `python -B _dev/mutate_batch_v270.py --scan-only` |
| nodeid 体检 | **1224 条 / 坏 0** | `python -B _dev/check_mutation_nodeids.py` |
| 变异体语法自检 | **489 条 / 0 不过** | `python -B _dev/check_mutation_ast.py` |
| 恒真扫描（活树 / 全仓） | 活树 **0 条**（exit 0）· 全仓另计**冻结副本 3 条**（exit 0） | `audit_tautology_asserts_v2100.py tests --strict` / `. --strict` |
| 指纹清单 / 覆盖 | **28 个键 · 28 文件 / 472 条覆盖 · 盲区 7 文件 / 17 条** | `probe_fingerprint_gap_v290.py` |
| 发布门一致性用例 | **37 passed** | `pytest tests/test_release_check.py` |

### 9.7 ⚠ 我自己在这一批里犯的错，以及工具链怎么抓到的（如实记）

**错**：我给 A 的 spec 追加「口径限定」说明时，**把 ASCII 双引号直接写进了 JSON 字符串值里**
（`newline=""` 与 `"逐字节相同"` 两处共 4 个裸引号）→ `mutations_agent_a_v2100.json` **变成非法 JSON**。

**怎么被发现的（不是我复核出来的，是数字对不上）**：下一次 `--scan-only` 报 **505 条**（少 9 条 = 整整一份 spec）、
`check_mutation_nodeids` 报 **坏 1**、`check_mutation_ast` 报 **480 条**（少 9）——
**三处同时掉同一份 spec 的量**，这才指向「那份文件解析失败被跳过」。

**修复**：只对 `note` 那一行做转义（4 个裸引号 → 反斜杠引号），`mutations` 段一字未动；
复跑三查回到 **514 / 坏 0 · nodeid 1224 / 坏 0 · AST 489 / 0 不过**；两份 spec 现在都是**合法 JSON + 纯 LF**。

**教训（两条，值得进纪律）**：
1. **「改完必须复核」对「只改注释/说明」同样适用**——我改 `note` 后没有重新 `json.loads` 一遍，
   是等到三查数字变了才发现。**JSON 的文本字段里要用转义引号或「」，别直接粘 ASCII 引号。**
2. **这次兜底的形态值得记住**：`--scan-only` **静默跳过**解析失败的文件（不报错，只是少一条），
   真正喊出来的是 `check_mutation_nodeids` 的 **坏 1**。**所以三查要一起跑、三个数要一起看**——
   只跑 `--scan-only` 的话，「少了 9 条」很容易被读成「别人删了 spec」。
