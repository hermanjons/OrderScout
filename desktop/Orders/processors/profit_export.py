"""Prepare an account-scoped profit snapshot using the manual Orders engine."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from Feedback.processors.pipeline import Result, map_error_to_message
from Orders.processors import profit
from settings import DB_NAME


def read_order_profit_export_payload(*, order: Any, db_name: str = DB_NAME) -> Result:
    """Read current inputs and calculate the exact payload retained for approval.

    The existing manual engine owns monetary calculations and missing-data
    rules. This read operation does not write a file or grant approval.
    """
    try:
        order_number = str(getattr(order, "orderNumber", "") or "").strip()
        if not order_number:
            return Result.fail("Kâr dışa aktarımı için sipariş numarası gerekli.", close_dialog=False)
        raw_account_id = getattr(order, "api_account_id", None)
        account_id = int(raw_account_id) if raw_account_id not in (None, "") else None
        account_ids = [account_id] if account_id is not None else None

        items_result = profit.load_order_items_for_order_numbers(
            [order_number], api_account_ids=account_ids, db_name=db_name,
        )
        if not items_result.success:
            return items_result
        catalog_result = profit.load_order_profit_catalog(api_account_ids=account_ids, db_name=db_name)
        if not catalog_result.success:
            return catalog_result
        items_by_order = (items_result.data or {}).get("items_by_order") or {}
        items = list(items_by_order.get((account_id, order_number), []) or [])
        payload = profit.estimate_order_profit(order=order, order_items=items, catalog=dict(catalog_result.data or {}))
        return Result.ok(
            "Sipariş kârı mevcut motorla hesaplandı." if payload.get("estimated_profit_ready")
            else "Sipariş kârı hesaplanamıyor; eksik veya uyumsuz veriler sonuçta belirtildi.",
            close_dialog=False,
            data={"order_number": order_number, "api_account_id": account_id,
                  "estimated_profit_payload": deepcopy(payload)},
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)
