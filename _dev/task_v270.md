# 第 5 轮任务书（草案 · 待开工）

记录：2026-10-12。下一轮按主代理建议：先做 A（插件分发 Phase 3），后做 B（DSH 浮层 Web 版）。

## 0 用户报的新缺陷（优先，与已登记小账同批修）

**导出角色不成功** —— 用户 2026-10-12 报告，只有一句描述，未复现未定位。

- 开工第一步：先复现「导出角色包」这条链（pet_export.export_bundle 侧），确认是点了没反应 / 报错 / 导出成功但文件不对 / 只在某角色或某机器上失败。
- 最可疑方向（导出侧最近动过两次）：① v2.4.4 把导出大条目的判据换成每轮写了几块 —— 若某些条件下只写一块就结束，判据是绿的但产物可能缺件 ② v2.5.x 改过固定时间戳 ZipInfo 写法 ③ v2.6.0 抽出 land_role 并改 import_bundle 调用。
- 验收：能真失败的用例（构造失败路径必须红）+ 一次真导出（产物能被导入角色包重新读回来，角色与状态图齐）。
- 需要用户提供：导出时的截图或报错文字、哪个角色（是否自定义角色）、导出到哪个目录、磁盘是否够。

## 1 A 先做：插件分发 Phase 3（远端索引接线）

- plugin_index_url 要有配置入口（配置键 + 设置里可填，或允许手改 config.json 并给文档）。
- 硬化已就位、别推翻：只收 https、远端索引不许指向本地路径或 file://、体积上限前置、下载后核对 sha256+bytes 不符即拒并删临时文件、解包前再走 validate_plugin_zip。
- 体验：地址校验与可读报错、刷新失败人话提示、能退回只读随包索引。
- 真正的验收：把下一版的新内容只以插件形式发布一次（不再打进绿色版），证明内容与版本解耦。

## 2 B 后做：dsh-dafeiyu-deskmate（DSH 浮层 Web 版）

- 复用素材（PNG 帧、WAV）与数据格式（行为表、台词库）+ 状态机逻辑；渲染换 Canvas 或 DOM。
- 第一步只做待机 + 点击反应 + 台词气泡；验收 = 能装上、能看到、能在市场里被找到。
- 第二步接 DSH 会话上下文（AI 思考中 / 回复完成 / 报错时宠物有反应）——这是它真正的差异化。
- 规矩：宿主半 Node + 客户端半 __ModuleLoader__.load 工厂；每条路由必须过 trust fence（ctx.connection.requestRejection）；浮层用 shell.overlay；桌面端安装方式是在会话里说把它装上（dsh plugin --profile desktop 被 CLI 硬拒）。

## 3 已登记的小账（与第 0 条同批）

- a install_file 安装时不核对索引与包的 data_kind 是否一致（界面显示台词、实际落地成 role）。
- b 极端情况下 history 会白丢一个回滚点、留下孤儿 .prev-<id>。
- c 同内容折叠时回滚文案可能说撤销了 0 项。
- d razor（静默异常白名单）只校验理由是否填写、不校验证据原文。
- e 按铁律 5，定版前整批复跑全部 _dev/mutations_*.json —— 现存提示级：results_fastci_slices_v251.json 与 results_guardrails_can_fail.json 指纹过期、前者缺 pet_plugin_index.py 键。
- f M-H2 缩掉的那半已由 M-A17 补上（已完成，不用再做）。

## 4 押后 / 待用户决定

- 裁 Qt：-51.6%（107.49 到 52.07 MiB，四道门验证过），保留 opengl32sw.dll —— 用户说等稳定了再处理。
- God Object 继续拆：__init__ 仍 423 行、3 处注册表调用，fx 两处与 pet_audio.init 仍内联。
- A2 注解未做全仓：要补就得同时改 README 注解表的措辞。
- D9 四项：DeepSeek API key、Gitee token、四个平台、真实注销关机验证。

## 5 现行六条铁律（写在 _dev/README.md）

1. 绿色版目录里调 python.exe 一律加 -B（py_compile 例外，-B 拦不住它，别用）。
2. 跑全量前确认 _dev/.mutation.lock 不存在。
3. 测试断言不许依赖机器速度（注入每单位固定成本，断言结构性事实）。
4. 契约必须双向覆盖。
5. 定版前必须对着出货修订复跑全部 _dev/mutations_*.json（含三份旧形态单脚本驱动）；SPEC-BAD / ANCHOR-LOST / NOT CAUGHT / WRONG TEST 一律不许当通过。
6. 变异验证必须在影子副本里做，不许原地改真仓（原地改写+事后还原会制造 1~2 秒"真仓处于变异态"窗口，并发的全量 pytest 撞进去就看到假红——v2.7.0 第 5 轮实测过：A 全量里 3 条红完全等于 B 的 pet_ai 变异红集）。与铁律 2 是一对：2 管"别在窗口里下结论"，6 管"别制造窗口"。
## 0.1 已定位（2026-10-12 用户补充现象后 5 分钟内确认）

**用户现象**：导出时**卡在「继续导出」**，旁边的**「取消」也没反应**。（= 弹窗卡住、两个按钮都是死的）

**根因（已确认，非推测）**：`pet_dialogs.py` 的 `build_role_meta_dialog()`（:5785）里
- `btn_ok = QPushButton("继续导出")`（:5809）与 `btn_cancel = QPushButton("取消")`（:5810）
- 只被 `row.addWidget(...)`（:5811-5812）加进布局，**全仓没有任何 `clicked.connect`**（grep `btn_ok|btn_cancel` 只命中创建与加布局三行）。
- 于是 `pick_role_meta()`（:5768）走 `modal(dlg)` 时进入嵌套事件循环，**两个按钮都关不掉这个窗口** → 界面永久停在「继续导出」，取消也无效。

**这是 v2.5.0 B 的回归**：B 为了尺寸验收把「角色信息」对话框的**构造**抽成 `build_role_meta_dialog`（docstring 写明"工厂只建窗口不 exec；pick_role_meta 负责 modal 与取值"），**搬家时把按钮接线丢了**。之前内联版本是能用的。

**修法（约 2 行 + 1 条能真失败的用例）**：
1. 在 `build_role_meta_dialog` 里接上：`btn_ok.clicked.connect(dlg.accept)`、`btn_cancel.clicked.connect(dlg.reject)`；
2. 复核 `pick_role_meta` 的结果读取路径（`modal(dlg) != Accepted` 时返回 None）与 `dlg.close()`/Esc 的语义；
3. **用例**：① 点「继续导出」→ 对话框 accept 且返回四个字段 ② 点「取消」→ 返回 None ③ **能真失败**：注释掉两条 connect → 两条用例必须红（变异验证）。
4. **顺带扫一遍**：`pet_dialogs.py` 里还有没有别的"抽成工厂后忘记接线"的对话框（grep 所有 `QPushButton(` 看是否有建了不加 `clicked` 的）。

**影响面**：**导出角色包这条功能完全不可用**（不是偶发、是必现）。属 P1。
**未做**：本轮（v2.6.1）未修——用户要求与已登记小账同批在下一轮做；诊断已留档，下一轮是 5 分钟的活。
## 6 三份盘点（2026-10-12 完成，只读）

- 按钮接线：`_dev/audit_buttons_binding_v270.md`（123 个按钮控件 + 61 个菜单动作；未接线 17 = 2 个真动作按钮 + 15 个 QCheckBox 状态输入，逐条反证）
- 反馈缺失：`_dev/audit_feedback_v270.md`（完全无反馈 13 条 · 成功后零提示 46 条 · P0 硬阻断 1 条；含"现成反馈手段清单"与"标杆实现"照抄对象）
- 导出卡死定位：本文档 §0.1

## 7 下一轮批次（按严重度，先清单后动手）

**P0**
- 导出角色包必现不可用：`pet_dialogs.py:5809-5812` 两个按钮零 clicked.connect（+ btn_ok 无 setDefault）。用户现象=卡在继续导出、取消也没反应。

**P1（含一条数据丢失类）**
- **AI 设置保存静默丢数据**：`pet_dialogs.py:3093-3094` 丢弃 `_call` 返回值并无条件 accept；失败只在 `:298` 记日志。影响：人设正文、API 地址、模型、max_tokens、工具开关、RAG 都走这条路。**前置**：`桌宠.py:4963-4965` 的 apply_ai_settings 没有返回值，要先改主窗。
- 导出行为 JSON 成功零提示：`:2668-2670` 只有失败分支；未选中还静默 return（`:2662-2663`）。
- 删除行为无二次确认：`:2624-2639` 全程没有 _confirm（同仓到处都用），点一下永久删、且无已删除提示。
- 气泡样式 / 物理参数保存双静默：`:3999-4010`、`:4714-4721` 丢弃返回值 + accept；apply_bubble_style 成功不弹气泡；apply_physics 值未变则静默 return（`桌宠.py:4447-4448`）。
- 绑定下拉空态：`:5143` except 静默 + 无提示无入口；并确认配音素材有没有"添加"入口。

**P2**
- 新增通用按钮契约用例（AST 扫每个 QPushButton/QToolButton 必须有接线或在白名单）——全仓目前只有一处按钮点击用例，这类缺陷没人能发现。
- 5 处"入口打不开静默"：物理 `pet_dialogs.py:4724-4730`、行为 `桌宠.py:1970-1975`、待机 `:1977-1982`、闹钟 `:2033-2038`、账本 `pet_balance.py:404-409`；同仓 7 个入口用 `_dialog_failed`（`pet_dialogs.py:5677`）做对了，照抄。
- 另 8 条完全无反馈：失效引用单删/全删（`:4627`/`:4640` 丢弃 delete/delete_many 返回值）、行为删除选中步骤（`:2377-2378` takeItem(-1) 静默）、角色设为当前/恢复默认（`:3335-3349`/`:3371-3378` 失败只记日志）。

**P3 / 小账 / 收尾**
- `pet_resources.py:1584` 被 ext 白名单丢弃的条目要记日志；`:5708 open_idle` 死入口；5 处循环文案按钮。
- 小账 a~d：install_file 不核 data_kind · history 孤儿 .prev · 同内容折叠文案 · razor 不校验证据原文。
- 按铁律 5 证据整批复跑。

**开工前先做两件**（反馈审计实测不了的）
1. 花 5 分钟实测：**模态度话框打开时宠物气泡能否压在上面**（两个 WindowStaysOnTopHint 的 z 序取决于最近一次 raise）——这决定"面板内操作用弹窗还是气泡"。
2. QListWidget.setCurrentRow 是否自动滚到可见处未实测 → 验收写成"断言 currentItem() 的行 id == 新条目 id"（结构性，不依赖滚动）。

**之后**：Phase 3 远端索引接线 → DSH 浮层 Web 版。