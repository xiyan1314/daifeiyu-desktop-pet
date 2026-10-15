# v2.8.0 第 6 轮任务书（插件分发闭环 + 反馈清账）

基线：HEAD `da7f049`（v2.7.0 已发布，公开 CI #55 绿）。护栏：pytest **1161** · v13 **273/0** · 静态 **0/0** · 变异门 **295 锚点 / 坏 0**。

本轮两件事：**① 插件分发 Phase 3（远端索引接线）** ② **把上一轮的公开欠账清干净**（`_dev/audit_feedback_v270.md` §5）。

> **另有两批口头追加**（主代理 2026-10-15，此前**不在本文件里、只在会话消息里**）——本文件全文 grep `D9` / `D14` / `S14` / `S15` / `S20` / `P3-3` / `pet_balance` / `未实测` / `setCurrentRow` / `视口` **全部 0 命中**（证据：`_dev/audit_checklist_completeness_v280.md` §1.1-U1/U2、§4.1）。按 `_dev/plan_v270_rounds.md` 第四节流水新增的第 **11** 步「**口头追加 ≠ 文件落地**」，现**原样落盘**为下面的《代理 A · 追加项》与《代理 B · 追加项》两节。

## 六条铁律（现行，缺一不可）
1. 绿色版目录里调 python.exe 一律加 `-B`；**语法检查用 `ast.parse`，别用 `py_compile`**。
2. 跑全量前确认 `_dev/.mutation.lock/` 不存在；**别在别人跑测试时下结论**。
3. **测试断言不许依赖机器速度**（注入每单位固定成本 → 断言结构性事实）。
4. **契约必须双向覆盖**；**不许放宽任何既有断言**。
5. 定版前对着出货修订整批复跑全部证据（`_dev/mutate_batch_v270.py`）；SPEC-BAD / ANCHOR-LOST / NOT CAUGHT / WRONG TEST 一律不许当通过。
6. **变异验证必须在影子副本里做，不许原地改真仓**（原地改会制造 1~2 秒"真仓处于变异态"窗口，并发的全量 pytest 撞进去就看到假红）。

## 本轮统一口径（两路都要守）
- **一次用户动作一句反馈**（成功用气泡 + 选中所属条目；失败不关窗 + 给原因；入口打不开用 `_dialog_failed`）。
- **`(ok, msg)` 契约**：跨领地回调一律返回**二元组**；判据写 `if not (isinstance(res, tuple) and res[0])`，**`None` 也算失败**，**不要写 `is not True`**。
- **动效时长进令牌**：本轮涉及的任何时长/曲线，**先在 `pet_dialogs.py` 或公共处集中定义常量**（本轮次数少，先集中，第 7 轮再抽 `pet_motion.py`），**不许散落魔法数字**。
- **默认零打扰**：任何定时/后台行为都不得在用户没动作时弹窗或抢焦点。

---

## 代理 A · 交互面（`pet_dialogs.py` + `桌宠.py`）

**领地**：`pet_dialogs.py`、`桌宠.py`、新建 `tests/test_dialogs_feedback_v280.py`。
**不碰**：`pet_plugin_index.py` / `pet_config.py` / `pet_ai.py`（那是 B 的）。

### A1 插件 Phase 3 的**设置入口与交互**（后端由 B 提供，见下面的接口约定）
- 在插件管理对话框里加一个「**索引来源**」区：显示当前用的是「随包索引」还是「远端索引（URL）」；可填/可改/可恢复默认。
- **地址校验与可读报错**：非 https、指向本地路径/file://、空、超长 → **当场拒绝并说清为什么**（不要只把原始异常抛给用户）。
- **刷新失败的人话提示**：网络不可用 / 404 / sha256 不符 / 体积超限 → 每条一个明确文案，并**保留可回退到「只读随包索引」的路径**。
- **刷新成功后**：明确告诉用户「远端索引已更新（共 N 个插件）」，并**列表真的刷新**（照抄 `PluginManagerDialog` 既有的安装/卸载/回滚那套口径）。
- ⚠ 不要自己发明下载逻辑——**一切取数走 B 提供的接口**。

### A2 反馈清账（`_dev/audit_feedback_v270.md` §5 公开清单里属于对话框的项）
- **P2-5 静态 `QInputDialog.getText`**（声音素材重命名等 6 处）→ 统一到项目的 `_warn/_info/_confirm` 口径（深色主题一致）。⚠ **先查既有用例怎么驱动这些路径**：`tests/test_dialogs_v24.py` 等处可能有 monkeypatch 静态方法的用例，**改成真 modal 会让它挂死**——若确实会，**保留原样并在报告里点名**（铁律 4：不许放宽既有断言），不要硬改。
- **P2-7 合成框没有「取消」按钮** → 补上（与其它内联框一致），取消要能真的放弃编辑且不留半截。
- **P3-5 清空引用 / 清除片段无确认** → 按既有 `_confirm` 口径补二次确认（带对象名与后果），成功后给回执。
- **P3-6 文案混用** → 同一动作在同一批对话框里用同一套措辞（列出你统一的对照表）。
- **N12 帧动作取消被误报** → 已在上轮修过（取消→静默）；本轮复核仍成立即可。
- **N13「＋合成…」内联框** → 与 P2-7 是同一处，一起做。
- **N14 导入向导「＋添加形态」无提示** → 成功后给回执（气泡或内联状态行）。

### A3 `_toast` 的行为层（上一轮只改了文档口径，行为层留作公开欠账）
- `桌宠.show_bubble` 在 `_closing` 早退分支**要返回 False**（现在返回 True 却什么都没弹），并给 `_toast` 一个**兜底**（例如失败时写一条限流日志，或退化为对话框内状态行）。
- **验收**：`_closing=True` 时 `_toast(...)` 返回 **False**；且此时用户仍能**在某处**看到该反馈（兜底证据）。**变异**：把早退分支改回返回 True → 必须红。

## 代理 A · 追加项（主代理 2026-10-15 口头追加，现落盘）

> 这 6 项此前**只存在于会话消息里**：`_dev/plan_v270_rounds.md` §7.1/§7.3 早已判给 A，但本任务书 grep 0 命中（`_dev/audit_checklist_completeness_v280.md` §1.1-U1、§4.1）。**都在 `pet_dialogs.py`，与手上同族，去重后做。**

- **D9 · 对白「移除」成员**：已有二次确认（第 5 轮 P2-1 口径），**补成功回执**——移除后不能只有列表变化。
- **D14 · 角色编辑「删除」自定义动作**：**补确认 + 回执**。⚠ 它是**暂存态**（取消可整体回滚），**确认文案不许写成不可逆**（不出现"永久删除 / 无法恢复"一类措辞）。
- **S14 / S15 · 语音面板**：「导入…」事件片段**补成功回执**；「清除」片段**补二次确认 + 回执**（走 `_confirm` 口径，带对象名与后果）。
- **P2-8 ·「新建」内联状态标签**：第 5 轮只做了"选中 + 回执"（现树 `pet_dialogs.py:4680-4694` 一带），本轮**补常驻的"新建中"状态标签**，**照抄仓库里已有的内联标签做法**（不要新造一种样式）。同一件事在审计里分散登记为 **N2**（台词「新建」）/ **N4**（台词页「新建对白」）/ **N5**（行为「新建」）/ **P2-8**（台词 / 行为 / 闹钟新建）→ **一并覆盖，不要只做一处**。
- **D16 / P2-6 ·「清除长期记忆」改用统一确认框（本轮做）**：现树 `pet_dialogs.py:3388-3399` 仍是裸 `QMessageBox.question/information/warning`（没走 `modal()`，也没进 `_confirm/_info/_warn` 口径）→ 统一到项目口径。
  - ⚠ 既有用例 `tests/test_dialogs_v24.py:135-159`（`test_ai_settings_clear_long_term_keeps_history`）是靠 monkeypatch `QMessageBox.question` / `QMessageBox.information` 驱动的，改成 `_confirm` 会走真 modal 挂死 —— **允许改该用例**，但**改法必须是加强**（例如 monkeypatch `pet_dialogs.modal`，或给 `_confirm` 注入替身）；**不许删断言、不许放宽**（铁律 4）。做不到就保留原样并在报告里点名。
- **按钮审计 P3-5 · `open_idle` 死入口**（**注意：这是"按钮审计的 P3-5"**，与上面 A2 那条"**反馈审计** P3-5 = 清空引用 / 清除片段确认"是两件事，见 `plan_v270_rounds.md` §7.5-L9/L10）：`pet_dialogs.py:6316 def open_idle(pet)` 全仓**零引用**（唯一"零引用且可疑"的 UI 定义）。**二选一**：① 给它一个真实 UI 入口；② 删掉 / 合并到实际走的那条路径（`pet._open_idle_dialog`）。动手前先确认它不是外部入口（插件 API / 文档里承诺过）。**报告里说清选了哪个、为什么。**
- **两条未实测（两条都归 A）**：计划 §7.1 曾写"A/B 各一条"、§7.3 写"都给 A"（自相矛盾，`audit_checklist_completeness_v280.md` §2-C1）——**以本裁决为准：两条都归 A**（`plan_v270_rounds.md` §7.1 那行已改）。
  1. **`QListWidget.setCurrentRow` 是否自动滚进视口**：在它自己的对话框用例里顺手验（现树 `pet_dialogs.py` 有 13 处 `setCurrentRow`）。**能断言"新条目在视口内"就补断言**（用 `visualItemRect` / `viewport().rect()` 这类**结构性**判据，别依赖机器速度）；**不能就如实标注**"仍未实测"并保留在公开清单里。
  2. **静态 `QInputDialog` 在某窗口下的前台锁行为**：实测它**会不会锁住前台**（这正是 P2-5"值不值得改成真 modal"的判据）。**结论写进报告**：实测命令 / 观察到的现象 / 结论，三行。

---

## 代理 B · 插件后端与配置（`pet_plugin_index.py` + `pet_config.py` + `pet_ai.py` + **`pet_balance.py`**）

**领地**：`pet_plugin_index.py`、`pet_config.py`、`pet_ai.py`、**`pet_balance.py`（主代理 2026-10-15 追加扩张，见下面《代理 B · 追加项》）**、新建 `tests/test_plugin_phase3_v280.py`、新建 `tests/test_ai_write_first_v280.py`、新建 `tests/test_balance_feedback_v280.py`。
**不碰**：`pet_dialogs.py`、`桌宠.py`（A 的）。

### B1 远端索引**真的能跑**（Phase 3 的核心）
**给 A 的接口约定（先定死，再实现）**：

- `set_remote_base(url) -> (ok: bool, msg: str)`：校验并保存/清除远端基址（空串 = 回到随包索引）。
- `refresh(force=False) -> (ok: bool, msg: str, count: int)`：取远端 `index.json` → 校验 → 落地为本地索引缓存 → 返回可用插件数。
- `source_info() -> dict`：`{"kind": "bundled"|"remote", "url": str, "updated_at": str}` 供 A 显示。
**保留 v2.6.0 已做的硬化，不许推翻**：只收 https · 远端索引不许指向本地路径/file:// · 体积上限**前置**（分块累计 / Content-Length 先看）· 下载后**核对 sha256 与 bytes** 不符即拒并删临时文件 · 解包前再走 `validate_plugin_zip` · `url2pathname` 与 `..`/空段拒绝。
**测试（不许真联网）**：走已有的**可注入 `fetch(url)->(bytes|None, err)`**，覆盖：正常取回 · sha256 不符 · bytes 不符 · 超过体积上限（**前置判定必须生效**）· 非 https 拒绝 · 远端指向本地拒绝 · 404/超时的人话错误 · 刷新失败后**仍能用随包索引**。
**真联网的那一次我（主代理）自己跑**：用**本仓库自己的 raw 地址**做真源（`https://raw.githubusercontent.com/xiyan1314/daifeiyu-desktop-pet/main/plugins/index.json`），核对取回的 sha256/bytes 与本地一致。**你不要在 pytest 里联网。**

### B2 `plugin_index_url` 配置键（`pet_config.py`）
- 加键（默认空 = 随包索引），**默认值不改变任何既有行为**；旧 `config.json` 读入后行为与现在完全一致（**逐字节回归**）。
- 键的落盘走既有的原子写；**写失败要能返回错误**（沿用 v2.7.0 的 `(ok,msg)` 口径）。

### B3 `pet_ai.py` 三处「先改内存再写盘」→ 改成**先写盘成功再提交**
- `set_api_key` / `set_ai_enabled` / `set_chat_rounds`：与 `apply_settings` 同口径（v2.7.0 已用的是：`new = dict(cfg)` → 写盘 → 判错 → **成功才** `cfg.update(new)`）。
- **成功路径必须与改前逐位等价**（内容与**键顺序**都一致），配一条钉住它的用例。
- 失败时：**内存不变** + 如实气泡（不复用成功话术）+ 记日志。

## 代理 B · 追加项（主代理 2026-10-15 口头追加，现落盘）

> 与 A 追加项同因：本任务书此前 grep `S20` / `P3-3` / `pet_balance` **全部 0 命中**（`_dev/audit_checklist_completeness_v280.md` §1.1-U1/U2、§4.1-D5/D6）。**领地已扩到 `pet_balance.py`**（见上面的领地行）——这是本轮唯一的跨出"插件后端"的一处。

- **S20 / P3-3 · 菜单「✏️ 记一笔…」构建失败**：`pet_balance.add_manual_record` 的 `except` 此前只写日志 → **构建失败 = 点了没反应**。改成**用户能看到**：**气泡 + 日志两条都要**（口径同"入口打不开"）。
  - ⚠ **不许 import `pet_dialogs` 的私有助手**（`_toast` / `_info` / `_confirm` / `_dialog_failed` 那一类）——`pet_balance` 与 `pet_dialogs` 领地互斥；走 `pet_balance` 自己的可见出口（宠物气泡 + `error.log`）。
- **同一函数 `amount <= 0` 分支**（含清空后确定）：此前**静默丢弃** → **给提示，且绝不记账**；两件事都要断言（"说了没记" + "账本里真的没有"）。
- **配能真失败的用例**：`tests/test_balance_feedback_v280.py`（领地内）；两条都要满足"还原修复必须红"（铁律 4）。
- **旁证（主代理 2026-10-15 落笔时的现树状态）**：B 已按上述口径实现 —— `pet_balance.py:386-415`（docstring 明写 S20/P3-3：气泡 + 日志、不 import `pet_dialogs` 私有助手、`amount<=0` 明说"这笔没有记"）+ `tests/test_balance_feedback_v280.py`（7159 B）。**本文件此前未登记这两条**，登记在此，免得下轮复核时又变成"无据可查"。

---

## 代理 C · 证据与门（`_dev/**`）

**领地**：`_dev/**`（含新建 `_dev/mutations_agent_c_v280.json` 等）。**不碰任何产品代码与 tests/**。

**这轮的重点（上一轮的教训）**：**从一开始就把变异落成 spec**，不要等收尾再补。
- 为 A/B 的每条新用例写**能真失败的变异**（文本变异，走 `_dev/mutate_check.py` 同一套：`id`/`file`/`old`/`new`/`tests`/`expect_fail`/`why` + 顶层 `repo_fingerprint`）。
- 每条 `old` 必须在当前树**恰好命中 1 次**（`--scan-only` 秒级体检）。**锚点被后续修复挪走是常态**——发现命中 0 或 2 就重锚并写明。
- **A/B 的用例可能还在改**：你可以先把"稳定下来的"落进去，收尾前再补一轮。**回报时要给出：条数 / CAUGHT 数 / 哪些锚点重锚过 / 哪些暂不可构造（附理由）**。
- 更新 `_dev/audit_feedback_v270.md` §5：**本轮做掉的划掉并注明轮次**，没做的保留在公开清单里。

---

## 共同验收（安静窗口、串行）
- `python -B -m pytest tests -o addopts="" -q` → **0 failed**（基线 1161）
- `python -B _verify_v13.py` → **273 项 0 FAILS**
- `python -B _check_static.py`（单跑）→ **0 问题 0 待确认**
- `python -B _dev/mutate_batch_v270.py --scan-only` → 锚点坏 0

**回报格式**：改动清单（句柄为准，行号会漂）· 三项数字 · **每条修复的变异原文**（变异改了什么 / 精确命令 / 失败断言行 / 恢复后是否绿）· **没做到/让步/疑问如实写**（不许写成做完了）。
**不要提交**（我统一提交）；不碰 VERSION / version_info / _verify_green / CHANGELOG / _release_notes_* / 绿色版 / 发布 zip。