from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from Core.views import NumberStepper


class TestNumberStepper(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_set_value_clamps_to_range_and_updates_text(self) -> None:
        widget = NumberStepper(minimum=5, maximum=20, step=3)
        widget.setValue(999)
        self.assertEqual(widget.value(), 20)
        self.assertEqual(widget.input.text(), "20")

        widget.setValue(-10)
        self.assertEqual(widget.value(), 5)
        self.assertEqual(widget.input.text(), "5")

    def test_step_buttons_respect_single_step_and_bounds(self) -> None:
        widget = NumberStepper(minimum=0, maximum=10, step=4)
        widget.setValue(8)
        widget._step_by(+1)
        self.assertEqual(widget.value(), 10)

        widget._step_by(-1)
        self.assertEqual(widget.value(), 6)

    def test_set_range_reclamps_current_value(self) -> None:
        widget = NumberStepper(minimum=0, maximum=100, step=1)
        widget.setValue(75)
        widget.setRange(10, 50)
        self.assertEqual(widget.value(), 50)

    def test_invalid_text_falls_back_to_minimum(self) -> None:
        widget = NumberStepper(minimum=3, maximum=9, step=1)
        widget.input.setText("abc")
        self.assertEqual(widget.value(), 3)
        self.assertEqual(widget.input.text(), "3")


if __name__ == "__main__":
    unittest.main()
