# v2.6.0 第 4 轮任务书（插件分发 Phase 2 + D7-B · 三路并行，领地互斥）

仓库 E:\deep seek\desktop-pet。基线：HEAD `7ee8766`（v2.5.1 + CI 修复），工作树干净。护栏：pytest **948** · v13 **273/0** · 静态 **0/0**。**公开 CI 现在是绿的（#51 success）——请让它保持绿。**

## 通用铁律
1. 跑全量前确认 `_dev/.mutation.lock/` 不存在；**别在多路并行改树时下结论**（并发假红踩过多次）。
2. 绿色版目录里调 python.exe **一律加 `-B`**；**语法检查别用 `python -m py_compile`**（`-B` 拦不住），用 `python -B -c "import ast; ast.parse(...)"`。
3. 源码里**不要写字面量 `pet.xxx(` 或 `pet_dialogs.py`** 这类形状（纯文本扫描器会误命中）。
4. **每条改动配能真失败的测试**（优先变异验证）。**不许放宽既有断言**。
5. **测试断言不许依赖机器速度**——这是上一轮公开 CI 红了五个提交的病根。要注入"每单位固定成本"再断言结构性事实。
6. 不碰 VERSION / version_info.txt / _verify_green.py / CHANGELOG.md / _release_notes_*.md / 绿色版 / 发布 zip。不提交（我统一提交）。
7. 如实报告没做到的；**数字必须来自实跑**。

---

## 代理 A：插件分发 Phase 2（下载器 + 市场页 + 更新/回滚/合并）

**领地：新建 `pet_plugin_index.py`、`pet_plugin_host.py`、`pet_dialogs.py`、`tests/test_plugin_market_v252.py`（新建）、`_dev/**` 里你自己的证据。**

### A1 索引下载器 `pet_plugin_index.py`（Qt-free 纯逻辑，可无 GUI 单测）
- 读 `plugins/index.json` 与**远端索引**（同一格式），**注入式取数**（构造时传一个 `fetch(url) -> (bytes|None, err)`，默认实现用 urllib；**测试一律注入假 fetch，不许真联网**）。
- **哈希校验**：下载后必须核对 `sha256` 与 `bytes`，不符即拒并删临时文件；解包前再走 **`pet_plugin.validate_plugin_zip`**（校验器是唯一真源，别自己再写一套判据）。
- 下载到临时文件 → 校验 → 交给 `PluginHost.install_zip` → **任何一步失败都不留残余**。
- `base_url` 口径沿用已参数化的那套（相对 `packs/x.zip` 与绝对 URL 都要能取到；**相对路径按"随包的本地副本"解析**）。
- 版本比较用与 `_check_release` 同款的四段整数比较；`host_min` 高于宿主则该条目**标为不可装**并给出可读原因，**不是静默隐藏**。

### A2 市场页（扩充 `PluginManagerDialog`）
- 两个页签：**已安装**（现有列表）/ **可安装**（索引里的条目：名称/类型/大小/版本/是否已装/可不可装）。
- 操作：安装（带进度与可读错误）、**更新**（有新版本时出现）、**回滚**（见 A3）、卸载、启用禁用、刷新索引。
- **尺寸与滚动必须走 `_FitDialog` 那套**，并在 `tests/test_dialog_fit_v250.py` 的口径表里登记（该文件归 A，见下）。
- **网络操作不许卡界面**：下载走后台线程 + 信号回主线程（照抄 `pet_balance` 那套代次/守卫口径，别自创）。

### A3 更新 / 回滚 / 合并语义（这是本轮最容易做假的地方，请实打实做）
- **更新**：同 id 装新版本时，**把新版新增内容真正并进宿主库**（不再"内容不重复导入"地跳过）。需要**按内容哈希去重**的落地记录：`_installed.json` 里记每个已落地条目的内容指纹，更新时"只落新的、不重复落旧的"。
- **回滚**：保留上一个版本的 payload（例如 `plugins/<id>/.previous/`）与落地记录；回滚 = 恢复上一版目录 + 把这一版**新落地**的条目撤销（**用户自己的内容一件都不许动**）+ 登记回到上一版状态。
- **禁用**：维持 v2.5.1 的口径（只改登记、不撤内容），但**界面文案必须与行为一致**（现在写"已禁用"容易被理解成卸载）。
- **每一步都要有能真失败的用例**：更新补内容、更新不重复落旧内容、回滚撤销新版新增且不碰用户数据、回滚后再次更新仍正确。

### A4 `tests/test_dialog_fit_v250.py`（本文件归你）
- 市场页改成多页签后，`PluginManagerDialog` 的设计尺寸若变，**三处同步**：源码 `clamp_dialog` 字面量 / `_DESIGN_SIZES` / `_dev/dialog_size_report.md`；并保持"每个可钳制对话框都必须登记在口径表里"与"登记类必须真是 `_FitDialog` 子类"两条契约绿。

---

## 代理 B：D7-B —— 211 条静默 except 逐条判定

**领地：除 `pet_plugin.py`、`pet_plugin_host.py`、`pet_plugin_index.py`、`pet_dialogs.py` 之外的产品模块（`pet_*.py`、`桌宠.py`）、`pet_log.py`（如需）、新建 `tests/test_silent_except_v252.py`、`_dev/silent_except_*`。**

- 现成工具：`_dev/audit_silent_except.py`（实测输出 **A=0 / B=219 / C=128 / OK=119**，分档口径见该脚本）。**以它的列表为起点**，逐条判定 B 档（`except: pass` 类）。
- **判定三选一**：① 该补日志 → 用**限流口径**（`pet_log.guard_slot` 或 60s 同名一条；**注意别刷屏**，参考 v2.5.1 里 `keep_source` 按角色 id 限流的做法）② 该改逻辑（例如吞掉了本该上报的错误）③ **确实该静默**（清理/探测/关闭路径）→ **写进白名单并给出理由**。
- **硬要求**：a) **白名单要落成数据 + 有测试钉住**（新增静默 except 必须让测试红——否则白名单会变成垃圾桶）b) 每条改动都要**能真失败**的用例（构造触发路径，断言"有日志"或"行为符合预期"）c) **A 档必须保持 0**。
- 若某条判定需要动 `桌宠.py`，**照做**（该文件归你），但要**极小改动**、并跑全量护栏。
- 交付：`_dev/silent_except_report_v252.md`（逐条：位置 / 现行为 / 判定 / 依据 / 是否实测）+ 代码改动 + 白名单数据 + 测试。**211 条要全部有归属**，不许"未判定"收尾。

---

## 代理 C：门禁与文档收口

**领地：`pet_plugin.py`、`_check_release.py`、`_dev/_mutate_lib.py`、`plugins/README.md`、`_dev/*.md`、`tests/test_release_check.py`、`tests/test_plugin_v251.py`。**

1. **校验器与安装器两处口径差**（v2.5.1 审查实测）：`payload/a:b.png` 过校验但解包被判越界；`files: []` 过校验但安装器才拒。→ **让校验器也拒**（Windows 非法字符 `<>:"|?*` 与保留设备名；`files` 为空即拒），并**同步 12 条判据文档**（`_dev/plugin_format_v251.md`）+ 补能真失败的用例。**注意**：这会让之前"能过"的合成包变成被拒——**确认 5 个官方包仍全部通过**（它们是唯一真实样本）。
2. **变异指纹"缺键"提示**：现在 `stale_fingerprints` 只比对"记录里存在的键"，导致其余 14 份 `_dev/*.json` 看不见 `pet_plugin.py`/`pet_plugin_host.py`/`pet_dialogs.py`/`pet_menu.py` 的改动。→ 让发布门**能提示"这份证据缺这些键"**（**提示级，别挡发布**），配能真失败的用例；若你判断会把老证据一次性全标脏，就在报告里说明取舍与影响面。
3. **文档同步**：`_dev/plugin_packs_report.md` 的 `890` → **948**（或写成"基线由当轮实测为准"避免再过期）· `plugins/README.md` 补"市场/更新/回滚"的新口径（A 落地后对齐）· `_dev/build_official_plugins.py` 的过期 docstring（说只接 role/lines）· `_dev/dialog_size_report.md` 若 A 改了尺寸则同步。
4. **`_dev/README.md`** 登记本轮新增 spec/报告与两条新铁律（"断言不许依赖机器速度"、"契约必须双向覆盖"）。

---

## 共同验收（安静窗口、串行）
- `python -B -m pytest tests -o addopts="" -q` → **0 failed**（基线 948）
- `python -B _verify_v13.py` → **273 项 0 FAILS**
- `python -B _check_static.py`（单跑）→ **0 问题 0 待确认**

回报：改动清单 · 三项数字 · **没做到/有疑问**。