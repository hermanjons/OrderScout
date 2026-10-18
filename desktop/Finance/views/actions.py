
from __future__ import annotations

from collections import defaultdict
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
import re
from typing import Any
import uuid

from sqlalchemy import func
from sqlmodel import Session, select

from Account.models.models import ApiAccount
from Account.processors.pipeline import get_company_by_id
from Account.views.actions import collect_selected_companies
from Finance.processors.pipeline import (
    cost_source_type_label,
    normalize_finance_cost_card_source_metadata,
    normalize_cost_source_type,
)
from Core.utils.model_utils import get_engine
from Feedback.processors.pipeline import Result, map_error_to_message
from Logistics.constants.catalog_constants import (
    builtin_cargo_provider_records,
    cargo_provider_code_for_source_id,
    cargo_provider_records,
    cargo_provider_name_for_code,
    cargo_provider_options,
    cargo_provider_source_id_for_code,
)
from Core.db.models import SOURCE_TYPE_BUILTIN, SOURCE_TYPE_USER, build_source_id, coerce_source_id
from Marketplaces.constants.catalog_constants import (
    builtin_marketplace_records,
    canonical_platform_code,
    marketplace_code_for_source_id,
    marketplace_db_id_for_code,
    marketplace_db_id_for_source_id,
    marketplace_records,
    marketplace_source_id_for_code,
    marketplace_finance_service_definitions,
    marketplace_finance_service_options,
    marketplace_finance_transaction_types,
    marketplace_cargo_form_visible_fields,
    platform_label_for_code,
    platform_select_options,
)
from Finance.constants.domain_constants import (
    FINANCE_BACKFILL_EMPTY_WINDOW_THRESHOLD,
    FINANCE_BACKFILL_MAX_YEARS,
    FINANCE_COST_MATCH_MODE_OPTIONS,
    FINANCE_COST_VALUE_TYPE_OPTIONS,
    FINANCE_CURRENCY_OPTIONS,
    FINANCE_INCREMENTAL_OVERLAP_MINUTES,
    finance_builtin_cost_item_records,
    finance_cargo_tariff_default_records,
    finance_cost_rule_exists,
    finance_cost_rule_label,
    normalize_finance_cost_rule_key,
)
from Finance.constants.trendyol.constants import (
    FINANCE_PLATFORM_TRENDYOL,
    TRENDYOL_FINANCE_DEFAULT_FETCH_DAYS,
    TRENDYOL_FINANCE_DEFAULT_MAX_PAGES,
    TRENDYOL_FINANCE_DEFAULT_PAGE_SIZE,
    TRENDYOL_FINANCE_SAFE_RANGE_DAYS,
    TZ_GMT3,
)
from Finance.constants.paths import (
    FINANCE_CARGO_TARIFFS_DEFAULT_FILE,
    FINANCE_CARGO_TARIFFS_FILE,
    FINANCE_COST_ITEMS_DEFAULT_FILE,
    FINANCE_RUNTIME_STATE_FILE,
)
from Finance.models.trendyol.models import (
    Company,
    FinanceCargoInvoiceItem,
    FinanceCostItem,
    FinanceCostItemMarketplaceLink,
    FinanceInvoiceDocument,
    FinanceManualTransaction,
)
from Logistics.models.models import LogisticsCargoProvider, LogisticsCargoTariff
from Marketplaces.models.models import Marketplace
from Finance.processors.trendyol.pipeline import (
    create_brand,
    create_company,
    delete_brand,
    delete_company,
    get_finance_account_sync_bounds,
    get_finance_cargo_invoice_items_from_db,
    get_finance_cargo_invoice_transactions_from_db,
    get_finance_filter_metadata,
    get_finance_transactions_from_db,
    list_brands,
    list_companies,
    sync_finance_for_accounts,
    update_brand,
    update_company,
)
from settings import DB_NAME

_finance_cargo_tariffs_default_cache_signature: tuple[str, int, int] | None = None
_finance_cargo_tariffs_default_cache_rows: list[dict[str, Any]] | None = None
FINANCE_MANUAL_SERVICE_KEY = "manual"
FINANCE_MANUAL_SERVICE_LABEL = "Manuel Kayıt"
FINANCE_MARKETPLACE_SERVICE_LABEL = "Pazaryeri API"
FINANCE_INVOICE_DOCUMENT_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".xml", ".html", ".htm"}


def finance_service_options(include_all: bool = True) -> list[tuple[str, str]]:
    return marketplace_finance_service_options(FINANCE_PLATFORM_TRENDYOL, include_all=include_all)


def finance_transaction_type_options(
    metadata_types: list[str] | None = None,
    *,
    include_all: bool = True,
) -> list[str]:
    default_types = marketplace_finance_transaction_types(FINANCE_PLATFORM_TRENDYOL)
    options = sorted({str(row or "").strip() for row in (metadata_types or default_types) if str(row or "").strip()})
    if include_all:
        return ["Tümü"] + options
    return options


def finance_default_date_range() -> tuple[date, date]:
    today = datetime.now(TZ_GMT3).date()
    start = today - timedelta(days=max(1, TRENDYOL_FINANCE_DEFAULT_FETCH_DAYS) - 1)
    return start, today

def finance_cost_calculation_options(*, include_all: bool = True) -> list[tuple[str, str]]:
    options = list(FINANCE_COST_VALUE_TYPE_OPTIONS)
    return ([("Tümü", "")] + options) if include_all else options


def finance_cost_match_mode_options(*, include_all: bool = False) -> list[tuple[str, str]]:
    options = list(FINANCE_COST_MATCH_MODE_OPTIONS)
    return ([("Tümü", "")] + options) if include_all else options


def finance_cost_item_platform_options(
    *,
    include_all: bool = False,
    db_name: str | None = None,
) -> list[tuple[str, str]]:
    options = [
        (
            _compact_text(row.get("label")),
            str(coerce_source_id(row.get("sourceId") or row.get("source_id")) or ""),
        )
        for row in marketplace_records(db_name=db_name)
        if _compact_text(row.get("label")) and coerce_source_id(row.get("sourceId") or row.get("source_id")) is not None
    ]
    return ([("Tümü", "")] + options) if include_all else options


def finance_cargo_tariff_platform_options(
    *,
    include_all: bool = True,
    db_name: str | None = None,
) -> list[tuple[str, str]]:
    options = [
        (
            _compact_text(row.get("label")),
            str(coerce_source_id(row.get("sourceId") or row.get("source_id")) or ""),
        )
        for row in marketplace_records(db_name=db_name)
        if _compact_text(row.get("label")) and coerce_source_id(row.get("sourceId") or row.get("source_id")) is not None
    ]
    return ([("Tümü", "")] + options) if include_all else options


def finance_cargo_provider_options(
    platform_code: str | None = None,
    *,
    include_all: bool = True,
    db_name: str | None = None,
) -> list[tuple[str, str]]:
    options = [
        (
            _compact_text(row.get("cargoProviderName")),
            str(coerce_source_id(row.get("sourceId") or row.get("source_id")) or ""),
        )
        for row in cargo_provider_records(platform_code, db_name=db_name)
        if _compact_text(row.get("cargoProviderName")) and coerce_source_id(row.get("sourceId") or row.get("source_id")) is not None
    ]
    return ([("Tümü", "")] + options) if include_all else options


def finance_cargo_tariff_visible_fields(platform_code: object | None = None) -> set[str]:
    normalized_platform = marketplace_code_for_source_id(platform_code) or platform_code
    return set(marketplace_cargo_form_visible_fields(normalized_platform))


def action_create_brand(
    name: str,
    code: str | None = None,
    registration_no: str | None = None,
    country: str | None = None,
    website: str | None = None,
    contact_email: str | None = None,
    contact_phone: str | None = None,
    address: str | None = None,
    note: str | None = None,
    db_name: str = DB_NAME,
) -> Result:
    return create_brand(
        name=name,
        code=code,
        registration_no=registration_no,
        country=country,
        website=website,
        contact_email=contact_email,
        contact_phone=contact_phone,
        address=address,
        note=note,
        db_name=db_name,
    )


def action_update_brand(pk: int, update_data: dict[str, Any], db_name: str = DB_NAME) -> Result:
    return update_brand(pk=pk, update_data=update_data, db_name=db_name)


def action_delete_brand(pk: int, db_name: str = DB_NAME) -> Result:
    return delete_brand(pk=pk, db_name=db_name)


def action_list_brands(only_active: bool = True, db_name: str = DB_NAME) -> Result:
    return list_brands(only_active=only_active, db_name=db_name)


def action_create_company(name: str, db_name: str = DB_NAME, **kwargs: Any) -> Result:
    return create_company(name=name, db_name=db_name, **kwargs)


def action_update_company(pk: int, update_data: dict[str, Any], db_name: str = DB_NAME) -> Result:
    return update_company(pk=pk, update_data=update_data, db_name=db_name)


def action_delete_company(pk: int, db_name: str = DB_NAME) -> Result:
    return delete_company(pk=pk, db_name=db_name)


def action_list_companies(only_active: bool = True, db_name: str = DB_NAME) -> Result:
    return list_companies(only_active=only_active, db_name=db_name)


def _now_epoch_ms() -> int:
    return int(datetime.now(TZ_GMT3).timestamp() * 1000)


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


def _finance_window_ms() -> int:
    return int(timedelta(days=max(1, TRENDYOL_FINANCE_SAFE_RANGE_DAYS)).total_seconds() * 1000)


def _finance_backfill_floor_ms(now_ms: int) -> int:
    return int(now_ms - timedelta(days=FINANCE_BACKFILL_MAX_YEARS * 365).total_seconds() * 1000)


def _load_finance_runtime_state(*, state_path: Path = FINANCE_RUNTIME_STATE_FILE) -> dict[str, Any]:
    try:
        if not state_path.exists():
            return {"accounts": {}}
        raw = state_path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            parsed.setdefault("accounts", {})
            return parsed
    except Exception:
        pass
    return {"accounts": {}}


def _save_finance_runtime_state(data: dict[str, Any], *, state_path: Path = FINANCE_RUNTIME_STATE_FILE) -> None:
    payload = dict(data or {})
    payload.setdefault("accounts", {})
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _finance_account_state_key(account: dict[str, Any]) -> str:
    pk = _compact_text(account.get("pk"))
    seller_id = _compact_text(account.get("seller_id"))
    comp_name = _compact_text(account.get("comp_name"))
    return pk or seller_id or comp_name or "finance-account"


def _prepare_finance_account_state(
    account: dict[str, Any],
    raw_state: dict[str, Any] | None,
    *,
    now_ms: int,
    db_name: str | None = None,
) -> dict[str, Any]:
    state = dict(raw_state or {})
    latest_sync_ms = _parse_epoch_ms(state.get("latest_sync_ms"))
    earliest_sync_ms = _parse_epoch_ms(state.get("earliest_sync_ms"))
    backfill_cursor_ms = _parse_epoch_ms(state.get("backfill_cursor_ms"))

    account_pk = account.get("pk")
    if account_pk not in (None, "") and (latest_sync_ms is None or earliest_sync_ms is None):
        bounds_res = get_finance_account_sync_bounds(api_account_id=int(account_pk), db_name=db_name) if db_name else get_finance_account_sync_bounds(api_account_id=int(account_pk))
        if bounds_res.success:
            bounds = bounds_res.data or {}
            if latest_sync_ms is None:
                latest_sync_ms = _parse_epoch_ms(bounds.get("max_transaction_date"))
            if earliest_sync_ms is None:
                earliest_sync_ms = _parse_epoch_ms(bounds.get("min_transaction_date"))
            if backfill_cursor_ms is None and earliest_sync_ms is not None:
                backfill_cursor_ms = max(0, int(earliest_sync_ms) - 1)

    if latest_sync_ms is not None:
        state["latest_sync_ms"] = int(latest_sync_ms)
    if earliest_sync_ms is not None:
        state["earliest_sync_ms"] = int(earliest_sync_ms)
    if backfill_cursor_ms is None:
        backfill_cursor_ms = int(now_ms)
    state["backfill_cursor_ms"] = int(backfill_cursor_ms)
    state["backfill_complete"] = bool(state.get("backfill_complete", False))
    state["empty_backfill_windows"] = max(0, int(state.get("empty_backfill_windows", 0) or 0))
    state["pk"] = account.get("pk")
    state["seller_id"] = _compact_text(account.get("seller_id"))
    state["comp_name"] = _compact_text(account.get("comp_name"))
    return state


def resolve_finance_sync_plan(
    accounts: list[dict[str, Any]],
    *,
    now_ms: int | None = None,
    state_path: Path = FINANCE_RUNTIME_STATE_FILE,
    db_name: str | None = None,
) -> Result:
    try:
        effective_now_ms = int(_now_epoch_ms() if now_ms is None else now_ms)
        overlap_ms = max(1, FINANCE_INCREMENTAL_OVERLAP_MINUTES) * 60 * 1000
        window_ms = _finance_window_ms()
        floor_ms = _finance_backfill_floor_ms(effective_now_ms)

        runtime_state = _load_finance_runtime_state(state_path=state_path)
        account_states = dict(runtime_state.get("accounts") or {})
        jobs: list[dict[str, Any]] = []
        plan_accounts: list[dict[str, Any]] = []

        for account in list(accounts or []):
            state_key = _finance_account_state_key(account)
            account_state = _prepare_finance_account_state(
                account,
                account_states.get(state_key),
                now_ms=effective_now_ms,
                db_name=db_name,
            )
            account_states[state_key] = account_state

            latest_sync_ms = _parse_epoch_ms(account_state.get("latest_sync_ms"))
            if latest_sync_ms is not None:
                incremental_start_ms = max(0, int(latest_sync_ms) - overlap_ms)
                if incremental_start_ms < effective_now_ms:
                    jobs.append(
                        {
                            "account_key": state_key,
                            "account": account,
                            "mode": "incremental",
                            "start_ms": incremental_start_ms,
                            "end_ms": effective_now_ms,
                        }
                    )

            if not bool(account_state.get("backfill_complete", False)):
                cursor_ms = min(int(account_state.get("backfill_cursor_ms") or effective_now_ms), effective_now_ms)
                probe = cursor_ms
                while probe > floor_ms:
                    start_ms = max(floor_ms, probe - window_ms + 1)
                    jobs.append(
                        {
                            "account_key": state_key,
                            "account": account,
                            "mode": "backfill",
                            "start_ms": int(start_ms),
                            "end_ms": int(probe),
                        }
                    )
                    probe = int(start_ms) - 1

            plan_accounts.append(
                {
                    "account_key": state_key,
                    "pk": account.get("pk"),
                    "seller_id": _compact_text(account.get("seller_id")),
                    "comp_name": _compact_text(account.get("comp_name")),
                    "latest_sync_ms": latest_sync_ms,
                    "backfill_complete": bool(account_state.get("backfill_complete", False)),
                }
            )

        runtime_state["accounts"] = account_states
        return Result.ok(
            "Finance sync planÄ± hazÄ±r.",
            close_dialog=False,
            data={
                "jobs": jobs,
                "state": runtime_state,
                "accounts": plan_accounts,
                "now_ms": effective_now_ms,
                "floor_ms": floor_ms,
            },
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def _mark_finance_job_success(
    runtime_state: dict[str, Any],
    *,
    account_key: str,
    job: dict[str, Any],
    result: Result,
    now_ms: int,
    floor_ms: int,
) -> bool:
    accounts = runtime_state.setdefault("accounts", {})
    account_state = dict(accounts.get(account_key) or {})
    account_state["latest_sync_ms"] = max(int(account_state.get("latest_sync_ms") or 0), int(now_ms))
    account_state["updated_at_ms"] = int(now_ms)

    if job.get("mode") == "backfill":
        counts = (result.data or {}).get("counts", {}) or {}
        has_data = int(counts.get("transactions") or 0) > 0 or int(counts.get("cargo_items") or 0) > 0
        start_ms = int(job.get("start_ms") or 0)
        next_cursor_ms = max(0, start_ms - 1)
        current_earliest = _parse_epoch_ms(account_state.get("earliest_sync_ms"))
        account_state["earliest_sync_ms"] = start_ms if current_earliest is None else min(current_earliest, start_ms)
        account_state["backfill_cursor_ms"] = next_cursor_ms
        empty_streak = max(0, int(account_state.get("empty_backfill_windows", 0) or 0))
        account_state["empty_backfill_windows"] = 0 if has_data else empty_streak + 1
        if next_cursor_ms <= int(floor_ms) or int(account_state["empty_backfill_windows"]) >= FINANCE_BACKFILL_EMPTY_WINDOW_THRESHOLD:
            account_state["backfill_complete"] = True

    accounts[account_key] = account_state
    return bool(account_state.get("backfill_complete", False))


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


def _runtime_record_pk(row: dict[str, Any] | None, *, fallback: int = 0) -> int:
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


def _row_matches_runtime_pk(row: dict[str, Any] | None, runtime_pk: int) -> bool:
    normalized_runtime_pk = int(runtime_pk or 0)
    if normalized_runtime_pk <= 0:
        return False
    return _runtime_record_pk(row) == normalized_runtime_pk


def _safe_int_id(value: Any) -> int | None:
    try:
        parsed = int(value)
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _safe_float(value: Any) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _safe_date(value: Any, *, default_date: date | None = None) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return default_date or datetime.now(TZ_GMT3).date()


def _to_epoch_ms(value: date, *, end_of_day: bool = False) -> int:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.combine(value, time.max if end_of_day else time.min)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_GMT3)
    return int(dt.timestamp() * 1000)


def _format_datetime(value: Any) -> str:
    try:
        if isinstance(value, datetime):
            dt = value
        else:
            raw = int(value or 0)
            if raw <= 0:
                return "-"
            dt = datetime.fromtimestamp(raw / 1000, tz=TZ_GMT3)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ_GMT3)
        return dt.astimezone(TZ_GMT3).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return "-"


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


def compact_number_text(value: object) -> str:
    if value in (None, ""):
        return ""
    text = _format_compact_number(value)
    return text if text != "" else str(value or "").strip()


def _normalize_finance_currency(value: Any, *, fallback: str = "TRY") -> str:
    code = _compact_text(value).upper()
    if code in FINANCE_CURRENCY_OPTIONS:
        return code
    fallback_code = _compact_text(fallback).upper()
    if fallback_code in FINANCE_CURRENCY_OPTIONS:
        return fallback_code
    return "TRY"


def _normalize_finance_direction(value: Any) -> str:
    raw = _compact_text(value).casefold()
    if raw in {"income", "credit", "alacak", "gelir", "in"}:
        return "income"
    if raw in {"expense", "debt", "borç", "borc", "gider", "out"}:
        return "expense"
    return "expense"


def _finance_direction_label(value: Any) -> str:
    return "Gelir / Alacak" if _normalize_finance_direction(value) == "income" else "Gider / Borç"


def _direction_amounts(direction: Any, amount: Any) -> tuple[float, float, float]:
    normalized = _normalize_finance_direction(direction)
    numeric = abs(_safe_float(amount))
    if normalized == "income":
        return 0.0, numeric, numeric
    return numeric, 0.0, -numeric


def _epoch_ms_from_date_like(value: Any, *, default_today: bool = True) -> int:
    parsed = _parse_epoch_ms(value)
    if parsed is not None:
        return int(parsed)
    if default_today:
        return _to_epoch_ms(datetime.now(TZ_GMT3).date())
    return 0


def finance_cost_currency(record: dict[str, Any] | None, default: str = "TRY") -> str:
    payload = dict(record or {})
    return _normalize_finance_currency(payload.get("currency"), fallback=default)


def finance_cost_amount_display(record: dict[str, Any] | None) -> str:
    payload = dict(record or {})
    amount_text = str(payload.get("defaultAmountText") or "-").strip() or "-"
    if _compact_text(payload.get("valueType")).casefold() != "numeric":
        return amount_text
    if amount_text == "-":
        return amount_text
    return f"{amount_text} {finance_cost_currency(payload)}"


def _normalize_supported_platforms(values: Any) -> list[str]:
    raw_values = values
    if isinstance(raw_values, str):
        raw_values = [part for part in raw_values.split(",") if str(part).strip()]
    out: list[str] = []
    for raw in list(raw_values or []):
        code = canonical_platform_code(raw)
        if code and code not in out:
            out.append(code)
    return out


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


def _format_ratio(value: float, total: float) -> str:
    if total <= 0:
        return "%0.00"
    return f"%{(float(value) / float(total)) * 100:.2f}"


def _now_iso_text() -> str:
    return datetime.now(TZ_GMT3).isoformat()


def _slugify_method_key(value: Any) -> str:
    text = re.sub(r"[^a-z0-9_]+", "-", _compact_text(value).casefold())
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or f"profit-method-{uuid.uuid4().hex[:10]}"


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _json_load(value: Any, *, default: Any) -> Any:
    try:
        if isinstance(value, str):
            parsed = json.loads(value)
            if parsed is not None:
                return parsed
    except Exception:
        pass
    return default


def _resolve_finance_cost_items_default_path(
    *,
    default_storage_path: str | Path | None = None,
    storage_path: str | Path | None = None,
) -> Path | None:
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


def _normalize_finance_cost_item_rows(
    records: list[dict[str, Any]] | None,
    *,
    is_builtin: bool = False,
) -> list[dict[str, Any]]:
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


def _normalize_supported_platform_source_ids(values: Any, *, db_name: str | None = None) -> list[int]:
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


def _platform_codes_for_source_ids(source_ids: Any, *, db_name: str | None = None) -> list[str]:
    out: list[str] = []
    for source_id in _normalize_supported_platform_source_ids(source_ids, db_name=db_name):
        code = marketplace_code_for_source_id(source_id, db_name=db_name)
        if code and code not in out:
            out.append(code)
    return out


def _accepted_finance_cost_item_platform_source_ids(*, db_name: str | None = None) -> set[int]:
    return {
        int(source_id)
        for row in marketplace_records(db_name=db_name)
        for source_id in [coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id"))]
        if source_id is not None
    }


def _marketplace_id_map_for_source_ids(
    source_ids: list[int] | set[int] | tuple[int, ...],
    *,
    db_name: str | None = None,
) -> dict[int, int]:
    out: dict[int, int] = {}
    for source_id in list(source_ids or []):
        normalized_source_id = _source_id_or_none(source_id)
        if normalized_source_id is None:
            continue
        marketplace_id = marketplace_db_id_for_source_id(normalized_source_id, db_name=db_name)
        if marketplace_id is not None:
            out[normalized_source_id] = marketplace_id
    return out


def _load_finance_cost_items_user_payload(
    *,
    storage_path: str | Path | None = None,
    db_name: str | None = None,
) -> dict[str, Any]:
    return _load_finance_cost_items_user_payload_db(db_name=db_name)


def _load_finance_cost_items_default_raw(
    *,
    default_storage_path: str | Path | None = None,
    storage_path: str | Path | None = None,
    db_name: str | None = None,
) -> list[dict[str, Any]]:
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


def _save_finance_cost_items_user_payload(
    records: list[dict[str, Any]],
    *,
    deleted_keys: list[str] | set[str] | None = None,
    storage_path: str | Path | None = None,
    db_name: str | None = None,
) -> None:
    _save_finance_cost_items_user_payload_db(records, deleted_keys=deleted_keys, db_name=db_name)


def _finance_cost_item_model_to_row(
    row: FinanceCostItem,
    *,
    supported_platform_source_ids: list[int] | None = None,
    db_name: str | None = None,
) -> dict[str, Any]:
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


def _load_finance_cost_items_user_payload_db(*, db_name: str | None = None) -> dict[str, Any]:
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


def _save_finance_cost_items_user_payload_db(
    records: list[dict[str, Any]],
    *,
    deleted_keys: list[str] | set[str] | None = None,
    db_name: str | None = None,
) -> None:
    builtin_by_key = {
        _compact_text(row.get("costKey")).casefold(): dict(row or {})
        for row in _load_finance_cost_items_default_raw(db_name=db_name)
        if _compact_text(row.get("costKey"))
    }
    cleaned_records: list[dict[str, Any]] = []
    for row in list(records or []):
        if not isinstance(row, dict):
            continue
        cost_key = _compact_text(row.get("costKey"))
        builtin_row = builtin_by_key.get(cost_key.casefold())
        source_type = _compact_text(row.get("sourceType") or row.get("source_type")).lower()
        if builtin_row is not None:
            source_type = SOURCE_TYPE_BUILTIN
        elif source_type not in {SOURCE_TYPE_BUILTIN, SOURCE_TYPE_USER}:
            source_type = SOURCE_TYPE_BUILTIN if bool(row.get("isBuiltin")) else SOURCE_TYPE_USER
        source_id = _source_id_or_none(row.get("sourceId") or row.get("source_id"))
        if builtin_row is not None:
            source_id = (
                _source_id_or_none(builtin_row.get("sourceId") or builtin_row.get("source_id"))
                or source_id
            )
        elif source_id is None:
            source_id = _next_runtime_source_id([*cleaned_records, row])
        value_type = _normalize_cost_value_type(row)
        supported_platform_source_ids = _normalize_supported_platform_source_ids(
            row.get("supportedPlatformSourceIds")
            or row.get("supported_platform_source_ids")
            or row.get("supportedPlatforms"),
            db_name=db_name,
        )
        source_meta = normalize_finance_cost_card_source_metadata(
            {
                **dict(row or {}),
                "costKey": cost_key,
                "defaultMatchMode": _normalize_cost_default_match_mode(row),
            }
        )
        cleaned_records.append(
            {
                "pk": _runtime_record_pk(row) or None,
                "dbPk": _db_pk_or_none(row),
                "costKey": cost_key,
                "name": _compact_text(row.get("name")) or None,
                "description": _compact_text(row.get("description")) or None,
                "valueType": value_type,
                "defaultMatchMode": _normalize_cost_default_match_mode(row),
                "defaultAmount": _optional_float(row.get("defaultAmount")),
                "currency": _normalize_finance_currency(row.get("currency")),
                "isVatIncluded": bool(row.get("isVatIncluded", True)),
                "vatRate": _optional_float(row.get("vatRate")),
                "supportedPlatformsJson": _json_dump(_platform_codes_for_source_ids(supported_platform_source_ids, db_name=db_name)),
                "supportedPlatformSourceIdsJson": _json_dump(supported_platform_source_ids),
                "supportedSourceTypesJson": _json_dump(list(source_meta.get("supportedSourceTypes") or [])),
                "defaultSourceType": _compact_text(source_meta.get("defaultSourceType")),
                "defaultSourceConfigJson": (
                    _json_dump(dict(source_meta.get("defaultSourceConfig") or {}) or {})
                    if dict(source_meta.get("defaultSourceConfig") or {}) or None
                    else None
                ),
                "isActive": bool(row.get("isActive", True)),
                "isDeleted": False,
                "createdAt": _compact_text(row.get("createdAt")) or _now_iso_text(),
                "updatedAt": _compact_text(row.get("updatedAt")) or _now_iso_text(),
                "sourceType": source_type,
                "sourceId": source_id,
                "source_id": source_id,
            }
        )

    active_rows_by_key: dict[str, dict[str, Any]] = {}
    for row in cleaned_records:
        cost_key = _compact_text(row.get("costKey"))
        if not cost_key:
            continue
        active_rows_by_key[cost_key.casefold()] = dict(row)

    deleted_key_set = {
        _compact_text(key)
        for key in list(deleted_keys or [])
        if _compact_text(key)
    }

    engine = get_engine(db_name or DB_NAME)
    with Session(engine) as session:
        existing_rows = session.exec(select(FinanceCostItem).order_by(FinanceCostItem.pk.asc())).all() or []
        existing_by_key = {
            _compact_text(row.costKey).casefold(): row
            for row in existing_rows
            if _compact_text(row.costKey)
        }
        existing_by_pk = {
            int(row.pk or 0): row
            for row in existing_rows
            if int(row.pk or 0) > 0
        }
        existing_by_source_id = {
            coerce_source_id(getattr(row, "sourceId", None)): row
            for row in existing_rows
            if coerce_source_id(getattr(row, "sourceId", None)) is not None
        }

        def _apply_row(model_row: FinanceCostItem, payload: dict[str, Any]) -> None:
            for field_name, field_value in payload.items():
                if field_name in {"dbPk", "source_id"}:
                    continue
                setattr(model_row, field_name, field_value)

        for row in cleaned_records:
            cost_key = _compact_text(row.get("costKey"))
            if not cost_key:
                continue
            row_pk = int(row.get("dbPk") or 0)
            model_row = existing_by_pk.get(row_pk) if row_pk > 0 else None
            row_source_id = _source_id_or_none(row.get("sourceId") or row.get("source_id"))
            if model_row is None and row_source_id is not None:
                model_row = existing_by_source_id.get(row_source_id)
            if model_row is None:
                model_row = existing_by_key.get(cost_key.casefold())
            if model_row is None:
                model_row = FinanceCostItem(
                    **{key: value for key, value in row.items() if key not in {"dbPk", "source_id"}}
                )
                session.add(model_row)
                session.flush()
                existing_by_pk[int(getattr(model_row, "pk", 0) or 0)] = model_row
                if row_source_id is not None:
                    existing_by_source_id[row_source_id] = model_row
                existing_by_key[cost_key.casefold()] = model_row
            else:
                _apply_row(model_row, row)
                session.flush()

            cost_item_id = int(getattr(model_row, "pk", 0) or 0)
            supported_platform_source_ids = _normalize_supported_platform_source_ids(
                _json_load(row.get("supportedPlatformSourceIdsJson"), default=[]),
                db_name=db_name,
            )
            platform_id_map = _marketplace_id_map_for_source_ids(supported_platform_source_ids, db_name=db_name)
            existing_links = session.exec(
                select(FinanceCostItemMarketplaceLink).where(
                    FinanceCostItemMarketplaceLink.cost_item_id == cost_item_id
                )
            ).all() or []
            existing_by_marketplace_id = {
                int(getattr(link_row, "marketplace_id", 0) or 0): link_row
                for link_row in existing_links
                if int(getattr(link_row, "marketplace_id", 0) or 0) > 0
            }
            target_marketplace_ids = set(platform_id_map.values())

            for marketplace_id, link_row in list(existing_by_marketplace_id.items()):
                if marketplace_id in target_marketplace_ids:
                    continue
                session.delete(link_row)

            for platform_source_id, marketplace_id in platform_id_map.items():
                link_row = existing_by_marketplace_id.get(marketplace_id)
                if link_row is None:
                    link_row = FinanceCostItemMarketplaceLink(
                        cost_item_id=cost_item_id,
                        marketplace_id=marketplace_id,
                        createdAt=_now_iso_text(),
                        updatedAt=_now_iso_text(),
                        sourceType=SOURCE_TYPE_USER,
                        sourceId=None,
                    )
                    session.add(link_row)
                link_row.cost_item_id = cost_item_id
                link_row.marketplace_id = marketplace_id
                link_row.updatedAt = _now_iso_text()
                link_row.sourceType = SOURCE_TYPE_BUILTIN if source_type == SOURCE_TYPE_BUILTIN else SOURCE_TYPE_USER
                link_row.sourceId = build_source_id(
                    "cost_item_marketplace_link",
                    {
                        "cost_item_id": cost_item_id,
                        "marketplace_id": marketplace_id,
                    },
                    source_type=link_row.sourceType,
                )
                if not _compact_text(getattr(link_row, "createdAt", "")):
                    link_row.createdAt = _now_iso_text()
            session.flush()

        tombstone_time = _now_iso_text()
        tombstone_targets = {key.casefold(): key for key in deleted_key_set}

        for cost_key_cf, original_key in sorted(tombstone_targets.items()):
            model_row = existing_by_key.get(cost_key_cf)
            if model_row is None:
                tombstone_source_type = SOURCE_TYPE_USER
                session.add(
                    FinanceCostItem(
                        costKey=original_key,
                        name=None,
                        description=None,
                        valueType=None,
                        defaultMatchMode=None,
                        defaultAmount=None,
                        currency="TRY",
                        isVatIncluded=True,
                        vatRate=None,
                        supportedPlatformsJson="[]",
                        supportedSourceTypesJson="[]",
                        defaultSourceType=None,
                        defaultSourceConfigJson=None,
                        isActive=False,
                        isDeleted=True,
                        createdAt=tombstone_time,
                        updatedAt=tombstone_time,
                        sourceType=tombstone_source_type,
                        sourceId=_next_runtime_source_id(cleaned_records),
                    )
                )
                continue
            model_row.isActive = False
            model_row.isDeleted = True
            model_row.updatedAt = tombstone_time
            for link_row in session.exec(
                select(FinanceCostItemMarketplaceLink).where(
                    FinanceCostItemMarketplaceLink.cost_item_id == int(getattr(model_row, "pk", 0) or 0)
                )
            ).all() or []:
                session.delete(link_row)
            if not _compact_text(model_row.createdAt):
                model_row.createdAt = tombstone_time

        session.commit()


def _load_finance_cost_items_raw(
    *,
    storage_path: str | Path | None = None,
    db_name: str | None = None,
    default_storage_path: str | Path | None = None,
) -> list[dict[str, Any]]:
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


def _next_finance_cost_item_pk(records: list[dict[str, Any]]) -> int:
    max_pk = 0
    for row in list(records or []):
        try:
            max_pk = max(max_pk, int((row or {}).get("pk") or 0))
        except Exception:
            continue
    return max_pk + 1


def _next_runtime_source_id(records: list[dict[str, Any]]) -> int:
    max_source_id = 0
    for row in list(records or []):
        source_id = _source_id_or_none((row or {}).get("sourceId") or (row or {}).get("source_id"))
        if source_id is None:
            continue
        max_source_id = max(max_source_id, int(source_id))
    return max_source_id + 1


def _ensure_unique_finance_cost_key(
    records: list[dict[str, Any]],
    desired_key: Any,
    *,
    current_pk: int | None = None,
) -> str:
    base = _slugify_method_key(desired_key).replace("_", "-")
    existing = {
        _compact_text(row.get("costKey")).casefold()
        for row in list(records or [])
        if int((row or {}).get("pk") or 0) != int(current_pk or 0)
    }
    if base.casefold() not in existing:
        return base
    suffix = 2
    while True:
        candidate = f"{base}-{suffix}"
        if candidate.casefold() not in existing:
            return candidate
        suffix += 1


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


def accept_finance_cost_item(
    item_pk: int,
    *,
    storage_path: str | Path | None = None,
    db_name: str | None = None,
    default_storage_path: str | Path | None = None,
) -> Result:
    try:
        normalized_pk = int(item_pk or 0)
        if normalized_pk <= 0:
            return Result.fail("Kabul edilecek maliyet kartı bulunamadı.", close_dialog=False)

        merged_records = _load_finance_cost_items_raw(
            storage_path=storage_path,
            db_name=db_name,
            default_storage_path=default_storage_path,
        )
        target = next((dict(row or {}) for row in merged_records if _row_matches_runtime_pk(row, normalized_pk)), None)
        if target is None:
            return Result.fail("Kabul edilecek maliyet kartı bulunamadı.", close_dialog=False)
        if not bool(target.get("isBuiltin")):
            return Result.fail("Bu kayıt önerilen bir maliyet kartı değil.", close_dialog=False)
        if bool(target.get("isBuiltinAccepted")):
            return Result.ok("Maliyet kartı zaten kullanıma alınmış.", close_dialog=False)

        save_payload = {
            "name": _compact_text(target.get("name")),
            "costKey": _compact_text(target.get("costKey")),
            "description": _compact_text(target.get("description")) or None,
            "valueType": _normalize_cost_value_type(target),
            "defaultMatchMode": _normalize_cost_default_match_mode(target),
            "defaultAmount": target.get("defaultAmount"),
            "currency": _normalize_finance_currency(target.get("currency")),
            "isVatIncluded": bool(target.get("isVatIncluded", True)),
            "vatRate": _optional_float(target.get("vatRate")),
            "supportedPlatformSourceIds": _normalize_supported_platform_source_ids(
                target.get("supportedPlatformSourceIds") or target.get("supportedPlatforms"),
                db_name=db_name,
            ),
            "supportedSourceTypes": list(target.get("supportedSourceTypes") or []),
            "defaultSourceType": _compact_text(target.get("defaultSourceType")),
            "defaultSourceConfig": dict(target.get("defaultSourceConfig") or {}) or None,
            "isActive": bool(target.get("isActive", True)),
            "isBuiltin": True,
            "sourceType": SOURCE_TYPE_BUILTIN,
            "sourceId": _source_id_or_none(target.get("sourceId") or target.get("source_id")),
        }
        result = save_finance_cost_item(
            save_payload,
            storage_path=storage_path,
            db_name=db_name,
            default_storage_path=default_storage_path,
        )
        if result.success:
            result.message = "Önerilen maliyet kartı kullanıma alındı."
        return result
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)
def _service_label(service_key: str) -> str:
    services = marketplace_finance_service_definitions(FINANCE_PLATFORM_TRENDYOL)
    payload = dict(services.get(service_key) or {})
    if payload:
        return str(payload.get("label") or service_key)
    return service_key or "-"


def _collect_selected_account_payload(company_list_widget) -> Result:
    try:
        selected = collect_selected_companies(company_list_widget)
        if not selected.success:
            return selected

        selected_company_pks = (selected.data or {}).get("selected_company_pks", []) or []
        return _collect_account_payload_for_company_pks(selected_company_pks)
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def _collect_account_payload_for_company_pks(selected_company_pks: list[int]) -> Result:
    try:
        normalized_pks = sorted({int(pk) for pk in (selected_company_pks or []) if str(pk).strip()})
        if not normalized_pks:
            return Result.fail("Hiçbir şirket seçilmedi.", close_dialog=False)

        creds = get_company_by_id(normalized_pks)
        if not creds.success:
            return creds

        records = (creds.data or {}).get("records", []) or []
        accounts = (creds.data or {}).get("accounts", []) or []

        company_map: dict[int, str] = {}
        account_record_map: dict[int, Any] = {}
        for rec in records:
            pk = getattr(rec, "pk", None)
            if pk is not None:
                company_map[int(pk)] = str(getattr(rec, "comp_name", "") or "")
                account_record_map[int(pk)] = rec

        payload: list[dict[str, Any]] = []
        for row in accounts:
            if not isinstance(row, (list, tuple)) or len(row) < 4:
                continue
            pk = row[0]
            account_record = account_record_map.get(int(pk))
            extra_config = (
                dict(getattr(account_record, "extra_config", None) or {})
                if account_record is not None
                else dict(row[5] or {})
                if len(row) > 5 and isinstance(row[5], dict)
                else {}
            )
            payload.append(
                {
                    "pk": pk,
                    "api_key": row[1],
                    "api_secret": row[2],
                    "seller_id": row[3],
                    "comp_name": company_map.get(int(pk), ""),
                    "extra_config": extra_config,
                }
            )

        if not payload:
            return Result.fail("Seçili şirketler için API bilgisi bulunamadı.", close_dialog=False)
        return Result.ok("Åirket API bilgileri hazÄ±r.", close_dialog=False, data={"accounts": payload})
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)

def _build_finance_insights(
    *,
    transactions: list[dict[str, Any]],
    cargo_items: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    total_credit = sum(_safe_float(row.get("credit")) for row in transactions)
    total_debt = sum(_safe_float(row.get("debt")) for row in transactions)
    net_amount = sum(_safe_float(row.get("netAmount")) for row in transactions)
    payment_order_total = sum(
        _safe_float(row.get("credit") or row.get("netAmount"))
        for row in transactions
        if _compact_text(row.get("transactionType")) == "PaymentOrder"
    )
    cargo_cost_total = sum(
        abs(_safe_float(row.get("netAmount")))
        for row in transactions
        if "kargo fatura" in f"{_compact_text(row.get('transactionType'))} {_compact_text(row.get('description'))}".casefold()
    )

    type_acc: dict[str, dict[str, float]] = defaultdict(lambda: {"count": 0.0, "net": 0.0, "abs": 0.0})
    company_acc: dict[str, dict[str, float]] = defaultdict(lambda: {"count": 0.0, "net": 0.0})
    daily_acc: dict[str, dict[str, float]] = defaultdict(lambda: {"count": 0.0, "net": 0.0})

    for row in transactions:
        tx_type = _compact_text(row.get("transactionType")) or "Diger"
        company = _compact_text(row.get("companyName")) or "-"
        net = _safe_float(row.get("netAmount"))
        day_key = _format_datetime(row.get("transactionDate"))
        if " " in day_key:
            day_key = day_key.split(" ", 1)[0]
        type_acc[tx_type]["count"] += 1
        type_acc[tx_type]["net"] += net
        type_acc[tx_type]["abs"] += abs(net)
        company_acc[company]["count"] += 1
        company_acc[company]["net"] += net
        daily_acc[day_key]["count"] += 1
        daily_acc[day_key]["net"] += net

    type_rows = sorted(type_acc.items(), key=lambda item: (item[1]["abs"], item[1]["count"]), reverse=True)
    company_rows = sorted(company_acc.items(), key=lambda item: (abs(item[1]["net"]), item[1]["count"]), reverse=True)
    daily_rows = sorted(daily_acc.items(), key=lambda item: item[0])
    total_abs = sum(item[1]["abs"] for item in type_rows)

    suggestions: list[str] = []
    if cargo_cost_total > 0 and total_debt > 0:
        suggestions.append(f"Toplam borcun {_format_ratio(cargo_cost_total, total_debt)} kismi kargo faturasi kaynakli.")
    if payment_order_total > 0:
        suggestions.append(f"Odeme emirleri toplami {_format_money(payment_order_total)} seviyesinde.")
    if total_debt > total_credit and total_credit > 0:
        suggestions.append(f"Borç akisi alacak akisini asti ({_format_money(total_debt)} > {_format_money(total_credit)}).")
    if company_rows:
        top_company = company_rows[0]
        suggestions.append(f"En yuksek net etki {_compact_text(top_company[0])} tarafinda goruluyor.")
    if errors:
        suggestions.append(f"{len(errors)} adet finance sorgu hatasi kaydedildi. Yetki ve transaction type kapsamlarini kontrol et.")
    if not suggestions:
        suggestions.append("Net akis dengeli. Kesinti ve odeme emirlerini haftalik takip etmek yeterli gorunuyor.")

    kpis = [
        {"label": "Kayit", "value": str(len(transactions)), "tone": "neutral"},
        {"label": "Net Akis", "value": _format_money(net_amount), "tone": "ok" if net_amount >= 0 else "bad"},
        {"label": "Toplam Alacak", "value": _format_money(total_credit), "tone": "ok"},
        {"label": "Toplam Borc", "value": _format_money(total_debt), "tone": "bad" if total_debt > 0 else "neutral"},
        {"label": "Odeme Emri", "value": _format_money(payment_order_total), "tone": "neutral"},
        {"label": "Kargo Kesintisi", "value": _format_money(cargo_cost_total), "tone": "bad" if cargo_cost_total > 0 else "neutral"},
    ]

    return {
        "kpis": kpis,
        "type_breakdown": [
            {"name": key, "count": int(val["count"]), "net": float(val["net"]), "share": (float(val["abs"]) / total_abs) if total_abs > 0 else 0.0}
            for key, val in type_rows[:12]
        ],
        "company_breakdown": [
            {"name": key, "count": int(val["count"]), "net": float(val["net"])}
            for key, val in company_rows[:12]
        ],
        "daily_breakdown": [
            {"date": key, "count": int(val["count"]), "net": float(val["net"])}
            for key, val in daily_rows[-14:]
        ],
        "cargo_kpis": {
            "cargo_item_count": len(cargo_items),
            "cargo_total": sum(_safe_float(row.get("amount")) for row in cargo_items),
        },
        "suggestions": suggestions,
    }


def _build_transaction_table_rows(records: list[dict[str, Any]]) -> tuple[list[str], list[list[str]]]:
    headers = [
        "Tarih",
        "Sirket",
        "Servis",
        "Islem Turu",
        "Aciklama",
        "Siparis No",
        "Paket",
        "Borc",
        "Alacak",
        "Net",
        "Para Birimi",
        "Referans",
    ]
    rows: list[list[str]] = []
    for row in records:
        reference = (
            _compact_text(row.get("paymentOrderId"))
            or _compact_text(row.get("commissionInvoiceSerialNumber"))
            or _compact_text(row.get("recordId"))
            or "-"
        )
        rows.append(
            [
                _format_datetime(row.get("transactionDate")),
                _compact_text(row.get("companyName")) or "-",
                _service_label(_compact_text(row.get("serviceKey"))),
                _compact_text(row.get("transactionType")) or "-",
                _compact_text(row.get("description")) or "-",
                _compact_text(row.get("orderNumber")) or "-",
                _compact_text(row.get("shipmentPackageId")) or "-",
                _format_money(row.get("debt")),
                _format_money(row.get("credit")),
                _format_money(row.get("netAmount")),
                _compact_text(row.get("currency")) or "-",
                reference,
            ]
        )
    return headers, rows


def _build_cargo_table_rows(records: list[dict[str, Any]]) -> tuple[list[str], list[list[str]]]:
    headers = ["Sirket", "Fatura Seri", "Siparis No", "Parcel", "Paket Tipi", "Desi", "Tutar"]
    rows: list[list[str]] = []
    for row in records:
        rows.append(
            [
                _compact_text(row.get("companyName")) or "-",
                _compact_text(row.get("invoiceSerialNumber")) or "-",
                _compact_text(row.get("orderNumber")) or "-",
                _compact_text(row.get("parcelUniqueId")) or "-",
                _compact_text(row.get("shipmentPackageType")) or "-",
                _format_money(row.get("desi")),
                _format_money(row.get("amount")),
            ]
        )
    return headers, rows


def _finance_invoice_key(company_name: str, invoice_serial_number: str) -> str:
    return f"{_compact_text(company_name)}::{_compact_text(invoice_serial_number)}"


def _invoice_sort_tuple(record: dict[str, Any]) -> tuple[int, str]:
    return (
        -int(_parse_epoch_ms(record.get("transactionDate")) or 0),
        _compact_text(record.get("invoiceSerialNumber")).casefold(),
    )


def _invoice_matches_search(record: dict[str, Any], search_text: str) -> bool:
    query = _compact_text(search_text).casefold()
    if not query:
        return True

    line_items = list(record.get("lineItems") or [])
    haystack_parts = [
        _compact_text(record.get("invoiceSerialNumber")),
        _compact_text(record.get("companyName")),
        _compact_text(record.get("sellerAccountId")),
        _compact_text(record.get("transactionDateText")),
        _compact_text(record.get("packageTypesText")),
        _compact_text(record.get("orderNumbersText")),
        _compact_text(record.get("parcelNumbersText")),
    ]
    for item in line_items:
        haystack_parts.extend(
            [
                _compact_text(item.get("orderNumber")),
                _compact_text(item.get("parcelUniqueId")),
                _compact_text(item.get("shipmentPackageType")),
            ]
        )
    haystack = " ".join(haystack_parts).casefold()
    return query in haystack


def _build_finance_cargo_invoice_groups(
    *,
    transactions: list[dict[str, Any]],
    cargo_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}

    for row in transactions:
        serial = _compact_text(row.get("commissionInvoiceSerialNumber"))
        if not serial:
            continue
        company_name = _compact_text(row.get("companyName")) or "-"
        key = _finance_invoice_key(company_name, serial)
        entry = grouped.setdefault(
            key,
            {
                "recordKey": key,
                "companyName": company_name,
                "sellerAccountId": _compact_text(row.get("sellerAccountId")) or "-",
                "invoiceSerialNumber": serial,
                "transactionDate": 0,
                "transactionDateText": "-",
                "lineItems": [],
                "orderNumbers": set(),
                "parcelNumbers": set(),
                "packageTypes": set(),
                "references": set(),
                "totalAmountValue": 0.0,
                "totalDesiValue": 0.0,
            },
        )
        tx_date = int(_parse_epoch_ms(row.get("transactionDate")) or 0)
        if tx_date >= int(entry.get("transactionDate") or 0):
            entry["transactionDate"] = tx_date
            entry["transactionDateText"] = _format_datetime(tx_date)
        reference = (
            _compact_text(row.get("paymentOrderId"))
            or _compact_text(row.get("recordId"))
            or _compact_text(row.get("shipmentPackageId"))
        )
        if reference:
            entry["references"].add(reference)

    for row in cargo_items:
        serial = _compact_text(row.get("invoiceSerialNumber"))
        if not serial:
            continue
        company_name = _compact_text(row.get("companyName")) or "-"
        key = _finance_invoice_key(company_name, serial)
        entry = grouped.setdefault(
            key,
            {
                "recordKey": key,
                "companyName": company_name,
                "sellerAccountId": _compact_text(row.get("sellerAccountId")) or "-",
                "invoiceSerialNumber": serial,
                "transactionDate": 0,
                "transactionDateText": "-",
                "lineItems": [],
                "orderNumbers": set(),
                "parcelNumbers": set(),
                "packageTypes": set(),
                "references": set(),
                "totalAmountValue": 0.0,
                "totalDesiValue": 0.0,
            },
        )
        order_number = _compact_text(row.get("orderNumber")) or "-"
        parcel_value = _compact_text(row.get("parcelUniqueId")) or "-"
        package_type = _compact_text(row.get("shipmentPackageType")) or "-"
        amount_value = _safe_float(row.get("amount"))
        desi_value = _safe_float(row.get("desi"))
        entry["lineItems"].append(
            {
                "orderNumber": order_number,
                "parcelUniqueId": parcel_value,
                "shipmentPackageType": package_type,
                "desi": desi_value,
                "desiText": _format_money(desi_value),
                "amount": amount_value,
                "amountText": _format_money(amount_value),
            }
        )
        if order_number and order_number != "-":
            entry["orderNumbers"].add(order_number)
        if parcel_value and parcel_value != "-":
            entry["parcelNumbers"].add(parcel_value)
        if package_type and package_type != "-":
            entry["packageTypes"].add(package_type)
        entry["totalAmountValue"] += amount_value
        entry["totalDesiValue"] += desi_value

    groups: list[dict[str, Any]] = []
    for entry in grouped.values():
        line_items = list(entry.get("lineItems") or [])
        line_items.sort(
            key=lambda item: (
                _compact_text(item.get("orderNumber")).casefold(),
                _compact_text(item.get("parcelUniqueId")).casefold(),
            )
        )
        order_numbers = sorted(set(entry.get("orderNumbers") or []))
        parcel_numbers = sorted(set(entry.get("parcelNumbers") or []))
        package_types = sorted(set(entry.get("packageTypes") or []))
        references = sorted(set(entry.get("references") or []))
        groups.append(
            {
                **entry,
                "lineItems": line_items,
                "itemCount": len(line_items),
                "orderCount": len(order_numbers),
                "parcelCount": len(parcel_numbers),
                "packageTypeCount": len(package_types),
                "orderNumbers": order_numbers,
                "parcelNumbers": parcel_numbers,
                "packageTypes": package_types,
                "references": references,
                "orderNumbersText": ", ".join(order_numbers[:4]) + (" ..." if len(order_numbers) > 4 else "") if order_numbers else "-",
                "parcelNumbersText": ", ".join(parcel_numbers[:4]) + (" ..." if len(parcel_numbers) > 4 else "") if parcel_numbers else "-",
                "packageTypesText": ", ".join(package_types) if package_types else "-",
                "referenceText": ", ".join(references[:3]) + (" ..." if len(references) > 3 else "") if references else "-",
                "totalAmountText": _format_money(entry.get("totalAmountValue")),
                "totalDesiText": _format_money(entry.get("totalDesiValue")),
            }
        )
    groups.sort(key=_invoice_sort_tuple)
    return groups


def _manual_transaction_to_dict(row: FinanceManualTransaction) -> dict[str, Any]:
    debt, credit, net_amount = _direction_amounts(getattr(row, "direction", ""), getattr(row, "amount", 0.0))
    company_name = _compact_text(getattr(getattr(row, "company", None), "name", ""))
    counterparty = _compact_text(getattr(row, "counterparty", ""))
    return {
        "pk": getattr(row, "pk", None),
        "api_account_id": None,
        "companyName": company_name or counterparty,
        "sellerAccountId": "",
        "serviceKey": FINANCE_MANUAL_SERVICE_KEY,
        "serviceLabel": FINANCE_MANUAL_SERVICE_LABEL,
        "sourceKind": "manual",
        "sourceLabel": FINANCE_MANUAL_SERVICE_LABEL,
        "marketplaceCode": "",
        "sellerId": None,
        "recordId": f"manual-{getattr(row, 'pk', '') or getattr(row, 'sourceId', '')}",
        "transactionType": _compact_text(getattr(row, "categoryName", "")) or _compact_text(getattr(row, "categoryKey", "")) or "Manuel",
        "description": _compact_text(getattr(row, "description", "")),
        "transactionDate": getattr(row, "transactionDate", None),
        "orderDate": None,
        "paymentDate": None,
        "orderNumber": "",
        "shipmentPackageId": None,
        "barcode": "",
        "receiptId": None,
        "paymentOrderId": "",
        "paymentPeriod": None,
        "currency": _compact_text(getattr(row, "currency", "")) or "TRY",
        "country": "",
        "affiliate": "",
        "debt": debt,
        "credit": credit,
        "netAmount": net_amount,
        "sellerRevenue": None,
        "commissionRate": None,
        "commissionAmount": None,
        "commissionInvoiceSerialNumber": "",
        "storeId": None,
        "storeName": "",
        "storeAddress": "",
        "direction": _normalize_finance_direction(getattr(row, "direction", "")),
        "directionText": _finance_direction_label(getattr(row, "direction", "")),
        "categoryKey": _compact_text(getattr(row, "categoryKey", "")),
        "categoryName": _compact_text(getattr(row, "categoryName", "")),
        "amount": getattr(row, "amount", None),
        "referenceNo": _compact_text(getattr(row, "referenceNo", "")),
        "counterparty": counterparty,
        "paymentMethod": _compact_text(getattr(row, "paymentMethod", "")),
        "attachmentsJson": _compact_text(getattr(row, "attachmentsJson", "")),
        "note": _compact_text(getattr(row, "note", "")),
    }


def _marketplace_transaction_to_unified(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row or {})
    payload.setdefault("sourceKind", "marketplace_api")
    payload.setdefault("sourceLabel", f"{platform_label_for_code(FINANCE_PLATFORM_TRENDYOL) or FINANCE_PLATFORM_TRENDYOL} API")
    payload.setdefault("marketplaceCode", FINANCE_PLATFORM_TRENDYOL)
    payload.setdefault("direction", "income" if _safe_float(payload.get("netAmount")) >= 0 else "expense")
    payload.setdefault("directionText", _finance_direction_label(payload.get("direction")))
    return payload


def _cargo_summary_by_invoice_serial(
    *,
    records: list[dict[str, Any]],
    company_name: str | None = None,
    db_name: str | None = None,
) -> dict[str, dict[str, Any]]:
    invoice_serials = sorted(
        {
            _compact_text(row.get("commissionInvoiceSerialNumber"))
            for row in records
            if _compact_text(row.get("commissionInvoiceSerialNumber"))
        }
    )
    if not invoice_serials:
        return {}

    clean_company = _compact_text(company_name).casefold()
    summary: dict[str, dict[str, Any]] = {}
    orders_by_serial: dict[str, set[str]] = defaultdict(set)
    engine = get_engine(db_name or DB_NAME)
    chunk_size = 800

    with Session(engine) as session:
        for offset in range(0, len(invoice_serials), chunk_size):
            serial_chunk = invoice_serials[offset : offset + chunk_size]
            aggregate_stmt = (
                select(
                    FinanceCargoInvoiceItem.invoiceSerialNumber,
                    func.count(FinanceCargoInvoiceItem.pk),
                    func.count(func.distinct(FinanceCargoInvoiceItem.orderNumber)),
                    func.coalesce(func.sum(FinanceCargoInvoiceItem.amount), 0.0),
                    func.coalesce(func.sum(FinanceCargoInvoiceItem.desi), 0.0),
                )
                .where(FinanceCargoInvoiceItem.invoiceSerialNumber.in_(serial_chunk))
                .group_by(FinanceCargoInvoiceItem.invoiceSerialNumber)
            )
            orders_stmt = (
                select(
                    FinanceCargoInvoiceItem.invoiceSerialNumber,
                    FinanceCargoInvoiceItem.orderNumber,
                )
                .where(FinanceCargoInvoiceItem.invoiceSerialNumber.in_(serial_chunk))
                .where(FinanceCargoInvoiceItem.orderNumber.is_not(None))
                .where(FinanceCargoInvoiceItem.orderNumber != "")
                .distinct()
                .order_by(FinanceCargoInvoiceItem.invoiceSerialNumber.asc(), FinanceCargoInvoiceItem.orderNumber.asc())
            )
            if clean_company:
                aggregate_stmt = (
                    aggregate_stmt
                    .join(ApiAccount, FinanceCargoInvoiceItem.api_account_id == ApiAccount.pk)
                    .where(func.lower(ApiAccount.comp_name) == clean_company)
                )
                orders_stmt = (
                    orders_stmt
                    .join(ApiAccount, FinanceCargoInvoiceItem.api_account_id == ApiAccount.pk)
                    .where(func.lower(ApiAccount.comp_name) == clean_company)
                )

            for serial, item_count, order_count, amount, desi in session.exec(aggregate_stmt).all() or []:
                serial_text = _compact_text(serial)
                if not serial_text:
                    continue
                summary[serial_text] = {
                    "count": int(item_count or 0),
                    "order_count": int(order_count or 0),
                    "amount": _safe_float(amount),
                    "desi": _safe_float(desi),
                }

            for serial, order_no in session.exec(orders_stmt).all() or []:
                serial_text = _compact_text(serial)
                order_text = _compact_text(order_no)
                if serial_text and order_text:
                    orders_by_serial[serial_text].add(order_text)

    out: dict[str, dict[str, Any]] = {}
    for serial, entry in summary.items():
        orders = sorted(orders_by_serial.get(serial, set()))
        order_count = int(entry.get("order_count") or len(orders))
        out[serial] = {
            "relatedCargoItemCount": int(entry.get("count") or 0),
            "relatedCargoOrderCount": order_count,
            "relatedCargoTotalAmount": _safe_float(entry.get("amount")),
            "relatedCargoTotalAmountText": _format_money(entry.get("amount")),
            "relatedCargoTotalDesi": _safe_float(entry.get("desi")),
            "relatedCargoTotalDesiText": _format_money(entry.get("desi")),
            "relatedCargoOrdersText": ", ".join(orders[:4]) + (" ..." if len(orders) > 4 else "") if orders else "-",
        }
    return out


def _finance_record_matches_search(record: dict[str, Any], search_text: str) -> bool:
    query = _compact_text(search_text).casefold()
    if not query:
        return True
    haystack = " ".join(
        _compact_text(record.get(key))
        for key in (
            "companyName",
            "counterparty",
            "sellerAccountId",
            "sourceLabel",
            "transactionType",
            "categoryName",
            "description",
            "referenceNo",
            "orderNumber",
            "shipmentPackageId",
            "barcode",
            "paymentOrderId",
            "commissionInvoiceSerialNumber",
            "invoiceSerialNumber",
            "shipmentPackageType",
            "storeName",
            "storeAddress",
            "note",
        )
    ).casefold()
    return query in haystack


def get_manual_finance_transactions_from_db(
    *,
    transaction_type: str | None = None,
    company_name: str | None = None,
    start_ms: int | None = None,
    end_ms: int | None = None,
    search_text: str | None = None,
    limit: int | None = None,
    db_name: str = DB_NAME,
) -> Result:
    try:
        clean_type = _compact_text(transaction_type).casefold()
        clean_company = _compact_text(company_name).casefold()
        clean_search = _compact_text(search_text)
        safe_limit = int(limit) if limit is not None and int(limit) > 0 else None
        engine = get_engine(db_name)
        with Session(engine) as session:
            stmt = (
                select(FinanceManualTransaction)
                .where(FinanceManualTransaction.isDeleted == False)  # noqa: E712
                .order_by(FinanceManualTransaction.transactionDate.desc(), FinanceManualTransaction.pk.desc())
            )
            if start_ms not in (None, ""):
                stmt = stmt.where(FinanceManualTransaction.transactionDate >= int(start_ms))
            if end_ms not in (None, ""):
                stmt = stmt.where(FinanceManualTransaction.transactionDate <= int(end_ms))
            if safe_limit is not None and not clean_type and not clean_company and not clean_search:
                stmt = stmt.limit(safe_limit)
            rows = session.exec(stmt).all() or []
            records = [_manual_transaction_to_dict(row) for row in rows]

        if clean_type:
            records = [
                row for row in records
                if clean_type in {
                    _compact_text(row.get("transactionType")).casefold(),
                    _compact_text(row.get("categoryKey")).casefold(),
                    _compact_text(row.get("categoryName")).casefold(),
                }
            ]
        if clean_company:
            records = [
                row for row in records
                if clean_company in {
                    _compact_text(row.get("companyName")).casefold(),
                    _compact_text(row.get("counterparty")).casefold(),
                }
            ]
        if clean_search:
            records = [row for row in records if _finance_record_matches_search(row, clean_search)]
        if safe_limit is not None:
            records = records[:safe_limit]
        return Result.ok(
            f"Manuel finans hareketleri çekildi (toplam: {len(records)})",
            close_dialog=False,
            data={"records": records},
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def save_manual_finance_transaction(payload: dict[str, Any], *, db_name: str | None = None) -> Result:
    try:
        data = dict(payload or {})
        amount = _optional_float(data.get("amount"))
        if amount is None or amount <= 0:
            return Result.fail("Tutar sıfırdan büyük olmalı.", close_dialog=False)
        transaction_date = _epoch_ms_from_date_like(data.get("transactionDate") or data.get("date"))
        currency = _normalize_finance_currency(data.get("currency"))
        direction = _normalize_finance_direction(data.get("direction"))
        category_name = _compact_text(data.get("categoryName") or data.get("category")) or (
            "Gelir" if direction == "income" else "Gider"
        )
        category_key = _compact_text(data.get("categoryKey")) or re.sub(r"[^a-z0-9]+", "-", category_name.casefold()).strip("-")
        company_id = _safe_int_id(data.get("company_id") or data.get("companyId"))
        attachments = data.get("attachments")
        if isinstance(attachments, list):
            attachments_json = json.dumps([str(item) for item in attachments if str(item or "").strip()], ensure_ascii=False)
        else:
            attachments_json = _compact_text(data.get("attachmentsJson") or attachments) or None

        row = FinanceManualTransaction(
            transactionDate=transaction_date,
            direction=direction,
            categoryKey=category_key or None,
            categoryName=category_name,
            description=_compact_text(data.get("description")) or None,
            referenceNo=_compact_text(data.get("referenceNo") or data.get("reference")) or None,
            amount=float(amount),
            currency=currency,
            isVatIncluded=bool(data.get("isVatIncluded", True)),
            vatRate=_optional_float(data.get("vatRate")),
            company_id=company_id,
            counterparty=_compact_text(data.get("counterparty")) or None,
            paymentMethod=_compact_text(data.get("paymentMethod")) or None,
            attachmentsJson=attachments_json,
            note=_compact_text(data.get("note")) or None,
            isDeleted=False,
        )
        engine = get_engine(db_name or DB_NAME)
        with Session(engine) as session:
            session.add(row)
            session.commit()
            session.refresh(row)
            record = _manual_transaction_to_dict(row)
        return Result.ok("Manuel finans hareketi kaydedildi.", close_dialog=False, data={"record": record})
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def delete_manual_finance_transaction(tx_pk: int, *, db_name: str | None = None) -> Result:
    try:
        normalized_pk = int(tx_pk or 0)
        if normalized_pk <= 0:
            return Result.fail("Silinecek manuel hareket bulunamadı.", close_dialog=False)
        engine = get_engine(db_name or DB_NAME)
        with Session(engine) as session:
            row = session.get(FinanceManualTransaction, normalized_pk)
            if row is None:
                return Result.fail("Silinecek manuel hareket bulunamadı.", close_dialog=False)
            row.isDeleted = True
            session.add(row)
            session.commit()
        return Result.ok("Manuel finans hareketi silindi.", close_dialog=False)
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def _invoice_document_to_dict(row: FinanceInvoiceDocument) -> dict[str, Any]:
    company_name = _compact_text(getattr(getattr(row, "company", None), "name", ""))
    api_company = _compact_text(getattr(getattr(row, "api_account", None), "comp_name", ""))
    counterparty = _compact_text(getattr(row, "counterparty", ""))
    file_path = _compact_text(getattr(row, "filePath", ""))
    invoice_type = _compact_text(getattr(row, "invoiceType", "")) or "other"
    invoice_date = int(_parse_epoch_ms(getattr(row, "invoiceDate", None)) or 0)
    return {
        "pk": getattr(row, "pk", None),
        "recordKey": _compact_text(getattr(row, "pk", "")) or f"{getattr(row, 'invoiceNumber', '')}:{file_path}",
        "invoiceNumber": _compact_text(getattr(row, "invoiceNumber", "")),
        "invoiceSerialNumber": _compact_text(getattr(row, "invoiceNumber", "")),
        "invoiceType": invoice_type,
        "invoiceTypeText": _invoice_type_label(invoice_type),
        "invoiceDate": invoice_date,
        "invoiceDateText": _format_datetime(invoice_date),
        "transactionDate": invoice_date,
        "transactionDateText": _format_datetime(invoice_date),
        "dueDate": getattr(row, "dueDate", None),
        "dueDateText": _format_datetime(getattr(row, "dueDate", None)),
        "companyName": company_name or counterparty or api_company,
        "counterparty": counterparty,
        "sellerAccountId": _compact_text(getattr(getattr(row, "api_account", None), "account_id", "")),
        "totalAmount": getattr(row, "totalAmount", None),
        "totalAmountText": _format_money(getattr(row, "totalAmount", None)),
        "vatAmount": getattr(row, "vatAmount", None),
        "vatAmountText": _format_money(getattr(row, "vatAmount", None)),
        "currency": _compact_text(getattr(row, "currency", "")) or "TRY",
        "filePath": file_path,
        "fileName": Path(file_path).name if file_path else "-",
        "fileType": _compact_text(getattr(row, "fileType", "")),
        "officialStatus": _compact_text(getattr(row, "officialStatus", "")) or "official_copy",
        "sourceReference": _compact_text(getattr(row, "sourceReference", "")),
        "referenceText": _compact_text(getattr(row, "sourceReference", "")) or "-",
        "note": _compact_text(getattr(row, "note", "")),
    }


def _invoice_document_projection_to_dict(row: Any) -> dict[str, Any]:
    (
        pk,
        invoice_number,
        invoice_type_raw,
        invoice_date_raw,
        due_date,
        company_name_raw,
        counterparty_raw,
        api_company_raw,
        seller_account_id_raw,
        total_amount,
        vat_amount,
        currency_raw,
        file_path_raw,
        file_type_raw,
        official_status_raw,
        source_reference_raw,
        note_raw,
    ) = row
    company_name = _compact_text(company_name_raw)
    api_company = _compact_text(api_company_raw)
    counterparty = _compact_text(counterparty_raw)
    file_path = _compact_text(file_path_raw)
    invoice_type = _compact_text(invoice_type_raw) or "other"
    invoice_date = int(_parse_epoch_ms(invoice_date_raw) or 0)
    return {
        "pk": pk,
        "recordKey": _compact_text(pk) or f"{_compact_text(invoice_number)}:{file_path}",
        "invoiceNumber": _compact_text(invoice_number),
        "invoiceSerialNumber": _compact_text(invoice_number),
        "invoiceType": invoice_type,
        "invoiceTypeText": _invoice_type_label(invoice_type),
        "invoiceDate": invoice_date,
        "invoiceDateText": _format_datetime(invoice_date),
        "transactionDate": invoice_date,
        "transactionDateText": _format_datetime(invoice_date),
        "dueDate": due_date,
        "dueDateText": _format_datetime(due_date),
        "companyName": company_name or counterparty or api_company,
        "counterparty": counterparty,
        "sellerAccountId": _compact_text(seller_account_id_raw),
        "totalAmount": total_amount,
        "totalAmountText": _format_money(total_amount),
        "vatAmount": vat_amount,
        "vatAmountText": _format_money(vat_amount),
        "currency": _compact_text(currency_raw) or "TRY",
        "filePath": file_path,
        "fileName": Path(file_path).name if file_path else "-",
        "fileType": _compact_text(file_type_raw),
        "officialStatus": _compact_text(official_status_raw) or "official_copy",
        "sourceReference": _compact_text(source_reference_raw),
        "referenceText": _compact_text(source_reference_raw) or "-",
        "note": _compact_text(note_raw),
    }


def _invoice_type_label(value: Any) -> str:
    raw = _compact_text(value).casefold()
    labels = {
        "purchase": "Alış Faturası",
        "sales": "Satış Faturası",
        "expense": "Gider Faturası",
        "cargo": "Kargo Faturası",
        "commission": "Komisyon Faturası",
        "other": "Diğer Fatura",
    }
    return labels.get(raw, _compact_text(value) or "Diğer Fatura")


def save_finance_invoice_document(payload: dict[str, Any], *, db_name: str | None = None) -> Result:
    try:
        data = dict(payload or {})
        invoice_number = _compact_text(data.get("invoiceNumber") or data.get("invoiceSerialNumber"))
        if not invoice_number:
            return Result.fail("Fatura numarası zorunludur.", close_dialog=False)
        file_path = _compact_text(data.get("filePath") or data.get("path"))
        if not file_path:
            return Result.fail("Resmi fatura sureti için dosya seçilmelidir.", close_dialog=False)
        if not Path(file_path).exists():
            return Result.fail("Seçilen fatura dosyası bulunamadı.", close_dialog=False)
        suffix_with_dot = Path(file_path).suffix.lower()
        if suffix_with_dot not in FINANCE_INVOICE_DOCUMENT_EXTENSIONS:
            return Result.fail("Fatura sureti PDF, görsel, XML veya HTML belge formatında olmalıdır.", close_dialog=False)
        invoice_date = _epoch_ms_from_date_like(data.get("invoiceDate") or data.get("date"))
        currency = _normalize_finance_currency(data.get("currency"))
        suffix = suffix_with_dot.lstrip(".")
        row = FinanceInvoiceDocument(
            invoiceNumber=invoice_number,
            invoiceType=_compact_text(data.get("invoiceType")) or "other",
            invoiceDate=invoice_date,
            dueDate=_parse_epoch_ms(data.get("dueDate")),
            company_id=_safe_int_id(data.get("company_id") or data.get("companyId")),
            counterparty=_compact_text(data.get("counterparty")) or None,
            totalAmount=_optional_float(data.get("totalAmount") or data.get("amount")),
            vatAmount=_optional_float(data.get("vatAmount")),
            currency=currency,
            filePath=str(Path(file_path).resolve()),
            fileType=suffix or None,
            officialStatus="official_copy",
            marketplace_id=_safe_int_id(data.get("marketplace_id") or data.get("marketplaceId")),
            api_account_id=_safe_int_id(data.get("api_account_id") or data.get("apiAccountId")),
            sourceTable=_compact_text(data.get("sourceTable")) or None,
            sourcePk=_safe_int_id(data.get("sourcePk")),
            sourceReference=_compact_text(data.get("sourceReference") or data.get("reference")) or None,
            note=_compact_text(data.get("note")) or None,
            isDeleted=False,
        )
        engine = get_engine(db_name or DB_NAME)
        with Session(engine) as session:
            session.add(row)
            session.commit()
            session.refresh(row)
            record = _invoice_document_to_dict(row)
        return Result.ok("Fatura sureti kaydedildi.", close_dialog=False, data={"record": record})
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def load_finance_invoice_documents_from_db(
    *,
    search_text: str = "",
    company_name: str = "",
    invoice_type: str = "",
    date_from: Any = None,
    date_to: Any = None,
    page: int = 1,
    page_size: int = 20,
    db_name: str | None = None,
) -> Result:
    try:
        start_ms = None
        end_ms = None
        if date_from not in (None, "") and date_to not in (None, ""):
            start_d = _safe_date(date_from)
            end_d = _safe_date(date_to, default_date=start_d)
            if end_d < start_d:
                start_d, end_d = end_d, start_d
            start_ms = _to_epoch_ms(start_d, end_of_day=False)
            end_ms = _to_epoch_ms(end_d, end_of_day=True)

        engine = get_engine(db_name or DB_NAME)
        with Session(engine) as session:
            stmt = (
                select(
                    FinanceInvoiceDocument.pk,
                    FinanceInvoiceDocument.invoiceNumber,
                    FinanceInvoiceDocument.invoiceType,
                    FinanceInvoiceDocument.invoiceDate,
                    FinanceInvoiceDocument.dueDate,
                    Company.name,
                    FinanceInvoiceDocument.counterparty,
                    ApiAccount.comp_name,
                    ApiAccount.account_id,
                    FinanceInvoiceDocument.totalAmount,
                    FinanceInvoiceDocument.vatAmount,
                    FinanceInvoiceDocument.currency,
                    FinanceInvoiceDocument.filePath,
                    FinanceInvoiceDocument.fileType,
                    FinanceInvoiceDocument.officialStatus,
                    FinanceInvoiceDocument.sourceReference,
                    FinanceInvoiceDocument.note,
                )
                .select_from(FinanceInvoiceDocument)
                .outerjoin(Company, FinanceInvoiceDocument.company_id == Company.pk)
                .outerjoin(ApiAccount, FinanceInvoiceDocument.api_account_id == ApiAccount.pk)
                .where(FinanceInvoiceDocument.isDeleted == False)  # noqa: E712
                .order_by(FinanceInvoiceDocument.invoiceDate.desc(), FinanceInvoiceDocument.pk.desc())
            )
            if start_ms not in (None, ""):
                stmt = stmt.where(FinanceInvoiceDocument.invoiceDate >= int(start_ms))
            if end_ms not in (None, ""):
                stmt = stmt.where(FinanceInvoiceDocument.invoiceDate <= int(end_ms))
            clean_type = _compact_text(invoice_type)
            if clean_type:
                stmt = stmt.where(FinanceInvoiceDocument.invoiceType == clean_type)
            rows = session.exec(stmt).all() or []
            records = [_invoice_document_projection_to_dict(row) for row in rows]

        clean_company = _compact_text(company_name).casefold()
        if clean_company:
            records = [
                row for row in records
                if clean_company in {
                    _compact_text(row.get("companyName")).casefold(),
                    _compact_text(row.get("counterparty")).casefold(),
                }
            ]
        clean_search = _compact_text(search_text).casefold()
        if clean_search:
            records = [
                row for row in records
                if clean_search in " ".join(
                    [
                        _compact_text(row.get("invoiceNumber")),
                        _compact_text(row.get("invoiceTypeText")),
                        _compact_text(row.get("companyName")),
                        _compact_text(row.get("counterparty")),
                        _compact_text(row.get("fileName")),
                        _compact_text(row.get("sourceReference")),
                        _compact_text(row.get("note")),
                    ]
                ).casefold()
            ]

        company_names = sorted({_compact_text(row.get("companyName")) for row in records if _compact_text(row.get("companyName"))})
        invoice_types = sorted({_compact_text(row.get("invoiceType")) for row in records if _compact_text(row.get("invoiceType"))})
        total_count = len(records)
        safe_page_size = max(1, int(page_size or 20))
        safe_page = max(1, int(page or 1))
        page_count = max(1, (total_count + safe_page_size - 1) // safe_page_size) if total_count > 0 else 1
        safe_page = min(safe_page, page_count)
        start_idx = (safe_page - 1) * safe_page_size
        paged_records = records[start_idx:start_idx + safe_page_size]
        total_amount = sum(_safe_float(row.get("totalAmount")) for row in records)
        last_invoice_date = max((int(row.get("invoiceDate") or 0) for row in records), default=0)
        return Result.ok(
            "Fatura suretleri veritabanından yüklendi.",
            close_dialog=False,
            data={
                "records": paged_records,
                "all_records": records,
                "total_count": total_count,
                "page": safe_page,
                "page_count": page_count,
                "page_size": safe_page_size,
                "summary_text": (
                    f"Toplam fatura sureti: {total_count} | "
                    f"Toplam tutar: {_format_money(total_amount)} | "
                    f"Son fatura: {_format_datetime(last_invoice_date)}"
                ),
                "metadata": {
                    "company_names": company_names,
                    "invoice_types": invoice_types,
                    "last_invoice_date": last_invoice_date,
                },
            },
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def delete_finance_invoice_document(invoice_pk: int, *, db_name: str | None = None) -> Result:
    try:
        normalized_pk = int(invoice_pk or 0)
        if normalized_pk <= 0:
            return Result.fail("Silinecek fatura sureti bulunamadı.", close_dialog=False)
        engine = get_engine(db_name or DB_NAME)
        with Session(engine) as session:
            row = session.get(FinanceInvoiceDocument, normalized_pk)
            if row is None:
                return Result.fail("Silinecek fatura sureti bulunamadı.", close_dialog=False)
            row.isDeleted = True
            session.add(row)
            session.commit()
        return Result.ok("Fatura sureti silindi.", close_dialog=False)
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


async def action_sync_finance_for_selected_companies(
    company_list_widget,
    *,
    date_from: Any = None,
    date_to: Any = None,
    page_size: int = TRENDYOL_FINANCE_DEFAULT_PAGE_SIZE,
    max_pages: int | None = TRENDYOL_FINANCE_DEFAULT_MAX_PAGES,
    progress_callback=None,
) -> Result:
    try:
        accounts_res = _collect_selected_account_payload(company_list_widget)
        if not accounts_res.success:
            return accounts_res
        accounts = (accounts_res.data or {}).get("accounts", []) or []
        return await action_sync_finance_for_accounts(
            accounts,
            date_from=date_from,
            date_to=date_to,
            page_size=page_size,
            max_pages=max_pages,
            progress_callback=progress_callback,
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


async def action_sync_finance_for_company_pks(
    selected_company_pks: list[int],
    *,
    date_from: Any = None,
    date_to: Any = None,
    page_size: int = TRENDYOL_FINANCE_DEFAULT_PAGE_SIZE,
    max_pages: int | None = TRENDYOL_FINANCE_DEFAULT_MAX_PAGES,
    progress_callback=None,
) -> Result:
    try:
        accounts_res = _collect_account_payload_for_company_pks(selected_company_pks)
        if not accounts_res.success:
            return accounts_res
        accounts = (accounts_res.data or {}).get("accounts", []) or []
        return await action_sync_finance_for_accounts(
            accounts,
            date_from=date_from,
            date_to=date_to,
            page_size=page_size,
            max_pages=max_pages,
            progress_callback=progress_callback,
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


async def action_sync_finance_for_accounts(
    accounts: list[dict[str, Any]],
    *,
    date_from: Any = None,
    date_to: Any = None,
    page_size: int = TRENDYOL_FINANCE_DEFAULT_PAGE_SIZE,
    max_pages: int | None = TRENDYOL_FINANCE_DEFAULT_MAX_PAGES,
    progress_callback=None,
) -> Result:
    try:
        accounts = [dict(account or {}) for account in (accounts or [])]
        if not accounts:
            return Result.fail("Seçili şirketler için API bilgisi bulunamadı.", close_dialog=False)

        plan_res = resolve_finance_sync_plan(accounts)
        if not plan_res.success:
            return plan_res

        plan_data = plan_res.data or {}
        jobs = list(plan_data.get("jobs", []) or [])
        runtime_state = dict(plan_data.get("state") or {})
        now_ms = int(plan_data.get("now_ms") or _now_epoch_ms())
        floor_ms = int(plan_data.get("floor_ms") or _finance_backfill_floor_ms(now_ms))

        if not jobs:
            return Result.ok(
                "Finans verileri zaten gÃ¼ncel.",
                close_dialog=False,
                data={
                    "counts": {"transactions": 0, "cargo_items": 0, "cargo_invoices": 0},
                    "db_counts": {"transactions": 0, "cargo_items": 0},
                    "errors": [],
                    "changed": False,
                },
            )

        safe_page_size = max(1, int(page_size or TRENDYOL_FINANCE_DEFAULT_PAGE_SIZE))
        safe_max_pages = max_pages if max_pages is None else max(1, int(max_pages))
        db_counts = {"transactions": 0, "cargo_items": 0}
        counts = {"transactions": 0, "cargo_items": 0, "cargo_invoices": 0}
        errors: list[dict[str, Any]] = []
        account_summaries: list[dict[str, Any]] = []
        skipped_backfill_accounts: set[str] = set()
        successful_job_count = 0

        total_jobs = max(1, len(jobs))

        for idx, job in enumerate(jobs):
            account_key = _compact_text(job.get("account_key"))
            if job.get("mode") == "backfill" and account_key in skipped_backfill_accounts:
                continue

            def _progress_bridge(current: int, total: int) -> None:
                if not progress_callback:
                    return
                total_safe = max(int(total), 1)
                ratio = max(0.0, min(1.0, float(int(current)) / float(total_safe)))
                overall = int(((idx + ratio) / float(total_jobs)) * 100)
                progress_callback(max(0, min(100, overall)), 100)

            one = await sync_finance_for_accounts(
                [job["account"]],
                transaction_date_start=int(job["start_ms"]),
                transaction_date_end=int(job["end_ms"]),
                page_size=safe_page_size,
                max_pages=safe_max_pages,
                progress_callback=_progress_bridge,
            )

            if not one.success:
                errors.append(
                    {
                        "account_key": account_key,
                        "mode": _compact_text(job.get("mode")),
                        "message": _compact_text(one.message) or "Bilinmeyen finance hatasi",
                    }
                )
                continue

            successful_job_count += 1
            one_data = one.data or {}
            one_counts = one_data.get("counts", {}) or {}
            counts["transactions"] += int(one_counts.get("transactions") or 0)
            counts["cargo_items"] += int(one_counts.get("cargo_items") or 0)
            counts["cargo_invoices"] += int(one_counts.get("cargo_invoices") or 0)
            one_db_counts = one_data.get("db_counts", {}) or {}
            db_counts["transactions"] += int(one_db_counts.get("transactions") or 0)
            db_counts["cargo_items"] += int(one_db_counts.get("cargo_items") or 0)
            account_summaries.extend(list(one_data.get("account_summaries", []) or []))
            errors.extend(list(one_data.get("errors", []) or []))

            backfill_completed = _mark_finance_job_success(
                runtime_state,
                account_key=account_key,
                job=job,
                result=one,
                now_ms=now_ms,
                floor_ms=floor_ms,
            )
            _save_finance_runtime_state(runtime_state)
            if job.get("mode") == "backfill" and backfill_completed:
                skipped_backfill_accounts.add(account_key)

        if progress_callback:
            progress_callback(100, 100)

        changed = db_counts["transactions"] > 0 or db_counts["cargo_items"] > 0
        if successful_job_count <= 0 and errors:
            return Result.fail(
                "Finans verileri alinamadi.",
                close_dialog=False,
                data={
                    "counts": {"transactions": 0, "cargo_items": 0, "cargo_invoices": 0},
                    "db_counts": db_counts,
                    "errors": errors,
                    "account_summaries": account_summaries,
                    "changed": False,
                },
            )

        return Result.ok(
            "Finans verileri alindi ve veritabanina kaydedildi.",
            close_dialog=False,
            data={
                "counts": counts,
                "db_counts": db_counts,
                "errors": errors,
                "account_summaries": account_summaries,
                "changed": changed,
                "job_count": len(jobs),
                "successful_job_count": successful_job_count,
            },
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def load_finance_dashboard_from_db(
    *,
    search_text: str = "",
    service_key: str = "",
    transaction_type: str = "",
    company_name: str = "",
    date_from: Any = None,
    date_to: Any = None,
    limit: int = 500,
    db_name: str | None = None,
) -> Result:
    try:
        metadata_res = get_finance_filter_metadata(db_name=db_name) if db_name else get_finance_filter_metadata()
        if not metadata_res.success:
            return metadata_res
        metadata = metadata_res.data or {}

        start_ms = None
        end_ms = None
        if date_from not in (None, "") and date_to not in (None, ""):
            start_d = _safe_date(date_from)
            end_d = _safe_date(date_to, default_date=start_d)
            if end_d < start_d:
                start_d, end_d = end_d, start_d
            start_ms = _to_epoch_ms(start_d, end_of_day=False)
            end_ms = _to_epoch_ms(end_d, end_of_day=True)

        tx_kwargs = {
            "service_key": _compact_text(service_key) or None,
            "transaction_type": _compact_text(transaction_type) or None,
            "company_name": _compact_text(company_name) or None,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "search_text": _compact_text(search_text) or None,
            "limit": limit,
        }
        if db_name:
            tx_kwargs["db_name"] = db_name

        tx_res = get_finance_transactions_from_db(
            **tx_kwargs,
        )
        if not tx_res.success:
            return tx_res
        transactions = list((tx_res.data or {}).get("records", []) or [])

        invoice_serials = sorted(
            {
                _compact_text(row.get("commissionInvoiceSerialNumber"))
                for row in transactions
                if _compact_text(row.get("commissionInvoiceSerialNumber"))
            }
        )
        if invoice_serials:
            cargo_kwargs = {
                "invoice_serial_numbers": invoice_serials,
                "company_name": _compact_text(company_name) or None,
                "search_text": _compact_text(search_text) or None,
                "limit": limit,
            }
            if db_name:
                cargo_kwargs["db_name"] = db_name
            cargo_res = get_finance_cargo_invoice_items_from_db(**cargo_kwargs)
            if not cargo_res.success:
                return cargo_res
            cargo_items = list((cargo_res.data or {}).get("records", []) or [])
        else:
            cargo_items = []

        transaction_headers, transaction_rows = _build_transaction_table_rows(transactions)
        cargo_headers, cargo_rows = _build_cargo_table_rows(cargo_items)
        insights = _build_finance_insights(transactions=transactions, cargo_items=cargo_items, errors=[])

        return Result.ok(
            "Finans verileri veritabanından yüklendi.",
            close_dialog=False,
            data={
                "metadata": metadata,
                "transactions": transactions,
                "cargo_items": cargo_items,
                "transaction_table_headers": transaction_headers,
                "transaction_table_rows": transaction_rows,
                "cargo_table_headers": cargo_headers,
                "cargo_table_rows": cargo_rows,
                "insights": insights,
                "summary_text": (
                    f"Kayit: {len(transactions)} | Kargo kalemi: {len(cargo_items)} | "
                    f"Son hareket: {_format_datetime(metadata.get('last_sync_at'))}"
                ),
            },
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def load_finance_transactions_from_db(
    *,
    search_text: str = "",
    service_key: str = "",
    transaction_type: str = "",
    company_name: str = "",
    date_from: Any = None,
    date_to: Any = None,
    limit: int = 5000,
    db_name: str | None = None,
) -> Result:
    try:
        metadata_res = get_finance_filter_metadata(db_name=db_name) if db_name else get_finance_filter_metadata()
        if not metadata_res.success:
            return metadata_res
        metadata = dict(metadata_res.data or {})
        safe_limit = int(limit) if limit is not None and int(limit or 0) > 0 else None

        start_ms = None
        end_ms = None
        if date_from not in (None, "") and date_to not in (None, ""):
            start_d = _safe_date(date_from)
            end_d = _safe_date(date_to, default_date=start_d)
            if end_d < start_d:
                start_d, end_d = end_d, start_d
            start_ms = _to_epoch_ms(start_d, end_of_day=False)
            end_ms = _to_epoch_ms(end_d, end_of_day=True)

        clean_service = _compact_text(service_key)
        include_manual = clean_service in {"", FINANCE_MANUAL_SERVICE_KEY}
        include_marketplace = clean_service != FINANCE_MANUAL_SERVICE_KEY

        raw_records: list[dict[str, Any]] = []
        if include_marketplace:
            tx_kwargs = {
                "service_key": clean_service or None,
                "transaction_type": _compact_text(transaction_type) or None,
                "company_name": _compact_text(company_name) or None,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "search_text": _compact_text(search_text) or None,
                "limit": safe_limit,
            }
            if db_name:
                tx_kwargs["db_name"] = db_name
            tx_res = get_finance_transactions_from_db(**tx_kwargs)
            if not tx_res.success:
                return tx_res
            marketplace_rows = [_marketplace_transaction_to_unified(row) for row in list((tx_res.data or {}).get("records", []) or [])]
            cargo_summary = _cargo_summary_by_invoice_serial(
                records=marketplace_rows,
                company_name=_compact_text(company_name) or None,
                db_name=db_name,
            )
            for row in marketplace_rows:
                serial = _compact_text(row.get("commissionInvoiceSerialNumber"))
                if serial and serial in cargo_summary:
                    row.update(cargo_summary[serial])
            raw_records.extend(marketplace_rows)

        if include_manual:
            manual_kwargs = {
                "transaction_type": _compact_text(transaction_type) or None,
                "company_name": _compact_text(company_name) or None,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "search_text": _compact_text(search_text) or None,
                "limit": safe_limit,
            }
            if db_name:
                manual_kwargs["db_name"] = db_name
            manual_res = get_manual_finance_transactions_from_db(**manual_kwargs)
            if not manual_res.success:
                return manual_res
            raw_records.extend(list((manual_res.data or {}).get("records", []) or []))

        raw_records.sort(
            key=lambda row: (
                int(_parse_epoch_ms(row.get("transactionDate")) or 0),
                int(row.get("pk") or 0),
            ),
            reverse=True,
        )
        if limit is not None and int(limit or 0) > 0:
            raw_records = raw_records[: max(1, int(limit or 5000))]

        records: list[dict[str, Any]] = []
        for idx, row in enumerate(raw_records, start=1):
            payload = dict(row or {})
            source_kind = _compact_text(payload.get("sourceKind")) or "marketplace_api"
            record_key = (
                f"{source_kind}:{_compact_text(payload.get('pk'))}"
                if _compact_text(payload.get("pk"))
                else ""
            ) or (
                _compact_text(payload.get("recordKey"))
                or "|".join(
                    [
                        source_kind,
                        _compact_text(payload.get("serviceKey")),
                        _compact_text(payload.get("api_account_id")),
                        _compact_text(payload.get("recordId")),
                        _compact_text(payload.get("transactionDate")),
                    ]
                )
                or str(idx)
            )
            reference = (
                _compact_text(payload.get("referenceNo"))
                or _compact_text(payload.get("paymentOrderId"))
                or _compact_text(payload.get("commissionInvoiceSerialNumber"))
                or _compact_text(payload.get("recordId"))
                or "-"
            )
            payload.update(
                {
                    "recordKey": record_key,
                    "rowNumber": idx,
                    "transactionDateText": _format_datetime(payload.get("transactionDate")),
                    "orderDateText": _format_datetime(payload.get("orderDate")),
                    "paymentDateText": _format_datetime(payload.get("paymentDate")),
                    "serviceLabel": (
                        FINANCE_MANUAL_SERVICE_LABEL
                        if _compact_text(payload.get("serviceKey")) == FINANCE_MANUAL_SERVICE_KEY
                        else _service_label(_compact_text(payload.get("serviceKey")))
                    ),
                    "debtText": _format_money(payload.get("debt")),
                    "creditText": _format_money(payload.get("credit")),
                    "netAmountText": _format_money(payload.get("netAmount")),
                    "amountText": _format_money(payload.get("amount")),
                    "sellerRevenueText": _format_money(payload.get("sellerRevenue")),
                    "commissionAmountText": _format_money(payload.get("commissionAmount")),
                    "commissionRateText": _format_compact_number(payload.get("commissionRate")) or "-",
                    "referenceText": reference,
                }
            )
            records.append(payload)

        total_debt = sum(_safe_float(row.get("debt")) for row in records)
        total_credit = sum(_safe_float(row.get("credit")) for row in records)
        total_net = sum(_safe_float(row.get("netAmount")) for row in records)
        last_transaction_date = max((int(_parse_epoch_ms(row.get("transactionDate")) or 0) for row in records), default=0)

        company_names = {
            _compact_text(row.get("companyName"))
            for row in records
            if _compact_text(row.get("companyName"))
        }
        metadata["company_names"] = sorted({*list(metadata.get("company_names") or []), *company_names})
        service_options = list(finance_service_options(include_all=True))
        if not any(value == FINANCE_MANUAL_SERVICE_KEY for _label, value in service_options):
            service_options.append((FINANCE_MANUAL_SERVICE_LABEL, FINANCE_MANUAL_SERVICE_KEY))
        metadata["service_options"] = service_options
        manual_types = [
            _compact_text(row.get("transactionType"))
            for row in records
            if _compact_text(row.get("serviceKey")) == FINANCE_MANUAL_SERVICE_KEY
            and _compact_text(row.get("transactionType"))
        ]
        metadata["transaction_type_options"] = finance_transaction_type_options(
            [*list(metadata.get("transaction_types") or []), *manual_types],
            include_all=True,
        )
        metadata["last_transaction_date"] = last_transaction_date
        summary_text = (
            f"Toplam hareket: {len(records)} | "
            f"Borç: {_format_money(total_debt)} | "
            f"Alacak: {_format_money(total_credit)} | "
            f"Net: {_format_money(total_net)} | "
            f"Son hareket: {_format_datetime(last_transaction_date)}"
        )

        return Result.ok(
            "Finans hareketleri veritabanından yüklendi.",
            close_dialog=False,
            data={
                "records": records,
                "all_records": records,
                "total_count": len(records),
                "summary_text": summary_text,
                "metadata": metadata,
            },
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def load_finance_cargo_invoices_from_db(
    *,
    search_text: str = "",
    company_name: str = "",
    package_type: str = "",
    date_from: Any = None,
    date_to: Any = None,
    page: int = 1,
    page_size: int = 20,
    db_name: str | None = None,
) -> Result:
    try:
        start_ms = None
        end_ms = None
        if date_from not in (None, "") and date_to not in (None, ""):
            start_d = _safe_date(date_from)
            end_d = _safe_date(date_to, default_date=start_d)
            if end_d < start_d:
                start_d, end_d = end_d, start_d
            start_ms = _to_epoch_ms(start_d, end_of_day=False)
            end_ms = _to_epoch_ms(end_d, end_of_day=True)

        tx_kwargs = {
            "company_name": _compact_text(company_name) or None,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "limit": None,
        }
        if db_name:
            tx_kwargs["db_name"] = db_name
        tx_res = get_finance_cargo_invoice_transactions_from_db(**tx_kwargs)
        if not tx_res.success:
            return tx_res
        transactions = list((tx_res.data or {}).get("records", []) or [])

        invoice_serials = sorted(
            {
                _compact_text(row.get("commissionInvoiceSerialNumber"))
                for row in transactions
                if _compact_text(row.get("commissionInvoiceSerialNumber"))
            }
        )

        if invoice_serials:
            cargo_kwargs = {
                "invoice_serial_numbers": invoice_serials,
                "company_name": _compact_text(company_name) or None,
                "limit": None,
            }
            if db_name:
                cargo_kwargs["db_name"] = db_name
            cargo_res = get_finance_cargo_invoice_items_from_db(**cargo_kwargs)
            if not cargo_res.success:
                return cargo_res
            cargo_items = list((cargo_res.data or {}).get("records", []) or [])
        else:
            cargo_items = []

        base_groups = _build_finance_cargo_invoice_groups(
            transactions=transactions,
            cargo_items=cargo_items,
        )

        company_names = sorted(
            {
                _compact_text(row.get("companyName"))
                for row in base_groups
                if _compact_text(row.get("companyName"))
            }
        )
        package_types = sorted(
            {
                _compact_text(package)
                for row in base_groups
                for package in list(row.get("packageTypes") or [])
                if _compact_text(package)
            }
        )

        grouped = list(base_groups)
        clean_package_type = _compact_text(package_type)
        if clean_package_type:
            grouped = [
                row
                for row in grouped
                if clean_package_type in set(row.get("packageTypes") or [])
            ]

        clean_search = _compact_text(search_text)
        if clean_search:
            grouped = [row for row in grouped if _invoice_matches_search(row, clean_search)]

        total_count = len(grouped)
        safe_page_size = max(1, int(page_size or 20))
        safe_page = max(1, int(page or 1))
        page_count = max(1, (total_count + safe_page_size - 1) // safe_page_size) if total_count > 0 else 1
        safe_page = min(safe_page, page_count)
        start_idx = (safe_page - 1) * safe_page_size
        end_idx = start_idx + safe_page_size
        paged_records = grouped[start_idx:end_idx]

        last_invoice_date = max((int(row.get("transactionDate") or 0) for row in grouped), default=0)
        summary_text = (
            f"Toplam fatura: {total_count} | "
            f"Toplam kalem: {sum(int(row.get('itemCount') or 0) for row in grouped)} | "
            f"Son fatura: {_format_datetime(last_invoice_date)}"
        )

        return Result.ok(
            "Kargo faturaları veritabanından yüklendi.",
            close_dialog=False,
            data={
                "records": paged_records,
                "all_records": grouped,
                "total_count": total_count,
                "page": safe_page,
                "page_count": page_count,
                "page_size": safe_page_size,
                "summary_text": summary_text,
                "metadata": {
                    "company_names": company_names,
                    "package_types": package_types,
                    "last_invoice_date": last_invoice_date,
                },
            },
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def load_finance_quick_summary(*, db_name: str | None = None) -> Result:
    try:
        tx_res = get_finance_cargo_invoice_transactions_from_db(db_name=db_name) if db_name else get_finance_cargo_invoice_transactions_from_db()
        if not tx_res.success:
            return tx_res
        transactions = list((tx_res.data or {}).get("records", []) or [])
        invoice_serials = sorted(
            {
                _compact_text(row.get("commissionInvoiceSerialNumber"))
                for row in transactions
                if _compact_text(row.get("commissionInvoiceSerialNumber"))
            }
        )
        cargo_res = (
            get_finance_cargo_invoice_items_from_db(invoice_serial_numbers=invoice_serials or None, db_name=db_name)
            if db_name
            else get_finance_cargo_invoice_items_from_db(invoice_serial_numbers=invoice_serials or None)
        )
        if not cargo_res.success:
            return cargo_res
        cargo_items = list((cargo_res.data or {}).get("records", []) or [])
        last_sync_at = max((int(_parse_epoch_ms(row.get("transactionDate")) or 0) for row in transactions), default=0)
        if not invoice_serials:
            text = "Henüz kaydedilmiş kargo faturası yok."
        else:
            text = (
                f"Fatura: {len(invoice_serials)} | "
                f"Kalem: {len(cargo_items)} | "
                f"Son fatura: {_format_datetime(last_sync_at)}"
            )
        return Result.ok(
            "Finans hızlı özeti hazır.",
            close_dialog=False,
            data={
                "text": text,
                "metadata": {
                    "invoice_count": len(invoice_serials),
                    "cargo_item_count": len(cargo_items),
                    "last_invoice_date": last_sync_at,
                },
            },
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def load_finance_cost_items(
    *,
    search_text: str = "",
    calculation_type: str = "",
    active_state: str = "",
    source_state: str = "",
    platform_code: str = "",
    storage_path: str | Path | None = None,
    db_name: str | None = None,
    default_storage_path: str | Path | None = None,
) -> Result:
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


def save_finance_cost_item(
    cost_payload: dict[str, Any],
    *,
    storage_path: str | Path | None = None,
    db_name: str | None = None,
    default_storage_path: str | Path | None = None,
) -> Result:
    try:
        payload = dict(cost_payload or {})
        name = _compact_text(payload.get("name"))
        if not name:
            return Result.fail("Maliyet adı zorunludur.", close_dialog=False)

        item_pk = payload.get("pk")
        requested_source_id = _source_id_or_none(payload.get("sourceId") or payload.get("source_id"))
        requested_cost_key = _compact_text(payload.get("costKey"))
        now_iso = _now_iso_text()
        builtin_records = _load_finance_cost_items_default_raw(
            default_storage_path=default_storage_path,
            storage_path=storage_path,
            db_name=db_name,
        )
        user_payload = _load_finance_cost_items_user_payload(storage_path=storage_path, db_name=db_name)
        records = list(user_payload.get("records") or [])
        deleted_keys = {_compact_text(key) for key in list(user_payload.get("deletedKeys") or []) if _compact_text(key)}
        merged_records = _load_finance_cost_items_raw(
            storage_path=storage_path,
            db_name=db_name,
            default_storage_path=default_storage_path,
        )
        normalized_pk = int(item_pk or 0)
        record_index = -1
        record: dict[str, Any] | None = None
        merged_record: dict[str, Any] | None = None
        if normalized_pk > 0:
            merged_record = next(
                (dict(row or {}) for row in merged_records if _row_matches_runtime_pk(row, normalized_pk)),
                None,
            )
        if merged_record is None and (requested_source_id is not None or requested_cost_key):
            merged_record = next(
                (
                    dict(row or {})
                    for row in merged_records
                    if (
                        requested_source_id is not None
                        and _source_id_or_none((row or {}).get("sourceId") or (row or {}).get("source_id")) == requested_source_id
                    )
                    or (requested_cost_key and _compact_text((row or {}).get("costKey")) == requested_cost_key)
                ),
                None,
            )
        if normalized_pk > 0 and merged_record is None:
            return Result.fail("Düzenlenecek maliyet kartı bulunamadı.", close_dialog=False)
        if merged_record is not None:
            existing_cost_key = _compact_text(merged_record.get("costKey"))
            existing_db_pk = _db_pk_or_none(merged_record)
            for idx, row in enumerate(records):
                if (
                    (existing_db_pk is not None and int((row or {}).get("dbPk") or 0) == existing_db_pk)
                    or (
                        requested_source_id is not None
                        and _source_id_or_none((row or {}).get("sourceId") or (row or {}).get("source_id")) == requested_source_id
                    )
                    or _compact_text((row or {}).get("costKey")) == existing_cost_key
                ):
                    record_index = idx
                    record = dict(row or {})
                    break
            if record is None:
                record = {
                    "costKey": existing_cost_key,
                    "createdAt": _compact_text(merged_record.get("createdAt")) or now_iso,
                }
                if existing_db_pk is not None:
                    record["dbPk"] = existing_db_pk
        else:
            record = {"createdAt": now_iso}

        assert record is not None
        is_builtin_target = bool(merged_record and merged_record.get("isBuiltin"))
        if is_builtin_target:
            builtin_base = dict(merged_record or {})
            editable_fields = set(_normalize_editable_fields(builtin_base.get("editableFields"))) or {"name", "description"}
            record["costKey"] = _compact_text(builtin_base.get("costKey"))
            record["editableFields"] = list(_normalize_editable_fields(builtin_base.get("editableFields")))

            record["name"] = name if "name" in editable_fields else _compact_text(builtin_base.get("name"))
            record["description"] = (
                _compact_text(payload.get("description")) or None
                if "description" in editable_fields
                else _compact_text(builtin_base.get("description")) or None
            )

            record["valueType"] = _normalize_cost_value_type(payload) if "valueType" in editable_fields else _normalize_cost_value_type(builtin_base)
            record["defaultMatchMode"] = (
                _normalize_cost_default_match_mode(payload)
                if "defaultMatchMode" in editable_fields
                else _normalize_cost_default_match_mode(builtin_base)
            )

            default_amount = _optional_float(payload.get("defaultAmount")) if "defaultAmount" in editable_fields else _optional_float(builtin_base.get("defaultAmount"))
            if "defaultAmount" in editable_fields and _compact_text(payload.get("defaultAmount")) and default_amount is None:
                return Result.fail(
                    "Varsayılan oran/fiyat sayısal olmalıdır." if _compact_text(record.get("valueType")).casefold() == "percentage" else "Varsayılan fiyat sayısal olmalıdır.",
                    close_dialog=False,
                )
            record["defaultAmount"] = default_amount

            currency = _normalize_finance_currency(
                payload.get("currency") if "currency" in editable_fields else builtin_base.get("currency"),
                fallback=builtin_base.get("currency") or "TRY",
            )
            if "currency" in editable_fields:
                currency_raw = _compact_text(payload.get("currency")).upper()
                if currency_raw and currency_raw not in FINANCE_CURRENCY_OPTIONS:
                    return Result.fail("Geçersiz para birimi.", close_dialog=False)
            record["currency"] = currency

            record["isVatIncluded"] = bool(payload.get("isVatIncluded", True)) if "isVatIncluded" in editable_fields else bool(builtin_base.get("isVatIncluded", True))
            vat_rate = _optional_float(payload.get("vatRate")) if "vatRate" in editable_fields else _optional_float(builtin_base.get("vatRate"))
            if "vatRate" in editable_fields:
                if vat_rate is None:
                    return Result.fail("Maliyet kartı için KDV oranı zorunludur.", close_dialog=False)
                if vat_rate < 0 or vat_rate > 100:
                    return Result.fail("KDV oranı 0 ile 100 arasında olmalıdır.", close_dialog=False)
            record["vatRate"] = vat_rate

            supported_platform_source_ids = (
                _normalize_supported_platform_source_ids(
                    payload.get("supportedPlatformSourceIds") or payload.get("supportedPlatforms"),
                    db_name=db_name,
                )
                if "supportedPlatforms" in editable_fields
                else _normalize_supported_platform_source_ids(
                    builtin_base.get("supportedPlatformSourceIds") or builtin_base.get("supportedPlatforms"),
                    db_name=db_name,
                )
            )
            if "supportedPlatforms" in editable_fields and not supported_platform_source_ids:
                return Result.fail("Maliyet kartı için en az bir platform seçilmelidir.", close_dialog=False)
            if storage_path in (None, ""):
                accepted_platforms = _accepted_finance_cost_item_platform_source_ids(db_name=db_name)
                if not set(supported_platform_source_ids).issubset(accepted_platforms):
                    return Result.fail("Önce ilgili pazaryerlerini kullanıma almalısın.", close_dialog=False)
            record["supportedPlatformSourceIds"] = supported_platform_source_ids
            record["supportedPlatforms"] = _platform_codes_for_source_ids(supported_platform_source_ids, db_name=db_name)
            record["supportedSourceTypes"] = (
                list(payload.get("supportedSourceTypes") or [])
                if "supportedSourceTypes" in editable_fields
                else list(builtin_base.get("supportedSourceTypes") or [])
            )
            record["defaultSourceType"] = (
                _compact_text(payload.get("defaultSourceType"))
                if "defaultSourceType" in editable_fields
                else _compact_text(builtin_base.get("defaultSourceType"))
            )
            record["defaultSourceConfig"] = (
                dict(payload.get("defaultSourceConfig") or {}) or None
                if "defaultSourceConfig" in editable_fields
                else dict(builtin_base.get("defaultSourceConfig") or {}) or None
            )
            record["isActive"] = bool(payload.get("isActive", True)) if "isActive" in editable_fields else bool(builtin_base.get("isActive", True))
        else:
            record["name"] = name
            record["description"] = _compact_text(payload.get("description")) or None
            value_type = _normalize_cost_value_type(payload)
            if value_type not in {key for _, key in FINANCE_COST_VALUE_TYPE_OPTIONS}:
                return Result.fail("Geçersiz değer tipi.", close_dialog=False)

            default_amount_raw = payload.get("defaultAmount")
            default_amount = _optional_float(default_amount_raw)
            if _compact_text(default_amount_raw) and default_amount is None:
                return Result.fail(
                    "Varsayılan oran/fiyat sayısal olmalıdır." if value_type == "percentage" else "Varsayılan fiyat sayısal olmalıdır.",
                    close_dialog=False,
                )
            currency_raw = _compact_text(payload.get("currency")).upper()
            if currency_raw and currency_raw not in FINANCE_CURRENCY_OPTIONS:
                return Result.fail("Geçersiz para birimi.", close_dialog=False)
            is_vat_included = bool(payload.get("isVatIncluded", True))
            vat_rate_raw = payload.get("vatRate")
            vat_rate = _optional_float(vat_rate_raw)
            if vat_rate is None:
                return Result.fail("Maliyet kartı için KDV oranı zorunludur.", close_dialog=False)
            if vat_rate < 0 or vat_rate > 100:
                return Result.fail("KDV oranı 0 ile 100 arasında olmalıdır.", close_dialog=False)

            currency = _normalize_finance_currency(
                currency_raw,
                fallback=(record.get("currency") or (merged_record or {}).get("currency") or "TRY"),
            )
            record["costKey"] = _ensure_unique_finance_cost_key(
                [*builtin_records, *records],
                payload.get("costKey") or name,
                current_pk=normalized_pk,
            )
            record["valueType"] = value_type
            payload_mode = _compact_text(payload.get("defaultMatchMode")).casefold()
            if payload_mode in {"manual", "semi_automatic", "automatic"}:
                current_mode = payload_mode
            else:
                current_mode = "automatic" if _compact_text(record.get("costKey")).casefold() == "kargo" else "manual"
            record["defaultMatchMode"] = current_mode
            record["defaultAmount"] = default_amount
            record["currency"] = currency
            record["isVatIncluded"] = is_vat_included
            record["vatRate"] = vat_rate
            supported_platform_source_ids = _normalize_supported_platform_source_ids(
                payload.get("supportedPlatformSourceIds")
                or payload.get("supportedPlatforms")
                or record.get("supportedPlatformSourceIds")
                or (merged_record or {}).get("supportedPlatformSourceIds")
                or record.get("supportedPlatforms")
                or (merged_record or {}).get("supportedPlatforms"),
                db_name=db_name,
            )
            if not supported_platform_source_ids:
                return Result.fail("Maliyet kartı için en az bir platform seçilmelidir.", close_dialog=False)
            if storage_path in (None, ""):
                accepted_platforms = _accepted_finance_cost_item_platform_source_ids(db_name=db_name)
                if not set(supported_platform_source_ids).issubset(accepted_platforms):
                    return Result.fail("Önce ilgili pazaryerlerini kullanıma almalısın.", close_dialog=False)
            record["supportedPlatformSourceIds"] = supported_platform_source_ids
            record["supportedPlatforms"] = _platform_codes_for_source_ids(supported_platform_source_ids, db_name=db_name)
            record["editableFields"] = []
            current_mode = current_mode if current_mode in {"manual", "semi_automatic", "automatic"} else "manual"
            builtin_rule_key = _system_rule_key_for_row(merged_record) or _system_rule_key_for_row(record)
            if builtin_rule_key:
                record["defaultMatchMode"] = "automatic"
                record["supportedSourceTypes"] = ["manual_value", "builtin_resolver"]
                record["defaultSourceType"] = "builtin_resolver"
                record["defaultSourceConfig"] = {"ruleKey": builtin_rule_key}
            else:
                requested_supported_sources = {
                    normalize_cost_source_type(key, fallback="")
                    for key in list(payload.get("supportedSourceTypes") or [])
                    if str(key or "").strip()
                }
                requested_default_source = normalize_cost_source_type(payload.get("defaultSourceType"), fallback="")
                if "builtin_resolver" in requested_supported_sources or requested_default_source == "builtin_resolver":
                    return Result.fail(
                        "Kural Tabanlı kaynak yalnızca sistemin tanımladığı varsayılan maliyet kartlarında kullanılabilir.",
                        close_dialog=False,
                    )
                record["defaultMatchMode"] = current_mode
                record["supportedSourceTypes"] = ["manual_value"]
                record["defaultSourceType"] = "manual_value"
                record["defaultSourceConfig"] = None
            record["isActive"] = bool(payload.get("isActive", True))
        source_id = (
            requested_source_id
            or _source_id_or_none((merged_record or {}).get("sourceId") or (merged_record or {}).get("source_id"))
        )
        source_type = _compact_text(payload.get("sourceType") or payload.get("source_type")).lower()
        if source_type not in {SOURCE_TYPE_BUILTIN, SOURCE_TYPE_USER}:
            source_type = _compact_text((merged_record or {}).get("sourceType")).lower()
        if source_type not in {SOURCE_TYPE_BUILTIN, SOURCE_TYPE_USER}:
            source_type = SOURCE_TYPE_BUILTIN if is_builtin_target else SOURCE_TYPE_USER
        record["sourceType"] = source_type
        record["sourceId"] = (
            source_id
            or _next_runtime_source_id([*builtin_records, *merged_records, *records])
        )
        record["source_id"] = record["sourceId"]
        if _db_pk_or_none(record) is not None:
            record["pk"] = int(record["dbPk"])
        else:
            record["pk"] = int(record["sourceId"] or 0)
        record.pop("calculationType", None)
        record.pop("unitName", None)
        record.pop("affectsEstimatedProfit", None)
        record.pop("affectsRealProfit", None)
        record["updatedAt"] = now_iso
        if not _compact_text(record.get("createdAt")):
            record["createdAt"] = now_iso

        if record_index >= 0:
            records[record_index] = record
        else:
            records.append(record)
        deleted_keys.discard(_compact_text(record.get("costKey")))
        _save_finance_cost_items_user_payload(
            records,
            deleted_keys=deleted_keys,
            storage_path=storage_path,
            db_name=db_name,
        )

        return Result.ok(
            "Maliyet kartı kaydedildi.",
            close_dialog=False,
            data={"record": _cost_item_to_dict({**record, "isBuiltin": bool(merged_record and merged_record.get("isBuiltin"))})},
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def delete_finance_cost_item(
    item_pk: int,
    *,
    storage_path: str | Path | None = None,
    db_name: str | None = None,
    default_storage_path: str | Path | None = None,
) -> Result:
    try:
        normalized_pk = int(item_pk or 0)
        builtin_records = _load_finance_cost_items_default_raw(
            default_storage_path=default_storage_path,
            storage_path=storage_path,
            db_name=db_name,
        )
        merged_records = _load_finance_cost_items_raw(
            storage_path=storage_path,
            db_name=db_name,
            default_storage_path=default_storage_path,
        )
        target = next((row for row in merged_records if _row_matches_runtime_pk(row, normalized_pk)), None)
        if target is None:
            return Result.fail("Silinecek maliyet kartı bulunamadı.", close_dialog=False)
        if bool((target or {}).get("isBuiltin")):
            return Result.fail(
                "Sistem varsayılan maliyet kartları silinemez. Yalnızca ad veya açıklama düzenlenebilir.",
                close_dialog=False,
            )
        cost_key = _compact_text((target or {}).get("costKey"))
        builtin_keys = {_compact_text(row.get("costKey")) for row in builtin_records if _compact_text(row.get("costKey"))}
        user_payload = _load_finance_cost_items_user_payload(storage_path=storage_path, db_name=db_name)
        records = list(user_payload.get("records") or [])
        deleted_keys = {_compact_text(key) for key in list(user_payload.get("deletedKeys") or []) if _compact_text(key)}
        remaining = [
            row for row in records
            if not _row_matches_runtime_pk(row, normalized_pk) and _compact_text((row or {}).get("costKey")) != cost_key
        ]
        if storage_path in (None, "") or cost_key in builtin_keys:
            deleted_keys.add(cost_key)
        _save_finance_cost_items_user_payload(
            remaining,
            deleted_keys=deleted_keys,
            storage_path=storage_path,
            db_name=db_name,
        )
        return Result.ok("Maliyet kartı silindi.", close_dialog=False)
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def delete_finance_cost_items(
    item_pks: list[int],
    *,
    storage_path: str | Path | None = None,
    db_name: str | None = None,
    default_storage_path: str | Path | None = None,
) -> Result:
    try:
        normalized = sorted({int(pk) for pk in (item_pks or []) if str(pk).strip()})
        if not normalized:
            return Result.fail("Silinecek maliyet kartı seçilmedi.", close_dialog=False)

        key_set = set(normalized)
        builtin_records = _load_finance_cost_items_default_raw(
            default_storage_path=default_storage_path,
            storage_path=storage_path,
            db_name=db_name,
        )
        merged_records = _load_finance_cost_items_raw(
            storage_path=storage_path,
            db_name=db_name,
            default_storage_path=default_storage_path,
        )
        target_rows = [row for row in merged_records if _runtime_record_pk(row) in key_set]
        deleted_count = len(target_rows)
        if deleted_count <= 0:
            return Result.fail("Seçili maliyet kartları bulunamadı.", close_dialog=False)
        builtin_targets = [row for row in target_rows if bool((row or {}).get("isBuiltin"))]
        if builtin_targets:
            return Result.fail(
                "Sistem varsayılan maliyet kartları toplu olarak silinemez.",
                close_dialog=False,
            )
        target_keys = {_compact_text(row.get("costKey")) for row in target_rows if _compact_text(row.get("costKey"))}
        builtin_keys = {_compact_text(row.get("costKey")) for row in builtin_records if _compact_text(row.get("costKey"))}
        user_payload = _load_finance_cost_items_user_payload(storage_path=storage_path, db_name=db_name)
        records = list(user_payload.get("records") or [])
        deleted_keys = {_compact_text(key) for key in list(user_payload.get("deletedKeys") or []) if _compact_text(key)}
        remaining = [
            row for row in records
            if _runtime_record_pk(row) not in key_set and _compact_text((row or {}).get("costKey")) not in target_keys
        ]
        if storage_path in (None, ""):
            deleted_keys.update(target_keys)
        else:
            deleted_keys.update({key for key in target_keys if key in builtin_keys})
        _save_finance_cost_items_user_payload(
            remaining,
            deleted_keys=deleted_keys,
            storage_path=storage_path,
            db_name=db_name,
        )
        return Result.ok(
            "Seçili maliyet kartları silindi.",
            close_dialog=False,
            data={"deleted_count": deleted_count},
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def _cargo_provider_name_for_code(
    code: Any,
    *,
    platform_code: Any = None,
    db_name: str | None = None,
) -> str:
    clean = _compact_text(code).upper()
    if not clean:
        return ""
    return cargo_provider_name_for_code(clean, platform_code=platform_code, db_name=db_name) or clean


def _path_signature(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return (str(path), int(stat.st_mtime_ns), int(stat.st_size))


def _fast_platform_code(value: Any, *, default: str = "") -> str:
    text = _compact_text(value).upper()
    if not text:
        return default
    normalized = re.sub(r"[^A-Z0-9]+", "_", text)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or default


def _finance_platform_label_lookup(*, db_name: str | None = None) -> dict[str, str]:
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


def _finance_cargo_provider_lookup(
    *,
    db_name: str | None = None,
) -> tuple[dict[tuple[str, str], str], dict[str, str]]:
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


def _marketplace_source_maps(*, db_name: str | None = None) -> tuple[dict[int, str], dict[str, int]]:
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


def _cargo_provider_source_maps(
    *,
    db_name: str | None = None,
) -> tuple[dict[int, str], dict[tuple[str, str], int], dict[tuple[str, str], str], dict[int, str]]:
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


def _accepted_cargo_tariff_platform_source_ids(*, db_name: str | None = None) -> set[int]:
    return {
        int(source_id)
        for row in marketplace_records(db_name=db_name)
        for source_id in [coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id"))]
        if source_id is not None
    }


def _accepted_cargo_tariff_provider_source_ids(*, db_name: str | None = None) -> set[int]:
    return {
        int(source_id)
        for row in cargo_provider_records(db_name=db_name)
        for source_id in [coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id"))]
        if source_id is not None
    }


def _ensure_logistics_cargo_provider_link(
    session: Session,
    *,
    platform_code: str,
    provider_code: str,
    platform_source_id: int | None = None,
    provider_source_id: int | None = None,
    provider_name: str | None = None,
    db_name: str | None = None,
    provider_cache: dict[tuple[str, str], tuple[int | None, str | None]] | None = None,
) -> tuple[int | None, str | None]:
    clean_platform_source_id = _source_id_or_none(platform_source_id) or marketplace_source_id_for_code(platform_code, db_name=db_name)
    clean_platform = canonical_platform_code(platform_code) or marketplace_code_for_source_id(clean_platform_source_id, db_name=db_name) or FINANCE_PLATFORM_TRENDYOL
    clean_provider_source_id = _source_id_or_none(provider_source_id) or cargo_provider_source_id_for_code(
        provider_code,
        platform_code=clean_platform,
        db_name=db_name,
    )
    clean_provider_code = (
        cargo_provider_code_for_source_id(clean_provider_source_id, db_name=db_name)
        or _compact_text(provider_code).upper()
    )
    normalized_name = (
        _compact_text(provider_name)
        or _cargo_provider_name_for_code(clean_provider_code, platform_code=clean_platform, db_name=db_name)
        or None
    )
    if not clean_provider_code:
        return None, normalized_name

    cache_key = (clean_platform, clean_provider_code)
    if provider_cache is not None and cache_key in provider_cache:
        cached_provider_id, cached_provider_name = provider_cache[cache_key]
        return cached_provider_id, cached_provider_name or normalized_name

    row = None
    if clean_provider_source_id is not None:
        row = session.exec(
            select(LogisticsCargoProvider).where(LogisticsCargoProvider.sourceId == clean_provider_source_id)
        ).first()
    if row is None:
        row = session.exec(
            select(LogisticsCargoProvider).where(
                LogisticsCargoProvider.platformCode == clean_platform,
                LogisticsCargoProvider.cargoProviderCode == clean_provider_code,
            )
        ).first()
    if row is None:
        if provider_cache is not None:
            provider_cache[cache_key] = (None, normalized_name)
        return None, normalized_name
    if normalized_name and _compact_text(row.cargoProviderName) != normalized_name:
        row.cargoProviderName = normalized_name
        row.updatedAt = _now_iso_text()
        session.flush()

    resolved_provider_id = int(getattr(row, "pk", 0) or 0) or None
    resolved_provider_name = _compact_text(getattr(row, "cargoProviderName", "")) or normalized_name
    if provider_cache is not None:
        provider_cache[cache_key] = (resolved_provider_id, resolved_provider_name)
    return resolved_provider_id, resolved_provider_name


def _resolve_finance_cargo_tariffs_path(
    *,
    storage_path: str | Path | None = None,
    db_name: str | None = None,
) -> Path:
    if storage_path not in (None, ""):
        return Path(storage_path)
    if db_name not in (None, ""):
        base = Path(str(db_name))
        if base.suffix:
            return base.with_name(f"{base.stem}.finance_cargo_tariffs.json")
        return base / "finance_cargo_tariffs.json"
    return FINANCE_CARGO_TARIFFS_FILE


def _resolve_finance_cargo_tariffs_default_path(
    *,
    default_storage_path: str | Path | None = None,
    storage_path: str | Path | None = None,
) -> Path | None:
    if default_storage_path not in (None, ""):
        return Path(default_storage_path)
    if storage_path not in (None, ""):
        return None
    return FINANCE_CARGO_TARIFFS_DEFAULT_FILE


def _normalize_finance_cargo_tariff_rows(
    records: list[dict[str, Any]] | None,
    *,
    is_builtin: bool = False,
    db_name: str | None = None,
) -> list[dict[str, Any]]:
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


def _load_finance_cargo_tariffs_user_payload(
    *,
    storage_path: str | Path | None = None,
    db_name: str | None = None,
) -> dict[str, Any]:
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


def _load_finance_cargo_tariffs_default_raw(
    *,
    default_storage_path: str | Path | None = None,
    storage_path: str | Path | None = None,
    db_name: str | None = None,
) -> list[dict[str, Any]]:
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


def _save_finance_cargo_tariffs_user_payload(
    records: list[dict[str, Any]],
    *,
    deleted_keys: list[str] | set[str] | None = None,
    storage_path: str | Path | None = None,
    db_name: str | None = None,
) -> None:
    if storage_path in (None, ""):
        _save_finance_cargo_tariffs_user_payload_db(
            records,
            deleted_keys=deleted_keys,
            db_name=db_name,
        )
        return
    path = _resolve_finance_cargo_tariffs_path(storage_path=storage_path, db_name=db_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned_records: list[dict[str, Any]] = []
    for row in list(records or []):
        if not isinstance(row, dict):
            continue
        platform_source_id = _source_id_or_none(row.get("platformSourceId") or row.get("platform_source_id"))
        platform_code = (
            marketplace_code_for_source_id(platform_source_id, db_name=db_name)
            or canonical_platform_code(row.get("platform"))
            or FINANCE_PLATFORM_TRENDYOL
        )
        platform_source_id = platform_source_id or marketplace_source_id_for_code(platform_code, db_name=db_name)
        provider_source_id = _source_id_or_none(row.get("cargoProviderSourceId") or row.get("cargo_provider_source_id"))
        provider_code = (
            cargo_provider_code_for_source_id(provider_source_id, db_name=db_name)
            or _compact_text(row.get("cargoProviderCode")).upper()
        )
        provider_source_id = provider_source_id or cargo_provider_source_id_for_code(
            provider_code,
            platform_code=platform_code,
            db_name=db_name,
        )
        provider_name = (
            _compact_text(row.get("cargoProviderName"))
            or _cargo_provider_name_for_code(provider_code, platform_code=platform_code, db_name=db_name)
            or None
        )
        is_vat_included = bool(row.get("isVatIncluded", True))
        source_type = _compact_text(row.get("sourceType") or row.get("source_type")).lower()
        if source_type not in {SOURCE_TYPE_BUILTIN, SOURCE_TYPE_USER}:
            source_type = SOURCE_TYPE_BUILTIN if bool(row.get("isBuiltin")) else SOURCE_TYPE_USER
        source_id = _source_id_or_none(row.get("sourceId") or row.get("source_id"))
        if source_id is None:
            source_id = _next_runtime_source_id([*cleaned_records, row])
        cleaned_records.append(
            {
                "tariffKey": _compact_text(row.get("tariffKey")),
                "name": _compact_text(row.get("name")),
                "description": _compact_text(row.get("description")) or None,
                "platform": platform_code,
                "platformSourceId": platform_source_id,
                "platform_source_id": platform_source_id,
                "cargoProviderCode": provider_code or None,
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
                "sourceType": source_type,
                "sourceId": source_id,
                "source_id": source_id,
            }
        )
    payload = {
        "records": cleaned_records,
        "deletedKeys": sorted({_compact_text(key) for key in list(deleted_keys or []) if _compact_text(key)}),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


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


def _load_finance_cargo_tariffs_user_payload_db(*, db_name: str | None = None) -> dict[str, Any]:
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


def _save_finance_cargo_tariffs_user_payload_db(
    records: list[dict[str, Any]],
    *,
    deleted_keys: list[str] | set[str] | None = None,
    db_name: str | None = None,
) -> None:
    builtin_by_key = {
        _compact_text(row.get("tariffKey")).casefold(): dict(row or {})
        for row in _load_finance_cargo_tariffs_default_raw(db_name=db_name)
        if _compact_text(row.get("tariffKey"))
    }
    cleaned_records: list[dict[str, Any]] = []
    for row in list(records or []):
        if not isinstance(row, dict):
            continue
        tariff_key = _compact_text(row.get("tariffKey"))
        builtin_row = builtin_by_key.get(tariff_key.casefold())
        platform_source_id = _source_id_or_none(row.get("platformSourceId") or row.get("platform_source_id"))
        platform_code = (
            marketplace_code_for_source_id(platform_source_id, db_name=db_name)
            or canonical_platform_code(row.get("platform"))
            or FINANCE_PLATFORM_TRENDYOL
        )
        platform_source_id = platform_source_id or marketplace_source_id_for_code(platform_code, db_name=db_name)
        provider_source_id = _source_id_or_none(row.get("cargoProviderSourceId") or row.get("cargo_provider_source_id"))
        provider_code = (
            cargo_provider_code_for_source_id(provider_source_id, db_name=db_name)
            or _compact_text(row.get("cargoProviderCode")).upper()
        )
        provider_source_id = provider_source_id or cargo_provider_source_id_for_code(
            provider_code,
            platform_code=platform_code,
            db_name=db_name,
        )
        provider_name = (
            _compact_text(row.get("cargoProviderName"))
            or _cargo_provider_name_for_code(provider_code, platform_code=platform_code, db_name=db_name)
            or None
        )
        source_type = _compact_text(row.get("sourceType") or row.get("source_type")).lower()
        if builtin_row is not None:
            source_type = SOURCE_TYPE_BUILTIN
        elif source_type not in {SOURCE_TYPE_BUILTIN, SOURCE_TYPE_USER}:
            source_type = SOURCE_TYPE_BUILTIN if bool(row.get("isBuiltin")) else SOURCE_TYPE_USER
        source_id = _source_id_or_none(row.get("sourceId") or row.get("source_id"))
        if builtin_row is not None:
            source_id = (
                _source_id_or_none(builtin_row.get("sourceId") or builtin_row.get("source_id"))
                or source_id
            )
        elif source_id is None:
            source_id = _next_runtime_source_id([*cleaned_records, row])
        cleaned_records.append(
            {
                "pk": _runtime_record_pk(row) or None,
                "dbPk": _db_pk_or_none(row),
                "tariffKey": tariff_key,
                "name": _compact_text(row.get("name")) or None,
                "description": _compact_text(row.get("description")) or None,
                "cargo_provider_id": None,
                "platform": platform_code,
                "platformSourceId": platform_source_id,
                "platform_source_id": platform_source_id,
                "cargoProviderCode": provider_code or None,
                "cargoProviderSourceId": provider_source_id,
                "cargo_provider_source_id": provider_source_id,
                "cargoProviderName": provider_name,
                "minDesi": _optional_float(row.get("minDesi")),
                "maxDesi": _optional_float(row.get("maxDesi")),
                "minSalePrice": _optional_float(row.get("minSalePrice")),
                "maxSalePrice": _optional_float(row.get("maxSalePrice")),
                "amount": _optional_float(row.get("amount")),
                "currency": _normalize_finance_currency(row.get("currency")),
                "isVatIncluded": bool(row.get("isVatIncluded", True)),
                "vatRate": _optional_float(row.get("vatRate")),
                "isActive": bool(row.get("isActive", True)),
                "isDeleted": False,
                "createdAt": _compact_text(row.get("createdAt")) or _now_iso_text(),
                "updatedAt": _compact_text(row.get("updatedAt")) or _now_iso_text(),
                "sourceType": source_type,
                "sourceId": source_id,
                "source_id": source_id,
            }
        )

    active_rows_by_key: dict[str, dict[str, Any]] = {}
    for row in cleaned_records:
        tariff_key = _compact_text(row.get("tariffKey"))
        if not tariff_key:
            continue
        active_rows_by_key[tariff_key.casefold()] = dict(row)

    deleted_key_set = {
        _compact_text(key)
        for key in list(deleted_keys or [])
        if _compact_text(key)
    }
    builtin_records = _load_finance_cargo_tariffs_default_raw(
        db_name=db_name,
    )

    engine = get_engine(db_name or DB_NAME)
    with Session(engine) as session:
        existing_rows = session.exec(select(LogisticsCargoTariff).order_by(LogisticsCargoTariff.pk.asc())).all() or []
        existing_provider_rows = session.exec(
            select(LogisticsCargoProvider).order_by(LogisticsCargoProvider.pk.asc())
        ).all() or []
        existing_by_key = {
            _compact_text(row.tariffKey).casefold(): row
            for row in existing_rows
            if _compact_text(row.tariffKey)
        }
        existing_by_pk = {
            int(row.pk or 0): row
            for row in existing_rows
            if int(row.pk or 0) > 0
        }
        existing_by_source_id = {
            coerce_source_id(getattr(row, "sourceId", None)): row
            for row in existing_rows
            if coerce_source_id(getattr(row, "sourceId", None)) is not None
        }
        provider_link_cache: dict[tuple[str, str], tuple[int | None, str | None]] = {
            (
                canonical_platform_code(getattr(row, "platformCode", "")) or FINANCE_PLATFORM_TRENDYOL,
                _compact_text(getattr(row, "cargoProviderCode", "")).upper(),
            ): (
                int(getattr(row, "pk", 0) or 0) or None,
                _compact_text(getattr(row, "cargoProviderName", "")) or None,
            )
            for row in existing_provider_rows
            if _compact_text(getattr(row, "cargoProviderCode", ""))
        }

        def _apply_row(model_row: LogisticsCargoTariff, payload: dict[str, Any]) -> None:
            for field_name, field_value in payload.items():
                if field_name in {
                    "dbPk",
                    "source_id",
                    "platformSourceId",
                    "platform_source_id",
                    "cargoProviderSourceId",
                    "cargo_provider_source_id",
                }:
                    continue
                setattr(model_row, field_name, field_value)

        for row in cleaned_records:
            tariff_key = _compact_text(row.get("tariffKey"))
            if not tariff_key:
                continue
            cargo_provider_id, resolved_provider_name = _ensure_logistics_cargo_provider_link(
                session,
                platform_code=str(row.get("platform") or FINANCE_PLATFORM_TRENDYOL),
                provider_code=str(row.get("cargoProviderCode") or ""),
                platform_source_id=row.get("platformSourceId") or row.get("platform_source_id"),
                provider_source_id=row.get("cargoProviderSourceId") or row.get("cargo_provider_source_id"),
                provider_name=str(row.get("cargoProviderName") or ""),
                db_name=db_name,
                provider_cache=provider_link_cache,
            )
            row["cargo_provider_id"] = cargo_provider_id
            if resolved_provider_name:
                row["cargoProviderName"] = resolved_provider_name
            row_pk = int(row.get("dbPk") or 0)
            model_row = existing_by_pk.get(row_pk) if row_pk > 0 else None
            row_source_id = _source_id_or_none(row.get("sourceId") or row.get("source_id"))
            if model_row is None and row_source_id is not None:
                model_row = existing_by_source_id.get(row_source_id)
            if model_row is None:
                model_row = existing_by_key.get(tariff_key.casefold())
            if model_row is None:
                model_row = LogisticsCargoTariff(
                    **{
                        key: value
                        for key, value in row.items()
                        if key not in {"dbPk", "source_id", "platformSourceId", "platform_source_id", "cargoProviderSourceId", "cargo_provider_source_id"}
                    }
                )
                session.add(model_row)
                if row_source_id is not None:
                    existing_by_source_id[row_source_id] = model_row
                existing_by_key[tariff_key.casefold()] = model_row
                continue
            _apply_row(model_row, row)

        tombstone_time = _now_iso_text()
        tombstone_targets = {key.casefold(): key for key in deleted_key_set}
        builtin_key_casefolds = {
            _compact_text(row.get("tariffKey")).casefold()
            for row in builtin_records
            if _compact_text(row.get("tariffKey"))
        }

        for tariff_key_cf, original_key in sorted(tombstone_targets.items()):
            model_row = existing_by_key.get(tariff_key_cf)
            if model_row is None:
                tombstone_source_type = SOURCE_TYPE_BUILTIN if tariff_key_cf in builtin_key_casefolds else SOURCE_TYPE_USER
                session.add(
                    LogisticsCargoTariff(
                        tariffKey=original_key,
                        name=None,
                        description=None,
                        cargo_provider_id=None,
                        platform=FINANCE_PLATFORM_TRENDYOL,
                        cargoProviderCode=None,
                        cargoProviderName=None,
                        minDesi=None,
                        maxDesi=None,
                        minSalePrice=None,
                        maxSalePrice=None,
                        amount=None,
                        currency="TRY",
                        isVatIncluded=True,
                        vatRate=None,
                        isActive=False,
                        isDeleted=True,
                        createdAt=tombstone_time,
                        updatedAt=tombstone_time,
                        sourceType=tombstone_source_type,
                        sourceId=_next_runtime_source_id(cleaned_records),
                    )
                )
                continue
            model_row.isActive = False
            model_row.isDeleted = True
            model_row.updatedAt = tombstone_time
            if not _compact_text(model_row.createdAt):
                model_row.createdAt = tombstone_time

        session.commit()


def _load_finance_cargo_tariffs_raw(
    *,
    storage_path: str | Path | None = None,
    db_name: str | None = None,
    default_storage_path: str | Path | None = None,
) -> list[dict[str, Any]]:
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


def _next_finance_cargo_tariff_pk(records: list[dict[str, Any]]) -> int:
    max_pk = 0
    for row in list(records or []):
        try:
            max_pk = max(max_pk, int((row or {}).get("pk") or 0))
        except Exception:
            continue
    return max_pk + 1


def _ensure_unique_finance_cargo_tariff_key(
    records: list[dict[str, Any]],
    desired_key: Any,
    *,
    current_pk: int | None = None,
) -> str:
    base = _slugify_method_key(desired_key).replace("_", "-")
    existing = {
        _compact_text(row.get("tariffKey")).casefold()
        for row in list(records or [])
        if int((row or {}).get("pk") or 0) != int(current_pk or 0)
    }
    if base.casefold() not in existing:
        return base
    suffix = 2
    while True:
        candidate = f"{base}-{suffix}"
        if candidate.casefold() not in existing:
            return candidate
        suffix += 1


def _range_label(min_value: Any, max_value: Any, *, suffix: str = "", empty_text: str = "-") -> str:
    left = _optional_float(min_value)
    right = _optional_float(max_value)
    if left is None and right is None:
        return empty_text
    if left is not None and right is not None:
        return f"{left:g} - {right:g}{suffix}"
    if left is not None:
        return f"{left:g}+{suffix}"
    return f"0 - {right:g}{suffix}"


def _cargo_tariff_to_dict(
    row: dict[str, Any],
    *,
    platform_label_lookup: dict[str, str] | None = None,
    provider_lookup: dict[tuple[str, str], str] | None = None,
    provider_fallback_lookup: dict[str, str] | None = None,
    marketplace_code_by_source_id: dict[int, str] | None = None,
    provider_code_by_source_id: dict[int, str] | None = None,
    provider_name_by_source_id: dict[int, str] | None = None,
    db_name: str | None = None,
) -> dict[str, Any]:
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


def load_finance_cargo_tariffs(
    *,
    search_text: str = "",
    platform: str = "",
    cargo_provider_code: str = "",
    active_state: str = "",
    source_state: str = "",
    storage_path: str | Path | None = None,
    db_name: str | None = None,
    default_storage_path: str | Path | None = None,
) -> Result:
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


def load_finance_cargo_tariffs_summary(
    *,
    storage_path: str | Path | None = None,
    db_name: str | None = None,
    default_storage_path: str | Path | None = None,
) -> Result:
    try:
        raw_records = _load_finance_cargo_tariffs_raw(
            storage_path=storage_path,
            db_name=db_name,
            default_storage_path=default_storage_path,
        )
        total_count = len(raw_records)
        active_count = sum(1 for row in raw_records if bool((row or {}).get("isActive", True)))
        return Result.ok(
            "Kargo tarifesi Ã¶zeti yÃ¼klendi.",
            close_dialog=False,
            data={
                "total_count": total_count,
                "active_count": active_count,
            },
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def accept_finance_cargo_tariff(
    item_pk: int,
    *,
    storage_path: str | Path | None = None,
    db_name: str | None = None,
    default_storage_path: str | Path | None = None,
) -> Result:
    try:
        normalized_pk = int(item_pk or 0)
        if normalized_pk <= 0:
            return Result.fail("Kabul edilecek kargo tarifesi bulunamadı.", close_dialog=False)

        merged_records = _load_finance_cargo_tariffs_raw(
            storage_path=storage_path,
            db_name=db_name,
            default_storage_path=default_storage_path,
        )
        target = next((dict(row or {}) for row in merged_records if _row_matches_runtime_pk(row, normalized_pk)), None)
        if target is None:
            return Result.fail("Kabul edilecek kargo tarifesi bulunamadı.", close_dialog=False)
        if not bool(target.get("isBuiltin")):
            return Result.fail("Bu kayıt önerilen bir kargo tarifesi değil.", close_dialog=False)
        if bool(target.get("isBuiltinAccepted")):
            return Result.ok("Kargo tarifesi zaten kullanıma alınmış.", close_dialog=False)

        save_payload = {
            "tariffKey": _compact_text(target.get("tariffKey")),
            "name": _compact_text(target.get("name")),
            "description": _compact_text(target.get("description")) or None,
            "platform": _fast_platform_code(target.get("platform"), default=FINANCE_PLATFORM_TRENDYOL),
            "platformSourceId": _source_id_or_none(target.get("platformSourceId") or target.get("platform_source_id")),
            "cargoProviderCode": _compact_text(target.get("cargoProviderCode")).upper(),
            "cargoProviderSourceId": _source_id_or_none(target.get("cargoProviderSourceId") or target.get("cargo_provider_source_id")),
            "cargoProviderName": _compact_text(target.get("cargoProviderName")) or None,
            "minDesi": target.get("minDesi"),
            "maxDesi": target.get("maxDesi"),
            "minSalePrice": target.get("minSalePrice"),
            "maxSalePrice": target.get("maxSalePrice"),
            "amount": target.get("amount"),
            "currency": _normalize_finance_currency(target.get("currency")),
            "isVatIncluded": bool(target.get("isVatIncluded", True)),
            "vatRate": _optional_float(target.get("vatRate")),
            "isActive": bool(target.get("isActive", True)),
            "isBuiltin": True,
            "sourceType": SOURCE_TYPE_BUILTIN,
            "sourceId": _source_id_or_none(target.get("sourceId") or target.get("source_id")),
            "source_id": _source_id_or_none(target.get("sourceId") or target.get("source_id")),
        }
        result = save_finance_cargo_tariff(
            save_payload,
            storage_path=storage_path,
            db_name=db_name,
            default_storage_path=default_storage_path,
        )
        if result.success:
            result.message = "Önerilen kargo tarifesi kullanıma alındı."
        return result
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def accept_finance_cargo_tariffs(
    item_pks: list[int],
    *,
    storage_path: str | Path | None = None,
    db_name: str | None = None,
    default_storage_path: str | Path | None = None,
) -> Result:
    try:
        normalized_pks = []
        seen_pks: set[int] = set()
        for raw_pk in list(item_pks or []):
            try:
                pk = int(raw_pk or 0)
            except Exception:
                pk = 0
            if pk <= 0 or pk in seen_pks:
                continue
            seen_pks.add(pk)
            normalized_pks.append(pk)
        if not normalized_pks:
            return Result.fail("Kabul edilecek kargo tarifesi bulunamadı.", close_dialog=False)

        merged_records = _load_finance_cargo_tariffs_raw(
            storage_path=storage_path,
            db_name=db_name,
            default_storage_path=default_storage_path,
        )
        merged_by_pk = {
            _runtime_record_pk(row): dict(row or {})
            for row in merged_records
            if _runtime_record_pk(row) > 0
        }
        targets: list[dict[str, Any]] = []
        for pk in normalized_pks:
            target = dict(merged_by_pk.get(pk) or {})
            if not target:
                return Result.fail("Kabul edilecek kargo tarifesi bulunamadı.", close_dialog=False)
            if not bool(target.get("isBuiltin")):
                return Result.fail("Bu kayıt önerilen bir kargo tarifesi değil.", close_dialog=False)
            if bool(target.get("isBuiltinAccepted")):
                continue
            targets.append(target)
        if not targets:
            return Result.ok("Önerilen kargo tarifeleri zaten kullanıma alınmış.", close_dialog=False)

        provider_name_overrides: dict[tuple[str, str], str] = {}
        if storage_path in (None, ""):
            engine = get_engine(db_name or DB_NAME)
            with Session(engine) as session:
                accepted_marketplace_source_ids = {
                    coerce_source_id(source_id)
                    for source_id in session.exec(select(Marketplace.sourceId).order_by(Marketplace.pk.asc())).all() or []
                    if coerce_source_id(source_id) is not None
                }
                accepted_provider_rows = session.exec(
                    select(LogisticsCargoProvider.sourceId, LogisticsCargoProvider.cargoProviderName)
                    .order_by(LogisticsCargoProvider.pk.asc())
                ).all() or []
                accepted_provider_names = {
                    coerce_source_id(source_id): _compact_text(provider_name)
                    for source_id, provider_name in accepted_provider_rows
                    if coerce_source_id(source_id) is not None
                }
            for target in targets:
                platform_source_id = _source_id_or_none(target.get("platformSourceId") or target.get("platform_source_id"))
                if platform_source_id not in accepted_marketplace_source_ids:
                    return Result.fail("Önce ilgili pazaryerini kullanıma almalısın.", close_dialog=False)
                provider_source_id = _source_id_or_none(target.get("cargoProviderSourceId") or target.get("cargo_provider_source_id"))
                if provider_source_id is not None:
                    provider_name = _compact_text(accepted_provider_names.get(provider_source_id))
                    if not provider_name:
                        return Result.fail("Önce ilgili kargo firmasını kullanıma almalısın.", close_dialog=False)
                    platform = marketplace_code_for_source_id(platform_source_id, db_name=db_name) or _fast_platform_code(target.get("platform"), default=FINANCE_PLATFORM_TRENDYOL)
                    provider_code = cargo_provider_code_for_source_id(provider_source_id, db_name=db_name) or _compact_text(target.get("cargoProviderCode")).upper()
                    provider_name_overrides[(platform, provider_code)] = provider_name

        now_iso = _now_iso_text()
        accepted_records: list[dict[str, Any]] = []

        for target in targets:
            platform = _fast_platform_code(target.get("platform"), default=FINANCE_PLATFORM_TRENDYOL)
            provider_code = _compact_text(target.get("cargoProviderCode")).upper()
            provider_name = (
                provider_name_overrides.get((platform, provider_code))
                or _compact_text(target.get("cargoProviderName"))
                or None
            )
            accepted_records.append(
                {
                "tariffKey": _compact_text(target.get("tariffKey")),
                "name": _compact_text(target.get("name")),
                "description": _compact_text(target.get("description")) or None,
                "platform": platform,
                "platformSourceId": _source_id_or_none(target.get("platformSourceId") or target.get("platform_source_id")),
                "platform_source_id": _source_id_or_none(target.get("platformSourceId") or target.get("platform_source_id")),
                "cargoProviderCode": provider_code or None,
                "cargoProviderSourceId": _source_id_or_none(target.get("cargoProviderSourceId") or target.get("cargo_provider_source_id")),
                "cargo_provider_source_id": _source_id_or_none(target.get("cargoProviderSourceId") or target.get("cargo_provider_source_id")),
                "cargoProviderName": provider_name,
                "minDesi": target.get("minDesi"),
                "maxDesi": target.get("maxDesi"),
                "minSalePrice": target.get("minSalePrice"),
                "maxSalePrice": target.get("maxSalePrice"),
                "amount": target.get("amount"),
                "currency": _normalize_finance_currency(target.get("currency")),
                "isVatIncluded": bool(target.get("isVatIncluded", True)),
                "vatRate": _optional_float(target.get("vatRate")),
                "isActive": bool(target.get("isActive", True)),
                "createdAt": _compact_text(target.get("createdAt")) or now_iso,
                "updatedAt": now_iso,
                "isBuiltin": True,
                "sourceType": SOURCE_TYPE_BUILTIN,
                "sourceId": _source_id_or_none(target.get("sourceId") or target.get("source_id")),
                "source_id": _source_id_or_none(target.get("sourceId") or target.get("source_id")),
            }
            )

        if storage_path in (None, ""):
            _save_finance_cargo_tariffs_user_payload_db(
                accepted_records,
                deleted_keys=set(),
                db_name=db_name,
            )
        else:
            user_payload = _load_finance_cargo_tariffs_user_payload(storage_path=storage_path, db_name=db_name)
            records = [dict(row or {}) for row in list(user_payload.get("records") or [])]
            deleted_keys = {
                _compact_text(key) for key in list(user_payload.get("deletedKeys") or []) if _compact_text(key)
            }
            records_by_pk = {
                int((row or {}).get("pk") or 0): idx
                for idx, row in enumerate(records)
                if int((row or {}).get("pk") or 0) > 0
            }
            records_by_key = {
                _compact_text((row or {}).get("tariffKey")): idx
                for idx, row in enumerate(records)
                if _compact_text((row or {}).get("tariffKey"))
            }
            for target, record in zip(targets, accepted_records):
                normalized_pk = _runtime_record_pk(target)
                target_key = _compact_text(record.get("tariffKey"))
                record_index = records_by_pk.get(normalized_pk)
                if record_index is None and target_key:
                    record_index = records_by_key.get(target_key)
                created_at = now_iso
                if record_index is not None and 0 <= record_index < len(records):
                    created_at = _compact_text(records[record_index].get("createdAt")) or created_at
                    record["createdAt"] = created_at
                    records[record_index] = record
                else:
                    if not _compact_text(record.get("createdAt")):
                        record["createdAt"] = _compact_text(target.get("createdAt")) or created_at
                    records_by_pk[normalized_pk] = len(records)
                    if target_key:
                        records_by_key[target_key] = len(records)
                    records.append(record)
                deleted_keys.discard(target_key)
            _save_finance_cargo_tariffs_user_payload(
                records,
                deleted_keys=deleted_keys,
                storage_path=storage_path,
                db_name=db_name,
            )
        return Result.ok(
            f"{len(targets)} önerilen kargo tarifesi kullanıma alındı.",
            close_dialog=False,
            data={"accepted_count": len(targets)},
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def save_finance_cargo_tariff(
    tariff_payload: dict[str, Any],
    *,
    storage_path: str | Path | None = None,
    db_name: str | None = None,
    default_storage_path: str | Path | None = None,
) -> Result:
    try:
        payload = dict(tariff_payload or {})
        name = _compact_text(payload.get("name"))
        if not name:
            return Result.fail("Tarife adı zorunludur.", close_dialog=False)

        platform_source_id = _source_id_or_none(
            payload.get("platformSourceId")
            or payload.get("platform_source_id")
            or payload.get("platform")
        )
        platform = (
            marketplace_code_for_source_id(platform_source_id, db_name=db_name)
            or canonical_platform_code(payload.get("platform"))
            or FINANCE_PLATFORM_TRENDYOL
        )
        platform_source_id = platform_source_id or marketplace_source_id_for_code(platform, db_name=db_name)
        visible_fields = finance_cargo_tariff_visible_fields(platform)
        currency = _compact_text(payload.get("currency")) or "TRY"
        if currency not in FINANCE_CURRENCY_OPTIONS:
            return Result.fail("Geçersiz para birimi.", close_dialog=False)

        min_desi = _optional_float(payload.get("minDesi")) if "desiRange" in visible_fields else None
        max_desi = _optional_float(payload.get("maxDesi")) if "desiRange" in visible_fields else None
        min_sale_price = _optional_float(payload.get("minSalePrice")) if "salePriceRange" in visible_fields else None
        max_sale_price = _optional_float(payload.get("maxSalePrice")) if "salePriceRange" in visible_fields else None
        amount = _optional_float(payload.get("amount"))
        is_vat_included = bool(payload.get("isVatIncluded", True))
        vat_rate = _optional_float(payload.get("vatRate")) if "vatRate" in visible_fields else None
        if min_desi is not None and max_desi is not None and min_desi > max_desi:
            return Result.fail("Min desi, max desiden büyük olamaz.", close_dialog=False)
        if min_sale_price is not None and max_sale_price is not None and min_sale_price > max_sale_price:
            return Result.fail("Min fiyat, max fiyattan büyük olamaz.", close_dialog=False)
        if not is_vat_included:
            if vat_rate is None:
                return Result.fail("KDV hariç ücret için KDV oranı zorunludur.", close_dialog=False)
            if vat_rate < 0 or vat_rate > 100:
                return Result.fail("KDV oranı 0 ile 100 arasında olmalıdır.", close_dialog=False)

        provider_source_id = _source_id_or_none(
            payload.get("cargoProviderSourceId")
            or payload.get("cargo_provider_source_id")
            or payload.get("cargoProviderCode")
        ) if "cargoProvider" in visible_fields else None
        provider_code = (
            cargo_provider_code_for_source_id(provider_source_id, db_name=db_name)
            or _compact_text(payload.get("cargoProviderCode")).upper()
        ) if "cargoProvider" in visible_fields else ""
        provider_source_id = (
            provider_source_id
            or cargo_provider_source_id_for_code(provider_code, platform_code=platform, db_name=db_name)
        ) if provider_code else None
        provider_name = (
            _compact_text(payload.get("cargoProviderName"))
            or _cargo_provider_name_for_code(provider_code, platform_code=platform, db_name=db_name)
            or None
        )
        if storage_path in (None, ""):
            if marketplace_db_id_for_source_id(platform_source_id, db_name=db_name) is None:
                return Result.fail("Önce ilgili pazaryerini kullanıma almalısın.", close_dialog=False)
            if provider_code:
                engine = get_engine(db_name or DB_NAME)
                with Session(engine) as session:
                    provider_row = None
                    if provider_source_id is not None:
                        provider_row = session.exec(
                            select(LogisticsCargoProvider).where(LogisticsCargoProvider.sourceId == provider_source_id)
                        ).first()
                    if provider_row is None:
                        provider_row = session.exec(
                            select(LogisticsCargoProvider).where(
                                LogisticsCargoProvider.platformCode == platform,
                                LogisticsCargoProvider.cargoProviderCode == provider_code,
                            )
                        ).first()
                if provider_row is None:
                    return Result.fail("Önce ilgili kargo firmasını kullanıma almalısın.", close_dialog=False)
                resolved_provider_name = _compact_text(getattr(provider_row, "cargoProviderName", ""))
                if resolved_provider_name:
                    provider_name = resolved_provider_name
                provider_source_id = coerce_source_id(getattr(provider_row, "sourceId", None)) or provider_source_id

        item_pk = payload.get("pk")
        requested_source_id = _source_id_or_none(payload.get("sourceId") or payload.get("source_id"))
        requested_tariff_key = _compact_text(payload.get("tariffKey"))
        now_iso = _now_iso_text()
        builtin_records = _load_finance_cargo_tariffs_default_raw(
            default_storage_path=default_storage_path,
            storage_path=storage_path,
            db_name=db_name,
        )
        user_payload = _load_finance_cargo_tariffs_user_payload(storage_path=storage_path, db_name=db_name)
        records = list(user_payload.get("records") or [])
        deleted_keys = {_compact_text(key) for key in list(user_payload.get("deletedKeys") or []) if _compact_text(key)}
        merged_records = _load_finance_cargo_tariffs_raw(
            storage_path=storage_path,
            db_name=db_name,
            default_storage_path=default_storage_path,
        )
        normalized_pk = int(item_pk or 0)
        record_index = -1
        record: dict[str, Any] | None = None
        merged_record: dict[str, Any] | None = None
        if normalized_pk > 0:
            merged_record = next(
                (dict(row or {}) for row in merged_records if _row_matches_runtime_pk(row, normalized_pk)),
                None,
            )
        if merged_record is None and (requested_source_id is not None or requested_tariff_key):
            merged_record = next(
                (
                    dict(row or {})
                    for row in merged_records
                    if (
                        requested_source_id is not None
                        and _source_id_or_none((row or {}).get("sourceId") or (row or {}).get("source_id")) == requested_source_id
                    )
                    or (requested_tariff_key and _compact_text((row or {}).get("tariffKey")) == requested_tariff_key)
                ),
                None,
            )
        if normalized_pk > 0 and merged_record is None:
            return Result.fail("Düzenlenecek kargo tarifesi bulunamadı.", close_dialog=False)
        if merged_record is not None:
            existing_key = _compact_text(merged_record.get("tariffKey"))
            existing_db_pk = _db_pk_or_none(merged_record)
            for idx, row in enumerate(records):
                if (
                    (existing_db_pk is not None and int((row or {}).get("dbPk") or 0) == existing_db_pk)
                    or (
                        requested_source_id is not None
                        and _source_id_or_none((row or {}).get("sourceId") or (row or {}).get("source_id")) == requested_source_id
                    )
                    or _compact_text((row or {}).get("tariffKey")) == existing_key
                ):
                    record_index = idx
                    record = dict(row or {})
                    break
            if record is None:
                record = {
                    "tariffKey": existing_key,
                    "createdAt": _compact_text(merged_record.get("createdAt")) or now_iso,
                }
                if existing_db_pk is not None:
                    record["dbPk"] = existing_db_pk
        else:
            record = {"createdAt": now_iso}

        assert record is not None
        current_runtime_pk = normalized_pk or _runtime_record_pk(merged_record) or _runtime_record_pk(record)
        record["tariffKey"] = _ensure_unique_finance_cargo_tariff_key(
            [*builtin_records, *records],
            payload.get("tariffKey") or name,
            current_pk=current_runtime_pk,
        )
        record["name"] = name
        record["description"] = _compact_text(payload.get("description")) or None
        record["platform"] = platform
        record["platformCode"] = platform
        record["platformSourceId"] = platform_source_id
        record["platform_source_id"] = platform_source_id
        record["cargoProviderCode"] = provider_code or None
        record["cargoProviderSourceId"] = provider_source_id
        record["cargo_provider_source_id"] = provider_source_id
        record["cargoProviderName"] = provider_name
        record["minDesi"] = min_desi
        record["maxDesi"] = max_desi
        record["minSalePrice"] = min_sale_price
        record["maxSalePrice"] = max_sale_price
        record["amount"] = amount
        record["currency"] = currency
        record["isVatIncluded"] = is_vat_included
        record["vatRate"] = None if is_vat_included else vat_rate
        record["isActive"] = bool(payload.get("isActive", True))
        source_type = _compact_text(payload.get("sourceType") or payload.get("source_type")).lower()
        if source_type not in {SOURCE_TYPE_BUILTIN, SOURCE_TYPE_USER}:
            source_type = _compact_text((merged_record or {}).get("sourceType")).lower()
        if source_type not in {SOURCE_TYPE_BUILTIN, SOURCE_TYPE_USER}:
            source_type = SOURCE_TYPE_BUILTIN if bool(merged_record and merged_record.get("isBuiltin")) else SOURCE_TYPE_USER
        record["sourceType"] = source_type
        record["sourceId"] = (
            requested_source_id
            or _source_id_or_none((merged_record or {}).get("sourceId") or (merged_record or {}).get("source_id"))
            or _next_runtime_source_id([*builtin_records, *merged_records, *records])
        )
        record["source_id"] = record["sourceId"]
        if _db_pk_or_none(record) is not None:
            record["pk"] = int(record["dbPk"])
        else:
            record["pk"] = int(record["sourceId"] or 0)
        record["updatedAt"] = now_iso
        if not _compact_text(record.get("createdAt")):
            record["createdAt"] = now_iso

        if record_index >= 0:
            records[record_index] = record
        else:
            records.append(record)
        deleted_keys.discard(_compact_text(record.get("tariffKey")))
        _save_finance_cargo_tariffs_user_payload(
            records,
            deleted_keys=deleted_keys,
            storage_path=storage_path,
            db_name=db_name,
        )

        return Result.ok(
            "Kargo tarifesi kaydedildi.",
            close_dialog=False,
            data={"record": _cargo_tariff_to_dict({**record, "isBuiltin": bool(merged_record and merged_record.get("isBuiltin"))})},
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def delete_finance_cargo_tariff(
    item_pk: int,
    *,
    storage_path: str | Path | None = None,
    db_name: str | None = None,
    default_storage_path: str | Path | None = None,
) -> Result:
    try:
        normalized_pk = int(item_pk or 0)
        builtin_records = _load_finance_cargo_tariffs_default_raw(
            default_storage_path=default_storage_path,
            storage_path=storage_path,
            db_name=db_name,
        )
        merged_records = _load_finance_cargo_tariffs_raw(
            storage_path=storage_path,
            db_name=db_name,
            default_storage_path=default_storage_path,
        )
        target = next((row for row in merged_records if _row_matches_runtime_pk(row, normalized_pk)), None)
        if target is None:
            return Result.fail("Silinecek kargo tarifesi bulunamadı.", close_dialog=False)
        tariff_key = _compact_text((target or {}).get("tariffKey"))
        builtin_keys = {_compact_text(row.get("tariffKey")) for row in builtin_records if _compact_text(row.get("tariffKey"))}
        user_payload = _load_finance_cargo_tariffs_user_payload(storage_path=storage_path, db_name=db_name)
        records = list(user_payload.get("records") or [])
        deleted_keys = {_compact_text(key) for key in list(user_payload.get("deletedKeys") or []) if _compact_text(key)}
        remaining = [
            row for row in records
            if not _row_matches_runtime_pk(row, normalized_pk) and _compact_text((row or {}).get("tariffKey")) != tariff_key
        ]
        if storage_path in (None, "") or tariff_key in builtin_keys:
            deleted_keys.add(tariff_key)
        _save_finance_cargo_tariffs_user_payload(
            remaining,
            deleted_keys=deleted_keys,
            storage_path=storage_path,
            db_name=db_name,
        )
        return Result.ok("Kargo tarifesi silindi.", close_dialog=False)
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def delete_finance_cargo_tariffs(
    item_pks: list[int],
    *,
    storage_path: str | Path | None = None,
    db_name: str | None = None,
    default_storage_path: str | Path | None = None,
) -> Result:
    try:
        normalized = sorted({int(pk) for pk in (item_pks or []) if str(pk).strip()})
        if not normalized:
            return Result.fail("Silinecek kargo tarifesi seçilmedi.", close_dialog=False)

        key_set = set(normalized)
        builtin_records = _load_finance_cargo_tariffs_default_raw(
            default_storage_path=default_storage_path,
            storage_path=storage_path,
            db_name=db_name,
        )
        merged_records = _load_finance_cargo_tariffs_raw(
            storage_path=storage_path,
            db_name=db_name,
            default_storage_path=default_storage_path,
        )
        target_rows = [row for row in merged_records if _runtime_record_pk(row) in key_set]
        deleted_count = len(target_rows)
        if deleted_count <= 0:
            return Result.fail("Seçili kargo tarifeleri bulunamadı.", close_dialog=False)
        target_keys = {_compact_text(row.get("tariffKey")) for row in target_rows if _compact_text(row.get("tariffKey"))}
        builtin_keys = {_compact_text(row.get("tariffKey")) for row in builtin_records if _compact_text(row.get("tariffKey"))}
        user_payload = _load_finance_cargo_tariffs_user_payload(storage_path=storage_path, db_name=db_name)
        records = list(user_payload.get("records") or [])
        deleted_keys = {_compact_text(key) for key in list(user_payload.get("deletedKeys") or []) if _compact_text(key)}
        remaining = [
            row for row in records
            if _runtime_record_pk(row) not in key_set and _compact_text((row or {}).get("tariffKey")) not in target_keys
        ]
        if storage_path in (None, ""):
            deleted_keys.update(target_keys)
        else:
            deleted_keys.update({key for key in target_keys if key in builtin_keys})
        _save_finance_cargo_tariffs_user_payload(
            remaining,
            deleted_keys=deleted_keys,
            storage_path=storage_path,
            db_name=db_name,
        )
        return Result.ok(
            "Seçili kargo tarifeleri silindi.",
            close_dialog=False,
            data={"deleted_count": deleted_count},
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)

