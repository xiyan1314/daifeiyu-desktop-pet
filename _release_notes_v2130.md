# 大肥鱼桌宠 v2.13.0 发布说明（2026-11-16）

> 主题：**体积与暴露面**——发布包从 3890 条 / 309.5 MB 压到 **968 条 / 123.3 MiB**、一级菜单（最多 18 项）收到 **恰好 9 项**、
> 补上首屏 GIF 与第 1 个官方角色包，并给"素材热重载 / 首启 0 弹窗 / 崩溃自恢复"留下可复跑的验收。
> 这一轮**不是功能轮**：没有新玩法，只有更小的包、更短的菜单、更少的暴露面。
> 验证读数见 §七；本轮经过三审（三路独立）+ 修复波，下面标「审查实测」的是审查在影子副本里抓到的。

## 一、包体积：3890 条 / 309.5 MB → 968 条 / 123.3 MiB

### 怎么压的（白名单 + 瘦身清单，单一来源）

- 发布门新增 **`check_pack()`**（`_check_release.py`）：解压后 **≤150 MiB**、条目 **≤1300**、
  顶层白名单（`PACK_TOP_ALLOWED` 穷举 58 项）之外多一个就红、瘦身清单命中就红、
  两个明令保留项缺一个就红。数字写死在门里 —— **下次再胖回去，发版时当场红**。
- 瘦身脚本 `_dev/prune_green.py` 只读同一份清单（不抄第二遍），并按 T0-06 校验
  "解析后的路径仍在 root 之内"；用法是**先副本、后真包**。

| 删掉的 | 体积 | 文件数 | 为什么能删 |
|---|---|---|---|
| `PySide6/resources/` | 106.3 MB | 11 | WebEngine 的 `.pak`，全仓零引用 |
| `PySide6/qml/` | 25.1 MB | 2519 | 全仓没有 QML |
| 未用绑定 `.pyd`（Qt3D*/QtCharts/QtQuick/QtWebEngine*…） | ~27 MB | ~50 | 产品只 import QtCore/QtGui/QtWidgets/QtMultimedia/**QtNetwork** |
| Qt 开发工具（assistant/designer/linguist/qmlls…） | ~13 MB | ~18 | 运行期不用 |
| 类型桩 `.pyi` / metatypes / typesystems / glue / scripts / support / lib / QtAsyncio / distutils | ~10 MB | ~330 | 开发期才用 |
| **合计** | **171.9 MiB** | **2923** | 绿色版目录 295.3 → 123.4 MiB |

**两个明令保留**：`opengl32sw.dll`（19.7 MB，R-94）与 `avcodec-61.dll`（13.4 MB，QtMultimedia 依赖）。
**审查实测的一条意外**：`QtNetwork.pyd` 也不能删 —— QtMultimedia 的抽帧路径在 C++ 侧动态 import 它，
删掉后 `_verify_green.py` 的「video extract in green」当场红（`libshiboken: could not import module 'PySide6.QtNetwork'`）。

### 怎么验的

- 先在**副本**上 `--apply` → 副本的 `_verify_green.py` **GREEN CHECKS: 0 FAILS**（视频抽帧 3 帧）；
- 再对真绿版目录 `--apply` → **982 files / 123.4 MiB**（同步本轮新代码后 **983 files**），再跑一次 `_verify_green.py` **0 FAILS**；
- 发布包重新打包后由 `check_pack()` 复算：**条目与解压体积都要在门限内**。

## 二、一级菜单（最多 18，余额行在场时）→ 恰好 9（只搬家，不删功能）

| 原来在顶层 | 现在在哪 |
|---|---|
| 余额 / 今日已用信息行（不可点） | **💰 记账** 子菜单首行 |
| 📌 窗口置顶 · 🔊 音效 · 🤖 AI 对话 · 🌀 甩抛物理 | **⚙️ 设置…** 第一组 |
| ❤️ 夸夸她 · ☀️ 今日天气 · 📍 天气城市… · 🖥️ 系统状态 · ℹ️ 关于 | **ℹ️ 更多** |
| 其余（说话/喂食/角色/记账/资源管理/设置/动作/退出） | 原位 |

新结构：`💭 和它说话 · 🍖 喂食 · 🐟 角色 · 💰 记账 · 📦 资源管理 · ⚙️ 设置… · 🎭 动作 · ℹ️ 更多 · ⏹ 退出`。

- 两处硬断言（`_verify_green.py` / `_verify_v13.py`）与 4 条旧用例同步收紧到 **≤9**；
- 新增 `tests/test_menu_v2130.py`：**恰好 9 条**（不是 ≤9）、**搬家后每条都还能触发**（spy）、
  余额行只读、资源管理仍恰好一条（D3 不回归）、设置子菜单没丢功能（≥30 条）。

## 三、素材热重载（2 秒生效，不用重启）

- 新模块 `pet_hotreload.py`（**纯逻辑、零 Qt**）：文件签名 = `mtime_ns + size`；`Watcher.prime/poll`
  只回答"自上次以来变了哪些"，判据可喂假 stat（1ms 级），不靠 sleep。
- 窗口侧 2s 一拍：**只在待机态**重载（走路/表情/睡觉/吃帧/变身中途不换贴图），
  重载内容 = 贴图 / 状态图 / 帧集 / 音效，重载后一条气泡「素材已重新加载~」。
- **监听边界**：内置 `assets/` 全树 + 根级 `character*.png`；**用户角色文件不自动重读**
  （编辑到一半的 PNG 不该被读进来；角色切换走既有 `apply_role`）。
- 判据：`tests/test_hotreload_v2130.py` —— 纯逻辑 5 条 + 真窗口 5 条（含"改 character.png 后同一窗口
  像素真的变了"与"busy 时不许重载"；两条都实测能把改坏的代码抓红）。

## 四、门面：README 首屏 GIF + gallery 第 1 个官方包

- `docs/demo.gif`：320×320 / **17 帧**（10 帧待机 + 7 帧吃播，全部来自真实 `assets/`），README 中英首屏引用。
- `gallery/official_abyss.dfypet.zip`（+ `_preview.png`）：官方「深渊大肥鱼」，由内置 assets
  **色相旋转派生**（不引入任何外部素材，符合 plan §16）；生成脚本 `_dev/build_gallery_pack_v2130.py`，
  产物过 `pet_export.validate_bundle`；README 画廊表两处新增一行。

## 五、两条验收（此前没有统一读数）

1. **首启 0 弹窗**：真窗口跑 3.1s（覆盖 D1 的 2600ms 定时器），`QMessageBox` 四个静态入口 +
   `QMessageBox.exec` + `QDialog.exec` **全程 0 次**；D1 引导仍然只走一条气泡并落盘。
2. **崩溃自恢复（端到端）**：真跑 `main.py`，替身第一次 `SystemExit(3)` → 守护**拉起恰好一次** →
   替身第二次正常返回即停；`crash_recovery.json` 落盘。此前只有 `pet_guard` 的纯逻辑判据，
   `main.py` 那条真的 spawn 子进程的路径没跑过。

## 六、遗留-13：6 条"只守形状"的判据换 AST

`tests/test_easter_v2120.py` 的 5 条 + `tests/test_firstrun_v2120.py` 的 1 条此前读源码字符串 ——
**把调用注释掉仍然绿**（v2.12.0 独立验收 X1 实测）。现在读 AST（注释天然不进语法树）：
影子副本实测 **8 个变异全部 RED**（注释掉 poke/feed/late/落盘、删方法、改 start 参数、写死 enabled、tray_tip 判断改 if True）。

## 七、验证读数

> 定版九门 + 证据整批复跑后回写（没跑过的数字不写）。

| 项 | 读数 |
|---|---|
| pytest | 待取 |
| `_verify_v13` | 待取 |
| 静态体检 | 待取 |
| 锚点 / nodeid / pinned | 待取 |
| 静默 except | 待取 |
| 绿版同步 / `RELEASE CHECK OK` | 待取 |
| 发布包 | 待取（条目 / 解压 MiB / 压缩 B / sha256） |
| CI | 待取 |