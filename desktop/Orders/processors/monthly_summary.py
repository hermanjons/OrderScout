"""Calendar-month aggregates over the shared latest-order read operation."""
from __future__ import annotations

from calendar import monthrange
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
from typing import Any

from Feedback.processors.pipeline import Result, map_error_to_message
from Orders.constants import TZ_GMT3
from Orders.processors.trendyol.pipeline import (
    canonical_order_status_code,
    get_latest_orders_filtered,
)
from settings import DB_NAME


def _month_labels(start_ms: int, end_ms: int) -> list[str]:
    first = datetime.fromtimestamp(start_ms / 1000, TZ_GMT3)
    last = datetime.fromtimestamp(end_ms / 1000, TZ_GMT3)
    start_index = first.year * 12 + first.month - 1
    end_index = last.year * 12 + last.month - 1
    if end_index - start_index >= 1200:
        raise ValueError("monthly_scope_exceeds_1200_months")
    return [f"{index // 12:04d}-{index % 12 + 1:02d}" for index in range(start_index, end_index + 1)]


def _amount(row: Any) -> Decimal | None:
    value = getattr(row, "packageTotalPrice", None)
    if value is None:
        value = getattr(row, "totalPrice", None)
    if value is None:
        return None
    amount = Decimal(str(value))
    if not amount.is_finite():
        raise ValueError("monthly_amount_must_be_finite")
    return amount


def _partial_months(months: list[str], start_ms: int, end_ms: int) -> list[dict[str, Any]]:
    boundaries = []
    for month in dict.fromkeys((months[0], months[-1])):
        year, number = map(int, month.split("-"))
        first = int(datetime(year, number, 1, tzinfo=TZ_GMT3).timestamp() * 1000)
        last = int(datetime(year, number, monthrange(year, number)[1], 23, 59, 59,
                            999000, tzinfo=TZ_GMT3).timestamp() * 1000)
        actual_first, actual_last = max(first, start_ms), min(last, end_ms)
        if actual_first != first or actual_last != last:
            boundaries.append({"month": month, "start_ms": actual_first, "end_ms": actual_last,
                "start_date": datetime.fromtimestamp(actual_first / 1000, TZ_GMT3).date().isoformat(),
                "end_date": datetime.fromtimestamp(actual_last / 1000, TZ_GMT3).date().isoformat()})
    return boundaries


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def summarize_orders_by_month(
    *,
    start_date_ms: int,
    end_date_ms: int,
    api_account_ids: list[int] | None = None,
    db_name: str = DB_NAME,
) -> Result:
    """Count order-date months with current cancellations and amounts per currency.

    Dates are inclusive epoch-millisecond boundaries. A cancellation belongs to
    the month the order was placed; this is not a cancellation-event history.
    Empty months are deliberate zero rows for each currency observed in scope.
    Missing amounts or currencies remain explicit rather than becoming money.
    """
    try:
        if any(isinstance(value, bool) or not isinstance(value, int)
               for value in (start_date_ms, end_date_ms)):
            raise ValueError("monthly_integer_date_boundaries_required")
        if end_date_ms < start_date_ms:
            raise ValueError("monthly_end_before_start")
        months = _month_labels(start_date_ms, end_date_ms)
        if api_account_ids is not None and (not isinstance(api_account_ids, list)
                or any(isinstance(value, bool) or not isinstance(value, int) or value <= 0
                       for value in api_account_ids)):
            raise ValueError("monthly_positive_account_ids_required")
        accounts = sorted(set(api_account_ids or []))
        latest = get_latest_orders_filtered(start_ms=start_date_ms, end_ms=end_date_ms,
            api_account_ids=accounts or None, db_name=db_name)
        if not latest.success:
            return latest

        source_rows = []
        for order in (latest.data or {}).get("orders") or []:
            amount = _amount(order)
            status = str(getattr(order, "shipmentPackageStatus", None)
                         or getattr(order, "status", None) or "Unknown").strip()
            canonical_status = canonical_order_status_code(status)
            source_rows.append({
                "api_account_id": getattr(order, "api_account_id", None),
                "order_number": str(getattr(order, "orderNumber", "") or "").strip(),
                "order_date_ms": int(getattr(order, "orderDate", 0) or 0),
                "last_modified_ms": int(getattr(order, "lastModifiedDate", 0) or 0),
                "status": status,
                "cancelled": canonical_status == "Cancelled",
                "currency": str(getattr(order, "currencyCode", "") or "").strip().upper() or None,
                "amount": str(amount) if amount is not None else None,
            })
        source_rows.sort(key=lambda row: (row["api_account_id"] or 0, row["order_number"]))
        currencies = sorted({row["currency"] for row in source_rows if row["currency"]})
        currency_groups = [*currencies, *([None] if any(row["currency"] is None for row in source_rows) else [])]
        # No orders still means known zero counts across every requested month;
        # no currency is inferred from an empty dataset.
        buckets = {(month, currency): [] for month in months for currency in currency_groups or [None]}
        for row in source_rows:
            month = datetime.fromtimestamp(row["order_date_ms"] / 1000, TZ_GMT3).strftime("%Y-%m")
            buckets[(month, row["currency"])].append(row)

        output = []
        for (month, currency), members in buckets.items():
            cancelled = [row for row in members if row["cancelled"]]
            non_cancelled = [row for row in members if not row["cancelled"]]
            item = {"month": month, "currency": currency,
                    "total_orders": len(members), "cancelled_orders": len(cancelled),
                    "non_cancelled_orders": len(non_cancelled)}
            for prefix, rows in (("total", members), ("cancelled", cancelled), ("non_cancelled", non_cancelled)):
                missing = sum(row["amount"] is None for row in rows)
                item[f"{prefix}_missing_amount_orders"] = missing
                item[f"{prefix}_amount"] = (None if missing or (currency is None and rows)
                    else _money(sum((Decimal(row["amount"]) for row in rows), Decimal(0))))
            output.append(item)

        scope = {"start_date_ms": start_date_ms, "end_date_ms": end_date_ms,
                 "api_account_ids": accounts, "timezone": "UTC+03:00", "date_basis": "order_date"}
        scope_accounts = sorted({row["api_account_id"] for row in source_rows if row["api_account_id"] is not None})
        source_hash = hashlib.sha256(json.dumps({"scope": scope, "rows": source_rows},
            ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        return Result.ok("Aylık sipariş toplamları ve iptaller para birimine göre hesaplandı.", close_dialog=False,
            data={"rows": output, "partial_months": _partial_months(months, start_date_ms, end_date_ms),
                  "month_count": len(months), "row_count": len(output),
                  "total_orders": len(source_rows), "cancelled_orders": sum(row["cancelled"] for row in source_rows),
                  "currencies": currencies, "missing_currency_orders": sum(row["currency"] is None for row in source_rows),
                  "missing_amount_orders": sum(row["amount"] is None for row in source_rows),
                  "scope": scope, "scope_account_ids": scope_accounts,
                  "api_account_ids": accounts or scope_accounts, "start_ms": start_date_ms, "end_ms": end_date_ms,
                  "date_basis": "order_date", "timezone": "UTC+03:00", "complete": True,
                  "cancellation_basis": "latest_order_status_in_order_date_month",
                  "amount_basis": "packageTotalPrice_else_totalPrice;missing_values_are_null",
                  "source_revision": max((row["last_modified_ms"] for row in source_rows), default=0),
                  "source_snapshot_hash": source_hash,
                  "simulated_excluded": int((latest.data or {}).get("simulated_excluded") or 0),
                  "data_coverage": {"status": "local_records", "complete_for_local_scope": True,
                                    "marketplace_history_completeness_known": False},
                  "network_request_performed": False})
    except (ValueError, TypeError, OverflowError, OSError, InvalidOperation) as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False,
                           data={"complete": False, "reason": str(exc)})
