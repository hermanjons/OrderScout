from __future__ import annotations

from pathlib import Path

from Logistics.constants.catalog_constants import LOGISTICS_DEFAULT_CARGO_TARIFFS_FILE
from settings import USER_DATA_DIR


DOMAIN_CONSTANTS_ROOT = Path(__file__).resolve().parent
DOMAIN_FILES_ROOT = DOMAIN_CONSTANTS_ROOT / "files"

FINANCE_COST_ITEMS_DEFAULT_FILE = DOMAIN_FILES_ROOT / "finance_cost_items.default.json"
FINANCE_RUNTIME_STATE_FILE = USER_DATA_DIR / "finance_runtime_state.json"
FINANCE_CARGO_TARIFFS_FILE = USER_DATA_DIR / "finance_cargo_tariffs.json"
FINANCE_CARGO_TARIFFS_DEFAULT_FILE = LOGISTICS_DEFAULT_CARGO_TARIFFS_FILE

__all__ = [
    "DOMAIN_CONSTANTS_ROOT",
    "DOMAIN_FILES_ROOT",
    "FINANCE_CARGO_TARIFFS_DEFAULT_FILE",
    "FINANCE_CARGO_TARIFFS_FILE",
    "FINANCE_COST_ITEMS_DEFAULT_FILE",
    "FINANCE_RUNTIME_STATE_FILE",
]
