"""Local profit reads shared by manual consumers and AI tool adapters."""
from __future__ import annotations

from Feedback.processors.pipeline import Result, map_error_to_message
from Orders.processors.profit import (
    _normalize_profit_account_ids,
    estimate_orders_profit_summary,
)
from Orders.processors.trendyol.pipeline import get_latest_orders_filtered
from settings import DB_NAME


def read_profit_estimate(
    *,
    db_name: str = DB_NAME,
    start_ms: int | None = None,
    end_ms: int | None = None,
    api_account_ids: list[int] | None = None,
) -> Result:
    """Estimate non-cancelled local orders without needing marketplace access."""
    try:
        accounts = _normalize_profit_account_ids(api_account_ids)
        orders_result = get_latest_orders_filtered(
            db_name=db_name, start_ms=start_ms, end_ms=end_ms,
            api_account_ids=accounts,
        )
        if not orders_result.success:
            return orders_result
        source = dict(orders_result.data or {})
        eligible_orders = []
        for order in source.get("orders") or []:
            status = str(getattr(order, "shipmentPackageStatus", None)
                         or getattr(order, "status", None) or "").strip().casefold()
            if "cancel" not in status and "iptal" not in status:
                eligible_orders.append(order)
        result = estimate_orders_profit_summary(
            orders=eligible_orders, db_name=db_name, api_account_ids=accounts,
        )
        if result.success:
            result.data = {
                **dict(result.data or {}),
                "start_ms": start_ms, "end_ms": end_ms,
                "simulated_excluded": int(source.get("simulated_excluded") or 0),
            }
        return result
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)
