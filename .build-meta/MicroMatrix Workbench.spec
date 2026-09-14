# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.hooks import collect_submodules

datas = [
    ('/Users/micromatrix/Documents/Project/micromatrix-workbench/vendor/cloudflared/darwin-arm64/cloudflared.manifest.json', 'vendor/cloudflared/darwin-arm64'),
    ('/Users/micromatrix/Documents/Project/micromatrix-workbench/.build-meta/build-version.txt', 'agent_workbench'),
    ('/Users/micromatrix/Documents/Project/micromatrix-workbench/agent_workbench/web/dist', 'agent_workbench/web/dist'),
]
binaries = [('/Users/micromatrix/Documents/Project/micromatrix-workbench/vendor/cloudflared/darwin-arm64/cloudflared', 'vendor/cloudflared/darwin-arm64')]
hiddenimports = []
hiddenimports += collect_submodules('agent_runtime')
hiddenimports += collect_submodules('agent_workbench')
tmp_ret = collect_all('webview')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

a = Analysis(
    ['/Users/micromatrix/Documents/Project/micromatrix-workbench/desktop.py'],
    pathex=['/Users/micromatrix/Documents/Project/micromatrix-workbench'],
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
    name='MicroMatrix Workbench',
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
    icon=['/Users/micromatrix/Documents/Project/micromatrix-workbench/deploy/icons/workbench-app-icon.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MicroMatrix Workbench',
)
app = BUNDLE(
    coll,
    name='MicroMatrix Workbench.app',
    icon='/Users/micromatrix/Documents/Project/micromatrix-workbench/deploy/icons/workbench-app-icon.icns',
    bundle_identifier='org.micromatrix.workbench',
    version='0.4.22',
    info_plist={'CFBundleVersion': '0.4.22'},
)
