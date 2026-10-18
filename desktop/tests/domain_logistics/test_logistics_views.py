from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

import Core.views as core_views
from Logistics.signals.signals import logistics_signals
import Logistics.views.cargo_providers_window as providers_window
import Logistics.views.cargo_tariffs_window as tariffs_window
import Logistics.views.views as logistics_views


class _FakeHookIndex:
    def __init__(self, payload: dict | None = None) -> None:
        self._record = SimpleNamespace(payload=dict(payload or {}))

    def data(self, role):
        if role == core_views.RecordWorkspaceListModel.RecordRole:
            return self._record
        return None


class _FakeLogisticsWindow(QWidget):
    itemsChanged = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.reload_count = 0

    def reload_items(self) -> None:
        self.reload_count += 1

    def request_reload_items(self) -> None:
        self.reload_count += 1


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


class TestLogisticsViews(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    @classmethod
    def _source(cls, module) -> str:
        return Path(module.__file__).resolve().read_text(encoding="utf-8")

    def test_logistics_views_module_is_thin_orchestrator(self) -> None:
        source = self._source(logistics_views)
        self.assertIn("from Logistics.views.cargo_providers_window import LogisticsCargoProvidersFormWindow", source)
        self.assertIn("from Logistics.views.cargo_tariffs_window import LogisticsCargoTariffsWindow", source)
        self.assertNotIn("RecordWorkspaceSplitShell(", source)

    def test_logistics_cargo_providers_window_uses_scaffold_without_legacy_shell(self) -> None:
        source = self._source(providers_window)
        self.assertIn("RecordWorkspaceScaffold(", source)
        self.assertNotIn("RecordWorkspaceSplitShell(", source)
        self.assertNotIn("RecordWorkspaceBehaviorController(", source)

        window = providers_window.LogisticsCargoProvidersFormWindow()
        self.assertIsInstance(window._workspace, core_views.RecordWorkspaceScaffold)
        self.assertIs(window.left_panel_title, window._workspace.left_card.title_label)
        self.assertIs(window.left_panel_hint, window._workspace.left_card.subtitle_label)
        self.assertIs(window.bulk_panel, window._workspace.bulk_panel)
        self.assertIsInstance(window._workspace.editor_action_bar, core_views.RecordWorkspaceEditorActionBar)
        self.assertIs(window.btn_save_provider.parentWidget(), window._workspace.editor_action_bar)
        window._set_left_mode("new")
        self.assertEqual(window.btn_save_provider.text(), "Kargo Firmasını Kaydet")
        self.assertTrue(window.btn_delete_provider.isHidden())
        window._editing_record = {"canDelete": True}
        window._set_left_mode("edit")
        self.assertEqual(window.btn_save_provider.text(), "Güncelle")
        self.assertFalse(window.btn_delete_provider.isHidden())
        window._load_form(
            {
                "key": "ptt",
                "cargoProviderName": "PTT Kargo",
                "platformCode": "AMAZON",
                "cargoProviderCode": "PTT",
                "canDelete": False,
            },
            open_panel=False,
        )
        self.assertTrue(window.btn_delete_provider.isHidden())
        window.close()
        window.deleteLater()
        self._app.processEvents()

    def test_logistics_cargo_tariffs_window_is_local_scaffold_window(self) -> None:
        window = tariffs_window.LogisticsCargoTariffsWindow()
        self.assertIsInstance(window._workspace, core_views.RecordWorkspaceScaffold)
        self.assertEqual(window.windowTitle(), "Kargo Tarifeleri")
        self.assertIsInstance(window._workspace.editor_action_bar, core_views.RecordWorkspaceEditorActionBar)
        self.assertIs(window.btn_save_tariff.parentWidget(), window._workspace.editor_action_bar)
        self.assertEqual(window.btn_save_tariff.minimumWidth(), 0)
        window.close()
        window.deleteLater()
        self._app.processEvents()

    def test_logistics_cargo_provider_delegate_uses_scaffold_default_select_text_after_acceptance(self) -> None:
        delegate = providers_window.LogisticsCargoProvidersListDelegate()
        base_delegate = providers_window.OrdersStyleListDelegate()

        pending_index = _FakeHookIndex({"isBuiltin": True, "isBuiltinAccepted": False})
        accepted_index = _FakeHookIndex({"isBuiltin": True, "isBuiltinAccepted": True})

        self.assertEqual(
            delegate._hook_text(pending_index),
            providers_window.LOGISTICS_CARGO_PROVIDER_ACCEPT_BUTTON_TEXT,
        )
        self.assertEqual(
            delegate._hook_text(accepted_index),
            base_delegate._hook_text(accepted_index),
        )

    def test_logistics_cargo_tariffs_active_spin_turns_off_in_bulk_mode(self) -> None:
        window = tariffs_window.LogisticsCargoTariffsWindow()
        window.show()
        self._app.processEvents()

        record = {
            "pk": 10,
            "name": "Trendyol Kargo",
            "description": "Test",
            "platform": "TRENDYOL",
            "providerText": "Yurtiçi",
            "desiRangeText": "0-1",
            "salePriceRangeText": "0-100",
            "amountText": "10",
            "currency": "TRY",
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

    def test_logistics_cargo_tariffs_clicking_second_card_keeps_panel_open_and_switches_active(self) -> None:
        with patch.object(tariffs_window.LogisticsCargoTariffsWindow, "request_reload_items"):
            window = tariffs_window.LogisticsCargoTariffsWindow()
            window.resize(1600, 900)
            window.show()
            self._app.processEvents()

        first = {
            "pk": 10,
            "name": "Trendyol Kargo",
            "description": "Test",
            "platform": "TRENDYOL",
            "providerText": "Yurtiçi",
            "desiRangeText": "0-1",
            "salePriceRangeText": "0-100",
            "amountText": "10",
            "currency": "TRY",
            "amountModeText": "KDV dahil",
            "isActive": True,
        }
        second = {
            "pk": 11,
            "name": "Hepsiburada Kargo",
            "description": "Test 2",
            "platform": "HEPSIBURADA",
            "providerText": "Aras",
            "desiRangeText": "1-2",
            "salePriceRangeText": "100-200",
            "amountText": "12",
            "currency": "TRY",
            "amountModeText": "KDV dahil",
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

    def test_logistics_tab_uses_local_window_classes(self) -> None:
        tab = logistics_views.LogisticsTab()
        self.assertIsNone(tab.cargo_providers_window)
        self.assertIsNone(tab.cargo_tariffs_window)
        tab.close()
        tab.deleteLater()
        self._app.processEvents()

    def test_logistics_tab_delays_summary_bootstrap_until_after_first_paint(self) -> None:
        calls: list[str] = []

        def fake_summary():
            calls.append("summary")
            return logistics_views.Result.ok(
                data={
                    "providers_result": logistics_views.Result.ok(data={"records": []}, close_dialog=False),
                    "tariffs_result": logistics_views.Result.ok(data={"records": []}, close_dialog=False),
                },
                close_dialog=False,
            )

        with patch.object(logistics_views, "SyncWorker", _ImmediateSyncWorker), patch.object(
            logistics_views,
            "_load_logistics_summary_state",
            side_effect=fake_summary,
        ):
            tab = logistics_views.LogisticsTab()
            self.addCleanup(tab.close)
            self.addCleanup(tab.deleteLater)
            tab.show()
            self._app.processEvents()

            self.assertEqual(calls, [])
            QTest.qWait(logistics_views._LOGISTICS_SUMMARY_BOOTSTRAP_DELAY_MS + 40)
            self._app.processEvents()
            self.assertEqual(calls, ["summary"])

    def test_logistics_tab_badges_track_changes_and_clear_on_open(self) -> None:
        pending_two_one = logistics_views.Result.ok(
            data={
                "providers_result": logistics_views.Result.ok(data={"records": [{}, {}]}, close_dialog=False),
                "tariffs_result": logistics_views.Result.ok(data={"records": [{}]}, close_dialog=False),
            },
            close_dialog=False,
        )
        pending_three_four = logistics_views.Result.ok(
            data={
                "providers_result": logistics_views.Result.ok(data={"records": [{}, {}, {}]}, close_dialog=False),
                "tariffs_result": logistics_views.Result.ok(data={"records": [{}, {}, {}, {}]}, close_dialog=False),
            },
            close_dialog=False,
        )

        with patch.object(logistics_views, "SyncWorker", _ImmediateSyncWorker), patch.object(
            logistics_views,
            "_load_logistics_summary_state",
            side_effect=[pending_two_one, pending_three_four],
        ), patch(
            "Logistics.views.cargo_providers_window.LogisticsCargoProvidersFormWindow",
            _FakeLogisticsWindow,
        ), patch(
            "Logistics.views.cargo_tariffs_window.LogisticsCargoTariffsWindow",
            _FakeLogisticsWindow,
        ):
            tab = logistics_views.LogisticsTab()
            self.addCleanup(tab.close)
            self.addCleanup(tab.deleteLater)

            tab._refresh_summaries_async()
            self.assertEqual(tab.cargo_providers_btn._badge_count, 2)
            self.assertEqual(tab.cargo_tariffs_btn._badge_count, 1)
            self.assertTrue(tab.cargo_providers_btn._active)
            self.assertTrue(tab.cargo_tariffs_btn._active)

            tab.open_cargo_providers_window()
            tab.open_cargo_tariffs_window()
            self.assertEqual(tab.cargo_providers_btn._badge_count, 0)
            self.assertEqual(tab.cargo_tariffs_btn._badge_count, 0)

            tab.cargo_providers_window.hide()
            tab.cargo_tariffs_window.hide()
            logistics_signals.cargo_providers_changed.emit()
            self._app.processEvents()
            self.assertEqual(tab.cargo_providers_btn._badge_count, 1)
            self.assertEqual(tab.cargo_tariffs_btn._badge_count, 3)
