# A-10 真机取证（2026-10-16 · dsh-main-r11）

> 探针：`E:\deep seek\_r11_a10_probe\probe_a10.py`（**真桌面**，不设 `QT_QPA_PLATFORM`）。
> 背景：A-10 一直是**静态推断**（Qt 的 `WindowDoesNotAcceptFocus` → Windows `WS_EX_NOACTIVATE`），
> REMAINING 里记的是「真机从没验过」。本文件把这个洞补上。

## 一、实测读数（原文）

```
QT_QPA_PLATFORM = (未设，= windows 真桌面)
A 桌宠同款(含DoesNotAcceptFocus): hwnd=0x3090390  exstyle=0x08080088  bits=NOACTIVATE,TOOLWINDOW,TOPMOST,LAYERED  is_foreground=False
B 对照组(去掉DoesNotAcceptFocus):  hwnd=0x2370698  exstyle=0x00080088  bits=TOOLWINDOW,TOPMOST,LAYERED                  is_foreground=False
判读①桌宠窗口有 WS_EX_NOACTIVATE: True
判读②对照组没有（证明探针能区分，不是恒真）: True
A-10 PROBE OK
```

- `0x08080088` 里的 **`0x08000000` = `WS_EX_NOACTIVATE`** → **点它不会激活窗口，也就拿不到键盘焦点**。
- 对照组（同 flags 只去掉 `WindowDoesNotAcceptFocus`）= `0x00080088`，**没有** `WS_EX_NOACTIVATE`
  → 探针**能区分**（不是"读到 0 也算过"的恒真判据）。
- 两个窗口 `is_foreground=False`：`show()` **没有抢前台**（这条同时证明"不抢焦点"的意图在真机成立）。

## 二、结论（把推断改成实测）

1. **主窗口的 Esc / Enter / Space 在真机上不可达**（除非窗口已被其它途径给了焦点）。
   → 发布说明里那句「点过它并拿到键盘焦点时生效」**在真机上等于"永远不生效"**，必须改口径。
2. **可靠入口 = 托盘菜单**（托盘图标接受点击，不依赖 `WS_EX_NOACTIVATE`）。
3. 这**不是 bug**：`WindowDoesNotAcceptFocus` 是**有意**钉死的（桌宠常驻桌面，抢焦点会打断用户正在敲的东西）。
   → 所以修法是**改文案 + 把"有意"写进用例旁**（C-39），**不是**去掉那个 flag。

## 三、本轮落地

- 发布说明 / README 的措辞：改成「**键盘快捷键仅在窗口已获得键盘焦点时生效；托盘菜单是可靠入口**」（与事实一致）。
- `tests/test_motion_v2110.py` 那条钉死 `WindowDoesNotAcceptFocus` 的断言旁补注释（**C-39**）：
  写明「这是有意钉死；要让主窗口收键，先读这条代价」。
- **不新增判据**（真机桌面状态无法进 CI）；本文件就是这条事实的证据通道。

## 四、补测（同日 · 更强的一条：**平台行为**而非静态位）

`_r11_a10_probe/probe_a10_v2.py` 在同一个窗口上再问一句 `SendMessageW(WM_MOUSEACTIVATE)`：

```
QT_QPA_PLATFORM = (未设 = windows 真桌面)
A 桌宠同款（含 DoesNotAcceptFocus）
    exstyle=0x08080088  bits=NOACTIVATE,TOOLWINDOW,TOPMOST,LAYERED
    WM_MOUSEACTIVATE=3 MA_NOACTIVATE（点击不激活）
B 对照组（去掉 DoesNotAcceptFocus）
    exstyle=0x00080088  bits=TOOLWINDOW,TOPMOST,LAYERED
    WM_MOUSEACTIVATE=1 MA_ACTIVATE（点击会激活）
A-10 PROBE OK
```

→ **"点它不激活"是平台对这条消息的回答**（`MA_NOACTIVATE`），不是我从 flag 位推的。
（另有一位只读研究代理独立跑出**同一组读数**：0x08080088 / MA_NOACTIVATE=3，对照组 0x00080088 / MA_ACTIVATE=1。）

## 五、两处**仍然没验到**（如实）

1. **真人点一下**：用 `SendInput` 合成的点击**连对照组都没抢到前台**（`GetForegroundWindow` 不变）→
   注入点击的语义 ≠ 真人点击。**"真人点它能不能拿到焦点"这一格仍然只能靠人**。
2. **不能写成普通 pytest 用例**：`tests/conftest.py:7` 强制 `QT_QPA_PLATFORM=offscreen`，
   而 offscreen 下 `winId()` **不是真 HWND**，读 exstyle 没有意义。
   → 所以这条判据的形态只能是**独立探针**（`_dev/probe_focus_noactivate.py`，不进 pytest）。

附注（值得记住）：`SetForegroundWindow` 对这类窗口**返回 1 且真切了前台** ——
所以"在菜单里做一个『取得焦点』入口"**并非注定无效**，只是"焦点进来之后 `WM_KEYDOWN` 会不会到达窗口"仍未验。
本轮**不做**这个入口（那会新增一个未验证的承诺），托盘「👉 戳一下」已可靠且有用例钉着。
