# v2.5.1 第 3 轮任务书（PetHub 插件地基 · 三路并行，领地互斥）

仓库：E:\deep seek\desktop-pet。基线 v2.5.0 = HEAD 8a81376，工作树干净。护栏：pytest **795** · v13 **273/0** · 静态 **0/0**。

## 通用铁律（三路必读）
1. 跑全量 pytest 前确认 `_dev/.mutation.lock/` 不存在；**别在多路并行改树时下结论**（并发假红踩过三次）。
2. 绿色版目录里调用 python.exe **一律加 `-B`**；**语法检查别用 `python -m py_compile`**（`-B` 拦不住它），改用 `python -B -c "import ast; ast.parse(...)"`。
3. 源码里**不要写字面量 `pet.xxx(` 或 `pet_dialogs.py` 这类形状**——扫描器是纯文本正则，会误命中（踩过三次）。
4. 每条改动配**能真失败**的测试（优先变异验证：把修复拿掉必须红）。
5. 不碰 VERSION / version_info.txt / _verify_green.py / CHANGELOG.md / _release_notes_*.md / 绿色版 / 发布 zip。不提交（由主代理统一提交）。
6. 如实报告没做到的；**数字必须来自实跑**，不许预写。

---

## 代理 A：Phase 0 校验器 + 两条发布门冲突 + 两条 v2.5.0 遗留

**领地：新建 `pet_plugin.py`、`_check_release.py`、`pet_dialogs.py`（仅 L5 那一个 clamp 字面量）、`tests/test_plugin_v251.py`（新建）、`tests/test_release_check.py`、`tests/test_dialog_fit_v250.py`（仅 L5 的 `_DESIGN_SIZES` 一行）、`_dev/**`。**

### A1（Phase 0，主任务）`pet_plugin.py`：只做"看懂一个插件包"，不安装、不碰 UI、不碰启动路径
必须是 **Qt-free 纯逻辑模块**（可无 GUI 单测）。实现：
- 常量：`PLUGIN_FORMAT = "dfypet-plugin"`、`API_VERSIONS = {1}`、`CAPABILITIES`（宿主白名单）、`ALLOWED_EXTS`、`FORBIDDEN_EXTS`、`DATA_KINDS`。
- `validate_plugin_zip(path, host_version) -> (manifest | None, err)`，**12 条判据**：
  1 zip 可打开；条目数 ≤ 2000；解压总量 ≤ 512MB（**复用** `pet_export` 的 `EXPORT_MAX_ENTRIES` / `EXPORT_MAX_BYTES`）
  2 `manifest.json` 存在、UTF-8 **无 BOM**、可解析为 dict
  3 `format == "dfypet-plugin"`；`version` 是 int 且 ≤ 宿主支持
  4 **全量 namelist 路径安全**：每个条目必须 `== "manifest.json"` 或 `startswith(payload_root)`；不含 `..`、不以 `/` 或盘符开头、不含 `\`、不含 NUL
  5 **外部属性**：`external_attr >> 16` 不得带执行位（`mode & 0o111`）；符号链接位（`0o120000`）一律拒
  6 **扩展名白名单**：`.png .jpg .jpeg .wav .mp3 .txt .json .md`；其余**点名文件**拒绝
  7 **code 一致性**：`kind == "data"` ⇒ `code is False`；`kind != "data"` ⇒ `code is True`；不一致即拒
  8 `capabilities ⊆ CAPABILITIES`
  9 **双版本门硬拒**：`min_host_version <= 宿主 VERSION`（用与 `_check_release` 同款四段整数比较），不满足则拒绝且 err 里给出"要求 X，当前 Y"；`api_version ∉ API_VERSIONS` 也拒
 10 **校验和**：`files` 必须覆盖 payload 下**每一个**条目（多一个少一个都拒）；逐条核对 `sha256` 与 `bytes`
 11 `kind == "data"` ⇒ `data_kind ∈ DATA_KINDS`
 12 `kind == "ui"` ⇒ **无条件拒绝**（"本版本不支持 UI 插件"）
- `read_installed(plugins_dir) -> (list[dict], list[str])`：只读扫 `<dir>/*/manifest.json` 与 `_installed.json`；**坏目录/坏 JSON 只跳过并进问题串，绝不抛**；目录不存在返回 `([], [])`。
- **禁止项清单**（校验器与文档同时写死）：`.py .pyc .pyd .dll .exe .bat .cmd .ps1 .vbs .js .com .scr .msi .lnk` 与嵌套压缩包 `.zip .7z .rar .tar .gz`。
- **验收 = `tests/test_plugin_v251.py`，14 条**（每条都要能真失败）：合法数据包通过 · 缺 plugin 段拒 · `kind=data` 却 `code=true` 拒 · payload 里有 `evil.py` **点名拒绝** · 条目名含 `..` 拒 · `min_host_version=99.0.0` 拒且 err 含 99.0.0 与当前版本 · `api_version=2` 拒 · `sha256` 改一位拒并点名文件 · 某 payload 文件不在 `files` 里拒 · `kind=ui` 拒 · plugins 目录不存在返回空不抛 · 目录里放普通文件跳过不抛 · `plugins/x/` 无 manifest 跳过不抛 · **回归：现有 `.dfypet.zip` 的 `validate_bundle` 行为逐位不变**（`test_export*` 全绿）。

### A2（冲突一）`_check_release.SYNC_FILES` 缺**反向校验**
现状：`check_shipped_files()` 只检查"清单里的文件还在磁盘上"，`check_zip` 的 `need = _sync_pairs()` 只含清单 + assets → **新增模块若不加进清单，绿色版/发布包缺件时任何门都不响、用户双击即 ImportError**（本轮 `pet_services.py` 就差点这样）。
**修**：新增一条**反向校验**——扫源码里所有 `import pet_*` / `from pet_* import` 的模块名，**必须都在 SYNC_FILES 里**（排除测试/自检脚本与 `_dev`）；漏了就报。配能真失败的测试（从清单里删一个真模块 → 必须报）。

### A3（冲突二）`USER_DATA_DIRS` 不含 `plugins`
现状：用户装了插件后打包，**发布包会把用户插件一起发出去**。**修**：把 `plugins`（含 `plugins/_download` 之类临时目录）加进"用户数据"清单，确保打包/同步时被排除。配能真失败的测试。

### A4（v2.5.0 遗留 L5）`RoleEditDialog` 设计宽 600 与内容最小宽 620 差 20px
**三处必须同步改**，否则设计尺寸契约用例会红：① `pet_dialogs.py` 的那个 `clamp_dialog(self, 600, ...)` 字面量 ② `tests/test_dialog_fit_v250.py` 的 `_DESIGN_SIZES["RoleEditDialog"]` ③ `_dev/dialog_size_report.md` 的设计尺寸表。**注意**：CHANGELOG / 发布说明里写着"设计尺寸一个没改"（那是 v2.5.0 的事实）——你改了之后**在本轮 CHANGELOG 里注明**"RoleEditDialog 设计宽 600 → 620（消除 20px 横向滚动条）"，我会写进 v2.5.1 的 CHANGELOG。

---

## 代理 B：Phase 1 安装管线 + 只读插件管理对话框（接口按 A 的签名写）

**领地：新建 `pet_plugin_host.py`、`pet_export.py`（只抽可复用落地函数，**不许改 `format:"dfypet-role"` 的行为**）、`pet_dialogs.py`（只加插件管理对话框）、`pet_menu.py`（只在设置子菜单里加入口）、`桌宠.py`（**只加一行接线**）、`tests/test_plugin_host_v251.py`（新建）。**

**接口约定（A 正在实现，你按这个签名写，不要改它）**：`pet_plugin.validate_plugin_zip(path, host_version) -> (manifest | None, err)` · `pet_plugin.read_installed(plugins_dir) -> (list[dict], list[str])`。

### B1 安装/卸载/禁用
新建 `pet_plugin_host.py`：
- `install_zip(path) -> (ok: bool, msg: str)`：下载/校验（**调 A 的校验器**）→ **失败则显示具体原因并删临时文件，`plugins/` 下不留任何残余** → 通过则解包到 `<DATA_DIR>/plugins/<id>/` 并写 `_installed.json`（记 `source_url` / `zip_sha256` / 安装时间 / 校验结果 / `enabled`）。
- `uninstall(id) -> (ok, msg)`：删 `plugins/<id>/`；**已落地到宿主库的资产不删**（角色/台词已进 `roles.json`/`lines.json`，属用户数据，与"导入角色包"同口径）——**确认框里必须写明这一点**。
- `set_enabled(id, on)`：只改 `_installed.json`，文件保留（可逆）。
- `list_installed()`：调 A 的 `read_installed`。
- **落地动作复用现有管线**：从 `pet_export.py` 抽出可复用的落地函数（例如角色落地那段），**错误文案逐字不变**（`:226` 注释明说调用方与测试依赖那些字面量）。

### B2 只读插件管理对话框 + 菜单入口
- 在 `pet_dialogs.py` 里加一个**插件管理对话框**（复用现有 `Dialog(pet)` + `modal()` 形态；**只读列表**：id/名称/版本/kind/是否启用/来源；按钮：安装（选 zip）/卸载/启用禁用/刷新）。**尺寸必须走 v2.5.0 的 `_FitDialog` 那套**（clamp + 可滚动 + 按钮吸附），并在 `tests/test_dialog_fit_v250.py` 的窗口清单里登记它。
- **菜单入口必须放进「⚙️ 设置…」子菜单**——`_verify_v13.py` 有顶层菜单硬上限 18 项的断言，**加顶层项必红**。
- `桌宠.py` 的接线**只能一行**（`PetWindow.__init__` 已 423 行、212 方法；再加逻辑就是加剧 God Object）。

### B3 验收（都要能真失败）
① 装一个合法数据包 → 目标库条目增加且**原有内容一条不少** ② 装完卸载 → 条目**仍在**但 `plugins/<id>/` 已删 ③ `min_host_version=99.0.0` → 拒绝**且 `plugins/` 下不留任何文件** ④ 含 `evil.py` → 拒绝并**点名** ⑤ 重复装同一包 → 冲突处理正确 ⑥ 反向：把校验器的扩展名白名单注释掉 → 判据 ④ 必须红。

---

## 代理 C：官方内容插件 + 索引（让"用户能下载内容"这条链路真实跑通）

**领地：新建 `plugins/**`（含 `plugins/index.json`）、`_dev/build_official_plugins.py`（打包工具）、`_dev/plugin_packs_report.md`、`README.md` 的插件小节（只加一节）。不要动产品代码与 tests。**

### C1 从现有可选素材做 3-5 个**官方内容插件**
素材现状：`assets/` 共 150 文件（PNG 144 + WAV 6），其中金币特效 86 帧、摸头 10、吃 7、吃饱呼吸 10、状态图 17、音效 6。**按类型切成插件包**（例如：①金币特效包 ②互动特效包（摸头+吃+呼吸）③表情包 ④音效包 ⑤台词包（示例，让用户知道格式））。
- 每个包按 **Phase 0 的格式**做（`format: "dfypet-plugin"`、`manifest.json` 逐字段、`files` 逐条 sha256+bytes、`payload/` 单根、`kind: "data"`、`data_kind`、`code: false`、`min_host_version` 填当前版本、`api_version: 1`、`capabilities` 取最小必要）。
- **写一个打包工具** `_dev/build_official_plugins.py`（可复跑、幂等、输出到 `plugins/packs/` 或你判断更合适的位置），**不要手搓 zip**。
- 每个包附一份**人类可读说明**（`README` 或 `plugin.json` 里的 description），写清"包含什么/多大/装上会看到什么"。

### C2 `plugins/index.json`
按方案里的索引格式（`index_version` / `updated_at` / `host_min` / `plugins[]`，每条含 `id` / `name` / `kind` / `data_kind` / `code` / `summary` / `author` / `releases[]`（`version` / `min_host_version` / `api_version` / `url` / `sha256` / `bytes` / `published_at`））。**sha256 必须是真实的包哈希**（用你的打包工具算出来写进去）。

### C3 验收
- **每个官方包都必须能通过 A 的校验器**（`validate_plugin_zip` 返回 `(manifest, "")`）——这是你这轮最硬的判据；A 还没落地前你可以先按 12 条判据**自己写一个临时校验脚本**核对（放 `_dev/`，A 落地后换成调它的）。
- **反向**：故意把某个包的 `files` 里少写一个条目 / 改一位 sha256 / 塞一个 `.py` → 必须被拒。
- `_dev/build_official_plugins.py` 复跑两次，产物**逐字节相同**（幂等）。

---

## 共同验收（安静窗口、串行）
- `python -B -m pytest tests -o addopts="" -q` → 0 failed（基线 795）
- `python -B _verify_v13.py` → 273 项 0 FAILS
- `python -B _check_static.py`（单跑）→ 0 问题 0 待确认

回报时分别给出：改动清单 · 三项数字 · **没做到/有疑问**。