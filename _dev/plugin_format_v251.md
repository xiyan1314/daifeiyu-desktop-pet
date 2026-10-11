# 插件包格式 v1（dfypet-plugin）· 单一真源

> v2.5.1 代理A（Phase 0）。**校验器**：[`pet_plugin.py`](../pet_plugin.py)（12 条判据，Qt-free）。
> 本文与校验器里的常量/清单**同时写死**，由 `tests/test_plugin_v251.py::test_禁止项清单与文档同时写死`
> 钉住（两边漂了就红）。

## 1. 包结构

```
x.dfypet-plugin            # 就是一个 zip（扩展名随意，内容必须是 zip）
├── manifest.json          # 根下唯一在 payload 之外的文件（UTF-8，**无 BOM**）
└── payload/               # 单根：payload 之外不许有任何文件
    ├── a.txt
    └── sub/b.png          # 允许子目录
```

* 条目名必须 `== "manifest.json"` 或以 `payload_root` 开头；不含 `..`、不以 `/` 或盘符开头、
  不含反斜杠、不含 NUL、无空路径段。
* 写包工具带的**目录条目**（`payload/`）允许，且不参与 `files` 覆盖计数。
* `external_attr >> 16` 不许带执行位（`mode & 0o111`）；符号链接（`0o120000`）一律拒。

## 2. manifest.json 字段（**顶层只放包级字段，插件元数据全在 plugin 段**）

```json
{
  "format": "dfypet-plugin",
  "version": 1,
  "payload_root": "payload/",
  "created_at": "2026-10-11T00:00:00",
  "files": [{"path": "payload/a.txt", "sha256": "<64 位小写 hex>", "bytes": 5}],
  "plugin": {
    "id": "official-lines-basic",
    "name": "示例台词包",
    "version": "1.0.0",
    "author": "官方",
    "homepage": "",
    "license": "MIT",
    "description": "装上会看到什么",
    "summary": "一句话",
    "kind": "data",
    "data_kind": "lines",
    "code": false,
    "min_host_version": "2.5.0",
    "max_host_version": "",
    "api_version": 1,
    "capabilities": [],
    "events": [],
    "signature": ""
  }
}
```

| 字段 | 位置 | 必填 | 口径 |
|---|---|---|---|
| `format` | 顶层 | ✔ | 字面量 `"dfypet-plugin"` |
| `version` | 顶层 | ✔ | **包格式版本**：int，`1 <= version <= 1`（宿主 `PLUGIN_FORMAT_VERSION`） |
| `payload_root` | 顶层 | ✘ | 缺省 `"payload/"`；给了就必须以 `/` 结尾且是安全相对目录 |
| `files` | 顶层 | ✔ | 逐条 `{"path": <zip 内条目名>, "sha256": <hex>, "bytes": <int>}`；**只认 `path`** |
| `created_at` | 顶层 | ✘ | 仅记录 |
| `id` | plugin | ✔ | 安装目录名（`plugins/<id>/`）：`[A-Za-z0-9][A-Za-z0-9._-]{0,63}`，不许以点结尾、不许 `..`、不许 Windows 保留名、不许**宿主保留名**（见 §6） |
| `name` | plugin | ✘ | 缺省用 `id` |
| `version` | plugin | ✘ | 插件自身版本（int/str），仅记录 |
| `author` / `homepage` / `license` / `description` / `summary` | plugin | ✘ | 仅展示 |
| `kind` | plugin | ✔ | `"data"`（`"ui"` 本版本一律拒） |
| `data_kind` | plugin | kind=data 时 ✔ | 见下表 `DATA_KINDS` |
| `code` | plugin | ✔ | bool：`kind=data ⇒ false`；非 data ⇒ true |
| `min_host_version` | plugin | ✔ | 宿主版本下限（四段整数比较：`"2.5"` == `"2.5.0"`）。**必须是数字版本串**：`"abc"` / `"latest"` 一律拒（v2.5.1 修复：`version_key` 只抽数字，写错的版本串此前会被抽成 `(0,0,0,0)` 而**恒放行**） |
| `max_host_version` | plugin | ✘ | 仅记录，**本轮不参与判定** |
| `api_version` | plugin | ✔ | 必须 ∈ `{1}` |
| `capabilities` | plugin | ✘ | 宿主权限白名单（见下）的子集；**空表 `[]` 合法 = 纯数据零权限** |
| `events` / `signature` | plugin | ✘ | 仅记录：**本轮不验签**（Phase 0 只做结构校验） |

**顶层重复键一律忽略**（不是拒绝）：如果 `id`/`kind` 之类在顶层又写了一份，校验器
只读 `plugin` 段——单一真源，免得两处漂移。

## 3. 取值表

`DATA_KINDS`（每个都有现成的宿主落地管线）：

| data_kind | 落到哪 |
|---|---|
| `role` | RoleLibrary（角色） |
| `lines` | LineService（台词） |
| `audio` | AudioLibrary（音效/音频片段） |
| `voice_ref` | VoiceAssetLibrary（参考音/声音素材） |
| `behaviors` | BehaviorService（行为） |
| `prompt` | 人设文件（prompt） |

`CAPABILITIES`（宿主权限白名单 v1）：与 `DATA_KINDS` **同一套名字**（`role` `lines` `audio`
`voice_ref` `behaviors` `prompt`）。空表 = 零权限。越界（例如 `network`）一律拒。

> 注意：`fx` / `states` / `sounds` **不是**合法的 data_kind / capability——那些是应用自带的
> `assets/` 内容，本轮没有"把帧素材落到用户目录"的管线。

## 4. 禁止项清单（**校验器与本文同时写死**）

payload 里出现下面任何一类，整包拒绝并**点名该文件**：

* **可执行 / 脚本**：`.py` `.pyc` `.pyd` `.dll` `.exe` `.bat` `.cmd` `.ps1` `.vbs` `.js`
  `.com` `.scr` `.msi` `.lnk`
* **嵌套压缩包**：`.zip` `.7z` `.rar` `.tar` `.gz`

扩展名白名单（**只允许**这些）：`.png` `.jpg` `.jpeg` `.wav` `.mp3` `.txt` `.json` `.md`

> ⚠ **白名单只看后缀，不校验文件内容**：一个 `.py` 改名成 `.png` 能过校验。宿主从不执行 payload
> 里的任何东西（`kind=data` / `code=false` / `capabilities=[]`），所以这不是漏洞；但 `prompt`
> 类是**纯文本**、会被 AI 设置选中当人设用——只装信得过的包。这一条同时写进了随包的
> `plugins/README.md`（绿色版用户读得到的那份）。

## 5. 容量与校验

* 条目数 ≤ `pet_export.EXPORT_MAX_ENTRIES`（2000）；解压总量 ≤ `pet_export.EXPORT_MAX_BYTES`
  （512 MiB）——**与角色包同一份常量**，不是各写一份。
  * 第一道闸看 zip 中央目录**声明**的 `file_size`（可以是假的）；判据 10 读内容时**分块**统计
    **真实**解压字节再比一次上限（v2.5.1：此前用 `zf.read` 把每个文件整份读进内存，64 MB
    payload 实测峰值 141 MB，按上限外推 >1 GB）。
* `files` 必须**不多不少**覆盖 `payload` 下每一个文件条目：多一条（含把 `manifest.json` 也列进去）
  或漏一条都拒；每条都要对得上真实 `sha256` 与 `bytes`（sha256 是**边读边算**的，不靠整份内容驻留内存）。

## 6. 宿主安装目录口径（与 `_check_release` 对齐）

```
<DATA_DIR>/plugins/
├── _installed.json            # 宿主写的安装索引：{"format":"dfypet-plugins-installed","version":1,
│                              #   "plugins": {"<id>": {"enabled": bool, "source_url": str, ...}}}
├── _download/                 # 临时下载目录（用户数据，**绝不发包**）
├── <id>/                      # 用户装的插件（用户数据，**绝不发包**）
└── packs/ + index.json + README.md   # 官方内容（随绿色版与发布包出货）
```

`read_installed(plugins_dir) -> (list[dict], list[str])` 只读扫 `<dir>/<id>/manifest.json` 与
`_installed.json`；坏目录/坏 JSON 只跳过并进问题串，**绝不抛**；目录不存在返回 `([], [])`。
条目形如 `{"id","name","version","kind","data_kind","enabled","source_url","dir"}`。

**保留名（v2.5.1 兼容审查 P1-1 / P2-2）**：`packs` / `index.json` / `README.md` /
`_installed.json` / `_download` 是出货布局里**不是插件**的名字（官方内容仓库 + 宿主自己的
登记与临时目录）。三处一致：

1. **校验器**拒（`_id_problem`："plugin.id 是宿主的保留名"）；
2. **安装器 / 卸载 / 启停**拒（`pet_plugin_host._reserved_problem`，单靠保留名清单不够，
   还加了第二道保险：目标目录存在却**没有 `manifest.json`、登记表里也没这条** → 拒绝覆盖）；
3. **读清单**静默跳过（不再对 `packs/` 报"缺 manifest.json，已跳过"）。

清单只有一份：`pet_plugin.RESERVED_PLUGIN_NAMES`（大小写不敏感——Windows/macOS 上
`PACKS` 与 `packs` 是同一个目录）。

**安装事务（v2.5.1）**：解包在 `plugins/.tmp-xxxx`（与目标**同盘**）里做 → 提交用 `os.replace`
（同盘 rename 原子；此前 `%TEMP%` 跨盘 `shutil.move` = copytree+rmtree，失败留半截目录）→
写 `_installed.json`。「已装」以**登记表**为准：登记里没有这条、或这条的 `landed` 是空表
（内容从没落地过，例如手工拷进来的目录），按新装处理、照常落地；同 id 换 `data_kind` 明确拒绝。
任何一步失败都逐条回滚已经并进宿主库的内容（`_unland`），不留"库里有、登记里没有"的孤儿。

## 7. 开发者自检

```powershell
python -B -m pytest tests/test_plugin_v251.py -o addopts="" -q
```
