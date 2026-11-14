"""Stage the pinned local model runtimes and distribution license files."""
from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import io
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile
from urllib.request import urlopen
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[2]
LLAMA_RELEASE = "b9221"
LLAMA_DIGESTS = {
    "cpu": "d90efe3ef03cfc1f16f001e559420ea9aaa2d18d7b295bc30e7a336c68add0ae",
    "vulkan": "2e3a946da07d1eaf3917b810cf05c16ae36e0fc4b07334a2b774ee8f786e4374",
}
LLAMA_BASE = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_RELEASE}"
VC_REDIST = (
    "https://download.visualstudio.microsoft.com/download/pr/e9604e21-4b79-4096-a4b3-1b63d4b55b4d/CC0FF0EB1DC3F5188AE6300FAEF32BF5BEEBA4BDD6E8E445A9184072096B713B/VC_redist.x64.exe",
    "cc0ff0eb1dc3f5188ae6300faef32bf5beeba4bdd6e8e445a9184072096b713b",
)
PYQT_SOURCE = (
    "https://files.pythonhosted.org/packages/d1/f9/b0c2ba758b14a7219e076138ea1e738c068bf388e64eee68f3df4fc96f5a/PyQt6-6.7.1.tar.gz",
    "3672a82ccd3a62e99ab200a13903421e2928e399fda25ced98d140313ad59cb9",
)


def verified_download(cache: Path, url: str, sha256: str) -> bytes:
    file = cache / url.rsplit("/", 1)[-1]
    if file.is_file():
        data = file.read_bytes()
    else:
        with urlopen(url, timeout=40) as response:
            data = response.read()
    if hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError(f"SHA-256 mismatch for {file.name}")
    if not file.exists():
        file.write_bytes(data)
    return data


def stage_runtime(bundle: Path, cache: Path) -> None:
    for variant, digest in LLAMA_DIGESTS.items():
        name = f"llama-{LLAMA_RELEASE}-bin-win-{variant}-x64.zip"
        data = verified_download(cache, f"{LLAMA_BASE}/{name}", digest)
        target = bundle / "_internal" / "AI" / "runtime" / "llama.cpp" / f"windows-x64-{variant}"
        target.mkdir(parents=True, exist_ok=True)
        with ZipFile(io.BytesIO(data)) as archive:
            for member in archive.namelist():
                filename = PurePosixPath(member).name
                if filename.endswith(".dll") or filename == "llama-server.exe":
                    (target / filename).write_bytes(archive.read(member))


def stage_licenses(bundle: Path, cache: Path) -> None:
    output = bundle / "licenses"
    output.mkdir(exist_ok=True)
    for dist in metadata.distributions():
        destination = output / (dist.metadata["Name"] + "-" + dist.version)
        for item in dist.files or ():
            name = item.name.casefold()
            if name.startswith(("license", "copying", "notice")) or "licenses" in item.parts:
                target = destination / item
                source = dist.locate_file(item)
                if ".." not in item.parts and not item.is_absolute() and source.is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    extra = {
        "llama.cpp-b9221/MIT.txt": (
            "https://raw.githubusercontent.com/ggml-org/llama.cpp/b9221/LICENSE",
            "94f29bbed6a22c35b992c5c6ebf0e7c92f13b836b90f36f461c9cf2f0f1d010d",
        ),
        "LLVM-OpenMP-19.1.5/LICENSE.txt": (
            "https://raw.githubusercontent.com/llvm/llvm-project/llvmorg-19.1.5/openmp/LICENSE.TXT",
            "fdad1758a9e1f9d5a81e18879b3406772115edc92c24bfa36b70c654f325e8e4",
        ),
    }
    for name, (url, digest) in extra.items():
        destination = output / name
        destination.parent.mkdir(exist_ok=True)
        destination.write_bytes(verified_download(cache, url, digest))
    with tarfile.open(fileobj=io.BytesIO(verified_download(cache, *PYQT_SOURCE)), mode="r:gz") as archive:
        license_file = archive.extractfile("PyQt6-6.7.1/LICENSE")
        if license_file is None:
            raise ValueError("Missing PyQt6 license")
        destination = output / "PyQt6-6.7.1"
        destination.mkdir(exist_ok=True)
        (destination / "LICENSE").write_bytes(license_file.read())
    python = output / "Python"
    python.mkdir(exist_ok=True)
    shutil.copy2(Path(sys.base_prefix) / "LICENSE.txt", python)
    original = output / "OrderScout"
    original.mkdir(exist_ok=True)
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(ROOT / name, original)
    shutil.copy2(ROOT / "docs" / "windows-build.md", output / "SOURCE.md")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("download_cache", type=Path)
    args = parser.parse_args()
    if not (args.bundle / "OrderScout.exe").is_file():
        parser.error("bundle must contain the built OrderScout.exe")
    args.download_cache.mkdir(parents=True, exist_ok=True)
    verified_download(args.download_cache, *VC_REDIST)
    stage_runtime(args.bundle, args.download_cache)
    stage_licenses(args.bundle, args.download_cache)


if __name__ == "__main__":
    main()
