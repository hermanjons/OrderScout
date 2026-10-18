from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QApplication, QListView

from Core.views import PhoneNumberInput


class TestPhoneNumberInput(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_popup_view_uses_opaque_list_surface(self) -> None:
        widget = PhoneNumberInput(dial_codes=["+90", "+1", "+44"])
        popup_view = widget._code_combo.view()
        self.assertIsInstance(popup_view, QListView)
        self.assertEqual(popup_view.objectName(), "PhoneDialCodePopup")
        self.assertTrue(popup_view.autoFillBackground())
        self.assertEqual(popup_view.palette().color(QPalette.ColorRole.Base).name().lower(), "#ffffff")
        self.assertIn("background: #FFFFFF", popup_view.styleSheet())


if __name__ == "__main__":
    unittest.main()
