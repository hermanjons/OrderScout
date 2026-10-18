from __future__ import annotations

from pathlib import Path


CORE_BASE_DIR = Path(__file__).resolve().parents[2]
CORE_CONSTANTS_DIR = Path(__file__).resolve().parent
CORE_DEFAULT_FILES_DIR = CORE_CONSTANTS_DIR / "files"

UNIT_OPTIONS_FILE = CORE_DEFAULT_FILES_DIR / "unit_options.json"
COUNTRY_DIRECTORY_FILE = CORE_DEFAULT_FILES_DIR / "country_directory.json"
CURRENCY_OPTIONS_FILE = CORE_DEFAULT_FILES_DIR / "currency_options.json"

__all__ = [
    "CORE_CONSTANTS_DIR",
    "CORE_BASE_DIR",
    "CORE_DEFAULT_FILES_DIR",
    "COUNTRY_DIRECTORY_FILE",
    "CURRENCY_OPTIONS_FILE",
    "UNIT_OPTIONS_FILE",
]
