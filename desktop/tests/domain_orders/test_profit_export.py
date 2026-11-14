from __future__ import annotations

from copy import deepcopy
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlmodel import Session, select

from Account.models.models import ApiAccount
from Core.utils.model_utils import get_engine
from Feedback.processors.pipeline import Result
from Listing.models.models import ListingProduct, ListingProductStockSnapshot
from Orders.models.trendyol.models import OrderData, OrderItem
from Orders.processors.profit_export import read_order_profit_export_payload
from Orders.processors import profit
from Orders.views import actions
from Stock.constants.domain_constants import StockTxDirection, StockTxReason
from Stock.models.models import StockItem, StockTx, Warehouse
from tests.support.db_case import IsolatedDbTestCase


class TestProfitExportDatabase(IsolatedDbTestCase):
    def _seed(self, *, with_items=True, with_stock_cost=True, currency="TRY"):
        with Session(get_engine(self.db_path)) as session:
            session.add_all([
                ApiAccount(pk=1, account_id="export-1", comp_name="First", platform="TRENDYOL"),
                ApiAccount(pk=2, account_id="export-2", comp_name="Second", platform="TRENDYOL"),
                Warehouse(pk=1, name="Profit warehouse"),
                StockItem(pk=1, sku="PROFIT-1", name="Profit item", vat_rate=0),
                StockItem(pk=2, sku="PROFIT-2", name="Other account item", vat_rate=0),
            ])
            session.flush()
            for account in (1, 2):
                session.add(ListingProduct(pk=account, api_account_id=account, product_id=f"PROFIT-{account}",
                                           barcode="BAR-SAME", title="Profit item", sale_price=100,
                                           stock_item_id=account, vat_rate=0, on_sale=True, approved=True,
                                           raw={"currencyCode": "TRY"}))
                session.flush()
                session.add(ListingProductStockSnapshot(listing_id=account, stock_item_id=account, qty=1))
            if with_stock_cost:
                session.add_all([
                    StockTx(item_id=1, warehouse_id=1, direction=StockTxDirection.IN_, reason=StockTxReason.manual_in,
                            qty=10, unit_cost=10, currency="TRY", unit_cost_input_mode="gross"),
                    StockTx(item_id=2, warehouse_id=1, direction=StockTxDirection.IN_, reason=StockTxReason.manual_in,
                            qty=10, unit_cost=50, currency="TRY", unit_cost_input_mode="gross"),
                ])
            orders = [
                OrderData(pk=1, orderNumber="PROFIT-SAME", api_account_id=1, id=101, lastModifiedDate=999,
                          packageTotalPrice=999, currencyCode=currency),
                OrderData(pk=2, orderNumber="PROFIT-SAME", api_account_id=1, id=101, lastModifiedDate=1000,
                          packageTotalPrice=200, currencyCode=currency),
                OrderData(pk=3, orderNumber="PROFIT-SAME", api_account_id=2, id=201, lastModifiedDate=1000,
                          packageTotalPrice=300, currencyCode="TRY"),
            ]
            session.add_all(orders)
            session.flush()
            if with_items:
                for order, quantity in zip(orders, (99, 2, 3)):
                    session.add(OrderItem(orderNumber=order.orderNumber, api_account_id=order.api_account_id,
                                          order_data_pk=order.pk, order_data_id=order.id,
                                          snapshotLastModifiedDate=order.lastModifiedDate,
                                          id=order.pk, lineId=1, quantity=quantity, price=100, amount=quantity * 100,
                                          barcode="BAR-SAME", productName="Profit item", vatRate=0,
                                          currencyCode=currency if order.api_account_id == 1 else "TRY"))
            session.commit()
            order = session.get(OrderData, 2)
            session.expunge(order)
            return order

    def _manual_payload(self, order):
        items_result = actions.load_order_items_for_order_numbers(
            [order.orderNumber], api_account_ids=[order.api_account_id], db_name=self.db_path,
        )
        catalog_result = actions.load_order_profit_catalog(api_account_ids=[order.api_account_id], db_name=self.db_path)
        assert items_result.success and catalog_result.success
        items = items_result.data["items_by_order"].get((order.api_account_id, order.orderNumber), [])
        return actions.estimate_order_profit(order=order, order_items=items, catalog=catalog_result.data)

    def test_projection_matches_the_actual_ui_engine_and_uses_latest_account_bound_items(self):
        order = self._seed()
        expected = self._manual_payload(order)
        result = read_order_profit_export_payload(order=order, db_name=self.db_path)
        assert result.success, result.message
        payload = result.data["estimated_profit_payload"]
        assert payload == expected
        assert payload["estimated_profit_ready"], payload["estimated_profit_missing_reasons"]
        assert payload["estimated_profit"] == pytest.approx(180)
        assert payload["estimated_profit_detail"]["results"]["total_costs"] == pytest.approx(20)
        assert payload["estimated_profit_detail"]["summary"]["item_quantity_total"] == 2
        assert result.data["api_account_id"] == 1

    def test_prepared_snapshot_is_stable_when_current_costs_later_change(self):
        order = self._seed()
        prepared = read_order_profit_export_payload(order=order, db_name=self.db_path)
        snapshot = deepcopy(prepared.data["estimated_profit_payload"])
        with Session(get_engine(self.db_path)) as session:
            cost = session.exec(select(StockTx).where(StockTx.item_id == 1)).one()
            cost.unit_cost = 30
            session.add(cost)
            session.commit()
        refreshed = read_order_profit_export_payload(order=order, db_name=self.db_path)
        assert prepared.data["estimated_profit_payload"] == snapshot
        assert refreshed.data["estimated_profit_payload"]["estimated_profit"] == pytest.approx(140)

    def test_missing_items_keep_the_ui_engine_unavailable_result_without_fake_zero_costs(self):
        order = self._seed(with_items=False)
        result = read_order_profit_export_payload(order=order, db_name=self.db_path)
        assert result.success
        payload = result.data["estimated_profit_payload"]
        assert payload == self._manual_payload(order)
        assert not payload["estimated_profit_ready"] and payload["estimated_profit"] is None
        assert payload["estimated_profit_missing_reasons"]
        assert payload["estimated_profit_detail"]["results"] == {}

    def test_missing_stock_cost_is_explicitly_unavailable_instead_of_presenting_profit(self):
        order = self._seed(with_stock_cost=False)
        result = read_order_profit_export_payload(order=order, db_name=self.db_path)
        assert result.success
        payload = result.data["estimated_profit_payload"]
        assert payload == self._manual_payload(order)
        assert not payload["estimated_profit_ready"] and payload["estimated_profit"] is None
        assert payload["estimated_profit_missing_reasons"]

    def test_foreign_currency_retains_the_existing_engine_refusal(self):
        order = self._seed(currency="EUR")
        result = read_order_profit_export_payload(order=order, db_name=self.db_path)
        payload = result.data["estimated_profit_payload"]
        assert result.success and payload == self._manual_payload(order)
        assert not payload["estimated_profit_ready"] and payload["estimated_profit"] is None
        assert any("EUR" in reason for reason in payload["estimated_profit_missing_reasons"])


@pytest.mark.parametrize("failed_reader", ["load_order_items_for_order_numbers", "load_order_profit_catalog"])
def test_failed_read_preserves_its_result_and_diagnostics_without_a_snapshot(failed_reader):
    failure = Result.fail("Source unavailable", close_dialog=False, data={"source_error": "profit-data", "retryable": True})
    with patch.object(profit, "load_order_items_for_order_numbers", return_value=Result.ok(
        "items", data={"items_by_order": {}}
    )), patch.object(profit, "load_order_profit_catalog", return_value=Result.ok("catalog", data={})), patch.object(
        profit, failed_reader, return_value=failure
    ), patch.object(profit, "estimate_order_profit") as estimator:
        result = read_order_profit_export_payload(order=SimpleNamespace(orderNumber="O-1", api_account_id=1),
                                                  db_name="unused.sqlite3")
    assert result is failure
    estimator.assert_not_called()
    assert "estimated_profit_payload" not in result.data


def test_profit_processor_import_graph_does_not_load_views_or_ai():
    script = """
import builtins
original_import = builtins.__import__
def domain_import(name, globals=None, locals=None, fromlist=(), level=0):
    names = [name, *(f'{name}.{child}' for child in (fromlist or ()) if isinstance(child, str))]
    if any(value.startswith('AI.') or '.views' in value for value in names):
        raise AssertionError(f'Domain operation imported an application view or AI module: {name}')
    return original_import(name, globals, locals, fromlist, level)
builtins.__import__ = domain_import
from Orders.processors.profit_export import read_order_profit_export_payload
"""
    completed = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
