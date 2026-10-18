from __future__ import annotations

from pathlib import Path

from settings import ASSETS_DIR, USER_DATA_DIR

ORDERS_ASSETS_DIR = Path(ASSETS_DIR)
ORDERS_FETCH_PANEL_ICON_PATH = ORDERS_ASSETS_DIR / "veri-cekme.png"
ORDERS_MANAGER_ICON_PATH = ORDERS_ASSETS_DIR / "orders-manager-icon.png"
ORDERS_RETURNS_ICON_PATH = ORDERS_ASSETS_DIR / "orders-returns-icon.png"
ORDERS_SIDEBAR_EDIT_ICON_PATH = ORDERS_ASSETS_DIR / "duzenleme-icon.png"
ORDERS_SIDEBAR_BULK_ICON_PATH = ORDERS_ASSETS_DIR / "toplu-secim (2).png"

ORDER_FALLBACK_LOGO_PATH = "images/siparisler.png"
ORDERS_RUNTIME_STATE_FILE = Path(USER_DATA_DIR) / "orders_runtime_state.json"
