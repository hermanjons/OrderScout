"""Profit account selection reaches the real shared engine without credentials."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from jsonschema import Draft202012Validator
import pytest
from sqlmodel import Session, select

from AI.processors import tools
from Core.utils.model_utils import get_engine
from Finance.processors.profit import read_profit_estimate
from Listing.models.models import ListingProduct, ListingProductStockSnapshot
from Orders.models.trendyol.models import OrderData, OrderHeader, OrderItem
from Orders.processors.trendyol.pipeline import get_latest_orders_filtered
from Orders.views.actions import estimate_orders_profit_summary
from Testing.processors.business_agent_fixtures import seed_business_fixture


@pytest.fixture
def database(tmp_path):
    database = str(tmp_path / "profit-accounts.sqlite3")
    now = datetime(2026, 10, 23, 12, tzinfo=timezone(timedelta(hours=3)))
    seed_business_fixture(database, isolation_root=tmp_path, now=now)
    with Session(get_engine(database)) as session:
        listing = ListingProduct(
            api_account_id=102, product_id="B-CUP", title="Other store cup",
            barcode="PILOT-KUPA-BAR", stock_code="PILOT-KUPA", stock_item_id=401,
            sale_price=9000, vat_rate=0, on_sale=True, approved=True,
        )
        session.add(listing)
        session.flush()
        session.add(ListingProductStockSnapshot(listing_id=listing.pk, stock_item_id=401, qty=1))
        # Both stores deliberately have the same order number and product barcode.
        for model in (OrderData, OrderHeader, OrderItem):
            row = session.exec(select(model).where(model.api_account_id == 102)).one()
            row.orderNumber = "PILOT-A-NEW-1"
            session.add(row)
        latest = session.exec(select(OrderData).where(
            OrderData.api_account_id == 101, OrderData.orderNumber == "PILOT-A-NEW-1",
        )).one()
        stale = latest.model_dump(exclude={"pk"})
        stale.update(lastModifiedDate=latest.lastModifiedDate - 1000,
                     packageTotalPrice=500, totalPrice=500)
        session.add(OrderData(**stale))
        # An incomplete cancelled order cannot block or inflate estimated profit.
        session.add(OrderData(
            api_account_id=101, orderNumber="CANCELLED-PROFIT-TEST", id=999999,
            orderDate=latest.orderDate, lastModifiedDate=latest.lastModifiedDate,
            status="Cancelled", shipmentPackageStatus="Cancelled",
            packageTotalPrice=1000000, currencyCode="TRY",
        ))
        session.commit()
    return database


@pytest.mark.parametrize("tool_name,key", [
    ("finance.profit_estimate", "estimated_profit"), ("finance.profit_amount", "amount"),
])
def test_native_contract_and_handler_preserve_each_store_scope(database, tool_name, key):
    tool = tools.registered_tools()[tool_name]
    assert tool.canonical_callable == "Finance.processors.profit.read_profit_estimate"
    for accounts, expected, revenue, count in [
        ([101], 800, 1000, 1), ([102], 8900, 9000, 1), (None, 9700, 10000, 2),
    ]:
        arguments = {"period": "all", "start_date": "2026-10-22", "end_date": "2026-10-22"}
        if accounts is not None:
            arguments["api_account_ids"] = accounts
        assert not list(Draft202012Validator(tool.parameters).iter_errors(arguments))
        result = tool.handler(db_name=database, **arguments)
        assert result.success, result.message
        assert result.data["estimated_profit_ready"]
        # 1000 - 2*100 = 800; other store 9000 - 1*100 = 8900.
        assert result.data[key] == pytest.approx(expected)
        assert result.data["revenue"] == revenue
        assert result.data["orders"] == count
        assert result.data["requested_api_account_ids"] == (accounts or [])
        assert [row["api_account_id"] for row in result.data["account_scopes"]] == (accounts or [101, 102])
        assert result.data["start_ms"] < result.data["end_ms"]


def test_manual_summary_filters_accounts_and_deduplicates_snapshots(database):
    all_orders = get_latest_orders_filtered(db_name=database).data["orders"]
    scoped = [row for row in all_orders if row.orderNumber == "PILOT-A-NEW-1"]
    scoped.append(SimpleNamespace(orderNumber="PILOT-A-NEW-1", api_account_id=101,
                                  lastModifiedDate=0, packageTotalPrice=1))
    for accounts, expected in [([101], 800), ([102], 8900), (None, 9700)]:
        result = estimate_orders_profit_summary(orders=scoped, db_name=database, api_account_ids=accounts)
        assert result.success, result.message
        assert result.data["estimated_profit"] == pytest.approx(expected)
        assert result.data["order_count"] == (1 if accounts else 2)
        assert {row["api_account_id"] for row in result.data["rows"]} == set(accounts or [101, 102])


def test_missing_currency_blocks_only_its_scoped_total(database):
    primary = read_profit_estimate(db_name=database, api_account_ids=[101])
    assert primary.success and primary.data["estimated_profit"] is None
    assert primary.data["partial_estimated_profit"] == pytest.approx(2000)
    assert primary.data["complete_order_count"] == 4
    assert primary.data["incomplete_order_count"] == 1
    assert any("USD" in reason for reason in primary.data["missing_reasons"])
    secondary = read_profit_estimate(db_name=database, api_account_ids=[102])
    assert secondary.success and secondary.data["estimated_profit"] == pytest.approx(8900)


@pytest.mark.parametrize("account_ids", [[], [0], [-1], [True], ["101"]])
def test_invalid_account_scope_cannot_expand_to_all_accounts(database, account_ids):
    for tool_name in ("finance.profit_estimate", "finance.profit_amount"):
        schema = tools.registered_tools()[tool_name].parameters
        assert list(Draft202012Validator(schema).iter_errors({"api_account_ids": account_ids}))
    result = read_profit_estimate(db_name=database, api_account_ids=account_ids)
    assert not result.success


def test_unknown_account_does_not_fall_back_to_all_accounts(database):
    result = tools.finance_profit_amount(db_name=database, period="all", api_account_ids=[999])
    assert result.success and result.data["orders"] == 0
    assert result.data["requested_api_account_ids"] == [999]
    assert result.data["revenue"] == 0
