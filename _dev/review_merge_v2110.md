# v2.11.0 三审 · 合并收件箱（协调者维护）

> 规则：**先收齐再改**（改动会让其余两路的锚点作废）。每条注明来源路、`文件:行号`、是否实测。

## 质量路（acc02e07）· 2026-10-17 · 冻结复核 212/212 相符

**结论：能发**。2 必改 + 6 应改 + 3 备查。

### 必改
1. **系统通知静默丢弃 → 闹钟可能零感知，且两处文案说"回执不会静默丢"**
   - `pet_notify.py:19-20`（自述：远程桌面/explorer 没起/托盘折叠/系统关了通知 → showMessage 静默什么都不做）；`:112-117`（不抛就 return True）。
   - `桌宠.py:4294-4301`：shown 为真就 return True、不再弹气泡；唯一调用点是闹钟 `:2225-2227`（注释写"回执不会静默丢"）；`_release_notes_v2110.md:26` 同口径。**与 `cfg["sound"]` 无关**（铃声另受开关管）→ 若音效也关，闹钟既无气泡也无声音 = 相对 v2.10.0 的回归。
   - 建议：shown 为真时仍补一条气泡（或至少 sound 关时补）；两处口径改成"托盘不可用/被限流/开关关 → 退回气泡；**托盘接受但系统丢弃的，代码无法感知**"。
2. **CHANGELOG 自述与现树矛盾**：`CHANGELOG.md:9` 仍写"版本号五处仍停在 2.10.0"，而五处实测已是 2.11.0 → 删/改。

### 应改
3. `_fs_override` 是**死字段**（`桌宠.py:1135` 注释声称"手动叫出来不再藏"，全仓只有三处赋值且都是 False；`_show_pet()` 不置位）→ 现在靠 `_hidden_for_fullscreen` 巧合成立；且 `_check_fullscreen/set_fullscreen_hide/_fs_override` 在 tests 里 **0 命中**（默认开的功能藏/显两跳无判据）。
4. 备份成功回执的"常驻"只写在注释里：`pet_dialogs.py:7985-7986` 说 hold_ms=0，实际 `_toast(pet, msg)` 走默认 5s → 含 zip 全路径那句 5 秒就没了。
5. 恢复后"建议重启"是口头：`pet_backup.py:836-838`；现树 27 处 `save_config(self.cfg)` 会把内存旧配置写回 → 恢复被悄悄盖回去。建议改"**必须**重启"或置"配置待重载"标志。
6. 时段问候"只认 True（"true"/1 不算）"与归一化相反：`pet_config._to_bool` 会把 "true" 变 True → 改注释与发布说明即可。
7. 走路帧**没有被动停止点**：`pet_wander.py:104-111` 三支只早退不 `_walk_anim(False)`；按下时 `桌宠.py:5340-5341` 只 stop timer → 拖拽/甩抛期间原地迈腿（概率低）。
8. **四条回执路径零用例**（`open_backup/open_restore` · `_time_mood_tick/_set_time_mood` · `_check_fullscreen/set_fullscreen_hide/_fs_override` · `桌宠._notify` 的退回组合）。

### 备查
9. `audit_tautology --strict` exit 0；`test_boundary_claims_v2110` 有反向对照（不是空转）；`test_walk_anim_v2110.py:319` 基线取在动作之后 → 对"临时 addItem 再删"不敏感（同 helper 在 `:303` 那条是真判据）。
10. 文案：`⏰` 与同子菜单的「⏰ 闹钟…」重名，建议换图标；全屏隐藏"无声藏起来"建议首次给一次性提示；时段问候在窗口外打开最长等约 7 小时（建议回一句"下次 XX:00 叫你"）。撤销光晕/描边净删 ✔（产品码 0 命中）；C-34 变身已进形态子菜单 ✔。
11. 数字账本：`桌宠.py` 305 / `pet_dialogs.py` 424 == README ✔；walk 8 张 256×256、sha 互不相同、参数 2.0px/1.5°/±1% == 发布说明 ✔。

### 质量路**没测**的
没跑 pytest（会写 `__pycache__`/`.pytest_cache`）、没跑 `gen_walk_frames.py --check` —— 全部结论来自只读读码 / AST / 哈希 / PNG 头解析。

## 待收
- [ ] 找茬（b9b34933）
- [ ] 兼容（090f7220）


## 兼容路（090f7220）· 结论：不建议按现树发（2 必改都是发布口径/流程，不是代码缺陷）

1. **崩溃重启在打包 exe 上不生效**：`大肥鱼桌宠.spec:5` 入口是 桌宠.py，守护在 main.py:68-133 → exe 永不执行；而发布说明 :25 写开、:44 没提 exe。修法二选一：spec 入口改 main.py ／ 文案限定为「仅源码 python main.py 启动生效」。
2. **绿色版未同步**：check_sync 实测 missing 13 / diff 12（缺 5 个新模块 + 8 张 walk 帧；绿版 VERSION 仍 2.10.0）→ 现在打绿版包 = 名义 2.11 / 实际 2.10，双击即 ImportError。**这属 ⑩ 绿版同步的活**。
3. 恢复备份后不重载内存也不强制重启 → 25 处 save_config 会用旧 cfg 盖回去（**与质量路 #5 同一件事，两路独立命中 ⇒ 提优先级**）。
4. verify_backup 不看 config.json 的 schema_version：实测 schema=9 的包恢复成功 → 之后配置永不再落盘，界面只有 error.log。
5. 全屏隐藏对老用户默认开（桌宠.py:272），而同批 time_mood 默认关的理由正是「老用户升级不该突然变化」→ 建议首启提示或默认关。
6. 备查：备份包「有一条不在白名单就整包拒」（跨版本恢复会变整包不可用，文案未写）· crash_recovery.json 无倒灌风险（实测）· 五新模块无第三方依赖（requirements 不变）· 打包门能真红（反向对照实测）· 老配置升级实测通过 · 冻结清单含 ledger/roles 两个用户数据文件（跑一次桌宠就会让冻结失效，未来冻结只收代码/测试/资产）。

## 待收
- [ ] 找茬（b9b34933）


## 找茬路（b9b34933）· 结论：**不能发（3 必改）** · 冻结 212/212 相符 · 变异抽查 13 条：12 红 / 1 绿

**必改**
1. 通知回执口径错（与质量路 #1 同）：pet_notify 只要不抛就 True；桌宠.py:4289-4291 docstring 与 :2226 注释称「回执不会静默丢」为假；闹钟退化成单通道（音效关时零感知）。
2. **CHANGELOG.md:7-18 的 v2.11.0 段只写了撤光晕/描边** —— 走路播帧、交叉淡入、全屏隐藏、备份/恢复、崩溃守护、通知+hold_ms、时段问候、A-07/C-34/A-10 清账**一个字没有**（全文件 grep 无「全屏」「备份」「走路」「通知」「时段」）；另有 :9 仍写「版本号五处仍停在 2.10.0」。
3. **守护重启记账顺序与 pet_guard 契约相反**：main.py:110-112 在 sleep/spawn **之前**就 record_crash(will_restart=True)；pet_guard.py:396-401 明写 note_restart 只在真的拉起之后调，而 main.py 从未调 note_restart/adopt_marker；main.py:122 注释「少记一次重启」为假；main.py:97-106 连做两次 decide()（第一次结果被覆盖 = 死代码）；tests 里 main.run 0 命中。

**应改** 4. _fs_override 死字段 + 全屏藏/显零判据 · 5. tests/test_windows_v2110.py:477 的「能真失败」配方是假的（挪 _last_poll 不变红，只有整行删才红）· 6. A-07 钉子只认 _reduce_motion 一个名字（另有 _sys_reduce_motion / pet_motion.reduce_motion_enabled 两条等价入口）· 7. 按住/拖拽时原地踏步（实测：复刻 mousePressEvent 后 anim_mode=walk、1.5s 仍在换帧）· 8. _walk_anim 非首形态守卫零用例 · 9. 不记账只在代码里成立、零判据。

**备查** 10. 净删是真净删（产品码 0 命中）· 11. git diff HEAD -- tests/ 只有收紧没有放宽 · 12. 备份三条承诺经得起看 · 13. 混合 DPI 原点换算错误已披露但无判据 · 14. **冻结清单不覆盖头号新资产**（assets/walk_* 与 _dev/gen_walk_frames.py 都不在 212 条里）；发布说明第六节仍是「待取」· 15. 与质量路重合 1/3/7/8，其清单没有第 2 后半/3/5/6/8/13/14。
