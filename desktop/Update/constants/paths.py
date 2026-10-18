from __future__ import annotations

from pathlib import Path

from settings import USER_DATA_DIR


UPDATE_CONFIG_FILE = Path(__file__).resolve().parent / "files" / "update_config.json"
UPDATES_ROOT = USER_DATA_DIR / "updates"
UPDATES_ROOT.mkdir(parents=True, exist_ok=True)
UPDATE_STATE_FILE = USER_DATA_DIR / "update_state.json"
