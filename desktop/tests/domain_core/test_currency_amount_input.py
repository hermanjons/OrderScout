from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from Core.views import CurrencyAmountInput


class TestCurrencyAmountInput(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_set_value_formats_with_group_separator(self) -> None:
        widget = CurrencyAmountInput(decimals=2, currency="try")
        widget.setValue(2500.75)
        self.assertEqual(widget.text(), "2.500,75")
        self.assertAlmostEqual(widget.value(), 2500.75, places=3)
        self.assertEqual(widget.currency(), "TRY")

    def test_raw_digit_entry_auto_groups_large_integer(self) -> None:
        widget = CurrencyAmountInput(decimals=3)
        widget.lineEdit().setText("100000")
        self.assertEqual(widget.text(), "100.000")
        self.assertEqual(widget.value(), 100000.0)

    def test_glow_curve_stays_subtle_but_keeps_growing(self) -> None:
        widget = CurrencyAmountInput(decimals=2)
        low = widget.lineEdit()._intensity(123.0)
        high = widget.lineEdit()._intensity(100_000_000.0)
        self.assertGreater(high, low)
        self.assertLess(high, 0.25)


if __name__ == "__main__":
    unittest.main()
