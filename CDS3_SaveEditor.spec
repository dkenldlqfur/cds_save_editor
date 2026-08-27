# -*- mode: python ; coding: utf-8 -*-
import os
import json

_project_root = os.path.abspath(SPECPATH)

# Python 3.14의 Tcl 탐색이 한글 사용자 프로필 경로에서 실패할 수 있다.
# 리소스에 둔 영문 경로의 Tcl/Tk 데이터를 PyInstaller와 스플래시가 사용하게 한다.
_resource_tcl_root = os.path.join(_project_root, 'Resources', 'tcl')
os.environ['TCL_LIBRARY'] = os.path.join(_resource_tcl_root, 'tcl8.6')
os.environ['TK_LIBRARY'] = os.path.join(_resource_tcl_root, 'tk8.6')

with open(os.path.join(_project_root, 'Resources', 'data', 'app_config.json'), 'r', encoding='utf-8') as _config_file:
    _app_version = json.load(_config_file)['version']


a = Analysis(
    [os.path.join(_project_root, 'CDS_SaveEditor.pyw')],
    pathex=[_project_root],
    binaries=[],
    datas=[(os.path.join(_project_root, 'Resources'), 'Resources')],
    hiddenimports=['vlc'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

splash = Splash(
    os.path.join(_project_root, 'Resources', 'splash.jpg'),
    binaries=a.binaries,
    datas=a.datas,
    text_pos=None,
    text_size=12,
    minify_script=True,
    always_on_top=True,
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    splash,
    splash.binaries,
    [],
    name='CDS_SaveEditor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[os.path.join(_project_root, 'Resources', 'Icon.ico')],
)
