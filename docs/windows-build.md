# Windows x64 build

OrderScout 0.3.6 runs on Windows 10 and 11 on x64. Build it from the repository
root with Python 3.11 x64 and Inno Setup 6.7.1. Use a clean Python environment
and the two hash-locked dependency files.

```powershell
py -3.11 -m venv .venv-build
$python = ".\.venv-build\Scripts\python.exe"
& $python -m pip install --require-hashes -r requirements.lock -r scripts/windows/build-requirements.lock
& $python -m PyInstaller --noconfirm --workpath build/windows --distpath dist/windows scripts/windows/OrderScout.spec
& $python scripts/windows/stage-dependencies.py dist/windows/OrderScout build/windows/downloads
$app = (Resolve-Path dist/windows/OrderScout).Path
$out = (Resolve-Path dist/windows).Path
$vcRedist = (Resolve-Path build/windows/downloads/VC_redist.x64.exe).Path
$version = (Get-Item "$app\OrderScout.exe").VersionInfo.ProductVersion
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" "/DAppVersion=$version" "/DAppDir=$app" "/DOutputDir=$out" "/DVCRedist=$vcRedist" scripts/windows/OrderScout.iss
```

The setup file is `dist/windows/OrderScout_Setup_x64.exe`. A different Inno Setup
installation location requires adjusting the ISCC path. The app executable uses
the adjacent `_internal` directory and the worker executable in the same
installation directory.

Run the packaged checks with a new output directory. This command creates an
isolated database and uses recorded model responses.

```powershell
Start-Process -FilePath "$app\OrderScout.exe" -WindowStyle Hidden -Wait -PassThru -ArgumentList '--smoke-windows-release', '"D:\OrderScout-release-check"'
```

## Source for distributed components

The corresponding OrderScout source, including the installer and build
scripts, is tagged [v0.3.6](https://github.com/hermanjons/OrderScout/tree/v0.3.6).
Released binaries and source archives are linked from the
[Windows download page](https://github.com/hermanjons/OrderScout-releases/releases/tag/v.0.3.6).

| Component | Source |
| --- | --- |
| Python 3.11.15 | [CPython v3.11.15](https://github.com/python/cpython/tree/v3.11.15) |
| PyQt6 6.7.1 | [Source distribution](https://pypi.org/project/PyQt6/6.7.1/#files) |
| PyQt6-sip 13.8.0 | [Source distribution](https://pypi.org/project/PyQt6-sip/13.8.0/#files) |
| Qt 6.7.2 | [Qt 6.7.2 source modules](https://download.qt.io/archive/qt/6.7/6.7.2/submodules/), including Qt Base, Qt SVG, Qt PDF in Qt WebEngine, and Qt translations |
| llama.cpp b9221 | [Source and build files](https://github.com/ggml-org/llama.cpp/tree/b9221) |
| LLVM OpenMP 19.1.5 | [Source](https://github.com/llvm/llvm-project/tree/llvmorg-19.1.5/openmp) |
| PyInstaller 6.22.3 | [Bootloader and build source](https://github.com/pyinstaller/pyinstaller/tree/v6.22.3) |

The other Python packages and their exact versions are in the dependency locks
and their source distributions are on PyPI. License texts are in the installed
`licenses` folder.
