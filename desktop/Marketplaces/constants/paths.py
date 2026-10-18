from __future__ import annotations

from pathlib import Path

from settings import USER_DATA_DIR


MARKETPLACES_CONSTANTS_DIR = Path(__file__).resolve().parent
MARKETPLACES_DEFAULT_FILES_DIR = MARKETPLACES_CONSTANTS_DIR / "files"

DEFAULT_MARKETPLACES_FILE = MARKETPLACES_DEFAULT_FILES_DIR / "default_marketplaces.json"

DOMAIN_CONSTANTS_ROOT = USER_DATA_DIR / "constants" / "marketplaces"
MARKETPLACE_LABEL_OVERRIDES_FILE = DOMAIN_CONSTANTS_ROOT / "marketplace_label_overrides.user.json"


def platform_api_config_file(platform_code: str) -> Path:
    code = str(platform_code or "").strip().casefold()
    return MARKETPLACES_DEFAULT_FILES_DIR / code / "platform_api_config.json"


def platform_cargo_config_file(platform_code: str) -> Path:
    code = str(platform_code or "").strip().casefold()
    return MARKETPLACES_DEFAULT_FILES_DIR / code / "platform_cargo_config.json"


def ensure_marketplaces_paths() -> None:
    DOMAIN_CONSTANTS_ROOT.mkdir(parents=True, exist_ok=True)
