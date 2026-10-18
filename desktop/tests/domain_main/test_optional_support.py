from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel
from sqlmodel import SQLModel

import Core.db.model_registry  # noqa: F401
from AI.processors.manual_capabilities import list_manual_capabilities
from Feedback.processors.pipeline import Result
from Orders.views.views import OrdersTab
from Support.views.support_dialog import SupportDialog
from Support.views.views import SupportButton


class TestOptionalSupport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _dialog(self, url):
        with patch("settings.DONATION_URL", url):
            dialog = SupportDialog()
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.close)
        return dialog

    def test_support_is_available_without_any_configuration_or_network(self):
        with patch("requests.sessions.Session.request", side_effect=AssertionError("Unexpected network")):
            action = SupportButton().create_action()
            dialog = self._dialog("")
        self.assertEqual(action.data(), "support")
        self.assertIn("kahve", action.text())
        self.assertFalse(dialog.donate_button.isEnabled())
        self.assertIn("henüz eklenmedi", dialog.hint_label.text())

    def test_main_toolbar_offers_support_in_place_of_activation(self):
        from Main_interface.views.views import MainInterface

        with patch("Main_interface.views.views.DEFAULT_ENABLE_AI_UI", False):
            window = MainInterface()
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
        actions = window.toolBar.actions()
        self.assertEqual(sum(action.data() == "support" for action in actions), 1)
        self.assertFalse(any(action.data() == "license_manager" for action in actions))

    def test_configured_donation_opens_only_on_click(self):
        with patch("Support.views.support_dialog.QDesktopServices.openUrl", return_value=True) as open_url:
            dialog = self._dialog("https://buymeacoffee.com/example")
            open_url.assert_not_called()
            QTest.mouseClick(dialog.donate_button, Qt.MouseButton.LeftButton)
        open_url.assert_called_once_with(dialog.donation_url)

    def test_invalid_donation_urls_are_disabled(self):
        for url in ("not a link", "https://", "file:///private", "javascript:alert(1)"):
            with self.subTest(url=url):
                self.assertFalse(self._dialog(url).donate_button.isEnabled())

    def test_browser_failure_is_reported_without_closing_app(self):
        dialog = self._dialog("https://buymeacoffee.com/example")
        with patch("Support.views.support_dialog.QDesktopServices.openUrl", return_value=False), \
             patch("Support.views.support_dialog.AppMessageCenter.warning") as warning:
            dialog._open_donation_page()
        warning.assert_called_once()

    def test_new_installations_do_not_register_license_tables(self):
        from Core.constants.db_constants import SOURCE_IDENTITY_TABLES

        self.assertNotIn("license_state", SQLModel.metadata.tables)
        self.assertNotIn("license_action_log", SQLModel.metadata.tables)
        self.assertNotIn("license_state", SOURCE_IDENTITY_TABLES)
        self.assertNotIn("license_action_log", SOURCE_IDENTITY_TABLES)

    def test_ai_cannot_offer_removed_license_actions(self):
        capabilities = list_manual_capabilities()
        self.assertTrue(capabilities)
        self.assertFalse(any(cap.domain == "license" for cap in capabilities))

    def test_order_fetch_starts_without_license_validation(self):
        button = Mock()
        button.isEnabled.return_value = True
        companies = Mock()
        companies.count.return_value = 1
        tab = SimpleNamespace(company_list=companies, fetch_button=button, status_label=QLabel())
        with patch("Orders.views.actions.get_orders_from_companies", return_value=Result.ok()) as fetch:
            OrdersTab.get_orders(tab)
        fetch.assert_called_once_with(tab, companies, button)
        button.start.assert_called_once()
        self.assertNotIn("Lisans", tab.status_label.text())

    def test_order_fetch_failure_restores_button(self):
        button = Mock()
        button.isEnabled.return_value = True
        companies = Mock()
        companies.count.return_value = 1
        tab = SimpleNamespace(company_list=companies, fetch_button=button, status_label=QLabel())
        with patch("Orders.views.actions.get_orders_from_companies", return_value=Result.fail("Test error")), \
             patch("Orders.views.views.MessageHandler.show"):
            OrdersTab.get_orders(tab)
        button.fail.assert_called_once()
        button.setEnabled.assert_called_with(True)
        self.assertIn("Test error", tab.status_label.text())
