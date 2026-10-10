# A 档静默 except 判定清单（v2.4.2 · B 区第二轮收紧）

> 工具：`_dev/audit_silent_except.py` · 配套回归：`tests/test_silent_except_audit_v241.py`（12 例，含 3 组变异验证）
> 本文替代上一版同名文件。上一版把 19 条判成"真 1 · 误报 15 · 良性 3"，**与它自己的 19 行明细对不上**；
> 本轮按明细重算，并把三条残留误报从**判据**里真正摘掉（不是改结论）。

## 0. 一句话结论

- 原判 **A=19** → 第一轮收紧（①②③）后 **A=4** → **本轮再收紧一轮后 A=1**。
- 19 条逐条判定：**真 2**（1 条已修 + 1 条低危保留）· **误报 17** · 良性 0。
- 本轮**没有为变绿放宽任何判据**：三条新判据全是"证据式"，每条都配**双向**合成反例
  （该降的降了 / 真吞掉的照样报 A），并做了"关掉判据 → 反例重新变 A"的变异验证。
- 漏报面自查（§5）：**没有第 5、6 条被漏报的真吞异常**。复核面 = 83 条"含写盘/网络/进程却被
  降档"的条目逐桶过一遍 + 2 条 A4 防御性读取豁免。

## 1. 本轮收紧了什么（④⑤⑥）

| # | 新判据 | 实现 | 为什么这不是"被吞"（依据） | 命中原条目 |
|---|---|---|---|---|
| ④ | 纯轮转 | `_is_backup_rename` + `_is_pure_rotation` | 改名是**原子**的：`os.replace(X, X + "后缀")` 失败时文件仍在**原名**下，成功也只是换个名字——既不丢数据，也不会让用户"以为成功"。判据要求 AST **逐字比对**目的名 = "源名 + 非空字符串常量后缀"，且 try 体内除只读判断（getsize/exists…）外**不能有任何其它调用**（认不出的调用直接不放行）。 | pet_main.py:31 |
| ⑤ | 信号 0 探针 | `_is_signal0_probe` | `os.kill(pid, 0)` 不投递任何信号，是"进程还在不在"的探测；探针失败＝进程不在了，对 `is_running` 这类函数 `False` **正是安全答案**。要求信号实参是字面量 `0`。 | pet_voice.py:726 |
| ⑥ | 回滚里的回滚 | `_nested_handler_map` + `_rollback_in_reporting_handler` | handler 嵌在一个**已经上报错误**的 handler 内部（沿外层 handler 链必须真的看到 `_ends_with_report`＝以 `return 非零值 / raise` 结尾），**且**它自己的 try 体是 `_is_pure_cleanup`（只删残留）。用户已经看到失败提示 → 内层清理失败不会让他以为成功。只降 A→B，报告里仍留着这条。 | pet_export.py:679 |

反向保护（写进了 `tests/test_silent_except_audit_v241.py`，不是口头承诺）：

- ④ 有一条反例："**提交式改名** `os.replace(tmp, final)`（目的名不是源名+后缀）失败被吞" → 必须仍是 A1；
  还有一条："轮转旁边还有一次真写盘（`open(...,"w")`）" → 必须仍是 A1。
- ⑤ 有一条反例："`os.kill(pid, 9)` 真发信号" → 必须仍是 A3。
- ⑥ 有两条反例："外层**不上报**（handler 只 pass）" → 内层静默必须仍被报出来；
  "内层是**独立写盘**（`os.makedirs`）" → 即使外层上报也必须留在 A。
- 变异验证：把 ④⑤⑥ 分别关掉，三条合成反例必须**重新回到 A 档**（否则用例是空转的）。

## 2. 19 条逐条判定

行号口径：**2026-10-10 21:20:03 那一次扫描**（当次共 50 个 .py、550 个 handler）。
见 §7 的"行号会漂"说明——定位请用"文件 + 函数 + 片段"三件套。

| # | 原条目（审计当时） | 当前锚点（文件:行 · 函数 · 片段） | 当前档 | 判定 | 依据 |
|---|---|---|---|---|---|
| 1 | pet_book.py:693 | pet_book.py:689 · `Book.export_csv` · `return False, str(e)` | B | 误报 | 早前已改走 `pet_io.atomic_write_bytes(log=pet_log.log_error)`，handler 把失败 return 给调用方（界面当场弹"导出失败"）。**领地外，只判定** |
| 2 | pet_config.py:291 | pet_config.py:291 · `write_config` · 读旧配置失败分支 | **OK** | **真 · 已修** | 加密失败后要读磁盘旧值保住密文；读失败时曾 `out["api_key"] = ""` → 用户的 Key 被**静默清空**。已补 `log(...)`；脚本现在直接判 OK |
| 3 | pet_export.py:256 | pet_export.py:355 · **`BundleWriter.finish`**（原 `export_bundle`；v2.4.2 导出处拆成 `plan_bundle` + `BundleWriter`） · `return False, "写入失败：%s" % e` | B | 误报 | 关包/原子替换失败都 `return (False, "写入失败：…")`，界面弹提示。**领地外，只判定** |
| 4 | pet_export.py:378 | pet_export.py:498 · `import_bundle` · `_local_keys = {}  # 有意忽略：拿不到就当作没有本地密钥` | B | 误报 | try 体只做 `(cfg or {}).get("voice")` 取字段 + `dict(...)`；失败＝"没有本地密钥"，不改变导入结果 |
| 5 | pet_export.py:454 | pet_export.py:574 · `import_bundle` · `_ver = BUNDLE_VERSION` | B | 误报 | `int(manifest.get("version") or BUNDLE_VERSION)` 的常量兜底；最坏是少弹一句"包版本高于当前支持" |
| 6 | pet_export.py:550 | pet_export.py:**673** · `import_bundle`（**外层** handler） · `return None, "导入失败：%s" % e` | B | 误报 | handler 以 `return None, "导入失败：…"` 结尾 → 已上报调用方 |
| 7 | pet_export.py:556 | pet_export.py:**679** · `import_bundle`（回滚） · `role_lib._data["roles"].remove(role)` + `_save()` | B | **误报 → 本轮收紧⑥** | 处在"外层已 `return` 导入失败"的 handler 内部，且 try 体是只删残留的清理；最坏后果＝留一个空角色条目（注释就写在 680-682 行） |
| 8 | pet_io.py:270 | pet_io.py:279 · `atomic_write_bytes` · 重试循环 `except PermissionError` | B | 误报 | 重试耗尽后 `raise last`（284）→ 外层 `_log(...)` + `return str(e)`（287-288）。**领地外，只判定** |
| 9 | pet_main.py:31 | pet_main.py:31 · `check_memory` · `os.replace(path, path + ".old")` | **C** | **误报 → 本轮收紧④** | 512KB 轮转失败＝文件没改名，数据仍在原名下：既不是数据丢失也不是用户可见错误。上一版把它记成"良性"却仍留在 A 里（那就是统计与明细打架的地方），本轮按"脚本判错"改正为误报并降档 |
| 10 | pet_resources.py:886 | pet_resources.py:868 · `RoleLibrary.import_file` · `return None, "复制文件失败"` | B | 误报 | except 里只删半截文件，紧接着把失败 return 给导入向导 |
| 11 | pet_resources.py:1014 | pet_resources.py:1000 · `RoleLibrary.import_processed` · `_cleanup_files(...)` + `return None, "复制文件失败"` | B | 误报 | 回滚 + 上报 |
| 12 | pet_resources.py:1060 | pet_resources.py:1048 · `RoleLibrary`（状态图） · `return None, "复制状态图失败"` | B | 误报 | 同上 |
| 13 | pet_resources.py:1124 | pet_resources.py:**1114** · `RoleLibrary`（keep_source 保留原图） · `os.makedirs(sdir, exist_ok=True)` + `shutil.copyfile(sf, target)` | **A** | **真（低危）· 本轮保留** | 用户开了"保留原图"却在界面上看不出失败；脚本的 A 判据（静默 + 写盘）**成立**。本轮**不**收紧，理由见 §4 |
| 14 | pet_resources.py:1398 | pet_resources.py:1388 · `AudioLibrary.import_fragment` · `return None, "复制文件失败"` | B | 误报 | 回滚 + 上报 |
| 15 | pet_resources.py:1637 | pet_resources.py:1629 · `VoiceAssetLibrary.import_file` · `return None, "复制文件失败"` | B | 误报 | 同上 |
| 16 | pet_voice.py:711 | pet_voice.py:726 · `VoiceLauncher.is_running` · `os.kill(pid, 0)` 兜底 | B | **误报 → 本轮收紧⑤** | 进程存活探针；内层取不到 `create_time` 时也 `return False`。对探针而言 `False` 是**安全答案** |
| 17 | pet_voice.py:819 | pet_voice.py:834 · `VoiceLauncher.wait_ready` · handler 只写 `last` | B | 误报 | 三个 handler 属于**同一个 try**（第一轮收紧①），循环后 `return False, "…（等了 N 秒…）"` 已上报。**领地外，只判定** |
| 18 | pet_voice.py:821 | pet_voice.py:836 · 同上 | B | 误报 | 同上 |
| 19 | pet_voice.py:823 | pet_voice.py:838 · 同上 | B | 误报 | 同上 |

**统计（照上表 19 行逐条数，别照抄旧结论）：真 2 · 误报 17 · 良性 0（合计 19）。**

- `真` = 第 2 行（pet_config 静默清 Key，**已修**，脚本现在判 OK、已不在 A 里）+ 第 13 行（保留原图静默失败，**仍为 A**）。
- `误报` = 其余 17 行。其中 14 行在第一轮（①②③）已降档；剩下 **3 行（第 7 / 9 / 16 行）由本轮 ⑥ / ④ / ⑤ 降档**。
- 上一版把第 9、13 行都记成"良性"还同时宣称 A=4 —— 那正是被抓到的矛盾点：第 9 行其实该按
  "脚本判错"降档（本轮已做），第 13 行其实该按"真问题（低危）"计。

**19 → 4 → 1 的桥（逐阶段可对账）：**

| 阶段 | A | 组成（按上表行号） |
|---|---|---|
| 审计当时 | 19 | 第 1-19 行 |
| 第一轮收紧 ①②③ 后 | 4 | 第 **7、9、13、16** 行（其余 15 行降档；第 2 行修复后转 OK） |
| 本轮收紧 ④⑤⑥ 后 | **1** | 第 **13** 行 |

## 3. A=4 → A=1 的实测 diff（本轮）

下表是"把 ④⑤⑥ 分别关掉后重新扫描"与当前扫描的**逐条差分**——除这三行外，其余条目档位一字未变。

| 位置 | 函数 | 收紧前 | 收紧后 | 触发判据 |
|---|---|---|---|---|
| pet_export.py:679 | `import_bundle` | A（A4 用户动作(import_bundle)失败无提示） | B（回滚里的回滚：删残留的清理，嵌在已上报错误的 handler 内部） | ⑥ |
| pet_main.py:31 | `check_memory` | A（A1 写盘被吞: os.replace()@30） | C（良性：仅把已有文件轮转到它自己的备份名） | ④ |
| pet_voice.py:726 | `VoiceLauncher` | A（A3 后端启停被吞: os.kill()@728） | B（功能性吞咽（可恢复，无写盘/网络）） | ⑤ |

收紧后生产路径三档：**A=1（"数据丢失/用户可见错误被吞"）、B=211（功能性吞咽）、C=126（良性）、OK=111（已处理）**。

## 4. 为什么最后一条（pet_resources.py:1114）留着不收紧

④⑤⑥ 都是"证据式"的，而这一条**不满足任何一种能被安全写成证据的形态**：

- 它不是轮转（是 `copyfile` 新建副本，不是改名）；
- 不是探针；也不在任何"已上报"的 handler 内部（它在 `import_processed` 的**成功路径**上，
  外层 handler 是 `return None, "导入失败：%s" % e`，跟这个内层 try 不是父子）；
- 唯一能摘掉它的候选判据是"**try 体只新建、不覆盖/不删除 → 不算数据丢失**"。这条**不能要**：
  同形态的 `shutil.copyfile(user_file, backup_path)` 静默失败就是"用户以为有备份、其实没有"，
  正是 A 档要抓的东西；判据一放宽，这一类会**整批漏检**。

所以保留 `A=1`，并明确记下人工结论：**真问题、低危、接受现状**。
最坏后果 = 用户勾了"保留原图"，但 `roles/<id>/source/` 里没有原图（导入本身成功、角色可用）。
要彻底消掉它，正确做法是**改代码**（补一句 `pet_log.log_error` 或把它塞进导入完成后的
`warnings`），**不是放宽判据**。用户在 v2.4.1 已经就同类改动下过"不为回滚/可选路径引 pet_log，
收益不抵改动面"的结论，本轮尊重该结论，不动 pet_resources 的代码。

## 5. 漏报面自查：有没有第 5、6 条被漏报的真吞异常？

方法：A 档的判据是"handler 静默 **且** try 体有写盘/网络/进程"。所以漏报只可能藏在
"**当前不是 A、但 try 体经 `_classify_try_body` 判定确有写盘/网络/进程**"的条目里。
把这类条目全部列出来逐桶复核（当次共 **83 条**）：

| 降档依据 | 条数 | 复核结论 |
|---|---|---|
| 已上报（handler `return` 哨兵/错误文案） | 43 | 逐条看过：handler 都把失败转成返回值或错误文案。静态看不到调用方是否检查——脚本**有意**留在 B（这是写在文件头的已知口径，不是漏报） |
| 仅删残留的清理（`_is_pure_cleanup`） | 30 | 逐条看过（pet_dialogs 6、pet_resources 10、pet_voice 6、pet_export 4、桌宠 2、pet_main 2；合计 30）：全是 `os.remove`/`rmtree` 一类；其中 pet_resources 1161/1430/1682 还把失败 `return False, "删除文件失败：%s"` 上报。**没有一条是真丢数据** |
| 重试/轮询循环（第一轮 ②） | 4 | pet_io:279、pet_voice:834/836/838 —— 循环后统一 `raise`/`return`，已核 |
| 日志设施自身（`EXEMPT_FILES`） | 3 | pet_log 的"写日志失败"无处可记，代码内已有 stderr 兜底 |
| 写权限探针（`EXEMPT_FN_RE`） | 2 | `桌宠._data_dir` —— 失败＝目录不可写，是**回退信号**，不是错误 |
| 纯轮转（本轮 ④） | 1 | pet_main:31 —— 见 §2 第 9 行 |

另查 A4 的"防御性读取"豁免面：只有 **2 条**（pet_export.py:498 / 574），都是"取字段 + 常量兜底"。

**结论：没有找到第 5、6 条被漏报的真吞异常。A=1 就是当前的真实余额。**

## 6. 本轮实际改了什么

| 文件 | 改动 |
|---|---|
| `_dev/audit_silent_except.py` | ① 新增三条判据 ④⑤⑥（`_is_backup_rename` / `_is_pure_rotation` / `_is_signal0_probe` / `_nested_handler_map` / `_rollback_in_reporting_handler`）并接进 `scan()` 的档位链；② 头部口径注释补 ④⑤⑥ 的"为什么"；③ 顺手修两处**口径缺陷**：**(a)** 带 UTF-8 BOM 的 `.py` 此前被**整份 SKIP**（`ast.parse` 见到残留 `\ufeff` 直接 SyntaxError）→ 改用 `utf-8-sig` 读，BOM 文件现在正常扫描（当时 `_dev/_dbg_*.py` 3 个立刻从 SKIP 变回可分析）；**(b)** `SKIP` 条目的 `nonprod` 恒 `False` → `tests/_dev` 下的坏文件被算成"生产路径"，把三档统计的分母污染 → 现在按路径归属 |
| `tests/test_silent_except_audit_v241.py` | 6 例 → **12 例**：④⑤⑥ 各 1 例（每条都带**双向**反例）+ 1 例变异验证（关掉判据后合成反例必须重新变 A）+ BOM 扫描 / 归属统计 2 例 |
| `pet_resources.py` / `pet_export.py` / `pet_voice.py` / `pet_main.py` | **未改任何一行代码。** 本轮是判据侧收紧；第 13 行的取舍见 §4 |

## 7. 怎么复跑 / 口径与限制

    python _dev/audit_silent_except.py                                          # 完整三档报告（当前 A=1）
    python _dev/audit_silent_except.py --tier A                                 # 只看 A
    python -m pytest tests/test_silent_except_audit_v241.py -o addopts="" -q     # 判据自身的回归（12 例）

- **行号是快照值**：本文所有行号取自 2026-10-10 21:20:03 的那一次扫描。当时 `pet_export.py`
  正被**另一个代理**做 v2.4.2 导出重构（`export_bundle` 拆成 `plan_bundle` + `BundleWriter`），
  同一文件的行号在两次扫描之间已经漂了 ±1~2 行 —— 所以定位请用
  **"文件 + 函数 + 代码片段"三件套**，别只认行号。
- 统计口径：A/B/C/OK 只统计**生产路径**（`tests/` 与 `_dev/` 不计入 A 档，见脚本头部说明）；
  全量（含非生产）另计 `N`（测试/_dev 的静默 except）与 `SKIP`（解析失败）。
- 已知限制（有意为之，不是 bug）：handler 把失败 `return` 成哨兵值时，**静态看不到调用方是否检查**——
  这类一律留 B 档（43 条），既不肯降成 C，也不肯升成 A。
- 注释"有意忽略"**不**降级：注释不是证据（`annotated` 只作为人工复核的一列）。
