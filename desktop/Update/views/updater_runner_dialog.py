from __future__ import annotations

import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout

from settings import ASSETS_DIR
from Update.constants.ui_constants import (
    UPDATE_RUNNER_BADGE_RUNNING_TEXT,
    UPDATE_RUNNER_DETAIL_CHECKING_TEXT,
    UPDATE_RUNNER_DETAIL_RUNNING_TEXT,
    UPDATE_RUNNER_EYEBROW_TEXT,
    UPDATE_RUNNER_STAGE_PREPARING_TEXT,
    UPDATE_RUNNER_STAGE_RUNNING_TEXT,
    UPDATE_RUNNER_SUBTITLE_TEXT,
    UPDATE_RUNNER_TITLE_TEXT,
    UPDATE_RUNNER_WINDOW_TITLE,
)


class UpdaterRunnerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._close_allowed = False
        self.setWindowTitle(UPDATE_RUNNER_WINDOW_TITLE)
        self.setFixedSize(460, 238)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setModal(False)

        icon_path = os.path.join(ASSETS_DIR, "orderscout-logo.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.setStyleSheet(
            """
            QDialog {
                background: #f8fafc;
                font-family: "Segoe UI";
            }
            QFrame#RunnerCard {
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 18px;
            }
            QLabel#Eyebrow {
                color: #2563eb;
                font-size: 11px;
                font-weight: 700;
            }
            QLabel#Title {
                color: #0f172a;
                font-size: 20px;
                font-weight: 700;
            }
            QLabel#Subtitle {
                color: #475569;
                font-size: 13px;
            }
            QLabel#Stage {
                color: #0f172a;
                font-size: 13px;
                font-weight: 600;
            }
            QLabel#Detail {
                color: #64748b;
                font-size: 12px;
            }
            QLabel#Badge {
                background: #dbeafe;
                color: #1d4ed8;
                border-radius: 10px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 700;
            }
            QProgressBar {
                background: #e2e8f0;
                border: none;
                border-radius: 4px;
                min-height: 8px;
                max-height: 8px;
            }
            QProgressBar::chunk {
                background: #2563eb;
                border-radius: 4px;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)

        card = QFrame(self)
        card.setObjectName("RunnerCard")
        root.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(12)

        logo = QLabel(card)
        logo.setFixedSize(36, 36)
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path).scaled(
                36,
                36,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            logo.setPixmap(pixmap)
        header.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)

        titles = QVBoxLayout()
        titles.setSpacing(2)

        self._eyebrow = QLabel(UPDATE_RUNNER_EYEBROW_TEXT, card)
        self._eyebrow.setObjectName("Eyebrow")
        titles.addWidget(self._eyebrow)

        self._title = QLabel(UPDATE_RUNNER_TITLE_TEXT, card)
        self._title.setObjectName("Title")
        self._title.setWordWrap(True)
        titles.addWidget(self._title)

        self._subtitle = QLabel(UPDATE_RUNNER_SUBTITLE_TEXT, card)
        self._subtitle.setObjectName("Subtitle")
        self._subtitle.setWordWrap(True)
        titles.addWidget(self._subtitle)
        header.addLayout(titles, 1)

        self._badge = QLabel(UPDATE_RUNNER_BADGE_RUNNING_TEXT, card)
        self._badge.setObjectName("Badge")
        header.addWidget(self._badge, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        self._stage = QLabel(UPDATE_RUNNER_STAGE_PREPARING_TEXT, card)
        self._stage.setObjectName("Stage")
        self._stage.setWordWrap(True)
        layout.addWidget(self._stage)

        self._detail = QLabel(UPDATE_RUNNER_DETAIL_CHECKING_TEXT, card)
        self._detail.setObjectName("Detail")
        self._detail.setWordWrap(True)
        layout.addWidget(self._detail)

        self._bar = QProgressBar(card)
        self._bar.setRange(0, 100)
        self._bar.setValue(8)
        self._bar.setTextVisible(False)
        layout.addWidget(self._bar)

    def set_progress(self, value: int) -> None:
        self._bar.setValue(max(0, min(100, int(value or 0))))

    def set_stage(self, text: str) -> None:
        self._stage.setText(str(text or "").strip() or UPDATE_RUNNER_STAGE_RUNNING_TEXT)

    def set_detail(self, text: str) -> None:
        self._detail.setText(str(text or "").strip() or UPDATE_RUNNER_DETAIL_RUNNING_TEXT)

    def set_badge(self, text: str, *, kind: str = "info") -> None:
        self._badge.setText(str(text or "").strip() or "Kurulum")
        palette = {
            "info": ("#dbeafe", "#1d4ed8"),
            "ok": ("#dcfce7", "#15803d"),
            "error": ("#fee2e2", "#b91c1c"),
        }
        bg, fg = palette.get(str(kind or "").strip().lower(), palette["info"])
        self._badge.setStyleSheet(
            "background: {bg}; color: {fg}; border-radius: 10px; padding: 4px 10px; "
            "font-size: 11px; font-weight: 700;".format(bg=bg, fg=fg)
        )

    def allow_close(self, allowed: bool) -> None:
        self._close_allowed = bool(allowed)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._close_allowed:
            super().closeEvent(event)
            return
        event.ignore()
