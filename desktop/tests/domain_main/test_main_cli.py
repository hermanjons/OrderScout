from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import main


class TestMainCli(unittest.TestCase):
    def test_apply_runtime_flags_test_lab_ui(self) -> None:
        original = os.environ.get("ENABLE_TEST_LAB_UI")
        try:
            with patch("sys.argv", ["main.py", "--test-lab-ui", "1"]):
                main._apply_runtime_flags()
            self.assertEqual(os.environ.get("ENABLE_TEST_LAB_UI"), "1")
        finally:
            if original is None:
                os.environ.pop("ENABLE_TEST_LAB_UI", None)
            else:
                os.environ["ENABLE_TEST_LAB_UI"] = original

    def test_cli_router_worker_dispatch(self) -> None:
        with patch("sys.argv", ["main.py", "--worker", "orders.db_save_worker"]):
            with patch.object(main, "_run_worker_mode") as run_worker:
                routed = main._cli_router()

        self.assertTrue(routed)
        run_worker.assert_called_once_with("orders.db_save_worker")

    def test_cli_router_update_runner_dispatch(self) -> None:
        with patch("sys.argv", ["main.py", "--update-runner", "payload.json"]):
            with patch.object(main, "_run_update_runner_mode") as run_runner:
                routed = main._cli_router()

        self.assertTrue(routed)
        run_runner.assert_called_once_with("payload.json")

    def test_cli_router_stock_dialog_smoke_dispatch(self) -> None:
        with patch("sys.argv", ["main.py", "--smoke-stock-dialogs", "report.json"]):
            with patch.object(main, "_run_stock_dialog_smoke_mode") as run_smoke:
                routed = main._cli_router()

        self.assertTrue(routed)
        run_smoke.assert_called_once_with("report.json")

    def test_cli_router_ignores_removed_listing_flag(self) -> None:
        with patch("sys.argv", ["main.py", "--listing-db-save-worker"]):
            routed = main._cli_router()

        self.assertFalse(routed)


if __name__ == "__main__":
    unittest.main()
