# v2.11.0 发版 runbook（⑤–⑬）· 给"下一轮完成收尾"用

> 前置：①–③ 已完（六门全绿）· **④ 冻结已完成**：`E:\deep seek\_v2110_release_freeze_final.txt`（212 条 / 无 BOM / `桌宠.py 0e66fadbd105`）。
> 用户指令：**v2.11.0 发出去之后主动报告**（Release + CI），**然后停下等安排**；v2.12.0 一律等发出去后再开。
> 铁律：**跑任何门/证据/三审时树必须静止**（无锁 / 无 python 测试进程 / 无写入者，三查缺一不可）。

## ⑤ 三审（找茬 / 质量 / 兼容）

三路**独立**派发（子代理，≤8 并发），每份任务书必须含：
1. **冻结哈希**（贴 `_v2110_release_freeze_final.txt` 的表，要求开工前**逐位比对**，不符就停手报）；
2. 各自重点：找茬＝判据有牙/边界/变异；质量＝用户体验/文案/空转断言；兼容＝老数据/绿色版/打包口径；
3. 硬要求：**每条发现给 `文件:行号` + 是否实测**；**查不到就说查不到**。
三审期间**一个字节都不许改**（改了就作废其余两路的锚点）。

## ⑥ 修三审（**先收齐再改**）

三份都回来 → 合并发现 → **一次性**派修复（文件不重叠）。修完 **⑥.5 重新冻结**（新哈希，旧表作废）。

## ⑦ delta 复跑 · ⑧ 独立验收

- ⑦ 让原审查回来复核：逐条判「真的好了 / 部分 / 没好」+ 重跑它那批变异；
- ⑧ **非作者**做独立验收：**抽检它的抽检 ≥2 条**——"还原前必须绿、还原后必须红"，抓"判据只守形状不守取值"。

## ⑨ 证据整批复跑（定版 · 安静窗口 · ~55 分钟）

```powershell
cd 'E:\deep seek\desktop-pet'
$env:PYTHONIOENCODING='utf-8'
python -B _dev/mutate_batch_v270.py *> 'E:\deep seek\_v2110_batch_out.txt'
"BATCH_EXIT=$LASTEXITCODE"
```
**必须看输出尾部**（`BATCH_EXIT=` + 最后几行），**不许只看作业状态**（历史血案：Tee 到不存在的目录 → python 根本没跑，作业却报 exit 0）。
跑完必查：`python -B _dev/check_pinned_ast.py` → **过期 0 / 已消失 0**；批次结果 **36 项 / 0 项非 0**。

## ⑩ 绿版同步

- 判据单一来源 = `_check_release.SYNC_FILES`（**不许手抄**；本轮已加入 `pet_windows / pet_backup / pet_guard / pet_time_mood / pet_notify`）。
- **显式目标路径**逐文件复制（`Copy-Item -Destination <目录>` 会拍平路径），逐文件 **sha256 比对**，清 `__pycache__`，**不许有 `_index_cache/`**，**用户数据一个都不许动**。
- 绿版自检：`cd 大肥鱼桌宠_绿色版; .\python.exe -B _verify_green.py` → **GREEN CHECKS: 0 FAILS**（本轮版本号已升 2.11.0，这份断言已同步）。
- `python -B _check_release.py` 的 `check_sync()` 必须变 **0 个问题**。

## ⑪ 白名单打包（**绝不许整目录**）

- 白名单同样只在 `_check_release.py`（`USER_DATA_NAMES / USER_DATA_DIRS / RESIDUE_RE / ZIP_EXTRA_*` + plugins 白名单）；
- 产物：仓库根 `daifeiyu-desktop-pet.zip`（**必须重打**，现在那份是 v2.10.0 的 115,123,751 B）；
- 打包后**解压自查** + 喂一个**毒样本**（例如把用户 `config.json` 放进暂存目录）证明判据不是空转。

## ⑫ 发布门

```powershell
python -B _check_release.py     # 必须打出 RELEASE CHECK OK
```
四个通道：`clean_tree`（**必须先提交**，否则它读"运行时代码有未提交改动"）/ `check_sync` / `check_zip` / 证据通道。
⚠ `clean_tree` 会点名未跟踪文件（`_dev/task_r11_v2110_round.md`、`_dev/probe_*.py` 等）→ 一并 `git add`。

## ⑬ 提交 → 推送 → Release → CI（**用户已授权"发出去之后跟我说"**）

```powershell
git add -A
git commit -m "v2.11.0：动起来好看 I + 旧第 8 轮那批落点 + 清账"
git push origin main
```
- Release：标题 `v2.11.0`，正文用 `_release_notes_v2110.md`，附件 = **本次重打的** `daifeiyu-desktop-pet.zip`；
  本机无 `gh` → 走 **GCM 凭据 + GitHub API**（凭据不打印、不落盘；做法见 `2026-10-16-1745-…-RELEASED.md` §二）；
- **CI 必须真看**：GCM → `api.github.com/.../actions/runs?per_page=3` → 对 `head_sha` 看 `conclusion`；
  红了就按 `_v2100_reviews/CI修复.md` 的流程定位到 step（**别忘了 CI 是 Pytest + Offscreen smoke 两个独立进程**）。
- **发完主动报告**：Release 链接 / tag / commit / 包大小 / CI 结论 → 然后**停下等用户安排**。

## 三个已知的坑（都踩过）

1. **作业 exit 0 可能是假的** → 长作业必须看输出尾部。
2. **静态门 ~13 分钟且不能并行**（规则 I 是 O(常量×文件)）；并行会变成 30+ 分钟。
3. **`_check_release` 的 `clean_tree` 要求先提交**，而 `check_zip` 要求先重打包 —— 两步都在 ⑫ 之前。
