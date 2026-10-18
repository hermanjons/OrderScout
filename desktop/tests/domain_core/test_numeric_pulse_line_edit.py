from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QFocusEvent
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout

from Core.views import NumericPulseLineEdit


class TestNumericPulseLineEdit(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def _build_host(self) -> tuple[QWidget, NumericPulseLineEdit]:
        host = QWidget()
        layout = QVBoxLayout(host)
        widget = NumericPulseLineEdit(decimals=3)
        layout.addWidget(widget)
        host.show()
        self.addCleanup(host.close)
        self.addCleanup(host.deleteLater)
        return host, widget

    def test_focus_out_keeps_decimal_text_with_dot_separator(self) -> None:
        host, widget = self._build_host()
        _ = host
        widget.setFocus(Qt.FocusReason.OtherFocusReason)
        self._app.processEvents()
        widget.setText("0.20")

        focus_out = QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.OtherFocusReason)
        QApplication.sendEvent(widget, focus_out)
        self._app.processEvents()

        self.assertEqual(widget.text(), "0.20")
        self.assertAlmostEqual(widget.value(), 0.2, places=6)


if __name__ == "__main__":
    unittest.main()
