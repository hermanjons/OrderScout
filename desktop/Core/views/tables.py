from __future__ import annotations

from contextlib import contextmanager
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
    QAbstractAnimation, QSize, QRect, QEvent, QDate, QTime, QUrl, QRegularExpression, QSignalBlocker
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QFontDatabase, QPixmap, QPalette, QDoubleValidator, QConicalGradient, QFontMetrics, QBrush, QKeyEvent, QCursor, QPainterPath, QGuiApplication, QTextCharFormat, QRadialGradient, QDesktopServices, QRegularExpressionValidator, QValidator, QIcon
from Feedback.processors.pipeline import Result, map_error_to_message


# ========================
# Rounded path helper

@contextmanager
def optimized_table_updates(table: QTableWidget, row_count: int | None = None, *, block_signals: bool = True):
    """Batch QTableWidget mutations without per-cell repaints or sort churn."""
    updates_enabled = True
    sorting_enabled = False
    blocker = None
    try:
        updates_enabled = bool(table.updatesEnabled())
        sorting_enabled = bool(table.isSortingEnabled())
        if block_signals:
            blocker = QSignalBlocker(table)
        if sorting_enabled:
            table.setSortingEnabled(False)
        table.setUpdatesEnabled(False)
        if row_count is not None:
            table.setRowCount(max(0, int(row_count)))
        yield table
    finally:
        try:
            if sorting_enabled:
                table.setSortingEnabled(True)
            table.setUpdatesEnabled(updates_enabled)
        finally:
            del blocker

class GlowBadge(QWidget):
    clicked = pyqtSignal(str)

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._text = text
        self._raw_text = text
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._phase = 0.0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        self.label = QLabel(text)
        self.label.setStyleSheet("font-weight: 700; color: #0F172A;")
        self.label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.label)

        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        QTimer.singleShot(0, self._update_elided_text)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._text)
        super().mousePressEvent(event)

    def text(self) -> str:
        return self._raw_text

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_elided_text()

    def _update_elided_text(self) -> None:
        lay = self.layout()
        if lay is None:
            self.label.setText(self._raw_text)
            return
        margins = lay.contentsMargins()
        available = max(12, self.width() - margins.left() - margins.right())
        fm = QFontMetrics(self.label.font())
        self.label.setText(
            fm.elidedText(self._raw_text, Qt.TextElideMode.ElideRight, available)
        )

    def _tick(self) -> None:
        self._phase = (self._phase + 2.0) % 360.0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = self.rect().adjusted(1, 1, -1, -1)
        radius = rect.height() / 2

        # base pill
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(236, 253, 245))
        painter.drawRoundedRect(rect, radius, radius)

        # animated ring glow
        center = rect.center()
        grad = QConicalGradient(QPointF(center), self._phase)
        grad.setColorAt(0.00, QColor(16, 185, 129, 0))
        grad.setColorAt(0.20, QColor(16, 185, 129, 140))
        grad.setColorAt(0.50, QColor(59, 130, 246, 120))
        grad.setColorAt(0.80, QColor(16, 185, 129, 140))
        grad.setColorAt(1.00, QColor(16, 185, 129, 0))

        pen = QPen(QBrush(grad), 2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, radius, radius)


# ========================
# ExcelTableWidget
# ========================
class ExcelTableWidget(QTableWidget):
    """
    Excel-like table defaults:
    - Interactive column/row resizing
    - Hover highlight
    - Clean headers
    """
    def __init__(self, rows: int = 0, cols: int = 0, parent=None):
        super().__init__(rows, cols, parent)
        self.setMouseTracking(True)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.horizontalHeader().setStretchLastSection(False)
        # enable row resizing (needs vertical header visible)
        self.verticalHeader().setVisible(True)
        self.verticalHeader().setFixedWidth(28)
        self.verticalHeader().setDefaultSectionSize(28)
        self.horizontalHeader().setMinimumSectionSize(60)
        self.verticalHeader().setMinimumSectionSize(24)
        self.cellClicked.connect(self._expand_cell_to_fit)
        self._resize_col = -1
        self._resize_start_x = 0
        self._resize_start_w = 0
        self._resizing = False
        self.viewport().installEventFilter(self)
        self.setStyleSheet("""
        QTableWidget {
            gridline-color: rgba(15, 23, 42, 0.06);
        }
        QHeaderView::section {
            background: rgba(15, 23, 42, 0.05);
            border: 0px;
            padding: 8px 10px;
            font-weight: 900;
            color: rgba(15, 23, 42, 0.88);
        }
        QTableCornerButton::section {
            background: rgba(15, 23, 42, 0.05);
            border: 0px;
        }
        QTableWidget::item:hover {
            background: rgba(34, 197, 94, 0.10);
        }
        """)

    def _expand_cell_to_fit(self, row: int, col: int) -> None:
        item = self.item(row, col)
        if item is None:
            return
        text = item.text()
        if not text:
            return

        # Calculate needed size for full text (single-line)
        fm = QFontMetrics(item.font())
        text_width = fm.horizontalAdvance(text) + 22  # padding
        text_height = fm.height() + 12

        if text_width > self.columnWidth(col):
            self.setColumnWidth(col, text_width)
        if text_height > self.rowHeight(row):
            self.setRowHeight(row, text_height)

    def _hit_column_edge(self, x: int, threshold: int = 4) -> int:
        """Return column index if mouse is near a column edge inside the viewport."""
        for col in range(self.columnCount()):
            start = self.columnViewportPosition(col)
            width = self.columnWidth(col)
            edge = start + width
            if abs(x - edge) <= threshold:
                return col
        return -1

    def eventFilter(self, source, event):
        if source is self.viewport():
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                x = event.position().toPoint().x()
                col = self._hit_column_edge(x)
                if col != -1:
                    self._resize_col = col
                    self._resize_start_x = x
                    self._resize_start_w = self.columnWidth(col)
                    self._resizing = True
                    self.viewport().grabMouse()
                    self.viewport().setCursor(Qt.CursorShape.SplitHCursor)
                    return True

            if event.type() == QEvent.Type.MouseMove:
                x = event.position().toPoint().x()
                if self._resizing and self._resize_col != -1:
                    delta = x - self._resize_start_x
                    new_w = max(self.horizontalHeader().minimumSectionSize(), self._resize_start_w + delta)
                    self.setColumnWidth(self._resize_col, new_w)
                    return True

                if self._hit_column_edge(x) != -1:
                    self.viewport().setCursor(Qt.CursorShape.SplitHCursor)
                else:
                    self.viewport().setCursor(Qt.CursorShape.ArrowCursor)

            if event.type() == QEvent.Type.MouseButtonRelease:
                if self._resizing and self._resize_col != -1:
                    self._resize_col = -1
                    self._resizing = False
                    self.viewport().releaseMouse()
                    return True

        return super().eventFilter(source, event)
