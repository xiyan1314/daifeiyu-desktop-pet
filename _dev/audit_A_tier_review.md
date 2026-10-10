# A 档静默 except 判定清单（v2.4.1 · B 区）

> 工具：`_dev/audit_silent_except.py`（收紧判据后）· 配套回归：`tests/test_silent_except_audit_v241.py`（判据本身可失败）
> 本文替代上一轮的 `_dev/_auditA.txt`（原始扫描输出，已删）

## 0. 一句话结论

原判 **A=19** 里，**真问题只有 1 处**（`pet_config.py` 写配置时读旧值失败 → API Key 被静默写空），**已修**；
其余 18 处是**误报**（重试循环、已有上报通道、注释明说有意忽略的清理）。收紧判据后 A 降为 **4**，
这 4 条也已逐条判定。**没有为变绿而放宽任何判据**——收紧是"认得出证据才降档"，认不出证据就保持原判。

## 1. 审计口径：这轮收紧了什么

收紧前 A=19，其中约半数是误报——问题出在**判据把"重试 / 上报 / 清理"也算成了"吞掉"**。
`_dev/audit_silent_except.py` 加了四条**证据式**收紧（认不出证据就保持原判，不悄悄放宽）：

| # | 收紧 | 依据 | 命中原条目 |
|---|---|---|---|
| ① | 同一 try 的多个 handler 只计一条 A | `pet_voice.wait_ready` 的 3 个 except 曾算 3 条 | pet_voice 819/821/823 |
| ② | handler 只把异常存进变量、其后 return/raise/记日志 | `pet_io.atomic_write_bytes` 的重试循环（末尾 `raise last`） | pet_io 270 |
| ③ | handler 先清理残留、最后 `return None/False, "…失败"` | pet_resources 6 处复制失败、pet_export 打包失败 | pet_resources 886/1014/1060/1124/1398/1637、pet_export 256/550 |
| ④ | try 体只做取字段/类型转换（常量兜底）不算"用户动作失败无提示" | `pet_export.import_bundle` 的两处防御性读取 | pet_export 378/454 |

附带修一处**真缺陷**：`annotated`（"已注释"列）此前用 ast 源码片段判断，而片段在最后一条语句
结束处截断，于是 `pass  # 有意忽略：…` 这种**同行尾注释**一律漏判。现在按行号取整段。

收紧后：**A=4**（518 个生产路径 handler）。

## 2. 19 条逐条判定（行号以**当前文件**为准）

| # | 原条目（审计当时） | 当前行 | 函数 | 判定 | 依据 |
|---|---|---|---|---|---|
| 1 | pet_book.py:693 | pet_book.py:682 | Book.export_csv | **误报（旧实现已消失）** | 早前 A 区收口已把"自建 tmp + os.replace"换成 `pet_io.atomic_write_bytes(log=pet_log.log_error)`，且 handler `return False, str(e)` 上报调用方。**领地外，只判定** |
| 2 | pet_config.py:291 | pet_config.py:291 | write_config | **真问题 → 已修** | 加密失败后要读磁盘旧值保住密文；读失败时 `out["api_key"] = ""` → 用户的 Key 被**静默清空**。已补 `log("read old config for api_key failed, api_key cleared: %r")` |
| 3 | pet_export.py:256 | pet_export.py:256 | export_bundle | 误报 | handler `return False, "写入失败：%s" % e`（界面弹"导出失败"）；tmp 清理尽力而为且已有注释 |
| 4 | pet_export.py:378 | pet_export.py:378 | import_bundle | 误报 | 同 try 只做 `(cfg or {}).get("voice")` 取字段，失败就当"没有本地密钥"；注释已写明 |
| 5 | pet_export.py:454 | pet_export.py:452 | import_bundle | 误报 | `int(manifest["version"])` 的常量兜底；最坏是少弹一句"包版本高于当前支持"，不丢数据。**本轮补注释** |
| 6 | pet_export.py:550 | pet_export.py:550 | import_bundle | 误报 | 外层 handler `return None, "导入失败：%s" % e` + 尽力回滚，已有注释 |
| 7 | pet_export.py:556 | pet_export.py:556 | import_bundle | 误报（有意保留） | 只是"回滚时把已入索引的角色删掉"的尽力而为；最坏=下次启动看到一个没有素材的空角色。要给 pet_export 引 pet_log，收益不抵改动面 |
| 8 | pet_io.py:270 | pet_io.py:275-288 | atomic_write_bytes | 误报 | 重试**耗尽**后 `raise last` → 外层 `_log(log, "pet_io 写盘失败 …")` + `return str(e)`。**领地外，只判定** |
| 9 | pet_main.py:31 | pet_main.py:31 | check_memory | 良性（已注释） | 512KB 轮转失败 → 日志继续追加变大，不丢数据、不影响功能；注释写明"体积检查失败直接追加" |
| 10 | pet_resources.py:886 | pet_resources.py:868 | RoleLibrary 导入单图 | 误报 | `return None, "复制文件失败"` 上报调用方；except 里只删半截文件。**本轮补注释** |
| 11 | pet_resources.py:1014 | pet_resources.py:996 | RoleLibrary.import_processed | 误报 | `_cleanup_files(...)` 回滚 + `return None, "复制文件失败"`。**本轮补注释** |
| 12 | pet_resources.py:1060 | pet_resources.py:1048 | RoleLibrary（状态图） | 误报 | 同上 + `return None, "复制状态图失败"`。**本轮补注释** |
| 13 | pet_resources.py:1124 | pet_resources.py:1106 | RoleLibrary（保留原图） | 良性（已注释） | "体积优化开关"的尽力而为路径，失败不影响导入结果 |
| 14 | pet_resources.py:1398 | pet_resources.py:1380 | AudioLibrary.import_fragment | 误报 | `return None, "复制文件失败"`。**本轮补注释** |
| 15 | pet_resources.py:1637 | pet_resources.py:1619 | VoiceAssetLibrary.import_file | 误报 | 同上。**本轮补注释** |
| 16 | pet_voice.py:711 | pet_voice.py:720 | VoiceLauncher.is_running | 误报 | 进程探针：内层取不到 create_time → `return False`（保守认定"不是我们的进程"）；外层兜底 `os.kill(pid, 0)` → 失败也 False。对探针来说 False 是**安全答案**。**领地外，只判定** |
| 17 | pet_voice.py:819 | pet_voice.py:828 | VoiceLauncher.wait_ready | 误报 | 同一个 try 的三个 handler（收紧①）；每个只写 `last`，循环后 `return False, "…（等了 N 秒…）" % (last…)` 已上报。**领地外，只判定** |
| 18 | pet_voice.py:821 | pet_voice.py:830 | 同上 | 误报 | 同上 |
| 19 | pet_voice.py:823 | pet_voice.py:832 | 同上 | 误报 | 同上 |

**统计：真 1（已修）· 误报 15 · 良性 3。** 没有第 4 类。

## 3. 领地内 13 处的落地清单（本轮实际改动）

| 文件 | 位置 | 改动 |
|---|---|---|
| pet_config.py | 291 | **补 `log(...)`**：读旧配置失败时留痕（此前只剩"Key 自己没了"） |
| pet_export.py | 452 | 补注释：为什么版本号读坏时静默回退是安全的 |
| pet_resources.py | 868 / 996 / 1048 / 1380 / 1619 | 各补一段注释：失败**已由返回值上报**，except 里只是"清理半截文件"的尽力而为（并说明清理失败的最坏后果） |
| pet_main.py | 31 | 无需改（既有注释已说明） |
| pet_resources.py | 1106 | 无需改（既有注释已说明） |

`pet_export.py:556` **有意保留**：给 pet_export 引 pet_log 会扩大改动面，而最坏后果只是一个空角色
条目，性价比不成立（已在代码注释里说明）。

## 4. 领地外 6 处（只判定，未改；交回主代理转派）

`pet_voice.py` 720 / 828 / 830 / 832、`pet_book.py` 682、`pet_io.py` 275-288 —— 全部判为 **误报**，
依据见上表第 1/8/16/17/18/19 行。**未改动任何一行代码。**

## 5. 怎么复跑

    python _dev/audit_silent_except.py --tier A     # 当前口径：A=4
    python -m pytest tests/test_silent_except_audit_v241.py -o addopts="" -q   # 判据自身的回归

审计脚本自己打印的就是完整三档报告；要留机器可读的原始版本，把上面第一条重定向到文件即可
（本轮那份一次性 dump `_dev/silent_except_review_v241.md` 已删：它与本文重复且一条命令可重生成）。
