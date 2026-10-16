# v2.11.0 三审任务书（找茬 / 质量 / 兼容）

> **谁写的**：v2.11.0 收尾执行者（2026-10-16 09:35）。
> **为什么写**：本仓铁律——**证据必须对着出货修订**，而三审必须**锚在冻结哈希**上；
> 任务书写在磁盘上，是为了让三审**可复核、可追责、不靠转述**（转述 nodeid 出过事，见 §七 纪律）。

## 零、开工第一步（**不做完不许开始审**）

```powershell
cd 'E:\deep seek\desktop-pet'
# 逐条算，与下表**逐位比对**；只要有一条不符 → **停手，报给派单的人**，不许"差不多就行"
@('pet_motion.py','桌宠.py','pet_dialogs.py','pet_config.py','pet_widgets.py','_check_release.py','README.md','README.en.md','CHANGELOG.md','version_info.txt','_verify_green.py','tests/test_motion_v2110.py') | % {
  '{0,-34} {1}' -f $_, (Get-FileHash $_ -Algorithm SHA256).Hash.Substring(0,12) }
```

### 冻结哈希 —— 产品/测试侧（**审查对象就是这一批；整批不改它们**）

| 文件 | sha256 前 12 位 |
|---|---|
| `pet_motion.py` | `FCEE7AB63BB2` |
| `桌宠.py` | `59B2F99C52BA` |
| `pet_dialogs.py` | `7E1A11CFF2A2` |
| `pet_config.py` | `6FE2B20AE424` |
| `pet_widgets.py` | `B8DE517121E1` |
| `_check_release.py` | `7377B3FAD58E` |
| `README.md` | `5FF173710B15` |
| `README.en.md` | `12D2B7B660FF` |
| `CHANGELOG.md` | `5908CD0B73F5` |
| `version_info.txt` | `6D547B045DA1` |
| `_verify_green.py` | `（开工时现算，与 §三 的版本行对照）` |
| `tests/test_motion_v2110.py` | `（开工时现算）` |

**出货修订 = 提交 `b28bdac`**（工作树在它之后还有整批回写的 `_dev/*.json` 与两份新文档，见下）。

### 冻结哈希 —— `_dev` 证据侧

⚠ **这一侧在「证据整批」（`python -B _dev/mutate_batch_v270.py`）跑完之后会被改写，那是预期，不是漂移。**
整批会把 `pinned_ast`（pinned 用例体 AST 摘要）与**跑前跑后源码指纹**写回各 spec 的 `results` 段。
**所以：不要因为 `_dev/mutations_*.json` 的哈希变了就停手**（上一轮找茬中途停手是对的，那是因为当时**产品侧**哈希变了）。
要判「证据是否对着出货修订」，用这两个工具（秒级、只读）：

```powershell
python -B _dev/check_pinned_ast.py          # 期望：过期 0 条、已消失 0 条
python -B _dev/mutate_batch_v270.py --scan-only   # 期望：锚点合计 556 条，坏 0 条
python -B _dev/check_mutation_nodeids.py    # 期望：校验范围内 1311 条，坏 0 条
```

## 一、本轮改了什么（三审的靶子）

**v2.11.0 = 第 9 轮（无障碍与反馈）+ 并入的 v2.10.0 清账内容**。
两轮改动交错在同一棵未提交的工作树里、**无法干净分离**（用户已裁决合并发布），
所以**合并后的树由本次三审 + 独立验收重新验证**。

### 1a. 第 9 轮（代理 A / B / C）

- **A**：`pet_motion.py`（新：动效令牌表 `DUR`/`EASE`/`SCALE`/`GLOW`/`OUTLINE`/`RIPPLE`/`THINKING`/`HEART`/`DRAG` + 纯函数 `duration_ms`/`effective_duration`/`animation_enabled`/`easing_name`/`visual_scale`/`reduce_motion_enabled`/`high_contrast_enabled`/`palette`/`contrast_ratio`/`bubble_colors`/`parse_hex`/`system_reduce_motion`/`system_dark_theme`）· `桌宠.py`（视觉三件套 A4：悬停光晕/按下描边/点击涟漪 · 贴边 300ms 缓动 A5 · 减少动效 A2 · 高对比度 A3 · 键盘可达 · 拖拽阈值 8px 与光标 · 双击走事件 · AI 在途指示 · 气泡锚点）· `pet_widgets.py`（气泡淡入淡出 + 跟随 + 高对比度配色）· `pet_dialogs.py`（V7 台词库边界回执统一成内联状态行）· `tests/test_motion_v2110.py`（48 条）· README 两份函数数同步（桌宠 291 / pet_dialogs 398）。
- **B**：`pet_chat.py`（B6 错误可操作：200 但结构坏单独归类、兜底不再谎称网络）· `pet_dialogs.py`（B5 tooltip 与常驻小字 · B8 朗读在途/失败反馈 + `_voice_waiting` 闸门 + 钩子只挂一次 · A2/A3 菜单接线）· `tests/test_feedback_v2110_b.py`（21 条）。
- **C**：V1 pinned 用例体 AST 摘要（`_dev/check_pinned_ast.py` 新增，可判过期的变异 **7/489 → 489/489**）· V2 teardown 相位不计检出 · V3 `_short` 跨文件顶替修复 · V5 三处文档更正 · V6 第 21 条结案 · **P1 判据改造**（删掉会必然假红的比例上界 0.90，换成不可解析槽精确多重集名单 + 解析器自检）· `_check_release.py` 也读 `pinned_ast`（+150/−2，8 个 hunk）· 重锚 `M-C12`/`M-C5`。

### 1b. 并入的 v2.10.0 清账内容

行为重名四选一 · 导入素材提示解释清楚 · 两处入口明说「取消会不会撤销」· 判定器假阳性路修复（pytest 回显的 ERROR 行）· 指纹覆盖 **14 → 29** · 恒真断言系统性清理（含"断言写在平台走不到的分支里"那种隐蔽形状）。

### 1c. 收尾执行者本轮的改动（**就是本次三审最该盯的部分**）

| # | 改动 | 定性 | 为什么这么改 |
|---|---|---|---|
| 1 | `pet_config.normalize_cfg` 补 `reduce_motion`/`high_contrast` 枚举归一化 | **产品缺陷修复** | 新键漏在归一化之外 → 手改 config.json 塞 `null`/`[]`/`123` 会带着坏值一路进判定 |
| 2 | `tests/test_io_v231.py` 的 `_Stub` 补 `_reset_pointer_state`/`_press_squash`/`unsetCursor` | **用例落后于协议** | `closeEvent` 在"收进托盘"分支多调了一次复位；替身按真实协议转发（**断言一个字没改，另加一条**） |
| 3 | `pet_widgets.BUBBLE_STYLE_CANON` + `tests/test_motion_v2110.py` 的 `win` 夹具 pinned/断言/复原 | **夹具污染**（不是产品缺陷） | 全局 `BUBBLE_STYLE` 被别的用例改成 `#445566` 不还原 → 全量跑红、单跑绿 |
| 4 | `_LEFTOVER_IN_INIT` 登记两个只读系统探针 + 写清"什么算合法残留" | **红线口径**（父代理裁决） | ⚠ **这一条必须由三审独立判** |
| 5 | `pet_dialogs._route_voice_event`：`except Exception` → `except RuntimeError` | **收紧**（审计裁决） | 原来会把重构引入的 `AttributeError`/`TypeError` 也吞掉 —— 那正是 B8 要修的那条路 |
| 6 | `pet_motion.duration_ms` 去掉不可能的 `TypeError` + 新增 `test_every_token_value_is_numeric` | **收紧 + 补判据** | `str(name)` 之后 `ValueError` 只可能来自"表里写了非数值"＝自己写错，不许静默回 0 |
| 7 | `_dev/silent_except_whitelist_summary.json` 登记 17 条新键 + 1 条 count 变化 | **数据** | 见 `_dev/silent_except_whitelist.py --check`（现 323 条 / `unreviewed` 0） |
| 8 | `_dev/errors.md`（新增） | 文档 | 审计员建议的追加型错误留痕；第一条家族＝夹具没有复原全局状态 |
| 9 | 版本五处升 2.11.0 + `CHANGELOG` 首条 + `_release_notes_v2110.md`（新增） | 定版 | 含"本版包含 v2.10.0 清账内容"与"明确没做/登记"一节 |

## 二、五门读数（**收尾执行者亲手跑，安静窗口，PRE/POST 三查都有**）

| 门 | 命令 | 读数 |
|---|---|---|
| pytest | `python -B -m pytest tests` | **1462 passed, 25 warnings in 268.97s（exit 0）** |
| 护栏 v13 | `python -B _verify_v13.py` | **TOTAL CHECKS: 273, FAILS: 0 / V13 VERIFY ALL OK（exit 0，26s）** |
| 静态体检 | `python -B _check_static.py` | **问题 0 条，待确认 0 条（exit 0）** |
| 锚点体检 | `python -B _dev/mutate_batch_v270.py --scan-only` | **锚点合计 556 条，坏 0 条（exit 0）** |
| nodeid 体检 | `python -B _dev/check_mutation_nodeids.py` | **校验范围内 1311 条，坏 0 条（exit 0）** |
| pinned 体检 | `python -B _dev/check_pinned_ast.py` | **8 份 / 205 条 / 过期 0（exit 0）** |
| 变异体 AST | `python -B _dev/check_mutation_ast.py` | **531 条 / 0 不过（exit 0）** |
| 静默 except | `python -B _dev/silent_except_whitelist.py --check` | **判定通过：323 条 / unreviewed 0（exit 0）** |
| 版本 | `_check_release.check_version()` | **fails=[]（空）** |

**三查（缺一不可）在跑门前后各记一次**：无锁（`_dev/.mutation.lock` 不存在）+ 无 python 进程 + 无写入者；
并比 `pet_dialogs.py` 哈希（PRE/POST 一致 = 跑的时候没人动）。

## 三、四个重点（**必须给结论，不许"看着没问题"**）

### 重点 1：A4 三件套的"几何不变"与"对象数回基线"

- 悬停只做**光晕**、按下只补**描边**——**几何是否真的不变**（要看断言，不看眼看）：窗口尺寸 / `scale` / `squash` / item 变换 / item 位置**五元组逐项**；
- **点击涟漪**收尾后**场景对象数是否真的回到基线**（"看起来没了"不算）；
- 反查：`pet_motion.SCALE` 里 `HOVER`/`PRESS` 是否被钉成 `1.0`，以及有没有别的地方偷偷改缩放。

### 重点 2："减少动效"覆盖的完整性

- **逐条列举**所有动效点（令牌表 `DUR` 的 12 个键 + 一次性动效 + 脉动 + 气泡淡入淡出 + 贴边 + 涟漪 + 心形），**每一条**是否都被开关覆盖；
- **关掉后终态与开着一模一样**（只是瞬时）——不许出现"关掉之后某个东西留在半路"；
- **素材帧的边界**：A 声明"素材帧序列不随开关停（停掉等于把角色冻成一张图）"，产品决策 D1（**下一轮**）要改成"放慢帧率、不停帧"。**本轮要判的是：这条边界是否被如实登记、有没有被静默扩大**。

### 重点 3：`_LEFTOVER_IN_INIT` 那两个只读系统探针的登记口径（**红线口径，必须独立判**）

- 被登记的是 `pet_motion.system_reduce_motion()` / `system_dark_theme()`（`桌宠.py:1128-1129`）；
- 父代理定的口径：**只读系统探针（不构造服务、不持状态、不 import 重物）算合法残留**；**持有生命周期/资源的不算**；
- **三审要独立判**：① 这两条是否真的满足上面的口径（读码，不是读注释）② 这个口径本身是否会被用来把"服务构造"混进来（**判据的形状是否够硬**）③ 是否需要更硬的机检（例如断言这两个调用的返回值被赋给"普通属性"、不接受参数、不返回持有型对象）。

### 重点 4：静默 except 的"两类"判据 —— **它现在没有牙齿**（审计已指出）

- 现状：白名单**只要给理由码就绿**，**没有任何测试区分**"对象已死"（`RuntimeError`，忽略正确）与"我写错了"（`TypeError`/`AttributeError`）；
- 本轮已做两处**收紧**（见 §1c 的 #5/#6），但**判据本身仍无机检**；
- **三审要判**：该不该加机检、加什么形态（例如"`cleanup`/`teardown` 只许出现在只吞 `RuntimeError` 的 handler 上；吞 `Exception`/`TypeError` 的必须归入留痕类"），**以及这个形态在现有 323 条上会不会假红**。
- 附加题：**P1 那条"极松上界 0.95 绊线"**（审计员实测：树里出现全新写法、而解析器恰好错误解析它时，现口径的名单与自检**都不响**，而旧的 0.90 上界会响）→ **判该不该补**。

## 四、报告格式（**硬要求**）

1. **每条发现给 `文件:行号` + 是否实测**（实测＝你亲手跑/亲手读到的，附命令或原文片段）；
2. **查不到就说查不到** —— 不许"大概/应该/看起来/没问题"；
3. **把「必须在发版前改」与「可以登记到下一轮」分开列**（上一轮找茬这么做，效果很好）；
4. **对 §1c 的 9 条逐条给"我同意/我不同意这个定性"**（尤其 #3 夹具污染 vs 产品缺陷、#4 红线口径）—— **本轮最有价值的判断就是"定性对不对"**；
5. 开工时若产品/测试侧哈希与 §零 不符 → **停手报，不要接着跑**。

## 五、边界与已知项（**不许把"已登记"读成"没做"，也不许把"没做"读成"已登记"**）

- **D1–D4（用户已拍板的产品决策）未开始** —— 任务书的硬次序是"**等 v2.11.0 发出去之后再做**"（不许把未验证的新功能塞进正在收尾的版本）；
- **E1–E6（前几轮欠账）未开始**（E6 的"31 份缺 pinned 段"由本次整批**部分**解决）；
- **A 的 24 条变异 `expect_fail` 仍全空** → 判定走松一档的默认口径（证据成立，但下一个人改动这些用例时判定会先变宽再暴露）；
- **静默 except 两类判据无机检**（见重点 4）；
- **审计员押后的三条**：白名单机检 · P1 的 0.95 绊线 · 三处"文档比代码旧"（`_check_release.py` 注释的"28 个键"实为 29 · `_dev/fingerprint_coverage_v2100.md` 同页 14/28/29 · `_dev/b3_submit_model_v290.md` 的行号已漂）；
- **`prompts/default.txt` 那次未归因删除**：本机 2026-10-16 08:58:32 它被**重新生成**（写入门槛是"仅当不存在时写"）→ 那一刻它不存在。**产品代码里没有任何删 `prompts/*.txt` 的路径**（已逐处核过三处 `os.remove`）；**重生成内容 == 内置 `SYSTEM_PROMPT`，绿版那份也一致，没有用户内容丢失的证据**。**但"发生过一次删除"与"没丢内容"是两件事**，发布说明已按这个口径写。

## 六、审查对象与领地（请照本仓规矩）

- 三审**只读**；要改东西**不要自己改**（写成发现交给派单的人，先收齐全部审查再一次改）；
- 建议**动手前把整棵树复制到独占影子**（含 `.git`）—— 上一轮正是这一步救回了作废的锚点；
- **三审期间树必须静止**（任何人都不许开始修）；
- 别在共享仓里跑取锁的东西（`mutate_check` 会放 `_dev/.mutation.lock`，会让别人的全门读数作废 —— 本轮已经发生过一次）。

## 七、为什么这些规矩存在（给三审的上下文，不是说教）

- **转述 nodeid 出过事**：值班人手抄长 nodeid 少了一个 `play_`，那条变异会永远判不成 CAUGHT —— 所以**转述变异原料一律走文件通道**，nodeid 不许手抄；
- **冻结后有人接着改 = 三审锚点作废**（上一轮我犯了三次，代价是三次冻结作废）→ **先收齐、再一次改、改完再冻、冻完再验**；
- **"树必须静止"不只适用于三审，而适用于所有护栏运行**（三查：无锁 + 无 python + 无写入者，缺一不可）；
- **改判据的人没有资格自己选"抬高阈值"** —— 抬高阈值 / 改判据构造 / 修代码是**三件不同的事**。

