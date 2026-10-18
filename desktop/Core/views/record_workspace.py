from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable

from PyQt6.QtCore import QAbstractListModel, QEvent, QModelIndex, QObject, QPoint, QRect, QSize, QSignalBlocker, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListView,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)
from Core.constants.ui_constants import (
    RECORD_WORKSPACE_EMPTY_TEXT,
    RECORD_WORKSPACE_NEXT_BUTTON_TEXT,
    RECORD_WORKSPACE_PAGE_LABEL_TEMPLATE,
    RECORD_WORKSPACE_PAGE_SIZE_LABEL,
    RECORD_WORKSPACE_PREV_BUTTON_TEXT,
    RECORD_WORKSPACE_SELECT_BUTTON_TEXT,
    RECORD_WORKSPACE_STYLE,
)

from .controls import SelectClearToggleButton
from .splitters import ListLoadingOverlay, ResettableSplitter
from .tab_widgets import SplitPanelSidebar


def compose_record_workspace_style(*chunks: str) -> str:
    parts: list[str] = [RECORD_WORKSPACE_STYLE.strip()]
    for chunk in chunks:
        text = str(chunk or "")
        if text.strip():
            parts.append(text.strip())
    return "\n\n".join(parts)


@dataclass
class RecordWorkspaceCardRecord:
    orderNumber: str
    title: str
    subtitle: str
    extra: str
    logo_path: str
    payload: object = None
    action_text: str = ""
    _selected: bool = False

    @property
    def recordKey(self) -> str:
        return str(self.orderNumber or "").strip()


class RecordWorkspaceListModel(QAbstractListModel):
    TitleRole = Qt.ItemDataRole.UserRole + 1
    SubtitleRole = Qt.ItemDataRole.UserRole + 2
    ExtraRole = Qt.ItemDataRole.UserRole + 3
    IconRole = Qt.ItemDataRole.UserRole + 4
    RecordRole = Qt.ItemDataRole.UserRole + 5
    SelectedRole = Qt.ItemDataRole.UserRole + 6
    PlaceholderRole = Qt.ItemDataRole.UserRole + 7
    ActiveRole = Qt.ItemDataRole.UserRole + 8
    ActionTextRole = Qt.ItemDataRole.UserRole + 9

    def __init__(self, parent=None, *, empty_placeholder_text: str):
        super().__init__(parent)
        self._items: list[object] = []
        self._has_placeholder = False
        self._active_row: int = -1
        self._empty_placeholder_text = str(empty_placeholder_text or RECORD_WORKSPACE_EMPTY_TEXT)
        self._row_by_key: dict[str, int] = {}
        self._row_by_record_id: dict[int, int] = {}

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._items)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self._items):
            return None
        item = self._items[row]
        if self._is_placeholder_item(item):
            if role in (Qt.ItemDataRole.DisplayRole, self.TitleRole):
                return item.get("title") or ""
            if role == self.PlaceholderRole:
                return True
            return None
        record = self._record_from_item(item)
        if role in (Qt.ItemDataRole.DisplayRole, self.TitleRole):
            return getattr(record, "title", "") or ""
        if role == self.SubtitleRole:
            return getattr(record, "subtitle", "") or ""
        if role == self.ExtraRole:
            return getattr(record, "extra", "") or ""
        if role == self.IconRole:
            return getattr(record, "logo_path", "") or ""
        if role == self.RecordRole:
            return record
        if role == self.SelectedRole:
            return bool(getattr(record, "_selected", False))
        if role == self.PlaceholderRole:
            return False
        if role == self.ActiveRole:
            return row == self._active_row
        if role == self.ActionTextRole:
            return str(getattr(record, "action_text", "") or "")
        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled

    def set_records(self, records: list[RecordWorkspaceCardRecord]) -> None:
        self.beginResetModel()
        self._active_row = -1
        self._row_by_key = {}
        self._row_by_record_id = {}
        if records:
            self._items = list(records)
            self._has_placeholder = False
            self._rebuild_row_lookup()
        else:
            self._items = [{"placeholder": True, "title": self._empty_placeholder_text}]
            self._has_placeholder = True
        self.endResetModel()

    @staticmethod
    def _is_placeholder_item(item: object) -> bool:
        return isinstance(item, dict) and bool(item.get("placeholder"))

    @staticmethod
    def _record_from_item(item: object):
        if isinstance(item, dict):
            return item.get("record")
        return item

    @staticmethod
    def _record_key_of(record) -> str:
        return str(getattr(record, "recordKey", getattr(record, "orderNumber", "")) or "").strip().upper()

    def _rebuild_row_lookup(self) -> None:
        row_by_key: dict[str, int] = {}
        row_by_record_id: dict[int, int] = {}
        for row, item in enumerate(self._items):
            if not item or self._is_placeholder_item(item):
                continue
            record = self._record_from_item(item)
            if record is None:
                continue
            row_by_record_id[id(record)] = row
            key = self._record_key_of(record)
            if key:
                row_by_key.setdefault(key, row)
        self._row_by_key = row_by_key
        self._row_by_record_id = row_by_record_id

    def visible_count(self) -> int:
        return 0 if self._has_placeholder else len(self._items)

    def item_at(self, row: int):
        if row < 0 or row >= len(self._items):
            return None
        return self._items[row]

    def record_at(self, row: int):
        item = self.item_at(row)
        if item is None or self._is_placeholder_item(item):
            return None
        return self._record_from_item(item)

    def row_for_record(self, record) -> int:
        if record is None:
            return -1
        return int(self._row_by_record_id.get(id(record), -1))

    def row_for_key(self, key: str) -> int:
        needle = str(key or "").strip().upper()
        if not needle:
            return -1
        return int(self._row_by_key.get(needle, -1))

    def set_selected(self, row: int, selected: bool) -> None:
        record = self.record_at(row)
        if record is None:
            return
        setattr(record, "_selected", bool(selected))
        idx = self.index(row)
        self.dataChanged.emit(idx, idx, [self.SelectedRole])

    def set_active_row(self, row: int) -> None:
        if self._has_placeholder:
            row = -1
        if row < 0 or row >= len(self._items):
            row = -1
        elif self._is_placeholder_item(self._items[row]):
            row = -1
        if self._active_row == row:
            return
        previous = self._active_row
        self._active_row = row
        if previous >= 0:
            previous_idx = self.index(previous)
            self.dataChanged.emit(previous_idx, previous_idx, [self.ActiveRole])
        if row >= 0:
            current_idx = self.index(row)
            self.dataChanged.emit(current_idx, current_idx, [self.ActiveRole])

    def clear_active_row(self) -> None:
        self.set_active_row(-1)


class RecordWorkspaceListDelegate(QStyledItemDelegate):
    def __init__(self, parent=None, *, on_select_button=None):
        super().__init__(parent)
        self._icon_cache: dict[tuple[str, int, float], QPixmap] = {}
        self._icon_cache_limit = 256
        self._icon_size = 52
        self._row_height = 108
        self._hover_row: int | None = None
        self._pressed_row: int | None = None
        self._on_select_button = on_select_button
        self._spin_phase: float = 0.0
        self._active_visual_enabled: bool = True
        self._guide_select_enabled: bool = False
        self._guide_phase: float = 0.0
        self._hook_w = 44
        self._hook_h = 30
        self._hook_horizontal_padding = 22
        self._hook_font_cached = QFont("Segoe UI", 8, QFont.Weight.Bold)
        self._placeholder_font = QFont("Segoe UI", 9)
        self._title_font = QFont("Segoe UI", 10, QFont.Weight.Bold)
        self._value_fonts: dict[int, QFont] = {}
        self._key_fonts: dict[int, QFont] = {}
        self._sep_fonts: dict[int, QFont] = {}

    def advance_spin_phase(self, step: float = 1.0) -> None:
        self._spin_phase = (self._spin_phase + max(0.1, float(step))) % 1024.0

    def reset_spin_phase(self) -> None:
        self._spin_phase = 0.0

    def set_active_visual_enabled(self, enabled: bool) -> None:
        self._active_visual_enabled = bool(enabled)

    def advance_guide_phase(self, step: float = 1.0) -> None:
        self._guide_phase = (self._guide_phase + max(0.1, float(step))) % 1024.0

    def reset_guide_phase(self) -> None:
        self._guide_phase = 0.0

    def set_guide_select_enabled(self, enabled: bool) -> None:
        self._guide_select_enabled = bool(enabled)

    def _item_rect(self, option: QStyleOptionViewItem) -> QRect:
        return option.rect.adjusted(6, 4, -6, -4)

    def _is_placeholder_index(self, index: QModelIndex) -> bool:
        return bool(index.data(RecordWorkspaceListModel.PlaceholderRole))

    def _is_selected_index(self, index: QModelIndex) -> bool:
        return bool(index.data(RecordWorkspaceListModel.SelectedRole))

    def _is_active_index(self, index: QModelIndex) -> bool:
        return bool(index.data(RecordWorkspaceListModel.ActiveRole))

    def _is_hook_selected_index(self, index: QModelIndex) -> bool:
        return self._is_selected_index(index)

    def _hook_text(self, index: QModelIndex) -> str:
        return str(index.data(RecordWorkspaceListModel.ActionTextRole) or RECORD_WORKSPACE_SELECT_BUTTON_TEXT)

    def _hook_font(self) -> QFont:
        return self._hook_font_cached

    def _value_font(self, point_size: int) -> QFont:
        size = int(point_size or 8)
        font = self._value_fonts.get(size)
        if font is None:
            font = QFont("Segoe UI", size)
            self._value_fonts[size] = font
        return font

    def _key_font(self, point_size: int) -> QFont:
        size = int(point_size or 8)
        font = self._key_fonts.get(size)
        if font is None:
            font = QFont("Segoe UI", size, QFont.Weight.Bold)
            self._key_fonts[size] = font
        return font

    def _sep_font(self, point_size: int) -> QFont:
        size = int(point_size or 8)
        font = self._sep_fonts.get(size)
        if font is None:
            font = QFont("Segoe UI", size)
            self._sep_fonts[size] = font
        return font

    def _hook_width_for_index(self, index: QModelIndex, *, minimum: int | None = None) -> int:
        text = str(self._hook_text(index) or "").strip()
        base_width = int(self._hook_w if minimum is None else minimum)
        if not text:
            return base_width
        metrics = QFontMetrics(self._hook_font())
        text_width = metrics.horizontalAdvance(text)
        return max(base_width, text_width + int(self._hook_horizontal_padding))

    def _load_icon(self, path: str, dpr: float) -> QPixmap | None:
        if not path:
            return None
        key = (path, self._icon_size, float(dpr))
        pix_cached = self._icon_cache.get(key)
        if pix_cached is not None:
            return pix_cached
        pix = QPixmap(path)
        if pix.isNull():
            return None
        target = int(self._icon_size * dpr)
        pix = pix.scaled(
            target,
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        pix.setDevicePixelRatio(dpr)
        if len(self._icon_cache) >= self._icon_cache_limit:
            self._icon_cache.clear()
        self._icon_cache[key] = pix
        return pix

    def _hook_layout_metrics(self, rect: QRect, view=None) -> tuple[int, int]:
        scrollbar_gap = 0
        right_edge = rect.right()
        scroll_host = None

        if view is not None:
            if hasattr(view, "verticalScrollBar"):
                scroll_host = view
            elif hasattr(view, "parent"):
                parent = view.parent()
                if parent is not None and hasattr(parent, "verticalScrollBar"):
                    scroll_host = parent

        if scroll_host is None:
            parent = self.parent()
            if parent is not None and hasattr(parent, "verticalScrollBar"):
                scroll_host = parent

        if scroll_host is not None:
            try:
                if hasattr(scroll_host, "viewport") and scroll_host.viewport() is not None:
                    vp_right = int(scroll_host.viewport().rect().right())
                    right_edge = min(right_edge, vp_right)
                sb = scroll_host.verticalScrollBar()
                if sb is not None and sb.isVisible():
                    scrollbar_gap = int(sb.width()) + 6
            except Exception:
                scrollbar_gap = 0

        return right_edge, scrollbar_gap

    def _hook_content_right(self, rect: QRect, view=None, *, right_margin: int = 10) -> int:
        right_edge, scrollbar_gap = self._hook_layout_metrics(rect, view=view)
        return right_edge - int(right_margin) - scrollbar_gap

    def _build_hook_rect(
        self,
        rect: QRect,
        *,
        view=None,
        content_right: int | None = None,
        vertical_rect: QRect | None = None,
        left_margin: int = 8,
        right_margin: int = 10,
        hook_w: int | None = None,
        hook_h: int | None = None,
    ) -> QRect:
        hook_w = int(self._hook_w if hook_w is None else hook_w)
        hook_h = int(self._hook_h if hook_h is None else hook_h)
        if content_right is None:
            content_right = self._hook_content_right(rect, view=view, right_margin=right_margin)
        available = max(1, int(content_right) - (rect.left() + int(left_margin)))
        hook_w = max(16, min(hook_w, available))
        x = max(rect.left() + int(left_margin), int(content_right) - hook_w)
        anchor_rect = vertical_rect if vertical_rect is not None else rect
        y = anchor_rect.center().y() - hook_h // 2
        return QRect(x, y, hook_w, hook_h)

    def _hook_rect(self, rect: QRect, view=None) -> QRect:
        return self._build_hook_rect(rect, view=view)

    def _hook_rect_for_index(self, rect: QRect, index: QModelIndex, view=None) -> QRect:
        return self._build_hook_rect(
            rect,
            view=view,
            hook_w=self._hook_width_for_index(index),
        )

    def _paint_placeholder(self, painter: QPainter, rect: QRect, index: QModelIndex) -> None:
        painter.setPen(QColor("#6B7280"))
        painter.setFont(self._placeholder_font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, index.data(RecordWorkspaceListModel.TitleRole) or "")

    def _paint_card_surface(
        self,
        painter: QPainter,
        rect: QRect,
        *,
        hovered: bool,
        card_selected: bool,
        active_visible: bool,
    ) -> None:
        bg = QColor("#FFFFFF")
        border = QColor(0, 0, 0, 0)
        if card_selected or active_visible:
            bg = QColor("#EFF6FF")
            border = QColor("#60A5FA")
        elif hovered:
            bg = QColor("#F8FAFC")
            border = QColor(226, 232, 240)

        painter.setBrush(bg)
        painter.setPen(QPen(border, 1))
        painter.drawRoundedRect(rect, 10, 10)

        if not active_visible:
            return

        spin_rect = rect.adjusted(1, 1, -1, -1)
        spin_pen = QPen(QColor("#2563EB"), 2)
        spin_pen.setStyle(Qt.PenStyle.CustomDashLine)
        spin_pen.setDashPattern([9, 6])
        spin_pen.setDashOffset(-self._spin_phase)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(spin_pen)
        painter.drawRoundedRect(spin_rect, 10, 10)

    def _icon_rect(self, rect: QRect) -> QRect:
        x = rect.left() + 10
        return QRect(x, rect.center().y() - self._icon_size // 2, self._icon_size, self._icon_size)

    def _paint_card_icon(self, painter: QPainter, index: QModelIndex, icon_rect: QRect) -> None:
        icon_path = index.data(RecordWorkspaceListModel.IconRole) or ""
        dpr = painter.device().devicePixelRatioF()
        pix = self._load_icon(icon_path, dpr)
        if pix is not None:
            pr = pix.devicePixelRatio() or 1.0
            pw = int(pix.width() / pr)
            ph = int(pix.height() / pr)
            target = QRect(0, 0, pw, ph)
            target.moveCenter(icon_rect.center())
            painter.drawPixmap(target, pix)
            return
        painter.setBrush(QColor("#E5E7EB"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(icon_rect, 8, 8)

    def _content_left(self, rect: QRect) -> int:
        return self._icon_rect(rect).right() + 12

    def _text_right(self, rect: QRect, hook_rect: QRect) -> int:
        return hook_rect.left() - 10

    def _text_width(self, rect: QRect, hook_rect: QRect) -> int:
        return max(10, self._text_right(rect, hook_rect) - self._content_left(rect))

    @staticmethod
    def _split_label_value(text: str) -> tuple[str, str]:
        raw = str(text or "").strip()
        if not raw:
            return "", ""
        if ":" not in raw:
            return "", raw
        label, value = raw.split(":", 1)
        return f"{label.strip()}:", value.strip()

    def _draw_labeled_single_line(
        self,
        painter: QPainter,
        rect: QRect,
        text: str,
        *,
        key_color: QColor,
        value_color: QColor,
        point_size: int = 8,
    ) -> None:
        label, value = self._split_label_value(text)
        value_font = self._value_font(point_size)

        if not label:
            painter.setPen(value_color)
            painter.setFont(value_font)
            fm = painter.fontMetrics()
            painter.drawText(
                rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                fm.elidedText(str(value or text or ""), Qt.TextElideMode.ElideRight, rect.width()),
            )
            return

        key_font = self._key_font(point_size)
        key_token = f"{label} "

        painter.setFont(key_font)
        key_fm = painter.fontMetrics()
        key_width = key_fm.horizontalAdvance(key_token)

        if key_width >= rect.width():
            painter.setPen(key_color)
            painter.drawText(
                rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                key_fm.elidedText(label, Qt.TextElideMode.ElideRight, rect.width()),
            )
            return

        painter.setPen(key_color)
        painter.drawText(
            QRect(rect.left(), rect.top(), key_width, rect.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            key_token,
        )

        painter.setPen(value_color)
        painter.setFont(value_font)
        value_width = max(0, rect.width() - key_width)
        value_fm = painter.fontMetrics()
        painter.drawText(
            QRect(rect.left() + key_width, rect.top(), value_width, rect.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            value_fm.elidedText(value, Qt.TextElideMode.ElideRight, value_width),
        )

    def _draw_labeled_segments_line(
        self,
        painter: QPainter,
        rect: QRect,
        text: str,
        *,
        key_color: QColor,
        value_color: QColor,
        point_size: int = 8,
    ) -> None:
        raw = str(text or "").strip()
        if not raw:
            return

        segments = [part.strip() for part in raw.split("|") if part and part.strip()]
        if not segments:
            self._draw_labeled_single_line(
                painter,
                rect,
                raw,
                key_color=key_color,
                value_color=value_color,
                point_size=point_size,
            )
            return

        key_font = self._key_font(point_size)
        value_font = self._value_font(point_size)
        sep_font = self._sep_font(point_size)
        sep_color = QColor("#9CA3AF")

        x = rect.left()
        remaining = rect.width()
        y = rect.top()
        h = rect.height()

        for idx, segment in enumerate(segments):
            if remaining <= 0:
                return

            if idx > 0:
                sep_text = " | "
                painter.setFont(sep_font)
                sep_fm = painter.fontMetrics()
                sep_w = sep_fm.horizontalAdvance(sep_text)
                if sep_w >= remaining:
                    painter.setPen(value_color)
                    painter.drawText(
                        QRect(x, y, remaining, h),
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                        "...",
                    )
                    return
                painter.setPen(sep_color)
                painter.drawText(
                    QRect(x, y, sep_w, h),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    sep_text,
                )
                x += sep_w
                remaining -= sep_w

            label, value = self._split_label_value(segment)
            source_value = value if label else segment

            if label:
                key_token = f"{label} "
                painter.setFont(key_font)
                key_fm = painter.fontMetrics()
                key_w = key_fm.horizontalAdvance(key_token)
                if key_w >= remaining:
                    painter.setPen(key_color)
                    painter.drawText(
                        QRect(x, y, remaining, h),
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                        key_fm.elidedText(label, Qt.TextElideMode.ElideRight, remaining),
                    )
                    return
                painter.setPen(key_color)
                painter.drawText(
                    QRect(x, y, key_w, h),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    key_token,
                )
                x += key_w
                remaining -= key_w

            painter.setFont(value_font)
            value_fm = painter.fontMetrics()

            if idx == len(segments) - 1:
                value_text = value_fm.elidedText(source_value, Qt.TextElideMode.ElideRight, remaining)
                painter.setPen(value_color)
                painter.drawText(
                    QRect(x, y, remaining, h),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    value_text,
                )
                return

            painter.setFont(sep_font)
            sep_fm = painter.fontMetrics()
            reserve = sep_fm.horizontalAdvance(" | ") + value_fm.horizontalAdvance("...")
            painter.setFont(value_font)
            value_fm = painter.fontMetrics()
            allowance = max(0, remaining - reserve)
            if allowance <= 0:
                painter.setPen(value_color)
                painter.drawText(
                    QRect(x, y, remaining, h),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    "...",
                )
                return

            value_text = value_fm.elidedText(source_value, Qt.TextElideMode.ElideRight, allowance)
            painter.setPen(value_color)
            painter.drawText(
                QRect(x, y, allowance, h),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                value_text,
            )
            used = value_fm.horizontalAdvance(value_text)
            x += used
            remaining -= used

            if value_text != source_value:
                return

    def _paint_card_content(self, painter: QPainter, rect: QRect, index: QModelIndex, hook_rect: QRect) -> None:
        title = index.data(RecordWorkspaceListModel.TitleRole) or ""
        subtitle = index.data(RecordWorkspaceListModel.SubtitleRole) or ""
        extra = index.data(RecordWorkspaceListModel.ExtraRole) or ""

        icon_rect = self._icon_rect(rect)
        self._paint_card_icon(painter, index, icon_rect)

        x = self._content_left(rect)
        text_width = self._text_width(rect, hook_rect)

        painter.setPen(QColor("#111827"))
        painter.setFont(self._title_font)
        title_rect = QRect(x, rect.top() + 18, text_width, 20)
        fm = painter.fontMetrics()
        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            fm.elidedText(title, Qt.TextElideMode.ElideRight, title_rect.width()),
        )

        sub_rect = QRect(x, title_rect.bottom() + 4, text_width, 18)
        self._draw_labeled_single_line(
            painter,
            sub_rect,
            subtitle,
            key_color=QColor("#111827"),
            value_color=QColor("#374151"),
            point_size=8,
        )

        extra_rect = QRect(x, sub_rect.bottom() + 2, text_width, 18)
        self._draw_labeled_segments_line(
            painter,
            extra_rect,
            extra,
            key_color=QColor("#111827"),
            value_color=QColor("#6B7280"),
            point_size=8,
        )


    def _paint_hook_button(
        self,
        painter: QPainter,
        hook_rect: QRect,
        *,
        index: QModelIndex,
        row: int,
        hook_selected: bool,
    ) -> None:
        hover_hook = self._hover_row == row
        pressed_hook = self._pressed_row == row
        hook_draw = hook_rect
        if pressed_hook:
            hook_draw = hook_rect.adjusted(1, 1, -1, -1)
            painter.setBrush(QColor("#E2E8F0"))
            painter.setPen(QPen(QColor("#94A3B8"), 1))
        elif hover_hook:
            painter.setBrush(QColor("#F1F5F9"))
            painter.setPen(QPen(QColor("#CBD5E1"), 1))
        elif hook_selected:
            painter.setBrush(QColor("#DCFCE7"))
            painter.setPen(QPen(QColor("#22C55E"), 1))
        elif self._guide_select_enabled:
            guide_pen = QPen(QColor("#3B82F6"), 2)
            guide_pen.setStyle(Qt.PenStyle.CustomDashLine)
            guide_pen.setDashPattern([8, 6])
            guide_pen.setDashOffset(-self._guide_phase)
            painter.setBrush(QColor("#EFF6FF"))
            painter.setPen(guide_pen)
        else:
            painter.setBrush(QColor("#F8FAFC"))
            painter.setPen(QPen(QColor("#CBD5E1"), 1))
        painter.drawRoundedRect(hook_draw, 8, 8)

        if hook_selected:
            painter.setPen(QPen(QColor("#166534"), 2))
            cx = hook_rect.center().x()
            cy = hook_rect.center().y()
            painter.drawLine(cx - 6, cy, cx - 1, cy + 5)
            painter.drawLine(cx - 1, cy + 5, cx + 7, cy - 4)
            return

        painter.setPen(QColor("#475569"))
        painter.setFont(self._hook_font())
        painter.drawText(hook_rect, Qt.AlignmentFlag.AlignCenter, self._hook_text(index))

    @staticmethod
    def _mark_view_action_click_handled(view) -> None:
        if view is None:
            return
        for method_name in ("_mark_hook_click_handled", "_mark_action_button_click_handled"):
            marker = getattr(view, method_name, None)
            if not callable(marker):
                continue
            try:
                marker()
            except Exception:
                continue
            return

    @staticmethod
    def _update_view_row(view, index: QModelIndex, fallback_rect: QRect) -> None:
        if view is None:
            return
        viewport = view.viewport()
        if viewport is None:
            return
        rect = QRect(fallback_rect)
        try:
            visual_rect = view.visualRect(index)
            if visual_rect.isValid() and not visual_rect.isNull():
                rect = visual_rect
        except Exception:
            pass
        viewport.update(rect.adjusted(-2, -2, 2, 2))

    def _handle_hook_activated(self, model, index: QModelIndex, next_selected: bool) -> bool:
        handled = False
        if self._on_select_button:
            try:
                handled = bool(self._on_select_button(index, next_selected))
            except Exception:
                handled = False
        if not handled and hasattr(model, "set_bulk_selected_row"):
            model.set_bulk_selected_row(index.row(), next_selected)
            handled = True
        if not handled and hasattr(model, "set_selected"):
            model.set_selected(index.row(), next_selected)
            handled = True
        return handled

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        rect = self._item_rect(option)
        row = index.row()
        is_placeholder = self._is_placeholder_index(index)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        selected_flag = self._is_selected_index(index)
        hook_selected = self._is_hook_selected_index(index)
        active_flag = self._is_active_index(index)
        active_visible = active_flag and self._active_visual_enabled

        if is_placeholder:
            self._paint_placeholder(painter, rect, index)
            painter.restore()
            return

        hook_rect = self._hook_rect_for_index(rect, index, option.widget)
        self._paint_card_surface(
            painter,
            rect,
            hovered=hovered,
            card_selected=bool(selected_flag or hook_selected),
            active_visible=active_visible,
        )
        self._paint_card_content(painter, rect, index, hook_rect)
        self._paint_hook_button(
            painter,
            hook_rect,
            index=index,
            row=row,
            hook_selected=hook_selected,
        )

        painter.restore()

    def editorEvent(self, event, model, option, index):
        if self._is_placeholder_index(index):
            return False
        rect = self._item_rect(option)
        view = option.widget
        hook_rect = self._hook_rect_for_index(rect, index, view)
        if event.type() == QEvent.Type.MouseMove:
            pos = event.position().toPoint()
            hovering = hook_rect.contains(pos)
            if hovering and self._hover_row != index.row():
                self._hover_row = index.row()
                if view:
                    view.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
                    self._update_view_row(view, index, option.rect)
            elif not hovering and self._hover_row == index.row():
                self._hover_row = None
                if view:
                    view.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
                    self._update_view_row(view, index, option.rect)
        if event.type() == QEvent.Type.Leave:
            if self._hover_row is not None:
                self._hover_row = None
                if view:
                    view.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
                    self._update_view_row(view, index, option.rect)
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            if hook_rect.contains(pos):
                self._pressed_row = index.row()
                if view:
                    self._update_view_row(view, index, option.rect)
                return True
        if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            was_pressed = self._pressed_row == index.row()
            self._pressed_row = None
            if view:
                self._update_view_row(view, index, option.rect)
            if was_pressed and hook_rect.contains(pos):
                self._mark_view_action_click_handled(view)
                current = self._is_hook_selected_index(index)
                next_selected = not current
                return bool(self._handle_hook_activated(model, index, next_selected))
        return super().editorEvent(event, model, option, index)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        _ = option
        _ = index
        return QSize(0, self._row_height)


class RecordWorkspaceListWidget(QListView):
    selection_changed = pyqtSignal()
    selection_state_changed = pyqtSignal()
    page_changed = pyqtSignal(int, int, int, int)
    record_clicked = pyqtSignal(object)
    selection_button_clicked = pyqtSignal(object, bool)
    blank_area_clicked = pyqtSignal()

    def __init__(self, parent=None, *, empty_placeholder_text: str):
        super().__init__(parent)
        self.setObjectName("RecordWorkspaceListView")
        self.setSelectionMode(QListView.SelectionMode.NoSelection)
        self.setMouseTracking(True)
        self.setSpacing(6)
        self.setUniformItemSizes(True)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)

        self.records: list[RecordWorkspaceCardRecord] = []
        self.filtered_records: list[RecordWorkspaceCardRecord] = []
        self._duplicate_record_keys: set[str] = set()
        self.page_size: int = 20
        self.current_page: int = 1
        self._active_record_key: str = ""
        self._active_record_ref = None
        self._pre_click_active_record_key: str = ""
        self._pre_click_active_record_ref = None
        self._has_pre_click_active_snapshot: bool = False
        self._active_spin_allowed: bool = True
        self._active_border_animation_enabled: bool = False
        self._guide_select_animation_enabled: bool = False
        self._suppress_click_once = False
        self._external_selection_handler_enabled = False
        self._last_selection_signature: tuple[str, ...] = tuple()

        self._model = RecordWorkspaceListModel(parent=self, empty_placeholder_text=empty_placeholder_text)
        self._delegate = RecordWorkspaceListDelegate(self, on_select_button=self._on_select_button_clicked)
        self.setModel(self._model)
        self.setItemDelegate(self._delegate)
        self.clicked.connect(self._on_row_clicked)

        self._active_border_timer = QTimer(self)
        self._active_border_timer.setInterval(42)
        self._active_border_timer.timeout.connect(self._tick_active_border_animation)

    @staticmethod
    def _record_key_of(record) -> str:
        return str(getattr(record, "recordKey", getattr(record, "orderNumber", "")) or "").strip().upper()

    def set_records(self, records: list[RecordWorkspaceCardRecord]) -> None:
        if isinstance(records, list):
            self.records = records
        else:
            self.records = list(records or [])
        self.filtered_records = self.records
        seen_keys: set[str] = set()
        duplicate_keys: set[str] = set()
        for record in self.filtered_records:
            key = self._record_key_of(record)
            if key:
                if key in seen_keys:
                    duplicate_keys.add(key)
                else:
                    seen_keys.add(key)
        self._duplicate_record_keys = duplicate_keys
        self.current_page = 1
        self._build_page()

    def get_selected_records(self) -> list[RecordWorkspaceCardRecord]:
        return [record for record in (self.filtered_records or []) if bool(getattr(record, "_selected", False))]

    def total_record_count(self) -> int:
        return len(self.filtered_records or [])

    def shown_count(self) -> int:
        return self._model.visible_count()

    def get_total_pages(self) -> int:
        total = len(self.filtered_records or [])
        if total <= 0:
            return 1
        return (total + self.page_size - 1) // self.page_size

    def set_page_size(self, size: int) -> None:
        value = int(size or 0)
        if value <= 0:
            return
        self.page_size = value
        self.current_page = 1
        self._build_page()

    def go_to_page(self, page: int) -> None:
        total_pages = self.get_total_pages()
        self.current_page = max(1, min(int(page or 1), total_pages))
        self._build_page()

    def next_page(self) -> None:
        self.go_to_page(self.current_page + 1)

    def prev_page(self) -> None:
        self.go_to_page(self.current_page - 1)

    def set_record_selected(self, record, selected: bool) -> None:
        if record is None:
            return
        setattr(record, "_selected", bool(selected))
        row = self._find_row_for_record(record)
        if row < 0:
            row = self._find_row_by_key(self._record_key_of(record))
        if row >= 0:
            self._model.set_selected(row, bool(selected))
        self._emit_selection_signals_if_needed()

    def clear_selected_records(self) -> None:
        changed = False
        for record in self.filtered_records or []:
            if bool(getattr(record, "_selected", False)):
                setattr(record, "_selected", False)
                changed = True
        if changed:
            self._build_page()
        else:
            self._emit_selection_signals_if_needed(force=True)

    def select_all_filtered_records(self) -> None:
        changed = False
        for record in self.filtered_records or []:
            if not bool(getattr(record, "_selected", False)):
                setattr(record, "_selected", True)
                changed = True
        if changed:
            self._build_page()
        else:
            self._emit_selection_signals_if_needed(force=True)

    def set_active_record(self, record) -> None:
        if record is None:
            self.clear_active_record()
            return
        self._active_record_ref = record
        self._active_record_key = self._record_key_of(record)
        self._reapply_active_row()

    def clear_active_record(self) -> None:
        self._active_record_ref = None
        self._active_record_key = ""
        self._model.clear_active_row()
        self._set_active_border_animation_enabled(False)

    def set_active_spin_allowed(self, allowed: bool) -> None:
        self._active_spin_allowed = bool(allowed)
        self._delegate.set_active_visual_enabled(self._active_spin_allowed)
        active_row = self._find_row_by_key(self._active_record_key)
        self._set_active_border_animation_enabled(active_row >= 0 and self._active_spin_allowed)

    def set_select_button_guide_enabled(self, enabled: bool) -> None:
        self._guide_select_animation_enabled = bool(enabled)
        self._delegate.set_guide_select_enabled(self._guide_select_animation_enabled)
        self._sync_border_animation_timer()

    def set_external_selection_handler_enabled(self, enabled: bool) -> None:
        self._external_selection_handler_enabled = bool(enabled)

    def sync_dynamic_row_width(self) -> None:
        try:
            self.doItemsLayout()
            self.viewport().update()
        except Exception:
            return

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.sync_dynamic_row_width()

    def _find_row_for_record(self, record) -> int:
        if record is None:
            return -1
        row = self._model.row_for_record(record)
        if row >= 0:
            return row
        for row in range(self._model.rowCount()):
            if self._model.record_at(row) is record:
                return row
        return -1

    def _find_row_by_key(self, key: str) -> int:
        needle = str(key or "").strip().upper()
        if not needle:
            return -1
        row = self._model.row_for_key(needle)
        if row >= 0:
            return row
        for row in range(self._model.rowCount()):
            record = self._model.record_at(row)
            if self._record_key_of(record) == needle:
                return row
        return -1

    def is_active_record(self, record) -> bool:
        if record is None:
            return False
        if self._active_record_ref is not None:
            return self._active_record_ref is record
        active_key = str(self._active_record_key or "").strip().upper()
        return bool(active_key) and self._record_key_of(record) == active_key

    def take_pre_click_active_match(self, record):
        if not self._has_pre_click_active_snapshot:
            return None
        self._has_pre_click_active_snapshot = False
        previous_ref = self._pre_click_active_record_ref
        previous_key = str(self._pre_click_active_record_key or "").strip().upper()
        self._pre_click_active_record_ref = None
        self._pre_click_active_record_key = ""
        if record is None:
            return False
        if previous_ref is not None:
            return previous_ref is record
        return bool(previous_key) and self._record_key_of(record) == previous_key

    def _reapply_active_row(self) -> None:
        row = self._find_row_for_record(self._active_record_ref)
        if row < 0:
            row = self._find_row_by_key(self._active_record_key)
        self._model.set_active_row(row)
        self._set_active_border_animation_enabled(row >= 0 and self._active_spin_allowed)

    def _set_active_border_animation_enabled(self, enabled: bool) -> None:
        self._active_border_animation_enabled = bool(enabled)
        self._sync_border_animation_timer()

    def _selection_signature(self) -> tuple[str, ...]:
        selected_keys: list[str] = []
        for index, record in enumerate(self.filtered_records or []):
            if not bool(getattr(record, "_selected", False)):
                continue
            key = self._record_key_of(record)
            if not key or key in self._duplicate_record_keys:
                key = f"{key or 'row'}:{id(record)}:{index}"
            selected_keys.append(key)
        return tuple(sorted(selected_keys))

    def _emit_selection_signals_if_needed(self, *, force: bool = False) -> None:
        signature = self._selection_signature()
        if not force and signature == self._last_selection_signature:
            return
        self._last_selection_signature = signature
        self.selection_changed.emit()
        self.selection_state_changed.emit()

    def _sync_border_animation_timer(self) -> None:
        should_tick = self._active_border_animation_enabled or self._guide_select_animation_enabled
        if should_tick:
            if not self._active_border_timer.isActive():
                self._active_border_timer.start()
        elif self._active_border_timer.isActive():
            self._active_border_timer.stop()
        if not self._active_border_animation_enabled:
            self._delegate.reset_spin_phase()
        if not self._guide_select_animation_enabled:
            self._delegate.reset_guide_phase()
        self._update_animation_rows()

    def _tick_active_border_animation(self) -> None:
        if self._active_border_animation_enabled:
            self._delegate.advance_spin_phase(1.35)
        if self._guide_select_animation_enabled:
            self._delegate.advance_guide_phase(1.35)
        self._update_animation_rows()

    def _update_animation_rows(self) -> None:
        if self._guide_select_animation_enabled:
            self._update_visible_card_rows()
            return
        active_row = self._find_row_by_key(self._active_record_key)
        if active_row < 0:
            return
        index = self._model.index(active_row)
        rect = self.visualRect(index)
        if rect.isValid() and not rect.isNull():
            self.viewport().update(rect.adjusted(-2, -2, 2, 2))

    def _update_visible_card_rows(self) -> None:
        viewport = self.viewport()
        if viewport is None:
            return
        row_count = self._model.rowCount()
        if row_count <= 0:
            return

        visible_rect = viewport.rect()
        first_index = self.indexAt(visible_rect.topLeft())
        last_index = self.indexAt(visible_rect.bottomLeft())
        first_row = first_index.row() if first_index.isValid() else 0
        last_row = last_index.row() if last_index.isValid() else row_count - 1
        first_row = max(0, min(first_row, row_count - 1))
        last_row = max(first_row, min(last_row, row_count - 1))

        update_rect = QRect()
        for row in range(first_row, last_row + 1):
            rect = self.visualRect(self._model.index(row))
            if rect.isValid() and not rect.isNull():
                update_rect = rect if update_rect.isNull() else update_rect.united(rect)

        if update_rect.isValid() and not update_rect.isNull():
            viewport.update(update_rect.adjusted(-2, -2, 2, 2))

    def _build_page(self) -> None:
        total = len(self.filtered_records or [])
        if total <= 0:
            self._model.set_records([])
            self._set_active_border_animation_enabled(False)
            self._emit_selection_signals_if_needed()
            self.page_changed.emit(1, 1, 0, 0)
            return
        page_size = max(1, int(self.page_size or 20))
        total_pages = (total + page_size - 1) // page_size
        self.current_page = max(1, min(self.current_page, total_pages))
        start_idx = (self.current_page - 1) * page_size
        end_idx = min(start_idx + page_size, total)
        self._model.set_records(self.filtered_records[start_idx:end_idx])
        self._reapply_active_row()
        self._emit_selection_signals_if_needed()
        self.page_changed.emit(self.current_page, total_pages, total, end_idx - start_idx)

    def _on_row_clicked(self, index: QModelIndex) -> None:
        try:
            if self._suppress_click_once:
                self._suppress_click_once = False
                return
            if not index.isValid():
                return
            if bool(index.data(RecordWorkspaceListModel.PlaceholderRole)):
                return
            record = index.data(RecordWorkspaceListModel.RecordRole)
            if record is None:
                return
            self._pre_click_active_record_ref = self._active_record_ref
            self._pre_click_active_record_key = self._active_record_key
            self._has_pre_click_active_snapshot = True
            self.set_active_record(record)
            self.record_clicked.emit(record)
        except Exception:
            return

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            index = self.indexAt(event.pos())
            if not index.isValid():
                self.clear_active_record()
                self.blank_area_clicked.emit()
        super().mousePressEvent(event)

    def _on_select_button_clicked(self, index: QModelIndex, selected: bool) -> bool:
        try:
            self._suppress_click_once = True
            if not index.isValid():
                return False
            if bool(index.data(RecordWorkspaceListModel.PlaceholderRole)):
                return False
            record = index.data(RecordWorkspaceListModel.RecordRole)
            if record is None:
                return False
            if self._external_selection_handler_enabled:
                self.selection_button_clicked.emit(record, bool(selected))
            else:
                self.set_record_selected(record, bool(selected))
                self.selection_button_clicked.emit(record, bool(selected))
            return True
        except Exception:
            return False


class RecordWorkspaceSectionCard(QFrame):
    def __init__(self, parent=None, *, title: str = "", subtitle: str = "", object_name: str = "SectionCard") -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(14, 12, 14, 12)
        self._root.setSpacing(10)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(4)
        self.title_label = QLabel(str(title or ""), self, objectName="SectionTitle")
        self.title_label.setVisible(bool(str(title or "").strip()))
        self.subtitle_label = QLabel(str(subtitle or ""), self, objectName="Muted")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setVisible(bool(str(subtitle or "").strip()))
        text_col.addWidget(self.title_label)
        text_col.addWidget(self.subtitle_label)
        header.addLayout(text_col, 1)

        self.header_trailing = QLabel("", self, objectName="StatusInfo")
        self.header_trailing.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.header_trailing.setVisible(False)
        header.addWidget(self.header_trailing, 0, Qt.AlignmentFlag.AlignTop)

        self._root.addLayout(header)

        self.body_host = QWidget(self)
        self.body_layout = QVBoxLayout(self.body_host)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(8)
        self._root.addWidget(self.body_host, 1)

        self.footer_label = QLabel("", self, objectName="StatusInfo")
        self.footer_label.setWordWrap(True)
        self.footer_label.setVisible(False)
        self._root.addWidget(self.footer_label)

    def set_title(self, text: str) -> None:
        value = str(text or "")
        self.title_label.setText(value)
        self.title_label.setVisible(bool(value.strip()))

    def set_subtitle(self, text: str) -> None:
        value = str(text or "")
        self.subtitle_label.setText(value)
        self.subtitle_label.setVisible(bool(value.strip()))

    def set_header_trailing(self, text: str) -> None:
        value = str(text or "")
        self.header_trailing.setText(value)
        self.header_trailing.setVisible(bool(value.strip()))

    def set_footer_text(self, text: str) -> None:
        value = str(text or "")
        self.footer_label.setText(value)
        self.footer_label.setVisible(bool(value.strip()))

    def set_body_widget(self, widget: QWidget | None, *, stretch: int = 0) -> None:
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)
            child = item.widget()
            if child is not None:
                child.setParent(None)
        if widget is not None:
            self.body_layout.addWidget(widget, stretch)


class RecordWorkspaceEditorActionBar(QWidget):
    clearRequested = pyqtSignal()
    saveRequested = pyqtSignal()
    deleteRequested = pyqtSignal()

    def __init__(
        self,
        parent=None,
        *,
        clear_text: str = "Temizle",
        save_new_text: str = "Kaydet",
        save_edit_text: str = "Güncelle",
        delete_text: str = "Sil",
    ) -> None:
        super().__init__(parent)
        self._clear_text = str(clear_text or "Temizle")
        self._save_new_text = str(save_new_text or "Kaydet")
        self._save_edit_text = str(save_edit_text or "Güncelle")
        self._delete_text = str(delete_text or "Sil")
        self._mode = "new"
        self._delete_supported = True
        self._delete_available = True

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.clear_button = QPushButton(self._clear_text, self)
        self.clear_button.setObjectName("Ghost")
        self.save_button = QPushButton(self._save_new_text, self)
        self.save_button.setObjectName("Primary")
        self.delete_button = QPushButton(self._delete_text, self)
        self.delete_button.setObjectName("Danger")

        for button in (self.clear_button, self.save_button, self.delete_button):
            button.setMinimumHeight(44)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setAutoDefault(False)
            button.setDefault(False)

        self.clear_button.clicked.connect(self.clearRequested.emit)
        self.save_button.clicked.connect(self.saveRequested.emit)
        self.delete_button.clicked.connect(self.deleteRequested.emit)

        layout.addWidget(self.clear_button)
        layout.addStretch(1)
        layout.addWidget(self.delete_button)
        layout.addWidget(self.save_button)

        self.set_mode("new")

    def set_labels(
        self,
        *,
        clear_text: str | None = None,
        save_new_text: str | None = None,
        save_edit_text: str | None = None,
        delete_text: str | None = None,
    ) -> None:
        if clear_text is not None:
            self._clear_text = str(clear_text or "Temizle")
        if save_new_text is not None:
            self._save_new_text = str(save_new_text or "Kaydet")
        if save_edit_text is not None:
            self._save_edit_text = str(save_edit_text or "Güncelle")
        if delete_text is not None:
            self._delete_text = str(delete_text or "Sil")
        self.clear_button.setText(self._clear_text)
        self.delete_button.setText(self._delete_text)
        self.set_mode(self._mode)

    def set_mode(self, mode: str) -> None:
        mode_key = str(mode or "edit").strip().lower()
        if mode_key not in {"new", "edit", "bulk"}:
            mode_key = "edit"
        self._mode = mode_key
        is_new = mode_key == "new"
        self.delete_button.setVisible(self._delete_supported and self._delete_available and not is_new)
        self.save_button.setText(self._save_new_text if is_new else self._save_edit_text)

    def mode(self) -> str:
        return self._mode

    def set_delete_supported(self, supported: bool) -> None:
        self._delete_supported = bool(supported)
        self.set_mode(self._mode)

    def set_delete_available(self, available: bool) -> None:
        self._delete_available = bool(available)
        self.set_mode(self._mode)


class RecordWorkspaceFooterBar(QFrame):
    def __init__(
        self,
        parent=None,
        *,
        page_size_options: tuple[int, ...] = (20, 50, 100),
    ) -> None:
        super().__init__(parent)
        self.setObjectName("SectionCard")
        self._list_widget = None
        self._page_size_options = tuple(int(v) for v in page_size_options if int(v) > 0) or (20, 50, 100)

        root = QGridLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setHorizontalSpacing(12)
        root.setVerticalSpacing(0)
        root.setColumnStretch(0, 1)
        root.setColumnStretch(1, 0)
        root.setColumnStretch(2, 1)

        left_wrap = QWidget(self)
        left_layout = QHBoxLayout(left_wrap)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        self.select_toggle = SelectClearToggleButton(parent=self)
        left_layout.addWidget(self.select_toggle, 0, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        left_layout.addStretch(1)
        root.addWidget(left_wrap, 0, 0)

        center_wrap = QWidget(self)
        center_layout = QHBoxLayout(center_wrap)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(12)
        self.prev_button = QPushButton(RECORD_WORKSPACE_PREV_BUTTON_TEXT, self)
        self.prev_button.setObjectName("PageButton")
        center_layout.addWidget(self.prev_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.page_label = QLabel(
            RECORD_WORKSPACE_PAGE_LABEL_TEMPLATE.format(current=1, total=1, count=0),
            center_wrap,
            objectName="FieldLabel",
        )
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_layout.addWidget(self.page_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self.next_button = QPushButton(RECORD_WORKSPACE_NEXT_BUTTON_TEXT, self)
        self.next_button.setObjectName("PageButton")
        center_layout.addWidget(self.next_button, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(center_wrap, 0, 1, Qt.AlignmentFlag.AlignCenter)

        right_wrap = QWidget(self)
        right_layout = QHBoxLayout(right_wrap)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        self.page_size_label = QLabel(RECORD_WORKSPACE_PAGE_SIZE_LABEL, right_wrap, objectName="Muted")
        right_layout.addWidget(self.page_size_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self.page_size_combo = QComboBox(self)
        self.page_size_combo.setObjectName("Combo")
        self.page_size_combo.setMinimumWidth(74)
        for value in self._page_size_options:
            self.page_size_combo.addItem(str(value), value)
        right_layout.addWidget(self.page_size_combo, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(right_wrap, 0, 2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.select_toggle.actionRequested.connect(self._on_toggle_requested)
        self.prev_button.clicked.connect(self._go_prev_page)
        self.next_button.clicked.connect(self._go_next_page)
        self.page_size_combo.currentIndexChanged.connect(self._on_page_size_changed)

    def bind_list_widget(self, list_widget) -> None:
        previous = self._list_widget
        if previous is not None:
            try:
                previous.selection_changed.disconnect(self.refresh)
            except Exception:
                pass
            try:
                previous.page_changed.disconnect(self._on_page_changed)
            except Exception:
                pass
        self._list_widget = list_widget
        if list_widget is not None:
            try:
                list_widget.selection_changed.connect(self.refresh)
            except Exception:
                pass
            try:
                list_widget.page_changed.connect(self._on_page_changed)
            except Exception:
                pass
            try:
                page_size = int(getattr(list_widget, "page_size", 20) or 20)
            except Exception:
                page_size = 20
            combo_index = self.page_size_combo.findData(page_size)
            if combo_index >= 0:
                blocker = QSignalBlocker(self.page_size_combo)
                self.page_size_combo.setCurrentIndex(combo_index)
                del blocker
        self.refresh()

    def _selected_count(self) -> int:
        if self._list_widget is None:
            return 0
        try:
            return len(self._list_widget.get_selected_records())
        except Exception:
            return 0

    def _total_count(self) -> int:
        if self._list_widget is None:
            return 0
        try:
            return int(self._list_widget.total_record_count())
        except Exception:
            return 0

    def _go_prev_page(self) -> None:
        if self._list_widget is None:
            return
        try:
            self._list_widget.prev_page()
        except Exception:
            return

    def _go_next_page(self) -> None:
        if self._list_widget is None:
            return
        try:
            self._list_widget.next_page()
        except Exception:
            return

    def _on_toggle_requested(self, action: str) -> None:
        if self._list_widget is None:
            return
        try:
            if str(action or "").strip().lower() == "clear":
                self._list_widget.clear_selected_records()
            else:
                self._list_widget.select_all_filtered_records()
        except Exception:
            return

    def _on_page_size_changed(self, index: int) -> None:
        if self._list_widget is None or index < 0:
            return
        value = self.page_size_combo.itemData(index)
        try:
            self._list_widget.set_page_size(int(value or 20))
        except Exception:
            return

    def _on_page_changed(self, current_page: int, total_pages: int, total_records: int, shown_count: int) -> None:
        self.page_label.setText(
            RECORD_WORKSPACE_PAGE_LABEL_TEMPLATE.format(
                current=max(1, int(current_page)),
                total=max(1, int(total_pages)),
                count=max(0, int(total_records)),
            )
        )
        self.prev_button.setEnabled(int(current_page) > 1)
        self.next_button.setEnabled(int(current_page) < int(total_pages))
        self.select_toggle.setSelectionCounts(self._selected_count(), int(total_records))
        _ = shown_count

    def refresh(self) -> None:
        total = self._total_count()
        current_page = 1
        total_pages = 1
        if self._list_widget is not None:
            try:
                current_page = int(getattr(self._list_widget, "current_page", 1) or 1)
                total_pages = int(self._list_widget.get_total_pages())
            except Exception:
                current_page = 1
                total_pages = 1
        self._on_page_changed(current_page, total_pages, total, 0)


class RecordWorkspaceScaffold(QWidget):
    """Shared record-management window scaffold.

    Contract:
    - Provides window structure and shared behavior only: sidebar, splitter,
      editor slot, filters slot, records slot, footer bar, action slot, and
      guidance/lock wiring.
    - Domain widgets own their visuals. The scaffold must not inject broad
      descendant styles that override child widget backgrounds, gradients,
      shadows, focus visuals, or custom paint behavior.
    - Editor calmness may be achieved at viewport level only. Child widgets
      inside the editor slot must render as their domain/theme defines them.
    - Domains may disable the default action island via
      ``show_editor_actions_card=False``.
    """

    def __init__(
        self,
        parent=None,
        *,
        empty_placeholder_text: str = "Gosterilecek kayit bulunamadi.",
        sidebar_buttons: tuple[dict[str, object], ...] | None = None,
        page_size_options: tuple[int, ...] = (20, 50, 100),
        left_title: str = "Duzenle",
        left_subtitle: str = "",
        filters_title: str = "Filtreler",
        filters_subtitle: str = "",
        records_title: str = "Kayitlar",
        records_subtitle: str = "",
        shell_kwargs: dict[str, object] | None = None,
        style_sheet: str | None = None,
        show_editor_actions_card: bool = True,
        editor_canvas_color: str | None = None,
        editor_surface_color: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("RecordWorkspaceRoot")
        if style_sheet is not None:
            self.setStyleSheet(style_sheet)
        self._show_editor_actions_card = bool(show_editor_actions_card)
        self._editor_canvas_color = str(editor_canvas_color or "").strip()
        self._editor_surface_color = str(editor_surface_color or "").strip()
        self._editor_actions_widget: QWidget | None = None
        self._editor_actions_visible_modes: set[str] = {"new", "edit"}

        shell_options = dict(shell_kwargs or {})
        shell_options.setdefault("root_margins", (0, 0, 0, 0))
        shell_options.setdefault("root_spacing", 8)
        self.shell = RecordWorkspaceSplitShell(self, **shell_options)
        self.sidebar = self.shell.sidebar
        self._editor_layout_syncing = False
        self._list_loading_overlay: ListLoadingOverlay | None = None
        self._list_loading_watch_target = None
        self._list_loading_watch_viewport = None
        self._behavior_controllers: list["RecordWorkspaceBehaviorController"] = []
        self._editor_layout_refresh_timer = QTimer(self)
        self._editor_layout_refresh_timer.setSingleShot(True)
        self._editor_layout_refresh_timer.timeout.connect(self.refresh_editor_layout)
        self._list_loading_sync_timer = QTimer(self)
        self._list_loading_sync_timer.setSingleShot(True)
        self._list_loading_sync_timer.timeout.connect(self.sync_list_loading_geometry)

        self._install_sidebar_buttons(sidebar_buttons)

        splitter = self.shell.splitter

        self.left_card = RecordWorkspaceSectionCard(
            title=left_title,
            subtitle=left_subtitle,
            object_name="SectionCard",
        )
        self.left_card.setMinimumWidth(320)
        splitter.addWidget(self.left_card)

        left_body = QWidget(self.left_card)
        left_body.setAutoFillBackground(False)
        left_body_layout = QVBoxLayout(left_body)
        left_body_layout.setContentsMargins(0, 0, 0, 0)
        left_body_layout.setSpacing(10)

        self.editor_scroll = QScrollArea(left_body)
        self.editor_scroll.setWidgetResizable(True)
        self.editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.editor_scroll.setMinimumHeight(0)
        self.editor_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.editor_scroll.setAutoFillBackground(False)
        self.editor_scroll.viewport().setAutoFillBackground(False)
        self.editor_host = QWidget()
        self.editor_host.setObjectName("EditorCanvas")
        self.editor_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.editor_layout = QVBoxLayout(self.editor_host)
        # Keep a small inset so widgets with outer glow/shadow effects can
        # breathe inside scaffold-driven forms. Do not force editor_host itself
        # transparent; descendant widget painting must stay under domain control.
        self.editor_layout.setContentsMargins(8, 6, 8, 6)
        self.editor_layout.setSpacing(10)
        self.editor_surface = QFrame(self.editor_host)
        self.editor_surface.setObjectName("EditorSurface")
        self.editor_surface.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.editor_surface_layout = QVBoxLayout(self.editor_surface)
        self.editor_surface_layout.setContentsMargins(0, 0, 0, 0)
        self.editor_surface_layout.setSpacing(0)
        self.editor_layout.addWidget(self.editor_surface)
        self.set_editor_canvas_color(editor_canvas_color)
        self.set_editor_surface_color(editor_surface_color)
        self.editor_scroll.setWidget(self.editor_host)
        self.editor_scroll.viewport().installEventFilter(self)
        self.editor_host.installEventFilter(self)
        self.editor_surface.installEventFilter(self)
        left_body_layout.addWidget(self.editor_scroll, 1)

        self.editor_actions_host = QWidget(left_body)
        self.editor_actions_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.editor_actions_layout = QHBoxLayout(self.editor_actions_host)
        self.editor_actions_layout.setContentsMargins(0, 0, 0, 0)
        self.editor_actions_layout.setSpacing(8)
        self.editor_actions_card = QFrame(self.editor_actions_host)
        self.editor_actions_card.setObjectName("SoftCard")
        self.editor_actions_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.editor_actions_card_layout = QHBoxLayout(self.editor_actions_card)
        self.editor_actions_card_layout.setContentsMargins(8, 8, 8, 8)
        self.editor_actions_card_layout.setSpacing(8)
        self.editor_actions_layout.addWidget(self.editor_actions_card, 1)
        self.editor_action_bar = RecordWorkspaceEditorActionBar(self.editor_actions_card)
        self.editor_actions_card_layout.addWidget(self.editor_action_bar, 1)
        self._editor_actions_widget = self.editor_action_bar
        if not self._show_editor_actions_card:
            self.editor_actions_card.hide()
            self.editor_actions_host.hide()
        left_body_layout.addWidget(self.editor_actions_host)

        self.bulk_panel = QFrame(left_body)
        self.bulk_panel.setObjectName("QuickCard")
        self.bulk_layout = QVBoxLayout(self.bulk_panel)
        self.bulk_layout.setContentsMargins(12, 10, 12, 10)
        self.bulk_layout.setSpacing(8)
        self.bulk_panel.hide()
        left_body_layout.addWidget(self.bulk_panel, 1)

        self.left_card.set_body_widget(left_body, stretch=1)

        self.right_card = QFrame(self)
        self.right_card.setObjectName("SectionCard")
        self.right_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        right_layout = QVBoxLayout(self.right_card)
        right_layout.setContentsMargins(14, 12, 14, 12)
        right_layout.setSpacing(10)

        self.filters_card = RecordWorkspaceSectionCard(
            self.right_card,
            title=filters_title,
            subtitle=filters_subtitle,
            object_name="SectionCard",
        )
        self.filters_host = QWidget(self.filters_card)
        self.filters_layout = QVBoxLayout(self.filters_host)
        self.filters_layout.setContentsMargins(0, 0, 0, 0)
        self.filters_layout.setSpacing(8)
        self.filters_card.set_body_widget(self.filters_host, stretch=1)
        right_layout.addWidget(self.filters_card)

        self.records_card = RecordWorkspaceSectionCard(
            self.right_card,
            title=records_title,
            subtitle=records_subtitle,
            object_name="SectionCard",
        )
        self.list_widget = RecordWorkspaceListWidget(
            self.records_card,
            empty_placeholder_text=empty_placeholder_text,
        )
        self.records_card.set_body_widget(self.list_widget, stretch=1)
        right_layout.addWidget(self.records_card, 1)

        self.footer_bar = RecordWorkspaceFooterBar(self.right_card, page_size_options=page_size_options)
        self.footer_bar.bind_list_widget(self.list_widget)
        right_layout.addWidget(self.footer_bar)
        self.records_card.body_host.installEventFilter(self)

        splitter.addWidget(self.right_card)
        splitter.setCollapsible(0, True)
        splitter.setCollapsible(1, False)

        self.shell.set_left_guidance_targets(
            editor_widget=self.editor_scroll,
            actions_widget=self.editor_actions_card if self._show_editor_actions_card else None,
            bulk_widget=self.bulk_panel,
            host=self.left_card,
        )
        self.shell.set_right_guidance_widget(self.list_widget, host=self.right_card)
        self._bind_list_loading_target(self.list_widget)
        self.schedule_editor_layout_refresh()
        self.schedule_list_loading_geometry_sync()

    def _install_sidebar_buttons(self, sidebar_buttons: tuple[dict[str, object], ...] | None) -> None:
        button_specs = list(sidebar_buttons or [])
        if not button_specs:
            button_specs = [
                {"panel_id": "new", "text": "+", "tooltip": "Yeni kayit paneli"},
                {"panel_id": "edit", "text": "E", "tooltip": "Duzenleme paneli"},
                {"panel_id": "bulk", "text": "S", "tooltip": "Toplu secim paneli"},
            ]
        for spec in button_specs:
            panel_id = str(spec.get("panel_id") or "").strip()
            if not panel_id:
                continue
            params = dict(spec)
            params.pop("panel_id", None)
            params.setdefault("text", "")
            self.sidebar.add_panel_button(panel_id, params.pop("text"), **params)

    @staticmethod
    def _replace_layout_contents(layout, widget: QWidget | None) -> None:
        while layout.count():
            item = layout.takeAt(0)
            child = item.widget()
            if child is not None:
                child.setParent(None)
        if widget is not None:
            layout.addWidget(widget)

    @staticmethod
    def _set_slot_widget_size_policy(widget: QWidget | None) -> None:
        if widget is None:
            return
        try:
            policy = widget.sizePolicy()
            policy.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
            widget.setSizePolicy(policy)
            widget.setMinimumWidth(0)
        except Exception:
            return

    def schedule_editor_layout_refresh(self) -> None:
        if not self._editor_layout_refresh_timer.isActive():
            self._editor_layout_refresh_timer.start(0)

    def schedule_list_loading_geometry_sync(self) -> None:
        if not self._list_loading_sync_timer.isActive():
            self._list_loading_sync_timer.start(0)

    def eventFilter(self, watched, event):
        if self._editor_layout_syncing:
            return super().eventFilter(watched, event)
        if watched in {self.editor_scroll.viewport(), self.editor_host, self.editor_surface}:
            if event.type() in {
                QEvent.Type.Resize,
                QEvent.Type.Show,
                QEvent.Type.LayoutRequest,
            }:
                self.schedule_editor_layout_refresh()
        records_card = getattr(self, "records_card", None)
        records_body_host = getattr(records_card, "body_host", None)
        if watched in {
            records_body_host,
            self._list_loading_watch_target,
            self._list_loading_watch_viewport,
        }:
            if event.type() in {
                QEvent.Type.Resize,
                QEvent.Type.Show,
                QEvent.Type.Move,
                QEvent.Type.LayoutRequest,
            }:
                self.schedule_list_loading_geometry_sync()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.sync_list_loading_geometry()

    def refresh_editor_layout(self) -> None:
        if self._editor_layout_syncing:
            return
        viewport = self.editor_scroll.viewport()
        target_width = max(0, int(viewport.width() or 0))
        if target_width <= 0:
            return
        self._editor_layout_syncing = True
        try:
            size_changed = False
            if (
                self.editor_host.width() != target_width
                or self.editor_host.minimumWidth() != target_width
                or self.editor_host.maximumWidth() != target_width
            ):
                self.editor_host.setFixedWidth(target_width)
                size_changed = True
            self.editor_host.adjustSize()
            if size_changed:
                try:
                    self.shell.sync_guidance_geometry()
                except Exception:
                    pass
        finally:
            self._editor_layout_syncing = False

    def set_left_title(self, text: str) -> None:
        self.left_card.set_title(text)

    def set_left_subtitle(self, text: str) -> None:
        self.left_card.set_subtitle(text)

    def set_filters_title(self, text: str) -> None:
        self.filters_card.set_title(text)

    def set_filters_subtitle(self, text: str) -> None:
        self.filters_card.set_subtitle(text)

    def set_records_title(self, text: str) -> None:
        self.records_card.set_title(text)

    def set_records_subtitle(self, text: str) -> None:
        self.records_card.set_subtitle(text)

    def set_filters_footer_text(self, text: str) -> None:
        self.filters_card.set_footer_text(text)

    def set_records_summary_text(self, text: str) -> None:
        self.records_card.set_header_trailing(text)

    def _bind_list_loading_target(self, widget) -> None:
        for watched in (self._list_loading_watch_target, self._list_loading_watch_viewport):
            if watched is not None:
                try:
                    watched.removeEventFilter(self)
                except Exception:
                    pass
        self._list_loading_watch_target = None
        self._list_loading_watch_viewport = None

        if widget is None:
            if self._list_loading_overlay is not None:
                self._list_loading_overlay.set_target(None)
            return

        self._list_loading_watch_target = widget
        try:
            widget.installEventFilter(self)
        except Exception:
            pass
        viewport = None
        try:
            viewport = widget.viewport() if hasattr(widget, "viewport") else None
        except Exception:
            viewport = None
        if viewport is not None:
            self._list_loading_watch_viewport = viewport
            try:
                viewport.installEventFilter(self)
            except Exception:
                pass
        if self._list_loading_overlay is not None:
            self._list_loading_overlay.set_target(widget)
        self.schedule_list_loading_geometry_sync()

    def _ensure_list_loading_overlay(self) -> None:
        records_card = getattr(self, "records_card", None)
        list_widget = getattr(self, "list_widget", None)
        if records_card is None or list_widget is None:
            return
        if self._list_loading_overlay is None:
            self._list_loading_overlay = ListLoadingOverlay(
                self.records_card.body_host,
                target=self.list_widget,
                message="Yukleniyor...",
                hide_target_content_while_busy=True,
            )
        else:
            self._list_loading_overlay.set_target(self.list_widget)
        self._list_loading_overlay.sync_geometry()

    def sync_list_loading_geometry(self) -> None:
        self._ensure_list_loading_overlay()
        if self._list_loading_overlay is not None:
            self._list_loading_overlay.sync_geometry()

    def set_list_loading(self, busy: bool, message: str | None = None) -> None:
        self._ensure_list_loading_overlay()
        if self._list_loading_overlay is None:
            return
        self._list_loading_overlay.set_busy(bool(busy), message=message)
        self._list_loading_overlay.sync_geometry()

    def is_list_loading(self) -> bool:
        if self._list_loading_overlay is None:
            return False
        return self._list_loading_overlay.is_busy()

    def set_filters_widget(self, widget: QWidget | None) -> None:
        self._set_slot_widget_size_policy(widget)
        self._replace_layout_contents(self.filters_layout, widget)

    def set_editor_widget(self, widget: QWidget | None) -> None:
        self._set_slot_widget_size_policy(widget)
        self._replace_layout_contents(self.editor_surface_layout, widget)
        self.schedule_editor_layout_refresh()

    def set_editor_canvas_color(self, color: str | None) -> None:
        self._editor_canvas_color = str(color or "").strip()
        viewport_bg = self._editor_canvas_color or "transparent"
        self.editor_scroll.setStyleSheet(
            f"""
            QScrollArea {{
                background: transparent;
                border: 0px;
            }}
            QScrollArea::viewport {{
                background: {viewport_bg};
            }}
            """
        )
        if self._editor_canvas_color:
            self.editor_host.setStyleSheet(
                f"""
                QWidget#EditorCanvas {{
                    background-color: {self._editor_canvas_color};
                    border: 0px;
                    border-radius: 10px;
                }}
                """
            )
        else:
            self.editor_host.setStyleSheet(
                """
                QWidget#EditorCanvas {
                    background: transparent;
                    border: 0px;
                }
                """
            )

    def set_editor_surface_color(self, color: str | None) -> None:
        self._editor_surface_color = str(color or "").strip()
        if self._editor_surface_color:
            self.editor_surface.setStyleSheet(
                f"""
                QFrame#EditorSurface {{
                    background-color: {self._editor_surface_color};
                    border: 0px;
                    border-radius: 10px;
                }}
                """
            )
        else:
            self.editor_surface.setStyleSheet(
                """
                QFrame#EditorSurface {
                    background: transparent;
                    border: 0px;
                }
                """
            )

    def set_editor_actions_widget(self, widget: QWidget | None) -> None:
        self._set_slot_widget_size_policy(widget)
        self._editor_actions_widget = widget
        while self.editor_actions_card_layout.count():
            item = self.editor_actions_card_layout.takeAt(0)
            child = item.widget()
            if child is not None:
                child.setParent(None)
        if not self._show_editor_actions_card:
            self.editor_actions_host.hide()
            self.editor_actions_card.hide()
            self.editor_actions_host.setMinimumHeight(0)
            self.editor_actions_host.setMaximumHeight(16777215)
            return
        if widget is not None:
            self.editor_actions_card_layout.addWidget(widget, 1)
        if widget is None:
            self.editor_actions_host.hide()
            self.editor_actions_card.hide()
            self.editor_actions_host.setMinimumHeight(0)
            self.editor_actions_host.setMaximumHeight(16777215)
            return

        self._sync_editor_actions_visibility()
        self.editor_actions_host.setMinimumHeight(0)
        self.editor_actions_host.setMaximumHeight(16777215)
        try:
            widget.adjustSize()
        except Exception:
            pass
        self.editor_actions_card.adjustSize()
        self.editor_actions_card.updateGeometry()
        self.editor_actions_host.adjustSize()
        self.editor_actions_host.updateGeometry()
        self.schedule_editor_layout_refresh()

    def use_default_editor_action_bar(self) -> None:
        self.set_editor_actions_widget(self.editor_action_bar)

    def set_editor_actions_visible_modes(self, modes: set[str] | tuple[str, ...] | list[str]) -> None:
        normalized = {
            str(mode or "").strip().lower()
            for mode in (modes or [])
            if str(mode or "").strip().lower() in {"new", "edit", "bulk"}
        }
        self._editor_actions_visible_modes = normalized
        self._sync_editor_actions_visibility()

    def _sync_editor_actions_visibility(self) -> None:
        if not self._show_editor_actions_card or self._editor_actions_widget is None:
            self.editor_actions_host.hide()
            self.editor_actions_card.hide()
            return
        mode_key = str(self.editor_action_bar.mode() or "edit").strip().lower()
        visible = mode_key in self._editor_actions_visible_modes
        self.editor_actions_host.setVisible(visible)
        self.editor_actions_card.setVisible(visible)

    def set_editor_action_labels(
        self,
        *,
        clear_text: str | None = None,
        save_new_text: str | None = None,
        save_edit_text: str | None = None,
        delete_text: str | None = None,
    ) -> None:
        self.editor_action_bar.set_labels(
            clear_text=clear_text,
            save_new_text=save_new_text,
            save_edit_text=save_edit_text,
            delete_text=delete_text,
        )

    def set_editor_action_mode(self, mode: str) -> None:
        self.editor_action_bar.set_mode(mode)
        self._sync_editor_actions_visibility()

    def set_editor_action_delete_supported(self, supported: bool) -> None:
        self.editor_action_bar.set_delete_supported(supported)

    def set_editor_action_delete_available(self, available: bool) -> None:
        self.editor_action_bar.set_delete_available(available)

    def set_bulk_widget(self, widget: QWidget | None) -> None:
        self._set_slot_widget_size_policy(widget)
        self._replace_layout_contents(self.bulk_layout, widget)

    def set_list_widget(self, widget) -> None:
        if widget is None:
            return
        if widget is self.list_widget:
            return
        old_widget = self.list_widget
        body_layout = self.records_card.body_layout
        if old_widget is not None:
            body_layout.removeWidget(old_widget)
            old_widget.hide()
        if widget.parentWidget() is not self.records_card.body_host:
            widget.setParent(self.records_card.body_host)
        self.list_widget = widget
        body_layout.addWidget(self.list_widget, 1)
        self.footer_bar.bind_list_widget(self.list_widget)
        self.shell.set_right_guidance_widget(self.list_widget, host=self.right_card)
        self._bind_list_loading_target(self.list_widget)
        for controller in list(self._behavior_controllers):
            try:
                controller.bind_list_widget(self.list_widget)
                controller.sync_state()
            except Exception:
                pass
        if old_widget is not None:
            old_widget.deleteLater()

    def create_behavior_controller(self, **kwargs) -> "RecordWorkspaceBehaviorController":
        controller = RecordWorkspaceBehaviorController(
            shell=self.shell,
            **kwargs,
        )
        self._behavior_controllers.append(controller)
        return controller

class AnimatedGuidanceRing(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._dash_offset = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(70)
        self._timer.timeout.connect(self._tick)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()

    def _tick(self):
        self._dash_offset -= 1.4
        if self._dash_offset < -512:
            self._dash_offset = 0.0
        self.update()

    def start(self):
        if not self._timer.isActive():
            self._timer.start()
        self.show()
        self.raise_()
        self.update()

    def stop(self):
        self._timer.stop()
        self.hide()

    def paintEvent(self, event):
        _ = event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(2, 2, -2, -2)
        if rect.width() <= 0 or rect.height() <= 0:
            return

        glow_pen = QPen(QColor(59, 130, 246, 68), 5)
        glow_pen.setStyle(Qt.PenStyle.SolidLine)
        painter.setPen(glow_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 13, 13)

        dash_pen = QPen(QColor("#3B82F6"), 2)
        dash_pen.setStyle(Qt.PenStyle.CustomDashLine)
        dash_pen.setDashPattern([8, 6])
        dash_pen.setDashOffset(self._dash_offset)
        painter.setPen(dash_pen)
        painter.drawRoundedRect(rect, 13, 13)


class EditLockOverlay(QWidget):
    def __init__(self, parent=None, *, message: str = ""):
        super().__init__(parent)
        self._message = str(message or "")
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()

    def set_message(self, message: str) -> None:
        self._message = str(message or "")
        self.update()

    def paintEvent(self, event):
        _ = event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = self.rect().adjusted(2, 2, -2, -2)
        if rect.width() <= 0 or rect.height() <= 0:
            return

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(248, 250, 252, 222))
        painter.drawRoundedRect(rect, 12, 12)

        border_pen = QPen(QColor("#60A5FA"), 2)
        border_pen.setStyle(Qt.PenStyle.DashLine)
        border_pen.setDashPattern([7, 5])
        painter.setPen(border_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 12, 12)

        if self._message:
            painter.setPen(QColor("#1D4ED8"))
            painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            painter.drawText(
                rect.adjusted(14, 14, -14, -14),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                self._message,
            )


class RecordWorkspaceSplitShell(QObject):
    def __init__(
        self,
        host: QWidget,
        *,
        sidebar_width: int = 92,
        left_stick_size: int = 560,
        left_collapse_trigger: int = 440,
        min_left_width: int = 360,
        min_right_width: int = 320,
        fallback_total_width: int = 1480,
        root_margins: tuple[int, int, int, int] = (14, 14, 14, 14),
        root_spacing: int = 8,
        snap_on_drag: bool = False,
    ) -> None:
        super().__init__(host)
        self.host = host
        self._left_stick_size = max(0, int(left_stick_size))
        self._left_collapse_trigger = max(0, int(left_collapse_trigger))
        self._min_left_width = max(0, int(min_left_width))
        self._min_right_width = max(0, int(min_right_width))
        self._fallback_total_width = max(1, int(fallback_total_width))
        self._snap_on_drag = bool(snap_on_drag)
        self._splitter_guard = False
        self._state_changed_callback = None
        self._active_panel: str | None = None
        self._left_guidance_host: QWidget | None = None
        self._left_editor_target: QWidget | None = None
        self._left_actions_target: QWidget | None = None
        self._left_bulk_target: QWidget | None = None
        self._left_highlight_overlay: EditLockOverlay | None = None
        self._left_message_provider = None
        self._right_guidance_target: QWidget | None = None
        self._right_guidance_host: QWidget | None = None
        self._right_guidance_ring: AnimatedGuidanceRing | None = None
        self._left_highlight_enabled = False
        self._right_guidance_enabled = False

        self.root_layout = QHBoxLayout(host)
        self.root_layout.setContentsMargins(*root_margins)
        self.root_layout.setSpacing(int(root_spacing))

        self.sidebar = SplitPanelSidebar(host, sidebar_width=int(sidebar_width))
        self.root_layout.addWidget(self.sidebar)

        self.splitter = ResettableSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(True)
        self.splitter.setHandleWidth(6)
        self.splitter.splitterMoved.connect(self._on_splitter_moved)
        self.root_layout.addWidget(self.splitter, 1)
        self.host.installEventFilter(self)
        self.splitter.installEventFilter(self)

    def set_state_changed_callback(self, callback) -> None:
        self._state_changed_callback = callback

    def set_left_highlight_widget(self, widget: QWidget | None) -> None:
        self.set_left_guidance_targets(host=widget)

    def set_left_guidance_targets(
        self,
        *,
        editor_widget: QWidget | None = None,
        actions_widget: QWidget | None = None,
        bulk_widget: QWidget | None = None,
        host: QWidget | None = None,
    ) -> None:
        previous = {
            self._left_guidance_host,
            self._left_editor_target,
            self._left_actions_target,
            self._left_bulk_target,
        }
        for watched in previous:
            if watched is not None:
                watched.removeEventFilter(self)

        self._left_guidance_host = host
        self._left_editor_target = editor_widget
        self._left_actions_target = actions_widget
        self._left_bulk_target = bulk_widget

        current = {
            self._left_guidance_host,
            self._left_editor_target,
            self._left_actions_target,
            self._left_bulk_target,
        }
        for watched in current:
            if watched is not None:
                watched.installEventFilter(self)

        if self._left_highlight_overlay is not None and self._left_guidance_host is not None:
            self._left_highlight_overlay.setParent(self._left_guidance_host)
        elif self._left_highlight_overlay is None and self._left_guidance_host is not None:
            self._left_highlight_overlay = EditLockOverlay(self._left_guidance_host)

        self.sync_guidance_geometry()
        self.set_left_highlight_enabled(self._left_highlight_enabled)

    def set_left_guidance_message_provider(self, provider) -> None:
        self._left_message_provider = provider
        self.sync_guidance_geometry()

    def set_left_highlight_enabled(self, enabled: bool) -> None:
        self._left_highlight_enabled = bool(enabled)
        overlay = self._left_highlight_overlay
        if overlay is None:
            return
        if not self._left_highlight_enabled:
            overlay.hide()
            return
        self.sync_guidance_geometry()
        overlay.show()
        overlay.raise_()

    def set_right_guidance_widget(self, widget: QWidget | None, *, host: QWidget | None = None) -> None:
        prev_target = self._right_guidance_target
        prev_host = self._right_guidance_host
        if prev_target is not None:
            prev_target.removeEventFilter(self)
        if prev_host is not None and prev_host is not prev_target and prev_host is not self.host:
            prev_host.removeEventFilter(self)

        self._right_guidance_target = widget
        resolved_host = host or (widget.parentWidget() if widget is not None else None)
        self._right_guidance_host = resolved_host

        if widget is not None:
            widget.installEventFilter(self)
        if resolved_host is not None and resolved_host is not widget:
            resolved_host.installEventFilter(self)

        if self._right_guidance_ring is not None and self._right_guidance_host is not None:
            self._right_guidance_ring.setParent(self._right_guidance_host)
        elif self._right_guidance_ring is None and self._right_guidance_host is not None:
            self._right_guidance_ring = AnimatedGuidanceRing(self._right_guidance_host)

        self.sync_guidance_geometry()
        self.set_right_guidance_enabled(self._right_guidance_enabled)

    def set_right_guidance_enabled(self, enabled: bool) -> None:
        self._right_guidance_enabled = bool(enabled)
        ring = self._right_guidance_ring
        if ring is None:
            return
        if not self._right_guidance_enabled or self._right_guidance_target is None or self._right_guidance_host is None:
            ring.stop()
            return
        self.sync_guidance_geometry()
        ring.start()

    @staticmethod
    def _mapped_rect(widget: QWidget | None, host: QWidget | None) -> QRect:
        if widget is None or host is None:
            return QRect()
        if not widget.isVisible() or not host.isVisible():
            return QRect()
        try:
            top_left = widget.mapTo(host, QPoint(0, 0))
        except Exception:
            return QRect()
        return QRect(top_left, widget.size())

    def sync_guidance_geometry(self) -> None:
        overlay = self._left_highlight_overlay
        left_host = self._left_guidance_host
        if overlay is not None and left_host is not None:
            if overlay.parentWidget() is not left_host:
                overlay.setParent(left_host)
            if not self._left_highlight_enabled or not left_host.isVisible():
                overlay.hide()
            else:
                if self._active_panel == "bulk" and self._left_bulk_target is not None and self._left_bulk_target.isVisible():
                    left_rect = self._mapped_rect(self._left_bulk_target, left_host)
                else:
                    editor_rect = self._mapped_rect(self._left_editor_target, left_host)
                    actions_rect = self._mapped_rect(self._left_actions_target, left_host)
                    if editor_rect.isNull():
                        left_rect = actions_rect
                    elif actions_rect.isNull():
                        left_rect = editor_rect
                    else:
                        left_rect = editor_rect.united(actions_rect)
                left_rect = left_rect.adjusted(-2, -2, 2, 2).intersected(left_host.rect())
                message = ""
                if callable(self._left_message_provider):
                    try:
                        message = str(self._left_message_provider() or "")
                    except Exception:
                        message = ""
                overlay.set_message(message)
                if left_rect.isNull():
                    overlay.hide()
                else:
                    overlay.setGeometry(left_rect)
                    overlay.raise_()
                    overlay.show()

        ring = self._right_guidance_ring
        target = self._right_guidance_target
        host = self._right_guidance_host
        if ring is None or target is None or host is None:
            return
        if ring.parentWidget() is not host:
            ring.setParent(host)
        target_rect = self._mapped_rect(target, host)
        if target_rect.isNull():
            ring.hide()
            return
        ring_rect = target_rect.adjusted(-4, -4, 4, 4).intersected(host.rect())
        ring.setGeometry(ring_rect)
        ring.raise_()
        if self._right_guidance_enabled:
            ring.show()
        else:
            ring.hide()

    def eventFilter(self, watched, event):
        watched_targets = {
            getattr(self, "host", None),
            getattr(self, "splitter", None),
            getattr(self, "_left_guidance_host", None),
            getattr(self, "_left_editor_target", None),
            getattr(self, "_left_actions_target", None),
            getattr(self, "_left_bulk_target", None),
            getattr(self, "_right_guidance_target", None),
            getattr(self, "_right_guidance_host", None),
        }
        watched_targets.discard(None)
        if watched in watched_targets:
            if event.type() in {
                QEvent.Type.Resize,
                QEvent.Type.Move,
                QEvent.Type.Show,
                QEvent.Type.LayoutRequest,
            }:
                QTimer.singleShot(0, self.sync_guidance_geometry)
            elif event.type() == QEvent.Type.Hide and self._right_guidance_ring is not None:
                self._right_guidance_ring.hide()
        return super().eventFilter(watched, event)

    def splitter_total_size(self) -> int:
        sizes = self.splitter.sizes()
        total = int(sum(sizes)) if sizes else 0
        if total > 0:
            return total
        width = int(self.splitter.width() or 0)
        return width if width > 0 else self._fallback_total_width

    def is_left_panel_open(self) -> bool:
        sizes = self.splitter.sizes()
        return len(sizes) >= 2 and int(sizes[0]) > 8

    def open_left_panel(
        self,
        *,
        left_width: int | None = None,
        min_left: int | None = None,
        min_right: int | None = None,
    ) -> None:
        if self.is_left_panel_open():
            self._notify_state_changed()
            return
        total = self.splitter_total_size()
        target_left = self._left_stick_size if left_width is None else int(left_width)
        min_left_width = self._min_left_width if min_left is None else max(0, int(min_left))
        min_right_width = self._min_right_width if min_right is None else max(0, int(min_right))
        left = max(min_left_width, min(target_left, total - min_right_width))
        self._snap(left, total)

    def close_left_panel(self) -> None:
        if not self.is_left_panel_open():
            self._notify_state_changed()
            return
        self._snap(0, self.splitter_total_size())

    def sync_sidebar_active(self, active_panel: str | None) -> None:
        self._active_panel = active_panel if self.is_left_panel_open() else None
        self.sidebar.set_active_panel(active_panel if self.is_left_panel_open() else None)
        self.sync_guidance_geometry()

    def _snap(self, left: int, total: int) -> None:
        self._splitter_guard = True
        clamped_left = max(0, int(left))
        self.splitter.setSizes([clamped_left, max(0, int(total) - clamped_left)])
        QTimer.singleShot(0, self._release_splitter_guard)

    def _release_splitter_guard(self) -> None:
        self._splitter_guard = False
        self._notify_state_changed()

    def _notify_state_changed(self) -> None:
        self.sync_guidance_geometry()
        if self._state_changed_callback is not None:
            try:
                self._state_changed_callback()
            except Exception:
                return

    def _on_splitter_moved(self, pos: int, _index: int) -> None:
        if self._splitter_guard:
            return
        if not self._snap_on_drag:
            self._notify_state_changed()
            return
        try:
            sizes = self.splitter.sizes()
            if len(sizes) < 2:
                return
            left, right = int(sizes[0]), int(sizes[1])
            total = left + right
            if total <= 0:
                return
            if left >= self._left_stick_size:
                self._notify_state_changed()
                return
            if pos <= self._left_collapse_trigger:
                self._snap(0, total)
                return
            self._snap(self._left_stick_size, total)
        except Exception:
            self._splitter_guard = False
            self._notify_state_changed()


class RecordWorkspaceBehaviorAdapter(ABC):
    new_panel_id: str | None = "new"
    edit_panel_id: str | None = "edit"
    bulk_panel_id: str | None = "bulk"
    clear_active_on_close: bool = True
    list_record_clicked_signal_names: tuple[str, ...] = (
        "record_clicked",
        "card_clicked",
        "item_clicked",
        "order_clicked",
        "tx_clicked",
    )
    list_selection_button_signal_names: tuple[str, ...] = ("selection_button_clicked",)
    list_blank_area_signal_names: tuple[str, ...] = ("blank_area_clicked", "background_clicked")
    list_selection_state_signal_names: tuple[str, ...] = (
        "selection_state_changed",
        "selection_changed",
        "bulk_selection_changed",
    )
    list_external_selection_handler_method_names: tuple[str, ...] = ("set_external_selection_handler_enabled",)

    @property
    @abstractmethod
    def list_widget(self):
        raise NotImplementedError

    @abstractmethod
    def get_mode(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def set_mode(self, mode: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_active_key(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_selected_count(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def get_record_key(self, record) -> str:
        raise NotImplementedError

    @abstractmethod
    def prepare_new(self) -> None:
        raise NotImplementedError

    def edit_without_active(self) -> None:
        return

    @abstractmethod
    def activate_record(self, record) -> None:
        raise NotImplementedError

    @abstractmethod
    def clear_active(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def apply_selection(self, record, selected: bool) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_select_button_guide_enabled(self, enabled: bool) -> None:
        raise NotImplementedError

    @abstractmethod
    def on_state_changed(self) -> None:
        raise NotImplementedError

    def open_panel(self, shell: "RecordWorkspaceSplitShell") -> None:
        shell.open_left_panel()

    def close_panel(self, shell: "RecordWorkspaceSplitShell") -> None:
        shell.close_left_panel()

    @abstractmethod
    def edit_guidance_message(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def bulk_guidance_message(self) -> str:
        raise NotImplementedError


class RecordWorkspaceBehaviorController(QObject):
    def __init__(
        self,
        *,
        shell: RecordWorkspaceSplitShell,
        adapter: RecordWorkspaceBehaviorAdapter,
        auto_wire_sidebar: bool = True,
        auto_wire_list_signals: bool = True,
    ) -> None:
        super().__init__(shell.host)
        self.shell = shell
        self.adapter = adapter
        self.list_widget = None
        self._selection_signal = None
        self._auto_wire_list_signals = bool(auto_wire_list_signals)
        self._new_panel_id = str(getattr(adapter, "new_panel_id", "new") or "").strip() or None
        self._edit_panel_id = str(getattr(adapter, "edit_panel_id", "edit") or "").strip() or None
        self._bulk_panel_id = str(getattr(adapter, "bulk_panel_id", "bulk") or "").strip() or None
        self._clear_active_on_close = bool(getattr(adapter, "clear_active_on_close", True))

        self.shell.set_state_changed_callback(self.sync_state)
        self.shell.set_left_guidance_message_provider(self.left_guidance_message)
        if auto_wire_sidebar:
            try:
                self.shell.sidebar.panel_toggled.connect(self.handle_panel_sidebar_toggled)
            except Exception:
                pass
        self.bind_list_widget(adapter.list_widget)
        QTimer.singleShot(0, self.sync_state)

    @staticmethod
    def _normalized_name_candidates(value, defaults: tuple[str, ...]) -> tuple[str, ...]:
        if value is None:
            return defaults
        if isinstance(value, str):
            token = value.strip()
            return (token,) if token else defaults
        names: list[str] = []
        for item in value:
            token = str(item or "").strip()
            if token:
                names.append(token)
        return tuple(names) or defaults

    def _adapter_name_candidates(self, attr_name: str, defaults: tuple[str, ...]) -> tuple[str, ...]:
        return self._normalized_name_candidates(getattr(self.adapter, attr_name, None), defaults)

    def _resolve_signal(self, list_widget, attr_name: str, defaults: tuple[str, ...]):
        if list_widget is None:
            return None
        for name in self._adapter_name_candidates(attr_name, defaults):
            signal = getattr(list_widget, name, None)
            if signal is not None:
                return signal
        return None

    def _resolve_callable(self, list_widget, attr_name: str, defaults: tuple[str, ...]):
        if list_widget is None:
            return None
        for name in self._adapter_name_candidates(attr_name, defaults):
            callback = getattr(list_widget, name, None)
            if callable(callback):
                return callback
        return None

    def _record_clicked_signal_for(self, list_widget):
        return self._resolve_signal(list_widget, "list_record_clicked_signal_names", ("record_clicked",))

    def _selection_button_signal_for(self, list_widget):
        return self._resolve_signal(list_widget, "list_selection_button_signal_names", ("selection_button_clicked",))

    def _blank_area_signal_for(self, list_widget):
        return self._resolve_signal(list_widget, "list_blank_area_signal_names", ("blank_area_clicked",))

    def _selection_signal_for(self, list_widget):
        return self._resolve_signal(
            list_widget,
            "list_selection_state_signal_names",
            ("selection_state_changed", "selection_changed"),
        )

    def _set_external_selection_handler_enabled(self, list_widget, enabled: bool) -> None:
        method = self._resolve_callable(
            list_widget,
            "list_external_selection_handler_method_names",
            ("set_external_selection_handler_enabled",),
        )
        if method is None:
            return
        try:
            method(bool(enabled))
        except Exception:
            return

    def _disconnect_list_signals(self, list_widget) -> None:
        if list_widget is None or not self._auto_wire_list_signals:
            return
        record_signal = self._record_clicked_signal_for(list_widget)
        if record_signal is not None:
            try:
                record_signal.disconnect(self.handle_record_clicked)
            except Exception:
                pass
        select_signal = self._selection_button_signal_for(list_widget)
        if select_signal is not None:
            try:
                select_signal.disconnect(self.handle_select_button_clicked)
            except Exception:
                pass
        blank_signal = self._blank_area_signal_for(list_widget)
        if blank_signal is not None:
            try:
                blank_signal.disconnect(self.handle_blank_area_clicked)
            except Exception:
                pass
        selection_signal = self._selection_signal_for(list_widget)
        if selection_signal is not None:
            try:
                selection_signal.disconnect(self.handle_selection_changed)
            except Exception:
                pass
        try:
            self._set_external_selection_handler_enabled(list_widget, False)
        except Exception:
            pass

    def _connect_list_signals(self, list_widget) -> None:
        if list_widget is None or not self._auto_wire_list_signals:
            return
        record_signal = self._record_clicked_signal_for(list_widget)
        if record_signal is not None:
            try:
                record_signal.connect(self.handle_record_clicked)
            except Exception:
                pass
        select_signal = self._selection_button_signal_for(list_widget)
        if select_signal is not None:
            try:
                select_signal.connect(self.handle_select_button_clicked)
            except Exception:
                pass
        blank_signal = self._blank_area_signal_for(list_widget)
        if blank_signal is not None:
            try:
                blank_signal.connect(self.handle_blank_area_clicked)
            except Exception:
                pass
        selection_signal = self._selection_signal_for(list_widget)
        if selection_signal is not None:
            try:
                selection_signal.connect(self.handle_selection_changed)
            except Exception:
                pass
        try:
            self._set_external_selection_handler_enabled(list_widget, True)
        except Exception:
            pass

    def bind_list_widget(self, list_widget) -> None:
        if list_widget is self.list_widget:
            return
        previous = self.list_widget
        self._disconnect_list_signals(previous)
        self.list_widget = list_widget
        self._selection_signal = self._selection_signal_for(self.list_widget)
        self._connect_list_signals(self.list_widget)

    def _mode(self) -> str:
        try:
            value = str(self.adapter.get_mode() or "").strip().lower()
        except Exception:
            value = ""
        return value if value in {"new", "edit", "bulk"} else "edit"

    def _set_mode(self, mode: str) -> None:
        mode_key = str(mode or "").strip().lower()
        if mode_key not in {"new", "edit", "bulk"}:
            mode_key = "edit"
        try:
            self.adapter.set_mode(mode_key)
        except Exception:
            return

    def _active_key(self) -> str:
        try:
            return str(self.adapter.get_active_key() or "").strip()
        except Exception:
            return ""

    def _selected_count(self) -> int:
        try:
            return max(0, int(self.adapter.get_selected_count() or 0))
        except Exception:
            return 0

    def _panel_id_for_mode(self, mode: str) -> str | None:
        mode_key = str(mode or "").strip().lower()
        if mode_key == "new":
            return self._new_panel_id
        if mode_key == "bulk":
            return self._bulk_panel_id
        return self._edit_panel_id

    def _open_panel(self) -> None:
        try:
            self.adapter.open_panel(self.shell)
        finally:
            self.sync_state()

    def _close_panel(self, *, clear_active: bool) -> None:
        if clear_active:
            self._clear_active()
        try:
            self.adapter.close_panel(self.shell)
        finally:
            self.sync_state()

    def _clear_active(self) -> None:
        try:
            self.adapter.clear_active()
        except Exception:
            return

    def _clicked_record_matches_active(self, record, key: str) -> bool:
        list_widget = self.list_widget
        if list_widget is not None:
            pre_click_matcher = getattr(list_widget, "take_pre_click_active_match", None)
            if callable(pre_click_matcher):
                try:
                    pre_click_match = pre_click_matcher(record)
                except Exception:
                    pre_click_match = None
                if pre_click_match is not None:
                    return bool(pre_click_match)
            matcher = getattr(list_widget, "is_active_record", None)
            if callable(matcher):
                try:
                    return bool(matcher(record))
                except Exception:
                    pass
        return bool(key) and key == self._active_key()

    def left_guidance_message(self) -> str:
        if not self.shell.is_left_panel_open():
            return ""
        mode = self._mode()
        if mode == "edit" and not self._active_key():
            try:
                return str(self.adapter.edit_guidance_message() or "")
            except Exception:
                return ""
        if mode == "bulk" and self._selected_count() <= 0:
            try:
                return str(self.adapter.bulk_guidance_message() or "")
            except Exception:
                return ""
        return ""

    def sync_state(self) -> None:
        mode = self._mode()
        panel_open = self.shell.is_left_panel_open()
        active_panel = self._panel_id_for_mode(mode) if panel_open else None
        edit_needs_guidance = panel_open and mode == "edit" and not self._active_key()
        bulk_needs_guidance = panel_open and mode == "bulk" and self._selected_count() <= 0
        self.shell.sync_sidebar_active(active_panel)
        self.shell.set_left_highlight_enabled(edit_needs_guidance or bulk_needs_guidance)
        self.shell.set_right_guidance_enabled(edit_needs_guidance)
        try:
            self.adapter.set_select_button_guide_enabled(bulk_needs_guidance)
        except Exception:
            pass
        try:
            self.adapter.on_state_changed()
        except Exception:
            return

    def handle_panel_sidebar_toggled(self, panel_id: str, active: bool) -> None:
        panel_key = str(panel_id or "").strip()
        if panel_key not in {self._new_panel_id, self._edit_panel_id, self._bulk_panel_id}:
            return
        if not active:
            clear_active = self._clear_active_on_close and self._mode() in {"new", "edit"}
            self._close_panel(clear_active=clear_active)
            return
        if panel_key == self._new_panel_id:
            self._set_mode("new")
            try:
                self.adapter.prepare_new()
            except Exception:
                pass
            self._open_panel()
            return
        if panel_key == self._bulk_panel_id:
            self._set_mode("bulk")
            self._open_panel()
            return
        self._set_mode("edit")
        if not self._active_key():
            try:
                self.adapter.edit_without_active()
            except Exception:
                pass
        self._open_panel()

    def handle_record_clicked(self, record, *_args) -> None:
        try:
            key = str(self.adapter.get_record_key(record) or "").strip()
        except Exception:
            key = ""
        if not key:
            return
        if self._mode() == "edit" and self.shell.is_left_panel_open() and self._clicked_record_matches_active(record, key):
            self._close_panel(clear_active=True)
            return
        self._set_mode("edit")
        try:
            self.adapter.activate_record(record)
        except Exception:
            pass
        self._open_panel()

    def handle_blank_area_clicked(self, *_args) -> None:
        if not self.shell.is_left_panel_open():
            return
        clear_active = self._mode() in {"new", "edit"}
        self._close_panel(clear_active=clear_active)

    def handle_select_button_clicked(self, record, selected: bool) -> None:
        try:
            self.adapter.apply_selection(record, bool(selected))
        except Exception:
            pass
        count = self._selected_count()
        if count <= 0:
            if self._mode() == "bulk" and self.shell.is_left_panel_open():
                self._close_panel(clear_active=False)
            else:
                self.sync_state()
            return
        if self._bulk_panel_id is None:
            self.sync_state()
            return
        self._set_mode("bulk")
        self._open_panel()

    def handle_selection_changed(self, *_args) -> None:
        count = self._selected_count()
        if count <= 0:
            if self._mode() == "bulk" and self.shell.is_left_panel_open():
                self._close_panel(clear_active=False)
            else:
                self.sync_state()
            return
        if self._bulk_panel_id is None:
            self.sync_state()
            return
        self._set_mode("bulk")
        self._open_panel()


__all__ = [
    "AnimatedGuidanceRing",
    "compose_record_workspace_style",
    "EditLockOverlay",
    "RECORD_WORKSPACE_STYLE",
    "RecordWorkspaceBehaviorAdapter",
    "RecordWorkspaceBehaviorController",
    "RecordWorkspaceCardRecord",
    "RecordWorkspaceFooterBar",
    "RecordWorkspaceListDelegate",
    "RecordWorkspaceListModel",
    "RecordWorkspaceListWidget",
    "RecordWorkspaceScaffold",
    "RecordWorkspaceSectionCard",
    "RecordWorkspaceSplitShell",
]
