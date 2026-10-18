from __future__ import annotations

from time import monotonic
from typing import Optional

from PyQt6.QtWidgets import QDialog

from Feedback.constants.messages import ERROR_SUPPRESSION_WINDOW_SECONDS, MESSAGE_TITLE_FAIL, MESSAGE_TITLE_OK
from Feedback.processors.result_models import Result


class MessageHandler:
    _ERROR_SUPPRESSION_WINDOW_SECONDS = ERROR_SUPPRESSION_WINDOW_SECONDS
    _last_error_signature: tuple[str, str, str] | None = None
    _last_error_at: float = 0.0

    @classmethod
    def _should_suppress_error(cls, title: str, message: str, details: str | None) -> bool:
        now = monotonic()
        signature = (str(title or ""), str(message or ""), str(details or ""))
        if (
            cls._last_error_signature == signature
            and (now - cls._last_error_at) < cls._ERROR_SUPPRESSION_WINDOW_SECONDS
        ):
            return True
        cls._last_error_signature = signature
        cls._last_error_at = now
        return False

    @classmethod
    def reset_runtime_state(cls) -> None:
        cls._last_error_signature = None
        cls._last_error_at = 0.0

    @staticmethod
    def show(
        dialog: Optional[object],
        result: Result,
        *,
        only_errors: bool = False,
        ui_enabled: bool = True,
        title_ok: str = MESSAGE_TITLE_OK,
        title_fail: str = MESSAGE_TITLE_FAIL,
    ) -> None:
        if not ui_enabled:
            return

        parent = dialog if isinstance(dialog, QDialog) else None
        from Core.views import AppMessageCenter

        if result.success:
            if (not only_errors) and result.message:
                AppMessageCenter.success(parent, title_ok, result.message)
            if result.close_dialog and isinstance(dialog, QDialog):
                dialog.accept()
            return

        details = None
        if result.error is not None:
            details = f"{type(result.error).__name__}: {result.error}"
        if MessageHandler._should_suppress_error(title_fail, str(result.message or ""), details):
            return
        AppMessageCenter.error(parent, title_fail, str(result.message or ""), details=details)
