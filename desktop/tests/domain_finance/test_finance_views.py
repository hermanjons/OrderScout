from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QApplication, QWidget

import Core.views as core_views
import Finance.views.finance_cost_items_window as cost_window
import Finance.views.finance_manager_window as manager_window
import Finance.views.finance_transactions_window as transactions_window
import Finance.views.views as finance_views
import Logistics.views.cargo_tariffs_window as logistics_cargo_window


class _FakeHookIndex:
    def __init__(self, payload: dict | None = None) -> None:
        self._record = SimpleNamespace(payload=dict(payload or {}))

    def data(self, role):
        if role == core_views.RecordWorkspaceListModel.RecordRole:
            return self._record
        return None


class _ImmediateSignal:
    def __init__(self) -> None:
        self._callbacks = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)

    def emit(self, *args, **kwargs) -> None:
        for callback in list(self._callbacks):
            callback(*args, **kwargs)


class _ImmediateSyncWorker:
    def __init__(self, func, *args, parent=None, **kwargs) -> None:
        _ = parent
        self._func = func
        self._args = args
        self._kwargs = kwargs
        self.result_ready = _ImmediateSignal()
        self.finished = _ImmediateSignal()

    def isRunning(self) -> bool:
        return False

    def start(self) -> None:
        result = self._func(*self._args, **self._kwargs)
        self.result_ready.emit(result)
        self.finished.emit()

    def deleteLater(self) -> None:
        return None


class _FakeTopLevelWindow(QWidget):
    itemsChanged = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.reload_count = 0

    def open_full(self):
        self.show()
        return self

    def reload_items(self) -> None:
        self.reload_count += 1

    def reload_from_db(self) -> None:
        self.reload_count += 1


class TestFinanceViews(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    @classmethod
    def _source(cls, module) -> str:
        return Path(module.__file__).resolve().read_text(encoding="utf-8")

    def test_finance_windows_use_scaffold_without_legacy_shell(self) -> None:
        for module in (manager_window, cost_window, transactions_window):
            source = self._source(module)
            self.assertIn("RecordWorkspaceScaffold(", source)
            self.assertNotIn("RecordWorkspaceSplitShell(", source)
            self.assertNotIn("RecordWorkspaceBehaviorController(", source)

        finance_views_source = self._source(finance_views)
        self.assertIn('("Logistics.views.cargo_tariffs_window", "FinanceCargoTariffCard")', finance_views_source)
        self.assertIn('("Logistics.views.cargo_tariffs_window", "FinanceCargoTariffsWindow")', finance_views_source)

    def test_finance_manager_window_uses_scaffold_slots(self) -> None:
        window = manager_window.FinanceManagerWindow()
        self.assertIsInstance(window._workspace, core_views.RecordWorkspaceScaffold)
        self.assertTrue(window._workspace.footer_bar.select_toggle.isHidden())
        self.assertIs(window.left_panel_title, window._workspace.left_card.title_label)
        self.assertIs(window.left_panel_hint, window._workspace.left_card.subtitle_label)
        window.close()
        window.deleteLater()
        self._app.processEvents()

    def test_finance_cost_items_window_uses_scaffold_slots(self) -> None:
        window = cost_window.FinanceCostItemsWindow()
        self.assertIsInstance(window._workspace, core_views.RecordWorkspaceScaffold)
        self.assertFalse(window._workspace.footer_bar.isHidden())
        self.assertIs(window.left_panel_title, window._workspace.left_card.title_label)
        self.assertIs(window.left_panel_hint, window._workspace.left_card.subtitle_label)
        self.assertIs(window.bulk_panel, window._workspace.bulk_panel)
        self.assertFalse(window._workspace_shell.is_left_panel_open())
        self.assertIsInstance(window._workspace.editor_action_bar, core_views.RecordWorkspaceEditorActionBar)
        self.assertIs(window.btn_save_cost.parentWidget(), window._workspace.editor_action_bar)
        self.assertEqual(window.btn_new_cost.minimumWidth(), 0)
        self.assertEqual(window.btn_save_cost.minimumWidth(), 0)
        self.assertEqual(window.btn_delete_cost.minimumWidth(), 0)
        window._set_left_mode("new")
        self.assertEqual(window.btn_save_cost.text(), "Maliyet Kartını Kaydet")
        self.assertTrue(window.btn_delete_cost.isHidden())
        window._active_pk = 11
        window._set_left_mode("edit")
        self.assertEqual(window.btn_save_cost.text(), "Güncelle")
        self.assertFalse(window.btn_delete_cost.isHidden())
        window._load_editor_payload({"pk": 11, "name": "Kargo", "isBuiltin": True})
        self.assertTrue(window.btn_delete_cost.isHidden())
        window.close()
        window.deleteLater()
        self._app.processEvents()

    def test_finance_cost_items_pending_builtin_uses_accept_hook_text(self) -> None:
        window = cost_window.FinanceCostItemsWindow()
        record = {
            "pk": 1002,
            "name": "Komisyon",
            "description": "Önerilen kart",
            "valueType": "percentage",
            "valueTypeLabel": "Yüzdesel",
            "defaultSourceTypeLabel": "Manual",
            "defaultAmountLabel": "Varsayılan Oran",
            "defaultAmountText": "%12",
            "amountModeText": "KDV dahil",
            "currency": "TRY",
            "isActive": True,
            "isBuiltin": True,
            "isBuiltinAccepted": False,
        }
        card = window._build_card_record(record)
        window.list_widget.set_records([card])
        index = window.list_widget.model().index(0, 0)
        self.assertEqual(window.list_widget.itemDelegate()._hook_text(index), "KABUL ET")
        rect = window.list_widget.visualRect(index)
        pending_hook_rect = window.list_widget.itemDelegate()._hook_rect_for_index(rect, index, window.list_widget)
        default_hook_rect = cost_window.OrdersStyleListDelegate()._build_hook_rect(rect, view=window.list_widget)
        self.assertGreater(int(pending_hook_rect.width()), int(default_hook_rect.width()))
        window.close()
        window.deleteLater()
        self._app.processEvents()

    def test_finance_cost_items_regular_select_hook_keeps_default_width(self) -> None:
        window = cost_window.FinanceCostItemsWindow()
        record = {
            "pk": 7,
            "name": "Paketleme",
            "description": "Normal kart",
            "valueType": "numeric",
            "valueTypeLabel": "Sayısal",
            "defaultSourceTypeLabel": "Manual",
            "defaultAmountLabel": "Varsayılan Fiyat",
            "defaultAmountText": "3 TRY",
            "amountModeText": "KDV dahil",
            "currency": "TRY",
            "isActive": True,
            "isBuiltin": False,
            "isBuiltinAccepted": True,
        }
        card = window._build_card_record(record)
        window.list_widget.set_records([card])
        index = window.list_widget.model().index(0, 0)
        rect = window.list_widget.visualRect(index)
        regular_hook_rect = window.list_widget.itemDelegate()._hook_rect_for_index(rect, index, window.list_widget)
        self.assertEqual(int(regular_hook_rect.width()), 44)
        window.close()
        window.deleteLater()
        self._app.processEvents()

    def test_finance_transactions_window_uses_scaffold_slots(self) -> None:
        window = transactions_window.FinanceTransactionsWindow()
        self.assertIsInstance(window._workspace, core_views.RecordWorkspaceScaffold)
        self.assertTrue(window._workspace.footer_bar.select_toggle.isHidden())
        self.assertIs(window.left_panel_title, window._workspace.left_card.title_label)
        self.assertIs(window.left_panel_hint, window._workspace.left_card.subtitle_label)
        self.assertFalse(window._workspace_shell.is_left_panel_open())
        window.close()
        window.deleteLater()
        self._app.processEvents()

    def test_finance_cost_items_delegate_uses_scaffold_default_select_text_after_acceptance(self) -> None:
        delegate = cost_window.FinanceCostItemsListDelegate()
        base_delegate = cost_window.OrdersStyleListDelegate()

        pending_index = _FakeHookIndex({"isBuiltin": True, "isBuiltinAccepted": False})
        accepted_index = _FakeHookIndex({"isBuiltin": True, "isBuiltinAccepted": True})

        self.assertEqual(
            delegate._hook_text(pending_index),
            cost_window.FINANCE_COST_ITEM_ACCEPT_BUTTON_TEXT,
        )
        self.assertEqual(
            delegate._hook_text(accepted_index),
            base_delegate._hook_text(accepted_index),
        )

    def test_finance_cost_items_accept_builtin_flow_uses_domain_handler(self) -> None:
        window = cost_window.FinanceCostItemsWindow()
        record = {
            "pk": 1002,
            "name": "Komisyon",
            "description": "Önerilen kart",
            "valueType": "percentage",
            "valueTypeLabel": "Yüzdesel",
            "defaultSourceTypeLabel": "Manual",
            "defaultAmountLabel": "Varsayılan Oran",
            "defaultAmountText": "%12",
            "amountModeText": "KDV dahil",
            "currency": "TRY",
            "isActive": True,
            "isBuiltin": True,
            "isBuiltinAccepted": False,
        }
        window._record_map = {1002: record}
        card = window._build_card_record(record)
        with patch.object(cost_window.AppMessageCenter, "confirm", return_value=True), patch.object(
            cost_window, "accept_finance_cost_item", return_value=cost_window.Result.ok("ok", close_dialog=False)
        ) as accept_mock, patch.object(window, "reload_items") as reload_mock, patch.object(
            cost_window.MessageHandler, "show"
        ):
            window._workspace_apply_selection(card, True)

        accept_mock.assert_called_once_with(1002)
        reload_mock.assert_called_once()
        self.assertFalse(window._selected_pks)
        window.close()
        window.deleteLater()
        self._app.processEvents()

    def test_finance_cargo_tariffs_window_uses_scaffold_slots(self) -> None:
        window = finance_views.FinanceCargoTariffsWindow()
        self.assertIsInstance(window._workspace, core_views.RecordWorkspaceScaffold)
        self.assertFalse(window._workspace.footer_bar.isHidden())
        self.assertIs(window.left_panel_title, window._workspace.left_card.title_label)
        self.assertIs(window.left_panel_hint, window._workspace.left_card.subtitle_label)
        self.assertIs(window.bulk_panel, window._workspace.bulk_panel)
        self.assertFalse(window._workspace_shell.is_left_panel_open())
        self.assertIsInstance(window._workspace.editor_action_bar, core_views.RecordWorkspaceEditorActionBar)
        self.assertIs(window.btn_save_tariff.parentWidget(), window._workspace.editor_action_bar)
        self.assertEqual(window.btn_new_tariff.minimumWidth(), 0)
        self.assertEqual(window.btn_save_tariff.minimumWidth(), 0)
        self.assertEqual(window.btn_delete_tariff.minimumWidth(), 0)
        window._set_left_mode("new")
        self.assertEqual(window.btn_save_tariff.text(), "Kargo Tarifesini Kaydet")
        self.assertTrue(window.btn_delete_tariff.isHidden())
        window._active_pk = 12
        window._set_left_mode("edit")
        self.assertEqual(window.btn_save_tariff.text(), "Güncelle")
        self.assertFalse(window.btn_delete_tariff.isHidden())
        window._active_pk = 0
        window._load_editor_payload(None)
        self.assertTrue(window.btn_delete_tariff.isHidden())
        window.close()
        window.deleteLater()
        self._app.processEvents()

    def test_finance_cargo_tariffs_window_populates_filter_provider_options_on_init(self) -> None:
        def _platform_options(*, include_all=True, db_name=None):
            _ = db_name
            return [("Tümü", ""), ("Trendyol", "TRENDYOL")] if include_all else [("Trendyol", "TRENDYOL")]

        def _provider_options(platform_code=None, *, include_all=True, db_name=None):
            _ = (platform_code, db_name)
            return [("Tümü", ""), ("Aras Kargo Marketplace", "ARASMP")] if include_all else [("Aras Kargo Marketplace", "ARASMP")]

        with patch.object(logistics_cargo_window, "logistics_cargo_tariff_platform_options", side_effect=_platform_options), patch.object(
            logistics_cargo_window, "logistics_cargo_provider_options", side_effect=_provider_options
        ):
            window = finance_views.FinanceCargoTariffsWindow()

        self.assertGreaterEqual(window.filter_provider_combo.findData("ARASMP"), 0)
        window.close()
        window.deleteLater()
        self._app.processEvents()

    def test_finance_cargo_tariffs_window_preserves_user_resized_left_panel_width(self) -> None:
        window = finance_views.FinanceCargoTariffsWindow()
        window.resize(1600, 900)
        window.show()
        self._app.processEvents()

        window._open_left_panel()
        self._app.processEvents()
        with patch.object(window._splitter, "sizes", return_value=[860, 600]):
            window._sync_sidebar_state_from_splitter()
        self.assertGreaterEqual(window._preferred_left_panel_width, 860)

        with patch.object(window._workspace_shell, "open_left_panel") as open_mock:
            window._open_left_panel()
        open_mock.assert_called_once_with(left_width=860, min_left=420, min_right=300)
        window.close()
        window.deleteLater()
        self._app.processEvents()

    def test_finance_cargo_tariffs_window_uses_half_width_default_left_panel(self) -> None:
        window = finance_views.FinanceCargoTariffsWindow()
        self.assertIsNone(window._preferred_left_panel_width)
        with patch.object(window, "_splitter_total_size", return_value=1600), patch.object(
            window._workspace_shell, "open_left_panel"
        ) as open_mock:
            window._open_left_panel()
        open_mock.assert_called_once_with(left_width=800, min_left=420, min_right=300)
        window.close()
        window.deleteLater()
        self._app.processEvents()

    def test_finance_cargo_tariffs_window_allows_right_filters_to_shrink(self) -> None:
        window = finance_views.FinanceCargoTariffsWindow()
        self.assertEqual(window._workspace.right_card.minimumWidth(), 0)
        self.assertEqual(window._workspace.filters_card.minimumWidth(), 0)
        self.assertEqual(window._workspace.records_card.minimumWidth(), 0)
        self.assertEqual(window.filter_platform_combo.minimumWidth(), 0)
        self.assertEqual(window.filter_provider_combo.minimumWidth(), 0)
        self.assertEqual(window.filter_active_combo.minimumWidth(), 0)
        self.assertEqual(window.filter_source_combo.minimumWidth(), 0)
        window.close()
        window.deleteLater()
        self._app.processEvents()

    def test_finance_cargo_tariffs_delegate_uses_scaffold_default_select_text_after_acceptance(self) -> None:
        delegate = finance_views.FinanceCargoTariffsWindow().list_widget.itemDelegate()
        base_delegate = logistics_cargo_window.OrdersStyleListDelegate()

        pending_index = _FakeHookIndex({"isBuiltin": True, "isBuiltinAccepted": False})
        accepted_index = _FakeHookIndex({"isBuiltin": True, "isBuiltinAccepted": True})

        self.assertEqual(
            delegate._hook_text(pending_index),
            logistics_cargo_window.FINANCE_CARGO_TARIFF_ACCEPT_BUTTON_TEXT,
        )
        self.assertEqual(
            delegate._hook_text(accepted_index),
            base_delegate._hook_text(accepted_index),
        )

    def test_finance_cargo_tariffs_accept_builtin_flow_uses_domain_handler(self) -> None:
        window = finance_views.FinanceCargoTariffsWindow()
        record = {
            "pk": 9101,
            "tariffKey": "trendyol-express-0-5-desi",
            "name": "Trendyol Express 0-5 Desi",
            "description": "Önerilen tarife",
            "platformCode": "TRENDYOL",
            "platform": "Trendyol",
            "cargoProviderCode": "TEXMP",
            "cargoProviderName": "Trendyol Express Marketplace",
            "providerText": "Trendyol Express Marketplace",
            "desiRangeText": "0 - 5 desi",
            "salePriceRangeText": "0 - 300 TL",
            "amount": 54.9,
            "amountText": "54,90 TL",
            "currency": "TRY",
            "isVatIncluded": False,
            "vatRate": 20,
            "amountModeText": "KDV hariç (%20)",
            "isActive": True,
            "isBuiltin": True,
            "isBuiltinAccepted": False,
        }
        window._record_map = {9101: record}
        card = window._build_card_record(record)
        with patch.object(logistics_cargo_window.AppMessageCenter, "confirm", return_value=True), patch.object(
            logistics_cargo_window, "accept_logistics_cargo_tariff", return_value=logistics_cargo_window.Result.ok("ok", close_dialog=False)
        ) as accept_mock, patch.object(window, "reload_items") as reload_mock, patch.object(
            logistics_cargo_window.MessageHandler, "show"
        ):
            window._workspace_apply_selection(card, True)

        accept_mock.assert_called_once_with(9101)
        reload_mock.assert_called_once()
        self.assertFalse(window._selected_pks)
        window.close()
        window.deleteLater()
        self._app.processEvents()

    def test_finance_cargo_tariffs_bulk_accept_uses_batch_handler(self) -> None:
        window = finance_views.FinanceCargoTariffsWindow()
        window._records = [
            {"pk": 9101, "isBuiltin": True, "isBuiltinAccepted": False},
            {"pk": 9102, "isBuiltin": True, "isBuiltinAccepted": False},
        ]
        window._record_map = {int(row["pk"]): dict(row) for row in window._records}
        window._selected_pks = {9101, 9102}
        with patch.object(logistics_cargo_window.AppMessageCenter, "confirm", return_value=True), patch.object(
            logistics_cargo_window,
            "accept_logistics_cargo_tariffs",
            return_value=logistics_cargo_window.Result.ok("ok", close_dialog=False),
        ) as accept_mock, patch.object(logistics_cargo_window, "SyncWorker", _ImmediateSyncWorker), patch.object(window, "reload_items") as reload_mock, patch.object(
            logistics_cargo_window.MessageHandler,
            "show",
        ):
            window._accept_pending_tariffs_bulk()

        accept_mock.assert_called_once_with([9101, 9102])
        reload_mock.assert_called_once()
        window.close()
        window.deleteLater()
        self._app.processEvents()

    def test_finance_cost_bulk_guidance_uses_scaffold_bulk_surface(self) -> None:
        window = cost_window.FinanceCostItemsWindow()
        window.resize(1600, 900)
        window.show()
        self._app.processEvents()

        window._set_left_mode("bulk")
        window._open_left_panel()
        window._workspace_controller.sync_state()
        self._app.processEvents()

        overlay = window._workspace_shell._left_highlight_overlay
        self.assertIsNotNone(overlay)
        self.assertTrue(overlay.isVisible())

        host = window._workspace.left_card
        expected = window._workspace_shell._mapped_rect(window.bulk_panel, host)
        actual = overlay.geometry()
        self.assertGreater(actual.width(), host.width() // 2)
        self.assertGreater(actual.height(), host.height() // 2)
        self.assertLessEqual(abs(actual.width() - expected.width()), 8)
        self.assertLessEqual(abs(actual.height() - expected.height()), 8)

        window.close()
        window.deleteLater()
        self._app.processEvents()

    def test_finance_cost_active_spin_turns_off_in_bulk_mode(self) -> None:
        window = cost_window.FinanceCostItemsWindow()
        window.show()
        self._app.processEvents()

        record = {
            "pk": 10,
            "name": "Kargo",
            "description": "Test",
            "valueTypeLabel": "Sayısal",
            "defaultSourceTypeLabel": "Manual",
            "amountModeText": "KDV dahil",
            "isActive": True,
        }
        window._records = [record]
        window._record_map = {10: record}
        card = window._build_card_record(record)
        window.list_widget.set_records([card])
        window._active_pk = 10
        window._set_left_mode("edit")
        window._open_left_panel()
        window._sync_card_states()
        self.assertTrue(window.list_widget._active_spin_allowed)

        window._workspace_apply_selection(card, True)
        window._set_left_mode("bulk")
        window._sync_card_states()
        self.assertFalse(window.list_widget._active_spin_allowed)

        window.close()
        window.deleteLater()
        self._app.processEvents()

    def test_finance_cost_clicking_second_card_keeps_panel_open_and_switches_active(self) -> None:
        with patch.object(cost_window.FinanceCostItemsWindow, "request_reload_items"):
            window = cost_window.FinanceCostItemsWindow()
            window.resize(1600, 900)
            window.show()
            self._app.processEvents()

        first = {
            "pk": 10,
            "name": "Kargo",
            "description": "Test",
            "valueType": "numeric",
            "valueTypeLabel": "Sayısal",
            "defaultSourceTypeLabel": "Kural",
            "defaultAmountLabel": "Varsayılan",
            "defaultAmountText": "10.00",
            "amountModeText": "KDV dahil",
            "currency": "TRY",
            "isActive": True,
        }
        second = {
            "pk": 11,
            "name": "Komisyon",
            "description": "Test 2",
            "valueType": "numeric",
            "valueTypeLabel": "Sayısal",
            "defaultSourceTypeLabel": "Manual",
            "defaultAmountLabel": "Varsayılan",
            "defaultAmountText": "12.50",
            "amountModeText": "KDV dahil",
            "currency": "TRY",
            "isActive": True,
        }
        window._records = [first, second]
        window._record_map = {10: first, 11: second}
        cards = [window._build_card_record(first), window._build_card_record(second)]
        window.list_widget.set_records(cards)
        window._workspace_activate_record(cards[0])
        window._open_left_panel()
        window._workspace_controller.sync_state()
        self._app.processEvents()

        second_index = window.list_widget.model().index(1, 0)
        window.list_widget._on_row_clicked(second_index)
        self._app.processEvents()

        self.assertTrue(window._is_left_panel_open())
        self.assertEqual(window._active_pk, 11)
        self.assertTrue(window.list_widget.is_active_record(cards[1]))
        self.assertFalse(window.list_widget.is_active_record(cards[0]))

        window.close()
        window.deleteLater()
        self._app.processEvents()

    def test_finance_tab_wraps_quick_access_buttons(self) -> None:
        tab = finance_views.FinanceTab()
        self.assertIsInstance(tab.cost_items_btn.parentWidget().layout(), core_views.FlowLayout)
        self.assertIs(tab.invoices_btn.parentWidget(), tab.cost_items_btn.parentWidget())
        self.assertIs(tab.transactions_btn.parentWidget(), tab.cost_items_btn.parentWidget())
        self.assertTrue(tab.invoices_btn.isHidden())
        self.assertTrue(tab.transactions_btn.isHidden())
        self.assertFalse(tab.cost_items_btn.isHidden())
        self.assertFalse(tab.brands_btn.isHidden())
        self.assertFalse(tab.companies_btn.isHidden())
        source = self._source(finance_views)
        self.assertIn("finance-cost-items-icon.png", source)
        self.assertIn("finance-invoices-icon.png", source)
        self.assertIn("finance-transactions-icon.png", source)
        tab.close()
        tab.deleteLater()
        self._app.processEvents()

    def test_finance_tab_fetch_panel_has_auto_fetch_controls(self) -> None:
        tab = finance_views.FinanceTab()
        self.addCleanup(tab.close)
        self.addCleanup(tab.deleteLater)

        self.assertFalse(tab.auto_fetch_minutes.isEnabled())

        tab.auto_fetch_minutes.setValue(5)
        tab.auto_fetch_toggle.setChecked(True)
        tab._toggle_auto_fetch()

        self.assertTrue(tab.auto_fetch_minutes.isEnabled())
        self.assertEqual(tab._auto_fetch_interval, 300)
        self.assertTrue(tab.fetch_button._repeat_enabled)

        tab.auto_fetch_toggle.setChecked(False)
        tab._toggle_auto_fetch()

        self.assertFalse(tab.auto_fetch_minutes.isEnabled())
        self.assertFalse(tab.fetch_button._repeat_enabled)

    def test_finance_tab_opens_invoice_window_from_quick_access(self) -> None:
        tab = finance_views.FinanceTab()
        self.addCleanup(tab.close)
        self.addCleanup(tab.deleteLater)

        with patch("Finance.views.finance_manager_window.FinanceManagerWindow", _FakeTopLevelWindow):
            tab.open_invoices_window()

        self.assertIsNotNone(tab.invoices_window)
        self.assertTrue(tab.invoices_window.isVisible())
        self.assertEqual(tab.invoices_window.reload_count, 0)

        tab.open_invoices_window()
        self.assertEqual(tab.invoices_window.reload_count, 1)

    def test_finance_tab_opens_transactions_window_from_quick_access(self) -> None:
        tab = finance_views.FinanceTab()
        self.addCleanup(tab.close)
        self.addCleanup(tab.deleteLater)

        with patch("Finance.views.finance_transactions_window.FinanceTransactionsWindow", _FakeTopLevelWindow):
            tab.open_transactions_window()

        self.assertIsNotNone(tab.transactions_window)
        self.assertTrue(tab.transactions_window.isVisible())
        self.assertEqual(tab.transactions_window.reload_count, 0)

        tab.open_transactions_window()
        self.assertEqual(tab.transactions_window.reload_count, 1)

    def test_finance_tab_quick_badges_follow_deltas_and_clear_on_open(self) -> None:
        tab = finance_views.FinanceTab()
        self.addCleanup(tab.close)
        self.addCleanup(tab.deleteLater)

        stock_signal = finance_views.stock_signals.quick_access_changed
        stock_signal.emit("brands", 2)
        stock_signal.emit("companies", 3)
        self.assertEqual(tab.brands_btn._badge_count, 2)
        self.assertEqual(tab.companies_btn._badge_count, 3)

        with patch("Finance.views.finance_brand_manager_window.FinanceBrandManagerDialog", _FakeTopLevelWindow):
            tab.open_brand_manager_window()
        self.assertEqual(tab.brands_btn._badge_count, 0)
        self.assertTrue(tab.brands_btn._active)

        with patch("Finance.views.finance_company_manager_window.FinanceCompanyManagerDialog", _FakeTopLevelWindow):
            tab.open_company_manager_window()
        self.assertEqual(tab.companies_btn._badge_count, 0)
        self.assertTrue(tab.companies_btn._active)

        pending_two = finance_views.Result.ok(data={"records": [{}, {}]}, close_dialog=False)
        pending_five = finance_views.Result.ok(data={"records": [{}, {}, {}, {}, {}]}, close_dialog=False)
        with patch("Finance.views.actions.load_finance_cost_items", side_effect=[pending_two, pending_five]), patch(
            "Finance.views.finance_cost_items_window.FinanceCostItemsWindow",
            _FakeTopLevelWindow,
        ):
            tab._refresh_cost_items_summary()
            self.assertEqual(tab.cost_items_btn._badge_count, 2)

            tab.open_cost_items_window()
            self.assertEqual(tab.cost_items_btn._badge_count, 0)

            tab.cost_items_window.hide()
            tab._on_cost_items_changed()
            self.assertEqual(tab.cost_items_btn._badge_count, 3)
            self.assertTrue(tab.cost_items_btn._active)
