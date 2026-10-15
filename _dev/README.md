# _dev/ 索引（开发/验证脚本，**不进发布包**）

> 发布包与绿色版都不含这个目录：`_check_release.py` 的 `ZIP_EXTRA_PREFIX` 拦 `_dev/`，
> 并有用例钉住（`tests/test_release_chain_v24.py` 的 L3）。
>
> **入库口径（v2.4.2 第三轮收口；v2.4.3 反过来改白名单）**：只入库**脚本与报告**。探针的原始
> 逐轮数据复跑即得，一律 .gitignore。v2.4.3（兼容审查 L8）：此前是"点名忽略几个已知 json"，
> 比复跑命令窄——`probe_export_cost.py` 的 docstring 示例写着 `--json _dev/export_before.json`，
> 照文档复跑就会落下一个**未跟踪**文件、直接撞上发布门的"未跟踪文件"判据（门红）。现在反过来：
> `_dev/*` 全忽略，只白名单 `*.py` / `*.md` / `*_summary.json` / `mutations_*.json` /
> `results_*.json` / `pytest_v242_full.txt`（`.mutation.lock/` 也被 `_dev/*` 覆盖）。
> 新增纯数据产物不必再回来补规则。

---

## 零、六条铁律（动手之前先看一眼；代价都是实测过的）

**铁律 1：在绿色版目录里调用 `python.exe`，一律加 `-B`（或设 `PYTHONDONTWRITEBYTECODE=1`）。**

内置解释器**在启动时**就把 stdlib 编译成 `.pyc` 写进 `Lib/__pycache__/`，这**发生在任何脚本运行之前**——
所以 `_verify_green.py:14` 的 `sys.dont_write_bytecode = True` **拦不住这一批**（它只保护绿色根下的产品模块）。
实测（`qt_strip_report.md` §7.1b 的副本对照实验）：

| 调用方式（在绿色版目录内） | `Lib/` 下新增 `.pyc` |
|---|---|
| `./python.exe -c "import sys"` | **14**（`Lib/__pycache__` 10 个 + `Lib/encodings/__pycache__` 4 个） |
| `./python.exe -B -c "import sys"` | **0** |
| `PYTHONDONTWRITEBYTECODE=1` + `./python.exe -c "import sys"` | **0** |

这 14 个 `.pyc` 会让**发布检测假失败**（绿色版目录里不许有 `__pycache__`），而 `git status` 依旧干净
（`.gitignore` 的 `__pycache__/` 盖住了）——**肉眼看不见，发布门看得见**。`_dev/` 下现存唯一踩这条的是
`repro_quiet.py` 的跑法注释（已加 `-B`）；根目录 `ROADMAP.md`「铁律 1」与 `决策记录-2026-10-11.md` 同口径。
⚠️ 仍**未**加 `-B` 的活文档：`_verify_green.py:8` 的用法示例（`_verify_green.py:8` 写的是 `.\python.exe _verify_green.py`）—— 它不归 `_dev/` 管，已报给人类。

⚠️ **这条又被踩了一次（2026-10-11 13:45–13:50 实测）**：绿色版目录里出现 **24 个 `__pycache__` /
232 个 `.pyc`（合计 3,728,732 B）**，最新一批是 `Lib/__pycache__/shlex.cpython-310.pyc`（13:50:50）——
而当天 09:16 的交接记录里这个数字是 **0 个 pyc / 0 个 `__pycache__`**。也就是说**本场会话里有人**
在绿色版目录里跑了未加 `-B` 的解释器（`git status` 依旧干净，肉眼看不见）。收尾前必须：核对后清掉这
24 个目录，再用 `-B` 复跑绿色版自检；同时比对该目录下用户数据（`config.json` / `roles.json` /
`ledger*.json` / `memory*.json` / `roles/`）的**路径 + 大小 + mtime**，确认一个字节没动。

**铁律 2：跑全量 pytest 之前，确认 `_dev/.mutation.lock/` 不存在。**

变异脚本全程在 `%TEMP%` 影子副本里变异与跑用例（真仓只读），但会在真仓放一个运行锁**目录**
`_dev/.mutation.lock/<pid>.json`（一个持有者一个文件）声明"此刻的结果不可信"；发布门
`_check_release.mutation_lock_problems` 看到它就明确拒绝判定。**锁在 ≠ 有变异在跑**：脚本被强杀
（SIGKILL / 关终端窗口）时 `finally` 跑不到，锁会留下变成**死锁**。看到锁的正确动作：先确认没有
`mutate_*` / `verify_guardrails_can_fail.py` 在跑（`Get-Process python` 看启动时间），确认是死锁再删目录；
**带着锁跑出来的全量结果不作数**（v2.4.2 那次"看似测试污染"的一半成因就是变异窗口与全量门重叠）。

**铁律 3：测试断言不许依赖机器速度（墙钟阈值 = 公开 CI 连红五个提交 #46~#50 的病根）。**

要判"分片/限流/成本"这类事，**先注入"每单位固定成本"**（v2.5.1 用的是帧 5ms / 写条目 8ms），
再断言**结构性事实**：每片单位数上界由预算除注入成本推出来、片数下界、单位守恒、真解码张数守恒、
进度气泡必然出现。**不要**写 `elapsed < 200ms` 这种阈值——同一条用例在快机器上必然假红/假绿。
口径来自提交 `7ee8766`（"修复公开 CI 红门禁"）：三条墙钟用例去墙钟化后，模拟快机器（活变小、
预算与成本同比放大）不假红，**拿掉注入立刻复现 CI #50 的三条红**。

**铁律 4：契约必须双向覆盖（只钉一侧 = 另一侧漂了也没人知道）。**

同一个口径写在两处（两条实现 / 代码与文档）时，**两侧都要有用例**，而且要**互为反向**：

1. **校验器 ↔ 安装器**：v2.5.1 审查实测的两处口径差就是单向覆盖的产物——"必须拒"只在安装器
   一侧有用例，于是校验器悄悄放行了 `payload/a:b.png`（安装器解包时才算"越界"）与 `files: []`
   （安装器才以"没有 payload 目录"拒）。现在校验器**先拒**，两侧一起钉：
   `tests/test_plugin_v251.py::test_口径差_校验器先拒_安装器不留残余`。
2. **常量 ↔ 文档**：`pet_plugin.WIN_ILLEGAL_CHARS` / `WIN_RESERVED_NAMES` 与
   `_dev/plugin_format_v251.md` **互查**——常量里的每个名字都要在文档里，文档里多写一个
   `com10`（常量里没有）也要红：`tests/test_plugin_v251.py::test_windows名字判据与文档同时写死`。

**铁律 5：定版前必须对着出货修订复跑全部 `_dev/mutations_*.json`（含三份旧形态的单脚本驱动）。**

证据有没有效，只由"跑在**这一份**源码上"决定——spec 里的 `old` 是**源码字面量**，任何一次重构、改名、
调参会让它匹配 0 次（`SPEC-BAD` / `ANCHOR-LOST`），而**结果 JSON 里的 CAUGHT 数字不会自己变**：它还是
上一版跑出来的，读起来照样"17/17 全绿"。所以 **SPEC-BAD / ANCHOR-LOST / NOT CAUGHT / WRONG TEST
一律不许当"通过"**——它们的含义是"**这条没被验证**"，不是"这条没问题"。

复跑面 = 全部 `mutations_*.json` 走 `python -B _dev/mutate_check.py <spec>`，**外加**三份**旧形态**
由各自单脚本驱动：`mutate_export_slice.py` 5/5 · `mutate_startup_defer.py` 8/8 ·
`verify_guardrails_can_fail.py` 9/9（三份**不吃** `mutate_check.py`，喂进去只会 `KeyError: mutations`，
这是预期）。跑完对着发布门的两个提示通道复核到**双双静默**：`mutation_evidence_notes()`（指纹过期 /
缺键）+ `mutation_verdict_notes()`（判定不通过）。

**定版前还要跑一次 nodeid 体检（v2.9.0 第 7 轮 · 代理 C 新增，与 `--scan-only` 并列）**：
`python -B _dev/check_mutation_nodeids.py`（秒级、只读、不跑 pytest）。**理由是一条本轮实测出来的新失败模式**：
**改用例名是常规操作，而它会让变异静默失效**——A10 把
`test_static_input_dialogs_are_gone_except_the_frame_action_one` 改名成
`test_static_input_dialogs_are_gone`（而且是**加强式**改写：从"只剩这一处"变成"一处不剩"），
spec 里的 nodeid 不会跟着动，于是 `MA11` 与 `M-C-A22` 指向了**不存在的用例**：pytest 报 node-not-found，
**这两条变异永远判不成 CAUGHT**，而这件事**只有定版整批跑时才暴露成 WRONG TEST**（白烧一整批）。
锚点一直有 `--scan-only` 体检（命中次数必须恰好 1），**nodeid 在此之前一条体检都没有**——这是"清单完整性"的另一面。
判据：`tests/x.py::test_y` 的文件存在**且**真有这个 `def`（含类方法、参数化 `[参数]`）；只给文件的旧形态（`MF4`）文件存在即可；
裸用例名在这份 spec 引用过的文件里找得到即可；`tests` 与 `expect_fail` **两份都查**（后者缺了会永远判 WRONG TEST）。
**校验范围（v2.9.0 三审 F-6 更正）**：**只查 `mutations[].tests` / `mutations[].expect_fail`** —— 这两份才是判定真正会用到的 nodeid；
spec 顶层 `evidence.tests`、`results.tests` / `results.items[].failed` 是**历史记录**（记的是"当时跑出什么"，保留当时的用例名本来就是对的），
**不在校验范围、也不该改**；工具会把范围外还剩多少条**一并报出来**（本轮实测 **429 条**），免得读的人以为措辞比范围大。
退出码 0/1 可直接进定版流水。本轮实测：**校验范围内 1139 条 / 坏 0**（F-C 之后：`A7-M2` 的 tests/expect_fail 从 3 条 nodeid 收到 2 条；修掉那几条之前是**坏 2**）。

**改了源码的人，收工前必须跑一次 `python -B _dev/mutate_batch_v270.py --scan-only`（v2.9.0 第 7 轮定为规矩）**。
理由：**锚点是源码字面量**，你**有意**改写一处实现（改名、改文案、把回执从 `_toast` 换成 `_note`、把函数搬进另一个模块）
就会把**别人的**锚点改成命中 0 次。本轮 A 有意改写了 9 处源码，一次自查就查出 **9 条旧锚点 count=0**
（`agent_a_v280` MA18/MA19/MA22/MA23 · `agent_c_v280` M-C-A30/A31/A36/A37 · `critic_v270` M-R5-P2-4）；
**如果它不自查，这 9 条只会在定版批跑时暴露成 SPEC-BAD / ANCHOR-LOST —— 那时已经很难定位是谁改的**。
自查是秒级的，成本几乎为零；不查的代价是一整批证据作废。**同理，改源码也会让 nodeid 漂移**（见上一段），
两条体检一起跑：`--scan-only` + `check_mutation_nodeids.py`。

**凡是被测路径可能弹真框的用例，必须先 stub `_confirm`/`_info`/`_warn` 三件套**（或加 `quiet` 类 fixture）。
**（v2.9.0 第 7 轮 · 测试健壮性第一条 —— 注意：这条与前五条「证据保护」分开归类：前五条保的是"证据还算不算数"，这条保的是"回归会不会挂住"。）**
**理由（本轮实测）**：`tests/test_dialogs_v24.py::test_ai_settings_clear_long_term_keeps_history` 的第一段**只 stub 了 `_confirm`（返回 False）**，
没 stub `_info`/`_warn`；正常路径下确认被拒 → 函数提前 return，`_info` 走不到。
于是把确认整段拿掉的变异（`M-A290-01`）会让代码走到 `_info` = `modal(QMessageBox)` = **真 exec()** → offscreen 下无人可点 → **永久阻塞**。
**"本该红、结果挂"比假绿更坏**：假绿至少跑完了；挂住会让这条判成"**没被验证**"（harness 折成 `rc=3` → WRONG TEST），
还会**拖垮整批节奏**（本轮实测：一条挂 ~600s，两条就是 ~20 分钟）。
**本仓已两次踩同一类**：本轮这条 + 上一轮的 `tests/test_dialogs_feedback_v280.py::test_dialog_wires_cfg_read_and_write_into_the_backend`（A 当时补了 `quiet`）。
**自查法**：grep 你的用例里有没有 `_confirm`/`_info`/`_warn` 的直接或间接调用点，而被测函数在"参数不合法 / 确认被拒"这些**出错分支**上会不会弹框。

**转述变异原料时，nodeid 也不许手抄（v2.9.0 第 7 轮 · 证据保护第五条）**。
本轮实测的**第三种**原料风险就是"人传话丢失字符"：值班人转述 A 的意图时，把
`test_test_play_plays_and_does_not_say_saved_twice` 写成 `test_test_plays_and_does_not_say_saved_twice`（少一个 `play_`），
**而转述人当时还特意说过"我转抄长字符串才是引入错误的地方"——结果正是这么错的**。
规矩：转述变异原料时，**要么让来源方写成文件**（像 B 那样交 `%TEMP%\b_mutations_v290.json`），
**要么由收方用 `python -B _dev/check_mutation_nodeids.py` 复核**。**"我照抄一遍"本身就是风险点。**

**这一个工具已经抓到三种不同的原料风险**（都发生在"规格文件"上，不是产品代码上）：

| 命中 | 风险类型 | 当场后果（若没抓到） |
|---|---|---|
| `MA11` / `M-C-A22` | **用例改名**（源码改动波及规格） | pytest node-not-found → 永远判不成 CAUGHT，只有定版批跑才暴露 |
| `B7-M1` / `B7-M2` | **乱码**（编码在管道里坏了） | 红的是对的用例、`expect_fail` 谁也匹配不上 → 永远 WRONG TEST |
| `B6-M2` | **转述错**（人传话丢字符） | 同上：node-not-found，静默失效 |

**同一件工具抓到三种不同风险，就是它该进定版流水的最好理由**（跑法见 §一 的脚本表）。

**中文 nodeid / 标识符经"管道或控制台"落盘后一律视为不可信（v2.9.0 第 7 轮 · 证据保护第四条）**。
本轮实测：B 交来的 `%TEMP%\b_mutations_v290.json` 里，**B7-M1 与 B7-M2 的 `expect_fail` 两个中文 nodeid
都被写成了 U+FFFD 乱码**（它自述"18/18 CAUGHT"是对的——它在自己影子里用的是内存里的正确字符串，
**落盘那一步才坏的**）。照抄的后果：pytest 红的是**正确的**用例，而 `expect_fail` 谁也匹配不上 →
**这两条永远判 WRONG TEST**。**判定器工作正常，坏的是原料。**
交原料的人：**要么用文件传递并让收的人自查，要么同时给一个 ASCII 别名**（例如
`tests/test_x.py::test_y` 的英文函数名，或干脆把中文用例名改成英文）。
收原料的人：**必须逐条对齐现树，不许批量兜底**——代理 C 本轮图省事写了"凡乱码就填 B7-M1 的 nodeid"，
**B7-M2 当场判 WRONG TEST**，是**判定器把它抓出来的**（判定器抓原料错，比抓代码错更有价值）。
查法：`python -B _dev/mutate_check.py <spec>` 跑一遍 + 看 `results` 里的 `failed` 列表对不对得上；
乱码字符可以用 `/[\uFFFD]/` 或 `grep -P '\xef\xbf\xbd'` 扫出来。

**一条命令跑完整批（v2.7.0 代理 C 落成脚本）**：`python -B _dev/mutate_batch_v270.py` ——
自动收全 ① 带 `mutations` 段的 `_dev/mutations_*.json`（当前 **26 份 / 471 条锚点** —— v2.8.0 第 6 轮是 22 份 / 392 条，v2.7.0 当时是 20 份 / 270 条，验收员
定版实测为 20 份 / **269** 条，本轮 P1-1 回执修复新增 `M-R6-P1-1` 一条 → **270**）走 `mutate_check.py`；
② 三份**旧形态单脚本驱动**（`mutate_export_slice.py` 5/5 · `mutate_startup_defer.py` 8/8 ·
`mutate_proc_reset_v26.py` 12/12，**共 25 条**）；③ 两份独立结果（`verify_fastci_slices_v251.py`
11 组 · `verify_guardrails_can_fail.py` 9/9）。
**合计 445 条锚点**（420 + 25）—— 这个数字**以 `python -B _dev/mutate_batch_v270.py --scan-only`
的实测输出为准**（`--scan-only` 末行现为「锚点合计 **496** 条，坏 0 条」，2026-10-15 v2.9.0 第 7 轮实测；每加/删一条变异它都会变，
本行此前写的「18 份 / 203 条」是 v2.7.0 代理 C 落成脚本当天的快照，已过期）。
v2.7.0 三份新 spec 的条数：`mutations_agent_a_v270.json` **31** · `mutations_agent_b_v270.json` **35** ·
`mutations_critic_v270.json` **14**（A/B 由验收员复跑 **31/31 · 35/35 全 CAUGHT**）。
**v2.8.0 第 6 轮新增两份**：`mutations_agent_c_v280.json` **97** 条 + `mutations_agent_a_v280.json` **25** 条
（后者是代理 A 那套变异，原本只在 `%TEMP%`，由代理 C 用 ast 原样取出收编入库——见下表与 `_dev/agent_c_v280_report.md`）。
**v2.9.0 第 7 轮新增**：`mutations_agent_b_v280.json` **23** 条（B 上一轮的原料只落在 `%TEMP%\b_mutations_v280.json`，本轮由代理 C 逐字收编——**上一轮那份 spec 根本没入库**，这是补账）
＋ `mutations_agent_b_v290.json` **23** 条（B1 动作候选 + B4 待机引用清理 + B5 待机下拉 + B6 试播 + B7 勾选回读：B 的 18 条 + 代理 C 独立补的 5 条，实测 **23/23 CAUGHT**）
＋ `mutations_agent_a_v290.json` **13** 条（A10 静态输入框归零 · A11/D16 统一确认 · A1 候选下拉 · A2 图片做动作 · A5 未保存确认含**反向**变异 · A6 把确认加回来 · A4 回执改回气泡）。
逐项打印 rc / 用时 / 末行，并把**跑前跑后**的源码指纹一起写进 `_dev/results_batch_v270.json`：
**跑前跑后指纹不一致 = 这一批不是对着同一棵树测的，必须重跑**——三路并行时这是常态，门禁没红
不代表证据有效。只要做锚点体检（秒级、不跑 pytest）：`python -B _dev/mutate_batch_v270.py --scan-only`
（要求每条锚点命中**恰好 1 次**；命中 0 次或 2 次都是"这条没被验证"）。

**反面教材（v2.6.0 第 4 轮实测，别重演）**：`mutations_dialog_fit_v250.json` 的 **M-D09** 钉的是
`clamp_dialog(self, 600, 540)`，而 **v2.5.1 的 A/L5 就把 RoleEditDialog 的设计宽改成了 620**——
`git show 1b5d591:pet_dialogs.py` 里**只有 `620/540`、根本没有 `600/540`**：这条锚点在 **v2.5.1 就已经
死了、跨 v2.5.1 与 v2.6.0 两个版本静默**。没被发现的原因很直接：v2.5.1 给同一件事另立了 M-L1（620），
v2.5.0 那份 spec **再没被整批复跑过**，而它的 `results` 段一直躺着"17/17 CAUGHT"。
同轮 5 条 SPEC-BAD 里另有 4 条是本轮改动的漂移（`compat_v243` M-C12 · `plugin_v251` M-H2/M-H3 ·
`round3_a` M-A13），其中 **M-C12 是"命中 2 次"而不是 0 次**——发布门口径是 **匹配次数 `!= 1`** 即
SPEC-BAD（v2.6.0 新增的 `missing_fingerprint_keys` 复制了同一段两句判空，把唯一锚点变成了歧义）。

**铁律 5 的显式例外登记（v2.7.0 定版收尾 · 全仓唯一一条）：注入型变异 —— wire 用例的同步驱动。**

`tests/test_ui_wire_cache_v241.py::test_in_place_material_swap_is_re_decoded_and_replayed` 里那两处
`drain_anim_slices(win)`（v2.7.0 第 5 轮加的"同步驱动在途分片"，现树 **:227 / :247**）**塞不进普通文本
变异 spec**。机理：`_wire_anim_sets` 首片一旦超预算（`_FRAME_SLICE_MS = 12ms`）就走 `_anim_start_async`，
那条路**先把 idle 槽置空**，真帧集要等 `_anim_chunk_step` 分片装完；用例没有事件循环，当场读到的就是空集。
这两处 drain 就是把"事件循环跑完"**同步**跑一遍——**安静机器上首片不超预算，那条路根本走不到**，
所以把 drain 从测试文件里**文本删掉**，用例照样全绿。验收员用复现器忠实复现了这一点：

| 影子里的动作（产品源码一个字节不动，只改测试文件） | 结果 |
|---|---|
| 拿掉那两处 `drain_anim_slices`（安静机器，不注入） | **rc=0（绿）** → 文本变异会得到假的 `NOT CAUGHT` |
| 同上 **+ `SLOW_SWAP=1` 注入慢解码**（模拟负载/杀软下的冷解码 > 12ms 预算） | **rc=1（红）**，红在 `assert old, "idle 帧集是空的"` |
| 对照组①：drain 原样 + 不注入 | rc=0（绿） |
| 对照组②：drain 原样 + `SLOW_SWAP=1` | rc=0（绿）—— **注入本身不制造假红**，"红"只由"修复被拿掉"造成 |

> 上面四行由本轮定版收尾**逐条复跑过**（0 / 1 / 0 / 0），不是照抄别人的结论。

**复现器（不进仓库，放系统 TEMP）：`%TEMP%\wire_repro_v270\repro_driver.py`** —— 只把"素材被换过之后的那次
重新解码"延迟 20ms（依据 = 同一路径这次的 `(mtime, size)` 与上次解码时不同且刚被写过），其余解码一律不干预；
它自己先 `import 桌宠`（真仓在最前），pytest 里再 import 时命中同一个模块对象——所以**产品源码读的永远是真仓**，
被变异的只是影子里的那个测试文件。复现步骤与预期输出：

```powershell
# 安静 = 绿（先把影子副本里那两处 drain 去掉，产品源码原样）
python -B %TEMP%\wire_repro_v270\repro_driver.py tests/test_ui_wire_cache_v241.py -q          # 预期 rc=0
# 注入 = 红（同一个影子，加环境变量触发慢解码注入）
$env:SLOW_SWAP=1; python -B %TEMP%\wire_repro_v270\repro_driver.py tests/test_ui_wire_cache_v241.py -q   # 预期 rc=1
```

⚠️ **这条复现器只能验"测试文件里的修复"**：产品源码被它钉在真仓（`sys.modules` 里已经是那一份）。
要拿它验产品源码的改动，得把驱动器里那行 `sys.path.insert(0, <真仓>)` 改成影子根，否则会**拿未变异的
真仓产品代码**跑出"全绿"的假象。

**定性：这不是一条被豁免的修复，而是一条证据形态不同的修复；把它塞进文本 spec 只会产生假绿/假红。**
假绿 = 安静机器上"拿掉修复仍全绿" → 记成 `NOT CAUGHT`（污染门禁含义：读数像"有一条没被验证"）；
假红 = 机器恰好有负载时它真红了 → 记成 `CAUGHT`，于是"这条被验证了"同样是假的。判定它只有一条路：
**按上面的复现器在注入条件下跑——安静必须绿、注入必须红，两条都要**（缺一条就不算证据）。

**铁律 6：变异验证必须在影子副本里做，不许原地改真仓。**

原地改写 + 事后还原会造出一个 1~2 秒的"**真仓正处于变异态**"窗口——任何并发的全量 pytest 撞进
这个窗口就会看到**假红**：红的是别人写的用例，看起来却像产品缺陷。
**v2.7.0 第 5 轮实测（2026-10-12）**：A 的全量里 3 条红
（`tests/test_feedback_host_v270.py` 的 `test_set_api_key_empty_input_is_not_silent` /
`test_set_api_key_write_failure_does_not_claim_success` /
`test_ai_toggle_and_chat_rounds_report_write_failure`）**完全等于** B 当时正在跑的 pet_ai 变异红集
（MP8/MP9/MP10/MP11：`if not key:` / `if err:` → `if False:`），第 4 条（wire）另有归属——
只有"窗口重叠"能解释这个集合，但**无法回溯证明**，所以按"不许制造这种窗口"处理（B 自己报的，
没有推给偶发）。

正确做法：`_dev/_mutate_lib.py` 的 `shadow_repo()` / `shadow()`（整仓复制到 `%TEMP%`，变异与
pytest 都在影子里跑，真仓只读），或自己在 `%TEMP%` 里复制一份仓库再改；
不想动真仓的"运行时替换"也是可选项（`%TEMP%` 里放一个驱动脚本，先 `monkeypatch` 目标方法再
`pytest.main(...)`——v2.7.0 第 5 轮用它验了"对话框失败不关窗"那两条跨模块用例）。
**唯一例外**：该文件**只有你在动**、且窗口可忽略（秒级）时允许原地改，但**必须在回报里点名**
（哪个文件、哪几次变异、窗口多大）。

这条与铁律 2 是一对：铁律 2 管"**别在变异窗口里下结论**"，铁律 6 管"**别制造那个窗口**"。

---

## 一、变异验证（"这个护栏能真失败"的证据）

全部走 `_mutate_lib.py`：整仓复制到 `%TEMP%` **影子副本**，变异与 pytest 都在影子里做——
真实仓库只读，只在仓库里放一个运行锁**目录** `_dev/.mutation.lock/`（一个持有者一个 `<pid>.json`，
已 gitignore；发布门 `_check_release.mutation_lock_problems` 看到它会明确拒绝判定）。

**影子副本必须与真仓等价（v2.5.0 第 3 轮 · 质量审查 M1）**：`SKIP_DIRS` 此前连 `.git` 与
`_verify_assets` 一起排除，于是 **3 条用例在影子里永久必红**（`tests/test_release_chain_v24.py`
的两条 L9 需要 `.git`；`tests/test_voice.py` 需要 `_verify_assets/sample.mp4`）——
①以全量套件为判据的 spec 在影子里基线只能记 `BASELINE-RED`；②这 3 条结构上永远进不了变异覆盖；
③影子里的 3 红容易被读成"测试污染"。两者合计只有 **8.9 MB / 381 文件**，现在照抄；跳过表里
只剩缓存 / 打包产物 / 绿色版目录（`__pycache__` / `build` / `dist` / `大肥鱼桌宠_绿色版` …）。
**这解决的真实事故**：旧脚本原地覆写产品源码，变异窗口里别的进程跑全量门会看到来源不明的红
（本轮浪费了两位审查员的时间），且被强杀时会留下半变异源码。

| 脚本 | 干什么 | 复跑 | 结果落盘 |
|---|---|---|---|
| `_mutate_lib.py` | 影子副本 / 运行锁 / 结果 JSON 口径（M7） | 被下面 4 个 import，不单独跑 | — |
| `mutate_check.py` | 按 spec 逐条把修复拿掉，指定用例必须变红 | `python _dev/mutate_check.py _dev/mutations_x.json` | 回写 spec 的 `results` 段 |
| `mutate_export_slice.py` | 导出两段式 E1-E5（**旧形态**：一脚本一套变异 + 结果 JSON 顶层指纹，不是 spec 形态） | `python _dev/mutate_export_slice.py [关键字]` | `mutations_export_slice_v242.json` |
| `mutate_startup_defer.py` | 启动延迟装载 M1-M8（同上，旧形态） | `python _dev/mutate_startup_defer.py [关键字]` | `mutations_startup_defer_v242.json` |
| `verify_guardrails_can_fail.py` | 护栏 A1-A6 / B7-B8 定向变异（9 条，同上，旧形态） | `python _dev/verify_guardrails_can_fail.py` | `results_guardrails_can_fail.json` |
| `verify_d7a_v250_agent_c.py` | v2.5.0 D7-A 三条改动的定向变异（6 条，旧形态，**不产出结果 JSON**） | `python _dev/verify_d7a_v250_agent_c.py` | —（报告里贴输出） |
| `verify_services_ast_v250.py` | **AST 实参对照**（不是变异）：旧 `__init__`（git `2a6563c`）vs 新 `pet_services.py` 的每一处构造实参；`--selftest` 现场验"对调两个实参一定报差异" | `python -B _dev/verify_services_ast_v250.py [--selftest]` | —（stdout 的 `compared=` / `mismatches=`） |
| `mutate_batch_v270.py` | **整批复跑 = 铁律 5 的可执行形态**（v2.7.0 代理 C）：26 份 spec（471 条锚点，条数以 `--scan-only` 为准）+ 3 份旧形态单脚本驱动（25 条）+ 2 份独立结果，一条命令跑完；记录跑前跑后源码指纹，不一致就明确喊"这批不作数" | `python -B _dev/mutate_batch_v270.py [--scan-only]` | `results_batch_v270.json` |
| `check_mutation_nodeids.py` | **nodeid 体检（v2.9.0 第 7 轮 代理 C）**：spec 点名的用例在当前树里**还存不存在**。改用例名（哪怕是加强式改名）会让 `tests`/`expect_fail` 里的 nodeid 指向不存在的用例 → pytest node-not-found → **这条变异永远判不成 CAUGHT**，且只有定版整批跑才暴露。锚点有 `--scan-only`，nodeid 在此之前没有体检——这是清单完整性的另一面。秒级、只读、退出码 0/1 可进流水；**范围 = `mutations[].tests`/`expect_fail`**（历史记录不在内，工具会报出范围外条数）；本轮实测校验范围内 1139 条 / 坏 0 | `python -B _dev/check_mutation_nodeids.py [_dev/mutations_x.json …]`（不带参数＝自动收全） | —（stdout） |
| `check_mutation_ast.py` | **变异体语法自检（v2.8.0 代理 C）**：逐条在内存里应用 `old → new` 再 `ast.parse` —— 抓"把 `if x:` 的缩进体一起换掉"这类错（pytest 收集期才炸，判定只能落 WRONG TEST，整批白跑）。非 `.py` 目标跳过。秒级，**跑批之前先过一遍** | `python -B _dev/check_mutation_ast.py [_dev/mutations_x.json …]`（不带参数＝自动收全） | —（stdout） |
| `probe_c_mutation_output_v270.py` | 小账 a~d 的**变异原文证据**：逐条打印"改了什么 / 锚点命中几次 / 失败断言原文 / 还原后是否绿"（`mutate_check.py` 抓到时不打印输出，这份补的就是那段原文） | `python -B _dev/probe_c_mutation_output_v270.py` | —（stdout，贴报告） |

这三条**旧形态**驱动的 2026-10-11 v2.4.4 复跑结果：导出 **5/5**（`E3` 已重锚到"固定时间戳
`ZipInfo`"写法：`self._zf.writestr(_zi, json.dumps(...))`）、启动延迟装载 **8/8**（`M6` 锚点补回
`not self._custom_role and` 前缀）、护栏 **9/9** —— 已无 ANCHOR-LOST。锚点失效只代表"这条没被验证"，
不等于护栏失效——重锚后重跑才有判定（本轮 5 处重锚见下方"锚点跟着实现搬家"一条）。

结果 JSON 的字段口径（M7）：`checked_at` 时间戳 + 每条 `id / verdict(CAUGHT) / rc / tail`。
`verdict` 里出现 `ANCHOR-LOST` 或 `SPEC-BAD` = 源码改了、spec 的替换锚点失效——**这条没被验证**，
要同步锚点后重跑，别把它读成"通过"。

**判定口径（v2.4.3 · 质量审查 M5）**：此前只看 `rc != 0` 就算 CAUGHT——"别的用例被负载抖红"
也会被记成"这条变异被抓住了"（`test_startup_defer_v242` 的 60ms 阈值在影子里实测抖到
96.4/70.3/97.2ms）。现在 spec 可以写 `expect_fail: [...]`：**它点名的用例必须全部出现在失败
列表里**才算 CAUGHT；没写就退回"`tests` 里至少一条必须在失败列表里"；rc≠0 但预期用例没红 =
`WRONG TEST`（同样计入未抓到）。每条结果都存下 `failed` 列表，便于复核"红的是不是它"。
**v2.4.4 补两条**：① 比对按**基名**——pytest 的参数化实例写成 `test_x[参数]`，spec 里通常只写不带参数
的节点名，此前不剥后缀会把"用例真的红了"记成 WRONG TEST（见下方"参数化后缀"一条，已修）；
② 发布门新增 `mutation_verdict_notes()`：`_dev/*.json` 的 results 段里出现 NOT CAUGHT / WRONG TEST /
SPEC-BAD / ANCHOR-LOST / INVALID / BASELINE-RED 就**出声**（只提示、不挡发布）——此前只提示"指纹过期"，
判定本身没通过是**全静默**的。

**指纹比对（v2.4.3 · 质量审查 M4）**：`repo_fingerprint` 记的是**变异当时**关键文件的 sha256
前 12 位，此前没有任何人比对——结果 JSON 里 `桌宠.py` 记的是 `059b7abfa512`/`2ac5743967b1`，
与出货修订不是同一份。现在发布门（`_check_release.py` 的 `mutation_evidence_notes()`）逐个读
`_dev/*.json` 的指纹，不一致就打印"该证据已过期，需复跑对应 spec"（只提示、不挡发布；
过期是开发期的正常中间态，但**不许静默**）。
关键文件清单 = **14 个**（v2.9.0 第 7 轮实测；v2.5.1 起本文一直写「11 个」，**漏记了 v2.6.0 补的 `pet_plugin_index.py`** —— 实为 12，本轮又补 2）：`桌宠.py` / `pet_export.py` / `pet_lines.py` / `pet_alarm.py` /
`pet_behaviors.py` / `_check_release.py` / `pet_balance.py`（v2.4.4 补）/ `pet_plugin.py` /
`pet_plugin_host.py` / `pet_dialogs.py` / `pet_menu.py`（v2.5.1 找茬审查 P3-1 补的四个模块）/
`pet_plugin_index.py`（v2.6.0 补，本文此前漏记）/ `pet_ai.py` / `pet_config.py`（v2.9.0 第 7 轮补，见下）。
**v2.9.0 第 7 轮为什么补 `pet_ai.py` / `pet_config.py`**：实测**全库 40 条**变异的锚点落在这两个文件上（`pet_ai.py` **31** / `pet_config.py` **9**；31 = agent_b_v270 的 9 + agent_b_v280 的 7 + **agent_b_v290 的 2（B7-M1/M2）** + critic_v270 的 3 + agent_c_v280 的 10）
（`pet_ai.py` **31** 条 / `pet_config.py` **9** 条；含本轮新增的 `B7-M1/M2`），而两处清单里都没有它们 → 改这两个文件**一条「证据过期」提示都不会有**
（同一个盲区第 4 次出现）。复现探针 `probe_fingerprint_gap_v290.py`：补前 **20 个锚点文件 / 84 条变异**零提示，
补后 **18 个 / 46 条**（残留的都是 `pet_io.py` / `pet_widgets.py` / `requirements.txt` 这类非「关键文件」）。
`pet_balance.py` 那次是典型盲区：A-1 改的正是它、3 条锚点随之失效，而清单里没有它 →
**发布门一条"证据过期"都不会提示**。两份清单（`_check_release.MUTATION_FINGERPRINT_FILES` 与
`_dev/_mutate_lib.repo_fingerprint`）由 `tests/test_release_check.py` 的清单一致性用例钉住，
且**逐项点名**必须有那 5 个文件（`pet_balance.py` + 四个新模块）。

**"缺键"提示（v2.6.0 · 代理 C）**：把清单补到 11 个**救不了已经在盘上的老证据**——
`stale_fingerprints()` 只比对"记录里存在的键"，于是那 14 份 7 键的老 JSON 里
`pet_plugin.py` / `pet_plugin_host.py` / `pet_dialogs.py` / `pet_menu.py` **等于不存在**：
改这四个文件，发布门一条提示都不会有（补清单那次留下的后半截盲区）。现在
`mutation_evidence_notes()` 会**汇总一句**点名"哪几份证据缺哪些键"（`missing_fingerprint_keys()`，
判据只认**当前树里真的存在**的文件）：

* **只提示、不挡发布**（与"指纹过期"同一条 notes 通道）；
* 汇总成**一行**而不是一份证据一行——实测那是 14 行噪音，结论完全一样；
* 影响面（2026-10-12 v2.6.0 实测，脚本 `_dev/probe_fingerprint_gap_v260.py`）：**14 份**证据各缺
  4 个键；同轮**17 份**证据处于"指纹过期"（多路并行改树窗口里的正常中间态，定版前统一复跑即可）。
  要消掉缺键那条只有两条路：**重跑对应 spec 让指纹补齐**，或在报告里**点名"这份证据不覆盖这几个
  模块"**（两者都行，但必须选一个——不许当作没看见）。

**基线为什么要重跑几次**：`run_baseline()` 在基线红时会重跑（最多 3 遍，间隔 3s）。原因不是放水，
而是时序敏感的用例在"影子副本刚复制出来 = 冷缓存 + 机器上还有别的会话在跑 pytest"时会偶发红：
`tests/test_startup_defer_v242.py::test_startup_task_is_chunked_not_one_shot` 断言"启动分片单轮 < 60ms"，
实测冷缓存首轮出现过 96.4/70.3/97.2 ms → 基线 1 failed，紧接着重跑就 0.55~0.99s 全过。
变异**本身**的判定仍然严格：rc==0 就是 NOT CAUGHT，收集期就炸才算 INVALID。

spec 清单（**状态列的 CAUGHT 数 = 该文件 `results` 段当前的实测值**，与 `checked_at` 同一轮）：

| spec | 覆盖 | 状态（2026-10-11 v2.4.4 复跑） |
|---|---|---|
| `mutations_q_item1.json` | M-Q1..Q4 顶层未知键保留（pet_alarm / pet_behaviors） | 4/4 CAUGHT |
| `mutations_q_item2.json` | M-Q5..Q9 GBK 回退读（pet_lines 薄壳 → pet_io.read_json_fallback；收口时实现刚被搬到 pet_io，锚点已同步） | 5/5 CAUGHT |
| `mutations_q_item3.json` | M-Q10..Q15 语音/错误文案等 | 6/6 CAUGHT |
| `mutations_compat_v242.json` | M-C1..C15 v2.4.2 兼容修复 | **15/15 CAUGHT**（M-C9 此前记 WRONG TEST：参数化实例确实红了、是判定口径没认出来；v2.4.4 修完 `_short` 后按基名比对 → CAUGHT，见下方"参数化后缀"一条） |
| `mutations_release_door.json` | G-D1/G-A1/G-L1 发布门新判据（D 条目 / 素材清单 / 变异锁） | 3/3 CAUGHT |
| `mutations_round3_a.json` | 另一路代理的 v2.4.2 第三轮 spec（同一套机制） | **16/16 CAUGHT**（v2.4.4 已重锚：M-A1 钉 `if not handed: self._retire(...)`、M-A2 钉顶层 except 的 `handed = self._emit("balance_err", gen)`，两个改名后的用例节点同步更新；2026-10-12 第 4 轮复跑 16/16，M-A13 重锚：pet_tools.py 注解数 39→41） |
| `mutations_relay_v243.json` | **v2.4.4 收口主 spec**：启动接力 / 撒钱预载分片 / SND_PURGE（M-R1..M-R15）＋ A-1 余额请求代次 / A-2 状态图死名单 / C-2 分片判据去墙钟（M-V1/V2/V3/V4/V5/V6/V7/V8）；钉 `tests/test_relay_v243.py` + `tests/test_round3_a_fixes.py` | **23/23 CAUGHT**（v2.4.4 补三条：M-V4 自动轮询不许有手动反馈 / M-V7 `_retire` 的代次守卫 / M-V8 切片预算放宽 8 倍必须红；M-V1/V2/V3 随 A-1、L2 重锚） |
| `mutations_asset_absence_v244.json` | 素材缺失降级：占位鱼 / 摸头缺帧 / 接力收口 / 撒钱空帧集与目录预检 / 自定义角色口径 / 合成回退音 / 状态图守卫 / 坏配置回落（M-A1..A9，钉 `tests/test_asset_absence_v244.py`） | 9/9 CAUGHT |
| `mutations_compat_v243.json` | 兼容审查 M1/M3/M4 + 质量审查 M1/M4/L2/L3 + 找茬复审 M1/M3/M5/L①（M-C1..C13） | **13/13 CAUGHT**（M-C10 此前 SPEC-BAD：锚点钉的是旧 `args=(key,)`；A-1 改代次后按 `args=(key, gen)` 重锚 → CAUGHT；2026-10-12 第 4 轮复跑 13/13，M-C12 重锚：旧锚点被 v2.6.0 新增的 `missing_fingerprint_keys` 复制成 2 处、命中 2 次即 SPEC-BAD） |
| `mutations_services_v250.json` | **v2.5.0 第 3 轮新增**：服务注册表（A1）构造顺序 + **实参级** golden + 摸头守卫（A3）——M-S1 wander/weather 顺序对调 · M-S2 WeatherService 的 signals↔lambda 对调 · M-S3 MenuBuilder 后两实参对调 · M-S4 mood 拆回字面 new · M-S5 A3 口径退回（不传组名） · M-S6 从 SYNC_FILES 删掉新模块 | **6/6 CAUGHT** |
| `mutations_dialog_fit_v250.json` | **v2.5.0 第 3 轮新增**：对话框尺寸与滚动（B）——M-D01..D12 **逐个**删掉 12 个类的设计尺寸 clamp · M-D13 自指比例 0.85→1.5 · M-D14 重钳兜底 · M-D15 下限保护 · M-D16 滚动容器 · M-D17 按钮行进滚动区 | **17/17 CAUGHT**（2026-10-12 第 4 轮复跑：M-D09 重锚——v2.5.1 A/L5 把设计宽 600→620，旧锚点自 v2.5.1 起静默失效，见 §零 铁律 5 的反面教材） |
| `mutations_plugin_v251.json` | **v2.5.1 代理A新增**：插件包校验器（M-P1 code 一致性 · M-P2 路径穿越 · M-P3 双版本门 · M-P4 禁止项清单 · M-P5 files 覆盖 · M-P6 容量上限复用 · M-P7 执行位 · M-P8 read_installed 不抛）· 发布门反向校验（M-R1 漏件必须报 · M-R2 AST 扫描不许空转 · M-R3 用户插件必须点名）· 安装器（M-H1 P1-1 保留名自保 · M-H2 S1-c already 必须以 landed 为准 · M-H3 S1-a 登记写失败回滚 · M-H4 P2-1 未落地内容必须点名）· M-P9 min_host_version 版本号判据 · L5 设计宽 620（M-L1） | **17/17 CAUGHT**（2026-10-12 第 4 轮复跑：M-H2/M-H3 重锚——v2.6.0 给 `_has_landed` 补了内容指纹参、登记失败的回滚调用收成无条件 `_unland`；2026-10-11 实测；M-P4/M-P8 首轮 NOT CAUGHT——M-P4 的"点名"被扩展名白名单分支同样满足、M-P8 的锚点钉在了走不到的分支上，都已重锚 + 收紧断言后复跑） |
| `mutations_plugin_gap_v260.json` | **v2.6.0 代理C新增**：校验器与安装器两处口径差收口（M-G1 Windows 非法字符 · M-G2 保留设备名 · M-G3 空 files · M-G4/G5 发布门"缺键"提示与纯函数 · M-G6/G7 文档↔常量双向契约 · M-G8 安装器不再交出校验器那句原因） | **8/8 CAUGHT**（2026-10-12 实测：`python -B _dev/mutate_check.py _dev/mutations_plugin_gap_v260.json`） |
| `mutations_plugin_c_v270.json` | **v2.7.0 代理 C 新增（插件线小账 a~d）**：M-C-a1 索引条目的 data_kind 与包自报不一致必须拒 · M-C-b1 当前版目录丢失而 .prev 在时保住回滚点 · M-C-b2 没有 .prev 就不留悬空回滚点 · M-C-b3 登记里没这条却留 .prev 则当孤儿清掉 · M-C-b4 登记写失败要回挪上一版目录 · M-C-c1 同内容折叠的回滚文案 · M-C-d1 razor 核对证据原文可查。钉 `tests/test_plugin_market_v270.py` | **7/7 CAUGHT**（2026-10-15 实测；原文证据见 `probe_c_mutation_output_v270.py` 与 `agent_c_v270_report.md`） |
| `mutations_agent_a_v280.json` | **v2.8.0 第 6 轮 代理 A 新增（25 条，由代理 C 收编入库）**：A1 索引来源区（地址校验/空地址拒/回退路径/重画列表/force 口径/后端结果/接线注入）· A3 `_toast` 行为层（早退返回 False / 兜底返回 / 限流日志）· A2/P2-5/P2-7/D9/D11/D14/N14/N15/P3-5/P3-6（静态输入框、合成框取消与接线、清除片段确认、各处回执、文案 tooltip）。id 沿用代理 A 的 `MA01~MA25`（便于与它的报告对账），`old`/`new` 由 `ast` 从它的 `%TEMP%` 驱动里原样取出 | **25/25 CAUGHT**（2026-10-15 实测：`python -B _dev/mutate_check.py _dev/mutations_agent_a_v280.json`；基线 23 条用例全过） |
| `mutations_agent_c_v280.json` | **v2.8.0 第 6 轮 代理 C 新增（97 条，三个来源合一）**：① **M-C-H01~H11** v2.6.0 远端硬化回退护栏（只收 https / 远端不许指本地 / Content-Length 前置 / 本地边读边判 / 注入容量兜底 / 解包前走校验器 —— 这 11 条此前**一条变异都没有**，是真空档）钉 `tests/test_plugin_market_v252.py`；② **M-C-B01~B48** B 的插件 Phase 3 / 配置键 / 先写盘再提交（`tests/test_plugin_phase3_v280.py` + `tests/test_ai_write_first_v280.py` + `tests/test_balance_feedback_v280.py`）；③ **M-C-A01~A40** A 的交互面（索引来源区 / 刷新 / `_toast` 行为层 / 合成框取消 / 静态输入框 / 文案对照表 / 各处回执与确认，`tests/test_dialogs_feedback_v280.py`） | **97/97 CAUGHT**（2026-10-15 实测：`python -B _dev/mutate_check.py _dev/mutations_agent_c_v280.json`；基线 70 条用例全过） |
| `mutations_agent_b_v280.json` | **v2.8.0 第 6 轮 代理 B（23 条；v2.9.0 第 7 轮由代理 C 从 `%TEMP%` 收编入库——上一轮这份 spec **根本没进树**，是补账）**：插件索引（远端基址校验 / 没注入 fetch 就不联网 / 缓存命中与 force 语义 / 索引落地 / 体积上限前置 / `source_url` 不串站点 / `.json` 直通 / 组合错误两条原因都说 / 主机名判据 / 解析不了不抛）· 配置归一（`plugin_index_url` 归一 / `DEFAULT_CONFIG` 少一行）· **先写盘再提交**（`set_api_key` / `set_ai_enabled` / `set_chat_rounds` / `talk()` 自动开开关 / 程序化同步勾选不 emit）· 账本反馈（构建失败可见 / 金额 ≤0 明说）。id 沿用 B 的 `M-B01~M-B23`，逐字收编（只加 title/note） | 见该文件 `results` 段（2026-10-15 当前树复跑） |
| `mutations_agent_b_v290.json` | **v2.9.0 第 7 轮 代理 B1（11 条 = B 交的 6 条 + 代理 C 独立补的 5 条）**：`pet_behaviors.action_choices` 的候选来源（空列表 / 漏 `custom_actions()` / 只摘 `ANIM_ACTIONS` 这一支 / `none` 未排除 / `getattr` 兜底 / `except` 收窄）+ 稳定排序（B1-M3 与其**确定性**版本 M-B290-07）+ `validate_steps` 不许变白名单（B1-M4 与同失败点的 M-B290-08） | **11/11 CAUGHT**（2026-10-15 实测：`python -B _dev/mutate_check.py _dev/mutations_agent_b_v290.json`；基线 7 条用例全过。⚠ M-B290-03 **首跑 WRONG TEST**——是代理 C 的 `expect_fail` 写宽了 2 条，已按实测改正，见该条 `why`） |
| `mutations_plugin_market_v260.json` | **v2.6.0 第 2 阶段新增**：插件市场（M-A01..A04 索引层 sha256 / 声明字节数 / 相对 url 解析 / host_min 可装性）· 按内容指纹合并与回滚（M-A05 指纹落账 · M-A06 去重失效 · M-A07 landed 累积 · M-A08 撤销本版新增 · M-A09 保留上一版 payload · M-A10 旧登记补账 · M-A16 同版本重复安装不顶回滚点 · **M-A17 `_fresh` 的 still_there 被摘掉：登记有账就当库里真有，库里缺的内容补不回来**）· 市场界面（M-A11..A15） | **17/17 CAUGHT**（2026-10-12 第 4 轮复跑；M-A17 是本轮**新增**的一条，与 M-A06 锚同一行、方向相反：M-A06 去重失效＝旧内容重复落，M-A17 去重过度＝缺的内容不补） |

**2026-10-15 v2.8.0 第 6 轮（代理 C）中间态记录 —— 不作发布依据。**
新入库**两份**：`mutations_agent_c_v280.json`（97 条，**97/97 CAUGHT**）与 `mutations_agent_a_v280.json`（25 条，**25/25 CAUGHT**，代理 A 的 `%TEMP%` 驱动由代理 C 收编）；同轮 `--scan-only` 报出 **7 条旧锚点已死**
（`agent_b_v270` S17-KEY-ERR / S17-TOGGLE-ERR / S17-ROUNDS-ERR · `critic_v270` M-R5-F4 / M-R5-F5 / M-R5-P3-2 ·
`compat_v243` M-C5），**全部重锚**（原因逐条写在各条的 `note` 字段里）：三处是 B 本轮把 `set_api_key` /
`set_ai_enabled` / `set_chat_rounds` 改成"先写盘再提交"造成的漂移，两处是 A3 改写 `_toast` docstring 造成的，
一处是 `new = dict(cfg)` 由 1 处变 3 处造成**命中 2 次**（歧义），一处是 `桌宠.py` 函数数 254→255。
重锚后 `--scan-only` = **417 条 / 坏 0**，`check_mutation_ast.py` = **392 条 / 0 不过**。
⚠ A/B 当时仍在改树：**这一批的用途只有"当前源码上每条变异都能被抓住"＋找出断裂锚点**；
定版必须按铁律 5 在安静窗口再整批跑一次。

**2026-10-15 v2.9.0 第 7 轮（代理 C）中间态记录 —— 不作发布依据。**
本轮 C 的三件事（详见 `_dev/agent_c_v290_report.md`）：
① **补录上一轮漏掉的 B spec**：`mutations_agent_b_v280.json` **23 条**（`M-B01~M-B23`）只落在 `%TEMP%\b_mutations_v280.json`，
   本轮逐字收编入库；旁证 = 同目录 `b_mut_out.txt`（B 当时的原始运行输出，23 条 rc=1 且 FAILED 的正是 spec 点名的用例）。
② **指纹清单 12 → 14**（补 `pet_ai.py` / `pet_config.py`）：全库 **40 条**变异的锚点在这两个文件上却零提示，是同一个盲区第 4 次
   （v2.4.4 `pet_balance.py`、v2.5.1 四模块、v2.6.0 `pet_plugin_index.py` 之后）。探针 `probe_fingerprint_gap_v290.py`：
   零覆盖锚点 **20 个文件 / 84 条 → 18 个 / 46 条**。⚠ 越界留痕：指纹一致性用例
   （`tests/test_release_check.py::test_fingerprint_file_list_matches_the_mutation_lib`）把两处清单钉成必须逐项一致，
   所以本轮**临时**在 `_check_release.py` 加了两个文件名字符串（**未改一行逻辑**，`pytest tests/test_release_check.py` = 37 passed）。
③ **本轮变异随做随落**：`mutations_agent_b_v290.json`（B1，11 条，11/11 CAUGHT）已入库；A 侧与 B 的 B4~B8 等它们落地后补。

`--scan-only` 现为 **锚点合计 496 条 / 坏 0**（471 条 spec 形态 + 25 条旧形态驱动）；nodeid 体检 **1141 个 / 坏 0**（体检当场抓出并修掉 1 条转述错的 nodeid）。
**A 批 28 条判定（收尾实测）**：**CAUGHT 23 / WRONG TEST 4 / NOT CAUGHT 1**——其中 2 条是**测试不够健壮挂死**（⚠ 本轮新增「**测试健壮性第一条**」规矩：被测路径可能弹真框的用例必须 stub `_confirm`/`_info`/`_warn`）、1 条是代理 C 的 `expect_fail` 写宽（已按实测改正）、1 条是**真覆盖缺口**（`_human_import_error` 被测、它的使用点没被测）、1 条是**判据口径缺口**（ERROR 行不算检出）。
**同轮还修掉 9 条被有意改写改死的旧锚点**（`agent_a_v280` MA18/MA19/MA22/MA23 · `agent_c_v280` M-C-A30/A31/A36/A37 · `critic_v270` M-R5-P2-4，其中 MA18/M-C-A30 是**语义反转**）＋ 2 条指向已改名用例的 nodeid（MA11 / M-C-A22）＋ 1 条历史笔误（`agent_a_v270` M-A-01 的 expect_fail 文件名）。
⚠ 三轮并行仍在改树：**本批只证明"当前源码上每条变异都能被抓住"**；定版按铁律 5 在安静窗口整批再跑一次。
**已知中间态（别误读成"证据坏了"）**：`_dev/*.json` 里 27 份有指纹段的证据当前全部报「过期 `pet_behaviors.py`」——
那是本轮 B 正在改 `pet_behaviors.py` + 本轮给清单补了两个新键造成的，定版整批复跑即消；本轮**不处理**。

**2026-10-12 v2.6.0 第 4 轮（出货修订 `bb73d5b`）整批复跑记录**：整批由人发起，报出 **5 条 SPEC-BAD**
（`compat_v243` M-C12 · `dialog_fit_v250` M-D09 · `plugin_v251` M-H2/M-H3 · `round3_a` M-A13），
**全部重锚后复跑**为 13/13 · 17/17 · 17/17 · 16/16；同轮给 `plugin_market_v260` 补了 M-A17 → 17/17；
三份旧形态单脚本同轮对齐 **5/5 · 8/8 · 9/9**；本轮回写的 7 份证据指纹**全部与当前树一致**。
这 5 条**全是锚点漂移**（不是护栏失效），其中 M-D09 是历史欠账——见 §零 铁律 5 的反面教材。

**2026-10-15 v2.7.0 整批复跑（代理 C）—— 并行窗口中间态，**不作发布依据**。**
起因：v2.6.1 的 anim_mode 修复改了 `桌宠.py`，于是 v2.6.0 那批复跑落下的**全部 20 份证据**
（不是此前以为的 2 份）指纹在 v2.6.1 定版那一刻就过期了。本轮用
`python -B _dev/mutate_batch_v270.py` 整批跑完 **22 项 / 268 条判定**，结果：
**SPEC-BAD 0 · ANCHOR-LOST 0 · WRONG TEST 0 · NOT CAUGHT 0 · INVALID 0 · BASELINE-RED 0**
（`mutation_verdict_notes()` 静默）；`results_fastci_slices_v251.json` 的**缺 `pet_plugin_index.py` 键**
也随复跑补齐（缺键提示一并消失）。
跑的过程里发现并修好 **3 条断裂锚点**（`plugin_market_v260` M-A09/M-A16、`plugin_v251` M-H3 ——
都是本轮 `install_zip` 重构造成的漂移），另有一条 M-H3 因重锚时 old/new 配错而**空转成 NOT CAUGHT**、
修正后 CAUGHT（教训：重锚要连 `new` 一起复核，见 `results_batch_v270.json` 的 `rerun_after_batch`）。
**但 A、B 当时正在改 `桌宠.py` / `pet_dialogs.py`**：跑前跑后指纹不一致（`fingerprint_moved`），
跑完后这两个文件又变了 → 发布门仍有 15 条"指纹过期"。
**所以这一批的用途只有一个：证明"当前源码上每条变异都能被抓住"＋找出断裂锚点；
定版必须在安静窗口用同一条命令再跑一次**（跑法见 §零 铁律 5）。

**2026-10-11 v2.4.4 证据对齐复跑**（真仓只读、逐个在 %TEMP% 影子里跑；本次总耗时约 255s）：上表
**9 个 spec 全部 rc=0、共 94 条变异 100% CAUGHT**；三条**不是** `mutate_check.py` 形态的结果文件
（`mutations_export_slice_v242.json` / `mutations_startup_defer_v242.json` / `results_guardrails_can_fail.json`）
由各自的单脚本驱动，同轮一并对齐（5/5 · 8/8 · 9/9）。**12 个结果 JSON / 116 条变异的指纹（7 个键，含 `pet_balance.py`）
全部与当前树一致**——发布门的 `mutation_evidence_notes()` 与 `mutation_verdict_notes()` 双双静默，
就是"这批证据对着这棵树"的机器判据。

**v2.5.0 第 2 轮勘误（代理 C 实测）**：上面"12 个结果 JSON 的指纹全部与当前树一致"**只在那批复跑的
时刻成立**——复跑在 11:05–11:09，而 `桌宠.py` 最后一次写入是 **11:17:18**（提交 `2a6563c` 里是
`aebe068e71de`），于是 12 个 JSON 记的 `dfb0cae9b8f9` 在定版那一刻就**全部**过期（v2.4.4 交接只承认了
其中 2 条）。第 2 轮三路并行又在改 `桌宠.py` 与 `_check_release.py`，所以：**指纹对齐只在对齐的那一刻
成立**。代理 C 本轮按任务书复跑了两条单脚本证据（`startup_defer` 8/8 · `guardrails_can_fail` 9/9，实耗
47.7s / 10.1s），第二条跑的**过程中** `桌宠.py` 又变了两次（`ed9e8f6df365` → `ce950ac96e11`）——
结论：**12 条等三路都落地后统一复跑一遍**（9 个 spec 各 15–45s + 3 条单脚本驱动，整批约 4–5 分钟），
否则发布门会一直挂 12 条"指纹过期"提示。

**v2.5.0 第 3 轮（找茬审查 → 修复）证据变更**（2026-10-11，三条"证据骗自己"）：

1. **`startup_defer` M7 重锚**：A3 把那行改成 `self._ensure_default_frames(self._startup_frame_sets())`
   并在上方插了 5 行说明注释，旧锚点（连注释一起钉）匹配 **0 次** → 按设计记 `ANCHOR-LOST`，
   而这条变异守的**正是 A3 改的那一行**（等于 A3 一直没有变异证明）。重锚成"只钉调用行本身"
   （唯一、且不随注释 churn 失效）后复跑：**8/8 CAUGHT、0 ANCHOR-LOST**，
   `mutation_verdict_notes()` 与 `mutation_evidence_notes()` 双双归零（14:54 实测）。
   A3 的**口径**（传不传组名）另由 `mutations_services_v250.json` 的 M-S5 专钉。
2. **两批"没有可复跑产物"的证据落库**：此前 10 个 `mutations_*.json` 里**没有任何一条锚点**
   落在 `pet_dialogs.py` / `pet_services.py`（grep `clamp_dialog` / `ServiceRegistry` = 0 命中），
   而发布说明写着"对话框 7/7、注册表 4/4" —— 唯一出处是 `dialog_size_report.md` 里一句
   "DETECTED"。现在两批 spec 都入库（各带 `repo_fingerprint`，走 `mutate_check.py` 同一套判定）。
3. **AST 实参对照脚本入库**：`verify_services_ast_v250.py` —— 发布说明里那句
   `compared=16 / mismatches=0` 此前**全仓没有对应脚本**（grep `compared=` = 0）。它比旧
   `__init__`（git `2a6563c`）与新 `pet_services.py` 的每一处构造实参（位置实参保序、关键字按名），
   `--selftest` 现场验"对调两个实参一定报差异"；当前实测 `compared=18 mismatches=0`
   （18 = 注册表首段 16 条 + build_anim/build_mood 各 1 条；另外三处没搬的仍在 `__init__`）。

至此 `_dev/*.json` 共 **14 个结果文件 / 139 条变异**：全部 CAUGHT，指纹全部对齐当前树，
发布门的 `mutation_evidence_notes()` 与 `mutation_verdict_notes()` **双双为 0**
（15:10 复核；"发布门 0 问题"这句话现在成立——此前 `startup_defer` 挂着一条 ANCHOR-LOST）。

**D7-A（代理 C · v2.5.0）的定向变异验证**：`_dev/verify_d7a_v250_agent_c.py` —— 把三条改动逐个拿掉，
`tests/test_d7a_v250_agent_c.py` 必须变红。**实测 6/6 检出**（keep_source 补的日志 / 限流窗口 / 形参进 bad /
diff 未知键带回 / pet_fx 重新写死帧集 / README 口径说明被删）。它**不产出结果 JSON、不记指纹**：这三条是
"补日志 + 收紧静态检查 + 写口径"，不属于 `mutations_*.json` 那套需要复跑的指纹证据。

**判定口径的两条已知伪红 + 一条已知偶发红**（复核 `results` 时先看这里，别当成回归）：
1. ~~**参数化后缀**~~ **v2.4.4 已修**：pytest 的 FAILED 行写的是 `test_x[param-id]`，此前 `_short()` 只切 `::`
   与空格、**不剥 `[...]`** → spec 里写不带参数的节点名就找不到它、判 `WRONG TEST`（`mutations_compat_v242`
   的 M-C9 就是这种：`test_undecodable_index_is_backed_up_before_first_write` 的 behaviors 参数化实例确实红了）。
   现在 `_short()` 剥后缀且比对按**基名**，复跑后 M-C9 = CAUGHT。防回归：
   `tests/test_mutate_harness_v244.py`（其中一条**真跑一个参数化用例**、再从 pytest 输出里抽失败名）。
2. **锚点跟着实现搬家**：源码重构会让 spec 的 `old` 片段匹配 0 次 → `SPEC-BAD` / `ANCHOR-LOST`。
   这**不代表护栏失效**，只代表"这条还没验证"，必须重锚后重跑。v2.4.4 重锚了 5 处：
   `round3_a` M-A1/M-A2（A-1 换代次）、`compat_v243` M-C10（`args=(key, gen)`）、`relay_v243` M-V3
   （L2 把 refresh 改成 `getattr` 防御读）、`export_slice` E3（固定时间戳 ZipInfo）、`startup_defer` M6
   （补 `not self._custom_role and` 前缀）。
3. **偶发红会被记成 CAUGHT**（不是伪红，是方向相反的风险）：pinned 用例自己偶发抖红时，rc≠0 且它在
   `failed` 里 → 这条变异被记成 CAUGHT，而其实什么都没验证。已知一例：
   `tests/test_relay_v243.py::test_stop_voice_clip_uses_modern_stop_flags`（1/15，审查实测；它同时是
   `mutations_relay_v243.json` M-R1 唯一 pinned 的用例）。复核 M-R1 时留意 `tail` 里的失败数与
   实际变异是否对得上；要彻底消除得让这条用例的判据不依赖播放时序。

---

## 二、探针（**只读测量**，不改产品代码）

| 脚本 | 量什么 |
|---|---|
| `probe_startup_cost.py` | `PetWindow()` 构造里每一段的实测占比（`--runs N --json out`） |
| `probe_export_cost.py` | `export_bundle` 各段占时（zip 写盘 vs 读取 vs 其它） |
| `probe_export_io.py` | 导出耗时归因（二）：首次读盘 vs 缓存命中 |
| `probe_ui_freeze.py` | UI 卡顿探针 v2（计数器插桩；它的 json 输出未入库） |
| `repro_frame_freeze.py` | 可复现的 UI 卡顿测量：每个卡点主线程被连续占住多久 / 事件循环真的卡住了吗。结果按 label 追加进 `_dev/ui_freeze_raw.json`（gitignore） |
| `probe_asset_absence.py` | **素材缺失探针**：临时资源根（`main.app_dir` 指到 %TEMP%）上构造 PetWindow，逐条打印"缺素材时各消费点的返回值/异常"——真实 `assets/` 全程只读。用户可感知的降级清单见 `asset_absence_report.md` |
| `probe_money_preload_gap.py` | **撒钱预载的事件循环缺口**：eager（v2.4.2 原样：一次同步解 86 帧）vs sliced（当前：按 _FRAME_SLICE_MS 分片），**每轮一个新进程** + 1ms PreciseTimer 心跳、交替采样（`--rounds N --json out`；`--repo <树>` 可量别的检出）。摘要见 `money_preload_summary.json` |
| `probe_test_order.py` | **反序探针**（pytest 插件）：把 `tests/test_export_slice_v242.py` 挪到收集顺序最前/最后，用来判定"这些红是不是被别的模块污染"——顺序无关的失败才是真失败 |
| `probe_plugin_gap_v260.py` | **校验器/安装器口径差复现探针**（v2.6.0 代理C）：造 4 个曾被校验器放行的合成包（`payload/a:b.png` / `payload/con.png` / `files: []` 两种形状）+ 1 个控制组，逐条打印"校验器怎么说 / 安装器怎么说 / plugins/ 下有没有残余"。收口前后各跑一次就是证据（收口前：校验器全放行、安装器才拒；收口后：两侧同一句原因、零残余） |
| `probe_fingerprint_gap_v260.py` | **发布门"缺键"影响面探针**（v2.6.0 代理C，只读）：逐份打印 `_dev/*.json` 记了几个键 / 缺哪些键 / 哪些指纹过期，再打印 `mutation_evidence_notes()` 当前返回的每一条提示 |
| `probe_fingerprint_gap_v290.py` | **锚点文件 ↔ 指纹清单的覆盖面探针**（v2.9.0 第 7 轮代理C，只读）：把两种"判不了过期"分开打——① 逐份 spec 收 `file` 字段，列出**不在指纹清单里**的锚点文件（改了它＝零提示，真盲区）及其变异 ID；② 逐份证据 JSON 的缺键 / 过期；③ 当场对一遍两处清单是否逐项一致。补 `pet_ai.py`/`pet_config.py` 前后各跑一次就是 C-2 的证据（84 条 → 46 条） |

---

## 三、A/B 对照（基线与当前，交替成对采样）

| 脚本 | 说明 | 复跑 |
|---|---|---|
| `compare_startup_baseline.py` | 启动耗时 A/B，交替跑基线/当前抵消负载漂移 | `python _dev/compare_startup_baseline.py --baseline "<基线树>" --rounds 5 --json _dev/startup_ab.json` |
| `compare_export_baseline.py` | 导出包 A/B：条目名/顺序/结构/解压后内容逐条比对 | `python _dev/compare_export_baseline.py --baseline "<基线树>"` |
| `export_fingerprint.py` | 导出指纹（被上面那个在两边各调一次） | `python _dev/export_fingerprint.py --repo <树> --out <json>` |

**摘要（入库）**：`startup_ab_summary.json`（10 轮交替：init_ms 中位 102.9 → 46.9 ms）、
`export_ab_summary.json`（25 条目：order / entries / manifest 三者全等）。原始 json 不入库。

**基线树已删，但基线 commit 现在写死了**（v2.4.3 · 兼容审查 L2）：基线是
**`eb7b590c7b4e9721d25632f1cd15ea9c97a70866`**（`eb7b590`，"v2.4.1 文档更正"，2026-10-10
20:59:29 +0800）——worktree 删了、仓库里没有它的 ref，这个结论是**复核出来的**：`%TEMP%` 里
留存的 `wt-p-baseline-uncommitted-20261010-224443.patch`（7 个文件的 688+/96- 适配改动），
其 7 个 `index` 旧侧 blob 与 `git rev-parse eb7b590:<路径>` **逐条相等**。同样的字段
（`baseline_commit`）也写进了 `startup_ab_summary.json` / `export_ab_summary.json`，
两个摘要里还各记了 7 个**适配文件**的 sha256 前 12 位（当前主线版本）——重跑 A/B 前先核一遍，
不一致说明适配漂了。重建命令：`git worktree add ../wt-p-baseline eb7b590`，再把不参与改动的
文件抄齐（见脚本 docstring）。

---

## 四、一次性复现脚本（GUI / IO，无参数；跑完看 stdout 的断言与打印）

- `e2e_double_feed.py` 重复投喂；`e2e_full_form.py` 吃饱形态链路；
  `e2e_idle_and.py` / `e2e_idle_or.py` 待机动作与/或；`e2e_idle_v218.py` v2.1.8 待机动作
- `repro_default.py` 默认角色；`repro_4form.py` 四形态角色；`repro_full_user.py` 完整用户流程；
  `repro_idle_actions.py` 待机动作；`repro_mood.py` 情绪；`repro_quiet.py` 喂食时间轴相位无关验收；
  `repro_io_conflict.py` 并发写盘"静默丢失"（v2.3.1 发布说明引用的那组数字）

**别改名**：`e2e_full_form.py` / `e2e_idle_and.py` / `repro_io_conflict.py` 被测试引用
（`tests/test_io_v231.py` 的 A7/A8 会检查它们的负载注释与定时退出写法）。

---

## 五、语义重复定位（只读分析）

| 脚本 | 判据 |
|---|---|
| `find_dup_tests.py [相似度]` | AST 取 `test_*` 函数体，归一化后算文本相似度 |
| `find_dup_tests_api.py` | 按"用例触碰的 API 面"聚类，不看文本 |
| `find_dup_symbols.py` | 按被测符号分组：同一符号被多少文件/用例覆盖 |
| `find_dup_claims.py` | 比较**断言形态**（根对象名忽略、常量保留） |
| `audit_silent_except.py` | 静默 `except` 分类审计（A 档计数；只读分析） |

---

## 六、入库的报告与摘要

| 文件 | 是什么 |
|---|---|
| `audit_A_tier_review.md` | 静默 except A 档审计报告 |
| `asset_absence_report.md` | **素材缺失降级报告**（v2.4.4）：逐条列"缺素材时各消费点返回什么/用户看到什么"；配 `probe_asset_absence.py` + `mutations_asset_absence_v244.json` |
| `qt_strip_report.md` | **Qt 精简实验报告**（v2.4.4）：绿色版裁 Qt 的可行性与实测；§7.1 是**铁律 1** 的原始证据（那次越界往绿色版写了 14 个 .pyc） |
| `parasite_plugin_study.md` | **寄生 / 插件形态调研**（v2.4.4）：外部项目对照 + 我们 README 的可落地改动清单；是调研产物，不是本轮要执行的活 |
| `task_v244.md` | v2.4.4 第 1 轮任务书（A-1/A-2/C-2/C-3 + 两条铁律 + 硬性要求）——**历史留档**，别当成现行指令读 |
| `ui_freeze_report.md` | UI 卡顿修前/修后对照表（数字原文；配 `ui_freeze_summary.json`） |
| `startup_ab_summary.json` | 启动 A/B 摘要（每侧 10 轮：min/median/max + 解码数 + 首屏标志） |
| `export_ab_summary.json` | 导出 A/B 摘要（条目数 + order + 三项全等判定） |
| `ui_freeze_summary.json` | UI 卡顿摘要（按 label：n / worst_gap_ms / 中位 / 最慢 6 个场景） |
| `money_preload_summary.json` | 撒钱预载缺口摘要（4 轮交替、每轮新进程：eager 中位 70.9ms / sliced **单片** 12.3~12.6ms、**事件循环间隔**中位 25.5ms、入口 0.0ms、5~6 片、86/86 逐张 toImage 全等）。注意单片与循环间隔不是一回事，口径见该文件 `interpretation` |
| `pytest_v242_full.txt` | v2.4.2 定版那次全量的原始输出尾巴（632 passed）——提交信息引用它，别删 |
| `pytest_v243_full.txt` | v2.4.3 全量输出（`python -m pytest tests -o addopts="" -q` → **691 passed / 0 failed**，65.4s；连跑两次同结果）。定版提交信息引用它 |
| `plugin_packs_report.md` | **官方内容插件与索引**（v2.5.1 代理 C）：5 个包逐类"能不能落地"的实测证据 + 26 条反向变异清单 + 踩坑与发货注意。配 `build_official_plugins.py`（打包，幂等）· `plugin_pack_rules.py`（12 条判据参照实现）· `verify_plugin_packs_v251.py`（验收：正向 + 反向 + 索引 + 上架门槛 + 幂等；v2.6.0 加了两条真 zip 反向与 6 条单元级交叉核对 → **70 条**）· `probe_plugin_landing_v251.py`（五类宿主接口落地，29 条）· `probe_plugin_install_v251.py`（索引→包→真安装器→宿主库端到端，20 条）。**§九 是 v2.6.0 增量**（口径差收口 + 70/70 + 8/8 变异），§七/§八 的 890 是历史读数，**基线以当轮实测为准** |
| `agent_c_v260_report.md` | **v2.6.0 代理 C 完工报告**：校验器/安装器两处口径差收口、发布门"缺键"提示、文档同步（12 条判据文档 / plugins README / 基线数字）、两条新铁律的落地位置。含"没做到/有疑问"一节 |

**v2.4.4 三项硬性门实测（2026-10-11 A-4 复跑，未提交树）**：`python -m pytest tests -o addopts="" -q` →
**716 passed / 0 failed**（104.89s）· `python _verify_v13.py` → **273 项 / 0 FAILS**（27.9s）·
`python _check_static.py` → **问题 0 条 / 待确认 0 条**（单跑，107.8s）。原始输出在 gitignore 的
`_dev/_v244_final_gates.log`；**定版时**再按 `pytest_v24x_full.txt` 的口径把尾巴留档入库（现在不落 txt：
它会被 `!_dev/pytest_*_full.txt` 白名单放行 → 变成未跟踪文件 → 撞发布门的"未跟踪"判据）。

`gen_full_idle_frames.py` 是**素材生成器**（`assets/character_full.png` → `assets/idle_full_f00..f09.png`），
不是探针：`tests/test_full_form_frames_v24.py` 会按路径加载它并逐像素比对，**别改名**；
`python _dev/gen_full_idle_frames.py --check` 可单独校验素材是否被手改过。

---

## 七、已删除（2026-10-10 第三轮收口，被取代/已降级为摘要）

- `startup_before.json` / `startup_after.json`：非交替样本（同一棵树连测，会被负载漂移骗）→ 由 `*_ab_summary.json` 取代
- `export_payload_drift_before_NOT_AB.json` / `_after_NOT_AB.json`：文件名自己标了"非 A/B"→ 删
- `ui_freeze_raw.json` / `startup_ab.json` / `export_ab.json`：原始逐轮/逐条目数据 → 摘要 + 复跑命令，原始文件已 gitignore
- `__pycache__/`：编译缓存

### 候选清理（2026-10-11 A-4 清点：**只列不删**，等人类决定）

| 候选 | 为什么算过期 / 多余 | 建议 |
|---|---|---|
| `_dev/__pycache__/` | 编译缓存；跑一次 `python _dev/xxx.py` 就重建（加 `-B` 则根本不生成），`.gitignore` 覆盖 | **删**（零损失） |
| `mutate_export_slice.py` / `mutate_startup_defer.py` / `verify_guardrails_can_fail.py` ＋ 它们的三份结果 JSON | `mutate_check.py`（spec 驱动、结果带 `failed` 列表、判定口径 M5）之后的**旧形态**：一脚本一套变异，结果条目没有 `failed`，判定比现在松 | 先把三套并成 `mutations_*.json` 再用 `mutate_check.py` 统一跑，**并完再删**；现在它们还是那三块证据的唯一来源 |
| `e2e_idle_v218.py`（文件名自带 v2.1.8）· `e2e_idle_or.py` · `e2e_double_feed.py` · `repro_default.py` · `repro_4form.py` · `repro_full_user.py` · `repro_idle_actions.py` · `repro_mood.py` | v2.1.x 的人工一次性复现脚本，**没有任何测试引用**；场景已进 pytest（待机动作 `test_behaviors_v21.py` / `test_p3.py`、四形态 `test_full_form_frames_v24.py::test_custom_role_four_form_rules_unchanged`、情绪 `test_mood.py`、喂食链路 `test_state_invariants.py`） | 可删；留着只剩"真机 GUI 人工复核"的价值。⚠️ `e2e_full_form.py` / `e2e_idle_and.py` / `repro_io_conflict.py` **被测试引用，别动** |
| `probe_test_order.py` | v2.4.2 那次"疑似测试污染"的一次性反序探针，结论已写进 §七附与 `_mutate_lib.py` | 可删；当通用"收集顺序"排查工具留着也合理（优先级最低） |

> **别删**：`pytest_v242_full.txt`（v2.4.2 提交信息引用它）· `pytest_v243_full.txt`（v2.4.3 定版证据）·
> `*_summary.json`（原始逐轮数据已 gitignore，摘要删了就得重测）· `mutations_q_item1/2/3.json`（Q 条目唯一证据）·
> §六 的调研报告（`qt_strip_report.md` / `parasite_plugin_study.md` 里还有没执行的建议）。

### 附：本轮那次"看似测试污染"的复盘（为什么要影子副本）

2026-10-10 第三轮收尾时，有审查员在树里看到 `test_export_slice_v242` 的 3 条红，第一反应是
"测试污染"。实际是两个因素叠加：① `assets/idle_f03.png` 被外部脚本删掉（工作树出现 ` D` 条目，
而探针的"首屏 9 帧非空图"照样 PASS）；② 变异脚本正在**原地覆写** `pet_export.py`。
`probe_test_order.py`（反序证明）与 `_mutprobe/hold_e2.py`（在副本里按住 E2 变异再跑全量，
复现 608 passed / 3 failed，`--ignore` 掉该文件则 605/0）都用真数据排除了"收集顺序污染"这一解释。
两个临时探针目录随后已删；`_mutate_lib.py` 的 `%TEMP%` 影子副本 + 运行锁就是这次事故的产物，
`_check_release.py` 新增的"D 条目单独点名 / 素材清单完整性"两条判据同样来自它。

## 八、测试环境陷阱（省得下一个人再踩）

**offscreen 下字体库是空的**：`QT_QPA_PLATFORM=offscreen` 时 `QFontDatabase.families() == 0`，
`QFont(...).family()` 拿回 `'Sans Serif'`、`inFontUcs4(0x4E2D) == False`。也就是说
**字体回退 / 字体链接的行为在测试里覆盖不到**——只能靠 AST 守卫钉源码形态
（`tests/test_round3_a_fixes.py` 的 `test_no_shipped_source_hardcodes_a_single_font_family`、
`test_dialog_qss_uses_the_single_source_fallback_chain`、
`test_font_fallback_mechanism_comment_is_hedged`），行为验证只能在真机（默认 windows 平台）上做：
实测 `QFont("No Such Font XYZ")` 的 `exactMatch()` 为 False，但 `inFontUcs4(0x4E2D)` 仍是 True、
advance("中") 仍是正常宽度——Qt 自己做字体链接，所以"候选全不可用"未必等于豆腐块。

**别在测试里调 `QRawFont.fromFont(<无法解析的 QFont>)`**：审查实测它在 offscreen 下会让
**整个 pytest 进程段错误**（`0xC0000005`）。本机复核时试过一例没有触发（可能与调用点/Qt 状态
有关），但代价不对称：一次崩溃 = 一次全量结果作废。要验字体行为就单独写一次性探针。

## 九、v2.4.3 留到 v2.4.4 的三条 —— 现状（2026-10-11 更新）

| 条目（v2.4.3 原文） | 现状 |
|---|---|
| **复审 M2**：`pet_balance` 的 `_fetching_balance` 由 worker 的 finally 复位，槽还没跑时用户再点一次会真起第二个并发线程（探针实测 started==2；过后反馈会落到别的结果上 = 重复/错配） | ✅ **v2.4.4 已修（A-1）**：`_fetching_balance` 布尔 → **请求代次**（`_balance_gen` / `_balance_active_gen`）；在途只在**槽消费完那一代**（或结果交不出去时的 `_retire`）才清空，旧代迟到结果丢弃并记一条日志。证据：`mutations_relay_v243.json` 的 M-V1/V2/V3 + 新增 M-V4（自动轮询无手动反馈）/ M-V7（`_retire` 代次守卫）（钉 `tests/test_relay_v243.py` + `tests/test_round3_a_fixes.py`）。**锚点已重锚并复跑**：`round3_a` M-A1/A2、`compat_v243` M-C10、`relay_v243` M-V3（见 §一） |
| **复审 M4**：状态图分片的"零推进自锁"整表清空 pending，异常后那个状态永久缺图 | ✅ **v2.4.4 已修（A-2）**：改成"只摘掉**真正试过且没建出来**的名字"（死名单），pending 里没试过的留到下一轮；异常一次后恢复方法再调 `_state_pix` 仍能补建。证据：`mutations_relay_v243.json` 的 M-R12..M-R15（M-R8 也已按内联实现重锚） |
| **复审 L④**：`pet_fx.py` 的 86 / "money" 仍是写死的（"单一来源"只在 `桌宠.py` 内成立） | ✅ **v2.5.0 做了"文档与自测不再写死"（A-3 · 代理 C）**：模块 docstring 改成指向 `桌宠.py` 的具名常量（`_MONEY_FRAME_PREFIX` / `_MONEY_FRAME_COUNT` / `_DEFAULT_FRAME_SETS`），`__main__` 自测新增 `pet_fx.frame_sets(assets/fx)` **按磁盘实况数**前缀与张数（长帧集的等待时间也跟着实际张数走，不再写死 3400ms）。**没有真单源化**：那要动 import 方向（`pet_fx` 被 `桌宠` import），本轮不做——所以真源仍是"素材本身 + 桌宠.py 的常量"，由 `tests/test_d7a_v250_agent_c.py` 的一条用例钉住"磁盘实况 == 桌宠.py 具名常量"（漂移即红） |

> **v2.4.4 已修的口径缺口**（上一轮暴露的，不是代码问题）：`_mutate_lib.repo_fingerprint` 的"关键文件"
> 清单里原本**没有 `pet_balance.py`** → A-1（改的正是它）不会在任何"证据过期"提示里出现，三条锚点失效
> 只能靠人跑出来。现在两份清单都补上了它（7 个键），并加了"点名的文件必须存在"的断言；发布门另加
> `mutation_verdict_notes()` 扫没通过的判定（SPEC-BAD / WRONG TEST / NOT CAUGHT / ANCHOR-LOST / INVALID /
> BASELINE-RED）。两处都在 `tests/test_release_check.py` 里有能真失败的用例。

> 找东西的捷径：`_dev` 里的 `.py` 都能单独跑（`python _dev/<名字>.py`，Qt 类的会自动 offscreen）；
> 会写文件的只有三类——`gen_full_idle_frames.py`（素材）、探针的 `--json` 输出、变异验证的结果 JSON。

---

## 记账更正（主代理 2026-10-15，依据 v2.8.0 质量审查）

**① `M-C-A*` 的 97 条不是 97 个独立信息点**：其中 **12 对与 A 的 `MA*` 同锚点**（`M-C-A04/12/14/15/18/19/25/28/29/31/36/37`）——锚点剥空白后逐字节相同、`new` 只差注释、`expect` 集合逐字相同。质量审查独立跑对照对（`MA01 ↔ M-C-A18`）结果**完全一样**。
**定性更正**：这 12 对**不提供独立验证**（"多一次独立验证"不成立，C 的论证站不住），它们提供的是**运行事故冗余**（本轮 C 真在某条桩上挂死过整批，A 名下那份没崩 → 消掉"一次事故连坐 12 条图钉"的单点故障）。**结论：保留，但账目分开写**——`M-C-A*` = 全新锚点 **28** + 与 A 同锚点 **12**。

**② 挂死风险那条已失效（回填）**：`tests/test_dialogs_feedback_v280.py::test_dialog_wires_cfg_read_and_write_into_the_backend` **已带 `quiet`**（`:475` 签名 `(tmp_path, quiet)`），A 是在自己的变异验证里发现会挂死后补的，当前修订复核**无挂起**。
**③ `audit_feedback_v270.md` §5.1 登记 1 的定性要改**：原文写"等价变异（后面的『只收 https』判据会把同批样本拒掉）"——**理由说反了**：`pet_plugin_index.py:130` 在 `:134` **之前**，样本**先被 `:130` 拒**；删掉 `:130` 后由 `:134` 兜住，属**兜底等价（fallthrough-equivalent）**。真缺口是**措辞未覆盖**：用例只断言 `"https" in msg or "太长" in msg or "主机" in msg`，**不点名"本地路径"**——而 `:130-133` 存在的唯一意义就是把措辞说具体。**修法**：补一条 `assert "本地路径" in msg`，该分支立刻有能真失败的变异。

**④ 冻结读数**：冻结时 `dirty=29`，事后读数是 31——多出的两条是本轮自己产生的未跟踪件（`_dev/review_task_v280.md` / `_dev/agent_c_v280_report.md`）。**7 个产品文件哈希逐项相符才是"冻结"的实质**。
---

## 锚点换行口径（2026-10-15 定，两个代理各踩一次反向坑）

**规矩：变异锚点一律用 `\n`，不要用 `\r\n`。**

**原因**：`mutate_check` 读源码走 `io.open(encoding="utf-8")` 的 **universal newlines**——文件里的 `\r\n` 会被**归一成 `\n`** 再与锚点比对。所以即使目标文件是 CRLF（例如 `pet_dialogs.py` 实测 7495 个 CRLF / 0 个裸 LF），**锚点也必须写 `\n`**。

**两次反向踩坑记录（防止第三次）**：
- 第 5 轮 B：锚点按**文件字节**切（用 `\r\n`）→ 命中 0 次 → 改 `\n` 后通过。**（结论正确）**
- 第 6 轮修复代理 D：看到 `pet_dialogs.py` 是 CRLF，**建议主代理把多行锚点写成 `\r\n`** → 主代理照做 → **3 条 SPEC-BAD（命中 0 次）**；改成 `\n` 后 **5/5 CAUGHT**。**（结论错误）**

**自查方法**：入库前先 `python -B _dev/mutate_batch_v270.py --scan-only`——锚点命中 0/2 次会当场报出来，不必等整批跑完。