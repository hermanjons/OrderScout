from __future__ import annotations

import inspect
import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QPointF, QRect, Qt, QEvent
from PyQt6.QtTest import QTest
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication, QDialog, QStyleOptionViewItem

import Stock.views.views as stock_views
import Stock.views.tab as stock_tab_module
import Stock.views.stock_item_manager_dialog as stock_item_manager_dialog_module
import Stock.views.stock_tx_dialog as stock_tx_dialog_module
import Stock.views.warehouse_manager_dialog as warehouse_manager_dialog_module
from Core.views import RecordWorkspaceEditorActionBar


class TestStockViews(TestCase):
    STOCK_VIEW_FILES = (
        "stock_item_manager_dialog.py",
        "stock_tx_dialog.py",
        "warehouse_manager_dialog.py",
        "brand_manager_dialog.py",
        "company_manager_dialog.py",
        "upper_group_manager_dialog.py",
        "sub_group_manager_dialog.py",
    )

    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    @classmethod
    def _stock_view_source(cls) -> str:
        base = Path(stock_views.__file__).resolve().parent
        chunks: list[str] = []
        for name in cls.STOCK_VIEW_FILES:
            chunks.append((base / name).read_text(encoding="utf-8"))
        return "\n".join(chunks)

    @classmethod
    def _views_facade_source(cls) -> str:
        return Path(stock_views.__file__).resolve().read_text(encoding="utf-8")

    @classmethod
    def _view_file_source(cls, name: str) -> str:
        return (Path(stock_views.__file__).resolve().parent / name).read_text(encoding="utf-8")

    def _cleanup_dialog(self, dialog) -> None:
        dialog.close()
        dialog.deleteLater()
        self._app.processEvents()

    def _cleanup_widget(self, widget) -> None:
        widget.close()
        widget.deleteLater()
        self._app.processEvents()

    def test_same_display_cost_ignores_float_tail_when_ui_text_matches(self) -> None:
        self.assertTrue(stock_views._same_display_cost(23.602, 23.6020000001))

    def test_same_display_cost_detects_visible_difference(self) -> None:
        self.assertFalse(stock_views._same_display_cost(23.602, 23.603))

    def test_country_default_dial_code_comes_from_core_mapping(self) -> None:
        self.assertEqual(stock_views._country_default_dial_code("Turkiye"), "+90")
        self.assertEqual(stock_views._country_default_dial_code("Azerbaycan"), "+994")

    def test_tx_mode_tabs_define_locked_visual_state(self) -> None:
        self.assertIn('QPushButton#TxModeTab[locked="true"]', stock_views.MODERN_LIGHT_QSS)
        self.assertIn('QPushButton#TxModeTab[active="true"][tone="out"][locked="true"]', stock_views.MODERN_LIGHT_QSS)

    def test_tx_mode_tabs_stay_enabled_but_lock_in_attachment_update_mode(self) -> None:
        dialog = stock_views.StockTxDialog()
        self.addCleanup(self._cleanup_dialog, dialog)
        original_selected_tx = dialog.txs_list.selected_tx

        class DummyTx:
            direction = "OUT"

        dialog._left_mode = "edit"
        dialog.txs_list.selected_tx = lambda: DummyTx()
        dialog._is_editor_panel_open = lambda: True

        dialog._sync_tx_mode_switch_state()

        self.assertTrue(dialog.btn_tab_in.isEnabled())
        self.assertTrue(dialog.btn_tab_out.isEnabled())
        self.assertTrue(dialog.btn_tab_in.property("locked"))
        self.assertTrue(dialog.btn_tab_out.property("locked"))
        dialog.txs_list.selected_tx = original_selected_tx

    def test_tx_mode_active_out_tab_keeps_red_fill_inside_scaffold(self) -> None:
        dialog = stock_views.StockTxDialog()
        self.addCleanup(self._cleanup_dialog, dialog)

        class DummyTx:
            direction = "OUT"

        original_selected_tx = dialog.txs_list.selected_tx
        original_panel_open = dialog._is_editor_panel_open
        dialog._left_mode = "edit"
        dialog.txs_list.selected_tx = lambda: DummyTx()
        dialog._is_editor_panel_open = lambda: True
        dialog._set_tx_mode(dialog.MODE_OUT, emit_refresh=False)
        dialog._sync_tx_mode_switch_state()
        dialog.resize(1500, 900)
        dialog.show()
        self._app.processEvents()

        image = dialog.btn_tab_out.grab().toImage()
        sample = image.pixelColor(18, max(1, image.height() // 2))
        self.assertGreater(sample.red(), 180)
        self.assertGreater(sample.red(), sample.green())
        self.assertGreater(sample.red(), sample.blue())

        dialog.txs_list.selected_tx = original_selected_tx
        dialog._is_editor_panel_open = original_panel_open

    def test_stock_tx_dialog_uses_scaffold_scroll_for_editor(self) -> None:
        dialog = stock_views.StockTxDialog()
        self.addCleanup(self._cleanup_dialog, dialog)
        self.assertIs(dialog._tx_form_scroll, dialog._editor_scroll)

    def test_brand_manager_dialog_constructs_without_legacy_scroll_refs(self) -> None:
        with patch.object(stock_views.BrandManagerDialog, "refresh", autospec=True, return_value=None):
            dialog = stock_views.BrandManagerDialog()
        self.addCleanup(self._cleanup_dialog, dialog)
        self.assertIsNotNone(dialog._workspace)

    def test_company_manager_dialog_constructs_without_legacy_scroll_refs(self) -> None:
        with patch.object(stock_views.CompanyManagerDialog, "refresh", autospec=True, return_value=None):
            dialog = stock_views.CompanyManagerDialog()
        self.addCleanup(self._cleanup_dialog, dialog)
        self.assertIsNotNone(dialog._workspace)

    def test_brand_manager_dialog_uses_scaffold_action_bar(self) -> None:
        with patch.object(stock_views.BrandManagerDialog, "refresh", autospec=True, return_value=None):
            dialog = stock_views.BrandManagerDialog()
        self.addCleanup(self._cleanup_dialog, dialog)

        self.assertIsInstance(dialog._workspace.editor_action_bar, RecordWorkspaceEditorActionBar)
        self.assertIs(dialog.btn_save.parentWidget(), dialog._workspace.editor_action_bar)
        dialog._set_left_mode("new")
        self.assertEqual(dialog.btn_save.text(), "Marka Kaydet")
        self.assertTrue(dialog.btn_delete.isHidden())
        dialog._set_left_mode("edit")
        self.assertEqual(dialog.btn_save.text(), "Güncelle")
        self.assertFalse(dialog.btn_delete.isHidden())

    def test_company_manager_dialog_uses_scaffold_action_bar(self) -> None:
        with patch.object(stock_views.CompanyManagerDialog, "refresh", autospec=True, return_value=None):
            dialog = stock_views.CompanyManagerDialog()
        self.addCleanup(self._cleanup_dialog, dialog)

        self.assertIsInstance(dialog._workspace.editor_action_bar, RecordWorkspaceEditorActionBar)
        self.assertIs(dialog.btn_save.parentWidget(), dialog._workspace.editor_action_bar)
        dialog._set_left_mode("new")
        self.assertEqual(dialog.btn_save.text(), "Firma Kaydet")
        self.assertTrue(dialog.btn_delete.isHidden())
        dialog._set_left_mode("edit")
        self.assertEqual(dialog.btn_save.text(), "Güncelle")
        self.assertFalse(dialog.btn_delete.isHidden())

    def test_stock_item_manager_dialog_requests_white_editor_canvas_and_surface(self) -> None:
        with patch.object(stock_views.StockItemManagerDialog, "refresh_table", autospec=True, return_value=None):
            dialog = stock_views.StockItemManagerDialog()
        self.addCleanup(self._cleanup_dialog, dialog)
        self.assertIn("#FFFFFF", dialog._workspace.editor_host.styleSheet())
        self.assertIn("#FFFFFF", dialog._workspace.editor_scroll.styleSheet())
        self.assertIn("#FFFFFF", dialog._workspace.editor_surface.styleSheet())

    def test_stock_item_manager_dialog_uses_scaffold_action_bar(self) -> None:
        with patch.object(stock_views.StockItemManagerDialog, "refresh_table", autospec=True, return_value=None):
            dialog = stock_views.StockItemManagerDialog()
        self.addCleanup(self._cleanup_dialog, dialog)

        self.assertIsInstance(dialog._workspace.editor_action_bar, RecordWorkspaceEditorActionBar)
        self.assertIs(dialog.btn_save.parentWidget(), dialog._workspace.editor_action_bar)
        dialog._set_left_mode("new")
        self.assertEqual(dialog.btn_save.text(), "Stok Kartı Kaydet")
        self.assertTrue(dialog.btn_delete.isHidden())
        dialog._set_left_mode("edit")
        self.assertEqual(dialog.btn_save.text(), "Güncelle")
        self.assertFalse(dialog.btn_delete.isHidden())

    def test_warehouse_manager_dialog_uses_scaffold_action_bar(self) -> None:
        dialog = stock_views.WarehouseManagerDialog()
        self.addCleanup(self._cleanup_dialog, dialog)

        self.assertIsInstance(dialog._workspace.editor_action_bar, RecordWorkspaceEditorActionBar)
        self.assertIs(dialog.btn_save.parentWidget(), dialog._workspace.editor_action_bar)
        dialog._set_left_mode("new")
        self.assertEqual(dialog.btn_save.text(), "Depo Kaydet")
        self.assertTrue(dialog.btn_delete.isHidden())
        dialog._set_left_mode("edit")
        self.assertEqual(dialog.btn_save.text(), "Güncelle")
        self.assertFalse(dialog.btn_delete.isHidden())

    def test_upper_group_manager_dialog_uses_scaffold_action_bar(self) -> None:
        with patch.object(stock_views.UpperGroupManagerDialog, "refresh", autospec=True, return_value=None):
            dialog = stock_views.UpperGroupManagerDialog()
        self.addCleanup(self._cleanup_dialog, dialog)

        self.assertIsInstance(dialog._workspace.editor_action_bar, RecordWorkspaceEditorActionBar)
        self.assertIs(dialog.btn_save.parentWidget(), dialog._workspace.editor_action_bar)
        self.assertEqual(type(dialog.records_list).__name__, "ManagerCardsListWidget")

    def test_sub_group_manager_dialog_uses_scaffold_action_bar(self) -> None:
        with patch.object(stock_views.SubGroupManagerDialog, "refresh", autospec=True, return_value=None):
            dialog = stock_views.SubGroupManagerDialog()
        self.addCleanup(self._cleanup_dialog, dialog)

        self.assertIsInstance(dialog._workspace.editor_action_bar, RecordWorkspaceEditorActionBar)
        self.assertIs(dialog.btn_save.parentWidget(), dialog._workspace.editor_action_bar)
        self.assertEqual(type(dialog.records_list).__name__, "ManagerCardsListWidget")

    def test_group_manager_dialogs_expose_scaffold_filters_and_footer(self) -> None:
        with patch.object(stock_views.UpperGroupManagerDialog, "refresh", autospec=True, return_value=None):
            upper_dialog = stock_views.UpperGroupManagerDialog()
        self.addCleanup(self._cleanup_dialog, upper_dialog)

        with patch.object(stock_views.SubGroupManagerDialog, "refresh", autospec=True, return_value=None):
            sub_dialog = stock_views.SubGroupManagerDialog()
        self.addCleanup(self._cleanup_dialog, sub_dialog)

        self.assertFalse(upper_dialog._workspace.filters_card.isHidden())
        self.assertFalse(upper_dialog._workspace.footer_bar.isHidden())
        self.assertFalse(sub_dialog._workspace.filters_card.isHidden())
        self.assertFalse(sub_dialog._workspace.footer_bar.isHidden())

    def test_group_manager_dialogs_keep_core_footer_chrome(self) -> None:
        with patch.object(stock_views.UpperGroupManagerDialog, "refresh", autospec=True, return_value=None):
            dialog = stock_views.UpperGroupManagerDialog()
        self.addCleanup(self._cleanup_dialog, dialog)

        self.assertIn("QPushButton#PageButton", dialog._workspace.styleSheet())
        self.assertEqual(dialog._workspace.footer_bar.page_size_combo.objectName(), "Combo")
        self.assertEqual(dialog._workspace.footer_bar.page_size_combo.styleSheet(), "")

    def test_manager_cards_widget_can_bulk_select_negative_default_ids(self) -> None:
        widget = stock_views.ManagerCardsListWidget()
        self.addCleanup(self._cleanup_widget, widget)
        widget.set_items(
            [
                {
                    "pk": -11,
                    "title": "Varsayılan Kayıt",
                    "subtitle": "Demo",
                    "extra": "Default",
                    "badge": "Üst Grup",
                }
            ]
        )
        record = widget.model().index(0, 0).data(stock_views.ManagerCardsListModel.RecordRole)
        widget.set_record_selected(record, True)
        self.assertEqual(widget.bulk_selected_count(), 1)

    def test_stock_tx_dialog_reuses_cached_backend_query_for_local_filters(self) -> None:
        tx_row = SimpleNamespace(
            pk=101,
            item_id=1,
            warehouse_id=1,
            direction="IN_",
            reason="manual_in",
            qty=1,
            occurred_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
            unit_cost=25.0,
            currency="TRY",
            counterparty="Demo Tedarikci",
            note="demo hareket",
            attachments=None,
            order_ref=None,
            listing_id=None,
            map_qty=None,
        )
        query_result = SimpleNamespace(success=True, message="ok", data={"records": [tx_row]})

        with patch.object(stock_views.StockTxDialog, "refresh_all", autospec=True, return_value=None):
            dialog = stock_views.StockTxDialog()
        self.addCleanup(self._cleanup_dialog, dialog)

        dialog._item_name_by_id = {1: "Demo Urun"}
        dialog._item_unit_by_id = {1: "adet"}
        dialog._warehouse_name_by_id = {1: "Ana Depo"}

        with patch.object(stock_tx_dialog_module, "action_list_txs_filtered", return_value=query_result) as filtered_mock:
            dialog.refresh_txs_list()
            self.assertEqual(filtered_mock.call_count, 1)

            dialog.le_tx_search.setText("demo")
            dialog.refresh_txs_list()
            self.assertEqual(filtered_mock.call_count, 1)

    def test_manager_cards_widget_supports_scaffold_footer_contract(self) -> None:
        widget = stock_views.ManagerCardsListWidget()
        self.addCleanup(self._cleanup_widget, widget)
        widget.set_pagination_enabled(True)
        widget.set_items(
            [
                {"pk": idx + 1, "title": f"Kayıt {idx + 1}", "subtitle": "Demo", "extra": "Kaynak", "badge": "Alt Grup"}
                for idx in range(25)
            ]
        )

        self.assertEqual(widget.total_record_count(), 25)
        self.assertEqual(widget.shown_count(), 20)
        self.assertEqual(widget.get_total_pages(), 2)
        widget.select_all_filtered_records()
        self.assertEqual(len(widget.get_selected_records()), 25)
        widget.go_to_page(2)
        self.assertEqual(widget.shown_count(), 5)
        widget.clear_selected_records()
        self.assertEqual(len(widget.get_selected_records()), 0)

    def test_group_manager_bulk_mode_hides_editor_action_bar(self) -> None:
        with patch.object(stock_views.UpperGroupManagerDialog, "refresh", autospec=True, return_value=None):
            upper_dialog = stock_views.UpperGroupManagerDialog()
        with patch.object(stock_views.BrandManagerDialog, "refresh", autospec=True, return_value=None):
            brand_dialog = stock_views.BrandManagerDialog()
        with patch.object(stock_views.CompanyManagerDialog, "refresh", autospec=True, return_value=None):
            company_dialog = stock_views.CompanyManagerDialog()
        for dialog in (upper_dialog, brand_dialog, company_dialog):
            self.addCleanup(self._cleanup_dialog, dialog)

            dialog._set_left_mode("bulk")
            self.assertTrue(dialog._editor_actions_wrap.isHidden())
            self.assertFalse(dialog.bulk_panel.isHidden())
            dialog._set_left_mode("edit")
            self.assertFalse(dialog._editor_actions_wrap.isHidden())
            self.assertTrue(dialog.bulk_panel.isHidden())

    def test_stock_tx_dialog_uses_scaffold_action_bar(self) -> None:
        dialog = stock_views.StockTxDialog()
        self.addCleanup(self._cleanup_dialog, dialog)

        self.assertIsInstance(dialog._workspace.editor_action_bar, RecordWorkspaceEditorActionBar)
        self.assertIs(dialog.btn_submit_tx.parentWidget(), dialog._workspace.editor_action_bar)
        self.assertTrue(dialog._workspace.editor_action_bar.delete_button.isHidden())
        dialog._set_left_mode("new")
        dialog._set_tx_mode(dialog.MODE_IN, emit_refresh=False)
        self.assertEqual(dialog.btn_clear_form.text(), "Formu Temizle")
        self.assertEqual(dialog.btn_submit_tx.text(), "Stok Giriş Kaydet")
        dialog._set_tx_mode(dialog.MODE_OUT, emit_refresh=False)
        self.assertEqual(dialog.btn_submit_tx.text(), "Stok Çıkış Kaydet")

    def test_stock_tx_dialog_refresh_all_uses_pk_for_item_and_warehouse_selectors(self) -> None:
        item_row = SimpleNamespace(
            pk=11,
            id=None,
            sku="SKU-11",
            name="Demo Urun",
            unit="adet",
            image_path=None,
            allow_negative_stock=False,
            vat_rate=20.0,
        )
        warehouse_row = SimpleNamespace(pk=21, id=None, name="Ana Depo")
        empty_result = SimpleNamespace(success=True, data={"records": []})

        dialog = stock_views.StockTxDialog()
        self.addCleanup(self._cleanup_dialog, dialog)

        with (
            patch.object(stock_tx_dialog_module, "action_list_items", return_value=SimpleNamespace(success=True, data={"records": [item_row]})),
            patch.object(stock_tx_dialog_module, "action_list_warehouses", return_value=SimpleNamespace(success=True, data={"records": [warehouse_row]})),
            patch.object(stock_tx_dialog_module, "action_list_companies", return_value=empty_result),
            patch.object(stock_views.StockTxDialog, "refresh_balance_and_txs", autospec=True, return_value=None),
        ):
            dialog.refresh_all()

        self.assertEqual(dialog.cb_item.currentData(), 11)
        self.assertEqual(dialog.cb_wh.currentData(), 21)

    def test_stock_tx_list_model_matches_pk_only_rows_for_selection(self) -> None:
        tx_row = SimpleNamespace(pk=77, id=None)
        model = stock_tx_dialog_module.StockTxListModel([tx_row])
        self.assertTrue(model.set_selected_by_id(77))
        self.assertEqual(model.selected_tx_id(), 77)

    def test_manager_cards_widget_matches_pk_only_rows_for_selection(self) -> None:
        widget = stock_views.ManagerCardsListWidget()
        self.addCleanup(self._cleanup_widget, widget)
        widget.set_items([{"pk": 13, "name": "Ana Depo", "subtitle": "Demo", "extra": "Test"}])
        self.assertTrue(widget.set_selected_id(13))
        self.assertEqual(widget.selected_record_id(), 13)
        record = widget.selected_record()
        widget.set_record_selected(record, True)
        self.assertEqual(widget.bulk_selected_count(), 1)

    def test_stock_items_list_model_matches_pk_only_rows_for_selection(self) -> None:
        model = stock_item_manager_dialog_module.StockItemsListModel(
            [{"pk": 31, "name": "Demo Kart", "sku": "SKU-31", "barcode": None, "item_type": "physical", "unit": "adet"}]
        )
        self.assertTrue(model.set_selected_by_id(31))
        self.assertEqual(model.selected_item_id(), 31)

    def test_warehouse_manager_refresh_uses_pk_record_key(self) -> None:
        warehouse_row = SimpleNamespace(
            pk=21,
            id=None,
            name="Ana Depo",
            code="ADP",
            manager_name="Demo",
            phone=None,
            email=None,
            address=None,
            city="Ankara",
            country="Turkiye",
            capacity_m3=None,
            note=None,
        )
        with patch.object(warehouse_manager_dialog_module, "action_list_warehouses", return_value=SimpleNamespace(success=True, data={"records": [warehouse_row]})):
            dialog = stock_views.WarehouseManagerDialog()
            dialog.refresh()
        self.addCleanup(self._cleanup_dialog, dialog)
        self.assertEqual(dialog._records[0]["pk"], 21)
        self.assertTrue(dialog.records_list.set_selected_id(21))
        self.assertEqual(dialog.records_list.selected_record_id(), 21)

    def test_stock_tab_exposes_group_managers_in_quick_access(self) -> None:
        with patch.object(stock_views.StockTab, "_open_full_dialog", autospec=True) as open_dialog:
            tab = stock_views.StockTab()
            self.addCleanup(self._cleanup_widget, tab)

            self.assertEqual(tab.btn_upper_groups._text, "Üst Gruplar")
            self.assertEqual(tab.btn_sub_groups._text, "Alt Gruplar")
            tab.open_upper_groups()
            open_dialog.assert_called_once_with(
                tab,
                stock_views.__getattr__("UpperGroupManagerDialog"),
                "Üst Gruplar",
                quick_key="upper_groups",
                quick_icon_name="stock-upper-groups-icon.png",
            )

        with patch.object(stock_views.StockTab, "_open_full_dialog", autospec=True) as open_dialog:
            tab = stock_views.StockTab()
            self.addCleanup(self._cleanup_widget, tab)
            tab.open_sub_groups()
            open_dialog.assert_called_once_with(
                tab,
                stock_views.__getattr__("SubGroupManagerDialog"),
                "Alt Gruplar",
                quick_key="sub_groups",
                quick_icon_name="stock-sub-groups-icon.png",
            )

    def test_stock_tabs_retain_open_dialogs_until_closed(self) -> None:
        class DummyDialog(QDialog):
            def open_full(self):
                self.show()
                return self

        for tab_cls in (stock_views.StockTab, stock_tab_module.StockTab):
            tab = tab_cls()
            self.addCleanup(self._cleanup_widget, tab)

            tab._open_full_dialog(DummyDialog, "Demo")
            self.assertEqual(len(tab._open_dialogs), 1)
            dialog = tab._open_dialogs[0]
            dialog.done(0)
            self._app.processEvents()
            self.assertEqual(tab._open_dialogs, [])

    def test_stock_workspace_windows_request_white_editor_canvas_and_surface(self) -> None:
        source = self._stock_view_source()
        self.assertIn('editor_canvas_color="#FFFFFF"', source)
        self.assertIn('editor_surface_color="#FFFFFF"', source)

    def test_stock_item_manager_dialog_workspace_handlers_drop_legacy_fallbacks(self) -> None:
        methods = (
            stock_views.StockItemManagerDialog._sync_guidance_overlays_geometry,
            stock_views.StockItemManagerDialog._sync_focus_guidance_state,
            stock_views.StockItemManagerDialog._sync_sidebar_state_from_splitter,
            stock_views.StockItemManagerDialog._open_editor_panel,
            stock_views.StockItemManagerDialog._close_editor_panel,
        )
        combined = "\n".join(inspect.getsource(method) for method in methods)
        self.assertNotIn('hasattr(self, "_workspace_behavior")', combined)
        self.assertNotIn('hasattr(self, "_workspace_shell")', combined)

    def test_stock_windows_drop_manual_splitter_legacy(self) -> None:
        source = self._stock_view_source()
        self.assertNotIn("splitterMoved.connect", source)
        self.assertNotIn("_splitter_guard", source)
        self.assertNotIn("_splitter_settle_timer", source)
        self.assertNotIn("_settle_item_splitter", source)
        self.assertNotIn("_settle_tx_splitter", source)
        self.assertNotIn("_settle_manager_splitter", source)
        self.assertNotIn("_snap_splitter", source)

    def test_stock_windows_do_not_override_shell_fallback_total_width(self) -> None:
        source = self._stock_view_source()
        self.assertNotIn("fallback_total_width", source)

    def test_stock_windows_drop_local_guidance_overlay_legacy(self) -> None:
        source = self._stock_view_source()
        self.assertNotIn("AnimatedGuidanceRing", source)
        self.assertNotIn("EditLockOverlay", source)
        self.assertNotIn("_edit_block_overlay", source)
        self.assertNotIn("_records_focus_ring", source)
        self.assertNotIn("_tx_edit_block_overlay", source)
        self.assertNotIn("_tx_records_focus_ring", source)

    def test_stock_windows_drop_dead_manual_workspace_handlers(self) -> None:
        source = self._stock_view_source()
        self.assertNotIn("def _on_panel_sidebar_toggled", source)
        self.assertNotIn("def _on_records_background_clicked", source)
        self.assertNotIn("def _on_record_card_clicked", source)
        self.assertNotIn("def _on_record_select_button_clicked", source)
        self.assertNotIn("def _on_items_background_clicked", source)
        self.assertNotIn("def _on_item_card_clicked", source)
        self.assertNotIn("def _on_item_select_button_clicked", source)
        self.assertNotIn("def _on_txs_background_clicked", source)
        self.assertNotIn("def _on_tx_card_clicked", source)
        self.assertNotIn("def _on_tx_select_button_clicked", source)

    def test_stock_views_py_only_keeps_tab_and_facade_role(self) -> None:
        source = self._views_facade_source()
        self.assertNotIn("class StockItemsListModel", source)
        self.assertNotIn("class StockTxListModel", source)
        self.assertNotIn("class ManagerCardsListModel", source)
        self.assertNotIn("class StockItemsWorkspaceBehaviorAdapter", source)
        self.assertNotIn("class StockManagerWorkspaceBehaviorAdapter", source)
        self.assertNotIn("class SubGroupWorkspaceBehaviorAdapter", source)
        self.assertNotIn("class StockTxWorkspaceBehaviorAdapter", source)

    def test_stock_views_sources_do_not_keep_mojibake_or_ascii_ui_fallback_text(self) -> None:
        source = self._views_facade_source() + "\n" + self._stock_view_source()
        self.assertNotIn(chr(0x00C4) + chr(0x0178), source)
        self.assertNotIn(chr(0x00C5) + chr(0x0178), source)
        self.assertNotIn("🔄 Yenile", source)
        self.assertNotIn("📊 Anlık Durum", source)
        self.assertNotIn("Duzenlemek icin sagdaki listeden", source)
        self.assertNotIn("Toplu islem icin sagdaki listeden", source)
        self.assertNotIn("Bu degerle devam etmek istiyor musun?", source)
        self.assertNotIn("Olu?acak hareket", source)

    def test_stock_manager_cards_use_core_select_hook_chrome(self) -> None:
        source = self._view_file_source("company_manager_dialog.py")
        self.assertIn("class ManagerCardsListDelegate(RecordWorkspaceListDelegate):", source)
        self.assertNotIn('painter.drawText(hook_rect, Qt.AlignmentFlag.AlignCenter, "SEÇ")', source)
        self.assertNotIn("def editorEvent(self, event, model, option, index):", source)

    def test_stock_tx_cards_use_core_select_hook_chrome(self) -> None:
        source = self._view_file_source("stock_tx_dialog.py")
        self.assertIn("class StockTxListDelegate(RecordWorkspaceListDelegate):", source)
        self.assertIn("self._paint_hook_button(", source)
        self.assertIn("self._handle_hook_activated(model, index, next_selected)", source)
        self.assertNotIn("self._hover_select_row", source)
        self.assertNotIn("self._pressed_select_row", source)

    def test_stock_item_select_rect_stays_centered_with_core_hook_helper(self) -> None:
        delegate = stock_views.StockItemsListDelegate()
        rect = QRect(0, 0, 920, 96)
        select_rect, _ = delegate._button_rects(rect, has_source=True)
        self.assertLessEqual(abs(select_rect.center().y() - rect.center().y()), 1)

    def test_stock_tx_select_rect_stays_centered_with_core_hook_helper(self) -> None:
        delegate = stock_views.StockTxListDelegate()
        rect = QRect(0, 0, 1080, 96)
        select_rect, _, _, _ = delegate._button_rects(
            rect,
            direction_code="OUT",
            has_order_button=True,
            has_listing_button=True,
        )
        self.assertLessEqual(abs(select_rect.center().y() - rect.center().y()), 1)

    def test_stock_item_select_button_hover_uses_core_hook_animation_state(self) -> None:
        widget = stock_views.StockItemsListWidget()
        self.addCleanup(self._cleanup_widget, widget)
        widget.resize(1400, 520)
        widget.set_items(
            [
                {
                    "id": 1,
                    "name": "Demo Kart",
                    "sku": "demo-sku",
                    "barcode": "123",
                    "item_type": "PHYSICAL",
                    "unit": "adet",
                    "brand": "Demo",
                    "category": "Kategori",
                    "sub_category": "Alt",
                    "on_hand": 3,
                    "is_active": True,
                    "image_path": "",
                }
            ]
        )
        widget.show()
        self._app.processEvents()
        index = widget.model().index(0, 0)
        rect = widget.visualRect(index).adjusted(6, 4, -6, -4)
        delegate = widget.itemDelegate()
        select_rect, _ = delegate._button_rects(rect, has_source=True, view=widget)
        center = QPointF(select_rect.center())
        option = QStyleOptionViewItem()
        option.rect = widget.visualRect(index)
        option.widget = widget
        event = QMouseEvent(
            QEvent.Type.MouseMove,
            center,
            center,
            center,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        delegate.editorEvent(event, widget.model(), option, index)
        self.assertEqual(delegate._hover_row, 0)

    def test_stock_items_widget_paginates_large_records(self) -> None:
        widget = stock_views.StockItemsListWidget()
        self.addCleanup(self._cleanup_widget, widget)
        records = [
            {
                "id": idx + 1,
                "name": f"Stok {idx + 1}",
                "sku": f"SKU-{idx + 1}",
                "barcode": str(idx + 1),
                "item_type": "PHYSICAL",
                "unit": "adet",
                "brand": "Demo",
                "category": "Kategori",
                "sub_category": "Alt",
                "on_hand": idx,
                "avg_unit_cost": 10,
                "is_active": True,
                "image_path": "",
            }
            for idx in range(45)
        ]

        widget.set_items(records)

        self.assertEqual(widget.total_record_count(), 45)
        self.assertEqual(widget.shown_count(), 20)
        self.assertEqual(widget.get_total_pages(), 3)
        self.assertLessEqual(len(widget._inline_stock_controls), 20)

        widget.select_all_filtered_records()
        self.assertEqual(widget.bulk_selected_count(), 45)
        widget.go_to_page(3)
        self.assertEqual(widget.shown_count(), 5)
        self.assertEqual(widget.bulk_selected_count(), 45)

    def test_stock_tx_select_button_click_toggles_bulk_selection(self) -> None:
        widget = stock_views.StockTxListWidget()
        self.addCleanup(self._cleanup_widget, widget)
        widget.resize(1500, 520)
        widget.set_items(
            [
                {
                    "id": 11,
                    "direction": "OUT",
                    "item_id": 5,
                    "qty": 2,
                    "reason": "ORDER",
                    "warehouse_id": 1,
                    "unit_price": 23,
                }
            ],
            item_name_by_id={5: "Demo Ürün"},
            item_unit_by_id={5: "adet"},
            warehouse_name_by_id={1: "Demo Depo"},
        )
        widget.show()
        self._app.processEvents()
        index = widget.model().index(0, 0)
        rect = widget.visualRect(index).adjusted(6, 4, -6, -4)
        select_rect, _, _, _ = widget.itemDelegate()._button_rects(
            rect,
            direction_code="OUT",
            has_order_button=False,
            has_listing_button=False,
            view=widget,
        )
        center = QPoint(select_rect.center().x(), select_rect.center().y())
        self.assertEqual(widget.bulk_selected_count(), 0)
        QTest.mouseMove(widget.viewport(), center)
        QTest.mouseClick(widget.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
        self._app.processEvents()
        self.assertEqual(widget.bulk_selected_count(), 1)

    def test_stock_tx_widget_paginates_large_records(self) -> None:
        widget = stock_views.StockTxListWidget()
        self.addCleanup(self._cleanup_widget, widget)
        records = [
            {
                "id": idx + 1,
                "direction": "OUT",
                "item_id": 5,
                "qty": idx + 1,
                "reason": "ORDER",
                "warehouse_id": 1,
                "unit_price": 12,
            }
            for idx in range(45)
        ]

        widget.set_items(
            records,
            item_name_by_id={5: "Demo Ürün"},
            item_unit_by_id={5: "adet"},
            warehouse_name_by_id={1: "Demo Depo"},
        )

        self.assertEqual(widget.total_record_count(), 45)
        self.assertEqual(widget.shown_count(), 20)
        self.assertEqual(widget.get_total_pages(), 3)
        widget.select_all_filtered_records()
        self.assertEqual(widget.bulk_selected_count(), 45)
        widget.go_to_page(3)
        self.assertEqual(widget.shown_count(), 5)
        self.assertEqual(widget.bulk_selected_count(), 45)

    def test_stock_tx_workspace_adapter_applies_external_selection(self) -> None:
        widget = stock_views.StockTxListWidget()
        self.addCleanup(self._cleanup_widget, widget)
        tx = type("DummyTx", (), {"id": 77})()
        widget.set_items(
            [{"id": 77, "direction": "OUT", "item_id": 5, "qty": 1, "reason": "ORDER", "warehouse_id": 1, "unit_price": 12}],
            item_name_by_id={5: "Demo Ürün"},
            item_unit_by_id={5: "adet"},
            warehouse_name_by_id={1: "Demo Depo"},
        )
        dialog = type("DummyDialog", (), {"txs_list": widget, "_left_mode": "edit", "_set_left_mode": lambda self, mode: None, "_clear_tx_workspace_state": lambda self: None, "_prepare_new_tx_workspace": lambda self: None, "_sync_tx_workspace_state": lambda self: None})()
        adapter = stock_views.StockTxWorkspaceBehaviorAdapter(dialog)
        adapter.apply_selection(tx, True)
        self.assertEqual(widget.bulk_selected_count(), 1)

    def test_stock_item_inline_controls_do_not_cover_select_button(self) -> None:
        widget = stock_views.StockItemsListWidget()
        self.addCleanup(self._cleanup_widget, widget)
        widget.resize(1600, 520)
        widget.set_items(
            [
                {
                    "id": 1,
                    "name": "Demo Kart",
                    "sku": "demo-sku",
                    "barcode": "123",
                    "item_type": "PHYSICAL",
                    "unit": "adet",
                    "brand": "Demo",
                    "category": "Kategori",
                    "sub_category": "Alt",
                    "on_hand": 3,
                    "avg_unit_cost": 23,
                    "avg_cost_currency": "TRY",
                    "is_active": True,
                    "image_path": "",
                }
            ]
        )
        widget.show()
        self._app.processEvents()
        index = widget.model().index(0, 0)
        row_rect = widget.visualRect(index).adjusted(6, 4, -6, -4)
        select_rect, _ = widget.itemDelegate()._button_rects(row_rect, has_source=True, view=widget)
        inline_ctrl = widget._inline_stock_controls[0]
        self.assertFalse(inline_ctrl.geometry().intersects(select_rect))

    def test_stock_item_inline_metric_labels_have_headroom(self) -> None:
        inline = stock_item_manager_dialog_module.InlineStockAdjustControls()
        self.addCleanup(self._cleanup_widget, inline)
        self.assertGreaterEqual(inline.avg_price.label.height(), 16)
        self.assertGreaterEqual(inline.stock.label.height(), 16)
        self.assertGreaterEqual(inline.minimumHeight(), 60)

    def test_stock_item_inline_metric_geometry_stays_inside_parent(self) -> None:
        inline = stock_item_manager_dialog_module.InlineStockAdjustControls()
        self.addCleanup(self._cleanup_widget, inline)
        inline.setGeometry(0, 0, 472, 60)
        stock_rect = QRect(254, 0, 128, 56)
        avg_rect = QRect(104, 0, 140, 56)
        inline.place_controls(stock_rect, avg_rect)
        self.assertGreaterEqual(inline.stock.geometry().top(), 0)
        self.assertGreaterEqual(inline.avg_price.geometry().top(), 0)
        self.assertTrue(inline.rect().contains(inline.stock.geometry()))
        self.assertTrue(inline.rect().contains(inline.avg_price.geometry()))
