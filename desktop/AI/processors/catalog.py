from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from AI.constants.paths import DEFAULT_AI_CONFIG_FILE


_DEFAULT_AI_CONFIG_SIGNATURE: tuple[str, int, int] | None = None
_DEFAULT_AI_CONFIG_CACHE: dict[str, Any] | None = None


def _json_file_signature(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return (str(path), int(stat.st_mtime_ns), int(stat.st_size))


def _read_default_ai_config(path: Path) -> dict[str, Any]:
    global _DEFAULT_AI_CONFIG_SIGNATURE, _DEFAULT_AI_CONFIG_CACHE

    try:
        if not path.exists():
            _DEFAULT_AI_CONFIG_SIGNATURE = None
            _DEFAULT_AI_CONFIG_CACHE = {}
            return {}
        signature = _json_file_signature(path)
        if _DEFAULT_AI_CONFIG_CACHE is not None and _DEFAULT_AI_CONFIG_SIGNATURE == signature:
            return dict(_DEFAULT_AI_CONFIG_CACHE)
        payload = json.loads(path.read_text(encoding="utf-8"))
        out = payload if isinstance(payload, dict) else {}
        _DEFAULT_AI_CONFIG_SIGNATURE = signature
        _DEFAULT_AI_CONFIG_CACHE = dict(out)
        return dict(out)
    except Exception:
        return {}


def load_default_ai_config() -> dict[str, Any]:
    return dict(_read_default_ai_config(DEFAULT_AI_CONFIG_FILE))


def clear_ai_catalog_cache() -> None:
    global _DEFAULT_AI_CONFIG_SIGNATURE, _DEFAULT_AI_CONFIG_CACHE
    _DEFAULT_AI_CONFIG_SIGNATURE = None
    _DEFAULT_AI_CONFIG_CACHE = None
