# v2.8.0 第 6 轮 · 专项追查：46 条「成功后零提示」逐条对照表 + 「15 行未覆盖」重建

> **只读专项复核**。本次唯一写入的文件就是本文件；产品代码 / 测试 / 其它 `_dev` 文档一个字节没碰。
> 追查人：专项追查子代理 ｜ 时间：**2026-10-15 18:45** ｜ 仓库：`E:\deep seek\desktop-pet` ｜ 基线提交：**da7f049**（v2.7.0，HEAD；工作树另有第 6 轮未提交改动）
> 触发：`_dev/audit_checklist_completeness_v280.md` §0.2 **限制 3**（「46 条从来没有逐条对照表」）与 §3.9（「15 行未覆盖无法确认」），以及该报告 §5 结论第 6 条点名的「结构性缺口」。

---

## 0. 快照 / 口径 / 方法（先看这里，决定下面每条结论的可信度）

### 0.1 快照（**下面所有行号只对本快照有效**；行号会漂，请按句柄复核）

| 文件 | 字节 | mtime | sha256 前 12 | 行数 |
|---|---|---|---|---|
| `pet_dialogs.py` | 357916 | 2026-10-15 18:33:47 | `7E6B0F880CD2` | 7453 |
| `桌宠.py` | 303065 | 2026-10-15 18:32:12 | `CD0046333926` | 5471 |
| `pet_ai.py` | 18764 | 2026-10-15 18:31:00 | `967038396D48` | 307 |
| `pet_balance.py` | 23871 | 2026-10-15 18:31:18 | `66948E5514A4` | 433 |

**树在动**：复核期间第 6 轮正在跑（`git status --short` 显示 pet_dialogs / 桌宠 / pet_ai / pet_balance / pet_config / pet_plugin_index 均为 M）。我在 18:33 与 18:45 **两次取哈希，四个被测文件完全一致**，所以下面每条结论对应同一个快照；但**不保证你读到本文件时树还是这样**——复核请以句柄名为准。

### 0.2 判定口径（「有可见反馈」到底指什么）

沿用 `audit_feedback_v270.md` §1 的反馈原语清单，逐条判「当前代码里这条操作**用户能不能看见结果**」：

| 判为「有 ✅」 | 判为「弱 ⚠️」 | 判为「无 ❌」 |
|---|---|---|
| ① 模态框 `_warn / _info / _confirm`（`pet_dialogs.py:341-364`，经 `modal()` 置顶）② 宠物气泡 `_toast`（`:411-440` → `桌宠.show_bubble` → `pet_widgets.Bubble`，5 秒自隐）③ 窗口内状态行 `_save_hint / _notes / _hint / _banner / _count` 文本变化 ④ 按 id 选中 **且** `scrollToItem` ⑤ 按钮置灰/启用切换 | 只有「列表加了一行 / 少了一行 / 下拉值变了」这类**间接**变化；或成功回执依赖另一个窗口的可见性 | 点下去之后，在常规交互路径（桌宠在运行、对话框已打开、宠物没在退出）上**屏幕上不出现任何新东西**：没有框、没有气泡、没有状态行、没有选中/滚动、没有置灰变化 |

**两条边界，先说清楚，避免夸大：**

- `_toast` 是**尽力而为**（`pet_dialogs.py:411-425` 自己写明）：`show_bubble` 明确回报没显示时走 `_toast_fallback`（`:443-460`）——**传了 `status=` 就写状态行，没传就只落一条限流日志**。全仓 38 个 `_toast` 调用点里**只有 3 个**传了 `status`（`:6899 / :6904 / :6956`，全是第 6 轮新增的插件索引来源区）。所以「气泡被拒绝」时，面板内的回执**仍然只有日志**——这不是本次要判的「点了没反应」（气泡被拒只在宠物退出/无屏幕时发生），但**别把 `_toast` 当成"保证可见"**。
- 面板内气泡压在模态框之上，**有实测依据**：`pet_dialogs.py:406-408` 引用 `_dev/probe_bubble_z_order_v270.py`（第 5 轮开工前实测项，已入库）。所以「对话框开着时气泡看不见」这个担心，按仓内证据**不成立**。

### 0.3 我读了哪些句柄（**不是抽样**）

`pet_dialogs.py` 全量 AST 类/方法表（逐条定位 340+ 个 def/class），再**逐个读**了 §2 涉及的全部方法体，外加：`_toast / _toast_fallback / _apply_result / _apply_call / _save_failed / _warn / _info / _confirm / _ask_text / _ask_item / _call / _dialog_failed`；`桌宠.py` 的 `_open_behavior_dialog / _open_idle_dialog / _open_alarm_dialog / apply_idle_settings / apply_role / apply_physics / apply_sound_group / apply_voice / apply_bubble_style / apply_ai_settings / _clear_logs / clear_long_term_memory / show_bubble / _export_role / _export_step / _import_role_bundle`；`pet_ai.py` 全文 307 行；`pet_balance.py` 的 4 个菜单入口。**每条结论都给出我实际读到的行。**

### 0.4 三条限制（不许「大概都有了」）

1. **未跑 GUI、未跑 pytest**：本复核是**源码级**判定，未启动 Qt、未点按钮、未截图。凡"气泡会不会被挡住""弹窗会不会被前台锁拦"之类的判断一律引用仓内既有实测件或标注**未实测**。
2. **未判"文案好不好"**：只判"有没有"，不判"说得对不对"。
3. **质量审查报告仍然不存在**：我独立重跑了定位（`L3-[0-9]`、`15 行未覆盖`、文件名 `*质量* / *审查* / *review*`，含 `~/.dsh`）→ **0 命中**，与 `audit_checklist_completeness_v280.md` §0.2 限制 1 一致。§2 的清单是**我按现树重算的**，不是原文。

---

## 1. 逐条对照表（`audit_feedback_v270.md` §2 四张表 **全列 = 65 行**）

图例：**✅ 有可见反馈** ｜ **⚠️ 弱反馈（有间接变化但无明确成功信号）** ｜ **❌ 无** ｜ `∈46` = 属于审计 §0.1 口径的「成功后零提示 46 条」。
46 条的还原口径（与审计 §0.1 原文自洽）：新建 **14**（N1–N18 去掉 3 个标杆，再去掉无入口的 N9）+ 删除 **15**（D1–D14、D18）+ 导出 **1**（E3）+ 保存/重命名/导入/应用 **16**（S2–S7、S10–S16、S22、S23、S25）= **46**。

### 1.1 新建（N1–N18）

| 编号 | 现树位置（句柄 @ 行） | 当前实际行为 | 有可见反馈 | 证据（我读到的现树代码） | ∈46 | 若"无"→建议归轮 |
|---|---|---|---|---|---|---|
| N1 | `pet_dialogs.py:3595-3634 RolePanel._import` | 成功：`_refresh()` + `apply_role` + **`_info`「导入成功！…」**；失败 `_warn`；向导取消静默 return | ✅ | 3617-3619 `_warn(... err or "导入失败")`；3631-3632 `_info(... "导入成功！…")` | — | — |
| N2 | `pet_dialogs.py:4644-4653 LinesDialog._new_line` | 清空表单 + `setCurrentRow(-1)` + 聚焦 + **气泡「已进入新建态：写完台词点「保存」」** | ✅ | 4653 `_toast(self._pet, "已进入新建态：写完台词点「保存」")`；4652 注释点名 **N2** | **是** | — |
| N3 | `pet_dialogs.py:4655-4687 LinesDialog._save_line` | 新建落库→**清类别筛选 / 清搜索**（4683→4689-4694）→`_refresh_all()`→按 id **选中 + `scrollToItem`**（4686→4696-4706）→气泡「台词已保存~」；空文本 / 保存失败 `_warn` | ✅ | 4666-4687；`_clear_line_filters` 4689-4694；`_select_line` 4696-4706 | **是** | — |
| N4 | `pet_dialogs.py:4841-4857 LinesDialog._new_dialogue` | 落库→`_refresh_all()`→按 id **选中 + 滚动**（4852-4856）→气泡「已新建对白「X」，记得改名~」 | ✅ | 4847-4857 | **是** | — |
| N5 | `pet_dialogs.py:2771-2777 BehaviorDialog._new` | `_reset_form()` + **气泡「已进入新建态：填好行为名与步骤后点「保存」」** | ✅ | 2776-2777（docstring 2772-2775 自述"清空表单时屏幕零变化"已解决） | **是** | — |
| N6 | `pet_dialogs.py:2882-2902 BehaviorDialog._save` | 落库→`_refresh()`→`_select_behavior(id)`（2904-2914，按 id 选中+滚动）→气泡「行为「X」已保存」；失败 `_warn` | ✅ | 2893-2902 + 2904-2914 | **是** | — |
| N7 | `pet_dialogs.py:3854-3868 SoundPanel._import_audio` | 导入→`_refresh()`→`_select_fragment(id)`（3933-3943，选中+滚动）→气泡「已导入音频「X」」 | ✅ | 3861-3868 | **是** | — |
| N8 | `pet_dialogs.py:4022-4036 VoiceAssetPanel._import_asset` | 导入→`_refresh()`（`_hint` 计数仍会变，4010）→`_select_asset(id)`（4038-4048，选中+滚动）→气泡「已导入参考音「X」」 | ✅ | 4029-4036 | **是** | — |
| N9 | `pet_dialogs.py:3242-3264 AISettingsDialog`（人设行） | 人设下拉**只读**（内置 + `prompts/custom/*.txt`，来源 `桌宠.py:557-565 persona_choices` / `:501-502 _prompts_dir`）+「自定义（自己写人设）」文本框；**全窗口没有「新建人设」按钮，也没有目录路径提示**（`pet_dialogs.py` 全文 `prompts` 只出现 1 次，是 3244 的注释） | ❌ **无入口**（不是"点了没反应"，是"没得点"） | 3242-3264；grep `prompts` → 仅 3244 注释 | **是** | 计划 `plan_v270_rounds.md` §7.5-**L8** 已裁决 **不做** → 建议**把这条从"未归位"改成"明确不做"销账** |
| N10 | `pet_dialogs.py:3112-3138 AlarmDialog._save` | 落库→`_refresh()`→按 id `setCurrentRow` + `scrollToItem`（3133-3137）→气泡「闹钟已保存~（到点气泡提醒）」 | ✅ | 3128-3138 | **是** | — |
| N11 | `pet_dialogs.py:6168-6181 IdleDialog._add_action` | 加项→`_refresh_table()`→`_select_action(id)`（6196-6206，`setCurrentCell`+`scrollToItem`）→气泡「已添加待机动作」 | ✅ | 6174-6181 | **是** | — |
| N12 | `pet_dialogs.py:2391-2453 RoleEditDialog._add_frame_action` | **取消已不再误报**：先 `if not files: return`（2395-2399），再判 `< 2`（2400-2402）；成功：写 `_forms[idx]["animations"]` + `_refresh_act_list()`（2437-2438）；**成功路径无任何回执** | ⚠️ **弱**：只有动作列表多一行。`_act_list` **限高 80px**（`:1981`），`_refresh_act_list`（2379-2389）**不选中、不滚动** → 动作多时新条目落在视口外，用户视角等同"点了没反应" | 2395-2402（取消分支，注释点名 P2-4）；2437-2438（成功分支，**无 toast**） | **是** | **第 6 轮 A2 同族**（补 `_toast` + `scrollToItem`）**或明确写"不做"**——计划 §7.6 第 2 条的"二选一"原文即指此类 |
| N13 | `pet_dialogs.py:2455-2516 RoleEditDialog._add_proc_action` | **「取消」按钮已补**（2488-2496：`ok / cancel` + `btn_row` + `stick_buttons`，且走 `modal(dlg)` 2499）；成功：写 `procs` + `_refresh_act_list()`（2514-2516）；**成功路径无任何回执** | ⚠️ 同 N12（同一个 80px 列表） | 2486-2499（注释点名 **P2-7 / N13**）；2514-2516（成功分支，无 toast） | **是** | 同 N12 |
| N14 | `pet_dialogs.py:1497-1507 RoleImportDialog._on_add_form`（+ `_add_form` 1509-1516） | 加形态成功后写**窗口内状态行**：`self._notes.setText("已添加「形态N」（共 N 个，最多 8 个）…")`；满 8 个 `_warn` | ✅ | 1503-1507；`_notes` 是 `QLabel` 且已 `addWidget` 进 root（1424-1426） | **是** | — |
| N15 | `pet_dialogs.py:2794-2836 BehaviorDialog._add_step` | 校验通过→`QListWidgetItem` + `self._steps.addItem(_it)` + `_param.clear()`（2833-2836）；各类校验失败 `_warn` | ⚠️ **弱**：步骤列表加一行（列表紧邻按钮，可见），但**无成功回执** | 2829-2836（成功分支**无 toast**）；失败分支 2800 / 2805 / 2814 / 2831 都有 `_warn` | **是** | **第 6 轮 A2 同族**（计划 §7.6 第 2 条**点名 N15**）或明确"不做" |
| N16 | `pet_dialogs.py:4888-4902 LinesDialog._add_member` | 落库→`_on_pick_dialogue()` + `_refresh_dialogues()` + 气泡「已添加到对白（顺序即播放顺序）」；未选对白 / 失败 `_warn` | ✅ | 4896-4902 | **是** | — |
| N17 | `pet_dialogs.py:7348-7367 _install_selected / _install / _install_path` | 成功 `_info(msg)`；失败 `_warn`；宿主未接线 `_warn`；`refresh()` | ✅ | 7357-7367 | — | 标杆 |
| N18 | `桌宠.py:2523-2597 PetWindow._import_role_bundle` | 成功气泡「角色包导入成功！来自「作者」…（警告）」；失败→**六份 JSON 快照整体回滚** + 气泡「导入失败：…」；取消静默 | ✅ | 2537-2540（失败+回滚）、2576-2597（成功，含"被截掉的警告条数也写出来"） | — | 标杆 |

### 1.2 删除（D1–D18）

| 编号 | 现树位置（句柄 @ 行） | 当前实际行为 | 有可见反馈 | 证据 | ∈46 | 若"无"→建议归轮 |
|---|---|---|---|---|---|---|
| D1 | `pet_dialogs.py:3684-3705 RolePanel._delete` | 未选中 `_warn`（3688-3689）；`_confirm`（带角色名 3696-3698）；失败 `_warn`；成功 `_refresh` + `apply_role` + 气泡「已删除角色「X」」 | ✅ | 3699-3705 | **是** | — |
| D2 | `pet_dialogs.py:3906-3931 SoundPanel._delete_audio` | 未选中 `_warn`；`_confirm`（含"引用它的槽位将变静音"）；失败 `_warn`；成功 `_refresh` + `apply_sound_group` + 气泡「已删除音频片段「X」」 | ✅ | 3922-3931 | **是** | — |
| D3 | `pet_dialogs.py:4069-4085 VoiceAssetPanel._delete_asset` | 未选中 `_warn`；`_confirm`（说明会变失效引用）；失败 `_warn`；成功 `_refresh` + 气泡「已删除声音素材「X」」 | ✅ | 4076-4085 | **是** | — |
| D4 | `pet_dialogs.py:4708-4726 LinesDialog._delete_selected` | 未选中 `_warn`（4712-4714，✅ 审计点名的正例）；`_confirm` 带条数；`delete_many` 的 `err` 判据；成功气泡**「已删除 N 条台词」（`n` 终于被用上）** | ✅ | 4718-4726（4725 注释点名 **D4**） | **是** | — |
| D5 | `pet_dialogs.py:4728-4740 LinesDialog._clear_all` | `_confirm`（写明可"撤销删除"找回）；失败 `_warn`；成功气泡「已清空全部台词与对白（本窗口内可「撤销删除」找回）」 | ✅ | 4731-4740 | **是** | — |
| D6 | `pet_dialogs.py:5080-5092 LinesDialog._delete_bad_one` | 入口 `_bad_selected()`（5021-5033：未选中 `_warn`、行为步骤引用也有 `_warn`）；`_confirm`；**`delete` 返回值已接住**（5087-5090）；成功气泡「已删除失效台词」 | ✅ | 5086-5092（注释点名 **D6**） | **是** | — |
| D7 | `pet_dialogs.py:5094-5110 LinesDialog._delete_all_bad` | 无失效项→`_info`；`_confirm` 带条数；**`delete_many` 的 `n, err` 全接住**（5105-5108）；成功气泡「已删除 N 条失效台词（可用「撤销删除」找回）」 | ✅ | 5104-5110（注释点名 **D7**） | **是** | — |
| D8 | `pet_dialogs.py:4859-4871 LinesDialog._delete_dialogue` | 未选中 `_warn`；`_confirm`；失败 `_warn`；成功气泡「已删除对白（台词本身不受影响）」 | ✅ | 4863-4871 | **是** | — |
| D9 | `pet_dialogs.py:4904-4925 LinesDialog._remove_member` | 未选中 `_warn`（4909-4911）；**`_confirm` 已补**（4912）；失败 `_warn`；成功气泡**「已从对白里移除：X（台词本身不受影响）」** | ✅ | 4912-4925（4924 注释点名 **D9**） | **是** | — |
| D10 | `pet_dialogs.py:2916-2940 BehaviorDialog._delete` | 未选中 `_warn`；**`_confirm` 已补**（2926-2928，注释点名 P1-3）；失败 `_warn`；成功 `_reset_form` + `_refresh` + 气泡「已删除行为「X」」；顺带清 `idle_behavior` | ✅ | 2917-2940 | **是** | — |
| D11 | `pet_dialogs.py:2786-2792 BehaviorDialog._del_step` | **已从 lambda 改成具名方法**：`row < 0` → `_warn`「请在「行为步骤」里选中要删的步骤」（2790）；成功 `self._steps.takeItem(row)` → 行消失（可见） | ⚠️ **弱**：未选中提示 ✅，但**成功无回执**（只有行消失） | 2786-2792（注释点名 **P1-6**） | **是** | 若要求"已删除"回执 → **第 6 轮 A2 同族**；否则可结（P1-6 的原要求就是"至少要有未选中提示"） |
| D12 | `pet_dialogs.py:3140-3158 AlarmDialog._delete` | **未选中仍静默 return**（3142-3146，注释写明 `tests/test_dialogs_more_v24.py::test_alarm_dialog_update_failure_and_delete_without_selection` 断言"未选中删除不该弹提示"，既有断言不动）；选中路径：`_confirm`→失败 `_warn`→`_new()` + `_refresh()` + 气泡「已删除闹钟 X」 | ✅（选中路径）/ 未选中路径静默（**裁决不做**） | 3142-3158 | **是** | 兼容报告 §5.F.19 / 发布说明 §四-1 已公开承认 → 建议**改成"明确不做"销账** |
| D13 | `pet_dialogs.py:6183-6194 IdleDialog._remove_action` | 未选中 `_warn`（6185-6187）；失败 `_warn`；成功 `_refresh_table` + 气泡「已移除待机动作」 | ✅ | 6189-6194 | **是** | — |
| D14 | `pet_dialogs.py:2518-2550 RoleEditDialog._del_action` | 未选中 `_warn`；**`_confirm` 已补**（2532-2537，文案点明"只解除引用 / 取消可回滚 / 保存后才生效"）；成功 `_refresh_act_list` + 气泡**「已删除自定义动作「X」（保存后生效）」** | ✅ | 2525-2550（2521-2523 注释点名 **D14**） | **是** | — |
| D15 | `pet_dialogs.py:7369-7395 _uninstall / uninstall_id` | `_confirm`（逐条说明保留了什么）→成功 `_info`；失败 `_warn`；宿主未接线 `_warn`；`refresh()` | ✅ | 7375-7395 | — | 标杆 |
| D16 | `pet_dialogs.py:3387-3399 AISettingsDialog._clear_long_term` | **仍是裸 `QMessageBox.question`**（3390-3393）→ `_call` → 成功 `QMessageBox.information`「已经忘掉啦~」，失败 `QMessageBox.warning` | ✅ **有**（用户看得见）但**未走统一 `_confirm / _info / _warn`**（不带 `DIALOG_QSS`） | 3390-3399 | — | **P2-6 未做** → 计划 §7.5-L7 已排 **第 6 轮**（现树未见落地） |
| D17 | `桌宠.py:5129-5173 PetWindow._clear_logs` | 三种文案区分：**「有 N 个文件没删掉（可能被占用）：…」/「日志和对话记忆都清干净啦~」/「本来就干干净净的~」**，并带"长期记忆保留"尾巴 | ✅ | 5165-5173 | — | 标杆 |
| D18 | `pet_dialogs.py:5067-5078 LinesDialog._clear_refs` | `_bad_selected()`（未选中 `_warn`）→`_confirm`（"清空引用"）→`save` 失败 `_warn`→成功气泡「已清空这条台词的角色/声音引用」 | ✅ | 5071-5078 | **是** | — |

### 1.3 导出（E1–E4）

| 编号 | 现树位置（句柄 @ 行） | 当前实际行为 | 有可见反馈 | 证据 | ∈46 | 若"无"→建议归轮 |
|---|---|---|---|---|---|---|
| E1 | `桌宠.py:2295-2368 _export_role / _export_step` + `pet_dialogs.py:6393-6429 build_role_meta_dialog` | **P0-1 硬阻断已修**：`:6423-6425 btn_ok.setDefault(True)` + `btn_ok.clicked.connect(dlg.accept)` + `btn_cancel.clicked.connect(dlg.reject)`；导出全程有气泡：重入 2303 / 默认角色不可导出 2306 / `plan_bundle` 失败 2337 / 分片进度 2359 / 成功 2366 / 失败 2368 | ✅ | 6417-6427；2295-2368 | —（硬阻断，不属 46） | — |
| E2 | `pet_dialogs.py:4273-4288 LedgerDialog._export` | 成功 `_info`「导出成功 已导出到：<路径>」；失败 `_warn`；文件框取消静默 | ✅ | 4284-4288 | — | 标杆 |
| E3 | `pet_dialogs.py:2963-2979 BehaviorDialog._export` | 未选中→`_info`「先在列表里选中一个行为，再点「导出…」」（2966-2968，注释点名 **E3 / P1-2**）；成功→气泡「行为已导出到 <文件名>」；失败 `_warn` | ✅ | 2964-2979 | **是** | — |
| E4 | 全仓 `getSaveFileName` 只有 3 处产品代码：`pet_dialogs.py:2970`（行为 JSON）、`:4278`（账本 CSV）、`桌宠.py:2308`（角色包 zip） | **确无第四处导出**（审计结论仍成立） | ✅ n/a | grep `getSaveFileName`（其余命中全在 `tests/`、`_dev/`） | — | — |

### 1.4 同源：保存 / 重命名 / 导入 / 应用（S1–S25）

| 编号 | 现树位置（句柄 @ 行） | 当前实际行为 | 有可见反馈 | 证据 | ∈46 | 若"无"→建议归轮 |
|---|---|---|---|---|---|---|
| S1 | `pet_dialogs.py:3636-3659 RolePanel._edit` + `:2276-2360 RoleEditDialog._save` | 保存→`accept()`（2360）→调用方 `_info`「已保存「X」的修改。」；失败 4 处 `_warn` | ✅ | 3656-3657；2282 / 2286 / 2321 / 2337 | — | 标杆 |
| S2 | `pet_dialogs.py:3870-3904 SoundPanel._rename` | 未选中 `_warn`；条目消失 `_warn`；**手工建框 + `modal(dlg)`**（3886-3891）；**空名 `_warn`「名字不能为空」**（3894-3897，注释点名 S2 / P2-3）；失败 `_warn`；成功 `_refresh` + `_select_fragment` + 气泡「已重命名为「X」」 | ✅ | 3874-3904 | **是** | — |
| S3 | `pet_dialogs.py:4050-4067 VoiceAssetPanel._rename` | **已从静态 `QInputDialog.getText` 改成 `_ask_text`（手工建框 + `modal`）**（4056-4058）；失败 `_warn`；成功 `_refresh` + `_select_asset` + 气泡「已重命名为「X」」 | ✅ | 4056-4067 | **是** | — |
| S4 | `pet_dialogs.py:4873-4882 LinesDialog._rename_dialogue` | 未选对白 `_warn`；失败 `_warn`；成功 `_refresh_all` + 气泡「对白名称已保存~」 | ✅ | 4874-4882 | **是** | — |
| S5 | `pet_dialogs.py:4655-4687 LinesDialog._save_line`（编辑分支 4667-4670） | 同 N3（含筛选 / 搜索残留陷阱已消除） | ✅ | 4667-4687 | **是** | — |
| S6 | `pet_dialogs.py:2882-2902 BehaviorDialog._save`（编辑分支 2886-2887） | 同 N6 | ✅ | 2886-2902 | **是** | — |
| S7 | `pet_dialogs.py:3112-3138 AlarmDialog._save`（编辑分支 3118-3122） | 同 N10（弱化点"会选中"已升级为气泡） | ✅ | 3118-3138 | **是** | — |
| S8 | `pet_dialogs.py:6220-6234 IdleDialog._save` + `桌宠.py:2012-2031 apply_idle_settings` | 回调**返回 True / False**；失败 `_warn`；成功 `accept()` + 主窗气泡**「待机设置已更新~（N 条动作，模式）」** | ✅ | 6230-6234；2028-2031 | — | 标杆 |
| S9 | `pet_dialogs.py:5935-5975 VoiceDialog._save` + `桌宠.py:4868-4893 apply_voice` | 回调**「语音设置已更新~」气泡**（4891-4892，非 `_silent` 时）；`res is None` → `_warn` | ✅ | 5965-5968；4873-4893 | — | 标杆（审计留的"非 dict 返回 False 会放行"注释仍在：`:4873-4874` vs `:5966`，实际不可达） |
| S10 | `pet_dialogs.py:3401-3420 AISettingsDialog._save` + `桌宠.py:5101-5127 apply_ai_settings` + `pet_ai.py:223-270 apply_settings` | `_apply_call(..., strict=True)`；失败→`_save_failed`（519-532：**不关窗**，写 `_save_hint` 状态行 3319-3322，回调给了原因再弹 `_warn`）；成功 `accept()` + 气泡 msg | ✅ | 3410-3420；519-532；5113-5127；236-270 | **是** | — |
| S11 | `pet_dialogs.py:4400-4416 BubbleStyleDialog._save` + `桌宠.py:4920-4961 apply_bubble_style` | 同上（`_save_hint` 4354-4357）；成功气泡「气泡样式已更新~（新样式从下一条气泡开始）」 | ✅ | 4410-4416；4927-4961（写失败回退 cfg + 返回 (False, 原因)） | **是** | — |
| S12 | `pet_dialogs.py:5188-5200 PhysicsDialog._save` + `桌宠.py:4501-4547 apply_physics` | 同上（`_save_hint` 5180-5183）；**「值未变」不再静默**：`:4522-4523` 返回 `(True, "物理参数没有改动")` → 对话框气泡（5200） | ✅ | 5194-5200；4513-4547 | **是** | — |
| S13 | `pet_dialogs.py:5751-5758 VoiceDialog._on_bind_changed` | 失败 `_warn`；成功气泡「绑定已保存~」 | ✅ | 5754-5758 | **是** | — |
| S14 | `pet_dialogs.py:5898-5908 VoiceDialog._import` | 取消静默；失败 `_warn`；成功 `_refresh_rows()`（行标记「—」→「✓ 已配」，5885-5889）**+ 气泡「「X」的事件片段已配好（立即生效）」** | ✅ | 5899-5908（docstring 点名 **S14**） | **是** | — |
| S15 | `pet_dialogs.py:5918-5932 VoiceDialog._clear` | **`_confirm` 已补**（5921-5925，带事件名 + "只解除引用不删磁盘文件"）；失败 `_warn`；成功 `_refresh_rows()` + 气泡「已清除「X」的事件片段（音频文件没删）」 | ✅ | 5919-5932（docstring 点名 **P3-5 / S15**） | **是** | — |
| S16 | `pet_dialogs.py:3808-3836 SoundPanel._on_slot` + `桌宠.py:4680-4710 apply_sound_group` | `set_slot` 失败 `_warn` + 回滚；`_apply_call(..., strict=True)`；失败 `_save_failed`；成功气泡「音效组已更新~」 | ✅ | 3821-3836（注释点名 **S16 / L2-1**）；4691-4710 | **是** | — |
| S17 | `pet_ai.py:82-123 AIService.set_api_key` | 空 Key→气泡**「没有输入 Key，什么都没改~（要清空请用菜单「清除DeepSeek API Key」）」**（100-106）；写盘失败→气泡「Key 没能保存：…」（116-121）；成功→气泡「记住啦！可以和我聊天了~」（123） | ✅ | 98-123（注释点名 **S17**） | — | 标杆 |
| S18 | `pet_ai.py:272-304 AIService.set_chat_rounds` | 写失败→气泡「对话记忆没能保存：…」；成功两种气泡（「记住最近 N 轮对话啦~」/「不带记忆啦…」） | ✅ | 285-304 | — | 标杆 |
| S19 | `pet_balance.py:360-374 set_budget`、`:376-384 set_balance_alert` | 取消 `val is None` → return；成功气泡「预算 X 元…／余额预警 X 元…」（含"提醒已关闭"分支） | ✅ | 370-374；380-384 | — | 标杆 |
| S20 | `pet_balance.py:386-415 BalanceService.add_manual_record` | **第 6 轮已修**：`pet_dialogs.AmountNoteDialog` + `modal`（399-401）；金额 > 0 → 气泡**「记好啦：X 元」**（406）；≤ 0 → 气泡**「零元就不记啦…（真的没有记）」**（409）；异常→日志 + 气泡「「记一笔」打不开：…」（410-415） | ✅ | 386-415（docstring 点名 **S20 / P3-3**）；配套 `tests/test_balance_feedback_v280.py`（5 条，含"金额不大于零_给提示且绝不记账"） | **是** | — |
| S21 | `pet_dialogs.py:6446-6472 set_frame_max` | 手工 `WindowStaysOnTopHint` + `raise_` + `activateWindow` + `setFocus`（6455-6459）；成功后气泡**「帧上限改为 N 帧啦~」**（6472） | ✅ | 6448-6472 | — | 标杆 |
| S22 | `pet_dialogs.py:3661-3682 RolePanel._set_active` | 未选中 `_warn`；`_apply_call` 失败→`_save_failed`（不关窗 + 状态行 / 警告框）；成功 `_refresh` + 气泡「已切换到角色「X」」 | ✅ | 3664-3682（注释点名 **S22**） | **是** | — |
| S23 | `pet_dialogs.py:3707-3719 RolePanel._reset_default` | 失败→`_save_failed`；成功 `_refresh` + 气泡「已恢复默认角色」 | ✅ | 3712-3719（注释点名 **S23**） | **是** | — |
| S24 | 同 N18（`桌宠.py:2523-2597`） | 同 N18 | ✅ | 同上 | — | 标杆 |
| S25 | 5 处入口：`pet_dialogs.py:5203-5211 open_physics`｜`桌宠.py:1988-2001 _open_behavior_dialog`｜`:2003-2010 _open_idle_dialog`｜`:2061-2069 _open_alarm_dialog`｜`pet_balance.py:417-433 open_ledger` | 前 4 处→`pet_dialogs._dialog_failed`（6285-6292：`log_error` + `_warn` 中文警告框「「X」打不开：…（详情见 error.log）」）；三处裸 `.exec()` 已改成 `pet_dialogs.modal(...)`（1999 / 2008 / 2067）；第 5 处 `pet_balance` 按同口径用**气泡** + 日志（不 import 私有助手，425-433） | ✅ | 5205-5211；1998-2001；2007-2010；2066-2069；425-433 | **是** | — |

### 1.5 本节统计

| 判定 | 条数 | 哪些 |
|---|---|---|
| ✅ 有可见反馈 | **58** | N1–N8、N10、N11、N14、N16–N18；D1–D10、D12、D13、D14、D15、D16、D17、D18；E1–E4；S1–S14、S16–S25 |
| ⚠️ 弱反馈（有间接变化、无明确成功回执） | **5** | **N12、N13、N15、D11**（4 条 ∈46）+ S9 的不可达分支（不计入判定，仅备注） |
| ❌ 无（含"无入口"） | **2** | **N9**（无入口，∈46）、D12 的"未选中静默"分支（裁决不做） |
| 合计 | 65 | 与 §2 四张表行数一致 |

---

## 2. 「15 行未覆盖」重建清单

> **⚠️ 本清单为主代理核对后重建，非原始报告原文。**
> 质量审查报告**至今没有落成仓库文件**（我独立复核：`L3-[0-9]` / `15 行未覆盖` / 文件名 `*质量* / *审查* / *review*` 在仓库与 `~/.dsh` 全部 0 命中）。下面是我按 `audit_checklist_completeness_v280.md` 的口径，**把审计 §3 的 25 条 + §2 的四张表对着现树代码逐条重判**得到的结果。

### 2.1 审计 §3 修复清单 25 条 —— 逐条判定

| ID | 判定 | 现树证据（句柄 @ 行） |
|---|---|---|
| P0-1 | ✅ **做了** | `build_role_meta_dialog` `6423-6425`：`setDefault(True)` + 两条 `clicked.connect` 已补 |
| P1-1 | ✅ 做了 | `AISettingsDialog._save` `3410-3420`（strict + `_save_failed`→不关窗）；`桌宠.apply_ai_settings` `5113-5127` 返回 `(ok, msg)`；`pet_ai.apply_settings` `236-270` 返回二元组 |
| P1-2 | ✅ 做了 | `BehaviorDialog._export` `2964-2979`：未选中 `_info`、成功 `_toast` |
| P1-3 | ✅ 做了 | `BehaviorDialog._delete` `2926-2940`：`_confirm` + 气泡 |
| P1-4 | ✅ 做了 | `BubbleStyleDialog._save` `4410-4416`、`PhysicsDialog._save` `5194-5200`；`桌宠.apply_bubble_style` `4927-4961` 返回二元组；`apply_physics` `4513-4547`「值未变」也返回 `(True, msg)` |
| P1-5 | ✅ 做了 | `_delete_bad_one` `5086-5092`、`_delete_all_bad` `5104-5110`：返回值 `(ok, err)` / `(n, err)` 都接住 |
| P1-6 | ✅ 做了 | `BehaviorDialog._del_step` `2786-2792`：lambda → 具名方法 + 未选中 `_warn` |
| P1-7 | ✅ 做了 | 5 处入口全部有用户提示（见 S25 行）；`_dialog_failed` `6285-6292` |
| P1-8 | ✅ 做了 | `_save_line` `4680-4687` + `_clear_line_filters` `4689-4694` + `_select_line` `4696-4706` |
| P1-9 | ✅ 做了 | `BehaviorDialog._select_behavior` `2904-2914`、`SoundPanel._select_fragment` `3933-3943`、`VoiceAssetPanel._select_asset` `4038-4048`、`IdleDialog._select_action` `6196-6206`（全部 `scrollToItem`） |
| P2-1 | ✅ 做了 | 审计点名的 10 处删除全部有「已删除…」气泡：3684 / 3906 / 4069 / 4708 / 4728 / 4859 / 4904 / 2916 / 3140 / 6183 |
| P2-2 | ✅ **做了（本次逐条核完）** | 审计点名的 9 处：行为保存 2902、音频重命名 3904、素材重命名 4067、台词保存 4687、对白名称 4882、绑定下拉 5758、音效组槽位 3836、语音导入 5908、语音清除 5931 —— **9/9 都有气泡**。这就是 `audit_feedback_v270.md` §5 第 7 行"部分已做 / 未逐条核对"指向的那一批，**现已逐条核完** |
| P2-3 | ✅ 做了 | `SoundPanel._rename` `3894-3897` 空名 `_warn`；`pet_ai.set_api_key` `100-106` 空 Key 气泡（**明确拒绝加 `sk-` 前缀校验**，见 review_task_v270:12） |
| P2-4 | ✅ 做了 | `_add_frame_action` `2395-2402`：先判取消再判 <2 |
| **P2-5** | ⚠️ **部分做** | 6 处静态输入框 → **5 处已改** `_ask_text / _ask_item`（`:376-401`；用例 `test_dialogs_feedback_v280.py::test_static_input_dialogs_are_gone_except_the_frame_action_one`）；**剩 1 处**：`RoleEditDialog._add_frame_action` `2407` 仍是 `QInputDialog.getText`，**已在 `:373-375` 报备**（既有用例 `test_dialogs_more_v24.py` 用 `monkeypatch(QInputDialog, "getText")` 驱动它，改真 modal 会在 offscreen 挂死） |
| **P2-6** | ❌ **未做** | `AISettingsDialog._clear_long_term` `3390-3399` **仍是裸 `QMessageBox.question / information / warning`**，参数与文案一字未动（计划 §7.5-L7 已把它排进第 6 轮） |
| P2-7 | ✅ 做了 | `_add_proc_action` `2488-2499`：`ok / cancel` 两按钮 + `stick_buttons` + `modal` |
| **P2-8** | ❌ **未做（按原口径）** | 原口径是"表单区顶部**内联状态标签**「● 新建中（未保存）」"。现树：**全仓 grep `新建中` = 0 命中**；替代物是**瞬时气泡**，且只覆盖两处：`LinesDialog._new_line` `4653`、`BehaviorDialog._new` `2777`；**闹钟「新建」`AlarmDialog._new` `3071-3079` 仍然零反馈**（清表单 + `setCurrentRow(-1)`，本来就空时屏幕上什么都不变）——计划 §7.5-L7 写的"含 N2 / N4 / N5"只兑现了 N2 / N5 的弱化版，**N5 对应的是"行为"，N4（新建对白）只有 4857 的保存后气泡** |
| **P2-9** | ❌ **未做**（= N9） | 人设行 `3242-3264` 无新建入口、无路径提示；计划 §7.5-L8 裁决 **不做** |
| P3-1 | ✅ 做了 | `_set_active` `3661-3682`、`_reset_default` `3707-3719` |
| P3-2 | ✅ 做了 | `SoundPanel._on_slot` `3808-3836`（strict）+ `桌宠.apply_sound_group` `4691-4710` 返回 `(ok, msg)` |
| P3-3 | ✅ 做了 | `pet_balance.add_manual_record` `398-415`（异常分支也给了气泡） |
| **P3-4** | ⚠️ **部分做** | 主批已修（我逐处核过 14 个"未选中"出口，全部有 `_warn`：3688、3642 / 3741、3874 / 3910、4052 / 4071、4712、4860、4909、2918、2789、6185、2526、7331 / 7371 / 7399、6857）。**残项 1 处**：`AlarmDialog._delete` `3142-3146` 未选中**静默 return**，注释写明被既有用例 `test_alarm_dialog_update_failure_and_delete_without_selection` 钉住（**裁决：不补**）。另发现审计没点名的同类：`LinesDialog._move_line` `4634-4635`「`j == row`（已到顶 / 底）→ 静默 return」 |
| P3-5 | ✅ 做了 | 清空引用 `5071-5078`、清除片段 `5921-5932`、移除成员 `4912-4925`、删自定义动作 `2532-2550` |
| P3-6 | ✅ 做了（换方案） | 文案没改，改成 `_btn_tip` tooltip 对照表（常量 `277-278`、实现 `281-293`、9 处调用：1330 / 1988 / 1989 / 2626 / 2647 / 3037 / 4571 / 4770 / 4796）——审计给的就是"改文案**或**加 tooltip" |

**§3 口径合计：做了 20 条 ｜ 部分做 2 条（P2-5、P3-4）｜ 未做 3 条（P2-6、P2-8、P2-9）。**

### 2.2 §5「公开未做清单」14 行 —— 逐行下落（第 5 轮写的，现在是否还成立）

| §5 行 | 内容 | 现树判定 | 证据 |
|---|---|---|---|
| 1 | D9 回执 | ✅ **已闭** | `_remove_member` `4925` 气泡 |
| 2 | D14 确认 + 回执 | ✅ **已闭** | `_del_action` `2532-2537` 确认 + `2548` 气泡 |
| 3 | S14 / S15 | ✅ **已闭** | `5908` 气泡；`5921-5931` 确认 + 气泡 |
| 4 | S20 / P3-3 | ✅ **已闭** | `pet_balance.py` `398-415`（气泡三分支）+ 5 条新用例 |
| 5 | P2-5 静态输入框 | ⚠️ **部分闭**（5/6） | 仅剩 `2407`（已报备） |
| 6 | P2-7 / N13 | ⚠️ **部分闭** | P2-7（取消按钮）✅ `2488-2496`；**N13 的"成功回执"仍未做**（`2514-2516` 无 toast） |
| 7 | P3-4 / P3-5 | ⚠️ **基本闭**：P3-5 全做；P3-4 只剩闹钟一处（裁决不补） | 见 2.1 的 P3-4 / P3-5 |
| 8 | P3-6 文案 | ✅ **已闭**（tooltip 方案） | `277-293` + 9 处调用 |
| 9 | N14 / N15 | ⚠️ **部分闭**：N14 ✅ `1506-1507`；**N15 仍无回执** `2833-2836` | — |
| 10 | 两条未实测 | ⚠️ **部分闭**：① `setCurrentRow` 滚进视口——现树已不依赖 Qt 行为，四处 `_select_*` 显式 `scrollToItem`（**结构性消解**，但仍未真 GUI 实测"在视口内"）；② 静态 `QInputDialog` 前台锁——**仍未实测**，也没有实测记录落盘 | `3933-3943`、`4038-4048`、`4696-4706`、`6196-6206`；`2407` |
| 11 | F5 另一种修法 | ✅ **已闭** | `桌宠.show_bubble` `3756-3774` **如实回报可见性**；`_toast` `411-440` + `_toast_fallback` `443-460` |
| 12 | F4 同族三处先写盘 | ✅ **已闭** | `pet_ai.set_ai_enabled` `42-80`、`set_api_key` `107-123`、`set_chat_rounds` `289-304`（"先写副本→落盘→成功才 `cfg.update`"）+ `tests/test_ai_write_first_v280.py` 6 条 |
| 13 | 兼容 P3-3 裁决不删 | ✅ 裁决保持（`apply_physics` `4540-4547` 气泡 + 对话框 `_toast` 会各来一次；`Bubble.show_text` 幂等，见注释） | `4540-4547` |
| 14 | L2-2 A/B 变异入库 | ✅ 已闭环（§5 自己已划掉） | — |

### 2.3 【重建版】仍未做 / 部分做 清单

> **声明：本清单为主代理核对后重建，非原始报告原文。** 判定依据 = 上面的 §2 全表 + §3 25 条 + §5 14 行，对着 **sha256 `7E6B0F880CD2` 的 pet_dialogs.py** 逐条读码。

| # | 项 | 类别 | 现树事实（句柄 @ 行） | 现树里"无反馈"到什么程度 | 计划里的落点 / 建议 |
|---|---|---|---|---|---|
| **R1** | **P2-6 / D16** | **未做** | `AISettingsDialog._clear_long_term` `3390-3399` | **有反馈**（裸 QMessageBox），只是没走统一框 → 深色主题下样式不一致 | 计划 §7.5-L7 已排 **第 6 轮**；建议本轮补或明确"不做" |
| **R2** | **P2-8 / 闹钟「新建」** | **未做** | `AlarmDialog._new` `3071-3079` | **真的点了没反应**：表单本来就是默认值时，点「新建」屏幕上零变化（列表无选中时连"取消选中"都看不见） | 计划 §7.5-L7 排 **第 6 轮**（"内联状态标签，含 N2 / N4 / N5"）；现树只做了台词 / 行为两处的**气泡版**，且**没有内联标签**。建议：要么补标签，要么把这条改成"气泡版已完成、标签不做" |
| **R3** | **P2-9 / N9** | **未做（= 裁决不做）** | 人设行 `3242-3264` | 无入口 = 无处可点（不是"点了没反应"） | §7.5-L8 裁决 **不做** → 建议**销账**，别继续挂在"未归位" |
| **R4** | **P2-5 静态输入框** | **部分做** | 仅剩 `RoleEditDialog._add_frame_action` `2407` | 不影响"点了没反应"；是**前台锁风险未实测** | 已报备例外（`373-375`）+ 用例钉住；建议**保留并销账** |
| **R5** | **P3-4 残项 / 兼容 §5.F.19** | **部分做（= 裁决不补）** | `AlarmDialog._delete` `3142-3146` | 未选中时点「删除」= 零反应（**但这是被既有断言钉住的有意行为**） | 建议在计划里写成"**明确不做**"并注明被哪条用例钉住 |
| **R6** | **N12**（＋帧动作… 成功无回执） | **部分做** | `RoleEditDialog._add_frame_action` `2437-2438`（无 toast）；`_refresh_act_list` `2379-2389` 不选中不滚动；`_act_list` 限高 `1981` | 成功后只有当行多一行；**动作多时新条目在 80px 视口外** → 用户视角等同"点了没反应" | 计划 §7.6 第 2 条的"二选一"未覆盖到它 → 建议**第 6 轮 A2 同族**补 `_toast` + `scrollToItem` |
| **R7** | **N13**（＋合成… 成功无回执） | **部分做** | `_add_proc_action` `2514-2516`（无 toast），同上 80px 列表 | 同 N12 | 同上 |
| **R8** | **N15**（添加步骤 成功无回执） | **部分做** | `BehaviorDialog._add_step` `2833-2836`（无 toast） | 步骤列表加一行（可见），但没有"已添加"信号 | §7.6 第 2 条**点名 N15** → 建议第 6 轮 A2 同族补，或明确"不做" |
| **R9** | **D11**（删除选中步骤 成功无回执） | **部分做** | `BehaviorDialog._del_step` `2792`（`takeItem`，无 toast） | 行消失（可见）；P1-6 原要求"至少未选中提示"**已满足** | 建议：与 R8 一起补一句气泡，或明确"不做" |
| **R10** | **两条未实测（②）** | **未做** | `2407` 静态 `QInputDialog`；无任何实测记录落盘（`_dev/probe_*` 里没有前台锁的探针） | 不是反馈问题，是**证据缺口** | 建议第 6 轮 A 路如实标注"测不了"并保留在清单（计划 §7.1 第 10 行已经这么要求） |

**重建版条数：10 条**（未做 3 + 部分做 7）。
若把"同一件事的两份编号"拆开计（P2-6 / D16 拆 2、P2-9 / N9 拆 2，其余已各按 1 行计），最多 **12 行**；若再把已裁决的"兼容 P3-3 双气泡"（`4540-4547`）也算一行 → **13 行**。

### 2.4 为什么我凑不出「15 行」——差额说明（**不猜**）

- 我另外做了一次**更接近"第 5 轮未覆盖"**的重算：用 `git show da7f049:pet_dialogs.py` 与现树做 AST 级 `_toast` 现场对比。**v2.7.0 提交时 `_toast` 已覆盖 34 个方法**；第 6 轮只新增了 4 个与审计有关的（`RoleEditDialog._del_action`=D14、`LinesDialog._remove_member`=D9、`VoiceDialog._import`=S14、`VoiceDialog._clear`=S15）+ 3 个插件索引来源区的。
  → **第 5 轮结束时"46 条里仍然没有成功回执"的只有 8 行：N12、N13、N15、D11、D9、D14、S14、S15。** 8 ≠ 15。
- 换言之：`audit_checklist_completeness_v280.md` §3.3 里标成"❌ 未归位（低）"的 **N2 / N4 / N5 / N8 / N10 / N11 / N16**，**代码其实早在 v2.7.0 就有气泡回执**（N2 `4653`、N5 `2777`、N7 `3868`、N8 `4036`、N10 `3138`、N11 `6181`、N16 `4902`，全部在 `da7f049` 里就存在）。那些行的"未归位"是**计划层没排轮**的意思，**不是"没做"**。请主代理不要把它们当成"15 行"里的成员。
- **结论：原始报告的"15 行"具体身份无法从现树复核**（全仓无该表述、无原文文件）。我能给的最接近的两种切法是：**"针对现树的未做 / 部分做" = 10 行（§2.3）**；**"第 5 轮结束时仍无回执" = 8 行**。两者都不等于 15 —— 这不是我没查，是**源头那份报告不在仓库里**（`audit_checklist_completeness_v280.md` §0.2 限制 1 已经下过同一个结论）。

---

## 3. 结论（一句话 + 数字）

**这 46 条里，现在真正"点了没反应"的是 1 条** ——

- **46 条口径**：`AlarmDialog` 的「**新建**」（R2，`pet_dialogs.py:3071-3079`）是**唯一一条**在常规交互路径上"点下去屏幕上什么都不变"的（表单本来就是默认状态时）。它原来属于 N2 / N5 同一族（P2-8），**N2 / N5 已在现树用气泡解决，闹钟这一处漏了**。
- 另有 **4 条**（N12 / N13 / N15 / D11）属于"**有反应但缺成功回执**"，其中 **N12、N13** 因为动作列表限高 80px 且不滚动，**在动作较多时同样会表现为"点了没反应"**；N15、D11 的列表变化就在按钮旁边，肉眼可见。
- 其余 **41 条全部有用户可见反馈**（气泡 / 弹窗 / 状态行 / 选中 + 滚动 / 置灰之一）。
- 不在这 46 条里、但同样"点下去没反应"的还有 **2 处**：`AlarmDialog._delete` 未选中时（`3142-3146`，**有意静默、被既有用例钉住**）、`LinesDialog._move_line` 已到顶 / 底时（`4634-4635`，**无人认领**）。
- **65 行全表口径**：✅ 58 ｜ ⚠️ 5 ｜ ❌ 2（N9 无入口 + D12 未选中静默）。

---

## 4. 可复跑命令（全部只读；python 一律 `-B`）

    1) 快照：Get-FileHash -Algorithm SHA256 pet_dialogs.py, 桌宠.py, pet_ai.py, pet_balance.py
    2) 全量 _toast 调用点（38 处）：rg -n "_toast\(" pet_dialogs.py
    3) 静态输入框残留：rg -n "QInputDialog\.(getText|getItem|getInt|getDouble|getMultiLineText)\(" --glob "*.py"
       → 产品代码只剩 pet_dialogs.py:2407
    4) 导出入口：rg -n "getSaveFileName" --glob "*.py" → 产品代码 3 处（2970 / 4278 / 桌宠.py:2308）
    5) 第 5 轮覆盖度（AST 级）：python -B -c "…读 git show da7f049:pet_dialogs.py 与现树，各自 ast 遍历取含 _toast( 的外层函数名…"
       （本次用的就是这个；结果：OLD 34 个方法，NEW 多出 6 个）
    6) 质量审查报告定位：rg -n "L3-[0-9]|15 行未覆盖" -g "*.md" .
       → 0 命中

## 5. 我没做到的（诚实声明）

1. **没跑 GUI / 没跑 pytest**：所有"看得见 / 看不见"都是**源码级**判定，未实测气泡在真实桌面上的可见性（z 序那条引用的是仓内既有探针 `_dev/probe_bubble_z_order_v270.py`）。
2. **没验证 `_toast` 在真实点击流里的调用次数**：只做了静态调用点核对；"一次动作一句反馈"是否真的只弹一条（例如 S12 会同时走主窗 `show_bubble` 与对话框 `_toast`）未实测，只按 `Bubble.show_text` 幂等的注释接受。
3. **没恢复质量审查报告原文**，因此 §2.3 的"10 行"是**重建**，与原文的"15 行"**不保证同集合**；差额原因见 §2.4。
4. **没审 `pet_plugin_host.py` 内部**（插件安装 / 卸载的落地细节不在本次范围，与审计口径一致）。
5. **行号会漂**：全部行号对应 §0.1 的哈希快照；第 6 轮仍在写 `pet_dialogs.py`，请按**句柄名**复核。
