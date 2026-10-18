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

class SplitterHandleWithReset(QSplitterHandle):
    def __init__(self, orientation: Qt.Orientation, splitter: QSplitter):
        super().__init__(orientation, splitter)
        self.setCursor(
            Qt.CursorShape.SplitHCursor
            if orientation == Qt.Orientation.Horizontal
            else Qt.CursorShape.SplitVCursor
        )
        self.setToolTip("Sürükle: paneli aç/kapat • Çift tıkla: sıfırla")
        self._pulse_phase = 0.0
        self._hovered = False
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(80)
        self._pulse_timer.timeout.connect(self._on_pulse_tick)

    def _reset(self):
        splitter = self.splitter()
        if splitter:
            splitter.setSizes([620, 920])

    def _on_pulse_tick(self):
        if not self.isVisible() or not self._hovered:
            return
        self._pulse_phase += 0.24
        if self._pulse_phase >= math.tau:
            self._pulse_phase -= math.tau
        self.update()

    def enterEvent(self, event):
        self._hovered = True
        if not self._pulse_timer.isActive():
            self._pulse_timer.start()
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        if self._pulse_timer.isActive():
            self._pulse_timer.stop()
        self.update()
        super().leaveEvent(event)

    def mouseDoubleClickEvent(self, event):
        self._reset()
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pulse = (math.sin(self._pulse_phase) + 1.0) / 2.0
        line_alpha = int(95 + pulse * 45) if self._hovered else 95

        if self.orientation() == Qt.Orientation.Horizontal:
            center_x = self.width() // 2
            painter.setPen(QPen(QColor(148, 163, 184, line_alpha), 2))
            painter.drawLine(center_x, 8, center_x, max(8, self.height() - 8))
        else:
            center_y = self.height() // 2
            painter.setPen(QPen(QColor(148, 163, 184, line_alpha), 2))
            painter.drawLine(8, center_y, max(8, self.width() - 8), center_y)

        dot_alpha = int(170 + pulse * 45) if self._hovered else 160
        painter.setBrush(QColor(120, 129, 150, dot_alpha))
        painter.setPen(Qt.PenStyle.NoPen)
        cx = self.width() // 2
        cy = self.height() // 2
        radius = 2
        gap = 6
        for i in (-1, 0, 1):
            painter.drawEllipse(cx - radius, cy + i * gap - radius, radius * 2, radius * 2)


class ResettableSplitter(QSplitter):
    def __init__(self, orientation: Qt.Orientation, parent: QWidget | None = None):
        super().__init__(orientation, parent)
        super().setHandleWidth(10)

    def createHandle(self):
        return SplitterHandleWithReset(self.orientation(), self)

    def setHandleWidth(self, width: int):
        super().setHandleWidth(max(10, int(width or 0)))


class ListLoadingOverlay(QWidget):
    """
    Reusable loading overlay for list widgets.
    - Blurs the target list while busy, or fully suppresses its content.
    - Shows animated circular loader + message.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        target: QWidget | None = None,
        blur_radius: float = 5.5,
        message: str = "Yukleniyor...",
        hide_target_content_while_busy: bool = False,
    ):
        super().__init__(parent)
        self._target: QWidget | None = None
        self._message = str(message or "Yukleniyor...")
        self._blur_radius = max(0.0, float(blur_radius))
        self._hide_target_content_while_busy = bool(hide_target_content_while_busy)
        self._busy = False
        self._spinner_phase = 0.0
        self._blur_effect: QGraphicsBlurEffect | None = None
        self._opacity_effect: QGraphicsOpacityEffect | None = None
        self._prev_effect = None
        self._target_updates_were_enabled: bool | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._tick)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(False)
        self.hide()
        if target is not None:
            self.set_target(target)

    @staticmethod
    def _is_qobject_alive(obj: object | None) -> bool:
        if obj is None:
            return False
        try:
            # QObject API call raises RuntimeError if wrapped C++ object was deleted.
            getattr(obj, "objectName")()
            return True
        except Exception:
            return False

    def _live_target(self) -> QWidget | None:
        if self._is_qobject_alive(self._target):
            return self._target
        self._target = None
        self._blur_effect = None
        self._opacity_effect = None
        self._prev_effect = None
        return None

    def set_target(self, target: QWidget | None) -> None:
        if target is self._target:
            return
        if self._busy:
            self._remove_target_effect()
        if isinstance(target, QWidget) and self._is_qobject_alive(target):
            self._target = target
        else:
            self._target = None
        if self._busy:
            self._apply_target_effect()
        self.sync_geometry()

    def set_busy(self, busy: bool, *, message: str | None = None) -> None:
        if message is not None:
            text = str(message or "").strip()
            if text:
                self._message = text
        desired = bool(busy)
        if desired == self._busy:
            if self._busy:
                self.sync_geometry()
                self.raise_()
                self.update()
            return
        self._busy = desired
        if self._busy:
            self._spinner_phase = 0.0
            self._apply_target_effect()
            self.sync_geometry()
            self.show()
            self.raise_()
            if not self._timer.isActive():
                self._timer.start()
            self.update()
            return
        if self._timer.isActive():
            self._timer.stop()
        self._remove_target_effect()
        self.hide()
        self.update()

    def is_busy(self) -> bool:
        return bool(self._busy)

    def sync_geometry(self) -> None:
        target = self._live_target()
        if target is None or self.parentWidget() is None:
            if self._busy:
                self.hide()
            return
        host = self.parentWidget()
        rect = target.geometry().adjusted(1, 1, -1, -1)
        rect = rect.intersected(host.rect())
        if rect.width() <= 2 or rect.height() <= 2:
            if self._busy:
                self.hide()
            return
        self.setGeometry(rect)
        if self._busy:
            self.show()
            self.raise_()

    def _apply_target_effect(self) -> None:
        if self._hide_target_content_while_busy:
            self._apply_content_suppression()
            return
        self._apply_blur()

    def _apply_blur(self) -> None:
        target = self._live_target()
        if target is None:
            return
        try:
            current = target.graphicsEffect()
        except Exception:
            self._target = None
            self._blur_effect = None
            self._prev_effect = None
            return

        if not self._is_qobject_alive(self._blur_effect):
            self._blur_effect = None
        if self._blur_effect is None:
            self._blur_effect = QGraphicsBlurEffect(target)
            self._blur_effect.setBlurHints(QGraphicsBlurEffect.BlurHint.QualityHint)
        if current is not self._blur_effect:
            self._prev_effect = current

        try:
            self._blur_effect.setBlurRadius(self._blur_radius)
            target.setGraphicsEffect(self._blur_effect)
        except Exception:
            # Target/effect may have been destroyed between checks.
            self._blur_effect = None
            self._opacity_effect = None
            self._prev_effect = None

    def _apply_content_suppression(self) -> None:
        target = self._live_target()
        if target is None:
            return
        try:
            if self._target_updates_were_enabled is None:
                self._target_updates_were_enabled = bool(target.updatesEnabled())
            target.setUpdatesEnabled(False)
        except Exception:
            self._target = None
            self._opacity_effect = None
            self._target_updates_were_enabled = None

    def _remove_target_effect(self) -> None:
        target = self._live_target()
        if target is None:
            self._prev_effect = None
            self._blur_effect = None
            self._opacity_effect = None
            self._target_updates_were_enabled = None
            return
        if self._target_updates_were_enabled is not None:
            try:
                target.setUpdatesEnabled(bool(self._target_updates_were_enabled))
            except Exception:
                pass
            self._target_updates_were_enabled = None
        try:
            current = target.graphicsEffect()
        except Exception:
            self._prev_effect = None
            self._blur_effect = None
            self._opacity_effect = None
            return

        prev_effect = self._prev_effect if self._is_qobject_alive(self._prev_effect) else None
        active_overlay_effects = []
        if self._is_qobject_alive(self._blur_effect):
            active_overlay_effects.append(self._blur_effect)
        if self._is_qobject_alive(self._opacity_effect):
            active_overlay_effects.append(self._opacity_effect)
        if active_overlay_effects and current in active_overlay_effects:
            try:
                target.setGraphicsEffect(prev_effect)
            except Exception:
                pass
        self._prev_effect = None

    def _tick(self) -> None:
        self._spinner_phase = (self._spinner_phase + 18.0) % 360.0
        spinner_rect = self._spinner_update_rect()
        self.update(spinner_rect if spinner_rect.isValid() else self.rect())

    def _spinner_update_rect(self) -> QRect:
        rect = self.rect().adjusted(2, 2, -2, -2)
        if rect.width() <= 0 or rect.height() <= 0:
            return QRect()
        cx = rect.center().x()
        cy = rect.center().y() - 8
        return QRect(cx - 24, cy - 24, 48, 48).intersected(self.rect())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setClipRect(event.rect())
        rect = self.rect().adjusted(2, 2, -2, -2)
        if rect.width() <= 0 or rect.height() <= 0:
            return

        painter.setPen(Qt.PenStyle.NoPen)
        background_alpha = 238 if self._hide_target_content_while_busy else 165
        painter.setBrush(QColor(248, 250, 252, background_alpha))
        painter.drawRoundedRect(rect, 12, 12)

        cx = rect.center().x()
        cy = rect.center().y() - 8
        radius_outer = 16
        radius_inner = 10
        for i in range(12):
            alpha = 30 + int((225 * (i + 1)) / 12)
            pen = QPen(QColor(37, 99, 235, alpha), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            angle = math.radians(float(self._spinner_phase + i * 30.0))
            x1 = cx + math.cos(angle) * radius_inner
            y1 = cy + math.sin(angle) * radius_inner
            x2 = cx + math.cos(angle) * radius_outer
            y2 = cy + math.sin(angle) * radius_outer
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        if self._message:
            painter.setPen(QColor("#1E293B"))
            painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            text_rect = rect.adjusted(10, 34, -10, -8)
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                self._message,
            )
# ========================
