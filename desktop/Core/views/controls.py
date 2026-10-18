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
    QAbstractAnimation, QSize, QRect, QEvent, QDate, QTime, QUrl, QRegularExpression, QSignalBlocker
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QFontDatabase, QPixmap, QPalette, QDoubleValidator, QConicalGradient, QFontMetrics, QBrush, QKeyEvent, QCursor, QPainterPath, QGuiApplication, QTextCharFormat, QRadialGradient, QDesktopServices, QRegularExpressionValidator, QValidator, QIcon
from Feedback.processors.pipeline import Result, map_error_to_message


# ========================
# Rounded path helper

from .drawing import _rounded_rect_path
from .lock_badges import _init_disabled_lock_badge, _lock_on_disabled, _position_disabled_lock_badge, _set_lock_on_disabled, _sync_disabled_lock_badge

_DECORATIVE_FONT_FAMILY_CACHE: str | None = None
_PIXMAP_CACHE_LIMIT = 160
_PIXMAP_CACHE: dict[tuple[str, int, int], QPixmap] = {}
_SCALED_PIXMAP_CACHE: dict[tuple[str, int, int, int, int], QPixmap] = {}


def _pixmap_signature(path: str | os.PathLike | None) -> tuple[str, int, int] | None:
    raw = str(path or "").strip()
    if not raw:
        return None
    try:
        stat = os.stat(raw)
        return (raw, int(stat.st_mtime_ns), int(stat.st_size))
    except Exception:
        return (raw, -1, -1)


def _cached_pixmap(path: str | os.PathLike | None) -> QPixmap | None:
    signature = _pixmap_signature(path)
    if signature is None:
        return None
    cached = _PIXMAP_CACHE.get(signature)
    if cached is not None:
        return cached
    pixmap = QPixmap(signature[0])
    if len(_PIXMAP_CACHE) >= _PIXMAP_CACHE_LIMIT:
        _PIXMAP_CACHE.clear()
        _SCALED_PIXMAP_CACHE.clear()
    _PIXMAP_CACHE[signature] = pixmap
    return pixmap


def _cached_scaled_pixmap(path: str | os.PathLike | None, width: int, height: int) -> QPixmap | None:
    signature = _pixmap_signature(path)
    if signature is None:
        return None
    key = (*signature, int(width), int(height))
    cached = _SCALED_PIXMAP_CACHE.get(key)
    if cached is not None:
        return cached
    pixmap = _cached_pixmap(signature[0])
    if pixmap is None or pixmap.isNull():
        return pixmap
    scaled = pixmap.scaled(
        int(width),
        int(height),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    if len(_SCALED_PIXMAP_CACHE) >= _PIXMAP_CACHE_LIMIT:
        _SCALED_PIXMAP_CACHE.clear()
    _SCALED_PIXMAP_CACHE[key] = scaled
    return scaled


def clear_control_pixmap_cache() -> None:
    _PIXMAP_CACHE.clear()
    _SCALED_PIXMAP_CACHE.clear()

class PackageButton(QAbstractButton):
    """
    Sipariş Paketi görünümünde özel buton.
    Hem ikon hem başlık içerir. Hover'da animasyon ve parlama efekti verir.
    """

    clicked = pyqtSignal()

    def __init__(
            self,
            text="Siparişler",
            icon_path=None,
            bg_color="#f0f0f0",
            border_color="#999999",
            hover_color="#e0ffe0",
            radius=12,
            parent=None
    ):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(200, 80)

        self._hover_progress = 0.0
        self._text = text
        self._icon = _cached_pixmap(icon_path)
        self._bg_color = QColor(bg_color)
        self._border_color = QColor(border_color)
        self._hover_color = QColor(hover_color)
        self._radius = radius

        self._is_hovered = False
        self._anim = QPropertyAnimation(self, b"hover_progress", self)
        self._anim.setDuration(250)
        self._anim.setEasingCurve(QEasingCurve.Type.OutQuad)

    def enterEvent(self, event):
        try:
            self._is_hovered = True
            self._anim.stop()
            self._anim.setStartValue(self._hover_progress)
            self._anim.setEndValue(1.0)
            self._anim.start()
        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    def leaveEvent(self, event):
        try:
            self._is_hovered = False
            self._anim.stop()
            self._anim.setStartValue(self._hover_progress)
            self._anim.setEndValue(0.0)
            self._anim.start()
        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, event):
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            rect = self.rect().adjusted(1, 1, -1, -1)
            bg = QColor(self._bg_color)
            if self._is_hovered:
                bg = self._bg_color.lighter(100 + int(20 * self._hover_progress))

            painter.setBrush(bg)
            painter.setPen(QPen(self._border_color, 1))
            painter.drawRoundedRect(rect, self._radius, self._radius)

            if self._icon:
                icon_size = 36
                icon_x = 20
                icon_y = (self.height() - icon_size) // 2
                painter.drawPixmap(icon_x, icon_y, icon_size, icon_size, self._icon)

            font = QFont()
            font.setPointSize(11)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor("#333333"))

            text_x = 70 if self._icon else 20
            text_y = self.height() // 2 + 5
            painter.drawText(QPointF(text_x, text_y), self._text)

        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    def get_hover_progress(self):
        return self._hover_progress

    def set_hover_progress(self, value):
        self._hover_progress = value
        self.update()

    hover_progress = pyqtProperty(float, fget=get_hover_progress, fset=set_hover_progress)


# ========================
# ListSmartItemWidget
# ========================

# ========================
# BadgeButton
# ========================
class BadgeButton(QAbstractButton):
    """
    Badge-enabled action button with:
    - left icon area + right text area (split by divider)
    - optional badge on top-right
    - animated glow ring when active
    """

    def __init__(
            self,
            text="İlanlar",
            icon_path=None,
            *,
            icon_size: int = 44,
            badge_count: int = 0,
            badge_text: str | None = None,
            badge_color: str | QColor | None = None,
            badge_text_color: str | QColor | None = None,
            font_size: int | None = None,
            radius: int = 14,
            base_w: int = 230,
            base_h: int = 90,
            min_w: int = 120,
            min_h: int = 60,
            left_w: int = 70,
            badge_r: int = 11,
            badge_font: int = 8,
            badge_offset_x: int = 0,
            badge_offset_y: int = 0,
            center_text: bool = False,
            show_divider: bool = True,
            size_scale: float = 1.0,
            parent=None,
    ):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._base_w = int(base_w or 230)
        self._base_h = int(base_h or 90)
        self._min_w = int(min_w or 120)
        self._min_h = int(min_h or 60)
        self._base_left_w = int(left_w or 0)
        self._base_radius = int(radius or 14)
        self._base_icon_size = int(icon_size or 44)
        self._base_font_size = int(font_size or 11)
        self._base_badge_r = int(badge_r or 11)
        self._base_badge_font = int(badge_font or 8)
        self._base_glow_pen = 5
        self._size_scale = float(size_scale or 1.0)

        self._text = text
        self._icon = _cached_pixmap(icon_path)
        self._icon_size = self._base_icon_size
        self._radius = self._base_radius
        self._left_w = self._base_left_w
        self._font_size = self._base_font_size
        self._badge_r = self._base_badge_r
        self._badge_font = self._base_badge_font
        self._glow_pen_w = self._base_glow_pen
        self._badge_count = int(badge_count or 0)
        self._badge_text = (badge_text or "").strip() or None
        self._badge_bg = QColor(badge_color) if badge_color else QColor("#EF4444")
        self._badge_fg = QColor(badge_text_color) if badge_text_color else QColor("#FFFFFF")
        self._active = False
        self._phase = 0.0
        self._center_text = bool(center_text)
        self._show_divider = bool(show_divider)
        self._badge_offset_x = int(badge_offset_x or 0)
        self._badge_offset_y = int(badge_offset_y or 0)

        self._apply_size_scale()

        self._glow_timer = QTimer(self)
        self._glow_timer.setInterval(90)
        self._glow_timer.timeout.connect(self._tick_glow)

    def _has_badge(self) -> bool:
        return bool(self._badge_text) or int(self._badge_count or 0) > 0

    def _sync_glow_timer(self) -> None:
        should_run = bool(self._active and self._has_badge() and self.isVisible())
        if should_run:
            if not self._glow_timer.isActive():
                self._glow_timer.start()
        else:
            if self._glow_timer.isActive():
                self._glow_timer.stop()

    def showEvent(self, event):
        self._sync_glow_timer()
        super().showEvent(event)

    def hideEvent(self, event):
        if self._glow_timer.isActive():
            self._glow_timer.stop()
        super().hideEvent(event)

    def _apply_size_scale(self) -> None:
        try:
            scale = max(0.6, min(2.5, float(self._size_scale)))
            self._size_scale = scale
            w = max(self._min_w, int(self._base_w * scale))
            h = max(self._min_h, int(self._base_h * scale))
            self.setFixedSize(w, h)
            self._icon_size = max(16, int(self._base_icon_size * scale))
            self._radius = max(8, int(self._base_radius * scale))
            self._left_w = max(0, int(self._base_left_w * scale))
            self._font_size = max(9, int(self._base_font_size * scale))
            self._badge_r = max(8, int(self._base_badge_r * scale))
            self._badge_font = max(7, int(self._base_badge_font * scale))
            self._glow_pen_w = max(3, int(self._base_glow_pen * scale))
            self.update()
        except Exception:
            pass

    def setSizeScale(self, scale: float) -> None:
        self._size_scale = float(scale or 1.0)
        self._apply_size_scale()

    def setBadgeCount(self, count: int) -> None:
        self._badge_count = max(0, int(count or 0))
        self._sync_glow_timer()
        self.update()

    def setBadgeText(self, text: str | None) -> None:
        self._badge_text = (text or "").strip() or None
        self._sync_glow_timer()
        self.update()

    def setBadgeColor(self, color: str | QColor | None) -> None:
        self._badge_bg = QColor(color) if color else QColor("#EF4444")
        self.update()

    def setBadgeTextColor(self, color: str | QColor | None) -> None:
        self._badge_fg = QColor(color) if color else QColor("#FFFFFF")
        self.update()

    def setActive(self, active: bool) -> None:
        self._active = bool(active)
        self._sync_glow_timer()
        self.update()

    def setText(self, text: str) -> None:
        self._text = text or ""
        self.update()

    def setCenterText(self, enabled: bool) -> None:
        self._center_text = bool(enabled)
        self.update()

    def setShowDivider(self, enabled: bool) -> None:
        self._show_divider = bool(enabled)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        rect = self.rect().adjusted(1, 1, -1, -1)
        badge_text = self._badge_text
        if not badge_text and self._badge_count > 0:
            badge_text = str(self._badge_count) if self._badge_count < 100 else "99+"
        badge_pad = 0
        if badge_text:
            badge_pad = self._badge_r * 2 + 10

        # glow ring
        if self._active:
            center = QPointF(rect.center())
            grad = QConicalGradient(center, self._phase)
            has_badge = bool(self._badge_text) or self._badge_count > 0
            ring = QColor("#38BDF8") if has_badge else QColor("#22C55E")
            grad.setColorAt(0.00, QColor(ring.red(), ring.green(), ring.blue(), 0))
            grad.setColorAt(0.18, QColor(ring.red(), ring.green(), ring.blue(), 190))
            grad.setColorAt(0.50, QColor(ring.red(), ring.green(), ring.blue(), 255))
            grad.setColorAt(0.82, QColor(ring.red(), ring.green(), ring.blue(), 190))
            grad.setColorAt(1.00, QColor(ring.red(), ring.green(), ring.blue(), 0))
            painter.setPen(QPen(QBrush(grad), self._glow_pen_w))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), self._radius + 4, self._radius + 4)

        # base
        painter.setBrush(QColor("#F8FAFC"))
        painter.setPen(QPen(QColor("#CBD5E1"), 1))
        painter.drawRoundedRect(rect, self._radius, self._radius)

        # divider
        left_w = self._left_w
        divider_x = rect.left() + left_w
        if self._show_divider and left_w > 0:
            painter.setPen(QPen(QColor("#E2E8F0"), 1))
            div_pad = max(6, int(10 * self._size_scale))
            painter.drawLine(divider_x, rect.top() + div_pad, divider_x, rect.bottom() - div_pad)

        # icon
        if self._icon and not self._icon.isNull():
            icon_x = rect.left() + (left_w - self._icon_size) // 2
            icon_y = rect.center().y() - self._icon_size // 2
            painter.drawPixmap(icon_x, icon_y, self._icon_size, self._icon_size, self._icon)

        # text
        painter.setPen(QColor("#0F172A"))
        font = QFont()
        font.setPointSize(self._font_size)
        font.setBold(True)
        painter.setFont(font)
        if self._center_text:
            pad = max(8, int(10 * self._size_scale))
            text_rect = rect.adjusted(pad, 0, -pad, 0)
            align = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignCenter
        else:
            if self._icon and not self._icon.isNull() and left_w > 0:
                text_rect = QRect(
                    divider_x + 8,
                    rect.top(),
                    rect.width() - divider_x - 12 - badge_pad,
                    rect.height(),
                )
            else:
                pad = max(8, int(10 * self._size_scale))
                text_rect = rect.adjusted(pad, 0, -pad - badge_pad, 0)
            align = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        painter.drawText(text_rect, align, self._text)

        # badge
        if badge_text:
            badge_r = self._badge_r
            badge_rect = QRect(
                rect.right() - badge_r * 2 - 6 + self._badge_offset_x,
                rect.top() + 6 + self._badge_offset_y,
                badge_r * 2,
                badge_r * 2,
            )
            painter.setBrush(self._badge_bg)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(badge_rect)
            painter.setPen(self._badge_fg)
            font = QFont()
            font.setPointSize(self._badge_font)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)

    def _tick_glow(self) -> None:
        if not self._active or not self.isVisible():
            self._sync_glow_timer()
            return
        self._phase = (self._phase + 6.0) % 360.0
        self.update()

class ListSmartItemWidget(QWidget):
    """
    Kart görünümünde çok amaçlı liste öğesi.
    """

    interaction = pyqtSignal(str, object)  # (identifier, value)
    selectionRequested = pyqtSignal(QWidget)

    def __init__(
            self,
            title: str,
            identifier: str = None,
            subtitle: str = None,
            extra: str = None,
            icon_path: str = None,
            optional_widget: QWidget = None,
            *,
            icon_size: int = 28,
            show_icon_placeholder: bool = False,
            min_height: int | None = None
    ):
        super().__init__()
        try:
            self.identifier = identifier or title
            self._hover = False
            self._selected = False
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self._icon_size = max(0, int(icon_size))

            # Title'ın tam halini sakla (ellipsis öncesi)
            self._full_title_text = title or ""

            layout = QHBoxLayout(self)
            layout.setContentsMargins(12, 8, 12, 8)
            layout.setSpacing(12)

            # Sol: Icon
            if icon_path or show_icon_placeholder:
                self.icon = QLabel()
                if icon_path:
                    pixmap = _cached_scaled_pixmap(icon_path, self._icon_size, self._icon_size)
                    if pixmap is not None:
                        self.icon.setPixmap(pixmap)
                self.icon.setFixedSize(self._icon_size, self._icon_size)
                layout.addWidget(self.icon, alignment=Qt.AlignmentFlag.AlignTop)
            else:
                self.icon = None

            # Orta: Metinler
            text_layout = QVBoxLayout()
            text_layout.setSpacing(2)

            # Title – genişliğe göre ... ile kısaltılacak
            self.label_title = QLabel()
            self.label_title.setStyleSheet("font-weight: bold; font-size: 14px; color: #222;")
            self.label_title.setWordWrap(False)
            self.label_title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            text_layout.addWidget(self.label_title)

            self.label_subtitle = None
            if subtitle:
                self.label_subtitle = QLabel(subtitle)
                self.label_subtitle.setStyleSheet("color: #444; font-size: 12px;")
                self.label_subtitle.setWordWrap(False)
                self.label_subtitle.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                text_layout.addWidget(self.label_subtitle)

            self.label_extra = None
            if extra:
                self.label_extra = QLabel(extra)
                self.label_extra.setStyleSheet("color: #666; font-size: 12px;")
                self.label_extra.setWordWrap(False)
                self.label_extra.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                text_layout.addWidget(self.label_extra)

            layout.addLayout(text_layout, stretch=1)

            # Sağ: Opsiyonel widget (SwitchButton vb.)
            self.right_widget = optional_widget
            if self.right_widget:
                self.right_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
                layout.addWidget(
                    self.right_widget,
                    alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                self._connect_right_widget()

            # Shadow / background – senin aynısı
            self._shadow = QGraphicsDropShadowEffect(self)
            self._shadow.setBlurRadius(12)
            self._shadow.setXOffset(0)
            self._shadow.setYOffset(2)
            self._shadow.setColor(QColor(0, 0, 0, 50))
            self.setGraphicsEffect(self._shadow)
            self._shadow.setEnabled(False)

            self.setAutoFillBackground(True)
            self._apply_background("#ffffff")

            # Başlangıçta title'ı elide ederek göster
            self._update_elided_title()
            if min_height is not None:
                self.setMinimumHeight(int(min_height))

        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    # =========================================================
    # Sağdaki widget bağlantıları (aynı)
    # =========================================================
    def _connect_right_widget(self):
        if hasattr(self.right_widget, "clicked"):
            self.right_widget.clicked.connect(self._on_right_widget_clicked)
        if hasattr(self.right_widget, "stateChanged"):
            self.right_widget.stateChanged.connect(self._on_right_widget_state_changed)

    def _on_right_widget_clicked(self, value):
        self.interaction.emit(self.identifier, value)

    def _on_right_widget_state_changed(self, state):
        self.interaction.emit(self.identifier, state)

    # =========================================================
    # Etkileşim / seçim (aynı)
    # =========================================================
    def mousePressEvent(self, event):
        if self.right_widget and self.right_widget.geometry().contains(event.pos()):
            return super().mousePressEvent(event)
        self._selected = True
        self.update_style()
        self.selectionRequested.emit(self)
        super().mousePressEvent(event)

    def set_selected(self, selected: bool):
        self._selected = selected
        self.update_style()

    def enterEvent(self, event):
        self._hover = True
        self.update_style()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update_style()
        super().leaveEvent(event)

    # =========================================================
    # Arka plan / stil (aynen)
    # =========================================================
    def _apply_background(self, hex_color: str):
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(hex_color))
        self.setPalette(pal)

    def update_style(self):
        self.update()

    # =========================================================
    # Title'ı ellipsis ile kısaltma
    # =========================================================
    def _update_elided_title(self):
        """
        Title label'ın mevcut genişliğine göre metni '...' ile kısalt.
        Burada sadece label'ın kendi genişliğini kullanıyoruz ki
        widget ve item genişliğini şişirmesin.
        """
        if not self.label_title:
            return

        fm = self.label_title.fontMetrics()
        avail = self.label_title.width()

        # İlk seferde width 0 gelebilir; layout oturunca tekrar deneriz
        if avail <= 0:
            QTimer.singleShot(0, self._update_elided_title)
            return

        # Biraz güvenlik payı
        if avail < 50:
            avail = 50

        elided = fm.elidedText(
            self._full_title_text,
            Qt.TextElideMode.ElideRight,
            int(avail)
        )
        self.label_title.setText(elided)

    def resizeEvent(self, event):
        """
        Widget yeniden boyutlanınca ellipsis'i güncelle.
        """
        super().resizeEvent(event)
        self._update_elided_title()

    # =========================================================
    # sizeHint: genişliği sabit tut → yatay taşma olmasın
    # =========================================================
    def sizeHint(self):
        """
        QListWidgetItem genişliğini şişirmemek için width'i küçük döndürüyoruz.
        Yükseklik super'dan alınır, genişliği QListWidget viewport'una uyduruyor.
        """
        base = super().sizeHint()
        return QSize(10, base.height())

    # =========================================================
    # Paint (senin kodun)
    # =========================================================
    def paintEvent(self, event):
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            base_color = QColor("#ffffff")
            hover_color = QColor("#fafafa")
            selected_color = QColor("#f0f6ff")

            if self._selected:
                bg = selected_color
                border = QColor("#3399ff")
                border_width = 2
            elif self._hover:
                bg = hover_color
                border = QColor("#cccccc")
                border_width = 1
            else:
                bg = base_color
                border = QColor(Qt.GlobalColor.transparent)
                border_width = 0

            rect = self.rect()
            painter.setBrush(bg)
            painter.setPen(QPen(border, border_width))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 6, 6)

            super().paintEvent(event)

        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))



# ========================
# CircularProgressButton
# ========================


class CircularProgressButton(QPushButton):
    started = pyqtSignal()
    finished = pyqtSignal()
    scaleChanged = pyqtSignal(float)

    def __init__(self, text="Başlat", parent=None, *, size_scale: float = 1.0, repeat_interval: int | None = None):
        try:
            super().__init__(text, parent)

            self._progress = 0
            self._is_running = False
            self._running_text = ""
            self._auto_reset_on_complete = True
            self._scale = 1.0
            self._base_size = 120
            self._size_scale = float(size_scale or 1.0)
            self._label_font_size = 10
            self._progress_font_size = 20
            self._badge_font_size = 8
            self._ring_pen_w = 6
            self._badge_fixed_w = None

            self.default_color = QColor("#3498db")  # normal mavi
            self.running_color = QColor("#2ecc71")  # çalışırken yeşil
            self.text_color = QColor("white")
            self._apply_size_scale()
            self.setCursor(Qt.CursorShape.PointingHandCursor)

            # font
            self.progress_font_family = self._pick_decorative_font()
            self.progress_font_base = QFont(self.progress_font_family, self._label_font_size, QFont.Weight.Black)
            self.progress_font_base.setStretch(100)

            # ölçek animasyonu
            self._scale_anim = QPropertyAnimation(self, b"scale")
            self._scale_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

            # repeat (auto trigger) support
            self._repeat_enabled = False
            self._repeat_interval = 0
            self._repeat_remaining = 0
            self._repeat_timer = QTimer(self)
            self._repeat_timer.setInterval(1000)
            self._repeat_timer.timeout.connect(self._tick_repeat)

            self._rotation = 0.0
            self._badge_pulse = 0.0
            self._pulse_t = 0.0
            self._spin_timer = QTimer(self)
            self._spin_timer.setInterval(40)
            self._spin_timer.timeout.connect(self._tick_spin)

            if repeat_interval is not None:
                self.setRepeatInterval(int(repeat_interval))
        except Exception as e:
            Result.fail(map_error_to_message(e), error=e)

    def _apply_size_scale(self):
        try:
            scale = max(0.6, min(2.5, float(self._size_scale)))
            self._size_scale = scale
            size = max(60, int(self._base_size * scale))
            self.setFixedSize(size, size)
            self._label_font_size = max(9, int(10 * scale))
            self._progress_font_size = max(14, int(20 * scale))
            self._badge_font_size = max(8, int(8 * scale))
            self._ring_pen_w = max(4, int(6 * scale))
            self.setFont(QFont("Segoe UI", self._label_font_size, QFont.Weight.Bold))
            self._badge_fixed_w = None
            try:
                self.progress_font_base.setPointSize(self._label_font_size)
            except Exception:
                pass
        except Exception as e:
            Result.fail(map_error_to_message(e), error=e)

    def setSizeScale(self, scale: float):
        self._size_scale = float(scale or 1.0)
        self._apply_size_scale()
        self.update()

    # ----------------
    def _pick_decorative_font(self) -> str:
        global _DECORATIVE_FONT_FAMILY_CACHE
        if _DECORATIVE_FONT_FAMILY_CACHE:
            return _DECORATIVE_FONT_FAMILY_CACHE
        try:
            prefer = ["Orbitron", "Russo One", "Digital-7", "Bahnschrift SemiBold"]
            available = QFontDatabase.families()
            for fam in prefer:
                if fam in available:
                    _DECORATIVE_FONT_FAMILY_CACHE = fam
                    return fam
            _DECORATIVE_FONT_FAMILY_CACHE = "Segoe UI"
            return _DECORATIVE_FONT_FAMILY_CACHE
        except Exception as e:
            Result.fail(map_error_to_message(e), error=e)
            _DECORATIVE_FONT_FAMILY_CACHE = "Segoe UI"
            return "Segoe UI"

    # ----------------
    def getScale(self) -> float:
        return self._scale

    def setScale(self, value: float):
        try:
            if self._scale == value:
                return
            self._scale = value
            self.scaleChanged.emit(value)
            self.update()
        except Exception as e:
            Result.fail(map_error_to_message(e), error=e)

    scale = pyqtProperty(float, fget=getScale, fset=setScale, notify=scaleChanged)

    # ----------------
    # badge pulse
    def getBadgePulse(self) -> float:
        return self._badge_pulse

    def setBadgePulse(self, value: float):
        try:
            self._badge_pulse = float(value)
            self.update()
        except Exception as e:
            Result.fail(map_error_to_message(e), error=e)

    badgePulse = pyqtProperty(float, fget=getBadgePulse, fset=setBadgePulse)

    # ----------------
    def start(self):
        try:
            if self._is_running:
                return
            self._set_spin_active(False)
            if self._repeat_timer.isActive():
                self._repeat_timer.stop()
            self._repeat_remaining = 0
            self._is_running = True
            self._is_failed = False  # fail state sıfırlansın
            self._progress = 0
            self.running_color = QColor("#2ecc71")  # yeşil
            self._animate_to(0.85, duration=200)  # basılı hale geç
            self.started.emit()
            self.update()
        except Exception as e:
            Result.fail(map_error_to_message(e), error=e)

    def setRunningText(self, text: str | None) -> None:
        try:
            self._running_text = str(text or "").strip()
            self.update()
        except Exception as e:
            Result.fail(map_error_to_message(e), error=e)

    def runningText(self) -> str:
        try:
            return str(self._running_text or "")
        except Exception:
            return ""

    def clearRunningText(self) -> None:
        self.setRunningText("")

    def setAutoResetOnComplete(self, enabled: bool) -> None:
        self._auto_reset_on_complete = bool(enabled)

    def reset(self):
        try:
            if not self._is_running and self._progress == 0 and self._scale == 1.0 and not self._is_failed:
                return
            self._is_running = False
            self._progress = 0
            self._running_text = ""
            self._is_failed = False  # hata modu sıfırlanır
            self.running_color = QColor("#2ecc71")
            self._animate_to(1.0, duration=250)
            self.finished.emit()
            if self._repeat_enabled:
                self._start_repeat_timer()
            else:
                self._set_spin_active(False)
            self.update()
        except Exception as e:
            Result.fail(map_error_to_message(e), error=e)

    def setProgress(self, value: int):
        try:
            v = max(0, min(100, int(value)))

            if not self._is_running and v > 0:
                self.start()

            if self._progress == v and self._is_running:
                return

            self._progress = v
            self.update()

            if v >= 100 and self._auto_reset_on_complete:
                QTimer.singleShot(120, self.reset)
        except Exception as e:
            Result.fail(map_error_to_message(e), error=e)

    # ----------------
    def _animate_to(self, end_value: float, duration: int = 200):
        try:
            if self._scale_anim.state() == QAbstractAnimation.State.Running:
                self._scale_anim.stop()
            self._scale_anim.setDuration(duration)
            self._scale_anim.setStartValue(self._scale)
            self._scale_anim.setEndValue(end_value)
            self._scale_anim.start()
        except Exception as e:
            Result.fail(map_error_to_message(e), error=e)

    # ----------------
    # repeat helpers (auto click + countdown)
    def setRepeatInterval(self, seconds: int):
        try:
            sec = int(seconds)
            if sec <= 0:
                sec = 1
            self._repeat_interval = sec
            if self._repeat_enabled:
                self._repeat_remaining = sec
                self.update()
        except Exception as e:
            Result.fail(map_error_to_message(e), error=e)

    def enableRepeat(self, enabled: bool = True, *, immediate: bool = False):
        try:
            self._repeat_enabled = bool(enabled)
            if not self._repeat_enabled:
                self._stop_repeat_timer()
                return
            if not self._is_running:
                self._start_repeat_timer(immediate=immediate)
            else:
                self._repeat_remaining = 0
                self._set_spin_active(False)
        except Exception as e:
            Result.fail(map_error_to_message(e), error=e)

    def stopRepeat(self):
        try:
            self._repeat_enabled = False
            self._stop_repeat_timer()
        except Exception as e:
            Result.fail(map_error_to_message(e), error=e)

    def _format_repeat_time(self, seconds: int) -> str:
        sec = max(0, int(seconds))
        mins, secs = divmod(sec, 60)
        return f"{mins}:{secs:02d}"

    def _start_repeat_timer(self, immediate: bool = False):
        if self._repeat_interval <= 0:
            self._repeat_interval = 60
        self._repeat_remaining = self._repeat_interval
        self._set_spin_active(True)
        if not self._repeat_timer.isActive():
            self._repeat_timer.start()
        if immediate:
            self._fire_repeat()
        self.update()

    def _stop_repeat_timer(self):
        self._repeat_timer.stop()
        self._repeat_remaining = 0
        self._set_spin_active(False)
        self.update()

    def _fire_repeat(self):
        if not self._repeat_enabled:
            return
        if not self.isEnabled():
            return
        if self._is_running:
            return
        self._repeat_remaining = 0
        self.click()
        self._pulse_t = 0.0
        self.update()

    def _tick_repeat(self):
        if not self._repeat_enabled:
            self._stop_repeat_timer()
            return
        if self._is_running:
            return
        if self._repeat_remaining <= 1:
            self._fire_repeat()
            return
        self._repeat_remaining -= 1
        self._pulse_t = 0.0
        self.update()

    def _set_spin_active(self, active: bool):
        if active:
            if not self._spin_timer.isActive():
                self._spin_timer.start()
        else:
            self._spin_timer.stop()
            self._badge_pulse = 0.0
            self._pulse_t = 0.0

    def _tick_spin(self):
        self._rotation = (self._rotation + 0.6) % 360.0
        if self._repeat_enabled and self._repeat_remaining > 0 and not self._is_running:
            self._pulse_t = (self._pulse_t + 0.04) % 1.0
            self._badge_pulse = self._heart_pulse(self._pulse_t)
        else:
            self._badge_pulse = 0.0
        self.update()

    def _heart_pulse(self, t: float) -> float:
        # Two quick beats per second: strong + smaller rebound
        def _tri(x: float, w: float) -> float:
            return max(0.0, 1.0 - abs(x) / w)

        p1 = _tri(t - 0.08, 0.08)  # main beat
        p2 = 0.6 * _tri(t - 0.28, 0.10)  # secondary beat
        return max(p1, p2)
    def mousePressEvent(self, event):
        try:
            if not self._is_running:
                self.start()
            super().mousePressEvent(event)
        except Exception as e:
            Result.fail(map_error_to_message(e), error=e)

    # ----------------
    def paintEvent(self, event):
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            rect = self.rect()
            radius = min(rect.width(), rect.height()) / 2 - self._ring_pen_w
            center = QPointF(rect.center())

            painter.save()
            painter.translate(center)
            painter.scale(self._scale, self._scale)
            painter.translate(-center)

            active_countdown = (
                self._repeat_enabled
                and self._repeat_remaining > 0
                and not self._is_running
                and not getattr(self, "_is_failed", False)
            )

            # dış çember
            pen = QPen(QColor("#22D3EE") if active_countdown else QColor("#bdc3c7"), self._ring_pen_w)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, radius, radius)

            if active_countdown:
                # snake-like moving highlight
                snake = QConicalGradient(center, self._rotation)
                snake.setColorAt(0.00, QColor(56, 189, 248, 0))
                snake.setColorAt(0.06, QColor(56, 189, 248, 255))
                snake.setColorAt(0.12, QColor(56, 189, 248, 120))
                snake.setColorAt(0.20, QColor(56, 189, 248, 0))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QBrush(snake), self._ring_pen_w))
                painter.drawEllipse(center, radius, radius)

                # inner moving black dot
                angle = math.radians(self._rotation)
                dot_r = max(3, int(radius * 0.08))
                orbit_r = max(6, int(radius * 0.45))
                dx = math.cos(angle) * orbit_r
                dy = math.sin(angle) * orbit_r
                dot_center = QPointF(center.x() + dx, center.y() + dy)
                painter.setBrush(QColor("#0B0F1A"))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(dot_center, dot_r, dot_r)

            # 1) Fail state → kırmızı + Retry
            if getattr(self, "_is_failed", False):
                painter.setBrush(QColor("#e74c3c"))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(center, radius - 8, radius - 8)

                painter.setPen(self.text_color)
                painter.setFont(self.font())
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Retry")

            # 2) Running state → progress + yüzde
            elif self._is_running:
                # progress çemberi
                if self._progress > 0:
                    pen.setColor(self.running_color)
                    painter.setPen(pen)
                    span_angle = int(360 * self._progress / 100)
                    painter.drawArc(
                        QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius),
                        -90 * 16,
                        -span_angle * 16
                    )

                # iç dolgu
                painter.setBrush(self.running_color)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(center, radius - 8, radius - 8)

                display_text = str(self._running_text or "").strip()
                painter.setPen(self.text_color)
                progress_font = QFont(self.progress_font_base)
                if display_text:
                    progress_font.setPointSize(max(8, self._label_font_size))
                    progress_font.setWeight(QFont.Weight.Bold)
                else:
                    progress_font.setPointSize(self._progress_font_size)
                    progress_font.setWeight(QFont.Weight.Black)
                painter.setFont(progress_font)
                if display_text:
                    inner_rect = rect.adjusted(18, 18, -18, -18)
                    painter.drawText(
                        inner_rect,
                        Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                        display_text,
                    )
                else:
                    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{self._progress}%")

            # 3) Idle state → mavi + Başlat
            else:
                painter.setBrush(self.default_color)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(center, radius - 8, radius - 8)

                painter.setPen(self.text_color)
                painter.setFont(self.font())
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())

            # repeat countdown overlay (bottom digital badge)
            if active_countdown:
                text = self._format_repeat_time(self._repeat_remaining)
                badge_font = QFont(self.progress_font_family, self._badge_font_size, QFont.Weight.DemiBold)
                painter.setFont(badge_font)
                fm = QFontMetrics(badge_font)

                diameter = radius * 2
                inner_radius = max(0, radius - (self._ring_pen_w + 2))
                badge_h = max(16, int(diameter * 0.22))
                bottom_margin = 10
                badge_center_y = center.y() + inner_radius - bottom_margin - badge_h / 2
                dy = badge_center_y - center.y()
                max_half_w = 0.0
                if inner_radius > 0:
                    max_half_w = max(0.0, math.sqrt(max(0.0, inner_radius ** 2 - dy ** 2)) - 2)

                pad_x = 12
                if self._badge_fixed_w is None:
                    self._badge_fixed_w = fm.horizontalAdvance("88:88") + pad_x * 2
                desired_w = self._badge_fixed_w
                max_w = int(max_half_w * 2)
                if max_w <= 0:
                    painter.restore()
                    return
                badge_w = min(desired_w, max_w)
                badge_x = int(center.x() - badge_w / 2)
                badge_y = int(badge_center_y - badge_h / 2)

                badge_rect = QRect(badge_x, badge_y, int(badge_w), int(badge_h))
                pulse = self._badge_pulse
                glow_alpha = int(90 + 37 * pulse)
                # soft white frame like ActionPulseButton
                frame_rect = badge_rect.adjusted(-3, -2, 3, 2)
                frame_alpha = int(120 + 80 * pulse)
                painter.setPen(QPen(QColor(255, 255, 255, frame_alpha), 1))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(frame_rect, 5, 5)

                # green glow pushed toward the frame
                glow_radius = max(frame_rect.width(), frame_rect.height()) * 0.4
                glow = QRadialGradient(QPointF(frame_rect.center()), glow_radius)
                glow.setColorAt(0.0, QColor(34, 255, 128, 0))
                glow.setColorAt(0.55, QColor(34, 255, 128, glow_alpha))
                glow.setColorAt(1.0, QColor(34, 255, 128, 0))
                painter.setBrush(QBrush(glow))
                painter.setPen(Qt.PenStyle.NoPen)
                glow_rect = frame_rect.adjusted(-4, -4, 4, 4)
                painter.drawRoundedRect(glow_rect, glow_rect.height() / 2, glow_rect.height() / 2)

                painter.setPen(QPen(QColor("#1F2937"), 1))
                base_alpha = int(200 + 20 * pulse)
                painter.setBrush(QColor(15, 23, 42, base_alpha))
                painter.drawRoundedRect(badge_rect, 4, 4)

                painter.setPen(QColor("#E5E7EB"))
                painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, text)

            painter.restore()

        except Exception as e:
            Result.fail(map_error_to_message(e), error=e)

    def fail(self):
        try:
            self._is_running = False
            self._progress = 0
            self._running_text = ""
            self._is_failed = True  # fail state aktif

            self.running_color = QColor("#e74c3c")  # kırmızı
            self._animate_to(1.0, duration=250)  # çıkık hale dön
            self.update()
        except Exception as e:
            Result.fail(map_error_to_message(e), error=e)


# ========================
# SwitchButton
# ========================
class SwitchButton(QAbstractButton):
    def __init__(self, parent=None, checked_color="#1abc9c", unchecked_color="#cccccc", thumb_color="white", animation_duration=150):
        super().__init__(parent)
        try:
            self.setCheckable(True)
            self._checked_color = QColor(checked_color)
            self._unchecked_color = QColor(unchecked_color)
            self._thumb_color = QColor(thumb_color)

            self._thumb_pos = 3
            self._anim = QPropertyAnimation(self, b"thumb_pos", self)
            self._anim.setDuration(animation_duration)

            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setFixedSize(50, 28)
            self.setThumbInitial()
            _init_disabled_lock_badge(self)
        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    # BURASI YENİ: animasyonun takip edeceği property
    def getThumbPos(self):
        return self._thumb_pos

    def setThumbPos(self, pos):
        self._thumb_pos = pos
        self.update()  # repaint tetikle
    thumb_pos = pyqtProperty(int, fget=getThumbPos, fset=setThumbPos)

    def paintEvent(self, event):
        try:
            radius = self.height() / 2
            bg_color = self._checked_color if self.isChecked() else self._unchecked_color

            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(bg_color)
            painter.drawRoundedRect(self.rect(), radius, radius)

            r = self.height() - 6
            painter.setBrush(self._thumb_color)
            painter.drawEllipse(QRectF(self._thumb_pos, 3, r, r))
        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    def mouseReleaseEvent(self, event):
        try:
            if event.button() == Qt.MouseButton.LeftButton:
                self.toggle()
                self._animate()
                self.clicked.emit(self.isChecked())
        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    def _animate(self):
        try:
            start = self._thumb_pos
            end = self.width() - self.height() + 3 if self.isChecked() else 3
            self._anim.stop()
            self._anim.setStartValue(start)
            self._anim.setEndValue(end)
            self._anim.start()
        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    def setThumbInitial(self):
        try:
            self._thumb_pos = self.width() - self.height() + 3 if self.isChecked() else 3
        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    def setChecked(self, checked: bool):
        try:
            super().setChecked(checked)
            self.setThumbInitial()
            self.update()
        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    def setEnabled(self, enabled: bool):
        super().setEnabled(enabled)
        _sync_disabled_lock_badge(self)
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        _position_disabled_lock_badge(self)

    def moveEvent(self, event):
        super().moveEvent(event)
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


class ActionPulseButton(QAbstractButton):
    """
    Dikkat çekici aksiyon butonu.
    - Aktifken etrafında canlı yanıp sönen border animasyonu var.
    - Pasifken gri ve cansız.
    - Metin + opsiyonel ikon destekli.
    """

    clicked = pyqtSignal()

    def __init__(
        self,
        text: str = "Aksiyon",
        icon_path: str | None = None,
        *,
        center_text: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        try:
            self._text = text
            self._icon = _cached_pixmap(icon_path)
            self._center_text = bool(center_text)

            self._radius = 10
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self.setFixedSize(180, 60)
            self.setCursor(Qt.CursorShape.PointingHandCursor)

            # renkler
            self._bg_enabled = QColor("#4e6cef")      # aktif gövde
            self._bg_disabled = QColor("#9e9e9e")     # pasif gövde
            self._text_color_enabled = QColor("#ffffff")
            self._text_color_disabled = QColor("#dddddd")

            # pulse seviyesi (0.0 - 1.0)
            self._pulse_level = 0.0

            # animasyon
            self._pulse_anim = QPropertyAnimation(self, b"pulseLevel", self)
            self._pulse_anim.setDuration(800)
            self._pulse_anim.setStartValue(0.0)
            self._pulse_anim.setEndValue(1.0)
            self._pulse_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
            self._pulse_anim.setLoopCount(-1)

            # başlangıçta kapalı kalsın
            self.setEnabled(False)

        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    # ---------------------------
    # pulse property
    # ---------------------------
    def getPulseLevel(self) -> float:
        return self._pulse_level

    def setPulseLevel(self, val: float):
        try:
            self._pulse_level = float(val)
            self.update()
        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    pulseLevel = pyqtProperty(float, fget=getPulseLevel, fset=setPulseLevel)

    # ---------------------------
    # enable/disable
    # ---------------------------
    def setEnabled(self, enabled: bool):
        """
        enable -> animasyon başlar
        disable -> animasyon durur, gri görünüm
        """
        try:
            super().setEnabled(enabled)

            if enabled:
                if self._pulse_anim.state() != QPropertyAnimation.State.Running:
                    # ileri geri yanıp sönen efekt
                    # startValue=0, endValue=1 arası gidip geliyor gibi olsun diye
                    # ping-pong efektini elle taklit ediyoruz:
                    self._pulse_anim.setStartValue(0.0)
                    self._pulse_anim.setEndValue(1.0)
                    self._pulse_anim.start()
            else:
                if self._pulse_anim.state() == QPropertyAnimation.State.Running:
                    self._pulse_anim.stop()
                self._pulse_level = 0.0
                self.update()
        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    # ---------------------------
    # public api
    # ---------------------------
    def setText(self, text: str):
        self._text = text
        self.update()

    def setIconPixmap(self, path: str):
        try:
            self._icon = _cached_pixmap(path)
            self.update()
        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    def setCenterText(self, enabled: bool) -> None:
        self._center_text = bool(enabled)
        self.update()

    # ---------------------------
    # click
    # ---------------------------
    def mouseReleaseEvent(self, event):
        try:
            if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
                self.clicked.emit()
        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    # ---------------------------
    # paint
    # ---------------------------
    def paintEvent(self, event):
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            full_rect = self.rect()
            body_rect = full_rect.adjusted(4, 4, -4, -4)  # iç gövde
            outer_rect = full_rect.adjusted(1, 1, -1, -1) # dış halka sınırı

            # aktif/pasif renk seç
            if self.isEnabled():
                bg = QColor(self._bg_enabled)
                text_color = QColor(self._text_color_enabled)
            else:
                bg = QColor(self._bg_disabled)
                text_color = QColor(self._text_color_disabled)

            #
            # 1) Dış pulsating border (SADECE ENABLE İKEN)
            #
            if self.isEnabled():
                # pulse_level 0 → sönük, 1 → parlak
                # alpha'yı sert arttırıyoruz ki göze çarpsın
                alpha = int(80 + self._pulse_level * 170)  # 80-250 arası
                pulse_color = QColor("#6f8cff")  # maviye yakın parıltı
                pulse_color.setAlpha(alpha)

                pulse_pen = QPen(pulse_color)
                pulse_pen.setWidth(4)  # kalın border
                painter.setPen(pulse_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)

                # dış çerçevenin yuvarlak köşeleri biraz büyük olsun ki glow hissi versin
                painter.drawRoundedRect(outer_rect, self._radius + 4, self._radius + 4)

            #
            # 2) Ana buton gövdesi
            #
            painter.setBrush(bg)
            painter.setPen(QPen(bg.darker(140), 1))
            painter.drawRoundedRect(body_rect, self._radius, self._radius)

            #
            # 3) İçerik (ikon + text)
            #
            x_cursor = body_rect.left() + 14
            cy = body_rect.center().y()

            # ikon
            if self._icon and not self._icon.isNull():
                icon_size = 28
                icon_y = int(cy - icon_size / 2)
                painter.drawPixmap(x_cursor, icon_y, icon_size, icon_size, self._icon)
                x_cursor += icon_size + 8

            # text
            font = QFont("Segoe UI", 11, QFont.Weight.Bold)
            painter.setFont(font)
            painter.setPen(text_color)

            if self._center_text and (self._icon is None or self._icon.isNull()):
                text_rect = QRectF(body_rect)
                align = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignCenter
            else:
                text_rect = QRectF(
                    x_cursor,
                    cy - 10,
                    body_rect.right() - x_cursor - 10,
                    24
                )
                align = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft

            painter.drawText(text_rect, align, self._text)

        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))


class SelectClearToggleButton(QPushButton):
    """
    Single reusable button for "Select All" / "Clear Selection" flows.
    Emits `actionRequested` with:
      - "select" when button is in select mode
      - "clear" when button is in clear mode
    """

    actionRequested = pyqtSignal(str)

    def __init__(
        self,
        select_text: str = "Tümünü Seç",
        clear_text: str = "Seçimi Kaldır",
        parent=None,
    ):
        super().__init__(parent)
        self._select_text = str(select_text or "Tümünü Seç")
        self._clear_text = str(clear_text or "Seçimi Kaldır")
        self._clear_mode = False
        self.setObjectName("GhostBtn")
        self.clicked.connect(self._on_clicked)
        self._sync_text()

    def _sync_text(self) -> None:
        self.setText(self._clear_text if self._clear_mode else self._select_text)
        self._apply_mode_style()

    def _apply_mode_style(self) -> None:
        if self._clear_mode:
            self.setStyleSheet(
                """
                QPushButton {
                    padding: 6px 10px;
                    border-radius: 10px;
                    border: 1px solid #EF4444;
                    background: #FEF2F2;
                    color: #B91C1C;
                    font-weight: 700;
                }
                QPushButton:hover {
                    background: #FEE2E2;
                    border: 1px solid #DC2626;
                }
                QPushButton:pressed {
                    background: #FECACA;
                }
                QPushButton:disabled {
                    background: #F9FAFB;
                    border: 1px solid #E5E7EB;
                    color: #9CA3AF;
                }
                """
            )
            return

        self.setStyleSheet(
            """
            QPushButton {
                padding: 6px 10px;
                border-radius: 10px;
                border: 1px solid #3B82F6;
                background: #EFF6FF;
                color: #1D4ED8;
                font-weight: 700;
            }
            QPushButton:hover {
                background: #DBEAFE;
                border: 1px solid #2563EB;
            }
            QPushButton:pressed {
                background: #BFDBFE;
            }
            QPushButton:disabled {
                background: #F9FAFB;
                border: 1px solid #E5E7EB;
                color: #9CA3AF;
            }
            """
        )

    def _on_clicked(self) -> None:
        self.actionRequested.emit("clear" if self._clear_mode else "select")

    def setSelectionCounts(self, selected_count: int, total_count: int) -> None:
        total = max(0, int(total_count or 0))
        selected = max(0, min(total, int(selected_count or 0)))
        self.setEnabled(total > 0)
        # Any selection means user can clear quickly.
        self._clear_mode = selected > 0
        self._sync_text()

    def setClearMode(self, enabled: bool) -> None:
        self._clear_mode = bool(enabled)
        self._sync_text()

    def isClearMode(self) -> bool:
        return bool(self._clear_mode)


# ========================
# NumberStepper (Custom)
# ========================
class NumberStepper(QWidget):
    """
    Compact segmented integer stepper.
    Keeps the old spinbox API while using lightweight button pulses.
    """
    valueChanged = pyqtSignal(int)

    def __init__(self, parent=None, *, minimum: int = 0, maximum: int = 10_000_000, step: int = 1):
        super().__init__(parent)
        self._min = int(minimum)
        self._max = int(maximum)
        self._step = int(step)
        self._value = self._clamp(0)

        self.setObjectName("NumberStepper")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(112)
        self.setMaximumWidth(160)
        self.resize(144, 34)
        self.setFixedHeight(34)

        self.frame = QFrame(self)
        self.frame.setObjectName("NumberStepperFrame")
        self.frame.setProperty("focused", False)

        self.input = QLineEdit(self.frame)
        self.input.setObjectName("NumberStepperInput")
        self.input.setPlaceholderText("0")
        self.input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.input.setValidator(QRegularExpressionValidator(QRegularExpression(r"-?\d+"), self.input))
        self.input.installEventFilter(self)
        self.input.textChanged.connect(self._on_text_changed)

        self.btn_up = QToolButton(self.frame)
        self.btn_up.setObjectName("NumberStepperPlus")
        self.btn_up.setText("+")
        self.btn_up.setAutoRaise(False)
        self.btn_up.setFixedSize(28, 28)
        self.btn_up.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_up.clicked.connect(lambda: self._step_by(+1, self.btn_up, "plus"))

        self.btn_down = QToolButton(self.frame)
        self.btn_down.setObjectName("NumberStepperMinus")
        self.btn_down.setText("-")
        self.btn_down.setAutoRaise(False)
        self.btn_down.setFixedSize(28, 28)
        self.btn_down.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_down.clicked.connect(lambda: self._step_by(-1, self.btn_down, "minus"))

        frame_layout = QHBoxLayout(self.frame)
        frame_layout.setContentsMargins(3, 2, 3, 2)
        frame_layout.setSpacing(4)
        frame_layout.addWidget(self.btn_down, 0, Qt.AlignmentFlag.AlignVCenter)
        frame_layout.addWidget(self.input, 1, Qt.AlignmentFlag.AlignVCenter)
        frame_layout.addWidget(self.btn_up, 0, Qt.AlignmentFlag.AlignVCenter)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.frame)

        self._apply_default_style()
        self._write_value(self._value, emit=False)

    def _apply_default_style(self):
        # Scoped styling for this widget only
        self.setStyleSheet("""
        QFrame#NumberStepperFrame {
            border: 1px solid rgba(17, 24, 39, 0.12);
            border-radius: 17px;
            background: #FFFFFF;
        }
        QFrame#NumberStepperFrame[focused="true"] {
            border: 1px solid rgba(15, 23, 42, 0.24);
        }
        QLineEdit#NumberStepperInput {
            border: 0px;
            border-radius: 10px;
            padding: 0px 4px;
            background: transparent;
            color: #0F172A;
            font-size: 13px;
            font-weight: 800;
            min-height: 28px;
            max-height: 28px;
        }
        QToolButton#NumberStepperPlus, QToolButton#NumberStepperMinus {
            border: 0px;
            border-radius: 14px;
            font-size: 15px;
            font-weight: 950;
            padding: 0px;
        }
        QToolButton#NumberStepperPlus {
            background: rgba(34, 197, 94, 0.10);
            color: #15803D;
        }
        QToolButton#NumberStepperMinus {
            background: rgba(239, 68, 68, 0.10);
            color: #B91C1C;
            font-size: 16px;
        }
        QToolButton#NumberStepperPlus:hover {
            background: rgba(34, 197, 94, 0.18);
            color: #166534;
        }
        QToolButton#NumberStepperMinus:hover {
            background: rgba(239, 68, 68, 0.18);
            color: #991B1B;
        }
        QToolButton#NumberStepperPlus[pulse="true"] {
            background: rgba(34, 197, 94, 0.32);
            color: #14532D;
        }
        QToolButton#NumberStepperMinus[pulse="true"] {
            background: rgba(239, 68, 68, 0.30);
            color: #7F1D1D;
        }
        """)

    def eventFilter(self, watched, event):
        if watched is self.input and event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self.frame.setProperty("focused", event.type() == QEvent.Type.FocusIn)
            self.frame.style().unpolish(self.frame)
            self.frame.style().polish(self.frame)
        return super().eventFilter(watched, event)

    def sizeHint(self) -> QSize:
        return QSize(144, 34)

    def minimumSizeHint(self) -> QSize:
        return QSize(112, 34)

    def _parse(self, text: str) -> int:
        try:
            return int(text.strip())
        except Exception:
            return 0

    def _clamp(self, val: int) -> int:
        return max(self._min, min(self._max, int(val)))

    def _write_value(self, val: int, *, emit: bool = True) -> None:
        val = self._clamp(val)
        changed = val != self._value
        self._value = val
        if self.input.text().strip() != str(val):
            with QSignalBlocker(self.input):
                self.input.setText(str(val))
        if emit and changed:
            self.valueChanged.emit(val)

    def _clamp_and_emit(self) -> None:
        self._write_value(self._parse(self.input.text()))

    def _on_text_changed(self, _text: str) -> None:
        self._clamp_and_emit()

    def _pulse(self, button: QToolButton) -> None:
        button.setProperty("pulse", True)
        button.style().unpolish(button)
        button.style().polish(button)
        QTimer.singleShot(130, lambda: self._finish_pulse(button))

    def _finish_pulse(self, button: QToolButton) -> None:
        button.setProperty("pulse", False)
        button.style().unpolish(button)
        button.style().polish(button)

    def _step_by(self, direction: int, button: QToolButton | None = None, tone: str = "plus") -> None:
        val = self.value() + direction * self._step
        self._write_value(val)
        if button is not None:
            self._pulse(button)

    # Public API
    def value(self) -> int:
        return self._value

    def setValue(self, val: int) -> None:
        self._write_value(val)

    def setRange(self, minimum: int, maximum: int) -> None:
        self._min = int(minimum)
        self._max = int(maximum)
        self._clamp_and_emit()

    def setSingleStep(self, step: int) -> None:
        self._step = int(step)

    def setToolTip(self, tip: str) -> None:
        super().setToolTip(tip)
        self.input.setToolTip(tip)
        self.btn_up.setToolTip(tip)
        self.btn_down.setToolTip(tip)


# ========================
# ✨ GlowActionButton + LabeledActionInput
# ========================
class GlowActionButton(QAbstractButton):
    """
    Small action button with animated glow ring.
    States: idle (neutral), pending (blue border), success/error (neutral)
    """
    def __init__(self, text: str = "OK", parent=None):
        super().__init__(parent)
        self._text = text or "OK"
        self._state = "idle"
        self._radius = 8
        self._joined = False
        self._border_color = None
        self._phase = 0.0
        self._chromeless = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(36, 28)
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

    def setText(self, text: str) -> None:
        self._text = text or "OK"
        self.update()

    def setJoined(self, joined: bool) -> None:
        self._joined = bool(joined)
        self.update()

    def setChromeless(self, chromeless: bool) -> None:
        self._chromeless = bool(chromeless)
        self.update()

    def setBorderColor(self, color: str | None) -> None:
        self._border_color = color
        self.update()

    def setState(self, state: str) -> None:
        state = (state or "").strip().lower()
        if state not in {"idle", "pending", "success", "error"}:
            state = "idle"
        self._state = state
        if self._state == "pending":
            if not self._timer.isActive():
                self._timer.start()
        else:
            if self._timer.isActive():
                self._timer.stop()
            self._phase = 0.0
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + 6.0) % 360.0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = self.rect().adjusted(2, 2, -2, -2)
        ring_rect = rect.adjusted(-1, -1, 1, 1)

        round_left = not self._joined
        round_right = True
        if self._chromeless:
            if self._state == "pending":
                ring_rect = rect.adjusted(-2, -2, 2, 2)
                grad = QConicalGradient(QPointF(ring_rect.center()), self._phase)
                grad.setColorAt(0.00, QColor(59, 130, 246, 0))
                grad.setColorAt(0.18, QColor(59, 130, 246, 190))
                grad.setColorAt(0.50, QColor(59, 130, 246, 255))
                grad.setColorAt(0.82, QColor(59, 130, 246, 190))
                grad.setColorAt(1.00, QColor(59, 130, 246, 0))
                painter.setPen(QPen(QBrush(grad), 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(_rounded_rect_path(QRectF(ring_rect), self._radius + 2, round_left=round_left, round_right=round_right))
            painter.setPen(QColor("#0F172A"))
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._text)
            return
        if self._border_color:
            border_color = QColor(self._border_color)
        else:
            border_color = QColor("#3B82F6") if self._state == "pending" else QColor("#CBD5E1")
        fill_color = QColor("#FFFFFF")
        painter.setBrush(QColor("#FFFFFF"))
        base_path = _rounded_rect_path(QRectF(rect), self._radius, round_left=round_left, round_right=round_right)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill_color)
        painter.drawPath(base_path)

        painter.setPen(QPen(border_color, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(base_path)

        if self._state == "pending":
            ring_rect = rect.adjusted(-2, -2, 2, 2)
            grad = QConicalGradient(QPointF(ring_rect.center()), self._phase)
            grad.setColorAt(0.00, QColor(59, 130, 246, 0))
            grad.setColorAt(0.18, QColor(59, 130, 246, 190))
            grad.setColorAt(0.50, QColor(59, 130, 246, 255))
            grad.setColorAt(0.82, QColor(59, 130, 246, 190))
            grad.setColorAt(1.00, QColor(59, 130, 246, 0))
            painter.setPen(QPen(QBrush(grad), 2))
            painter.drawPath(_rounded_rect_path(QRectF(ring_rect), self._radius + 2, round_left=round_left, round_right=round_right))

        if self._joined:
            # mask the inner seam for a unified look
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill_color)
            painter.drawRect(QRect(rect.left() - 1, rect.top(), 4, rect.height()))
            painter.setPen(QPen(border_color, 1))
            painter.drawLine(rect.left() + 1, rect.top() + 1, rect.left() + 1, rect.bottom() - 1)

        painter.setPen(QColor("#0F172A"))
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._text)


class LabeledActionInput(QWidget):
    """
    Label + line edit + integrated OK area drawn as a single control.
    """
    submitted = pyqtSignal(object)

    def __init__(
        self,
        parent=None,
        *,
        label: str = "",
        placeholder: str = "",
        button_text: str = "OK",
        idle_glow: bool = False,
        integrated: bool = True,
    ):
        super().__init__(parent)
        self._label_text = label or ""
        self._state = "idle"
        self._integrated = bool(integrated)
        self._focused = False
        self._pending_phase = 0.0
        self._pending_timer = QTimer(self)
        self._pending_timer.setInterval(40)
        self._pending_timer.timeout.connect(self._tick_pending)
        self._reveal = 1.0
        self._reveal_timer = QTimer(self)
        self._reveal_timer.setInterval(30)
        self._reveal_timer.timeout.connect(self._tick_reveal)
        self._ok_text = button_text or "OK"
        self._idle_arrow = "→"
        self._ok_width = 44
        self._field_radius = 12
        self._field_rect = QRect()
        self._ok_rect = QRect()
        self._input_rect = QRect()
        self._ok_hover = False
        self._ok_pressed = False
        self.setMouseTracking(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.label = QLabel(self._label_text)
        self.label.setStyleSheet("font-size: 10px; color: #64748B;")
        self.label.setFixedHeight(16)

        self.input = QLineEdit(self)
        self.input.setPlaceholderText(placeholder or "")
        self.input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.input.setStyleSheet("padding: 0px 6px; border: 0px; background: transparent;")
        self.input.setFrame(False)
        self.input.installEventFilter(self)

        layout.addWidget(self.label)
        layout.addStretch(1)

        self.input.returnPressed.connect(self._emit_submit)
        self.setMinimumHeight(60)
        self._update_geometry()

    def _emit_submit(self):
        if self._state == "pending":
            return
        self.submitted.emit(self.value())

    def setLabel(self, text: str) -> None:
        self._label_text = text or ""
        self.label.setText(self._label_text)

    def setPlaceholderText(self, text: str) -> None:
        self.input.setPlaceholderText(text or "")

    def setValidator(self, validator) -> None:
        self.input.setValidator(validator)

    def setValue(self, value) -> None:
        self.input.setText("" if value is None else str(value))

    def value(self):
        return (self.input.text() or "").strip()

    def setState(self, state: str) -> None:
        state = (state or "").strip().lower()
        self._state = state
        if state == "pending" and self._ok_rect.contains(self.mapFromGlobal(QCursor.pos())):
            self.setCursor(Qt.CursorShape.ForbiddenCursor)
        elif state != "pending":
            self.unsetCursor()
        if state == "pending":
            if not self._pending_timer.isActive():
                self._pending_timer.start()
        else:
            if self._pending_timer.isActive():
                self._pending_timer.stop()
            self._pending_phase = 0.0
        if state == "success":
            self._start_reveal()
        else:
            if self._reveal_timer.isActive():
                self._reveal_timer.stop()
            self._reveal = 1.0
        self.update()

    def _tick_pending(self) -> None:
        self._pending_phase = (self._pending_phase + 6.0) % 360.0
        self.update()

    def _start_reveal(self) -> None:
        self._reveal = 0.0
        if not self._reveal_timer.isActive():
            self._reveal_timer.start()

    def _tick_reveal(self) -> None:
        self._reveal = min(1.0, self._reveal + 0.12)
        if self._reveal >= 1.0 and self._reveal_timer.isActive():
            self._reveal_timer.stop()
        self.update()

    def _current_border_color(self) -> QColor:
        if self._state == "success":
            return QColor("#22C55E")
        if self._state == "error":
            return QColor("#EF4444")
        if self._state == "pending":
            return QColor("#CBD5E1")
        if self._focused:
            return QColor("#3B82F6")
        return QColor("#E5E7EB")

    def eventFilter(self, obj, event):
        if obj is self.input:
            if event.type() == QEvent.Type.FocusIn:
                self._focused = True
                if self._state in {"success", "error"}:
                    self.setState("idle")
                self.update()
            elif event.type() == QEvent.Type.FocusOut:
                self._focused = False
                self.update()
        return super().eventFilter(obj, event)

    def _update_geometry(self) -> None:
        if not self._integrated:
            return
        label_h = self.label.height()
        spacing = self.layout().spacing()
        top = label_h + spacing
        field_h = max(36, int(self.height() - top))
        base_rect = QRect(0, top, self.width(), field_h)
        self._field_rect = base_rect.adjusted(2, 2, -2, -2)
        self._ok_rect = QRect(self._field_rect.right() - self._ok_width + 1, self._field_rect.top(), self._ok_width, self._field_rect.height())
        input_h = max(24, min(30, self._field_rect.height() - 8))
        input_y = self._field_rect.top() + (self._field_rect.height() - input_h) // 2
        self._input_rect = QRect(
            self._field_rect.left() + 8,
            input_y,
            self._field_rect.width() - self._ok_width - 16,
            input_h,
        )
        self.input.setGeometry(self._input_rect)
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_geometry()

    def mousePressEvent(self, event):
        if self._state == "pending":
            event.accept()
            return
        if self._integrated and self._ok_rect.contains(event.position().toPoint()):
            self._ok_pressed = True
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._state == "pending":
            event.accept()
            return
        if self._ok_pressed:
            was_inside = self._ok_rect.contains(event.position().toPoint())
            self._ok_pressed = False
            self.update()
            if was_inside:
                self._emit_submit()
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if self._integrated:
            inside = self._ok_rect.contains(event.position().toPoint())
            if inside != self._ok_hover:
                self._ok_hover = inside
                self.update()
            if self._state == "pending" and inside:
                self.setCursor(Qt.CursorShape.ForbiddenCursor)
            elif inside:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.unsetCursor()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._ok_hover or self._ok_pressed:
            self._ok_hover = False
            self._ok_pressed = False
            self.update()
        self.unsetCursor()
        super().leaveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._integrated or not self._field_rect.isValid():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        border_color = self._current_border_color()
        path = _rounded_rect_path(QRectF(self._field_rect), self._field_radius, round_left=True, round_right=False)
        painter.setPen(QPen(border_color, 1))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawPath(path)

        seam_x = self._ok_rect.left()
        painter.drawLine(seam_x, self._field_rect.top() + 1, seam_x, self._field_rect.bottom() - 1)

        if self._ok_hover or self._ok_pressed:
            hover_color = QColor("#E2E8F0") if not self._ok_pressed else QColor("#CBD5E1")
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(hover_color)
            painter.drawRect(self._ok_rect.adjusted(1, 1, -1, -1))

        if self._state in {"pending", "success", "error"}:
            if self._state == "pending":
                step = int(self._pending_phase // 60) % 6
                dots_count = [1, 2, 3, 2, 1, 0][step]
                dots = "." * dots_count
                painter.setPen(QColor("#0F172A"))
                painter.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
                painter.drawText(self._ok_rect, Qt.AlignmentFlag.AlignCenter, dots)
            else:
                text = self._ok_text
                color = QColor("#0F172A")
                if self._state == "success":
                    color = QColor("#22C55E")
                    color.setAlpha(int(255 * self._reveal))
                elif self._state == "error":
                    color = QColor("#EF4444")
                painter.setPen(color)
                painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
                painter.drawText(self._ok_rect, Qt.AlignmentFlag.AlignCenter, text)
        else:
            painter.setPen(QColor("#0F172A"))
            painter.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
            for dx in (0, 1):
                painter.drawText(self._ok_rect.translated(dx, 0), Qt.AlignmentFlag.AlignCenter, self._idle_arrow)

        if self._state == "pending":
            ring_rect = self._ok_rect.adjusted(1, 1, -1, -1)
            grad = QConicalGradient(QPointF(ring_rect.center()), self._pending_phase)
            grad.setColorAt(0.00, QColor(59, 130, 246, 0))
            grad.setColorAt(0.18, QColor(59, 130, 246, 190))
            grad.setColorAt(0.50, QColor(59, 130, 246, 255))
            grad.setColorAt(0.82, QColor(59, 130, 246, 190))
            grad.setColorAt(1.00, QColor(59, 130, 246, 0))
            painter.setPen(QPen(QBrush(grad), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(ring_rect)

    def input_center_offset(self) -> int:
        try:
            return int((self.label.height() + self.layout().spacing()) / 2)
        except Exception:
            return 0
