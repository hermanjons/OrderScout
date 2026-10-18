from __future__ import annotations

import json

from Update.constants.paths import UPDATE_CONFIG_FILE


_UPDATE_CONFIG_SIGNATURE: tuple[str, int, int] | None = None
_UPDATE_CONFIG_CACHE: dict | None = None


def _config_signature() -> tuple[str, int, int]:
    stat = UPDATE_CONFIG_FILE.stat()
    return (str(UPDATE_CONFIG_FILE), int(stat.st_mtime_ns), int(stat.st_size))


def load_default_update_config() -> dict:
    global _UPDATE_CONFIG_SIGNATURE, _UPDATE_CONFIG_CACHE

    if not UPDATE_CONFIG_FILE.exists():
        raise RuntimeError(f"Update config bulunamadi: {UPDATE_CONFIG_FILE}")
    signature = _config_signature()
    if _UPDATE_CONFIG_CACHE is not None and _UPDATE_CONFIG_SIGNATURE == signature:
        return dict(_UPDATE_CONFIG_CACHE)
    try:
        raw = UPDATE_CONFIG_FILE.read_text(encoding="utf-8-sig")
        payload = json.loads(raw)
    except Exception as exc:
        raise RuntimeError(f"Update config okunamadi/bozuk: {UPDATE_CONFIG_FILE}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Update config JSON obje olmalidir.")
    _UPDATE_CONFIG_SIGNATURE = signature
    _UPDATE_CONFIG_CACHE = dict(payload)
    return dict(payload)


def clear_update_catalog_cache() -> None:
    global _UPDATE_CONFIG_SIGNATURE, _UPDATE_CONFIG_CACHE
    _UPDATE_CONFIG_SIGNATURE = None
    _UPDATE_CONFIG_CACHE = None
