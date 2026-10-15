# v2.7.0 第 5 轮 · 三路审查任务书（冻结后派发）

仓库 E:\deep seek\desktop-pet。基线 HEAD `9f7fb78`（v2.6.1 已发布）。**本轮改动未提交**。

**冻结要求（审查员必须做）**：开工第一件事——`git status --short`、`git rev-parse HEAD`、以及下列关键文件的 sha256 前 12 位，**抄进你的报告开头**：
`pet_dialogs.py` · `桌宠.py` · `pet_ai.py` · `pet_config.py` · `pet_balance.py` · `pet_resources.py` · `pet_plugin_host.py` · `pet_plugin_index.py` · `README.md`
**行号只在你自己抄的那份快照上有效**；（若发现树在动，立刻停手报我。）

## 本轮做了什么（三路实现，各自已回报）

**代理 A（`pet_dialogs.py` 全部）**：P0 导出角色包卡死（`:6185/:6186` 两条 `clicked.connect` + `setDefault`）· P1-1 AI 设置保存失败不关窗 · P1-2 导出行为成功提示 · P1-3 删除行为二次确认 · P1-4 气泡样式/物理保存双静默 · P2 绑定下拉空态三分（空库/索引不可用/库故障）· D6/D7 的 `delete/delete_many` 返回值 · D11 删除步骤 · S22/S23 · 新建后按 id 选中 + `scrollToItem` · S2 空名重命名 · 新增 `_toast`/`_apply_result`/`_apply_call`(strict)/`_save_failed` 四个反馈出口 · 新建 2 个测试文件共 36 条 · README 数字 304→319。自述 **31 条变异全 RED**。
**代理 B（`桌宠.py`/`pet_ai.py`/`pet_config.py`/`pet_balance.py`/`pet_resources.py`/`tests/test_ui_wire_cache_v241.py`）**：三个 `apply_*` 与 `AIService.apply_settings` 一律返回 `(ok,msg)`（**`pet_ai` 不再自己弹气泡**；`pet_config.write_config` 失败 `return err` → 一路传到对话框）· 四处入口静默（行为/待机/闹钟/账本）· `pet_resources.py` 白名单外条目记限流日志 · S17 空 Key 修复（**拒绝加 `sk-` 前缀校验**，理由：本地后端 key 任意）· wire 用例顺序红改成自隔离（`drain_anim_slices`）。自述变异全部带原文。
**代理 C（插件线）**：小账 a `install_file` 核 `data_kind` · b `history`/`.prev` 强制成对（含 S1-a 分支连带修复）· c 回滚文案 · d razor 新增"证据原文必须找得到"**硬判据**（307 条零假红）· 按铁律 5 对着出货修订**整批复跑全部证据**（此前 **20 份全过期**）。

## 三审各自的重点（都要**动手实测**，不许停在读码）

### 找茬审查
1. **P0 是否真复刻了用户路径**：A 的端到端用例是否真的走了"菜单 → 对话框 → 继续导出 → 产物 → 用真入口回读"？**你自己跑一遍**；再把两条 `connect` 注释掉，确认**红的原因就是"对话框没关"**。
2. **`_apply_call` 的 strict 语义**：`None`/`False`/方法缺失是否真当失败？**构造**一个返回 `None` 的回调（模拟"方法自己抛异常时 `_call` 回 None"）→ 断言窗口**不关**。
3. **绑定三态是否真能区分**：造 ① 索引文件不存在 ② 索引文件在且有内容但 0 条可用 ③ 库读抛异常 —— 三种提示**必须互不相同**；并把 `_asset_items` 换成"永远只回（不绑定）"的桩，确认判据**不依赖它**。
4. **`pet_config.write_config` 的错误传播链**：注入**返回错误串（不抛异常）**——这正是现网形态 → 断言一路到"真对话框不关窗 + 原因可见"；再**单独**检查"只读兼容模式"那条分支是否也会返回原因（B 说改了，**自己验**）。
5. **顺序污染是否真修好**：把 wire 用例与"恶意顺序"的前置文件合跑多次；用 B 的复现器（`%TEMP%\wire_repro_v270\repro_driver.py`，`SLOW_SWAP=1`）确认**注入慢解码下也绿**。
6. **有没有"补了但用户看不到"**：气泡在极端情况下会被对话框压住（B 实测过），检查有没有哪条成功反馈**恰好在这种几何下**等于没有。

### 质量审查
1. **每个新用例是否真能失败**：A 自述 31 条变异、B 自述 9+ 条 —— **抽样自查**（不许照抄他们的表），重点验"断言的是可见结果还是内部调用"。
2. **有没有为了变绿放宽断言/删用例/加 skip**：`git diff HEAD -- tests/` **逐文件逐行**扫；**特别注意 A 改动过的那条既有用例**（它自述把 2 条"假绿"改真了：删除步骤改成点真按钮、取消改成看 `finished` 信号——**确认这是加强不是替换弱化**）。
3. **审计的 58 条"无反馈/零提示"覆盖了多少、漏了多少**：对照 `_dev/audit_feedback_v270.md` 的清单逐条核"是否真的有了用户可见反馈"。
4. **已知让步是否合理**：① AlarmDialog 未选中删除保持静默（既有断言钉住）② D16 清除长期记忆没改成 `_confirm`（会让既有用例挂死）③ 人设"新建"入口不存在=缺功能 ④ N12/N13/N14/P2-8 弱反馈未动。**逐条判断这个理由站不站得住**。
5. **数字**：README 的 `pet_dialogs.py` = **319** 是否与 AST 实测一致（A 说最后一次校准过）；`_dev/*.md` 里的数字有没有过期的。

### 兼容审查
1. **旧数据/旧配置**：本轮改了 `pet_config.write_config` 的返回语义、`save_config` 的透传、`pet_ai.AIService` 的行为（**气泡搬家**）——用真数据目录跑"设置 AI / 改物理 / 改气泡样式 / 记一笔账"四条路径，**逐字节对照** `config.json` / `ledger.json` / 用户数据；确认**没有多写/少写/半截**（B 说"失败不留半截"，自己验）。
2. **`save_config` 的 40+ 调用点**：B 说"没有一个消费返回值"——**自己 grep 复核**，并挑 3 个不同调用方确认改返回值语义没让它们的行为变。
3. **`pet_ai` 气泡搬家**：以前服务层弹、现在对话框弹——**找一条不经过对话框的调用路径**（如果存在），看会不会变成"完全没有反馈"。
4. **发布链**：版本五处、绿色版待同步清单（`pet_dialogs.py`/`桌宠.py`/`pet_ai.py`/`pet_config.py` 等）、`_dev` 不入包、素材索引、**工作区不得有未跟踪文件**。
5. **用户可见行为是否都该写 CHANGELOG**：本轮改的是"反馈"，但有几条**改变了行为**（删除行为现在要确认 · AI/物理/气泡保存失败不再关窗 · 空 Key 现在有提示 · 导出行为现在有提示）——**列一份必须写进发布说明的清单给我**。

## 通用铁律
1. 跑全量前确认 `_dev/.mutation.lock/` 不存在；**别与其它审查并发跑 pytest 与静态体检**。
2. **变异必须在影子副本里做**（`_dev/_mutate_lib` 的机制，或复制仓库到 %TEMP%）——**铁律 6**：原地改真仓会制造"1~2 秒变异窗口"，让并发跑的人看到假红（本轮就这么发生过一次）。
3. 绿色版目录里调 python.exe 一律加 `-B`；**语法检查别用 `py_compile`**，用 `ast.parse`。
4. 断言不许依赖机器速度；**不许放宽任何断言**。
5. 每条发现给 `文件:行号 | 问题 | 建议 | 是否实测`；区分「实测 / 读码推断 / 没找到」；最后一句「是否可发布」。
---

## 冻结快照（2026-10-12，三路实现全部停笔、无锁、主代理已自跑护栏）

```
HEAD            9f7fb78a88c32d660e52ed90cfc48cfda20a8e7e
dirty_paths     49        lock=False
pet_dialogs.py      EBB4AF7709F6
桌宠.py              E04AC6CF2CAF
pet_ai.py           1870C7971632
pet_config.py       D70F2185D20F
pet_balance.py      C374984CA058
pet_resources.py    E28F38917052
pet_plugin_host.py  82FB7B1384C8
pet_plugin_index.py 7E9B4537B98E
README.md           933B59F1C386
```

**主代理自己跑过的（你可以引用，但建议自己抽验）：**
- `python -B -m pytest tests -o addopts="" -q` → **1143 passed / 0 failed**（138.75s）
- `python -B _verify_v13.py` → **V13 VERIFY ALL OK（273 项 0 FAILS）**
- `python -B _check_static.py` → **0 问题 / 0 待确认**
- `python -B _dev/repro_quiet.py`（时间轴三相位）→ **timeline=0**
- **P0 端到端**：`pytest tests/test_dialogs_feedback_v270.py -k export_role_bundle` → **2 passed**；A 的两个测试文件合跑 **36 passed**

**三路实现的自述数字（未独立复核，供你交叉验证）**：A 31 条变异全 RED · B 16 条变异带原文 · C 批跑 268 条判定全 0 异常（SPEC-BAD/ANCHOR-LOST/WRONG TEST/NOT CAUGHT/INVALID/BASELINE-RED）。
