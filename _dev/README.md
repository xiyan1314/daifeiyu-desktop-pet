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

## 一、变异验证（"这个护栏能真失败"的证据）

全部走 `_mutate_lib.py`：整仓复制到 `%TEMP%` **影子副本**，变异与 pytest 都在影子里做——
真实仓库只读，只在仓库里放一个运行锁**目录** `_dev/.mutation.lock/`（一个持有者一个 `<pid>.json`，
已 gitignore；发布门 `_check_release.mutation_lock_problems` 看到它会明确拒绝判定）。
**这解决的真实事故**：旧脚本原地覆写产品源码，变异窗口里别的进程跑全量门会看到来源不明的红
（本轮浪费了两位审查员的时间），且被强杀时会留下半变异源码。

| 脚本 | 干什么 | 复跑 | 结果落盘 |
|---|---|---|---|
| `_mutate_lib.py` | 影子副本 / 运行锁 / 结果 JSON 口径（M7） | 被下面 4 个 import，不单独跑 | — |
| `mutate_check.py` | 按 spec 逐条把修复拿掉，指定用例必须变红 | `python _dev/mutate_check.py _dev/mutations_x.json` | 回写 spec 的 `results` 段 |
| `mutate_export_slice.py` | 导出两段式 E1-E5 | `python _dev/mutate_export_slice.py [关键字]` | `mutations_export_slice_v242.json` |
| `mutate_startup_defer.py` | 启动延迟装载 M1-M8（8/8 CAUGHT） | `python _dev/mutate_startup_defer.py [关键字]` | `mutations_startup_defer_v242.json` |
| `verify_guardrails_can_fail.py` | 护栏 A1-A6 / B7-B8 定向变异（9 条） | `python _dev/verify_guardrails_can_fail.py` | `results_guardrails_can_fail.json` |

结果 JSON 的字段口径（M7）：`checked_at` 时间戳 + 每条 `id / verdict(CAUGHT) / rc / tail`。
`verdict` 里出现 `ANCHOR-LOST` 或 `SPEC-BAD` = 源码改了、spec 的替换锚点失效——**这条没被验证**，
要同步锚点后重跑，别把它读成"通过"。

**判定口径（v2.4.3 · 质量审查 M5）**：此前只看 `rc != 0` 就算 CAUGHT——"别的用例被负载抖红"
也会被记成"这条变异被抓住了"（`test_startup_defer_v242` 的 60ms 阈值在影子里实测抖到
96.4/70.3/97.2ms）。现在 spec 可以写 `expect_fail: [...]`：**它点名的用例必须全部出现在失败
列表里**才算 CAUGHT；没写就退回"`tests` 里至少一条必须在失败列表里"；rc≠0 但预期用例没红 =
`WRONG TEST`（同样计入未抓到）。每条结果都存下 `failed` 列表，便于复核"红的是不是它"。

**指纹比对（v2.4.3 · 质量审查 M4）**：`repo_fingerprint` 记的是**变异当时**关键文件的 sha256
前 12 位，此前没有任何人比对——结果 JSON 里 `桌宠.py` 记的是 `059b7abfa512`/`2ac5743967b1`，
与出货修订不是同一份。现在发布门（`_check_release.py` 的 `mutation_evidence_notes()`）逐个读
`_dev/*.json` 的指纹，不一致就打印"该证据已过期，需复跑对应 spec"（只提示、不挡发布；
过期是开发期的正常中间态，但**不许静默**）。

**基线为什么要重跑几次**：`run_baseline()` 在基线红时会重跑（最多 3 遍，间隔 3s）。原因不是放水，
而是时序敏感的用例在"影子副本刚复制出来 = 冷缓存 + 机器上还有别的会话在跑 pytest"时会偶发红：
`tests/test_startup_defer_v242.py::test_startup_task_is_chunked_not_one_shot` 断言"启动分片单轮 < 60ms"，
实测冷缓存首轮出现过 96.4/70.3/97.2 ms → 基线 1 failed，紧接着重跑就 0.55~0.99s 全过。
变异**本身**的判定仍然严格：rc==0 就是 NOT CAUGHT，收集期就炸才算 INVALID。

spec 清单：

| spec | 覆盖 | 状态 |
|---|---|---|
| `mutations_q_item1.json` | M-Q1..Q4 顶层未知键保留（pet_alarm / pet_behaviors） | 4/4 CAUGHT |
| `mutations_q_item2.json` | M-Q5..Q9 GBK 回退读（pet_lines 薄壳 → pet_io.read_json_fallback；收口时实现刚被搬到 pet_io，锚点已同步） | 5/5 CAUGHT |
| `mutations_q_item3.json` | M-Q10..Q15 语音/错误文案等 | 6/6 CAUGHT |
| `mutations_compat_v242.json` | M-C1..C15 v2.4.2 兼容修复 | 15/15 CAUGHT |
| `mutations_release_door.json` | G-D1/G-A1/G-L1 发布门新判据（D 条目 / 素材清单 / 变异锁） | 3/3 CAUGHT |
| `mutations_round3_a.json` | 本轮另一路代理的 spec（同一套机制） | 见文件 `results` |
| `mutations_relay_v243.json` | 启动接力 / 撒钱预载分片 / SND_PURGE（M-R1..R11，钉 `tests/test_relay_v243.py`） | 11/11 CAUGHT |
| `mutations_compat_v243.json` | 兼容审查 M1/M3/M4 + 质量审查 M1/M4/L2/L3 + 找茬复审 M1/M3/M5/L①（M-C1..C13） | 见文件 `results` |

---

## 二、探针（**只读测量**，不改产品代码）

| 脚本 | 量什么 |
|---|---|
| `probe_startup_cost.py` | `PetWindow()` 构造里每一段的实测占比（`--runs N --json out`） |
| `probe_export_cost.py` | `export_bundle` 各段占时（zip 写盘 vs 读取 vs 其它） |
| `probe_export_io.py` | 导出耗时归因（二）：首次读盘 vs 缓存命中 |
| `probe_ui_freeze.py` | UI 卡顿探针 v2（计数器插桩；它的 json 输出未入库） |
| `repro_frame_freeze.py` | 可复现的 UI 卡顿测量：每个卡点主线程被连续占住多久 / 事件循环真的卡住了吗。结果按 label 追加进 `_dev/ui_freeze_raw.json`（gitignore） |
| `probe_money_preload_gap.py` | **撒钱预载的事件循环缺口**：eager（v2.4.2 原样：一次同步解 86 帧）vs sliced（当前：按 _FRAME_SLICE_MS 分片），**每轮一个新进程** + 1ms PreciseTimer 心跳、交替采样（`--rounds N --json out`；`--repo <树>` 可量别的检出）。摘要见 `money_preload_summary.json` |
| `probe_test_order.py` | **反序探针**（pytest 插件）：把 `tests/test_export_slice_v242.py` 挪到收集顺序最前/最后，用来判定"这些红是不是被别的模块污染"——顺序无关的失败才是真失败 |

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
| `ui_freeze_report.md` | UI 卡顿修前/修后对照表（数字原文；配 `ui_freeze_summary.json`） |
| `startup_ab_summary.json` | 启动 A/B 摘要（每侧 10 轮：min/median/max + 解码数 + 首屏标志） |
| `export_ab_summary.json` | 导出 A/B 摘要（条目数 + order + 三项全等判定） |
| `ui_freeze_summary.json` | UI 卡顿摘要（按 label：n / worst_gap_ms / 中位 / 最慢 6 个场景） |
| `money_preload_summary.json` | 撒钱预载缺口摘要（4 轮交替、每轮新进程：eager 中位 70.9ms / sliced **单片** 12.3~12.6ms、**事件循环间隔**中位 25.5ms、入口 0.0ms、5~6 片、86/86 逐张 toImage 全等）。注意单片与循环间隔不是一回事，口径见该文件 `interpretation` |
| `pytest_v242_full.txt` | v2.4.2 定版那次全量的原始输出尾巴（632 passed）——提交信息引用它，别删 |
| `pytest_v243_full.txt` | v2.4.3 全量输出（`python -m pytest tests -o addopts="" -q` → **691 passed / 0 failed**，65.4s；连跑两次同结果）。定版提交信息引用它 |

`gen_full_idle_frames.py` 是**素材生成器**（`assets/character_full.png` → `assets/idle_full_f00..f09.png`），
不是探针：`tests/test_full_form_frames_v24.py` 会按路径加载它并逐像素比对，**别改名**；
`python _dev/gen_full_idle_frames.py --check` 可单独校验素材是否被手改过。

---

## 七、已删除（2026-10-10 第三轮收口，被取代/已降级为摘要）

- `startup_before.json` / `startup_after.json`：非交替样本（同一棵树连测，会被负载漂移骗）→ 由 `*_ab_summary.json` 取代
- `export_payload_drift_before_NOT_AB.json` / `_after_NOT_AB.json`：文件名自己标了"非 A/B"→ 删
- `ui_freeze_raw.json` / `startup_ab.json` / `export_ab.json`：原始逐轮/逐条目数据 → 摘要 + 复跑命令，原始文件已 gitignore
- `__pycache__/`：编译缓存

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

## 九、本轮明确不修（留给 v2.4.4，附理由）

| 条目 | 为什么留到下一轮 |
|---|---|
| **复审 M2**：`pet_balance` 的 `_fetching_balance` 由 worker 的 finally 复位，槽还没跑时用户再点一次会真起第二个并发线程（会多弹一次气泡/金币音/撒钱） | 修法要么把复位改回槽独占、要么引入请求代次，会连带改掉 P1-1 的三条用例与 `mutations_round3_a.json` 的 M-A1/A2 证据；本轮只做了两处无争议的收口：M1（`refresh()` 的 `start()` 兜底）与 L①（`_closing` 用 `getattr(..., False)`） |
| **复审 M4**：状态图分片的"零推进自锁"整表清空 pending，异常后那个状态永久缺图 | 唯一触发路径是 `_ensure_state_pix` 抛异常（静态可证 pending 的名字集合 ⊆ `_STATE_MARK_MAP`，非异常路径不可达）。改成 `_state_pix_dead` 死名单要同时改 relay 用例与 `mutations_relay_v243.json` 的 M-R8（那条钉的正是"自锁"），属独立一轮的活 |
| **复审 L④**：`pet_fx.py` 的 86 / "money" 仍是写死的（"单一来源"只在 `桌宠.py` 内成立） | 单源化要动 import 方向（`pet_fx` 被 `桌宠` import），本轮只在 `桌宠.py` 内把帧数/前缀具名；`pet_fx.py` 那两处下一轮统一 |

> 找东西的捷径：`_dev` 里的 `.py` 都能单独跑（`python _dev/<名字>.py`，Qt 类的会自动 offscreen）；
> 会写文件的只有三类——`gen_full_idle_frames.py`（素材）、探针的 `--json` 输出、变异验证的结果 JSON。
