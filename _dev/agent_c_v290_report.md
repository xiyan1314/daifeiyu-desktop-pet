# 代理 C · v2.9.0 第 7 轮报告（证据与记账）

- 领地：`_dev/**`（**未碰产品代码与 `tests/**`**；唯一的越界见 §2，已获批并留痕）
- 基线：HEAD `5ac99f0`（v2.8.0）· 本轮改动全部**未提交**
- 口径：所有判定都由代理 C 在**全新影子副本**里独立跑出（`_dev/mutate_check.py`），**不采信任何人的自述**；
  锚点一律 `\n`（运行器 universal newlines）

---

## 0. 一句话

本轮 C 的四件事都落地了：**补录 B 上一轮丢失的 23 条 spec（并复跑 23/23 CAUGHT）** ·
**指纹清单 12 → 14（补 `pet_ai.py` / `pet_config.py`）** · **本轮变异随做随落（B 23 条 23/23 CAUGHT；A 13 条已落、待 A 全量转绿后复跑）** ·
**公开清单与份数按实测更新**。顺带抓出并修掉 **9 条被有意改写改死的旧锚点**、**2 条指向已改名用例的 nodeid**、
**1 条同族的历史笔误**，并把两条体检（锚点 / nodeid）与两条规矩写进 `_dev/README.md`。

---

## 1. C-1：补录 B 的 23 条变异（上一轮的缺口）

**事实**：上一轮 B 自述的 23 条**只落在 `%TEMP%\b_mutations_v280.json`**，`_dev/mutations_agent_b_v280.json`
**根本不存在**（任务书点名）。本轮**逐字收编**入库（只加 `title`/`note` 两个头部字段，`id/why/file/old/new/tests` 一行没改）。

**旁证**（不是我编的）：同目录 `%TEMP%\b_mut_out.txt` 是 B 当时的原始运行输出，
**23 条全部 rc=1，且 FAILED 的用例正是 spec 里 `tests` 点名的那些**（逐条对上）。

**核验**（本轮实测）：

| 检查 | 结果 |
|---|---|
| `--scan-only` | 23 条锚点**全部命中恰好 1 次** |
| `check_mutation_ast.py` | 23 条 / **0 锚点或语法问题** |
| `mutate_check.py`（当前树，影子副本） | **23/23 CAUGHT**、not_caught 0、blocked 0（`results` 段已回写，含 **14 键**指纹） |

---

## 2. C-2：`pet_ai.py` / `pet_config.py` 进指纹清单（12 → 14）

**为什么要**：`repo_fingerprint` 记的是"证据是对着哪份源码测的"。这两个文件此前不在清单里 →
**改它们，发布门一条"证据过期"提示都不会有**（同一个盲区第 4 次：v2.4.4 `pet_balance.py`、
v2.5.1 四模块、v2.6.0 `pet_plugin_index.py`）。

**实测规模（本轮新增探针 `probe_fingerprint_gap_v290.py`，可复跑）**：锚点落在这两个文件上的变异
**全库 40 条**（`pet_ai.py` **31** / `pet_config.py` **9**）——任务书写的"16 条"是**代理 C 自己那 16 条**
（`M-C-B30~B39` 十条 + `M-C-B08/09/29/40/41/42` 六条），全库口径见探针输出。

| | 补清单前 | 补清单后 |
|---|---|---|
| 指纹键 | 12 | **14**（两处逐项一致） |
| 零覆盖的锚点文件 / 变异 | **20 个 / 84 条** | **18 个 / 46 条** |
| 残留（未补，**超出 C-2 点名范围，如实登记**） | — | `pet_io.py` 8 · `_dev/silent_except_whitelist.py` 5 · `pet_widgets.py` 3 · `requirements.txt` 3 · `pet_services.py` 3 · `tests/test_dialog_buttons_v270.py` 3 · `README.md` 3 · 其余 8 个文件各 1~2 条 |

**⚠ 越界留痕（已获批准的原话）**：**"本轮因指纹一致性用例的硬约束，临时在 `_check_release.py` 加两个文件名字符串，未改逻辑。"**
原因：`tests/test_release_check.py::test_fingerprint_file_list_matches_the_mutation_lib` 把
`_check_release.MUTATION_FINGERPRINT_FILES` 与 `_dev/_mutate_lib.repo_fingerprint` **钉成必须逐项一致** →
只改 `_dev/**` 会让共同验收的 pytest 变红。改动 = **两个文件名字符串 + 一段注释，零逻辑**。
核验：`python -B -m pytest tests/test_release_check.py -o addopts="" -q` → **37 passed**。

---

## 3. C-3：本轮的变异（随做随落，不等到收尾）

### 3.1 代理 B：`_dev/mutations_agent_b_v290.json`（23 条 = B 的 18 + C 独立补的 5）

- **B 的 18 条**（`%TEMP%\b_mutations_v290.json` 正式原料：B1 七 / B4 三 / B5 五 / B6 一 / B7 二）：
  `id`/`why`/`expect_fail` **逐字保留**。
- **C 独立补的 5 条**（`M-B290-*`）：候选恒空 / 只摘 `ANIM_ACTIONS` 这一支 / `except` 收窄成 `ValueError` /
  稳定排序的**确定性**版本（降序）/ `validate_steps` 用内建名集合当白名单。
- **独立复跑结果：23/23 CAUGHT**（`results.checked_at` 见文件；not_caught 0 / blocked 0）。
- **逐条对账**：把 B 每条 `expect_fail` 与本轮实测 `failed` 列表比 → **首次 0 不一致**（B 自述可信）；
  修掉我自己的一个连带错误后复跑，**23/23**。
- **记账口径**：`M-B290-03` ↔ B 的 `B1-M7`、`M-B290-08` ↔ B 的 `B1-M4` 是**同失败点**，
  **保留两条、账目分开写**——它们提供的是**运行事故冗余**（一条挂死不至于让这个失败点没有证据），
  **不是独立验证**（与 `README.md`『记账更正①』同一口径）。

### 3.2 代理 A：`_dev/mutations_agent_a_v290.json`（13 条）

| 组 | 变异 | 钉的用例 |
|---|---|---|
| A10 | `M-A290-04` 定义退回静态 `QInputDialog.getText` · `M-A290-05` **调用点绕过统一入口** | `test_dialogs_feedback_v280.py::test_static_input_dialogs_are_gone` |
| A11/D16 | `M-A290-01` 不再确认 · `M-A290-02` **问但不认取消** · `M-A290-03` 清完零回执 | `test_dialogs_v24.py::test_ai_settings_clear_long_term_keeps_history` |
| A1 | `A1-M1` 候选恒空 · `A1-M2` ★**回落第一条＝把未知名改掉**（UI 侧，与 B 的 `B1-M4` 数据侧**不是同一失败点**） | `test_dialogs_behavior_v290.py::test_action_param_*` / `test_typed_action_name_*` / `test_unknown_action_name_survives_load_and_save` |
| A2 | `A2-M1` 落点假装成功 · `A2-M2` 取消也当确定 | `…test_import_images_*` |
| A5 | `A5-M1` 去掉未保存确认 · **`A5-M2` ★反向：没改动也弹确认** | `…test_cancel_with_unsaved_edits_*` / `…test_cancel_without_edits_does_not_ask` |
| A6 | `A6-M1` **把删自定义动作的确认加回来**（有意撤销上一轮） | `…test_delete_custom_action_can_be_undone_by_cancelling` + `test_dialogs_feedback_v280.py::test_role_edit_delete_action_needs_no_confirm_and_is_undoable` |
| A4 | `A4-M1` 回执从内联状态行**改回宠物气泡** | `…test_step_receipts_use_the_inline_status_line_not_the_bubble` |

**第二批（15 条）已落盘**：A3-M1/M2 · A2-M3 · A7-M1/M2 · A9A11-M1 · A11-M2/M3 · A8-M1/M2 · B4-M1（UI 侧）· B5-M1/M2（UI 侧）· B6-M1/M2（UI 侧）——锚点**全部按现树自取、逐条验证命中 1 次**（A 本轮改写了 pet_dialogs.py 约 894 行）。

**状态（最终 · 已跑完）**：**28 条 / CAUGHT 23 / WRONG TEST 4 / NOT CAUGHT 1 / blocked 0**
（`results.checked_at` = 2026-10-16 00:02:28；**14 键指纹**，含本轮新补的 `pet_ai.py` / `pet_config.py`）。
**五条非 CAUGHT 的逐条定性已写进各自 `why`**，摘要见下。

**（历史）此前两次起跑都没跑完**：
两次起跑都没跑完：① 第一次撞上 A 的半成品状态（当时 `test_behavior_step_receipts` / `test_role_edit_delete_action_*` 还没转绿）；
② 第二次跑 **9.5 分钟仍未结束**，被**按协调协议主动终止**（A 要跑全量门，C 不持锁、不并发——理由：**争用下的红/绿都不可信**）。
**⚠ 不能断言是"挂死"**：stdout 被缓冲到进程结尾，看不到进度；而 `test_dialogs_behavior_v290.py` 的对话框用例本身很重
（每条变异 = 一个新 pytest 进程 + 影子副本导入 PySide6/桌宠），**13 条跑到 6–10 分钟是正常的**。
准确表述：**"跑了 9.5 分钟没有判定产出，按协议终止"**。
**复跑入口（安静窗口，一条命令）**：`python -B _dev/mutate_check.py _dev/mutations_agent_a_v290.json`
（若真是挂死，`mutate_check` 会把它折成 `rc=3` + 一句说明，判 WRONG TEST＝这条没被验证，**整批不会崩**）。

---

### 3.3 A 批五条非 CAUGHT 的定性（**都不是「护栏失效」，但一律不许当通过**）

| 变异 | 判定 | 定性 | 该谁动 |
|---|---|---|---|
| `M-A290-01` 不确认就清长期记忆 | WRONG TEST（rc=3 · 600s 折叠） | **测试不够健壮**：用例第一段只 stub `_confirm`，没 stub `_info`/`_warn` → 变异走到真 `modal(QMessageBox)` → offscreen 永久阻塞 | **A**：stub 三件套（2 行，加强式）→ 复跑转 CAUGHT |
| `M-A290-02` 问但不认取消 | 同上 | 同一根因的第二个受害者 | 同上 |
| `A1-M2` 回填时回落第一条 | WRONG TEST（rc=1） | **代理 C 的 expect_fail 写宽了**：实测只有 `test_unknown_action_name_survives_load_and_save` 红；`test_typed_action_name_that_is_not_a_candidate_is_kept` **抓不到**（它是「先设候选再手填」，不经过回填分支） | **C**（已按实测改正）；**A 顺手改那条 docstring 或补一条回填断言** |
| `A7-M2` 库层失败端英文异常 | **NOT CAUGHT**（rc=0 · 2 passed） | **真覆盖缺口**：`_human_import_error` 被**单测**了，但它在 `_import` 里的**使用点**没有任何用例钉住（另一条只走扩展名预检，到不了 import_file 失败分支） | **A**：补一条「.json + import_file 返回英文 codec 错误」的用例 |
| `A11-M2` 常驻标签整个拿掉 | WRONG TEST（rc=1 · 2 errors） | **判据口径缺口**：变异其实被检出（fixture/调用期 AttributeError → 2 ERROR 行），但 `mutate_check.judge` 只看 FAILED 行；`_mutate_lib.test_error_lines()` 说明本仓早承认「setup/call 期 error 也算检出」，只是 judge 没接 | **留待专门一轮**（改 judge 口径会影响全部 spec） |
## 4. 新增工具：`_dev/check_mutation_nodeids.py`（nodeid 体检）

**抓到的真问题（本轮新失败模式）**：**改用例名是常规操作，而它会让变异静默失效。**
A10 把 `test_static_input_dialogs_are_gone_except_the_frame_action_one` **改名**为
`test_static_input_dialogs_are_gone`（而且是加强式改写）→
`mutations_agent_a_v280.json` 的 **MA11** 与 `mutations_agent_c_v280.json` 的 **M-C-A22**
nodeid 指向**不存在的用例**：pytest 报 node-not-found，**这两条永远判不成 CAUGHT**，
而且**只有定版整批跑时才暴露成 WRONG TEST**（白烧一整批）。
**锚点一直有 `--scan-only` 体检（命中次数必须恰好 1），nodeid 在此之前一条体检都没有。**

工具：秒级、只读、不跑 pytest；`tests` 与 `expect_fail` 两份都查；含类方法 / 参数化 / 只给文件的旧形态（`MF4`）/
裸用例名四种形态；**退出码 0/1 可直接进定版流水**。
**实测**：修之前**坏 2**（MA11 / M-C-A22）→ 修之后**坏 0**；落 A 第二批时它又当场抓出**第 3 条**（`B6-M2` 的 nodeid 被转述成 `test_test_plays_…`，现树真名是 `test_test_play_plays_and_…`）→ 修正后 **1140 条 / 坏 0**；**F-C 之后 1139 条 / 坏 0**（`A7-M2` 的 tests/expect_fail 从 3 条 nodeid 收到 2 条，改指真覆盖用例）。三次命中都是「原料里的 nodeid 与现树不一致」，这条工具的价值已被三次独立命中证明。

**⚠ 范围更正（v2.9.0 三审 F-6）**：它**只校验 `mutations[].tests` / `expect_fail`**；spec 顶层 `evidence.tests`、`results.tests` / `results.items[].failed` 属于**历史记录**（当时跑出什么），里面可能仍留着改名前的旧用例名——**那是应该保留的，不算漂移，也不该改**。原先的结论文案（"nodeid 全部对得上"）**比它实际校验的范围大**，已改成"**校验范围内**对得上"，并把范围外条数（本轮 **429 条**）一并打印出来。**感谢三审指出——这是"措辞比证据大"的又一例。**
已按父代理要求写进 `_dev/README.md` **铁律 5**（与 `--scan-only` 并列）+ §一 脚本表。

---

## 5. spec 维护（本轮顺手修掉的漂移）

### 5.1 九条"被有意改写改死"的旧锚点（**重锚前逐条独立复核 = 命中 0 次**）

| spec :: id | 原锚点为什么会死 | 新锚点（现在命中 1 次） |
|---|---|---|
| `agent_a_v280` MA18 · `agent_c_v280` M-C-A30 | A6 **有意撤销**上一轮的"删自定义动作二次确认" | **语义反转**：改成"**把确认加回来**"（`item = self._act_list.currentItem()` 之前插 `_confirm`），并与 `A6-M1` 明写同失败点 |
| `agent_a_v280` MA19 · `agent_c_v280` M-C-A31 | 删动作回执的文案改了（`（保存后生效）` → `（点「取消」或关掉这个窗口，本次删除会被放弃）`） | `_toast(self._pet, "已删除自定义动作「%s」（点「取消」…）" % name)` |
| `agent_a_v280` MA22 · `agent_c_v280` M-C-A36 | 添加步骤回执 **`_toast` → `_note`**（A4 改内联状态行） | `self._note("已添加步骤：%s（点「保存」才落盘）" % …)` |
| `agent_a_v280` MA23 · `agent_c_v280` M-C-A37 | 同上（删除步骤） | `self._note("已删除步骤%s（点「保存」才落盘）" % …)` |
| `critic_v270` M-R5-P2-4 | 帧动作实现搬进模块级 `add_frame_action` | `if not files:` 那段（取消 = 静默返回） |

同时把两条 `tests`/`expect_fail` 里**已改名**的用例引用（`test_role_edit_delete_action_needs_confirm_and_reports`
→ `…needs_no_confirm_and_is_undoable`）一并更新，并给 MA22/MA23/M-C-A36/M-C-A37 **补上 v290 的新用例**。

### 5.2 一条历史笔误（无害但会误导复核）

`mutations_agent_a_v270.json` 的 **M-A-01** `expect_fail` 把
`test_export_role_bundle_end_to_end` 写成了 `tests/test_dialog_buttons_v270.py`（实际在
`tests/test_dialogs_feedback_v270.py`）。**判定按 basename 比对，所以一直没影响结果**，已改正文件名。

---

## 6. ⚠ 乱码 nodeid（原料级坑 + 我自己的连带错误）

**事实**：B 交来的 `%TEMP%\b_mutations_v290.json` 里，**B7-M1 与 B7-M2 的 `expect_fail`** 里两个中文 nodeid
被写成了 **U+FFFD 乱码**（非 UTF-8 管道落盘）。B 自述"18/18 CAUGHT"没错——它在自己影子里用的是内存里的
正确字符串，**坏在落盘那一步**。照抄的后果：pytest 红的是**正确**的用例，而 `expect_fail` 谁也匹配不上 →
**永远判 WRONG TEST**。

**我的连带错误（如实登记）**：第一遍我用"凡含乱码就填 B7-M1 的 nodeid"的**批量兜底**修法 →
**B7-M2 当场判 WRONG TEST**（红的是两条 `test_talk_自动开开关_*`，而 `expect_fail` 指的是另一条）。
**是判定器把它抓出来的**，不是我自查出来的。已改成**逐条对齐 `tests` 字段**，复跑 **23/23 CAUGHT**。
教训写进 spec 与 `_dev/README.md`（证据保护第四条）：**乱码 nodeid 必须逐条对齐，不许批量兜底**。

---

## 7. 公开清单与份数（按实测更新）

- `_dev/README.md`：spec 份数/条数（26 份 / 456 条锚点；合计 481）、`--scan-only` 末行、**指纹清单 11 → 14**（本文此前一直漏记 v2.6.0 补的
  `pet_plugin_index.py`，实为 12）、新增两份 spec 的表格行、新增两个脚本的登记、**铁律 5 新增两条规矩**
  （nodeid 体检 + 改源码者自查 + 乱码 nodeid），并追加 **v2.9.0 第 7 轮中间态记录**（明确"不作发布依据"）。
- `_dev/audit_feedback_v270.md`：新增 **§5.2 第 7 轮（v2.9.0）清账**，逐条点名用例与变异 ID，并如实登记
  **哪几条还没有变异证据**。

---

## 8. 数字（本轮实测）

| 指标 | 数值 | 出处 |
|---|---|---|
| 锚点体检 | **496 条 / 坏 0**（471 条 spec 形态 + 25 条旧形态驱动） | `python -B _dev/mutate_batch_v270.py --scan-only`（收尾实测） |
| nodeid 体检 | **1139 个 / 坏 0**（校验范围内；F-C 后） | `python -B _dev/check_mutation_nodeids.py` |
| 变异体语法自检 | 本轮三份 spec 全 0 问题 | `python -B _dev/check_mutation_ast.py …` |
| B 批判定 | **23/23 CAUGHT** | `mutations_agent_b_v290.json` 的 `results` |
| 补录批判定 | **23/23 CAUGHT** | `mutations_agent_b_v280.json` 的 `results` |
| A 批判定 | **23/28 CAUGHT**（4 WRONG TEST + 1 NOT CAUGHT，逐条定性见 §3.3） | `mutations_agent_a_v290.json` 的 `results`（14 键指纹） |
| pytest / v13 / 静态门 | **本轮 C 未跑**：全量门按铁律 2 必须在**安静窗口**跑，且属定版动作 | — |

---

## 9. 没做到 / 让步 / 疑问（如实写，不许写成做完了）

1. ~~A 的第二批 16 条收尾时尚未到手~~ → **已到手并落盘**（15 条，见 §3.2 第二批）；**但其中 3 条的判定还没转绿**：
   `M-A290-01` / `M-A290-02`（等 A 给 `test_dialogs_v24.py` 补 stub 三件套）与 `A7-M2`（等 A 补 `_human_import_error` 使用点的用例）。
   **这两处补完后由定版整批复跑覆盖**（值班人已确认：C 不必单独复跑，省约 25 分钟）。
2. **A 批已跑完（28 条 / CAUGHT 23）**，但**五条非 CAUGHT 的"转绿"依赖 A 的三处改动**（§3.3）；
   在那之前，这 5 条的正确读法是"**这条还没被验证**"，不是"护栏失效"、更不是"通过"。
   **其中 `A11-M2` 的根因在判据口径**（ERROR 行不算检出），**不在一轮里顺手改判定口径**——留待专门一轮。
3. **27 份老证据现在全部报"指纹过期"**——这是**轮中间态**（B 在改 `pet_behaviors.py` + 本轮给清单补了两个新键），
   **按铁律 5 由定版整批复跑消掉**，本轮**不处理**；不要读成"证据坏了"。
4. **残留的 18 个锚点文件 / 46 条变异仍无指纹覆盖**——**超出 C-2 的点名范围，我没有擅自扩清单**
   （每加一个键都会让所有老证据多一条"缺键"提示）。要不要继续补，是**产品/流程决策**，不是 C 能自己定的。
5. **越界一处**：`_check_release.py` 加两个文件名字符串（§2，已获批、零逻辑）。
6. **协调教训（写下来免得下一个人再踩）**：C 在收到"锁已放，A 可以跑全量"之后**约 15 秒**就开了一条 A 批变异运行，
   而 A 的 PRE 检查抓到了锁、**一行 pytest 都没跑就自我中断**（这次没产生争用下的数字，没污染）。
   **根因不是"想跑 A 批"，而是把"锁已放"这个瞬时状态当成了放行承诺。** 正确做法（本轮定的协议）：
   **① 跑完当前这条就停；② 回一句"我已停，等你"（这是承诺）；③ 等值班人回"可以继续"才动。**
   **"锁已放" 只说明"此刻没人持锁"，它不承诺"接下来几分钟也没人持锁"。**
   **同一条纪律的另一面（v2.9.0 三审补充 · 值班人自己踩到并更正）**：**任何护栏 / 全门 / 证据跑动期间，「树」必须静止。**
   `_dev/.mutation.lock` 管的是「**锁在跑**」，它管不了「**树在写**」——**「跑门期间有人写源码」与「跑门期间有人持锁」是同一类污染的两个来源，产出的红绿都不可信。**
   本轮实测两次：① 值班人在 A 还在写入时起了全门 → `pytest 1336 passed` **整批作废**；② C 在 A 的半成品状态起跑 A 批 → **BASELINE-RED（rc=2，不给判定）**，白烧一轮。
   **动手前的「静止三查」（第三查是本轮漏掉、事后补上的）**：**① 无锁**（`_dev/.mutation.lock` 不存在）· **② 无进程**（`Get-Process python` 为空）· **③ 无写者**（没有别的 agent 正在写产品源码 / tests）。
   **前两查都过、第三查不过，照样白跑** —— 这正是本轮那两次的成因。
7. **登记（独立验收 F-C 的另外两件，前者不改、后者已由 A 对齐）**：
   · **`tests/test_import_thread.py:108` 是真·恒真断言**（`assert not dlg._ok.isEnabled() or True`）——**预存在**，不在本轮范围；
     同类弱断言另有 `test_io_v231.py:1287`、`test_plugin_host_v251.py:1643`。**建议进「恒真断言清理」清单**
     （本轮刚清掉 `tests/test_dialogs_feedback_v280.py:1150` 那条——说明这类是**系统性**的，不是孤例）。
   · **注释里的数字也会算错（一例，且是我自己写的）**：`_dev/_mutate_lib.py` 的 C-2 注释原先写「全库 38 条 / pet_ai.py 29 条」，
     而它自己的分项列的是 10+7+3+10 —— **算术只到 30、实测是 29**（agent_b_v270 实为 **9** 条，我写的"十条"是错的）；
     更要紧的是**漏了本轮 agent_b_v290 的 `B7-M1/M2` 两条**。A 已对齐为 **40 条 / pet_ai.py 31 条**
     （9 + 7 + 2 + 3 + 10）**+ pet_config.py 9 条**，逐项复核无误。**教训：注释里的数字要与实测同一口径，且要跟着新 spec 更新——它和"证据指纹"一样会过期。**
8. **疑问**：`mutations_agent_d_v280.json` 的 `MF4` 用的是"只给文件 + 裸用例名"的旧形态——
   本次 nodeid 体检**特意兼容**了它（否则误报 2 条），但如果以后还有这种写法，**建议统一成完整 nodeid**，
   否则"用例改名"这类漂移在它身上仍然体检不出来。

---

## 10. 复跑入口（给下一个人）

```powershell
python -B _dev/mutate_batch_v270.py --scan-only          # 锚点：命中次数必须恰好 1
python -B _dev/check_mutation_nodeids.py                 # nodeid：用例必须还在（退出码 0/1）
python -B _dev/check_mutation_ast.py                     # 变异体语法（跑批之前先过一遍）
python -B _dev/mutate_check.py _dev/mutations_agent_b_v290.json
python -B _dev/mutate_check.py _dev/mutations_agent_a_v290.json
python -B _dev/mutate_batch_v270.py                       # 定版：安静窗口整批（铁律 5）
```
