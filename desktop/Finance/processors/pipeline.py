from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from Finance.constants.domain_constants import (
    FINANCE_COST_SOURCE_DEFINITIONS,
    FINANCE_LEGACY_MATCH_MODE_TO_SOURCE_TYPE,
    FINANCE_SOURCE_TYPE_TO_LEGACY_MATCH_MODE,
)


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _normalize_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return dict(value)
    return None


def _positive_int_or_none(value: Any) -> int | None:
    try:
        parsed = int(value)
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _cargo_provider_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    provider_id = _positive_int_or_none(
        payload.get("cargoProviderId")
        if "cargoProviderId" in payload
        else payload.get("cargo_provider_id")
    )
    provider_code = _compact_text(
        payload.get("cargoProviderCode")
        if "cargoProviderCode" in payload
        else payload.get("cargo_provider_code")
    ).upper()
    provider_name = _compact_text(
        payload.get("cargoProviderName")
        if "cargoProviderName" in payload
        else payload.get("cargo_provider_name")
    )

    metadata: dict[str, Any] = {}
    if provider_id is not None:
        metadata["cargoProviderId"] = provider_id
    if provider_code:
        metadata["cargoProviderCode"] = provider_code
    if provider_name:
        metadata["cargoProviderName"] = provider_name
    return metadata


def _normalize_source_type_list(values: Any) -> list[str]:
    out: list[str] = []
    for raw in list(values or []):
        source_type = normalize_cost_source_type(raw, fallback="")
        if source_type and source_type not in out:
            out.append(source_type)
    return out


def _builtin_resolver_key(
    source_config: dict[str, Any] | None,
    *,
    cost_key: Any = None,
    card: dict[str, Any] | None = None,
) -> str:
    payload = dict(source_config or {})
    for key in ("resolverKey", "resolver_key", "ruleKey", "rule_key"):
        value = _compact_text(payload.get(key))
        if value:
            return value

    card_payload = dict(card or {})
    for key in ("defaultRuleKey", "ruleKey", "rule_key", "defaultResolverKey", "resolverKey", "resolver_key"):
        value = _compact_text(card_payload.get(key))
        if value:
            return value

    if _compact_text(cost_key).casefold() == "kargo":
        return "cargo_amount_matcher"
    return ""


def cost_source_type_label(source_type: Any) -> str:
    clean = normalize_cost_source_type(source_type, fallback="")
    return str((FINANCE_COST_SOURCE_DEFINITIONS.get(clean) or {}).get("label") or clean or "-")


def normalize_cost_source_type(value: Any, *, fallback: str = "manual_value") -> str:
    raw = _compact_text(value).casefold()
    if raw in FINANCE_COST_SOURCE_DEFINITIONS:
        return raw
    legacy = FINANCE_LEGACY_MATCH_MODE_TO_SOURCE_TYPE.get(raw)
    if legacy:
        return legacy
    return _compact_text(fallback).casefold() or "manual_value"


def source_type_to_legacy_match_mode(source_type: Any, *, fallback: str = "manual") -> str:
    normalized = normalize_cost_source_type(source_type, fallback="")
    return FINANCE_SOURCE_TYPE_TO_LEGACY_MATCH_MODE.get(normalized, _compact_text(fallback) or "manual")


def normalize_cost_source_config(
    source_type: Any,
    source_config: Any,
    *,
    cost_key: Any = None,
    card: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    normalized_type = normalize_cost_source_type(source_type)
    payload = _normalize_dict(source_config) or {}
    cargo_provider_meta = _cargo_provider_metadata(payload)

    if normalized_type == "manual_value":
        amount = _optional_float(
            payload.get("amount")
            if "amount" in payload
            else payload.get("value")
        )
        if amount is None:
            return None
        normalized = {"amount": amount}
        normalized.update(cargo_provider_meta)
        return normalized

    if normalized_type == "builtin_resolver":
        resolver_key = _builtin_resolver_key(payload, cost_key=cost_key, card=card)
        if not resolver_key:
            return None
        normalized = dict(payload)
        normalized["ruleKey"] = resolver_key
        normalized.pop("resolverKey", None)
        normalized.pop("resolver_key", None)
        normalized.update(cargo_provider_meta)
        return normalized

    if normalized_type == "db_field":
        field_path = ""
        for key in ("fieldPath", "field_path", "path", "sourceField"):
            field_path = _compact_text(payload.get(key))
            if field_path:
                break
        if not field_path:
            return None
        normalized = dict(payload)
        normalized["fieldPath"] = field_path
        if "label" in normalized and not _compact_text(normalized.get("label")):
            normalized.pop("label", None)
        normalized.update(cargo_provider_meta)
        return normalized

    if normalized_type == "formula":
        formula = ""
        for key in ("formula", "expression"):
            formula = _compact_text(payload.get(key))
            if formula:
                break
        if not formula:
            return None
        normalized = dict(payload)
        normalized["formula"] = formula
        normalized.update(cargo_provider_meta)
        return normalized

    if normalized_type == "agent_tool":
        tool_name = ""
        for key in ("tool", "toolName", "agentTool"):
            tool_name = _compact_text(payload.get(key))
            if tool_name:
                break
        if not tool_name:
            return None
        normalized = dict(payload)
        normalized["tool"] = tool_name
        normalized.update(cargo_provider_meta)
        return normalized

    return _normalize_dict(payload)


def normalize_finance_cost_card_source_metadata(row: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(row or {})
    cost_key = _compact_text(payload.get("costKey"))

    supported_source_types = _normalize_source_type_list(payload.get("supportedSourceTypes"))
    default_source_type = normalize_cost_source_type(
        payload.get("defaultSourceType") or payload.get("defaultMatchMode"),
        fallback="manual_value",
    )
    default_source_config = normalize_cost_source_config(
        default_source_type,
        payload.get("defaultSourceConfig"),
        cost_key=cost_key,
        card=payload,
    )

    if not supported_source_types:
        supported_source_types = ["manual_value"]
        if default_source_type == "builtin_resolver":
            supported_source_types.append("builtin_resolver")

    if default_source_type not in supported_source_types:
        supported_source_types.insert(0, default_source_type)

    return {
        "supportedSourceTypes": supported_source_types,
        "defaultSourceType": default_source_type,
        "defaultSourceConfig": deepcopy(default_source_config) if isinstance(default_source_config, dict) else None,
    }


def default_source_binding_for_cost_card(
    card: dict[str, Any] | None,
    *,
    cost_key: Any = None,
) -> tuple[str, dict[str, Any] | None]:
    payload = dict(card or {})
    metadata = normalize_finance_cost_card_source_metadata(
        {**payload, "costKey": _compact_text(cost_key) or _compact_text(payload.get("costKey"))}
    )
    return metadata["defaultSourceType"], deepcopy(metadata.get("defaultSourceConfig"))
