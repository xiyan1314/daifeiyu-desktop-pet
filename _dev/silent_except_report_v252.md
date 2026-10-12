# D7-B：静默 except 逐条判定报告（v2.6.0 · 代理 B）

> 口径与数据：_dev/audit_silent_except.py（分档）· _dev/silent_except_whitelist.py（判定器）· _dev/silent_except_whitelist_summary.json（白名单数据）· tests/test_silent_except_v252.py（razor + 行为用例）· _dev/mutate_check.py + _dev/mutations_silent_except_v260.json（变异验证，19 条 spec）
> 本文由 python -B _dev/silent_except_report.py 生成，数字全部来自实跑。
>
> **数字口径（v2.6.0 第 4 轮收口补注）**：白名单条数已在 §3.1 / §5 按收口后的 **307** 条更新
> （首轮 222 + 收编的 85，"222"只作为演变说明保留）；§0 / §1 / §3 的 **B 档逐条读数仍是首轮快照**
> （B=248 / 领地外 60）——第 4 轮收口后重跑是 B=251 / 领地外 0（DELEGATED_FILES 已清空），
> 逐条清单未重排；要一份全表最新的报告直接跑上面的生成器即可。

## 0. 一句话结论

- **B 档（功能性吞咽）逐条判定完毕，没有「未判定」**：收尾实测 B=248 条，其中本代理领地 188 条、领地外（代理 A/C 并行改造的 4 个文件）60 条。
- 三选一结果：**①补限流日志 5 处 · ②改逻辑 1 处 · ③确实该静默（进白名单）其余全部**；另有 1 处限流口径收敛（guard_slot → pet_log.log_throttled）。每条改动都有能真失败的用例，并做了变异验证（把改动逐个还原 → 对应用例必须红）：复跑命令 **python -B _dev/mutate_check.py _dev/mutations_silent_except_v260.json**（v2.6.0 第 4 轮把原来 12 条原地覆写式变异迁成 _mutate_lib 的 spec 形态、再补 7 条，共 **19 条 / 19 CAUGHT**；旧的 _dev/silent_except_mutate.py 已停用）。
- **A 档 = 0**（收尾实测）。
- 白名单落成**数据**（**307** 条 = 首轮快照 222 条 + 本轮收编的 4 个领地外文件 85 条，每条带理由码 + 一句话「为什么该静默」+ 源码证据），并由 razor 钉住：新增静默 except / 改了 handler 结构 / 条目失效 / 理由是 unreviewed 占位 → **测试红**。

## 1. 起点对账（任务书的数字与实跑不一致，按实跑）

任务书写「实测输出 A=0 / B=219 / C=128 / OK=119」，同段又说「211 条」。**代理 B 接手时第一次实跑的结果是：**

| 指标 | 任务书 | 接手实测 | 说明 |
|---|---|---|---|
| A | 0 | **0** | 一致 |
| B | 219（正文另说 211） | **240**（领地内 194 / 领地外 46） | 不一致，差 +21 |
| C | 128 | **132** | 差 +4 |
| OK | 119 | **127** | 差 +8 |

任务书那两个数字（219 / 211）**无法在本仓库复现**：接手时工作树干净（HEAD 7ee8766，只有未跟踪的 _dev/task_v260.md），审计脚本本身在版本控制里、未改动。推测是更早某次快照的数字（v2.5.0/v2.5.1 之间加过插件系统与 D7-A 的改动）。按铁律 7，报告一律以实跑为准，起点定成接手那一刻的实测值。

收尾读数（含并行代理 A/C 的在制品：A 正在往 pet_dialogs / pet_plugin_index / pet_plugin_host 加市场页与下载器，所以领地外条数在涨）：

| 档 | 条数 | 其中领地内 | 其中领地外 |
|---|---|---|---|
| A（数据丢失/用户可见错误被吞） | **0** | 0 | 0 |
| B（功能性吞咽） | 248 | 188 | 60 |
| C（良性） | 137 | 100 | 37 |
| OK（已有日志/上报） | 138 | - | - |

## 2. 起点 240 条的归属

| 归属 | 条数 | 说明 |
|---|---|---|
| ① 该补日志 → 已补（补完就不再是「静默 except」，从 B 档消失） | 5 | §4 |
| ② 该改逻辑 → 已改（同上） | 1 | §4 |
| ③ 确实该静默 → 进白名单（含领地外只判定的） | 其余全部 | §3 逐条表 |
| 附带：限流口径收敛（不是新增日志） | 1 | §4.3 |

**为什么绝大多数是 ③**：这不是「懒得改」。B 档的两大来源本身就是「已经处理过」的形态——①失败以返回值/错误文案上报调用方（界面会当场显示，再写一条日志只是重复）；②可选能力/探针/清理路径（失败等于「这个能力没有」，补日志反而制造噪音）。本轮把「看得见就有价值」的那几处挑出来补了日志（§4），其余按证据登记并逐条写清理由。

## 3. 逐条判定（B 档全部 248 条）

列口径：**现行为**＝handler 原文（单行化截断）；**判定**＝①/②/③；**依据**＝白名单理由码 +「为什么该静默」一句话；**是否实测**＝是否构造路径真跑过。

| 位置（文件:行 · 函数） | 现行为 | 判定 | 依据（为什么该静默） | 是否实测 |
|---|---|---|---|---|
| pet_alarm.py:62 · normalize_time | except (TypeError, ValueError): return "" | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_alarm.py:388 · AlarmService | except OSError as e: return None, "无法读取文件：%s" % e | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_alarm.py:402 · AlarmService | except Exception as e: return None, "铃声导入失败：%s" % e | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_anim.py:121 · load_frame_set | except Exception: pix = QPixmap() | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_audio.py:47 · <module> | except ImportError: winsound = None | ③ 确实该静默 | 理由码 optional：可选能力降级（音效/动画/缩放/预览/悬停提示）：失败＝该能力缺席，不丢数据 | 否（静态判定） |
| pet_audio.py:120 · _probe_wav | except Exception: return False, None | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_audio.py:191 · _rebuild_effects | except Exception: _effects[name] = None | ③ 确实该静默 | 理由码 optional：可选能力降级（音效/动画/缩放/预览/悬停提示）：失败＝该能力缺席，不丢数据 | 否（静态判定） |
| pet_audio.py:205 · _on_default_device_changed | except Exception: dev_id = None | ③ 确实该静默 | 理由码 optional：可选能力降级（音效/动画/缩放/预览/悬停提示）：失败＝该能力缺席，不丢数据 | 否（静态判定） |
| pet_audio.py:232 · _winsound_file_play | except Exception: return False | ③ 确实该静默 | 理由码 probe：能力/存在性探针：失败本身就是安全的假值（is_running=False / 没有这个能力） | 否（静态判定） |
| pet_audio.py:240 · _winsound_file_play | except Exception: return False | ③ 确实该静默 | 理由码 probe：能力/存在性探针：失败本身就是安全的假值（is_running=False / 没有这个能力） | 否（静态判定） |
| pet_audio.py:311 · _qt_playable | except Exception: return False | ③ 确实该静默 | 理由码 probe：能力/存在性探针：失败本身就是安全的假值（is_running=False / 没有这个能力） | 否（静态判定） |
| pet_balance.py:121 · BalanceService | except Exception as e: return False, repr(e) | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_balance.py:138 · BalanceService | except Exception: return True | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_balance.py:367 · BalanceService | except (TypeError, ValueError): cur = cfg.get("budget", 0.0) or 0.0 | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_behaviors.py:104 · _to_float | except (TypeError, ValueError): return default | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_behaviors.py:135 · normalize_idle_cfg | except Exception: weight = 1.0 | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_behaviors.py:162 · normalize_idle_cfg | except (TypeError, ValueError): delay = DEFAULT_BEHAVIOR_CFG["idle_trigger_delay"] | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_behaviors.py:168 · normalize_idle_cfg | except (TypeError, ValueError): after_full = DEFAULT_BEHAVIOR_CFG["idle_delay_after_full"] | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_behaviors.py:191 · _clamp_int | except (TypeError, ValueError): return default | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_behaviors.py:280 · update_idle_action | except (TypeError, ValueError): return False, "顺序必须是数字" | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_behaviors.py:371 · validate_steps | except (TypeError, ValueError): ms = 500 | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_behaviors.py:579 · BehaviorService | except Exception as e: return None, "文件读取失败：%s" % e | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_book.py:120 · _date_shift | except Exception: return _today() | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_book.py:140 · _normalize_record | except Exception: lt = time.localtime() | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_book.py:407 · Book | except Exception: usage = 0.0 | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_book.py:412 · Book | except Exception: lb = None | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_book.py:520 · Book | except Exception: return None | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_book.py:574 · Book | except Exception: n = 7 | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_book.py:631 · Book | except Exception: return alerts | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_book.py:689 · Book | except Exception as e: # pet_io 的契约是"绝不抛"，这里再兜一层：导出失败绝不能掀掉调用方的界面 return False, str(e) | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_chat.py:152 · test_api_connection | except Exception: body = "" | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_chat.py:155 · test_api_connection | except requests.exceptions.Timeout: return False, "响应超时：服务商可能过载，或接口地址不是 OpenAI 兼容端点" | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_chat.py:157 · test_api_connection | except requests.exceptions.ConnectionError: return False, "连不上接口地址：检查网络/代理/地址（本地 Ollama 要先启动）" | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_chat.py:159 · test_api_connection | except Exception: # 有意忽略：未知异常只给通用中文（原始英文对小白不友好，调用方有日志兜底） return False, "连接失败，请检查接口地址与网络设置" | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_chat.py:413 · _accepts_epoch_kwargs | except (TypeError, ValueError): return False | ③ 确实该静默 | 理由码 probe：能力/存在性探针：失败本身就是安全的假值（is_running=False / 没有这个能力） | 否（静态判定） |
| pet_chat.py:455 · ChatService | except Exception: return None | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_chat.py:632 · ChatService | except Exception: body = "" | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_config.py:45 · normalize_physics | except (TypeError, ValueError): bad.append(k) | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_config.py:164 · normalize_cfg | except (TypeError, ValueError): cfg["scale"] = 1.0 | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_config.py:191 · normalize_cfg | except (TypeError, ValueError): cfg[_k] = _d | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_config.py:202 · normalize_cfg | except (TypeError, ValueError): cfg["role_frame_max"] = 24 | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_config.py:239 · normalize_cfg | except (TypeError, ValueError): cfg["transform_seconds"] = _bcfg["transform_seconds"] | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_config.py:259 · normalize_cfg | except Exception: cfg["bubble_style"] = dict(defaults["bubble_style"]) | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_config.py:264 · normalize_cfg | except (TypeError, ValueError): cfg[k] = 0.0 | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_dialogs.py:276 · _get | except Exception: return None | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_dialogs.py:415 · _remove_background | except Exception: return None | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_dialogs.py:476 · _content_bbox | except Exception: return None | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_dialogs.py:699 · dialog_available_geometry | except Exception: return None | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_dialogs.py:936 · _extract_video_frames | except Exception as e: return None, "抽帧失败：%s" % e | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_dialogs.py:1069 · _ImportWorker | except ImportCancelled: self.failed.emit("已取消处理") | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_dialogs.py:1071 · _ImportWorker | except Exception as e: self.failed.emit("处理失败：%s" % e) | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_dialogs.py:1436 · RoleImportDialog | except Exception: return None, "读取图片失败" | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_dialogs.py:2010 · RoleEditDialog | except Exception: return None, "读取图片失败" | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_dialogs.py:2049 · RoleEditDialog | except Exception as e: return False, "处理失败：%s" % e | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_dialogs.py:2491 · BehaviorDialog | except (TypeError, ValueError): # 有意忽略：坏值回默认（load 时 normalize 已兜底，此处防御外部直改 cfg） self._idle_secs.setValue(pet_behaviors.DEFAULT_BEHAVIOR_CFG["idle_beha | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_dialogs.py:2860 · _ApiTestWorker | except Exception: # 有意忽略：test_api_connection 已兜底不抛；此处防御性收尾（线程内不触 UI） self.result.emit("❌ 测试失败，请稍后再试") | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_dialogs.py:3024 · AISettingsDialog | except RuntimeError: _running = False | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_dialogs.py:3058 · AISettingsDialog | except RuntimeError: _running = False | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_dialogs.py:3248 · RolePanel | except Exception: self._preview_full.setPixmap(QPixmap()) self._preview_full.setText("吃饱图无法预览") | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_dialogs.py:3442 · SoundPanel | except Exception: slots = None | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_dialogs.py:3622 · VoiceAssetPanel | except Exception: binds = {} | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_dialogs.py:3970 · BubbleStyleDialog | except Exception: return default | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_dialogs.py:4942 · VoiceDialog | except Exception: names = [] | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_dialogs.py:4981 · VoiceDialog | except (TypeError, ValueError): self._lwait.setValue(30) | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_dialogs.py:4990 · VoiceDialog | except Exception: st = {} | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_dialogs.py:5154 · VoiceDialog | except Exception: cur = {} | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_dialogs.py:5513 · IdleDialog | except Exception: return [] | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_dialogs.py:5565 · IdleDialog | except (TypeError, ValueError): weight = 1.0 | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_dialogs.py:5731 · _VoicePickDialog | except Exception: assets = [] | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_dialogs.py:6223 · PluginManagerDialog | except Exception as e: self._index_retire(gen, "线程启动失败：%r" % (e,)) self._apply_index(None, "取数失败：%r" % (e,)) return False | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_dialogs.py:6252 · PluginManagerDialog | except Exception as e: data, err = None, "读取索引失败：%r" % (e,) | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_dialogs.py:6336 · PluginManagerDialog | except Exception as e: path, err = None, "下载失败：%r" % (e,) | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_dialogs.py:6414 · PluginManagerDialog | except Exception: return True | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_export.py:267 · plan_bundle | except Exception as e: return None, "导出失败：%s" % e | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_export.py:331 · BundleWriter | except Exception: # _zf 先关掉它就会抛 AttributeError（见 zipfile 的实现） self._big, self._big_src = None, None | ③ 确实该静默 | 理由码 teardown：关闭/退出/销毁路径：进程即将结束或对象即将销毁，记日志没有接收方 | 否（静态判定） |
| pet_export.py:437 · BundleWriter | except Exception as e: self.error = e self.done = True | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_export.py:468 · BundleWriter | except Exception as e: self._cleanup_tmp() return False, "写入失败：%s" % e | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_export.py:519 · validate_bundle | except KeyError: return None, "不是角色包：缺少 manifest.json" | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_export.py:521 · validate_bundle | except Exception as e: return None, "manifest.json 无法解析：%s" % e | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_export.py:544 · validate_bundle | except zipfile.BadZipFile: return None, "文件不是有效的 zip 包" | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_export.py:546 · validate_bundle | except Exception as e: return None, "打开失败：%s" % e | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_export.py:635 · import_bundle | except Exception: _local_keys = {} | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_export.py:711 · import_bundle | except (TypeError, ValueError): # v2.4.1（B 区 · A 档静默 except 判定）：**误报**——这里只做"能不能比较 # 版本号"的防御性读取，包里的 version 写坏了就按当前版本处理，最坏是 # 少弹一句"包版本高于当前支持"的提示；不丢数据、 | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_export.py:805 · import_bundle | except Exception as e: # 非事务回滚：清理本次已入索引的角色条目与已解包文件（尽力而为） if role_appended: try: role_lib._data["roles"].remove(role) role_lib._save() except Exception | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_export.py:811 · import_bundle | except Exception: # 有意忽略：回滚保存尽力而为。**最坏后果 = 留一个空角色条目**（索引里有角色、 # 素材已被下面的 written 循环删掉 → 下次启动看到一个没有素材的形态）。 # 不引 pet_log 上报是对的取舍：为一个"回滚中的回滚"引入依赖，收益不抵改动面。 | ③ 确实该静默 | 理由码 cleanup：尽力而为的清理/回滚：失败只会在磁盘上留孤儿文件，不改变用户可见结果 | 否（静态判定） |
| pet_fx.py:85 · frame_sets | except OSError: return out | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_fx.py:135 · AnimatedEmote | except Exception: frame_list = [] | ③ 确实该静默 | 理由码 optional：可选能力降级（音效/动画/缩放/预览/悬停提示）：失败＝该能力缺席，不丢数据 | 否（静态判定） |
| pet_fx.py:143 · AnimatedEmote | except Exception: self._loops = 1 | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_fx.py:165 · AnimatedEmote | except Exception: # 任何异常（含 item 已销毁）：静默收尾，不向上抛 self.stop() return False | ③ 确实该静默 | 理由码 teardown：关闭/退出/销毁路径：进程即将结束或对象即将销毁，记日志没有接收方 | 否（静态判定） |
| pet_fx.py:191 · AnimatedEmote | except Exception: return False | ③ 确实该静默 | 理由码 probe：能力/存在性探针：失败本身就是安全的假值（is_running=False / 没有这个能力） | 否（静态判定） |
| pet_fx.py:218 · AnimatedEmote | except Exception: # 换帧出错就静默收尾，避免定时器空转 self._finish() | ③ 确实该静默 | 理由码 optional：可选能力降级（音效/动画/缩放/预览/悬停提示）：失败＝该能力缺席，不丢数据 | 否（静态判定） |
| pet_io.py:224 · preferred_encoding | except Exception: return "" | ③ 确实该静默 | 理由码 probe：能力/存在性探针：失败本身就是安全的假值（is_running=False / 没有这个能力） | 否（静态判定） |
| pet_io.py:239 · _codec_name | except Exception: return e | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_io.py:258 · is_single_byte_encoding | except UnicodeDecodeError: bad += 1 if bad > 8: return False | ③ 确实该静默 | 理由码 probe：能力/存在性探针：失败本身就是安全的假值（is_running=False / 没有这个能力） | 否（静态判定） |
| pet_io.py:262 · is_single_byte_encoding | except (LookupError, ValueError): return False | ③ 确实该静默 | 理由码 probe：能力/存在性探针：失败本身就是安全的假值（is_running=False / 没有这个能力） | 否（静态判定） |
| pet_io.py:264 · is_single_byte_encoding | except Exception: return False | ③ 确实该静默 | 理由码 probe：能力/存在性探针：失败本身就是安全的假值（is_running=False / 没有这个能力） | 否（静态判定） |
| pet_io.py:357 · _almost_utf8 | except Exception: return False | ③ 确实该静默 | 理由码 probe：能力/存在性探针：失败本身就是安全的假值（is_running=False / 没有这个能力） | 否（静态判定） |
| pet_io.py:392 · read_json_fallback | except UnicodeDecodeError: text = "" for cand in fallback_encodings(): if is_single_byte_encoding(cand) and _almost_utf8(raw): continue # 单字节页 + "几乎就是 | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_io.py:531 · atomic_write_bytes | except PermissionError as e: # Windows 共享冲突：杀软/索引器/残留句柄瞬时锁住目标文件 last = e if i < attempts - 1: time.sleep(_RETRY_SLEEP) | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_io.py:583 · _read_json_status | except FileNotFoundError: return _default_from(factory, expect, log, path), False, False | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_lines.py:513 · LineService | except (TypeError, ValueError): order = 0 | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_log.py:63 · _quarantine | except Exception: return "" | ③ 确实该静默 | 理由码 self-logging：日志设施自身的兜底：写日志失败无处可记（代码内已有 stderr 出口） | 否（静态判定） |
| pet_log.py:76 · _rotate_if_needed | except Exception: return "" | ③ 确实该静默 | 理由码 self-logging：日志设施自身的兜底：写日志失败无处可记（代码内已有 stderr 出口） | 否（静态判定） |
| pet_log.py:81 · _rotate_if_needed | except Exception as e: if _quarantine(path): return "error.log 轮转失败（%r），已改名 error.log%s 重新开始" % (e, BAD_SUFFIX) return "error.log 轮转失败且无法改名（%r）" % (e, | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_main.py:36 · check_memory | except Exception: return True | ③ 确实该静默 | 理由码 probe：能力/存在性探针：失败本身就是安全的假值（is_running=False / 没有这个能力） | 否（静态判定） |
| pet_main.py:87 · has_pyinstaller_signature | except Exception: return False | ③ 确实该静默 | 理由码 probe：能力/存在性探针：失败本身就是安全的假值（is_running=False / 没有这个能力） | 否（静态判定） |
| pet_main.py:106 · acquire_single_instance | except Exception: return True | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_plugin.py:299 · validate_plugin_zip | except zipfile.BadZipFile: return _fail("文件不是有效的 zip 包") | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_plugin.py:301 · validate_plugin_zip | except Exception as e: # 权限/加密/半截文件… return _fail("打开失败：%s" % e) | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_plugin.py:315 · validate_plugin_zip | except Exception as e: return _fail("manifest.json 读不出来：%s" % e) | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_plugin.py:321 · validate_plugin_zip | except UnicodeDecodeError as e: return _fail("manifest.json 不是 UTF-8：%s" % e) | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_plugin.py:325 · validate_plugin_zip | except Exception as e: return _fail("manifest.json 无法解析：%s" % e) | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_plugin.py:430 · validate_plugin_zip | except Exception as e: return _fail("payload 条目读不出来（%s）：%s" % (n, e)) | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_plugin.py:459 · _read_json | except Exception as e: # 坏 JSON / 权限 / 半截文件… return None, "%s" % e | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_plugin.py:535 · read_installed | except OSError as e: problems.append("插件目录读不出来（%s）：%s" % (base, e)) return [], problems | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_plugin_host.py:178 · _norm_dir | except Exception: return os.path.normcase(text) | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_plugin_host.py:359 · _sha256_file | except Exception: return "" | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_plugin_host.py:491 · _fp_json | except Exception: text = repr(obj) | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_plugin_host.py:508 · _fp_file | except Exception: return "" | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_plugin_host.py:668 · _plan_prompts | except Exception: data = b"" | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_plugin_host.py:803 · PluginHost | except Exception: return None | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_plugin_host.py:866 · PluginHost | except Exception as e: return False, "无法创建插件目录：%s" % e | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_plugin_host.py:876 · PluginHost | except Exception as e: return False, "无法创建插件临时目录：%s" % e | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_plugin_host.py:880 · PluginHost | except Exception as e: return False, "解包失败：%s" % e | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_plugin_host.py:1060 · PluginHost | except Exception as e: # 目录没换成 = 这次回滚没成立：**先别撤内容**（撤了就两边都不对了），如实报错 return False, ("恢复上一版插件目录失败：%s——这次回滚没有生效，当前这一版仍在用" % e) | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_plugin_host.py:1108 · PluginHost | except Exception as e: # 兜底：清单读不出来也不该让对话框打不开 rows, problems = [], ["读取插件目录失败：%s" % e] | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_plugin_host.py:1274 · PluginHost | except Exception as e: return {}, "%s 归一化失败：%s" % (ROLE_PAYLOAD, e) | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_plugin_host.py:1298 · PluginHost | except Exception as e: _remove_files(written, self._log, drop_empty_parents=True) return {}, "写入角色素材失败：%s" % e | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_plugin_host.py:1485 · PluginHost | except Exception as e: self._rollback_behaviors(svc, added) return {}, "行为文件准备失败（%s）：%s" % (it["src"], e) | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_plugin_host.py:1612 · PluginHost | except Exception as e: return {}, "无法创建人设目录：%s" % e | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_plugin_host.py:1618 · PluginHost | except Exception as e: _remove_files(written, self._log, drop_empty_parents=True) return {}, "写入人设文件失败（%s）：%s" % (rel, e) | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_plugin_index.py:114 · default_fetch | except Exception as e: return None, "读取本地文件失败：%s" % e | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_plugin_index.py:126 · default_fetch | except (TypeError, ValueError): total = 0 | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_plugin_index.py:140 · default_fetch | except Exception as e: # URLError / HTTPError / 超时 / SSL… return None, "网络请求失败：%s" % e | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_plugin_index.py:153 · format_size | except (TypeError, ValueError): return "-" | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_plugin_index.py:391 · PluginIndex | except Exception as e: return None, "索引不是合法的 UTF-8 JSON：%s" % e | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_plugin_index.py:520 · PluginIndex | except Exception: return made | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_plugin_index.py:542 · PluginIndex | except Exception as e: # 注入的取数自己抛了：折成一句人话 return None, "取数失败：%r" % (e,) | ③ 确实该静默（领地外，只判定） | 理由码 ?： | 否（静态判定） |
| pet_resources.py:127 · _clamp01 | except (TypeError, ValueError): return default | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_resources.py:145 · _norm_offset | except (TypeError, ValueError): out[k] = 0 | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_resources.py:193 · _norm_procs | except (TypeError, ValueError): amp = d["amp"] | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_resources.py:197 · _norm_procs | except (TypeError, ValueError): period = d["period_ms"] | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_resources.py:295 · _probe_png | except Exception as e: return False, "无法读取：%s" % e | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_resources.py:310 · _probe_wav_ok | except Exception: return False | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_resources.py:661 · RoleLibrary | except Exception: return None | ③ 确实该静默 | 理由码 probe：能力/存在性探针：失败本身就是安全的假值（is_running=False / 没有这个能力） | 否（静态判定） |
| pet_resources.py:676 · RoleLibrary | except Exception: return None | ③ 确实该静默 | 理由码 probe：能力/存在性探针：失败本身就是安全的假值（is_running=False / 没有这个能力） | 否（静态判定） |
| pet_resources.py:703 · RoleLibrary | except Exception: out.append(None) | ③ 确实该静默 | 理由码 probe：能力/存在性探针：失败本身就是安全的假值（is_running=False / 没有这个能力） | 否（静态判定） |
| pet_resources.py:747 · RoleLibrary | except Exception: ok = False break | ③ 确实该静默 | 理由码 probe：能力/存在性探针：失败本身就是安全的假值（is_running=False / 没有这个能力） | 否（静态判定） |
| pet_resources.py:849 · RoleLibrary | except Exception: out.append(None) | ③ 确实该静默 | 理由码 probe：能力/存在性探针：失败本身就是安全的假值（is_running=False / 没有这个能力） | 否（静态判定） |
| pet_resources.py:902 · RoleLibrary | except Exception: return None, "无法读取文件大小" | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_resources.py:912 · RoleLibrary | except Exception as e: return None, "无法创建角色目录：%s" % e | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_resources.py:918 · RoleLibrary | except Exception: # v2.4.1（B 区 · A 档静默 except 判定）：这里的静默是**安全**的—— # 复制失败**不是被吞掉**，下一行就把 "复制文件失败" 返回给调用方 # （导入向导/界面会当场告诉用户）；except 里只做"删掉半截文件"的 # 尽力清理， | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_resources.py:950 · RoleLibrary | except Exception as e: return None, "导入失败：%s" % e | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_resources.py:986 · RoleLibrary | except Exception: return None, "无法读取文件大小" | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_resources.py:1001 · RoleLibrary | except Exception: return None, "无法读取文件大小" | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_resources.py:1017 · RoleLibrary | except Exception: return None, "无法读取文件大小" | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_resources.py:1024 · RoleLibrary | except Exception as e: return None, "无法创建角色目录：%s" % e | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_resources.py:1050 · RoleLibrary | except Exception: # v2.4.1（B 区 · A 档静默 except 判定）：不是吞掉——_cleanup_files 清掉 # 本次已复制的半成品（回滚），紧接着把 "复制文件失败" 返回调用方。 self._cleanup_files(dst_base, dst_full, | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_resources.py:1088 · RoleLibrary | except (TypeError, ValueError): interval_ms = None | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_resources.py:1098 · RoleLibrary | except Exception: # v2.4.1（B 区 · A 档静默 except 判定）：不是吞掉——先清掉本次复制的 # 半成品（回滚整个导入），紧接着把 "复制状态图失败" 返回调用方。 self._cleanup_files(dst_base, dst_full, *dst_fram | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_resources.py:1176 · RoleLibrary | except Exception as e: return None, "导入失败：%s" % e | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_resources.py:1185 · RoleLibrary | except Exception: return False | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_resources.py:1404 · AudioLibrary | except Exception: return None | ③ 确实该静默 | 理由码 probe：能力/存在性探针：失败本身就是安全的假值（is_running=False / 没有这个能力） | 否（静态判定） |
| pet_resources.py:1418 · AudioLibrary | except Exception: return None, "无法读取文件大小" | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_resources.py:1434 · AudioLibrary | except Exception as e: return None, "无法创建音频目录：%s" % e | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_resources.py:1440 · AudioLibrary | except Exception: # v2.4.1（B 区 · A 档静默 except 判定）：失败**已上报**（返回 "复制文件 # 失败" 给导入向导），这里只做半截文件清理；清理失败也只剩一个孤儿文件。 try: if os.path.exists(dst): os.remove(dst | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_resources.py:1468 · AudioLibrary | except Exception as e: return None, "导入失败：%s" % e | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_resources.py:1642 · VoiceAssetLibrary | except Exception: return None | ③ 确实该静默 | 理由码 probe：能力/存在性探针：失败本身就是安全的假值（is_running=False / 没有这个能力） | 否（静态判定） |
| pet_resources.py:1659 · VoiceAssetLibrary | except Exception: return None, "无法读取文件大小" | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_resources.py:1675 · VoiceAssetLibrary | except Exception as e: return None, "无法创建参考音目录：%s" % e | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_resources.py:1681 · VoiceAssetLibrary | except Exception: # v2.4.1（B 区 · A 档静默 except 判定）：失败**已上报**（返回 "复制文件 # 失败" 给导入向导），这里只做半截文件清理；清理失败也只剩一个孤儿文件。 try: if os.path.exists(dst): os.remove(dst | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_resources.py:1708 · VoiceAssetLibrary | except Exception as e: return None, "导入失败：%s" % e | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_screen.py:33 · screen_geometry_at | except Exception: screens = [] | ③ 确实该静默 | 理由码 probe：能力/存在性探针：失败本身就是安全的假值（is_running=False / 没有这个能力） | 否（静态判定） |
| pet_screen.py:39 · screen_geometry_at | except Exception: scr = None | ③ 确实该静默 | 理由码 probe：能力/存在性探针：失败本身就是安全的假值（is_running=False / 没有这个能力） | 否（静态判定） |
| pet_tools.py:275 · parse_call | except Exception: return name, None, call_id | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_tools.py:285 · args_json | except Exception: return "{}" | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_tools.py:295 · parse_args | except Exception: return {} | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_tools.py:304 · result_text | except Exception: txt = str(result) | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_tools.py:319 · _fmt_money | except (TypeError, ValueError): return "一笔账" | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_tools.py:344 · _describe_timer | except (TypeError, ValueError): span = "一会儿" | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_tools.py:412 · execute | except Exception as e: return {"ok": False, "error": "工具执行失败：%r" % (e,)} | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_voice.py:124 · VoiceBackend | except requests.exceptions.Timeout: return None, "连接后端超时（服务没启动或响应太慢）" | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_voice.py:126 · VoiceBackend | except requests.exceptions.ConnectionError: return None, "连不上后端服务（检查地址、服务是否已启动）" | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_voice.py:128 · VoiceBackend | except Exception as e: return None, "请求后端失败：%s" % e | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_voice.py:135 · VoiceBackend | except requests.exceptions.Timeout: return None, "连接后端超时（服务没启动或响应太慢）" | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_voice.py:137 · VoiceBackend | except requests.exceptions.ConnectionError: return None, "连不上后端服务（检查地址、服务是否已启动）" | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_voice.py:139 · VoiceBackend | except Exception as e: return None, "请求后端失败：%s" % e | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_voice.py:218 · F5TtsBackend | except Exception as e: return None, "读取参考音失败：%s" % e | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_voice.py:258 · CosyVoiceBackend | except Exception as e: return None, "读取参考音失败：%s" % e | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_voice.py:307 · MiniMaxBackend | except Exception as e: return None, "读取参考音失败：%s" % e | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_voice.py:317 · MiniMaxBackend | except Exception: file_id, _br = None, {} | ③ 确实该静默 | 理由码 probe：能力/存在性探针：失败本身就是安全的假值（is_running=False / 没有这个能力） | 否（静态判定） |
| pet_voice.py:342 · MiniMaxBackend | except Exception as e: return None, "MiniMax 克隆返回无法解析：%s" % e | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_voice.py:368 · MiniMaxBackend | except Exception as e: return None, "MiniMax 返回内容无法解析：%s" % e | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_voice.py:406 · ElevenLabsBackend | except Exception as e: return None, "读取参考音失败：%s" % e | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_voice.py:414 · ElevenLabsBackend | except Exception: voice_id = None | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_voice.py:488 · SapiBackend | except FileNotFoundError: return None, "系统没有 PowerShell，本地语音不可用" | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_voice.py:490 · SapiBackend | except subprocess.TimeoutExpired: return None, "本地语音合成超时" | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_voice.py:498 · SapiBackend | except Exception as e: return None, "读取合成结果失败：%s" % e | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_voice.py:567 · _audio_duration | except Exception: return 1.2 | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_voice.py:576 · _decode_json_audio | except Exception as e: return None, "%s 返回内容无法解析：%s" % (who, e) | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_voice.py:590 · _decode_json_audio | except Exception as e: return None, "%s 下载音频失败：%s" % (who, e) | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_voice.py:594 · _decode_json_audio | except Exception: raw = None | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_voice.py:619 · _decode_json_audio | except Exception as e: return None, "%s 下载音频失败：%s" % (who, e) | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_voice.py:625 · _decode_json_audio | except Exception as e: return None, "%s 读取音频失败：%s" % (who, e) | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_voice.py:703 · VoiceLauncher | except (TypeError, ValueError): return 0 | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_voice.py:723 · VoiceLauncher | except Exception: return False | ③ 确实该静默 | 理由码 probe：能力/存在性探针：失败本身就是安全的假值（is_running=False / 没有这个能力） | 否（静态判定） |
| pet_voice.py:726 · VoiceLauncher | except Exception: try: os.kill(pid, 0) return True except Exception: return False | ③ 确实该静默 | 理由码 probe：能力/存在性探针：失败本身就是安全的假值（is_running=False / 没有这个能力） | 否（静态判定） |
| pet_voice.py:730 · VoiceLauncher | except Exception: return False | ③ 确实该静默 | 理由码 probe：能力/存在性探针：失败本身就是安全的假值（is_running=False / 没有这个能力） | 否（静态判定） |
| pet_voice.py:770 · VoiceLauncher | except Exception: _ct = None | ③ 确实该静默 | 理由码 probe：能力/存在性探针：失败本身就是安全的假值（is_running=False / 没有这个能力） | 否（静态判定） |
| pet_voice.py:794 · VoiceLauncher | except Exception: kids = [] | ③ 确实该静默 | 理由码 cleanup：尽力而为的清理/回滚：失败只会在磁盘上留孤儿文件，不改变用户可见结果 | 否（静态判定） |
| pet_voice.py:834 · VoiceLauncher | except requests.exceptions.ConnectionError: last = "还连不上：%s" % base | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_voice.py:836 · VoiceLauncher | except requests.exceptions.Timeout: last = "探测超时：%s" % base | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_voice.py:838 · VoiceLauncher | except Exception as e: last = "探测失败：%s" % e | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_voice.py:1008 · VoiceService | except Exception as e: return False, "语音目录创建失败：%s" % e | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_voice.py:1044 · VoiceService | except Exception as e: return False, "导入失败：%s" % e | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_voice.py:1211 · VoiceService | except Exception: return False | ③ 确实该静默 | 理由码 probe：能力/存在性探针：失败本身就是安全的假值（is_running=False / 没有这个能力） | 否（静态判定） |
| pet_voice.py:1249 · VoiceService | except (TypeError, ValueError): cap = 400 | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_voice.py:1308 · VoiceService | except requests.exceptions.Timeout: return False, "服务无响应（超时）：确认已启动：%s" % base | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_voice.py:1310 · VoiceService | except requests.exceptions.ConnectionError: return False, "连不上服务：确认已启动：%s" % base | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_voice.py:1312 · VoiceService | except Exception as e: return False, "探测失败：%s" % e | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| pet_voice.py:1625 · normalize_voice | except (TypeError, ValueError): wait_s = 30 | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_voice.py:1636 · normalize_voice | except (TypeError, ValueError): cache_max = 400 | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_widgets.py:272 · Bubble | except Exception: font_size = 10 | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| pet_widgets.py:307 · Bubble | except Exception: border = QColor("#203170") bg = QColor("#ffffff") fg = QColor("#203170") font_size = 10 radius = 16 | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| 桌宠.py:367 · _parse_schema_version | except (TypeError, ValueError): return 1 | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| 桌宠.py:412 · load_config | except FileNotFoundError: # 兼容审查 L4：**首次运行**（还没有 config.json）不是错误，不该往 error.log 里写 # 吓人的"读取失败"。与 pet_resources._read_json 的"首次无文件=静默"口径保持一致。 set_redac | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| 桌宠.py:833 · PetWindow | except (TypeError, ValueError): pet_resources.FRAME_MAX = 24 | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| 桌宠.py:1262 · PetWindow | except Exception: pix = QPixmap() | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| 桌宠.py:1552 · PetWindow | except ValueError: return False | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| 桌宠.py:1611 · PetWindow | except (TypeError, ValueError): _secs = _d_secs | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| 桌宠.py:1682 · PetWindow | except (TypeError, ValueError): delay = 0 | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| 桌宠.py:1742 · PetWindow | except (TypeError, ValueError): _secs = IDLE_FORM_HOLD_SECS | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| 桌宠.py:2055 · PetWindow | except (TypeError, ValueError) as e: return False, "记账数据读不出来：%r" % (e,) | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| 桌宠.py:2163 · PetWindow | except (TypeError, ValueError): return {"ok": False, "error": "minutes 得是数字"} | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| 桌宠.py:2692 · PetWindow | except (OSError, TypeError, ValueError): return (str(path), None, None) | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| 桌宠.py:2729 · PetWindow | except Exception: return None | ③ 确实该静默 | 理由码 probe：能力/存在性探针：失败本身就是安全的假值（is_running=False / 没有这个能力） | 否（静态判定） |
| 桌宠.py:2937 · PetWindow | except Exception: # noqa: BLE001 superseded = True | ③ 确实该静默 | 理由码 optional：可选能力降级（音效/动画/缩放/预览/悬停提示）：失败＝该能力缺席，不丢数据 | 否（静态判定） |
| 桌宠.py:3748 · PetWindow | except Exception: _quit_now = False | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| 桌宠.py:4020 · PetWindow | except (TypeError, ValueError): _after_delay = 0 | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| 桌宠.py:4614 · PetWindow | except Exception as e: ok, msg = False, "等待后端就绪出错：%s" % e | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| 桌宠.py:4845 · PetWindow | except Exception: _empty = True | ③ 确实该静默 | 理由码 optional：可选能力降级（音效/动画/缩放/预览/悬停提示）：失败＝该能力缺席，不丢数据 | 否（静态判定） |
| 桌宠.py:4850 · PetWindow | except Exception: texts = [] | ③ 确实该静默 | 理由码 optional：可选能力降级（音效/动画/缩放/预览/悬停提示）：失败＝该能力缺席，不丢数据 | 否（静态判定） |
| 桌宠.py:4863 · PetWindow | except Exception: texts = [] | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| 桌宠.py:4870 · PetWindow | except Exception: return random.choice(fallback) if fallback else "" | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| 桌宠.py:5245 · is_autostart_enabled | except Exception: return False | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| 桌宠.py:5255 · set_autostart | except FileNotFoundError: # 目标键不存在（个别环境 Run 键缺失）：创建后写入，不把环境差异当错误 key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_SET_V | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |
| 桌宠.py:5268 · set_autostart | except Exception as e: return False, str(e) | ③ 确实该静默 | 理由码 reported：失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 | 否（静态判定） |
| 生成占位角色.py:12 · <module> | except AttributeError: RESAMPLE = Image.LANCZOS | ③ 确实该静默 | 理由码 fallback：坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 | 否（静态判定） |

### 3.1 白名单按理由码汇总（307 条）

> **条数演变（v2.6.0 第 4 轮收口实跑）**：首轮快照是 **222** 条，本轮把原先整体豁免的 4 个领地外文件
> （pet_plugin.py / pet_plugin_host.py / pet_plugin_index.py / pet_dialogs.py，DELEGATED_FILES 已清空）逐条收编进来 **+85** 条 → **307** 条。
> 下表两列都按 307 条这一版数据重读（B 档 handler 覆盖数同样按收口后的实跑扫描算）。

条目数＝白名单条目；B 档 handler 数＝该理由码**覆盖到**的 B 档 handler 个数（一个条目可覆盖多个同形状 handler，所以这一列不必等于条目数）。

| 理由码 | 条目数 | 覆盖的 B 档 handler 数 | 为什么该静默（闭集口径） |
|---|---|---|---|
| reported | 81 | 119 | 失败已随返回值/哨兵上报调用方（调用方据此弹提示或降级），不需要再写一条日志 |
| fallback | 81 | 80 | 坏值回默认（反序列化/归一化/类型转换）：不改变用户可见结果 |
| probe | 44 | 33 | 能力/存在性探针：失败本身就是安全的假值（is_running=False / 没有这个能力） |
| optional | 32 | 12 | 可选能力降级（音效/动画/缩放/预览/悬停提示）：失败＝该能力缺席，不丢数据 |
| teardown | 25 | 2 | 关闭/退出/销毁路径：进程即将结束或对象即将销毁，记日志没有接收方 |
| cleanup | 23 | 3 | 尽力而为的清理/回滚：失败只会在磁盘上留孤儿文件，不改变用户可见结果 |
| self-logging | 21 | 2 | 日志设施自身的兜底：写日志失败无处可记（代码内已有 stderr 出口） |

## 4. 代码改动清单（每条都有能真失败的用例 + 变异验证）

| 类型 | 位置 | 改前（现行为） | 改后 | 用例 |
|---|---|---|---|---|
| ① | pet_config.py:124 · decrypt_secret | DPAPI 解密失败静默 return 空串（与「从没设过 Key」在界面上完全一样） | pet_log.log_throttled("config.decrypt_secret", …)，返回值口径不变 | tests/test_silent_except_v252.py::test_decrypt_secret_failure_is_logged |
| ① | pet_resources.py:872 · RoleLibrary.stage_file | 复制失败静默 return None（异常原文被丢，调用方只报「写入角色目录失败」） | pet_log.log_throttled("role.stage_file", …)，返回值口径不变 | tests/test_silent_except_v252.py::test_role_stage_file_failure_is_logged |
| ① | pet_audio.py:294 · preview_file | 试听失败静默 return False（用户点了没声音，日志里也没线索） | pet_log.log_throttled("audio.preview_file", …)，返回值口径不变 | tests/test_silent_except_v252.py::test_audio_preview_failure_is_logged |
| ① | 桌宠.py:4768 · PetWindow.preview_audio | 两条链路（winsound → QMediaPlayer）都失败时静默 return False | pet_log.log_throttled("preview_audio:<路径>", …)（按文件路径限流） | tests/test_silent_except_v252.py::test_window_preview_audio_failure_is_logged |
| ① | 桌宠.py:522 · _persona_file_text | 人设文件读不出来静默 return None（调用方直接回退内置人设，用户只觉得「人设自己变了」） | 只对**用户自建**人设（file: 前缀）记限流日志；内置预设没有同名文件是设计行为，不记 | tests/test_silent_except_v252.py::test_persona_file_text_logs_only_for_custom_personas |
| ② | pet_tools.py:361 · describe_call | 确认文案拼不出来 → detail 置空 → 通用问法「想调用「记一笔」，可以吗？」（这是 AI 写入类工具的**确认框正文**，用户看不到要写什么就点了确认） | 退回**带参数的保守文案**（把参数原样带给用户看）+ 限流日志 | tests/test_silent_except_v252.py::test_describe_call_keeps_args_when_describe_raises |
| 口径 | pet_log.py:91 / 桌宠.py:695 · guard_slot / _log_slot_error | 「同名 60s 一条」在仓里有三份各自实现（_SLOT_SEEN / _SLOT_ERR_SEEN / keep_source） | pet_log.log_throttled 成为单一实现，guard_slot 收敛到它；桌宠._log_slot_error **本轮有意不动**（它的 except 是有意义的兜底，改了会多一个静默点） | tests/test_silent_except_v252.py::test_guard_slot_still_throttles_after_refactor |

### 4.3 新增的限流出口

- pet_log.log_throttled(key, msg, gap=60.0, now=None, **log_kw)：**唯一的公共实现**（返回 True/False 表示这条有没有落盘，now 可注入 → 用例断言不依赖机器速度）。
  > v2.6.0 第 4 轮（找茬审查实测）更正：说它是"全仓唯一的「同名 60s 一条」实现"**不准确**——本轮
  > 只**收敛了 guard_slot 一处**，仓里还有 **3 处手写的同口径**没动：`pet_resources.py:337,361-365`
  > （`_SOURCE_FAIL_SEEN`）· `桌宠.py:712-713`（`_SLOT_ERR_SEEN`）· `桌宠.py:5204-5205`
  > （`_EXC_BOX_SEEN`）。三者**留待下一轮**：改它们要么多出一个纯静默 except（前两处），要么是
  > 异常钩子自己的兜底（第三处），不在本轮"消灭静默"的主题里硬凑口径统一。
- pet_log.guard_slot 收敛到它（行为逐位不变：同一槽名 60s 一条、文案含 traceback）。
- 桌宠._log_slot_error 与 pet_resources._SOURCE_FAIL_SEEN **本轮有意不动**：前者的 except 是有意义的兜底（取不到 traceback 也要记一行），改成调 log_throttled 会多出一个纯静默 except——本轮主题正是消灭静默，不为「口径统一」制造新的静默点。两者都写进了白名单（理由码 self-logging），留给下一轮。

## 5. 白名单与 razor（任务书硬要求 a）

- **数据**：_dev/silent_except_whitelist_summary.json，**307** 条（首轮快照 222 条 + 本轮收编的 85 条，见 §3.1 的条数演变），字段 key/file/func/shape/count/tier/reason/why/evidence/lines；why 就是「为什么该静默」的那句话（数据自带，不必回头查代码）。
- **键 = (文件, 函数, 结构指纹)**：指纹把标识符/常量/消息文本匿名化后取 AST 的 sha1 前 10 位——改文案、改变量名不会误报；把 return 错误文案改成 pass、或新增一个静默 except，一定报。
- **razor 的判定**（_dev/silent_except_whitelist.py 的 check()，测试与 CLI 同一实现）：
  1. 生产路径每个静默 except（= 审计的 B ∪ C）都必须命中白名单条目，且 count 一致；
  2. 白名单条目必须仍对应活代码（失效条目 → 红）；
  3. 理由码必须来自闭集；unreviewed 占位 → 红（--write 只登记占位，必须有人给真理由）；
  4. 每条都要有源码证据；
  5. A 档必须为 0（覆盖全仓，含领地外）。
- **razor 不是空转**（用例自带合成反例）：新写一个静默 except → 报「未登记」；同一个 except 补上日志 → 不再报；伪造失效条目 → 报「已失效」；把某条理由改成 unreviewed → 报占位。见 tests/test_silent_except_v252.py。
- **领地外 4 个文件**（pet_plugin.py、pet_plugin_host.py、pet_plugin_index.py、pet_dialogs.py）：本轮**不钉**静默清单（代理 A/C 正在改，钉了就是天天假红），但仍在「A 档 = 0」的管辖内。下一轮把 DELEGATED_FILES 清空即自动纳入。

## 6. A 档 = 0 的实测

实测 **A = 0**（python -B _dev/audit_silent_except.py 与 razor 用例各跑一次，两者都覆盖全仓生产路径，含代理 A/C 的文件）。

## 7. 变异验证（把每处改动还原成旧行为 → 用例必须红）

跑法：python -B _dev/mutate_check.py _dev/mutations_silent_except_v260.json（19 条 spec：影子副本 + 运行锁 + expect_fail 判定 + 结果 JSON 带 repo_fingerprint；原 12 条变异里 8 条改产品代码、4 条改白名单数据，本轮再补 7 条）。结果见 §8。

> **v2.6.0 第 4 轮（找茬审查 B-5）迁移说明**：上面这条命令取代了原来"原地覆写真仓"的
> python -B _dev/silent_except_mutate.py —— 那条跑法**作废**：它不写运行锁、中断会截断
> 白名单数据、判定只看 rc、也没有结果 JSON（发布门看不见）。原 12 条已迁成 _mutate_lib
> 的 spec 形态，并补上本轮 7 条，共 **19 条 / 19 CAUGHT**。
> _dev/silent_except_mutate.py 现在是一个**停用桩**：再跑它只会打印这句迁移说明。

## 8. 护栏读数（收尾实跑）

跑法：安静窗口串行（先确认 _dev/.mutation.lock 里没有活着的变异进程）——pytest 全量 → v13 → 静态，各自单跑。当次工作树含并行代理 A/C 的在制品。

| 护栏 | 读数 |
|---|---|
| pytest tests -o addopts="" -q | **1025 passed**（0 failed；基线 948，本轮三路新增用例 +77） |
| python -B _verify_v13.py | **273 checks / 0 FAILS**（V13 VERIFY ALL OK） |
| python -B _check_static.py | **0 问题 0 待确认**（单跑） |

## 9. 没做到 / 有疑问（如实列）

1. **只有 7 处做了行为实测**，其余 241 条是静态判定。判据是 handler 原文 + 审计工具的档位规则（可复核），但「调用方到底会不会把错误显示给用户」这一步静态看不到——这正是审计工具文件头写明的已知盲区。下一轮可以补「全量调用方核对」。
2. **领地外 60 条只判定、不登记进 razor**，见 §5 最后一条。
3. **限流口径还剩两份老实现**（桌宠._log_slot_error / pet_resources._SOURCE_FAIL_SEEN），本轮有意不动，理由见 §4.3。
4. **任务书的 219/211 复现不出来**，见 §1。
5. 白名单是「数据 + 理由码」，它能防「悄悄新增」，**防不住「有人睁着眼写一个假理由」**——那需要人看报告，机器没法代劳。
