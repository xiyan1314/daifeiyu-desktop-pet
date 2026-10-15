# v2.7.0 前置盘点：按钮接线全量审计 + 角色绑定「只剩不绑定」定位

- **日期**：2026-10-12｜**仓库**：E:\deep seek\desktop-pet（v2.6.1，HEAD 9f7fb78）
- **性质**：**只读盘点**。本轮未改任何产品代码 / 测试 / 文档；全篇唯一写入的文件就是本文件。
- **方法**：ast.parse 静态分析（不用 py_compile）+ 只读 grep + 临时目录探针（-B，系统 TEMP，未碰真仓用户数据、未碰绿色版目录）。
- **口径**：判定"接线" = 该控件被 .clicked/.triggered/.toggled/.accepted/….connect(…) 接上，或经**别名 / 容器 / 返回值 / 跨方法同名句柄**传递后接上；判定"未接线" = 在**方法作用域**内没有任何 connect，且别名闭包、容器成员、返回值、跨方法同名句柄**全部查过仍为空**。

---

## 0. 结论摘要（先看这里）

> **v2.7.0 第 5 轮已修（收尾标注）**：**动作按钮未接线 0 条**（原 2 条 ——「继续导出」/「取消」
> 已接 `clicked.connect`，并有用例从**菜单项**一路钉到产物：`tests/test_critic_menu_e2e_v270.py`）。
> **状态输入（QCheckBox）未接线仍 15 条** —— 那不是缺陷（逐条反证见 §3.1），口径与结论不变。
> 本文其余 `文件:行号` 对应**审计当时**的树（`pet_dialogs.py` 之后净增约 +380 行），引用时请按句柄名 grep。

**未接线的动作按钮：2 条**（↓ 已由上注修掉；以下是审计当时的现场）（同一处、同一条缺陷）——`pet_dialogs.py:5809 btn_ok = QPushButton("继续导出")` 与 `pet_dialogs.py:5810 btn_cancel = QPushButton("取消")`。
全仓 grep `btn_ok|btn_cancel` **只命中 4 行**（:5809 创建、:5810 创建、:5811-5812 两条 row.addWidget(…)），**零 clicked.connect**。
→ 导出角色流程必现卡死（P1）。与既有诊断一致，本轮复核成立。

**最严重的 3 条**：

| # | 位置 | 现象 | 级别 |
|---|---|---|---|
| 1 | pet_dialogs.py:5809 / :5810 | 两个按钮点了没反应 → pick_role_meta()(:5768) 的 modal(dlg) 里关不掉窗口，**导出角色包完全不可用** | **P1** |
| 2 | tests/test_dialog_fit_v250.py（整份）+ tests/helpers_dialog_fit_v250.py（20 个窗口清单） | 尺寸契约**只量几何、从不点按钮**：该文件里 .click()/QTest/clicked/isChecked **命中 0**；全仓唯一一处 .click() 用例在 tests/test_plugin_market_v252.py:1144，_verify_v13.py 与 _dev/ 各 0 处 → "抽成工厂后忘记接线"这类缺陷**没有任何用例能发现** | **P2（系统性防线缺失）** |
| 3 | pet_dialogs.py:5138-5145（VoiceDialog._asset_items）→ :5160-5163 | 角色绑定下拉在声音素材库为空时**只剩一项「（不绑定）」**，界面既不解释也没入口；填充异常还被 :5143 except Exception: pass 静默吞掉 | **P2** |

**其余 121 个按钮类控件 + 54 个菜单动作全部有据可查地接线**；空 lambda **0**；接到不存在的方法 **0**；handler 体死路 **0**。

---

## 1. 覆盖范围与统计（数字来自实跑，不是估算）

扫描产物（系统临时目录，未入库）：%TEMP%\pet_audit\{raw,resolve,audit,menu_audit,dead10}.json。

| 项 | 数量 | 说明 |
|---|---|---|
| 按钮类控件构造点 | **123** | QPushButton / QToolButton / QCheckBox / QRadioButton / QDialogButtonBox；**全部**在 pet_dialogs.py（pet_menu.py / 桌宠.py / pet_tools.py / pet_plugin_host.py 里这类构造点 = 0） |
| 已接线 | **106** | 见 2.3 |
| **未接线** | **17** | = 2 个动作按钮（真缺陷）+ 15 个 QCheckBox 状态输入（**非缺陷**，逐条反证见 3.1） |
| 菜单动作绑定 | **61** | X = <menu>.addAction(…) / addMenu(…)：pet_menu.py 59 + 桌宠.py 2（托盘菜单） |
| 其中 QAction（需接线） | **54** | **54/54 已接线**（triggered / toggled） |
| 其中子菜单容器 | 7 | addMenu(…)，不需要接线（见 2.2） |
| 内联 addAction（无变量） | 5 | 展示行 setEnabled(False) 或 QActionGroup.addAction(act) 分组（见 2.2） |
| QDialogButtonBox | **0** | 全仓没有这个类；唯一两处 addButton 是 QMessageBox（:325-326），由 QMessageBox 自己派发（见 2.2） |
| 空 lambda / pass 回调 | **0** | 见 2.2 |
| 接到不存在的方法 | **0** | 120 条 self.<m> 全部在**声明类或其基类**（或 Qt 内建 accept/reject/close/…）里找到；53 个 pet.<svc>.<m> / pet._<m> 全部存在于对应模块与类（见 3.2） |
| handler 体死路（docstring/pass/常量 return） | **0** | 同 3.2 |

---

## 2. 任务 1：全量按钮表

排序：**未接线 → 可疑/需人工确认 → 已接线**。"证据"列直接给出我在源码里读到的行号或语句。

### 2.1 未接线（17 条）

| 文件:行号 | 按钮文案 | 变量名 | 是否接线 | 接到哪（函数名）| 判定 |
|---|---|---|---|---|---|
| pet_dialogs.py:5809 | 继续导出 | btn_ok | **否** | —（全仓零 connect；:5809-5812 只有创建与 row.addWidget） | **未接线 → P1** |
| pet_dialogs.py:5810 | 取消 | btn_cancel | **否** | —（全仓零 connect；:5809-5812 只有创建与 row.addWidget） | **未接线 → P1** |
| pet_dialogs.py:1160 | 自动去背景（无透明通道时） | self._adv_rmbg | 否（状态输入） | `.isChecked()` @1537 | 无缺陷：状态输入，保存路径读了它 |
| pet_dialogs.py:1162 | 裁剪透明边距 | self._adv_trim | 否（状态输入） | `.isChecked()` @1538 | 无缺陷：状态输入，保存路径读了它 |
| pet_dialogs.py:1164 | 保留原图到角色目录 source/ | self._adv_keep | 否（状态输入） | `.isChecked()` @1539 | 无缺陷：状态输入，保存路径读了它 |
| pet_dialogs.py:1713 | 睡觉形态 | self._ck_sleep_form | 否（状态输入） | 1815-1821 循环 → _ck.isChecked() @1818 | 无缺陷：状态输入，保存路径读了它 |
| pet_dialogs.py:1714 | 变身形态 | self._ck_transform_form | 否（状态输入） | 1816（同一循环元组项）→ _ck.isChecked() @1818 | 无缺陷：状态输入，保存路径读了它 |
| pet_dialogs.py:1715 | 不参与喂食 | self._ck_no_feed | 否（状态输入） | 1817（同一循环元组项）→ _ck.isChecked() @1818 | 无缺陷：状态输入，保存路径读了它 |
| pet_dialogs.py:2715 | 启用 | self._ck_enabled | 否（状态输入） | `.isChecked()` @2807 | 无缺陷：状态输入，保存路径读了它 |
| pet_dialogs.py:2966 | 写入类操作先问我（记账/预算/闹钟/定时提醒） | self._tools_confirm | 否（状态输入） | `.isChecked()` @3090 | 无缺陷：状态输入，保存路径读了它 |
| pet_dialogs.py:2977 | 把记账摘要与长期记忆随对话发给 AI（取消勾选 = 完全不注入） | self._rag | 否（状态输入） | `.isChecked()` @3091 | 无缺陷：状态输入，保存路径读了它 |
| pet_dialogs.py:4700 | 顶边也反弹（ceilingBounce） | self._ceil | 否（状态输入） | `.isChecked()` @4719 | 无缺陷：状态输入，保存路径读了它 |
| pet_dialogs.py:4778 | 开启语音（默认关闭） | self._en | 否（状态输入） | `.isChecked()` @5358 | 无缺陷：状态输入，保存路径读了它 |
| pet_dialogs.py:4781 | 日常台词也用配音朗读（气泡同时显示；关闭则只有气泡） | self._daily | 否（状态输入） | `.isChecked()` @5363 | 无缺陷：状态输入，保存路径读了它 |
| pet_dialogs.py:4908 | 启动桌宠时自动拉起后端（默认关：和以前一样自己启动） | self._lauto | 否（状态输入） | `.isChecked()` @4967 | 无缺陷：状态输入，保存路径读了它 |
| pet_dialogs.py:4910 | 桌宠退出时结束它自己拉起的后端（手动开的不动） | self._lkill | 否（状态输入） | `.isChecked()` @4968 | 无缺陷：状态输入，保存路径读了它 |
| pet_dialogs.py:5484 | 被打断的动作算已消费（下次不再重播它） | self._resume | 否（状态输入） | `.isChecked()` @5620 | 无缺陷：状态输入，保存路径读了它 |

### 2.2 可疑 / 需人工确认（**不判定为缺陷**，但逐条给证据）

| 位置 | 文案 / 变量 | 疑点 | 证据与判定 |
|---|---|---|---|
| pet_dialogs.py:325 | yes = box.addButton("确定", YesRole) | addButton 后没有 clicked.connect | :324 box = _box(…) 造的是 **QMessageBox**；:327 modal(box)；:328 return box.clickedButton() is yes —— **QMessageBox 自派发按钮事件**，不需要 connect。**判定：已接线（框架内建）** |
| pet_dialogs.py:326 | box.addButton("取消", NoRole) | 同上 | 同上。**判定：已接线（框架内建）** |
| pet_menu.py:69 / 79 / 88 / 111 / 132 / 170 / 211 | food_menu / form_menu / role_menu / book_menu / set_menu / snd_set / act_menu | 扫描器报"未接线" | 这 7 条是 menu.addMenu("…") 的**子菜单容器**（返回 QMenu 不是 QAction），本来就没有 triggered 可接。**判定：无缺陷** |
| pet_menu.py:45 / 95 / 101 / 177 / 182 | 内联 addAction | 无变量名可查 | :45 menu.addAction(self._make_size_action(menu))（QWidgetAction 滑块）；:95/:101/:177/:182 <group>.addAction(act)（QActionGroup 互斥分组）。**判定：无缺陷** |
| pet_dialogs.py:2388 / 2726 / 4163 / 4361 / 5466 | _b / b = QPushButton(_label) | 文案是循环变量，值域不明 | 均在 for _label, _cb in (…) 循环里创建并**当场**接线（:2389 / :2727 / :4164 / :4362 / :5467）。**判定：已接线**；但每个文案是否都该有分支**需人工确认**（未逐个数循环项） |

### 2.3 已接线（106 条按钮）

| 文件:行号 | 按钮文案 | 变量名 | 是否接线 | 接到哪（函数名）| 判定 |
|---|---|---|---|---|---|
| pet_dialogs.py:1123 | ＋ 添加形态 | self._add_form_btn | 是 | `clicked -> self._add_form` @1124 | 已接线 |
| pet_dialogs.py:1135 | 选多张图片… | m_btn | 是 | `clicked -> self._pick_multi` @1136 | 已接线 |
| pet_dialogs.py:1137 | 视频/GIF 抽帧… | v_btn | 是 | `clicked -> self._pick_video` @1138 | 已接线 |
| pet_dialogs.py:1153 | 自定义帧间隔 | self._adv_interval_chk | 是 | `toggled -> self._adv_interval.setEnabled` @1159 | 已接线 |
| pet_dialogs.py:1166 | 自定义渲染参数（锚点/缩放/偏移） | self._adv_render_chk | 是 | `toggled -> lambda on: [w.setEnabled(on) for w in self._adv_render_widgets]` @1191 | 已接线 |
| pet_dialogs.py:1223 | 导入 | self._ok | 是 | `clicked -> self._do_import` @1229 | 已接线 |
| pet_dialogs.py:1224 | 取消 | self._cancel | 是 | `clicked -> self.reject` @1230 | 已接线 |
| pet_dialogs.py:1225 | 停止处理 | self._stop_btn | 是 | `clicked -> self._stop_worker` @1226 | 已接线 |
| pet_dialogs.py:1274 | 浏览… | pick | 是 | `clicked -> lambda _c=False, fi=i: self._pick_form(fi)` @1275 | 已接线 |
| pet_dialogs.py:1276 | ✕ | rem | 是 | `clicked -> lambda _c=False, fi=i: self._del_form(fi)` @1278 | 已接线 |
| pet_dialogs.py:1644 | 上移 | up_btn | 是 | `clicked -> lambda : self._move_form(-1)` @1645 | 已接线 |
| pet_dialogs.py:1646 | 下移 | down_btn | 是 | `clicked -> lambda : self._move_form(1)` @1647 | 已接线 |
| pet_dialogs.py:1672 | 换图（重新处理）… | self._img_btn | 是 | `clicked -> self._pick_image` @1673 | 已接线 |
| pet_dialogs.py:1674 | 设正面图… | self._front_btn | 是 | `clicked -> self._pick_front` @1675 | 已接线 |
| pet_dialogs.py:1676 | 清正面 | self._front_clear | 是 | `clicked -> self._clear_front` @1677 | 已接线 |
| pet_dialogs.py:1743 | 选图… | st_pick | 是 | `clicked -> self._pick_state` @1744 | 已接线 |
| pet_dialogs.py:1745 | 清除 | st_clear | 是 | `clicked -> self._clear_state` @1746 | 已接线 |
| pet_dialogs.py:1762 | ＋帧动作… | b_add_f | 是 | `clicked -> self._add_frame_action` @1763 | 已接线 |
| pet_dialogs.py:1764 | ＋合成… | b_add_p | 是 | `clicked -> self._add_proc_action` @1765 | 已接线 |
| pet_dialogs.py:1766 | 删除 | b_del | 是 | `clicked -> self._del_action` @1767 | 已接线 |
| pet_dialogs.py:1778 | 保存 | self._ok | 是 | `clicked -> self._save` @1781 | 已接线 |
| pet_dialogs.py:1779 | 取消 | self._cancel | 是 | `clicked -> self.reject` @1782 | 已接线 |
| pet_dialogs.py:2257 | 添加 | ok | 是 | `clicked -> dlg.accept` @2258 | 已接线 |
| pet_dialogs.py:2370 | 添加步骤 | b_add_step | 是 | `clicked -> self._add_step` @2371 | 已接线 |
| pet_dialogs.py:2377 | 删除选中步骤 | b_del_step | 是 | `clicked -> lambda : self._steps.takeItem(self._steps.currentRow())` @2378 | 已接线 |
| pet_dialogs.py:2388 | <Name> | _b | 是 | `clicked -> _cb` @2389 | 已接线 |
| pet_dialogs.py:2706 | 选铃声…（wav/mp3） | self._ring_btn | 是 | `clicked -> self._pick_ringtone` @2707 | 已接线 |
| pet_dialogs.py:2708 | 清除铃声 | self._ring_clear | 是 | `clicked -> self._clear_ring` @2709 | 已接线 |
| pet_dialogs.py:2710 | 试听 | self._ring_test | 是 | `clicked -> self._test_ring` @2711 | 已接线 |
| pet_dialogs.py:2726 | <Name> | _b | 是 | `clicked -> _cb` @2727 | 已接线 |
| pet_dialogs.py:2919 | 测试连接 | self._test_btn | 是 | `clicked -> self._test_connection` @2920 | 已接线 |
| pet_dialogs.py:2963 | 允许 AI 主动调用工具（查余额/天气/记账/闹钟/表情） | self._tools | 是 | `toggled -> self._tools_confirm.setEnabled` @2969 | 已接线 |
| pet_dialogs.py:2987 | 清除长期记忆（称呼/别名/喜好/不喜欢/近况） | _lt_btn | 是 | `clicked -> self._clear_long_term` @2988 | 已接线 |
| pet_dialogs.py:2997 | 保存 | ok | 是 | `clicked -> self._save` @3000 | 已接线 |
| pet_dialogs.py:2998 | 取消 | cancel | 是 | `clicked -> self.reject` @3001 | 已接线 |
| pet_dialogs.py:3115 | 导入角色… | self._btn_import | 是 | `clicked -> self._import` @3123 | 已接线 |
| pet_dialogs.py:3116 | 设为当前 | self._btn_set | 是 | `clicked -> self._set_active` @3124 | 已接线 |
| pet_dialogs.py:3117 | 编辑… | self._btn_edit | 是 | `clicked -> self._edit` @3125 | 已接线 |
| pet_dialogs.py:3118 | 删除 | self._btn_del | 是 | `clicked -> self._delete` @3126 | 已接线 |
| pet_dialogs.py:3119 | 恢复默认 | self._btn_default | 是 | `clicked -> self._reset_default` @3127 | 已接线 |
| pet_dialogs.py:3398 | 试听 | b_preview | 是 | `clicked -> self._preview_selected` @3404 | 已接线 |
| pet_dialogs.py:3399 | 导入音频… | b_import | 是 | `clicked -> self._import_audio` @3405 | 已接线 |
| pet_dialogs.py:3400 | 重命名 | b_rename | 是 | `clicked -> self._rename` @3406 | 已接线 |
| pet_dialogs.py:3401 | 删除 | b_del | 是 | `clicked -> self._delete_audio` @3407 | 已接线 |
| pet_dialogs.py:3590 | 试听 | b_preview | 是 | `clicked -> self._preview_selected` @3596 | 已接线 |
| pet_dialogs.py:3591 | 导入参考音… | b_import | 是 | `clicked -> self._import_asset` @3597 | 已接线 |
| pet_dialogs.py:3592 | 重命名 | b_rename | 是 | `clicked -> self._rename` @3598 | 已接线 |
| pet_dialogs.py:3593 | 删除 | b_del | 是 | `clicked -> self._delete_asset` @3599 | 已接线 |
| pet_dialogs.py:3710 | 关闭 | close_btn | 是 | `clicked -> self.reject` @3711 | 已接线 |
| pet_dialogs.py:3747 | 确定 | ok_btn | 是 | `clicked -> self.accept` @3750 | 已接线 |
| pet_dialogs.py:3748 | 取消 | cancel_btn | 是 | `clicked -> self.reject` @3751 | 已接线 |
| pet_dialogs.py:3797 | 记一笔… | self._btn_add | 是 | `clicked -> self._add_manual` @3800 | 已接线 |
| pet_dialogs.py:3798 | 导出 CSV… | self._btn_export | 是 | `clicked -> self._export` @3801 | 已接线 |
| pet_dialogs.py:3799 | 关闭 | close_btn | 是 | `clicked -> self.reject` @3802 | 已接线 |
| pet_dialogs.py:3920 | — | btn | 是 | `clicked -> lambda _checked=False, k=key: self._pick(k)` @3922 | 已接线 |
| pet_dialogs.py:3949 | 保存 | save_btn | 是 | `clicked -> self._save` @3953 | 已接线 |
| pet_dialogs.py:3950 | 恢复默认 | reset_btn | 是 | `clicked -> self._reset_default` @3954 | 已接线 |
| pet_dialogs.py:3951 | 取消 | cancel_btn | 是 | `clicked -> self.reject` @3955 | 已接线 |
| pet_dialogs.py:4051 | 关闭 | close_btn | 是 | `clicked -> self.accept` @4052 | 已接线 |
| pet_dialogs.py:4163 | <Name> | b | 是 | `clicked -> cb` @4164 | 已接线 |
| pet_dialogs.py:4328 | 新建对白 | b_new | 是 | `clicked -> self._new_dialogue` @4329 | 已接线 |
| pet_dialogs.py:4330 | 删除对白 | b_del | 是 | `clicked -> self._delete_dialogue` @4331 | 已接线 |
| pet_dialogs.py:4343 | 保存名称 | b_rename | 是 | `clicked -> self._rename_dialogue` @4344 | 已接线 |
| pet_dialogs.py:4353 | 添加 → | b_add | 是 | `clicked -> self._add_member` @4354 | 已接线 |
| pet_dialogs.py:4361 | <Name> | b | 是 | `clicked -> cb` @4362 | 已接线 |
| pet_dialogs.py:4518 | 重新扫描 | b_scan | 是 | `clicked -> lambda : (self._scan(), self._refresh_invalid())` @4519 | 已接线 |
| pet_dialogs.py:4520 | 修复角色… | b_fix_role | 是 | `clicked -> self._fix_role` @4521 | 已接线 |
| pet_dialogs.py:4522 | 修复声音… | b_fix_voice | 是 | `clicked -> self._fix_voice` @4523 | 已接线 |
| pet_dialogs.py:4524 | 清空引用 | b_clear | 是 | `clicked -> self._clear_refs` @4525 | 已接线 |
| pet_dialogs.py:4531 | 删除该台词 | b_del | 是 | `clicked -> self._delete_bad_one` @4532 | 已接线 |
| pet_dialogs.py:4533 | 一键删除所有失效台词 | b_del_all | 是 | `clicked -> self._delete_all_bad` @4534 | 已接线 |
| pet_dialogs.py:4704 | 保存 | ok | 是 | `clicked -> self._save` @4707 | 已接线 |
| pet_dialogs.py:4705 | 取消 | cancel | 是 | `clicked -> self.reject` @4708 | 已接线 |
| pet_dialogs.py:4764 | 保存 | ok | 是 | `clicked -> self._save` @4767 | 已接线 |
| pet_dialogs.py:4765 | 关闭 | cancel | 是 | `clicked -> self.reject` @4768 | 已接线 |
| pet_dialogs.py:4856 | 测试后端 | b_test | 是 | `clicked -> self._test_backend` @4857 | 已接线 |
| pet_dialogs.py:4858 | 管理声音素材…（导入/试听/删除） | b_assets | 是 | `clicked -> self._open_assets` @4859 | 已接线 |
| pet_dialogs.py:4889 | 选脚本… | _b_cmd | 是 | `clicked -> self._pick_launch_cmd` @4890 | 已接线 |
| pet_dialogs.py:4897 | 选目录… | _b_cwd | 是 | `clicked -> self._pick_launch_cwd` @4898 | 已接线 |
| pet_dialogs.py:4914 | 立即启动后端 | self._lstart | 是 | `clicked -> self._start_backend_now` @4915 | 已接线 |
| pet_dialogs.py:4916 | 结束后端（只关桌宠拉起的） | self._lstop | 是 | `clicked -> self._stop_backend_now` @4917 | 已接线 |
| pet_dialogs.py:5173 | 试听 | b | 是 | `clicked -> lambda _c=False, c=cb: self._preview(c.currentData())` @5174 | 已接线 |
| pet_dialogs.py:5207 | 朗读 | b_speak | 是 | `clicked -> self._speak_line` @5208 | 已接线 |
| pet_dialogs.py:5209 | 重新生成 | b_regen | 是 | `clicked -> self._regen_line` @5210 | 已接线 |
| pet_dialogs.py:5211 | 停止 | b_stop | 是 | `clicked -> self._stop` @5212 | 已接线 |
| pet_dialogs.py:5220 | 朗读整段对白 | b_dspeak | 是 | `clicked -> self._speak_dialogue` @5221 | 已接线 |
| pet_dialogs.py:5224 | 编辑台词/对白…（台词设置） | b_edit | 是 | `clicked -> lambda : modal(LinesDialog(self._pet))` @5225 | 已接线 |
| pet_dialogs.py:5298 | 导入… | b1 | 是 | `clicked -> lambda _c=False, k=key: self._import(k)` @5299 | 已接线 |
| pet_dialogs.py:5300 | 试听 | b2 | 是 | `clicked -> lambda _c=False, k=key: self._test(k)` @5301 | 已接线 |
| pet_dialogs.py:5302 | 清除 | b3 | 是 | `clicked -> lambda _c=False, k=key: self._clear(k)` @5303 | 已接线 |
| pet_dialogs.py:5461 | 添加 | b_add | 是 | `clicked -> self._add_action` @5462 | 已接线 |
| pet_dialogs.py:5466 | <Name> | b | 是 | `clicked -> cb` @5467 | 已接线 |
| pet_dialogs.py:5490 | 保存 | ok | 是 | `clicked -> self._save` @5493 | 已接线 |
| pet_dialogs.py:5491 | 关闭 | cancel | 是 | `clicked -> self.reject` @5494 | 已接线 |
| pet_dialogs.py:5741 | 全选 | b_all | 是 | `clicked -> lambda : self._check_all(True)` @5742 | 已接线 |
| pet_dialogs.py:5743 | 全不选 | b_none | 是 | `clicked -> lambda : self._check_all(False)` @5744 | 已接线 |
| pet_dialogs.py:5748 | 确定 | ok | 是 | `clicked -> self.accept` @5750 | 已接线 |
| pet_dialogs.py:5751 | 取消导出 | cancel | 是 | `clicked -> self.reject` @5752 | 已接线 |
| pet_dialogs.py:6013 | 安装 | self._btn_install | 是 | `clicked -> lambda checked=False: self._install_selected()` @6029 | 已接线 |
| pet_dialogs.py:6020 | 安装… | self._btn_install_file | 是 | `clicked -> lambda checked=False: self._install()` @6030 | 已接线 |
| pet_dialogs.py:6022 | 更新 | self._btn_update | 是 | `clicked -> lambda checked=False: self._update_selected()` @6031 | 已接线 |
| pet_dialogs.py:6023 | 回滚 | self._btn_rollback | 是 | `clicked -> lambda checked=False: self._rollback()` @6032 | 已接线 |
| pet_dialogs.py:6024 | 卸载 | self._btn_uninstall | 是 | `clicked -> lambda checked=False: self._uninstall()` @6033 | 已接线 |
| pet_dialogs.py:6025 | 启用 / 禁用 | self._btn_toggle | 是 | `clicked -> lambda checked=False: self._toggle()` @6034 | 已接线 |
| pet_dialogs.py:6026 | 刷新索引 | self._btn_refresh | 是 | `clicked -> lambda checked=False: self.refresh_index(manual=True)` @6035 | 已接线 |
| pet_dialogs.py:6027 | 关闭 | close_btn | 是 | `clicked -> self.reject` @6036 | 已接线 |

### 2.4 已接线（54 条菜单动作 + 7 个子菜单容器）

| 文件:行号 | 菜单文案 | 变量名 | 是否接线 | 接到哪（函数名）| 判定 |
|---|---|---|---|---|---|
| pet_menu.py:47 | 📌 窗口置顶 | pet._top_act | 是 | `toggled -> pet._set_always_on_top` @50 | 已接线 |
| pet_menu.py:51 | 🔊 音效 | sound_act | 是 | `toggled -> pet._set_sound` @54 | 已接线 |
| pet_menu.py:55 | 🤖 AI对话 | pet._ai_act | 是 | `toggled -> pet.ai.set_ai_enabled` @58 | 已接线 |
| pet_menu.py:60 | 🌀 甩抛物理 | phys_act | 是 | `toggled -> pet._set_physics` @63 | 已接线 |
| pet_menu.py:66 | 💭 和它说话 | talk_act | 是 | `triggered -> pet.ai.talk` @67 | 已接线 |
| pet_menu.py:69 | 🍖 喂食 | food_menu | 不需要 | —（addMenu 返回子菜单容器） | 无缺陷：子菜单 |
| pet_menu.py:71 | — | act | 是 | `triggered -> lambda checked=False, f=food: pet.feed(f)` @72；`triggered -> lambda checked=False, k=key: pet.set_user_form(k)` @86；`triggered -> lambda checked=False, rid=r.get('id'): pet.apply_role(rid)` @100 | 已接线 |
| pet_menu.py:74 | 🍱 食物托盘 | tray_act | 是 | `toggled -> pet._set_food_tray` @77 | 已接线 |
| pet_menu.py:79 | 🐡 形态 | form_menu | 不需要 | —（addMenu 返回子菜单容器） | 无缺陷：子菜单 |
| pet_menu.py:84 | — | act | 是 | `triggered -> lambda checked=False, f=food: pet.feed(f)` @72；`triggered -> lambda checked=False, k=key: pet.set_user_form(k)` @86；`triggered -> lambda checked=False, rid=r.get('id'): pet.apply_role(rid)` @100 | 已接线 |
| pet_menu.py:88 | 🐟 角色 | role_menu | 不需要 | —（addMenu 返回子菜单容器） | 无缺陷：子菜单 |
| pet_menu.py:91 | 默认角色 | role_def | 是 | `triggered -> lambda checked=False: pet.apply_role('')` @94 | 已接线 |
| pet_menu.py:97 | — | act | 是 | `triggered -> lambda checked=False, f=food: pet.feed(f)` @72；`triggered -> lambda checked=False, k=key: pet.set_user_form(k)` @86；`triggered -> lambda checked=False, rid=r.get('id'): pet.apply_role(rid)` @100 | 已接线 |
| pet_menu.py:103 | 导入角色… | role_import_act | 是 | `triggered -> lambda : pet_dialogs.open_resource_manager(pet, 0)` @104 | 已接线 |
| pet_menu.py:106 | 📦 导出角色包… | role_export_act | 是 | `triggered -> lambda checked=False: pet._export_role()` @107 | 已接线 |
| pet_menu.py:108 | 📦 导入角色包… | bundle_import_act | 是 | `triggered -> lambda checked=False: pet._import_role_bundle()` @109 | 已接线 |
| pet_menu.py:111 | 💰 记账 | book_menu | 不需要 | —（addMenu 返回子菜单容器） | 无缺陷：子菜单 |
| pet_menu.py:112 | 查询余额 | balance_act | 是 | `triggered -> pet.balance.fetch` @113 | 已接线 |
| pet_menu.py:114 | 📊 余额挂件 | badge_act | 是 | `toggled -> pet._set_badge` @117 | 已接线 |
| pet_menu.py:119 | 📒 账本… | ledger_act | 是 | `triggered -> pet.balance.open_ledger` @120 | 已接线 |
| pet_menu.py:121 | ✏️ 记一笔… | manual_act | 是 | `triggered -> pet.balance.add_manual_record` @122 | 已接线 |
| pet_menu.py:124 | 💸 今日预算… | budget_act | 是 | `triggered -> pet.balance.set_budget` @125 | 已接线 |
| pet_menu.py:126 | 🚨 余额预警… | bal_alert_act | 是 | `triggered -> pet.balance.set_balance_alert` @127 | 已接线 |
| pet_menu.py:129 | 📦 资源管理… | res_act | 是 | `triggered -> lambda : pet_dialogs.open_resource_manager(pet, 0)` @130 | 已接线 |
| pet_menu.py:132 | ⚙️ 设置… | set_menu | 不需要 | —（addMenu 返回子菜单容器） | 无缺陷：子菜单 |
| pet_menu.py:133 | 🖱️ 跟随鼠标 | pet._follow_act | 是 | `toggled -> pet.wander.set_follow` @136 | 已接线 |
| pet_menu.py:137 | 🚶 散步 | pet._wander_act | 是 | `toggled -> pet.wander.set_wander` @140 | 已接线 |
| pet_menu.py:142 | 🎨 气泡样式… | bubble_style_act | 是 | `triggered -> lambda : pet_dialogs.open_bubble_style(pet)` @143 | 已接线 |
| pet_menu.py:145 | 🖱️ 透明区穿透 | ct_act | 是 | `toggled -> pet._set_click_through` @148 | 已接线 |
| pet_menu.py:150 | 🎞️ 帧数上限… | fm_act | 是 | `triggered -> lambda : pet_dialogs.set_frame_max(pet, self._save_cfg)` @169 | 已接线 |
| pet_menu.py:152 | 🌀 物理参数… | phys_param_act | 是 | `triggered -> lambda : pet_dialogs.open_physics(pet)` @153 | 已接线 |
| pet_menu.py:155 | 🎤 语音设置… | voice_act | 是 | `triggered -> lambda : pet_dialogs.open_voice(pet)` @156 | 已接线 |
| pet_menu.py:158 | 🧩 行为设置… | beh_act | 是 | `triggered -> lambda checked=False: pet._open_behavior_dialog()` @159 | 已接线 |
| pet_menu.py:161 | 🎙 启动配音后端 | vstart_act | 是 | `triggered -> lambda checked=False: pet._menu_start_voice_backend()` @162 | 已接线 |
| pet_menu.py:164 | 😴 待机设置… | idle_act | 是 | `triggered -> lambda checked=False: pet._open_idle_dialog()` @165 | 已接线 |
| pet_menu.py:167 | ⏰ 闹钟… | alarm_act | 是 | `triggered -> lambda checked=False: pet._open_alarm_dialog()` @168 | 已接线 |
| pet_menu.py:170 | 🎵 音效设置 | snd_set | 不需要 | —（addMenu 返回子菜单容器） | 无缺陷：子菜单 |
| pet_menu.py:173 | 默认音效 | grp_def | 是 | `triggered -> lambda checked=False: pet._set_sound_group('default')` @176 | 已接线 |
| pet_menu.py:178 | 自定义音效组 | grp_cus | 是 | `triggered -> lambda checked=False: pet._set_sound_group('custom')` @181 | 已接线 |
| pet_menu.py:184 | 管理音频片段… | snd_manage_act | 是 | `triggered -> lambda : pet_dialogs.open_resource_manager(pet, 1)` @185 | 已接线 |
| pet_menu.py:186 | 💬 自定义台词… | lines_act | 是 | `triggered -> lambda : pet_dialogs.open_lines(pet)` @187 | 已接线 |
| pet_menu.py:189 | 🚀 开机自启 | pet._autostart_act | 是 | `toggled -> pet._set_autostart` @192 | 已接线 |
| pet_menu.py:193 | 🔑 设置DeepSeek API Key | key_act | 是 | `triggered -> pet.ai.set_api_key` @194 | 已接线 |
| pet_menu.py:195 | 🧹 清除DeepSeek API Key | clear_key_act | 是 | `triggered -> pet.ai.clear_api_key` @196 | 已接线 |
| pet_menu.py:198 | 🤖 AI设置… | ai_set_act | 是 | `triggered -> pet.ai.open_ai_settings` @199 | 已接线 |
| pet_menu.py:200 | 🧠 对话记忆… | mem_act | 是 | `triggered -> pet.ai.set_chat_rounds` @201 | 已接线 |
| pet_menu.py:202 | 🧹 清理日志… | clear_logs_act | 是 | `triggered -> pet._clear_logs` @203 | 已接线 |
| pet_menu.py:206 | 🧩 插件管理… | plugin_act | 是 | `triggered -> lambda checked=False: pet_dialogs.open_plugins(pet)` @207 | 已接线 |
| pet_menu.py:211 | 🎭 动作 | act_menu | 不需要 | —（addMenu 返回子菜单容器） | 无缺陷：子菜单 |
| pet_menu.py:212 | 原地小跳 | jump_act | 是 | `triggered -> lambda checked=False: pet.actions.play_action('jump', force=True)` @213 | 已接线 |
| pet_menu.py:215 | — | a | 是 | `triggered -> lambda checked=False, k=_arg: pet.actions.play_action('emote', k, force=True)` @216；`triggered -> lambda checked=False, n=_name: pet.actions.play_action(n, force=True)` @224 | 已接线 |
| pet_menu.py:223 | — | a | 是 | `triggered -> lambda checked=False, k=_arg: pet.actions.play_action('emote', k, force=True)` @216；`triggered -> lambda checked=False, n=_name: pet.actions.play_action(n, force=True)` @224 | 已接线 |
| pet_menu.py:228 | 🐡 变身 | tf_act | 是 | `triggered -> lambda checked=False: pet._do_transform()` @229 | 已接线 |
| pet_menu.py:231 | ❤️ 夸夸她 | praise_act | 是 | `triggered -> lambda checked=False: pet.mood.blush()` @232 | 已接线 |
| pet_menu.py:233 | ☀️ 今日天气 | weather_act | 是 | `triggered -> pet.weather.fetch` @234 | 已接线 |
| pet_menu.py:235 | 📍 天气城市… | city_act | 是 | `triggered -> pet._set_city` @236 | 已接线 |
| pet_menu.py:237 | 🖥️ 系统状态 | cpu_act | 是 | `triggered -> pet.actions.show_system_status` @238 | 已接线 |
| pet_menu.py:239 | ℹ️ 关于 | about_act | 是 | `triggered -> pet._about` @240 | 已接线 |
| pet_menu.py:242 | ⏹ 退出 | quit_act | 是 | `triggered -> pet._quit` @243；`triggered -> self._quit` @1211 | 已接线 |
| 桌宠.py:1207 | 🐟 显示桌宠 | show_act | 是 | `triggered -> self._show_pet` @1208 | 已接线 |
| 桌宠.py:1210 | ⏹ 退出 | quit_act | 是 | `triggered -> pet._quit` @243；`triggered -> self._quit` @1211 | 已接线 |

---

## 3. 反证与假阳性排除（"允许误报，但每条都要有证据"）

### 3.1 2.1 里 15 个 QCheckBox **不是**缺陷：它们是状态输入，保存路径逐个 isChecked()

| 控件（创建行） | 变量 | 读取处（真源码） | 用途 |
|---|---|---|---|
| 控件（创建行） | 变量 | 读取处（真源码） | 用途 |
|---|---|---|---|
| `pet_dialogs.py:1160` | `self._adv_rmbg` | : 1537  `"remove_bg": self._adv_rmbg.isChecked(),` | 导入选项 remove_bg |
| `pet_dialogs.py:1162` | `self._adv_trim` | : 1538  `"trim": self._adv_trim.isChecked(),` | 导入选项 trim |
| `pet_dialogs.py:1164` | `self._adv_keep` | : 1539  `"keep_source": self._adv_keep.isChecked(),` | 导入选项 keep_source |
| `pet_dialogs.py:1713` | `self._ck_sleep_form` | : 1815-1821 循环：for _flag, _ck in (("sleep_form", self._ck_sleep_form), ...) → _ck.isChecked() @1818   | 形态标记 sleep_form |
| `pet_dialogs.py:1714` | `self._ck_transform_form` | : 1816（同一循环的元组项）→ _ck.isChecked() @1818   | 形态标记 transform_form |
| `pet_dialogs.py:1715` | `self._ck_no_feed` | : 1817（同一循环的元组项）→ _ck.isChecked() @1818   | 形态标记 no_feed |
| `pet_dialogs.py:2715` | `self._ck_enabled` | : 2807  `_enabled = self._ck_enabled.isChecked()` | 闹钟启用 |
| `pet_dialogs.py:2966` | `self._tools_confirm` | : 3090  `"ai_tools_confirm": self._tools_confirm.isChecked(),` | AI 工具写入前确认 |
| `pet_dialogs.py:2977` | `self._rag` | : 3091  `"ai_rag_enabled": self._rag.isChecked(), # v2.4：隐私开关（此前只有键没有入口）` | 隐私开关 ai_rag_enabled |
| `pet_dialogs.py:4700` | `self._ceil` | : 4719  `"ceilingBounce": self._ceil.isChecked()}` | 物理 ceilingBounce |
| `pet_dialogs.py:4778` | `self._en` | : 5358  `"enabled": self._en.isChecked(),` | 语音总开关 |
| `pet_dialogs.py:4781` | `self._daily` | : 5363  `"speak_daily": self._daily.isChecked(),` | 日常台词也用配音 |
| `pet_dialogs.py:4908` | `self._lauto` | : 4967  `"auto_start": self._lauto.isChecked(),` | 后端 auto_start |
| `pet_dialogs.py:4910` | `self._lkill` | : 4968  `"kill_on_exit": self._lkill.isChecked(),` | 后端 kill_on_exit |
| `pet_dialogs.py:5484` | `self._resume` | : 5620  `"idle_resume_on_interrupt": self._resume.isChecked(),` | 待机 idle_resume_on_interrupt |

QCheckBox 是**状态输入**而非动作按钮：状态由保存路径主动读 .isChecked()，不需要 clicked.connect（除非要联动别的控件——本仓确有 4 处联动：:1153 → :1159 toggled、:1166 → :1191 toggled、:2963 → :2969 toggled，以及 :1716 的 for _ck in (…) 批量初始化）。

### 3.2 "接到不存在的方法"与"handler 体死路"：**0 条**

- **120** 条 self.<m> 形式的 connect，全部在**声明类**（含基类递归、含 Qt 内建白名单）里找到同名方法 → 0 条悬空。
- **53** 个菜单 handler（pet.ai.talk / pet.balance.fetch / pet._set_physics / …）逐个回查 pet_services.py 的服务映射与 桌宠.py 的 PetWindow，**全部存在**。
- handler 体为"只有 docstring / 只有 pass / 只 return 常量"的 **0** 条。
- 扫描器最初报的 67 条 "UNRESOLVED" 是**我自己的假阳性**，逐条查证后全部排除：self.accept / self.reject / setEnabled / deleteLater（Qt 内建）、_cb / cb / on_value（函数形参）、on_frame(pet_anim.py:149) / _on_default_device_changed(pet_audio.py:195)（嵌套 def）。

### 3.3 反向情况："接了但 UI 上没有入口"

- **install_path（本轮点名的例子）已经是修好的状态，不是遗留缺陷。**
  pet_dialogs.py:6477 def install_path(self, path) ← :6470 def _install(self) ← :6030 self._btn_install_file.clicked.connect(lambda checked=False: self._install())，
  且 :6014-6019 的注释写明了 v2.6.0 第 4 轮 P1-1 把「安装…（选本地包）」入口加回来的原因（v2.5.1 曾让 _install() 失去调用点）。**判定：已接线、有 UI 入口。**
- 全仓"名字在**产品代码里零引用**"的定义共 39 个（_dev/dead10.json）。排除 Qt 事件回调（mousePressEvent / wheelEvent / nativeEvent / paintEvent 由 Qt 调）与**字符串派发**（见下）后，UI 模块只剩 1 条真正可疑：
  - **pet_dialogs.py:5708 open_idle(pet)** —— docstring 自称"待机设置对话框入口（菜单也走 pet._open_idle_dialog）"，但全仓只有 tests/test_dialogs_more_v24.py 提到它，菜单走的是 PetWindow._open_idle_dialog。**判定：可疑（死入口），P3，需人工确认后决定删或接。**
- **字符串派发必须排除**：pet_dialogs._call(pet, name, …)(:280) 用 getattr 按名字调用，共 22 处（:3093 apply_ai_settings、:4720 apply_physics、:5373 apply_voice、:3075 clear_long_term_memory、:3294/:3329 apply_role …）。所以 apply_voice / apply_physics / apply_ai_settings 这类"零引用"**是活的**，不能报成死代码。

---

## 4. 任务 2：角色绑定为什么只剩「（不绑定）」

### 4.1 下拉在哪（唯一定位）

全仓含「不绑定」字面量的地方**只有一处**：`pet_dialogs.py:5139 out = [("", "（不绑定）")]`。

- 控件：QComboBox cb，:5160-5163 填充，逐槽位一行，行在 QFormLayout 里（:5176 self._bind_form.addRow(label, row)）。
- 只有它属于**「语音设置 → 角色绑定」页**：VoiceDialog._build_bind_tab()(:5117) → _refresh_bindings()(:5147) → 每个槽位一个下拉。
- 对照：LinesDialog._voice_items()(:4068) 的占位文案是**「（跟随角色绑定）」**(:4069)，字面量不同；导出流程里的选声音素材是**勾选列表**不是下拉（_VoicePickDialog:5717、pick_voice_assets:5817），里面**没有**「不绑定」这一项。
- 入口链：pet_dialogs.open_voice(pet)(:5630) → VoiceDialog(pet)(:5633)；菜单 pet_menu.py:155「🎤 语音设置…」。

### 4.2 数据来源（自下而上）

| 层 | 位置 | 内容 |
|---|---|---|
| 索引文件 | <DATA_DIR>/voice_assets.json（pet_resources.py:1565） | {"assets":[{id,name,file,ext,added,duration}…]} |
| 素材目录 | <DATA_DIR>/voice_ref/（pet_resources.py:1564） | 真实参考音文件 |
| 服务 | VoiceAssetLibrary._load()（pet_resources.py:1571-1594）→ assets()（:1623） | 构造时**一次性读盘**；assets() 返回内存副本 |
| 服务产地 | pet_services.py:151 pet.voice_assets = pet_resources.VoiceAssetLibrary(data_dir)（**唯一产地**；桌宠.py:2482 那处只在"导入回滚"时重建） | |
| 面板取值 | pet_dialogs.py:4748 self._assets = _get(parent, "voice_assets") | |
| 填充 | :5138 _asset_items() → :5141 for a in (self._assets.assets() if self._assets is not None else []) → :5142 out.append(…) → :5162-5163 cb.addItem(text, val) | |
| 当前绑定 | :5153 cur = self._svc.bindings()（cfg["voice"]["bindings"]，槽位→素材 id） | 用于选中项；_want 已失效时**会**加「（已失效：…）」占位(:5165-5167) |

### 4.3 "为什么只剩一项"：三个假设的判定

| 假设 | 判定 | 证据 |
|---|---|---|
| **H3 填充代码在 v2.5.0/v2.6.0 重构里丢了**（与导出那条同病） | **否（已排除）** | git log -L 5128,5180:pet_dialogs.py 与 git log -S "_asset_items" / -S "（不绑定）" 都**只命中 f5c35e1（v2.1.0）**：该函数自 v2.1.0 引入后再没被任何提交改过（v2.5.0 B / v2.6.0 的改动都没碰这段）。代码在、填充在、addItem 在。 |
| **H1 数据源为空**（没导入过参考音 / 索引文件不存在） | **能复现出用户看到的原样界面** | 探针 A：空数据目录 → assets() = [] → _asset_items() = **[('', '（不绑定）')]**（与用户描述逐字一致） |
| **H2 过滤条件把素材全筛掉** | **成立但需特定数据**：_load() 的 :1584 if ext not in self._EXTS: continue（_EXTS = (".wav", ".mp3")）会**静默丢弃** ext 缺失或非 wav/mp3 的条目 | 探针 C：3 条（无 ext / m4a / .wav）→ assets() 只剩 1 条；探针 D：两条都无 ext → assets() = [] → 下拉**只剩「（不绑定）」** |

**最小复现**（只读、临时目录、python -B；用的是 pet_dialogs.py 里 _asset_items 的**真实源码**（AST 抽取后 exec）+ 真实 VoiceAssetLibrary）：

~~~~
== A. empty data dir ==
   voice_assets.json exists: False
   lib.assets() = []
   _asset_items() = [('', '（不绑定）')]          <-- 用户看到的界面就是这个

== B. normal import path (valid .wav via import_file) ==
   import_file -> 3f4a1773_1791796016 err= None
   index on disk: {"assets":[{"id":"...","name":"测试音色","file":"....wav","ext":".wav",...}]}
   reload assets() = ['测试音色']
   _asset_items() = [('', '（不绑定）'), ('3f4a1773_1791796016', '测试音色')]   <-- 正常路径是好的

== C. hand-written index whose entries lack a legal ext ==
   raw entries on disk: 3 (no-ext / m4a / .wav)
   lib.assets() = [('ccc333', '正常 wav')]        <-- 2 条被 _load 静默丢弃
   _asset_items() = [('', '（不绑定）'), ('ccc333', '正常 wav')]

== D. all entries lack ext (worst case) ==
   lib.assets() = []
   _asset_items() = [('', '（不绑定）')]           <-- 同样只剩一项
~~~~

### 4.4 证据链（一句话版）

菜单「🎤 语音设置…」→ VoiceDialog(pet)(:5633) → _build_bind_tab(:5117) → _refresh_bindings(:5147) → 每槽位 QComboBox 填 _asset_items()(:5138) → self._assets.assets()(:5141) → VoiceAssetLibrary(pet_services.py:151) → 读 <DATA_DIR>/voice_assets.json(pet_resources.py:1565) **且用 :1584 的 ext 白名单过滤**。
**只要这个文件不存在 / 条目被 :1584 全部滤掉 / self._assets 为 None，下拉就恰好只有「（不绑定）」一项**，而且三种情况在界面上**长得一模一样**——因为 :5143 的 except Exception: pass 把原因也吞了。

### 4.5 本轮**不能**确定的部分（需人工确认，不猜）

- 用户的 <DATA_DIR>/voice_assets.json 我**没读到**：整个 E:\deep seek 递归搜 voice_assets.json **0 个命中**、voice_ref/ 目录 **0 个**（仓库根只有 ledger.json / ledger_archive.json / roles.json；%~APPDATA%~大肥鱼桌宠 不存在）。所以用户实际是 H1（库为空）还是 H2（条目被 ext 过滤）**无法在本机判定**——绿色版目录按任务要求未碰。
- 判据给下一轮：让用户提供 <DATA_DIR>/voice_assets.json（该文件不存在 ⇒ H1；存在但 assets 数组里条目的 ext 不是 .wav/.mp3 ⇒ H2）。
- 代码侧交叉验证：产品代码里**唯一的写入路径** VoiceAssetLibrary.import_file()(:1690-1698) 一定会写 ext，_apply_imported_voice_assets(桌宠.py:2361) 也走 import_file → **H2 只可能来自手改 / 外部工具写的历史文件**；H1（从未导入过素材）是我目前更倾向的解释（**倾向 ≠ 结论，仍标需人工确认**）。

---

## 5. 给下一轮的修复清单（按严重度排序）

### P1

| # | 文件:行号 | 现象 | 根因 | 建议修法 | 需要的验收（能真失败的用例） |
|---|---|---|---|---|---|
| P1-1 | pet_dialogs.py:5809、:5810 | 导出角色时"继续导出 / 取消"两个按钮点了没反应，modal(dlg) 关不掉窗口 → **导出角色包完全不可用（必现）** | v2.5.0 B 把「角色信息」框抽成 build_role_meta_dialog()(:5785) 时把两条接线丢了；只剩 row.addWidget(…)(:5811-5812) | 在 :5812 后补 btn_ok.clicked.connect(dlg.accept) 与 btn_cancel.clicked.connect(dlg.reject)（与 _VoicePickDialog:5750/5752 同款）；可顺带 btn_ok.setDefault(True)（现状连回车也触发不了：build_role_meta_dialog 里**没有** setDefault，对比 _VoicePickDialog:5749） | ① 点「继续导出」→ 断言 dlg.result() == QDialog.DialogCode.Accepted 且 pick_role_meta 返回 4 字段 dict；② 点「取消」→ 断言 Rejected 且返回 None；③ **变异**：把两条 connect 注释掉 → ①②必须**红**（可无头跑：QPushButton.click() 不需要 show） |

### P2

| # | 文件:行号 | 现象 | 根因 | 建议修法 | 需要的验收（能真失败的用例） |
|---|---|---|---|---|---|
| P2-2 | tests/test_dialog_fit_v250.py（整份）、tests/helpers_dialog_fit_v250.py:109-147（20 个窗口清单） | 尺寸契约覆盖了 build_role_meta_dialog（:143）却**只量几何**；全仓唯一一处按钮点击用例是 tests/test_plugin_market_v252.py:1144 → 这一类缺陷**零用例覆盖** | 契约口径只定义"窗口不超屏 / 能滚到底 / 按钮可见"，从未定义"按钮点得动" | 新增**通用**契约用例（建议 tests/test_dialog_buttons_wired_v270.py）：AST 扫 pet_dialogs.py 每个 QPushButton/QToolButton 构造点，断言"有 .clicked/.toggled 接线（含别名/跨方法）**或**在显式白名单里（白名单项必须写一句为什么不需要接线）"；再在 20 个工厂上各加一条"至少有一个动作按钮被接线"的断言 | ① 注释掉 :5809/:5810 的两条 connect → 通用契约**红**；② 把 15 个 QCheckBox 从白名单删掉 → **红**（证明白名单真在生效）；③ 照 tests/test_plugin_market_v252.py:1144 那种"**走按钮自己的 clicked 连接**"的写法给「继续导出」补一条端到端断言 |
| P2-3 | pet_dialogs.py:5138-5145（_asset_items）→ :5160-5163 | 素材库为空时角色绑定下拉**只剩「（不绑定）」**，和"填充坏掉"长得一样；用户直接问"怎么只有不绑定的选项" | 空态与故障态不可区分；:5143 except Exception: pass 把异常也吞了；该页没有"还没有素材，去导入"的提示与入口（「管理声音素材…」按钮在另一个页签） | ① :5143 改成先 pet_log.log_error(…) 再按原契约返回（对齐 v2.4 静默 except 审计口径）；② 空态时在下拉旁加提示 +「去导入参考音…」按钮（复用 :5109 _open_assets）；③ 回归 :5165-5167 的「（已失效：…）」占位 | 素材库为空 → 断言下拉 count()==1 **且**提示文案存在（现在会红）；注入一个会抛异常的 _assets → 断言 error.log 出现一条日志（现在会红） |

### P3

| # | 文件:行号 | 现象 | 根因 | 建议修法 | 需要的验收（能真失败的用例） |
|---|---|---|---|---|---|
| P3-4 | pet_resources.py:1581-1585 | voice_assets.json 里 ext 缺失 / 非 wav-mp3 的条目被**静默丢弃**（探针 C/D 实测：3 条只剩 1 条、2 条全没） | if ext not in self._EXTS: continue  # 非法扩展名残留项丢弃 —— 没有日志、没有占位项，用户只看到下拉变空 | 丢弃时记一条 pet_log.log_error（带 id/name/ext）；或对 ext 缺失但 file 有扩展名的条目**回填** ext 再判 | 构造 3 条（无 ext / m4a / .wav）→ 断言 assets() 长度按设计 **且** error.log 有 2 条丢弃记录（现在会红） |
| P3-5 | pet_dialogs.py:5708 open_idle() | docstring 自称"待机设置对话框入口"，实际**只有测试直接调**，菜单走 PetWindow._open_idle_dialog | v2.1 起菜单改造后遗留的死入口 | 二选一：删掉（并在 _dev 小账登记）或让菜单走它；**动手前先确认不是绿色版 / 插件的外部入口** | 若决定删：用例断言 pet_dialogs 不再有该名字（或断言菜单路径唯一） |
| P3-6 | pet_dialogs.py:2388 / 2726 / 4163 / 4361 / 5466 | 这 5 处按钮**文案是循环变量**（QPushButton(_label)），静态只能确认"接了 _cb"，确认不了每个文案是否都该有动作 | 无缺陷，属审计盲区 | 下一轮若要更严：把循环项表提成模块级常量，或用例断言"循环项数量 == 分支数" | 契约用例断言按钮数与循环项数一致 |

---

## 6. 复现方式（只读）

~~~~powershell
# 1) 按钮接线审计（AST：方法作用域 + 别名/容器/返回值/跨方法追踪）
python -B %TEMP%\pet_audit\scan6.py      # 产物：%TEMP%\pet_audit\audit.json
python -B %TEMP%\pet_audit\scan7.py      # 菜单 / QAction + handler 存在性
python -B %TEMP%\pet_audit\scan11.py     # self.<m> 精确回查声明类与基类
python -B %TEMP%\pet_audit\scan10.py     # 产品代码零引用定义（反向"无入口"）

# 2) 角色绑定空下拉最小复现（真实源码 + 真实库，临时目录，不留痕）
python -B %TEMP%\pet_audit\probe_binding.py

# 3) 手工复核（本轮实际用过的两条）
git -C "E:\deep seek\desktop-pet" log --oneline -S "_asset_items" -- pet_dialogs.py   # 只命中 f5c35e1(v2.1.0)
git -C "E:\deep seek\desktop-pet" log --oneline -L 5128,5180:pet_dialogs.py           # 该段自 v2.1.0 未被改过
~~~~

**本轮限制（诚实声明）**：

1. 我**没有跑 GUI**（不启动 Qt）：所有"按钮点了会怎样"的结论都基于源码 + Qt 语义推断。需人工确认的点：btn_ok 未 setDefault（连回车也触发不了）；Esc / 标题栏 × 按 _FitDialog(:786 只覆写 showEvent) 推断**仍可关闭**——未实测。
2. 用户的真实 <DATA_DIR>/voice_assets.json 不在本机可读范围（E:\deep seek 全盘搜 0 命中），H1/H2 的最终归属**需用户数据确认**；绿色版目录按要求未碰。
3. 绿色版目录、tests/、_dev/、任何产品代码**均未修改**；唯一写入 = 本文件。
