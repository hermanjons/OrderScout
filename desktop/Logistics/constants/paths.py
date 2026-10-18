from __future__ import annotations

from pathlib import Path

from settings import MEDIA_ROOT


DOMAIN_CONSTANTS_ROOT = Path(__file__).resolve().parent
LOGISTICS_FILES_ROOT = DOMAIN_CONSTANTS_ROOT / "files"

CARGO_PROVIDERS_FILENAME = "cargo_providers.json"
CARGO_TARIFFS_DEFAULT_FILENAME = "cargo_tariffs.default.json"
CARGO_PROVIDER_LOGOS_DIRNAME = "cargo_provider_logos"


def cargo_providers_file() -> Path:
    return LOGISTICS_FILES_ROOT / CARGO_PROVIDERS_FILENAME


def cargo_tariffs_default_file() -> Path:
    return LOGISTICS_FILES_ROOT / CARGO_TARIFFS_DEFAULT_FILENAME


def cargo_provider_logos_dir() -> Path:
    path = MEDIA_ROOT / CARGO_PROVIDER_LOGOS_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path
