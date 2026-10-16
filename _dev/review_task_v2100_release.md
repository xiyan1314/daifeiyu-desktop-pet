# v2.10.0 发版轮 · 三审任务书（找茬 / 质量 / 兼容）

> 写于 2026-10-16，第 10 轮末。**唯一真源**：`_dev/REMAINING.md`（v3）· 本轮任务书 `_dev/task_v2100_release_round.md` · 交接 `.agents/handoffs/2026-10-16-1430-dsh-main-r10-v2100-ready.md`。

## 零、冻结哈希（产品/测试侧，318 项）

> ⚠ **开工第一件事**：按本表逐位比对。**只要有一条不符 → 停手，报给派单的人，不许接着跑。**
> 表由 `git ls-files` 过滤 `.py/.md/.txt` 后逐文件取 `sha256[:12]` 生成。
> **不在表里的**：`_dev/**` 的大部分、以及工作树里未跟踪的新文件（它们是**证据侧与文档侧**）。
> **证据侧在「定版证据整批复跑」后会被改写 —— 那是预期，不是漂移**（见 `_dev/review_task_v2110.md` §零 的说明）。

```
46A286C4F69E  CHANGELOG.md
4C0347D472FB  README.en.md
7AF179E91129  README.md
3D84512BEC58  ROADMAP.md
DCA4541E2829  _check_release.py
6286F9F493BD  _check_static.py
2C906A8C7115  _dev/MASTER_CHECKLIST.md
1534F90B263A  _dev/README.md
B37092BB0647  _dev/VERIFY_DISCIPLINE.md
75F2895AD6FF  _dev/_mutate_lib.py
8C93BD51CF12  _dev/agent_c_v2100_report.md
1E4FF67E05D0  _dev/agent_c_v2110_report.md
EAAB086A5087  _dev/agent_c_v260_report.md
2D29BD3CF933  _dev/agent_c_v270_report.md
1F73E4AF5376  _dev/agent_c_v280_report.md
1DE30A3E6919  _dev/agent_c_v290_report.md
EE58029F25DA  _dev/asset_absence_report.md
268443E5AD76  _dev/audit_A_tier_review.md
7750A6A76A46  _dev/audit_behavior_assets_v290.md
0D8AD5D2F26A  _dev/audit_buttons_binding_v270.md
1DCA658AA7B2  _dev/audit_checklist_completeness_v280.md
1EE8293E862D  _dev/audit_feedback_v270.md
D9E2F9FD7AA2  _dev/audit_silent_except.py
4089017A29D7  _dev/audit_tautology_asserts_v2100.py
111C78D6BF11  _dev/b3_submit_model_v290.md
09117515A907  _dev/build_official_plugins.py
3C311FCCCFA6  _dev/check_mutation_ast.py
E5A9387816A6  _dev/check_mutation_nodeids.py
31868776CACB  _dev/check_pinned_ast.py
EAC31CE785F3  _dev/compare_export_baseline.py
9C35F89F6712  _dev/compare_startup_baseline.py
6AE98C05055D  _dev/coverage_recheck_v280.md
D9DAFF4F91B2  _dev/critic_mutation_output_v270.md
F83268FF080C  _dev/critic_round5_report_v270.md
78C83AB0D265  _dev/dialog_size_report.md
12E315B035C3  _dev/e2e_double_feed.py
A4FC113873CA  _dev/e2e_full_form.py
9CC2BCA52ABE  _dev/e2e_idle_and.py
F47EC56FDC4C  _dev/e2e_idle_or.py
FA71611D05AC  _dev/e2e_idle_v218.py
8591FE978B78  _dev/errors.md
9CBCA793D984  _dev/export_fingerprint.py
B93253247549  _dev/find_dup_claims.py
B0C4C0C7F4FD  _dev/find_dup_symbols.py
2097EA2F7E96  _dev/find_dup_tests.py
0B7AAD00C6A3  _dev/find_dup_tests_api.py
2B05BC355E6E  _dev/fingerprint_coverage_v2100.md
D4C16838C074  _dev/gen_full_idle_frames.py
F3D886B4E87B  _dev/mutate_batch_v270.py
61819A4BF8F9  _dev/mutate_check.py
C9C1D09E02FB  _dev/mutate_export_slice.py
9AF802AFDB6A  _dev/mutate_proc_reset_v26.py
91A0FC04CE37  _dev/mutate_startup_defer.py
A6C445621C26  _dev/parasite_plugin_study.md
1176F0A1BCC8  _dev/plan_v270_rounds.md
DBF0387FAB1D  _dev/plugin_format_v251.md
96A2FC66DA32  _dev/plugin_market_report_v260.md
12507D66E621  _dev/plugin_pack_rules.py
E7123E8C2295  _dev/plugin_packs_report.md
5473496ECE0D  _dev/probe_asset_absence.py
117EF10F4CC1  _dev/probe_autoscroll_v2110.py
D2CB541D2DFB  _dev/probe_bubble_z_order_v270.py
A8A2DE6FAB0B  _dev/probe_c_mutation_output_v270.py
220544758DD3  _dev/probe_c_v280_hang.py
5DC9CBBD1E11  _dev/probe_critic_mutation_output_v270.py
83B221EA92EB  _dev/probe_export_cost.py
D8638D424E19  _dev/probe_export_io.py
47D9B031777A  _dev/probe_fingerprint_gap_v260.py
535BA97B97D0  _dev/probe_fingerprint_gap_v290.py
6E57896C2661  _dev/probe_judge_error_lines_v2100.py
7905694D30F8  _dev/probe_l5_v251.py
3A46C81A9FDF  _dev/probe_money_preload_gap.py
499DB2F96248  _dev/probe_plugin_gap_v260.py
0CA64BC2CB64  _dev/probe_plugin_install_v251.py
D256621443AB  _dev/probe_plugin_landing_v251.py
1A0ABA2E8C77  _dev/probe_plugin_market_v260.py
104F42BAB319  _dev/probe_proc_reset_v26.py
9F1065C29EBC  _dev/probe_qt_anim_tick_v26.py
37987843914E  _dev/probe_qt_setcurrenttime_v26.py
E526DCECAC38  _dev/probe_singleshot_cancel_v26.py
6EBA8636F70B  _dev/probe_slot_resolution_v2110.py
E3CE1AE1E64B  _dev/probe_startup_cost.py
CE97B3C3FA3C  _dev/probe_test_order.py
6D986918715C  _dev/probe_ui_freeze.py
FA8F849B58B7  _dev/pytest_v242_full.txt
654DEA56A4F5  _dev/pytest_v243_full.txt
509835C28265  _dev/pytest_v244_full.txt
D7D4C9015B5E  _dev/pytest_v250_full.txt
34CF0622F686  _dev/pytest_v251_full.txt
E000D982B141  _dev/pytest_v260_full.txt
975B98015084  _dev/pytest_v261_full.txt
7A699C8092ED  _dev/qt_strip_report.md
1846167633D0  _dev/repro_4form.py
283E641FDC96  _dev/repro_default.py
DEA95FFFA547  _dev/repro_frame_freeze.py
E5B3BD931783  _dev/repro_full_user.py
56415A99E66C  _dev/repro_idle_actions.py
7FB28A12F28C  _dev/repro_io_conflict.py
0A6CFB0D49F7  _dev/repro_mood.py
1915EED4B750  _dev/repro_quiet.py
D83AED246DDE  _dev/review_task_v2110.md
194CD50720C4  _dev/review_task_v270.md
EA6E66AD3763  _dev/review_task_v280.md
1CC9BF5C5FE9  _dev/review_task_v290.md
85CBBC9B503E  _dev/silent_except_b_list.py
10743366F40A  _dev/silent_except_ctx.py
6704F1C5DFD6  _dev/silent_except_mutate.py
D9A3202EE5ED  _dev/silent_except_report.py
B3D3E2B4F5BB  _dev/silent_except_report_v252.md
729E0F4E6BD7  _dev/silent_except_whitelist.py
DE071AEBC7CD  _dev/task_fix_verify_v260.md
AA34824DB1CA  _dev/task_v2100_round.md
58EFB2CAAFBB  _dev/task_v2110_round.md
2651A2A297B6  _dev/task_v2120_round.md
08A4B37032C0  _dev/task_v244.md
469064FB9A97  _dev/task_v250.md
E41B45E728A2  _dev/task_v251.md
591F7E611421  _dev/task_v260.md
36B2E0E87BA6  _dev/task_v270.md
77FD1F408814  _dev/task_v270_round.md
94ADFA80BE6B  _dev/task_v280_round.md
EB4BAAFD48BF  _dev/task_v290_round.md
237024657A86  _dev/ui_freeze_report.md
FE57BDECF929  _dev/verify_ambient_settle_v26.py
7614687C6C0D  _dev/verify_d7a_v250_agent_c.py
97372311F9FB  _dev/verify_fastci_slices_v251.py
E53E5C60A8DC  _dev/verify_fix_batch_v260.md
5EFA2F2A4839  _dev/verify_guardrails_can_fail.py
FE875AB4F03F  _dev/verify_idle_settle_v26.py
B9811FD0332A  _dev/verify_plugin_packs_v251.py
021E5E8AA4B8  _dev/verify_proc_reset_cross_v26.py
33A9AE61F899  _dev/verify_services_ast_v250.py
F471EF143056  _release_notes_v154.md
B592C6B7F61B  _release_notes_v155.md
7078CD713307  _release_notes_v156.md
C1AC07F9E2DD  _release_notes_v160.md
04C345505148  _release_notes_v161.md
637CA952C953  _release_notes_v162.md
366B6A53F344  _release_notes_v200.md
004D7EAF4EBC  _release_notes_v201.md
4937CBDDD671  _release_notes_v202.md
5746E0E686AD  _release_notes_v203.md
5BC6642F5F57  _release_notes_v204.md
604D8CEF7DE4  _release_notes_v205.md
A4219C4F1A2B  _release_notes_v206.md
A0C2987DBFE3  _release_notes_v207.md
38FF40A00C95  _release_notes_v210.md
E4293957D33F  _release_notes_v2100.md
DA051589B15A  _release_notes_v211.md
6AE9EBB6E11C  _release_notes_v212.md
88428DDBDE0B  _release_notes_v213.md
B436CC274E34  _release_notes_v214.md
9E07804E1B07  _release_notes_v215.md
A3357D8B4C32  _release_notes_v216.md
1C100A269588  _release_notes_v217.md
6A86990BF898  _release_notes_v218.md
3915EF751718  _release_notes_v219.md
84948B5ACCFF  _release_notes_v220.md
DB1FD4112D2C  _release_notes_v221.md
607C73272759  _release_notes_v222.md
E2840ECB1165  _release_notes_v223.md
CA4D1A6FCB1F  _release_notes_v224.md
52543BFA5DD6  _release_notes_v225.md
8305114E1B30  _release_notes_v226.md
17585FB7E657  _release_notes_v227.md
5C56E1E25DC2  _release_notes_v230.md
57C9DF7A83AF  _release_notes_v231.md
06DDAD414AF5  _release_notes_v240.md
19623CFE71B6  _release_notes_v241.md
5AF22C050D6E  _release_notes_v242.md
0520BFBA3559  _release_notes_v243.md
EBBB5710C061  _release_notes_v244.md
38E830B95630  _release_notes_v250.md
5A548462F4CC  _release_notes_v251.md
2EB8FA4953DE  _release_notes_v260.md
D85E6E70969C  _release_notes_v261.md
213BE584FA33  _release_notes_v270.md
C905D1817CA9  _release_notes_v280.md
24E094ACE4DF  _release_notes_v290.md
76F163F53F40  _verify_green.py
5B28E5B04C1C  _verify_v13.py
8F424D8DEE57  docs/release-notes/_release_notes_v130.md
E0AC64E2F6D4  docs/release-notes/_release_notes_v131.md
673535250950  docs/release-notes/_release_notes_v132.md
C08D44A24B64  docs/release-notes/_release_notes_v133.md
532DF9DC0B11  docs/release-notes/_release_notes_v140.md
8F7CA1B74F12  docs/release-notes/_release_notes_v141.md
99764981EC3B  docs/release-notes/_release_notes_v142.md
B7BEC25EE4B7  docs/release-notes/_release_notes_v150.md
52EE12261B54  docs/release-notes/_release_notes_v151.md
0CA1D60676C2  docs/release-notes/_release_notes_v152.md
B37CC61A6E50  docs/release-notes/_release_notes_v153.md
ACFFB5B77AEE  gallery/README.md
613AA1B1896A  main.py
29892A65F129  pet_actions.py
A5989E7FE646  pet_ai.py
1149E94DEEE3  pet_alarm.py
730079AE9EC7  pet_anim.py
A6FEADF4D653  pet_audio.py
045129227EE2  pet_balance.py
732273F95FB4  pet_behaviors.py
098676AC52D4  pet_book.py
DE979C429C2C  pet_chat.py
B46E0F180880  pet_config.py
E5AB516B0A19  pet_dialogs.py
DB474BDD6670  pet_export.py
5CF36B395B70  pet_fx.py
6B1E0413FB7F  pet_io.py
5332F60B5F26  pet_lines.py
DE14ECF338AB  pet_log.py
8543CB499126  pet_main.py
44224C3320C6  pet_menu.py
613E017BFB02  pet_mood.py
4A99066986AE  pet_motion.py
F34C1527E4ED  pet_physics.py
2F7853298FC3  pet_plugin.py
82FB7B1384C8  pet_plugin_host.py
E5E9845785E8  pet_plugin_index.py
5D8DF41558DF  pet_resources.py
CF5874875535  pet_screen.py
ECEBB6AB5891  pet_services.py
46E9030D073F  pet_tools.py
3A9C9CC3324E  pet_voice.py
D3A3ADA02838  pet_wander.py
5BE7618260F6  pet_weather.py
B8DE517121E1  pet_widgets.py
E59D0F0B8706  plugins/README.md
FBD398081225  requirements-lock.txt
276C9B7D3197  requirements.txt
A3E47D16F7FC  tests/_probe_dialog_sizes.py
7A699DC5373F  tests/conftest.py
B31DEFCFA6F4  tests/helpers_deps_bounds.py
2F3EE862CC65  tests/helpers_dialog_fit_v250.py
33A257E70173  tests/helpers_roles.py
D632291BF1AB  tests/test_ai_write_first_v280.py
15C89E00C8C7  tests/test_alarm.py
0542376187C1  tests/test_anim.py
E72139BC717C  tests/test_anim_slice_v241.py
5403C56D015E  tests/test_api_errors.py
227911FC3C7A  tests/test_assertion_strength_v2100.py
43BF10904BEC  tests/test_asset_absence_v244.py
A550E7A99912  tests/test_balance_feedback_v280.py
767C2B47A0EC  tests/test_behavior_v290.py
A86342FAEF1B  tests/test_behaviors.py
41FA5CB748C5  tests/test_behaviors_v21.py
73043F748044  tests/test_book.py
1EFB1003D2A9  tests/test_book_date_recover_v24.py
D74119CA4E02  tests/test_book_race_v24.py
3AE9A5FBB927  tests/test_chat_epoch_contract_v24.py
44731DAA832C  tests/test_compat_v242_fixes.py
419A0E0D0837  tests/test_config.py
0C675C947FDF  tests/test_config_robustness.py
3B3822BC433C  tests/test_constants_sync.py
5E24BFF8A99D  tests/test_critic_menu_e2e_v270.py
2FB7D1BCE07E  tests/test_d7a_v250_agent_c.py
94C0022F1AE1  tests/test_deadcode_types_v241.py
8425D3002D4A  tests/test_deps_bounds_v24.py
4F95ACCA7FC6  tests/test_dialog_buttons_v270.py
8A39D6F1B619  tests/test_dialog_fit_v250.py
EDCE752641C2  tests/test_dialogs_behavior_v290.py
A114E04404C1  tests/test_dialogs_feedback_v270.py
E28AEF66C30D  tests/test_dialogs_feedback_v280.py
4A6E6D846222  tests/test_dialogs_more_v24.py
F18D8A5919F3  tests/test_dialogs_v24.py
C7EBF1CABC6F  tests/test_export.py
6BC1434BC29F  tests/test_export_slice_v242.py
15AE845CBC4B  tests/test_export_v21.py
2B86D6F8E14B  tests/test_features_v230.py
4DB8C22AE191  tests/test_feedback_host_v270.py
0E3D437A4091  tests/test_feedback_v2110_b.py
915AD8F4913E  tests/test_full_form_frames_v24.py
A1B3159CC39F  tests/test_guardrails_v24.py
863AA9E98FAB  tests/test_heal_top_level_keys.py
3FB8A763206E  tests/test_heal_unify_v241.py
EFF2287557CF  tests/test_idle_settle_v26.py
1C6FC2EC5D05  tests/test_import_thread.py
40965B39B5CB  tests/test_io_v231.py
1AA6EB7EEBA9  tests/test_launcher.py
4AA5E347C743  tests/test_lines.py
0680444FFFB1  tests/test_memory_redact.py
3BDF704D1360  tests/test_mood.py
1209641BBDE0  tests/test_motion_v2110.py
BB9DE66ECBF9  tests/test_mutate_harness_v244.py
831433E319BB  tests/test_p3.py
B077D6434891  tests/test_persistence_consistency.py
D013E28C791A  tests/test_petting_guard_v250.py
09FB9A13EB39  tests/test_physics.py
449B77F013A2  tests/test_pinned_ast_v2110.py
D156F186DB8C  tests/test_plugin_host_v251.py
5EBE49876510  tests/test_plugin_market_v252.py
8942447E99A4  tests/test_plugin_market_v270.py
A0745EF5E4DB  tests/test_plugin_phase3_v280.py
B584192D610B  tests/test_plugin_v251.py
71266EEAB99A  tests/test_relay_v243.py
5C4904199B20  tests/test_release_chain_v24.py
FB144D6EE617  tests/test_release_check.py
FC70921FD6E1  tests/test_resources.py
740A21579580  tests/test_review_fixes_225.py
D4AB4214D6BF  tests/test_role_schema.py
01E55F880D3F  tests/test_round3_a_fixes.py
CAB05FF859F7  tests/test_screens.py
3CB628011099  tests/test_services_registry_v250.py
BA205AC73AAB  tests/test_silent_except_audit_v241.py
947F424BC6BE  tests/test_silent_except_v252.py
082500A2CC03  tests/test_silent_logging_v24.py
705E489D5408  tests/test_slot_recover_frames_v24.py
796D51B2E1FC  tests/test_startup_defer_v242.py
754D800C1267  tests/test_state_invariants.py
CFB90A695304  tests/test_static_undef_names_v280.py
139D91F44F28  tests/test_subsystem_annotations_v250.py
B61274185FBB  tests/test_tools_v230.py
A9DE256D0D70  tests/test_ui_wire_cache_v241.py
C39EA94CE4DD  tests/test_voice.py
2ECCA057655B  tests/test_voice_assets.py
F2D55CCBBCB7  tests/test_voice_contracts_v24.py
FE5E9E6B1A28  tests/test_voice_v21.py
9EBD117B613F  tests/test_walk.py
4CD7B8A9E09D  version_info.txt
```

## 一、本轮改了什么（三审的靶子）

从 **v2.9.0（提交 `209875e`）** 之后累计：**v2.10.0 清账** + **v2.11.0 无障碍/反馈** + **第 10 轮 A/C/D 全清**。
工作树：`39 files changed, 1857 insertions(+), 328 deletions(-)` **+ 10 个新文件**。
逐包报告在 `E:\deep seek\_v2100_reports\`（P1…P8 六份落盘；P9/P10 只有消息，没落盘）。

| 包 | 文件 | 改了什么 |
|---|---|---|
| P1 | `pet_motion.py` · `tests/test_motion_v2110.py` | A-08/A-11/A-12/C-09/C-10/C-20/C-21/C-31；**D1 令牌** `RATE["FRAME_REDUCED"]=0.5` + `frame_rate_factor()` |
| P3 | `pet_voice.py` | **`EventClipResult`**（played/missing/failed/voice_off + `fallback_allowed`，无 `__bool__`）；`speak()` 改成返回 `(ok, err)` |
| P4 | `pet_config.py` · `pet_menu.py` | 三态单一来源 `MOTION_MODES` / `normalize_motion_mode` / `is_auto_motion_mode`；菜单每个无障碍开关多一条「🔁 跟随系统」；**D3 删重复入口**；**D4 改名**「管理音效片段…」 |
| P6 | `pet_dialogs.py`（**+478 行**）· `tests/test_dialogs_v2100_round.py`（新） | **E1** `_StatusLine` 三处复用 · **E2** `_regen_line` 无服务时给交代 · **E3** `_FitDialog.keyPressEvent`（Esc/Enter/Space）· **F1** `ActionPanel` 资源管理第 4 页签「动作」· **C-15** 朗读文案改进行态 · D4 兄弟串 |
| P7 | `桌宠.py` · `pet_anim.py` · `tests/test_host_v2100_round.py`（新） | **C-13 三态接线**（`_set_reduce_motion` 收 auto/on/off，切 auto **重读**系统）· **D1 帧率**（`_safe_rate_factor` / `play(rate_factor=)` / 四条素材帧路径 / 吃帧看门狗改用生效间隔）· **D2 喂食优先级链**（`_clip = voice.play_event("feed")` → `if _clip.fallback_allowed and cfg.sound: play_sound("feed")`） |
| P8 | `_dev/mutations_agent_a_v2110.json` · `tests/test_feedback_host_v270.py` · `_check_release.py` | **E4**：24 条变异补 `expect_fail`（29 个 nodeid，1311→**1340**）· **C-12** autouse 复原气泡样式 · `_check_release.py:818` 注释 28→29 |
| P9 | `_dev/silent_except_whitelist_summary.json` · `README.md` · `README.en.md` · `tests/test_subsystem_annotations_v250.py` · `pet_export.py` | 白名单 **323→325**（两条 `fallback`）· README 注解表数字改准 · `OUT_OF_SCOPE_PINNED` `(0,9)→(0,13)` · 注释改词 |
| P10 | 版本五处 · `CHANGELOG.md` · `_release_notes_v2100.md` | 版本 **2.11.0 → 2.10.0**（五处）· CHANGELOG 两条并一条 · 发布说明合并 **18,294 B** · **删除** `_release_notes_v2110.md` |

## 二、三路各自的重点

**找茬（对抗性）**：专找「声称做了其实没做 / 判据没牙齿 / 假覆盖 / 文档与代码不符」。
- `_release_notes_v2100.md` **逐句对代码**（本仓最恨「文档说了代码没做」）；
- **本轮新加的判据做变异自证**：想一个「把它改坏」的最小变异，问「这条用例会红吗」；
- **D2 的优先级链**在异常路径下的行为（有片段但播不出 / 语音总开关关着 / 音效总开关关着）；
- **D1 帧率**：走路/甩抛飞行/食物飞行/拖拽弹簧**不纳入**（收窄声明口径）是否在发布说明与代码注释里一致。

**质量**：真实用户路径走通（含真模态框）。
- 新增 UI：`ActionPanel` 第 4 页签 · 三处试听状态行 · 托盘两条「跟随系统」 —— **对象数回基线 / 设计尺寸 / Tab 链 / 键盘**；
- 新静默 except（`pet_anim._safe_rate_factor` · `pet_motion.frame_rate_factor`）的归属与契约；
- `tests/` 里有没有新出现的**恒真断言 / 死块**。

**兼容**：老配置 / 老角色 / 老插件 / 绿版。
- `normalize_cfg` 三态对**旧 config.json** 的兜底；
- `play_event` 返回值改动对**既有调用点**的向后兼容（P3 报告说 6 处生产调用全是语句调用、不看返回值）；
- 顶层菜单 **≤18** 硬断言（D3 之后余量为 0，且 `pet_menu.py:243-245` 的「🐡 变身」是条件项）；
- `_release_notes_v2100.md` 对用户的**承诺是否兑现**。

## 三、纪律（违反即作废）

1. **只读**：不许改任何文件（连报告也不许写进 `desktop-pet`）。
2. **不许跑门**：全量 pytest / `--scan-only` / `check_mutation_nodeids.py` / `check_pinned_ast.py` / `_verify_v13.py` / 变异整批 —— 那些要等**三审收齐后**在安静窗口由协调者跑。可以跑**与你审查对象相关的那几个测试文件**（只读）。
3. **树必须静止**：三路同时跑，谁也不许写。
4. **锚必须对得上**：开工先按 §零 逐位比对；不符**停手报**。
5. 每条发现带 **文件:行 + 原文片段** + 「为什么是问题」；没证据的标【推测】。
6. **失败 ≠ 没问题；没找到 ≠ 没有问题** —— 查过没发现就写「我查了 X、Y、没发现」，并列出查过的范围。
7. 💡 **交叉核对（本轮特别要求）**：`E:\deep seek\_user_rules\` 有《用户要求与规矩总表》等 4 份（约 500 条，原话取自人类主对话日志）。**要判定某条判据/承诺是否真的来自用户时，查它** —— 本轮已查出 **6 处「代理裁决被写成用户明令」**（见 `补充-仓库内未扫部分.md` §5.2）。

**交付**：报告写到 `E:\deep seek\_v2100_reviews\<路名>.md`（**仓库之外**），写完只回一句「路径 + 字节数 + 行数」。