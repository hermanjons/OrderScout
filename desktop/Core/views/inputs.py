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
    QAbstractAnimation, QSize, QRect, QEvent, QDate, QTime, QUrl, QRegularExpression, QLocale
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QFontDatabase, QPixmap, QPalette, QDoubleValidator, QConicalGradient, QFontMetrics, QBrush, QKeyEvent, QCursor, QPainterPath, QGuiApplication, QTextCharFormat, QRadialGradient, QDesktopServices, QRegularExpressionValidator, QValidator, QIcon
from Core.constants.ui_constants import (
    PHONE_DEFAULT_DIAL_CODE,
    PHONE_FALLBACK_DIAL_CODES,
    PHONE_MAX_DIGITS,
    PHONE_MIN_DIGITS,
    PHONE_NUMBER_PLACEHOLDER,
)
from Feedback.processors.pipeline import Result, map_error_to_message


# ========================
# Rounded path helper

from .drawing import _rounded_rect_path
from .lock_badges import _init_disabled_lock_badge, _lock_on_disabled, _position_disabled_lock_badge, _set_lock_on_disabled, _sync_disabled_lock_badge

class AnimatedBorderLineEdit(QLineEdit):

    def __init__(self, parent=None, *, idle_glow: bool = False, joined: bool = False):
        super().__init__(parent)
        self._state = "idle"
        self._idle_glow = bool(idle_glow)
        self._joined = bool(joined)
        self._border_color = "#E5E7EB"
        self._apply_style(self._border_color)
        _init_disabled_lock_badge(self)

    def setState(self, state: str) -> None:
        state = (state or "").strip().lower()
        if state not in {"idle", "pending", "success", "error"}:
            state = "idle"
        self._state = state
        self._apply_style(self._current_color())

    def setInView(self, active: bool) -> None:
        # no-op: animation removed
        return

    def borderColor(self) -> str:
        return self._border_color

    def _current_color(self) -> str:
        if self._state == "success":
            return "#22C55E"
        if self._state == "error":
            return "#EF4444"
        if self._state == "pending":
            return "#E5E7EB"
        if self.hasFocus():
            return "#3B82F6"
        return "#E5E7EB"

    def _apply_style(self, color: str) -> None:
        self._border_color = color
        if self._state == "success":
            bg = "#ECFDF3"
        elif self._state == "error":
            bg = "#FEF2F2"
        else:
            bg = "#FFFFFF"
        if self._joined:
            self.setStyleSheet(
                "padding: 7px 10px; border-top-left-radius: 10px; border-bottom-left-radius: 10px; "
                "border-top-right-radius: 0px; border-bottom-right-radius: 0px; "
                f"border: 1px solid {color}; border-right: 0px; background: {bg};"
            )
        else:
            self.setStyleSheet(
                "padding: 7px 10px; border-radius: 10px; "
                f"border: 1px solid {color}; background: {bg};"
            )

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._apply_style(self._current_color())
        self._notify_parent()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self._apply_style(self._current_color())
        self._notify_parent()

    def _notify_parent(self) -> None:
        parent = self.parent()
        if parent is not None and hasattr(parent, "_sync_button_border"):
            try:
                parent._sync_button_border()
            except Exception:
                pass

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
# NumericPulseLineEdit
# ========================
class NumericPulseLineEdit(QLineEdit):
    """
    Numeric-only line edit with soft green glow on increasing values.
    - Accepts int/float
    - 0 or empty -> no glow
    """
    valueChanged = pyqtSignal(float)

    def __init__(self, parent=None, *, decimals: int = 3):
        super().__init__(parent)
        self._decimals = max(0, int(decimals))
        self._guard = False
        self._glow_enabled = True
        self._glow_color = QColor(34, 197, 94)
        self._glow_alpha_base = 80
        self._glow_alpha_range = 120
        self._glow_blur_base = 6.0
        self._glow_blur_range = 6.0
        self._glow_peak_extra = 8.0
        self._glow_peak_range = 4.0
        self._glow_intensity_divisor = 3.5

        self.setPlaceholderText("0")
        self.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

        validator = QDoubleValidator(0.0, 1e12, self._decimals, self)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        locale = QLocale(QLocale.Language.English, QLocale.Country.UnitedStates)
        locale.setNumberOptions(QLocale.NumberOption.RejectGroupSeparator)
        validator.setLocale(locale)
        self.setValidator(validator)

        self._glow = QGraphicsDropShadowEffect(self)
        self._glow.setOffset(0, 0)
        self._glow.setBlurRadius(0)
        self._glow.setColor(QColor(self._glow_color.red(), self._glow_color.green(), self._glow_color.blue(), 0))
        self.setGraphicsEffect(self._glow)

        self._anim = QPropertyAnimation(self._glow, b"blurRadius", self)
        self._anim.setDuration(420)
        self._anim.setEasingCurve(QEasingCurve.Type.OutQuad)

        self.textChanged.connect(self._on_text_changed)

    def _normalize_text(self, text: str) -> str:
        if "," in text:
            return text.replace(",", ".")
        return text

    def _parse_value(self) -> float:
        t = (self.text() or "").strip()
        if not t:
            return 0.0
        try:
            return float(t)
        except Exception:
            return 0.0

    def _intensity(self, value: float) -> float:
        if value <= 0:
            return 0.0
        return min(1.0, math.log10(value + 1) / max(0.1, self._glow_intensity_divisor))

    def _pulse(self, value: float) -> None:
        if not self._glow_enabled:
            return
        intensity = self._intensity(value)
        if intensity <= 0.0:
            self._glow.setBlurRadius(0)
            self._glow.setColor(QColor(self._glow_color.red(), self._glow_color.green(), self._glow_color.blue(), 0))
            return

        alpha = int(self._glow_alpha_base + intensity * self._glow_alpha_range)
        base = self._glow_blur_base + intensity * self._glow_blur_range
        peak = base + self._glow_peak_extra + intensity * self._glow_peak_range

        self._glow.setColor(QColor(self._glow_color.red(), self._glow_color.green(), self._glow_color.blue(), alpha))
        self._anim.stop()
        self._anim.setStartValue(base)
        self._anim.setEndValue(peak)
        self._anim.start()

    def _on_text_changed(self, text: str) -> None:
        if self._guard:
            return
        fixed = self._normalize_text(text)
        if fixed != text:
            self._guard = True
            self.setText(fixed)
            self._guard = False
            return

        value = self._parse_value()
        self.valueChanged.emit(value)
        self._pulse(value)

    def value(self) -> float:
        return self._parse_value()

    def has_value(self) -> bool:
        return bool((self.text() or "").strip())

    def setValue(self, value: float | None) -> None:
        if value is None:
            self.setText("")
            return
        fmt = f"{{:.{self._decimals}f}}".format(float(value))
        fmt = fmt.rstrip("0").rstrip(".") if "." in fmt else fmt
        self.setText(fmt)

    def setGlowEnabled(self, enabled: bool) -> None:
        self._glow_enabled = bool(enabled)
        if not self._glow_enabled:
            try:
                self._anim.stop()
            except Exception:
                pass
            self.setGraphicsEffect(None)
        else:
            if self.graphicsEffect() is None:
                self.setGraphicsEffect(self._glow)
            self._pulse(self._parse_value())

    def setGlowColor(self, color: QColor | str) -> None:
        next_color = QColor(color) if not isinstance(color, QColor) else QColor(color)
        if not next_color.isValid():
            return
        self._glow_color = next_color
        self._pulse(self._parse_value())

    def setGlowProfile(
        self,
        *,
        alpha_base: int | None = None,
        alpha_range: int | None = None,
        blur_base: float | None = None,
        blur_range: float | None = None,
        peak_extra: float | None = None,
        peak_range: float | None = None,
        intensity_divisor: float | None = None,
    ) -> None:
        if alpha_base is not None:
            self._glow_alpha_base = max(0, int(alpha_base))
        if alpha_range is not None:
            self._glow_alpha_range = max(0, int(alpha_range))
        if blur_base is not None:
            self._glow_blur_base = max(0.0, float(blur_base))
        if blur_range is not None:
            self._glow_blur_range = max(0.0, float(blur_range))
        if peak_extra is not None:
            self._glow_peak_extra = max(0.0, float(peak_extra))
        if peak_range is not None:
            self._glow_peak_range = max(0.0, float(peak_range))
        if intensity_divisor is not None:
            self._glow_intensity_divisor = max(0.1, float(intensity_divisor))
        self._pulse(self._parse_value())


class CurrencyPulseLineEdit(NumericPulseLineEdit):
    def __init__(self, parent=None, *, decimals: int = 2):
        super().__init__(parent, decimals=decimals)
        self._group_separator = "."
        self._decimal_separator = ","
        self.setValidator(QRegularExpressionValidator(QRegularExpression(r"^[0-9.,]*$"), self))

    def _group_digits(self, digits: str) -> str:
        raw = "".join(ch for ch in str(digits or "") if ch.isdigit())
        if not raw:
            return ""
        chunks: list[str] = []
        while raw:
            chunks.append(raw[-3:])
            raw = raw[:-3]
        return self._group_separator.join(reversed(chunks))

    def _normalize_text(self, text: str) -> str:
        raw = "".join(ch for ch in str(text or "").strip() if ch.isdigit() or ch in ".,")
        if not raw:
            return ""

        integer_part = raw
        decimal_part = ""
        if self._decimal_separator in raw:
            integer_part, decimal_part = raw.split(self._decimal_separator, 1)

        integer_digits = "".join(ch for ch in integer_part if ch.isdigit())
        decimal_digits = "".join(ch for ch in decimal_part if ch.isdigit())[: self._decimals]

        has_decimal = self._decimal_separator in raw

        if integer_digits:
            integer_digits = integer_digits.lstrip("0") or "0"
        elif decimal_digits or has_decimal:
            integer_digits = "0"

        grouped_integer = self._group_digits(integer_digits)
        if has_decimal:
            return f"{grouped_integer or '0'}{self._decimal_separator}{decimal_digits}"
        return grouped_integer

    def _parse_value(self) -> float:
        text = str(self.text() or "").strip()
        if not text:
            return 0.0
        normalized = text.replace(self._group_separator, "").replace(self._decimal_separator, ".")
        try:
            return float(normalized)
        except Exception:
            return 0.0

    def setValue(self, value: float | None) -> None:
        if value is None:
            self.setText("")
            return
        numeric = float(value)
        fmt = f"{{:.{self._decimals}f}}".format(numeric)
        fmt = fmt.rstrip("0").rstrip(".") if "." in fmt else fmt
        integer_part, dot, decimal_part = fmt.partition(".")
        grouped_integer = self._group_digits(integer_part)
        if dot and decimal_part:
            self.setText(f"{grouped_integer}{self._decimal_separator}{decimal_part}")
            return
        self.setText(grouped_integer)


class CurrencyAmountInput(QWidget):
    textChanged = pyqtSignal(str)
    currencyChanged = pyqtSignal(str)

    def __init__(
        self,
        parent=None,
        *,
        decimals: int = 2,
        currency: str = "TRY",
        placeholder: str = "0",
        badge_min_width: int = 76,
        badge_max_width: int = 92,
        spacing: int = 8,
    ):
        super().__init__(parent)
        self._outer_pad_x = 4
        self._outer_pad_y = 4
        self.setObjectName("CurrencyAmountInput")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(
            """
            QWidget#CurrencyAmountInput {
                background: transparent;
            }
            QWidget#CurrencyAmountInput QLineEdit#CurrencyAmountField {
                border: 1px solid #E7D39A;
                border-radius: 16px;
                background: #FFFDF7;
                color: #B7791F;
                font-weight: 700;
                padding: 8px 14px;
            }
            QWidget#CurrencyAmountInput QLineEdit#CurrencyAmountField:focus {
                border: 1px solid #E4BE52;
                background: #FFFDF3;
            }
            QLabel#CurrencyAmountBadge {
                border: 1px solid #c7d7f3;
                border-radius: 16px;
                background: #f6f9ff;
                color: #143a7a;
                font-weight: 700;
                padding: 0 10px;
            }
            """
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(self._outer_pad_x, self._outer_pad_y, self._outer_pad_x, self._outer_pad_y)
        layout.setSpacing(max(6, int(spacing)))

        self._line_edit = CurrencyPulseLineEdit(self, decimals=decimals)
        self._line_edit.setObjectName("CurrencyAmountField")
        self._line_edit.setPlaceholderText(str(placeholder or "0"))
        self._line_edit.setGlowColor("#E0A106")
        self._line_edit.setGlowProfile(
            alpha_base=125,
            alpha_range=145,
            blur_base=9,
            blur_range=5,
            peak_extra=12,
            peak_range=6,
            intensity_divisor=42.0,
        )
        self._line_edit.textChanged.connect(self.textChanged.emit)
        layout.addWidget(self._line_edit, 1)

        self._currency_label = QLabel(str(currency or "TRY").strip().upper() or "TRY", self)
        self._currency_label.setObjectName("CurrencyAmountBadge")
        self._currency_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._currency_label.setMinimumHeight(42)
        self._currency_label.setMinimumWidth(max(52, int(badge_min_width)))
        self._currency_label.setMaximumWidth(max(self._currency_label.minimumWidth(), int(badge_max_width)))
        layout.addWidget(self._currency_label, 0)
        _init_disabled_lock_badge(self)

    def setMinimumHeight(self, h: int) -> None:
        super().setMinimumHeight(h)
        target = max(24, int(h) - (self._outer_pad_y * 2))
        self._line_edit.setMinimumHeight(target)
        self._currency_label.setMinimumHeight(target)
        _position_disabled_lock_badge(self)

    def setFixedHeight(self, h: int) -> None:
        super().setFixedHeight(h)
        target = max(24, int(h) - (self._outer_pad_y * 2))
        self._line_edit.setFixedHeight(target)
        self._currency_label.setFixedHeight(target)
        _position_disabled_lock_badge(self)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        _position_disabled_lock_badge(self)

    def setPlaceholderText(self, text: str) -> None:
        self._line_edit.setPlaceholderText(str(text or ""))

    def placeholderText(self) -> str:
        return self._line_edit.placeholderText()

    def setText(self, text: str) -> None:
        self._line_edit.setText(str(text or ""))

    def text(self) -> str:
        return self._line_edit.text()

    def clear(self) -> None:
        self._line_edit.clear()

    def setValue(self, value: float | None) -> None:
        self._line_edit.setValue(value)

    def value(self) -> float:
        return self._line_edit.value()

    def has_value(self) -> bool:
        return self._line_edit.has_value()

    def setGlowEnabled(self, enabled: bool) -> None:
        self._line_edit.setGlowEnabled(enabled)

    def setEnabled(self, enabled: bool) -> None:
        super().setEnabled(enabled)
        self._line_edit.setEnabled(enabled)
        self._currency_label.setEnabled(enabled)
        _sync_disabled_lock_badge(self)

    def setLockOnDisabled(self, enabled: bool) -> None:
        _set_lock_on_disabled(self, enabled)

    def lockOnDisabled(self) -> bool:
        return _lock_on_disabled(self)

    def lineEdit(self) -> NumericPulseLineEdit:
        return self._line_edit

    def setCurrency(self, currency: str) -> None:
        code = str(currency or "TRY").strip().upper() or "TRY"
        self._currency_label.setText(code)
        self.currencyChanged.emit(code)

    def currency(self) -> str:
        return str(self._currency_label.text() or "").strip().upper() or "TRY"

    def badgeLabel(self) -> QLabel:
        return self._currency_label


class PercentageValueValidator(QValidator):
    def __init__(self, *, decimals: int = 2, parent=None):
        super().__init__(parent)
        self._decimals = max(0, int(decimals))

    def validate(self, input_str: str, pos: int):
        raw = str(input_str or "")
        text = raw.strip()
        if text == "":
            return (QValidator.State.Intermediate, input_str, pos)

        normalized = text.replace(",", ".")
        if normalized.count(".") > 1:
            return (QValidator.State.Invalid, input_str, pos)

        if normalized.startswith("."):
            normalized = f"0{normalized}"

        if normalized.endswith("."):
            head = normalized[:-1]
            if head == "":
                return (QValidator.State.Intermediate, input_str, pos)
            try:
                value = float(head)
            except Exception:
                return (QValidator.State.Invalid, input_str, pos)
            state = QValidator.State.Intermediate if 0.0 <= value <= 100.0 else QValidator.State.Invalid
            return (state, input_str, pos)

        parts = normalized.split(".")
        if len(parts) == 2 and len(parts[1]) > self._decimals:
            return (QValidator.State.Invalid, input_str, pos)

        try:
            value = float(normalized)
        except Exception:
            return (QValidator.State.Invalid, input_str, pos)

        if 0.0 <= value <= 100.0:
            return (QValidator.State.Acceptable, input_str, pos)
        return (QValidator.State.Invalid, input_str, pos)


class PercentageProgressLineEdit(NumericPulseLineEdit):
    """
    Percentage-only numeric input with a green progress border.
    The border progress follows the entered percentage:
    50 -> half perimeter, 100 -> full perimeter.
    """

    def __init__(self, parent=None, *, decimals: int = 2):
        super().__init__(parent, decimals=decimals)
        self._progress_color = QColor("#22C55E")
        self._track_color = QColor(203, 213, 225, 92)
        self._border_pen_width = 2.35
        self._corner_radius = 10.0
        self.setPlaceholderText("0-100")

        self.setValidator(PercentageValueValidator(decimals=self._decimals, parent=self))

        self.textChanged.connect(lambda _text="": self.update())

    @staticmethod
    def _clamp_percentage(value: float) -> float:
        try:
            numeric = float(value)
        except Exception:
            return 0.0
        return max(0.0, min(100.0, numeric))

    def _parse_value(self) -> float:
        return self._clamp_percentage(super()._parse_value())

    def progressRatio(self) -> float:
        if not self.has_value():
            return 0.0
        return self._parse_value() / 100.0

    def setValue(self, value: float) -> None:
        if value is None:
            self.setText("")
            return
        super().setValue(self._clamp_percentage(value))

    @staticmethod
    def _path_percent_at_length(path: QPainterPath, length: float) -> float:
        total = float(path.length() or 0.0)
        if total <= 0:
            return 0.0
        target = max(0.0, min(total, float(length)))
        try:
            return float(path.percentAtLength(target))
        except Exception:
            return max(0.0, min(1.0, target / total))

    @classmethod
    def _partial_border_path(cls, path: QPainterPath, ratio: float) -> QPainterPath:
        progress = max(0.0, min(1.0, float(ratio)))
        if progress <= 0.0:
            return QPainterPath()
        if progress >= 0.9999:
            return path

        total = float(path.length() or 0.0)
        if total <= 0:
            return QPainterPath()
        target_len = total * progress
        steps = max(20, int(math.ceil(target_len / 5.0)))
        partial = QPainterPath()
        for step in range(steps + 1):
            current_len = target_len * (step / steps)
            percent = cls._path_percent_at_length(path, current_len)
            point = path.pointAtPercent(percent)
            if step == 0:
                partial.moveTo(point)
            else:
                partial.lineTo(point)
        return partial

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        ratio = self.progressRatio()
        if ratio <= 0.0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        rect = QRectF(self.rect()).adjusted(1.4, 1.4, -1.4, -1.4)
        if rect.width() <= 4 or rect.height() <= 4:
            return

        border_path = _rounded_rect_path(rect, self._corner_radius)
        progress_path = self._partial_border_path(border_path, ratio)
        if progress_path.isEmpty():
            return

        track_pen = QPen(self._track_color, self._border_pen_width)
        track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        track_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(track_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(progress_path)

        progress_pen = QPen(self._progress_color, self._border_pen_width)
        progress_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        progress_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(progress_pen)
        painter.drawPath(progress_path)


class CircularPercentageInput(QWidget):
    textChanged = pyqtSignal(str)
    editingFinished = pyqtSignal()

    def __init__(self, parent=None, *, decimals: int = 2, diameter: int = 118):
        super().__init__(parent)
        self._decimals = max(0, int(decimals))
        self._diameter = max(84, int(diameter))
        self._track_color = QColor(203, 213, 225, 170)
        self._progress_color = QColor("#22C55E")
        self._fill_color = QColor("#FFFFFF")
        self._ring_width = 7.0
        self._value_validator = PercentageValueValidator(decimals=self._decimals, parent=self)

        self.setObjectName("CircularPercentageInput")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setMinimumSize(self._diameter, self._diameter)
        self.setMaximumSize(self._diameter, self._diameter)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            """
            QWidget#CircularPercentageInput {
                background: transparent;
            }
            QWidget#CircularPercentageInput QLineEdit {
                border: none;
                background: transparent;
                color: #0F172A;
                font-size: 20px;
                font-weight: 800;
                padding: 0;
            }
            QWidget#CircularPercentageInput QLineEdit:disabled {
                color: #94A3B8;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(0)

        self._line_edit = QLineEdit(self)
        self._line_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._line_edit.setPlaceholderText("0")
        self._line_edit.setValidator(self._value_validator)
        self._line_edit.textChanged.connect(self._on_text_changed)
        self._line_edit.editingFinished.connect(self.editingFinished.emit)
        layout.addStretch(1)
        layout.addWidget(self._line_edit, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)
        _init_disabled_lock_badge(self)

    def _on_text_changed(self, text: str) -> None:
        self.textChanged.emit(str(text or ""))
        self.update()

    def lineEdit(self) -> QLineEdit:
        return self._line_edit

    def validator(self) -> QValidator | None:
        return self._line_edit.validator()

    def setValidator(self, validator: QValidator) -> None:
        self._line_edit.setValidator(validator)

    def setPlaceholderText(self, text: str) -> None:
        self._line_edit.setPlaceholderText(str(text or ""))

    def placeholderText(self) -> str:
        return self._line_edit.placeholderText()

    def setText(self, text: str) -> None:
        self._line_edit.setText(str(text or ""))

    def text(self) -> str:
        return self._line_edit.text()

    def clear(self) -> None:
        self._line_edit.clear()

    def setFocus(self, reason: Qt.FocusReason = Qt.FocusReason.OtherFocusReason) -> None:
        self._line_edit.setFocus(reason)

    def selectAll(self) -> None:
        self._line_edit.selectAll()

    def setReadOnly(self, read_only: bool) -> None:
        self._line_edit.setReadOnly(bool(read_only))

    def setEnabled(self, enabled: bool) -> None:
        super().setEnabled(enabled)
        self._line_edit.setEnabled(enabled)
        _sync_disabled_lock_badge(self)
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        _position_disabled_lock_badge(self)

    def setLockOnDisabled(self, enabled: bool) -> None:
        _set_lock_on_disabled(self, enabled)

    def lockOnDisabled(self) -> bool:
        return _lock_on_disabled(self)

    def setDiameter(self, diameter: int) -> None:
        self._diameter = max(84, int(diameter))
        self.setMinimumSize(self._diameter, self._diameter)
        self.setMaximumSize(self._diameter, self._diameter)
        self.updateGeometry()
        self.update()

    @staticmethod
    def _clamp_percentage(value: float) -> float:
        try:
            numeric = float(value)
        except Exception:
            return 0.0
        return max(0.0, min(100.0, numeric))

    def has_value(self) -> bool:
        return str(self.text() or "").strip() != ""

    def value(self) -> float:
        text = str(self.text() or "").strip()
        if not text:
            return 0.0
        normalized = text.replace(",", ".")
        try:
            return self._clamp_percentage(float(normalized))
        except Exception:
            return 0.0

    def setValue(self, value: float | None) -> None:
        if value is None:
            self.clear()
            return
        clamped = self._clamp_percentage(value)
        if float(clamped).is_integer():
            self.setText(str(int(clamped)))
            return
        self.setText(f"{clamped:.{self._decimals}f}".rstrip("0").rstrip("."))

    def progressRatio(self) -> float:
        if not self.has_value():
            return 0.0
        return self.value() / 100.0

    def sizeHint(self) -> QSize:
        return QSize(self._diameter, self._diameter)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def mousePressEvent(self, event) -> None:
        self._line_edit.setFocus()
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(self.rect()).adjusted(6, 6, -6, -6)
        if rect.width() <= 0 or rect.height() <= 0:
            return

        inner_rect = rect.adjusted(self._ring_width, self._ring_width, -self._ring_width, -self._ring_width)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._fill_color)
        painter.drawEllipse(inner_rect)

        track_pen = QPen(self._track_color, self._ring_width)
        track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(rect)

        ratio = self.progressRatio()
        if ratio > 0.0:
            progress_pen = QPen(self._progress_color, self._ring_width)
            progress_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(progress_pen)
            painter.drawArc(rect, 90 * 16, int(-360 * 16 * ratio))

class NumericRangeGlowInput(QWidget):
    rangeChanged = pyqtSignal(float, float)

    def __init__(
        self,
        parent=None,
        *,
        decimals: int = 2,
        left_placeholder: str = "İlk değer",
        right_placeholder: str = "İkinci değer",
    ):
        super().__init__(parent)
        self.setObjectName("NumericRangeGlowInput")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._glow_color = QColor(34, 197, 94)
        self.setStyleSheet(
            """
            QWidget#NumericRangeGlowInput {
                background: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 12px;
            }
            QLineEdit#RangePart {
                border: none;
                background: transparent;
                padding: 8px 10px;
                min-height: 24px;
                color: #0F172A;
            }
            QLabel#RangeDash {
                color: #64748B;
                font-size: 16px;
                font-weight: 800;
                padding: 0 2px;
            }
            """
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        self._left_edit = NumericPulseLineEdit(self, decimals=decimals)
        self._left_edit.setObjectName("RangePart")
        self._left_edit.setPlaceholderText(left_placeholder or "")
        self._left_edit.setGlowEnabled(False)
        layout.addWidget(self._left_edit, 1)

        self._dash_label = QLabel("—", self)
        self._dash_label.setObjectName("RangeDash")
        self._dash_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._dash_label.setMinimumWidth(14)
        layout.addWidget(self._dash_label, 0)

        self._right_edit = NumericPulseLineEdit(self, decimals=decimals)
        self._right_edit.setObjectName("RangePart")
        self._right_edit.setPlaceholderText(right_placeholder or "")
        self._right_edit.setGlowEnabled(False)
        layout.addWidget(self._right_edit, 1)

        self._glow = QGraphicsDropShadowEffect(self)
        self._glow.setOffset(0, 0)
        self._glow.setBlurRadius(0)
        self._glow.setColor(QColor(self._glow_color.red(), self._glow_color.green(), self._glow_color.blue(), 0))
        self.setGraphicsEffect(self._glow)

        self._left_edit.valueChanged.connect(self._on_values_changed)
        self._right_edit.valueChanged.connect(self._on_values_changed)

    def _range_span(self) -> float:
        if not self._left_edit.has_value() or not self._right_edit.has_value():
            return 0.0
        return abs(self._right_edit.value() - self._left_edit.value())

    def _sync_glow(self) -> None:
        span = self._range_span()
        if span <= 0:
            self._glow.setBlurRadius(0)
            self._glow.setColor(QColor(34, 197, 94, 0))
            return
        intensity = min(1.0, math.log10(span + 1) / 3.5)
        alpha = int(70 + intensity * 130)
        blur = 8 + intensity * 16
        self._glow.setColor(QColor(self._glow_color.red(), self._glow_color.green(), self._glow_color.blue(), alpha))
        self._glow.setBlurRadius(blur)

    def _on_values_changed(self, *_args) -> None:
        self._sync_glow()
        self.rangeChanged.emit(self.leftValue(), self.rightValue())

    def setMinimumHeight(self, h: int) -> None:
        super().setMinimumHeight(h)
        inner_height = max(0, int(h) - 8)
        self._left_edit.setMinimumHeight(inner_height)
        self._right_edit.setMinimumHeight(inner_height)

    def leftEdit(self) -> NumericPulseLineEdit:
        return self._left_edit

    def rightEdit(self) -> NumericPulseLineEdit:
        return self._right_edit

    def leftText(self) -> str:
        return self._left_edit.text()

    def rightText(self) -> str:
        return self._right_edit.text()

    def leftValue(self) -> float:
        return self._left_edit.value()

    def rightValue(self) -> float:
        return self._right_edit.value()

    def setValues(self, left_value: float | None, right_value: float | None) -> None:
        self._left_edit.setValue(left_value)
        self._right_edit.setValue(right_value)
        self._sync_glow()

    def clear(self) -> None:
        self._left_edit.clear()
        self._right_edit.clear()
        self._sync_glow()



class PhoneNumberInput(QWidget):
    """
    Dial code + numeric local number input.
    - Local part accepts digits only.
    - Public value is normalized as: +<code><digits>
    """

    textChanged = pyqtSignal(str)

    def __init__(
            self,
            parent=None,
            *,
            dial_codes: list[str] | None = None,
            default_code: str = PHONE_DEFAULT_DIAL_CODE,
            number_placeholder: str = PHONE_NUMBER_PLACEHOLDER,
            max_digits: int = PHONE_MAX_DIGITS,
    ):
        super().__init__(parent)
        self._max_digits = max(PHONE_MIN_DIGITS, min(20, int(max_digits or PHONE_MAX_DIGITS)))
        self._height = 40
        self._dial_codes = self._normalize_dial_codes(dial_codes or [default_code, *PHONE_FALLBACK_DIAL_CODES])

        if not self._dial_codes:
            self._dial_codes = [PHONE_DEFAULT_DIAL_CODE]

        self._code_combo = QComboBox(self)
        self._code_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContentsOnFirstShow)
        self._code_combo.addItems(self._dial_codes)
        self._code_combo.setCurrentText(self._resolve_code(default_code))
        self._code_combo.setMinimumContentsLength(max(len(code) for code in self._dial_codes))
        self._code_combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        fm = QFontMetrics(self._code_combo.font())
        code_text_w = fm.horizontalAdvance(max(self._dial_codes, key=len))
        combo_w = max(124, min(154, code_text_w + 78))
        self._code_combo.setFixedWidth(combo_w)
        self._code_combo.setMinimumWidth(combo_w)
        self._code_combo.setStyleSheet(
            "QComboBox { padding-left: 8px; padding-right: 20px; background: #FFFFFF; }"
            "QComboBox::drop-down { width: 18px; }"
        )
        self._code_combo.setFixedHeight(self._height)
        self._code_combo.setEditable(False)
        self._code_combo.setMaxVisibleItems(min(12, max(4, len(self._dial_codes))))

        self._code_combo_view = QListView(self._code_combo)
        self._code_combo_view.setObjectName("PhoneDialCodePopup")
        self._code_combo_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._code_combo_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._code_combo_view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._code_combo_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._code_combo_view.setUniformItemSizes(True)
        self._code_combo_view.setSpacing(2)
        self._code_combo_view.setAutoFillBackground(True)
        self._code_combo_view.viewport().setAutoFillBackground(True)
        popup_palette = self._code_combo_view.palette()
        popup_palette.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
        popup_palette.setColor(QPalette.ColorRole.Text, QColor("#0F172A"))
        popup_palette.setColor(QPalette.ColorRole.Highlight, QColor("#DBEAFE"))
        popup_palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#1D4ED8"))
        self._code_combo_view.setPalette(popup_palette)
        self._code_combo_view.setStyleSheet(
            """
            QListView#PhoneDialCodePopup {
                background: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 12px;
                padding: 4px;
                outline: none;
                color: #0F172A;
            }
            QListView#PhoneDialCodePopup::item {
                min-height: 30px;
                padding: 6px 10px;
                border-radius: 8px;
            }
            QListView#PhoneDialCodePopup::item:hover {
                background: #EFF6FF;
            }
            QListView#PhoneDialCodePopup::item:selected {
                background: #DBEAFE;
                color: #1D4ED8;
            }
            """
        )
        self._code_combo.setView(self._code_combo_view)

        self._number_edit = QLineEdit(self)
        self._number_edit.setPlaceholderText(str(number_placeholder or PHONE_NUMBER_PLACEHOLDER))
        self._number_edit.setClearButtonEnabled(True)
        self._number_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._number_edit.setMinimumWidth(0)
        self._number_edit.setFixedHeight(self._height)
        self._number_edit.setMaxLength(self._max_digits)
        pattern = QRegularExpression(rf"\d{{0,{self._max_digits}}}")
        self._number_edit.setValidator(QRegularExpressionValidator(pattern, self._number_edit))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._code_combo, 0)
        layout.addWidget(self._number_edit, 1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)
        self.setFixedHeight(self._height)

        self._code_combo.currentIndexChanged.connect(lambda _i: self.textChanged.emit(self.text()))
        self._number_edit.textChanged.connect(lambda _t: self.textChanged.emit(self.text()))

    @staticmethod
    def _normalize_dial_codes(values: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for raw in values:
            code = str(raw or "").strip()
            if not code:
                continue
            if code.startswith("00"):
                code = "+" + code[2:]
            if not code.startswith("+"):
                code = "+" + code.lstrip("+")
            code = "+" + "".join(ch for ch in code[1:] if ch.isdigit())
            if len(code) <= 1:
                continue
            if code in seen:
                continue
            seen.add(code)
            out.append(code)
        out.sort(key=lambda x: (len(x), x))
        return out

    def _resolve_code(self, code: str) -> str:
        norm = self._normalize_dial_codes([code])
        if norm and norm[0] in self._dial_codes:
            return norm[0]
        return self._dial_codes[0]

    def _split_phone(self, value: str) -> tuple[str, str]:
        raw = str(value or "").strip()
        if not raw:
            return self._code_combo.currentText(), ""

        cleaned = "".join(ch for ch in raw if ch.isdigit() or ch == "+")
        if cleaned.startswith("00"):
            cleaned = "+" + cleaned[2:]
        if not cleaned.startswith("+"):
            digits_only = "".join(ch for ch in cleaned if ch.isdigit())
            return self._code_combo.currentText(), digits_only[:self._max_digits]

        digits = "+" + "".join(ch for ch in cleaned[1:] if ch.isdigit())
        sorted_codes = sorted(self._dial_codes, key=len, reverse=True)
        for code in sorted_codes:
            if digits.startswith(code):
                local = "".join(ch for ch in digits[len(code):] if ch.isdigit())
                return code, local[:self._max_digits]

        prefix = "+" + "".join(ch for ch in digits[1:4] if ch.isdigit())
        local = "".join(ch for ch in digits[len(prefix):] if ch.isdigit()) if len(prefix) > 1 else ""
        return self._resolve_code(prefix), local[:self._max_digits]

    def clear(self) -> None:
        self._number_edit.clear()
        self.textChanged.emit(self.text())

    def is_empty(self) -> bool:
        return not bool((self._number_edit.text() or "").strip())

    def text(self) -> str:
        number = "".join(ch for ch in (self._number_edit.text() or "") if ch.isdigit())
        if not number:
            return ""
        return f"{self._code_combo.currentText()}{number}"

    def setText(self, value: str | None) -> None:
        code, local = self._split_phone(str(value or ""))
        idx = self._code_combo.findText(code)
        if idx >= 0:
            self._code_combo.setCurrentIndex(idx)
        self._number_edit.setText(local)
        self.textChanged.emit(self.text())

    def value(self) -> str | None:
        txt = self.text()
        return txt if txt else None

    def setValue(self, value: str | None) -> None:
        self.setText(value)

    def setPlaceholderText(self, text: str) -> None:
        self._number_edit.setPlaceholderText(str(text or ""))

    def currentDialCode(self) -> str:
        return str(self._code_combo.currentText() or "")

    def setCurrentDialCode(self, code: str) -> None:
        target = self._resolve_code(code)
        idx = self._code_combo.findText(target)
        if idx >= 0:
            self._code_combo.setCurrentIndex(idx)

# ========================
# FlowLayout (wrap)
# ========================
