# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import re

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
)

root = Path(SPECPATH).resolve().parents[1]
desktop = root / "desktop"
settings = (desktop / "settings.py").read_text(encoding="utf-8")
version = re.search(r'APP_VERSION = os\.getenv\("ORDER_SCOUT_VERSION", "(\d+\.\d+\.\d+)"\)', settings)[1]
version_tuple = tuple(map(int, version.split("."))) + (0,)
assets = [desktop / "images", desktop / "Labels" / "assets"]
assets.extend(desktop.glob("*/constants/files"))
datas = [(str(path), path.relative_to(desktop).as_posix()) for path in assets]

# Migration discovery and the manual capability index read these source paths.
migrations = sorted(desktop.glob("*/models/**/migrations.py"))
action_sources = sorted(desktop.glob("*/views/actions.py"))
source_files = migrations + action_sources
datas.extend((str(path), path.parent.relative_to(desktop).as_posix()) for path in source_files)
hiddenimports = [".".join(path.relative_to(desktop).with_suffix("").parts) for path in source_files]
# Domain roots can be namespace packages. Resolve their lazy module names
# directly from the same source tree that Analysis imports.
for directory in (
    "Account/constants", "Core/views", "Finance/views", "Labels/processors",
    "Listing/constants", "Logistics/views", "Orders/views", "Stock/views",
):
    hiddenimports.extend(
        ".".join(path.relative_to(desktop).with_suffix("").parts)
        for path in sorted((desktop / directory).glob("*.py"))
        if path.name != "__init__.py"
    )
hiddenimports.append("Logistics.processors.cargo_amount_matcher")
hiddenimports.append("Testing.processors.windows_release_smoke")

analysis = Analysis(
    [str(desktop / "main.py")],
    pathex=[str(desktop)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["IPython", "matplotlib", "pytest", "scipy", "tkinter"],
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts,
    [],
    exclude_binaries=True,
    name="OrderScout",
    icon=str(desktop / "images" / "orderscout-logo.ico"),
    version=VSVersionInfo(
        ffi=FixedFileInfo(filevers=version_tuple, prodvers=version_tuple, mask=0x3F,
                          flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
        kids=[
            StringFileInfo([StringTable("040904B0", [
                StringStruct("FileDescription", "OrderScout"),
                StringStruct("FileVersion", version),
                StringStruct("OriginalFilename", "OrderScout.exe"),
                StringStruct("ProductName", "OrderScout"),
                StringStruct("ProductVersion", version),
            ])]),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    ),
    console=False,
    upx=False,
)
worker = EXE(
    pyz, analysis.scripts, [], exclude_binaries=True, name="OrderScoutWorker",
    console=True, upx=False,
)
app = COLLECT(exe, worker, analysis.binaries, analysis.datas, name="OrderScout", upx=False)
