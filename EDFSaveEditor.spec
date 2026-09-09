# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('AppIcon.ico', '.'), ('C:\\Python312\\Lib\\site-packages\\tksheet', 'tksheet'), ('EDFSaveEditorLogic.py', '.'), ('EDFSaveEditorSave_Handler.py', '.'), ('TableParser.py', '.'), ('EDFWeaponFarming.py', '.'), ('MissionNames.json', '.'), ('WeaponNamesLang.json', '.'), ('languages.json', '.'), ('fonts', 'fonts')]
binaries = [('C:\\Python312\\tcl\\tcl8.6', 'lib\\tcl8.6'), ('C:\\Python312\\tcl\\tk8.6', 'lib\\tk8.6')]
hiddenimports = ['customtkinter', 'timeit', 'cryptography.hazmat.bindings._openssl']
tmp_ret = collect_all('cryptography')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['EDFSaveEditorMain.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    a.binaries,
    a.datas,
    [],
    name='EDFSaveEditor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='version_info.txt',
    icon=['AppIcon.ico'],
)
