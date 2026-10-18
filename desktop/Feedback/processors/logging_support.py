from __future__ import annotations

import atexit
import logging
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from pathlib import Path
from queue import Queue

from Feedback.constants.logging import (
    LOG_BACKUP_COUNT,
    LOG_DATE_FORMAT,
    LOG_ENCODING,
    LOG_MAX_BYTES,
    LOG_MESSAGE_FORMAT,
)
from Feedback.constants.paths import feedback_log_file
from Feedback.processors.redaction import SecretRedactingFormatter

_LOGGER_NAME = "orderscout"
_QUEUE_HANDLER_LOG_FILE_ATTR = "_orderscout_log_file"
_QUEUE_HANDLER_QUEUE_ATTR = "_orderscout_queue"
_listener: QueueListener | None = None


class SafeRotatingFileHandler(RotatingFileHandler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            super().emit(record)
        except OSError:
            return

    def handleError(self, record: logging.LogRecord) -> None:
        return


def resolve_log_file() -> Path:
    return feedback_log_file()


def _has_orderscout_file_handler(logger: logging.Logger, log_file: Path) -> bool:
    expected = str(log_file)
    for handler in logger.handlers:
        if isinstance(handler, QueueHandler):
            try:
                if str(getattr(handler, _QUEUE_HANDLER_LOG_FILE_ATTR, "")) == expected:
                    return True
            except Exception:
                continue
    return False


def _stop_listener() -> None:
    global _listener
    listener = _listener
    _listener = None
    if listener is None:
        return
    try:
        listener.stop()
    except Exception:
        pass


def configure_logger() -> logging.Logger:
    global _listener

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    log_file = resolve_log_file()
    if _has_orderscout_file_handler(logger, log_file):
        return logger

    file_handler = SafeRotatingFileHandler(
        filename=str(log_file),
        mode="a",
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding=LOG_ENCODING,
        delay=True,
    )
    formatter = SecretRedactingFormatter(
        fmt=LOG_MESSAGE_FORMAT,
        datefmt=LOG_DATE_FORMAT,
    )
    file_handler.setFormatter(formatter)

    log_queue: Queue[logging.LogRecord] = Queue()
    queue_handler = QueueHandler(log_queue)
    # Redact before enqueueing, including exception text prepared by QueueHandler.
    queue_handler.setFormatter(SecretRedactingFormatter("%(message)s"))
    setattr(queue_handler, _QUEUE_HANDLER_LOG_FILE_ATTR, str(log_file))
    setattr(queue_handler, _QUEUE_HANDLER_QUEUE_ATTR, log_queue)

    _stop_listener()
    _listener = QueueListener(log_queue, file_handler, respect_handler_level=True)
    _listener.start()

    logger.addHandler(queue_handler)
    logger.info("[LOGGER] Log file: %s", log_file)
    return logger


atexit.register(_stop_listener)
logger = configure_logger()
