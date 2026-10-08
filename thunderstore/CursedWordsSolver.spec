# -*- mode: python ; coding: utf-8 -*-
"""Windowed onedir build. data/ is packed for the frozen path helper."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).resolve().parent
datas = []
for folder, dest in (
    (root / "data" / "wiki", "data/wiki"),
    (root / "data" / "game", "data/game"),
):
    for path in sorted(folder.glob("*.json")):
        if path.name.startswith("_"):
            continue
        datas.append((str(path), dest))

a = Analysis(
    [str(root / "cursed_words_solver" / "app.py")],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=collect_submodules("cursed_words_solver"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(root / "thunderstore" / "pyi_rth_stdio.py")],
    excludes=["pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CursedWordsSolver",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="CursedWordsSolver",
)
