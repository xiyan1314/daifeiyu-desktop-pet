# v2.7.0 第 5 轮任务书（反馈修复批次 · 三路并行，领地互斥）

基线：HEAD `9f7fb78`（v2.6.1 已发布，公开 CI 绿）。护栏：pytest **1061** · v13 **273/0** · 静态 **0/0**。

## 必读（三路都读，里面有每条的 行号 / 现状 / 建议修法 / 能真失败的验收）
- `_dev/audit_feedback_v270.md` —— 反馈缺失：完全无反馈 13 条 · 成功后零提示 46 条 · P0 一条；含**现成反馈手段清单**与**标杆实现**（照抄对象）。
- `_dev/audit_buttons_binding_v270.md` —— 按钮接线全量（123 控件）+ 绑定下拉定位。
- `_dev/task_v270.md` §6-7 —— 批次与顺序。

## 通用铁律（六条，缺一不可）
1. 跑全量前确认 `_dev/.mutation.lock/` 不存在；**别在多路并行改树时下结论**。
2. 绿色版目录里调 python.exe **一律加 `-B`**；**语法检查别用 `py_compile`**（它绕开 `-B`），用 `ast.parse`。
3. **测试断言不许依赖机器速度**（注入每单位固定成本 → 断言结构性事实）。
4. **契约必须双向覆盖**。
5. **不许放宽任何既有断言**；每条改动配**能真失败**的用例（变异：把修复注释掉必须红）。
6. 不碰 VERSION / version_info.txt / _verify_green.py / CHANGELOG.md / _release_notes_*.md / 绿色版 / 发布 zip。**不提交**（我统一提交）。如实报告没做到的。

## 反馈口径（A、B 必须统一，否则用户看到两种风格）
- **面板内轻操作**（保存成功、新建成功、删除成功、导出成功）→ 用 **宠物气泡** `pet.show_bubble(text)`（5 秒自动隐藏；`桌宠.py:3700-3709` → `pet_widgets.py:264-289`）+ **列表选中新条目并滚到可见处**（正例照抄 `AlarmDialog:2823-2826`）。
- **失败 / 需要用户决策**（保存失败、删除确认、危险操作）→ 用 **`_warn/_info/_confirm`**（`pet_dialogs.py:305-328`）。
- **入口打不开** → 统一用 **`_dialog_failed`**（`pet_dialogs.py:5677-5684`；同仓 7 个入口已经做对了，照抄）。
- **`_call`（`pet_dialogs.py:280-302`）是最大静默失败通道**：所有走它的地方都要检查返回值。
- 槽函数里**不许弹模态框**（用气泡 + 日志，见 `pet_log.guard_slot` 的口径）。

---

## 代理 A：`pet_dialogs.py` 全部（P0 + P1 + P2 in-file）

**领地**：`pet_dialogs.py`、新建 `tests/test_dialogs_feedback_v270.py`、新建 `tests/test_dialog_buttons_v270.py`。**别的文件一律不碰。**

### A1（P0）导出角色包卡死
`:5809-5812` 的 `btn_ok("继续导出")` / `btn_cancel("取消")` **零 `clicked.connect`** → `modal()` 后关不掉窗口。**修**：接 `accept`/`reject`，`btn_ok` 加 `setDefault`；复核 `pick_role_meta`（`:5768`）的结果读取与 Esc/关闭语义。**用例**：点按钮断言 `result()==Accepted` 并返回四字段 / 点取消返回 None；**注释掉那两条 connect 必须红**。

### A2（P2·防下一次）通用按钮契约用例
新建 `tests/test_dialog_buttons_v270.py`：**AST 扫 `pet_dialogs.py` 里每个 `QPushButton`/`QToolButton`**，必须"有 `clicked.connect`"或"在显式白名单里并写明理由"，否则红。**这条用例必须能抓住 `:5809/:5810` 的修复前状态**（把你修好的两行注释掉 → 必须红）。白名单要写清每条为什么可以没有接线（例如纯展示按钮）。

### A3（P1-1）AI 设置保存静默丢数据
`:3093-3094` 丢弃 `_call` 返回值 + 无条件 `accept()`；失败只在 `:298` 记日志。**影响**：人设正文 / API 地址 / 模型 / max_tokens / 工具开关 / RAG 整批可能静默丢失，窗口照常关闭＝"保存成功"假象。
**接口约定（与代理 B 对齐）**：`PetWindow.apply_ai_settings(...)` 改为**返回 `(ok: bool, msg: str)`**（B 负责改主窗）。**修**：检查返回值；失败 → **不关闭窗口** + `_warn` 显示原因 + 日志。**用例**：让 apply 返回失败 → 断言窗口没关且弹了警告；成功 → 断言关了且**有气泡**。

### A4（P1-2）导出行为 JSON 成功零提示
`:2668-2670` 只有失败分支，成功路径**没有任何分支**；未选中行为还静默 return（`:2662-2663`）。**修**：成功 → 气泡"行为已导出到 <文件名>"；未选中 → `_info` 提示"先选一个行为"；失败保持 `_warn`。**用例**：成功路径断言气泡文案含文件名；未选中断言有提示且没有落盘。

### A5（P1-3）删除行为无二次确认
`:2624-2639` 全程没有 `_confirm`（同仓到处都用）→ 点一下永久删。**修**：加 `_confirm`（带行为名与后果）；确认后删除并**气泡"已删除 X"**。**用例**：确认框返回 False → 断言没删；返回 True → 断言删了且有气泡。

### A6（P1-4）气泡样式 / 物理参数保存双静默
`:3999-4010`、`:4714-4721` 丢弃返回值 + `accept()`；`apply_bubble_style` 成功不弹气泡；**`apply_physics` 值未变则静默 return**（`桌宠.py:4447-4448`）。
**接口约定**：`apply_bubble_style` / `apply_physics` 也改为**返回 `(ok, msg)`**（B 负责改主窗）；"值未变"要返回 **ok=True + msg="没有改动"**（不是静默）。**修**：成功 → 气泡（含"没有改动"）；失败 → 不关窗 + `_warn`。

### A7（P2）绑定下拉空态 + 其余 in-file 无反馈条目
- 绑定下拉（`:5138-5145` → `:5160-5163`）：`except Exception: pass` 改为**记日志 + 空态提示**（例如"还没有配音素材，先到『声音素材』里导入"）；若仓里**确实没有添加素材的入口**，在报告里点名（那是缺功能，不是缺反馈）。
- 另按审计清单补：失效引用单删/全删（`:4627`/`:4640` 丢弃 `delete/delete_many` 返回值）· 行为「删除选中步骤」（`:2377-2380` `takeItem(-1)` 静默）· 角色「设为当前」/「恢复默认」（`:3335-3349`/`:3371-3378`）· 角色/台词/行为/音效/人设 **新建后选中新条目并滚到可见处**（照抄 `AlarmDialog:2823-2826`；反例 `BehaviorDialog:2619-2622`）。
- 新建/删除/保存/重命名/导入/应用各处的"成功后零提示"（审计列了 46 条，**在 `pet_dialogs.py` 里的都要补**）。

---

## 代理 B：`桌宠.py` / `pet_balance.py` / `pet_resources.py`（非对话框那一半）

**领地**：`桌宠.py`、`pet_balance.py`、`pet_resources.py`、新建 `_dev/probe_bubble_z_order_v270.py`、新建 `tests/test_feedback_host_v270.py`。**不碰 `pet_dialogs.py`。**

### B0（先做·5 分钟）气泡与模态度话框的 z 序实测
审计没跑 GUI，**不知道模态度话框打开时宠物气泡能不能压在上面**（两个 `WindowStaysOnTopHint` 的 z 序取决于最近一次 raise）。**这决定 A 的修法**（面板内用气泡还是弹窗）。用真 Qt（offscreen 或真窗口）实测并把结论写进 `_dev/probe_bubble_z_order_v270.py` 的注释与回报——**如果气泡会被模态框压住，立刻告诉我**（我们改口径：面板内成功也用轻量内联标签）。

### B1 `apply_ai_settings` / `apply_bubble_style` / `apply_physics` 返回 `(ok, msg)`
按 A 的接口约定改主窗（`:4963-4965` 等）；**`apply_physics` 值未变时返回 ok=True + "没有改动"**（现在是静默 return，`桌宠.py:4447-4448`）。

### B2 5 处"入口打不开静默"
物理 `pet_dialogs.py:4724-4730`（**这个在 A 的领地，A 做**）· 行为 `桌宠.py:1970-1975` · 待机 `:1977-1982` · 闹钟 `:2033-2038` · 账本 `pet_balance.py:404-409`。**统一照抄 `_dialog_failed`（`pet_dialogs.py:5677-5684`）**（`pet_balance.py` 里的那份按同口径，别 import pet_dialogs，用气泡 + 日志）。
**用例**：让弹窗构造抛异常 → 断言有用户可见提示（且不崩）。

### B3 `pet_resources.py:1584` 被 ext 白名单丢弃的条目要记日志
（限流，别刷屏；口径照 `pet_log.log_throttled`。）**用例**：塞一个 `.m4a` 素材 → 断言有日志且库状态可解释。

---

## 代理 C：插件线小账 a~d + 证据批跑

**领地**：`pet_plugin_host.py`、`pet_plugin_index.py`、`_dev/**`。**不碰 `pet_dialogs.py` / `桌宠.py` / `pet_balance.py` / `pet_resources.py`。**

- **a** `install_file` 安装时**核对索引与包的 `data_kind` 是否一致**（不一致 → 明确拒绝并给人话原因）。用例 + 变异。
- **b** 极端情况下 `history` 会白丢一个回滚点、留孤儿 `.prev-<id>` → 修（目录不在而 `.prev` 在时把它当 history 来源或一并清掉）。用例。
- **c** 同内容折叠时回滚文案可能说"撤销了 0 项" → 文案与行为对齐（首次安装不要说"撤销"）。用例。
- **d** razor（`_dev/silent_except_whitelist.py`）**只校验理由是否填写、不校验证据原文** → 至少加一条"证据字符串必须能在该文件里找到"的判据（若会大面积假红，就先做成提示级并在报告里说明取舍）。
- **铁律 5**：**对着出货修订整批复跑全部 `_dev/mutations_*.json`（含三份旧形态单脚本驱动）**，把 SPEC-BAD / ANCHOR-LOST / NOT CAUGHT 全部清掉（现存提示级：`results_fastci_slices_v251.json` 与 `results_guardrails_can_fail.json` 指纹过期、前者缺 `pet_plugin_index.py` 键）。**只需重跑对齐，不改产品逻辑。**

---

## 共同验收（安静窗口、串行）
- `python -B -m pytest tests -o addopts="" -q` → **0 failed**（基线 1061）
- `python -B _verify_v13.py` → **273 项 0 FAILS**
- `python -B _check_static.py`（单跑）→ **0 问题 0 待确认**

回报：改动清单 · 三项数字 · 每条变异的**能真失败证据** · **没做到/有疑问**。