from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


class LazyTabHost(QWidget):
    def __init__(
        self,
        *,
        factory: Callable[[], QWidget],
        loading_text: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._factory = factory
        self._content: QWidget | None = None
        self._load_scheduled = False
        self._loading_text = str(loading_text or "Modül yükleniyor...")
        self._load_timer = QTimer(self)
        self._load_timer.setSingleShot(True)
        self._load_timer.setInterval(0)
        self._load_timer.timeout.connect(self._ensure_loaded)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._layout = layout

        self._placeholder = QWidget(self)
        placeholder_layout = QVBoxLayout(self._placeholder)
        placeholder_layout.addStretch()
        self._status = QLabel(self._loading_text, self._placeholder)
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet("color:#64748B; font-size:13px; font-weight:600;")
        placeholder_layout.addWidget(self._status)
        self._retry = QPushButton("Tekrar dene", self._placeholder)
        self._retry.clicked.connect(self.request_load)
        self._retry.hide()
        placeholder_layout.addWidget(self._retry, alignment=Qt.AlignmentFlag.AlignHCenter)
        placeholder_layout.addStretch()
        self._layout.addWidget(self._placeholder, 1)

    @property
    def content(self) -> QWidget | None:
        return self._content

    def is_loaded(self) -> bool:
        return self._content is not None

    def request_load(self) -> None:
        if self._content is not None or self._load_scheduled:
            return
        self._load_scheduled = True
        self._status.setText(self._loading_text)
        self._retry.hide()
        self._load_timer.start()

    def _ensure_loaded(self) -> None:
        self._load_scheduled = False
        if self._content is not None:
            return
        self.setUpdatesEnabled(False)
        try:
            widget = self._factory()
            self._layout.addWidget(widget, 1)
            self._content = widget
            self._layout.removeWidget(self._placeholder)
            self._placeholder.hide()
            self._placeholder.deleteLater()
        except Exception as exc:
            self._status.setText("Sekme açılamadı.")
            self._retry.show()
            print(f"[main tabs] load failed: {exc}")
        finally:
            self.setUpdatesEnabled(True)
            self.update()

    def __getattr__(self, name: str):
        if name.startswith("_") or self._content is None:
            raise AttributeError(name)
        return getattr(self._content, name)
