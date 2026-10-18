from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from Feedback.processors.pipeline import Result
from Orders.views import actions


def _catalog(*currencies):
    stocks = [
        SimpleNamespace(pk=index, sku=f"SKU-{index}", name=f"Product {index}", vat_rate=0)
        for index, _currency in enumerate(currencies, 1)
    ]
    listings = [
        {"api_account_id": 1, "barcode": f"BAR-{index}", "title": stock.name,
         "salePrice": 100, "vatRate": 0,
         "stock_items": [{"stock_item_id": index, "qty": 1}], "cost_items": []}
        for index, stock in enumerate(stocks, 1)
    ]
    balances = [
        {"item": stock, "avg_unit_cost": 10, "avg_cost_input_mode": "gross",
         "avg_cost_currency": currency}
        for stock, currency in zip(stocks, currencies)
    ]
    with patch.object(actions, "get_active_companies", return_value=Result.ok(
        "read", data={"records": [SimpleNamespace(pk=1, platform="TRENDYOL")]}
    )), patch.object(actions, "get_listings_from_db", return_value=Result.ok(
        "read", data={"items": listings}
    )), patch.object(actions, "action_list_items", return_value=Result.ok(
        "read", data={"records": stocks}
    )), patch.object(actions, "action_list_item_balances", return_value=Result.ok(
        "read", data={"records": balances}
    )), patch.object(actions, "load_finance_cost_items", return_value=Result.ok(
        "read", data={"records": []}
    )), patch.object(actions, "load_logistics_cargo_tariffs", return_value=Result.ok(
        "read", data={"records": []}
    )):
        result = actions.load_order_profit_catalog(api_account_ids=[1], db_name="unused.sqlite3")
    assert result.success, result.message
    return result.data


def _order(index=1):
    return SimpleNamespace(orderNumber=f"ORD-{index}", api_account_id=1,
                           currencyCode="TRY", packageTotalPrice=100)


def _items(index=1, quantity=1):
    return [{"barcode": f"BAR-{index}", "name": f"Product {index}",
             "qty": quantity, "unit_price": 100, "vatRate": 0}]


def test_try_cost_keeps_reference_profit_and_currency_evidence():
    catalog = _catalog(" try ")
    assert catalog["stock_cost_meta_map"][1]["currency"] == "TRY"
    result = actions.estimate_order_profit(order=_order(), order_items=_items(quantity=2), catalog=catalog)

    assert result["estimated_profit_ready"]
    assert result["estimated_profit"] == pytest.approx(180)
    assert result["estimated_profit_detail"]["results"]["total_costs"] == pytest.approx(20)
    assert result["estimated_profit_missing_reasons"] == []


@pytest.mark.parametrize("currency", ["EUR", "USD"])
def test_foreign_stock_cost_is_not_sent_to_try_profit_engine(currency):
    catalog = _catalog(currency)
    assert catalog["stock_cost_meta_map"][1]["currency"] == currency
    with patch.object(actions, "estimate_listing_profit") as try_estimator:
        result = actions.estimate_order_profit(order=_order(), order_items=_items(), catalog=catalog)

    try_estimator.assert_not_called()
    assert result["estimated_profit_ready"] is False
    assert result["estimated_profit"] is None
    assert result["estimated_profit_text"] == "-"
    assert result["estimated_profit_detail"]["results"] == {}
    assert any(currency in reason and "kur" in reason for reason in result["estimated_profit_missing_reasons"])


@pytest.mark.parametrize("currency", [None, "", " "])
def test_missing_stock_currency_withholds_profit_without_defaulting_to_try(currency):
    catalog = _catalog(currency)
    assert catalog["stock_cost_meta_map"][1]["currency"] is None
    result = actions.estimate_order_profit(order=_order(), order_items=_items(), catalog=catalog)

    assert result["estimated_profit_ready"] is False
    assert result["estimated_profit"] is None
    assert any("para birimi eksik" in reason for reason in result["estimated_profit_missing_reasons"])


def test_foreign_unselected_stock_does_not_block_selected_try_order():
    catalog = _catalog("TRY", "EUR")
    result = actions.estimate_order_profit(order=_order(), order_items=_items(), catalog=catalog)

    assert result["estimated_profit_ready"]
    assert result["estimated_profit"] == pytest.approx(90)


def test_order_summary_withholds_total_and_keeps_only_supported_partial_profit():
    catalog = _catalog("TRY", "EUR")
    orders = [_order(1), _order(2)]
    with patch.object(actions, "load_order_profit_catalog", return_value=Result.ok(
        "catalog", data=catalog
    )), patch.object(actions, "load_order_items_for_order_numbers", return_value=Result.ok(
        "items", data={"items_by_order": {(1, order.orderNumber): _items(index)
                                           for index, order in enumerate(orders, 1)}}
    )):
        result = actions.estimate_orders_profit_summary(orders=orders, db_name="unused.sqlite3")

    assert result.success, result.message
    assert result.data["estimated_profit_ready"] is False
    assert result.data["estimated_profit"] is None
    assert result.data["partial_estimated_profit"] == pytest.approx(90)
    assert result.data["complete_order_count"] == 1
    assert result.data["incomplete_order_count"] == 1
    assert result.data["rows"][1]["estimated_profit"] is None
    assert any("EUR" in reason for reason in result.data["missing_reasons"])


def test_foreign_order_sales_are_not_mixed_with_try_stock_cost():
    order = _order()
    order.currencyCode = "EUR"
    with patch.object(actions, "estimate_listing_profit") as try_estimator:
        result = actions.estimate_order_profit(order=order, order_items=_items(), catalog=_catalog("TRY"))

    try_estimator.assert_not_called()
    assert result["estimated_profit_ready"] is False
    assert result["estimated_profit"] is None
    assert any("satış para birimi EUR" in reason for reason in result["estimated_profit_missing_reasons"])


def test_legacy_order_without_sales_currency_keeps_try_profit_behavior():
    result = actions.estimate_order_profit(
        order=SimpleNamespace(orderNumber="ORD-1", api_account_id=1),
        order_items=_items(), catalog=_catalog("TRY"),
    )
    assert result["estimated_profit_ready"]
    assert result["estimated_profit"] == pytest.approx(90)


def test_foreign_item_currency_survives_loading_and_blocks_profit():
    row = SimpleNamespace(orderNumber="ORD-1", api_account_id=1, barcode="BAR-1",
                          quantity=1, price=100, currencyCode="EUR", vatRate=0)
    with patch.object(actions, "get_latest_order_items_by_numbers", return_value=Result.ok(
        "read", data={"items": [row]}
    )):
        loaded = actions.load_order_items_for_order_numbers(["ORD-1"], db_name="unused.sqlite3")

    assert loaded.success, loaded.message
    items = loaded.data["items_by_order"][(1, "ORD-1")]
    assert items[0]["currencyCode"] == "EUR"
    result = actions.estimate_order_profit(order=_order(), order_items=items, catalog=_catalog("TRY"))
    assert result["estimated_profit"] is None
    assert any("kalemi satış para birimi EUR" in reason for reason in result["estimated_profit_missing_reasons"])


@pytest.mark.parametrize("key", ["handling-fee", "platform-hizmet-bedeli"])
def test_selected_foreign_fixed_cost_card_blocks_profit(key):
    catalog = _catalog("TRY")
    catalog["listing_lookup"]["by_barcode"][(1, "bar-1")]["cost_items"] = [
        {"cost_key": key, "source_type": "manual_value", "amount": 5}
    ]
    catalog["cost_items_cache"] = [
        {"costKey": key, "valueType": "numeric", "currency": "EUR", "vatRate": 0}
    ]
    result = actions.estimate_order_profit(order=_order(), order_items=_items(), catalog=catalog)

    assert result["estimated_profit_ready"] is False
    assert result["estimated_profit"] is None
    assert any("Maliyet kartı" in reason and "EUR" in reason for reason in result["estimated_profit_missing_reasons"])


def test_percentage_card_currency_and_unselected_foreign_cards_do_not_block_profit():
    catalog = _catalog("TRY")
    catalog["listing_lookup"]["by_barcode"][(1, "bar-1")]["cost_items"] = [
        {"cost_key": "komisyon", "source_type": "manual_value", "amount": 5}
    ]
    catalog["cost_items_cache"] = [
        {"costKey": "komisyon", "valueType": "percentage", "currency": "EUR", "vatRate": 0},
        {"costKey": "unused-fee", "valueType": "numeric", "currency": "USD", "vatRate": 0},
    ]
    result = actions.estimate_order_profit(order=_order(), order_items=_items(), catalog=catalog)

    assert result["estimated_profit_ready"], result["estimated_profit_missing_reasons"]
    assert result["estimated_profit"] == pytest.approx(85)


@pytest.mark.parametrize("selected_currency", ["EUR", "TRY"])
def test_only_selected_cargo_tariff_currency_affects_profit(selected_currency):
    catalog = _catalog("TRY")
    catalog["stock_dimension_map"] = {1: {"weight_kg": 1}}
    catalog["listing_lookup"]["by_barcode"][(1, "bar-1")]["cost_items"] = [
        {"cost_key": "kargo", "source_type": "builtin_resolver",
         "source_config": {"ruleKey": "cargo_amount_matcher"}}
    ]
    catalog["cost_items_cache"] = [
        {"costKey": "kargo", "valueType": "numeric", "currency": "TRY", "vatRate": 0}
    ]
    catalog["cargo_tariffs_cache"] = [
        {"tariffKey": "selected", "platformCode": "TRENDYOL", "minDesi": 0,
         "maxDesi": 2, "minSalePrice": 0, "maxSalePrice": 200, "amount": 5,
         "currency": selected_currency, "vatRate": 0, "isVatIncluded": True, "isActive": True},
        {"tariffKey": "unused", "platformCode": "TRENDYOL", "minDesi": 0,
         "maxDesi": 2, "minSalePrice": 300, "maxSalePrice": 400, "amount": 50,
         "currency": "USD", "vatRate": 0, "isVatIncluded": True, "isActive": True},
    ]
    result = actions.estimate_order_profit(order=_order(), order_items=_items(), catalog=catalog)

    if selected_currency == "TRY":
        assert result["estimated_profit_ready"], result["estimated_profit_missing_reasons"]
        assert result["estimated_profit"] == pytest.approx(85)
    else:
        assert result["estimated_profit_ready"] is False
        assert result["estimated_profit"] is None
        assert any("Kargo tarifesi EUR" in reason for reason in result["estimated_profit_missing_reasons"])
