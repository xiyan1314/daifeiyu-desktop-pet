# UI 卡顿收口报告（v2.4.1 · B 区 C1–C3）

> 复现脚本：`python _dev/repro_frame_freeze.py --label <名字>`（只读测量，不改产品代码）
> 原始数据：`python _dev/repro_frame_freeze.py --label <名字>` 生成，按 label 写进 `_dev/ui_freeze_raw.json`
> （**该文件已被 .gitignore 忽略**，复跑即得；入库的是摘要 `_dev/ui_freeze_summary.json`）· 深度归因工具：`_dev/probe_ui_freeze.py`

## 1. 卡在哪（探针归因，不是猜）

三个阶段的探针数据指向同一个根因：**帧动画的 PNG 解码全在主线程上同步做，而且同一批
PNG 会被反复解码**。

| 阶段 | 证据 | 关键数字 |
|---|---|---|
| ① 原始（v2.4.0 / 未修） | `apply_role` 单次最长 597.7 ms；`_wire_anim_sets` 409.2 ms；`_play_idle` 单次最长 184.4 ms | 一次 `apply_role(60帧×4形态512px)` 解 69 个 PNG。**这一行的原始 json（`_freeze3.json`）没有入库**，只作背景，别当成可在仓库里复现的证据 |
| ② 指纹缓存（前一位代理） | `_play_idle` 12 次 **690.2 ms → 10.1 ms**；解码批次 64 → 32 | 治好了**热路径重复注册**；冷加载仍 408–728 ms。这组数字来自 `probe_ui_freeze.py` 的**计数器插桩**（其 json 输出未入库）；同一阶段基线（`before` 段）的摘要在 `_dev/ui_freeze_summary.json`，逐场景原始数据复跑即得 |
| ③ 本轮：解码缓存 + 时间片分摊 | 见下表（`after/after2/final` 三次实测范围）；逐场景原始数据由 `repro_frame_freeze.py` 生成、不入库，摘要在 `_dev/ui_freeze_summary.json` | 冷加载的**最长连续阻塞**降到 ≈1 个切片（12 ms 预算）+ 非解码工作 |

根因链条：`_play_idle`（每次待机/形态重查）→ `_wire_anim_sets` → 无条件把当前形态
整批帧重新解码。前一位代理用**指纹缓存**解决了"重复注册"；本轮补的是"**第一次也得解**"
这件事本身——它仍然是一次 60×512px ≈ 450 ms 的主线程长阻塞。

## 2. 修了什么（`桌宠.py`）

三层，互相叠加（**不是替代**）：

1. `_frame_pix(path)` —— **单帧解码缓存**，键 = `(路径, mtime_ns, 文件大小)`。
   同一份素材只解一次；素材被换（重新导入/用户改图）键自动失配重解，绝不拿陈旧贴图。
   有界（`_FRAME_CACHE_MAX = 512`，满了按插入序淘汰最旧一条）。QPixmap 隐式共享，命中不复制像素。
2. `_wire_anim_sets` 的**首片预算**：一个事件循环切片里最多解 `_FRAME_SLICE_MS = 12 ms`。
   小帧集（测试角色、默认素材）整个批次都落在首片里 → **同步装好，行为与旧版逐位相同**。
3. `_anim_start_async` / `_anim_chunk_step` —— 一片解不完就挂到 `QTimer(0)` 下一轮接力，
   跑在**主线程**（不跨线程，所以没有"线程里裸写盘"问题，静态体检 P 类不受影响）。
   每片只占 ≈12 ms；全部解完后一次性 `add_set`，再由 `_anim_ready` 按 `_play_idle` 的**同一判据**
   补一次起播。角色/形态在解码途中变了 → 指纹不符，本批作废（不会装错形态的帧）。

顺带清理：`_pix_frames` 在这次重构后失去唯一调用点（`_check_static` / `_verify_v13` /
tests 全仓无引用），按本仓既有惯例（v2.4 删 `_role_frames`）删掉。

## 3. 实测：修前 / 修后（同一台机器、同一个脚本）

`_dev/repro_frame_freeze.py` 的口径：`main_thread_ms` = 场景函数**同步返回**耗时；
`loop_gap_ms` = 5 ms 心跳定时器的最大间隔 = **主线程连续不让出事件循环的时长**（用户感知的假死）。
三个数字每次几乎相等（`gap ≈ main`），说明这段时间事件循环一次都没转。

"修后"一列是 `--label after / after2 / final` 三次跑的**实测范围**（这台机器 run-to-run 波动大，
见第 4 节），不是挑最好看的那次：

| 场景（60 帧 512px 真实美术，最坏情况） | 修前（指纹缓存后） | 修后（3 次实测范围） | 口径说明 |
|---|---|---|---|
| `apply_role(60 帧 512px 单形态)` 冷加载 | **456.8 ms** | **60.9 – 72.5 ms** | 这一列是 `main_thread_ms` = **同步阻塞**；**总解码耗时一次都没少**，只是从"一次占住主线程"摊成后台分片 |
| `apply_role(60 帧 512px)` 第二次（预热重解） | **240.8 ms** | **17.7 – 72.2 ms** | 同上（预热重解也走同一条分片路径） |
| `apply_role(60 帧×4 形态 512px)` | **481.7 ms** | **95.7 – 156.5 ms** | 4 形态的同步段仍受首片预算约束，其余在后台分片里解 |
| `_import_role_bundle(60 帧 512px 真实美术包)` | **548.7 ms** | **130.3 – 203.1 ms** | 含解包/复制等非解码工作，不全是帧解码 |
| `role_lib.delete` | 67.9 ms | 22.0 – 43.0 ms | 与帧解码无关（删目录/改索引），属 run-to-run 波动 |
| `_play_idle() ×5`（稳定态热路径） | 0.2 ms | 0.1 – 0.3 ms（**不变**） | — |
| `_play_idle() ×5`（分片装好后的第一批） | 0.2 ms | 45.3 ms（一次性，见第 4 节） | — |
| `pet_export.export_bundle` | 199.3 ms | 124.6 – 205.9 ms | **无稳定改善**（区间含噪声） |
| `PetWindow()` 构造（启动） | 411.3 ms | 173.3 – 364.1 ms | 波动大，**未系统改善** |

**对外口径（别写成"快 6–7 倍"）**：这三层修的是**最长连续阻塞**（用户感知的"假死"），
不是总耗时——总解码工作量完全没变，只是从"一次占住主线程 456.8 ms"变成"分片后单次最长
阻塞 ≈60 ms（非解码工作 + 一个 12 ms 切片）"。所以只能说：

> **最长连续阻塞 456.8 ms → ~60 ms（总解码耗时基本不变，界面不再假死）。**

上表里"修前/修后"两列就是实测值本身（原话口径见第 3 节）；完整逐场景数据可用第 5 节的命令重跑
复现（写进 `_dev/ui_freeze_raw.json`，已 gitignore），入库摘要见 `_dev/ui_freeze_summary.json`。

对照（前一位代理用 `probe_ui_freeze.py` 的计数器式插桩，低方差）：
`_play_idle` 12 次 690.2 ms / 单次最大 199.5 ms → 10.1 ms / 3.1 ms；解码批次 64 → 32。

**"卡顿消失"的可复现判据**：`python _dev/repro_frame_freeze.py --label check` 输出里，
`apply_role(60 帧 512px 真实美术)` 这一行的 `loop_gap_ms` 必须 < 100 ms
（修前 456.8 ms）。`loop_gap_ms` 就是"主线程连续阻塞"的直接测量。
该脚本的"帧集就绪"判据是 **`win._anim_pending is None`**（这一批分片收尾的权威信号）——
**不要退回"idle 帧集非空"**：分片在途时那上面还挂着上一次注册的帧集，判据恒真 →
`ready_ms` 会恒等于 `main_thread_ms`（早先那版原始数据里 40 行全部相等就是这个坑）。

## 4. 老实说：没修的和没修好的

| 项目 | 现状 | 为什么没动 |
|---|---|---|
| `PetWindow()` 启动 | 173–411 ms（run-to-run 波动大） | 窗口显示**之前**的构造：`load_frame_set` ×37 帧 + `_build_state_pix` + `_build_sprites`。要改得动"先建窗还是先解码"的时序，超出 C1–C3 的"非阻塞替代"范围 |
| `_export_role` / `export_bundle` | ≈200 ms 未改善 | 主体是 `zipfile` + `ZIP_DEFLATED` 对 PNG 的压缩长循环（60 个文件 10 MB）。要分片就得把 `export_bundle` 拆成"收集 / 逐条写"两段 API；本轮不做，避免动到导出包的产出格式 |
| `apply_role` 残余 ≈70 ms | 不再是帧解码 | 残余是 `_build_sprites` + `_build_state_pix`（程序化叠图）+ `save_config`（≈11 ms 原子写）。要继续压需要另一个分片对象 |
| `_play_idle` 首次 45 ms | 一次性 | 分片装好帧集后**第一次** `_play_idle` 做的重排/变换工作；同步路径里同一份工作本来也在 `apply_role` 里（只是被摊进 456 ms）。稳定态 0.3 ms 与修前一致，**没有稳态回归** |

`_dev/probe_ui_freeze.py` 的"单次场景数字 run-to-run 波动可达 ±50%"在这台机器上是实测事实
（与解码无关的场景，如 `role_lib.delete`，两次跑也差近一倍）。所以上表的**稳健证据是
"最长连续阻塞"这一项**（456.8 ms → 60.9–72.5 ms，量级差异远超波动）与低方差的计数器插桩，
而不是总耗时（总耗时本来就不该变），也不是小场景的绝对值。

## 5. 怎么复跑

    # 主测量（打印表格 + 按 label 累积进 _dev/ui_freeze_raw.json；该文件已 gitignore，不入库）
    python _dev/repro_frame_freeze.py --label myrun

    # 深度归因（场景段 + 稳态 sys.setprofile 画像 + 内部函数插桩）
    python _dev/probe_ui_freeze.py --json _dev/_probe_myrun.json --steady 3

    # 帧集注册指纹缓存 + 解码缓存上界 + 同路径换素材的回归
    python -m pytest tests/test_ui_wire_cache_v241.py -o addopts="" -q

    # 分片状态机的回归（冷缓存 + ≥8 张 512px 帧：真的分片 / 单次阻塞 ≤ 一个切片 /
    # 不多起播 / 同步臂作废在途批 / 分片窗口期不播旧角色）
    python -m pytest tests/test_anim_slice_v241.py -o addopts="" -q
