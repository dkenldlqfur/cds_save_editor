# PyInstaller 3.3 specification for the Windows XP (SP3, x86) build.
# Build this specification with Python 3.4 x86 and PyInstaller 3.3.1.

import os
import json

project_root = os.path.abspath(SPECPATH)
with open(os.path.join(project_root, 'Resources', 'data', 'app_config.json'), 'r', encoding='utf-8') as config_file:
    app_version = json.load(config_file)['version']
distribution_name = 'CDS_SaveEditor_XP_v' + app_version

a = Analysis(
    [os.path.join(project_root, 'CDS_SaveEditor.pyw')],
    pathex=[project_root],
    binaries=[],
    datas=[(os.path.join(project_root, 'Resources'), 'Resources')],
    hiddenimports=['vlc'],
    hookspath=[],
    runtime_hooks=[],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    name=distribution_name,
    debug=False,
    strip=False,
    upx=False,
    console=False,
    exclude_binaries=True,
    icon=os.path.join(project_root, 'Resources', 'Icon.ico'),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    name=distribution_name,
)
