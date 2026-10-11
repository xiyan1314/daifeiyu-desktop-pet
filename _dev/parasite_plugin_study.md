# 寄生式插件调研报告（代理 C）

> 产出人：代理 C ｜ 日期：本轮 ｜ 领地：**只读 + 本文件**
> 本报告**没有改动任何产品代码**；仓库内唯一写入是本文件。
> 调研前 \`git status --porcelain\` 实测输出：\`?? _dev/probe_asset_absence.py\`（**不是我建的**，是并行代理的产物，我未触碰）。
> HEAD = \`9ab85bb\`（v2.4.3），除上面那个未跟踪文件外工作树干净。

## 0. 证据口径与版本说明（先读这一节）

| 代号 | 含义 |
|---|---|
| **实测** | 我本人读到了那段字节 / 跑出了那个输出（命令 + 返回） |
| **读码推断** | 源码/文档写了、我没运行它去观察运行时行为 |
| **没找到** | 我找过、没有 |

**版本错位（很重要，别把两版 README 混为一谈）**：

- 本机 \`node_modules\` 里躺的是 **dsh-whale-widget 0.3.9**（实测：\`C:\Users\29179\.dsh\profiles\desktop\node_modules\dsh-whale-widget\package.json:3\` → \`"version": "0.3.9"\`）。
- npm 上最新已经是 **0.3.18**（实测：\`https://registry.npmjs.org/dsh-whale-widget\` → \`dist-tags.latest = 0.3.18\`，共 28 个版本）。
- 本机那份 \`README.md\`（401 行）是 **0.3.9 时代**的文本，**没有**「官方桌面端（Electron 客户端）请先看这一节」。
- 那一节在**市场页抓取的 HEAD 版 README** 里（实测：\`https://awesome-dsh-plugin.com/p/MeteorNOX/DeepSeek-Balance-Whale-Widget/\`，正文里 \`官方桌面端（Electron 客户端）请先看这一节\` 首次出现在页面前段）。

**各文件在后面的简称**：

| 简称 | 真实路径 |
|---|---|
| \`WW/pkg\` | \`C:\Users\29179\.dsh\profiles\desktop\node_modules\dsh-whale-widget\package.json\` |
| \`WW/patch\` | \`C:\Users\29179\.dsh\profiles\desktop\node_modules\dsh-whale-widget\cordis.patch.yml\` |
| \`WW/README\` | \`C:\Users\29179\.dsh\profiles\desktop\node_modules\dsh-whale-widget\README.md\`（0.3.9） |
| \`WW/host\` | \`C:\Users\29179\.dsh\profiles\desktop\node_modules\dsh-whale-widget\lib\index.js\`（宿主侧 Node 半区，3471 行） |
| \`WW/client\` | \`C:\Users\29179\.dsh\profiles\desktop\node_modules\dsh-whale-widget\assets\whale-widget.js\`（前端半区，14455 行 / 717022 B） |
| \`DSH/ws\` | \`E:\deep seek\DSH Desktop\resources\app\node_modules\@deepseek-ai\dsh-host-webserver\lib\index.js\` |
| \`DSH/bin\` | \`E:\deep seek\DSH Desktop\resources\app\node_modules\@deepseek-ai\dsh\lib\bin.js\` |
| \`MKT/cli\` | \`C:\Users\29179\.dsh\profiles\desktop\node_modules\dshmarket\lib\dsh-cli.js\` |
| \`MKT/reg\` | \`C:\Users\29179\.dsh\profiles\desktop\node_modules\dshmarket\lib\registry.js\` |
| \`MKT/npmcat\` | \`C:\Users\29179\.dsh\profiles\desktop\node_modules\dshmarket\lib\catalog-npm.js\` |
| \`SB/patch\` | \`C:\Users\29179\.dsh\profiles\desktop\node_modules\dsh-better-sidebar\cordis.patch.yml\` |
| \`SB/pkg\` | \`C:\Users\29179\.dsh\profiles\desktop\node_modules\dsh-better-sidebar\package.json\` |
| \`P/pkg\` | \`C:\Users\29179\.dsh\profiles\desktop\package.json\`（desktop profile 的 manifest） |
| \`P/patch\` | \`C:\Users\29179\.dsh\profiles\desktop\cordis.patch.yml\` |
| \`R/README\` | \`E:\deep seek\desktop-pet\README.md\`（我们自己的，227 行） |

---

# A. 寄生模式（技术）

## A1 它怎么挂进宿主：三段式，不是"注入一个脚本"那么简单

**第一段：包声明自己是 bundle**（实测，\`WW/pkg:29-33\`）

\`\`\`json
"dsh": { "bundle": { "patch": "./cordis.patch.yml" } }
\`\`\`

**第二段：patch 层插一行**（实测，\`WW/patch:13-15\`）

\`\`\`yaml
- insert:
    - id: dsh-whale-widget
      name: dsh-whale-widget
\`\`\`

注释里写明了安装命令：\`dsh plugin --profile web add dsh-whale-widget\`（\`WW/patch:7-10\`）。

**第三段：被写进 profile 的 bundle 栈**（实测，\`P/package.json:12\` 依赖 + \`P/package.json:17-29\` 的 \`dsh.profile.bundles\` 数组，\`dsh-whale-widget\` 在第 20 行）。
profile 自己的 patch 层在 \`P/patch\` 里（这个文件里**没有**鲸鱼的行——bundle patch 已经把活干了）。

> 对照：better-sidebar 在 README 式的注释里把这三段讲得最清楚，\`SB/patch:1-45\`（"the command reconciles \`dsh.profile.bundles\` against installed packages … one command installs and mounts"），并且它还用 \`!!js\` 表达式做了**聚合包重复挂载守卫**（\`SB/patch:46-49\`）。这是"工程化写法"和"够用写法"的分水岭。

**第四段（真正"寄生"的地方）：宿主半区把前端脚本塞进 index.html。**
（实测，\`WW/host:3458-3463\`）

\`\`\`js
disposers.push(ctx.webServer.tapIndex((html) => {
  if (html.indexOf('/dsh-whale/widget.js') !== -1) return html
  const tag = '<script defer src="/dsh-whale/widget.js"></script>'
  if (html.indexOf('</body>') !== -1) return html.replace('</body>', tag + '</body>')
  return html + tag
}))
\`\`\`

而 \`/dsh-whale/widget.js\` 是它**自己注册的路由**（实测，\`WW/host:3446-3456\`，\`kind:'exact'\`），内容来自 \`loadWidgetJs()\`，按 mtime 热读磁盘文件（\`WW/host:578-582\` 附近；README 也写了"前端由宿主按 mtime 热读取"，\`WW/README:366\`）。

**\`tapIndex\` 是宿主正式 API，不是 hack**（实测，\`DSH/ws:213-226\`：注释写着"the escape hatch for markup no IndexInjection row expresses"，返回 disposer）。它跑在结构化注入表之后（\`DSH/ws:356-362\`）。DSH 官方更推荐的形态是结构化 row（\`DSH/ws:24-52\`：\`global\`/\`script\`/\`script-src\`/\`script-preload\`/\`style\`/\`html\`），鲸鱼用的是**原始 tap**。

**资源全部走自建路由**：\`WW/host\` 里一共 **22 条 \`kind:'exact'\` 路由，前缀全是 \`/dsh-whale/\`**（实测，行号：2599/2618/2637/2653/2666/2723/2738/2797/2822/2887/2933/2958/2992/3017/3128/3183/3208/3308/3338/3347/3405/3447）。HEAD 版 README 说 23 条（差的那条是 0.3.16 加的 \`/dsh-whale/wait.json\`，本机 0.3.9 没有）。

## A2 前端怎么落进 DOM：**没有 Shadow DOM**，是"约定前缀 + 自贴 <style> + body 直挂"

- **没有 Shadow DOM**（实测：\`grep attachShadow\` / \`shadowRoot\` 在 \`WW/client\` 全仓 **0 命中**）。
- 样式是**自己 \`createElement('style')\` 贴到 \`document.head\`**（实测，\`WW/client:743-750\`）。
- 关键一行是 \`data-plugin\` 标记（实测，\`WW/client:744-748\` 的注释 + 748 行代码）：

  \`\`\`js
  styleEl.setAttribute('data-plugin', 'dsh-whale-widget')
  \`\`\`

  注释解释了为什么：**不带 \`data-plugin\` 的 \`<style>\` 会被 DSH 客户端模块系统 \`claimStyles\` 认领到"当前正在物化的那个插件"名下，那个插件热重载时 \`removeOwnedStyles\` 会把你的样式一起删掉**，于是 20 多个 \`dshwv-*\` 节点从 \`position:fixed\` 掉回文档流、页面被撑到几千像素高（\`WW/client:744-747\`）。**这是"寄生插件"最有价值的一条教训。**
- 根节点 \`<div class="dshwv-root">\` 直挂 body（实测，\`WW/client:784-785\`）。
- **DOM 守护**：因为它把 30 多个节点挂在 \`document.body\` 上，SPA 切路由 / 别的插件整体替换 body 子树时会变成孤儿。所以有 \`dshwBodyAppend()\` 登记器 + \`MutationObserver\` 全量核对（\`WW/client:752-782\` 登记器，\`WW/client:10322-10354\` 守护本体；\`root\` 掉了立即补挂，\`root\` 正常也最多每 1.5s 全量核对一次）。注释里明确点出事故："其余节点会变成'存在但不在文档里'的孤儿 —— 界面看起来恢复了，可一旦点开对应功能就静默失效"（\`WW/client:754-755\`）。
- **页面自检 / 只挂主界面**：脚本会被注入 DSH 的**每一个** index 页面（含市场等 SPA 视图），所以先判"是不是主聊天界面"——特征是三选一的 composer（旧 textarea / 旧 contenteditable / 新 \`[data-composer-input]\`，后者"1515 个前端文件里仅 dsh-client-ui-conversation 命中"，\`WW/client:5-33\`）。**检测不到就一行 DOM 都不碰、不注册任何全局监听**（\`WW/client:53-77\`，无限等 + MutationObserver，v739 去掉了"5 秒死线"）。

## A3 拖动 / 吸附怎么实现

全部是**自己写的一套**，不依赖宿主任何拖拽 API（实测，\`WW/client\`）：

| 环节 | 实现 | 行号 |
|---|---|---|
| 起点 | \`pointerdown\`（捕获期，\`document\` 级），记录 \`origLeft/origTop/w/h/vp\` | \`14710-14721\` |
| 移动 | \`pointermove\` → \`state.left/top = clamp(orig + delta, 0, vp - size)\` → \`express()\` | \`14723-14734\` |
| 点击 vs 拖动 | 位移平方 \`>= CLICK_SQ(=9)\` 才置 \`drag.moved\` | \`226\`（常量）/ \`14727\` |
| 吸附判定 | \`snapZones(cx, cyBox, cyImg, vp)\`：左右看**图像中心 x**、上边看**盒中心 y**、下边看**图像中心 y** | \`12489-12505\` |
| 吸附区可配 | \`snapBounds()\` 支持"按比例（%）"或"按像素"两种模式，\`mode:'off'\` = 全自由 | \`12467-12488\` |
| 边界夹取 | \`clamp()\` + \`saveAnchorPos()\` | \`12460-12463\` |
| 翻转 | 贴左必翻、贴右不翻；自由摆放按"图像中心 vs 翻转线" | \`12506-12520\` |
| 锚点记忆 | \`localStorage\` 的 \`dshw-snap\`（\`SNAP_KEY\`） | \`10424\` / \`10494\` / \`10514\` |
| 拖拽手势期间 | \`root.classList.add('dshwv-dragging')\`，\`setWidgetCursor('grabbing')\` | \`14716-14718\` |

**移动端单独一套**：\`touchstart\` 捕获期接管（\`14872\`），并有"自研触摸接管，不会把页面手势判成滚动"（\`WW/README:40\`）。

## A4 怎么避免挡住宿主交互（这一节是精髓，四层防御）

**第 1 层：容器 \`pointer-events:none\`，只有真控件才 \`auto\`**
（实测，\`WW/client:239\`：\`.dshwv-root{position:fixed;...;pointer-events:none;...;z-index:9999;...}\`）
图像层 \`.dshwv-img\` 也是 \`pointer-events:none\`（\`WW/client:247\`），气泡 \`.dshwv-pop\` 同样 \`pointer-events:none\`（\`WW/client:248\`），**只有泡泡打开时才把 SVG 路径打开**（\`WW/client:253-254\`：\`pointer-events:visiblePainted\`）。菜单按钮 \`.dshwv-menu-btn\` 显式 \`pointer-events:auto\`（\`WW/client:280\`）。

**第 2 层：透明像素命中测试（alpha hit-test）** —— 因为它是个不规则剪影角色，"矩形可点区"会挡住角色方框底下的宿主内容。
（实测，\`WW/client:14620-14682\`）

- 把角色图按 \`object-fit:contain + object-position:right bottom\` 的真实几何画进一张 **610×610 离屏 canvas**（\`14625-14644\`）；
- \`isWhaleHit(e)\` 把鼠标坐标映射到 canvas，翻转时 \`lx = 610 - lx\`，读单像素 **\`data[3] > 10\`**（\`14670-14678\`）；
- **失败也要安全降级**：命中图没加载完 → 返回 \`false\`（不拦页面）；加载失败（404）→ 退回"图像矩形区域"，注释写着"绝不吞掉整页事件"（\`14622\` / \`14657-14668\`）。

**第 3 层：捕获期拦截 + 白名单豁免**
- \`pointerdown\` 捕获期：只有 \`isWhaleHit\` 命中才 \`preventDefault + stopPropagation\`（\`14711-14712\`）。
- \`pointerup\` 也要拦，注释："防止下方元素（如文件行）监听 pointerup 穿透误触发"（\`14735-14738\`）。
- \`click\` **持久注册**（不随 \`endDrag\` 移除），注释解释了原因："click 在 pointerup 之后派发，若在 endDrag 移除会导致 click 穿透到下方元素（如误打开文件）"（\`14741-14744\`）。
- 但**必须豁免挂件自身 UI**，否则"自定义角色是不透明正方形图时，这些元素位于非透明像素上，会被 isWhaleHit 判定命中而吞掉 click"（\`14745-14747\`），豁免清单在 \`14748-14755\`（\`.dshwv-pop/.dshwv-menu/.dshwv-menu-btn/.dshwv-rolelist/.dshwv-cropmask/.dshwv-confirmmask/.dshwv-audiomask/.dshwv-snapmask/.dshwv-bubmask/.dshwv-qedit/.dshwv-usagepanel/.dshwv-usage-mask/.dshwv-resmask/.dshwv-custmenu/.dshwv-custbtn\`）。
- 右键单独处理：不在 \`pointerdown\` 阶段收菜单，交给 \`contextmenu\` toggle（\`14703-14705\`）。

**第 4 层：行为上的退让**
- 菜单按钮可隐藏（隐藏后右键/长按唤出）——\`WW/README:39\`。
- "右缘滚动条避让"（\`WW/README\` 致谢段里提到是 PR #18 引入，\`WW/README:393\`）。
- 提醒层抢层时"退化为居中卡片"而不是硬盖（\`WW/README:61\`）。

## A5 音效怎么播

**不用 \`<audio>\` 元素，走 Web Audio + 预解码 + 同步起播**（实测，\`WW/client:82-115\`）：

- \`dshwvAudio()\` 惰性建 \`AudioContext({latencyHint:'interactive'})\`，\`suspended\` 时 \`resume()\`（\`WW/client:96-106\`）；
- 两级缓存：\`dshwvAudioBuffers\`（url → Promise，防重复下载/解码）与 \`dshwvAudioDecoded\`（url → AudioBuffer，**解码完成后同步可读**）（\`WW/client:107-108\`）；
- 注释把"为什么不用 media element"写得很清楚：**不经过 media element 就不会被 macOS 注册进系统「正在播放」（无 Touch Bar 播放条）**，而且 \`start()\` 能在 \`pointerdown\` 的**同一个任务**里同步调用（\`WW/client:83-94\`）；
- 自动播放策略：挂一次性 \`pointerdown\`/\`keydown\` 解锁监听并自摘（\`WW/client:211-221\`）；
- 音频文件**走自己的路由下发**（\`/dsh-whale/audio-fragment.wav?id=...\`，\`WW/host:3128\`；预置片段表 \`WW/host:50-60\`；随包 wav 路径 \`WW/host:62-70\`）。README 里明确"MIME 必须与文件字节一致"（\`WW/host:49\` 注释）以及"删掉 assets 里的文件会让对应功能静默降级"（\`WW/README:171\`）。

> ⚠️ 有一个**已知的副作用**值得记：装了 IDM/迅雷这类下载管理器时，音效请求会被当成下载任务抢走，每次打开 DSH 弹"下载确认框"，**关掉音效开关也不能消除**（市场页 HEAD README 的常见问题；issue #158）。

## A6 它怎么与宿主隔离

| 隔离维度 | 做法 | 证据 |
|---|---|---|
| **CSS 类名前缀** | 全部 \`dshwv-\`（根 \`.dshwv-root\`） | 实测 \`WW/client:239-741\`（整个 CSS 数组） |
| **CSS 变量前缀** | \`--dshw-\`（\`--dshw-scale\`/\`--dshw-base\`/\`--dshw-vx\`/\`--dshw-vy\`/\`--dshw-u\`） | 实测 \`WW/client:239\`/248/257/266…（\`grep --dshw\` 26 命中） |
| **不要 Shadow DOM** | 靠前缀 + 自贴 style，换取"能读到宿主的 \`font-family:inherit\`"与调试方便 | 读码推断（无显式注释说明"为何不用 shadow"） |
| **样式所有权** | \`<style data-plugin="dsh-whale-widget">\`，防被别的插件的 \`removeOwnedStyles\` 连带删除 | 实测 \`WW/client:744-750\` |
| **z-index** | 根 \`9999\`；小面板列表 \`10001\`；裁剪遮罩 \`20500\`；**模块遮罩可临时抬到 \`30000\`**（用完还原，代码里存了 \`bkModMaskZ\` 备份） | 实测 \`WW/client:239\` / \`303\` / \`321\` / \`332\` / \`344\` / \`1768\` / \`1778\` |
| **全局变量命名** | \`window.__dshWhaleWidget\`（一次性闸门）、\`window.__dshWhaleInit\`、\`window.__dshWhaleRoot\`（供外部定位/调试） | 实测 \`WW/client:2-3\` / \`79-80\` / \`10331\` |
| **localStorage 键** | \`dshw-role\` / \`dshw-snap\` / \`dshw-last-seq\`（HEAD 版还写 \`dshw-pos\`） | 实测 \`WW/client:793\` / \`10424\` / \`15159\` |
| **运行时数据** | 全部写 \`$DSH_HOME\`（默认 \`~/.dsh\`），**不写 node_modules**，注释理由是"node_modules 可能只读或更新时被清掉" | 实测 \`WW/host:20-22\` + 文件表 \`WW/README:128-142\`（\`.dshw-*.json\`、\`whale-roles/\`、\`whale-audio/\`、\`whale-bubble-imgs/\`） |
| **凭据** | 不落配置，只存**凭据名**，真要密钥走 \`ctx.credentials\` | 实测 \`WW/host:72\` / \`2033\` / \`2070\` / \`2848\` |
| **数据保护** | 账本被外部改坏时**拒绝覆盖**（"已停止写入以保护原记录"） | 市场页 HEAD README 常见问题（外部） |

## A7 它对宿主的版本/接口依赖有多深（坏掉会怎样）

**宿主服务依赖只有 4 个**（实测，\`WW/host:585-588\`）：

\`\`\`js
export default {
  name: 'whale-balance-widget',
  inject: ['webServer', 'credentials', 'connection'],
  apply(ctx) { ... }
}
\`\`\`

用到的方法只有 4 个（实测，\`grep ctx.<...>\` 全量统计）：
\`ctx.webServer.register\`(1)、\`ctx.webServer.tapIndex\`(1)、\`ctx.credentials.resolve\`(8)、\`ctx.credentials.set\`(1)、\`ctx.on('session/event'|'session/disposed')\`(2)、\`ctx.get('connection')\`(1)、\`ctx.effect\`(1)。

| 依赖 | 用在哪 | 它坏掉 / 改名会怎样 | 置信度 |
|---|---|---|---|
| \`webServer.register({kind:'exact',path,handler})\` | \`WW/host:613-621\` 统一包装后 22 处 | **全挂**：所有资源 404，前端脚本拿不到 → 界面上什么都不出现 | 实测（API 定义见 \`DSH/ws:171-184\`，重复注册直接 throw） |
| \`webServer.tapIndex(transform)\` | \`WW/host:3458\` | 脚本**根本不会被注入** → 静默不出现（**这正是它自己文档里"右下角什么都没有、控制台也不报错"的成因之一**，见 B 节桌面端一段） | 实测（API 定义见 \`DSH/ws:213-226\`） |
| \`connection.requestRejection(req)\` | \`WW/host:589-611\` 的 \`rejected()\`，\`registerRoute\` 里**每条路由都先过** | 它选择 **fail-open**：注释写"inject 已声明该服务，正常不会走到这里；打一条 warn 便于发现'栅栏实际失效'，而不是静默放行"（\`WW/host:597-603\`）。**坏掉的后果是安全性下降而不是功能失效** | 实测 |
| \`session/event\` + \`turn/end\` + \`assistant/message\` 的事件形状（\`data.usage.inputTokens/cacheReadTokens/outputTokens\`、\`data.turn\`、\`data.message.source.model\`） | \`WW/host:674-723\` | 每轮消耗记账**静默不记**（整段被 \`try/catch\` 包住）；注释里还明确纠正过口径："dsh 保证 reasoningTokens ⊆ outputTokens（见 dsh-token-meter 的校验），所以 reasoning 不能再单独累加 —— 否则输出侧被重复计价（实测偏高约一倍）"（\`WW/host:698-701\`） | 实测 |
| \`ctx.credentials.resolve/set\` | \`WW/host\` 8+1 处 | 余额查不了（只影响需要凭据的功能） | 实测 |
| **前端侧写死的宿主 DOM 契约** | \`[data-composer-input]\` / \`[data-composer-seat]\` / \`[data-composer-card]\`，回退 \`textarea\` / \`[contenteditable=true]\` / \`[role=textbox][aria-multiline=true]\` | **主界面识别失败 → 挂件完全不初始化**。注释实录了这次事故："DSH 0.1.6-alpha.1 起的新版…只认前两种会让挂件在新版 DSH 上完全不初始化，见 issue #123"（\`WW/client:12-15\`） | 实测 |
| **前端侧与 DSH 客户端模块系统共用 \`<style>\` 所有权** | \`data-plugin\` 标记（\`WW/client:744-748\`） | 不标记 → 被别插件热重载连带删除 → 布局崩成文档流 | 实测（注释即证据） |
| **profile 名** | 桌面端读 \`desktop\` profile，而 CLI **硬拒** \`--profile desktop\` | 装错 profile = 一个字都读不到（见 B 节） | 实测（\`DSH/bin:35-37\`） |

**另外还有一道 DSH 侧的"运行时兼容闸"**（实测，跑 \`dsh plugin --help\` 的输出）：启动器会拿插件的 \`peerDependencies\`（\`@deepseek-ai/dsh*\`）跟 \`getDshRuntimeVersion()\` 比，不匹配就 **"it stays installed but profile startup denies it until you grant an exemption for those exact versions"**，要 \`dsh plugin allow-version\` 显式豁免（文档：\`E:\deep seek\DSH Desktop\resources\app\node_modules\@deepseek-ai\dsh-app-boot\README.zh.md:52-56\`）。**本机实测就撞上了**：better-sidebar@0.19.1 / dsh-memory-vault@0.1.5 / dshmarket@1.54.0 都被报"incompatible with dsh 0.2.0-rc.2"。

> better-sidebar 的应对方式是**把版本范围写进 \`peerDependencies\`**（\`SB/pkg:75-94\`，14 个 \`@deepseek-ai/dsh-*\` 全部 \`^0.1.5-rc.1\`），并保留 \`exports\` 子路径与 \`dsh.client.inject\`（\`SB/pkg:42-56\`）。代价就是上面那条——宿主一处升版就全部红灯。**这是"深耦合"的另一面。**

## A8 这套做法能不能搬到"桌宠寄生在别的宿主里"

结论分三档给，别听笼统的"能/不能"。

### ✅ 能直接搬（与宿主无关，纯浏览器技术，占 80%）

| 能力 | 依据 |
|---|---|
| 透明无边框角色 / 气泡 / 面板的整套 CSS 与布局 | \`WW/client:239-741\` 全是纯 CSS |
| **alpha 命中测试**（不规则剪影不挡下面） | \`WW/client:14620-14682\`，只需要一张图 + canvas |
| pointer 拖动 / 夹取 / 吸附 / 翻转 / 锚点记忆 | \`WW/client:12467-12520\` / \`14710-14760\` |
| Web Audio 预解码 + 同步起播 + 手势解锁 | \`WW/client:82-115\` / \`205-221\` |
| \`<style data-plugin>\` 自贴 + 类名前缀隔离 | \`WW/client:743-750\` |
| **DOM 守护 / 重新挂载**（SPA 切路由必备） | \`WW/client:752-782\` / \`10322-10354\` |
| 关掉 \`window.__xxx\` 一次性闸门 + 幂等初始化 | \`WW/client:2-3\` / \`79-80\` |

**搬走需要改的**：\`/dsh-whale/*\` 全部换成宿主自己的资源路由；\`dshwv-\` 前缀换掉；\`dshw-\` 存储键换掉。

### ⚠️ 需要"宿主提供等价物"才能搬（占 15%）

| 需要宿主给的东西 | whale 用的 | 没有的话 |
|---|---|---|
| **一段"每个页面都能注入的 HTML 变换"** | \`webServer.tapIndex\` | 只能改成宿主插件机制（浏览器扩展 content script / Electron preload / 用户脚本），**这是最关键的依赖** |
| **一条静态资源路由** | \`webServer.register\` | 可以把 JS/CSS/图内联进注入的那段 HTML，或让宿主静态目录托管 |
| **一个"会话/回合事件流"** | \`session/event\` | 桌宠就退化成"只会动、不会感知宿主状态" |
| **凭据服务** | \`credentials\` | 自己在页面里存（安全性下降） |
| **一个浏览器信任栅栏** | \`connection.requestRejection\` | 自己写 Host/Origin 校验，否则本机接口可被任意网页读写（\`WW/host:589-611\`） |

> **判断口径**：只要宿主能被"注入一段 \`<script>\`"并且"能对外提供一个 HTTP 路由"，A 这套就能 1:1 搬过去。**minimal 版本甚至不需要路由**——把 \`whale-widget.js\` 内联进注入的 script 标签、把图片转 dataURL 即可，代价是包体变大、前端不能热更新。

### ❌ 搬不过去的（占 5%，是 DSH 专属语义）

- \`cordis.patch.yml\` / \`dsh.profile.bundles\` 的挂载机制（宿主专属）。
- \`ctx.effect\` 的自动释放语义（\`WW/host:3465-3469\`：卸载时逐个调 disposer）。
- \`dsh plugin\` 安装链、市场收录（见 B 节）。

### 🎯 对我们的直接含义

**"桌宠寄生在别的宿主里"最优路径不是照抄它的 Node 半区，而是照抄它的前端半区 + 用目标宿主自己的插件机制挂载。** 具体到我们能碰到的宿主：

| 目标宿主 | 挂载手段 | 可行性 |
|---|---|---|
| **DSH Web / DSH Desktop** | 就是这一套（bundle patch + tapIndex + 自建路由） | 高，但见 A7 的兼容闸与 B 节的 profile 陷阱 |
| **任意浏览器页面** | 用户脚本 / content script，把 \`widget.js\` 内联或走 \`data:\` URL | 中（需要给扩展加资源托管，或全内联） |
| **别的 Electron 应用** | preload 注入 + 主进程起本地 HTTP（或 IPC 取资源） | 中高 |
| **原生桌面宿主（非 Web）** | ❌ 这套完全不适用，那是 Qt/WPF 的活（= 我们现在的绿色版路线） | 低 |

---

# B. 推广与下载方式

## B1 它怎么写简介（description 的两套写法）

**npm \`description\`（长句罗列，面向搜索）** —— 实测，\`WW/pkg:4\`，一行 100+ 字，把"余额/今日已用/峰谷定价/泡泡/音效/自定义角色/吸附"全塞进去。
**keywords 只有 5 个**：\`dsh / dsh-plugin / deepseek-harness / balance / widget\`（\`WW/pkg:5-11\`）。

**市场条目 description 是另一套**（中英双语、更短、更"产品"）—— 实测，registry 里 \`dsh-whale-widget\` 条目：

\`\`\`json
"description": {
  "zh": "右下角常驻的小鲸鱼挂件：余额、今日已用与每轮对话消耗（含峰谷价），余额预警与今日预算的泡泡内容都可编辑；…内置 30+ 厂商模板…数据全在本机，无遥测。",
  "en": "A fixed-corner whale widget for the DSH web GUI — ... Local-only, no telemetry."
}
\`\`\`

**注意收尾那句 \`Local-only, no telemetry.\`（本地、无遥测）**——对"要读用户 API key 的插件"来说这是**必须主动声明的卖点**，不然就是劝退项。

来源：\`https://awesome-dsh-plugin.com/plugins.json\`（实测，用 \`Invoke-RestMethod\` 拉全量 4489 条后筛 \`name -eq 'dsh-whale-widget'\`）。

## B2 README 结构与"一键安装命令"的给法（0.3.9 本地版）

\`WW/README\` 401 行的骨架（实测）：

| 行 | 章节 | 作用 |
|---|---|---|
| 1-5 | 标题 + **顶部大图** + 一句话定位 + "dsh plugin 一键安装，无需任何会话令牌" | 3 秒说服 |
| 7-20 | **「两条分支怎么选」表格 + 三条 ⚠️** | 先把"装错了"这条路堵死 |
| 22-101 | 特性（记账显示 / 交互 / 泡泡系统 / 提醒 / 音效角色图片 / 自定义 API / Codex 模式） | 能力清单，大量 emoji + 加粗 |
| 103-142 | 目录结构 + **运行时数据文件表** | 让用户知道"我的数据在哪、会不会被清" |
| **144-214** | **安装：方式 A（本地资源包）/ B（GitHub）/ C（本地仓库）/ D（npm）** | 四条路并列，每条都配 PowerShell 代码块 |
| 216-268 | **「给 AI 的安装说明（直接复制给 AI 助手）」** | 一大段可整段复制的 prompt，把"解压到固定目录""别多套一层""先 remove 再 add""装完重启"全写进去 |
| 270-291 | 凭据（装完必读） | |
| 293-297 | 卸载（一条命令） | |
| 299-326 | 从旧手动安装升级（含"删掉这段旧补丁"的精确 diff） | |
| 328-351 | 验证（curl 清单 + **"401/403 是预期行为"的说明**） | |
| 353-367 | 常见问题（11 条，每条"现象 → 怎么办"） | |
| 369-378 | 定价表（表格） | |
| 380-384 | 开发与维护（改前端 Ctrl+F5 / 改宿主重启） | |
| 386-395 | 致谢（逐 PR 列贡献者与贡献内容） | |
| 397-401 | 许可证 + **素材不在 MIT 范围内**的醒目声明 | |

**一键安装命令的给法（实测，\`WW/README:174-214\` + 市场页）：**

- **首选 npm 名**：\`dsh plugin --profile web add dsh-whale-widget\`（\`WW/README:213\`）
- **备选 GitHub**：\`dsh plugin --profile web add github:MeteorNOX/DeepSeek-Balance-Whale-Widget\`（\`WW/README:179\`）
- **本地资源包**：\`dsh plugin --profile web add link:<绝对路径>\`（\`WW/README:164\`），并给了 \`file:\` 的取舍说明（\`WW/README:170\`）
- ⚠️ **它自己反复强调两条路二选一、不能混装**（\`WW/README:18\`）。

**市场页给出的安装块**（实测，\`https://awesome-dsh-plugin.com/p/MeteorNOX/DeepSeek-Balance-Whale-Widget/\`）更精炼，而且是**两条并列**：

\`\`\`
# from npm (prebuilt)
dsh plugin --profile web add dsh-whale-widget
# from GitHub (first run asks for allowBuilds approval — follow the hint, retry)
dsh plugin --profile web add github:MeteorNOX/DeepSeek-Balance-Whale-Widget
\`\`\`

紧跟一段**安全告示**（原文）："Any plugin you install runs third-party code with your own permissions — it can read your files, use your credentials, and reach the network, and tool approvals don't sandbox it. … only install sources you trust, and pin a commit (\`github:owner/repo#sha\`)."

## B3 截图 / GIF：有，但用法很克制

- 仓库里确实有展示素材：\`assets/DSH2.png\`（809921 B，README 顶部展示图）、\`assets/rua.gif\` / \`bubble-petpet.gif\`（94643 B）、\`bubble-money1.gif\`（2704365 B）—— 实测文件清单。
- **但 README 正文只在第 3 行用了一张 PNG**（\`WW/README:3\`：\`![DSH 小鲸鱼记账挂件](assets/DSH2.png)\`）；那些 GIF 是**功能素材**（泡泡图库），不是展示图。
- **npm 包的 \`files\` 里带上了 \`assets\`**（\`WW/pkg:14-20\`：\`["lib","assets","cordis.patch.yml","README.md","PROVENANCE.md"]\`），所以包页也能显示出图。
- 市场页用的是**直接 hotlink 仓库 HEAD 的图**（实测：市场页 HTML 里 \`<img src="https://raw.githubusercontent.com/MeteorNOX/DeepSeek-Balance-Whale-Widget/HEAD/assets/DSH2.png" ...>\`）—— 意味着**改仓库里的图 = 改市场页的图**。
- 还有一条**元数据卫生**的做法值得学：自 0.3.1 起随包 PNG **一律剥离 \`eXIf\`/\`iTXt\`/\`tEXt\`/\`zTXt\` 块**（实测，\`PROVENANCE.md:26-31\`），理由之一是内嵌过设计工具的账号 id。

## B4 版本更新怎么表达

**四种表达同时存在**（实测）：

1. **npm 版本线密集**：28 个版本，2026-08-20 → 2026-10-02（实测 \`registry.npmjs.org\` 的 \`time\` 字段）；0.3.9 之后到 0.3.18 是 **9 个版本 / 13 天**。
2. **README 里"当前状态"用内部构建号**：\`v679 起新增模型会自动跟随模板\`（\`WW/README:291\`）、\`v743/v745\`（\`WW/client:752\` / \`82\`）—— **只出现在注释与 README 的边角**，npm 版本号才是对外口径。
3. **RELEASE 自动化**：push 触发自动发布 npm、用 Trusted Publishing（OIDC）—— 来自 \`WW/README:392\` 的致谢段（PR #6/#7 由 \`@under-the-ocean\` 提交）；"发布时自动建 Release 并生成 PR changelog"来自同段 PR #46（\`WW/README:394\`）。
4. **升级说明写在 FAQ 里**：如"改了前端代码不生效 → 硬刷新；改了宿主必须重启 \`dsh web\`"（\`WW/README:366\`）；"已经是 \`github:\` 装的，要换 npm 名请先 remove"（\`WW/README:18\`）。

**下载量（实测，\`api.npmjs.org\`）**：

| 包 | last-week | last-month |
|---|---|---|
| \`dsh-whale-widget\` | **46935** | 146796 |
| \`dsh-better-sidebar\` | 38068 | — |
| \`dshmarket\`（市场本体） | 112438 | — |

星标/下载（市场页 + registry 条目实测）：★ **4363**、30 天下载 **138017**、收录日期 **2026-08-23**。

## B5 市场条目与收录标准

**市场是什么**（实测）：\`dshmarket\` v1.54.0，包说明就写着"DSH 可视化插件市场：逛一逛，点一下，装好"（\`C:\Users\29179\.dsh\profiles\desktop\node_modules\dshmarket\package.json:3\`）。

**数据从哪来**（实测，\`MKT/reg:120-136\` + \`MKT/reg:27-42\` + \`dshmarket/package.json:33\`）：

- 目录源是 **\`https://awesome-dsh-plugin.com/plugins.json\`**（每个请求都重新拉，15s 超时，2 次重试，**没有任何 cache/snapshot 兜底**——注释解释得很硬："For a catalog, stale is not a degraded answer, it is a wrong one"）。
- 中文区会走 mirror；npm 包里还有一条 \`catalogFromPackage()\` 的备用路径（\`MKT/npmcat:82-111\`，从 npm 包的 tarball 里解 \`package/plugins.json\`）。
- 环境变量 \`DSHM_REGISTRY_URL\` 只做测试覆盖，不削弱安装路由的 registry 校验（\`MKT/reg:31-42\`）。

**条目字段结构**（实测，直接从 \`plugins.json\` 拿到的 whale 条目）：

\`\`\`json
{
  "name": "DeepSeek-Balance-Whale-Widget", "owner": "MeteorNOX",
  "url": "https://github.com/MeteorNOX/DeepSeek-Balance-Whale-Widget",
  "page": "https://awesome-dsh-plugin.com/p/MeteorNOX/DeepSeek-Balance-Whale-Widget/",
  "category": "ui",
  "description": { "en": "...", "zh": "..." },
  "npm": "dsh-whale-widget", "version": "0.3.18",
  "stars": 4363, "downloads": 138017,
  "downloadsStart": "2026-09-10", "downloadsEnd": "2026-10-09", "downloadsCheckedAt": "2026-10-10",
  "capabilities": ["fs-write","fs-read","network","credentials","env"],
  "capabilityRedLines": ["reads credentials/secrets AND has network access",
                         "uses literal IP 100.100.100.200 for network access"],
  "capabilityCheckedAt": "2026-10-10T16:53:51.331Z",
  "install": "dsh plugin --profile web add dsh-whale-widget",
  "added": "2026-08-23"
}
\`\`\`

**目录规模与分类**（实测）：4489 条，23 个分类（\`ui\` 781 / \`tools\` 585 / \`dev\` 321 / … / \`fun\` 137）；**4489 条全部带 \`install\` 命令**；**494 条带 \`capabilityRedLines\` 红线条目，3995 条干净**。

**收录标准 / gate**（**外部资料，非官方文档，我无法就地复现**）：

- 权威入口是 \`awesome-dsh-plugin/awesome-dsh-plugin\` 仓库的 \`contributing.md#how-submissions-are-reviewed--收录如何评审\`（web_search 命中，但 \`github.com\` / \`raw.githubusercontent.com\` 在本机被 web_fetch 以"resolves to a non-public IP"拒绝，**我没能读到原文**）。
- **第三方教程给出了可操作的三条**（实测抓取 \`https://zoahdev.github.io/dsh-tutorials/zh-26-submission-gate.html\`）：
  1. **必须声明 \`dsh.bundle\` manifest**，否则直接拒绝；
  2. 仓库年龄 ≥ 1 天（按 \`created_at\`，不是 PR 时间）；
  3. 仓库 commit 数 ≥ **10**。
  三条都过才绿；失败是 \`mergeStateStatus: UNSTABLE\`（可合并但检查失败）。此外还有一条内容检查 \`check (PR check)\`，条目格式/内容问题要按它的输出修。
- 教程还提到"收录后更新 README 徽章，并在官方 Discussions 展示帖同步"。
- 另一份候选资料：\`dshworks/awesome-dsh-plugins\` 的 \`CONTRIBUTING.md\`（web_search 命中，**未读到原文**）。
- **没找到**：官方（DeepSeek / awesome-dsh-plugin 站点内）的"收录标准"页面——站内 \`/about\`、\`/submit\`、\`/docs\`、\`/criteria\` 我都试过，除 \`/docs/\` 是分类页外**全 404**（实测）。首页确实有 "Submit ↗ GitHub ↗ RSS" 三个链接指向外部。

## B6 用户从"看到"到"装上"一共几步

**路径一：从 npm（最快，2 步）**
1. 看到市场页/README → 复制 \`dsh plugin --profile web add dsh-whale-widget\`
2. 粘进终端回车 → 重启 \`dsh web\` → 浏览器 F5

**路径二：从 GitHub（3 步，且第一次可能失败一次）**
1. 复制 \`dsh plugin --profile web add github:owner/repo\`
2. 若 pnpm 拦构建脚本 → 报 \`ERR_PNPM_GIT_DEP_PREPARE_NOT_ALLOWED\` / \`ERR_PNPM_IGNORED_BUILDS\`，按提示把 key 加进 profile 的 \`pnpm-workspace.yaml\` 的 \`allowBuilds\`（\`WW/README:255-256\`）
3. 重跑命令 → 重启 → F5

**路径三：从本地资源包（4 步）**
1. 下载 zip → 解压到**固定目录**（不能是临时/下载目录，之后不能移动）
2. \`Test-Path\` 三件套自检（\`WW/README:156-158\`）
3. 若装过同名先 \`remove\`
4. \`add link:<绝对路径>\` → 重启 → F5

**路径四（**桌面端**，即我们的用户）**：**1 步，但方式完全不同**（实测 HEAD README 原文 + \`DSH/bin:35-37\`）：

> "官方桌面客户端用的是 **desktop profile**（\`%USERPROFILE%\.dsh\profiles\desktop\`），而 \`dsh plugin\` 命令行**按设计拒绝**碰它：
> \`error: profile "desktop" is managed exclusively by the Electron application\`
> …桌面端的正确装法：**让桌面端里的 DSH 自己装**。在桌面客户端的会话里直接说一句就够了（例如「把 dsh-whale-widget 装上」）—— 它会调用内置的 \`plugin_manager\` 工具，而那个工具的**作用域就是当前 profile**。"

**这一条我用本机代码交叉验证过（实测）**：
- \`DSH/bin:35-37\`：

  \`\`\`js
  function rejectElectronProfile(program, profile) {
    if (profile.toLowerCase() === "desktop") program.error("error: profile \"desktop\" is managed exclusively by the Electron application");
  }
  \`\`\`
- 本机 \`dsh\` 就是桌面端自己的 shim（实测：\`Get-Command dsh\` → \`C:\Users\29179\AppData\Roaming\DSH Desktop\host-commands\desktop\generations\…\bin\dsh.cmd\`），里面写着 \`set "DSH_DESKTOP_DEFAULT_PROFILE=desktop"\`。

**生效时机的坑（HEAD README + issue #162）**：新装通常热生效（工具返回 \`"application":"applied"\`）；**换版本要重启客户端**（\`restart-required\`）；但"新装也可能要重开一次客户端才出现"。

**桌面端的两条自检**（HEAD README 原文）：
- 宿主半区：\`%USERPROFILE%\.dsh\.dshw-turn.json\` 存在且 \`seq\` 随对话递增；
- 客户端半区：\`%APPDATA%\@deepseek-ai\dsh-desktop\Local Storage\leveldb\` 里出现 \`dshw-pos\` / \`dshw-last-seq\`（"只有挂件前端会写"）。

---

# C. 落到我们身上：「绿色版下载」+「插件版下载」并列的 README 结构

> **本节全部是建议，我没有改任何文件**（唯一写入是这份报告本身）。

## C0 先摆清我们现在的家底

| 事实 | 证据 |
|---|---|
| 绿色版 zip 就在仓库根、**113,534,667 B ≈ 108.3 MiB** | 实测 \`E:\deep seek\desktop-pet\daifeiyu-desktop-pet.zip\` |
| 另一个归档 zip **112,784,494 B ≈ 107.6 MiB** | 实测 \`大肥鱼桌宠_绿色版_v142_归档.zip\` |
| 绿色版目录是**免安装成品**：\`pythonw.exe\` + \`python310.dll\` + \`Lib/\` + 全部 \`pet_*.py\` + \`启动桌宠.vbs\` | 实测 \`大肥鱼桌宠_绿色版\\\` 清单；**里面还有用户数据**（\`config.json\` / \`ledger.json\` / \`roles.json\` / \`lines.json\`）——按硬性约束④，谁都不许动 |
| 现有 README 的"下载/安装"其实是**两小节**：\`## 🚀 快速开始\`（\`R/README:41-54\`）+ \`## 🛡️ 杀软误报说明\`（\`R/README:151-156\`）+ \`## 📦 打包\`（\`R/README:217-223\`） | 实测 |
| 现在**只有"两种方式"**（免安装绿色版 / 源码运行），**没有"插件版"这个概念** | 实测 \`R/README:43-54\` |
| 我们**已经借过**小鲸鱼的东西，README 里明说了 | 实测 \`R/README:185-186\`；\`R/README:25-26\`；\`docs/阶段计划.md:6\` |
| 本仓库 CI **只跑测试**，没有发布/Release 自动化 | 实测 \`.github/workflows/ci.yml:1-40\`（只有 \`Pytest\` + \`Offscreen smoke\`） |
| 中英双 README 都在，且英文版同样有 \`## 🚀 Quick Start\` | 实测 \`README.en.md:45\` / \`:49\` |

## C1 建议的 README 章节顺序（改动后）

原则：**"下载"必须在第一屏可点**；**"绿色版 vs 插件版"要在同一个表里并排**，不能一个在开头一个在结尾。

\`\`\`
1. # 标题 + 一句话定位 + 中英切换                     （保持 R/README:1-14）
2. ## 📢 版本公告                                     （保持 R/README:6-10，见 C3-①）
3. ## ⬇️ 下载                                        ← 新章节，把三张表并排
     3.1 一张"选哪个"决策表（3 行：绿色版 / 插件版 / 源码）
     3.2 绿色版下载条目（含大小、包含什么、适合谁、怎么用、校验）
     3.3 插件版下载条目（含大小、包含什么、适合谁、怎么用、需要什么宿主版本）
     3.4 源码运行（保持 R/README:49-54 原样，降级为第三选择）
4. ## ✨ 特色                                        （保持 R/README:16-39）
5. ## 🎮 玩法 / 🛠️ 平台与数据说明 / 🧠 AI 对话与记账 …（全部保持原序）
6. ## 🎨 角色画廊 / 💬 社区 …                          （保持）
7. ## 🛡️ 杀软误报说明                                 （保持 R/README:151-156，见 C3-②）
8. ## 📁 目录结构                                      （保持 R/README:158-183，见 C3-③）
9. ## 📦 打包                                          （保持 R/README:217-223，追加插件版打包）
10. ## 📜 License
\`\`\`

**为什么把「下载」提到第 3 位而不是第 1 位**：现在的第 1-2 位是"人设 + 版本公告"，社区项目靠这个拉人；下载放第 3 位仍在首屏内（README 折叠线之上通常能到 40-60 行）。

## C2 每个下载条目必须写什么（逐字段说明）

### 决策表（放在 3.1，3 行 5 列）

| 你要什么 | 选哪个 | 要装 Python 吗 | 要装 DSH 吗 | 体积 |
|---|---|---|---|---|
| **桌面上一只独立的鱼**（不依赖任何别的软件） | **绿色版** | ❌ 不用 | ❌ 不用 | ≈108 MB |
| **DSH 界面里的一只鱼**（在 DSH 窗口里常驻） | **插件版** | ❌ 不用 | ✅ **要**（Web 或桌面端） | 待定，见 C4 |
| 想改代码 / 想跑测试 | 源码运行 | ✅ Python 3.10 | ❌ | 仓库大小 |

### 绿色版条目（3.2）—— 逐字段

| 字段 | 建议写法 | 依据 |
|---|---|---|
| 名称 + 直达链接 | \`[daifeiyu-desktop-pet.zip](https://github.com/xiyan1314/daifeiyu-desktop-pet/releases)\` | 沿用 \`R/README:45\` 的 Releases 直链 |
| **大小** | 写**实测值** \`≈108 MB\`，并注明"解压后约 XXX MB"（需要实测解压后体积，我**没测**） | 实测 zip = 113,534,667 B |
| **包含什么** | 明确列：\`pythonw.exe\` + \`python310.dll\` + \`Lib/\` + \`pet_*.py\` + \`assets/\` + \`启动桌宠.vbs\`；**明确说"不含易被杀软误报的自解压 exe"** | 实测绿色版目录清单 + 现行文案 \`R/README:47\` |
| **适合谁** | "不想装 Python、只想双击就用的人；Windows 10/11" | \`R/README:66\` |
| **怎么用（3 步内）** | 1 解压到任意文件夹（**别放 C:\\Program Files 之类只读目录**）→ 2 双击 \`启动桌宠.vbs\` → 3 右键设置 API Key | 沿用 \`R/README:45\`，补上"只读目录会回退 %APPDATA%"（\`R/README:68\`） |
| **升级怎么迁移** | 指到 \`R/README:112\`（拷 config.json / ledger*.json / roles/ / lines.json 等即迁移） | 实测该行已写 |
| **卸载 / 不留痕** | 指到"清除 API Key"（\`R/README:80\`） | 实测 |

### 插件版条目（3.3）—— 逐字段

| 字段 | 建议写法 | 依据 |
|---|---|---|
| **前置条件（最重要，必须前置）** | "需要先有 DSH（DeepSeek Harness）"。**并且必须按"Web 还是桌面端"给两套装法** | \`DSH/bin:35-37\` 实测：桌面端 profile 被 CLI 硬拒 |
| **桌面端装法** | "**在 DSH 桌面端的会话里说一句「把大肥鱼插件装上」**，让 DSH 自己调 \`plugin_manager\` 装进当前 profile" | HEAD README 原文 + \`dsh\` shim 里的 \`DSH_DESKTOP_DEFAULT_PROFILE=desktop\`（实测） |
| **Web 装法** | \`dsh plugin --profile web add <包名>\`（或 \`github:<owner>/<repo>\` / \`link:<绝对路径>\`） | \`WW/README:179\` / \`164\` / \`213\`；\`DSH/bin.js:48\` 的示例写法 |
| **⚠️ 反面警告** | 明确写"**不要**用 \`--profile desktop\`，CLI 会直接报错" | 实测错误文案：\`profile "desktop" is managed exclusively by the Electron application\` |
| **大小** | npm 包的话写 \`unpackedSize\`（可实测：\`registry.npmjs.org\` 的 \`dist.unpackedSize\`）；whale 是 5,978,436 B ≈ 5.7 MiB | 实测 |
| **包含什么** | \`package.json\` + \`cordis.patch.yml\` + \`lib/\` + \`assets/\`（写明**哪几个资源是必需的**，缺了会静默降级） | \`WW/README:148\` / \`171\` |
| **适合谁** | "已经天天开 DSH、想让鱼待在 DSH 窗口里的人" | |
| **怎么用** | 装 → 生效（热生效 or 重启）→ 出现位置（写清是"DSH 窗口右下角"还是"跟着窗口"） | \`WW/README:367\` / HEAD README 的 \`applied\`/\`restart-required\` |
| **装完怎么自检** | 给**一条命令级**的证据（whale 给的是"某文件存在且 seq 递增"+"localStorage 键出现"） | HEAD README 原文 |
| **卸载** | 一条 \`dsh plugin --profile web remove <包名>\`（Web）；桌面端说"让 DSH 自己卸" | \`WW/README:295-297\` |
| **数据存哪** | 明确写插件版的数据文件与绿色版**是不是同一份**（这决定用户能不能两边都装、数据会不会打架） | **没找到**（我们的插件版还不存在） |
| **和绿色版的关系** | 必须回答"两个都装会怎样"——同一时间是不是只能跑一个 | 类比 \`R/README:10\` 已经处理过"怀旧版与新版互不干扰（同一时间只跑一个）" |

### 每个条目统一的"三件套"（从 whale 学到的）

1. **一条命令 / 一次双击** —— 不要让人读三段才动手。
2. **一个自检动作** —— "装完跑这个，看到 X 就对了"（whale：\`curl\` 返回 401/403 也算对，\`WW/README:349-351\`）。
3. **一句"装错了会怎样"** —— whale 用 ⚠️ 把"装错 profile = 右下角什么都没有、控制台也不报错"写在安装节最前面。**对我们是"装错 profile / 装错版本（没升 DSH）"两条。**

## C3 现有 README「下载/安装」段的具体改动对照（**只给对照，不落盘**）

### C3-① 版本公告段（\`R/README:6-10\`）

**改动前**（\`R/README:6-10\`，原样）：
\`\`\`markdown
## 📢 版本公告
> 不喜欢新版本？可以下载怀旧版：
> [v1.4.2（行走降速 + 跟随伴飞）](https://github.com/xiyan1314/daifeiyu-desktop-pet/releases/tag/v1.4.2) ·
> [v1.4.1（跟随/散步降速）](https://github.com/xiyan1314/daifeiyu-desktop-pet/releases/tag/v1.4.1)
> 解压后双击「启动桌宠.vbs」即可，与新版互不干扰（同一时间只跑一个）。
\`\`\`

**改动后**（建议）：
\`\`\`markdown
## 📢 版本公告
> 本版同时提供**两种形态**，按你的场景选一个（下面「⬇️ 下载」有完整对照）：
> - 🖥️ **绿色版**：独立桌面宠物，解压双击就能跑，**不需要 DSH**。
> - 🧩 **插件版**：装进 DeepSeek Harness（DSH），在 DSH 窗口里常驻。
>
> 不喜欢新版本？可以下载怀旧版：
> [v1.4.2（行走降速 + 跟随伴飞）](…/releases/tag/v1.4.2) ·
> [v1.4.1（跟随/散步降速）](…/releases/tag/v1.4.1)
> 解压后双击「启动桌宠.vbs」即可，与新版互不干扰（同一时间只跑一个）。
\`\`\`

**改动理由**：现在 README 从头到尾没有"插件版"三个字，用户翻到底都不会知道有第二个形态。**这是"同时能看到两种下载"的最低成本实现——一句话 + 两个链接锚点。**

### C3-② 快速开始 → 拆成「⬇️ 下载」章节（\`R/README:41-54\`）

**改动前**（\`R/README:41-54\`，原样）：
\`\`\`markdown
## 🚀 快速开始

**方式一：免安装绿色版（推荐，无需 Python）**

到 [Releases](https://github.com/xiyan1314/daifeiyu-desktop-pet/releases) 下载附件 \`daifeiyu-desktop-pet.zip\`（**解压到任意文件夹**，包内直接是程序文件）→ 双击 \`启动桌宠.vbs\`。
（v2.2.5：文案与产物对齐——zip 内没有外层目录，此前 README 写成"解压后是 大肥鱼桌宠_绿色版 文件夹"与实际不符。）
（绿色版使用微软签名的 pythonw.exe + 完整运行库，不含易被杀软误报的自解压 exe。）

**方式二：源码运行**

\`\`\`bash
pip install -r requirements.txt
python main.py        # 规范入口（桌宠.py 为兼容壳）；或双击 启动桌宠.bat
\`\`\`
\`\`\`

**改动后**（建议）：
\`\`\`markdown
## ⬇️ 下载

先选一个（两个**互不影响**，但同一时间建议只跑一个）：

| 你想要 | 选这个 | 需要 Python | 需要 DSH | 体积 |
|---|---|---|---|---|
| 桌面上多一只**独立**的鱼 | 🖥️ **绿色版** | 不用 | 不用 | ≈108 MB |
| DSH 界面里多一只**常驻**的鱼 | 🧩 **插件版** | 不用 | 要（Web 或桌面端） | ≈<实测> MB |
| 想改代码 / 跑测试 | 📦 源码运行 | Python 3.10 | 不用 | 仓库 |

---

### 🖥️ 绿色版（独立桌面宠物 · 推荐给"只想双击就用"的人）

**下载**：[daifeiyu-desktop-pet.zip](https://github.com/xiyan1314/daifeiyu-desktop-pet/releases)（**≈108 MB**）

| 项目 | 内容 |
|---|---|
| **包含什么** | \`pythonw.exe\` + 完整 Python 3.10 运行库（\`Lib/\`、\`python310.dll\`）+ 全部 \`pet_*.py\` + \`assets/\`（帧图 / 音效）+ \`启动桌宠.vbs\`。**不含易被杀软误报的自解压 exe** |
| **适合谁** | Windows 10/11；不想装 Python、不想管依赖的人 |
| **怎么用** | ① 解压到任意文件夹（**别放只读目录**）→ ② 双击 \`启动桌宠.vbs\` → ③ 右键 →「设置DeepSeek API Key」 |
| **数据在哪** | 程序目录；只读时自动回退 \`%APPDATA%\\大肥鱼桌宠\` |
| **升级怎么迁移** | 把 \`config.json\` / \`ledger*.json\` / \`roles/ + roles.json\` / \`lines.json\` 拷过去即可 |
| **卸载** | 删文件夹；分享前先右键 →「清除DeepSeek API Key」 |

（v2.2.5 口径：zip 内没有外层目录，解压出来直接是程序文件。）

---

### 🧩 插件版（寄生在 DeepSeek Harness 里）

> ⚠️ **先确认你用的是哪种 DSH**，两种装法**完全不同**，装错了表现是"界面里什么都没有、控制台也不报错"。

**A. DSH 桌面端（Electron 客户端）** —— 命令行**装不了**（\`dsh plugin --profile desktop\` 会被直接拒绝：\`profile "desktop" is managed exclusively by the Electron application\`）。

正确做法：**在 DSH 桌面端的会话里直接说一句「把大肥鱼插件装上」**，让 DSH 自己用内置插件管理器装进当前 profile。

**B. DSH Web（\`dsh web\`）**
\`\`\`powershell
dsh plugin --profile web add <插件包名>
# 或从仓库装（跟随 main，不跟随已发布版本）
dsh plugin --profile web add github:xiyan1314/daifeiyu-desktop-pet
\`\`\`

| 项目 | 内容 |
|---|---|
| **包含什么** | \`package.json\`（含 \`dsh.bundle.patch\`）+ \`cordis.patch.yml\` + \`lib/\` + \`assets/\`。**\`assets/\` 缺文件会让对应功能静默降级（没图 / 没声）** |
| **适合谁** | 已经天天开 DSH、想让鱼待在 DSH 窗口里的人 |
| **装完怎么自检** | <待定：给一条命令或一个界面现象> |
| **生效方式** | 新装通常热生效；**换版本要重启 DSH**；没看到就重启一次再刷新 |
| **卸载** | \`dsh plugin --profile web remove <插件包名>\` |
| **和绿色版的关系** | <待定：两个都装是否冲突、数据是否共用> |

---

### 📦 源码运行

\`\`\`bash
pip install -r requirements.txt
python main.py        # 规范入口（桌宠.py 为兼容壳）；或双击 启动桌宠.bat
\`\`\`
\`\`\`

**改动理由（逐条）**：
1. 现在"方式一/方式二"是**并列但语义不同**的两件事（分发形态 vs 开发方式）；加了插件版就是三件，**必须用表格**才能一眼选对。
2. 绿色版条目缺了 whale 有的四样：**大小**、**包含什么**、**适合谁**、**自检/数据在哪**。补上后"下载页"才自洽。
3. 桌面端那一句是**必须写的**——它是实测的硬错误，不是"可能有问题"。

### C3-③ 杀软误报段（\`R/README:151-156\`）

**改动前**（\`R/README:151-156\`，节选关键句）：
> "…因此本项目**默认分发绿色版**（pythonw.exe + 源码），结构上不存在被杀软误删的自解压 exe。若仍被拦截：加入信任 / 白名单，或直接用方式二源码运行。"

**改动后**（建议只改最后那句的回指）：
> "…若仍被拦截：加入信任 / 白名单，或直接用上面「📦 源码运行」。"

外加**一段插件版的对应说明**：
> "插件版不经过 Windows 杀软的可执行文件启发式（它是被 DSH 加载的 JS + 资源），但**它会以你的权限运行**——这一点 DSH 的市场页也会明确提示（\`Any plugin you install runs third-party code with your own permissions\`）。只从你信任的来源装。"

**改动理由**：原文的"方式二"是旧编号，加了章节会指错；而且插件版有**另一类**风险（不是杀软，是权限），值得单独一句。

### C3-④ 目录结构 / 素材说明段（\`R/README:158-186\`）

**改动前**（\`R/README:185-186\`，原样）：
\`\`\`markdown
> 素材说明：petpet/money 动图与 task-end-a/exp-orb 音效概念借自 MIT 开源的
> dsh-whale-widget 插件（DeepSeek-Balance-Whale-Widget 系列），帧图由 GIF 转换生成。
\`\`\`

**改动后**（建议在同一个 blockquote 里补 2 行）：
\`\`\`markdown
> 素材说明：petpet/money 动图与 task-end-a/exp-orb 音效概念借自 MIT 开源的
> dsh-whale-widget 插件（DeepSeek-Balance-Whale-Widget 系列），帧图由 GIF 转换生成。
> 插件版的挂载方式（bundle patch + 自建路由 + 前端注入）同样参考该插件的公开实现；
> 其 \`assets/\` 下的美术素材**不在 MIT 范围内**，我们没有复制它的图片与音频。
\`\`\`

**改动理由**：whale 的 \`PROVENANCE.md:9-10\` 明确划了"代码 MIT / assets 非 MIT"的界线。我们要么不碰它的 assets，要么照它那样如实标注——**先声明"没复制"是最省事且最诚实的做法**。

### C3-⑤ 打包段（\`R/README:217-223\`）

**改动前**（\`R/README:219-223\`）：
\`\`\`bash
pip install -r requirements.txt        # 含 PyInstaller>=6.0,<7
python -m PyInstaller --noconfirm --clean 大肥鱼桌宠.spec
# 产物 dist\\大肥鱼桌宠\\（可选 exe 版；对外分享推荐绿色版）
\`\`\`

**改动后**（建议追加 3 行）：
\`\`\`bash
# 插件版打包（用 DSH 自己的安装命令把本目录装成 bundle 插件）：
dsh plugin --profile web add link:.
# 或发布到 npm 后：dsh plugin --profile web add <包名>
\`\`\`

### C3-⑥ 英文版同步（\`README.en.md:45-49\`）

**改动前**（\`README.en.md:45-49\`）：只有一个 \`## 🚀 Quick Start\`，正文是 "Download \`daifeiyu-desktop-pet.zip\` from [Releases](../../releases) → extract → double-click \`启动桌宠.vbs\`."

**改动后**：与 C3-② 同构，标题改 \`## ⬇️ Download\`，加同一张 3 行决策表 + 两个 \`###\` 子节。**注意**：\`README.en.md:49\` 用的是相对链接 \`../../releases\`，而中文版 \`R/README:45\` 用的是绝对 GitHub URL——**两处链接口径不统一**，顺手对齐。

## C4 我没做到的 / 需要别人补的（如实报告）

1. **插件版目前不存在**，所以 C2 里所有"待定"字段（包大小、包含什么、自检动作、与绿色版是否冲突、数据是否共用）**我无法给实测值**——这些必须等插件版真的做出来。
2. **解压后体积我没测**（只报了 zip 的 108.3 MiB）。要写进 README 得实测一次。
3. **仓库里那个 zip 是 2026/10/10 23:54 的**，是否就是 v2.4.3 的发布产物我**没验证**（\`_check_release.py\` 有逐字节比对门，那是发布门的活）。
4. **awesome-dsh-plugin 的官方收录原文我没读到**（\`github.com\` / \`raw.githubusercontent.com\` 被 web_fetch 以 "resolves to a non-public IP address" 拒绝）。B5 的三条 gate 来自**第三方教程**，属于"外部资料、未独立复现"。
5. **我没有观察挂件的运行时行为**——本报告 A 节的所有结论都来自**静态读码 + 注释**。注释里写的"实测 1515 个前端文件里仅 dsh-client-ui-conversation 命中""实测偏高约一倍"等，是**插件作者的实测**，不是我的。
6. **npm 包页 \`npmjs.com/package/dsh-whale-widget\` 我没直接打开**（registry JSON 与市场页已覆盖同样的元数据）。所以"包页的视觉排版"我只能推断（\`files\` 含 README.md + assets，故会有图有文）。
7. **\`dsh plugin --help\` 实际转发给了 pnpm**（实测输出就是 pnpm 的 help），所以 DSH 自己的 \`plugin\` 子命令帮助文本我**没拿到**；A7 里关于子命令的结论来自 \`DSH/bin.js\` 注释（\`DSH/bin:22-23\` / \`48\`）与 \`dsh-plugin-manager\` 的 \`README.zh.md\`。
8. **本机 whale 是 0.3.9 而不是 0.3.18**：本报告中引 \`WW/README\` 行号的地方都只对 **0.3.9** 成立；引"市场页 HEAD README"的地方对 0.3.18 成立。**两者不能互相引行号。**

---

## 附：本报告用到的实测命令（可复跑）

\`\`\`powershell
# 1) 仓库状态（结论：除别人的 _dev/probe_asset_absence.py 外干净）
cd "E:\deep seek\desktop-pet"; git status --porcelain; git log --oneline -1

# 2) npm 元数据 + 下载量
Invoke-RestMethod "https://registry.npmjs.org/dsh-whale-widget" | Select-Object -ExpandProperty dist-tags
Invoke-RestMethod "https://api.npmjs.org/downloads/point/last-week/dsh-whale-widget"

# 3) 市场目录（4489 条）与 whale 条目
$j = Invoke-RestMethod "https://awesome-dsh-plugin.com/plugins.json"
($j.plugins | Where-Object { $_.npm -eq 'dsh-whale-widget' }) | ConvertTo-Json -Depth 6

# 4) 桌面端 profile 为何装不了
Select-String -Path "E:\deep seek\DSH Desktop\resources\app\node_modules\@deepseek-ai\dsh\lib\bin.js" -Pattern "managed exclusively"
Get-Content "C:\Users\29179\AppData\Roaming\DSH Desktop\host-commands\desktop\generations\*\bin\dsh.cmd"

# 5) 本机装的是哪一版鲸鱼
(Get-Content "C:\Users\29179\.dsh\profiles\desktop\node_modules\dsh-whale-widget\package.json" | ConvertFrom-Json).version
\`\`\`

**— 报告结束 —**
