from __future__ import annotations

import json
import os
import unittest
import logging
from logging.handlers import QueueHandler, RotatingFileHandler
from unittest.mock import patch

import httpx
from sqlalchemy.exc import IntegrityError

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog

from Feedback.processors.pipeline import (
    MessageHandler,
    Result,
    configure_logger,
    logger,
    map_error_to_message,
    resolve_log_file,
)
from Feedback.processors.logging_support import SafeRotatingFileHandler


class TestFeedbackPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        MessageHandler.reset_runtime_state()

    def test_resolve_log_file_points_to_orderscout_log(self) -> None:
        log_file = resolve_log_file()
        self.assertEqual(log_file.name, "orderscout.log")
        self.assertTrue(log_file.parent.exists())

    def test_configure_logger_is_idempotent(self) -> None:
        before = len(logger.handlers)
        configured = configure_logger()
        after = len(configured.handlers)
        self.assertIs(configured, logger)
        self.assertEqual(before, after)
        self.assertTrue(any(isinstance(handler, QueueHandler) for handler in configured.handlers))

    def test_file_logger_suppresses_log_file_os_errors(self) -> None:
        handler = SafeRotatingFileHandler("unused.log", delay=True)
        record = logging.LogRecord("orderscout", logging.INFO, __file__, 1, "test", (), None)

        with patch.object(RotatingFileHandler, "emit", side_effect=PermissionError("locked")):
            handler.emit(record)

    def test_file_logger_suppresses_internal_logging_errors(self) -> None:
        handler = SafeRotatingFileHandler("unused.log", delay=True)
        record = logging.LogRecord("orderscout", logging.INFO, __file__, 1, "test", (), None)

        with patch.object(SafeRotatingFileHandler, "shouldRollover", side_effect=PermissionError("locked")):
            handler.emit(record)

    def test_result_ok_preserves_payload(self) -> None:
        res = Result.ok("tamam", close_dialog=False, data={"x": 1})
        self.assertTrue(res.success)
        self.assertEqual(res.message, "tamam")
        self.assertFalse(res.close_dialog)
        self.assertEqual(res.data, {"x": 1})

    def test_result_fail_preserves_error(self) -> None:
        err = ValueError("boom")
        res = Result.fail("patladi", error=err, close_dialog=False, data={"y": 2})
        self.assertFalse(res.success)
        self.assertEqual(res.message, "patladi")
        self.assertIs(res.error, err)
        self.assertFalse(res.close_dialog)
        self.assertEqual(res.data, {"y": 2})

    def test_map_error_to_message_handles_builtin_exceptions(self) -> None:
        self.assertEqual(map_error_to_message(ValueError("x")), "Gecersiz deger.")
        self.assertEqual(map_error_to_message(FileNotFoundError("x")), "Gerekli dosya bulunamadi.")
        self.assertEqual(
            map_error_to_message(json.JSONDecodeError("bad", "{}", 0)),
            "JSON formati gecersiz.",
        )

    def test_map_error_to_message_handles_httpx_status_error(self) -> None:
        request = httpx.Request("GET", "https://example.com")
        response = httpx.Response(404, request=request)
        error = httpx.HTTPStatusError("bad", request=request, response=response)
        self.assertEqual(
            map_error_to_message(error),
            "HTTP istegi basarisiz (HTTP 404).",
        )

    def test_map_error_to_message_handles_httpx_request_error(self) -> None:
        request = httpx.Request("GET", "https://example.com")
        error = httpx.RequestError("down", request=request)
        self.assertEqual(map_error_to_message(error), "HTTP baglanti hatasi olustu.")

    def test_map_error_to_message_handles_specific_integrity_errors(self) -> None:
        not_null_error = IntegrityError(
            "INSERT ...",
            {},
            Exception("NOT NULL constraint failed: trendyol_order_data.id"),
        )
        self.assertEqual(
            map_error_to_message(not_null_error),
            "Zorunlu alan eksik: trendyol_order_data.id.",
        )

        fk_error = IntegrityError(
            "INSERT ...",
            {},
            Exception("FOREIGN KEY constraint failed"),
        )
        self.assertEqual(map_error_to_message(fk_error), "İlişkili kayıt bulunamadı.")

    def test_message_handler_success_shows_popup_and_accepts_dialog(self) -> None:
        dialog = QDialog()
        dialog_shown = {"accepted": False}

        def _accepted() -> None:
            dialog_shown["accepted"] = True

        dialog.accepted.connect(_accepted)

        with patch("Core.views.AppMessageCenter.success") as success_mock:
            MessageHandler.show(dialog, Result.ok("basarili", close_dialog=True), only_errors=False)

        success_mock.assert_called_once()
        self.assertTrue(dialog_shown["accepted"])

    def test_message_handler_error_shows_details(self) -> None:
        err = RuntimeError("pat")
        with patch("Core.views.AppMessageCenter.error") as error_mock:
            MessageHandler.show(None, Result.fail("hata", error=err, close_dialog=False), only_errors=True)

        error_mock.assert_called_once()
        _, kwargs = error_mock.call_args
        self.assertEqual(kwargs["details"], "RuntimeError: pat")

    def test_message_handler_suppresses_duplicate_error_bursts(self) -> None:
        err = RuntimeError("pat")
        with patch("Core.views.AppMessageCenter.error") as error_mock:
            MessageHandler.show(None, Result.fail("hata", error=err, close_dialog=False), only_errors=True)
            MessageHandler.show(None, Result.fail("hata", error=err, close_dialog=False), only_errors=True)

        error_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
