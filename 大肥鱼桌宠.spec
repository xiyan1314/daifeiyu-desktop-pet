# -*- mode: python ; coding: utf-8 -*-


# v2.12.0（第 12 轮 · 遗留-1）：入口改成 main.py —— 它是崩溃自动重启的守护入口。
# 此前这里是 桌宠.py ⇒ 打包出来的 exe 上 pet_guard 一次都不执行（见 _dev/REMAINING.md 遗留-1）。
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='大肥鱼桌宠',
    version='version_info.txt',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='大肥鱼桌宠',
)