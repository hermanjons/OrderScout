"""Finance-owned aggregation of recorded marketplace and manual movements."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from Feedback.processors.pipeline import Result, map_error_to_message
from Finance.processors import agentic_repository
from settings import DB_NAME


def _value(row: Any, name: str, default: Any = None) -> Any:
    return row.get(name, default) if isinstance(row, Mapping) else getattr(row, name, default)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float:
    try:
        text = str(value).strip().replace(",", ".")
        return float(text) if text else 0.0
    except (TypeError, ValueError):
        return 0.0


def transaction_amount_totals(records: Iterable[Any]) -> dict[str, float]:
    """Sum normalized movement amounts without changing their currency scope.

    Callers group by currency or retain the already-selected UI record scope.
    netAmount is authoritative; it is not reconstructed from credit and debt.
    """
    totals = {"credit": 0.0, "debt": 0.0, "netAmount": 0.0}
    for row in records:
        for key in totals:
            totals[key] += _number(_value(row, key))
    return totals


def _cashflow_totals(finance_rows: list[Any], manual_rows: list[Any]) -> dict[str, Any]:
    totals_by_currency: dict[str, dict[str, Any]] = {}

    def currency_totals(value: Any) -> dict[str, Any]:
        currency = _text(value).upper() or "UNSPECIFIED"
        return totals_by_currency.setdefault(currency, {
            "currency": currency, "marketplace_credit": 0.0, "marketplace_debt": 0.0,
            "marketplace_net": 0.0, "manual_in": 0.0, "manual_out": 0.0,
            "manual_by_category": {},
        })

    marketplace_by_currency: dict[str, list[Any]] = {}
    type_counts: dict[str, int] = {}
    for row in finance_rows:
        currency = currency_totals(_value(row, "currency"))["currency"]
        marketplace_by_currency.setdefault(currency, []).append(row)
        tx_type = _text(_value(row, "transactionType")) or "unknown"
        type_counts[tx_type] = type_counts.get(tx_type, 0) + 1
    for currency, rows in marketplace_by_currency.items():
        amounts = transaction_amount_totals(rows)
        totals_by_currency[currency].update({
            "marketplace_credit": amounts["credit"], "marketplace_debt": amounts["debt"],
            "marketplace_net": amounts["netAmount"],
        })

    for row in manual_rows:
        totals = currency_totals(_value(row, "currency"))
        amount = _number(_value(row, "amount", 0))
        direction = _text(_value(row, "direction")).casefold()
        category = _text(_value(row, "categoryName") or _value(row, "categoryKey") or "uncategorized")
        income = direction in {"in", "income", "credit", "alacak", "gelir"}
        totals["manual_in" if income else "manual_out"] += amount
        categories = totals["manual_by_category"]
        categories[category] = categories.get(category, 0.0) + (amount if income else -amount)

    if not totals_by_currency:
        currency_totals("TRY")
    currency_rows = []
    for currency, totals in sorted(totals_by_currency.items()):
        row = {key: round(totals[key], 2) for key in (
            "marketplace_credit", "marketplace_debt", "marketplace_net", "manual_in", "manual_out",
        )}
        row["currency"] = currency
        row["combined_net"] = round(totals["marketplace_net"] + totals["manual_in"] - totals["manual_out"], 2)
        row["manual_by_category"] = {key: round(value, 2) for key, value in totals["manual_by_category"].items()}
        currency_rows.append(row)
    single = currency_rows[0] if len(currency_rows) == 1 and currency_rows[0]["currency"] != "UNSPECIFIED" else None
    return {
        "currency": single["currency"] if single else None,
        "currency_totals": currency_rows,
        **{key: single[key] if single else None for key in (
            "marketplace_credit", "marketplace_debt", "marketplace_net", "manual_in", "manual_out", "combined_net",
        )},
        "transaction_type_counts": type_counts,
        "manual_by_category": single["manual_by_category"] if single else {},
    }


def read_cashflow_summary(*, db_name: str = DB_NAME, start_ms: int | None = None,
                          end_ms: int | None = None) -> Result:
    """Read complete recorded cashflow, keeping dates, deletion and currencies explicit."""
    try:
        finance_result = agentic_repository.list_records("transaction", db_name=db_name)
        if not finance_result.success:
            return finance_result
        manual_result = agentic_repository.list_records("manual_transaction", db_name=db_name)
        if not manual_result.success:
            return manual_result

        def in_period(row: Any) -> bool:
            if start_ms is None and end_ms is None:
                return True
            stamp = int(_value(row, "transactionDate", 0) or 0)
            return (start_ms is None or stamp >= int(start_ms)) and (end_ms is None or stamp <= int(end_ms))

        finance_rows = [row for row in ((finance_result.data or {}).get("records") or []) if in_period(row)]
        manual_rows = [row for row in ((manual_result.data or {}).get("records") or [])
                       if not bool(_value(row, "isDeleted", False)) and in_period(row)]
        return Result.ok("Finans hareketleri para birimine göre özetlendi.", close_dialog=False,
                         data=_cashflow_totals(finance_rows, manual_rows))
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)
