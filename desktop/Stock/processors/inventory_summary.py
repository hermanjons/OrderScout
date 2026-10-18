"""Stock-owned inventory and low-stock projections shared by all adapters."""
from __future__ import annotations
from typing import Any
from Feedback.processors.pipeline import Result, map_error_to_message


def _text(value):
    return str(value or "").strip()


def _number(value):
    try:
        return float(str(value).strip().replace(",", "."))
    except (ValueError, TypeError):
        return 0.0


def _rounded(value):
    return round(_number(value), 2)


def read_low_stock_summary(*, db_name: str | None = None, limit: int = 10) -> Result:
    from Stock.processors.pipeline import list_item_balances
    try:
        limit = max(1, min(50, int(limit or 10)))
        source = list_item_balances(only_active=True, db_name=db_name)
        if not source.success:
            return source
        balance_rows = list((source.data or {}).get("records") or [])
        rows: list[dict[str, Any]] = []
        for balance_row in balance_rows:
            if not isinstance(balance_row, dict):
                continue
            item = balance_row.get("item")
            balance = _number(balance_row.get("on_hand"))
            min_stock = balance_row.get("min_stock")
            threshold = _number(min_stock) if min_stock is not None else 0.0
            if balance_row.get("is_low") is True or balance <= 0:
                rows.append(
                    {
                        "sku": _text(getattr(item, "sku", "")),
                        "name": _text(getattr(item, "name", "")),
                        "balance": _rounded(balance),
                        "threshold": _rounded(threshold),
                        "unit": _text(getattr(item, "unit", "")) or "adet",
                        "gap": _rounded(threshold - balance),
                    }
                )
        rows.sort(key=lambda row: (-_number(row.get("gap")), _number(row.get("balance"))))
        return Result.ok(
            f"{len(rows)} düşük/kritik stok kaydı bulundu.",
            close_dialog=False,
            data={
                "total_low_stock": len(rows),
                "items": rows[:limit],
                "threshold_rule": "stock_minimum_or_zero_balance",
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def read_inventory_overview(*, db_name: str | None = None, limit: int = 12) -> Result:
    from Stock.processors.pipeline import list_item_balances
    try:
        limit = max(1, min(50, int(limit or 12)))
        source = list_item_balances(only_active=False, db_name=db_name)
        if not source.success:
            return source
        balance_rows = list((source.data or {}).get("records") or [])
        active_rows = [
            row for row in balance_rows
            if isinstance(row, dict)
            and bool(getattr(row.get("item"), "is_active", True))
        ]
        zero_or_negative: list[dict[str, Any]] = []
        top_balances: list[dict[str, Any]] = []
        value_by_currency: dict[str, float] = {}
        balance_by_unit: dict[str, float] = {}
        valuation_missing_items = 0
        for balance_row in active_rows:
            item = balance_row.get("item")
            balance = _number(balance_row.get("on_hand"))
            unit = _text(getattr(item, "unit", "")) or "adet"
            balance_by_unit[unit] = balance_by_unit.get(unit, 0.0) + balance
            raw_cost = balance_row.get("avg_unit_cost")
            currency = _text(balance_row.get("avg_cost_currency")).upper()
            domain_values = balance_row.get("stock_value_by_currency")
            missing_quantity = _number(balance_row.get("valuation_missing_quantity"))
            if isinstance(domain_values, dict):
                item_values = {
                    _text(code).upper(): _rounded(_number(amount))
                    for code, amount in domain_values.items()
                    if _text(code)
                }
            else:
                item_values = (
                    {currency: _rounded(balance * _number(raw_cost))}
                    if raw_cost is not None and currency else {}
                )
                if balance > 0 and not item_values:
                    missing_quantity = balance
            if missing_quantity > 0:
                valuation_missing_items += 1
            for code, amount in item_values.items():
                value_by_currency[code] = value_by_currency.get(code, 0.0) + amount
            stock_value = (
                next(iter(item_values.values()))
                if len(item_values) == 1 and missing_quantity <= 0 else None
            )
            row = {
                "sku": _text(getattr(item, "sku", "")),
                "name": _text(getattr(item, "name", "")),
                "balance": _rounded(balance),
                "unit": unit,
                "stock_value": stock_value,
                "stock_value_currency": next(iter(item_values)) if stock_value is not None else "",
                "stock_value_by_currency": [
                    {"currency": code, "amount": amount}
                    for code, amount in sorted(item_values.items())
                ],
                "valuation_missing_quantity": _rounded(missing_quantity),
            }
            top_balances.append(row)
            if balance <= 0:
                zero_or_negative.append(row)
        top_balances.sort(key=lambda row: _number(row.get("balance")), reverse=True)
        value_parts = [
            f"{_rounded(amount):.2f} {currency}"
            for currency, amount in sorted(value_by_currency.items())
        ]
        valuation_note = (
            " Hareketli ortalama maliyetle kismi stok degeri: "
            + ", ".join(value_parts)
            + f"; {valuation_missing_items} kalemin maliyeti eksik."
            if valuation_missing_items and value_parts
            else f" {valuation_missing_items} kalemin maliyeti eksik; tam stok degeri hesaplanamadi."
            if valuation_missing_items
            else " Hareketli ortalama maliyetle stok degeri: " + ", ".join(value_parts) + "."
            if value_parts
            else ""
        )
        unit_rows = [
            {"unit": unit, "balance": _rounded(amount)}
            for unit, amount in sorted(balance_by_unit.items())
        ]
        single_balance = unit_rows[0]["balance"] if len(unit_rows) == 1 else (0.0 if not unit_rows else None)
        balance_label = (
            f"toplam {single_balance:.2f} {unit_rows[0]['unit']} bakiye"
            if len(unit_rows) == 1
            else "toplam 0.00 bakiye" if not unit_rows
            else "birim bazinda bakiye: " + ", ".join(
                f"{row['balance']:.2f} {row['unit']}" for row in unit_rows
            )
        )
        return Result.ok(
            f"{len(active_rows)} aktif stok karti ve {balance_label} var.{valuation_note}",
            close_dialog=False,
            data={
                "total_items": len(balance_rows),
                "active_items": len(active_rows),
                "zero_or_negative": len(zero_or_negative),
                "total_balance": single_balance,
                "balance_by_unit": unit_rows,
                "stock_value_by_currency": [
                    {"currency": currency, "amount": _rounded(amount)}
                    for currency, amount in sorted(value_by_currency.items())
                ],
                "stock_valuation_complete": valuation_missing_items == 0,
                "valuation_missing_items": valuation_missing_items,
                "top_balances": top_balances[:limit],
                "zero_or_negative_items": zero_or_negative[:limit],
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)
