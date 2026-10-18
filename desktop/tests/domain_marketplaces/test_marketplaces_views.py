from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QApplication, QWidget
from sqlmodel import SQLModel

import Core.views as core_views
from Core.utils.model_utils import get_engine
from Marketplaces.signals.signals import marketplace_signals
import Marketplaces.views.actions as marketplaces_actions
import Marketplaces.views.marketplaces_manager_window as marketplaces_manager_window
import Marketplaces.views.views as marketplaces_views


class _FakeHookIndex:
    def __init__(self, payload: dict | None = None) -> None:
        self._record = SimpleNamespace(payload=dict(payload or {}))

    def data(self, role):
        if role == core_views.RecordWorkspaceListModel.RecordRole:
            return self._record
        return None


class _FakeMarketplacesWindow(QWidget):
    itemsChanged = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()


class TestMarketplacesViews(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    @classmethod
    def _views_source(cls) -> str:
        return Path(marketplaces_views.__file__).resolve().read_text(encoding="utf-8")

    @classmethod
    def _manager_source(cls) -> str:
        return Path(marketplaces_manager_window.__file__).resolve().read_text(encoding="utf-8")

    @classmethod
    def _actions_source(cls) -> str:
        return Path(marketplaces_actions.__file__).resolve().read_text(encoding="utf-8")

    def _drain_events(self, cycles: int = 8) -> None:
        for _ in range(max(1, cycles)):
            self._app.processEvents()

    def test_views_py_keeps_tab_role(self) -> None:
        source = self._views_source()
        self.assertIn("class MarketplacesTab(QWidget):", source)
        self.assertNotIn("class MarketplacesWindow(QWidget):", source)

    def test_marketplaces_sources_do_not_contain_mojibake(self) -> None:
        combined = self._views_source() + "\n" + self._manager_source() + "\n" + self._actions_source()
        for token in ("\u00C3", "\u00C4", "\u00C5", "\uFFFD"):
            self.assertNotIn(token, combined)

    def test_marketplaces_manager_window_uses_scaffold_without_legacy_shell(self) -> None:
        source = self._manager_source()
        self.assertIn("RecordWorkspaceScaffold(", source)
        self.assertIn("SwitchButton(", source)
        self.assertIn("SwitchSelectWidget(", source)
        self.assertIn("_build_status_row(", source)
        self.assertNotIn("_build_capability_row(", source)
        self.assertNotIn('form.addRow("Kaynak"', source)
        self.assertNotIn("RecordWorkspaceSplitShell(", source)
        self.assertNotIn("fallback_total_width", source)
        self.assertNotIn("_open_left_panel(", source)
        self.assertNotIn("_close_left_panel(", source)
        self.assertNotIn("def open_panel(", source)
        self.assertNotIn("def close_panel(", source)
        self.assertNotIn("_workspace_shell.open_left_panel(", source)
        self.assertNotIn("_workspace_shell.close_left_panel(", source)
        self.assertNotIn("_on_panel_sidebar_toggled(", source)
        self.assertNotIn("_on_splitter_moved(", source)
        self.assertNotIn("QStackedWidget", source)

    def test_marketplaces_window_requests_white_editor_surface(self) -> None:
        window = marketplaces_manager_window.MarketplacesWindow()
        self.assertIn("#FFFFFF", window._workspace.editor_scroll.styleSheet())
        self.assertIn("#FFFFFF", window._workspace.editor_surface.styleSheet())
        self.assertIsInstance(window.list_widget.itemDelegate(), core_views.RecordWorkspaceListDelegate)
        self.assertIs(window.list_widget._delegate, window.list_widget.itemDelegate())
        self.assertGreater(window._workspace.filters_layout.count(), 0)
        self.assertIsInstance(window._workspace.editor_action_bar, core_views.RecordWorkspaceEditorActionBar)
        self.assertIs(window.btn_save.parentWidget(), window._workspace.editor_action_bar)
        self.assertEqual(window.btn_clear_edit.text(), "Temizle")
        self.assertTrue(window._workspace.editor_action_bar.delete_button.isHidden())
        self.assertEqual(window.btn_save.text(), "Güncelle")
        self.assertIsInstance(window.filter_status_combo, core_views.SwitchSelectWidget)
        self.assertIsInstance(window.filter_source_combo, core_views.SwitchSelectWidget)

        self.assertIsInstance(window.status_switch, core_views.SwitchButton)

    def test_marketplaces_button_opens_top_level_window(self) -> None:
        tab = marketplaces_views.MarketplacesTab()
        tab.open_marketplaces_window()
        self.assertIsNotNone(tab.marketplaces_window)
        self.assertIsNone(tab.marketplaces_window.parentWidget())

    def test_bulk_mode_enables_select_button_guidance(self) -> None:
        with patch.object(marketplaces_manager_window.MarketplacesWindow, "request_reload_items"):
            window = marketplaces_manager_window.MarketplacesWindow()
            window.show()
            self._app.processEvents()
        window.reload_items()
        window._workspace_behavior.handle_panel_sidebar_toggled("bulk", True)
        self._app.processEvents()
        self.assertEqual(window._left_mode, "bulk")
        self.assertTrue(window._workspace_shell.is_left_panel_open())
        self.assertFalse(window._editor_scroll.isVisible())
        self.assertFalse(window._editor_actions_host.isVisible())
        self.assertTrue(window.bulk_panel.isVisible())
        self.assertTrue(window.list_widget._guide_select_animation_enabled)
        self.assertTrue(window.list_widget._active_border_timer.isActive())

    def test_edit_mode_enables_active_card_animation(self) -> None:
        window = marketplaces_manager_window.MarketplacesWindow()
        window.show()
        self._drain_events()
        window.reload_items()
        self._drain_events()
        record = window.list_widget.filtered_records[0]
        window._workspace_behavior.handle_record_clicked(record)
        self._drain_events()
        self.assertEqual(window._left_mode, "edit")
        self.assertTrue(window._workspace_shell.is_left_panel_open())
        self.assertTrue(window._editor_scroll.isVisible())
        self.assertTrue(window._editor_actions_host.isVisible())
        self.assertFalse(window.bulk_panel.isVisible())
        self.assertTrue(window.list_widget._active_spin_allowed)
        self.assertTrue(window.list_widget._active_border_timer.isActive())

    def test_reload_preserves_active_record_and_bulk_selection(self) -> None:
        fake_records = [
            {
                "code": "TRENDYOL",
                "label": "Trendyol",
                "description": "Varsayılan Trendyol pazaryeri entegrasyonu.",
                "isActive": True,
                "isBuiltin": True,
                "isBuiltinAccepted": True,
            },
            {
                "code": "HEPSIBURADA",
                "label": "Hepsiburada",
                "description": "İkinci test kaydı.",
                "isActive": True,
                "isBuiltin": False,
                "isBuiltinAccepted": True,
            },
        ]
        with patch.object(
            marketplaces_manager_window,
            "load_marketplaces",
            lambda *args, **kwargs: marketplaces_actions.Result.ok(data={"records": fake_records}, close_dialog=False),
        ):
            window = marketplaces_manager_window.MarketplacesWindow()
            window.show()
            self._drain_events()
            window.reload_items()
            self._drain_events()
            first = window.list_widget.filtered_records[0]
            second = window.list_widget.filtered_records[1]

            window._workspace_behavior.handle_record_clicked(first)
            window.list_widget.set_record_selected(second, True)
            window._workspace_behavior.handle_selection_changed()
            self._drain_events()

            self.assertEqual(window._left_mode, "bulk")
            self.assertTrue(window._workspace_shell.is_left_panel_open())

            active_code = str((getattr(first, "payload", None) or {}).get("code") or "").strip().upper()
            selected_code = str((getattr(second, "payload", None) or {}).get("code") or "").strip().upper()

            window.reload_items()
            self._drain_events()

            self.assertEqual(window._active_code, active_code)
            self.assertIn(selected_code, window.list_widget.selected_payload_codes())
            self.assertEqual(window._left_mode, "bulk")
            self.assertTrue(window._workspace_shell.is_left_panel_open())

    def test_accept_marketplace_from_window_updates_loaded_records(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_name = str(Path(tmpdir) / "marketplaces.sqlite3")
            engine = get_engine(db_name)
            SQLModel.metadata.create_all(engine)

            with patch.object(
                marketplaces_manager_window,
                "load_marketplaces",
                lambda *args, **kwargs: marketplaces_actions.load_marketplaces(db_name=db_name),
            ), patch.object(
                marketplaces_manager_window,
                "accept_marketplace_record",
                lambda *args, **kwargs: marketplaces_actions.accept_marketplace_record(db_name=db_name, **kwargs),
            ), patch.object(
                marketplaces_manager_window.AppMessageCenter,
                "confirm",
                lambda *args, **kwargs: True,
            ), patch.object(
                marketplaces_manager_window.MessageHandler,
                "show",
                lambda *args, **kwargs: None,
            ):
                window = marketplaces_manager_window.MarketplacesWindow()
                self.addCleanup(window.close)
                self.addCleanup(window.deleteLater)
                window.reload_items()
                self._drain_events()

                window._accept_marketplace("TRENDYOL")
                self._drain_events()

                target = next(
                    row.payload
                    for row in (window.list_widget.filtered_records or [])
                    if str((row.payload or {}).get("code") or "").strip().upper() == "TRENDYOL"
                )
                self.assertTrue(bool(target.get("isBuiltinAccepted")))
                self.assertEqual(str(target.get("sourceCode") or ""), "accepted")

    def test_marketplaces_delegate_uses_scaffold_default_select_text_after_acceptance(self) -> None:
        delegate = marketplaces_manager_window.MarketplacesListDelegate()
        base_delegate = core_views.RecordWorkspaceListDelegate()

        pending_index = _FakeHookIndex({"isBuiltin": True, "isBuiltinAccepted": False})
        accepted_index = _FakeHookIndex({"isBuiltin": True, "isBuiltinAccepted": True})

        self.assertEqual(
            delegate._hook_text(pending_index),
            marketplaces_manager_window.MARKETPLACE_ACCEPT_BUTTON_TEXT,
        )
        self.assertEqual(
            delegate._hook_text(accepted_index),
            base_delegate._hook_text(accepted_index),
        )

    def test_marketplaces_tab_badge_tracks_changes_and_clears_on_open(self) -> None:
        tab = marketplaces_views.MarketplacesTab()
        self.addCleanup(tab.close)
        self.addCleanup(tab.deleteLater)

        pending_two = marketplaces_actions.Result.ok(data={"records": [{}, {}]}, close_dialog=False)
        pending_three = marketplaces_actions.Result.ok(data={"records": [{}, {}, {}]}, close_dialog=False)
        pending_five = marketplaces_actions.Result.ok(data={"records": [{}, {}, {}, {}, {}]}, close_dialog=False)

        with patch.object(marketplaces_views, "load_marketplaces", side_effect=[pending_two, pending_three, pending_five]):
            tab._refresh_summary()
            self.assertEqual(tab.btn_marketplaces._badge_count, 2)

            tab.marketplaces_window = _FakeMarketplacesWindow()
            tab.open_marketplaces_window()
            self.assertEqual(tab.btn_marketplaces._badge_count, 0)

            tab.marketplaces_window.hide()
            marketplace_signals.marketplaces_changed.emit()
            self._drain_events()
            self.assertEqual(tab.btn_marketplaces._badge_count, 2)

        self.assertTrue(tab.btn_marketplaces._active)
