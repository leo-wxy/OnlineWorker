# -*- mode: python ; coding: utf-8 -*-
# onlineworker.spec — PyInstaller spec for building the OnlineWorker Telegram bot
# Run: pyinstaller onlineworker.spec --clean --noconfirm
# Output: dist/onlineworker-bot (single macOS binary)

import platform

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[],  # No data files needed — config is external via --data-dir
    hiddenimports=[
        'yaml',
        'dotenv',
        'httpx',
        'httpx._transports',
        'httpx._transports.default',
        'websockets',
        'websockets.legacy',
        'websockets.legacy.client',
        'telegram',
        'telegram.ext',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'unittest',
        'pytest',
        'test',
        'tests',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='onlineworker-bot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,   # Strip symbols for smaller binary
    upx=False,    # UPX not used on macOS
    console=True,  # stdout/stderr for Tauri sidecar to capture
    target_arch='arm64',  # Apple Silicon
)
