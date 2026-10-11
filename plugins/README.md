# PetHub 官方内容插件（官方索引）

> v2.5.1 起，桌宠的「官方内容」就放在这个目录里，**随绿色版与发布包一起出货**——不用联网也能装。
> **包格式与红线的随包说明**就是本文件末尾那节「包的格式与红线（速查）」（绿色版里也翻得到）；
> 开发期的完整判据文档在仓库的 _dev/plugin_format_v251.md（**不进发布包**，拿到绿色版的用户
> 看不到它），校验器实现是 pet_plugin.py（12 条判据，Qt-free，随绿色版一起出货）。

## 目录里有什么

| 文件 | 说明 |
|---|---|
| index.json | 官方索引：index_version / updated_at / host_min / plugins[]（每条含 id、name、kind、data_kind、code、summary、author、releases[]） |
| packs/&lt;id&gt;-&lt;版本&gt;.dfypet-plugin.zip | 包本体（就是一个 zip；扩展名只是给人看的，校验按内容来） |
| README.md | 本文件 |

**用户装的插件不在这里**：宿主把装好的插件放在「数据目录/plugins/&lt;id&gt;/」，另有
_installed.json 记启用状态、_download/ 放临时下载——那些是**用户数据**，打包时一律排除。
本目录只有「官方内容」这一份，跟着程序走。

## 五个官方包

| 包 | 类型 | 大小 | 装上会看到什么 |
|---|---|---|---|
| official-audio-core 官方·基础音效 | 音效 audio | 165 KB | 「资源管理 → 音频片段」多 6 条音频（点击/松开/被戳/喂食/AI 回复完成/金币到账），可在「音效组」里指派 |
| official-lines-moyu 官方·摸鱼台词 | 台词 lines | 2.0 KB | 台词库多 12 条（撒娇/贪吃/开心/闲逛各 3 条）+ 一组「摸鱼三连」对白；你原有的台词一条不动 |
| official-role-daifeiyu 官方·大肥鱼角色包 | 角色 role | 1.2 MB | 角色列表多一只「官方·大肥鱼」（可改名/删除）；戳戳、喂食、睡觉的表情走这套美术图，而不是程序化叠图 |
| official-behaviors-idle 官方·待机行为 | 行为 behaviors | 2.5 KB | 行为库多 4 条（得意炫耀/害羞扭扭/蜷着睡/闻到零食），可在「待机设置」里排顺序与权重 |
| official-persona-moyu 官方·人设「摸鱼搭子」 | 人设 prompt | 1.3 KB | AI 设置的人设下拉里多一项「我的：摸鱼搭子」，选中即换性格说话 |

### 装 / 卸 / 重装的账（v2.5.1）

* **直接重装同一个包 = 覆盖更新**：插件目录整体替换，安装登记里仍然只有一条；**内容不重复
  导入**（角色 / 台词 / 音效在首次安装时已经进了库，再导一遍只会多出一份）。包内容变了也一样：
  覆盖更新只换插件目录，包内**新增 / 改动的内容不会自动进库**——要重新导入请**先卸载再装**。
* **卸载后再装 = 重新导入**：卸载只删插件目录，已落地的角色 / 台词 / 音效**保留**（那是用户
  数据，与「导入角色包」同口径）；再装一次就等于"第一次装"，会再进一份。
* **换机器 / 升级时把整个 plugins/ 一起拷走**（含 _installed.json）：它是"装过什么、什么已经
  落地"的账本。只拷 plugins/&lt;插件 id&gt;/ 而漏掉 _installed.json，重装同一个包会被当成
  第一次安装 → 内容再进一份。
* **没落地的内容会写在安装结果里**：role 插件包里如果还夹带了台词 / 参考音 / 闹钟设置，本版本
  **不会**导入它们（它们只在"手动导入角色包"那条路上生效），安装完成的提示里会列出"N 项内容
  没有导入"——看到那行别以为是装失败了。

每个包的**详细说明**（包含什么 / 多大 / 装上会看到什么 / 包内结构 / 落地方式）写在包自己的
manifest.json 的 plugin.description 里——安装器与插件管理对话框读的就是这一段，所以它跟包的
内容永远同步，不会像文档一样过期。

### ① official-audio-core —— 官方·基础音效（6 段）

* **包含什么**：assets/sounds 里的 6 个 wav（ya1 / ya2 / d1 / d2 / task-end-a / exp-orb）。
* **多大**：包 165 KB。
* **装上会看到什么**：「资源管理 → 音频片段」里多 6 条（显示名分别是 点击·呀 / 松开·呀啊 /
  被戳到·抖一下 / 喂食·啊呜 / AI 回复完成 / 金币到账），**不会动你现在的音效组**——
  要不要把它们指派给点击/松开/喂食/AI 回复/金币，由你在「音效组」里自己选。
* **包内结构**：payload/audio/&lt;6 个 wav&gt; + payload/audio/pack.json（建议显示名；宿主有意不采纳槽位建议）。
* **落地方式**：宿主逐个调 AudioLibrary.import_file（拷进 数据目录/audio/ 并写 audio.json）。

### ② official-lines-moyu —— 官方·摸鱼台词（12 条 + 1 组对白）

* **包含什么**：12 条原创台词（撒娇/贪吃/开心/闲逛各 3 条）+ 一组三句的对白编排「摸鱼三连」。
* **多大**：包 2.0 KB。
* **装上会看到什么**：台词库里多这 12 条（类别已分好，会参与随机台词与待机），对白列表里多
  「摸鱼三连」；**你原有的台词一条都不会动、也不会被覆盖**。
* **包内结构**：payload/lines.json，形状 {"lines":[{"key","text","category","role_slot","voice_slot"}…],
  "dialogues":[{"name","lines":[key…]}]}。
* **落地方式**：宿主逐条 LineService.add 并按 key → 新 id 建对白；任一条失败逐条回滚。

### ③ official-role-daifeiyu —— 官方·大肥鱼角色包（双形态 + 17 张表情）

* **包含什么**：本体 4 张（侧/正 × 常态/吃饱）+ 17 张表情状态图（常态 10 / 吃饱 7）。
* **多大**：包 1.2 MB。
* **装上会看到什么**：角色列表里多一只「官方·大肥鱼」，可改名/切换/删除；戳戳、喂食、
  睡觉、被夸时用它自带的表情美术图（自定义角色默认是程序化叠图）；**原有角色一个不动**，
  重复安装会再进一只（id 不冲突）。
* **包内结构**：payload/role.json（角色 dict，素材引用就是 payload 根下的 png 文件名）+
  21 张 png 平铺在 payload 根。
* **落地方式**：宿主把素材换新文件名复制进 数据目录/roles/，改写引用后走
  pet_export.land_role —— 与「导入角色包」**同一套口径**（id 冲突换新、写索引失败回滚）。

### ④ official-behaviors-idle —— 官方·待机行为（4 条）

* **包含什么**：4 条行为的 JSON（coin_brag 得意炫耀 / shy_wiggle 害羞扭扭 / sleepy_curl 蜷着睡 /
  snack_alert 闻到零食），动作类型与参数都过宿主的 validate_steps。
* **多大**：包 2.5 KB。
* **装上会看到什么**：行为库多这 4 条，可在「待机设置」里把它们排进待机动作列表（顺序/权重自选）。
* **包内结构**：payload/behaviors/&lt;名字&gt;.json，每个文件与宿主「导出行为」逐字段一致
  （{"behavior":{"id","name","steps"}} 外加 format/version 两个说明键）。
* **⚠️ id 口径**：文件里的 id 是**必须自带的 8 位小写 hex**（宿主 BehaviorService 的硬判据：
  长度 8 且每个字符都在 0123456789abcdef 里）。官方包用它自己算的确定性示例 id
  （md5("dfypet-official:" + 行为名) 取前 8 位）；**入库时宿主的 import_file 会分配全新的 uuid**，
  所以这个 id 只是一张"入场券"，不参与任何跨包引用，也不需要谁跟谁算出同一个值。
* **落地方式**：宿主逐条 BehaviorService.import_file（它负责校验 id 与动作序列、给新 id）。

### ⑤ official-persona-moyu —— 官方·人设「摸鱼搭子」

* **包含什么**：一份人设文本（约 200 字），轻松口语化的摸鱼搭子。
* **多大**：包 1.3 KB。
* **装上会看到什么**：AI 设置的人设下拉里多一项「我的：摸鱼搭子」，选中就能让它换性格说话；
  **同名文件一律拒绝，绝不覆盖你自己写的人设**。
* **包内结构**：payload/prompts/摸鱼搭子.txt（文件名就是界面里显示的预设名）。
* **落地方式**：宿主拷进 数据目录/prompts/custom/&lt;文件名&gt;（宿主的 persona_file_ids 自动认）。

## 索引格式（index.json）

    {
      "index_version": 1,
      "updated_at": "2026-10-11",
      "host_min": "2.5.0",
      "plugins": [
        {
          "id": "official-lines-moyu",
          "name": "官方·摸鱼台词（12 条 + 1 组对白）",
          "kind": "data",
          "data_kind": "lines",
          "code": false,
          "summary": "…一句话…",
          "author": "大肥鱼桌宠（官方）",
          "releases": [
            {
              "version": "1.0.0",
              "min_host_version": "2.5.0",
              "api_version": 1,
              "url": "packs/official-lines-moyu-1.0.0.dfypet-plugin.zip",
              "sha256": "…包本体的 sha256…",
              "bytes": 2000,
              "published_at": "2026-10-11"
            }
          ]
        }
      ]
    }

* **url 是相对 index.json 所在目录的路径**（也可以直接写成 https 绝对地址）。发布到 GitHub
  Release 时用打包工具的 --base-url 重算一遍即可。
* **sha256 / bytes 是包本体的真实哈希与大小**：下载侧先核对再安装（打包工具自动算，不手写）。
* host_min / min_host_version 是宿主版本下限：宿主版本不够，校验器会**硬拒**并告诉你
  「要求 X，当前 Y」。

## 包的格式与红线（速查）

* 一个包 = 一个 zip：根下只有 manifest.json（UTF-8、**无 BOM**），其余全部在 payload/ 单根下。
* manifest 顶层只放包级字段（format / version / payload_root / created_at / files）；
  插件元数据全在 plugin 段（id / name / version / kind / data_kind / code / min_host_version /
  api_version / capabilities …）。**顶层重复键一律忽略**（单一真源）。
* **官方包一律 kind=data、code=false、capabilities=[]（零权限）**：包里没有一行代码。
* 允许的扩展名只有 .png .jpg .jpeg .wav .mp3 .txt .json .md；出现
  .py .pyc .pyd .dll .exe .bat .cmd .ps1 .vbs .js .com .scr .msi .lnk 或嵌套压缩包
  .zip .7z .rar .tar .gz —— **整包拒绝并点名那个文件**。
* ⚠ **扩展名白名单只看后缀、不校验文件内容**：一个 .py 改名成 .png 能过校验。宿主从不执行
  payload 里的任何东西（kind=data、code=false、capabilities=[]），所以这不是漏洞；但**人设
  （prompt）类是纯文本**，会被 AI 设置选中当人设用——**只装你信得过的包**。
* **plugins/ 下有几个保留名**：`packs/`、`index.json`、`README.md`、`_installed.json`、
  `_download/`。它们是官方内容仓库与宿主自己的目录，**不许被当插件 id**（校验器与安装器都会
  拒，卸载也一样），读插件清单时直接跳过。**别把自己的包丢进 packs/**：官方资产以 index.json
  里登记的 url 为准，packs/ 里的其他文件既不会被认成官方内容，也不该跟着发布包出货。
* files 必须**不多不少**覆盖 payload 下每一个文件条目（逐条 sha256 + bytes）；目录条目不算。
* kind=ui 本版本无条件拒绝；每个包还带 min_host_version 与 api_version 两道版本门。

## 自己做一个包 / 重新生成官方包

    # 重新生成官方包 + 索引（幂等：复跑产物逐字节相同）
    python -B _dev/build_official_plugins.py

    # 只比对：临时重打一遍，与 plugins/ 逐字节比较（不写盘）
    python -B _dev/build_official_plugins.py --check

打包工具会在构建期做两道门：① 每个包过 pet_plugin.validate_plugin_zip（12 条判据）；
② 每个上架的包在临时数据目录里**真装一次**（PluginHost.install_zip），宿主库必须真的多出内容
——装不上就直接非零退出，不会把装不上的包写进索引。

想自己做包：照上面「包的格式与红线」写 manifest.json + payload/，用校验器验一遍
（pet_plugin.validate_plugin_zip(包路径, "2.5.0") 必须返回 (manifest, "")），
再在本地用「插件管理 → 安装」选它试装即可。
