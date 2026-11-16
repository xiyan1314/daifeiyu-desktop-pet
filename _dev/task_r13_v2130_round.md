# 第 13 轮 · v2.13.0 · 体积与暴露面（作业单）

> 派工：`plan_v270_rounds.md` §25.3（唯一有效表）。
> 本轮不做功能扩张：**瘦身 + 收口 + 门面 + 两条验收**；素材链/WebP 在下一轮（v2.14.0）。

## 一、范围（做完即停）

| # | 项 | 判据（文件） | 备注 |
|---|---|---|---|
| 1 | **遗留-13**：6 条只守形状的判据换 AST | `tests/test_easter_v2120.py` · `tests/test_firstrun_v2120.py` | 先把调用注释掉仍绿 → 换 AST 后必须红（影子副本实测 8 个变异全红） |
| 2 | **一级菜单 18 → 9** | `tests/test_menu_v2130.py` | 搬家不删功能：余额行进「记账」、四个开关进「设置」、陪伴/天气/状态/关于进「更多」 |
| 3 | **解压体积 ≤150 MiB / 条目 ≤1300** | `_check_release.PACK_*` · `_dev/prune_green.py` · `tests/test_pack_v2130.py` | 白名单（顶层穷举）+ 瘦身清单（单一来源）；明令保留 `opengl32sw.dll` / `avcodec-61.dll` |
| 4 | **素材热重载** | `pet_hotreload.py` · `tests/test_hotreload_v2130.py` | 2s 一份签名；改 `assets/` 不用重启。用户角色文件不在监听面（显式 apply_role 重载） |
| 5 | **README 首屏 GIF** | `docs/demo.gif` · `tests/test_face_v2130.py` | 17 帧真实素材（10 idle + 7 eat），不画新图 |
| 6 | **gallery/ 1 个官方包** | `gallery/official_abyss.dfypet.zip` + 预览 · `_dev/build_gallery_pack_v2130.py` | 由内置 assets 色相派生（§16：不引外部素材） |
| 7 | **首启 0 弹窗** | `tests/test_round13_accept_v2130.py` | 真窗口跑 3.1s，QMessageBox/QDialog 全程 0 次 |
| 8 | **崩溃自恢复验收** | `tests/test_round13_accept_v2130.py` | 真跑 `main.py`：第一次 SystemExit(3) → 守护拉起一次 → 第二次正常返回即停 |

## 二、口径（写死，不许临场改）

- **体积按解压后算**：`pack_stats()` 读 zip 条目；MB 一律 **MiB**（150 × 1024 × 1024）。
- **瘦身只删 PySide6 里产品不用的**：`PACK_PRUNE_DIRS` + 未用绑定（`PACK_PY_KEEP` 之外）+ 未用 DLL。
  保留项一：`opengl32sw.dll`（19.7 MB，R-94 明令）与 `avcodec-61.dll`（13.4 MB，QtMultimedia 依赖）。
- **QtNetwork 必须留**：QtMultimedia 抽帧路径在 C++ 侧动态 import `PySide6.QtNetwork`（实测删除后
  `_verify_green.py` 的"video extract in green"红）。
- **白名单漏了会红**：新增顶层条目必须同时进 `PACK_TOP_ALLOWED`；体积/条目回涨也会红。
- **热重载的边界**：只监听内置 `assets/` 与根级 `character*.png`；用户角色文件**不自动重读**
  （避免读到编辑一半的半成品；角色切换有显式重载）。

## 三、收尾（老规矩，一步不跳）

九门 → 冻结 → 三审（≥3 路独立）→ 收齐再改 → delta → 独立验收（≥2 条还原必红）→ 证据整批 →
绿版同步（含瘦身；先副本后真包）→ 白名单打包 → `RELEASE CHECK OK` → 推送/tag/Release/CI。

> ⚠ 本轮改动面在**打包构成**：绿版目录不是 git 仓库内容，瘦身脚本必须先 `--dry-run` 再
> `--root <副本> --apply` 跑通 `_verify_green.py`，最后才动真包。