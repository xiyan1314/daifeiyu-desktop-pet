# 角色画廊规范（gallery/）

> 这里放社区贡献的自定义角色包，README 的「角色画廊」表格从这里取数据。

## 目录结构

```
gallery/
├── README.md              ← 本文件（规范）
├── lazycat_preview.png    ← 预览图（≤200×200，PNG，透明底更佳）
├── lazycat.dfypet.zip     ← 角色包（桌宠菜单「导出角色包」生成）
├── cybersnake_preview.png
└── cybersnake.dfypet.zip
```

## 命名约定

- 一律**小写英文 + 下划线**：`<角色id>_preview.png` / `<角色id>.dfypet.zip`
- 同名预览图与角色包必须成对出现（README 表格里的下载链接指向角色包）
- 角色包内的 `manifest.meta` 建议填全（角色名 / 作者 / 简介 / 标签），导入方会显示作者

## 提交方式（PR）

1. 在桌宠里导出你的角色包：右键 → 角色 → **导出角色包** → 填角色信息 → 保存 `.dfypet.zip`
2. 准备一张预览图（≤200×200，PNG）
3. Fork 本仓库，把两个文件放进 `gallery/`
4. 在 `README.md` 的「角色画廊」表格里加一行（角色 / 作者 / 描述 / 下载）
5. 提 PR，并在描述里写一句："我确认这个角色是我自制或有权分享的"

## 审核标准（宽松）

- ✅ 能正常导入、不崩（我们会在最新版上跑一次导入）
-- ✅ 素材无版权争议（自己画的 / 剪映做的 / AI 生成的都可以，请注明来源）
- ❌ 不收录：含他人作品的直接搬运、含可执行文件/脚本、体积异常（> 30MB 请先精简帧数）

## 不想提 PR？

直接到 [Discussions 的「晒角色」帖](https://github.com/xiyan1314/daifeiyu-desktop-pet/discussions/1)
回复：附角色包 + 预览图 + 一句话介绍。我们会定期把合适的角色搬进 `gallery/`。