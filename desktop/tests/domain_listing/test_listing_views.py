from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel, QFrame, QWidget

import Core.views as core_views
import Listing.views.views as listing_views
import Listing.views.listing_manager_window as listing_manager_window


class _FakeWorkspaceShell:
    def __init__(self) -> None:
        self.host = QWidget()
        self._left_panel_open = False
        self.active_panel_id = None
        self.left_highlight_enabled = False
        self.right_guidance_enabled = False
        self._state_changed_callback = None
        self._left_guidance_message_provider = None

    def set_state_changed_callback(self, callback) -> None:
        self._state_changed_callback = callback

    def set_left_guidance_message_provider(self, provider) -> None:
        self._left_guidance_message_provider = provider

    def is_left_panel_open(self) -> bool:
        return self._left_panel_open

    def sync_sidebar_active(self, panel_id) -> None:
        self.active_panel_id = panel_id

    def set_left_highlight_enabled(self, enabled: bool) -> None:
        self.left_highlight_enabled = bool(enabled)

    def set_right_guidance_enabled(self, enabled: bool) -> None:
        self.right_guidance_enabled = bool(enabled)

    def open_left_panel(self) -> None:
        self._left_panel_open = True

    def close_left_panel(self) -> None:
        self._left_panel_open = False


class _FakeListingTab:
    def __init__(self, list_widget) -> None:
        self.list_widget = list_widget
        self._selection_mode = "detail"
        self._active_listing_record = None
        self.behavior_cleared = False
        self.workspace_state_sync_count = 0

    def _selected_listing_count(self) -> int:
        return 0

    def _workspace_record_key(self, record) -> str:
        return str(self.list_widget._item_key_of(record) or "")

    def _on_listing_behavior_cleared(self) -> None:
        self.behavior_cleared = True
        self._selection_mode = "detail"

    def _sync_listing_workspace_state(self) -> None:
        self.workspace_state_sync_count += 1


class TestListingViews(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    @classmethod
    def _views_source(cls) -> str:
        return Path(listing_views.__file__).resolve().read_text(encoding="utf-8")

    @classmethod
    def _manager_source(cls) -> str:
        return Path(listing_manager_window.__file__).resolve().read_text(encoding="utf-8")

    def test_normalized_account_platform_canonicalizes_labels(self) -> None:
        self.assertEqual(listing_views._normalized_account_platform("Trendyol"), "TRENDYOL")
        self.assertEqual(listing_views._normalized_account_platform("hepsiburada"), "HEPSIBURADA")

    def test_listing_fetch_page_size_is_stage_safe(self) -> None:
        self.assertEqual(
            listing_views._listing_fetch_page_size([[1, "key", "secret", "seller", "tr-TR", "stage"]]),
            200,
        )
        self.assertEqual(
            listing_views._listing_fetch_page_size([[1, "key", "secret", "seller", "tr-TR", "production"]]),
            1000,
        )
        self.assertEqual(
            listing_views._listing_fetch_page_size(
                [
                    [1, "key", "secret", "seller", "tr-TR", "production"],
                    [2, "key", "secret", "seller", "tr-TR", "sandbox"],
                ]
            ),
            200,
        )

    def test_platform_filter_options_use_marketplace_labels_and_unique_codes(self) -> None:
        options = listing_views._platform_filter_options_from_account_platforms(
            {
                1: "Trendyol",
                2: "TRENDYOL",
                3: "HEPSIBURADA",
            }
        )

        self.assertEqual(options, [("Hepsiburada", "HEPSIBURADA"), ("Trendyol", "TRENDYOL")])

    def test_listing_badge_count_uses_inserted_and_updated_rows(self) -> None:
        self.assertEqual(
            listing_views._listing_badge_count_from_save_counts(
                {"inserted": 2, "updated": 3, "history": 7, "deleted": 1}
            ),
            6,
        )
        self.assertEqual(listing_views._listing_badge_count_from_save_counts({"history": 4}), 0)

    def test_listing_badge_count_includes_deleted_rows(self) -> None:
        self.assertEqual(
            listing_views._listing_badge_count_from_save_counts(
                {"inserted": 0, "updated": 0, "deleted": 4}
            ),
            4,
        )

    def test_listing_fetch_progress_uses_actual_worker_percent(self) -> None:
        self.assertEqual(listing_views._listing_fetch_percent(0, 4), 0)
        self.assertEqual(listing_views._listing_fetch_percent(2, 4), 50)
        self.assertEqual(listing_views._listing_fetch_percent(4, 4), 100)

    def test_listing_fetch_progress_waits_for_save_before_showing_100(self) -> None:
        class FakeProgressButton:
            def __init__(self) -> None:
                self.progress_values: list[int] = []

            def setProgress(self, value: int) -> None:
                self.progress_values.append(int(value))

        button = FakeProgressButton()
        fake_tab = SimpleNamespace(
            _fetch_progress_actual=0,
            _fetch_progress_display=0,
            fetch_button=button,
        )

        listing_views.ListingTab._set_fetch_progress_actual(fake_tab, 100)
        self.assertEqual(button.progress_values[-1], 99)

        listing_views.ListingTab._set_fetch_progress_actual(fake_tab, 40)
        self.assertEqual(button.progress_values, [99])

    def test_listing_fetch_button_waits_for_db_save_before_reenable(self) -> None:
        class FakeProgressButton:
            def __init__(self) -> None:
                self.enabled = False
                self.progress_values: list[int] = []
                self.failed = False
                self.reset_called = False

            def setEnabled(self, enabled: bool) -> None:
                self.enabled = bool(enabled)

            def setProgress(self, value: int) -> None:
                self.progress_values.append(int(value))

            def fail(self) -> None:
                self.failed = True

            def reset(self) -> None:
                self.reset_called = True

        button = FakeProgressButton()
        fake_tab = SimpleNamespace(
            _fetch_from_auto_repeat=True,
            _fetch_waiting_for_save=True,
            _fetch_failed=False,
            _fetch_progress_actual=100,
            _fetch_progress_display=100,
            fetch_button=button,
            _stop_fetch_progress=lambda: None,
        )
        fake_tab._set_fetch_progress_actual = lambda value: button.setProgress(int(value))
        fake_tab._reset_fetch_button_after_success = lambda: listing_views.ListingTab._reset_fetch_button_after_success(fake_tab)

        listing_views.ListingTab._on_worker_finished(fake_tab)
        self.assertFalse(button.enabled)
        self.assertTrue(fake_tab._fetch_waiting_for_save)

        listing_views.ListingTab._finish_fetch_progress(fake_tab, success=True)
        self.assertFalse(button.enabled)
        self.assertFalse(fake_tab._fetch_waiting_for_save)
        self.assertEqual(button.progress_values[-1], 100)

        listing_views.ListingTab._reset_fetch_button_after_success(fake_tab)
        self.assertTrue(button.enabled)
        self.assertTrue(button.reset_called)

    def test_listing_uses_core_resettable_splitter(self) -> None:
        self.assertIs(listing_views.ResettableSplitter, core_views.ResettableSplitter)

    def test_listing_signals_expose_extended_domain_events(self) -> None:
        for attr in (
            "fetch_started",
            "products_loaded",
            "products_save_started",
            "products_saved",
            "products_save_failed",
            "stock_matches_changed",
            "cost_matches_changed",
            "cost_snapshots_synced",
            "listing_cache_updated",
        ):
            self.assertTrue(hasattr(listing_views.listing_signals, attr), attr)

    def test_remove_stock_match_row_does_not_create_placeholder_row(self) -> None:
        rows = [{"stock_item_id": 12, "qty": 1}]
        self.assertEqual(listing_views._remove_stock_match_row_at(rows, 0), [])

    def test_cost_card_currency_defaults_to_try_and_uppercases(self) -> None:
        self.assertEqual(listing_views._cost_card_currency({"currency": "usd"}), "USD")
        self.assertEqual(listing_views._cost_card_currency({}), "TRY")

    def test_compact_cost_row_preserves_manual_amount_and_rule_config(self) -> None:
        manual_row = listing_views._compact_cost_row(
            {
                "cost_key": "paketleme",
                "source_type": "manual_value",
                "source_config": {"amount": 5.0},
            }
        )
        self.assertEqual(manual_row["amount"], 5.0)
        self.assertEqual(manual_row["source_config"], {"amount": 5.0})

        rule_row = listing_views._compact_cost_row(
            {
                "cost_key": "kargo",
                "source_type": "builtin_resolver",
                "source_config": {"ruleKey": "cargo_amount_matcher"},
            }
        )
        self.assertIsNone(rule_row["amount"])
        self.assertEqual(rule_row["source_config"], {"ruleKey": "cargo_amount_matcher"})

    def test_cost_row_requires_cargo_provider_for_cargo_card(self) -> None:
        row = listing_manager_window.CostItemRow(
            [
                {
                    "costKey": "kargo",
                    "name": "Kargo",
                    "valueType": "numeric",
                    "supportedSourceTypes": ["manual_value", "builtin_resolver"],
                    "defaultSourceType": "builtin_resolver",
                    "defaultSourceConfig": {"ruleKey": "cargo_amount_matcher"},
                }
            ],
            cargo_providers=[
                {
                    "pk": 41,
                    "platformCode": "TRENDYOL",
                    "cargoProviderCode": "ARAS",
                    "cargoProviderName": "Aras Kargo Marketplace",
                }
            ],
            row_index=0,
            on_change=lambda *_args: None,
            selected_key="kargo",
            source_type="builtin_resolver",
            source_config={"ruleKey": "cargo_amount_matcher"},
        )
        try:
            self.assertIsNone(row.value())
            row.cargo_provider_combo.setCurrentIndex(0)
            self._app.processEvents()
            self.assertEqual(
                row.state().get("source_config"),
                {
                    "ruleKey": "cargo_amount_matcher",
                    "cargoProviderId": 41,
                    "cargoProviderCode": "ARAS",
                    "cargoProviderName": "Aras Kargo Marketplace",
                },
            )
            self.assertIsNotNone(row.value())
        finally:
            row.close()
            row.deleteLater()
            self._app.processEvents()

    def test_cost_row_keeps_remove_button_compact_and_syncs_visible_hosts(self) -> None:
        row = listing_manager_window.CostItemRow(
            [
                {
                    "costKey": "kargo",
                    "name": "Kargo",
                    "valueType": "numeric",
                    "supportedSourceTypes": ["manual_value", "builtin_resolver"],
                    "defaultSourceType": "builtin_resolver",
                    "defaultSourceConfig": {"ruleKey": "cargo_amount_matcher"},
                },
                {
                    "costKey": "komisyon",
                    "name": "Komisyon",
                    "valueType": "percentage",
                    "supportedSourceTypes": ["manual_value"],
                    "defaultSourceType": "manual_value",
                    "defaultSourceConfig": {"amount": 12.0},
                },
            ],
            cargo_providers=[
                {
                    "pk": 42,
                    "platformCode": "TRENDYOL",
                    "cargoProviderCode": "TEX",
                    "cargoProviderName": "Trendyol Express Marketplace",
                }
            ],
            row_index=0,
            on_change=lambda *_args: None,
            selected_key="komisyon",
            source_type="manual_value",
            source_config={"amount": 12.0},
        )
        try:
            row.show()
            self._app.processEvents()
            self.assertLessEqual(row.btn_remove.width(), 80)
            self.assertTrue(row.amount_host.isVisible())
            self.assertFalse(row.source_field_host.isVisible())
            self.assertFalse(row.cargo_provider_host.isVisible())

            row.cb.setCurrentText("Kargo")
            self._app.processEvents()
            mode_index = row.mode_combo.findData("builtin_resolver")
            row.mode_combo.setCurrentIndex(mode_index)
            self._app.processEvents()

            self.assertFalse(row.amount_host.isVisible())
            self.assertFalse(row.source_field_host.isVisible())
            self.assertTrue(row.cargo_provider_host.isVisible())
        finally:
            row.close()
            row.deleteLater()
            self._app.processEvents()

    def test_listing_manager_decorate_product_uses_selected_cargo_provider_tariff(self) -> None:
        window = listing_manager_window.ListingManagerWindow()
        try:
            window._account_platform_map = {1: "TRENDYOL"}
            window._stock_cost_map = {7: 10.0}
            window._stock_vat_rate_map = {7: 20.0}
            window._stock_cost_meta_map = {}
            window._stock_dimension_map = {}
            window._cost_items_cache = [
                {
                    "costKey": "kargo",
                    "name": "Kargo",
                    "label": "Kargo",
                    "valueType": "numeric",
                    "defaultSourceType": "builtin_resolver",
                    "defaultSourceConfig": {"ruleKey": "cargo_amount_matcher"},
                    "supportedSourceTypes": ["builtin_resolver"],
                    "isVatIncluded": False,
                    "vatRate": 20.0,
                    "supportedPlatforms": ["TRENDYOL"],
                }
            ]
            window._cargo_tariffs_cache = [
                {
                    "tariffKey": "ptt-0",
                    "name": "Trendyol PTT 0 Desi",
                    "platformCode": "TRENDYOL",
                    "cargo_provider_id": 41,
                    "cargoProviderCode": "PTT",
                    "cargoProviderName": "Ptt Kargo Marketplace",
                    "minDesi": 0,
                    "maxDesi": 0,
                    "amount": 77.54,
                    "isVatIncluded": False,
                    "vatRate": 20.0,
                    "isActive": True,
                },
                {
                    "tariffKey": "tex-0",
                    "name": "Trendyol Express 0 Desi",
                    "platformCode": "TRENDYOL",
                    "cargo_provider_id": 42,
                    "cargoProviderCode": "TEX",
                    "cargoProviderName": "Trendyol Express Marketplace",
                    "minDesi": 0,
                    "maxDesi": 0,
                    "amount": 12.0,
                    "isVatIncluded": False,
                    "vatRate": 20.0,
                    "isActive": True,
                },
            ]

            product = {
                "api_account_id": 1,
                "productId": "P-1",
                "title": "Ornek Ilan",
                "salePrice": 114.99,
                "vatRate": 20.0,
                "dimensionalWeight": None,
                "stock_items": [{"stock_item_id": 7, "qty": 1}],
                "cost_items": [
                    {
                        "cost_key": "kargo",
                        "source_type": "builtin_resolver",
                        "source_config": {
                            "ruleKey": "cargo_amount_matcher",
                            "cargoProviderId": 42,
                            "cargoProviderCode": "TEX",
                            "cargoProviderName": "Trendyol Express Marketplace",
                        },
                    }
                ],
            }

            window._decorate_product(product, sync_cost_snapshot=False)

            self.assertEqual(product.get("matched_cargo_tariff_key"), "tex-0")
            detail = dict(product.get("estimated_profit_detail") or {})
            summary = dict(detail.get("summary") or {})
            self.assertEqual(summary.get("cargo_tariff_name"), "Trendyol Express 0 Desi")
        finally:
            window.close()
            window.deleteLater()
            self._app.processEvents()

    def test_prepare_listing_items_reuses_large_lookup_maps(self) -> None:
        items = [
            {
                "api_account_id": 1,
                "productId": "P-1",
                "stock_items": [{"stock_item_id": 7, "qty": 1}],
            },
            {
                "api_account_id": 1,
                "productId": "P-2",
                "stock_items": [{"stock_item_id": 8, "qty": 1}],
            },
        ]
        account_name_map = {1: "Store"}
        account_logo_map = {1: "logo.png"}
        account_platform_map = {1: "TRENDYOL"}
        stock_item_label_map = {i: f"SKU-{i}" for i in range(100)}
        stock_cost_map = {i: float(i) for i in range(100)}
        stock_vat_rate_map = {i: 20.0 for i in range(100)}
        stock_cost_meta_map = {i: {"input_mode": "gross"} for i in range(100)}
        stock_dimension_map = {i: {"weight_kg": 1.0} for i in range(100)}
        cost_items_cache = [
            {
                "costKey": "komisyon",
                "name": "Komisyon",
                "valueType": "percentage",
                "supportedPlatforms": ["TRENDYOL"],
            }
        ]
        cargo_tariffs = [{"tariffKey": "cargo-1", "amount": 10.0}]

        with patch.object(
            listing_manager_window,
            "estimate_listing_profit",
            return_value={"estimated_profit": 1.0},
        ) as mock_estimate:
            listing_manager_window._prepare_listing_items_for_view(
                items,
                account_name_map=account_name_map,
                account_logo_map=account_logo_map,
                account_platform_map=account_platform_map,
                stock_item_label_map=stock_item_label_map,
                stock_cost_map=stock_cost_map,
                stock_vat_rate_map=stock_vat_rate_map,
                stock_cost_meta_map=stock_cost_meta_map,
                stock_dimension_map=stock_dimension_map,
                cost_items_cache=cost_items_cache,
                cargo_tariffs=cargo_tariffs,
            )

        self.assertEqual(mock_estimate.call_count, 2)
        for call in mock_estimate.call_args_list:
            self.assertIs(call.kwargs["stock_cost_map"], stock_cost_map)
            self.assertIs(call.kwargs["stock_vat_rate_map"], stock_vat_rate_map)
            self.assertIs(call.kwargs["stock_cost_meta_map"], stock_cost_meta_map)
            self.assertIs(call.kwargs["stock_dimension_map"], stock_dimension_map)
            self.assertIs(call.kwargs["cargo_tariffs"], cargo_tariffs)

    def test_cost_match_dialog_manual_cargo_row_keeps_hosts_non_overlapping(self) -> None:
        dlg = listing_manager_window.CostMatchDialog(
            None,
            product_title="Ornek",
            cost_items=[
                {
                    "costKey": "kargo",
                    "name": "Kargo",
                    "valueType": "numeric",
                    "supportedSourceTypes": ["manual_value", "builtin_resolver"],
                    "defaultSourceType": "manual_value",
                    "defaultSourceConfig": {"amount": 10.0},
                }
            ],
            cargo_providers=[
                {
                    "pk": 42,
                    "platformCode": "TRENDYOL",
                    "cargoProviderCode": "TEX",
                    "cargoProviderName": "Trendyol Express Marketplace",
                }
            ],
            current_items=[
                {
                    "cost_key": "kargo",
                    "source_type": "manual_value",
                    "source_config": {
                        "amount": 10.0,
                        "cargoProviderId": 42,
                        "cargoProviderCode": "TEX",
                        "cargoProviderName": "Trendyol Express Marketplace",
                    },
                }
            ],
        )
        try:
            dlg.show()
            self._app.processEvents()
            row = dlg._row_widgets[0][1]
            self.assertFalse(row.cost_host.geometry().intersects(row.mode_host.geometry()))
            self.assertFalse(row.mode_host.geometry().intersects(row.amount_host.geometry()))
            self.assertFalse(row.amount_host.geometry().intersects(row.cargo_provider_host.geometry()))
            self.assertFalse(row.cargo_provider_host.geometry().intersects(row.btn_remove.geometry()))
        finally:
            dlg.close()
            dlg.deleteLater()
            self._app.processEvents()

    def test_cost_match_dialog_percentage_input_stays_inside_amount_host(self) -> None:
        dlg = listing_manager_window.CostMatchDialog(
            None,
            product_title="Ornek",
            cost_items=[
                {
                    "costKey": "komisyon",
                    "name": "Komisyon",
                    "valueType": "percentage",
                    "supportedSourceTypes": ["manual_value"],
                    "defaultSourceType": "manual_value",
                    "defaultSourceConfig": {"amount": 12.0},
                }
            ],
            cargo_providers=[],
            current_items=[
                {
                    "cost_key": "komisyon",
                    "source_type": "manual_value",
                    "source_config": {"amount": 12.0},
                }
            ],
        )
        try:
            dlg.show()
            self._app.processEvents()
            row = dlg._row_widgets[0][1]
            self.assertTrue(row.percent_input.isVisible())
            self.assertTrue(row.amount_host.rect().contains(row.percent_input.geometry()))
        finally:
            dlg.close()
            dlg.deleteLater()
            self._app.processEvents()

    def test_listing_views_py_keeps_tab_and_facade_role(self) -> None:
        source = self._views_source()
        self.assertNotIn("from .listing_manager_window import *", source)
        self.assertIn("from .listing_manager_window import ListingManagerWindow", source)
        self.assertIn("class ListingTab(QWidget):", source)
        self.assertNotIn("class ListingManagerWindow(QWidget):", source)

    def test_listing_sources_do_not_contain_mojibake(self) -> None:
        combined = self._views_source() + "\n" + self._manager_source()
        for token in ("\u00C3", "\u00C4", "\u00C5", "\u00E2"):
            self.assertNotIn(token, combined)

    def test_listing_manager_window_uses_listing_constants_for_platform_and_ui_tokens(self) -> None:
        source = self._manager_source()
        self.assertIn("from Listing.constants.platform_constants import", source)
        self.assertIn("from Listing.constants.ui_constants import", source)
        self.assertNotIn("from Marketplaces.constants.catalog_constants import", source)
        self.assertIn("account_signals.company_changed.connect(self._request_catalog_refresh)", source)
        self.assertIn("marketplace_signals.marketplaces_changed.connect(self._request_catalog_refresh)", source)
        self.assertIn("logistics_signals.cargo_providers_changed.connect(self._request_catalog_refresh)", source)
        self.assertIn("logistics_signals.cargo_tariffs_changed.connect(self._request_catalog_refresh)", source)

    def test_listing_manager_window_drops_local_overlay_and_shell_fallback(self) -> None:
        source = self._manager_source()
        self.assertIn("RecordWorkspaceScaffold(", source)
        self.assertIn("compose_record_workspace_style(LISTING_STYLE)", source)
        self.assertNotIn("RecordWorkspaceSplitShell(", source)
        self.assertNotIn("AnimatedGuidanceRing", source)
        self.assertNotIn("EditLockOverlay", source)
        self.assertNotIn("fallback_total_width", source)
        self.assertNotIn("count_label", source)
        self.assertNotIn("btn_tools_selection_toggle", source)
        self.assertNotIn("btn_selection_toggle", source)

    def test_listing_cost_items_cache_excludes_unaccepted_builtin_templates(self) -> None:
        window = listing_manager_window.ListingManagerWindow()
        try:
            payload = {
                "records": [
                    {
                        "costKey": "kargo",
                        "name": "Kargo",
                        "valueType": "numeric",
                        "valueTypeLabel": "Sayısal",
                        "defaultMatchMode": "manual",
                        "defaultMatchModeLabel": "Manuel",
                        "defaultSourceType": "manual_value",
                        "defaultSourceTypeLabel": "Manuel Değer",
                        "defaultSourceConfig": None,
                        "defaultAmount": 10.0,
                        "currency": "TRY",
                        "isVatIncluded": True,
                        "vatRate": 20,
                        "supportedPlatforms": ["TRENDYOL"],
                        "isBuiltin": True,
                        "isBuiltinAccepted": False,
                    },
                    {
                        "costKey": "paketleme",
                        "name": "Paketleme",
                        "valueType": "numeric",
                        "valueTypeLabel": "Sayısal",
                        "defaultMatchMode": "manual",
                        "defaultMatchModeLabel": "Manuel",
                        "defaultSourceType": "manual_value",
                        "defaultSourceTypeLabel": "Manuel Değer",
                        "defaultSourceConfig": None,
                        "defaultAmount": 3.0,
                        "currency": "TRY",
                        "isVatIncluded": True,
                        "vatRate": 20,
                        "supportedPlatforms": ["TRENDYOL"],
                        "isBuiltin": True,
                        "isBuiltinAccepted": True,
                    },
                    {
                        "costKey": "komisyon",
                        "name": "Komisyon",
                        "valueType": "percentage",
                        "valueTypeLabel": "Yüzdesel",
                        "defaultMatchMode": "manual",
                        "defaultMatchModeLabel": "Manuel",
                        "defaultSourceType": "manual_value",
                        "defaultSourceTypeLabel": "Manuel Değer",
                        "defaultSourceConfig": None,
                        "defaultAmount": 12.0,
                        "currency": "TRY",
                        "isVatIncluded": True,
                        "vatRate": 20,
                        "supportedPlatforms": ["TRENDYOL"],
                        "isBuiltin": False,
                        "isBuiltinAccepted": True,
                    },
                ]
            }
            with patch.object(
                listing_manager_window,
                "action_load_finance_cost_items",
                return_value=listing_manager_window.Result.ok("ok", data=payload, close_dialog=False),
            ):
                window._load_cost_items_cache()
            self.assertEqual(
                [row.get("costKey") for row in window._cost_items_cache],
                ["paketleme", "komisyon"],
            )
        finally:
            window.close()
            window.deleteLater()
            self._app.processEvents()

    def test_listing_manager_delegate_uses_core_select_hook_contract(self) -> None:
        self.assertTrue(
            issubclass(listing_manager_window.ListingListDelegate, core_views.RecordWorkspaceListDelegate)
        )

    def test_listing_manager_refreshes_catalog_caches_when_company_signal_emits(self) -> None:
        with patch.object(
            listing_manager_window.ListingManagerWindow,
            "_load_cached_products",
            autospec=True,
        ) as mock_load:
            window = listing_manager_window.ListingManagerWindow()
            try:
                window._cache_loaded = True
                window.show()
                self._app.processEvents()
                mock_load.reset_mock()

                listing_manager_window.account_signals.company_changed.emit()
                self._app.processEvents()

                self.assertTrue(mock_load.called)
            finally:
                window.close()
                window.deleteLater()
                self._app.processEvents()

    def test_open_profit_detail_reuses_cached_estimation_without_recompute(self) -> None:
        window = listing_manager_window.ListingManagerWindow()
        try:
            window._account_platform_map = {1: "TRENDYOL"}
            window._stock_items_cache = [{"id": 7, "label": "SKU-7 - Stock 7"}]
            window._stock_item_label_map = {7: "SKU-7 - Stock 7"}
            product = {
                "api_account_id": 1,
                "productId": "P-1",
                "title": "Hazir Karlilik",
                "stock_items": [{"stock_item_id": 7, "qty": 1}],
                "estimated_profit_detail": {
                    "summary": {"sale_quantity": 1},
                    "applied_costs": [],
                    "results": {},
                },
                "estimated_profit_breakdown": [],
                "estimated_profit_missing_reasons": [],
            }

            with patch.object(window, "_refresh_product_profit_estimation") as mock_refresh, patch.object(
                window,
                "_load_stock_items_cache",
            ) as mock_load_stock, patch.object(
                listing_manager_window.ProfitBreakdownDialog,
                "showMaximized",
                autospec=True,
                return_value=0,
            ) as mock_show:
                window._open_profit_detail(product)

            mock_refresh.assert_not_called()
            mock_load_stock.assert_not_called()
            self.assertTrue(mock_show.called)
        finally:
            window.close()
            window.deleteLater()
            self._app.processEvents()

    def test_load_stock_items_cache_uses_pk_based_stock_ids(self) -> None:
        window = listing_manager_window.ListingManagerWindow()
        try:
            stock_row = SimpleNamespace(
                pk=17,
                id=None,
                sku="SKU-17",
                name="Stock 17",
                vat_rate=20.0,
                weight_kg=None,
                length_cm=None,
                width_cm=None,
                height_cm=None,
            )
            balance_row = {
                "item": stock_row,
                "avg_unit_cost": 12.5,
                "avg_cost_input_mode": "gross",
            }

            with patch.object(
                listing_manager_window,
                "action_list_items",
                return_value=SimpleNamespace(success=True, data={"records": [stock_row]}),
            ), patch.object(
                listing_manager_window,
                "action_list_item_balances",
                return_value=SimpleNamespace(success=True, data={"records": [balance_row]}),
            ):
                window._load_stock_items_cache()

            self.assertEqual(window._stock_items_cache, [{"id": 17, "label": "SKU-17 - Stock 17"}])
            self.assertEqual(window._stock_item_label_map[17], "SKU-17 - Stock 17")
            self.assertEqual(window._stock_cost_map[17], 12.5)
        finally:
            window.close()
            window.deleteLater()
            self._app.processEvents()

    def test_local_cost_match_signal_does_not_trigger_full_list_refresh(self) -> None:
        window = listing_manager_window.ListingManagerWindow()
        try:
            window._pending_local_cost_refresh_keys.add((1, "P-1"))
            with patch.object(window, "_refresh_from_listing_signal") as mock_refresh:
                window._on_listing_cost_matches_changed({"api_account_id": 1, "product_id": "P-1"})
            mock_refresh.assert_not_called()
            self.assertFalse(window._pending_local_cost_refresh_keys)
        finally:
            window.close()
            window.deleteLater()
            self._app.processEvents()

    def test_refresh_record_preserves_payload_when_same_object_instance_is_updated(self) -> None:
        list_widget = listing_manager_window.ListingListWidget()
        try:
            item = {
                "api_account_id": 1,
                "productId": "P-1",
                "title": "Ilk Kayit",
                "barcode": "ABC",
                "stockCode": "STK-1",
                "salePrice": 25.0,
            }
            list_widget.set_items([item])

            same_ref = list_widget.items[0]
            same_ref["title"] = "Guncel Kayit"
            same_ref["salePrice"] = 30.0

            self.assertTrue(list_widget.refresh_record(same_ref))
            refreshed = list_widget.items[0]
            self.assertEqual(refreshed.get("title"), "Guncel Kayit")
            self.assertEqual(refreshed.get("salePrice"), 30.0)
            self.assertEqual(refreshed.get("barcode"), "ABC")
            self.assertEqual(refreshed.get("stockCode"), "STK-1")
        finally:
            list_widget.deleteLater()
            self._app.processEvents()

    def test_profit_breakdown_dialog_reuses_precomputed_initial_estimation(self) -> None:
        parent = QWidget()
        product = {
            "title": "Hazir Dialog",
            "stock_items": [{"stock_item_id": 7, "qty": 1}],
            "estimated_profit_detail": {
                "summary": {"sale_quantity": 1},
                "applied_costs": [],
                "results": {},
            },
            "estimated_profit_breakdown": [],
            "estimated_profit_missing_reasons": [],
        }
        with patch.object(listing_manager_window, "estimate_listing_profit") as mock_estimate:
            dlg = listing_manager_window.ProfitBreakdownDialog(
                parent,
                product_title="Hazir Dialog",
                product=product,
                estimation_context={
                    "stock_item_label_map": {7: "SKU-7 - Stock 7"},
                    "stock_cost_map": {7: 10.0},
                    "stock_vat_rate_map": {7: 20.0},
                    "stock_cost_meta_map": {},
                    "stock_dimension_map": {},
                    "cost_card_map": {},
                    "cargo_tariffs": [],
                    "platform_code": "TRENDYOL",
                },
            )
            try:
                mock_estimate.assert_not_called()
                dlg.sale_qty.setValue(2)
                self._app.processEvents()
                self.assertEqual(mock_estimate.call_count, 1)
            finally:
                dlg.close()
                dlg.deleteLater()
                parent.deleteLater()
                self._app.processEvents()

    def test_profit_breakdown_dialog_paginates_sale_and_cost_drawers(self) -> None:
        parent = QWidget()
        product = {
            "title": "Sayfali Dialog",
            "estimated_profit_ready": True,
            "estimated_profit": 100.0,
            "estimated_profit_text": "100.00 TL",
            "estimated_profit_missing_reasons": [f"Eksik {idx}" for idx in range(9)],
            "estimated_profit_detail": {
                "summary": {
                    "sale_quantity": 1,
                    "sale_quantity_text": "1",
                    "unit_sale_price_text": "150.00 TL",
                    "sale_price_text": "150.00 TL",
                    "linked_stock_label": "SKU - Stok",
                },
                "results": {
                    "total_costs": 50.0,
                    "total_costs_text": "50.00 TL",
                    "estimated_profit_text": "100.00 TL",
                },
                "applied_costs": [
                    {"label": f"Maliyet {idx}", "gross": 1.0, "note": f"Satir {idx}"}
                    for idx in range(9)
                ],
            },
            "estimated_profit_breakdown": [],
        }
        dlg = listing_manager_window.ProfitBreakdownDialog(
            parent,
            product_title="Sayfali Dialog",
            product=product,
            estimation_context={},
        )
        try:
            dlg._summary_expanded = True
            dlg._active_detail_tabs = {"sale", "cost"}
            dlg._rebuild_body()
            self._app.processEvents()

            bars = [frame for frame in dlg.findChildren(QFrame) if frame.objectName() == "DetailPaginationBar"]
            self.assertEqual(len(bars), 1)
            self.assertEqual(dlg._detail_page_indexes["cost"], 0)

            dlg._change_detail_page("cost", 1)
            self._app.processEvents()

            self.assertEqual(dlg._detail_page_indexes["cost"], 1)
            self.assertEqual(dlg._active_detail_tabs, {"sale", "cost"})
            labels = [label.text() for label in dlg.findChildren(QLabel)]
            self.assertIn("Sayfa 2 / 3", labels)
            viewport_drawers = [
                drawer
                for drawer in dlg.body_scroll.viewport().findChildren(listing_manager_window.SmoothHeightFrame)
                if drawer.objectName() == "InnerDrawer"
            ]
            self.assertLessEqual(len(viewport_drawers), 2)

            self.assertFalse(dlg._missing_expanded)
            dlg._toggle_missing_expanded()
            self._app.processEvents()

            self.assertTrue(dlg._missing_expanded)
            self.assertEqual(dlg._missing_page_index, 0)
            missing_rows = [
                frame for frame in dlg.findChildren(QFrame) if frame.objectName() == "MissingReasonRow"
            ]
            self.assertEqual(len(missing_rows), dlg._MISSING_ROWS_PER_PAGE)
            labels = [label.text() for label in dlg.findChildren(QLabel)]
            self.assertIn("Sayfa 1 / 3", labels)

            dlg._change_missing_page(1)
            self._app.processEvents()

            self.assertEqual(dlg._missing_page_index, 1)
            labels = [label.text() for label in dlg.findChildren(QLabel)]
            self.assertIn("Sayfa 2 / 3", labels)
        finally:
            dlg.close()
            dlg.deleteLater()
            parent.deleteLater()
            self._app.processEvents()

    def test_profit_breakdown_dialog_detail_drawers_animate_without_rebuilding_body(self) -> None:
        parent = QWidget()
        product = {
            "title": "Smooth Dialog",
            "estimated_profit_ready": True,
            "estimated_profit": 35.0,
            "estimated_profit_text": "35.00 TL",
            "estimated_profit_missing_reasons": ["Stok eşleşmesi bekleniyor"],
            "estimated_profit_detail": {
                "summary": {
                    "sale_quantity": 1,
                    "sale_quantity_text": "1",
                    "unit_sale_price_text": "100.00 TL",
                    "sale_price_text": "100.00 TL",
                    "linked_stock_label": "SKU - Stok",
                },
                "results": {
                    "total_costs": 65.0,
                    "total_costs_text": "65.00 TL",
                    "estimated_profit_text": "35.00 TL",
                },
                "applied_costs": [
                    {"label": f"Maliyet {idx}", "gross": 5.0 + idx, "note": f"Satir {idx}"}
                    for idx in range(9)
                ],
            },
            "estimated_profit_breakdown": [],
        }
        dlg = listing_manager_window.ProfitBreakdownDialog(
            parent,
            product_title="Smooth Dialog",
            product=product,
            estimation_context={},
        )
        try:
            dlg.resize(1000, 560)
            dlg.show()
            self._app.processEvents()
            dlg._summary_expanded = True
            dlg._rebuild_body()
            for _ in range(3):
                self._app.processEvents()
                QTest.qWait(15)

            self.assertEqual(dlg._body_layout.contentsMargins().right(), 18)
            before_count = dlg._body_layout.count()
            cost_drawer = dlg._summary_cards["cost"]["drawer"]
            sale_card = dlg._summary_cards["sale"]["button"]
            cost_card = dlg._summary_cards["cost"]["button"]
            sale_geometry = sale_card.geometry()
            cost_geometry = cost_card.geometry()
            self.assertTrue(cost_drawer.isHidden())
            bar = dlg.body_scroll.verticalScrollBar()
            bar.setValue(min(60, bar.maximum()))
            frozen_value = bar.value()
            frozen_width = dlg._body_content.width()

            dlg._toggle_detail_tab("cost")
            self._app.processEvents()
            drawer_y = cost_drawer.y()

            self.assertIs(cost_drawer, dlg._summary_cards["cost"]["drawer"])
            self.assertEqual(dlg._body_layout.count(), before_count)
            self.assertFalse(cost_drawer.isHidden())
            self.assertTrue(cost_drawer.isAnimating())
            self.assertGreater(cost_drawer.expandedHeight(), 120)
            self.assertEqual(cost_drawer.targetHeight(), cost_drawer.expandedHeight())
            self.assertEqual(dlg.detail_drawer_spacer.maximumHeight(), cost_drawer.expandedHeight() + 24)
            self.assertEqual(sale_card.geometry(), sale_geometry)
            self.assertEqual(cost_card.geometry(), cost_geometry)
            observed_values = []
            observed_widths = []
            observed_heights = []
            observed_drawer_y = []
            observed_spacer_heights = []
            QTest.qWait(100)
            self._app.processEvents()
            observed_values.append(bar.value())
            observed_widths.append(dlg._body_content.width())
            observed_heights.append(cost_drawer.maximumHeight())
            observed_drawer_y.append(cost_drawer.y())
            observed_spacer_heights.append(dlg.detail_drawer_spacer.maximumHeight())
            self.assertEqual(cost_drawer.y(), drawer_y)
            self.assertEqual(sale_card.geometry(), sale_geometry)
            self.assertEqual(cost_card.geometry(), cost_geometry)
            self.assertGreater(cost_drawer.maximumHeight(), 0)
            self.assertLess(cost_drawer.maximumHeight(), cost_drawer.expandedHeight())
            for _ in range(5):
                QTest.qWait(20)
                self._app.processEvents()
                observed_values.append(bar.value())
                observed_widths.append(dlg._body_content.width())
                observed_heights.append(cost_drawer.maximumHeight())
                observed_drawer_y.append(cost_drawer.y())
                observed_spacer_heights.append(dlg.detail_drawer_spacer.maximumHeight())
            self.assertEqual(observed_values, [frozen_value] * len(observed_values))
            self.assertEqual(observed_widths, [frozen_width] * len(observed_widths))
            self.assertLessEqual(max(observed_drawer_y) - min(observed_drawer_y), 0)
            self.assertEqual(
                observed_spacer_heights,
                [cost_drawer.expandedHeight() + 24] * len(observed_spacer_heights),
            )
            height_steps = [
                next_height - current_height
                for current_height, next_height in zip(observed_heights, observed_heights[1:])
            ]
            self.assertTrue(height_steps)
            self.assertLessEqual(max(height_steps), 32)
            QTest.qWait(1500)
            self._app.processEvents()
            viewport = dlg.body_scroll.viewport()
            missing_panels = [
                panel
                for panel in dlg.findChildren(QFrame)
                if panel.objectName() == "MissingPanel" and panel.isVisible()
            ]
            self.assertTrue(missing_panels)
            missing_top = missing_panels[0].mapTo(viewport, QPoint(0, 0)).y()
            drawer_bottom = cost_drawer.y() + cost_drawer.maximumHeight()
            self.assertGreaterEqual(missing_top - drawer_bottom, 8)

            dlg._toggle_detail_tab("cost")

            self.assertIs(cost_drawer, dlg._summary_cards["cost"]["drawer"])
            self.assertEqual(dlg._body_layout.count(), before_count)
            self.assertFalse(cost_drawer.isHidden())
            self.assertTrue(cost_drawer.isAnimating())
            QTest.qWait(1500)
            self._app.processEvents()
            self.assertTrue(cost_drawer.isHidden())
            self.assertEqual(dlg.detail_drawer_spacer.maximumHeight(), 0)
        finally:
            dlg.close()
            dlg.deleteLater()
            parent.deleteLater()
            self._app.processEvents()

    def test_listing_card_click_switches_active_record_without_closing_panel(self) -> None:
        list_widget = listing_manager_window.ListingListWidget()
        list_widget.set_items(
            [
                {"api_account_id": 101, "productId": "P-1001", "title": "Ilk"},
                {"api_account_id": 202, "productId": "P-1001", "title": "Ikinci"},
            ]
        )
        shell = _FakeWorkspaceShell()
        tab = _FakeListingTab(list_widget)
        adapter = listing_manager_window.ListingWorkspaceBehaviorAdapter(tab)
        controller = core_views.RecordWorkspaceBehaviorController(
            shell=shell,
            adapter=adapter,
            auto_wire_sidebar=False,
        )

        self._app.processEvents()
        first_index = list_widget.model().index(0, 0)
        second_index = list_widget.model().index(1, 0)

        list_widget._on_row_clicked(first_index)
        self._app.processEvents()
        self.assertTrue(shell.is_left_panel_open())
        self.assertEqual(list_widget._active_listing_key, "api_account_id:101|productId:P-1001")

        list_widget._on_row_clicked(second_index)
        self._app.processEvents()

        self.assertTrue(shell.is_left_panel_open())
        self.assertEqual(list_widget._active_listing_key, "api_account_id:202|productId:P-1001")
        self.assertFalse(tab.behavior_cleared)
        self.assertEqual(shell.active_panel_id, "edit")
        controller.deleteLater()

    def test_listing_icon_click_switches_active_record_without_closing_panel(self) -> None:
        list_widget = listing_manager_window.ListingListWidget()
        list_widget.resize(1400, 600)
        list_widget.set_items(
            [
                {"api_account_id": 101, "productId": "P-1001", "title": "Ilk", "barcode": "B1", "stockCode": "S1"},
                {"api_account_id": 202, "productId": "P-1001", "title": "Ikinci", "barcode": "B2", "stockCode": "S2"},
            ]
        )
        list_widget.show()
        self._app.processEvents()

        shell = _FakeWorkspaceShell()
        tab = _FakeListingTab(list_widget)
        adapter = listing_manager_window.ListingWorkspaceBehaviorAdapter(tab)
        controller = core_views.RecordWorkspaceBehaviorController(
            shell=shell,
            adapter=adapter,
            auto_wire_sidebar=False,
        )

        self._app.processEvents()
        QTest.mouseClick(
            list_widget.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(30, 40),
        )
        self._app.processEvents()
        self.assertTrue(shell.is_left_panel_open())
        self.assertEqual(list_widget._active_listing_key, "api_account_id:101|productId:P-1001")

        QTest.mouseClick(
            list_widget.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(30, 220),
        )
        self._app.processEvents()

        self.assertTrue(shell.is_left_panel_open())
        self.assertEqual(list_widget._active_listing_key, "api_account_id:202|productId:P-1001")
        self.assertFalse(tab.behavior_cleared)
        controller.deleteLater()

    def test_listing_right_side_rects_shrink_without_crushing_text_area(self) -> None:
        rect = QRect(0, 0, 1360, 176)
        delegate = listing_manager_window.ListingListDelegate()
        side_rects = listing_manager_window._listing_right_side_rects(rect, hook_delegate=delegate)
        text_left = 10 + 110 + 12
        text_right = side_rects["qty"].left() - listing_manager_window.LISTING_TEXT_CLUSTER_GAP

        self.assertFalse(side_rects["compact"])
        self.assertGreaterEqual(text_right - text_left, 220)
        self.assertLess(side_rects["qty"].right(), side_rects["price"].left())
        self.assertLess(side_rects["price"].right(), side_rects["cost_badge"].left())
        self.assertLess(side_rects["cost_badge"].right(), side_rects["hook"].left())
        self.assertLessEqual(abs(side_rects["hook"].center().y() - rect.center().y()), 1)

    def test_listing_right_side_rects_compact_mode_hides_badges_and_keeps_hook_visible(self) -> None:
        rect = QRect(0, 0, 760, 176)
        delegate = listing_manager_window.ListingListDelegate()
        side_rects = listing_manager_window._listing_right_side_rects(rect, hook_delegate=delegate)
        text_left = 10 + 110 + 12
        text_right = side_rects["qty"].left() - listing_manager_window.LISTING_TEXT_CLUSTER_GAP

        self.assertTrue(side_rects["compact"])
        self.assertTrue(side_rects["badges_hidden"])
        self.assertTrue(side_rects["cost_badge"].isNull())
        self.assertTrue(side_rects["product_badge"].isNull())
        self.assertGreaterEqual(text_right - text_left, 200)
        self.assertLess(side_rects["qty"].right(), side_rects["price"].left())
        self.assertLess(side_rects["price"].right(), side_rects["hook"].left())
        self.assertLessEqual(abs(side_rects["hook"].center().y() - rect.center().y()), 1)

    def test_listing_right_side_rects_transitional_width_hides_badges_before_text_collides(self) -> None:
        rect = QRect(0, 0, 1140, 176)
        delegate = listing_manager_window.ListingListDelegate()
        side_rects = listing_manager_window._listing_right_side_rects(rect, hook_delegate=delegate)
        text_left = 10 + 110 + 12
        text_right = side_rects["qty"].left() - listing_manager_window.LISTING_TEXT_CLUSTER_GAP

        self.assertTrue(side_rects["compact"])
        self.assertTrue(side_rects["badges_hidden"])
        self.assertGreaterEqual(text_right - text_left, 300)
        self.assertLess(side_rects["price"].right(), side_rects["hook"].left())
        self.assertLessEqual(abs(side_rects["hook"].center().y() - rect.center().y()), 1)

    def test_listing_right_side_rects_compact_mode_keeps_badges_visible_when_possible(self) -> None:
        rect = QRect(0, 0, 1160, 176)
        delegate = listing_manager_window.ListingListDelegate()
        side_rects = listing_manager_window._listing_right_side_rects(rect, hook_delegate=delegate)
        text_left = 10 + 110 + 12
        text_right = side_rects["qty"].left() - listing_manager_window.LISTING_TEXT_CLUSTER_GAP

        self.assertTrue(side_rects["compact"])
        self.assertFalse(side_rects["badges_hidden"])
        self.assertFalse(side_rects["cost_badge"].isNull())
        self.assertFalse(side_rects["product_badge"].isNull())
        self.assertGreaterEqual(text_right - text_left, 220)
        self.assertLess(side_rects["qty"].right(), side_rects["price"].left())
        self.assertLess(side_rects["price"].right(), side_rects["cost_badge"].left())
        self.assertLess(side_rects["cost_badge"].right(), side_rects["hook"].left())
        self.assertLessEqual(abs(side_rects["hook"].center().y() - rect.center().y()), 1)
