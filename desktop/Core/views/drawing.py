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
from Feedback.processors.pipeline import Result, map_error_to_message


# ========================
# Rounded path helper

def _rounded_rect_path(rect: QRectF, radius: float, *, round_left: bool = True, round_right: bool = True) -> QPainterPath:
    r = max(0.0, min(radius, rect.width() / 2.0, rect.height() / 2.0))
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    path = QPainterPath()

    path.moveTo(x + (r if round_left else 0.0), y)

    if round_right:
        path.lineTo(x + w - r, y)
        path.quadTo(x + w, y, x + w, y + r)
        path.lineTo(x + w, y + h - r)
        path.quadTo(x + w, y + h, x + w - r, y + h)
    else:
        path.lineTo(x + w, y)
        path.lineTo(x + w, y + h)

    if round_left:
        path.lineTo(x + r, y + h)
        path.quadTo(x, y + h, x, y + h - r)
        path.lineTo(x, y + r)
        path.quadTo(x, y, x + r, y)
    else:
        path.lineTo(x, y + h)
        path.lineTo(x, y)

    path.closeSubpath()
    return path
