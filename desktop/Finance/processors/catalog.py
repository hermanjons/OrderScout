from __future__ import annotations

import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

from Finance.constants.paths import FINANCE_COST_ITEMS_DEFAULT_FILE

_builtin_cost_items_signature: tuple[str, int, int] | None = None
_builtin_cost_items_cache: list[dict[str, Any]] | None = None


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def _read_cost_items_file(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8-sig").strip()
        if not raw:
            return []
        payload = json.loads(raw)
    except Exception:
        return []
    records = payload.get("records") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        return []
    return [dict(row) for row in records if isinstance(row, dict)]


def _read_builtin_cost_items() -> list[dict[str, Any]]:
    global _builtin_cost_items_signature, _builtin_cost_items_cache

    path = FINANCE_COST_ITEMS_DEFAULT_FILE
    if not path.exists():
        _builtin_cost_items_signature = None
        _builtin_cost_items_cache = []
        return []

    stat = path.stat()
    signature = (str(path), int(stat.st_mtime_ns), int(stat.st_size))
    if _builtin_cost_items_cache is not None and _builtin_cost_items_signature == signature:
        return [dict(row) for row in _builtin_cost_items_cache]

    out = _read_cost_items_file(path)
    _builtin_cost_items_signature = signature
    _builtin_cost_items_cache = [dict(row) for row in out]
    return [dict(row) for row in out]


def finance_builtin_cost_item_records(path: str | Path | None = None) -> list[dict[str, Any]]:
    if path not in (None, ""):
        return _read_cost_items_file(Path(path))
    return [dict(row) for row in _read_builtin_cost_items()]


def finance_builtin_cost_item_keys() -> tuple[str, ...]:
    keys: list[str] = []
    seen: set[str] = set()
    for row in _read_builtin_cost_items():
        cost_key = _compact_text(row.get("costKey"))
        if not cost_key:
            continue
        folded = cost_key.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        keys.append(cost_key)
    return tuple(keys)


@lru_cache(maxsize=1)
def _finance_cost_rule_registry() -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    for row in _read_builtin_cost_items():
        source_type = _compact_text(row.get("defaultSourceType")).casefold()
        source_config = dict(row.get("defaultSourceConfig") or {}) or {}
        if source_type != "builtin_resolver":
            continue
        rule_key = _compact_text(source_config.get("ruleKey"))
        if not rule_key:
            continue
        registry.setdefault(
            rule_key,
            {
                "key": rule_key,
                "label": _compact_text(row.get("name")) or rule_key,
                "description": _compact_text(row.get("description")),
                "costKey": _compact_text(row.get("costKey")) or None,
                "supportedPlatforms": list(row.get("supportedPlatforms") or []),
                "defaultSourceConfig": dict(source_config),
            },
        )
    return registry


def normalize_finance_cost_rule_key(value: Any, *, fallback: str = "") -> str:
    key = _compact_text(value)
    if key in _finance_cost_rule_registry():
        return key
    fallback_key = _compact_text(fallback)
    if fallback_key in _finance_cost_rule_registry():
        return fallback_key
    return ""


def finance_cost_rule_exists(rule_key: Any) -> bool:
    return normalize_finance_cost_rule_key(rule_key) != ""


def finance_cost_rule_definition(rule_key: Any) -> dict[str, Any]:
    key = normalize_finance_cost_rule_key(rule_key)
    payload = dict(_finance_cost_rule_registry().get(key) or {})
    return deepcopy(payload) if payload else {}


def finance_cost_rule_label(rule_key: Any) -> str:
    key = normalize_finance_cost_rule_key(rule_key)
    payload = _finance_cost_rule_registry().get(key) or {}
    return str(payload.get("label") or key or "-")


def finance_cost_rule_refresh() -> None:
    global _builtin_cost_items_signature, _builtin_cost_items_cache
    _builtin_cost_items_signature = None
    _builtin_cost_items_cache = None
    _finance_cost_rule_registry.cache_clear()
