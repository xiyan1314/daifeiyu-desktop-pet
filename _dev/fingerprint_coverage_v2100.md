# 指纹覆盖残留 · 逐文件评估（v2.10.0 第 8 轮 · 代理 C · 任务 R6）

> **v2.11.0 第 9 轮补记（代理 C · 父代理授权）**：清单 **28 → 29**，新补 `pet_motion.py`
> （本轮新增的**动效令牌表**：后续所有动效的时长/缓动/幅度都挂在它上面，改它 ≈ 改所有动效；
> A 的 spec 有 **3 条锚点**在它上面 → 此前是零提示盲区）。两处清单同时改，`test_release_check.py` 41 passed。

> **一句话**：全库 **35 个锚点文件 / 478 条变异**里，**14 个文件 / 428 条**有指纹覆盖，
> **21 个文件 / 50 条**是"改了它 → 一条「证据过期」提示都不会有"的真盲区（v2.9.0 第 7 轮是 18 / 46；
> **+3 文件 / +4 条是代理 C 本轮自己的新 spec 造成的**，如实记账）。
> 本文逐文件给裁决与理由；最终**补了 14 个文件（34 条）**，其余 7 个文件（17 条）写明为什么不需要。
> **✅ 已落地（v2.10.0 第 8 轮收尾 + 质量审必修）**：两处清单都补到 **28 个键**，探针复跑实测
> **覆盖 28 文件 / 472 条 · 盲区 7 文件 / 17 条**，两处清单**逐项一致**，
> `pytest tests/test_release_check.py` **37 passed**。落地过程与越界留痕见 §三。
> ⚠ **第 14 个文件是质量审必修 A 追加的**：`tests/test_import_thread.py` 与 `tests/test_dialog_buttons_v270.py`——
> **承载锚点的测试文件**。实测缺口：把 `test_import_thread.py` 那条用例体清空（nodeid 不动）→
> `check_mutation_nodeids` **rc=0 / 坏 0**（名字还在），而同一条变异 `M-C2100-R4-01` **CAUGHT→NOT CAUGHT**，
> **指纹一声不吭**。**只加"承载锚点的两个测试文件"，不是整个 `tests/**`**（整目录会把每次测试改动都变成过期噪音）。
> **⚠ 但"覆盖 458 条"这句话要到定版整批复跑之后才在盘上成立**：盘上 **30 份**有指纹段的证据仍只记着 14 个键 →
> 发布门 `mutation_evidence_notes()` 会多出 **362 条"缺键"提示**（只提示、不进 fails），
> 且 `_check_release.py` 自身哈希因本次改动而变 → 全部证据对它也报"过期"。**这批提示由定版整批复跑一次性消掉。**

**数据来源（可复跑，只读）**：`python -B _dev/probe_fingerprint_gap_v290.py`
（2026-10-16 本轮实测；该脚本是 v2.9.0 第 7 轮代理 C 落的探针，本轮直接复用，未改一行）。

## 一、现状（本轮实测）

```
指纹清单：发布门 14 个 / 变异库 14 个 —— 逐项一致
清单内容：桌宠.py / pet_export.py / pet_lines.py / pet_alarm.py / pet_behaviors.py / _check_release.py /
          pet_balance.py / pet_plugin.py / pet_plugin_host.py / pet_dialogs.py / pet_menu.py /
          pet_plugin_index.py / pet_ai.py / pet_config.py

spec 27 份 / 变异 478 条，锚点落在 35 个文件上
  ① 已被指纹覆盖（改它 → 证据会报「过期」）：14 个文件 / 428 条变异
  ① 未被指纹覆盖（改它 → 零提示，真盲区）：21 个文件 / 50 条变异
```

**这条盲区已经咬过四次**（README §一 已记）：v2.4.4 的 `pet_balance.py` · v2.5.1 的四个对话框模块 ·
v2.6.0 的 `pet_plugin_index.py` · v2.9.0 的 `pet_ai.py` / `pet_config.py`。
每次都是"改了它、锚点随之失效或语义漂移，而发布门**一声不吭**"。

## 二、裁决表（21 个未覆盖文件，逐条）

**进 = 建议加进两处清单**（`_check_release.MUTATION_FINGERPRINT_FILES` 与
`_dev/_mutate_lib.repo_fingerprint`，两处由
`tests/test_release_check.py::test_fingerprint_file_list_matches_the_mutation_lib` 钉成**逐项一致**）。

| # | 文件 | 条数 | 变异 ID | 裁决 | 理由 |
|---|---|---|---|---|---|
| 1 | `pet_io.py` | **9** | M-C2100-R4-02 · M-C4 · M-C5 · M-Q6 · M-Q7 · M-Q8 · M-A11 · M-A12 · M-A15 | **进** | 出货模块，**全库最大的单点盲区**（9 条）。写盘/读盘/回退这套语义最容易被顺手重写，改它零提示最危险 |
| 2 | `pet_services.py` | 3 | M-S1 · M-S2 · M-S3 | **进** | 出货模块（服务注册表；实参级 golden 就锚在它上面） |
| 3 | `pet_widgets.py` | 3 | M-C3 · M-A4 · M-A5 | **进** | 出货模块（公共控件；多个对话框口径建在它上面） |
| 4 | `pet_resources.py` | 2 | B3-DROP-LOG · M-S2 | **进** | 出货模块（动作/素材名册；动作候选就来自它） |
| 5 | `pet_tools.py` | 2 | M-S6 · M-S17 | **进** | 出货模块 |
| 6 | `pet_voice.py` | 2 | M-Q10 · M-Q15 | **进** | 出货模块（语音；M-Q10/Q15 就是它的错误文案与回退） |
| 7 | `pet_audio.py` | 2 | M-A7 · M-S3 | **进** | 出货模块（音频库事件） |
| 8 | `pet_chat.py` | 2 | M-A9 · M-A16 | **进** | 出货模块（对话轮次/回执） |
| 9 | `pet_log.py` | 2 | M-S7 · M-S8 | **进** | 出货模块（日志通道；静默 except 的口径依赖它） |
| 10 | `pet_actions.py` | 1 | M-C14 | **进** | 出货模块 |
| 11 | `pet_book.py` | 1 | M-Q14 | **进** | 出货模块（账本） |
| 12 | `_check_static.py` | 1 | MF4-undef-check-neutered | **进** | **按 `_check_release.py` 的同一条逻辑**：它自己就是被测对象（MF4 变异的就是它的判据），而且它是发布流程里真跑的一环。既然 `_check_release.py` 在清单里，它就该在 |
| 13 | `requirements.txt` | 3 | M-C4 · M-A6 · M-A7 | 不进 | 依赖清单：三条锚点点名的都是"**这几行必须在**"，`--scan-only` 命中恰好 1 次即证明还在（锚点自证）；且每加一个依赖就变 → 高噪音零信号 |
| 14 | `README.md` | 3 | M-C5 · M-A13 · M-A14 | 不进 | 文档，不在被测路径上；它的口径由**用例**钉（`tests/test_round3_a_fixes.py` 之类：删掉那段说明 → 用例红）。计入指纹 = "改一个错别字 ⇒ 27 份证据全报过期" |
| 15 | `.github/workflows/ci.yml` | 1 | M-A8 | 不进 | CI 配置：不进发布包，不参与任何被测行为 |
| 16 | `_dev/silent_except_whitelist.py` | 5 | M-C-d1 · M-S9 · M-S10 · M-S11 · M-S12 | 不进 | `_dev/**` **不进发布包**（`_check_release.ZIP_EXTRA_PREFIX = ("_verify_assets/", "_dev/")`，有用例钉住）；它的正确性由 `tests/test_silent_except_v252.py` 兜 |
| 17 | `_dev/plugin_format_v251.md` | 2 | M-G6 · M-G7 | 不进 | 同上（文档在 `_dev/` 下）；它钉的是"文档 ↔ 常量双向契约"，那条契约有专门用例（改任一侧就红） |
| 18 | `_dev/mutate_check.py` | 1 | M-C2100-R5-01（本轮新增） | 不进 | **自指条目**：它是**判定器本身**。把证据生产机器计入指纹，含义会从"被测源码漂了"变成"有人碰了任何文件"——每轮改 `_dev/` 都会让全部 27 份证据报过期。它自己的守卫是**回归用例**（`tests/test_mutate_harness_v244.py` 14 条）＋本轮新加的"新旧口径对照探针"`probe_judge_error_lines_v2100.py` |
| 19 | `_dev/_mutate_lib.py` | 1 | M-C2100-R5-02（本轮新增） | 不进 | 同上（影子副本/运行锁/抽取器都在这份里；它一变，全库证据的**生产条件**就变，但那不等于"被测源码漂了"） |
| 20 | `tests/test_dialog_buttons_v270.py` | 3 | M-A-29 · M-A-30 · M-A-31 | **进**（质量审必修 A 改判） | 它是**承载锚点的测试文件**：用例体被清空而 nodeid 不动时，nodeid 体检**抓不到**、判定却会静默失效 → 只有指纹能出声。**不是整个 `tests/**`**（那样每次测试改动都变过期噪音） |
| 21 | `tests/test_import_thread.py` | 1 | M-C2100-R4-05（本轮新增） | **进**（同上） | 同上；实测反例就是它（清空用例体 → R4-01 变 NOT CAUGHT 而指纹不响） |

**加完之后的账**（收尾实测）：全库 **28 份 spec / 489 条变异**，锚点落在 35 个文件上——
**覆盖 28 个文件 / 472 条**，未覆盖 **7 个文件 / 17 条**（第 13~19 项：ci.yml 1 · README.md 3 ·
`_dev/_mutate_lib.py` 2 · `_dev/mutate_check.py` 1 · `_dev/plugin_format_v251.md` 2 ·
`_dev/silent_except_whitelist.py` 5 · requirements.txt 3）。
覆盖率从 **428/478（89.5%）** 升到 **472/489（96.5%）**。

## 三、推荐补丁（**两处必须同时改**，否则一致性用例当场红）

`_check_release.py:739-742`（**A 的领地**）：

```python
MUTATION_FINGERPRINT_FILES = ("桌宠.py", "pet_export.py", "pet_lines.py", "pet_alarm.py",
                              "pet_behaviors.py", "_check_release.py", "pet_balance.py",
                              "pet_plugin.py", "pet_plugin_host.py", "pet_dialogs.py",
                              "pet_menu.py", "pet_plugin_index.py", "pet_ai.py", "pet_config.py",
                              # v2.10.0 第 8 轮（R6）：补 12 个"有锚点、却零提示"的文件
                              # （pet_io.py 一处就 9 条）。逐条理由见 _dev/fingerprint_coverage_v2100.md
                              "pet_io.py", "pet_services.py", "pet_widgets.py", "pet_resources.py",
                              "pet_tools.py", "pet_voice.py", "pet_audio.py", "pet_chat.py",
                              "pet_log.py", "pet_actions.py", "pet_book.py", "_check_static.py")
```

`_dev/_mutate_lib.py:262-264`（**我的领地，但必须与上面同一次提交**）——
`repo_fingerprint` 里那条同样的元组追加**逐字相同的 12 个名字、同样的顺序**。

**机械约束**：`tests/test_release_check.py` 有一条用例把两处清单钉成**逐项一致（顺序也一致）**，
所以**只改一处 = 全量 pytest 当场红**。

**✅ 落地记录（2026-10-16 收尾）**：`_check_release.py` 不在代理 C 的领地内（任务书 ⛔"不要碰产品代码"；
v2.9.0 第 7 轮 C 往这里加两个字符串时被记为"越界一处，已获批、零逻辑"），
**父代理显式授权（选①）后由 C 落地**：
- `_check_release.py:739-742` 只追加**文件名字符串**（2 行注释 + 4 行名字），
  `git diff -U0` 实测**恰好 1 个 hunk、+6/-1、零逻辑行**；
- `_dev/_mutate_lib.repo_fingerprint` 同步加**逐字相同的 12 个名字、同样的顺序**；
- 探针复跑：`发布门 26 个 / 变异库 26 个 —— 逐项一致`；
- `pytest tests/test_release_check.py` → **37 passed**。
- 两个兼容/找茬审查各自独立复核过这一处（1 个 hunk、零逻辑），并实测**新键真能判过期**
  （给 `pet_io.py` 加一行注释 → 发布门报 `pet_io.py: 6b1e0413fb7f→…`，复原后消失）。

**⚠ 三条裁决"未能证伪"（兼容审原话，如实记账，别读成"已证明"）**：`requirements.txt` / `README.md` /
`.github/workflows/ci.yml` **不该进指纹**这三条，审查方**没有找到反例**，但也**没有证明**它们永远不会成为盲区——
维持本裁决，但把"未能证伪"写在这里；一旦出现真实盲区实例，按 §四 的"什么情况下回来改判"处理。

## 四、为什么不"一股脑全加"

一把全加（21 个文件）看着最省事，实际会把指纹从**信号**变成**噪音**：
`_dev/**` 与 `tests/**` 每轮都在动，文档/依赖清单/CI 配置也动，
于是每个中间态都挂着几十条"证据过期"，读的人第三次之后就开始忽略这条通道——
**而这条通道正是前四次盲区里唯一能出声的那条**。判据宁可**窄而准**：
**"指纹 = 被测源码的版本戳"**，它回答的问题是"这份证据是对着这一版**被测代码**跑的吗"，
不是"这棵树跟当时一模一样吗"（后者由 `results` 的 `checked_at` ＋ `--scan-only` ＋ nodeid 体检分别回答）。

**什么情况下要回来改判**（把反驳条件写下来，免得裁决变成教条）：
1. 第 16~19 项（`_dev/**` 自指条目）如果出现"判定器改了、而旧判定**悄悄**失效"的实例
   （即回归用例没兜住），说明"用例兜底"这个前提不成立 → 那时再把 `_dev/mutate_check.py` /
   `_dev/_mutate_lib.py` 加进去。**这条已经有一次实测教训**：`tests/**` 原本也按"用例兜底"判"不进"，
   质量审证明**兜不住**（用例体被清空、nodeid 不动 → nodeid 体检与判定双双静默）→
   **承载锚点的测试文件改判为进**；剩下的 `tests/**`（不承载锚点的那些）仍靠 nodeid 体检 + 判定本身兜；
2. `requirements.txt` 如果出现"锚点还在、但依赖语义已变"的实例（例如换成 `>=` 约束却没人发现），
   就把它加进去（那时它不再是"锚点自证"的文件）；
3. `README.md` 同理：如果出现"说明被改坏而用例没红"的实例，就该给它**单独一条文档契约用例**，
   而不是靠指纹（指纹只会说"文档变了"，不会说"哪句话变错了"）。

## 五、复跑与验收（给落地的人）

```powershell
python -B _dev/probe_fingerprint_gap_v290.py          # 实测（已落地）：14 个键 → 28 个键；未覆盖 50 条 → 17 条
python -B _dev/mutate_batch_v270.py --scan-only       # 锚点合计/坏 0（改清单不动锚点，习惯性过一遍）
python -B -m pytest tests/test_release_check.py -o addopts= -q    # 一致性用例必须绿
```

**⚠ 加键的副作用（预期内，别误读）**：盘上 **30 份**证据（有指纹段的共 32 份）都**没有**这 12 个新键 →
发布门 `mutation_evidence_notes()` 会多出"缺键"提示，直到**定版整批复跑**（铁律 5）把指纹补齐。
这正是 README 里写好的那条路（"要消掉缺键那条只有两条路：重跑对应 spec，或在报告里点名
『这份证据不覆盖这几个模块』"）。
