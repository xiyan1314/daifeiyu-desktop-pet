# Gitee 镜像指南（国内 clone 加速）

> 目的：国内直连 GitHub 慢/不稳，镜像一份能让更多人 clone 到源码。
> 代码在 Gitee 上是**只读镜像**：主开发仍在 GitHub，Gitee 侧定期同步即可。

## 一、需要你做的事（我无法代做：需要 Gitee 账号与令牌）

1. 注册/登录 Gitee：https://gitee.com
2. 新建仓库：右上角 **+ → 新建仓库**
   - 仓库名称：`daifeiyu-desktop-pet`
   - 路径：`daifeiyu-desktop-pet`
   - **不要**勾选"使用 Readme 初始化"（否则首次 push 会冲突）
   - 开源许可：MIT（与主仓库一致）
3. 生成私人令牌：**设置 → 私人令牌 → 生成新令牌**，勾选 `projects` 权限
   （拿到后**不要**发给我，也不要把令牌写进任何文件——下面用环境变量传）

## 二、推送镜像（在仓库目录执行，PowerShell）

```powershell
cd "E:\deep seek\desktop-pet"
git remote add gitee https://gitee.com/<你的Gitee用户名>/daifeiyu-desktop-pet.git

# 首次推送（会提示输入 Gitee 用户名 + 私人令牌作为密码）
git push gitee main
git push gitee --tags        # 把版本 tag 也推过去
```

## 三、后续同步（每次 GitHub 发版后跑一次）

```powershell
git fetch origin main
git push gitee origin/main:main
git push gitee --tags
```

> 想全自动的话，Gitee 支持"仓库镜像管理"：**仓库 → 管理 → 镜像仓库 → 新建镜像**，
> 选"从 GitHub 导入"，填 `https://github.com/xiyan1314/daifeiyu-desktop-pet.git`，
> 勾选"自动同步"，之后 Gitee 会定期自己拉，不用手动 push。
>
> ⚠️ 注意：镜像仓库不会同步 Release 附件（Gitee 的附件走它自己的"发行版"），
> 所以建议在 Gitee 也手动发一次 Release 并上传 `daifeiyu-desktop-pet.zip`，
> 或者 README 里注明"下载请到 GitHub Releases，Gitee 只作源码镜像"。

## 四、建议同步到 Gitee 的内容

| 内容 | 是否同步 | 说明 |
|---|---|---|
| 源码（main 分支） | ✅ | 镜像主要目的 |
| 版本 tag | ✅ | `git push gitee --tags` |
| `daifeiyu-desktop-pet.zip`（112MB） | ⚠️ 手动 | 建议放到 Gitee 的"发行版"里，或写清去 GitHub 下载 |
| `CHANGELOG.md` / `_release_notes_v*.md` | ✅ | 已在仓库内，会随源码一起同步 |
| 用户数据（config/roles/ledger） | ❌ | 永不入库（已在 .gitignore） |