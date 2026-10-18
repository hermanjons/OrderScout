from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from AI.processors import tools
from Feedback.processors.pipeline import Result


def test_inventory_overview_uses_stock_domain_balances_and_keeps_currency():
    rows = [
        {"item": SimpleNamespace(is_active=True, sku="A", name="A", unit="adet"),
         "on_hand": 4, "avg_unit_cost": 25, "avg_cost_currency": "TRY"},
        {"item": SimpleNamespace(is_active=True, sku="B", name="B", unit="adet"),
         "on_hand": 2, "avg_unit_cost": 10, "avg_cost_currency": "USD"},
        {"item": SimpleNamespace(is_active=True, sku="C", name="C", unit="adet"),
         "on_hand": 3, "avg_unit_cost": None, "avg_cost_currency": "TRY"},
        {"item": SimpleNamespace(is_active=False, sku="D", name="D", unit="adet"),
         "on_hand": 7, "avg_unit_cost": 1, "avg_cost_currency": "TRY"},
    ]
    with patch("Stock.processors.pipeline.list_item_balances", return_value=Result.ok(
        "balances", data={"records": rows}
    )) as domain_read, patch.object(tools.stock_repo, "list_transactions") as raw_transactions:
        result = tools.stock_inventory_overview()

    assert result.success, result.message
    assert result.data["total_items"] == 4
    assert result.data["active_items"] == 3
    assert result.data["total_balance"] == 9
    assert result.data["stock_value_by_currency"] == [
        {"currency": "TRY", "amount": 100},
        {"currency": "USD", "amount": 20},
    ]
    assert result.data["stock_valuation_complete"] is False
    assert result.data["valuation_missing_items"] == 1
    assert next(row for row in result.data["top_balances"] if row["sku"] == "C")["stock_value"] is None
    domain_read.assert_called_once()
    raw_transactions.assert_not_called()


def test_inventory_overview_preserves_stock_domain_failure():
    with patch("Stock.processors.pipeline.list_item_balances", return_value=Result.fail("db failed")):
        result = tools.stock_inventory_overview()
    assert not result.success


def test_inventory_overview_does_not_add_incompatible_units():
    rows = [
        {"item": SimpleNamespace(is_active=True, sku="A", name="A", unit="adet"),
         "on_hand": 4, "avg_unit_cost": 25, "avg_cost_currency": "TRY"},
        {"item": SimpleNamespace(is_active=True, sku="B", name="B", unit="kg"),
         "on_hand": 2, "avg_unit_cost": 10, "avg_cost_currency": "TRY"},
    ]
    with patch("Stock.processors.pipeline.list_item_balances", return_value=Result.ok(
        "balances", data={"records": rows}
    )):
        result = tools.stock_inventory_overview()
    assert result.success, result.message
    assert result.data["total_balance"] is None
    assert result.data["balance_by_unit"] == [
        {"unit": "adet", "balance": 4}, {"unit": "kg", "balance": 2}
    ]
    assert "4.00 adet" in result.message and "2.00 kg" in result.message
    assert result.data["stock_value_by_currency"] == [{"currency": "TRY", "amount": 120}]


def test_low_stock_uses_domain_minimum_threshold_instead_of_reorder_point():
    rows = [
        {"item": SimpleNamespace(sku="A", name="A", unit="adet", reorder_point=10),
         "on_hand": 7, "min_stock": 5, "is_low": False},
        {"item": SimpleNamespace(sku="B", name="B", unit="adet", reorder_point=10),
         "on_hand": 4, "min_stock": 5, "is_low": True},
    ]
    with patch("Stock.processors.pipeline.list_item_balances", return_value=Result.ok(
        "balances", data={"records": rows}
    )), patch.object(tools.stock_repo, "list_transactions") as raw_transactions:
        result = tools.low_stock_summary()

    assert result.success, result.message
    assert result.data["total_low_stock"] == 1
    assert result.data["items"][0]["sku"] == "B"
    assert result.data["threshold_rule"] == "stock_minimum_or_zero_balance"
    raw_transactions.assert_not_called()


def test_same_item_warehouse_values_keep_currencies_and_missing_cost_separate():
    from Stock.processors.pipeline import _summarize_item_valuation_rows

    cases = [
        ([(1, 1, 100, "TRY", "gross"), (1, 1, 10, "USD", "gross")],
         {"TRY": 100, "USD": 10}, 0),
        ([(1, 1, 100, "TRY", "gross"), (1, 1, None, "TRY", "gross")],
         {"TRY": 100}, 1),
    ]
    for layers, expected_values, expected_missing in cases:
        avg, currencies, _modes, values, missing = _summarize_item_valuation_rows(layers)
        assert 1 not in avg
        assert 1 not in currencies
        assert values[1] == expected_values
        assert missing.get(1, 0) == expected_missing
        row = {
            "item": SimpleNamespace(is_active=True, sku="A", name="A", unit="adet"),
            "on_hand": 2, "avg_unit_cost": avg.get(1),
            "avg_cost_currency": currencies.get(1, ""),
            "stock_value_by_currency": values[1],
            "valuation_missing_quantity": missing.get(1, 0),
        }
        with patch("Stock.processors.pipeline.list_item_balances", return_value=Result.ok(
            "balances", data={"records": [row]}
        )):
            result = tools.stock_inventory_overview()
        assert result.success, result.message
        assert {part["currency"]: part["amount"] for part in result.data["stock_value_by_currency"]} == expected_values
        assert result.data["stock_valuation_complete"] is (expected_missing == 0)
        assert result.data["valuation_missing_items"] == (1 if expected_missing else 0)
        assert result.data["top_balances"][0]["stock_value"] is None
