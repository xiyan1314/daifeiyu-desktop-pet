仓库 E:\deep seek\desktop-pet（v2.6.0 第 4 轮）。**你是唯一写入者，活很小。**

**领地**：tests/test_plugin_market_v252.py、plugins/README.md、_dev/silent_except_report_v252.md（及其生成器 .py）、_dev/silent_except_whitelist_summary.json、.gitignore。
**不碰** VERSION / version_info / _verify_green / CHANGELOG / _release_notes_* / 绿色版 / 发布 zip。**不要提交。**
【铁律】跑前确认 _dev/.mutation.lock/ 不存在；python 一律 -B；语法检查用 ast.parse（别用 py_compile）；**不许放宽任何断言**；**断言不许依赖机器速度**。

验收员已逐条核过 20 条清单（20/20 已修、无删断言/放阈值/skip 类手脚），但抓出下面 5 处要收。

## 1 最重要：假覆盖（tests/test_plugin_market_v252.py:1011）
那条 Content-Length 用例的 docstring 声称"去掉 default_fetch 的前置判断就会红"，但验收员在影子里把 pet_plugin_index.py:223 的 if total and total > cap: 改成 if False: 之后，**用例仍然绿**。
原因：假 read 抛的 AssertionError 文本自带"对端自报"四个字，被 default_fetch 的 except Exception 包成错误串后，断言里那句 contains 判据照样成立（影子里实测 err = 网络请求失败：前置判断没生效：对端自报超限，还是去读内容了）。
产品代码那条前置是真的（:219-225 先看 Content-Length 再 read），只是**这条护栏抓不到它被删**。
**修**：① 假 read 抛的文本改成**不含"对端自报"**的字样（例如 READ-CALLED）；② 断言里补一条"错误串不能是取数被调用那类"（例如断言 网络请求失败 不在 err 里）。两条都做更稳。
**硬要求**：改完在**影子副本**里把那行改成 if False: → **必须红**；改回来 → 绿。把两次实测输出写进回报。

## 2 随包发货的文档还在骗用户（plugins/README.md:64-65）
那句仍写"补不出来才退回这一版不合并新内容的老口径"——A-3 的修复已证实与行为不符（新文案在 pet_plugin_host.py:1200-1202，用例在 tests/test_plugin_host_v251.py:1563）。**这个文件随绿色版发给用户**。
**修**：按 pet_plugin_host.py:1200-1202 的当前真实文案与行为改写那一句（已经落过的内容不重复落、**库里还缺的会照常补回来**）。只改这一处。

## 3 数字与失效引用（_dev/silent_except_report_v252.md）
① 4 处仍写白名单"222 条"→ 实测 **307**（222 + 收编的 85）→ 改成 307 并说明演变。
② 第 9 行仍把复跑命令写成**已停用**的 silent_except_mutate.py → 改成 python -B _dev/mutate_check.py _dev/mutations_silent_except_v260.json。
③ **生成器 .py 里同样两处一并同步**，否则下次生成又写回旧的。

## 4 同类缺口（验收员点名）：.gitignore 修了 plugins/*/ 却没修 prompts/custom/
P2-2 已把 prompts/custom 定性为**用户数据**（进了 USER_DATA_DIRS），而本仓开发方式是"仓库即数据目录"→ 装官方 persona 包或自建人设会冒未跟踪文件、撞 check_clean_tree（与 P2-3 给 plugins/ 修掉的同一类问题）。
**修**：.gitignore 里**忽略 prompts/custom/**，但**别误伤 prompts/*.txt 内置预设**（要随包发货、要入库）。
**硬要求**：给出 git check-ignore -v 两条实测 —— prompts/custom/x.txt 必须命中；prompts/default.txt 必须 rc=1（不命中）。

## 5 精度（低优先·非发布阻断）
白名单 85 条里 11 条的 lines 行号是快照旧值（偏移 +2 到 +8），证据文本仍可找到，razor 用 shape 指纹**不受影响**。若能一键刷新就刷新；**若刷新要重跑判定器且风险高，就在回报里说明并保留现状**。

【硬性】① 第 1 项两次实测输出 ② 第 4 项两条 git check-ignore 实测 ③ 完工回报三项护栏：python -B -m pytest tests -o addopts="" -q（目标 0 failed，当前 **1054**）· python -B _verify_v13.py（**273 项 0 FAILS**）· python -B _check_static.py（单跑 **0/0**）④ 不要提交 ⑤ 如实报告没做到的。