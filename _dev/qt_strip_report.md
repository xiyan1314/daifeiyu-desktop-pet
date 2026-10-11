# Qt 裁剪实验报告（代理 B）

> 任务：裁 Qt 实验，决定「核心版」值不值得做。
> 领地：只在 %TEMP% 的副本里操作；本文件是唯一写进仓库的东西。
> 仓库：E:/deep seek/desktop-pet @ 9ab85bb（v2.4.3），开工时工作树干净。
> 实验时间：2026-10-11 08:36 – 09:5x

---

## 0. 一句话结论

**值得做。** 四个候选组 + 一个候选组之外的意外收获（icudtl.dat），共 **2566 个条目 / 55.43 MiB 压缩**；
**逐组单独删、六组一起删，四道闸全绿**。
发布 zip 107.49 → **52.07 MiB（−51.6%）**，解压 292.62 → **137.37 MiB**。

最划算的一刀不是 qml 也不是 opengl32sw，而是 **5 个 *.debug.* 文件 = 16.83 MiB**，
占整个 QtWebEngine 成本（30.66 MiB）的 **55%**——**即使保留 WebEngine 也应该删掉它们**。

**唯一一删就红的是 assets 精简**（只省 3.67 MiB，却静默丢掉吃帧/两个特效/全部 17 张表情图）→ **不建议做**。

---

## 1. 方法与环境

- **副本**：robocopy /E 整份复制 大肥鱼桌宠_绿色版 → %TEMP%/qt-strip-20261011-083616/work（3891 文件 / 292.89 MiB）。原目录全程只读（见 §7.1 的一处越界交代）。
- **自带 python**：3.10.2（Lib/site-packages 内 PySide6 6.11.2，无 pytest）。
- **系统 python**：3.10.2 + pytest 9.1.1（仓库门用它跑；**通过 PYTHONPATH 强制指向副本的 PySide6**，已验证生效：
  PySide6.__file__ = …/qt-strip-…/work/Lib/site-packages/PySide6/__init__.py）。
- **删一组、测一组**：用 manifest + stash/restore 把目标条目移到 stash/，跑完四道闸再移回。

### 四道闸（比任务书多一道）

| # | 闸 | 用什么 python | 说明 |
|---|---|---|---|
| 1 | **_verify_green.py** | 副本自带 python，cwd=副本 | 19 项，唯一直接跑在成品包上的检查 |
| 2 | **_verify_v13.py** | 副本自带 python + 仓库源码 | 273 项；用的是**副本的 PySide6** |
| 3 | **pytest tests** | 系统 python + PYTHONPATH=副本 site-packages | `-o addopts= -q -p no:cacheprovider`，`PYTHONDONTWRITEBYTECODE=1`（不在仓库留痕） |
| 4 | **真实窗口 GUI 探针（新增）** | 副本自带 python | **真实 windows 平台插件**（非 offscreen）：真 HWND、真绘制、10 个对话框、3s 事件循环、托盘、真 app.exec() |

第 4 道是本轮新增的：绿色版自带的两个检查都是 offscreen，**没有任何一道闸碰过 qwindows.dll**。
探针带 faulthandler 看门狗（60s 必杀）+ 硬逃逸（os._exit），不可能挂住整轮。

---

## 2. 基线（未裁剪的副本）

| 闸 | 结果 |
|---|---|
| _verify_green.py | **19 PASS / 0 FAILS** |
| _verify_v13.py | 273 项，**0 FAILS**（首次基线跑出 1 FAIL，见 §7.3 抖动说明） |
| pytest | **691 passed**（此后仓库被并行代理加了 tests/test_asset_absence_v244.py → 之后各轮恒为 **707 passed**） |
| 真实窗口 GUI | **17 PASS / 0 FAILS**，platformName()=="windows"，1 屏，pet.grab() 480×480，事件循环 47 ticks，app.exec() 返回 rc=0 |

---

## 3. 逐组结果（每组单独删，其余保持原样）

| 轮 | 删掉（测试时用 Test-Path 逐项确认过缺失） | ① green | ② v13 | ③ pytest | ④ 真实窗口 |
|---|---|---|---|---|---|
| R1 | 40 个 webengine 相关文件 | 19/0 ✅ | 273/0 ✅ | 707 ✅ | 17/0 ✅ |
| R2 | resources/icudtl.dat | 19/0 ✅ | 273/0 ✅ | 707 ✅ | 17/0 ✅ |
| R3 | PySide6/qml/（2531 文件）+ 8 个 qml CLI 工具 | 19/0 ✅ | 273/0 ✅ | 707 ✅ | 17/0 ✅ |
| R4 | opengl32sw.dll | 19/0 ✅ | 273/0 ✅ | 707 ✅ | 17/0 ✅ |
| R5 | designer/assistant/linguist/lrelease/lupdate | 19/0 ✅ | 273/0 ✅ | 707 ✅ | 17/0 ✅ |
| **R6** | **assets 精简（eat_/f_/n_ + fx/）** | **19/1 ❌** | 273/0 ✅ | 707 ✅ | 17/0 ✅ |
| R7 | **上面六个 Qt 组一起删** | **19/0 ✅** | **273/0 ✅** | **707 ✅** | **17/0 ✅** |

R6 唯一那条红：`FAIL assets fx present` → 就是 `_verify_green.py:63-64`（见 §6）。

**「一删就红」的只有这一条，而且它拦的是 assets，不是 Qt。**

### R4 的额外证据（强制软件 GL）

`opengl32sw.dll` 删掉后，用 **QT_OPENGL=software** 强逼 Qt 走软件 GL 路径：

```
MODE=software PLATFORM=windows
sw_dll_present=False
GLCONTEXT_CREATE=True      <- 仍然建得出上下文
MAKECURRENT=True
```

因为 Qt 回退到了系统 opengl32.dll。另有旁证：源码里 **QOpenGLWidget / QQuickWidget / QOpenGL / QtOpenGL / setAttribute(Qt.AA_*) 一处都没有**，
产品是纯 QtWidgets raster 绘制，**从来不申请 GL 上下文**。→ 删除安全，但这条的风险是**机器相关**的（见 §5.5）。

---

## 4. 省多少（数字取自发布 zip 自己的中央目录，精确值不是估算）

zip：E:/deep seek/desktop-pet/daifeiyu-desktop-pet.zip，113,534,667 字节（108.28 MiB），3879 条目，压缩数据合计 107.49 MiB。

| 组 | 条目 | 压缩 MiB | 解压 MiB |
|---|---|---|---|
| QtWebEngine（全部含 webengine 字样） | 40 | **30.66** | 90.22 |
| └ 其中 5 个 *.debug.* 构件 | 5 | **16.83** | 77.16 |
| resources/icudtl.dat | 1 | **4.38** | 9.98 |
| PySide6/qml/ | 2531 | **8.53** | 23.95 |
| qml CLI 工具（8 个 exe，含 qmlls 1.32） | 8 | **2.48** | 6.48 |
| opengl32sw.dll | 1 | **7.32** | 19.68 |
| designer+assistant+linguist+lrelease+lupdate | 5 | **2.11** | 5.15 |
| **六组并集（去重后）** | **2566** | **55.43** | **155.25** |
| 再加上 webengine 组之外的 v8_context_snapshot.debug.bin | 1 | 0.35 | 2.33 |
| **六组 + 全部 *.debug.* 构件** | **2567** | **55.78** | **157.58** |

- 发布 zip：**107.49 → 52.07 MiB（−51.6%）**；含文件头/中央目录，成品 zip 约 **52–53 MiB**（原 108.28 MiB）。
- 解压体积：**292.62 → 137.37 MiB**。
- 单文件冠军：**qtwebengine_devtools_resources.debug.pak = 72.33 MB 原始 / 14.03 MiB 压缩 = 整个发布 zip 的 13.1%**，一个调试用资源。

任务书给的四个候选数字我全部复现：webengine 30.66、qml+qmlls 9.85（=8.53+1.32）、opengl32sw 7.32、Qt 工具 2.11。
（小订正：webengine 是 **40** 个条目不是 37；2.11 MiB 含 lrelease+lupdate，只算 designer/assistant/linguist 是 1.36 MiB。）

### 还没测的下一档（仅估算，本轮**未验证**）

- PySide6 顶层 .pyd/.pyi 中不属于 {QtCore, QtGui, QtWidgets, QtMultimedia} 的：**111 个条目 / 8.55 MiB 压缩 / 27.91 MB 原始**。
- 只被这些绑定拖进来的 Qt6*.dll：Qt6Network 0.73、Qt6OpenGL 0.39、Qt6Svg 0.25 MiB。
- ⚠️ Qt6Svg 被 imageformats/qsvg.dll 依赖，Qt6Network 很可能被 Qt6Multimedia 依赖 → **不能不看就删**。

---

## 5. 结论：哪些确实能删

### 5.1 确认可删（四道闸全绿 + 真实窗口正常）

1. **QtWebEngine 全家（40 条目 / 30.66 MiB）** — R1、R7
2. **resources/icudtl.dat（4.38 MiB）** — R2 单独删也全绿，说明**连 WebEngine 一起保留时它也是死的**（产品从不实例化 WebEngine）
3. **PySide6/qml/ + 8 个 qml CLI 工具（11.01 MiB）** — R3、R7
4. **opengl32sw.dll（7.32 MiB）** — R4（含强制软件 GL 探针）
5. **designer/assistant/linguist/lrelease/lupdate（2.11 MiB）** — R5

**六组一起删仍然全绿（R7）** → 没有隐藏的交叉依赖。

### 5.2 最低风险的第一刀

只删 **5 个 *.debug.* 文件 = 16.83 MiB**（占 WebEngine 成本 55%，占整包 15.7%），
纯调试资源，正常运行时不会被加载。**即使最终决定保留 WebEngine，也应该先删这 5 个。**

### 5.3 不建议删

**assets 精简** —— 省 3.67 MiB，代价见 §6。**性价比极差，不要做。**

### 5.4 对「核心版」的判断

- **纯 Qt 部分不需要改任何产品代码**，是发布脚本 / 打包清单的改动 + 绿色版检查单一处。
- 发布体积砍半（108.28 → 约 52–53 MiB），解压砍半（292.6 → 137 MiB）。
- 唯一需要动的仓库文件是 **`_verify_green.py:63-64`，且只有在你还想裁 assets 时才需要动**；只裁 Qt 的话**一行都不用改**。

### 5.5 诚实标注的风险点

opengl32sw.dll 是这五组里**唯一风险与机器相关**的：本机有可用显卡驱动，删掉后 Qt 回退到系统 opengl32.dll 照样建上下文，所以这里测不出来。
在没有/坏 GL 驱动的机器上，这个文件正是软件回退的本体。因为**产品代码零 GL 调用**，我判定它安全，但这条是「推不出来但风险可接受」，不是「实测证明无害」。

---

## 6. 反向问题：assets 只留「角色基础图 + idle 帧 + sounds」会不会红？

### 实测答案：**只有一条红，就是 _verify_green.py:63-64。**

```
FAIL assets fx present
GREEN CHECKS: 1 FAILS
```

同一轮里 **v13 273/0 ✅、pytest 707 passed ✅、真实窗口 GUI 17/0 ✅**。
也就是说：**这个精简对所有闸都是隐形的，只有那一行硬编码发现了它**——而且只发现了 fx 目录。

### 但「不红」不等于「没损失」

我写了个专门探针，pristine 与精简各跑一次，在启动接力装载跑完之后数实际可用的素材：

| 运行时到底加载到了什么 | 原样 | assets 精简后 |
|---|---|---|
| _idle_frames | 10 | 10 |
| _idle_full_frames | 10 | 10 |
| **_eat_frames** | 7 | **0** |
| **_fx_petpet**（摸摸头特效） | 10 | **0** |
| **_fx_money**（撒钱特效） | 86 | **0** |
| **state_pix 非空条目（表情美术图）** | **17 / 17** | **0 / 17** |
| assets/fx 条目 | 96 | 0 |
| assets/sounds 条目 | 6 | 6 |

根因（读源码得出，非猜测）：

- 桌宠.py:108-111 `_DEFAULT_FRAME_SETS` 把 `("eat", "", "eat", 7, ...)` 和 `("petpet", "fx", "petpet", 10, ...)` 列为**默认角色的正式帧集**；
- 桌宠.py:725 `_fill_state_pix`：`pix = win._load_img(["assets/%s_%s.png" % (form[0], s)])`，**`form[0]` 就是 n / f** → `n_angry.png`…`f_laugh.png` 这 17 张正是两个形态的表情状态图；
- 而 `_fill_state_pix` 的语义是**「缺图不建键」**（第 710 行注释），`_state_pix` 又有程序化叠图兜底 → **缺图不会抛错、不会红，只是悄悄没有美术**。

所以现状是：**一个会静默降级的功能面，只有一行 directory-exists 检查勉强看着它。**

### 要参数化哪几行（具体建议，**我没有改仓库**）

**只改 `_verify_green.py:63-64` 这两行**，其余不用动。现在是：

```python
check("assets fx present", os.path.isdir(os.path.join(HERE, "assets", "fx"))
      and os.path.isdir(os.path.join(HERE, "assets", "sounds")))
```

建议一：**拆成多条具名检查、并把「删素材」变成显式的版次开关**，而不是让它靠目录缺失被动发现：

```python
# _verify_green.py: 替换 63-64
_KEEP_FX = os.environ.get("DFY_GREEN_KEEP_FX", "1") == "1"
check("assets sounds present",
      os.path.isdir(os.path.join(HERE, "assets", "sounds")))
check("assets fx present",
      (not _KEEP_FX) or os.path.isdir(os.path.join(HERE, "assets", "fx")))
```

建议二：**改成按产品真正点名的文件来断言**（与 `_DEFAULT_FRAME_SETS`、`_fill_state_pix` 同一口径），
这样任何一条素材被删都会红，而不只是 fx 目录消失才红：

```python
_A = os.path.join(HERE, "assets")
check("eat frames", os.path.isfile(os.path.join(_A, "eat_f00.png")))
check("petpet fx frames", os.path.isfile(os.path.join(_A, "fx", "petpet_f00.png")))
check("money fx frames", os.path.isfile(os.path.join(_A, "fx", "money_f00.png")))
check("emotion state art", os.path.isfile(os.path.join(_A, "n_laugh.png"))
      and os.path.isfile(os.path.join(_A, "f_laugh.png")))
```

⚠️ **不能**改成在 `PetWindow()` 之后断言 `len(pet._fx_petpet) == 10`：
按 桌宠.py:105-106 的注释，idle 以外的帧集是**首帧显示之后才接力装载**的，
而 `_verify_green.py` 刻意**不转事件循环**就断言 → 那样写会自己造成假失败。用文件存在性断言最稳。

**这份素材账（吃了多少美术、换回多少 MiB）应该由发布脚本显式记一笔，而不是留给检查环节事后发现。**

---

## 7. 越界与偏差（如实交代）

### 7.1 ⚠️ 我往原绿色版目录写了 14 个 .pyc（唯一一处越界）

- 08:36:06 我跑的第一次自带 python 探测 `"…/大肥鱼桌宠_绿色版/python.exe" -c "import sys; print(sys.version)"`
  让内置 Python 的 site 引导**编译了 14 个 stdlib 模块**到 `Lib/__pycache__/` 和 `Lib/encodings/__pycache__/`。
- 已核对：原目录中 mtime 落在 08:30–08:40 的文件**恰好 14 个，全是 .pyc，全部位于 __pycache__ 目录内，没有一个是非 .pyc 或在 __pycache__ 之外**。
- **用户数据完好无损**：config.json 2026-10-10 21:10:19、roles.json / ledger.json / ledger_archive.json 21:09:46、memory.log 21:09:49，全部是实验前的旧时间戳；目录里没有 roles/ 子目录。
- 这些 .pyc 被 `.gitignore:39 (__pycache__/)` 覆盖，**git status 依旧干净**。
- **已于 09:15 经父代理授权清理完毕**（完整执行记录见 §7.1b）：绿色版目录回到实验开工前的 **3877 文件 / 306,949,957 字节**，**0 个 .pyc、0 个 __pycache__**。
  原（已执行过的）清理命令留档如下：

```powershell
Get-ChildItem "E:/deep seek/desktop-pet/大肥鱼桌宠_绿色版" -Recurse -Force -File -Filter *.pyc |
  Where-Object { $_.LastWriteTime -ge (Get-Date "2026-10-11 08:36:00") -and $_.LastWriteTime -lt (Get-Date "2026-10-11 08:37:00") } |
  Remove-Item -Force
Get-ChildItem "E:/deep seek/desktop-pet/大肥鱼桌宠_绿色版" -Recurse -Force -Directory -Filter __pycache__ |
  Where-Object { -not (Get-ChildItem $_.FullName -Force) } | Remove-Item -Force
```

### 7.2 R4/R5/R6 的背景状态不是「纯净的 pristine」

我的 stash/restore 助手在**目标已存在**时会把目录**嵌套**进去。R3 恢复时 `PySide6/qml` 已被某一步重新创建，
于是副本里变成了 `PySide6/qml/qml/…`（已实测确认：work 有 `qml/qml/QtQuick`，原目录是 `qml/QtQuick`）。

- **不影响任何结论**：每一轮在测试时刻都用 `Test-Path` 明确记录了目标组件的存在与否（存在 presence.txt）；
  R3 与 R7 都是在 `qml_dir=False` / `qmlls=False` 下跑的，本来就已经证明 qml 全删也能全绿。
- 直接后果只是：**R4/R5/R6 是在「qml 存在但结构错位（等于失效）」的前提下跑的**——这反而让这三轮更严格，不是更松。
- 但「每组之间都恢复到了原样」这句话**只对其余五组成立**，qml 那组不成立。仅限 %TEMP% 副本，仓库无关。

### 7.3 _verify_v13.py 的 proc resets to idle 是计时抖动

`_verify_v13.py:719-728` 给「合成动作播完并复位」的预算是**固定 1.2 秒**。
我在**第一次基线**跑出 1 FAIL（就是这条），之后 **7 轮 8 次全部 0 FAILS**。
→ 单独一条这个红当噪声处理，尤其在有别的代理同时抢 CPU 时。

### 7.4 pytest 数量漂移是并行代理造成的

基线 691 passed；之后恒为 **707 passed**。原因是并行代理新增了 `tests/test_asset_absence_v244.py`（+16）。
`git status` 里另有 `_dev/asset_absence_report.md`、`_dev/mutations_asset_absence_v244.json`、
`_dev/parasite_plugin_study.md`、`_dev/probe_asset_absence.py`、`_dev/README.md`（改动）——**都不是我写的**。
我的 checker 全程用 `-p no:cacheprovider` + `PYTHONDONTWRITEBYTECODE=1`，**没往仓库写任何东西**。

### 7.5 关于真实窗口探针的一处未解现象（**不是产品结论**）

最早一版探针在 `app.exec()` 上挂了 8 分钟不返回。后续定位：

- **在未裁剪的 pristine 副本上同样复现** → 与裁剪无关；
- 去掉 QMessageBox 屏蔽（DFY_NO_MODAL_STUB=1）后**不再复现**；
- 加了 warning 记录器后，整场会话 **warning 调用数 = 0**，也没有任何 modal 顶层窗口。

结论：这是**我探针迭代过程中的现象，不是产品缺陷**，我无法归因到具体哪一步，如实记录。
现行探针用有界 processEvents 循环 + 带硬逃逸的真 app.exec()，稳定通过。

---

## 8. 哪些**没有**在真实窗口下验证

真实窗口探针确实跑了真 windows 平台（platformName()=="windows"、1 屏、真 HWND、pet.grab() 480×480、
10 个对话框构造+show、3 秒事件循环 47 ticks、托盘 isVisible、真 app.exec() 返回 rc=0）。但以下是**没覆盖**的：

1. **没有任何人工交互**：菜单的 `exec` 被 stub（用子类捕获 actions 后立即返回），
   文件/输入/消息框全部被 stub 成立即返回——**否则整轮会阻塞**。所以「点开菜单、点某个菜单项真的生效」没验证。
2. **对话框内部的模态分支没走**：10 个对话框只验证了「构造 + show + close」不崩，**没点过里面任何按钮**。
3. **音频输出没有断言**：能加载音效库、sounds/ 6 个文件在，但**没验证真的出声**。
4. **托盘交互、拖拽、跟随/散步的鼠标路径、多显示器与 DPI 缩放**：全部未覆盖。
5. **opengl32sw 的「坏驱动机器」场景**：本机驱动正常，测不出差异（见 §5.5）。
6. **打包/解压后的真实运行**：所有实验都在**已解压的副本**上做，没有重新打 zip 再解压验证。
   §4 的体积数字来自现有 zip 的中央目录计算，**不是重新打包实测的体积**。

---

## 9. 建议的下一步

1. **先删 5 个 *.debug.* 文件（16.83 MiB，零风险）** —— 与「核心版」决策无关，单独就该做。
2. **核心版按 R7 的六组做**（2566 条目 / 55.43 MiB）：纯打包清单改动，产品代码一行不动。
3. **不要裁 assets**（省 3.67 MiB，损失吃帧 + 两个特效 + 17 张表情图，且只被一行检查拦着）。
4. 若确要认真评估 assets 版次：先把 §6 建议的参数化落到 `_verify_green.py:63-64`，再谈裁。
5. 下一档体积（111 个未用绑定 / 8.55 MiB + 相关 Qt6*.dll）**本轮未测**，需要单独一轮，
   且必须先确认 Qt6Svg / Qt6Network 被插件与多媒体依赖的实际情况。
6. **清掉 §7.1 的 14 个 .pyc**（或重新生成绿色版），免得发布检测假失败。

---

## 附：本轮四道闸在仓库上的最终单跑结果（供完工回报）

| 命令 | 结果 |
|---|---|
| `python -m pytest tests -o addopts="" -q` | **707 passed**（0 failed；含并行代理新增的 16 项） |
| `python _verify_v13.py` | **TOTAL CHECKS: 273, FAILS: 0** |
| `python _check_static.py` | **问题 0 条，待确认 0 条**（0/0） |

（三条都在 PYTHONDONTWRITEBYTECODE=1 下跑，仓库无新增产物。）

---

## §7.1b 清理执行记录（2026-10-11 09:15，经父代理授权）

**删前核对（全部通过）**

- 绿色版目录下 **.pyc 总数恰好 = 14**，**全部** mtime = 2026-10-11 08:36:06 —— 即**没有一个是我之外的来源**。
- **__pycache__ 目录恰好 = 2 个**：`Lib/__pycache__`（10 文件）、`Lib/encodings/__pycache__`（4 文件），无一例外。
- 08:30–08:40 窗口内：文件 14 个、**非 .pyc 的 0 个、位于 __pycache__ 之外的 0 个**。
- 逐条打印 14 条路径 + 大小后才删除；另加三条安全断言（必须在绿色根之下 / 扩展名 .pyc / 父目录名含 __pycache__），任一不满足即中止。

**删除内容（14 个 .pyc）**

```text
Lib/encodings/__pycache__/aliases.cpython-310.pyc        10959 B
Lib/encodings/__pycache__/gbk.cpython-310.pyc             1402 B
Lib/encodings/__pycache__/utf_8.cpython-310.pyc           1635 B
Lib/encodings/__pycache__/__init__.cpython-310.pyc        3945 B
Lib/__pycache__/abc.cpython-310.pyc                       6789 B
Lib/__pycache__/codecs.cpython-310.pyc                   33217 B
Lib/__pycache__/genericpath.cpython-310.pyc               3945 B
Lib/__pycache__/io.cpython-310.pyc                        3701 B
Lib/__pycache__/ntpath.cpython-310.pyc                   14782 B
Lib/__pycache__/os.cpython-310.pyc                       31594 B
Lib/__pycache__/site.cpython-310.pyc                     17418 B
Lib/__pycache__/stat.cpython-310.pyc                      4311 B
Lib/__pycache__/_collections_abc.cpython-310.pyc         32851 B
Lib/__pycache__/_sitebuiltins.cpython-310.pyc             3585 B
```

随后删除**删空后为空**的 2 个 __pycache__ 目录（两者均 0 子目录，删完为空）。

**删后核对**

| | 删前 | 删后 |
|---|---|---|
| 文件数 | 3891 | **3877** |
| 总字节 | 307,120,091 | **306,949,957** |
| .pyc 数 | 14 | **0** |
| __pycache__ 目录数 | 2 | **0** |

3877 文件 / 306,949,957 字节 **正好等于我实验开工前第一次测量原目录得到的数字** → 内容层面完全复原。

**用户数据：字节级一致**（name|size|mtime 刻度|sha256 四项全等，PRE vs POST 逐字节比对 = IDENTICAL）

```text
config.json           63 B  2026-10-10 21:10:19  sha256:61C9BBD8907CF39A
roles.json            33 B  2026-10-10 21:09:46  sha256:2DADB0EFDB76AE1B
ledger.json          116 B  2026-10-10 21:09:46  sha256:348D45B98A4C90CA
ledger_archive.json   16 B  2026-10-10 21:09:46  sha256:074723AC66E17558
memory.log           329 B  2026-10-10 21:09:49  sha256:D1A2C51E9841D74D
lines.json         20269 B  2026-10-10 19:04:51  sha256:8AB5F276BC276A95
error.log            142 B  2026-10-10 11:15:21  sha256:F4491CF65428CD98
roles/ 目录：不存在（本来就没有）
```

> 注：绿色版目录里**没有** `memory*.json`，记忆侧是 `memory.log`（329 B）；也没有 `roles/` 子目录。两者现状均与开工时一致。

**`_verify_green.py:14` 那条要求现在满足吗？—— 满足**

- 现在 `大肥鱼桌宠_绿色版` 下 **0 个 .pyc、0 个 __pycache__**。
- 旁证：**发布 zip 里 __pycache__/.pyc 条目数 = 0** → 「绿色版不含 __pycache__」本来就是这个项目的发布不变量，现已复原。

**残留的唯一痕迹：两个目录的 mtime（无任何内容变化）**

`Lib` 与 `Lib/encodings` 这两个**目录本身**的 mtime 现在是 2026-10-11 09:15:03。
它们**不是我创建的目录**（是原有的）；只是「在它们内部创建/删除 __pycache__」会更新父目录 mtime。
我**无法还原**这个 mtime —— 第一次写入之前我没有记录过它。同层未被触碰的兄弟目录可作参照：
`Lib/asyncio` 2026-10-10 17:25:12、 `Lib/ctypes` 22:06:37、 `Lib/collections` / `Lib/email` 23:54:59。
**仅目录 mtime 变化，无任何文件增删改。**

**机制已实测确认**（在一次性副本上做的对照实验，副本可弃）

| 调用方式（在绿色版目录内） | Lib/ 下新增 .pyc |
|---|---|
| `./python.exe -c "import sys"` | **14**（`Lib/__pycache__` 10 个 + `Lib/encodings/__pycache__` 4 个）—— 与我 08:36 造成的是完全同一批 |
| `./python.exe -B -c "import sys"` | **0** |
| `PYTHONDONTWRITEBYTECODE=1` + `./python.exe -c "import sys"` | **0** |

⚠️ **对发布流程的可操作建议**：内置解释器**在绿色版目录内启动时**，Python 会在跑任何脚本之前就把 stdlib 编译进
`Lib/__pycache__` —— 因此 `_verify_green.py:14` 的 `sys.dont_write_bytecode = True` **来不及拦住这一批**
（它只保护绿色根下的产品模块；实测 `_verify_green.py` 自己确实不会在绿色根留 __pycache__）。
凡是在绿色版目录里调用 `python.exe` 的地方（发布检测、打包前自检、冒烟脚本），
**一律加 `-B` 或设 `PYTHONDONTWRITEBYTECODE=1`**；否则每跑一次就多 14 个 .pyc，
而 `_verify_green.py:14` 的注释说得很清楚：这会让发布检测假失败。
