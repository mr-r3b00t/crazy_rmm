# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Remote Support Client (Windows x64)

Build with:
    pyinstaller client_windows.spec
"""

import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# Collect all submodules for packages that need them
mss_datas, mss_binaries, mss_hiddenimports = collect_all('mss')
pag_hiddenimports = collect_submodules('pyautogui')

a = Analysis(
    ['client_windows.py'],
    pathex=[],
    binaries=mss_binaries,
    datas=mss_datas,
    hiddenimports=[
        'websockets',
        'websockets.legacy',
        'websockets.legacy.client',
        'websockets.legacy.server',
        'websockets.legacy.protocol',
        'websockets.client',
        'websockets.server',
        'websockets.connection',
        'websockets.frames',
        'websockets.headers',
        'websockets.http11',
        'websockets.typing',
        'websockets.uri',
        'mss',
        'mss.windows',
        'PIL',
        'PIL.Image',
        'PIL.JpegImagePlugin',
        'pyautogui',
        'pyautogui._pyautogui_win',
        'pyscreeze',
        'pytweening',
        'pyperclip',
        'mouseinfo',
    ] + pag_hiddenimports + mss_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'scipy',
        'pandas',
        'IPython',
        'notebook',
        'pytest',
        'setuptools',
        'wheel',
        'pip',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='RemoteSupportClient',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # No console window (GUI app)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='x86_64',
    codesign_identity=None,
    entitlements_file=None,
    # icon='icon.ico',      # Uncomment if you have an icon file
    version_info=None,
)
