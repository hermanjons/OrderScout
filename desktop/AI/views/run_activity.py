"""Compact, read-only details for an observed chat run."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class RunActivityPanel(QFrame):
    """Show supplied run observations without inventing progress or a plan."""

    close_requested = pyqtSignal()
    MAX_OBSERVATIONS = 100

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.run_id = ""
        self._messages: list[str] = []
        self._pending_scroll: tuple[str, int] | None = None
        self._scroll_passes = 0
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.timeout.connect(self._restore_scroll)
        self.setObjectName("runActivityPanel")
        self.setMinimumWidth(200)
        self.setMaximumWidth(280)
        self.resize(240, self.height())
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(
            "QFrame#runActivityPanel { background: #FAFBFD; border: 0; "
            "border-left: 1px solid #E2E8F0; }"
            "QFrame#runActivityPanel QWidget { font-family: 'Segoe UI'; font-size: 11px; }"
            "QLabel { border: 0; background: transparent; color: #475569; }"
            "QLabel#runActivityTitle { font-size: 12px; font-weight: 600; color: #0F172A; }"
            "QPushButton#runActivityClose { border: 0; border-radius: 5px; "
            "background: transparent; color: #64748B; font-size: 18px; }"
            "QPushButton#runActivityClose:hover { background: #EFF6FF; color: #2563EB; }"
            "QPushButton#runActivityClose:focus { border: 1px solid #2563EB; }"
            "QScrollArea#runActivityScroll { border: 0; background: transparent; }"
            "QWidget#runActivityRecords { background: transparent; }"
            "QScrollBar:vertical { width: 5px; background: transparent; margin: 0; }"
            "QScrollBar::handle:vertical { background: #CBD5E1; border-radius: 2px; min-height: 24px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 13, 12, 14)
        layout.setSpacing(10)
        header = QHBoxLayout()
        header.setSpacing(4)
        self.title_label = self._label("İşlem ayrıntıları")
        self.title_label.setObjectName("runActivityTitle")
        header.addWidget(self.title_label, 1)
        self.close_button = QPushButton("×", self)
        self.close_button.setObjectName("runActivityClose")
        self.close_button.setFixedSize(24, 24)
        self.close_button.setToolTip("İşlem ayrıntılarını kapat")
        self.close_button.setAccessibleName("İşlem ayrıntılarını kapat")
        self.close_button.clicked.connect(self.close_requested.emit)
        header.addWidget(self.close_button)
        layout.addLayout(header)

        metadata = QHBoxLayout()
        metadata.setSpacing(8)
        self.status_label = self._label("")
        self.status_label.setWordWrap(True)
        self.elapsed_label = self._label("")
        self.elapsed_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        metadata.addWidget(self.status_label, 1)
        metadata.addWidget(self.elapsed_label)
        layout.addLayout(metadata)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setObjectName("runActivityScroll")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setAccessibleName("Gözlenen işlemler")
        self.scroll_area.verticalScrollBar().rangeChanged.connect(self._apply_pending_scroll)
        self._records = QWidget()
        self._records.setObjectName("runActivityRecords")
        self._records_layout = QVBoxLayout(self._records)
        self._records_layout.setContentsMargins(0, 2, 4, 0)
        self._records_layout.setSpacing(12)
        self._records_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_area.setWidget(self._records)
        layout.addWidget(self.scroll_area, 1)
        self._replace_records([])

    def sizeHint(self):
        hint = super().sizeHint()
        hint.setWidth(240)
        return hint

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setTextFormat(Qt.TextFormat.PlainText)
        return label

    def set_run(
        self,
        run_id: str,
        *,
        status: str,
        elapsed: str,
        messages: list[str],
        active: bool = False,
    ) -> None:
        """Replace the selected run and its latest, consecutive-unique records."""
        previous_run = self.run_id
        self.run_id = run_id
        self.status_label.setText(status)
        self.status_label.setStyleSheet(
            f"color: {'#2563EB' if active else '#64748B'}; font-weight: 600;"
        )
        self.elapsed_label.setText(elapsed)
        observations: list[str] = []
        for message in messages:
            if message.strip() and (not observations or observations[-1] != message):
                observations.append(message)
        observations = observations[-self.MAX_OBSERVATIONS :]
        if previous_run == run_id and observations == self._messages:
            return

        bar = self.scroll_area.verticalScrollBar()
        if previous_run != run_id:
            scroll_target = ("top", 0)
        elif self._pending_scroll is not None:
            scroll_target = self._pending_scroll
        elif bar.value() >= bar.maximum() - 2:
            scroll_target = ("bottom", 0)
        else:
            scroll_target = ("preserve", bar.value())
        self._messages = observations
        self._pending_scroll = scroll_target
        self._replace_records(observations)
        self._scroll_passes = 0
        self._scroll_timer.start(0)

    def _replace_records(self, observations: list[str]) -> None:
        while self._records_layout.count():
            widget = self._records_layout.takeAt(0).widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        for message in observations or ["Henüz işlem kaydı yok."]:
            label = self._label(message)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            self._records_layout.addWidget(label)

    def _apply_pending_scroll(self) -> None:
        if self._pending_scroll is None:
            return
        mode, previous_value = self._pending_scroll
        bar = self.scroll_area.verticalScrollBar()
        bar.setValue(bar.maximum() if mode == "bottom" else previous_value)

    def _restore_scroll(self) -> None:
        self._apply_pending_scroll()
        self._scroll_passes += 1
        # Wrapped labels and the scroll area settle in separate layout events.
        if self._scroll_passes < 2:
            self._scroll_timer.start(0)
        else:
            self._pending_scroll = None
