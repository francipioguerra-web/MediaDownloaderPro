# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('index.html', '.'), ('styles.css', '.'), ('script.js', '.')]
binaries = []
hiddenimports = []
tmp_ret = collect_all('pywebview')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('yt_dlp')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['app_fast.py'],
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
    [],
    exclude_binaries=True,
    name='MediaDownloader',
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MediaDownloader',
)
app = BUNDLE(
    coll,
    name='MediaDownloader.app',
    icon=None,
    bundle_identifier='com.mediadownloader.mac',
    info_plist={
        'CFBundleDisplayName': 'MediaDownloader',
        'CFBundleName': 'MediaDownloader',
        'CFBundleIdentifier': 'com.mediadownloader.mac',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'CFBundleURLTypes': [
            {
                'CFBundleURLName': 'MediaDownloader Protocol',
                'CFBundleURLSchemes': ['mediadownloader']
            }
        ]
    }
)
