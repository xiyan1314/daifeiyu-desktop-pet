# 第 11 轮 · v2.11.0 任务书 —— 动起来好看 I + 旧第 8 轮那批落点 + 清账

> 协调者：**dsh-main-r11**（会话 `session-93b8f6de`）。写于 2026-10-16 23:5x。
> **真源**：`_dev/plan_v270_rounds.md` §十八（轮号新表，§三 已作废）· `_dev/REMAINING.md`（102 条）· `_dev/MASTER_CHECKLIST.md:48/50`（本轮与旧第 8 轮那批的**交付要点原文**）· `_dev/VERIFY_DISCIPLINE.md`（§十 树必须静止 · §十四 铁规矩）。
> **本任务书不是计划**：它是这一轮的**作业单**，每条都带"判据在哪、谁拥有哪些文件、怎么算做完"。

---

## 零、用户裁决（本轮的全部依据 · 2026-10-16）

| # | 原话 | 落地成什么 |
|---|---|---|
| 1 | 「**开工**」 | 本轮开始（认领 `T-R11-V2110`，lease 12h） |
| 2 | 「**攒进 v2.11.0**」 | 上一批（撤悬停光晕/按下描边，10 个文件已在工作树）**不单独发补丁**，与本轮一起发 **v2.11.0** |
| 3 | 「**解决未完成事项和欠账**」 | **A 档剩 2 条**（A-07 / A-10）+ `REMAINING` 里可清的 C/D（见包 W5） |
| 4 | 「旧第 8 轮那一批内容…**在 v2.11.0 解决**」 | `plan` §18.6 **缺口① 关闭** → 下面 W2/W3/W4 九个交付点 |
| 5 | 「**R-DSH 插第 16 轮**，由谁负责：看情况」 | `plan` §18.5 已批注；**owner 待定**，本轮不做 |

---

## 一、交付范围（5 个包 + 版本与文档）

### W1 · 只读/纯逻辑底座（**不碰 桌宠.py**，可与 W2 并行）

| 点 | 交付 | 领地 | 判据要点 |
|---|---|---|---|
| W1-a | **`pet_windows.py`**：前台窗口是否全屏（ctypes + **可注入探针** + 去抖 N 次 + 节流 ≥250ms；出错走安全侧 = 不当成全屏） | `pet_windows.py` · `tests/test_windows_v2110.py` | 覆盖/容差边界 · 任务栏/桌面/自身窗口排除 · 多屏 · ctypes 抛错 → False · 去抖边界（N-1 不动、N 触发）· 每条一个"还原就红" |
| W1-b | **`pet_backup.py`**：用户数据 zip 备份 / 恢复（manifest + sha256 + 原子写 + **恢复前自动快照** + **拒绝 zip slip** + 失败回滚） | `pet_backup.py` · `tests/test_backup_v2110.py` | 白名单**复用 `_check_release` 的口径**（不许手抄）· 往返逐字节 · 断 zip/缺文件/sha 不符 · `../` 与绝对路径**拒绝且不落文件** · 原子性 · 回滚 |
| W1-c | **walk 占位帧集**：`_dev/gen_walk_frames.py` → `assets/walk_f00..f07.png`（8 帧，从 `character.png` 程序化派生） | `_dev/gen_walk_frames.py` · `assets/walk_f*.png` · `tests/test_walk_frames_v2110.py` | 仿 `_dev/gen_full_idle_frames.py` 的标杆：确定性/幂等/`--check`/alpha bleed/不裁切/四边 alpha=0/8 帧两两不同/首尾无跳变/**无凭空黑像素** |

### W2 · 主题：**动起来好看 I**（`MASTER_CHECKLIST.md:50` 原文）

> 「走路也播帧动画（**无帧集角色兜底**）· 动画链 + **交叉淡入 100–200ms**」，前置 = walk 帧集（W1-c）。

| 点 | 交付 | 领地 |
|---|---|---|
| W2-a | **走路播帧**：移动时播 `walk` 帧集；停下回 `idle`；**无帧集角色（自定义角色/素材缺失）继续走原静态兜底**，不许因此不走路、不许报错 | `桌宠.py` · `pet_wander.py` · `pet_motion.py` |
| W2-b | **动画链 + 交叉淡入 100–200ms**：状态切换（idle↔walk↔eat↔poke↔sleep）时两帧交叉淡入；时长进令牌表（`pet_motion.DUR`），**关「减少动效」= 瞬时**（0ms，不留半截） | `桌宠.py` · `pet_anim.py` · `pet_motion.py` |
| W2-c | **A-07 裁决落地**（见 §二） | `pet_motion.py` · `CHANGELOG` · `_release_notes` |

### W3 · 不打扰你 / 不丢数据（原方向 3/4/5/6）

| 点 | 交付（`MASTER_CHECKLIST.md:48` 原文） | 领地 |
|---|---|---|
| W3-a | **全屏自动隐藏**（消费 W1-a；**先抽 `pet_windows.py`** 已完成在 W1-a） | `桌宠.py` · `pet_menu.py` |
| W3-b | **ZIP 备份恢复**（消费 W1-b；入口放 `⚙️ 设置…` 子菜单，**顶层菜单 18 项上限不许破**） | `pet_dialogs.py` · `pet_menu.py` · `桌宠.py` |
| W3-c | **崩溃自动重启**（启动器级：退避 + 上限 + 安全模式标记；**不许无限重启循环**） | `main.py` · `pet_guard.py`(新) · `启动桌宠.vbs`? |
| W3-d | **持续气泡 + 系统通知**：气泡可"常驻/定时"；系统通知走**已有 `QSystemTrayIcon.showMessage`**（零新依赖） | `pet_widgets.py` · `桌宠.py` · `pet_menu.py` |
| W3-e | **发行拆分（核心版 vs 可选包）**：方向 13/15/19 作可选包；`focus.json` 归**必须保留的用户资产**；判据落在 `_check_release` 口径里 | `_check_release.py` · `_dev/build_*` · 文档 |

### W4 · 有点人味（UX D1/E1/E2/D2）

| 点 | 交付 | 领地 |
|---|---|---|
| W4-a | **D1 首次启动引导气泡**（首次运行一次性、可"不再提示"） | `桌宠.py` · `pet_config.py` |
| W4-b | **E1 惊喜彩蛋**（低频、可关、不打扰；不许变成"每次启动都弹"） | `桌宠.py` · `pet_lines.py`? |
| W4-c | **E2 时间感知情绪**（按时段给情绪/台词；**不许与 `pet_mood` 现有机制打架**） | `pet_mood.py` · `桌宠.py` |
| W4-d | **D2 菜单悬停预览（300ms 阈值 + 可关闭）** | `pet_menu.py` · `桌宠.py` · `pet_motion.py` |

### W5 · 清账（A 档剩 2 条 + 可清 C/D）

| 点 | 交付 |
|---|---|
| W5-a | **A-10 主窗口键盘**：① **真机**取证（不是 offscreen 推断）② 发布说明改成与事实一致的措辞 ③ 若确认"点它拿不到焦点"，给托盘/菜单一个显式入口 + 用例 |
| W5-b | **C-34 菜单顶层项数**：`变身` 条件项会把顶层顶到 19 → 本轮的修法是与 D2/新入口**一起**把顶层稳定在 ≤18（**这是本轮唯一会被新菜单项踩到的硬上限**） |
| W5-c | `REMAINING` 里"顺手已修"的条目回写（研究代理给的清单，逐条 grep 复核后才改） |

### W6 · 版本与文档（协调者本人）

版本五处（`桌宠.py` VERSION · `version_info.txt` 四行 · `_verify_green.py` 断言 · `CHANGELOG` 首条 · `_release_notes_v2110.md`）· `CHANGELOG` 把"未发布（下一版 v2.11.0 待发）"并进 v2.11.0 条目 · `_dev/REMAINING.md` 回写 · `plan` §十八 状态更新。

---

## 二、本轮的两条**裁决**（我以协调者身份先定，用户可推翻）

1. **A-07 → 走 (b) 收窄声明 + 登记边界**（不把那 4 处位移塞进「减少动效」）：
   原因：走路是**角色的核心行为**，关掉它会显得僵死；而"减少动效"要治的是**时长动画**。配套补偿——走路播帧**照 D1 的帧率倍率放慢**，且**交叉淡入在减少动效下不发生**。
   落地：`pet_motion.effective_duration` 的「已知边界」段 + `CHANGELOG`/`发布说明` 的无条件全称断言**逐句改掉**（这是 A-07 的病根）。
2. **W3-e 发行拆分**：本轮只做**判据与文档层**（核心版/可选包的边界写进 `_check_release` 的白名单 + 发布说明），**不真的去改 PyInstaller 打包方式**（那是"裁 Qt"那条横向轨的邻域，押后）。

---

## 三、文件领地（**写死，避免并行撞车**）

| 波次 | 拥有 `桌宠.py` 的人 | 其它独占文件 |
|---|---|---|
| W1（并行 3 个） | **无人** | W1-a `pet_windows.py`+test · W1-b `pet_backup.py`+test · W1-c `_dev/gen_walk_frames.py`+`assets/walk_f*`+test |
| W2（串行 1 个，**动画**） | **W2 动画代理** | `pet_anim.py` · `pet_motion.py` · `pet_wander.py` · `tests/test_motion_v2110.py`? （只加不改，改要先报） |
| W3（串行，**接线**） | **W3 接线代理** | `pet_menu.py` · `pet_widgets.py` · `pet_dialogs.py` · `main.py` · `pet_guard.py` |
| W4（串行，**人味**） | **W4 代理** | `pet_mood.py` · `pet_config.py` |

> **规则**：同一时刻**只有一个代理拥有 `桌宠.py`**。没拿到 `桌宠.py` 的代理，把接线路点写进报告（在哪一行、加什么），由当前持有者或协调者落地。

---

## 四、每包都必须自带的判据（缺一不可）

1. **能真失败**：每条断言都要能说清"把哪一行拿掉/改坏，它就红"（报告里逐条写）。
2. **结构断言优先**：不看眼。可数就数（对象数/调用次数/帧数/几何五元组），不可数就**显式登记为"只能人眼"**。
3. **对象数回基线**：凡新建 QGraphicsItem / 窗口 / 定时器，都要有"收尾后回到基线"的断言。
4. **「减少动效」覆盖**：新动效一律走 `pet_motion` 令牌；关掉开关 = 瞬时（0ms）或**根本不产生**，并逐条进 `test_every_animation_point_is_covered_by_the_switch` 的列举。
5. **不许改角色几何**（A4 硬口径）：悬停/按下/交叉淡入都**不许**写 scale/squash/窗口尺寸。
6. **不动顶层菜单 18 项上限**：新入口一律进已有子菜单（C-34 就是这条的旧账）。

---

## 五、13 步流水（本轮的勾选板）

| # | 步骤 | 状态 |
|---|---|---|
| ① | 实现（多子代理并行） | 🔄 W1 三包进行中 |
| ② | 版本五处升级 | ⬜ |
| ③ | 安静窗口全门（六条，协调者亲手） | ⬜ |
| ④ | 冻结哈希 | ⬜ |
| ⑤ | 三审（找茬/质量/兼容，锚冻结哈希） | ⬜ |
| ⑥ | 修三审（先收齐再改） | ⬜ |
| ⑦ | delta 复跑 | ⬜ |
| ⑧ | 独立验收（非作者，≥2 条还原必红） | ⬜ |
| ⑨ | 证据整批复跑（~55 分钟） | ⬜ |
| ⑩ | 绿版同步（绿版自带 python.exe 自检） | ⬜ |
| ⑪ | 白名单打包 + 解压自查 + 毒样本 | ⬜ |
| ⑫ | `_check_release` → `RELEASE CHECK OK` | ⬜ |
| ⑬ | 提交 → 推送 → Release → CI 绿 | ⬜ **推送前要问用户** |

---

## 六、红线（违反即作废）

1. **树必须静止**跑门（无锁 / 无 python 测试进程 / 无写入者）—— 三查缺一不可。
2. **CI 两步结构**：`Pytest` 与 `Offscreen smoke` 是**两个独立进程**，`tests/conftest.py` 的夹具**管不到 `_verify_v13.py`**（#58 的教训）→ 涉及宿主环境的钉死必须**两处都做**。
3. **看 CI 必须真看**（GCM 凭据 → GitHub API → 看 `head_sha` 与 `conclusion`），不许假设绿。
4. **作业状态 exit 0 可能是假的**：长作业必须看输出尾部。
5. **改文档用行号定位**，不许模式匹配替换（会命中历史行）。

---

## 七、研究代理交回的**硬约束**（本轮所有实现代理都必须遵守；写在这里防止只活在消息里）

### 7.1 走路播帧（W2）
- 帧集注册**三处一起改**：`桌宠.py:120-123` `_DEFAULT_FRAME_SETS` · `_wire_anim_key`(`:2964-2988`，指纹只含 idle+eat) · `_wire_anim_sets`(`:3056-3057`)。
- **不许**把 `"walk"` 塞进 `pet_resources.ANIM_ACTIONS`（`:82`）—— `"walk"` 今天是**合法的自定义动作名**，塞进去撞老角色数据。只做素材级 walk。
- 走路位移仍是 `pet_wander.WanderController.tick` → `pet.move`（`:151`，120ms）；**播帧与位移没有任何现成耦合**（`frame_moved` 是第 12 轮的事）。
- `_apply_transform`(`:3786`) 的锚点读**当前 pixmap 自身尺寸**（`:3801-3809`）→ walk 帧必须同画布同质心，否则走路一跳一跳。
- 注意：`tests/test_asset_absence_v244.py:310-314` 把帧集数钉成 `(10,7,10)` —— **不要**动这三组。

### 7.2 交叉淡入（W2）
- 现成令牌：`pet_motion.DUR["TRANSITION"]=200`（`pet_motion.py:47`），**今天 0 消费点**；启用后必须从 `tests/test_motion_v2110.py` 的 `_DUR_RESERVED` 里删掉（那里有反钉）。
- **令牌扫描面只有 4 个文件**（桌宠/pet_widgets/pet_actions/pet_balance）→ `duration_ms("TRANSITION", self._reduce_motion())` 必须写在 `桌宠.py`。
- 现成先例可抄：`_show_emote`(`:3734-3779`) 的 opacity 分叉、`pet_widgets._fade_to`(`:417-447`) 的 `ms<=0 直接落终态`。
- 多图层先例：`emote_item`(`:945`) / `fx_item`(`:952`) —— 第二张 item 建在 `__init__` 里才计入基线。

### 7.3 旧第 8 轮那 9 项（W3/W4）
- **这 9 项没有一项是用户原话**（全部来自用户 #194 提交的两份 AI 起草的附件方案）→ 任何地方都**不许写成"用户要求"**，要写"用户 #194 提交的方案 + 2026-10-16 用户裁决并入 v2.11.0"。
- `REMAINING.md` 里这 9 项**0 收录** → 本轮必须**先登记再实现**（否则下一个人又一次"以为没做"）。
- 现成能力：托盘对象 `桌宠.py:1287`（系统通知用 `tray.showMessage`，**零新依赖**）；气泡固定 5s（`pet_widgets.py:370`）；`_toast`（`pet_dialogs.py:451`）是既有回执通道。
- **别做**：① 不加菜单顶层项（18 项上限，`_verify_green.py:86`）；② 不动窗口尺寸/角色几何；③ 不在 `pet_chat.py` 加 Qt（它今天 0 个 Qt import）。

### 7.4 两条会被踩到的门
- `_verify_v13.py:163-168`（walk 常量）、`:315/:745`（`anim_mode ∈ {state, idle}`）→ 新增 `walk` 模式要复核。
- `_check_release.asset_manifest_problems`(`:345-361`) 用 **git 索引 vs 磁盘** → 新 `assets/walk_f*.png` **必须 git add**。
---

## 八、进度板（2026-10-17 白天 · dsh-main-r11）

### 8.1 已落（有判据、跑过）

| 交付 | 文件 | 判据 | 读数 |
|---|---|---|---|
| **⑤ 发行拆分：用户数据台账** | `_check_release.py`（`focus.json` 进 `USER_DATA_NAMES`）· `tests/test_core_pack_v2110.py` · `_dev/core_pack_plan_v2110.md` | 3 条（覆盖 / focus 提前划线 / 反向对照非空转） | `3 passed` |
| **A-07 反向钉子** | `tests/test_boundary_claims_v2110.py` | 3 条（4 处位移仍无 `_reduce_motion` / 反向对照能真红 / 三处声明逐词点名） | `3 passed` |
| **C-34 产品侧收口** | `pet_menu.py`（「🐡 变身」→ `🐡 形态` 子菜单） | 顶层恒 ≤18（结构性）；**判据仍缺**（要构造自定义角色+变身形态） | AST OK |
| **A-10 真机取证** | `_dev/probe_a10_real_machine.md` · `_dev/probe_focus_noactivate.py` | `exstyle=0x08080088` + `WM_MOUSEACTIVATE=3`；对照组 `0x00080088` + `1` | `A-10 PROBE OK`（两次独立） |
| **C-39** | `tests/test_motion_v2110.py:1101` 上方注释 | 纯注释（把「有意钉死」写进代码） | — |
| **C-36 补证** | `_dev/REMAINING.md`（C-36 条） | 新 mtime `22:19:17` + 候选写者 + 一步实验 | — |

### 8.2 进行中（代理在跑，文件已落地但未验收）

| 包 | 文件 | 状态 |
|---|---|---|
| W1-a 全屏检测 | `pet_windows.py`（24 KB） | 测试文件未落 |
| W1-b ZIP 备份 | `pet_backup.py`（42 KB）· `tests/test_backup_v2110.py` | **36 passed / 1 failed**（`test_恢复失败回滚…`，代理还在修） |
| W1-c walk 帧集 | `_dev/gen_walk_frames.py`（19 KB，AST OK） | **assets/walk_f*.png 还没生成** |
| W2 走路播帧+交叉淡入 | 正在改 `桌宠.py` / `pet_wander.py`（两者 mtime 已变） | 未收工 |
| ⑧ 时间感知 | `pet_time_mood.py`（18 KB） | 测试文件未落 |
| ④ 崩溃重启 | 无文件 | 代理在跑（另有一个重复代理已 interrupt） |
| ① 气泡常驻+通知 | `pet_widgets.py`? `pet_notify.py`? | 未见落盘 |

### 8.3 还没派（等 `桌宠.py` 让出来）

- W3 **接线包**：全屏自动隐藏 / 备份入口 + 对话框 / 持续气泡 / 系统通知 / 菜单（顶层不许破 18）
- W4 **人味包**：D1 首次引导 / E1 彩蛋 / D2 菜单悬停预览（默认关）
- 崩溃重启的 **main.py 接线**（我亲自做）
- ② 版本五处 / ⑧ CHANGELOG 与发布说明

### 8.4 两个已知风险（不粉饰）

1. **W2 正在改 `桌宠.py`** —— 我这一轮想改的那句 A-07 气泡文案（`桌宠.py:4790`）被它挡了，**等它收工再改**（记在这里，别忘）。
2. **并发派单撞上限**：④ 被派成两个代理，已 interrupt 掉重复的那个；届时 `pet_guard.py` 若只有一份且 AST OK，就按一份算。
### 8.5 第 2 轮进展（2026-10-17 · dsh-main-r11）

| 交付 | 结果 |
|---|---|
| **walk 帧集（主题的前置素材）** | 我跑生成器落盘 **8 帧**（assets/walk_f00..f07.png，退出码 0；--check = 8/8 ok；MAD(vis) 12.8–28.9；四边余量最小 1；seam/平均步进 **0.644x**）。**已 git add**（发布门资产清单用 git 索引 vs 磁盘）。 |
| **walk 素材判据**（新文件） | tests/test_walk_frames_v2110.py **6 条全过**：帧数/尺寸/模式 · 四边 alpha 恒 0 · 幂等（--check + AST 禁 random/time/datetime）· 两两不同 + 相邻差异够大 · 首尾无缝 · **无凭空黑 + 反向对照（人造黑边必须被抓到）**。 |
| **黑边判据的半径**（写清来历，不是拍脑袋） | 实测力臂 **R=146.79px**（质心 149.46,143.99）→ 2 度旋转位移 5.12px + 起伏 2.0 + 挤压 1.47 ⇒ 上界 **8.59px**；再 +2（该判据量的是「到最近**暗**像素」的距离，暗掩膜比轮廓稀）⇒ **取 11px**。实测最远一个落在 10.44px。 |
| **新模块进 SYNC_FILES** | pet_windows.py / pet_backup.py / pet_guard.py / pet_time_mood.py 已登记（否则发布门「被 import 却没在清单里」要到用户双击 ImportError 才发现）。check_shipped_files() = **[]**。 |
| **pet_guard.py 冒烟** | 正常退出→不重启；崩溃#1→1.0s 后重启（窗口内第 1/3 次）；退避 2/4/8s；重启命令带 --guard-restart。**仍缺自带单测**（代理在跑）。 |
| **已绿的既有新测试** | test_backup_v2110.py（36→已修）· test_time_mood_v2110.py · test_core_pack_v2110.py · test_boundary_claims_v2110.py 合计 **51 passed**；test_asset_absence_v244.py + test_full_form_frames_v24.py **27 passed**（新素材没打破旧判据）。 |

**当前 check_sync() = 16 个问题** —— 这是第 10 步尚未执行（绿版还没同步四个新模块与其它改动），**属于预期中间态**，不是缺陷。

### 8.6 第 3 轮进展 + **一个必须先收口的红**（2026-10-17 · dsh-main-r11）

**已落并绿**：walk 帧集（8 帧 + 6 条素材判据）· `pet_windows.py`（+94 条测试）· `pet_backup.py`（34 条测试 / 27 条变异 CAUGHT）· `pet_guard.py`（46 条测试 / 二次验收 11 条变异）· `pet_time_mood.py` · `pet_notify.py` + `pet_widgets.Bubble(hold_ms)`（18 条变异 CAUGHT）· ⑤ 用户数据台账 · A-07 反向钉子 · C-34 产品侧收口 · A-10 真机取证。

**⚠ 现在唯一的「非产品代码」红：`python -B _dev/silent_except_whitelist.py --check` rc=1** ——
三个新模块（pet_backup / pet_guard / pet_windows）带进来约 **30 条 unreviewed 静默 except 条目**。
我已手工给其中 ~19 条写了真理由（cleanup / probe / optional / fallback / reported，逐条含 why），
**剩下约 10 条还没写**（`pet_backup._short_time / _size_text / _skip_names / _write_zip_atomic ×2 /
collect_user_files / create_backup ×2 / is_user_data / list_snapshots`）。
它们看代码都属「返回一句人话 / 回默认值 / 回空集」的 `reported` 或 `fallback`，
**但本仓规矩是「白名单不许自动扩容」——必须有人逐条给理由，不许 `--seed` 批量盖**。
→ 下一个接手的人：照 `_dev/silent_except_whitelist.py` 的 reason 码表逐条补（10 分钟级），
然后 `--check` 必须 rc=0、`tests/test_silent_except_v252.py` 必须绿。

**其它已知红（都已定位，见各代理报告）**：
· `tests/test_release_check.py::test_本仓被导入的运行时模块都在发货清单里` → W1-b 已改成运行期口径（`check_imported_modules_shipped()` = `[]` 实测通过）。
· `tests/test_host_v2100_round.py::test_every_material_frame_play_site_carries_the_rate_token` → W2 已把 `walk` 加进那份「字面帧集播放路径」精确集合（4 passed）。
· `tests/test_readme_annotation_scope_matches_the_code` → README 已同步到 **296 函数**（M-C5 锚点也同步了）。
· `tests/test_slot_recover_frames_v24.py` 那条在**单跑时是绿的**（4 passed），全量里红 → 怀疑是 10 个 python 进程争用下的 0.6s 采样抖动 / 顺序污染，**冻结时要重跑确认**。

**接线还没做**（都等 桌宠.py 空出来 / 由我亲自）：`show_bubble(hold_ms=)` 透传、`_notify()`（系统通知 + 退回气泡）、
`_alarm_tick` 改用它、`⚙️ 设置…` 加「系统通知 / 备份数据… / 从备份恢复…」三条（**都在子菜单，顶层仍 18**）、
`DEFAULT_CONFIG` 加 `notify: True`、`SYNC_FILES` 加 `pet_notify.py`、`main.py` 的守护接线。
