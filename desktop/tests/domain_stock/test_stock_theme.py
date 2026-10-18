from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget

from Core.views import PhoneNumberInput
from Stock.views.views import MODERN_LIGHT_QSS, _apply_stock_composite_theme


class TestStockTheme(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_stock_theme_styles_plain_fields_without_overriding_composite_children(self) -> None:
        root = QWidget()
        self.addCleanup(root.close)
        root.setObjectName("StockRoot")
        root.setStyleSheet(MODERN_LIGHT_QSS)

        layout = QVBoxLayout(root)
        plain_line_edit = QLineEdit(root)
        phone_input = PhoneNumberInput(root)
        layout.addWidget(plain_line_edit)
        layout.addWidget(phone_input)

        _apply_stock_composite_theme(root)

        self.assertIn("background: #FFFFFF", plain_line_edit.styleSheet())
        self.assertEqual(phone_input._number_edit.styleSheet(), "")
        self.assertNotIn("#StockRoot QLineEdit,", MODERN_LIGHT_QSS)


if __name__ == "__main__":
    unittest.main()
