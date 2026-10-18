
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from Account.models.models import ApiAccount
from Core.db import model_registry  # noqa: F401
from Core.utils.model_utils import (
    create_records,
    delete_records,
    get_engine,
    get_records,
    make_normalizer,
    update_records,
)
from Feedback.processors.pipeline import Result, map_error_to_message
from settings import DB_NAME


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

from Finance.api.trendyol.finance_api import TrendyolFinanceApi
from Marketplaces.api.trendyol.base_api import trendyol_account_client_kwargs
from Finance.constants.trendyol.constants import (
    FINANCE_SERVICE_CARGO_INVOICE_ITEMS,
    FINANCE_SERVICE_OTHER_FINANCIALS,
    FINANCE_SERVICE_SETTLEMENTS,
    TRENDYOL_FINANCE_CARGO_INVOICE_KEYWORDS,
    TRENDYOL_FINANCE_DEFAULT_MAX_PAGES,
    TRENDYOL_FINANCE_DEFAULT_PAGE_SIZE,
    TRENDYOL_FINANCE_MAX_PAGE_SIZE,
    TRENDYOL_FINANCE_OTHER_TRANSACTION_TYPES,
    TRENDYOL_FINANCE_SAFE_RANGE_DAYS,
    TRENDYOL_FINANCE_SETTLEMENT_TRANSACTION_TYPES,
    TZ_GMT3,
)
from Finance.constants.domain_constants import (
    FINANCE_CARGO_ITEM_UNIQUE_FIELDS,
    FINANCE_FETCH_ACCOUNT_CONCURRENCY,
    FINANCE_SYNC_CARGO_CONCURRENCY,
    FINANCE_SYNC_STAGE_CONCURRENCY,
    FINANCE_TRANSACTION_UNIQUE_FIELDS,
)
from Finance.models.trendyol.models import Brand, Company, FinanceCargoInvoiceItem, FinanceTransaction

_text_normalizer = make_normalizer(strip_strings=True)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _as_optional_int(value: Any, default: int | None = None) -> int | None:
    if value in (None, ""):
        return default
    try:
        return int(float(value))
    except Exception:
        return default


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except Exception:
            return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace(" ", "")
    if "," in normalized and "." in normalized:
        if normalized.rfind(",") > normalized.rfind("."):
            normalized = normalized.replace(".", "").replace(",", ".")
        else:
            normalized = normalized.replace(",", "")
    else:
        normalized = normalized.replace(",", ".")
    try:
        return float(normalized)
    except Exception:
        return None


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_epoch_ms(value: Any) -> int:
    if value in (None, ""):
        return 0
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ_GMT3)
        return int(dt.timestamp() * 1000)
    if isinstance(value, (int, float)):
        num = int(value)
        if num > 10**11:
            return num
        if num > 10**9:
            return num * 1000
        return 0
    text = _compact_text(value)
    if not text:
        return 0
    if text.isdigit():
        return _normalize_epoch_ms(int(text))
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ_GMT3)
        return int(dt.timestamp() * 1000)
    except Exception:
        return 0


def split_finance_date_range(start_ms: int, end_ms: int) -> list[tuple[int, int]]:
    start_val = _as_int(start_ms, 0)
    end_val = _as_int(end_ms, 0)
    if start_val <= 0 or end_val <= 0:
        return []
    if end_val < start_val:
        start_val, end_val = end_val, start_val

    window_ms = int(timedelta(days=TRENDYOL_FINANCE_SAFE_RANGE_DAYS).total_seconds() * 1000) - 1
    cursor = start_val
    chunks: list[tuple[int, int]] = []
    while cursor <= end_val:
        chunk_end = min(end_val, cursor + window_ms)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + 1
    return chunks


def _sanitize_page_size(size: int) -> int:
    value = _as_int(size, TRENDYOL_FINANCE_DEFAULT_PAGE_SIZE)
    if value <= 0:
        value = TRENDYOL_FINANCE_DEFAULT_PAGE_SIZE
    return min(value, TRENDYOL_FINANCE_MAX_PAGE_SIZE)


def _sanitize_max_pages(max_pages: int | None) -> int:
    if max_pages is None:
        return max(1, TRENDYOL_FINANCE_DEFAULT_MAX_PAGES)
    value = _as_int(max_pages, TRENDYOL_FINANCE_DEFAULT_MAX_PAGES)
    if value <= 0:
        value = TRENDYOL_FINANCE_DEFAULT_MAX_PAGES
    return max(1, value)


def _extract_content(payload: Any) -> list:
    if isinstance(payload, dict):
        for key in ("content", "items", "data", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    if isinstance(payload, list):
        return payload
    return []


def _account_info(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        extra_config = (
            dict(raw.get("extra_config") or {})
            if isinstance(raw.get("extra_config"), dict)
            else {}
        )
        for key in (
            "environment",
            "api_environment",
            "credential_reference",
            "credential_ref",
        ):
            if raw.get(key) not in (None, "") and key not in extra_config:
                extra_config[key] = raw.get(key)
        return {
            "pk": raw.get("pk"),
            "api_key": _compact_text(raw.get("api_key")),
            "api_secret": _compact_text(raw.get("api_secret")),
            "seller_id": _compact_text(raw.get("seller_id")),
            "comp_name": _compact_text(raw.get("comp_name")),
            "extra_config": extra_config,
        }
    if isinstance(raw, (list, tuple)):
        extra_config = (
            dict(raw[5] or {})
            if len(raw) > 5 and isinstance(raw[5], dict)
            else {}
        )
        legacy_company_name = (
            _compact_text(raw[4])
            if len(raw) == 5 and isinstance(raw[4], str)
            else ""
        )
        return {
            "pk": raw[0] if len(raw) > 0 else None,
            "api_key": _compact_text(raw[1] if len(raw) > 1 else ""),
            "api_secret": _compact_text(raw[2] if len(raw) > 2 else ""),
            "seller_id": _compact_text(raw[3] if len(raw) > 3 else ""),
            "comp_name": legacy_company_name,
            "extra_config": extra_config,
        }
    return {
        "pk": None,
        "api_key": "",
        "api_secret": "",
        "seller_id": "",
        "comp_name": "",
        "extra_config": {},
    }


def _extract_total_pages(payload: dict[str, Any]) -> int | None:
    for key in ("totalPages", "pageCount", "pages"):
        value = payload.get(key)
        if value is None:
            continue
        parsed = _as_int(value, -1)
        if parsed >= 0:
            return parsed
    return None


def _annotate_record(
    record: Any,
    *,
    account: dict[str, Any],
    service_key: str,
    invoice_serial_number: str = "",
) -> dict[str, Any]:
    row = dict(record) if isinstance(record, dict) else {"value": record}
    row["_finance_service"] = service_key
    row["_api_account_id"] = account.get("pk")
    row["_seller_id"] = account.get("seller_id")
    row["_company_name"] = account.get("comp_name")
    environment = _compact_text(
        dict(account.get("extra_config") or {}).get("environment")
        or dict(account.get("extra_config") or {}).get("api_environment")
        or "production"
    ).casefold()
    row["_environment"] = environment
    if invoice_serial_number:
        row["_invoice_serial_number"] = invoice_serial_number
    return row


async def _fetch_finance_records(
    *,
    service_key: str,
    comp_api_account_list: list,
    transaction_date_start: int | None = None,
    transaction_date_end: int | None = None,
    transaction_type: str | None = None,
    invoice_serial_number: str | None = None,
    page_size: int = TRENDYOL_FINANCE_DEFAULT_PAGE_SIZE,
    max_pages: int | None = TRENDYOL_FINANCE_DEFAULT_MAX_PAGES,
    progress_callback: Callable[[int, int], None] | None = None,
) -> Result:
    try:
        accounts_raw = list(comp_api_account_list or [])
        if not accounts_raw:
            return Result.fail("Finans sorgusu için seçili şirket bulunamadı.", close_dialog=False)

        if service_key in (FINANCE_SERVICE_SETTLEMENTS, FINANCE_SERVICE_OTHER_FINANCIALS):
            if transaction_date_start in (None, "") or transaction_date_end in (None, ""):
                return Result.fail("Finans tarih aralığı zorunludur.", close_dialog=False)

        invoice_serial = _compact_text(invoice_serial_number)
        if service_key == FINANCE_SERVICE_CARGO_INVOICE_ITEMS and not invoice_serial:
            return Result.fail("Kargo fatura seri numarası zorunludur.", close_dialog=False)

        size = _sanitize_page_size(page_size)
        page_limit = _sanitize_max_pages(max_pages)
        expected_steps = max(1, len(accounts_raw) * page_limit)
        current_step = 0
        progress_lock = asyncio.Lock()
        semaphore = asyncio.Semaphore(max(1, min(FINANCE_FETCH_ACCOUNT_CONCURRENCY, len(accounts_raw))))

        all_records: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        account_summaries: list[dict[str, Any]] = []
        
        async def _advance_progress(step_count: int = 1) -> None:
            nonlocal current_step
            async with progress_lock:
                current_step = min(expected_steps, current_step + max(1, int(step_count or 1)))
                if progress_callback:
                    progress_callback(current_step, expected_steps)

        async def _fetch_account(raw_account: Any) -> tuple[list[dict[str, Any]], list[dict[str, str]], dict[str, Any]]:
            account = _account_info(raw_account)
            try:
                client_kwargs = trendyol_account_client_kwargs(account)
                seller_id = _compact_text(client_kwargs.get("supplier_id"))
                environment = _compact_text(client_kwargs.get("environment")) or "production"
                api = TrendyolFinanceApi(**client_kwargs)
            except Exception:
                seller_id = _compact_text(account.get("seller_id"))
                environment = _compact_text(
                    dict(account.get("extra_config") or {}).get("environment")
                    or dict(account.get("extra_config") or {}).get("api_environment")
                    or "production"
                ).casefold()
                await _advance_progress(page_limit)
                return (
                    [],
                    [
                        {
                            "seller_id": seller_id or "-",
                            "company": _compact_text(account.get("comp_name")) or "-",
                            "message": "API bilgileri eksik.",
                        }
                    ],
                    {
                        "seller_id": seller_id,
                        "company": _compact_text(account.get("comp_name")),
                        "environment": environment,
                        "records": 0,
                        "pages_fetched": 0,
                        "failed": True,
                        "error": "API bilgileri eksik.",
                    },
                )
            page = 0
            pages_fetched = 0
            account_records = 0
            account_failed = False
            account_error_msg = ""
            fetched_records: list[dict[str, Any]] = []
            account_errors: list[dict[str, str]] = []

            async with semaphore:
                while pages_fetched < page_limit:
                    if service_key == FINANCE_SERVICE_SETTLEMENTS:
                        one = await api.get_settlements(
                            transaction_date_start=_as_int(transaction_date_start),
                            transaction_date_end=_as_int(transaction_date_end),
                            page=page,
                            size=size,
                            transaction_type=transaction_type,
                        )
                    elif service_key == FINANCE_SERVICE_OTHER_FINANCIALS:
                        one = await api.get_other_financials(
                            transaction_date_start=_as_int(transaction_date_start),
                            transaction_date_end=_as_int(transaction_date_end),
                            page=page,
                            size=size,
                            transaction_type=transaction_type,
                        )
                    elif service_key == FINANCE_SERVICE_CARGO_INVOICE_ITEMS:
                        one = await api.get_cargo_invoice_items(
                            invoice_serial_number=invoice_serial,
                            page=page,
                            size=size,
                        )
                    else:
                        return [], [], {
                            "seller_id": seller_id,
                            "company": _compact_text(account.get("comp_name")),
                            "environment": environment,
                            "records": 0,
                            "pages_fetched": 0,
                            "failed": True,
                            "error": "Desteklenmeyen finans servis tipi.",
                        }

                    await _advance_progress(1)

                    if not one.success:
                        account_failed = True
                        account_error_msg = _compact_text(one.message) or "Bilinmeyen API hatasi"
                        account_errors.append(
                            {
                                "seller_id": seller_id,
                                "company": _compact_text(account.get("comp_name")) or "-",
                                "message": account_error_msg,
                            }
                        )
                        break

                    payload = one.data or {}
                    content = _extract_content(payload)
                    for row in content:
                        fetched_records.append(
                            _annotate_record(
                                row,
                                account=account,
                                service_key=service_key,
                                invoice_serial_number=invoice_serial,
                            )
                        )
                    account_records += len(content)
                    pages_fetched += 1

                    total_pages = _extract_total_pages(payload if isinstance(payload, dict) else {})
                    if not content:
                        break
                    if total_pages is not None and page >= (total_pages - 1):
                        break
                    if len(content) < size:
                        break
                    page += 1

            summary = (
                {
                    "seller_id": seller_id,
                    "company": _compact_text(account.get("comp_name")),
                    "environment": environment,
                    "records": account_records,
                    "pages_fetched": pages_fetched,
                    "failed": bool(account_failed),
                    "error": account_error_msg,
                }
            )
            return fetched_records, account_errors, summary

        results = await asyncio.gather(*(_fetch_account(raw_account) for raw_account in accounts_raw))
        for fetched_records, account_errors, summary in results:
            all_records.extend(fetched_records)
            errors.extend(account_errors)
            account_summaries.append(summary)

        if progress_callback:
            progress_callback(expected_steps, expected_steps)

        if not all_records and errors:
            return Result.fail(
                "Finans verileri alinamadi.",
                close_dialog=False,
                data={
                    "service_key": service_key,
                    "records": [],
                    "errors": errors,
                    "account_summaries": account_summaries,
                },
            )

        return Result.ok(
            f"Finans verileri alindi. Kayit sayisi: {len(all_records)}",
            close_dialog=False,
            data={
                "service_key": service_key,
                "records": all_records,
                "errors": errors,
                "account_summaries": account_summaries,
            },
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


async def fetch_settlements_for_accounts(
    comp_api_account_list: list,
    *,
    transaction_date_start: int,
    transaction_date_end: int,
    transaction_type: str | None = None,
    page_size: int = TRENDYOL_FINANCE_DEFAULT_PAGE_SIZE,
    max_pages: int | None = TRENDYOL_FINANCE_DEFAULT_MAX_PAGES,
    progress_callback: Callable[[int, int], None] | None = None,
) -> Result:
    return await _fetch_finance_records(
        service_key=FINANCE_SERVICE_SETTLEMENTS,
        comp_api_account_list=comp_api_account_list,
        transaction_date_start=transaction_date_start,
        transaction_date_end=transaction_date_end,
        transaction_type=transaction_type,
        page_size=page_size,
        max_pages=max_pages,
        progress_callback=progress_callback,
    )


async def fetch_other_financials_for_accounts(
    comp_api_account_list: list,
    *,
    transaction_date_start: int,
    transaction_date_end: int,
    transaction_type: str | None = None,
    page_size: int = TRENDYOL_FINANCE_DEFAULT_PAGE_SIZE,
    max_pages: int | None = TRENDYOL_FINANCE_DEFAULT_MAX_PAGES,
    progress_callback: Callable[[int, int], None] | None = None,
) -> Result:
    return await _fetch_finance_records(
        service_key=FINANCE_SERVICE_OTHER_FINANCIALS,
        comp_api_account_list=comp_api_account_list,
        transaction_date_start=transaction_date_start,
        transaction_date_end=transaction_date_end,
        transaction_type=transaction_type,
        page_size=page_size,
        max_pages=max_pages,
        progress_callback=progress_callback,
    )


async def fetch_cargo_invoice_items_for_accounts(
    comp_api_account_list: list,
    *,
    invoice_serial_number: str,
    page_size: int = TRENDYOL_FINANCE_DEFAULT_PAGE_SIZE,
    max_pages: int | None = TRENDYOL_FINANCE_DEFAULT_MAX_PAGES,
    progress_callback: Callable[[int, int], None] | None = None,
) -> Result:
    return await _fetch_finance_records(
        service_key=FINANCE_SERVICE_CARGO_INVOICE_ITEMS,
        comp_api_account_list=comp_api_account_list,
        invoice_serial_number=invoice_serial_number,
        page_size=page_size,
        max_pages=max_pages,
        progress_callback=progress_callback,
    )


def _derive_transaction_record_id(record: dict[str, Any], service_key: str) -> str:
    candidates = (
        record.get("id"),
        record.get("transactionId"),
        record.get("paymentOrderId"),
        record.get("receiptId"),
        record.get("commissionInvoiceSerialNumber"),
        record.get("shipmentPackageId"),
        record.get("orderNumber"),
    )
    for value in candidates:
        text = _compact_text(value)
        if text:
            return text
    tx_date = _normalize_epoch_ms(record.get("transactionDate") or record.get("paymentDate") or record.get("orderDate"))
    desc = _compact_text(record.get("description"))[:80]
    return f"{service_key}:{tx_date}:{desc or 'record'}"


def normalize_finance_transaction_record(record: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        return None

    service_key = _compact_text(record.get("serviceKey") or record.get("_finance_service") or FINANCE_SERVICE_SETTLEMENTS)
    api_account_id = _as_optional_int(record.get("api_account_id") if "api_account_id" in record else record.get("_api_account_id"))
    seller_id = _as_optional_int(record.get("sellerId") if "sellerId" in record else record.get("_seller_id"))

    credit = _as_float(record.get("credit"))
    debt = _as_float(record.get("debt"))
    net_amount = _as_float(record.get("netAmount"))
    if net_amount is None:
        if credit is not None or debt is not None:
            net_amount = float(credit or 0.0) - float(debt or 0.0)
        else:
            net_amount = _as_float(record.get("sellerRevenue"))
    if net_amount is None:
        net_amount = 0.0

    return {
        "api_account_id": api_account_id,
        "serviceKey": service_key,
        "sellerId": seller_id,
        "recordId": _derive_transaction_record_id(record, service_key),
        "transactionType": _compact_text(record.get("transactionType")) or None,
        "description": _compact_text(record.get("description")) or None,
        "transactionDate": _normalize_epoch_ms(record.get("transactionDate")),
        "orderDate": _normalize_epoch_ms(record.get("orderDate")) or None,
        "paymentDate": _normalize_epoch_ms(record.get("paymentDate")) or None,
        "orderNumber": _compact_text(record.get("orderNumber")) or None,
        "shipmentPackageId": _as_optional_int(record.get("shipmentPackageId")),
        "barcode": _compact_text(record.get("barcode")) or None,
        "receiptId": _as_optional_int(record.get("receiptId")),
        "paymentOrderId": _compact_text(record.get("paymentOrderId")) or None,
        "paymentPeriod": _as_optional_int(record.get("paymentPeriod")),
        "currency": _compact_text(record.get("currency")) or None,
        "country": _compact_text(record.get("country")) or None,
        "affiliate": _compact_text(record.get("affiliate")) or None,
        "debt": float(debt) if debt is not None else None,
        "credit": float(credit) if credit is not None else None,
        "netAmount": float(net_amount),
        "sellerRevenue": _as_float(record.get("sellerRevenue")),
        "commissionRate": _as_float(record.get("commissionRate")),
        "commissionAmount": _as_float(record.get("commissionAmount")),
        "commissionInvoiceSerialNumber": _compact_text(record.get("commissionInvoiceSerialNumber")) or None,
        "storeId": _as_optional_int(record.get("storeId")),
        "storeName": _compact_text(record.get("storeName")) or None,
        "storeAddress": _compact_text(record.get("storeAddress")) or None,
    }


def normalize_finance_cargo_invoice_item(record: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        return None
    invoice_serial_number = _compact_text(record.get("invoiceSerialNumber") or record.get("_invoice_serial_number"))
    if not invoice_serial_number:
        return None
    return {
        "api_account_id": _as_optional_int(record.get("api_account_id") if "api_account_id" in record else record.get("_api_account_id")),
        "sellerId": _as_optional_int(record.get("sellerId") if "sellerId" in record else record.get("_seller_id")),
        "invoiceSerialNumber": invoice_serial_number,
        "parcelUniqueId": _as_optional_int(record.get("parcelUniqueId"), default=0),
        "orderNumber": _compact_text(record.get("orderNumber")) or None,
        "shipmentPackageType": _compact_text(record.get("shipmentPackageType")) or "Unknown",
        "amount": _as_float(record.get("amount")),
        "desi": _as_float(record.get("desi")),
    }

def _dedupe_rows(rows: list[dict[str, Any]], key_builder: Callable[[dict[str, Any]], tuple[Any, ...]]) -> list[dict[str, Any]]:
    latest: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows or []:
        latest[key_builder(row)] = row
    return list(latest.values())


def save_finance_transactions_to_db(records: list[dict[str, Any]], db_name: str = DB_NAME) -> Result:
    try:
        normalized = [row for row in (normalize_finance_transaction_record(rec) for rec in (records or [])) if row]
        normalized = _dedupe_rows(
            normalized,
            lambda row: (
                row.get("serviceKey"),
                row.get("api_account_id"),
                row.get("recordId"),
                row.get("transactionDate"),
            ),
        )
        if not normalized:
            return Result.ok(
                "Kaydedilecek finans hareketi yok.",
                close_dialog=False,
                data={"changed": False, "counts": {"transactions": 0}},
            )
        res = create_records(
            model=FinanceTransaction,
            data_list=normalized,
            db_name=db_name,
            conflict_keys=FINANCE_TRANSACTION_UNIQUE_FIELDS,
            mode="update",
            chunk_size=500,
            drop_unknown=True,
        )
        if not res.success:
            return res
        affected = int((res.data or {}).get("affected", 0) or 0)
        return Result.ok(
            "Finans hareketleri veritabanina kaydedildi.",
            close_dialog=False,
            data={"changed": affected > 0, "counts": {"transactions": affected}},
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def save_finance_cargo_items_to_db(records: list[dict[str, Any]], db_name: str = DB_NAME) -> Result:
    try:
        normalized = [row for row in (normalize_finance_cargo_invoice_item(rec) for rec in (records or [])) if row]
        normalized = _dedupe_rows(
            normalized,
            lambda row: (
                row.get("api_account_id"),
                row.get("invoiceSerialNumber"),
                row.get("parcelUniqueId"),
                row.get("shipmentPackageType"),
            ),
        )
        if not normalized:
            return Result.ok(
                "Kaydedilecek kargo fatura kalemi yok.",
                close_dialog=False,
                data={"changed": False, "counts": {"cargo_items": 0}},
            )
        res = create_records(
            model=FinanceCargoInvoiceItem,
            data_list=normalized,
            db_name=db_name,
            conflict_keys=FINANCE_CARGO_ITEM_UNIQUE_FIELDS,
            mode="update",
            chunk_size=500,
            drop_unknown=True,
        )
        if not res.success:
            return res
        affected = int((res.data or {}).get("affected", 0) or 0)
        return Result.ok(
            "Kargo fatura kalemleri veritabanina kaydedildi.",
            close_dialog=False,
            data={"changed": affected > 0, "counts": {"cargo_items": affected}},
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def _is_cargo_invoice_transaction(record: dict[str, Any]) -> bool:
    haystack = " ".join(
        [
            _compact_text(record.get("transactionType")),
            _compact_text(record.get("description")),
        ]
    ).casefold()
    return bool(haystack) and any(keyword in haystack for keyword in TRENDYOL_FINANCE_CARGO_INVOICE_KEYWORDS)


def extract_cargo_invoice_targets(transaction_records: list[dict[str, Any]], comp_api_account_list: list) -> list[dict[str, Any]]:
    accounts_by_pk: dict[int, dict[str, Any]] = {}
    for raw in comp_api_account_list or []:
        account = _account_info(raw)
        pk = _as_optional_int(account.get("pk"))
        if pk is not None:
            accounts_by_pk[pk] = account

    seen: set[tuple[int, str]] = set()
    targets: list[dict[str, Any]] = []
    for record in transaction_records or []:
        if not _is_cargo_invoice_transaction(record):
            continue
        serial = _compact_text(record.get("commissionInvoiceSerialNumber") or record.get("invoiceSerialNumber"))
        account_pk = _as_optional_int(record.get("_api_account_id") if "_api_account_id" in record else record.get("api_account_id"))
        if not serial or account_pk is None:
            continue
        account = accounts_by_pk.get(account_pk)
        if not account:
            continue
        key = (account_pk, serial)
        if key in seen:
            continue
        seen.add(key)
        targets.append({"account": account, "invoice_serial_number": serial})
    return targets


def _merge_result_payload(
    destination: list[dict[str, Any]],
    result: Result,
    *,
    service_key: str,
    errors: list[dict[str, Any]],
    account_summaries: list[dict[str, Any]],
    transaction_type: str | None = None,
    extra_context: dict[str, Any] | None = None,
) -> None:
    if result.success:
        data = result.data or {}
        destination.extend(list(data.get("records", []) or []))
        account_summaries.extend(list(data.get("account_summaries", []) or []))
        for item in list(data.get("errors", []) or []):
            row = dict(item) if isinstance(item, dict) else {"message": str(item)}
            row.setdefault("service_key", service_key)
            if transaction_type:
                row.setdefault("transaction_type", transaction_type)
            if extra_context:
                row.update(extra_context)
            errors.append(row)
        return

    failure = {
        "service_key": service_key,
        "transaction_type": transaction_type or "",
        "message": _compact_text(result.message) or "Bilinmeyen finance hatasi",
    }
    if extra_context:
        failure.update(extra_context)
    errors.append(failure)
    data = result.data or {}
    account_summaries.extend(list(data.get("account_summaries", []) or []))


async def sync_finance_for_accounts(
    comp_api_account_list: list,
    *,
    transaction_date_start: int,
    transaction_date_end: int,
    page_size: int = TRENDYOL_FINANCE_DEFAULT_PAGE_SIZE,
    max_pages: int | None = TRENDYOL_FINANCE_DEFAULT_MAX_PAGES,
    progress_callback: Callable[[int, int], None] | None = None,
) -> Result:
    try:
        accounts = list(comp_api_account_list or [])
        if not accounts:
            return Result.fail("Finans senkronizasyonu için seçili şirket yok.", close_dialog=False)

        windows = split_finance_date_range(transaction_date_start, transaction_date_end)
        if not windows:
            return Result.fail("Gecersiz finans tarih araligi.", close_dialog=False)

        safe_page_size = _sanitize_page_size(page_size)
        safe_max_pages = _sanitize_max_pages(max_pages)

        all_transaction_records: list[dict[str, Any]] = []
        all_cargo_items: list[dict[str, Any]] = []
        transaction_keys: set[tuple[Any, ...]] = set()
        cargo_item_keys: set[tuple[Any, ...]] = set()
        cargo_invoice_serials: set[str] = set()
        errors: list[dict[str, Any]] = []
        account_summaries: list[dict[str, Any]] = []

        settlement_jobs = [
            (start_ms, end_ms, tx_type)
            for start_ms, end_ms in windows
            for tx_type in TRENDYOL_FINANCE_SETTLEMENT_TRANSACTION_TYPES
        ]
        other_jobs = [
            (start_ms, end_ms, tx_type)
            for start_ms, end_ms in windows
            for tx_type in TRENDYOL_FINANCE_OTHER_TRANSACTION_TYPES
        ]
        total_stage_jobs = max(1, len(settlement_jobs) + len(other_jobs))
        completed_jobs = 0

        def _emit(percent: int) -> None:
            if progress_callback:
                progress_callback(max(0, min(100, int(percent))), 100)

        stage_semaphore = asyncio.Semaphore(max(1, min(FINANCE_SYNC_STAGE_CONCURRENCY, total_stage_jobs)))
        cargo_semaphore = asyncio.Semaphore(max(1, FINANCE_SYNC_CARGO_CONCURRENCY))

        _emit(1)

        async def _fetch_stage_job(job_kind: str, start_ms: int, end_ms: int, tx_type: str) -> tuple[str, str, Result]:
            async with stage_semaphore:
                if job_kind == FINANCE_SERVICE_SETTLEMENTS:
                    one = await fetch_settlements_for_accounts(
                        accounts,
                        transaction_date_start=start_ms,
                        transaction_date_end=end_ms,
                        transaction_type=tx_type,
                        page_size=safe_page_size,
                        max_pages=safe_max_pages,
                    )
                else:
                    one = await fetch_other_financials_for_accounts(
                        accounts,
                        transaction_date_start=start_ms,
                        transaction_date_end=end_ms,
                        transaction_type=tx_type,
                        page_size=safe_page_size,
                        max_pages=safe_max_pages,
                    )
                return job_kind, tx_type, one

        stage_tasks = [
            asyncio.create_task(_fetch_stage_job(FINANCE_SERVICE_SETTLEMENTS, start_ms, end_ms, tx_type))
            for start_ms, end_ms, tx_type in settlement_jobs
        ] + [
            asyncio.create_task(_fetch_stage_job(FINANCE_SERVICE_OTHER_FINANCIALS, start_ms, end_ms, tx_type))
            for start_ms, end_ms, tx_type in other_jobs
        ]

        for future in asyncio.as_completed(stage_tasks):
            service_key, tx_type, one = await future
            _merge_result_payload(
                all_transaction_records,
                one,
                service_key=service_key,
                transaction_type=tx_type,
                errors=errors,
                account_summaries=account_summaries,
            )
            if one.success:
                for rec in list(((one.data or {}).get("records", []) or [])):
                    transaction_keys.add(
                        (
                            _compact_text(rec.get("_finance_service") or service_key),
                            _as_optional_int(rec.get("_api_account_id")),
                            _derive_transaction_record_id(rec, service_key),
                            _normalize_epoch_ms(rec.get("transactionDate")),
                        )
                    )
                    serial = _compact_text(rec.get("commissionInvoiceSerialNumber") or rec.get("invoiceSerialNumber"))
                    if serial:
                        cargo_invoice_serials.add(serial)
            completed_jobs += 1
            _emit(5 + int((completed_jobs / total_stage_jobs) * 55))

        cargo_targets = extract_cargo_invoice_targets(all_transaction_records, accounts)
        async def _fetch_cargo_target(target: dict[str, Any]) -> tuple[dict[str, Any], Result]:
            async with cargo_semaphore:
                one = await fetch_cargo_invoice_items_for_accounts(
                    [target["account"]],
                    invoice_serial_number=target["invoice_serial_number"],
                    page_size=safe_page_size,
                    max_pages=safe_max_pages,
                )
                return target, one

        cargo_tasks = [asyncio.create_task(_fetch_cargo_target(target)) for target in cargo_targets]
        for idx, future in enumerate(asyncio.as_completed(cargo_tasks), start=1):
            target, one = await future
            _merge_result_payload(
                all_cargo_items,
                one,
                service_key=FINANCE_SERVICE_CARGO_INVOICE_ITEMS,
                errors=errors,
                account_summaries=account_summaries,
                extra_context={"invoice_serial_number": target["invoice_serial_number"]},
            )
            if one.success:
                for rec in list(((one.data or {}).get("records", []) or [])):
                    cargo_item_keys.add(
                        (
                            _as_optional_int(rec.get("_api_account_id")),
                            _compact_text(rec.get("invoiceSerialNumber") or rec.get("_invoice_serial_number")),
                            _as_optional_int(rec.get("parcelUniqueId"), default=0),
                            _compact_text(rec.get("shipmentPackageType")) or "Unknown",
                        )
                    )
                    serial = _compact_text(rec.get("invoiceSerialNumber") or rec.get("_invoice_serial_number"))
                    if serial:
                        cargo_invoice_serials.add(serial)
            _emit(60 + int((idx / max(1, len(cargo_targets))) * 25))

        _emit(88)
        tx_save = save_finance_transactions_to_db(all_transaction_records)
        if not tx_save.success:
            return tx_save
        cargo_save = save_finance_cargo_items_to_db(all_cargo_items)
        if not cargo_save.success:
            return cargo_save
        tx_count = len(transaction_keys)
        cargo_count = len(cargo_item_keys)
        _emit(100)

        if tx_count <= 0 and cargo_count <= 0 and errors:
            return Result.fail(
                "Finans verileri alinamadi.",
                close_dialog=False,
                data={
                    "errors": errors,
                    "account_summaries": account_summaries,
                    "db_counts": {"transactions": 0, "cargo_items": 0},
                    "counts": {"transactions": 0, "cargo_items": 0, "cargo_invoices": 0},
                },
            )

        return Result.ok(
            "Finans verileri alindi ve veritabanina kaydedildi.",
            close_dialog=False,
            data={
                "errors": errors,
                "account_summaries": account_summaries,
                "counts": {
                    "transactions": tx_count,
                    "cargo_items": cargo_count,
                    "cargo_invoices": len(cargo_invoice_serials),
                },
                "db_counts": {
                    "transactions": int(((tx_save.data or {}).get("counts") or {}).get("transactions", 0) or 0),
                    "cargo_items": int(((cargo_save.data or {}).get("counts") or {}).get("cargo_items", 0) or 0),
                },
            },
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def _transaction_to_dict(row: FinanceTransaction) -> dict[str, Any]:
    company_name = _compact_text(getattr(getattr(row, "api_account", None), "comp_name", ""))
    seller_account_id = _compact_text(getattr(getattr(row, "api_account", None), "account_id", ""))
    return {
        "pk": getattr(row, "pk", None),
        "api_account_id": getattr(row, "api_account_id", None),
        "companyName": company_name,
        "sellerAccountId": seller_account_id,
        "serviceKey": _compact_text(getattr(row, "serviceKey", "")),
        "sellerId": getattr(row, "sellerId", None),
        "recordId": _compact_text(getattr(row, "recordId", "")),
        "transactionType": _compact_text(getattr(row, "transactionType", "")),
        "description": _compact_text(getattr(row, "description", "")),
        "transactionDate": getattr(row, "transactionDate", None),
        "orderDate": getattr(row, "orderDate", None),
        "paymentDate": getattr(row, "paymentDate", None),
        "orderNumber": _compact_text(getattr(row, "orderNumber", "")),
        "shipmentPackageId": getattr(row, "shipmentPackageId", None),
        "barcode": _compact_text(getattr(row, "barcode", "")),
        "receiptId": getattr(row, "receiptId", None),
        "paymentOrderId": _compact_text(getattr(row, "paymentOrderId", "")),
        "paymentPeriod": getattr(row, "paymentPeriod", None),
        "currency": _compact_text(getattr(row, "currency", "")),
        "country": _compact_text(getattr(row, "country", "")),
        "affiliate": _compact_text(getattr(row, "affiliate", "")),
        "debt": getattr(row, "debt", None),
        "credit": getattr(row, "credit", None),
        "netAmount": getattr(row, "netAmount", None),
        "sellerRevenue": getattr(row, "sellerRevenue", None),
        "commissionRate": getattr(row, "commissionRate", None),
        "commissionAmount": getattr(row, "commissionAmount", None),
        "commissionInvoiceSerialNumber": _compact_text(getattr(row, "commissionInvoiceSerialNumber", "")),
        "storeId": getattr(row, "storeId", None),
        "storeName": _compact_text(getattr(row, "storeName", "")),
        "storeAddress": _compact_text(getattr(row, "storeAddress", "")),
    }


def _cargo_item_to_dict(row: FinanceCargoInvoiceItem) -> dict[str, Any]:
    company_name = _compact_text(getattr(getattr(row, "api_account", None), "comp_name", ""))
    seller_account_id = _compact_text(getattr(getattr(row, "api_account", None), "account_id", ""))
    return {
        "pk": getattr(row, "pk", None),
        "api_account_id": getattr(row, "api_account_id", None),
        "companyName": company_name,
        "sellerAccountId": seller_account_id,
        "sellerId": getattr(row, "sellerId", None),
        "invoiceSerialNumber": _compact_text(getattr(row, "invoiceSerialNumber", "")),
        "parcelUniqueId": getattr(row, "parcelUniqueId", None),
        "orderNumber": _compact_text(getattr(row, "orderNumber", "")),
        "shipmentPackageType": _compact_text(getattr(row, "shipmentPackageType", "")),
        "amount": getattr(row, "amount", None),
        "desi": getattr(row, "desi", None),
    }


def _matches_search(record: dict[str, Any], search_text: str) -> bool:
    query = _compact_text(search_text).casefold()
    if not query:
        return True
    haystack = " ".join(
        _compact_text(record.get(key))
        for key in (
            "companyName",
            "sellerAccountId",
            "transactionType",
            "description",
            "orderNumber",
            "shipmentPackageId",
            "barcode",
            "paymentOrderId",
            "commissionInvoiceSerialNumber",
            "invoiceSerialNumber",
            "shipmentPackageType",
            "storeName",
            "storeAddress",
        )
    ).casefold()
    return query in haystack

def get_finance_transactions_from_db(
    *,
    service_key: str | None = None,
    transaction_type: str | None = None,
    api_account_ids: list[int] | None = None,
    company_name: str | None = None,
    start_ms: int | None = None,
    end_ms: int | None = None,
    search_text: str | None = None,
    limit: int | None = None,
    db_name: str = DB_NAME,
) -> Result:
    try:
        clean_company = _compact_text(company_name).casefold()
        clean_search = _compact_text(search_text)
        safe_limit = int(limit) if limit is not None and int(limit) > 0 else None
        engine = get_engine(db_name)
        with Session(engine) as session:
            stmt = (
                select(FinanceTransaction)
                .options(selectinload(FinanceTransaction.api_account))
                .order_by(FinanceTransaction.transactionDate.desc(), FinanceTransaction.pk.desc())
            )
            clean_service = _compact_text(service_key)
            if clean_service:
                stmt = stmt.where(FinanceTransaction.serviceKey == clean_service)
            clean_type = _compact_text(transaction_type)
            if clean_type:
                stmt = stmt.where(FinanceTransaction.transactionType == clean_type)
            if api_account_ids:
                clean_account_ids = [int(row) for row in api_account_ids if row is not None]
                if clean_account_ids:
                    stmt = stmt.where(FinanceTransaction.api_account_id.in_(clean_account_ids))
            if start_ms not in (None, ""):
                stmt = stmt.where(FinanceTransaction.transactionDate >= _as_int(start_ms))
            if end_ms not in (None, ""):
                stmt = stmt.where(FinanceTransaction.transactionDate <= _as_int(end_ms))
            if safe_limit is not None and not clean_company and not clean_search:
                stmt = stmt.limit(safe_limit)
            rows = session.exec(stmt).all() or []

        records = [_transaction_to_dict(row) for row in rows]
        if clean_company:
            records = [row for row in records if _compact_text(row.get("companyName")).casefold() == clean_company]
        if clean_search:
            records = [row for row in records if _matches_search(row, clean_search)]
        if safe_limit is not None:
            records = records[:safe_limit]
        return Result.ok(
            f"Finans hareketleri cekildi (toplam: {len(records)})",
            close_dialog=False,
            data={"records": records},
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def get_finance_cargo_invoice_transactions_from_db(
    *,
    api_account_ids: list[int] | None = None,
    company_name: str | None = None,
    start_ms: int | None = None,
    end_ms: int | None = None,
    search_text: str | None = None,
    limit: int | None = None,
    db_name: str = DB_NAME,
) -> Result:
    try:
        clean_company = _compact_text(company_name).casefold()
        clean_search = _compact_text(search_text)
        safe_limit = int(limit) if limit is not None and int(limit) > 0 else None
        engine = get_engine(db_name)
        with Session(engine) as session:
            stmt = (
                select(FinanceTransaction)
                .options(selectinload(FinanceTransaction.api_account))
                .where(FinanceTransaction.commissionInvoiceSerialNumber.is_not(None))
                .where(FinanceTransaction.commissionInvoiceSerialNumber != "")
                .order_by(FinanceTransaction.transactionDate.desc(), FinanceTransaction.pk.desc())
            )
            if api_account_ids:
                clean_account_ids = [int(row) for row in api_account_ids if row is not None]
                if clean_account_ids:
                    stmt = stmt.where(FinanceTransaction.api_account_id.in_(clean_account_ids))
            if start_ms not in (None, ""):
                stmt = stmt.where(FinanceTransaction.transactionDate >= _as_int(start_ms))
            if end_ms not in (None, ""):
                stmt = stmt.where(FinanceTransaction.transactionDate <= _as_int(end_ms))
            if safe_limit is not None and not clean_company and not clean_search:
                stmt = stmt.limit(safe_limit)
            rows = session.exec(stmt).all() or []

        records = [_transaction_to_dict(row) for row in rows]
        if clean_company:
            records = [row for row in records if _compact_text(row.get("companyName")).casefold() == clean_company]
        if clean_search:
            records = [row for row in records if _matches_search(row, clean_search)]
        if safe_limit is not None:
            records = records[:safe_limit]
        return Result.ok(
            f"Kargo faturasi hareketleri cekildi (toplam: {len(records)})",
            close_dialog=False,
            data={"records": records},
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def get_finance_cargo_invoice_items_from_db(
    *,
    invoice_serial_numbers: list[str] | None = None,
    api_account_ids: list[int] | None = None,
    company_name: str | None = None,
    search_text: str | None = None,
    limit: int | None = None,
    db_name: str = DB_NAME,
) -> Result:
    try:
        clean_company = _compact_text(company_name).casefold()
        clean_search = _compact_text(search_text)
        safe_limit = int(limit) if limit is not None and int(limit) > 0 else None
        engine = get_engine(db_name)
        with Session(engine) as session:
            stmt = (
                select(FinanceCargoInvoiceItem)
                .options(selectinload(FinanceCargoInvoiceItem.api_account))
                .order_by(FinanceCargoInvoiceItem.pk.desc())
            )
            if api_account_ids:
                clean_account_ids = [int(row) for row in api_account_ids if row is not None]
                if clean_account_ids:
                    stmt = stmt.where(FinanceCargoInvoiceItem.api_account_id.in_(clean_account_ids))
            if invoice_serial_numbers:
                clean_serials = [_compact_text(row) for row in invoice_serial_numbers if _compact_text(row)]
                if clean_serials:
                    stmt = stmt.where(FinanceCargoInvoiceItem.invoiceSerialNumber.in_(clean_serials))
            if safe_limit is not None and not clean_company and not clean_search:
                stmt = stmt.limit(safe_limit)
            rows = session.exec(stmt).all() or []

        records = [_cargo_item_to_dict(row) for row in rows]
        if clean_company:
            records = [row for row in records if _compact_text(row.get("companyName")).casefold() == clean_company]
        if clean_search:
            records = [row for row in records if _matches_search(row, clean_search)]
        if safe_limit is not None:
            records = records[:safe_limit]
        return Result.ok(
            f"Kargo fatura kalemleri cekildi (toplam: {len(records)})",
            close_dialog=False,
            data={"records": records},
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def get_finance_filter_metadata(db_name: str = DB_NAME) -> Result:
    try:
        def _clean_distinct(values: list[Any]) -> list[str]:
            return sorted({_compact_text(value) for value in values if _compact_text(value)})

        engine = get_engine(db_name)
        with Session(engine) as session:
            tx_count = int(session.exec(select(func.count(FinanceTransaction.pk))).one() or 0)
            cargo_count = int(session.exec(select(func.count(FinanceCargoInvoiceItem.pk))).one() or 0)
            min_date, max_date = session.exec(
                select(
                    func.min(FinanceTransaction.transactionDate),
                    func.max(FinanceTransaction.transactionDate),
                )
            ).one()
            transaction_types = _clean_distinct(
                session.exec(
                    select(FinanceTransaction.transactionType)
                    .where(FinanceTransaction.transactionType.is_not(None))
                    .where(FinanceTransaction.transactionType != "")
                    .distinct()
                ).all()
            )
            service_keys = _clean_distinct(
                session.exec(
                    select(FinanceTransaction.serviceKey)
                    .where(FinanceTransaction.serviceKey.is_not(None))
                    .where(FinanceTransaction.serviceKey != "")
                    .distinct()
                ).all()
            )
            tx_companies = _clean_distinct(
                session.exec(
                    select(ApiAccount.comp_name)
                    .select_from(FinanceTransaction)
                    .join(ApiAccount, FinanceTransaction.api_account_id == ApiAccount.pk)
                    .where(ApiAccount.comp_name.is_not(None))
                    .where(ApiAccount.comp_name != "")
                    .distinct()
                ).all()
            )
            cargo_companies = _clean_distinct(
                session.exec(
                    select(ApiAccount.comp_name)
                    .select_from(FinanceCargoInvoiceItem)
                    .join(ApiAccount, FinanceCargoInvoiceItem.api_account_id == ApiAccount.pk)
                    .where(ApiAccount.comp_name.is_not(None))
                    .where(ApiAccount.comp_name != "")
                    .distinct()
                ).all()
            )
        min_date_int = _as_int(min_date, 0)
        max_date_int = _as_int(max_date, 0)

        return Result.ok(
            "Finance filter metadata hazÄ±r.",
            close_dialog=False,
            data={
                "company_names": sorted({*tx_companies, *cargo_companies}),
                "transaction_types": transaction_types,
                "service_keys": service_keys,
                "min_transaction_date": min_date_int,
                "max_transaction_date": max_date_int,
                "last_sync_at": max_date_int,
                "transaction_count": tx_count,
                "cargo_item_count": cargo_count,
            },
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def get_finance_account_sync_bounds(*, api_account_id: int, db_name: str = DB_NAME) -> Result:
    try:
        account_pk = _as_optional_int(api_account_id)
        if account_pk is None:
            return Result.fail("Gecersiz finance account kimligi.", close_dialog=False)

        engine = get_engine(db_name)
        with Session(engine) as session:
            min_tx, max_tx, row_count = session.exec(
                select(
                    func.min(FinanceTransaction.transactionDate),
                    func.max(FinanceTransaction.transactionDate),
                    func.count(FinanceTransaction.pk),
                ).where(FinanceTransaction.api_account_id == int(account_pk))
            ).one()

        return Result.ok(
            "Finance account sync sÄ±nÄ±rlarÄ± hazÄ±r.",
            close_dialog=False,
            data={
                "api_account_id": int(account_pk),
                "min_transaction_date": _as_optional_int(min_tx),
                "max_transaction_date": _as_optional_int(max_tx),
                "count": _as_int(row_count, 0),
            },
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def _engine():
    return get_engine(DB_NAME)


def _ok(message: str, **data: Any) -> Result:
    return Result.ok(message, close_dialog=False, data=data)


def _fail(message: str, error: Exception) -> Result:
    return Result.fail(map_error_to_message(error), error=error, close_dialog=False, data={"detail": message})


def create_brand(
    name: str,
    code: Optional[str] = None,
    registration_no: Optional[str] = None,
    country: Optional[str] = None,
    website: Optional[str] = None,
    contact_email: Optional[str] = None,
    contact_phone: Optional[str] = None,
    address: Optional[str] = None,
    note: Optional[str] = None,
    db_name: str = DB_NAME,
) -> Result:
    try:
        payload = {
            "name": (name or "").strip(),
            "code": (code or "").strip() or None,
            "registration_no": (registration_no or "").strip() or None,
            "country": (country or "").strip() or None,
            "website": (website or "").strip() or None,
            "contact_email": (contact_email or "").strip() or None,
            "contact_phone": (contact_phone or "").strip() or None,
            "address": (address or "").strip() or None,
            "note": (note or "").strip() or None,
            "is_active": True,
            "created_at": _utcnow_naive(),
        }
        if not payload["name"]:
            return Result.fail("Marka adı boş olamaz.", close_dialog=False)
        result = create_records(
            model=Brand,
            mode="plain",
            data_list=[payload],
            db_name=db_name,
            conflict_keys=["name"],
            normalizer=_text_normalizer,
        )
        if not result.success:
            return result
        return _ok("Marka başarıyla kaydedildi.")
    except Exception as error:
        return _fail("Marka oluşturulamadı.", error)


def update_brand(pk: int, update_data: Dict[str, Any], db_name: str = DB_NAME) -> Result:
    try:
        if not pk:
            return Result.fail("Geçersiz id.", close_dialog=False)
        return update_records(model=Brand, filters={"pk": pk}, update_data=update_data, db_name=db_name)
    except Exception as error:
        return _fail("Marka güncellenemedi.", error)


def delete_brand(pk: int, db_name: str = DB_NAME) -> Result:
    try:
        if not pk:
            return Result.fail("Geçersiz id.", close_dialog=False)
        return delete_records(model=Brand, filters={"pk": pk}, db_name=db_name)
    except Exception as error:
        return _fail("Marka silinemedi.", error)


def list_brands(only_active: bool = True, db_name: str = DB_NAME) -> Result:
    try:
        result = get_records(model=Brand, db_engine=get_engine(db_name or DB_NAME))
        if not result.success:
            return result
        records = list((result.data or {}).get("records") or [])
        if only_active:
            records = [record for record in records if bool(getattr(record, "is_active", False))]
        return _ok(
            f"{len(records)} marka çekildi." if records else "Marka bulunmuyor.",
            records=records,
        )
    except Exception as error:
        return _fail("Markalar okunamadı.", error)


def create_company(name: str, db_name: str = DB_NAME, **kwargs: Any) -> Result:
    try:
        payload = {
            "name": (name or "").strip(),
            "tax_no": (kwargs.get("tax_no") or "").strip() or None,
            "phone": (kwargs.get("phone") or "").strip() or None,
            "email": (kwargs.get("email") or "").strip() or None,
            "address": (kwargs.get("address") or "").strip() or None,
            "note": (kwargs.get("note") or "").strip() or None,
            "is_active": True,
            "created_at": _utcnow_naive(),
        }
        if not payload["name"]:
            return Result.fail("Şirket adı boş olamaz.", close_dialog=False)
        result = create_records(
            model=Company,
            mode="plain",
            data_list=[payload],
            db_name=db_name,
            conflict_keys=["name"],
            normalizer=_text_normalizer,
        )
        if not result.success:
            return result
        return _ok("Şirket başarıyla kaydedildi.")
    except Exception as error:
        return _fail("Şirket oluşturulamadı.", error)


def update_company(pk: int, update_data: Dict[str, Any], db_name: str = DB_NAME) -> Result:
    try:
        if not pk:
            return Result.fail("Geçersiz id.", close_dialog=False)
        return update_records(model=Company, filters={"pk": pk}, update_data=update_data, db_name=db_name)
    except Exception as error:
        return _fail("Şirket güncellenemedi.", error)


def delete_company(pk: int, db_name: str = DB_NAME) -> Result:
    try:
        if not pk:
            return Result.fail("Geçersiz id.", close_dialog=False)
        return delete_records(model=Company, filters={"pk": pk}, db_name=db_name)
    except Exception as error:
        return _fail("Şirket silinemedi.", error)


def list_companies(only_active: bool = True, db_name: str = DB_NAME) -> Result:
    try:
        result = get_records(model=Company, db_engine=get_engine(db_name or DB_NAME))
        if not result.success:
            return result
        records = list((result.data or {}).get("records") or [])
        if only_active:
            records = [record for record in records if bool(getattr(record, "is_active", False))]
        return _ok(
            f"{len(records)} şirket çekildi." if records else "Şirket bulunmuyor.",
            records=records,
        )
    except Exception as error:
        return _fail("Şirketler okunamadı.", error)

