from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from Feedback.processors.logging_support import logger


@dataclass
class Result:
    success: bool
    message: str = ""
    error: Optional[Exception] = None
    close_dialog: bool = True
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls, message: str = "", close_dialog: bool = True, data: Optional[dict[str, Any]] = None) -> "Result":
        res = cls(True, message=message, close_dialog=close_dialog, data=data or {})
        if message:
            logger.info("[OK] %s", message)
        return res

    @classmethod
    def fail(
        cls,
        message: str = "",
        error: Optional[Exception] = None,
        close_dialog: bool = False,
        data: Optional[dict[str, Any]] = None,
    ) -> "Result":
        res = cls(False, message=message, error=error, close_dialog=close_dialog, data=data or {})
        if message:
            logger.error("[FAIL] %s", message)
        if error is not None:
            logger.exception("[%s] %s", type(error).__name__, error, exc_info=error)
        return res
