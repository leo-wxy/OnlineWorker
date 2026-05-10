# -*- mode: python ; coding: utf-8 -*-
# onlineworker-x86_64.spec — PyInstaller spec for building x86_64 (Intel) binary
# Run: arch -x86_64 /usr/local/bin/python3.13 -m PyInstaller onlineworker-x86_64.spec --clean --noconfirm --distpath dist-x86_64

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=[
        'yaml',
        'dotenv',
        'httpx',
        'httpx._transports',
        'httpx._transports.default',
        'socksio',
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
    strip=True,
    upx=False,
    console=True,
    target_arch='x86_64',  # Intel
)
