from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QValidator
from PyQt6.QtWidgets import QApplication

from Core.views import CircularPercentageInput


class TestCircularPercentageInput(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_progress_ratio_matches_percentage(self) -> None:
        widget = CircularPercentageInput(decimals=2)
        widget.setValue(20)
        self.assertAlmostEqual(widget.progressRatio(), 0.2, places=3)

    def test_set_value_clamps_to_hundred(self) -> None:
        widget = CircularPercentageInput(decimals=2)
        widget.setValue(120)
        self.assertEqual(widget.value(), 100.0)
        self.assertEqual(widget.text(), "100")

    def test_validator_rejects_values_above_hundred(self) -> None:
        widget = CircularPercentageInput(decimals=2)
        validator = widget.validator()
        self.assertIsNotNone(validator)
        state, _, _ = validator.validate("125", 3)
        self.assertEqual(state, QValidator.State.Invalid)

    def test_widget_keeps_circular_size_hint(self) -> None:
        widget = CircularPercentageInput(decimals=2)
        hint = widget.sizeHint()
        self.assertEqual(hint.width(), hint.height())
        self.assertGreaterEqual(hint.width(), 84)


if __name__ == "__main__":
    unittest.main()
