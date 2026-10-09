# 🐟 DaFeiYu Desktop Pet (大肥鱼桌宠)

> A spoiled, greedy, easily-startled desktop pet fish that calls you "Proxy" (绳匠)~
> Catchphrase: **What I like, I never let go~**

A Windows desktop pet built with **PySide6 (Qt6) + Python 3.10**, MIT licensed.
Transparent frameless window, always-on-top, draggable, feedable, chatty — perfect coding companion.

中文介绍见 [README.md](README.md)。

> **Note / 说明**：This English README is a short overview and **lags behind the Chinese README.md**
> (which documents v2.1 features: AI voice-cloning dubbing, customizable lines & dialogues,
> idle-behaviour system, local TTS-backend launcher, alarms…).
> The Chinese [README.md](README.md) is the authoritative, up-to-date document.
> 英文版只是概览，功能细节以中文 README.md 为准（v2.1 新增能力尚未全部翻译）。

## ✨ Features

- 🖼️ **Two forms with frame animation**: Normal + Full (round belly); 10-frame idle + 7-frame eating animation
- 😠 **Poke chain**: poke → puzzled, poke again within 2.5s → angry, again → hissing threat
- 🍰 **Feeding**: dried fish / cake / diamond; click to launch it flying into her mouth, or drag & drop
- 💬 **AI chat**: DeepSeek API, replies in short cute Chinese (≤25 chars) with short-term memory
- 🐍 **Xixifu-style personality** (Zenless Zone Zero's Cissia, aka "啥子蛇"): self-proclaimed "villain" who follows only her instincts — cold-tongued but soft-hearted, calls herself "本专员" (this commissioner) and wraps her gluttony in fake case investigations, sometimes hisses "嘶~"
- 💰 **Balance widget** (optional): DeepSeek API balance + today's usage, rolling numbers, auto-refresh every 60s
- 🔐 **Key security**: API Key encrypted with Windows DPAPI, never stored in plaintext
- 🎵 **Sounds**: press / release / feed / AI-reply-done / balance-credit (winsound-first chain, fallback-safe)
- 🖐️ **Petting**: hold the pet for 1.5s → petpet animation + shy line (inspired by the whale widget's petpet)
- 💸 **Money rain**: successful balance check → coin sound + money GIF frames
- 😴 **Idle life**: falls asleep after 60s, occasional mischievous grins, blushes when praised
- 📌 Single instance, tray icon, follow mouse / wander, wheel resize, edge snapping
- 🚀 **Auto-start on boot** (off by default, right-click → "⚙️ 设置…" to enable): HKCU Run key, greets you every morning
- 🐳 **v1.3 customization & bookkeeping (inspired by the dsh-whale-widget plugin)**:
  - 🖼️ **Character import**: right-click → "🐟 角色" to import png/jpg/bmp/webp with auto background-removal / trim / scale; **1~8 custom forms with your own names and images** (feeding cycles through forms, back to the first after 12s); switch/delete/restore anytime
  - 🎞️ **Animated characters (v1.3.2)**: pick multiple images as a frame sequence, or auto-extract frames from a **video / GIF** (video: 3~20 sampled frames, GIF: 3~24); every frame gets the same auto-processing; idle loops the animation, feeding switches to the full form
  - Custom characters get **procedural expression art** (blush/anger/sleep marks composited onto your image, v1.3.3) plus bubble & head emote; squish/edge/follow effects kept
  - 🔊 **Sound import + custom sound groups**: import wav/mp3 clips with preview; each of the 5 events (poke/release/feed/AI reply/coin) can use any clip or stay silent
  - 📦 **Resource manager**: one window for characters and audio clips (preview/audition/set-active/delete)
  - 📒 **Bookkeeping**: balance-diff auto-ledger (daily archive) + manual entries; ledger window with today / 7 days / all, search and CSV export; daily budget & balance alerts (once per day)
  - 🎨 **Bubble style + custom lines**: bubble colors/font/radius fully adjustable; add your own lines to four line pools
  - 🌈 **Beautified right-click menu**: compact dark rounded theme, size slider, emoji icons, balance/today-usage info row

## 🚀 Quick Start

**Option 1: Portable build (recommended, no Python needed)**

Download `daifeiyu-desktop-pet.zip` from [Releases](../../releases) → extract → double-click `启动桌宠.vbs`.
(Uses Microsoft-signed pythonw.exe + bundled runtime; no self-extracting exe that antivirus flags.)

**Option 2: Run from source**

```bash
pip install -r requirements.txt
python main.py   # canonical entry (桌宠.py kept as compat shim)
```

## 🎮 Controls

- Left-drag to move; hold for a squishy Q-bounce effect
- Right-click menu (compact dark theme, whale-widget style): balance/today-usage header + 🎚️ size slider; flat toggles (always-on-top / sound / AI chat); talk · feed (incl. tray & forms) · characters · ledger (widget/books/entry/budget/alert) · resource manager · settings… (follow/wander/bubble/sound group/lines/API key); praise/weather/system/about/quit
- Poke 3 times in a row for the full emotion chain; praise her to make her blush
- Full form digests back to normal after ~12 seconds

## 🛠️ Platform & data notes

- **Windows only** (winsound audio, DPAPI key encryption and tray icon are Windows-specific; no macOS/Linux build yet)
- Weather uses the free [open-meteo](https://open-meteo.com/) API, default city Beijing; right-click → "📍 天气城市…" to change and save
- Runtime data lives next to the app (falls back to %APPDATA%\大肥鱼桌宠 when read-only)

## 🧠 AI Chat & Bookkeeping (optional)

1. Right-click → "设置DeepSeek API Key" and paste your key (sk-...)
2. Right-click → "和它说话" to chat; enable "余额挂件" for the balance widget
3. Right-click → "查询余额": balance drops are auto-recorded (daily archive); "✏️ 记一笔" for manual entries; "📒 账本" shows today / 7 days / all with search and CSV export
4. Right-click → "💸 今日预算" / "🚨 余额预警" to set alert thresholds (0 = off; once per day)
5. Before sharing, right-click → "清除DeepSeek API Key" to wipe key and balance baseline (manual entries kept)

> All network calls use HTTPS with timeouts; the key is DPAPI-encrypted and bound to your Windows account.

## 🎨 Customize your pet

- **Character**: right-click → "🐟 角色" → "导入角色…" — material is auto-processed (background removed when opaque, transparent margins trimmed, oversized images scaled; png/jpg/bmp/webp supported):
  - **Single form**: pick one image; normal/full forms share it
  - **Dual form**: also pick a "full" image; feeding switches between the two (you choose the mode)
  - **Animated**: pick multiple images as an ordered frame sequence, or auto-extract frames from a video / GIF (video 3~20, GIF 3~24 frames)
  - Emotions = procedural expression art + bubble + head emote; squish/edge/follow effects kept
- **Sounds**: right-click → "🎵 音效设置" → "管理音频片段…" to import wav/mp3 and audition; assign a clip (or silence) per event in the custom group
- **Bubble**: right-click → "🎨 气泡样式…" to tweak background/text/border colors, font size and corner radius
- **Lines**: right-click → "💬 自定义台词…" to append your own lines to four pools
- Custom data lives next to the app (roles/, audio/, config.json) — copy these to migrate

## 🛡️ Antivirus note

Unsigned PyInstaller exes get false-flagged by AV/ML engines (we saw Defender report `Wacapew.C!ml`),
so this project ships a **portable build** (pythonw.exe + source) by default — nothing for AV to flag.
All source code is public for review.

## 📁 Structure

```
desktop-pet/
├── 桌宠.py              # main app (window / interactions / AI / balance / menu)
├── pet_anim.py          # frame animation module
├── pet_mood.py          # mood state machine
├── pet_audio.py         # sound module (winsound-first chain + custom groups)
├── pet_fx.py            # frame-fx module (petting / money rain)
├── pet_resources.py     # resource library: character & audio import (v1.3)
├── pet_book.py          # ledger: balance-diff bookkeeping, daily archive, alerts (v1.3)
├── pet_dialogs.py       # resource/ledger/bubble-style/lines dialogs (v1.3)
├── assets/              # frames / expressions / sounds
├── 去背景.py            # background removal tool
├── 生成占位角色.py      # placeholder generator
├── 启动桌宠.bat         # source-run launcher
├── 大肥鱼桌宠.spec      # PyInstaller spec (optional exe build)
└── docs/                # design docs

> Runtime data (auto-generated, not committed): config.json (since v2: diff-only storage,
> DPAPI-encrypted key), ledger.json / ledger_archive.json, roles/ + roles.json, audio/ + audio.json
```

> Asset note: the petpet/money animations and task-end-a/exp-orb sounds are inspired by the MIT-licensed dsh-whale-widget plugin (DeepSeek-Balance-Whale-Widget series); frame images were converted from GIFs.

## 📜 License

[MIT](LICENSE) © DaFeiYu Desktop Pet Project