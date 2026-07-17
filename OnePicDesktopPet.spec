# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path


datas = [("assets", "assets"), ("config", "config")]
private_assets = Path("user_assets")
if os.environ.get("ONEPIC_INCLUDE_USER_ASSETS") == "1" and private_assets.exists():
    datas.append(("user_assets", "user_assets"))

a = Analysis(
    ["main.py"],
    pathex=["src"],
    binaries=[],
    datas=datas,
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
    name="OnePicDesktopPet",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["assets\\icons\\pet.png"],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="OnePicDesktopPet",
)
