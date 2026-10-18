from __future__ import annotations

from pathlib import Path

from settings import USER_DATA_DIR


# Program bundle defaults (read-only intent)
STOCK_CONSTANTS_DIR = Path(__file__).resolve().parent
STOCK_DEFAULT_FILES_DIR = STOCK_CONSTANTS_DIR / "files"
DEFAULT_UPPER_GROUPS_FILE = STOCK_DEFAULT_FILES_DIR / "upper_groups.json"
DEFAULT_SUB_GROUPS_FILE = STOCK_DEFAULT_FILES_DIR / "sub_groups.json"
ITEM_TYPE_OPTIONS_FILE = STOCK_DEFAULT_FILES_DIR / "item_type_options.json"

# User additions (AppData)
DOMAIN_CONSTANTS_ROOT = USER_DATA_DIR / "constants" / "stock"
USER_UPPER_GROUPS_FILE = DOMAIN_CONSTANTS_ROOT / "upper_groups.user.json"
USER_SUB_GROUPS_FILE = DOMAIN_CONSTANTS_ROOT / "sub_groups.user.json"


def ensure_constants_paths() -> None:
    DOMAIN_CONSTANTS_ROOT.mkdir(parents=True, exist_ok=True)
