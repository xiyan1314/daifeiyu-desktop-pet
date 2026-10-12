# v2.6.0 代理 C 完工报告：门禁与文档收口

> 任务书：_dev/task_v260.md 的「代理 C」一节（第 4 轮 · 三路并行）。认领：T-038（agent-C-v260）。
> 领地：`pet_plugin.py` / `_check_release.py` / `_dev/_mutate_lib.py` / `plugins/README.md` /
> `_dev/*.md` / `tests/test_release_check.py` / `tests/test_plugin_v251.py`。
> 为了让"官方包验收"这条既有证据链仍然成立，另同步了 `_dev/plugin_pack_rules.py`（参照实现）、
> `_dev/verify_plugin_packs_v251.py`（验收脚本）与 `_dev/build_official_plugins.py` 的过期 docstring。
> **未提交**（铁律 6，主代理统一提交）；VERSION / version_info.txt / _verify_green.py / CHANGELOG.md /
> 绿色版 / 发布 zip 一个字节没碰。

> **主代理裁决（2026-10-12，四条待定全部有结论）**：① 14 份缺键老证据**定版批次统一复跑**
> （锁树后一次跑完 17 份；本代理不动手，报告如实记"缺键、尚未复跑、定版处理"）；
> ② `files: []` 一律拒**采纳**（写进发布说明成为 v1 格式规则："不存在合法空数据插件"）；
> ③ `plugins/README.md` 的市场一节**口径可接受**，定版前由 A 与本节约一次；
> ④ `_dev/_mutate_lib.py` 没动是对的，绿色版/发布包/提交都等定版（铁律 6）。

## 零、结论先行

1. **两处口径差收口**：`payload/a:b.png`（Windows 非法字符）与 `files: []`（空 payload）
   现在**校验器先拒**、安装器不再"晚一步拒"；**5 个官方包仍全部通过**（验收脚本 70/70，
   含 5 条正向 + 5 条两引擎交叉核对）；8 条定向变异 **8/8 CAUGHT**。
2. **发布门能提示"这份证据缺这些键"**（汇总一行、**只提示不挡发布**）：实测 **14 份**老证据各缺
   4 个键（`pet_plugin.py` / `pet_plugin_host.py` / `pet_dialogs.py` / `pet_menu.py`）。
3. **文档同步**：12 条判据文档、`plugin_packs_report.md`（890 → 948 的口径更正）、
   `build_official_plugins.py` 过期 docstring、`_dev/README.md`（两条新铁律 + 本轮登记）。

## 一、改动清单

| 文件 | 改了什么 |
|---|---|
| `pet_plugin.py` | 判据 4 新增**Windows 非法字符** `<>:"|?*`（`WIN_ILLEGAL_CHARS`）与**保留设备名**（`WIN_RESERVED_NAMES`：任意路径段、大小写不敏感、**带扩展名一样算**）；判据 10 新增**空 `files` 一律拒**；`_WIN_RESERVED` → `WIN_RESERVED_NAMES`（id 判据与条目名判据**共用一份**）；模块 docstring 的判据 4/10 同步 |
| `_check_release.py` | 新增纯函数 `missing_fingerprint_keys(recorded, current)`；`mutation_evidence_notes()` 多出**一条汇总提示**（缺键的份数 + 缺哪些键）；头部 docstring 登记 |
| `tests/test_plugin_v251.py` | +9 条用例（28 个参数化实例）：非法字符逐字符 + 合法名字控制组 · 保留设备名 7 种形状 + 6 个近似名字不误伤 · 空 files 两种形状 + 控制组 · payload_root 含非法字符/设备名 · **跨口径双侧用例** · **文档双向契约**；本文件 75 → **103 passed** |
| `tests/test_release_check.py` | +2 条用例（缺键纯函数 + 发布门提示，含"补齐两个键即归零"控制组）；本文件 33 → **35 passed** |
| `_dev/plugin_format_v251.md` | §1 新增两条 Windows 名字判据（含 43 个设备名的**完整清单**）；§5 新增"`files: []` 一律拒"与"校验器是唯一真源 / 契约双向覆盖" |
| `_dev/plugin_pack_rules.py` | 参照实现同步两条新判据——两个引擎对同一批名字**结论仍逐条一致** |
| `_dev/verify_plugin_packs_v251.py` | +8 条检查（2 条**真 zip** 反向变异 + 6 条单元级交叉核对）；62 → **70 条 PASS 70 / FAIL 0** |
| `_dev/mutations_plugin_gap_v260.json` | 新增定向变异 spec（8 条；**8/8 CAUGHT**） |
| `_dev/probe_plugin_gap_v260.py` | 新增复现探针（`--before` 模拟旧判定，见 §二） |
| `_dev/probe_fingerprint_gap_v260.py` | 新增"缺键影响面"只读探针 |
| `_dev/plugin_packs_report.md` | §七/§八 的 890 更正为"v2.5.1 定版基线 **948**，v2.6.0 起**基线以当轮实测为准**"；新增 §九 v2.6.0 增量 |
| `_dev/build_official_plugins.py` | 过期 docstring 按代码改正（role 包是 `payload/role.json` + 素材 png 平铺，**不是**标准 dfypet-role 角色包那套 `roles/`） |
| `_dev/README.md` | §零「两条铁律」→「**四条**铁律」（新增铁律 3「断言不许依赖机器速度」、铁律 4「契约必须双向覆盖」，各带实测出处）；指纹小节补"缺键提示"；§一 spec 表 / §二 探针表 / §六 报告表登记本轮新增 |

## 二、1 号活：校验器与安装器两处口径差（实测，收口前后对照）

复跑：`python -B _dev/probe_plugin_gap_v260.py --before`（模拟 v2.5.1 判定）与
`python -B _dev/probe_plugin_gap_v260.py`（当前树）。原始输出：`_dev/_probe_before_v260.txt` /
`_dev/_probe_out_v260.txt`（两者都在 .gitignore 覆盖范围内，报告里贴了全文要点）。

| 形状 | 收口前（`--before`） | 收口后（当前树） |
|---|---|---|
| `payload/a:b.png` | 校验器**通过**（err=`''`）；安装器 `ok=False 解包失败：条目解包后越界：payload/a:b.png` | 两侧同一句：`插件包含不安全的条目名（条目名含 Windows 非法字符 ':'）：'payload/a:b.png'` |
| `payload/con.png`（保留设备名） | 校验器**通过**；安装器也只是因为没接线 lines_lib 才失败（**与设备名无关**） | 两侧同一句：`…（条目名含 Windows 保留设备名：'con.png'）…` |
| `files: []`（带 / 不带 `payload/` 目录条目） | 校验器**通过**；安装器 `插件包里没有 payload 目录（payload_root='payload/'）` | 两侧同一句：`插件包校验和不对：files 清单是空的…` |
| 控制组（一个正常 `payload/a.txt`） | 校验器通过 | 校验器通过（**不许误伤**，两侧都用同一条控制组钉住） |

**判据落点**

* 判据 4（`_unsafe_name_reason`）：全量 namelist 逐条 + `payload_root + "x"` 各走一遍——
  payload_root 是解包时的根前缀，它自己也要过同一套名字判据。
* 判据 10（`_files_problems`）：空表判断**有意放在覆盖判据之后**——payload 里有文件、files 却是
  空表时，上面那句"payload 下有文件没进 files 清单"更准确。第一版实现放在前面，把
  `verify_plugin_packs_v251.py` 那条既有反向变异挤红了（它按"没进 files"断言），已按实测改正。

**影响面（任务书点名要确认的）**：**5 个官方包与打包工具产物零影响**——包内条目名全是 ASCII /
中文，无非法字符、无设备名、payload 非空。受影响的是审查期造的**合成**反例包（本来就该拒）。

**契约双向覆盖（新铁律 4 的第一个落点）**：
`tests/test_plugin_v251.py::test_口径差_校验器先拒_安装器不留残余` 同时钉两侧——
校验器必须 `(None, 非空原因)`，安装器必须 `ok=False`、**拒绝理由就是校验器那句**、且
`plugins/` 下零残余（校验先于建目录）。变异 M-G8（把安装器那句"交出原因"的早退改掉）→ 该用例红。

## 三、2 号活：发布门"这份证据缺这些键"提示

* **背景**：`stale_fingerprints()` 只比对"记录里**存在**的键"。v2.5.1 给清单补的四个模块
  （`pet_plugin.py` / `pet_plugin_host.py` / `pet_dialogs.py` / `pet_menu.py`）在**已经在盘上**的老
  证据里等于不存在——改这四个文件，发布门一条提示都不会有（补清单那次留下的后半截盲区）。
* **实现**：`missing_fingerprint_keys(recorded, current)` 只认**当前树里真的存在**的文件
  （树里没有的文件本来就算不出指纹）；`mutation_evidence_notes()` 把结果**汇总成一行**。
* **只提示、不挡发布**：与"指纹过期"同一条 notes 通道（`main()` 里 `[提示]` 那一排），
  不进 `fails`。
* **取舍（任务书要求说明）**：一份证据一行会把门禁刷成 **14 行**噪音，结论完全一样，所以选**汇总一行**。
  这条提示在**老证据重跑之前会一直在**——这是有意的："缺键"不是错误，是**这份证据不覆盖这几个模块**
  这个事实；消掉它只有两条路：重跑对应 spec 让指纹补齐，或在报告里点名不覆盖。两条都行，但不许当没看见。
* **实测影响面**（`python -B _dev/probe_fingerprint_gap_v260.py`，2026-10-12 收口后）：
  有指纹段的证据 **17 份**，其中 **14 份缺键**（各缺那 4 个）·**17 份"指纹过期"**
  （多路并行改树窗口里的正常中间态：`_check_release.py` 是我改的、`pet_export.py`/`桌宠.py` 是
  A/B 正在改的）。发布门现在输出 **18 条提示 = 17 条过期 + 1 条缺键汇总**（此前是 17 条）。
* **能真失败**：`tests/test_release_check.py::test_mutation_evidence_notes_flags_evidence_missing_keys`
  （+ 纯函数那条）；变异 M-G4 / M-G5 都 CAUGHT。控制组：把键补齐 → 提示归零（不许变成常驻噪音）。

## 四、3 / 4 号活：文档同步与登记

* `_dev/plugin_format_v251.md`：两条新判据写死（含 43 个设备名完整清单），由
  `test_windows名字判据与文档同时写死` **双向**钉住（常量里少一个 → 红；文档里多写 `com10` → 也红）。
* `_dev/plugin_packs_report.md`：890 → **948** 口径更正（§七 §八 保留历史读数并注明"v2.5.1 定版
  基线 948；v2.6.0 起**基线以当轮实测为准**"），另加 §九 v2.6.0 增量（70/70 · 8/8 · 影响面）。
* `_dev/build_official_plugins.py`：过期 docstring 按代码改正。
* `_dev/README.md`：两条新铁律 + 本轮新增的 spec / 探针 / 报告全部登记（`run` 命令都写了）。
* `plugins/README.md`：把 v2.5.1 那节"装 / 卸 / 重装的账"**重写**成 v2.6.0 的市场口径
  （索引从哪来 / 下载与校验 / 更新按内容指纹合并 / 回滚撤销新版新增且不碰用户数据 / 卸载保留用户数据 /
  禁用只改登记 / 可不可装给出人话原因 / 老登记补账）；「包的格式与红线（速查）」补两条名字判据。
  口径来源是 **A 当前代码**（不是凭任务书猜），风险见 §六.3。
  **A 完工后的补正（2026-10-12，主代理转达）**：`「更新」` 那条补了一句「**同一版本且内容完全一致的
  重复安装不挪目录、也不轮换回滚点**」——A 的探针抓到的 bug ①：v1 更新到 v2 后再重复装一次 v2，
  会把上一版回滚点顶掉，用户以为能回到 v1、实际只能回到 v2。落笔前按 `pet_plugin_host.py` 的
  `repeat` 分支（`already and added == 0 and skipped > 0 and same_version` 时不 `os.replace`
  到 `.prev-<id>/`）核对过，**只加了这一句，该文件其余内容没动**。
* `_dev/dialog_size_report.md`：A 把 `PluginManagerDialog` 的设计尺寸从 760x520 改成 **860x560**，
  第 3.1 节补上这一行（表头 14 → **15 个**）——这是"三处同步"里的第三处，`.md` 归我。

## 五、三项护栏（实跑）

三条命令在**一个后台作业里串行**跑（2026-10-12 10:00–10:06），跑之前确认过
`_dev/.mutation.lock` **不存在**（铁律 2）；原始输出在 `%TEMP%\agentC_v260_gates\{pytest,v13,static}.txt`。

| 门 | 命令 | 结果 |
|---|---|---|
| pytest | `python -B -m pytest tests -o addopts="" -q` | **976 passed / 2 failed**（105.14s）——两条红**都不是代理 C 的**，见下 |
| v13 | `python -B _verify_v13.py` | **TOTAL CHECKS: 273, FAILS: 0** |
| 静态 | `python -B _check_static.py`（单跑） | **问题 0 条 / 待确认 0 条** |

* **两条 pytest 红是代理 B 的在制品**（与 C 的改动无关）：`pet_tools.py` 被 B 改了
  （类型注解 39 → 40 条），而 `README.md` 里那行标注还是 `39/39` →
  `tests/test_deadcode_types_v241.py::test_pinned_annotations_are_complete` 与
  `tests/test_round3_a_fixes.py::test_readme_annotation_scope_matches_the_code` 红。
  C 的领地全绿：`tests/test_plugin_v251.py` **103 passed**、`tests/test_release_check.py` **35 passed**、
  `_dev/verify_plugin_packs_v251.py` **70/70**、`_dev/mutate_check.py _dev/mutations_plugin_gap_v260.json` **8/8 CAUGHT**。
* ⚠️ 口径：这次跑在**多路并行改树**的窗口里（A 正在写市场页、B 正在写静默 except 白名单），
  按铁律 1 只作"当时读数"，**定版必须由主代理在安静窗口串行复跑**。

## 六、没做到 / 有疑问（如实）

1. **三项护栏跑在多路并行窗口里**：pytest 那 2 条红是 B 的在制品（见 §五）。定版数字以主代理的
   安静窗口复跑为准。
2. **14 份"缺键"的老证据尚未复跑**：我完工时它们的状态是"缺 4 个键、且指纹过期"，
   发布门上那条**缺键汇总是提示级、不会挡发布**。重跑会把它们的 `checked_at` 与指纹改成
   复跑那一刻的读数——**证据必须对着出货修订**，所以这件事留给定版批次做：
   **主代理 2026-10-12 裁决：锁树后的收尾批次里一次跑完这 17 份**（复用 `_dev/mutate_check.py`
   + 三个单脚本驱动），**不需要本代理再动手**；本报告如实记下"这 14 份缺键、尚未复跑、
   定版批次会处理"。在此之前看到这条提示请按提示理解：**这份证据不覆盖那四个模块**。
3. **`plugins/README.md` 的市场一节是按 A 当前代码写的**（依据：`pet_plugin_index.py` 的 docstring、
   `PluginManagerDialog` 的按钮/文案、`pet_plugin_host.rollback()` 与 `.prev-<id>` 的实现）。
   我完工时 A 的 `tests/test_plugin_market_v252.py` 还没进树——**主代理 2026-10-12 裁决：口径可接受，
   已提醒 A"改文案要回头对一遍"，定版前让 A 与本节对一次**。
4. **`_dev/_mutate_lib.py` 一行没动**：任务书把它列进了我的领地，但本轮它确实没有需要改的地方
   （清单与 `_check_release.MUTATION_FINGERPRINT_FILES` 逐项一致，由既有用例钉住）。
5. **绿色版 / 发布包一个字节没碰**（铁律 6）：绿色版里的 `pet_plugin.py` 等还没同步本轮改动，
   那是发布流程的事——等主代理定版时统一做。
6. **一条口径上的取舍（主代理 2026-10-12 裁决：采纳）**：`files: []` 按任务书原文实现成
   **一律拒**。代价是"合法的空数据插件"这种形态在 v1 格式里**不存在了**——裁决理由：空数据插件
   没有真实用途，而且它消除了一处歧义（"没有 payload"与"没进清单"两种解释）；会写进发布说明成为
   **格式规则**（v1 格式不存在合法空数据插件）。5 个官方包与打包工具不受影响（它们都有 payload 文件）。
