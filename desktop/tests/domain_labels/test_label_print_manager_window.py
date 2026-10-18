from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from Core.views import SwitchSelectWidget
from Labels.views.label_print_manager_window import LabelPrintManagerWindow


class TestLabelPrintManagerWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_model_selector_searches_manufacturer_package_code(self) -> None:
        dialog = LabelPrintManagerWindow()
        try:
            self.assertIsInstance(dialog.model_combo, SwitchSelectWidget)
            self.assertGreaterEqual(dialog.model_combo.findData("TANEX_2736"), 0)
            model_index = dialog.model_combo.findData("TANEX_2610")
            self.assertGreaterEqual(model_index, 0)

            dialog.model_combo._search.setText("2610")
            dialog.model_combo._apply_filter()
            visible_codes = {
                entry["data"]
                for entry in dialog.model_combo._items
                if not entry["item"].isHidden()
            }
            self.assertEqual(visible_codes, {"TANEX_2610"})

            dialog.model_combo.setCurrentIndex(model_index)
            self.assertEqual(dialog.get_selected_model_code(), "TANEX_2610")
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
