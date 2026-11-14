from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PyQt6.QtCore import QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from sqlmodel import Session, select

from Account.models.models import ApiAccount
from Core.db.bootstrap import init_database
from Core.services.business_refresh import (
    BusinessRefreshService, account_uses_local_data, business_refresh_signals,
    refresh_business_data,
)
from Core.utils.model_utils import get_engine
from Feedback.processors.pipeline import Result


def wait_for(predicate, timeout=4.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        QTest.qWait(5)
    assert predicate(), "Background operation did not finish"


def outcome(*, success=True, cursors=None):
    return Result.ok("", close_dialog=False, data={
        "remote_success": success, "cursors": cursors or {},
        "domains": {domain: {"success": success, "message": "Yerel kayıtlar yenilendi.",
                              "mode": "local", "changed": False}
                    for domain in ("orders", "listing", "finance")},
    })


def test_synthetic_marker_wins_even_with_accidentally_added_credentials():
    account = SimpleNamespace(account_id="123", api_key="unused", api_secret="unused",
                              extra_config={"data_origin": "synthetic", "environment": "production"})
    assert account_uses_local_data(account)
    account.extra_config = {"environment": "local"}
    assert account_uses_local_data(account)
    account.extra_config = {"auto_sync_mode": "local"}
    assert account_uses_local_data(account)
    account.extra_config = {}
    account.api_key = None
    assert account_uses_local_data(account)


def test_isolated_synthetic_cycle_never_reaches_marketplace_adapters(tmp_path):
    db_name = str(tmp_path / "local.sqlite3")
    init_database(db_name)
    with Session(get_engine(db_name)) as session:
        session.add(ApiAccount(account_id="local-1", comp_name="Marmara-demo", platform="TRENDYOL",
                               api_key="fabricated", api_secret="fabricated",
                               extra_config={"data_origin": "synthetic", "environment": "local",
                                             "auto_sync_mode": "local"}))
        session.commit()
    with patch("Orders.processors.background_refresh.refresh_orders", new_callable=AsyncMock) as orders, \
            patch("Listing.processors.background_refresh.refresh_listings", new_callable=AsyncMock) as listings, \
            patch("Finance.processors.background_refresh.refresh_finance", new_callable=AsyncMock) as finance:
        result = asyncio.run(refresh_business_data(db_name=db_name))
    assert result.success
    assert not any(adapter.called for adapter in (orders, listings, finance))
    assert all(row["mode"] == "local" and row["local_accounts"] == 1
               for row in result.data["domains"].values())
    assert all("yapılandırılmadı" in row["message"] for row in result.data["domains"].values())


def test_worker_keeps_gui_responsive_and_coalesces_requests(tmp_path):
    gui_thread = threading.get_ident()
    calls = []
    active = 0
    peak = 0
    release = threading.Event()

    async def callback(**kwargs):
        nonlocal active, peak
        calls.append((threading.get_ident(), kwargs))
        active += 1
        peak = max(peak, active)
        try:
            while len(calls) == 1 and not release.is_set():
                await asyncio.sleep(0.005)
            await asyncio.sleep(0.02)
            return outcome(cursors={"orders": {"until_ms": 123}})
        finally:
            active -= 1

    service = BusinessRefreshService(db_name=str(tmp_path / "data.sqlite3"), callback=callback)
    ticks = []
    gui_timer = QTimer()
    gui_timer.setInterval(5)
    gui_timer.timeout.connect(lambda: ticks.append(True))
    gui_timer.start()
    try:
        service.start()
        wait_for(lambda: len(calls) == 1)
        for _ in range(20):
            service.request_refresh()
        wait_for(lambda: len(ticks) >= 3)
        release.set()
        wait_for(lambda: len(calls) == 2 and service._worker is None)
        assert peak == 1
        assert all(thread_id != gui_thread for thread_id, _ in calls)
        assert calls[1][1]["cursors"] == {"orders": {"until_ms": 123}}
        assert calls[1][1]["allow_remote"] is False
    finally:
        release.set()
        gui_timer.stop()
        service.stop()
        wait_for(lambda: service._worker is None)


def test_failures_back_off_without_advancing_cursors_or_showing_dialogs(tmp_path):
    now = [0.0]
    calls = []

    async def callback(**kwargs):
        calls.append(kwargs)
        return outcome(success=False)

    service = BusinessRefreshService(db_name=str(tmp_path / "data.sqlite3"), callback=callback,
                                     clock=lambda: now[0])
    try:
        service.start()
        wait_for(lambda: len(calls) == 1 and service._worker is None)
        assert service._next_remote == 30
        for _ in range(10):
            service._tick()
        assert len(calls) == 1
        now[0] = 30
        service._tick()
        wait_for(lambda: len(calls) == 2 and service._worker is None)
        assert service._next_remote == 90
        assert service._cursors == {}
    finally:
        service.stop()
        wait_for(lambda: service._worker is None)


def test_local_database_change_reloads_without_bypassing_remote_interval(tmp_path):
    path = tmp_path / "data.sqlite3"
    init_database(str(path))
    calls = []
    notifications = []

    async def callback(**kwargs):
        calls.append(kwargs)
        return await refresh_business_data(**kwargs)

    def refreshed(domain, payload):
        notifications.append(domain)

    service = BusinessRefreshService(db_name=str(path), callback=callback)
    business_refresh_signals.refreshed.connect(refreshed)
    try:
        service.start()
        wait_for(lambda: len(calls) == 1 and service._worker is None)
        notifications.clear()
        with Session(get_engine(str(path))) as session:
            session.add(ApiAccount(account_id="2", comp_name="Yeni Firma-demo", platform="TRENDYOL",
                                   extra_config={"auto_sync_mode": "local"}))
            session.commit()
        service._tick()
        wait_for(lambda: len(calls) == 2 and service._worker is None)
        assert calls[1]["allow_remote"] is False
        assert set(notifications) == {"orders", "listing", "finance"}
        assert "Son kontrol:" in business_refresh_signals.statuses["orders"]
    finally:
        business_refresh_signals.refreshed.disconnect(refreshed)
        service.stop()
        wait_for(lambda: service._worker is None)


def test_stop_cancels_inflight_requests_and_retains_worker_until_finished(tmp_path):
    entered = threading.Event()
    cancelled = threading.Event()

    async def callback(**kwargs):
        entered.set()
        try:
            await asyncio.sleep(3600)
        finally:
            cancelled.set()

    service = BusinessRefreshService(db_name=str(tmp_path / "data.sqlite3"), callback=callback)
    service.start()
    wait_for(entered.is_set)
    assert service.stop() is False
    wait_for(lambda: service._worker is None)
    assert cancelled.is_set()
    assert not service._timer.isActive()


def test_domain_timeout_drains_child_requests_before_next_domain():
    cancelled = threading.Event()
    account = SimpleNamespace(pk=1, account_id="123", api_key="key", api_secret="secret",
                              platform="TRENDYOL", extra_config={})

    async def child_request():
        try:
            await asyncio.sleep(3600)
        finally:
            cancelled.set()

    async def orders(*args, **kwargs):
        asyncio.create_task(child_request())
        await asyncio.sleep(3600)

    async def listings(*args, **kwargs):
        assert cancelled.is_set(), "Previous domain's HTTP children must finish first"
        return Result.ok("", data={"cursor": {"page": 1}})

    with patch("Account.processors.pipeline.get_active_companies", return_value=Result.ok("", data={"records": [account]})), \
            patch("Orders.processors.background_refresh.refresh_orders", side_effect=orders), \
            patch("Listing.processors.background_refresh.refresh_listings", side_effect=listings), \
            patch("Finance.processors.background_refresh.refresh_finance", new_callable=AsyncMock,
                  return_value=Result.ok("", data={"cursor": {"until_ms": 100}})):
        result = asyncio.run(refresh_business_data(db_name="unused", domain_timeout=0.02,
                                                   cursors={"orders": {"until_ms": 50}}))
    assert result.success
    assert result.data["remote_success"] is False
    assert result.data["cursors"]["orders"] == {"until_ms": 50}
    assert result.data["cursors"]["listing"] == {"page": 1}
    assert cancelled.is_set()


def test_listing_cursor_traverses_both_states_without_pruning_partial_scan():
    from Listing.processors.background_refresh import refresh_listings

    account = SimpleNamespace(pk=1, account_id="123", api_key="key", api_secret="secret", extra_config={})
    fetched = Result.ok("", data={"items": [{"product_id": "P1"}],
                                 "per_account": [{"meta": {"items": [{}], "totalPages": 3}}]})
    with patch("Listing.processors.trendyol.pipeline.fetch_listings_all", new_callable=AsyncMock, return_value=fetched) as fetch, \
            patch("Listing.processors.pipeline.save_listings_to_db", return_value=Result.ok("", data={"changed": True})) as save:
        first = asyncio.run(refresh_listings([account], db_name="isolated", cursor={}))
        assert first.success and first.data["cursor"]["1"]["page"] == 1
        assert first.data["has_more"] is True
        assert save.call_args.kwargs["prune_missing"] is False
        assert save.call_args.kwargs["db_name"] == "isolated"
        fetched.data["per_account"][0]["meta"]["totalPages"] = 1
        last = asyncio.run(refresh_listings([account], db_name="isolated", cursor={
            "1": {"approved": False, "page": 0},
        }))
        assert last.data["cursor"]["1"] == {"approved": True, "page": 0, "token": ""}
        assert last.data["has_more"] is False
        assert fetch.call_args.kwargs["approved"] is False


def test_finance_page_cap_is_partial_and_explicit_database_reaches_both_savers():
    from Finance.processors.trendyol import pipeline as finance

    fake_api = SimpleNamespace(get_settlements=AsyncMock(return_value=Result.ok("", data={
        "content": [{"id": str(n)} for n in range(10)], "totalPages": 4,
    })))
    with patch.object(finance, "TrendyolFinanceApi", return_value=fake_api):
        limited = asyncio.run(finance.fetch_settlements_for_accounts(
            [[1, "key", "secret", "123"]], transaction_date_start=1700000000000,
            transaction_date_end=1700000001000, page_size=10, max_pages=1,
        ))
    assert limited.data["errors"]
    assert limited.data["account_summaries"][0]["failed"] is True

    empty = Result.ok("", data={"records": [], "errors": [], "account_summaries": []})
    with patch.object(finance, "fetch_settlements_for_accounts", new_callable=AsyncMock, return_value=empty), \
            patch.object(finance, "fetch_other_financials_for_accounts", new_callable=AsyncMock, return_value=empty), \
            patch.object(finance, "save_finance_transactions_to_db", return_value=Result.ok("", data={"counts": {}})) as save_tx, \
            patch.object(finance, "save_finance_cargo_items_to_db", return_value=Result.ok("", data={"counts": {}})) as save_cargo:
        result = asyncio.run(finance.sync_finance_for_accounts(
            [[1, "key", "secret", "123"]], transaction_date_start=1700000000000,
            transaction_date_end=1700000001000, db_name="isolated",
        ))
    assert result.success
    assert save_tx.call_args.kwargs["db_name"] == "isolated"
    assert save_cargo.call_args.kwargs["db_name"] == "isolated"


def test_orders_tab_has_no_manual_refresh_controls():
    from Orders.views.views import OrdersTab

    tab = OrdersTab()
    try:
        assert not hasattr(tab, "fetch_button")
        assert not hasattr(tab, "auto_fetch_toggle")
        tab._on_background_status("orders", "Yerel kayıtlar yenilendi. Son kontrol: 10:20:30")
        assert "10:20:30" in tab.status_label.text()
    finally:
        tab.close()
        tab.deleteLater()


def test_stock_sync_is_scoped_and_idempotent(tmp_path):
    from Listing.models import ListingProduct, ListingProductStockSnapshot
    from Orders.models.trendyol.models import OrderHeader
    from Orders.processors.background_refresh import sync_saved_order_stock
    from Stock.models import StockTx
    from Stock.processors import pipeline as stock

    path = str(tmp_path / "stock.sqlite3")
    other = str(tmp_path / "unrelated.sqlite3")
    init_database(path)
    init_database(other)
    with stock.database_scope(path):
        assert stock.create_item(sku="SKU-demo", name="Ürün-demo").success
        assert stock.create_warehouse(name="Ana Depo-demo").success
        item = stock.list_items().data["records"][0]
        warehouse = stock.list_warehouses().data["records"][0]
        assert stock.manual_in(item_id=item.pk, warehouse_id=warehouse.pk, qty=20, unit_cost=100).success
    with Session(get_engine(path)) as session:
        session.add(ApiAccount(pk=1, account_id="local", comp_name="Şirket-demo", platform="TRENDYOL"))
        session.add(OrderHeader(pk=1, orderNumber="order-demo", api_account_id=1))
        session.add(ListingProduct(pk=1, api_account_id=1, product_id="product-demo",
                                   product_code="9001", title="Ürün-demo", stock_item_id=item.pk))
        session.add(ListingProductStockSnapshot(listing_id=1, stock_item_id=item.pk, qty=2, status="append"))
        session.commit()
    line = {"api_account_id": 1, "orderNumber": "order-demo", "quantity": 3,
            "productCode": "9001", "orderLineItemStatusName": "Created"}
    with patch.object(stock, "DB_NAME", other):
        first = sync_saved_order_stock([line], db_name=path)
        again = sync_saved_order_stock([line], db_name=path)
    assert first.success and first.data["tx_created"] == 1, first.message
    assert again.success and again.data["tx_duplicate"] == 1, again.message
    with Session(get_engine(other)) as session:
        assert session.exec(select(StockTx)).all() == []
    with Session(get_engine(path)) as session:
        transactions = session.exec(select(StockTx)).all()
        assert len(transactions) == 2
        order_out = [row for row in transactions if row.order_header_id == 1]
        assert len(order_out) == 1 and order_out[0].qty == 6
