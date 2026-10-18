from __future__ import annotations

from pathlib import Path

from settings import MEDIA_LOGS


DOMAIN_LOGS_DIR: Path = MEDIA_LOGS
LOG_FILE_NAME = "orderscout.log"


def feedback_logs_dir() -> Path:
    DOMAIN_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return DOMAIN_LOGS_DIR


def feedback_log_file() -> Path:
    return feedback_logs_dir() / LOG_FILE_NAME


__all__ = [
    "DOMAIN_LOGS_DIR",
    "LOG_FILE_NAME",
    "feedback_log_file",
    "feedback_logs_dir",
]
