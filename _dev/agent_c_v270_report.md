# v2.7.0 代理 C 完工报告（插件线小账 a~d + 铁律 5 整批复跑）

记录：2026-10-15 · 代理 C（会话 session-43fb 子代理）· 基线 HEAD `9f7fb78`（v2.6.1）

---

## 0 结论速览

| 项 | 数字 | 备注 |
|---|---|---|
| 小账 a~d | 4/4 完成 | 每条都有「能真失败」的原文证据（见 §2） |
| 新变异 spec | `_dev/mutations_plugin_c_v270.json` 7 条 | **7/7 CAUGHT**（跑完复查仍是 7/7） |
| 新用例 | `tests/test_plugin_market_v270.py` 9 条 | 全绿 |
| 铁律 5 整批 | **22 项 / 268 条判定** | SPEC-BAD **0** · ANCHOR-LOST **0** · WRONG TEST **0** · NOT CAUGHT **0** · INVALID **0** · BASELINE-RED **0** |
| pytest | **1143 passed, 0 failed**（156.09s） | `python -B -m pytest tests -o addopts="" -q` |
| v13 | **TOTAL CHECKS: 273, FAILS: 0** | `python -B _verify_v13.py` |
| 静态 | **问题 0 条，待确认 0 条** | `python -B _check_static.py` |

**⚠ 一句话定性**：证据整批的**判定通道全绿**，但它是**并行窗口的中间态、不作发布依据** ——
A、B 当时正在改 `桌宠.py` / `pet_dialogs.py`，批次跑前跑后指纹不一致（见 §3.4）。
这一批的价值是两条：① 找出并修好断裂锚点；② 证明**当前源码上每条变异都能被抓住**。
定版必须在安静窗口用同一条命令重跑。

**领地声明**：只改了 `pet_plugin_host.py` / `pet_plugin_index.py` / `_dev/**`，
**没碰** `pet_dialogs.py` / `桌宠.py` / `pet_balance.py` / `pet_resources.py`。
另新建了 `tests/test_plugin_market_v270.py`（a~d 都要求「用例 + 变异」，任务书的领地清单只列了
三个文件、没列 tests/；新建**独立文件**是为了不与 A、B 的测试文件冲突，已在回报里点名）。
未提交（任务书要求统一提交）。

---

## 1 改动清单

| 文件 | 改了什么 |
|---|---|
| `pet_plugin_index.py` | `PluginIndex.install_file`：新增「索引条目的 `data_kind` ↔ 包的 manifest `data_kind`」核对（小账 a） |
| `pet_plugin_host.py` | `install_zip`：`history` 与 `.prev-<id>/` 强制成对（4 个分支 + 孤儿清理，小账 b）；登记写失败分支补「上一版目录挪回去」（b 的连带）；`rollback` 成功/失败两条文案与行为对齐（小账 c） |
| `_dev/silent_except_whitelist.py` | 新增 `evidence_in_source()` 判据并接进 `check()`（小账 d） |
| `tests/test_plugin_market_v270.py` | **新建**，9 条用例（a×2 / b×4 / c×2 / d×1） |
| `_dev/mutations_plugin_c_v270.json` | **新建**，7 条变异 spec |
| `_dev/mutate_batch_v270.py` | **新建**，铁律 5 的可执行形态（整批复跑 + 指纹前后对照 + `--scan-only` 锚点体检） |
| `_dev/probe_c_mutation_output_v270.py` | **新建**，a~d 的变异**原文**证据收集器 |
| `_dev/mutations_plugin_market_v260.json` | 重锚 M-A09 / M-A16（`install_zip` 重构导致漂移），并清掉作废的 `results` 段 |
| `_dev/mutations_plugin_v251.json` | 重锚 M-H3（同上） |
| `_dev/README.md` | 铁律 5 补「一条命令跑完整批」+ 工具表两行 + 本轮复跑记录（标注中间态） |
| 其余 19 份 `_dev/*.json` | 只被复跑**回写 results / 指纹**，判据与锚点一字未改 |

---

## 2 小账 a~d（逐条：现状 → 修法 → 用例 → 变异原文证据）

### 通用：证据怎么产生的

```
python -B _dev/mutate_check.py _dev/mutations_plugin_c_v270.json     # 判定（7/7 CAUGHT）
python -B _dev/probe_c_mutation_output_v270.py                      # 原文证据（改了什么/红在哪条断言/还原后是否绿）
```

变异全在 `%TEMP%` 影子副本里做（`_dev/_mutate_lib.shadow`），真仓只读、只留 `_dev/.mutation.lock/`。
下面每条都贴**实际输出原文**，不是「已 CAUGHT」四个字。

### a · `install_file` 不核索引与包的 `data_kind`

**现状**：`install_file` 只核 `id`（`:597`）。索引写 `data_kind=lines`、包里装的是 role 时，
市场页按索引显示「台词包」，落地却把一只角色塞进角色库 —— 界面与实际内容对不上，用户零线索。

**修法**（`pet_plugin_index.py:install_file`）：

```python
want_kind = str(entry.get("data_kind") or "")
got_kind = str(meta.get("data_kind") or "")
if want_kind and got_kind and want_kind != got_kind:
    return False, ("索引条目「%s」标的是「%s」类插件，包里的 manifest 却自报"
                   "「%s」类——界面会按索引显示成一种、实际落地成另一种，"
                   "已拒绝安装（索引与包不是同一件东西，宁可不装）" % (want, want_kind, got_kind))
```

**用例**：`test_a_索引与包的data_kind不一致必须拒绝`（负向：拒绝 + 库不变 + 无插件目录 + 无登记）
+ `test_a_索引与包的data_kind一致照常安装`（正向对照：不许把正常包也拦掉）。

**变异原文**（M-C-a1：`if want_kind and got_kind and want_kind != got_kind:` → `if False:`）：

```
    变异前|             if want_kind and got_kind and want_kind != got_kind:
    变异后|             if False:  # MUT: 不核索引与包的类别（小账 a 的修复被拿掉）
  锚点命中次数：1（要求恰好 1）
  变异后：rc=1  失败用例=['test_a_索引与包的data_kind不一致必须拒绝']
      >       assert ok is False, msg
      E       AssertionError: 已安装插件「小账包 upd」，并导入 1 条台词。可在插件管理里卸载（已导入的内容会保留）。
      E       assert True is False
      FAILED tests/test_plugin_market_v270.py::test_a_索引与包的data_kind不一致必须拒绝
  还原后：rc=0  失败用例=(无)  → 绿
```

### b · `history` 白丢一个回滚点、留孤儿 `.prev-<id>`

**现状**：`install_zip` 里 `history[-1]` 与 `.prev-<id>/` 本该成对（轮换 target → .prev 时配对），
但「当前版目录**不在**」时走的是 else 分支：
`"history": ([prev_record] if (already and moved_prev and prev_record) else (list(known.get("history")) if repeat else []))`
→ `moved_prev=False` 且 `repeat=False` 时 history 被清成 `[]`（**回滚点白丢、回滚按钮变灰**），
而 `.prev-<id>/` 原样留在盘上成**孤儿**（没人能回滚它、也没人清它）。

**修法**（`pet_plugin_host.py:install_zip`）——`history` 与 `.prev` **强制成对**：

| 状态 | 新口径 |
|---|---|
| 目录不在而 `.prev` 在 | `.prev` 正是 `history[-1]` 记的那一版 payload，配对关系还成立 → **既不轮换也不清**（回滚点保住） |
| 两边都不在 | `history` 一并清掉（不留指向空气的回滚点） |
| 登记里没这条却留 `.prev` | 无主孤儿 → 一并清掉 |
| （连带）登记写失败 | 与 S1-b 提交失败分支同口径：`.prev` **挪回** `plugins/<id>/`（此前只撤新目录，会留下「登记说装着上一版、目录却不在、payload 躺在 .prev」的错位状态 —— 这正是孤儿备份的制造者） |

**用例**（4 条，覆盖三种状态 + 一个连带）：
`test_b_当前版目录不在而备份在_回滚点不丢也不留孤儿` · `test_b_没有备份就不许留悬空回滚点` ·
`test_b_登记里没有这条却留着备份_一并清掉` · `test_b_登记写失败时上一版目录要挪回去`。

**变异原文**（4 条，逐条贴失败断言）：

```
[M-C-b1] 变异前| elif already and not target_is_dir: / keep_history = prev_is_dir
         变异后| keep_history = False  # MUT: history 白丢 + .prev 成孤儿
  变异后：rc=1  失败用例=['test_b_当前版目录不在而备份在_回滚点不丢也不留孤儿']
      E       AssertionError: 回滚点白丢了：history 被清空，而备份还躺在盘上
      E       assert []

[M-C-b2] 变异前| keep_history = prev_is_dir   # .prev 不在 → 悬空回滚点一并清掉
         变异后| keep_history = True  # MUT: 留一个盘上不存在的回滚点
  变异后：rc=1  失败用例=['test_b_没有备份就不许留悬空回滚点']
      E       AssertionError: 没有可恢复的 payload 却留着回滚记录：[{'id': 'upd', 'version': '1.0.0', ...}]
      E       assert [{'id': 'upd'...}] == []

[M-C-b3] 变异前| if not already and prev_is_dir: / shutil.rmtree(previous, ignore_errors=True)
         变异后| if False:  # MUT: 孤儿 .prev 不清 / pass
  变异后：rc=1  失败用例=['test_b_登记里没有这条却留着备份_一并清掉']
      E       AssertionError: 没有任何登记记录能跟它配对，备份却留在盘上（孤儿）
      E        +  where True = exists() ... /plugins/.prev-upd).exists

[M-C-b4] 变异前| if moved_prev:（登记写失败分支）
         变异后| if False:  # MUT: 登记写失败时不回挪上一版目录
  变异后：rc=1  失败用例=['test_b_登记写失败时上一版目录要挪回去']
      E       AssertionError: 上一版目录没挪回去（插件目录整个不见了）
      E        +  where False = is_dir()
```

每条**还原后 rc=0（全绿）**。

### c · 同内容折叠时回滚文案说「撤销了 0 项」

**现状**：`rollback` 成功文案无条件写 `撤销了本版新导入的 %d 项内容`。同内容折叠（这一版内容与
上一版完全一致、按指纹一条都没重复落）时差集为空 → 用户读到自相矛盾的「**撤销了 0 项**」。

**修法**（`pet_plugin_host.rollback`）：`count` 为 0 时改说
「这一版没有新导入的内容（与上一版一致），没有条目需要撤销」；失败分支同样不再写「已撤销 … 0 项」。

**用例**：`test_c_同内容折叠回滚不说撤销了0项`（+ 文案断言仍要真的回滚目录与登记）
与 `test_c_有内容可撤时文案照旧`（契约的另一半：`count>0` 时仍要说清「撤销了 N 项」）。

**变异原文**（M-C-c1）：

```
    变异前| done = ("撤销了本版新导入的 %d 项内容" % count if count
    变异前|         else "这一版没有新导入的内容（与上一版一致），没有条目需要撤销")
    变异后| done = ("撤销了本版新导入的 %d 项内容" % count)  # MUT: 0 项也照念撤销
  变异后：rc=1  失败用例=['test_c_同内容折叠回滚不说撤销了0项']
      E       AssertionError: 回滚文案说了一句自相矛盾的「撤销了 0 项」：
      E         '已把插件「upd」回滚到上一版 1.0.0：撤销了本版新导入的 0 项内容（你自己的角色 / 台词 / 音效一件没动）'
```

### d · razor 只校验理由填没填、不校验证据原文

**现状**：`_dev/silent_except_whitelist.py:check()` 对 `evidence` 只判**非空** ——
抄一句别处的话、或代码改过之后没重跑 `--write`，白名单照样绿。

**修法**：新增 `evidence_in_source(rec, root)` 并接进 `check()` 的判定链：
两边空白都归一化（与 `_flatten` 同口径）、剥掉 `_flatten` 截断留下的尾部 `...`，
再判「这段原文是不是真的在这个文件里」。三态：`ok` / `missing`（报问题）/ `unknown`
（文件不存在或读不动 → **不误报**，合成树用例不受影响）。

**取舍（任务书允许退成提示级）**：实测现有 **307 条证据全部逐条命中、零假红**，
所以做成**硬判据**（不是提示级）—— 残留项直接消掉。CLI 复核：

```
$ python -B _dev/silent_except_whitelist.py --check
扫描：生产路径静默 except 条目 307 个（领地内 307 / 领地外 0）；A 档 0 条
判定通过：每个静默 except 都有归属（白名单条目 307）
```

**用例**：`test_d_razor会核对证据原文能不能找到` —— 正向（整份白名单零假红）+ 负向（把一条真条目的
evidence 换成抄来的一句话 → 必须被点名）+ 不误报（不存在的文件 → `unknown`）。

**变异原文**（M-C-d1：`if verdict == "missing":` → `if False:`）：

```
  变异后：rc=1  失败用例=['test_d_razor会核对证据原文能不能找到']
      >       assert any("源码证据对不上" in p for p in probs), probs
      E       AssertionError: []
      E       assert False
```

---

## 3 铁律 5：整批复跑

### 3.1 出发点（先纠正一个错判）

任务书原话是「现存提示级：`results_fastci_slices_v251.json` 与 `results_guardrails_can_fail.json` 指纹过期、
前者缺 `pet_plugin_index.py` 键」。实测**不止**：`_check_release.mutation_evidence_notes()` 一次报出
**20 份证据全部指纹过期**，全是 `桌宠.py: 99e2abf3e7fb → 8e3827252517` —— v2.6.1 的 anim_mode 修复
改了 `桌宠.py`，于是 v2.6.0 那批复跑留下的证据在定版那一刻就**全部**失效。
所以本轮做的是**整批复跑**，不是补两份。

### 3.2 覆盖面（22 项，一份不落）

```
python -B _dev/mutate_batch_v270.py            # 整批（约 28 分钟）
python -B _dev/mutate_batch_v270.py --scan-only # 只做锚点体检（秒级）
```

| 类 | 项 | 结果 |
|---|---|---|
| 带 `mutations` 段的 spec（`mutate_check.py` 驱动） | 17 份 / **190 条**变异（= 此前 183 条 + 本轮新增 7 条；收尾又加 `mutations_critic_v270.json` 13 条 → 现树 **18 份 / 203 条**） | 全部 rc=0，**全 CAUGHT** |
| 三份旧形态单脚本驱动 | `mutate_export_slice.py` 5/5 · `mutate_startup_defer.py` 8/8 · `mutate_proc_reset_v26.py` 12/12(+BASELINE PASS) | 全部 rc=0 |
| 两份独立结果 | `verify_fastci_slices_v251.py`（11 组实验，0 组与预期不符）· `verify_guardrails_can_fail.py`（9/9） | 全部 rc=0 |

### 3.3 发现并修好的断裂锚点

跑前先做 `--scan-only` 体检（215 条锚点）：**坏 3 条**，全部是本轮 `install_zip` 重构造成的漂移 ——
`mutations_plugin_market_v260.json` 的 M-A09 / M-A16、`mutations_plugin_v251.json` 的 M-H3。
重锚后 **215 条全部命中恰好 1 次**。

**我自己在重锚上犯过一个错（记下来）**：M-H3 重锚时把 `old` 收到只剩 return 行，
却没有同步改 `new` —— 结果变异变成「多插一行 rmtree」的空转，**被整批复跑当场记成 NOT CAUGHT**。
修正（`old` = `self._unland(...)` + return 两行，`new` = 只剩 return 行）后单独复跑 → **CAUGHT**。
教训：**重锚要连 `new` 一起复核**，否则「变异还在跑」但守的东西已经没了。

另：`mutations_compat_v243.json` 首轮 **rc=2**（影子基线偶发红 → 按设计不产出判定、`results` 段还是 10-12 的旧值），
单独复跑后基线 15 条全过、**13/13 CAUGHT**。两件事都写进了 `results_batch_v270.json` 的 `rerun_after_batch`。

### 3.4 最终判定（跑完两条复跑后重新普查）

```
总条目 268 不合格 0
--- mutation_verdict_notes()（判定不通过）--- 条数 0
--- mutation_evidence_notes()（指纹过期 / 缺键）--- 条数 15（**全是并行窗口的指纹漂移**，见下）
```

- **SPEC-BAD 0 · ANCHOR-LOST 0 · WRONG TEST 0 · NOT CAUGHT 0 · INVALID 0 · BASELINE-RED 0**。
- `results_fastci_slices_v251.json` 的**缺 `pet_plugin_index.py` 键**已随复跑补齐（缺键汇总提示消失）。
- `results_fastci_slices_v251.json` 与 `results_guardrails_can_fail.json` 的**指纹已对齐当前树**。
- 剩下 15 条「指纹过期」**不是判定问题**：批次跑的 28 分钟里 A、B 正在改 `桌宠.py` / `pet_dialogs.py`，
  `fingerprint_before != fingerprint_after`（漂移文件：`pet_dialogs.py`、`桌宠.py`），跑完后这两个文件又变了。

### 3.5 ⚠ 这一批**不作发布依据**

`_dev/results_batch_v270.json` 里已写入 `state` / `warning` 两个字段，明确标注：
**并行窗口中间态**；用途只有两个 —— 找出断裂锚点、证明当前源码上每条变异都能抓住。
**定版必须在安静窗口用同一条命令再跑一次**（A、B 停笔后），那次才会把 15 条指纹提示一并消掉。

---

## 4 三项护栏（本轮实测，含 A/B 在途改动）

| 护栏 | 命令 | 结果 |
|---|---|---|
| pytest | `python -B -m pytest tests -o addopts="" -q` | **1143 passed**, 0 failed, 12 warnings, 156.09s |
| v13 | `python -B _verify_v13.py` | **TOTAL CHECKS: 273, FAILS: 0** → `V13 VERIFY ALL OK` |
| 静态 | `python -B _check_static.py` | **问题 0 条，待确认 0 条** |

（基线 1061；1143 = 1061 + 三路本轮新增的用例，含代理 C 的 9 条。）

---

## 5 没做到 / 有疑问（如实）

1. **这一批证据不是发布依据**（上面 §3.5）。指纹会在 A/B 再动一下 `桌宠.py` / `pet_dialogs.py` 后立刻过期 ——
   这是机理，不是我没跑完。定版重跑的成本约 **28 分钟**（一条命令）。
2. **b 的连带修复（S1-a 登记写失败时回挪 `.prev`）超出了任务书 b 的字面范围**：
   它属于「同一个状态家族的另一个制造者」，我按 S1-b 同口径修了并补了用例（M-C-b4 守着）。
   如果判定为越界，回退点很干净：删 `install_zip` 登记失败分支里那个 `if moved_prev:` 块 +
   删 `test_b_登记写失败时上一版目录要挪回去` 一条用例，b 的主修不受影响。
3. **c 的「首次安装不要说撤销」我按「差集为空（`count==0`）时不说撤销了 0 项」理解并实现** ——
   若原意另有所指（例如安装路径的某句文案），请指出，我再改；当前实现覆盖了 `rollback` 的成功与失败两条文案。
4. **`tests/test_plugin_market_v270.py` 不在任务书给代理 C 写死的领地清单里**（那份只列了
   `pet_plugin_host.py` / `pet_plugin_index.py` / `_dev/**`），但 a~d 都要求「用例 + 变异」，
   且新建独立文件不会与 A、B 的 `tests/test_*.py` 冲突。若规则上不允许，请告知，我把用例并回既有文件。
5. **`_dev/README.md` 在我读之后被别的进程写过一次**（edit 报 `file changed since it was read`），
   我重读后按新内容改的；如果同一处还有人在改，注意别互相覆盖。
6. **`--scan-only` 只查锚点命中次数**，不查「锚点位置是否还是它守的那件事」—— 后者只能靠人看
   （M-D09 那种「锚点还在、守的东西早换了」的坑它发现不了）。
7. 没有提交（任务书要求统一提交）；VERSION / version_info / CHANGELOG / 绿色版 / 发布 zip 一字未动。
