from __future__ import annotations

import os
from typing import Iterable

from PyQt6.QtCore import QRect, QRectF, QSize, Qt, QEasingCurve, QPropertyAnimation, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QImage, QLinearGradient, QMovie, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStyleOptionTab,
    QTabBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


_QUICK_ACCESS_ICON_CACHE_LIMIT = 96
_QUICK_ACCESS_ICON_CACHE: dict[tuple[str, int, int], tuple[QPixmap, tuple[float, float]]] = {}


def _quick_access_icon_signature(path: str | os.PathLike | None) -> tuple[str, int, int] | None:
    raw = str(path or "").strip()
    if not raw:
        return None
    try:
        stat = os.stat(raw)
        return (raw, int(stat.st_mtime_ns), int(stat.st_size))
    except Exception:
        return (raw, -1, -1)


class GlowTabBar(QTabBar):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._hover_index = -1
        self._pressed_index = -1
        self._indicator_x = 0.0
        self._indicator_w = 0.0
        self._container_border_color = QColor(255, 255, 255, 24)
        self._container_bg_color = QColor("#2A2F36")
        self._indicator_color = QColor("#22C55E")
        self._active_text_color = QColor("#22C55E")
        self._inactive_text_color = QColor("#E5E7EB")
        self._hover_text_color = QColor("#FFFFFF")
        self._icon_pixmap_cache: dict[tuple[int, int, int, float], QPixmap] = {}
        self._icon_pixmap_cache_order: list[tuple[int, int, int, float]] = []
        self._icon_pixmap_cache_limit = 96

        self.setMouseTracking(True)
        self.setDrawBase(False)
        self.setExpanding(True)
        self.setElideMode(Qt.TextElideMode.ElideRight)
        self.setDocumentMode(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._anim_x = QPropertyAnimation(self, b"indicatorX", self)
        self._anim_w = QPropertyAnimation(self, b"indicatorW", self)
        for anim in (self._anim_x, self._anim_w):
            anim.setDuration(220)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.currentChanged.connect(self._on_current_changed)

    @staticmethod
    def _coerce_color(value, default_color: QColor) -> QColor:
        if isinstance(value, QColor):
            return QColor(value)
        text = str(value or "").strip()
        if not text:
            return QColor(default_color)
        color = QColor(text)
        if not color.isValid():
            return QColor(default_color)
        return color

    def set_palette(
        self,
        *,
        container_bg=None,
        container_border=None,
        indicator=None,
        text_active=None,
        text_inactive=None,
        text_hover=None,
    ) -> None:
        self._container_bg_color = self._coerce_color(container_bg, self._container_bg_color)
        self._container_border_color = self._coerce_color(container_border, self._container_border_color)
        self._indicator_color = self._coerce_color(indicator, self._indicator_color)
        self._active_text_color = self._coerce_color(text_active, self._active_text_color)
        self._inactive_text_color = self._coerce_color(text_inactive, self._inactive_text_color)
        self._hover_text_color = self._coerce_color(text_hover, self._hover_text_color)
        self.update()

    def tabSizeHint(self, index: int) -> QSize:
        size = super().tabSizeHint(index)
        size.setWidth(max(188, size.width() + 53))
        size.setHeight(max(106, size.height() + 48))
        return size

    def leaveEvent(self, event):
        self._hover_index = -1
        self.update()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        hover_index = self.tabAt(event.position().toPoint())
        if hover_index != self._hover_index:
            self._hover_index = hover_index
            self.update()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed_index = self.tabAt(event.position().toPoint())
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._pressed_index = -1
        self.update()
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_indicator(animated=False)

    def tabLayoutChange(self) -> None:
        super().tabLayoutChange()
        self._icon_pixmap_cache.clear()
        self._icon_pixmap_cache_order.clear()
        self._sync_indicator(animated=False)

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_indicator(animated=False)

    def _on_current_changed(self, _index: int) -> None:
        self._sync_indicator(animated=True)

    def _indicator_target(self, index: int) -> tuple[float, float] | None:
        if index < 0 or index >= self.count():
            return None
        rect = QRectF(self.tabRect(index)).adjusted(10.0, 7.0, -10.0, -8.0)
        if rect.width() <= 0:
            return None
        width = max(42.0, rect.width() * 0.52)
        x = rect.center().x() - (width / 2.0)
        return x, width

    def _sync_indicator(self, *, animated: bool) -> None:
        target = self._indicator_target(self.currentIndex())
        if target is None:
            self._indicator_x = 0.0
            self._indicator_w = 0.0
            self.update()
            return
        tx, tw = target
        if (
            not animated
            or self._indicator_w <= 0.0
            or not self.isVisible()
        ):
            self._indicator_x = float(tx)
            self._indicator_w = float(tw)
            self.update()
            return

        self._anim_x.stop()
        self._anim_w.stop()
        self._anim_x.setStartValue(float(self._indicator_x))
        self._anim_x.setEndValue(float(tx))
        self._anim_w.setStartValue(float(self._indicator_w))
        self._anim_w.setEndValue(float(tw))
        self._anim_x.start()
        self._anim_w.start()

    def get_indicator_x(self) -> float:
        return float(self._indicator_x)

    def set_indicator_x(self, value: float) -> None:
        self._indicator_x = float(value)
        self.update()

    def get_indicator_w(self) -> float:
        return float(self._indicator_w)

    def set_indicator_w(self, value: float) -> None:
        self._indicator_w = max(0.0, float(value))
        self.update()

    indicatorX = pyqtProperty(float, fget=get_indicator_x, fset=set_indicator_x)
    indicatorW = pyqtProperty(float, fget=get_indicator_w, fset=set_indicator_w)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        outer = QRectF(self.rect()).adjusted(4.0, 4.0, -4.0, -4.0)

        painter.save()
        painter.setPen(QPen(self._container_border_color, 1.0))
        painter.setBrush(self._container_bg_color)
        painter.drawRoundedRect(outer, 16.0, 16.0)
        painter.restore()

        self._draw_ai_activation_overlay(painter, outer)

        if self._indicator_w > 0.0:
            indicator_rect = QRectF(
                float(self._indicator_x),
                outer.bottom() - 6.4,
                float(self._indicator_w),
                6.0,
            )
            painter.save()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._indicator_color)
            painter.drawRoundedRect(indicator_rect, 3.0, 3.0)
            painter.restore()

        for index in range(self.count()):
            self._draw_tab(painter, index)

    def _draw_ai_activation_overlay(self, painter: QPainter, outer: QRectF) -> None:
        current = self.currentIndex()
        if current < 0 or current >= self.count():
            return
        if str(self.tabText(current) or "").strip().casefold() != "ai":
            return

        icon_rects: list[tuple[int, QRectF]] = []
        for index in range(self.count()):
            if not self.isTabVisible(index):
                continue
            draw_rect = QRectF(self.tabRect(index)).adjusted(8.0, 6.0, -8.0, -8.0)
            if draw_rect.width() <= 0:
                continue
            icon_size = max(42, min(52, int(draw_rect.height() * 0.52)))
            icon_rect = QRectF(
                draw_rect.center().x() - (icon_size / 2.0),
                draw_rect.top() + 9.0,
                float(icon_size),
                float(icon_size),
            )
            icon_rects.append((index, icon_rect.adjusted(-5.0, -5.0, 5.0, 5.0)))
        if len(icon_rects) < 2:
            return

        target_rect = next((rect for index, rect in icon_rects if index == current), None)
        if target_rect is None:
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        target_center = target_rect.center()
        halo_rect = target_rect.adjusted(-18.0, -18.0, 18.0, 18.0)
        halo = QRadialGradient(target_center, max(44.0, halo_rect.width() * 0.56))
        halo.setColorAt(0.00, QColor(34, 197, 94, 92))
        halo.setColorAt(0.45, QColor(20, 184, 166, 42))
        halo.setColorAt(1.00, QColor(34, 197, 94, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(halo_rect)

        cable_rows = [
            (index, rect)
            for index, rect in icon_rects
            if index != current
        ]
        cable_rows.sort(key=lambda item: item[1].center().x())
        total = max(1, len(cable_rows))

        for lane, (index, source_rect) in enumerate(cable_rows):
            if index == current:
                continue
            source_center = source_rect.center()
            lane_offset = (lane - ((total - 1) / 2.0)) * 6.4
            start_x = source_rect.right() + 2.0
            start_y = source_center.y() + (lane_offset * 0.18)
            end_x = target_rect.left() - 2.0
            end_y = target_center.y() + (lane_offset * 0.62)
            pull_up = 7.0 + ((lane % 3) * 2.8)

            cable = QPainterPath()
            cable.moveTo(start_x, start_y)
            cable.cubicTo(
                start_x + ((end_x - start_x) * 0.32),
                start_y - pull_up - (lane_offset * 0.10),
                start_x + ((end_x - start_x) * 0.70),
                end_y - pull_up + (lane_offset * 0.10),
                end_x,
                end_y,
            )

            glow_pen = QPen(QColor(34, 197, 94, 20), 4.0)
            glow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(glow_pen)
            painter.drawPath(cable)

            cable_pen = QPen(QColor(45, 212, 191, 150), 1.18)
            cable_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(cable_pen)
            painter.drawPath(cable)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(20, 184, 166, 165))
            painter.drawEllipse(QRectF(start_x - 2.3, start_y - 2.3, 4.6, 4.6))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(34, 197, 94, 178))
        painter.drawEllipse(QRectF(target_rect.left() - 5.0, target_center.y() - 6.0, 12.0, 12.0))

        focus_rect = QRectF(target_center.x() - 64.0, outer.bottom() - 9.5, 128.0, 3.0)
        focus_gradient = QLinearGradient(focus_rect.left(), focus_rect.center().y(), focus_rect.right(), focus_rect.center().y())
        focus_gradient.setColorAt(0.0, QColor(34, 197, 94, 0))
        focus_gradient.setColorAt(0.5, QColor(34, 197, 94, 170))
        focus_gradient.setColorAt(1.0, QColor(34, 197, 94, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(focus_gradient)
        painter.drawRoundedRect(focus_rect, 1.5, 1.5)
        painter.restore()

    def _draw_tab(self, painter: QPainter, index: int) -> None:
        if not self.isTabVisible(index):
            return

        opt = QStyleOptionTab()
        self.initStyleOption(opt, index)

        rect = QRectF(self.tabRect(index)).adjusted(8.0, 6.0, -8.0, -8.0)
        if rect.width() <= 0 or rect.height() <= 0:
            return

        is_current = index == self.currentIndex()
        is_hover = index == self._hover_index
        is_pressed = index == self._pressed_index

        if is_pressed:
            rect = rect.translated(0.0, 1.0)

        text_color = QColor(self._active_text_color) if is_current else QColor(self._inactive_text_color)
        if is_hover and not is_current:
            text_color = QColor(self._hover_text_color)

        icon = self.tabIcon(index)
        has_icon = not icon.isNull()

        painter.save()
        if has_icon:
            icon_size = max(42, min(52, int(rect.height() * 0.52)))
            icon_rect = QRectF(
                rect.center().x() - (icon_size / 2.0),
                rect.top() + 9.0,
                float(icon_size),
                float(icon_size),
            )
            plate_rect = icon_rect.adjusted(-5.0, -5.0, 5.0, 5.0)
            painter.save()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(248, 250, 252, 232))
            painter.drawRoundedRect(plate_rect, 12.0, 12.0)
            painter.restore()

            pix = self._cached_icon_pixmap(index, icon, icon_size)
            if not pix.isNull():
                pix_size = pix.deviceIndependentSize()
                target = QRectF(icon_rect)
                if pix_size.width() > 0 and pix_size.height() > 0:
                    scale = min(icon_rect.width() / pix_size.width(), icon_rect.height() / pix_size.height())
                    target_w = pix_size.width() * scale
                    target_h = pix_size.height() * scale
                    target = QRectF(
                        icon_rect.center().x() - (target_w / 2.0),
                        icon_rect.center().y() - (target_h / 2.0),
                        target_w,
                        target_h,
                    )
                painter.drawPixmap(target.toRect(), pix)
            text_rect = QRectF(rect.left(), icon_rect.bottom() + 6.0, rect.width(), rect.height() - icon_rect.height() - 15.0)
            text_flags = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        else:
            text_rect = rect
            text_flags = Qt.AlignmentFlag.AlignCenter

        font = QFont(self.font())
        font.setPointSize(14)
        font.setBold(is_current or is_hover)
        painter.setFont(font)
        painter.setPen(text_color)
        painter.drawText(text_rect, text_flags, opt.text)
        painter.restore()

    def invalidate_icon_cache(self, index: int | None = None) -> None:
        if index is None:
            self._icon_pixmap_cache.clear()
            self._icon_pixmap_cache_order.clear()
            return
        prefix = int(index)
        remove_keys = [key for key in self._icon_pixmap_cache.keys() if key[0] == prefix]
        for key in remove_keys:
            self._icon_pixmap_cache.pop(key, None)
        if remove_keys:
            remove_set = set(remove_keys)
            self._icon_pixmap_cache_order = [key for key in self._icon_pixmap_cache_order if key not in remove_set]

    def _cached_icon_pixmap(self, index: int, icon: QIcon, icon_size: int) -> QPixmap:
        try:
            cache_key = int(icon.cacheKey())
        except Exception:
            cache_key = 0
        try:
            dpr = round(float(self.devicePixelRatioF()), 2)
        except Exception:
            dpr = 1.0
        key = (int(index), cache_key, int(icon_size), dpr)
        cached = self._icon_pixmap_cache.get(key)
        if cached is not None:
            return cached
        pix = icon.pixmap(QSize(icon_size, icon_size))
        self._icon_pixmap_cache[key] = pix
        self._icon_pixmap_cache_order.append(key)
        while len(self._icon_pixmap_cache_order) > self._icon_pixmap_cache_limit:
            old_key = self._icon_pixmap_cache_order.pop(0)
            self._icon_pixmap_cache.pop(old_key, None)
        return pix


class GlowTabWidget(QTabWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setTabBar(GlowTabBar(self))
        self._animated_tab_movies: dict[int, QMovie] = {}
        self.setDocumentMode(True)
        self.setMovable(False)
        self.setUsesScrollButtons(False)
        self.setTabPosition(QTabWidget.TabPosition.North)
        self.setStyleSheet(
            """
            QTabWidget::pane {
                border: none;
                background: transparent;
                margin-top: 8px;
            }
            """
        )

    def set_tab_palette(
        self,
        *,
        container_bg=None,
        container_border=None,
        indicator=None,
        text_active=None,
        text_inactive=None,
        text_hover=None,
    ) -> None:
        bar = self.tabBar()
        if isinstance(bar, GlowTabBar):
            bar.set_palette(
                container_bg=container_bg,
                container_border=container_border,
                indicator=indicator,
                text_active=text_active,
                text_inactive=text_inactive,
                text_hover=text_hover,
            )    

    def set_animated_tab_icon(
        self,
        index: int,
        gif_path: str,
        *,
        fallback_icon: QIcon | None = None,
        size: QSize | None = None,
    ) -> None:
        if index < 0 or index >= self.count():
            return

        path = str(gif_path or "").strip()
        if not path:
            if fallback_icon is not None:
                self.setTabIcon(index, fallback_icon)
            return

        movie = QMovie(path)
        if not movie.isValid():
            if fallback_icon is not None:
                self.setTabIcon(index, fallback_icon)
            return

        if size is None:
            size = QSize(40, 40)
        movie.setScaledSize(size)

        old_movie = self._animated_tab_movies.get(index)
        if old_movie is not None:
            try:
                old_movie.stop()
            except Exception:
                pass

        self._animated_tab_movies[index] = movie

        def _apply_current_frame(*_args) -> None:
            frame = movie.currentPixmap()
            if frame.isNull():
                return
            self.setTabIcon(index, QIcon(frame))
            bar = self.tabBar()
            if bar is not None:
                bar.update()

        movie.frameChanged.connect(_apply_current_frame)
        _apply_current_frame()
        movie.start()

    def setTabIcon(self, index: int, icon: QIcon) -> None:  # noqa: N802
        super().setTabIcon(index, icon)
        bar = self.tabBar()
        if isinstance(bar, GlowTabBar):
            bar.invalidate_icon_cache(index)


class SplitSidebarButton(QToolButton):
    _SHAPE_ALIASES = {
        "vertical": "vertical",
        "dikey": "vertical",
        "horizontal": "horizontal",
        "yatay": "horizontal",
        "circular": "circular",
        "circle": "circular",
        "round": "circular",
        "dairesel": "circular",
        "yuvarlak": "circular",
    }

    def __init__(
        self,
        text: str = "",
        parent: QWidget | None = None,
        icon_text: str = "",
        icon_path: str = "",
        shape: str = "vertical",
        icon_scale: float = 1.0,
    ):
        super().__init__(parent)
        self._active = False
        self._hover = False
        self._icon_text = str(icon_text or "").strip()
        self._icon_pixmap: QPixmap | None = None
        self._icon: QIcon | None = None
        self._icon_mass_offset: tuple[float, float] = (0.0, 0.0)
        self._shape = "vertical"
        self._icon_scale = 1.0
        self._icon_nudge_px: tuple[int, int] = (0, 0)
        self._label = self._compact_text(text)

        self.setText(self._label)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(86)
        self.setMinimumWidth(54)
        self.setAutoRaise(False)

        self._glow = QGraphicsDropShadowEffect(self)
        self._glow.setBlurRadius(24)
        self._glow.setOffset(0, 0)
        self._glow.setColor(QColor(59, 130, 246, 210))
        self.setGraphicsEffect(self._glow)
        self._glow.setEnabled(False)
        self.setShape(shape)
        self.setIconScale(icon_scale)
        self.setIconPath(icon_path)

    @classmethod
    def _normalize_shape(cls, shape: str) -> str:
        key = str(shape or "").strip().lower()
        return cls._SHAPE_ALIASES.get(key, "vertical")

    def setShape(self, shape: str) -> None:
        self._shape = self._normalize_shape(shape)
        if self._shape == "circular":
            side = 68
            self.setMinimumSize(side, side)
            self.setMaximumSize(side, side)
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        elif self._shape == "horizontal":
            self.setMaximumSize(16777215, 16777215)
            self.setMinimumHeight(54)
            self.setMinimumWidth(98)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        else:
            self.setMaximumSize(16777215, 16777215)
            self.setMinimumHeight(86)
            self.setMinimumWidth(54)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.update()

    def shape(self) -> str:
        return self._shape

    def setIconScale(self, scale: float) -> None:
        try:
            value = float(scale)
        except Exception:
            value = 1.0
        if value < 0.4:
            value = 0.4
        elif value > 1.6:
            value = 1.6
        self._icon_scale = value
        self.update()

    def setIconText(self, icon_text: str) -> None:
        self._icon_text = str(icon_text or "").strip()
        self.update()

    def setIconNudge(self, x_px: int = 0, y_px: int = 0) -> None:
        try:
            x_val = int(x_px)
        except Exception:
            x_val = 0
        try:
            y_val = int(y_px)
        except Exception:
            y_val = 0
        self._icon_nudge_px = (max(-16, min(16, x_val)), max(-16, min(16, y_val)))
        self.update()

    def setIconPath(self, icon_path: str) -> None:
        path = str(icon_path or "").strip()
        if not path:
            self._icon_pixmap = None
            self._icon = None
            self._icon_mass_offset = (0.0, 0.0)
            self.update()
            return
        signature = _quick_access_icon_signature(path)
        cached = _QUICK_ACCESS_ICON_CACHE.get(signature) if signature is not None else None
        if cached is not None:
            self._icon_pixmap = cached[0]
            self._icon = QIcon(cached[0])
            self._icon_mass_offset = cached[1]
            self.update()
            return
        pix = QPixmap(path)
        if pix.isNull():
            self._icon_pixmap = None
            self._icon = None
            self._icon_mass_offset = (0.0, 0.0)
            self.update()
            return
        pix = self._crop_transparent_margins(pix)
        self._icon_pixmap = pix
        self._icon = QIcon(pix)
        self._icon_mass_offset = self._compute_icon_mass_offset(pix)
        if signature is not None:
            if len(_QUICK_ACCESS_ICON_CACHE) >= _QUICK_ACCESS_ICON_CACHE_LIMIT:
                _QUICK_ACCESS_ICON_CACHE.clear()
            _QUICK_ACCESS_ICON_CACHE[signature] = (pix, self._icon_mass_offset)
        self.update()

    @staticmethod
    def _crop_transparent_margins(pix: QPixmap) -> QPixmap:
        if pix.isNull():
            return pix
        img: QImage = pix.toImage().convertToFormat(QImage.Format.Format_ARGB32)
        w, h = img.width(), img.height()
        min_x, min_y = w, h
        max_x, max_y = -1, -1
        threshold = 8
        for y in range(h):
            for x in range(w):
                if img.pixelColor(x, y).alpha() > threshold:
                    if x < min_x:
                        min_x = x
                    if y < min_y:
                        min_y = y
                    if x > max_x:
                        max_x = x
                    if y > max_y:
                        max_y = y
        if max_x < min_x or max_y < min_y:
            return pix
        rect = QRect(min_x, min_y, (max_x - min_x + 1), (max_y - min_y + 1))
        cropped = pix.copy(rect)
        return cropped if not cropped.isNull() else pix

    @staticmethod
    def _compute_icon_mass_offset(pix: QPixmap) -> tuple[float, float]:
        if pix.isNull():
            return 0.0, 0.0
        img = pix.toImage().convertToFormat(QImage.Format.Format_ARGB32)
        w, h = img.width(), img.height()
        if w <= 0 or h <= 0:
            return 0.0, 0.0
        sum_alpha = 0.0
        sum_x = 0.0
        sum_y = 0.0
        for yy in range(h):
            for xx in range(w):
                alpha = float(img.pixelColor(xx, yy).alpha())
                if alpha <= 0.0:
                    continue
                sum_alpha += alpha
                sum_x += xx * alpha
                sum_y += yy * alpha
        if sum_alpha <= 0.0:
            return 0.0, 0.0
        mass_x = sum_x / sum_alpha
        mass_y = sum_y / sum_alpha
        geom_x = (w - 1) / 2.0
        geom_y = (h - 1) / 2.0
        dx_norm = (mass_x - geom_x) / max(1.0, float(w))
        dy_norm = (mass_y - geom_y) / max(1.0, float(h))
        return dx_norm, dy_norm

    @staticmethod
    def _compact_text(text: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        if "\n" in raw:
            return raw
        words = raw.split()
        if len(words) <= 1:
            return raw
        if len(words) == 2:
            return f"{words[0]}\n{words[1]}"
        return f"{words[0]}\n{' '.join(words[1:])}"

    def setActive(self, active: bool) -> None:
        active = bool(active)
        if self._active == active:
            return
        self._active = active
        self._glow.setEnabled(self._active)
        self.update()

    def isActive(self) -> bool:
        return self._active

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        base_rect = QRectF(self.rect()).adjusted(5.0, 6.0, -5.0, -6.0)
        if self._shape == "circular":
            diameter = min(base_rect.width(), base_rect.height())
            rect = QRectF(
                base_rect.center().x() - diameter / 2.0,
                base_rect.center().y() - diameter / 2.0,
                diameter,
                diameter,
            )
            radius = diameter / 2.0
        elif self._shape == "horizontal":
            target_h = min(54.0, base_rect.height())
            rect = QRectF(
                base_rect.left(),
                base_rect.center().y() - target_h / 2.0,
                base_rect.width(),
                target_h,
            )
            radius = rect.height() / 2.0
        else:
            rect = base_rect
            radius = 10.0

        if self._shape == "circular":
            text_color = QColor("#0F172A")
            indicator = QColor(0, 0, 0, 0)
            border = QColor(0, 0, 0, 0)
            bg = QColor(255, 255, 255, 0)
        elif self._active:
            bg = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            bg.setColorAt(0.0, QColor("#3B82F6"))
            bg.setColorAt(1.0, QColor("#2563EB"))
            border = QColor("#93C5FD")
            text_color = QColor("#FFFFFF")
            indicator = QColor("#E0ECFF")
        elif self._hover:
            bg = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            bg.setColorAt(0.0, QColor("#F8FBFF"))
            bg.setColorAt(1.0, QColor("#E8F1FF"))
            border = QColor("#BFDBFE")
            text_color = QColor("#1E3A8A")
            indicator = QColor("#93C5FD")
        else:
            bg = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            bg.setColorAt(0.0, QColor("#F8FAFC"))
            bg.setColorAt(1.0, QColor("#EEF2F7"))
            border = QColor("#CBD5E1")
            text_color = QColor("#334155")
            indicator = QColor(0, 0, 0, 0)

        if self._shape == "circular":
            pass
        else:
            p.setPen(QPen(border, 1.0))
            p.setBrush(bg)
            p.drawRoundedRect(rect, radius, radius)

        if self._active and self._shape != "circular":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(indicator)
            if self._shape == "horizontal":
                indicator_rect = QRectF(rect.left() + 10, rect.top() + 2, rect.width() - 20, 3)
                p.drawRoundedRect(indicator_rect, 1.5, 1.5)
            else:
                indicator_rect = QRectF(rect.left() + 2, rect.top() + 8, 3, rect.height() - 16)
                p.drawRoundedRect(indicator_rect, 1.5, 1.5)

        if self._icon_pixmap is not None and not str(self.text() or "").strip():
            base_dim = min(rect.width(), rect.height())
            if self._shape == "circular":
                icon_size = int(base_dim * 0.74)
            elif self._shape == "horizontal":
                icon_size = int(base_dim * 0.54)
            else:
                icon_size = int(base_dim * 0.58)
            if self._active or self._hover:
                icon_size += 2
            icon_size = max(14, int(icon_size * self._icon_scale))
            if self._icon is not None:
                pix = self._icon.pixmap(icon_size, icon_size)
            else:
                pix = self._icon_pixmap.scaled(
                    icon_size,
                    icon_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            dx_norm, dy_norm = self._icon_mass_offset
            if self._shape == "circular":
                dx_norm, dy_norm = 0.0, 0.0
            x = int(round(rect.x() + (rect.width() - pix.width()) / 2.0 - (dx_norm * pix.width())))
            y = int(round(rect.y() + (rect.height() - pix.height()) / 2.0 - (dy_norm * pix.height())))
            nudge_x, nudge_y = self._icon_nudge_px
            x += nudge_x
            y += nudge_y
            p.drawPixmap(x, y, pix)
        elif self._icon_text and not str(self.text() or "").strip():
            icon_font = QFont(self.font())
            icon_font.setPointSize(18 if self._active else 16)
            icon_font.setBold(self._active or self._hover)
            p.setFont(icon_font)
            p.setPen(text_color)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._icon_text)
        else:
            font = QFont(self.font())
            font.setPointSize(9)
            font.setBold(self._active or self._hover)
            p.setFont(font)
            p.setPen(text_color)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())


class SplitPanelSidebar(QFrame):
    panel_toggled = pyqtSignal(str, bool)

    def __init__(self, parent: QWidget | None = None, *, sidebar_width: int = 68):
        super().__init__(parent)
        self._buttons: dict[str, SplitSidebarButton] = {}
        self._active_panel: str | None = None

        self.setObjectName("OsSplitSidebar")
        self.setFixedWidth(max(56, int(sidebar_width)))
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(10)
        self._buttons_layout = QVBoxLayout()
        # Sidebar içindeki ikon-butonu kolonunu yatayda hafif sağa kaydır.
        self._buttons_layout.setContentsMargins(7, 0, 0, 0)
        self._buttons_layout.setSpacing(8)
        root.addLayout(self._buttons_layout)
        root.addStretch(1)

        self.setStyleSheet(
            """
            QFrame#OsSplitSidebar {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #F6FAFF,
                    stop:1 #EEF4FC
                );
                border: 1px solid rgba(148, 163, 184, 72);
                border-radius: 14px;
            }
            """
        )

    def add_panel_button(
        self,
        panel_id: str,
        text: str,
        *,
        tooltip: str | None = None,
        icon_text: str = "",
        icon_path: str = "",
        shape: str = "vertical",
        icon_scale: float = 1.0,
        icon_nudge_x: int = 0,
        icon_nudge_y: int = 0,
    ) -> SplitSidebarButton:
        if panel_id in self._buttons:
            raise ValueError(f"Duplicate panel id: {panel_id}")
        button = SplitSidebarButton(
            text,
            self,
            icon_text=icon_text,
            icon_path=icon_path,
            shape=shape,
            icon_scale=icon_scale,
        )
        if tooltip:
            button.setToolTip(tooltip)
        button.setIconNudge(icon_nudge_x, icon_nudge_y)
        button.clicked.connect(lambda _=False, pid=panel_id: self._on_button_clicked(pid))
        self._buttons[panel_id] = button
        if button.shape() == "circular":
            self._buttons_layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignHCenter)
        else:
            self._buttons_layout.addWidget(button)
        return button

    def _on_button_clicked(self, panel_id: str) -> None:
        if self._active_panel == panel_id:
            self.set_active_panel(None)
            self.panel_toggled.emit(panel_id, False)
            return
        self.set_active_panel(panel_id)
        self.panel_toggled.emit(panel_id, True)

    def set_active_panel(self, panel_id: str | None) -> None:
        self._active_panel = panel_id if panel_id in self._buttons else None
        for pid, btn in self._buttons.items():
            btn.setActive(pid == self._active_panel)

    def active_panel(self) -> str | None:
        return self._active_panel


class DashboardHeroCard(QFrame):
    def __init__(
        self,
        *,
        title: str,
        subtitle: str = "",
        action_text: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("OsHeroCard")
        self.setMinimumHeight(94)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(14)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(4)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("OsHeroTitle")
        text_col.addWidget(self.title_label)

        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("OsHeroSubtitle")
        self.subtitle_label.setWordWrap(True)
        text_col.addWidget(self.subtitle_label)

        layout.addLayout(text_col, 1)

        self.action_button = QPushButton(action_text) if action_text else None
        if self.action_button is not None:
            self.action_button.setObjectName("OsHeroAction")
            self.action_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.action_button.setMinimumHeight(44)
            self.action_button.setMinimumWidth(152)
            layout.addWidget(self.action_button, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.setStyleSheet(
            """
            QFrame#OsHeroCard {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(255,255,255,0.98),
                    stop:0.55 rgba(247,250,255,0.98),
                    stop:1 rgba(243,248,255,0.98)
                );
                border: 1px solid rgba(15, 23, 42, 0.06);
                border-radius: 20px;
            }
            QLabel#OsHeroTitle {
                font-size: 18px;
                font-weight: 900;
                color: #0F172A;
            }
            QLabel#OsHeroSubtitle {
                font-size: 12px;
                color: rgba(15, 23, 42, 0.66);
            }
            QPushButton#OsHeroAction {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #2563EB,
                    stop:1 #1D4ED8
                );
                color: #FFFFFF;
                border: 0px;
                border-radius: 12px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: 900;
            }
            QPushButton#OsHeroAction:hover {
                background: #1D4ED8;
            }
            QPushButton#OsHeroAction:pressed {
                background: #1E40AF;
                padding-top: 9px;
            }
            """
        )

class QuickAccessSection(QFrame):
    def __init__(
        self,
        *,
        title: str = "Hızlı Erişim",
        subtitle: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("OsQuickAccessCard")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        self.title_label = QLabel(title, self)
        self.title_label.setObjectName("OsQuickAccessTitle")
        root.addWidget(self.title_label)

        self.subtitle_label = QLabel(subtitle, self)
        self.subtitle_label.setObjectName("OsQuickAccessSubtitle")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setVisible(bool(str(subtitle or "").strip()))
        root.addWidget(self.subtitle_label)

        self.body = QWidget(self)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 4, 0, 0)
        self.body_layout.setSpacing(12)
        root.addWidget(self.body, 1)

        self.setStyleSheet(
            """
            QFrame#OsQuickAccessCard {
                background: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 16px;
            }
            QLabel#OsQuickAccessTitle {
                font-size: 14px;
                font-weight: 900;
                color: #0F172A;
            }
            QLabel#OsQuickAccessSubtitle {
                font-size: 12px;
                color: #64748B;
            }
            """
        )

    def set_subtitle(self, text: str) -> None:
        self.subtitle_label.setText(text or "")
        self.subtitle_label.setVisible(bool(str(text or "").strip()))

