"""Thin model-facing contract for the shared Orders calendar-month read."""
from __future__ import annotations

from datetime import date, datetime, time

from AI.runtime.contracts import AgentTool
from Feedback.processors.pipeline import Result
from Orders.constants import TZ_GMT3
from settings import DB_NAME


def orders_monthly_summary(*, start_date: str, end_date: str,
                           api_account_ids: list[int] | None = None, all_accounts: bool = False,
                           db_name: str = DB_NAME) -> Result:
    from Orders.views.actions import action_summarize_orders_by_month
    if ((api_account_ids is None and all_accounts is not True)
            or (api_account_ids is not None and all_accounts is not False)):
        return Result.fail("Hesap kapsamı açıkça seçilmeli: api_account_ids veya all_accounts=true.",
            close_dialog=False, data={"complete": False, "reason": "explicit_account_scope_required"})
    try:
        # Unlike a relative period, these explicit days cannot silently fall
        # back to today when the model supplies an invalid date.
        first, last = date.fromisoformat(start_date), date.fromisoformat(end_date)
        if first.isoformat() != start_date or last.isoformat() != end_date:
            raise ValueError("monthly_iso_dates_required")
        start_ms = int(datetime.combine(first, time.min, TZ_GMT3).timestamp() * 1000)
        end_ms = int(datetime.combine(last, time.max, TZ_GMT3).timestamp() * 1000)
    except (ValueError, TypeError, OverflowError) as exc:
        return Result.fail("Aylık özet için başlangıç ve bitiş günlerini YYYY-MM-DD biçiminde belirt.",
                           close_dialog=False, data={"complete": False, "reason": str(exc)})
    result = action_summarize_orders_by_month(start_date_ms=start_ms, end_date_ms=end_ms,
        api_account_ids=api_account_ids, db_name=db_name)
    if isinstance(result.data, dict):
        result.data = {**result.data, "tool": "orders.monthly_summary",
                       "start_date": start_date, "end_date": end_date}
    return result


def monthly_order_summary_tool() -> AgentTool:
    integer = {"type": "integer"}
    row = {"month": {"type": "string"}, "currency": {"type": ["string", "null"]},
           **{f"{prefix}_orders": integer for prefix in ("total", "cancelled", "non_cancelled")},
           **{f"{prefix}_amount": {"type": ["number", "null"]} for prefix in ("total", "cancelled", "non_cancelled")},
           **{f"{prefix}_missing_amount_orders": integer for prefix in ("total", "cancelled", "non_cancelled")}}
    return AgentTool(name="orders.monthly_summary", domain="orders", handler=orders_monthly_summary,
        canonical_callable="Orders.views.actions.action_summarize_orders_by_month",
        description="Aggregate latest local orders by calendar month and observed currency. Explicit inclusive "
            "account scope is required: supply actual api_account_ids OR all_accounts=true. Resolve a store name "
            "to its real local account ID with marketplaces.account_lookup; never guess IDs or treat a named store "
            "as all accounts. Rows aggregate the requested accounts together, not per account. "
            "start_date/end_date days use UTC+03:00; partial_months gives each partial month's exact inclusive "
            "start_date/end_date and millisecond bounds. Use those facts when describing coverage: first and last "
            "months can have different boundaries. Rows include total_orders, "
            "cancelled_orders, non_cancelled_orders and their separate amounts. Cancellations use the latest "
            "status in the order's placement month, not cancellation-event dates. Currencies stay separate; "
            "missing currency/amounts remain null with missing-value counts. Empty months have zero-count rows. "
            "Reads all matching local orders once; does not fetch, build a report or write an Excel file. "
            "Shared manual Orders operation. Monthly rows can be used as report sources at rows_path=rows.",
        parameters={"type": "object", "properties": {
            "start_date": {"type": "string", "description": "Inclusive first day, YYYY-MM-DD."},
            "end_date": {"type": "string", "description": "Inclusive last day, YYYY-MM-DD."},
            "api_account_ids": {"type": "array", "minItems": 1, "uniqueItems": True,
                "description": "Exact local account PKs; resolve store names using marketplaces.account_lookup.",
                "items": {"type": "integer", "minimum": 1}},
            "all_accounts": {"type": "boolean", "const": True,
                "description": "Explicitly aggregate ALL accounts; use only when that is the requested scope."}},
            "required": ["start_date", "end_date"], "additionalProperties": False,
            "oneOf": [{"required": ["api_account_ids"], "not": {"required": ["all_accounts"]}},
                      {"required": ["all_accounts"], "not": {"required": ["api_account_ids"]}}]},
        result_schema={"type": "object", "properties": {
            "rows": {"type": "array", "items": {"type": "object", "properties": row, "required": list(row)}},
            "partial_months": {"type": "array", "items": {"type": "object", "properties": {
                "month": {"type": "string"}, "start_date": {"type": "string"}, "end_date": {"type": "string"},
                "start_ms": integer, "end_ms": integer},
                "required": ["month", "start_date", "end_date", "start_ms", "end_ms"]}},
            **{name: integer for name in ("month_count", "row_count", "total_orders", "cancelled_orders",
                                           "missing_currency_orders", "missing_amount_orders", "source_revision")},
            "complete": {"type": "boolean"}, "currencies": {"type": "array", "items": {"type": "string"}},
            "scope": {"type": "object"}, "scope_account_ids": {"type": "array", "items": integer},
            "api_account_ids": {"type": "array", "items": integer}, "start_ms": integer, "end_ms": integer,
            "date_basis": {"type": "string"}, "timezone": {"type": "string"},
            "cancellation_basis": {"type": "string"}, "amount_basis": {"type": "string"},
            "source_snapshot_hash": {"type": "string"}, "data_coverage": {"type": "object"}}})
