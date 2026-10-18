from __future__ import annotations

import inspect
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QLabel

import Orders.views.orders_manager_window as orders_manager_window_module
import Orders.views.returns_manager_window as returns_manager_window_module
import Orders.views.views as orders_views_module
import Orders.views.actions as orders_actions
from Core.views import RecordWorkspaceListDelegate
from Feedback.processors.pipeline import Result
from Orders.constants.trendyol.constants import TRENDYOL_RETURN_STATUS_LIST
from Orders.views.actions import refresh_order_status_filter
from Orders.views.views import OrdersManagerWindow, ReturnsManagerWindow


class _FakeSignal:
    def __init__(self) -> None:
        self._slots = []

    def connect(self, slot) -> None:
        self._slots.append(slot)

    def emit(self, payload=None) -> None:
        for slot in list(self._slots):
            if payload is None:
                slot()
            else:
                slot(payload)


class _ImmediateWorker:
    def __init__(self, func, *args, parent=None, **kwargs) -> None:
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.result_ready = _FakeSignal()
        self.finished = _FakeSignal()

    def start(self) -> None:
        self.result_ready.emit(self.func(*self.args, **self.kwargs))
        self.finished.emit()


class TestOrdersViews(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_orders_manager_window_disables_scaffold_action_island(self) -> None:
        widget = OrdersManagerWindow()
        self.addCleanup(widget.close)
        self.assertFalse(widget._workspace._show_editor_actions_card)
        self.assertFalse(widget._workspace.editor_actions_host.isVisible())
        self.assertFalse(widget._workspace.editor_actions_card.isVisible())
        self.assertEqual(widget._workspace.editor_scroll.viewportMargins().right(), 12)
        self.assertEqual(widget._workspace._editor_canvas_color, "#FFFFFF")
        self.assertEqual(widget._workspace._editor_surface_color, "#FFFFFF")
        self.assertIsInstance(widget.list_widget.itemDelegate(), RecordWorkspaceListDelegate)

    def test_orders_views_module_is_now_facade_only(self) -> None:
        source = inspect.getsource(orders_views_module)
        self.assertIn("class OrdersTab(", source)
        self.assertNotIn("class OrdersListModel(", source)
        self.assertNotIn("class OrdersListDelegate(", source)
        self.assertNotIn("class OrdersListWidget(", source)
        self.assertNotIn("class OrdersManagerWindow(", source)
        self.assertNotIn("class OrdersWorkspaceBehaviorAdapter(", source)

    def test_orders_tab_starts_stock_auto_deduct_on_orders_persisted(self) -> None:
        calls: list[dict] = []

        def fake_auto_deduct(**kwargs):
            calls.append(dict(kwargs))
            return Result.ok("ok", close_dialog=False, data={"tx_created": 1})

        with patch.object(orders_views_module, "SyncWorker", _ImmediateWorker), \
             patch("Stock.views.actions.action_auto_deduct_order_items", side_effect=fake_auto_deduct):
            widget = orders_views_module.OrdersTab()
            self.addCleanup(widget.close)
            widget._on_orders_persisted_for_stock_sync(
                {
                    "source": "test",
                    "order_item_list": [
                        {
                            "api_account_id": 1,
                            "orderNumber": "ORD-1",
                            "quantity": 1,
                            "barcode": "B-1",
                            "orderLineItemStatusName": "Created",
                        }
                    ],
                }
            )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["created_by"], "orders:auto")
        self.assertEqual(calls[0]["order_item_list"][0]["orderNumber"], "ORD-1")
        self.assertEqual(widget._order_stock_sync_workers, [])

    def test_orders_manager_window_module_drops_legacy_workspace_fallbacks(self) -> None:
        source = inspect.getsource(orders_manager_window_module)
        self.assertNotIn("fallback_total_width", source)
        self.assertNotIn('hasattr(self, "_workspace_shell")', source)
        self.assertNotIn('hasattr(self, "_workspace")', source)
        self.assertNotIn('hasattr(self, "list_widget")', source)
        self.assertNotIn('hasattr(self, "bulk_metric_', source)
        self.assertNotIn('hasattr(self, "detail_tabs")', source)
        self.assertNotIn('hasattr(self, "detail_tab_hint")', source)
        self.assertNotIn('hasattr(self, "btn_approve_return")', source)
        self.assertNotIn('getattr(self.list_widget', source)
        self.assertNotIn('_selection_lock_overlay', source)
        self.assertNotIn('_bulk_right_focus_ring', source)
        self.assertNotIn("_splitter_guard", source)
        self.assertNotIn("_splitter_settle_timer", source)
        self.assertNotIn("def _release_splitter_guard(", source)
        self.assertNotIn("def _splitter_total_size(", source)
        self.assertNotIn("def _snap_splitter(", source)
        self.assertNotIn("def _restart_splitter_settle_timer(", source)
        self.assertNotIn("def _settle_orders_splitter(", source)
        self.assertNotIn("def _on_orders_splitter_moved(", source)
        self.assertNotIn("def _on_panel_sidebar_toggled(", source)
        self.assertNotIn("def _on_order_card_clicked(", source)
        self.assertNotIn("def _on_order_list_blank_clicked(", source)
        self.assertNotIn("def _on_order_select_button_clicked(", source)
        self.assertNotIn("def _sync_selection_sidebar_state(", source)
        self.assertNotIn("def _set_left_panel_highlight(", source)
        self.assertNotIn("def _open_selection_panel(", source)
        self.assertNotIn("def _close_selection_panel(", source)

    def test_returns_manager_window_module_drops_legacy_workspace_fallbacks(self) -> None:
        source = inspect.getsource(returns_manager_window_module)
        self.assertNotIn("fallback_total_width", source)
        self.assertNotIn('hasattr(self, "_workspace_shell")', source)
        self.assertNotIn('hasattr(self, "_workspace")', source)
        self.assertNotIn('hasattr(self, "list_widget")', source)
        self.assertNotIn('hasattr(self, "bulk_metric_', source)
        self.assertNotIn('hasattr(self, "detail_tabs")', source)
        self.assertNotIn('hasattr(self, "detail_tab_hint")', source)
        self.assertNotIn('hasattr(self, "btn_approve_return")', source)
        self.assertNotIn('getattr(self.list_widget', source)
        self.assertNotIn("_selection_lock_overlay", source)
        self.assertNotIn("_bulk_right_focus_ring", source)
        self.assertNotIn("_splitter_guard", source)
        self.assertNotIn("_splitter_settle_timer", source)
        self.assertNotIn("def _release_splitter_guard(", source)
        self.assertNotIn("def _splitter_total_size(", source)
        self.assertNotIn("def _snap_splitter(", source)
        self.assertNotIn("def _restart_splitter_settle_timer(", source)
        self.assertNotIn("def _settle_orders_splitter(", source)
        self.assertNotIn("def _on_orders_splitter_moved(", source)

    def test_orders_and_returns_have_separate_manager_modules(self) -> None:
        orders_source = inspect.getsource(orders_manager_window_module)
        returns_source = inspect.getsource(returns_manager_window_module)
        self.assertIn("class OrdersManagerWindow(", orders_source)
        self.assertNotIn("window_mode", inspect.signature(OrdersManagerWindow.__init__).parameters)
        self.assertIn("class ReturnsManagerWindow(", returns_source)
        self.assertNotIn("window_mode", inspect.signature(ReturnsManagerWindow.__init__).parameters)

    def test_orders_windows_use_core_select_hook_delegate(self) -> None:
        orders_source = inspect.getsource(orders_manager_window_module)
        returns_source = inspect.getsource(returns_manager_window_module)
        self.assertIn("class OrdersListDelegate(RecordWorkspaceListDelegate):", orders_source)
        self.assertIn("class OrdersListDelegate(RecordWorkspaceListDelegate):", returns_source)
        self.assertIn("self._paint_hook_button(", orders_source)
        self.assertIn("self._handle_hook_activated(model, index, next_selected)", orders_source)
        self.assertIn("self._paint_hook_button(", returns_source)
        self.assertIn("self._handle_hook_activated(model, index, next_selected)", returns_source)

    def test_detail_cache_key_includes_api_account_for_orders(self) -> None:
        widget = OrdersManagerWindow()
        self.addCleanup(widget.close)

        cache_key = widget._detail_cache_key_for_order(
            SimpleNamespace(orderNumber="ORD-1", api_account_id=9, _is_return=False)
        )

        self.assertEqual(cache_key, "order:9:ORD-1")

    def test_orders_manager_window_can_inject_missing_order_numbers_into_loaded_set(self) -> None:
        widget = OrdersManagerWindow()
        self.addCleanup(widget.close)

        existing = SimpleNamespace(orderNumber="ORD-READY", api_account_id=1)
        missing = SimpleNamespace(orderNumber="ORD-HISTORY", api_account_id=2)
        widget.list_widget.orders = [existing]
        widget.list_widget.filtered_orders = [existing]

        with patch.object(orders_manager_window_module, "load_orders_by_numbers") as load_mock:
            load_mock.return_value = SimpleNamespace(
                success=True,
                message="ok",
                data={"records": [missing]},
            )
            res = widget.ensure_order_numbers_loaded(["ORD-HISTORY"])

        self.assertTrue(res.success)
        loaded_numbers = [str(getattr(order, "orderNumber", "") or "") for order in widget.list_widget.orders]
        self.assertEqual(loaded_numbers, ["ORD-HISTORY", "ORD-READY"])

    def test_orders_manager_window_loads_records_for_current_status_filter(self) -> None:
        widget = OrdersManagerWindow()
        self.addCleanup(widget.close)

        widget.order_status_filter.addItem("Oluşturuldu", data="Created")
        idx = widget.order_status_filter.findData("Created")
        if idx >= 0:
            widget.order_status_filter.setCurrentIndex(idx)

        with patch.object(orders_manager_window_module, "load_orders_for_source_filters") as load_mock:
            load_mock.return_value = SimpleNamespace(success=True, data={"records": []})
            res = widget._load_records_for_window()

        self.assertTrue(res.success)
        load_mock.assert_called_once()
        kwargs = load_mock.call_args.kwargs
        self.assertEqual(kwargs["shipment_status_code"], "Created")
        self.assertIn("platform_code", kwargs)
        self.assertIn("date_from", kwargs)
        self.assertIn("date_to", kwargs)

    def test_returns_manager_window_loads_records_for_current_source_filters(self) -> None:
        widget = ReturnsManagerWindow()
        self.addCleanup(widget.close)

        widget.order_status_filter.addItem("Aksiyon Bekliyor", data="WaitingInAction")
        idx = widget.order_status_filter.findData("WaitingInAction")
        if idx >= 0:
            widget.order_status_filter.setCurrentIndex(idx)

        with patch.object(returns_manager_window_module, "load_returns_for_source_filters") as load_mock:
            load_mock.return_value = SimpleNamespace(success=True, data={"records": []})
            res = widget._load_records_for_window()

        self.assertTrue(res.success)
        load_mock.assert_called_once()
        kwargs = load_mock.call_args.kwargs
        self.assertIn(kwargs["shipment_status_code"], {"WaitingInAction", "Aksiyon Bekliyor"})
        self.assertIn("platform_code", kwargs)
        self.assertIn("date_from", kwargs)
        self.assertIn("date_to", kwargs)

    def test_orders_manager_window_preserves_selected_status_on_refresh(self) -> None:
        widget = OrdersManagerWindow()
        self.addCleanup(widget.close)

        widget.list_widget.orders = [
            SimpleNamespace(shipmentPackageStatus="Created", status="Created"),
            SimpleNamespace(shipmentPackageStatus="Shipped", status="Shipped"),
        ]
        refresh_order_status_filter(widget.order_status_filter, widget.list_widget.orders, include_known_statuses=True)

        shipped_idx = widget.order_status_filter.findData("Shipped")
        self.assertGreaterEqual(shipped_idx, 0)
        widget.order_status_filter.setCurrentIndex(shipped_idx)

        widget._refresh_order_status_filter()

        self.assertEqual(str(widget.order_status_filter.currentData() or ""), "Shipped")

    def test_returns_manager_window_preserves_selected_status_on_refresh(self) -> None:
        widget = ReturnsManagerWindow()
        self.addCleanup(widget.close)

        widget.list_widget.orders = [
            SimpleNamespace(claimItemStatus="WaitingInAction", status="WaitingInAction"),
            SimpleNamespace(claimItemStatus="Created", status="Created"),
        ]
        refresh_order_status_filter(widget.order_status_filter, widget.list_widget.orders, include_known_statuses=False)

        created_idx = widget.order_status_filter.findData("Created")
        self.assertGreaterEqual(created_idx, 0)
        widget.order_status_filter.setCurrentIndex(created_idx)

        widget._refresh_order_status_filter()

        self.assertEqual(str(widget.order_status_filter.currentData() or ""), "Created")

    def test_returns_manager_window_defaults_to_waiting_action_filter_when_available(self) -> None:
        widget = ReturnsManagerWindow()
        self.addCleanup(widget.close)

        widget.order_status_filter.addItem("Aktif Iadeler", data="__open_returns__")
        widget.order_status_filter.addItem("Aksiyon Bekliyor", data="WaitingInAction")

        widget._apply_default_order_status_selection()

        self.assertEqual(str(widget.order_status_filter.currentText() or ""), "Aksiyon Bekliyor")

    def test_orders_manager_ignores_stale_filter_worker_results(self) -> None:
        widget = OrdersManagerWindow()
        self.addCleanup(widget.close)

        old_row = SimpleNamespace(orderNumber="OLD", api_account_id=1)
        new_row = SimpleNamespace(orderNumber="NEW", api_account_id=1)
        widget.list_widget.orders = [old_row, new_row]
        widget.list_widget.filtered_orders = [old_row, new_row]
        widget._sync_default_filter_date_range_if_unmodified()
        widget._orders_source_signature = widget._current_orders_source_signature()

        workers = []

        class _ManualWorker:
            def __init__(self) -> None:
                self.result_ready = _FakeSignal()
                self.finished = _FakeSignal()
                self.started = False

            def start(self) -> None:
                self.started = True

            def isRunning(self) -> bool:
                return self.started

            def requestInterruption(self) -> None:
                return

            def wait(self, _ms: int = 0) -> bool:
                return True

            def deleteLater(self) -> None:
                return

        def fake_start_filter_worker(_parent, _list_widget, _filters, **kwargs):
            self.assertFalse(kwargs.get("apply_on_result", True))
            worker = _ManualWorker()
            workers.append(worker)
            return worker

        with patch.object(orders_manager_window_module, "start_filter_worker", side_effect=fake_start_filter_worker):
            widget.global_search.setText("old")
            widget.apply_filters()
            widget.global_search.setText("new")
            widget.apply_filters()

        self.assertEqual(len(workers), 2)

        workers[0].result_ready.emit(Result.ok("old", close_dialog=False, data={"filtered": [old_row]}))
        workers[0].finished.emit()
        self.assertEqual(widget.list_widget.filtered_orders, [old_row, new_row])

        workers[1].result_ready.emit(Result.ok("new", close_dialog=False, data={"filtered": [new_row]}))
        workers[1].finished.emit()
        self.assertEqual(widget.list_widget.filtered_orders, [new_row])
        self.assertIsNone(widget.filter_worker)

    def test_order_profit_decoration_does_not_start_duplicate_worker_for_pending_order(self) -> None:
        widget = OrdersManagerWindow()
        self.addCleanup(widget.close)

        workers = []

        class _ManualWorker:
            def __init__(self, _func, *args, **_kwargs) -> None:
                self.args = args
                self.result_ready = _FakeSignal()
                self.finished = _FakeSignal()
                workers.append(self)

            def start(self) -> None:
                return

            def isRunning(self) -> bool:
                return True

            def requestInterruption(self) -> None:
                return

            def wait(self, _ms: int = 0) -> bool:
                return True

            def deleteLater(self) -> None:
                return

        order = SimpleNamespace(orderNumber="ORD-PENDING", api_account_id=1)

        with patch.object(orders_manager_window_module, "SyncWorker", _ManualWorker):
            widget._queue_profit_decoration([order])
            widget._queue_profit_decoration([order])

        self.assertEqual(len(workers), 1)
        self.assertIn("order:1:ORD-PENDING", widget._profit_pending_keys)

        workers[0].finished.emit()
        self.assertNotIn("order:1:ORD-PENDING", widget._profit_pending_keys)

    def test_returns_manager_window_refresh_exposes_known_return_statuses_from_constants(self) -> None:
        widget = ReturnsManagerWindow()
        self.addCleanup(widget.close)

        widget.list_widget.orders = [
            SimpleNamespace(claimItemStatus="WaitingInAction", status="WaitingInAction"),
        ]

        widget._refresh_order_status_filter()

        self.assertGreaterEqual(widget.order_status_filter.findData("all"), 0)
        for status_code in TRENDYOL_RETURN_STATUS_LIST:
            self.assertGreaterEqual(widget.order_status_filter.findData(status_code), 0)

    def test_refresh_order_status_filter_skips_runtime_scan_for_known_status_codes(self) -> None:
        widget = ReturnsManagerWindow()
        self.addCleanup(widget.close)

        with patch.object(orders_actions, "extract_order_statuses", side_effect=AssertionError("should not scan")):
            res = orders_actions.refresh_order_status_filter(
                widget.order_status_filter,
                widget.list_widget.orders,
                include_known_statuses=False,
                known_status_codes=TRENDYOL_RETURN_STATUS_LIST,
            )

        self.assertTrue(res.success, res.message)

    def test_refresh_order_status_filter_skips_runtime_scan_for_known_order_statuses(self) -> None:
        widget = OrdersManagerWindow()
        self.addCleanup(widget.close)

        with patch.object(orders_actions, "extract_order_statuses", side_effect=AssertionError("should not scan")):
            res = orders_actions.refresh_order_status_filter(
                widget.order_status_filter,
                widget.list_widget.orders,
                include_known_statuses=True,
            )

        self.assertTrue(res.success, res.message)

    def test_extract_order_statuses_uses_claim_item_status_when_other_status_fields_missing(self) -> None:
        rows = [
            SimpleNamespace(claimItemStatus="WaitingInAction", shipmentPackageStatus=None, status=None),
        ]

        statuses = orders_actions.extract_order_statuses(rows)

        self.assertIn(("Aksiyon Bekliyor", "WaitingInAction"), statuses)

    def test_order_profit_catalog_uses_pk_based_stock_item_costs(self) -> None:
        stock_row = SimpleNamespace(
            pk=3,
            id=None,
            sku="SKU-3",
            name="Dil Temizleyici",
            vat_rate=20.0,
            weight_kg=None,
            length_cm=None,
            width_cm=None,
            height_cm=None,
        )
        balance_row = {
            "item": stock_row,
            "avg_unit_cost": 67.68,
            "avg_cost_input_mode": "gross",
            "avg_cost_currency": "TRY",
        }

        with patch.object(
            orders_actions,
            "get_active_companies",
            return_value=SimpleNamespace(success=True, data={"records": []}),
        ), patch.object(
            orders_actions,
            "get_listings_from_db",
            return_value=SimpleNamespace(success=True, data={"items": []}),
        ), patch.object(
            orders_actions,
            "action_list_items",
            return_value=SimpleNamespace(success=True, data={"records": [stock_row]}),
        ), patch.object(
            orders_actions,
            "action_list_item_balances",
            return_value=SimpleNamespace(success=True, data={"records": [balance_row]}),
        ), patch.object(
            orders_actions,
            "load_finance_cost_items",
            return_value=SimpleNamespace(success=True, data={"records": []}),
        ), patch.object(
            orders_actions,
            "load_logistics_cargo_tariffs",
            return_value=SimpleNamespace(success=True, data={"records": []}),
        ):
            res = orders_actions.load_order_profit_catalog()

        self.assertTrue(res.success, res.message)
        catalog = res.data
        self.assertEqual(catalog["stock_item_label_map"][3], "SKU-3 - Dil Temizleyici")
        self.assertEqual(catalog["stock_cost_map"][3], 67.68)
        self.assertEqual(catalog["stock_cost_meta_map"][3]["input_mode"], "gross")
        self.assertEqual(catalog["stock_cost_meta_map"][3]["currency"], "TRY")

    def test_order_profit_lookup_does_not_copy_large_index_buckets(self) -> None:
        listing = {"title": "Indexed Listing"}

        class NoCopyBucket:
            def __init__(self) -> None:
                self.rows = {(1, "sku-1"): listing}

            def get(self, key, default=None):
                return self.rows.get(key, default)

            def __iter__(self):
                raise AssertionError("lookup bucket should not be copied")

        matched = orders_actions._match_listing_for_order_item(
            order_item={"productCode": "SKU-1"},
            api_account_id=1,
            lookup={
                "by_product_code": NoCopyBucket(),
                "by_barcode": {},
                "by_stock_code": {},
            },
        )

        self.assertIs(matched, listing)

    def test_orders_list_widget_normalize_epoch_dates_ignores_class_properties(self) -> None:
        widget = OrdersManagerWindow()
        self.addCleanup(widget.close)

        class DummyOrder:
            def __init__(self) -> None:
                self.orderDate = 1712332800000

            @property
            def expensiveDate(self):
                raise AssertionError("property should not be touched")

        row = DummyOrder()

        widget.list_widget._normalize_epoch_dates([row])

        self.assertIsInstance(row.orderDate, orders_manager_window_module.datetime)

    def test_order_profit_breakdown_window_is_top_level_resizable_window(self) -> None:
        window = orders_manager_window_module.OrderProfitBreakdownWindow()
        self.addCleanup(window.close)

        self.assertNotIsInstance(window, QDialog)
        self.assertTrue(bool(window.windowFlags() & Qt.WindowType.Window))
        self.assertTrue(bool(window.windowFlags() & Qt.WindowType.WindowMinMaxButtonsHint))
        self.assertGreaterEqual(window.minimumWidth(), 1120)
        self.assertGreaterEqual(window.minimumHeight(), 760)

    def test_estimate_order_profit_uses_order_level_cargo_once_and_line_commissions(self) -> None:
        listings = [
            {
                "api_account_id": 1,
                "barcode": "A-1",
                "stockCode": "sku-a",
                "title": "Urun A",
                "salePrice": None,
                "vatRate": 20,
                "stock_items": [{"stock_item_id": 1, "qty": 1}],
                "cost_items": [
                    {"cost_key": "komisyon", "source_type": "manual_value", "amount": 15.0},
                    {"cost_key": "kargo", "source_type": "builtin_resolver", "source_config": {"ruleKey": "cargo_amount_matcher"}},
                    {"cost_key": "platform-hizmet-bedeli", "source_type": "manual_value", "amount": 10.99},
                ],
            },
            {
                "api_account_id": 1,
                "barcode": "B-1",
                "stockCode": "sku-b",
                "title": "Urun B",
                "salePrice": 35.0,
                "vatRate": 20,
                "stock_items": [{"stock_item_id": 2, "qty": 1}],
                "cost_items": [
                    {"cost_key": "komisyon", "source_type": "manual_value", "amount": 12.0},
                    {"cost_key": "kargo", "source_type": "builtin_resolver", "source_config": {"ruleKey": "cargo_amount_matcher"}},
                    {"cost_key": "platform-hizmet-bedeli", "source_type": "manual_value", "amount": 10.99},
                ],
            },
        ]
        catalog = {
            "account_platform_map": {1: "TRENDYOL"},
            "listing_lookup": orders_actions._build_listing_lookup_indexes(listings),
            "stock_cost_map": {1: 25.0, 2: 11.0},
            "stock_vat_rate_map": {1: 20.0, 2: 20.0},
            "stock_cost_meta_map": {
                1: {"input_mode": "gross", "currency": "TRY"},
                2: {"input_mode": "gross", "currency": "TRY"},
            },
            "stock_dimension_map": {1: {"weight_kg": 1.0}, 2: {"weight_kg": 1.0}},
            "cost_items_cache": [
                {"costKey": "komisyon", "name": "Komisyon", "valueType": "percentage", "isVatIncluded": True, "vatRate": 20, "supportedPlatforms": ["TRENDYOL"]},
                {"costKey": "kargo", "name": "Kargo", "valueType": "numeric", "defaultSourceType": "builtin_resolver", "defaultSourceConfig": {"ruleKey": "cargo_amount_matcher"}, "isVatIncluded": True, "vatRate": 20, "supportedPlatforms": ["TRENDYOL"]},
                {"costKey": "platform-hizmet-bedeli", "name": "Platform Hizmet Bedeli", "valueType": "numeric", "isVatIncluded": False, "vatRate": 20, "supportedPlatforms": ["TRENDYOL"]},
            ],
            "cargo_tariffs_cache": [
                {
                    "tariffKey": "order-cargo",
                    "platformCode": "TRENDYOL",
                    "minDesi": 0,
                    "maxDesi": 20,
                    "minSalePrice": 300,
                    "maxSalePrice": 400,
                    "amount": 50.0,
                    "isVatIncluded": True,
                    "vatRate": 20,
                    "isActive": True,
                }
            ],
        }

        result = orders_actions.estimate_order_profit(
            order=SimpleNamespace(orderNumber="ORD-1", api_account_id=1),
            order_items=[
                {"barcode": "A-1", "name": "Urun A", "qty": 3, "unit_price": 83.83, "vatRate": 20},
                {"barcode": "B-1", "name": "Urun B", "qty": 3, "unit_price": 29.50, "vatRate": 20},
            ],
            catalog=catalog,
        )

        self.assertTrue(result["estimated_profit_ready"], result["estimated_profit_missing_reasons"])
        detail = result["estimated_profit_detail"]
        costs = detail["applied_costs"]
        self.assertEqual([row["key"] for row in costs].count("kargo"), 1)
        self.assertEqual([row["key"] for row in costs].count("platform-hizmet-bedeli"), 1)
        self.assertEqual([row["key"] for row in costs].count("komisyon"), 2)
        self.assertAlmostEqual(detail["summary"]["sale_price"], 339.99)
        self.assertAlmostEqual(detail["results"]["total_costs"], 219.5315)
        self.assertEqual(result["estimated_profit_missing_reasons"], [])

    def test_estimate_orders_profit_summary_returns_total_only_when_all_orders_are_complete(self) -> None:
        orders = [
            SimpleNamespace(orderNumber="ORD-SUMMARY-1", api_account_id=1, packageTotalPrice=100.0),
            SimpleNamespace(orderNumber="ORD-SUMMARY-2", api_account_id=1, packageTotalPrice=200.0),
        ]
        items_by_order = {
            (1, "ORD-SUMMARY-1"): [{"barcode": "BAR-1"}],
            (1, "ORD-SUMMARY-2"): [{"barcode": "BAR-2"}],
        }
        with patch.object(
            orders_actions,
            "load_order_profit_catalog",
            return_value=Result.ok("catalog", close_dialog=False, data={"catalog": True}),
        ), patch.object(
            orders_actions,
            "load_order_items_for_order_numbers",
            return_value=Result.ok(
                "items",
                close_dialog=False,
                data={"items_by_order": items_by_order},
            ),
        ), patch.object(
            orders_actions,
            "estimate_order_profit",
            side_effect=[
                {
                    "estimated_profit_ready": True,
                    "estimated_profit": 25.0,
                    "estimated_profit_missing_reasons": [],
                },
                {
                    "estimated_profit_ready": True,
                    "estimated_profit": 40.0,
                    "estimated_profit_missing_reasons": [],
                },
            ],
        ):
            result = orders_actions.estimate_orders_profit_summary(
                orders=orders,
                db_name="isolated.sqlite3",
            )

        self.assertTrue(result.success, result.message)
        data = result.data or {}
        self.assertTrue(data.get("estimated_profit_ready"))
        self.assertEqual(data.get("estimated_profit"), 65.0)
        self.assertEqual(data.get("revenue"), 300.0)
        self.assertEqual(data.get("complete_order_count"), 2)
        self.assertEqual(data.get("incomplete_order_count"), 0)

    def test_estimate_orders_profit_summary_withholds_total_when_any_order_is_incomplete(self) -> None:
        orders = [
            SimpleNamespace(orderNumber="ORD-SUMMARY-READY", api_account_id=1, packageTotalPrice=100.0),
            SimpleNamespace(orderNumber="ORD-SUMMARY-MISSING", api_account_id=1, packageTotalPrice=200.0),
        ]
        items_by_order = {
            (1, "ORD-SUMMARY-READY"): [{"barcode": "BAR-READY"}],
            (1, "ORD-SUMMARY-MISSING"): [{"barcode": "BAR-MISSING"}],
        }
        with patch.object(
            orders_actions,
            "load_order_profit_catalog",
            return_value=Result.ok("catalog", close_dialog=False, data={"catalog": True}),
        ), patch.object(
            orders_actions,
            "load_order_items_for_order_numbers",
            return_value=Result.ok(
                "items",
                close_dialog=False,
                data={"items_by_order": items_by_order},
            ),
        ), patch.object(
            orders_actions,
            "estimate_order_profit",
            side_effect=[
                {
                    "estimated_profit_ready": True,
                    "estimated_profit": 25.0,
                    "estimated_profit_missing_reasons": [],
                },
                {
                    "estimated_profit_ready": False,
                    "estimated_profit": 200.0,
                    "estimated_profit_missing_reasons": ["Stok maliyeti eksik."],
                },
            ],
        ):
            result = orders_actions.estimate_orders_profit_summary(
                orders=orders,
                db_name="isolated.sqlite3",
            )

        self.assertTrue(result.success, result.message)
        data = result.data or {}
        self.assertFalse(data.get("estimated_profit_ready"))
        self.assertIsNone(data.get("estimated_profit"))
        self.assertEqual(data.get("partial_estimated_profit"), 25.0)
        self.assertEqual(data.get("complete_order_count"), 1)
        self.assertEqual(data.get("incomplete_order_count"), 1)
        self.assertIn("ORD-SUMMARY-MISSING: Stok maliyeti eksik.", data.get("missing_reasons") or [])

    def test_order_profit_breakdown_window_renders_payload_summary_and_lines(self) -> None:
        window = orders_manager_window_module.OrderProfitBreakdownWindow()
        self.addCleanup(window.close)

        order = SimpleNamespace(orderNumber="ORD-42")
        payload = {
            "estimated_profit_ready": True,
            "estimated_profit": 84.5,
            "estimated_profit_text": "84.50 TL",
            "estimated_profit_missing_reasons": ["Stok karti maliyeti eksik."],
            "estimated_profit_detail": {
                "summary": {
                    "sale_price_text": "329.99 TL",
                    "line_count_text": "1",
                    "matched_line_count_text": "1",
                    "item_quantity_total_text": "2",
                },
                "results": {
                    "payout_total_text": "300.00 TL",
                    "marketplace_deductions_text": "29.99 TL",
                    "total_costs_text": "215.49 TL",
                    "net_vat_text": "-25.00 TL",
                    "sale_price": 329.99,
                    "payout_total": 300.0,
                    "marketplace_deductions": 29.99,
                    "total_costs": 215.49,
                    "net_vat": 25.0,
                },
                "lines": [
                    {
                        "title": "Deneme Urun",
                        "listing_title": "Deneme Ilan",
                        "unit_price_text": "164.99 TL",
                        "qty_text": "2",
                        "amount_text": "329.99 TL",
                        "amount": 329.99,
                        "estimated_profit_ready": True,
                        "estimated_profit": 84.5,
                        "estimated_profit_text": "84.50 TL",
                        "detail": {
                            "applied_costs": [
                                {"label": "Stok maliyeti", "gross": 115.49},
                                {"label": "Komisyon", "gross": 80.00},
                                {"label": "Kargo", "gross": 20.00},
                            ],
                            "results": {
                                "payout_total": 300.0,
                                "total_costs": 215.49,
                            }
                        },
                        "missing_reasons": [],
                    }
                ],
            },
        }

        window.set_order_payload(order=order, payload=payload)

        self.assertEqual(window.subtitle_label.text(), "Sipariş: ORD-42")
        self.assertEqual(window._summary_cards["sale"]["value"].text(), "329.99 TL")
        self.assertEqual(window._summary_cards["cost"]["value"].text(), "215.49 TL")
        self.assertEqual(window.profit_value_label.text(), "84.50 TL")
        self.assertEqual(window.formula_label.text(), "329.99 TL - 215.49 TL = 84.50 TL")
        self.assertFalse(hasattr(window, "badge_row"))
        self.assertTrue(window.reveal_panel.isHidden())
        window._set_active_detail_tab("cost")
        self.assertFalse(window.reveal_panel.isHidden())
        self.assertFalse(window._summary_cards["cost"]["drawer"].isHidden())
        self.assertGreaterEqual(window._summary_cards["cost"]["drawer_layout"].count(), 4)
        window._set_active_detail_tab("sale")
        self.assertFalse(window._summary_cards["sale"]["drawer"].isHidden())
        self.assertFalse(window._summary_cards["cost"]["drawer"].isHidden())
        self.assertFalse(window.missing_panel.isHidden())

    def test_order_profit_detail_drawers_expand_without_instant_visibility_jump(self) -> None:
        window = orders_manager_window_module.OrderProfitBreakdownWindow()
        self.addCleanup(window.close)

        window.set_order_payload(
            order=SimpleNamespace(orderNumber="ORD-SMOOTH"),
            payload={
                "estimated_profit_ready": True,
                "estimated_profit": 25.0,
                "estimated_profit_text": "25.00 TL",
                "estimated_profit_missing_reasons": ["Stok eşleşmesi bekleniyor"],
                "estimated_profit_detail": {
                    "summary": {"sale_price_text": "100.00 TL"},
                    "results": {"total_costs": 75.0, "total_costs_text": "75.00 TL"},
                    "lines": [{"title": "Urun", "amount": 100.0, "amount_text": "100.00 TL"}],
                    "applied_costs": [{"label": "Maliyet", "gross": 75.0}],
                },
            },
        )

        window.resize(1360, 860)
        window.show()
        self._app.processEvents()
        window._toggle_summary_expanded()
        for _ in range(3):
            self._app.processEvents()
            QTest.qWait(15)
        QTest.qWait(1500)
        self._app.processEvents()

        drawer = window._summary_cards["cost"]["drawer"]
        sale_card = window._summary_cards["sale"]["button"]
        cost_card = window._summary_cards["cost"]["button"]
        content_layout = window._content_widget.layout()
        before_count = content_layout.count()
        sale_geometry = sale_card.geometry()
        cost_geometry = cost_card.geometry()
        self.assertIs(window.detail_drawer_spacer.parent(), window._content_widget)
        self.assertTrue(drawer.isHidden())

        window._toggle_detail_tab("cost")
        self._app.processEvents()

        self.assertEqual(content_layout.count(), before_count)
        self.assertFalse(drawer.isHidden())
        self.assertTrue(drawer.isAnimating())
        self.assertGreater(drawer.expandedHeight(), 120)
        self.assertEqual(drawer.targetHeight(), drawer.expandedHeight())
        self.assertEqual(window.detail_drawer_spacer.maximumHeight(), drawer.expandedHeight() + 24)
        self.assertEqual(sale_card.geometry(), sale_geometry)
        self.assertEqual(cost_card.geometry(), cost_geometry)
        QTest.qWait(80)
        self._app.processEvents()
        drawer_y = drawer.y()
        self.assertGreater(drawer.maximumHeight(), 0)
        QTest.qWait(100)
        self._app.processEvents()
        self.assertEqual(drawer.y(), drawer_y)
        self.assertEqual(content_layout.count(), before_count)
        self.assertEqual(sale_card.geometry(), sale_geometry)
        self.assertEqual(cost_card.geometry(), cost_geometry)
        self.assertEqual(window.detail_drawer_spacer.maximumHeight(), drawer.expandedHeight() + 24)
        self.assertGreater(drawer.maximumHeight(), 0)
        self.assertLess(drawer.maximumHeight(), drawer.expandedHeight())
        QTest.qWait(1500)
        self._app.processEvents()
        viewport = window.content_scroll.viewport()
        missing_top = window.missing_panel.mapTo(viewport, QPoint(0, 0)).y()
        drawer_bottom = drawer.y() + drawer.maximumHeight()
        self.assertGreaterEqual(missing_top - drawer_bottom, 8)

        window._toggle_detail_tab("cost")

        self.assertFalse(drawer.isHidden())
        self.assertTrue(drawer.isAnimating())
        self.assertGreaterEqual(window._summary_cards["cost"]["drawer_layout"].count(), 2)
        QTest.qWait(1500)
        self._app.processEvents()
        self.assertTrue(drawer.isHidden())
        self.assertEqual(window.detail_drawer_spacer.maximumHeight(), 0)

    def test_order_profit_summary_reveal_toggles_instantly_without_close_jump(self) -> None:
        window = orders_manager_window_module.OrderProfitBreakdownWindow()
        self.addCleanup(window.close)

        window.set_order_payload(
            order=SimpleNamespace(orderNumber="ORD-REVEAL"),
            payload={
                "estimated_profit_ready": True,
                "estimated_profit": 25.0,
                "estimated_profit_text": "25.00 TL",
                "estimated_profit_missing_reasons": [],
                "estimated_profit_detail": {
                    "summary": {"sale_price_text": "100.00 TL"},
                    "results": {"total_costs": 75.0, "total_costs_text": "75.00 TL"},
                    "lines": [{"title": "Urun", "amount": 100.0, "amount_text": "100.00 TL"}],
                    "applied_costs": [{"label": "Maliyet", "gross": 75.0}],
                },
            },
        )
        window.resize(1360, 860)
        window.show()
        self._app.processEvents()

        reveal = window.reveal_panel
        self.assertTrue(reveal.isHidden())

        window._toggle_summary_expanded()
        self._app.processEvents()

        self.assertFalse(reveal.isHidden())
        self.assertFalse(reveal.isAnimating())
        self.assertGreaterEqual(reveal.maximumHeight(), reveal.expandedHeight())
        self.assertEqual(window.detail_drawer_spacer.maximumHeight(), 0)

        window._toggle_detail_tab("cost")
        QTest.qWait(1500)
        self._app.processEvents()

        drawer = window._summary_cards["cost"]["drawer"]
        self.assertFalse(drawer.isHidden())
        self.assertFalse(drawer.isAnimating())
        self.assertGreater(window.detail_drawer_spacer.maximumHeight(), 0)

        window._toggle_summary_expanded()
        self._app.processEvents()

        self.assertTrue(reveal.isHidden())
        self.assertFalse(reveal.isAnimating())
        self.assertTrue(drawer.isHidden())
        self.assertFalse(drawer.isAnimating())
        self.assertEqual(window.detail_drawer_spacer.maximumHeight(), 0)

    def test_order_profit_detail_animation_keeps_scroll_position_locked(self) -> None:
        window = orders_manager_window_module.OrderProfitBreakdownWindow()
        self.addCleanup(window.close)

        lines = [
            {
                "title": f"Urun {idx}",
                "listing_title": f"Ilan {idx}",
                "qty_text": "1",
                "unit_price_text": "35.00 TL",
                "amount": 35.0,
                "amount_text": "35.00 TL",
            }
            for idx in range(10)
        ]
        costs = [
            {"label": f"Maliyet {idx}", "gross": 25.0 + idx, "note": f"Satir {idx}"}
            for idx in range(9)
        ]
        window.set_order_payload(
            order=SimpleNamespace(orderNumber="ORD-SCROLL"),
            payload={
                "estimated_profit_ready": True,
                "estimated_profit": 27.72,
                "estimated_profit_text": "27.72 TL",
                "estimated_profit_missing_reasons": [],
                "estimated_profit_detail": {
                    "summary": {"sale_price_text": "350.00 TL"},
                    "results": {"total_costs": 316.74, "total_costs_text": "316.74 TL"},
                    "lines": lines,
                    "applied_costs": costs,
                },
            },
        )

        window.resize(1360, 420)
        window.show()
        self._app.processEvents()
        window._toggle_summary_expanded()
        QTest.qWait(1500)
        self._app.processEvents()
        window._toggle_detail_tab("sale")
        QTest.qWait(1500)
        self._app.processEvents()

        bar = window.content_scroll.verticalScrollBar()
        bar.setValue(min(80, bar.maximum()))
        frozen_value = bar.value()
        frozen_width = window._content_widget.width()

        window._toggle_detail_tab("cost")
        drawer = window._summary_cards["cost"]["drawer"]
        sale_drawer = window._summary_cards["sale"]["drawer"]
        expected_spacer_height = max(drawer.expandedHeight(), sale_drawer.expandedHeight()) + 24
        observed_values = []
        observed_widths = []
        observed_heights = []
        observed_drawer_y = []
        observed_spacer_heights = []
        for _ in range(10):
            QTest.qWait(20)
            self._app.processEvents()
            observed_values.append(bar.value())
            observed_widths.append(window._content_widget.width())
            observed_heights.append(drawer.maximumHeight())
            observed_drawer_y.append(drawer.y())
            observed_spacer_heights.append(window.detail_drawer_spacer.maximumHeight())

        self.assertEqual(observed_values, [frozen_value] * len(observed_values))
        self.assertEqual(observed_widths, [frozen_width] * len(observed_widths))
        self.assertLessEqual(max(observed_drawer_y) - min(observed_drawer_y), 0)
        self.assertEqual(
            observed_spacer_heights,
            [expected_spacer_height] * len(observed_spacer_heights),
        )
        height_steps = [
            next_height - current_height
            for current_height, next_height in zip(observed_heights, observed_heights[1:])
        ]
        self.assertTrue(height_steps)
        self.assertLessEqual(max(height_steps), 32)
        QTest.qWait(1500)
        self._app.processEvents()
        self.assertEqual(bar.value(), frozen_value)

    def test_order_profit_breakdown_window_lazy_renders_large_payload(self) -> None:
        window = orders_manager_window_module.OrderProfitBreakdownWindow()
        self.addCleanup(window.close)

        order = SimpleNamespace(orderNumber="ORD-LARGE")
        lines = [
            {
                "title": f"Urun {idx}",
                "listing_title": f"Ilan {idx}",
                "qty_text": "1",
                "unit_price_text": "10.00 TL",
                "amount_text": "10.00 TL",
                "amount": 10.0,
                "estimated_profit_ready": False,
                "estimated_profit_text": "-",
                "detail": {"results": {"payout_total": 9.0, "total_costs": 2.0}},
            }
            for idx in range(500)
        ]
        payload = {
            "estimated_profit_ready": False,
            "estimated_profit": None,
            "estimated_profit_text": "-",
            "estimated_profit_missing_reasons": [f"Eksik {idx}" for idx in range(708)],
            "estimated_profit_detail": {
                "summary": {
                    "sale_price_text": "5000.00 TL",
                    "line_count_text": "500",
                    "matched_line_count_text": "500",
                    "item_quantity_total_text": "500",
                },
                "results": {
                    "total_costs_text": "1000.00 TL",
                    "total_costs": 1000.0,
                },
                "applied_costs": [{"label": "Maliyet", "gross": 2.0, "note": f"Satir {idx}"} for idx in range(500)],
                "lines": lines,
            },
        }

        window.set_order_payload(order=order, payload=payload)

        self.assertEqual(window.missing_value_label.text(), "708")
        self.assertEqual(window.missing_body_layout.count(), 0)
        self.assertFalse(window._missing_expanded)
        self.assertEqual(window.lines_layout.count(), 0)

        window._toggle_missing_expanded()
        self.assertTrue(window._missing_expanded)
        self.assertEqual(window.missing_body_layout.count(), window._MISSING_ROWS_PER_PAGE + 2)
        missing_labels = [label.text() for label in window.missing_panel.findChildren(QLabel)]
        self.assertIn("Sayfa 1 / 177", missing_labels)
        window._change_missing_page(1)
        self.assertEqual(window._missing_page_index, 1)
        missing_labels = [label.text() for label in window.missing_panel.findChildren(QLabel)]
        self.assertIn("Sayfa 2 / 177", missing_labels)

        window._set_active_detail_tab("sale")
        sale_layout = window._summary_cards["sale"]["drawer_layout"]
        self.assertEqual(sale_layout.count(), window._DETAIL_ROWS_PER_PAGE + 2)
        self.assertEqual(window._detail_page_indexes["sale"], 0)
        window._change_detail_page("sale", 1)
        self.assertEqual(window._detail_page_indexes["sale"], 1)

        window._set_active_detail_tab("cost")
        cost_layout = window._summary_cards["cost"]["drawer_layout"]
        self.assertEqual(cost_layout.count(), window._DETAIL_ROWS_PER_PAGE + 2)
        self.assertFalse(window._summary_cards["sale"]["drawer"].isHidden())
        self.assertFalse(window._summary_cards["cost"]["drawer"].isHidden())


if __name__ == "__main__":
    unittest.main()
