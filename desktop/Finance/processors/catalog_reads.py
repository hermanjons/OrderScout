"""Finance cost-card and cargo-tariff reads shared by manual and domain operations.

Builtin acceptance, editable overrides, source identities and default-file cache
state are owned here. Public readers retain explicit storage-path options.
"""
from __future__ import annotations

from collections import defaultdict
import json
from datetime import date, datetime
from pathlib import Path
import re
from typing import Any
from sqlmodel import Session, select
from Finance.processors.pipeline import cost_source_type_label, normalize_finance_cost_card_source_metadata
from Core.utils.model_utils import get_engine
from Feedback.processors.pipeline import Result, map_error_to_message
from Logistics.constants.catalog_constants import builtin_cargo_provider_records, cargo_provider_code_for_source_id, cargo_provider_records, cargo_provider_name_for_code, cargo_provider_source_id_for_code
from Core.db.models import SOURCE_TYPE_BUILTIN, SOURCE_TYPE_USER, coerce_source_id
from Marketplaces.constants.catalog_constants import builtin_marketplace_records, canonical_platform_code, marketplace_code_for_source_id, marketplace_records, marketplace_source_id_for_code, platform_label_for_code
from Finance.constants.domain_constants import FINANCE_COST_MATCH_MODE_OPTIONS, FINANCE_COST_VALUE_TYPE_OPTIONS, FINANCE_CURRENCY_OPTIONS, finance_builtin_cost_item_records, finance_cargo_tariff_default_records, finance_cost_rule_exists, finance_cost_rule_label, normalize_finance_cost_rule_key
from Finance.constants.trendyol.constants import FINANCE_PLATFORM_TRENDYOL, TZ_GMT3
from Finance.constants.paths import FINANCE_CARGO_TARIFFS_DEFAULT_FILE, FINANCE_CARGO_TARIFFS_FILE, FINANCE_COST_ITEMS_DEFAULT_FILE
from Finance.models.trendyol.models import FinanceCostItem, FinanceCostItemMarketplaceLink
from Logistics.models.models import LogisticsCargoTariff
from settings import DB_NAME


_finance_cargo_tariffs_default_cache_signature: tuple[str, int, int] | None = None
_finance_cargo_tariffs_default_cache_rows: list[dict[str, Any]] | None = None


def _parse_epoch_ms(value: Any) -> int | None:
    if value in (None, "", 0):
        return None
    try:
        if isinstance(value, datetime):
            dt = value if value.tzinfo is not None else value.replace(tzinfo=TZ_GMT3)
            return int(dt.timestamp() * 1000)
        if isinstance(value, date):
            dt = datetime(value.year, value.month, value.day, tzinfo=TZ_GMT3)
            return int(dt.timestamp() * 1000)
        if isinstance(value, (int, float)):
            raw = int(value)
            if raw <= 0:
                return None
            return raw if raw > 10**12 else raw * 1000
        text = str(value).strip()
        if not text:
            return None
        if text.isdigit():
            return _parse_epoch_ms(int(text))
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ_GMT3)
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def _source_id_or_none(value: Any) -> int | None:
    return coerce_source_id(value)


def _db_pk_or_none(row: dict[str, Any] | None) -> int | None:
    payload = dict(row or {})
    try:
        parsed = int(payload.get("dbPk") or 0)
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _runtime_record_pk(row: dict[str, Any] | None, *, fallback: int=0) -> int:
    payload = dict(row or {})
    db_pk = _db_pk_or_none(payload)
    if db_pk is not None:
        return db_pk
    source_id = _source_id_or_none(payload.get("sourceId") or payload.get("source_id"))
    if source_id is not None:
        return source_id
    try:
        raw_pk = int(payload.get("pk") or 0)
    except Exception:
        raw_pk = 0
    if raw_pk > 0:
        return raw_pk
    return int(fallback or 0)


def _safe_int_id(value: Any) -> int | None:
    try:
        parsed = int(value)
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _format_money(value: Any) -> str:
    try:
        return f"{float(value):,.2f}".replace(",", ".")
    except Exception:
        return "0.00"


def _format_compact_number(value: Any) -> str:
    numeric = _optional_float(value)
    if numeric is None:
        return ""
    text = f"{numeric:.2f}" if abs(numeric - round(numeric)) > 1e-9 else f"{int(round(numeric))}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _normalize_finance_currency(value: Any, *, fallback: str='TRY') -> str:
    code = _compact_text(value).upper()
    if code in FINANCE_CURRENCY_OPTIONS:
        return code
    fallback_code = _compact_text(fallback).upper()
    if fallback_code in FINANCE_CURRENCY_OPTIONS:
        return fallback_code
    return "TRY"


def _normalize_editable_fields(values: Any) -> list[str]:
    raw_values = values
    if isinstance(raw_values, str):
        raw_values = [part for part in raw_values.split(",") if str(part).strip()]
    out: list[str] = []
    for raw in list(raw_values or []):
        key = _compact_text(raw)
        if key and key not in out:
            out.append(key)
    return out


def _system_rule_key_for_row(row: dict[str, Any] | None) -> str:
    payload = dict(row or {})
    source_type = _compact_text(payload.get("defaultSourceType")).casefold()
    source_config = dict(payload.get("defaultSourceConfig") or {}) or {}
    if source_type != "builtin_resolver":
        return ""
    rule_key = normalize_finance_cost_rule_key(source_config.get("ruleKey"))
    return rule_key if finance_cost_rule_exists(rule_key) else ""


def _json_load(value: Any, *, default: Any) -> Any:
    try:
        if isinstance(value, str):
            parsed = json.loads(value)
            if parsed is not None:
                return parsed
    except Exception:
        pass
    return default


def _resolve_finance_cost_items_default_path(*, default_storage_path: str | Path | None=None, storage_path: str | Path | None=None) -> Path | None:
    if default_storage_path not in (None, ""):
        return Path(default_storage_path)
    return FINANCE_COST_ITEMS_DEFAULT_FILE


def _read_json_payload(path: Path) -> Any:
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8-sig").strip()
    if not raw:
        return None
    return json.loads(raw)


def _normalize_cost_value_type(row: dict[str, Any]) -> str:
    value_type = _compact_text(row.get("valueType")).casefold()
    if value_type in {"numeric", "percentage"}:
        return value_type
    legacy = _compact_text(row.get("calculationType")).casefold()
    if legacy == "percentage":
        return "percentage"
    return "numeric"


def _normalize_cost_default_match_mode(row: dict[str, Any]) -> str:
    mode = _compact_text(row.get("defaultMatchMode")).casefold()
    if mode in {"manual", "semi_automatic", "automatic"}:
        return mode
    legacy = _compact_text(row.get("calculationType")).casefold()
    if legacy == "automatic":
        return "automatic"
    return "manual"


def _cost_value_type_label(value_type_key: Any) -> str:
    clean = _compact_text(value_type_key)
    for label, key in FINANCE_COST_VALUE_TYPE_OPTIONS:
        if key == clean:
            return label
    return clean or "-"


def _cost_default_match_mode_label(mode_key: Any) -> str:
    clean = _compact_text(mode_key)
    for label, key in FINANCE_COST_MATCH_MODE_OPTIONS:
        if key == clean:
            return label
    return clean or "-"


def _normalize_finance_cost_item_rows(records: list[dict[str, Any]] | None, *, is_builtin: bool=False) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, row in enumerate(list(records or []), start=1):
        if not isinstance(row, dict):
            continue
        pk = _runtime_record_pk(row, fallback=idx)
        db_pk = _db_pk_or_none(row)
        source_type = _compact_text(row.get("sourceType") or row.get("source_type")).lower()
        if source_type not in {SOURCE_TYPE_BUILTIN, SOURCE_TYPE_USER}:
            source_type = SOURCE_TYPE_BUILTIN if is_builtin else SOURCE_TYPE_USER
        source_id = _source_id_or_none(row.get("sourceId") or row.get("source_id"))
        if source_id is None:
            source_id = idx
        value_type = _normalize_cost_value_type(row)
        default_match_mode = _normalize_cost_default_match_mode(row)
        is_vat_included = bool(row.get("isVatIncluded", True))
        vat_rate = _optional_float(row.get("vatRate"))
        source_meta = normalize_finance_cost_card_source_metadata(
            {
                **dict(row or {}),
                "costKey": _compact_text(row.get("costKey")),
                "defaultMatchMode": default_match_mode,
            }
        )
        out.append(
            {
                "pk": pk if pk > 0 else idx,
                "dbPk": db_pk,
                "costKey": _compact_text(row.get("costKey")),
                "name": _compact_text(row.get("name")),
                "description": _compact_text(row.get("description")),
                "valueType": value_type,
                "defaultMatchMode": default_match_mode,
                "defaultAmount": _optional_float(row.get("defaultAmount")),
                "currency": _normalize_finance_currency(row.get("currency")),
                "isVatIncluded": is_vat_included,
                "vatRate": vat_rate,
                "supportedPlatformSourceIds": _normalize_supported_platform_source_ids(
                    row.get("supportedPlatformSourceIds")
                    or row.get("supported_platform_source_ids")
                    or row.get("supportedPlatforms"),
                    db_name=None,
                ),
                "supportedPlatforms": _platform_codes_for_source_ids(
                    row.get("supportedPlatformSourceIds")
                    or row.get("supported_platform_source_ids")
                    or row.get("supportedPlatforms"),
                    db_name=None,
                ),
                "supportedSourceTypes": list(source_meta.get("supportedSourceTypes") or []),
                "defaultSourceType": _compact_text(source_meta.get("defaultSourceType")),
                "defaultSourceConfig": dict(source_meta.get("defaultSourceConfig") or {}) or None,
                "editableFields": _normalize_editable_fields(row.get("editableFields")),
                "isActive": bool(row.get("isActive", True)),
                "createdAt": _compact_text(row.get("createdAt")),
                "updatedAt": _compact_text(row.get("updatedAt")),
                "isBuiltin": bool(row.get("isBuiltin", is_builtin)),
                "sourceType": source_type,
                "sourceId": source_id,
                "source_id": source_id,
            }
        )
    return out


def _normalize_supported_platform_source_ids(values: Any, *, db_name: str | None=None) -> list[int]:
    raw_values = values
    if isinstance(raw_values, str):
        raw_values = [part for part in raw_values.split(",") if str(part).strip()]
    out: list[int] = []
    for raw in list(raw_values or []):
        source_id = _source_id_or_none(raw)
        if source_id is None:
            source_id = marketplace_source_id_for_code(raw, db_name=db_name)
        if source_id is None or source_id in out:
            continue
        out.append(source_id)
    return out


def _platform_codes_for_source_ids(source_ids: Any, *, db_name: str | None=None) -> list[str]:
    out: list[str] = []
    for source_id in _normalize_supported_platform_source_ids(source_ids, db_name=db_name):
        code = marketplace_code_for_source_id(source_id, db_name=db_name)
        if code and code not in out:
            out.append(code)
    return out


def _accepted_finance_cost_item_platform_source_ids(*, db_name: str | None=None) -> set[int]:
    return {
        int(source_id)
        for row in marketplace_records(db_name=db_name)
        for source_id in [coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id"))]
        if source_id is not None
    }


def _load_finance_cost_items_user_payload(*, storage_path: str | Path | None=None, db_name: str | None=None) -> dict[str, Any]:
    return _load_finance_cost_items_user_payload_db(db_name=db_name)


def _load_finance_cost_items_default_raw(*, default_storage_path: str | Path | None=None, storage_path: str | Path | None=None, db_name: str | None=None) -> list[dict[str, Any]]:
    path = _resolve_finance_cost_items_default_path(
        default_storage_path=default_storage_path,
        storage_path=storage_path,
    )
    if path is None:
        return []
    records = list(finance_builtin_cost_item_records(path))
    normalized = _normalize_finance_cost_item_rows(records, is_builtin=True)
    if storage_path in (None, ""):
        accepted_platforms = _accepted_finance_cost_item_platform_source_ids(db_name=db_name)
        normalized = [
            dict(row or {})
            for row in normalized
            if (
                _normalize_supported_platform_source_ids((row or {}).get("supportedPlatformSourceIds"), db_name=db_name)
                and set(
                    _normalize_supported_platform_source_ids((row or {}).get("supportedPlatformSourceIds"), db_name=db_name)
                ).issubset(accepted_platforms)
            )
        ]
    return normalized


def _finance_cost_item_model_to_row(row: FinanceCostItem, *, supported_platform_source_ids: list[int] | None=None, db_name: str | None=None) -> dict[str, Any]:
    normalized_source_ids = _normalize_supported_platform_source_ids(
        supported_platform_source_ids
        if supported_platform_source_ids is not None
        else _json_load(getattr(row, "supportedPlatformSourceIdsJson", "[]"), default=[]) or [],
        db_name=db_name,
    )
    return {
        "pk": int(getattr(row, "pk", 0) or 0),
        "dbPk": int(getattr(row, "pk", 0) or 0),
        "costKey": _compact_text(getattr(row, "costKey", "")),
        "name": _compact_text(getattr(row, "name", "")),
        "description": _compact_text(getattr(row, "description", "")) or None,
        "valueType": _compact_text(getattr(row, "valueType", "")),
        "defaultMatchMode": _compact_text(getattr(row, "defaultMatchMode", "")),
        "defaultAmount": _optional_float(getattr(row, "defaultAmount", None)),
        "currency": _normalize_finance_currency(getattr(row, "currency", "TRY")),
        "isVatIncluded": bool(getattr(row, "isVatIncluded", True)),
        "vatRate": _optional_float(getattr(row, "vatRate", None)),
        "supportedPlatformSourceIds": normalized_source_ids,
        "supportedPlatforms": _platform_codes_for_source_ids(normalized_source_ids, db_name=db_name),
        "supportedSourceTypes": list(
            _json_load(getattr(row, "supportedSourceTypesJson", "[]"), default=[]) or []
        ),
        "defaultSourceType": _compact_text(getattr(row, "defaultSourceType", "")),
        "defaultSourceConfig": dict(
            _json_load(getattr(row, "defaultSourceConfigJson", "{}"), default={}) or {}
        ) or None,
        "isActive": bool(getattr(row, "isActive", True)),
        "isDeleted": bool(getattr(row, "isDeleted", False)),
        "createdAt": _compact_text(getattr(row, "createdAt", "")),
        "updatedAt": _compact_text(getattr(row, "updatedAt", "")),
        "sourceType": _compact_text(getattr(row, "sourceType", "")) or None,
        "sourceId": _source_id_or_none(getattr(row, "sourceId", None)),
        "source_id": _source_id_or_none(getattr(row, "sourceId", None)),
    }


def _load_finance_cost_items_user_payload_db(*, db_name: str | None=None) -> dict[str, Any]:
    engine = get_engine(db_name or DB_NAME)
    with Session(engine) as session:
        rows = session.exec(select(FinanceCostItem).order_by(FinanceCostItem.pk.asc())).all() or []
        link_rows = session.exec(
            select(FinanceCostItemMarketplaceLink).order_by(
                FinanceCostItemMarketplaceLink.cost_item_id.asc(),
                FinanceCostItemMarketplaceLink.marketplace_id.asc(),
            )
        ).all() or []
    platform_source_ids_by_cost_item_id: dict[int, list[int]] = defaultdict(list)
    marketplace_source_id_by_pk = {
        int((row or {}).get("pk") or 0): coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id"))
        for row in marketplace_records(db_name=db_name)
        if int((row or {}).get("pk") or 0) > 0
    }
    for link_row in link_rows:
        cost_item_id = int(getattr(link_row, "cost_item_id", 0) or 0)
        marketplace_id = int(getattr(link_row, "marketplace_id", 0) or 0)
        if cost_item_id <= 0 or marketplace_id <= 0:
            continue
        source_id = marketplace_source_id_by_pk.get(marketplace_id)
        if source_id is None:
            continue
        platform_source_ids_by_cost_item_id[cost_item_id].append(source_id)
    deleted_keys: list[str] = []
    records: list[dict[str, Any]] = []
    for model_row in rows:
        payload = _finance_cost_item_model_to_row(
            model_row,
            supported_platform_source_ids=platform_source_ids_by_cost_item_id.get(int(getattr(model_row, "pk", 0) or 0), []),
            db_name=db_name,
        )
        cost_key = _compact_text(payload.get("costKey"))
        if not cost_key:
            continue
        if bool(payload.get("isDeleted")):
            deleted_keys.append(cost_key)
            continue
        records.append(payload)
    return {
        "records": _normalize_finance_cost_item_rows(records, is_builtin=False),
        "deletedKeys": [_compact_text(key) for key in deleted_keys if _compact_text(key)],
    }


def _load_finance_cost_items_raw(*, storage_path: str | Path | None=None, db_name: str | None=None, default_storage_path: str | Path | None=None) -> list[dict[str, Any]]:
    builtin_rows = _load_finance_cost_items_default_raw(
        default_storage_path=default_storage_path,
        storage_path=storage_path,
        db_name=db_name,
    )
    user_payload = _load_finance_cost_items_user_payload(storage_path=storage_path, db_name=db_name)
    user_rows = list(user_payload.get("records") or [])
    accepted_builtin_keys = {
        _compact_text(row.get("costKey")).casefold()
        for row in user_rows
        if _compact_text(row.get("costKey"))
    }
    deleted_keys = {
        _compact_text(key).casefold()
        for key in list(user_payload.get("deletedKeys") or [])
        if _compact_text(key)
    }

    merged: dict[str, dict[str, Any]] = {}
    builtin_keys: set[str] = set()

    for row in builtin_rows:
        cost_key = _compact_text(row.get("costKey"))
        if not cost_key or cost_key.casefold() in deleted_keys:
            continue
        builtin_keys.add(cost_key.casefold())
        merged[cost_key.casefold()] = {
            **dict(row),
            "isBuiltin": True,
            "isBuiltinAccepted": cost_key.casefold() in accepted_builtin_keys,
        }

    for row in user_rows:
        cost_key = _compact_text(row.get("costKey"))
        if not cost_key or cost_key.casefold() in deleted_keys:
            continue
        payload = dict(row)
        if cost_key.casefold() in builtin_keys:
            merged_row = dict(merged.get(cost_key.casefold()) or {})
            editable_fields = set(_normalize_editable_fields(merged_row.get("editableFields"))) or {"name", "description"}
            if "name" in editable_fields:
                override_name = _compact_text(payload.get("name"))
                if override_name:
                    merged_row["name"] = override_name
            if "description" in editable_fields:
                merged_row["description"] = _compact_text(payload.get("description")) or None
            if "valueType" in editable_fields:
                merged_row["valueType"] = _normalize_cost_value_type(payload)
            if "defaultMatchMode" in editable_fields:
                merged_row["defaultMatchMode"] = _normalize_cost_default_match_mode(payload)
            if "defaultAmount" in editable_fields:
                merged_row["defaultAmount"] = _optional_float(payload.get("defaultAmount"))
            if "currency" in editable_fields:
                merged_row["currency"] = _normalize_finance_currency(payload.get("currency"), fallback=merged_row.get("currency"))
            if "isVatIncluded" in editable_fields:
                merged_row["isVatIncluded"] = bool(payload.get("isVatIncluded", True))
            if "vatRate" in editable_fields:
                merged_row["vatRate"] = _optional_float(payload.get("vatRate"))
            if "supportedPlatforms" in editable_fields:
                merged_row["supportedPlatformSourceIds"] = _normalize_supported_platform_source_ids(
                    payload.get("supportedPlatformSourceIds") or payload.get("supportedPlatforms"),
                    db_name=db_name,
                )
                merged_row["supportedPlatforms"] = _platform_codes_for_source_ids(
                    merged_row.get("supportedPlatformSourceIds"),
                    db_name=db_name,
                )
            if "supportedSourceTypes" in editable_fields:
                merged_row["supportedSourceTypes"] = list(payload.get("supportedSourceTypes") or [])
            if "defaultSourceType" in editable_fields:
                merged_row["defaultSourceType"] = _compact_text(payload.get("defaultSourceType"))
            if "defaultSourceConfig" in editable_fields:
                merged_row["defaultSourceConfig"] = dict(payload.get("defaultSourceConfig") or {}) or None
            if "isActive" in editable_fields:
                merged_row["isActive"] = bool(payload.get("isActive", True))
            if _compact_text(payload.get("createdAt")):
                merged_row["createdAt"] = _compact_text(payload.get("createdAt"))
            if _compact_text(payload.get("updatedAt")):
                merged_row["updatedAt"] = _compact_text(payload.get("updatedAt"))
            merged_row["isBuiltin"] = True
            merged_row["isBuiltinAccepted"] = True
            merged[cost_key.casefold()] = merged_row
            continue
        payload["isBuiltin"] = False
        payload["isBuiltinAccepted"] = True
        merged[cost_key.casefold()] = payload

    return list(merged.values())


def _cost_item_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row or {})
    value_type = _normalize_cost_value_type(payload)
    default_match_mode = _normalize_cost_default_match_mode(payload)
    is_vat_included = bool(payload.get("isVatIncluded", True))
    vat_rate = _optional_float(payload.get("vatRate"))
    default_amount = _optional_float(payload.get("defaultAmount"))
    currency = _normalize_finance_currency(payload.get("currency"))
    source_meta = normalize_finance_cost_card_source_metadata(
        {
            **payload,
            "defaultMatchMode": default_match_mode,
        }
    )
    supported_platform_source_ids = _normalize_supported_platform_source_ids(
        payload.get("supportedPlatformSourceIds") or payload.get("supportedPlatforms")
    )
    supported_platforms = _platform_codes_for_source_ids(supported_platform_source_ids)
    supported_source_types = list(source_meta.get("supportedSourceTypes") or [])
    default_source_type = _compact_text(source_meta.get("defaultSourceType"))
    default_source_config = dict(source_meta.get("defaultSourceConfig") or {}) or None
    system_rule_key = _system_rule_key_for_row(
        {
            **payload,
            "defaultSourceType": default_source_type,
            "defaultSourceConfig": default_source_config,
        }
    )
    if system_rule_key:
        supported_source_types = ["manual_value", "builtin_resolver"]
        default_source_type = "builtin_resolver"
        default_source_config = {"ruleKey": system_rule_key}
    else:
        supported_source_types = ["manual_value"]
        default_source_type = "manual_value"
        default_source_config = None
    if value_type == "percentage":
        default_amount_text = f"%{_format_compact_number(default_amount)}" if default_amount is not None else "-"
        default_amount_label = "Varsayılan Oran"
    else:
        default_amount_text = _format_money(default_amount) if default_amount is not None else "-"
        default_amount_label = "Varsayılan Fiyat"
    amount_mode_text = "KDV dahil" if is_vat_included else "KDV hariç"
    return {
        "pk": int(payload.get("pk") or 0),
        "costKey": _compact_text(payload.get("costKey", "")),
        "name": _compact_text(payload.get("name", "")),
        "description": _compact_text(payload.get("description", "")),
        "valueType": value_type,
        "valueTypeLabel": _cost_value_type_label(value_type),
        "defaultMatchMode": default_match_mode,
        "defaultMatchModeLabel": _cost_default_match_mode_label(default_match_mode),
        "calculationType": value_type,
        "calculationTypeLabel": _cost_value_type_label(value_type),
        "defaultAmount": default_amount,
        "defaultAmountText": default_amount_text,
        "defaultAmountLabel": default_amount_label,
        "currency": currency,
        "isVatIncluded": is_vat_included,
        "amountModeText": amount_mode_text,
        "vatRate": vat_rate,
        "vatRateText": _format_compact_number(vat_rate),
        "supportedPlatforms": supported_platforms,
        "supportedPlatformSourceIds": supported_platform_source_ids,
        "supportedPlatformLabels": [platform_label_for_code(code) or code for code in supported_platforms],
        "supportedPlatformsText": ", ".join(platform_label_for_code(code) or code for code in supported_platforms),
        "supportedSourceTypes": supported_source_types,
        "supportedSourceTypeLabels": [cost_source_type_label(key) for key in supported_source_types],
        "supportedSourceTypesText": ", ".join(cost_source_type_label(key) for key in supported_source_types),
        "defaultSourceType": default_source_type,
        "defaultSourceTypeLabel": cost_source_type_label(default_source_type),
        "defaultSourceConfig": default_source_config,
        "editableFields": _normalize_editable_fields(payload.get("editableFields")),
        "systemRuleKey": system_rule_key or None,
        "systemRuleLabel": finance_cost_rule_label(system_rule_key) if system_rule_key else "",
        "isSystemRuleCard": bool(system_rule_key),
        "isActive": bool(payload.get("isActive", True)),
        "isBuiltin": bool(payload.get("isBuiltin", False)),
        "isBuiltinAccepted": bool(payload.get("isBuiltinAccepted", not bool(payload.get("isBuiltin", False)))),
        "createdAt": _compact_text(payload.get("createdAt", "")),
        "updatedAt": _compact_text(payload.get("updatedAt", "")),
        "sourceType": _compact_text(payload.get("sourceType", "")) or None,
        "sourceId": _source_id_or_none(payload.get("sourceId") or payload.get("source_id")),
        "source_id": _source_id_or_none(payload.get("sourceId") or payload.get("source_id")),
    }


def load_finance_cost_items(*, search_text: str='', calculation_type: str='', active_state: str='', source_state: str='', platform_code: str='', storage_path: str | Path | None=None, db_name: str | None=None, default_storage_path: str | Path | None=None) -> Result:
    try:
        raw_records = _load_finance_cost_items_raw(
            storage_path=storage_path,
            db_name=db_name,
            default_storage_path=default_storage_path,
        )
        records = [_cost_item_to_dict(row) for row in raw_records]
        records.sort(
            key=lambda row: (
                0 if bool(row.get("isActive")) else 1,
                _compact_text(row.get("updatedAt")),
                _compact_text(row.get("name")).casefold(),
            ),
            reverse=False,
        )
        records = sorted(
            records,
            key=lambda row: (
                not bool(row.get("isActive")),
                -_parse_epoch_ms(row.get("updatedAt") or row.get("createdAt") or 0) if _parse_epoch_ms(row.get("updatedAt") or row.get("createdAt") or 0) else 0,
                _compact_text(row.get("name")).casefold(),
            ),
        )
        clean_search = _compact_text(search_text).casefold()
        clean_calc = _compact_text(calculation_type)
        clean_active = _compact_text(active_state).casefold()
        clean_source = _compact_text(source_state).casefold()
        clean_platform_source_id = marketplace_source_id_for_code(platform_code, db_name=db_name)
        if clean_calc.casefold() == "all":
            clean_calc = ""
        if clean_active == "all":
            clean_active = ""
        if clean_source == "all":
            clean_source = ""

        if clean_search:
            records = [
                row
                for row in records
                if clean_search in " ".join(
                    [
                        _compact_text(row.get("name")),
                        _compact_text(row.get("description")),
                        _compact_text(row.get("costKey")),
                        _compact_text(row.get("valueTypeLabel")),
                        _compact_text(row.get("defaultMatchModeLabel")),
                        _compact_text(row.get("currency")),
                        _compact_text(row.get("amountModeText")),
                        _compact_text(row.get("supportedPlatformsText")),
                    ]
                ).casefold()
            ]
        if clean_calc:
            records = [row for row in records if _compact_text(row.get("valueType")) == clean_calc]
        if clean_platform_source_id is not None:
            records = [
                row for row in records
                if clean_platform_source_id in _normalize_supported_platform_source_ids(
                    row.get("supportedPlatformSourceIds"),
                    db_name=db_name,
                )
            ]
        if clean_active == "aktif":
            records = [row for row in records if bool(row.get("isActive"))]
        elif clean_active == "pasif":
            records = [row for row in records if not bool(row.get("isActive"))]
        if clean_source in {"pending", "builtin"}:
            records = [row for row in records if bool(row.get("isBuiltin")) and not bool(row.get("isBuiltinAccepted"))]
        elif clean_source in {"saved", "accepted"}:
            records = [row for row in records if bool(row.get("isBuiltinAccepted"))]

        active_count = sum(1 for row in records if bool(row.get("isActive")))
        return Result.ok(
            "Maliyet kartları yüklendi.",
            close_dialog=False,
            data={
                "records": records,
                "summary_text": f"Toplam kart: {len(records)} | Aktif: {active_count}",
            },
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def _cargo_provider_name_for_code(code: Any, *, platform_code: Any=None, db_name: str | None=None) -> str:
    clean = _compact_text(code).upper()
    if not clean:
        return ""
    return cargo_provider_name_for_code(clean, platform_code=platform_code, db_name=db_name) or clean


def _path_signature(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return (str(path), int(stat.st_mtime_ns), int(stat.st_size))


def _fast_platform_code(value: Any, *, default: str='') -> str:
    text = _compact_text(value).upper()
    if not text:
        return default
    normalized = re.sub(r"[^A-Z0-9]+", "_", text)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or default


def _finance_platform_label_lookup(*, db_name: str | None=None) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for row in builtin_marketplace_records():
        code = canonical_platform_code((row or {}).get("code"))
        label = _compact_text((row or {}).get("label"))
        if code and label:
            lookup[code] = label
    for row in marketplace_records(db_name=db_name):
        code = canonical_platform_code((row or {}).get("code"))
        label = _compact_text((row or {}).get("label"))
        if code and label:
            lookup[code] = label
    return lookup


def _finance_cargo_provider_lookup(*, db_name: str | None=None) -> tuple[dict[tuple[str, str], str], dict[str, str]]:
    by_platform: dict[tuple[str, str], str] = {}
    fallback: dict[str, str] = {}
    for row in cargo_provider_records(db_name=db_name):
        platform_code = canonical_platform_code((row or {}).get("platformCode"))
        provider_code = _compact_text((row or {}).get("cargoProviderCode")).upper()
        provider_name = _compact_text((row or {}).get("cargoProviderName"))
        if not provider_code or not provider_name:
            continue
        if platform_code:
            by_platform[(platform_code, provider_code)] = provider_name
        fallback.setdefault(provider_code, provider_name)
    return by_platform, fallback


def _marketplace_source_maps(*, db_name: str | None=None) -> tuple[dict[int, str], dict[str, int]]:
    code_by_source_id: dict[int, str] = {}
    source_id_by_code: dict[str, int] = {}
    for row in [*builtin_marketplace_records(), *marketplace_records(db_name=db_name)]:
        code = canonical_platform_code((row or {}).get("code"))
        source_id = coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id"))
        if not code or source_id is None:
            continue
        code_by_source_id[int(source_id)] = code
        source_id_by_code.setdefault(code, int(source_id))
    return code_by_source_id, source_id_by_code


def _cargo_provider_source_maps(*, db_name: str | None=None) -> tuple[dict[int, str], dict[tuple[str, str], int], dict[tuple[str, str], str], dict[int, str]]:
    code_by_source_id: dict[int, str] = {}
    source_id_by_key: dict[tuple[str, str], int] = {}
    name_by_key: dict[tuple[str, str], str] = {}
    name_by_source_id: dict[int, str] = {}
    for row in [*builtin_cargo_provider_records(), *cargo_provider_records(db_name=db_name)]:
        platform_code = canonical_platform_code((row or {}).get("platformCode"))
        provider_code = _compact_text((row or {}).get("cargoProviderCode")).upper()
        provider_name = _compact_text((row or {}).get("cargoProviderName"))
        source_id = coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id"))
        if not platform_code or not provider_code:
            continue
        if source_id is not None:
            code_by_source_id[int(source_id)] = provider_code
            source_id_by_key[(platform_code, provider_code)] = int(source_id)
            if provider_name:
                name_by_source_id[int(source_id)] = provider_name
        if provider_name:
            name_by_key[(platform_code, provider_code)] = provider_name
    return code_by_source_id, source_id_by_key, name_by_key, name_by_source_id


def _accepted_cargo_tariff_platform_source_ids(*, db_name: str | None=None) -> set[int]:
    return {
        int(source_id)
        for row in marketplace_records(db_name=db_name)
        for source_id in [coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id"))]
        if source_id is not None
    }


def _accepted_cargo_tariff_provider_source_ids(*, db_name: str | None=None) -> set[int]:
    return {
        int(source_id)
        for row in cargo_provider_records(db_name=db_name)
        for source_id in [coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id"))]
        if source_id is not None
    }


def _resolve_finance_cargo_tariffs_path(*, storage_path: str | Path | None=None, db_name: str | None=None) -> Path:
    if storage_path not in (None, ""):
        return Path(storage_path)
    if db_name not in (None, ""):
        base = Path(str(db_name))
        if base.suffix:
            return base.with_name(f"{base.stem}.finance_cargo_tariffs.json")
        return base / "finance_cargo_tariffs.json"
    return FINANCE_CARGO_TARIFFS_FILE


def _resolve_finance_cargo_tariffs_default_path(*, default_storage_path: str | Path | None=None, storage_path: str | Path | None=None) -> Path | None:
    if default_storage_path not in (None, ""):
        return Path(default_storage_path)
    if storage_path not in (None, ""):
        return None
    return FINANCE_CARGO_TARIFFS_DEFAULT_FILE


def _normalize_finance_cargo_tariff_rows(records: list[dict[str, Any]] | None, *, is_builtin: bool=False, db_name: str | None=None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    provider_name_cache: dict[tuple[str, str], str] = {}
    marketplace_code_by_source_id, marketplace_source_id_by_code = _marketplace_source_maps(db_name=db_name)
    provider_code_by_source_id, provider_source_id_by_key, provider_name_by_key, provider_name_by_source_id = _cargo_provider_source_maps(db_name=db_name)
    for idx, row in enumerate(list(records or []), start=1):
        if not isinstance(row, dict):
            continue
        pk = _runtime_record_pk(row, fallback=idx)
        db_pk = _db_pk_or_none(row)
        source_type = _compact_text(row.get("sourceType") or row.get("source_type")).lower()
        if source_type not in {SOURCE_TYPE_BUILTIN, SOURCE_TYPE_USER}:
            source_type = SOURCE_TYPE_BUILTIN if is_builtin else SOURCE_TYPE_USER
        source_id = _source_id_or_none(row.get("sourceId") or row.get("source_id"))
        if source_id is None:
            source_id = idx
        platform_source_id = coerce_source_id(
            row.get("platformSourceId") or row.get("platform_source_id")
        )
        platform_code = (
            marketplace_code_by_source_id.get(int(platform_source_id or 0), "")
            or _fast_platform_code(row.get("platform"), default=FINANCE_PLATFORM_TRENDYOL)
        )
        platform_source_id = platform_source_id or marketplace_source_id_by_code.get(platform_code)
        provider_source_id = coerce_source_id(
            row.get("cargoProviderSourceId") or row.get("cargo_provider_source_id")
        )
        provider_code = (
            provider_code_by_source_id.get(int(provider_source_id or 0), "")
            or _compact_text(row.get("cargoProviderCode")).upper()
        )
        provider_source_id = provider_source_id or provider_source_id_by_key.get((platform_code, provider_code))
        provider_name = _compact_text(row.get("cargoProviderName"))
        if not provider_name and provider_source_id is not None:
            provider_name = provider_name_by_source_id.get(int(provider_source_id), "")
        if not provider_name and provider_code:
            provider_name = provider_name_cache.get((platform_code, provider_code), "")
        if not provider_name and provider_code:
            provider_name = (
                provider_name_by_key.get((platform_code, provider_code))
                or _cargo_provider_name_for_code(provider_code, platform_code=platform_code, db_name=db_name)
                or ""
            )
            provider_name_cache[(platform_code, provider_code)] = provider_name
        is_vat_included = bool(row.get("isVatIncluded", True))
        out.append(
            {
                "pk": pk if pk > 0 else idx,
                "dbPk": db_pk,
                "tariffKey": _compact_text(row.get("tariffKey")),
                "name": _compact_text(row.get("name")),
                "description": _compact_text(row.get("description")),
                "platform": platform_code,
                "platformCode": platform_code,
                "platformSourceId": platform_source_id,
                "platform_source_id": platform_source_id,
                "cargoProviderCode": provider_code,
                "cargoProviderSourceId": provider_source_id,
                "cargo_provider_source_id": provider_source_id,
                "cargoProviderName": provider_name,
                "minDesi": _optional_float(row.get("minDesi")),
                "maxDesi": _optional_float(row.get("maxDesi")),
                "minSalePrice": _optional_float(row.get("minSalePrice")),
                "maxSalePrice": _optional_float(row.get("maxSalePrice")),
                "amount": _optional_float(row.get("amount")),
                "currency": _compact_text(row.get("currency")) or "TRY",
                "isVatIncluded": is_vat_included,
                "vatRate": None if is_vat_included else _optional_float(row.get("vatRate")),
                "isActive": bool(row.get("isActive", True)),
                "createdAt": _compact_text(row.get("createdAt")),
                "updatedAt": _compact_text(row.get("updatedAt")),
                "isBuiltin": bool(row.get("isBuiltin", is_builtin)),
                "sourceType": source_type,
                "sourceId": source_id,
                "source_id": source_id,
            }
        )
    return out


def _load_finance_cargo_tariffs_user_payload(*, storage_path: str | Path | None=None, db_name: str | None=None) -> dict[str, Any]:
    if storage_path in (None, ""):
        return _load_finance_cargo_tariffs_user_payload_db(db_name=db_name)
    path = _resolve_finance_cargo_tariffs_path(storage_path=storage_path, db_name=db_name)
    parsed = _read_json_payload(path)
    if parsed is None:
        return {"records": [], "deletedKeys": []}
    if isinstance(parsed, dict):
        records = parsed.get("records") or []
        deleted_keys = parsed.get("deletedKeys") or []
    elif isinstance(parsed, list):
        records = parsed
        deleted_keys = []
    else:
        raise RuntimeError(f"Kargo tarife JSON formatı hatalı: {path}")
    return {
        "records": _normalize_finance_cargo_tariff_rows(records, is_builtin=False, db_name=db_name),
        "deletedKeys": [_compact_text(key) for key in list(deleted_keys or []) if _compact_text(key)],
    }


def _load_finance_cargo_tariffs_default_raw(*, default_storage_path: str | Path | None=None, storage_path: str | Path | None=None, db_name: str | None=None) -> list[dict[str, Any]]:
    global _finance_cargo_tariffs_default_cache_signature, _finance_cargo_tariffs_default_cache_rows

    path = _resolve_finance_cargo_tariffs_default_path(
        default_storage_path=default_storage_path,
        storage_path=storage_path,
    )
    if path is None:
        return []
    try:
        signature = _path_signature(path)
    except FileNotFoundError:
        return []
    if (
        _finance_cargo_tariffs_default_cache_rows is not None
        and _finance_cargo_tariffs_default_cache_signature == signature
    ):
        normalized = [dict(row or {}) for row in _finance_cargo_tariffs_default_cache_rows]
    else:
        parsed = {"records": list(finance_cargo_tariff_default_records(path))}
        if parsed is None:
            return []
        if isinstance(parsed, dict):
            records = parsed.get("records") or []
        elif isinstance(parsed, list):
            records = parsed
        else:
            raise RuntimeError(f"Default kargo tarife JSON formatı hatalı: {path}")
        normalized = _normalize_finance_cargo_tariff_rows(records, is_builtin=True, db_name=db_name)
        _finance_cargo_tariffs_default_cache_signature = signature
        _finance_cargo_tariffs_default_cache_rows = [dict(row or {}) for row in normalized]
    filtered = [dict(row or {}) for row in normalized]
    if storage_path in (None, ""):
        accepted_platform_source_ids = _accepted_cargo_tariff_platform_source_ids(db_name=db_name)
        accepted_provider_source_ids = _accepted_cargo_tariff_provider_source_ids(db_name=db_name)
        filtered = [
            dict(row or {})
            for row in filtered
            if coerce_source_id((row or {}).get("platformSourceId") or (row or {}).get("platform_source_id"))
            in accepted_platform_source_ids
            and (
                not _compact_text((row or {}).get("cargoProviderCode"))
                or coerce_source_id((row or {}).get("cargoProviderSourceId") or (row or {}).get("cargo_provider_source_id"))
                in accepted_provider_source_ids
            )
        ]
    return filtered


def _finance_cargo_tariff_model_to_row(row: LogisticsCargoTariff) -> dict[str, Any]:
    platform_code = _fast_platform_code(getattr(row, "platform", FINANCE_PLATFORM_TRENDYOL), default=FINANCE_PLATFORM_TRENDYOL)
    platform_source_id = marketplace_source_id_for_code(platform_code)
    provider_code = _compact_text(getattr(row, "cargoProviderCode", "")).upper() or None
    provider_source_id = cargo_provider_source_id_for_code(provider_code, platform_code=platform_code) if provider_code else None
    return {
        "pk": int(getattr(row, "pk", 0) or 0),
        "dbPk": int(getattr(row, "pk", 0) or 0),
        "tariffKey": _compact_text(getattr(row, "tariffKey", "")),
        "name": _compact_text(getattr(row, "name", "")),
        "description": _compact_text(getattr(row, "description", "")) or None,
        "platform": platform_code,
        "platformCode": platform_code,
        "platformSourceId": platform_source_id,
        "platform_source_id": platform_source_id,
        "cargoProviderCode": provider_code,
        "cargoProviderSourceId": provider_source_id,
        "cargo_provider_source_id": provider_source_id,
        "cargoProviderName": _compact_text(getattr(row, "cargoProviderName", "")) or None,
        "minDesi": _optional_float(getattr(row, "minDesi", None)),
        "maxDesi": _optional_float(getattr(row, "maxDesi", None)),
        "minSalePrice": _optional_float(getattr(row, "minSalePrice", None)),
        "maxSalePrice": _optional_float(getattr(row, "maxSalePrice", None)),
        "amount": _optional_float(getattr(row, "amount", None)),
        "currency": _normalize_finance_currency(getattr(row, "currency", "TRY")),
        "isVatIncluded": bool(getattr(row, "isVatIncluded", True)),
        "vatRate": _optional_float(getattr(row, "vatRate", None)),
        "isActive": bool(getattr(row, "isActive", True)),
        "isDeleted": bool(getattr(row, "isDeleted", False)),
        "createdAt": _compact_text(getattr(row, "createdAt", "")),
        "updatedAt": _compact_text(getattr(row, "updatedAt", "")),
        "sourceType": _compact_text(getattr(row, "sourceType", "")) or None,
        "sourceId": _source_id_or_none(getattr(row, "sourceId", None)),
        "source_id": _source_id_or_none(getattr(row, "sourceId", None)),
    }


def _load_finance_cargo_tariffs_user_payload_db(*, db_name: str | None=None) -> dict[str, Any]:
    engine = get_engine(db_name or DB_NAME)
    with Session(engine) as session:
        rows = session.exec(select(LogisticsCargoTariff).order_by(LogisticsCargoTariff.pk.asc())).all() or []
    deleted_keys: list[str] = []
    records: list[dict[str, Any]] = []
    for model_row in rows:
        payload = _finance_cargo_tariff_model_to_row(model_row)
        tariff_key = _compact_text(payload.get("tariffKey"))
        if not tariff_key:
            continue
        if bool(payload.get("isDeleted")):
            deleted_keys.append(tariff_key)
            continue
        records.append(payload)
    return {
        "records": _normalize_finance_cargo_tariff_rows(records, is_builtin=False),
        "deletedKeys": [_compact_text(key) for key in deleted_keys if _compact_text(key)],
    }


def _load_finance_cargo_tariffs_raw(*, storage_path: str | Path | None=None, db_name: str | None=None, default_storage_path: str | Path | None=None) -> list[dict[str, Any]]:
    builtin_rows = _load_finance_cargo_tariffs_default_raw(
        default_storage_path=default_storage_path,
        storage_path=storage_path,
        db_name=db_name,
    )
    user_payload = _load_finance_cargo_tariffs_user_payload(storage_path=storage_path, db_name=db_name)
    user_rows = list(user_payload.get("records") or [])
    accepted_builtin_keys = {
        _compact_text(row.get("tariffKey")).casefold()
        for row in user_rows
        if _compact_text(row.get("tariffKey"))
    }
    deleted_keys = {
        _compact_text(key).casefold()
        for key in list(user_payload.get("deletedKeys") or [])
        if _compact_text(key)
    }

    merged: dict[str, dict[str, Any]] = {}
    builtin_keys: set[str] = set()
    builtin_source_ids: set[int] = set()
    for row in builtin_rows:
        tariff_key = _compact_text(row.get("tariffKey"))
        if not tariff_key or tariff_key.casefold() in deleted_keys:
            continue
        builtin_keys.add(tariff_key.casefold())
        source_id = _source_id_or_none(row.get("sourceId") or row.get("source_id"))
        if source_id is not None:
            builtin_source_ids.add(source_id)
        merged[tariff_key.casefold()] = {
            **dict(row),
            "isBuiltin": True,
            "isBuiltinAccepted": tariff_key.casefold() in accepted_builtin_keys,
            "isSeedRemoved": False,
        }

    for row in user_rows:
        tariff_key = _compact_text(row.get("tariffKey"))
        if not tariff_key or tariff_key.casefold() in deleted_keys:
            continue
        payload = dict(row)
        if tariff_key.casefold() in builtin_keys:
            builtin_row = dict(merged.get(tariff_key.casefold()) or {})
            merged_row = dict(builtin_row)
            merged_row.update(payload)
            merged_row["sourceType"] = SOURCE_TYPE_BUILTIN
            merged_row["sourceId"] = _source_id_or_none(builtin_row.get("sourceId") or builtin_row.get("source_id"))
            merged_row["source_id"] = merged_row["sourceId"]
            merged_row["isBuiltin"] = True
            merged_row["isBuiltinAccepted"] = True
            merged_row["isSeedRemoved"] = False
            merged[tariff_key.casefold()] = merged_row
            continue
        payload_source_type = _compact_text(payload.get("sourceType") or payload.get("source_type")).lower()
        payload_source_id = _source_id_or_none(payload.get("sourceId") or payload.get("source_id"))
        is_seed_removed = (
            payload_source_type == SOURCE_TYPE_BUILTIN
            or (
                payload_source_type == SOURCE_TYPE_USER
                and not bool(payload.get("isActive", True))
                and payload_source_id is not None
                and _source_id_or_none(payload.get("platformSourceId") or payload.get("platform_source_id")) is not None
            )
        ) and (payload_source_id is None or payload_source_id not in builtin_source_ids)
        payload["isBuiltin"] = bool(is_seed_removed)
        payload["isBuiltinAccepted"] = True
        payload["isSeedRemoved"] = bool(is_seed_removed)
        merged[tariff_key.casefold()] = payload

    return list(merged.values())


def _range_label(min_value: Any, max_value: Any, *, suffix: str='', empty_text: str='-') -> str:
    left = _optional_float(min_value)
    right = _optional_float(max_value)
    if left is None and right is None:
        return empty_text
    if left is not None and right is not None:
        return f"{left:g} - {right:g}{suffix}"
    if left is not None:
        return f"{left:g}+{suffix}"
    return f"0 - {right:g}{suffix}"


def _cargo_tariff_to_dict(row: dict[str, Any], *, platform_label_lookup: dict[str, str] | None=None, provider_lookup: dict[tuple[str, str], str] | None=None, provider_fallback_lookup: dict[str, str] | None=None, marketplace_code_by_source_id: dict[int, str] | None=None, provider_code_by_source_id: dict[int, str] | None=None, provider_name_by_source_id: dict[int, str] | None=None, db_name: str | None=None) -> dict[str, Any]:
    payload = dict(row or {})
    platform_source_id = _source_id_or_none(payload.get("platformSourceId") or payload.get("platform_source_id"))
    platform_code = (
        _fast_platform_code(payload.get("platform") or payload.get("platformCode"), default="")
        or (marketplace_code_by_source_id or {}).get(int(platform_source_id or 0), "")
        or FINANCE_PLATFORM_TRENDYOL
    )
    platform_source_id = platform_source_id or marketplace_source_id_for_code(platform_code, db_name=db_name)
    platform_label = (
        _compact_text((platform_label_lookup or {}).get(platform_code))
        or platform_label_for_code(platform_code, db_name=db_name)
        or "Trendyol"
    )
    provider_source_id = _source_id_or_none(payload.get("cargoProviderSourceId") or payload.get("cargo_provider_source_id"))
    provider_code = (
        _compact_text(payload.get("cargoProviderCode")).upper()
        or (provider_code_by_source_id or {}).get(int(provider_source_id or 0), "")
        or cargo_provider_code_for_source_id(provider_source_id, db_name=db_name)
    )
    provider_source_id = provider_source_id or cargo_provider_source_id_for_code(
        provider_code,
        platform_code=platform_code,
        db_name=db_name,
    )
    provider_name = _compact_text(payload.get("cargoProviderName"))
    if not provider_name and provider_source_id is not None:
        provider_name = _compact_text((provider_name_by_source_id or {}).get(int(provider_source_id)))
    if not provider_name and provider_code:
        provider_name = _compact_text((provider_lookup or {}).get((platform_code, provider_code)))
    if not provider_name and provider_code:
        provider_name = _compact_text((provider_fallback_lookup or {}).get(provider_code))
    if not provider_name:
        provider_name = _cargo_provider_name_for_code(
            provider_code,
            platform_code=platform_code,
            db_name=db_name,
        )
    amount = _optional_float(payload.get("amount"))
    vat_rate = _optional_float(payload.get("vatRate"))
    is_vat_included = bool(payload.get("isVatIncluded", True))
    amount_mode_text = "KDV dahil" if is_vat_included else f"KDV hariç (%{_format_compact_number(vat_rate) or '0'})"
    return {
        "pk": int(payload.get("pk") or 0),
        "tariffKey": _compact_text(payload.get("tariffKey")),
        "name": _compact_text(payload.get("name")),
        "description": _compact_text(payload.get("description")),
        "cargo_provider_id": _safe_int_id(payload.get("cargo_provider_id") or payload.get("cargoProviderId")),
        "platformCode": platform_code,
        "platformSourceId": platform_source_id,
        "platform_source_id": platform_source_id,
        "platform": platform_label,
        "cargoProviderCode": provider_code,
        "cargoProviderSourceId": provider_source_id,
        "cargo_provider_source_id": provider_source_id,
        "cargoProviderName": provider_name,
        "providerText": provider_name or "-",
        "minDesi": _optional_float(payload.get("minDesi")),
        "maxDesi": _optional_float(payload.get("maxDesi")),
        "desiRangeText": _range_label(payload.get("minDesi"), payload.get("maxDesi"), suffix=" desi"),
        "minSalePrice": _optional_float(payload.get("minSalePrice")),
        "maxSalePrice": _optional_float(payload.get("maxSalePrice")),
        "salePriceRangeText": _range_label(payload.get("minSalePrice"), payload.get("maxSalePrice"), suffix=" TL"),
        "amount": amount,
        "amountText": _format_money(amount) if amount not in (None, "") else "",
        "amountInputText": _format_compact_number(amount),
        "currency": _compact_text(payload.get("currency")) or "TRY",
        "isVatIncluded": is_vat_included,
        "vatRate": vat_rate,
        "vatRateText": _format_compact_number(vat_rate),
        "amountModeText": amount_mode_text,
        "isActive": bool(payload.get("isActive", True)),
        "isBuiltin": bool(payload.get("isBuiltin", False)),
        "isBuiltinAccepted": bool(payload.get("isBuiltinAccepted", not bool(payload.get("isBuiltin", False)))),
        "isSeedRemoved": bool(payload.get("isSeedRemoved", False)),
        "createdAt": _compact_text(payload.get("createdAt")),
        "updatedAt": _compact_text(payload.get("updatedAt")),
        "sourceType": _compact_text(payload.get("sourceType", "")) or None,
        "sourceId": _source_id_or_none(payload.get("sourceId") or payload.get("source_id")),
        "source_id": _source_id_or_none(payload.get("sourceId") or payload.get("source_id")),
    }


def load_finance_cargo_tariffs(*, search_text: str='', platform: str='', cargo_provider_code: str='', active_state: str='', source_state: str='', storage_path: str | Path | None=None, db_name: str | None=None, default_storage_path: str | Path | None=None) -> Result:
    try:
        raw_records = _load_finance_cargo_tariffs_raw(
            storage_path=storage_path,
            db_name=db_name,
            default_storage_path=default_storage_path,
        )
        platform_label_lookup = _finance_platform_label_lookup(db_name=db_name)
        provider_lookup, provider_fallback_lookup = _finance_cargo_provider_lookup(db_name=db_name)
        marketplace_code_by_source_id, _marketplace_source_id_by_code = _marketplace_source_maps(db_name=db_name)
        provider_code_by_source_id, _provider_source_id_by_key, _provider_name_by_key, provider_name_by_source_id = _cargo_provider_source_maps(db_name=db_name)
        records = [
            _cargo_tariff_to_dict(
                row,
                platform_label_lookup=platform_label_lookup,
                provider_lookup=provider_lookup,
                provider_fallback_lookup=provider_fallback_lookup,
                marketplace_code_by_source_id=marketplace_code_by_source_id,
                provider_code_by_source_id=provider_code_by_source_id,
                provider_name_by_source_id=provider_name_by_source_id,
                db_name=db_name,
            )
            for row in raw_records
        ]
        records = sorted(
            records,
            key=lambda row: (
                not bool(row.get("isActive")),
                -_parse_epoch_ms(row.get("updatedAt") or row.get("createdAt") or 0) if _parse_epoch_ms(row.get("updatedAt") or row.get("createdAt") or 0) else 0,
                _compact_text(row.get("name")).casefold(),
            ),
        )

        clean_search = _compact_text(search_text).casefold()
        clean_platform_source_id = _source_id_or_none(platform)
        clean_platform = marketplace_code_for_source_id(clean_platform_source_id, db_name=db_name) or canonical_platform_code(platform)
        clean_provider_source_id = _source_id_or_none(cargo_provider_code)
        clean_provider = cargo_provider_code_for_source_id(clean_provider_source_id, db_name=db_name) or _compact_text(cargo_provider_code).upper()
        clean_active = _compact_text(active_state).casefold()
        clean_source = _compact_text(source_state).casefold()
        if clean_platform.casefold() == "all":
            clean_platform = ""
        if clean_provider.casefold() == "all":
            clean_provider = ""
        if clean_active == "all":
            clean_active = ""
        if clean_source == "all":
            clean_source = ""

        if clean_search:
            records = [
                row for row in records
                if clean_search in " ".join(
                    [
                        _compact_text(row.get("name")),
                        _compact_text(row.get("description")),
                        _compact_text(row.get("tariffKey")),
                        _compact_text(row.get("platform")),
                        _compact_text(row.get("platformCode")),
                        _compact_text(row.get("cargoProviderCode")),
                        _compact_text(row.get("cargoProviderName")),
                    ]
                ).casefold()
            ]
        if clean_platform:
            records = [
                row
                for row in records
                if (
                    _source_id_or_none(row.get("platformSourceId") or row.get("platform_source_id")) == clean_platform_source_id
                    if clean_platform_source_id is not None
                    else _fast_platform_code(row.get("platformCode") or row.get("platform"), default="") == clean_platform
                )
            ]
        if clean_provider:
            records = [
                row
                for row in records
                if (
                    _source_id_or_none(row.get("cargoProviderSourceId") or row.get("cargo_provider_source_id")) == clean_provider_source_id
                    if clean_provider_source_id is not None
                    else _compact_text(row.get("cargoProviderCode")).upper() == clean_provider
                )
            ]
        if clean_active == "aktif":
            records = [row for row in records if bool(row.get("isActive"))]
        elif clean_active == "pasif":
            records = [row for row in records if not bool(row.get("isActive"))]
        if clean_source in {"pending", "builtin"}:
            records = [row for row in records if bool(row.get("isBuiltin")) and not bool(row.get("isBuiltinAccepted"))]
        elif clean_source in {"saved", "accepted"}:
            records = [row for row in records if bool(row.get("isBuiltinAccepted"))]

        active_count = sum(1 for row in records if bool(row.get("isActive")))
        return Result.ok(
            "Kargo tarifeleri yüklendi.",
            close_dialog=False,
            data={
                "records": records,
                "summary_text": f"Toplam tarife: {len(records)} | Aktif: {active_count}",
            },
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)
