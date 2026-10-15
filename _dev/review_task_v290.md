# v2.9.0（第 7 轮）三审任务书

**冻结快照（审查对象，锚定于此）**：HEAD `5ac99f0609b3ad2fa4ead5a919cf3be81a4478f4` · dirty=30 · lock=False · python_alive=0
```
pet_dialogs.py 824AD2A0AEF9   桌宠.py 17B471AA09E6       pet_behaviors.py 99F7DFF343E4
pet_ai.py A5989E7FE646        pet_config.py 7A4AD883D4E8 pet_plugin_index.py E5E9845785E8
pet_balance.py 66948E5514A4   _check_static.py 6286F9F493BD
README.md 7451C8886548        README.en.md DF96D3663013
```
**开工前先核哈希**；若与上表不符 → **停手报我**（说明树在动）。

**本轮护栏（主代理亲手跑，原文）**：pytest `1328 passed`（exit 0）· v13 `273/FAILS 0`（exit 0）· 静态 `0 问题 0 待确认`（exit 0）· 锚点 `496/坏 0`（exit 0）· nodeid `1140/坏 0`（exit 0）· `test_dialogs_behavior_v290.py 32 passed`。

## 本轮改了什么（背景）
用户报障：**"行为设置不对，还是不能导入素材创建新行为，有些按钮没用多余。按人机交互的知识改，现在效果不理想。"**
审计（`_dev/audit_behavior_assets_v290.md`）结论：**"选动作"这一步根本没被设计成一条路**（只能手打动作名；从素材做动作在另一个对话框；中间无指路无清单无校验），叠上 6 条"按 HCI 改反而更差"的改动。

**A（对话框与交互，`pet_dialogs.py` 894 行区间）**：A1 动作改可编辑下拉（候选唯一来源 `pet_behaviors.action_choices`）· A2 行为设置内「＋导入图片做动作…」+ 抽模块级 `add_frame_action`（角色编辑变薄包装）· A3 上移下移+边界回执+选中跟随 · A4 步骤回执改内联状态行（去气泡噪音）· A5 「关闭」→「取消」+ 未保存确认 · **A6 有意撤销上一轮的删动作二次确认** · A7 改名「导入行为文件（.json）…」+ 两层人话 · A8 按 B3 契约：VoiceDialog 保存不关窗、Voice/Idle 第二枚按钮改「取消」· A9 「要保存才落盘」提到常驻状态标签 · A10 最后一处静态 QInputDialog 并入 `_ask_text` · A11 D16 统一确认框 + 常驻「新建中」标签 + `open_idle` 给真实入口 · A12/B8 替身退化
**B（后端纯逻辑，`pet_behaviors.py` +255/−0）**：`action_choices` · `remove_idle_actions_for_behavior`（幂等/不误伤）· `idle_combo_state` / `idle_single_change`（**先算后写**）· `test_play_target`（**保存没成功不许播**）；`pet_ai.py` 两条牙齿弱点补测
**C（证据）**：补录上轮丢失的 23 条变异 · 指纹清单 12→14 · **nodeid 体检工具** · 五条证据保护规矩 + 一条测试健壮性规矩

## 你的审查任务（只读；唯一可写=你的报告）
**硬要求**：① **每条发现给 `文件:行号` 或实测输出** ② **改坏它是为了证明什么**：凡说"这个修好了"，**必须给出"还原后会红"的证据**（在**影子副本**里做，**不许改真仓**）③ **查不到就说查不到**，不许"大概/应该" ④ python 一律 `-B`；语法检查用 `ast.parse` ⑤ **不碰产品代码/tests/`_dev/**、不碰绿色版、不提交 git。

**⚠ 本轮的特别重点（我要求重点查的地方）**：
1. **`pet_dialogs.py` 894 行改动里的"未知名不被吃掉"**：老行为文件里含**任意**动作名 → 读入/保存后**原样保留**（UI 侧回填**绝不许回落第一条**）。B 的 `B1-M4` 是数据侧、A 的 `A1-M2` 是 UI 侧，**两个失败点都要看**。
2. **有意撤销与加强式改写**：A6 撤销了上一轮的二次确认；`test_role_edit_delete_action_needs_confirm_and_reports` → `..._needs_no_confirm_and_is_undoable`；`test_behavior_step_receipts` 改成读状态行 + `ui["toast"] == []`。**逐行看 `git diff HEAD -- tests/`，确认没有删断言、没有放宽**（本轮有 6 个领地外文件被改动，全部点名：`test_dialogs_more_v24.py` · `test_dialogs_v24.py` · `README.md:249` · `README.en.md:182` · `test_silent_except_v252.py:429`（数字 50→49）· 以及 C 的 `_check_release.py` 两个文件名字符串）。**A 主动点名说"50→49 那类数字被改动最容易藏回归"，请重点看那一处 diff。**
3. **B3 契约是否真落地**：VoiceDialog 保存**不关窗**、IdleDialog 第二枚按钮**改名「取消」**且**保存仍关窗**（零额外点击）、其余 8 个维持；**R4 不变量**（丢弃编辑的按钮不许叫「关闭」）有没有反例。
4. **"不会多打断一步"**：凡是"加确认/加回执/加提示"的改动，**是否让熟路多一步**。A5 要求"**没有改动直接关**"（无改动时不许弹）；**请找反例**。
5. **静默 except 与留痕**：A 把 4 处新 except 改成 `log_error`/`log_throttled`；**是否还有没理由的静默 except**（白名单 306 条 / `unreviewed` 0 是 C 的结论，**你独立看**）。

**回报格式**：`发现 | 证据(文件:行/实测输出) | 定性(阻断/一般/建议) | 你的验证方式` + **"我试过但没能推翻的假设"**（防止你只报坏消息）+ **"我查不到的部分"**。