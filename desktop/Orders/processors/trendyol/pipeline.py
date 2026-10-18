# Orders/processors/pipeline.py
from __future__ import annotations

import asyncio
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, date
from functools import lru_cache
from types import SimpleNamespace
from typing import Optional, Callable, Any

from sqlmodel import Session, select
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import aliased, contains_eager

from settings import DB_NAME

from Feedback.processors.pipeline import Result, map_error_to_message

from Orders.api.trendyol.orders_api import TrendyolApi
from Marketplaces.api.trendyol.base_api import trendyol_account_payload_client_kwargs
from Orders.constants import ORDER_FINAL_STATUS_CODES, TZ_GMT3
from Orders.models.trendyol.models import OrderItem, OrderData, OrderHeader, ReturnClaim
from Orders.constants.trendyol.constants import (
    ORDERDATA_UNIQ,
    ORDERITEM_UNIQ,
    RETURNCLAIM_UNIQ,
    TRENDYOL_MAX_STATUS_QUERY_WINDOW_DAYS,
    TRENDYOL_ORDER_STATUS_ALIASES,
    TRENDYOL_RETURN_STATUS_LABELS,
    TRENDYOL_RETURN_STATUS_PRIORITY,
    TRENDYOL_STATUS_LABELS,
)

from Core.utils.model_utils import create_records, get_records, get_engine, make_normalizer, update_records
from Core.utils.time_utils import coerce_to_date
from Marketplaces.constants.catalog_constants import canonical_platform_code
from Account.models.models import ApiAccount

_ENGINE_DB_NAME: str | None = None
_ENGINE = None


def _engine(db_name: str | None = None):
    global _ENGINE_DB_NAME, _ENGINE
    resolved_db_name = str(db_name or DB_NAME)
    if _ENGINE is None or _ENGINE_DB_NAME != resolved_db_name:
        _ENGINE = get_engine(resolved_db_name)
        _ENGINE_DB_NAME = resolved_db_name
    return _ENGINE


def _normalize_order_item_record(row: dict) -> dict:
    out = dict(row or {})

    line_id = (
        out.get("lineId")
        or out.get("lineItemId")
        or out.get("orderLineItemId")
        or out.get("id")
        or out.get("productCode")
    )
    if line_id not in (None, ""):
        out["lineId"] = line_id

    snapshot_last_modified = (
        out.get("snapshotLastModifiedDate")
        or out.get("lastModifiedDate")
        or out.get("taskDate")
    )
    if snapshot_last_modified not in (None, ""):
        out["snapshotLastModifiedDate"] = snapshot_last_modified

    return out


ORDERDATA_NORMALIZER = make_normalizer(
    strip_strings=True,
)

ORDERITEM_NORMALIZER = make_normalizer(
    coalesce_none={
        "productCode": 0,
        "orderLineItemStatusName": "Unknown",
        "order_data_id": 0,
        "taskDate": 0,
    },
    strip_strings=True,
    extra=_normalize_order_item_record,
)

RETURNCLAIM_NORMALIZER = make_normalizer(
    strip_strings=True,
    coalesce_none={
        "claimNumber": "",
        "claimItemStatus": "Unknown",
        "itemCount": 0,
    },
)

RETURN_ACTIVE_STATUS_FILTER_CODE = "__open_returns__"
RETURN_ACTIVE_STATUS_CODES = [
    "Created",
    "WaitingInAction",
    "WaitingFraudCheck",
    "InAnalysis",
    "Unresolved",
]

def _to_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _to_float(value, default: float | None = None) -> float | None:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def _resolve_order_snapshot_id(row: dict | None) -> int | None:
    payload = row or {}
    for key in ("id", "shipmentPackageId", "orderShipmentPackageId", "packageId"):
        value = _to_int(payload.get(key), default=0)
        if value > 0:
            return value
    return None


def _prepare_order_data_row(row: dict | None) -> dict | None:
    out = dict(row or {})
    snapshot_id = _resolve_order_snapshot_id(out)
    if snapshot_id is not None:
        out["id"] = snapshot_id

    order_number = str(out.get("orderNumber") or "").strip()
    last_modified = _to_int(out.get("lastModifiedDate"), default=0)
    api_account_id = out.get("api_account_id")
    if not order_number or api_account_id in (None, "") or snapshot_id is None or last_modified <= 0:
        return None

    out["orderNumber"] = order_number
    return out


ORDER_NORMALIZATION_REASON_MISSING_SNAPSHOT_IDENTITY = "missing_snapshot_identity"
ORDER_NORMALIZATION_REASON_MISSING_ORDER_NUMBER = "missing_order_number"
ORDER_NORMALIZATION_REASON_MISSING_ACCOUNT_IDENTITY = "missing_api_account_identity"
ORDER_NORMALIZATION_REASON_MISSING_LAST_MODIFIED_DATE = "missing_last_modified_date"
ORDER_NORMALIZATION_REASON_REJECTED = "normalization_rejected"


def _order_normalization_rejection_reason(
    row: dict | None,
    comp_api_account_id: int | None,
) -> str | None:
    payload = row or {}
    if _resolve_order_snapshot_id(payload) is None:
        return ORDER_NORMALIZATION_REASON_MISSING_SNAPSHOT_IDENTITY
    if not str(payload.get("orderNumber") or "").strip():
        return ORDER_NORMALIZATION_REASON_MISSING_ORDER_NUMBER
    if comp_api_account_id in (None, ""):
        return ORDER_NORMALIZATION_REASON_MISSING_ACCOUNT_IDENTITY
    if _to_int(payload.get("lastModifiedDate"), default=0) <= 0:
        return ORDER_NORMALIZATION_REASON_MISSING_LAST_MODIFIED_DATE
    return None


def _new_order_sync_diagnostics(
    *,
    api_account_id: int | None = None,
    environment: str = "",
    status: str = "",
) -> dict:
    return {
        "api_account_id": api_account_id,
        "environment": str(environment or "").strip().lower(),
        "status": str(status or "").strip(),
        "source_rows_seen": 0,
        "normalized_order_rows": 0,
        "normalized_item_rows": 0,
        "skipped_source_rows": 0,
        "skipped_reasons": {},
        "policy_excluded_source_rows": 0,
        "policy_excluded_reasons": {},
        "source_rows_complete": True,
        "windows_queried": 0,
        "pages_queried": 0,
        "fetch_errors": 0,
    }


def _record_order_sync_rejection(
    diagnostics: dict,
    reason: str | None,
    *,
    status: str = "",
) -> None:
    normalized_reason = str(reason or ORDER_NORMALIZATION_REASON_REJECTED).strip()
    if (
        normalized_reason == ORDER_NORMALIZATION_REASON_MISSING_SNAPSHOT_IDENTITY
        and str(status or "").strip().casefold() == "awaiting"
    ):
        # Awaiting is a pre-payment, non-actionable stock signal. Trendyol Stage can
        # legitimately expose these rows before assigning a persistent shipment
        # package identity. Preserve the source accounting without inventing an ID
        # or treating the operational package snapshot as corrupt/incomplete.
        diagnostics["policy_excluded_source_rows"] = int(
            diagnostics.get("policy_excluded_source_rows", 0) or 0
        ) + 1
        reasons = diagnostics.setdefault("policy_excluded_reasons", {})
        reasons[normalized_reason] = int(reasons.get(normalized_reason, 0) or 0) + 1
        return
    diagnostics["skipped_source_rows"] = int(diagnostics.get("skipped_source_rows", 0) or 0) + 1
    reasons = diagnostics.setdefault("skipped_reasons", {})
    reasons[normalized_reason] = int(reasons.get(normalized_reason, 0) or 0) + 1
    diagnostics["source_rows_complete"] = False


def _merge_order_sync_diagnostics(target: dict, source: dict | None) -> dict:
    incoming = source or {}
    for key in (
        "source_rows_seen",
        "normalized_order_rows",
        "normalized_item_rows",
        "skipped_source_rows",
        "policy_excluded_source_rows",
        "windows_queried",
        "pages_queried",
        "fetch_errors",
    ):
        target[key] = int(target.get(key, 0) or 0) + int(incoming.get(key, 0) or 0)

    reasons = target.setdefault("skipped_reasons", {})
    for reason, count in (incoming.get("skipped_reasons") or {}).items():
        key = str(reason or ORDER_NORMALIZATION_REASON_REJECTED).strip()
        reasons[key] = int(reasons.get(key, 0) or 0) + int(count or 0)

    excluded_reasons = target.setdefault("policy_excluded_reasons", {})
    for reason, count in (incoming.get("policy_excluded_reasons") or {}).items():
        key = str(reason or ORDER_NORMALIZATION_REASON_REJECTED).strip()
        excluded_reasons[key] = int(excluded_reasons.get(key, 0) or 0) + int(count or 0)

    if incoming.get("source_rows_complete") is False or int(target.get("skipped_source_rows", 0) or 0) > 0:
        target["source_rows_complete"] = False
    return target


def normalize_order_sync_diagnostics_policy(diagnostics: dict | None) -> dict[str, Any]:
    """Reclassify only evidenced, non-actionable Awaiting identity exclusions.

    Older audit rows can contain Stage ``Awaiting`` records under
    ``skipped_source_rows`` because those records have no persistent shipment package
    identity yet. The run-level status and reason are sufficient to replay that policy
    decision without another marketplace request. Identity loss in every actionable
    status remains an incomplete source snapshot.
    """

    normalized = dict(diagnostics or {})
    raw_runs = list(normalized.get("runs") or [])
    if not raw_runs:
        return normalized

    runs: list[dict[str, Any]] = []
    for raw_run in raw_runs:
        run = dict(raw_run or {}) if isinstance(raw_run, dict) else {}
        skipped_reasons = dict(run.get("skipped_reasons") or {})
        excluded_reasons = dict(run.get("policy_excluded_reasons") or {})
        skipped_count = int(run.get("skipped_source_rows") or 0)
        excluded_count = int(run.get("policy_excluded_source_rows") or 0)
        if str(run.get("status") or "").strip().casefold() == "awaiting":
            missing_identity = int(
                skipped_reasons.get(ORDER_NORMALIZATION_REASON_MISSING_SNAPSHOT_IDENTITY)
                or 0
            )
            moved = min(skipped_count, missing_identity)
            if moved > 0:
                skipped_count -= moved
                missing_identity -= moved
                excluded_count += moved
                excluded_reasons[ORDER_NORMALIZATION_REASON_MISSING_SNAPSHOT_IDENTITY] = (
                    int(
                        excluded_reasons.get(
                            ORDER_NORMALIZATION_REASON_MISSING_SNAPSHOT_IDENTITY
                        )
                        or 0
                    )
                    + moved
                )
                if missing_identity:
                    skipped_reasons[ORDER_NORMALIZATION_REASON_MISSING_SNAPSHOT_IDENTITY] = missing_identity
                else:
                    skipped_reasons.pop(ORDER_NORMALIZATION_REASON_MISSING_SNAPSHOT_IDENTITY, None)
        run["skipped_source_rows"] = skipped_count
        run["skipped_reasons"] = skipped_reasons
        run["policy_excluded_source_rows"] = excluded_count
        run["policy_excluded_reasons"] = excluded_reasons
        if skipped_count == 0 and int(run.get("fetch_errors") or 0) == 0:
            run["source_rows_complete"] = True
        runs.append(run)

    skipped_reasons: dict[str, int] = {}
    excluded_reasons: dict[str, int] = {}
    for run in runs:
        for reason, count in dict(run.get("skipped_reasons") or {}).items():
            skipped_reasons[str(reason)] = skipped_reasons.get(str(reason), 0) + int(count or 0)
        for reason, count in dict(run.get("policy_excluded_reasons") or {}).items():
            excluded_reasons[str(reason)] = excluded_reasons.get(str(reason), 0) + int(count or 0)

    normalized["runs"] = runs
    normalized["skipped_source_rows"] = sum(
        int(run.get("skipped_source_rows") or 0) for run in runs
    )
    normalized["skipped_reasons"] = skipped_reasons
    normalized["policy_excluded_source_rows"] = sum(
        int(run.get("policy_excluded_source_rows") or 0) for run in runs
    )
    normalized["policy_excluded_reasons"] = excluded_reasons
    normalized["source_rows_complete"] = all(
        run.get("source_rows_complete") is not False for run in runs
    )
    return normalized


def apply_order_sync_policy_to_observability(
    observability: dict | None,
    diagnostics: dict | None,
) -> dict[str, Any]:
    """Apply Orders-owned source policy to a persisted/replayed sync observation."""

    out = dict(observability or {})
    normalized = normalize_order_sync_diagnostics_policy(diagnostics)
    excluded_count = int(normalized.get("policy_excluded_source_rows") or 0)
    if excluded_count <= 0:
        return out

    fetched = dict(out.get("fetched") or {})
    fetched["policy_excluded_source_rows"] = excluded_count
    out["fetched"] = fetched
    skipped = dict(out.get("skipped") or {})
    skipped["source_rows"] = int(normalized.get("skipped_source_rows") or 0)
    skipped["source_reasons"] = dict(normalized.get("skipped_reasons") or {})
    out["skipped"] = skipped
    out["excluded"] = {
        "source_rows": excluded_count,
        "source_reasons": dict(normalized.get("policy_excluded_reasons") or {}),
        "policy": "non_actionable_awaiting_without_persistent_package_identity",
    }

    excluded_by_account: dict[int, int] = {}
    skipped_by_account: dict[int, int] = {}
    for run in list(normalized.get("runs") or []):
        try:
            account_pk = int(run.get("api_account_id") or 0)
        except Exception:
            account_pk = 0
        if account_pk <= 0:
            continue
        excluded_by_account[account_pk] = excluded_by_account.get(account_pk, 0) + int(
            run.get("policy_excluded_source_rows") or 0
        )
        skipped_by_account[account_pk] = skipped_by_account.get(account_pk, 0) + int(
            run.get("skipped_source_rows") or 0
        )
    accounts: list[dict[str, Any]] = []
    for raw_account in list(out.get("accounts") or []):
        account = dict(raw_account or {})
        try:
            account_pk = int(account.get("api_account_id") or 0)
        except Exception:
            account_pk = 0
        if account_pk > 0:
            account["source_rows_skipped"] = skipped_by_account.get(account_pk, 0)
            account["source_rows_policy_excluded"] = excluded_by_account.get(account_pk, 0)
        accounts.append(account)
    out["accounts"] = accounts

    watermark = dict(out.get("watermark") or {})
    source_complete = normalized.get("source_rows_complete") is not False
    watermark["source_rows_complete"] = source_complete
    readback = dict(out.get("db_readback") or {})
    if source_complete and readback.get("verified") is True:
        watermark["fresh_through_ms"] = int(watermark.get("requested_end_ms") or 0)
    out["watermark"] = watermark
    return out


def order_sync_diagnostics_warning(diagnostics: dict | None) -> str:
    payload = diagnostics or {}
    skipped = int(payload.get("skipped_source_rows", 0) or 0)
    policy_excluded = int(payload.get("policy_excluded_source_rows", 0) or 0)
    if skipped <= 0 and policy_excluded <= 0 and payload.get("source_rows_complete") is not False:
        return ""

    messages: list[str] = []
    if policy_excluded > 0:
        messages.append(
            f"{policy_excluded} Awaiting satırı henüz kalıcı shipment package kimliği "
            "taşımadığı için operational sipariş snapshot'ı dışında tutuldu."
        )

    reasons = payload.get("skipped_reasons") or {}
    missing_identity = int(reasons.get(ORDER_NORMALIZATION_REASON_MISSING_SNAPSHOT_IDENTITY, 0) or 0)
    if missing_identity == skipped and skipped > 0:
        messages.append(
            f"{skipped} pazaryeri sipariş satırı kalıcı shipment package kimliği "
            "taşımadığı için uydurma kimlik üretilmeden senkronizasyon dışında bırakıldı."
        )
    elif skipped > 0 or payload.get("source_rows_complete") is False:
        messages.append(
            f"{skipped} pazaryeri sipariş satırı kimlik/bütünlük kurallarını geçemedi; "
            "senkronizasyon eksik."
        )
    return " ".join(messages)


def _normalize_order_numbers(order_numbers: list[str] | tuple[str, ...] | None) -> list[str]:
    normalized = [str(item or "").strip() for item in (order_numbers or []) if str(item or "").strip()]
    return list(dict.fromkeys(normalized))


def _normalize_api_account_ids(api_account_ids: list[int] | tuple[int, ...] | None) -> list[int]:
    normalized: list[int] = []
    seen: set[int] = set()
    for item in api_account_ids or []:
        if item is None:
            continue
        try:
            value = int(item)
        except Exception:
            continue
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _normalize_platform_codes(platform_codes: list[str] | tuple[str, ...] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in platform_codes or []:
        value = canonical_platform_code(item)
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(value)
    return normalized


def _coerce_epoch_ms(value: Any) -> int | None:
    try:
        if value in (None, "", 0):
            return None
        if isinstance(value, datetime):
            dt = value
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=TZ_GMT3)
            return int(dt.timestamp() * 1000)
        if isinstance(value, date):
            dt = datetime(value.year, value.month, value.day, tzinfo=TZ_GMT3)
            return int(dt.timestamp() * 1000)
        ms = int(value)
        if ms <= 0:
            return None
        if ms < 10 ** 12:
            ms *= 1000
        return ms
    except Exception:
        return None


def _now_epoch_ms() -> int:
    return int(datetime.now(TZ_GMT3).timestamp() * 1000)


def _format_shipping_delta_parts(delta_ms: int) -> str:
    total_seconds = max(0, int(abs(delta_ms) // 1000))
    days, rem = divmod(total_seconds, 24 * 60 * 60)
    hours, rem = divmod(rem, 60 * 60)
    minutes, _seconds = divmod(rem, 60)

    if days > 0:
        return f"{days} gün {hours} saat"
    if hours > 0:
        return f"{hours} saat" if minutes <= 0 else f"{hours} saat {minutes} dk"
    return f"{minutes} dk"


def _normalize_runtime_status_code(status_code: str | None) -> str:
    code = str(status_code or "").strip()
    if not code:
        return ""
    for alias_code, canonical_code in TRENDYOL_ORDER_STATUS_ALIASES.items():
        if str(alias_code).casefold() == code.casefold():
            return str(canonical_code)
    # Agentic/domain callers use provider-independent snake_case status names,
    # while persisted Trendyol snapshots retain marketplace casing. Resolve
    # both forms at this Orders-owned boundary so every caller shares one
    # canonical lifecycle vocabulary instead of duplicating mappings in AI.
    normalized_key = "".join(
        char
        for char in unicodedata.normalize(
            "NFKD",
            code.casefold().replace("\u0131", "i"),
        )
        if char.isalnum() and not unicodedata.combining(char)
    )
    canonical_codes = tuple(
        dict.fromkeys(
            (
                *TRENDYOL_STATUS_LABELS.keys(),
                *ORDER_FINAL_STATUS_CODES,
                *TRENDYOL_ORDER_STATUS_ALIASES.values(),
            )
        )
    )
    for canonical_code in canonical_codes:
        canonical_key = "".join(
            char
            for char in unicodedata.normalize(
                "NFKD",
                str(canonical_code).casefold().replace("\u0131", "i"),
            )
            if char.isalnum() and not unicodedata.combining(char)
        )
        if canonical_key == normalized_key:
            return str(canonical_code)
    return code


def canonical_order_status_code(status_code: str | None) -> str:
    """Return the Orders-owned canonical shipment status code."""

    return _normalize_runtime_status_code(status_code)


def is_ready_to_ship_order_status(status_code: str | None) -> bool:
    """Keep operational label eligibility on the Orders status contract."""

    return canonical_order_status_code(status_code).casefold() in {
        "created",
        "picking",
    }


def is_simulated_order_record(row: Any) -> bool:
    order_number = str(getattr(row, "orderNumber", "") or "").strip().upper()
    cargo_provider = str(getattr(row, "cargoProviderName", "") or "").strip().casefold()
    return order_number.startswith("SIM-") or cargo_provider.startswith("simulated ")


def _exclude_simulated_order_sql(order_number_col, cargo_provider_col):
    return and_(
        ~func.coalesce(order_number_col, "").like("SIM-%"),
        ~func.coalesce(cargo_provider_col, "").like("simulated %"),
    )


@lru_cache(maxsize=256)
def _normalize_filter_choice_key_cached(text: str) -> str:
    text = str(text or "").strip()
    if not text:
        return ""
    text = text.replace("İ", "I").replace("ı", "i")
    normalized = unicodedata.normalize("NFKD", text.casefold())
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    cleaned: list[str] = []
    for ch in normalized:
        if ch.isalnum():
            cleaned.append(ch)
        elif ch.isspace():
            cleaned.append(" ")
    return " ".join("".join(cleaned).split())


def _normalize_filter_choice_key(value: Any) -> str:
    return _normalize_filter_choice_key_cached(str(value or "").strip())


def _is_all_like_filter_value(value: Any) -> bool:
    text_key = _normalize_filter_choice_key(value)
    compact_key = text_key.replace(" ", "")
    labels = {
        "",
        "all",
        "tumu",
        "tum",
        "tm",
        "seciniz",
        "seiniz",
        "select",
        "selection",
    }
    return text_key in labels or compact_key in labels


def _status_code_from_label(value: Any, label_map: dict[str, str]) -> str:
    key = _normalize_filter_choice_key(value)
    if not key:
        return ""
    for code, label in (label_map or {}).items():
        if _normalize_filter_choice_key(label) == key:
            return str(code or "").strip()
    return ""


def _normalize_selected_filter_status(value: Any) -> str:
    if _is_all_like_filter_value(value):
        return ""
    label_code = _status_code_from_label(value, TRENDYOL_STATUS_LABELS)
    if not label_code:
        label_code = _status_code_from_label(value, TRENDYOL_RETURN_STATUS_LABELS)
    return _normalize_runtime_status_code(label_code or str(value or "").strip())


def _selected_filter_statuses(value: Any) -> list[str]:
    if _is_all_like_filter_value(value):
        return []
    text = str(value or "").strip()
    key = _normalize_filter_choice_key(text)
    if text == RETURN_ACTIVE_STATUS_FILTER_CODE or key in {
        "aktif iadeler",
        "aktif iade",
        "acik iadeler",
        "acik iade",
        "open returns",
        "open return",
    }:
        return list(RETURN_ACTIVE_STATUS_CODES)
    status = _normalize_selected_filter_status(text)
    return [status] if status and not _is_all_like_filter_value(status) else []


def _dedupe_order_items_for_upsert(order_item_list: list[dict]) -> list[dict]:
    """
    Keep only the newest row for each ORDERITEM_UNIQ key before upsert.
    This prevents older pages/status rows from overriding newer taskDate data.
    """
    grouped: dict[tuple, dict] = {}

    for row in order_item_list or []:
        if not isinstance(row, dict):
            continue

        order_data_id = _to_int(row.get("order_data_id"), default=0)
        snapshot_last_modified = _to_int(
            row.get("snapshotLastModifiedDate") or row.get("lastModifiedDate") or row.get("taskDate"),
            default=0,
        )
        line_id = _to_int(
            row.get("lineId")
            or row.get("lineItemId")
            or row.get("orderLineItemId")
            or row.get("id")
            or row.get("productCode"),
            default=0,
        )
        api_account_id = row.get("api_account_id")

        key = (
            order_data_id,
            snapshot_last_modified,
            line_id,
            str(api_account_id).strip(),
        )

        current = grouped.get(key)
        if current is None:
            grouped[key] = row
            continue

        row_id = _to_int(row.get("id"), default=0)
        cur_id = _to_int(current.get("id"), default=0)
        if row_id > cur_id:
            grouped[key] = row

    return list(grouped.values())


def _dedupe_order_snapshots_for_upsert(order_data_list: list[dict]) -> list[dict]:
    """Keep one deterministic row for each immutable marketplace snapshot identity."""
    grouped: dict[tuple, dict] = {}
    unidentified: list[dict] = []

    for row in order_data_list or []:
        if not isinstance(row, dict):
            continue
        snapshot_id = _resolve_order_snapshot_id(row)
        last_modified = _to_int(row.get("lastModifiedDate"), default=0)
        api_account_id = row.get("api_account_id")
        if snapshot_id is None or last_modified <= 0 or api_account_id in (None, ""):
            unidentified.append(row)
            continue

        key = (snapshot_id, last_modified, str(api_account_id).strip())
        current = grouped.get(key)
        if current is None:
            grouped[key] = row
            continue

        current_score = sum(value not in (None, "", [], {}) for value in current.values())
        row_score = sum(value not in (None, "", [], {}) for value in row.values())
        if row_score > current_score:
            grouped[key] = row

    return [*grouped.values(), *unidentified]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).strip().replace(",", "."))
    except Exception:
        return float(default)


def _extract_claim_status_code(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("name", "code", "value", "title"):
            text = str(value.get(key) or "").strip()
            if text:
                return text
        return ""
    return str(value or "").strip()


def _extract_claim_reason_text(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("name", "code", "value", "title", "message"):
            text = str(value.get(key) or "").strip()
            if text:
                return text
        return ""
    return str(value or "").strip()


def _unique_preserve_order(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _claim_quantity_from_entry(order_line: dict, claim_items: list[dict]) -> int:
    direct_qty = order_line.get("quantity")
    if direct_qty not in (None, ""):
        return max(1, _to_int(direct_qty, default=1))

    line_items = order_line.get("lineItems")
    if isinstance(line_items, list) and line_items:
        total_qty = 0
        for line_item in line_items:
            if not isinstance(line_item, dict):
                continue
            qty = line_item.get("quantity")
            total_qty += max(1, _to_int(qty, default=1))
        if total_qty > 0:
            return total_qty

    claim_qty_total = 0
    for claim_item in claim_items:
        if not isinstance(claim_item, dict):
            continue
        qty = claim_item.get("quantity")
        if qty not in (None, ""):
            claim_qty_total += max(1, _to_int(qty, default=1))
    if claim_qty_total > 0:
        return claim_qty_total

    if claim_items:
        return max(1, len(claim_items))
    return 1


def _build_return_item_rows(claim: dict) -> dict[str, Any]:
    entries = claim.get("items")
    if not isinstance(entries, list) or not entries:
        entries = [claim]

    root_status = _extract_claim_status_code(
        claim.get("claimItemStatus")
        or claim.get("claimStatus")
        or claim.get("status")
    )
    root_reason = _extract_claim_reason_text(
        claim.get("claimReason")
        or claim.get("customerClaimReason")
        or claim.get("reason")
    )
    item_rows: list[dict[str, Any]] = []
    all_line_ids: list[str] = []
    waiting_line_ids: list[str] = []
    all_statuses: list[str] = []
    all_reasons: list[str] = []
    total_price = 0.0

    for entry in entries:
        entry_row = entry if isinstance(entry, dict) else {}
        order_line = entry_row.get("orderLine") if isinstance(entry_row.get("orderLine"), dict) else {}
        claim_items = entry_row.get("claimItems")
        if not isinstance(claim_items, list) or not claim_items:
            claim_items = [entry_row]

        quantity = _claim_quantity_from_entry(order_line, claim_items)

        line_statuses = _unique_preserve_order([
            _extract_claim_status_code(claim_item.get("claimItemStatus") or claim_item.get("status"))
            for claim_item in claim_items
            if isinstance(claim_item, dict)
        ])
        line_reasons = _unique_preserve_order([
            _extract_claim_reason_text(
                claim_item.get("customerClaimItemReason")
                or claim_item.get("trendyolClaimItemReason")
                or claim_item.get("claimItemReason")
                or claim_item.get("reason")
            )
            for claim_item in claim_items
            if isinstance(claim_item, dict)
        ])

        for claim_item in claim_items:
            if not isinstance(claim_item, dict):
                continue
            line_id = str(claim_item.get("claimItemId") or claim_item.get("id") or "").strip()
            if line_id:
                all_line_ids.append(line_id)
                status_code = _extract_claim_status_code(claim_item.get("claimItemStatus") or claim_item.get("status"))
                if status_code.casefold() == "waitinginaction":
                    waiting_line_ids.append(line_id)
            status_code = _extract_claim_status_code(claim_item.get("claimItemStatus") or claim_item.get("status"))
            if status_code:
                all_statuses.append(status_code)
            reason_text = _extract_claim_reason_text(
                claim_item.get("customerClaimItemReason")
                or claim_item.get("trendyolClaimItemReason")
                or claim_item.get("claimItemReason")
                or claim_item.get("reason")
            )
            if reason_text:
                all_reasons.append(reason_text)

        unit_price = order_line.get("price")
        if unit_price in (None, ""):
            unit_price = entry_row.get("price")
        if unit_price in (None, ""):
            for claim_item in claim_items:
                if isinstance(claim_item, dict) and claim_item.get("price") not in (None, ""):
                    unit_price = claim_item.get("price")
                    break
        if unit_price in (None, ""):
            unit_price = order_line.get("amount")
        if unit_price in (None, ""):
            unit_price = entry_row.get("amount")
        if unit_price in (None, ""):
            for claim_item in claim_items:
                if isinstance(claim_item, dict) and claim_item.get("amount") not in (None, ""):
                    unit_price = claim_item.get("amount")
                    break

        amount_value = _safe_float(unit_price, default=0.0) * max(1, quantity)
        total_price += amount_value

        item_rows.append(
            {
                "name": str(order_line.get("productName") or entry_row.get("productName") or "-").strip() or "-",
                "sku": str(
                    order_line.get("merchantSku")
                    or order_line.get("sku")
                    or entry_row.get("merchantSku")
                    or entry_row.get("sku")
                    or "-"
                ).strip() or "-",
                "barcode": str(order_line.get("barcode") or entry_row.get("barcode") or "-").strip() or "-",
                "qty": max(1, quantity),
                "amount": amount_value,
                "image": "",
                "claimItemStatuses": line_statuses,
                "claimReasons": line_reasons,
            }
        )

    if root_status:
        all_statuses.append(root_status)
        if root_status.casefold() == "waitinginaction" and all_line_ids and not waiting_line_ids:
            waiting_line_ids.extend(all_line_ids)
    if root_reason:
        all_reasons.append(root_reason)

    unique_statuses = _unique_preserve_order(all_statuses)
    summary_status = ""
    if len(unique_statuses) == 1:
        summary_status = unique_statuses[0]
    else:
        for candidate in TRENDYOL_RETURN_STATUS_PRIORITY:
            if any(str(value).casefold() == candidate.casefold() for value in unique_statuses):
                summary_status = candidate
                break
        if not summary_status and unique_statuses:
            summary_status = unique_statuses[0]

    unique_reasons = _unique_preserve_order(all_reasons)
    summary_reason = " | ".join(unique_reasons[:3]).strip()

    return {
        "items": item_rows,
        "claimLineItemIds": _unique_preserve_order(all_line_ids),
        "waitingClaimLineItemIds": _unique_preserve_order(waiting_line_ids),
        "claimItemStatuses": unique_statuses,
        "claimReasons": unique_reasons,
        "claimItemStatus": summary_status,
        "claimReason": summary_reason,
        "itemCount": sum(max(1, _to_int(row.get("qty"), default=1)) for row in item_rows),
        "totalPrice": total_price,
    }


def normalize_return_claim(claim: dict, comp_api_account_id: int) -> dict:
    summary = _build_return_item_rows(claim if isinstance(claim, dict) else {})
    claim_row = claim if isinstance(claim, dict) else {}
    claim_id = str(claim_row.get("claimId") or claim_row.get("id") or "").strip()
    claim_number = str(claim_row.get("claimNumber") or claim_id).strip()
    last_modified = _to_int(
        claim_row.get("lastModifiedDate")
        or claim_row.get("claimDate")
        or claim_row.get("orderDate"),
        default=0,
    )

    return {
        "api_account_id": comp_api_account_id,
        "claimId": claim_id,
        "claimNumber": claim_number,
        "orderNumber": str(claim_row.get("orderNumber") or "").strip(),
        "orderShipmentPackageId": _to_int(claim_row.get("orderShipmentPackageId"), default=0) or None,
        "orderOutboundPackageId": _to_int(claim_row.get("orderOutboundPackageId"), default=0) or None,
        "customerFirstName": str(claim_row.get("customerFirstName") or "").strip(),
        "customerLastName": str(claim_row.get("customerLastName") or "").strip(),
        "cargoTrackingNumber": str(claim_row.get("cargoTrackingNumber") or "").strip(),
        "cargoTrackingLink": str(claim_row.get("cargoTrackingLink") or "").strip(),
        "cargoProviderName": str(claim_row.get("cargoProviderName") or "").strip(),
        "cargoSenderNumber": str(claim_row.get("cargoSenderNumber") or "").strip(),
        "claimDate": _to_int(claim_row.get("claimDate"), default=0) or None,
        "orderDate": _to_int(claim_row.get("orderDate"), default=0) or None,
        "lastModifiedDate": last_modified,
        "claimItemStatus": summary["claimItemStatus"],
        "claimReason": summary["claimReason"],
        "totalPrice": summary["totalPrice"],
        "currencyCode": str(claim_row.get("currencyCode") or "").strip(),
        "itemCount": summary["itemCount"],
        "claimLineItemIds": summary["claimLineItemIds"],
        "waitingClaimLineItemIds": summary["waitingClaimLineItemIds"],
        "claimItemStatuses": summary["claimItemStatuses"],
        "claimReasons": summary["claimReasons"],
        "itemsJson": summary["items"],
        "replacementOutboundPackageInfo": (
            claim_row.get("replacementOutboundPackageInfo")
            if isinstance(claim_row.get("replacementOutboundPackageInfo"), dict)
            else None
        ),
        "rejectedPackageInfo": (
            claim_row.get("rejectedPackageInfo")
            if isinstance(claim_row.get("rejectedPackageInfo"), dict)
            else None
        ),
        "rawData": claim_row,
    }


# -------------------------------------------------
# ✅ Progress Tracker (race-safe)
# -------------------------------------------------
@dataclass
class _ProgressTracker:
    total: int
    callback: Optional[Callable[[int, int], None]] = None

    def __post_init__(self) -> None:
        self.current: int = 0
        self._lock = asyncio.Lock()

    async def step(self, inc: int = 1) -> None:
        async with self._lock:
            self.current += inc
            if self.callback:
                # callback sync olabilir; UI thread bridge sende zaten var
                self.callback(self.current, self.total)


# -------------------------------------------------
# ✅ Normalization
# -------------------------------------------------
def normalize_order_data(order_data: dict, comp_api_account_id: int) -> tuple[list[dict], list[dict]]:
    """
    Tek bir order verisini normalize eder ve (orders, items) döner.
    """
    orders: list[dict] = []
    items: list[dict] = []

    # Şirket id ekle
    order_data["api_account_id"] = comp_api_account_id
    snapshot_id = _resolve_order_snapshot_id(order_data)
    if snapshot_id is not None:
        order_data["id"] = snapshot_id

    # packageHistories fix (bazı paketlerde 1 eleman geliyor)
    histories = order_data.get("packageHistories", []) or []
    if len(histories) == 1:
        histories.insert(0, {"createdDate": 0, "status": "Awaiting"})
        order_data["packageHistories"] = histories

    prepared_order = _prepare_order_data_row(order_data)
    if prepared_order is None:
        return orders, items

    orders.append(prepared_order)

    # OrderItem doldurma
    for order_item in prepared_order.get("lines", []) or []:
        order_item["api_account_id"] = comp_api_account_id
        order_item["orderNumber"] = prepared_order.get("orderNumber")
        order_item["order_data_id"] = prepared_order.get("id")
        order_item["snapshotLastModifiedDate"] = prepared_order.get("lastModifiedDate")
        if order_item.get("lineId") in (None, ""):
            order_item["lineId"] = (
                order_item.get("id")
                or order_item.get("productCode")
                or 0
            )
        order_item["packageHistories"] = prepared_order.get("packageHistories", [])

        # taskDate belirle
        task_date = 0
        for history in order_item["packageHistories"]:
            if history.get("status") == prepared_order.get("status"):
                task_date = history.get("createdDate", 0) or 0
                break
        order_item["taskDate"] = task_date

        items.append(order_item)

    return orders, items


def _split_status_query_windows(
    final_ep_time: int,
    start_ep_time: int,
    *,
    max_days: int = TRENDYOL_MAX_STATUS_QUERY_WINDOW_DAYS,
) -> list[tuple[int, int]]:
    start_ms = int(final_ep_time)
    end_ms = int(start_ep_time)
    if start_ms > end_ms:
        start_ms, end_ms = end_ms, start_ms

    span_ms = max(1, int(max_days)) * 24 * 60 * 60 * 1000
    windows: list[tuple[int, int]] = []
    cursor = start_ms
    while cursor <= end_ms:
        window_end = min(end_ms, cursor + span_ms - 1)
        windows.append((cursor, window_end))
        cursor = window_end + 1
    return windows


# -------------------------------------------------
# ✅ Fetch (single status)
# -------------------------------------------------
async def fetch_orders_for_status(
    api: TrendyolApi,
    status: str,
    comp_api_account_id: int,
    start_page: int,
    final_ep_time: int,
    start_ep_time: int,
    tracker: Optional[_ProgressTracker] = None,
) -> Result:
    orders: list[dict] = []
    items: list[dict] = []
    diagnostics = _new_order_sync_diagnostics(
        api_account_id=comp_api_account_id,
        environment=getattr(api, "environment", ""),
        status=status,
    )

    for window_start, window_end in _split_status_query_windows(final_ep_time, start_ep_time):
        diagnostics["windows_queried"] += 1
        page = int(start_page)

        while True:
            diagnostics["pages_queried"] += 1
            res = await api.find_orders(status, window_start, window_end, page)
            if not res.success:
                diagnostics["fetch_errors"] = int(diagnostics.get("fetch_errors", 0) or 0) + 1
                diagnostics["source_rows_complete"] = False
                diagnostics["fetch_error"] = {
                    "kind": "request_failed",
                    "page": page,
                    "status_code": int((res.data or {}).get("status_code") or 0),
                }
                return Result.fail(
                    f"API hatası ({status}) -> {res.message}",
                    error=res.error,
                    close_dialog=False,
                    data={
                        "orders": orders,
                        "items": items,
                        "sync_diagnostics": diagnostics,
                    },
                )

            response_data = dict(res.data or {})
            content = response_data.get("content", []) or []
            total_pages = max(0, int(response_data.get("totalPages") or 0))
            if not content:
                if total_pages and page + 1 < total_pages:
                    diagnostics["fetch_errors"] = int(diagnostics.get("fetch_errors", 0) or 0) + 1
                    diagnostics["source_rows_complete"] = False
                    diagnostics["fetch_error"] = {
                        "kind": "empty_page_before_reported_end",
                        "page": page,
                        "total_pages": total_pages,
                    }
                    return Result.fail(
                        f"API pagination eksik döndü ({status}, sayfa {page + 1}/{total_pages}).",
                        close_dialog=False,
                        data={
                            "orders": orders,
                            "items": items,
                            "sync_diagnostics": diagnostics,
                        },
                    )
                break

            diagnostics["source_rows_seen"] += len(content)
            for od in content:
                rejection_reason = _order_normalization_rejection_reason(od, comp_api_account_id)
                norm_orders, norm_items = normalize_order_data(od, comp_api_account_id)
                if not norm_orders:
                    _record_order_sync_rejection(
                        diagnostics,
                        rejection_reason,
                        status=str(od.get("status") or status),
                    )
                    continue
                orders.extend(norm_orders)
                items.extend(norm_items)
                diagnostics["normalized_order_rows"] += len(norm_orders)
                diagnostics["normalized_item_rows"] += len(norm_items)

            if total_pages and page + 1 >= total_pages:
                break
            page += 1

    if tracker is not None:
        await tracker.step(1)

    warning = order_sync_diagnostics_warning(diagnostics)
    message = f"{status} için siparişler çekildi."
    if warning:
        message = f"{message} {warning}"
    return Result.ok(
        message,
        close_dialog=False,
        data={"orders": orders, "items": items, "sync_diagnostics": diagnostics},
    )

async def fetch_orders_all(
    status_list: list[str],
    final_ep_time: int,
    start_ep_time: int,
    comp_api_account_list: list,
    start_page: int = 0,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Result:
    """
    comp_api_account_list elemanı örn:
      [pk, api_key, api_secret, seller_id, ...]
    """
    try:
        all_orders: list[dict] = []
        all_items: list[dict] = []
        aggregate_diagnostics = _new_order_sync_diagnostics()
        aggregate_diagnostics["runs"] = []

        total_steps = max(1, len(comp_api_account_list) * len(status_list))
        tracker = _ProgressTracker(total=total_steps, callback=progress_callback)

        for comp_api_account in comp_api_account_list:
            # güvenli unpack
            acc_pk = comp_api_account[0]
            api = TrendyolApi(**trendyol_account_payload_client_kwargs(comp_api_account))

            tasks = [
                fetch_orders_for_status(
                    api=api,
                    status=status,
                    comp_api_account_id=acc_pk,
                    start_page=start_page,
                    final_ep_time=final_ep_time,
                    start_ep_time=start_ep_time,
                    tracker=tracker,
                )
                for status in status_list
            ]

            results = await asyncio.gather(*tasks)

            for r in results:
                if not r.success:
                    return r
                all_orders.extend((r.data or {}).get("orders", []) or [])
                all_items.extend((r.data or {}).get("items", []) or [])
                run_diagnostics = dict((r.data or {}).get("sync_diagnostics") or {})
                _merge_order_sync_diagnostics(aggregate_diagnostics, run_diagnostics)
                aggregate_diagnostics["runs"].append(run_diagnostics)

        emitted_orders = _dedupe_order_snapshots_for_upsert(all_orders)
        emitted_items = _dedupe_order_items_for_upsert(all_items)
        aggregate_diagnostics["emitted_order_rows"] = len(emitted_orders)
        aggregate_diagnostics["emitted_item_rows"] = len(emitted_items)
        aggregate_diagnostics["duplicate_order_rows"] = len(all_orders) - len(emitted_orders)
        aggregate_diagnostics["duplicate_item_rows"] = len(all_items) - len(emitted_items)

        warning = order_sync_diagnostics_warning(aggregate_diagnostics)
        message = "Siparişler başarıyla çekildi."
        if warning:
            message = f"Siparişler eksik kaynak satırları raporlanarak çekildi. {warning}"
        return Result.ok(
            message,
            data={
                "order_data_list": emitted_orders,
                "order_item_list": emitted_items,
                "sync_diagnostics": aggregate_diagnostics,
            },
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e)


# -------------------------------------------------
# ✅ Last used update
# -------------------------------------------------
def update_last_used_at_for_accounts(
    comp_api_account_list: list,
    db_name: str = DB_NAME,
    safety_minutes: int = 0,
) -> None:
    """
    API'den sipariş çektikten sonra ilgili ApiAccount kayıtlarının last_used_at alanını günceller.
    ZAMAN DAMGASI: GMT+3

    safety_minutes:
      - 0 (default): Şu anki zamanı yazar
      - >0: DB'ye yazarken zamanı X dakika GERİYE çeker (ör: 15 -> now-15dk)
        Bu, last_used_at tabanlı throttling/filtre hatalarını azaltmak için güvenlik payıdır.
    """
    try:
        # safety_minutes güvenli hale getir
        try:
            safety = int(safety_minutes)
        except Exception:
            safety = 0
        if safety < 0:
            safety = 0

        # pk'leri topla (duplicate temizle)
        account_pks: list[int] = []
        for acc in (comp_api_account_list or []):
            if isinstance(acc, (list, tuple)) and len(acc) >= 1 and isinstance(acc[0], int):
                account_pks.append(acc[0])

        if not account_pks:
            return

        # unique
        account_pks = list(dict.fromkeys(account_pks))

        # zamanı hesapla (GMT+3)
        now_local = datetime.now(TZ_GMT3)
        stamp = now_local - timedelta(minutes=safety) if safety else now_local

        # güncelle
        for pk in account_pks:
            update_records(
                model=ApiAccount,
                filters={"pk": pk},
                update_data={"last_used_at": stamp},
                db_name=db_name,
            )

    except Exception as e:
        print(f"[last_used_at] update exception: {e}")


# -------------------------------------------------
# ✅ Save to DB (changed flag)
# -------------------------------------------------
def save_orders_to_db(result: Result, db_name: str = DB_NAME) -> Result:
    """
    worker.result_ready -> Result.success + Result.data = {"order_data_list": [...], "order_item_list": [...]}

    Dönüş:
      Result.data = {"changed": bool, "counts": {...}}
    """
    try:
        if not isinstance(result, Result):
            return Result.fail("Geçersiz result objesi alındı.")

        if not result.success:
            return result

        payload = result.data or {}
        raw_order_data_list: list[dict] = payload.get("order_data_list", []) or []
        order_item_list: list[dict] = payload.get("order_item_list", []) or []
        sync_diagnostics = dict(payload.get("sync_diagnostics") or {})
        sync_diagnostics["skipped_reasons"] = dict(sync_diagnostics.get("skipped_reasons") or {})
        order_data_list: list[dict] = []
        db_rejected_reasons: dict[str, int] = {}
        for row in raw_order_data_list:
            prepared = _prepare_order_data_row(row)
            if prepared is not None:
                order_data_list.append(prepared)
                continue
            reason = _order_normalization_rejection_reason(row, (row or {}).get("api_account_id"))
            reason = str(reason or ORDER_NORMALIZATION_REASON_REJECTED)
            db_rejected_reasons[reason] = int(db_rejected_reasons.get(reason, 0) or 0) + 1

        normalized_input_order_rows = len(order_data_list)
        order_data_list = _dedupe_order_snapshots_for_upsert(order_data_list)
        input_item_rows = len(order_item_list)
        order_item_list = _dedupe_order_items_for_upsert(order_item_list)
        sync_diagnostics["persistence"] = {
            "input_order_rows": len(raw_order_data_list),
            "eligible_order_rows": len(order_data_list),
            "rejected_order_rows": len(raw_order_data_list) - normalized_input_order_rows,
            "rejected_reasons": db_rejected_reasons,
            "duplicate_order_rows": normalized_input_order_rows - len(order_data_list),
            "input_item_rows": input_item_rows,
            "eligible_item_rows": len(order_item_list),
            "duplicate_item_rows": input_item_rows - len(order_item_list),
            "input_rows_complete": len(raw_order_data_list) == normalized_input_order_rows,
        }

        changed = False
        counts = {"headers_inserted": 0, "data_inserted": 0, "items_inserted": 0}

        # Header key set
        header_keys: set[tuple[str, int]] = {
            (od.get("orderNumber"), od.get("api_account_id"))
            for od in order_data_list
            if od.get("orderNumber") and od.get("api_account_id") is not None
        }
        snapshot_input_keys: set[tuple[int, int, int]] = {
            (
                int(od.get("id")),
                int(od.get("lastModifiedDate")),
                int(od.get("api_account_id")),
            )
            for od in order_data_list
            if od.get("id") not in (None, "")
            and od.get("lastModifiedDate") not in (None, "")
            and od.get("api_account_id") not in (None, "")
        }
        item_input_keys: set[tuple[int, int, int, int]] = {
            (
                int(oi.get("order_data_id")),
                int(oi.get("snapshotLastModifiedDate")),
                int(oi.get("lineId")),
                int(oi.get("api_account_id")),
            )
            for oi in order_item_list
            if oi.get("order_data_id") not in (None, "")
            and oi.get("snapshotLastModifiedDate") not in (None, "")
            and oi.get("lineId") not in (None, "")
            and oi.get("api_account_id") not in (None, "")
        }
        existing_header_keys: set[tuple[str, int]] = set()
        existing_snapshot_keys: set[tuple[int, int, int]] = set()
        existing_item_keys: set[tuple[int, int, int, int]] = set()
        with Session(get_engine(db_name)) as session:
            if header_keys:
                rows = session.exec(
                    select(OrderHeader).where(
                        OrderHeader.orderNumber.in_(sorted({key[0] for key in header_keys})),
                        OrderHeader.api_account_id.in_(sorted({key[1] for key in header_keys})),
                    )
                ).all() or []
                existing_header_keys = {
                    (str(row.orderNumber or "").strip(), int(row.api_account_id))
                    for row in rows
                    if (str(row.orderNumber or "").strip(), int(row.api_account_id)) in header_keys
                }
            if snapshot_input_keys:
                rows = session.exec(
                    select(OrderData).where(
                        OrderData.id.in_(sorted({key[0] for key in snapshot_input_keys})),
                        OrderData.api_account_id.in_(sorted({key[2] for key in snapshot_input_keys})),
                    )
                ).all() or []
                existing_snapshot_keys = {
                    (int(row.id), int(row.lastModifiedDate), int(row.api_account_id))
                    for row in rows
                    if (int(row.id), int(row.lastModifiedDate), int(row.api_account_id)) in snapshot_input_keys
                }
            if item_input_keys:
                rows = session.exec(
                    select(OrderItem).where(
                        OrderItem.order_data_id.in_(sorted({key[0] for key in item_input_keys})),
                        OrderItem.api_account_id.in_(sorted({key[3] for key in item_input_keys})),
                    )
                ).all() or []
                for row in rows:
                    key = (
                        int(row.order_data_id or 0),
                        int(row.snapshotLastModifiedDate or 0),
                        int(row.lineId or 0),
                        int(row.api_account_id or 0),
                    )
                    if key in item_input_keys:
                        existing_item_keys.add(key)

        write_account_ids = sorted(
            {key[1] for key in header_keys}
            | {key[2] for key in snapshot_input_keys}
            | {key[3] for key in item_input_keys}
        )
        account_counts = {
            account_id: {
                "api_account_id": account_id,
                "headers_inserted": len(
                    {key for key in header_keys if key[1] == account_id} - existing_header_keys
                ),
                "headers_already_present": len(
                    {key for key in header_keys if key[1] == account_id} & existing_header_keys
                ),
                "order_snapshots_inserted": len(
                    {key for key in snapshot_input_keys if key[2] == account_id} - existing_snapshot_keys
                ),
                "order_snapshots_updated": 0,
                "order_snapshots_already_present": len(
                    {key for key in snapshot_input_keys if key[2] == account_id} & existing_snapshot_keys
                ),
                "item_rows_inserted": len(
                    {key for key in item_input_keys if key[3] == account_id} - existing_item_keys
                ),
                "item_rows_updated": 0,
                "item_rows_already_present": len(
                    {key for key in item_input_keys if key[3] == account_id} & existing_item_keys
                ),
            }
            for account_id in write_account_ids
        }

        if not header_keys and not order_item_list:
            return Result.ok(
                "Kaydedilecek sipariş yok.",
                close_dialog=False,
                data={
                    "changed": False,
                    "counts": counts,
                    "account_counts": [],
                    "sync_diagnostics": sync_diagnostics,
                },
            )

        # 1) Header upsert
        if header_keys:
            res_headers = create_records(
                model=OrderHeader,
                data_list=[
                    {"orderNumber": order_number, "api_account_id": api_account_id}
                    for order_number, api_account_id in header_keys
                ],
                db_name=db_name,
                conflict_keys=["orderNumber", "api_account_id"],
                mode="ignore",
            )
            if not res_headers.success:
                return res_headers

            inserted = (res_headers.data or {}).get("inserted", 0) or 0
            counts["headers_inserted"] = inserted
            if inserted > 0:
                changed = True

        # 2) Header pk map (sadece gerekli)
        header_pk_map: dict[tuple[str, int], int] = {}
        if header_keys:
            order_numbers = {k[0] for k in header_keys}
            api_account_ids = {k[1] for k in header_keys}

            res_header_rows = get_records(
                model=OrderHeader,
                db_name=db_name,
                filters={
                    "orderNumber": list(order_numbers),
                    "api_account_id": list(api_account_ids),
                },
            )
            if not res_header_rows.success:
                return res_header_rows

            header_rows = (res_header_rows.data or {}).get("records", []) or []
            header_pk_map = {
                (h.orderNumber, h.api_account_id): h.pk
                for h in header_rows
            }

        # 3) OrderData -> order_header_id
        for od in order_data_list:
            key = (od.get("orderNumber"), od.get("api_account_id"))
            od["order_header_id"] = header_pk_map.get(key)

        if order_data_list:
            res_data = create_records(
                model=OrderData,
                data_list=order_data_list,
                db_name=db_name,
                conflict_keys=ORDERDATA_UNIQ,
                mode="ignore",
                normalizer=ORDERDATA_NORMALIZER,
                chunk_size=1000,
                drop_unknown=True,
                rename_map={"3pByTrendyol": "byTrendyol3"},
            )
            if not res_data.success:
                return res_data

            inserted = (res_data.data or {}).get("inserted", 0) or 0
            counts["data_inserted"] = inserted
            if inserted > 0:
                changed = True

        order_data_pk_map: dict[tuple[int | None, int, int], tuple[int | None, int | None]] = {}
        order_data_lookup_keys = {
            (
                od.get("api_account_id"),
                _to_int(od.get("id"), default=0),
                _to_int(od.get("lastModifiedDate"), default=0),
            )
            for od in order_data_list
            if _to_int(od.get("id"), default=0) > 0 and _to_int(od.get("lastModifiedDate"), default=0) > 0
        }
        if order_data_lookup_keys:
            with Session(get_engine(db_name)) as session:
                order_numbers = sorted(
                    {
                        str(od.get("orderNumber") or "").strip()
                        for od in order_data_list
                        if str(od.get("orderNumber") or "").strip()
                    }
                )
                api_account_ids = sorted(
                    {
                        int(od.get("api_account_id"))
                        for od in order_data_list
                        if od.get("api_account_id") not in (None, "")
                    }
                )
                stmt = select(OrderData)
                if order_numbers:
                    stmt = stmt.where(OrderData.orderNumber.in_(order_numbers))
                if api_account_ids:
                    stmt = stmt.where(OrderData.api_account_id.in_(api_account_ids))
                for row in session.exec(stmt).all() or []:
                    key = (
                        getattr(row, "api_account_id", None),
                        _to_int(getattr(row, "id", None), default=0),
                        _to_int(getattr(row, "lastModifiedDate", None), default=0),
                    )
                    if key[1] <= 0 or key[2] <= 0:
                        continue
                    order_data_pk_map[key] = (
                        getattr(row, "pk", None),
                        getattr(row, "order_header_id", None),
                    )

        # 4) OrderItem -> order_header_id + order_data_pk
        for oi in order_item_list:
            key = (oi.get("orderNumber"), oi.get("api_account_id"))
            order_header_id = header_pk_map.get(key)
            lookup_key = (
                oi.get("api_account_id"),
                _to_int(oi.get("order_data_id"), default=0),
                _to_int(oi.get("snapshotLastModifiedDate"), default=0),
            )
            order_data_pk, mapped_order_header_id = order_data_pk_map.get(lookup_key, (None, None))
            oi["order_data_pk"] = order_data_pk
            oi["order_header_id"] = order_header_id or mapped_order_header_id

        if order_item_list:
            res_items = create_records(
                model=OrderItem,
                data_list=order_item_list,
                db_name=db_name,
                conflict_keys=ORDERITEM_UNIQ,
                mode="ignore",
                normalizer=ORDERITEM_NORMALIZER,
                chunk_size=1000,
                drop_unknown=True,
                rename_map={"3pByTrendyol": "byTrendyol3"},
            )
            if not res_items.success:
                return res_items

            inserted = (res_items.data or {}).get("inserted", 0) or 0
            counts["items_inserted"] = inserted
            if inserted > 0:
                changed = True

        return Result.ok(
            "Siparişler başarıyla veritabanına kaydedildi.",
            close_dialog=False,
            data={
                "changed": changed,
                "counts": counts,
                "account_counts": [account_counts[key] for key in sorted(account_counts)],
                "sync_diagnostics": sync_diagnostics,
            },
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e)


def build_orders_sync_observability(
    fetch_result: Result,
    save_result: Result,
    *,
    account_ids: list[int] | tuple[int, ...] | None = None,
    account_records: list[Any] | tuple[Any, ...] | None = None,
    return_claim_rows: list[dict] | tuple[dict, ...] | None = None,
    returns_save_data: dict | None = None,
    start_ms: int | None = None,
    end_ms: int | None = None,
    db_name: str | None = None,
) -> dict[str, Any]:
    """Build a PII-free sync summary and independently read persisted source rows.

    Trendyol order snapshots are immutable in the local schema.  Therefore an
    exact ``(package id, lastModifiedDate, account)`` lookup is stronger than a
    generic "save returned success" assertion and also distinguishes newly
    inserted snapshots from already-present/idempotently skipped snapshots.
    The helper lives in Orders so both manual UI and agent runtimes can share
    the same accounting contract.
    """

    def _value(row: Any, key: str, default: Any = None) -> Any:
        if isinstance(row, dict):
            return row.get(key, default)
        return getattr(row, key, default)

    def _positive_int(value: Any) -> int | None:
        try:
            parsed = int(value)
        except Exception:
            return None
        return parsed if parsed > 0 else None

    fetch_data = dict(fetch_result.data or {}) if isinstance(fetch_result.data, dict) else {}
    save_data = dict(save_result.data or {}) if isinstance(save_result.data, dict) else {}
    order_rows = [dict(row) for row in list(fetch_data.get("order_data_list") or []) if isinstance(row, dict)]
    item_rows = [dict(row) for row in list(fetch_data.get("order_item_list") or []) if isinstance(row, dict)]
    claim_rows = [dict(row) for row in list(return_claim_rows or []) if isinstance(row, dict)]
    diagnostics = normalize_order_sync_diagnostics_policy(
        dict(fetch_data.get("sync_diagnostics") or {})
    )
    persistence = dict((save_data.get("sync_diagnostics") or {}).get("persistence") or {})
    save_counts = dict(save_data.get("counts") or {})
    return_counts = dict((returns_save_data or {}).get("counts") or {})
    save_account_counts = {
        int(row.get("api_account_id")): dict(row)
        for row in list(save_data.get("account_counts") or [])
        if isinstance(row, dict) and _positive_int(row.get("api_account_id")) is not None
    }
    diagnostic_runs_by_account: dict[int, dict[str, int]] = {}
    for run in list(diagnostics.get("runs") or []):
        if not isinstance(run, dict):
            continue
        account_pk = _positive_int(run.get("api_account_id"))
        if account_pk is None:
            continue
        current = diagnostic_runs_by_account.setdefault(
            account_pk,
            {
                "source_rows_seen": 0,
                "source_rows_skipped": 0,
                "source_rows_policy_excluded": 0,
                "fetch_errors": 0,
            },
        )
        current["source_rows_seen"] += int(run.get("source_rows_seen") or 0)
        current["source_rows_skipped"] += int(run.get("skipped_source_rows") or 0)
        current["source_rows_policy_excluded"] += int(
            run.get("policy_excluded_source_rows") or 0
        )
        current["fetch_errors"] += int(run.get("fetch_errors") or 0)

    requested_accounts = _normalize_api_account_ids(account_ids)
    record_by_id: dict[int, Any] = {}
    for record in list(account_records or []):
        account_pk = _positive_int(_value(record, "pk"))
        if account_pk is not None:
            record_by_id[account_pk] = record
            if account_pk not in requested_accounts:
                requested_accounts.append(account_pk)

    snapshot_keys: set[tuple[int, int, int]] = set()
    header_keys: set[tuple[str, int]] = set()
    item_keys: set[tuple[int, int, int, int]] = set()
    claim_keys: set[tuple[str, int, int]] = set()
    order_numbers_by_snapshot: dict[tuple[int, int, int], str] = {}

    for row in order_rows:
        account_pk = _positive_int(row.get("api_account_id"))
        snapshot_id = _positive_int(row.get("id") or row.get("shipmentPackageId"))
        last_modified = _positive_int(row.get("lastModifiedDate"))
        order_number = str(row.get("orderNumber") or "").strip()
        if account_pk is not None and account_pk not in requested_accounts:
            requested_accounts.append(account_pk)
        if account_pk is not None and order_number:
            header_keys.add((order_number, account_pk))
        if account_pk is not None and snapshot_id is not None and last_modified is not None:
            key = (snapshot_id, last_modified, account_pk)
            snapshot_keys.add(key)
            order_numbers_by_snapshot[key] = order_number

    for row in item_rows:
        account_pk = _positive_int(row.get("api_account_id"))
        snapshot_id = _positive_int(row.get("order_data_id"))
        last_modified = _positive_int(
            row.get("snapshotLastModifiedDate") or row.get("lastModifiedDate")
        )
        line_id = _positive_int(
            row.get("lineId")
            or row.get("lineItemId")
            or row.get("orderLineItemId")
            or row.get("id")
            or row.get("productCode")
        )
        if all(value is not None for value in (snapshot_id, last_modified, line_id, account_pk)):
            item_keys.add((snapshot_id, last_modified, line_id, account_pk))

    for row in claim_rows:
        account_pk = _positive_int(row.get("api_account_id"))
        claim_id = str(row.get("claimId") or row.get("claim_id") or "").strip()
        last_modified = _positive_int(row.get("lastModifiedDate") or row.get("last_modified_date"))
        if claim_id and account_pk is not None and last_modified is not None:
            claim_keys.add((claim_id, last_modified, account_pk))

    found_snapshot_keys: set[tuple[int, int, int]] = set()
    found_header_keys: set[tuple[str, int]] = set()
    found_item_keys: set[tuple[int, int, int, int]] = set()
    found_claim_keys: set[tuple[str, int, int]] = set()
    with Session(get_engine(db_name or DB_NAME)) as session:
        if snapshot_keys:
            snapshot_ids = sorted({key[0] for key in snapshot_keys})
            account_scope = sorted({key[2] for key in snapshot_keys})
            rows = session.exec(
                select(OrderData).where(
                    OrderData.id.in_(snapshot_ids),
                    OrderData.api_account_id.in_(account_scope),
                )
            ).all() or []
            found_snapshot_keys = {
                (int(row.id), int(row.lastModifiedDate), int(row.api_account_id))
                for row in rows
                if (int(row.id), int(row.lastModifiedDate), int(row.api_account_id)) in snapshot_keys
            }
        if header_keys:
            numbers = sorted({key[0] for key in header_keys})
            account_scope = sorted({key[1] for key in header_keys})
            rows = session.exec(
                select(OrderHeader).where(
                    OrderHeader.orderNumber.in_(numbers),
                    OrderHeader.api_account_id.in_(account_scope),
                )
            ).all() or []
            found_header_keys = {
                (str(row.orderNumber or "").strip(), int(row.api_account_id))
                for row in rows
                if (str(row.orderNumber or "").strip(), int(row.api_account_id)) in header_keys
            }
        if item_keys:
            snapshot_ids = sorted({key[0] for key in item_keys})
            account_scope = sorted({key[3] for key in item_keys})
            rows = session.exec(
                select(OrderItem).where(
                    OrderItem.order_data_id.in_(snapshot_ids),
                    OrderItem.api_account_id.in_(account_scope),
                )
            ).all() or []
            for row in rows:
                key = (
                    int(row.order_data_id or 0),
                    int(row.snapshotLastModifiedDate or 0),
                    int(row.lineId or 0),
                    int(row.api_account_id or 0),
                )
                if key in item_keys:
                    found_item_keys.add(key)
        if claim_keys:
            claim_ids = sorted({key[0] for key in claim_keys})
            account_scope = sorted({key[2] for key in claim_keys})
            rows = session.exec(
                select(ReturnClaim).where(
                    ReturnClaim.claimId.in_(claim_ids),
                    ReturnClaim.api_account_id.in_(account_scope),
                )
            ).all() or []
            for row in rows:
                key = (
                    str(row.claimId or "").strip(),
                    int(row.lastModifiedDate or 0),
                    int(row.api_account_id or 0),
                )
                if key in claim_keys:
                    found_claim_keys.add(key)

    missing_snapshots = snapshot_keys - found_snapshot_keys
    missing_headers = header_keys - found_header_keys
    missing_items = item_keys - found_item_keys
    missing_claims = claim_keys - found_claim_keys
    exact_key_count = len(snapshot_keys) + len(item_keys) + len(claim_keys)
    source_contract_present = isinstance(fetch_data.get("sync_diagnostics"), dict)
    identifiers_complete = (
        len(snapshot_keys) == len(order_rows)
        and len(item_keys) == len(item_rows)
        and len(claim_keys) == len(claim_rows)
    )
    source_complete = (
        diagnostics.get("source_rows_complete", True) is not False
        and int(diagnostics.get("fetch_errors") or 0) == 0
    )
    readback_verified = identifiers_complete and not any(
        (missing_snapshots, missing_headers, missing_items, missing_claims)
    )

    per_account: list[dict[str, Any]] = []
    for account_pk in sorted(requested_accounts):
        record = record_by_id.get(account_pk)
        extra = _value(record, "extra_config", {})
        extra = dict(extra or {}) if isinstance(extra, dict) else {}
        environment = str(extra.get("environment") or "production").strip().casefold()
        environment = "stage" if environment in {"stage", "staging", "test", "sandbox"} else "production"
        account_snapshots = {key for key in snapshot_keys if key[2] == account_pk}
        account_items = {key for key in item_keys if key[3] == account_pk}
        account_claims = {key for key in claim_keys if key[2] == account_pk}
        account_headers = {key for key in header_keys if key[1] == account_pk}
        account_writes = dict(save_account_counts.get(account_pk) or {})
        account_diagnostics = dict(diagnostic_runs_by_account.get(account_pk) or {})
        if not account_diagnostics and len(requested_accounts) == 1:
            account_diagnostics = {
                "source_rows_seen": int(diagnostics.get("source_rows_seen") or len(order_rows)),
                "source_rows_skipped": int(diagnostics.get("skipped_source_rows") or 0),
                "source_rows_policy_excluded": int(
                    diagnostics.get("policy_excluded_source_rows") or 0
                ),
                "fetch_errors": int(diagnostics.get("fetch_errors") or 0),
            }
        per_account.append(
            {
                "api_account_id": account_pk,
                "store": str(_value(record, "comp_name", "") or "").strip(),
                "seller_id": str(_value(record, "account_id", "") or "").strip(),
                "environment": environment,
                "remote_order_snapshots": len(account_snapshots),
                "remote_unique_orders": len(account_headers),
                "remote_item_rows": len(account_items),
                "remote_return_snapshots": len(account_claims),
                "headers_inserted": int(account_writes.get("headers_inserted") or 0),
                "headers_already_present": int(account_writes.get("headers_already_present") or 0),
                "order_snapshots_inserted": int(account_writes.get("order_snapshots_inserted") or 0),
                "order_snapshots_updated": 0,
                "order_snapshots_already_present": int(account_writes.get("order_snapshots_already_present") or 0),
                "item_rows_inserted": int(account_writes.get("item_rows_inserted") or 0),
                "item_rows_updated": 0,
                "item_rows_already_present": int(account_writes.get("item_rows_already_present") or 0),
                "source_rows_seen": int(account_diagnostics.get("source_rows_seen") or 0),
                "source_rows_skipped": int(account_diagnostics.get("source_rows_skipped") or 0),
                "source_rows_policy_excluded": int(
                    account_diagnostics.get("source_rows_policy_excluded") or 0
                ),
                "fetch_errors": int(account_diagnostics.get("fetch_errors") or 0),
                "db_order_snapshots_found": len(account_snapshots & found_snapshot_keys),
                "db_item_rows_found": len(account_items & found_item_keys),
                "db_return_snapshots_found": len(account_claims & found_claim_keys),
                "readback_verified": not any(
                    (
                        account_snapshots - found_snapshot_keys,
                        account_headers - found_header_keys,
                        account_items - found_item_keys,
                        account_claims - found_claim_keys,
                    )
                ),
            }
        )

    eligible_orders = int(persistence.get("eligible_order_rows") or len(snapshot_keys))
    eligible_items = int(persistence.get("eligible_item_rows") or len(item_keys))
    orders_inserted = int(save_counts.get("data_inserted") or save_counts.get("orders_inserted") or save_counts.get("orders_upserted") or 0)
    items_inserted = int(save_counts.get("items_inserted") or 0)
    fetched_unique_orders = len({key[0:2] for key in header_keys})
    fetched = {
        "source_rows_seen": int(diagnostics.get("source_rows_seen") or len(order_rows)),
        "policy_excluded_source_rows": int(
            diagnostics.get("policy_excluded_source_rows") or 0
        ),
        "order_snapshots": len(snapshot_keys),
        "unique_orders": fetched_unique_orders,
        "item_rows": len(item_keys),
        "return_snapshots": len(claim_keys),
    }
    writes = {
        "headers_inserted": int(save_counts.get("headers_inserted") or 0),
        "order_snapshots_inserted": orders_inserted,
        "order_snapshots_updated": 0,
        "order_snapshots_already_present": max(0, eligible_orders - orders_inserted),
        "item_rows_inserted": items_inserted,
        "item_rows_updated": 0,
        "item_rows_already_present": max(0, eligible_items - items_inserted),
        "return_snapshots_inserted": int(return_counts.get("claims_inserted") or return_counts.get("claims_upserted") or 0),
        "return_snapshots_restored": int(return_counts.get("claims_restored") or 0),
    }
    skipped = {
        "source_rows": int(diagnostics.get("skipped_source_rows") or 0),
        "source_reasons": dict(diagnostics.get("skipped_reasons") or {}),
        "persistence_rejected_order_rows": int(persistence.get("rejected_order_rows") or 0),
        "persistence_duplicate_order_rows": int(persistence.get("duplicate_order_rows") or 0),
        "persistence_duplicate_item_rows": int(persistence.get("duplicate_item_rows") or 0),
    }
    excluded = {
        "source_rows": int(diagnostics.get("policy_excluded_source_rows") or 0),
        "source_reasons": dict(diagnostics.get("policy_excluded_reasons") or {}),
        "policy": "non_actionable_awaiting_without_persistent_package_identity",
    }
    errors = {
        "fetch_errors": int(diagnostics.get("fetch_errors") or 0),
        "count": int(diagnostics.get("fetch_errors") or 0),
    }
    readback = {
        "required": source_contract_present,
        "verified": readback_verified,
        "verified_by": (
            "db_exact_immutable_source_keys"
            if exact_key_count
            else "empty_remote_source_set"
            if identifiers_complete
            else "source_identity_contract_incomplete"
        ),
        "source_identity_contract_complete": identifiers_complete,
        "requested_order_snapshots": len(snapshot_keys),
        "found_order_snapshots": len(found_snapshot_keys),
        "requested_order_headers": len(header_keys),
        "found_order_headers": len(found_header_keys),
        "requested_item_rows": len(item_keys),
        "found_item_rows": len(found_item_keys),
        "requested_return_snapshots": len(claim_keys),
        "found_return_snapshots": len(found_claim_keys),
        "missing_order_snapshots": len(missing_snapshots),
        "missing_order_headers": len(missing_headers),
        "missing_item_rows": len(missing_items),
        "missing_return_snapshots": len(missing_claims),
        "missing_order_numbers": sorted(
            {
                order_numbers_by_snapshot.get(key, "")
                for key in missing_snapshots
                if order_numbers_by_snapshot.get(key, "")
            }
        )[:50],
    }
    watermark = {
        "requested_start_ms": int(start_ms or 0),
        "requested_end_ms": int(end_ms or 0),
        "source_rows_complete": source_complete,
        "db_readback_verified": readback_verified,
        "fresh_through_ms": int(end_ms or 0) if source_complete and readback_verified else 0,
    }
    return {
        "accounts": per_account,
        "fetched": fetched,
        "writes": writes,
        "skipped": skipped,
        "excluded": excluded,
        "errors": errors,
        "watermark": watermark,
        "db_readback": readback,
    }


def save_return_claims_to_db(result: Result, db_name: str = DB_NAME) -> Result:
    try:
        if not isinstance(result, Result):
            return Result.fail("Geçersiz result objesi alındı.")
        if not result.success:
            return result

        payload = result.data or {}
        claim_rows = payload.get("return_claim_list", []) or []
        if not claim_rows:
            return Result.ok(
                "Kaydedilecek iade kaydı yok.",
                close_dialog=False,
                data={"changed": False, "counts": {"claims_inserted": 0}},
            )

        header_pk_map: dict[tuple[str, int | None], int | None] = {}
        package_header_map: dict[tuple[int | None, int], int | None] = {}
        order_numbers = sorted(
            {
                str(row.get("orderNumber") or "").strip()
                for row in claim_rows
                if str(row.get("orderNumber") or "").strip()
            }
        )
        shipment_package_ids = sorted(
            {
                int(row.get("orderShipmentPackageId"))
                for row in claim_rows
                if row.get("orderShipmentPackageId") not in (None, "")
            }
        )
        api_account_ids = sorted(
            {
                int(row.get("api_account_id"))
                for row in claim_rows
                if row.get("api_account_id") not in (None, "")
            }
        )
        if order_numbers or shipment_package_ids:
            with Session(get_engine(db_name)) as session:
                if order_numbers:
                    stmt = select(OrderHeader).where(OrderHeader.orderNumber.in_(order_numbers))
                    if api_account_ids:
                        stmt = stmt.where(OrderHeader.api_account_id.in_(api_account_ids))
                    for row in session.exec(stmt).all() or []:
                        header_pk_map[
                            (
                                str(getattr(row, "orderNumber", "") or "").strip(),
                                getattr(row, "api_account_id", None),
                            )
                        ] = getattr(row, "pk", None)
                if shipment_package_ids:
                    data_stmt = select(OrderData).where(OrderData.shipmentPackageId.in_(shipment_package_ids))
                    if api_account_ids:
                        data_stmt = data_stmt.where(OrderData.api_account_id.in_(api_account_ids))
                    for row in session.exec(data_stmt).all() or []:
                        package_id = _to_int(getattr(row, "shipmentPackageId", None), default=0)
                        if package_id <= 0:
                            continue
                        package_header_map[(getattr(row, "api_account_id", None), package_id)] = getattr(
                            row,
                            "order_header_id",
                            None,
                        )

        for claim_row in claim_rows:
            key = (
                str(claim_row.get("orderNumber") or "").strip(),
                claim_row.get("api_account_id"),
            )
            package_key = (
                claim_row.get("api_account_id"),
                _to_int(claim_row.get("orderShipmentPackageId"), default=0),
            )
            claim_row["order_header_id"] = header_pk_map.get(key) or package_header_map.get(package_key)

        res = create_records(
            model=ReturnClaim,
            data_list=claim_rows,
            db_name=db_name,
            conflict_keys=RETURNCLAIM_UNIQ,
            mode="ignore",
            normalizer=RETURNCLAIM_NORMALIZER,
            chunk_size=500,
            drop_unknown=True,
        )
        if not res.success:
            return res

        inserted = int((res.data or {}).get("inserted", 0) or 0)
        restored = _restore_return_claims_from_fresh_payload(claim_rows, db_name=db_name)
        return Result.ok(
            "İadeler veritabanına kaydedildi.",
            close_dialog=False,
            data={
                "changed": inserted > 0 or restored > 0,
                "counts": {"claims_inserted": inserted, "claims_restored": restored},
            },
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def _fresh_return_claim_keys(claim_rows: list[dict]) -> set[tuple[int | None, str]]:
    keys: set[tuple[int | None, str]] = set()
    for row in claim_rows or []:
        if not isinstance(row, dict):
            continue
        claim_id = str(row.get("claimId") or row.get("id") or "").strip()
        if not claim_id:
            continue
        account_id = row.get("api_account_id")
        try:
            account_id = int(account_id) if account_id not in (None, "") else None
        except Exception:
            account_id = None
        keys.add((account_id, claim_id))
    return keys


def _restore_return_claims_from_fresh_payload(claim_rows: list[dict], *, db_name: str = DB_NAME) -> int:
    keys = _fresh_return_claim_keys(claim_rows)
    if not keys:
        return 0
    claim_ids = sorted({claim_id for _account_id, claim_id in keys if claim_id})
    account_ids = sorted({int(account_id) for account_id, _claim_id in keys if account_id is not None})
    restored = 0
    with Session(get_engine(db_name)) as session:
        stmt = select(ReturnClaim).where(ReturnClaim.claimId.in_(claim_ids))
        if account_ids:
            stmt = stmt.where(ReturnClaim.api_account_id.in_(account_ids))
        rows = session.exec(stmt).all() or []
        for row in rows:
            key = (getattr(row, "api_account_id", None), str(getattr(row, "claimId", "") or "").strip())
            if key not in keys:
                continue
            if getattr(row, "sync_deleted_at", None):
                row.sync_deleted_at = None
                restored += 1
        if restored:
            session.commit()
    return restored


def mark_return_claims_stale(
    *,
    claim_ids: list[str],
    api_account_ids: Optional[list[int]] = None,
    claim_keys: Optional[list[dict[str, Any]]] = None,
    reason: str = "",
    db_name: str = DB_NAME,
) -> Result:
    try:
        exact_keys: set[tuple[int | None, str]] = set()
        for row in claim_keys or []:
            if not isinstance(row, dict):
                continue
            claim_id = str(row.get("claim_id") or row.get("claimId") or "").strip()
            if not claim_id:
                continue
            account_id = row.get("api_account_id")
            try:
                account_id = int(account_id) if account_id not in (None, "") else None
            except Exception:
                account_id = None
            exact_keys.add((account_id, claim_id))
        normalized_claim_ids = [
            str(claim_id or "").strip()
            for claim_id in (claim_ids or [])
            if str(claim_id or "").strip()
        ]
        normalized_claim_ids.extend(claim_id for _account_id, claim_id in exact_keys)
        normalized_claim_ids = list(dict.fromkeys(normalized_claim_ids))
        if not normalized_claim_ids:
            return Result.fail("Stale isaretlenecek claim id gerekir.", close_dialog=False)

        normalized_account_ids = _normalize_api_account_ids(api_account_ids)
        if exact_keys:
            normalized_account_ids = sorted(
                {
                    *normalized_account_ids,
                    *[int(account_id) for account_id, _claim_id in exact_keys if account_id is not None],
                }
            )
        marker = datetime.now(TZ_GMT3).isoformat()
        changed = 0
        matched = 0
        rows_out: list[dict[str, Any]] = []
        with Session(get_engine(db_name)) as session:
            stmt = select(ReturnClaim).where(ReturnClaim.claimId.in_(normalized_claim_ids))
            if normalized_account_ids:
                stmt = stmt.where(ReturnClaim.api_account_id.in_(normalized_account_ids))
            rows = session.exec(stmt).all() or []
            matched = len(rows)
            for row in rows:
                key = (getattr(row, "api_account_id", None), str(getattr(row, "claimId", "") or "").strip())
                if exact_keys and key not in exact_keys:
                    continue
                before = getattr(row, "sync_deleted_at", None)
                if not before:
                    row.sync_deleted_at = marker
                    changed += 1
                rows_out.append(
                    {
                        "pk": getattr(row, "pk", None),
                        "api_account_id": getattr(row, "api_account_id", None),
                        "claim_id": getattr(row, "claimId", None),
                        "order_number": getattr(row, "orderNumber", None),
                        "last_modified_date": getattr(row, "lastModifiedDate", None),
                        "before_sync_deleted_at": before,
                        "after_sync_deleted_at": getattr(row, "sync_deleted_at", None),
                    }
                )
            if changed:
                session.commit()

        return Result.ok(
            f"{changed} iade claim snapshot stale isaretlendi.",
            close_dialog=False,
            data={
                "changed": changed > 0,
                "matched": matched,
                "stale_marked": changed,
                "claim_ids": normalized_claim_ids,
                "api_account_ids": normalized_account_ids,
                "sync_deleted_at": marker if changed else None,
                "reason": str(reason or "").strip(),
                "rows": rows_out,
            },
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


# -------------------------------------------------
# ✅ Runtime filter helpers
# -------------------------------------------------
def get_order_record_date(order) -> date | None:
    for attr in ("shipmentDate", "orderDate", "createdDate", "claimDate"):
        value = getattr(order, attr, None)
        coerced = coerce_to_date(value)
        if coerced:
            return coerced
    return None


def resolve_order_record_platform_code(order) -> str:
    direct_code = canonical_platform_code(getattr(order, "platform", None))
    if direct_code:
        return direct_code
    api_account = getattr(order, "api_account", None)
    return canonical_platform_code(getattr(api_account, "platform", None))


def summarize_order_shipping_deadline(order, *, now_ms: int | None = None) -> dict:
    if order is None or bool(getattr(order, "_is_return", False)):
        return {"text": "", "is_overdue": False, "deadline_ms": None, "delta_ms": None}

    raw_status = getattr(order, "shipmentPackageStatus", None) or getattr(order, "status", None)
    if _normalize_runtime_status_code(raw_status) != "Created":
        return {"text": "", "is_overdue": False, "deadline_ms": None, "delta_ms": None}

    deadline_ms = _coerce_epoch_ms(getattr(order, "agreedDeliveryDate", None))
    if deadline_ms is None:
        return {"text": "", "is_overdue": False, "deadline_ms": None, "delta_ms": None}

    current_ms = int(now_ms) if now_ms is not None else _now_epoch_ms()
    delta_ms = int(deadline_ms - current_ms)
    duration_text = _format_shipping_delta_parts(delta_ms)
    text = f"{duration_text} gecikti" if delta_ms < 0 else f"{duration_text} var kargolamaya"
    return {
        "text": text,
        "is_overdue": delta_ms < 0,
        "deadline_ms": deadline_ms,
        "delta_ms": delta_ms,
    }


def classify_order_shipping_deadline(order, *, now_ms: int | None = None) -> str:
    summary = summarize_order_shipping_deadline(order, now_ms=now_ms)
    deadline_ms = summary.get("deadline_ms")
    if deadline_ms is None:
        return ""

    delta_ms = int(summary.get("delta_ms") or 0)
    if delta_ms < 0:
        return "overdue"

    current_ms = int(now_ms) if now_ms is not None else _now_epoch_ms()
    deadline_day = datetime.fromtimestamp(int(deadline_ms) / 1000, tz=TZ_GMT3).date()
    current_day = datetime.fromtimestamp(int(current_ms) / 1000, tz=TZ_GMT3).date()
    if deadline_day <= current_day:
        return "due_today"
    return "sufficient_time"


def filter_order_records_in_memory(records: list, filters: dict) -> Result:
    try:
        filtered = list(records or [])
        explicit_now_ms = filters.get("now_ms")
        if explicit_now_ms in (None, ""):
            explicit_now_ms = None
        else:
            try:
                explicit_now_ms = int(explicit_now_ms)
            except Exception:
                explicit_now_ms = None

        processed_mode = filters.get("processed_mode", "all")
        global_text = str(filters.get("global", "") or "").lower().strip()
        order_no = str(filters.get("order_no", "") or "").lower().strip()
        cargo = filters.get("cargo")
        raw_platform = filters.get("platform_code") or filters.get("platform") or ""
        platform_code = "" if _is_all_like_filter_value(raw_platform) else canonical_platform_code(raw_platform)
        customer = str(filters.get("customer", "") or "").lower().strip()
        raw_shipment_status = filters.get("shipment_status_code") or filters.get("shipment_status") or ""
        shipment_status = "" if _is_all_like_filter_value(raw_shipment_status) else str(raw_shipment_status).strip()
        tracking_no = str(filters.get("tracking_no", "") or "").lower().strip()
        raw_deadline_category = filters.get("deadline_category", "") or ""
        deadline_category = str(raw_deadline_category).strip().casefold()
        date_enabled = bool(filters.get("date_enabled", False))
        date_from = filters.get("date_from")
        date_to = filters.get("date_to")

        def _to_local_float(value: str) -> float | None:
            text = str(value or "").strip().replace(",", ".")
            if not text:
                return None
            try:
                return float(text)
            except Exception:
                return None

        amount_min = _to_local_float(filters.get("amount_min", ""))
        amount_max = _to_local_float(filters.get("amount_max", ""))

        selected_statuses = _selected_filter_statuses(shipment_status)
        use_cargo_filter = bool(cargo and not _is_all_like_filter_value(cargo))
        use_status_filter = bool(selected_statuses)
        use_deadline_filter = bool(deadline_category and not _is_all_like_filter_value(deadline_category))
        use_amount_filter = amount_min is not None or amount_max is not None
        use_date_filter = bool(date_enabled and date_from and date_to)
        selected_status_key_set = {
            _normalize_runtime_status_code(status).casefold()
            for status in selected_statuses
            if _normalize_runtime_status_code(status)
        }

        out = []
        for record in filtered:
            if processed_mode in ("pending", "processed"):
                is_printed = bool(getattr(record, "is_printed", False))
                is_extracted = bool(getattr(record, "is_extracted", False))
                if processed_mode == "pending":
                    if is_printed or is_extracted:
                        continue
                elif not (is_printed or is_extracted):
                    continue

            if order_no:
                if (
                    order_no not in str(getattr(record, "orderNumber", "")).lower()
                    and order_no not in str(getattr(record, "claimNumber", "")).lower()
                    and order_no not in str(getattr(record, "claimId", "")).lower()
                ):
                    continue

            if use_cargo_filter and getattr(record, "cargoProviderName", None) != cargo:
                continue

            if platform_code and resolve_order_record_platform_code(record) != platform_code:
                continue

            if customer:
                customer_text = (
                    str(getattr(record, "customerFirstName", "") or "")
                    + " "
                    + str(getattr(record, "customerLastName", "") or "")
                ).lower()
                if customer not in customer_text:
                    continue

            if use_status_filter:
                record_status_key_set = {
                    _normalize_runtime_status_code(getattr(record, "shipmentPackageStatus", None)).casefold(),
                    _normalize_runtime_status_code(getattr(record, "claimItemStatus", None)).casefold(),
                    _normalize_runtime_status_code(getattr(record, "status", "")).casefold(),
                }
                record_status_key_set.discard("")
                if not (record_status_key_set & selected_status_key_set):
                    continue

            if tracking_no and tracking_no not in str(getattr(record, "cargoTrackingNumber", "")).lower():
                continue

            if use_deadline_filter and classify_order_shipping_deadline(record, now_ms=explicit_now_ms) != deadline_category:
                continue

            if use_amount_filter:
                try:
                    total_price = float(getattr(record, "totalPrice", 0) or 0)
                except Exception:
                    total_price = 0.0
                if amount_min is not None and total_price < amount_min:
                    continue
                if amount_max is not None and total_price > amount_max:
                    continue

            if use_date_filter:
                record_date = get_order_record_date(record)
                if not record_date or not (date_from <= record_date <= date_to):
                    continue

            if global_text:
                haystack = " ".join(
                    str(getattr(record, field, "") or "").lower()
                    for field in (
                        "orderNumber",
                        "claimNumber",
                        "claimId",
                        "claimReason",
                        "cargoProviderName",
                        "customerFirstName",
                        "customerLastName",
                        "cargoTrackingNumber",
                        "shipmentPackageStatus",
                        "status",
                    )
                )
                if global_text in haystack:
                    out.append(record)
                    continue

                try:
                    loaded_items = vars(record).get("items", None)
                except TypeError:
                    loaded_items = None
                loaded_items = list(loaded_items or []) if isinstance(loaded_items, list) else []
                in_items = any(
                    global_text in str(getattr(item, "productName", "")).lower()
                    or global_text in str(getattr(item, "merchantSku", "")).lower()
                    or global_text in str(getattr(item, "sku", "")).lower()
                    or global_text in str(getattr(item, "barcode", "")).lower()
                    for item in loaded_items
                )
                if not in_items:
                    continue

            out.append(record)

        return Result.ok("Filtre uygulandı.", close_dialog=False, data={"filtered": out})

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


# -------------------------------------------------
# ✅ Queries
# -------------------------------------------------
def get_latest_ready_to_ship_orders(
    *,
    api_account_ids: Optional[list[int]] = None,
    db_name: str | None = None,
) -> Result:
    return get_latest_orders(
        shipment_statuses=["Created", "Picking", "ReadyToShip"],
        api_account_ids=api_account_ids,
        db_name=db_name,
        exclude_simulated=True,
    )


def get_latest_orders_filtered(
    *,
    shipment_statuses: Optional[list[str]] = None,
    platform_codes: Optional[list[str]] = None,
    start_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
    order_numbers: Optional[list[str]] = None,
    api_account_ids: Optional[list[int]] = None,
    db_name: str | None = None,
) -> Result:
    return get_latest_orders(
        shipment_statuses=shipment_statuses,
        platform_codes=platform_codes,
        start_ms=start_ms,
        end_ms=end_ms,
        order_numbers=order_numbers,
        api_account_ids=api_account_ids,
        db_name=db_name,
        exclude_simulated=True,
    )


def get_latest_orders(
    *,
    shipment_statuses: Optional[list[str]] = None,
    platform_codes: Optional[list[str]] = None,
    start_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
    order_numbers: Optional[list[str]] = None,
    api_account_ids: Optional[list[int]] = None,
    db_name: str | None = None,
    exclude_simulated: bool = False,
) -> Result:
    """
    Her sipariş için en güncel snapshot'ı OrderHeader JOIN ile döndürür.
    Opsiyonel olarak shipment status filtrelemesi yapılabilir.
    Runtime olarak OrderData instance'larına ek alanlar basılır:
        - is_extracted, is_printed, extracted_at, printed_at
    """
    try:
        normalized_order_numbers = _normalize_order_numbers(order_numbers)
        normalized_api_account_ids = _normalize_api_account_ids(api_account_ids)
        engine = _engine(db_name)
        normalized_platform_codes = _normalize_platform_codes(platform_codes)
        with Session(engine) as session:
            simulated_excluded = 0
            if exclude_simulated:
                simulated_groups = select(
                    OrderData.api_account_id,
                    OrderData.orderNumber,
                ).where(~_exclude_simulated_order_sql(OrderData.orderNumber, OrderData.cargoProviderName))
                if start_ms is not None:
                    simulated_groups = simulated_groups.where(func.coalesce(OrderData.orderDate, 0) >= int(start_ms))
                if end_ms is not None:
                    simulated_groups = simulated_groups.where(func.coalesce(OrderData.orderDate, 0) <= int(end_ms))
                if normalized_order_numbers:
                    simulated_groups = simulated_groups.where(OrderData.orderNumber.in_(normalized_order_numbers))
                if normalized_api_account_ids:
                    simulated_groups = simulated_groups.where(OrderData.api_account_id.in_(normalized_api_account_ids))
                simulated_subq = simulated_groups.group_by(OrderData.api_account_id, OrderData.orderNumber).subquery()
                simulated_excluded = int(session.exec(select(func.count()).select_from(simulated_subq)).one() or 0)

            subq_base = select(
                OrderData.api_account_id,
                OrderData.orderNumber,
                func.max(OrderData.lastModifiedDate).label("max_date"),
            )
            if normalized_order_numbers:
                subq_base = subq_base.where(OrderData.orderNumber.in_(normalized_order_numbers))
            if normalized_api_account_ids:
                subq_base = subq_base.where(OrderData.api_account_id.in_(normalized_api_account_ids))
            if exclude_simulated:
                subq_base = subq_base.where(
                    _exclude_simulated_order_sql(OrderData.orderNumber, OrderData.cargoProviderName)
                )
            if start_ms is not None:
                subq_base = subq_base.where(func.coalesce(OrderData.orderDate, 0) >= int(start_ms))
            if end_ms is not None:
                subq_base = subq_base.where(func.coalesce(OrderData.orderDate, 0) <= int(end_ms))
            subq = subq_base.group_by(OrderData.api_account_id, OrderData.orderNumber).subquery()

            OD = aliased(OrderData)

            stmt = (
                select(OD)
                .join(
                    subq,
                    or_(
                        OD.api_account_id == subq.c.api_account_id,
                        and_(OD.api_account_id.is_(None), subq.c.api_account_id.is_(None)),
                    )
                    & (OD.orderNumber == subq.c.orderNumber)
                    & (OD.lastModifiedDate == subq.c.max_date),
                )
                .outerjoin(
                    OrderHeader,
                    or_(
                        OrderHeader.api_account_id == OD.api_account_id,
                        and_(OrderHeader.api_account_id.is_(None), OD.api_account_id.is_(None)),
                    )
                    & (OrderHeader.orderNumber == OD.orderNumber),
                )
                .outerjoin(
                    ApiAccount,
                    ApiAccount.pk == OD.api_account_id,
                )
                .options(
                    contains_eager(OD.api_account),
                    contains_eager(OD.header),
                )
            )
            if exclude_simulated:
                stmt = stmt.where(
                    _exclude_simulated_order_sql(OD.orderNumber, OD.cargoProviderName)
                )

            normalized_statuses: list[str] = []
            for requested_status in shipment_statuses or []:
                raw_status = str(requested_status or "").strip()
                canonical_status = canonical_order_status_code(raw_status)
                # Keep the persisted/raw code as well as its canonical form.
                # Historical snapshots can legitimately contain aliases such
                # as ReadyToShip while newer records use Created. Conversely,
                # provider-independent callers can send snake_case names that
                # only the canonical form can match in storage.
                for candidate in (raw_status, canonical_status):
                    if candidate and candidate not in normalized_statuses:
                        normalized_statuses.append(candidate)
            if normalized_statuses:
                stmt = stmt.where(
                    or_(
                        OD.shipmentPackageStatus.in_(normalized_statuses),
                        OD.status.in_(normalized_statuses),
                    )
                )
            if normalized_platform_codes:
                stmt = stmt.where(func.upper(func.coalesce(ApiAccount.platform, "")).in_(normalized_platform_codes))
            if normalized_api_account_ids:
                stmt = stmt.where(OD.api_account_id.in_(normalized_api_account_ids))
            if start_ms is not None:
                stmt = stmt.where(func.coalesce(OD.orderDate, 0) >= int(start_ms))
            if end_ms is not None:
                stmt = stmt.where(func.coalesce(OD.orderDate, 0) <= int(end_ms))

            rows: list[OrderData] = session.exec(stmt).all() or []
            latest_order_rows: dict[tuple[int | None, str], OrderData] = {}
            for row in rows:
                key = (
                    getattr(row, "api_account_id", None),
                    str(getattr(row, "orderNumber", "") or "").strip(),
                )
                current = latest_order_rows.get(key)
                if current is None or int(getattr(row, "pk", 0) or 0) > int(getattr(current, "pk", 0) or 0):
                    latest_order_rows[key] = row
            rows = list(latest_order_rows.values())

            for od in rows:
                h = od.header
                if h:
                    object.__setattr__(od, "is_extracted", bool(h.is_extracted))
                    object.__setattr__(od, "is_printed", bool(h.is_printed))
                    object.__setattr__(od, "extracted_at", h.extracted_at)
                    object.__setattr__(od, "printed_at", h.printed_at)
                else:
                    object.__setattr__(od, "is_extracted", False)
                    object.__setattr__(od, "is_printed", False)
                    object.__setattr__(od, "extracted_at", None)
                    object.__setattr__(od, "printed_at", None)

        return Result.ok(
            f"En güncel sipariş snapshotları çekildi (toplam: {len(rows)})",
            data={"orders": rows, "simulated_excluded": simulated_excluded},
            close_dialog=False,
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def restore_return_claims_from_stale(
    *,
    claim_ids: list[str],
    api_account_ids: Optional[list[int]] = None,
    claim_keys: Optional[list[dict[str, Any]]] = None,
    reason: str = "",
    db_name: str = DB_NAME,
) -> Result:
    try:
        exact_keys: set[tuple[int | None, str]] = set()
        for row in claim_keys or []:
            if not isinstance(row, dict):
                continue
            claim_id = str(row.get("claim_id") or row.get("claimId") or "").strip()
            if not claim_id:
                continue
            account_id = row.get("api_account_id")
            try:
                account_id = int(account_id) if account_id not in (None, "") else None
            except Exception:
                account_id = None
            exact_keys.add((account_id, claim_id))
        normalized_claim_ids = [
            str(claim_id or "").strip()
            for claim_id in (claim_ids or [])
            if str(claim_id or "").strip()
        ]
        normalized_claim_ids.extend(claim_id for _account_id, claim_id in exact_keys)
        normalized_claim_ids = list(dict.fromkeys(normalized_claim_ids))
        if not normalized_claim_ids:
            return Result.fail("Geri alinacak stale claim id gerekir.", close_dialog=False)

        normalized_account_ids = _normalize_api_account_ids(api_account_ids)
        if exact_keys:
            normalized_account_ids = sorted(
                {
                    *normalized_account_ids,
                    *[int(account_id) for account_id, _claim_id in exact_keys if account_id is not None],
                }
            )
        changed = 0
        matched = 0
        rows_out: list[dict[str, Any]] = []
        with Session(get_engine(db_name)) as session:
            stmt = select(ReturnClaim).where(ReturnClaim.claimId.in_(normalized_claim_ids))
            if normalized_account_ids:
                stmt = stmt.where(ReturnClaim.api_account_id.in_(normalized_account_ids))
            rows = session.exec(stmt).all() or []
            matched = len(rows)
            for row in rows:
                key = (getattr(row, "api_account_id", None), str(getattr(row, "claimId", "") or "").strip())
                if exact_keys and key not in exact_keys:
                    continue
                before = getattr(row, "sync_deleted_at", None)
                if before:
                    row.sync_deleted_at = None
                    changed += 1
                rows_out.append(
                    {
                        "pk": getattr(row, "pk", None),
                        "api_account_id": getattr(row, "api_account_id", None),
                        "claim_id": getattr(row, "claimId", None),
                        "order_number": getattr(row, "orderNumber", None),
                        "last_modified_date": getattr(row, "lastModifiedDate", None),
                        "before_sync_deleted_at": before,
                        "after_sync_deleted_at": getattr(row, "sync_deleted_at", None),
                    }
                )
            if changed:
                session.commit()

        return Result.ok(
            f"{changed} stale iade claim snapshot geri alindi.",
            close_dialog=False,
            data={
                "changed": changed > 0,
                "matched": matched,
                "restored": changed,
                "claim_ids": normalized_claim_ids,
                "api_account_ids": normalized_account_ids,
                "reason": str(reason or "").strip(),
                "rows": rows_out,
            },
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def _hydrate_return_claim_runtime(claim: ReturnClaim, api_accounts_by_id: dict[int, ApiAccount]) -> None:
    api_account = api_accounts_by_id.get(getattr(claim, "api_account_id", None))
    items_json = list(getattr(claim, "itemsJson", None) or [])

    item_namespaces = [
        SimpleNamespace(
            productName=str(item.get("name") or "-"),
            merchantSku=str(item.get("sku") or "-"),
            sku=str(item.get("sku") or "-"),
            barcode=str(item.get("barcode") or "-"),
            quantity=max(1, _to_int(item.get("qty"), default=1)),
            amount=item.get("amount"),
        )
        for item in items_json
        if isinstance(item, dict)
    ]

    object.__setattr__(claim, "api_account", api_account)
    object.__setattr__(claim, "status", str(getattr(claim, "claimItemStatus", "") or ""))
    object.__setattr__(claim, "shipmentPackageStatus", str(getattr(claim, "claimItemStatus", "") or ""))
    object.__setattr__(claim, "items", item_namespaces)
    object.__setattr__(claim, "shipmentAddress", {})
    object.__setattr__(claim, "invoiceAddress", {})
    object.__setattr__(claim, "_return_items", items_json)
    object.__setattr__(claim, "_is_return", True)
    object.__setattr__(claim, "_selected", bool(getattr(claim, "_selected", False)))


def get_latest_return_claims(
    *,
    start_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
    claim_statuses: Optional[list[str]] = None,
    platform_codes: Optional[list[str]] = None,
    claim_ids: Optional[list[str]] = None,
    api_account_ids: Optional[list[int]] = None,
    db_name: str | None = None,
) -> Result:
    try:
        engine = _engine(db_name)
        normalized_platform_codes = _normalize_platform_codes(platform_codes)
        with Session(engine) as session:
            base_subq = (
                select(
                    ReturnClaim.api_account_id,
                    ReturnClaim.claimId,
                    func.max(ReturnClaim.lastModifiedDate).label("max_last_modified"),
                )
                .where(ReturnClaim.sync_deleted_at.is_(None))
                .group_by(ReturnClaim.api_account_id, ReturnClaim.claimId)
            )

            normalized_claim_ids = [
                str(row or "").strip()
                for row in (claim_ids or [])
                if str(row or "").strip()
            ]
            if normalized_claim_ids:
                base_subq = base_subq.where(ReturnClaim.claimId.in_(normalized_claim_ids))

            normalized_api_account_ids = [int(row) for row in (api_account_ids or []) if row is not None]
            if normalized_api_account_ids:
                base_subq = base_subq.where(ReturnClaim.api_account_id.in_(normalized_api_account_ids))
            normalized_claim_statuses = [str(row or "").strip() for row in (claim_statuses or []) if str(row or "").strip()]

            subq = base_subq.subquery()
            RC = aliased(ReturnClaim)
            stmt = (
                select(RC)
                .join(
                    subq,
                    or_(
                        RC.api_account_id == subq.c.api_account_id,
                        and_(RC.api_account_id.is_(None), subq.c.api_account_id.is_(None)),
                    )
                    & (RC.claimId == subq.c.claimId)
                    & (RC.lastModifiedDate == subq.c.max_last_modified),
                )
            )
            if normalized_platform_codes:
                stmt = stmt.join(ApiAccount, ApiAccount.pk == RC.api_account_id)
                stmt = stmt.where(func.upper(func.coalesce(ApiAccount.platform, "")).in_(normalized_platform_codes))

            if start_ms is not None:
                stmt = stmt.where(func.coalesce(RC.claimDate, RC.orderDate, 0) >= int(start_ms))
            if end_ms is not None:
                stmt = stmt.where(func.coalesce(RC.claimDate, RC.orderDate, 0) <= int(end_ms))
            if normalized_claim_statuses:
                stmt = stmt.where(RC.claimItemStatus.in_(normalized_claim_statuses))
            stmt = stmt.where(RC.sync_deleted_at.is_(None))

            rows: list[ReturnClaim] = session.exec(stmt).all() or []
            latest_claim_rows: dict[tuple[int | None, str], ReturnClaim] = {}
            for row in rows:
                key = (
                    getattr(row, "api_account_id", None),
                    str(getattr(row, "claimId", "") or "").strip(),
                )
                current = latest_claim_rows.get(key)
                if current is None or int(getattr(row, "pk", 0) or 0) > int(getattr(current, "pk", 0) or 0):
                    latest_claim_rows[key] = row
            rows = list(latest_claim_rows.values())

        api_account_ids_from_rows = {
            getattr(row, "api_account_id", None)
            for row in rows
            if getattr(row, "api_account_id", None) is not None
        }
        api_accounts_by_id: dict[int, ApiAccount] = {}
        if api_account_ids_from_rows:
            acc_res = get_records(
                model=ApiAccount,
                db_name=db_name or DB_NAME,
                filters={"pk": list(api_account_ids_from_rows)},
            )
            if not acc_res.success:
                return acc_res
            api_accounts_by_id = {
                acc.pk: acc
                for acc in ((acc_res.data or {}).get("records", []) or [])
                if getattr(acc, "pk", None) is not None
            }

        rows.sort(
            key=lambda row: (
                _to_int(getattr(row, "claimDate", None) or getattr(row, "orderDate", None), default=0),
                str(getattr(row, "claimId", "") or ""),
            ),
            reverse=True,
        )
        for row in rows:
            _hydrate_return_claim_runtime(row, api_accounts_by_id)

        return Result.ok(
            f"En güncel iadeler çekildi (toplam: {len(rows)})",
            close_dialog=False,
            data={"claims": rows},
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def get_latest_return_claims_filtered(
    *,
    start_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
    claim_statuses: Optional[list[str]] = None,
    platform_codes: Optional[list[str]] = None,
    claim_ids: Optional[list[str]] = None,
    api_account_ids: Optional[list[int]] = None,
    db_name: str | None = None,
) -> Result:
    return get_latest_return_claims(
        start_ms=start_ms,
        end_ms=end_ms,
        claim_statuses=claim_statuses,
        platform_codes=platform_codes,
        claim_ids=claim_ids,
        api_account_ids=api_account_ids,
        db_name=db_name,
    )


def get_stale_return_claims(
    *,
    start_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
    claim_ids: Optional[list[str]] = None,
    api_account_ids: Optional[list[int]] = None,
    db_name: str = DB_NAME,
) -> Result:
    try:
        normalized_claim_ids = [
            str(row or "").strip()
            for row in (claim_ids or [])
            if str(row or "").strip()
        ]
        normalized_api_account_ids = [int(row) for row in (api_account_ids or []) if row is not None]
        with Session(get_engine(db_name)) as session:
            base_subq = (
                select(
                    ReturnClaim.api_account_id,
                    ReturnClaim.claimId,
                    func.max(ReturnClaim.lastModifiedDate).label("max_last_modified"),
                )
                .where(ReturnClaim.sync_deleted_at.is_not(None))
                .group_by(ReturnClaim.api_account_id, ReturnClaim.claimId)
            )
            if normalized_claim_ids:
                base_subq = base_subq.where(ReturnClaim.claimId.in_(normalized_claim_ids))
            if normalized_api_account_ids:
                base_subq = base_subq.where(ReturnClaim.api_account_id.in_(normalized_api_account_ids))

            subq = base_subq.subquery()
            RC = aliased(ReturnClaim)
            stmt = (
                select(RC)
                .join(
                    subq,
                    or_(
                        RC.api_account_id == subq.c.api_account_id,
                        and_(RC.api_account_id.is_(None), subq.c.api_account_id.is_(None)),
                    )
                    & (RC.claimId == subq.c.claimId)
                    & (RC.lastModifiedDate == subq.c.max_last_modified),
                )
                .where(RC.sync_deleted_at.is_not(None))
            )
            if start_ms is not None:
                stmt = stmt.where(func.coalesce(RC.claimDate, RC.orderDate, 0) >= int(start_ms))
            if end_ms is not None:
                stmt = stmt.where(func.coalesce(RC.claimDate, RC.orderDate, 0) <= int(end_ms))
            rows: list[ReturnClaim] = session.exec(stmt).all() or []

            account_ids = {
                getattr(row, "api_account_id", None)
                for row in rows
                if getattr(row, "api_account_id", None) is not None
            }
            api_accounts_by_id = {}
            if account_ids:
                accounts = session.exec(select(ApiAccount).where(ApiAccount.pk.in_(list(account_ids)))).all() or []
                api_accounts_by_id = {
                    int(getattr(account, "pk")): account
                    for account in accounts
                    if getattr(account, "pk", None) is not None
                }

        rows.sort(
            key=lambda row: (
                _to_int(getattr(row, "claimDate", None) or getattr(row, "orderDate", None), default=0),
                str(getattr(row, "claimId", "") or ""),
            ),
            reverse=True,
        )
        for row in rows:
            _hydrate_return_claim_runtime(row, api_accounts_by_id)

        return Result.ok(
            f"Stale isaretli iadeler cekildi (toplam: {len(rows)})",
            close_dialog=False,
            data={"claims": rows},
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def get_latest_order_items_by_numbers(
    order_numbers: list[str],
    *,
    api_account_ids: Optional[list[int]] = None,
    db_name: str | None = None,
) -> Result:
    try:
        normalized_numbers = _normalize_order_numbers(order_numbers)
        if not normalized_numbers:
            return Result.ok("Sipariş numarası bulunamadı.", close_dialog=False, data={"items": []})

        normalized_account_ids = _normalize_api_account_ids(api_account_ids)
        engine = _engine(db_name)
        with Session(engine) as session:
            latest_subq = (
                select(
                    OrderData.api_account_id,
                    OrderData.orderNumber,
                    func.max(OrderData.lastModifiedDate).label("max_last_modified"),
                )
                .where(OrderData.orderNumber.in_(normalized_numbers))
            )
            if normalized_account_ids:
                latest_subq = latest_subq.where(OrderData.api_account_id.in_(normalized_account_ids))
            latest_subq = latest_subq.group_by(OrderData.api_account_id, OrderData.orderNumber).subquery()

            latest_data = aliased(OrderData)
            stmt = (
                select(OrderItem)
                .join(
                    latest_data,
                    or_(
                        OrderItem.order_data_pk == latest_data.pk,
                        OrderItem.order_data_pk.is_(None)
                        & (OrderItem.order_data_id == latest_data.id)
                        & (OrderItem.snapshotLastModifiedDate == latest_data.lastModifiedDate)
                        & (OrderItem.api_account_id == latest_data.api_account_id),
                    ),
                )
                .join(
                    latest_subq,
                    (latest_data.api_account_id == latest_subq.c.api_account_id)
                    & (latest_data.orderNumber == latest_subq.c.orderNumber)
                    & (latest_data.lastModifiedDate == latest_subq.c.max_last_modified),
                )
                .where(OrderItem.orderNumber.in_(normalized_numbers))
                .order_by(OrderItem.orderNumber, OrderItem.lineId, OrderItem.id)
            )
            if normalized_account_ids:
                stmt = stmt.where(OrderItem.api_account_id.in_(normalized_account_ids))

            rows: list[OrderItem] = session.exec(stmt).all() or []

        return Result.ok(
            f"En güncel sipariş ürünleri çekildi ({len(rows)})",
            close_dialog=False,
            data={"items": rows},
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def get_order_full_details_by_numbers(
    order_numbers: list,
    *,
    mode: str = "all",
    order_refs: list[dict] | None = None,
    db_name: str | None = None,
) -> Result:
    """
    Verilen sipariş numaraları için header + data + items + (store_name/platform) döner.

    mode:
      - "all"    (default): Her header'ın TÜM OrderData snapshot'larını döndürür
      - "latest"          : Her header için sadece EN GÜNCEL OrderData snapshot'ını döndürür (DB seviyesinde)

    Not:
      - orders[*]["data"] her zaman LIST döner.
        mode="latest" iken liste 0/1 elemanlı olur.
      - store_name/platform snapshot üzerinden değil, header.api_account_id -> ApiAccount üzerinden verilir.
        Böylece DetachedInstanceError riski sıfırlanır.
    """
    try:
        resolved_db_name = str(db_name or DB_NAME)
        if not order_numbers:
            return Result.fail("Sipariş numarası listesi boş.", close_dialog=False)

        mode = (mode or "all").strip().lower()
        if mode not in ("all", "latest"):
            mode = "all"

        normalized = _normalize_order_numbers(order_numbers)
        if not normalized:
            return Result.fail("Geçerli sipariş numarası bulunamadı.", close_dialog=False)

        requested_ref_pairs: set[tuple[str, int]] = set()
        for ref in order_refs or []:
            if not isinstance(ref, dict):
                continue
            order_number = str(ref.get("orderNumber") or ref.get("order_number") or "").strip()
            try:
                api_account_id = int(ref.get("api_account_id"))
            except Exception:
                continue
            if order_number and api_account_id > 0:
                requested_ref_pairs.add((order_number, api_account_id))
        if order_refs is not None and not requested_ref_pairs:
            return Result.fail("Geçerli account-scoped sipariş referansı bulunamadı.", close_dialog=False)

        # ----------------------------------------------------
        # 1) Headers
        # ----------------------------------------------------
        header_filters: dict[str, Any] = {"orderNumber": normalized}
        if requested_ref_pairs:
            header_filters["api_account_id"] = sorted({pair[1] for pair in requested_ref_pairs})
        res_headers = get_records(
            model=OrderHeader,
            db_name=resolved_db_name,
            filters=header_filters,
        )
        if not res_headers.success:
            return res_headers

        headers: list[OrderHeader] = (res_headers.data or {}).get("records", []) or []
        if requested_ref_pairs:
            headers = [
                header
                for header in headers
                if (
                    str(getattr(header, "orderNumber", "") or "").strip(),
                    _to_int(getattr(header, "api_account_id", None), default=0),
                ) in requested_ref_pairs
            ]
        if not headers:
            return Result.ok(
                "Verilen sipariş numaraları için kayıt bulunamadı.",
                close_dialog=False,
                data={"orders": [], "headers": [], "order_data_list": [], "order_item_list": []},
            )

        header_pks = [h.pk for h in headers if getattr(h, "pk", None) is not None]
        if not header_pks:
            return Result.ok(
                "Header bulundu ancak PK bilgisi alınamadı.",
                close_dialog=False,
                data={"orders": [], "headers": headers, "order_data_list": [], "order_item_list": []},
            )

        # ----------------------------------------------------
        # 2) ApiAccounts (lazy'e dokunmadan ayrı çek)
        # ----------------------------------------------------
        header_api_account_ids = {
            getattr(h, "api_account_id", None)
            for h in headers
            if getattr(h, "api_account_id", None) is not None
        }

        api_accounts_by_id: dict[int, ApiAccount] = {}
        if header_api_account_ids:
            res_acc = get_records(
                model=ApiAccount,
                db_name=resolved_db_name,
                filters={"pk": list(header_api_account_ids)},
            )
            if not res_acc.success:
                return res_acc

            api_list: list[ApiAccount] = (res_acc.data or {}).get("records", []) or []
            api_accounts_by_id = {
                acc.pk: acc
                for acc in api_list
                if getattr(acc, "pk", None) is not None
            }

        # ----------------------------------------------------
        # 3) OrderData
        # ----------------------------------------------------
        if mode == "all":
            res_data = get_records(
                model=OrderData,
                db_name=resolved_db_name,
                filters={"order_header_id": header_pks},
            )
            if not res_data.success:
                return res_data
            order_data_list: list[OrderData] = (res_data.data or {}).get("records", []) or []
        else:
            engine = _engine(resolved_db_name)
            with Session(engine) as session:
                subq = (
                    select(
                        OrderData.order_header_id,
                        func.max(OrderData.lastModifiedDate).label("max_last_modified"),
                    )
                    .where(OrderData.order_header_id.in_(header_pks))
                    .group_by(OrderData.order_header_id)
                    .subquery()
                )

                OD = aliased(OrderData)

                stmt = (
                    select(OD)
                    .join(
                        subq,
                        (OD.order_header_id == subq.c.order_header_id)
                        & (OD.lastModifiedDate == subq.c.max_last_modified),
                    )
                )

                order_data_list: list[OrderData] = session.exec(stmt).all() or []

        # ----------------------------------------------------
        # 4) OrderItem
        # ----------------------------------------------------
        item_filters: dict[str, list[int] | list[str]] = {"order_header_id": header_pks}
        latest_item_pairs: set[tuple[int, int]] = set()
        latest_order_data_pk_set: set[int] = set()
        if mode == "latest":
            latest_order_data_ids: list[int] = []
            latest_order_data_pks: list[int] = []
            for od in order_data_list:
                order_data_pk = getattr(od, "pk", None)
                order_data_id = getattr(od, "id", None)
                snapshot_last_modified = getattr(od, "lastModifiedDate", None)
                if order_data_pk is not None:
                    latest_order_data_pks.append(int(order_data_pk))
                    latest_order_data_pk_set.add(int(order_data_pk))
                if order_data_id is None:
                    continue
                latest_order_data_ids.append(int(order_data_id))
                if snapshot_last_modified not in (None, ""):
                    latest_item_pairs.add((int(order_data_id), int(snapshot_last_modified)))
            if latest_order_data_pks:
                item_filters = {"order_data_pk": latest_order_data_pks}
            elif latest_order_data_ids:
                item_filters = {"order_data_id": latest_order_data_ids}

        res_items = get_records(
            model=OrderItem,
            db_name=resolved_db_name,
            filters=item_filters,
        )
        if not res_items.success:
            return res_items
        order_item_list: list[OrderItem] = (res_items.data or {}).get("records", []) or []
        if mode == "latest" and latest_item_pairs:
            order_item_list = [
                oi
                for oi in order_item_list
                if (
                    (
                        getattr(oi, "order_data_pk", None) is not None
                        and int(getattr(oi, "order_data_pk")) in latest_order_data_pk_set
                    )
                    or (
                        getattr(oi, "order_data_id", None) is not None
                        and getattr(oi, "snapshotLastModifiedDate", None) not in (None, "")
                        and (int(getattr(oi, "order_data_id")), int(getattr(oi, "snapshotLastModifiedDate")))
                        in latest_item_pairs
                    )
                )
            ]

        # ----------------------------------------------------
        # 5) Map'ler
        # ----------------------------------------------------
        data_by_header: dict[int, list[OrderData]] = {}
        for od in order_data_list:
            hid = getattr(od, "order_header_id", None)
            if hid is not None:
                data_by_header.setdefault(hid, []).append(od)

        items_by_header: dict[int, list[OrderItem]] = {}
        for oi in order_item_list:
            hid = getattr(oi, "order_header_id", None)
            if hid is not None:
                items_by_header.setdefault(hid, []).append(oi)

        # ----------------------------------------------------
        # 6) orders list
        # ----------------------------------------------------
        orders = []
        for h in headers:
            store_name = ""
            platform = ""

            acc_id = getattr(h, "api_account_id", None)
            api_acc: Optional[ApiAccount] = api_accounts_by_id.get(acc_id) if acc_id is not None else None
            if api_acc is not None:
                store_name = (getattr(api_acc, "comp_name", "") or "").strip()
                platform = (getattr(api_acc, "platform", "") or "").strip()

            orders.append(
                {
                    "header": h,
                    "data": data_by_header.get(h.pk, []) or [],  # LIST (mode latest: 0/1)
                    "items": items_by_header.get(h.pk, []) or [],
                    "store_name": store_name,
                    "platform": platform,
                }
            )

        return Result.ok(
            f"{len(orders)} siparişin detayları getirildi.",
            close_dialog=False,
            data={
                "orders": orders,
                "headers": headers,
                "order_data_list": order_data_list,
                "order_item_list": order_item_list,
            },
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def get_nonfinal_order_numbers(final_statuses: Optional[list[str]] = None) -> Result:
    """
    Her sipariş için en güncel OrderData snapshot'ını bulur.
    Bu kaydın status değeri final_statuses içinde değilse orderNumber döner.
    """
    try:
        if final_statuses is None:
            final_statuses = list(ORDER_FINAL_STATUS_CODES)
        normalized_final_statuses = [
            _normalize_runtime_status_code(status)
            for status in (final_statuses or [])
            if _normalize_runtime_status_code(status)
        ]

        engine = _engine()
        with Session(engine) as session:
            subq = (
                select(
                    OrderData.order_header_id,
                    func.max(OrderData.lastModifiedDate).label("max_last_modified"),
                )
                .group_by(OrderData.order_header_id)
                .subquery()
            )

            stmt = (
                select(OrderHeader.orderNumber)
                .join(subq, subq.c.order_header_id == OrderHeader.pk)
                .join(
                    OrderData,
                    (OrderData.order_header_id == OrderHeader.pk)
                    & (OrderData.lastModifiedDate == subq.c.max_last_modified),
                )
                .where(_exclude_simulated_order_sql(OrderHeader.orderNumber, OrderData.cargoProviderName))
            )
            if normalized_final_statuses:
                stmt = stmt.where(
                    ~func.coalesce(OrderData.shipmentPackageStatus, OrderData.status, "").in_(
                        normalized_final_statuses
                    )
                )

            rows = session.exec(stmt).all() or []

        order_numbers = sorted(
            {
                str(num).strip()
                for num in rows
                if num is not None and str(num).strip()
            }
        )

        return Result.ok(
            f"{len(order_numbers)} adet final olmayan sipariş bulundu.",
            close_dialog=False,
            data={"order_numbers": order_numbers},
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)
