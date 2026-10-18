from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
import unicodedata
from typing import Any

from sqlalchemy import func, or_
from sqlmodel import Session, select

from Account.models.models import ApiAccount
from Core.processors.report_artifacts import ReportColumn, ReportSnapshot, make_report_sheet
from Core.utils.contact_utils import normalize_contact_address
from Core.utils.model_utils import get_engine
from Feedback.processors.pipeline import Result, map_error_to_message
from Marketplaces.constants.catalog_constants import canonical_platform_code
from Marketplaces.processors.catalog import normalize_marketplace_environment
from Orders.constants import ORDER_FINAL_STATUS_CODES
from Orders.models.trendyol.models import OrderData, OrderHeader, OrderItem, ReturnClaim
from Orders.processors.trendyol.pipeline import (
    get_latest_order_items_by_numbers,
    get_latest_orders_filtered,
    get_latest_return_claims_filtered,
    is_ready_to_ship_order_status,
    summarize_order_shipping_deadline,
)
from settings import DB_NAME


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _normalized_key(value: Any) -> str:
    text = unicodedata.normalize(
        "NFKD",
        _text(value).casefold().replace("\u0131", "i"),
    )
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text).strip()


def _search_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _normalized_key(value)).strip()


def _order_status(row: Any) -> str:
    return _text(
        getattr(row, "shipmentPackageStatus", None)
        or getattr(row, "status", None)
        or "Unknown"
    )


def _order_selection_projection(row: Any) -> dict[str, Any]:
    return {
        "api_account_id": getattr(row, "api_account_id", None),
        "order_number": _text(getattr(row, "orderNumber", "")),
        "package_id": getattr(row, "id", None),
        "shipment_package_id": getattr(row, "shipmentPackageId", None),
        "status": _order_status(row),
        "cargo_provider": _text(getattr(row, "cargoProviderName", "")),
        "cargo_tracking_number": _text(
            getattr(row, "cargoTrackingNumber", "")
        ),
        "printed": bool(getattr(row, "is_printed", False)),
        "extracted": bool(getattr(row, "is_extracted", False)),
        "total_price": _number(
            getattr(row, "packageTotalPrice", None)
            or getattr(row, "totalPrice", None)
        ),
        "currency": _text(getattr(row, "currencyCode", "")) or "TRY",
        "order_date_ms": int(getattr(row, "orderDate", 0) or 0),
        "last_modified_ms": int(
            getattr(row, "lastModifiedDate", 0) or 0
        ),
    }


def _order_source_snapshot_hash(rows: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        "\n".join(
            "|".join(
                (
                    str(row.get("api_account_id") or ""),
                    _text(row.get("order_number")),
                    _text(row.get("status")),
                    str(int(row.get("last_modified_ms") or 0)),
                    "1" if bool(row.get("printed")) else "0",
                    "1" if bool(row.get("extracted")) else "0",
                )
            )
            for row in sorted(
                rows,
                key=lambda item: (
                    int(item.get("api_account_id") or 0),
                    _text(item.get("order_number")),
                ),
            )
        ).encode("utf-8")
    ).hexdigest()


def _order_source_revision(rows: list[dict[str, Any]]) -> int:
    return max(
        (int(row.get("last_modified_ms") or 0) for row in rows),
        default=0,
    )


def _item_sales_source_provenance(
    *,
    order_rows: list[Any],
    item_rows: list[Any],
    scope: dict[str, Any],
) -> tuple[int, str]:
    """Fingerprint the exact non-PII inputs behind an item-sales aggregate."""

    projected_orders = [
        {
            "api_account_id": getattr(row, "api_account_id", None),
            "order_number": _text(getattr(row, "orderNumber", "")),
            "status": _order_status(row),
            "last_modified_ms": int(
                getattr(row, "lastModifiedDate", 0) or 0
            ),
        }
        for row in order_rows
    ]
    projected_items = [
        {
            "api_account_id": getattr(row, "api_account_id", None),
            "order_number": _text(getattr(row, "orderNumber", "")),
            "line_id": _text(
                getattr(row, "lineId", None)
                or getattr(row, "id", None)
                or getattr(row, "barcode", "")
                or getattr(row, "sku", "")
                or getattr(row, "merchantSku", "")
                or getattr(row, "productName", "")
            ),
            "snapshot_last_modified_ms": int(
                getattr(row, "snapshotLastModifiedDate", 0) or 0
            ),
            "quantity": int(getattr(row, "quantity", 0) or 0),
            "gross_amount": _number(
                getattr(row, "lineGrossAmount", None)
                if getattr(row, "lineGrossAmount", None) is not None
                else getattr(row, "amount", None)
                if getattr(row, "amount", None) is not None
                else _number(getattr(row, "price", 0))
                * int(getattr(row, "quantity", 0) or 0)
            ),
        }
        for row in item_rows
    ]
    payload = {
        "scope": dict(scope or {}),
        "orders": sorted(
            projected_orders,
            key=lambda row: (
                int(row.get("api_account_id") or 0),
                _text(row.get("order_number")),
            ),
        ),
        "items": sorted(
            projected_items,
            key=lambda row: (
                int(row.get("api_account_id") or 0),
                _text(row.get("order_number")),
                _text(row.get("line_id")),
            ),
        ),
    }
    revision = max(
        [
            int(row.get("last_modified_ms") or 0)
            for row in projected_orders
        ]
        + [
            int(row.get("snapshot_last_modified_ms") or 0)
            for row in projected_items
        ],
        default=0,
    )
    content_hash = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return revision, content_hash


def _order_projection(row: Any) -> dict[str, Any]:
    account = getattr(row, "api_account", None)
    return {
        **_order_selection_projection(row),
        "customer": " ".join(
            value
            for value in (
                _text(getattr(row, "customerFirstName", "")),
                _text(getattr(row, "customerLastName", "")),
            )
            if value
        ),
        "platform_code": canonical_platform_code(
            getattr(account, "platform", "") if account is not None else ""
        ),
    }


def _order_item_projection(row: Any) -> dict[str, Any]:
    return {
        "line_id": getattr(row, "lineId", None) or getattr(row, "id", None),
        "product_name": _text(getattr(row, "productName", "")),
        "sku": _text(
            getattr(row, "sku", "")
            or getattr(row, "merchantSku", "")
            or getattr(row, "stockCode", "")
        ),
        "barcode": _text(getattr(row, "barcode", "")),
        "content_id": _text(getattr(row, "contentId", "")),
        "product_code": _text(getattr(row, "productCode", "")),
        "product_size": _text(getattr(row, "productSize", "")),
        "product_color": _text(getattr(row, "productColor", "")),
        "product_origin": _text(getattr(row, "productOrigin", "")),
        "quantity": int(getattr(row, "quantity", 0) or 0),
        "price": _number(
            getattr(row, "price", None) or getattr(row, "amount", None)
        ),
        "line_total": _number(
            getattr(row, "lineGrossAmount", None)
            or getattr(row, "lineUnitPrice", None)
            or getattr(row, "amount", None)
        ),
        "status": _text(getattr(row, "orderLineItemStatusName", "")),
    }


def _return_claim_projection(row: Any) -> dict[str, Any]:
    account = getattr(row, "api_account", None)
    return {
        "api_account_id": getattr(row, "api_account_id", None),
        "claim_id": _text(getattr(row, "claimId", "")),
        "claim_number": _text(getattr(row, "claimNumber", "")),
        "order_number": _text(getattr(row, "orderNumber", "")),
        "order_shipment_package_id": getattr(row, "orderShipmentPackageId", None),
        "status": _text(getattr(row, "claimItemStatus", "")),
        "reason": _text(getattr(row, "claimReason", "")),
        "item_count": int(getattr(row, "itemCount", 0) or 0),
        "total_price": _number(getattr(row, "totalPrice", None)),
        "currency": _text(getattr(row, "currencyCode", "")) or "TRY",
        "cargo_provider": _text(getattr(row, "cargoProviderName", "")),
        "cargo_tracking_number": _text(
            getattr(row, "cargoTrackingNumber", "")
        ),
        "customer_first_name": _text(getattr(row, "customerFirstName", "")),
        "customer_last_name": _text(getattr(row, "customerLastName", "")),
        "claim_date_ms": int(getattr(row, "claimDate", 0) or 0),
        "last_modified_ms": int(getattr(row, "lastModifiedDate", 0) or 0),
        "claim_line_item_ids": list(
            getattr(row, "claimLineItemIds", None) or []
        ),
        "waiting_line_item_ids": list(
            getattr(row, "waitingClaimLineItemIds", None) or []
        ),
        "platform_code": canonical_platform_code(
            getattr(account, "platform", "") if account is not None else ""
        ),
    }


def resolve_order_record(
    token: Any,
    *,
    api_account_id: int | None = None,
    db_name: str = DB_NAME,
) -> Result:
    try:
        clean = _text(token)
        if not clean:
            return Result.fail("Siparis referansi bos.", close_dialog=False)
        conditions = [
            OrderData.orderNumber == clean,
            OrderData.cargoTrackingNumber == clean,
            OrderData.cargoSenderNumber == clean,
        ]
        try:
            numeric = int(clean)
        except (TypeError, ValueError):
            numeric = None
        if numeric is not None:
            conditions.extend(
                [OrderData.pk == numeric, OrderData.id == numeric, OrderData.shipmentPackageId == numeric]
            )
        with Session(get_engine(db_name or DB_NAME)) as session:
            stmt = select(OrderData).where(or_(*conditions))
            if api_account_id not in (None, ""):
                stmt = stmt.where(OrderData.api_account_id == int(api_account_id))
            record = session.exec(
                stmt.order_by(OrderData.lastModifiedDate.desc(), OrderData.pk.desc())
            ).first()
            if record is None:
                return Result.fail(f"Siparis kaydi bulunamadi: {clean}", close_dialog=False)
            account = session.get(ApiAccount, getattr(record, "api_account_id", None)) if getattr(record, "api_account_id", None) else None
            object.__setattr__(record, "api_account", account)
            session.expunge(record)
            if account is not None:
                session.expunge(account)
        return Result.ok("Siparis kaydi cozuldu.", close_dialog=False, data={"record": record})
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def resolve_return_claim(
    token: Any,
    *,
    api_account_id: int | None = None,
    db_name: str = DB_NAME,
) -> Result:
    try:
        clean = _text(token)
        if not clean:
            return Result.fail("Iade referansi bos.", close_dialog=False)
        with Session(get_engine(db_name or DB_NAME)) as session:
            stmt = select(ReturnClaim).where(
                or_(
                    ReturnClaim.claimId == clean,
                    ReturnClaim.claimNumber == clean,
                    ReturnClaim.orderNumber == clean,
                )
            )
            if api_account_id not in (None, ""):
                stmt = stmt.where(ReturnClaim.api_account_id == int(api_account_id))
            record = session.exec(
                stmt.order_by(ReturnClaim.lastModifiedDate.desc(), ReturnClaim.pk.desc())
            ).first()
            if record is None:
                return Result.fail(f"Iade kaydi bulunamadi: {clean}", close_dialog=False)
            account = session.get(ApiAccount, getattr(record, "api_account_id", None)) if getattr(record, "api_account_id", None) else None
            object.__setattr__(record, "api_account", account)
            session.expunge(record)
            if account is not None:
                session.expunge(account)
        return Result.ok("Iade kaydi cozuldu.", close_dialog=False, data={"record": record})
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def list_orders(
    *,
    order_numbers: list[str] | None = None,
    api_account_ids: list[int] | None = None,
    db_name: str = DB_NAME,
) -> Result:
    try:
        with Session(get_engine(db_name or DB_NAME)) as session:
            stmt = select(OrderData)
            numbers = [_text(value) for value in list(order_numbers or []) if _text(value)]
            accounts = [int(value) for value in list(api_account_ids or []) if value is not None]
            if numbers:
                stmt = stmt.where(OrderData.orderNumber.in_(numbers))
            if accounts:
                stmt = stmt.where(OrderData.api_account_id.in_(accounts))
            rows = session.exec(
                stmt.order_by(OrderData.lastModifiedDate.desc(), OrderData.pk.desc())
            ).all() or []
        return Result.ok("Siparis kayitlari getirildi.", close_dialog=False, data={"records": rows})
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def list_order_headers(
    order_numbers: list[str] | None = None,
    *,
    api_account_ids: list[int] | None = None,
    db_name: str = DB_NAME,
) -> Result:
    try:
        with Session(get_engine(db_name or DB_NAME)) as session:
            stmt = select(OrderHeader)
            numbers = [_text(value) for value in list(order_numbers or []) if _text(value)]
            accounts = [int(value) for value in list(api_account_ids or []) if value is not None]
            if numbers:
                stmt = stmt.where(OrderHeader.orderNumber.in_(numbers))
            if accounts:
                stmt = stmt.where(OrderHeader.api_account_id.in_(accounts))
            rows = session.exec(stmt.order_by(OrderHeader.pk.desc())).all() or []
        return Result.ok("Siparis header kayitlari getirildi.", close_dialog=False, data={"records": rows})
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def restore_order_header_extraction_snapshots(
    snapshots: list[dict[str, Any]],
    *,
    db_name: str = DB_NAME,
) -> Result:
    try:
        restored: list[int] = []
        with Session(get_engine(db_name or DB_NAME)) as session:
            for snapshot in list(snapshots or []):
                pk = int(snapshot.get("pk") or 0)
                row = session.get(OrderHeader, pk) if pk > 0 else None
                if row is None:
                    return Result.fail(
                        "Kaynak siparis header kaydi cleanup sirasinda bulunamadi.",
                        close_dialog=False,
                    )
                row.is_extracted = bool(snapshot.get("is_extracted"))
                row.extracted_at = snapshot.get("extracted_at")
                session.add(row)
                restored.append(pk)
            session.commit()
        return Result.ok(
            "Siparis header snapshotlari geri yuklendi.",
            close_dialog=False,
            data={"restored_pks": restored},
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def list_order_items(
    order_numbers: list[str],
    *,
    api_account_ids: list[int] | None = None,
    db_name: str = DB_NAME,
) -> Result:
    try:
        numbers = [_text(value) for value in list(order_numbers or []) if _text(value)]
        if not numbers:
            return Result.ok("Siparis kalemi bulunamadi.", close_dialog=False, data={"records": []})
        with Session(get_engine(db_name or DB_NAME)) as session:
            stmt = select(OrderItem).where(OrderItem.orderNumber.in_(numbers))
            accounts = [int(value) for value in list(api_account_ids or []) if value is not None]
            if accounts:
                stmt = stmt.where(OrderItem.api_account_id.in_(accounts))
            rows = session.exec(
                stmt.order_by(OrderItem.snapshotLastModifiedDate.desc(), OrderItem.pk.desc())
            ).all() or []
        return Result.ok("Siparis kalemleri getirildi.", close_dialog=False, data={"records": rows})
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def list_return_claims(
    *,
    claim_ids: list[str] | None = None,
    order_numbers: list[str] | None = None,
    api_account_ids: list[int] | None = None,
    active: bool | None = True,
    statuses: list[str] | None = None,
    start_date_ms: int | None = None,
    end_date_ms: int | None = None,
    db_name: str = DB_NAME,
) -> Result:
    try:
        with Session(get_engine(db_name or DB_NAME)) as session:
            stmt = select(ReturnClaim)
            ids = [_text(value) for value in list(claim_ids or []) if _text(value)]
            numbers = [_text(value) for value in list(order_numbers or []) if _text(value)]
            accounts = [int(value) for value in list(api_account_ids or []) if value is not None]
            clean_statuses = [_text(value) for value in list(statuses or []) if _text(value)]
            if ids:
                stmt = stmt.where(ReturnClaim.claimId.in_(ids))
            if numbers:
                stmt = stmt.where(ReturnClaim.orderNumber.in_(numbers))
            if accounts:
                stmt = stmt.where(ReturnClaim.api_account_id.in_(accounts))
            if clean_statuses:
                stmt = stmt.where(ReturnClaim.claimItemStatus.in_(clean_statuses))
            if start_date_ms is not None:
                stmt = stmt.where(
                    func.coalesce(ReturnClaim.claimDate, ReturnClaim.orderDate, 0)
                    >= int(start_date_ms)
                )
            if end_date_ms is not None:
                stmt = stmt.where(
                    func.coalesce(ReturnClaim.claimDate, ReturnClaim.orderDate, 0)
                    <= int(end_date_ms)
                )
            if active is True:
                stmt = stmt.where(ReturnClaim.sync_deleted_at.is_(None))
            elif active is False:
                stmt = stmt.where(ReturnClaim.sync_deleted_at.is_not(None))
            rows = session.exec(
                stmt.order_by(ReturnClaim.lastModifiedDate.desc(), ReturnClaim.pk.desc())
            ).all() or []
        return Result.ok("Iade kayitlari getirildi.", close_dialog=False, data={"records": rows})
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def select_ready_to_ship_orders(
    *,
    order_numbers: list[str] | None = None,
    api_account_ids: list[int] | None = None,
    start_date_ms: int | None = None,
    end_date_ms: int | None = None,
    only_not_printed: bool = False,
    limit: int = 500,
    db_name: str = DB_NAME,
) -> Result:
    """Create the one authoritative ready-order set shared by count/list/actions."""

    try:
        clean_limit = max(1, min(500, int(limit or 500)))
        latest = get_latest_orders_filtered(
            shipment_statuses=["Created", "Picking", "ReadyToShip"],
            order_numbers=order_numbers,
            start_ms=start_date_ms,
            end_ms=end_date_ms,
            api_account_ids=api_account_ids,
            db_name=db_name,
        )
        if not latest.success:
            return latest
        ready_rows = list((latest.data or {}).get("orders") or [])
        ready_rows.sort(
            key=lambda row: (
                int(getattr(row, "orderDate", 0) or 0),
                _text(getattr(row, "orderNumber", "")),
            ),
            reverse=True,
        )
        projected: list[dict[str, Any]] = []
        printed_count = 0
        extracted_count = 0
        for row in ready_rows:
            is_printed = bool(getattr(row, "is_printed", False))
            is_extracted = bool(getattr(row, "is_extracted", False))
            printed_count += int(is_printed)
            extracted_count += int(is_extracted)
            projected.append(_order_selection_projection(row))
        eligible = (
            [row for row in projected if not row["printed"]]
            if only_not_printed
            else projected
        )
        listed = eligible[:clean_limit]
        order_numbers = [
            row["order_number"] for row in listed if row["order_number"]
        ]
        query_fingerprint = hashlib.sha256(
            "|".join(
                (
                    "orders.ready_to_ship",
                    ",".join(
                        str(value)
                        for value in sorted(
                            int(value)
                            for value in list(api_account_ids or [])
                            if value not in (None, "")
                        )
                    ),
                    str(start_date_ms or ""),
                    str(end_date_ms or ""),
                    "not_printed" if only_not_printed else "all_print_states",
                )
            ).encode("utf-8")
        ).hexdigest()
        source_snapshot_hash = _order_source_snapshot_hash(projected)
        source_revision = _order_source_revision(projected)
        return Result.ok(
            "Kargoya hazir authoritative siparis secimi hazirlandi.",
            close_dialog=False,
            data={
                "ready_to_ship": len(projected),
                "selected_count": len(eligible),
                "printed": printed_count,
                "not_printed": max(0, len(projected) - printed_count),
                "extracted": extracted_count,
                "not_extracted": max(0, len(projected) - extracted_count),
                "only_not_printed": bool(only_not_printed),
                "listed_count": len(listed),
                "order_numbers": order_numbers,
                "truncated": len(listed) < len(eligible),
                "orders": listed,
                "api_account_ids": sorted(
                    {
                        int(row["api_account_id"])
                        for row in projected
                        if row.get("api_account_id") not in (None, "")
                    }
                ),
                "simulated_excluded": int(
                    (latest.data or {}).get("simulated_excluded") or 0
                ),
                "query_fingerprint": query_fingerprint,
                "source_revision": source_revision,
                "source_snapshot_hash": source_snapshot_hash,
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def summarize_orders(
    *,
    api_account_ids: list[int] | None = None,
    start_date_ms: int | None = None,
    end_date_ms: int | None = None,
    sample_limit: int = 8,
    db_name: str = DB_NAME,
) -> Result:
    """Summarize latest operational order snapshots in the Orders domain."""

    try:
        latest = get_latest_orders_filtered(
            start_ms=start_date_ms,
            end_ms=end_date_ms,
            api_account_ids=api_account_ids,
            db_name=db_name,
        )
        if not latest.success:
            return latest
        rows = list((latest.data or {}).get("orders") or [])
        status_counts: dict[str, int] = {}
        cancelled_count = 0
        estimated_revenue = 0.0
        revenue_by_currency: dict[str, float] = {}
        for row in rows:
            status = _text(
                getattr(row, "shipmentPackageStatus", None)
                or getattr(row, "status", None)
                or "Unknown"
            )
            status_counts[status] = status_counts.get(status, 0) + 1
            is_cancelled = "cancel" in status.casefold() or "iptal" in status.casefold()
            cancelled_count += int(is_cancelled)
            if not is_cancelled:
                amount = _number(
                    getattr(row, "packageTotalPrice", None)
                    or getattr(row, "totalPrice", None)
                )
                currency = (
                    _text(getattr(row, "currencyCode", "")).upper()
                    or "TRY"
                )
                estimated_revenue += amount
                revenue_by_currency[currency] = (
                    revenue_by_currency.get(currency, 0.0) + amount
                )
        ordered = sorted(
            rows,
            key=lambda row: int(getattr(row, "orderDate", 0) or 0),
            reverse=True,
        )
        total_orders = len(rows)
        revenue_order_count = max(0, total_orders - cancelled_count)
        status_rates = {
            status: round((count / total_orders) * 100.0, 2)
            for status, count in status_counts.items()
        } if total_orders else {}
        dominant_status = ""
        dominant_status_count = 0
        if status_counts:
            dominant_status, dominant_status_count = max(
                status_counts.items(),
                key=lambda item: (int(item[1]), str(item[0])),
            )
        dominant_status_rate = (
            round((dominant_status_count / total_orders) * 100.0, 2)
            if total_orders
            else 0.0
        )
        cancellation_rate = (
            round((cancelled_count / total_orders) * 100.0, 2)
            if total_orders
            else 0.0
        )
        average_revenue_per_order = (
            round(estimated_revenue / revenue_order_count, 2)
            if revenue_order_count
            else 0.0
        )
        currencies = sorted(revenue_by_currency)
        currency = (
            currencies[0]
            if len(currencies) == 1
            else "MIXED"
            if currencies
            else "TRY"
        )
        scope_account_ids = sorted(
            {
                int(getattr(row, "api_account_id"))
                for row in ordered
                if getattr(row, "api_account_id", None) not in (None, "")
            }
        )
        source_rows = [_order_selection_projection(row) for row in ordered]
        samples = [
            {
                "api_account_id": getattr(row, "api_account_id", None),
                "order_number": _text(getattr(row, "orderNumber", "")),
                "status": _text(
                    getattr(row, "shipmentPackageStatus", None)
                    or getattr(row, "status", None)
                    or "Unknown"
                ),
                "total_price": _number(
                    getattr(row, "packageTotalPrice", None)
                    or getattr(row, "totalPrice", None)
                ),
            }
            for row in ordered[: max(1, min(50, int(sample_limit or 8)))]
        ]
        return Result.ok(
            "Siparis ozeti Orders domaininde hesaplandi.",
            close_dialog=False,
            data={
                "total_orders": total_orders,
                "cancelled_orders": cancelled_count,
                "estimated_revenue": round(estimated_revenue, 2),
                "currency": currency,
                "currencies": currencies or [currency],
                "revenue_by_currency": {
                    code: round(value, 2)
                    for code, value in sorted(revenue_by_currency.items())
                },
                "status_counts": status_counts,
                # These are canonical derived indicators, calculated beside
                # their source aggregates.  The AI layer can therefore explain
                # a broad analysis request without inventing arithmetic in a
                # model response.
                "status_rates": status_rates,
                "dominant_status": dominant_status,
                "dominant_status_count": dominant_status_count,
                "dominant_status_rate": dominant_status_rate,
                "cancellation_rate": cancellation_rate,
                "revenue_order_count": revenue_order_count,
                "average_revenue_per_order": average_revenue_per_order,
                "sample_orders": samples,
                # Aggregate reads need account/environment identity, not a
                # record-id -> account map for every matching order. Returning
                # only distinct account ids keeps count/status observations
                # privacy-minimal and prevents long-lived task artifacts from
                # growing linearly with the entire order table.
                "scope_account_ids": scope_account_ids,
                "source_revision": _order_source_revision(source_rows),
                "source_snapshot_hash": _order_source_snapshot_hash(source_rows),
                "simulated_excluded": int(
                    (latest.data or {}).get("simulated_excluded") or 0
                ),
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def summarize_order_cancellations(
    *,
    api_account_ids: list[int] | None = None,
    start_date_ms: int | None = None,
    end_date_ms: int | None = None,
    limit: int = 12,
    db_name: str = DB_NAME,
) -> Result:
    """Return cancelled orders and latest line-level cancellation reasons."""

    try:
        latest = get_latest_orders_filtered(
            start_ms=start_date_ms,
            end_ms=end_date_ms,
            api_account_ids=api_account_ids,
            db_name=db_name,
        )
        if not latest.success:
            return latest
        cancelled = [
            row
            for row in list((latest.data or {}).get("orders") or [])
            if "cancel" in _order_status(row).casefold()
            or "iptal" in _order_status(row).casefold()
        ]
        cancelled_refs = {
            (
                getattr(row, "api_account_id", None),
                _text(getattr(row, "orderNumber", "")),
            )
            for row in cancelled
            if _text(getattr(row, "orderNumber", ""))
        }
        reasons: dict[str, int] = {}
        if cancelled_refs:
            item_result = list_order_items(
                sorted({number for _account, number in cancelled_refs}),
                api_account_ids=api_account_ids,
                db_name=db_name,
            )
            if not item_result.success:
                return item_result
            seen_lines: set[tuple[Any, str, Any]] = set()
            for item in list((item_result.data or {}).get("records") or []):
                item_ref = (
                    getattr(item, "api_account_id", None),
                    _text(getattr(item, "orderNumber", "")),
                )
                if item_ref not in cancelled_refs:
                    continue
                line_key = (
                    *item_ref,
                    getattr(item, "lineId", None)
                    or getattr(item, "id", None)
                    or getattr(item, "pk", None),
                )
                if line_key in seen_lines:
                    continue
                seen_lines.add(line_key)
                reason = _text(
                    getattr(item, "cancelReason", None)
                    or getattr(item, "cancelReasonCode", None)
                    or "Sebep yok"
                )
                reasons[reason] = reasons.get(reason, 0) + 1
        ordered = sorted(
            cancelled,
            key=lambda row: int(getattr(row, "orderDate", 0) or 0),
            reverse=True,
        )
        bounded_limit = max(1, min(100, int(limit or 12)))
        projections = [_order_projection(row) for row in ordered[:bounded_limit]]
        return Result.ok(
            "Siparis iptal ozeti Orders domaininde hesaplandi.",
            close_dialog=False,
            data={
                "cancelled_orders": len(cancelled),
                "cancel_reasons": reasons,
                "cancel_reason_count_unit": "order_line",
                "orders": projections,
                "scope_rows": [
                    {
                        "order_number": _text(getattr(row, "orderNumber", "")),
                        "api_account_id": getattr(row, "api_account_id", None),
                    }
                    for row in ordered
                    if _text(getattr(row, "orderNumber", ""))
                ],
                "listed_count": len(projections),
                "truncated": len(projections) < len(cancelled),
                "simulated_excluded": int(
                    (latest.data or {}).get("simulated_excluded") or 0
                ),
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def analyze_fulfillment_risks(
    *,
    api_account_ids: list[int] | None = None,
    start_date_ms: int | None = None,
    end_date_ms: int | None = None,
    now_ms: int | None = None,
    ready_wait_hours: float = 24.0,
    limit: int = 12,
    db_name: str = DB_NAME,
) -> Result:
    """Apply the Orders-domain fulfillment risk rules to latest snapshots."""

    try:
        latest = get_latest_orders_filtered(
            start_ms=start_date_ms,
            end_ms=end_date_ms,
            api_account_ids=api_account_ids,
            db_name=db_name,
        )
        if not latest.success:
            return latest
        measured_at_ms = int(
            now_ms
            if now_ms is not None
            else datetime.now(timezone.utc).timestamp() * 1000
        )
        final_statuses = {
            "cancelled",
            "delivered",
            "returned",
            "undeliveredandreturned",
            "unsupplied",
        }
        risks: list[dict[str, Any]] = []
        for order in list((latest.data or {}).get("orders") or []):
            status = _order_status(order)
            if _search_key(status).replace(" ", "") in final_statuses:
                continue
            tracking = _text(getattr(order, "cargoTrackingNumber", ""))
            provider = _text(getattr(order, "cargoProviderName", ""))
            order_date_ms = int(getattr(order, "orderDate", 0) or 0)
            age_hours = (
                max(0.0, (measured_at_ms - order_date_ms) / 3_600_000)
                if order_date_ms > 0
                else 0.0
            )
            reasons: list[str] = []
            if not tracking:
                reasons.append("tracking_missing")
            if not provider:
                reasons.append("cargo_provider_missing")
            if (
                is_ready_to_ship_order_status(status)
                and age_hours >= float(ready_wait_hours or 24.0)
            ):
                reasons.append("order_age_over_threshold_while_ready")
            if not reasons:
                continue
            risks.append(
                {
                    "api_account_id": getattr(order, "api_account_id", None),
                    "order_number": _text(getattr(order, "orderNumber", "")),
                    "status": status,
                    "age_hours": round(age_hours, 1),
                    "cargo_provider": provider,
                    "cargo_tracking_number": tracking,
                    "reasons": reasons,
                }
            )
        risks.sort(
            key=lambda row: (
                len(row.get("reasons") or []),
                _number(row.get("age_hours")),
            ),
            reverse=True,
        )
        bounded_limit = max(1, min(100, int(limit or 12)))
        listed = risks[:bounded_limit]
        risk_status_counts: dict[str, int] = {}
        reason_counts: dict[str, int] = {}
        for row in risks:
            risk_status_counts[row["status"]] = risk_status_counts.get(row["status"], 0) + 1
            for reason in row["reasons"]:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
        return Result.ok(
            "Fulfillment risk analizi Orders domaininde tamamlandi.",
            close_dialog=False,
            data={
                "risk_count": len(risks),
                "risk_evidence": {
                    "status_counts": risk_status_counts,
                    "reason_counts": reason_counts,
                    "reason_codes": sorted(reason_counts),
                    "reasons_overlap": True,
                    "basis": "latest_local_order_snapshots",
                    "delay_assessment": "not_measured_by_this_operation",
                    "rules": {
                        "tracking_missing": "Nonfinal order has no cargo tracking number.",
                        "cargo_provider_missing": "Nonfinal order has no cargo provider.",
                        "order_age_over_threshold_while_ready": "Ready-to-ship business queue and elapsed time since orderDate exceeds threshold; not time spent in the current status or a confirmed shipping-deadline breach.",
                    },
                    "ready_wait_hours": float(ready_wait_hours or 24.0),
                    "age_measurement": {
                        "origin_field": "orderDate",
                        "unit": "hours",
                        "operator": "greater_than_or_equal",
                        "threshold": float(ready_wait_hours or 24.0),
                        "time_in_status_measured": False,
                    },
                    "excluded_statuses": sorted(final_statuses),
                },
                "orders": listed,
                "scope_rows": [
                    {
                        "order_number": row.get("order_number"),
                        "api_account_id": row.get("api_account_id"),
                    }
                    for row in risks
                    if row.get("order_number")
                ],
                "listed_count": len(listed),
                "truncated": len(listed) < len(risks),
                "measured_at_ms": measured_at_ms,
                "ready_wait_hours": float(ready_wait_hours or 24.0),
                "simulated_excluded": int(
                    (latest.data or {}).get("simulated_excluded") or 0
                ),
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def analyze_shipping_deadlines(
    *,
    order_numbers: list[str],
    api_account_ids: list[int] | None = None,
    now_ms: int | None = None,
    db_name: str = DB_NAME,
) -> Result:
    """Analyze agreed delivery deadlines for an exact typed order scope."""

    try:
        requested = list(
            dict.fromkeys(
                _text(value)
                for value in list(order_numbers or [])
                if _text(value)
            )
        )
        if not requested:
            return Result.fail(
                "Kargolama son tarihi icin siparis secilmedi.",
                close_dialog=False,
            )
        latest = get_latest_orders_filtered(
            order_numbers=requested,
            api_account_ids=api_account_ids,
            db_name=db_name,
        )
        if not latest.success:
            return latest
        resolved_now_ms = int(
            now_ms
            if now_ms is not None
            else datetime.now(timezone.utc).timestamp() * 1000
        )
        latest_rows = list((latest.data or {}).get("orders") or [])
        found_numbers = {
            _text(getattr(row, "orderNumber", "")) for row in latest_rows
        }
        missing = [number for number in requested if number not in found_numbers]
        rows: list[dict[str, Any]] = []
        scope_rows: list[dict[str, Any]] = []
        for order in latest_rows:
            order_number = _text(getattr(order, "orderNumber", ""))
            deadline = summarize_order_shipping_deadline(
                order,
                now_ms=resolved_now_ms,
            )
            deadline_ms = deadline.get("deadline_ms")
            delta_ms = deadline.get("delta_ms")
            measurable = deadline_ms is not None and delta_ms is not None
            rows.append(
                {
                    "api_account_id": getattr(order, "api_account_id", None),
                    "order_number": order_number,
                    "status": _order_status(order),
                    "measurable": measurable,
                    "deadline_field": "agreedDeliveryDate" if measurable else "",
                    "deadline_ms": int(deadline_ms) if measurable else None,
                    "delta_hours": round(int(delta_ms) / 3_600_000, 2)
                    if measurable
                    else None,
                    "is_overdue": bool(deadline.get("is_overdue"))
                    if measurable
                    else None,
                    "overdue_days": round(
                        abs(min(0, int(delta_ms))) / 86_400_000,
                        2,
                    )
                    if measurable
                    else None,
                    "deadline_text": _text(deadline.get("text")),
                    "unavailable_reason": ""
                    if measurable
                    else (
                        "agreedDeliveryDate is absent or the order status is "
                        "outside the domain deadline rule"
                    ),
                }
            )
            if order_number:
                scope_rows.append(
                    {
                        "order_number": order_number,
                        "api_account_id": getattr(order, "api_account_id", None),
                    }
                )
        measurable_count = sum(1 for row in rows if row.get("measurable"))
        overdue_count = sum(1 for row in rows if row.get("is_overdue") is True)
        return Result.ok(
            "Kargolama son tarihi Orders domaininde analiz edildi.",
            close_dialog=False,
            data={
                "requested_count": len(requested),
                "matched_count": len(rows),
                "measurable_count": measurable_count,
                "unmeasurable_count": len(rows) - measurable_count,
                "missing_count": len(missing),
                "overdue_count": overdue_count,
                "not_overdue_count": sum(
                    1
                    for row in rows
                    if row.get("measurable")
                    and row.get("is_overdue") is False
                ),
                "measurement_rule": (
                    "Orders domain summarize_order_shipping_deadline: "
                    "agreedDeliveryDate minus measured_at_ms."
                ),
                "measured_at_ms": resolved_now_ms,
                "order_numbers": requested,
                "missing_order_numbers": missing,
                "orders": rows,
                "scope_rows": scope_rows,
                "listed_count": len(rows),
                "count": len(rows),
                "truncated": False,
                "simulated_excluded": int(
                    (latest.data or {}).get("simulated_excluded") or 0
                ),
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def summarize_returns(
    *,
    api_account_ids: list[int] | None = None,
    start_date_ms: int | None = None,
    end_date_ms: int | None = None,
    sample_limit: int = 8,
    db_name: str = DB_NAME,
) -> Result:
    """Summarize latest active return snapshots in the Orders domain."""

    try:
        latest = get_latest_return_claims_filtered(
            start_ms=start_date_ms,
            end_ms=end_date_ms,
            api_account_ids=api_account_ids,
            db_name=db_name,
        )
        if not latest.success:
            return latest
        rows = list((latest.data or {}).get("claims") or [])
        status_counts: dict[str, int] = {}
        item_count = 0
        total_amount = 0.0
        waiting_action_count = 0
        for row in rows:
            status = _text(getattr(row, "claimItemStatus", "")) or "Unknown"
            status_counts[status] = status_counts.get(status, 0) + 1
            waiting_action_count += int(status == "WaitingInAction")
            try:
                item_count += int(getattr(row, "itemCount", 0) or 0)
            except (TypeError, ValueError):
                pass
            total_amount += _number(getattr(row, "totalPrice", None))
        ordered = sorted(
            rows,
            key=lambda row: int(
                getattr(row, "claimDate", None)
                or getattr(row, "orderDate", None)
                or 0
            ),
            reverse=True,
        )
        scope_rows = [
            {
                "claim_id": _text(
                    getattr(row, "claimId", "")
                    or getattr(row, "claimNumber", "")
                ),
                "api_account_id": getattr(row, "api_account_id", None),
            }
            for row in ordered
            if _text(getattr(row, "claimId", "") or getattr(row, "claimNumber", ""))
        ]
        samples = [
            {
                "claim_id": _text(getattr(row, "claimId", "")),
                "order_number": _text(getattr(row, "orderNumber", "")),
                "status": _text(getattr(row, "claimItemStatus", "")),
                "total_price": _number(getattr(row, "totalPrice", None)),
            }
            for row in ordered[: max(1, min(50, int(sample_limit or 8)))]
        ]
        return Result.ok(
            "Iade ozeti Orders domaininde hesaplandi.",
            close_dialog=False,
            data={
                "total_claims": len(rows),
                "total_items": item_count,
                "estimated_return_amount": round(total_amount, 2),
                "status_counts": status_counts,
                "waiting_action_count": waiting_action_count,
                "sample_claims": samples,
                "scope_rows": scope_rows,
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def list_nonfinal_orders(
    *,
    final_statuses: list[str] | None = None,
    api_account_ids: list[int] | None = None,
    limit: int = 200,
    db_name: str = DB_NAME,
) -> Result:
    """List latest orders outside the caller's explicit terminal status set."""

    try:
        terminal = {
            _normalized_key(value)
            for value in list(final_statuses or ORDER_FINAL_STATUS_CODES)
            if _text(value)
        }
        latest = get_latest_orders_filtered(
            api_account_ids=api_account_ids,
            db_name=db_name,
        )
        if not latest.success:
            return latest
        rows: list[dict[str, Any]] = []
        for order in list((latest.data or {}).get("orders") or []):
            status = _text(
                getattr(order, "shipmentPackageStatus", None)
                or getattr(order, "status", None)
                or "Unknown"
            )
            if _normalized_key(status) in terminal:
                continue
            order_number = _text(getattr(order, "orderNumber", ""))
            if not order_number:
                continue
            rows.append(
                {
                    "order_number": order_number,
                    "api_account_id": getattr(order, "api_account_id", None),
                    "status": status,
                    "customer": " ".join(
                        value
                        for value in (
                            _text(getattr(order, "customerFirstName", "")),
                            _text(getattr(order, "customerLastName", "")),
                        )
                        if value
                    ),
                    "last_modified_ms": int(
                        getattr(order, "lastModifiedDate", 0) or 0
                    ),
                }
            )
        rows.sort(
            key=lambda row: (
                int(row.get("last_modified_ms") or 0),
                _text(row.get("order_number")),
            ),
            reverse=True,
        )
        bounded_limit = max(1, min(1000, int(limit or 200)))
        selected = rows[:bounded_limit]
        status_counts: dict[str, int] = {}
        for row in rows:
            status = _text(row.get("status")) or "Unknown"
            status_counts[status] = status_counts.get(status, 0) + 1
        return Result.ok(
            "Final olmayan siparisler Orders domaininden getirildi.",
            close_dialog=False,
            data={
                "count": len(selected),
                "total_count": len(rows),
                "order_numbers": [row["order_number"] for row in selected],
                "orders": selected,
                "final_statuses": sorted(terminal),
                "status_counts": status_counts,
                "status_counts_complete": True,
                "truncated": len(selected) < len(rows),
                "simulated_excluded": int(
                    (latest.data or {}).get("simulated_excluded") or 0
                ),
                "account_scopes": list(
                    (latest.data or {}).get("account_scopes") or []
                ),
                "environment_by_account": dict(
                    (latest.data or {}).get("environment_by_account") or {}
                ),
                "source_revision": (latest.data or {}).get("source_revision"),
                "source_snapshot_hash": _text(
                    (latest.data or {}).get("source_snapshot_hash")
                ),
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def summarize_nonfinal_orders(
    *,
    final_statuses: list[str] | None = None,
    api_account_ids: list[int] | None = None,
    sample_limit: int = 12,
    db_name: str = DB_NAME,
) -> Result:
    """Summarize the latest snapshots outside the canonical terminal set."""

    result = list_nonfinal_orders(
        final_statuses=final_statuses,
        api_account_ids=api_account_ids,
        limit=max(1, min(1000, int(sample_limit or 12))),
        db_name=db_name,
    )
    if not result.success:
        return result
    data = dict(result.data or {})
    sample_orders = [
        {
            "order_number": _text(row.get("order_number")),
            "api_account_id": row.get("api_account_id"),
            "status": _text(row.get("status")) or "Unknown",
            "last_modified_ms": int(row.get("last_modified_ms") or 0),
        }
        for row in list(data.get("orders") or [])
        if isinstance(row, dict) and _text(row.get("order_number"))
    ]
    return Result.ok(
        "Final olmayan siparislerin durum ozeti Orders domaininde hesaplandi.",
        close_dialog=False,
        data={
            "total_count": int(data.get("total_count") or 0),
            "status_counts": dict(data.get("status_counts") or {}),
            "status_counts_complete": bool(
                data.get("status_counts_complete")
            ),
            "final_statuses": list(data.get("final_statuses") or []),
            "sample_orders": sample_orders,
            "order_numbers": [
                _text(row.get("order_number"))
                for row in sample_orders
                if _text(row.get("order_number"))
            ],
            "sample_count": len(sample_orders),
            "truncated": bool(data.get("truncated")),
            "simulated_excluded": int(data.get("simulated_excluded") or 0),
            "account_scopes": list(data.get("account_scopes") or []),
            "environment_by_account": dict(
                data.get("environment_by_account") or {}
            ),
            "source_revision": data.get("source_revision"),
            "source_snapshot_hash": _text(data.get("source_snapshot_hash")),
        },
    )


def _order_line_item_counts(
    order_rows: list[Any],
    *,
    api_account_ids: list[int] | None,
    db_name: str,
) -> Result:
    """Return per-Order line cardinality for a materialized row page."""

    order_numbers = list(
        dict.fromkeys(
            _text(getattr(row, "orderNumber", ""))
            for row in list(order_rows or [])
            if _text(getattr(row, "orderNumber", ""))
        )
    )
    item_count_by_order: dict[tuple[int | None, str], int] = {}
    if order_numbers:
        item_result = get_latest_order_items_by_numbers(
            order_numbers,
            api_account_ids=api_account_ids,
            db_name=db_name,
        )
        if not item_result.success:
            return item_result
        for item in list((item_result.data or {}).get("items") or []):
            key = (
                getattr(item, "api_account_id", None),
                _text(getattr(item, "orderNumber", "")),
            )
            if key[1]:
                item_count_by_order[key] = (
                    item_count_by_order.get(key, 0) + 1
                )
    return Result.ok(
        "Siparis kalem sayilari Orders domaininden getirildi.",
        close_dialog=False,
        data={"item_count_by_order": item_count_by_order},
    )


def list_recent_orders(
    *,
    api_account_ids: list[int] | None = None,
    start_date_ms: int | None = None,
    end_date_ms: int | None = None,
    limit: int = 5,
    db_name: str = DB_NAME,
) -> Result:
    """Return the latest operational order projections with a stable scope."""

    try:
        latest = get_latest_orders_filtered(
            start_ms=start_date_ms,
            end_ms=end_date_ms,
            api_account_ids=api_account_ids,
            db_name=db_name,
        )
        if not latest.success:
            return latest
        source_rows = sorted(
            list((latest.data or {}).get("orders") or []),
            key=lambda row: int(getattr(row, "orderDate", 0) or 0),
            reverse=True,
        )
        bounded_limit = max(1, min(100, int(limit or 5)))
        selected = source_rows[:bounded_limit]
        item_counts = _order_line_item_counts(
            selected,
            api_account_ids=api_account_ids,
            db_name=db_name,
        )
        if not item_counts.success:
            return item_counts
        item_count_by_order = dict(
            (item_counts.data or {}).get("item_count_by_order") or {}
        )
        rows = [
            {
                "api_account_id": getattr(row, "api_account_id", None),
                "order_number": _text(getattr(row, "orderNumber", "")),
                "package_id": getattr(row, "id", None),
                "shipment_package_id": getattr(row, "shipmentPackageId", None),
                "status": _text(
                    getattr(row, "shipmentPackageStatus", None)
                    or getattr(row, "status", None)
                    or "Unknown"
                ),
                "customer": " ".join(
                    value
                    for value in (
                        _text(getattr(row, "customerFirstName", "")),
                        _text(getattr(row, "customerLastName", "")),
                    )
                    if value
                ),
                "cargo_provider": _text(getattr(row, "cargoProviderName", "")),
                "cargo_tracking_number": _text(
                    getattr(row, "cargoTrackingNumber", "")
                ),
                "total_price": _number(
                    getattr(row, "packageTotalPrice", None)
                    or getattr(row, "totalPrice", None)
                ),
                "item_count": item_count_by_order.get(
                    (
                        getattr(row, "api_account_id", None),
                        _text(getattr(row, "orderNumber", "")),
                    ),
                    0,
                ),
                "currency": _text(getattr(row, "currencyCode", "")) or "TRY",
                "order_date_ms": int(getattr(row, "orderDate", 0) or 0),
                "last_modified_ms": int(
                    getattr(row, "lastModifiedDate", 0) or 0
                ),
            }
            for row in selected
        ]
        return Result.ok(
            "Son siparisler Orders domaininden getirildi.",
            close_dialog=False,
            data={
                "orders": rows,
                "scope_rows": [
                    {
                        "order_number": row["order_number"],
                        "api_account_id": row["api_account_id"],
                    }
                    for row in rows
                    if row["order_number"]
                ],
                "listed_count": len(rows),
                "total_count": len(source_rows),
                "truncated": len(rows) < len(source_rows),
                "simulated_excluded": int(
                    (latest.data or {}).get("simulated_excluded") or 0
                ),
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def query_orders(
    *,
    query: str = "",
    order_numbers: list[str] | None = None,
    api_account_ids: list[int] | None = None,
    start_date_ms: int | None = None,
    end_date_ms: int | None = None,
    filters: dict[str, Any] | None = None,
    sort: str = "order_date_desc",
    limit: int = 10,
    offset: int = 0,
    mode: str = "list",
    db_name: str = DB_NAME,
) -> Result:
    """Search/filter latest order snapshots behind one typed domain contract."""

    try:
        clean_filters = dict(filters or {})
        clean_query = _text(query or clean_filters.get("query"))
        query_key = _search_key(clean_query)
        requested_numbers = list(
            dict.fromkeys(
                _text(value)
                for value in list(order_numbers or [])
                if _text(value)
            )
        )
        status_value = _text(
            clean_filters.get("status") or clean_filters.get("shipment_status")
        )
        statuses = [
            _text(value)
            for value in (
                [status_value]
                if status_value
                else list(
                    clean_filters.get("statuses")
                    or clean_filters.get("status_in")
                    or []
                )
            )
            if _text(value)
        ]
        platform_code = canonical_platform_code(
            clean_filters.get("platform_code")
            or clean_filters.get("platform")
            or clean_filters.get("source")
            or ""
        )
        latest = get_latest_orders_filtered(
            shipment_statuses=statuses or None,
            platform_codes=[platform_code] if platform_code else None,
            start_ms=start_date_ms,
            end_ms=end_date_ms,
            order_numbers=requested_numbers or None,
            api_account_ids=api_account_ids,
            db_name=db_name,
        )
        if not latest.success:
            return latest
        rows = list((latest.data or {}).get("orders") or [])
        cargo_provider = _search_key(
            clean_filters.get("cargo_provider") or clean_filters.get("cargo")
        )
        customer = _search_key(clean_filters.get("customer"))
        min_total = clean_filters.get("min_total_price")
        max_total = clean_filters.get("max_total_price")
        min_value = _number(min_total) if min_total not in (None, "") else None
        max_value = _number(max_total) if max_total not in (None, "") else None
        exclude_cancelled = bool(clean_filters.get("exclude_cancelled", False))
        # Identity-looking tokens create a strict lookup boundary. Extract them
        # from the normalized raw sentence so ordinary words are never joined
        # into one synthetic identifier (for example "show delivered order").
        normalized_query = _normalized_key(clean_query)
        query_identifiers = [
            _search_key(value)
            for value in re.findall(
                r"\b(?:ord|order)[-_]?[a-z0-9_-]+\b|\b\d{6,}\b",
                normalized_query,
            )
        ]
        terms = [token for token in query_key.split() if len(token) >= 2]
        scored: list[tuple[int, Any]] = []
        for row in rows:
            status = _order_status(row)
            if exclude_cancelled and (
                "cancel" in status.casefold() or "iptal" in status.casefold()
            ):
                continue
            if cargo_provider and cargo_provider not in _search_key(
                getattr(row, "cargoProviderName", "")
            ):
                continue
            customer_text = _search_key(
                " ".join(
                    (
                        _text(getattr(row, "customerFirstName", "")),
                        _text(getattr(row, "customerLastName", "")),
                        _text(getattr(row, "customerEmail", "")),
                    )
                )
            )
            if customer and customer not in customer_text:
                continue
            total = _number(
                getattr(row, "packageTotalPrice", None)
                or getattr(row, "totalPrice", None)
            )
            if min_value is not None and total < min_value:
                continue
            if max_value is not None and total > max_value:
                continue
            identifiers = [
                _search_key(value)
                for value in (
                    getattr(row, "orderNumber", ""),
                    getattr(row, "id", ""),
                    getattr(row, "shipmentPackageId", ""),
                    getattr(row, "cargoTrackingNumber", ""),
                    getattr(row, "cargoSenderNumber", ""),
                )
                if _text(value)
            ]
            haystack = " ".join(
                _search_key(value)
                for value in (
                    *identifiers,
                    getattr(row, "cargoProviderName", ""),
                    getattr(row, "customerFirstName", ""),
                    getattr(row, "customerLastName", ""),
                    getattr(row, "customerEmail", ""),
                    status,
                )
                if _text(value)
            )
            haystack_tokens = set(haystack.split())
            score = 0
            if query_key:
                if query_identifiers and not any(
                    query_identifier == identifier
                    or identifier.startswith(query_identifier)
                    for identifier in identifiers
                    for query_identifier in query_identifiers
                ):
                    continue
                for identifier in identifiers:
                    if query_key == identifier:
                        score += 1000
                    elif identifier and identifier in query_key:
                        score += 800
                if query_key in haystack:
                    score += 30
                # Natural-language filler must not select an unrelated order
                # merely because a two-letter fragment occurs inside a name.
                # Customer, carrier and status lookup terms match whole tokens.
                score += sum(4 for term in terms if term in haystack_tokens)
                if score <= 0:
                    continue
            scored.append((score, row))

        clean_sort = _text(sort).casefold() or "order_date_desc"
        reverse = not clean_sort.endswith("_asc")
        if clean_sort in {"relevance", "relevance_desc"} or query_key:
            scored.sort(
                key=lambda pair: (
                    pair[0],
                    int(getattr(pair[1], "orderDate", 0) or 0),
                ),
                reverse=True,
            )
        elif clean_sort.startswith(("total_price", "price", "amount")):
            scored.sort(
                key=lambda pair: (
                    _number(
                        getattr(pair[1], "packageTotalPrice", None)
                        or getattr(pair[1], "totalPrice", None)
                    ),
                    int(getattr(pair[1], "orderDate", 0) or 0),
                ),
                reverse=reverse,
            )
        elif clean_sort.startswith(("last_modified", "modified")):
            scored.sort(
                key=lambda pair: int(
                    getattr(pair[1], "lastModifiedDate", 0) or 0
                ),
                reverse=reverse,
            )
        else:
            scored.sort(
                key=lambda pair: int(getattr(pair[1], "orderDate", 0) or 0),
                reverse=reverse,
            )
        bounded_limit = max(1, min(500, int(limit or 10)))
        clean_offset = max(0, int(offset or 0))
        clean_mode = _text(mode).casefold() or "list"
        if clean_mode == "snapshot":
            if len(scored) > 10_000:
                return Result.fail("Sipariş snapshot sınırı 10.000 kayıt; tarih veya mağaza kapsamını daralt.", close_dialog=False,
                                   data={"total_count": len(scored), "snapshot_limit": 10_000, "complete": False})
            bounded_limit, clean_offset = 10_000, 0
        if clean_mode not in {"list", "top", "count", "summary", "snapshot"}:
            clean_mode = "list"
        page_rows = [row for _score, row in scored[clean_offset : clean_offset + bounded_limit]]
        item_counts = _order_line_item_counts(
            page_rows,
            api_account_ids=api_account_ids,
            db_name=db_name,
        )
        if not item_counts.success:
            return item_counts
        item_count_by_order = dict(
            (item_counts.data or {}).get("item_count_by_order") or {}
        )
        out_rows = []
        for row in page_rows:
            projection = _order_projection(row)
            projection["item_count"] = item_count_by_order.get(
                (
                    getattr(row, "api_account_id", None),
                    _text(getattr(row, "orderNumber", "")),
                ),
                0,
            )
            out_rows.append(projection)
        source_rows = [
            _order_selection_projection(row)
            for _score, row in scored
        ]
        query_fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "operation": "orders.query",
                    "query": clean_query,
                    "order_numbers": requested_numbers,
                    "api_account_ids": sorted(
                        int(value)
                        for value in list(api_account_ids or [])
                        if value not in (None, "")
                    ),
                    "start_date_ms": start_date_ms,
                    "end_date_ms": end_date_ms,
                    "filters": clean_filters,
                    "sort": clean_sort,
                    "mode": clean_mode,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        source_snapshot_hash = _order_source_snapshot_hash(source_rows)
        source_revision = _order_source_revision(source_rows)
        status_counts: dict[str, int] = {}
        total_amount = 0.0
        for _score, row in scored:
            status = _order_status(row)
            status_counts[status] = status_counts.get(status, 0) + 1
            total_amount += _number(
                getattr(row, "packageTotalPrice", None)
                or getattr(row, "totalPrice", None)
            )
        if clean_mode == "count":
            out_rows = []
        return Result.ok(
            "Siparis sorgusu Orders domaininde tamamlandi.",
            close_dialog=False,
            data={
                "query": clean_query,
                "order_numbers": requested_numbers,
                "filters": clean_filters,
                "sort": clean_sort,
                "mode": clean_mode,
                "count": len(scored),
                "total_count": len(scored),
                "orders": out_rows,
                "scope_rows": [
                    {
                        "order_number": row["order_number"],
                        "api_account_id": row["api_account_id"],
                    }
                    for row in out_rows
                    if row["order_number"]
                ],
                "pagination": {
                    "offset": clean_offset,
                    "limit": bounded_limit,
                    "page": (clean_offset // bounded_limit) + 1,
                    "page_size": bounded_limit,
                    "total_pages": max(1, (len(scored) + bounded_limit - 1) // bounded_limit),
                    "returned": len(out_rows),
                },
                "total_amount": round(total_amount, 2),
                "status_counts": status_counts,
                "truncated": clean_offset + len(out_rows) < len(scored),
                "simulated_excluded": int(
                    (latest.data or {}).get("simulated_excluded") or 0
                ),
                "query_fingerprint": query_fingerprint,
                "source_revision": source_revision,
                "source_snapshot_hash": source_snapshot_hash,
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def query_return_claims(
    *,
    query: str = "",
    claim_ids: list[str] | None = None,
    api_account_ids: list[int] | None = None,
    start_date_ms: int | None = None,
    end_date_ms: int | None = None,
    filters: dict[str, Any] | None = None,
    sort: str = "claim_date_desc",
    limit: int = 10,
    offset: int = 0,
    mode: str = "list",
    db_name: str = DB_NAME,
) -> Result:
    """Search/filter latest return snapshots behind one typed contract."""

    try:
        clean_filters = dict(filters or {})
        clean_query = _text(query or clean_filters.get("query"))
        query_key = _search_key(clean_query)
        requested_claim_ids = list(
            dict.fromkeys(
                _text(value)
                for value in list(claim_ids or [])
                if _text(value)
            )
        )
        status_value = _text(
            clean_filters.get("status")
            or clean_filters.get("claim_item_status")
        )
        statuses = [
            _text(value)
            for value in (
                [status_value]
                if status_value
                else list(
                    clean_filters.get("statuses")
                    or clean_filters.get("status_in")
                    or []
                )
            )
            if _text(value)
        ]
        if bool(
            clean_filters.get("actionable")
            or clean_filters.get("waiting_action_only")
        ):
            statuses = ["WaitingInAction"]
        platform_code = canonical_platform_code(
            clean_filters.get("platform_code")
            or clean_filters.get("platform")
            or clean_filters.get("source")
            or ""
        )
        latest = get_latest_return_claims_filtered(
            start_ms=start_date_ms,
            end_ms=end_date_ms,
            claim_statuses=statuses or None,
            platform_codes=[platform_code] if platform_code else None,
            claim_ids=requested_claim_ids or None,
            api_account_ids=api_account_ids,
            db_name=db_name,
        )
        if not latest.success:
            return latest
        rows = list((latest.data or {}).get("claims") or [])
        order_number = _search_key(clean_filters.get("order_number"))
        claim_id_filter = _search_key(clean_filters.get("claim_id"))
        cargo_provider = _search_key(
            clean_filters.get("cargo_provider") or clean_filters.get("cargo")
        )
        min_total = clean_filters.get("min_total_price")
        max_total = clean_filters.get("max_total_price")
        min_value = _number(min_total) if min_total not in (None, "") else None
        max_value = _number(max_total) if max_total not in (None, "") else None
        normalized_query = _normalized_key(clean_query)
        query_identifiers = [
            _search_key(value)
            for value in re.findall(
                r"\b(?:claim|clm|ord|order)[-_]?[a-z0-9_-]+\b|"
                r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b|"
                r"\b\d{6,}\b",
                normalized_query,
            )
        ]
        terms = [token for token in query_key.split() if len(token) >= 2]
        scored: list[tuple[int, Any]] = []
        for row in rows:
            if order_number and order_number != _search_key(
                getattr(row, "orderNumber", "")
            ):
                continue
            if claim_id_filter and claim_id_filter != _search_key(
                getattr(row, "claimId", "")
            ):
                continue
            if cargo_provider and cargo_provider not in _search_key(
                getattr(row, "cargoProviderName", "")
            ):
                continue
            total = _number(getattr(row, "totalPrice", None))
            if min_value is not None and total < min_value:
                continue
            if max_value is not None and total > max_value:
                continue
            identifiers = [
                _search_key(value)
                for value in (
                    getattr(row, "claimId", ""),
                    getattr(row, "claimNumber", ""),
                    getattr(row, "orderNumber", ""),
                    getattr(row, "cargoTrackingNumber", ""),
                )
                if _text(value)
            ]
            haystack = " ".join(
                _search_key(value)
                for value in (
                    *identifiers,
                    getattr(row, "cargoProviderName", ""),
                    getattr(row, "customerFirstName", ""),
                    getattr(row, "customerLastName", ""),
                    getattr(row, "claimItemStatus", ""),
                    getattr(row, "claimReason", ""),
                )
                if _text(value)
            )
            haystack_tokens = set(haystack.split())
            score = 0
            if query_key:
                if query_identifiers and not any(
                    query_identifier == identifier
                    or identifier.startswith(query_identifier)
                    for identifier in identifiers
                    for query_identifier in query_identifiers
                ):
                    continue
                for identifier in identifiers:
                    if query_key == identifier:
                        score += 1000
                    elif identifier and identifier in query_key:
                        score += 800
                if query_key in haystack:
                    score += 30
                score += sum(4 for term in terms if term in haystack_tokens)
                if score <= 0:
                    continue
            scored.append((score, row))

        clean_sort = _text(sort).casefold() or "claim_date_desc"
        reverse = not clean_sort.endswith("_asc")
        if clean_sort in {"relevance", "relevance_desc"} or query_key:
            scored.sort(
                key=lambda pair: (
                    pair[0],
                    int(getattr(pair[1], "claimDate", 0) or 0),
                ),
                reverse=True,
            )
        elif clean_sort.startswith(("total_price", "price", "amount")):
            scored.sort(
                key=lambda pair: (
                    _number(getattr(pair[1], "totalPrice", None)),
                    int(getattr(pair[1], "claimDate", 0) or 0),
                ),
                reverse=reverse,
            )
        elif clean_sort.startswith(("last_modified", "modified")):
            scored.sort(
                key=lambda pair: int(
                    getattr(pair[1], "lastModifiedDate", 0) or 0
                ),
                reverse=reverse,
            )
        else:
            scored.sort(
                key=lambda pair: int(getattr(pair[1], "claimDate", 0) or 0),
                reverse=reverse,
            )
        bounded_limit = max(1, min(500, int(limit or 10)))
        clean_offset = max(0, int(offset or 0))
        page_rows = [
            row
            for _score, row in scored[
                clean_offset : clean_offset + bounded_limit
            ]
        ]
        out_rows = [_return_claim_projection(row) for row in page_rows]
        status_counts: dict[str, int] = {}
        total_amount = 0.0
        actionable_count = 0
        for _score, row in scored:
            status = _text(getattr(row, "claimItemStatus", "")) or "Unknown"
            status_counts[status] = status_counts.get(status, 0) + 1
            total_amount += _number(getattr(row, "totalPrice", None))
            actionable_count += int(status == "WaitingInAction")
        clean_mode = _text(mode).casefold() or "list"
        if clean_mode not in {"list", "top", "count", "summary"}:
            clean_mode = "list"
        if clean_mode == "count":
            out_rows = []
        return Result.ok(
            "Iade sorgusu Orders domaininde tamamlandi.",
            close_dialog=False,
            data={
                "query": clean_query,
                "claim_ids": requested_claim_ids,
                "filters": clean_filters,
                "sort": clean_sort,
                "mode": clean_mode,
                "count": len(scored),
                "total_count": len(scored),
                "returns": out_rows,
                "scope_rows": [
                    {
                        "claim_id": row["claim_id"],
                        "api_account_id": row["api_account_id"],
                    }
                    for row in out_rows
                    if row["claim_id"]
                ],
                "pagination": {
                    "offset": clean_offset,
                    "limit": bounded_limit,
                    "page": (clean_offset // bounded_limit) + 1,
                    "page_size": bounded_limit,
                    "total_pages": max(
                        1,
                        (len(scored) + bounded_limit - 1) // bounded_limit,
                    ),
                    "returned": len(out_rows),
                },
                "actionable_count": actionable_count,
                "total_amount": round(total_amount, 2),
                "status_counts": status_counts,
                "truncated": clean_offset + len(out_rows) < len(scored),
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def reconcile_return_snapshot(
    *,
    observed_claim_ids: list[str] | None = None,
    snapshot_complete: bool = False,
    api_account_ids: list[int] | None = None,
    start_date_ms: int | None = None,
    end_date_ms: int | None = None,
    start_last_modified_ms: int | None = None,
    end_last_modified_ms: int | None = None,
    filters: dict[str, Any] | None = None,
    limit: int = 100,
    db_name: str = DB_NAME,
) -> Result:
    """Compare latest local return claims with a complete remote identity set."""

    try:
        clean_filters = dict(filters or {})
        scoped_accounts = list(api_account_ids or [])
        if not scoped_accounts:
            scoped_accounts = [
                int(value)
                for value in list(
                    clean_filters.get("api_account_ids")
                    or clean_filters.get("account_ids")
                    or []
                )
                if _text(value).isdigit()
            ]
        status = _text(
            clean_filters.get("status")
            or clean_filters.get("claim_item_status")
        )
        latest = get_latest_return_claims_filtered(
            start_ms=start_date_ms,
            end_ms=end_date_ms,
            claim_statuses=[status] if status else None,
            api_account_ids=scoped_accounts or None,
            db_name=db_name,
        )
        if not latest.success:
            return latest
        order_number = _search_key(clean_filters.get("order_number"))
        local_records = []
        for row in list((latest.data or {}).get("claims") or []):
            modified = int(getattr(row, "lastModifiedDate", 0) or 0)
            if (
                start_last_modified_ms is not None
                and modified < int(start_last_modified_ms)
            ):
                continue
            if (
                end_last_modified_ms is not None
                and modified > int(end_last_modified_ms)
            ):
                continue
            if order_number and order_number != _search_key(
                getattr(row, "orderNumber", "")
            ):
                continue
            local_records.append(row)
        local_records.sort(
            key=lambda row: int(getattr(row, "lastModifiedDate", 0) or 0),
            reverse=True,
        )
        local_rows = [_return_claim_projection(row) for row in local_records]
        local_ids = {
            _text(row.get("claim_id"))
            for row in local_rows
            if _text(row.get("claim_id"))
        }
        observed_ids = {
            _text(value)
            for value in list(observed_claim_ids or [])
            if _text(value)
        }
        bounded_limit = max(1, min(500, int(limit or 100)))
        scope_rows = [
            {
                "claim_id": row.get("claim_id"),
                "api_account_id": row.get("api_account_id"),
            }
            for row in local_rows
            if row.get("claim_id")
        ]
        if not observed_ids and not snapshot_complete:
            return Result.ok(
                "Lokal iadeler hazir; tam remote snapshot bekleniyor.",
                close_dialog=False,
                data={
                    "needs_remote_snapshot": True,
                    "local_count": len(local_rows),
                    "observed_count": 0,
                    "stale_count": None,
                    "local_returns": local_rows[:bounded_limit],
                    "scope_rows": scope_rows,
                    "filters": clean_filters,
                    "snapshot_complete": False,
                    "truncated": len(local_rows) > bounded_limit,
                },
            )
        stale_rows = [
            row
            for row in local_rows
            if _text(row.get("claim_id")) not in observed_ids
        ]
        confirmed_rows = [
            row
            for row in local_rows
            if _text(row.get("claim_id")) in observed_ids
        ]
        unexpected_ids = sorted(observed_ids - local_ids)
        return Result.ok(
            "Return snapshot reconciliation Orders domaininde tamamlandi.",
            close_dialog=False,
            data={
                "needs_remote_snapshot": False,
                "local_count": len(local_rows),
                "observed_count": len(observed_ids),
                "stale_count": len(stale_rows),
                "confirmed_count": len(confirmed_rows),
                "unexpected_remote_count": len(unexpected_ids),
                "stale_returns": stale_rows[:bounded_limit],
                "confirmed_returns": confirmed_rows[:bounded_limit],
                "unexpected_remote_claim_ids": unexpected_ids[:bounded_limit],
                "scope_rows": scope_rows,
                "filters": clean_filters,
                "snapshot_complete": bool(snapshot_complete),
                "truncated": any(
                    len(values) > bounded_limit
                    for values in (stale_rows, confirmed_rows, unexpected_ids)
                ),
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def get_order_full_context(
    *,
    query: str = "",
    order_numbers: list[str] | None = None,
    api_account_ids: list[int] | None = None,
    limit: int | None = None,
    filters: dict[str, Any] | None = None,
    start_date_ms: int | None = None,
    end_date_ms: int | None = None,
    sort: str = "order_date_desc",
    offset: int = 0,
    db_name: str = DB_NAME,
) -> Result:
    """Compose the canonical order, header, item and return read model."""

    try:
        default_limit = len(set(order_numbers or [])) if order_numbers else 5
        bounded_limit = max(1, min(100, int(limit or default_limit)))
        selected = query_orders(
            query=query,
            order_numbers=order_numbers,
            api_account_ids=api_account_ids,
            filters=filters,
            start_date_ms=start_date_ms,
            end_date_ms=end_date_ms,
            sort="relevance" if query else sort,
            limit=bounded_limit,
            offset=offset,
            mode="list",
            db_name=db_name,
        )
        if not selected.success:
            return selected
        selected_data = dict(selected.data or {})
        selected_rows = [
            dict(row)
            for row in list(selected_data.get("orders") or [])
            if isinstance(row, dict) and _text(row.get("order_number"))
        ]
        contexts: list[dict[str, Any]] = []
        scope_rows: list[dict[str, Any]] = []
        for selected_row in selected_rows:
            order_number = _text(selected_row.get("order_number"))
            account_id = selected_row.get("api_account_id")
            resolved = resolve_order_record(
                order_number,
                api_account_id=(
                    int(account_id) if account_id not in (None, "") else None
                ),
                db_name=db_name,
            )
            if not resolved.success:
                return resolved
            order = (resolved.data or {}).get("record")
            if order is None:
                return Result.fail(
                    f"Siparis baglami cozulmedi: {order_number}",
                    close_dialog=False,
                )
            scoped_accounts = (
                [int(account_id)] if account_id not in (None, "") else None
            )
            headers = list_order_headers(
                [order_number],
                api_account_ids=scoped_accounts,
                db_name=db_name,
            )
            items = list_order_items(
                [order_number],
                api_account_ids=scoped_accounts,
                db_name=db_name,
            )
            claims = list_return_claims(
                order_numbers=[order_number],
                api_account_ids=scoped_accounts,
                active=True,
                db_name=db_name,
            )
            for domain_result in (headers, items, claims):
                if not domain_result.success:
                    return domain_result

            header_rows = list((headers.data or {}).get("records") or [])
            header = header_rows[0] if header_rows else None
            latest_items: dict[Any, Any] = {}
            for item in list((items.data or {}).get("records") or []):
                key = (
                    getattr(item, "lineId", None)
                    or getattr(item, "id", None)
                    or getattr(item, "pk", None)
                )
                if key not in latest_items:
                    latest_items[key] = item
            latest_claims: dict[str, Any] = {}
            for claim in list((claims.data or {}).get("records") or []):
                claim_id = _text(getattr(claim, "claimId", ""))
                if claim_id and claim_id not in latest_claims:
                    latest_claims[claim_id] = claim

            account = getattr(order, "api_account", None)
            order_projection = _order_projection(order)
            order_projection.update(
                {
                    "cargo_sender_number": _text(
                        getattr(order, "cargoSenderNumber", "")
                    ),
                    "cargo_tracking_link": _text(
                        getattr(order, "cargoTrackingLink", "")
                    ),
                    "customer_email": _text(getattr(order, "customerEmail", "")),
                    "account": _text(
                        getattr(account, "comp_name", "")
                        or getattr(account, "account_id", "")
                    )
                    if account is not None
                    else "",
                    "platform": _text(getattr(account, "platform", ""))
                    if account is not None
                    else "",
                }
            )
            return_rows = [
                _return_claim_projection(claim)
                for claim in latest_claims.values()
            ]
            contexts.append(
                {
                    "order": order_projection,
                    "header": {
                        "exists": header is not None,
                        "is_printed": bool(getattr(header, "is_printed", False))
                        if header is not None
                        else False,
                        "is_extracted": bool(
                            getattr(header, "is_extracted", False)
                        )
                        if header is not None
                        else False,
                        "printed_at": getattr(header, "printed_at", None)
                        if header is not None
                        else None,
                        "extracted_at": getattr(header, "extracted_at", None)
                        if header is not None
                        else None,
                    },
                    "shipment_address": normalize_contact_address(
                        getattr(order, "shipmentAddress", None),
                        source="shipment",
                    ),
                    "invoice_address": normalize_contact_address(
                        getattr(order, "invoiceAddress", None),
                        source="invoice",
                    ),
                    "items": [
                        _order_item_projection(item)
                        for item in latest_items.values()
                    ],
                    "returns": return_rows,
                    "return_count": len(return_rows),
                    "waiting_return_count": sum(
                        1
                        for claim in return_rows
                        if claim.get("status") == "WaitingInAction"
                    ),
                }
            )
            scope_rows.append(
                {
                    "order_number": order_number,
                    "api_account_id": account_id,
                }
            )

        return Result.ok(
            f"{len(contexts)} siparis icin kanonik tam baglam hazirlandi.",
            close_dialog=False,
            data={
                "query": query,
                "filters": dict(filters or {}),
                "pagination": dict(selected_data.get("pagination") or {}),
                "order_numbers": [
                    _text((context.get("order") or {}).get("order_number"))
                    for context in contexts
                ],
                "count": len(contexts),
                "listed_count": len(contexts),
                "total_count": int(selected_data.get("total_count") or len(contexts)),
                "truncated": bool(selected_data.get("truncated")),
                "contexts": contexts,
                "scope_rows": scope_rows,
                "simulated_excluded": int(
                    selected_data.get("simulated_excluded") or 0
                ),
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def build_order_product_public_identities(
    *,
    order_numbers: list[str],
    api_account_ids: list[int] | None = None,
    limit: int = 20,
    item_ordinal: int | None = None,
    research_facets: list[str] | None = None,
    db_name: str = DB_NAME,
) -> Result:
    """Project order items into web-safe public product identities without PII."""

    try:
        numbers = list(
            dict.fromkeys(
                _text(value)
                for value in list(order_numbers or [])
                if _text(value)
            )
        )
        if not numbers:
            return Result.fail(
                "Public urun identity icin exact order_numbers zorunlu.",
                close_dialog=False,
            )
        bounded_limit = max(1, min(100, int(limit or 20)))
        selected_item_ordinal = (
            max(1, min(100, int(item_ordinal)))
            if item_ordinal is not None
            else None
        )
        normalized_research_facets = list(
            dict.fromkeys(
                _text(value).casefold()
                for value in list(research_facets or [])
                if _text(value).casefold() in {"user_opinions"}
            )
        )
        context_result = get_order_full_context(
            order_numbers=numbers,
            api_account_ids=api_account_ids,
            limit=min(20, len(numbers)),
            db_name=db_name,
        )
        if not context_result.success:
            return context_result
        contexts = [
            dict(row)
            for row in list((context_result.data or {}).get("contexts") or [])
            if isinstance(row, dict)
        ]
        identities: list[dict[str, Any]] = []
        seen: set[str] = set()
        for context in contexts:
            order = dict(context.get("order") or {})
            marketplace = _text(order.get("platform_code") or order.get("platform"))
            for item_index, item in enumerate(
                list(context.get("items") or []),
                start=1,
            ):
                if (
                    selected_item_ordinal is not None
                    and item_index != selected_item_ordinal
                ):
                    continue
                if not isinstance(item, dict):
                    continue
                public_fields = {
                    "product_name": _text(item.get("product_name")),
                    "barcode": _text(item.get("barcode")),
                    "content_id": _text(item.get("content_id")),
                    "product_code": _text(item.get("product_code")),
                    "product_size": _text(item.get("product_size")),
                    "product_color": _text(item.get("product_color")),
                    "product_origin": _text(item.get("product_origin")),
                    "marketplace": marketplace,
                }
                identity_material = "|".join(
                    public_fields[key]
                    for key in sorted(public_fields)
                )
                if not identity_material.replace("|", ""):
                    continue
                identity_id = "product_" + hashlib.sha256(
                    identity_material.encode("utf-8")
                ).hexdigest()[:20]
                if identity_id in seen:
                    continue
                seen.add(identity_id)
                policy_public_fields: list[dict[str, Any]] = []
                if public_fields["product_name"]:
                    policy_public_fields.append(
                        {
                            "field": "product_name",
                            "value": public_fields["product_name"],
                            "public": True,
                        }
                    )
                barcode = public_fields["barcode"]
                if barcode and re.fullmatch(r"[0-9]{8,14}", barcode):
                    policy_public_fields.append(
                        {"field": "barcode", "value": barcode, "public": True}
                    )
                if public_fields["product_code"]:
                    policy_public_fields.append(
                        {
                            "field": "manufacturer_code",
                            "value": public_fields["product_code"],
                            "public": True,
                        }
                    )
                public_query = " ".join(
                    dict.fromkeys(
                        _text(row.get("value"))
                        for row in policy_public_fields
                        if _text(row.get("value"))
                    )
                )
                if "user_opinions" in normalized_research_facets:
                    public_query = " ".join(
                        value
                        for value in (
                            public_query,
                            "kullanıcı yorumları değerlendirme deneyim",
                        )
                        if value
                    )
                identities.append(
                    {
                        "identity_id": identity_id,
                        **public_fields,
                        "public_query": public_query,
                        "public_product_fields": policy_public_fields,
                        "ordered_quantity": max(0, int(item.get("quantity") or 0)),
                    }
                )
                if len(identities) >= bounded_limit:
                    break
            if len(identities) >= bounded_limit:
                break
        return Result.ok(
            "Siparis kalemleri privacy-safe public urun identity'lerine donusturuldu.",
            close_dialog=False,
            data={
                "product_identities": identities,
                "primary_public_query": _text(
                    (identities[0] if identities else {}).get("public_query")
                ),
                "primary_public_product_fields": list(
                    (identities[0] if identities else {}).get("public_product_fields")
                    or []
                ),
                "identity_count": len(identities),
                "source_order_count": len(contexts),
                "contains_customer_pii": False,
                "contains_order_identifiers": False,
                "selected_item_ordinal": selected_item_ordinal,
                "research_facets": normalized_research_facets,
                "public_fields": [
                    "product_name",
                    "barcode",
                    "content_id",
                    "product_code",
                    "product_size",
                    "product_color",
                    "product_origin",
                    "marketplace",
                ],
                "web_query_public_fields": [
                    "product_name",
                    "barcode",
                    "manufacturer_code",
                ],
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def summarize_order_item_sales(
    *,
    order_numbers: list[str] | None = None,
    api_account_ids: list[int] | None = None,
    product_identities: list[dict[str, Any]] | None = None,
    start_date_ms: int | None = None,
    end_date_ms: int | None = None,
    exclude_statuses: list[str] | None = None,
    group_by: str = "product",
    limit: int = 20,
    db_name: str = DB_NAME,
) -> Result:
    """Aggregate latest canonical order/item snapshots without UI coupling.

    ``marketplace_item`` counts ordered marketplace product units from each
    latest OrderItem.quantity. A line with quantity=4 contributes four units,
    not one line. This unit establishes no conversion to a Stock item's
    physical unit (for example adet or kg).
    """

    try:
        numbers = [_text(value) for value in list(order_numbers or []) if _text(value)]
        accounts = [int(value) for value in list(api_account_ids or []) if value is not None]
        excluded = {
            _text(value).casefold()
            for value in list(
                exclude_statuses
                or ["Cancelled", "UnDeliveredAndReturned", "Returned", "UnSupplied"]
            )
            if _text(value)
        }
        clean_group = _text(group_by).casefold() or "product"
        if clean_group not in {"product", "sku", "barcode", "content_id", "product_code"}:
            return Result.fail(
                "Desteklenmeyen siparis kalemi gruplama alani.",
                close_dialog=False,
                data={"supported_group_by": ["product", "sku", "barcode", "content_id", "product_code"]},
            )
        identity_filters = [
            {
                key: _text(row.get(key))
                for key in (
                    "product_name",
                    "sku",
                    "barcode",
                    "content_id",
                    "product_code",
                )
                if _text(row.get(key))
            }
            for row in list(product_identities or [])
            if isinstance(row, dict)
        ]
        identity_filters = [row for row in identity_filters if row]
        provenance_scope = {
            "order_numbers": sorted(set(numbers)),
            "api_account_ids": sorted(set(accounts)),
            "start_date_ms": start_date_ms,
            "end_date_ms": end_date_ms,
            "excluded_statuses": sorted(excluded),
            "group_by": clean_group,
            "product_identities": identity_filters,
        }

        with Session(get_engine(db_name or DB_NAME)) as session:
            order_stmt = select(OrderData)
            if numbers:
                order_stmt = order_stmt.where(OrderData.orderNumber.in_(numbers))
            if accounts:
                order_stmt = order_stmt.where(OrderData.api_account_id.in_(accounts))
            if start_date_ms is not None:
                order_stmt = order_stmt.where(OrderData.orderDate >= int(start_date_ms))
            if end_date_ms is not None:
                order_stmt = order_stmt.where(OrderData.orderDate <= int(end_date_ms))
            order_rows = session.exec(
                order_stmt.order_by(
                    OrderData.lastModifiedDate.desc(),
                    OrderData.pk.desc(),
                )
            ).all() or []

            latest_orders: dict[tuple[int | None, str], OrderData] = {}
            for row in order_rows:
                key = (getattr(row, "api_account_id", None), _text(getattr(row, "orderNumber", "")))
                if key[1] and key not in latest_orders:
                    latest_orders[key] = row
            eligible_keys = {
                key
                for key, row in latest_orders.items()
                if _text(getattr(row, "status", "")).casefold() not in excluded
                and _text(getattr(row, "shipmentPackageStatus", "")).casefold() not in excluded
            }
            eligible_numbers = sorted({key[1] for key in eligible_keys})
            if not eligible_numbers:
                source_revision, source_snapshot_hash = (
                    _item_sales_source_provenance(
                        order_rows=[],
                        item_rows=[],
                        scope=provenance_scope,
                    )
                )
                return Result.ok(
                    "Siparis kalemi satis ozeti bos.",
                    close_dialog=False,
                    data={
                        "rows": [],
                        "group_by": clean_group,
                        "order_count": 0,
                        "matched_order_count": 0,
                        "population_order_count": 0,
                        "gross_amount_by_currency": {},
                        "total_gross_amount": 0.0,
                        "currency": "",
                        "total_quantity": 0,
                        "quantity_unit": "marketplace_item",
                        "quantity_unit_description": "Ordered marketplace product units from OrderItem.quantity; not order-line count or Stock physical units.",
                        "product_count": 0,
                        "empty_result": True,
                        "metrics_complete": True,
                        "currency_applicable": False,
                        "leading_five_quantity": 0,
                        "leading_five_quantity_share": 0.0,
                        "identity_filter_count": len(identity_filters),
                        "excluded_statuses": sorted(excluded),
                        "start_date_ms": start_date_ms,
                        "end_date_ms": end_date_ms,
                        "source_revision": source_revision,
                        "source_snapshot_hash": source_snapshot_hash,
                    },
                )

            item_stmt = select(OrderItem).where(OrderItem.orderNumber.in_(eligible_numbers))
            if accounts:
                item_stmt = item_stmt.where(OrderItem.api_account_id.in_(accounts))
            item_rows = session.exec(
                item_stmt.order_by(
                    OrderItem.snapshotLastModifiedDate.desc(),
                    OrderItem.pk.desc(),
                )
            ).all() or []

        latest_items: dict[tuple[Any, ...], OrderItem] = {}
        for row in item_rows:
            account_id = getattr(row, "api_account_id", None)
            order_number = _text(getattr(row, "orderNumber", ""))
            if (account_id, order_number) not in eligible_keys:
                continue
            line_identity = (
                getattr(row, "lineId", None)
                or getattr(row, "id", None)
                or _text(getattr(row, "barcode", ""))
                or _text(getattr(row, "sku", ""))
                or _text(getattr(row, "merchantSku", ""))
                or _text(getattr(row, "productName", ""))
            )
            key = (account_id, order_number, str(line_identity))
            if key not in latest_items:
                latest_items[key] = row

        aggregates: dict[str, dict[str, Any]] = {}
        matched_order_keys: set[tuple[int | None, str]] = set()
        for row in latest_items.values():
            sku = _text(
                getattr(row, "sku", "")
                or getattr(row, "merchantSku", "")
                or getattr(row, "stockCode", "")
            )
            barcode = _text(getattr(row, "barcode", ""))
            content_id = _text(getattr(row, "contentId", ""))
            product_code = _text(getattr(row, "productCode", ""))
            product_name = _text(getattr(row, "productName", "")) or "-"
            row_identity = {
                "product_name": product_name,
                "sku": sku,
                "barcode": barcode,
                "content_id": content_id,
                "product_code": product_code,
            }
            if identity_filters and not any(
                any(
                    _text(row_identity.get(key)).casefold()
                    == _text(value).casefold()
                    for key, value in identity_filter.items()
                    if _text(value) and _text(row_identity.get(key))
                )
                for identity_filter in identity_filters
            ):
                continue
            matched_order_keys.add(
                (
                    getattr(row, "api_account_id", None),
                    _text(getattr(row, "orderNumber", "")),
                )
            )
            identity_by_group = {
                "sku": sku,
                "barcode": barcode,
                "content_id": content_id,
                "product_code": product_code,
                "product": content_id or product_code or barcode or sku or product_name.casefold(),
            }
            identity = identity_by_group[clean_group] or product_name.casefold()
            quantity = max(0, int(getattr(row, "quantity", 0) or 0))
            gross_value = getattr(row, "lineGrossAmount", None)
            if gross_value is None:
                gross_value = getattr(row, "amount", None)
            if gross_value is None:
                gross_value = float(getattr(row, "price", 0) or 0) * quantity
            bucket = aggregates.setdefault(
                identity,
                {
                    "identity": identity,
                    "product_name": product_name,
                    "sku": sku,
                    "barcode": barcode,
                    "content_id": content_id,
                    "product_code": product_code,
                    "currency": _text(getattr(row, "currencyCode", "")) or "TRY",
                    "quantity": 0,
                    "quantity_unit": "marketplace_item",
                    "order_numbers": set(),
                    "gross_amount": 0.0,
                },
            )
            bucket["quantity"] += quantity
            bucket["order_numbers"].add(_text(getattr(row, "orderNumber", "")))
            bucket["gross_amount"] += float(gross_value or 0)

        result_rows: list[dict[str, Any]] = []
        for bucket in aggregates.values():
            result_rows.append(
                {
                    **{key: value for key, value in bucket.items() if key != "order_numbers"},
                    "order_count": len(bucket["order_numbers"]),
                    "gross_amount": round(float(bucket["gross_amount"]), 2),
                }
            )
        result_rows.sort(
            key=lambda row: (-int(row.get("quantity") or 0), -float(row.get("gross_amount") or 0), str(row.get("identity") or ""))
        )
        bounded_limit = max(1, min(500, int(limit or 20)))
        source_revision, source_snapshot_hash = _item_sales_source_provenance(
            order_rows=[
                latest_orders[key]
                for key in sorted(
                    eligible_keys,
                    key=lambda value: (
                        int(value[0] or 0),
                        _text(value[1]),
                    ),
                )
            ],
            item_rows=list(latest_items.values()),
            scope=provenance_scope,
        )
        total_quantity = sum(int(row.get("quantity") or 0) for row in result_rows)
        leading_five_quantity = sum(
            int(row.get("quantity") or 0) for row in result_rows[:5]
        )
        leading_five_quantity_share = (
            round((leading_five_quantity / total_quantity) * 100.0, 2)
            if total_quantity
            else 0.0
        )
        gross_amount_by_currency: dict[str, float] = {}
        for row in result_rows:
            currency = _text(row.get("currency")) or "TRY"
            gross_amount_by_currency[currency] = (
                gross_amount_by_currency.get(currency, 0.0)
                + float(row.get("gross_amount") or 0.0)
            )
        gross_amount_by_currency = {
            currency: round(amount, 2)
            for currency, amount in sorted(gross_amount_by_currency.items())
        }
        single_currency = (
            next(iter(gross_amount_by_currency))
            if len(gross_amount_by_currency) == 1
            else ""
        )
        return Result.ok(
            "Siparis kalemi satis ozeti hazirlandi.",
            close_dialog=False,
            data={
                "rows": result_rows[:bounded_limit],
                "group_by": clean_group,
                # ``order_count`` always describes the returned result scope.
                # With an identity filter it is the number of distinct orders
                # containing any matching alias, not the whole eligible order
                # population and not a naive sum of per-alias row counts.
                "order_count": (
                    len(matched_order_keys)
                    if identity_filters
                    else len(eligible_keys)
                ),
                "matched_order_count": len(matched_order_keys),
                "population_order_count": len(eligible_keys),
                "gross_amount_by_currency": gross_amount_by_currency,
                "total_gross_amount": (
                    gross_amount_by_currency[single_currency]
                    if single_currency
                    else 0.0
                    if not result_rows
                    else None
                ),
                "currency": single_currency,
                "product_count": len(result_rows),
                "total_quantity": total_quantity,
                "quantity_unit": "marketplace_item",
                "quantity_unit_description": "Ordered marketplace product units from OrderItem.quantity; not order-line count or Stock physical units.",
                "empty_result": not bool(result_rows),
                "metrics_complete": True,
                "currency_applicable": bool(single_currency),
                "leading_five_quantity": leading_five_quantity,
                "leading_five_quantity_share": leading_five_quantity_share,
                "truncated": len(result_rows) > bounded_limit,
                "identity_filter_count": len(identity_filters),
                "excluded_statuses": sorted(excluded),
                "start_date_ms": start_date_ms,
                "end_date_ms": end_date_ms,
                "source_revision": source_revision,
                "source_snapshot_hash": source_snapshot_hash,
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def build_order_item_sales_report_snapshot(
    *,
    order_numbers: list[str] | None = None,
    api_account_ids: list[int] | None = None,
    start_date_ms: int | None = None,
    end_date_ms: int | None = None,
    exclude_statuses: list[str] | None = None,
    group_by: str = "product",
    limit: int = 100,
    period_label: str = "Secili donem",
    db_name: str = DB_NAME,
) -> Result:
    """Build an immutable, privacy-minimal report from canonical Orders data."""

    try:
        summary = summarize_order_item_sales(
            order_numbers=order_numbers,
            api_account_ids=api_account_ids,
            start_date_ms=start_date_ms,
            end_date_ms=end_date_ms,
            exclude_statuses=exclude_statuses,
            group_by=group_by,
            limit=limit,
            db_name=db_name,
        )
        if not summary.success:
            return summary
        data = dict(summary.data or {})
        rows = [dict(row) for row in list(data.get("rows") or []) if isinstance(row, dict)]
        clean_period_label = _text(period_label) or "Secili donem"
        summary_rows = [
            {"metric": "Donem", "value": clean_period_label},
            {"metric": "Kapsamdaki siparis", "value": str(int(data.get("order_count") or 0))},
            {"metric": "Urun/grup", "value": str(int(data.get("product_count") or 0))},
            {"metric": "Toplam adet", "value": str(int(data.get("total_quantity") or 0))},
            {
                "metric": "Ilk 5 urun adedi",
                "value": str(int(data.get("leading_five_quantity") or 0)),
            },
            {
                "metric": "Ilk 5 urun payi (%)",
                "value": str(float(data.get("leading_five_quantity_share") or 0.0)),
            },
            {"metric": "Gruplama", "value": _text(data.get("group_by"))},
            {
                "metric": "Haric tutulan durumlar",
                "value": ", ".join(str(value) for value in list(data.get("excluded_statuses") or [])),
            },
        ]
        detail_rows = [
            {
                "rank": index,
                "product_name": _text(row.get("product_name")) or "-",
                "sku": _text(row.get("sku")),
                "barcode": _text(row.get("barcode")),
                "content_id": _text(row.get("content_id")),
                "product_code": _text(row.get("product_code")),
                "quantity": int(row.get("quantity") or 0),
                "order_count": int(row.get("order_count") or 0),
                "gross_amount": round(float(row.get("gross_amount") or 0.0), 2),
                "currency": _text(row.get("currency")) or "TRY",
            }
            for index, row in enumerate(rows, start=1)
        ]
        sheets = (
            make_report_sheet(
                name="Rapor Ozeti",
                columns=(
                    ReportColumn("metric", "Ölçüm", width=30),
                    ReportColumn("value", "Değer", width=46),
                ),
                rows=summary_rows,
            ),
            make_report_sheet(
                name="En Cok Satanlar",
                columns=(
                    ReportColumn("rank", "Sıra", data_type="integer", number_format="0", width=9),
                    ReportColumn("product_name", "Ürün", width=46),
                    ReportColumn("sku", "SKU", number_format="@", width=22),
                    ReportColumn("barcode", "Barkod", number_format="@", width=22),
                    ReportColumn("content_id", "Content ID", number_format="@", width=18),
                    ReportColumn("product_code", "Ürün Kodu", number_format="@", width=18),
                    ReportColumn("quantity", "Satılan Adet", data_type="integer", number_format="0", width=14),
                    ReportColumn("order_count", "Sipariş Sayısı", data_type="integer", number_format="0", width=15),
                    ReportColumn("gross_amount", "Brüt Tutar", data_type="number", number_format="#,##0.00", width=16),
                    ReportColumn("currency", "Para Birimi", width=12),
                ),
                rows=detail_rows,
            ),
        )
        snapshot = ReportSnapshot.create(
            title=f"{clean_period_label} En Çok Satan Ürünler",
            source_domain="orders",
            report_type="orders.item_sales",
            filters={
                "start_date_ms": start_date_ms,
                "end_date_ms": end_date_ms,
                "api_account_ids": [int(value) for value in list(api_account_ids or [])],
                "explicit_order_count": len(list(order_numbers or [])),
                "group_by": _text(data.get("group_by")),
                "limit": max(1, min(500, int(limit or 100))),
                "excluded_statuses": list(data.get("excluded_statuses") or []),
            },
            metadata={
                "period_label": clean_period_label,
                "order_count": int(data.get("order_count") or 0),
                "product_count": int(data.get("product_count") or 0),
                "total_quantity": int(data.get("total_quantity") or 0),
                "leading_five_quantity": int(
                    data.get("leading_five_quantity") or 0
                ),
                "leading_five_quantity_share": float(
                    data.get("leading_five_quantity_share") or 0.0
                ),
                "row_count": len(detail_rows),
                "truncated": bool(data.get("truncated")),
                "contains_customer_pii": False,
            },
            sheets=sheets,
        )
        return Result.ok(
            "Siparis kalemi satis raporu immutable snapshot olarak hazirlandi.",
            close_dialog=False,
            data={
                "report_snapshot": snapshot.to_dict(),
                "snapshot_id": snapshot.snapshot_id,
                "content_hash": snapshot.content_hash,
                "row_count": len(detail_rows),
                "order_count": int(data.get("order_count") or 0),
                "product_count": int(data.get("product_count") or 0),
                "total_quantity": int(data.get("total_quantity") or 0),
                "leading_five_quantity": int(
                    data.get("leading_five_quantity") or 0
                ),
                "leading_five_quantity_share": float(
                    data.get("leading_five_quantity_share") or 0.0
                ),
                "contains_customer_pii": False,
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def summarize_return_reasons(
    *,
    claim_ids: list[str] | None = None,
    order_numbers: list[str] | None = None,
    api_account_ids: list[int] | None = None,
    active: bool | None = True,
    statuses: list[str] | None = None,
    start_date_ms: int | None = None,
    end_date_ms: int | None = None,
    limit: int = 20,
    db_name: str = DB_NAME,
) -> Result:
    """Aggregate exact selected return claims by their canonical reason fields."""

    claims_result = list_return_claims(
        claim_ids=claim_ids,
        order_numbers=order_numbers,
        api_account_ids=api_account_ids,
        active=active,
        statuses=statuses,
        start_date_ms=start_date_ms,
        end_date_ms=end_date_ms,
        db_name=db_name,
    )
    if not claims_result.success:
        return claims_result
    latest: dict[tuple[int | None, str], ReturnClaim] = {}
    for row in list((claims_result.data or {}).get("records") or []):
        key = (getattr(row, "api_account_id", None), _text(getattr(row, "claimId", "")))
        if key[1] and key not in latest:
            latest[key] = row
    reason_rows: dict[str, dict[str, Any]] = {}
    without_reason = 0
    multi_reason_claims = 0
    for row in latest.values():
        reasons = [
            _text(value)
            for value in list(getattr(row, "claimReasons", None) or [])
            if _text(value)
        ]
        if not reasons and _text(getattr(row, "claimReason", "")):
            reasons = [
                _text(value)
                for value in re.split(
                    r"\s*(?:\||;|\r?\n)\s*",
                    _text(getattr(row, "claimReason", "")),
                )
                if _text(value)
            ]
        distinct_reasons: dict[str, str] = {}
        for reason in reasons:
            normalized = _normalized_key(reason)
            if normalized:
                distinct_reasons.setdefault(normalized, re.sub(r"\s+", " ", _text(reason)))
        reasons = list(distinct_reasons.values())
        if not reasons:
            without_reason += 1
            continue
        multi_reason_claims += int(len(reasons) > 1)
        for reason in reasons:
            normalized_reason = _normalized_key(reason)
            bucket = reason_rows.setdefault(
                normalized_reason,
                {
                    "reason": reason,
                    "normalized_reason": normalized_reason,
                    "claim_count": 0,
                    "item_count": 0,
                    "claim_ids": [],
                },
            )
            bucket["claim_count"] += 1
            bucket["item_count"] += max(0, int(getattr(row, "itemCount", 0) or 0))
            bucket["claim_ids"].append(_text(getattr(row, "claimId", "")))
    rows = sorted(
        reason_rows.values(),
        key=lambda row: (-int(row.get("claim_count") or 0), -int(row.get("item_count") or 0), str(row.get("reason") or "")),
    )
    bounded_limit = max(1, min(200, int(limit or 20)))
    total_claims = len(latest)
    claims_with_reason = max(0, total_claims - without_reason)
    reason_occurrence_count = sum(int(row.get("claim_count") or 0) for row in rows)
    selected = rows[:bounded_limit]
    selected_claim_ids = {
        claim_id
        for row in selected
        for claim_id in list(row.get("claim_ids") or [])
        if _text(claim_id)
    }
    selected_occurrences = sum(int(row.get("claim_count") or 0) for row in selected)
    reasons_with_percentages = [
        {
            **row,
            "percent_of_all_claims": round(
                int(row.get("claim_count") or 0) / total_claims * 100.0
                if total_claims
                else 0.0,
                2,
            ),
            "percent_of_reasoned_claims": round(
                int(row.get("claim_count") or 0) / claims_with_reason * 100.0
                if claims_with_reason
                else 0.0,
                2,
            ),
            "percent_of_reason_occurrences": round(
                int(row.get("claim_count") or 0) / reason_occurrence_count * 100.0
                if reason_occurrence_count
                else 0.0,
                2,
            ),
        }
        for row in selected
    ]
    scope_rows = [
        {
            "claim_id": claim_id,
            "api_account_id": account_id,
        }
        for account_id, claim_id in latest
    ]
    return Result.ok(
        "Secili iadelerin neden ozeti hazirlandi.",
        close_dialog=False,
        data={
            "rows": reasons_with_percentages,
            "reasons": reasons_with_percentages,
            "claim_count": total_claims,
            "total_claims": total_claims,
            "reason_count": len(rows),
            "total_distinct_reasons": len(rows),
            "without_reason_count": without_reason,
            "claims_with_reason": claims_with_reason,
            "claims_without_reason": without_reason,
            "multi_reason_claims": multi_reason_claims,
            "reason_occurrence_count": reason_occurrence_count,
            "reason_counting_rule": (
                "Each claim contributes at most once to each normalized reason; "
                "multi-reason claims contribute once to every distinct reason."
            ),
            "top_n": bounded_limit,
            "returned_reason_count": len(reasons_with_percentages),
            "selected_claim_occurrence_sum": selected_occurrences,
            "selected_unique_claim_count": len(selected_claim_ids),
            "selected_overlap_claims": max(0, selected_occurrences - len(selected_claim_ids)),
            "selected_percent_of_all_claims": round(
                len(selected_claim_ids) / total_claims * 100.0 if total_claims else 0.0,
                2,
            ),
            "truncated": len(rows) > bounded_limit,
            "scope_rows": scope_rows,
            "status_filter": list(statuses or []),
            "start_date_ms": start_date_ms,
            "end_date_ms": end_date_ms,
        },
    )


def restore_return_claim_sync_snapshots(
    snapshots: list[dict[str, Any]],
    *,
    db_name: str = DB_NAME,
) -> Result:
    try:
        restored: list[int] = []
        with Session(get_engine(db_name or DB_NAME)) as session:
            for snapshot in list(snapshots or []):
                pk = int(snapshot.get("pk") or 0)
                row = session.get(ReturnClaim, pk) if pk > 0 else None
                if row is None:
                    return Result.fail(
                        "Kaynak iade kaydi cleanup sirasinda bulunamadi.",
                        close_dialog=False,
                    )
                row.sync_deleted_at = snapshot.get("sync_deleted_at")
                session.add(row)
                restored.append(pk)
            session.commit()
        return Result.ok(
            "Iade snapshotlari geri yuklendi.",
            close_dialog=False,
            data={"restored_pks": restored},
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def mark_order_headers_extracted(
    order_refs: list[dict[str, Any]],
    *,
    db_name: str = DB_NAME,
    extracted_at: int | None = None,
) -> Result:
    try:
        when = int(extracted_at or datetime.now(timezone.utc).timestamp() * 1000)
        updated: list[str] = []
        missing: list[str] = []
        affected = 0
        with Session(get_engine(db_name or DB_NAME)) as session:
            for ref in order_refs:
                number = _text(ref.get("orderNumber") or ref.get("order_number"))
                if not number:
                    continue
                stmt = select(OrderHeader).where(OrderHeader.orderNumber == number)
                account_id = ref.get("api_account_id")
                if account_id not in (None, ""):
                    stmt = stmt.where(OrderHeader.api_account_id == int(account_id))
                headers = session.exec(stmt).all() or []
                if not headers:
                    missing.append(number)
                    continue
                for header in headers:
                    header.is_extracted = True
                    header.extracted_at = when
                    session.add(header)
                    affected += 1
                updated.append(number)
            session.commit()
        return Result.ok(
            "Siparis fis/cikti durumu guncellendi.",
            close_dialog=False,
            data={"affected": affected, "order_numbers": updated, "missing_order_numbers": missing},
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def target_account_ids(kind: str, tokens: list[Any], *, db_name: str = DB_NAME) -> Result:
    resolved: set[str] = set()
    environments: set[str] = set()
    verified: list[str] = []
    for raw_token in tokens:
        token = raw_token
        api_account_id = None
        if isinstance(raw_token, dict):
            token = raw_token.get("token") or raw_token.get("order_number") or raw_token.get("claim_id")
            api_account_id = raw_token.get("api_account_id")
        elif isinstance(raw_token, (list, tuple)) and raw_token:
            token = raw_token[0]
            api_account_id = raw_token[1] if len(raw_token) > 1 else None
        result = (
            resolve_order_record(token, api_account_id=api_account_id, db_name=db_name)
            if kind == "order"
            else resolve_return_claim(token, api_account_id=api_account_id, db_name=db_name)
        )
        if not result.success:
            return result
        record = (result.data or {}).get("record")
        account = getattr(record, "api_account", None)
        account_id = _text(getattr(account, "account_id", ""))
        if not account_id:
            return Result.fail(f"Hedef kaydin staging account kimligi bulunamadi: {_text(token)}", close_dialog=False)
        extra_config = dict(getattr(account, "extra_config", None) or {})
        environments.add(
            normalize_marketplace_environment(
                extra_config.get("environment")
                or extra_config.get("api_environment")
                or "production"
            )
        )
        resolved.add(account_id)
        verified.append(_text(token))
    return Result.ok(
        "Hedef hesaplar cozuldu.",
        close_dialog=False,
        data={
            "target_account_ids": sorted(resolved),
            "target_environments": sorted(environments),
            "verified_references": verified,
            "db_name": db_name,
        },
    )


def verify_agent_action_eligibility(
    action_type: str,
    *,
    record_refs: list[dict[str, Any]] | None = None,
    payload: dict[str, Any] | None = None,
    db_name: str = DB_NAME,
) -> Result:
    """Authoritative last-moment eligibility read-back for Orders-owned actions."""

    try:
        clean_action = _text(action_type)
        refs = [dict(row) for row in list(record_refs or []) if isinstance(row, dict)]
        clean_payload = dict(payload or {})
        order_numbers = list(
            dict.fromkeys(
                _text(row.get("record_id"))
                for row in refs
                if _text(row.get("record_type")) == "order"
                and _text(row.get("record_id"))
            )
        )
        claim_ids = list(
            dict.fromkeys(
                _text(row.get("record_id"))
                for row in refs
                if _text(row.get("record_type")) == "return_claim"
                and _text(row.get("record_id"))
            )
        )
        if not order_numbers:
            order_numbers = list(
                dict.fromkeys(
                    _text(value)
                    for value in list(
                        clean_payload.get("order_numbers")
                        or clean_payload.get("orders")
                        or []
                    )
                    if _text(value)
                )
            )
            single_order = _text(
                clean_payload.get("order_number") or clean_payload.get("order")
            )
            if single_order and single_order not in order_numbers:
                order_numbers.append(single_order)
        if not claim_ids:
            claim_ids = list(
                dict.fromkeys(
                    _text(value)
                    for value in list(clean_payload.get("claim_ids") or [])
                    if _text(value)
                )
            )
            single_claim = _text(clean_payload.get("claim_id"))
            if single_claim and single_claim not in claim_ids:
                claim_ids.append(single_claim)

        if clean_action == "labels.action_create_labels_from_selected_orders":
            if not order_numbers:
                return Result.fail(
                    "Etiket preflight hedef siparis kimligi tasimiyor.",
                    close_dialog=False,
                    data={"eligible": False, "reason": "missing_order_targets"},
                )
            selected = select_ready_to_ship_orders(
                order_numbers=order_numbers,
                only_not_printed=True,
                limit=max(1, len(order_numbers)),
                db_name=db_name,
            )
            if not selected.success:
                return selected
            eligible_ids = list((selected.data or {}).get("order_numbers") or [])
            eligible = set(eligible_ids) == set(order_numbers)
            return (
                Result.ok(
                    "Etiket hedefleri halen kargoya hazir ve yazdirilmamis.",
                    close_dialog=False,
                    data={
                        "eligible": True,
                        "verified_by": "Orders.select_ready_to_ship_orders",
                        "record_ids": eligible_ids,
                    },
                )
                if eligible
                else Result.fail(
                    "Etiket hedeflerinden biri artik uygun degil; yeniden prepare gerekiyor.",
                    close_dialog=False,
                    data={
                        "eligible": False,
                        "reason": "ready_or_printed_state_changed",
                        "requested_record_ids": order_numbers,
                        "eligible_record_ids": eligible_ids,
                    },
                )
            )

        if clean_action in {
            "orders.change_order_cargo_provider",
            "orders.change_orders_cargo_provider_bulk",
            "orders.action_export_order_profit_excel",
            "labels.mark_orders_extracted_from_label_result",
        }:
            if not order_numbers:
                return Result.fail(
                    "Orders action preflight hedef siparis kimligi tasimiyor.",
                    close_dialog=False,
                    data={"eligible": False, "reason": "missing_order_targets"},
                )
            queried = query_orders(
                order_numbers=order_numbers,
                mode="list",
                limit=max(1, len(order_numbers)),
                db_name=db_name,
            )
            if not queried.success:
                return queried
            rows = [dict(row) for row in list((queried.data or {}).get("orders") or []) if isinstance(row, dict)]
            found_ids = [_text(row.get("order_number")) for row in rows if _text(row.get("order_number"))]
            problems: list[str] = []
            if set(found_ids) != set(order_numbers):
                problems.append("order_target_missing")
            if clean_action in {
                "orders.change_order_cargo_provider",
                "orders.change_orders_cargo_provider_bulk",
            }:
                if not _text(clean_payload.get("cargo_provider_code")):
                    problems.append("cargo_provider_target_missing")
                terminal = {
                    "cancelled",
                    "delivered",
                    "returned",
                    "undeliveredandreturned",
                    "unsupplied",
                }
                if any(
                    _search_key(row.get("status")).replace(" ", "") in terminal
                    for row in rows
                ):
                    problems.append("order_status_terminal")
            if problems:
                return Result.fail(
                    "Orders action hedef eligibility kontrolu degisti; yeniden prepare gerekiyor.",
                    close_dialog=False,
                    data={
                        "eligible": False,
                        "reason_codes": problems,
                        "requested_record_ids": order_numbers,
                        "found_record_ids": found_ids,
                    },
                )
            return Result.ok(
                "Orders action hedefleri authoritative read-back ile uygun.",
                close_dialog=False,
                data={
                    "eligible": True,
                    "verified_by": "Orders.query_orders",
                    "record_ids": found_ids,
                    "statuses": {
                        _text(row.get("order_number")): _text(row.get("status"))
                        for row in rows
                        if _text(row.get("order_number"))
                    },
                },
            )

        return_rules = {
            "orders.approve_return_claim": (True, {"WaitingInAction"}),
            "orders.mark_return_claims_stale": (True, set()),
            "orders.restore_return_claims_from_stale": (False, set()),
        }
        if clean_action in return_rules:
            if not claim_ids:
                return Result.fail(
                    "Return action preflight hedef claim kimligi tasimiyor.",
                    close_dialog=False,
                    data={"eligible": False, "reason": "missing_claim_targets"},
                )
            active, allowed_statuses = return_rules[clean_action]
            listed = list_return_claims(
                claim_ids=claim_ids,
                active=active,
                db_name=db_name,
            )
            if not listed.success:
                return listed
            rows = list((listed.data or {}).get("records") or [])
            found_ids = list(
                dict.fromkeys(
                    _text(getattr(row, "claimId", ""))
                    for row in rows
                    if _text(getattr(row, "claimId", ""))
                )
            )
            status_by_id = {
                _text(getattr(row, "claimId", "")): _text(
                    getattr(row, "claimItemStatus", "")
                )
                for row in rows
                if _text(getattr(row, "claimId", ""))
            }
            eligible = set(found_ids) == set(claim_ids) and (
                not allowed_statuses
                or all(status_by_id.get(claim_id) in allowed_statuses for claim_id in claim_ids)
            )
            return (
                Result.ok(
                    "Return action hedefleri authoritative read-back ile uygun.",
                    close_dialog=False,
                    data={
                        "eligible": True,
                        "verified_by": "Orders.list_return_claims",
                        "record_ids": found_ids,
                        "statuses": status_by_id,
                        "active": active,
                    },
                )
                if eligible
                else Result.fail(
                    "Return action hedef eligibility kontrolu degisti; yeniden prepare gerekiyor.",
                    close_dialog=False,
                    data={
                        "eligible": False,
                        "reason": "return_state_changed",
                        "requested_record_ids": claim_ids,
                        "found_record_ids": found_ids,
                        "statuses": status_by_id,
                        "active": active,
                    },
                )
            )

        return Result.ok(
            "Orders action icin ek domain eligibility kurali gerekmiyor.",
            close_dialog=False,
            data={
                "eligible": True,
                "verified_by": "Orders.action_type_not_state_sensitive",
                "record_ids": order_numbers or claim_ids,
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)
