from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget


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

        self._placeholder = QLabel(self._loading_text, self)
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color:#64748B; font-size:13px; font-weight:600;")
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
        if self._placeholder is not None:
            self._placeholder.setText(self._loading_text)
        self._load_timer.start()

    def _ensure_loaded(self) -> None:
        self._load_scheduled = False
        if self._content is not None:
            return
        self.setUpdatesEnabled(False)
        try:
            widget = self._factory()
            self._content = widget
            self._layout.addWidget(widget, 1)
            if self._placeholder is not None:
                self._placeholder.deleteLater()
                self._placeholder = None
        except Exception as exc:
            if self._placeholder is not None:
                self._placeholder.setText(f"Sekme açılamadı: {exc}")
            print(f"[main tabs] load failed: {exc}")
        finally:
            self.setUpdatesEnabled(True)
            self.update()

    def __getattr__(self, name: str):
        if name.startswith("_") or self._content is None:
            raise AttributeError(name)
        return getattr(self._content, name)
