# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['oc.py'],
    pathex=[],
    binaries=[],
    datas=[('pictures', 'pictures')],
    # pynput 会根据 Windows 平台动态加载这些模块，必须明确告诉 PyInstaller。
    hiddenimports=[
        'pynput',
        'pynput.mouse',
        'pynput.keyboard',
        'pynput._util',
        'pynput._util.win32',
        'pynput.mouse._win32',
        'pynput.keyboard._win32',
        'charset_normalizer',
        'pypdf',
        'fitz',
    ],
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
    name='Giegisa',
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
    icon=['giegisa.ico'],
)
