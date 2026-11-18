# -*- mode: python ; coding: utf-8 -*-
# PyInstaller one-file, windowed release for ATLAS AI.
from pathlib import Path

root = Path(SPECPATH).resolve()

required_files = [
    root / "ATLAS_AI.py",
    root / "server.json",
    root / "assets" / "atlas_nebula_background.png",
    root / "gokatlasico.ico",
]
missing = [str(path) for path in required_files if not path.is_file()]
if missing:
    raise FileNotFoundError("Build input missing: " + ", ".join(missing))

a = Analysis(
    [str(root / "ATLAS_AI.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(root / "server.json"), "."),
        (str(root / "assets" / "atlas_nebula_background.png"), "assets"),
        (str(root / "gokatlasico.ico"), "."),
    ],
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
    a.binaries,
    a.datas,
    [],
    name="ATLAS_AI",
    icon=str(root / "gokatlasico.ico"),
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
)
