from __future__ import annotations

import math
import os

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QAbstractButton,
    QLabel, QHBoxLayout, QSizePolicy, QGraphicsDropShadowEffect,
    QLineEdit, QToolButton, QLayout, QTableWidget, QHeaderView,
    QListView, QListWidget, QListWidgetItem, QAbstractItemView, QFrame,
    QDateEdit, QCalendarWidget, QComboBox, QGraphicsOpacityEffect, QDialog,
    QAbstractScrollArea, QGraphicsBlurEffect,
    QFileDialog, QScrollArea, QMessageBox
    , QCheckBox, QSplitter, QSplitterHandle
)
from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF, QPoint, QPropertyAnimation, QEasingCurve, pyqtProperty, pyqtSignal, \
    QAbstractAnimation, QSize, QRect, QEvent, QDate, QTime, QUrl, QRegularExpression
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QFontDatabase, QPixmap, QPalette, QDoubleValidator, QConicalGradient, QFontMetrics, QBrush, QKeyEvent, QCursor, QPainterPath, QGuiApplication, QTextCharFormat, QRadialGradient, QDesktopServices, QRegularExpressionValidator, QValidator, QIcon
from Core.constants.ui_constants import (
    FILE_BADGE_DRAWER_CLOSED_ARROW_TEXT,
    FILE_BADGE_DRAWER_OPEN_ARROW_TEXT,
    FILE_BADGE_EMPTY_HINT_TEMPLATE,
    FILE_BADGE_HEADER_TEMPLATE,
    FILE_BADGE_HINT_TEXT,
    FILE_BADGE_IMAGE_EXTENSIONS,
    FILE_BADGE_IMAGE_OPEN_ERROR_TEXT,
    FILE_BADGE_PREVIEW_TITLE,
)
from Feedback.processors.pipeline import Result, map_error_to_message


# ========================
# Rounded path helper

from .lock_badges import _init_disabled_lock_badge, _lock_on_disabled, _position_disabled_lock_badge, _set_lock_on_disabled, _sync_disabled_lock_badge
from .tables import GlowBadge

class FlowLayout(QLayout):
    def __init__(self, parent=None, margin: int = 0, spacing: int = 6):
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect, test_only: bool):
        x = rect.x()
        y = rect.y()
        line_height = 0
        space_x = self.spacing()
        space_y = self.spacing()
        available_width = max(1, rect.width() - 1)

        for item in self._items:
            hint = item.sizeHint()
            if hint.width() > available_width:
                # Long chips should stay inside visible bounds so the remove button remains reachable.
                hint.setWidth(available_width)
            next_x = x + hint.width() + space_x
            if next_x - space_x > rect.right() and line_height > 0:
                x = rect.x()
                y = y + line_height + space_y
                next_x = x + hint.width() + space_x
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPointF(x, y).toPoint(), hint))

            x = next_x
            line_height = max(line_height, hint.height())

        return y + line_height - rect.y()


# ========================
# FileBadgePicker (reusable)
# ========================
class _FileBadgeChip(QWidget):
    openRequested = pyqtSignal(str)
    removeRequested = pyqtSignal(str)

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self._path = path
        self._text = os.path.basename(path) or path
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(32)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._badge = GlowBadge(self._text, self)
        self._badge.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        badge_layout = self._badge.layout()
        if badge_layout is not None:
            badge_layout.setContentsMargins(8, 4, 24, 4)
        self._badge.clicked.connect(self._on_open_clicked)
        layout.addWidget(self._badge)

        self._remove = QToolButton(self)
        self._remove.setObjectName("FileBadgeRemove")
        self._remove.setText("\u2715")
        self._remove.setCursor(Qt.CursorShape.PointingHandCursor)
        self._remove.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._remove.clicked.connect(self._on_remove_clicked)
        self._remove.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        size = 17
        self._remove.setGeometry(self.width() - size - 2, 1, size, size)

    def _on_open_clicked(self, _text: str):
        self.openRequested.emit(self._path)

    def _on_remove_clicked(self):
        self.removeRequested.emit(self._path)


class FileBadgePicker(QWidget):
    filesChanged = pyqtSignal(list)
    fileActivated = pyqtSignal(str)

    def __init__(
            self,
            parent=None,
            *,
            button_text: str = "Dosya Seç",
            clear_text: str | None = None,
            dialog_title: str = "Dosya Seç",
            dialog_filter: str = "Tüm Dosyalar (*)",
            allow_multiple: bool = True,
            allowed_extensions: list[str] | None = None,
            show_clear_button: bool = False,
            open_on_click: bool = True
    ):
        super().__init__(parent)
        self._button_text = button_text or "Dosya Ekle"
        self._clear_text = clear_text or "Temizle"
        self._dialog_title = dialog_title or "Dosya Seç"
        self._dialog_filter = dialog_filter or "Tüm Dosyalar (*)"
        self._allow_multiple = bool(allow_multiple)
        self._show_clear_button = bool(show_clear_button)
        self._open_on_click = bool(open_on_click)
        self._files: list[str] = []
        self._allowed_exts: set[str] = set()
        self._image_exts = set(FILE_BADGE_IMAGE_EXTENSIONS)
        self._drawer_open = False
        self.setAllowedExtensions(allowed_extensions or [])

        self._header_button = QPushButton(FILE_BADGE_HEADER_TEMPLATE.format(count=0, arrow=FILE_BADGE_DRAWER_CLOSED_ARROW_TEXT))
        self._header_button.setObjectName("FileBadgeHeaderButton")
        self._header_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header_button.setMinimumHeight(40)
        self._header_button.setAutoDefault(False)
        self._header_button.setDefault(False)
        self._header_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._header_button.clicked.connect(self._on_header_clicked)

        self._clear_button = QToolButton(self)
        self._clear_button.setObjectName("FileBadgeClearButton")
        self._clear_button.setText(self._clear_text)
        self._clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._clear_button.clicked.connect(self.clearFiles)
        self._clear_button.setVisible(self._show_clear_button)
        self._clear_button.setMinimumHeight(30)

        self._pick_button = QPushButton(self._button_text)
        self._pick_button.setObjectName("FileBadgePickButton")
        self._pick_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pick_button.setMinimumHeight(30)
        self._pick_button.setAutoDefault(False)
        self._pick_button.setDefault(False)
        self._pick_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._pick_button.clicked.connect(self.openFileDialog)

        self._drawer = QFrame(self)
        self._drawer.setObjectName("FileBadgeDrawer")
        self._drawer.setVisible(False)
        self._drawer.setMinimumWidth(0)
        self._drawer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._hint = QLabel()
        self._hint.setObjectName("FileBadgeHint")

        self._badge_host = QWidget()
        self._badge_host.setMinimumWidth(0)
        self._badge_host.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._badge_layout = FlowLayout(self._badge_host, margin=0, spacing=6)

        self._badge_scroll = QScrollArea(self._drawer)
        self._badge_scroll.setObjectName("FileBadgeScroll")
        self._badge_scroll.setWidgetResizable(True)
        self._badge_scroll.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)
        self._badge_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._badge_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._badge_scroll.setWidget(self._badge_host)
        self._badge_scroll.setMinimumHeight(54)
        self._badge_scroll.setMaximumHeight(188)

        drawer_row = QVBoxLayout(self._drawer)
        drawer_row.setContentsMargins(8, 8, 8, 8)
        drawer_row.setSpacing(6)
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        action_row.addWidget(self._hint, 1)
        action_row.addWidget(self._pick_button, 0)
        if self._show_clear_button:
            action_row.addWidget(self._clear_button, 0)
        drawer_row.addLayout(action_row)
        drawer_row.addWidget(self._badge_scroll, 1)

        self._drawer_anim = QPropertyAnimation(self._drawer, b"maximumHeight", self)
        self._drawer_anim.setDuration(160)
        self._drawer_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._drawer_anim.valueChanged.connect(self._on_drawer_anim_value)
        self._drawer_anim.finished.connect(self._hide_drawer_if_closed)
        self._drawer.setMaximumHeight(0)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        root.addWidget(self._header_button)
        root.addWidget(self._drawer)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)

        self.setStyleSheet("""
            QPushButton#FileBadgeHeaderButton {
                border: 1px solid #CBD5E1;
                border-radius: 16px;
                color: #0F172A;
                font-size: 12px;
                font-weight: 700;
                text-align: center;
                padding: 8px 12px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #F8FAFC,
                    stop:1 #EEF2FF
                );
            }
            QPushButton#FileBadgeHeaderButton:hover {
                border-color: #93C5FD;
                background: #EFF6FF;
            }
            QPushButton#FileBadgeHeaderButton:pressed {
                border-color: #60A5FA;
                background: #DBEAFE;
            }
            QPushButton#FileBadgeHeaderButton:focus {
                outline: none;
            }
            QFrame#FileBadgeDrawer {
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 12px;
            }
            QLabel#FileBadgeHint {
                color: #475569;
                font-size: 11px;
                padding-left: 4px;
            }
            QPushButton#FileBadgePickButton, QToolButton#FileBadgeClearButton {
                border: 1px solid #DBEAFE;
                border-radius: 12px;
                background: #FFFFFF;
                color: #0F172A;
                padding: 5px 12px;
                font-size: 12px;
                font-weight: 700;
            }
            QPushButton#FileBadgePickButton:hover, QToolButton#FileBadgeClearButton:hover {
                border-color: #93C5FD;
            }
            QPushButton#FileBadgePickButton:pressed, QToolButton#FileBadgeClearButton:pressed {
                background: #EFF6FF;
                border-color: #60A5FA;
            }
            QPushButton#FileBadgePickButton:focus, QToolButton#FileBadgeClearButton:focus {
                outline: none;
            }
            QScrollArea#FileBadgeScroll {
                background: transparent;
                border: none;
                border-radius: 0px;
            }
            QToolButton#FileBadgeRemove {
                border: 1px solid #FECACA;
                border-radius: 8px;
                background: #FFFFFF;
                color: #DC2626;
                min-width: 17px;
                min-height: 17px;
                max-width: 17px;
                max-height: 17px;
                font-size: 9px;
                font-weight: 900;
            }
            QToolButton#FileBadgeRemove:hover {
                border-color: #EF4444;
                color: #B91C1C;
            }
            QToolButton#FileBadgeRemove:focus {
                outline: none;
            }
        """)
        _init_disabled_lock_badge(self)
        self._refresh_header()
        QTimer.singleShot(0, lambda: self._sync_height(0))

    def minimumSizeHint(self) -> QSize:
        # Keep horizontal minimum neutral so selected file names cannot push form columns.
        return QSize(0, self._base_height())

    def sizeHint(self) -> QSize:
        return self.minimumSizeHint()

    def files(self) -> list[str]:
        return list(self._files)

    def setFiles(self, paths: list[str], *, emit_signal: bool = True) -> None:
        clean: list[str] = []
        seen = set()
        for p in (paths or []):
            if not p:
                continue
            full = os.path.abspath(str(p))
            if full in seen:
                continue
            if self._allowed_exts and not self._is_allowed(full):
                continue
            seen.add(full)
            clean.append(full)
            if not self._allow_multiple:
                break
        self._files = clean
        self._rebuild_badges()
        self._refresh_header()
        if emit_signal:
            self.filesChanged.emit(self.files())

    def clearFiles(self) -> None:
        self.setFiles([], emit_signal=True)

    def setAllowedExtensions(self, extensions: list[str]) -> None:
        normalized = set()
        for ext in (extensions or []):
            token = (ext or "").strip().lower()
            if not token:
                continue
            if not token.startswith("."):
                token = f".{token}"
            normalized.add(token)
        self._allowed_exts = normalized

    def setDialogFilter(self, dialog_filter: str) -> None:
        self._dialog_filter = dialog_filter or "Tüm Dosyalar (*)"

    def openFileDialog(self) -> None:
        if self._allow_multiple:
            selected, _ = QFileDialog.getOpenFileNames(self, self._dialog_title, "", self._dialog_filter)
            if selected:
                if self._allow_multiple:
                    merged = self._files + [p for p in selected if p not in self._files]
                    self.setFiles(merged)
                else:
                    self.setFiles(selected[:1])
            return
        selected, _ = QFileDialog.getOpenFileName(self, self._dialog_title, "", self._dialog_filter)
        if selected:
            self.setFiles([selected])

    def _is_allowed(self, path: str) -> bool:
        if not self._allowed_exts:
            return True
        return os.path.splitext(path)[1].lower() in self._allowed_exts

    def _refresh_header(self) -> None:
        count = len(self._files)
        self._header_button.setText(
            FILE_BADGE_HEADER_TEMPLATE.format(
                count=count,
                arrow=FILE_BADGE_DRAWER_OPEN_ARROW_TEXT if self._drawer_open else FILE_BADGE_DRAWER_CLOSED_ARROW_TEXT,
            )
        )
        self._hint.setText(FILE_BADGE_HINT_TEXT)
        self._clear_button.setEnabled(count > 0)

    def _base_height(self) -> int:
        lay = self.layout()
        if lay is None:
            return int(self._header_button.sizeHint().height())
        margins = lay.contentsMargins()
        return int(margins.top() + margins.bottom() + self._header_button.sizeHint().height())

    def _sync_height(self, drawer_height: int | float) -> None:
        lay = self.layout()
        spacing = lay.spacing() if lay is not None else 0
        h = self._base_height()
        drawer_h = int(max(0, float(drawer_height)))
        if self._drawer_open or drawer_h > 0:
            h += int(spacing) + drawer_h
        h = max(h, int(self._header_button.minimumHeight()))
        if self.height() != h:
            self.setFixedHeight(h)
            self.updateGeometry()
            if lay is not None:
                lay.invalidate()

    def _on_drawer_anim_value(self, value) -> None:
        try:
            drawer_h = int(float(value))
        except Exception:
            drawer_h = int(self._drawer.maximumHeight())
        self._sync_height(drawer_h)
        self._ensure_visible()

    def _rebuild_badges(self) -> None:
        while self._badge_layout.count():
            item = self._badge_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for path in self._files:
            chip = _FileBadgeChip(path)
            chip.openRequested.connect(self._open_file)
            chip.removeRequested.connect(self._remove_file)
            self._badge_layout.addWidget(chip)

        if not self._files:
            hint = QLabel(FILE_BADGE_EMPTY_HINT_TEMPLATE.format(button_text=self._button_text))
            hint.setStyleSheet("color:#64748B;font-size:11px;padding:6px;")
            self._badge_layout.addWidget(hint)

    def _remove_file(self, path: str) -> None:
        next_files = [p for p in self._files if p != path]
        self.setFiles(next_files)

    def _on_header_clicked(self) -> None:
        if not self._files and not self._drawer_open:
            self.openFileDialog()
            return
        self._set_drawer_open(not self._drawer_open)

    def _set_drawer_open(self, is_open: bool) -> None:
        self._drawer_open = bool(is_open)
        self._refresh_header()
        self._drawer_anim.stop()
        if self._drawer_open:
            self._drawer.setVisible(True)
            self._sync_height(self._drawer.maximumHeight())
            self._drawer_anim.setStartValue(self._drawer.maximumHeight())
            self._drawer_anim.setEndValue(188)
            self._drawer_anim.start()
            QTimer.singleShot(0, self._ensure_visible)
            QTimer.singleShot(200, self._ensure_visible)
        else:
            start = self._drawer.maximumHeight()
            self._drawer_anim.setStartValue(start if start > 0 else 188)
            self._drawer_anim.setEndValue(0)
            self._drawer_anim.start()

    def _hide_drawer_if_closed(self) -> None:
        if not self._drawer_open:
            self._drawer.setVisible(False)
            self._sync_height(0)
        else:
            self._sync_height(self._drawer.maximumHeight())
            self._ensure_visible()

    def _ensure_visible(self) -> None:
        parent = self.parentWidget()
        while parent is not None and not isinstance(parent, QAbstractScrollArea):
            parent = parent.parentWidget()
        if parent is None:
            return
        if isinstance(parent, QScrollArea):
            parent.ensureWidgetVisible(self, 12, 12)
            return
        viewport = parent.viewport()
        if viewport is None:
            return
        try:
            top_left = self.mapTo(viewport, QPoint(0, 0))
        except Exception:
            return
        desired_bottom = top_left.y() + self.height()
        viewport_bottom = viewport.height()
        if desired_bottom > viewport_bottom:
            vbar = parent.verticalScrollBar()
            if vbar is not None:
                vbar.setValue(vbar.value() + (desired_bottom - viewport_bottom) + 12)

    def _open_file(self, path: str) -> None:
        self.fileActivated.emit(path)
        if not self._open_on_click or not path or not os.path.exists(path):
            return
        ext = os.path.splitext(path)[1].lower()
        if ext in self._image_exts:
            dlg = QDialog(self)
            dlg.setWindowTitle(os.path.basename(path) or FILE_BADGE_PREVIEW_TITLE)
            lay = QVBoxLayout(dlg)
            img = QLabel()
            img.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pix = QPixmap(path)
            if pix.isNull():
                img.setText(FILE_BADGE_IMAGE_OPEN_ERROR_TEXT)
            else:
                img.setPixmap(
                    pix.scaled(
                        900, 600,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                )
            lay.addWidget(img, 1)
            dlg.resize(920, 640)
            dlg.exec()
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def setEnabled(self, enabled: bool) -> None:
        super().setEnabled(enabled)
        _sync_disabled_lock_badge(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        _position_disabled_lock_badge(self)

    def showEvent(self, event):
        super().showEvent(event)
        _sync_disabled_lock_badge(self)

    def hideEvent(self, event):
        super().hideEvent(event)
        _sync_disabled_lock_badge(self)

    def setLockOnDisabled(self, enabled: bool) -> None:
        _set_lock_on_disabled(self, enabled)

    def lockOnDisabled(self) -> bool:
        return _lock_on_disabled(self)


# ========================
# SwitchSelectWidget (dropdown + search + switch items)
# ========================
