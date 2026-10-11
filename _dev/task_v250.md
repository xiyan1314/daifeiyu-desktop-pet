# v2.5.0 第 2 轮任务书（三路并行，领地互斥）

仓库：E:\deep seek\desktop-pet。基线 v2.4.4 = HEAD 2a6563c，工作树干净。
护栏现状：pytest 732 全过 · v13 273 项 0 FAILS · 静态 0/0。

## 通用铁律（三路都必读）

1. 跑全量 pytest 前确认 _dev/.mutation.lock/ 不存在。
2. 在绿色版目录里调用 python.exe 一律加 -B（否则多 14 个 stdlib pyc，且 _verify_green.py 的 dont_write_bytecode 拦不住）。
3. 不要在多个代理并行改树时下结论：本轮三路同时在改，全量 pytest 可能出现并发假红——单跑确认后再下判断，并在回报里说明你跑的时间点。
4. 每条改动配能真失败的测试（优先变异验证：把修复拿掉必须红）。
5. 不碰：VERSION / version_info.txt / _verify_green.py / CHANGELOG.md / _release_notes_*.md / 绿色版 / 发布 zip。
6. 不要提交（提交由主代理统一做）。如实报告没做到的。

---

## 代理 A：God Object 拆分 + ServiceRegistry + 按子系统补注解

**领地：桌宠.py、新建的 pet_services.py（或你判断更合适的模块名）、tests/**。**

现状（已实测）：PetWindow 有 **212 个方法**，__init__ 从 746 行到 1207 行 = **462 行**；__init__ 里**字面 new 了 15 个服务**，其中 **9 个把 self（整个 PetWindow）当第一个参数**：wander / weather / chat / ai / balance / actions / menu_builder / anim / mood，另有 tool_ctx 用 lambda 间接捕获 self。

**任务 A1（主任务）：把服务构造抽成 ServiceRegistry。**
- 目标：__init__ 只调一次注册表（理想是**一行**），服务构造与它们的行号顺序全部搬进新模块。
- **硬约束：行为逐位不变**。构造顺序、传参、异常语义都不能变。这是重构，不是改造。
- **分批做**：先把**最容易摘的**（不依赖 self 的 6 个：role_lib / audio_lib / book / lines_lib / voice_assets / alarms / behaviors）搬走，跑一轮护栏；再把**依赖 self 的**逐个搬，每个都跑护栏。不要一次全搬。
- 新模块必须**自动进护栏**：名字用 pet_ 前缀（_check_static 与 _verify_v13 都动态扫 pet_*.py），并**加进 _check_release.py 的 SYNC_FILES**（否则绿色版/发布包缺件时任何门都不响、用户双击即 ImportError）。
- 测试要钉住：注册表构造出的服务集合与旧 __init__ 一致（名称 + 类型）、构造顺序一致、PetWindow 上仍能按原名访问到**同一类**对象。

**任务 A2：按子系统补类型注解。**
- 你搬走多少子系统，就给**那些子系统的新模块**补全注解（参数 + 返回值，含私有/静态）。**不做全仓一次性**，也不要动 pet_dialogs / pet_voice / pet_resources（别的代理在动）。
- 注解要与真实行为一致（返回形状要对）。

**任务 A3（顺手）：_start_petting 的帧集守卫。**
- 现状：feed() 已有 not self._custom_role 守卫（v2.4.3 修的），_start_petting 同源但实测只值 0.24ms。
- 修法：同样加角色判断，避免自定义角色在"接力未完就摸头"时同步解用不到的默认帧集。配一条能真失败的测试。

**⚠️ 两个硬约束**
1. **README 的函数数被 AST 断言钉住**：tests/test_round3_a_fixes.py 会断言 README.md / README.en.md 里桌宠.py 的"253 函数"等于 AST 实测。**你拆分后 桌宠.py 的函数数会变，必须同步两份 README 的那个数字**（授权你改这两处数字，别改 README 其它内容）。
2. **_verify_v13.py 会动态扫 pet_*.py 并要求每个 pet.xxx( 都能解析**（_check_static 同款）。新模块里写 pet.xxx( 必须真实存在。另：_verify_v13.py 有 EXPECT_CHECKS 常量与末尾硬断言 len(CHECKS) == 它；**能不加 check 就别加**。

## 代理 B：对话框尺寸与可滚动性（用户报的真实问题）

**领地：pet_dialogs.py、tests/**。不要动 桌宠.py（代理 A 在改）。**

**用户报的现象**：有些窗口内容多、窗口大、**看不到底**，而且**缩小不了**——底部内容（往往是说明文字、列表末尾，或确定/取消按钮）够不到。

**任务 B1（先体检，别先改）**：
- 逐个构造 pet_dialogs.py 里**全部**对话框（约 30 个 Dialog 类），量出每个的：**实际尺寸** vs **当前屏幕可用区域**、**有没有滚动容器**、**按钮行是否在可见范围内**。
- 在 QT_SCALE_FACTOR=1.25 与 1.5 下**各跑一遍**（模拟高 DPI——按 1080p 设计的窗口在 768 高的屏 + 150% 缩放下会直接超框，这很可能就是"有些窗口"特别明显的原因）。
- 产出**超限清单**：哪些窗口、超多少、根因是固定尺寸（setFixedSize / 写死 resize）还是**缺滚动容器**。放 _dev/dialog_size_report.md。

**任务 B2（按清单统一修，模式应该是一套）**：
1. 内容区套 QScrollArea（内容再多也能滚到底）。
2. **尺寸钳制到可用屏幕**（例如最大高度约可用高度的 85%，并做下限保护），**去掉写死的固定尺寸**。
3. **按钮行放在滚动区之外**，永远可见（确定/取消绝不能被滚走）。
4. 高 DPI 下按**逻辑像素**计算，别按物理像素写死。

**任务 B3（验收，要能真失败）**：
- 每个修过的对话框配测试：断言高度 ≤ 可用屏幕高度的上限、断言内容可滚动、断言按钮行可见。
- 在 QT_SCALE_FACTOR=1.5 下同样跑一遍（这才能抓住 DPI 回归）。
- **不能弄坏现有护栏**：_verify_v13.py 里有**对话框冒烟循环**（会构造并检查各对话框），改完必须仍 273/0。

## 代理 C：D7-A 三条 + A-3 + 补跑两条过期证据 + 清理

**领地：pet_resources.py、_check_static.py、pet_fx.py、README.md（仅 §类型注解口径 之外的文档小节）、_dev/**。不要动 桌宠.py 与 pet_dialogs.py。**

**任务 C1（D7-A 三条）**：
1. **pet_resources 的 A=1**（keep_source 静默失败）→ 补一行日志（用 pet_log 的限流口径，不影响 A 档定义）。配一条能真失败的测试。
2. **_check_static 的 M 检查形参遮蔽误报**：函数形参名没进 bad 集合，导致 def wire_shadow(self, _mod_fn): self.boom.connect(_mod_fn) 这类被误报 → 把形参名一并算进 bad（一行级）。配合成反例：合法的不报、违规的必报、歧义的必须跳过。
3. **config.json 的 diff 存储不保留未知键**：这是**有意为之**，不是缺陷 → 把口径**写进 README 与 pet_config.py 的注释**（说清"为什么有意"）。配一条测试或注释级断言均可，但要在回报里说明你选了哪种。

**任务 C2（A-3）**：pet_fx.py 仍写死 86 与 "money"（产品路径已由 桌宠.py 的具名常量驱动，只剩 docstring 与 __main__ 自测）。→ 单源化或至少让文档与自测不再写死那两个数字（**不要动 桌宠.py**；若真要单源化必须动 import 方向，先在回报里说明方案再决定，本任务允许你只做文档同步）。

**任务 C3（补跑两条过期证据）**：
- _dev/mutations_startup_defer_v242.json 与 _dev/results_guardrails_can_fail.json 的源码指纹已过期。
- ⚠️ 它们是**旧形态**结果文件，**必须用各自的单脚本驱动**（_dev/mutate_startup_defer.py 与 _dev/verify_guardrails_can_fail.py），**不能用 mutate_check.py**（会 KeyError: mutations）。
- 跑完确认指纹对齐当前树，并在发布门上不再出现"指纹过期"提示（mutation_evidence_notes() 返回 []）。

**任务 C4（清理，只做这三项）**：删 _dev/__pycache__/（若又生成）；其余清理候选（8 个 v2.1.x 脚本 + 3 个旧形态驱动）**保留**——它们仍是那三块证据的唯一来源。

---

## 三路共同验收（安静窗口、串行）

- python -B -m pytest tests -o addopts="" -q → 0 failed（基线 732）
- python -B _verify_v13.py → 273 项 0 FAILS
- python -B _check_static.py（单跑）→ 0 问题 0 待确认

回报时请**分别**给出：你自己的改动清单、上面三项数字、以及"没做到 / 有疑问"的部分。