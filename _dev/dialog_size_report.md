# 对话框尺寸与可滚动性 · 体检报告（v2.5.0 · 代理 B）

> 用户报的现象：**有些窗口内容多、窗口大、看不到底，而且缩小不了**——底部内容
> （说明文字、列表末尾，或确定 / 取消按钮）够不到。
> 本文件 = B1 体检的原始数据 + B2 的统一修法 + B3 的验收口径。**先体检、后动手**，
> 下面"修前"一节的数字全部是**改动之前**在真 Qt 上量出来的（不是推算）。

## 0. 一句话结论

两个根因，同一条修法能一起解决：

| 根因 | 实测证据 | 修法 |
|---|---|---|
| **尺寸写死**：`self.resize(W, H)` 把"设计尺寸"当成"实际尺寸" | VoiceDialog 实测 **700x903 逻辑像素**，在 **800x800 的逻辑屏上都装不下**（100% 缩放；不是高 DPI 才有） | `clamp_dialog()`：上限 = 屏幕可用区域 × 85%，另给下限保护 |
| **没有滚动容器**：全文件 `QScrollArea` 出现 **0 次** | 窗口被挤小之后 Qt 把超出部分**裁掉**而不是给滚动条 → 底部永久够不到；`minimumSizeHint` 又被布局顶大（Voice **903**、RoleImport **740**、RoleEdit **706**）→ "**也**缩小不了" | `scroll_content()` 内容区进 QScrollArea + `stick_buttons()` 按钮行留在滚动区之外 |

## 1. 怎么量的（可复现）

体检脚本：[`tests/_probe_dialog_sizes.py`](../desktop-pet/tests/_probe_dialog_sizes.py) —— 真 `PetWindow` + 临时数据目录 + offscreen，
逐个构造 pet_dialogs.py 里**全部**顶层窗口，量 4 件事：

* **actual**：`show()` 之后 Qt 实际给出的尺寸（= 产品代码 `resize()` 的结果）；
* **min**：`minimumSizeHint()`，布局允许缩到多小 —— 这就是"**缩小不了**"的量化；
* **scroll**：窗口里有几个 `QScrollArea`（0 = 内容再多也滚不到底）；
* **btn_row**：底排按钮行在窗口坐标系里的上下边界（**只取 `stick_buttons` 记下的那一行**——
  扫全部 `QPushButton` 会把被滚动区裁掉的内容按钮也算进来，实测会误报成 665）。

再加一条**经验下限**：`resize(200, 120)` 之后读回 Qt 实际允许的最小尺寸（等价于用户拖边框）。

```powershell
cd "E:\deep seek\desktop-pet"
python -B tests\_probe_dialog_sizes.py                                  # 100%（offscreen 逻辑屏 800x800）
$env:QT_SCALE_FACTOR="1.25"; python -B tests\_probe_dialog_sizes.py     # 逻辑屏 640x640
$env:QT_SCALE_FACTOR="1.5";  python -B tests\_probe_dialog_sizes.py     # 逻辑屏 533x533
```

> offscreen 平台的屏幕是 **800x800 物理像素**，`QT_SCALE_FACTOR` 只改 devicePixelRatio，
> 于是**逻辑**可用区域 = 800 / dpr：1.0 → 800x800，1.25 → 640x640，1.5 → **533x533**。
> 533 大致对应"1366x768 的屏 + 150% 缩放"（910x512），正是用户说"有些窗口特别明显"的场景。
> 全部判据都按**逻辑像素**：Qt 的窗口几何本来就是逻辑像素（物理 = 逻辑 × dpr），
> 所以同一套阈值在 100% / 125% / 150% 下都成立，代码里没有任何按物理像素写死的值。

### 覆盖面：pet_dialogs.py 里到底有多少个"对话框"

任务书估的是"约 30 个 Dialog 类"，**实测不是**：

* `QDialog` 子类 **14 个**（全仓唯一来源就是 pet_dialogs.py，`桌宠.py` 一个都没有）；
* 会被嵌进 ResourceManagerDialog 页签、但自己也是独立窗口的面板 **3 个**
  （RolePanel / SoundPanel / VoiceAssetPanel，`QWidget`）；
* **内联**构造、没有类名的框 **2 个**（`pick_role_meta` 的"角色信息"、
  `RoleEditDialog._add_proc_action` 的"程序化合成动作"）——这两个此前是**裸 `QDialog`**，
  完全没有任何屏幕钳制，是体检脚本第一版会漏掉的两个。

合计 **19 个顶层窗口/面板**，体检脚本与验收用例都按这 19 个跑。

## 2. 修前：超限清单

### 2.1 100% 缩放（逻辑屏 800x800）—— 只超了 1 个

| 窗口 | 实际尺寸 | 最小尺寸(minimumSizeHint) | 滚动容器 | 判定 |
|---|---|---|---|---|
| **VoiceDialog** | **700x903** | 622x903 | 0 | ❌ **超 103**，且**缩不下去**（下限 903 > 800） |
| RoleImportDialog | 600x740 | **508x740** | 0 | ⚠ 高度吃掉 92% 屏，且缩不下去 |
| RoleEditDialog | 610x706 | **610x706** | 0 | ⚠ 同上（完全缩不动） |
| LinesDialog | 780x620 | 616x452 | 0 | ⚠ 宽度吃掉 97.5% |
| ResourceManagerDialog | 700x560 | 640x560 | 0 | ⚠ 宽度缩不动（640） |
| IdleDialog | 660x560 | 402x503 | 0 | ⚠ |
| AISettingsDialog | 560x560 | 430x538 | 0 | ⚠ |
| LedgerDialog | 680x540 | 466x198 | 0 | ⚠ |
| BehaviorDialog | 640x500 | 612x359 | 0 | ⚠ 宽度缩不动（612） |
| AlarmDialog | 540x470 | 478x218 | 0 | ok |
| RolePanel | 614x480 | 614x480 | 0 | 面板，宽度缩不动 |
| SoundPanel / VoiceAssetPanel | 390x406 / 462x246 | — | 0 | ok |
| PhysicsDialog | 430x330 | 394x227 | 0 | ok |
| _VoicePickDialog | 460x380 | 322x138 | 0 | ok |
| AmountNoteDialog / BubbleStyleDialog | 286x113 / 282x302 | — | 0 | ok |

**全部 17 个窗口的滚动容器数都是 0。**

### 2.2 125% 缩放（逻辑屏 640x640）—— 超限开始成片

（尺寸不变，变的是可用区域；下面只列"超了"或"缩不到范围内"的）

| 窗口 | 实际尺寸 | 超出 | 缩得下去吗 | 缩到底仍是 |
|---|---|---|---|---|
| VoiceDialog | 700x903 | 60 x **263** | ✗ | 622x903 |
| RoleImportDialog | 600x740 | — x **100** | ✗ | 508x740 |
| RoleEditDialog | 610x706 | — x **66** | ✗ | 610x706 |
| LinesDialog | 780x620 | **140** x — | ✓（宽能缩到 616 < 640） | 616x452 |
| ResourceManagerDialog | 700x560 | **60** x — | ✗ | 640x560 |
| BehaviorDialog | 640x500 | 0（正好） | 部分 | 612x359 |
| LedgerDialog | 680x540 | **40** x — | ✓ | 466x198 |
| IdleDialog | 660x560 | **20** x — | ✓ | 402x503 |
| RolePanel | 614x480 | — | ✗ | 614x480 |
| AISettingsDialog | 560x560 | — | ✓ | 430x538 |

### 2.3 150% 缩放（逻辑屏 533x533）—— 这就是用户看到的"有些窗口"

| 窗口 | 打开时尺寸 | 超出上限(533) | **下限** | 能否自己拖到装得下 | 根因 |
|---|---|---|---|---|---|
| VoiceDialog | 700x903 | **167 x 370** | 622x903 | ❌ **不能** | 写死 resize + 无滚动区 |
| RoleImportDialog | 600x740 | **67 x 207** | 508x740 | ❌ 不能（高） | 写死 resize + 两张 240x170 `setFixedSize` 预览把最小高度顶到 740 |
| RoleEditDialog | 610x706 | **77 x 173** | 610x706 | ❌ 完全不能 | 写死 resize + 双栏内容把最小尺寸顶到 610x706 |
| LinesDialog | 780x620 | **247 x 87** | 616x452 | ❌ 不能（宽） | 写死 resize + 三个页签里 `setMinimumWidth(320)` 的下拉框 |
| ResourceManagerDialog | 700x560 | **167 x 27** | 640x560 | ❌ 不能（宽） | 写死 resize + 内嵌 RolePanel 的 `setMinimumWidth(340)` + 200x200 预览 |
| BehaviorDialog | 640x500 | **107 x 0** | 612x359 | ❌ 不能（宽） | 写死 resize + 行为步骤表宽 |
| IdleDialog | 660x560 | **127 x 27** | 402x503 | ✓ 能 | 写死 resize（打开即出框） |
| LedgerDialog | 680x540 | **147 x 7** | 466x198 | ✓ 能 | 写死 resize |
| AISettingsDialog | 560x560 | **27 x 27** | 430x538 | ✓ 能（高 538 仍超 5） | 写死 resize |
| RolePanel | 614x480 | **81 x 0** | 614x480 | ❌ 不能（宽） | 面板本身，`setMinimumWidth(340)` + 200 宽预览 |
| AlarmDialog | 540x470 | **7 x 0** | 478x218 | ✓ 能 | 写死 resize |
| PhysicsDialog | 430x330 / _VoicePickDialog 460x380 / SoundPanel 390x406 / VoiceAssetPanel 462x246 / AmountNoteDialog 286x113 / BubbleStyleDialog 282x302 | — | — | ✓ | **装得下**，但同样 0 个滚动容器（内容一多就出事） |

**"缩小不了"的直接原因**：`.minimumSizeHint()` ≠ 0，而是被**布局**撑出来的
（Voice 903 / RoleImport 740 / RoleEdit 706 / RolePanel 614 / Lines 616 / ResourceManager 640）。
用户拖边框时 Qt 不允许小过它——`resize(200,120)` 之后读回来**还是**这个数。

## 3. 修后：同一套体检的对照

同一个脚本、同一台机、同一天；**19 个窗口全部**：

| 窗口 | 150% 下打开尺寸 | 上限(453) | 滚动容器 | 纵向可滚范围 | 按钮行 | 缩到底 |
|---|---|---|---|---|---|---|

| RoleImportDialog | 453x430 | 453 | 1 | 320 | y=395..419 | 320x240 |
| RoleEditDialog | 453x453 | 453 | 1 | 263 | y=418..442 | 320x240 |
| BehaviorDialog | 453x453 | 453 | 1 | 0 | y=418..442 | 320x240 |
| AlarmDialog | 453x453 | 453 | 1 | 0 | y=418..442 | 320x240 |
| AISettingsDialog | 453x453 | 453 | 1 | 237 | y=418..442 | 320x240 |
| RolePanel | 408x306 | —（面板，不设上限） | 1 | 306 | — | 200x120 |
| SoundPanel | 390x306 | — | 1 | 48 | — | 200x120 |
| VoiceAssetPanel | 450x246 | — | 1 | 10 | — | 200x120 |
| ResourceManagerDialog | 453x453 | 453 | 4 | 0 | y=418..442 | 320x240 |
| AmountNoteDialog | 286x113 | 453 | 1 | 0 | y=78..102 | 286x120 |
| LedgerDialog | 453x453 | 453 | 1 | 0 | y=418..442 | 320x240 |
| BubbleStyleDialog | 282x302 | 453 | 1 | 0 | y=267..291 | 282x240 |
| LinesDialog | 453x453 | 453 | 1 | 9 | y=418..442 | 320x240 |
| PhysicsDialog | 430x330 | 453 | 1 | 0 | y=295..319 | 320x240 |
| VoiceDialog | 453x453 | 453 | 1 | **474** | y=418..442 | 320x240 |
| IdleDialog | 453x453 | 453 | 1 | 216 | y=418..442 | 320x240 |
| _VoicePickDialog | 453x380 | 453 | 1 | 0 | y=345..369 | 320x240 |


* **上限**：`可用区域 × 0.85`，150% 下 = `533 × 0.85 = 453`；100% 下 = 680。**没有任何窗口超过它**。
* **按钮行**：全部落在窗口矩形内（最大 bottom 442 ≤ 453），而且**都在滚动区之外**。
* **缩到底**：`minimumSize` 从 622x903 这类降到 **320x240**（下限保护），用户能把窗口拖到装得下。
* **纵向可滚范围 > 0** 的窗口 = 内容真的被裁掉了、真的滚得到（Voice 474、RoleImport 320、
  RoleEdit 263、AISettings 237、Idle 216…）；= 0 的是"内容本来就装得下"，不需要滚动条
  （判据按 `minimumSizeHint` 比视口，不是按 `sizeHint`——见第 5 节踩坑）。

100% 缩放下对照（同一次运行）：VoiceDialog 从 **700x903** 回到 **680x640**（设计尺寸，
装得下了），RoleImportDialog 600x430、RoleEditDialog 600x540、LinesDialog 680x620……
**设计尺寸一个都没改**，改的只是"装不下时不许超屏"。

## 4. 修法（一套模式，19 个窗口共用）

`pet_dialogs.py` 里新增 4 个东西（都在"通用助手"一节）：

```python
DIALOG_MAX_RATIO = 0.85   # 上限 = 可用区域 × 0.85
DIALOG_MIN_W, DIALOG_MIN_H = 320, 240

dialog_available_geometry(widget)   # 所在屏幕的 availableGeometry()（逻辑像素；可注入，见测试）
dialog_size_limits(widget)          # (min_w, min_h, max_w, max_h)
clamp_dialog(dlg, want_w, want_h)   # 取代写死的 resize（钳尺寸 + 上下限）
scroll_content(dlg)                 # 内容区进 QScrollArea，返回内容布局
stick_buttons(dlg, row)             # 按钮行钉在滚动区之外
class _FitDialog(QDialog):          # 14 个对话框的公共基类
    def showEvent(self, event):     # 显示前按"所在屏幕"再钳一次（换屏/换缩放后仍成立）
        clamp_dialog(self); super().showEvent(event)
```

每个窗口的改动就 3 处（机械、可批量核对）：

```diff
-class XDialog(QDialog):            +  class XDialog(_FitDialog):
-    self.resize(700, 640)          +  clamp_dialog(self, 700, 640)
-    root = QVBoxLayout(self)       +  root = scroll_content(self)
-    root.addLayout(btns)           +  stick_buttons(self, btns)
```

四个细节：

1. **按钮行留在滚动区之外**：`outer = [ QScrollArea(stretch=1), 按钮行 ]`。确定 / 取消
   永远不会被滚走（验收有专门的"按钮行不在内容布局里"断言）。
2. **不再按物理像素写死**：全程只有逻辑像素。`QT_SCALE_FACTOR` 只改 dpr，代码里
   一处乘法/除法都没有。
3. **去掉写死的固定尺寸**：14 处 `self.resize(W, H)` 全部改成 `clamp_dialog(self, W, H)`；
   静态用例钉住"以后不许再出现 `self.resize(字面量, 字面量)`"。
   *保留*的固定尺寸只有缩略图框（`prev.setFixedSize(240,170)`、`_preview.setFixedSize(180,130)`）——
   它们是图框不是窗口尺寸，套进滚动区后不再顶大窗口的最小高度。
4. **滚动区样式**：`QScrollArea { background: transparent; border: none; }` +
   `QScrollArea > QWidget > QWidget { background: transparent; }` + `setAutoFillBackground(False)`。
   不加这几行，滚动视口会用自己的浅色底，深色主题里会出现一块白板（已截图核对）。

顺带修掉的两处**裸 QDialog**（此前完全没进任何尺寸保护）：

* `pick_role_meta` 的"角色信息"框 → 抽成 `build_role_meta_dialog()` 工厂（可验收）+ `_FitDialog` + 滚动区；
* `RoleEditDialog._add_proc_action` 的"程序化合成动作"框 → `_FitDialog` + 滚动区。

面板（RolePanel / SoundPanel / VoiceAssetPanel）也套了滚动区：它们自己不是窗口，
但**它们的布局最小尺寸会把容器 ResourceManagerDialog 的下限顶到 640 宽**
（`_list.setMinimumWidth(340)` + 200x200 预览），是"容器缩不下去"的上游原因。

## 5. 踩过的两个坑（写下来给下次）

1. **`QScrollArea::sizeHint()` 不是内容尺寸**：`widgetResizable(True)` 时它返回 Qt
   写死的默认值（实测 **432x288**）。第一版 `showEvent` 用 `dlg.sizeHint()` 当"期望尺寸"，
   结果把设计好的 600x540 直接缩成 454x340（实测踩到，全部窗口都变小了）。
   → `clamp_dialog` 缺省用**当前尺寸**，设计尺寸由每个窗口显式传入。
2. **"按钮行可见"不能扫全部 `QPushButton`**：内容区里的按钮被滚动区裁掉之后
   `isVisibleTo()` 仍为 True，坐标却在窗口之外——实测把 RoleEditDialog 的"按钮下边界"
   报成 **665**，而窗口只有 540 高，看起来像布局坏了。→ 只量 `stick_buttons` 记下的那一行。

## 6. 验收与变异证据

验收用例：[`tests/test_dialog_fit_v250.py`](../desktop-pet/tests/test_dialog_fit_v250.py)（v2.5.0 第 3 轮补齐后 **41 条，约 3.3 秒**）：

| 用例 | 断言 | 拿掉修复会怎样（**实测**） |
|---|---|---|
| `test_每个窗口都不超屏_能滚到底_按钮可见[19]` | 尺寸 ≤ 可用×85%；有 `widgetResizable` 滚动容器；内容裁掉时滚动范围 > 0；按钮行在滚动区之外且压到下限仍在窗口内 | M1 整套钳制拿掉 → **16 failed** |
| `test_上限就是85百分比而不是写死像素` | 2000x1200 屏上上限跟着变 1700x1020；VoiceDialog 恢复 700x640 | M6 上限写死 510 → **failed** |
| `test_大窗口不再是缩小不了` | 4 个大窗口 `minimumSize` ≤ 320x240 且真能拖到 | 下限回归即红 |
| `test_本来就小的框不被撑大` | AmountNote 仍 286x113、BubbleStyle 仍 282x302 | M3 下限改成无条件 320x240 → **failed** |
| `test_pet_dialogs里没有裸顶层布局也没有写死resize` | AST：不许 `QVBoxLayout(self)` 当顶层布局、不许 `self.resize(字面量,字面量)` | M4/M5 → **failed** |
| `test_所有对话框都继承同一个可钳制基类` | 14 个都继承 `_FitDialog` 且 `showEvent` 里调 `clamp_dialog` | M7 去掉重钳 → **failed** |
| `test_每个对话框的设计尺寸就是它自己的契约[14]` | 2000x1200 大屏上 14 个对话框的实际尺寸 == 各自设计尺寸 | 删掉任一行 `clamp_dialog(self, W, H)` → **2 failed**（行为 + 源级；本轮 12 条逐条实测） |
| `test_每个对话框的设计尺寸都写在源码里` | AST：12 处 clamp 字面量 == 口径表；两个"内容天然尺寸"的类不许有 clamp | 同上（源级那一半，专治"sizeHint 恰好等于设计尺寸"时行为判据抓不到） |
| `test_取不到屏幕时不崩也不设上限` | 屏幕信息拿不到时返回"只留下限、不设上限" | — |
| `test_高DPI1_5下所有窗口仍不超屏` | **子进程**跑 `QT_SCALE_FACTOR=1.5`（逻辑屏 533x533），**19 行**逐个断言不超写死的 453 / 有滚动容器 / 按钮行在窗口内 | 改动前必红（Voice 700x903） |

**v2.5.0 第 3 轮补的两处（评审 M3 / L1）**：

* **设计尺寸原来只有 3 个窗口被钉住**（Voice/AmountNote/BubbleStyle）。`_FitDialog.showEvent` 的兜底用
  `dlg.width()`，而"没 resize 过"时它是 Qt 默认的 100x30 —— 设计尺寸**只由每个类自己那行 clamp 提供**：
  删掉 VoiceDialog 的 `clamp_dialog(self, 700, 640)`，窗口悄悄从 700x640 掉到 454x340，而当时**全绿**。
  现在 14 个各钉一条（`_DESIGN_SIZES`）+ 一条 AST 源级钉（`_class_clamp_literals`）。
* **19 个窗口这句此前名不副实**：报告与验收清单是 19，而体检脚本 `helpers_dialog_fit_v250.py` 的
  `dialog_factories()` 只有 **18**（少的正是第 19 个 `build_role_meta_dialog`），断言只写 `>= 18`。
  本轮把第 19 个补进体检清单、断言收紧成 `>= 19` —— 上面那张 150% 表以后是**真的 19 行**。

**变异证据已入库**：[`_dev/mutations_dialog_fit_v250.json`](mutations_dialog_fit_v250.json)（17 条，走
`_dev/mutate_check.py` 同一套机制、带 `repo_fingerprint`）—— **17/17 CAUGHT**（2026-10-11 第 3 轮实测）。
此前这里只写了一句"DETECTED"、仓里**没有可复跑产物**（当时 10 个 `mutations_*.json` 里没有任何一条
锚点落在 `pet_dialogs.py`），下一轮没人能复核。17 条 = 12 个类的设计尺寸 clamp 逐条删除 + 自指判据
（`DIALOG_MAX_RATIO` 0.85→1.5）+ 重钳兜底 / 下限保护 / 滚动容器 / 按钮行四处修法各拿掉一处。

**自指判据的坑（本轮修掉）**：主判据原先写成 `assert (max_w, max_h) == (int(SMALL.w * DIALOG_MAX_RATIO), ...)`
—— 上限由**被测常量自己算出来**，把 0.85 放宽到 1.5 时判据跟着放宽、19 条窗口用例全绿（审查实测）。
现在主判据写死绝对值 `HARD_MAX_SMALL = (870, 510)` / `HARD_MAX_150 = (453, 453)`，另外单钉
`DIALOG_MAX_RATIO == 0.85`（常量与绝对值两道机器判据，改哪个都红）。

为什么高 DPI 必须走子进程：`QT_SCALE_FACTOR` 是**建 QApplication 之前**读的环境变量，
测试进程里再设对它无效（`QT_SCALE_FACTOR` 改了但 dpr 还是 1.0）——那样这条用例会**假绿**。
用例里额外断言了子进程报回来的 `dpr == 1.5`，防止"没真跑在 1.5 下"。

## 7. 没做到的 / 边界（如实报）

1. **原生弹窗没动**：`QMessageBox`（`_warn/_info/_confirm`）、`QInputDialog`（帧上限 / 重命名音频）、
   `QFileDialog`、`QColorDialog` 都是 Qt 自带、自己按内容算尺寸的窗口，本次没套钳制。
   它们的内容都很短（一行提示 / 一个输入框），实测不超屏；但**如果以后有超长提示文本**，
   它们仍可能超——那时要么换 `QMessageBox` 的 `setText` 长度，要么单独处理。
2. **面板不设尺寸上限**：RolePanel / SoundPanel / VoiceAssetPanel 是嵌在页签里的 `QWidget`，
   给它们 `setMaximumSize` 会让它们在页签里长不大。它们只做了"内容可滚动"，
   "不超屏"由容器负责。
3. **缩略图框仍是固定尺寸**（`setFixedSize(240,170)` / `(180,130)` / `(200,200)` / `(72,26)`）。
   它们不再顶大窗口下限，但小屏上仍会让内容变宽/变高（靠滚动条解决，不是"自适应缩放"）。
4. **offscreen 屏是方的**：真实用户屏基本是 16:9，本报告的"150% = 533x533"是
   **等效高度**的模拟（533 ≈ 1366x768@150% 的 512），宽度方向比真实屏更苛刻，
   所以结论偏保守（真实屏上更宽松）。没有在真实 1920x1080@150% 的物理机上验过。
5. **没验证真实拖拽**：`minimumSize` 与 `maximumSize` 是程序化 `resize()` 验的，
   没有真人拖窗口边框。Qt 的窗口管理器对 `maximumSize` 的处理在 Windows 上
   一般一致，但这条是推理不是实测。
6. **本次没跑绿色版**（`_verify_green.py`）：按铁律 5，绿色版不归本代理动。
