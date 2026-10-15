# 代理 C · v2.8.0 第 6 轮回报（证据与门 · `_dev/**`）

> 领地：`_dev/**`。**本轮没有碰任何产品代码与 `tests/**`**（除下面"工具加固"里点名的两个
> `_dev/` 脚本）。也不碰 VERSION / version_info / _verify_green / CHANGELOG / 发布说明 / 绿色版 / 发布 zip。

## 一、三项数字（对着提交前那棵树实测）

| 项 | 命令 | 结果 |
|---|---|---|
| 本 spec 变异 | `python -B _dev/mutate_check.py _dev/mutations_agent_c_v280.json` | **97 条 / 97 CAUGHT / 0 NOT CAUGHT / 0 SPEC-BAD / 0 WRONG TEST**；基线 70 条用例全过（影子副本） |
| 全库锚点体检 | `python -B _dev/mutate_batch_v270.py --scan-only` | **锚点合计 392 条，坏 0 条** |
| 变异体语法自检（新工具） | `python -B _dev/check_mutation_ast.py` | **367 条，0 条锚点/语法不过** |

原始输出：`_dev/_probe_c_v280_batch97.txt`（逐条 rc / 末行 / 红了哪条用例；**本地文件，按 `_dev/` 入库约定不提交**——结论与逐条判定已在 spec 的 `results` 段里）。

## 二、改动清单（句柄为准，行号会漂）

| 句柄 | 动作 |
|---|---|
| `_dev/mutations_agent_c_v280.json` | **新建**：97 条变异 + `results` 段（含 `repo_fingerprint`） |
| `_dev/check_mutation_ast.py` | **新建**：变异体语法自检（跑批前的秒级闸门） |
| `_dev/mutate_batch_v270.py` | 无需改（自动收录 `mutations_*.json`，新 spec 已进批量门） |
| `_dev/_mutate_lib.py` | **加固**：`run_pytest` 把"影子里的 pytest 超时"折成 `rc=3` + 明确说明（此前 `TimeoutExpired` 直接冒泡→整批崩掉）；默认 `timeout` 1800→600 |
| `_dev/mutations_agent_b_v270.json` | **重锚 3 条**（S17-KEY-ERR / S17-TOGGLE-ERR / S17-ROUNDS-ERR） |
| `_dev/mutations_critic_v270.json` | **重锚 3 条**（M-R5-F4 / M-R5-F5 / M-R5-P3-2） |
| `_dev/mutations_compat_v243.json` | **重锚 1 条**（M-C5） |
| `_dev/audit_feedback_v270.md` | §5 更新：11 行划掉（行首编号加删除线 + 行尾注"v2.8.0 第 6 轮已做"），新增 §5.1 逐行现状 + 本轮新登记的做不到项 |
| `_dev/README.md` | 铁律 5 一节的份数/条数刷新（21 份 / 367 条 → 合计 **392**）、spec 表新增一行、脚本表新增 `check_mutation_ast.py`、新增 v2.8.0 中间态记录段 |
| `_dev/probe_c_v280_hang.py` | **新建**：只读探针——用 `faulthandler.dump_traceback_later` 定位"某条用例挂死在哪一行"（本轮用它排掉了两次误判的"挂死"） |
| `_dev/_probe_c_v280_notcaught.json` / `_dev/_probe_c_v280_batch97.txt` | 只读现场的原始数据（**按 `_dev/` 的入库约定不入库**：`.gitignore` 只放行 `*.py` / `*.md` / `mutations_*.json` / `results_*.json` / `*_summary.json`；结论已全部落进本报告与 spec 的 `results` 段） |

## 三、97 条的构成

| 组 | 条数 | 钉谁 | 覆盖什么 |
|---|---|---|---|
| **M-C-H01~H11** | 11 | `tests/test_plugin_market_v252.py`（v2.6.0 的既有用例） | **v2.6.0 远端硬化回退护栏**：只收 https（函数级/索引级/绝对 url/拼接后）、远端索引不许指本地、相对地址拒 `..`/空段、`file://` 折本机路径、Content-Length 前置上限、本地边读边判、注入取数容量兜底、解包前再走校验器。**这 11 条此前全库一条变异都没有（真空档）**，本轮补上 |
| **M-C-B01~B48** | 46 | B 的 `tests/test_plugin_phase3_v280.py`（19+3）、`tests/test_ai_write_first_v280.py`（6）、`tests/test_balance_feedback_v280.py`（2） | `set_remote_base`/`refresh`/`source_info` 的契约与失败路径、本地缓存与换站点串味、`index_url_of` 两种填法、`load_index` 生产口径不联网、配置键单一来源与逐字节回归、`pet_ai` 三处"先写盘再提交"（含键顺序逐位等价与失败留痕）、`pet_balance` 两处可见反馈 |
| **M-C-A01~A40** | 40 | A 的 `tests/test_dialogs_feedback_v280.py`（47 条用例） | 索引来源区（显示/校验/保存/恢复默认/接线/刷新成功与失败/线程边界/force 口径）、`_toast` 行为层（`_closing` 返回 False + 两条兜底出口）、合成框取消、静态输入框收口、文案对照表、各处回执与二次确认 |

完整逐条清单（id / 文件 / 变异锚点首行 / 钉住的用例 / 判定）：

| `M-C-H01` | pet_plugin_index.py | `if is_insecure_remote(target):` | test_明文http一律拒_只收https | CAUGHT |
| `M-C-H02` | pet_plugin_index.py | `bad = insecure_reason(self._index_url)` | test_明文http一律拒_只收https | CAUGHT |
| `M-C-H03` | pet_plugin_index.py | `if is_remote(url):` | test_明文http一律拒_只收https | CAUGHT |
| `M-C-H04` | pet_plugin_index.py | `joined = urllib.parse.urljoin(base, url)` | test_明文http一律拒_只收https | CAUGHT |
| `M-C-H05` | pet_plugin_index.py | `if base_remote:` | test_远端索引不许指向本地路径_随包索引不受限 | CAUGHT |
| `M-C-H06` | pet_plugin_index.py | `why = _rel_url_reason(url)              # v2.6.0（P3-2）：.. ` | test_相对地址拒路径穿越与空段 | CAUGHT |
| `M-C-H07` | pet_plugin_index.py | `tail = url[7:]` | test_file_url折成本机路径 | CAUGHT |
| `M-C-H08` | pet_plugin_index.py | `if total and total > cap:           # 前置：对端自己就说超了，不必读回来再判` | test_远端ContentLength自报超限_一个字节都不读 | CAUGHT |
| `M-C-H09` | pet_plugin_index.py | `if done > cap:` | test_本地取数边读边判_到上限就停手 | CAUGHT |
| `M-C-H10` | pet_plugin_index.py | `guard = pet_export.EXPORT_MAX_BYTES` | test_注入取数也有容量上限_超了不落盘 | CAUGHT |
| `M-C-H11` | pet_plugin_index.py | `manifest, verr = pet_plugin.validate_plugin_zip(path, self` | test_下载后走校验器与安装器_真装进宿主库 | CAUGHT |
| `M-C-B01` | pet_plugin_index.py | `new = dict(cfg)                     # 先改副本（失败时内存不变）` | test_set_remote_base_成功才提交_写失败内存不变 | CAUGHT |
| `M-C-B02` | pet_plugin_index.py | `self._drop_cache()              # 回随包索引：连这份缓存一起清（免得换个地址后串味` | test_set_remote_base_空串清除远端并丢掉它的缓存 | CAUGHT |
| `M-C-B03` | pet_plugin_index.py | `bad = remote_base_reason(text)` | test_set_remote_base_非https与本地路径一律拒_且不落盘 | CAUGHT |
| `M-C-B04` | pet_plugin_index.py | `if self._cfg_getter is None or self._save_cfg is None:` | test_set_remote_base_没接线时如实报错不假装存下 | CAUGHT |
| `M-C-B05` | pet_plugin_index.py | `if len(text) > REMOTE_BASE_MAX_LEN:` | test_set_remote_base_非https与本地路径一律拒_且不落盘 | CAUGHT |
| `M-C-B06` | pet_plugin_index.py | `if not low.startswith("https://"):` | test_set_remote_base_非https与本地路径一律拒_且不落盘 | CAUGHT |
| `M-C-B07` | pet_plugin_index.py | `if not urllib.parse.urlsplit(text).netloc:` | test_set_remote_base_非https与本地路径一律拒_且不落盘 | CAUGHT |
| `M-C-B08` | pet_config.py | `PLUGIN_INDEX_URL_KEY = pet_plugin_index.PLUGIN_INDEX_URL_K` | test_配置键名两处一致_单一来源 | CAUGHT |
| `M-C-B09` | pet_config.py | `bad = pet_plugin_index.remote_base_reason(text)` | test_配置键名两处一致_单一来源 | CAUGHT |
| `M-C-B10` | pet_plugin_index.py | `werr = self._write_cache(target, raw)` | test_refresh_取回校验落地并返回条目数 | CAUGHT |
| `M-C-B11` | pet_plugin_index.py | `return True, ("远端索引已更新（共 %d 个插件，其中 %d 个可安装）"` | test_refresh_取回校验落地并返回条目数 | CAUGHT |
| `M-C-B12` | pet_plugin_index.py | `if not force:` | test_refresh_force语义_命中缓存不联网_force强制重取 | CAUGHT |
| `M-C-B13` | pet_plugin_index.py | `if not base:` | test_refresh_没有远端地址时如实拒绝 | CAUGHT |
| `M-C-B14` | pet_plugin_index.py | `if data is None:` | test_refresh_失败不留假象_旧缓存与随包索引都不动 | CAUGHT |
| `M-C-B15` | pet_plugin_index.py | `if self._fetch is None:` | test_load_index_生产口径绝不联网_没缓存退回随包索引 | CAUGHT |
| `M-C-B16` | pet_plugin_index.py | `cached = self._read_cache(self._index_url)` | test_load_index_生产口径缓存命中就能用远端清单 | CAUGHT |
| `M-C-B17` | pet_plugin_index.py | `info = {"kind": "remote" if base else "bundled", "url": ba` | test_来源信息_随包与远端两种口径 | CAUGHT |
| `M-C-B18` | pet_plugin_index.py | `cached = self._read_cache(base)` | test_来源信息_随包与远端两种口径 | CAUGHT |
| `M-C-B19` | pet_plugin_index.py | `data, err = self._fetch_bytes(target, self._progress, INDE` | test_远端索引体积上限_前置传下去且事后仍判 | CAUGHT |
| `M-C-B20` | pet_plugin_index.py | `if len(data) > INDEX_MAX_BYTES:     # 上限前置只是止损；这条事后判据仍是唯一口` | test_远端索引体积上限_前置传下去且事后仍判 | CAUGHT |
| `M-C-B21` | pet_plugin_index.py | `if got_sha != want_sha:` | test_远端包sha256与bytes不符一律拒收且不留残余 | CAUGHT |
| `M-C-B22` | pet_plugin_index.py | `if isinstance(want_bytes, int) and not isinstance(want_byt` | test_远端包sha256与bytes不符一律拒收且不留残余 | CAUGHT |
| `M-C-B23` | pet_plugin_index.py | `bad = insecure_reason(base)` | test_非https的远端地址_刷新前就拒且不取数 | CAUGHT |
| `M-C-B24` | pet_plugin_index.py | `index, perr = parse_index(raw, target, self._host_version,` | test_索引格式不认识_整份拒且不落地 | CAUGHT |
| `M-C-B25` | pet_plugin_index.py | `cfg.update(new)                     # 写盘成功才提交进内存（键顺序与原地写逐位` | test_set_remote_base_成功才提交_写失败内存不变 | CAUGHT |
| `M-C-B27` | pet_plugin_index.py | `return text.rstrip("/") + "/" + INDEX_NAME` | test_refresh_取回校验落地并返回条目数 | CAUGHT |
| `M-C-B29` | pet_config.py | `if isinstance(value, str):` | test_配置键名两处一致_单一来源 | CAUGHT |
| `M-C-B30` | pet_ai.py | `cfg = self._cfg()` | test_set_api_key_写失败_内存不变且不说记住了 | CAUGHT |
| `M-C-B31` | pet_ai.py | `new = dict(cfg)` | test_set_api_key_成功路径与改前逐位等价 | CAUGHT |
| `M-C-B32` | pet_ai.py | `new = dict(cfg)` | test_set_ai_enabled_写失败_内存不变且不假装生效 | CAUGHT |
| `M-C-B33` | pet_ai.py | `if not _bad2:` | test_set_ai_enabled_无Key回退落盘失败_内存保持已提交值 | CAUGHT |
| `M-C-B34` | pet_ai.py | `new = dict(cfg)` | test_set_chat_rounds_写失败_内存不变且不报成功 | CAUGHT |
| `M-C-B35` | pet_ai.py | `cfg.update(new)         # 写盘成功才提交进内存` | test_set_chat_rounds_成功路径落盘且内存同步 | CAUGHT |
| `M-C-B36` | pet_ai.py | `self._log("ai set_api_key save failed: %s" % (err,))` | test_set_api_key_写失败_内存不变且不说记住了 | CAUGHT |
| `M-C-B37` | pet_ai.py | `self._log("ai set_ai_enabled save failed: %s" % (err,))` | test_set_ai_enabled_写失败_内存不变且不假装生效 | CAUGHT |
| `M-C-B38` | pet_ai.py | `self._log("ai set_chat_rounds save failed: %s" % (err,))` | test_set_chat_rounds_写失败_内存不变且不报成功 | CAUGHT |
| `M-C-B39` | pet_ai.py | `self._log("ai set_ai_enabled rollback save failed: %s"` | test_set_ai_enabled_无Key回退落盘失败_内存保持已提交值 | CAUGHT |
| `M-C-B40` | pet_config.py | `PLUGIN_INDEX_URL_DEFAULT = ""      # 空 = 只读**随包**索引（不联网、离线` | test_配置键默认值不进diff落盘_逐字节回归 | CAUGHT |
| `M-C-B41` | pet_config.py | `if PLUGIN_INDEX_URL_KEY in cfg:` | test_配置键真的存得住_读得回来 | CAUGHT |
| `M-C-B42` | pet_config.py | `if PLUGIN_INDEX_URL_KEY in cfg:` | test_配置键真的存得住_读得回来 | CAUGHT |
| `M-C-B43` | 桌宠.py | `"plugin_index_url": "",` | test_真加载器_老config读入写出不冒出这个键 | CAUGHT |
| `M-C-A01` | pet_dialogs.py | `extra.append("还没取回来——点「刷新索引」")` | test_source_shows_remote_from_config_without_network | CAUGHT |
| `M-C-A02` | pet_dialogs.py | `if str(info.get("kind") or "") == "remote" and url:` | test_source_shows_remote_from_config_without_network | CAUGHT |
| `M-C-A03` | pet_dialogs.py | `if not raw and not clearing:` | test_empty_save_is_rejected_and_points_at_reset | CAUGHT |
| `M-C-A04` | pet_dialogs.py | `ok, reason = pet_config.validate_plugin_index_url(raw)` | test_bad_source_url_is_rejected_on_the_spot_with_a_reason | CAUGHT |
| `M-C-A05` | pet_dialogs.py | `if not (isinstance(res, (tuple, list)) and res and res[0])` | test_backend_write_failure_keeps_window_and_reports_the_reason | CAUGHT |
| `M-C-A06` | pet_dialogs.py | `fn = getattr(idx, "set_remote_base", None)` | test_backend_without_set_remote_base_degrades_with_a_human_message | CAUGHT |
| `M-C-A07` | pet_dialogs.py | `raw = pet_config.normalize_plugin_index_url(url)` | test_saving_a_good_url_uses_the_backend_and_tells_the_next_step | CAUGHT |
| `M-C-A08` | pet_dialogs.py | `save = _get(pet, "save_config")` | test_dialog_wires_cfg_read_and_write_into_the_backend | CAUGHT |
| `M-C-A09` | pet_dialogs.py | `if not (isinstance(res, (tuple, list)) and res):` | test_refresh_missing_result_is_treated_as_failure | CAUGHT |
| `M-C-A10` | pet_dialogs.py | `self._set_hint("⚠ %s　可点「恢复默认（随包索引）」回到随包索引——它随程序出货，"` | test_refresh_failure_shows_the_reason_and_keeps_a_way_back | CAUGHT |
| `M-C-A11` | pet_dialogs.py | `ok, msg, count = _source_result(res)` | test_refresh_failure_shows_the_reason_and_keeps_a_way_back | CAUGHT |
| `M-C-A12` | pet_dialogs.py | `self._apply_index(data, err)` | test_refresh_success_reports_count_and_repaints_the_list | CAUGHT |
| `M-C-A13` | pet_dialogs.py | `threading.Thread(target=self._source_worker, args=(gen, id` | test_refresh_runs_off_the_main_thread_and_lands_on_it | CAUGHT |
| `M-C-A14` | pet_dialogs.py | `threading.Thread(target=self._source_worker, args=(gen, id` | test_manual_refresh_forces_and_auto_refresh_prefers_cache | CAUGHT |
| `M-C-A15` | pet_dialogs.py | `if res is False:` | test_toast_returns_false_and_logs_when_bubble_is_refused | CAUGHT |
| `M-C-A16` | pet_dialogs.py | `if status is not None:` | test_toast_falls_back_to_the_dialog_status_line | CAUGHT |
| `M-C-A17` | pet_dialogs.py | `pet_log.log_throttled("toast:" + str(text)[:60],` | test_toast_returns_false_and_logs_when_bubble_is_refused | CAUGHT |
| `M-C-A18` | 桌宠.py | `if self._closing:` | test_show_bubble_reports_false_while_closing | CAUGHT |
| `M-C-A19` | pet_dialogs.py | `cancel = QPushButton("取消")` | test_compose_dialog_has_cancel_and_reject_adds_nothing | CAUGHT |
| `M-C-A20` | pet_dialogs.py | `dlg.setTextValue(items[idx])` | test_ask_helpers_go_through_modal | CAUGHT |
| `M-C-A21` | pet_dialogs.py | `dlg.setTextValue(str(default or ""))` | test_ask_helpers_go_through_modal | CAUGHT |
| `M-C-A22` | pet_dialogs.py | `name, ok = _ask_text(self._parent_widget(), "重命名声音素材", "新名` | test_static_input_dialogs_are_gone_except_the_frame_action_one | CAUGHT |
| `M-C-A23` | pet_dialogs.py | `if text.startswith("新建"):` | test_wording_table_is_applied_to_new_and_add_buttons | CAUGHT |
| `M-C-A24` | pet_dialogs.py | `if len(self._form_rows) >= 8:` | test_import_wizard_add_form_gives_a_receipt_and_construction_stays_quiet | CAUGHT |
| `M-C-A25` | pet_dialogs.py | `self._notes.setText("已添加「%s」（共 %d 个，最多 8 个）：改好名字、选好图，"` | test_import_wizard_add_form_gives_a_receipt_and_construction_stays_quiet | CAUGHT |
| `M-C-A26` | pet_dialogs.py | `label = self._event_label(key)` | test_voice_event_import_receipt_and_clear_confirm | CAUGHT |
| `M-C-A27` | pet_dialogs.py | `_toast(self._pet, "已清除「%s」的事件片段（音频文件没删）" % label)` | test_voice_event_import_receipt_and_clear_confirm | CAUGHT |
| `M-C-A28` | pet_dialogs.py | `_toast(self._pet, "「%s」的事件片段已配好（立即生效）" % self._event_label` | test_voice_event_import_receipt_and_clear_confirm | CAUGHT |
| `M-C-A29` | pet_dialogs.py | `_toast(self._pet, "已从对白里移除：%s（台词本身不受影响）" % (_gone_text[:24` | test_dialogue_remove_member_reports_what_was_removed | CAUGHT |
| `M-C-A30` | pet_dialogs.py | `if not _confirm(self, "删除自定义动作",` | test_role_edit_delete_action_needs_confirm_and_reports | CAUGHT |
| `M-C-A31` | pet_dialogs.py | `_toast(self._pet, "已删除自定义动作「%s」（保存后生效）" % name)` | test_role_edit_delete_action_toasts_with_a_pet | CAUGHT |
| `M-C-A32` | pet_dialogs.py | `_toast(self.pet, back or "已恢复为随包索引（不联网）", status=self._hin` | test_reset_to_bundled_takes_effect_and_reports | CAUGHT |
| `M-C-B44` | pet_balance.py | `pet.show_bubble("「记一笔」打不开：%s\n（详情见数据目录的 error.log）" % (e,)` | test_对话框构建失败_有可见提示与日志 | CAUGHT |
| `M-C-B45` | pet_balance.py | `pet.show_bubble("金额要大于 0 才记得上哦~（这笔没有记）")` | test_金额不大于零_给提示且绝不记账 | CAUGHT |
| `M-C-B46` | pet_plugin_index.py | `if str(data.get("source_url") or "") != (index_url_of(base` | test_换站点后旧站点的缓存不许冒充新站点 | CAUGHT |
| `M-C-B47` | pet_plugin_index.py | `if parts.path.lower().endswith(".json"):` | test_直接填index_json地址也收_不重复拼路径 | CAUGHT |
| `M-C-B48` | pet_plugin_index.py | `return None, ("远端索引还没取回来（点「刷新索引」）；%s"` | test_load_index_随包也读不出来时把两条原因都说清 | CAUGHT |
| `M-C-A33` | pet_dialogs.py | `if not select:` | test_new_proc_action_is_selected_and_scrolled_into_view | CAUGHT |
| `M-C-A34` | pet_dialogs.py | `self._reset_form()` | test_alarm_new_gives_a_receipt | CAUGHT |
| `M-C-A35` | pet_dialogs.py | `self._reset_form()          # 静默清表：回执由下面这一句给（不许一次动作两句）` | test_alarm_delete_reports_exactly_once | CAUGHT |
| `M-C-A36` | pet_dialogs.py | `_toast(self.pet, "已添加步骤：%s（点「保存」才落盘）" % self._step_text(no` | test_behavior_step_receipts | CAUGHT |
| `M-C-A37` | pet_dialogs.py | `_toast(self.pet, "已删除步骤%s（点「保存」才落盘）"` | test_behavior_step_receipts | CAUGHT |
| `M-C-A38` | pet_dialogs.py | `# v2.8.0 第 6 轮：到顶/到底以前是静默 return —— 点了没反应与"已经到边界"在` | test_move_line_at_boundary_tells_the_user | CAUGHT |
| `M-C-A39` | pet_dialogs.py | `# 与台词「上移/下移」同一套措辞（P3-6：同一动作同一批对话框同一套话）` | test_lines_move_member_at_boundary_uses_the_same_wording | CAUGHT |
| `M-C-A40` | pet_dialogs.py | `self._refresh_all()` | test_new_line_scrolls_into_view | CAUGHT |

## 四、重锚过哪些（7 条，全部是"锚点漂移"不是护栏失效）

| spec · id | 为什么死 | 新锚点（节选） |
|---|---|---|
| `agent_b_v270` S17-KEY-ERR | B 把 `set_api_key` 改成先写副本：旧的 `err = self._save_cfg(self._cfg())` 一行不存在了 | `self._redact(key)` + `if err:` |
| `agent_b_v270` S17-TOGGLE-ERR | 同上（`set_ai_enabled`） | `new["ai_enabled"] = bool(on)` + `err = self._save_cfg(new)` + `if err:` |
| `agent_b_v270` S17-ROUNDS-ERR | 同上（`set_chat_rounds`） | `new["chat_memory_rounds"] = val` + `err = self._save_cfg(new)` + `if err:` |
| `critic_v270` M-R5-F4 | `new = dict(cfg)` 由 1 处变 3 处 → **命中 2 次（歧义）** | 补上 `for k, v in data.items():` 上下文，钉回 `apply_settings` |
| `critic_v270` M-R5-F5 | A3 把 `_toast` 的 docstring 整段改写（本轮行为层收口） | 新 docstring 的前两行（仍要求首行"尽力而为"、不许承诺"真的发出"） |
| `critic_v270` M-R5-P3-2 | B 给第二次落盘也加了"先写副本"，判据变量 `_err2` → `_bad2` | `if _bad2:` + 那条"另外：AI 开关也没能保存"气泡 |
| `compat_v243` M-C5 | 本轮给 `PetWindow` 加了 `plugin_index_url` 属性 → `桌宠.py` 函数数 254→255 | `\`桌宠.py\`（255 函数）` |

## 五、哪些暂不可构造（附理由）

1. **`remote_base_reason` 的"本地路径 / file://"分支**——单独删掉是**等价变异**：后面那条"只收 https:// 前缀"判据会把同一批样本（`file://`、盘符、`/etc/...`、UNC）全部拒掉，17 条断言照样全绿。**登记为"既不通过也不失败"**（B 也明确不另造第二套判据）。要可构造，得有一条"只填 `C:\...`，且要求文案点名『本地路径』"的用例。
2. **`桌宠.show_bubble` 末行 `return bool(self.bubble.isVisible())`**——"气泡窗口自己放弃显示"（`Bubble.show_text` 的早退）在 offscreen 下**不可达**：测试里气泡总是可见。改成 `return True` 不会被任何用例抓到。要一条"没有可用屏幕"的用例才可构造。
3. **等价变异（登记不做）**：`remote_base_reason` 本地分支（同 1）。

## 六、本轮发现（两条"用例/门禁"层面的真问题）

1. **假覆盖（已修）**：`tests/test_plugin_phase3_v280.py::test_load_index_随包也读不出来时把两条原因都说清` 原来只断言 `"还没取回来" in err` 与 `"索引" in err`——把 `load_index` 的组合错误**只报一半**（丢掉随包那半的原因），用例**照样绿**（实测 `NOT CAUGHT`，现场留在 `_dev/_probe_c_v280_notcaught.json`）。已报给 B，B 收紧断言（补 `"读取本地文件失败" in err`）后 **M-C-B48 CAUGHT**。
2. **"回归会挂死而不是变红"（仍未修，建议 A 处理）**：`tests/test_dialogs_feedback_v280.py::test_dialog_wires_cfg_read_and_write_into_the_backend` 是成功路径用例、**没有 `quiet` / `ui` fixture**——一旦"注入没接上"（`set_remote_base` 回 `(False, "索引地址没有接线…")`），用例会走进**真** `QMessageBox.exec()` 而**永久阻塞**。本轮实测：89 条那批因此挂在一个变异上白烧 20 分钟。**建议给这条用例加 `quiet`**（或把 `_warn` 换成记录器），让回归"红"而不是"挂"。
   （代理 C 已在 `_dev/_mutate_lib.run_pytest` 里把超时折成 `rc=3`，判定落 WRONG TEST＝这条没被验证，整批不再因一条挂死而崩掉。）

## 七、工具加固（`_dev/`，两条，都是本轮踩坑换来的）

1. `_dev/check_mutation_ast.py`（新）：跑批前逐条在内存里 `old → new` 再 `ast.parse`。本轮踩到一次
   `M-C-A05`：替换片段把 `if False:` 的缩进体一起换掉了 → 新源码 `IndentationError` → pytest **收集期**就炸
   （rc=4）→ 判定只能落 WRONG TEST，而整批要跑完才知道。现在这一步是秒级的（367 条 / 0 不过）。
2. `_dev/_mutate_lib.run_pytest`：`TimeoutExpired` 不再冒泡（见六·2），默认 `timeout` 1800→600。
   全量套件本身 2~4 分钟，单条变异跑的只是它的子集；600s 之后按"这条没被验证"收口。

## 八、没做到 / 让步 / 疑问（如实写）

- **不是安静窗口的最终证据**：本批是在 A/B 仍在改树时跑的（同一批的"跑前跑后指纹"必然不一致）。
  它的用途只有两个：证明"当前源码上 97 条都能被抓住"＋找出断裂锚点。**定版必须按铁律 5 在安静窗口
  用 `python -B _dev/mutate_batch_v270.py` 整批再跑一次**（392 条 + 25 条旧形态 + 2 份独立结果）。
- **H 组的 11 条钉的是 v2.6.0 的既有用例**（不是本轮新用例）。理由：那 11 条护栏**此前一条变异都没有**
  （真空档），而 B 本轮的任务正是"保留这些硬化、不许推翻"；B 的新用例覆盖了其中 5 条（https / 跨信任域 /
  上限前置 / sha256 / bytes），我另外用 M-C-B21~B24 单独钉了新用例，两组并存=铁律 4 的双向覆盖。
- **B 交来的 19 条临时 spec（`%TEMP%\b_mutations_v280.json`）我只收编了 5 条**（M-B15/B16 的 `pet_balance`
  两条 + M-B17 换站点串味 + M-B18 `.json` 直通 + M-B19 组合错误只报一半），其余 14 条与本 spec 的
  `M-C-B01~B14/B19/B20` **逐条对应同一行为**（锚点文字略有出入，判定完全等价）。对应关系：
  `B01→M-C-B01` · `B02→M-C-B03` · `B03→M-C-B15` · `B04→M-C-B16` · `B05→M-C-B12` · `B06→M-C-B10` ·
  `B07→M-C-B19` · `B08→M-C-B41` · `B09→M-C-B43` · `B10→M-C-B30` · `B11→M-C-B32` · `B12→M-C-B34` ·
  `B13→M-C-B38` · `B14→M-C-B33`。**没有丢掉任何一条覆盖**；如果你要求"B 的 19 条原样另立一份
  `mutations_agent_b_v280.json`"，我可以照办（那会把锚点总数推到 411，并多跑一遍重复判定）。
- **疑问**：`tests/test_balance_feedback_v280.py` 不在 A/B 的领地描述里（第 3 路/主代理改的 `pet_balance.py`）。
  我把它一并纳入了门（M-C-B44/B45），因为"每条新用例都要有能真失败的变异"这条口径不该挑领地。如果口径
  是"只覆盖 A/B 的用例"，请裁一下。
- **测试数据落点**：跑探针时发现 `error.log` / `prompts/default.txt` 在 18:41 被改过（跑了用例却没隔离
  数据目录）。不是我这路造成的（我的所有跑法都在 `%TEMP%` 影子副本或 `tmp_path` 里），但**值得点名**。


---

## 九、收尾追加：把代理 A 的 25 条变异收编入库（`_dev/mutations_agent_a_v280.json`）

**为什么要做**：A 的变异只活在 `%TEMP%\mutate_a_v280.py`（驱动）+ `%TEMP%\mut_all.txt`（证据）里，
仓库里没有对应 spec —— 这就是上一轮 **L2-2** 那个坑：铁律 5 的定版复跑**覆盖不到**它，
证据在交付物里不可复现。现在它进了库、进了批量门。

**怎么取的**：用 `ast` 把它的 `MUTS = [...]` 那一条赋值单独 `compile+exec` 进一个带 `T280` 的命名空间
（`ast.literal_eval` 不行——里面有 Name 引用），**`old` / `new` 一个字符没改**；`id` 沿用它的
`MA01~MA25`（便于与它的报告对账）；`tests`/`expect_fail` 从"用例名"翻成具体 nodeid。
（踩坑记录：第一次经 pwsh 管道 `Out-File` 落盘，控制台编码把文件名 `桌宠.py` 解成了 `????.py` ——
改成让 Python 自己写文件就好了。）

**四项验收**：

| 项 | 命令 | 结果 |
|---|---|---|
| 条数 | — | **25**（MA01~MA25，`桌宠.py` 1 条 + `pet_dialogs.py` 24 条） |
| CAUGHT | `python -B _dev/mutate_check.py _dev/mutations_agent_a_v280.json` | **25/25 CAUGHT / 0 NOT CAUGHT / 0 SPEC-BAD / 0 WRONG TEST**（基线 23 条用例全过） |
| 锚点体检 | `python -B _dev/mutate_batch_v270.py --scan-only` | **锚点合计 417 条，坏 0 条**（收编前 392/0） |
| 语法自检 | `python -B _dev/check_mutation_ast.py` | **392 条，0 条锚点/语法不过**（收编前 367/0） |

**重锚：0 条**。25 条锚点在当前树**全部恰好命中 1 次**——A 的驱动跑完（19:37）之后，`pet_dialogs.py`
与 `桌宠.py` 没有再动过。**不可构造：0 条**（它的 25 条全部可构造、全部 CAUGHT，不需要硬凑）。

**两条"看起来慢、其实没挂"**（写给下一个复核者，免得误判成挂死）：
`MA08-refresh-forgets-force` 跑了 **21.0s**、`MA14-voice-clear-no-confirm` 跑了 **31.4s**，
其余 23 条都在 1~7s。原因是这两条钉的用例里有 `_wait_source(dlg)` 的 **10 秒防挂死兜底定时器**
（force 口径变了 / 确认框被跳过之后，`sourceReady` 不再按时到达，兜底计时器按时到点放行）——
**它们是"按时到点后失败"，不是挂死**；两者在输出里的区别就是这一行有没有 `failed in XXs`。

**与 `mutations_agent_c_v280.json` 的关系**（两组并存，不是重复劳动）：
A 的 25 条覆盖的行为与我的 `M-C-A01~A40` 大面积重叠，但**锚点位置不同**，其中 4 条是**我这边没有的**：
- `MA06`：锚在 `_warn(...)` 那条**模态提示的文案**上（我的 M-C-A10 锚在 `_set_hint(...)` 的状态行上）——同一句"回退路径"的两个出口各钉一次；
- `MA12` / `MA13`：把"合成框取消"拆成**两半**（按钮不存在 / 按钮在但没接线），我的 M-C-A19 是一条把按钮变成"确定"；
- `MA25`：锚在**贴 tooltip 的调用点** `_btn_tip(b, label)`（我的 M-C-A23 锚在 `_btn_tip` **体内**的新建/添加分支）——一个钉"有没有贴"，一个钉"贴的是哪一套措辞"。
其余 21 条是同一行为的不同写法，保留它们等于对同一承诺多一次独立验证（铁律 4 的双向覆盖用得上），
且**成本只有每条 1~2 秒**。
