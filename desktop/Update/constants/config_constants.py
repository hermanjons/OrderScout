from __future__ import annotations

from Update.processors.catalog import load_default_update_config


DEFAULT_UPDATE_CONFIG = load_default_update_config()
VALID_UPDATE_CHANNELS = ("stable", "beta")
VERSION_DIR_PREFIX = "os-"

__all__ = [
    "DEFAULT_UPDATE_CONFIG",
    "VALID_UPDATE_CHANNELS",
    "VERSION_DIR_PREFIX",
]
