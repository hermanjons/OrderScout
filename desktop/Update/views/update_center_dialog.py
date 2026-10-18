from __future__ import annotations

import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from settings import ASSETS_DIR
from Update.constants.ui_constants import (
    UPDATE_CENTER_HEADER_SUBTITLE,
    UPDATE_CENTER_HEADER_TITLE,
    UPDATE_CENTER_WINDOW_TITLE,
    UPDATE_CHECK_BUTTON_TEXT,
    UPDATE_CLOSE_BUTTON_TEXT,
    UPDATE_CURRENT_VERSION_LABEL,
    UPDATE_INSTALL_BUTTON_TEXT,
    UPDATE_LATEST_VERSION_LABEL,
    UPDATE_NOTES_EMPTY_TEXT,
    UPDATE_NOTES_TITLE,
    UPDATE_PROGRESS_PREPARING_TITLE,
    UPDATE_PROGRESS_PROCESSING_TEXT,
    UPDATE_PROGRESS_READY_TEXT,
    UPDATE_PROGRESS_WINDOW_TITLE,
    UPDATE_PUBLISHED_AT_LABEL,
    UPDATE_RELEASE_TITLE_LABEL,
    UPDATE_RUNTIME_MODE_LABEL,
    UPDATE_SELECTED_ASSET_LABEL,
    UPDATE_SOURCE_LABEL,
    UPDATE_STATUS_PENDING_TEXT,
)


class UpdateCenterDialog(QDialog):
    check_requested = pyqtSignal()
    install_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(UPDATE_CENTER_WINDOW_TITLE)
        self.setMinimumSize(760, 560)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setModal(False)

        icon_path = os.path.join(ASSETS_DIR, "update-icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.setStyleSheet(
            """
            QDialog {
                background: #F3F4F6;
                color: #0F172A;
            }
            QFrame#Card {
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 12px;
            }
            QLabel#HeaderTitle {
                font-size: 18px;
                font-weight: 800;
                color: #0F172A;
            }
            QLabel#HeaderSubtitle {
                font-size: 12px;
                color: #475569;
            }
            QLabel#FieldKey {
                font-size: 12px;
                color: #64748B;
                font-weight: 600;
            }
            QLabel#FieldValue {
                font-size: 13px;
                color: #0F172A;
                font-weight: 700;
            }
            QLabel#StatusBadge {
                border-radius: 10px;
                padding: 5px 10px;
                font-size: 12px;
                font-weight: 700;
            }
            QTextEdit#NotesBox {
                background: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 10px;
                padding: 8px;
                font-size: 12px;
            }
            QPushButton#Primary {
                background: #2563EB;
                color: #FFFFFF;
                border: none;
                border-radius: 10px;
                padding: 8px 14px;
                font-weight: 700;
            }
            QPushButton#Primary:disabled {
                background: #94A3B8;
                color: #E2E8F0;
            }
            QPushButton#Secondary {
                background: #FFFFFF;
                color: #0F172A;
                border: 1px solid #CBD5E1;
                border-radius: 10px;
                padding: 8px 14px;
                font-weight: 700;
            }
            QPushButton#Secondary:disabled {
                color: #94A3B8;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        header = QFrame()
        header.setObjectName("Card")
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(14, 12, 14, 12)
        header_row.setSpacing(10)

        header_col = QVBoxLayout()
        header_col.setContentsMargins(0, 0, 0, 0)
        header_col.setSpacing(2)

        title = QLabel(UPDATE_CENTER_HEADER_TITLE)
        title.setObjectName("HeaderTitle")
        subtitle = QLabel(UPDATE_CENTER_HEADER_SUBTITLE)
        subtitle.setObjectName("HeaderSubtitle")
        subtitle.setWordWrap(True)

        header_col.addWidget(title)
        header_col.addWidget(subtitle)
        header_row.addLayout(header_col, 1)

        self._status_badge = QLabel(UPDATE_STATUS_PENDING_TEXT)
        self._status_badge.setObjectName("StatusBadge")
        header_row.addWidget(self._status_badge, 0, Qt.AlignmentFlag.AlignTop)
        root.addWidget(header)

        detail_card = QFrame()
        detail_card.setObjectName("Card")
        detail_grid = QGridLayout(detail_card)
        detail_grid.setContentsMargins(14, 12, 14, 12)
        detail_grid.setHorizontalSpacing(16)
        detail_grid.setVerticalSpacing(10)

        # key/value pairs occupy two rows each; use stepped indices to avoid overlap.
        self._current_value = self._add_detail_row(detail_grid, 0, 0, UPDATE_CURRENT_VERSION_LABEL)
        self._latest_value = self._add_detail_row(detail_grid, 0, 2, UPDATE_LATEST_VERSION_LABEL)
        self._release_value = self._add_detail_row(detail_grid, 2, 0, UPDATE_RELEASE_TITLE_LABEL)
        self._published_value = self._add_detail_row(detail_grid, 2, 2, UPDATE_PUBLISHED_AT_LABEL)
        self._asset_value = self._add_detail_row(detail_grid, 4, 0, UPDATE_SELECTED_ASSET_LABEL)
        self._source_value = self._add_detail_row(detail_grid, 4, 2, UPDATE_SOURCE_LABEL)
        self._runtime_value = self._add_detail_row(detail_grid, 6, 0, UPDATE_RUNTIME_MODE_LABEL, col_span=4)
        root.addWidget(detail_card)

        notes_card = QFrame()
        notes_card.setObjectName("Card")
        notes_col = QVBoxLayout(notes_card)
        notes_col.setContentsMargins(14, 12, 14, 12)
        notes_col.setSpacing(8)

        notes_title = QLabel(UPDATE_NOTES_TITLE)
        notes_title.setObjectName("FieldKey")
        self._notes = QTextEdit()
        self._notes.setObjectName("NotesBox")
        self._notes.setReadOnly(True)

        notes_col.addWidget(notes_title)
        notes_col.addWidget(self._notes, 1)
        root.addWidget(notes_card, 1)

        progress_card = QFrame()
        progress_card.setObjectName("Card")
        progress_col = QVBoxLayout(progress_card)
        progress_col.setContentsMargins(14, 10, 14, 10)
        progress_col.setSpacing(6)

        self._progress_stage = QLabel(UPDATE_PROGRESS_READY_TEXT)
        self._progress_stage.setObjectName("FieldKey")
        self._progress_bar = QProgressBar()
        self._progress_bar.setMinimum(0)
        self._progress_bar.setMaximum(100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)

        progress_col.addWidget(self._progress_stage)
        progress_col.addWidget(self._progress_bar)
        root.addWidget(progress_card)
        self._progress_card = progress_card
        self.set_progress_visible(False)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)

        self._check_btn = QPushButton(UPDATE_CHECK_BUTTON_TEXT)
        self._check_btn.setObjectName("Secondary")
        self._install_btn = QPushButton(UPDATE_INSTALL_BUTTON_TEXT)
        self._install_btn.setObjectName("Primary")
        self._close_btn = QPushButton(UPDATE_CLOSE_BUTTON_TEXT)
        self._close_btn.setObjectName("Secondary")

        self._check_btn.clicked.connect(self.check_requested.emit)
        self._install_btn.clicked.connect(self.install_requested.emit)
        self._close_btn.clicked.connect(self.close)

        actions.addWidget(self._check_btn)
        actions.addWidget(self._install_btn)
        actions.addStretch(1)
        actions.addWidget(self._close_btn)
        root.addLayout(actions)

        self.set_status(UPDATE_STATUS_PENDING_TEXT, kind="idle")
        self.set_install_enabled(False)

    def _add_detail_row(
        self,
        layout: QGridLayout,
        row: int,
        column: int,
        key: str,
        *,
        col_span: int = 1,
    ) -> QLabel:
        key_label = QLabel(str(key or ""))
        key_label.setObjectName("FieldKey")
        value_label = QLabel("-")
        value_label.setObjectName("FieldValue")
        value_label.setWordWrap(True)
        layout.addWidget(key_label, row, column, 1, col_span)
        layout.addWidget(value_label, row + 1, column, 1, col_span)
        return value_label

    def set_status(self, text: str, *, kind: str = "idle") -> None:
        palette = {
            "idle": ("#E2E8F0", "#334155"),
            "busy": ("#DBEAFE", "#1D4ED8"),
            "ok": ("#DCFCE7", "#166534"),
            "update": ("#FEF3C7", "#92400E"),
            "error": ("#FEE2E2", "#991B1B"),
        }
        bg, fg = palette.get(str(kind or "idle").lower(), palette["idle"])
        self._status_badge.setStyleSheet(
            f"background:{bg}; color:{fg}; border-radius: 10px; padding: 5px 10px; font-size: 12px; font-weight: 700;"
        )
        self._status_badge.setText(str(text or "-"))

    def set_versions(self, *, current_version: str, latest_version: str) -> None:
        self._current_value.setText(str(current_version or "-"))
        self._latest_value.setText(str(latest_version or "-"))

    def set_release_meta(self, *, title: str, published_at: str) -> None:
        self._release_value.setText(str(title or "-"))
        self._published_value.setText(str(published_at or "-"))

    def set_asset_meta(self, *, asset_text: str, source_text: str) -> None:
        self._asset_value.setText(str(asset_text or "-"))
        self._source_value.setText(str(source_text or "-"))

    def set_runtime_text(self, text: str) -> None:
        self._runtime_value.setText(str(text or "-"))

    def set_notes(self, text: str) -> None:
        body = str(text or "").strip()
        if not body:
            self._notes.setPlainText(UPDATE_NOTES_EMPTY_TEXT)
            return
        if "<" in body and ">" in body:
            self._notes.setHtml(body)
            return
        self._notes.setPlainText(body)

    def set_check_enabled(self, enabled: bool) -> None:
        self._check_btn.setEnabled(bool(enabled))

    def set_install_enabled(self, enabled: bool) -> None:
        self._install_btn.setEnabled(bool(enabled))

    def set_progress_visible(self, visible: bool) -> None:
        self._progress_card.setVisible(bool(visible))

    def set_progress(self, *, percent: int, stage_text: str) -> None:
        value = max(0, min(100, int(percent or 0)))
        self._progress_bar.setValue(value)
        self._progress_stage.setText(str(stage_text or UPDATE_PROGRESS_PROCESSING_TEXT))


class UpdateProgressDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(UPDATE_PROGRESS_WINDOW_TITLE)
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        self._title = QLabel(UPDATE_PROGRESS_PREPARING_TITLE)
        self._title.setStyleSheet("font-size: 14px; font-weight: 700;")

        self._stage = QLabel(UPDATE_STATUS_PENDING_TEXT)
        self._stage.setStyleSheet("font-size: 12px; color: #475569;")

        self._bar = QProgressBar()
        self._bar.setMinimum(0)
        self._bar.setMaximum(100)
        self._bar.setValue(0)
        self._bar.setTextVisible(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)
        root.addWidget(self._title)
        root.addWidget(self._stage)
        root.addWidget(self._bar)

    def set_stage(self, text: str) -> None:
        self._stage.setText(str(text or ""))

    def set_progress(self, value: int) -> None:
        percent = max(0, min(100, int(value or 0)))
        self._bar.setValue(percent)

    def set_title(self, text: str) -> None:
        self._title.setText(str(text or ""))
