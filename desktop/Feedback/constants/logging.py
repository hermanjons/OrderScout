from __future__ import annotations


LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 5
LOG_ENCODING = "utf-8"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_MESSAGE_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"

__all__ = [
    "LOG_BACKUP_COUNT",
    "LOG_DATE_FORMAT",
    "LOG_ENCODING",
    "LOG_MAX_BYTES",
    "LOG_MESSAGE_FORMAT",
]
