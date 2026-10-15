# v2.7.0 第 5 轮（收尾一路 · 审查转办）：完工报告

> 范围 = 三路审查转来的条目：F1 / F1b / F2 / F3 / F4 / F5 / F6 · L2-1 · L2-2（部分）· P2-4 ·
> P2-1 / P3-1 / P3-2 / P3-3（观察项）· P1-1。**未提交**（铁律 6，由主代理统一提交）。
> 版本五处 / 绿色版 / 发布 zip / CHANGELOG / _release_notes_* 一个字节没碰。

## 0. 三项护栏（本机、安静窗口、`_dev/.mutation.lock/` 不存在）

| 门 | 命令 | 结果 |
|---|---|---|
| pytest | `python -B -m pytest tests -o addopts="" -q` | **1158 passed, 0 failed**（198s；改前 1143 → +15 条新用例） |
| v13 | `python -B _verify_v13.py` | **TOTAL CHECKS 273, FAILS 0**（ALL OK） |
| 静态 | `python -B _check_static.py` | **问题 0 条，待确认 0 条** |

三项都是**同一棵树、串行**跑的；跑之前 `Test-Path _dev/.mutation.lock` = False，跑完也是 False。

## 1. 产品代码改了什么

| 文件 | 位置（句柄，行号会漂） | 改动 |
|---|---|---|
| `pet_dialogs.py` | `VoiceDialog._assets_index_unusable` | **F1**：判据补"**assets() 真为空**"——先问库，读得出就一律 False；日志只在真丢弃时落；读不出来的兜底补一条留痕日志（避免变成新的静默 except） |
| `pet_dialogs.py` | `_apply_result` / `_apply_call` 注释 | **F2**：**非空字符串 = 失败**（错误串就是原因）；空串仍是成功；strict 契约（(ok,msg)/True/False/None/非空串）写进 docstring |
| `pet_dialogs.py` | `_toast` docstring | **F5**：口径改成"**尽力而为**"（返回 False 只表示没尝试发），不再承诺"真的发出" |
| `pet_dialogs.py` | `SoundPanel._on_slot` | **L2-1 消费端**：`_apply_call(..., "apply_sound_group", ..., strict=True)` |
| `pet_dialogs.py` | `RoleEditDialog._add_frame_action` | **P2-4**：取消（空表）静默返回；只有真选 1 张才报"至少 2 张图" |
| `pet_ai.py` | `AIService.apply_settings` | **F4**：**先改副本、落盘成功才 `cfg.update(new)`**（取方案②，理由见函数内注释）；**F3**：把过期的"save_config 返回 None 判不出来"注释改准（链条已通） |
| `pet_ai.py` | `AIService.clear_api_key` | **P2-1**：同样先改副本；写盘失败 → **什么都不清**（Key / 余额基准 / 记忆 / 日志一个都不动）+ 如实报告 |
| `pet_ai.py` | `AIService.set_ai_enabled` | **P3-2**：第二次落盘（没 Key 就把开关退回关）的返回值不再丢弃，失败一并说出来 |
| `桌宠.py` | `apply_sound_group` | **L2-1 生产端**：返回 `(ok, msg)`；写失败退回 cfg 里的 `sound_group`；异常 → (False, 原因) |
| `桌宠.py` | `apply_bubble_style` / `apply_physics` | **P3-1**：写失败时 **cfg 退回原值**（改前是"内存已改 / 盘未改 / 引擎未改"三处不一致） |
| `桌宠.py` | `_import_role_bundle` | **P1-1**：接住 `apply_bubble_style` 的返回值，失败并进 `_res["warnings"]`，成功气泡里带一句原因 |

**L2-1 的接口改动是跨模块的**（`桌宠.apply_sound_group` 返回值从 None 变二元组）—— 其余调用点
（`_set_sound_group` / `_apply_sound_group`）不看返回值，行为不变；`_verify_v13.py` 里那处调用也不看。

## 2. 用例（每条修复都配了能真失败的用例）

| 条目 | 用例 |
|---|---|
| F1 / F1b | `tests/test_dialogs_feedback_v270.py::test_bind_hint_quiet_on_healthy_library`（**反向**：健康库 → 提示行必须为空 + 下拉里真有素材 + 没写误导日志；断点在**文案**上，不是谓词） |
| F2 | `…::test_apply_result_treats_bare_error_string_as_failure`、`…::test_physics_dialog_keeps_window_open_on_bare_error_string` |
| F4 | `…::test_ai_apply_settings_failure_leaves_memory_untouched`、`…::test_ai_apply_settings_success_commit_is_bit_identical`（成功路径逐位不变） |
| F5 | `…::test_toast_is_best_effort_not_a_delivery_receipt` |
| L2-1 | `…::test_sound_panel_backend_failure_does_not_claim_success`（生产端异常）、`…::test_sound_panel_treats_none_return_as_failure`（消费端 strict 契约） |
| P2-4 | `…::test_frame_action_cancel_is_not_reported_as_too_few` |
| P2-1 | `…::test_clear_api_key_save_failure_keeps_key_and_says_so`（含成功路径对照） |
| P3-1 | `…::test_bubble_style_and_physics_roll_back_cfg_on_write_failure`（真 `atomic_write_json` 注入） |
| P3-2 | `…::test_ai_toggle_second_save_failure_is_reported` |
| P1-1 | `tests/test_critic_menu_e2e_v270.py::test_bundle_import_reports_bubble_style_write_failure`（真包 → 真导入） |
| **F6（覆盖缺口）** | 新文件 `tests/test_critic_menu_e2e_v270.py`：真 `pet._open_menu()` → 真菜单树 → **真 `exec()` 循环**里 `QAction.trigger()` → 全路径到产物；另有一条结构钉子（菜单项在「🐟 角色」子菜单里的位置/文案） |

> F6 的实现注记：PySide6 的 **类级** `QMenu.exec` 替换对 C++ 调用点**不生效**（实测：真 exec 照样阻塞），
> 所以驱动器改成"**实例级**替换 `pet._new_menu` 拿到那棵树 + 定时器在真 exec 循环里触发 + `menu.close()`
> 退出循环"（无论成败都关，绝不留挂死用例）。

## 3. 变异：**13/13 CAUGHT**（影子副本，铁律 6）

- spec：`_dev/mutations_critic_v270.json`（13 条，`mutate_check.py` 跑通并**回写 results**
  —— `checked_at = 2026-10-15 16:33:55`，`repo_fingerprint` 12 个键）。
- **原文证据**：`_dev/critic_mutation_output_v270.md`（`probe_critic_mutation_output_v270.py` 的 stdout
  原样摘录，逐条贴"红在哪一句断言上"）。
- 每条锚点在真仓命中**恰好 1 次**（0 次/2 次都是"这条没被验证"，脚本会喊 SPEC-BAD）。

## 4. 没做的 / 需要协调的（如实）

1. ~~**L2-2 只完成本路**：A 的 31 条、B 的 16 条变异**没有落成 spec**~~ → **【已更正·原为反向失实】已完成**：A **31** 条（`_dev/mutations_agent_a_v270.json`）、B **35** 条（`_dev/mutations_agent_b_v270.json`）**已落成 spec 并入批量门**；`--scan-only` 收录、独立复跑 **31/31 与 35/35 全 CAUGHT**
   （grep `_dev/*.json` 只有本路 13 条引用第 5 轮的用例），**他们的变异原文只存在于各自会话里，无法复原**。
   需要人类/协调者找 A/B 补原始记录。本路 13 条已入库，`mutate_batch_v270.py` 会自动收进整批。
2. **兼容审查 P3-3 裁决为"不删"**（原建议：删掉 `桌宠.apply_physics` 里那条成功气泡）：
   B 的用例 `tests/test_feedback_host_v270.py::test_apply_physics_no_change_is_not_silent` 明确把
   "值真的变了 → 有可见反馈"钉在**主窗这一层**（`assert bubbles`），删掉它那条既有用例会红，且
   "直接调主窗回调"这条路彻底没反馈。重复代价有界：`Bubble.show_text` 对同文案/同尺寸/同位置幂等。
   已写进 `_dev/audit_feedback_v270.md` §5 第 13 条。
3. **F5 的另一种修法没做**（让 `_closing` 早退分支返回 False）：要改主窗公共接口，改动面不划算。
4. **F4/P2-1 的同族兄弟**（`set_ai_enabled` / `set_chat_rounds` / `set_api_key` 仍"先改内存再写盘"）
   —— 本轮只按点名修了 `apply_settings` 与 `clear_api_key`；其余写进未做清单。
5. **L3 文档债**：全部做完（见下），唯一例外是"审计 §4 的两条未实测"——它们本来就需要真 GUI 手测，
   本轮没有 GUI 环境，仍标未实测。

## 5. L3 文档债（已改）

- `_dev/audit_feedback_v270.md`：文件头加"行号对应修复前状态，请按句柄名 grep"；"323 个 def/class"
  → **326**（`ast.parse` 实测 304 函数 + 22 类）；**末尾新增 §5「本轮未做清单（公开声明）」14 条**
  （D9 / D14 / S14+S15 / S20 / P2-5 / P2-7+N13 / P3-4+P3-5 / P3-6 / N14+N15 / 两条未实测 /
  F5 另一修法 / F4 同族 / P3-3 裁决 / L2-2 缺口），每条带"为什么不在这轮做"。
- `_dev/audit_buttons_binding_v270.md`：§0 顶部标注"第 5 轮已修：动作按钮未接线 **0**（原 2）；
  状态输入未接线仍 **15**（非缺陷）"，并提示行号漂移。
- `_dev/agent_c_v270_report.md` + `_dev/README.md`：条数改准 —— **17 份 / 190 条**（183 + 本轮 7），
  收尾再加本 spec → 现树 **18 份 / 203 条**。
- `_dev/pytest_v270_full.txt` → **`_dev/pytest_v270_tail.txt`**，并从 UTF-16LE 转成 UTF-8（内容原样：
  `1143 passed, 12 warnings in 138.75s`）。
- `tests/test_dialogs_feedback_v270.py`：不可达的前提守卫 `pytest.skip` → `pytest.fail(..., pytrace=False)`。
- `_dev/probe_bubble_z_order_v270.py`：日期占位符 `2026-XX` → **2026-10-15**。

## 6. 新增文件清单（未跟踪，等主代理统一入库）

- `_dev/mutations_critic_v270.json`（spec + results）
- `_dev/probe_critic_mutation_output_v270.py`（原文证据驱动器）
- `_dev/critic_mutation_output_v270.md`（原文证据）
- `tests/test_critic_menu_e2e_v270.py`（F6）
- `_dev/pytest_v270_tail.txt`（.txt → 被 `.gitignore` 的 `_dev/*` 忽略，不会进发布门）
