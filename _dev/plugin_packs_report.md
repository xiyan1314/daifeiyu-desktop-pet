# 官方内容插件与索引 · 代理 C 完工报告（v2.5.1）

> 任务书：_dev/task_v251.md 的「代理 C」一节。领地：plugins/**、_dev/**、README.md 的插件小节。
> 结论先行：**5 个官方包全部上架**（plugins/index.json），每个包都过代理 A 的 12 条判据校验器
> （返回 (manifest, "")），并且**每个都真的装得上**——构建期就在临时数据目录里走代理 B 的
> pet_plugin_host.PluginHost.install_zip 真装一次，宿主库必须真的多出内容，否则打包工具非零退出。

## 一、改动清单（全部是新增；产品代码与 tests 一行未动）

| 文件 | 是什么 |
|---|---|
| plugins/index.json | 官方索引（5 个插件，每条含 id/name/kind/data_kind/code/summary/author/releases[]） |
| plugins/packs/official-audio-core-1.0.0.dfypet-plugin.zip | 官方·基础音效（6 段），168,925 B |
| plugins/packs/official-lines-moyu-1.0.0.dfypet-plugin.zip | 官方·摸鱼台词（12 条 + 1 组对白），1,970 B |
| plugins/packs/official-role-daifeiyu-1.0.0.dfypet-plugin.zip | 官方·大肥鱼角色包（双形态 + 17 张表情），1,213,323 B |
| plugins/packs/official-behaviors-idle-1.0.0.dfypet-plugin.zip | 官方·待机行为（4 条），2,591 B |
| plugins/packs/official-persona-moyu-1.0.0.dfypet-plugin.zip | 官方·人设「摸鱼搭子」，1,314 B |
| plugins/README.md | 官方内容的门面：5 个包逐条「包含什么 / 多大 / 装上会看到什么 / 包内结构 / 落地方式」+ 索引与包格式速查 |
| _dev/build_official_plugins.py | **打包工具**（可复跑、幂等；输出 5 个包 + index.json） |
| _dev/plugin_pack_rules.py | 12 条判据的**参照实现**（A 未落地前的尺子；A 落地后优先调它并做交叉核对）+ 确定性 zip 读写 |
| _dev/verify_plugin_packs_v251.py | 验收脚本：正向 + **26 条反向变异** + 索引自洽 + 上架门槛 + 幂等 |
| _dev/probe_plugin_landing_v251.py | 五类 data_kind 的**宿主接口落地**实测（不经过安装器） |
| _dev/probe_plugin_install_v251.py | **端到端**：索引 → 包 → 真安装器 → 宿主库 → 卸载/禁用/重装 |
| README.md（只加一节「🧩 官方内容插件（PetHub · v2.5.1）」） | 5 个包的一句话说明 + 红线 + 入口路径 |
| .gitignore（+2 行） | 主代理特批：!plugins/packs/*.zip —— 仓库原来 *.zip 全忽略，官方包会被吞掉 |

产出总量：5 个包合计 **1,388,123 B**；index.json 3,597 B；plugins/README.md 9,998 B。
（数字取自最终一次复跑的 index.json 与磁盘，二者逐字节一致。）

## 二、验收数字（全部来自实跑，命令可复跑）

| 检查 | 命令 | 结果 |
|---|---|---|
| 打包（含**每包真安装**自检） | python -B _dev/build_official_plugins.py | 5 个包全过校验器 + 全装得上（脚本非零退出即失败） |
| 幂等复跑 | python -B _dev/build_official_plugins.py --check | **产物与 plugins/ 逐字节相同** |
| 官方包验收 | python -B _dev/verify_plugin_packs_v251.py | **62 条检查 PASS 62 / FAIL 0**（含 26 条反向变异、索引自洽、上架门槛、幂等） |
| 五类落地实测 | python -B _dev/probe_plugin_landing_v251.py | **29 条检查 PASS 29 / FAIL 0** |
| 端到端链路 | python -B _dev/probe_plugin_install_v251.py | **20 条检查 PASS 20 / FAIL 0** |

反向变异的 26 条（每条都必须被拒，能真失败）：files 少一条 / sha256 改一位 / bytes 改一位 /
files 多列 manifest.json / payload 多一个文件 / 塞 evil.py / 塞 nested.zip / 塞 tool.exe /
条目名含 .. / 条目名含反斜杠 / manifest 带 BOM / 非 UTF-8 / 坏 JSON / 缺 manifest.json /
根本不是 zip / format 错 / 顶层 version=2 / 顶层 version="1" / 缺 plugin 段 / payload_root 不以 / 结尾 /
执行位 0o755 / 符号链接 0o120777 / kind=data 却 code=true / code=0 非 bool / kind=ui / kind=未知 /
capabilities 越界 network / capabilities 越界 fx / min_host_version=99.0.0 / api_version=2 /
data_kind=fx / plugin.id 含空格 / plugin.id 保留名 con / 条目数 2002 > 2000。
另有一条**正例**：包里带目录条目（0o40775）**必须仍然通过**（A 实测踩过的误拒点）。

## 三、每个包的真实哈希（index.json 与包逐字节对得上，由验收脚本逐条核对）

| 包 id | data_kind | bytes | sha256 |
|---|---|---|---|
| official-audio-core | audio | 168925 | 34598eb94818786b80ecedd5102ff306af1fa2feeac61b64f2602a37d31ca18e |
| official-lines-moyu | lines | 1970 | e46d1ca67554bcb6fcb4fd80c922491088cc48bcae6a7e9efc17521fc4b978bd |
| official-role-daifeiyu | role | 1213323 | d222070f5a4ecddf424f7202a071d310eb0f793dab2d490eaadeb5e066a7d58c |
| official-behaviors-idle | behaviors | 2591 | 1806fe25ba97d8c0259809a097c915a9091b059288025663608aec244e9528b0 |
| official-persona-moyu | prompt | 1314 | e7ca0a6f02cdd3892fbf062bb5cffbff53ec95c467749c3e7dfdc16aca450d9f |

## 四、每类「能不能落地」的实测证据（任务书与主代理要求的 ①②③）

| data_kind | 宿主落地接口 | ① 我的实测证据（探针 + 条数） | ② 能否过 B 的安装器 | 备齐的包 |
|---|---|---|---|---|
| audio | pet_resources.AudioLibrary.import_file | probe_plugin_landing：5 条 PASS（6 段全落地、原有片段一条不少、显示名正确、fragment_path 取得到） | **能**（install_zip 返回 ok，落地核对 audio +6） | official-audio-core |
| lines | pet_lines.LineService.add + add_dialogue | probe_plugin_landing：6 条 PASS（12 条台词 + 1 组对白，原有 89 条不动，类别合法） | **能**（lines +12、对白 +1；探针 89 → 101） | official-lines-moyu |
| role | pet_export.land_role + _remap_role_files（与「导入角色包」同一套） | probe_plugin_landing：7 条 PASS（双形态、常态 10 / 吃饱 7 状态图按生产查表 form_state_paths 全取到、重复导入换新 id、预置角色没被动过） | **能**（role +1） | official-role-daifeiyu |
| behaviors | pet_behaviors.BehaviorService.import_file | probe_plugin_landing：6 条 PASS（4 条落地、原有行为一条不少、逐条过 validate_steps 与 validate_name） | **能**（behaviors +4） | official-behaviors-idle |
| prompt | 拷进 数据目录/prompts/custom/ + 桌宠.persona_file_ids 的发现规则 | probe_plugin_landing：4 条 PASS（落地、发现规则认得出 file:摸鱼搭子、原有人设仍在、文本是 UTF-8 非空） | **能**（prompt +1） | official-persona-moyu |

**③ 哪类接不上：没有。** 五类的宿主接口与安装器落地本轮都实测通过。
途中一度只有 role / lines 能过安装器——那不是"接不上"，是**安装器当时还没接**（LANDING_KINDS 只列了两类），
我把这个发现与每类的确切 payload 形状报给主代理后，B 在同一轮补上了 audio / voice_ref / behaviors / prompt。

语音参考音（voice_ref）这一类**我没做包**：现有素材里没有合适的参考音（assets/sounds 全是效果音），
硬凑一份就是假内容——这一类留给有真实素材的时候再做。

## 五、踩到的坑（写给下一轮，每条都是实测）

1. **行为文件必须自带 8 位小写 hex id**（宿主 pet_behaviors._norm_behavior 的硬判据：长度 8 且每个
   字符都在 0123456789abcdef 里），否则整条判「行为 id 非法」、四条全进不去。官方包用确定性示例 id
   （md5("dfypet-official:" + 行为名) 取前 8 位）；**入库时宿主的 import_file 会分配全新 uuid**，
   所以不存在"两边算出同一个 id"这回事，也不需要谁跟谁对齐派生规则。
2. **RoleLibrary.form_state_paths 返回的是逐形态对齐的 [{state: 绝对路径}, ...]**，不是一维路径表
   （我第一次断言写错，被探针抓出来）。
3. **zipfile 在 Windows 上"读取时"就把条目名里的反斜杠规范化成 /**（ZipInfo.__init__ 用 os.sep 替换），
   所以判据 4 的"条目名含反斜杠"分支**在真包上不可达**——我的验收脚本把这条如实标成「备注」，
   另外用两个实现的判定函数（pet_plugin._unsafe_name_reason 与参照实现）做单元级核对，不假装测过。
4. **安装器契约以代码为准，不以文档直觉为准**：B 的落地口径是 payload/role.json、payload/lines.json、
   payload/behaviors/ 或 payload/behaviors.json、payload 下任意 .wav/.mp3、payload 下任意 .txt；
   我最初按自己的直觉做的 payload/manifest.json + payload/roles/* 装不上，已按契约改包并把契约写进
   plugins/README.md。
5. **仓库 .gitignore 的 *.zip 会把官方包一起吞掉**（被忽略 = 仓库里根本没有这些文件，而发布门又要求
   工作树无未跟踪文件）→ 加 !plugins/packs/*.zip（主代理特批）。
6. **打包排除与官方内容冲突**：plugins/ 若被整体当"用户数据"排除，官方索引就进不了绿色版/发布包
   （下载链直接断）。已按主代理裁决收窄为 plugins/&lt;id&gt;/ 与 plugins/_download/。
7. **manifest 顶层是单一真源**：插件元数据只在 plugin 段写一份；双写（顶层再放一份）虽然能过校验器，
   但那是两处真源，早晚漂移——A 的格式文档与我这份都写死了这一点。

## 六、发货注意（给主代理）

* plugins/** 与 _dev 下的 build_official_plugins.py / plugin_pack_rules.py /
  verify_plugin_packs_v251.py / probe_plugin_landing_v251.py / probe_plugin_install_v251.py /
  plugin_packs_report.md **都要进提交**（发布门要求工作树无未跟踪文件）。
* 绿色版目录与发布包要含 plugins/index.json、plugins/README.md、plugins/packs/*.zip。
* index.json 的 url 目前是**相对路径**（packs/xxx.zip，相对 index.json 所在目录）：绿色版内可直接解析；
  要让用户从 GitHub Release 下载，发布时用一条命令重算绝对地址：
  python -B _dev/build_official_plugins.py --base-url https://github.com/&lt;owner&gt;/&lt;repo&gt;/releases/download/v2.5.1/
* 包内有中文文件名（人设「摸鱼搭子.txt」）：zipfile 写的是带 UTF-8 标志（0x800）的条目名，
  解包侧同样用 zipfile 读没有问题（我的探针与 B 的安装器都实测过）。

## 七、没做到的 / 有疑问的

* 三项护栏我在**收尾时**跑过一次（数字见 §八）：890 passed / v13 273 项 0 FAILS / 静态 0 问题 0 待确认
  （这是**代理 C 收尾那一刻**的读数；之后 A/B 的修复与用例还在往树里落，定版数字以主代理的
  安静窗口复跑为准）。
  但那次是**多路并行改树的窗口**里跑的（A、B 当时还在写产品代码与 tests），按任务书铁律 1
  它只能算"当时那一刻的读数"，**定版必须由主代理在安静窗口串行复跑**。
* 我**没有**验证插件管理对话框里的完整 UI 操作（按钮、确认框）：那是 B 的领地；我验的是它背后的
  PluginHost 与包本身（同一入口、Qt-free 可测的那一半）。
* voice_ref 一类没有官方包（没有合适素材，宁缺勿假），见第四节末。
* 打包工具里 landing=="ready" 的包会做"真安装"自检，而 pet_plugin_host 属于别人的领地：
  它若临时语法错/改名，打包会**明确失败**并提示（--skip-landing-check 可跳过，但产物不作上架依据）。
  这是有意的——宁可构建失败，也不要出一个"过校验器但装不上"的包。

## 八、三项护栏（本轮实跑，2026-10-11 收尾）

| 门 | 命令 | 结果 |
|---|---|---|
| pytest | python -B -m pytest tests -o addopts="" -q | **890 passed / 0 failed**（143.00s，代理 C 收尾读数） |
| v13 | python -B _verify_v13.py | **TOTAL CHECKS: 273, FAILS: 0** |
| 静态 | python -B _check_static.py（单跑） | **问题 0 条，待确认 0 条** |

* 跑之前确认过 _dev/.mutation.lock **不存在**（铁律 2）；三条出口码都是 0，完整输出尾巴在
  %TEMP%\agentC_gates\{pytest,v13,static}.txt。
* 基线是 795，现在 890——差额全部来自 A / B 本轮新增的用例；**代理 C 一行 tests 都没写**
  （领地不含 tests/，我的验收走 _dev/ 下的三个脚本：62 + 29 + 20 = 111 条检查）。
* ⚠️ 口径：这次跑在**多路并行改树**的窗口里，按铁律 1 不作定版依据，定版由主代理在安静窗口串行复跑。
