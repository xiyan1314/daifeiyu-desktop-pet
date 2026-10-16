# P8 证据侧 · 回报（v2.10.0 发版轮）

## 1. 逐条：编号 | 文件:行 | 改前 → 改后

| 编号 | 文件:行 | 改前 → 改后 |
|---|---|---|
| **E4** | `_dev/mutations_agent_a_v2110.json`（24 处，每处插在该条 `tests` 之后） | 24 条**没有任何** `expect_fail` 键 → 24 条各带点名（共 **29 个 nodeid**）；615 → 692 行，`git diff --numstat` = **77 插入 / 0 删除**，其余字节一个没动（先用 `git show HEAD:` 取回原始 615 行再插入） |
| **C-12** | `tests/test_feedback_host_v270.py:103-126`（新增） | 无 → 新增 `@pytest.fixture(autouse=True) def bubble_style_back()`：进入时快照 `dict(main.BUBBLE_STYLE)`，`finally` 里原样复原（断言在用例体哪一步红都复原）；26 插入 / 0 删除 |
| **C-03①** | `_check_release.py:818` | `# …只覆盖 MUTATION_FINGERPRINT_FILES 那 28 个键，而` → `# …那 29 个键` ＋新增一行 `# （v2.11.0 补齐 pet_motion.py 之后逐项数过：27 个产品模块 + 那 2 个测试文件 = 29），而`（2 插入 / 1 删除，只动注释） |

## 2. E4 单独一张表（24 条）

| 变异 id | 它改坏了什么 | 我点名的 nodeid | 我凭什么推出来的（一句话） |
|---|---|---|---|
| `M-A2110-01-press-scale-returns` | 按下写了 squash_x/y + _apply_transform()（几何变了；还会把在播的呼吸相位打回 1.0） | `tests/test_motion_v2110.py::test_press_outline_appears_and_geometry_is_untouched`<br>`tests/test_motion_v2110.py::test_press_does_not_fight_an_inflight_breathing_animation` | 前者比几何五元组、后者比 squash 快照——两处都直接读这个变异写的那些字段 |
| `M-A2110-02-hover-scales` | 悬停写了 squash 1.06 + _apply_transform() | `tests/test_motion_v2110.py::test_hover_glow_does_not_change_geometry` | 该用例只有一条几何比对（hover 期间五元组必须不变） |
| `M-A2110-03-ripple-leaks-item` | _retire_overlay 不 removeItem → 绘制项留在场景里 | `tests/test_motion_v2110.py::test_ripple_returns_scene_to_baseline`<br>`tests/test_motion_v2110.py::test_petting_spawns_one_string_of_hearts_that_retire` | 两条各自断言对象数回基线：涟漪桶一条、心形桶一条，收尾走的是同一个函数 |
| `M-A2110-04-ripple-ignores-reduce-motion` | 涟漪开关判定写死 animation_enabled(False) | `tests/test_motion_v2110.py::test_every_animation_point_is_covered_by_the_switch` | 该用例第③条：减少动效下 _spawn_ripple 必须返回 None 且场景项数不变 |
| `M-A2110-05-edge-instant-move` | _slide_to 换成 self.move(x, y)（瞬移） | `tests/test_motion_v2110.py::test_edge_slide_eases_to_the_old_target` | 该用例第一条硬断言就是 _slide_anim is not None（贴边还是瞬移） |
| `M-A2110-06-edge-duration-hardcoded` | 贴边时长写死 900，绕过令牌表 | `tests/test_motion_v2110.py::test_edge_slide_eases_to_the_old_target` | 同一用例断言 duration() == pet_motion.DUR[EDGE] |
| `M-A2110-07-reduce-motion-not-instant` | duration_ms 在 reduce_motion 时返回 1（不再是 0） | `tests/test_motion_v2110.py::test_default_follows_system_and_never_downgrades`<br>`tests/test_motion_v2110.py::test_edge_slide_instant_when_motion_reduced` | 前者直接调 duration_ms(EDGE, True)==0；后者走 _snap_to_edge→_slide_to，ms>0 就会建动画对象 |
| `M-A2110-08-auto-downgrades-user` | system_value is None 时返回 True（替用户关掉动效） | `tests/test_motion_v2110.py::test_default_follows_system_and_never_downgrades` | 唯一断『读不到就保持开启』的那条（reduce_motion_enabled(auto, None) is False） |
| `M-A2110-09-drag-threshold-gone` | dist <= THRESHOLD_PX 改成 dist <= 0（阈值失效） | `tests/test_motion_v2110.py::test_drag_threshold_blocks_micro_moves` | 该用例走阈值内的 7px，然后断言窗口没动、_dragging/_moved 仍为 False |
| `M-A2110-10-drag-cursor-gone` | 拖拽态不设 ClosedHandCursor | `tests/test_motion_v2110.py::test_drag_cursor_states` | 该用例点名『拖拽中没有抓着光标』 |
| `M-A2110-11-double-click-second-release` | _suppress_release 置 False（不吞第二次 release） | `tests/test_motion_v2110.py::test_double_click_uses_the_event_and_swallows_the_second_release` | 该用例最后一段：双击后再来一次 release，pokes 必须仍是 [1] |
| `M-A2110-12-bubble-always-fades-in` | fresh 写死 True（已经在显示也走淡入） | `tests/test_motion_v2110.py::test_new_bubble_text_never_fades_in_over_old_one` | 新旧文本交替时 opacity 会从 0 重新淡起——该用例断言此刻必须 == 1.0 |
| `M-A2110-13-bubble-hold-zeroed` | 展示时长也随开关归零（BUBBLE_HOLD 传 _motion_reduced） | `tests/test_motion_v2110.py::test_bubble_fade_is_instant_when_motion_reduced` | 该用例断言 _timer.isActive() —— 归零后 QTimer.start(0) 不会起表 |
| `M-A2110-14-bubble-does-not-follow` | moveEvent 里不再 _position_bubble() | `tests/test_motion_v2110.py::test_bubble_follows_the_character_without_restarting_the_timer` | 该用例断言角色平移 (40,25) 后气泡位移逐像素相等 |
| `M-A2110-15-petting-no-hearts` | _start_petting 里不再 _spawn_hearts() | `tests/test_motion_v2110.py::test_petting_spawns_one_string_of_hearts_that_retire` | 该用例把 _spawn_hearts 换成计数器，断言 _start_petting 必须调到它一次 |
| `M-A2110-16-ai-inflight-invisible` | _sync_thinking 在途分支把 show() 改成 hide() | `tests/test_motion_v2110.py::test_ai_inflight_is_visible_and_survives_reduce_motion` | 该用例『AI 在途没有任何可见状态』就是这一支 |
| `M-A2110-17-contrast-palette-fails` | 浅色板 fg/border 改成 #eef1f6（浅字白底 ≈1.1:1） | `tests/test_motion_v2110.py::test_contrast_is_computed_not_eyeballed` | 该用例对两套板逐对算 contrast_ratio 并钉 ≥ 4.5:1 |
| `M-A2110-18-escape-does-nothing` | Esc 分支不再 close() | `tests/test_motion_v2110.py::test_keyboard_escape_and_enter_route_to_window_actions` | 该用例第一条断言 Esc 后 not win.isVisible()（另一条 Esc 用例断言的是光标/状态复位，不读可见性） |
| `M-A2110-19-reduce-toggle-not-persisted` | 勾选永远写 cfg[reduce_motion]=auto | `tests/test_motion_v2110.py::test_reduce_motion_toggle_persists_and_clears_inflight`<br>`tests/test_motion_v2110.py::test_tray_menu_carries_primary_action_and_toggles` | 前者读盘上必须是 on/off；后者断言勾选状态与 win.cfg[reduce_motion] 一致 |
| `M-A2110-20-high-contrast-no-restore` | 关掉高对比度时不把用户那份样式放回去（elif False） | `tests/test_motion_v2110.py::test_high_contrast_switch_applies_and_restores` | 该用例最后一句：关掉后 BUBBLE_STYLE[fg] 必须回到 before 的那份 |
| `M-A2110-21-emote-hidden-under-reduce` | 减少动效分支里立刻 _hide_emote（表情也不显示了） | `tests/test_motion_v2110.py::test_every_animation_point_is_covered_by_the_switch` | 该用例第⑤条：_show_emote 后 emote_item 必须 visible（表情是信息不是装饰） |
| `M-A2110-22-proc-action-ignores-reduce` | _play_proc 不再因减少动效提前收尾（改成 pass） | `tests/test_motion_v2110.py::test_proc_actions_are_covered_by_the_switch` | 该用例断言 0ms 语义：_tween_anim 不许是 Running（变异下它会跑 1200ms） |
| `M-A2110-23-lines-note-back-to-toast` | LinesDialog._note 改回 _toast(self._pet, text)（出口从状态行变成宠物气泡） | `tests/test_dialogs_feedback_v280.py::test_move_line_at_boundary_tells_the_user`<br>`tests/test_dialogs_feedback_v280.py::test_lines_move_member_at_boundary_uses_the_same_wording` | 两条都双面钉：状态行里有话 且 气泡为空——出口一换两面同时红 |
| `M-A2110-24-bubble-fadeout-not-instant` | 淡出时不传 _motion_reduced（仍走 180ms） | `tests/test_motion_v2110.py::test_bubble_fade_is_instant_when_motion_reduced` | 该用例第二半：减少动效下 _fade_anim 必须为 None |

（`tests/test_motion_v2110.py::test_x` 在正文里简写为 `test_x`。写这些点名时**没有**跑 pytest、**没有**读 `results` 里的红名单；该 spec 的 `results` 里有 2026-10-16 的历史红名单，我是**写完之后**才拿它做交叉核对，见 §6。）

## 3. 两条只读命令的原文读数

**改前（基线）**：
```
锚点合计 556 条，坏 0 条（坏 = 命中次数不是 1：源码改过，需要重锚）
  mutations_agent_a_v2110.json            锚点 24，坏 0
校验范围：mutations[].tests / mutations[].expect_fail —— 合计 1311 条，坏 0 条
（范围外历史记录 1243 条）
```
**改后（rc 均为 0）**：
```
锚点合计 556 条，坏 0 条（坏 = 命中次数不是 1：源码改过，需要重锚）      <- 与改前逐字一致
  mutations_agent_a_v2110.json            锚点 24，坏 0
  mutations_agent_a_v2110.json             nodeid  58 个，坏 0            <- 29 个 tests + 29 个 expect_fail
校验范围：mutations[].tests / mutations[].expect_fail —— 合计 1340 条，坏 0 条
（范围外历史记录 1243 条）
**校验范围内** nodeid 全部对得上 —— 可以进整批复跑
```
外加 `python -B _dev/check_mutation_ast.py`：**531 条变异，0 条锚点/语法问题**，rc=0。

⚠ **请同步更新文档读数**：`_dev/README.md` 与 `_release_notes_v2110.md` 现写「校验范围内 **1311** 条」（本题 +29）；那是 P2/P1 的领地，我没动。

## 4. 我改了哪些**指纹清单**里的文件（明确点名）

| 文件 | 在不在 `MUTATION_FINGERPRINT_FILES`（29 个键） | 后果 |
|---|---|---|
| **`_check_release.py`** | **在（第 6 项）** | **我改了它 → 指纹漂，这是预期的**。现树 `_check_release.py` = `dca4541e2829`；盘上 33 份证据记的是 `7377b3fad58e` → 整批回写后刷新 |
| `tests/test_feedback_host_v270.py` | **不在**（清单里只有 `test_dialog_buttons_v270.py` / `test_import_thread.py`） | 文件指纹通道**不会**报它 |
| `_dev/mutations_agent_a_v2110.json` | 不在（`_dev/` 从来不在清单里） | — |

⚠ 但 `tests/test_feedback_host_v270.py` **有另一条通道会出声**：它的两个 pinned 用例（`test_move_line_at_boundary_tells_the_user` / `test_lines_move_member_at_boundary_uses_the_same_wording`）的用例体摘要记在 `mutations_agent_a_v2110.json` 的 `pinned_ast` 段里 —— 我**只在文件里新增了一个夹具**、用例体一字未动，所以摘要**不变**；整批复跑会照常重算这一段。可逆性：既没改也没删任何既有 fixture（`cfg_back` 原样保留）。

## 5. 没做到的

1. **「24/24 仍 CAUGHT」我没验**（按铁律归安静窗口的整批）。我做的是前置证明：写进去的 29 个 nodeid 都是 `tests` 里真实存在的用例（nodeid 体检 58 个 / 坏 0），且每条变异至少点名一条自己 `tests` 里的用例。
2. **C-12 与 C-03① 一次测试都没跑**（不许跑全量 pytest；也不该在这个多写入者的窗口里跑）。两处只做了静态可解析性验证（`ast.parse` 通过）→ 按本仓口径：**已改，未实测**。
3. **`tests/test_release_check.py:431` 有一句同款过期注释**「文件指纹只覆盖 **28** 个键」——不在我的三份独占文件里 → **没动，仅点名**，请派给该文件写入者。
4. `_dev/fingerprint_coverage_v2100.md`（C-03②）与 `_dev/b3_submit_model_v290.md`（C-03③）不在我的范围 → 没动。

## 6. 交叉核对（写完之后做的，不是来源）

把 §2 的 29 个点名与该 spec `results`（2026-10-16 09:27:46）里记的 `failed` 列表逐条比：**24/24 条变异的点名全部落在当年红名单里，0 条多余、0 条遗漏**（含 01/03/07/19/23 这 5 条各红 2 条的）。含义：这次收紧**不会**把任何一条从 CAUGHT 变成 WRONG TEST —— 真正读数仍以整批为准。
