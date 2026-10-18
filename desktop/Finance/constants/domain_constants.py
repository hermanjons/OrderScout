from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from Core.processors.catalog import currency_options
from Finance.processors.catalog import (
    finance_builtin_cost_item_keys as _finance_builtin_cost_item_keys,
    finance_builtin_cost_item_records as _finance_builtin_cost_item_records,
)
from Logistics.constants.catalog_constants import default_cargo_tariff_records


FINANCE_INCREMENTAL_OVERLAP_MINUTES = 10
FINANCE_BACKFILL_EMPTY_WINDOW_THRESHOLD = 6
FINANCE_BACKFILL_MAX_YEARS = 5
FINANCE_FETCH_ACCOUNT_CONCURRENCY = 4
FINANCE_SYNC_STAGE_CONCURRENCY = 4
FINANCE_SYNC_CARGO_CONCURRENCY = 6
FINANCE_TRANSACTION_UNIQUE_FIELDS = ["serviceKey", "api_account_id", "recordId", "transactionDate"]
FINANCE_CARGO_ITEM_UNIQUE_FIELDS = ["api_account_id", "invoiceSerialNumber", "parcelUniqueId", "shipmentPackageType"]

FINANCE_COST_VALUE_TYPE_OPTIONS = [
    ("Sayısal", "numeric"),
    ("Yüzdesel", "percentage"),
]
FINANCE_COST_MATCH_MODE_OPTIONS = [
    ("Manuel", "manual"),
    ("Yarı Otomatik", "semi_automatic"),
    ("Otomatik", "automatic"),
]
FINANCE_CURRENCY_OPTIONS = tuple(currency_options())
FINANCE_COST_SOURCE_DEFINITIONS: dict[str, dict[str, object]] = {
    "manual_value": {
        "label": "Manuel Değer",
        "requires_amount": True,
        "enabled": True,
    },
    "builtin_resolver": {
        "label": "Kural Tabanlı",
        "requires_amount": False,
        "enabled": True,
    },
    "db_field": {
        "label": "Veri Alanı",
        "requires_amount": False,
        "enabled": True,
    },
    "formula": {
        "label": "Formül",
        "requires_amount": False,
        "enabled": False,
    },
    "agent_tool": {
        "label": "Agent Aracı",
        "requires_amount": False,
        "enabled": False,
    },
}
FINANCE_LEGACY_MATCH_MODE_TO_SOURCE_TYPE = {
    "manual": "manual_value",
    "fixed": "manual_value",
    "per_order": "manual_value",
    "percentage": "manual_value",
    "per_unit": "manual_value",
    "per_package": "manual_value",
    "per_minute": "manual_value",
    "automatic": "builtin_resolver",
    "tariff_lookup": "builtin_resolver",
    "semi_automatic": "builtin_resolver",
}
FINANCE_SOURCE_TYPE_TO_LEGACY_MATCH_MODE = {
    "manual_value": "manual",
    "builtin_resolver": "automatic",
    "db_field": "manual",
    "formula": "manual",
    "agent_tool": "manual",
}
FINANCE_BUILTIN_COST_ITEM_RECORDS = tuple(_finance_builtin_cost_item_records())
FINANCE_BUILTIN_COST_ITEM_KEYS = _finance_builtin_cost_item_keys()
FINANCE_CARGO_TARIFFS_DEFAULT_RECORDS = tuple(default_cargo_tariff_records())


def finance_builtin_cost_item_records(path: str | Path | None = None) -> tuple[dict[str, Any], ...]:
    if path not in (None, ""):
        return tuple(_finance_builtin_cost_item_records(path))
    return tuple(dict(row or {}) for row in FINANCE_BUILTIN_COST_ITEM_RECORDS)


def finance_cargo_tariff_default_records(path: str | Path | None = None) -> tuple[dict[str, Any], ...]:
    if path not in (None, ""):
        return tuple(default_cargo_tariff_records(path))
    return tuple(dict(row or {}) for row in FINANCE_CARGO_TARIFFS_DEFAULT_RECORDS)


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def _build_finance_cost_rule_definitions() -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    for row in FINANCE_BUILTIN_COST_ITEM_RECORDS:
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


FINANCE_COST_RULE_DEFINITIONS = _build_finance_cost_rule_definitions()


def normalize_finance_cost_rule_key(value: Any, *, fallback: str = "") -> str:
    key = _compact_text(value)
    if key in FINANCE_COST_RULE_DEFINITIONS:
        return key
    fallback_key = _compact_text(fallback)
    if fallback_key in FINANCE_COST_RULE_DEFINITIONS:
        return fallback_key
    return ""


def finance_cost_rule_exists(rule_key: Any) -> bool:
    return normalize_finance_cost_rule_key(rule_key) != ""


def finance_cost_rule_definition(rule_key: Any) -> dict[str, Any]:
    key = normalize_finance_cost_rule_key(rule_key)
    payload = dict(FINANCE_COST_RULE_DEFINITIONS.get(key) or {})
    return deepcopy(payload) if payload else {}


def finance_cost_rule_label(rule_key: Any) -> str:
    key = normalize_finance_cost_rule_key(rule_key)
    payload = FINANCE_COST_RULE_DEFINITIONS.get(key) or {}
    return str(payload.get("label") or key or "-")

__all__ = [
    "FINANCE_BACKFILL_EMPTY_WINDOW_THRESHOLD",
    "FINANCE_BACKFILL_MAX_YEARS",
    "FINANCE_BUILTIN_COST_ITEM_KEYS",
    "FINANCE_BUILTIN_COST_ITEM_RECORDS",
    "FINANCE_CARGO_TARIFFS_DEFAULT_RECORDS",
    "FINANCE_CARGO_ITEM_UNIQUE_FIELDS",
    "FINANCE_COST_MATCH_MODE_OPTIONS",
    "FINANCE_COST_RULE_DEFINITIONS",
    "FINANCE_COST_SOURCE_DEFINITIONS",
    "FINANCE_COST_VALUE_TYPE_OPTIONS",
    "FINANCE_CURRENCY_OPTIONS",
    "FINANCE_FETCH_ACCOUNT_CONCURRENCY",
    "FINANCE_INCREMENTAL_OVERLAP_MINUTES",
    "FINANCE_LEGACY_MATCH_MODE_TO_SOURCE_TYPE",
    "FINANCE_SOURCE_TYPE_TO_LEGACY_MATCH_MODE",
    "FINANCE_SYNC_CARGO_CONCURRENCY",
    "FINANCE_SYNC_STAGE_CONCURRENCY",
    "FINANCE_TRANSACTION_UNIQUE_FIELDS",
    "finance_builtin_cost_item_records",
    "finance_cargo_tariff_default_records",
    "finance_cost_rule_definition",
    "finance_cost_rule_exists",
    "finance_cost_rule_label",
    "normalize_finance_cost_rule_key",
]
