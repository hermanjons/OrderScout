from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from Core.views import CircularProgressButton


class TestCircularProgressButton(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_set_progress_starts_button_from_idle(self) -> None:
        button = CircularProgressButton("Run")
        button.setProgress(25)
        self.assertTrue(button._is_running)
        self.assertEqual(button._progress, 25)

    def test_auto_reset_can_be_disabled_for_multistage_jobs(self) -> None:
        button = CircularProgressButton("Run")
        button.setAutoResetOnComplete(False)
        button.setProgress(100)
        self.assertTrue(button._is_running)
        self.assertEqual(button._progress, 100)

    def test_reset_clears_running_text_progress_and_failure_state(self) -> None:
        button = CircularProgressButton("Run")
        button.setProgress(55)
        button.setRunningText("Saving")
        button.fail()
        button.reset()
        self.assertFalse(button._is_running)
        self.assertFalse(button._is_failed)
        self.assertEqual(button._progress, 0)
        self.assertEqual(button.runningText(), "")


if __name__ == "__main__":
    unittest.main()
